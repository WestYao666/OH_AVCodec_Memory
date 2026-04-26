# MEM-ARCH-AVCODEC-S38

status: pending_approval
title: SourcePlugin 源插件体系——File/HTTP/DataStream/Fd 四类协议与 MediaDownloader 架构
scope: [AVCodec, MediaEngine, SourcePlugin, ProtocolType, FileSource, HttpSource, DataStreamSource, FileFdSource, Plugin, Rank]
pipeline_position: Filter Pipeline 最上游（数据源入口）
author: builder-agent
created_at: "2026-04-25T19:07:00+08:00"
evidence_count: 15

## 摘要
AVCodec 模块的 SourcePlugin 体系定义了统一的数据源抽象层，通过 ProtocolType（FILE/FD/HTTP/STREAM）区分四类来源：FileSource（本地文件）、FileFdSource（文件描述符，含云端预读缓冲）、HttpSourcePlugin（HTTP 流媒体，含 HLS/DASH 子插件）、DataStreamSource（数据流接口）。所有 SourcePlugin 均实现 SourcePlugin 接口（SetSource/Read/SeekToTime/GetSize），通过 Plugin 注册机制（definition.rank = 100）被 SourcePluginManager 统一调度。HttpSourcePlugin 内部通过 MediaDownloader 基类聚合 HlsMediaDownloader/DashMediaDownloader/DownloadMonitor 三种下载器。

## 架构要点
- **四类源插件**：FileSource（FILE）、FileFdSource（FD）、HttpSourcePlugin（HTTP）、DataStreamSource（STREAM），通过 ProtocolType 区分
- **rank=100 最高优先级**：所有源插件 rank 均设为 100（MAX_RANK），MediaEngine 按注册顺序选择第一个匹配的插件
- **统一接口**：SetSource(MediaSource) → Read(Buffer, offset, expectedLen) → GetSize/SeekToTime，SourcePlugin 是 Filter Pipeline 的最上游节点
- **HttpSourcePlugin 双层架构**：HttpSourcePlugin（入口路由） + MediaDownloader（HlsMediaDownloader/DashMediaDownloader/DownloadMonitor）
- **FileFdSource 云端预读**：FileFdSource 包含 ringBuffer_ 环形缓冲（40MB default）+ isReadBlocking_ 阻塞控制，支持 ReadOnlineFile/ReadOfflineFile 双路径
- **DataStreamSource 内存池**：DataStreamSourcePlugin 使用 AVSharedMemoryPool（初始 10 个 × 10KB）+ ReadAt(offset) / ReadAt(size) 两种读取重载

## 关键证据

| 证据 | 文件:行号 | 说明 |
|------|-----------|------|
| E1 | file_source_plugin.cpp:52-54 | 定义 FileSource，rank=100，ProtocolType=FILE |
| E2 | file_fd_source_plugin.cpp:129-133 | 定义 FileFdSource，rank=MAX_RANK，ProtocolType=FD |
| E3 | file_fd_source_plugin.cpp:81 | CACHE_SIZE = 40*1024*1024 默认环形缓冲大小 |
| E4 | file_fd_source_plugin.cpp:202-208 | ReadOnlineFile/ReadOfflineFile 双路径分支 |
| E5 | file_fd_source_plugin.cpp:255-261 | isReadBlocking_ 阻塞控制标志 |
| E6 | data_stream_source_plugin.cpp:51-56 | 定义 DataStreamSource，rank=100，ProtocolType=STREAM |
| E7 | data_stream_source_plugin.cpp:37 | INIT_MEM_CNT=10，MEM_SIZE=10240，MAX_MEM_CNT=10*1024 |
| E8 | data_stream_source_plugin.cpp:207-216 | ReadAt(offset)/ReadAt(size) 两种重载 |
| E9 | http_source_plugin.cpp:289-298 | 三种下载器创建路由（DASH/HTTP/HLS） |
| E10 | http_source_plugin.cpp:37-40 | LOWER_M3U8/DASH_SUFFIX 常量 |
| E11 | http_source_plugin.cpp:526-539 | SelectBitRate/AutoSelectBitRate 码率选择 |
| E12 | http_source_plugin.cpp:645-674 | CheckIsM3U8Uri() HLS URL 自动识别多策略 |
| E13 | media_downloader.h | MediaDownloader 基类定义（所有下载器继承） |
| E14 | hls_media_downloader.cpp:44-106 | HlsMediaDownloader 三轨初始化（video/audio/subtitle） |
| E15 | file_source_plugin.cpp:167-220 | FileSource Read + GetSize 实现 |

## 关键文件清单

```
services/media_engine/plugins/source/
├── file_source_plugin.cpp          # 本地文件（FILE协议）
├── file_source_plugin.h
├── file_fd_source_plugin.cpp       # 文件描述符（FD协议），含云端缓冲
├── file_fd_source_plugin.h
├── data_stream_source_plugin.cpp   # 数据流接口（STREAM协议）
├── data_stream_source_plugin.h
├── http_source/
│   ├── http_source_plugin.cpp      # HTTP统一入口（HTTP协议）
│   ├── http_source_plugin.h
│   ├── media_downloader.h           # MediaDownloader 基类
│   ├── hls/
│   │   ├── hls_media_downloader.cpp  # HLS下载器
│   │   ├── hls_segment_manager.cpp    # 分片管理
│   │   └── m3u8.cpp                  # M3U8解析器
│   ├── dash/
│   │   └── dash_media_downloader.cpp # DASH下载器
│   ├── http/
│   │   └── http_media_downloader.cpp # 普通HTTP下载器
│   └── monitor/
│       └── download_monitor.cpp      # DownloadMonitor（其他HTTP）
```

## SourcePlugin 接口契约

所有 SourcePlugin 必须实现以下方法（SourcePlugin 接口）：

```cpp
// 初始化
Status SetSource(std::shared_ptr<MediaSource> source);  // 设置媒体源
Status SetCallback(const std::shared_ptr<Callback>& cb); // 设置回调

// 读取
std::shared_ptr<Buffer> Read(std::shared_ptr<Buffer>& buffer, uint64_t offset, size_t expectedLen);
Status GetSize(uint64_t& size);
Seekable GetSeekable();  // 返回 SEEKABLE/UNSEEKABLE

// 搜索（可选）
Status SeekToTime(uint64_t timestampUs);
```

## 四类 SourcePlugin 特征对比

| 插件 | ProtocolType | seekable | 特殊机制 | 适用场景 |
|------|-------------|---------|---------|---------|
| FileSource | FILE | SEEKABLE | 直接读文件 | 本地文件播放 |
| FileFdSource | FD | SEEKABLE | ringBuffer_（40MB）、isReadBlocking_、ReadOnlineFile/ReadOfflineFile | 云端文件描述符播放 |
| DataStreamSource | STREAM | 取决于 dataSrc_ | AVSharedMemoryPool、ReadAt(offset/size) 双模式 | 数据流注入 |
| HttpSourcePlugin | HTTP | 取决于具体下载器 | HlsMediaDownloader / DashMediaDownloader | 网络流媒体 |

## 与 Filter Pipeline 的关系

SourcePlugin 是 Filter Pipeline 的最上游节点：

```
SourcePlugin（数据源）
  ├─ FileSource        → 本地文件 → DemuxerFilter
  ├─ FileFdSource      → 云端FD   → DemuxerFilter
  ├─ DataStreamSource  → 数据流   → DemuxerFilter
  └─ HttpSourcePlugin   → HTTP流  → Hls/DashMediaDownloader → RingBuffer → DemuxerFilter
```

DemuxerFilter 接收来自 SourcePlugin 的数据流，执行音视频解封装（已覆盖于 S14 Filter Chain）。

## 与现有 S 系列的关系

| 已有主题 | 与 S38 的关系 |
|---------|--------------|
| S14（Filter Chain） | SourcePlugin → DemuxerFilter → DecoderFilter 是 Filter Pipeline 的完整链路 |
| S37（HTTP 流媒体） | HttpSourcePlugin 是 S37 的技术子集，S37 重点在 HLS/DASH 内部实现 |
| S28（VideoCaptureFilter） | VideoCaptureFilter 是录制管线的数据源，与 SourcePlugin 是不同路径（采集 vs 播放） |
| S1（codec_server） | codec_server 加载 SourcePlugin 的时机在管线初始化阶段 |

## 关键行号锚点速查

| 描述 | 文件 | 行号 |
|------|------|------|
| FileSource 注册 | `file_source_plugin.cpp` | 52-56 |
| FileFdSource 注册 | `file_fd_source_plugin.cpp` | 129-133 |
| FileFdSource ringBuffer | `file_fd_source_plugin.cpp` | 81（CACHE_SIZE） |
| FileFdSource 双读模式 | `file_fd_source_plugin.cpp` | 202-208 |
| DataStreamSource 注册 | `data_stream_source_plugin.cpp` | 51-56 |
| DataStreamSource 内存池 | `data_stream_source_plugin.cpp` | 37（INIT_MEM_CNT） |
| HttpSourcePlugin 路由 | `http_source_plugin.cpp` | 289-298 |
| HttpSourcePlugin M3U8判断 | `http_source_plugin.cpp` | 645-674 |
| MediaDownloader 基类 | `media_downloader.h` | 基类定义 |