---
id: MEM-ARCH-AVCODEC-S122
title: "MediaEngine Streaming 基础设施——HttpSourcePlugin 三路下载器路由 / StreamDemuxer 分片缓存 / HLS+DASH 自适应码率调度"
tags: [AVCodec, MediaEngine, Source, Streaming, HttpSourcePlugin, StreamDemuxer, HLS, DASH, AdaptiveBitrate, PullData, DownloadMonitor]
scope: "新需求开发/问题定位/流媒体播放/HLS-DASH 自适应码率"
status: approved
approved_at: '2026-05-12T10:42:00+08:00'
approved_by: ou_60d8641be684f82e8d9cb84c3015dde7
created: "2026-05-14T01:50"
source-ref: https://gitcode.com/openharmony/multimedia_av_codec
evidence-tags: [HttpSourcePlugin, Streaming, AdaptiveBitrate, DownloadMonitor, PullData, StreamDemuxer, HLS, DASH]
evidence-files:
  - path: services/media_engine/plugins/source/http_source/http_source_plugin.cpp
    lines: 769
  - path: services/media_engine/plugins/source/http_source/http_source_plugin.h
    lines: 115
  - path: services/media_engine/modules/demuxer/stream_demuxer.cpp
    lines: ~600
  - path: services/media_engine/modules/demuxer/stream_demuxer.h
    lines: 492
builder: builder-agent
generated: "2026-05-14T01:50:00+08:00"
---

# S122: MediaEngine Streaming 基础设施

## 1. 模块定位

Streaming 基础设施是 Source 模块的插件层扩展，在 `HttpSourcePlugin` 中实现三层下载器路由、
在 `StreamDemuxer` 中实现分片缓存读取，共同支撑 HLS + DASH 自适应码率播放场景。

与 S106 互补：S106 聚焦 Source.cpp + M3U8 解析（Streaming 入口），S122 聚焦
HttpSourcePlugin 三路下载器路由 + StreamDemuxer 分片缓存 + 自适应码率调度。

---

## 2. 核心组件

### 2.1 HttpSourcePlugin（http_source_plugin.cpp, 769行 / http_source_plugin.h, 115行）

**HTTP Source 插件统一入口**，持有 `std::shared_ptr<MediaDownloader> downloader_`。

#### 2.1.1 三路下载器工厂路由

HttpSourcePlugin::SetDownloaderBySource() 根据 MIME 类型和 Seek 能力决定实例化哪个下载器：

| 条件 | 下载器 | 代码位置 |
|------|--------|---------|
| DASH 流 (`mimeType_ == AVMimeTypes::APPLICATION_MPD`) | `DashMediaDownloader(loaderCombinations_)` | http_source_plugin.cpp:288-289 |
| 非 M3U8 + 支持 Seek | `HlsMediaDownloader(expectDuration, userDefinedDuration, httpHeader_, loaderCombinations_)` | http_source_plugin.cpp:297-299 |
| M3U8 URI (直接 `.m3u8` 后缀或 `=?m3u8` 查询参数) | `HlsMediaDownloader(mimeType_)` | http_source_plugin.cpp:310-311 |
| 普通 HTTP 流 | `HttpMediaDownloader(uri_, expectDuration, loaderCombinations_)` | http_source_plugin.cpp:338-339 |

**关键证据**：

```cpp
// http_source_plugin.cpp:288-289
downloader_ = std::make_shared<DownloadMonitor>(
              std::make_shared<DashMediaDownloader>(loaderCombinations_));

// http_source_plugin.cpp:297-299
downloader_ = std::make_shared<DownloadMonitor>(
              std::make_shared<HlsMediaDownloader>(expectDuration, userDefinedDuration, httpHeader_, loaderCombinations_));

// http_source_plugin.cpp:310-311
downloader_ = std::make_shared<DownloadMonitor>(std::make_shared<HlsMediaDownloader>(mimeType_));

// http_source_plugin.cpp:338-339
downloader_ = std::make_shared<DownloadMonitor>(std::make_shared<HttpMediaDownloader>(uri_, expectDuration, loaderCombinations_));
```

每个下载器均被 `DownloadMonitor` 包装（装饰器模式），用于统计上报和质量监控。

#### 2.1.2 自适应码率调度

HttpSourcePlugin 实现 SourcePlugin 双码率接口：

```cpp
// http_source_plugin.h:56-57
Status SelectBitRate(uint32_t bitRate) override;
Status AutoSelectBitRate(uint32_t bitRate) override;

// http_source_plugin.cpp:526-530
Status HttpSourcePlugin::SelectBitRate(uint32_t bitRate)
{
    FALSE_RETURN_V(downloader_ != nullptr, Status::ERROR_NULL_POINTER);
    if (downloader_->SelectBitRate(bitRate)) {
        return Status::OK;
    }
    return Status::ERROR_UNKNOWN;
}
```

- `SelectBitRate(bitRate)`：手动指定目标码率，透传给具体 downloader（HlsMediaDownloader / DashMediaDownloader）
- `AutoSelectBitRate(bitRate)`：自动模式，由 downloader 内部算法选择最优码率

#### 2.1.3 M3U8 URI 识别三条件

```cpp
// http_source_plugin.cpp:645-674
bool HttpSourcePlugin::CheckIsM3U8Uri()
{
    // 条件1：查询参数含 =m3u8
    if (pairUri.second.find(EQUAL_M3U8) != std::string::npos) { // EQUAL_M3U8 = "=m3u8"
        return true;
    }
    // 条件2：路径以 .m3u8 结尾
    if (uri.find(LOWER_M3U8) != std::string::npos) { // LOWER_M3U8 = "m3u8"
        return true;
    }
    // 条件3：MIME 类型为 APPLICATION_M3U8（由 SetDownloaderBySource 设置 mimeType_）
    return (mimeType_ == AVMimeTypes::APPLICATION_M3U8); // source.cpp:250 设置
}
```

### 2.2 StreamDemuxer（stream_demuxer.h, 492行 / stream_demuxer.cpp, ~600行）

**分片流式解封装器**，负责 DASH/HLS 分片缓存读取，是 Source 与 MediaDemuxer 之间的桥梁。

#### 2.2.1 PullData 三路分发机制

StreamDemuxer::PullData() 根据流 Seek 能力选择不同读取路径：

| 方法 | 适用场景 | 行为 |
|------|---------|------|
| `PullDataWithCache()` | 可Seek流（SEEKABLE），分片缓存合并 | 先从 cache 读，剩余部分合并写入 cache |
| `PullDataWithoutCache()` | 不可Seek流（UNSEEKABLE），直接读 | 读取后写入 cacheDataMap_，处理 DEMUXER_STATE_PARSE_FRAME 状态 |
| `ReadRetry()` | 通用重试层 | TRY_READ_TIMES=10，SLEEP_TIME=10ms，可中断 |

**关键证据**：

```cpp
// stream_demuxer.cpp:46-47
const int32_t TRY_READ_SLEEP_TIME = 10;  // ms
const int32_t TRY_READ_TIMES = 10;

// stream_demuxer.cpp:71-90 PullData 路由逻辑
if (source_->IsSeekToTimeSupported() || source_->GetSeekable() == Plugins::Seekable::UNSEEKABLE) {
    return PullDataWithCache(streamID, offset, size, bufferPtr, isSniffCase);
}
return PullData(streamID, offset, size, bufferPtr, isSniffCase);
```

#### 2.2.2 PullDataWithCache 缓存合并算法

```cpp
// stream_demuxer.cpp:133-159
Status StreamDemuxer::PullDataWithCache(int32_t streamID, uint64_t offset, size_t size, ...)
{
    // 1. 从 cache 读取部分数据
    // 2. 剩余部分调用 PullData(streamID, remainOffset, remainSize, ...)
    // 3. 检查状态是否为 DEMUXER_STATE_PARSE_FRAME（不允许跨分片缓存）
    if (pluginStateMap_[streamID] == DemuxerState::DEMUXER_STATE_PARSE_FRAME) {
        MEDIA_LOG_W("PullDataWithCache, not cache begin."); // 不允许跨分片边界缓存
    }
}
```

#### 2.2.3 DASH 分片合并 ProcInnerDash

```cpp
// stream_demuxer.cpp:181-201
Status StreamDemuxer::ProcInnerDash(int32_t streamID, uint64_t offset, std::shared_ptr<Buffer>& bufferPtr)
{
    // 从 cacheDataMap_ 取出该 streamID 的已缓存数据，与当前读取的分片合并
    // 用于 DASH 分片边界不整齐时的合并读取
}
```

#### 2.2.4 ReadRetry 重试机制

```cpp
// stream_demuxer.cpp:245-277
Status StreamDemuxer::ReadRetry(int32_t streamID, uint64_t offset, size_t size, ...)
{
    while (retryTimes <= TRY_READ_TIMES && !isInterruptNeeded_.load()) {
        err = plugin_->ReadAt(streamID, offset, readSize, data, isSniffCase);
        if (err == Status::OK || err == Status::ERROR_AGAIN) {
            readCond_.wait_for(lock, std::chrono::milliseconds(TRY_READ_SLEEP_TIME));
        }
        retryTimes++;
    }
    if (retryTimes > TRY_READ_TIMES || isInterruptNeeded_.load()) {
        return Status::ERROR_TIMEOUT;
    }
}
```

---

## 3. 自适应码率事件驱动

Source::ProcessEvent() 处理来自 Downloader 的码率切换事件：

| 事件 | 处理 | 代码位置 |
|------|------|---------|
| `PluginEventType::HLS_SEEK_READY` | HLS 直播流 Seek 准备就绪，重新路由读取路径 | source.cpp:384 |
| `PluginEventType::DASH_SEEK_READY` | DASH 直播流 Seek 准备就绪，重新路由读取路径 | source.cpp:378 |
| `PluginEventType::FLV_AUTO_SELECT_BITRATE` | FLV 直播流自动码率切换 | source.cpp:381 |
| `PluginEventType::SOURCE_BITRATE_START` | 开始上报码率信息 | source.cpp:366 |

---

## 4. DownloadMonitor 装饰器

所有下载器均被 `DownloadMonitor` 包装，用于：

- 统计 `totalBytesRead_`、`downloadSpeed_` 等质量指标
- 设置 DFX 上报（`SetSourceStatisticsDfx(reportInfo_)`）
- 统一 Pause/Resume 中断控制

```cpp
// http_source_plugin.cpp:288
downloader_ = std::make_shared<DownloadMonitor>(
              std::make_shared<DashMediaDownloader>(loaderCombinations_));
```

---

## 5. 与相邻记忆的关联

| 记忆 | 关系 |
|------|------|
| S106 | S106 聚焦 Source.cpp + M3U8 解析器（Streaming 入口）；S122 聚焦 HttpSourcePlugin 三路下载器 + StreamDemuxer 缓存读取 |
| S101 | S101 是 StreamDemuxer 完整分析（PullData/ReadRetry/CallbackReadAt）；S122 补充 DASH 分片合并 ProcInnerDash |
| S102 | S102 是 SampleQueueController 流控（SPEED_START/STOP）；S122 是 StreamDemuxer 读取层的重试和缓存 |
| S75 | S75 是 MediaDemuxer 六组件引擎层；S122 是 Source → StreamDemuxer → DemuxerFilter 的中间读取桥 |
| S37/S38 | S37/S38 是 SourcePlugin 体系；S122 补充 HttpSourcePlugin 的具体下载器工厂路由逻辑 |
| S41 | S41 是 DemuxerFilter 封装；S122 补充 StreamDemuxer 分片缓存读取机制，是 DemuxerFilter 的下游数据源 |

---

## 6. 关键文件索引

| 文件 | 行数 | 核心职责 |
|------|------|---------|
| `services/media_engine/plugins/source/http_source/http_source_plugin.cpp` | 769 | 三路下载器路由、自适应码率调度、DownloadMonitor 装饰 |
| `services/media_engine/plugins/source/http_source/http_source_plugin.h` | 115 | HttpSourcePlugin 类定义、SelectBitRate/AutoSelectBitRate 接口 |
| `services/media_engine/modules/demuxer/stream_demuxer.cpp` | ~600 | PullData 三路分发、ReadRetry 重试、ProcInnerDash DASH合并 |
| `services/media_engine/modules/demuxer/stream_demuxer.h` | 492 | StreamDemuxer 类定义、CallbackReadAt/PullDataWithCache/WithoutCache 声明 |
| `services/media_engine/modules/source/source.cpp` | 715 | HLS_SEEK_READY / DASH_SEEK_READY 事件处理（source.cpp:378/384） |
| `services/media_engine/plugins/source/http_source/hls/hls_media_downloader.cpp` | 704 | HLS 分片下载器，SelectBitRate 实现 |
| `services/media_engine/plugins/source/http_source/dash/dash_media_downloader.cpp` | 1409 | DASH 下载器，SelectBitRate 实现 |
