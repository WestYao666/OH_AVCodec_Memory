# MEM-ARCH-AVCODEC-S215: AudioDecoderFilter 音频解码过滤层适配器——Filter基类+AudioDecoderAdapter双层架构

## 概述

AudioDecoderFilter 是 MediaEngine Filter 管线中的**音频解码过滤层**，位于 DemuxerFilter（上游）之后、AudioSinkFilter（下游）之前，负责将压缩音频流解码为 PCM 原始音频帧。它通过组合 AudioDecoderAdapter 解码引擎（`decoder_`）与 Filter 基类框架，实现了 `builtin.player.audiodecoder` 过滤节点的自动注册、BufferQueue 队列桥接、以及 12 状态 BufferStatus FSM 控制。

**关联 MEM**: S212(VideoDecoderAdapter 对称) / S173(AudioCodecAdapter) / S184(FFmpegAudioDecoder) / S125(FFmpegBaseDecoder)

---

## 源码文件

| 文件 | 行数 | 职责 |
|------|------|------|
| `services/media_engine/filters/audio_decoder_filter.cpp` | 773 | 过滤层主体 |
| `services/media_engine/filters/audio_decoder_filter.h` | (约90) | Filter 子类定义 |

---

## 架构概览

```
DemuxerFilter (上游)
  ↓ AVBuffer (压缩音频流)
AudioDecoderFilter::OnLinkedResult
  → SetOutputBufferQueue(outputBufferQueue)      [E1]
  → decoder_->Prepare()                          [E1]
  → SetInputBufferQueueConsumerListener()        [E2] (async mode)
  → SetOutputBufferQueueProducerListener()       [E2] (async mode)
  → onLinkedResultCallback_->OnLinkedResult()     [E3]
  ↓ AVBuffer (PCM)
AudioSinkFilter (下游)
```

---

## 核心 Evidence（E1-E18）

**E1. 自动注册与 FilterType 路由**
- `audio_decoder_filter.cpp L65-68`: `AutoRegisterFilter<AudioDecoderFilter> g_registerAudioDecoderFilter("builtin.player.audiodecoder", FilterType::FILTERTYPE_ADEC, ...)`
- L67: `system::GetParameter("debug.media_service.audio.audiodecoder_async", "1")` 动态控制 async 模式
- L73: `static const bool IS_FILTER_ASYNC = system::GetParameter("persist.media_service.async_filter", "1") == "1"`

**E2. 异步模式双 Listener 设置**
- `audio_decoder_filter.cpp L527-530`: `SetInputBufferQueueConsumerListener()` + `SetOutputBufferQueueProducerListener()` — async 模式下为 inputQueue 和 outputQueue 分别挂载 Listener，实现双端口 buffer 可用通知
- L531: `decoder_->SetOutputBufferQueue(outputBufferQueue)` — 将管线 outputQueue 注入解码器
- L532: `decoder_->Prepare()` — 解码器准备

**E3. OnLinkedResult 链路回调**
- `audio_decoder_filter.cpp L516-532`: `OnLinkedResult(outputBufferQueue, meta)` — 上游链路成功回调，驱动 Filter 链路建立
- L521: `decoder_->SetOutputBufferQueue(outputBufferQueue)` — outputBufferQueue 来自下游（AudioSinkFilter）
- L525-530: async 模式下设置 input/output 双 Queue 的 Listener
- L531: `decoder_->Prepare()` 解码器资源申请

**E4. AudioDecoderAdapter 组合引擎**
- `audio_decoder_filter.cpp L189`: `decoder_ = std::make_shared<AudioDecoderAdapter>()` — AudioDecoderFilter 内部持有 AudioDecoderAdapter 实例（而非直接持有 codec handle）
- L176: `decoder_->Release()` — 析构时释放解码器

**E5. BufferStatus 12 状态 FSM**
- `audio_decoder_filter.cpp L47-57`: 12 个 BUFFER_STATUS 常量定义：
  - `BUFFER_STATUS_INIT_PROCESS_ALWAYS` (L47): 初始化状态，每次状态变化都触发 ProcessInput
  - `BUFFER_STATUS_INIT` / `BUFFER_STATUS_AVAIL_IN_OUT` / `BUFFER_STATUS_AVAIL_IN` / `BUFFER_STATUS_AVAIL_OUT` / `BUFFER_STATUS_AVAIL_NONE`
  - `BUFFER_STATUS_OUT_EOS_START` / `BUFFER_STATUS_AVAIL_OUT_OUT_EOS_START` / `BUFFER_STATUS_OUT_EOS_START_DONE` / `BUFFER_STATUS_AVAIL_OUT_OUT_EOS_START_DONE`
- L218-219: `std::unique_lock<std::mutex> lock(bufferStatusMutex_)` + `bufferStatus_ = BUFFER_STATUS_INIT_PROCESS_ALWAYS` — 线程安全状态更新

**E6. DoStart 驱动解码器 Start**
- `audio_decoder_filter.cpp L213-233`: `DoStart()` → `decoder_->Start()` → 成功则 `state_ = FilterState::RUNNING`
- L219: `bufferStatus_ = BUFFER_STATUS_INIT_PROCESS_ALWAYS` 重置
- L222-232: 启动异常时写 HiSysEvent `FaultAudioCodecEventWrite(audioCodecFaultInfo)`

**E7. DoPause / DoFreeze 双暂停路径**
- `audio_decoder_filter.cpp L237-251`: `DoPause()` → `decoder_->Pause()` → `state_ = FilterState::PAUSED`
- L246-251: `DoFreeze()` → 当 `state_ == FilterState::RUNNING` 时 → `state_ = FilterState::FROZEN`

**E8. DoResume 恢复**
- `audio_decoder_filter.cpp L255-280`: `DoPauseAudioAlign()` 调用 `DoPause()` — Audio 对齐暂停路径
- L265-269: 恢复时 `bufferStatus_ = BUFFER_STATUS_INIT_PROCESS_ALWAYS` + `decoder_->Start()`
- L276-280: FROZEN 恢复路径

**E9. DoStop / DoFlush / DoRelease 三段停止**
- `audio_decoder_filter.cpp L289-329`: `DoStop()` → `decoder_->Stop()` → `state_ = FilterState::STOPPED`
- L306-309: `DoFlush()` → `decoder_->Flush()`
- L321-322: `DoRelease()` → `decoder_->Release()`

**E10. Configure 参数传递**
- `audio_decoder_filter.cpp L393-441`: `Configure(meta)` → `decoder_->Init(true, mime)` → `decoder_->SetCodecCallback()` → `decoder_->Configure(meta)` → `decoder_->SetAudioDecryptionConfig()`
- L397-402: MIME 类型校验 + `eventReceiver_->OnEvent(EVENT_ERROR, MSERR_UNSUPPORT_AUD_DEC_TYPE)` 错误上报
- L421: `decoder_->SetCodecCallback(mediaCodecCallback)` 设置解码回调

**E11. UpdateTrackInfoSampleFormat 采样格式自动转换**
- `audio_decoder_filter.cpp L441-479`: `UpdateTrackInfoSampleFormat(mime, meta)` — 非 RAW/APE/FLAC 格式自动降为 S16LE；bit depth > 16 时升为 S32LE
- L444: MIME 非 `AUDIO_RAW` 时设置
- L445: APE/FLAC 保持原始格式
- L459-461: `sampleFormatGetRes && AudioSampleFormatToBitDepth(sampleFormat) > 16` → S32LE
- L473-474: `hasPerRawSampleData && sampleDepth > 16` → S32LE

**E12. IsNeedProcessInput 状态机判断**
- `audio_decoder_filter.cpp L561-586`: `IsNeedProcessInput(isOutPort)` — 12 状态 BufferStatus FSM 路由，根据 bufferStatus_ 决定是否触发 ProcessInput
- L565-577: 8 个 FALSE_RETURN_V_MSG_D/D/I 分支处理 OUT_EOS_START / INPORT_AVAIL / OUTPORT_AVAIL 等状态
- L578-579: `bufferStatus_ == BUFFER_STATUS_AVAIL_NONE` 时自动分配

**E13. DoProcessInputBuffer 双端口驱动**
- `audio_decoder_filter.cpp L589-627`: `DoProcessInputBuffer(recvArg, dropFrame)` — `isOutPort = (recvArg == BUFFER_AVAILABLE_OUT_PORT)`
- L592: `lastBufferStatus = BUFFER_STATUS_INIT_PROCESS_ALWAYS`
- L593-594: `MEDIA_TRACE_DEBUG_POSTFIX` 调试 trace
- L598-599: `std::unique_lock<std::mutex>(bufferStatusMutex_, std::try_to_lock)` 尝试锁
- L607: `decoder_->ProcessInputBufferInner(isOutPort, dropFrame, bufferStatus)` — 解码器内部处理

**E14. MediaCodecCallback 回调桥接**
- `audio_decoder_filter.cpp L760-769`: `AudioDecoderCallback::OnInputBufferAvailable(index, buffer)` + `OnOutputBufferAvailable(index, buffer)` — 与 `decoder_->SetCodecCallback()` 绑定
- `audio_decoder_filter.h`: 定义 `AudioDecInputPortConsumerListener` (L112) 和 `AudioDecOutPortProducerListener` (L134)，分别监听 input/output buffer 可用事件

**E15. Filter 基类生命周期集成**
- `audio_decoder_filter.cpp L154-169`: `AudioDecoderFilter(name, type)` 构造函数 → `Filter(name, type, IS_FILTER_ASYNC)` → 析构时调用 `Filter::StopFilterTask()`
- L183-192: `Init(receiver, callback)` 初始化事件接收器和回调

**E16. SetParameter / GetOutputFormat 透传**
- `audio_decoder_filter.cpp L328-335`: `SetParameter(parameter)` → `decoder_->SetParameter(parameter)`
- `audio_decoder_filter.cpp L334-335`: `GetOutputFormat(parameter)` → `decoder_->GetOutputFormat(parameter)`

**E17. FilterState 五状态机**
- `audio_decoder_filter.cpp L209`: `state_ = FilterState::READY` (DoPrepare 后)
- L233: `state_ = FilterState::RUNNING` (DoStart 成功后) 或 `FilterState::ERROR`
- L242: `state_ = FilterState::PAUSED` (DoPause 后)
- L251: `state_ = FilterState::FROZEN` (DoFreeze 后)
- L298: `state_ = FilterState::STOPPED` (DoStop 后)

**E18. AudioDecoderFilterLinkCallback 链路回调**
- `audio_decoder_filter.cpp L73-108`: `AudioDecoderFilterLinkCallback` 继承 `FilterLinkCallback`，实现 OnLinkedResult / OnUnlinkedResult / OnUpdatedResult 三个链路回调
- L82-84: OnLinkedResult 触发 `codecFilter->OnLinkedResult(queue, meta)` 转发

---

## 关键设计模式

### 1. Filter 组合 Adapter 模式
AudioDecoderFilter 本身是 Filter 子类，但它将所有编解码核心逻辑委托给 `AudioDecoderAdapter`（decoder_）。Filter 负责管线集成（队列管理、状态机、生命周期），Adapter 负责编解码细节（MIME 路由、硬软切换、DRM 解密）。

### 2. 双端口 BufferQueue 异步驱动
async 模式下：
- inputQueue Consumer 挂载 `AudioDecInputPortConsumerListener` → 收到 buffer → 触发 `HandleInputBuffer(false)`
- outputQueue Producer 挂载 `AudioDecOutPortProducerListener` → 收到 buffer → 触发 `HandleInputBuffer(true)`
- 两个 Listener 共同驱动 `DoProcessInputBuffer`

### 3. BufferStatus 12 状态 FSM
通过 `bufferStatus_`（uint32_t 位图）与 mutex 锁，实现 IN/OUT 双端口可用性的精确跟踪，避免死锁和重复消费。

---

## 与 S212 VideoDecoderAdapter 对照

| 维度 | S212 VideoDecoderAdapter | S215 AudioDecoderFilter |
|------|--------------------------|------------------------|
| 过滤类型 | `builtin.player.videodecoderadapter` | `builtin.player.audiodecoder` |
| 内部引擎 | `VideoDecoderAdapter` (VideoCodec) | `AudioDecoderAdapter` (AudioCodec) |
| BufferQueue | AVBufferQueue 双队列 | AVBufferQueue 双队列 |
| 状态机 | FilterState 5态 + ProcessStateCode | FilterState 5态 + BufferStatus 12态 |
| 模式 | async + sync 双模式 | async 模式优先 |

---

## 总结

AudioDecoderFilter 是 MediaEngine Filter 管线中**音频解码的标准入口节点**。它通过 AutoRegisterFilter 实现自动注册，通过 AudioDecoderAdapter 组合模式支持硬软编解码切换，通过 12 状态 BufferStatus FSM 实现精确的双端口 buffer 管理，并通过 UpdateTrackInfoSampleFormat 实现采样格式的自动降级/升级。它与 S212 VideoDecoderAdapter 形成视音频对称的过滤层适配架构。