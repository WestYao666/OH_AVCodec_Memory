---
type: architecture
id: MEM-ARCH-AVCODEC-S166
status: draft
topic: MediaEngine 模块架构——filters/plugins/modules 三层目录结构与Filter组件体系
scope: AVCodec, MediaEngine, Filter, Plugin, Module, Directory, Architecture
assoc_scenes: 新需求开发, 问题定位, 新人入项, 代码导航
builder: builder-agent
created: 2026-05-20T18:15 Asia/Shanghai
evidence_source: local_mirror /home/west/av_codec_repo
---

# MEM-ARCH-AVCODEC-S166 — MediaEngine 模块架构

## Metadata

| 字段 | 内容 |
|------|------|
| ID | MEM-ARCH-AVCODEC-S166 |
| 标题 | MediaEngine 模块架构——filters/plugins/modules 三层目录结构与Filter组件体系 |
| 状态 | draft |
| 创建时间 | 2026-05-20T18:15 Asia/Shanghai |
| Builder | builder-agent |
| 标签 | AVCodec, MediaEngine, Filter, Plugin, Module, Directory, Architecture |
| 关联主题 | S14(FilterChain), S41(DemuxerFilter), S34(MuxerFilter), S22(MediaSyncManager), S112(PipelineController) |

---

## 1. 架构概述

MediaEngine 是 AVCodec 中承接 Filter Pipeline 数据处理的核心模块，位于 `services/media_engine/` 目录下，采用 filters / plugins / modules 三层目录结构组织代码：

- **filters/** — Filter 组件实现层，承载具体音视频 Filter 的业务逻辑（采集/解码/编码/渲染/封装等）
- **plugins/** — 插件抽象层，定义 Filter/Muxer/Demuxer 的插件注册机制与厂商实现
- **modules/** — 通用功能模块层，提供 Sink（渲染输出）、Source（数据源）、Demuxer/Muxer 引擎、音频重采样、PTS 转换等可复用组件

```
services/media_engine/
├── filters/          # Filter 组件实现（~20个子目录）
│   ├── audio_capture/
│   ├── audio_data_source/
│   ├── audio_decoder/
│   ├── audio_encoder/
│   ├── demuxer/
│   ├── muxer/
│   ├── video_capture/
│   ├── video_decoder/
│   ├── video_encoder/
│   ├── video_render/
│   ├── subtitle_sink/
│   ├── surface_decoder/
│   ├── surface_encoder/
│   ├── transcoder/
│   └── ...
├── plugins/         # 插件抽象与厂商实现
│   ├── ffmpeg_adapter/
│   │   ├── common/
│   │   ├── audio_encoder/
│   │   ├── audio_decoder/
│   │   └── muxer/
│   └── ...
└── modules/          # 通用功能模块
    ├── sink/         # 三路 Sink（Video/Audio/Subtitle）
    ├── source/       # 数据源（协议路由/音频采集）
    ├── demuxer/      # 解封装引擎
    ├── muxer/        # 封装引擎
    └── pts_index_conversion/  # PTS ↔ Index 双向转换
```

三层结构的协作模式：
- **filters/** 中的 Filter（如 DemuxerFilter / MuxerFilter）调用 **modules/** 中的引擎（MediaDemuxer / MediaMuxer）
- **modules/** 中的引擎通过 **plugins/** 中的插件（FFmpegDemuxerPlugin / MPEG4DemuxerPlugin / FFmpegMuxerPlugin）扩展格式支持
- **plugins/** 中的适配器（FFmpeg Adapter）调用 FFmpeg libavcodec/libavformat 库

---

## 2. filters/ 目录详解

filters/ 目录包含约 20 个子目录，每个对应一种 Filter 类型，按功能分为以下类别：

### 2.1 数据源Filter（Source Filters）

| Filter | 目录 | 注册名 | 功能 |
|--------|------|--------|------|
| AudioCaptureFilter | audio_capture/ | builtin.recorder.audiocapture | 设备音频实时采集，AudioCaptureModule 驱动 |
| AudioDataSourceFilter | audio_data_source/ | builtin.recorder.audiodatasource | 外部音频数据源注入，无设备依赖 |
| VideoCaptureFilter | video_capture/ | builtin.recorder.videocapture | Surface 模式视频采集，ConsumerSurfaceBufferListener 桥接 |
| HTTPStreamSource | （Source模块内） | builtin.source.http | HTTP/HTTPS 流媒体源，HttpSourcePlugin |

### 2.2 解码Filter（Decoder Filters）

| Filter | 目录 | 注册名 | 功能 |
|--------|------|--------|------|
| AudioDecoderFilter | audio_decoder/ | builtin.player.audiodecoder | 音频解码Filter封装，AudioDecoderAdapter三层调用 |
| SurfaceDecoderFilter | surface_decoder/ | builtin.player.surfacedecoder | 视频解码Surface模式，SurfaceDecoderAdapter三层调用 |
| DecoderSurfaceFilter | video_decoder/ | builtin.player.videodecoder | FILTERTYPE_VDEC，VideoDecoderAdapter+VideoSink+PostProcessor三组件 |

### 2.3 编码Filter（Encoder Filters）

| Filter | 目录 | 注册名 | 功能 |
|--------|------|--------|------|
| AudioEncoderFilter | audio_encoder/ | builtin.recorder.audioencoder | 音频编码Filter，SetTranscoderMode转码模式支持 |
| SurfaceEncoderFilter | video_encoder/ | builtin.recorder.videoencoder | 视频编码Surface模式，FILTERTYPE_VENC，ProcessStateCode五状态机 |
| VideoEncoderFilter | video_encoder/ | builtin.recorder.videoencoder | 等同SurfaceEncoderFilter，Filter层封装 |

### 2.4 渲染Filter（Output Filters）

| Filter | 目录 | 注册名 | 功能 |
|--------|------|--------|------|
| VideoRenderFilter | video_render/ | builtin.player.videorender | 视频渲染输出，vsync驱动帧送达，HDR→SDR色域转换 |
| AudioSinkFilter | （modules/sink/内） | builtin.player.audiosink | 音频播放输出，AudioSink+MediaSynchronousSink+AudioSinkPlugin三层 |
| SubtitleSinkFilter | subtitle_sink/ | builtin.player.subtitlesink | 字幕渲染，SubtitleBufferState三状态(WAIT/SHOW/DROP) |

### 2.5 解封装/封装Filter（Demuxer/Muxer Filters）

| Filter | 目录 | 注册名 | 功能 |
|--------|------|--------|------|
| DemuxerFilter | demuxer/ | builtin.player.demuxer | 解封装Filter，MediaDemuxer核心引擎，多轨AVBufferQueue |
| MuxerFilter | muxer/ | builtin.recorder.muxer | 封装Filter，录制管线输出终点，preFilterCount_多轨协调 |

### 2.6 处理Filter（Processing Filters）

| Filter | 目录 | 注册名 | 功能 |
|--------|------|--------|------|
| VideoResizeFilter | video_resize/ | builtin.transcoder.videoresize | 转码增强，FILTERTYPE_VIDRESIZE，VPE DetailEnhancer |
| WaterMarkFilter | watermark/ | builtin.transcoder.watermark | OpenGL ES GPU水印叠加，FBO渲染管线 |
| SeiParserFilter | seiparser/ | builtin.player.seiparser | SEI信息解析，AnnexB NALU双格式，AVC/HEVC双解析器 |
| MetaDataFilter | metadata/ | builtin.player.timedmetadata | 时域元数据注入，TIMED_METADATA，SetInputMetaSurface |
| PreProcessorFilter | preprocessor/ | builtin.encoder.preprocessor | 编码前处理，Crop/Downsample/DropFrame三功能编排 |

### 2.7 转码专用Filter

| Filter | 目录 | 注册名 | 功能 |
|--------|------|--------|------|
| TranscoderFilter | transcoder/ | builtin.transcoder | 转码Pipeline入口，Encode→Decode桥接 |

### 2.8 Filter 基类架构

所有 Filter 继承自 `FilterBase` 基类，FilterBase 定义七生命周期：
- `DoPrepare` — 准备资源
- `DoStart` — 启动处理
- `DoStop` — 停止处理
- `DoPause` — 暂停处理
- `DoFreeze` — 冻结状态
- `DoUnFreeze` — 解冻恢复
- `DoResume` — 恢复运行

Filter 之间通过 `FilterLinkCallback` 链接：
1. `LinkNext` — 建立链接
2. `OnLinked` — 链接完成回调
3. `OnLinkedResult` — 链接结果回调

AutoRegisterFilter 实现插件静态注册：`REGISTER_FILTER(FilterType, FilterName, CreateFunc)`

---

## 3. plugins/ 目录详解

plugins/ 目录包含插件抽象层和厂商实现：

### 3.1 FFmpeg Adapter

路径：`plugins/ffmpeg_adapter/`

```
ffmpeg_adapter/
├── common/           # 通用工具链（ffmpeg_utils, ffmpeg_convert, ffmpeg_converter, stream_parser_manager）
├── audio_encoder/    # AAC/FLAC/MP3/G711mu/LBVC 五子插件
├── audio_decoder/    # 17+ 子插件（aac/ac3/mp3/flac/vorbis/wma/dts/...）
└── muxer/            # FFmpegMuxerPlugin / MPEG4MuxerPlugin / FLVMuxerPlugin
```

关键证据：
- `ffmpeg_base_encoder.cpp:396行` — 编码器基类（avcodec_send_frame/avcodec_receive_packet）
- `ffmpeg_base_decoder.cpp:605行` — 解码器基类
- `ffmpeg_aac_encoder_plugin.cpp:902行` — 自实现 AVAudioFifo + ADTS 7字节头
- `ffmpeg_muxer_plugin.cpp:1414行` — FFmpeg 封装插件

### 3.2 插件注册机制

CodecPlugin 插件通过 CRTP 模板静态注册：
```cpp
REGISTER_MUXER_PLUGIN(FFmpegMuxerPlugin, "mp4", CreateFunc);
```

PluginManagerV2 管理插件生命周期：
- `CreatePluginByMime(PluginType, mime)` — 按 MIME 类型创建
- `GetPluginByRank(PluginType, rank)` — 按优先级获取

---

## 4. modules/ 目录详解

modules/ 包含可复用的功能模块：

### 4.1 sink/ — 三路渲染输出引擎

| 模块 | 文件 | 核心类 | 功能 |
|------|------|--------|------|
| VideoSink | video_sink.cpp:462行 | VideoSink | 视频渲染同步，DoSyncWrite渲染决策，前4帧强制渲染 |
| AudioSink | audio_sink.cpp:1793行 | AudioSink | 音频播放输出，AudioVivid 80ms固定延迟补偿 |
| SubtitleSink | subtitle_sink.cpp:517行 | SubtitleSink | 字幕渲染，RenderLoop独立线程，三状态机 |

三路 Sink 均继承 `MediaSynchronousSink`，与 MediaSyncManager 协作：
- VIDEO_SINK = 0（最高优先级，时钟锚点供应方）
- AUDIO_SINK = 2
- SUBTITLE_SINK = 8

### 4.2 source/ — 数据源模块

| 模块 | 文件 | 功能 |
|------|------|------|
| Source | source.cpp:715行 | 协议路由（http/https/file/fd/stream），FindPlugin→PluginManagerV2创建 |
| AudioCaptureModule | audio_capture_module.cpp:509行 | 设备音频实时采集，Read/Poll双模式，GetMaxAmplitude峰值检测 |

### 4.3 demuxer/ — 解封装引擎

| 模块 | 文件 | 功能 |
|------|------|------|
| MediaDemuxer | media_demuxer.cpp:6012行 | 解封装核心引擎，ReadLoop/SampleConsumerLoop双TaskThread |
| StreamDemuxer | stream_demuxer.cpp:492行 | 流式读取，PullData分片缓存，ReadRetry重试机制 |
| DemuxerPluginManager | demuxer_plugin_manager.cpp:1159行 | 插件管理，Track路由，三层映射表(StreamID→TrackID→InnerTrackIndex) |
| TypeFinder | type_finder.cpp:216行 | 媒体类型探测，PeekRange嗅探(DEFAULT_SNIFF_SIZE=4096*4) |

### 4.4 muxer/ — 封装引擎

| 模块 | 文件 | 功能 |
|------|------|------|
| MediaMuxer | media_muxer.cpp:571行 | 封装核心，Track管理，四状态机，AVBufferQueue异步写入 |
| FFmpegMuxerPlugin | ffmpeg_muxer_plugin.cpp:1414行 | FFmpeg九格式封装 |
| MPEG4MuxerPlugin | mpeg4_muxer_plugin.cpp:574行 | 原生MP4 Box手写实现 |

### 4.5 pts_index_conversion/ — PTS 转换模块

| 模块 | 文件 | 功能 |
|------|------|------|
| TimeAndIndexConversion | pts_and_index_conversion.cpp:640行 | MP4/MOV/AVI/MPEGPS PTS↔Index双向转换，STTS/CTTS双表查表 |

---

## 5. 三层协作数据流

完整播放 Pipeline 示例：

```
Source (source.cpp:715)
  → DemuxerFilter (demuxer/)
    → MediaDemuxer (modules/demuxer/)
      → FFmpegDemuxerPlugin (plugins/ffmpeg_adapter/muxer/)
        OR MPEG4DemuxerPlugin
  → AudioDecoderFilter (audio_decoder/)
    → AudioCodecEngine
  → VideoDecoderFilter (video_decoder/)
    → VideoDecoderAdapter
      → HDecoder (硬件) / FCodec (FFmpeg软件)
  → VideoRenderFilter (video_render/)
    → VideoSink (modules/sink/)
      → MediaSyncManager (IMediaSynchronizer)
  → AudioSinkFilter (modules/sink/)
    → AudioSink
  → SubtitleSinkFilter (subtitle_sink/)
    → SubtitleSink
```

录制 Pipeline 示例：

```
AudioCaptureFilter (audio_capture/) / VideoCaptureFilter (video_capture/)
  → AudioEncoderFilter (audio_encoder/) / SurfaceEncoderFilter (video_encoder/)
    → MediaCodec
  → MuxerFilter (muxer/)
    → MediaMuxer (modules/muxer/)
      → FFmpegMuxerPlugin / MPEG4MuxerPlugin
```

---

## 6. 关键Evidence索引

| 文件路径 | 行数 | 关键内容 |
|---------|------|---------|
| services/media_engine/filters/ | ~20子目录 | Filter组件完整列表 |
| services/media_engine/plugins/ffmpeg_adapter/common/ffmpeg_utils.cpp | 505行 | Mime2CodecId 15+ MIME映射 |
| services/media_engine/plugins/ffmpeg_adapter/common/ffmpeg_convert.cpp | 247行 | ColorSpace三函数映射(PQ/HLG/BT2020) |
| services/media_engine/plugins/ffmpeg_adapter/audio_encoder/ffmpeg_aac_encoder_plugin.cpp | 902行 | AVAudioFifo+ADTS 7字节头 |
| services/media_engine/plugins/ffmpeg_adapter/muxer/ffmpeg_muxer_plugin.cpp | 1414行 | 九格式FFmpeg封装 |
| services/media_engine/modules/sink/video_sink.cpp | 462行 | DoSyncWrite渲染决策，前4帧强制渲染 |
| services/media_engine/modules/sink/audio_sink.cpp | 1793行 | AudioVivid 80ms固定延迟补偿 |
| services/media_engine/modules/sink/subtitle_sink.cpp | 517行 | RenderLoop独立线程，三状态WAIT/SHOW/DROP |
| services/media_engine/modules/source/source.cpp | 715行 | 协议路由五类型(http/https/file/fd/stream) |
| services/media_engine/modules/source/audio_capture/audio_capture_module.cpp | 509行 | Read/Poll双模式+GetMaxAmplitude |
| services/media_engine/modules/demuxer/media_demuxer.cpp | 6012行 | 解封装核心引擎 |
| services/media_engine/modules/demuxer/stream_demuxer.cpp | 492行 | PullData分片缓存 |
| services/media_engine/modules/demuxer/demuxer_plugin_manager.cpp | 1159行 | 插件管理+三层映射表 |
| services/media_engine/modules/demuxer/type_finder.cpp | 216行 | PeekRange嗅探(DEFAULT_SNIFF_SIZE=4096*4) |
| services/media_engine/modules/muxer/media_muxer.cpp | 571行 | 封装核心+Track管理+四状态机 |
| services/media_engine/modules/pts_index_conversion/pts_and_index_conversion.cpp | 640行 | PTS↔Index双向转换 |

---

## 7. 关联主题

| 关联 | 主题ID | 说明 |
|------|--------|------|
| 上游 | S87, S37, S38 | Source模块协议路由/源插件体系 |
| 中游 | S41, S34, S14 | DemuxerFilter/MuxerFilter/FilterChain架构 |
| 下游 | S31, S32, S49 | AudioSinkFilter/VideoRenderFilter/SubtitleSinkFilter |
| 引擎 | S69, S75, S65 | MediaDemuxer/MediaMuxer核心引擎 |
| 插件 | S68, S76, S40 | FFmpegDemuxerPlugin/FFmpegMuxerPlugin |
| Pipeline | S112 | FilterGraph/PipelineController整体架构 |