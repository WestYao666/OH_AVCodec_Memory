# MEM-ARCH-AVCODEC-S173.md

> **主题**: AudioCodecAdapter + AudioCodecWorker 音频编解码适配器——AudioBaseCodec工厂注入与双TaskThread驱动
> **scope**: AVCodec, AudioCodec, Adapter, Worker, AudioBaseCodec, TaskThread, Pipeline, CodecState
> **关联场景**: 新需求开发/问题定位/音频编解码/Worker驱动
> **状态**: pending_approval
> **来源**: Builder 2026-05-21 注册，2026-05-25 Builder 生成草案

---

## 1. 架构定位

S173 填补了 AudioCodec 引擎层的最后一公里：CodecBase 适配层（AudioCodecAdapter） + 双 TaskThread 驱动（AudioCodecWorker） + 音频引擎基类（AudioBaseCodec）。三者构成 AudioCodec 的完整三层调用链：

```
Native C API (AudioCodecObject)
    ↓ OH_AudioCodec_CreateByMime
AVCodecAudioCodecImpl (IPC CodecClient 代理侧)
    ↓ AudioBaseCodec::make_sharePtr 工厂
AudioCodecAdapter (Filter 适配层, CodecBase 子类)
    ↓ 持有 audioCodec_ + worker_
AudioCodecWorker (双 TaskThread 驱动)
    ↓ 持有 audioCodec_ + inputBuffer_/outputBuffer_
AudioBaseCodec (引擎基类，FFmpeg/硬件解码器统一抽象层)
    ↓ dlopen 插件
具体音频解码器（FFmpegDecoderPlugin / AAC / FLAC / MP3 / G711mu / LBVC...）
```

**关联记忆**：
- S35 (AudioDecoderFilter): Filter 层封装，与 S173 引擎层互补
- S62 (AudioBuffersManager): AudioCodecWorker 的双缓冲区管理器
- S125 (FFmpegBaseDecoder / DecoderPlugin): AudioBaseCodec 引擎层的具体实现
- S8 (FFmpeg 音频插件总览): FFmpegAdapter 完整编解码矩阵

---

## 2. AudioCodecAdapter（Filter 适配层）

**源码**：
- `services/engine/codec/audio/audio_codec_adapter.cpp` (467 行)
- `services/engine/codec/include/audio/audio_codec_adapter.h` (77 行)

### 2.1 类继承关系

```cpp
class AudioCodecAdapter : public CodecBase, public NoCopyable {
public:
    explicit AudioCodecAdapter(const std::string &name);
    ~AudioCodecAdapter() override;

    // CodecBase 接口（部分）
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
    std::atomic<CodecState> state_;                       // L34: 线程安全状态机
    const std::string name_;                                // L35: Codec 实例名称
    std::shared_ptr<AVCodecCallback> callback_;            // L36: 上层回调
    std::shared_ptr<AudioBaseCodec> audioCodec;            // L37: 引擎基类（工厂注入）
    std::shared_ptr<AudioCodecWorker> worker_;            // L38: 双 TaskThread 驱动

private: // 私有 Do 方法（对应七状态机转换）
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

### 2.2 构造函数与初始化

```cpp
// audio_codec_adapter.cpp L33
AudioCodecAdapter::AudioCodecAdapter(const std::string &name)
    : state_(CodecState::RELEASED), name_(name) {}

// L36-40: audioCodec_ + worker_ 均通过 AudioBaseCodec::make_sharePtr 工厂创建
// audioCodec 在 doInit() 中由 AudioBaseCodec::make_sharePtr(name_) 创建
// worker_ 在 doInit() 中由 std::make_shared<AudioCodecWorker>(audioCodec, callback_) 创建
```

### 2.3 生命周期七步曲（与 VideoCodecAdapter 对称）

| 步骤 | 入口函数 | 内部 Do 方法 | 状态转换 | 关键操作 |
|------|---------|------------|---------|---------|
| 1 | SetCallback | — | RELEASED | 检查 state_，设置 callback_ |
| 2 | Init | doInit | RELEASED→INITIALIZED | 创建 audioCodec + worker_ |
| 3 | Configure | doConfigure | INITIALIZED→CONFIGURED | 检查 channel_count/sample_rate |
| 4 | Start | doStart | CONFIGURED→RUNNING | 启动 worker_->Start() |
| 5 | Flush | doFlush | RUNNING→FLUSHED | worker_->Pause() |
| 6 | Stop | doStop | RUNNING/FLUSHED→CONFIGURED | worker_->Stop() |
| 7 | Release | doRelease | ANY→RELEASED | worker_->Release()，释放 audioCodec |

### 2.4 Configure 校验

```cpp
// audio_codec_adapter.cpp L100-115
int32_t AudioCodecAdapter::Configure(const Format &format)
{
    if (!format.ContainKey(MediaDescriptionKey::MD_KEY_CHANNEL_COUNT)) {
        AVCODEC_LOGE("Configure failed, missing channel count key in format.");
        return AVCodecServiceErrCode::AVCS_ERR_CONFIGURE_MISMATCH_CHANNEL_COUNT;
    }
    if (!format.ContainKey(MediaDescriptionKey::MD_KEY_SAMPLE_RATE)) {
        AVCODEC_LOGE("Configure failed, missing sample rate key in format.");
        return AVCodecServiceErrCode::AVCS_ERR_MISMATCH_SAMPLE_RATE;
    }
    int32_t ret = doConfigure(format);
    return ret;
}
```

### 2.5 Start 状态机

```cpp
// audio_codec_adapter.cpp L118-140
int32_t AudioCodecAdapter::Start()
{
    CHECK_AND_RETURN_RET_LOG(callback_ != nullptr, AVCodecServiceErrCode::AVCS_ERR_UNKNOWN,
        "adapter start error, callback not initialized .");
    if (!audioCodec) {
        AVCODEC_LOGE("adapter start error, audio codec not initialized .");
        return AVCodecServiceErrCode::AVCS_ERR_UNKNOWN;
    }
    if (state_ == CodecState::FLUSHED) {
        AVCODEC_LOGI("Start, doResume");
        return doResume();
    }
    if (state_ != CodecState::CONFIGURED) {
        AVCODEC_LOGE("Start is incorrect, state = %{public}s .", stateToString(state_).data());
        return AVCodecServiceErrCode::AVCS_ERR_INVALID_STATE;
    }
    // L136: state_ = CodecState::STARTING;
    // L138: worker_->Start();
    // L140: state_ = CodecState::RUNNING;
}
```

---

## 3. AudioCodecWorker（双 TaskThread 驱动）

**源码**：
- `services/engine/codec/audio/audio_codec_worker.cpp` (429 行)
- `services/engine/codec/include/audio/audio_codec_worker.h` (95 行)

### 3.1 类定义

```cpp
class AudioCodecWorker : public NoCopyable {
public:
    AudioCodecWorker(const std::shared_ptr<AudioBaseCodec> &codec,
                     const std::shared_ptr<AVCodecCallback> &callback);

    bool PushInputData(const uint32_t &index);
    bool Start();
    bool Stop();
    bool Pause();
    bool Resume();
    bool Release();

    std::shared_ptr<AudioBuffersManager> GetInputBuffer() const noexcept;
    std::shared_ptr<AudioBuffersManager> GetOutputBuffer() const noexcept;
    std::shared_ptr<AudioBufferInfo> GetOutputBufferInfo(const uint32_t &index) const noexcept;
    std::shared_ptr<AudioBufferInfo> GetInputBufferInfo(const uint32_t &index) const noexcept;

private:
    void ProduceInputBuffer();       // OS_AuCodecIn TaskThread 驱动输入
    void ConsumerOutputBuffer();     // OS_AuCodecOut TaskThread 驱动输出
    void Dispose();
    bool Begin();
    bool HandInputBuffer(int32_t &ret);
    void ReleaseOutputBuffer(const uint32_t &index, const int32_t &ret);
    void SetFirstAndEosStatus(...);
    void ReleaseAllInBufferQueue();
    void ReleaseAllInBufferAvaQueue();
    void ResetTask();

private:
    bool isFirFrame_;
    std::atomic<bool> isRunning;
    std::shared_ptr<AudioBaseCodec> codec_;
    int32_t inputBufferSize;
    int32_t outputBufferSize;
    const int16_t bufferCount;  // = DEFAULT_BUFFER_COUNT = 8
    const std::string_view name_;
    std::mutex stateMutex_;
    std::mutex inAvaMutex_;
    std::mutex inputMutex_;
    std::mutex outputMutex_;
    std::condition_variable inputCondition_;
    std::condition_variable outputCondition_;

    std::unique_ptr<TaskThread> inputTask_;   // OS_AuCodecIn 线程
    std::unique_ptr<TaskThread> outputTask_;  // OS_AuCodecOut 线程
    std::shared_ptr<AVCodecCallback> callback_;
    std::shared_ptr<AudioBuffersManager> inputBuffer_;   // 输入缓冲区管理器
    std::shared_ptr<AudioBuffersManager> outputBuffer_;  // 输出缓冲区管理器
    std::queue<uint32_t> inBufIndexQue_;     // 输入 Buffer 索引队列
    std::queue<uint32_t> inBufAvaIndexQue_;  // 可用输入 Buffer 索引队列
};
```

### 3.2 双 TaskThread 驱动机制

```cpp
// audio_codec_worker.cpp L44-52
constexpr short DEFAULT_BUFFER_COUNT = 8;
constexpr int TIMEOUT_MS = 1000;
const std::string_view ASYNC_HANDLE_INPUT = "OS_AuCodecIn";    // 输入处理线程名
const std::string_view ASYNC_DECODE_FRAME = "OS_AuCodecOut";    // 输出处理线程名

// audio_codec_worker.cpp L54-66: 构造函数
AudioCodecWorker::AudioCodecWorker(const std::shared_ptr<AudioBaseCodec> &codec,
                                   const std::shared_ptr<AVCodecCallback> &callback)
    : isFirFrame_(true),
      isRunning(true),
      codec_(codec),
      inputBufferSize(codec_->GetInputBufferSize()),
      outputBufferSize(codec_->GetOutputBufferSize()),
      bufferCount(DEFAULT_BUFFER_COUNT),   // 8 个缓冲区
      name_(codec->GetCodecType()),
      inputTask_(std::make_unique<TaskThread>(ASYNC_HANDLE_INPUT)),
      outputTask_(std::make_unique<TaskThread>(ASYNC_DECODE_FRAME)),
      callback_(callback),
      inputBuffer_(std::make_shared<AudioBuffersManager>(inputBufferSize, INPUT_BUFFER, DEFAULT_BUFFER_COUNT)),
      outputBuffer_(std::make_shared<AudioBuffersManager>(outputBufferSize, OUTPUT_BUFFER, DEFAULT_BUFFER_COUNT))
{
    inputTask_->RegisterHandler([this] { ProduceInputBuffer(); });
    outputTask_->RegisterHandler([this] { ConsumerOutputBuffer(); });
}
```

### 3.3 数据流驱动路径

```
外部调用 AudioCodecAdapter::QueueInputBuffer(index)
    ↓ PushInputData(index)
    ↓ inBufIndexQue_.push(index) + notify_all
    ↓ OS_AuCodecIn TaskThread 唤醒
    ↓ ProduceInputBuffer()
        ↓ codec_->SendFrame() 发送给 AudioBaseCodec
    ↓ AudioBaseCodec 引擎处理（FFmpeg/硬件）
    ↓ OS_AuCodecOut TaskThread 消费
    ↓ ConsumerOutputBuffer()
        ↓ codec_->ReceiveFrame() 获取解码结果
        ↓ callback_->OnOutputBufferAvailable() 回调通知上层
```

### 3.4 PushInputData 入口

```cpp
// audio_codec_worker.cpp L101-118
bool AudioCodecWorker::PushInputData(const uint32_t &index)
{
    AVCODEC_LOGD_LIMIT(LOGD_FREQUENCY, "%{public}s Worker PushInputData enter,index:%{public}u",
                        name_.data(), index);
    if (!isRunning) {
        return true;
    }
    if (!callback_ || !codec_) {
        AVCODEC_LOGE("push input buffer failed in worker, callback/codec is nullptr.");
        Dispose();
        return false;
    }
    std::lock_guard<std::mutex> lock(stateMutex_);
    inBufIndexQue_.push(index);       // L116: 入队
    outputCondition_.notify_all();    // L117: 唤醒 ConsumerOutputBuffer
    return true;
}
```

---

## 4. 与 S62 AudioBuffersManager 的关系

```cpp
// AudioCodecWorker 持有双 AudioBuffersManager
// inputBuffer_:  inputBufferSize + DEFAULT_BUFFER_COUNT(8)
// outputBuffer_: outputBufferSize + DEFAULT_BUFFER_COUNT(8)
//
// AudioBuffersManager::RequestAvailableIndex() 阻塞等待 TIMEOUT_MS=1000ms
// AudioBuffersManager::ReleaseBuffer() 重置状态 + notify_all
//
// AudioBufferInfo 双 AVSharedMemoryBase（数据 + 元数据）
// BufferStatus 枚举（IDLE / OWEN_BY_CLIENT）
```

---

## 5. 与 S125/S35 的上下游关系

```
S35 AudioDecoderFilter（Filter 层）
    ↓
S173 AudioCodecAdapter（Filter 适配层）
    ↓ AudioBaseCodec::make_sharePtr
S125 FFmpegBaseDecoder（引擎基类）
    ↓
具体 FFmpeg 音频解码器（AudioFFMpegDecoderPlugin）

对比 VideoCodec 对称路径：
S45 SurfaceDecoderFilter → S154 VideoDecoder 基类 → 具体解码器实现
```

---

## 6. 关键证据汇总

| # | 文件 | 行号 | 内容 |
|---|------|------|------|
| 1 | audio_codec_adapter.h | 23-34 | AudioCodecAdapter 类定义，CodecBase 子类 |
| 2 | audio_codec_adapter.cpp | 33 | 构造函数 state_ = RELEASED |
| 3 | audio_codec_adapter.cpp | 100-115 | Configure 校验 channel_count/sample_rate |
| 4 | audio_codec_adapter.cpp | 118-140 | Start 状态机 + FLUSHED 特殊处理 |
| 5 | audio_codec_adapter.cpp | 56-80 | 析构函数 Release worker_ + audioCodec |
| 6 | audio_codec_worker.h | 45-60 | AudioCodecWorker 私有成员（双 TaskThread + 双 BufferManager） |
| 7 | audio_codec_worker.cpp | 44-52 | DEFAULT_BUFFER_COUNT=8, TIMEOUT_MS=1000, 双 TaskThread 命名 |
| 8 | audio_codec_worker.cpp | 54-66 | 构造函数初始化 inputBuffer_/outputBuffer_ + RegisterHandler |
| 9 | audio_codec_worker.cpp | 101-118 | PushInputData 入口 + notify_all |
| 10 | audio_codec_worker.cpp | 101-118 | ProduceInputBuffer / ConsumerOutputBuffer 双驱动循环 |

---

## 7. 架构总结

```
AudioCodecAdapter        AudioCodecWorker            AudioBaseCodec
┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│ CodecBase 接口    │    │ 双 TaskThread    │    │ 引擎基类         │
│ 七状态机          │───▶│ OS_AuCodecIn     │───▶│ (FFmpeg/硬件)    │
│ state_ 原子变量   │    │ OS_AuCodecOut    │    │ dlopen 插件      │
│ callback_        │    │                  │    │                  │
│ audioCodec_ ─────┼───▶│ 双 AudioBuffers │    │ SendFrame()      │
│ worker_ ─────────┼───▶│ Manager (8缓冲) │    │ ReceiveFrame()   │
└──────────────────┘    └──────────────────┘    └──────────────────┘

生命周期: SetCallback → Init(创建worker) → Configure → Start(worker.Start) → Stop/Flush → Release
```