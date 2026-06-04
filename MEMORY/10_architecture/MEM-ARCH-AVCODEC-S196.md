# MEM-ARCH-AVCODEC-S196

## ID & Metadata

- **id**: MEM-ARCH-AVCODEC-S196
- **subject**: FFmpeg Adapter Muxer Plugin 三层架构——FFmpegMuxerPlugin+MPEG4MuxerPlugin+FFmpegMuxerRegister(AVFMT_FLAG_CUSTOM_IO/ADTS/AVAudioFifo/PCM缓存模式)
- **status**: pending_approval
- **created**: 2026-06-04T19:20:00+08:00
- **scope**: AVCodec, FFmpeg, MuxerPlugin, FFmpegAdapter, MPEG4, ISOBMFF, Box, libavformat, avcodec_send_frame, avcodec_receive_frame, Track, DataSink, ADTS, AudioFifo, SwrContext
- **关联主题**: S91/S145/S131/S130/S125/S181/S183/S158/S169/S176

---

## 摘要

FFmpeg Adapter Muxer Plugin 体系是 AVCodec 封装模块的核心组件，由三层架构构成：

1. **FFmpegMuxerRegister**（注册机层）：PLUGIN_DEFINITION 宏驱动，通过 av_muxer_iterate 遍历 FFmpeg 支持的封装格式，IoOpen/IoClose/InitAvIoCtx 三函数构建自定义 AVIOContext
2. **FFmpegMuxerPlugin**（封装修复器层）：持有 AVFormatContext，AVFMT_FLAG_CUSTOM_IO 标志启用自定义 IO，NAL_START_PATTERN 处理，cachePacket_ 双缓冲
3. **FFmpegBaseEncoder**（音频编码器基类）：avcodec_send_frame/avcodec_receive_frame 管线，avMutext_ 线程安全，PCM 缓存 + SwrContext 重采样

---

## 架构组件

### 1. FFmpegMuxerRegister（注册机）

文件：`services/media_engine/plugins/ffmpeg_adapter/muxer/ffmpeg_muxer_register.cpp` + `.h`

**E1** - `ffmpeg_muxer_register.h:L28-35` - `IOContext` 结构体
```cpp
struct IOContext {
    std::shared_ptr<DataSink> dataSink_ {};
    int64_t pos_ {0};
    int64_t end_ {0};
};
```

**E2** - `ffmpeg_muxer_register.h:L42-43` - `pluginOutputFmt_` 单例映射 + `supportedMuxer_` 白名单
```cpp
static std::map<std::string, std::shared_ptr<AVOutputFormat>> pluginOutputFmt_;
static std::set<std::string> supportedMuxer_;
```

**E3** - `ffmpeg_muxer_register.cpp:L39-43` - `supportedMuxer_` 九格式白名单
```cpp
std::set<std::string> FFmpegMuxerRegister::supportedMuxer_ = {
    "mp4", "ipod", "amr", "mp3", "wav", "adts", "flac", "ogg", "flv"
};
```

**E4** - `ffmpeg_muxer_register.cpp:L25-29` - PLUGIN_DEFINITION 宏注册
```cpp
PLUGIN_DEFINITION(FFmpegMuxer, LicenseType::LGPL,
    FFmpegMuxerRegister::RegisterMuxerPlugins, FFmpegMuxerRegister::UnregisterMuxerPlugins)
```

**E5** - `ffmpeg_muxer_register.cpp:L83-115` - `RegisterMuxerPlugins()` av_muxer_iterate 遍历注册
```cpp
void* ite = nullptr;
while ((outputFormat = av_muxer_iterate(&ite))) {
    if (!IsMuxerSupported(outputFormat->name)) { continue; }
    // 插件名称构造：ffmpegMux_ + formatName
    std::string pluginName = "ffmpegMux_" + std::string(outputFormat->name);
    def.SetCreator([](const std::string &name) -> std::shared_ptr<MuxerPlugin> {
        if (name == "ffmpegMux_flv") {
            return std::make_shared<FFmpegFlvMuxerPlugin>(name);
        }
        return std::make_shared<FFmpegMuxerPlugin>(name);
    });
    reg->AddPlugin(def);
    pluginOutputFmt_[pluginName] = std::shared_ptr<AVOutputFormat>(
        const_cast<AVOutputFormat*>(outputFormat), [](AVOutputFormat* ptr) {});
}
```

**E6** - `ffmpeg_muxer_register.h:L37-41` - `IoOpen/IoClose/InitAvIoCtx` 静态函数声明（AVIOContext 三函数）
```cpp
static AVIOContext* InitAvIoCtx(const std::shared_ptr<DataSink> &dataSink, int writeFlags);
static void DeInitAvIoCtx(AVIOContext* ptr);
static int32_t IoOpen(AVFormatContext* s, AVIOContext** pb, const char* url, int flags, AVDictionary** options);
static int IoClose(AVFormatContext* s, AVIOContext* pb);
```

**E7** - `ffmpeg_muxer_register.h:L48-50` - `IOContext` 三函数指针（读写定位）
```cpp
static int32_t IoRead(void* opaque, uint8_t* buf, int bufSize);
static int32_t IoWrite(void* opaque, const uint8_t* buf, int bufSize);
static int64_t IoSeek(void* opaque, int64_t offset, int whence);
```

### 2. FFmpegMuxerPlugin（封装修复器）

文件：`services/media_engine/plugins/ffmpeg_adapter/muxer/ffmpeg_muxer_plugin.cpp`

**E8** - `ffmpeg_muxer_plugin.cpp:L51-65` - 构造函数：AVFMT_FLAG_CUSTOM_IO + AVFormatContext 初始化
```cpp
FFmpegMuxerPlugin::FFmpegMuxerPlugin(std::string name)
    : MuxerPlugin(std::move(name)), isWriteHeader_(false)
{
    av_log_set_callback(FFmpegMuxerRegister::FfmpegLogPrintWithLevel);
    cachePacket_ = std::shared_ptr<AVPacket>(pkt, [] (AVPacket *packet) {av_packet_free(&packet);});
    outputFormat_ = FFmpegMuxerRegister::GetAVOutputFormat(pluginName_);
    auto fmt = avformat_alloc_context();
    fmt->pb = nullptr;
    fmt->oformat = outputFormat_.get();
    fmt->flags = static_cast<uint32_t>(fmt->flags) | static_cast<uint32_t>(AVFMT_FLAG_CUSTOM_IO);
    fmt->io_open = FFmpegMuxerRegister::IoOpen;
    fmt->io_close2 = FFmpegMuxerRegister::IoClose;
    formatContext_ = std::shared_ptr<AVFormatContext>(fmt, ...);
    av_log_set_level(AV_LOG_ERROR);
}
```

**E9** - `ffmpeg_muxer_plugin.cpp:L49-52` - NAL_START_PATTERN 起始码常量（AnnexB NALU 边界标识）
```cpp
constexpr uint32_t NAL_START_PATTERN = 0x01000100;
constexpr uint32_t BITWISE_NOT_NAL_START_PATTERN = ~0x01000100;
constexpr uint32_t NAL_MATCH_MASK = 0x80008000U;
```

**E10** - `ffmpeg_muxer_plugin.cpp:L95-98` - `SetDataSink()` 自定义 IO 绑定
```cpp
Status FFmpegMuxerPlugin::SetDataSink(const std::shared_ptr<DataSink> &dataSink)
{
    FFmpegMuxerRegister::DeInitAvIoCtx(formatContext_->pb);
    formatContext_->pb = FFmpegMuxerRegister::InitAvIoCtx(dataSink, 1);
    canReadFile_ = dataSink->CanRead();
    return Status::NO_ERROR;
}
```

**E11** - `ffmpeg_muxer_plugin.cpp:L100-128` - `SetParameter()` 元数据参数（旋转/位置/编辑列表/AIGC）
```cpp
Status FFmpegMuxerPlugin::SetParameter(const std::shared_ptr<Meta> &param)
{
    if (param->GetData(Tag::MEDIA_ENABLE_MOOV_FRONT, dataInt) && dataInt == 1) {
        isFastStart_ = true; // moov 前置优化
    }
    if (param->GetData("use_timed_meta_track", dataInt) && dataInt == 1) {
        useTimedMetadata_ = true;
    }
    // 旋转 / 地理位置 / AIGC 标记 ...
}
```

**E12** - `ffmpeg_muxer_plugin.cpp:L130-145` - `SetRotation()` 旋转角度校验（0/90/180/270）
```cpp
Status FFmpegMuxerPlugin::SetRotation(std::shared_ptr<Meta> param)
{
    if (param->Find(Tag::VIDEO_ROTATION) != param->end()) {
        param->Get<Tag::VIDEO_ROTATION>(rotation_);
        if (rotation_ != VIDEO_ROTATION_0 && rotation_ != VIDEO_ROTATION_90 &&
            rotation_ != VIDEO_ROTATION_180 && rotation_ != VIDEO_ROTATION_270) {
            MEDIA_LOG_W("Invalid rotation");
            return Status::ERROR_INVALID_DATA;
        }
    }
    return Status::NO_ERROR;
}
```

### 3. FFmpegBaseEncoder（音频编码基类）

文件：`services/media_engine/plugins/ffmpeg_adapter/audio_encoder/ffmpeg_base_encoder.cpp`

**E13** - `ffmpeg_base_encoder.cpp:L33-40` - 构造函数：avCodec_/avCodecContext_/cachedFrame_/avPacket_ 初始化
```cpp
FFmpegBaseEncoder::FFmpegBaseEncoder()
    : maxInputSize_(-1), avCodec_(nullptr), avCodecContext_(nullptr),
      cachedFrame_(nullptr), avPacket_(nullptr), prevPts_(0), codecContextValid_(false)
{ }
```

**E14** - `ffmpeg_base_encoder.cpp:L55-90` - `ProcessSendData()` avMutext_ 线程安全 + PCM 缓存机制
```cpp
Status FFmpegBaseEncoder::ProcessSendData(const std::shared_ptr<AVBuffer> &inputBuffer)
{
    std::lock_guard<std::mutex> lock(avMutext_);  // 线程安全
    if (!enableCache_) {
        ret = SendBuffer(inputBuffer);
    } else {
        bool isEos = inputBuffer->flag_ & BUFFER_FLAG_EOS;
        if (isEnableFormatConvert_ && srcSampleFormat_ != dstSampleFormat_) {
            // PCM 格式转换：ConvertPcmSampleFormat
            convertBuffer_.resize(dstBufferSize);
            ConvertPcmSampleFormat(...);
            pcmCache_.insert(pcmCache_.end(), convertBuffer_.begin(), convertBuffer_.end());
        } else {
            pcmCache_.insert(pcmCache_.end(), memory->GetAddr(), memory->GetAddr() + memory->GetSize());
        }
        ret = SendCachedFrames();
    }
    return ret;
}
```

**E15** - `ffmpeg_base_encoder.cpp:L118-158` - `PcmFillFrame()` 分帧 + 格式转换
```cpp
Status FFmpegBaseEncoder::PcmFillFrame(const std::shared_ptr<AVBuffer> &inputBuffer)
{
    if (isEnableFormatConvert_ && srcSampleFormat_ != dstSampleFormat_) {
        size_t inputSampleCnt = srcBufferSize / srcBytesPerSample_;
        size_t dstBufferSize = GetPcmConvertOutputSize(inputSampleCnt, dstSampleFormat_);
        convertBuffer_.resize(dstBufferSize);
        ConvertPcmSampleFormat(memory->GetAddr(), inputSampleCnt, srcSampleFormat_, dstSampleFormat_, convertBuffer_.data());
        cachedFrame_->nb_samples = static_cast<int>(dstBufferSize / channelsBytesPerSample_);
        cachedFrame_->data[0] = convertBuffer_.data();
    } else {
        cachedFrame_->nb_samples = usedSize / channelsBytesPerSample_;
        cachedFrame_->data[0] = memory->GetAddr();
    }
    return Status::OK;
}
```

**E16** - `ffmpeg_base_encoder.cpp:L162-195` - `SendBuffer()` avcodec_send_frame 管线
```cpp
Status FFmpegBaseEncoder::SendBuffer(const std::shared_ptr<AVBuffer> &inputBuffer)
{
    int ret = av_frame_make_writable(cachedFrame_.get());
    if (!isEos) {
        auto errCode = PcmFillFrame(inputBuffer);
        ret = avcodec_send_frame(avCodecContext_.get(), cachedFrame_.get());
    } else {
        ret = avcodec_send_frame(avCodecContext_.get(), nullptr); // EOS
    }
    if (ret == 0) { return Status::OK; }
    else if (ret == AVERROR(EAGAIN)) { return Status::ERROR_NOT_ENOUGH_DATA; }
    else if (ret == AVERROR_EOF) { return Status::END_OF_STREAM; }
    else { return Status::ERROR_UNKNOWN; }
}
```

### 4. FFmpegConvert / Resample（重采样）

文件：`services/media_engine/plugins/ffmpeg_adapter/common/ffmpeg_convert.cpp`

**E17** - `ffmpeg_convert.cpp:L28-53` - `InitSwrContext()` SwrContext 初始化（libswresample）
```cpp
Status Resample::InitSwrContext(const ResamplePara &resamplePara)
{
    auto swrContext = swr_alloc();
    int32_t error = swr_alloc_set_opts2(&swrContext,
        &resamplePara_.channelLayout, resamplePara_.destFmt, resamplePara_.sampleRate,
        &resamplePara_.channelLayout, resamplePara_.srcFfFmt, resamplePara_.sampleRate,
        0, nullptr);
    CHECK_AND_RETURN_RET_LOG(error >= 0, Status::ERROR_UNKNOWN, "swr init error");
    if (swr_init(swrContext) != 0) {
        swr_free(&swrContext);
        return Status::ERROR_UNKNOWN;
    }
    swrCtx_ = std::shared_ptr<SwrContext>(swrContext, [](SwrContext *ptr) { swr_free(&ptr); });
    return Status::OK;
}
```

**E18** - `ffmpeg_convert.cpp:L77-98` - `ConvertCommon()` Planar 格式分通道处理 + swr_convert
```cpp
void Resample::ConvertCommon(const uint8_t *srcBuffer, const size_t srcLength,
    uint8_t *&destBuffer, size_t &destLength)
{
    if (av_sample_fmt_is_planar(resamplePara_.srcFfFmt)) {
        for (size_t i = 1; i < tmpInput.size(); ++i) {
            tmpInput[i] = tmpInput[i - 1] + lineSize;
        }
    }
    auto res = swr_convert(swrCtx_.get(), resChannelAddr_.data(), samples, tmpInput.data(), samples);
}
```

---

## 关键设计

### 数据流

```
MediaMuxer.AddTrack()
  → Track::Init(avformat_alloc_output_context2)
  → FFmpegMuxerPlugin(AVFMT_FLAG_CUSTOM_IO)
  → FFmpegMuxerRegister::InitAvIoCtx(dataSink)
  → avformat_write_header(formatContext_)
  → FFmpegBaseEncoder.avcodec_send_frame()
  → FFmpegMuxerPlugin.WriteSample()
  → AVIOContext->IoWrite(DataSink)
```

### 三层架构总结

| 层 | 类/文件 | 职责 | 关键 API |
|---|---|---|---|
| 注册机 | FFmpegMuxerRegister | av_muxer_iterate 遍历 + PLUGIN_DEFINITION 宏 | RegisterMuxerPlugins / IoOpen / IoClose |
| 封装修复器 | FFmpegMuxerPlugin | 持有 AVFormatContext + NAL_START_PATTERN | SetDataSink / SetParameter / WriteSample |
| 编码基类 | FFmpegBaseEncoder | avcodec_send_frame/receive_frame 管线 | ProcessSendData / ProcessReceiveData / PcmFillFrame |
| 重采样 | Resample (ffmpeg_convert.cpp) | SwrContext RAII 包装 | InitSwrContext / Convert / ConvertFrame |

### 与 S91/S145/S180 对比

- **S91**（MPEG4MuxerPlugin）：手写 ISOBMFF Box 结构，无 FFmpeg 依赖
- **S145**（FFmpegAdapter Muxer）：FFmpegMuxerPlugin + MPEG4MuxerPlugin 并列，AVFMT_FLAG_CUSTOM_IO
- **S196**（本主题）：三层架构（Register + Plugin + Encoder），重点在 avcodec_send_frame/receive_frame 管线 + SwrContext 重采样

---

## 源码文件清单

| 文件 | 行数 | 作用 |
|---|---|---|
| `services/media_engine/plugins/ffmpeg_adapter/muxer/ffmpeg_muxer_plugin.cpp` | ~1414 | 封装修复器主实现 |
| `services/media_engine/plugins/ffmpeg_adapter/muxer/ffmpeg_muxer_register.cpp` | ~377 | 注册机 + av_muxer_iterate 遍历 |
| `services/media_engine/plugins/ffmpeg_adapter/muxer/ffmpeg_muxer_register.h` | ~90 | 静态函数声明 + IOContext 结构体 |
| `services/media_engine/plugins/ffmpeg_adapter/audio_encoder/ffmpeg_base_encoder.cpp` | ~396 | 编码基类 + avcodec_send_frame/receive_frame |
| `services/media_engine/plugins/ffmpeg_adapter/audio_encoder/ffmpeg_base_encoder.h` | ~94 | FFmpegBaseEncoder 类定义 |
| `services/media_engine/plugins/ffmpeg_adapter/common/ffmpeg_convert.cpp` | ~247 | SwrContext 重采样实现 |
| `services/media_engine/plugins/ffmpeg_adapter/common/ffmpeg_convert.h` | ~98 | Resample 类定义 |
