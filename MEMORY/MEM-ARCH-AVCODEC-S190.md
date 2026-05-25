# MEM-ARCH-AVCODEC-S190.md

## 状态

- **status**: draft
- **mem_id**: MEM-ARCH-AVCODEC-S190
- **subject**: FFmpeg Resample 重采样器 + AudioCaptureModule 音频采集双模块集成架构
- **scope**: AVCodec, FFmpeg, Resample, SwrContext, AudioCaptureModule, AudioCapturer, AudioSource, GetMaxAmplitude, TrackMaxAmplitude, AudioResample, AVAudioFifo
- **关联场景**: 新需求开发/音频采集接入/音频重采样/振幅监测/音频源模块
- **draft_time**: 2026-05-25T15:34:00+08:00
- **关联主题**: S125/S132/S158/S176/S119/S147/S50

---

## 主题概述

FFmpeg Resample 重采样器与 AudioCaptureModule 音频采集模块构成音频输入/处理双核心组件。Resample 基于 FFmpeg libswresample 封装 SwrContext，支持采样率/通道布局/格式三参数重采样；AudioCaptureModule 基于 AudioStandard::AudioCapturer 封装，支持 Read/Poll 双模式，并提供 GetMaxAmplitude/TrackMaxAmplitude 振幅监测功能。

---

## Evidence 列表（行号级）

### 1. Resample 重采样器（FFmpeg libswresample）

| # | 文件 | 行号 | Evidence |
|---|------|------|----------|
| E1 | `services/media_engine/plugins/ffmpeg_adapter/common/ffmpeg_convert.cpp` | L44 | `swr_alloc_set_opts2(&swrContext, &resamplePara_.channelLayout, resamplePara_.destFmt, resamplePara_.sampleRate, &resamplePara_.channelLayout, resamplePara_.srcFfFmt, resamplePara_.sampleRate, 0, nullptr)` — SwrContext 初始化六参数配置 |
| E2 | `services/media_engine/plugins/ffmpeg_adapter/common/ffmpeg_convert.cpp` | L48 | `if (swr_init(swrContext) != 0)` — SwrContext 初始化验证 |
| E3 | `services/media_engine/plugins/ffmpeg_adapter/common/ffmpeg_convert.cpp` | L53 | `swrCtx_ = std::shared_ptr<SwrContext>(swrContext, [](SwrContext *ptr) { swr_free(&ptr); })` — SwrContext RAII 智能指针管理 |
| E4 | `services/media_engine/plugins/ffmpeg_adapter/common/ffmpeg_convert.cpp` | L70-73 | `swr_alloc_set_opts2` 二次初始化（ReInit 路径） |
| E5 | `services/media_engine/plugins/ffmpeg_adapter/common/ffmpeg_convert.cpp` | L111 | `swr_convert(swrCtx_.get(), resampleChannelAddr_.data(), samples, tmpInput.data(), samples)` — swr_convert 主动重采样 |
| E6 | `services/media_engine/plugins/ffmpeg_adapter/common/ffmpeg_convert.cpp` | L187 | `swr_convert_frame(swrCtx_.get(), outputFrame, inputFrame)` — swr_convert_frame 帧级重采样 API |
| E7 | `services/media_engine/plugins/ffmpeg_adapter/common/ffmpeg_convert.cpp` | L193 | `uint32_t Resample::GetSampleOffset()` — 重采样样本偏移量查询接口 |

### 2. AudioCaptureModule 音频采集

| # | 文件 | 行号 | Evidence |
|---|------|------|----------|
| E8 | `services/media_engine/modules/source/audio_capture/audio_capture_module.cpp` | L94 | `audioCapturer_ = AudioStandard::AudioCapturer::Create(options_, appInfo)` — AudioCapturer 工厂创建 |
| E9 | `services/media_engine/modules/source/audio_capture/audio_capture_module.cpp` | L320-348 | `Status AudioCaptureModule::Read(std::shared_ptr<AVBuffer> &buffer, size_t expectedLen)` — Read(AVBuffer) 重载模式，调用 `audioCapturer_->Read(*bufData->GetAddr(), expectedLen, true)` |
| E10 | `services/media_engine/modules/source/audio_capture/audio_capture_module.cpp` | L355-371 | `Status AudioCaptureModule::Read(uint8_t *cacheAudioData, size_t expectedLen)` — Read(raw) 重载模式，直接填充内存缓冲区 |
| E11 | `services/media_engine/modules/source/audio_capture/audio_capture_module.cpp` | L348-354 | `if (isTrackMaxAmplitude) { TrackMaxAmplitude(reinterpret_cast<int16_t *>(bufData->GetAddr()), ...); }` — Read 路径自动触发 TrackMaxAmplitude 振幅监测 |
| E12 | `services/media_engine/modules/source/audio_capture/audio_capture_module.cpp` | L456-469 | `int32_t AudioCaptureModule::GetMaxAmplitude()` — GetMaxAmplitude 公开接口（L458 惰性初始化 isTrackMaxAmplitude=true） |
| E13 | `services/media_engine/modules/source/audio_capture/audio_capture_module.cpp` | L471 | `void AudioCaptureModule::TrackMaxAmplitude(int16_t *data, int32_t size)` — TrackMaxAmplitude 内部实现，逐样本峰值追踪 |

### 3. AAC 编码器 ADTS 头（Resample 下游消费者）

| # | 文件 | 行号 | Evidence |
|---|------|------|----------|
| E14 | `services/media_engine/plugins/ffmpeg_adapter/audio_encoder/aac/ffmpeg_aac_encoder_plugin.cpp` | L37 | `constexpr int32_t ADTS_HEADER_SIZE = 7` — ADTS 头固定 7 字节 |
| E15 | `services/media_engine/plugins/ffmpeg_adapter/audio_encoder/aac/ffmpeg_aac_encoder_plugin.cpp` | L102-124 | `Status FFmpegAACEncoderPlugin::GetAdtsHeader(std::string &adtsHeader, int32_t &headerSize, ...)` — ADTS 头构造，含帧长度字段 |
| E16 | `services/media_engine/plugins/ffmpeg_adapter/audio_encoder/aac/ffmpeg_aac_encoder_plugin.cpp` | L694 | `if (!(fifo_ = av_audio_fifo_alloc(...)))` — AVAudioFifo 缓冲分配 |
| E17 | `services/media_engine/plugins/ffmpeg_adapter/audio_encoder/aac/ffmpeg_aac_encoder_plugin.cpp` | L392/445/748 | `av_audio_fifo_size(fifo_)` / `av_audio_fifo_reset(fifo_)` — AVAudioFifo 状态查询与重置 |
| E18 | `services/media_engine/plugins/ffmpeg_adapter/audio_encoder/aac/ffmpeg_aac_encoder_plugin.cpp` | L297 | `GetAdtsHeader(header, headerSize, avCodecContext_, avPacket_->size)` — 编码输出前插入 ADTS 头 |

---

## Source Files

```
services/media_engine/plugins/ffmpeg_adapter/common/ffmpeg_convert.cpp      (247行)
services/media_engine/plugins/ffmpeg_adapter/common/ffmpeg_convert.h        (98行)
services/media_engine/modules/source/audio_capture/audio_capture_module.cpp  (509行)
services/media_engine/modules/source/audio_capture/audio_capture_module.h    (95行)
services/media_engine/plugins/ffmpeg_adapter/audio_encoder/aac/ffmpeg_aac_encoder_plugin.cpp (902行)
```

---

## 架构关联

```
AudioCaptureModule                    Resample (SwrContext)              AAC Encoder Plugin
┌─────────────────────────┐          ┌─────────────────────────────┐    ┌──────────────────────────┐
│ AudioStandard::         │          │ swr_alloc_set_opts2()        │    │ av_audio_fifo_alloc()     │
│ AudioCapturer::Create   │──Read()──▶│ swr_convert() /              │──▶ │ GetAdtsHeader()           │
│ (L94)                   │          │ swr_convert_frame() (L187)   │    │ (L102-124)               │
│                         │          │                              │    │                          │
│ GetMaxAmplitude() (L456)│          │ GetSampleOffset() (L193)     │    │ ADTS_HEADER_SIZE = 7 (L37)│
└─────────────────────────┘          └─────────────────────────────┘    └──────────────────────────┘
```

- **本地镜像路径**: `/home/west/av_codec_repo/`
- **draft_time**: 2026-05-25T15:34:00+08:00
- **builder**: builder-agent (subagent)