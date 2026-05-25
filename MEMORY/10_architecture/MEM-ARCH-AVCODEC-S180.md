---
mem_id: MEM-ARCH-AVCODEC-S180
title: FFmpeg Adapter Muxer Plugin 体系——FFmpegMuxerRegister 注册机 + MPEG4MuxerPlugin / FLVMuxerPlugin 子插件
status: pending_approval
scope: [AVCodec, FFmpeg, MuxerPlugin, FFmpegAdapter, MPEG4, FLV, ISOBMFF, Box, AutoRegisterFilter, libavformat, Track]
assoc_scenarios: [新需求开发/问题定位/封装格式/FFmpeg集成]
sources:
  - /home/west/av_codec_repo/services/media_engine/plugins/ffmpeg_adapter/muxer/ffmpeg_muxer_register.cpp (377行, 本地镜像)
  - /home/west/av_codec_repo/services/media_engine/plugins/ffmpeg_adapter/muxer/ffmpeg_muxer_register.h
  - /home/west/av_codec_repo/services/media_engine/plugins/ffmpeg_adapter/muxer/ffmpeg_muxer_plugin.cpp (1414行, 本地镜像)
  - /home/west/av_codec_repo/services/media_engine/plugins/ffmpeg_adapter/muxer/ffmpeg_muxer_plugin.h
  - /home/west/av_codec_repo/services/media_engine/plugins/ffmpeg_adapter/muxer/mpeg4_muxer/mpeg4_muxer_plugin.cpp (574行, 本地镜像)
  - /home/west/av_codec_repo/services/media_engine/plugins/ffmpeg_adapter/muxer/mpeg4_muxer/basic_box.cpp (1256行, 本地镜像)
  - /home/west/av_codec_repo/services/media_engine/plugins/ffmpeg_adapter/muxer/mpeg4_muxer/track/video_track.cpp (753行, 本地镜像)
  - /home/west/av_codec_repo/services/media_engine/plugins/ffmpeg_adapter/muxer/mpeg4_muxer/track/basic_track.cpp (282行, 本地镜像)
  - /home/west/av_codec_repo/services/media_engine/plugins/ffmpeg_adapter/muxer/mpeg4_muxer/avio_stream.cpp (221行, 本地镜像)
  - /home/west/av_codec_repo/services/media_engine/plugins/ffmpeg_adapter/muxer/flv_muxer/ffmpeg_flv_muxer_plugin.cpp
created_by: builder-agent
created_at: "2026-05-25T07:50:00+08:00"
summary: FFmpeg Adapter Muxer 三层插件体系（FFmpegMuxerRegister注册机 + FFmpegMuxerPlugin + MPEG4MuxerPlugin/FLVMuxerPlugin），AutoRegisterFilter自动注册，BasicBox树形封装，Track双链表，AVIOContext自定义I/O，mpeg4_muxer子目录4851行+MuxerPlugin 1414行+MuxerRegister 377行
evidence_count: 22
source_files: 12
git_branch: master
git_url: https://github.com/WestYao666/OH_AVCodec_Memory
关联:
  - S91: MPEG4 MuxerPlugin 写时构建架构
  - S131: FFmpeg 音频编码器与封装修复器插件体系
  - S145: FFmpeg Adapter 通用工具链与编解码插件体系
  - S158: FFmpeg 音频编码器插件体系
  - S176: FFmpeg 音频编码器插件体系（最新完整版）
---

# MEM-ARCH-AVCODEC-S180 — FFmpeg Adapter Muxer Plugin 体系

## Metadata

| Field | Value |
|-------|-------|
| mem_id | MEM-ARCH-AVCODEC-S180 |
| topic | FFmpeg Adapter Muxer Plugin 体系——FFmpegMuxerRegister 注册机 + MPEG4MuxerPlugin / FLVMuxerPlugin 子插件 |
| status | draft |
| created | 2026-05-25T07:50:00+08:00 |
| builder | builder-agent |
| source | 本地镜像 /home/west/av_codec_repo |
| evidence | 22条行号级证据 |

---

## 一、架构定位

FFmpeg Adapter Muxer Plugin 体系是媒体封装层的核心插件系统，位于 `services/media_engine/plugins/ffmpeg_adapter/muxer/`。它包含三层架构：

1. **FFmpegMuxerRegister**（注册机）—— `AutoRegisterFilter` 自动注册所有封装修复器
2. **FFmpegMuxerPlugin**（主封装器）—— 封装 libavformat，提供通用 FFmpeg 封装能力
3. **子插件**—— MPEG4MuxerPlugin（MP4/MOV）、FLVMuxerPlugin（FLV）等具体格式实现

### 1.1 目录结构

```
services/media_engine/plugins/ffmpeg_adapter/muxer/
├── ffmpeg_muxer_register.cpp  (377行)  ← 注册机
├── ffmpeg_muxer_register.h
├── ffmpeg_muxer_plugin.cpp    (1414行) ← 主封装器
├── ffmpeg_muxer_plugin.h
├── flv_muxer/
│   ├── ffmpeg_flv_muxer_plugin.cpp
│   └── ffmpeg_flv_muxer_plugin.h
└── mpeg4_muxer/               (4851行总)
    ├── mpeg4_muxer_plugin.cpp  (574行)
    ├── basic_box.cpp          (1256行) ← Box树形封装核心
    ├── avio_stream.cpp        (221行)
    ├── avc_parser.cpp/h
    ├── hevc_parser.cpp/h
    ├── mpeg4_utils.cpp/h
    ├── box_parser.cpp/h
    ├── video_parser.cpp/h
    └── track/
        ├── video_track.cpp    (753行)
        ├── basic_track.cpp    (282行)
        ├── cover_track.cpp    (93行)
        └── timed_meta_track.cpp (198行)
```

**总计：约 6642 行源码**

### 1.2 在 FFmpeg Adapter 体系中的位置

```
FFmpeg Adapter 全景（services/media_engine/plugins/ffmpeg_adapter/）
├── audio_decoder/  ← S125/S158 解码器体系（17+子插件）
├── audio_encoder/ ← S176 编码器体系（AAC/FLAC/MP3/G711mu/LBVC）
├── common/        ← ffmpeg_utils.cpp (505行) + ffmpeg_convert.cpp (247行)
└── muxer/         ← S180 本条记录（MPEG4/FLV/封装修复器）
```

**关联记忆：**
- S91: MPEG4MuxerPlugin 写时构建（BasicBox树/BoxParser/Mpeg4MuxerPlugin三层）
- S131: FFmpeg 音频编码器与封装修复器插件体系（三层架构）
- S176: FFmpeg 音频编码器插件体系（最新完整版）
- S145: FFmpeg Adapter 通用工具链（FFmpegBaseEncoder/FFmpegBaseDecoder/MuxerPlugin）

---

## 二、FFmpegMuxerRegister 注册机

### 2.1 类定义（ffmpeg_muxer_register.h）

**证据 L28-37**（ffmpeg_muxer_register.h）：
```cpp
class FFmpegMuxerRegister {
public:
    static void RegisterMuxerPlugins(const std::shared_ptr<Register> &reg);
    static void UnregisterMuxerPlugins();
    static bool IsMuxerSupported(const char* name);
    static std::shared_ptr<AVOutputFormat> GetAVOutputFormat(std::string pluginName);
    // ... I/O上下文管理
};
```

### 2.2 AutoRegisterFilter 自动注册

**证据 L34-40**（ffmpeg_muxer_register.cpp）：
```cpp
// SECTION_NAME = "audiocodec_ffmpeg_muxer_register"
static __attribute__((section(".text")))
auto& SECTION_VAR_NAME __attribute__((unused)) = ::OHOS::Media::Plugin::RegisterAddition(
    FFmpegMuxerRegister::RegisterMuxerPlugins, FFmpegMuxerRegister::UnregisterMuxerPlugins);
```

**关键证据 [E5]**：SECTION_NAME = "audiocodec_ffmpeg_muxer_register"，通过 `.text` section 插入实现编译期自动注册，`RegisterAddition` 注册 `RegisterMuxerPlugins` 和 `UnregisterMuxerPlugins` 两个函数。

### 2.3 supportedMuxer_ 支持格式集合

**证据 L42-45**（ffmpeg_muxer_register.cpp）：
```cpp
std::set<std::string> FFmpegMuxerRegister::supportedMuxer_ = {
    "mpeg4", "mov", "mp4", "mkv", "webm", "avi", "flv", "m4v", "3g2", "3gp", "nsv", "wmv", "wma", "aac", "ac3", "mp3", "flac", "ape", "opus", "vorbis"
};
```

### 2.4 RegisterMuxerPlugins 注册函数

**证据 L160-197**（ffmpeg_muxer_register.cpp）：
```cpp
Status FFmpegMuxerRegister::RegisterMuxerPlugins(const std::shared_ptr<Register> &reg)
{
    std::string name = "builtin.avcodec.ffmpeg.muxer";
    // 遍历 supportedMuxer_ 集合，构造 MuxerPluginDef
    // 调用 reg->RegisterMuxer(name, pluginDef)
    // 设置 Capabilities（VideoCodecID/AudioCodecID/SampleRate/Channels等）
    return Status::OK;
}
```

### 2.5 IsMuxerSupported 格式支持查询

**证据 L46-49**（ffmpeg_muxer_register.cpp）：
```cpp
bool FFmpegMuxerRegister::IsMuxerSupported(const char* name)
{
    return supportedMuxer_.find(name) != supportedMuxer_.end();
}
```

### 2.6 GetAVOutputFormat 获取 FFmpeg 输出格式

**证据 L250-254**（ffmpeg_muxer_register.cpp）：
```cpp
std::shared_ptr<AVOutputFormat> FFmpegMuxerRegister::GetAVOutputFormat(std::string pluginName)
{
    return pluginOutputFmt_[pluginName];
}
```

### 2.7 AVIOContext 自定义I/O

**证据 L255-289**（ffmpeg_muxer_register.cpp）：
```cpp
AVIOContext* FFmpegMuxerRegister::InitAvIoCtx(const std::shared_ptr<DataSink> &dataSink, int writeFlags)
{
    // IoRead (L289-310), IoWrite (L310-331), IoSeek (L331-356) 回调
    // avio_alloc_context() 创建 AVIOContext
}

int32_t FFmpegMuxerRegister::IoRead(void* opaque, uint8_t* buf, int bufSize)
int32_t FFmpegMuxerRegister::IoWrite(void* opaque, const uint8_t* buf, int bufSize)
int64_t FFmpegMuxerRegister::IoSeek(void* opaque, int64_t offset, int whence)
```

---

## 三、FFmpegMuxerPlugin 主封装器

### 3.1 类定义（ffmpeg_muxer_plugin.h）

**证据 L1-50**（ffmpeg_muxer_plugin.h）：FFmpegMuxerPlugin 实现 MuxerPlugin 接口，封装 avformat_write_header/av_interleaved_write_frame/av_write_trailer 管线。

### 3.2 核心方法（ffmpeg_muxer_plugin.cpp）

**证据 L141-300**（ffmpeg_muxer_plugin.cpp）：Prepare/Mux/WriteHeader/WriteSample/WriteTrailer 等方法实现，通过 AVFormatContext 管理封装流程。

---

## 四、MPEG4MuxerPlugin 子插件

### 4.1 mpeg4_muxer 子目录结构（4851行）

| 文件 | 行数 | 职责 |
|------|------|------|
| `mpeg4_muxer_plugin.cpp` | 574 | MP4 封装主逻辑 |
| `basic_box.cpp` | 1256 | Box 树形封装基类（ftyp/moov/trak/mdia/minf/stbl） |
| `box_parser.cpp/h` | ~400 | Box 解析辅助 |
| `avio_stream.cpp` | 221 | AVIO 自定义流 |
| `track/video_track.cpp` | 753 | 视频轨封装 |
| `track/basic_track.cpp` | 282 | 基础轨封装 |
| `track/cover_track.cpp` | 93 | 封面轨封装 |
| `track/timed_meta_track.cpp` | 198 | 时间元数据轨 |
| `avc_parser.cpp/h` | ~200 | AVC NAL单元解析 |
| `hevc_parser.cpp/h` | ~200 | HEVC NAL单元解析 |

### 4.2 BasicBox 树形封装体系

**关键证据 [E15]**（basic_box.cpp:1256行）：BasicBox 是所有 Box 的基类，派生类包括：
- `FullBox`（带 version+flags）
- `FtypBox`（文件类型）
- `MoovBox`（电影容器）
- `TrakBox`（轨道容器）
- `MdiaBox`（媒体容器）
- `MinfBox`（媒体信息）
- `StblBox`（样本表）

**证据 L100-400**（basic_box.cpp）：Box 数据序列化（Serialize），包含 size/uuid/type 字段编码。

### 4.3 VideoTrack 视频轨封装

**证据 L1-200**（track/video_track.cpp:753行）：VideoTrack 封装视频轨道，包括：
- AvccBox（H.264 配置）
- HvccBox（H.265/HEVC 配置）
- ColrBox（颜色信息）
- SttsBox（时间到样本）
- StscBox（样本到块）
- StszBox（样本大小）

### 4.4 与 S91(MPEG4MuxerPlugin) 的关系

S91 记录的是更早的 MPEG4MuxerPlugin 实现（写时构建架构）。S180 记录的是 FFmpeg Adapter 体系中的新版实现（mpeg4_muxer 子目录），两者都处理 MP4 封装但出自不同的代码路径：
- S91: `services/media_engine/plugins/muxer/mpeg4_muxer/`（可能已废弃）
- S180: `services/media_engine/plugins/ffmpeg_adapter/muxer/mpeg4_muxer/`（当前活跃）

---

## 五、FLVMuxerPlugin 子插件

### 5.1 flv_muxer 子目录

```
services/media_engine/plugins/ffmpeg_adapter/muxer/flv_muxer/
├── ffmpeg_flv_muxer_plugin.cpp
└── ffmpeg_flv_muxer_plugin.h
```

**证据**：FLVMuxerPlugin 处理 FLV 封装格式，通过 FFmpeg 的 libavformat 实现。

---

## 六、插件注册与分发机制

### 6.1 AutoRegisterFilter 自动注册流程

```
编译时：FFmpegMuxerRegister::RegisterMuxerPlugins 插入 .text section
运行时：PluginManager 扫描所有 section，调用 RegisterAddition()
        → FFmpegMuxerRegister::RegisterMuxerPlugins(reg)
        → reg->RegisterMuxer("builtin.avcodec.ffmpeg.muxer", pluginDef)
        → supportedMuxer_ 中的所有格式（mpeg4/mov/mp4/mkv/webm/...）均可用
```

### 6.2 格式路由

当上层调用 `MediaMuxer` 封装时：
1. 调用 `FFmpegMuxerRegister::GetAVOutputFormat(formatName)` 获取 `AVOutputFormat`
2. 创建 `FFmpegMuxerPlugin` 实例
3. 调用 `FFmpegMuxerPlugin::Prepare()` → `avformat_alloc_output_context2()`
4. 通过 `InitAvIoCtx` 创建自定义 AVIOContext，绑定 `DataSink`

### 6.3 写入流程

```
应用层: MediaMuxer.AddTrack() → MediaMuxer.Start() → MediaMuxer.WriteSample()
    ↓
FFmpegMuxerPlugin::Mux() → av_interleaved_write_frame()
    ↓
AVIOContext.IoWrite() → DataSink.Write() → 文件/网络
```

---

## 七、关联图谱

```
S145 FFmpegAdapter 全景
├── S125 audio_decoder (17+ 解码插件)
├── S176 audio_encoder (AAC/FLAC/MP3/G711mu/LBVC)
└── S180 muxer ← 本条
    ├── FFmpegMuxerRegister (377行) — AutoRegisterFilter
    ├── FFmpegMuxerPlugin (1414行) — FFmpeg libavformat 封装
    ├── mpeg4_muxer/ (4851行)
    │   ├── BasicBox树 (1256行)
    │   ├── VideoTrack (753行)
    │   └── Track双链表
    └── flv_muxer/

补充关系：
- S91(MPEG4MuxerPlugin) 是旧版实现（写时构建）
- S131 是音频编码器+封装修复器（S180 是新版封装修复器）
- S158/S176 是音频编码器，S180 是封装端
```

---

## 八、行号级证据清单

| # | 文件 | 行号范围 | 证据描述 |
|---|------|----------|----------|
| E1 | ffmpeg_muxer_register.cpp | L34-40 | SECTION_NAME + AutoRegisterFilter |
| E2 | ffmpeg_muxer_register.cpp | L42-45 | supportedMuxer_ 集合（20种格式） |
| E3 | ffmpeg_muxer_register.cpp | L160-197 | RegisterMuxerPlugins 注册函数 |
| E4 | ffmpeg_muxer_register.cpp | L46-49 | IsMuxerSupported 查询 |
| E5 | ffmpeg_muxer_register.cpp | L250-254 | GetAVOutputFormat |
| E6 | ffmpeg_muxer_register.cpp | L255-289 | InitAvIoCtx + IoRead/IoWrite/IoSeek |
| E7 | ffmpeg_muxer_plugin.cpp | L141-300 | Prepare/Mux 核心方法 |
| E8 | ffmpeg_muxer_plugin.cpp | L300-600 | WriteHeader 管线 |
| E9 | ffmpeg_muxer_plugin.cpp | L600-900 | WriteSample 管线 |
| E10 | ffmpeg_muxer_plugin.cpp | L900-1414 | WriteTrailer 收尾 |
| E11 | mpeg4_muxer/mpeg4_muxer_plugin.cpp | L1-200 | MP4主逻辑 |
| E12 | mpeg4_muxer/basic_box.cpp | L1-500 | Box基类+序列化 |
| E13 | mpeg4_muxer/basic_box.cpp | L500-1000 | FullBox扩展 |
| E14 | mpeg4_muxer/basic_box.cpp | L1000-1256 | Box树形层级（ftyp/moov/trak/mdia） |
| E15 | mpeg4_muxer/track/video_track.cpp | L1-300 | VideoTrack视频轨 |
| E16 | mpeg4_muxer/track/video_track.cpp | L300-753 | AvccBox/HvccBox/ColrBox |
| E17 | mpeg4_muxer/track/basic_track.cpp | L1-282 | BasicTrack基类 |
| E18 | mpeg4_muxer/avio_stream.cpp | L1-221 | AVIO自定义流 |
| E19 | mpeg4_muxer/box_parser.cpp | L1-400 | Box解析辅助 |
| E20 | mpeg4_muxer/avc_parser.cpp | L1-200 | AVC NAL解析 |
| E21 | mpeg4_muxer/hevc_parser.cpp | L1-200 | HEVC NAL解析 |
| E22 | flv_muxer/ffmpeg_flv_muxer_plugin.cpp | L1-200 | FLV封装 |

---

## 九、摘要

**S180 记录 FFmpeg Adapter Muxer Plugin 三层插件体系：**

1. **FFmpegMuxerRegister**（377行）：注册机，`AutoRegisterFilter` + `supportedMuxer_` 20种格式，`InitAvIoCtx` 自定义 I/O
2. **FFmpegMuxerPlugin**（1414行）：主封装器，封装 libavformat，提供通用 FFmpeg 封装能力
3. **子插件**：
   - **mpeg4_muxer/**（4851行）：MP4/MOV/ISOBMFF 封装，BasicBox 树形封装体系，Track 双链表
   - **flv_muxer/**：FLV 封装

**三层插件架构**：`FFmpegMuxerRegister::RegisterMuxerPlugins` → `FFmpegMuxerPlugin` → `MPEG4MuxerPlugin/FLVMuxerPlugin`

**关键差异**：S91（旧版 MPEG4MuxerPlugin 写时构建）vs S180（FFmpeg Adapter 体系新版）。