# MEM-ARCH-AVCODEC-S122: MediaEngine Streaming 基础设施

> **状态**: draft  
> **主题**: HttpSourcePlugin 三路下载器路由 / StreamDemuxer 分片缓存 / HLS+DASH 自适应码率调度  
> **来源**: av_codec_repo (本地镜像)  
> **与S106互补**: S106聚焦Source.cpp+M3U8解析；本条目聚焦HTTP Source插件路由、协议推断、Streaming分片管理

---

## 1. HttpSourcePlugin 入口与注册

**文件**: `services/media_engine/plugins/source/http_source/http_source_plugin.cpp`

### 1.1 插件注册 (L46-56)
```cpp
Status HttpSourceRegister(std::shared_ptr<Register> reg)
{
    SourcePluginDef definition;
    definition.name = "HttpSource";
    definition.description = "Http source";
    definition.rank = 100;  // 高优先级
    Capability capability;
    capability.AppendFixedKey<std::vector<ProtocolType>>(Tag::MEDIA_PROTOCOL_TYPE,
        {ProtocolType::HTTP, ProtocolType::HTTPS});  // 仅处理HTTP(S)
    definition.AddInCaps(capability);
    definition.SetCreator(HttpSourcePluginCreater);
    return reg->AddPlugin(definition);
}
PLUGIN_DEFINITION(HttpSource, LicenseType::APACHE_V2, HttpSourceRegister, [] {});
```

### 1.2 三路下载器选择路由 (L229-265 `SetDownloaderBySource`)
核心决策树：

```
SetDownloaderBySource(source)
  ├─ IsDash()                                    → DashMediaDownloader
  ├─ IsSeekToTimeSupported() && mimeType!=M3U8   → HlsMediaDownloader (可seek的HLS，非m3u8扩展名)
  ├─ uri_.compare(0,4,"http")==0                 → HttpMediaDownloader
  └─ mimeType_==APPLICATION_M3U8                 → HlsMediaDownloader (强制)
```

**关键辅助函数** `IsDash()` (L585-592):
```cpp
bool HttpSourcePlugin::IsDash()
{
    auto it = std::find_if(std::begin(DASH_LIST), std::end(DASH_LIST),
        [this](const std::string& key) {
            return this->uri_.find(key) != std::string::npos;
    });
    return it != std::end(DASH_LIST);
}
// DASH_LIST = { ".mpd", "type=mpd" }
```

**关键辅助函数** `IsSeekToTimeSupported()` (L340-348):
```cpp
bool HttpSourcePlugin::IsSeekToTimeSupported()
{
    if (mimeType_ != AVMimeTypes::APPLICATION_M3U8) {
        return CheckIsM3U8Uri() || uri_.find(DASH_SUFFIX) != std::string::npos;
        // DASH_SUFFIX = ".mpd"
    }
    MEDIA_LOG_I("IsSeekToTimeSupported return true");
    return true;
}
```

### 1.3 M3U8 URI 检查 (L537-576 `CheckIsM3U8Uri`)
支持多种非标准HLS路径（不是以 `.m3u8` 结尾）：
- 资源类型参数：`?autotype=m3u8`
- 查询参数：`=m3u8` 后缀
- 无扩展名但URI含 `m3u8`

### 1.4 下载器包装: DownloadMonitor (L233-244)
所有下载器均通过 `DownloadMonitor` 包装：
```cpp
if (IsDash()) {
    downloader_ = std::make_shared<DownloadMonitor>(
        std::make_shared<DashMediaDownloader>(loaderCombinations_));
} else if (IsSeekToTimeSupported() && mimeType_ != AVMimeTypes::APPLICATION_M3U8) {
    downloader_ = std::make_shared<DownloadMonitor>(
        std::make_shared<HlsMediaDownloader>(expectDuration, userDefinedDuration, httpHeader_, loaderCombinations_));
} else if (uri_.compare(0, 4, "http") == 0) {
    InitHttpSource(source);  // → HttpMediaDownloader
}
```

---

## 2. DownloadMonitor 装饰层

**文件**: `services/media_engine/plugins/source/http_source/monitor/download_monitor.h`

### 2.1 职责
`DownloadMonitor` 继承 `MediaDownloader` 接口，作为所有下载器的**统一装饰器**，提供：
1. **监控循环** (`HttpMonitorLoop`): 后台任务监控下载状态
2. **错误码映射**: HTTP状态码和curl错误码 → `MediaServiceErrCode`
3. **重试队列**: `retryTasks_` 管理失败请求的重试
4. **读写超时**: `lastReadTime_` 追踪读超时

### 2.2 错误码映射 (L57-148)
- **客户端错误** (-6到101): SSL证书、时间戳、网络拒绝、无法连接主机等
- **服务端错误** (400-511): 401无权限、403/404/410资源不存在、408/504超时、502/503网络不可用

### 2.3 关键状态
```cpp
std::atomic<bool> isClosed_{false};
std::shared_ptr<MediaDownloader> downloader_;  // 被包装的实际下载器
std::list<RetryRequest> retryTasks_;
std::atomic<bool> isPlaying_ {false};
std::weak_ptr<Callback> callback_;
```

---

## 3. HlsMediaDownloader 分片管理

**文件**: `services/media_engine/plugins/source/http_source/hls/hls_media_downloader.h`

### 3.1 多流分段管理器
每个流类型独立管理：
```cpp
std::shared_ptr<HlsSegmentManager> videoSegManager_ {nullptr};
std::shared_ptr<HlsSegmentManager> audioSegManager_ {nullptr};
std::shared_ptr<HlsSegmentManager> subtitlesSegManager_ {nullptr};
```

### 3.2 构造方式
两种构造签名：
```cpp
// 方式1: 指定缓冲时长和用户定义duration
explicit HlsMediaDownloader(
    int expectBufferDuration,        // 默认 19s (DEFAULT_EXPECT_DURATION)
    bool userDefinedDuration,         // 是否允许自动调节
    const std::map<std::string, std::string>& httpHeader,
    std::shared_ptr<MediaSourceLoaderCombinations> sourceLoader);

// 方式2: 仅mimeType (用于强制M3U8场景)
explicit HlsMediaDownloader(
    std::string mimeType,
    const std::map<std::string, std::string>& httpHeader);
```

### 3.3 关键能力
- `SelectBitRate(uint32_t bitRate)`: 码率切换
- `GetBitRates()`: 获取可用码率列表
- `SetPlayStrategy()`: 设置播放策略（缓冲配置）
- `HlsSegmentManager`: 每个流的分段获取和缓存
- `MediaCachedBuffer`: Ring buffer 实现分片预读

---

## 4. StreamDemuxer 分片缓存

**文件**: `services/media_engine/modules/demuxer/stream_demuxer.cpp`

### 4.1 缓存架构
```cpp
std::map<int32_t, CacheData> cacheDataMap_;  // streamID → CacheData
mutable std::mutex cacheDataMutex_;
```

`CacheData` 包含：
- `offset`: 缓存起始位置
- `data`: `std::shared_ptr<Buffer>` 缓存数据

### 4.2 读取路径分支

**DEMUXER_STATE_PARSE_HEADER** (L294-304):
- 优先读缓存：`CheckCacheExist(offset)` → `PullDataWithCache`
- 缓存未命中：`PullDataWithoutCache` → 可能触发合并缓存

**DEMUXER_STATE_PARSE_FRAME** (L307-319):
- 优先读缓存（仅 DASH 或 `GetIsDataSrcNoSeek()` 时）
- `PullData` vs `PullDataWithCache`

### 4.3 DASH分片合并 (L138-172 `ProcInnerDash`)
DASH场景下，`PullDataWithoutCache` 会与已有缓存合并：
```cpp
// 将前一个缓存片段与当前数据合并成新的 `mergedBuffer`
mergedBuffer = Buffer::CreateDefaultBuffer(bufferMemory->GetSize() + cacheMemory->GetSize());
mergeMemory->Write(cacheMemory->GetReadOnlyData(), cacheMemory->GetSize(), 0);
mergeMemory->Write(bufferMemory->GetReadOnlyData(), bufferMemory->GetSize(), cacheMemory->GetSize());
cacheDataMap_[streamID].SetData(mergedBuffer);
```

### 4.4 PullData 重试逻辑 (L206-239)
```cpp
while (true && !isInterruptNeeded_.load()) {
    err = source_->Read(streamID, data, offset, size);
    if (err == Status::ERROR_AGAIN && !isSniffCase) {
        return err;  // 立即返回，等待下次调用
    }
    if (err != Status::END_OF_STREAM && data->GetMemory()->GetSize() == 0) {
        // 空数据，重试最多 TRY_READ_TIMES(10) 次，每次 sleep 10ms
        retryTimes++;
        if (retryTimes > TRY_READ_TIMES || isInterruptNeeded_.load()) {
            break;
        }
        continue;
    }
    break;
}
```

### 4.5 读取超时监控
`SOURCE_READ_WARNING_MS = 100ms`:
```cpp
ScopedTimer timer("Source Read", SOURCE_READ_WARNING_MS);
err = source_->Read(streamID, data, offset, size);
```

---

## 5. 自适应码率调度 (ABR)

### 5.1 码率选择入口
`HttpSourcePlugin` 暴露给上层的码率控制：
```cpp
Status SelectBitRate(uint32_t bitRate)   // L390-397: 手动选码率
Status AutoSelectBitRate(uint32_t bitRate) // L400-406: 自动码率
std::vector<uint32_t> GetBitRates()      // L374-377: 获取可用码率列表
Status SetCurrentBitRate(int32_t bitRate, int32_t streamID) // L436-442
```

### 5.2 DownloadMonitor 中的触发模式
```cpp
void SetIsTriggerAutoMode(bool isAuto) override;
// 当为true时，下载器自动选择码率（基于网络状况）
```

### 5.3 HlsMediaDownloader 码率决策
- `SelectBitrate(uint32_t bitRate)`: 切换到指定码率
- `AutoSelectBitrate(uint32_t bitRate)`: 基于下层DownloadMonitor的网络反馈自动切换
- `GetBitRates()`: 返回manifest中声明的所有码率

---

## 6. 离线缓存与播放策略

### 6.1 MediaSourceLoaderCombinations (L199-215)
`SetDownloaderBySource` 中会初始化离线缓存组合：
```cpp
if (source->GetSourceLoader() != nullptr) {
    loaderCombinations_ = std::make_shared<MediaSourceLoaderCombinations>(source->GetSourceLoader());
    loaderCombinations_->EnableOfflineCache(source->GetenableOfflineCache());
    // Cookie + 离线缓存 → 禁用缓存
    if (httpHeader_.find("Cookie") != httpHeader_.end() && loaderCombinations_->GetenableOfflineCache()) {
        loaderCombinations_->Close(-1);
    }
    // 存储空间不足 → 禁用缓存
    if (loaderCombinations_->GetenableOfflineCache() && !storageUsage->HasEnoughStorage()) {
        loaderCombinations_->Close(-1);
    }
}
```

### 6.2 PlayStrategy 缓冲配置
`HttpSourcePlugin::SetParameter` 从 meta 中提取：
```cpp
meta->GetData(Tag::BUFFERING_SIZE, bufferSize_);
meta->GetData(Tag::WATERLINE_HIGH, waterline_);
```

---

## 7. 关键数据流总结

```
MediaSource (URI)
    ↓
HttpSourcePlugin::SetSource()
    ↓
SetDownloaderBySource()  → 协议推断
    ├─ IsDash()            → .mpd / type=mpd  → DashMediaDownloader
    ├─ IsSeekToTimeSupported() && !M3U8 mime → HlsMediaDownloader (可seek HLS)
    └─ plain http          → HttpMediaDownloader
    ↓ (所有下载器被 DownloadMonitor 包装)
DownloadMonitor
    ↓
RingBuffer / HlsSegmentManager (分片预读 + 缓存)
    ↓
StreamDemuxer::PullData / PullDataWithCache (分片缓存合并)
    ↓
DemuxerCallback::OnRead() → VideoDecoder
```

---

## Evidence 列表

| # | 文件 | 关键行号 | 描述 |
|---|------|---------|------|
| E1 | http_source_plugin.cpp | 46-56 | HttpSource 插件注册 |
| E2 | http_source_plugin.cpp | 229-265 | 三路下载器路由选择 |
| E3 | http_source_plugin.cpp | 340-348 | IsSeekToTimeSupported 判断 |
| E4 | http_source_plugin.cpp | 537-576 | CheckIsM3U8Uri 非标准路径支持 |
| E5 | http_source_plugin.cpp | 185-214 | SetDownloaderBySource 完整逻辑 |
| E6 | download_monitor.h | 1-148 | DownloadMonitor 接口与错误码映射 |
| E7 | hls_media_downloader.h | 1-90 | HlsMediaDownloader 分片管理架构 |
| E8 | stream_demuxer.cpp | 50-90 | ReadFrameData / ReadHeaderData 缓存路径 |
| E9 | stream_demuxer.cpp | 138-172 | ProcInnerDash DASH分片合并 |
| E10 | stream_demuxer.cpp | 206-239 | PullData 重试逻辑与超时监控 |

---

**关联**: S106 (Source.cpp + M3U8解析)  
**下一步**: 补充 DashMediaDownloader 和 HttpMediaDownloader 的分片下载逻辑细节