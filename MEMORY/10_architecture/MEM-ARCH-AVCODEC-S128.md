# MEM-ARCH-AVCODEC-S128: HttpSourcePlugin 三路下载器路由与 StreamDemuxer 分片缓存读取机制

## 摘要

HttpSourcePlugin 是 AVCodec 流媒体基础设施的核心入口，负责根据 URI 类型将下载请求路由到三个不同的下载器实现（DASH / HLS / plain HTTP），并通过 DownloadMonitor 装饰器注入重试与监控能力。StreamDemuxer 在解封装层接收来自 Source 的数据流，通过 PullData 三路分发机制（WithCache / WithoutCache / 直接）和 ReadRetry 重试逻辑完成数据供给。本条目基于本地镜像 `/home/west/av_codec_repo` 逐行源码分析。

---

## 1. HttpSourcePlugin 三路下载器路由

### 1.1 三路分发入口

**文件**: `services/media_engine/plugins/source/http_source/http_source_plugin.cpp`
**行号**: `SetDownloaderBySource()` — 277~307 行

```cpp
void HttpSourcePlugin::SetDownloaderBySource(std::shared_ptr<MediaSource> source)
{
    // [E1] line 277: IsDash() 检查 .mpd 后缀 → DashMediaDownloader
    if (IsDash()) {
        downloader_ = std::make_shared<DownloadMonitor>(
                      std::make_shared<DashMediaDownloader>(loaderCombinations_));
        downloader_->Init();
        delayReady_ = false;
    }
    // [E2] line 284: IsSeekToTimeSupported() && 非 m3u8 mimeType → HlsMediaDownloader
    else if (IsSeekToTimeSupported() && mimeType_ != AVMimeTypes::APPLICATION_M3U8) {
        bool userDefinedDuration = false;
        uint32_t expectDuration = DEFAULT_EXPECT_DURATION; // line 28: 19s
        UserDefinedDuration(playStrategy, userDefinedDuration, expectDuration);
        downloader_ = std::make_shared<DownloadMonitor>(
                      std::make_shared<HlsMediaDownloader>(expectDuration, userDefinedDuration, ...));
        downloader_->Init();
        delayReady_ = false;
    }
    // [E3] line 300: 纯 HTTP 流 → HttpMediaDownloader
    else if (uri_.compare(0, 4, "http") == 0) {
        InitHttpSource(source);
    }
    // [E4] line 305: mimeType 明确为 application/m3u8 → HlsMediaDownloader
    if (mimeType_ == AVMimeTypes::APPLICATION_M3U8) {
        downloader_ = std::make_shared<DownloadMonitor>(
                      std::make_shared<HlsMediaDownloader>(mimeType_));
        downloader_->Init();
    }
}
```

### 1.2 三路判断条件

| 路由分支 | 判断函数 | 判断逻辑 | 目标下载器 |
|---|---|---|---|
| DASH | `IsDash()` (line 706) | `uri_.find(".mpd")` 或 `uri_.find("type=mpd")` | `DashMediaDownloader` |
| HLS (支持Seek) | `IsSeekToTimeSupported()` (line 383) + mimeType 检查 | 非 m3u8 mimeType + m3u8 URI或.mp4 HLS | `HlsMediaDownloader` |
| HLS (mime明确) | `mimeType_ == AVMimeTypes::APPLICATION_M3U8` (line 305) | MIME类型匹配 | `HlsMediaDownloader` |
| Plain HTTP | `uri_.compare(0, 4, "http")` (line 300) | 纯 HTTP/HTTPS 协议，无 M3U8/MPD | `HttpMediaDownloader` |

**E5**: `CheckIsM3U8Uri()` (line 629~666) 支持多种 m3u8 格式识别：
```cpp
// 支持非标准扩展名: ?autotype=m3u8, .doplaylist?auto=m3u8
// 先找资源类型(文件名扩展名)，再查 query 参数中 `=m3u8`
```

### 1.3 三路下载器类型声明

**文件**: `services/media_engine/plugins/source/http_source/http_source_plugin.h`
**行号**: 57~80 行（成员变量）

```cpp
private:
    uint32_t bufferSize_;
    uint32_t waterline_;
    std::shared_ptr<MediaDownloader> downloader_;   // 基类指针持有三路之一
    std::shared_ptr<MediaSourceLoaderCombinations> loaderCombinations_; // 离线缓存组合器
    std::map<std::string, std::string> httpHeader_;
    std::string mimeType_;
    std::string uri_;
```

**文件**: `services/media_engine/plugins/source/http_source/http_source_plugin.cpp`
**行号**: 22~26 行（常量定义）

```cpp
const std::string DASH_SUFFIX = ".mpd";
const std::string EQUAL_M3U8 = "=" + LOWER_M3U8;   // "=m3u8"
const std::string DASH_LIST[] = {
    std::string(".mpd"),
    std::string("type=mpd"),
};
```

---

## 2. DownloadMonitor 装饰器：重试与监控注入

### 2.1 装饰器模式结构

**文件**: `services/media_engine/plugins/source/http_source/monitor/download_monitor.h`
**行号**: 47 行

```cpp
class DownloadMonitor : public MediaDownloader, public std::enable_shared_from_this<DownloadMonitor> {
    // 继承 MediaDownloader，所有方法透传至 downloader_
    // 额外注入：HttpMonitorLoop 重试调度 + 错误码映射 + 统计上报
```

**E6**: `Init()` (download_monitor.cpp line 49~71) — 创建后台 Task 定期执行重试循环：

```cpp
task_ = std::make_shared<Task>(std::string("OS_HttpMonitor"));
task_->RegisterJob([this] { return HttpMonitorLoop(); });
task_->Start();   // 50ms 周期轮询 retryTasks_ 队列
```

### 2.2 HttpMonitorLoop 重试循环

**文件**: `services/media_engine/plugins/source/http_source/monitor/download_monitor.cpp`
**行号**: 42~59 行

```cpp
int64_t DownloadMonitor::HttpMonitorLoop()
{
    RetryRequest task;
    {
        AutoLock lock(taskMutex_);
        if (!retryTasks_.empty()) {
            task = retryTasks_.front();
            retryTasks_.pop_front();
        }
    }
    if (task.request && task.function) {
        task.function();  // 执行重试函数
    }
    return RETRY_SEG * MICROSECONDS_TO_MILLISECOND; // 50ms
}
```

### 2.3 错误码映射表

**文件**: `services/media_engine/plugins/source/http_source/monitor/download_monitor.h`
**行号**: 126~143 行

```cpp
std::map<int32_t, MediaServiceErrCode> clientErrorCodeMap_ = {
    {-6, MSERR_IO_SSL_SERVER_CERT_UNTRUSTED},
    {-5, MSERR_IO_CONNECTION_TIMEOUT},
    {-4, MSERR_IO_NETWORK_ACCESS_DENIED},
    {-2, MSERR_IO_RESOURE_NOT_FOUND},
    {1,   MSERR_IO_UNSUPPORTTED_REQUEST},
    {2,   MSERR_DATA_SOURCE_IO_ERROR},
    {5,   MSERR_IO_CANNOT_FIND_HOST},
    // ...
};
// 服务器错误码（500/502/503 等）映射到客户端 MediaServiceErrCode
const std::set<int32_t> SERVER_RETRY_ERROR_CODES = {
    300, 301, 302, 303, 304, 305, 403, 500, 0
};
const std::set<int32_t> CLIENT_RETRY_ERROR_CODES = {
    23, 25, 26, 28, 56, 18, 0  // CURLE_*
};
```

### 2.4 Read 数据透传与统计

**文件**: `services/media_engine/plugins/source/http_source/monitor/download_monitor.cpp`
**行号**: 124~140 行

```cpp
Status DownloadMonitor::Read(unsigned char* buff, ReadDataInfo& readDataInfo)
{
    auto ret = downloader_->Read(buff, readDataInfo);
    time(&lastReadTime_);
    if (ULLONG_MAX - haveReadData_ > readDataInfo.realReadLength_) {
        haveReadData_ += readDataInfo.realReadLength_;  // 累计读取字节统计
    }
    if (readDataInfo.isEos_ && ret == Status::END_OF_STREAM) {
        MEDIA_LOG_I("buffer is empty, read eos." PUBLIC_LOG_U64, haveReadData_);
    }
    return ret;
}
```

---

## 3. StreamDemuxer PullData 三路分发机制

### 3.1 三路分发入口

**文件**: `services/media_engine/modules/demuxer/stream_demuxer.cpp`
**行号**: `PullData()` — 317~358 行

```cpp
Status StreamDemuxer::PullData(int32_t streamID, uint64_t offset, size_t size,
    std::shared_ptr<Plugins::Buffer>& data, bool isSniffCase)
{
    // [E7] line 320: HLS / UNSEEKABLE 流直接走 ReadRetry，不做 offset 对齐
    if (source_->IsSeekToTimeSupported() || source_->GetSeekable() == Plugins::Seekable::UNSEEKABLE) {
        err = ReadRetry(streamID, offset, readSize, data, isSniffCase);
        return err;
    }
    // [E8] line 332: VOD / 可 seek 流，按 totalSize 对齐 offset 后读取
    if (offset >= totalSize) {
        return Status::END_OF_STREAM;
    }
    // [E9] line 337: 带缓存的分段读取
    err = PullDataWithCache(streamID, offset, readSize, data, isSniffCase);
}
```

### 3.2 ReadRetry 重试逻辑

**文件**: `services/media_engine/modules/demuxer/stream_demuxer.cpp`
**行号**: 271~308 行

```cpp
Status StreamDemuxer::ReadRetry(int32_t streamID, uint64_t offset, size_t size,
    std::shared_ptr<Plugins::Buffer>& data, bool isSniffCase)
{
    Status err = Status::OK;
    int32_t retryTimes = 0;
    while (true && !isInterruptNeeded_.load()) {
        err = source_->Read(streamID, data, offset, size);
        if (err == Status::ERROR_AGAIN && !isSniffCase) {
            return err;  // 非 sniffing 场景，直接返回 AGAIN
        }
        if (err != Status::END_OF_STREAM && data->GetMemory()->GetSize() == 0) {
            std::unique_lock<std::mutex> lock(mutex_);
            readCond_.wait_for(lock, std::chrono::milliseconds(TRY_READ_SLEEP_TIME),
                               [&] { return isInterruptNeeded_.load(); }); // 等 10ms 再试
            retryTimes++;
            if (retryTimes > TRY_READ_TIMES) break;  // 最多重试 10 次 × 10ms = 100ms
        }
        break;
    }
    return err;
}
```

**E10**: `TRY_READ_SLEEP_TIME = 10ms`, `TRY_READ_TIMES = 10`，即单次 PullData 最多等待 100ms。

### 3.3 PullDataWithCache 缓存合并

**文件**: `services/media_engine/modules/demuxer/stream_demuxer.cpp`
**行号**: 99~157 行

```cpp
Status StreamDemuxer::PullDataWithCache(int32_t streamID, uint64_t offset, size_t size,
    std::shared_ptr<Buffer>& bufferPtr, bool isSniffCase)
{
    // 1. 命中缓存：直接从 cacheDataMap_[streamID] 读取
    uint64_t offsetInCache = offset - cacheDataMap_[streamID].GetOffset();
    if (size <= memory->GetSize() - offsetInCache) {
        bufferPtr->GetMemory()->Write(memory->GetReadOnlyData() + offsetInCache, size, 0);
        return Status::OK;
    }
    // 2. 缓存部分命中：从缓存读一部分，剩余走 PullData 补齐
    bufferPtr->GetMemory()->Write(memory->GetReadOnlyData() + offsetInCache,
                                  memory->GetSize() - offsetInCache, 0);
    uint64_t remainOffset = cacheDataMap_[streamID].GetOffset() + memory->GetSize();
    uint64_t remainSize = size - (memory->GetSize() - offsetInCache);
    Status ret = PullData(streamID, remainOffset, remainSize, tempBuffer, isSniffCase);
    // 3. 合并缓存：将新数据与旧缓存合并，写回 cacheDataMap_
    std::shared_ptr<Buffer> mergedBuffer = Buffer::CreateDefaultBuffer(
        tempBuffer->GetMemory()->GetSize() + memory->GetSize());
    mergedBuffer->GetMemory()->Write(memory->GetReadOnlyData(), memory->GetSize(), 0);
    mergedBuffer->GetMemory()->Write(tempBuffer->GetMemory()->GetReadOnlyData(),
                                      tempBuffer->GetMemory()->GetSize(), memory->GetSize());
    cacheDataMap_[streamID].SetData(mergedBuffer);
}
```

### 3.4 PullDataWithoutCache 写入缓存

**文件**: `services/media_engine/modules/demuxer/stream_demuxer.cpp`
**行号**: 221~250 行

```cpp
Status StreamDemuxer::PullDataWithoutCache(int32_t streamID, uint64_t offset, size_t size,
    std::shared_ptr<Buffer>& bufferPtr, bool isSniffCase)
{
    // 1. 直接 PullData 读取数据
    Status ret = PullData(streamID, offset, size, bufferPtr, isSniffCase);
    // 2. DASH 流：将已有缓存与新数据合并（ProcInnerDash）
    if (cacheDataMap_.find(streamID) != cacheDataMap_.end()) {
        ret = ProcInnerDash(streamID, offset, bufferPtr);  // 合并到 cache
    }
    // 3. 首次写入缓存
    if (cacheDataMap_[streamID].GetData() == nullptr) {
        auto buffer = Buffer::CreateDefaultBuffer(bufferPtr->GetMemory()->GetSize());
        buffer->GetMemory()->Write(bufferPtr->GetMemory()->GetReadOnlyData(),
                                    bufferPtr->GetMemory()->GetSize(), 0);
        cacheDataMap_[streamID].Init(buffer, offset);  // 记录起始 offset
    }
}
```

### 3.5 DASH 特殊缓存合并 ProcInnerDash

**文件**: `services/media_engine/modules/demuxer/stream_demuxer.cpp`
**行号**: 183~198 行

```cpp
Status StreamDemuxer::ProcInnerDash(int32_t streamID,  uint64_t offset,
    std::shared_ptr<Buffer>& bufferPtr)
{
    if (IsDash()) {
        // 将旧缓存（cacheDataMap_[streamID]）和新 buffer 合并为一个新 Buffer
        std::shared_ptr<Buffer> mergedBuffer = Buffer::CreateDefaultBuffer(
            bufferMemory->GetSize() + cacheMemory->GetSize());
        mergeMemory->Write(cacheMemory->GetReadOnlyData(), cacheMemory->GetSize(), 0);
        mergeMemory->Write(bufferMemory->GetReadOnlyData(), bufferMemory->GetSize(),
                           cacheMemory->GetSize());
        cacheDataMap_[streamID].SetData(mergedBuffer);
        // 合并后 cache offset 不变，覆盖的是起始 offset 的连续数据
    }
    return Status::OK;
}
```

---

## 4. 三路下载器类体系

### 4.1 MediaDownloader 基类

**文件**: `services/media_engine/plugins/source/http_source/media_downloader.h`
（基类，三路下载器均继承）

```cpp
class MediaDownloader {
    virtual Status Read(unsigned char* buff, ReadDataInfo& readDataInfo) = 0;
    virtual bool Open(const std::string& url, ...) = 0;
    virtual void Close(bool isAsync) = 0;
    virtual bool SeekToTime(int64_t seekTime, SeekMode mode) = 0;
    virtual size_t GetContentLength() const = 0;
    virtual Seekable GetSeekable() const = 0;
    // ...
};
```

### 4.2 HlsMediaDownloader — HLS 分片管理器

**文件**: `services/media_engine/plugins/source/http_source/hls/hls_media_downloader.h`
**行号**: 44 行（成员变量）

```cpp
private:
    std::shared_ptr<HlsSegmentManager> videoSegManager_;
    std::shared_ptr<HlsSegmentManager> audioSegManager_;
    std::shared_ptr<HlsSegmentManager> subtitlesSegManager_;
    // 三路 SegmentManager（视频/音频/字幕），每路独立管理 M3U8 分片下载
```

### 4.3 DashMediaDownloader — DASH MPD + 分片

**文件**: `services/media_engine/plugins/source/http_source/dash/dash_media_downloader.h`
**行号**: 99~108 行

```cpp
private:
    std::shared_ptr<DashMpdDownloader> mpdDownloader_;  // MPD 解析器
    ThreadSafeContainer<std::vector<std::shared_ptr<DashSegmentDownloader>>> segmentDownloaders_;
    // 每个 streamId 对应一个 DashSegmentDownloader，支持 BitrateParam 多码率切换
```

### 4.4 HttpMediaDownloader — 普通 HTTP 流

**文件**: `services/media_engine/plugins/source/http_source/http/http_media_downloader.h`
**行号**: 293 行（文件总行数 2259 行）
**E11**: 直接基于 HTTP Range 请求读取，无切片概念，适用于 MP4/FLV 等单一文件容器。

---

## 5. 数据流整体路径

```
应用层 MediaSource
        │
        ▼
HttpSourcePlugin::SetSource()
        │ SetDownloaderBySource() — 三路分发
        ▼
┌───────────────────────────────────────────────┐
│            DownloadMonitor (装饰器)            │
│  ├─ 重试调度: HttpMonitorLoop (50ms 周期)       │
│  ├─ 错误码映射: clientErrorCodeMap_            │
│  └─ 统计上报: haveReadData_ / reportInfo_      │
└───────────────────────────────────────────────┘
        │
   ┌────┴──────────────────────┐
   ▼                            ▼
HlsMediaDownloader     DashMediaDownloader     HttpMediaDownloader
   │                              │                    │
   │ HlsSegmentManager           │ DashMpdDownloader   │
   │   - videoSegManager_       │   - segmentDownloaders_
   │   - audioSegManager_       │   (per streamId)     │
   │   - subtitlesSegManager_   │                     │
   └──────────────────────────────┘                    │
        │                                                    │
        ▼ Read(buff, readDataInfo)                          │
   StreamDemuxer::PullData(streamId, offset, size, buffer)  │
        │ 三路分发:                                          │
        ├─ ReadRetry (HLS/UNSEEKABLE: 10ms×10次)            │
        ├─ PullDataWithCache (VOD seekable: 缓存命中合并)    │
        └─ PullDataWithoutCache (VOD seekable: 缓存写入)      │
        │                                                    │
        ▼ Buffer 返回给 Pipeline 上游 Filter                  │
   DemuxerFilter → AudioDecoderFilter / VideoDecoderFilter
```

---

## 6. 关联记忆条目

| ID | 主题 | 关联说明 |
|---|---|---|
| S106 | MediaEngine Source 模块流媒体基础设施 | S128 的父级，S106 聚焦 Source.cpp + M3U8 解析入口 |
| S120 | HttpSourcePlugin 三路下载器路由 | 本条目前身（草案状态） |
| S122 | MediaEngine Streaming 基础设施 | S122 补充 HTTP 插件路由、协议推断、Streaming 分片管理 |
| S75/S97/S101 | StreamDemuxer 细节 | 本条目深度解析 PullData 三路机制，与 S75/S97/S101 互补 |
| S55/S83/S92/S114 | 错误码与回调体系 | DownloadMonitor 错误码映射与三层回调关联 |
| S113 | SEI 信息解析框架 | StreamDemuxer 供给数据给 SeiParserFilter |

---

## 7. 关键行号速查表

| 文件 | 行号 | 内容 |
|---|---|---|
| http_source_plugin.cpp | 277~307 | SetDownloaderBySource 三路分发 |
| http_source_plugin.cpp | 300~313 | InitHttpSource → HttpMediaDownloader |
| http_source_plugin.cpp | 383~394 | IsSeekToTimeSupported() 判断 |
| http_source_plugin.cpp | 629~666 | CheckIsM3U8Uri() 多格式识别 |
| http_source_plugin.cpp | 706~712 | IsDash() .mpd/type=mpd 检测 |
| download_monitor.cpp | 42~59 | HttpMonitorLoop 50ms 重试调度 |
| download_monitor.cpp | 124~140 | Read 透传 + 统计 haveReadData_ |
| download_monitor.h | 126~143 | clientErrorCodeMap_ 错误码映射 |
| stream_demuxer.cpp | 271~308 | ReadRetry 10ms×10次重试 |
| stream_demuxer.cpp | 317~358 | PullData 三路分发入口 |
| stream_demuxer.cpp | 183~198 | ProcInnerDash DASH 缓存合并 |
| stream_demuxer.cpp | 99~157 | PullDataWithCache 缓存命中合并 |
| stream_demuxer.cpp | 221~250 | PullDataWithoutCache 缓存写入 |
| hls_media_downloader.h | 44 | 三路 HlsSegmentManager 成员 |
| dash_media_downloader.h | 99~108 | mpdDownloader + segmentDownloaders_ |

---

## 8. 版本与日期

- **draft**: true
- **version**: 1.0
- **author**: builder
- **created_at**: 2026-05-14T09:13:00+08:00
- **updated_at**: 2026-05-14T09:13:00+08:00
- **status**: draft
- **关联**: S106, S120, S122, S75, S97, S101, S55, S83, S92, S114, S113