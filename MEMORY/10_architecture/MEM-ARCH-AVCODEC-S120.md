# MEM-ARCH-AVCODEC-S120

> **主题**: MediaEngine Source 模块流媒体基础设施——Streaming 协议路由 / Plugin 管理 / HLS 分片下载 / Buffering 策略  
> **scope**: AVCodec, MediaEngine, Source, Streaming, Protocol, HLS, AdaptiveBitrate, Buffering  
> **关联场景**: 新需求开发 / 问题定位 / 流媒体播放 / HLS 自适应码率  
> **状态**: ⏳ pending_approval (待耀耀审批)  
> **备注**: 对 S106 的补充，S106 重点在 Source.cpp，M3U8 解析、HLS 下载；S120 聚焦 HTTP Source 插件路由、协议推断、Streaming 分片管理

---

## 1. 架构定位

Source 模块位于 MediaEngine 最上游，负责将外部 URI（http/https/file/fd/stream）转换为插件化的数据源，对接下游 DemuxerFilter 进行解封装。

```
URI 输入
  └─ Source::SetSource()
       └─ FindPlugin() → PluginManagerV2::CreatePluginByMime(protocol_)
            ├─ http/https  → HttpSourcePlugin（HLS/DASH 分片下载）
            ├─ file        → FileSourcePlugin
            ├─ fd          → FdSourcePlugin
            └─ stream      → StreamSourcePlugin
       └─ plugin_->Init() → plugin_->SetSource() → plugin_->Prepare()
```

---

## 2. 核心源码证据（本地镜像）

### 2.1 Source 入口类（source.h: 184行，source.cpp: 715行）

| 行号 | 关键成员 | 类型 |
|------|---------|------|
| source.h:88 | `std::shared_ptr<Plugins::SourcePlugin> plugin_` | 插件实例 |
| source.h:89 | `std::shared_ptr<Plugins::PluginInfo> pluginInfo_` | 插件元信息 |
| source.h:90 | `bool isPluginReady_ {false}` | 就绪标志 |
| source.h:94 | `std::shared_ptr<CallbackImpl> mediaDemuxerCallback_` | Demuxer 回调桥接 |
| source.h:97 | `std::string protocol_` | 协议字符串（http/https/file/fd/stream） |
| source.cpp:564-582 | `Source::FindPlugin()` | 协议解析→插件发现核心函数 |

**source.cpp:564-582** FindPlugin 实现：
```cpp
Status Source::FindPlugin(const std::shared_ptr<MediaSource>& source)
{
    MediaAVCodec::AVCodecTrace trace("Source::FindPlugin");
    if (!ParseProtocol(source)) {  // 从 URI 提取协议
        MEDIA_LOG_E("Invalid source!");
        return Status::ERROR_INVALID_PARAMETER;
    }
    if (protocol_.empty()) {
        MEDIA_LOG_E("protocol_ is empty");
        return Status::ERROR_INVALID_PARAMETER;
    }
    // 关键：PluginManagerV2 工厂分发协议插件
    auto plugin = Plugins::PluginManagerV2::Instance().CreatePluginByMime(
        Plugins::PluginType::SOURCE, protocol_);
    if (plugin != nullptr) {
        plugin_ = std::static_pointer_cast<SourcePlugin>(plugin);
        plugin_->SetInterruptState(isInterruptNeeded_);
        return Status::OK;
    }
    MEDIA_LOG_E("Cannot find any plugin");
    return Status::ERROR_UNSUPPORTED_FORMAT;
}
```

### 2.2 协议路由表（source.cpp:38-43）

```cpp
static std::map<std::string, ProtocolType> g_protocolStringToType = {
    {"http", ProtocolType::HTTP},
    {"https", ProtocolType::HTTPS},
    {"file", ProtocolType::FILE},
    {"stream", ProtocolType::STREAM},
    {"fd", ProtocolType::FD}
};
```

### 2.3 HLS 事件回调（source.cpp:378-384）

```cpp
} else if (event.type == PluginEventType::DASH_SEEK_READY) {
    // DASH 定位完成回调
} else if (event.type == PluginEventType::HLS_SEEK_READY) {
    // HLS 定位完成回调
}
```

### 2.4 HLS 下载器（hls_media_downloader.h / .cpp: 704行）

| 关键类 | 职责 | 证据 |
|--------|------|------|
| `HlsMediaDownloader` | M3U8 playlist 下载、分片依次请求 | hls_media_downloader.cpp:704行 |
| `HlsPlaylistDownloader` | Master playlist / Variant stream 切换 | hls_playlist_downloader.h |
| `HlsSegmentManager` | 分片缓存管理、Bitrate 自适应切换 | hls_segment_manager.cpp:2582行 |

**HlsMediaDownloader 核心接口**：
- `DownloadPlaylist()` → 获取 m3u8
- `GetNextSegment()` → 获取下一分片 URL
- `SelectBitRate(uint32_t bitRate)` → 码率切换

### 2.5 M3U8 解析器（m3u8.h / m3u8.cpp: 1435行）

| 行号 | 函数 | 功能 |
|------|------|------|
| m3u8.cpp:~1435行 | `ParseMasterPlaylist()` | 解析 #EXT-X-STREAM-INF 多码率列表 |
| m3u8.cpp | `ParseMediaPlaylist()` | 解析媒体播放列表（#EXTINF 分片） |
| m3u8.cpp | `GetTargetDuration()` | 获取 #EXT-X-TARGETDURATION |
| m3u8.cpp | `GetSegmentCount()` | 获取总片数 |

### 2.6 HTTP Source 下载器（downloader.h:83-196）

```cpp
enum class RequestProtocolType : int32_t {
    HTTP,
    HTTPS,
    // ...
};

void SetRequestProtocolType(RequestProtocolType protocolType);
RequestProtocolType protocolType_ {RequestProtocolType::HTTP};
```

---

## 3. 关键设计点

### 3.1 PluginManagerV2 工厂路由

Source 模块不直接创建插件，而是通过 `PluginManagerV2::Instance().CreatePluginByMime(PluginType::SOURCE, protocol_)` 按协议字符串查找注册插件：

- **http/https** → HttpSourcePlugin（HLS/DASH 自适应码率）
- **file** → FileSourcePlugin（本地文件）
- **fd** → FdSourcePlugin（文件描述符）
- **stream** → StreamSourcePlugin（流式数据）

### 3.2 HLS 自适应码率

HlsMediaDownloader 在下载过程中维护多码率分片列表，用户可通过 `SelectBitRate()` 切换码率档次。切换后 HlsSegmentManager 更新当前 SegManager 的目标 URL，重新下载。

### 3.3 分片缓冲策略

- `SetExtraCache(cacheDuration)` 设置额外缓存时长
- `WaitForBufferingEnd()` 等待初始缓冲完成
- `IsHlsEnd(streamId)` 判断 HLS 流结束

### 3.4 Seek 机制

HLS/DASH 流定位通过事件驱动：
- `PluginEventType::HLS_SEEK_READY` → HLS 定位完成
- `PluginEventType::DASH_SEEK_READY` → DASH 定位完成

Source 层在收到事件后通过 `seekCond_` 条件变量通知等待线程。

---

## 4. 关联记忆

| 关联 | 说明 |
|------|------|
| **S106** | Source 模块行号级 evidence（S106 已提交审批） |
| **S75** | HlsSegmentManager 分片管理 |
| **S37/S38** | SourcePlugin 接口定义 |
| **S41** | DemuxerFilter 接收 Source 数据流 |
| **S87** | HTTP Source 插件注册 |
| **S86** | Buffering 状态管理 |

---

## 5. 建设空白（未覆盖）

- [ ] AdaptiveBitrate 降码率算法细节（待补录）
- [ ] DASH 分片下载器具体实现（待补录）
- [ ] HttpSourcePlugin 内部 Retry 策略（待补录）

---

_Builder: draft 生成于 2026-05-13，基于本地镜像 /home/west/av_codec_repo_