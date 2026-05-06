# MEM-ARCH-AVCODEC-S40

status: approved
approved_at: "2026-05-06"
title: FFmpeg Muxer Plugin 体系——FFmpegMuxerPlugin + MediaMuxer + MuxerFilter 三层封装架构
scope: [AVCodec, MediaEngine, Muxer, FFmpeg, Plugin, FFmpegMuxerRegister, FLV, MP4, Container, MuxerFilter, MediaMuxer]
pipeline_position: 录制管线输出终点（多轨合成输出）
author: builder-agent
created_at: "2026-04-25T21:51:00+08:00"
evidence_count: 15

## 摘要
AVCodec 模块的封装（Muxer）体系由 FFmpegMuxerPlugin（底层 FFmpeg 封装）、MediaMuxer（中介管理层）、MuxerFilter（Filter 图入口）三层构成。FFmpegMuxerPlugin 直接操作 avformat（AVFormatContext/AVOutputFormat/AVIOContext），通过自定义 AVIOContext 的 IoRead/IoWrite/IoSeek 实现与 DataSink 的解耦；支持 mp4/ipod/amr/mp3/wav/adts/flac/ogg/flv 九种格式。MediaMuxer 是 Server 侧代理，负责 AddTrack/Start/Stop 并持有 MuxerPlugin 实例。MuxerFilter 是 Pipeline 入口，通过 MediaMuxer 调度多轨音频/视频的缓冲队列，完成录制管线末端的多路合成与文件输出。

## 架构要点
- **三层架构**：MuxerFilter（Pipeline 入口）→ MediaMuxer（Server 侧代理）→ FFmpegMuxerPlugin（底层 FFmpeg 封装）
- **九种格式支持**：mp4, ipod, amr, mp3, wav, adts, flac, ogg, flv，通过 supportedMuxer_ set 管理
- **LGPL 许可**：PLUGIN_DEFINITION(FFmpegMuxer, LicenseType::LGPL, ...) 遵循 FFmpeg LGPL 要求
- **FLV 专用插件**：name=="ffmpegMux_flv" → FFmpegFlvMuxerPlugin，其他 → FFmpegMuxerPlugin
- **自定义 AVIOContext**：InitAvIoCtx(DataSink) 替换 FFmpeg 内部 pb，通过 IoRead/IoWrite/IoSeek 回调桥接到 DataSink::Write/Read/Seek
- **AVFMT_FLAG_CUSTOM_IO**：formatContext_->flags |= AVFMT_FLAG_CUSTOM_IO，禁用 FFmpeg 内部 I/O，完全由外部 DataSink 驱动
- **两阶段写入**：Start() 调用 avformat_write_header（写入文件头），Stop() 调用 av_interleaved_write_trailer（写入尾信息）
- **多轨同步**：MuxerFilter 通过 preFilterCount_ 协调多轨（视频+音频+字幕），stopCount_==preFilterCount_ 时触发 Stop
- **maxDuration_ 超时停止**：EventCompleteStopAsync 异步线程执行 mediaMuxer_->Stop()，避免阻塞 Pipeline

## 关键证据

| 证据 | 文件:行号 | 说明 |
|------|-----------|------|
| E1 | ffmpeg_muxer_register.cpp:42-44 | supportedMuxer_ = {"mp4","ipod","amr","mp3","wav","adts","flac","ogg","flv"} 九种格式 |
| E2 | ffmpeg_muxer_register.cpp:33-34 | PLUGIN_DEFINITION(FFmpegMuxer, LicenseType::LGPL, Register/Unregister) |
| E3 | ffmpeg_muxer_register.cpp:182-186 | name=="ffmpegMux_flv" → FFmpegFlvMuxerPlugin; else → FFmpegMuxerPlugin |
| E4 | ffmpeg_muxer_register.cpp:250-252 | GetAVOutputFormat(pluginName) 返回 pluginOutputFmt_[pluginName] |
| E5 | ffmpeg_muxer_register.cpp:255-289 | InitAvIoCtx(DataSink) → AVIOContext，IoRead/IoWrite/IoSeek 回调桥接 DataSink |
| E6 | ffmpeg_muxer_register.cpp:310-330 | IoWrite → dataSink->Write(buf, bufSize)，直接转发到底层文件 |
| E7 | ffmpeg_muxer_plugin.h:106-107 | outputFormat_/formatContext_ 共享指针持有 FFmpeg 核心对象 |
| E8 | ffmpeg_muxer_plugin.cpp:81-92 | 构造：GetAVOutputFormat + avformat_alloc_context + AVFMT_FLAG_CUSTOM_IO + IoOpen/IoClose 注册 |
| E9 | ffmpeg_muxer_plugin.cpp:963-966 | AddTrack：isWriteHeader_ 检查 + outputFormat_ != nullptr 校验 |
| E10 | ffmpeg_muxer_plugin.cpp:1042-1073 | Start：avformat_alloc_context → avformat_write_header → isWriteHeader_=true |
| E11 | ffmpeg_muxer_plugin.cpp:1103-1110 | WriteSample：isWriteHeader_ 检查 + avpacket 写入 formatContext_->pb |
| E12 | muxer_filter.cpp:43-54 | FORMAT_TABLE：OutputFormat→MimeType 映射（MPEG_4/MP4、M4A、AMR、MP3、WAV、AAC） |
| E13 | muxer_filter.cpp:55-58 | AutoRegisterFilter("builtin.recorder.muxer", FILTERTYPE_MUXER) Pipeline 注册名 |
| E14 | muxer_filter.cpp:101-102 | MediaMuxer(appUid, appPid) + Init(fd, format) 创建底层封装器 |
| E15 | muxer_filter.cpp:178-182 | stopCount_==preFilterCount_ 时调用 mediaMuxer_->Stop()，多轨同步停止 |

## 关键文件清单

```
services/media_engine/plugins/ffmpeg_adapter/muxer/
├── ffmpeg_muxer_plugin.cpp          # FFmpeg 底层封装：WriteSample/Start/Stop
├── ffmpeg_muxer_plugin.h
├── ffmpeg_muxer_register.cpp       # 插件注册：FormatName2OutCapability/InitAvIoCtx
├── ffmpeg_muxer_register.h
├── flv_muxer/                       # FFmpegFlvMuxerPlugin 专用 FLV 封装
│   ├── ffmpeg_flv_muxer_plugin.cpp
│   └── ffmpeg_flv_muxer_plugin.h
└── mpeg4_muxer/                     # MPEG4 专用封装（如有）
services/media_engine/modules/muxer/
├── media_muxer.cpp                  # MediaMuxer：Server 侧 MuxerPlugin 代理
└── media_muxer.h
services/media_engine/filters/
└── muxer_filter.cpp                 # MuxerFilter：Pipeline 入口，多轨协调，maxDuration_ 停止
```

## 与相邻主题的关系
- **上游**：AudioCaptureFilter(S26)/VideoCaptureFilter(S28) 产生原始数据 → MuxerFilter 消费
- **下游**：文件写入 DataSink（文件描述符 fd）
- **对比 MuxerFilter(S8 音频)**：S8 覆盖 FFmpeg AudioCodecAdapter（音频编码），S40 覆盖 FFmpeg MuxerPlugin（容器封装）
- **依赖**：MuxerFilter ← MediaMuxer ← FFmpegMuxerPlugin ← FFmpeg libavformat/libavcodec
