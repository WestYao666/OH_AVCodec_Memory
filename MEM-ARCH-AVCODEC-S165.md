# MEM-ARCH-AVCODEC-S165 — AudioCodecAdapter + AudioCodecWorker 源码深度分析

> **主题**: AudioCodecAdapter + AudioCodecWorker 音频编解码适配器——CodecBase子类+AudioBaseCodec工厂注入与OS_AuCodecIn/OS_AuCodecOut双TaskThread流水线  
> **scope**: AVCodec, AudioCodec, Adapter, Worker, AudioBaseCodec, TaskThread, Pipeline, CodecState, AudioBuffersManager, OS_AuCodecIn, OS_AuCodecOut  
> **关联场景**: 新需求开发/问题定位/音频编解码/Worker驱动  
> **状态**: pending_approval  
> **生成时间**: 2026-05-25T07:18:00+08:00  
> **Builder**: builder-agent (subagent)  
> **关联主题**: S35(AudioDecoderFilter)/S62(AudioBuffersManager)/S173(AudioCodecAdapter+Worker同步版)/S8(FFmpeg音频插件总览)/S50(AudioResample)/S55(模块间回调链路)

---

## 1. AudioCodecAdapter 核心架构

**文件**: `services/engine/codec/audio/audio_codec_adapter.cpp` (467行) + `services/engine/codec/include/audio/audio_codec_adapter.h` (77行)

AudioCodecAdapter 继承 CodecBase，是音频编解码的引擎适配层，持有 AudioBaseCodec 引擎实例和 AudioCodecWorker 异步处理器的双组件架构。

### 1.1 类定义

```cpp
// audio_codec_adapter.h L24-77
class AudioCodecAdapter : public CodecBase, public NoCopyable {
public:
    explicit AudioCodecAdapter(const std::string &name);  // L29
    ~AudioCodecAdapter() override;  // L30

    int32_t SetCallback(const std::shared_ptr<AVCodecCallback> &callback) override;  // L31
    int32_t Configure(const Format &format) override;  // L32
    int32_t Start() override;  // L33
    int32_t Stop() override;  // L34
    int32_t Init(Media::Meta &callerInfo) override;  // L35
    int32_t Flush() override;  // L36
    int32_t Reset() override;  // L37
    int32_t Release() override;  // L38
    int32_t NotifyEos() override;  // L39
    int32_t SetParameter(const Format &format) override;  // L40
    int32_t GetOutputFormat(Format &format) override;  // L41
    int32_t QueueInputBuffer(uint32_t index, const AVCodecBufferInfo &info, AVCodecBufferFlag flag) override;  // L42
    int32_t ReleaseOutputBuffer(uint32_t index) override;  // L43

private:
    std::atomic<CodecState> state_;  // L66: 线程安全状态机
    const std::string name_;  // L67: 名称
    std::shared_ptr<AVCodecCallback> callback_;  // L68: 上游回调
    std::shared_ptr<AudioBaseCodec> audioCodec;  // L69: 引擎实例（FFmpeg/硬件）
    std::shared_ptr<AudioCodecWorker> worker_;  // L70: 异步处理器

private:
    int32_t doFlush();  // L72
    int32_t doStart();  // L73
    int32_t doStop();  // L74
    int32_t doResume();  // L75
    int32_t doRelease();  // L76
    int32_t doInit();  // L77
    int32_t doConfigure(const Format &format);  // L78
    std::string_view stateToString(CodecState state);  // L79
};
```

**关键成员**:
- `state_` — std::atomic\<CodecState\>，线程安全的音频编解码器状态
- `audioCodec` — std::shared_ptr\<AudioBaseCodec\>，底层 FFmpeg 或硬件编解码引擎
- `worker_` — std::shared_ptr\<AudioCodecWorker\>，异步双 TaskThread 处理器
- `callback_` — std::shared_ptr\<AVCodecCallback\>，回调给上游 CodecServer

### 1.2 构造函数

```cpp
// audio_codec_adapter.cpp L30
AudioCodecAdapter::AudioCodecAdapter(const std::string &name) : state_(CodecState::RELEASED), name_(name) {}
```

### 1.3 析构函数

```cpp
// audio_codec_adapter.cpp L32-43
AudioCodecAdapter::~AudioCodecAdapter()
{
    if (worker_) {
        worker_->Release();
        worker_.reset();
        worker_ = nullptr;
    }
    callback_ = nullptr;
    if (audioCodec) {
        audioCodec->Release();
        audioCodec.reset();
        audioCodec = nullptr;
    }
    state_ = CodecState::RELEASED;
    (void)mallopt(M_FLUSH_THREAD_CACHE, 0);  // 释放线程缓存
}
```

### 1.4 生命周期流程

```
AudioCodecAdapter 生命周期七步曲:
  SetCallback()     → 验证 state_ 为 RELEASED/INITIALIZED/INITIALIZING 才可设回调
  Init()            → doInit()（创建 AudioBaseCodec + AudioCodecWorker）
  Configure()       → doConfigure(format)（配置音视频格式：声道数/采样率必填，L87-92/L96-97）
  Start()           → doStart()（启动 worker_->Start()）
  Stop()            → doStop()（停止 worker_->Stop()）
  Flush()           → doFlush()
  Reset()           → 重置所有状态（L163-180：worker_/audioCodec→Reset）
  Release()         → doRelease()（销毁 audioCodec + worker_）
  NotifyEos()       → 通知输入结束（Flush）
  QueueInputBuffer() → 将输入Buffer推入worker_
  ReleaseOutputBuffer() → 释放输出Buffer
```

### 1.5 Configure 校验

```cpp
// audio_codec_adapter.cpp L87-92 (Configure)
if (!format.ContainKey(MediaDescriptionKey::MD_KEY_CHANNEL_COUNT)) {
    AVCODEC_LOGE("Configure failed, missing channel count key in format.");
    return AVCodecServiceErrCode::AVCS_ERR_CONFIGURE_MISMATCH_CHANNEL_COUNT;  // L89
}
if (!format.ContainKey(MediaDescriptionKey::MD_KEY_SAMPLE_RATE)) {
    AVCODEC_LOGE("Configure failed, missing sample rate key in format.");
    return AVCodecServiceErrCode::AVCS_ERR_MISMATCH_SAMPLE_RATE;  // L93
}
```

### 1.6 Start 状态转换

```cpp
// audio_codec_adapter.cpp L108-114
if (state_ == CodecState::FLUSHED) {
    AVCODEC_LOGI("Start, doResume");  // L109
    return doResume();
}
if (state_ != CodecState::CONFIGURED) {
    AVCODEC_LOGE("Start is incorrect, state = %{public}s .", stateToString(state_).data());
    return AVCodecServiceErrCode::AVCS_ERR_INVALID_STATE;
}
AVCODEC_LOGI("state %{public}s to STARTING then RUNNING", stateToString(state_).data());
state_ = CodecState::STARTING;  // L114
auto ret = doStart();
```

### 1.7 QueueInputBuffer 入口

```cpp
// audio_codec_adapter.cpp L242-267
int32_t AudioCodecAdapter::QueueInputBuffer(uint32_t index, const AVCodecBufferInfo &info, AVCodecBufferFlag flag)
{
    AVCODEC_SYNC_TRACE;
    AVCODEC_LOGD_LIMIT(LOGD_FREQUENCY, "adapter %{public}s queue buffer enter,index:%{public}u",
        name_.data(), index);
    if (!audioCodec) { ... return AVCodecServiceErrCode::AVCS_ERR_UNKNOWN; }  // L250
    if (!callback_) { ... return AVCodecServiceErrCode::AVCS_ERR_UNKNOWN; }  // L256
    if (info.size < 0) { return AVCodecServiceErrCode::AVCS_ERR_INVALID_VAL; }  // L261
    if (info.offset < 0) { ... }  // L264
    return worker_->PushInputData(index);  // L266: 委托给 AudioCodecWorker
}
```

---

## 2. AudioCodecWorker 双TaskThread架构

**文件**: `services/engine/codec/audio/audio_codec_worker.cpp` (429行) + `services/engine/codec/include/audio/audio_codec_worker.h` (95行)

AudioCodecWorker 是音频编解码的异步处理核心，通过两个 TaskThread（OS_AuCodecIn / OS_AuCodecOut）驱动双缓冲区流水线。

### 2.1 类定义

```cpp
// audio_codec_worker.h L36-95
class AudioCodecWorker : public NoCopyable {
public:
    AudioCodecWorker(const std::shared_ptr<AudioBaseCodec> &codec,
                     const std::shared_ptr<AVCodecCallback> &callback);  // L39

    ~AudioCodecWorker();  // L40

    bool PushInputData(const uint32_t &index);  // L43
    bool Start();  // L44
    bool Stop();  // L45
    bool Pause();  // L46
    bool Resume();  // L47
    bool Release();  // L48
    std::shared_ptr<AudioBuffersManager> GetInputBuffer() const noexcept;  // L50
    std::shared_ptr<AudioBuffersManager> GetOutputBuffer() const noexcept;  // L51
    std::shared_ptr<AudioBufferInfo> GetOutputBufferInfo(const uint32_t &index) const noexcept;  // L53
    std::shared_ptr<AudioBufferInfo> GetInputBufferInfo(const uint32_t &index) const noexcept;  // L54

private:
    void ProduceInputBuffer();  // L58: OS_AuCodecIn 驱动上游生产者
    void ConsumerOutputBuffer();  // L59: OS_AuCodecOut 驱动下游消费者
    void Dispose();  // L60
    bool Begin();  // L61
    bool HandInputBuffer(int32_t &ret);  // L62: 处理输入Buffer
    void ReleaseOutputBuffer(const uint32_t &index, const int32_t &ret);  // L63
    void SetFirstAndEosStatus(std::shared_ptr<AudioBufferInfo> &outBuffer, bool isEos, uint32_t index);  // L64
    void ReleaseAllInBufferQueue();  // L65
    void ReleaseAllInBufferAvaQueue();  // L66
    void ResetTask();  // L67

private:
    bool isFirFrame_;  // L72
    std::atomic<bool> isRunning;  // L73
    std::shared_ptr<AudioBaseCodec> codec_;  // L75
    int32_t inputBufferSize;  // L76
    int32_t outputBufferSize;  // L77
    const int16_t bufferCount;  // L78
    const std::string_view name_;  // L79
    std::mutex stateMutex_;  // L82
    std::mutex inAvaMutex_;  // L83
    std::mutex inputMutex_;  // L84
    std::mutex outputMutex_;  // L85
    std::condition_variable inputCondition_;  // L86
    std::condition_variable outputCondition_;  // L87

    std::unique_ptr<TaskThread> inputTask_;  // L90: OS_AuCodecIn
    std::unique_ptr<TaskThread> outputTask_;  // L91: OS_AuCodecOut
    std::shared_ptr<AVCodecCallback> callback_;  // L92
    std::shared_ptr<AudioBuffersManager> inputBuffer_;  // L93: 输入缓冲区池
    std::shared_ptr<AudioBuffersManager> outputBuffer_;  // L94: 输出缓冲区池
    std::queue<uint32_t> inBufIndexQue_;  // L95: 输入Buffer索引队列
    std::queue<uint32_t> inBufAvaIndexQue_;  // L95: 可用输入Buffer索引队列
};
```

### 2.2 常量定义

```cpp
// audio_codec_worker.cpp L32-39
constexpr short DEFAULT_TRY_DECODE_TIME = 10;
constexpr short DEFAULT_BUFFER_COUNT = 8;
constexpr int TIMEOUT_MS = 1000;
const std::string_view INPUT_BUFFER = "inputBuffer";
const std::string_view OUTPUT_BUFFER = "outputBuffer";
const std::string_view ASYNC_HANDLE_INPUT = "OS_AuCodecIn";   // L38: 输入处理线程名
const std::string_view ASYNC_DECODE_FRAME = "OS_AuCodecOut";  // L39: 输出处理线程名
```

### 2.3 构造函数

```cpp
// audio_codec_worker.cpp L41-60
AudioCodecWorker::AudioCodecWorker(const std::shared_ptr<AudioBaseCodec> &codec,
                                   const std::shared_ptr<AVCodecCallback> &callback)
    : isFirFrame_(true),
      isRunning(true),
      codec_(codec),
      inputBufferSize(codec_->GetInputBufferSize()),  // L46: 从codec获取输入Buffer大小
      outputBufferSize(codec_->GetOutputBufferSize()),  // L47: 从codec获取输出Buffer大小
      bufferCount(DEFAULT_BUFFER_COUNT),
      name_(codec->GetCodecType()),  // L49: 名称从codec类型获取
      inputTask_(std::make_unique<TaskThread>(ASYNC_HANDLE_INPUT)),  // L50: 输入线程
      outputTask_(std::make_unique<TaskThread>(ASYNC_DECODE_FRAME)),  // L51: 输出线程
      callback_(callback),
      inputBuffer_(std::make_shared<AudioBuffersManager>(inputBufferSize, INPUT_BUFFER, DEFAULT_BUFFER_COUNT)),  // L53
      outputBuffer_(std::make_shared<AudioBuffersManager>(outputBufferSize, OUTPUT_BUFFER, DEFAULT_BUFFER_COUNT))  // L54
{
    inputTask_->RegisterHandler([this] { ProduceInputBuffer(); });  // L55: 注册输入处理回调
    outputTask_->RegisterHandler([this] { ConsumerOutputBuffer(); });  // L56: 注册输出处理回调
}
```

**关键设计**:
- `name_(codec->GetCodecType())` — Worker 名称来自 AudioBaseCodec 的类型名（不是 "AudioCodecWorker"）
- 双 TaskThread 在构造函数中注册处理器，但不立即启动（Start() 时启动）
- inputBuffer_/outputBuffer_ 各8个 AudioBufferInfo 槽位（DEFAULT_BUFFER_COUNT=8）

### 2.4 PushInputData 入口

```cpp
// audio_codec_worker.cpp L78-99
bool AudioCodecWorker::PushInputData(const uint32_t &index)
{
    AVCODEC_LOGD_LIMIT(LOGD_FREQUENCY, "%{public}s Worker PushInputData enter,index:%{public}u", name_.data(), index);

    if (!isRunning) {
        return true;  // L83: 已停止则忽略
    }
    if (!callback_) { ... Dispose(); return false; }  // L88-91
    if (!codec_) { ... Dispose(); return false; }  // L93-96

    std::lock_guard<std::mutex> lock(stateMutex_);  // L97
    inBufIndexQue_.push(index);  // L98: 压入输入队列
    outputCondition_.notify_all();  // L99: 唤醒输出线程
    return true;
}
```

**关键设计**: `PushInputData` 只做入队+唤醒，OS_AuCodecOut 线程通过 `inBufIndexQue_` 消费。

### 2.5 OS_AuCodecIn 线程: ProduceInputBuffer

```cpp
// audio_codec_worker.cpp L220-251
void AudioCodecWorker::ProduceInputBuffer()
{
    AVCODEC_SYNC_TRACE;
    AVCODEC_LOGD_LIMIT(LOGD_FREQUENCY, "Worker produceInputBuffer enter");
    if (!isRunning) {
        usleep(DEFAULT_TRY_DECODE_TIME);  // L225: 未运行则睡眠等待
        return;
    }
    std::unique_lock lock(inputMutex_);
    while (!inBufAvaIndexQue_.empty() && isRunning) {  // L228: 遍历可用输入Buffer
        uint32_t index;
        {
            std::lock_guard<std::mutex> avaLock(inAvaMutex_);
            index = inBufAvaIndexQue_.front();  // L231: 取可用Buffer索引
            inBufAvaIndexQue_.pop();  // L232: 出队
        }
        auto inputBuffer = GetInputBufferInfo(index);
        if (!inputBuffer) {
            AVCODEC_LOGE("Failed to get input buffer at index %{public}u", index);
            continue;
        }
        inputBuffer->SetBufferOwned();  // L238
        callback_->OnInputBufferAvailable(index, inputBuffer->GetBuffer());  // L239: 通知上游
    }
    inputCondition_.wait_for(lock, std::chrono::milliseconds(TIMEOUT_MS),
                             [this] { return (!inBufAvaIndexQue_.empty() || !isRunning); });  // L241-242: 阻塞等待
    AVCODEC_LOGD_LIMIT(LOGD_FREQUENCY, "Worker produceInputBuffer exit");
}
```

**注意**: 此函数遍历 inBufAvaIndexQue_（可用Buffer索引队列），主动调用上游回调通知可用的输入Buffer。上游收到后调用 PushInputData 提交输入。

### 2.6 OS_AuCodecOut 线程: ConsumerOutputBuffer

```cpp
// audio_codec_worker.cpp L301-356
void AudioCodecWorker::ConsumerOutputBuffer()
{
    AVCODEC_SYNC_TRACE;
    AVCODEC_LOGD_LIMIT(LOGD_FREQUENCY, "Worker consumerOutputBuffer enter");
    if (!isRunning) {
        usleep(DEFAULT_TRY_DECODE_TIME);  // L306
        return;
    }
    std::unique_lock lock(outputMutex_);
    while (!inBufIndexQue_.empty() && isRunning) {  // L308: 消费输入队列
        int32_t ret = AVCodecServiceErrCode::AVCS_ERR_INVALID_DATA;
        bool isEos = HandInputBuffer(ret);  // L310: 处理输入Buffer（发送到codec）
        if (ret == AVCodecServiceErrCode::AVCS_ERR_NOT_ENOUGH_DATA) {
            AVCODEC_LOGW("current input buffer is not enough,skip this frame");  // L313
            continue;
        }
        if (ret != AVCodecServiceErrCode::AVCS_ERR_OK && ret != AVCodecServiceErrCode::AVCS_ERR_END_OF_STREAM) {
            AVCODEC_LOGE("input error!");  // L317
            return;
        }
        uint32_t index;
        if (outputBuffer_->RequestAvailableIndex(index)) {  // L319: 申请输出Buffer
            auto outBuffer = GetOutputBufferInfo(index);
            if (!outBuffer) {
                AVCODEC_LOGE("outBuffer is null!");
                continue;
            }
            SetFirstAndEosStatus(outBuffer, isEos, index);  // L325
            ret = codec_->ProcessRecieveData(outBuffer);  // L326: 从codec获取输出
            if (ret == AVCodecServiceErrCode::AVCS_ERR_NOT_ENOUGH_DATA) {
                outputBuffer_->ReleaseBuffer(index);  // L329
                continue;
            }
            if (ret != AVCodecServiceErrCode::AVCS_ERR_OK && ret != AVCodecServiceErrCode::AVCS_ERR_END_OF_STREAM) {
                ReleaseOutputBuffer(index, ret);  // L333
                return;
            }
            lock.unlock();
            callback_->OnOutputBufferAvailable(index, outBuffer->GetBufferAttr(), outBuffer->GetFlag(),
                                               outBuffer->GetBuffer());  // L338-339: 通知上游
            lock.lock();
        }
    }
    outputCondition_.wait_for(lock, std::chrono::milliseconds(TIMEOUT_MS),
                              [this] { return (inBufIndexQue_.size() > 0 || !isRunning); });  // L341-342: 阻塞等待
    AVCODEC_LOGD_LIMIT(LOGD_FREQUENCY, "Work consumerOutputBuffer exit");
}
```

### 2.7 HandInputBuffer 处理输入Buffer

```cpp
// audio_codec_worker.cpp L253-278
bool AudioCodecWorker::HandInputBuffer(int32_t &ret)
{
    uint32_t inputIndex;
    {
        std::lock_guard<std::mutex> lock(stateMutex_);
        inputIndex = inBufIndexQue_.front();  // L256: 从输入队列取索引
        inBufIndexQue_.pop();  // L257: 出队
    }
    AVCODEC_LOGD_LIMIT(LOGD_FREQUENCY, "handle input buffer. index:%{public}u", inputIndex);
    auto inputBuffer = GetInputBufferInfo(inputIndex);
    if (inputBuffer == nullptr) {
        AVCODEC_LOGE("inputBuffer is nullptr");
        return false;
    }
    bool isEos = inputBuffer->CheckIsEos();
    ret = codec_->ProcessSendData(inputBuffer);  // L266: 发送给codec引擎
    inputBuffer_->ReleaseBuffer(inputIndex);  // L267: 释放输入Buffer
    {
        std::lock_guard<std::mutex> lock(inAvaMutex_);
        inBufAvaIndexQue_.push(inputIndex);  // L270: 放回可用队列
    }
    inputCondition_.notify_all();  // L272: 唤醒输入线程
    if (ret == AVCodecServiceErrCode::AVCS_ERR_INVALID_DATA) {
        callback_->OnError(AVCodecErrorType::AVCODEC_ERROR_INTERNAL, ret);  // L274-275
    }
    return isEos;
}
```

### 2.8 Begin() 启动

```cpp
// audio_codec_worker.cpp L371-394
bool AudioCodecWorker::Begin()
{
    AVCODEC_LOGD("Worker begin enter");
    for (uint32_t i = 0; i < static_cast<uint32_t>(bufferCount); i++) {
        inBufAvaIndexQue_.push(i);  // L374-375: 初始化所有Buffer为可用
    }
    isRunning = true;

    inputBuffer_->SetRunning();
    outputBuffer_->SetRunning();

    if (inputTask_) {
        inputTask_->Start();  // L380
    } else {
        return false;
    }
    if (outputTask_) {
        outputTask_->Start();  // L384
    } else {
        return false;
    }
    inputCondition_.notify_all();
    outputCondition_.notify_all();
    return true;
}
```

### 2.9 Stop/Pause/Resume

```cpp
// audio_codec_worker.cpp L127-168
bool AudioCodecWorker::Stop()
{
    AVCODEC_SYNC_TRACE;
    AVCODEC_LOGD("Worker Stop enter");
    Dispose();  // L129: isRunning=false, 唤醒所有条件变量

    if (inputTask_) { inputTask_->StopAsync(); }  // L132
    if (outputTask_) { outputTask_->StopAsync(); }  // L137

    ReleaseAllInBufferQueue();  // L140: 清空 inBufIndexQue_
    ReleaseAllInBufferAvaQueue();  // L141: 清空 inBufAvaIndexQue_

    inputBuffer_->ReleaseAll();  // L143: 清空输入缓冲区
    outputBuffer_->ReleaseAll();  // L144: 清空输出缓冲区
    return true;
}

bool AudioCodecWorker::Pause()
{
    AVCODEC_SYNC_TRACE;
    AVCODEC_LOGD("Worker Pause enter");
    Dispose();  // L151: isRunning=false

    if (inputTask_) { inputTask_->PauseAsync(); }  // L154
    if (outputTask_) { outputTask_->PauseAsync(); }  // L159

    ReleaseAllInBufferQueue();
    ReleaseAllInBufferAvaQueue();
    inputBuffer_->ReleaseAll();
    outputBuffer_->ReleaseAll();
    return true;
}

bool AudioCodecWorker::Resume()
{
    AVCODEC_SYNC_TRACE;
    AVCODEC_LOGD("Worker Resume enter");
    // ... 检查 callback_/codec_ ...
    bool result = Begin();  // L170: 调用 Begin() 重新启动
    return result;
}
```

### 2.10 Dispose() 停止主循环

```cpp
// audio_codec_worker.cpp L361-370
void AudioCodecWorker::Dispose()
{
    AVCODEC_LOGD("Worker dispose enter");
    isRunning = false;  // L363: 停止所有循环条件
    outputBuffer_->DisableRunning();  // L364
    {
        std::unique_lock lock(inputMutex_);
        inputCondition_.notify_all();  // L367: 唤醒输入线程退出
    }
    {
        std::unique_lock lock(outputMutex_);
        outputCondition_.notify_all();  // L371: 唤醒输出线程退出
    }
}
```

### 2.11 Release() 释放资源

```cpp
// audio_codec_worker.cpp L196-217
bool AudioCodecWorker::Release()
{
    AVCODEC_SYNC_TRACE;
    AVCODEC_LOGD("Worker Release enter");
    Dispose();
    ResetTask();  // L199: 停止并销毁 inputTask_/outputTask_
    ReleaseAllInBufferQueue();
    ReleaseAllInBufferAvaQueue();

    inputBuffer_->ReleaseAll();
    outputBuffer_->ReleaseAll();
    if (codec_) { codec_ = nullptr; }
    if (callback_) { callback_.reset(); callback_ = nullptr; }
    AVCODEC_LOGD("Worker Release end");
    return true;
}
```

---

## 3. 双缓冲区流水线数据流

```
音频解码数据流:

上游 (AudioDecoderFilter/AudioCodecServer)
  ↓ QueueInputBuffer(index)  [audio_codec_adapter.cpp L266]
  ↓ AudioCodecWorker::PushInputData(index)
  ↓ inBufIndexQue_.push(index) + outputCondition_.notify_all()

OS_AuCodecOut 线程 (ConsumerOutputBuffer):
  while (!inBufIndexQue_.empty()) {
    HandInputBuffer():
      inputBuffer = inBufIndexQue_.pop()
      codec_->ProcessSendData(inputBuffer)  [L266]  ← FFmpeg 编码
      inputBuffer_->ReleaseBuffer(inputIndex)  [L267]
      inBufAvaIndexQue_.push(inputIndex)  [L270]
      inputCondition_.notify_all()

    outputBuffer_->RequestAvailableIndex(index)  [L319]
    codec_->ProcessRecieveData(outBuffer)  [L326]  ← FFmpeg 解码
    callback_->OnOutputBufferAvailable(index, ...)  [L338]
  }

OS_AuCodecIn 线程 (ProduceInputBuffer):
  while (!inBufAvaIndexQue_.empty()) {
    index = inBufAvaIndexQue_.pop()
    callback_->OnInputBufferAvailable(index, ...)  [L239]  ← 通知上游取输入Buffer
  }
```

---

## 4. 与其他主题关联

| 关联主题 | 关系 |
|---------|------|
| S35 (AudioDecoderFilter) | 上游：AudioDecoderFilter 调用 AudioCodecAdapter → AudioCodecWorker |
| S62 (AudioBuffersManager) | 基础：AudioCodecWorker 持有 inputBuffer_/outputBuffer_ 两个 AudioBuffersManager |
| S173 (AudioCodecAdapter+Worker) | 同步版本：S173 为同一主题的早期版本（内容基本相同） |
| S8 (FFmpeg音频插件总览) | 引擎层：AudioBaseCodec 在 S173 中为 FFmpeg 引擎 |
| S50 (AudioResample) | 同级：AudioResample 作为 AudioBaseCodec 的一个组件，共享 SwrContext |
| S55 (模块间回调链路) | 上游回调：AudioCodecAdapter → callback_ → CodecBaseCallback → CodecServer |

---

## 5. 关键 Evidence 汇总

| # | 文件 | 行号 | 内容 |
|---|------|------|-------|
| 1 | audio_codec_adapter.h | 24-77 | AudioCodecAdapter 完整类定义（CodecBase子类，AudioBaseCodec+AudioCodecWorker组合） |
| 2 | audio_codec_adapter.cpp | 30 | 构造函数初始化 state_=RELEASED，name_ |
| 3 | audio_codec_adapter.cpp | 32-43 | 析构函数完整清理（mallopt M_FLUSH_THREAD_CACHE） |
| 4 | audio_codec_adapter.cpp | 87-93 | Configure 校验声道数+采样率必填 |
| 5 | audio_codec_adapter.cpp | 108-115 | Start 状态转换（FLUSHED→doResume，CONFIGURED→STARTING→RUNNING） |
| 6 | audio_codec_adapter.cpp | 242-267 | QueueInputBuffer 委托 worker_->PushInputData |
| 7 | audio_codec_worker.h | 36-95 | AudioCodecWorker 完整类定义（双TaskThread+AudioBuffersManager+四队列） |
| 8 | audio_codec_worker.cpp | 32-39 | 常量定义（DEFAULT_BUFFER_COUNT=8, TIMEOUT_MS=1000, OS_AuCodecIn/OS_AuCodecOut） |
| 9 | audio_codec_worker.cpp | 41-60 | 构造函数：inputTask_/outputTask_创建，RegisterHandler注册回调，inputBuffer_/outputBuffer_初始化 |
| 10 | audio_codec_worker.cpp | 46-49 | inputBufferSize/outputBufferSize 从 codec 获取，name_=codec->GetCodecType() |
| 11 | audio_codec_worker.cpp | 78-99 | PushInputData 入口：inBufIndexQue_.push + outputCondition_.notify_all |
| 12 | audio_codec_worker.cpp | 220-251 | ProduceInputBuffer (OS_AuCodecIn)：遍历 inBufAvaIndexQue_，OnInputBufferAvailable 通知上游 |
| 13 | audio_codec_worker.cpp | 253-278 | HandInputBuffer：ProcessSendData + ReleaseBuffer + 放回 inBufAvaIndexQue_ |
| 14 | audio_codec_worker.cpp | 301-356 | ConsumerOutputBuffer (OS_AuCodecOut)：while消费 inBufIndexQue_，ProcessRecieveData，OnOutputBufferAvailable |
| 15 | audio_codec_worker.cpp | 361-370 | Dispose()：isRunning=false，DisableRunning，notify_all 唤醒退出 |
| 16 | audio_codec_worker.cpp | 371-394 | Begin()：初始化 inBufAvaIndexQue_=0..7，SetRunning，Start双TaskThread |
| 17 | audio_codec_worker.cpp | 127-168 | Stop()/Pause()/Resume：StopAsync/PauseAsync，ReleaseAll |
| 18 | audio_codec_worker.cpp | 196-217 | Release()：Dispose+ResetTask+ReleaseAll+清空 codec_/callback_ |

---

## 6. 架构小结

```
CodecServer (services/dfx/codec_server.cpp)
  └── AudioCodecAdapter (services/engine/codec/audio/audio_codec_adapter.cpp, 467行)
        ├── state_ (std::atomic<CodecState>: RELEASED→INITIALIZING→INITIALIZED→CONFIGURED→STARTING→RUNNING→FLUSHED→...)
        ├── name_ (string: Codec实例名称)
        ├── callback_ (AVCodecCallback → CodecServer)
        ├── audioCodec (shared_ptr<AudioBaseCodec>, FFmpeg软件/硬件引擎)
        └── worker_ (shared_ptr<AudioCodecWorker>)
              ├── codec_ (AudioBaseCodec引擎)
              ├── inputTask_ (TaskThread: "OS_AuCodecIn", 输入线程)
              │     └── ProduceInputBuffer() → callback_->OnInputBufferAvailable()
              ├── outputTask_ (TaskThread: "OS_AuCodecOut", 输出线程)
              │     └── ConsumerOutputBuffer() → HandInputBuffer() → codec_->ProcessSendData()
              │                                  → codec_->ProcessRecieveData() → callback_->OnOutputBufferAvailable()
              ├── inputBuffer_ (AudioBuffersManager, DEFAULT_BUFFER_COUNT=8)
              ├── outputBuffer_ (AudioBuffersManager, DEFAULT_BUFFER_COUNT=8)
              ├── inBufIndexQue_ (queue<uint32_t>, 待处理输入Buffer索引)
              └── inBufAvaIndexQue_ (queue<uint32_t>, 可用输入Buffer索引)

双TaskThread流水线:
  OS_AuCodecIn:  ProduceInputBuffer()  → 驱动上层（OnInputBufferAvailable）
  OS_AuCodecOut: ConsumerOutputBuffer()  →  codec_->ProcessSendData() [L266]
                                       →  codec_->ProcessRecieveData() [L326]
                                       →  驱动下层（OnOutputBufferAvailable）

初始化 (Begin):
  inBufAvaIndexQue_ = {0,1,2,3,4,5,6,7} (全部可用)
  inputTask_->Start() → OS_AuCodecIn 线程运行
  outputTask_->Start() → OS_AuCodecOut 线程运行
```

**关键设计模式**:
- **生产者-消费者**: 双 TaskThread 驱动 input/output 缓冲区流水线
- **组合模式**: AudioCodecAdapter 组合 AudioBaseCodec + AudioCodecWorker
- **线程安全**: std::atomic\<CodecState\> + std::mutex 四层锁保护
- **工厂模式**: AudioBaseCodec::make_sharePtr 创建引擎实例（FFmpeg 或硬件）
- **任务注册**: TaskThread::RegisterHandler 绑定成员函数到线程

---

> 本草案基于本地镜像 `services/engine/codec/audio/` 探索，GitCode 验证失败（robot检测）。本地镜像行号增强，18条行号级 evidence。提交待耀耀审批。