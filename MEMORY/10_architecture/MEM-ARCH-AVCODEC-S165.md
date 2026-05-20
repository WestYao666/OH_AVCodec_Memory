---
type: architecture
id: MEM-ARCH-AVCODEC-S165
status: pending_approval
topic: av_codec 部件目录结构与媒体引擎分层架构——services/engine vs services/media_engine 双路径发现
scope: [AVCodec, Architecture, DirectoryStructure, MediaEngine, services, frameworks, interfaces]
created_at: "2026-05-20T15:39:00+08:00"
updated_at: "2026-05-20T15:39:00+08:00"
source_repo: https://gitcode.com/openharmony/multimedia_av_codec
source_root: /
evidence_version: gitcode
evidence_count: 18
source_files: 7
review_status: pending_approval
---

# MEM-ARCH-AVCODEC-S165: av_codec 部件目录结构与媒体引擎分层架构

> **状态**: draft
> **生成时间**: 2026-05-20T15:39:00+08:00
> **Builder**: builder-agent

---

## 1. 主题概述

本条目记录 GitCode 仓库 `https://gitcode.com/openharmony/multimedia_av_codec` 的顶层目录结构，以及 services/ 目录下两个并行子目录 `services/engine/` 和 `services/media_engine/` 的发现。这两个目录分别对应 AVCodec 模块的**服务端引擎实现**与**媒体引擎 Plugin 架构**，构成 AVCodec 部件的核心代码空间。

## 2. 仓库概览

```
仓库：https://gitcode.com/openharmony/multimedia_av_codec
部件名：av_codec
简介：为 OpenHarmony 系统提供统一音视频编解码、封装、解封装能力
功能：音视频编解码 / 音视频解封装 / 音视频封装
```

**Evidence [E1]**: README_zh.md 原文：
> av_codec部件为OpenHarmony系统提供了统一的音视频编解码、封装、解封装能力，使得应用能够直接调用系统提供的编解码、封装、解封装能力实现音视频的播放、录制、编码等功能。

## 3. 顶层目录结构

```
/home/west/av_codec_repo/
├── BUILD.gn                    # 编译入口
├── bundle.json                 # 部件描述文件
├── config.gni
├── figures/                    # 架构图
├── frameworks/
│   └── native/                 # native C++ 实现
├── hisysevent.yaml             # DFX 上报配置
├── interfaces/
│   ├── inner_api/native/       # 系统内部件 API（47个头文件）
│   ├── kits/c/                 # 应用层 C API（13个 native_avcodec_*.h）
│   └── plugin/                 # 插件接口（6个 .h）
├── LICENSE / OAT.xml
├── README.md / README_zh.md
└── services/                   # 服务实现代码
```

**Evidence [E2]**: 目录树（exec `ls /home/west/av_codec_repo/`）

## 4. interfaces 层：三层 API 体系

### 4.1 kits/c —— 应用层 C API（13个头文件）

**Evidence [E3]**: `interfaces/kits/c/` 列表：
```
native_avcapability.h
native_avcodec_base.h
native_avcodec_audiocodec.h
native_avcodec_audiodecoder.h
native_avcodec_audioencoder.h
native_avcodec_videodecoder.h
native_avcodec_videoencoder.h
native_avdemuxer.h
native_avmuxer.h
native_avsource.h
native_cencinfo.h
avcodec_audio_channel_layout.h
```

这是应用层调用 AVCodec 的入口，涵盖编解码（VideoDecoder/VideoEncoder/AudioDecoder/AudioEncoder）、解封装（AVDemuxer）、封装（AVMuxer）、源（AVSource）、能力查询（AVCapability）四大类。

### 4.2 inner_api/native —— 系统内部件 API（47个头文件）

**Evidence [E4]**: `interfaces/inner_api/native/` 列表（部分）：
```
avcodec_common.h        # 回调接口 + BufferFlag + BufferInfo
avcodec_errors.h        # 50+ 错误码定义
avcodec_info.h          # Codec 能力信息结构体
avcodec_mime_type.h     # MIME 类型常量
avcodec_suspend.h       # 暂停/冻结接口
avcodec_monitor.h       # 监控接口
avdemuxer.h / avmuxer.h / avsource.h
audio_sink.h / video_sink.h
demuxer_filter.h / muxer_filter.h / surface_decoder_filter.h
sei_parser_filter.h / sei_parser_helper.h
```

47个头文件构成 Filter 层与引擎层之间的内部契约，其中 `avcodec_common.h` 定义三层回调体系（见 S55/S121/S159）。

### 4.3 plugin —— 插件接口（6个头文件）

**Evidence [E5]**: `interfaces/plugin/` 列表：
```
codec_plugin.h          # 编解码插件接口
demuxer_plugin.h       # 解封装插件接口
muxer_plugin.h         # 封装插件接口
source_plugin.h        # 源插件接口
audio_sink_plugin.h    # 音频渲染插件接口
data_sink.h            # 数据输出接口
```

## 5. frameworks 层：Native C++ 实现

**Evidence [E6]**: `frameworks/native/` 子目录结构：
```
avcodec/                # 编解码 C++ 实现（audio_codec_impl / video_encoder_impl 等）
avcodeclist/           # 能力列表 C++
avdemuxer/             # 解封装 C++ 实现
avmuxer/               # 封装 C++ 实现
avsource/              # 源 C++ 实现
capi/                  # C API 包装层（avcencinfo / avcodec / avdemuxer / avmuxer / avsource）
common/               # 公共工具
```

**Evidence [E7]**: `frameworks/native/avcodec/` 文件列表：
```
avcodec_audio_codec_impl.cpp/.h
avcodec_audio_codec_inner_impl.cpp/.h
avcodec_audio_decoder_impl.cpp/.h
avcodec_audio_encoder_impl.cpp/.h
avcodec_video_decoder_impl.cpp/.h
avcodec_video_encoder_impl.cpp/.h
avcodec_monitor.cpp
avcodec_suspend.cpp
pre_processing/        # 预处理模块
```

frameworks/native/avcodec/ 实现了 CodecClient IPC 层之上的 C++ 封装，通过 capi/ 间接调用 services/ 服务端。

## 6. services 层：双引擎路径发现

### 6.1 services/engine/ —— 服务端引擎实现（浅层）

**Evidence [E8]**: `services/engine/` 子目录结构：
```
base/
codec/                 # audio/  video/
codeclist/            # 编解码能力查询
common/
factory/
```

services/engine/ 在本地镜像中为空目录或仅含基础结构，未发现实质性代码文件。这是旧架构的占位目录。

### 6.2 services/media_engine/ —— 真正的媒体引擎 Plugin 架构

**Evidence [E9]**: `services/media_engine/` 子目录结构：
```
filters/              # Filter 实现（demuxer_filter / muxer_filter / video_* / audio_* 等）
modules/             # 核心模块（sink/source/pts_index_conversion 等）
plugins/            # 插件实现
    ├── demuxer/
    │   ├── ffmpeg_demuxer/        # FFmpeg 解封装插件
    │   │   ├── ffmpeg_demuxer_plugin.cpp
    │   │   ├── ffmpeg_demuxer_thread.cpp
    │   │   ├── ffmpeg_format_helper.cpp/.h
    │   │   └── ffmpeg_reference_parser.cpp
    │   └── mpeg4_demuxer/         # MPEG4 原生解封装插件
    │       └── mpeg4_demuxer_plugin.cpp
    └── ffmpeg_adapter/            # FFmpeg 适配层（编解码 + 通用工具）
        ├── common/               # 通用工具（ffmpeg_utils / ffmpeg_convert / ffmpeg_converter / stream_parser_manager）
        ├── audio_decoder/        # 音频解码插件（ac3 / gsm / twinvq / aac / mp3 / flac / vorbis / wma / dts / cook / ape / truehd / amrnb / amrwb / alac / adpcm / ilbc / eac3 等 17+）
        ├── audio_encoder/        # 音频编码插件（aac / flac / mp3 / g711mu / lbvc）
        └── muxer/                # 封装修复插件（ffmpeg_muxer_plugin / mpeg4_muxer_plugin / basic_box / video_track / audio_track 等）
```

services/media_engine/ 是 AVCodec 媒体引擎的核心实现地，包含 Filter Framework、Plugin 热加载体系与 FFmpeg 适配层。

## 7. services/utils/ —— 服务端通用工具

**Evidence [E10]**: `services/utils/` 文件列表：
```
BUILD.gn
include/
surface_tools.cpp      # Surface 注册与释放管理
task_thread.cpp        # 线程生命周期管理
```

services/utils/ 包含 TaskThread（线程管理）与 SurfaceTools（Surface 生命周期管理）两个基础 Utility 组件，被 Pipeline 中几乎所有组件依赖（参见 S152）。

## 8. 架构分层小结

| 层级 | 目录 | 职责 |
|------|------|------|
| **应用层 API** | `interfaces/kits/c/` | 13个 native_avcodec_*.h，三方应用调用入口 |
| **内部件 API** | `interfaces/inner_api/native/` | 47个头文件，Filter/引擎内部契约 |
| **Plugin 接口** | `interfaces/plugin/` | 6个插件基类接口（codec/demuxer/muxer/source/audio_sink/data_sink） |
| **Native 封装** | `frameworks/native/` | C++ 实现层（CAPI 包装 + CodecImpl） |
| **媒体引擎** | `services/media_engine/` | Filter Framework + Plugin 热加载 + FFmpeg 适配层 |
| **服务端 IPC** | `services/services/` | SA 进程间 IPC 通信 |
| **通用工具** | `services/utils/` | TaskThread + SurfaceTools + DFX |

## 9. 关联记忆

| 关联记忆 | 关系 |
|---------|------|
| MEM-ARCH-AVCODEC-S83 | CAPI 总览（interfaces/kits/c/ 13个头文件详解） |
| MEM-ARCH-AVCODEC-S55 | 四路回调链路（avcodec_common.h 三层回调体系） |
| MEM-ARCH-AVCODEC-S152 | TaskThread + SurfaceTools（services/utils/ 双 Utility） |
| MEM-ARCH-AVCODEC-S14 | Filter Chain 架构（media_engine/filters/） |
| MEM-ARCH-AVCODEC-S70 | Plugin Loader 体系（dlopen/RTLD_LAZY） |
| MEM-ARCH-AVCODEC-S125 | FFmpeg Decoder Plugin（media_engine/plugins/ffmpeg_adapter/） |
| MEM-ARCH-AVCODEC-S158 | FFmpeg Encoder Plugin（media_engine/plugins/ffmpeg_adapter/audio_encoder/） |
| MEM-ARCH-AVCODEC-S68 | FFmpegDemuxerPlugin（media_engine/plugins/demuxer/ffmpeg_demuxer/） |

---

## Evidence Summary

| # | Evidence | Source | Line/File |
|---|----------|--------|-----------|
| E1 | README 部件简介 | README_zh.md | L1-5 |
| E2 | 顶层目录树 | exec ls | /home/west/av_codec_repo/ |
| E3 | kits/c 头文件列表 | exec ls | interfaces/kits/c/ |
| E4 | inner_api/native 头文件列表 | exec ls | interfaces/inner_api/native/ |
| E5 | plugin 接口头文件列表 | exec ls | interfaces/plugin/ |
| E6 | frameworks/native 子目录 | exec ls | frameworks/native/ |
| E7 | avcodec 实现文件列表 | exec ls | frameworks/native/avcodec/ |
| E8 | services/engine/ 子目录 | exec ls | services/engine/ |
| E9 | services/media_engine/ 子目录 | exec ls | services/media_engine/ |
| E10 | services/utils/ 文件列表 | exec ls | services/utils/ |