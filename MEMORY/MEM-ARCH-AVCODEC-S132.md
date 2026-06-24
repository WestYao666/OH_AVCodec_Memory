# MEM-ARCH-AVCODEC-S132

> **记忆工厂草案** | Builder Agent | 2026-06-25T01:55+08:00  
> **主题**: FFmpeg Audio Encoder Plugin 架构——FFmpegBaseEncoder 基类 + AAC/FLAC 编码器插件体系  
> **状态**: pending_approval  
> **关联**: S125/S8/S50/S60/S130/S158/S169/S184  
> **代码镜像**: /home/west/av_codec_repo

---

## 1 架构概览

FFmpeg 音频编码器插件体系位于 `services/media_engine/plugins/ffmpeg_adapter/audio_encoder/`，采用三层架构：

```
注册层: ffmpeg_encoder_plugin.cpp (CodecPluginDef)
    └── ffmpeg_base_encoder.cpp (FFmpegBaseEncoder 引擎基类)
            └── 子插件: AAC(自实现) / FLAC(组合) / MP3(自实现) / G711mu(自实现) / LBVC(自实现)
```

**五种编码器对比**：

| 编码器 | 基类复用 | ADTS/封装 | 重采样 | 代码量 |
|--------|---------|-----------|--------|--------|
| AAC | 否（自实现） | ADTS 7字节头 | SwrContext | 902+159行 |
| FLAC | FFmpegBaseEncoder | 原生FLAC | 否 | 252行 |
| MP3 | 否（自实现） | 无 | 否 | 404行 |
| G711mu | 否（自实现） | 无 | 否 | 304行 |
| LBVC | 否（自实现） | LBVC封装 | 否 | 285行 |

---

## 2 核心组件

### 2.1 FFmpegBaseEncoder 引擎基类

**文件**: `ffmpeg_adapter/audio_encoder/ffmpeg_base_encoder.h` (94行) + `ffmpeg_base_encoder.cpp` (396行)

FFmpegBaseEncoder 是所有 FFmpeg 音频编码器的通用引擎基类，封装 libavcodec 编码管线。

**关键成员**：

| 成员 | 类型 | 说明 |
|------|------|------|
| `avCodec_` | `shared_ptr<AVCodec>` | FFmpeg codec 实例 |
| `avCodecContext_` | `shared_ptr<AVCodecContext>` | codec 上下文 |
| `cachedFrame_` | `shared_ptr<AVFrame>` | 输入 PCM 缓存帧 |
| `avPacket_` | `shared_ptr<AVPacket>` | 输出压缩包 |
| `avMutext_` | `mutex` | 线程安全锁 |
| `dataCallback_` | `DataCallback*` | 数据回调接口 |

**编码管线关键步骤**：

1. `ProcessSendData()` → `SendBuffer()` → `avcodec_send_frame()` (L113)
2. `ProcessReceiveData()` → `ReceiveBuffer()` → `avcodec_receive_packet()` (L149)
3. `AllocateContext()` → `avcodec_alloc_context3()` (L261)
4. `OpenContext()` → `avcodec_open2()` (L312)

**证据**：
- E1: ffmpeg_base_encoder.h L1-L94 FFmpegBaseEncoder 类定义，ProcessSendData/ProcessReceiveData 接口
- E2: ffmpeg_base_encoder.cpp L113 `avcodec_send_frame(avCodecContext_.get(), cachedFrame_.get())`
- E3: ffmpeg_base_encoder.cpp L149 `avcodec_receive_packet(avCodecContext_.get(), avPacket_.get())`
- E4: ffmpeg_base_encoder.cpp L261 `avcodec_alloc_context3(avCodec_.get())`
- E5: ffmpeg_base_encoder.cpp L312 `avcodec_open2(avCodecContext_.get(), avCodec_.get(), nullptr)`
- E6: ffmpeg_base_encoder.cpp L94-L134 SendBuffer 完整逻辑，含 AVERROR(EAGAIN)/AVERROR_EOF 错误处理

### 2.2 注册层 ffmpeg_encoder_plugin

**文件**: `ffmpeg_adapter/audio_encoder/ffmpeg_encoder_plugin.h` (26行) + `ffmpeg_encoder_plugin.cpp` (85行)

通过 `CodecPluginDef::SetCreator` 静态注册 AAC 和 FLAC 两种编码器。

**证据**：
- E7: ffmpeg_encoder_plugin.cpp L44-45 `std::vector<std::string_view> codecVec = { AVCodecCodecName::AUDIO_ENCODER_AAC_NAME, AVCodecCodecName::AUDIO_ENCODER_FLAC_NAME }`
- E8: ffmpeg_encoder_plugin.cpp L46-60 SetDefinition 分发函数，AAC(L47-54)/FLAC(L56-60) 各自 SetCreator

### 2.3 AAC 编码器插件 FFmpegAACEncoderPlugin

**文件**: `ffmpeg_adapter/audio_encoder/aac/ffmpeg_aac_encoder_plugin.h` (159行) + `ffmpeg_aac_encoder_plugin.cpp` (902行)

AAC 是唯一自实现完整编码管线的插件（不复用 FFmpegBaseEncoder），包含 ADTS 头生成和 SwrContext 重采样。

**关键结构**：

| 成员 | 类型 | 说明 |
|------|------|------|
| `fifo_` | `AVAudioFifo*` | FFmpeg 音频帧队列缓冲 |
| `resample_` | `shared_ptr<Ffmpeg::Resample>` | 重采样器 |
| `srcFmt_` | `AVSampleFormat` | 源采样格式 |
| `ptsMode_` | `AudioEncodePtsMode` | PTS 编码模式 |

**ADTS 7字节头格式**（L37: `constexpr int32_t ADTS_HEADER_SIZE = 7`）：

```
Byte[0-1]: 0xFFF (sync word)
Byte[2]:   (protection_absent << 7) | (profile << 5) | (freqIdx << 2) | (chanCfg >> 2)
Byte[3-4]: ((chanCfg & 0x3) << 6) | (frameLength >> 11)
Byte[5]:   (frameLength & 0x7FF) >> 3
Byte[6]:   ((frameLength & 0x7) << 5) | 0x1F | 0xFC (final byte)
```

**重采样触发条件**（CheckResample, L585-590）：
- 当输入采样格式不在 codec 支持的 sample_fmts 列表中时触发
- ResamplePara: channels/sampleRate/channelLayout/srcFmt/destFmt

**证据**：
- E9: ffmpeg_aac_encoder_plugin.cpp L37 `constexpr int32_t ADTS_HEADER_SIZE = 7`
- E10: ffmpeg_aac_encoder_plugin.cpp L102-119 GetAdtsHeader 生成 ADTS 7字节头
- E11: ffmpeg_aac_encoder_plugin.cpp L116 `av_audio_fifo_alloc(L694)` 分配 FIFO 缓冲
- E12: ffmpeg_aac_encoder_plugin.cpp L562-572 ResamplePara 构建与 Ffmpeg::Resample 初始化
- E13: ffmpeg_aac_encoder_plugin.cpp L585-590 CheckResample 判断是否需要重采样
- E14: ffmpeg_aac_encoder_plugin.cpp L609 `AUDIO_AAC_IS_ADTS` ADTS 模式判断
- E15: ffmpeg_aac_encoder_plugin.cpp L694-700 `av_audio_fifo_alloc` FIFO 创建
- E16: ffmpeg_aac_encoder_plugin.cpp L701-735 SendEncoder → PushInFifo → FIFO 填充流程

### 2.4 FLAC 编码器插件 FFmpegFlacEncoderPlugin

**文件**: `ffmpeg_adapter/audio_encoder/flac/ffmpeg_flac_encoder_plugin.h` + `ffmpeg_flac_encoder_plugin.cpp` (252行)

FLAC 采用组合模式，内部持有 `basePlugin`（FFmpegBaseEncoder 实例）。

**证据**：
- E17: ffmpeg_flac_encoder_plugin.cpp L55 `: CodecPlugin(name), basePlugin(std::make_unique<FFmpegBaseEncoder>())` 构造函数组合 FFmpegBaseEncoder
- E18: ffmpeg_flac_encoder_plugin.cpp L161 `basePlugin->AllocateContext("flac")` 初始化编码器
- E19: ffmpeg_flac_encoder_plugin.cpp L214-221 QueueInputBuffer/QueueOutputBuffer 委托 FFmpegBaseEncoder 处理

### 2.5 MP3/G711mu/LBVC 编码器

均为自实现插件，直接继承 CodecPlugin，不复用 FFmpegBaseEncoder：

- MP3: `audio_mp3_encoder_plugin.h/cpp` (404行) — 自实现 lame 编码管线
- G711mu: `audio_g711mu_encoder_plugin.h/cpp` (304行) — G.711 mu-law 压扩
- LBVC: `audio_lbvc_encoder_plugin.h/cpp` (285行) — LBVC 私有格式

### 2.6 Resample 重采样器

**文件**: `ffmpeg_adapter/common/ffmpeg_convert.h` (L42-86) + `ffmpeg_convert.cpp` (247行)

Resample 封装 libswresample 的 SwrContext：

**ResamplePara 六参数**：
```cpp
struct ResamplePara {
    uint32_t channels;           // 通道数
    uint32_t sampleRate;         // 采样率
    uint32_t bitsPerSample;      // 位深
    AVChannelLayout channelLayout; // 通道布局
    AVSampleFormat srcFfFmt;     // 源格式
    uint32_t destSamplesPerFrame;// 目标每帧采样数
    AVSampleFormat destFmt;       // 目标格式
};
```

**核心方法**：
- `Init()` / `InitSwrContext()` — 初始化 SwrContext
- `Convert()` — Buffer 级转换
- `ConvertFrame()` — AVFrame 级转换

**证据**：
- E20: ffmpeg_convert.h L42-51 ResamplePara 六参数结构体
- E21: ffmpeg_convert.h L69 `std::shared_ptr<SwrContext> swrCtx_` SwrContext 成员

---

## 3 数据流

### AAC 编码器数据流

```
QueueInputBuffer
  → CheckResample (是否需要重采样)
  → PushInFifo (PCM 入 FIFO)
  → SendEncoder
      → PcmFillFrame (从 FIFO 取数据填充 cachedFrame_)
      → avcodec_send_frame()
  → ReceiveBuffer
      → avcodec_receive_packet()
      → GetAdtsHeader (生成 7 字节 ADTS 头)
      → Write(ADTS + packet) → OutputBuffer
```

### FLAC 编码器数据流

```
QueueInputBuffer → basePlugin->ProcessSendData → avcodec_send_frame
QueueOutputBuffer → basePlugin->ProcessReceiveData → avcodec_receive_packet → OutputBuffer
```

---

## 4 与其他主题的关联

| 关联主题 | 关系 |
|---------|------|
| S125 | FFmpeg 解码器基类 FfmpegBaseDecoder，与 S132 对称 |
| S8 | FFmpeg 音频插件总览 |
| S50 | AudioResample（基于 libswresample） |
| S60 | AAC 音频编解码 FFmpeg 插件 |
| S130 | FFmpegAdapterCommon（共享 Resample/ColorSpace/ChannelLayout） |
| S158/S169 | FFmpeg 音频编码器三层架构（与本主题内容重叠） |
