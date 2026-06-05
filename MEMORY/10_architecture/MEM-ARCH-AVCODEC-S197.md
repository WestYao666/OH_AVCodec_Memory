# MEM-ARCH-AVCODEC-S197 · 音频编解码 Adapter 层架构

**status:** draft  
**version:** 0.1  
**author:** builder-agent  
**created:** 2026-06-05  
**source:** https://gitcode.com/openharmony/multimedia_av_codec + local repo

---

## 主题

**AudioCodec Adapter 层**（`AudioDecoderAdapter` / `AudioEncoderFilter` / `AudioSinkFilter`）在 Pipeline Filter 架构中的定位与生命周期管理。

---

## 一、Adapter 定位：Filter 与 MediaCodec Core 的桥接层

```
App/Framework
    └─ Pipeline (Filter Graph)
           └─ AudioDecoderFilter  ← filter (Filter 框架侧)
                  └─ AudioDecoderAdapter  ← adapter (封装 MediaAVCodec::AudioCodec Core)
                         └─ MediaAVCodec::AudioCodec  ← 实际编解码引擎（AudioCodecFactory 创建）
```

**证据：**
- `audio_decoder_filter.cpp:189`：`decoder_ = std::make_shared<AudioDecoderAdapter>()` — Filter 层持有 Adapter 实例
- `audio_decoder_adapter.cpp:44-53`：Adapter 通过 `AudioCodecFactory::CreateByMime(name, false)` 或 `CreateByName(name)` 创建真正的 `audiocodec_`
- `audio_encoder_filter.cpp:101-103`：`mediaCodec_ = std::make_shared<MediaCodec>(); mediaCodec_->Init(codecMimeType_, true)` — Encoder 侧直接持有 MediaCodec，暂无独立 Adapter 封装

---

## 二、AudioDecoderAdapter 接口设计（239 行 CPP）

Adapter 暴露 18 个方法，全部透传给内部 `audiocodec_`：

| 方法 | 行号 | 职责 |
|------|------|------|
| `Init(isMimeType, name)` | 44-53 | 通过 `AudioCodecFactory` 创建 `audiocodec_` 实例 |
| `Configure(parameter)` | 56-68 | 配置参数；返回 `ERROR_UNSUPPORTED_FORMAT` 当 `AVCS_ERR_INVALID_VAL` |
| `SetParameter(parameter)` | 70-76 | 动态更新参数 |
| `Prepare()` | 79-86 | 准备解码器，`isRunning_ = false` |
| `Start()` | 90-105 | 启动，**带 50ms 启动超时警告**（`AUDIO_DECODER_START_WARNING_MS`） |
| `Stop()` | 108-115 | 停止，`isRunning_ = false` |
| `Flush()` | 119-127 | 刷新，`isRunning_ = false` |
| `Reset()` | 130-139 | 重置，`isRunning_ = false` |
| `Release()` | 141-148 | 释放资源 |
| `SetOutputBufferQueue()` | 152-158 | 设置输出 Buffer 队列 |
| `GetInputBufferQueue()` | 161-165 | 获取输入队列 Producer |
| `GetInputBufferQueueConsumer()` | 168-170 | 获取输入队列 Consumer |
| `GetOutputBufferQueueProducer()` | 173-175 | 获取输出队列 Producer |
| `ProcessInputBufferInner()` | 178-181 | 触发输入 Buffer 处理 |
| `GetOutputFormat()` | 184-188 | 获取输出格式 |
| `ChangePlugin()` | 191-197 | 动态更换插件（MIME/Encoder 标志） |
| `SetDumpInfo()` | 199-201 | DFX 诊断信息注入 |
| `OnDumpInfo(fd)` | 205-218 | 输出队列状态（输入/输出队列大小） |
| `NotifyEos()` | 220-223 | 通知解码器 EOS |
| `SetCodecCallback()` | 227-229 | 设置编解码回调 |
| `SetAudioDecryptionConfig()` | 233-237 | DRM 解密配置 |

**关键发现：**
- `audio_decoder_adapter.cpp:24`：`LABEL = {LOG_CORE, LOG_DOMAIN_SYSTEM_PLAYER, "AudioDecoderAdapter"}` — 日志域为 `SYSTEM_PLAYER`，不是 `RECORDER`
- `audio_decoder_adapter.cpp:56-68`：Configure 错误时返回 `Status::ERROR_UNSUPPORTED_FORMAT`，而非通用的 `ERROR_INVALID_STATE`
- `audio_decoder_adapter.cpp:90-105`：Start 带 `ScopedTimer`，超时 50ms 触发告警

---

## 三、AudioEncoderFilter 的双重模式（转码 vs 录制）

**证据：**
- `audio_encoder_filter.cpp:55-68` 构造函数：`isTranscoderMode_` 标志决定是否启用转码模式
- `audio_encoder_filter.cpp:101-103`：`mediaCodec_ = std::make_shared<MediaCodec>()` — 与 Decoder 不同，Encoder 直接持有 MediaCodec，**没有独立 Adapter 封装**
- `audio_encoder_filter.cpp:270-350`：`UpdateParameterToConfigure` — 转码模式下对输入 PCM 参数（采样率、声道、码率）做自动适配，调用 `FindClosestBitrate`、`FindClosestSampleRate`、`AdjustChannelCount` 等工具函数
- `audio_encoder_filter.cpp:320-340`：MP3/AAC 格式最大声道数限制为 2；AMR 格式强制单声道

**格式配置表（静态常量）：**
- `audio_encoder_filter.cpp:37-77`：定义了 `MP3_FORMAT_CONFIG`、`AAC_FORMAT_CONFIG`、`RAW_FORMAT_CONFIG`、`AMR_NB_FORMAT_CONFIG`、`AMR_WB_FORMAT_CONFIG` 五种格式的码率-采样率映射和最大声道数

---

## 四、AudioSinkFilter：FILTERTYPE_ASINK 的生命周期

**证据：**
- `audio_sink_filter.cpp:37`：`AutoRegisterFilter<AudioSinkFilter>("builtin.player.audiosink", FilterType::FILTERTYPE_ASINK, ...)` — 注册名为 `builtin.player.audiosink`
- `audio_sink_filter.cpp:59-68`：构造函数读取两个 debug 参数控制回调模式和合并模式：`debug.media_service.audio.audiosink_callback`、`debug.media_service.audio.audiosink_processinput_merged`
- `audio_sink_filter.cpp:67`：`audioSink_ = std::make_shared<AudioSink>(isRenderCallbackMode, isProcessInputMerged)` — 内部持有 `AudioSink`
- `audio_sink_filter.cpp:144`：`onLinkedResultCallback_->OnLinkedResult(audioSink_->GetBufferQueueProducer(), trackMeta_)` — Link 时返回 AudioSink 的 BufferQueue

---

## 五、Filter 类型速查

| Filter | 类型常量 | 行号 | 备注 |
|--------|----------|------|------|
| `AudioDecoderFilter` | `FILTERTYPE_ADEC` | 198 | 使用 `AudioDecoderAdapter` |
| `AudioEncoderFilter` | `FILTERTYPE_AENC` | 98 | 直接持有 `MediaCodec` |
| `AudioCaptureFilter` | `AUDIO_CAPTURE` | 41 | 录制侧音频采集 |
| `AudioSinkFilter` | `FILTERTYPE_ASINK` | 37 | 播放侧音频输出 |

---

## 六、生命周期状态机对比

```
AudioDecoderAdapter          AudioEncoderFilter
─────────────────────────    ─────────────────────────────────
Init → Configure → Prepare → Start → (Stop|Flush|Reset|Release)
                            ↑
                   转码模式额外：
                   UpdateParameterToConfigure（参数自适应）
                   ProcessingThreadFunc（独立线程）
                   channelConverter_（声道转换）
```

---

## 七、DFX 能力

| 组件 | DFX 机制 | 证据 |
|------|----------|------|
| AudioDecoderAdapter | `SetDumpInfo` + `OnDumpInfo` 输出队列大小 | `audio_decoder_adapter.cpp:199-218` |
| AudioDecoderAdapter | 启动超时计时器（50ms） | `audio_decoder_adapter.cpp:99` |
| AudioEncoderFilter | `SetFaultEvent` → `FaultAudioCodecEventWrite` | `audio_encoder_filter.cpp:340-350` |

---

## 八、架构缺陷/观察

1. **Adapter 不对称**：AudioDecoder 有专用 `AudioDecoderAdapter`，但 AudioEncoder 直接使用 MediaCodec（无 Adapter 层），导致 Filter 层接口不一致
2. **日志域混用**：AudioDecoderAdapter 使用 `LOG_DOMAIN_SYSTEM_PLAYER`，AudioEncoderFilter 使用 `LOG_DOMAIN_RECORDER`，在统一日志追踪时需注意
3. **Start 超时阈值硬编码**：`AUDIO_DECODER_START_WARNING_MS = 50` 写死在源码，无配置项

---

## 参考文件

- `services/media_engine/filters/audio_decoder_adapter.cpp` (2025 Huawei)
- `services/media_engine/filters/audio_decoder_filter.cpp`
- `services/media_engine/filters/audio_encoder_filter.cpp`
- `services/media_engine/filters/audio_sink_filter.cpp`
- `services/media_engine/filters/audio_capture_filter.cpp`
- `https://gitcode.com/openharmony/multimedia_av_codec/blob/master/services/media_engine/filters/audio_decoder_adapter.cpp`

---

## 待审批

请确认以上内容是否准确，approve 后正式 commit。