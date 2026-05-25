# MEM-ARCH-AVCODEC-S125

> **记忆工厂草案** | Builder Agent | 2026-05-26T02:04+08:00  
> **主题**: FFmpeg 软件解码器基类与 FFmpeg 音频解码插件体系——FfmpegBaseDecoder / Resample / FfmpegDecoderPlugin 三层架构  
> **状态**: pending_approval  
> **关联**: S35/S8/S50/S60/S130/S158/S169/S184/S188

---

## 1 架构概览

FFmpeg 软件音频解码器采用三层架构：

```
FfmpegDecoderPlugin (插件注册层, 50 codec变体)
    └── FfmpegBaseDecoder (引擎基类, libavcodec管线)
            └── FfmpegConvert::Resample (重采样层, libswresample)
```

- **E1**: `ffmpeg_decoder_plugin.cpp L37-92`: codecVec 50 codec名称向量
- **E2**: `ffmpeg_decoder_plugin.cpp L94-138`: codecMimeMap 50 MIME向量
- **E3**: `ffmpeg_decoder_plugin.cpp L140-170`: codecInitMap 50函数指针向量，CRTP模板实例化
- **E4**: `ffmpeg_base_decoder.cpp L23-31`: NoCopyable禁止拷贝 + 头文件依赖链
- **E5**: `ffmpeg_base_decoder.h L27-28`: `extern "C"`包裹libavcodec/libavutil
- **E6**: `ffmpeg_convert.cpp L23-25`: Resample::Init() swr_alloc_set_opts2初始化

---

## 2 FfmpegDecoderPlugin 注册层

### 2.1 50 Codec变体向量

**证据**: `ffmpeg_decoder_plugin.cpp L37-92` codecVec (50个FFmpeg codec名称):

| 索引 | codec名 | 说明 |
|------|---------|------|
| 0 | mp3 | AUDIO_DECODER_MP3_NAME |
| 1 | aac | AUDIO_DECODER_AAC_NAME |
| 2 | flac | AUDIO_DECODER_FLAC_NAME |
| 3 | vorbis | AUDIO_DECODER_VORBIS_NAME |
| 4-6 | amrnb/amrwb/ape | AMR家族+APE |
| 7 | ac3 | AUDIO_DECODER_AC3_NAME |
| 8-39 | adpcm×34 | ADPCM系列(PSX/SBPRO/DTK/THP/YAMAHA等) |
| 40-42 | wma×3 | wmav1/wmav2/wmapro |
| 43 | alac | AUDIO_DECODER_ALAC_NAME |
| 44 | ilbc | AUDIO_DECODER_ILBC_NAME |
| 45 | truehd | (SUPPORT_CODEC_TRUEHD) |
| 46 | twinvq | AUDIO_DECODER_TWINVQ_NAME |
| 47 | dvaudio | AUDIO_DECODER_DVAUDIO_NAME |
| 48 | dts | (SUPPORT_CODEC_DTS) |
| 49 | cook | AUDIO_DECODER_COOK_NAME |

### 2.2 50 MIME类型映射

**证据**: `ffmpeg_decoder_plugin.cpp L94-138` codecMimeMap (AUDIO_MPEG/AUDIO_AAC/AUDIO_FLAC等)

### 2.3 CRTP函数指针驱动

**证据**: `ffmpeg_decoder_plugin.cpp L140-170` codecInitMap (InitDefinition<T>模板50实例化):

```cpp
static const std::vector<void(*)(...)> codecInitMap = {
    InitDefinition<FFmpegMp3DecoderPlugin>,    // 0
    InitDefinition<FFmpegAACDecoderPlugin>,    // 1
    InitDefinition<FFmpegFlacDecoderPlugin>,   // 2
    // ... (50个函数指针)
};
```

**关键**: 同一ADPCM类型共享FFmpegADPCMDecoderPlugin类实例(索引10-39)

---

## 3 FfmpegBaseDecoder 引擎基类

### 3.1 关键成员

**证据**: `ffmpeg_base_decoder.h L68-104`:

```cpp
class FfmpegBaseDecoder : public NoCopyable {
    bool isFirst;
    bool hasExtra_;
    bool currentFrameFormatChanged_;
    int32_t maxInputSize_;
    int64_t nextPts_;
    int64_t inputPts_;
    float durationTime_;
    
    std::shared_ptr<AVCodec> avCodec_;           // FFmpeg codec实例
    std::shared_ptr<AVCodecContext> avCodecContext_; // codec上下文
    std::shared_ptr<AVFrame> cachedFrame_;       // 解码帧缓存
    std::shared_ptr<AVPacket> avPacket_;          // 输入packet
    std::mutex avMutext_;                         // 线程安全
    std::mutex parameterMutex_;
    
    Ffmpeg::Resample resample_;                  // 重采样器
    bool needResample_;
    AVSampleFormat destFmt_;
    std::shared_ptr<AVFrame> convertedFrame_;    // 转换后帧
    DataCallback *dataCallback_;
    std::vector<uint8_t> config_data;
    int32_t againIndex_;                          // 分片输出索引
};
```

### 3.2 SendBuffer 管线 (avcodec_send_packet)

**证据**: `ffmpeg_base_decoder.cpp L126-170`:

```cpp
Status FfmpegBaseDecoder::SendBuffer(const std::shared_ptr<AVBuffer> &inputBuffer)
{
    // L141-150: 内存拷贝到avPacket
    avPacket_->size = memory->GetSize();
    avPacket_->data = ptr;
    avPacket_->pts = inputBuffer->pts_;
    // L152: avcodec_send_packet发送
    auto ret = avcodec_send_packet(avCodecContext_.get(), avPacket_.get());
    // L153: av_packet_unref释放packet引用
    av_packet_unref(avPacket_.get());
    // L154-169: 错误处理分支
    if (ret == 0) -> OK
    else if (ret == AVERROR(EAGAIN)) -> ERROR_NOT_ENOUGH_DATA
    else if (ret == AVERROR_EOF) -> END_OF_STREAM
    else if (ret == AVERROR_INVALIDDATA) -> ERROR_INVALID_DATA
    else -> ERROR_UNKNOWN
}
```

### 3.3 ReceiveBuffer 管线 (avcodec_receive_frame)

**证据**: `ffmpeg_base_decoder.cpp L172-210`:

```cpp
Status FfmpegBaseDecoder::ReceiveBuffer(std::shared_ptr<AVBuffer> &outBuffer)
{
    const bool lastStatusIsAgain = againIndex_ > 0;
    auto ret = lastStatusIsAgain ? 0 : avcodec_receive_frame(avCodecContext_.get(), cachedFrame_.get());
    if (ret >= 0) {
        // L184-192: PTS处理
        if (cachedFrame_->pts == AV_NOPTS_VALUE) {
            cachedFrame_->pts = (inputPts_ == 0 ? nextPts_ : inputPts_);
            inputPts_ = 0;
        } else if (lastStatusIsAgain) {
            cachedFrame_->pts = nextPts_;
        }
        CheckFormatChange();
        status = ReceiveFrameSucc(outBuffer);
    }
    // againIndex_分片处理...
}
```

### 3.4 againIndex_ 分片输出机制

**证据**: `ffmpeg_base_decoder.h L103`: `int32_t againIndex_`

当avcodec_receive_frame返回EAGAIN时(输出尚未就绪)，againIndex_++，下次调用复用已缓存帧

### 3.5 Resample重采样集成

**证据**: `ffmpeg_base_decoder.h L91`: `Ffmpeg::Resample resample_`

**E7**: `ffmpeg_convert.cpp L23-25`: Resample::Init() 调用swr_alloc_set_opts2初始化SwrContext

**E8**: `ffmpeg_convert.cpp L34-44`: swr_alloc_set_opts2参数设置(channelLayout/destFmt/sampleRate)

**E9**: `ffmpeg_convert.cpp L55-68`: swr_init初始化后swrCtx_智能指针管理

---

## 4 重采样器 Resample

### 4.1 InitSwrContext 全初始化路径

**证据**: `ffmpeg_convert.cpp L67-86`:

```cpp
Status Resample::InitSwrContext(const ResamplePara &resamplePara)
{
    auto swrContext = swr_alloc();
    int32_t error = swr_alloc_set_opts2(&swrContext,
        &resamplePara_.channelLayout, resamplePara_.destFmt, resamplePara_.sampleRate,
        &resamplePara_.channelLayout, resamplePara_.srcFfFmt, resamplePara_.sampleRate, 0, nullptr);
    if (swr_init(swrContext) != 0) {
        swr_free(&swrContext);
        return Status::ERROR_UNKNOWN;
    }
    swrCtx_ = std::shared_ptr<SwrContext>(swrContext, [](SwrContext *ptr) {
        swr_free(&ptr);
    });
}
```

### 4.2 ConvertCommon 重采样转换

**证据**: `ffmpeg_convert.cpp L98-125`:

```cpp
void Resample::ConvertCommon(const uint8_t *srcBuffer, const size_t srcLength,
                             uint8_t *&destBuffer, size_t &destLength)
{
    // L101-107: Planar格式展开
    if (av_sample_fmt_is_planar(resamplePara_.srcFfFmt)) {
        for (size_t i = 1; i < tmpInput.size(); ++i) {
            tmpInput[i] = tmpInput[i - 1] + lineSize;
        }
    }
    // L109: 计算采样数
    auto samples = lineSize / static_cast<size_t>(av_get_bytes_per_sample(resamplePara_.srcFfFmt));
    // L111-112: swr_convert转换
    size_t destSize = swr_convert(swrCtx_.get(), ...);
}
```

---

## 5 能力注册

**证据**: `ffmpeg_decoder_plugin.cpp L37-50`: codecVec 50种codec名称

**E10**: `ffmpeg_decoder_plugin.cpp L37`: mp3 (AUDIO_DECODER_MP3_NAME)

**E11**: `ffmpeg_decoder_plugin.cpp L38`: aac (AUDIO_DECODER_AAC_NAME)

**E12**: `ffmpeg_decoder_plugin.cpp L39`: flac (AUDIO_DECODER_FLAC_NAME)

**E13**: `ffmpeg_decoder_plugin.cpp L43`: alac (AUDIO_DECODER_ALAC_NAME)

**E14**: `ffmpeg_decoder_plugin.cpp L49`: cook (AUDIO_DECODER_COOK_NAME)

**E15**: `ffmpeg_base_decoder.cpp L23-31`: NoCopyable+头文件依赖(libavcodec/avutil)

---

## 6 与其他模块的关系

| 关联模块 | 关系 | 说明 |
|---------|------|------|
| S35 (AudioDecoderFilter) | 上游Filter封装 | AudioDecoderFilter→FfmpegBaseDecoder→具体decoder |
| S8 (FFmpeg音频插件总览) | 互补 | S8总览，S125源码深度分析 |
| S50 (AudioResample) | 共享Resample | S50的SwrContext与S125共享ffmpeg_convert |
| S130 (FFmpegAdapterCommon) | 共用工具 | FfmpegConvert/ChannelLayout映射表共享 |
| S158/S169/S176 (AudioEncoder) | 对称 | 编码器三层架构(S158)与解码器对称 |
| S184/S188 (FFmpeg Audio Decoder增强版) | 互补 | S184为本地镜像增强版 |

---

## 7 关键证据索引

| 证据 | 文件 | 行号 |
|------|------|------|
| codecVec 50 codec名称向量 | ffmpeg_decoder_plugin.cpp | L37-92 |
| codecMimeMap 50 MIME向量 | ffmpeg_decoder_plugin.cpp | L94-138 |
| codecInitMap 50函数指针 | ffmpeg_decoder_plugin.cpp | L140-170 |
| ADPCM共享FFmpegADPCMDecoderPlugin | ffmpeg_decoder_plugin.cpp | L10-39 |
| FfmpegBaseDecoder类定义 | ffmpeg_base_decoder.h | L27-104 |
| avcodec_send_packet管线 | ffmpeg_base_decoder.cpp | L126-170 |
| avcodec_receive_frame管线 | ffmpeg_base_decoder.cpp | L172-210 |
| againIndex_分片输出 | ffmpeg_base_decoder.h | L103 |
| Resample swr_alloc_set_opts2 | ffmpeg_convert.cpp | L23-25 |
| Resample swr_init | ffmpeg_convert.cpp | L55-68 |
| Resample ConvertCommon | ffmpeg_convert.cpp | L98-125 |
| SUPPORT_CODEC_TRUEHD条件编译 | ffmpeg_decoder_plugin.cpp | L45 |
| SUPPORT_CODEC_DTS条件编译 | ffmpeg_decoder_plugin.cpp | L48 |
| NoCopyable禁止拷贝 | ffmpeg_base_decoder.cpp | L23 |
| extern "C" libavcodec | ffmpeg_base_decoder.h | L27-28 |
| config_data存储extradata | ffmpeg_base_decoder.h | L102 |
| needResample_自动触发 | ffmpeg_base_decoder.cpp | L53 |

---

## 8 工程信息

- **本地镜像路径**: `/home/west/av_codec_repo`
- **源码文件**:
  - `services/media_engine/plugins/ffmpeg_adapter/audio_decoder/ffmpeg_decoder_plugin.cpp` (250行)
  - `services/media_engine/plugins/ffmpeg_adapter/audio_decoder/ffmpeg_decoder_plugin.h` (46行)
  - `services/media_engine/plugins/ffmpeg_adapter/audio_decoder/ffmpeg_base_decoder.cpp` (605行)
  - `services/media_engine/plugins/ffmpeg_adapter/audio_decoder/ffmpeg_base_decoder.h` (129行)
  - `services/media_engine/plugins/ffmpeg_adapter/common/ffmpeg_convert.cpp` (247行)
  - `services/media_engine/plugins/ffmpeg_adapter/common/ffmpeg_convert.h` (98行)
- **编译产物**: `libffmpeg_adapter.z.so`
- **依赖库**: `libavcodec.z.so`, `libavutil.z.so`, `libswresample.z.so`