---
type: architecture
id: MEM-ARCH-AVCODEC-S131
title: "FFmpeg 音频编码器与封装修复器插件体系——FFmpegBaseEncoder / FFmpegEncoderPlugin / FfmpegMuxerPlugin 三层架构"
scope: [AVCodec, FFmpeg, AudioEncoder, MuxerPlugin, Plugin, libavcodec, avcodec_send_frame, avcodec_receive_packet, AAC, FLAC, MP3, G711mu, LBVC, aac, flac, mp3, g711mu, lbvc, FFmpegMuxerPlugin, FFmpegMuxerRegister, AutoRegisterFilter, Filter]
status: pending_approval
created_at: "2026-05-14T14:10:00+08:00"
created_by: builder-agent
关联主题: [S125(FFmpegDecoder基类), S60(AAC音频FFmpeg插件), S8(FFmpeg音频插件总览), S40(FFmpegMuxerPlugin总览), S130(FFmpegAdapterCommon工具链)]
source_repo: /home/west/av_codec_repo
source_root: services/media_engine/plugins/ffmpeg_adapter
evidence_version: local_mirror
---

# MEM-ARCH-AVCODEC-S131: FFmpeg 音频编码器与封装修复器插件体系

## 核心定位

`services/media_engine/plugins/ffmpeg_adapter/` 包含两个平行的 FFmpeg 插件子系统：

1. **音频编码器插件**：`audio_encoder/` 目录，FFmpegBaseEncoder 引擎 + 5 个格式子插件（AAC/FLAC/MP3/G711mu/LBVC）
2. **FFmpeg 封装修复器**：`muxer/` 目录，FFmpegMuxerPlugin + FFmpegMuxerRegister + flv_muxer/ + mpeg4_muxer/ 两个子封装修复器

这两个子系统与 `audio_decoder/`（S125）构成完整的 FFmpeg 编解码插件矩阵，与 `common/` 工具链（S130）共享 SwrContext/SwsContext 色域/通道布局转换能力。

---

## 一、音频编码器引擎：FFmpegBaseEncoder

**源码路径**: `services/media_engine/plugins/ffmpeg_adapter/audio_encoder/ffmpeg_base_encoder.cpp` (396行) + `ffmpeg_base_encoder.h` (94行)

### 1.1 类继承结构

```
FFmpegBaseEncoder : NoCopyable
├── avCodecContext_ : std::shared_ptr<AVCodecContext>   // FFmpeg codec 上下文
├── cachedFrame_    : std::shared_ptr<AVFrame>           // 输入帧缓存
├── avPacket_       : std::shared_ptr<AVPacket>           // 输出数据包
├── avMutext_       : std::mutex                         // 线程安全锁
├── prevPts_        : int64_t                            // 前一帧 PTS（编码时间戳）
├── maxInputSize_   : int32_t                            // 最大输入尺寸
├── codecContextValid_ : bool                            // codec 上下文是否有效
└── ProcessSendData / ProcessReceiveData / OpenContext  // 核心方法
```

### 1.2 核心方法（行号级）

```cpp
// ffmpeg_base_encoder.cpp

// line 27-30: 时间单位常量（与 FFmpegBaseDecoder 一致）
constexpr int32_t NS_PER_US = 1000;

// line 42-53: 构造函数（初始化成员列表）
FFmpegBaseEncoder::FFmpegBaseEncoder()
    : maxInputSize_(-1),
      avCodec_(nullptr),
      avCodecContext_(nullptr),
      cachedFrame_(nullptr),
      avPacket_(nullptr),
      prevPts_(0),
      codecContextValid_(false)
{ }

// line 72-86: ProcessSendData——输入数据写入（带线程安全锁）
Status FFmpegBaseEncoder::ProcessSendData(const std::shared_ptr<AVBuffer> &inputBuffer)
{
    auto memory = inputBuffer->memory_;
    if (memory == nullptr) {
        AVCODEC_LOGE("memory is nullptr");
        return Status::ERROR_INVALID_DATA;
    }
    if (memory->GetSize() <= 0 && !(inputBuffer->flag_ & BUFFER_FLAG_EOS)) {
        AVCODEC_LOGE("size is %{public}d, but flag is not 1 ", memory->GetSize());
        return Status::ERROR_INVALID_DATA;
    }
    Status ret;
    {
        std::lock_guard<std::mutex> lock(avMutext_);
        // ... 写入 avPacket_
    }
}
```

**对比 FFmpegBaseDecoder（S125）**：解码器使用 `avcodec_send_packet` → `avcodec_receive_frame`，编码器使用 `avcodec_send_frame` → `avcodec_receive_packet`（方向相反，函数对称）

---

## 二、FFmpegEncoderPlugin 音频编码器插件注册层

**源码路径**: `services/media_engine/plugins/ffmpeg_adapter/audio_encoder/ffmpeg_encoder_plugin.cpp` (85行) + `ffmpeg_encoder_plugin.h` (26行)

### 2.1 插件注册表（line 40-48）

```cpp
// ffmpeg_encoder_plugin.cpp line 40-48
std::vector<std::string_view> codecVec = {
    AVCodecCodecName::AUDIO_ENCODER_AAC_NAME,   // 0: aac
    AVCodecCodecName::AUDIO_ENCODER_FLAC_NAME,  // 1: flac
};

// SetDefinition 分发函数（line 50-85）
// case 0: AAC → FFmpegAACEncoderPlugin(name)
// case 1: FLAC → FFmpegFlacEncoderPlugin(name)
```

### 2.2 五路格式子插件（line 40-48 + 目录结构）

| 子目录 | 编码插件 | MIME 类型 | 说明 |
|--------|---------|-----------|------|
| `aac/` | FFmpegAACEncoderPlugin | AUDIO_AAC | AAC-LC / HE-AAC |
| `flac/` | FFmpegFlacEncoderPlugin | AUDIO_FLAC | FLAC 无损编码 |
| `mp3/` | (mp3 encoder plugin) | AUDIO_MP3 | MP3 编码 |
| `g711mu/` | (g711mu encoder plugin) | AUDIO_G711MU | G.711 μ-law |
| `lbvc/` | (lbvc encoder plugin) | AUDIO_LBVC | LBVC 编码 |

**与音频解码器对应**：解码器 22 个格式插件（S125），编码器 5 个格式插件（数量少因为音频编码场景相对少）

---

## 三、FFmpegMuxerPlugin 封装修复器插件

**源码路径**: `services/media_engine/plugins/ffmpeg_adapter/muxer/ffmpeg_muxer_plugin.cpp` + `ffmpeg_muxer_plugin.h`

### 3.1 封装修复器注册与初始化

```cpp
// ffmpeg_muxer_plugin.cpp line 37-38: LogTag
constexpr OHOS::HiviewDFX::HiLogLabel LABEL = {LOG_CORE, LOG_DOMAIN_MUXER, "FFmpegMuxerPlugin"};

// line 26: 支持的轨道引用类型（hint/cdsc/font/hind/vdep/vplx/subt/thmb/auxl/cdtg/aest）
const std::set<std::string> SUPPORTED_TRACK_REF_TYPE = {"hint", "cdsc", "font", ...};

// line 32-33: 地理坐标边界
constexpr float LATITUDE_MIN = -90.0f;
constexpr float LONGITUDE_MAX = 180.0f;
```

### 3.2 FFmpegMuxerRegister 注册器

```
ffmpeg_muxer_register.cpp/h     → 静态注册入口
flv_muxer/                      → FLV 容器封装修复器
mpeg4_muxer/                    → MP4/MOV 容器封装修复器
```

---

## 四、架构关联图

```
┌─────────────────────────────────────────────────────────┐
│  MediaEngine Pipeline                                    │
│  AudioEncoderFilter (S24/S36)                           │
│    └─► FFmpegEncoderPlugin (audio_encoder_plugin.cpp)    │
│          ├─► FFmpegAACEncoderPlugin   (aac/)             │
│          ├─► FFmpegFlacEncoderPlugin (flac/)             │
│          ├─► FFmpegMP3EncoderPlugin  (mp3/)             │
│          ├─► FFmpegG711muEncoderPlugin(g711mu/)         │
│          └─► FFmpegLBVCEncoderPlugin (lbvc/)            │
│                └─► FFmpegBaseEncoder (ffmpeg_base_encoder.cpp)  │
│                      ├─► avCodecContext_                  │
│                      ├─► avcodec_send_frame()             │
│                      └─► avcodec_receive_packet()         │
│                                                          │
│  MuxerFilter (S34)                                      │
│    └─► FFmpegMuxerPlugin (muxer/ffmpeg_muxer_plugin.cpp)  │
│          ├─► FFmpegMuxerRegister  (flv_muxer/)           │
│          └─► FFmpegMuxerRegister  (mpeg4_muxer/)         │
│                └─► libavformat (av_write_frame/av_interleaved_write_frame)  │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  FFmpeg Adapter Common (S130)                            │
│  ffmpeg_convert (Resample/SwsContext)                    │
│  ffmpeg_converter (ChannelLayout映射)                    │
│  ffmpeg_utils (Mime2CodecId/ColorSpace/FindNalStartCode) │
│  stream_parser_manager (HEVC流解析)                      │
└─────────────────────────────────────────────────────────┘
```

---

## 五、关键 evidence 汇总

| # | 文件 | 行号 | 内容 |
|---|------|------|------|
| 1 | ffmpeg_base_encoder.cpp | 42-53 | FFmpegBaseEncoder 构造函数（成员初始化） |
| 2 | ffmpeg_base_encoder.cpp | 72-86 | ProcessSendData 输入数据写入（avMutext_ 锁保护） |
| 3 | ffmpeg_encoder_plugin.cpp | 40-48 | codecVec 插件注册表（AAC/FLAC） |
| 4 | ffmpeg_encoder_plugin.cpp | 50-85 | SetDefinition 工厂分发（case 0→AAC/case 1→FLAC） |
| 5 | ffmpeg_muxer_plugin.cpp | 37-38 | LogTag 定义（LOG_DOMAIN_MUXER） |
| 6 | ffmpeg_muxer_plugin.cpp | 32-33 | 地理坐标边界常量（LATITUDE/LONGITUDE） |
| 7 | audio_encoder/ 目录 | 子目录 | aac/flac/mp3/g711mu/lbvc 五个编码器子插件 |

---

## 六、关联记忆

- **S125**: FFmpegBaseDecoder + FfmpegDecoderPlugin + 22 格式子插件（解码器侧镜像）
- **S60**: AAC 音频 FFmpeg 插件（ADTS 封装、Resample 四通道）
- **S8**: FFmpeg 音频编解码插件总览（CodecPlugin CRTP 注册机制）
- **S130**: FFmpeg Adapter Common 工具链（Resample/ColorSpace/ChannelLayout 共享）
- **S40**: FFmpegMuxerPlugin 总览（封装修复器全局视图）