---
id: MEM-ARCH-AVCODEC-S235
title: VideoCaptureFilter — Surface → AVBuffer 桥接过滤器
type: architecture_fact
scope: [AVCodec, MediaEngine, Filter, VideoCapture, Surface]
status: pending_approval
confidence: high
summary: >
  VideoCaptureFilter 是录制管线的视频采集过滤器，桥接 Surface（OHOS 图形表面）
  与 Filter 管线。它从 Surface 消费原始视频帧（通过 IBufferConsumerListener回调），
  将 SurfaceBuffer 转换为 AVBuffer 后通过 outputBufferQueueProducer_推送给下游。
  支持 Pause/Resume 时间戳修正（totalPausedTime_ 累积），支持 EOS通知。
关联场景: 录制管线 / Camera → Encoder 桥接 / 实时视频采集
关联: S100(Filter框架) / S112(Surface机制) / S215(AVBuffer)
---

## 1. 架构定位

VideoCaptureFilter位于录制（Recorder）管线的数据源侧，负责：

```
Camera/VirtualCamera
    │
    ▼  (Surface Producer → Consumer Surface)
Surface (OHOS Graphic Buffer)
    │
    ▼ ConsumerSurfaceBufferListener::OnBufferAvailable()
VideoCaptureFilter
    │
    ▼ ProcessAndPushOutputBuffer() → outputBufferQueueProducer_->PushBuffer()
下游 Filter (VideoEncoderFilter)
```

**核心职责**：将 OHOS Surface 的视频帧转换为 Filter 管线中的 AVBuffer，不做编解码。

---

## 2. 过滤器注册与实例化

###2.1 自注册机制

**E1**: `video_capture_filter.cpp L30-35` — Filter 自注册宏

```cpp
static AutoRegisterFilter<VideoCaptureFilter> g_registerSurfaceEncoderFilter(
    "builtin.recorder.videocapture",
    FilterType::VIDEO_CAPTURE,
    [](const std::string& name, const FilterType type) {
        return std::make_shared<VideoCaptureFilter>(name, FilterType::VIDEO_CAPTURE);
    });
```

注册名称：`"builtin.recorder.videocapture"`，类型：`FilterType::VIDEO_CAPTURE`。

### 2.2 FilterLinkCallback 适配器

**E2**: `video_capture_filter.cpp L37-66` — VideoCaptureFilterLinkCallback弱引用回调桥

```cpp
class VideoCaptureFilterLinkCallback : public FilterLinkCallback {
    std::weak_ptr<VideoCaptureFilter> videoCaptureFilter_;
    void OnLinkedResult(...)  { videoCaptureFilter_.lock()->OnLinkedResult(...); }
    void OnUnlinkedResult(...) { videoCaptureFilter_.lock()->OnUnlinkedResult(...); }
    void OnUpdatedResult(...) { videoCaptureFilter_.lock()->OnUpdatedResult(...); }
};
```

通过 `weak_ptr` 避免循环引用。

### 2.3 ConsumerSurfaceBufferListener 表面缓冲区监听器

**E3**: `video_capture_filter.cpp L68-80` — IBufferConsumerListener 实现

```cpp
class ConsumerSurfaceBufferListener : public IBufferConsumerListener {
    std::weak_ptr<VideoCaptureFilter> videoCaptureFilter_;
    void OnBufferAvailable() {
        videoCaptureFilter_.lock()->OnBufferAvailable(); // 触发帧采集
    }
};
```

当 Surface 有可用帧时触发采集流程。

---

## 3. Surface 配置与初始化

### 3.1 SetInputSurface 外部注入模式

**E4**: `video_capture_filter.cpp L111-119` — 外部 Surface 注入 + Listener 注册

```cpp
Status VideoCaptureFilter::SetInputSurface(sptr<Surface> surface)
{
    if (surface == nullptr) return Status::ERROR_UNKNOWN;
    inputSurface_ = surface;
    sptr<IBufferConsumerListener> listener = new ConsumerSurfaceBufferListener(shared_from_this());
    inputSurface_->RegisterConsumerListener(listener); // 注册帧回调
    return Status::OK;
}
```

### 3.2 GetInputSurface 内部创建模式

**E5**: `video_capture_filter.cpp L121-145` — 创建 Consumer Surface 并返回 Producer

```cpp
sptr<Surface> VideoCaptureFilter::GetInputSurface()
{
    // 1. 创建 Consumer Surface
    sptr<Surface> consumerSurface = Surface::CreateSurfaceAsConsumer("EncoderSurface");
    // 2. 设置 DefaultUsage = ENCODE_USAGE（编码用途）
    GSError err = consumerSurface->SetDefaultUsage(ENCODE_USAGE);
    // 3. 获取 Producer Surface 并返回给上游（Camera）
    sptr<IBufferProducer> producer = consumerSurface->GetProducer();
    sptr<Surface> producerSurface = Surface::CreateSurfaceAsProducer(producer);
    inputSurface_ = consumerSurface;
    inputSurface_->RegisterConsumerListener(listener);
    return producerSurface; // 返回给 Camera
}
```

两种工作模式：外部注入（SetInputSurface）或内部创建（GetInputSurface）。

---

## 4. 生命周期管理

### 4.1 DoPrepare / DoStart / DoPause / DoResume / DoStop

**E6**: `video_capture_filter.cpp L147-182` — 生命周期方法

```cpp
Status VideoCaptureFilter::DoPrepare()
{
    filterCallback_->OnCallback(shared_from_this(),
        FilterCallBackCommand::NEXT_FILTER_NEEDED, StreamType::STREAMTYPE_ENCODED_VIDEO);
    return Status::OK;
}

Status VideoCaptureFilter::DoPause()
{
    isStop_ = true;
    latestPausedTime_ = latestBufferTime_; // 记录暂停时刻
    return Status::OK;
}

Status VideoCaptureFilter::DoResume()
{
    isStop_ = false;
    refreshTotalPauseTime_ = true; // 下帧时刷新暂停时长
    return Status::OK;
}
```

**E7**: `video_capture_filter.cpp L184-195` — DoStop 重置所有时间状态

```cpp
Status VideoCaptureFilter::DoStop()
{
    isStop_ = true;
    latestBufferTime_ = TIME_NONE;
    latestPausedTime_ = TIME_NONE;
    totalPausedTime_ = 0;
    refreshTotalPauseTime_ = false;
    return Status::OK;
}
```

---

## 5. 核心数据流：OnBufferAvailable → AcquireInputBuffer → ProcessAndPushOutputBuffer

### 5.1 OnBufferAvailable 触发采集

**E8**: `video_capture_filter.cpp L230-244` — 主触发函数

```cpp
void VideoCaptureFilter::OnBufferAvailable()
{
    sptr<SurfaceBuffer> inputBuffer;
    int64_t timestamp;
    int32_t bufferSize = 0;
    int32_t isKeyFrame = 0;

    if (!AcquireInputBuffer(inputBuffer, timestamp, bufferSize, isKeyFrame)) return;
    if (!ProcessAndPushOutputBuffer(inputBuffer, timestamp, bufferSize, isKeyFrame)) return;
    inputSurface_->ReleaseBuffer(inputBuffer, -1); // 归还 Surface Buffer
}
```

### 5.2 AcquireInputBuffer 获取并验证 Surface Buffer

**E9**: `video_capture_filter.cpp L246-268` — Surface AcquireBuffer + 同步等待

```cpp
bool VideoCaptureFilter::AcquireInputBuffer(sptr<SurfaceBuffer>& buffer, ...)
{
    FALSE_RETURN_V_MSG(inputSurface_ != nullptr, false, "inputSurface_ is nullptr");

    sptr<SyncFence> fence;
    OHOS::Rect damage;
    GSError ret = inputSurface_->AcquireBuffer(buffer, fence, timestamp, damage);
    FALSE_RETURN_V_MSG(ret == GSERROR_OK && buffer != nullptr && fence != nullptr, false, "AcquireBuffer fail");

    constexpr uint32_t waitForEver = -1;
    (void)fence->Wait(waitForEver); // 等待帧就绪（同步等待）

    if (isStop_) { // 暂停状态则放弃此帧
        inputSurface_->ReleaseBuffer(buffer, -1);
        return false;
    }

    // 从 SurfaceBuffer 的 ExtraData 提取关键信息
    auto extraData = buffer->GetExtraData();
    extraData->ExtraGet("timeStamp", timestamp);
    extraData->ExtraGet("dataSize", bufferSize);
    extraData->ExtraGet("isKeyFrame", isKeyFrame);
    return true;
}
```

关键：从 SurfaceBuffer 的 ExtraData 中提取 `timeStamp`/`dataSize`/`isKeyFrame`。

### 5.3 ProcessAndPushOutputBuffer 转换为 AVBuffer 并推送

**E10**: `video_capture_filter.cpp L270-295` — RequestBuffer + Write + Push 三步曲

```cpp
bool VideoCaptureFilter::ProcessAndPushOutputBuffer(
    sptr<SurfaceBuffer>& buffer, int64_t timestamp, int32_t bufferSize, int32_t isKeyFrame)
{
    std::shared_ptr<AVBuffer> emptyOutputBuffer;
    AVBufferConfig avBufferConfig;
    avBufferConfig.size = bufferSize;
    avBufferConfig.memoryType = MemoryType::SHARED_MEMORY;
    avBufferConfig.memoryFlag = MemoryFlag::MEMORY_READ_WRITE;

    Status status = outputBufferQueueProducer_->RequestBuffer(emptyOutputBuffer, ...);
    FALSE_RETURN_V_MSG(status == Status::OK && emptyOutputBuffer != nullptr, false, "RequestBuffer fail");

    emptyOutputBuffer->flag_ = isKeyFrame != 0
        ? static_cast<uint32_t>(Plugins::AVBufferFlag::SYNC_FRAME) : 0;
    bufferMem->Write((const uint8_t *)buffer->GetVirAddr(), bufferSize, 0); // 内存拷贝
    UpdateBufferConfig(emptyOutputBuffer, timestamp);

    status = outputBufferQueueProducer_->PushBuffer(emptyOutputBuffer, true);
    FALSE_RETURN_V_MSG(status == Status::OK, false, "PushBuffer fail");
    return true;
}
```

注意：帧数据通过 `GetVirAddr()` 直接读取 SurfaceBuffer 虚拟地址，零拷贝写入 AVBuffer。

---

## 6. PTS 时间戳修正机制

### 6.1 UpdateBufferConfig 时间戳计算

**E11**: `video_capture_filter.cpp L297-315` — PTS = (timestamp - startBufferTime_ - totalPausedTime_) / 1000

```cpp
void VideoCaptureFilter::UpdateBufferConfig(std::shared_ptr<AVBuffer> buffer, int64_t timestamp)
{
    if (startBufferTime_ == TIME_NONE) {
        startBufferTime_ = timestamp;
        buffer->flag_ = (uint32_t)Plugins::AVBufferFlag::SYNC_FRAME // 首帧标记 SYNC_FRAME
                     | (uint32_t)Plugins::AVBufferFlag::CODEC_DATA; // 和 CODEC_DATA
    }
    latestBufferTime_ = timestamp;

    // 刷新 totalPausedTime_（只在 Resume后的第一帧执行）
    if (refreshTotalPauseTime_) {
        if (latestPausedTime_ != TIME_NONE && latestBufferTime_ > latestPausedTime_) {
            totalPausedTime_ += latestBufferTime_ - latestPausedTime_; // 累加本次暂停时长
        }
        refreshTotalPauseTime_ = false;
    }

    constexpr int32_t NS_PER_US = 1000;
    buffer->pts_ = timestamp - startBufferTime_ - totalPausedTime_;
    buffer->pts_ = buffer->pts_ / NS_PER_US; // 转换为微秒
}
```

### 6.2 Pause/Resume 暂停时长修正语义

```
首帧 timestamp=0     startBufferTime_=0
第N帧 timestamp=T pts = (T-0-0)/1000
       ↓ DoPause
       isStop_=true, latestPausedTime_=T
       ↓ DoResume
       refreshTotalPauseTime_=true
第N+1帧 timestamp=T2
       totalPausedTime_ += (T2 - T)  // 累加本次暂停
       pts = (T2-0-totalPausedTime_)/1000  // 扣除暂停，跳过中间帧
       refreshTotalPauseTime_=false
```

---

## 7. LinkNext 管线连接

**E12**: `video_capture_filter.cpp L206-215` — LinkNext 注册下游 Filter 并触发 OnLinked

```cpp
Status VideoCaptureFilter::LinkNext(const std::shared_ptr<Filter> &nextFilter, StreamType outType)
{
    nextFilter_ = nextFilter;
    nextFiltersMap_[outType].push_back(nextFilter_);
    std::shared_ptr<FilterLinkCallback> filterLinkCallback =
        std::make_shared<VideoCaptureFilterLinkCallback>(shared_from_this());
    nextFilter->OnLinked(outType, configureParameter_, filterLinkCallback);
    return Status::OK;
}
```

LinkNext 时传入 configureParameter_（编码参数），下游 Filter 通过 OnLinked 获取。

---

## 8. OnLinkedResult 下游 BufferQueue 回调

**E13**: `video_capture_filter.cpp L222-229` — 接收 outputBufferQueueProducer_

```cpp
void VideoCaptureFilter::OnLinkedResult(
    const sptr<AVBufferQueueProducer> &outputBufferQueue,
    std::shared_ptr<Meta> &meta)
{
    outputBufferQueueProducer_ = outputBufferQueue;
}
```

下游 VideoEncoderFilter 在 OnLinked 时将自己的 AVBufferQueueProducer 回调给 VideoCaptureFilter。

---

## 9. 关键数据流总图

```
Camera (Producer Side)
   │
   ▼ Surface::CreateSurfaceAsProducer(producer)
Surface Producer ──────────────────────────► Surface Consumer (VideoCaptureFilter)
                                                    │
  ┌────────────────────────────────────────────────┘
   ▼ ConsumerSurfaceBufferListener::OnBufferAvailable()
   │
   ▼ AcquireInputBuffer()
   │    inputSurface_->AcquireBuffer() [E9]
   │    fence->Wait(waitForEver) [E9]
   │    extraData->ExtraGet("timeStamp"/"dataSize"/"isKeyFrame") [E9]
   │
   ▼ ProcessAndPushOutputBuffer()
   │    outputBufferQueueProducer_->RequestBuffer()  [E10]
   │    bufferMem->Write(GetVirAddr(), bufferSize)   [E10]
   │    UpdateBufferConfig(pts计算)                  [E11]
   │    outputBufferQueueProducer_->PushBuffer()     [E10]
   │
   ▼ inputSurface_->ReleaseBuffer() [E8]
        │
        ▼
   VideoEncoderFilter (下游)
```

---

## 10. 与相关记忆条目关联

| 关联 | 说明 |
|------|------|
| S100(Filter框架) | Filter 基类、AutoRegisterFilter 自注册机制 |
| S112(Surface机制) | OHOS Surface / SurfaceBuffer / Producer-Consumer 模型 |
| S215(AVBuffer) | AVBuffer / AVBufferConfig / MemoryType / Flag 定义 |
| S220(VideoEncoderFilter) | 下游编码器，消费 VideoCaptureFilter 输出的 AVBuffer |
| S113(BufferQueue) | AVBufferQueueProducer / RequestBuffer / PushBuffer 机制 |

---

## 11. Evidence 汇总

| # | 文件 | 行号 | 内容 |
|---|------|------|------|
| E1 | video_capture_filter.cpp | 30-35 | AutoRegisterFilter 自注册宏 |
| E2 | video_capture_filter.cpp | 37-66 | VideoCaptureFilterLinkCallback 弱引用桥 |
| E3 | video_capture_filter.cpp | 68-80 | ConsumerSurfaceBufferListener 实现 |
| E4 | video_capture_filter.cpp | 111-119 | SetInputSurface 外部注入模式 |
| E5 | video_capture_filter.cpp | 121-145 | GetInputSurface 内部创建 Consumer Surface |
| E6 | video_capture_filter.cpp | 147-182 | DoPrepare/DoStart/DoPause/DoResume生命周期 |
| E7 | video_capture_filter.cpp | 184-195 | DoStop 重置时间状态 |
| E8 | video_capture_filter.cpp | 230-244 | OnBufferAvailable触发采集主流程 |
| E9 | video_capture_filter.cpp | 246-268 | AcquireInputBuffer Surface获取+同步等待+ExtraData提取 |
| E10 | video_capture_filter.cpp | 270-295 | ProcessAndPushOutputBuffer Request+Write+Push |
| E11 | video_capture_filter.cpp | 297-315 | UpdateBufferConfig PTS修正+暂停时长累积 |
| E12 | video_capture_filter.cpp | 206-215 | LinkNext 下游 Filter 连接 |
| E13 | video_capture_filter.cpp | 222-229 | OnLinkedResult 接收 outputBufferQueueProducer_ |