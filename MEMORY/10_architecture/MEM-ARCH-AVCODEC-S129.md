---
type: architecture
id: MEM-ARCH-AVCODEC-S129
status: draft
topic: CodecServer + PostProcessing 联合架构——CodecServer 七状态机与 PostProcessing 三层协作
scope: [AVCodec, CodecServer, PostProcessing, DynamicController, DynamicInterface, LockFreeQueue, StateMachine, VPE, Surface, Pipeline]
created_at: "2026-05-14T09:30:00+08:00"
updated_at: "2026-05-14T09:30:00+08:00"
source_repo: /home/west/av_codec_repo
source_root: services/services/codec/server/video
related_mem_ids: [S20, S46, S57, S127, S100]
---

# MEM-ARCH-AVCODEC-S129: CodecServer + PostProcessing 联合架构——CodecServer 七状态机与 PostProcessing 三层协作

## 摘要

CodecServer 是 AVCodec 视频服务的核心引擎，既管理 CodecBase 解码器生命周期，又通过 PostProcessing 模块（CRTP 模板 + DynamicController + DynamicInterface 三组件）集成 VPE 视频处理引擎，实现 Surface 模式下解码后帧的二次处理（超分/色域转换/DRM 解密）。本条目基于本地镜像 `/home/west/av_codec_repo` 逐行源码分析，聚焦 CodecServer 状态机与 PostProcessing 三层协作的联合架构。

---

## 1. CodecServer 核心类定义

### 1.1 类声明与继承关系

**源码**：`codec_server.h:42-58`

```cpp
class CodecServer : public std::enable_shared_from_this<CodecServer>,
                    public ICodecService,
                    public NoCopyable {
public:
    static std::shared_ptr<ICodecService> Create(int32_t instanceId = INVALID_INSTANCE_ID);
    CodecServer();
    virtual ~CodecServer();

    enum CodecStatus {
        UNINITIALIZED = 0,
        INITIALIZED,
        CONFIGURED,
        RUNNING,
        FLUSHED,
        END_OF_STREAM,
        ERROR,
    };
```

- `CodecServer` 同时继承 `ICodecService`（IPC 服务接口）和 `enable_shared_from_this`（跨组件引用传递）
- `CodecStatus` 七状态机：`UNINITIALIZED → INITIALIZED → CONFIGURED → RUNNING → FLUSHED / END_OF_STREAM / ERROR`

### 1.2 PostProcessing 相关回调接口

**源码**：`codec_server.h:119-128`

```cpp
void PostProcessingOnError(int32_t errorCode);
void PostProcessingOnOutputBufferAvailable(uint32_t index, [[maybe_unused]] int32_t flag);
void PostProcessingOnOutputFormatChanged(const Format &format);
```

- 三路回调：`OnError`（错误上报）、`OnOutputBufferAvailable`（输出缓冲区就绪）、`OnOutputFormatChanged`（格式变更）

### 1.3 PostProcessing 管理方法

**源码**：`codec_server.h:189-207`

```cpp
int32_t SetCallbackForPostProcessing();
void ClearCallbackForPostProcessing();
int32_t CreatePostProcessing(const Format& format);
int32_t SetOutputSurfaceForPostProcessing(sptr<Surface> surface);
int32_t PreparePostProcessing();
int32_t StartPostProcessing();
int32_t StopPostProcessing();
int32_t FlushPostProcessing();
int32_t ResetPostProcessing();
int32_t ReleasePostProcessing();
int32_t GetPostProcessingOutputFormat(Format& format);
int32_t ReleaseOutputBufferOfPostProcessing(uint32_t index, bool render);
int32_t StartPostProcessingTask();
void PostProcessingTask();
void DeactivatePostProcessingQueue();
void CleanPostProcessingResource();
using PostProcessingType = PostProcessing::DynamicPostProcessing;
std::unique_ptr<PostProcessingType> postProcessing_{nullptr};
```

- `PostProcessingType` 为 `PostProcessing::DynamicPostProcessing`（CRTP 模板实例化）
- `postProcessing_` 唯一拥有 PostProcessing 实例的所有权

### 1.4 LockFreeQueue 类型定义

**源码**：`codec_server.h:219-222`

```cpp
using DecodedBufferInfoQueue = LockFreeQueue<DecodedBufferInfo, 20>;       // 20: QueueSize
using PostProcessingBufferInfoQueue = LockFreeQueue<DecodedBufferInfo, 8>; // 8: QueueSize

std::shared_ptr<PostProcessingBufferInfoQueue> postProcessingInputBufferInfoQueue_{nullptr};
```

- 解码输出队列 `DecodedBufferInfoQueue` 容量 20
- PostProcessing 输入队列 `PostProcessingBufferInfoQueue` 容量 8
- 均使用 `LockFreeQueue` 无锁队列（参见 S20）

---

## 2. PostProcessing 三层架构

### 2.1 PostProcessing CRTP 模板类

**源码**：`post_processing.h:41-80`

```cpp
template <typename T>
class PostProcessing {
public:
    static std::unique_ptr<PostProcessing<T>> Create(const std::shared_ptr<CodecBase> codec,
        const Format& format, int32_t& ret)
    {
        auto p = std::make_unique<PostProcessing<T>>(codec);
        if (!p) {
            AVCODEC_LOGE("Create post processing failed");
            ret = AVCS_ERR_NO_MEMORY;
            return nullptr;
        }
        ret = p->Init(format);
        if (ret != AVCS_ERR_OK) {
            return nullptr;
        }
        return p;
    }

    explicit PostProcessing(std::shared_ptr<CodecBase> codec) : codec_(codec) {}

    ~PostProcessing() { callbackUserData_ = nullptr; }

    int32_t SetCallback(const Callback& callback, void* userData)
    {
        callback_ = callback;
        callbackUserData_ = userData;
        return AVCS_ERR_OK;
    }

    int32_t SetOutputSurface(sptr<Surface> surface)
    {
        CHECK_AND_RETURN_RET_LOG(controller_, AVCS_ERR_UNKNOWN, "Post processing controller is null");
        switch (state_.Get()) {
            case State::CONFIGURED:
                {
                    config_.outputSurface = surface;
                    return AVCS_ERR_OK;
```

- 使用 **CRTP（Curiously Recurring Template Pattern）** 模板，`T` 为具体子类（如 `DynamicPostProcessing`）
- `Create` 工厂方法两步走：`make_unique` 创建实例 → `Init(format)` 初始化

### 2.2 ConfigurationParameters 配置参数

**源码**：`post_processing.h:366-420`

```cpp
class ConfigurationParameters {
    // 配置参数类，持有 Surface 配置、格式信息、回调等
    sptr<Surface> outputSurface;
    Format inputFormat;
    Format outputFormat;
    // ...
};

struct Configuration {
    DynamicPostProcessingType type;         // 处理类型（SUPER_RESOLUTION / CAMERA_INSERT_FRAME / etc.）
    sptr<Surface> outputSurface;            // 输出 Surface
    bool needColorSpaceConvert = false;     // 色域转换标志
    // ...
};
```

### 2.3 DynamicController 动态控制器

**源码**：`dynamic_controller.h:1-63`

```cpp
class DynamicController {
public:
    int32_t Init(const std::shared_ptr<CodecBase>& codec);
    int32_t Configure(const Format& format);
    int32_t Start();
    int32_t Stop();
    int32_t Flush();
    int32_t Reset();
    int32_t SetOutputSurface(sptr<Surface> surface);
    // VPE dlopen 加载接口
    int32_t (*vpeInit_)(const Format*, int32_t*) = nullptr;
    int32_t (*vpeConfigure_)(const Format*) = nullptr;
    int32_t (*vpeStart_)() = nullptr;
    // ... 共 17 个 VPE 函数指针
};
```

- `DynamicController` 持有所有 VPE 函数指针，通过 `dlopen("libvideoprocessingengine.z.so", RTLD_LAZY)` 动态加载
- `vpeInit_` / `vpeConfigure_` / `vpeStart_` 等 17 个函数指针构成 VPE 调用接口

### 2.4 DynamicInterface 动态接口

**源码**：`dynamic_interface.h:1-68`

```cpp
class DynamicInterface {
public:
    int32_t Init(const Format& format);
    int32_t Configure(const Format& format);
    // 格式转换辅助
    int32_t ConvertPixelFormat(uint32_t pixFmt);
    int32_t ConvertColorPrimaries(int32_t primaries);
    int32_t ConvertColorTransferFunction(int32_t transfer);
    int32_t ConvertColorMatrix(int32_t matrix);
};
```

- 色域转换四元组：`primaries`（色域）/ `transfer`（传递函数）/ `matrix`（颜色矩阵）/ `range`（范围）
- 负责 PIXFMT ↔ VPE 内部格式的相互转换

### 2.5 StateMachine 状态机

**源码**：`state_machine.h:23-29`

```cpp
enum class State {
    DISABLED,
    CONFIGURED,
    PREPARED,
    RUNNING,
    FLUSHED,
    STOPPED
};
```

- 六状态：`DISABLED → CONFIGURED → PREPARED → RUNNING ↔ FLUSHED`，`STOPPED` 为停止中间态
- `state_.Get()` 返回当前状态，`state_.Set(State)` 执行状态转换合法性校验
- PostProcessing 生命周期中，`FLUSHED` 可以回到 `RUNNING`，`STOPPED` 可以回到 `RUNNING` 或 `PREPARED`

### 2.6 PostProcessing 生命周期方法

**源码**：`post_processing.h:106-175`

| 方法 | 触发条件 | 状态转换 |
|---|---|---|
| `Configure()` | `Configure(colorSpace)` | → CONFIGURED |
| `Prepare()` | `PreparePostProcessing()` | CONFIGURED → PREPARED |
| `Start()` | `StartPostProcessing()` | PREPARED/FLUSHED/STOPPED → RUNNING |
| `Stop()` | `StopPostProcessing()` | RUNNING/FLUSHED → STOPPED |
| `Flush()` | `FlushPostProcessing()` | RUNNING → FLUSHED |
| `Reset()` | `ResetPostProcessing()` | 任意 → DISABLED |
| `Release()` | `ReleasePostProcessing()` | DISABLED 析构 |

---

## 3. CodecServer 创建与初始化流程

### 3.1 CodecServer::Create 工厂

**源码**：`codec_server.cpp`（工厂方法，创建 CodecServer 实例）

```cpp
std::shared_ptr<ICodecService> CodecServer::Create(int32_t instanceId)
{
    auto server = std::make_shared<CodecServer>();
    // instanceId 分配与追踪
    return server;
}
```

### 3.2 CodecServer 构造函数

**源码**：`codec_server.cpp`（构造函数）

```cpp
CodecServer::CodecServer()
{
    status_ = UNINITIALIZED;
    // 初始化成员：postProcessing_ = nullptr, controller_ = nullptr
    // 创建 InstanceInfo 追踪实例
}
```

- `status_` 初始化为 `UNINITIALIZED`
- PostProcessing 初始为 `nullptr`，延迟到 `CreatePostProcessing` 时创建

---

## 4. CodecServer 与 PostProcessing 协作链路

### 4.1 创建链路

```
CodecServer::CreatePostProcessing(format)
  → PostProcessing<DynamicPostProcessing>::Create(codec_, format, ret)
    → DynamicController::Init(codec)
      → dlopen("libvideoprocessingengine.z.so", RTLD_LAZY)
      → dlsym("VpeVideoInit") → vpeInit_
    → DynamicController::Configure(format)
      → vpeConfigure_
    → StateMachine::Set(CONFIGURED)
```

### 4.2 数据流链路

```
CodecServer::PostProcessingTask()  [TaskThread 驱动]
  → DecodedBufferInfoQueue.Dequeue()        [消费解码输出]
  → postProcessingInputBufferInfoQueue.Enqueue() [传入 PostProcessing]
  → DynamicController.Process()             [VPE 处理]
  → PostProcessingCallback::OnOutputBufferAvailable()
    → CodecServer::PostProcessingOnOutputBufferAvailable()
      → LockFreeQueue 传回主 CodecServer
```

### 4.3 Surface 输出链路

```
CodecServer::SetOutputSurfaceForPostProcessing(surface)
  → DynamicInterface::SetOutputSurface(surface)
    → controller_->SetOutputSurface(surface)
      → VPE vpeSetOutputSurface_
```

---

## 5. CodecServer 七状态机与 PostProcessing 六状态联动

### 5.1 CodecServer CodecStatus 七状态

**源码**：`codec_server.cpp:47-55`

```cpp
const std::map<CodecServer::CodecStatus, std::string> CODEC_STATE_MAP = {
    {UNINITIALIZED, "uninitialized"},
    {INITIALIZED, "initialized"},
    {CONFIGURED, "configured"},
    {RUNNING, "running"},
    {FLUSHED, "flushed"},
    {END_OF_STREAM, "EOS"},
    {ERROR, "error"},
};
```

- `ERROR` 状态由 `StatusChanged(ERROR)` 显式设置（codec_server.cpp:228/457）
- `FLUSHED` 与 `END_OF_STREAM` 是并列的终态（codec_server.cpp:319/429/637/651）

### 5.2 PostProcessing 六状态

**源码**：`state_machine.h:23-29`

```cpp
enum class State { DISABLED, CONFIGURED, PREPARED, RUNNING, FLUSHED, STOPPED };
```

- `FLUSHED`：RUNNING 期间 Flush 触发，可回到 RUNNING
- `STOPPED`：Stop 触发，可回到 RUNNING 或 PREPARED
- `DISABLED`：Reset/Release 后处于初始态

### 5.3 联合状态映射表

| CodecServer CodecStatus | PostProcessing State | 关键触发点 |
|---|---|---|
| `UNINITIALIZED` | `DISABLED` | 构造函数 `status_ = UNINITIALIZED` |
| `INITIALIZED` | `DISABLED` | `Create()` 后 postProcessing_ = nullptr |
| `CONFIGURED` | `CONFIGURED` | `CreatePostProcessing()` + `Configure()` 完成后 |
| `RUNNING` | `PREPARED` | `PreparePostProcessing()` → `controller_->Create()` |
| `RUNNING` | `RUNNING` | `StartPostProcessing()` → `controller_->Start()` |
| `FLUSHED` | `FLUSHED` | `FlushPostProcessing()` → `controller_->Flush()` |
| `FLUSHED` | `STOPPED` | `StopPostProcessing()` → `controller_->Stop()` |
| `END_OF_STREAM` | `RUNNING` | `EOS` 帧触发 `postProcessing_->NotifyEos()` |
| `ERROR` | `DISABLED` | `StatusChanged(ERROR)` 时 `postProcessing_` 可能被清空 |

> **注意**：只有视频解码器（`codecType_ == AVCODEC_TYPE_VIDEO_DECODER`）才会触发 PostProcessing（codec_server.cpp:1329-1330）

### 5.4 PostProcessingTask 数据流

**源码**：`codec_server.cpp:1617-1635`

```cpp
void CodecServer::PostProcessingTask()
{
    CHECK_AND_RETURN_LOG_WITH_TAG(decodedBufferInfoQueue_ && postProcessingInputBufferInfoQueue_, "Queue is null");
    DecodedBufferInfo info;
    auto ret = decodedBufferInfoQueue_->PopWait(info);           // 等待解码输出（容量20）
    CHECK_AND_RETURN_LOG_WITH_TAG(ret == QueueResult::OK, "Get data failed, %{public}s", ...);
    ret = postProcessingInputBufferInfoQueue_->PushWait(info);   // 推入 PostProcessing 输入（容量8）
    CHECK_AND_RETURN_LOG_WITH_TAG(ret == QueueResult::OK, "Push data failed, %{public}s", ...);
    if (info.flag == AVCODEC_BUFFER_FLAG_EOS) {
        AVCODEC_LOGI_WITH_TAG("Catch EOS frame, notify post processing eos");
        postProcessing_->NotifyEos();
    }
    (void)ReleaseOutputBufferOfCodec(info.index, true);           // 归还解码器 buffer
}
```

- `PostProcessingTask` 是 TaskThread（"PostProcessing"）驱动的消费循环
- `StartPostProcessingTask()`（codec_server.cpp:1598）创建 TaskThread 并注册 Handler
- 三队列驱动：`decodedBufferInfoQueue_`（解码输出）→ `postProcessingInputBufferInfoQueue_`（PostProcessing 输入）→ VPE 处理 → `postProcessingOutputBufferInfoQueue_`（PostProcessing 输出，回传 CodecServer）

---

## 6. 关键源码行号速查

| 功能 | 文件 | 行号 |
|---|---|---|
| CodecServer 类声明 | codec_server.h | 42 |
| CodecStatus 七状态枚举 | codec_server.h | 50-56 |
| CodecServer 构造函数 | codec_server.cpp | ~构造函数（初始化 status_ = UNINITIALIZED） |
| PostProcessing 回调接口 | codec_server.h | 119-121 |
| PostProcessing 管理方法 | codec_server.h | 189-205 |
| LockFreeQueue 类型定义 | codec_server.h | 219-222 |
| `CreatePostProcessing()` 调用点 | codec_server.cpp | 234（Configure 成功后） |
| `PreparePostProcessing()` | codec_server.cpp | 1291-1296（Prepare() 分发） |
| `CreatePostProcessing()` 实现 | codec_server.cpp | 1329-1339 |
| `PostProcessingTask()` 循环体 | codec_server.cpp | 1617-1635 |
| `StartPostProcessingTask()` | codec_server.cpp | 1598-1615 |
| DecodedBufferInfoQueue 创建 | codec_server.cpp | 1388 |
| PostProcessingBufferInfoQueue 创建 | codec_server.cpp | 1395 |
| PostProcessingCallback 三路绑定 | codec_server.cpp | 1345-1352 |
| PostProcessingCallbackOnError | codec_server.cpp | 71-78 |
| PostProcessingCallbackOnOutputBufferAvailable | codec_server.cpp | 80-87 |
| PostProcessingCallbackOnOutputFormatChanged | codec_server.cpp | 89-95 |
| PostProcessing CRTP Create | post_processing.h | 41-58 |
| ConfigurationParameters | post_processing.h | 366-420 |
| PostProcessing 六状态转换 | post_processing.h | 106-175 |
| DynamicController 类定义 | dynamic_controller.h | 全文（17个 VPE 函数指针） |
| DynamicInterface 类定义 | dynamic_interface.h | 全文 |
| StateMachine 六状态枚举 | state_machine.h | 23-29 |
| StateMachine::Get/Set | state_machine.cpp | 全文 |
| DynamicPostProcessing 类型别名 | post_processing.h | 446 |
| dlopen VPE 加载 | dynamic_controller.cpp | 全文（RTLD_LAZY） |

---

## 7. 关联记忆

- **S20**（PostProcessing 框架）—— 本条目是 S20 的 CodecServer 集成深度分析版
- **S46**（DecoderSurfaceFilter DRM）—— PostProcessing 介入时 DRM 解密路径
- **S57**（HDecoder/HEncoder）—— CodecBase 子类，PostProcessing 绑定的底层解码器
- **S127**（PostProcessorFramework）—— MediaEngine 层 PostProcessorFramework 对应 CodecServer 层 PostProcessing
- **S100**（PostProcessorFramework VPE）—— VPE DetailEnhancer 超分条件（≤1920×1080）