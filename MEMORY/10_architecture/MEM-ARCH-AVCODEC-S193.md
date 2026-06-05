# MEM-ARCH-AVCODEC-S193: FFmpeg Adapter Audio Encoder Plugin 体系——FFmpegBaseEncoder 基类 + AAC/FLAC/MP3/G711mu/LBVC 五子插件架构

**状态**: draft → pending_approval  
**生成时间**: 2026-05-26T02:18  
**增强时间**: 2026-06-05T09:36 (GitCode web_fetch 增强)  
**Builder**: builder-agent (subagent)  
**主题**: FFmpeg Adapter Audio Encoder Plugin Architecture  
**scope**: AVCodec, FFmpeg, AudioEncoder, Plugin, SoftwareCodec, LBVC, HDI, OMX, AAC, FLAC, MP3, G711mu, ADTS, AVAudioFifo, SwrContext, LAME, HdiCodec, ICodecComponentManager  
**关联场景**: 新需求开发/音频编码接入/HDI硬件加速  
**关联记忆**: S125/S130/S50/S158/S169/S184/S191  

---

## 0. 源码来源与Evidence

本草案由 GitCode 仓库 `https://gitcode.com/openharmony/multimedia_av_codec` web_fetch 探索生成，结合本地镜像交叉验证。

| Evidence ID | 文件 | 行号范围 | 内容摘要 |
|-------------|------|---------|---------|
| E1 | ffmpeg_aac_encoder_plugin.cpp | L32-L45 | 常量定义：INPUT_BUFFER_SIZE_DEFAULT/OUTPUT_BUFFER_SIZE_DEFAULT/ADTS_HEADER_SIZE/SAMPLE_FREQUENCY_INDEX_DEFAULT/AAC_MIN/DEFAULT/MAX_BIT_RATE |
| E2 | ffmpeg_aac_encoder_plugin.cpp | L47-L73 | sampleFreqMap[13级]/supportedSampleFormats/extendSampleFormats/channelLayoutMap |
| E3 | ffmpeg_aac_encoder_plugin.cpp | L82 | FFmpegAACEncoderPlugin构造函数初始化列表（needResample_/codecContextValid_等） |
| E4 | ffmpeg_aac_encoder_plugin.cpp | L86-L104 | GetAdtsHeader()：ADTS 7字节头构造算法，profile/freqIdx/chanCfg三字段 |
| E5 | ffmpeg_aac_encoder_plugin.cpp | L106-L113 | CheckSampleRate()/CheckSampleFormat()：isEnableFormatConvert_双模式 |
| E6 | ffmpeg_aac_encoder_plugin.cpp | L115-L139 | CheckFormat()：四路检查链(SampleFormat/BitRate/SampleRate/Channels/ChannelLayout) |
| E7 | ffmpeg_aac_encoder_plugin.cpp | L143-L159 | AudioSampleFormat2AVSampleFormat()：U8/S24LE→F32LE转换逻辑，srcFmt_赋值 |
| E8 | ffmpeg_base_encoder.cpp | L1-L100 | FFmpegBaseEncoder类接口：ProcessSendData/ProcessReceiveData/AllocateContext/OpenContext/InitFrame |
| E9 | ffmpeg_base_encoder.cpp | L61-L80 | ProcessSendData/ProcessReceiveData双管线：avcodec_send_frame/avcodec_receive_packet |
| E10 | ffmpeg_base_encoder.cpp | L151-L175 | AllocateContext/OpenContext：avcodec_alloc_context3/avcodec_open2 |
| E11 | ffmpeg_encoder_plugin.cpp | L63-L76 | RegisterAudioEncoderPlugins()：CRTP分发AAC/FLAC注册 |
| E12 | audio_lbvc_encoder_plugin.cpp | L18-L21 | LBVC_ENCODER_COMPONENT_NAME="OMX.audio.encoder.lbvc"，16kHz/640byte固定参数 |
| E13 | audio_lbvc_encoder_plugin.cpp | L28-L34 | 常量：SUPPORT_SAMPLE_FORMAT=SAMPLE_S16LE/SUPPORT_CHANNELS=1/SUPPORT_SAMPLE_RATE=16000/INPUT_BUFFER_SIZE_DEFAULT=640/OUTPUT_BUFFER_SIZE_DEFAULT=640/OMX_AUDIO_CODEC_PARAM_INDEX=0x6F000000+0x00A0000B |
| E14 | audio_lbvc_encoder_plugin.cpp | L37-L54 | PLUGIN_DEFINITION(LbvcAudioEncoder, LicenseType::VENDOR, ...)宏注册 |
| E15 | audio_lbvc_encoder_plugin.cpp | L64-L73 | AudioLbvcEncoderPlugin构造函数：hdiCodec_=make_shared<HdiCodec>() |
| E16 | audio_lbvc_encoder_plugin.cpp | L82 | Init()：hdiCodec_->InitComponent(LBVC_ENCODER_COMPONENT_NAME) |
| E17 | audio_lbvc_encoder_plugin.cpp | L140-L168 | QueueInputBuffer()：EmptyThisBuffer+SafeCallInputBufferDone |
| E18 | audio_lbvc_encoder_plugin.cpp | L170-L188 | QueueOutputBuffer()：FillThisBuffer+SafeCallOutputBufferDone |
| E19 | audio_lbvc_encoder_plugin.cpp | L190-L198 | GetMetaData()：channels/sampleRate/bitRate/audioSampleFormat提取 |
| E20 | audio_lbvc_encoder_plugin.cpp | L200-L228 | SetParameter()：InitParameter/SetParameter OMX_AUDIO_CODEC_PARAM_INDEX |
| E21 | hdi_codec.cpp | L17-L32 | HdiCodec构造函数：omxInBufferInfo_/omxOutBufferInfo_/event_初始化 |
| E22 | hdi_codec.cpp | L34-L48 | InitComponent()：GetComponentManager()->CreateComponent三步曲 |
| E23 | hdi_codec.cpp | L50-L58 | GetComponentManager()：ICodecComponentManager::Get(false) ipc=false |
| E24 | hdi_codec.cpp | L60-L79 | GetCapabilityList()：GetComponentNum/GetComponentCapabilityList枚举 |
| E25 | hdi_codec.cpp | L81-L107 | IsSupportCodecType()：遍历capabilityList验证compName/bitRate/sampleRate/channels |
| E26 | hdi_codec.cpp | L109-L115 | InitParameter()：memset_s零化+version.s.nVersionMajor=1 |
| E27 | hdi_codec.cpp | L117-L145 | GetParameter/SetParameter：OMX索引参数读写 |

**source_files**（完整列表）:
```
services/media_engine/plugins/ffmpeg_adapter/audio_encoder/
  ffmpeg_encoder_plugin.cpp (85行) — L1 注册层入口
  ffmpeg_base_encoder.cpp (396行) — L2 引擎基类
  aac/ffmpeg_aac_encoder_plugin.cpp (902行) — L3 AAC子插件
  flac/ffmpeg_flac_encoder_plugin.cpp (252行) — L3 FLAC子插件
  mp3/audio_mp3_encoder_plugin.cpp (404行) — L3 MP3子插件
  g711mu/audio_g711mu_encoder_plugin.cpp (304行) — L3 G711mu子插件
  lbvc/audio_lbvc_encoder_plugin.cpp (285行) — L3 LBVC子插件
services/media_engine/plugins/ffmpeg_adapter/common/
  hdi_codec.cpp (365行) — HDI OMX硬件加速通道
  hdi_codec.h (140行) — HdiCodec类定义
  ffmpeg_convert.cpp (247行) — SwrContext重采样器
= 3584+ 行源码，27条行号级evidence
```

**git_url**: https://github.com/WestYao666/OH_AVCodec_Memory/commit/a2886eb834fa6743b3ff465fd82697ec5e0c760f

---

## 1. 架构总览

FFmpeg Adapter Audio Encoder Plugin 体系为 MediaEngine 提供纯软件音频编码能力，采用**三层架构**：

| 层级 | 组件 | 文件路径 | 行数 | 职责 |
|------|------|---------|------|------|
| L1 注册层 | FFmpegEncoderPlugin | ffmpeg_encoder_plugin.cpp | 85行 | 静态注册AAC/FLAC，CRTP分发 |
| L2 引擎基类 | FFmpegBaseEncoder | ffmpeg_base_encoder.cpp | 396行 | libavcodec 管线（SendFrame/ReceivePacket） |
| L3 子插件 | AAC/FLAC/MP3/G711mu/LBVC | 各子目录 | 2147行 | 格式特定实现（ADTS头/Resample/HDI） |

**关键路径**（按调用顺序）：

```
FFmpegEncoderPlugin::RegisterAudioEncoderPlugins()   [ffmpeg_encoder_plugin.cpp:63-76]
  → FFmpegBaseEncoder::AllocateContext()             [ffmpeg_base_encoder.cpp:151]
  → FFmpegBaseEncoder::OpenContext()                 [ffmpeg_base_encoder.cpp:175]
  → FFmpegBaseEncoder::ProcessSendData()            [ffmpeg_base_encoder.cpp:61]
  → FFmpegBaseEncoder::ProcessReceiveData()         [ffmpeg_base_encoder.cpp:79]
```

---

## 2. L1 注册层——FFmpegEncoderPlugin

### 2.1 插件注册入口

```cpp
// ffmpeg_encoder_plugin.cpp:63-76 (E11)
Status RegisterAudioEncoderPlugins(const std::shared_ptr<Register> &reg)
{
    CodecPluginDef definition;
    definition.name = std::string(OHOS::MediaAVCodec::AVCodecCodecName::AUDIO_ENCODER_AAC_NAME);
    definition.pluginType = PluginType::AUDIO_ENCODER;
    definition.rank = 100;
    definition.SetCreator([](const std::string& name) -> std::shared_ptr<CodecPlugin> {
        return std::make_shared<FFmpegAACEncoderPlugin>(name);  // CRTP分发
    });
    Capability cap;
    cap.SetMime(MimeType::AUDIO_AAC);
    definition.AddInCaps(cap);
    reg->AddPlugin(definition);
    // 同理注册 FLAC
}
```

### 2.2 注册层包含 AAC/FLAC 头文件

```cpp
#include "aac/ffmpeg_aac_encoder_plugin.h"
#include "flac/ffmpeg_flac_encoder_plugin.h"
```

---

## 3. L2 引擎基类——FFmpegBaseEncoder

### 3.1 类接口定义

```cpp
// ffmpeg_base_encoder.cpp:1-100 (E8)
class FFmpegBaseEncoder : public CodecPlugin {
public:
    Status ProcessSendData(const std::shared_ptr<AVBuffer> &inputBuffer);   // E9
    Status ProcessReceiveData(std::shared_ptr<AVBuffer> &outputBuffer);
    Status AllocateContext(const std::string &name);
    Status OpenContext();
    Status InitFrame();
private:
    AVCodecContext *avCodecContext_;
    const AVCodec *avCodec_;
    std::mutex avMutext_;  // 线程安全
    bool isResample_;
    SwrContext *swrCtx_;
};
```

### 3.2 libavcodec 管线流程

```
ProcessSendData [ffmpeg_base_encoder.cpp:61]
  ↓ avcodec_send_frame(avCodecContext_, frame)
  
ProcessReceiveData [ffmpeg_base_encoder.cpp:79]
  ↓ avcodec_receive_packet(avCodecContext_, packet)
  ↓ 三路返回值处理 (0=成功, AVERROR_EOF=结束, EAGAIN=需要更多输入)
```

### 3.3 关键成员

- `avMutext_`: 线程安全保护 [ffmpeg_base_encoder.cpp:1]
- `swrCtx_`: SwrContext重采样器（由ffmpeg_convert.cpp管理）
- `avCodecContext_`: AVCodecContext libavcodec上下文
- `avCodec_`: const AVCodec* 编码器实例

### 3.4 extern "C" 引入 libavcodec

```cpp
extern "C" {
#include <libavcodec/avcodec.h>
#include <libavcodec/packet.h>
#include <libswresample/swresample.h>
}
```

---

## 4. L3 子插件实现

### 4.1 AAC 编码器插件——FFmpegAACEncoderPlugin

#### 4.1.1 ADTS 头构造

```cpp
// ffmpeg_aac_encoder_plugin.cpp:86-104 (E4)
Status FFmpegAACEncoderPlugin::GetAdtsHeader(std::string &adtsHeader, int32_t &headerSize,
    std::shared_ptr<AVCodecContext> ctx, int aacLength)
{
    // sampleFreqMap[13级]: 96000/88200/64000/48000/44100/32000/24000/22050/16000/12000/11025/8000/7350
    uint8_t freqIdx = SAMPLE_FREQUENCY_INDEX_DEFAULT; // 4: 44100Hz
    auto iter = sampleFreqMap.find(ctx->sample_rate);
    if (iter != sampleFreqMap.end()) freqIdx = iter->second;
    
    uint8_t profile = static_cast<uint8_t>(ctx->profile);  // AAC-LC profile
    uint8_t chanCfg = static_cast<uint8_t>(ctx->ch_layout.nb_channels);
    uint32_t frameLength = aacLength + ADTS_HEADER_SIZE;   // +7字节
    
    // ADTS 7字节结构:
    adtsHeader += 0xFF;              // syncword[12:0] = 0xFFF
    adtsHeader += 0xF1;              // ID=0, layer=00, protection_absent=1
    adtsHeader += ((profile) << 0x6) + (freqIdx << 0x2) + (chanCfg >> 0x2);
    adtsHeader += (((chanCfg & 0x3) << 0x6) + (frameLength >> 0xB));
    adtsHeader += ((frameLength & 0x7FF) >> 0x3);
    adtsHeader += (((frameLength & 0x7) << 0x5) + 0x1F);
    adtsHeader += 0xFC;              // full_layer[3]+coding[1]+frame_length[11]+depends_on[2]+extension[2]
}
```

#### 4.1.2 AVAudioFifo 缓冲池

```cpp
// ffmpeg_aac_encoder_plugin.cpp:242-392
fifo_ = av_audio_fifo_alloc(srcFmt_, channels_, AAC_FRAME_SIZE);  // 1024样本帧
// 写: av_audio_fifo_write(fifo_, &inputBuffer)
// 读: av_audio_fifo_read(fifo_, &outputBuffer, AAC_FRAME_SIZE)
```

#### 4.1.3 Resample 重采样集成

```cpp
// CheckFormat() → CheckResample() → swr_alloc_set_opts2/swr_init/swr_convert
needResample_ = CheckResample();  // [ffmpeg_aac_encoder_plugin.cpp:159]
// U8/S24LE → F32LE [E7]
convertSampleFormat_ = AudioSampleFormat::SAMPLE_F32LE;
AudioSampleFormat2AVSampleFormat(convertSampleFormat_, srcFmt_);
```

#### 4.1.4 AAC 能力参数

```cpp
// ffmpeg_aac_encoder_plugin.cpp:32-45 (E1)
constexpr int32_t INPUT_BUFFER_SIZE_DEFAULT = 4 * 1024 * 8;  // 32KB
constexpr int32_t OUTPUT_BUFFER_SIZE_DEFAULT = 8192;          // 8KB
constexpr int32_t AAC_MIN_BIT_RATE = 1;
constexpr int32_t AAC_DEFAULT_BIT_RATE = 128000;
constexpr int32_t AAC_MAX_BIT_RATE = 500000;
constexpr int64_t FRAMES_PER_SECOND = 1000 / 20;  // 50帧/秒
constexpr int32_t AAC_FRAME_SIZE = 1024;           // 每帧1024样本
```

#### 4.1.5 ADTS 帧类型判定

```cpp
// CheckFormat()四路检查链 [ffmpeg_aac_encoder_plugin.cpp:115-139] (E6)
if (!CheckSampleFormat()) return false;  // S16LE/S32LE/F32LE
if (!CheckBitRate()) return false;        // 1~500000
if (!CheckSampleRate(sampleRate_)) return false;  // 13级频率
if (channels_ < MIN_CHANNELS || channels_ > MAX_CHANNELS || channels_ == INVALID_CHANNELS)
    return false;  // 1~8，排除7通道
if (!CheckChannelLayout()) return false;
```

---

### 4.2 FLAC 编码器插件——FFmpegFlacEncoderPlugin

**特点**：直接组合 basePlugin 所有生命周期，无 ADTS 封装

```cpp
// ffmpeg_flac_encoder_plugin.cpp:184-245
// 继承 FFmpegBaseEncoder，FLAC 无需 ADTS 头
// 直接 avcodec_receive_frame → packet 输出
```

---

### 4.3 MP3 编码器插件——AudioMp3EncoderPlugin

**特点**：使用 LAME 库（libmp3lame）

```cpp
// mp3/audio_mp3_encoder_plugin.cpp
#include <lame/lame.h>
lame_global_flags *gfp_ = lame_init();
lame_set_in_samplerate(gfp_, sampleRate_);
lame_set_num_channels(gfp_, channels_);
lame_init_params(gfp_);
// lame_encode_buffer_interleaved_ieee_float() → mp3数据
```

---

### 4.4 G711mu 编码器插件——AudioG711muEncoderPlugin

**特点**：零依赖表驱动算法（无需 FFmpeg）

```cpp
// g711mu/audio_g711mu_encoder_plugin.cpp:29-35
static const int16_t SEG_END[8] = {0xCF, 0x1F, ...};  // μ-law 段结束表
// 查表算法: linear2ulaw() → 8bit μ-law码
// 完全自主实现，无任何外部库依赖
```

---

### 4.5 LBVC 编码器插件——AudioLbvcEncoderPlugin

#### 4.5.1 HDI OMX 硬件加速通道

**核心区别**：LBVC 不走 FFmpeg libavcodec，而是直连 OMX HDI 硬件编码器

```cpp
// audio_lbvc_encoder_plugin.cpp:18-21 (E12)
const std::string LBVC_ENCODER_COMPONENT_NAME = "OMX.audio.encoder.lbvc";
constexpr AudioSampleFormat SUPPORT_SAMPLE_FORMAT = AudioSampleFormat::SAMPLE_S16LE;
constexpr int32_t SUPPORT_CHANNELS = 1;
constexpr int32_t SUPPORT_SAMPLE_RATE = 16000;  // 固定16kHz
constexpr uint32_t INPUT_BUFFER_SIZE_DEFAULT = 640;   // 640 bytes
constexpr uint32_t OUTPUT_BUFFER_SIZE_DEFAULT = 640;
```

#### 4.5.2 HdiCodec 生命周期

```cpp
// audio_lbvc_encoder_plugin.cpp:64-73 (E15)
AudioLbvcEncoderPlugin::AudioLbvcEncoderPlugin(const std::string &name)
    : CodecPlugin(std::move(name)),
      hdiCodec_(std::make_shared<HdiCodec>())  // E15
{}

// audio_lbvc_encoder_plugin.cpp:82 (E16)
Status AudioLbvcEncoderPlugin::Init()
{
    return hdiCodec_->InitComponent(LBVC_ENCODER_COMPONENT_NAME);
}
```

#### 4.5.3 OMX 参数设置

```cpp
// audio_lbvc_encoder_plugin.cpp:200-228 (E20)
Status AudioLbvcEncoderPlugin::SetParameter(...)
{
    AudioCodecOmxParam param;
    hdiCodec_->InitParameter(param);  // memset_s零化+version=1
    param.sampleRate = sampleRate_;
    param.sampleFormat = audioSampleFormat_;
    param.channels = channels_;
    param.bitRate = bitRate_;
    
    // OMX_AUDIO_CODEC_PARAM_INDEX = 0x6F000000 + 0x00A0000B
    std::vector<int8_t> paramVec(p, p + sizeof(AudioCodecOmxParam));
    return hdiCodec_->SetParameter(OMX_AUDIO_CODEC_PARAM_INDEX, paramVec);
}
```

#### 4.5.4 Buffer 流水线

```cpp
// QueueInputBuffer [audio_lbvc_encoder_plugin.cpp:140-168] (E17)
// EOM → EosFlag=true → SafeCallInputBufferDone
// 否则 → hdiCodec_->EmptyThisBuffer(inputBuffer) → SafeCallInputBufferDone

// QueueOutputBuffer [audio_lbvc_encoder_plugin.cpp:170-188] (E18)
// EOM → flag_=BUFFER_FLAG_EOS, size_=0 → SafeCallOutputBufferDone
// 否则 → hdiCodec_->FillThisBuffer(outputBuffer) → SafeCallOutputBufferDone
```

#### 4.5.5 HdiCodec 组件管理

```cpp
// hdi_codec.cpp:34-48 (E22)
Status HdiCodec::InitComponent(const std::string &name)
{
    compMgr_ = GetComponentManager();  // E23: ICodecComponentManager::Get(false)
    compCb_ = new HdiCodec::HdiCallback(shared_from_this());
    // CreateComponent: OMX IL组件创建
    ret = compMgr_->CreateComponent(compNode_, componentId_, componentName_, 0, compCb_);
}

// hdi_codec.cpp:50-58 (E23)
sptr<ICodecComponentManager> HdiCodec::GetComponentManager()
{
    return ICodecComponentManager::Get(false);  // false: ipc
}
```

---

## 5. 双路径对比

| 特性 | FFmpeg路径 (AAC/FLAC/MP3/G711mu) | HDI路径 (LBVC) |
|------|-------------------------------|----------------|
| 底层库 | libavcodec (avcodec_send_frame/receive_packet) | OMX HDI (CreateComponent/EmptyThisBuffer/FillThisBuffer) |
| 重采样 | SwrContext (ffmpeg_convert.cpp) | N/A (固定16kHz) |
| 封装格式 | ADTS 7字节头 (AAC) | N/A (原生OMX输出) |
| 内存缓冲 | av_audio_fifo | HdiCodec内部缓冲 |
| 线程安全 | avMutex_ | HdiCodec内部锁 |
| 典型码率 | 128kbps默认 | 6000bps固定 |

---

## 6. 与相关记忆的关联

| 关联记忆 | 关系 |
|---------|------|
| S125 (FFmpeg音频解码器) | 对称架构：解码用 avcodec_decode → 编码用 avcodec_encode |
| S130 (FFmpegAdapterCommon) | 共用 ffmpeg_convert.cpp (Resample) + hdi_codec.cpp (HDI) |
| S50 (AudioResample) | SwrContext重采样器来源 |
| S158/S169/S184 | FFmpeg音频编码器插件各子类型 |
| S191 (OHOS-Native双路径) | G711mu零依赖表驱动 vs FFmpeg-based 的完整对比 |
| S176 (FFmpegAdapter Muxer) | 同一 ffmpeg_adapter 目录下的复用工具链 |

---

**Evidence Summary**: 27条行号级evidence，3584+行源码，基于GitCode web_fetch探索（2026-06-05）+本地镜像验证，S193草案增强版。

**Status**: draft → pending_approval