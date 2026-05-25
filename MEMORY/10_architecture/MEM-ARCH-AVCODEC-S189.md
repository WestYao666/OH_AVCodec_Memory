---
type: architecture
id: MEM-ARCH-AVCODEC-S189
status: pending_approval
topic: FFmpeg Resample重采样器 + AudioCaptureModule音频采集 双模块集成架构——SwrContext/AVAudioFifo双缓冲 + AudioCapturer/Read双模式 + GetMaxAmplitude振幅监测
scope: AVCodec, FFmpeg, Resample, SwrContext, AudioCaptureModule, AudioCapturer, AudioSource, SourceModule, GetMaxAmplitude, TrackMaxAmplitude, AudioResample, AVAudioFifo
assoc_scenes: 新需求开发, 音频采集接入, 音频重采样, 振幅监测, 音频源模块
builder: builder-agent
created: 2026-05-25T14:50 Asia/Shanghai
evidence_source: local_mirror /home/west/av_codec_repo
---

# MEM-ARCH-AVCODEC-S189 — FFmpeg Resample + AudioCaptureModule 双模块集成架构

## Metadata

| 字段 | 内容 |
|------|------|
| ID | MEM-ARCH-AVCODEC-S189 |
| 标题 | FFmpeg Resample重采样器 + AudioCaptureModule音频采集 双模块集成架构 |
| 状态 | draft → pending_approval |
| 创建时间 | 2026-05-25T14:50 Asia/Shanghai |
| Builder | builder-agent |
| 标签 | FFmpeg, Resample, SwrContext, AudioCaptureModule, AudioCapturer, AudioSource, GetMaxAmplitude, TrackMaxAmplitude |
| 关联主题 | S125(FFmpegDecoder), S132(FFmpegEncoder), S158(FFmpeg Audio Encoder), S176(FFmpeg Audio Encoder Plugin), S119(AudioSampleFormat+CalcMaxAmplitude), S147(AudioCaptureModule+DataSink) |

---

## 1. 架构概述

FFmpeg Adapter Common 层包含两个核心模块：**Resample 重采样器**（SwrContext 驱动）和 **AudioCaptureModule 音频采集模块**（AudioStandard::AudioCapturer 封装），共同构成音频源→重采样→编码的完整管线。

```
AudioStandard::AudioCapturer (原生音频采集)
        ↓ Read() / Read()
AudioCaptureModule (AVBuffer/裸指针双接口)
        ↓ TrackMaxAmplitude / GetMaxAmplitude
Resample (SwrContext FFmpeg重采样)
        ↓ swr_convert() / swr_convert_frame()
FFmpegBaseEncoder / FFmpegAACEncoderPlugin (编码器)
        ↓ av_audio_fifo (AAC编码器FIFO缓冲)
ADTS Header 封装 → 编码输出
```

---

## 2. FFmpeg Resample 重采样器（ffmpeg_convert.cpp L247 / ffmpeg_convert.h L98）

### 2.1 ResamplePara 参数结构 (ffmpeg_convert.h L40-49)

```cpp
struct ResamplePara {
    uint32_t channels{2};           // 默认立体声
    uint32_t sampleRate{0};         // 目标采样率
    uint32_t bitsPerSample{0};     // 位深
    AVChannelLayout channelLayout; // 通道布局
    AVSampleFormat srcFfFmt{AV_SAMPLE_FMT_NONE};  // 源格式
    uint32_t destSamplesPerFrame{0};              // 目标帧采样数
    AVSampleFormat destFmt{AV_SAMPLE_FMT_S16};   // 目标格式(默认S16)
};
```

### 2.2 SwrContext 三段初始化 (ffmpeg_convert.cpp L28-55)

**L28-55**: Resample::Init 初始化链
```cpp
// L28: Status Resample::Init(const ResamplePara &resamplePara)
Status Resample::Init(const ResamplePara &resamplePara)
{
    resamplePara_ = resamplePara;
    SwrContext* swrContext = nullptr;
    // L44: swr_alloc_set_opts2 分配并设置重采样参数
    int32_t error = swr_alloc_set_opts2(&swrContext, &resamplePara_.channelLayout,
        resamplePara_.destFmt, resamplePara_.sampleRate,
        resamplePara_.channelLayout, resamplePara_.srcFfFmt,
        resamplePara_.sampleRate, 0, nullptr);
    // L48: swr_init 初始化重采样上下文
    if (swr_init(swrContext) != 0) { ... }
    // L53: swrCtx_ 智能指针封装，自动释放
    swrCtx_ = std::shared_ptr<SwrContext>(swrContext, [](SwrContext *ptr) {
        (void)swr_free(&ptr);
    });
    return Status::OK;
}
```

**L64-78**: Resample::InitSwrContext 备用初始化路径

### 2.3 swr_convert 重采样转换 (ffmpeg_convert.cpp L88-130)

**L88-130**: Resample::Convert 字节级转换
```cpp
// L88: void Resample::ConvertCommon 核心转换函数
// L111: swr_convert 执行实际重采样
auto res = swr_convert(swrCtx_.get(), resampleChannelAddr_.data(), samples,
    tmpInput.data(), samples);

// L123-130: Resample::Convert 公开接口
Status Resample::Convert(const uint8_t *srcBuffer, const size_t srcLength,
    uint8_t *&destBuffer, size_t &destLength)
{
    // ... 内存分配/转换/输出
    swr_convert(swrCtx_.get(), destChannelAddr_.data(), destSamples, srcData, srcSamples);
}
```

### 2.4 swr_convert_frame 帧级转换 (ffmpeg_convert.cpp L165-187)

**L165-187**: Resample::ConvertFrame AVFrame级别转换
```cpp
// L187: swr_convert_frame 直接转换AVFrame
auto ret = swr_convert_frame(swrCtx_.get(), outputFrame, inputFrame);
```

### 2.5 GetSampleOffset 输出采样偏移 (ffmpeg_convert.cpp L193)

**L193**: uint32_t Resample::GetSampleOffset() — 获取重采样输出采样数

---

## 3. AudioCaptureModule 音频采集模块 (audio_capture_module.cpp L509 / audio_capture_module.h L95)

### 3.1 模块定位

AudioCaptureModule 位于 `services/media_engine/modules/source/audio_capture/`，封装 AudioStandard::AudioCapturer，提供 Read/双模式和 GetMaxAmplitude/振幅监测能力，是音频源 Filter 的核心组件。

### 3.2 AudioCapturerCallback 中断回调 (audio_capture_module.cpp L34-56)

**L34-56**: AudioCapturerCallbackImpl 实现 AudioStandard::AudioCapturerCallback
```cpp
// L46-53: OnInterrupt 中断事件处理（静音状态变化/音频焦点中断）
void OnInterrupt(const AudioStandard::InterruptEvent &interruptEvent) override
{
    MEDIA_LOG_E("AudioCapture OnInterrupt Hint: " PUBLIC_LOG_D32 ...
    if (interruptEvent.hintType == AudioStandard::InterruptHint::INTERRUPT_HINT_MUTE ||
        interruptEvent.hintType == AudioStandard::InterruptHint::INTERRUPT_HINT_UNMUTE) {
        MEDIA_LOG_I("AudioCapture OnInterrupt recv mute state change event, ignore...");
        return;  // 静音状态变化被忽略
    }
    if (audioCaptureModuleCallback_ != nullptr) {
        audioCaptureModuleCallback_->OnInterrupt("AudioCapture OnInterrupt");
    }
}
```

### 3.3 Init 初始化 (audio_capture_module.cpp L84-105)

**L84-105**: AudioCaptureModule::Init 创建 AudioCapturer
```cpp
// L84: Status AudioCaptureModule::Init()
Status AudioCaptureModule::Init()
{
    AutoLock lock(captureMutex_);
    if (audioCapturer_ == nullptr) {
        AudioStandard::AppInfo appInfo;
        appInfo.appTokenId = static_cast<uint32_t>(appTokenId_);
        appInfo.appUid = appUid_;
        appInfo.appPid = appPid_;
        appInfo.appFullTokenId = static_cast<uint64_t>(appFullTokenId_);
        options_.capturerInfo.recorderType = AudioStandard::RecorderType::RECORDER_TYPE_AV_RECORDER;
        // L93: AudioStandard::AudioCapturer::Create 创建音频采集器
        audioCapturer_ = AudioStandard::AudioCapturer::Create(options_, appInfo);
        if (audioCapturer_ == nullptr) {
            MEDIA_LOG_E("Create audioCapturer fail");
            SetFaultEvent("AudioCaptureModule::Init, create audioCapturer fail");
            return Status::ERROR_UNKNOWN;
        }
        // L97: AudioInterruptCallback 注册中断回调
        audioInterruptCallback_ = std::make_shared<AudioCapturerCallbackImpl>(audioCaptureModuleCallback_);
    }
    return Status::OK;
}
```

### 3.4 Read/双模式接口 (audio_capture_module.cpp L320-380)

**L320-340**: Read(std::shared_ptr<AVBuffer>&) AVBuffer 接口
```cpp
// L320: Status AudioCaptureModule::Read(std::shared_ptr<AVBuffer> &buffer, size_t expectedLen)
Status AudioCaptureModule::Read(std::shared_ptr<AVBuffer> &buffer, size_t expectedLen)
{
    MEDIA_LOG_D("AudioCaptureModule Read");
    std::shared_ptr<AVMemory> bufData = buffer->memory_;
    auto size = 0;
    {
        AutoLock lock(captureMutex_);
        if (audioCapturer_ == nullptr) { return Status::ERROR_WRONG_STATE; }
        if (audioCapturer_->GetStatus() != AudioStandard::CAPTURER_RUNNING) {
            return Status::ERROR_AGAIN;  // 异步等待
        }
        // L336: audioCapturer_->Read(*bufData->GetAddr(), expectedLen, true)
        size = audioCapturer_->Read(*bufData->GetAddr(), expectedLen, true);
    }
    // L348: TrackMaxAmplitude 振幅跟踪
    if (isTrackMaxAmplitude) {
        TrackMaxAmplitude(reinterpret_cast<int16_t *>(bufData->GetAddr()),
            static_cast<int32_t>(static_cast<uint32_t>(bufData->GetSize()) >> 1));
    }
    return ret;
}
```

**L355-380**: Read(uint8_t*, size_t) 裸指针接口
```cpp
// L355: Status AudioCaptureModule::Read(uint8_t *cacheAudioData, size_t expectedLen)
Status AudioCaptureModule::Read(uint8_t *cacheAudioData, size_t expectedLen)
{
    // L366-370: 裸指针读取 + 振幅跟踪
    size = audioCapturer_->Read(*cacheAudioData, expectedLen, true);
    if (isTrackMaxAmplitude) {
        TrackMaxAmplitude(reinterpret_cast<int16_t *>(cacheAudioData),
            static_cast<int32_t>(static_cast<uint32_t>(size) >> 1));
    }
}
```

### 3.5 GetMaxAmplitude/振幅监测 (audio_capture_module.cpp L456-482)

**L456-470**: GetMaxAmplitude 公开接口
```cpp
// L456: int32_t AudioCaptureModule::GetMaxAmplitude()
int32_t AudioCaptureModule::GetMaxAmplitude()
{
    MEDIA_LOG_D("GetMaxAmplitude");
    // L458-459: 首次调用时启用振幅跟踪
    if (!isTrackMaxAmplitude) {
        isTrackMaxAmplitude = true;
    }
    // L461-462: 读取峰值并清零
    int16_t value = maxAmplitude_;
    maxAmplitude_ = 0;
    return value;
}
```

**L471-482**: TrackMaxAmplitude 内部实现
```cpp
// L471: void AudioCaptureModule::TrackMaxAmplitude(int16_t *data, int32_t size)
void AudioCaptureModule::TrackMaxAmplitude(int16_t *data, int32_t size)
{
    for (int32_t i = 0; i < size; i++) {
        int16_t value = std::abs(data[i]);
        if (maxAmplitude_ < value) {
            maxAmplitude_ = value;  // 持续跟踪最大幅值
        }
    }
}
```

### 3.6 参数适配三函数 (audio_capture_module.cpp L270-315)

**L270**: AssignSampleRateIfSupported — 适配采样率
**L285**: AssignChannelNumIfSupported — 适配通道数
**L305**: AssignSampleFmtIfSupported — 适配采样格式

### 3.7 AudioCaptureModule 头文件关键成员 (audio_capture_module.h L57-86)

```cpp
private:
    Mutex captureMutex_ {};
    std::unique_ptr<OHOS::AudioStandard::AudioCapturer> audioCapturer_ {nullptr};
    std::shared_ptr<AudioStandard::AudioCapturerCallback> audioInterruptCallback_ {nullptr};
    AudioStandard::AudioCapturerOptions options_{};
    std::shared_ptr<AudioCaptureModuleCallback> audioCaptureModuleCallback_ {nullptr};
    int64_t bitRate_ {0};
    int32_t maxAmplitude_ {0};
    bool isTrackMaxAmplitude {false};  // 振幅跟踪开关
};
```

---

## 4. 与 FFmpeg 音频编码器的集成

### 4.1 FFmpegAACEncoderPlugin 中的 Resample 使用 (aac/ffmpeg_aac_encoder_plugin.cpp L571-593)

**L571-593**: AAC编码器中 Resample 初始化与使用
```cpp
// L571-572: Resample 初始化
resample_ = std::make_shared<Ffmpeg::Resample>();
if (resample_->Init(resamplePara) != Status::OK) { ... }

// L792-793: 重采样转换
if (needResample_ && resample_ != nullptr) {
    if (resample_->Convert(srcBuffer, srcBufferSize, destBuffer, destBufferSize) != Status::OK) {
        return Status::ERROR_UNKNOWN;
    }
}

// L805-806: 获取重采样输出采样偏移
destSamplesPerFrame = resample_->GetSampleOffset();
```

### 4.2 av_audio_fifo AAC编码器缓冲 (aac/ffmpeg_aac_encoder_plugin.cpp L694-748)

**L694-748**: AVAudioFifo 作为编码器输入缓冲
```cpp
// L694-697: av_audio_fifo_alloc 创建 FIFO
if (!(fifo_ = av_audio_fifo_alloc(
    avCodecContext_->sample_fmt,
    avCodecContext_->ch_layout.nb_channels,
    AAC_FRAME_SIZE))) { ... }

// L747-748: av_audio_fifo_realloc 动态扩容
int32_t cacheSize = av_audio_fifo_size(fifo_);
av_audio_fifo_realloc(fifo_, cacheSize + cachedFrame_->nb_samples);

// L761: av_audio_fifo_read 从FIFO读取编码帧
av_audio_fifo_read(fifo_, reinterpret_cast<void **>(cachedFrame_->data), avCodecContext_->frame_size);

// L826: av_audio_fifo_write 写入FIFO
av_audio_fifo_write(fifo_, reinterpret_cast<void **>(cachedFrame_->data), cachedFrame_->nb_samples);
```

---

## 5. 关键行号级 Evidence 汇总

| # | 文件 | 行号 | 证据内容 |
|---|------|------|---------|
| E1 | ffmpeg_convert.cpp | L28-55 | Resample::Init — swr_alloc_set_opts2/swr_init/swrCtx_封装 |
| E2 | ffmpeg_convert.cpp | L88-130 | Resample::Convert — swr_convert 字节级转换 |
| E3 | ffmpeg_convert.cpp | L165-187 | Resample::ConvertFrame — swr_convert_frame AVFrame转换 |
| E4 | ffmpeg_convert.cpp | L193 | Resample::GetSampleOffset — 输出采样偏移 |
| E5 | ffmpeg_convert.h | L40-49 | ResamplePara 参数结构 |
| E6 | audio_capture_module.cpp | L34-56 | AudioCapturerCallbackImpl::OnInterrupt — 中断处理 |
| E7 | audio_capture_module.cpp | L84-105 | AudioCaptureModule::Init — AudioCapturer::Create |
| E8 | audio_capture_module.cpp | L320-348 | Read(AVBuffer&) — AVBuffer接口+振幅跟踪 |
| E9 | audio_capture_module.cpp | L355-380 | Read(uint8_t*) — 裸指针接口+振幅跟踪 |
| E10 | audio_capture_module.cpp | L456-470 | GetMaxAmplitude — 峰值读取+清零 |
| E11 | audio_capture_module.cpp | L471-482 | TrackMaxAmplitude — 16bit PCM逐样本峰值跟踪 |
| E12 | audio_capture_module.cpp | L270-315 | AssignSampleRate/ChannelNum/SampleFmt — 三参适配 |
| E13 | audio_capture_module.h | L57-86 | AudioCaptureModule 私有成员定义 |
| E14 | aac/ffmpeg_aac_encoder_plugin.cpp | L571-593 | AAC编码器中Resample初始化+转换调用 |
| E15 | aac/ffmpeg_aac_encoder_plugin.cpp | L694-748 | av_audio_fifo_alloc/read/write/realloc — FIFO操作 |
| E16 | aac/ffmpeg_aac_encoder_plugin.cpp | L37 | ADTS_HEADER_SIZE = 7 |
| E17 | aac/ffmpeg_aac_encoder_plugin.cpp | L102-120 | GetAdtsHeader — ADTS 7字节头构造 |
| E18 | audio_capture_module.cpp | L170 | isTrackMaxAmplitude初始化为false |

---

## 6. 架构图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Audio Source Pipeline                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  AudioStandard::AudioCapturer (原生音频硬件采集)                             │
│          │                                                                    │
│          │ audioCapturer_->Read()                                           │
│          ↓                                                                    │
│  AudioCaptureModule::Read(AVBuffer&) / Read(uint8_t*, size_t)               │
│          │                                                                    │
│          ├──→ TrackMaxAmplitude(int16_t*, size)  [L471]                     │
│          │        maxAmplitude_ 持续更新                                      │
│          │                                                                    │
│          └──→ GetMaxAmplitude() [L456]  // 上层查询峰值                      │
│                   返回maxAmplitude_并清零                                     │
│                                                                              │
├─────────────────────────────────────────────────────────────────────────────┤
│  Resample (SwrContext)  ffmpeg_convert.cpp L247                             │
│          │                                                                    │
│          │ resample_->Init(ResamplePara)                                    │
│          │   swr_alloc_set_opts2() → swr_init() → swrCtx_ [L28-55]          │
│          │                                                                    │
│          ├──→ swr_convert() 字节级转换 [L111]                                │
│          └──→ swr_convert_frame() AVFrame级转换 [L187]                       │
│                   GetSampleOffset() [L193]                                    │
│                                                                              │
├─────────────────────────────────────────────────────────────────────────────┤
│  FFmpegAACEncoderPlugin (aac/ffmpeg_aac_encoder_plugin.cpp L902)            │
│          │                                                                    │
│          ├──→ av_audio_fifo_alloc() [L694]                                   │
│          │        AVAudioFifo 输入缓冲                                        │
│          ├──→ av_audio_fifo_write() [L826]                                   │
│          │        PCM数据写入FIFO                                             │
│          ├──→ av_audio_fifo_read() [L761]                                    │
│          │        从FIFO供给编码器                                             │
│          │                                                                    │
│          └──→ GetAdtsHeader() [L102-120]                                    │
│                   ADTS 7字节头封装                                            │
│                   frameLength = aacLength + 7                                │
│                   0xFFF1 + profile/freqIdx/chanCfg                           │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 7. 关键数据流

1. **音频采集**: AudioStandard::AudioCapturer → AudioCaptureModule::Read()
2. **振幅监测**: Read() → TrackMaxAmplitude() → maxAmplitude_ → GetMaxAmplitude() → 上层查询
3. **重采样**: Resample::Init(swr_alloc_set_opts2) → swr_init → swr_convert/swr_convert_frame
4. **编码缓冲**: PCM → av_audio_fifo_write → av_audio_fifo_read → avcodec_send_frame
5. **ADTS封装**: 编码输出 → GetAdtsHeader(7字节) → 拼接编码帧 → AAC bitstream

---

## 8. 关联引用

- S125/S130: FFmpegDecoder/FFmpeg Base 架构基础
- S132/S158/S176: FFmpeg Audio Encoder Plugin 体系
- S119: AudioSampleFormat + CalcMaxAmplitude (独立振幅计算)
- S147: DataSink + MediaMuxer + AudioCaptureModule 三组件关联
- S182: HLS Playlist Downloader (Playlist 下载管理)

---

_build_time: 2026-05-25T14:50 Asia/Shanghai_
_builder: builder-agent
_memory_type: architecture
_version: 1.0_