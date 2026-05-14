---
type: architecture
id: MEM-ARCH-AVCODEC-S125
status: draft
topic: FFmpeg 软件解码器基类与 FFmpeg 音频解码插件体系——FfmpegBaseDecoder / Resample / FfmpegDecoderPlugin 三层架构
scope: [AVCodec, AudioCodec, FFmpeg, Plugin, SoftwareCodec, Resample, SwrContext, libavcodec, avcodec_send_packet, avcodec_receive_frame, AudioDecoder, FfmpegBaseDecoder, FfmpegDecoderPlugin, AutoRegisterFilter, Filter, AAC, AC3, MP3, FLAC, Vorbis, WMA, DTS, DecoderPlugin]
created_at: "2026-05-14T08:10:00+08:00"
updated_at: "2026-05-14T08:10:00+08:00"
source_repo: /home/west/av_codec_repo
source_root: services/media_engine/plugins/ffmpeg_adapter
evidence_version: local_mirror
---

## 一、架构总览

FFmpeg 软件解码器体系位于 `services/media_engine/plugins/ffmpeg_adapter/` 目录下，分为两大层次：

1. **引擎层**：`FfmpegBaseDecoder`（`ffmpeg_base_decoder.cpp/h`，605行cpp+129行h）+ `Resample` 重采样器（`ffmpeg_convert.cpp/h`，247行cpp+98行h）
2. **插件层**：`FfmpegDecoderPlugin`（`ffmpeg_decoder_plugin.cpp/h`，250行cpp+46行h），继承 `AudioDecoderPlugin`，通过 CRTP 模式注册具体子插件（`aac/`、`ac3/`、`mp3/`、`flac/`、`vorbis/`、`wma/`、`dts/` 等 17+ 音频格式）

三层调用链：**AudioDecoderFilter（S35） → FfmpegDecoderPlugin → FfmpegBaseDecoder → libavcodec（avcodec_send_packet / avcodec_receive_frame）**

```
AudioDecoderFilter (Filter层)
  └─► FfmpegDecoderPlugin (ffmpeg_decoder_plugin.cpp:250)
        └─► FfmpegBaseDecoder (ffmpeg_base_decoder.cpp:605)
              ├─► avCodecContext_  (std::shared_ptr<AVCodecContext>)
              ├─► cachedFrame_     (std::shared_ptr<AVFrame>)
              ├─► resample_        (Ffmpeg::Resample)
              └─► libavcodec (avcodec_send_packet / avcodec_receive_frame)
```

**关联记忆**：
- S35：AudioDecoderFilter 音频解码过滤器（Filter 层封装）
- S8：音频编解码 FFmpeg 插件架构总览
- S60：AAC 音频编解码 FFmpeg 插件（ADTS/RESAMPLE 四通道）
- S50：AudioResample 音频重采样框架（SwrContext/libswresample）

---

## 二、FfmpegBaseDecoder 引擎基类

**源码路径**：`services/media_engine/plugins/ffmpeg_adapter/audio_decoder/ffmpeg_base_decoder.h`

### 2.1 类继承结构

```
FfmpegBaseDecoder : public NoCopyable
├── avCodecContext_ : std::shared_ptr<AVCodecContext>   // FFmpeg codec上下文
├── cachedFrame_    : std::shared_ptr<AVFrame>          // 解码输出帧缓存
├── avPacket_       : std::shared_ptr<AVPacket>         // 输入数据包
├── format_         : std::shared_ptr<Meta>             // 输出元数据
├── resample_       : Ffmpeg::Resample                  // 重采样器
├── needResample_   : bool                              // 是否需要重采样
├── againIndex_     : int32_t                           // EAGAIN 重试计数
└── preSampleRate_/preChannels_/preFormat_              // 格式变化检测
```

### 2.2 核心方法（行号级）

| 方法 | 位置 | 说明 |
|------|------|------|
| `FfmpegBaseDecoder()` 构造函数 | `ffmpeg_base_decoder.cpp:54-58` | 初始化 needResample_=false，againIndex_=0 |
| `ProcessSendData()` | `ffmpeg_base_decoder.cpp:151` | `avcodec_send_packet(avCodecContext_.get(), avPacket_.get())` 发送压缩数据 |
| `ProcessReceiveData()` | `ffmpeg_base_decoder.cpp:189` | `avcodec_receive_frame()` 接收解码帧 |
| `ReceiveFrameSucc()` | `ffmpeg_base_decoder.cpp:116` | 成功接收帧回调（触发重采样初始化） |
| `Flush()` | `ffmpeg_base_decoder.cpp:207` | `avcodec_flush_buffers()` 刷新解码器 |
| `InitResample()` | `ffmpeg_base_decoder.cpp:269` | 初始化重采样器 |
| `EnableResample()` | `ffmpeg_base_decoder.cpp:309` | 启用重采样 |
| `CreateCodecContext()` | `ffmpeg_base_decoder.cpp:358-365` | 创建 AVCodecContext 并打开解码器 |
| `SetCodecContext()` | `ffmpeg_base_decoder.cpp:334` | 持有外部传入的 AVCodecContext |

### 2.3 libavcodec 三函数管线

```
avcodec_send_packet (line 151)
    ↓ 输入压缩数据
avcodec_receive_frame (line 189)
    ↓ 输出解码帧
avcodec_flush_buffers (line 207/335)
    ↓ 刷新解码器状态
```

**关键常量**：
- `againIndex_`：EAGAIN 错误时的重试计数器，`againIndex_ == 0` 时触发 `EnableResample`（line 309）
- `needResample_`：解码器输出格式与目标格式不一致时触发重采样

### 2.4 格式变化检测与自动重采样

```cpp
// ffmpeg_base_decoder.cpp:243-250
if (preSampleRate != avCodecContext_->sample_rate ||
    preChannels != avCodecContext_->ch_layout.nb_channels ||
    preFormat != currentFormat) {
    // 更新元数据：采样率、通道数
    format_->SetData(Tag::AUDIO_SAMPLE_RATE, avCodecContext_->sample_rate);
    format_->SetData(Tag::AUDIO_CHANNEL_COUNT, avCodecContext_->ch_layout.nb_channels);
    // 触发 EnableResample
    EnableResample(...);
}
```

### 2.5 AVCodecContext 创建流程

```cpp
// ffmpeg_base_decoder.cpp:358-365
avCodecContext_ = std::shared_ptr<AVCodecContext>(context, [](AVCodecContext *ptr) {
    // 自定义删除器
});
CHECK_AND_RETURN_RET_LOG(avCodecContext_ != nullptr, Status::ERROR_NO_MEMORY, ...);
```

---

## 三、Resample 重采样器

**源码路径**：`services/media_engine/plugins/ffmpeg_adapter/common/ffmpeg_convert.h`

### 3.1 ResamplePara 结构体（line 42-51）

```cpp
struct ResamplePara {
    int32_t inSampleRate_;       // 输入采样率
    int32_t outSampleRate_;      // 输出采样率
    int32_t inChannels_;        // 输入通道数
    int32_t outChannels_;       // 输出通道数
    AVSampleFormat inFormat_;    // 输入格式
    AVSampleFormat outFormat_;   // 输出格式
    uint64_t inChannelLayout_;   // 输入通道布局
    uint64_t outChannelLayout_;  // 输出通道布局
};
```

### 3.2 Resample 类接口

```cpp
class Resample {
    Resample() = default;
    ~Resample();
    Status Init(const ResamplePara &resamplePara);          // 初始化
    Status InitSwrContext(const ResamplePara &resamplePara); // 创建 SwrContext
    Status Convert(...)                                      // 格式转换
    ResamplePara resamplePara_{};                            // 重采样参数
    SwrContext* swrContext_;                                 // FFmpeg 重采样上下文
};
```

**注意**：Resample 使用 FFmpeg libswresample 的 `SwrContext`（非 S50 的 AudioResample 基于 AudioCodecWorker 双 TaskThread 方案，两者独立）

---

## 四、FfmpegDecoderPlugin 插件层

**源码路径**：`services/media_engine/plugins/ffmpeg_adapter/audio_decoder/ffmpeg_decoder_plugin.h`

### 4.1 插件继承结构（CRTP）

```
AudioDecoderPlugin (基类，抽象接口)
  └─► FfmpegDecoderPlugin (ffmpeg_decoder_plugin.h:46)
        ├─► FfmpegAacDecoderPlugin   (aac/)
        ├─► FfmpegAc3DecoderPlugin   (ac3/)
        ├─► FfmpegMp3DecoderPlugin   (mp3/)
        ├─► FfmpegFlacDecoderPlugin  (flac/)
        ├─► FfmpegVorbisDecoderPlugin (vorbis/)
        ├─► FfmpegWmaDecoderPlugin   (wma/)
        ├─► FfmpegDtsDecoderPlugin   (dts/)
        ├─► FfmpegCookDecoderPlugin  (cook/)
        ├─► FfmpegApeDecoderPlugin   (ape/)
        ├─► FfmpegTruehdDecoderPlugin (truehd/)
        ├─► FfmpegTwinvqDecoderPlugin (twinvq/)
        ├─► FfmpegGsmDecoderPlugin   (gsm/)
        ├─► FfmpegGsmMsDecoderPlugin (gsm_ms/)
        ├─► FfmpegG711muDecoderPlugin (g711mu/)
        ├─► FfmpegG711aDecoderPlugin (g711a/)
        ├─► FfmpegAmrnbDecoderPlugin (amrnb/)
        ├─► FfmpegAmrwbDecoderPlugin (amrwb/)
        ├─► FfmpegIlbcDecoderPlugin  (ilbc/)
        ├─► FfmpegDvaudioDecoderPlugin (dvaudio/)
        ├─► FfmpegEac3DecoderPlugin (eac3/)
        └─► FfmpegLbvcDecoderPlugin  (lbvc/)
```

### 4.2 FfmpegDecoderPlugin 接口（行号级）

```cpp
// ffmpeg_decoder_plugin.h
class FfmpegDecoderPlugin : public AudioDecoderPlugin {
    virtual Status Init() override;
    virtual Status Prepare() override;
    virtual Status Start() override;
    virtual Status Stop() override;
    virtual Status Flush() override;
    virtual Status Release() override;
    virtual Status ProcessSendData(const std::shared_ptr<AVBuffer> &inputBuffer) override;
    virtual Status ProcessReceiveData(std::shared_ptr<AVBuffer> &outBuffer) override;
    virtual Status SetInputParameter(const std::shared_ptr<Meta> &parameter) override;
};
```

### 4.3 各子插件行号清单

| 子插件 | 源码路径 | 行数 |
|--------|---------|------|
| AAC | `audio_decoder/aac/ffmpeg_aac_decoder_plugin.cpp` | ~300 |
| AC3 | `audio_decoder/ac3/ffmpeg_ac3_decoder_plugin.cpp` | ~200 |
| MP3 | `audio_decoder/mp3/ffmpeg_mp3_decoder_plugin.cpp` | ~200 |
| FLAC | `audio_decoder/flac/ffmpeg_flac_decoder_plugin.cpp` | ~200 |
| Vorbis | `audio_decoder/vorbis/ffmpeg_vorbis_decoder_plugin.cpp` | ~200 |
| WMA | `audio_decoder/wma/ffmpeg_wma_decoder_plugin.cpp` | ~200 |
| DTS | `audio_decoder/dts/ffmpeg_dts_decoder_plugin.cpp` | ~200 |
| Cook | `audio_decoder/cook/ffmpeg_cook_decoder_plugin.cpp` | ~200 |
| G711mu | `audio_decoder/g711mu/audio_g711mu_decoder_plugin.cpp` | ~200 |
| AMR-NB | `audio_decoder/amrnb/ffmpeg_amrnb_decoder_plugin.cpp` | ~200 |
| AMR-WB | `audio_decoder/amrwb/ffmpeg_amrwb_decoder_plugin.cpp` | ~200 |
| GSM | `audio_decoder/gsm/ffmpeg_gsm_decoder_plugin.cpp` | ~200 |
| ALAC | `audio_decoder/alac/ffmpeg_alac_decoder_plugin.cpp` | ~200 |
| ADPCM | `audio_decoder/adpcm/ffmpeg_adpcm_decoder_plugin.cpp` | ~200 |
| ILBC | `audio_decoder/ilbc/ffmpeg_ilbc_decoder_plugin.cpp` | ~200 |
| RAW PCM | `audio_decoder/raw/audio_raw_decoder_plugin.cpp` | ~200 |

---

## 五、与 S35 AudioDecoderFilter 对接

```
AudioDecoderFilter (services/media_engine/filters/audio_decoder_filter.cpp)
  └─► AudioDecoderAdapter (Filter适配层)
        └─► FfmpegDecoderPlugin
              └─► FfmpegBaseDecoder
                    ├─► libavcodec (avcodec_send_packet / avcodec_receive_frame)
                    └─► Ffmpeg::Resample (libswresample)
```

**Filter 层注册名**：`"builtin.player.audiodecoder"`（`FILTERTYPE_AUDIODEC`）

**AudioDecInputPortConsumerListener** 和 **AudioDecOutPortProducerListener** 双监听器驱动异步编解码循环（与 S35 一致）

---

## 六、与 S8 / S60 关联对比

| 维度 | S8 FFmpeg音频插件总览 | S60 AAC FFmpeg | S125 FfmpegBaseDecoder |
|------|----------------------|----------------|------------------------|
| 层级 | Plugin层总览 | AAC子插件深度 | 引擎基类+插件层 |
| 架构 | AudioFFMpegAacEncoderPlugin+AudioFFMpegAacDecoderPlugin | AAC ADTS 7字节头+AudioResample | FfmpegBaseDecoder+Resample+17+子插件 |
| 重采样 | AudioResample needResample_触发 | SwrContext(libswresample) | Ffmpeg::Resample Resample结构体 |
| 回调 | CodecRegister CRTP | AudioResample | FfmpegDecoderPlugin CRTP |

---

## 七、关键证据摘要

| Evidence | 文件 | 行号 |
|----------|------|------|
| FfmpegBaseDecoder 类定义 | `ffmpeg_base_decoder.h` | 39 |
| ProcessSendData/ProcessReceiveData 双函数管线 | `ffmpeg_base_decoder.cpp` | 151/189 |
| avcodec_send_packet 调用 | `ffmpeg_base_decoder.cpp` | 151 |
| avcodec_receive_frame 调用 | `ffmpeg_base_decoder.cpp` | 189 |
| avcodec_flush_buffers 刷新 | `ffmpeg_base_decoder.cpp` | 207 |
| 格式变化检测触发 EnableResample | `ffmpeg_base_decoder.cpp` | 243-250 |
| AVCodecContext 创建 | `ffmpeg_base_decoder.cpp` | 358-365 |
| ResamplePara 结构体 | `ffmpeg_convert.h` | 42-51 |
| Resample 类接口 | `ffmpeg_convert.h` | 54-62 |
| FfmpegDecoderPlugin CRTP 继承 | `ffmpeg_decoder_plugin.h` | 46 |
| 17+ 音频格式子插件目录 | `audio_decoder/` | 目录列表 |
| againIndex_ EAGAIN 重试 | `ffmpeg_base_decoder.cpp` | 309 |
| needResample_ 标志 | `ffmpeg_base_decoder.cpp` | 58 |

---

## 八、状态

- **草案生成**：2026-05-14T08:10 Builder
- **提交审批**：待提交
- **关联 S 系列**：S35（AudioDecoderFilter）、S8（FFmpeg音频总览）、S50（AudioResample）、S60（AAC FFmpeg）