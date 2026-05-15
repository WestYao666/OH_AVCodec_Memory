# MEM-ARCH-AVCODEC-S152 — TaskThread + SurfaceTools 双 Utility 组件架构

## Metadata

| Field | Value |
|-------|-------|
| mem_id | MEM-ARCH-AVCODEC-S152 |
| topic | TaskThread 线程管理框架与 SurfaceTools Surface 生命周期管理——双Utility组件五态机与单例映射表 |
| scope | AVCodec, Utils, Thread, Surface, TaskThread, SurfaceTools, TaskDispatch, Lifecycle, Pipeline |
| status | pending_approval |
| source | Builder Agent — 本地镜像 + web_fetch 交叉验证 |
| created | 2026-05-15T13:25:00+08:00 |
|关联 | S14(FilterChain) / S20(PostProcessing) / S34(MuxerFilter) / S39(VideoDecoder) / S45(SurfaceDecoderFilter) / S46(DecoderSurfaceFilter) |

---

## 1. 概述

`services/utils/` 是 AVCodec 模块的通用 Utility 层，包含两个独立组件：

- **TaskThread**：通用线程管理框架，提供五态机生命周期控制（STARTED/PAUSING/PAUSED/STOPPING/STOPPED）
- **SurfaceTools**：Surface 生命周期管理器，单例模式，持有 `surfaceProducerMap_` 映射表追踪 Surface 与实例的绑定关系

两个组件均被 CodecServer 等核心组件直接调用，是 Pipeline 数据流之外的基础设施支撑。

**文件分布**：

```
services/utils/
├── include/
│   ├── task_thread.h      (69行)  类声明
│   ├── task_thread.cpp    (175行) 实现
│   ├── surface_tools.h    (41行)  类声明
│   ├── surface_tools.cpp  (107行) 实现
│   ├── block_queue.h      (168行) 有界阻塞队列
│   ├── scope_guard.h      (63行)  RAII 作用域守卫
│   └── utils.h            (46行)  工具函数
├── task_thread.cpp
├── surface_tools.cpp
└── BUILD.gn
```

**总代码量**：utils 目录总计 ~669 行（不含 BUILD.gn），是 AVCodec 最小颗粒度的 Utility 层。

---

## 2. TaskThread 线程管理框架

### 2.1 五态机

```
STOPPED ──Start()──> STARTED ──Pause()──> PAUSING ──等待──> PAUSED
                                    │                         │
                                    └──(STOPPING/STOPPED) <───┘
STARTED ──Stop()──> STOPPING ──wait──> STOPPED
STARTED ──StopAsync()──> STOPPING
```

| 状态 | 说明 |
|------|------|
| STOPPED | 初始态/终止态，线程已退出 |
| STARTED | 运行中，执行 handler_() |
| PAUSING | 过渡态，等待 PAUSED 或 STOPPED 确认 |
| PAUSED | 暂停态，500ms 自醒窗口（`syncCond_.wait_for(lock, chrono::milliseconds(500))`） |
| STOPPING | 停止中，notify_all 唤醒 Run 循环退出 |

关键实现：`task_thread.cpp:110-150`（Run 循环）

```cpp
// task_thread.cpp:110-150
void TaskThread::Run()
{
    auto ret = pthread_setname_np(pthread_self(), name_.data()); // 线程名最长16字节
    for (;;) {
        if (runningState_.load() == RunningState::STARTED) {
            handler_();  // 用户自定义任务回调
        }
        std::unique_lock lock(stateMutex_);
        if (runningState_.load() == RunningState::PAUSING || runningState_.load() == RunningState::PAUSED) {
            runningState_ = RunningState::PAUSED;
            syncCond_.notify_all();
            constexpr int timeoutMs = 500;  // 500ms 自醒窗口
            syncCond_.wait_for(lock, std::chrono::milliseconds(timeoutMs),
                               [this] { return runningState_.load() != RunningState::PAUSED; });
        }
        if (runningState_.load() == RunningState::STOPPING || runningState_.load() == RunningState::STOPPED) {
            runningState_ = RunningState::STOPPED;
            syncCond_.notify_all();
            break;
        }
    }
}
```

### 2.2 两套构造函数

```cpp
// task_thread.h:34-36
explicit TaskThread(std::string_view name);                              // ① 无线程，自管理 Start/Stop
TaskThread(std::string_view name, std::function<void()> handler);        // ② 立即创建线程
```

① 用于 CodecServer 等延迟启动场景（`codec_server.h:174` 持有 `shared_ptr<TaskThread>`）：
```cpp
// codec_server.h:174
std::shared_ptr<TaskThread> inputParamTask_ = nullptr;
// codec_server.h:184
std::shared_ptr<TaskThread> releaseBufferTask_{nullptr};
// codec_server.h:223
std::unique_ptr<TaskThread> postProcessingTask_{nullptr};
```

② 用于 AudioCodecWorker 等立即启动场景（`audio_codec_worker.h` 使用 OS_AuCodecIn/OS_AuCodecOut 命名线程）。

### 2.3 核心方法

| 方法 | 行为 |
|------|------|
| `Start()` | 线程已存在时等待 STOPPED，然后创建新线程 |
| `Stop()` | 同步等待 STOPPING→STOPPED，join 线程 |
| `StopAsync()` | 异步设置 STOPPING，不等待 |
| `Pause()` | 同步等待 PAUSING→PAUSED，含 STOPPING 打断 |
| `PauseAsync()` | 异步设置 PAUSING |
| `RegisterHandler()` | 替换默认 doTask 行为 |

### 2.4 使用场景

TaskThread 驱动整个 AVCodec 异步管线：

| 使用方 | 文件:行号 | 线程命名 |
|--------|---------|---------|
| CodecServer | codec_server.h:174 | inputParamTask_（编码输入参数） |
| CodecServer | codec_server.h:184 | releaseBufferTask_（缓冲区释放） |
| CodecServer | codec_server.h:223 | postProcessingTask_（后处理） |
| FCodec | fcodec.cpp | SendFrame TaskThread（软件解码发送） |
| FCodec | fcodec.cpp | ReceiveFrame TaskThread（软件解码接收） |
| AudioCodecWorker | audio_codec_worker.cpp | OS_AuCodecIn/OS_AuCodecOut |
| AvcEncoder | avc_encoder.cpp | SendFrame/ReceiveFrame TaskThread |

---

## 3. SurfaceTools Surface 生命周期管理

### 3.1 单例模式

```cpp
// surface_tools.h:22
class SurfaceTools {
public:
    static SurfaceTools &GetInstance();  // 局部静态单例
private:
    std::mutex mutex_;
    std::unordered_map<uint64_t, int32_t> surfaceProducerMap_;  // SurfaceUniqueId → instanceId
};
```

### 3.2 核心映射表

```cpp
// surface_tools.cpp:46-54
bool SurfaceTools::RegisterReleaseListener(int32_t instanceId, sptr<Surface> surface,
    OnReleaseFunc callback, OHSurfaceSource type)
{
    uint64_t id = surface->GetUniqueId();  // Surface 全局唯一ID
    std::lock_guard<std::mutex> lock(mutex_);
    GSError err = surface->RegisterReleaseListener(callback);
    surface->SetSurfaceSourceType(type);
    surfaceProducerMap_[id] = instanceId;  // 登记：Surface→Codec实例映射
    return true;
}
```

关键流程：
1. `RegisterReleaseListener` 将 `instanceId` 与 Surface 的 `uniqueId` 绑定
2. `CleanCache(instanceId, surface, cleanAll)` 清理 Surface 缓存（仅当映射匹配）
3. `ReleaseSurface(instanceId, surface, cleanAll, abadon)` 清理缓存 + 反注册监听器 + 移除映射

### 3.3 三接口分工

| 方法 | surface_tools.cpp | 功能 |
|------|-------------------|------|
| `RegisterReleaseListener(instanceId, surface, callback, type)` | L37-55 | 注册释放监听器 + 登记映射 |
| `CleanCache(instanceId, surface, cleanAll)` | L70-79 | 仅清理缓存，保留映射 |
| `ReleaseSurface(instanceId, surface, cleanAll, abadon)` | L81-99 | 清理缓存 + 反注册 + 可选删除映射 |

### 3.4 调用方

| 使用方 | 文件:行号 | 用途 |
|--------|---------|------|
| CodecServer | codec_server.cpp:377 | `SurfaceTools::GetInstance().CleanCache(...)` |
| CodecServer | codec_server.cpp:500 | `SurfaceTools::GetInstance().ReleaseSurface(...)` |
| HDecoder | hdecoder.cpp | 注册 Surface 释放监听器 |
| FCodec | fcodec.cpp | 注册 Surface 释放监听器 |
| RenderSurface | render_surface.cpp | 注册 Surface 释放监听器 |

---

## 4. BlockQueue 有界阻塞队列

```cpp
// services/utils/include/block_queue.h (168行)
// 模板化有界阻塞队列，支持多线程安全入队/出队
// 关键方法：Push/TryPush/Pop/TryPop/Wait Pop
```

BlockQueue 是 TaskThread handler_ 的重要数据源，与 TaskThread 配合构成异步数据流驱动机制（与 S64 AVBuffer Signal/Wait 机制互补）。

---

## 5. ScopeGuard RAII 作用域守卫

```cpp
// scope_guard.h (63行)
// 用法示例：
void Foo() {
    auto fd = open(...);
    ON_SCOPE_EXIT(id) { close(fd); };  // 函数退出时自动关闭 fd
    // ... 可能抛异常的代码 ...
}  // fd 在此自动关闭
```

---

## 6. 与 Pipeline 组件的关联

```
TaskThread（线程管理）
├── CodecServer
│   ├── inputParamTask_    → 处理编码输入参数（codec_server.h:174）
│   ├── releaseBufferTask_ → 处理缓冲区释放（codec_server.h:184）
│   └── postProcessingTask_→ 后处理（codec_server.h:223）
├── FCodec / HDecoder / AvcEncoder / Av1Decoder
│   └── SendFrame / ReceiveFrame 异步双线程
└── AudioCodecWorker
    └── OS_AuCodecIn / OS_AuCodecOut

SurfaceTools（Surface 生命周期）
├── CodecServer::CleanCache(instanceId)  (codec_server.cpp:377)
├── CodecServer::ReleaseSurface(instanceId) (codec_server.cpp:500)
├── HDecoder / FCodec / RenderSurface
│   └── RegisterReleaseListener 注册 Surface 释放回调
└── surfaceProducerMap_ (SurfaceUniqueId → instanceId 单例映射表)
```

---

## 7. Evidence 索引

| # | 文件 | 行号 | 内容摘要 |
|---|------|------|---------|
| 1 | task_thread.h | 34-69 | TaskThread 类声明，五态机枚举，接口方法 |
| 2 | task_thread.cpp | 1-37 | 构造函数，dtor，Start() |
| 3 | task_thread.cpp | 38-58 | Stop() / StopAsync() |
| 4 | task_thread.cpp | 59-85 | Pause() / PauseAsync() |
| 5 | task_thread.cpp | 86-92 | RegisterHandler() |
| 6 | task_thread.cpp | 93-96 | doTask() 默认空实现 |
| 7 | task_thread.cpp | 97-150 | Run() 循环，500ms 自醒，pthread_setname_np |
| 8 | codec_server.h | 174 | `shared_ptr<TaskThread> inputParamTask_` |
| 9 | codec_server.h | 184 | `shared_ptr<TaskThread> releaseBufferTask_` |
| 10 | codec_server.h | 223 | `unique_ptr<TaskThread> postProcessingTask_` |
| 11 | surface_tools.h | 18-41 | SurfaceTools 单例类声明 |
| 12 | surface_tools.cpp | 24-34 | GetInstance() 局部静态单例 |
| 13 | surface_tools.cpp | 37-55 | RegisterReleaseListener + surfaceProducerMap_ 登记 |
| 14 | surface_tools.cpp | 57-67 | RegisterReleaseListener（带 Sequence+Fence） |
| 15 | surface_tools.cpp | 69-79 | CleanCache 仅清理缓存 |
| 16 | surface_tools.cpp | 81-99 | ReleaseSurface 清理+反注册+移除映射 |
| 17 | codec_server.cpp | 377 | SurfaceTools::GetInstance().CleanCache |
| 18 | codec_server.cpp | 500 | SurfaceTools::GetInstance().ReleaseSurface |
| 19 | utils.h | 18-25 | SleepFor(us/ms) / AlignUp / ReinterpretPointerCast |
| 20 | scope_guard.h | 22-50 | ScopeGuard RAII / ON_SCOPE_EXIT 宏 |
| 21 | block_queue.h | 1-168 | 模板化有界阻塞队列（TaskThread 数据源） |
| 22 | audio_codec_worker.cpp | - | TaskThread OS_AuCodecIn/OS_AuCodecOut 驱动音频编解码 |
| 23 | fcodec.cpp | - | TaskThread SendFrame/ReceiveFrame 双线程软件解码 |
| 24 | render_surface.cpp | - | SurfaceTools::RegisterReleaseListener 注册 Surface 释放回调 |

---

## 8. 修订历史

| 日期 | 操作 | 说明 |
|------|------|------|
| 2026-05-15T13:25 | Builder | 草案生成：TaskThread 五态机 + SurfaceTools 单例映射表，本地镜像行号级 evidence |