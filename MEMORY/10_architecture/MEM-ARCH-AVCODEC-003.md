id: MEM-ARCH-AVCODEC-003
title: Plugin 架构——解封装/封装/源/池四类插件
type: architecture_fact
scope: [AVCodec, Plugin, Demuxer, Muxer]
status: approved
confidence: high
summary: >
  services/media_engine/plugins/ 目录下存在四类插件：
  - demuxer：解封装插件，读取媒体容器（mp4/mkv等），输出压缩流
  - muxer：（目录存在但内容未详细扫描）
  - source：媒体源插件（input）
  - sink：媒体输出插件（output）
  - ffmpeg_adapter：FFmpeg 适配层，将 FFmpeg 解封装能力适配进本框架
  media_codec/ 是编解码核心实现，位于 media_engine/modules/media_codec/。
why_it_matters:
 - 新需求开发：新增格式支持需要实现对应 demuxer/muxer plugin
 - 问题定位：封装/解封装问题在 plugin 层排查
 - 性能分析：sink/source 插件是数据流瓶颈定位的关键点
evidence:
 - kind: code
   ref: services/media_engine/plugins/
   anchor: 目录结构
   note: 四类插件：demuxer / muxer / source / sink + ffmpeg_adapter
 - kind: code
   ref: services/media_engine/modules/sink/
   anchor: 文件列表
   note: audio_sink.cpp / video_sink.cpp / subtitle_sink.cpp / media_sync_manager.cpp
 - kind: code
   ref: services/media_engine/modules/media_codec/
   anchor: 编解码核心
   note: media_codec.h/cpp 是编解码核心实现
 - kind: code
   ref: services/media_engine/modules/post_processor/
   anchor: 后处理模块
   note: video_post_processor_factory.cpp / super_resolution_post_processor 等
 - kind: doc
   ref: README_zh.md
   anchor: 模块介绍
   note: 官方文档提及插件化架构
related:
 - MEM-ARCH-AVCODEC-001
 - MEM-ARCH-AVCODEC-002
 - FAQ-SCENE3-001
owner: 耀耀
review:
  owner: 耀耀
  approved_at: "2026-04-17"
  change_policy: update_on_code_change
update_trigger: code_change
created_at: "2026-04-17"
updated_at: "2026-04-17"
