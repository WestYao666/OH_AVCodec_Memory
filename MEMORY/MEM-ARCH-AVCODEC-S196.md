---
id: MEM-ARCH-AVCODEC-S196
title: FFmpeg Adapter Muxer Plugin 体系——FFmpegMuxerPlugin + MPEG4MuxerPlugin + FFmpegMuxerRegister 三层架构
status: pending_approval
scope: FFmpeg Adapter Muxer Plugin Architecture, FFmpegBaseEncoder, FFmpegMuxerRegister, MPEG4MuxerPlugin, ISOBMFF, Box, libavformat, avcodec_send_frame, avcodec_receive_frame, Track, DataSink, ADTS, AudioFifo
timestamp: 2026-06-04T13:45
evidence_count: 18
source_files: services/media_engine/plugins/ffmpeg_adapter/muxer/ffmpeg_muxer_plugin.cpp, services/media_engine/plugins/ffmpeg_adapter/muxer/ffmpeg_muxer_register.cpp, services/media_engine/plugins/ffmpeg_adapter/audio_encoder/ffmpeg_base_encoder.cpp, services/media_engine/plugins/ffmpeg_adapter/audio_encoder/ffmpeg_base_encoder.h, services/media_engine/plugins/ffmpeg_adapter/common/ffmpeg_convert.cpp, services/media_engine/plugins/ffmpeg_adapter/common/ffmpeg_convert.h
---

## 一句话总结
FFmpeg Adapter Muxer Plugin 体系由 FFmpegMuxerRegister 注册机、FFmpegMuxerPlugin 封装修复器和 MPEG4MuxerPlugin 子插件三层构成，底层基于 libavformat；音频编码侧 FFmpegBaseEncoder 提供 avcodec_send_frame/receive_frame 统一管线，配合 ADTS 头和 AVAudioFifo 双缓冲。

## 架构图

```
┌─────────────────────────────────────────────────────────────┐
│              FFmpegAdapter Plugin Architecture                │
├─────────────────────────────────────────────────────────────┤
│  muxer/                                                     │
│  ├── FFmpegMuxerRegister (注册机, AutoRegisterFilter)      │
│  │   └── GetAVOutputFormat / InitAvIoCtx / IoOpen/Close     │
│  ├── FFmpegMuxerPlugin (封装修复器, AVFMT_FLAG_CUSTOM_IO)   │
│  │   ├── cachePacket_ (AVPacket shared_ptr)                   │
│  │   ├── NAL_START_PATTERN = 0x01000100                      │
│  │   └── videoTracksInfo_ / hevcParser_                     │
│  └── mpeg4_muxer/ (子插件, ISOBMFF BasicBox 树)              │
│      ├── mpeg4_muxer_plugin.cpp                             │
│      ├── basic_box.cpp (1256行)                             │
│      └── video_track.cpp / audio_track.cpp / basic_track.cpp│
│                                                              │
│  audio_encoder/                                              │
│  ├── FFmpegBaseEncoder (引擎基类)                           │
│  │   ├── avcodec_send_frame / avcodec_receive_packet       │
│  │   ├── pcmCache_ (PCM缓冲)                                │
│  │   ├── cachedFrame_ (AVFrame shared_ptr)                  │
│  │   └── isEnableFormatConvert_ / format conversion         │
│  ├── aac/ (AAC 子插件, ADTS 7字节头, AVAudioFifo)            │
│  ├── flac/ (FLAC 子插件, 组合 FFmpegBaseEncoder)            │
│  ├── mp3/ (MP3 子插件, LAME 库)                             │
│  ├── g711mu/ (G711mu 子插件, 零依赖查表)                    │
│  └── lbvc/ (LBVC 子插件, HDI OMX)                           │
│                                                              │
│  common/                                                     │
│  ├── ffmpeg_convert.cpp (SwrContext 重采样器)               │
│  └── ffmpeg_convert.h                                       │
└─────────────────────────────────────────────────────────────┘
```

## 核心源码分析（带行号的证据）

### 1. FFmpegMuxerPlugin 构造函数（封装修复器核心）

**ffmpeg_muxer_plugin.cpp 构造函数**

```cpp
// services/media_engine/plugins/ffmpeg_adapter/muxer/ffmpeg_muxer_plugin.cpp
FFmpegMuxerPlugin::FFmpegMuxerPlugin(std::string name)
 : MuxerPlugin(std::move(name)), isWriteHeader_(false)
{
    // L53-55: mallopt 禁用线程缓存，防止内存碎片
    mallopt(M_SET_THREAD_CACHE, M_THREAD_CACHE_DISABLE);
    mallopt(M_DELAYED_FREE, M_DELAYED_FREE_DISABLE);

    // L59: 设置 FFmpeg 日志回调
    av_log_set_callback(FFmpegMuxerRegister::FfmpegLogPrintWithLevel);

    // L61-62: 创建 AVPacket 智能指针，cachePacket_
    auto pkt = av_packet_alloc();
    cachePacket_ = std::shared_ptr<AVPacket>(pkt, [](AVPacket *packet) { av_packet_free(&packet); });

    // L63-64: 通过 FFmpegMuxerRegister 获取 AVOutputFormat
    outputFormat_ = FFmpegMuxerRegister::GetAVOutputFormat(pluginName_);

    // L66-73: 创建 AVFormatContext，设置 AVFMT_FLAG_CUSTOM_IO
    auto fmt = avformat_alloc_context();
    fmt->pb = nullptr;
    fmt->oformat = outputFormat_.get();
    fmt->flags = static_cast<uint32_t>(fmt->flags) | static_cast<uint32_t>(AVFMT_FLAG_CUSTOM_IO);
    fmt->io_open = FFmpegMuxerRegister::IoOpen;    // 自定义 IO 打开回调
    fmt->io_close2 = FFmpegMuxerRegister::IoClose;  // 自定义 IO 关闭回调
}
```

**关键常量（ffmpeg_muxer_plugin.cpp L33-47）**

```cpp
const std::set<std::string> SUPPORTED_TRACK_REF_TYPE = {"hint", "cdsc", "font", ...};
constexpr float LATITUDE_MIN = -90.0f;
constexpr float LATITUDE_MAX = 90.0f;
constexpr int32_t MIN_HE_AAC_SAMPLE_RATE = 16000;
constexpr int32_t MAX_USERMETA_STRING_LENGTH = 256;

// NAL 起始码相关常量（用于封装修复）
constexpr uint32_t NAL_START_PATTERN = 0x01000100;        // L44
constexpr uint32_t NAL_MATCH_MASK = 0x80008000U;           // L46
```

---

### 2. FFmpegMuxerPlugin SetDataSink（DataSink 注入）

**ffmpeg_muxer_plugin.cpp SetDataSink 方法**

```cpp
Status FFmpegMuxerPlugin::SetDataSink(const std::shared_ptr<DataSink> &dataSink)
{
    FALSE_RETURN_V_MSG_E(dataSink != nullptr, Status::ERROR_INVALID_PARAMETER, "data sink is null");
    FFmpegMuxerRegister::DeInitAvIoCtx(formatContext_->pb);
    // L85: 通过 FFmpegMuxerRegister 初始化自定义 AVIOContext
    formatContext_->pb = FFmpegMuxerRegister::InitAvIoCtx(dataSink, 1);
    FALSE_RETURN_V_MSG_E(formatContext_->pb != nullptr, Status::ERROR_INVALID_OPERATION, ...);
}
```

---

### 3. FFmpegMuxerRegister 注册机（核心函数）

**FFmpegMuxerRegister::GetAVOutputFormat** — 按插件名获取 FFmpeg 输出格式

**FFmpegMuxerRegister::InitAvIoCtx** — 初始化自定义 AVIOContext，桥接 DataSink

**FFmpegMuxerRegister::IoOpen / IoClose** — FFmpeg IO 回调，用于读写数据

---

### 4. FFmpegBaseEncoder 引擎基类（avcodec_send_frame 管线）

**ffmpeg_base_encoder.h 关键成员（行号推断）**

```cpp
// ffmpeg_base_encoder.h
class FFmpegBaseEncoder : NoCopyable {
public:
    FFmpegBaseEncoder();
    ~FFmpegBaseEncoder();
    Status ProcessSendData(const std::shared_ptr<AVBuffer> &inputBuffer);
    Status ProcessReceiveData(std::shared_ptr<AVBuffer> &outputBuffer);
    Status AllocateContext(const std::string &name);
    Status InitContext(const std::shared_ptr<Meta> &format);
    Status OpenContext();
    Status InitFrame();
    std::shared_ptr<AVCodecContext> GetCodecContext() const;
    void SetCallback(DataCallback *callback);
    void SetPtsMode(int32_t mode);
    void SetFormatConvert(bool enable, AudioSampleFormat srcFormat, AudioSampleFormat dstFormat);

private:
    int32_t maxInputSize_;
    std::shared_ptr<AVCodec> avCodec_;
    std::shared_ptr<AVCodecContext> avCodecContext_;  // FFmpeg 编码器上下文
    std::shared_ptr<AVFrame> cachedFrame_;            // 缓存 AVFrame
    std::shared_ptr<AVPacket> avPacket_;               // 缓存 AVPacket
    mutable std::mutex avMutext_;                      // 编码器锁
    std::mutex parameterMutex_;
    std::shared_ptr<Meta> format_;
    bool isEnableFormatConvert_;
    AudioSampleFormat srcSampleFormat_;
    AudioSampleFormat dstSampleFormat_;
    std::vector<uint8_t> convertBuffer_;
    std::vector<uint8_t> pcmCache_;                     // PCM 缓存（enableCache_ 模式）
    int64_t prevPts_;
    bool codecContextValid_;
    bool isFirstInputPts_;
    int32_t ptsMode_;
    bool enableCache_;
};
```

---

**ffmpeg_base_encoder.cpp ProcessSendData（核心输入逻辑）**

```cpp
// ffmpeg_base_encoder.cpp L53-82
Status FFmpegBaseEncoder::ProcessSendData(const std::shared_ptr<AVBuffer> &inputBuffer)
{
    auto memory = inputBuffer->memory_;
    if (memory == nullptr) {
        AVCODEC_LOGE("memory is nullptr");
        return Status::ERROR_INVALID_DATA;
    }

    std::lock_guard<std::mutex> lock(avMutext_);
    if (avCodecContext_ == nullptr) {
        return Status::ERROR_WRONG_STATE;
    }

    if (!enableCache_) {
        ret = SendBuffer(inputBuffer);          // 直接发送模式
    } else {
        bool isEos = inputBuffer->flag_ & BUFFER_FLAG_EOS;
        if (!isEos && ptsMode_ == FIRST_INPUT_START_ENCODE_PTS_MODE && isFirstInputPts_) {
            prevPts_ = inputBuffer->pts_;
            isFirstInputPts_ = false;
        }
        if (isEos) {
            ret = SendEosBuffer();
        } else {
            if (isEnableFormatConvert_ && srcSampleFormat_ != dstSampleFormat_) {
                // L74-79: 格式转换后缓存 PCM
                size_t srcBufferSize = static_cast<size_t>(memory->GetSize());
                size_t inputSampleCnt = srcBufferSize / static_cast<size_t>(srcBytesPerSample_);
                size_t dstBufferSize = GetPcmConvertOutputSize(inputSampleCnt, dstSampleFormat_);
                convertBuffer_.resize(dstBufferSize);
                ConvertPcmSampleFormat(memory->GetAddr(), inputSampleCnt,
                    srcSampleFormat_, dstSampleFormat_, convertBuffer_.data());
                pcmCache_.insert(pcmCache_.end(), convertBuffer_.begin(), convertBuffer_.end());
            } else {
                pcmCache_.insert(pcmCache_.end(), memory->GetAddr(),
                    memory->GetAddr() + memory->GetSize());
            }
            ret = SendCachedFrames();
        }
    }
    // L81-82: 回调通知输入 buffer 已消费
    SafeCallInputBufferDone(dataCallback_, inputBuffer);
    return Status::OK;
}
```

---

**ffmpeg_base_encoder.cpp SendBuffer（avcodec_send_frame 管线）**

```cpp
// ffmpeg_base_encoder.cpp L105-115
Status FFmpegBaseEncoder::SendBuffer(const std::shared_ptr<AVBuffer> &inputBuffer)
{
    int ret = av_frame_make_writable(cachedFrame_.get());  // L106: 确保 frame 可写
    if (ret != 0) { ... }

    bool isEos = inputBuffer->flag_ & BUFFER_FLAG_EOS;
    if (!isEos) {
        auto errCode = PcmFillFrame(inputBuffer);           // L111: PCM 填充 frame
        if (errCode != Status::OK) { ... }
        ret = avcodec_send_frame(avCodecContext_.get(), cachedFrame_.get()); // L113: 发送 frame
    } else {
        ret = avcodec_send_frame(avCodecContext_.get(), nullptr); // EOS 发送 nullptr
    }

    if (ret == 0) {
        return Status::OK;
    } else if (ret == AVERROR(EAGAIN)) {
        return Status::ERROR_NOT_ENOUGH_DATA;
    } else if (ret == AVERROR_EOF) {
        return Status::END_OF_STREAM;
    } else {
        return Status::ERROR_UNKNOWN;
    }
}
```

---

**ffmpeg_base_encoder.cpp ProcessReceiveData（avcodec_receive_packet 管线）**

```cpp
Status FFmpegBaseEncoder::ProcessReceiveData(std::shared_ptr<AVBuffer> &outputBuffer)
{
    // L120+: 从 avCodecContext_ 接收编码后的 packet
    int ret = avcodec_receive_packet(avCodecContext_.get(), avPacket_.get());
    if (ret == 0) {
        // 编码成功，填充 outputBuffer
        return Status::OK;
    } else if (ret == AVERROR(EAGAIN)) {
        return Status::ERROR_NOT_ENOUGH_DATA;  // 需要更多输入
    } else if (ret == AVERROR_EOF) {
        return Status::END_OF_STREAM;
    }
}
```

---

### 5. FFmpegConvert 重采样器（SwrContext）

**ffmpeg_convert.cpp SwrContext 初始化（推断行号）**

```cpp
// ffmpeg_convert.cpp / ffmpeg_convert.h
// swr_alloc_set_opts2() 创建 SwrContext
// swr_init() 初始化重采样上下文
// swr_convert() / swr_convert_frame() 执行重采样
// swrCtx_ 成员：SwrContext 智能指针
```

---

### 6. AAC 子插件（ADTS 7字节头 + AVAudioFifo）

**services/media_engine/plugins/ffmpeg_adapter/audio_encoder/aac/**

- **ADTS_HEADER_SIZE = 7** — AAC 封包前需插入 7 字节 ADTS 头
- **av_audio_fifo_alloc()** — 创建 FFmpeg Audio FIFO 缓冲区
- **av_audio_fifo_write()** / **av_audio_fifo_read()** — FIFO 读写
- **av_audio_fifo_size()** / **av_audio_fifo_drop()** — FIFO 管理
- AAC 编码器使用自实现的 AVAudioFifo 管理输入样本，而 FFmpeg FLAC 编码器直接组合 FFmpegBaseEncoder

---

## 关联记忆

| 关联 | 说明 |
|------|------|
| S91 | MPEG4 MuxerPlugin 写时构建架构 — 与 S196 共享 mpeg4_muxer 子目录，S196 补充 FFmpegMuxerPlugin 封装修复层 |
| S145 | FFmpeg Adapter Muxer Plugin 体系 — 早期版本，S196 基于 web_fetch 源码行号增强 |
| S131 | FFmpeg 音频编码器与封装修复器插件体系 — 音频编码器三层架构，S196 为其 muxer 分支 |
| S130 | FFmpeg Adapter Common 通用工具链 — ffmpeg_convert.cpp / ffmpeg_utils.cpp，S196 与其共享 common 组件 |
| S125 | FFmpeg 软件解码器基类 — FfmpegBaseDecoder 与 FFmpegBaseEncoder 对称架构 |
| S181 | FFmpeg Adapter Common 通用工具链 — Mime2CodecId / ColorSpace / ChannelLayout，S196 与其共享 common 层 |
| S183 | AvcEncoder 软件 H.264 编码器 — 与 FFmpegBaseEncoder 对比：双库加载 vs libavcodec 单库 |
| S158/S169/S176 | FFmpeg 音频编码器子插件（AAC/FLAC/MP3/G711mu/LBVC）— S196 描述 muxer 侧，S158 等描述 encoder 侧 |

## 关键设计模式

1. **AVFMT_FLAG_CUSTOM_IO** — FFmpegMuxerPlugin 不使用 FFmpeg 内部 I/O，通过 InitAvIoCtx 注册 DataSink 回调，实现与 MediaMuxer 的解耦
2. **三层插件架构** — FFmpegMuxerRegister(注册机) → FFmpegMuxerPlugin(封装修复器) → MPEG4MuxerPlugin/BasicBox(具体格式)
3. **avcodec_send_frame/receive_packet** — FFmpeg 音频编码管线，与视频 avcodec_send_packet/receive_frame 形成编解码对称
4. **PCM 缓存模式** — enableCache_ 时 pcmCache_ 累积 PCM 数据，分帧后通过 cachedFrame_ 发送给 FFmpeg，解决输入样本对齐问题
5. **NAL_START_PATTERN** — 0x01000100 用于封装修复时识别 NAL 单元边界