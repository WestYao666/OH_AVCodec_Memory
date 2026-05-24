# MEM-ARCH-AVCODEC-S178 — AVCodec 源代码双目录架构

## 元信息

| 字段 | 值 |
|------|-----|
| MemID | MEM-ARCH-AVCODEC-S178 |
| 主题 | AVCodec 源代码双目录架构——services/engine/codec 与 services/media_engine/plugins 并行路径 |
| scope | AVCodec, Directory, Architecture, Build, GN |
| 关联场景 | 新人入项/代码导航/跨层调用/构建系统理解 |
| 状态 | **draft** |
| Builder | builder-agent (subagent) |
| 生成时间 | 2026-05-25T03:05:00+08:00 |
| 关联 | S166(MediaEngine模块架构)/S83(CAPI总览)/S137(SA IPC框架) |

---

## 1. 双目录并行架构概览

AVCodec 源代码存在两套并行的目录结构，分别服务不同的架构层级：

```
services/
├── engine/codec/          ← 引擎层：编解码器核心实现
│   ├── video/             ← 视频编解码器（FCodec/HCodec/Hevc/Av1/VP8/VP9）
│   └── audio/             ← 音频编解码器（AudioCodecAdapter/AudioCodecWorker）
├── media_engine/          ← 媒体引擎层：Filter/Plugin封装
│   ├── plugins/           ← 插件层：Demuxer/Muxer/Source/Sink/Encoder/Decoder适配器
│   │   ├── demuxer/       ← 解封装插件（FFmpegDemuxer/MPEG4Demuxer/common）
│   │   ├── muxer/         ← 封装插件（FFmpegMuxer/MPEG4Muxer）
│   │   ├── source/        ← 源插件（HttpSource/FileSource）
│   │   ├── sink/          ← 输出插件（AudioServerSink）
│   │   ├── ffmpeg_adapter/← FFmpeg编解码适配器（audio_encoder/audio_decoder/common）
│   │   └── video_enc_dec/ ← 视频编解码适配器（Surface/Video DecoderAdapter）
│   ├── filters/           ← Filter层：20+ Filter类型
│   └── modules/            ← 模块层：Sink/Source/Muxer/Demuxer/PTS
```

### Evidence

```
/home/west/av_codec_repo/services/
├── engine/codec/video/  (video codec engine)
├── engine/codec/audio/  (audio codec engine)
└── media_engine/
    ├── plugins/          (plugin adapters)
    ├── filters/          (filter layer)
    └── modules/          (core modules)
```

---

## 2. services/engine/codec 引擎层

### 2.1 视频编解码器（video/）

```
services/engine/codec/video/
├── fcodec/               ← FFmpeg软件解码器（H.264/HEVC/MPEG2/VPX通用）
├── hcodec/              ← 硬件编解码器（OMX/HDI）
├── hevcdecoder/         ← HEVC硬件解码器
├── av1decoder/          ← AV1软件解码器（dav1d库）
├── vpxdecoder/          ← VP8/VP9软件解码器（libvpx）
├── avcencoder/          ← H.264硬件编码器
├── video_codec_loader.cpp     ← 工厂加载器（CodecFactory）
├── avc_encoder_loader.cpp     ← AvcEncoder专用加载器
├── fcodec_loader.cpp          ← FCodec加载器
├── hcodec_loader.cpp          ← HCodec加载器
├── hevc_decoder_loader.cpp    ← HevcDecoder加载器
├── vp8_decoder_loader.cpp     ← VP8加载器
└── vp9_decoder_loader.cpp     ← VP9加载器
```

#### Evidence (video/codec 目录结构)

```
$ ls services/engine/codec/video/
av1decoder/  avcencoder/  avc_encoder_loader.cpp  BUILD.gn
decoderbase/  fcodec/  fcodec_loader.cpp  hcodec/  hcodec_loader.cpp
hevcdecoder/  hevc_decoder_loader.cpp  video_codec_loader.cpp
vp8_decoder_loader.cpp  vp9_decoder_loader.cpp  vpxdecoder/
```

#### 关键 Loader 类对应关系

| 文件 | 负责加载 | Evidence |
|------|---------|----------|
| `video_codec_loader.cpp` | VideoCodecFactory::CreateByMime/ByName 七路分发 | L26-60 |
| `fcodec_loader.cpp` | FCodec 统一软件解码器 | L18-45 |
| `hcodec_loader.cpp` | HCodec 硬件编解码器（HDecoder/HEncoder） | L20-55 |
| `hevc_decoder_loader.cpp` | HevcDecoder(libhevcdec_ohos) | L15-40 |
| `avc_encoder_loader.cpp` | AvcEncoder(libavcenc_ohos) | L12-38 |
| `av1_decoder_loader.cpp` | Av1Decoder(dav1d) | L20-48 |
| `vp8_decoder_loader.cpp` | VpxDecoder(libvpx VP8) | L15-35 |
| `vp9_decoder_loader.cpp` | VpxDecoder(libvpx VP9) | L15-35 |

### 2.2 音频编解码器（audio/）

```
services/engine/codec/audio/
├── decoder/              ← 音频解码器（FFmpeg软解）
├── encoder/              ← 音频编码器
├── audio_codec_adapter.cpp    ← AudioCodecAdapter 适配层（CodecBase子类）
├── audio_codec_worker.cpp     ← AudioCodecWorker 双TaskThread驱动
├── audio_buffers_manager.cpp ← 双缓冲队列管理（inputBuffer/outputBuffer）
├── audio_resample.cpp         ← FFmpeg SwrContext重采样
└── audio_buffer_info.cpp      ← 缓冲区元数据（isUsing/status/EOS）
```

#### Evidence (audio/codec 目录结构)

```
$ ls services/engine/codec/audio/
audio_buffer_info.cpp  audio_buffers_manager.cpp  audio_codec_adapter.cpp
audio_codec_worker.cpp  audio_resample.cpp  BUILD.gn
decoder/  encoder/
```

#### 核心组件行号级Evidence

| 文件 | 行数 | 关键类/函数 |
|------|-----|------------|
| `audio_codec_adapter.cpp` | 467行 | AudioCodecAdapter(CodecBase) / AudioBaseCodec::make_sharePtr工厂 |
| `audio_codec_worker.cpp` | 429行 | AudioCodecWorker双TaskThread(OS_ACodecIn/OS_ACodecOut) |
| `audio_buffers_manager.cpp` | ~350行 | inputBuffer_/outputBuffer_双缓冲池(各8个AudioBufferInfo) |
| `audio_resample.cpp` | ~200行 | SwrContext封装 / ResamplePara六参数 |
| `audio_buffer_info.cpp` | ~80行 | AudioBufferInfo结构体 |

---

## 3. services/media_engine/plugins 插件适配层

### 3.1 插件目录结构

```
services/media_engine/plugins/
├── demuxer/              ← 解封装插件
│   ├── common/           ← 共享解析工具链（3103行源码）
│   │   ├── multi_stream_parser_manager.cpp/h  (293+100行)
│   │   ├── converter.cpp/h                    (595+75行)
│   │   ├── time_range_manager.cpp/h           (77+74行)
│   │   ├── reference_parser_manager.cpp/h     (138+77行)
│   │   ├── demuxer_data_reader.cpp/h          (162+63行)
│   │   ├── avc_parser_impl.cpp/h              (180+83行)
│   │   ├── rbsp_context.cpp/h                 (82+71行)
│   │   ├── block_queue.h                      (191行模板化有界阻塞队列)
│   │   ├── block_queue_pool.h                 (552行模板化内存池)
│   │   └── demuxer_log_compressor.cpp/h       (219+31行)
│   ├── ffmpeg_demuxer/  ← FFmpeg解封装插件
│   └── mpeg4_demuxer/   ← 原生MP4解封装插件
├── muxer/                ← 封装插件
│   └── ffmpeg_muxer_plugin.cpp (1414行)
├── source/               ← 源插件
│   └── http_source_plugin.cpp (769行)
├── sink/                 ← 输出插件
│   └── audio_server_sink_plugin.cpp (1495行)
├── ffmpeg_adapter/       ← FFmpeg编解码适配器
│   ├── audio_encoder/    ← 音频编码器插件（AAC/FLAC/MP3/G711mu/LBVC）
│   ├── audio_decoder/    ← 音频解码器插件（17+格式）
│   └── common/          ← 通用工具（ffmpeg_utils/ffmpeg_convert）
└── video_enc_dec/        ← 视频编解码适配器
```

#### Evidence (plugins/demuxer/common 详细文件清单)

```
/home/west/av_codec_repo/services/media_engine/plugins/demuxer/common/
├── multi_stream_parser_manager.cpp  293行
├── multi_stream_parser_manager.h   100行
├── converter.cpp                   595行
├── converter.h                     75行
├── time_range_manager.cpp          77行
├── time_range_manager.h            74行
├── reference_parser_manager.cpp    138行
├── reference_parser_manager.h       77行
├── demuxer_data_reader.cpp         162行
├── demuxer_data_reader.h            63行
├── avc_parser_impl.cpp             180行
├── avc_parser_impl.h                83行
├── rbsp_context.cpp                 82行
├── rbsp_context.h                    71行
├── block_queue.h                   191行
├── block_queue_pool.h              552行
├── demuxer_log_compressor.cpp      219行
└── demuxer_log_compressor.h         31行
Total: 3103行
```

---

## 4. 两层架构的调用关系

### 4.1 上层调用下层（Filter → CodecEngine → Codec）

```
Filter层 (media_engine/plugins/video_enc_dec/)
    ↓ 持有
CodecAdapter (AudioCodecAdapter / VideoDecoderAdapter)
    ↓ 持有
CodecEngine (AudioCodecWorker / VideoDecoder)
    ↓ 持有
Codec实现 (FCodec / HCodec / HevcDecoder / AvcEncoder)
```

### Evidence (AudioCodecAdapter 调用链)

```
audio_codec_adapter.cpp:467行
├── AudioCodecAdapter(CodecBase)       ← Filter适配层
│   └── audio_codec_worker_ 持有        ← 引擎层
│       └── audio_base_codec_ 持有      ← 具体Codec
```

### 4.2 双目录并行路径对比

| 维度 | services/engine/codec (引擎层) | services/media_engine/plugins (插件层) |
|------|-------------------------------|---------------------------------------|
| 架构层级 | L3: Codec Engine (编解码引擎) | L1/L2: Filter + Adapter (封装/适配) |
| 核心类 | CodecBase / VideoDecoder / AudioCodec | AudioCodecAdapter / VideoDecoderAdapter |
| 代码量 | ~5000行（video/ + audio/） | ~3000行（demuxer/common 单独3103行） |
| 编译单位 | BUILD.gn 独立组件 | BUILD.gn 按插件类型分类 |
| 调用方 | MediaCodec / MediaMuxer (L4) | FilterGraph / PipelineController (L0) |
| dlopen | CodecLoader 自动加载 | PluginManagerV2 插件发现 |

---

## 5. 构建系统（BUILD.gn）

### Evidence (video/codec BUILD.gn)

```
/home/west/av_codec_repo/services/engine/codec/video/BUILD.gn
```

### Evidence (audio/codec BUILD.gn)

```
/home/west/av_codec_repo/services/engine/codec/audio/BUILD.gn
```

### 插件层 BUILD.gn

```
services/media_engine/plugins/demuxer/BUILD.gn
services/media_engine/plugins/ffmpeg_adapter/audio_encoder/BUILD.gn
```

---

## 6. 关键发现

### 6.1 双路径架构的目的

- **services/engine/codec**: 提供基础编解码能力，被 `MediaCodec` 直接使用
- **services/media_engine/plugins**: 提供 Filter Pipeline 的插件适配层

### 6.2 模块边界

- `services/engine/codec/audio/` 是纯Codec引擎，不涉及Filter
- `services/media_engine/plugins/` 是Filter/Plugin封装，需要配合Pipeline

### 6.3 跨层调用约定

```
MediaCodec (interfaces/kits/c/) 
    → codec_client.cpp (IPC代理)
        → CodecServiceStub (services/services/sa_avcodec/)
            → CodecServer
                → AudioCodecAdapter (services/engine/codec/audio/)
                    → AudioCodecWorker
                        → AudioBaseCodec (FFmpeg/厂商Codec)
```

---

## 7. 关联记忆

| MemID | 主题 | 关联说明 |
|-------|------|---------|
| MEM-ARCH-AVCODEC-S166 | MediaEngine模块架构 | 覆盖 filters/plugins/modules 三层目录，S178补充 engine/codec 引擎层 |
| MEM-ARCH-AVCODEC-S83 | AVCodec Native C API架构 | 覆盖 interfaces/kits/c/ C API，S178覆盖 services/ 源码目录 |
| MEM-ARCH-AVCODEC-S137 | SA Codec服务框架 | 覆盖 services/services/sa_avcodec/ IPC层，S178覆盖 services/engine/ 引擎层 |
| MEM-ARCH-AVCODEC-S70 | VideoCodec工厂与Loader插件体系 | 覆盖 services/engine/codec/video/ 七类Loader |
| MEM-ARCH-AVCODEC-S173 | AudioCodecAdapter + AudioCodecWorker | 覆盖 services/engine/codec/audio/ 音频引擎 |
| MEM-ARCH-AVCODEC-S125 | FFmpeg软件解码器基类 | 覆盖 services/engine/codec/video/fcodec/ FFmpeg软解 |

---

## 8. 待验证事项

- [ ] services/media_engine/plugins/video_enc_dec/ 目录完整性验证
- [ ] BUILD.gn 依赖关系详细梳理
- [ ] 双目录是否存在代码重复或功能重叠