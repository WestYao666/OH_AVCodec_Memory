---
id: MEM-ARCH-AVCODEC-S106
title: "MediaEngine Source 模块流媒体基础设施——Protocol 路由 / Plugin 管理 / HLS+Bitrate 双调度 / Buffering 策略"
scope: [AVCodec, MediaEngine, Source, Streaming, Protocol, HLS, DASH, AdaptiveBitrate, Buffering]
status: pending_approval
submitted_by: builder-agent
submitted_at: "2026-05-09T14:48:00+08:00"
created_by: builder-agent
created_at: "2026-05-09T06:16:00+08:00"
evidence_sources:
  - "services/media_engine/modules/source/source.cpp (715行)"
  - "services/media_engine/modules/source/source.h (~180行)"
  - "services/media_engine/plugins/source/file_source_plugin.cpp (~400行)"
  - "services/media_engine/plugins/source/http_source/http_source_plugin.cpp (~500行)"
  - "services/media_engine/plugins/source/http_source/hls/m3u8.cpp (1435行)"
  - "services/media_engine/plugins/source/http_source/hls/hls_media_downloader.cpp (704行)"
  - "services/media_engine/plugins/source/http_source/hls/hls_segment_manager.cpp (2582行)"
  - "services/media_engine/plugins/source/data_stream_source_plugin.cpp (~200行)"
  - "services/media_engine/plugins/source/file_fd_source_plugin.cpp (~300行)"
---

# MEM-ARCH-AVCODEC-S106: MediaEngine Source 模块流媒体基础设施

## 主题

MediaEngine Source 模块流媒体基础设施——Protocol 路由 / Plugin 管理 / HLS+Bitrate 双调度 / Buffering 策略

## Scope

AVCodec, MediaEngine, Source, Streaming, Protocol, HLS, DASH, AdaptiveBitrate, Buffering

## 关联场景

新需求开发 / 问题定位 / 流媒体播放 / HLS-DASH 自适应码率

## 状态

`pending_approval`（2026-05-09 提交审批，2026-05-09 Builder 增强行号级证据）

---

## 概述

`Source` 类（`services/media_engine/modules/source/source.cpp`, 715行）是 MediaEngine 层媒体源核心引擎，位于 Filter Pipeline 最上游。它负责：

1. **协议路由**：根据 URI 前缀识别 HTTP/HTTPS/FILE/STREAM/FD 五类协议
2. **SourcePlugin 插件管理**：通过 `PluginManagerV2::CreatePluginByMime(SOURCE, protocol_)` 动态创建插件
3. **流媒体支持**：HLS M3U8 自适应码率、DASH MPD 分片流
4. **Buffering 策略**：预缓冲、缓存时长控制、FLV 直播判断
5. **Seek/Stream 控制**：时间Seek、轨选默认ID设置

---

## 核心组件

### 1. ProtocolType 协议识别（source.cpp:38-43）

```cpp
static std::map<std::string, ProtocolType> g_protocolStringToType = {
    {"http", ProtocolType::HTTP},
    {"https", ProtocolType::HTTPS},
    {"file", ProtocolType::FILE},
    {"stream", ProtocolType::STREAM},
    {"fd", ProtocolType::FD}
};
```

- `GetProtocolByUri()` 从 URI 提取 `://` 前缀得到协议类型
- HLS M3U8 强制走 HTTP（`mimeType == AVMimeTypes::APPLICATION_M3U8` 时 protocol_="http"）
- FD 类型走 `SourceType::SOURCE_TYPE_FD` 分支
- STREAM 类型走 `SourceType::SOURCE_TYPE_STREAM` 分支

### 2. FindPlugin 插件工厂路由（source.cpp:564-585）

```cpp
Status Source::FindPlugin(const std::shared_ptr<MediaSource>& source)
{
    if (!ParseProtocol(source)) { ... }
    if (protocol_.empty()) { ... }
    auto plugin = Plugins::PluginManagerV2::Instance()
        .CreatePluginByMime(Plugins::PluginType::SOURCE, protocol_);
    if (plugin != nullptr) {
        plugin_ = std::static_pointer_cast<SourcePlugin>(plugin);
        plugin_->SetInterruptState(isInterruptNeeded_);
        return Status::OK;
    }
    return Status::ERROR_UNSUPPORTED_FORMAT;
}
```

- 路由到 `PluginManagerV2` 的 `CreatePluginByMime(SOURCE, protocol_)` 创建具体 SourcePlugin
- 四类具体插件（见下节）
- `isInterruptNeeded_` 中断状态透传

### 3. SourcePlugin 插件体系（四类具体插件）

| 插件 | 源码路径 | 关键能力 |
|------|---------|---------|
| FileSourcePlugin | `services/media_engine/plugins/source/file_source_plugin.cpp` | 文件 Read/Seek/GetSize，std::FILE 封装，FileSourceAllocator 内存分配，downloadInfo 下载统计 |
| HttpSourcePlugin | `services/media_engine/plugins/source/http_source/http_source_plugin.cpp` | HTTP/HTTPS，委托 HlsMediaDownloader/DashMediaDownloader，RingBuffer 缓冲，AdaptiveBitrate |
| DataStreamSourcePlugin | `services/media_engine/plugins/source/data_stream_source_plugin.cpp` | 内存流（无设备依赖），AVSharedMemoryPool 内存池 |
| FileFdSourcePlugin | `services/media_engine/plugins/source/file_fd_source_plugin.cpp` | fd 句柄，云端预读（ringBuffer_ 40MB），isReadBlocking_ 阻塞控制 |

SourcePlugin 基接口核心方法（`plugin/source_plugin.h`）：
- `Read(streamID, buffer, offset, expectedLen)` 读取数据
- `SeekTo(offset)` / `SeekToTime(timeNs, mode)` Seek
- `GetSize()` / `GetDuration()` 元数据
- `GetSeekable()` 可 Seek 性查询
- `SelectBitRate(bitRate)` / `AutoSelectBitRate(bitRate)` 自适应码率
- `SelectStream(streamID)` 轨选

### 4. HLS 流媒体支持

HttpSourcePlugin 内置 HLS 处理链路：

```
HttpSourcePlugin 
  → HlsMediaDownloader (services/media_engine/plugins/source/http_source/hls/)
    → M3U8 解析（playlist 路由 video/audio/subtitle 三轨）
    → SegManager 分片下载
    → AesDecryptor AES-128-CBC 解密
    → 自适应码率 SelectBitRate
```

关键方法：
- `IsHls()`: 是否为 HLS 流
- `IsHlsFmp4()`: 是否为 HLS fMP4（Fragmented MP4）
- `IsHlsEnd(streamId)`: HLS 流是否结束
- `GetHLSDiscontinuity()`: 不连续性标记（切换码率时）
- `GetSegmentOffset()`: 分片偏移

### 5. DASH 流媒体支持

```
HttpSourcePlugin
  → DashMediaDownloader (services/media_engine/plugins/source/http_source/dash/)
    → MPD 解析
    → DashMpdDownloader + SegmentDownloader
    → Track 切换 CheckChangeStreamID
```

### 6. 自适应码率调度（Adaptive Bitrate）

```cpp
Status Source::SelectBitRate(uint32_t bitRate)
{
    return plugin_->SelectBitRate(bitRate);
}
Status Source::AutoSelectBitRate(uint32_t bitRate)
{
    return plugin_->AutoSelectBitRate(bitRate);
}
Status Source::GetBitRates(std::vector<uint32_t>& bitRates)
{
    return plugin_->GetBitRates(bitRates);
}
```

- `CanAutoSelectBitRate()`: 回调接口判断是否可自动选码率
- `SetSelectBitRateFlag(bool flag, uint32_t desBitRate)`: 手动设置目标码率

### 7. Buffering 策略

| 方法 | 功能 |
|------|------|
| `SetExtraCache(cacheDuration)` | 设置额外缓存时长 |
| `IsNeedPreDownload()` | 判断是否需要预下载 |
| `WaitForBufferingEnd()` | 等待缓冲完成（直播流同步） |
| `GetCachedDuration()` | 获取已缓存时长 |
| `RestartAndClearBuffer()` | 重启并清空缓冲区 |
| `StopBufferring(isAppBackground)` | 停止缓冲（App 切后台） |

FLV 直播判断：
```cpp
// source.cpp:543
isFlvLiveStream_ = source->GetMediaStreamList().size() > 0;
```

### 8. Stream 轨选管理

```cpp
Status Source::SelectStream(int32_t streamID)
{
    return plugin_->SelectStream(streamID);
}
void Source::SetDefaultStreamId(int32_t& videoStreamId, 
                                int32_t& audioStreamId, 
                                int32_t& subTitleStreamId)
{
    plugin_->SetDefaultStreamId(videoStreamId, audioStreamId, subTitleStreamId);
}
```

### 9. Seek 机制

```cpp
Status Source::SeekToTime(int64_t seekTime, SeekMode mode)
{
    if (seekable_ != Seekable::SEEKABLE) { GetSeekable(); }
    int64_t timeNs;
    if (Plugins::Ms2HstTime(seekTime, timeNs)) {
        return plugin_->SeekToTime(timeNs, mode);
    }
}
Status Source::MediaSeekTimeByStreamId(int64_t seekTime, SeekMode mode, int32_t streamId)
{
    return plugin_->MediaSeekTimeByStreamId(timeUs, mode, streamId);
}
```

### 10. 中断与优先级控制

```cpp
void Source::SetInterruptState(bool isInterruptNeeded)
{
    isInterruptNeeded_ = isInterruptNeeded;
    if (plugin_) plugin_->SetInterruptState(isInterruptNeeded_);
}
```

---

## 与其他组件关系

| 关联组件 | 关系 |
|---------|------|
| S87 MediaSource（Filter 层） | S87 是 Filter 层封装，Source 是 engine 层实现 |
| S37/S38 SourcePlugin 体系 | S38 覆盖 Filter 层 SourceFilter，本 S106 覆盖 engine 层 Source 模块 |
| S41 DemuxerFilter | Source 输出 → DemuxerFilter 输入（Pipeline 上游→下游） |
| S69/S75 MediaDemuxer | MediaDemuxer 是 Source 的消费方，负责解封装 |
| S86 HLS Cache Engine | HLS 流媒体缓存（HlsMediaDownloader） |

---

## 关键文件证据

| 文件 | 行数/行号 | 关键内容 |
|------|----------|---------|
| `services/media_engine/modules/source/source.cpp` | 715行 | Source 主体实现 |
| `services/media_engine/modules/source/source.h` | 180行 | Source 类定义，75+方法 |
| `services/media_engine/plugins/source/file_source_plugin.cpp` | ~400行 | FileSourcePlugin 实现 |
| `services/media_engine/plugins/source/http_source/http_source_plugin.cpp` | ~500行 | HttpSourcePlugin，含 HLS/DASH 路由 |
| `services/media_engine/plugins/source/data_stream_source_plugin.cpp` | ~200行 | DataStreamSourcePlugin |
| `services/media_engine/plugins/source/file_fd_source_plugin.cpp` | ~300行 | FileFdSourcePlugin，云端预读 |
| `plugin/source_plugin.h` | ~200行 | SourcePlugin 基接口（纯虚函数） |
| `services/media_engine/plugins/source/http_source/hls/` | HLS 分片下载 | HlsMediaDownloader+M3U8 解析器 |
| `services/media_engine/plugins/source/http_source/dash/` | DASH 分片下载 | DashMediaDownloader+MPD 解析器 |

---

## 详细行号级 Evidence

### 核心数据结构

| 符号 | 文件:行号 | 说明 |
|------|---------|------|
| `g_protocolStringToType` | source.cpp:38-43 | HTTP/HTTPS/FILE/STREAM/FD 五协议映射表 |
| `class Source` | source.h:85 | Source 主类，继承 Plugins::Callback + enable_shared_from_this |
| `enum class Seekable` | source.h（推断） | INVALID / NOT_SEEKABLE / SEEKABLE |

### 初始化与插件创建

| 符号 | 文件:行号 | 说明 |
|------|---------|------|
| `Source::ParseProtocol()` | source.cpp:540-547 | URI 解析提取协议类型，FLV 直播判断 |
| `Source::FindPlugin()` | source.cpp:564-585 | PluginManagerV2::CreatePluginByMime(SOURCE, protocol_) 路由 |
| `Source::SetSource()` | source.cpp:98-99 | FindPlugin → plugin_ 创建 |
| `Source::SetExtraCache()` | source.cpp:125-131 | SetExtraCache(cacheDuration) → plugin_->SetExtraCache() |
| `IsNeedPreDownload()` | source.cpp:294-300 | 预下载判断 → plugin_->IsNeedPreDownload() |

### 自适应码率调度

| 符号 | 文件:行号 | 说明 |
|------|---------|------|
| `GetBitRates()` | source.cpp:210-217 | 获取支持码率列表 → plugin_->GetBitRates() |
| `SelectBitRate()` | source.cpp:220-227 | 手动选码率 → plugin_->SelectBitRate() |
| `AutoSelectBitRate()` | source.cpp:230-237 | 自动选码率 → plugin_->AutoSelectBitRate() |
| `CanAutoSelectBitRate()` | source.cpp:405-408 | 判断是否可自动选码率（mediaDemuxerCallback_ 查询） |
| `SetSelectBitRateFlag()` | source.cpp:398-401 | 手动设置目标码率（mediaDemuxerCallback_->SetSelectBitRateFlag） |

### Seek 与时间控制

| 符号 | 文件:行号 | 说明 |
|------|---------|------|
| `IsSeekToTimeSupported()` | source.cpp:199 | 是否支持按时间 Seek |
| `GetSeekable()` | source.cpp:422-430 | 查询可 Seek 性 → plugin_->GetSeekable() |
| `SeekToTime()` | source.cpp:250-257 | 按时间 Seek → plugin_->SeekToTime() |
| `source.cpp:265` | source.cpp:265 | MediaSeekTimeByStreamId 多轨 Seek |

### 缓冲策略

| 符号 | 文件:行号 | 说明 |
|------|---------|------|
| `WaitForBufferingEnd()` | source.cpp:650-653 | 等待缓冲完成（直播流同步）→ plugin_->WaitForBufferingEnd() |
| `GetCachedDuration()` | source.cpp:662-665 | 获取已缓存时长 → plugin_->GetCachedDuration() |
| `RestartAndClearBuffer()` | source.cpp:668-671 | 重启并清空缓冲区 → plugin_->RestartAndClearBuffer() |
| `StopBufferring()` | source.cpp:692-695 | 停止缓冲（App 切后台）→ plugin_->StopBufferring() |

### HLS/DASH 流媒体

| 符号 | 文件:行号 | 说明 |
|------|---------|------|
| `IsHls()` | source.cpp:704 | 是否为 HLS 流 → plugin_->IsHls() |
| `IsHlsFmp4()` | source.cpp:680-683 | HLS fMP4（Fragmented MP4）→ plugin_->IsHlsFmp4() |
| `IsHlsEnd()` | source.cpp:698-701 | HLS 流结束判断 → plugin_->IsHlsEnd(streamId) |
| `GetHLSDiscontinuity()` | source.cpp:638-641 | 不连续性标记（切换码率时）→ plugin_->GetHLSDiscontinuity() |
| `GetSegmentOffset()` | source.cpp:632-635 | 分片偏移 → plugin_->GetSegmentOffset() |

### 轨选管理

| 符号 | 文件:行号 | 说明 |
|------|---------|------|
| `GetStreamInfo()` | source.cpp:502-516 | 获取轨信息列表 → plugin_->GetStreamInfo() |
| `SelectStream()` | source.cpp:615-618 | 选择轨 → plugin_->SelectStream(streamID) |
| `SetDefaultStreamId()` | source.cpp:621-624 | 设置默认轨（video/audio/subtitle）→ plugin_->SetDefaultStreamId() |

### FLV 直播判断

| 符号 | 文件:行号 | 说明 |
|------|---------|------|
| `isFlvLiveStream_` | source.cpp:547 | `source->GetMediaStreamList().size() > 0` 判断 FLV 直播 |

---

## 待审批说明

草案文件由 Builder Agent 生成（2026-05-09），请耀耀审批：
- `approve MEM-ARCH-AVCODEC-S106` → 正式入库
- `revise MEM-ARCH-AVCODEC-S106` → 返回修订意见
- `reject MEM-ARCH-AVCODEC-S106` → 拒绝并说明原因
