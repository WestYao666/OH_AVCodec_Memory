---
id: MEM-ARCH-AVCODEC-S191
title: "OHOS-Native Audio Codec Plugins vs FFmpeg Adapter Architecture——G711mu/Opus 自主实现 vs FFmpeg-Based 音频编解码双路径"
scope: ["AVCodec", "AudioCodec", "Plugin", "FFmpeg", "G711mu", "Opus", "SoftwareCodec", "Engine", "FFmpegAdapter", "dlopen", "OHOS-Native"]
topic: "OHOS-Native Audio Codec Plugins（G711mu/Opus自主实现）vs FFmpeg Adapter Architecture（FFmpeg-Based编解码）——services/engine/codec/audio/引擎路径与services/media_engine/plugins/ffmpeg_adapter/适配路径对比，services/engine/codec/audio/decoder/audio_ffmpeg_decoder_plugin.cpp基类组合模式，services/engine/codec/audio/encoder/audio_g711mu_encoder_plugin.cpp无外部依赖表驱动算法，services/engine/codec/audio/encoder/audio_opus_encoder_plugin.cpp dlopen libav_codec_ext_base.z.so。
status: draft
created_at: "2026-05-25T16:20:00+08:00"
evidence_count: 20
source_files: |
  services/engine/codec/audio/encoder/audio_g711mu_encoder_plugin.cpp (239行)
  services/engine/codec/audio/decoder/audio_g711mu_decoder_plugin.cpp (168行)
  services/engine/codec/audio/encoder/audio_opus_encoder_plugin.cpp (263行)
  services/engine/codec/audio/decoder/audio_opus_decoder_plugin.cpp (242行)
  services/engine/codec/audio/decoder/audio_ffmpeg_decoder_plugin.cpp (398行)
  services/engine/codec/audio/encoder/audio_ffmpeg_aac_encoder_plugin.cpp (583行)
  services/engine/codec/audio/decoder/audio_ffmpeg_aac_decoder_plugin.cpp (~250行)
  services/media_engine/plugins/ffmpeg_adapter/audio_encoder/ffmpeg_base_encoder.cpp (396行)
  services/media_engine/plugins/ffmpeg_adapter/audio_decoder/ffmpeg_base_decoder.cpp (605行)
---

# OHOS-Native Audio Codec Plugins vs FFmpeg Adapter Architecture

## 1. 概述：双路径架构

AVCodec 音频编解码存在两条并行路径：

| 路径 | 位置 | 特点 | 代表插件 |
|------|------|------|---------|
| **Engine 引擎路径** | `services/engine/codec/audio/` | 插件粒度细，自主实现为主 | G711mu（无依赖）、Opus（dlopen扩展库）、FFmpeg AAC（组合基类） |
| **FFmpeg Adapter 适配路径** | `services/media_engine/plugins/ffmpeg_adapter/` | 继承 FFmpegBase 基类，标准化封装 | AAC、FLAC、MP3、Vorbis、WMA（均继承 FFmpegBaseDecoder/Encoder） |

**关键区别**：
- Engine 路径：插件可组合 `AudioFfmpegDecoderPlugin` 基类（composition），或完全自实现（无外部依赖）
- FFmpeg Adapter 路径：强制继承 `FFmpegBaseDecoder`/`FFmpegBaseEncoder` 基类（inheritance）

---

## 2. G711mu 编解码器：零依赖表驱动算法

### 2.1 G711mu 编码器（audio_g711mu_encoder_plugin.cpp:239行）

**文件**：`services/engine/codec/audio/encoder/audio_g711mu_encoder_plugin.cpp`

**架构**：完全自包含的 OHOS-Native 实现，无任何外部库依赖。

**参数约束**（第47-49行）：
```cpp
constexpr int32_t SUPPORT_CHANNELS = 1;         // 仅支持单声道
constexpr int SUPPORT_SAMPLE_RATE = 8000;       // 仅支持 8000Hz
constexpr int INPUT_BUFFER_SIZE_DEFAULT = 1280;  // 20ms: 320样本 × 2字节 × 1通道
constexpr int OUTPUT_BUFFER_SIZE_DEFAULT = 640;   // 20ms: 160字节（压缩后）
```

**μ-law 编码算法**（第120-148行 `G711MuLawEncode`）：
```cpp
// AVCODEC_G711MU_SEG_END[8] = {0x3F, 0x7F, 0xFF, 0x1FF, 0x3FF, 0x7FF, 0xFFF, 0x1FFF}
// AVCODEC_G711MU_LINEAR_BIAS = 0x84，AVCODEC_G711MU_CLIP = 8159
// 算法：对PCM值分段线性量化，8段索引×4位量化值=8位μ-law输出
uint8_t muLawValue = (uint8_t)(seg << 4) | ((pcmShort >> (seg + 1)) & 0xF);
return (muLawValue ^ mask);  // μ-law = ~线性值（按声道位翻转）
```

**处理流程**：
1. `Init(format)` → `CheckFormat` 校验通道数/采样率/格式（第79-101行）
2. `ProcessSendData(inputBuffer)` → 对每个 int16_t PCM 样本调用 `G711MuLawEncode`（第150-184行）
3. `ProcessRecieveData(outBuffer)` → 将压缩后的 encodeResult_ 写入输出缓冲区（第186-207行）

**特点**：
- 无锁 Codec：`std::mutex avMutext_` 保护共享数据
- 无状态 Reset/Release/Flush：空操作（简单编解码器无需清理状态）
- MIME 类型固定为 `MEDIA_MIMETYPE_AUDIO_G711MU`

### 2.2 G711mu 解码器（audio_g711mu_decoder_plugin.cpp:168行）

**文件**：`services/engine/codec/audio/decoder/audio_g711mu_decoder_plugin.cpp`

**μ-law 解码算法**（第62-74行 `G711MuLawDecode`）：
```cpp
// G711MuLawDecode：μ-law → 线性 PCM
muLawValue = ~muLawValue;  // μ-law 取反（编码时μ-law=~线性）
tmp = ((muLawValue & AVCODEC_G711MU_QUANT_MASK) << 3) + G711MU_LINEAR_BIAS;
tmp <<= ((unsigned)muLawValue & AVCODEC_G711MU_SEG_MASK) >> AVCODEC_G711MU_SHIFT;
// 第7位=符号位：正数=tmp-G711MU_LINEAR_BIAS，负数=G711MU_LINEAR_BIAS-tmp
return ((muLawValue & AUDIO_G711MU_SIGN_BIT) ? (G711MU_LINEAR_BIAS - tmp) : (tmp - G711MU_LINEAR_BIAS));
```

**缓冲区大小**（第28-29行）：
```cpp
constexpr int INPUT_BUFFER_SIZE_DEFAULT = 640;   // μ-law 输入：160字节
constexpr int OUTPUT_BUFFER_SIZE_DEFAULT = 1280;  // PCM 输出：320样本 × 2字节
// 压缩比恒定为 2:1（640字节→1280字节）
```

---

## 3. Opus 编解码器：dlopen 扩展库模式

### 3.1 Opus 编码器（audio_opus_encoder_plugin.cpp:263行）

**文件**：`services/engine/codec/audio/encoder/audio_opus_encoder_plugin.cpp`

**架构**：动态加载 libav_codec_ext_base.z.so，不使用 FFmpeg libavcodec。

**dlopen 初始化**（第49-67行）：
```cpp
handle = dlopen("libav_codec_ext_base.z.so", 1);  // RTLD_NOW=1
OpusPluginClassCreateFun* PluginCodecCreate =
    (OpusPluginClassCreateFun *)dlsym(handle, "OpusPluginClassEncoderCreate");
// 三函数指针：PluginCodecPtr->SetParameter/Init/ProcessSendData/ProcessRecieveData
```

**参数约束**（第37-46行）：
```cpp
constexpr int32_t MIN_CHANNELS = 1; MAX_CHANNELS = 2;          // 1-2声道
static const int32_t OPUS_ENCODER_SAMPLE_RATE_TABLE[] = {8000, 12000, 16000, 24000, 48000};
constexpr int32_t MIN_BITRATE = 6000; MAX_BITRATE = 510000;    // 6kbps-510kbps
constexpr int32_t MIN_COMPLEX = 1; MAX_COMPLEX = 10;           // 复杂度 1-10
// TIME_S = 0.02（20ms帧），TIME_US = 20000μs
```

**与 G711mu 对比**：
- G711mu：无任何外部依赖，纯表驱动算法
- Opus：依赖 libav_codec_ext_base.z.so（硬件加速或专利相关实现）

### 3.2 Opus 解码器（audio_opus_decoder_plugin.cpp:242行）

**文件**：`services/engine/codec/audio/decoder/audio_opus_decoder_plugin.cpp`

**dlopen 初始化**（第49-62行）：
```cpp
handle = dlopen("libav_codec_ext_base.z.so", 1);
OpusPluginClassCreateFun *PluginCodecCreate =
    (OpusPluginClassCreateFun *)dlsym(handle, "OpusPluginClassDecoderCreate");
// OpusPluginClassDecoderCreate → OpusPluginClass → ProcessSendData/ProcessRecieveData
```

**输出计算**（第136-137行）：
```cpp
memory->Write(codeData, len * channels * sizeof(short));  // len=帧数，channels=声道数
attr.size = len * channels * sizeof(short);              // 输出大小=帧数×声道×2字节
```

---

## 4. Engine 路径 FFmpeg AAC 编解码器：组合基类模式

### 4.1 AudioFfmpegDecoderPlugin 基类（audio_ffmpeg_decoder_plugin.cpp:398行）

**文件**：`services/engine/codec/audio/decoder/audio_ffmpeg_decoder_plugin.cpp`

**核心接口**（第31-50行）：
```cpp
AudioFfmpegDecoderPlugin();                              // 构造函数
int32_t ProcessSendData(const std::shared_ptr<AudioBufferInfo>& inputBuffer);  // 送入压缩数据
int32_t ProcessRecieveData(std::shared_ptr<AudioBufferInfo>& outBuffer);       // 取出 PCM 数据
int32_t InitResample();                                   // 初始化重采样
int32_t AllocateContext(const std::string &name);         // 分配 FFmpeg AVCodecContext
int32_t InitContext(const Format &format);                // 配置通道/采样率/格式
int32_t OpenContext();                                    // 打开编码器
void EnableResample(AVSampleFormat destFmt);             // 启用重采样
int32_t ConvertPlanarFrame(std::shared_ptr<AudioBufferInfo>& outBuffer);        // 平面格式转换
```

**关键成员**：
- `std::shared_ptr<AVCodecContext> avCodecContext_`（FFmpeg 解码器上下文）
- `std::shared_ptr<AVPacket> avPacket_`（压缩数据包）
- `std::shared_ptr<AVFrame> cachedFrame_`（解码帧缓存）
- `std::unique_ptr<AudioResample> resample_`（SwrContext 重采样器）
- `avMutext_`（线程互斥锁）

**avcodec send/receive 管线**（第55-130行）：
```cpp
ProcessSendData → SendBuffer → avcodec_send_packet → AVERROR_XXX/EAGAIN 处理
ProcessRecieveData → ReceiveBuffer → avcodec_receive_frame → ConvertPlanarFrame → 重采样（需要时）
```

### 4.2 AudioFFMpegAacEncoderPlugin（audio_ffmpeg_aac_encoder_plugin.cpp:583行）

**文件**：`services/engine/codec/audio/encoder/audio_ffmpeg_aac_encoder_plugin.cpp`

**ADTS 头构造**（第37-38行）：
```cpp
constexpr uint32_t ADTS_HEADER_SIZE = 7;  // ADTS 固定7字节头
static std::map<int32_t, uint8_t> sampleFreqMap = {{96000,0},{88200,1},...,{44100,4},...};
static std::map<int32_t, uint64_t> channelLayoutMap = {{1,AV_CH_LAYOUT_MONO},{2,AV_CH_LAYOUT_STEREO},...};
```

**成员初始化**（第52-56行）：
```cpp
AudioFFMpegAacEncoderPlugin()
    : maxInputSize_(-1), avCodec_(nullptr), avCodecContext_(nullptr),
      cachedFrame_(nullptr), avPacket_(nullptr), prevPts_(0),
      resample_(nullptr), needResample_(false),
      srcFmt_(AVSampleFormat::AV_SAMPLE_FMT_NONE), srcLayout_(0),
      codecContextValid_(false) {}
```

### 4.3 AudioFFMpegAacDecoderPlugin（组合模式）

**文件**：`services/engine/codec/audio/decoder/audio_ffmpeg_aac_decoder_plugin.cpp`

**组合模式**（第30-35行）：
```cpp
AudioFFMpegAacDecoderPlugin::AudioFFMpegAacDecoderPlugin()
    : basePlugin(std::make_unique<AudioFfmpegDecoderPlugin>()), channels_(0) {}
// AAC 解码器组合 AudioFfmpegDecoderPlugin 基类，而非继承
// ADTS 格式检测：CheckAdts(format) 区分 ADTS 和 LATM
```

---

## 5. FFmpeg Adapter 路径：继承基类模式

### 5.1 FFmpegBaseDecoder（ffmpeg_base_decoder.cpp:605行）

**文件**：`services/media_engine/plugins/ffmpeg_adapter/audio_decoder/ffmpeg_base_decoder.cpp`

**继承模式**：所有 FFmpeg 音频解码器均继承 `FFmpegBaseDecoder`（CRTP 模板实例化）：
```cpp
// FFmpegBaseDecoder::Init() → avcodec_open2 → avcodec_send_packet/avcodec_receive_frame
// FFmpegBaseDecoder::Resample() → SwrContext 重采样（来自 FFmpegConvert）
// 派生类只需实现：CheckFormat / GetCodecName / Init，成功则调用基类 InitContext
```

### 5.2 FFmpegBaseEncoder（ffmpeg_base_encoder.cpp:396行）

**文件**：`services/media_engine/plugins/ffmpeg_adapter/audio_encoder/ffmpeg_base_encoder.cpp`

**继承模式**：所有 FFmpeg 音频编码器均继承 `FFmpegBaseEncoder`：
```cpp
// FFmpegBaseEncoder::EncodeProcess() → avcodec_send_frame/avcodec_receive_packet
// 派生类只需实现：InitEncoder / CreatePacket / GetAdtsHeader（AAC）
```

---

## 6. 双路径架构对比总结

| 维度 | Engine 引擎路径 | FFmpeg Adapter 适配路径 |
|------|----------------|------------------------|
| **位置** | `services/engine/codec/audio/` | `services/media_engine/plugins/ffmpeg_adapter/` |
| **继承模式** | 组合（composition）：`AudioFfmpegDecoderPlugin` 基类被组合 | 继承（inheritance）：`FFmpegBaseDecoder/Encoder` 被继承 |
| **G711mu** | 完全自实现，无外部依赖 | N/A |
| **Opus** | dlopen `libav_codec_ext_base.z.so` | N/A |
| **AAC** | 组合基类 `AudioFfmpegDecoderPlugin` | 继承 `FFmpegBaseDecoder/Encoder` |
| **插件注册** | 独立插件，通过 AudioCodecFactory 路由 | AutoRegisterFilter 静态注册 |
| **适用场景** | 需细粒度控制的专有/硬件加速编解码器 | 通用 FFmpeg 支持的编解码器 |
| **代表插件** | G711mu、Opus、AVC、HEVC | AAC、FLAC、MP3、Vorbis、WMA |

**核心设计意图**：
- Engine 路径采用**组合优于继承**模式，允许插件复用 `AudioFfmpegDecoderPlugin` 基类的 FFmpeg 管线，同时可替换或扩展特定行为
- FFmpeg Adapter 路径采用**继承**模式，通过 CRTP 模板实例化 50 种音频解码器变体（ADPCM×34、WMA×3 等），减少代码重复
- G711mu 作为最简单的编解码器（2:1 压缩比、零依赖），是理解 OHOS AudioCodecPlugin 接口契约的最佳入门案例

---

## 7. 与现有 S 系列记忆的关联

| 关联记忆 | 关系 |
|---------|------|
| S125（FFmpeg 音频解码器基类） | FFmpeg Adapter 路径：FfmpegBaseDecoder 继承模式 |
| S8（FFmpeg 音频插件总览） | FFmpeg Adapter 路径的全局视图 |
| S50（AudioResample 重采样） | 两路径共用的重采样机制 |
| S158/S169（FFmpeg 音频编码器） | FFmpeg Adapter 路径的 AAC/FLAC 编码器 |
| S184（FFmpeg 音频解码器体系） | FFmpeg Adapter 路径完整音频解码器矩阵 |

---

## 8. 关键行号速查

| 组件 | 文件 | 关键行号 |
|------|------|---------|
| G711mu 编码器-μ-law 算法 | audio_g711mu_encoder_plugin.cpp | L120-148 |
| G711mu 编码器-参数约束 | audio_g711mu_encoder_plugin.cpp | L47-53 |
| G711mu 解码器-μ-law 解码 | audio_g711mu_decoder_plugin.cpp | L62-74 |
| G711mu 解码器-缓冲区大小 | audio_g711mu_decoder_plugin.cpp | L28-29 |
| Opus 编码器-dlopen 初始化 | audio_opus_encoder_plugin.cpp | L49-67 |
| Opus 编码器-参数约束 | audio_opus_encoder_plugin.cpp | L37-46 |
| Opus 解码器-dlopen 初始化 | audio_opus_decoder_plugin.cpp | L49-62 |
| AudioFfmpegDecoderPlugin-基类 | audio_ffmpeg_decoder_plugin.cpp | L31-50 |
| AudioFfmpegDecoderPlugin-avcodec管线 | audio_ffmpeg_decoder_plugin.cpp | L55-130 |
| AudioFFMpegAacDecoderPlugin-组合模式 | audio_ffmpeg_aac_decoder_plugin.cpp | L30-35 |
| AudioFFMpegAacEncoderPlugin-ADTS | audio_ffmpeg_aac_encoder_plugin.cpp | L37-38 |
