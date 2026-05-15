# MEM-ARCH-AVCODEC-S158

## FFmpeg 音频编码器插件体系——FFmpegBaseEncoder 基类 + 五子插件架构

| 字段 | 值 |
|------|------|
| mem_id | MEM-ARCH-AVCODEC-S158 |
| 标题 | FFmpeg 音频编码器插件体系 |
| 模块 | services/media_engine/plugins/ffmpeg_adapter/audio_encoder |
| 文件路径 | ffmpeg_base_encoder.cpp / ffmpeg_encoder_plugin.cpp / aac / flac / g711mu / lbvc / mp3 |
| 状态 | draft |
| 关联记忆 | S125(FFmpeg Decoder) / S130(FFmpeg Adapter Common) / S60(AAC编解码) / S50(AudioResample) / S8(FFmpeg Audio) |

---

## 一、架构总览

FFmpeg 音频编码器采用三层架构：
- **Layer 1**: FFmpegBaseEncoder (396行) —— 引擎基类，封装 libavcodec 编码管线
- **Layer 2**: FFmpegEncoderPlugin (85行) —— 插件注册层，AutoRegisterFilter 静态注册
- **Layer 3**: 五路编码器子插件 —— AAC / FLAC / MP3 / G711mu / LBVC

```
FFmpegEncoderPlugin (85行)
  ├── ffmpeg_aac_encoder_plugin.cpp (902行)    ← AAC编码器
  ├── ffmpeg_flac_encoder_plugin.cpp (252行)   ← FLAC编码器
  ├── audio_g711mu_encoder_plugin.cpp          ← G.711 mu-law
  ├── audio_lbvc_encoder_plugin.cpp             ← LBVC
  └── ffmpeg_mp3_encoder_plugin.cpp            ← MP3
  └── FFmpegBaseEncoder (396行)                 ← 基类（被组合）
```

---

## 二、FFmpegBaseEncoder 引擎基类

**文件**: `services/media_engine/plugins/ffmpeg_adapter/audio_encoder/ffmpeg_base_encoder.cpp` (396行)  
**头文件**: `ffmpeg_base_encoder.h` (94行)

### 2.1 核心接口

```cpp
// ffmpeg_base_encoder.h L25-35
class FFmpegBaseEncoder : public AudioBaseEncoder {
public:
    virtual ~FFmpegBaseEncoder() = default;
    int32_t Init(const AudioEncInfo& audioEncInfo) override;
    int32_t Process(Message&& msg) override;
    int32_t Flush() override;
    int32_t Release() override;
    // ... 等 AudioBaseEncoder 接口
};
```

### 2.2 libavcodec 编码管线

```cpp
// ffmpeg_base_encoder.cpp L120-180（推测）
int32_t FFmpegBaseEncoder::Init(const AudioEncInfo& audioEncInfo) {
    // 1. avcodec_find_encoder_by_name() / avcodec_find_encoder()
    // 2. avcodec_alloc_context3()
    // 3. 设置 codecContext 参数（bitrate/sampleRate/channelLayout）
    // 4. avcodec_open2()
    return AVCODEC_OK;
}
```

```cpp
// ffmpeg_base_encoder.cpp L200-250（推测）
int32_t FFmpegBaseEncoder::Process(Message&& msg) {
    // avcodec_send_frame(codecContext, frame)
    // avcodec_receive_packet(codecContext, AVPacket)
    return AVCODEC_OK;
}
```

### 2.3 与 FFmpegBaseDecoder (S125) 对比

| 维度 | FFmpegBaseEncoder | FFmpegBaseDecoder |
|------|-------------------|-------------------|
| 核心函数 | avcodec_send_frame | avcodec_send_packet |
| 输出函数 | avcodec_receive_packet | avcodec_receive_frame |
| 输入源 | PCM 帧 | AVPacket 码流 |
| 工具函数 | AudioResample (SwrContext) | AudioConvert |

---

## 三、FFmpegEncoderPlugin 插件注册层

**文件**: `services/media_engine/plugins/ffmpeg_adapter/audio_encoder/ffmpeg_encoder_plugin.cpp` (85行)  
**头文件**: `ffmpeg_encoder_plugin.h` (26行)

### 3.1 AutoRegisterFilter 静态注册

```cpp
// ffmpeg_encoder_plugin.cpp L20-30（推测）
namespace {
    AutoRegisterFilter<FFmpegEncoderPlugin> g_register("builtin.audioencoder.ffmpeg");
}
```

### 3.2 CreateAudioEncoder 工厂

```cpp
// ffmpeg_encoder_plugin.cpp L50-80（推测）
std::shared_ptr<AudioBaseEncoder> FFmpegEncoderPlugin::CreateAudioEncoder(
    const AudioEncInfo& audioEncInfo, AVCodecCategory category) {
    auto encoder = std::make_shared<FFmpegBaseEncoder>();
    encoder->Init(audioEncInfo);
    return encoder;
}
```

---

## 四、AAC 编码器——ffmpeg_aac_encoder_plugin.cpp (902行)

**文件**: `services/media_engine/plugins/ffmpeg_adapter/audio_encoder/aac/ffmpeg_aac_encoder_plugin.cpp`

### 4.1 自实现 AudioFifo + Resample

AAC 编码器**不依赖 FFmpegBaseEncoder**，完全自实现：

```cpp
// ffmpeg_aac_encoder_plugin.cpp L37-50
static const int ADTS_HEADER_SIZE = 7;
static const int INPUT_SAMPLE_PER_FRAME = 1024;
static const int MAX_AAC_HEADER_SIZE = 64;
```

```cpp
// ffmpeg_aac_encoder_plugin.cpp L100-150（推测）
int32_t FFmpegAacEncoderPlugin::Init(const AudioEncInfo& audioEncInfo) {
    // 1. 创建 SwrContext (AudioResample)
    swrContext_ = SwrContext::CreateSwrContext();
    // 2. avcodec_find_encoder_by_name("aac")
    // 3. avcodec_alloc_context3() + avcodec_open2()
    // 4. av_audio_fifo_alloc()
}
```

### 4.2 ADTS 头构造

```cpp
// ffmpeg_aac_encoder_plugin.cpp L200-280（推测）
void FFmpegAacEncoderPlugin::WriteAdtsHeader(uint8_t* adtsHeader, int aacProfile, int sampleRate, int channelCount) {
    // ADTS L102-124: GetAdtsHeader()
    // 0xFF (syncword) + 0xF1 (mpeg4 container)
    // profile[1:0] + samplingFrequencyIndex[1:0] + privateBit[1:0] + channelConfiguration[1:0]
}
```

### 4.3 编码管线

```cpp
// ffmpeg_aac_encoder_plugin.cpp L600-700（推测）
int32_t FFmpegAacEncoderPlugin::EncodeFrame(const uint8_t* inputBuffer, size_t inputLength,
                                             uint8_t* outputBuffer, size_t& outputLength) {
    // 1. SwrContext 转换采样率/通道
    // 2. av_audio_fifo_write() 写入 FIFO
    // 3. avcodec_send_frame(codecContext, frame)
    // 4. avcodec_receive_packet(codecContext, packet)
    // 5. 写 ADTS 头
}
```

---

## 五、FLAC 编码器——ffmpeg_flac_encoder_plugin.cpp (252行)

**文件**: `services/media_engine/plugins/ffmpeg_adapter/audio_encoder/flac/ffmpeg_flac_encoder_plugin.cpp`

### 5.1 组合 FFmpegBaseEncoder

```cpp
// ffmpeg_flac_encoder_plugin.cpp L30-50
class FFmpegFlacEncoderPlugin : public AudioBaseEncoder {
private:
    std::shared_ptr<FFmpegBaseEncoder> baseEncoder_;
    // ...
};
```

### 5.2 采样率/通道布局表

```cpp
// ffmpeg_flac_encoder_plugin.cpp L38-44
static const int SUPPORT_SAMPLE_RATE_MAP[] = {8000, 16000, 22050, 24000, 32000, 44100, 48000, 96000};
static const int SUPPORT_CHANNEL_LAYOUT_MAP[] = {AV_CH_MONO, AV_CH_STEREO};
```

### 5.3 InitContext

```cpp
// ffmpeg_flac_encoder_plugin.cpp L100-130
int32_t FFmpegFlacEncoderPlugin::Init(const AudioEncInfo& audioEncInfo) {
    baseEncoder_ = std::make_shared<FFmpegBaseEncoder>();
    baseEncoder_->Init(audioEncInfo);  // 内部调用 avcodec_find_encoder("flac")
}
```

---

## 六、其他编码器插件

### 6.1 G711mu

**文件**: `services/media_engine/plugins/ffmpeg_adapter/audio_encoder/g711mu/audio_g711mu_encoder_plugin.cpp`

- 无损 PCM μ-law 压缩（64kbps）
- 自实现（非 FFmpeg），类似 AAC 的自实现路径

### 6.2 LBVC

**文件**: `services/media_engine/plugins/ffmpeg_adapter/audio_encoder/lbvc/audio_lbvc_encoder_plugin.cpp`

- Low Bitrate Voice Codec
- 自实现路径

### 6.3 MP3

**文件**: `services/media_engine/plugins/ffmpeg_adapter/audio_encoder/mp3/ffmpeg_mp3_encoder_plugin.cpp`

- 组合 FFmpegBaseEncoder
- avcodec_find_encoder("libmp3lame")

---

## 七、与 S125(FFmpeg Decoder) 对比矩阵

| 维度 | Encoder | Decoder |
|------|---------|---------|
| 基类 | FFmpegBaseEncoder (396行) | FFmpegBaseDecoder (605行) |
| libavcodec API | avcodec_send_frame / receive_packet | avcodec_send_packet / receive_frame |
| AAC | 自实现 AAC (902行) | FFmpegDecoderPlugin |
| FLAC | 组合 FFmpegBaseEncoder | FFmpegDecoderPlugin |
| 自实现程度 | AAC 完全自实现 | 解码器统一基类 |
| Resample | 内置 SwrContext | 独立 AudioConvert (247行) |

---

## 八、关联记忆

| 记忆 | 关系 |
|------|------|
| S125 | FFmpegDecoder 对应架构，编解码对称 |
| S130 | 共享 FFmpegAdapter Common (ffmpeg_convert / ffmpeg_utils) |
| S50 | AudioResample (SwrContext) 在 AAC/FLAC 中使用 |
| S60 | AAC 编解码完整链路（Encoder AAC + Decoder AAC） |
| S8 | FFmpeg 音频插件总览 |
| S132 | 同主题，S132 为已提交审批版本（FFmpegBaseEncoder + AAC/FLAC） |

---

## 九、Evidence 列表

| # | 文件 | 行号 | 说明 |
|---|------|------|------|
| 1 | ffmpeg_base_encoder.cpp | 396 | 编码器引擎基类 |
| 2 | ffmpeg_base_encoder.h | 94 | 头文件定义 |
| 3 | ffmpeg_encoder_plugin.cpp | 85 | 插件注册层 |
| 4 | ffmpeg_aac_encoder_plugin.cpp | 902 | AAC 自实现编码器（ADTS 头构造） |
| 5 | ffmpeg_flac_encoder_plugin.cpp | 252 | FLAC 组合编码器 |
| 6 | audio_g711mu_encoder_plugin.cpp | - | G.711 mu-law 编码器 |
| 7 | audio_lbvc_encoder_plugin.cpp | - | LBVC 编码器 |
| 8 | ffmpeg_mp3_encoder_plugin.cpp | - | MP3 组合编码器 |
| 9 | ffmpeg_aac_encoder_plugin.cpp L102-124 | - | GetAdtsHeader() ADTS 7字节头 |
| 10 | ffmpeg_flac_encoder_plugin.cpp L38-44 | - | 采样率/通道布局表 |