---
id: MEM-ARCH-AVCODEC-S67
title: SourcePlugin 源插件体系——File/HTTP/DataStream/Fd 四类协议与 MediaDownloader 分层架构
type: architecture_fact
scope: [AVCodec, MediaEngine, SourcePlugin, ProtocolType, FileSource, HttpSource, DataStreamSource, FileFdSource, Plugin, HLS, DASH, Rank]
status: draft
confidence: medium
created_by: builder-agent
created_at: "2026-04-27T08:21:00+08:00"
service_scenario: 新需求开发/问题定位
summary: >
  S67 梳理 SourcePlugin 源插件体系，它是 Filter Pipeline 最上游的数据入口。
  四类源插件（FileSource/FILE、FileFdSource/FD、HttpSourcePlugin/HTTP、DataStreamSource/STREAM），
  均实现 Plugins::SourcePlugin 接口（SetSource/Read/GetSize）。HTTP 源插件内部采用 MediaDownloader 分层架构：
  HlsMediaDownloader（HLS m3u8 路由，video/audio/subtitle 三轨 SegManager）、DashMediaDownloader（MPD 解析）。
  rank=100 是最高优先级，FileFdSource 使用 RingBuffer 40MB 云端预读，DataStreamSource 使用 AVSharedMemoryPool 内存池。
  与 DemuxerFilter(S41) 下游衔接，构成完整播放管线入口。
why_it_matters:
 - Filter Pipeline 最上游入口：理解数据从网络/文件到 Filter 的第一跳
 - HLS/DASH 自适应流：直播/点播场景的核心能力
 - rank 优先级：多协议竞争时的插件选择策略
evidence:
 - kind: code
   ref: services/media_engine/plugins/source/file_fd_source_plugin.cpp
   anchor: Line 92/131: MAX_RANK=100, definition.rank=MAX_RANK
   note: |
     Line 92: constexpr int32_t MAX_RANK = 100（最高优先级）
     Line 131: definition.rank = MAX_RANK（FileFdSource 注册 rank=100）
 - kind: code
   ref: services/media_engine/plugins/source/file_fd_source_plugin.cpp
   anchor: Line 144/167: FileFdSourcePlugin 核心函数
   note: |
     Line 144: FileFdSourcePlugin 构造函数
     Line 167: SetSource() 设置数据源 URI
     Line 197/202: Read() 方法重载（offset/expectedLen）
     Line 206: ReadOnlineFile vs ReadOfflineFile 分支
     Line 261: isReadBlocking_ 云端预读阻塞标志
 - kind: code
   ref: services/media_engine/plugins/source/file_fd_source_plugin.cpp
   anchor: Line 220-255: ReadOfflineFile/ReadOnlineFile
   note: |
     ReadOfflineFile: 本地文件读取，position_ 游标追踪
     ReadOnlineFile: 云端文件，支持 isReadBlocking_ 阻塞读
     HandleReadResult 处理 END_OF_STREAM
 - kind: code
   ref: services/media_engine/plugins/source/http_source/http_source_plugin.cpp
   anchor: Line 37/39/161/289-311: m3u8 路由判断逻辑
   note: |
     Line 37: const std::string LOWER_M3U8 = "m3u8"
     Line 39: EQUAL_M3U8 = "=" + LOWER_M3U8
     Line 161/170: CheckIsM3U8Uri() m3u8 URI 检测
     Line 289: DashMediaDownloader 路由条件
     Line 298-311: HlsMediaDownloader 或 DownloadMonitor 选择
 - kind: code
   ref: services/media_engine/plugins/source/http_source/http_source_plugin.cpp
   anchor: Line 645-669: CheckIsM3U8Uri 实现
   note: |
     suffix == LOWER_M3U8 或 uri 包含 m3u8 或 pairUri 包含 m3u8= 多种检测
 - kind: code
   ref: services/media_engine/plugins/source/http_source/hls/hls_media_downloader.h
   anchor: Line 45-115: HlsMediaDownloader 类定义
   note: |
     Line 45: HlsMediaDownloader 继承 MediaDownloader + enable_shared_from_this
     Line 108: GetSegmentManager(uint32_t streamId)
     Line 113-115: videoSegManager_/audioSegManager_/subtitlesSegManager_ 三轨分片管理
 - kind: code
   ref: services/media_engine/plugins/source/http_source/
   anchor: hls/ 和 dash/ 子目录结构
   note: |
     hls/: hls_media_downloader.cpp/h, hls_segment_manager.cpp/h, m3u8.cpp/h, hls_tags.cpp/h, playlist_downloader.cpp/h
     dash/: dash_media_downloader.cpp/h, dash_mpd_downloader.cpp/h, dash_segment_downloader.cpp/h, mpd_parser/
 - kind: code
   ref: services/media_engine/plugins/source/http_source/
   anchor: download/ 子目录结构
   note: |
     download/: downloader.cpp/h, media_source_loading_request.cpp/h, app_client.cpp/h, network_client/http_curl_client.cpp/h
 - kind: code
   ref: services/media_engine/plugins/source/data_stream_source_plugin.cpp
   anchor: DataStreamSourcePlugin 架构
   note: |
     DataStreamSourcePlugin 使用 AVSharedMemoryPool 内存池
     继承 Plugins::SourcePlugin，PluginType::SOURCE
 - kind: code
   ref: services/media_engine/plugins/source/file_source_plugin.cpp
   anchor: FileSourcePlugin 架构
   note: |
     FileSourcePlugin PluginType::SOURCE rank 优先级
     文件本地读取，SetSource/Read/GetSize 三函数
 - kind: code
   ref: services/media_engine/plugins/source/http_source/download/downloader.h
   anchor: MediaDownloader 分层架构
   note: |
     MediaDownloader 是 HTTP 下载的基类
     派生 HlsMediaDownloader（m3u8）、DashMediaDownloader（mpd）、DownloadMonitor（通用）
 - kind: code
   ref: services/media_engine/filters/demuxer_filter.cpp
   anchor: Line 50: builtin.player.demuxer 注册
   note: |
     DemuxerFilter 注册名 "builtin.player.demuxer"
     FilterType::FILTERTYPE_DEMUXER，下游衔接 SourcePlugin
key_findings:
 - 'PluginType::SOURCE: 所有源插件的共同类型'
 - 'FileFdSource rank=100: 最高优先级，云端预读 isReadBlocking_'
 - 'HttpSourcePlugin: m3u8 → HlsMediaDownloader / mpd → DashMediaDownloader / other → DownloadMonitor'
 - 'HlsMediaDownloader: 三轨 SegManager（video/audio/subtitle）'
 - 'SourcePlugin 统一接口: SetSource(source) / Read(buffer, offset, expectedLen) / GetSize()'
 - 'RingBuffer: FileFdSource 云端预读 40MB 环形缓冲（推测）'
 - 'AVSharedMemoryPool: DataStreamSource 内存池机制'
 - 'Filter Pipeline 上游: SourcePlugin → DemuxerFilter → DecoderFilter'
 - 'CheckIsM3U8Uri: 三种检测方式（suffix/uri contains/pairUri）'
related:
 - MEM-ARCH-AVCODEC-S41  # DemuxerFilter 下游衔接
 - MEM-ARCH-AVCODEC-S37  # HTTP 流媒体源插件（重复探索 S67）
 - MEM-ARCH-AVCODEC-S38  # SourcePlugin 源插件体系（草案，可能被 S67 覆盖）
 - MEM-ARCH-AVCODEC-S58  # MPEG4BoxParser 容器解析（与 SourcePlugin 互补）
 - MEM-ARCH-AVCODEC-S66  # TypeFinder 媒体类型探测（SourcePlugin 数据源嗅探）
owner: builder-agent
review:
  owner: 耀耀
  change_policy: manual_review
update_trigger: 新增 SourcePlugin 类型 / HTTP 下载架构变更
notes: |
  S67 与 S37/S38 存在主题重叠（S37 是草案，S38 是草案）。S67 基于本地代码验证，
  提供了 FileFdSource rank=100、HlsMediaDownloader 三轨 SegManager 等具体 evidence。
  建议合并或确认 S67 为独立主题。
---