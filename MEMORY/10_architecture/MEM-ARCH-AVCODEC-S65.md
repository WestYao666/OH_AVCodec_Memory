---
id: MEM-ARCH-AVCODEC-S65
title: MediaMuxer 封装核心实现——Track 管理器与 AVBufferQueue 异步写入架构
status: approved
approved_at: "2026-05-06"
scope: [AVCodec, MediaMuxer, MuxerPlugin, Track, AVBufferQueue, DataSink, OutputFormat, ThreadProcessor, PTS, AsyncMode]
created_by: builder-agent
created_at: 2026-04-27T07:10:00+08:00
evidence_count: 15
---

## 摘要

MediaMuxer 是 OH AVCodec 封装层的**核心 orchestrator（编排器）**，位于 `services/media_engine/modules/muxer/media_muxer.cpp`（571行）和 `media_muxer.h`（106行）。它不负责具体的容器格式编码，而是管理多个 Track（音视频轨）的生命周期，通过 **AVBufferQueue** 接收编码后的样本，按 **PTS 排序** 后将数据写入 MuxerPlugin（实际容器格式处理器）。与 S40（FFmpegMuxerPlugin）互补：S40 聚焦 FFmpeg 底层封装，S65 聚焦 MediaMuxer 编排层。

**定位关系**：
```
MuxerFilter（Filter层） → MediaMuxer（Track管理+异步写入） → MuxerPlugin（FFmpegMuxerPlugin等，具体容器格式）
                    ↑ AVBufferQueue 生产-消费
```

---

## 关键发现（带证据）

### 1. MediaMuxer 四状态机

MediaMuxer 有独立的状态机（UNINITIALIZED → INITIALIZED → STARTED → STOPPED），与 CodecBase/AVCodecServer 状态机独立：

```cpp
// media_muxer.h:57-60
enum class State {
    UNINITIALIZED,
    INITIALIZED,
    STARTED,
    STOPPED
};
std::atomic<State> state_ = State::UNINITIALIZED;
```

状态转换规则（`media_muxer.cpp`）：
- `Init(fd/FILE, format)` → UNINITIALIZED → INITIALIZED（同时创建 MuxerPlugin）
- `AddTrack()` → 在 INITIALIZED 状态下调用
- `Start()` → INITIALIZED → STARTED（启动 OS_MUXER_WRITE 线程：`media_muxer.cpp:295-303`）
- `Stop()` → STARTED → STOPPED
- `Reset()` → 返回 UNINITIALIZED

### 2. Track 内部类：每个轨一个 AVBufferQueue

MediaMuxer::Track 是内部类，每个 Track 管理一个独立的 AVBufferQueue：

```cpp
// media_muxer.h:82-93
class Track : public IConsumerListener {
public:
    int32_t trackId_ = -1;
    std::string mimeType_ = {};
    std::shared_ptr<Meta> trackDesc_ = nullptr;
    sptr<AVBufferQueueProducer> producer_ = nullptr;  // 给 MuxerFilter 用
    sptr<AVBufferQueueConsumer> consumer_ = nullptr;  // MediaMuxer 内部用
    std::shared_ptr<AVBufferQueue> bufferQ_ = nullptr;
    std::shared_ptr<AVBuffer> curBuffer_ = nullptr;
    uint64_t writeCount_ = 0;
    std::atomic<int32_t> bufferAvailableCount_ = 0;  // 消费者计数
};
```

Track 通过 `SetBufferAvailableListener(MediaMuxer* listener)` 注册自身为缓冲区可用监听器。外部（MuxerFilter）通过 `GetInputBufferQueue(trackIndex)` 获取 AVBufferQueueProducer 写入数据，内部 MediaMuxer 通过 Track 的 consumer 消费数据。

### 3. CreatePlugin：OutputFormat → MimeType → Plugin 路由

```cpp
// media_muxer.cpp:456-478
std::shared_ptr<Plugins::MuxerPlugin> MediaMuxer::CreatePlugin(Plugins::OutputFormat format)
{
    static const std::unordered_map<Plugins::OutputFormat, std::string> table = {
        {Plugins::OutputFormat::DEFAULT, MimeType::MEDIA_MP4},
        {Plugins::OutputFormat::MPEG_4,  MimeType::MEDIA_MP4},
        {Plugins::OutputFormat::M4A,     MimeType::MEDIA_M4A},
        {Plugins::OutputFormat::AMR,     MimeType::MEDIA_AMR},
        {Plugins::OutputFormat::MP3,      MimeType::MEDIA_MP3},
        {Plugins::OutputFormat::WAV,      MimeType::MEDIA_WAV},
        {Plugins::OutputFormat::AAC,      MimeType::MEDIA_AAC},
        {Plugins::OutputFormat::FLAC,      MimeType::MEDIA_FLAC},
        {Plugins::OutputFormat::OGG,       MimeType::MEDIA_OGG},
        {Plugins::OutputFormat::FLV,       MimeType::MEDIA_FLV},
    };
    auto plugin = Plugins::PluginManagerV2::Instance().CreatePluginByMime(
        Plugins::PluginType::MUXER, table.at(format));
    return std::reinterpret_pointer_cast<Plugins::MuxerPlugin>(plugin);
}
```

路由链：OutputFormat（枚举）→ MimeType 字符串 → `PluginManagerV2::CreatePluginByMime`（dlopen 加载具体插件）。

### 4. CanAddTrack：MUX_FORMAT_INFO 白名单校验

```cpp
// media_muxer.cpp:44-62
const std::unordered_map<OutputFormat, std::set<std::string>> MUX_FORMAT_INFO = {
    {OutputFormat::MPEG_4, {MimeType::AUDIO_MPEG, MimeType::AUDIO_AAC, /* video types */}},
    {OutputFormat::M4A,     {MimeType::AUDIO_AAC}},
    {OutputFormat::AMR,    {MimeType::AUDIO_AMR_NB, MimeType::AUDIO_AMR_WB}},
    // ...
};
```

每种 OutputFormat 限制了允许的 MimeType 类型集合，CanAddTrack 在 AddTrack 之前做格式兼容性校验（`media_muxer.cpp:481-486`）。

### 5. ThreadProcessor：PTS 排序的异步写入循环

```cpp
// media_muxer.cpp:365-403
void MediaMuxer::ThreadProcessor()
{
    constexpr int32_t timeoutMs = 500;  // 500ms 超时唤醒检查退出
    pthread_setname_np(pthread_self(), threadName_.substr(0, 15).c_str());
    int32_t trackCount = static_cast<int32_t>(tracks_.size());
    for (;;) {
        // 等待缓冲区可用（条件变量 + 500ms timeout）
        std::unique_lock<std::mutex> lock(mutexBufferAvailable_);
        condBufferAvailable_.wait_for(lock, std::chrono::milliseconds(timeoutMs),
            [this] { return isThreadExit_ || bufferAvailableCount_ > 0; });

        // 从所有 Track 中选择 PTS 最小的 buffer
        std::shared_ptr<AVBuffer> buffer1 = nullptr;
        for (int i = 0; i < trackCount; ++i) {
            std::shared_ptr<AVBuffer> buffer2 = tracks_[i]->GetBuffer();
            if ((buffer1 != nullptr && buffer2 != nullptr && buffer1->pts_ > buffer2->pts_) ||
                (buffer1 == nullptr && buffer2 != nullptr)) {
                buffer1 = buffer2;
                trackIdx = i;
            }
        }
        // PTS 排序写人，保证音视频交织顺序正确
        if (buffer1 != nullptr) {
            muxer_->WriteSample(tracks_[trackIdx]->trackId_, tracks_[trackIdx]->curBuffer_);
            tracks_[trackIdx]->ReleaseBuffer();
        }
    }
}
```

核心机制：每次从所有 Track 的当前 buffer 中选 PTS 最小的进行写入，保证容器中样本的时序正确性。

### 6. 双模式数据输入：AVBufferQueue vs WriteSample

MediaMuxer 支持两种数据输入方式：

1. **AVBufferQueue 模式**（推荐，异步）：
   - `GetInputBufferQueue(trackIndex)` → 返回 `sptr<AVBufferQueueProducer>`
   - 外部（MuxerFilter）通过 `AVBufferQueueProducer::PushBuffer` 写入
   - MediaMuxer 通过 Track consumer 消费

2. **WriteSample 模式**（直接调用）：
   - `WriteSample(trackIndex, sample)` → 直接调用 `muxer_->WriteSample()`
   - 绕过 AVBufferQueue，直接同步写入

### 7. DataSink 双实现：Fd vs FILE*

```cpp
// media_muxer.cpp:113-137
Status MediaMuxer::Init(int32_t fd, Plugins::OutputFormat format)
{
    muxer_ = CreatePlugin(format_);
    muxer_->SetCallback(this);
    return muxer_->SetDataSink(std::make_shared<DataSinkFd>(fd));  // 文件描述符
}

Status MediaMuxer::Init(FILE *file, Plugins::OutputFormat format)
{
    muxer_->SetDataSink(std::make_shared<DataSinkFile>(file));  // FILE 指针
}
```

DataSink 是 MuxerPlugin 的输出抽象层，Fd 路径用于生产环境（支持云端录制），FILE 路径用于本地文件。

### 8. OnEvent 回调：Plugins::Callback 接口

```cpp
// media_muxer.h:48
class MediaMuxer : public Plugins::Callback {
public:
    void OnEvent(const Plugins::PluginEvent &event) override;
};
```

MediaMuxer 继承 Plugins::Callback，可接收 MuxerPlugin 的事件回调（如 FLV 插件的文件完成事件）。

---

## 关联记忆

| 关联 | 说明 |
|------|------|
| S40 | FFmpegMuxerPlugin 底层容器格式插件，九种格式（mp4/flv/mp3等） |
| S34 | MuxerFilter Filter 层入口，调用 MediaMuxer::GetInputBufferQueue |
| S52 | PTS 与帧索引转换，MediaMuxer ThreadProcessor 依赖 PTS 排序 |
| S64 | AVBuffer Signal/Wait 机制，MediaMuxer Track 的 AVBufferQueue 消费驱动 |
| S24/S36 | AudioEncoderFilter / VideoEncoderFilter 输出样本给 MuxerFilter |

---

## 架构总结

```
MuxerFilter
  ├─ GetInputBufferQueue(trackIndex) → AVBufferQueueProducer
  └─ AddTrack(meta) → MediaMuxer::AddTrack

MediaMuxer (Track 管理 + 异步写入编排)
  ├─ Track[0..N] (每个轨一个)
  │    ├─ AVBufferQueueProducer (给 MuxerFilter 写)
  │    └─ AVBufferQueueConsumer (MediaMuxer 自己消费)
  ├─ CreatePlugin(OutputFormat) → MuxerPlugin
  ├─ OS_MUXER_WRITE 线程
  │    └─ ThreadProcessor(): PTS 排序写入
  └─ DataSink (Fd 或 FILE*)

MuxerPlugin (FFmpegMuxerPlugin / 其他插件)
  └─ WriteSample(trackId, buffer)
       └─ 容器格式编码（MP4/FLV/MKV...）
```
