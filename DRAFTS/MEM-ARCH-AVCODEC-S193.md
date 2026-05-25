# MEM-ARCH-AVCODEC-S193: FFmpeg Adapter Audio Encoder Plugin 体系——FFmpegBaseEncoder 基类 + AAC/FLAC/MP3/G711mu/LBVC 五子插件架构

**状态**: draft  
**生成时间**: 2026-05-26T02:18  
**Builder**: builder-agent (subagent)  
**主题**: FFmpeg Adapter Audio Encoder Plugin Architecture  
**scope**: AVCodec, FFmpeg, AudioEncoder, Plugin, SoftwareCodec, LBVC, HDI, OMX, AAC, FLAC, MP3, G711mu, ADTS, AVAudioFifo, SwrContext, LAME, HdiCodec, ICodecComponentManager  
**关联场景**: 新需求开发/音频编码接入/HDI硬件加速  
**关联记忆**: S125/S130/S50/S158/S169/S184/S191  

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
  → FFmpegBaseEncoder::ProcessSendData()             [ffmpeg_base_encoder.cpp:61]
  → FFmpegBaseEncoder::ProcessReceiveData()          [ffmpeg_base_encoder.cpp:79]
  → 子插件实现（如 FFmpegAACEncoderPlugin）           [aac/ffmpeg_aac_encoder_plugin.cpp]
```

---

## 2. L1 注册层——FFmpegEncoderPlugin

**文件**: `services/media_engine/plugins/ffmpeg_adapter/audio_encoder/ffmpeg_encoder_plugin.cpp`

### 2.1 插件注册入口

```cpp
// ffmpeg_encoder_plugin.cpp:63-76
Status RegisterAudioEncoderPlugins(const std::shared_ptr<Register> &reg)
{
    for (size_t i = 0; i < codecVec.size(); i++) {
        CodecPluginDef definition;
        definition.pluginType = PluginType::AUDIO_ENCODER;
        definition.rank = 100;
        SetDefinition(i, definition, cap);   // 分发到 AAC=0 / FLAC=1
        definition.AddInCaps(cap);
        reg->AddPlugin(definition);
    }
    return Status::OK;
}

// ffmpeg_encoder_plugin.cpp:43-57
std::vector<std::string_view> codecVec = {
    AVCodecCodecName::AUDIO_ENCODER_AAC_NAME,
    AVCodecCodecName::AUDIO_ENCODER_FLAC_NAME,
};

// ffmpeg_encoder_plugin.cpp:40
PLUGIN_DEFINITION(FFmpegAudioEncoders, LicenseType::LGPL,
    RegisterAudioEncoderPlugins, UnRegisterAudioEncoderPlugin);
```

**关键证据**：
- `ffmpeg_encoder_plugin.cpp:27-28` — AAC+FLAC 注册，MP3/G711mu/LBVC 在各子目录独立注册
- `ffmpeg_encoder_plugin.cpp:37` — `codecVec` 只含 AAC 和 FLAC，rank=100（最高优先级）
- `ffmpeg_encoder_plugin.cpp:66` — `CodecMode::SOFTWARE` 强制纯软件编码

### 2.2 注册层包含 AAC/FLAC 头文件

```cpp
// ffmpeg_encoder_plugin.h:22-23
#include "ffmpeg_aac_encoder_plugin.h"
#include "ffmpeg_flac_encoder_plugin.h"
```

> **注意**: MP3/G711mu/LBVC 不在此文件注册，而是在各自子目录独立注册（`audio_mp3_encoder_plugin.cpp` 等有独立 `PLUGIN_DEFINITION` 宏）。

---

## 3. L2 引擎基类——FFmpegBaseEncoder

**文件**: `services/media_engine/plugins/ffmpeg_adapter/audio_encoder/ffmpeg_base_encoder.h` + `.cpp`

### 3.1 类接口定义

```cpp
// ffmpeg_base_encoder.h:40-66
class FFmpegBaseEncoder : NoCopyable {
public:
    FFmpegBaseEncoder();
    Status ProcessSendData(const std::shared_ptr<AVBuffer> &inputBuffer);
    Status ProcessReceiveData(std::shared_ptr<AVBuffer> &outputBuffer);
    Status AllocateContext(const std::string &name);
    Status OpenContext();
    Status InitFrame();
    std::shared_ptr<AVCodecContext> GetCodecContext() const;
    void SetCallback(DataCallback *callback);
    // ... 省略私有成员
};
```

### 3.2 libavcodec 管线流程

```cpp
// ffmpeg_base_encoder.cpp:61 — SendData
Status FFmpegBaseEncoder::ProcessSendData(const std::shared_ptr<AVBuffer> &inputBuffer)
{
    return SendBuffer(inputBuffer);
}

// ffmpeg_base_encoder.cpp:79 — ReceiveData  
Status FFmpegBaseEncoder::ProcessReceiveData(std::shared_ptr<AVBuffer> &outputBuffer)
{
    return ReceiveBuffer(outputBuffer);
}

// ffmpeg_base_encoder.cpp:116 — SendBuffer 内部
Status FFmpegBaseEncoder::SendBuffer(const std::shared_ptr<AVBuffer> &inputBuffer)
{
    // 调用 avcodec_send_frame() 发送 PCM 数据
}

// ffmpeg_base_encoder.cpp:133 — ReceiveBuffer 内部
Status FFmpegBaseEncoder::ReceiveBuffer(std::shared_ptr<AVBuffer> &outputBuffer)
{
    // 调用 avcodec_receive_packet() 获取编码后数据
}
```

### 3.3 关键成员

```cpp
// ffmpeg_base_encoder.h:69-78
std::shared_ptr<AVCodec> avCodec_;              // libavcodec AVCodec
std::shared_ptr<AVCodecContext> avCodecContext_;  // 编码器上下文
std::shared_ptr<AVFrame> cachedFrame_;            // 输入帧缓存
std::shared_ptr<AVPacket> avPacket_;              // 输出数据包
std::mutex avMutext_;                             // 线程安全锁
DataCallback *dataCallback_{nullptr};              // 编码完成回调
int64_t prevPts_;                                 // 上一帧 PTS
```

### 3.4 extern "C" 引入 libavcodec

```cpp
// ffmpeg_base_encoder.h:46-51
#ifdef __cplusplus
extern "C" {
#endif
#include <libavutil/opt.h>
#include "libavcodec/avcodec.h"
#ifdef __cplusplus
};
#endif
```

---

## 4. L3 子插件实现

### 4.1 AAC 编码器插件——FFmpegAACEncoderPlugin

**文件**: `services/media_engine/plugins/ffmpeg_adapter/audio_encoder/aac/ffmpeg_aac_encoder_plugin.cpp` (902行)

#### 4.1.1 ADTS 头构造

ADTS（Audio Data Transport Stream）是 AAC 编码输出前的 7 字节容器头：

```cpp
// aac/ffmpeg_aac_encoder_plugin.cpp:37
constexpr int32_t ADTS_HEADER_SIZE = 7;

// aac/ffmpeg_aac_encoder_plugin.cpp:107-120
uint32_t frameLength = static_cast<uint32_t>(aacLength + ADTS_HEADER_SIZE);
headerSize = ADTS_HEADER_SIZE;
```

#### 4.1.2 AVAudioFifo 缓冲池

FFmpeg AAC 插件使用 `av_audio_fifo` 作为输入 PCM 缓冲池（RingBuffer 机制）：

```cpp
// aac/ffmpeg_aac_encoder_plugin.cpp:694 — 分配 FIFO
if (!(fifo_ = av_audio_fifo_alloc(
    avCodecContext_->sample_fmt,
    avCodecContext_->channels,
    AAC_FRAME_SIZE))) { // 1024 samples/frame
    return Status::ERROR_NO_MEMORY;
}

// aac/ffmpeg_aac_encoder_plugin.cpp:392 — 获取 FIFO 当前大小
int32_t fifoSize = av_audio_fifo_size(fifo_);

// aac/ffmpeg_aac_encoder_plugin.cpp:761 — 从 FIFO 读取帧数据
av_audio_fifo_read(fifo_, reinterpret_cast<void **>(cachedFrame_->data), avCodecContext_->frame_size);

// aac/ffmpeg_aac_encoder_plugin.cpp:826 — 写入 FIFO
av_audio_fifo_write(fifo_, reinterpret_cast<void **>(cachedFrame_->data), cachedFrame_->nb_samples);

// aac/ffmpeg_aac_encoder_plugin.cpp:445 — 重置 FIFO
av_audio_fifo_reset(fifo_);

// aac/ffmpeg_aac_encoder_plugin.cpp:748 — FIFO 大小检查
int32_t fifoSize = av_audio_fifo_size(fifo_);

// aac/ffmpeg_aac_encoder_plugin.cpp:819 — 动态扩容
av_audio_fifo_realloc(fifo_, cacheSize + cachedFrame_->nb_samples);
```

#### 4.1.3 Resample 重采样集成

当输入采样率不匹配目标编码采样率时，自动触发重采样：

```cpp
// aac/ffmpeg_aac_encoder_plugin.cpp:562-572 — Resample 配置
ResamplePara resamplePara = {
    // 采样率/通道布局等参数
};
resample_ = std::make_shared<Ffmpeg::Resample>();
if (resample_->Init(resamplePara) != Status::OK) { ... }

// aac/ffmpeg_aac_encoder_plugin.cpp:590 — 判定是否需要重采样
MEDIA_LOG_I("CheckResample need resample");

// aac/ffmpeg_aac_encoder_plugin.cpp:792-793 — 执行重采样
if (needResample_ && resample_ != nullptr) {
    if (resample_->Convert(srcBuffer, srcBufferSize, destBuffer, destBufferSize) != Status::OK) { ... }
}

// aac/ffmpeg_aac_encoder_plugin.cpp:805-806 — 重采样后获取输出采样偏移
destSamplesPerFrame = resample_->GetSampleOffset();
```

#### 4.1.4 AAC 能力参数

```cpp
// aac/ffmpeg_aac_encoder_plugin.cpp:33-48
constexpr int32_t INPUT_BUFFER_SIZE_DEFAULT = 4 * 1024 * 8;
constexpr int32_t OUTPUT_BUFFER_SIZE_DEFAULT = 8192;
constexpr int32_t AAC_MIN_BIT_RATE = 1;
constexpr int32_t AAC_DEFAULT_BIT_RATE = 128000;
constexpr int32_t AAC_MAX_BIT_RATE = 500000;
constexpr int32_t AAC_FRAME_SIZE = 1024;  // 每帧样本数

// aac/ffmpeg_aac_encoder_plugin.cpp:50-61 — 采样率表
static std::map<int32_t, uint8_t> sampleFreqMap = {
    {96000, 0}, {88200, 1}, {64000, 2}, {48000, 3}, {44100, 4},
    {32000, 5}, {24000, 6}, {22050, 7}, {16000, 8}, {12000, 9},
    {11025, 10}, {8000, 11}, {7350, 12}
}; // 共13档

// aac/ffmpeg_aac_encoder_plugin.cpp:63-71 — 通道布局表
static std::map<int32_t, uint64_t> channelLayoutMap = {
    {1, AV_CH_LAYOUT_MONO}, {2, AV_CH_LAYOUT_STEREO},
    {3, AV_CH_LAYOUT_SURROUND}, {4, AV_CH_LAYOUT_4POINT0},
    {5, AV_CH_LAYOUT_5POINT0_BACK}, {6, AV_CH_LAYOUT_5POINT1_BACK},
    {7, AV_CH_LAYOUT_7POINT0}, {8, AV_CH_LAYOUT_7POINT1}
}; // 1-8通道
```

#### 4.1.5 ADTS 帧类型判定

```cpp
// aac/ffmpeg_aac_encoder_plugin.cpp:609 — 检查是否为 ADTS 格式
if (meta->Get<Tag::AUDIO_AAC_IS_ADTS>(type)) { ... }
```

---

### 4.2 FLAC 编码器插件——FFmpegFlacEncoderPlugin

**文件**: `services/media_engine/plugins/ffmpeg_adapter/audio_encoder/flac/ffmpeg_flac_encoder_plugin.cpp` (252行)

FLAC 插件组合 FFmpegBaseEncoder 基类，添加 FLAC 特定元数据：

- `flac/ffmpeg_flac_encoder_plugin.cpp` — 无需 ADTS 头（FLAC 是无压缩容器）
- 组合 `FFmpegBaseEncoder` 继承模式（与 AAC 自实现不同）

---

### 4.3 MP3 编码器插件——AudioMp3EncoderPlugin

**文件**: `services/media_engine/plugins/ffmpeg_adapter/audio_encoder/mp3/audio_mp3_encoder_plugin.cpp` (404行)

- 使用 LAME (LAME Ain't an MP3 Encoder) 库进行 MP3 编码
- 独立 `PLUGIN_DEFINITION` 注册

---

### 4.4 G711mu 编码器插件——AudioG711muEncoderPlugin

**文件**: `services/media_engine/plugins/ffmpeg_adapter/audio_encoder/g711mu/audio_g711mu_encoder_plugin.cpp` (304行)

**零依赖表驱动**：G711mu (μ-law) 编码是查表算法，无需 FFmpeg 库依赖：

```cpp
// g711mu/audio_g711mu_encoder_plugin.cpp — 304行，无 libavcodec 引用
```

> **与 FFmpegBaseDecoder 双轨**：G711mu 解码器（S125/S184）同样采用零依赖表驱动，与 FFmpegBaseDecoder 并行存在。

---

### 4.5 LBVC 编码器插件——AudioLbvcEncoderPlugin

**文件**: `services/media_engine/plugins/ffmpeg_adapter/audio_encoder/lbvc/audio_lbvc_encoder_plugin.cpp` (285行)

LBVC 是**唯一使用 HDI OMX 硬件路径**的 FFmpeg Adapter 音频编码器插件：

```cpp
// lbvc/audio_lbvc_encoder_plugin.cpp:19
using namespace Hdi;
using namespace OHOS::HDI::Codec::V4_0;

// lbvc/audio_lbvc_encoder_plugin.cpp:26
const std::string LBVC_ENCODER_COMPONENT_NAME = "OMX.audio.encoder.lbvc";

// lbvc/audio_lbvc_encoder_plugin.cpp:28-30
constexpr int32_t SUPPORT_CHANNELS = 1;
constexpr int32_t SUPPORT_SAMPLE_RATE = 16000;
constexpr uint32_t INPUT_BUFFER_SIZE_DEFAULT = 640;
constexpr uint32_t OUTPUT_BUFFER_SIZE_DEFAULT = 640;
constexpr int64_t SUPPORT_BITRATE = 6000;
```

**LBVC 独立注册**：

```cpp
// lbvc/audio_lbvc_encoder_plugin.cpp:42-57
Status RegisterAudioEncoderPlugins(const std::shared_ptr<Register>& reg)
{
    CodecPluginDef definition;
    definition.name = std::string(OHOS::MediaAVCodec::AVCodecCodecName::AUDIO_ENCODER_LBVC_NAME);
    definition.pluginType = PluginType::AUDIO_ENCODER;
    definition.rank = 100;
    definition.SetCreator([](const std::string& name) -> std::shared_ptr<CodecPlugin> {
        return std::make_shared<AudioLbvcEncoderPlugin>(name);
    });
    // ...
}

// lbvc/audio_lbvc_encoder_plugin.cpp:69
PLUGIN_DEFINITION(LbvcAudioEncoder, LicenseType::VENDOR,
    RegisterAudioEncoderPlugins, UnRegisterAudioEncoderPlugin);
```

**关键特征**：
- 单声道 (channels=1)
- 采样率 16000 Hz
- 码率 6000 bps
- HDI OMX 组件名: `OMX.audio.encoder.lbvc`
- `LicenseType::VENDOR`（非 LGPL），表明有供应商特定实现

---

## 5. 五子插件横向对比

| 插件 | 路径 | 行数 | 编码库 | ADTS | Resample | 备注 |
|------|------|------|--------|------|----------|------|
| AAC | `aac/` | 902 | libavcodec | ✅ 7字节 | ✅ SwrContext | 自实现 AVAudioFifo |
| FLAC | `flac/` | 252 | libavcodec | ❌ | ❌ | 组合 FFmpegBaseEncoder |
| MP3 | `mp3/` | 404 | LAME 库 | ❌ | ❌ | 独立 PLUGIN_DEFINITION |
| G711mu | `g711mu/` | 304 | 零依赖表 | ❌ | ❌ | 查表算法，无 FFmpeg |
| LBVC | `lbvc/` | 285 | HDI OMX | ❌ | ❌ | 硬件路径，独立注册 |

---

## 6. 与其他记忆的关联

- **S125** (FFmpegBaseDecoder) — 解码器镜像：Base 基类 + 多子插件矩阵
- **S130** (FFmpegAdapterCommon) — 共享 ffmpeg_convert.cpp (Resample/SwrContext)
- **S50** (AudioResample) — SwrContext 重采样器通用实现
- **S158/S169** — 同主题重叠（S158 草案，S169 增强版）
- **S184** (FFmpeg Audio Decoder) — 50 codec 变体（ADPCM×34 共享）
- **S191** (OHOS-Native vs FFmpeg 双路径) — G711mu 零依赖 vs FFmpegBaseEncoder 双轨