# MEM-ARCH-AVCODEC-S252

## 基本信息

| 字段 | 值 |
|------|-----|
| mem_id | MEM-ARCH-AVCODEC-S252 |
| 主题 | SideOutputSurfaceProcessor 侧输出视频后处理器——三Surface架构 + 双缓冲队列流水线 + memcpy_s零拷贝复制 |
| scope | MediaEngine, PostProcessor, SideOutput, Surface, BufferQueue, WorkerThread, Camera |
| 关联场景 | 视频录制/预览双路输出/边录制边预览/Camera插入帧后处理/多Surface协调 |
| status | draft |
| 来源 | 本地镜像 /home/west/av_codec_repo/services/media_engine/modules/post_processor/ |
| 依赖关联 | S100(SuperResolutionPostProcessor)/S127(CameraPostProcessor)同属VideoPostProcessorType体系 |

---

## 架构概述

SideOutputSurfaceProcessor 是 VideoPostProcessorType::SIDE_OUTPUT 类型的视频后处理器，继承 BaseVideoPostProcessor。其核心职责是**从主视频管线消费帧，同时向 SideSurface 输出副本科，用于边录制边预览、多路输出等场景**。

### 三 Surface 架构

| Surface | 角色 | 流向 |
|---------|------|------|
| consumerSurface_ | 输入Surface，消费上游Pipeline帧 | 上游→consumerSurface_ |
| producerSurface_ | 输出Surface，向下游Pipeline输出处理后帧 | producerSurface_→下游 |
| sideSurface_ | 侧输出Surface，输出副本科供预览/录制 | sideSurface_→外部消费者 |

### 双缓冲队列流水线

| 队列 | 类型 | 最大深度 | 说明 |
|------|------|---------|------|
| consumerBufferQueue_ | std::queue<SurfaceBufferInfo> | 无硬上限 | 消费侧缓冲队列 |
| producerBufferQueue_ | std::queue<SurfaceBufferInfo> | 无硬上限 | 生产侧缓冲队列 |
| renderBufferQueue_ | std::map<uint32_t, SurfaceBufferInfo> | 5 (MAX_RENDER_BUFFER_QUEUE_SIZE) | 渲染中缓冲，超限丢弃最旧帧 |

---

## Evidence 条目

**E1: AutoRegisterPostProcessor 自注册机制 (side_output_surface_processor.cpp L36-44)**

```cpp
static AutoRegisterPostProcessor<SideOutputSurfaceProcessor> g_registerSideOutputProcessor(
    VideoPostProcessorType::SIDE_OUTPUT, []() -> std::shared_ptr<BaseVideoPostProcessor> {
        auto postProcessor = std::make_shared<SideOutputSurfaceProcessor>();
        return postProcessor;
    }, &IsSideOutputSurfaceSupported);
```

枚举定义 (base_video_post_processor.h L40-46):
```cpp
enum VideoPostProcessorType {
    NONE,
    SUPER_RESOLUTION,
    CAMERA_INSERT_FRAME,
    CAMERA_MP_PWP,
    SIDE_OUTPUT,  // <-- 本主题
};
```

**E2: ConsumerSurfaceBufferListener 消费者缓冲监听器 (side_output_surface_processor.cpp L46-58)**

```cpp
class ConsumerSurfaceBufferListener : public IBufferConsumerListener {
public:
    explicit ConsumerSurfaceBufferListener(std::weak_ptr<SideOutputSurfaceProcessor> processor)
        : interPostProcessor_(processor) {}
    void OnBufferAvailable() override {
        auto processor = interPostProcessor_.lock();
        if (processor != nullptr) {
            processor->OnConsumerBufferAvailable();
        }
    }
private:
    std::weak_ptr<SideOutputSurfaceProcessor> interPostProcessor_;
};
```

**E3: Init() 工作线程启动 (side_output_surface_processor.cpp L73-97)**

```cpp
Status SideOutputSurfaceProcessor::Init()
{
    MEDIA_LOG_I("SideOutputSurfaceProcessor Init");
    std::lock_guard<std::mutex> lock(lock_);
    if (isInitialized_.load()) {
        MEDIA_LOG_I("Already initialize!");
        return Status::OK;
    }
    sampleTask_ = std::make_shared<Task>("SideOutputSample", "SideOutputSurfaceProcessor",
        TaskType::SINGLETON, TaskPriority::HIGH, false);
    isRunning_.store(true);
    worker_ = std::thread([this]() {
        while (isRunning_.load()) {
            if (!WaitTrigger()) {
                MEDIA_LOG_I("continue-----------");
                continue;
            }
            ProcessBuffers();
        }
    });
    isInitialized_.store(true);
    return Status::OK;
}
```

**E4: ProcessorState 三态机 (side_output_surface_processor.h L88)**

```cpp
enum class ProcessorState { IDLE, RUNNING, STOPPING };
std::atomic<ProcessorState> state_ {ProcessorState::IDLE};
```

**E5: Start/Stop/Flush/Release 生命周期 (side_output_surface_processor.cpp L99-186)**

```cpp
Status SideOutputSurfaceProcessor::Flush()
{
    MEDIA_LOG_I("SideOutputSurfaceProcessor Flush");
    {
        std::lock_guard<std::mutex> lock(lock_);
        if (producerSurface_ != nullptr) {
            producerSurface_->CleanCache(false);
        }
        if (sideSurface_ != nullptr) {
            sideSurface_->CleanCache(false);
        }
    }
    ClearBufferQueues();
    return Status::OK;
}

Status SideOutputSurfaceProcessor::Stop()
{
    MEDIA_LOG_I("SideOutputSurfaceProcessor Stop");
    std::lock_guard<std::mutex> lock(lock_);
    state_.store(ProcessorState::STOPPING);
    isPaused_.store(true);
    cvTrigger_.notify_one();
    return Status::OK;
}

Status SideOutputSurfaceProcessor::Start()
{
    MEDIA_LOG_I("SideOutputSurfaceProcessor Start");
    std::lock_guard<std::mutex> lock(lock_);
    if (state_.load() == ProcessorState::RUNNING) {
        return Status::OK;
    }
    state_.store(ProcessorState::RUNNING);
    isPaused_.store(false);
    cvTrigger_.notify_one();
    return Status::OK;
}
```

**E6: Release() 资源释放 (side_output_surface_processor.cpp L142-186)**

```cpp
Status SideOutputSurfaceProcessor::Release()
{
    MEDIA_LOG_I("SideOutputSurfaceProcessor Release");
    {
        std::lock_guard<std::mutex> lock(lock_);
        if (!isInitialized_.load()) {
            MEDIA_LOG_I("Already deinitialize!");
            return Status::OK;
        }
        isRunning_.store(false);
        isInitialized_.store(false);
        isPaused_.store(false);
        if (state_.load() == ProcessorState::RUNNING) {
            state_.store(ProcessorState::STOPPING);
        }
    }
    cvTrigger_.notify_all();
    if (worker_.joinable()) {
        worker_.join();
    }
    if (sampleTask_ != nullptr) {
        sampleTask_->Stop();
        sampleTask_ = nullptr;
    }
    ClearBufferQueues();
    {
        std::lock_guard<std::mutex> lock(lock_);
        callback_ = nullptr;
        if (consumerSurface_ != nullptr) {
            consumerSurface_->UnregisterConsumerListener();
            consumerSurface_ = nullptr;
        }
        if (producerSurface_ != nullptr) {
            producerSurface_->UnRegisterReleaseListener();
            producerSurface_->Disconnect();
            producerSurface_->CleanCache(true);
            producerSurface_ = nullptr;
        }
        sideSurface_ = nullptr;
    }
    return Status::OK;
}
```

**E7: GetInputSurface/SetOutputSurface 双Surface设置 (side_output_surface_processor.cpp L189-250)**

```cpp
sptr<Surface> SideOutputSurfaceProcessor::GetInputSurface()
{
    MEDIA_LOG_I("SideOutputSurfaceProcessor GetInputSurface");
    std::lock_guard<std::mutex> lock(lock_);
    if (consumerSurface_ != nullptr) {
        return producerSurface_;  // 返回producer作为下游输入
    }
    // ... 首次创建consumer-producer配对
    sptr<IBufferProducer> producer = consumerSurface_->GetProducer();
    // Register release listener for producer
    GSError err = surface->RegisterReleaseListener([weakProcessor](sptr<SurfaceBuffer>& buffer) {
        // ...
        return processor->OnProducerBufferReleased();
    });
    // ...
}

Status SideOutputSurfaceProcessor::SetOutputSurface(sptr<Surface> surface)
{
    FALSE_RETURN_V_MSG(surface != nullptr, Status::ERROR_NULL_SURFACE, "SetOutputSurface null surface");
    FALSE_RETURN_V_MSG_W(!surface->IsConsumer(), Status::ERROR_INVALID_PARAMETER, "surface is NOT producer");
    // ...
    sideSurface_ = surface;  // 侧输出Surface
}
```

**E8: OnConsumerBufferAvailable 消费侧缓冲获取 (side_output_surface_processor.cpp L309-345)**

```cpp
void SideOutputSurfaceProcessor::OnConsumerBufferAvailable()
{
    MEDIA_LOG_I("OnConsumerBufferAvailable start");
    if (!isRunning_.load() || state_.load() != ProcessorState::RUNNING) {
        return;
    }
    sptr<Surface> consumerSurface;
    {
        std::lock_guard<std::mutex> lock(lock_);
        consumerSurface = consumerSurface_;
    }
    SurfaceBufferInfo bufferInfo{};
    GSError err = consumerSurface->AcquireBuffer(bufferInfo.buffer, bufferInfo.fence, bufferInfo.timestamp, damage);
    if (err != GSERROR_OK || bufferInfo.buffer == nullptr) {
        MEDIA_LOG_E("Failed to acquire buffer, ret: %{public}d!", err);
        return;
    }
    if (bufferInfo.fence != nullptr) {
        bufferInfo.fence->Wait(WAIT_FOR_EVER);
    }
    PushBufferToConsumer(bufferInfo);
}
```

**E9: PushBufferToConsumer 缓冲入队与分辨率变更处理 (side_output_surface_processor.cpp L398-440)**

```cpp
void SideOutputSurfaceProcessor::PushBufferToConsumer(SurfaceBufferInfo& bufferInfo)
{
    bool needPrepare = false;
    bool resolutionChanged = false;
    {
        // ...
        bool isFirstBuffer = UpdateRequestConfigFromBuffer(bufferInfo);
        // ...
        if (resolutionChanged) {
            HandleResolutionChange();
        }
        // ...
        consumerBufferQueue_.push(bufferInfo);
        producerBufferQueue_.push(producerBufferInfo);
    }
    // ...
    if (state_.load() != ProcessorState::IDLE) {
        cvTrigger_.notify_one();
    }
}
```

**E10: OnProducerBufferReleased 生产者缓冲释放回调 (side_output_surface_processor.cpp L423-473)**

```cpp
GSError SideOutputSurfaceProcessor::OnProducerBufferReleased()
{
    MEDIA_LOG_I("OnProducerBufferReleased step in");
    if (state_.load() == ProcessorState::STOPPING) {
        MEDIA_LOG_I("Skip when stopping.");
        return GSERROR_OK;
    }
    if (!isBufferQueueReady_.load()) {
        MEDIA_LOG_W("Skip OnProducerBufferReleased, buffer queue not ready");
        return GSERROR_OK;
    }
    sptr<Surface> producerSurface;
    // Request new buffer from producer
    err = producerSurface->RequestBuffer(bufferInfo.buffer, bufferInfo.fence, requestCfg_);
    producerBufferQueue_.push(bufferInfo);
    if (state_.load() != ProcessorState::IDLE) {
        cvTrigger_.notify_one();
    }
    return GSERROR_OK;
}
```

**E11: ProcessBuffers 核心处理循环 (side_output_surface_processor.cpp L694-722)**

```cpp
void SideOutputSurfaceProcessor::ProcessBuffers()
{
    if (!isRunning_.load()) {
        MEDIA_LOG_I("Skip when died.");
        return;
    }
    {
        std::lock_guard<std::mutex> lock(lock_);
        if (consumerSurface_ == nullptr || producerSurface_ == nullptr) {
            MEDIA_LOG_W("consumer or producer is null!");
            return;
        }
    }
    while (isRunning_.load()) {
        isProcessing_ = true;
        SurfaceBufferInfo srcBufferInfo;
        SurfaceBufferInfo dstBufferInfo;
        if (!GetConsumerAndProducerBuffer(srcBufferInfo, dstBufferInfo)) {
            MEDIA_LOG_D("GetConsumerAndProducerBuffer break");
            isProcessing_ = false;
            cvDone_.notify_all();
            break;
        }
        MEDIA_LOG_I("ProcessBuffer start");
        ProcessBuffer(srcBufferInfo, dstBufferInfo);
    }
    isProcessing_ = false;
    cvDone_.notify_all();
}
```

**E12: ProcessBuffer memcpy_s零拷贝复制 (side_output_surface_processor.cpp L525-558)**

```cpp
bool SideOutputSurfaceProcessor::ProcessBuffer(SurfaceBufferInfo& srcBufferInfo, SurfaceBufferInfo& dstBufferInfo)
{
    MEDIA_LOG_D("ProcessBuffer src(w=%{public}d,h=%{public}d), dst(w=%{public}d,h=%{public}d)",
        srcBufferInfo.buffer->GetWidth(), srcBufferInfo.buffer->GetHeight(),
        dstBufferInfo.buffer->GetWidth(), dstBufferInfo.buffer->GetHeight());
    srcBufferInfo.buffer->InvalidateCache();
    dstBufferInfo.timestamp = srcBufferInfo.timestamp;
    void* srcAddr = srcBufferInfo.buffer->GetVirAddr();
    void* dstAddr = dstBufferInfo.buffer->GetVirAddr();
    if (srcAddr == nullptr || dstAddr == nullptr) {
        return false;
    }
    uint32_t size = srcBufferInfo.buffer->GetSize();
    if (size > dstBufferInfo.buffer->GetSize()) {
        return HandleBufferSizeMismatch(srcBufferInfo, dstBufferInfo);
    }
    if (size > 0) {
        errno_t ret = memcpy_s(dstAddr, size, srcAddr, size);  // 核心：零拷贝 memcpy
        if (ret != EOK) {
            MEDIA_LOG_E("ProcessBuffer memcpy_s failed, ret=%{public}d", ret);
            return false;
        }
    }
    // Release consumer buffer and output producer buffer
    consumerSurface_->ReleaseBuffer(srcBufferInfo.buffer, -1);
    OutputBuffer(dstBufferInfo);
    return true;
}
```

**E13: OutputBuffer + HandleRenderBufferOverflow 渲染队列管理 (side_output_surface_processor.cpp L577-608)**

```cpp
void SideOutputSurfaceProcessor::OutputBuffer(const SurfaceBufferInfo& bufferInfo)
{
    sptr<SurfaceBuffer> bufferToCancel;
    {
        std::lock_guard<std::mutex> bufferLock(bufferLock_);
        bufferToCancel = HandleRenderBufferOverflow();  // 超限丢弃最旧
        renderBufferQueue_[bufferInfo.buffer->GetSeqNum()] = bufferInfo;
    }
    if (bufferToCancel != nullptr) {
        producerSurface_->CancelBuffer(bufferToCancel);
    }
    // callback通知
    if (callback_ != nullptr) {
        callback_->OnBufferAvailable(index, bufferInfo.timestamp);
    }
}

sptr<SurfaceBuffer> SideOutputSurfaceProcessor::HandleRenderBufferOverflow()
{
    if (renderBufferQueue_.size() < MAX_RENDER_BUFFER_QUEUE_SIZE) {  // MAX_RENDER_BUFFER_QUEUE_SIZE = 5
        return nullptr;
    }
    auto oldest = renderBufferQueue_.begin();
    MEDIA_LOG_W("renderBufferQueue overflow, drop oldest buffer id: %{public}u",
        oldest->second.buffer->GetSeqNum());
    sptr<SurfaceBuffer> bufferToCancel = oldest->second.buffer;
    renderBufferQueue_.erase(oldest);
    return bufferToCancel;
}
```

**E14: CopyBufferToSideSurface 侧输出复制 (side_output_surface_processor.cpp L899-943)**

```cpp
bool SideOutputSurfaceProcessor::CopyBufferToSideSurface(sptr<SurfaceBuffer> srcBuffer, int64_t timestamp)
{
    MEDIA_LOG_I("[SIDE_OUTPUT] srcBuffer: w=%{public}d,h=%{public}d,f=%{public}d",
        srcBuffer->GetWidth(), srcBuffer->GetHeight(), srcBuffer->GetFormat());
    sptr<Surface> sideSurface;
    {
        std::lock_guard<std::mutex> lock(lock_);
        sideSurface = sideSurface_;
    }
    if (sideSurface == nullptr) {
        MEDIA_LOG_E("CopyBufferToSideSurface: sideSurface is nullptr");
        return false;
    }
    UpdateConfigIfZero(srcBuffer);
    SurfaceBufferInfo sideBufferInfo;
    if (!RequestSideBuffer(sideBufferInfo, sideSurface)) {
        return false;
    }
    MEDIA_LOG_I("[SIDE_OUTPUT] sideBuffer: w=%{public}d,h=%{public}d,f=%{public}d",
        sideBufferInfo.buffer->GetWidth(), sideBufferInfo.buffer->GetHeight(),
        sideBufferInfo.buffer->GetFormat());
    srcBuffer->InvalidateCache();
    void* srcAddr = srcBuffer->GetVirAddr();
    void* sideAddr = sideBufferInfo.buffer->GetVirAddr();
    uint32_t copySize = (srcSize < sideSize) ? srcSize : sideSize;
    errno_t ret = memcpy_s(sideAddr, copySize, srcAddr, copySize);
    return FlushSideBuffer(sideBufferInfo, timestamp, sideSurface);
}
```

**E15: RequestSideBuffer + FlushSideBuffer (side_output_surface_processor.cpp L946-982)**

```cpp
bool SideOutputSurfaceProcessor::RequestSideBuffer(SurfaceBufferInfo& sideBufferInfo, sptr<Surface> sideSurface)
{
    BufferRequestConfig cfg = requestCfg_;
    if (cfg.width == 0 || cfg.height == 0) {
        cfg.usage = BUFFER_USAGE_CPU_READ | BUFFER_USAGE_CPU_WRITE | BUFFER_USAGE_MEM_DMA;
        cfg.timeout = 0;
        cfg.strideAlignment = STRIDE_ALIGNMENT;  // STRIDE_ALIGNMENT = 32
    }
    GSError err = sideSurface->RequestBuffer(sideBufferInfo.buffer, sideBufferInfo.fence, cfg);
    if (err != GSERROR_OK || sideBufferInfo.buffer == nullptr) {
        MEDIA_LOG_E("RequestSideBuffer failed ret=%{public}d", err);
        return false;
    }
    return true;
}

bool SideOutputSurfaceProcessor::FlushSideBuffer(SurfaceBufferInfo& sideBufferInfo,
    int64_t timestamp, sptr<Surface> sideSurface)
{
    BufferFlushConfig flushConfig = {
        .damage = {0, 0, sideBufferInfo.buffer->GetWidth(), sideBufferInfo.buffer->GetHeight()},
        .timestamp = timestamp
    };
    GSError flushRet = sideSurface->FlushBuffer(sideBufferInfo.buffer, -1, flushConfig);
    if (flushRet == GSERROR_OK) {
        MEDIA_LOG_I("FlushSideBuffer success");
        return true;
    }
    MEDIA_LOG_E("FlushSideBuffer failed ret=%{public}d", flushRet);
    return false;
}
```

**E16: GetVideoSample/HandleSampleTask 侧输出采样 (side_output_surface_processor.cpp L811-888)**

```cpp
void SideOutputSurfaceProcessor::GetVideoSample(int32_t &result)
{
    MEDIA_LOG_I("SideOutputSurfaceProcessor GetVideoSample");
    result = 1;
    {
        std::lock_guard<std::mutex> lock(sampleMutex_);
        if (sampleProcessing_.load()) {
            MEDIA_LOG_W("GetVideoSample: previous sample still processing, skip");
            return;
        }
        sampleResult_ = 1;
        sampleDone_ = false;
        sampleProcessing_ = true;
    }
    if (sampleTask_ != nullptr) {
        sampleTask_->SubmitJobOnce([this]() { HandleSampleTask(); });
    } else {
        HandleSampleTask();
    }
    {
        std::unique_lock<std::mutex> lock(sampleMutex_);
        if (!sampleDoneCond_.wait_for(lock, std::chrono::milliseconds(GET_VIDEO_SAMPLE_TIMEOUT),  // 1000ms
            [this]() { return sampleDone_.load(); })) {
            MEDIA_LOG_E("GetVideoSample: timeout waiting for HandleSampleTask");
        }
        sampleProcessing_ = false;
        result = sampleResult_;
    }
}

void SideOutputSurfaceProcessor::HandleSampleTask()
{
    sptr<SurfaceBuffer> srcBuffer;
    int64_t srcTimestamp = 0;
    {
        std::lock_guard<std::mutex> lock(bufferLock_);
        if (pendingSideSrcBuffer_ != nullptr) {
            srcBuffer = pendingSideSrcBuffer_;
            srcTimestamp = pendingSideTimestamp_;
        } else {
            MEDIA_LOG_W("HandleSampleTask: pendingSideSrcBuffer_ is empty");
        }
    }
    if (srcBuffer == nullptr) {
        DealNoImage();
        return;
    }
    int32_t copyResult = CopyBufferToSideSurface(srcBuffer, srcTimestamp);
    {
        std::lock_guard<std::mutex> lock(sampleMutex_);
        sampleResult_ = copyResult;
        sampleDone_ = true;
        sampleDoneCond_.notify_all();
    }
}
```

**E17: WaitTrigger 条件触发 (side_output_surface_processor.cpp L727-756)**

```cpp
bool SideOutputSurfaceProcessor::WaitTrigger()
{
    FALSE_RETURN_V_MSG(isRunning_.load(), false, "WaitTrigger died.");
    uint32_t consumerSize = 0;
    uint32_t producerSize = 0;
    std::unique_lock<std::mutex> waitLock(waitLock_);
    if (!cvTrigger_.wait_for(waitLock, std::chrono::seconds(WAIT_TRIGGER_TIMEOUT),  // 200ms timeout
        [this, &consumerSize, &producerSize] {
        FALSE_RETURN_V_MSG(isRunning_.load(), true, "Skip WaitTrigger when died.");
        FALSE_RETURN_V_MSG(!isPaused_.load(), false, "Paused, waiting for resume.");
        std::lock(consumerBufferLock_, bufferLock_);
        // consumerSize > 0 或 state == STOPPING 时返回true
        return !isRunning_.load() || state_.load() == ProcessorState::STOPPING || consumerSize > 0;
        })) {
        MEDIA_LOG_I("Video processing timeout.");
        return false;
    }
    if (isPaused_.load()) {
        cvTrigger_.wait(waitLock, [this] {
            return !isPaused_.load() || !isRunning_.load();
        });
        if (!isRunning_.load()) {
            return false;
        }
    }
    FALSE_RETURN_V_MSG(isRunning_.load(), true, "Skip WaitTrigger when died.");
    return true;
}
```

**E18: Buffer常量定义 (side_output_surface_processor.cpp L21-27)**

```cpp
constexpr OHOS::HiviewDFX::HiLogLabel LABEL = { LOG_CORE, LOG_DOMAIN_SYSTEM_PLAYER, "SideOutputSurfaceProcessor" };
constexpr uint32_t WAIT_FOR_EVER = std::numeric_limits<uint32_t>::max();
constexpr uint32_t BUFFER_QUEUE_SIZE = 5;
constexpr int32_t STRIDE_ALIGNMENT = 32;
constexpr int32_t WAIT_TRIGGER_TIMEOUT = 200;
constexpr int32_t GET_VIDEO_SAMPLE_TIMEOUT = 1000;
constexpr size_t MAX_RENDER_BUFFER_QUEUE_SIZE = 5;
```

**E19: UpdateRequestConfigFromBuffer 动态配置更新 (side_output_surface_processor.cpp L346-369)**

```cpp
bool SideOutputSurfaceProcessor::UpdateRequestConfigFromBuffer(const SurfaceBufferInfo& bufferInfo)
{
    if (!isBufferQueueReady_.load()) {
        isBufferQueueReady_ = true;
        requestCfg_.usage = bufferInfo.buffer->GetUsage();
        requestCfg_.timeout = 0;
        requestCfg_.strideAlignment = STRIDE_ALIGNMENT;
        requestCfg_.width = bufferInfo.buffer->GetWidth();
        requestCfg_.height = bufferInfo.buffer->GetHeight();
        requestCfg_.format = bufferInfo.buffer->GetFormat();
        needPrepareBuffers_.store(true);
        return true;
    }
    if (requestCfg_.width != bufferInfo.buffer->GetWidth() ||
            requestCfg_.height != bufferInfo.buffer->GetHeight()) {
        requestCfg_.width = bufferInfo.buffer->GetWidth();
        requestCfg_.height = bufferInfo.buffer->GetHeight();
        requestCfg_.format = bufferInfo.buffer->GetFormat();
        MEDIA_LOG_E("Resolution changed: %{public}u x %{public}u", requestCfg_.width, requestCfg_.height);
        return false;  // 触发分辨率变更处理
    }
    return false;
}
```

**E20: DealNoImage 无数据降级处理 (side_output_surface_processor.cpp L982-988)**

```cpp
void SideOutputSurfaceProcessor::DealNoImage()
{
    std::lock_guard<std::mutex> lock(sampleMutex_);
    sampleResult_ = 1;  // 失败标记
    MEDIA_LOG_W("HandleSampleTask: no data available");
}
```

---

## 核心流程图

```
上游Pipeline
    ↓ (Surface帧)
consumerSurface_
    ↓ AcquireBuffer + OnConsumerBufferAvailable
consumerBufferQueue_
    ↓
GetConsumerAndProducerBuffer (同时获取consumer+producer缓冲)
    ↓
ProcessBuffer
    ├─ memcpy_s(src→dst) 零拷贝复制
    ├─ consumerSurface_->ReleaseBuffer(src)
    └─ OutputBuffer(dst)
         ├─ HandleRenderBufferOverflow (renderQueue>5时丢弃最旧)
         ├─ renderBufferQueue_[seqNum] = dst
         └─ callback_->OnBufferAvailable()

producerSurface_ ← OnProducerBufferReleased回调持续补充缓冲
    ↓ (Surface帧，送给下游Pipeline)
下游Pipeline

---
GetVideoSample (外部触发)
    → HandleSampleTask
         → CopyBufferToSideSurface → RequestSideBuffer → FlushSideBuffer
         → sideSurface_ → 外部预览/录制消费者
```

---

## 与同族 PostProcessor 的关系

| PostProcessorType | 处理器 | 场景 |
|-------------------|--------|------|
| SUPER_RESOLUTION | SuperResolutionPostProcessor | 超分 |
| CAMERA_INSERT_FRAME | CameraPostProcessor | 插入帧 |
| CAMERA_MP_PWP | CameraPostProcessor | 逐行后处理 |
| **SIDE_OUTPUT** | **SideOutputSurfaceProcessor** | **边录制边预览/多路输出** |

SideOutputSurfaceProcessor 与 SuperResolutionPostProcessor (S100)、CameraPostProcessor (S127) 同属 VideoPostProcessorType 枚举，通过 VideoPostProcessorFactory::CreateVideoPostProcessor 创建。

---

## 关键设计

1. **三 Surface 协作**：consumerSurface 消费上游、producerSurface 输出下游、sideSurface 输出副本科；producerSurface 与 consumerSurface 配对通过 RegisterReleaseListener 形成闭环
2. **Worker Thread 流水线**：Init 创建工作线程，WaitTrigger 等待 consumerBufferQueue 非空或超时（200ms），ProcessBuffers 循环处理
3. **零拷贝复制**：ProcessBuffer 使用 memcpy_s 将帧从 consumer 缓冲复制到 producer 缓冲，避免 GPU 回读
4. **SideSurface 异步采样**：GetVideoSample/HandleSampleTask 通过 Task 单例异步执行 CopyBufferToSideSurface，结果通过 sampleDoneCond_ 通知
5. **渲染队列防溢**：MAX_RENDER_BUFFER_QUEUE_SIZE=5，超限时丢弃最旧帧
6. **分辨率变更响应**：UpdateRequestConfigFromBuffer 检测分辨率变化，触发 CancelOldBuffersOnResolutionChange 清空旧缓冲
