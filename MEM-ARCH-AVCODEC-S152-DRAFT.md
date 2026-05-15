---
scope: [AVCodec, Utils, Thread, Surface, Lifecycle, TaskThread, SurfaceTools, TaskDispatch]
status: draft
created_by: builder-agent
created_at: 2026-05-15T12:52:00+08:00
summary: TaskThread 线程管理框架与 SurfaceTools Surface 生命周期管理的双Utility架构
evidence_count: 20
source_files: 4
review_status: pending_approval
---

# S152: TaskThread 线程管理框架 + SurfaceTools Surface 生命周期管理

## 1. 主题概述

AVCodec 模块的两大基础 Utility 组件——TaskThread（线程生命周期管理）和 SurfaceTools（Surface 注册与释放管理）。两者均为 services/utils/ 目录下的公共工具，不属于具体 Filter/Codec 引擎，但被 Pipeline 中几乎所有组件依赖。

## 2. 目录位置

```
services/utils/
├── task_thread.cpp          (175行)
├── include/task_thread.h    (69行)
├── surface_tools.cpp        (107行)
└── include/surface_tools.h  (63行)
```

## 3. TaskThread 线程管理框架

### 3.1 设计背景

AVCodec Pipeline 中大量使用独立 TaskThread 驱动数据流循环（ReadLoop/RenderLoop/SendFrame/ReceiveFrame 等）。TaskThread 提供统一的线程生命周期管理，避免每个组件自行管理 pthread/thread 对象。

### 3.2 状态机

TaskThread::RunningState 五态枚举（task_thread.h:46-52）：

| 状态 | 含义 | 合法转换 |
|------|------|---------|
| STOPPED | 线程未启动或已停止 | → STARTED |
| STARTED | 运行中 | → PAUSING / STOPPING |
| PAUSING | 正在暂停（同步等待） | → PAUSED |
| PAUSED | 暂停中（500ms 超时自醒） | → STARTED / STOPPING |
| STOPPING | 正在停止（同步等待） | → STOPPED |

状态转换由 std::atomic<RunningState> 保护（task_thread.h:59），线程安全。

### 3.3 API 完整列表

| 函数 | 行为 | 同步性 |
|------|------|--------|
| `TaskThread(name)` | 构造（STOPPED态，无线程） | - |
| `TaskThread(name, handler)` | 构造+启动线程 | - |
| `Start()` | 若已停止则重建线程并启动 | 同步（等待线程就绪） |
| `Stop()` | 发送STOPPING信号并join等待 | 同步（阻塞直到线程退出） |
| `StopAsync()` | 仅发送STOPPING信号 | 异步（非阻塞） |
| `Pause()` | 发送PAUSING信号并等待PAUSED | 同步（阻塞直到PAUSED） |
| `PauseAsync()` | 仅发送PAUSING信号 | 异步（非阻塞） |
| `RegisterHandler(fn)` | 替换默认 doTask 处理器 | - |

关键实现约束（task_thread.cpp）：
- **Stop() 同步等待**（第67-78行）：若状态为STOPPING，先 wait 等待状态变为 STOPPED，然后 join 线程，保证析构时线程已退出
- **Pause() 500ms 超时自醒**（第132-136行）：`syncCond_.wait_for(lock, chrono::milliseconds(500), predicate)`，防止 Pause 后无人唤醒导致永久阻塞
- **pthread_setname_np 线程命名**（第122-125行）：使用 `name_` 命名线程（最大15字符），方便调试
- **默认 doTask 空循环**（第148-150行）：若派生类未重写 doTask，则无实际操作

### 3.4 使用模式

TaskThread 通常与具体任务循环绑定（task_thread.cpp:31-33）：

```cpp
TaskThread::TaskThread(std::string_view name, std::function<void()> handler)
    : TaskThread(name)
{
    handler_ = std::move(handler);
    loop_ = std::make_unique<std::thread>(&TaskThread::Run, this);
}
```

即：构造时传入业务 handler → Run() 循环调用 handler_()。

## 4. SurfaceTools Surface 生命周期管理

### 4.1 设计背景

Surface（图形surface）是 AVCodec 解码输出/编码输入的核心载体。Surface 生命周期跨越 Codec 引擎和图形系统，需要统一管理 surface→instanceId 的映射关系，避免内存泄漏或 Use-After-Free。

### 4.2 单例模式

SurfaceTools::GetInstance() 静态单例（surface_tools.h:23-27 / surface_tools.cpp:22-27）：

```cpp
SurfaceTools &SurfaceTools::GetInstance()
{
    static SurfaceTools instance;
    return instance;
}
```

### 4.3 核心数据结构

surfaceProducerMap_（surface_tools.h:34）：`unordered_map<uint64_t, int32_t>`，key = surface->GetUniqueId()，value = instanceId。实现 surface→Codec实例 的多对一映射管理。

### 4.4 API 完整列表

| 函数 | 行为 |
|------|------|
| `RegisterReleaseListener(instanceId, surface, callback, type)` | 注册 Surface 释放监听，surfaceProducerMap_ 记录映射 |
| `RegisterReleaseListener(instanceId, surface, callbackWithFence, type)` | 支持 fence+sequence 的重载版本 |
| `CleanCache(instanceId, surface, cleanAll)` | 调用 surface->CleanCache()，仅当 instanceId 匹配时执行 |
| `ReleaseSurface(instanceId, surface, cleanAll, abandon)` | 完整释放：CleanCache → UnRegisterReleaseListener → 擦除映射 |

关键实现（surface_tools.cpp）：
- **RegisterReleaseListener**（第28-47行）：获取 surface->GetUniqueId() → surface->RegisterReleaseListener(callback) → surfaceProducerMap_[id] = instanceId。失败时返回 false。
- **CleanCache**（第49-62行）：仅在 surfaceProducerMap_ 中存在且 instanceId 匹配时才调用 surface->CleanCache()，防止串扰。
- **ReleaseSurface**（第64-82行）：CleanCache + UnRegisterReleaseListener + SetSurfaceSourceType(DEFAULT) + 可选擦除 map。

### 4.5 SurfaceSourceType 枚举

OHSurfaceSource 类型标记（surface_tools.h 包含）：
- `OH_SURFACE_SOURCE_VIDEO`（默认）
- `OH_SURFACE_SOURCE_DEFAULT`

## 5. 与其他 S 系列记忆的关联

| 关联记忆 | 关系 |
|---------|------|
| S14（Filter Chain） | TaskThread 驱动 Filter 的 ReadLoop/RenderLoop |
| S20（PostProcessing） | TaskThread 驱动 DynamicController/DynamicInterface |
| S34/S65/S91（MuxerFilter/MediaMuxer） | TaskThread 驱动 OS_MUXER_WRITE 线程 |
| S39/S53/S54（VideoDecoder系列） | TaskThread 驱动 SendFrame/ReceiveFrame |
| S45/S46（SurfaceDecoderFilter/DecoderSurfaceFilter） | SurfaceTools 管理解码输出 Surface |
| S64（AVBuffer Signal/Wait） | TaskThread 驱动 AVBuffer 异步循环 |
| S23/S24/S26/S28（视频/音频采集Filter） | SurfaceTools 管理采集用 Surface |

## 6. 架构要点总结

- **TaskThread**：统一封装 pthread 的生命周期管理，提供 Start/Stop/Pause 同步语义，500ms pause 超时防止死锁，pthread_setname_np 便于调试
- **SurfaceTools**：单例模式管理 Surface→CodecInstance 的多对一映射，RegisterReleaseListener 注册图形系统回调，CleanCache/ReleaseSurface 组合完成安全清理
- **共性**：均为 services/utils/ 的基础组件，不直接参与编解码逻辑，但被 Pipeline 中所有组件依赖

## 7. Evidence 行号索引

| 文件 | 行号 | 内容 |
|------|------|------|
| task_thread.h | 26-39 | TaskThread 公有 API 声明 |
| task_thread.h | 46-52 | RunningState 五态枚举 |
| task_thread.h | 59 | std::atomic<RunningState> 线程安全状态 |
| task_thread.cpp | 28-33 | TaskThread 构造函数+启动线程 |
| task_thread.cpp | 53-61 | Start() 同步等待实现 |
| task_thread.cpp | 64-78 | Stop() 同步 join 实现 |
| task_thread.cpp | 93-106 | Pause() 同步等待实现 |
| task_thread.cpp | 108-115 | PauseAsync() 异步实现 |
| task_thread.cpp | 122-125 | pthread_setname_np 线程命名 |
| task_thread.cpp | 132-136 | 500ms wait_for 超时自醒 |
| task_thread.cpp | 141-150 | Run() 主循环与状态转换 |
| surface_tools.h | 23-27 | GetInstance 单例实现 |
| surface_tools.h | 34 | surfaceProducerMap_ 数据结构 |
| surface_tools.cpp | 28-47 | RegisterReleaseListener 双版本实现 |
| surface_tools.cpp | 49-62 | CleanCache 实例校验实现 |
| surface_tools.cpp | 64-82 | ReleaseSurface 完整释放实现 |

---
*Builder Agent | 2026-05-15T12:52+08:00 | draft → pending_approval*