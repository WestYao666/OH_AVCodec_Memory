# MEM-ARCH-AVCODEC-S191: OHOS-Native Audio Codec Plugins vs FFmpeg Adapter Architecture

## 概述

AVCodec 音频编解码插件体系存在两条并行路径：
- **OHOS-Native 引擎路径**（`services/engine/codec/audio/`）：G711mu/Opus 零依赖自主实现，FFmpegDecoderPlugin 组合基类
- **FFmpegAdapter 路径**（`services/media_engine/plugins/ffmpeg_adapter/audio/`）：FFmpegBaseDecoder/Encoder 继承基类，dlopen libavcodec

本记忆聚焦双路径对比与 OHOS 原生插件的架构特征。

---

## 证据（行号级）

### 路径一：services/engine/codec/audio/ — OHOS-Native 引擎

#### 1. audio_g711mu_encoder_plugin.cpp（239行）— 零依赖表驱动编码

- **L120-148** `G711MuLawEncode(int16_t pcmValue)` — 纯算法无外部依赖
  - 8段线性量化编码（AUDIO_G711MU_SEG_END 8元素查找表）
  - AVCODEC_G711MU_LINEAR_BIAS=0x84，AUDIO_G711MU_SIGN_BIT=0x80
  - muLawValue = (seg << 4) | ((pcmShort >> (seg + 1)) & 0xF)
- **L41-44** 常量约束：SUPPORT_CHANNELS=1，SUPPORT_SAMPLE_RATE=8000，INPUT_BUFFER_SIZE_DEFAULT=1280，OUTPUT_BUFFER_SIZE_DEFAULT=640
- **L58-75** `CheckSampleFormat()` — 通道数/采样率/采样格式三重校验，返回AVCS_ERR_*错误码
- **L82-96** `ProcessSendData()` — 输入PCM 16bit样本遍历编码
- **L98-114** `ProcessRecieveData()` — 输出mu-law字节写入

#### 2. audio_g711mu_decoder_plugin.cpp（168行）— μ-law 解码

- **L62-74** `G711MuLawDecode(uint8_t muLawValue)` — 反量化重建PCM
  - tmp = ((muLawValue & AVCODEC_G711MU_QUANT_MASK) << 3) + G711MU_LINEAR_BIAS
  - 根据AVCODEC_G711MU_SEG_MASK移位确定段号
  - 正负号位判断：AUDIO_G711MU_SIGN_BIT=0x80
- **L36-46** `CheckInit()` — 仅支持单声道8000Hz，与编码器参数严格对应

#### 3. audio_opus_encoder_plugin.cpp（263行）— dlopen 扩展库编码

- **L49-67** 构造函数 dlopen：
  ```
  handle = dlopen("libav_codec_ext_base.z.so", 1);
  PluginCodecCreate = (OpusPluginClassCreateFun *)dlsym(handle, "OpusPluginClassEncoderCreate");
  PluginCodecCreate(&PluginCodecPtr);
  ```
  - libav_codec_ext_base.z.so — 非标准FFmpeg的OHOS扩展编解码库
- **L41-49** `OPUS_ENCODER_SAMPLE_RATE_TABLE[]` = {8000,12000,16000,24000,48000}，仅这5档
- **L52-61** `CheckSampleFormat()` — 通道数1-2/采样率5档/码率6000-510000/complexity 1-10 四重校验
- **L127-142** `ProcessSendData()` — PCM字节传入PluginCodecPtr::ProcessSendData，TIME_S=0.02（20ms帧）

#### 4. audio_opus_decoder_plugin.cpp（242行）— dlopen 扩展库解码

- **L49-62** dlopen 同编码器，OpusPluginClassDecoderCreate
- **L64-81** `ProcessSendData()` — mu-law数据传入解码器
- **L87-108** `ProcessRecieveData()` — 输出PCM数据写入outBuffer

#### 5. audio_ffmpeg_decoder_plugin.cpp（426行）— FFmpeg 组合基类

- **L35-46** 构造函数初始化：avCodec_/avCodecContext_/cachedFrame_/avPacket_/resample_/needResample_
- **L55-90** `SendBuffer()` — avcodec_send_packet，错误处理（AVERROR_EAGAIN/AVERROR_EOF/AVERROR_INVALIDDATA）
- **L92-137** `ReceiveBuffer()` — avcodec_receive_frame，PTS追踪（bufferGroupPtsDistance计算）
- **L139-160** `ConvertPlanarFrame()` — resample_->ConvertFrame 格式转换
- **L162-197** `ReceiveFrameSucc()` — 音频帧输出，needResample_时InitResample()初始化SwrContext
- **L286-330** `InitContext()` — ch_layout设置（L302-310 av_channel_layout_from_mask），sample_fmt=AV_SAMPLE_FMT_S16
- **L332-354** `OpenContext()` — avcodec_open2
- **L356-373** `InitResample()` — SwrContext初始化（ResamplePara结构体）

### 路径二：services/media_engine/plugins/ffmpeg_adapter/audio/ — FFmpegAdapter 继承基类

#### 6. audio_g711mu_encoder_plugin.cpp（304行）— FFmpegAdapter G711mu（与engine路径重复）

- **L108-136** `G711MuLawEncode()` — 与engine路径相同算法，但类名/命名空间不同（Plugins::G711mu）
- **L32-34** PLUGIN_DEFINITION宏注册：`definition.name = "builtin.audio_encoder.g711mu"`
- **L56-64** Capability设置：MimeType::AUDIO_G711MU，CodecMode::SOFTWARE，rank=100

#### 7. ffmpeg_base_encoder.cpp（396行）— FFmpegBaseEncoder 基类

- avcodec_send_frame/avcodec_receive_packet 管线
- 需要子插件实现具体编码逻辑

#### 8. AAC/FLAC/MP3/LBVC 子插件（2628行总计）

- **ffmpeg_aac_encoder_plugin.cpp** (902行) — ADTS 7字节头自实现，av_audio_fifo缓冲
- **ffmpeg_flac_encoder_plugin.cpp** (252行) — 采样率表/通道布局表
- **audio_mp3_encoder_plugin.cpp** (404行)
- **audio_lbvc_encoder_plugin.cpp** (285行)

---

## 关键发现

### 双路径架构对比

| 维度 | OHOS-Native（engine/codec/audio/） | FFmpegAdapter（ffmpeg_adapter/audio/） |
|------|-----------------------------------|----------------------------------------|
| G711mu | 零依赖表驱动，无FFmpeg | 复用FFmpeg生态，plugin注册机制 |
| Opus | dlopen libav_codec_ext_base.z.so | N/A（engine路径独有） |
| FFmpeg音频 | AudioFfmpegDecoderPlugin组合基类 | FFmpegBaseDecoder继承基类 |
| 注册方式 | 直接工厂 | PLUGIN_DEFINITION宏+AutoRegisterFilter |
| 依赖 | 无外部.so（Opus除外） | libavcodec/libavformat |
| 路径 | services/engine/codec/audio/ | services/media_engine/plugins/ffmpeg_adapter/ |

### G711mu 双路径共存

- `services/engine/codec/audio/encoder/audio_g711mu_encoder_plugin.cpp`（239行）：OHOS-Native CodecPlugin 基类，直接G711MuLawEncode算法
- `services/media_engine/plugins/ffmpeg_adapter/audio_encoder/g711mu/audio_g711mu_encoder_plugin.cpp`（304行）：FFmpegAdapter生态，PLUGIN_DEFINITION宏注册，相同算法

### Opus 扩展库路径

`audio_opus_encoder_plugin.cpp` L49-67：dlopen("libav_codec_ext_base.z.so")，非标准FFmpeg的私有扩展库，OpusPluginClassEncoderCreate函数指针创建编码器实例，与FFmpegAdapter生态完全独立

### FFmpeg AudioDecoder 组合 vs 继承

- engine路径：`AudioFfmpegDecoderPlugin` 组合FFmpeg（直接持有AVCodecContext/AVPacket/AVFrame）
- ffmpeg_adapter路径：`FFmpegBaseDecoder` 基类+继承模式，子插件只需实现特定codec

---

## 关联记忆

- S125：FFmpeg 软件解码器基类与 FFmpeg 音频解码插件体系
- S130：FFmpeg Adapter Common 通用工具链（Resample/ColorSpace/ChannelLayout）
- S50：AudioResample 音频重采样框架（SwrContext）
- S158/S169/S176：FFmpeg 音频编码器插件体系
- S8：FFmpeg 音频编解码总览

---

## 状态

- status: draft
- 生成时间: 2026-05-25T16:20
- 证据来源: 本地镜像 /home/west/av_codec_repo/services/engine/codec/audio/ + services/media_engine/plugins/ffmpeg_adapter/audio_encoder/