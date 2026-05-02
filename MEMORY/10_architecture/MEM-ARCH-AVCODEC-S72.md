# MEM-ARCH-AVCODEC-S72: AudioCodec Worker Pipeline 整合视图

> **ID**: MEM-ARCH-AVCODEC-S72
> **Title**: AudioCodec Worker Pipeline 整合视图——AudioResample + AudioBuffersManager + AudioCodecWorker 三层协作架构
> **Type**: architecture
> **Scope**: AVCodec, AudioCodec, WorkerThread, Pipeline, FFmpeg, BufferManagement, Resample, SwrContext
> **Status**: draft
> **Created**: 2026-05-03T01:33:00+08:00
> **Tags**: AudioCodec, AudioCodecWorker, AudioBuffersManager, AudioResample, SwrContext, TaskThread, Pipeline, FFmpeg, BufferManagement, libswresample

---

## 核心架构描述（中文）

AudioCodec Worker Pipeline 是 OpenHarmony AVCodec 模块中音频编解码的核心执行管线，由 AudioCodecWorker 驱动双 TaskThread（OS_AuCodecIn / OS_AuCodecOut），配合 AudioBuffersManager 缓冲区管理器和 AudioResample 重采样框架，完成音频数据的解码/编码全流程。

### 三层协作模型

```
┌────────────────────────────────────────────────────────────────────┐
│                    AudioCodecWorker                                │
│  services/engine/audio/src/audio_codec_worker.cpp                  │
│  ├─ OS_AuCodecIn TaskThread  ───► 输入流水线驱动                    │
│  ├─ OS_AuCodecOut TaskThread ───► 输出流水线驱动                    │
│  ├─ inputBuffer_  : AudioBuffersManager（8个 AudioBufferInfo 池）    │
│  ├─ outputBuffer_ : AudioBuffersManager（8个 AudioBufferInfo 池）    │
│  └─ AudioResample :: InitSwrContext / swr_convert                  │
└────────────────┬─────────────────────────────────────────────────┘
                 │
    ┌────────────┴──────────────────────┐
    ▼                                  ▼
┌──────────────────┐           ┌──────────────────────┐
│  AudioBuffersManager  │       │    AudioResample      │
│  inputBuffer_          │       │    libswresample      │
│  outputBuffer_         │       │    SwrContext         │
│  RequestAvailableIndex │       │    ResamplePara       │
│  (500ms block + CV)    │       │    CheckResample      │
└────────┬─────────────┘           └──────────────────────┘
         │
         ▼
┌──────────────────────────────────────────────────────────┐
│              AudioBufferInfo (per buffer)                 │
│  ├─ AVSharedMemoryBase data_     (音频原始数据)          │
│  ├─ AVSharedMemoryBase metaData_ (元数据/时间戳)         │
│  ├─ BufferStatus status_         (IDLE/OWEN_BY_CLIENT)   │
│  └─ isUsing / EOS / FirstFrame 标志位                   │
└──────────────────────────────────────────────────────────┘
```

### 双 TaskThread 驱动机制

**OS_AuCodecIn（输入线程）**:
- 驱动 `inputBuffer_` 的填充流程
- 从 Filter 层（AudioDecoderFilter / AudioDataSourceFilter）接收原始音频压缩数据
- 调用 `RequestAvailableIndex()` 阻塞等待（500ms timeout）获取可用缓冲区
- 填充完成后通知 output 线程

**OS_AuCodecOut（输出线程）**:
- 驱动 `outputBuffer_` 的消费流程
- 调用 FFmpeg 解码器（AudioFFMpegAacDecoderPlugin 等）执行解码
- 触发 AudioResample 进行格式转换（采样率/通道布局）
- 将 PCM 数据推送至下一级 Filter（AudioSinkFilter）

### AudioBuffersManager 缓冲区管理

```cpp
// services/engine/audio/src/audio_buffers_manager.cpp
class AudioBuffersManager {
    std::vector<AudioBufferInfo> inputBuffer_;   // 8个缓冲区
    std::vector<AudioBufferInfo> outputBuffer_;  // 8个缓冲区
    
    // 获取可用缓冲区（阻塞最多500ms）
    int32_t RequestAvailableIndex();
    
    // 释放缓冲区回池
    void ReleaseBuffer(uint32_t index);
    
    // 重置所有缓冲区状态
    void ResetBuffer();
};
```

**BufferStatus 枚举**:
```cpp
enum BufferStatus {
    IDLE = 0,           // 缓冲区空闲，可使用
    OWEN_BY_CLIENT = 1  // 已被客户端占用
};
```

**RequestAvailableIndex 等待机制**:
- 使用 `condition_variable` + `mutex`
- 等待超时：500ms
- `notify_all()` 在 `ReleaseBuffer` 时调用，唤醒等待线程

### AudioResample 重采样框架

**SwrContext 初始化**:
```cpp
// 基于 FFmpeg libswresample
SwrContext* swr = swr_alloc();
av_opt_set_channel_layout(swr, "in_ch_layout", ...);
av_opt_set_channel_layout(swr, "out_ch_layout", ...);
swr_init(swr);
```

**ResamplePara 结构体**:
```cpp
struct ResamplePara {
    uint32_t sampleRate;      // 目标采样率（支持13档：8000-192000）
    uint32_t inSampleRate;    // 输入采样率
    uint32_t channels;        // 通道数（1-8）
    uint32_t inChannels;      // 输入通道数
    uint32_t outChannels;     // 输出通道数
    AVSampleFormat inFormat;  // 输入格式
    AVSampleFormat outFormat; // 输出格式
};
```

**重采样触发时机**:
- 解码器 `ReceiveFrameSucc` 回调中首次触发
- `needResample_` 标志由 `CheckResample()` 判定
- 支持格式： planar signed 16/32/64bit、float、double

### AudioFFMpegAacDecoderPlugin 解码器插件

**与 AudioCodecWorker 的协作**:
```cpp
class AudioFFMpegAacDecoderPlugin : public AudioBaseCodec {
    // FFmpeg libavcodec 封装
    // avcodec_send_packet() / avcodec_receive_frame()
    // 输出 PCM 数据给 AudioResample
};
```

**ADTS 头处理**:
- AAC 流需解析 7 字节 ADTS 头
- 提取采样率、通道数、帧长度信息

### 与 Filter 层对接

**Filter → Worker → Filter 完整路径**:

```
AudioDataSourceFilter / AudioCaptureFilter
         │
         ▼ (AVBufferQueue)
AudioCodecWorker (OS_AuCodecIn Thread)
         │
         ▼ (AudioBuffersManager.inputBuffer_)
FFmpeg Decoder (AudioFFMpegAacDecoderPlugin)
         │
         ▼ (PCM data)
AudioResample (SwrContext) ─── 格式转换
         │
         ▼ (AudioBuffersManager.outputBuffer_)
AudioCodecWorker (OS_AuCodecOut Thread)
         │
         ▼ (AVBufferQueue)
AudioSinkFilter / AudioEncoderFilter
```

### 状态机关联

| 组件 | 状态枚举 | 说明 |
|------|---------|------|
| AudioCodecWorker | OS_AuCodecIn / OS_AuCodecOut | 双线程独立运行 |
| AudioBufferInfo | IDLE / OWEN_BY_CLIENT | 缓冲区生命周期 |
| AudioResample | INIT / CONVERTING / IDLE | 重采样状态 |

### Evidence 来源

1. **S50** — AudioResample 框架（SwrContext / libswresample）
2. **S62** — AudioBuffersManager 双缓冲池管理（RequestAvailableIndex 500ms / condition_variable）
3. **S60** — AudioFFMpegAacDecoder/EncoderPlugin 双插件（ADTS 7字节头 / FFmpeg libavcodec）
4. **S35** — AudioDecoderFilter 三层架构（Filter → AudioDecoderAdapter → AudioCodec）
5. **S8** — FFmpeg 音频插件总览（AudioBaseCodec CRTP 注册机制）

---

## 补充 Evidence（来自 GitCode）

**源码路径参考**（基于 multimedia_av_codec 源码树）:
- `services/engine/audio/src/audio_codec_worker.cpp` — 双 TaskThread 驱动
- `services/engine/audio/src/audio_buffers_manager.cpp` — 缓冲区池管理
- `services/engine/audio/src/audio_resample.cpp` — SwrContext 封装
- `services/plugins/audio/ffmpeg_aac/` — AudioFFMpegAacDecoderPlugin

---

## 关联主题

| 关联 | 说明 |
|------|------|
| S50 | AudioResample — SwrContext 封装与重采样参数 |
| S62 | AudioBuffersManager — 双缓冲区池与 condition_variable 机制 |
| S60 | AudioFFMpegAacDecoder/EncoderPlugin — FFmpeg 解码器插件 |
| S8 | FFmpeg 音频插件总览 — AudioBaseCodec CRTP 注册 |
| S35 | AudioDecoderFilter — Filter 层封装 |
| S31 | AudioSinkFilter — 音频输出终点 |

---

## 变更记录

| 日期 | 操作 | 说明 |
|------|------|------|
| 2026-05-03T01:33 | Builder | 整合 S50/S62/S60/S35/S8 生成 S72：AudioCodec Worker Pipeline 三层协作架构 |