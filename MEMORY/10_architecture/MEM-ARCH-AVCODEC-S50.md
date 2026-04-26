---
id: MEM-ARCH-AVCODEC-S50
title: "AudioResample 音频重采样框架——SwrContext/libswresample 与 AudioBuffersManager 双组件协作"
scope: [AVCodec, AudioCodec, AudioResample, SwrContext, libswresample, AudioBuffersManager, AudioBufferInfo, FFmpeg, SampleRate, ChannelLayout]
status: pending_approval
created_by: builder-agent
created_at: "2026-04-26T14:52:00+08:00"
---

# MEM-ARCH-AVCODEC-S50: AudioResample 音频重采样框架——SwrContext/libswresample 与 AudioBuffersManager 双组件协作

## 1. 概述

AVCodec 音频编解码链路中，输入/输出音频格式（采样率、声道布局、采样格式）与目标格式可能不一致。AudioResample 组件基于 FFmpeg libswresample 实现实时音频重采样，将音频帧从源格式转换为目标格式。AudioBuffersManager 则管理音频编解码器的输入/输出缓冲区队列，负责缓冲区的申请、状态追踪与回收。两者构成音频 Codec 引擎的双核心支撑组件。

**适用场景**：
- 三方应用接入：音频格式不匹配时（如录音输入 48kHz/PLANAR 输出 AAC 需要 44100Hz/INTERLEAVED）
- 问题定位：音频杂音/无声/卡顿常因重采样参数错误或缓冲区耗尽
- 新需求开发：接入新音频编码器（如 Opus/FLAC）需理解 AudioBuffersManager 的双缓冲队列机制

## 2. 核心机制

### 2.1 AudioResample：libswresample 封装

**证据**：`services/engine/codec/include/audio/audio_resample.h`

```cpp
struct ResamplePara {
    uint32_t channels {2};           // 声道数，默认 2（STEREO）
    int32_t sampleRate {0};          // 目标采样率
    int32_t bitsPerSample {0};       // 采样位深
    AVChannelLayout channelLayout;   // FFmpeg 声道布局
    AVSampleFormat srcFmt {AV_SAMPLE_FMT_NONE};   // 源采样格式
    int32_t destSamplesPerFrame {0}; // 目标每帧样本数
    AVSampleFormat destFmt {AV_SAMPLE_FMT_S16};   // 目标采样格式
};

class AudioResample {
public:
    int32_t Init(const ResamplePara& resamplePara);
    int32_t Convert(const uint8_t* srcBuffer, const size_t srcLength,
                    uint8_t*& destBuffer, size_t& destLength);
    int32_t InitSwrContext(const ResamplePara& resamplePara);
    int32_t ConvertFrame(AVFrame *outputFrame, const AVFrame *inputFrame);
private:
    ResamplePara resamplePara_ {};
    std::vector<uint8_t> resampleCache_ {};      // 重采样输出缓存
    std::vector<uint8_t*> resampleChannelAddr_ {}; // 声道地址数组（planar 格式）
    std::shared_ptr<SwrContext> swrCtx_ {nullptr}; // FFmpeg SwrContext 智能指针
};
```

**关键**：SwrContext 使用 `std::shared_ptr` 管理生命周期，自定义删除器调用 `swr_free()`，避免内存泄漏。

### 2.2 InitSwrContext：FFmpeg 重采样上下文初始化

**证据**：`services/engine/codec/audio/audio_resample.cpp` 行 35-60

```cpp
int32_t AudioResample::InitSwrContext(const ResamplePara& resamplePara)
{
    resamplePara_ = resamplePara;
    SwrContext *swrContext = swr_alloc();
    if (swrContext == nullptr) {
        AVCODEC_LOGE("cannot allocate swr context");
        return AVCodecServiceErrCode::AVCS_ERR_NO_MEMORY;
    }
    int error = swr_alloc_set_opts2(&swrContext,
        &resamplePara_.channelLayout,   // 输出声道布局
        resamplePara_.destFmt,           // 输出采样格式
        resamplePara_.sampleRate,        // 输出采样率
        &resamplePara_.channelLayout,   // 输入声道布局
        resamplePara_.srcFmt,            // 输入采样格式
        resamplePara_.sampleRate,        // 输入采样率
        0, nullptr);                     // 日志上下文
    if (error < 0) {
        AVCODEC_LOGE("swr init error");
        return AVCodecServiceErrCode::AVCS_ERR_UNKNOWN;
    }
    if (swr_init(swrCtx_) != 0) {
        AVCODEC_LOGE("swr init error");
        swr_free(&swrContext);
        return AVCodecServiceErrCode::AVCS_ERR_UNKNOWN;
    }
    swrCtx_ = std::shared_ptr<SwrContext>(swrContext, [](SwrContext *ptr) {
        if (ptr) swr_free(&ptr);
    });
    return AVCodecServiceErrCode::AVCS_ERR_OK;
}
```

### 2.3 Convert：字节级重采样

**证据**：`services/engine/codec/audio/audio_resample.cpp` 行 62-82

```cpp
int32_t AudioResample::Convert(const uint8_t* srcBuffer, const size_t srcLength,
                               uint8_t*& destBuffer, size_t& destLength)
{
    size_t lineSize = srcLength / resamplePara_.channels;
    std::vector<const uint8_t*> tmpInput(resamplePara_.channels);
    tmpInput[0] = srcBuffer;
    // Planar 格式：每声道数据分开存储，需要计算偏移量
    if (av_sample_fmt_is_planar(resamplePara_.srcFmt)) {
        for (size_t i = 1; i < tmpInput.size(); ++i) {
            tmpInput[i] = tmpInput[i-1] + lineSize;
        }
    }
    int32_t samples = static_cast<int32_t>(lineSize) / av_get_bytes_per_sample(resamplePara_.srcFmt);
    // swr_convert：FFmpeg 重采样核心函数
    auto res = swr_convert(swrCtx_.get(), resampleChannelAddr_.data(),
                           resamplePara_.destSamplesPerFrame,
                           tmpInput.data(), samples);
    if (res < 0) {
        destLength = 0;
        return AVCodecServiceErrCode::AVCS_ERR_OK; // 仍返回 OK，日志在 FFmpeg 层
    }
    destBuffer = resampleCache_.data();
    destLength = static_cast<size_t>(res * av_get_bytes_per_sample(resamplePara_.destFmt))
                 * resamplePara_.channels;
    return AVCodecServiceErrCode::AVCS_ERR_OK;
}
```

### 2.4 ConvertFrame：AVFrame 级重采样（用于解码器输出）

**证据**：`services/engine/codec/audio/audio_resample.cpp`

```cpp
int32_t AudioResample::ConvertFrame(AVFrame *outputFrame, const AVFrame *inputFrame)
{
    if (outputFrame == nullptr || inputFrame == nullptr) {
        AVCODEC_LOGE("Frame null pointer");
        return AVCodecServiceErrCode::AVCS_ERR_NO_MEMORY;
    }
    // 直接使用 FFmpeg AVFrame 进行重采样，无需手动展开 Planar 数据
    auto res = swr_convert(swrCtx_.get(),
                           outputFrame->data,    // 输出数据指针数组
                           outputFrame->nb_samples, // 输出帧容量
                           inputFrame->data,      // 输入数据指针数组
                           inputFrame->nb_samples);// 输入帧样本数
    return (res >= 0) ? AVCodecServiceErrCode::AVCS_ERR_OK
                       : AVCodecServiceErrCode::AVCS_ERR_UNKNOWN;
}
```

## 3. 重采样触发条件判定

### 3.1 AudioFFMpegAacEncoderPlugin::CheckResample

**证据**：`services/engine/codec/audio/encoder/audio_ffmpeg_aac_encoder_plugin.cpp`

```cpp
bool AudioFFMpegAacEncoderPlugin::CheckResample() const
{
    if (avCodec_ == nullptr || avCodecContext_ == nullptr) {
        return false;
    }
    // 遍历编码器支持的采样格式，若输入格式不在支持列表中则需要重采样
    for (size_t index = 0; avCodec_->sample_fmts[index] != AV_SAMPLE_FMT_NONE; ++index) {
        if (avCodec_->sample_fmts[index] == srcFmt_) {
            return false;  // 不需要重采样
        }
    }
    return true;  // 需要重采样
}
```

**触发时机**：编码器初始化时（Configure 阶段），根据输入音频格式与编码器原生格式对比决定。

### 3.2 AudioFFMpegDecoderPlugin 延迟初始化

**证据**：`services/engine/codec/audio/decoder/audio_ffmpeg_decoder_plugin.cpp` 行 343-360

```cpp
// 解码器首次收到有效输出帧时才初始化重采样器（延迟初始化）
int32_t AudioFfmpegDecoderPlugin::InitResample()
{
    if (needResample_) {
        ResamplePara resamplePara = {
            .channels = avCodecContext_->ch_layout.nb_channels,
            .sampleRate = avCodecContext_->sample_rate,
            .bitsPerSample = 0,
            .channelLayout = avCodecContext_->ch_layout,
            .srcFmt = avCodecContext_->sample_fmt,   // 以解码器输出格式为源格式
            .destSamplesPerFrame = 0,
            .destFmt = destFmt_,                     // 目标格式由外部指定
        };
        resample_ = std::make_shared<AudioResample>();
        if (resample_->InitSwrContext(resamplePara) != AVCodecServiceErrCode::AVCS_ERR_OK) {
            return AVCodecServiceErrCode::AVCS_ERR_UNKNOWN;
        }
    }
    return AVCodecServiceErrCode::AVCS_ERR_OK;
}
```

**解码器特殊处理**：解码器的重采样器在 `ReceiveFrameSucc()` 中首次发现需要重采样时才创建，而非提前初始化。

## 4. AudioBuffersManager：音频缓冲区管理

### 4.1 双缓冲队列架构

**证据**：`services/engine/codec/audio/audio_codec_worker.cpp` 行 49-50

```cpp
AudioCodecWorker::AudioCodecWorker(const std::shared_ptr<AudioBaseCodec> &codec, ...)
    : ...
      inputBuffer_(std::make_shared<AudioBuffersManager>(inputBufferSize, INPUT_BUFFER, DEFAULT_BUFFER_COUNT)),
      outputBuffer_(std::make_shared<AudioBuffersManager>(outputBufferSize, OUTPUT_BUFFER, DEFAULT_BUFFER_COUNT))
```

每个 AudioCodecWorker 持有两个 AudioBuffersManager 实例：
- `inputBuffer_`：管理输入缓冲区（待编码/待解码的原始音频数据）
- `outputBuffer_`：管理输出缓冲区（已编码/已解码的音频数据）

### 4.2 AudioBuffersManager 核心接口

**证据**：`services/engine/codec/include/audio/audio_buffers_manager.h`

```cpp
class AudioBuffersManager : public NoCopyable {
public:
    AudioBuffersManager(const uint32_t bufferSize, const std::string_view &name,
                        const uint16_t count, const uint32_t metaSize = 0);
    ~AudioBuffersManager();

    std::shared_ptr<AudioBufferInfo> getMemory(const uint32_t &index) const noexcept;
    bool ReleaseBuffer(const uint32_t &index);
    bool SetBufferBusy(const uint32_t &index);
    bool RequestNewBuffer(uint32_t &index, std::shared_ptr<AudioBufferInfo> &buffer);
    bool RequestAvailableIndex(uint32_t &index);
    void ReleaseAll();
    void SetRunning();
    void DisableRunning();

private:
    std::atomic<bool> isRunning_;
    std::condition_variable availableCondition_;
    std::queue<uint32_t> inBufIndexQue_;         // 可用 buffer index 队列（FIFO）
    std::vector<bool> inBufIndexExist;            // 每个 index 的存在性标记
    const uint16_t bufferCount_;                   // 固定 buffer 数量
    uint32_t bufferSize_;                          // 每个 buffer 大小（字节）
    uint32_t metaSize_;                            // 元数据区大小
    std::string_view name_;                        // "INPUT_BUFFER" / "OUTPUT_BUFFER"
    std::vector<std::shared_ptr<AudioBufferInfo>> bufferInfo_; // 实际 buffer 对象数组
};
```

### 4.3 AudioBufferInfo：单个缓冲区元数据

**证据**：`services/engine/codec/include/audio/audio_buffer_info.h`

```cpp
class AudioBufferInfo : public NoCopyable {
    std::atomic<bool> isUsing;                        // 是否被占用
    std::atomic<BufferStatus> status_;                // 缓冲区状态
    bool isEos_;                                      // 是否处于 EOS 状态
    bool isFirstFrame_;                               // 是否为第一帧
    uint32_t bufferSize_;
    uint32_t metaSize_;
    std::shared_ptr<Media::AVSharedMemoryBase> buffer_;   // 实际音频数据内存
    std::shared_ptr<Media::AVSharedMemoryBase> metadata_; // 元数据内存
    AVCodecBufferInfo info_;                          // PTS / offset / size
    AVCodecBufferFlag flag_;                          // 缓冲区标志（KEY_FRAME/EOS 等）
};
```

## 5. 数据流：AudioResample + AudioBuffersManager 协作

```
[应用层]
    │
    │ PushInputData(index) → AudioCodecWorker::HandInputBuffer
    ▼
[inputBuffer_ (AudioBuffersManager)]
    │ RequestAvailableIndex() → inBufIndexQue_.pop()
    │ getMemory(index) → AudioBufferInfo
    │ codec_->ProcessSendData(inputBuffer)  ← 原始 PCM 数据（可能格式不匹配）
    ▼
[AudioCodec 内部]
    │
    │ (如需要重采样)
    │ AudioResample::Convert() 或 AudioResample::ConvertFrame()
    │ swr_convert() → 源格式 → 目标格式
    ▼
[outputBuffer_ (AudioBuffersManager)]
    │ ReleaseOutputBuffer(index)
    │ callback_->OnOutputBufferAvailable(outBuffer)
    ▼
[应用层消费]
    │ ReleaseBuffer(index) → inBufIndexQue_.push(index) → 归还队列
```

## 6. 与其他记忆条目的关联

| 条目 | 关联点 |
|------|--------|
| **MEM-ARCH-AVCODEC-S8**（音频 FFmpeg 插件） | AudioFFMpegAacEncoderPlugin / AudioFfmpegDecoderPlugin 使用 AudioResample |
| **MEM-ARCH-AVCODEC-S18**（AudioCodecServer） | AudioCodecWorker 是 AudioCodecServer 的内部工作引擎 |
| **MEM-ARCH-AVCODEC-S35**（AudioDecoderFilter） | AudioDecoderFilter 的 Filter 层之下是 AudioCodecWorker，AudioBuffersManager 是 Worker 的双缓冲管理组件 |

## 7. 相关文件索引

| 文件 | 作用 |
|------|------|
| `services/engine/codec/include/audio/audio_resample.h` | AudioResample 类声明 + ResamplePara 结构体 |
| `services/engine/codec/audio/audio_resample.cpp` | FFmpeg SwrContext 封装实现 |
| `services/engine/codec/include/audio/audio_buffers_manager.h` | AudioBuffersManager 类声明 + 队列管理 |
| `services/engine/codec/include/audio/audio_buffer_info.h` | AudioBufferInfo 单缓冲区元数据 |
| `services/engine/codec/audio/audio_codec_worker.cpp` | AudioCodecWorker 双 AudioBuffersManager 实例化 |
| `services/engine/codec/audio/encoder/audio_ffmpeg_aac_encoder_plugin.cpp` | AAC 编码器中 CheckResample + AudioResample 初始化 |
| `services/engine/codec/audio/decoder/audio_ffmpeg_decoder_plugin.cpp` | 解码器中延迟 AudioResample 初始化 + ConvertFrame |

## 8. 关键调试参数

```bash
# 重采样相关日志关键字
"Resample init failed"        # AudioResample 初始化失败
"swr init error"               # FFmpeg swr_init 失败
"convert frame failed"          # 重采样转换失败
"Resmaple init failed"         # AAC 编码器重采样初始化失败
"recode output description"    # 解码器首次发现需要重采样（延迟初始化触发）
"swr_convert"                  # 配合 FFmpeg 日志查看

# 缓冲区相关日志关键字
"PushInputData"                # 输入 buffer 入队
"ProduceInputBuffer"            # Worker 生产输入 buffer
"ConsumerOutputBuffer"         # Worker 消费输出 buffer
"ReleaseOutputBuffer"          # 输出 buffer 释放
"RequestNewBuffer"             # 动态申请新 buffer
"inBufIndexQue_"               # 配合队列大小变化日志
"isUsing"                      # 配合原子操作日志
```

---

## 变更记录

| 日期 | 操作 | 说明 |
|------|------|------|
| 2026-04-26T14:52 | 新建草案 | builder-agent 从 audio_resample.h/cpp、audio_buffers_manager.h、audio_codec_worker.cpp 提取 AudioResample（libswresample 封装）与 AudioBuffersManager 双组件协作证据 |
