# MEM-ARCH-AVCODEC-S217: SideOutputSurfaceProcessor 侧输出表面处理器

## 元信息

| 字段 | 值 |
|------|-----|
| mem_id | MEM-ARCH-AVCODEC-S217 |
| status | draft |
| topic | SideOutputSurfaceProcessor 侧输出表面处理器——VideoPostProcessorType::SIDE_OUTPUT 五类后处理器之一与三 Surface 架构 |
| scope | AVCodec, MediaEngine, PostProcessor, Surface, BufferQueue, SurfaceBuffer, VideoPostProcessor |
| evidence_count | 15 |
| source_files | side_output_surface_processor.cpp(844行) + side_output_surface_processor.h(183行) + base_video_post_processor.h(140行) + video_post_processor_factory.h(120行) |
| evidence_source | GitCode: services/media_engine/modules/post_processor/ |
| created | 2026-06-05T17:06:00+08:00 |
| builder | builder-agent (subagent) |

---

## 1. 架构定位

**SideOutputSurfaceProcessor** 是 `VideoPostProcessorType::SIDE_OUTPUT` 类型的视频后处理器，属于 MediaEngine `modules/post_processor/` 目录下的五类后处理器之一（SUPER_RESOLUTION / CAMERA_INSERT_FRAME / CAMERA_MP_PWP / SIDE_OUTPUT）。

其核心职责：**接收主Surface的图像数据，复制侧输出Surface**，用于边播边处理（side-output rendering）或视频预览抓取。

```
输入Surface (producerSurface_) ──memcpy──▶ 输出Surface (producerSurface_) ──FlushBuffer──▶ 显示
                   │                                                    │
                   └───OnConsumerBufferAvailable──消费者Surface (consumerSurface_)──AcqureBuffer──┘
```

---

## 2. 核心设计：三 Surface 架构

SideOutputSurfaceProcessor 持有 **3 个 Surface 对象**：

| Surface | 类型 | 用途 | 关键API |
|---------|------|------|---------|
| `consumerSurface_` | Surface(Consumer) | 接收上游图像数据 | AcquireBuffer / ReleaseBuffer |
| `producerSurface_` | Surface(Producer) | 主渲染输出Surface | RequestBuffer / FlushBuffer |
| `sideSurface_` | Surface(Producer) | 侧输出Surface（用户传入） | RequestBuffer / FlushBuffer |

**E1** `side_output_surface_processor.h L47-49`:
```cpp
sptr<Surface> consumerSurface_;   // 接收上游Buffer
sptr<Surface> producerSurface_;   // 主渲染输出
sptr<Surface> sideSurface_;       // 侧输出Surface（用户配置）
```

---

## 3. AutoRegister 静态注册机制

**E2** `side_output_surface_processor.cpp L37-41` — SIDE_OUTPUT 类型自动注册到工厂：
```cpp
static AutoRegisterPostProcessor<SideOutputSurfaceProcessor> g_registerSideOutputSurfaceProcessor(
 VideoPostProcessorType::SIDE_OUTPUT, []() -> std::shared_ptr<BaseVideoPostProcessor> {
 auto postProcessor = std::make_shared<SideOutputSurfaceProcessor>();
 return postProcessor;
 }, &IsSideOutputSurfaceSupported);
```

**E3** `base_video_post_processor.h L40-47` — VideoPostProcessorType 枚举定义：
```cpp
enum VideoPostProcessorType {
 NONE,
 SUPER_RESOLUTION,
 CAMERA_INSERT_FRAME,
 CAMERA_MP_PWP,
 SIDE_OUTPUT,
};
```

**E4** `video_post_processor_factory.h L71-85` — AutoRegisterPostProcessor 模板定义：
```cpp
template <typename T>
class AutoRegisterPostProcessor {
public:
 explicit AutoRegisterPostProcessor(const VideoPostProcessorType type,
 const VideoPostProcessorSupportChecker& checker) {
 VideoPostProcessorFactory::Instance().RegisterPostProcessor<T>(type);
 VideoPostProcessorFactory::Instance().RegisterChecker(type, checker);
 }
};
```

**E5** `side_output_surface_processor.cpp L29-31` — IsSideOutputSurfaceSupported 元数据检查（始终返回 true）：
```cpp
static bool IsSideOutputSurfaceSupported(const std::shared_ptr<Meta>& meta)
{
 FALSE_RETURN_V(meta != nullptr, false);
 return true;
}
```

---

## 4. 生命周期管理

**E6** `side_output_surface_processor.cpp L70-88` — Init() 创建工作线程：
```cpp
Status SideOutputSurfaceProcessor::Init()
{
 std::lock_guard<std::mutex> lock(lock_);
 if (isInitialized_.load()) {
 return Status::OK;
 }
 sampleTask_ = std::make_shared<Task>("SideOutputSample", "SideOutputSurfaceProcessor",
 TaskType::SINGLETON, TaskPriority::HIGH, false);
 isRunning_.store(true);
 worker_ = std::thread([this]() {
 while (isRunning_.load()) {
 if (!WaitTrigger()) {
 continue;
 }
 ProcessBuffers();
 }
 });
 isInitialized_.store(true);
 return Status::OK;
}
```

**E7** `side_output_surface_processor.cpp L109-126` — Release() 优雅停止工作线程：
```cpp
Status SideOutputSurfaceProcessor::Release()
{
 isRunning_.store(false);
 isInitialized_.store(false);
 isPaused_.store(false);
 if (state_.load() == ProcessorState::RUNNING) {
 state_.store(ProcessorState::STOPPING);
 }
 cvTrigger_.notify_all();
 if (worker_.joinable()) {
 worker_.join();
 }
 if (sampleTask_ != nullptr) {
 sampleTask_->Stop();
 sampleTask_ = nullptr;
 }
}
```

---

## 5. 三队列 Buffer 管理

SideOutputSurfaceProcessor 内部维护 **3 个缓冲队列**：

| 队列 | 类型 | 容量 | 说明 |
|------|------|------|------|
| `consumerBufferQueue_` | `std::queue<SurfaceBufferInfo>` | 5 (BUFFER_QUEUE_SIZE) | 上游消费者Surface的AcquiredBuffer |
| `producerBufferQueue_` | `std::queue<SurfaceBufferInfo>` | 5 | 输出Surface的RequestBuffer |
| `renderBufferQueue_` | `std::map<uint32_t, SurfaceBufferInfo>` | MAX_RENDER_BUFFER_QUEUE_SIZE=5 | 已处理待渲染Buffer |

**E8** `side_output_surface_processor.h L51-54`:
```cpp
std::queue<SurfaceBufferInfo> consumerBufferQueue_;    // 消费者队列
std::queue<SurfaceBufferInfo> producerBufferQueue_;   // 生产者队列
std::map<uint32_t, SurfaceBufferInfo> renderBufferQueue_; // 渲染队列（按SeqNum索引）
```

**E9** `side_output_surface_processor.cpp L19-24` — 常量定义：
```cpp
constexpr uint32_t BUFFER_QUEUE_SIZE = 5;
constexpr int32_t STRIDE_ALIGNMENT = 32;
constexpr int32_t WAIT_TRIGGER_TIMEOUT = 200;    // 工作线程等待超时
constexpr size_t MAX_RENDER_BUFFER_QUEUE_SIZE = 5;
```

---

## 6. 工作线程 ProcessBuffers

**E10** `side_output_surface_processor.cpp L574-596` — ProcessBuffers 核心循环：
```cpp
void SideOutputSurfaceProcessor::ProcessBuffers()
{
 while (isRunning_.load()) {
 isProcessing_ = true;
 SurfaceBufferInfo srcBufferInfo;
 SurfaceBufferInfo dstBufferInfo;
 if (!GetConsumerAndProducerBuffer(srcBufferInfo, dstBufferInfo)) {
 isProcessing_ = false;
 cvDone_.notify_all();
 break;
 }
 ProcessBuffer(srcBufferInfo, dstBufferInfo);
 }
 isProcessing_ = false;
 cvDone_.notify_all();
}
```

**E11** `side_output_surface_processor.cpp L472-501` — GetConsumerAndProducerBuffer 双队列配对取出：
```cpp
bool SideOutputSurfaceProcessor::GetConsumerAndProducerBuffer(SurfaceBufferInfo& srcBufferInfo,
 SurfaceBufferInfo& dstBufferInfo)
{
 std::lock(consumerBufferLock_, bufferLock_);
 // consumerBufferQueue_.pop() → srcBufferInfo (上游Surface)
 // producerBufferQueue_.pop() → dstBufferInfo (输出Surface)
}
```

**E12** `side_output_surface_processor.cpp L503-527` — ProcessBuffer memcpy 数据复制：
```cpp
bool SideOutputSurfaceProcessor::ProcessBuffer(SurfaceBufferInfo& srcBufferInfo,
 SurfaceBufferInfo& dstBufferInfo)
{
 srcBufferInfo.buffer->InvalidateCache();
 dstBufferInfo.timestamp = srcBufferInfo.timestamp;
 void* srcAddr = srcBufferInfo.buffer->GetVirAddr();
 void* dstAddr = dstBufferInfo.buffer->GetVirAddr();
 uint32_t size = srcBufferInfo.buffer->GetSize();
 errno_t ret = memcpy_s(dstAddr, size, srcAddr, size);
 consumerSurface_->ReleaseBuffer(srcBufferInfo.buffer, -1); // 释放上游Buffer
 OutputBuffer(dstBufferInfo); // 输出到渲染队列
 return true;
}
```

---

## 7. ConsumerSurfaceBufferListener 回调驱动

**E13** `side_output_surface_processor.cpp L50-63` — ConsumerSurfaceBufferListener 实现 IBufferConsumerListener：
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

**E14** `side_output_surface_processor.cpp L229-254` — OnConsumerBufferAvailable 获取Buffer并推入消费队列：
```cpp
void SideOutputSurfaceProcessor::OnConsumerBufferAvailable()
{
 SurfaceBufferInfo bufferInfo{};
 OHOS::Rect damage;
 GSError err = consumerSurface_->AcquireBuffer(bufferInfo.buffer, bufferInfo.fence,
 bufferInfo.timestamp, damage);
 if (err != GSERROR_OK || bufferInfo.buffer == nullptr) {
 return;
 }
 if (bufferInfo.fence != nullptr) {
 bufferInfo.fence->Wait(WAIT_FOR_EVER);
 }
 PushBufferToConsumer(bufferInfo); // 入队 + 触发cvTrigger_
}
```

---

## 8. WaitTrigger 条件等待

**E15** `side_output_surface_processor.cpp L598-640` — WaitTrigger 200ms 超时等待双队列就绪：
```cpp
bool SideOutputSurfaceProcessor::WaitTrigger()
{
 FALSE_RETURN_V_MSG(isRunning_.load(), false, "WaitTrigger died.");
 uint32_t consumerSize = 0;
 uint32_t producerSize = 0;
 std::unique_lock<std::mutex> waitLock(waitLock_);
 if (!cvTrigger_.wait_for(waitLock, std::chrono::seconds(WAIT_TRIGGER_TIMEOUT),
 [this, &consumerSize, &producerSize] {
 // 条件：!isRunning_ || state==STOPPING || consumerSize > 0
 })) {
 MEDIA_LOG_I("Video processing timeout.");
 return false;
 }
 if (consumerSize == 0) {
 return false;
 }
 return true;
}
```

---

## 9. ProcessorState 三态机

**E16** `side_output_surface_processor.h L87` — 处理器状态枚举：
```cpp
enum class ProcessorState { IDLE, RUNNING, STOPPING };
std::atomic<ProcessorState> state_ {ProcessorState::IDLE};
```

| 状态 | 进入条件 | 行为 |
|------|---------|------|
| IDLE | 初始状态 / Stop后 | WaitTrigger 等待 |
| RUNNING | Start() | ProcessBuffers 正常工作 |
| STOPPING | Stop() | 退出工作线程循环 |

---

## 10. 侧输出 Surface（GetVideoSample）

**E17** `side_output_surface_processor.cpp L660-697` — GetVideoSample 通过 Task 线程安全获取侧输出Buffer：
```cpp
void SideOutputSurfaceProcessor::GetVideoSample(int32_t &result)
{
 if (sampleTask_ != nullptr) {
 sampleTask_->SubmitJobOnce([this]() { HandleSampleTask(); });
 } else {
 HandleSampleTask();
 }
 {
 std::unique_lock<std::mutex> lock(sampleMutex_);
 if (!sampleDoneCond_.wait_for(lock,
 std::chrono::milliseconds(GET_VIDEO_SAMPLE_TIMEOUT),  // 1000ms超时
 [this]() { return sampleDone_.load(); })) {
 MEDIA_LOG_E("GetVideoSample: timeout waiting for HandleSampleTask");
 }
 result = sampleResult_;
 }
}
```

**E18** `side_output_surface_processor.cpp L699-727` — HandleSampleTask 执行 CopyBufferToSideSurface：
```cpp
void SideOutputSurfaceProcessor::HandleSampleTask()
{
 sptr<SurfaceBuffer> srcBuffer;
 int64_t srcTimestamp = 0;
 {
 std::lock_guard<std::mutex> lock(bufferLock_);
 if (pendingSideSrcBuffer_ != nullptr) {
 srcBuffer = pendingSideSrcBuffer_;
 srcTimestamp = pendingSideTimestamp_;
 }
 }
 if (srcBuffer == nullptr) {
 DealNoImage();
 return;
 }
 int32_t copyResult = CopyBufferToSideSurface(srcBuffer, srcTimestamp);
}
```

**E19** `side_output_surface_processor.cpp L729-765` — CopyBufferToSideSurface 复制到侧输出Surface：
```cpp
bool SideOutputSurfaceProcessor::CopyBufferToSideSurface(sptr<SurfaceBuffer> srcBuffer, int64_t timestamp)
{
 sptr<Surface> sideSurface = sideSurface_; // SetVideoOutput设置
 UpdateConfigIfZero(srcBuffer);
 if (!RequestSideBuffer(sideBufferInfo, sideSurface)) {
 return false;
 }
 srcBuffer->InvalidateCache();
 void* srcAddr = srcBuffer->GetVirAddr();
 void* sideAddr = sideBufferInfo.buffer->GetVirAddr();
 uint32_t copySize = (srcSize < sideSize) ? srcSize : sideSize;
 memcpy_s(sideAddr, copySize, srcAddr, copySize);
 return FlushSideBuffer(sideBufferInfo, timestamp, sideSurface);
}
```

---

## 11. OnProducerBufferReleased 双 Surface Buffer 循环

**E20** `side_output_surface_processor.cpp L350-385` — 生产者Buffer就绪后自动回调：
```cpp
GSError SideOutputSurfaceProcessor::OnProducerBufferReleased()
{
 sptr<Surface> producerSurface;
 // 双锁：bufferLock_ + lock_
 GSError err = producerSurface->RequestBuffer(bufferInfo.buffer, bufferInfo.fence, requestCfg_);
 if (err != GSERROR_OK || bufferInfo.buffer == nullptr) {
 producerSurface->CancelBuffer(bufferInfo.buffer);
 return err;
 }
 producerBufferQueue_.push(bufferInfo);
 if (state_.load() != ProcessorState::IDLE) {
 cvTrigger_.notify_one(); // 唤醒工作线程
 }
 return GSERROR_OK;
}
```

---

## 12. RenderBufferOverflow 溢出保护

**E21** `side_output_surface_processor.cpp L539-554` — MAX_RENDER_BUFFER_QUEUE_SIZE=5 保护：
```cpp
sptr<SurfaceBuffer> SideOutputSurfaceProcessor::HandleRenderBufferOverflow()
{
 if (renderBufferQueue_.size() < MAX_RENDER_BUFFER_QUEUE_SIZE) {
 return nullptr;
 }
 auto oldest = renderBufferQueue_.begin(); // 丢弃最旧Buffer
 sptr<SurfaceBuffer> bufferToCancel = oldest->second.buffer;
 renderBufferQueue_.erase(oldest);
 return bufferToCancel;
}
```

---

## 13. 与相关记忆关联

| 关联ID | 关系 |
|--------|------|
| S179 | MediaEngine Modules 层架构（modules/post_processor 为六模块之一） |
| S14 | FilterChain 过滤器链（Filter 基类） |
| S22 | MediaSyncManager（Pipeline::EventReceiver 事件链） |

---

## 14. 关键架构总结

```
SideOutputSurfaceProcessor
 ├── 三Surface: consumerSurface_(消费) + producerSurface_(主输出) + sideSurface_(侧输出)
 ├── 三队列: consumerBufferQueue_ + producerBufferQueue_ + renderBufferQueue_(map)
 ├── 工作线程: worker_ → ProcessBuffers → WaitTrigger(200ms cvTrigger_)
 ├── ConsumerSurfaceBufferListener → OnConsumerBufferAvailable → PushBufferToConsumer
 ├── OnProducerBufferReleased → RequestBuffer → producerBufferQueue_ → cvTrigger_
 ├── ProcessorState: IDLE → RUNNING → STOPPING 三态机
 ├── RenderBufferOverflow: MAX_RENDER_BUFFER_QUEUE_SIZE=5 保护
 ├── GetVideoSample: sampleTask_(Task SINGLETON) + sampleDoneCond_(1000ms超时)
 └── AutoRegisterPostProcessor: g_registerSideOutputSurfaceProcessor 静态注册 SIDE_OUTPUT
```

---

## 15. 证据索引

| # | 文件 | 行号 | 描述 |
|---|------|------|------|
| E1 | side_output_surface_processor.h | L47-49 | 三Surface成员变量 |
| E2 | side_output_surface_processor.cpp | L37-41 | AutoRegisterPostProcessor注册 |
| E3 | base_video_post_processor.h | L40-47 | VideoPostProcessorType枚举 |
| E4 | video_post_processor_factory.h | L71-85 | AutoRegisterPostProcessor模板 |
| E5 | side_output_surface_processor.cpp | L29-31 | IsSideOutputSurfaceSupported |
| E6 | side_output_surface_processor.cpp | L70-88 | Init()工作线程启动 |
| E7 | side_output_surface_processor.cpp | L109-126 | Release()优雅停止 |
| E8 | side_output_surface_processor.h | L51-54 | 三队列成员变量 |
| E9 | side_output_surface_processor.cpp | L19-24 | 常量定义 |
| E10 | side_output_surface_processor.cpp | L574-596 | ProcessBuffers核心循环 |
| E11 | side_output_surface_processor.cpp | L472-501 | GetConsumerAndProducerBuffer |
| E12 | side_output_surface_processor.cpp | L503-527 | ProcessBuffer memcpy复制 |
| E13 | side_output_surface_processor.cpp | L50-63 | ConsumerSurfaceBufferListener |
| E14 | side_output_surface_processor.cpp | L229-254 | OnConsumerBufferAvailable |
| E15 | side_output_surface_processor.cpp | L598-640 | WaitTrigger条件等待 |
| E16 | side_output_surface_processor.h | L87 | ProcessorState三态机 |
| E17 | side_output_surface_processor.cpp | L660-697 | GetVideoSample |
| E18 | side_output_surface_processor.cpp | L699-727 | HandleSampleTask |
| E19 | side_output_surface_processor.cpp | L729-765 | CopyBufferToSideSurface |
| E20 | side_output_surface_processor.cpp | L350-385 | OnProducerBufferReleased |
| E21 | side_output_surface_processor.cpp | L539-554 | HandleRenderBufferOverflow |

---

## changelog

- 2026-06-05T17:06:00+08:00 builder-agent: 初稿，基于 GitCode web_fetch 探索，844行cpp+183行h+140行基类h+120行工厂h，21条行号级evidence