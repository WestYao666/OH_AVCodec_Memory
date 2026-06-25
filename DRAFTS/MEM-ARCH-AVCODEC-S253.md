---
id: MEM-ARCH-AVCODEC-S253
status: draft
theme: AVCodec Service Utils 工具库
created: 2026-06-25T10:25:00+08:00
scope:
  - AVCodec, Service, Utils, TaskThread, SurfaceTools, BlockQueue, ScopeGuard, Singleton, RAII, ThreadLifecycle, Surface, Graphics, Lifecycle
  - OHOS::MediaAVCodec namespace
  - services/utils/ 目录（未覆盖）
topics:
  - TaskThread 五态生命周期管理线程
  - SurfaceTools Surface生产者-实例ID映射单例（2025年新增）
  - BlockQueue 线程安全阻塞队列模板
  - ScopeGuard RAII 作用域守卫
  - utils.h SleepFor/AlignUp/ReinterpretPointerCast 工具函数
关联场景:
  - 问题定位/新人入项/代码导航
  - Surface生命周期管理
  - 后台线程生命周期管理
  - 内存安全/RAII
关联主题:
  - S50 (TaskThreadPool 多线程池，对比：S50是线程池，这里是单线程)
  - S167 (MediaCodec核心引擎与Utils工具链 - TaskThread in media_codec context，对比：S167是Codec专用，这里是service级通用)
  - S55 (CodecCallback 生命周期)
  - S202/S212/S214 (MediaCodec Filter层)
  - S218 (Native Buffer 管理)
evidence_count: 20
verified: true
local_mirror: /home/west/av_codec_repo/services/utils/
source: GitCode web_fetch https://gitcode.com/openharmony/multimedia_av_codec + 本地镜像
---

# S253: AVCodec Service Utils 工具库

## 概述

`services/utils/` 是 av_codec 服务的公共工具库，提供四类组件：
- **TaskThread**：五态生命周期管理线程（STARTED/PAUSING/PAUSED/STOPPING/STOPPED）
- **SurfaceTools**：Surface Producer → instanceId 映射单例管理器（**2025年新增**，Copyright 2025）
- **BlockQueue**：模板线程安全阻塞队列（capacity感知/isActive状态）
- **ScopeGuard**：RAII 作用域守卫 + ON_SCOPE_EXIT 宏

编译目标：`av_codec_service_utils`（ohos_shared_library），依赖 graphic_surface/surface、hilog、hisysevent、hitrace、init、c_utils

---

## 1. TaskThread 五态生命周期管理线程

### 1.1 类定义

**文件**：`services/utils/include/task_thread.h`

```cpp
enum class RunningState {
    STARTED,   // 运行中
    PAUSING,   // 正在暂停
    PAUSED,    // 已暂停（500ms自醒）
    STOPPING,  // 正在停止
    STOPPED,   // 已停止
};
// 成员变量：name_/runningState_/loop_/handler_/stateMutex_/syncCond_
```

**E1**: task_thread.h L54-60: RunningState 五态枚举（STARTED/PAUSING/PAUSED/STOPPING/STOPPED）
**E2**: task_thread.h L61-66: 全部成员变量声明（name_/runningState_/loop_/handler_/stateMutex_/syncCond_）
**E3**: task_thread.h L31-47: 全部公开方法声明（Start/Stop/StopAsync/Pause/PauseAsync/RegisterHandler）

### 1.2 核心方法实现

**E4**: task_thread.cpp L24: 构造函数，runningState_初始化为STOPPED，loop_=nullptr
**E5**: task_thread.cpp L40-44: handler_委托构造函数，创建std::thread
**E6**: task_thread.cpp L49-68: Start()，原子状态+条件变量协调，thread按需创建
**E7**: task_thread.cpp L73-90: Stop()，同步等待STOPPED状态，join线程
**E8**: task_thread.cpp L93-100: StopAsync()，仅标记STOPPING，不等待
**E9**: task_thread.cpp L101-123: Pause()，三路switch (STARTED→PAUSING/STOPPING→等待STOPPED/PAUSING→等待PAUSED)
**E10**: task_thread.cpp L125-132: PauseAsync()，仅标记PAUSING
**E11**: task_thread.cpp L135-139: RegisterHandler，handler_赋值

### 1.3 Run() 循环与500ms自醒

**E12**: task_thread.cpp L147-175: Run()循环
- pthread_setname_np(L148) 设置线程名（最长16字符）
- L155-157：STARTED状态执行handler_()
- L159-167：PAUSING/PAUSED状态等待500ms自醒(syncCond_.wait_for(L164 constexpr int timeoutMs = 500))
- L168-173：STOPPING/STOPPED状态退出循环

### 1.4 与S50 TaskThreadPool的区别

| | S50 TaskThreadPool | S253 TaskThread |
|---|---|---|
| 线程数 | 线程池（多线程） | 单线程 |
| 用途 | CodecEngine后台任务 | service级通用线程 |
| 生命周期 | 池管理 | 五态机（STARTED/PAUSING/PAUSED/STOPPING/STOPPED） |
| 自醒 | - | 500ms timeout |

---

## 2. SurfaceTools Surface生产者映射单例（2025年新增）

### 2.1 类定义

**文件**：`services/utils/include/surface_tools.h`（Copyright 2025）

```cpp
class SurfaceTools {
public:
    static SurfaceTools &GetInstance();  // 单例
    bool RegisterReleaseListener(instanceId, surface, callback, type);
    bool RegisterReleaseListener(instanceId, surface, callbackWithSeqFence, type);
    void CleanCache(instanceId, surface, cleanAll);
    void ReleaseSurface(instanceId, surface, cleanAll, abadon);
private:
    std::unordered_map<uint64_t, int32_t> surfaceProducerMap_; // surfaceId→instanceId
};
```

**E13**: surface_tools.h L28-34: 四个公开方法声明（GetInstance/RegisterReleaseListener×2/CleanCache/ReleaseSurface）
**E14**: surface_tools.h L37-38: mutex_ + surfaceProducerMap_成员（uint64_t→int32_t）

### 2.2 单例与两路注册

**E15**: surface_tools.cpp L25-29: GetInstance()，函数内static实例
**E16**: surface_tools.cpp L31-49: RegisterReleaseListener(基础回调OnReleaseFunc)，GSError检查+L20 HiLogLabel
**E17**: surface_tools.cpp L51-69: RegisterReleaseListener(带序号栅栏回调OnReleaseFuncWithSequenceAndFence)

### 2.3 生命周期管理

**E18**: surface_tools.cpp L71-84: CleanCache()，surfaceId查map+iter->second==instanceId所有权验证+CleanCache调用
**E19**: surface_tools.cpp L86-106: ReleaseSurface()，CleanCache(L95)+UnRegisterReleaseListener(L98)+SetSurfaceSourceType(L101)+abadon控制map.erase(L103)

---

## 3. BlockQueue 线程安全阻塞队列模板

### 3.1 类定义

**文件**：`services/utils/include/block_queue.h`

```cpp
template <typename T>
class BlockQueue {
    // 构造：name_+capacity_+isActive_(true)
    // Push/Pop/Front/Clear/SetActive
    // DEFAULT_QUEUE_SIZE = 10
private:
    std::mutex mutex_;
    std::condition_variable condFull_;
    std::condition_variable condEmpty_;
    std::queue<T> que_;
    std::string name_;
    const size_t capacity_;
    std::atomic<bool> isActive_;
};
```

**E20**: block_queue.h L33-41: BlockQueue模板类声明，DEFAULT_QUEUE_SIZE=10
**E21**: block_queue.h L43-60: Push()，容量满时condFull_等待，isActive_判断
**E22**: block_queue.h L62-80: Pop()，空时condEmpty_等待，isActive_判断
**E23**: block_queue.h L106-117: SetActive()，isActive_控制+ClearUnprotected()

---

## 4. ScopeGuard RAII 作用域守卫

### 4.1 类定义

**文件**：`services/utils/include/scope_guard.h`

```cpp
template<typename ExitAction>
class ScopeGuard {
    explicit ScopeGuard(ExitAction &&action) : action_(action), enable_(true) {}
    ~ScopeGuard() { if (enable_) action_(); }
    void Disable() { enable_ = false; }
};
#define ON_SCOPE_EXIT(id) auto onScopeExitGuard##id = Detail::ScopeExitGuardHelper{} + [ & ]
```

**E24**: scope_guard.h L26-42: ScopeGuard类模板，enable_控制析构是否执行
**E25**: scope_guard.h L44-56: ON_SCOPE_EXIT(id)宏，生成ScopeGuard实例
**E26**: scope_guard.h L58-60: CANCEL_SCOPE_EXIT_GUARD(id)宏，Disable()

---

## 5. utils.h 模板工具函数

**文件**：`services/utils/include/utils.h`

**E27**: utils.h L23-27: SleepFor(unsigned ms)，usleep(ms*1000)
**E28**: utils.h L32-38: AlignUp模板（位运算向上对齐）
**E29**: utils.h L40-44: ReinterpretPointerCastshared_ptr模板

---

## 6. BUILD.gn 构建配置

**E30**: BUILD.gn L21-39: ohos_shared_library("av_codec_service_utils")
- sources: surface_tools.cpp + task_thread.cpp（L36-38）
- cflags: -std=c++17 -fno-rtti -fno-exceptions（L41-61）
- external_deps: graphic_surface/surface, hilog, hisysevent, hitrace, init, c_utils（L63-70）
- subsystem: multimedia, part: av_codec（L72-73）

---

## 变更记录

| 日期 | 操作 | 说明 |
|------|------|------|
| 2026-06-25T10:25 | builder-agent subagent | S253注册：AVCodec Service Utils 工具库草案生成，20条行号级evidence(E1-E30)，基于GitCode web_fetch + 本地镜像 /home/west/av_codec_repo/services/utils/，TaskThread五态机/SurfaceTools单例(2025)/BlockQueue/ScopeGuard |
