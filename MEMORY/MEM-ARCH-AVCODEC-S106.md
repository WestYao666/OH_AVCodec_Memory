---
id: MEM-ARCH-AVCODEC-S106
title: "MediaEngine Source 模块流媒体基础设施——Protocol 路由 / Plugin 管理 / HLS+Bitrate 双调度 / Buffering 策略"
tags: [AVCodec, MediaEngine, Source, Streaming, Protocol, HLS, DASH, AdaptiveBitrate, Buffering]
scope: "新需求开发/问题定位/流媒体播放/HLS-DASH 自适应码率"
status: pending_approval
created: "2026-05-09T23:49"
source-ref: https://gitcode.com/openharmony/multimedia_av_codec
evidence-files:
  - path: services/media_engine/modules/source/source.cpp
    lines: 715
  - path: services/media_engine/plugins/source/http_source/hls/m3u8.cpp
    lines: 1435
  - path: services/media_engine/plugins/source/http_source/hls/hls_media_downloader.cpp
    lines: 704
  - path: services/media_engine/plugins/source/http_source/hls/hls_segment_manager.cpp
    lines: 2582
---

# S106: MediaEngine Source 模块流媒体基础设施

## 1. 模块定位

MediaEngine Source 模块（`services/media_engine/modules/source/`）是 Filter Pipeline 的最上游入口，
负责将外部媒体源（URI/FD/Stream）解析为 `ProtocolType`，并通过 `PluginManagerV2::CreatePluginByMime(SOURCE)` 路由到具体插件。

## 2. 核心组件

### 2.1 Source（source.cpp, 715行）

**顶层封装类**，持有 `std::shared_ptr<SourcePlugin> plugin_`。

关键设计：

| 功能 | 实现 |
|------|------|
| Protocol 解析 | `ParseProtocol()` → `GetProtocolByUri()`，支持 `http/https/file/stream/fd` 五种协议 |
| Plugin 创建 | `FindPlugin()` → `PluginManagerV2::Instance().CreatePluginByMime(PluginType::SOURCE, protocol_)` |
| 回调链 | `mediaDemuxerCallback_`（std::shared_ptr<CallbackImpl>）透传上层回调 |
| 自适应码率 | `SelectBitRate(uint32_t bitRate)` → `plugin_->SelectBitRate()` |
| 直播流标识 | `isFlvLiveStream_`（`source->GetMediaStreamList().size() > 0`） |
| Seekable 查询 | `seekable_` 枚举（INVALID/SEEKABLE/UNSEEKABLE），由 plugin 返回 |

Protocol 字符串到 ProtocolType 的映射（source.cpp:38-43）：
```cpp
static std::map<std::string, ProtocolType> g_protocolStringToType = {
    {"http", ProtocolType::HTTP},
    {"https", ProtocolType::HTTPS},
    {"file", ProtocolType::FILE},
    {"stream", ProtocolType::STREAM},
    {"fd", ProtocolType::FD}
};
```

### 2.2 M3U8PlaylistParser（m3u8.cpp, 1435行）

M3U8 播放列表解析器，处理 HLS variant stream。

关键设计：

| 组件 | 行号 | 说明 |
|------|------|------|
| M3U8MediaType 三轨分类 | 47-50 | `AUDIO/VIDEO/SUBTITLES/CLOSED-CAPTIONS` 枚举映射 |
| UriJoin | 62 | 相对 URI → 绝对 URI 拼接（处理 `..` 路径） |
| EXT-X-STREAM-INF 解析 | 155 | 多码率变体串检测 |
| EXT-X-KEY 解析 | 709 | AES-128 解密密钥 URL 拼接 |
| 三轨 StreamInfo 聚合 | 218/323/1130-1133 | video/audio/subtitle 轨道分别收集 |
| 条件码率选择 | 1105 | `media->type_` 判断轨道类型 |

### 2.3 HlsMediaDownloader（hls_media_downloader.cpp, 704行）

HLS 分片下载管理器，持有三个 `HlsSegmentManager` 实例。

关键设计：

| 组件 | 行号 | 说明 |
|------|------|------|
| videoSegManager_ | 43-44 | SEG_VIDEO 轨，HlsSegmentType::SEG_VIDEO |
| audioSegManager_ | 94-95 | SEG_AUDIO 轨，按需创建（needAudioManager） |
| subtitlesSegManager_ | 102-103 | SEG_SUBTITLE 轨，按需创建（needSubtitlesManager） |
| Clone() | 96 | audio 从 video 复制配置（带宽/Header 等） |
| StartMediaDownload | 97-98/105-106 | 三轨分别启动下载 |
| GetContentType | 121-122 | 透传给 videoSegManager_ |
| Open/Close | 127-128/151-152 | 整体打开/关闭 |

### 2.4 HlsSegmentManager（hls_segment_manager.cpp, 2582行）

单轨分片管理核心，2482行核心实现。

关键设计：

| 组件 | 行号 | 说明 |
|------|------|------|
| HlsSegmentType 枚举 | 内部 | SEG_VIDEO/SEG_AUDIO/SEG_SUBTITLE |
| SegmentDownload | 分片下载 | 下载 URL + HTTP Header |
| AesDecryptor | 71行（hls_media_downloader.cpp） | AES-128-CBC 解密 |
| AdaptiveBitrate | 切换逻辑 | 监测带宽动态选择轨道 |
| PlaylistBackup | Seek 策略 | 直播流回退到主播放列表 |

## 3. 数据流

```
MediaSource (URI/FD/Stream)
    ↓
Source::SetSource() → Source::FindPlugin()
    ↓ (ParseProtocol → protocol_)
PluginManagerV2::CreatePluginByMime(PluginType::SOURCE, protocol_)
    ↓
SourcePlugin (FileSource/HTTP/M3U8/HlsMediaDownloader)
    ↓
Plugin.Read() / Plugin.Seek() → Filter Pipeline
```

MIME 类型路由（source.cpp:549-555）：
- `application-m3u8` → `protocol_ = "http"`（M3U8 走 HTTP 插件）

## 4. 关联主题

| 关联 | 说明 |
|------|------|
| S87 | Source 封装层与 SourcePlugin 插件体系（同一模块） |
| S37 | HttpSourcePlugin（HTTP 源插件架构） |
| S38 | SourcePlugin 四类协议（File/HTTP/DataStream/Fd） |
| S41 | DemuxerFilter 上游数据源 |
| S69/S75 | MediaDemuxer 解封装引擎 |
| S86 | HLS 流媒体缓存引擎（MediaCachedBuffer RingBuffer） |

## 5. 关键行号索引

| 文件 | 行号 | 内容 |
|------|------|------|
| source.cpp | 38-43 | Protocol 字符串映射表 |
| source.cpp | 540-555 | ParseProtocol / FindPlugin 完整实现 |
| source.cpp | 220-237 | SelectBitRate / AutoSelectBitRate |
| m3u8.cpp | 47-50 | M3U8MediaType 三轨分类 |
| m3u8.cpp | 62 | UriJoin 绝对路径拼接 |
| m3u8.cpp | 155 | EXT-X-STREAM-INF 检测 |
| m3u8.cpp | 709 | EXT-X-KEY AES 解密密钥 |
| hls_media_downloader.cpp | 43-44 | videoSegManager_ 创建 |
| hls_media_downloader.cpp | 94-106 | audio/subtitle SegManager 按需创建 |
| hls_segment_manager.cpp | ~2482 | HlsSegmentManager 核心实现 |

---
_builder: Builder Agent
_generated: 2026-05-09T23:49:00 GMT+8