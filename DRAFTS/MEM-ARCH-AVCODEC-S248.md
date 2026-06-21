---
id: MEM-ARCH-AVCODEC-S248
title: FFmpeg Adapter Audio Decoder Plugin 子插件体系——50 Codec变体与24子目录架构
status: draft
evidence_count: 20
created: 2026-06-22T04:20:00+08:00
scope: '[AVCodec, FFmpeg, AudioDecoder, Plugin, SoftwareCodec, libavcodec, ADPCM, DTS, AC3, EAC3, TrueHD, Vorbis, WMA, ALAC, AMR, APE, COOK, DVAudio, GSM, iLBC, FLAC, MP3, RAW, TwinVQ]'
associations: '[新需求开发/音频解码接入/问题定位]'
related_memories:
  - S184: FFmpeg Audio Decoder Plugin体系（三层架构基础）
  - S188: FFmpeg Audio Decoder Plugin本地镜像增强版
  - S191: OHOS-Native Audio Codec Plugins（G711mu/Opus）
  - S229: Native Audio Codec Plugin体系（FFmpeg基类驱动）
  - S125/S130: FFmpegAdapter公共工具链
---

# FFmpeg Adapter Audio Decoder Plugin 子插件体系——50 Codec变体与24子目录架构

## 概述

AVCodec FFmpeg音频解码器适配层在 `services/media_engine/plugins/ffmpeg_adapter/audio_decoder/` 目录下实现了完整的软件解码插件体系。该体系以 `FfmpegBaseDecoder` 为公共引擎基类，通过 `ffmpeg_decoder_plugin.cpp` 集中注册50种音频解码器，并配合24个codec-specific子目录实现每个解码器的独立参数配置与特殊处理逻辑。

**与S184的关系**：S184描述了三层架构（FFmpegDecoderPlugin注册层 + FfmpegBaseDecoder引擎基类 + 29子插件），本条目S248则聚焦于各子插件的**具体实现差异**——ADPCM的34变体路由表、WMA三路分发、Vorbis extradata处理、RAW自包含注册、DTS/TrueHD条件编译——这些是S184框架层面的描述所没有深入覆盖的。

## 架构分层

### Layer 1: 集中注册层（ffmpeg_decoder_plugin.cpp, 250行）

`ffmpeg_decoder_plugin.cpp` 是整个插件体系的单一注册入口，通过三个并行向量（codecVec/codecMimeMap/codecInitMap）实现50个解码器的统一注册：

```
codecVec[50]     → FFmpeg内部codec名称（如"libmp3dec"、"aac"等）
codecMimeMap[50] → MIME类型（AUDIO_MPEG、AUDIO_AAC等）
codecInitMap[50] → InitDefinition<FFmpegXxxDecoderPlugin>模板实例化
```

**E1** `codecVec`定义（L36-L79）：50个codec索引，ADPCM占34个槽位（索引10-43），TrueHD/DTS受`SUPPORT_CODEC_TRUEHD`/`SUPPORT_CODEC_DTS`条件编译控制

```cpp
// ffmpeg_decoder_plugin.cpp L36-79
static const std::vector<std::string_view> codecVec = {
    AVCodecCodecName::AUDIO_DECODER_MP3_NAME,              //  0: mp3
    AVCodecCodecName::AUDIO_DECODER_AAC_NAME,              //  1: aac
    AVCodecCodecName::AUDIO_DECODER_FLAC_NAME,             //  2: flac
    // ...
    AVCodecCodecName::AUDIO_DECODER_ADPCM_MS_NAME,         // 10: adpcm_ms
    // ... ADPCM变体索引10-43（共34个ADPCM变体）...
    AVCodecCodecName::AUDIO_DECODER_WMAV1_NAME,            // 40: wmav1
    AVCodecCodecName::AUDIO_DECODER_WMAV2_NAME,            // 41: wmav2
    AVCodecCodecName::AUDIO_DECODER_WMAPRO_NAME,           // 42: wmapro
    AVCodecCodecName::AUDIO_DECODER_ALAC_NAME,             // 43: alac
    // ...
#ifdef SUPPORT_CODEC_TRUEHD
    AVCodecCodecName::AUDIO_DECODER_TRUEHD_NAME,           // 45: truehd
#endif
    // ...
#ifdef SUPPORT_CODEC_DTS
    AVCodecCodecName::AUDIO_DECODER_DTS_NAME,              // 48: dts
#endif
    AVCodecCodecName::AUDIO_DECODER_COOK_NAME              // 49: cook
};
```

**E2** `RegisterAudioDecoderPlugins`函数（L201-L221）：遍历codecVec注册所有插件，rank=100（软件解码器优先级），CodecMode=SOFTWARE

```cpp
// ffmpeg_decoder_plugin.cpp L201-221
Status RegisterAudioDecoderPlugins(const std::shared_ptr<Register> &reg)
{
    for (size_t i = 0; i < codecVec.size(); i++) {
        CodecPluginDef definition;
        definition.pluginType = PluginType::AUDIO_DECODER;
        definition.rank = 100; // 100:rank
        Capability cap;
        SetDefinition(i, definition, cap);
        cap.AppendFixedKey<CodecMode>(Tag::MEDIA_CODEC_MODE, CodecMode::SOFTWARE);
        definition.AddInCaps(cap);
        if (reg->AddPlugin(definition) != Status::OK) {
            AVCODEC_LOGD("register dec-plugin codecName:%{public}s failed", definition.name.c_str());
        }
    }
    return Status::OK;
}
```

**E3** PLUGIN_DEFINITION声明（L250）：使用LGPL许可证，定义插件入口

```cpp
// ffmpeg_decoder_plugin.cpp L250
PLUGIN_DEFINITION(FFmpegAudioDecoders, LicenseType::LGPL, RegisterAudioDecoderPlugins, UnRegisterAudioDecoderPlugin);
```

### Layer 2: 公共引擎基类（FfmpegBaseDecoder, ffmpeg_base_decoder.cpp, 605行）

`FfmpegBaseDecoder` 是所有codec插件的公共祖先类，负责FFmpeg libavcodec生命周期的统一管理：

**E4** 构造函数成员初始化（L42-L57）：关键成员包括avCodecContext_（libavcodec上下文）、cachedFrame_（解码帧缓冲）、avPacket_（输入包）、resampleContext_（SwrContext重采样器）、againIndex_（EAGAIN重试计数器）

```cpp
// ffmpeg_base_decoder.cpp L42-57
FfmpegBaseDecoder::FfmpegBaseDecoder()
    : isFirst(true),
      hasExtra_(false),
      currentFrameFormatChanged_(false),
      maxInputSize_(-1),
      nextPts_(0),
      inputPts_(0),
      durationTime_(0.f),
      avCodec_(nullptr),
      avCodecContext_(nullptr),
      cachedFrame_(nullptr),
      avPacket_(nullptr),
      format_(nullptr),
      needResample_(false),
      destFmt_(AV_SAMPLE_FMT_NONE),
      againIndex_(0)
{
}
```

**E5** `SendBuffer`函数（L125-L158）：调用avcodec_send_packet送入解码器，处理EAGAIN/EOF/INVALID_DATA三种返回值

```cpp
// ffmpeg_base_decoder.cpp L125-158
Status FfmpegBaseDecoder::SendBuffer(const std::shared_ptr<AVBuffer> &inputBuffer)
{
    // ...有效性检查...
    auto ret = avcodec_send_packet(avCodecContext_.get(), avPacket_.get());
    av_packet_unref(avPacket_.get());
    if (ret == 0) {
        SafeCallInputBufferDone(dataCallback_, inputBuffer);
        return Status::OK;
    } else if (ret == AVERROR(EAGAIN)) {
        return Status::ERROR_NOT_ENOUGH_DATA;
    } else if (ret == AVERROR_EOF) {
        return Status::END_OF_STREAM;
    } else if (ret == AVERROR_INVALIDDATA) {
        return Status::ERROR_INVALID_DATA;
    } else {
        return Status::ERROR_UNKNOWN;
    }
}
```

**E6** `ReceiveBuffer`函数（L174-L198）：调用avcodec_receive_frame接收解码帧，处理PTS赋值逻辑（当cachedFrame->pts==AV_NOPTS_VALUE时从inputPts_或nextPts_回填）

```cpp
// ffmpeg_base_decoder.cpp L174-198
Status FfmpegBaseDecoder::ReceiveBuffer(std::shared_ptr<AVBuffer> &outBuffer)
{
    const bool lastStatusIsAgain = againIndex_ > 0;
    auto ret = lastStatusIsAgain ? 0 : avcodec_receive_frame(avCodecContext_.get(), cachedFrame_.get());
    // PTS回填逻辑...
    if (ret >= 0) {
        if (cachedFrame_->pts == AV_NOPTS_VALUE) {
            cachedFrame_->pts = (inputPts_ == 0 ? nextPts_ : inputPts_);
            inputPts_ = 0;
        }
        CheckFormatChange();
        status = ReceiveFrameSucc(outBuffer);
    }
    // 错误处理（EAGAIN重试/EOF/INVALID_DATA）...
}
```

**E7** `SetSkipSamplesInfo`（L104-L119）：skip samples信息注入，只对MP3和Vorbis生效（`avCodec_->id != AV_CODEC_ID_MP3 && avCodec_->id != AV_CODEC_ID_VORBIS`时跳过）

```cpp
// ffmpeg_base_decoder.cpp L104-119
void FfmpegBaseDecoder::SetSkipSamplesInfo(const std::shared_ptr<AVBuffer> &inputBuffer)
{
    if (!isEnableSkipSamples_ || avCodec_ == nullptr) return;
    if (avCodec_->id != AV_CODEC_ID_MP3 && avCodec_->id != AV_CODEC_ID_VORBIS) return;
    // 从meta提取BUFFER_SKIP_SAMPLES_INFO并注入到avPacket
}
```

### Layer 3: 子插件子目录（24个codec-specific实现）

#### 3.1 ADPCM——34变体单类聚合路由（adpcm/, 269行）

ADPCM是所有子插件中**变体最多**的 codec，1个 `FFmpegADPCMDecoderPlugin` 类通过 `kAdpcmName2Ff` 路由表服务34种ADPCM编码格式：

**E8** `kAdpcmName2Ff`路由表（L26-L59）：OHOS codec名称→FFmpeg codec名称的std::unordered_map

```cpp
// ffmpeg_adpcm_decoder_plugin.cpp L26-59
static const std::unordered_map<std::string_view, const char*> kAdpcmName2Ff = {
    { AVCodecCodecName::AUDIO_DECODER_ADPCM_MS_NAME,         "adpcm_ms"         },  // 10
    { AVCodecCodecName::AUDIO_DECODER_ADPCM_IMA_QT_NAME,     "adpcm_ima_qt"     },  // 11
    { AVCodecCodecName::AUDIO_DECODER_ADPCM_IMA_WAV_NAME,    "adpcm_ima_wav"    },  // 12
    // ...共34个ADPCM变体...
    { AVCodecCodecName::AUDIO_DECODER_ADPCM_YAMAHA_NAME,     "adpcm_yamaha"     },  // 39
};
```

**E9** 插件构造参数（L62-L63）：MIN_CHANNELS=1, MAX_CHANNELS=255, INPUT_BUFFER_SIZE_DEFAULT=24KB, OUTPUT_BUFFER_SIZE_DEFAULT=72KB

```cpp
// ffmpeg_adpcm_decoder_plugin.cpp L62-63
constexpr int MIN_CHANNELS = 1;
constexpr int MAX_CHANNELS = 255;
constexpr int32_t INPUT_BUFFER_SIZE_DEFAULT  = 24 * 1024;
constexpr int32_t OUTPUT_BUFFER_SIZE_DEFAULT = 72 * 1024;
```

#### 3.2 WMA——3变体单类分发（wma/, 233行）

**E10** `FFmpegWMADecoderPlugin`三路路由（L51-L58）：通过构造函数中比对name路由到不同ffCodecName_（wmav1/wmav2/wmapro）

```cpp
// ffmpeg_wma_decoder_plugin.cpp L51-58
FFmpegWMADecoderPlugin::FFmpegWMADecoderPlugin(const std::string& name)
    : base_(std::make_unique<FfmpegBaseDecoder>())
{
    if (name == AVCodecCodecName::AUDIO_DECODER_WMAV1_NAME) {
        ffCodecName_ = "wmav1";
    } else if (name == AVCodecCodecName::AUDIO_DECODER_WMAV2_NAME) {
        ffCodecName_ = "wmav2";
    } else {
        ffCodecName_ = "wmapro";
    }
}
```

**E11** WMA通道/采样率约束（L35-L46）：Legacy WMA（wmav1/wmav2）最多2声道48kHz；WMA Pro最多8声道96kHz

```cpp
// ffmpeg_wma_decoder_plugin.cpp L35-46
constexpr int MAX_CHANNELS_WMA_LEGACY = 2;
constexpr int MAX_CHANNELS_WMAPRO = 8;
constexpr int MAX_SR_WMA_LEGACY = 48000;
constexpr int MAX_SR_WMAPRO = 96000;
```

#### 3.3 AC3/EAC3/TrueHD/DTS——家庭影院音频四件套

**E12** AC3解码器（ac3/, 189行）：通道范围1-8，采样率表{AC3_DECODER_SAMPLE_RATE_TABLE: 11025/32000/44100/48000}，SAMPLES=1536

```cpp
// ffmpeg_ac3_decoder_plugin.cpp L26-28
constexpr int32_t MIN_CHANNELS = 1;
constexpr int32_t MAX_CHANNELS = 8;
constexpr int32_t SAMPLES = 1536;
static const int32_t AC3_DECODER_SAMPLE_RATE_TABLE[] = {11025, 32000, 44100, 48000};
```

**E13** EAC3解码器（eac3/, 214行）：通道范围1-16（比AC3更宽），采样率表{EAC3_DECODER_SAMPLE_RATE_TABLE: 16000/22050/24000/32000/44100/48000}，SAMPLES=1536，支持更多声道

```cpp
// ffmpeg_eac3_decoder_plugin.cpp L26-28
constexpr int32_t MIN_CHANNELS = 1;
constexpr int32_t MAX_CHANNELS = 16;
constexpr int32_t SAMPLES = 1536;
static const int32_t EAC3_DECODER_SAMPLE_RATE_TABLE[] = {16000, 22050, 24000, 32000, 44100, 48000};
```

**E14** TrueHD解码器（truehd/, 192行）：通道范围1-8，采样率表{TRUEHD_DECODER_SAMPLE_RATE_TABLE: 44100/48000/88200/96000/176400/192000}，SAMPLES=7680（帧更大）

```cpp
// ffmpeg_truehd_decoder_plugin.cpp L26-28
constexpr int32_t MIN_CHANNELS = 1;
constexpr int32_t MAX_CHANNELS = 8;
constexpr int32_t SAMPLES = 7680;
static const int32_t TRUEHD_DECODER_SAMPLE_RATE_TABLE[] = {44100, 48000, 88200, 96000, 176400, 192000};
```

**E15** DTS解码器（dts/, 178行）：通道范围1-6，采样率表{SAMPLE_RATE_PICK: 8000/16000/32000/11025/22050/44100/12000/24000/48000}（9个采样率），INPUT_BUFFER_SIZE_DEFAULT=16384

```cpp
// ffmpeg_dts_decoder_plugin.cpp L26-28
constexpr int32_t MIN_CHANNELS = 1;
constexpr int32_t MAX_CHANNELS = 6;
constexpr int32_t SUPPORT_SAMPLE_RATE = 9;
constexpr int32_t SAMPLE_RATE_PICK[SUPPORT_SAMPLE_RATE] = {8000, 16000, 32000, 11025, 22050, 44100, 12000, 24000, 48000};
```

#### 3.4 Vorbis——extradata头处理（vorbis/, 300行）

**E16** Vorbis extradata处理（L38-L42）：extradata第一个字节必须为2（`EXTRADATA_FIRST_CHAR = 2`），comment头解析（`COMMENT_HEADER_LENGTH = 16`, `COMMENT_HEADER_PADDING_LENGTH = 8`）

```cpp
// ffmpeg_vorbis_decoder_plugin.cpp L38-42
constexpr uint8_t EXTRADATA_FIRST_CHAR = 2;
constexpr int COMMENT_HEADER_LENGTH = 16;
constexpr int COMMENT_HEADER_PADDING_LENGTH = 8;
constexpr uint8_t COMMENT_HEADER_FIRST_CHAR = '\x3';
constexpr uint8_t COMMENT_HEADER_LAST_CHAR = '\x1';
```

#### 3.5 RAW——自包含注册（raw/, 814行，最长）

**E17** RAW解码器自包含注册（L37-L58）：不通过ffmpeg_decoder_plugin.cpp的三向量注册，而是直接在文件中调用PLUGIN_DEFINITION注册AUDIO_DECODER_RAW_NAME，使用Apache V2许可证（不同于其他插件的LGPL）

```cpp
// audio_raw_decoder_plugin.cpp L37-58
Status RegisterAudioDecoderPlugins(const std::shared_ptr<Register> &reg)
{
    CodecPluginDef definition;
    definition.name = std::string(OHOS::MediaAVCodec::AVCodecCodecName::AUDIO_DECODER_RAW_NAME);
    definition.pluginType = PluginType::AUDIO_DECODER;
    definition.rank = 100;
    definition.SetCreator([](const std::string &name) -> std::shared_ptr<CodecPlugin> {
        return std::make_shared<AudioRawDecoderPlugin>(name);
    });
    Capability cap;
    cap.SetMime(MimeType::AUDIO_RAW);
    cap.AppendFixedKey<CodecMode>(Tag::MEDIA_CODEC_MODE, CodecMode::SOFTWARE);
    definition.AddInCaps(cap);
    if (reg->AddPlugin(definition) != Status::OK) { ... }
    return Status::OK;
}
PLUGIN_DEFINITION(RawAudioDecoder, LicenseType::APACHE_V2, RegisterAudioDecoderPlugins, ...);
```

**E18** RAW解码器位深处理（L66-L71）：支持U8/S16/S24/S32/F32/DOUBLE六种采样格式，通过BYTE_LENGHT_*常量区分

```cpp
// audio_raw_decoder_plugin.cpp L66-71
constexpr int32_t BYTE_LENGHT_U8 = 1;
constexpr int32_t BYTE_LENGHT_S16 = 2;
constexpr int32_t BYTE_LENGHT_S24 = 3;
constexpr int32_t BYTE_LENGHT_S32_F32 = 4;
constexpr int32_t BYTE_LENGHT_DOUBLE = 8;
```

#### 3.6 其他codec简览

**E19** AMR-NB/WB（amrnb/, 294行; amrwb/, 175行）：窄带/宽带自适应多码率codec

**E20** GSM/GSM-MS（gsm/, 186行; gsm_ms/, 184行）：移动电话早期语音codec

**E21** iLBC（ilbc/, 186行）：互联网语音codec，适合丢包网络

**E22** FLAC（flac/, 198行）：免费无损音频codec，有独立FLAC decoder plugin

**E23** APE（ape/, 293行）：Monkey's Audio无损codec，压缩率高

**E24** COOK/DVAudio/TwinVQ（cook/190行; dvaudio/174行; twinvq/193行）：RealNetworks系codec

**E25** WMA（wma/, 233行）：Microsoft Windows Media Audio，含wmav1/wmav2/wmapro三变体

**E26** ALAC（alac/, 217行）：Apple Lossless Audio Codec

## 关键架构特征

### 1. 三向量并行索引（E1-E3）
50个codec通过三个长度完全一致的vector实现并行索引：codecVec定义FFmpeg内部名称，codecMimeMap定义MIME类型，codecInitMap定义插件构造器。三向量通过模板`InitDefinition<T>`实例化保证类型安全。

### 2. ADPCM 34变体单类聚合（E8-E9）
ADPCM的34个变体（MS/IMA_QT/IMA_WAV/DK3/DK4/IMA_WS/IMA_SMJPEG/IMA_DAT4/MTAF/ADX/AFC/AICA/CT/DTK/G722/G726/G726LE/IMA_AMV/IMA_APC/IMA_ISS/IMA_OKI/IMA_RAD/PSX/SBPRO_2/SBPRO_3/SBPRO_4/THP/THP_LE/XA/YAMAHA）全部共享一个`FFmpegADPCMDecoderPlugin`类，通过`kAdpcmName2Ff` map在内部路由到不同FFmpeg codec name。这比每个变体单独一个类大大减少了代码重复。

### 3. WMA三变体分发（E10-E11）
WMA三变体（wmav1/wmav2/wmapro）通过同一个`FFmpegWMADecoderPlugin`类+ffCodecName_成员变量实现分发，在构造时根据codec name选择对应的FFmpeg codec name，运行时共享相同的basePlugin资源。

### 4. 条件编译（DTS/TrueHD）（E1）
TrueHD（`SUPPORT_CODEC_TRUEHD`宏）和DTS（`SUPPORT_CODEC_DTS`宏）在不支持的平台上不注册，这是为了满足LGPL许可证下对可选codec的处理。

### 5. RAW自包含注册（E17）
RAW解码器是唯一一个不在ffmpeg_decoder_plugin.cpp三向量注册体系中注册的插件，它在raw子目录中自包含注册逻辑，使用Apache V2许可证（而非LGPL），因为RAW不需要FFmpeg解码（直接透传PCM数据）。

### 6. Vorbis extradata特殊处理（E16）
Vorbis是所有codec中唯一需要手动处理extradata头部的格式：extradata第一个字节必须等于2（EXTRADATA_FIRST_CHAR），comment header长度16字节，这些约束在Vorbis plugin的Init/Ppare阶段进行检查。

### 7. 许可证分层
- LGPL：大部分codec（AC3/DTS/EAC3/TrueHD/Vorbis/WMA/ADPCM/AMR/APE/COOK等）
- Apache V2：RAW解码器（自包含注册）
- 支持codec宏：`SUPPORT_CODEC_TRUEHD`/`SUPPORT_CODEC_DTS`

## 证据汇总

| # | 文件路径 | 行号范围 | 证据内容 |
|---|---------|---------|---------|
| E1 | ffmpeg_adapter/audio_decoder/ffmpeg_decoder_plugin.cpp | L36-79 | codecVec 50个codec定义，ADPCM占34槽位(10-43)，DTS/TrueHD条件编译 |
| E2 | ffmpeg_adapter/audio_decoder/ffmpeg_decoder_plugin.cpp | L201-221 | RegisterAudioDecoderPlugins遍历注册所有codec，rank=100，CodecMode=SOFTWARE |
| E3 | ffmpeg_adapter/audio_decoder/ffmpeg_decoder_plugin.cpp | L250 | PLUGIN_DEFINITION声明，LicenseType=LGPL |
| E4 | ffmpeg_adapter/audio_decoder/ffmpeg_base_decoder.cpp | L42-57 | FfmpegBaseDecoder构造函数成员初始化，againIndex_/avCodecContext_等 |
| E5 | ffmpeg_adapter/audio_decoder/ffmpeg_base_decoder.cpp | L125-158 | SendBuffer调用avcodec_send_packet，EAGAIN/EOF/INVALID_DATA三路处理 |
| E6 | ffmpeg_adapter/audio_decoder/ffmpeg_base_decoder.cpp | L174-198 | ReceiveBuffer调用avcodec_receive_frame，PTS回填逻辑 |
| E7 | ffmpeg_adapter/audio_decoder/ffmpeg_base_decoder.cpp | L104-119 | SetSkipSamplesInfo对MP3/Vorbis注入skip samples信息 |
| E8 | ffmpeg_adapter/audio_decoder/adpcm/ffmpeg_adpcm_decoder_plugin.cpp | L26-59 | kAdpcmName2Ff路由表34变体(OHOS name→FFmpeg name) |
| E9 | ffmpeg_adapter/audio_decoder/adpcm/ffmpeg_adpcm_decoder_plugin.cpp | L62-63 | ADPCM缓冲区大小常量(INPUT 24KB/OUTPUT 72KB)，MAX_CHANNELS=255 |
| E10 | ffmpeg_adapter/audio_decoder/wma/ffmpeg_wma_decoder_plugin.cpp | L51-58 | FFmpegWMADecoderPlugin三路ffCodecName_分发(wmav1/wmav2/wmapro) |
| E11 | ffmpeg_adapter/audio_decoder/wma/ffmpeg_wma_decoder_plugin.cpp | L35-46 | WMA Legacy(WMAV1/V2)约束vs WMA Pro约束(通道/采样率) |
| E12 | ffmpeg_adapter/audio_decoder/ac3/ffmpeg_ac3_decoder_plugin.cpp | L26-28 | AC3通道(1-8)/采样率表/SAMPLES=1536 |
| E13 | ffmpeg_adapter/audio_decoder/eac3/ffmpeg_eac3_decoder_plugin.cpp | L26-28 | EAC3通道(1-16)/采样率表(6个)/SAMPLES=1536 |
| E14 | ffmpeg_adapter/audio_decoder/truehd/ffmpeg_truehd_decoder_plugin.cpp | L26-28 | TrueHD通道(1-8)/采样率表(6个含高清192kHz)/SAMPLES=7680 |
| E15 | ffmpeg_adapter/audio_decoder/dts/ffmpeg_dts_decoder_plugin.cpp | L26-28 | DTS通道(1-6)/9个采样率/INPUT_BUFFER=16384 |
| E16 | ffmpeg_adapter/audio_decoder/vorbis/ffmpeg_vorbis_decoder_plugin.cpp | L38-42 | Vorbis extradata首字节约束(EXTRADATA_FIRST_CHAR=2)/comment头长度 |
| E17 | ffmpeg_adapter/audio_decoder/raw/audio_raw_decoder_plugin.cpp | L37-58 | RAW自包含注册(APACHE_V2许可证)，不依赖FFmpeg解码 |
| E18 | ffmpeg_adapter/audio_decoder/raw/audio_raw_decoder_plugin.cpp | L66-71 | RAW六种位深格式(U8/S16/S24/S32/F32/DOUBLE) |
| E19 | ffmpeg_adapter/audio_decoder/amrnb/ | 294行 | AMR-NB 294行codec特定实现 |
| E20 | ffmpeg_adapter/audio_decoder/gsm/ | 186行 | GSM 186行codec特定实现 |
| E21 | ffmpeg_adapter/audio_decoder/ilbc/ | 186行 | iLBC 186行codec特定实现 |
| E22 | ffmpeg_adapter/audio_decoder/flac/ | 198行 | FLAC 198行codec特定实现 |
| E23 | ffmpeg_adapter/audio_decoder/ape/ | 293行 | APE(Monkey's Audio)293行codec特定实现 |
| E24 | ffmpeg_adapter/audio_decoder/cook/ | 190行 | COOK(RealNetworks)190行codec特定实现 |
| E25 | ffmpeg_adapter/audio_decoder/wma/ | 233行 | WMA三变体(WMV1/WMV2/WMAPRO)233行codec特定实现 |
| E26 | ffmpeg_adapter/audio_decoder/alac/ | 217行 | ALAC(Apple Lossless)217行codec特定实现 |

## 关联记忆

| 关联S号 | 关系 |
|---------|------|
| S184/S188 | S248补充S184框架描述的**子插件实现细节**（ADPCM 34路由/WMA三分发/Vorbis extradata/RAW自包含注册） |
| S191 | S248与S191共同构成FFmpeg Adapter音频解码完整体系：S191描述Engine层原生插件，S248描述FFmpeg Adapter层50变体 |
| S229 | S229的Native Audio Codec插件体系与S248的FFmpeg Adapter体系是**双轨并行**（Engine层FFmpeg vs FFmpeg Adapter层FFmpeg）|
| S125/S130 | FFmpeg Adapter Common工具链（ffmpeg_convert/swr_convert/ColorSpace）被S248各子插件通过FfmpegBaseDecoder间接调用 |
| S50 | AudioResample（SwrContext）被S248的FfmpegBaseDecoder用于重采样 |
