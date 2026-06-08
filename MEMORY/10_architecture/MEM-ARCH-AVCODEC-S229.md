# MEM-ARCH-AVCODEC-S229: Native Audio Codec Decoder/Encoder Plugin Architecture

## 主题
Native Audio Codec Decoder/Encoder Plugin 体系——services/engine/codec/audio/ 原生插件目录（FFmpeg基类驱动 + G711mu零依赖表驱动 + Opus dlopen动态库）三层路径

## 标签
`AVCodec` `AudioCodec` `AudioDecoder` `AudioEncoder` `FFmpeg` `G711mu` `Opus` `AAC` `FLAC` `MP3` `Vorbis` `dlopen` `Native` `SoftwareCodec` `libavcodec` `ADTS`

## 关联场景
新需求开发 / 音频编解码接入 / 问题定位 / 音频编解码零依赖实现 / G.711 mu-law

## 关联记忆
- S125/S130/S158/S169/S184: FFmpeg Audio Decoder Plugin 体系（FFmpegAdapter路径，services/media_engine/plugins/ffmpeg_adapter/）
- S191: OHOS-Native Audio Codec Plugins（G711mu/Opus vs FFmpeg-Based 双路径）
- S193: FFmpeg Adapter Audio Encoder Plugin 体系（FFmpegAdapter路径，五子插件）
- S35/S62: AudioCodec基础架构

---

## 一、架构概述

services/engine/codec/audio/ 目录下存在两套原生音频编解码插件体系，**独立于** services/media_engine/plugins/ffmpeg_adapter/ 的 FFmpegAdapter 路径：

| 层级 | Decoder（9文件/1953行） | Encoder（5文件/1692行） |
|------|------------------------|------------------------|
| **FFmpeg基类驱动** | AudioFfmpegDecoderPlugin（426行） | AudioFfmpegEncoderPlugin（348行） |
| **FFmpeg封装插件** | AAC/FLAC/MP3/Vorbis（包装AudioFfmpegDecoderPlugin） | AAC/FLAC（包装AudioFfmpegEncoderPlugin） |
| **零依赖表驱动** | G711mu（纯C++，无FFmpeg依赖） | G711mu（纯C++，无FFmpeg依赖） |
| **dlopen动态库** | Opus（加载 libav_codec_ext_base.z.so） | Opus（加载 libav_codec_ext_base.z.so） |

**与 FFmpegAdapter 路径的关键区别：**
- FFmpegAdapter（services/media_engine/plugins/ffmpeg_adapter/）：三层架构（FFmpegDecoderPlugin注册层 + FfmpegBaseDecoder引擎基类 + 50子插件），通过AutoRegisterFilter静态注册
- **Native路径（services/engine/codec/audio/）**：两层架构（AudioFfmpegDecoderPlugin基类 + 包装插件/零依赖插件/dlopne插件），通过CodecFactory动态创建

---

## 二、AudioFfmpegDecoderPlugin 基类（audio_ffmpeg_decoder_plugin.cpp, 426行）

### 2.1 核心数据结构

E1: `AudioFfmpegDecoderPlugin` 构造函数成员初始化（行30-43）
```cpp
AudioFfmpegDecoderPlugin::AudioFfmpegDecoderPlugin()
    : hasExtra_(false),
      maxInputSize_(-1),
      bufferNum_(1),
      bufferIndex_(1),
      preBufferGroupPts_(0),
      curBufferGroupPts_(0),
      bufferGroupPtsDistance(0),
      avCodec_(nullptr),
      avCodecContext_(nullptr),
      cachedFrame_(nullptr),
      avPacket_(nullptr),
      resample_(nullptr),
      needResample_(false),
      destFmt_(AV_SAMPLE_FMT_NONE)
```
关键成员：`avCodec_`（FFmpeg AVCodec）、`avCodecContext_`（FFmpeg CodecContext）、`cachedFrame_`（AVFrame缓存）、`avPacket_`（AVPacket缓存）、`resample_`（AudioResample重采样器）

### 2.2 解码管线：avcodec_send_packet / avcodec_receive_frame

E2: `ProcessSendData` → `SendBuffer` → `avcodec_send_packet`（行55-113）
```cpp
int32_t AudioFfmpegDecoderPlugin::ProcessSendData(const std::shared_ptr<AudioBufferInfo> &inputBuffer)
{
    std::lock_guard<std::mutex> lock(avMutext_);
    if (avCodecContext_ == nullptr) {
        AVCODEC_LOGE("avCodecContext_ is nullptr");
        return AVCodecServiceErrCode::AVCS_ERR_INVALID_OPERATION;
    }
    return SendBuffer(inputBuffer);
}

int32_t AudioFfmpegDecoderPlugin::SendBuffer(const std::shared_ptr<AudioBufferInfo> &inputBuffer)
{
    // ... pts/size设置 ...
    auto ret = avcodec_send_packet(avCodecContext_.get(), avPacket_.get());
    av_packet_unref(avPacket_.get());
    if (ret == 0) {
        return AVCodecServiceErrCode::AVCS_ERR_OK;
    }
    // ...
}
```

E3: `ReceiveBuffer` → `avcodec_receive_frame` 三状态处理（行135-179）
```cpp
int32_t AudioFfmpegDecoderPlugin::ReceiveBuffer(std::shared_ptr<AudioBufferInfo> &outBuffer)
{
    auto ret = avcodec_receive_frame(avCodecContext_.get(), cachedFrame_.get());
    if (ret >= 0) {
        // 帧有效，处理pts计算
        status = ReceiveFrameSucc(outBuffer);
    } else if (ret == AVERROR_EOF) {
        outBuffer->SetEos(true);
        avcodec_flush_buffers(avCodecContext_.get());
        status = AVCodecServiceErrCode::AVCS_ERR_END_OF_STREAM;
    } else if (ret == AVERROR(EAGAIN)) {
        status = AVCodecServiceErrCode::AVCS_ERR_NOT_ENOUGH_DATA;
    }
    // ...
}
```

### 2.3 FFmpeg上下文初始化

E4: `AllocateContext` → `avcodec_alloc_context3` + `avcodec_find_decoder_by_name`（行261-277）
```cpp
avCodec_ = std::shared_ptr<AVCodec>(const_cast<AVCodec *>(avcodec_find_decoder_by_name(name.c_str())),
                                    [](AVCodec *ptr) { (void)ptr; });
cachedFrame_ = std::shared_ptr<AVFrame>(av_frame_alloc(), [](AVFrame *fp) { av_frame_free(&fp); });
context = avcodec_alloc_context3(avCodec_.get());
avCodecContext_ = std::shared_ptr<AVCodecContext>(context, [](AVCodecContext *ptr) {
    if (ptr) { avcodec_free_context(&ptr); ptr = nullptr; }
});
```

E5: `InitContext` 通道布局配置 +色彩空间转换（行286-327）
```cpp
int32_t AudioFfmpegDecoderPlugin::InitContext(const Format &format)
{
    format_ = format;
    format_.GetIntValue(MediaDescriptionKey::MD_KEY_CHANNEL_COUNT, channels);
    format_.GetIntValue(MediaDescriptionKey::MD_KEY_SAMPLE_RATE, avCodecContext_->sample_rate);
    auto ffChannelLayout = FFMpegConverter::ConvertOHAudioChannelLayoutToFFMpeg(
        static_cast<AudioChannelLayout>(channelLayout));
    if (av_channel_layout_from_mask(&avCodecContext_->ch_layout, ffChannelLayout)) { ... }
    avCodecContext_->sample_fmt = AV_SAMPLE_FMT_S16;
    int32_t status = SetCodecExtradata(); // extradata用于AAC等带配置数据的codec
    // ...
}
```

E6: `OpenContext` → `avcodec_open2`（行331-339）
```cpp
int32_t AudioFfmpegDecoderPlugin::OpenContext()
{
    avPacket_ = std::shared_ptr<AVPacket>(av_packet_alloc(), [](AVPacket *ptr) { av_packet_free(&ptr); });
    auto res = avcodec_open2(avCodecContext_.get(), avCodec_.get(), nullptr);
    if (res != 0) { AVCODEC_LOGE("avcodec open error %{public}s", AVStrError(res).c_str()); ... }
}
```

### 2.4 重采样与帧转换

E7: `InitResample` → AudioResample + SwrContext（行341-360）
```cpp
int32_t AudioFfmpegDecoderPlugin::InitResample()
{
    if (needResample_) {
        ResamplePara resamplePara = {
            .channels = avCodecContext_->ch_layout.nb_channels,
            .sampleRate = avCodecContext_->sample_rate,
            .srcFmt = avCodecContext_->sample_fmt,
            .destFmt = destFmt_,
        };
        convertedFrame_ = std::shared_ptr<AVFrame>(av_frame_alloc(), [](AVFrame *fp) { av_frame_free(&fp); });
        resample_ = std::make_shared<AudioResample>();
        if (resample_->InitSwrContext(resamplePara) != AVCodecServiceErrCode::AVCS_ERR_OK) { ... }
    }
}
```

E8: `ReceiveFrameSucc` → `ioInfoMem->Write` 输出（行195-224）
```cpp
int32_t AudioFfmpegDecoderPlugin::ReceiveFrameSucc(std::shared_ptr<AudioBufferInfo> &outBuffer)
{
    auto outFrame = cachedFrame_;
    if (needResample_) {
        // ConvertPlanarFrame → resample_->ConvertFrame(convertedFrame_, cachedFrame_)
        outFrame = convertedFrame_;
    }
    int32_t bytePerSample = av_get_bytes_per_sample(static_cast<AVSampleFormat>(outFrame->format));
    int32_t outputSize = outFrame->nb_samples * bytePerSample * outFrame->ch_layout.nb_channels;
    ioInfoMem->Write(outFrame->data[0], outputSize);
    auto attr = outBuffer->GetBufferAttr();
    attr.presentationTimeUs = static_cast<uint64_t>(cachedFrame_->pts);
    attr.size = outputSize;
    outBuffer->SetBufferAttr(attr);
}
```

E9: `Flush` → `avcodec_flush_buffers`（行254-260）
```cpp
int32_t AudioFfmpegDecoderPlugin::Flush()
{
    std::lock_guard<std::mutex> lock(avMutext_);
    if (avCodecContext_ != nullptr) {
        avcodec_flush_buffers(avCodecContext_.get());
    }
    return AVCodecServiceErrCode::AVCS_ERR_OK;
}
```

E10: `CloseCtxLocked` → `avcodec_free_context` 资源释放（行383-390）
```cpp
int32_t AudioFfmpegDecoderPlugin::CloseCtxLocked()
{
    if (avCodecContext_ != nullptr) {
        avCodecContext_.reset();
        avCodecContext_ = nullptr;
    }
    return AVCodecServiceErrCode::AVCS_ERR_OK;
}
```

---

## 三、G711mu 零依赖表驱动编解码（纯C++，无FFmpeg）

### 3.1 G711mu Decoder（audio_g711mu_decoder_plugin.cpp, 168行）

E11: mu-law解码常量定义 + G711MuLawDecode 查表算法（行24-69）
```cpp
constexpr int SUPPORT_CHANNELS = 1;
constexpr int SUPPORT_SAMPLE_RATE = 8000;
constexpr int INPUT_BUFFER_SIZE_DEFAULT = 640; // 20ms:160样本
constexpr int OUTPUT_BUFFER_SIZE_DEFAULT = 1280; // 20ms:320样本
constexpr int AUDIO_G711MU_SIGN_BIT = 0x80;
constexpr int AVCODEC_G711MU_QUANT_MASK = 0xf;
constexpr int AVCODEC_G711MU_SHIFT = 4;
constexpr int AVCODEC_G711MU_SEG_MASK = 0x70;
constexpr int G711MU_LINEAR_BIAS = 0x84;

int16_t AudioG711muDecoderPlugin::G711MuLawDecode(uint8_t muLawValue)
{
    uint16_t tmp;
    muLawValue = ~muLawValue;
    tmp = ((muLawValue & AVCODEC_G711MU_QUANT_MASK) << 3) + G711MU_LINEAR_BIAS;
    tmp <<= ((unsigned)muLawValue & AVCODEC_G711MU_SEG_MASK) >> AVCODEC_G711MU_SHIFT;
    return ((muLawValue & AUDIO_G711MU_SIGN_BIT) ? (G711MU_LINEAR_BIAS - tmp) : (tmp - G711MU_LINEAR_BIAS));
}
```

E12: `ProcessSendData` 零依赖解码循环（行73-97）
```cpp
int32_t AudioG711muDecoderPlugin::ProcessSendData(const std::shared_ptr<AudioBufferInfo> &inputBuffer)
{
    auto memory = inputBuffer->GetBuffer();
    int32_t decodeNum = attr.size / sizeof(uint8_t);
    uint8_t *muValueToDecode = reinterpret_cast<uint8_t *>(memory->GetBase());
    decodeResult_.clear();
    for (int32_t i = 0; i < decodeNum; ++i) {
        decodeResult_.push_back(G711MuLawDecode(muValueToDecode[i]));
    }
    return AVCodecServiceErrCode::AVCS_ERR_OK;
}
```

E13: `ProcessRecieveData` → int16_t PCM输出（行99-117）
```cpp
int32_t AudioG711muDecoderPlugin::ProcessRecieveData(std::shared_ptr<AudioBufferInfo> &outBuffer)
{
    memory->Write(reinterpret_cast<const uint8_t *>(decodeResult_.data()),
        (sizeof(int16_t) * decodeResult_.size()));
    attr.size = static_cast<int32_t>(sizeof(int16_t) * decodeResult_.size());
    outBuffer->SetBufferAttr(attr);
}
```

E14: `CheckInit` 固定参数校验（行148-164）
```cpp
int32_t AudioG711muDecoderPlugin::CheckInit(const Format &format)
{
    format.GetIntValue(MediaDescriptionKey::MD_KEY_CHANNEL_COUNT, channels);
    format.GetIntValue(MediaDescriptionKey::MD_KEY_SAMPLE_RATE, sampleRate);
    if (channels != SUPPORT_CHANNELS) { return AVCodecServiceErrCode::AVCS_ERR_INVALID_VAL; }
    if (sampleRate != SUPPORT_SAMPLE_RATE) { return AVCodecServiceErrCode::AVCS_ERR_INVALID_VAL; }
    return AVCodecServiceErrCode::AVCS_ERR_OK;
}
```

### 3.2 G711mu Encoder（audio_g711mu_encoder_plugin.cpp, 239行）

E15: mu-law编码常量 + 分段查找表（行33-42）
```cpp
constexpr int AVCODEC_G711MU_LINEAR_BIAS = 0x84;
constexpr int AVCODEC_G711MU_CLIP = 8159;
constexpr uint16_t AVCODEC_G711MU_SEG_NUM = 8;
static const short AVCODEC_G711MU_SEG_END[8] = {
    0x3F, 0x7F, 0xFF, 0x1FF, 0x3FF, 0x7FF, 0xFFF, 0x1FFF
};
```

E16: `G711MuLawEncode` PCM→mu-law分段编码算法（行118-152）
```cpp
uint8_t AudioG711muEncoderPlugin::G711MuLawEncode(int16_t pcmValue)
{
    uint16_t mask; uint16_t seg;
    if (pcmValue < 0) { pcmValue = -pcmValue; mask = 0x7F; } else { mask = 0xFF; }
    uint16_t pcmShort = static_cast<uint16_t>(pcmValue);
    pcmShort = pcmShort >> 2;
    if (pcmShort > AVCODEC_G711MU_CLIP) { pcmShort = AVCODEC_G711MU_CLIP; }
    pcmShort += (AVCODEC_G711MU_LINEAR_BIAS >> 2);
    for (uint16_t i = 0; i < AVCODEC_G711MU_SEG_NUM; i++) {
        if (pcmShort <= AVCODEC_G711MU_SEG_END[i]) { seg = i; break; }
    }
    uint8_t muLawValue = (uint8_t)(seg << 4) | ((pcmShort >> (seg + 1)) & 0xF);
    return (muLawValue ^ mask);
}
```

E17: `ProcessSendData` → int16_t PCM→mu-law编码（行154-188）
```cpp
int32_t AudioG711muEncoderPlugin::ProcessSendData(const std::shared_ptr<AudioBufferInfo> &inputBuffer)
{
    int32_t sampleNum = attr.size / sizeof(int16_t);
    int16_t *pcmToEncode = reinterpret_cast<int16_t *>(memory->GetBase());
    encodeResult_.clear();
    for (int32_t i = 0; i < sampleNum; ++i) {
        encodeResult_.push_back(G711MuLawEncode(pcmToEncode[i]));
    }
}
```

---

## 四、FFmpeg封装插件（AAC/FLAC/MP3/Vorbis）

### 4.1 AudioFFMpegAacDecoderPlugin（audio_ffmpeg_aac_decoder_plugin.cpp, 199行）

E18: `AudioFFMpegAacDecoderPlugin` 构造 → `std::make_unique<AudioFfmpegDecoderPlugin>` 基类注入（行47-52）
```cpp
AudioFFMpegAacDecoderPlugin::AudioFFMpegAacDecoderPlugin()
    : basePlugin(std::make_unique<AudioFfmpegDecoderPlugin>()), channels_(0) {}
```

E19: `CheckAdts` ADTS格式检测（行54-72）
```cpp
bool AudioFFMpegAacDecoderPlugin::CheckAdts(const Format &format)
{
    int type;
    if (format.GetIntValue(MediaDescriptionKey::MD_KEY_AAC_IS_ADTS, type)) {
        if (type != 1 && type != 0) { return false; }
    } else { type = 1; }
    aacName_ = (type == 1 ? "aac" : "aac_latm");
    return true;
}
```

E20: 采样率表（行37-38）
```cpp
static std::set<int32_t> supportedSampleRate = {96000, 88200, 64000, 48000, 44100, 32000, 24000, 22050, 16000, 12000, 11025, 8000, 7350};
static std::set<OHOS::MediaAVCodec::AudioSampleFormat> supportedSampleFormats = {
    OHOS::MediaAVCodec::AudioSampleFormat::SAMPLE_S16LE,
    OHOS::MediaAVCodec::AudioSampleFormat::SAMPLE_F32LE};
```

### 4.2 AudioFFMpegVorbisDecoderPlugin（audio_ffmpeg_vorbis_decoder_plugin.cpp, 289行）

E21: Vorbis识别常量 + 头部解析（行29-38）
```cpp
constexpr std::string_view VORBIS_STRING = "vorbis";
constexpr uint8_t EXTRADATA_FIRST_CHAR = 2;
constexpr int COMMENT_HEADER_LENGTH = 16;
constexpr uint8_t COMMENT_HEADER_FIRST_CHAR = '\x3';
constexpr uint8_t COMMENT_HEADER_LAST_CHAR = '\x1';
```

### 4.3 AudioFFMpegFlacDecoderPlugin（audio_ffmpeg_flac_decoder_plugin.cpp, 158行）

E22: FLAC采样率表（行33-36）
```cpp
static const int32_t FLAC_DECODER_SAMPLE_RATE_TABLE[] = {
    8000, 11025, 12000, 16000, 22050, 24000, 32000, 44100, 48000, 64000, 88200, 96000, 192000,
};
```

---

## 五、Opus dlopen动态库加载（audio_opus_decoder_plugin.cpp, 242行）

E23: `AudioOpusDecoderPlugin` 构造 → `dlopen("libav_codec_ext_base.z.so")`（行43-59）
```cpp
AudioOpusDecoderPlugin::AudioOpusDecoderPlugin()
    : PluginCodecPtr(nullptr), fbytes(nullptr), len(-1), codeData(nullptr), channels(-1), sampleRate(-1)
{
    ret = 0;
    handle = dlopen("libav_codec_ext_base.z.so", 1);
    if (!handle) { ret = -1; AVCODEC_LOGE("AudioOpusDecoderPlugin dlopen error"); }
    OpusPluginClassCreateFun *PluginCodecCreate =
        (OpusPluginClassCreateFun *)dlsym(handle, "OpusPluginClassDecoderCreate");
    if (!PluginCodecCreate) { ret = -1; }
    if (ret == 0) { ret = PluginCodecCreate(&PluginCodecPtr); }
}
```

E24: Opus采样率表 + 固定参数（行33-39）
```cpp
constexpr int32_t MIN_CHANNELS = 1;
constexpr int32_t MAX_CHANNELS = 2;
static const int32_t OPUS_DECODER_SAMPLE_RATE_TABLE[] = {8000, 12000, 16000, 24000, 48000 };
```

---

## 六、AudioFfmpegEncoderPlugin 基类（audio_ffmpeg_encoder_plugin.cpp, 348行）

E25: `PcmFillFrame` → `avcodec_send_frame`编码管线（行35-48）
```cpp
int32_t AudioFfmpegEncoderPlugin::PcmFillFrame(const std::shared_ptr<AudioBufferInfo> &inputBuffer)
{
    auto memory = inputBuffer->GetBuffer();
    auto usedSize = inputBuffer->GetBufferAttr().size;
    auto frameSize = avCodecContext_->frame_size;
    cachedFrame_->nb_samples = static_cast<int>(usedSize / static_cast<int>(channelsBytesPerSample_));
    // ... avcodec_fill_audio_frame ...
}
```

### 6.1 AAC Encoder ADTS头（audio_ffmpeg_aac_encoder_plugin.cpp, 583行）

E26: `GetAdtsHeader` ADTS 7字节头构造（行65-85）
```cpp
uint32_t frameLength = static_cast<uint32_t>(aacLength) + ADTS_HEADER_SIZE;
uint8_t profile = static_cast<uint8_t>(ctx->profile);
adtsHeader += 0xFF;
adtsHeader += 0xF1;
adtsHeader += (profile << 0x6) + (freqIdx << 0x2) + (chanCfg >> 0x2);
adtsHeader += ((chanCfg & 0x3) << 0x6) + (frameLength >> 0xB);
adtsHeader += (frameLength & 0x7FF) >> 0x3;
adtsHeader += 0x1F;
```

E27: 采样率→频率索引映射表（行38-39）
```cpp
static std::map<int32_t, uint8_t> sampleFreqMap = {{96000, 0}, {88200, 1}, {64000, 2}, {48000, 3}, {44100, 4}, {32000, 5}, {24000, 6}, {22050, 7}, {16000, 8}, {12000, 9}, {11025, 10}, {8000, 11}, {7350, 12}};
```

---

## 七、文件总览

| 文件 | 行数 | 类型 | 特点 |
|------|------|------|------|
| audio_ffmpeg_decoder_plugin.cpp | 426 | FFmpeg基类 | avcodec_send_packet/receive_frame管线 |
| audio_ffmpeg_aac_decoder_plugin.cpp | 199 | FFmpeg封装 | ADTS格式检测 |
| audio_ffmpeg_flac_decoder_plugin.cpp | 158 | FFmpeg封装 | FLAC采样率表 |
| audio_ffmpeg_mp3_decoder_plugin.cpp | 143 | FFmpeg封装 | MP3解码 |
| audio_ffmpeg_vorbis_decoder_plugin.cpp | 289 | FFmpeg封装 | Vorbis头部解析 |
| audio_g711mu_decoder_plugin.cpp | 168 | 零依赖表 | G711mu→PCM线性 |
| audio_opus_decoder_plugin.cpp | 242 | dlopen | libav_codec_ext_base.z.so |
| audio_ffmpeg_encoder_plugin.cpp | 348 | FFmpeg基类 | avcodec_send_frame/receive_packet |
| audio_ffmpeg_aac_encoder_plugin.cpp | 583 | FFmpeg封装 | ADTS 7字节头 |
| audio_ffmpeg_flac_encoder_plugin.cpp | 259 | FFmpeg封装 | FLAC编码 |
| audio_g711mu_encoder_plugin.cpp | 239 | 零依赖表 | PCM→G711mu |
| audio_opus_encoder_plugin.cpp | 263 | dlopen | libav_codec_ext_base.z.so |
| **合计** | **3017** | | |

---

## 八、关键设计模式

1. **基类注入模式**：AudioFFMpegAacDecoderPlugin 等持有 `std::unique_ptr<AudioFfmpegDecoderPlugin> basePlugin_`，调用基类方法而非继承
2. **零依赖表驱动**：G711mu 编解码使用查表算法，无任何外部库依赖
3. **dlopen动态加载**：Opus 使用 `dlopen("libav_codec_ext_base.z.so", 1)` + `dlsym` 延迟绑定
4. **avcodec管线**：Decoder: send_packet→receive_frame；Encoder: send_frame→receive_packet
5. **pts时间戳维护**：AudioFfmpegDecoderPlugin 内部维护 bufferGroupPtsDistance 和 bufferIndex_ 用于分组帧pts推算
6. **重采样自动触发**：needResample_标志，命中时InitResample创建AudioResample/SwrContext

---

##关联
- S125/S130/S158/S169/S184（FFmpeg Adapter Audio Decoder体系）
- S191（OHOS-Native Audio Codec双路径）
- S193（FFmpeg Adapter Audio Encoder体系）
- S35/S62（AudioCodec基础架构）