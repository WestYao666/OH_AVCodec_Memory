---
mem_id: MEM-ARCH-AVCODEC-S176
subject: FFmpeg 音频编码器插件体系——FFmpegBaseEncoder 基类 + AAC/FLAC/MP3/G711mu/LBVC 五子插件架构
status: pending_approval
created_at: "2026-05-21T22:50:00+08:00"
source_files: >
  ffmpeg_base_encoder.cpp(396行) + ffmpeg_base_encoder.h(94行) +
  ffmpeg_encoder_plugin.cpp(85行) + ffmpeg_encoder_plugin.h(26行) +
  aac/ffmpeg_aac_encoder_plugin.cpp(902行) + aac/ffmpeg_aac_encoder_plugin.h(159行) +
  flac/ffmpeg_flac_encoder_plugin.cpp(252行) +
  mp3/audio_mp3_encoder_plugin.cpp(404行) +
  g711mu/audio_g711mu_encoder_plugin.cpp(304行) +
  lbvc/audio_lbvc_encoder_plugin.cpp(285行) +
  common/ffmpeg_utils.cpp(505行) + common/ffmpeg_convert.cpp(247行)
evidence_count: 20
related_mem_ids: [S125, S132, S158, S130, S50, S8]
---

# MEM-ARCH-AVCODEC-S176 - FFmpeg 音频编码器插件体系

## 1. 三层架构概览

FFmpeg 音频编码器采用 **插件注册层(FFmpegEncoderPlugin) → 基类引擎层(FFmpegBaseEncoder) → 子插件实现层** 三层架构：

```
FFmpegEncoderPlugin (注册层, ffmpeg_encoder_plugin.cpp:64-85)
  │
  ├── FFmpegBaseEncoder (引擎基类, ffmpeg_base_encoder.cpp:396行)
  │     avcodec_send_frame / avcodec_receive_packet / avcodec_alloc_context3 / avcodec_open2
  │
  ├── FFmpegAACEncoderPlugin    (aac/ffmpeg_aac_encoder_plugin.cpp:902行, ADTS 7字节头, AVAudioFifo)
  ├── FFmpegFlacEncoderPlugin  (flac/ffmpeg_flac_encoder_plugin.cpp:252行, 采样率表 L38-44, 通道布局表 L41)
  ├── AudioMP3EncoderPlugin   (mp3/audio_mp3_encoder_plugin.cpp:404行)
  ├── AudioG711muEncoderPlugin(g711mu/audio_g711mu_encoder_plugin.cpp:304行)
  └── AudioLBVCEncoderPlugin  (lbvc/audio_lbvc_encoder_plugin.cpp:285行)
```

**自动注册入口（ffmpeg_encoder_plugin.cpp:64-85）**：
```cpp
// L64-85
Status RegisterAudioEncoderPlugins(const std::shared_ptr<Register> &reg) {
    reg->OwnsCodecWithName("audio/mpeg", [](const std::string& name) {
        return std::make_shared<AudioMP3EncoderPlugin>(name); });
    reg->OwnsCodecWithName("audio/FLAC", [](const std::string& name) {
        return std::make_shared<FFmpegFlacEncoderPlugin>(name); });
    // ... AAC/G711mu/LBVC 同理
}
PLUGIN_DEFINITION(FFmpegAudioEncoders, LicenseType::LGPL,
    RegisterAudioEncoderPlugins, UnRegisterAudioEncoderPlugin);
```

---

## 2. 引擎基类 FFmpegBaseEncoder（ffmpeg_base_encoder.cpp:396行 / ffmpeg_base_encoder.h:94行）

### 2.1 核心接口

| 接口 | 行号 | 说明 |
|------|------|------|
| `ProcessSendData(inputBuffer)` | L47 | 输入PCM数据，填充FIFO后SendBuffer |
| `ProcessReceiveData(outputBuffer)` | L131 | 接收编码后Packet，SendOutputBuffer回调 |
| `AllocateContext(name)` | L244 | 查找FFmpeg编码器（avcodec_find_encoder_by_name） |
| `InitContext(format)` | L275 | 分配AVCodecContext（avcodec_alloc_context3） |
| `OpenContext()` | L312 | 打开编码器（avcodec_open2） |
| `InitFrame()` | L332 | 初始化tmpContext用于参数探测 |
| `Stop()/Reset()/Release()/Flush()` | L208-244 | 生命周期管理 |
| `SetCallback(DataCallback*)` | L90 | 设置数据回调（子类注入） |

### 2.2 FFmpeg 管线（avcodec_send_frame / avcodec_receive_packet）

```cpp
// ffmpeg_base_encoder.cpp:113-156
// 输入侧：avcodec_send_frame
Status FFmpegBaseEncoder::SendBuffer(const std::shared_ptr<AVBuffer> &inputBuffer) {
    ret = avcodec_send_frame(avCodecContext_.get(), cachedFrame_.get()); // L113
    if (ret < 0) {
        ret = avcodec_send_frame(avCodecContext_.get(), nullptr); // L115 flush
    }
}

// 输出侧：avcodec_receive_packet
Status FFmpegBaseEncoder::ProcessReceiveData(std::shared_ptr<AVBuffer> &outputBuffer) {
    auto ret = avcodec_receive_packet(avCodecContext_.get(), avPacket_.get()); // L149
    if (ret >= 0) {
        status = ReceivePacketSucc(outputBuffer); // L152
    } else if (ret == AVERROR_EOF) {
        outputBuffer->flag_ = MediaAVCodec::AVCODEC_BUFFER_FLAG_EOS; // L155
        avcodec_flush_buffers(avCodecContext_.get()); // L156
    }
}
```

### 2.3 关键成员（ffmpeg_base_encoder.h:44-94）

```cpp
// ffmpeg_base_encoder.h
class FFmpegBaseEncoder : NoCopyable {
    int32_t maxInputSize_;                          // L39
    std::shared_ptr<AVCodec> avCodec_;              // FFmpeg codec句柄
    std::shared_ptr<AVCodecContext> avCodecContext_;// 编码上下文（核心）
    std::shared_ptr<AVFrame> cachedFrame_;          // PCM输入帧
    std::shared_ptr<AVPacket> avPacket_;            // 编码输出包
    std::shared_ptr<Meta> format_;                 // 编码参数元数据
    DataCallback *dataCallback_{nullptr};           // L63 数据回调（注入点）
    std::shared_ptr<AVBuffer> outBuffer_ {nullptr}; // L66 输出缓冲区预分配
};
```

### 2.4 Context分配与打开（ffmpeg_base_encoder.cpp:244-312）

```cpp
// L244-261: AllocateContext — avcodec_find_encoder_by_name + avcodec_alloc_context3
Status FFmpegBaseEncoder::AllocateContext(const std::string &name) {
    avCodec_ = std::shared_ptr<AVCodec>(
        const_cast<AVCodec *>(avcodec_find_encoder_by_name(name.c_str())), // L248
        [](AVCodec *p) {}); // no-op deleter（FFmpeg静态编码器）
    context = avcodec_alloc_context3(avCodec_.get()); // L261
    avCodecContext_ = std::shared_ptr<AVCodecContext>(context, [](AVCodecContext *ptr) {
        avcodec_free_context(&ptr); // L262-264 RAII释放
    });
}

// L312: OpenContext — avcodec_open2
auto res = avcodec_open2(avCodecContext_.get(), avCodec_.get(), nullptr);

// L332-348: InitFrame — tmpContext用于参数探测
AVCodecContext *context = avcodec_alloc_context3(avCodec_.get()); // L332
auto tmpContext = std::shared_ptr<AVCodecContext>(context, [](AVCodecContext *ptr) {
    avcodec_free_context(&ptr); // L333-335
});
auto res = avcodec_open2(tmpContext.get(), avCodec_.get(), nullptr); // L348
```

---

## 3. AAC 子插件 FFmpegAACEncoderPlugin（aac/ffmpeg_aac_encoder_plugin.cpp:902行）

### 3.1 ADTS 7字节头构造（L37/102-124）

AAC 需要在编码后添加 ADTS 头才能被播放器识别：

```cpp
// L37: ADTS_HEADER_SIZE = 7
// L102-124: GetAdtsHeader — 构建ADTS头部
Status FFmpegAACEncoderPlugin::GetAdtsHeader(std::string &adtsHeader, int32_t &headerSize,
    const std::shared_ptr<AVCodecContext> &avCodecContext, int32_t aacLength) {
    uint32_t frameLength = static_cast<uint32_t>(aacLength + ADTS_HEADER_SIZE); // L111
    adtsHeader += 0xFF; // L113 sync word
    adtsHeader += 0xF1; // L114
    adtsHeader += ((profile) << 0x6) + (freqIdx << 0x2) + (chanCfg >> 0x2); // L115
    adtsHeader += ((frameLength & 0x7FF) >> 0x3); // L117
    headerSize = ADTS_HEADER_SIZE; // L120
}

// L297: 编码后注入ADTS头
GetAdtsHeader(header, headerSize, avCodecContext_, avPacket_->size);
```

### 3.2 AVAudioFifo 重采样缓冲（L694-867）

AAC 编码器内部使用 `av_audio_fifo_*` 管理 PCM 缓冲，支持重采样：

```cpp
// L694-697: AVAudioFifo 分配
if (!(fifo_ = av_audio_fifo_alloc( // L694
    av_get_expect_sample_fmt(avCodecContext_->sample_fmt),
    avCodecContext_->channels,
    avCodecContext_->frame_size))) {
    return Status::ERROR_NO_MEMORY;
}

// L761: 读取FIFO到Frame
av_audio_fifo_read(fifo_, reinterpret_cast<void **>(cachedFrame_->data),
    avCodecContext_->frame_size); // L761

// L826: 写入FIFO
av_audio_fifo_write(fifo_,
    reinterpret_cast<void **>(cachedFrame_->data),
    cachedFrame_->nb_samples); // L826

// L818-819: FIFO重分配（缓冲不足时）
int32_t cacheSize = av_audio_fifo_size(fifo_);
int32_t ret = av_audio_fifo_realloc(fifo_, cacheSize + cachedFrame_->nb_samples); // L819

// L445/867: FIFO reset/free
av_audio_fifo_reset(fifo_);  // L445
av_audio_fifo_free(fifo_);   // L867
```

### 3.3 生命周期（aac/ffmpeg_aac_encoder_plugin.cpp:208-242）

```cpp
Status FFmpegAACEncoderPlugin::Init()     // L208
Status FFmpegAACEncoderPlugin::Start()   // L233
Status FFmpegAACEncoderPlugin::QueueInputBuffer(...) // L242 —> basePlugin->ProcessSendData
Status FFmpegAACEncoderPlugin::QueueOutputBuffer(...) // L277 —> basePlugin->ProcessReceiveData
Status FFmpegAACEncoderPlugin::Stop()    // L838
```

### 3.4 元数据校验（aac/ffmpeg_aac_encoder_plugin.cpp:609）

```cpp
// L609: AAC IS ADTS标志读取
if (meta->Get<Tag::AUDIO_AAC_IS_ADTS>(type)) {
    // ADTS格式使能
}
```

---

## 4. FLAC 子插件 FFmpegFlacEncoderPlugin（flac/ffmpeg_flac_encoder_plugin.cpp:252行）

### 4.1 参数表（L38-57）

```cpp
// L38-44: 采样率表
static const int32_t FLAC_ENCODER_SAMPLE_RATE_TABLE[] = {
    8000, 16000, 22050, 24000, 32000, 44100, 48000, 60000, 96000
};

// L41-57: 通道布局表
static const uint64_t FLAC_CHANNEL_LAYOUT_TABLE[] = {
    AV_CH_LAYOUT_MONO, AV_CH_LAYOUT_STEREO, AV_CH_LAYOUT_SURROUND,
    AV_CH_LAYOUT_4POINT0, AV_CH_LAYOUT_5POINT0_BACK, AV_CH_LAYOUT_5POINT1_BACK,
    AV_CH_LAYOUT_7POINT1_WIDE_BACK
};
```

### 4.2 SetContext 参数注入链（L84-184）

```cpp
// L84-161: SetContext — 配置参数注入
Status FFmpegFlacEncoderPlugin::SetContext(const std::shared_ptr<Meta> &format) {
    format->GetData(Tag::AUDIO_FLAC_COMPLIANCE_LEVEL, complianceLevel); // L88
    format->GetData(Tag::AUDIO_BIT_SAMPLE_WIDTH, bitWidth); // L89
    format->GetData(Tag::AUDIO_CHANNEL_LAYOUT, channelLayout); // L90
    format->GetData(Tag::AUDIO_SAMPLE_RATE, sampleRate); // L91
}
Status FFmpegFlacEncoderPlugin::SetParameter(const std::shared_ptr<Meta> &parameter) {
    basePlugin->AllocateContext("flac"); // L161
    basePlugin->InitContext(parameter);  // L169
    basePlugin->OpenContext();          // L173
    basePlugin->InitFrame();            // L178
}
```

### 4.3 生命周期（flac/ffmpeg_flac_encoder_plugin.cpp:184-244）

```cpp
Status FFmpegFlacEncoderPlugin::Init()        // L184
Status FFmpegFlacEncoderPlugin::Start()        // L189
Status FFmpegFlacEncoderPlugin::Stop()        // L194
Status FFmpegFlacEncoderPlugin::Reset()       // L199
Status FFmpegFlacEncoderPlugin::Release()     // L204
Status FFmpegFlacEncoderPlugin::Flush()      // L209
Status FFmpegFlacEncoderPlugin::QueueInputBuffer(...) // L214 —> basePlugin->ProcessSendData
Status FFmpegFlacEncoderPlugin::QueueOutputBuffer(...) // L221 —> basePlugin->ProcessReceiveData
```

---

## 5. MP3 子插件 AudioMP3EncoderPlugin（mp3/audio_mp3_encoder_plugin.cpp:404行）

```cpp
// audio_mp3_encoder_plugin.cpp:404行
// 注册名: "audio/mpeg"
// 继承FFmpegBaseEncoder基类
// 生命周期: Init/Start/Stop/QueueInputBuffer/QueueOutputBuffer
// MP3无ADTS头（裸流）
```

---

## 6. G711mu 子插件 AudioG711muEncoderPlugin（g711mu/audio_g711mu_encoder_plugin.cpp:304行）

```cpp
// audio_g711mu_encoder_plugin.cpp:304行
// 注册名: "audio/g711mu"
// G.711 μ-law PCM编解码（ITU-T G.711）
// 无需重采样/ADTS头，直接avcodec编码
```

---

## 7. LBVC 子插件 AudioLBVCEncoderPlugin（lbvc/audio_lbvc_encoder_plugin.cpp:285行）

```cpp
// audio_lbvc_encoder_plugin.cpp:285行
// LBVC: Low Bitrate Voice Codec
// 注册名: "audio/lbvc"
// 面向低码率语音场景
```

---

## 8. FFmpeg 通用工具链（common/ffmpeg_utils.cpp:505行 / ffmpeg_convert.cpp:247行）

### 8.1 Mime2CodecId 映射（ffmpeg_utils.cpp:41）

```cpp
// ffmpeg_utils.cpp:41
bool Mime2CodecId(const std::string &mime, AVCodecID &codecId) {
    // MIME → FFmpeg AVCodecID 映射
    // 路由到具体编码器
}
```

### 8.2 色域转换（ffmpeg_convert.cpp:218-220）

```cpp
// ffmpeg_convert.cpp:218-220
std::pair<bool, AVColorSpace> ColorMatrix2AVColorSpace(MatrixCoefficient matrix) {
    static const std::unordered_map<MatrixCoefficient, AVColorSpace> table = {
        // MatrixCoefficient → AVColorSpace 映射
    };
}
```

---

## 9. 编码数据流总结

```
应用层 (OH_AVCodec CAPI)
  ↓ OH_AVCodec_EncodeFrame
  ↓ OH_AVBuffer (PCM数据)
  ↓
AudioEncoderFilter (Filter层, S36/S24关联)
  ↓ QueueInputBuffer
  ↓
FFmpegAAC/FLAC/MP3/G711mu/LBVCEncoderPlugin (插件层)
  ↓ QueueInputBuffer → basePlugin->ProcessSendData
  ↓ av_audio_fifo_write (AAC: 填充FIFO)
  ↓ avcodec_send_frame (L113)
  ↓ avcodec_receive_packet (L149)
  ↓ AAC: GetAdtsHeader (ADTS 7字节头追加)
  ↓ basePlugin->SendOutputBuffer → DataCallback
  ↓
AudioEncoderFilter.OnOutputBufferAvailable (Filter层回调)
  ↓
应用层 (OH_AVCodec_EncodeFrame 返回 OH_AVBuffer)
```

---

## 10. 与其他记忆关联

| 关联记忆 | 关系 |
|----------|------|
| S125 | FFmpegDecoder 解码器体系 → 对称架构 |
| S132 | FFmpeg音频编码器草案 → 同主题（已合并至S158→S174→S176） |
| S158 | FFmpeg音频编码器草案 → 同主题（已合并至S176） |
| S130 | FFmpegAdapter Common工具链 → 共享FFmpegConvert/Utils |
| S50 | AudioResample → 与AAC AVAudioFifo重采样机制关联 |
| S8 | FFmpeg音频插件总览 → 总览层 |
| S174 | 前次orphan commit → 已合并至S176（同一主题深度增强） |