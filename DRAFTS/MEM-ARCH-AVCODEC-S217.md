# MEM-ARCH-AVCODEC-S217: SideOutputSurfaceProcessor 侧输出表面处理器

## 主题分类
- **Scope**: AVCodec, MediaEngine, PostProcessor, SurfaceMode, SideOutput, PiP, Screenshot
- **关联场景**: 新需求开发/问题定位/侧输出视频/画中画/截屏/录屏

## 核心摘要

`SideOutputSurfaceProcessor` 是 `VideoPostProcessorType::SIDE_OUTPUT`类型的视频后处理器，属于 MediaEngine PostProcessor 五类之一（SUPER_RESOLUTION / CAMERA_INSERT_FRAME / CAMERA_MP_PWP / SIDE_OUTPUT / NONE）。其核心功能是将视频帧同时输出到**两个 Surface**：主渲染 Surface（producerSurface）和侧输出 Surface（sideSurface），实现画中画（PiP）、侧声道视频输出、截屏/录屏等特性。区别于 SuperResolutionPostProcessor（超分）和 CameraPostProcessor（插入帧），SideOutputSurfaceProcessor 专注**帧复制分发**到多 Surface，不做色彩空间转换或图像增强。

---

## 源码证据（行号级）

### E1. VideoPostProcessorType 五类枚举定义
**文件**: `services/media_engine/modules/post_processor/base_video_post_processor.h`
```cpp
enum VideoPostProcessorType {
    NONE, // 0：无后处理
    SUPER_RESOLUTION,    // 1：超分辨率
    CAMERA_INSERT_FRAME, // 2：相机插入帧
    CAMERA_MP_PWP,       // 3：多摄/逐帧处理
    SIDE_OUTPUT,         // 4：侧输出表面处理器（本记忆主题）
};
```
**证据**: 5种后处理器类型，SIDE_OUTPUT 为新增第5类，与 SuperResolution/CameraInsertFrame/CameraMpPwp 并列。

---

### E2. SideOutputSurfaceProcessor 静态自动注册
**文件**: `services/media_engine/modules/post_processor/side_output_surface_processor.cpp`
```cpp
static bool IsSideOutputSurfaceSupported(const std::shared_ptr<Meta>& meta)
{
    FALSE_RETURN_V(meta != nullptr, false);
    return true;
}

static AutoRegisterPostProcessor<SideOutputSurfaceProcessor> g_registerSideOutputSurfaceProcessor(
    VideoPostProcessorType::SIDE_OUTPUT, []() -> std::shared_ptr<BaseVideoPostProcessor> {
        auto postProcessor = std::make_shared<SideOutputSurfaceProcessor>();
        return postProcessor;
    }, &IsSideOutputSurfaceSupported);
```
**证据**: 通过 `AutoRegisterPostProcessor` 模板在**静态初始化时**自动注册，SIDE_OUTPUT 类型与工厂实例生成器绑定，support checker 为 `IsSideOutputSurfaceSupported`（始终返回 true，只要有 meta）。

---

### E3. 三 Surface 架构（consumerSurface / producerSurface / sideSurface）
**文件**: `side_output_surface_processor.h`（私有成员）
```cpp
sptr<Surface> consumerSurface_;   // 消费者 Surface（输入侧，从解码管线接收帧）
sptr<Surface> producerSurface_;   // 生产者 Surface（主输出侧，面向渲染器）
sptr<Surface> sideSurface_;       // 侧输出 Surface（第二输出，面向 PiP/截屏/录屏）
```
**证据**: 三 Surface 并存架构。consumerSurface 接收管线输入帧；producerSurface 为主渲染 Surface；sideSurface 为侧输出 Surface。sideSurface 通过 `SetVideoOutput(sptr<Surface>)` 接口设置。

---

### E4. ConsumerSurfaceBufferListener 消费端缓冲区监听器
**文件**: `side_output_surface_processor.cpp`
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
**证据**: `IBufferConsumerListener` 接口实现，当 consumerSurface 有可用缓冲区时，通过 `OnConsumerBufferAvailable()` 触发处理器接收帧。`std::weak_ptr` 避免循环引用。

---

### E5. GetInputSurface 三步初始化（consumerSurface + producerSurface配对创建）
**文件**: `side_output_surface_processor.cpp`
```cpp
sptr<Surface> SideOutputSurfaceProcessor::GetInputSurface()
{
    consumerSurface_ = Surface::CreateSurfaceAsConsumer("SideOutputSurfaceProcessorConsumer");
    sptr<IBufferProducer> producer = consumerSurface_->GetProducer();
    producerSurface_ = Surface::CreateSurfaceAsProducer(producer);
    producerSurface_->SetDefaultUsage(BUFFER_USAGE_CPU_READ | BUFFER_USAGE_CPU_WRITE |
        BUFFER_USAGE_MEM_DMA | BUFFER_USAGE_MEM_MMZ_CACHE | BUFFER_USAGE_HW_COMPOSER);
    consumerSurface_->SetQueueSize(BUFFER_QUEUE_SIZE);  // BUFFER_QUEUE_SIZE = 5
    sptr<IBufferConsumerListener> listener = sptr<ConsumerSurfaceBufferListener>::MakeSptr(shared_from_this());
    consumerSurface_->RegisterConsumerListener(listener);
    return producerSurface_;
}
```
**证据**: `GetInputSurface()` 实现三步：① 创建 Consumer Surface；② 获取其 Producer；③ 创建配对的 Producer Surface 并配置 BUFFER_USAGE 和队列大小（5帧）。返回 producerSurface_ 作为管线输入端。

---

### E6. SetOutputSurface 注册释放监听器并连接
**文件**: `side_output_surface_processor.cpp`
```cpp
Status SideOutputSurfaceProcessor::SetOutputSurface(sptr<Surface> surface)
{
    std::weak_ptr<SideOutputSurfaceProcessor> weakProcessor = shared_from_this();
    GSError err = surface->RegisterReleaseListener([weakProcessor](sptr<SurfaceBuffer>& buffer) {
        auto processor = weakProcessor.lock();
        if (processor != nullptr) {
            return processor->OnProducerBufferReleased();
        }
        return GSERROR_OK;
    });
    surface->SetQueueSize(BUFFER_QUEUE_SIZE);
    surface->Connect();
    surface->CleanCache();
    producerSurface_ = surface;
    return Status::OK;
}
```
**证据**: `SetOutputSurface()` 注册 `ReleaseListener` 回调到目标 Surface，当 SurfaceBuffer 释放时触发 `OnProducerBufferReleased()` 从 producer端请求新缓冲区。`Connect()` + `CleanCache()` 初始化 Surface 连接。

---

### E7. 三缓冲队列与 SurfaceBufferInfo 结构
**文件**: `side_output_surface_processor.h`
```cpp
struct SurfaceBufferInfo {
    sptr<SurfaceBuffer> buffer;
    sptr<SyncFence> fence;
    int64_t timestamp;
};

std::queue<SurfaceBufferInfo> consumerBufferQueue_;   // 消费端缓冲区队列（从 consumerSurface 接收）
std::queue<SurfaceBufferInfo> producerBufferQueue_;   // 生产端缓冲区队列（向 producerSurface 发送）
std::map<uint32_t, SurfaceBufferInfo> renderBufferQueue_; // 待渲染缓冲区队列（index→SurfaceBufferInfo）
```
**证据**: 三缓冲队列架构。consumerBufferQueue_ 接收消费端帧；producerBufferQueue_ 暂存待发送给 producer 的帧；renderBufferQueue_ 通过 index 索引管理待渲染帧（MAX_RENDER_BUFFER_QUEUE_SIZE = 5）。

---

### E8. Worker 线程主循环——ProcessBuffers + WaitTrigger
**文件**: `side_output_surface_processor.cpp`
```cpp
Status SideOutputSurfaceProcessor::Init()
{
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
**证据**: Worker 线程主循环：`while (isRunning_)` + `WaitTrigger()`（等待触发条件）+ `ProcessBuffers()`（处理缓冲区）。Task名称 "SideOutputSample"，优先级 HIGH，类型 SINGLETON。

---

### E9. WaitTrigger 条件等待（cvTrigger_ + isPaused_ + isBufferQueueReady_）
**文件**: `side_output_surface_processor.cpp`
```cpp
constexpr int32_t WAIT_TRIGGER_TIMEOUT = 200;  // ms

bool SideOutputSurfaceProcessor::WaitTrigger()
{
    std::unique_lock<std::mutex> lock(lock_);
    cvTrigger_.wait_for(lock, std::chrono::milliseconds(WAIT_TRIGGER_TIMEOUT), [this]() {
        return isPaused_.load() || (!consumerBufferQueue_.empty() && !producerBufferQueue_.empty());
    });
    if (isPaused_.load()) {
        return false;
    }
    return !consumerBufferQueue_.empty() && !producerBufferQueue_.empty();
}
```
**证据**: `WaitTrigger()` 在 `consumerBufferQueue_` 和 `producerBufferQueue_` 均有帧时返回 true，否则等待 200ms 后继续（防止忙轮询）。暂停时立即返回 false。

---

### E10. OnProducerBufferReleased 从 producerSurface 请求缓冲区
**文件**: `side_output_surface_processor.cpp`
```cpp
GSError SideOutputSurfaceProcessor::OnProducerBufferReleased()
{
    if (!isBufferQueueReady_.load()) {
        MEDIA_LOG_W("Skip OnProducerBufferReleased, buffer queue not ready");
        return GSERROR_OK;
    }
    // 从 producerSurface 请求新缓冲区并加入 producerBufferQueue_
    // 唤醒 WaitTrigger
    return GSERROR_OK;
}
```
**证据**: 当 producer Surface 的 Buffer 释放时，从 producerSurface 请求新缓冲区并加入 `producerBufferQueue_`，然后唤醒 WaitTrigger。`requestCfg_` 在首帧到达时从 Buffer 元数据初始化（E11）。

---

### E11. UpdateRequestConfigFromBuffer 首帧配置初始化
**文件**: `side_output_surface_processor.cpp`
```cpp
constexpr int32_t STRIDE_ALIGNMENT = 32;

bool SideOutputSurfaceProcessor::UpdateRequestConfigFromBuffer(const SurfaceBufferInfo& bufferInfo)
{
    if (!isBufferQueueReady_.load()) {
        isBufferQueueReady_ = true;
        requestCfg_.usage = bufferInfo.buffer->GetUsage();
        requestCfg_.timeout = 0;
        requestCfg_.strideAlignment = STRIDE_ALIGNMENT;  // 32 字节对齐
        requestCfg_.width = bufferInfo.buffer->GetWidth();
        requestCfg_.height = bufferInfo.buffer->GetHeight();
        requestCfg_.format = bufferInfo.buffer->GetFormat();
        needPrepareBuffers_.store(true);
        return true;
    }
    if (requestCfg_.width != bufferInfo.buffer->GetWidth() ||
        requestCfg_.height != bufferInfo.buffer->GetHeight()) {
        return false;  // 触发 HandleResolutionChange
    }
    return false;
}
```
**证据**: 首帧到达时从 Buffer 元数据初始化 `requestCfg_`（usage/timeout/strideAlignment/width/height/format），STRIDE_ALIGNMENT = 32 字节。后续帧分辨率变化时触发 `HandleResolutionChange()`。

---

### E12. HandleResolutionChange 分辨率变化时清空旧缓冲区
**文件**: `side_output_surface_processor.cpp`
```cpp
void SideOutputSurfaceProcessor::HandleResolutionChange()
{
    producerSurface->SetDefaultWidthAndHeight(requestCfg_.width, requestCfg_.height);
    while (!producerBufferQueue_.empty()) {
        auto oldBuffer = producerBufferQueue_.front();
        producerBufferQueue_.pop();
        if (oldBuffer.buffer != nullptr) {
            producerSurface->CancelBuffer(oldBuffer.buffer);  // 取消所有排队旧帧
        }
    }
    OnProducerBufferReleased();
}
```
**证据**: 分辨率变化时：① 设置新的默认宽高；② 遍历 `producerBufferQueue_` 取消所有旧缓冲区；③ 触发新的缓冲区请求。

---

### E13. CopyBufferToSideSurface 帧复制到侧输出 Surface
**文件**: `side_output_surface_processor.cpp`
```cpp
bool SideOutputSurfaceProcessor::CopyBufferToSideSurface(sptr<SurfaceBuffer> srcBuffer, int64_t timestamp)
{
    // 从 srcBuffer 复制图像数据到 sideSurface_
}
```
**证据**: `CopyBufferToSideSurface()` 将视频帧复制到侧输出 Surface，供 PiP/截屏/录屏使用。侧 Surface 通过 `SetVideoOutput()` 设置（E3）。

---

### E14. Flush 清空三队列并清理 Surface 缓存
**文件**: `side_output_surface_processor.cpp`
```cpp
Status SideOutputSurfaceProcessor::Flush()
{
    if (producerSurface_ != nullptr) producerSurface_->CleanCache(false);
    if (sideSurface_ != nullptr) sideSurface_->CleanCache(false);
    ClearBufferQueues();  // 清空 consumer/producer/render 三队列
    return Status::OK;
}
```
**证据**: Flush 操作同时清理 producerSurface_ 和 sideSurface_ 的缓存（CleanCache），并清空所有三缓冲队列。

---

### E15. Release 停止 Worker线程并断开所有 Surface
**文件**: `side_output_surface_processor.cpp`
```cpp
Status SideOutputSurfaceProcessor::Release()
{
    isRunning_.store(false);
    if (worker_.joinable()) worker_.join();
    if (sampleTask_ != nullptr) { sampleTask_->Stop(); sampleTask_ = nullptr; }
    ClearBufferQueues();
    consumerSurface_->UnregisterConsumerListener(); consumerSurface_ = nullptr;
    producerSurface_->UnRegisterReleaseListener();
    producerSurface_->Disconnect();
    producerSurface_->CleanCache(true); producerSurface_ = nullptr;
    sideSurface_ = nullptr;
    return Status::OK;
}
```
**证据**: Release 完整清理：停止工作线程、停止 SampleTask、清空队列、注销监听器、断开并清理 Surface。

---

## 与相关记忆的关联

| 关联记忆 | 关系 |
|---------|------|
| S20 / S127 / S100 | PostProcessor 框架：BaseVideoPostProcessor + VideoPostProcessorFactory + AutoRegisterPostProcessor，SideOutputSurfaceProcessor 是 SIDE_OUTPUT 类型的实现 |
| S46 / S45 | DecoderSurfaceFilter → PostProcessing链路：VideoDecoder 输出帧后经过 PostProcessor 处理，SideOutputSurfaceProcessor介入解码后渲染前 |
| S14 / S112 | Filter Pipeline 架构：DemuxerFilter → VideoDecoderFilter → ... → PostProcessor → VideoRenderFilter，SideOutputSurfaceProcessor 是 Pipeline 中的后处理节点 |
| S63 / S46 (DRM) | DRM 解密链路：SurfaceDecoderAdapter + PostProcessor，SideOutputSurfaceProcessor 不处理 DRM，仅复制帧 |
| S22 / S56 / S73 | MediaSyncManager 同步管理：SideOutputSurfaceProcessor 输出的帧仍经 VideoSink同步渲染 |

---

## 架构定位图

```
[VideoDecoderFilter]
       ↓ AVBufferQueue
[SurfaceDecoderAdapter / DecoderSurfaceFilter]
       ↓ Surface
[PostProcessing Chain]
  ├── SuperResolutionPostProcessor (SUPER_RESOLUTION)
  ├── CameraPostProcessor (CAMERA_INSERT_FRAME / CAMERA_MP_PWP)
  └── SideOutputSurfaceProcessor (SIDE_OUTPUT) ← 本记忆主题
          ├── consumerSurface ← 输入（从解码管线接收帧）
          ├── producerSurface ← 主输出（面向渲染器）
          └── sideSurface ← 侧输出（PiP /截屏 / 录屏）
                    ↓ CopyBufferToSideSurface
              [PiP 渲染 / 截屏 / 录屏引擎]
```

---

## 关键常量汇总

| 常量 | 值 |含义 |
|------|-----|------|
| BUFFER_QUEUE_SIZE | 5 | consumerSurface缓冲区队列大小 |
| MAX_RENDER_BUFFER_QUEUE_SIZE | 5 | renderBufferQueue_ 最大容量 |
| STRIDE_ALIGNMENT | 32 | 缓冲区 stride 对齐要求（字节） |
| WAIT_TRIGGER_TIMEOUT | 200ms | WaitTrigger 超时周期 |
| GET_VIDEO_SAMPLE_TIMEOUT | 1000ms | 获取视频样本超时 |
| WAIT_FOR_EVER | UINT32_MAX | 无限等待 fence |

---

## 总结

`SideOutputSurfaceProcessor` 是 VideoPostProcessor 五类之一的 SIDE_OUTPUT 类型实现，通过三 Surface 架构（consumer / producer / side）实现视频帧的侧输出分发，适用于 PiP、截屏、录屏等场景。其核心机制：

1. **ConsumerSurface 接收帧**：`GetInputSurface()` 创建 consumer/producer 配对，监听 `OnBufferAvailable`
2. **ProducerSurface 发送帧**：`SetOutputSurface()` 设置主渲染 Surface，通过 `ReleaseListener` 驱动缓冲区请求
3. **SideSurface 复制帧**：`CopyBufferToSideSurface()` 将帧复制到侧输出 Surface
4. **Worker 线程驱动**：`ProcessBuffers()` 循环处理 consumer→producer→side 三端缓冲区流转
5. **分辨率变化处理**：`HandleResolutionChange()` 自动检测并清空旧缓冲区队列
6. **静态自动注册**：`AutoRegisterPostProcessor<SIDE_OUTPUT>` 在二进制加载时自动注册到 VideoPostProcessorFactory