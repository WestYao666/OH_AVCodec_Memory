---
mem_id: MEM-ARCH-AVCODEC-S76
status: pending_approval
submitted_by: builder-agent
submitted_at: "2026-05-03T07:19:00+08:00"
scope: AVCodec, MediaEngine, Demuxer, FFmpeg, Plugin, FFmpegDemuxerPlugin, libavformat, avformat_open_input, av_read_frame, av_seek_frame, BitstreamFilter, ReadAhead, AVPacketWrapper, FFmpegFormatHelper, MultiStreamParser
tags: [demuxer, ffmpeg, plugin, av_read_frame, avformat, pipeline]
associations:
  - S41 (DemuxerFilter - Filter layer entry)
  - S68 (FFmpegDemuxerPlugin - same file, already exists)
  - S58 (MPEG4BoxParser - container format parsing)
  - S38 (SourcePlugin - source layer)
  - S69 (MediaDemuxer - engine core)
  - S75 (MediaDemuxer six-component architecture)
related_frontmatter:
  - MEM-ARCH-AVCODEC-007 (demuxer plugin overview, approved)
---

# S76：FFmpegDemuxerPlugin 音视频解封装插件——libavformat 封装与 av_read_frame 管线

> **草案状态**: draft
> **生成时间**: 2026-05-03T07:19+08:00
> **scope**: AVCodec, MediaEngine, Demuxer, FFmpeg, Plugin, FFmpegDemuxerPlugin, libavformat, av_read_frame, av_seek_frame, BitstreamFilter, AVPacketWrapper
> **关联场景**: 新需求开发 / 问题定位

---

## 1. 概述

**FFmpegDemuxerPlugin** 是 OpenHarmony AVCodec 模块的 **FFmpeg 解封装插件**，位于 `services/media_engine/plugins/demuxer/ffmpeg_demuxer/ffmpeg_demuxer_plugin.cpp`，共 **4129 行**。

该插件继承 `DemuxerPlugin` 基类，封装 FFmpeg libavformat 的核心 API（`avformat_open_input` / `av_read_frame` / `av_seek_frame`），支持 **25+ 种容器格式**（FLV/MKV/MPEGTS/MPEGPS/RM/WMV/OGG/MP3 等），是 OpenHarmony 媒体引擎中最通用的解封装插件。

**定位**：S76 为 FFmpegDemuxerPlugin 引擎层深度分析，对应 S68（草案已生成但文件状态为 draft）；S41 为 Filter 层封装入口。

---

## 2. 架构总览

```
FFmpegDemuxerPlugin (4129行 .cpp + .h)
        │
        ├── libavformat (FFmpeg C库)
        │     ├── avformat_open_input()     ─── 打开输入容器
        │     ├── av_read_frame()           ─── 按帧读取音视频包
        │     ├── av_seek_frame()           ─── 时间戳Seek
        │     └── avformat_close_input()   ─── 关闭输入
        │
        ├── FFmpegDemuxerThread (895行)     ─── 异步读线程
        │     ├── AVReadPacket()            ─── DataSource 拉取回调
        │     ├── ReadAhead 缓冲            ─── SOFT_LIMIT/HARD_LIMIT
        │     └── isPauseReadPacket_        ─── 暂停标志
        │
        ├── FFmpegFormatHelper (1367行)     ─── FFmpeg ↔ OpenHarmony 类型转换
        │     ├── GetFileTypeByName()       ─── 文件类型识别
        │     ├── ConvertFormatParams()     ─── 格式参数转换
        │     └── 25+ 容器格式支持
        │
        ├── MultiStreamParserManager        ─── 多轨解析器管理
        │     └── MPEG4/TS/H264/HEVC 各格式专用 Parser
        │
        └── BitstreamFilter 注入           ─── h264_mp4toannexb / hevc_mp4toannexb
              (Annex B 转换)
```

---

## 3. 核心数据结构

### 3.1 FFmpegDemuxerPlugin 类（DemuxerPlugin 子类）

| 关键成员 | 类型 | 用途 |
|---------|------|------|
| `formatContext_` | `std::shared_ptr<AVFormatContext>` | FFmpeg 格式上下文，持有所有流信息 |
| `ioContext_` | `IOContext` | 自定义 I/O 上下文，桥接 DataSource |
| `streamParsers_` | `MultiStreamParserManager*` | 多轨解析器管理器 |
| `seekable_` | `Plugins::Seekable` | 文件是否支持 Seek |
| `seekTime_` | `int64_t` | 当前 Seek 时间戳 |
| `seekMode_` | `SeekMode` | Seek 模式（PREVIOUS/NEXT/CLOSEST_SYNC）|
| `isWriteHeader_` | `bool` | 是否已写入容器头 |
| `isPauseReadPacket_` | `std::atomic<bool>` | 异步读线程暂停标志 |
| `cacheQueue_` | `BlockQueue<AVPacketWrapper>` | 读线程缓冲队列 |

**g_seekModeToFFmpegSeekFlags** 常量映射（ffmpeg_demuxer_plugin.cpp:162）：
```cpp
{ SeekMode::SEEK_PREVIOUS_SYNC, AVSEEK_FLAG_BACKWARD },
{ SeekMode::SEEK_NEXT_SYNC, AVSEEK_FLAG_FRAME },
{ SeekMode::SEEK_CLOSEST_SYNC, AVSEEK_FLAG_FRAME | AVSEEK_FLAG_BACKWARD }
```

### 3.2 IOContext 自定义 I/O

| 字段 | 类型 | 用途 |
|------|------|------|
| `dataSource` | `DataSource*` | 数据源（File/HTTP/DASH） |
| `avioContext` | `AVIOContext*` | FFmpeg 自定义 I/O 上下文 |
| `avReadPacketStopState` | `atomic<AVReadPacketStopState>` | 读线程停止状态控制 |
| `readStartTimeMs` | `int64_t` | 读开始时间（超时监控） |
| `readTimeoutMs` | `atomic<int32_t>` | 读超时阈值 |

### 3.3 AVPacketWrapper

| 字段 | 类型 | 用途 |
|------|------|------|
| `pkt_` | `AVPacket*` | FFmpeg AVPacket |
| `pts_` / `dts_` | `int64_t` | PTS/DTS（微秒） |
| `trackId_` | `uint32_t` | 轨道 ID |
| `GetAVPacket()` | `AVPacket*` | 获取底层 FFmpeg Packet |
| `GetPts()` / `GetDts()` | `int64_t` | 获取时间戳 |

### 3.4 ReadAhead 缓冲

| 常量 | 值 | 用途 |
|------|-----|------|
| `DEFAULT_CACHE_LIMIT` | 50×1024×1024 | 50MB 硬限制 |
| `SOFT_LIMIT_MULTIPLIER` | 2 | 软限制倍率 |
| `HARD_LIMIT_MULTIPLIER` | 4 | 硬限制倍率 |
| `DEFAULT_READ_SIZE` | 4096 | 默认读块大小 |
| `DEFAULT_SNIFF_SIZE` | 4096×4 | 媒体类型嗅探大小 |
| `LIVE_FLV_PROBE_SIZE` | 100×1024×2 | 直播 FLV 快速探测 |
| `RANK_MAX` | 100 | 插件优先级最高值 |

---

## 4. 关键代码路径 / Evidence

### 4.1 初始化路径（SetDataSource → Prepare）

**ffmpeg_demuxer_plugin.cpp:1492**：
```cpp
int ret = avformat_open_input(&formatContext, nullptr, pluginImpl.get(), options);
MEDIA_LOG_E("Call avformat_open_input failed by " PUBLIC_LOG_S ", err:" PUBLIC_LOG_S,
             pluginName_.c_str(), av_err2str(ret));
```

**ffmpeg_demuxer_plugin.cpp:1588-1589**：
```cpp
seekable_ = ioContext_.dataSource->IsDash() ? Plugins::Seekable::UNSEEKABLE : source->GetSeekable();
if (seekable_ == Plugins::Seekable::SEEKABLE) {
    // 初始化 Seek 上下文
}
```

**ffmpeg_demuxer_plugin.cpp:1638**：
```cpp
fileType_ = FFmpegFormatHelper::GetFileTypeByName(*formatContext_);
```

### 4.2 读帧路径（ReadSample）

**ffmpeg_demuxer_plugin.cpp:3215**（主入口）：
```cpp
Status FFmpegDemuxerPlugin::ReadSample(uint32_t trackId, std::shared_ptr<AVBuffer> sample)
{
    MediaAVCodec::AVCodecTrace trace(std::string("ReadSample_") + std::to_string(trackId));
    // ...
}
```

**ffmpeg_demuxer_plugin.cpp:1250-1254**（FFmpeg 读帧）：
```cpp
return av_read_frame(formatContext_.get(), pkt);
// ...
int ffmpegRet = av_read_frame(formatContext_.get(), pkt);
MEDIA_LOG_E("Call av_read_frame failed:" PUBLIC_LOG_S ", retry: " PUBLIC_LOG_D32,
             av_err2str(ffmpegRet), retryCnt);
```

**ffmpeg_demuxer_plugin.cpp:2484**（错误处理）：
```cpp
FALSE_RETURN_V_MSG_E(ffmpegRet >= 0, ret, "Call av_read_frame failed, ret:" PUBLIC_LOG_D32, ffmpegRet);
```

### 4.3 异步读线程（FFmpegDemuxerThread）

**ffmpeg_demuxer_thread.cpp:71**（AVReadPacket 回调）：
```cpp
int FFmpegDemuxerPlugin::AVReadPacket(void* opaque, uint8_t* buf, int bufSize)
{
    MediaAVCodec::AVCodecTrace trace("AVReadPacket_ReadAt");
    // 通过 ioContext_ 调用 DataSource->ReadAt()
    auto ret = ioContext->dataSource->ReadAt(fileOffset, buf, bufSize);
    // ...
}
```

**ffmpeg_demuxer_thread.cpp:698**（停止状态控制）：
```cpp
Status FFmpegDemuxerPlugin::SetAVReadPacketStopState(bool state)
{
    ioContext_.avReadPacketStopState.store(state ? AVReadPacketStopState::TRUE : AVReadPacketStopState::FALSE);
}
```

**ffmpeg_demuxer_thread.cpp:228**（恢复读）：
```cpp
isPauseReadPacket_.store(false);
```

### 4.4 Seek 路径（DoSeekInternal）

**ffmpeg_demuxer_plugin.cpp:2847-2852**：
```cpp
Status FFmpegDemuxerPlugin::DoSeekInternal(int trackIndex, int64_t seekTime, int64_t ffTime,
    SeekMode mode, int64_t& realSeekTime)
{
    realSeekTime = ConvertTimeFromFFmpeg(ffTime, avStream->time_base);
    // 调用 av_seek_frame() 或 SyncSeekThread()
}
```

**ffmpeg_demuxer_plugin.cpp:2828**（同步 Seek 通知读线程）：
```cpp
void FFmpegDemuxerPlugin::SyncSeekThread()
{
    MEDIA_LOG_I("Seek notify read thread to stop");
}
```

### 4.5 BitstreamFilter 注入

**ffmpeg_demuxer_plugin.cpp:2100**：
```cpp
if (!streamParsers_->ParserIsInited(avStream.index)) {
    // 注入 h264_mp4toannexb / hevc_mp4toannexb BitstreamFilter
    // 将 MP4 风格的 NALU 起始码转换为 Annex B 格式
}
```

### 4.6 FLV 直播流特殊处理

**ffmpeg_demuxer_plugin.cpp:1508**：
```cpp
if (FFmpegFormatHelper::GetFileTypeByName(*formatContext) == FileType::FLV) {
    // Fix init live-flv-source too slow
    // 直播 FLV 跳过预读，LIVE_FLV_PROBE_SIZE=100KB×2 快速探测
}
```

**ffmpeg_demuxer_plugin.cpp:461**：
```cpp
static bool IsEnableSeekTimeCalib(const std::shared_ptr<AVFormatContext> &formatContext)
{
    // FLV 直播流禁用 Seek 校准
}
```

### 4.7 容器格式支持（FFmpegFormatHelper）

FFmpegFormatHelper.cpp 支持 25+ 容器格式，包括：
- **视频**：FLV, MKV, MPEGTS, MPEGPS, RM, WMV, AVI, MOV/MP4, OGG, WebM
- **音频**：MP3, AAC, OGG, FLAC, WAV, AMR, WMA
- **流媒体**：HLS (m3u8), DASH (mpd), HTTP 自适应流

**ffmpeg_demuxer_plugin.cpp:162-164**（Seek 模式映射）：
```cpp
static const std::map<SeekMode, int32_t> g_seekModeToFFmpegSeekFlags = {
    { SeekMode::SEEK_PREVIOUS_SYNC, AVSEEK_FLAG_BACKWARD },
    { SeekMode::SEEK_NEXT_SYNC, AVSEEK_FLAG_FRAME },
    { SeekMode::SEEK_CLOSEST_SYNC, AVSEEK_FLAG_FRAME | AVSEEK_FLAG_BACKWARD }
};
```

---

## 5. PTS 与索引转换

**ffmpeg_demuxer_plugin.cpp:3306-3331**：
```cpp
void FFmpegDemuxerPlugin::InitPTSandIndexConvert()
{
    // 初始化 PTS ↔ Index 转换器，支持 MP4 STTS/CTTS 表
}
```

**ffmpeg_demuxer_plugin.cpp:3331**：
```cpp
InitPTSandIndexConvert();
// 在 Prepare / GetMediaInfo 阶段调用
```

---

## 6. 多轨解析器（MultiStreamParserManager）

| Parser 类型 | 用途 |
|-----------|------|
| `MPEG4StreamParser` | MP4/MOV 容器，解析 stbl/stsc/stsz/stco |
| `TSStreamParser` | MPEG-TS 容器，解析 PAT/PMT |
| `H264StreamParser` | H.264 裸流，解析 SPS/PPS |
| `HEVCStreamParser` | HEVC 裸流，解析 VPS/SPS/PPS |
| `ADTSStreamParser` | AAC 音频，解析 ADTS 头 |

**ffmpeg_demuxer_plugin.cpp:1768**：
```cpp
void FFmpegDemuxerPlugin::InitParser()
{
    for (size_t trackIndex = 0; trackIndex < formatContext_->nb_streams; ++trackIndex) {
        if (!streamParsers_->ParserIsInited(trackIndex)) {
            MEDIA_LOG_W("Init failed");
        }
    }
}
```

---

## 7. 与其他模块的关系

| 上下游模块 | 调用关系 |
|-----------|---------|
| **DataSource** | FFmpegDemuxerPlugin 通过 IOContext → DataSource → SourcePlugin 获取数据 |
| **MediaDemuxer** | MediaDemuxer 持有 FFmpegDemuxerPlugin 实例，调用 ReadSample/GetMediaInfo |
| **DemuxerPluginManager** | DemuxerPluginManager 负责 Sniffer 路由，匹配到 FFmpegDemuxerPlugin |
| **DemuxerFilter** | Filter 层封装，调用 MediaDemuxer → FFmpegDemuxerPlugin |
| **BitstreamFilter** | h264_mp4toannexb / hevc_mp4toannexb 注入 MP4→AnnexB 转换 |
| **FFmpegMuxerPlugin** | 同为 FFmpeg 封装，Muxer 侧对应插件 |

---

## 8. 关键文件清单

| 文件 | 行数 | 用途 |
|------|------|------|
| `ffmpeg_demuxer_plugin.cpp` | 4129 | FFmpeg 解封装插件主实现 |
| `ffmpeg_demuxer_plugin.h` | ~250 | 类定义、DemuxerPlugin 子类 |
| `ffmpeg_demuxer_thread.cpp` | 895 | 异步读线程 AVReadPacket 回调 |
| `ffmpeg_format_helper.cpp` | 1367 | FFmpeg ↔ OpenHarmony 类型转换 |
| `ffmpeg_utils.cpp` | ~400 | FFmpeg 工具函数（错误码转换等） |
| `ffmpeg_reference_parser.cpp` | ~300 | 参考帧解析器 |
| `ffmpeg_demuxer_register.cpp` | ~200 | 插件注册（CRTP 静态注册） |

---

## 9. 总结

**FFmpegDemuxerPlugin** 是 AVCodec 模块最核心的解封装插件，通过封装 FFmpeg libavformat 实现了对 25+ 种容器格式的统一解封装支持。其架构特点：

1. **libavformat 三函数管线**：`avformat_open_input` → `av_read_frame` → `av_seek_frame`
2. **自定义 I/O 上下文（IOContext）**：桥接 DataSource 与 FFmpeg AVIOContext，支持 File/HTTP/DASH 数据源
3. **异步读线程（FFmpegDemuxerThread）**：独立 TaskThread 执行 AVReadPacket，通过 cacheQueue_ 缓冲包
4. **MultiStreamParserManager**：为每个轨道创建专用 Parser（H264/HEVC/MPEG4/ADTS）
5. **BitstreamFilter 注入**：自动注入 h264_mp4toannexb / hevc_mp4toannexb 做 Annex B 转换
6. **Seek 校准**：直播 FLV 禁用 Seek，MPEGTS/通用三分支策略
7. **ReadAhead 缓冲**：SOFT_LIMIT/HARD_LIMIT 双水位线流控
