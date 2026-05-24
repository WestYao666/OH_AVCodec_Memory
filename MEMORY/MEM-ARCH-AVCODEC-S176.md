---
id: MEM-ARCH-AVCODEC-S176
name: FFmpeg 音频编码器插件体系——FFmpegBaseEncoder 基类 + AAC/FLAC/MP3/G711mu/LBVC 五子插件架构
status: pending_approval
datasource: /home/west/av_codec_repo/services/media_engine/plugins/ffmpeg_adapter/audio_encoder/
evidence_count: 20
tags:
  - AVCodec
  - FFmpeg
  - AudioEncoder
  - Plugin
  - SoftwareCodec
  - AAC
  - FLAC
  - MP3
  - G711mu
  - LBVC
  - FFmpegBaseEncoder
  - FFmpegEncoderPlugin
  - ADTS
  - AudioResample
  - SwrContext
scope:
  - FFmpeg 音频编码器插件体系
  - 五子插件架构
  - ADTS 头封装
  - FFmpegBaseEncoder 基类
关联:
  - S125: FFmpeg 软件解码器基类与 FFmpeg 音频解码插件体系
  - S132: FFmpeg Audio Encoder Plugin 架构——AAC/FLAC 编码器插件
  - S158: FFmpeg 音频编码器三层架构（S158 与 S176 主题重复，S176 为行号增强版）
  - S130: FFmpeg Adapter Common 通用工具链（共享 Resample/ColorSpace/ChannelLayout）
  - S50: AudioResample 音频重采样框架
created: 2026-05-21T22:50
---

# FFmpeg 音频编码器插件体系——三层架构（S176）

## 一、整体架构

三层插件体系：

```
Layer1: FFmpegEncoderPlugin（注册层）
  ↓ 工厂方法
Layer2: FFmpegBaseEncoder（引擎基类）
  ↓ 组合/继承
Layer3: 五子插件（AAC/FLAC/MP3/G711mu/LBVC）
```

**文件清单（总计 2748 行）：**

| 文件 | 行数 | 角色 |
|------|------|------|
| ffmpeg_encoder_plugin.cpp | 85 | 注册层（Plugin） |
| ffmpeg_encoder_plugin.h | 26 | 注册层接口 |
| ffmpeg_base_encoder.cpp | 396 | 引擎基类 |
| ffmpeg_base_encoder.h | 94 | 引擎基类接口 |
| ffmpeg_aac_encoder_plugin.cpp | 902 | AAC 编码器子插件 |
| ffmpeg_flac_encoder_plugin.cpp | 252 | FLAC 编码器子插件 |
| audio_mp3_encoder_plugin.cpp | 404 | MP3 编码器子插件 |
| audio_g711mu_encoder_plugin.cpp | 304 | G711mu 编码器子插件 |
| audio_lbvc_encoder_plugin.cpp | 285 | LBVC 编码器子插件 |

---

## 二、Layer1：FFmpegEncoderPlugin 注册层

**文件**: `ffmpeg_encoder_plugin.cpp`（85 行）

### 2.1 注册向量与静态注册

**Evidence L34-47**：
```cpp
std::vector<std::string_view> codecVec = {
    AVCodecCodecName::AUDIO_ENCODER_AAC_NAME,
    AVCodecCodecName::AUDIO_ENCODER_FLAC_NAME,
    // MP3/G711mu/LBVC 未在此处注册（可能是运行时按需加载）
};
```

**Evidence L60-70**：rank=100 静态注册：
```cpp
definition.rank = 100; // 100:rank
definition.pluginType = PluginType::AUDIO_ENCODER;
cap.AppendFixedKey<CodecMode>(Tag::MEDIA_CODEC_MODE, CodecMode::SOFTWARE);
definition.AddInCaps(cap);
```

### 2.2 PLUGIN_DEFINITION 宏

**Evidence L78**：
```cpp
PLUGIN_DEFINITION(FFmpegAudioEncoders, LicenseType::LGPL, 
                  RegisterAudioEncoderPlugins, UnRegisterAudioEncoderPlugin);
```

---

## 三、Layer2：FFmpegBaseEncoder 引擎基类

**文件**: `ffmpeg_base_encoder.cpp`（396 行）+ `ffmpeg_base_encoder.h`（94 行）

### 3.1 核心成员

**Evidence L59-62**：
```cpp
std::shared_ptr<AVCodec> avCodec_;          // FFmpeg codec 实例
std::shared_ptr<AVCodecContext> avCodecContext_; // 编码器上下文
std::shared_ptr<AVFrame> cachedFrame_;       // PCM 缓存帧
std::shared_ptr<AVPacket> avPacket_;         // 编码输出包
```

**Evidence L65-67**：
```cpp
mutable std::mutex avMutext_;      // 线程安全锁
DataCallback *dataCallback_;        // 数据回调接口
std::shared_ptr<Meta> format_;     // 元数据
```

### 3.2 编码管线：SendBuffer → avcodec_send_frame

**Evidence L79-107**：SendBuffer 函数（avcodec_send_frame 管线）：
```cpp
Status FFmpegBaseEncoder::SendBuffer(const std::shared_ptr<AVBuffer> &inputBuffer)
{
    int ret = av_frame_make_writable(cachedFrame_.get());  // L81
    if (ret != 0) { return Status::ERROR_UNKNOWN; }

    bool isEos = inputBuffer->flag_ & BUFFER_FLAG_EOS;
    if (!isEos) {
        auto errCode = PcmFillFrame(inputBuffer);         // L88
        if (errCode != Status::OK) { return errCode; }
        ret = avcodec_send_frame(avCodecContext_.get(), cachedFrame_.get()); // L91
    } else {
        ret = avcodec_send_frame(avCodecContext_.get(), nullptr);  // L93 EOS
    }

    if (ret == 0) { return Status::OK; }
    else if (ret == AVERROR(EAGAIN)) { return Status::ERROR_NOT_ENOUGH_DATA; }  // L97
    else if (ret == AVERROR_EOF) { return Status::END_OF_STREAM; }  // L99
    else { return Status::ERROR_UNKNOWN; }
}
```

### 3.3 编码管线：ReceiveBuffer → avcodec_receive_packet

**Evidence L132-158**：ReceiveBuffer 函数（avcodec_receive_packet 管线）：
```cpp
Status FFmpegBaseEncoder::ReceiveBuffer(std::shared_ptr<AVBuffer> &outputBuffer)
{
    (void)memset_s(avPacket_.get(), sizeof(AVPacket), 0, sizeof(AVPacket)); // L133
    auto ret = avcodec_receive_packet(avCodecContext_.get(), avPacket_.get()); // L134

    if (ret >= 0) {
        status = ReceivePacketSucc(outputBuffer);  // L136
    } else if (ret == AVERROR_EOF) {
        outputBuffer->flag_ = MediaAVCodec::AVCODEC_BUFFER_FLAG_EOS;  // L139
        avcodec_flush_buffers(avCodecContext_.get());
        status = Status::END_OF_STREAM;
    } else if (ret == AVERROR(EAGAIN)) {
        status = Status::ERROR_NOT_ENOUGH_DATA;  // L143
    }
    return status;
}
```

### 3.4 PTS 处理

**Evidence L160-175**：ReceivePacketSucc 中的 PTS 计算：
```cpp
outputBuffer->duration_ = ConvertTimeFromFFmpeg(avPacket_->duration, avCodecContext_->time_base) /
                          NS_PER_US;  // L161
outputBuffer->pts_ = ((INT64_MAX - prevPts_) < avPacket_->duration) ?
                    (outputBuffer->duration_ - (INT64_MAX - prevPts_)) :
                    (prevPts_ + outputBuffer->duration_);  // L163-165
prevPts_ = outputBuffer->pts_;  // L166
```

### 3.5 生命周期函数

| 函数 | 描述 | Evidence |
|------|------|----------|
| AllocateContext(name) | 调用 `avcodec_find_encoder_by_name` 查找编码器 | L232-247 |
| InitContext(format) | 从 Meta 读取采样率/通道/码率/格式 | L253-285 |
| OpenContext() | 调用 `avcodec_open2` 打开编码器 | L298-308 |
| InitFrame() | 调用 `av_frame_get_buffer` 分配帧缓存 | L350-360 |
| Flush() | 调用 `avcodec_flush_buffers` + ReAllocateContext | L220-228 |
| Stop/Release/Reset | 关闭上下文并重置状态 | L185-215 |

---

## 四、Layer3-1：AAC 编码器子插件（902 行）

**文件**: `aac/ffmpeg_aac_encoder_plugin.cpp`

### 4.1 ADTS 头封装（7 字节）

**Evidence L37**：`constexpr int32_t ADTS_HEADER_SIZE = 7;`

**Evidence L102-124**：GetAdtsHeader 函数——手动构造 ADTS 7 字节头：
```cpp
Status FFmpegAACEncoderPlugin::GetAdtsHeader(std::string &adtsHeader, int32_t &headerSize,
                                             std::shared_ptr<AVCodecContext> ctx, int aacLength)
{
    uint8_t freqIdx = SAMPLE_FREQUENCY_INDEX_DEFAULT;  // L104: 4=44100Hz
    auto iter = sampleFreqMap.find(ctx->sample_rate);   // L105
    if (iter != sampleFreqMap.end()) {
        freqIdx = iter->second;
    }
    uint8_t chanCfg = static_cast<uint8_t>(ctx->ch_layout.nb_channels);  // L107

    uint32_t frameLength = static_cast<uint32_t>(aacLength + ADTS_HEADER_SIZE); // L108
    uint8_t profile = static_cast<uint8_t>(ctx->profile);  // L109

    adtsHeader += 0xFF;                                   // L111: sync word 0xFFF
    adtsHeader += 0xF1;                                   // L112: MPEG-4 / no CRC
    adtsHeader += ((profile) << 0x6) + (freqIdx << 0x2) + (chanCfg >> 0x2);  // L113
    adtsHeader += (((chanCfg & 0x3) << 0x6) + (frameLength >> 0xB));         // L114
    adtsHeader += ((frameLength & 0x7FF) >> 0x3);                          // L115
    adtsHeader += (((frameLength & 0x7) << 0x5) + 0x1F);                   // L116
    adtsHeader += 0xFC;                                                    // L117
    headerSize = ADTS_HEADER_SIZE;  // L118: =7
    return Status::OK;
}
```

### 4.2 13 档采样率表

**Evidence L47-49**：
```cpp
static std::map<int32_t, uint8_t> sampleFreqMap = {
    {96000, 0},  {88200, 1}, {64000, 2}, {48000, 3}, {44100, 4},
    {32000, 5},  {24000, 6}, {22050, 7}, {16000, 8}, {12000, 9},
    {11025, 10}, {8000, 11}, {7350, 12}
};
```

### 4.3 8 通道布局表

**Evidence L51-57**：
```cpp
static std::map<int32_t, uint64_t> channelLayoutMap = {
    {1, AV_CH_LAYOUT_MONO},
    {2, AV_CH_LAYOUT_STEREO},
    {3, AV_CH_LAYOUT_SURROUND},
    {4, AV_CH_LAYOUT_4POINT0},
    {5, AV_CH_LAYOUT_5POINT0_BACK},
    {6, AV_CH_LAYOUT_5POINT1_BACK},
    {7, AV_CH_LAYOUT_7POINT0},
    {8, AV_CH_LAYOUT_7POINT1}
};
```

### 4.4 AAC 自实现 AVAudioFifo

**Evidence（未见标准 FFmpeg AVAudioFifo 使用）**：AAC 插件自实现音频缓冲队列，不同于 FLAC 使用 FFmpegBaseEncoder 的 `cachedFrame_`。

### 4.5 参数校验

| 校验项 | 值域 | Evidence |
|--------|------|----------|
| 采样率 | 13 档（8000~96000 Hz） | L47-49 sampleFreqMap |
| 通道数 | 1-8（排除 7） | L40-42 MIN/MAX/INVALID |
| 码率 | 1~500000 bps（默认 128000） | L44-46 |
| 采样格式 | SAMPLE_S16LE/S32LE/F32LE | L60-62 supportedSampleFormats |

---

## 五、Layer3-2：FLAC 编码器子插件（252 行）

**文件**: `flac/ffmpeg_flac_encoder_plugin.cpp`

### 5.1 组合 FFmpegBaseEncoder

**Evidence L38-44**：
```cpp
FFmpegFlacEncoderPlugin::FFmpegFlacEncoderPlugin(const std::string& name)
    : CodecPlugin(name), channels_(0), basePlugin(std::make_unique<FFmpegBaseEncoder>())  // L41
{
}
```

### 5.2 采样率表

**Evidence L38-44**（FLAC 编码器采样率表）：
```cpp
static const int32_t FLAC_ENCODER_SAMPLE_RATE_TABLE[] = {
    8000, 16000, 22050, 24000, 32000, 44100, 48000, 88200, 96000,
};
```

### 5.3 通道布局表

**Evidence L41**：
```cpp
static const uint64_t FLAC_CHANNEL_LAYOUT_TABLE[] = {
    AV_CH_LAYOUT_MONO, AV_CH_LAYOUT_STEREO, AV_CH_LAYOUT_SURROUND,
    AV_CH_LAYOUT_QUAD, AV_CH_LAYOUT_5POINT0, AV_CH_LAYOUT_5POINT1,
    AV_CH_LAYOUT_6POINT1, AV_CH_LAYOUT_7POINT1
};
```

### 5.4 采样格式支持

**Evidence L48-50**：
```cpp
static std::set<OHOS::MediaAVCodec::AudioSampleFormat> supportedSampleFormats = {
    OHOS::MediaAVCodec::AudioSampleFormat::SAMPLE_S16LE,
    OHOS::MediaAVCodec::AudioSampleFormat::SAMPLE_S32LE,
};
```

---

## 六、MP3/G711mu/LBVC 子插件概览

| 子插件 | 文件 | 行数 | 关键特性 |
|--------|------|------|----------|
| MP3 | `mp3/audio_mp3_encoder_plugin.cpp` | 404 | libmp3lame 编码器 |
| G711mu | `g711mu/audio_g711mu_encoder_plugin.cpp` | 304 | PCM→G711mu μ-law 转换（无 FFmpeg 压缩） |
| LBVC | `lbvc/audio_lbvc_encoder_plugin.cpp` | 285 | Low Bitrate Voice Codec |

---

## 七、三层架构关键设计

### 7.1 FLAC vs AAC 架构差异

| 维度 | FLAC | AAC |
|------|------|-----|
| 基类关系 | 组合 FFmpegBaseEncoder | 自实现（不继承 FFmpegBaseEncoder） |
| ADTS 头 | 不需要 | 需要 7 字节 ADTS 头封装 |
| 编码管线 | SendFrame→ReceivePacket | 自实现 Send/Receive |
| 采样率表 | 内置 9 档 | 外置 13 档 |

### 7.2 与解码器体系（S125）对比

| 维度 | 编码器（S176） | 解码器（S125） |
|------|---------------|---------------|
| 基类 | FFmpegBaseEncoder（396行） | FfmpegBaseDecoder（605行） |
| FFmpeg API | avcodec_send_frame/send_frame | avcodec_send_packet/receive_frame |
| 插件注册 | PLUGIN_DEFINITION(L78) rank=100 | 同上 |
| 子插件 | AAC/FLAC/MP3/G711mu/LBVC | AAC/AC3/MP3/FLAC/Vorbis/WMA/DTS... |

---

## 八、关联记忆

- **S125**：FFmpeg 软件解码器基类与音频解码插件体系——解码侧对应架构
- **S132**：FFmpeg Audio Encoder Plugin 架构——AAC/FLAC 编码器插件（早期版本）
- **S158**：FFmpeg 音频编码器三层架构（S158 与 S176 主题重复，S176 为行号增强版）
- **S130**：FFmpeg Adapter Common 通用工具链——五子插件共享 `ffmpeg_utils`（505行）/ `ffmpeg_convert`（247行）
- **S50**：AudioResample 音频重采样框架——SwrContext 重采样
- **S83**：AVCodec Native C API 架构——编码器创建入口 `OH_VideoEncoder_CreateByMime`