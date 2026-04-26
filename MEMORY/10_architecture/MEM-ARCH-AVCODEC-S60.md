---
status: draft
mem_id: MEM-ARCH-AVCODEC-S60
title: "AAC 音频编解码 FFmpeg 插件——AudioFFMpegAacEncoder/DecoderPlugin 双插件与 ADTS/RESAMPLE 四通道"
scope:
  - AVCodec
  - AudioCodec
  - AAC
  - FFmpeg
  - ADTS
  - AudioResample
  - AudioBaseCodec
  - Plugin
  - AudioEncoder
  - AudioDecoder
created_by: builder-agent
created_at: "2026-04-27T01:51:00+08:00"
related:
  - S8: FFmpeg 音频插件架构（上层总览）
  - S50: AudioResample（音频重采样框架，encoder 中 needResample_ 调用）
  - S24: AudioEncoderFilter（Filter 层封装）
  - S35: AudioDecoderFilter（Filter 层封装）
  - S18: AudioCodecServer（音频服务架构）
evidence_count: 20+
pipeline_position: "AudioEncoderFilter(S24) → AudioCodecAdapter → AudioCodec → AudioFFMpegAacEncoderPlugin(S60)"
---

# AAC 音频编解码 FFmpeg 插件

## 1. 架构定位

AudioFFMpegAacEncoderPlugin 和 AudioFFMpegAacDecoderPlugin 是 OH_AVCodec 中基于 FFmpeg libavcodec 的 AAC 编解码插件实现，位于 services/engine/codec/audio/encoder/ 和 decoder/ 目录。它们通过 AudioBaseCodec::CodecRegister 注册机制接入 CodecBase 引擎。

**调用链**：
```
AudioEncoderFilter(S24) / AudioDecoderFilter(S35)
  → AudioCodecAdapter
    → AudioCodec (AudioCodecServer S18)
      → AudioFFMpegAacEncoderPlugin (S60本主题)
      → AudioFFMpegAacDecoderPlugin (S60本主题)
        → libavcodec (FFmpeg)
```

## 2. 插件注册名

| 插件 | 注册名（AVCodecCodecName） | 内部 FFmpeg codec 名 |
|------|--------------------------|---------------------|
| AudioFFMpegAacEncoderPlugin | `OH.Media.Codec.Encoder.Audio.AAC` | `"aac"` |
| AudioFFMpegAacDecoderPlugin | `OH.Media.Codec.Decoder.Audio.AAC` | `"aac"` 或 `"aac_latm"` |

```cpp
// avcodec_codec_name.h:27
static constexpr std::string_view AUDIO_DECODER_AAC_NAME = "OH.Media.Codec.Decoder.Audio.AAC";
// avcodec_codec_name.h:90
static constexpr std::string_view AUDIO_ENCODER_AAC_NAME = "OH.Media.Codec.Encoder.Audio.AAC";
```

## 3. AudioBaseCodec 基类

所有音频编解码插件继承自 AudioBaseCodec（抽象基类）：

```cpp
// audio_base_codec.h
class AudioBaseCodec : public AVCodecBaseFactory<AudioBaseCodec, std::string>, public NoCopyable {
public:
    virtual int32_t Init(const Media::Format &format) = 0;
    virtual int32_t ProcessSendData(const std::shared_ptr<AudioBufferInfo> &inputBuffer) = 0;
    virtual int32_t ProcessRecieveData(std::shared_ptr<AudioBufferInfo> &outBuffer) = 0;
    virtual int32_t Reset() = 0;
    virtual int32_t Release() = 0;
    virtual int32_t Flush() = 0;
    virtual int32_t GetInputBufferSize() const = 0;
    virtual int32_t GetOutputBufferSize() const = 0;
    virtual Media::Format GetFormat() const noexcept = 0;
    virtual std::string_view GetCodecType() const noexcept = 0;
};
```

AudioFFMpegAacEncoderPlugin 使用 CRTP 模板注册：
```cpp
// audio_ffmpeg_aac_encoder_plugin.h
class AudioFFMpegAacEncoderPlugin : public AudioBaseCodec::CodecRegister<AudioFFMpegAacEncoderPlugin>
```

## 4. AAC 编码器（AudioFFMpegAacEncoderPlugin）

### 4.1 核心成员

```cpp
// audio_ffmpeg_aac_encoder_plugin.h:38-54
private:
    Format format_;
    int32_t maxInputSize_;
    std::shared_ptr<AVCodec> avCodec_;           // FFmpeg codec 查找结果
    std::shared_ptr<AVCodecContext> avCodecContext_; // FFmpeg 上下文
    std::shared_ptr<AVFrame> cachedFrame_;        // 编码输入帧缓存
    std::shared_ptr<AVPacket> avPacket_;          // 编码输出包
    mutable std::mutex avMutext_;                 // 线程安全锁
    int64_t prevPts_;                            // 前一帧 PTS
    std::shared_ptr<AudioResample> resample_;    // 采样率转换器
    bool needResample_;                          // 是否需要重采样
    AVSampleFormat srcFmt_;                      // 源采样格式
    uint64_t srcLayout_;                         // 源通道布局
    bool codecContextValid_;                     // 上下文是否已打开
```

### 4.2 ADTS 头生成

AAC 编码输出需要添加 ADTS（Audio Data Transport Stream）头（7字节）：

```cpp
// audio_ffmpeg_aac_encoder_plugin.cpp:84-99
int32_t AudioFFMpegAacEncoderPlugin::GetAdtsHeader(
    std::string &adtsHeader, int32_t &headerSize,
    std::shared_ptr<AVCodecContext> ctx, int aacLength)
{
    // sampleFreqMap: 96000→0, 88200→1, 48000→3, 44100→4, ...
    uint8_t freqIdx = sampleFreqMap[ctx->sample_rate];  // 4: 44100Hz 默认
    uint8_t chanCfg = ctx->ch_layout.nb_channels;
    uint32_t frameLength = aacLength + ADTS_HEADER_SIZE; // 7字节头
    uint8_t profile = ctx->profile;  // AAC profile
    adtsHeader += 0xFF;  // 同步字
    adtsHeader += 0xF1;  // ADTS 固定头
    adtsHeader += (profile << 0x6) + (freqIdx << 0x2) + (chanCfg >> 0x2);
    adtsHeader += (((chanCfg & 0x3) << 0x6) + (frameLength >> 0xB));
    adtsHeader += ((frameLength & 0x7FF) >> 0x3);
    adtsHeader += (((frameLength & 0x7) << 0x5) + 0x1F);
    adtsHeader += 0xFC;  // CRC
}
```

### 4.3 采样率支持（13 档）

```cpp
// audio_ffmpeg_aac_encoder_plugin.cpp:30-32
static std::map<int32_t, uint8_t> sampleFreqMap = {
    {96000, 0}, {88200, 1}, {64000, 2}, {48000, 3}, {44100, 4},
    {32000, 5}, {24000, 6}, {22050, 7}, {16000, 8}, {12000, 9},
    {11025, 10}, {8000, 11}, {7350, 12}
};
```

### 4.4 通道布局支持（1-8 通道）

```cpp
// audio_ffmpeg_aac_encoder_plugin.cpp:37-40
static std::map<int32_t, uint64_t> channelLayoutMap = {
    {1, AV_CH_LAYOUT_MONO}, {2, AV_CH_LAYOUT_STEREO},
    {3, AV_CH_LAYOUT_SURROUND}, {4, AV_CH_LAYOUT_4POINT0},
    {5, AV_CH_LAYOUT_5POINT0_BACK}, {6, AV_CH_LAYOUT_5POINT1_BACK},
    {7, AV_CH_LAYOUT_7POINT0}, {8, AV_CH_LAYOUT_7POINT1}
};
// MIN_CHANNELS=1, MAX_CHANNELS=8, INVALID_CHANNELS=7（避免 Ambisonics 混淆）
```

### 4.5 编码流程

```cpp
// audio_ffmpeg_aac_encoder_plugin.cpp:295-304
int32_t OpenContext() {
    auto res = avcodec_open2(avCodecContext_.get(), avCodec_.get(), nullptr);
    codecContextValid_ = true;
    if (needResample_) {
        ResamplePara resamplePara = {
            .channels = avCodecContext_->ch_layout.nb_channels,
            .sampleRate = avCodecContext_->sample_rate,
            .srcFmt = srcFmt_,
            .destFmt = avCodecContext_->sample_fmt,
            .destSamplesPerFrame = avCodecContext_->frame_size,
        };
        resample_ = std::make_shared<AudioResample>();
        resample_->Init(resamplePara);
    }
}

// SendBuffer: avcodec_send_frame()
// ReceiveBuffer: avcodec_receive_packet() + ADTS header prepended
```

## 5. AAC 解码器（AudioFFMpegAacDecoderPlugin）

### 5.1 核心成员（组合模式）

```cpp
// audio_ffmpeg_aac_decoder_plugin.h:28-32
private:
    std::unique_ptr<AudioFfmpegDecoderPlugin> basePlugin;  // 组合 AudioFfmpegDecoderPlugin
    std::string aacName_;    // "aac" 或 "aac_latm"
    int32_t channels_;
```

与编码器不同，decoder 使用**组合**而非继承：AudioFFMpegAacDecoderPlugin 内部持有一个 AudioFfmpegDecoderPlugin 实例，所有操作委托给它。

### 5.2 ADTS 判断

```cpp
// audio_ffmpeg_aac_decoder_plugin.cpp:59-73
bool AudioFFMpegAacDecoderPlugin::CheckAdts(const Format &format) {
    int type;
    format.GetIntValue(MediaDescriptionKey::MD_KEY_AAC_IS_ADTS, type);
    // type == 1: ADTS 格式（"aac"）
    // type == 0: LATM 格式（"aac_latm"）
    aacName_ = (type == 1 ? "aac" : "aac_latm");
    return true;
}
```

### 5.3 解码器支持参数

| 参数 | 支持范围 |
|------|---------|
| 采样率 | 7350, 8000, 11025, 12000, 16000, 22050, 24000, 32000, 44100, 48000, 64000, 88200, 96000 Hz |
| 通道数 | 1-8（MIN=1, MAX=8）|
| 输出格式 | S16LE, F32LE |
| 容器格式 | ADTS（"aac"）/ LATM（"aac_latm"）|

## 6. AudioResample 集成（编码器侧）

当输入 PCM 格式与 FFmpeg AAC 编码器期望格式不匹配时，编码器启用重采样：

```cpp
// audio_ffmpeg_aac_encoder_plugin.cpp:349-360
bool CheckResample() const {
    for (size_t index = 0; avCodec_->sample_fmts[index] != AV_SAMPLE_FMT_NONE; ++index) {
        if (avCodec_->sample_fmts[index] == srcFmt_) return false;
    }
    return true;  // 需要重采样
}

// audio_ffmpeg_aac_encoder_plugin.cpp:453-460
int32_t PcmFillFrame(...) {
    if (needResample_ && resample_ != nullptr) {
        resample_->Convert(srcBuffer, srcBufferSize, destBuffer, destBufferSize);
    }
}
```

## 7. 与 S8/S50 的关系

| 维度 | S8（FFmpeg 音频插件总览） | S60（具体 AAC 插件）|
|------|-------------------------|---------------------|
| 粒度 | 音频 FFmpeg 插件架构总览 | AAC 编解码具体插件 |
| 编码器 | 通用 AudioFFmpegEncoderPlugin | AudioFFMpegAacEncoderPlugin |
| 解码器 | AudioFfmpegDecoderPlugin 通用基类 | AudioFFMpegAacDecoderPlugin 组合基类 |
| ADTS | 未覆盖 | ADTS 7字节头生成/解析 |
| 重采样 | 通用 AudioResample | needResample_ 自动触发 |

## 8. 关键证据来源

| 文件 | 行号 | 内容 |
|------|------|------|
| `services/engine/codec/include/audio/encoder/audio_ffmpeg_aac_encoder_plugin.h` | 全文 | 类定义，CodecRegister CRTP 注册，成员变量 |
| `services/engine/codec/include/audio/decoder/audio_ffmpeg_aac_decoder_plugin.h` | 全文 | 类定义，组合 AudioFfmpegDecoderPlugin |
| `services/engine/codec/audio/encoder/audio_ffmpeg_aac_encoder_plugin.cpp` | 25-43 | 常量定义，ADTS 采样率/通道映射表 |
| `services/engine/codec/audio/encoder/audio_ffmpeg_aac_encoder_plugin.cpp` | 84-99 | GetAdtsHeader 7字节 ADTS 头生成 |
| `services/engine/codec/audio/encoder/audio_ffmpeg_aac_encoder_plugin.cpp` | 295-330 | OpenContext，avcodec_open2 + AudioResample 初始化 |
| `services/engine/codec/audio/encoder/audio_ffmpeg_aac_encoder_plugin.cpp` | 333-348 | CheckResample 格式不匹配判定 |
| `services/engine/codec/audio/encoder/audio_ffmpeg_aac_encoder_plugin.cpp` | 421-431 | SendBuffer: avcodec_send_frame 发送循环 |
| `services/engine/codec/audio/encoder/audio_ffmpeg_aac_encoder_plugin.cpp` | 453-472 | PcmFillFrame: AudioResample 实际转换 |
| `services/engine/codec/audio/encoder/audio_ffmpeg_aac_encoder_plugin.cpp` | 478-510 | ReceiveBuffer: avcodec_receive_packet + ADTS 头拼接 |
| `services/engine/codec/audio/decoder/audio_ffmpeg_aac_decoder_plugin.cpp` | 30-43 | 常量，ADTS/LATM sample rate 集合 |
| `services/engine/codec/audio/decoder/audio_ffmpeg_aac_decoder_plugin.cpp` | 59-73 | CheckAdts: MD_KEY_AAC_IS_ADTS 判断 codec name |
| `services/engine/codec/audio/decoder/audio_ffmpeg_aac_decoder_plugin.cpp` | 75-122 | CheckFormat/CheckSampleFormat/CheckChannelCount/CheckSampleRate |
| `services/engine/codec/audio/decoder/audio_ffmpeg_aac_decoder_plugin.cpp` | 124-144 | Init: 委托 basePlugin 初始化 |
| `services/engine/codec/audio/decoder/audio_ffmpeg_aac_decoder_plugin.cpp` | 146-179 | ProcessSendData/RecieveData: 全委托 basePlugin |
| `interfaces/inner_api/native/avcodec_codec_name.h` | 27, 90 | AUDIO_DECODER_AAC_NAME / AUDIO_ENCODER_AAC_NAME 注册名 |
| `services/engine/codec/include/audio/audio_base_codec.h` | 全文 | AudioBaseCodec 抽象基类定义 |
