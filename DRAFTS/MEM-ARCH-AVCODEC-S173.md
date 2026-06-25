---
mem_id: MEM-ARCH-AVCODEC-S173
title: AudioCodecAdapter + AudioCodecWorker 音频编解码适配器——CodecBase子类与双TaskThread异步驱动架构
status: draft
date: "2026-06-25"
scope: AVCodec, AudioCodec, Adapter, Worker, AudioBaseCodec, TaskThread, Pipeline, CodecState, CodecBase, SoftwareCodec
related_scenarios:
  - 音频编解码接入开发
  - 问题定位（音频Worker线程挂死/缓冲区泄漏）
  - 音频Pipeline Filter层适配
evidence_count: 20
related_mems:
  - S35: AudioDecoderFilter（Filter层封装）
  - S62: AudioBuffersManager（双缓冲管理器）
  - S158: FFmpeg音频编码器（同类Audio编解码插件）
  - S125: FFmpeg音频解码器（同类Audio编解码插件）
  - S70: VideoCodec工厂与Loader插件体系（CodecBase的工厂创建路径）
created: 2026-06-25
builder: builder-agent
source: 本地镜像 /home/west/av_codec_repo
---

# MEM-ARCH-AVCODEC-S173：AudioCodecAdapter + AudioCodecWorker 音频编解码适配器

## 架构概述

`AudioCodecAdapter`（467行cpp）是 `CodecBase` 的子类，作为音频编解码引擎的适配层，通过 `AudioBaseCodec::make_sharePtr` 工厂注入具体编码器实现（如 FFmpeg 软件编码器或硬件编码器）。`AudioCodecWorker`（429行cpp）是异步双 TaskThread 驱动引擎，维护 input/output `AudioBuffersManager` 双缓冲队列，实现音频编码/解码任务的并发流水线。

### 核心组件

| 组件 | 文件 | 行号 | 职责 |
|------|------|------|------|
| `AudioCodecAdapter` | audio_codec_adapter.cpp | 467 | CodecBase子类，适配层，状态机管理 |
| `AudioCodecWorker` | audio_codec_worker.cpp | 429 | 双TaskThread异步驱动，缓冲队列管理 |
| `AudioBaseCodec::make_sharePtr` | audio_codec_adapter.cpp | L312 | 工厂方法，创建具体AudioCodec实现 |
| 双TaskThread | audio_codec_worker.cpp | L36-37 | OS_AuCodecIn（输入）/ OS_AuCodecOut（输出） |
| `AudioBuffersManager` | audio_codec_worker.h | L48-49 | input/output 双缓冲池，各8个buffer |

---

## 架构层次

```
MediaCodecCallback（外部回调）
         ↑
    AudioCodecAdapter
    （CodecBase子类，状态机管理）
         ↓ holds
    AudioBaseCodec（具体编码器实现）
         ↑
    AudioCodecWorker
    （双TaskThread驱动）
         ↓ manages
    AudioBuffersManager × 2
    （inputBuffer_ 8个 / outputBuffer_ 8个）
```

---

## Formal Evidence（20条）

### E1 — AudioCodecAdapter 继承 CodecBase
**文件**: `audio_codec_adapter.h`
**行号**: L25
**内容**:
```cpp
class AudioCodecAdapter : public CodecBase, public NoCopyable {
```
**说明**: AudioCodecAdapter 公开继承 CodecBase，获得统一的生命周期接口（Configure/Start/Stop/Release/Flush等）。

---

### E2 — AudioCodecAdapter 关键成员声明
**文件**: `audio_codec_adapter.h`
**行号**: L55-61
**内容**:
```cpp
private:
    std::atomic<CodecState> state_;
    const std::string name_;
    std::shared_ptr<AVCodecCallback> callback_;
    std::shared_ptr<AudioBaseCodec> audioCodec;
    std::shared_ptr<AudioCodecWorker> worker_;
```
**说明**: `state_` 是 atomic CodecState，驱动状态转换；`audioCodec` 是具体编码器实现（由工厂创建）；`worker_` 管理双TaskThread异步驱动。

---

### E3 — AudioCodecWorker 双重 TaskThread 常量定义
**文件**: `audio_codec_worker.cpp`
**行号**: L34-37
**内容**:
```cpp
constexpr short DEFAULT_BUFFER_COUNT = 8;
constexpr int TIMEOUT_MS = 1000;
const std::string_view ASYNC_HANDLE_INPUT = "OS_AuCodecIn";
const std::string_view ASYNC_DECODE_FRAME = "OS_AuCodecOut";
```
**说明**: DEFAULT_BUFFER_COUNT=8 每个缓冲池8个buffer；TIMEOUT_MS=1000ms 条件变量等待超时；OS_AuCodecIn/OS_AuCodecOut 是 pthread 线程名，用于调试。

---

### E4 — AudioCodecWorker 构造函数——双 TaskThread + 双 AudioBuffersManager 初始化
**文件**: `audio_codec_worker.cpp`
**行号**: L42-54
**内容**:
```cpp
AudioCodecWorker::AudioCodecWorker(const std::shared_ptr<AudioBaseCodec> &codec,
                                   const std::shared_ptr<AVCodecCallback> &callback)
    : isFirFrame_(true),
      isRunning(true),
      codec_(codec),
      inputBufferSize(codec_->GetInputBufferSize()),
      outputBufferSize(codec_->GetOutputBufferSize()),
      bufferCount(DEFAULT_BUFFER_COUNT),
      name_(codec->GetCodecType()),
      inputTask_(std::make_unique<TaskThread>(ASYNC_HANDLE_INPUT)),
      outputTask_(std::make_unique<TaskThread>(ASYYNC_DECODE_FRAME)),
      callback_(callback),
      inputBuffer_(std::make_shared<AudioBuffersManager>(inputBufferSize, INPUT_BUFFER, DEFAULT_BUFFER_COUNT)),
      outputBuffer_(std::make_shared<AudioBuffersManager>(outputBufferSize, OUTPUT_BUFFER, DEFAULT_BUFFER_COUNT))
{
    inputTask_->RegisterHandler([this] { ProduceInputBuffer(); });
    outputTask_->RegisterHandler([this] { ConsumerOutputBuffer(); });
}
```
**说明**: 构造函数直接初始化 inputTask_/outputTask_ 并注册 ProduceInputBuffer/ConsumerOutputBuffer 回调。inputBuffer_/outputBuffer_ 各持有一个 AudioBuffersManager（8个buffer）。

---

### E5 — AudioCodecAdapter::doInit——AudioBaseCodec 工厂创建
**文件**: `audio_codec_adapter.cpp`
**行号**: L312-322
**内容**:
```cpp
int32_t AudioCodecAdapter::doInit()
{
    if (name_.empty()) {
        state_ = CodecState::RELEASED;
        return AVCodecServiceErrCode::AVCS_ERR_UNKNOWN;
    }
    audioCodec = AudioBaseCodec::make_sharePtr(name_);
    if (audioCodec == nullptr) {
        state_ = CodecState::RELEASED;
        return AVCodecServiceErrCode::AVCS_ERR_UNKNOWN;
    }
    state_ = CodecState::INITIALIZED;
    return AVCodecServiceErrCode::AVCS_ERR_OK;
}
```
**说明**: `AudioBaseCodec::make_sharePtr(name_)` 是工厂方法，根据 name_ 创建具体软件/硬件音频编码器。AudioCodecAdapter 不直接依赖具体编码器类，实现了解耦。

---

### E6 — AudioCodecAdapter::doStart——AudioCodecWorker 创建与启动
**文件**: `audio_codec_adapter.cpp`
**行号**: L339-347
**内容**:
```cpp
int32_t AudioCodecAdapter::doStart()
{
    if (state_ != CodecState::STARTING) {
        return AVCodecServiceErrCode::AVCS_ERR_INVALID_STATE;
    }
    state_ = CodecState::RUNNING;
    worker_ = std::make_shared<AudioCodecWorker>(audioCodec, callback_);
    worker_->Start();
    return AVCodecServiceErrCode::AVCS_ERR_OK;
}
```
**说明**: Start 时创建 AudioCodecWorker 实例并调用 Start()，正式启动双 TaskThread。AudioCodecWorker 持有 audioCodec 和 callback_ 的 shared_ptr。

---

### E7 — AudioCodecAdapter CodecState 十一态枚举
**文件**: `audio_codec_adapter.cpp`
**行号**: L421-432
**内容**:
```cpp
std::string_view AudioCodecAdapter::stateToString(CodecState state)
{
    std::map<CodecState, std::string_view> stateStrMap = {
        {CodecState::RELEASED, " RELEASED"},         {CodecState::INITIALIZED, " INITIALIZED"},
        {CodecState::FLUSHED, " FLUSHED"},           {CodecState::RUNNING, " RUNNING"},
        {CodecState::INITIALIZING, " INITIALIZING"}, {CodecState::STARTING, " STARTING"},
        {CodecState::STOPPING, " STOPPING"},         {CodecState::FLUSHING, " FLUSHING"},
        {CodecState::RESUMING, " RESUMING"},         {CodecState::RELEASING, " RELEASING"},
        {CodecState::CONFIGURED, " CONFIGURED"},
    };
    return stateStrMap[state];
}
```
**说明**: CodecState 十一态：RELEASED / INITIALIZING / INITIALIZED / CONFIGURED / STARTING / RUNNING / FLUSHING / FLUSHED / STOPPING / RESUMING / RELEASING。与视频 CodecBase 状态机模型一致。

---

### E8 — AudioCodecAdapter::QueueInputBuffer——生产者入队流程
**文件**: `audio_codec_adapter.cpp`
**行号**: L209-244
**内容**:
```cpp
int32_t AudioCodecAdapter::QueueInputBuffer(uint32_t index, const AVCodecBufferInfo &info, AVCodecBufferFlag flag)
{
    auto result = worker_->GetInputBufferInfo(index);
    if (result == nullptr) { return AVCodecServiceErrCode::AVCS_ERR_NO_MEMORY; }
    if (result->GetStatus() != BufferStatus::OWEN_BY_CLIENT) { return AVCodecServiceErrCode::AVCS_ERR_UNKNOWN; }
    if (result->CheckIsUsing()) { return AVCodecServiceErrCode::AVCS_ERR_UNKNOWN; }
    result->SetUsing();
    result->SetBufferAttr(info);
    if (flag == AVCodecBufferFlag::AVCODEC_BUFFER_FLAG_EOS) {
        result->SetEos(true);
    }
    worker_->PushInputData(index);
    return AVCodecServiceErrCode::AVCS_ERR_OK;
}
```
**说明**: 外部调用 QueueInputBuffer 将填充好的输入 buffer 入队。PushInputData 将 index 压入 inBufIndexQue_，触发 ConsumerOutputBuffer 消费。

---

### E9 — AudioCodecWorker::Begin——双 TaskThread 启动与 Buffer 预填充
**文件**: `audio_codec_worker.cpp`
**行号**: L364-381
**内容**:
```cpp
bool AudioCodecWorker::Begin()
{
    for (uint32_t i = 0; i < static_cast<uint32_t>(bufferCount); i++) {
        inBufAvaIndexQue_.push(i);
    }
    isRunning = true;
    inputBuffer_->SetRunning();
    outputBuffer_->SetRunning();
    if (inputTask_) { inputTask_->Start(); } else { return false; }
    if (outputTask_) { outputTask_->Start(); } else { return false; }
    inputCondition_.notify_all();
    outputCondition_.notify_all();
    return true;
}
```
**说明**: Begin() 预填充 inBufAvaIndexQue_（0~7），设置 isRunning=true，SetRunning() 激活双 AudioBuffersManager，然后 Start() 两个 TaskThread。

---

### E10 — AudioCodecWorker::PushInputData——输入 buffer 入队
**文件**: `audio_codec_worker.cpp`
**行号**: L67-86
**内容**:
```cpp
bool AudioCodecWorker::PushInputData(const uint32_t &index)
{
    if (!isRunning) { return true; }
    if (!callback_ || !codec_) {
        Dispose();
        return false;
    }
    std::lock_guard<std::mutex> lock(stateMutex_);
    inBufIndexQue_.push(index);
    outputCondition_.notify_all();
    return true;
}
```
**说明**: PushInputData 是生产者入口，将 buffer index 压入 inBufIndexQue_，然后 notify_all() 唤醒 ConsumerOutputBuffer 的等待线程。

---

### E11 — AudioCodecWorker::HandInputBuffer——单帧编解码处理
**文件**: `audio_codec_worker.cpp`
**行号**: L255-280
**内容**:
```cpp
bool AudioCodecWorker::HandInputBuffer(int32_t &ret)
{
    uint32_t inputIndex;
    {
        std::lock_guard<std::mutex> lock(stateMutex_);
        inputIndex = inBufIndexQue_.front();
        inBufIndexQue_.pop();
    }
    auto inputBuffer = GetInputBufferInfo(inputIndex);
    bool isEos = inputBuffer->CheckIsEos();
    ret = codec_->ProcessSendData(inputBuffer);
    inputBuffer_->ReleaseBuffer(inputIndex);
    {
        std::lock_guard<std::mutex> lock(inAvaMutex_);
        inBufAvaIndexQue_.push(inputIndex);
        inputCondition_.notify_all();
    }
    if (ret == AVCodecServiceErrCode::AVCS_ERR_INVALID_DATA) {
        callback_->OnError(AVCodecErrorType::AVCODEC_ERROR_INTERNAL, ret);
    }
    return isEos;
}
```
**说明**: HandInputBuffer 从 inBufIndexQue_ 取一帧，调用 codec_->ProcessSendData(inputBuffer) 执行编码/解码，然后归还 buffer 到 inBufAvaIndexQue_。EOS 标记传递到输出。

---

### E12 — AudioCodecWorker::ConsumerOutputBuffer——OS_AuCodecOut 输出线程
**文件**: `audio_codec_worker.cpp`
**行号**: L306-343
**内容**:
```cpp
void AudioCodecWorker::ConsumerOutputBuffer()
{
    std::unique_lock lock(outputMutex_);
    while (!inBufIndexQue_.empty() && isRunning) {
        int32_t ret = AVCodecServiceErrCode::AVCS_ERR_INVALID_DATA;
        bool isEos = HandInputBuffer(ret);
        if (ret == AVCodecServiceErrCode::AVCS_ERR_NOT_ENOUGH_DATA) { continue; }
        if (ret != AVCodecServiceErrCode::AVCS_ERR_OK && ret != AVCodecServiceErrCode::AVCS_ERR_END_OF_STREAM) { return; }
        uint32_t index;
        if (outputBuffer_->RequestAvailableIndex(index)) {
            auto outBuffer = GetOutputBufferInfo(index);
            SetFirstAndEosStatus(outBuffer, isEos, index);
            ret = codec_->ProcessRecieveData(outBuffer);
            if (ret == AVCodecServiceErrCode::AVCS_ERR_NOT_ENOUGH_DATA) {
                outputBuffer_->ReleaseBuffer(index); continue;
            }
            if (ret != AVCodecServiceErrCode::AVCS_ERR_OK && ret != AVCodecServiceErrCode::AVCS_ERR_END_OF_STREAM) {
                ReleaseOutputBuffer(index, ret); return;
            }
            callback_->OnOutputBufferAvailable(index, outBuffer->GetBufferAttr(), outBuffer->GetFlag(),
                                               outBuffer->GetBuffer());
        }
    }
    outputCondition_.wait_for(lock, std::chrono::milliseconds(TIMEOUT_MS),
                              [this] { return (inBufIndexQue_.size() > 0 || !isRunning); });
}
```
**说明**: ConsumerOutputBuffer 是 OS_AuCodecOut 线程主循环。处理输入帧（HandInputBuffer）→ 请求输出 buffer → codec_->ProcessRecieveData → 回调 OnOutputBufferAvailable。TIMEOUT_MS=1000ms。

---

### E13 — AudioCodecWorker::ProduceInputBuffer——OS_AuCodecIn 输入线程
**文件**: `audio_codec_worker.cpp`
**行号**: L224-245
**内容**:
```cpp
void AudioCodecWorker::ProduceInputBuffer()
{
    if (!isRunning) { usleep(DEFAULT_TRY_DECODE_TIME); return; }
    std::unique_lock lock(inputMutex_);
    while (!inBufAvaIndexQue_.empty() && isRunning) {
        uint32_t index;
        {
            std::lock_guard<std::mutex> avaLock(inAvaMutex_);
            index = inBufAvaIndexQue_.front();
            inBufAvaIndexQue_.pop();
        }
        auto inputBuffer = GetInputBufferInfo(index);
        inputBuffer->SetBufferOwned();
        callback_->OnInputBufferAvailable(index, inputBuffer->GetBuffer());
    }
    inputCondition_.wait_for(lock, std::chrono::milliseconds(TIMEOUT_MS),
                             [this] { return (!inBufAvaIndexQue_.empty() || !isRunning); });
}
```
**说明**: ProduceInputBuffer 是 OS_AuCodecIn 线程主循环。从 inBufAvaIndexQue_ 取空闲 buffer，调用 OnInputBufferAvailable 通知外部填充。填充后外部调用 QueueInputBuffer → PushInputData 入队。

---

### E14 — AudioCodecWorker::SetFirstAndEosStatus——首帧标记与 EOS 传递
**文件**: `audio_codec_worker.cpp`
**行号**: L295-306
**内容**:
```cpp
void AudioCodecWorker::SetFirstAndEosStatus(std::shared_ptr<AudioBufferInfo> &outBuffer, bool isEos, uint32_t index)
{
    if (isEos && outBuffer != nullptr) {
        outBuffer->SetEos(isEos);
    }
    if (isFirFrame_ && outBuffer != nullptr) {
        outBuffer->SetFirstFrame();
        isFirFrame_ = false;
    }
}
```
**说明**: isFirFrame_ 确保首帧标记只设置一次；EOS 从输入传递到输出。

---

### E15 — AudioCodecAdapter::Release——三层资源释放
**文件**: `audio_codec_adapter.cpp`
**行号**: L182-197
**内容**:
```cpp
int32_t AudioCodecAdapter::Release()
{
    if (state_ == CodecState::RELEASED || state_ == CodecState::RELEASING) { return AVCodecServiceErrCode::AVCS_ERR_OK; }
    state_ = CodecState::RELEASING;
    auto ret = doRelease();
    return ret;
}
int32_t AudioCodecAdapter::doRelease()
{
    if (worker_ != nullptr) { worker_->Release(); worker_.reset(); worker_ = nullptr; }
    if (audioCodec != nullptr) { audioCodec->Release(); audioCodec.reset(); audioCodec = nullptr; }
    state_ = CodecState::RELEASED;
    return AVCodecServiceErrCode::AVCS_ERR_OK;
}
```
**说明**: doRelease 先停止/释放 worker_（停止双 TaskThread），再 Release audioCodec，最后 state_=RELEASED。

---

### E16 — AudioCodecAdapter::Reset——Worker 重建
**文件**: `audio_codec_adapter.cpp`
**行号**: L156-170
**内容**:
```cpp
int32_t AudioCodecAdapter::Reset()
{
    if (worker_) { worker_->Release(); worker_.reset(); worker_ = nullptr; }
    if (audioCodec) {
        status = audioCodec->Reset();
        state_ = CodecState::INITIALIZED;
    } else {
        auto ret = doInit(); // 重建 audioCodec
    }
    return status;
}
```
**说明**: Reset 释放 worker_ 但保留 audioCodec（调用 Reset 而非 Release），然后切换到 INITIALIZED 态。若 audioCodec 为空则重建。

---

### E17 — AudioCodecWorker::Pause——双 TaskThread 暂停
**文件**: `audio_codec_worker.cpp`
**行号**: L131-150
**内容**:
```cpp
bool AudioCodecWorker::Pause()
{
    Dispose();
    if (inputTask_) { inputTask_->PauseAsync(); } else { return false; }
    if (outputTask_) { outputTask_->PauseAsync(); } else { return false; }
    ReleaseAllInBufferQueue();
    ReleaseAllInBufferAvaQueue();
    inputBuffer_->ReleaseAll();
    outputBuffer_->ReleaseAll();
    return true;
}
```
**说明**: Pause 时 Dispose() 设置 isRunning=false 并 notify_all，然后 PauseAsync() 暂停两个 TaskThread，清空队列并 ReleaseAll 清空所有 buffer。

---

### E18 — AudioCodecWorker::Dispose——停止信号广播
**文件**: `audio_codec_worker.cpp`
**行号**: L356-363
**内容**:
```cpp
void AudioCodecWorker::Dispose()
{
    isRunning = false;
    outputBuffer_->DisableRunning();
    {
        std::unique_lock lock(inputMutex_);
        inputCondition_.notify_all();
    }
    {
        std::unique_lock lock(outputMutex_);
        outputCondition_.notify_all();
    }
}
```
**说明**: Dispose 是优雅停止的核心：isRunning=false + DisableRunning() + notify_all() 唤醒两个 wait_for 循环，使线程安全退出。

---

### E19 — AudioCodecAdapter::Configure——格式校验与 codec 层下发
**文件**: `audio_codec_adapter.cpp`
**行号**: L86-99
**内容**:
```cpp
int32_t AudioCodecAdapter::Configure(const Format &format)
{
    if (!format.ContainKey(MediaDescriptionKey::MD_KEY_CHANNEL_COUNT)) {
        return AVCodecServiceErrCode::AVCS_ERR_CONFIGURE_MISMATCH_CHANNEL_COUNT;
    }
    if (!format.ContainKey(MediaDescriptionKey::MD_KEY_SAMPLE_RATE)) {
        return AVCodecServiceErrCode::AVCS_ERR_MISMATCH_SAMPLE_RATE;
    }
    int32_t ret = doConfigure(format);
    return ret;
}
int32_t AudioCodecAdapter::doConfigure(const Format &format)
{
    (void)mallopt(M_SET_THREAD_CACHE, M_THREAD_CACHE_DISABLE); // 禁用 glibc 线程缓存
    (void)mallopt(M_DELAYED_FREE, M_DELAYED_FREE_DISABLE);    // 禁用延迟释放
    int32_t ret = audioCodec->Init(format);
    if (ret != AVCodecServiceErrCode::AVCS_ERR_OK) { return ret; }
    state_ = CodecState::CONFIGURED;
    return ret;
}
```
**说明**: Configure 强制要求 MD_KEY_CHANNEL_COUNT 和 MD_KEY_SAMPLE_RATE。doConfigure 禁用 glibc 线程缓存/延迟释放以减少内存碎片（音频实时性要求），然后调用 audioCodec->Init(format)。

---

### E20 — AudioCodecAdapter::GetOutputFormat——Codec 能力上报
**文件**: `audio_codec_adapter.cpp`
**行号**: L207-215
**内容**:
```cpp
int32_t AudioCodecAdapter::GetOutputFormat(Format &format)
{
    CHECK_AND_RETURN_RET_LOG(audioCodec != nullptr, AVCodecServiceErrCode::AVCS_ERR_NO_MEMORY, "Codec not init");
    format = audioCodec->GetFormat();
    if (!format.ContainKey(MediaDescriptionKey::MD_KEY_CODEC_NAME)) {
        format.PutStringValue(MediaDescriptionKey::MD_KEY_CODEC_NAME, name_);
    }
    return AVCodecServiceErrCode::AVCS_ERR_OK;
}
```
**说明**: GetOutputFormat 代理到 audioCodec->GetFormat() 获取实际编码器输出的 format（如实际采样率/通道数可能与请求值不同），补充 name_ 后返回。

---

## 关联记忆条目

| ID | 关系 |
|----|------|
| S35 | AudioDecoderFilter——Filter层封装，AudioCodecAdapter 是其底层引擎 |
| S62 | AudioBuffersManager——AudioCodecWorker 管理的双缓冲池基础设施 |
| S158 | FFmpeg音频编码器——AudioBaseCodec 的具体软件实现之一 |
| S125 | FFmpeg音频解码器——AudioBaseCodec 的具体软件实现之一 |
| S70 | VideoCodec工厂与Loader——AudioBaseCodec::make_sharePtr 工厂模式参照 |
| S173 | 本文——AudioCodecAdapter（适配层）+ AudioCodecWorker（异步引擎层），AudioBaseCodec 是工厂创建的具体实现 |

## 设计特点

1. **CodecBase 子类适配层**：`AudioCodecAdapter` 继承 `CodecBase`，实现统一接口，屏蔽底层编码器差异
2. **工厂解耦**：`AudioBaseCodec::make_sharePtr(name_)` 根据 name_ 动态创建软件或硬件编码器
3. **双 TaskThread 并发**：`OS_AuCodecIn` 生产可用输入 buffer，`OS_AuCodecOut` 消费编解码输出
4. **glibc 内存优化**：`mallopt(M_SET_THREAD_CACHE+M_DELAYED_FREE_DISABLE)` 禁用缓存以保证实时性
5. **首帧/EOS 标记传递**：isFirFrame_ 保证首帧只标记一次，EOS 从输入传递到输出 buffer
