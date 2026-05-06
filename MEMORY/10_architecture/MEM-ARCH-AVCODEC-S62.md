---
status: approved
approved_at: "2026-05-06"
---

# MEM-ARCH-AVCODEC-S62: AudioBuffersManager 音频编解码双缓冲队列管理

## 概述

AudioBuffersManager 是音频编解码引擎的**缓冲区生命周期管理器**，位于 `services/engine/codec/audio/` 目录。它管理一组 AudioBufferInfo 对象，通过原子状态机控制缓冲区的可用性，配合 AudioCodecWorker 的双 TaskThread（ProduceInputBuffer/ConsumerOutputBuffer）实现音频数据的流水线处理。

**定位**：S62 与 S50(AudioResample) 互补——AudioResample 处理采样率转换，AudioBuffersManager 管理 PCM 缓冲区的申请/释放/状态流转。

---

## 核心架构

### AudioBuffersManager 类（缓冲区池管理器）

**头文件**：`services/engine/codec/include/audio/audio_buffers_manager.h`  
**源文件**：`services/engine/codec/audio/audio_buffers_manager.cpp`

```cpp
class AudioBuffersManager : public NoCopyable {
    // 四队列核心
    std::atomic<bool> isRunning_;                    // 运行状态标志
    std::mutex availableMutex_;                       // 可用队列锁
    std::condition_variable availableCondition_;       // 缓冲区可用条件变量
    std::queue<uint32_t> inBufIndexQue_;             // 可用缓冲区索引队列（FIFO）
    mutable std::mutex stateMutex_;                   // 状态变更锁
    const uint16_t bufferCount_;                      // 缓冲区数量（默认8）
    uint32_t bufferSize_;                             // 单缓冲区大小
    uint32_t metaSize_;                              // 元数据大小（可选）
    std::string_view name_;                          // 标识："inputBuffer" | "outputBuffer"
    std::vector<bool> inBufIndexExist;               // 索引存在性标记
    std::vector<std::shared_ptr<AudioBufferInfo>> bufferInfo_;  // 缓冲区实体数组
};
```

### AudioBufferInfo 类（单缓冲区实体）

**头文件**：`services/engine/codec/include/audio/audio_buffer_info.h`  
**源文件**：`services/engine/codec/audio/audio_buffer_info.cpp`

```cpp
class AudioBufferInfo : public NoCopyable {
    bool isHasMeta_;                                // 是否有元数据
    bool isEos_;                                    // EOS标志
    bool isFirstFrame_;                             // 首帧标志
    std::atomic<bool> isUsing;                     // 正在使用标志
    std::atomic<BufferStatus> status_;             // 缓冲区状态（IDLE/OWEN_BY_CLIENT）
    uint32_t bufferSize_;                           // 缓冲区大小
    uint32_t metaSize_;                            // 元数据大小
    std::shared_ptr<Media::AVSharedMemoryBase> buffer_;     // 数据缓冲区（AVSharedMemoryBase）
    std::shared_ptr<Media::AVSharedMemoryBase> metadata_;    // 元数据缓冲区（可选）
    AVCodecBufferInfo info_;                        // 缓冲区属性（PTS/配置信息）
    AVCodecBufferFlag flag_;                       // 缓冲区标志（EOS/NONE）
};
```

**BufferStatus 枚举**：
- `IDLE`：缓冲区空闲，可被申请
- `OWEN_BY_CLIENT`：客户端占用中

---

## 双缓冲区队列机制

### 初始化（initBuffers）

```cpp
void AudioBuffersManager::initBuffers()
{
    // 预创建 bufferCount_ 个 AudioBufferInfo，逐一放入 inBufIndexQue_
    for (size_t i = 0; i < bufferCount_; i++) {
        bufferInfo_[i] = std::make_shared<AudioBufferInfo>(bufferSize_, name_, metaSize_);
        inBufIndexQue_.emplace(i);      // 入队可用索引
        inBufIndexExist[i] = true;
    }
}
```

**关键点**：预分配所有缓冲区，避免运行时 malloc。inBufIndexQue_ 初始时包含所有索引，表示全部空闲。

### 申请缓冲区（RequestAvailableIndex）

```cpp
bool AudioBuffersManager::RequestAvailableIndex(uint32_t &index)
{
    // 队列空时等待，最多等待 DEFAULT_SLEEP_TIME(500ms)
    while (inBufIndexQue_.empty() && isRunning_) {
        std::unique_lock aLock(availableMutex_);
        availableCondition_.wait_for(aLock, std::chrono::milliseconds(DEFAULT_SLEEP_TIME), ...);
    }
    if (!isRunning_) return false;

    // 出队，标记为占用
    index = inBufIndexQue_.front();
    inBufIndexQue_.pop();
    inBufIndexExist[index] = false;      // 标记为不可用
    bufferInfo_[index]->SetBufferOwned(); // status_ = OWEN_BY_CLIENT
    return true;
}
```

**关键点**：
- **阻塞等待**机制：队列空时等待 500ms，避免忙轮询
- **原子状态转移**：出队时立即标记 `SetBufferOwned()`（OWEN_BY_CLIENT）
- **isRunning_ 控制**：Stop 时退出等待循环

### 释放缓冲区（ReleaseBuffer）

```cpp
bool AudioBuffersManager::ReleaseBuffer(const uint32_t &index)
{
    bufferInfo_[index]->ResetBuffer();   // 重置：isUsing=false, status_=IDLE, flag_=NONE
    if (!inBufIndexExist[index]) {
        inBufIndexQue_.emplace(index);  // 重新入队
        inBufIndexExist[index] = true;
    }
    availableCondition_.notify_all();      // 通知等待者
    return true;
}
```

**关键点**：`ResetBuffer()` 清空 EOS/首帧/使用标志，缓冲区恢复 IDLE 状态。

### 状态机转移图

```
申请者视角:
  IDLE →(RequestAvailableIndex)→ OWEN_BY_CLIENT
  OWEN_BY_CLIENT →(ReleaseBuffer)→ IDLE

ReleaseBuffer 内部:
  ResetBuffer(): isUsing=false, status_=IDLE, flag_=NONE, isEos_=false, isFirstFrame_=false
              → inBufIndexQue_.push(index)
              → notify_all() 通知等待者
```

---

## AudioCodecWorker 双队列架构

**源文件**：`services/engine/codec/audio/audio_codec_worker.cpp`

AudioCodecWorker 是 AudioBuffersManager 的消费者/生产者，管理**输入/输出两个缓冲区池**：

```cpp
const int16_t bufferCount = DEFAULT_BUFFER_COUNT;  // 8
const std::string_view INPUT_BUFFER = "inputBuffer";
const std::string_view OUTPUT_BUFFER = "outputBuffer";

// 构造函数中初始化两个 AudioBuffersManager
inputBuffer_(std::make_shared<AudioBuffersManager>(inputBufferSize, INPUT_BUFFER, DEFAULT_BUFFER_COUNT)),
outputBuffer_(std::make_shared<AudioBuffersManager>(outputBufferSize, OUTPUT_BUFFER, DEFAULT_BUFFER_COUNT))

// 双 TaskThread
inputTask_(std::make_unique<TaskThread>("OS_AuCodecIn")),   // ProduceInputBuffer：消费输入缓冲区
outputTask_(std::make_unique<TaskThread>("OS_AuCodecOut"))  // ConsumerOutputBuffer：消费输出缓冲区
```

### 数据流

```
外部 PushInputData(index)
  → inputBuffer_->RequestAvailableIndex()  获取输入缓冲区
  → AudioBaseCodec::Encode/Decode          编码/解码
  → inputBuffer_->ReleaseBuffer(index)     归还输入缓冲区
  → callback_->OnOutputBufferAvailable()    通知输出缓冲区可用
  → outputBuffer_->RequestAvailableIndex() 获取输出缓冲区
  → callback_->OnOutputBufferAvailable()    送达应用
  → outputBuffer_->ReleaseBuffer(index)    归还输出缓冲区
```

### 核心方法

| 方法 | 功能 |
|------|------|
| `PushInputData(index)` | 应用层压入输入数据索引 |
| `GetInputBuffer()` | 获取输入缓冲区管理器 |
| `GetOutputBuffer()` | 获取输出缓冲区管理器 |
| `GetInputBufferInfo(index)` | 根据索引获取输入缓冲区详情 |
| `GetOutputBufferInfo(index)` | 根据索引获取输出缓冲区详情 |

---

## AudioBufferInfo 内存布局

每个 AudioBufferInfo 包含两个 AVSharedMemoryBase：

```cpp
// 数据缓冲区（FLAGS_READ_WRITE，可读写）
buffer_ = std::make_shared<AVSharedMemoryBase>(bufferSize_, AVSharedMemory::Flags::FLAGS_READ_WRITE, name_);

// 元数据缓冲区（FLAGS_READ_ONLY，可选，仅当 metaSize_ > 0 时创建）
if (metaSize_ > 0) {
    metadata_ = std::make_shared<AVSharedMemoryBase>(metaSize_, AVSharedMemory::Flags::FLAGS_READ_ONLY, name_);
}
```

**ResetBuffer 时**：
```cpp
bool AudioBufferInfo::ResetBuffer()
{
    isEos_ = false;
    isFirstFrame_ = false;
    isUsing = false;
    status_ = BufferStatus::IDLE;
    flag_ = AVCodecBufferFlag::AVCODEC_BUFFER_FLAG_NONE;
    if (buffer_) buffer_->ClearUsedSize();  // 清空已用大小标记
    return true;
}
```

---

## 与 S50(AudioResample) 的关系

| 对比项 | AudioResample (S50) | AudioBuffersManager (S62) |
|--------|---------------------|--------------------------|
| 职责 | 采样率/格式转换 | 缓冲区生命周期管理 |
| 核心类型 | SwrContext (libswresample) | AudioBufferInfo + AudioBuffersManager |
| 数据形态 | 处理 PCM 帧数据 | 管理 AVSharedMemoryBase 内存块 |
| 触发时机 | 解码器 ReceiveFrameSucc 首次触发 | 整个编解码循环 |
| 关联组件 | AudioCodecWorker（双 Manager） | AudioCodecWorker（持有双 Manager） |

**协作关系**：
```
AudioCodecWorker
  ├─ inputBuffer_  (AudioBuffersManager)
  │    └─ AudioBufferInfo × 8 → AudioResample 处理输入 PCM
  └─ outputBuffer_ (AudioBuffersManager)
       └─ AudioBufferInfo × 8 → AudioResample 处理输出 PCM
```

---

## 与 S8(FFmpeg音频插件) 的关系

AudioFFMpegAacEncoderPlugin / AudioFFMpegAacDecoderPlugin 运行在 AudioBaseCodec 层，**不直接感知 AudioBuffersManager**。AudioCodecWorker 通过 AudioBaseCodec 的虚接口调用插件：

```
AudioCodecWorker
  → AudioBaseCodec（虚接口）
     → AudioFFMpegAacDecoderPlugin（具体实现）
        ← AudioCodecWorker 持有 inputBuffer_/outputBuffer_
```

---

## Evidence

| 证据 | 文件 | 行号 |
|------|------|------|
| AudioBuffersManager 类定义 | `services/engine/codec/include/audio/audio_buffers_manager.h` | 全文件 |
| AudioBuffersManager 实现 | `services/engine/codec/audio/audio_buffers_manager.cpp` | 全文件 |
| AudioBufferInfo 类定义 | `services/engine/codec/include/audio/audio_buffer_info.h` | 全文件 |
| AudioBufferInfo 实现 | `services/engine/codec/audio/audio_buffer_info.cpp` | 全文件 |
| AudioCodecWorker 持有双 Manager | `services/engine/codec/include/audio/audio_codec_worker.h` | 构造函数区 |
| DEFAULT_BUFFER_COUNT=8 | `services/engine/codec/audio/audio_codec_worker.cpp` | ~50行 |
| INPUT_BUFFER/OUTPUT_BUFFER 标识 | `services/engine/codec/audio/audio_codec_worker.cpp` | ~45行 |
| RequestAvailableIndex 阻塞等待 | `services/engine/codec/audio/audio_buffers_manager.cpp` | ~80行 |
| ReleaseBuffer notify_all | `services/engine/codec/audio/audio_buffers_manager.cpp` | ~130行 |
| SetBufferOwned 状态转移 | `services/engine/codec/audio/audio_buffers_manager.cpp` | ~65行 |
| AVSharedMemoryBase 双缓冲区创建 | `services/engine/codec/audio/audio_buffer_info.cpp` | ~50行 |
| ResetBuffer 清空状态 | `services/engine/codec/audio/audio_buffer_info.cpp` | ~140行 |

---

## 元数据记录

- **ID**: MEM-ARCH-AVCODEC-S62
- **类型**: Architecture Memory
- **主题**: AudioBuffersManager 音频编解码双缓冲队列管理
- **scope**: AVCodec, AudioCodec, BufferManagement, AudioCodecWorker
- **关联**: S50(AudioResample), S8(FFmpeg音频插件), S18(AudioCodecServer), S35(AudioDecoderFilter)
- **状态**: draft
- **生成时间**: 2026-04-27T05:15 GMT+8
- **Builder**: Builder Agent (subagent)
