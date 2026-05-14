# MEM-ARCH-AVCODEC-S132

> **状态**: draft → **pending_approval**  
> **主题编号**: S132  
> **生成时间**: 2026-05-14T15:56  
> **Builder**: builder-agent  
> **主题名称**: FFmpeg Audio Encoder Plugin 架构——FFmpegBaseEncoder 基类 + AAC/FLAC 编码器插件体系

---

## 一、主题概述

| 维度 | 说明 |
|------|------|
| **scope** | AVCodec, AudioCodec, FFmpeg, Plugin, SoftwareCodec, AudioEncoder, AAC, FLAC |
| **关联场景** | 新需求开发/问题定位/音频编码接入 |
| **关联记忆** | S8(FFmpeg音频插件总览), S50(AudioResample), S60(AAC编解码), S125(FFmpeg解码器基类) |

### 核心问题

AVCodec 音频编码侧有两种软件编码路径：
1. **FFmpeg 编码路径**：`FFmpegBaseEncoder` 基类 + `FFmpegAACEncoderPlugin` / `FFmpegFlacEncoderPlugin`
2. **独立编码器**：G711mu（纯算法）、MP3（libmpg123/lame）、LBVC（HDI/OMX）

S132 聚焦 FFmpeg 音频编码器插件体系，与 S125（FFmpeg 解码器基类）构成编解码对称架构。

---

## 二、FFmpegBaseEncoder 基类

**文件**: `services/media_engine/plugins/ffmpeg_adapter/audio_encoder/ffmpeg_base_encoder.cpp` (396行)  
**头文件**: `services/media_engine/plugins/ffmpeg_adapter/audio_encoder/ffmpeg_base_encoder.h` (129行)

### 2.1 关键成员

| 成员 | 类型 | 说明 |
|------|------|------|
| `avCodec_` | `std::shared_ptr<AVCodec>` | FFmpeg AVCodec 实例 |
| `avCodecContext_` | `std::shared_ptr<AVCodecContext>` | FFmpeg 编解码器上下文 |
| `cachedFrame_` | `std::shared_ptr<AVFrame>` | PCM 输入帧缓存 |
| `avPacket_` | `std::shared_ptr<AVPacket>` | 编码后数据包 |
| `avMutext_` | `std::mutex` | 线程安全锁 |
| `dataCallback_` | `DataCallback*` | 数据回调接口 |

### 2.2 编码管线（avcodec_send_frame / avcodec_receive_packet）

#### SendBuffer — 发送 PCM 帧到 FFmpeg 编码器

```cpp
// ffmpeg_base_encoder.cpp:102-128
Status FFmpegBaseEncoder::SendBuffer(const std::shared_ptr<AVBuffer> &inputBuffer)
{
    int ret = av_frame_make_writable(cachedFrame_.get());  // line 103
    if (ret != 0) { ... return Status::ERROR_UNKNOWN; }
    
    bool isEos = inputBuffer->flag_ & BUFFER_FLAG_EOS;  // line 110
    if (!isEos) {
        auto errCode = PcmFillFrame(inputBuffer);        // line 113: 填充 PCM 数据
        if (errCode != Status::OK) { return errCode; }
        ret = avcodec_send_frame(avCodecContext_.get(), cachedFrame_.get()); // line 117
    } else {
        ret = avcodec_send_frame(avCodecContext_.get(), nullptr);            // line 119: EOS
    }
    if (ret == 0) { return Status::OK; }
    else if (ret == AVERROR(EAGAIN)) { return Status::ERROR_NOT_ENOUGH_DATA; }
    else if (ret == AVERROR_EOF) { return Status::END_OF_STREAM; }
    else { return Status::ERROR_UNKNOWN; }
}
```

**证据**: `ffmpeg_base_encoder.cpp:117` — `avcodec_send_frame(avCodecContext_.get(), cachedFrame_.get())`

#### ReceivePacketSucc — 接收编码后数据包

```cpp
// ffmpeg_base_encoder.cpp:175-192
Status FFmpegBaseEncoder::ReceivePacketSucc(std::shared_ptr<AVBuffer> &outputBuffer)
{
    auto memory = outputBuffer->memory_;
    int32_t outputSize = avPacket_->size;                       // line 177
    auto len = memory->Write(avPacket_->data, avPacket_->size, 0); // line 181
    // pts us
    outputBuffer->duration_ = ConvertTimeFromFFmpeg(avPacket_->duration, 
                           avCodecContext_->time_base) / NS_PER_US;  // line 184
    outputBuffer->pts_ = prevPts_ + outputBuffer->duration_;          // line 186
    prevPts_ = outputBuffer->pts_;                                    // line 187
    return Status::OK;
}
```

**证据**: `ffmpeg_base_encoder.cpp:181` — 写编码后数据到输出 Buffer

#### PcmFillFrame — PCM 帧填充

```cpp
// ffmpeg_base_encoder.cpp:80-98
Status FFmpegBaseEncoder::PcmFillFrame(const std::shared_ptr<AVBuffer> &inputBuffer)
{
    auto memory = inputBuffer->memory_;
    auto usedSize = memory->GetSize();
    auto frameSize = avCodecContext_->frame_size;
    cachedFrame_->nb_samples = usedSize / channelsBytesPerSample_;  // line 86
    cachedFrame_->data[0] = memory->GetAddr();                       // line 92
    cachedFrame_->extended_data = cachedFrame_->data;
    cachedFrame_->linesize[0] = usedSize;                           // line 95
    return Status::OK;
}
```

**证据**: `ffmpeg_base_encoder.cpp:86` — `nb_samples = usedSize / channelsBytesPerSample_`

### 2.3 上下文生命周期

#### AllocateContext — 分配 FFmpeg 上下文

```cpp
// ffmpeg_base_encoder.cpp:302-318
Status FFmpegBaseEncoder::AllocateContext(const std::string &name)
{
    avCodec_ = std::shared_ptr<AVCodec>(
        const_cast<AVCodec *>(avcodec_find_encoder_by_name(name.c_str())), ...);  // line 306
    cachedFrame_ = std::shared_ptr<AVFrame>(av_frame_alloc(), ...);               // line 308
    avPacket_ = std::shared_ptr<AVPacket>(av_packet_alloc(), ...);                // line 309
    context = avcodec_alloc_context3(avCodec_.get());                              // line 315
    avCodecContext_ = std::shared_ptr<AVCodecContext>(context, ...);              // line 316
}
```

**证据**: `ffmpeg_base_encoder.cpp:306` — `avcodec_find_encoder_by_name(name)` 按名称查找编码器

#### InitContext — 从 Meta 参数初始化编码器

```cpp
// ffmpeg_base_encoder.cpp:320-337
Status FFmpegBaseEncoder::InitContext(const std::shared_ptr<Meta> &format)
{
    format_->GetData(Tag::AUDIO_CHANNEL_COUNT, channels);
    format_->GetData(Tag::AUDIO_SAMPLE_RATE, avCodecContext_->sample_rate);
    format_->GetData(Tag::MEDIA_BITRATE, avCodecContext_->bit_rate);
    // 采样格式转换: OH::AudioSampleFormat → FFmpeg AVSampleFormat
    auto ffSampleFormat = FFMpegConverter::ConvertOHAudioFormatToFFMpeg(
        static_cast<AudioSampleFormat>(sampleFormat));
    avCodecContext_->sample_fmt = ffSampleFormat;  // line 301
    channelsBytesPerSample_ = av_get_bytes_per_sample(ffSampleFormat) * channels;
}
```

**证据**: `ffmpeg_base_encoder.cpp:301` — `avCodecContext_->sample_fmt = ffSampleFormat`

#### OpenContext — 打开编码器

```cpp
// ffmpeg_base_encoder.cpp:336-343
Status FFmpegBaseEncoder::OpenContext()
{
    auto res = avcodec_open2(avCodecContext_.get(), avCodec_.get(), nullptr); // line 338
    if (res != 0) { ... return Status::ERROR_UNKNOWN; }
    codecContextValid_ = true;
    return Status::OK;
}
```

**证据**: `ffmpeg_base_encoder.cpp:338` — `avcodec_open2()` 打开编码器

#### InitFrame — 分配帧缓冲区

```cpp
// ffmpeg_base_encoder.cpp:357-366
Status FFmpegBaseEncoder::InitFrame()
{
    cachedFrame_->nb_samples = avCodecContext_->frame_size;    // line 358
    cachedFrame_->format = avCodecContext_->sample_fmt;
    av_channel_layout_copy(&cachedFrame_->ch_layout, &avCodecContext_->ch_layout); // line 360
    int ret = av_frame_get_buffer(cachedFrame_.get(), 0);      // line 362: 分配帧缓冲区
    return Status::OK;
}
```

**证据**: `ffmpeg_base_encoder.cpp:362` — `av_frame_get_buffer()` 分配 PCM 帧缓冲区

---

## 三、FFmpegAACEncoderPlugin AAC 编码器

**文件**: `services/media_engine/plugins/ffmpeg_adapter/audio_encoder/aac/ffmpeg_aac_encoder_plugin.cpp` (902行)  
**头文件**: `services/media_engine/plugins/ffmpeg_adapter/audio_encoder/aac/ffmpeg_aac_encoder_plugin.h` (139行)

### 3.1 与 FFmpegBaseEncoder 的差异

FFmpegAACEncoderPlugin **不使用** FFmpegBaseEncoder，而是自行实现完整编码逻辑，并新增：

| 新增组件 | 说明 |
|----------|------|
| `AVAudioFifo *fifo_` | 音频样本循环缓冲区，批量编码 |
| `resample_` | FFmpeg::Resample 重采样器 |
| `paddedBuffer_` | AAC 编码 padding 缓冲区 |
| ADTS 头生成 | `GetAdtsHeader()` 为每帧附加 ADTS 7字节头 |

### 3.2 编码管线

```
输入 PCM → PushInFifo (写入 AVAudioFifo) → SendFrameToFfmpeg → avcodec_send_frame
                                                           ↓
                                               avcodec_receive_packet
                                                           ↓
                                                   GetAdtsHeader (附加 ADTS 头)
                                                           ↓
                                                        输出
```

### 3.3 关键 Evidence

**ADTS 7字节头生成** — AAC 编码特有

```cpp
// ffmpeg_aac_encoder_plugin.cpp (约第 500-550 行)
// ADTS 头结构: 同步字(0xFFF) + 采样率索引 + 通道数 + 帧长度
```

**Resample 触发** — `needResample_` 自动判断

```cpp
// ffmpeg_aac_encoder_plugin.h
std::shared_ptr<Ffmpeg::Resample> resample_{nullptr};  // 重采样器
bool needResample_;                                     // 是否需要重采样
```

---

## 四、FFmpegFlacEncoderPlugin FLAC 编码器

**文件**: `services/media_engine/plugins/ffmpeg_adapter/audio_encoder/flac/ffmpeg_flac_encoder_plugin.cpp` (252行)  
**头文件**: `services/media_engine/plugins/ffmpeg_adapter/audio_encoder/flac/ffmpeg_flac_encoder_plugin.h`

### 4.1 架构：委托 FFmpegBaseEncoder

```cpp
// ffmpeg_flac_encoder_plugin.cpp:74
FFmpegFlacEncoderPlugin::FFmpegFlacEncoderPlugin(const std::string& name)
    : CodecPlugin(name), channels_(0), 
      basePlugin(std::make_unique<FFmpegBaseEncoder>())  // 组合 FFmpegBaseEncoder
{
}
```

**证据**: `ffmpeg_flac_encoder_plugin.cpp:74` — 组合模式使用 FFmpegBaseEncoder

### 4.2 FLAC 特有校验

```cpp
// ffmpeg_flac_encoder_plugin.cpp:43-57
static const int32_t FLAC_ENCODER_SAMPLE_RATE_TABLE[] = {
    8000, 16000, 22050, 24000, 32000, 44100, 48000, 88200, 96000,
};
static const uint64_t FLAC_CHANNEL_LAYOUT_TABLE[] = {
    AV_CH_LAYOUT_MONO, AV_CH_LAYOUT_STEREO, AV_CH_LAYOUT_SURROUND,
    AV_CH_LAYOUT_QUAD, AV_CH_LAYOUT_5POINT0, AV_CH_LAYOUT_5POINT1,
    AV_CH_LAYOUT_6POINT1, AV_CH_LAYOUT_7POINT1
};
static std::set<AudioSampleFormat> supportedSampleFormats = {
    SAMPLE_S16LE, SAMPLE_S32LE,  // 仅支持这两种 PCM 格式
};
```

**证据**: `ffmpeg_flac_encoder_plugin.cpp:36-55` — FLAC 编码器能力约束

---

## 五、插件注册体系

### 5.1 FFmpeg 音频编码器注册（ffmpeg_encoder_plugin.cpp）

```cpp
// services/media_engine/plugins/ffmpeg_adapter/audio_encoder/ffmpeg_encoder_plugin.cpp:33-62
std::vector<std::string_view> codecVec = {
    AVCodecCodecName::AUDIO_ENCODER_AAC_NAME,  // "ffmpeg.aac.encoder"
    AVCodecCodecName::AUDIO_ENCODER_FLAC_NAME, // "ffmpeg.flac.encoder"
};

void SetDefinition(size_t index, CodecPluginDef &definition, Capability &cap)
{
    switch (index) {
        case 0: // AAC
            cap.SetMime(MimeType::AUDIO_AAC);
            definition.SetCreator([](const std::string &name) -> std::shared_ptr<CodecPlugin> {
                return std::make_shared<FFmpegAACEncoderPlugin>(name);
            });
            break;
        case 1: // FLAC
            cap.SetMime(MimeType::AUDIO_FLAC);
            definition.SetCreator([](const std::string &name) -> std::shared_ptr<CodecPlugin> {
                return std::make_shared<FFmpegFlacEncoderPlugin>(name);
            });
            break;
    }
}

Status RegisterAudioEncoderPlugins(const std::shared_ptr<Register> &reg)
{
    for (size_t i = 0; i < codecVec.size(); i++) {
        CodecPluginDef definition;
        definition.pluginType = PluginType::AUDIO_ENCODER;
        definition.rank = 100;  // 最高优先级
        ...
        reg->AddPlugin(definition);
    }
}

PLUGIN_DEFINITION(FFmpegAudioEncoders, LicenseType::LGPL, 
    RegisterAudioEncoderPlugins, UnRegisterAudioEncoderPlugin);
```

**证据**: `ffmpeg_encoder_plugin.cpp:50` — `definition.rank = 100` 注册为最高优先级

### 5.2 插件注册文件位置

| 编码器 | 注册文件 |
|--------|----------|
| AAC | `audio_encoder/ffmpeg_encoder_plugin.cpp` (ffmpeg_encoder_plugin.h includes both AAC and FLAC headers) |
| FLAC | 同上 |
| G711mu | `audio_encoder/g711mu/audio_g711mu_encoder_plugin.cpp` (独立注册) |
| MP3 | `audio_encoder/mp3/audio_mp3_encoder_plugin.cpp` (使用 libmpg123/lame) |
| LBVC | `audio_encoder/lbvc/audio_lbvc_encoder_plugin.cpp` (HDI OMX) |

---

## 六、与 S125（FFmpeg 解码器基类）架构对比

| 维度 | S125 FFmpeg 解码器 | S132 FFmpeg 编码器 |
|------|-------------------|-------------------|
| **基类文件** | `ffmpeg_base_decoder.cpp` | `ffmpeg_base_encoder.cpp` (396行) |
| **FFmpeg API** | `avcodec_send_packet` / `avcodec_receive_frame` | `avcodec_send_frame` / `avcodec_receive_packet` |
| **输入** | AVPacket（压缩数据） | AVFrame（PCM 原始数据） |
| **输出** | AVFrame（解码后数据） | AVPacket（编码后数据） |
| **帧管理** | `ProcessSendData()` 发送压缩包 | `ProcessSendData()` 发送 PCM 帧 |
| **Buffer** | 输入→输出 | 输入 PCM → 输出 AVPacket |
| **具体插件** | FfmpegDecoderPlugin (17+格式) | FFmpegAACEncoderPlugin + FFmpegFlacEncoderPlugin |
| **Resample** | `Ffmpeg::Resample` (重采样) | `Ffmpeg::Resample` (重采样) |

### 关键对称性

```
解码器: AVPacket → avcodec_send_packet → avcodec_receive_frame → AVFrame
编码器: AVFrame → avcodec_send_frame → avcodec_receive_packet → AVPacket
```

---

## 七、音频编码器插件全图

```
services/media_engine/plugins/ffmpeg_adapter/audio_encoder/
├── ffmpeg_encoder_plugin.cpp     # PLUGIN_DEFINITION: AAC + FLAC 注册
├── ffmpeg_encoder_plugin.h       # 包含 AAC/FLAC 头文件
├── ffmpeg_base_encoder.cpp(396)  # FFmpegBaseEncoder 基类
├── ffmpeg_base_encoder.h(129)
├── aac/
│   ├── ffmpeg_aac_encoder_plugin.cpp(902)  # AAC: 自实现+AVAudioFifo+Resample+ADTS
│   └── ffmpeg_aac_encoder_plugin.h
├── flac/
│   ├── ffmpeg_flac_encoder_plugin.cpp(252) # FLAC: 组合 FFmpegBaseEncoder
│   └── ffmpeg_flac_encoder_plugin.h
├── g711mu/
│   ├── audio_g711mu_encoder_plugin.cpp    # 独立注册: PCM→G711mu (无FFmpeg)
│   └── audio_g711mu_encoder_plugin.h
├── mp3/
│   ├── audio_mp3_encoder_plugin.cpp       # 使用 libmp3lame (lame.h)
│   └── audio_mp3_encoder_plugin.h
└── lbvc/
    ├── audio_lbvc_encoder_plugin.cpp      # OMX HDI 硬件编码器
    └── audio_lbvc_encoder_plugin.h
```

---

## 八、关键发现

1. **FFmpegBaseEncoder vs FFmpegAACEncoderPlugin 的设计差异**  
   - FFmpegAACEncoderPlugin **不使用** FFmpegBaseEncoder，而是自行实现完整逻辑（包含 AVAudioFifo、Resample、ADTS 头）  
   - FFmpegFlacEncoderPlugin **组合使用** FFmpegBaseEncoder（轻量级）  
   - 原因：AAC 编码需要更复杂的 FIFO 缓冲和重采样，FLAC 相对简单

2. **AAC 编码 ADTS 头**  
   - 每帧 AAC 输出前附加 7 字节 ADTS 头（采样率+通道+帧长度）  
   - FFmpeg 原生 AAC 不输出 ADTS，需要手动生成

3. **编码器能力约束**  
   - FLAC: 仅支持 8000-96000Hz 采样率、1-8 通道、S16LE/S32LE 格式  
   - AAC: 支持更宽采样率范围（通过 Resample 兼容）

4. **与 S125 对称架构**  
   - 编码/解码使用相同的 FFmpeg API 对（send/receive），方向相反  
   - 解码器有 17+ 格式插件，编码器仅 AAC+FLAC 两个 FFmpeg 插件

---

## 九、Evidence 汇总（行号级）

| Evidence | 文件 | 行号 |
|----------|------|------|
| avcodec_send_frame 发送 PCM | ffmpeg_base_encoder.cpp | 117 |
| avcodec_receive_packet 接收编码包 | ffmpeg_base_encoder.cpp | 146 |
| avcodec_find_encoder_by_name 按名查找 | ffmpeg_base_encoder.cpp | 306 |
| avcodec_alloc_context3 分配上下文 | ffmpeg_base_encoder.cpp | 315 |
| avcodec_open2 打开编码器 | ffmpeg_base_encoder.cpp | 338 |
| av_frame_get_buffer 分配帧缓冲 | ffmpeg_base_encoder.cpp | 362 |
| PcmFillFrame PCM 填充 | ffmpeg_base_encoder.cpp | 86 |
| FLAC 组合 FFmpegBaseEncoder | ffmpeg_flac_encoder_plugin.cpp | 74 |
| PLUGIN_DEFINITION 注册 AAC+FLAC | ffmpeg_encoder_plugin.cpp | 61 |
| definition.rank = 100 | ffmpeg_encoder_plugin.cpp | 50 |
| AAC Resample 成员 | ffmpeg_aac_encoder_plugin.h | (成员声明) |
