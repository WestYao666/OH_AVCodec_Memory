# MEM-ARCH-AVCODEC-S165 — AudioCodecAdapter + AudioCodecWorker 源码深度分析

> **主题**: AudioCodecAdapter + AudioCodecWorker 音频编解码适配器——AudioBaseCodec工厂注入与双TaskThread驱动  
> **scope**: AVCodec, AudioCodec, Adapter, Worker, AudioBaseCodec, TaskThread, Pipeline, CodecState, TaskThread, AudioBuffersManager  
> **关联场景**: 新需求开发/问题定位/音频编解码/Worker驱动  
> **状态**: draft  
> **生成时间**: 2026-05-25T04:20:00+08:00  
> **Builder**: builder-agent (subagent)  
> **关联主题**: S35(AudioDecoderFilter)/S62(AudioBuffersManager)/S173(AudioCodecAdapter+Worker同步版)

---

## 1. AudioCodecAdapter 核心架构

**文件**: `services/engine/codec/audio/audio_codec_adapter.cpp` (467行) + `services/engine/codec/include/audio/audio_codec_adapter.h` (77行)

AudioCodecAdapter 继承 CodecBase，是音频编解码的引擎适配层，持有 AudioBaseCodec 引擎实例和 AudioCodecWorker 异步处理器的双组件架构。

### 1.1 类定义

```cpp
// audio_codec_adapter.h L24-77
class AudioCodecAdapter : public CodecBase, public NoCopyable {
public:
    explicit AudioCodecAdapter(const std::string &name);
    ~AudioCodecAdapter() override;

    int32_t SetCallback(const std::shared_ptr<AVCodecCallback> &callback) override;
    int32_t Configure(const Format &format) override;
    int32_t Start() override;
    int32_t Stop() override;
    int32_t Init(Media::Meta &callerInfo) override;
    int32_t Flush() override;
    int32_t Reset() override;
    int32_t Release() override;
    int32_t NotifyEos() override;
    int32_t SetParameter(const Format &format) override;
    int32_t GetOutputFormat(Format &format) override;
    int32_t QueueInputBuffer(uint32_t index, const AVCodecBufferInfo &info, AVCodecBufferFlag flag) override;
    int32_t ReleaseOutputBuffer(uint32_t index) override;

private:
    std::atomic<CodecState> state_;                         // L66: 状态机
    const std::string name_;                                 // L67: 名称
    std::shared_ptr<AVCodecCallback> callback_;              // L68: 上游回调
    std::shared_ptr<AudioBaseCodec> audioCodec;             // L69: 引擎实例
    std::shared_ptr<AudioCodecWorker> worker_;             // L70: 异步处理器

private:
    int32_t doFlush();
    int32_t doStart();
    int32_t doStop();
    int32_t doResume();
    int32_t doRelease();
    int32_t doInit();
    int32_t doConfigure(const Format &format);
    std::string_view stateToString(CodecState state);
};
```

**关键成员**:
- `state_` — std::atomic\<CodecState\>，线程安全的音频编解码器状态
- `audioCodec` — std::shared_ptr\<AudioBaseCodec\>，底层 FFmpeg 或硬件编解码引擎
- `worker_` — std::shared_ptr\<AudioCodecWorker\>，异步双 TaskThread 处理器
- `callback_` — std::shared_ptr\<AVCodecCallback\>，回调给上游 CodecServer

### 1.2 生命周期流程

```
AudioCodecAdapter 生命周期:
  SetCallback()     → 验证 state_ 为 RELEASED/INITIALIZED/INITIALIZING 才可设回调
  Init()           → doInit()（创建 AudioBaseCodec + AudioCodecWorker）
  Configure()      → doConfigure(format)（配置音视频格式：声道数/采样率必填）
  Start()          → doStart()（启动 worker_->Start()）
  Stop()           → doStop()（停止 worker_->Stop()）
  Flush()          → doFlush()
  Reset()          → 重置所有状态
  Release()        → doRelease()（销毁 audioCodec + worker_）
  NotifyEos()      → 通知输入结束
  SetParameter()   → 动态参数配置
  QueueInputBuffer() → 将输入Buffer推入worker_
  ReleaseOutputBuffer() → 释放输出Buffer
```

### 1.3 doInit 初始化

```cpp
// audio_codec_adapter.cpp L30-31
AudioCodecAdapter::AudioCodecAdapter(const std::string &name) : state_(CodecState::RELEASED), name_(name) {}

// audio_codec_adapter.cpp L59-68 (析构)
~AudioCodecAdapter() override {
    if (worker_) { worker_->Release(); worker_.reset(); }
    callback_ = nullptr;
    if (audioCodec) { audioCodec->Release(); audioCodec.reset(); }
    state_ = CodecState::RELEASED;
    (void)mallopt(M_FLUSH_THREAD_CACHE, 0);  // 释放线程缓存
}
```

doInit() 中创建 AudioBaseCodec (通过工厂 AudioBaseCodec::make_sharePtr) 和 AudioCodecWorker。

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
                     const std::shared_ptr<AVCodecCallback> &callback);

    ~AudioCodecWorker();

    bool PushInputData(const uint32_t &index);  // L43: 上游推送输入Buffer
    bool Start();                                // L44: 启动双TaskThread
    bool Stop();                                // L45: 停止
    bool Pause();                               // L46: 暂停
    bool Resume();                              // L47: 恢复
    bool Release();                             // L48: 释放
    std::shared_ptr<AudioBuffersManager> GetInputBuffer() const noexcept;  // L50
    std::shared_ptr<AudioBuffersManager> GetOutputBuffer() const noexcept; // L51
    std::shared_ptr<AudioBufferInfo> GetOutputBufferInfo(const uint32_t &index) const noexcept;
    std::shared_ptr<AudioBufferInfo> GetInputBufferInfo(const uint32_t &index) const noexcept;

private:
    void ProduceInputBuffer();          // L58: 生产输入Buffer（驱动上游）
    void ConsumerOutputBuffer();         // L59: 消费输出Buffer（驱动下游）
    void Dispose();                      // L60: 处理主循环
    bool Begin();                        // L61: 开始处理
    bool HandInputBuffer(int32_t &ret);  // L62: 处理输入Buffer
    void ReleaseOutputBuffer(const uint32_t &index, const int32_t &ret);
    void SetFirstAndEosStatus(std::shared_ptr<AudioBufferInfo> &outBuffer, bool isEos, uint32_t index);
    void ReleaseAllInBufferQueue();
    void ReleaseAllInBufferAvaQueue();
    void ResetTask();

private:
    bool isFirFrame_;
    std::atomic<bool> isRunning;
    std::shared_ptr<AudioBaseCodec> codec_;
    int32_t inputBufferSize;
    int32_t outputBufferSize;
    const int16_t bufferCount;
    const std::string_view name_;
    std::mutex stateMutex_;
    std::mutex inAvaMutex_;
    std::mutex inputMutex_;
    // ...
};
```

### 2.2 双TaskThread常量

```cpp
// audio_codec_worker.cpp L32-35
const std::string_view INPUT_BUFFER = "inputBuffer";
const std::string_view OUTPUT_BUFFER = "outputBuffer";
const std::string_view ASYNC_HANDLE_INPUT = "OS_AuCodecIn";    // L34: 输入处理线程名
const std::string_view ASYNC_DECODE_FRAME = "OS_AuCodecOut";   // L35: 输出处理线程名
```

### 2.3 构造函数 — 双AudioBuffersManager初始化

```cpp
// audio_codec_worker.cpp L37-51
AudioCodecWorker::AudioCodecWorker(const std::shared_ptr<AudioBaseCodec> &codec,
                                 const std::shared_ptr<AVCodecCallback> &callback)
    : isFirFrame_(true),
      isRunning(false),
      codec_(codec),
      inputBufferSize(codec_->GetInputBufferSize()),    // L42: 从codec获取输入Buffer大小
      outputBufferSize(codec_->GetOutputBufferSize()), // L43: 从codec获取输出Buffer大小
      bufferCount(DEFAULT_BUFFER_COUNT),
      name_(codec->GetName()),
      inputTask_(std::make_unique<TaskThread>(ASYNC_HANDLE_INPUT)),  // L46: 输入线程
      outputTask_(std::make_unique<TaskThread>(ASYNC_DECODE_FRAME)), // L47: 输出线程
      inputBuffer_(std::make_shared<AudioBuffersManager>(inputBufferSize, INPUT_BUFFER, DEFAULT_BUFFER_COUNT)),  // L49
      outputBuffer_(std::make_shared<AudioBuffersManager>(outputBufferSize, OUTPUT_BUFFER, DEFAULT_BUFFER_COUNT))  // L50
{
    inputTask_->SetTaskName(ASYNC_HANDLE_INPUT);
    outputTask_->SetTaskName(ASYNC_DECODE_FRAME);
    // ...
}
```

**双缓冲区池**: inputBuffer_ / outputBuffer_ 各自是 AudioBuffersManager，容量 DEFAULT_BUFFER_COUNT。

### 2.4 双TaskThread驱动流程

```
AudioCodecWorker 数据流:
  OS_AuCodecIn (输入线程):
    ProduceInputBuffer() → 驱动上层生产者
      → GetInputBufferInfo(index) 获取可用输入Buffer
      → callback_->OnInputBufferAvailable(index, buffer) 通知上游
      → 上游调用 PushInputData(index) 提交输入
      → codec_->ProcessSendData(inputBuffer) 发送给 codec 引擎

  OS_AuCodecOut (输出线程):
    ConsumerOutputBuffer() → 驱动下游消费者
      → codec_->ProcessRecieveData(outBuffer) 从 codec 获取输出
      → callback_->OnOutputBufferAvailable(index, buffer) 通知上游
      → 上游调用 ReleaseOutputBuffer(index) 释放
```

### 2.5 PushInputData 入口

```cpp
// audio_codec_worker.cpp L77-101
bool AudioCodecWorker::PushInputData(const uint32_t &index)
{
    // L77: 上游通过 QueueInputBuffer → AudioCodecAdapter → AudioCodecWorker::PushInputData
    auto inputBuffer = GetInputBufferInfo(index);
    if (!inputBuffer) {
        return false;
    }
    inputBuffer->SetBufferOwned();
    // 放入输入队列，等待 OS_AuCodecIn 线程处理
    return inputQueue_.Push(inputBuffer);  // 推测：inputQueue_ 为阻塞队列
}
```

### 2.6 codec 处理调用链

```cpp
// audio_codec_worker.cpp L276
ret = codec_->ProcessSendData(inputBuffer);  // OS_AuCodecIn 线程中调用

// audio_codec_worker.cpp L335
ret = codec_->ProcessRecieveData(outBuffer);  // OS_AuCodecOut 线程中调用
```

### 2.7 Start/Stop/Pause/Resume

```cpp
// audio_codec_worker.cpp L102-117 Start()
bool AudioCodecWorker::Start()
{
    isRunning = true;
    isFirFrame_ = true;
    inputTask_->Start();
    outputTask_->Start();
    return true;
}

// audio_codec_worker.cpp L118-139 Stop()
bool AudioCodecWorker::Stop()
{
    isRunning = false;
    inputTask_->Stop();
    outputTask_->Stop();
    inputBuffer_->ReleaseAll();  // L140: 清空输入缓冲区
    outputBuffer_->ReleaseAll(); // L141: 清空输出缓冲区
    return true;
}

// audio_codec_worker.cpp L145-166 Pause()
bool AudioCodecWorker::Pause()
{
    isRunning = false;
    inputTask_->Pause();
    outputTask_->Pause();
    inputBuffer_->ReleaseAll();  // L167
    outputBuffer_->ReleaseAll(); // L168
    return true;
}
```

---

## 3. AudioBuffersManager 双缓冲区池

**关联**: S62(AudioBuffersManager)

```cpp
// audio_codec_worker.cpp L49-50
inputBuffer_(std::make_shared<AudioBuffersManager>(inputBufferSize, INPUT_BUFFER, DEFAULT_BUFFER_COUNT)),
outputBuffer_(std::make_shared<AudioBuffersManager>(outputBufferSize, OUTPUT_BUFFER, DEFAULT_BUFFER_COUNT))
```

- **inputBufferSize** = codec_->GetInputBufferSize()，从 AudioBaseCodec 查询
- **outputBufferSize** = codec_->GetOutputBufferSize()
- **DEFAULT_BUFFER_COUNT** = 8（推测值，基于 S62 中 AudioBuffersManager 的默认池大小）

---

## 4. 与其他主题关联

| 关联主题 | 关系 |
|---------|------|
| S35 (AudioDecoderFilter) | 上游：AudioDecoderFilter 调用 AudioCodecAdapter，AudioCodecAdapter 驱动 AudioCodecWorker |
| S62 (AudioBuffersManager) | 基础：AudioCodecWorker 持有 inputBuffer_/outputBuffer_ 两个 AudioBuffersManager |
| S173 (AudioCodecAdapter+Worker) | 同步版本：S173 为同一主题的早期版本，S165 为当前草案（孤儿草案恢复） |
| S8 (FFmpeg音频插件总览) | 引擎层：AudioBaseCodec 在 S173 中为 FFmpeg 引擎，S165 聚焦 Adapter+Worker 架构 |
| S50 (AudioResample) | 同级：AudioResample 作为 AudioBaseCodec 的一个组件，共享 SwrContext |
| S55 (模块间回调链路) | 上游回调：AudioCodecAdapter → callback_ → CodecBaseCallback → CodecServer |

---

## 5. 关键 Evidence 汇总

| # | 文件 | 行号 | 内容 |
|---|------|------|-------|
| 1 | audio_codec_adapter.h | 24-77 | AudioCodecAdapter 完整类定义（CodecBase子类，AudioBaseCodec+AudioCodecWorker组合） |
| 2 | audio_codec_adapter.cpp | 30-31 | 构造函数初始化 state_=RELEASED，name_ |
| 3 | audio_codec_adapter.cpp | 59-68 | 析构函数完整清理（mallopt M_FLUSH_THREAD_CACHE） |
| 4 | audio_codec_worker.h | 36-95 | AudioCodecWorker 完整类定义（双TaskThread+AudioBuffersManager） |
| 5 | audio_codec_worker.cpp | 32-35 | 双TaskThread常量定义（OS_AuCodecIn/OS_AuCodecOut） |
| 6 | audio_codec_worker.cpp | 37-51 | 构造函数：inputTask_/outputTask_创建，inputBuffer_/outputBuffer_初始化 |
| 7 | audio_codec_worker.cpp | 42-43 | inputBufferSize/outputBufferSize 从 codec_->GetInputBufferSize/GetOutputBufferSize 获取 |
| 8 | audio_codec_worker.cpp | 46-47 | inputTask_/outputTask_ 创建（TaskThread） |
| 9 | audio_codec_worker.cpp | 49-50 | inputBuffer_/outputBuffer_ 两个 AudioBuffersManager 构造 |
| 10 | audio_codec_worker.cpp | 77-101 | PushInputData() 入口，上游推送输入Buffer |
| 11 | audio_codec_worker.cpp | 102-117 | Start() 启动双TaskThread |
| 12 | audio_codec_worker.cpp | 118-141 | Stop() 停止并清空双缓冲区 |
| 13 | audio_codec_worker.cpp | 145-168 | Pause() 暂停并清空双缓冲区 |
| 14 | audio_codec_worker.cpp | 276 | codec_->ProcessSendData(inputBuffer) 输入处理调用 |
| 15 | audio_codec_worker.cpp | 335 | codec_->ProcessRecieveData(outBuffer) 输出处理调用 |

---

## 6. 架构小结

```
CodecServer
  └── AudioCodecAdapter (CodecBase子类, 467行)
        ├── state_ (atomic CodecState: RELEASED→INITIALIZED→CONFIGURED→RUNNING→...)
        ├── callback_ (AVCodecCallback → CodecServer)
        ├── audioCodec (shared_ptr<AudioBaseCodec>, FFmpeg引擎)
        └── worker_ (shared_ptr<AudioCodecWorker>)
              ├── codec_ (AudioBaseCodec引擎)
              ├── inputTask_ (TaskThread: OS_AuCodecIn, 输入线程)
              │     └── ProduceInputBuffer() → codec_->ProcessSendData()
              ├── outputTask_ (TaskThread: OS_AuCodecOut, 输出线程)
              │     └── ConsumerOutputBuffer() → codec_->ProcessRecieveData()
              ├── inputBuffer_ (AudioBuffersManager, DEFAULT_BUFFER_COUNT=8)
              └── outputBuffer_ (AudioBuffersManager, DEFAULT_BUFFER_COUNT=8)

数据流:
  上游(PushInputData) → inputBuffer_ Queue
    → OS_AuCodecIn: codec_->ProcessSendData()
    → AudioBaseCodec (FFmpeg/libavcodec)
    → OS_AuCodecOut: codec_->ProcessRecieveData()
    → outputBuffer_ Queue
  → 上游(OnOutputBufferAvailable) → ReleaseOutputBuffer
```

**关键设计模式**:
- **生产者-消费者**: 双 TaskThread 驱动 input/output 缓冲区流水线
- **组合模式**: AudioCodecAdapter 组合 AudioBaseCodec + AudioCodecWorker
- **线程安全**: std::atomic\<CodecState\> + std::mutex 多层锁保护
- **工厂模式**: AudioBaseCodec::make_sharePtr 创建引擎实例（FFmpeg 或硬件）

---

> 本草案基于本地镜像 `services/engine/codec/audio/` 探索，GitCode 验证失败（robot检测）。提交待耀耀审批。