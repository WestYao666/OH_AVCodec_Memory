# MEM-ARCH-AVCODEC-S230 — AudioDataSourceFilter 音频数据源过滤层

| 属性 | 值 |
|------|-----|
| **主题** | AudioDataSourceFilter 音频数据源过滤层——IAudioDataSource抽象接口+Task驱动ReadLoop+AVBufferQueue生产者输出 |
| **scope** | AVCodec, MediaEngine, Filter, AudioSource, IAudioDataSource, Task, ReadLoop, AVBufferQueue |
| **关联场景** | 新需求开发/音频采集接入/录制管线 |
| **状态** | draft |
| **依赖** | S189/S190(AudioCaptureModule), S185(AudioServerSink), S219(SourcePlugin) |
| **关联** | S184(FFmpeg音频解码), S191(OHOS-Native Audio), S193(FFmpeg Audio Encoder) |

---

## 1. 架构概述

AudioDataSourceFilter 是 MediaEngine 录音管线的**音频数据源过滤层**，注册名为 `"builtin.recorder.audiodatasource"`，FilterType 为 `AUDIO_DATA_SOURCE`。

```
IAudioDataSource（外部数据提供者）
    ↓ ReadAt()回调
AudioDataSourceFilter.ReadLoop() — Task 驱动线程
    ↓ PushBuffer()
AVBufferQueueProducer —下游 Filter消费
```

**三层职责**：
1. **数据源抽象层**：通过 `IAudioDataSource` 接口从外部获取音频数据（不直接依赖 AudioCapturer）
2. **异步读取层**：`Task` 驱动 `ReadLoop()` 在独立线程中持续读取
3. **缓冲输出层**：通过 `AVBufferQueueProducer` 将数据传递给管线下游

---

## 2. 关键源码文件

| 文件 | 路径 | 行数 |
|------|------|------|
| audio_data_source_filter.cpp | services/media_engine/filters/ | 343 |
| audio_data_source_filter.h | interfaces/inner_api/native/ | 75 |

---

## 3. Evidence 条目（行号级）

**E1 — AutoRegisterFilter 静态注册**
```cpp
// audio_data_source_filter.cpp L36-40
static AutoRegisterFilter<AudioDataSourceFilter> g_registerAudioDataSourceFilter("builtin.recorder.audiodatasource",
    FilterType::AUDIO_DATA_SOURCE,
    [](const std::string& name, const FilterType type) {
        return std::make_shared<AudioDataSourceFilter>(name, FilterType::AUDIO_DATA_SOURCE);
    });
```
> 注册名称：`builtin.recorder.audiodatasource`；FilterType：`AUDIO_DATA_SOURCE`

---

**E2 — AudioDataSourceFilterLinkCallback 链路回调**
```cpp
// audio_data_source_filter.cpp L32-53
class AudioDataSourceFilterLinkCallback : public FilterLinkCallback {
public:
    explicit AudioDataSourceFilterLinkCallback(std::shared_ptr<AudioDataSourceFilter> audioDataSourceFilter)
        : audioDataSourceFilter_(std::move(audioDataSourceFilter)) { }
    void OnLinkedResult(const sptr<AVBufferQueueProducer> &queue, std::shared_ptr<Meta> &meta) override { ... }
    void OnUnlinkedResult(std::shared_ptr<Meta> &meta) override { ... }
    void OnUpdatedResult(std::shared_ptr<Meta> &meta) override { ... }
private:
    std::weak_ptr<AudioDataSourceFilter> audioDataSourceFilter_;
};
```
> 三路回调（Linked/Unlinked/Updated）；weak_ptr 避免循环引用

---

**E3 — 构造函数**
```cpp
// audio_data_source_filter.cpp L55-57
AudioDataSourceFilter::AudioDataSourceFilter(std::string name, FilterType type): Filter(name, type)
{
    MEDIA_LOG_I("audio data source filter create");
}
```

---

**E4 — Init：Task + ReadLoop 初始化**
```cpp
// audio_data_source_filter.cpp L81-88
void AudioDataSourceFilter::Init(const std::shared_ptr<EventReceiver> &receiver,
    const std::shared_ptr<FilterCallback> &callback)
{
    MEDIA_LOG_I("AudioDataSourceFilter Init");
    receiver_ = receiver;
    callback_ = callback;
    if (!taskPtr_) {
        taskPtr_ = std::make_shared<Task>("DataReader");
        taskPtr_->RegisterJob([this] { ReadLoop(); return 0;});
    }
}
```
> Task 名："DataReader"；Job 绑定 `ReadLoop()`；懒创建模式

---

**E5 — DoPrepare：请求下游 Filter**
```cpp
// audio_data_source_filter.cpp L93-100
Status AudioDataSourceFilter::DoPrepare()
{
    MEDIA_LOG_I("AudioDataSourceFilter DoPrepare");
    if (callback_ == nullptr) {
        MEDIA_LOG_E("callback is nullptr");
        return Status::ERROR_NULL_POINTER;
    }
    callback_->OnCallback(shared_from_this(), FilterCallBackCommand::NEXT_FILTER_NEEDED,
        StreamType::STREAMTYPE_RAW_AUDIO);
    return Status::OK;
}
```
> 请求下游 Filter；StreamType：`STREAMTYPE_RAW_AUDIO`

---

**E6 — DoStart/DoPause/DoResume：Task 启停控制**
```cpp
// audio_data_source_filter.cpp L103-109 (DoStart)
Status AudioDataSourceFilter::DoStart()
{
    MEDIA_LOG_I("AudioDataSourceFilter DoStart");
    eos_ = false;
    if (taskPtr_) { taskPtr_->Start(); }
    return Status::OK;
}

// audio_data_source_filter.cpp L112-118 (DoPause)
Status AudioDataSourceFilter::DoPause()
{
    MEDIA_LOG_I("AudioDataSourceFilter DoPause");
    if (taskPtr_) { taskPtr_->Pause(); }
    return Status::OK;
}

// audio_data_source_filter.cpp L121-124 (DoResume)
Status AudioDataSourceFilter::DoResume()
{
    MEDIA_LOG_I("AudioDataSourceFilter DoResume");
    if (taskPtr_) { taskPtr_->Start(); }
    return Status::OK;
}
```

---

**E7 — DoStop/DoRelease：资源释放**
```cpp
// audio_data_source_filter.cpp L126-133 (DoStop)
Status AudioDataSourceFilter::DoStop()
{
    MEDIA_LOG_I("AudioDataSourceFilter DoStop");
    if (taskPtr_) { taskPtr_->Stop(); }
    return Status::OK;
}

// audio_data_source_filter.cpp L139-146 (DoRelease)
Status AudioDataSourceFilter::DoRelease()
{
    MEDIA_LOG_I("AudioDataSourceFilter DoRelease");
    if (taskPtr_) { taskPtr_->Stop(); }
    taskPtr_ = nullptr;
    audioDataSource_ = nullptr;
    return Status::OK;
}
```

---

**E8 — SetAudioDataSource：数据源注入**
```cpp
// audio_data_source_filter.cpp L177-179
void AudioDataSourceFilter::SetAudioDataSource(const std::shared_ptr<IAudioDataSource>& audioSource)
{
    audioDataSource_ = audioSource;
}
```
> IAudioDataSource 抽象接口注入；外部数据提供者实现 ReadAt()

---

**E9 — SetVideoFirstFramePts：音视频同步**
```cpp
// audio_data_source_filter.cpp L181-186
void AudioDataSourceFilter::SetVideoFirstFramePts(int64_t firstFramePts)
{
    if (audioDataSource_) {
        MEDIA_LOG_I("set firstVideoFramePts: " PUBLIC_LOG_D64, firstFramePts);
        audioDataSource_->SetVideoFirstFramePts(firstFramePts);
    }
}
```
> 录音场景音视频同步：将视频首帧 PTS 传给数据源

---

**E10 — SendEos：发送结束符**
```cpp
// audio_data_source_filter.cpp L190-204
Status AudioDataSourceFilter::SendEos()
{
    MEDIA_LOG_I("AudioDataSourceFilter SendEos");
    Status ret = Status::OK;
    if (outputBufferQueue_) {
        std::shared_ptr<AVBuffer> buffer;
        AVBufferConfig avBufferConfig;
        ret = outputBufferQueue_->RequestBuffer(buffer, avBufferConfig, TIME_OUT_MS);
        if (ret != Status::OK) { return ret; }
        buffer->flag_ |= BUFFER_FLAG_EOS;  // L201: EOS flag = 0x00000001
        outputBufferQueue_->PushBuffer(buffer, false);
    }
    eos_ = true;
    return ret;
}
```
> BUFFER_FLAG_EOS = 0x00000001（L27定义）；非阻塞 Push（第二个参数 false）

---

**E11 — ReadLoop：核心异步读取循环**
```cpp
// audio_data_source_filter.cpp L200-237
void AudioDataSourceFilter::ReadLoop()
{
    MEDIA_LOG_D("AudioDataSourceFilter ReadLoop In");
    if (eos_.load() || audioDataSource_ == nullptr) { return; }
    int64_t bufferSize = 0;
    if (audioDataSource_->GetSize(bufferSize) != 0) {
        MEDIA_LOGE_LIMIT(LOG_LIMIT_HUNDRED, "Get audioCaptureModule buffer size fail");
        return;
    }
    std::shared_ptr<AVBuffer> buffer;
    AVBufferConfig avBufferConfig;
    avBufferConfig.size = bufferSize;
    avBufferConfig.memoryFlag = MemoryFlag::MEMORY_READ_WRITE;
    if (outputBufferQueue_ == nullptr) { return; }
    Status status = outputBufferQueue_->RequestBuffer(buffer, avBufferConfig, TIME_OUT_MS);
    if (status != Status::OK) { return; }
    AudioDataSourceReadAtActionState readAtRet = audioDataSource_->ReadAt(buffer, bufferSize);
    if (readAtRet != AudioDataSourceReadAtActionState::OK) {
        outputBufferQueue_->PushBuffer(buffer, false);
        if (readAtRet == AudioDataSourceReadAtActionState::RETRY_IN_INTERVAL) {
            RelativeSleep(AUDIO_DATASOURCE_FILTER_READ_FAILED_WAIT_TIME); // 20ms
        }
        return;
    }
    buffer->memory_->SetSize(bufferSize);
    status = outputBufferQueue_->PushBuffer(buffer, true);
    if (status != Status::OK) { MEDIA_LOG_E("PushBuffer fail"); }
    RelativeSleep(AUDIO_DATASOURCE_FILTER_READ_SUCCESS_WAIT_TIME); // 4ms
}
```
> ReadAt 返回值三态处理（OK/RETRY_IN_INTERVAL/SKIP_WITHOUT_LOG）；失败重试间隔21333333ns（20ms）；成功等待4000000ns（4ms）

---

**E12 — OnLinkedResult：产出队列绑定**
```cpp
// audio_data_source_filter.cpp L239-243
void AudioDataSourceFilter::OnLinkedResult(const sptr<AVBufferQueueProducer> &queue, std::shared_ptr<Meta> &meta)
{
    MEDIA_LOG_I("AudioDataSourceFilter OnLinkedResult");
    outputBufferQueue_ = queue;
}
```
> 下游 Filter linked 后回调，接收 AVBufferQueueProducer

---

**E13 — RelativeSleep：clock_nanosleep 精确延时**
```cpp
// audio_data_source_filter.cpp L316-329
int32_t AudioDataSourceFilter::RelativeSleep(int64_t nanoTime)
{
    int32_t ret = -1;
    if (nanoTime <= 0) { MEDIA_LOG_E("RelativeSleep nanoTime <= 0"); return ret; }
    struct timespec time;
    time.tv_sec = nanoTime / AUDIO_NS_PER_SECOND;
    time.tv_nsec = nanoTime - (time.tv_sec * AUDIO_NS_PER_SECOND);
    clockid_t clockId = CLOCK_MONOTONIC;
    const int relativeFlag = 0;
    ret = clock_nanosleep(clockId, relativeFlag, &time, nullptr);
    if (ret != 0) { MEDIA_LOG_I("RelativeSleep may failed, ret is :%{public}d", ret); }
    return ret;
}
```
> CLOCK_MONOTONIC 相对时间睡眠；避免 % 操作优化性能

---

**E14 — LinkNext：Filter链路建立**
```cpp
// audio_data_source_filter.cpp L160-170
Status AudioDataSourceFilter::LinkNext(const std::shared_ptr<Filter> &nextFilter, StreamType outType)
{
    MEDIA_LOG_I("AudioDataSourceFilter LinkNext");
    auto meta = std::make_shared<Meta>();
    GetParameter(meta);
    nextFilter_ = nextFilter;
    nextFiltersMap_[outType].push_back(nextFilter_);
    std::shared_ptr<FilterLinkCallback> filterLinkCallback =
        std::make_shared<AudioDataSourceFilterLinkCallback>(shared_from_this());
    nextFilter->OnLinked(outType, meta, filterLinkCallback);
    return Status::OK;
}
```

---

**E15 — 头文件：FilterType 与 IAudioDataSource**
```cpp
// audio_data_source_filter.h L37-55
class AudioDataSourceFilter : public Filter, public std::enable_shared_from_this<AudioDataSourceFilter> {
public:
    // ... 15 public methods
    void SetAudioDataSource(const std::shared_ptr<IAudioDataSource>& audioSource);
    void SetVideoFirstFramePts(int64_t firstFramePts);
    FilterType GetFilterType();  // 返回 FilterType::AUDIO_CAPTURE（注意：注册用 AUDIO_DATA_SOURCE）
private:
    void ReadLoop();
    int32_t RelativeSleep(int64_t nanoTime);
    std::shared_ptr<Task> taskPtr_{ nullptr };
    sptr<AVBufferQueueProducer> outputBufferQueue_;
    std::shared_ptr<IAudioDataSource> audioDataSource_{ nullptr };
    std::atomic<bool> eos_{ false };
    Mutex captureMutex_{};
};
```
> `enable_shared_from_this` 支持 `shared_from_this()` 在回调中创建 LinkCallback；atomic eos_ 保证线程安全

---

## 4. 数据流总结

```
IAudioDataSource::GetSize() ← 获取缓冲区大小
         ↓
IAudioDataSource::ReadAt()        ← 读取音频数据
         ↓
AVBufferQueueProducer::RequestBuffer() ← 申请输出 buffer
         ↓
AVBufferQueueProducer::PushBuffer()     ← 推送至下游 Filter
         ↓
下游 Filter（通常是 AudioEncoderFilter 或 MuxerFilter）
```

**ReadLoop 调度周期**：
- 成功读取后：`RelativeSleep(4ms)` — 控制读取频率
- 读取失败（RETRY_IN_INTERVAL）：`RelativeSleep(20ms)` —等待数据就绪
- 读取失败（其他）：立即返回，下次 Task 触发时重试

**EOS 流程**：
1. 外部调用 `SendEos()`
2. RequestBuffer 申请一个 buffer
3. `buffer->flag_ |= BUFFER_FLAG_EOS` 设置结束标志
4. `PushBuffer(buffer, false)` 非阻塞推送
5. `eos_.store(true)` 原子标记

---

## 5. 与相关 S 条目对比

| S条目 | 主题 | 与 S230 差异 |
|-------|------|-------------|
| S189/S190 | AudioCaptureModule 音频采集 | S230 使用 IAudioDataSource 抽象接口，不直接依赖 AudioCapturer；AudioCaptureModule 更底层 |
| S219 | SourcePlugin 三件套 | S219 是协议层 Source（file/http/stream）；S230 是 Filter 层数据源，输出 AVBuffer |
| S185 | AudioServerSinkPlugin | S185 是输出终点（渲染到 AudioRenderer）；S230 是管线数据起点 |
| S184/S188 | FFmpeg Audio Decoder | S184 是解码 Filter；S230 是录音原始数据源，无编解码 |

---

## 6. 关键常量

| 常量 | 值 | 位置 |
|------|-----|------|
| BUFFER_FLAG_EOS | 0x00000001 | L27 |
| TIME_OUT_MS | 0 | L29（RequestBuffer 零超时） |
| LOG_LIMIT_HUNDRED | 100 | L20（日志限频） |
| AUDIO_NS_PER_SECOND | 1000000000 | L21 |
| AUDIO_DATASOURCE_FILTER_READ_FAILED_WAIT_TIME | 21333333ns (20ms) | L22 |
| AUDIO_DATASOURCE_FILTER_READ_SUCCESS_WAIT_TIME | 4000000ns (4ms) | L23 |

---

## 7. 疑点和未覆盖点

- `IAudioDataSource` 接口定义在 `audio_data_source_filter.h` 中，具体 `ReadAt` 返回的 `AudioDataSourceReadAtActionState` 枚举值定义位置未在本次探索中确认
- `FilterType::AUDIO_CAPTURE` vs `FilterType::AUDIO_DATA_SOURCE` 的区别（构造函数用 AUDIO_DATA_SOURCE 注册，GetFilterType 返回 AUDIO_CAPTURE）——可能为历史兼容设计
- `MediaDataSource`  vs `IAudioDataSource` 名称混淆：接口名为 `IAudioDataSource`，但头文件 `audio_data_source_filter.h` include 了 `"media_data_source.h"`

---

**生成时间**：2026-06-0815:38 GMT+8
**Builder**：builder-agent (subagent)
**本地镜像**：`/home/west/av_codec_repo/services/media_engine/filters/audio_data_source_filter.cpp` (343行) + `interfaces/inner_api/native/audio_data_source_filter.h` (75行)
**状态**：draft → 待提交审批