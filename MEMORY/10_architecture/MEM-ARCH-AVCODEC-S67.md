---
id: MEM-ARCH-AVCODEC-S67
title: SourcePlugin 源插件体系——File/HTTP/DataStream/Fd 四类协议与 MediaDownloader 分层架构
type: architecture_fact
scope: [AVCodec, MediaEngine, SourcePlugin, ProtocolType, FileSource, HttpSource, DataStreamSource, FileFdSource, Plugin, HLS, DASH, Rank]
status: pending_approval
confidence: high
created_by: builder-agent
created_at: "2026-04-27T08:21:00+08:00"
updated_at: "2026-05-03T14:20:00+08:00"
approved_by: null
service_scenario: 新需求开发/问题定位
summary: >
  S67 梳理 SourcePlugin 源插件体系，它是 Filter Pipeline 最上游的数据入口。
  四类源插件均实现 Plugins::SourcePlugin 接口（SetSource/Read/GetSize）。
  FileSourcePlugin（ProtocolType::FILE）、FileFdSourcePlugin（ProtocolType::FD，rank=100 最高优先级，40MB RingBuffer 云端预读）、
  HttpSourcePlugin（ProtocolType::HTTP，内部通过 CheckIsM3U8Uri() 路由到 HlsMediaDownloader/DashMediaDownloader/DownloadMonitor）、
  DataStreamSourcePlugin（ProtocolType::STREAM，AVSharedMemoryPool 内存池）。
  PluginType::SOURCE 是所有源插件的共同类型。FileFdSource rank=100 是所有源插件中最高优先级。
  与 DemuxerFilter(S41) 下游衔接，构成播放管线数据入口。
why_it_matters:
 - Filter Pipeline 最上游入口：理解数据从网络/文件到 Filter 的第一跳
 - HLS/DASH 自适应流：HttpSourcePlugin 内部路由机制是直播/点播场景的核心
 - rank 优先级：多协议竞争时的插件选择策略，rank 越大优先级越高
 - 云端预读：FileFdSource 的 40MB RingBuffer 是远程文件读取性能关键
evidence:
 # --- SourcePlugin 基类接口（interfaces/plugin/source_plugin.h）---
 - kind: code
   ref: interfaces/plugin/source_plugin.h
   anchor: Line 399: pluginType = PluginType::SOURCE
   note: 所有源插件必须声明 pluginType = PluginType::SOURCE

 - kind: code
   ref: interfaces/plugin/source_plugin.h
   anchor: Line 125: virtual Status SetSource(std::shared_ptr<MediaSource> source) = 0
   note: SourcePlugin 三函数接口之一：SetSource（设置数据源 URI）

 - kind: code
   ref: interfaces/plugin/source_plugin.h
   anchor: Line 398-405: class SourcePlugin Definition 结构体
   note: |
     apiVersion = SOURCE_API_VERSION（版本1.0）
     pluginType = PluginType::SOURCE（强制声明）
     rank = 0（默认优先级，可被插件覆盖）

 # --- FileFdSourcePlugin（最高优先级，40MB RingBuffer 云端预读）---
 - kind: code
   ref: services/media_engine/plugins/source/file_fd_source_plugin.cpp
   anchor: Line 92: constexpr int32_t MAX_RANK = 100
   note: rank=100 是所有 SourcePlugin 中最高优先级

 - kind: code
   ref: services/media_engine/plugins/source/file_fd_source_plugin.cpp
   anchor: Line 131: definition.rank = MAX_RANK; // 100: max rank
   note: FileFdSource 注册时设置 rank=100

 - kind: code
   ref: services/media_engine/plugins/source/file_fd_source_plugin.cpp
   anchor: Line 80: constexpr size_t CACHE_SIZE = 40 * 1024 * 1024
   note: RingBuffer 云端预读缓存大小 = 40MB

 - kind: code
   ref: services/media_engine/plugins/source/file_fd_source_plugin.cpp
   anchor: Line 177: ringBuffer_ = std::make_shared<RingBuffer>(CACHE_SIZE)
   note: 构造函数中初始化 40MB RingBuffer

 - kind: code
   ref: services/media_engine/plugins/source/file_fd_source_plugin.cpp
   anchor: Line 133: capability.AppendFixedKey<std::vector<ProtocolType>>(Tag::MEDIA_PROTOCOL_TYPE, {ProtocolType::FD})
   note: FileFdSource 声明协议类型 ProtocolType::FD

 - kind: code
   ref: services/media_engine/plugins/source/file_fd_source_plugin.cpp
   anchor: Line 206: ReadOnlineFile vs ReadOfflineFile 分支
   note: 云端文件（ReadOnlineFile）与本地文件（ReadOfflineFile）双分支读取路径

 - kind: code
   ref: services/media_engine/plugins/source/file_fd_source_plugin.cpp
   anchor: Line 261: isReadBlocking_ 云端预读阻塞标志
   note: 云端预读时设置 isReadBlocking_ 阻塞读标志

 # --- FileSourcePlugin（本地文件，ProtocolType::FILE）---
 - kind: code
   ref: services/media_engine/plugins/source/file_source_plugin.cpp
   anchor: Line 56: capability.AppendFixedKey<std::vector<ProtocolType>>(Tag::MEDIA_PROTOCOL_TYPE, {ProtocolType::FILE})
   note: FileSource 声明协议类型 ProtocolType::FILE

 # --- HttpSourcePlugin（HLS/DASH 自适应流，ProtocolType::HTTP）---
 - kind: code
   ref: services/media_engine/plugins/source/http_source/http_source_plugin.cpp
   anchor: Line 37: const std::string LOWER_M3U8 = "m3u8"
   note: m3u8 小写字符串常量，用于 HLS 检测

 - kind: code
   ref: services/media_engine/plugins/source/http_source/http_source_plugin.cpp
   anchor: Line 100: std::shared_ptr<MediaDownloader> downloader_
   note: HttpSourcePlugin 持有 MediaDownloader 基类指针

 - kind: code
   ref: services/media_engine/plugins/source/http_source/http_source_plugin.cpp
   anchor: Line 161/170: CheckIsM3U8Uri() m3u8 URI 检测
   note: Pause/Resume 时检查是否 M3U8 URI

 - kind: code
   ref: services/media_engine/plugins/source/http_source/http_source_plugin.cpp
   anchor: Line 287-311: SetDownloaderBySource() 三路分发
   note: |
     Line 287-291: IsDash() → DashMediaDownloader
     Line 298-311: CheckIsM3U8Uri() → HlsMediaDownloader : DownloadMonitor

 - kind: code
   ref: services/media_engine/plugins/source/http_source/http_source_plugin.cpp
   anchor: Line 645-669: CheckIsM3U8Uri() 实现
   note: 三种检测方式（suffix == m3u8 / uri contains m3u8 / pairUri contains m3u8=）

 - kind: code
   ref: services/media_engine/plugins/source/http_source/hls/hls_media_downloader.h
   anchor: Line 45: HlsMediaDownloader 继承 MediaDownloader + enable_shared_from_this
   note: HLS 下载器基类

 - kind: code
   ref: services/media_engine/plugins/source/http_source/hls/hls_media_downloader.h
   anchor: Line 113-115: videoSegManager_/audioSegManager_/subtitlesSegManager_ 三轨分片管理
   note: HlsMediaDownloader 三轨（video/audio/subtitle）SegmentManager

 - kind: code
   ref: services/media_engine/plugins/source/http_source/
   anchor: hls/ 和 dash/ 子目录结构
   note: |
     hls/: hls_media_downloader.cpp/h, hls_segment_manager.cpp/h, m3u8.cpp/h, hls_tags.cpp/h, playlist_downloader.cpp/h
     dash/: dash_media_downloader.cpp/h, dash_mpd_downloader.cpp/h, dash_segment_downloader.cpp/h, mpd_parser/

 # --- DataStreamSourcePlugin（AVSharedMemoryPool 内存池，ProtocolType::STREAM）---
 - kind: code
   ref: services/media_engine/plugins/source/data_stream_source_plugin.h
   anchor: Line 22: #include "common/avsharedmemorypool.h"
   note: 引入 AVSharedMemoryPool 内存池

 - kind: code
   ref: services/media_engine/plugins/source/data_stream_source_plugin.h
   anchor: Line 61: std::shared_ptr<AVSharedMemoryPool> pool_
   note: DataStreamSourcePlugin 持有 AVSharedMemoryPool 内存池

 - kind: code
   ref: services/media_engine/plugins/source/data_stream_source_plugin.cpp
   anchor: Line 68: pool_ = std::make_shared<AVSharedMemoryPool>("pool")
   note: 构造函数中创建 AVSharedMemoryPool 实例

 - kind: code
   ref: services/media_engine/plugins/source/data_stream_source_plugin.cpp
   anchor: Line 62: PLUGIN_DEFINITION(DataStream, Plugins::LicenseType::APACHE_V2, DataStreamSourceRegister, [] {})
   note: DataStreamSource 插件注册宏

 # --- 下游衔接 DemuxerFilter ---
 - kind: code
   ref: services/media_engine/filters/demuxer_filter.cpp
   anchor: Line 50: builtin.player.demuxer 注册
   note: DemuxerFilter 注册名 "builtin.player.demuxer"，FilterType::FILTERTYPE_DEMUXER

key_findings:
 - 'PluginType::SOURCE: 所有源插件的共同类型，所有插件必须声明 pluginType = PluginType::SOURCE'
 - 'rank=100: FileFdSource 是所有源插件中最高优先级'
 - '40MB RingBuffer: FileFdSource 云端预读缓存大小（CACHE_SIZE = 40 * 1024 * 1024）'
 - 'HttpSourcePlugin 三路分发: IsDash() → DashMediaDownloader / CheckIsM3U8Uri() → HlsMediaDownloader / else → DownloadMonitor'
 - 'HlsMediaDownloader 三轨: videoSegManager_/audioSegManager_/subtitlesSegManager_'
 - 'ProtocolType 四类: FILE/FD/HTTP/STREAM'
 - 'AVSharedMemoryPool: DataStreamSource 内存池（pool_ = make_shared<AVSharedMemoryPool>("pool")）'
 - 'Filter Pipeline: SourcePlugin → DemuxerFilter → DecoderFilter'
related:
 - MEM-ARCH-AVCODEC-S41  # DemuxerFilter 下游衔接
 - MEM-ARCH-AVCODEC-S37  # HTTP 流媒体源插件架构
 - MEM-ARCH-AVCODEC-S58  # MPEG4BoxParser 容器解析（与 SourcePlugin 互补）
 - MEM-ARCH-AVCODEC-S66  # TypeFinder 媒体类型探测（SourcePlugin 数据源嗅探）
owner: builder-agent
review:
  owner: 耀耀
  change_policy: manual_review
update_trigger: 新增 SourcePlugin 类型 / HTTP 下载架构变更
notes: |
  S67 基于本地代码镜像 /home/west/.openclaw/workspace-main/avcodec-dfx-memory/repo_tmp 验证。
  所有 evidence 均包含真实文件路径和行号。
  与 S37/S38 有主题重叠（S37/S38 均为 draft），建议以 S67 为准（已包含详细源码证据）。