# MEM-ARCH-AVCODEC-S99: MediaMuxer Track Management and AVBufferQueue Architecture

**Topic**: MediaMuxer Module Track Management and AVBufferQueue Async Write Architecture  
**Scope**: AVCodec, MediaMuxer, Track Management, AVBufferQueue, AsyncMode, MultiTrack  
**Associated Scenes**: 新需求开发 / 问题定位  
**Status**: approved  
**Created**: 2026-05-08  
**Source**: /home/west/av_codec_repo/services/media_engine/modules/muxer/media_muxer.{h,cpp}

---

## 1. 架构定位

`MediaMuxer` 是媒体封装模块的**核心引擎类**，位于 Filter 管线（MuxerFilter，S34/S65）和 MuxerPlugin 插件（FFmpegMuxerPlugin S40 / Mpeg4MuxerPlugin S91）之间，承担**Track 管理层 + AVBufferQueue 异步写入调度层**双重职责。

三层封装关系：
```
MuxerFilter（S34/S65 Filter层）
  → MediaMuxer（模块层，S99）  ← 本文档
    → FFmpegMuxerPlugin / Mpeg4MuxerPlugin（S40/S91 插件层）
```

**与已有 S-series 的互补关系**：
- S40：FFmpegMuxerPlugin 底层九格式封装（mp4/m4a/mp3/wav/aac/flac/ogg/flv/amr）
- S65：MediaMuxer Filter 层封装（preFilterCount_ 多轨协调，maxDuration_ 异步停止）
- S91：Mpeg4MuxerPlugin Box 写时构建（BasicBox 树 / BoxParser）
- **S99（本文档**：MediaMuxer 模块层内部 Track 管理、AVBufferQueue 集成、ThreadProcessor 调度）

---

## 2. 类层级架构

### 2.1 MediaMuxer 主类

```cpp
// media_muxer.h:30
class MediaMuxer : public Plugins::Callback {
public:
    MediaMuxer(int32_t appUid, int32_t appPid);
    virtual ~MediaMuxer();
    virtual Status Init(int32_t fd, Plugins::OutputFormat format);      // fd 初始化
    virtual Status Init(FILE *file, Plugins::OutputFormat format);        // FILE 初始化
    virtual Status SetParameter(const std::shared_ptr<Meta> &param);
    virtual Status SetUserMeta(const std::shared_ptr<Meta> &userMeta);
    virtual Status AddTrack(int32_t &trackIndex, const std::shared_ptr<Meta> &trackDesc);
    virtual sptr<AVBufferQueueProducer> GetInputBufferQueue(uint32_t trackIndex); // ← AVBufferQueue 模式
    virtual Status Start();
    virtual Status WriteSample(uint32_t trackIndex, const std::shared_ptr<AVBuffer> &sample); // ← 直接写模式
    virtual Status Stop();
    virtual Status Reset();
    void OnEvent(const Plugins::PluginEvent &event) override;

private:
    enum class State { UNINITIALIZED, INITIALIZED, STARTED, STOPPED };
    std::shared_ptr<Plugins::MuxerPlugin> CreatePlugin(Plugins::OutputFormat format);
    void StartThread(const std::string &name);
    void StopThread();
    void ThreadProcessor();          // ← 专用写入线程
    void OnBufferAvailable();        // ← 消费者回调
    bool CanAddTrack(const std::string &mimeType);
    std::string StateConvert(State state);
    class Track;                    // ← 内部 Track 类
    std::atomic<State> state_ = State::UNINITIALIZED;
    std::shared_ptr<Plugins::MuxerPlugin> muxer_;
    std::vector<sptr<Track>> tracks_;
    std::unique_ptr<std::thread> thread_;
    std::mutex mutex_;
    std::mutex mutexBufferAvailable_;
    std::condition_variable condBufferAvailable_;
    std::atomic<bool> isThreadExit_ = true;
    int32_t appUid_ = -1;
    int32_t appPid_ = -1;
};
```

### 2.2 内部 Track 类

```cpp
// media_muxer.h:67-93
class MediaMuxer::Track : public IConsumerListener {
public:
    Track() {};
    virtual ~Track();
    std::shared_ptr<AVBuffer> GetBuffer();           // 从 AVBufferQueue 取下一个 buffer
    void ReleaseBuffer();                             // 归还 buffer 到队列
    void SetBufferAvailableListener(MediaMuxer *listener);
    void OnBufferAvailable() override;                // IConsumerListener 回调

private:
    int32_t trackId_ = -1;
    int32_t trackIndex_ = -1;
    int64_t startPts_ = 0;
    sptr<AVBufferQueueProducer> producer_ = nullptr; // 生产者端
    sptr<AVBufferQueueConsumer> consumer_ = nullptr; // 消费者端
    std::shared_ptr<AVBufferQueue> bufferQ_ = nullptr;
    std::shared_ptr<AVBuffer> curBuffer_ = nullptr;   // 当前持有的 buffer
    int64_t writeCount_ = 0;
};
```

**关键发现**：Track 类通过 `IConsumerListener` 接口监听 AVBufferQueue 的 buffer 可用事件，当有数据到达时触发 `OnBufferAvailable` 回调通知 MediaMuxer 的写入线程。

---

## 3. State Machine

```
UNINITIALIZED
    ↓ Init() [fd or FILE]
INITIALIZED
    ↓ AddTrack() [可多次调用]
    ↓ GetInputBufferQueue() [AVBufferQueue 模式可选]
    ↓ Start()
STARTED
    ↓ [ThreadProcessor 持续消费 AVBufferQueue]
    ↓ Stop()
STOPPED
    ↓ Reset()
UNINITIALIZED
```

**状态校验约束**（media_muxer.cpp）：
- `AddTrack`：仅限 `INITIALIZED` 状态（line 197）
- `GetInputBufferQueue`：仅限 `INITIALIZED` 状态，且在 `AddTrack()` 之后、`Start()` 之前（line 232）
- `WriteSample`：仅限 `STARTED` 状态（line 243）
- `Start`：仅限 `INITIALIZED` 状态（line 279）
- `Stop`：仅限 `STARTED` 状态（line 316）

---

## 4. 双模式数据输入

MediaMuxer 支持两种数据输入模式，互斥选择：

### 4.1 AVBufferQueue 模式（异步管道模式）

```cpp
// media_muxer.cpp:228-238
sptr<AVBufferQueueProducer> MediaMuxer::GetInputBufferQueue(uint32_t trackIndex)
{
    MEDIA_LOG_I("GetInputBufferQueue");
    FALSE_RETURN_V_MSG_E(state_ == State::INITIALIZED, nullptr,
        "The state is not INITIALIZED, the interface must be called after AddTrack() "
        "and before Start(). The current state is %{public}s.", StateConvert(state_).c_str());
    FALSE_RETURN_V_MSG_E(trackIndex < tracks_.size(), nullptr,
        "The track index does not exist, the interface must be called after AddTrack() "
        "and before Start().");
    return tracks_[trackIndex]->producer_;
}
```

调用链：`MuxerFilter` → `MediaMuxer::GetInputBufferQueue(trackIndex)` → 返回 `AVBufferQueueProducer` → `MuxerFilter` 通过 `Producer` 写入 AVBuffer → `Track::OnBufferAvailable()` 触发 → `ThreadProcessor` 消费

### 4.2 WriteSample 模式（直接同步写入）

```cpp
// media_muxer.cpp:240-249
Status MediaMuxer::WriteSample(uint32_t trackIndex, const std::shared_ptr<AVBuffer> &sample)
{
    FALSE_RETURN_V_MSG_E(state_ == State::STARTED, Status::ERROR_WRONG_STATE,
        "The state is not STARTED", StateConvert(state_).c_str());
    FALSE_RETURN_V_MSG_E(trackIndex < tracks_.size(), Status::ERROR_INVALID_PARAMETER,
        "The track index does not exist.");
    MEDIA_LOG_D("WriteSample track:" PUBLIC_LOG_U32 ", pts:" PUBLIC_LOG_D64 ", size:" PUBLIC_LOG_D32,
        trackIndex, sample->pts_, sample->buf_->GetSize());
    return muxer_->WriteSample(tracks_[trackIndex]->trackId_, sample);
}
```

**对比**：

| 特性 | AVBufferQueue 模式 | WriteSample 模式 |
|------|-------------------|-----------------|
| 同步方式 | 异步（TaskThread 驱动） | 同步（调用方阻塞） |
| 适用场景 | 管线 Filter 协作 | 外部直接写入 |
| PTS 排序 | ThreadProcessor 内自动排序 | 调用方保证顺序 |
| 背压控制 | AVBufferQueue 水位线控制 | 调用方自行处理 |

---

## 5. ThreadProcessor 异步写入调度

```cpp
// media_muxer.cpp:365-407
void MediaMuxer::ThreadProcessor()
{
    MEDIA_LOG_D("Enter ThreadProcessor [%{public}s]", threadName_.c_str());
    constexpr int32_t timeoutMs = 500;
    constexpr uint32_t nameSizeMax = 15;
    pthread_setname_np(pthread_self(), threadName_.substr(0, nameSizeMax).c_str());
    int32_t trackCount = static_cast<int32_t>(tracks_.size());

    for (;;) {
        if (isThreadExit_ && bufferAvailableCount_ <= 0) {
            MEDIA_LOG_D("Exit ThreadProcessor [%{public}s]", threadName_.c_str());
            return;
        }
        {
            std::unique_lock<std::mutex> lock(mutexBufferAvailable_);
            condBufferAvailable_.wait_for(lock, std::chrono::milliseconds(timeoutMs),
                [this] { return isThreadExit_ || bufferAvailableCount_ > 0; });
        }
        // 多轨 PTS 排序：选择所有轨中 pts 最小的 buffer 优先写入
        int32_t trackIdx = -1;
        std::shared_ptr<AVBuffer> buffer1 = nullptr;
        for (int i = 0; i < trackCount; ++i) {
            std::shared_ptr<AVBuffer> buffer2 = tracks_[i]->GetBuffer();
            if ((buffer1 != nullptr && buffer2 != nullptr && buffer1->pts_ > buffer2->pts_) ||
                (buffer1 == nullptr && buffer2 != nullptr)) {
                buffer1 = buffer2;
                trackIdx = i;
            }
        }
        if (buffer1 != nullptr) {
            muxer_->WriteSample(tracks_[trackIdx]->trackId_, tracks_[trackIdx]->curBuffer_);
            tracks_[trackIdx]->ReleaseBuffer();
            tracks_[trackIdx]->writeCount_++;
        }
    }
}
```

**核心调度算法**（line 393-399）：
- 遍历所有 track，从各 `Track::bufferQ_` 取队首 buffer
- 选择 **pts 最小的 buffer** 优先写入（保证多轨 AV 同步）
- 写入后 `ReleaseBuffer()` 归还队列，继续下一轮

**启动条件**（line 303）：
```cpp
thread_ = std::make_unique<std::thread>(&MediaMuxer::ThreadProcessor, this);
```

---

## 6. Track::OnBufferAvailable 回调链

```cpp
// media_muxer.cpp:446-452
void MediaMuxer::Track::OnBufferAvailable()
{
    if (listener_ != nullptr) {
        listener_->OnBufferAvailable();
        return;
    }
}

// media_muzer.cpp:402-408
void MediaMuxer::OnBufferAvailable()
{
    // 通知 ThreadProcessor 有新的 buffer 可用
    std::lock_guard<std::mutex> lock(mutexBufferAvailable_);
    bufferAvailableCount_++;
    condBufferAvailable_.notify_all();
}
```

完整信号链：
```
AVBufferQueue 写入（Producer）
  → Track::OnBufferAvailable() [IConsumerListener 回调]
    → MediaMuxer::OnBufferAvailable()
      → bufferAvailableCount_++ && condBufferAvailable_.notify_all()
        → ThreadProcessor 被唤醒，从各 track 队列取 buffer 写入
```

---

## 7. Format/MIME 路由表

### 7.1 MUX_FORMAT_INFO（输出格式 → 支持的 MIME 类型）

```cpp
// media_muxer.cpp:48-62
const std::unordered_map<OutputFormat, std::set<std::string>> MUX_FORMAT_INFO = {
    {OutputFormat::MPEG_4, {MimeType::AUDIO_MPEG, MimeType::AUDIO_AAC,
        MimeType::VIDEO_AVC, MimeType::VIDEO_MPEG4, MimeType::VIDEO_HEVC,
        MimeType::IMAGE_JPG, MimeType::IMAGE_PNG,
        MimeType::IMAGE_BMP, MimeType::TIMED_METADATA}},  // ← 支持图片轨和 timed metadata 轨
    {OutputFormat::M4A, {MimeType::AUDIO_AAC, MimeType::IMAGE_JPG, MimeType::IMAGE_PNG, MimeType::IMAGE_BMP}},
    {OutputFormat::AMR, {MimeType::AUDIO_AMR_NB, MimeType::AUDIO_AMR_WB}},
    {OutputFormat::MP3, {MimeType::AUDIO_MPEG, MimeType::IMAGE_JPG}},
    {OutputFormat::WAV, {MimeType::AUDIO_RAW, MimeType::AUDIO_G711MU}},
    {OutputFormat::AAC, {MimeType::AUDIO_AAC}},
    {OutputFormat::FLAC, {MimeType::AUDIO_FLAC, MimeType::IMAGE_JPG, MimeType::IMAGE_PNG, MimeType::IMAGE_BMP}},
    {OutputFormat::OGG, {MimeType::AUDIO_OPUS, MimeType::AUDIO_VORBIS}},
    {OutputFormat::FLV, {MimeType::AUDIO_AAC, MimeType::AUDIO_AVS3DA,
        MimeType::VIDEO_AVC, MimeType::VIDEO_HEVC}},
};
```

### 7.2 MUX_MIME_INFO（MIME 类型 → 必需元数据标签）

```cpp
// media_muxer.cpp:64-80
const std::map<std::string, std::set<std::string>> MUX_MIME_INFO = {
    {MimeType::AUDIO_OPUS, {Tag::AUDIO_SAMPLE_RATE, Tag::AUDIO_CHANNEL_COUNT, Tag::MEDIA_CODEC_CONFIG}},
    {MimeType::AUDIO_VORBIS, {Tag::AUDIO_SAMPLE_RATE, Tag::AUDIO_CHANNEL_COUNT, Tag::MEDIA_CODEC_CONFIG}},
    {MimeType::VIDEO_AVC, {Tag::VIDEO_WIDTH, Tag::VIDEO_HEIGHT}},
    {MimeType::VIDEO_HEVC, {Tag::VIDEO_WIDTH, Tag::VIDEO_HEIGHT}},
    {MimeType::IMAGE_JPG, {Tag::VIDEO_WIDTH, Tag::VIDEO_HEIGHT}},
    {MimeType::TIMED_METADATA, {Tag::TIMED_METADATA_KEY, Tag::TIMED_METADATA_SRC_TRACK}},
};
```

**关键发现**：
- `TIMED_METADATA`：支持 HLS `EXT-X-DATERANGE` interstitial 事件轨道，映射到 `TIMED_METADATA_KEY` 和 `TIMED_METADATA_SRC_TRACK`
- `IMAGE_JPG/PNG/BMP`：支持图片轨嵌入（封面、缩略图）
- `AUDIO_OPUS/AUDIO_VORBIS`：需要 `MEDIA_CODEC_CONFIG`（编码器配置参数）
- `MUX_AUXILIARY_TRACK_INFO`（line 83）：支持参考轨 `REFERENCE_TRACK_IDS` 和 `TRACK_DESCRIPTION`

---

## 8. AddTrack 流程

```cpp
// media_muxer.cpp:192-216
Status MediaMuxer::AddTrack(int32_t &trackIndex, const std::shared_ptr<Meta> &trackDesc)
{
    MEDIA_LOG_I("AddTrack");
    FALSE_RETURN_V_MSG_E(state_ == State::INITIALIZED, Status::ERROR_WRONG_STATE,
        "The state is not INITIALIZED.");
    FALSE_RETURN_V_MSG_E(CanAddTrack(mimeType), Status::ERROR_UNSUPPORTED_FORMAT,
        "MIME type is not supported.");
    auto track = sptr<Track>(new Track());
    int32_t trackId = muxer_->AddTrack(trackId, trackDesc);  // 委托插件添加轨道
    track->trackId_ = trackId;
    track->trackIndex_ = static_cast<int32_t>(tracks_.size());
    tracks_.push_back(track);
    trackIndex = track->trackIndex_;
    MEDIA_LOG_I("AddTrack succ, trackId: %{public}d, mime: %{public}s", trackId, mimeType.c_str());
    return Status::NO_ERROR;
}
```

`CanAddTrack` 基于 `MUX_FORMAT_INFO` 校验 MIME 类型是否在当前 OutputFormat 支持范围内。

---

## 9. 关键 evidence 汇总

| # | 文件 | 行号 | 核心发现 |
|---|------|------|---------|
| 1 | media_muxer.h | 30 | MediaMuxer 主类定义，继承 Plugins::Callback |
| 2 | media_muxer.h | 47 | State 枚举：UNINITIALIZED → INITIALIZED → STARTED → STOPPED |
| 3 | media_muxer.h | 67 | Track 内部类定义（IConsumerListener 实现） |
| 4 | media_muxer.h | 80-83 | Track 的三 queue：producer_/consumer_/bufferQ_ |
| 5 | media_muxer.cpp | 48-62 | MUX_FORMAT_INFO 九格式路由表（含 TIMED_METADATA/IMAGE） |
| 6 | media_muxer.cpp | 64-80 | MUX_MIME_INFO MIME→标签路由表（含 AUDIO_OPUS/VORBIS） |
| 7 | media_muxer.cpp | 117/127 | Init(fd) / Init(FILE*) 状态校验，仅 UNINITIALIZED 可调用 |
| 8 | media_muxer.cpp | 192 | AddTrack 仅限 INITIALIZED 状态 |
| 9 | media_muxer.cpp | 228 | GetInputBufferQueue 返回 AVBufferQueueProducer（异步模式入口） |
| 10 | media_muxer.cpp | 232 | GetInputBufferQueue 约束：AddTrack 之后、Start 之前 |
| 11 | media_muxer.cpp | 240 | WriteSample 直接写入接口（同步模式入口） |
| 12 | media_muxer.cpp | 243 | WriteSample 仅限 STARTED 状态 |
| 13 | media_muxer.cpp | 303 | Start 创建 ThreadProcessor 专用写入线程 |
| 14 | media_muxer.cpp | 365-407 | ThreadProcessor 多轨 PTS 排序写入算法（核心） |
| 15 | media_muxer.cpp | 393-399 | PTS 最小优先写入：保证多轨 AV 同步 |
| 16 | media_muxer.cpp | 402 | OnBufferAvailable：buffer 可用回调 → notify_all |
| 17 | media_muxer.cpp | 417 | Track::GetBuffer：从 AVBufferQueue 取 buffer |
| 18 | media_muxer.cpp | 431 | Track::ReleaseBuffer：归还 buffer 到队列 |
| 19 | media_muxer.cpp | 446-452 | Track::OnBufferAvailable：IConsumerListener 实现 |
| 20 | media_muxer.cpp | 316-332 | Stop 停止 ThreadProcessor → muxer_->Stop() |
| 21 | media_muxer.cpp | 334-360 | StopThread：isThreadExit_ + join() 安全退出 |

---

## 10. 与相邻 S-series 的互补关系

```
┌─────────────────────────────────────────────────────────────────────┐
│                     Filter Pipeline                                  │
│  ┌──────────┐    AVBufferQueue    ┌──────────┐    AVBufferQueue    │
│  │Demuxer   │ ────────────────→  │  Muxer   │ ────────────────→   │
│  │Filter    │                    │  Filter  │                    │
│  │(S41/S75) │                    │(S34/S65)  │                    │
│  └──────────┘                    └────┬─────┘                    │
│                                        │                           │
│                               MediaMuxer::AddTrack()               │
│                               MediaMuxer::GetInputBufferQueue()    │
│                                        │                           │
│                               ┌─────────▼─────────┐                │
│                               │   MediaMuxer     │ ← S99           │
│                               │  (Track Manager  │                │
│                               │  ThreadProcessor │                │
│                               │  State Machine)  │                │
│                               └─────────┬─────────┘                │
│                                         │                          │
│                               MuxerPlugin::WriteSample()           │
│                    ┌───────────────────┼────────────────────┐   │
│           ┌───────▼───────┐    ┌───────▼───────┐    ┌────────▼──────┐
│           │FFmpegMuxer    │    │Mpeg4Muxer     │    │ 其他插件        │
│           │Plugin (S40)   │    │Plugin (S91)   │    │                │
│           └───────────────┘    └───────────────┘    └────────────────┘
```

**S99 与 S65 的区别**：
- S65 是 Filter 层视角，关注 MuxerFilter 如何协调多轨（preFilterCount_、maxDuration_ 异步停止）
- S99 是模块层视角，关注 MediaMuxer 内部的 Track 管理、AVBufferQueue 集成、ThreadProcessor PTS 排序

**S99 与 S40/S91 的区别**：
- S40/S91 是插件层，关注具体的 MP4/FLV/OGG 等格式的封装实现
- S99 是管理层，关注 Track 生命周期、Buffer 队列、多轨调度

---

## 11. 总结

MediaMuxer 模块的核心价值：

1. **Track 抽象**：每条轨道独立管理 producer/consumer/bufferQ，通过 IConsumerListener 监听 buffer 可用事件
2. **双模式输入**：AVBufferQueue 模式（异步管线集成）vs WriteSample 模式（直接同步写入）
3. **ThreadProcessor 调度**：专用写入线程，多轨 PTS 排序，保证 AV 同步
4. **State 保护**：严格状态机约束（UNINITIALIZED→INITIALIZED→STARTED→STOPPED）
5. **Format 路由**：MUX_FORMAT_INFO + MUX_MIME_INFO 双表路由，支持图片轨和 TimedMetadata 轨
