# MEM-ARCH-AVCODEC-S193

## FFmpeg Adapter Audio Encoder Plugin 体系——三层架构与五子插件总览

**主题**: FFmpeg Adapter Audio Encoder Plugin 体系——FFmpegBaseEncoder 基类 + AAC/FLAC/MP3/G711mu/LBVC 五子插件架构
**scope**: AVCodec, FFmpeg, AudioEncoder, Plugin, SoftwareCodec, LBVC, HDI, OMX
**关联场景**: 新需求开发 / 音频编码接入 / HDI 硬件加速
**状态**: draft
**Builder**: builder-agent (subagent)
**生成时间**: 2026-05-26T00:25:00+08:00
**证据数量**: 18 条（≥15 目标达成）
**来源**: 本地镜像 `/home/west/av_codec_repo/services/media_engine/plugins/ffmpeg_adapter/`

---

## 一、整体架构

FFmpeg Adapter 音频编码器插件体系采用**三层架构**：

| 层级 | 文件 | 职责 |
|------|------|------|
| **注册层** | `ffmpeg_encoder_plugin.cpp` (85行) | PLUGIN_DEFINITION 宏，驱动 FFmpegBaseEncoder + AAC + FLAC 注册 |
| **基类层** | `ffmpeg_base_encoder.cpp` (396行) + `.h` (94行) | FFmpegBaseEncoder 基类封装 avcodec_send_frame/receive_frame |
| **子插件层** | aac/ (902行) / flac/ (252行) / mp3/ (404行) / g711mu/ (304行) / lbvc/ (285行) | 具体编码器实现（自实现/FFmpeg/LAME/HDI） |

**关键设计差异**：
- AAC/FLAC：继承 FFmpegBaseEncoder 基类，使用 FFmpeg libavcodec 管线
- MP3：独立实现，依赖 LAME 库 (`#include "lame.h"`)
- G711mu：零依赖表驱动，无 FFmpeg 依赖
- LBVC：HDI OMX 硬件编码路径，通过 HdiCodec 代理跨进程调用

---

## 二、注册层：FFmpegEncoderPlugin

### E1: `ffmpeg_encoder_plugin.cpp:1-85` — PLUGIN_DEFINITION 注册两层编码器

- **codecVec** 仅包含 2 个 FFmpeg 驱动编码器（AAC + FLAC），通过 FFmpegBaseEncoder 基类路由
- **MP3/G711mu/LBVC** 各有独立 PLUGIN_DEFINITION，注册路径不经过 FFmpegEncoderPlugin
- **rank = 100** (line 54)，CodecMode = SOFTWARE (line 56)
- 注册函数 `RegisterAudioEncoderPlugins` 循环 codecVec，分发 SetDefinition

### E2: `ffmpeg_encoder_plugin.cpp:27-56` — SetDefinition 双路分发

```cpp
case 0: // aac
    definition.SetCreator([](const std::string &name) -> std::shared_ptr<CodecPlugin> {
        return std::make_shared<FFmpegAACEncoderPlugin>(name);
    });
case 1: // flac
    definition.SetCreator([](const std::string &name) -> std::shared_ptr<CodecPlugin> {
        return std::make_shared<FFmpegFlacEncoderPlugin>(name);
    });
```

---

## 三、基类层：FFmpegBaseEncoder

### E3: `ffmpeg_base_encoder.h:1-90` — FFmpegBaseEncoder 类定义

- 头文件包含 libavcodec/avcodec.h (extern "C") + ffmpeg_convert.h (Resample) + avbuffer.h
- 核心成员：`avCodecContext_` (shared_ptr<AVCodecContext>)、`cachedFrame_` (shared_ptr<AVFrame>)、`avPacket_` (shared_ptr<AVPacket>)、`avMutext_` (mutex 线程安全)
- 核心接口：`ProcessSendData` (输入) / `ProcessReceiveData` (输出) / `AllocateContext` / `OpenContext`

### E4: `ffmpeg_base_encoder.cpp:1-100` — FFmpegBaseEncoder 构造函数与 ProcessSendData

- 构造函数初始化 maxInputSize_=-1 / codecContextValid_=false / prevPts_=0
- `ProcessSendData` 校验 memory_->GetSize()，EAGAIN 返回 ERROR_NOT_ENOUGH_DATA
- avMutext_ 锁保护 avCodecContext_ 访问

### E5: `ffmpeg_convert.cpp:28-53` — Resample::InitSwrContext

```cpp
auto swrContext = swr_alloc();
// swr_alloc_set_opts2(..., &resamplePara_.channelLayout, resamplePara_.destFmt, resamplePara_.sampleRate, ...)
swr_init(swrContext); // ret=0 success
swrCtx_ = shared_ptr<SwrContext>(swrContext, [](SwrContext *ptr) { swr_free(&ptr); });
```
- SwrContext RAII 包装（deleter 调用 swr_free）
- InitSwrContext 初始化 libswresample 重采样上下文

---

## 四、子插件：AAC (FFmpegBaseEncoder 继承路径)

### E6: `aac/ffmpeg_aac_encoder_plugin.cpp:37` — ADTS_HEADER_SIZE = 7

- AAC 编码输出需要封装 ADTS 7 字节头（Audio Data Transport Stream）
- GetAdtsHeader (line 102) 计算 frameLength = aacLength + 7，写入 header

### E7: `aac/ffmpeg_aac_encoder_plugin.cpp:191-206` — AudioSampleFormat → AVSampleFormat 映射表

```cpp
{AudioSampleFormat::SAMPLE_S16P, AVSampleFormat::AV_SAMPLE_FMT_S16P},
{AudioSampleFormat::SAMPLE_F32P, AVSampleFormat::AV_SAMPLE_FMT_FLTP},
```
- formatTable.at(audioFmt) 查表转换（9 种格式覆盖）

### E8: `aac/ffmpeg_aac_encoder_plugin.cpp:242-275` — QueueInputBuffer 写入 AVAudioFifo

- `av_audio_fifo_write(fifo_, ...)` 将 PCM 数据写入 FFmpeg AVAudioFifo 缓冲（1152 样本/帧）
- 等待 fifoSize >= avCodecContext_->frame_size 后触发编码
- CreateCtxAndFifo 调用链：Start → CreateCtxAndFifo → AllocateContext → OpenContext → InitFrame

### E9: `aac/ffmpeg_aac_encoder_plugin.cpp:330-360` — avcodec_receive_frame 接收编码帧

```cpp
auto ret = avcodec_receive_packet(avCodecContext_.get(), avPacket_.get());
if (ret >= 0) { status = ReceivePacketSucc(outBuffer); }
else if (ret == AVERROR_EOF) { outBuffer->flag_ = BUFFER_FLAG_EOS; }
else if (ret == AVERROR(EAGAIN)) { status = ERROR_NOT_ENOUGH_DATA; }
```
- 三路返回值处理：OK / EOF / EAGAIN

### E10: `aac/ffmpeg_aac_encoder_plugin.cpp:370-392` — av_audio_fifo_size 缓冲水位判断

```cpp
int32_t fifoSize = av_audio_fifo_size(fifo_);
if (fifoSize >= avCodecContext_->frame_size) {
    outputBuffer->flag_ = 0; // not eos
    SafeCallOutputBufferDone(dataCallback_, outputBuffer);
    return Status::ERROR_AGAIN; // 驱动再次拉取
}
```
- av_audio_fifo_size 用于判断是否达到单帧编码门槛

---

## 五、子插件：FLAC（FFmpegBaseEncoder 组合路径）

### E11: `flac/ffmpeg_flac_encoder_plugin.cpp:184-245` — FFmpegFlacEncoderPlugin 组合 basePlugin

```cpp
Status FFmpegFlacEncoderPlugin::Stop()  { return basePlugin->Stop(); }
Status FFmpegFlacEncoderPlugin::Reset()  { return basePlugin->Reset(); }
Status FFmpegFlacEncoderPlugin::Release(){ return basePlugin->Release(); }
Status FFmpegFlacEncoderPlugin::Flush()  { return basePlugin->Flush(); }
Status FFmpegFlacEncoderPlugin::QueueInputBuffer(...) { return basePlugin->ProcessSendData(...); }
```
- FLAC 插件**组合**（而非继承）FFmpegBaseEncoder，所有生命周期方法委托给 basePlugin
- Init/Start 为空（basePlugin 在 ProcessSendData 首次调用时惰性初始化）

---

## 六、子插件：MP3（独立 LAME 路径）

### E12: `mp3/audio_mp3_encoder_plugin.cpp:52-60` — LAME 库常量定义

```cpp
constexpr int32_t OUTPUT_BUFFER_SIZE_DEFAULT = 4096;
constexpr int32_t LAME_BUFFER_SIZE_DEFAULT = 8640;    // 1152*1.25+7200=8640
constexpr int32_t LAME_INPUT_BUFFER_SIZE_ONE_CHAN = 2304;  // 1152*2=2304
constexpr int32_t LAME_INPUT_BUFFER_SIZE_TWO_CHAN = 4608;  // 1152*2*2=4608
```
- 使用 LAME MP3 encoder library（开源实现）
- 1152 样本/帧（LAME 标准）

### E13: `mp3/audio_mp3_encoder_plugin.cpp:52-55,89` — LameInfo 结构体与初始化

```cpp
struct AudioMp3EncoderPlugin::LameInfo {
    lame_global_flags* gfp;
};
// PLUGIN_DEFINITION(Mp3AudioEncoder, LicenseType::APACHE_V2, RegisterAudioEncoderPlugins, ...)
// definition.SetCreator([](const std::string& name) -> std::shared_ptr<CodecPlugin> {
//     return std::make_shared<AudioMp3EncoderPlugin>(name);
// });
```
- rank = 100，CodecMode = SOFTWARE，独立注册不经过 FFmpegEncoderPlugin

---

## 七、子插件：G711mu（零依赖表驱动路径）

### E14: `g711mu/audio_g711mu_encoder_plugin.cpp:1-70` — G711mu 零依赖表驱动实现

```cpp
constexpr int AVCODEC_G711MU_LINEAR_BIAS = 0x84;
constexpr int AVCODEC_G711MU_CLIP = 8159;
static const short AVCODEC_G711MU_SEG_END[8] = {
    0x3F, 0x7F, 0xFF, 0x1FF, 0x3FF, 0x7FF, 0xFFF, 0x1FFF
};
```
- **无 FFmpeg 依赖**，无 LAME 依赖，纯数学表查 PCM↔μ-law 转换
- SUPPORT_CHANNELS=1 / SUPPORT_SAMPLE_RATE=8000，固定参数

---

## 八、子插件：LBVC（HDI OMX 硬件加速路径）

### E15: `lbvc/audio_lbvc_encoder_plugin.cpp:27,35` — OMX LBVC 组件名与 HDI 参数索引

```cpp
const std::string LBVC_ENCODER_COMPONENT_NAME = "OMX.audio.encoder.lbvc";
constexpr uint32_t OMX_AUDIO_CODEC_PARAM_INDEX = 0x6F000000 + 0x00A0000B;
```

### E16: `lbvc/audio_lbvc_encoder_plugin.cpp:81,94` — HdiCodec OMX 跨进程组件创建

```cpp
hdiCodec_(std::make_shared<HdiCodec>())
// ...
Status ret = hdiCodec_->InitComponent(LBVC_ENCODER_COMPONENT_NAME);
```
- LBVC 使用 HdiCodec（而非 FFmpeg libavcodec），通过 OMX ICodecComponentManager 跨进程调用硬件编码器
- HdiCodec 封装 CreateComponent/EmptyThisBuffer/FillThisBuffer/SendCommand

---

## 九、HdiCodec：OMX HDI 代理

### E17: `common/hdi_codec.cpp:42-55` — HdiCodec::InitComponent 创建 OMX 组件

```cpp
Status HdiCodec::InitComponent(const std::string &name)
{
    compMgr_ = GetComponentManager();  // line 61: sptr<ICodecComponentManager>
    componentName_ = name;
    compCb_ = new HdiCodec::HdiCallback(shared_from_this());
    int32_t ret = compMgr_->CreateComponent(compNode_, componentId_, componentName_, 0, compCb_);
    // ret=0 成功，否则失败
}
```
- GetComponentManager 获取 ICodecComponentManager 单例
- CreateComponent 触发 OMX 组件创建（HDI IPC 调用）

### E18: `common/hdi_codec.cpp:211-228` — EmptyThisBuffer / FillThisBuffer OMX 缓冲传递

```cpp
Status HdiCodec::EmptyThisBuffer(const std::shared_ptr<AVBuffer> &buffer)  // 输入编码
{
    int32_t ret = compNode_->EmptyThisBuffer(*omxInBufferInfo_->omxBuffer.get());
    // ret >= 0 成功
}
Status HdiCodec::FillThisBuffer(std::shared_ptr<AVBuffer> &buffer)  // 输出拉取
{
    int32_t ret = compNode_->FillThisBuffer(*omxOutBufferInfo_->omxBuffer.get());
}
```
- OMX 三步：InitComponent → EmptyThisBuffer (输入PCM) → FillThisBuffer (输出码流)

---

## 十、关联记忆

| 关联 | 主题 | 说明 |
|------|------|------|
| ← | S125 (FFmpeg Decoder) | 解码器三层架构（对称） |
| ← | S130 (FFmpegAdapterCommon) | 共享 ffmpeg_utils / ffmpeg_convert / hdi_codec |
| ← | S50 (AudioResample) | SwrContext 重采样 |
| ← | S158/S169 (FFmpeg Audio Encoder) | 同主题 S132/S158/S169/S174 多版本草案 |
| ← | S191 (OHOS-Native vs FFmpeg Adapter) | 双路径架构对比（G711mu 零依赖 vs FFmpeg 组合） |

---

## 十一、关键设计模式总结

| 模式 | 示例 |
|------|------|
| **CRTP + PLUGIN_DEFINITION** | ffmpeg_encoder_plugin.cpp:85 |
| **组合（而非继承）** | FFmpegFlacEncoderPlugin ↔ FFmpegBaseEncoder (basePlugin) |
| **惰性初始化** | FFmpegBaseEncoder::ProcessSendData 首次触发 AllocateContext |
| **RAII 资源管理** | SwrContext shared_ptr deleter / avPacket_ / avCodecContext_ |
| **表查值（零依赖）** | G711mu SEG_END[8] 表驱动 PCM↔μ-law |
| **HDI OMX IPC** | LBVC: HdiCodec → ICodecComponentManager → OMX 组件 |