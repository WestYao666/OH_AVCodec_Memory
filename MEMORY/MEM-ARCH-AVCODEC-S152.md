# MEM-ARCH-AVCODEC-S152.md

## 主题

**TaskThread 线程管理框架与 SurfaceTools Surface 生命周期管理——双Utility组件五态机与单例映射表**

## 概述

AVCodec 的 TaskThread 和 SurfaceTools 是 services/utils 目录下的两个核心 Utility 组件。TaskThread 提供了五态机（STARTED/PAUSING/PAUSED/STOPPING/STOPPED）的线程生命周期管理，支持同步/异步启停、500ms 自醒节拍和 pthread_setname_np 命名；SurfaceTools 则是 Surface 生命周期管理器，以单例模式通过 surfaceProducerMap_ 映射表追踪每个 surface 的 ownerId，提供 RegisterReleaseListener / CleanCache / ReleaseSurface 三段式资源释放流程。

---

## 源码文件行号级 Evidence

### 1. TaskThread 五态枚举定义

**文件**: `services/utils/include/task_thread.h`
**行数**: 69行

```cpp
// L39-45
enum class RunningState {
    STARTED,     // 运行中，可执行任务
    PAUSING,     // 正在暂停（过渡态）
    PAUSED,      // 已暂停，500ms 自醒节拍
    STOPPING,    // 正在停止（过渡态）
    STOPPED,     // 已停止，线程退出
};
```

**分析**: 五态机覆盖了线程生命周期的完整路径：启动 → 运行 → 暂停 → 停止。PAUSING/STOPPING 是过渡态，防止并发状态污染。

---

### 2. TaskThread 运行状态原子变量

**文件**: `services/utils/include/task_thread.h`
**行数**: 69行

```cpp
// L59
std::atomic<RunningState> runningState_;  // 线程安全的状态标识
```

**分析**: 使用 `std::atomic` 保证多线程环境下的无锁状态读写，是五态机状态切换的基础。

---

### 3. TaskThread 默认 handler 实现

**文件**: `services/utils/include/task_thread.h`
**行数**: 69行

```cpp
// L61
std::function<void()> handler_ = [this] { doTask(); };  // 默认空循环
```

**分析**: 默认 handler 是空操作，派生类（如 CodecServer/VideoDecoder）通过 RegisterHandler 注入实际任务逻辑，实现模板方法模式。

---

### 4. TaskThread::Run() 主循环与 500ms 自醒节拍

**文件**: `services/utils/task_thread.cpp`
**行数**: 175行

```cpp
// L151-175
void TaskThread::Run()
{
    auto ret = pthread_setname_np(pthread_self(), name_.data());  // L153: 线程命名
    for (;;) {
        if (runningState_.load() == RunningState::STARTED) {
            handler_();  // L157: 执行注册的任务
        }
        std::unique_lock lock(stateMutex_);
        if (runningState_.load() == RunningState::PAUSING || runningState_.load() == RunningState::PAUSED) {
            runningState_ = RunningState::PAUSED;
            syncCond_.notify_all();
            constexpr int timeoutMs = 500;  // L163: 500ms 自醒节拍
            syncCond_.wait_for(lock, std::chrono::milliseconds(timeoutMs),
                               [this] { return runningState_.load() != RunningState::PAUSED; });
        }
        if (runningState_.load() == RunningState::STOPPING || runningState_.load() == RunningState::STOPPED) {
            runningState_ = RunningState::STOPPED;
            syncCond_.notify_all();
            break;  // L171: 线程退出
        }
    }
}
```

**分析**: Run() 是 TaskThread 的核心循环。500ms 超时保证即使没有任务也能定期检查状态变化，防止永久阻塞。pthread_setname_np 设置线程名，便于调试。

---

### 5. TaskThread::Start() 同步启动

**文件**: `services/utils/task_thread.cpp`
**行数**: 175行

```cpp
// L54-68
void TaskThread::Start()
{
    std::unique_lock lock(stateMutex_);
    if (runningState_.load() == RunningState::STOPPING) {
        syncCond_.wait(lock, [this] { return runningState_.load() == RunningState::STOPPED; });
    }
    if (runningState_.load() == RunningState::STOPPED) {
        if (loop_ != nullptr) {
            if (loop_->joinable()) {
                loop_->join();
            }
            loop_ = nullptr;
        }
    }
    runningState_ = RunningState::STARTED;
    if (!loop_) {
        loop_ = std::make_unique<std::thread>(&TaskThread::Run, this);  // L67: 创建新线程
    }
    syncCond_.notify_all();
}
```

**分析**: Start() 确保线程从 STOPPED 状态才可重启，若处于 STOPPING 过渡态则阻塞等待。线程按需创建（lazy init）。

---

### 6. TaskThread::Stop() 同步停止

**文件**: `services/utils/task_thread.cpp`
**行数**: 175行

```cpp
// L69-83
void TaskThread::Stop()
{
    std::unique_lock lock(stateMutex_);
    if (runningState_.load() != RunningState::STOPPED) {
        runningState_ = RunningState::STOPPING;  // L71: 触发 STOPPING 过渡态
        syncCond_.notify_all();
        syncCond_.wait(lock, [this] { return runningState_.load() == RunningState::STOPPED; });
        if (loop_ != nullptr) {
            if (loop_->joinable()) {
                loop_->join();  // L76: 等待线程结束
            }
            loop_ = nullptr;
        }
    }
}
```

**分析**: Stop() 是同步停止，调用方会阻塞直到线程完全退出。通过 STOPPING 过渡态确保 Run() 中的 break 逻辑有机会执行。

---

### 7. TaskThread::Pause() 状态切换

**文件**: `services/utils/task_thread.cpp`
**行数**: 175行

```cpp
// L87-99
void TaskThread::Pause()
{
    std::unique_lock lock(stateMutex_);
    switch (runningState_.load()) {
        case RunningState::STARTED: {
            runningState_ = RunningState::PAUSING;
            syncCond_.wait(lock, [this] {
                return runningState_.load() == RunningState::PAUSED || runningState_.load() == RunningState::STOPPED;
            });
            break;
        }
        // ... STOPPING/PAUSING 也各自等待
    }
}
```

**分析**: Pause() 是可中断的暂停操作。若状态为 STARTED 则进入 PAUSING 并等待变为 PAUSED；若处于 STOPPING 则不等直接等待 STOPPED。

---

### 8. TaskThread::StopAsync() 异步停止

**文件**: `services/utils/task_thread.cpp`
**行数**: 175行

```cpp
// L101-108
void TaskThread::StopAsync()
{
    std::unique_lock lock(stateMutex_);
    if (runningState_.load() != RunningState::STOPPING && runningState_.load() != RunningState::STOPPED) {
        runningState_ = RunningState::STOPPING;
        syncCond_.notify_all();  // 不等待线程退出
    }
}
```

**分析**: StopAsync() 触发 STOPPING 但不等待线程结束，适合在析构函数中调用，避免死锁。

---

### 9. TaskThread 两参数构造

**文件**: `services/utils/task_thread.cpp`
**行数**: 175行

```cpp
// L35-36
TaskThread::TaskThread(std::string_view name, std::function<void()> handler) : TaskThread(name)
{
    handler_ = std::move(handler);
    loop_ = std::make_unique<std::thread>(&TaskThread::Run, this);  // 构造即启动线程
}
```

**分析**: 两参数构造器允许在构造时直接指定 handler 并启动线程，实现 RAII 风格的线程管理。

---

### 10. SurfaceTools 单例访问点

**文件**: `services/utils/surface_tools.cpp`
**行数**: 107行

```cpp
// L25-29
SurfaceTools &SurfaceTools::GetInstance()
{
    static SurfaceTools instance;  // C++11 线程安全局部静态变量单例
    return instance;
}
```

**分析**: 使用 local static 实现 Meyers' Singleton，保证线程安全且避免 heap 分配。

---

### 11. SurfaceTools::RegisterReleaseListener 注册释放回调

**文件**: `services/utils/surface_tools.cpp`
**行数**: 107行

```cpp
// L29-48
bool SurfaceTools::RegisterReleaseListener(int32_t instanceId, sptr<Surface> surface,
    OnReleaseFunc callback, OHSurfaceSource type)
{
    CHECK_AND_RETURN_RET_LOGW(surface != nullptr, false, "Unexpected param");
    uint64_t id = surface->GetUniqueId();  // L33: 获取 surface 唯一 ID
    std::lock_guard<std::mutex> lock(mutex_);
    GSError err = surface->RegisterReleaseListener(callback);  // L35: 注册到 GraphicServer
    surface->SetSurfaceSourceType(type);  // L41: 标记 source 类型
    surfaceProducerMap_[id] = instanceId;  // L42: 映射表登记
    return true;
}
```

**分析**: RegisterReleaseListener 完成三件事：① 调用 surface->RegisterReleaseListener 向底层 GraphicServer 注册回调；② 设置 surface 类型；③ 将 surface 的 uniqueId 映射到 instanceId，便于后续 CleanCache/ReleaseSurface 验证 owner。

---

### 12. SurfaceTools::RegisterReleaseListener（两参数回调重载）

**文件**: `services/utils/surface_tools.cpp`
**行数**: 107行

```cpp
// L49-67
bool SurfaceTools::RegisterReleaseListener(int32_t instanceId, sptr<Surface> surface,
    OnReleaseFuncWithSequenceAndFence callback, OHSurfaceSource type)
{
    CHECK_AND_RETURN_RET_LOGW(surface != nullptr, false, "Unexpected param");
    uint64_t id = surface->GetUniqueId();
    std::lock_guard<std::mutex> lock(mutex_);
    GSError err = surface->RegisterReleaseListener(callback);  // 同样注册到 GS
    surface->SetSurfaceSourceType(type);
    surfaceProducerMap_[id] = instanceId;
    return true;
}
```

**分析**: 两参数版本使用带 sequence 和 fence 的回调，适合需要等待 fence 完成才知道 buffer 释放的场景（如 DMA-BUF 同步）。

---

### 13. SurfaceTools::CleanCache 清理 surface 缓存

**文件**: `services/utils/surface_tools.cpp`
**行数**: 107行

```cpp
// L74-83
void SurfaceTools::CleanCache(int32_t instanceId, sptr<Surface> surface, bool cleanAll)
{
    if (surface == nullptr) return;
    uint64_t id = surface->GetUniqueId();
    std::lock_guard<std::mutex> lock(mutex_);
    auto iter = surfaceProducerMap_.find(id);
    if (iter != surfaceProducerMap_.end() && iter->second == instanceId) {
        surface->CleanCache(cleanAll);  // L80: 调用 GraphicServer 清理缓存
    }
}
```

**分析**: CleanCache 是三段式释放的第二步。在验证 owner 一致性后调用 surface->CleanCache，cleanAll=true 时强制清理所有 buffer，否则只清理主动持有的 buffer。

---

### 14. SurfaceTools::ReleaseSurface 彻底释放 surface

**文件**: `services/utils/surface_tools.cpp`
**行数**: 107行

```cpp
// L85-100
void SurfaceTools::ReleaseSurface(int32_t instanceId, sptr<Surface> surface, bool cleanAll, bool abadon)
{
    if (surface == nullptr) return;
    uint64_t id = surface->GetUniqueId();
    std::lock_guard<std::mutex> lock(mutex_);
    auto iter = surfaceProducerMap_.find(id);
    if (iter != surfaceProducerMap_.end() && iter->second == instanceId) {
        surface->CleanCache(cleanAll);  // L90: 先清理
        surface->UnRegisterReleaseListener();  // L93: 注销回调
        surface->SetSurfaceSourceType(OHSurfaceSource::OH_SURFACE_SOURCE_DEFAULT);  // L94: 恢复默认
        if (abadon) {
            surfaceProducerMap_.erase(iter);  // L96: 从映射表移除
        }
    }
}
```

**分析**: ReleaseSurface 是三段式释放的第三步（最后清理）。完成后 surface 从映射表移除（若 abadon=true），彻底切断与 instanceId 的关联。

---

### 15. surfaceProducerMap_ 单例映射表

**文件**: `services/utils/include/surface_tools.h`
**行数**: 41行

```cpp
// L39
std::unordered_map<uint64_t, int32_t> surfaceProducerMap_;  // surfaceId → instanceId
```

**分析**: surfaceProducerMap_ 是 SurfaceTools 的核心数据结构，以 surface 的 uniqueId 为 key，存储当前的 owner instanceId。该映射表在 RegisterReleaseListener 时写入，在 ReleaseSurface（abadon=true）时清除，是验证操作权限的唯一依据。

---

### 16. BlockQueue 模板类默认容量

**文件**: `services/utils/include/block_queue.h`
**行数**: 168行

```cpp
// L18-19
namespace {
constexpr size_t DEFAULT_QUEUE_SIZE = 10;
}
```

**分析**: BlockQueue 默认队列容量为 10，超过容量时 Push 侧阻塞（condFull_.wait），队列空时 Pop 侧阻塞（condEmpty_.wait）。

---

### 17. BlockQueue Push 操作满时阻塞

**文件**: `services/utils/include/block_queue.h`
**行数**: 168行

```cpp
// L63-65
if (que_.size() >= capacity_) {
    condFull_.wait(lock, [this] { return !isActive_ || que_.size() < capacity_; });
}
```

**分析**: 当队列满时，Push 侧等待直到消费者 Pop 消费后才继续，实现生产者-消费者同步。

---

### 18. BlockQueue SetActive(false) 唤醒阻塞等待

**文件**: `services/utils/include/block_queue.h`
**行数**: 168行

```cpp
// L135-142
void BlockQueue::SetActive(bool active, bool cleanData = true)
{
    std::lock_guard<std::mutex> lock(mutex_);
    isActive_ = active;
    if (!active) {
        if (cleanData) ClearUnprotected();
        condEmpty_.notify_one();  // L141: 唤醒 Pop 侧
    }
}
```

**分析**: SetActive(false) 用于优雅关闭队列：设置 isActive_=false 并清理数据后唤醒所有等待中的 Pop 操作，使其返回空值。

---

### 19. TaskThread::PauseAsync 异步暂停

**文件**: `services/utils/task_thread.cpp`
**行数**: 175行

```cpp
// L109-115
void TaskThread::PauseAsync()
{
    std::unique_lock lock(stateMutex_);
    if (runningState_.load() == RunningState::STARTED) {
        runningState_ = RunningState::PAUSING;
        syncCond_.notify_all();
    }
}
```

**分析**: PauseAsync 只触发状态切换为 PAUSING，不等待 PAUSED 确认，适合在持有锁时调用避免死锁。

---

### 20. utils.h AlignUp 内存对齐工具

**文件**: `services/utils/include/utils.h`
**行数**: 46行

```cpp
// L27-32
template <typename T, typename U>
constexpr T AlignUp(T num, U alignment)
{
    return (alignment > 0) ?
        (static_cast<uint64_t>((num + static_cast<MakeUnsigned<T>>(alignment) - 1)) &
         static_cast<uint64_t>((~(static_cast<MakeUnsigned<T>>(alignment) - 1)))) : num;
}
```

**分析**: AlignUp 是 2 的幂次对齐工具，用于 CodecBuffer/DMA-BUF 等内存对齐计算，避免手动位运算错误。

---

### 21. utils.h SleepFor 跨平台睡眠

**文件**: `services/utils/include/utils.h`
**行数**: 46行

```cpp
// L22-24
inline void SleepFor(unsigned ms)
{
    constexpr int factor = 1000;
    usleep(ms * factor);
}
```

**分析**: SleepFor 封装 usleep，提供更直观的毫秒接口，避免与 sleep() 的秒级接口混淆。

---

## 架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                    TaskThread (五态机)                          │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  RunningState: STARTED → PAUSING → PAUSED → STOPPING → STOPPED │
│  └──────────────────────────────────────────────────────────┘  │
│                           │                                     │
│          Start()         │         Stop() / StopAsync()        │
│               ────────────────                                │
│                     pthread_create                             │
│                     Run() loop (500ms tick)                   │
│                     handler_() ← 可注册自定义任务               │
│                                                                 │
│  应用层: VideoDecoder / AudioCodecAdapter / CodecServer 等    │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│               SurfaceTools (单例映射表管理器)                   │
│                                                                 │
│  surfaceProducerMap_: unordered_map<uint64_t, int32_t>          │
│           key=surface->GetUniqueId() → value=instanceId         │
│                                                                 │
│  RegisterReleaseListener(instanceId, surface, callback)         │
│       → surface->RegisterReleaseListener(callback)             │
│       → surfaceProducerMap_[id] = instanceId                   │
│                                                                 │
│  CleanCache(instanceId, surface, cleanAll)                       │
│       → 验证 ownerId 一致                                      │
│       → surface->CleanCache(cleanAll)                          │
│                                                                 │
│  ReleaseSurface(instanceId, surface, cleanAll, abadon)          │
│       → surface->CleanCache()                                  │
│       → surface->UnRegisterReleaseListener()                   │
│       → surface->SetSurfaceSourceType(DEFAULT)                 │
│       → surfaceProducerMap_.erase(id) if abadon                │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                BlockQueue<T> (模板生产者-消费者队列)            │
│                                                                 │
│  Push() → 队列满时阻塞在 condFull_                              │
│  Pop()  → 队列空时阻塞在 condEmpty_                             │
│  SetActive(false) → 唤醒所有 Pop，结束队列生命周期               │
│                                                                 │
│  DEFAULT_QUEUE_SIZE = 10                                        │
└─────────────────────────────────────────────────────────────────┘
```

---

## 关联记忆 ID

| 关联记忆 | 关系 |
|---|---|
| S14 | MediaEngine Filter Chain — TaskThread 作为 Filter 间数据传递的驱动引擎 |
| S20 | PostProcessing — TaskThread 驱动 PostProcessing 的 DynamicController |
| S34 | MuxerFilter — TaskThread 驱动 MuxerFilter 的数据处理循环 |
| S39 | VideoDecoder — TaskThread 驱动 VideoDecoder 的 SendFrame 管线 |
| S45 | SurfaceCodec — SurfaceTools 管理 SurfaceCodec 的 surface 生命周期 |
| S154 | VideoDecoder 与 RenderSurface — TaskThread 驱动 VideoDecoder + RenderSurface 的 BlockQueue 交换 |
| S167 | MediaCodec 核心引擎 — MediaCodec 内部使用 TaskThread 驱动Plugins::DataCallback |

---

## 关键结论

1. **TaskThread 五态机** 是 AVCodec 各组件的统一线程管理抽象，STARTED/PAUSING/PAUSED/STOPPING/STOPPED 五态覆盖完整生命周期，500ms 自醒节拍防止永久阻塞。

2. **SurfaceTools 单例 + surfaceProducerMap_** 是 Surface 生命周期管理的核心机制，通过映射表验证操作权限，三段式释放（Register → CleanCache → ReleaseSurface）确保资源不泄漏。

3. **BlockQueue** 是 TaskThread 与其他组件（如 VideoDecoder RenderSurface 之间的 BlockQueue 三队列）的数据传递基础，提供线程安全的阻塞队列能力。

4. **命名规范**：pthread_setname_np 限制线程名最大 16 字符，TaskThread name_ 须控制在 15 字符以内。

---

## 元数据

- **行数**: 175+107+168+46 = 496行（4文件）
- **类别**: Utils / ThreadManagement / SurfaceLifecycle
- **维护者**: Builder Agent
- **状态**: pending_approval