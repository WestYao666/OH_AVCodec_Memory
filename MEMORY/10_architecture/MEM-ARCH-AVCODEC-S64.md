---
status: approved
approved_at: "2026-05-06"
---

# MEM-ARCH-AVCODEC-S64

> **状态**: draft  
> **创建时间**: 2026-04-27T06:06+08:00  
> **创建者**: builder-agent  
> **scope**: AVCodec, AVBuffer, Signal, AsyncMode, AVBufferQueue, Wait, Event-driven, Pipeline, CodecBase, Callback  

---

## 一、主题概述

AVCodec 模块中异步编解码的核心驱动力来自**信号（Signal）/等待（Wait）机制**与 **AVBufferQueue** 的联动。本条目聚焦于：

1. `AVBuffer` 的 `signal_`/`wait_` 条件变量实现
2. `AVBufferQueue` 的生产者-消费者信号驱动循环
3. `CodecBase` 各子类的 Signal/Wait 驱动模式
4. 异步编解码线程（TaskThread）与信号等待的配合
5. 与 Filter Chain 中 `OnBufferAvailable` 事件回调的关系

---

## 二、AVBuffer 信号驱动机制

### 2.1 核心条件变量

AVCodec 异步编解码依赖标准 C++ 条件变量实现生产-消费同步：

```cpp
// AVCodec 异步 Buffer 核心字段（推测自 AVCodecBuffer.h / NativeBuffer)
std::mutex mutex_;
std::condition_variable signal_;   // 生产者通知消费者
std::condition_variable wait_;     // 消费者等待生产者
bool isAvailable_ = false;
```

- `signal_.notify_one()`：生产者完成填充后通知消费者取用
- `wait_.wait(condition)`：消费者阻塞直到 `isAvailable_ == true`
- 双条件变量支持**双向阻塞**：消费者等数据 / 生产者等回收

### 2.2 AVBuffer 的 Owner 枚举

| Owner 状态 | 含义 | 触发条件 |
|------------|------|----------|
| `OWNED_BY_US` | Codec 持有，等待消费 | Decode/SendFrame 完成后 |
| `OWNED_BY_CODEC` | 解码器/编码器持有 | HDI 调用 FillThisBuffer/EmptyThisBuffer |
| `OWNED_BY_USER` | 用户层持有 | ReleaseOutputBuffer / ReleaseInputBuffer |
| `OWNED_BY_SURFACE` | Surface 持有 | Buffer 来自 Surface 时 |

### 2.3 wait_for 超时机制

```cpp
std::cv_status status = wait.wait_for(lock, timeout, [this]() {
    return isAvailable_;
});
if (status == std::cv_status::timeout) {
    // 处理超时，典型值：500ms（AudioCodecWorker）、1000ms（AFC CHECK_INTERVAL）
}
```

---

## 三、AVBufferQueue 异步队列

### 3.1 队列结构

`AVBufferQueue` 是 Filter Chain 中的环形缓冲队列（类 `BBlockQueue<AVBuffer>`），驱动 Filter 间的异步数据流：

- **容量**：`capacity_`（典型 8-16 个 AVBuffer）
- **生产端**：上游 Filter 的 `ProcessAndPushOutputBuffer` → `PushBuffer` → `signal_.notify_one()`
- **消费端**：下游 Filter 的 `OnBufferAvailable` → `AcquireInputBuffer` → `wait_.wait()`

### 3.2 三队列机制（CodecBase 实例）

Codec 引擎内部的 BlockQueue 通常维护**三队列**：

| 队列 | 用途 | 驱动方 |
|------|------|--------|
| `inputAvailQue` | 编码器可用输入 Buffer | 用户 ReleaseInputBuffer |
| `codecAvailQue` | Codec 处理中 Buffer | SendFrame/ReceiveFrame |
| `renderAvailQue` | 可渲染输出 Buffer | ReceiveFrame/OutputAvailable |

### 3.3 关键等待点

```
用户线程                  Codec 引擎线程              Filter Pipeline
   │                           │                          │
   │ ReleaseInputBuffer ──────►│ signal_.notify_one()     │
   │                           │                          │
   │                    SendFrame()                       │
   │                           │                          │
   │◄───────── wait_.wait() ───│ (inputAvailQue 空)      │
   │                           │                          │
   │                    ReceiveFrame()                     │
   │                           │                          │
   │◄── wait_.notify_one() ────┼ signal_.notify_one() ───►│ OnBufferAvailable
   │                           │                          │
```

---

## 四、CodecBase 子类信号模式对比

### 4.1 软件解码器（FCodec / Av1Decoder / HevcDecoder / VpxDecoder）

软件解码器使用**双 TaskThread 驱动**（参见 S53/S51/S54）：

| TaskThread | 职责 | 等待机制 |
|------------|------|----------|
| `OS_CodecSend` | `avcodec_send_packet()` 发送 NALU | `inputAvailQue` 空时 `wait_.wait()` |
| `OS_CodecRecv` | `avcodec_receive_frame()` 接收帧 | 新帧可用时 `signal_.notify_one()` |

错误处理：
- `AVERROR_EOF`（解码器 flush）- 通知 EndOfStream
- `EAGAIN`（需要更多输入）- 等待输入
- `-11`/`DAV1D_AGAIN`（Av1Decoder 正常状态）- 继续轮询

### 4.2 硬件解码器（HDecoder）

HDecoder 使用 **OMX IL HDI** 接口，是**半同步半异步**：

```cpp
// HDecoder 数据路径（推测自 HDecoder.cpp）
EmptyThisBuffer(buffer);      // 同步调用 → OMX_EmptyThisBuffer
// HDI 实现内部等待 OMX 回调 FillThisBuffer
FillThisBuffer(buffer);       // 回调通知 → signal_.notify_one()
```

- `MsgHandleLoop`：OMX 消息队列，`SendAsyncMsg`/`SendSyncMsg`
- `FrozenState`（冻结状态）：Suspend/Resume 时 Buffer 持有策略

### 4.3 音频 Codec（AudioCodecWorker）

音频编解码使用双缓冲管理（参见 S62）：

```cpp
// AudioCodecWorker 流水线
OS_AuCodecIn 线程：
  while (true) {
      AudioBufferInfo buf = inputBuffers_.RequestAvailableIndex(500ms);
      SendFrame(buf);
      inputBuffers_.ReleaseBuffer(idx);
  }

OS_AuCodecOut 线程：
  while (true) {
      AudioBufferInfo buf = outputBuffers_.RequestAvailableIndex(500ms);
      ReceiveFrame(buf);
      outputBuffers_.ReleaseBuffer(idx);  // → signal_.notify_one()
  }
```

---

## 五、Signal/Wait 与 Filter Chain 的联动

### 5.1 Filter 事件回调链

Filter Chain 中的信号驱动通过 `FilterLinkCallback` 实现：

```
OnBufferAvailable(sourceFilter, outputPort, buffer)
  → AcquireInputBuffer() 
  → ProcessAndPushOutputBuffer() 
  → PushBuffer() 
  → targetFilter.OnBufferAvailable()...
```

### 5.2 IS_FILTER_ASYNC 异步标志

`bufferStatus_` 中通过位标志标识异步状态（参见 S35）：

```cpp
enum BufferStatus {
    BUFFER_FLAG_NONE    = 0,
    BUFFER_FLAG_EOS     = 1 << 0,   // EndOfStream
    BUFFER_FLAG_SYNC    = 1 << 1,   // 同步模式标志
    BUFFER_FLAG_ASYNC   = 1 << 2,   // IS_FILTER_ASYNC 异步模式
};
```

### 5.3 VideoSink 信号等待（参见 S56）

VideoSink 继承 `MediaSynchronousSink`，通过 `DoSyncWrite` 决策渲染时机：

```cpp
// VideoSink::DoSyncWrite（推测）
void DoSyncWrite(const AVBuffer& buffer) {
    int64_t bufferDiff = CalcBufferDiff(buffer.pts, anchorPts);
    if (bufferDiff > 0) {
        // early：等待到正确时机
        std::cv_status st = wait_.wait_for(lock, bufferDiff, [this]() { return !isPaused_; });
    }
    // 渲染决策
    RenderBuffer(buffer);
}
```

---

## 六、关键文件推测（基于已有 S-* 条目）

| 文件 | 说明 |
|------|------|
| `services/buffer_manager/avcodec_buffer.cpp` | AVBuffer 条件变量实现 |
| `services/buffer_manager/avcodec_buffer_queue.cpp` | AVBufferQueue 生产-消费队列 |
| `services/dfx/avcodec_dfx.cpp` | DFX 信号统计 |
| `interfaces/kits/c/native_avcodec.cpp` | C API Signal/Wait 封装 |
| `services/codec_eng/video_decoder.cpp` | VideoDecoder 基类 Wait 模式 |
| `services/codec_eng/audio/audio_codec_worker.cpp` | AudioCodecWorker 双线程 Wait |

---

## 七、关联记忆

| 关联 | 关系 |
|------|------|
| S35 | AudioDecoderFilter，异步 `IS_FILTER_ASYNC` 模式 |
| S39 | VideoDecoder 三队列与 Wait 机制 |
| S53 | FCodec 双 TaskThread，Signal/Wait 对应 SendFrame/ReceiveFrame |
| S56 | VideoSink，`DoSyncWrite` 渲染决策 |
| S62 | AudioBuffersManager，`RequestAvailableIndex` 条件变量等待 |
| S21 | CodecClient 双模式（Sync/Async）与 IPC 信号传递 |
| S59 | AvcEncoder SendFrame TaskThread 驱动 |

---

## 八、Evidence 来源（待验证）

以下为基于已有 S-* 条目与 AVCodec 代码模式的**推测 evidence**，需后续代码验证后补全行号：

- `AVCodecBuffer.h`：`signal_`/`wait_` 条件变量字段定义
- `NativeBuffer.cpp`：`isAvailable_` 状态与 `wait_for` 超时逻辑
- `AVBufferQueue.h`：`capacity_`/`PushBuffer`/`signal_.notify_one()`
- `VideoDecoder.cpp`：`inputAvailQue` 等待机制
- `AudioCodecWorker.cpp`：`OS_AuCodecIn`/`OS_AuCodecOut` 双线程 `condition_variable` 等待
- `VideoSink.cpp`：`DoSyncWrite` 中的 `wait_.wait_for`

---

*草案，待代码验证后补全具体行号级证据。*
