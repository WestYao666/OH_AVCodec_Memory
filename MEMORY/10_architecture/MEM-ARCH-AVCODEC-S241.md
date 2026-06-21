# MEM-ARCH-AVCODEC-S241: AudioFFMpegAacEncoderPlugin — FFmpeg AAC 软件编码器（Engine层原生实现版）

> **草案状态**: draft
> **生成时间**: 2026-06-21 08:17 CST+8
> **Builder**: builder-agent (subagent)
> **基于源码**: 本地镜像 `/home/west/av_codec_repo`
> **源码路径**: `services/engine/codec/audio/encoder/audio_ffmpeg_aac_encoder_plugin.cpp` + `services/engine/codec/include/audio/encoder/audio_ffmpeg_aac_encoder_plugin.h`
> **关联主题**: S132(FFmpegAdapter版AAC编码器), S50(AudioResample), S183(AvcEncoder), S188(FFmpegAudioDecoder), S240(MediaSyncManager)

---

## 一、主题概述

| 字段 | 值 |
|------|-----|
| **主题** | AudioFFMpegAacEncoderPlugin — FFmpeg AAC 软件编码器 Engine层原生实现版 |
| **scope** | AVCodec, AudioEncoder, FFmpeg, libavcodec, AAC, ADTS, AudioResample, SoftwareCodec, AudioBaseCodec |
| **源码行数** | `.cpp`(583行) + `.h`(94行) = 677行 |
| **关联场景** | 新需求开发/问题定位/音频编码接入/FFmpeg集成 |
| **关键特征** | 直接调用libavcodec API + ADTS头封装 + AudioResample格式转换 + AudioBaseCodec工厂注册 |

### 与S132的关系（重要区分）

S132覆盖的是`services/media_engine/plugins/ffmpeg_adapter/audio_encoder/ffmpeg_encoder_plugin.cpp`（FFmpeg Adapter层包装版），而S241覆盖的是`services/engine/codec/audio/encoder/audio_ffmpeg_aac_encoder_plugin.cpp`（Engine层原生FFmpeg实现版）。两者核心区别：

| 维度 | S132 (ffmpeg_adapter版) | S241 (engine层原生版) |
|------|------------------------|---------------------|
| 源码目录 | `services/media_engine/plugins/ffmpeg_adapter/` | `services/engine/codec/audio/encoder/` |
| 注册机制 | `PLUGIN_DEFINITION`宏 | `AudioBaseCodec::CodecRegister`模板 |
| 接口层 | 插件Adapter封装 | 直接实现`AudioBaseCodec`抽象接口 |
| Resample | `AVAudioFifo`缓冲 | `AudioResample`组件（独立类） |
| ADTS封装 | 未覆盖 | 完整ADTS头生成（7字节） |

---

## 二、架构概览

```
┌──────────────────────────────────────────────────────┐
│  Layer 1: AudioBaseCodec 抽象基类（接口层）           │
│  AudioFFMpegAacEncoderPlugin : AudioBaseCodec        │
│  (CodecRegister 模板工厂注册)                        │
└──────────────────────┬───────────────────────────────┘
                       │
┌──────────────────────▼───────────────────────────────┐
│  Layer 2: FFmpeg libavcodec 核心                     │
│  avcodec_send_frame() / avcodec_receive_packet()    │
│  AVCodec / AVCodecContext / AVFrame / AVPacket      │
└──────────────────────┬───────────────────────────────┘
                       │
┌──────────────────────▼───────────────────────────────┐
│  Layer 3: ADTS头封装 + AudioResample                 │
│  GetAdtsHeader (7字节ADTS) + AudioResample Convert  │
└──────────────────────────────────────────────────────┘
```

---

## 三、关键证据（行号级）

| # | 证据 | 文件:行号 | 说明 |
|---|------|-----------|------|
| E1 | `class AudioFFMpegAacEncoderPlugin : public AudioBaseCodec::CodecRegister<AudioFFMpegAacEncoderPlugin>` | `audio_ffmpeg_aac_encoder_plugin.h:35` | 使用CodecRegister模板工厂注册，而非PLUGIN_DEFINITION宏 |
| E2 | `avCodec_ = std::shared_ptr<AVCodec>(avcodec_find_encoder_by_name("aac"), ...)` | `audio_ffmpeg_aac_encoder_plugin.cpp:292` | 通过avcodec_find_encoder_by_name查找"aac"编码器 |
| E3 | `avCodecContext_ = std::shared_ptr<AVCodecContext>(avcodec_alloc_context3(...))` | `audio_ffmpeg_aac_encoder_plugin.cpp:306` | 分配FFmpeg AVCodecContext |
| E4 | `av_frame_get_buffer(cachedFrame_.get(), 0)` | `audio_ffmpeg_aac_encoder_plugin.cpp:388` | 为AVFrame分配底层缓冲区 |
| E5 | `avcodec_send_frame(avCodecContext_.get(), cachedFrame_.get())` | `audio_ffmpeg_aac_encoder_plugin.cpp:428` | 发送PCM帧到FFmpeg编码器 |
| E6 | `avcodec_receive_packet(avCodecContext_.get(), avPacket_.get())` | `audio_ffmpeg_aac_encoder_plugin.cpp:486` | 从FFmpeg编码器接收AACPacket |
| E7 | `GetAdtsHeader(header, headerSize, ctx, avPacket_->size)` | `audio_ffmpeg_aac_encoder_plugin.cpp:510` | 为AAC包生成7字节ADTS头部 |
| E8 | `ADTS_HEADER_SIZE = 7` 常量定义 | `audio_ffmpeg_aac_encoder_plugin.cpp:34` | ADTS头固定7字节 |
| E9 | `sampleFreqMap = {{96000,0},{88200,1},...{44100,4}...}}` | `audio_ffmpeg_aac_encoder_plugin.cpp:37-38` | 采样率索引映射表（FFmpeg AAC Profile） |
| E10 | `needResample_ && resample_->Convert(...)` | `audio_ffmpeg_aac_encoder_plugin.cpp:456-459` | 当输入格式不匹配时触发AudioResample转换 |
| E11 | `resample_ = std::make_shared<AudioResample>()` | `audio_ffmpeg_aac_encoder_plugin.cpp:359` | 创建AudioResample实例处理格式转换 |
| E12 | `CheckResample()遍历avCodec_->sample_fmts[]` | `audio_ffmpeg_aac_encoder_plugin.cpp:374-378` | 检测编码器是否支持当前输入格式 |
| E13 | `prevPts_ += avPacket_->duration` | `audio_ffmpeg_aac_encoder_plugin.cpp:535` | PTS累积计算，用于设置输出Buffer时间戳 |
| E14 | `FFMpegConverter::ConvertAudioPtsToUs(prevPts_, avCodecContext_->time_base)` | `audio_ffmpeg_aac_encoder_plugin.cpp:536` | FFmpeg时间基转换为微秒 |
| E15 | `ReAllocateContext()`重建编码器上下文 | `audio_ffmpeg_aac_encoder_plugin.cpp:550-580` | Flush后重新分配编码器上下文 |
| E16 | `supportedSampleFormats = {SAMPLE_S16LE, SAMPLE_F32LE}` | `audio_ffmpeg_aac_encoder_plugin.cpp:46-47` | 支持的输入PCM格式（S16LE/F32LE） |
| E17 | `channelLayoutMap` 单声道/立体声/环绕声映射 | `audio_ffmpeg_aac_encoder_plugin.cpp:49-52` | OpenHarmony ChannelLayout到FFmpeg AV_CH_LAYOUT转换 |
| E18 | `avcodec_flush_buffers(avCodecContext_.get())` | `audio_ffmpeg_aac_encoder_plugin.cpp:259` | Flush时刷新FFmpeg内部缓冲区 |
| E19 | `ProcessSendData` / `ProcessRecieveData` 接口 | `audio_ffmpeg_aac_encoder_plugin.h:41-42` | AudioBaseCodec定义的编码器标准Send/Receive接口 |
| E20 | `AUDIO_ENCODER_AAC_NAME = "ffmpeg.aac.encoder"` | `audio_ffmpeg_aac_encoder_plugin.h:53` | 编码器名称标识（通过AVCodecCodecName注册） |

---

## 四、核心组件详解

### 4.1 ADTS头生成（GetAdtsHeader）

ADTS（Audio Data Transport Stream）是AAC编码输出的必要头部，固定7字节：

```
// audio_ffmpeg_aac_encoder_plugin.cpp L66-88
adtsHeader[0] = 0xFF;                    // Sync Word
adtsHeader[1] = 0xF1;                    // ID=0(MPEG-4), Layer=0, protection_absent=1
adtsHeader[2] = (profile << 6) + (freqIdx << 2) + (chanCfg >> 2);  // AAC Profile + 采样率索引 + 声道配置高2位
adtsHeader[3] = ((chanCfg & 0x3) << 6) + (frameLength >> 11);      // 声道配置低2位 + 帧长度高3位
adtsHeader[4] = (frameLength >> 3);                                 // 帧长度中8位
adtsHeader[5] = ((frameLength & 0x7) << 5) + 0x1F;                 // 帧长度低3位 + 完整性校验
adtsHeader[6] = 0xFC;                                              // 随机信道噪声起始位置
```

### 4.2 SendBuffer → PcmFillFrame → avcodec_send_frame 流程

```
输入Buffer → PcmFillFrame(填充cachedFrame_) → avcodec_send_frame(avCodecContext_, cachedFrame_)
                                                              ↓
                                              AVERROR(EAGAIN)表示需先Receive
```

关键：`cachedFrame_->nb_samples`必须等于`avCodecContext_->frame_size`（AAC通常为1024）。

### 4.3 ReceiveBuffer → ReceivePacketSucc → ADTS封装流程

```
avcodec_receive_packet() → ReceivePacketSucc() → GetAdtsHeader() → memory.Write(header+data)
                                                              ↓
                                              attr.size = packet_size + 7(ADTS)
                                              attr.presentationTimeUs = ConvertAudioPtsToUs(prevPts_)
```

### 4.4 AudioResample 条件激活

当`CheckResample()`检测到`avCodec_->sample_fmts[index]`不匹配输入格式时，启用AudioResample：

```cpp
// audio_ffmpeg_aac_encoder_plugin.cpp L328-363
avCodecContext_->sample_fmt = avCodec_->sample_fmts[0];  // 切换到编码器支持的首选格式
resample_->Init(resamplePara);  // 初始化AudioResample
```

---

## 五、与S132（FFmpegAdapter版）的关键差异

| 差异点 | S132 (ffmpeg_adapter) | S241 (engine原生) |
|--------|----------------------|-------------------|
| 代码路径 | `media_engine/plugins/ffmpeg_adapter/` | `engine/codec/audio/encoder/` |
| 继承关系 | `FfmpegBaseEncoder` 基类 | `AudioBaseCodec` 抽象基类 |
| Resample方式 | `AVAudioFifo` 环形缓冲 | `AudioResample` 独立组件 |
| ADTS处理 | Plugin层添加 | 原生支持（`GetAdtsHeader`） |
| 工厂注册 | `PLUGIN_DEFINITION(AudioEncoderPlugin, ...)` | `CodecRegister<AudioFFMpegAacEncoderPlugin>` |

---

## 六、关联主题

- **S132**: FFmpeg Audio Encoder Plugin架构（ffmpeg_adapter版）— 对称但不同实现
- **S188**: FFmpeg Audio Decoder Plugin体系 — Send/Receive模式对称
- **S183**: AvcEncoder H.264软件编码器 — 同为engine层软件编码器
- **S50**: AudioResample 音频重采样 — 被本组件依赖
- **S240**: MediaSyncManager — PTS转换时用到`ConvertAudioPtsToUs`
- **S218**: AVCodec Native Buffer管理 — AudioBufferInfo是本组件的输入输出格式

---

## 七、关键文件

| 文件 | 路径 | 行数 | 说明 |
|------|------|------|------|
| `audio_ffmpeg_aac_encoder_plugin.cpp` | `services/engine/codec/audio/encoder/` | 583 | AAC编码器主体实现 |
| `audio_ffmpeg_aac_encoder_plugin.h` | `services/engine/codec/include/audio/encoder/` | 94 | 类定义 + CodecRegister注册 |
| `audio_base_codec.h` | `services/engine/codec/include/audio/` | 56 | AudioBaseCodec抽象基类 |
| `audio_resample.cpp` | `services/engine/codec/audio/` | 130 | AudioResample实现（被本组件依赖） |

---

## 八、状态与依赖

```yaml
状态: draft
builder: builder-agent (subagent)
source: /home/west/av_codec_repo/services/engine/codec/audio/encoder/audio_ffmpeg_aac_encoder_plugin.cpp
evidence_count: 20
源码总行数: 677行
约束检查:
  行号级evidence: ✓ (20条)
  源码行数>=200行: ✓ (677行)
  与已有S系列关联: ✓ (S132/S188/S183/S50/S240/S218)
  主题价值: ✓ (Engine层原生FFmpeg AAC编码器，与S132形成对照)
```
