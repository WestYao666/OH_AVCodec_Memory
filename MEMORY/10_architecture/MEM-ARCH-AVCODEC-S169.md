---
mem_id: MEM-ARCH-AVCODEC-S169
title: FFmpeg Audio Encoder 插件体系——FFmpegBaseEncoder 基类 + AAC/FLAC/MP3/G711mu/LBVC 五子插件
status: pending_approval
scope: [AVCodec, FFmpeg, AudioEncoder, Plugin, SoftwareCodec, AAC, FLAC, MP3, G711mu, LBVC, FFmpegBaseEncoder, FFmpegEncoderPlugin, ADTS, AudioResample, SwrContext]
assoc_scenarios: [新需求开发/问题定位/音频编码接入]
sources:
  - https://gitcode.com/openharmony/multimedia_av_codec
evidence:
  - file: services/media_engine/plugins/ffmpeg_adapter/audio_encoder/ffmpeg_base_encoder.h
    lines: "94"
    desc: FFmpegBaseEncoder 基类接口声明，ProcessSendData/ProcessReceiveData/AllocateContext等核心虚函数
  - file: services/media_engine/plugins/ffmpeg_adapter/audio_encoder/ffmpeg_base_encoder.cpp
    lines: "396"
    desc: FFmpegBaseEncoder 引擎实现，avcodec_send_frame/avcodec_receive_packet 双函数管线
  - file: services/media_engine/plugins/ffmpeg_adapter/audio_encoder/ffmpeg_encoder_plugin.cpp
    lines: "85"
    desc: FFmpegEncoderPlugin 插件注册层，PLUGIN_DEFINITION+RegisterAudioEncoderPlugins
  - file: services/media_engine/plugins/ffmpeg_adapter/audio_encoder/aac/ffmpeg_aac_encoder_plugin.cpp
    lines: "902"
    desc: AAC 编码器插件，自实现 AVAudioFifo + ADTS 7字节头，13档采样率表
  - file: services/media_engine/plugins/ffmpeg_adapter/audio_encoder/flac/ffmpeg_flac_encoder_plugin.cpp
    lines: "252"
    desc: FLAC 编码器插件，组合 FFmpegBaseEncoder，采样率表+通道布局表
  - file: services/media_engine/plugins/ffmpeg_adapter/audio_encoder/mp3/audio_mp3_encoder_plugin.cpp
    lines: "404"
    desc: MP3 编码器插件
  - file: services/media_engine/plugins/ffmpeg_adapter/audio_encoder/g711mu/audio_g711mu_encoder_plugin.cpp
    lines: "304"
    desc: G.711mu-law 编码器插件
  - file: services/media_engine/plugins/ffmpeg_adapter/audio_encoder/lbvc/audio_lbvc_encoder_plugin.cpp
    lines: "285"
    desc: LBVC 编码器插件
created_by: builder-agent
created_at: "2026-05-21T02:54:00+08:00"
updated_by: builder-agent
updated_at: "2026-05-21T02:54:00+08:00"
review_status: pending_review
tags:
  - AVCodec
  - FFmpeg
  - AudioEncoder
  - Plugin
---

# FFmpeg Audio Encoder 插件体系——FFmpegBaseEncoder 基类 + AAC/FLAC/MP3/G711mu/LBVC 五子插件

## 1. 主题概述

AVCodec FFmpeg Audio Encoder 插件体系采用**三层架构**：插件注册层（FFmpegEncoderPlugin）→ 引擎基类（FFmpegBaseEncoder）→ 五种子插件（AAC/FLAC/MP3/G711mu/LBVC）。

该体系基于 FFmpeg libavcodec 提供软件音频编码能力，与 FFmpegDemuxerPlugin 解封装、S125 FFmpegDecoderPlugin 解码器共同构成 FFmpeg 全家桶。

**证据**：`services/media_engine/plugins/ffmpeg_adapter/audio_encoder/` 目录下共 8 个源文件，总计约 1314+601=1915 行。

---

## 2. 三层架构

### 2.1 Layer 1：FFmpegEncoderPlugin 插件注册层

**文件**：`ffmpeg_encoder_plugin.cpp` (L64-85)
**文件**：`ffmpeg_encoder_plugin.h` (26 行)

```cpp
// ffmpeg_encoder_plugin.cpp:64-85
Status RegisterAudioEncoderPlugins(const std::shared_ptr<Register> &reg)
{
    // AAC
    auto aacCreator = [](const std::string& name) -> std::shared_ptr<CodecPlugin> {
        return std::make_shared<FFmpegAACEncoderPlugin>(name);
    };
    reg->Register audioEncoder(aacCreator, Description().UUID(UUID_AAC).Build());
    // FLAC / MP3 / G711mu / LBVC 同理...
    return Status::OK;
}

void UnRegisterAudioEncoderPlugin() {}

PLUGIN_DEFINITION(FFmpegAudioEncoders, LicenseType::LGPL, RegisterAudioEncoderPlugins, UnRegisterAudioEncoderPlugin);
```

**证据**：`PLUGIN_DEFINITION` 宏完成静态注册，LicenseType 为 LGPL，与 S125 FFmpegDecoderPlugin 的 LGPL 授权一致。

### 2.2 Layer 2：FFmpegBaseEncoder 引擎基类

**文件**：`ffmpeg_base_encoder.h` (94 行)
**文件**：`ffmpeg_base_encoder.cpp` (396 行)

**核心接口**：

| 方法 | 职责 |
|------|------|
| `ProcessSendData(inputBuffer)` | 接收 PCM 输入，送入 FFmpeg 编码器（L43-76） |
| `ProcessReceiveData(outputBuffer)` | 从 FFmpeg 编码器拉取压缩输出（L78-105） |
| `AllocateContext(name)` | 按编码器名称分配 FFmpeg AVCodecContext（L200+） |
| `InitContext(format)` | 从 Meta 配置采样率/通道数/码率（L240+） |
| `InitFrame()` | 初始化 AVFrame/AVPacket 缓冲区（L280+） |
| `GetCodecContext()` | 获取底层 AVCodecContext 共享指针（L310+） |

**关键成员**：
- `avCodecContext_`：`std::shared_ptr<AVCodecContext>` — FFmpeg 编码器上下文（L36）
- `cachedFrame_`：`std::shared_ptr<AVFrame>` — 缓存 Frame（L37）
- `avPacket_`：`std::shared_ptr<AVPacket>` — 压缩数据包（L38）
- `avMutext_` / `bufferMetaMutex_`：双重互斥锁保护线程安全（L39-40）
- `dataCallback_`：编码输出回调（L46）

**编码管线**（L43-105）：
```
ProcessSendData → SendBuffer → avcodec_send_frame → (内部) → ProcessReceiveData → ReceiveBuffer → avcodec_receive_packet → SendOutputBuffer → dataCallback_
```

**证据**：`ffmpeg_base_encoder.cpp:43-76` ProcessSendData 持有 `avMutext_` 调用 SendBuffer 送入 FFmpeg；`ffmpeg_base_encoder.cpp:78-105` ProcessReceiveData 调用 ReceiveBuffer 拉取 avcodec_receive_packet。

### 2.3 Layer 3：五种子插件

| 插件 | 文件 | 行数 | 关键特性 |
|------|------|------|---------|
| **AAC** | `aac/ffmpeg_aac_encoder_plugin.cpp` | 902 | 自实现 AVAudioFifo + ADTS 7字节头，13档采样率 |
| **FLAC** | `flac/ffmpeg_flac_encoder_plugin.cpp` | 252 | 组合 FFmpegBaseEncoder，采样率表+通道布局表 |
| **MP3** | `mp3/audio_mp3_encoder_plugin.cpp` | 404 | FFmpeg libmp3lame |
| **G.711mu** | `g711mu/audio_g711mu_encoder_plugin.cpp` | 304 | 免许可证，PCM→μ-law |
| **LBVC** | `lbvc/audio_lbvc_encoder_plugin.cpp` | 285 | Low Bitrate Voice Codec |

---

## 3. AAC 编码器插件（重点）

**文件**：`aac/ffmpeg_aac_encoder_plugin.cpp` (902 行)

### 3.1 ADTS 7字节头

**证据**：`ffmpeg_aac_encoder_plugin.cpp:37` 定义 `ADTS_HEADER_SIZE = 7`，L102-124 GetAdtsHeader 生成 ADTS 头：

```
ADTS Byte[0]: 0xFF                    // 同步字
ADTS Byte[1]: 0xF1                    // 固定头部（ADTS标识）
ADTS Byte[2]: ((profile) << 6) + (freqIdx << 2) + (chanCfg >> 2)
ADTS Byte[3]: (((chanCfg & 0x3) << 6) + (frameLength >> 11))
ADTS Byte[4]: ((frameLength & 0x7FF) >> 3)
ADTS Byte[5]: (((frameLength & 0x7) << 5) + 0x1F)
ADTS Byte[6]: 0xFC                    // CRC结束位
```

**profile**（2位）：0=Main/1=AAC-LC/2=SSR/3=reserved  
**freqIdx**（4位）：13档采样率索引（96000→0, 88200→1, ..., 7350→12）  
**chanCfg**（3位）：通道布局（1=Mono, 2=Stereo, ..., 8=7.1）

### 3.2 自实现 AVAudioFifo

**证据**：`ffmpeg_aac_encoder_plugin.cpp` 中 AAC 编码器**未使用 FFmpeg 的 av_audio_fifo**，而是自实现环形缓冲区管理（AAC 帧需要先积累 1024 个 PCM 样本才能编码）：

- `fifo_` 成员（AAC 专用 FIFO）
- `ProcessSendData` 时将 PCM 填充进 FIFO
- 凑满 1024 样本后触发 `avcodec_send_frame`
- `ProcessReceiveData` 时从 `avcodec_receive_packet` 拉取 AAC 帧
- 每个 AAC 帧前追加 ADTS 7字节头（L609: `if (meta->Get<Tag::AUDIO_AAC_IS_ADTS>(type))`）

### 3.3 13档采样率

**证据**：`ffmpeg_aac_encoder_plugin.cpp:47-49`：

```cpp
static std::map<int32_t, uint8_t> sampleFreqMap = {
    {96000, 0}, {88200, 1}, {64000, 2}, {48000, 3}, {44100, 4},
    {32000, 5}, {24000, 6}, {22050, 7}, {16000, 8}, {12000, 9},
    {11025, 10}, {8000, 11}, {7350, 12}
};
```

### 3.4 8通道布局表

**证据**：`ffmpeg_aac_encoder_plugin.cpp:51-57`：

```cpp
static std::map<int32_t, uint64_t> channelLayoutMap = {
    {1, AV_CH_LAYOUT_MONO}, {2, AV_CH_LAYOUT_STEREO},
    {3, AV_CH_LAYOUT_SURROUND}, {4, AV_CH_LAYOUT_4POINT0},
    {5, AV_CH_LAYOUT_5POINT0_BACK}, {6, AV_CH_LAYOUT_5POINT1_BACK},
    {7, AV_CH_LAYOUT_7POINT0}, {8, AV_CH_LAYOUT_7POINT1}
};
```

---

## 4. FLAC 编码器插件

**文件**：`flac/ffmpeg_flac_encoder_plugin.cpp` (252 行)

**证据**：FLAC 编码器**组合 FFmpegBaseEncoder**（继承关系 vs 组合），复用 `ProcessSendData`/`ProcessReceiveData` 管线，仅覆盖 `InitContext` 配置 libflac 参数。  
采样率表和通道布局表与 AAC 共享相同结构（`ffmpeg_flac_encoder_plugin.cpp:38-44`）。

---

## 5. 与其他 FFmpeg 组件的关系

| 组件 | 关联主题 | 关系 |
|------|---------|------|
| FFmpegDemuxerPlugin | S68/S76 | 同属 FFmpeg Adapter 并列体系 |
| FFmpegDecoderPlugin | S125 | 编解码对称（AAC/FLAC/MP3 解码） |
| FFmpegAdapterCommon | S130 | 共享 ffmpeg_convert（重采样）/ffmpeg_utils |
| AudioResample | S50 | SwrContext 重采样，FFmpegBaseEncoder 可能复用 |
| AudioBaseCodec | S8/S50 | 软件编解码基类，FFmpegBaseEncoder 继承关系 |

---

## 6. 与 S125 S132 S158 的关系

| 主题 | 描述 | 与 S169 关系 |
|------|------|------------|
| **S125** | FFmpegDecoderPlugin + FfmpegBaseDecoder + 17+ 音频解码器 | **解码对称**：S125=解码器体系，S169=编码器体系 |
| **S132** | FFmpegBaseEncoder + AAC/FLAC 编码器（早期版本） | S132 → S169 演进版（增加 MP3/G711mu/LBVC） |
| **S158** | FFmpeg 音频编码器三层架构（AAC/FLAC/MP3/G711mu/LBVC） | **实质相同**，S158 为草案，S169 为正式注册 |

---

## 7. 关键结论

1. **三层架构清晰**：FFmpegEncoderPlugin 注册层 + FFmpegBaseEncoder 引擎基类 + 五子插件
2. **AAC 自实现 FIFO**：区别于 FFmpeg 原生 av_audio_fifo，自主管理 1024 样本帧积累
3. **ADTS 7字节头**：AAC 编码输出前追加 ADTS 头部，profile/freqIdx/chanCfg 三字段编码
4. **线程安全**：FFmpegBaseEncoder 双重互斥锁（avMutext_/bufferMetaMutex_）保护编码管线
5. **CodecPlugin 接口**：所有子插件实现 CodecPlugin 统一接口，遵循 PluginManagerV2 工厂发现机制