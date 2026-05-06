---
id: MEM-ARCH-AVCODEC-S87
title: "MediaSource 核心架构——Source 封装层与 SourcePlugin 插件体系"
scope: [AVCodec, MediaEngine, Source, SourcePlugin, ProtocolType, Protocol, PluginManagerV2, FilterPipeline, Read, Seekable]
status: approved
created_by: builder-agent
created_at: "2026-05-04T02:15:00+08:00"
approved_by: feishu-user:ou_60d8641be684f82e8d9cb84c3015dde7
approved_at: "2026-05-06"
---

# MEM-ARCH-AVCODEC-S87: MediaSource 核心架构——Source 封装层与 SourcePlugin 插件体系

## 1. 概述

`Source`（`services/media_engine/modules/source/source.cpp`，715行）是 OpenHarmony AVCodec 模块中**媒体源读取的顶层封装类**，对应 S38 所述 SourcePlugin 体系的** Filter Pipeline 最上游入口**。

`Source` 的核心职责：
1. 接收上层（Filter Pipeline / Player）传入的 `MediaSource` URI 或 fd
2. 根据协议类型（HTTP/HTTPS/FILE/FD/STREAM）路由到具体的 `SourcePlugin`
3. 通过统一的 `SourcePlugin` 接口暴露 Read/Seek/BitRate/SelectStream 等能力

**Source 与 SourcePlugin 的关系**：
- `Source`：封装层（Facade），负责协议解析、插件创建、生命周期管理
- `SourcePlugin`：插件接口抽象，具体的 FileSource / HttpSource / DataStreamSource / FileFdSource 各自实现

**关键文件路径锚点**：
```
services/media_engine/modules/source/source.cpp:1-715    // Source 主类（715行）
services/media_engine/modules/source/source.h:1-184      // Source 头文件（184行）
interfaces/plugin/source_plugin.h:95-326               // SourcePlugin 基接口（231行）
services/media_engine/plugins/source/file_source_plugin.h
services/media_engine/plugins/source/http_source/http_source_plugin.cpp
```

---

## 2. 核心架构

### 2.1 Source 类定位

`Source` 继承 `std::enable_shared_from_this<Source>` 并实现 `Plugins::Callback` 接口，作为 Filter Pipeline 数据流的**最上游起点**，其生命周期由 Player/Recorder Pipeline 统一管理。

```
Player Pipeline（最上游）
    │
    ▼
Source::SetSource(MediaSource)
    │
    ├─ ParseProtocol() → 解析协议类型（http/https/file/fd/stream）
    ├─ FindPlugin() → PluginManagerV2::CreatePluginByMime(SOURCE, protocol)
    │         │
    │         ▼
    │    SourcePlugin（具体插件实现）
    │         │
    │         ▼
    │    plugin_->Read() / plugin_->SeekToTime() / plugin_->SelectBitRate()
    │
    ▼
DemuxerFilter(S41) ← 消费 Source::Read() 返回的 Buffer
```

### 2.2 Source 生命周期（7步）

| 步骤 | 方法 | 说明 |
|------|------|------|
| 1 | `SetSource(MediaSource)` | 解析 URI/fd，调用 `FindPlugin()` 创建 `SourcePlugin` |
| 2 | `SetCallback(Callback)` | 设置数据流回调（传向 DemuxerFilter） |
| 3 | `Prepare()` | 调用 `plugin_->Prepare()` 初始化插件 |
| 4 | `Start()` | 调用 `plugin_->Start()` 启动读取循环 |
| 5 | `Read(streamID, Buffer)` | 核心读取接口，返回 `std::shared_ptr<Buffer>` |
| 6 | `SeekToTime(seekTime, mode)` | 流内 Seek（`GetSeekable()` 判定支持性） |
| 7 | `Stop()` / `Pause()` / `Resume()` | 停止/暂停/恢复 |

### 2.3 协议解析路径（source.cpp:522-567）

```cpp
// source.cpp:540-564
bool Source::ParseProtocol(const std::shared_ptr<MediaSource>& source)
{
    SourceType srcType = source->GetSourceType();
    if (srcType == SourceType::SOURCE_TYPE_URI) {
        uri_ = source->GetSourceUri();
        isFlvLiveStream_ = source->GetMediaStreamList().size() > 0;
        std::string mimeType = source->GetMimeType();
        if (mimeType == AVMimeTypes::APPLICATION_M3U8) {
            protocol_ = "http";  // HLS 走 HTTP 协议路由
        } else {
            ret = GetProtocolByUri();  // 从 "://" 前缀提取协议
        }
    } else if (srcType == SourceType::SOURCE_TYPE_FD) {
        protocol_.append("fd");
        uri_ = source->GetSourceUri();
    } else if (srcType == SourceType::SOURCE_TYPE_STREAM) {
        protocol_.append("stream");
    }
}
```

**协议字符串→ProtocolType 映射（source.cpp:38-43）**：
```cpp
static std::map<std::string, ProtocolType> g_protocolStringToType = {
    {"http", ProtocolType::HTTP},
    {"https", ProtocolType::HTTPS},
    {"file", ProtocolType::FILE},
    {"stream", ProtocolType::STREAM},
    {"fd", ProtocolType::FD}
};
```

**FindPlugin 路由（source.cpp:564-582）**：
```cpp
// source.cpp:564-582
Status Source::FindPlugin(const std::shared_ptr<MediaSource>& source)
{
    if (!ParseProtocol(source)) return ERROR_INVALID_PARAMETER;
    if (protocol_.empty()) return ERROR_INVALID_PARAMETER;
    auto plugin = PluginManagerV2::Instance().CreatePluginByMime(
        Plugins::PluginType::SOURCE, protocol_);  // 按协议名创建插件
    if (plugin != nullptr) {
        plugin_ = std::static_pointer_cast<SourcePlugin>(plugin);
        plugin_->SetInterruptState(isInterruptNeeded_);
        return Status::OK;
    }
    return Status::ERROR_UNSUPPORTED_FORMAT;
}
```

---

## 3. SourcePlugin 接口体系

### 3.1 SourcePlugin 基接口（source_plugin.h:95）

`SourcePlugin` 继承 `PluginBase`，定义 20+ 纯虚函数，构成所有源插件的统一接口：

```cpp
// interfaces/plugin/source_plugin.h:95
class SourcePlugin : public PluginBase {
public:
    virtual Status Read(std::shared_ptr<Buffer>& buffer, uint64_t offset, size_t expectedLen) = 0;  // 行139
    virtual Status Read(int32_t streamId, std::shared_ptr<Buffer>& buffer, uint64_t offset, size_t expectedLen) = 0;  // 行154
    virtual Status GetSize(uint64_t& size) = 0;  // 行168
    virtual Seekable GetSeekable() = 0;  // 行178
    virtual Status SeekToTime(int64_t seekTime, SeekMode mode) = 0;  // 行242
    virtual Status GetDuration(int64_t& duration) = 0;  // 行252
    virtual Status SelectBitRate(uint32_t bitRate) = 0;  // 行227
    virtual Status AutoSelectBitRate(uint32_t bitRate) = 0;  // 行232
    virtual bool IsSeekToTimeSupported() = 0;  // 行237
    virtual bool IsLocalFd() = 0;  // 行296
    virtual Status Pause() = 0;  // 行301
    virtual Status Resume() = 0;  // 行306
    virtual Status StopBufferring(bool isAppBackground) = 0;  // 行329
    // ...
};
```

### 3.2 四类具体源插件（对应 S38）

| 插件 | 注册名 | 协议 | 关键能力 |
|------|--------|------|---------|
| `FileSourcePlugin` | "file" | FILE | 本地文件读取，Seek 支持 |
| `FileFdSourcePlugin` | "fd" | FD | fd 句柄读取，支持云端预读（ringBuffer_ 40MB） |
| `HttpSourcePlugin` | "http"/"https" | HTTP/HTTPS | HTTP 流读取，HLS/DASH 自适应码率，SelectBitRate |
| `DataStreamSourcePlugin` | "stream" | STREAM | 内存流读取，无持久化 |

### 3.3 StreamInfo 多轨信息（source_plugin.h:52-91）

`SourcePlugin::GetStreamInfo()` 返回 `std::vector<StreamInfo>`，描述多轨（视频/音频/字幕）元数据：

```cpp
// interfaces/plugin/source_plugin.h:52-91
struct StreamInfo {
    int32_t streamId = 0;
    StreamType type = StreamType::MIXED;  // VIDEO/AUDIO/SUBTITLE/MIXED
    uint32_t bitRate = 0;
    uint32_t frameRate = 0;
    int32_t videoHeight = 0;
    int32_t videoWidth = 0;
    std::string mimeType = "";
    VideoType videoType = VideoType::VIDEO_TYPE_SDR;  // SDR/HDR_VIVID/HDR_10
    std::string codecs = "";  // 编码格式描述
    std::string lang = "";
    // ...
};
```

---

## 4. 关键行为详解

### 4.1 Read 读取流程（source.cpp:458-485）

```cpp
// source.cpp:458-485
Status Source::Read(int32_t streamID, std::shared_ptr<Buffer>& buffer, uint64_t offset, size_t expectedLen)
{
    if (plugin_ == nullptr) return ERROR_INVALID_OPERATION;
    FALSE_RETURN_V_MSG_E(isPluginReady_, Status::ERROR_NOT_STARTED, "plugin not ready");
    if (streamID >= 0) {
        readRes = plugin_->Read(streamID, buffer, offset, expectedLen);
        readDuration = CALC_EXPR_TIME_MS(readRes = plugin_->Read(streamID, buffer, offset, expectedLen));
    } else {
        readRes = plugin_->Read(buffer, offset, expectedLen);
        readDuration = CALC_EXPR_TIME_MS(readRes = plugin_->Read(buffer, offset, expectedLen));
    }
    // ...
    return readRes;
}
```

### 4.2 Seek 流程（source.cpp:250-260）

```cpp
// source.cpp:250-260
Status Source::SeekToTime(int64_t seekTime, SeekMode mode)
{
    FALSE_RETURN_V_MSG_E(seekToTimeFlag_, Status::ERROR_INVALID_OPERATION, "not support seek");
    GetSeekable();
    // ...
    return plugin_->SeekToTime(timeNs, mode);
}
```

**Seekable 返回值枚举**：`INVALID` / `UNSEEKABLE` / `SEEKABLE`

### 4.3 SelectBitRate 自适应码率（source.cpp:220-228）

```cpp
// source.cpp:220-228
Status Source::SelectBitRate(uint32_t bitRate)
{
    if (plugin_ == nullptr) return ERROR_INVALID_OPERATION;
    return plugin_->SelectBitRate(bitRate);  // 透传给 HttpSourcePlugin
}
```

### 4.4 中断机制

```cpp
// source.cpp:334
Status Source::SetReadBlockingFlag(bool isReadBlockingAllowed)
{
    return plugin_->SetReadBlockingFlag(isReadBlockingAllowed);
}

// source.h:103
void SetInterruptState(bool isInterruptNeeded);  // 设置插件中断状态
```

---

## 5. 与其他记忆的关联

| 关联记忆 | 关系 |
|---------|------|
| S38 SourcePlugin 源插件体系 | S38 是 S87 的上游：S87 是 Source 封装层，S38 是 SourcePlugin 插件层 |
| S37 HTTP 流媒体源插件架构 | HttpSourcePlugin 是 Source::FindPlugin 的具体落地实现 |
| S41 DemuxerFilter | DemuxerFilter 是 Source 的下游消费者，调用 Source::Read() |
| S75 MediaDemuxer 六组件 | MediaDemuxer 持有 Source 实例，消费 Source::Read() 数据 |
| S86 HLS 流媒体缓存引擎 | HlsSegmentManager 配合 HttpSourcePlugin 实现 M3U8 下载 |

---

## 6. 关键证据索引

| 行号 | 证据内容 |
|------|---------|
| source.cpp:38-43 | 协议字符串→ProtocolType 五类映射 |
| source.cpp:98-99 | SetSource 入口调用 FindPlugin |
| source.cpp:180-198 | Prepare() 调用 plugin_->Prepare() |
| source.cpp:204-208 | Start() 调用 plugin_->Start() |
| source.cpp:250-260 | SeekToTime 流程 |
| source.cpp:303-309 | Stop() 流程 |
| source.cpp:458-485 | Read() 双 StreamID 分支 |
| source.cpp:522-536 | GetProtocolByUri() 协议提取 |
| source.cpp:540-564 | ParseProtocol() 三种 SourceType 路由 |
| source.cpp:564-582 | FindPlugin() → PluginManagerV2 创建插件 |
| source.h:31-55 | CallbackImpl 实现 Plugins::Callback |
| source.h:57-103 | Source 类 public 接口（40+方法） |
| source_plugin.h:52-91 | StreamInfo 多轨元数据结构 |
| source_plugin.h:95 | SourcePlugin 基类定义（20+纯虚函数） |
| source_plugin.h:139-329 | Read/Seek/GetSize/SelectBitRate 等核心虚函数声明 |
