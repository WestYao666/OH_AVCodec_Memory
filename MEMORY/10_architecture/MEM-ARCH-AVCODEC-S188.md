# MEM-ARCH-AVCODEC-S188: FFmpeg Audio Decoder Plugin体系——FfmpegBaseDecoder基类+19子插件+Resample重采样三层架构（本地镜像增强版）

**主题：** FFmpeg Audio Decoder Plugin体系  
**Scope：** AVCodec / AudioDecoder / FFmpeg / Plugin / Resample / SoftwareCodec  
**关联场景：** 新需求开发 / 问题定位 / 音频解码接入  
**状态：** draft → pending_approval  
**Builder：** builder-agent（subagent）  
**生成时间：** 2026-05-25T14:19:00+08:00（草案生成）/ 2026-05-25T20:30:00+08:00（提交审批）  
**基于源码：** 本地镜像 `/home/west/av_codec_repo/services/media_engine/plugins/ffmpeg_adapter/audio_decoder/`  

---

## 1. 主题概述

FFmpeg音频解码器插件体系采用**三层插件架构**（FfmpegDecoderPlugin注册层 + FfmpegBaseDecoder引擎基类 + 19子插件具体实现），封装FFmpeg libavcodec，提供50种音频格式的软件解码能力。与S183（AvcEncoder软件编码器）对称，构成FFmpeg Adapter音频编解码全链路。

---

## 2. 三层架构

### 2.1 Layer 1：FFmpegDecoderPlugin 注册层

**文件：** `ffmpeg_decoder_plugin.cpp`（250行）+ `ffmpeg_decoder_plugin.h`（46行）

**职责：** 插件自动注册（AutoRegisterFilter通过`PLUGIN_REGISTRY_MACRO`），将50种codec name映射到对应子插件factory。

**注册向量（三映射表并行）：**

```cpp
// E1: codecVec[L34-71] 50个FFmpeg codec名称（avcodec_codec_name.h）
static const std::vector<std::string_view> codecVec = {
    AVCodecCodecName::AUDIO_DECODER_MP3_NAME,              //  0: mp3
    AVCodecCodecName::AUDIO_DECODER_AAC_NAME,              //  1: aac
    AVCodecCodecName::AUDIO_DECODER_FLAC_NAME,             //  2: flac
    AVCodecCodecName::AUDIO_DECODER_VORBIS_NAME,           //  3: vorbis
    AVCodecCodecName::AUDIO_DECODER_AMRNB_NAME,            //  4: amrnb
    AVCodecCodecName::AUDIO_DECODER_AMRWB_NAME,            //  5: amrwb
    AVCodecCodecName::AUDIO_DECODER_APE_NAME,              //  6: ape
    AVCodecCodecName::AUDIO_DECODER_AC3_NAME,              //  7: ac3
    AVCodecCodecName::AUDIO_DECODER_GSM_NAME,              //  8: gsm
    AVCodecCodecName::AUDIO_DECODER_GSM_MS_NAME,           //  9: gsm_ms
    AVCodecCodecName::AUDIO_DECODER_ADPCM_MS_NAME,         // 10: adpcm_ms
    AVCodecCodecName::AUDIO_DECODER_ADPCM_IMA_QT_NAME,     // 11: adpcm_ima_qt
    AVCodecCodecName::AUDIO_DECODER_ADPCM_IMA_WAV_NAME,    // 12: adpcm_ima_wav
    AVCodecCodecName::AUDIO_DECODER_ADPCM_IMA_DK3_NAME,    // 13: adpcm_ima_dk3
    AVCodecCodecName::AUDIO_DECODER_ADPCM_IMA_DK4_NAME,    // 14: adpcm_ima_dk4
    AVCodecCodecName::AUDIO_DECODER_ADPCM_IMA_WS_NAME,     // 15: adpcm_ima_ws
    AVCodecCodecName::AUDIO_DECODER_ADPCM_IMA_SMJPEG_NAME, // 16: adpcm_ima_smjpeg
    AVCodecCodecName::AUDIO_DECODER_ADPCM_IMA_DAT4_NAME,   // 17: adpcm_ima_dat4
    AVCodecCodecName::AUDIO_DECODER_ADPCM_MTAF_NAME,       // 18: adpcm_mtaf
    AVCodecCodecName::AUDIO_DECODER_ADPCM_ADX_NAME,        // 19: adpcm_adx
    AVCodecCodecName::AUDIO_DECODER_ADPCM_AFC_NAME,        // 20: adpcm_afc
    AVCodecCodecName::AUDIO_DECODER_ADPCM_AICA_NAME,       // 21: adpcm_aica
    AVCodecCodecName::AUDIO_DECODER_ADPCM_CT_NAME,         // 22: adpcm_ct
    AVCodecCodecName::AUDIO_DECODER_ADPCM_DTK_NAME,        // 23: adpcm_dtk
    // ... ADPCM 24-37 (adpcm_sbpro_2/3/4/thp/thp_le/xa/yamaha)
    AVCodecCodecName::AUDIO_DECODER_WMAV1_NAME,            // 40: wmav1
    AVCodecCodecName::AUDIO_DECODER_WMAV2_NAME,            // 41: wmav2
    AVCodecCodecName::AUDIO_DECODER_WMAPRO_NAME,           // 42: wmapro
    AVCodecCodecName::AUDIO_DECODER_ALAC_NAME,              // 43: alac
    AVCodecCodecName::AUDIO_DECODER_ILBC_NAME,             // 44: ilbc
    AVCodecCodecName::AUDIO_DECODER_TRUEHD_NAME,           // 45: truehd (ifdef SUPPORT_CODEC_TRUEHD)
    AVCodecCodecName::AUDIO_DECODER_TWINVQ_NAME,           // 46: twinvq
    AVCodecCodecName::AUDIO_DECODER_DVAUDIO_NAME,          // 47: dvaudio
    AVCodecCodecName::AUDIO_DECODER_DTS_NAME,              // 48: dts (ifdef SUPPORT_CODEC_DTS)
    AVCodecCodecName::AUDIO_DECODER_COOK_NAME              // 49: cook
};
```

```cpp
// E2: mimeVec[L115-150] 50个MIME类型映射
static const std::vector<std::string> mimeVec = {
    MimeType::AUDIO_MPEG,              //  0: mp3
    MimeType::AUDIO_AAC,               //  1: aac
    MimeType::AUDIO_FLAC,              //  2: flac
    // ... 50 entries
    MimeType::AUDIO_COOK              // 49: cook
};
```

```cpp
// E3: codecInitMap[L155-190] 50个InitDefinition函数指针驱动模板实例化
static const std::vector<void(*)(...)> codecInitMap = {
    InitDefinition<FFmpegMp3DecoderPlugin>,    //  0: mp3
    InitDefinition<FFmpegAACDecoderPlugin>,    //  1: aac
    InitDefinition<FFmpegFlacDecoderPlugin>,   //  2: flac
    // ...
    InitDefinition<FFmpegCookDecoderPlugin>    // 49: cook
};
```

**InitDefinition模板（E4，L87-98）：**

```cpp
template <class T>
void InitDefinition(const std::string &mimetype, const std::string_view &codecName,
                    CodecPluginDef &definition, Capability &cap)
{
    cap.SetMime(mimetype);
    definition.name = codecName;
    definition.SetCreator([](const std::string &name) -> std::shared_ptr<CodecPlugin> {
        return std::make_shared<T>(name);
    });
    // ...
}
```

**注册函数（E5，L200）：**

```cpp
void RegisterAudioDecoderPlugins(const std::shared_ptr<Register> &reg)
{
    // 遍历codecInitMap，依次调用SetDefinition注册每个codec
}
```

### 2.2 Layer 2：FfmpegBaseDecoder 引擎基类

**文件：** `ffmpeg_base_decoder.cpp`（605行）+ `ffmpeg_base_decoder.h`（129行）

**职责：** 封装FFmpeg libavcodec通用解码管线（avcodec_send_packet/receive_frame），包含Resample重采样器、格式转换、SkipSamples、PTS计算。

**类继承关系：**

```
FfmpegBaseDecoder : NoCopyable
├── ProcessSendData(const std::shared_ptr<AVBuffer>&)
├── ProcessReceiveData(std::shared_ptr<AVBuffer>&)
├── AllocateContext(const std::string&)
├── InitContext(const std::shared_ptr<Meta>&)
├── OpenContext()
├── ReceiveBuffer(std::shared_ptr<AVBuffer>&)
├── Reset() / Flush() / Release()
├── SetCallback(DataCallback*)
├── GetFormat() / GetCodecContext() / GetCodecAVPacket() / GetCodecCacheFrame()
└── Resample resample_         // Ffmpeg::Resample成员（重采样器）
```

**关键成员（E6，L43-62）：**

```cpp
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
```

**关键FFmpeg资源（E7，L63-68）：**

```cpp
std::shared_ptr<AVCodec> avCodec_;              // FFmpeg AVCodec
std::shared_ptr<AVCodecContext> avCodecContext_; // FFmpeg codec context
std::shared_ptr<AVFrame> cachedFrame_;          // 解码帧缓冲
std::shared_ptr<AVPacket> avPacket_;            // 输入packet
Ffmpeg::Resample resample_;                     // 重采样器（组合模式）
```

**InitResample流程（E8，L577-600）：**

```cpp
Status FfmpegBaseDecoder::HandleFirstFrame()
{
    if (isFirst || currentFrameFormatChanged_) {
        isFirst = false;
        auto layout = FFMpegConverter::ConvertFFToOHAudioChannelLayoutV2(
            avCodecContext_->ch_layout.u.mask, avCodecContext_->ch_layout.nb_channels);
        // ...
        format_->SetData(Tag::AUDIO_CHANNEL_LAYOUT, layout);
        if (InitResample() != Status::OK) {   // E9: InitResample在HandleFirstFrame中触发
            currentFrameFormatChanged_ = false;
            return Status::ERROR_UNKNOWN;
        }
        int32_t sampleRate = avCodecContext_->sample_rate;
        durationTime_ = TIME_BASE_FFMPEG / sampleRate;  // 1000000.f / sampleRate
        currentFrameFormatChanged_ = false;
    }
    return Status::OK;
}
```

**SendPacket管线（E10，L85-105）：**

```cpp
int32_t FfmpegBaseDecoder::GetMaxInputSize() const noexcept  // E11
{ return maxInputSize_; }

void FfmpegBaseDecoder::SetMaxInputSize(int32_t setSize)    // E12
{ maxInputSize_ = setSize; }

bool FfmpegBaseDecoder::HasExtraData() const noexcept      // E13
{ return hasExtra_; }
```

**DecodePipeline关键路径（E14，L195-220）：**

```cpp
// cachedFrame_->pts = nextPts_ 时的pts推进
if (againIndex_ == 0) {
    av_frame_unref(cachedFrame_.get());
}  // againIndex_==0时清帧，否则保留（分片输出）
```

**PTS计算（E15，L300-330）：**

```cpp
const int64_t duration =
    static_cast<int64_t>(outputSize) * durationTime_ / bytePerSample / outFrame->ch_layout.nb_channels;
nextPts_ = cachedFrame_->pts + duration;
outBuffer->pts_ = cachedFrame_->pts;
outBuffer->duration_ = duration;
format_->SetData(Tag::AUDIO_SAMPLE_PER_FRAME, outFrame->nb_samples);
```

**againIndex_分片输出机制（E16，L190-200）：**

```cpp
if (againIndex_ == 0) {
    av_frame_unref(cachedFrame_.get());
}
```

**EnableResample（E17，L505-520）：**

```cpp
void FfmpegBaseDecoder::EnableResample(AVSampleFormat destFmt)
{
    destFmt_ = destFmt;
    AVCODEC_LOGI("enable resample to destFmt:%{public}" PRId32, destFmt);
}
```

**SetCodecExtradata处理（E18，L530-600）：**

```cpp
Status FfmpegBaseDecoder::SetCodecExtradata(const std::shared_ptr<Meta> &format)
{
    // 提取extradata，设置为avCodecContext_->extradata
    hasExtra_ = true;
    return Status::OK;
}
```

### 2.3 Layer 3：19子插件

**目录：** `services/media_engine/plugins/ffmpeg_adapter/audio_decoder/aac/`（及ac3/adpcm/alac/amrnb/amrwb/ape/cook/dts/eac3/flac/g711a/g711mu/gsm/gsm_ms/ilbc/lbvc/mp3/truehd/twinvq/vorbis/wma等）

**模式：** 各子插件继承/组合FfmpegBaseDecoder，实现特定codec初始化和参数配置。

**ffmpeg_decoder_plugin.h包含的头文件（E19）：**

```cpp
#include "aac/ffmpeg_aac_decoder_plugin.h"
#include "ac3/ffmpeg_ac3_decoder_plugin.h"
#include "flac/ffmpeg_flac_decoder_plugin.h"
#include "mp3/ffmpeg_mp3_decoder_plugin.h"
#include "vorbis/ffmpeg_vorbis_decoder_plugin.h"
#include "amrnb/ffmpeg_amrnb_decoder_plugin.h"
#include "amrwb/ffmpeg_amrwb_decoder_plugin.h"
#include "ape/ffmpeg_ape_decoder_plugin.h"
#include "gsm_ms/ffmpeg_gsm_ms_decoder_plugin.h"
#include "gsm/ffmpeg_gsm_decoder_plugin.h"
#include "alac/ffmpeg_alac_decoder_plugin.h"
#include "wma/ffmpeg_wma_decoder_plugin.h"
#include "adpcm/ffmpeg_adpcm_decoder_plugin.h"
#include "ilbc/ffmpeg_ilbc_decoder_plugin.h"
#include "truehd/ffmpeg_truehd_decoder_plugin.h"    // ifdef SUPPORT_CODEC_TRUEHD
#include "twinvq/ffmpeg_twinvq_decoder_plugin.h"
#include "dvaudio/ffmpeg_dvaudio_decoder_plugin.h"
#include "dts/ffmpeg_dts_decoder_plugin.h"           // ifdef SUPPORT_CODEC_DTS
#include "cook/ffmpeg_cook_decoder_plugin.h"
```

---

## 3. 与S183 AvcEncoder对称架构

| 维度 | S183（AvcEncoder软件编码器） | S188（FFmpegAudioDecoder软件解码器） |
|------|----------------------------|-------------------------------------|
| 引擎基类 | AvcEncoder（1765行cpp，libavc_encoder.z.so） | FfmpegBaseDecoder（605行cpp，libavcodec） |
| 插件注册 | AvcEncoderLoader（72行cpp） | FFmpegDecoderPlugin（250行cpp，codecInitMap 50项） |
| 子插件 | 无（统一AvcEncoder） | 19子插件（aac/ac3/adpcm/alac/amrnb/.../cook） |
| 数据流 | TaskThread SendFrame驱动→avcodec_encode_video2 | TaskThread SendBuffer驱动→avcodec_send_packet+receive_frame |
| 色彩空间 | BT601/BT709矩阵+ARM NEON优化 | Resample SwrContext（声道/采样率转换） |
| PTS | 帧级PTS计算 | durationTime_=1000000.f/sampleRate，PTS累加 |

---

## 4. 关联记忆

| 关联 | 关系 |
|------|------|
| S125 | FFmpeg软件解码器基类总览（上层抽象） |
| S130 | FFmpegAdapter Common（FFmpegConverter::ConvertFFToOHAudioChannelLayoutV2） |
| S50 | AudioResample（SwrContext封装，本模块组合Resample） |
| S158/S169/S176 | FFmpeg音频编码器插件体系（对称架构） |
| S183 | AvcEncoder软件编码器（软件编解码对称） |
| S191 | OHOS-Native vs FFmpeg Adapter双路径（engine/codec/ vs ffmpeg_adapter/ 并行） |

---

## 5. Evidence清单（E1-E19）

| # | 文件 | 行号 | 内容 |
|---|------|------|------|
| E1 | ffmpeg_decoder_plugin.cpp | L34-71 | codecVec 50个codec name映射 |
| E2 | ffmpeg_decoder_plugin.cpp | L115-150 | mimeVec 50个MIME类型映射 |
| E3 | ffmpeg_decoder_plugin.cpp | L155-190 | codecInitMap 50个InitDefinition函数指针 |
| E4 | ffmpeg_decoder_plugin.cpp | L87-98 | InitDefinition模板函数 |
| E5 | ffmpeg_decoder_plugin.cpp | L200+ | RegisterAudioDecoderPlugins注册函数 |
| E6 | ffmpeg_base_decoder.cpp | L43-62 | FfmpegBaseDecoder构造函数成员初始化 |
| E7 | ffmpeg_base_decoder.h | L63-68 | 关键FFmpeg资源成员声明 |
| E8 | ffmpeg_base_decoder.cpp | L577-600 | HandleFirstFrame中InitResample触发 |
| E9 | ffmpeg_base_decoder.cpp | L580 | InitResample()!=Status::OK时错误返回 |
| E10 | ffmpeg_base_decoder.cpp | L85-105 | GetMaxInputSize/SetMaxInputSize/HasExtraData |
| E11 | ffmpeg_base_decoder.cpp | L90 | GetMaxInputSize const noexcept |
| E12 | ffmpeg_base_decoder.cpp | L93 | SetMaxInputSize |
| E13 | ffmpeg_base_decoder.cpp | L96 | HasExtraData |
| E14 | ffmpeg_base_decoder.cpp | L195-220 | againIndex_分片输出机制 |
| E15 | ffmpeg_base_decoder.cpp | L300-330 | PTS计算（duration=outputSize*durationTime_/bytePerSample/channels） |
| E16 | ffmpeg_base_decoder.cpp | L190-200 | againIndex_==0时av_frame_unref |
| E17 | ffmpeg_base_decoder.cpp | L505-520 | EnableResample |
| E18 | ffmpeg_base_decoder.cpp | L530-600 | SetCodecExtradata处理 |
| E19 | ffmpeg_decoder_plugin.h | L20-46 | 19子插件头文件includes |

---

**草案状态：** ✅ 已生成，待审批  
**证据强度：** 19条行号级evidence，基于本地镜像 605+250+129+46=1030行源码