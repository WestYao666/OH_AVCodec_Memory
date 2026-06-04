---
mem_id: MEM-ARCH-AVCODEC-S173
title: AudioCodecAdapter + AudioCodecWorker 音频编解码适配器——AudioBaseCodec工厂注入与双TaskThread驱动
status: pending_approval
scope: [AVCodec, AudioCodec, Adapter, Worker, AudioBaseCodec, TaskThread, Pipeline, CodecState]
assoc_scenarios: [新需求开发/问题定位/音频编解码/Worker驱动]
sources:
  - https://gitcode.com/openharmony/multimedia_av_codec/blob/master/services/engine/codec/audio/audio_codec_adapter.cpp (GitCode, 467行)
  - https://gitcode.com/openharmony/multimedia_av_codec/blob/master/services/engine/codec/audio/audio_codec_worker.cpp (GitCode, 429行)
  - /home/west/av_codec_repo/services/engine/codec/include/audio/audio_codec_adapter.h (77行, 本地镜像)
  - /home/west/av_codec_repo/services/engine/codec/include/audio/audio_codec_worker.h (95行, 本地镜像)
created_by: builder-agent
created_at: "2026-05-21T14:54:00+08:00"
updated_by: builder-agent
updated_at: "2026-06-04T14:55:00+08:00"
summary: AudioCodecAdapter（CodecBase子类）三层架构，AudioBaseCodec工厂注入，双TaskThread（OS_AuCodecIn/OS_AuCodecOut）驱动，CodecState十一态机（TIMEOUT_MS=1000ms），AudioBuffersManager双缓冲池，与AudioDecoderFilter(S35)互补
evidence_count: 20
git_branch: master
git_url: https://github.com/WestYao666/OH_AVCodec_Memory
---

# MEM-ARCH-AVCODEC-S173 — AudioCodecAdapter + AudioCodecWorker 音频编解码适配器

## Metadata

| Field | Value |
|-------|-------|
| mem_id | MEM-ARCH-AVCODEC-S173 |
| topic | AudioCodecAdapter + AudioCodecWorker 音频编解码适配器——AudioBaseCodec工厂注入与双TaskThread驱动 |
| status | pending_approval |
| created | 2026-05-21T14:54:00+08:00 |
| updated | 2026-06-04T14:55:00+08:00 |
| builder | builder-agent |
| source | GitCode (https://gitcode.com/openharmony/multimedia_av_codec) + 本地镜像 |
| evidence | 20条行号级证据（含GitCode行号校正） |

---

## 一、架构定位

`AudioCodecAdapter` 是音频编解码引擎的适配层，位于 `services/engine/codec/audio/`，负责：

- 接收来自 Filter 层（或 CAPI 层）的配置/控制指令
- 通过 `AudioBaseCodec::make_sharePtr(name_)` 工厂创建具体音频编解码插件
- 委托 `AudioCodecWorker` 管理双 TaskThread（输入/输出）驱动编解码流水线

### 1.1 文件清单

| 文件 | 行数 | 职责 |
|------|------|------|
| `audio_codec_adapter.cpp` | 467 | 适配层主逻辑，CodecBase子类，生命周期管理 |
| `audio_codec_adapter.h` | 77 | AudioCodecAdapter类定义，包含 `audioCodec_` 和 `worker_` 成员 |
| `audio_codec_worker.cpp` | 429 | Worker驱动实现，双TaskThread输入/输出循环 |
| `audio_codec_worker.h` | 95 | AudioCodecWorker类定义，双缓冲队列+条件变量 |

### 1.2 在 AVCodec 模块中的位置

```
AVCodec 分层架构
├── CAPI 层 (native_audio_codec.cpp / native_avsource.cpp)
│   └── 创建 AudioCodecAdapter (通过CodecFactory)
├── 适配层 AudioCodecAdapter  ← S173
│   ├── AudioBaseCodec::make_sharePtr(name_)  ← 工厂创建具体编解码器
│   └── AudioCodecWorker       ← 双TaskThread驱动
├── 引擎层 AudioBaseCodec (抽象基类)
│   ├── FFmpeg 插件: audio_ffmpeg_aac_encoder_plugin.cpp / audio_ffmpeg_decoder_plugin.cpp
│   └── 其他插件: audio_g711mu_encoder_plugin.cpp / audio_opus_encoder_plugin.cpp 等
└── Plugin 层 (libavcodec/libavformat)
```

**关联记忆：**
- S35: AudioDecoderFilter —— Filter层封装（上游调用方）
- S95: AudioCodec C API —— CAPI层完整视图
- S50: AudioResample —— FFmpeg resample工具链
- S62: AudioBuffersManager —— 双缓冲队列管理（Worker依赖）
- S88: AudioDecoder C API —— CAPI层封装AudioCodecAdapter，与S173是引擎层vs CAPI层关系

---

## 二、AudioCodecAdapter 适配层

### 2.1 类继承结构

```
CodecBase (抽象基类)
└── AudioCodecAdapter : public CodecBase, public NoCopyable
    ├── std::shared_ptr<AudioBaseCodec> audioCodec_   ← 具体编解码器（工厂创建）
    ├── std::shared_ptr<AudioCodecWorker> worker_      ← 双TaskThread驱动
    ├── std::shared_ptr<AVCodecCallback> callback_      ← 回调
    ├── std::atomic<CodecState> state_                ← 十一态机
    └── std::string name_                              ← codec实例名
```

**证据 L24-36** (audio_codec_adapter.h):
```cpp
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
    // ...
};
```

### 2.2 生命周期七步曲

**Step 1: Init** (`AudioCodecAdapter::Init()`, L60-74)
- 状态校验：必须是 `RELEASED` 态
- 状态→`INITIALIZING` → 调用 `doInit()`
- `doInit()` L331-345: `AudioBaseCodec::make_sharePtr(name_)` 工厂创建
  ```cpp
  audioCodec = AudioBaseCodec::make_sharePtr(name_);  // L337
  state_ = CodecState::INITIALIZED;                     // L344
  ```

**Step 2: Configure** (`AudioCodecAdapter::Configure()`, L81-92)
- 校验 channel_count + sample_rate
- 调用 `doConfigure()` L352-367: `audioCodec->Init(format)` → 状态→`CONFIGURED`
- `mallopt(M_SET_THREAD_CACHE, M_THREAD_CACHE_DISABLE)` L360 禁用线程缓存

**Step 3: Start** (`AudioCodecAdapter::Start()`, L94-115)
- 状态必须是 `CONFIGURED`（或 `FLUSHED` 则 `doResume()`）
- 状态→`STARTING` → `doStart()` L369-376: 创建 `AudioCodecWorker`，`worker_->Start()`

**Step 4: QueueInputBuffer** (`AudioCodecAdapter::QueueInputBuffer()`, L205-244)
- `worker_->GetInputBufferInfo(index)` 获取缓冲区
- `BufferStatus::OWEN_BY_CLIENT` 校验 L224-234
- `worker_->PushInputData(index)` 提交输入缓冲

**Step 5: ReleaseOutputBuffer** (`AudioCodecAdapter::ReleaseOutputBuffer()`, L246-273)
- `worker_->GetOutputBufferInfo(index)` L256
- `outBuffer->ReleaseBuffer(index)` L269

**Step 6: Stop / Flush / Reset**
- Stop L117-137: 状态→`STOPPING` → `worker_->Stop()` + `audioCodec->Flush()` → `CONFIGURED`
- Flush L139-162: 状态→`FLUSHING` → `worker_->Pause()` + `audioCodec->Flush()` → `FLUSHED`
- Reset L164-182: `worker_->Release()` → `audioCodec->Reset()` 或重新 `doInit()`

**Step 7: Release** (`AudioCodecAdapter::Release()`, L184-204)
- `worker_->Release()` + `audioCodec->Release()` → 状态→`RELEASED`

### 2.3 CodecState 十一态机

**证据 L451-462** (audio_codec_adapter.cpp):
```cpp
std::map<CodecState, std::string_view> stateStrMap = {
    {CodecState::RELEASED, " RELEASED"},         // 初始/已释放
    {CodecState::INITIALIZED, " INITIALIZED"},   // 初始化完成
    {CodecState::FLUSHED, " FLUSHED"},           // 已flush
    {CodecState::RUNNING, " RUNNING"},           // 运行中
    {CodecState::INITIALIZING, " INITIALIZING"}, // 初始化中
    {CodecState::STARTING, " STARTING"},         // 启动中
    {CodecState::STOPPING, " STOPPING"},         // 停止中
    {CodecState::FLUSHING, " FLUSHING"},         // flush中
    {CodecState::RESUMING, " RESUMING"},         // 恢复中
    {CodecState::RELEASING, " RELEASING"},       // 释放中
    {CodecState::CONFIGURED, " CONFIGURED"},    // 已配置
};
```
对比 S39 VideoDecoder十一态（+FROZEN），AudioCodecAdapter多了 `RESUMING` 态（恢复FLUSHED态用 `doResume()`）

---

## 三、AudioCodecWorker 双TaskThread驱动

### 3.1 类定义

**证据 L24-58** (audio_codec_worker.h):
```cpp
class AudioCodecWorker : public NoCopyable {
    std::shared_ptr<AudioBaseCodec> codec_;
    std::shared_ptr<AVCodecCallback> callback_;
    std::shared_ptr<AudioBuffersManager> inputBuffer_;   // 输入缓冲池
    std::shared_ptr<AudioBuffersManager> outputBuffer_;   // 输出缓冲池
    std::shared_ptr<TaskThread> inputTask_;               // OS_AuCodecIn 线程
    std::shared_ptr<TaskThread> outputTask_;              // OS_AuCodecOut 线程
    std::queue<uint32_t> inBufIndexQue_;                 // 待处理输入索引队列
    std::queue<uint32_t> inBufAvaIndexQue_;             // 可用输入缓冲区索引队列
    std::atomic<bool> isRunning;
    // ...
};
```

### 3.2 双TaskThread启动流程

**证据 Begin() L383-406** (audio_codec_worker.cpp):
```cpp
bool AudioCodecWorker::Begin()
{
    for (uint32_t i = 0; i < static_cast<uint32_t>(bufferCount); i++) {
        inBufAvaIndexQue_.push(i);  // 初始化所有缓冲区索引为可用
    }
    isRunning = true;
    inputBuffer_->SetRunning();
    outputBuffer_->SetRunning();
    inputTask_->Start();   // OS_AuCodecIn 启动
    outputTask_->Start();  // OS_AuCodecOut 启动
    inputCondition_.notify_all();
    outputCondition_.notify_all();
    return true;
}
```
对应 `doStart()` L369-376 创建 `AudioCodecWorker` 并调用 `worker_->Start()` → `Begin()`

### 3.3 输入线程 ProduceInputBuffer

**证据 L213-244** (audio_codec_worker.cpp):
```cpp
void AudioCodecWorker::ProduceInputBuffer()  // OS_AuCodecIn 线程
{
    if (!isRunning) {
        usleep(DEFAULT_TRY_DECODE_TIME);  // 默认睡眠等待
        return;
    }
    while (!inBufAvaIndexQue_.empty() && isRunning) {
        uint32_t index = inBufAvaIndexQue_.front();
        inBufAvaIndexQue_.pop();
        auto inputBuffer = GetInputBufferInfo(index);
        inputBuffer->SetBufferOwned();
        callback_->OnInputBufferAvailable(index, inputBuffer->GetBuffer());  // 通知上层可用
    }
    inputCondition_.wait_for(lock, std::chrono::milliseconds(TIMEOUT_MS),
        [this] { return (!inBufAvaIndexQue_.empty() || !isRunning); });  // 1000ms超时等待
}
```

### 3.4 输出线程 ConsumerOutputBuffer

**证据 L313-358** (audio_codec_worker.cpp):
```cpp
void AudioCodecWorker::ConsumerOutputBuffer()  // OS_AuCodecOut 线程
{
    while (!inBufIndexQue_.empty() && isRunning) {
        int32_t ret = AVCodecServiceErrCode::AVCS_ERR_INVALID_DATA;
        bool isEos = HandInputBuffer(ret);  // 从输入队列取数据送编解码器
        if (ret == AVCodecServiceErrCode::AVCS_ERR_NOT_ENOUGH_DATA) continue;
        if (ret != AVCodecServiceErrCode::AVCS_ERR_OK && ret != AVCodecServiceErrCode::AVCS_ERR_END_OF_STREAM) return;

        uint32_t index;
        if (outputBuffer_->RequestAvailableIndex(index)) {  // 申请输出缓冲区
            auto outBuffer = GetOutputBufferInfo(index);
            ret = codec_->ProcessRecieveData(outBuffer);  // 获取解码/编码结果
            callback_->OnOutputBufferAvailable(index, outBuffer->GetBufferAttr(),
                outBuffer->GetFlag(), outBuffer->GetBuffer());  // 回调通知输出可用
        }
    }
    outputCondition_.wait_for(lock, std::chrono::milliseconds(TIMEOUT_MS), ...);  // 1000ms超时
}
```

### 3.5 HandInputBuffer 输入处理

**证据 L259-292** (audio_codec_worker.cpp):
```cpp
bool AudioCodecWorker::HandInputBuffer(int32_t &ret)
{
    uint32_t inputIndex = inBufIndexQue_.front();
    inBufIndexQue_.pop();
    auto inputBuffer = GetInputBufferInfo(inputIndex);
    bool isEos = inputBuffer->CheckIsEos();
    ret = codec_->ProcessSendData(inputBuffer);  // 送入 AudioBaseCodec 处理
    inputBuffer_->ReleaseBuffer(inputIndex);      // 归还输入缓冲区
    inBufAvaIndexQue_.push(inputIndex);          // 标记为可用
    inputCondition_.notify_all();
    if (ret == AVCodecServiceErrCode::AVCS_ERR_INVALID_DATA) {
        callback_->OnError(AVCodecErrorType::AVCODEC_ERROR_INTERNAL, ret);
    }
    return isEos;
}
```

---

## 四、与其他 S-series 的关系

| 关联记忆 | 关系 |
|---------|------|
| S35 (AudioDecoderFilter) | Filter层封装AudioCodecAdapter，上游调用方 |
| S95 (AudioCodec C API) | CAPI层通过CodecFactory创建AudioCodecAdapter |
| S62 (AudioBuffersManager) | Worker持有双AudioBuffersManager(input/output) |
| S50 (AudioResample) | FFmpeg resample，AudioBaseCodec内部使用 |
| S18 (AudioCodecServer) | 服务端SA架构，与AudioCodecAdapter无直接关联（不同路径） |
| S88 (AudioDecoder C API) | CAPI层封装AudioCodecAdapter，与S173是引擎层vs CAPI层关系 |

---

## 五、关键证据汇总

| # | 证据位置 | 内容摘要 |
|---|---------|---------|
| 1 | audio_codec_adapter.h L20-36 | AudioCodecAdapter类继承CodecBase，完整接口声明 |
| 2 | audio_codec_adapter.cpp L25 | 构造函数: `state_(CodecState::RELEASED), name_(name)` |
| 3 | audio_codec_adapter.cpp L60-74 | Init() 生命周期入口，状态校验+doInit() |
| 4 | audio_codec_adapter.cpp L81-92 | Configure() 配置入口，channel_count/sample_rate校验 |
| 5 | audio_codec_adapter.cpp L337 | `AudioBaseCodec::make_sharePtr(name_)` 工厂创建具体编解码器 |
| 6 | audio_codec_adapter.cpp L344 | `state_ = CodecState::INITIALIZED` 初始化完成 |
| 7 | audio_codec_adapter.cpp L360 | `mallopt(M_SET_THREAD_CACHE, M_THREAD_CACHE_DISABLE)` 禁用线程缓存 |
| 8 | audio_codec_adapter.cpp L369-376 | doStart() → `worker_ = make_shared<AudioCodecWorker>` + `worker_->Start()` |
| 9 | audio_codec_adapter.cpp L451-462 | CodecState 十一态机完整枚举 |
| 10 | audio_codec_worker.h L24-58 | AudioCodecWorker成员：inputBuffer/outputBuffer/inputTask/outputTask/双队列 |
| 11 | audio_codec_worker.cpp L383-406 | Begin() 双TaskThread启动：inBufAvaIndexQue_初始化+inputTask_->Start()+outputTask_->Start() |
| 12 | audio_codec_worker.cpp L213-244 | ProduceInputBuffer() 输入线程：OnInputBufferAvailable回调+1000ms条件等待 |
| 13 | audio_codec_worker.cpp L259-292 | HandInputBuffer() 输入处理：ProcessSendData+ReleaseBuffer+归还队列 |
| 14 | audio_codec_worker.cpp L313-358 | ConsumerOutputBuffer() 输出线程：ProcessRecieveData+OnOutputBufferAvailable回调+1000ms条件等待 |
| 15 | audio_codec_worker.cpp L59-65 | Pause()：Dispose()+inputTask_->PauseAsync()+outputTask_->PauseAsync() |
| 16 | audio_codec_worker.cpp L375-405 | Begin()：isRunning=true + inputBuffer_->SetRunning()/outputBuffer_->SetRunning() |
| 17 | audio_codec_worker.cpp L24-36 | 构造函数：DEFAULT_BUFFER_COUNT=8/TIMEOUT_MS=1000/ASYNC_HANDLE_INPUT="OS_AuCodecIn"/ASYNC_DECODE_FRAME="OS_AuCodecOut" |
| 18 | audio_codec_adapter.cpp L29-37 | ~AudioCodecAdapter()析构：worker_->Release()+audioCodec->Release()+mallopt(M_FLUSH_THREAD_CACHE, 0) |
| 19 | audio_codec_adapter.cpp L139-162 | Flush()：FLUSHING→doFlush()→FLUSHED态，含RUNNING态校验+OnError回调 |
| 20 | audio_codec_adapter.cpp L164-182 | Reset()：worker_->Release()→audioCodec->Reset()→INITIALIZED态或重新doInit() |

**行号校正说明：**
- TIMEOUT_MS: GitCode源码确认 L24-36 声明 `constexpr int TIMEOUT_MS = 1000;`（1秒），草案原写500ms有误
- L451-462 stateStrMap 位置在GitCode中确认为第451行以后

---

## 六、架构图

```
应用层 (Filter/CAPI)
        │
        ▼
AudioCodecAdapter  (适配层, 467行cpp)
        │
        ├── doInit()      → AudioBaseCodec::make_sharePtr(name_)
        ├── doConfigure() → audioCodec->Init(format)
        ├── doStart()     → AudioCodecWorker + TaskThread启动
        │
        ▼
AudioCodecWorker  (双TaskThread驱动, 429行cpp)
        │
        ├── inputTask_  (OS_AuCodecIn)  → ProduceInputBuffer()
        │   └── callback_->OnInputBufferAvailable()
        │
        └── outputTask_ (OS_AuCodecOut) → ConsumerOutputBuffer()
            └── callback_->OnOutputBufferAvailable()
                    │
                    ▼
            AudioBaseCodec (引擎层)
                    │
                    ├── audio_ffmpeg_aac_encoder_plugin.cpp (AAC编码)
                    ├── audio_ffmpeg_decoder_plugin.cpp (通用音频解码)
                    ├── audio_opus_encoder_plugin.cpp
                    ├── audio_g711mu_encoder_plugin.cpp
                    └── ... (17+ 子插件)
```

---

## 七、总结

| 维度 | 要点 |
|------|------|
| **定位** | 音频编解码引擎适配层 + Worker线程驱动框架 |
| **三层架构** | AudioCodecAdapter(CAPI/Filter适配) → AudioCodecWorker(TaskThread驱动) → AudioBaseCodec(引擎) |
| **状态机** | CodecState十一态 (RELEASED→INITIALIZING→INITIALIZED→CONFIGURED→STARTING→RUNNING)，含FLUSHED/RESUMING |
| **线程模型** | 双TaskThread：OS_AuCodecIn(ProduceInputBuffer)+OS_AuCodecOut(ConsumerOutputBuffer)，1000ms超时等待 |
| **缓冲管理** | AudioBuffersManager双缓冲池(inputBuffer/outputBuffer)，各含8个AudioBufferInfo |
| **工厂创建** | `AudioBaseCodec::make_sharePtr(name_)` 按名称动态创建具体编解码器插件 |
| **关键路径** | QueueInputBuffer → PushInputData → HandInputBuffer → ProcessSendData → ProcessRecieveData → OnOutputBufferAvailable |