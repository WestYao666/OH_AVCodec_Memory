---
status: approved
approved_at: "2026-05-06"
---

# MEM-ARCH-AVCODEC-016: AVBufferQueue 异步编解码——输入/输出队列与 TaskThread 驱动机制

## Metadata

| 字段 | 值 |
|------|-----|
| mem_id | MEM-ARCH-AVCODEC-016 |
| title | AVBufferQueue 异步编解码——输入/输出队列与 TaskThread 驱动机制 |
| scope | AVCodec, Core, BufferQueue, Async |
| created | 2026-04-19 |
| requester | builder-agent (P1h) |

---

## 1. AVBufferQueue 队列机制

### 1.1 核心抽象：生产者-消费者模式

AVBufferQueue 是 OpenHarmony 多媒体系统中实现**异步、流水线式编解码**的核心数据结构。它基于经典的**生产者-消费者队列**模式，内部由 `std::deque` + `std::mutex` + `std::condition_variable` 实现同步。

```
Demuxer (Producer)              Codec (Consumer)
    │                                 │
    │  AttachBuffer / PushBuffer      │
    ▼                                 ▼
[ inputBufferQueue ]  ──Acq/Release──> [ Codec Core ]
     (AVBufferQueue)                      │
                                          │ decode
                                          ▼
                               [ outputBufferQueue ]
                                          │
                                          ▼
                               Surface / Renderer (Consumer)
```

### 1.2 输入队列（InputBufferQueue）

- **持有者**：`SurfaceDecoderAdapter`（解适配器）持有 `AVBufferQueueProducer` 和 `AVBufferQueueConsumer`
- **生产者**：Demuxer Filter，通过 `AVBufferQueueProducer::AttachBuffer()` 填充压缩数据帧
- **消费者**：Codec Engine，通过 `AVBufferQueueConsumer::AcquireBuffer()` 取帧，调用 `QueueInputBuffer(index)` 送入解码器
- **创建时机**：`SurfaceDecoderAdapter::GetInputBufferQueue()` 在首次调用时创建队列（Lazy Init）

```cpp
// surface_decoder_adapter.cpp
inputBufferQueue_ = AVBufferQueue::Create(0, MemoryType::UNKNOWN_MEMORY, "inputBufferQueue", true);
inputBufferQueueProducer_ = inputBufferQueue_->GetProducer();
inputBufferQueueConsumer_ = inputBufferQueue_->GetConsumer();
sptr<IConsumerListener> listener = new AVBufferAvailableListener(shared_from_this());
inputBufferQueueConsumer_->SetBufferAvailableListener(listener);  // 数据到达通知
```

### 1.3 输出队列（OutputBufferQueue）

- **持有者**：`SurfaceDecoderAdapter`（解适配器）
- **生产者**：Codec Engine，通过 `OnOutputBufferAvailable(index, buffer)` 回调输出原始视频帧
- **消费者**：下游 Filter（Surface Renderer），通过 Surface 或直接消费

### 1.4 关键 API

| 方法 | 角色 | 作用 |
|------|------|------|
| `AttachBuffer(buffer, isFilled)` | Producer | 向队列注册一个 buffer（已填充/空） |
| `AcquireBuffer(outBuffer)` | Consumer | 消费（获取）一个可用的 buffer |
| `ReleaseBuffer(inBuffer)` | Consumer | 归还 buffer 回队列（消费完成后） |
| `SetBufferAvailableListener(listener)` | Consumer | 注册数据到达回调（驱动 TaskThread） |

---

## 2. TaskThread 驱动机制

### 2.1 TaskThread 状态机

TaskThread（`services/utils/task_thread.h/cpp`）是 OpenHarmony 多媒体系统中通用的**异步任务驱动线程**，采用状态机管理生命周期：

```
              ┌─────────────────────────────────────────┐
              │              RunningState                 │
              └─────────────────────────────────────────┘
                              │
         ┌────────────────────┼────────────────────┐
         │                    │                    │
    ┌────▼────┐          ┌─────▼────┐          ┌────▼────┐
    │ STARTED │◄─pause───│ PAUSING  │◄─pause───│ PAUSED  │
    └────┬────┘          └────┬─────┘          └────┬────┘
         │                   │                    │
         │      ┌────────────┘                    │
         │      │ notify                          │
         │      ▼                                 │
    ┌────▼───────────────────────────────────────┴────┐
    │              STOPPING                           │
    └────────────────────┬────────────────────────────┘
                         │ join thread
                         ▼
                   ┌──────────┐
                   │ STOPPED  │
                   └──────────┘
```

### 2.2 核心接口

| 方法 | 语义 |
|------|------|
| `Start()` | 同步启动线程，等待进入 STARTED |
| `Stop()` | 同步停止，等待线程完全退出 |
| `StopAsync()` | 异步停止，只发信号不等待 |
| `Pause()` / `PauseAsync()` | 暂停/异步暂停 |
| `RegisterHandler(handler)` | 注册任务处理函数（自定义 DoTask） |

### 2.3 运行循环（Run）

```cpp
void TaskThread::Run() {
    pthread_setname_np(pthread_self(), name_.data());
    for (;;) {
        if (runningState_.load() == RunningState::STARTED) {
            handler_();  //执行业务逻辑
        }
        std::unique_lock lock(stateMutex_);
        if (runningState_.load() == RunningState::PAUSING || runningState_.load() == RunningState::PAUSED) {
            runningState_ = RunningState::PAUSED;
            syncCond_.notify_all();
            syncCond_.wait_for(lock, std::chrono::milliseconds(500), ...); // 500ms 唤醒窗口
        }
        if (runningState_.load() == RunningState::STOPPING || runningState_.load() == RunningState::STOPPED) {
            runningState_ = RunningState::STOPPED;
            syncCond_.notify_all();
            break;  // 退出循环
        }
    }
}
```

---

## 3. 与 Codec 实例生命周期的关系

```
Codec 生命周期                    AVBufferQueue / TaskThread 状态
───────────────────────────────────────────────────────────────
CreateByMime/Name()               AVBufferQueue 尚未创建（Lazy Init）
      │
Configure()                       可选创建 AVBufferQueue（Lazy Init）
      │
GetInputBufferQueue()  ──────────► AVBufferQueue::Create() 创建
      │                          Consumer listener 注册
Start() ────────────────────────► releaseBufferTask_->Start()
      │                              TaskThread 进入 STARTED
      │                          codecServer_->Prepare() / Start()
      │
      │  异步流水线运行：Demuxer → inputBufferQueue → Codec → outputBufferQueue
      │
Stop()  ─────────────────────────► releaseBufferTask_->Stop()
      │                              TaskThread 进入 STOPPED
Flush()                           清空队列 buffer
      │
Release() ───────────────────────► AVBufferQueue 引用清零，TaskThread dtor
```

### 关键设计点

- **Lazy Init**：AVBufferQueue 在首次调用 `GetInputBufferQueue()` 时才创建，而不是在构造时
- **TaskThread 与 Codec 解耦**：`releaseBufferTask_`（TaskThread 实例）专门负责 output buffer 的回收，不直接参与解码过程
- **双向队列共享**：Codec 实例同时持有 input 和 output 两个方向的队列引用，形成流水线

---

## 4. 异步编解码工作流程

### 4.1 解码流水线（以 SurfaceDecoderAdapter 为例）

```
Step 1: 初始化
  SurfaceDecoderAdapter::Init(mime)
    → VideoDecoderFactory::CreateByMime() 创建 codecServer_
    → 创建 Task("SurfaceDecoder")，注册 ReleaseBuffer job

Step 2: 获取输入队列（外部/Demuxer 调用）
  SurfaceDecoderAdapter::GetInputBufferQueue()
    → AVBufferQueue::Create() 创建队列
    → Consumer 注册 AVBufferAvailableListener

Step 3: Start
  SurfaceDecoderAdapter::Start()
    → releaseBufferTask_->Start()        // TaskThread 开始运行
    → codecServer_->Prepare()
    → codecServer_->Start()

Step 4: Demuxer 生产数据
  Demuxer Filter
    → AttachBuffer(filledBuffer, isFilled=true)  // 写入 inputBufferQueue
    → 触发 IConsumerListener::OnBufferAvailable()

Step 5: 消费输入（TaskThread 驱动）
  AVBufferAvailableListener::OnBufferAvailable()
    → AcquireAvailableInputBuffer()
    → inputBufferQueueConsumer_->AcquireBuffer()
    → codecServer_->QueueInputBuffer(index)

Step 6: 解码（异步，不阻塞 TaskThread）
  Codec Engine 内部异步解码

Step 7: 解码完成回调
  SurfaceDecoderAdapterCallback::OnOutputBufferAvailable()
    → 将 index 加入 indexs_ 向量
    → notify releaseBufferCondition_

Step 8: Output Buffer 回收（TaskThread 驱动）
  ReleaseBuffer() [running in TaskThread "SurfaceDecoder"]
    → wait(releaseBufferCondition_) 等待输出
    → codecServer_->ReleaseOutputBuffer(index, drop)
    → 循环 Step 5
```

### 4.2 关键异步机制总结

| 环节 | 异步机制 | 线程 |
|------|---------|------|
| 输入数据到达通知 | `IConsumerListener::OnBufferAvailable()` + `AcquireBuffer` | Demuxer 线程 |
| 解码触发 | `QueueInputBuffer()` | TaskThread 或外部线程 |
| 解码完成通知 | `OnOutputBufferAvailable()` 回调 | Codec 内部线程 |
| Output Buffer 回收 | `TaskThread::Run()` + `releaseBufferTask_` | "SurfaceDecoder" 线程 |

---

## 5. Evidence 来源

### 5.1 本地源码

| 文件 | 说明 |
|------|------|
| `services/utils/include/task_thread.h` | TaskThread 类定义，状态机接口 |
| `services/utils/task_thread.cpp` | TaskThread 实现，Run 循环，状态转换逻辑 |
| `services/media_engine/filters/surface_decoder_adapter.h` | AVBufferQueue 持有者声明，Task member |
| `services/media_engine/filters/surface_decoder_adapter.cpp` | 完整的输入队列+TaskThread 使用示例 |
| `services/media_engine/modules/demuxer/sample_queue.h` | SampleQueue 封装 AVBufferQueue |

### 5.2 GitCode 源码

- **仓库**：`https://gitcode.com/openharmony/multimedia_av_codec`
- **分支/路径**：主要对应 `multimedia_av_codec/services/utils/task_thread.cpp` 及 `services/media_engine/filters/` 下各 adapter 文件

---

## 6. 关联记忆

| mem_id | 标题 | 关系 |
|--------|------|------|
| MEM-ARCH-AVCODEC-010 | Codec 实例生命周期 | Codec Create→Configure→Start→Stop→Release 与 AVBufferQueue 的创建/销毁时机对应 |
| MEM-ARCH-AVCODEC-006 | media_codec 编解码数据流 | P1a，数据流视角 |
| MEM-ARCH-AVCODEC-014 | Codec Engine 架构 | CodecBase/Loader/Factory 插件架构 |

---

## 7. 审批信息

| 字段 | 值 |
|------|-----|
| submitted_at | 2026-04-19T12:36 GMT+8 |
| submitted_by | builder-agent (P1h) |

---

_本草案由记忆工厂 Builder Agent 自动生成，内容基于 OpenHarmony multimedia_av_codec 源码分析。_
