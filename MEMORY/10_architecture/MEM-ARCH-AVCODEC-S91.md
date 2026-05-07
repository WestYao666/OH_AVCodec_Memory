---
id: MEM-ARCH-AVCODEC-S91
title: "MPEG4 MuxerPlugin 写时构建架构——BasicBox树 / BoxParser / Mpeg4MuxerPlugin 三层封装"
status: draft
author: builder-agent
created_at: "2026-05-07T15:30:00+08:00"
evidence:
  - source: "services/media_engine/plugins/ffmpeg_adapter/muxer/mpeg4_muxer/mpeg4_muxer_plugin.h"
    lines: "1-65"
    finding: "Mpeg4MuxerPlugin 写时构建策略：Start() 时一次性写入 Header，Stop() 时后写入 Tailer，moov_box 通过 MoveMoovBoxToFront 动态前移以满足流式场景"
  - source: "services/media_engine/plugins/ffmpeg_adapter/muxer/mpeg4_muxer/basic_box.h"
    lines: "1-80"
    finding: "BasicBox 是 ISOBMFF 容器节点抽象基类，支持树形层级结构（父-子 container box）。FullBox 扩展 BasicBox 增加 version+flags 字段（用于 mvhd/trak 等 versioned box）"
  - source: "services/media_engine/plugins/ffmpeg_adapter/muxer/mpeg4_muxer/basic_box.cpp"
    lines: "1-n"
    finding: "BasicBox 树形结构实现，父-子 box 层级管理"
  - source: "services/media_engine/plugins/ffmpeg_adapter/muxer/mpeg4_muxer/box_parser.h"
    lines: "1-80"
    finding: "BoxParser 负责构建完整的 moov 树：MoovBoxGenerate() → MvhdBoxGenerate / TrakBoxGenerate(mdia+stbl) / UdtaBox"
  - source: "services/media_engine/plugins/ffmpeg_adapter/muxer/mpeg4_muxer/box_parser.cpp"
    lines: "1-n"
    finding: "moov_box 生成实现，TrakBoxGenerate 分发到 AudioBoxGenerate / VideoBoxGenerate"
  - source: "services/media_engine/plugins/ffmpeg_adapter/muxer/mpeg4_muxer/track/basic_track.h"
    lines: "1-n"
    finding: "BasicTrack 支持视频(AvccBox/HvccBox/ColrBox)和音频(EsdsBox)两种 track 类型"
tags: [architecture, avcodec, muxer, mpeg4, isoBMFF, box, track]
related:
  - MEM-ARCH-AVCODEC-S40
  - MEM-ARCH-AVCODEC-S58
  - MEM-ARCH-AVCODEC-S65
  - MEM-ARCH-AVCODEC-S74
---

# MPEG4 MuxerPlugin 写时构建架构

## 概述

Mpeg4MuxerPlugin 是 OpenHarmony AVCodec 媒体引擎中**原生 MP4/MOV 封装器的核心实现**，采用"写时构建"（Write-Time Construction）策略——Header 在 Start() 时一次性写入，Tailer 在 Stop() 时后写入，moov_box 通过 MoveMoovBoxToFront 动态前移以满足流式场景。与 FFmpegMuxerPlugin（S40）不同，本层直接操作 AVIOStream 字节流，不依赖 libavformat；支持 GLTF 3D 元数据盒（Aigc/海拔/经纬度地理标记）。

## 架构分层

三层组件协作：

```
Mpeg4MuxerPlugin（对外接口层）
    ↓
BoxParser（Box 树构建层）
    ↓
BasicBox / FullBox（ISOBMFF 节点层）
```

- **BasicBox**：ISOBMFF 容器节点的抽象基类，支持树形层级结构（父-子 container box）
- **FullBox**：扩展 BasicBox，增加 version+flags 字段（用于 mvhd/trak 等 versioned box）
- **BoxParser**：构建完整的 moov 树结构
- **Mpeg4MuxerPlugin**：对外提供 Start/Stop/AddTrack/WriteSample 接口

## 核心组件

### BasicBox / FullBox（ISOBMFF 节点层）

- **BasicBox**：虚基类，定义 size + type (4字节) 结构，派生 container box（moov/trak/mdia/minf 等）
- **FullBox**：在 BasicBox 基础上增加 version (1字节) + flags (3字节)，派生 mvhd/mdhd/tkhd 等 versioned box
- **树形层级**：父 box 持有 children_ 向量，递归 FlushWrite 写入字节流

### BoxParser（Box 树构建层）

- **MoovBoxGenerate()**：顶层入口，生成完整 moov box
  - MvhdBoxGenerate()：movie header box（timescale/Duration）
  - TrakBoxGenerate()：track box（含 mdia+stbl 子结构）
  - UdtaBoxGenerate()：用户元数据（地理位置/AIGC/海拔）
- **Stbl 子表生成**：StsdBoxGenerate 分发到 AudioBoxGenerate / VideoBoxGenerate

### Track 系统

- **BasicTrack**：抽象基类
- **视频 Track**：AvccBox（AVC 解码参数）/ HvccBox（HEVC 解码参数）/ ColrBox（色彩描述）
- **音频 Track**：EsdsBox（ES_descriptor）

## 关键设计

### 写时构建策略（Write-Time Construction）

```
Start() → 写入 ftyp_box（固定）
         → 创建 moov_box 树（内存）
Stop()  → 写入 moov_box（MoveMoovBoxToFront 将 moov 前移到 ftyp 后）
         → 写入 mdat_box（数据区）
```

**关键**：流式录制场景下，moov 不能立即写入（因为 duration 未知），因此在 Stop() 时通过 MoveMoovBoxToFront 将 moov 动态前移到 ftyp 之后，保证 MP4 文件可被播放器即时解析。

### 与 FFmpegMuxerPlugin（S40）的区别

| 维度 | FFmpegMuxerPlugin | Mpeg4MuxerPlugin |
|------|-------------------|-------------------|
| 底层 | libavformat（九格式） | 直接操作 AVIOStream 字节流 |
| moov 处理 | libavformat 自动管理 | MoveMoovBoxToFront 手动控制 |
| 依赖 | libavcodec.z.so | 无 FFmpeg 依赖 |
| GLTF 元数据 | 不支持 | AigcBox/UdtaBox 支持 |

### GLTF 3D 元数据支持

UdtaBox 支持写入：
- **AigcBox**：AIGC 生成内容标记
- **地理标记**：经纬度/海拔信息
- **用户自定义元数据**

## 关联记忆

- **S40**（FFmpegMuxerPlugin）：FFmpeg 封装层，九格式支持，与本主题互补
- **S58**（MPEG4BoxParser）：MP4/MOV 解析侧，与本主题封装侧对称
- **S65**（MediaMuxer）：Track 管理器，调用 Mpeg4MuxerPlugin
- **S74**（FFmpegMuxerPlugin 与 Mpeg4MuxerPlugin 双插件对比）：两种封装路径横向对比
