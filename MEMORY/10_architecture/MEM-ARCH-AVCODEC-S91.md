---
status: draft
mem_id: MEM-ARCH-AVCODEC-S91
title: "MPEG4 MuxerPlugin 写时构建架构——BasicBox树 / BoxParser / Mpeg4MuxerPlugin 三层封装"
scope: [AVCodec, MediaEngine, Muxer, MPEG4, MP4, ISOBMFF, Box, Track, Container]
evidence_sources:
  - "services/media_engine/plugins/ffmpeg_adapter/muxer/mpeg4_muxer/mpeg4_muxer_plugin.h(1-65)"
  - "services/media_engine/plugins/ffmpeg_adapter/muxer/mpeg4_muxer/basic_box.h(1-80)"
  - "services/media_engine/plugins/ffmpeg_adapter/muxer/mpeg4_muxer/basic_box.cpp"
  - "services/media_engine/plugins/ffmpeg_adapter/muxer/mpeg4_muxer/box_parser.h(1-80)"
  - "services/media_engine/plugins/ffmpeg_adapter/muxer/mpeg4_muxer/box_parser.cpp"
  - "services/media_engine/plugins/ffmpeg_adapter/muxer/mpeg4_muxer/track/basic_track.h"
核心发现：
- Mpeg4MuxerPlugin 采用"写时构建"（Write-Time Construction）策略：Header 在 Start() 时一次性写入，Tailer 在 Stop() 时后写入，moov_box 通过 MoveMoovBoxToFront 动态前移以满足流式场景
- BasicBox 是 ISOBMFF 容器节点的抽象基类，支持树形层级结构（父-子 container box）。FullBox 扩展 BasicBox 增加 version+flags 字段（用于 mvhd/trak 等 versioned box）
- BoxParser 负责构建完整的 moov 树：MoovBoxGenerate() → MvhdBoxGenerate / TrakBoxGenerate(mdia+stbl) / UdtaBox(地理位置/AIGC/用户元数据)
- Track 系统抽象为 BasicTrack，支持视频(AvccBox/HvccBox/ColrBox)和音频(EsdsBox)两种 track 类型，stbl 子 box 由 StsdBoxGenerate 分发到 AudioBoxGenerate / VideoBoxGenerate
- 与 FFmpegMuxerPlugin（S40）不同：本层直接操作 AVIOStream 字节流，不依赖 libavformat；支持 GLTF 3D 元数据盒（Aigc/海拔/经纬度地理标记）
关联记忆：S40（FFmpeg Muxer Plugin）, S58（MPEG4BoxParser 解析）, S65（MediaMuxer 封装核心）
---