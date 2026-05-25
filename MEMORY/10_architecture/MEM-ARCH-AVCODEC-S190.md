---
status: draft
mem_id: MEM-ARCH-AVCODEC-S190
title: "FFmpeg Resample 重采样器 + AudioCaptureModule 音频采集双模块集成架构——SwrContext/AVAudioFifo双缓冲 + AudioCapturer/Read双模式 + GetMaxAmplitude振幅监测"
scope: "AVCodec, FFmpeg, Resample, SwrContext, AudioCaptureModule, AudioCapturer, AudioSource, GetMaxAmplitude, TrackMaxAmplitude, AudioResample, AVAudioFifo"
timestamp: "2026-05-25T15:34:00+08:00"
evidence_count: 18
source_files:
  - "/home/west/av_codec_repo/services/media_engine/plugins/ffmpeg_adapter/common/ffmpeg_convert.cpp (247行)"
  - "/home/west/av_codec_repo/services/media_engine/plugins/ffmpeg_adapter/common/ffmpeg_convert.h (98行)"
  - "/home/west/av_codec_repo/services/media_engine/modules/source/audio_capture/audio_capture_module.cpp (509行)"
  - "/home/west/av_codec_repo/services/media_engine/modules/source/audio_capture/audio_capture_module.h (95行)"
  - "/home/west/av_codec_repo/services/media_engine/plugins/ffmpeg_adapter/audio_encoder/aac/ffmpeg_aac_encoder_plugin.cpp (902行)"
关联记忆:
  - S125 (FFmpegDecoder基类)
  - S132/S158/S176 (FFmpeg音频编码器)
  - S119 (AudioSampleFormat位深映射)
  - S147 (AudioCaptureModule)
  - S50/S130 (Resample/FFmpegAdapter)
---

# S190 FFmpeg Resample + AudioCaptureModule 双模块集成架构

## 1. 架构概述

本记忆描述两个独立模块的协作集成：

1. **FFmpeg Resample 重采样器** (`Resample` 类) — 基于 libswresample 的音频格式转换引擎
2. **AudioCaptureModule 音频采集模块** — 基于 AudioStandard::AudioCapturer 的实时音频采集引擎

两者通过 Pipeline 串联构成完整的"采集→重采样→编码"链路，上游接麦克风/屏幕音频，下游送 FFmpeg AAC/FLAC 编码器。

```
AudioStandard::AudioCapturer
        ↓ (Read 原始PCM)
AudioCaptureModule
        ↓ (GetMaxAmplitude/TrackMaxAmplitude 振幅监测)
   [可选: Resample]
        ↓ (SwrContext 重采样)
FFmpeg AAC/FLAC 编码器
        ↓ (av_audio_fifo 缓冲)
AVPacket → MuxerFilter
```

---

## 2. FFmpeg Resample 组件

### 2.1 Resample 类结构

源文件：`ffmpeg_convert.cpp` (247行) + `ffmpeg_convert.h` (98行)

```cpp
// ffmpeg_convert.h
class Resample {
public:
    Status Init(const ResamplePara &resamplePara);           // E1: ffmpeg_convert.cpp:28
    Status InitSwrContext(const ResamplePara &resamplePara); // E2: ffmpeg_convert.cpp:64
    void ConvertCommon(const uint8_t *srcBuffer, ...);       // E3: ffmpeg_convert.cpp:88
    Status Convert(const uint8_t *srcBuffer, ...);           // E4: ffmpeg_convert.cpp:123
    Status ConvertFrame(AVFrame *outputFrame, ...);          // E5: ffmpeg_convert.cpp:165
    uint32_t GetSampleOffset();                              // E6: ffmpeg_convert.cpp:193
};
```

### 2.2 SwrContext 双模式初始化

**E7: ffmpeg_convert.cpp:44** — `swr_alloc_set_opts2` 申请 SwrContext 并配置参数（输出格式/采样率/通道布局）：

```cpp
int32_t error = swr_alloc_set_opts2(&swrContext,
    &resamplePara_.channelLayout,  // 输出通道布局
    resamplePara_.destFmt,          // AVSampleFormat 目标格式
    resamplePara_.sampleRate,       // 目标采样率
    resamplePara_.srcChannelLayout, // 输入通道布局
    resamplePara_.srcFmt,           // 输入格式
    resamplePara_.srcSampleRate,    // 输入采样率
    0, nullptr);
```

**E8: ffmpeg_convert.cpp:48** — `swr_init` 初始化：

```cpp
if (swr_init(swrContext) != 0) {
    // 初始化失败
}
```

**E9: ffmpeg_convert.cpp:53** — `swrCtx_` 智能指针包装（含自定义删除器）：

```cpp
swrCtx_ = std::shared_ptr<SwrContext>(swrContext, [](SwrContext *ptr) {
    if (ptr != nullptr) {
        swr_freeContext(ptr);  // RAII 自动释放
    }
});
```

### 2.3 样本级重采样转换

**E10: ffmpeg_convert.cpp:111** — `swr_convert` 按样本数转换（PCM 缓冲区模式）：

```cpp
auto res = swr_convert(swrCtx_.get(), resampleChannelAddr_.data(), samples, tmpInput.data(), samples);
```

**E11: ffmpeg_convert.cpp:187** — `swr_convert_frame` 按 AVFrame 帧转换（帧级模式）：

```cpp
auto ret = swr_convert_frame(swrCtx_.get(), outputFrame, inputFrame);
```

### 2.4 ResamplePara 参数结构

`ResamplePara` 包含六元组：`srcFmt / dstFmt`、`srcSampleRate / dstSampleRate`、`srcChannelLayout / dstChannelLayout`，决定 SwrContext 的转换配置。

---

## 3. AudioCaptureModule 组件

### 3.1 类结构与初始化

源文件：`audio_capture_module.cpp` (509行) + `audio_capture_module.h` (95行)

**E12: audio_capture_module.cpp:94** — `AudioCapturer::Create` 工厂创建：

```cpp
audioCapturer_ = AudioStandard::AudioCapturer::Create(options_, appInfo);
```

### 3.2 Read 双模式

**E13: audio_capture_module.cpp:320** — AVBuffer 模式 Read（Pipeline 内使用）：

```cpp
Status AudioCaptureModule::Read(std::shared_ptr<AVBuffer> &buffer, size_t expectedLen)
// 返回: buffer 承载采集音频数据，内部调用 audioCapturer_->Read()
```

**E14: audio_capture_module.cpp:355** — 裸指针模式 Read（外部调用）：

```cpp
Status AudioCaptureModule::Read(uint8_t *cacheAudioData, size_t expectedLen)
// 直接填充传入的 uint8_t* 缓冲区
```

### 3.3 振幅监测双函数

**E15: audio_capture_module.cpp:456** — `GetMaxAmplitude` 获取峰值（重置内部计数器）：

```cpp
int32_t AudioCaptureModule::GetMaxAmplitude()
{
    if (!isTrackMaxAmplitude) {
        isTrackMaxAmplitude = true;  // 懒加载开启
    }
    int16_t value = maxAmplitude_;   // 上一次峰值
    maxAmplitude_ = 0;               // 重置计数器
    return value;
}
```

**E16: audio_capture_module.cpp:471** — `TrackMaxAmplitude` 逐样本峰值追踪：

```cpp
void AudioCaptureModule::TrackMaxAmplitude(int16_t *data, int32_t size)
{
    for (int32_t i = 0; i < size; i++) {
        int16_t value = *data++;
        if (value < 0) {
            value = -value;  // 取绝对值
        }
        if (maxAmplitude_ < value) {
            maxAmplitude_ = value;  // 更新峰值
        }
    }
}
```

**E17: audio_capture_module.cpp:348** — Read 中调用 TrackMaxAmplitude（AVBuffer 模式）：

```cpp
if (isTrackMaxAmplitude) {
    TrackMaxAmplitude(reinterpret_cast<int16_t *>(bufData->GetAddr()), ...);
}
```

**E18: audio_capture_module.cpp:370** — Read 中调用 TrackMaxAmplitude（裸指针模式）：

```cpp
if (isTrackMaxAmplitude) {
    TrackMaxAmplitude(reinterpret_cast<int16_t *>(cacheAudioData), ...);
}
```

---

## 4. 与 FFmpeg AAC 编码器的集成

在 AAC 编码器中，AudioCaptureModule 采集的 PCM 数据经过 Resample 重采样后，送入 `av_audio_fifo` 缓冲：

- `ffmpeg_aac_encoder_plugin.cpp:694` — `av_audio_fifo_alloc` 分配 FIFO 缓冲
- `ffmpeg_aac_encoder_plugin.cpp:761` — `av_audio_fifo_read` 消费 FIFO 数据
- `ffmpeg_aac_encoder_plugin.cpp:826` — `av_audio_fifo_write` 生产数据进 FIFO
- `ffmpeg_aac_encoder_plugin.cpp:37` — `ADTS_HEADER_SIZE = 7` (AAC 编码后封装的 ADTS 头长度)

---

## 5. 关联索引

| 关联记忆 | 关系 |
|----------|------|
| S125 (FFmpeg Decoder) | 同为 FFmpeg Adapter 体系，共享 Resample |
| S132/S158/S176 (FFmpeg Audio Encoder) | AAC/FLAC/MP3 编码器，消费 Resample 输出 |
| S119 (AudioSampleFormat) | 24种采样格式映射，与 Resample 协作 |
| S50/S130 (AudioResample) | SwrContext/Resample 重采样框架 |
| S147 (DataSink/MediaMuxer) | 下游 MuxerFilter 封装 |