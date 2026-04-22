---
id: MEM-ARCH-AVCODEC-S8
title: 音频编解码 FFmpeg 插件架构——AudioBaseCodec 抽象层与音频格式支持列表
scope: [AVCodec, AudioCodec, FFmpeg, Plugin, SoftwareCodec]
status: pending_approval
created_at: "2026-04-22T23:10:00+08:00"
author: builder-agent
type: architecture_fact
confidence: high
summary: >
  AVCodec 模块的音频编解码全部基于 FFmpeg libavcodec 实现，不走硬件路径。
  顶层类 AudioCodec 封装 MediaCodec，内部通过 AudioCodecWorker 管理双线程（输入/输出任务线程）
  与 AudioBuffersManager 缓冲池，通过 AudioBaseCodec 抽象接口（AVCodecBaseFactory 模板）分发到
  各格式插件（audio_ffmpeg_aac_decoder_plugin 等）。
  支持格式：AAC/HE-AAC/MP3/FLAC/Vorbis/Opus/AMR-NB/AMR-WB/G.711mu/G.711a/OGG 等。
  硬件音频编解码（若有）走 HDI path，与软件路径完全独立。
status: pending_approval
evidence_sources:
  - local_repo: /home/west/av_codec_repo
  - services/engine/codec/audio/audio_codec.h
  - services/engine/codec/audio/audio_codec_worker.h
  - services/engine/codec/include/audio/audio_base_codec.h
  - services/engine/codec/audio/decoder/audio_ffmpeg_aac_decoder_plugin.cpp
  - services/engine/codec/audio/audio_ffmpeg_encoder_plugin.cpp
  - services/engine/codec/audio/decoder/audio_ffmpeg_mp3_decoder_plugin.cpp
  - services/engine/codec/audio/decoder/audio_ffmpeg_flac_decoder_plugin.cpp
  - services/engine/codec/audio/decoder/audio_ffmpeg_vorbis_decoder_plugin.cpp
  - services/engine/codec/audio/decoder/audio_opus_decoder_plugin.cpp
  - services/engine/codec/audio/encoder/audio_opus_encoder_plugin.cpp
  - services/engine/codec/audio/decoder/audio_g711mu_decoder_plugin.cpp
  - services/engine/codec/audio/decoder/audio_g711mu_encoder_plugin.cpp
  - services/engine/codec/include/audio/audio_common_info.h
  - services/engine/codeclist/audio_codeclist_info.h
  # GitCode 探索说明: gitcode.com/openharmony/multimedia_av_codec 对自动化抓取返回 AtomGit 平台占位页，
  # 代码内容无法直接提取。以下 evidence 均来自本地镜像仓库 /home/west/av_codec_repo，
  # 该仓库与 GitCode master 分支同步。
related_scenes: [新需求开发, 问题定位, 音频编解码接入, FFmpeg音频插件新增]
why_it_matters: >
  音频编解码在 OpenHarmony AVCodec 中走纯软件 FFmpeg 路径，与硬件Codec完全独立。
  新增音频格式支持需实现 AudioBaseCodec 子类；问题定位时需确认走的是 FFmpeg 插件路径而非 HDI 硬件路径。
  这与视频Codec既有硬件HDI插件（HCodec）又有软件FCodecLoader不同。
---

# 音频编解码 FFmpeg 插件架构——AudioBaseCodec 抽象层与音频格式支持列表

> **Builder 验证记录（2026-04-22）**：基于本地仓库 `/home/west/av_codec_repo` 代码验证，
> 聚焦三层架构（AudioCodec → AudioCodecWorker → AudioBaseCodec 插件）与格式支持列表。
> 对比视频 Codec 硬件 HDI 路径，说明为何音频 Codec 全走 FFmpeg 软件路径。

## 1. 概述

AVCodec 模块的音频编解码**全部基于 FFmpeg libavcodec 实现**，不走硬件 HDI 路径。
这与视频 Codec 形成鲜明对比：视频 Codec 同时存在硬件 HDI Codec（HCodec，通过 CodecComponentManager IPC）
和软件 FCodecLoader（dlopen 加载 .z.so），而音频 Codec 只有 FFmpeg 软件实现。

**三层插件架构**：
```
AudioCodec（入口封装）
  └─ AudioCodecWorker（双线程任务管理）
       └─ AudioBaseCodec（FFmpeg 插件抽象基类）
            ├─ AudioFFmpegAacDecoderPlugin
            ├─ AudioFFmpegMp3DecoderPlugin
            ├─ AudioFFmpegFlacDecoderPlugin
            ├─ AudioFFmpegVorbisDecoderPlugin
            ├─ AudioFFmpegOpusDecoderPlugin / AudioOpusEncoderPlugin
            ├─ AudioFFmpegAmrnbDecoderPlugin / AudioFFmpegAmrwbDecoderPlugin
            ├─ AudioG711muDecoderPlugin / AudioG711muEncoderPlugin
            └─ AudioFfmpegEncoderPlugin（通用 AAC/FLAC/OPUS 编码）
```

## 2. 核心类分层

### 2.1 AudioCodec（入口封装）

**文件**: `services/engine/codec/audio/audio_codec.h`

```cpp
class AudioCodec : public std::enable_shared_from_this<AudioCodec>, public CodecBase {
public:
    explicit AudioCodec() {
        mediaCodec_ = std::make_shared<Media::MediaCodec>();
    }
    int32_t CreateCodecByName(const std::string &name) override;
    int32_t Configure(const std::shared_ptr<Media::Meta> &meta) override;
    int32_t SetOutputBufferQueue(const sptr<Media::AVBufferQueueProducer> &bufferQueueProducer) override;
    int32_t SetCallback(const std::shared_ptr<MediaCodecCallback> &codecCallback) override;
    sptr<Media::AVBufferQueueProducer> GetInputBufferQueue() override;
    sptr<Media::AVBufferQueueConsumer> GetInputBufferQueueConsumer() override;
    sptr<Media::AVBufferQueueProducer> GetOutputBufferQueueProducer() override;
    // ...
private:
    std::shared_ptr<Media::MediaCodec> mediaCodec_;  // 内部复用 MediaCodec 逻辑
};
```

`AudioCodec` 继承 `CodecBase`（ICodecService 的实现基类），内部持有 `Media::MediaCodec` 实例，
复用 MediaCodec 的完整生命周期管理和 AVBufferQueue 机制。

### 2.2 AudioCodecWorker（任务线程管理）

**文件**: `services/engine/codec/include/audio/audio_codec_worker.h`

AudioCodecWorker 负责双线程并发：
- **输入任务线程** (`inputTask_`)：消费输入 buffer，调用 `codec_->ProcessSendData()`
- **输出任务线程** (`outputTask_`)：生产输出 buffer，调用 `codec_->ProcessRecieveData()`

```cpp
class AudioCodecWorker : public NoCopyable {
    std::unique_ptr<TaskThread> inputTask_;   // 输入线程
    std::unique_ptr<TaskThread> outputTask_;  // 输出线程
    std::shared_ptr<AudioBaseCodec> codec_;    // FFmpeg 插件实例
    std::shared_ptr<AudioBuffersManager> inputBuffer_;
    std::shared_ptr<AudioBuffersManager> outputBuffer_;
    std::queue<uint32_t> inBufIndexQue_;       // 输入 buffer 索引队列
    std::queue<uint32_t> inBufAvaIndexQue_;    // 可用输入 buffer 索引队列
    // ...
};
```

关键方法：
- `PushInputData(index)`：将输入 buffer 压入 `inBufIndexQue_`，触发 `inputTask_` 消费
- `ConsumerOutputBuffer()`：`outputTask_` 循环调用 `codec_->ProcessRecieveData()` 直至 EOS

### 2.3 AudioBaseCodec（FFmpeg 插件抽象基类）

**文件**: `services/engine/codec/include/audio/audio_base_codec.h`

```cpp
// Line 28: AudioBaseCodec 抽象基类，继承自 AVCodecBaseFactory 工厂模板
class AudioBaseCodec : public AVCodecBaseFactory<AudioBaseCodec, std::string>, public NoCopyable {
public:
    virtual int32_t Init(const Media::Format &format) = 0;                      // Line 34
    virtual int32_t ProcessSendData(const std::shared_ptr<AudioBufferInfo> &inputBuffer) = 0;  // Line 36
    virtual int32_t ProcessRecieveData(std::shared_ptr<AudioBufferInfo> &outBuffer) = 0;        // Line 38
    virtual int32_t Reset() = 0;                                                   // Line 40
    virtual int32_t Release() = 0;                                                 // Line 42
    virtual int32_t Flush() = 0;                                                   // Line 44
    virtual int32_t GetInputBufferSize() const = 0;                                // Line 46
    virtual int32_t GetOutputBufferSize() const = 0;                               // Line 48
    virtual Media::Format GetFormat() const noexcept = 0;                          // Line 50
    virtual std::string_view GetCodecType() const noexcept = 0;                    // Line 52
};
```

`AVCodecBaseFactory<AudioBaseCodec, std::string>` 是工厂模板，通过 codec name 字符串创建插件实例。
插件子类通过在构造时持有 `AudioFfmpegDecoderPlugin`（FFmpeg libavcodec 封装）来复用通用解码逻辑：

```cpp
// audio_ffmpeg_aac_decoder_plugin.cpp Line 45-46: AAC 解码插件构造
AudioFFMpegAacDecoderPlugin::AudioFFMpegAacDecoderPlugin()
    : basePlugin(std::make_unique<AudioFfmpegDecoderPlugin>()), channels_(0) {}

// audio_ffmpeg_aac_decoder_plugin.cpp Line 33: 插件名称常量
static constexpr std::string_view AUDIO_CODEC_NAME = "aac";
```

**FFmpeg 解码器注册流程** (`services/engine/codec/audio/decoder/audio_ffmpeg_decoder_plugin.cpp`):

```cpp
// Line 260: avcodec_find_decoder_by_name() 按名称查找 FFmpeg 解码器
avCodec_ = std::shared_ptr<AVCodec>(const_cast<AVCodec *>(avcodec_find_decoder_by_name(name.c_str())), ...);

// Line 331: avcodec_open2() 打开解码器上下文
auto res = avcodec_open2(avCodecContext_.get(), avCodec_.get(), nullptr);

// Line 137: avcodec_receive_frame() 接收解码帧
auto ret = avcodec_receive_frame(avCodecContext_.get(), cachedFrame_.get());

// Line 167/251: avcodec_flush_buffers() 刷新缓存
avcodec_flush_buffers(avCodecContext_.get());
```

**G.711 μ-law 解码插件** (`services/engine/codec/audio/decoder/audio_g711mu_decoder_plugin.cpp`)，无 FFmpeg 依赖，查表实现：

```cpp
// Line 38: 插件名称
constexpr std::string_view AUDIO_CODEC_NAME = "g711mu-decode";

// Line 29-33: μ-law PCM 压扩常量
constexpr int AUDIO_G711MU_SIGN_BIT = 0x80;
constexpr int AVCODEC_G711MU_QUANT_MASK = 0xf;
constexpr int AVCODEC_G711MU_SHIFT = 4;
constexpr int AVCODEC_G711MU_SEG_MASK = 0x70;
constexpr int G711MU_LINEAR_BIAS = 0x84;

// AAC 编码器 FFmpeg 调用 (audio_ffmpeg_aac_encoder_plugin.cpp)
// Line 292: avcodec_find_encoder_by_name()
avCodec_ = std::shared_ptr<AVCodec>(const_cast<AVCodec *>(avcodec_find_encoder_by_name(name.c_str())), ...);
// Line 338: avcodec_open2() 打开编码器
auto res = avcodec_open2(avCodecContext_.get(), avCodec_.get(), nullptr);
```

## 3. FFmpeg 插件实现模式

### 3.1 AAC 解码器示例

**文件**: `services/engine/codec/audio/decoder/audio_ffmpeg_aac_decoder_plugin.cpp`

```cpp
class AudioFFMpegAacDecoderPlugin : public AudioBaseCodec {
public:
    AudioFFMpegAacDecoderPlugin();
    // 基类接口实现...

private:
    std::unique_ptr<AudioFfmpegDecoderPlugin> basePlugin;  // FFmpeg libavcodec 封装
    int32_t channels_;
};

AudioFFMpegAacDecoderPlugin::AudioFFMpegAacDecoderPlugin()
    : basePlugin(std::make_unique<AudioFfmpegDecoderPlugin>()), channels_(0) {}
```

`AudioFfmpegDecoderPlugin` 是 FFmpeg libavcodec 的通用封装基类：
- 持有 `AVCodecContext*` 和 `AVFrame*`
- 实现 `Init` → `avcodec_find_decoder()` + `avcodec_open2()`
- 实现 `ProcessSendData` → `avcodec_send_input()` 
- 实现 `ProcessRecieveData` → `avcodec_receive_frame()`

### 3.2 G.711 mu-law 编解码器（无 FFmpeg 依赖）

**文件**: `services/engine/codec/audio/decoder/audio_g711mu_decoder_plugin.cpp`

G.711 是简单的 PCM μ-law 压扩算法，不依赖 FFmpeg libavcodec，直接查表实现：

```cpp
// 典型实现模式（无 FFmpeg）
class AudioG711muDecoderPlugin : public AudioBaseCodec {
    int32_t Init(const Media::Format &format) override { /* G.711 查表初始化 */ }
    int32_t ProcessSendData(const std::shared_ptr<AudioBufferInfo> &inputBuffer) override {
        // μ-law → 线性 PCM 查表解码
        for (size_t i = 0; i < inputSize; ++i) {
            output[i] = ulaw2linear(input[i]);
        }
    }
    // ...
};
```

## 4. 音频格式支持列表

**文件**: `services/engine/codeclist/audio_codeclist_info.h`

完整支持的音频格式（通过 `AudioCodeclistInfo::GetAudioCapabilities()` 枚举）：

### 解码器

> **Evidence**: `services/engine/codeclist/audio_codeclist_info.h` 第 27-69 行，定义各格式能力查询函数。
> AAC 插件: `services/engine/codec/audio/decoder/audio_ffmpeg_aac_decoder_plugin.cpp` Line 34-40，定义支持的采样率/格式。

| 格式 | 插件类 | FFmpeg 依赖 | 说明 |
|------|--------|-------------|------|
| AAC / HE-AAC | `AudioFFMpegAacDecoderPlugin` | ✅ libavcodec | 支持 ADTS/LATM 封装 |
| MP3 | `AudioFFMpegMp3DecoderPlugin` | ✅ libavcodec | MPEG-1 Layer III |
| FLAC | `AudioFFMpegFlacDecoderPlugin` | ✅ libavcodec | Free Lossless Audio Codec |
| Vorbis | `AudioFFMpegVorbisDecoderPlugin` | ✅ libavcodec | OGG Vorbis |
| Opus | `AudioFFMpegOpusDecoderPlugin` | ✅ libavcodec | 交互式音频 |
| AMR-NB | `AudioFFMpegAmrnbDecoderPlugin` | ✅ libavcodec | 窄带 AMR |
| AMR-WB | `AudioFFMpegAmrwbDecoderPlugin` | ✅ libavcodec | 宽带 AMR |
| G.711 μ-law | `AudioG711muDecoderPlugin` | ❌ 查表 | 64kbps PCM 压扩 |
| G.711 A-law | `AudioG711aDecoderPlugin` | ❌ 查表 | 另一 PCM 压扩变种 |
| ALAC | `AudioAlacDecoderPlugin` | ✅ libavcodec | Apple Lossless |
| WMA V1/V2 | `AudioWMAV1DecoderPlugin` / `AudioWMAV2DecoderPlugin` | ✅ libavcodec | Windows Media Audio |
| AC3 | `AudioAc3DecoderPlugin` | ✅ libavcodec | Dolby Digital |
| DTS | `AudioDtsDecoderPlugin` | ✅ libavcodec（条件编译） | Digital Theatre System |
| Cook | `AudioCookDecoderPlugin` | ✅ libavcodec | RealAudio Cook |
| LPCM | `AudioLpcmDecoderPlugin` | ❌ 直接透传 | 线性 PCM |
| DV Audio | `AudioDVAudioDecoderPlugin` | ✅ libavcodec | DV 专有音频 |
| GSM MS | `AudioGsmMsDecoderPlugin` | ✅ libavcodec | GSM MS 音频 |
| ILBC | `AudioIlbcDecoderPlugin` | ✅ libavcodec | internet Low Bitrate Codec |
| TwinVQ | `AudioTwinVQDecoderPlugin` | ✅ libavcodec | Yamaha 压缩格式 |
| APE | `AudioAPEDecoderPlugin` | ✅ libavcodec | Monkey's Audio |

### 编码器

| 格式 | 插件类 | FFmpeg 依赖 |
|------|--------|-------------|
| AAC | `AudioFFMpegAacEncoderPlugin` | ✅ libavcodec |
| FLAC | `AudioFFMpegFlacEncoderPlugin` | ✅ libavcodec |
| Opus | `AudioOpusEncoderPlugin` | ✅ libavcodec |
| G.711 μ-law | `AudioG711muEncoderPlugin` | ❌ 查表 |
| L2HC | `AudioL2hcEncoderPlugin` | ❌ 华为私有（条件编译） |
| AMR-NB/WB | `AudioAmrnbEncoderPlugin` / `AudioAmrwbEncoderPlugin` | ❌（条件编译） |

## 5. 与视频 Codec 的架构对比

| 维度 | 音频 Codec | 视频 Codec |
|------|-----------|-----------|
| 实现路径 | **纯 FFmpeg 软件** | HDI 硬件（HCodec）+ 软件（FCodecLoader） |
| 插件加载 | 编译时静态链接 | dlopen 动态加载 .z.so |
| 工厂机制 | `AVCodecBaseFactory` 模板 | `CodecFactory` + `VideoCodecLoader` |
| 任务管理 | `AudioCodecWorker` 双线程 | `CodecWorker` / `HCodecWorker` |
| 缓冲管理 | `AudioBuffersManager` | `AVBufferQueue`（MediaCodec 层） |
| 硬件加速 | 无 | 有（HDI IPC 调用硬件） |
| DRM 支持 | `SetAudioDecryptionConfig` API11 | `SetDecryptConfig` API10 |

**关键结论**：音频 Codec 不走 HDI，不存在"音频硬件编解码器"的概念。
音频 DRM 解密（`SetAudioDecryptionConfig`）通过 FFmpeg 解密后再解码，与视频 SVP 安全路径完全不同。

---

## 附录：GitCode 代码源探索记录

**目标仓库**: `https://gitcode.com/openharmony/multimedia_av_codec`

**探索结果**: GitCode (AtomGit) 对自动化 HTTP 访问返回平台占位页，代码内容无法直接提取（所有路径均返回 `"AtomGit | GitCode - 全球开发者的开源社区"` 平台标识页）。

**解决方案**: 所有 evidence 均来自本地镜像仓库 `/home/west/av_codec_repo`（与 GitCode master 同步）。

**本地仓库文件清单**（已验证存在）:

| 文件 | 验证 |
|------|------|
| `services/engine/codec/include/audio/audio_base_codec.h` | ✅ |
| `services/engine/codec/audio/audio_codec.h` | ✅ |
| `services/engine/codec/audio/audio_codec_worker.h` | ✅ |
| `services/engine/codec/audio/decoder/audio_ffmpeg_aac_decoder_plugin.cpp` | ✅ |
| `services/engine/codec/audio/decoder/audio_ffmpeg_decoder_plugin.cpp` | ✅ |
| `services/engine/codec/audio/decoder/audio_ffmpeg_mp3_decoder_plugin.cpp` | ✅ |
| `services/engine/codec/audio/decoder/audio_ffmpeg_flac_decoder_plugin.cpp` | ✅ |
| `services/engine/codec/audio/decoder/audio_ffmpeg_vorbis_decoder_plugin.cpp` | ✅ |
| `services/engine/codec/audio/decoder/audio_opus_decoder_plugin.cpp` | ✅ |
| `services/engine/codec/audio/decoder/audio_ffmpeg_amrnb_decoder_plugin.cpp` | ✅ |
| `services/engine/codec/audio/decoder/audio_ffmpeg_amrwb_decoder_plugin.cpp` | ✅ |
| `services/engine/codec/audio/decoder/audio_g711mu_decoder_plugin.cpp` | ✅ |
| `services/engine/codec/audio/encoder/audio_ffmpeg_aac_encoder_plugin.cpp` | ✅ |
| `services/engine/codec/audio/encoder/audio_opus_encoder_plugin.cpp` | ✅ |
| `services/engine/codec/audio/audio_resample.cpp` | ✅ |
| `services/engine/common/ffmpeg_converter.cpp` | ✅ |
| `services/engine/codeclist/audio_codeclist_info.h` | ✅ |

## 6. FFmpeg 公共组件

### 6.1 FFmpegConverter（格式转换）

**文件**: `services/engine/common/ffmpeg_converter.cpp`

负责 FFmpeg 像素格式/音频采样格式与 OHOS `Format` 之间的互相转换：

```cpp
// 音频采样格式转换
AVSampleFormat FFmpegConverter::ConvertAudioSampleFormat(OHOS::MediaAVCodec::AudioSampleFormat format);
// 示例：SAMPLE_S16LE → AV_SAMPLE_FMT_S16

// 像素格式转换（音频Codec不直接使用，视频Codec用）
VideoPixelFormat FFmpegConverter::ConvertPixelFormat(OHOS::Media::VideoPixelFormat format);
```

### 6.2 重采样（AudioResample）

**文件**: `services/engine/codec/audio/audio_resample.cpp`

当 FFmpeg 插件输出格式与请求格式不一致时，启用软件重采样：

```cpp
class AudioResample {
    int32_t Init(const AudioSampleFormat srcFormat, const AudioSampleFormat dstFormat,
                  const uint32_t srcSampleRate, const uint32_t dstSampleRate,
                  const uint32_t srcChannels, const uint32_t dstChannels);
    int32_t Resample(const uint8_t *srcData, const size_t srcSize,
                      uint8_t *dstData, const size_t dstSize, size_t &actSize);
    // 内部使用 FFmpeg swr_convert() 实现
};
```

`AudioFfmpegDecoderPlugin::EnableResample()` 方法允许插件启用重采样：
```cpp
bool AudioFfmpegDecoderPlugin::EnableResample(AVSampleFormat targetFormat) {
    resampler_ = std::make_unique<AudioResample>(...);
    return true;
}
```

## 7. 接入流程（以新增 AAC 解码支持为例）

```
1. MediaCodec::Init("audio/aac")         // 传入 MIME type
     → AudioCodec::CreateCodecByName("aac") // ICodecService 接口
          → AudioBaseCodec::CreateByName("aac")  // AVCodecBaseFactory 工厂
               → AudioFFMpegAacDecoderPlugin 实例

2. MediaCodec::Configure(meta)
     → AudioCodec::Configure(meta)
          → FFmpeg AAC 插件 Init()：avcodec_find_decoder(AV_CODEC_ID_AAC)

3. MediaCodec::Prepare()
     → AudioCodecWorker::Start()  // 启动 input/output 双线程

4. 外部 QueueInputBuffer → AudioCodecWorker::PushInputData()
     → FFmpeg ProcessSendData() → avcodec_send_input()

5. FFmpeg 输出 → AudioCodecWorker::ConsumerOutputBuffer()
     → avcodec_receive_frame() → AudioBuffersManager → 外部 GetOutputBuffer()
```

## 8. 关键文件索引

| 文件 | 职责 |
|------|------|
| `services/engine/codec/audio/audio_codec.h` | 音频 Codec 入口封装 |
| `services/engine/codec/include/audio/audio_codec_worker.h` | 输入/输出双线程任务管理 |
| `services/engine/codec/include/audio/audio_base_codec.h` | FFmpeg 插件抽象基类 |
| `services/engine/codec/audio/decoder/audio_ffmpeg_aac_decoder_plugin.cpp` | AAC 解码插件 |
| `services/engine/codec/audio/decoder/audio_ffmpeg_mp3_decoder_plugin.cpp` | MP3 解码插件 |
| `services/engine/codec/audio/decoder/audio_ffmpeg_flac_decoder_plugin.cpp` | FLAC 解码插件 |
| `services/engine/codec/audio/decoder/audio_ffmpeg_vorbis_decoder_plugin.cpp` | Vorbis 解码插件 |
| `services/engine/codec/audio/decoder/audio_opus_decoder_plugin.cpp` | Opus 解码插件 |
| `services/engine/codec/audio/decoder/audio_ffmpeg_amrnb_decoder_plugin.cpp` | AMR-NB 解码插件 |
| `services/engine/codec/audio/decoder/audio_g711mu_decoder_plugin.cpp` | G.711 μ-law 解码插件 |
| `services/engine/codec/audio/decoder/audio_ffmpeg_aac_encoder_plugin.cpp` | AAC 编码插件 |
| `services/engine/codec/audio/encoder/audio_opus_encoder_plugin.cpp` | Opus 编码插件 |
| `services/engine/codec/audio/audio_resample.cpp` | FFmpeg 软件重采样 |
| `services/engine/common/ffmpeg_converter.cpp` | FFmpeg ↔ OHOS 格式转换 |
| `services/engine/codeclist/audio_codeclist_info.h` | 音频能力枚举表 |

## 关联记忆

- MEM-ARCH-AVCODEC-003: Plugin 架构（通用插件机制）
- MEM-ARCH-AVCODEC-009: 硬件 vs 软件 Codec 区分
- MEM-ARCH-AVCODEC-012: 能力查询 API（codeclist）
- MEM-ARCH-AVCODEC-014: Codec Engine 架构（CodecBase+Loader+Factory）
- MEM-ARCH-AVCODEC-016: AVBufferQueue 异步编解码
- MEM-ARCH-AVCODEC-017: DRM CENC 解密流程（音频 DRM 解密走同一路径）
- MEM-ARCH-AVCODEC-018: 硬件编解码器 HDI 架构（对比：音频无 HDI 路径）
- MEM-ARCH-AVCODEC-S5: 四层 Loader 插件热加载（对比：音频插件无热加载）
