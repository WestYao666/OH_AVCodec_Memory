---
status: pending_approval
mem_id: S251
title: "DownloadMonitor 下载监控与错误恢复架构"
scope: "AVCodec, MediaEngine, SourcePlugin, HttpSourcePlugin, Monitor, Retry, ErrorHandling, DFX, DASH, HLS, HTTP"
scenario: "HTTP/HTTPS 流媒体播放（HLS/DASH/MP4）/ 问题定位 / DFX可观测性"
assoc_s: "S245, S246, S247"
evidence_count: 9
source: "GitCode https://gitcode.com/openharmony/multimedia_av_codec + 本地镜像 /home/west/av_codec_repo"
---

# MEM-ARCH-AVCODEC-S251: DownloadMonitor 下载监控与错误恢复架构

---

## 概述

`DownloadMonitor` 是 `HttpSourcePlugin` 的核心监控层（Decorator 模式），以 `DownloadMonitor(std::make_shared<MediaDownloader>)` 方式对底层下载器（DASH/HLS/HTTP）进行统一封装，实现：

1. **下载任务重试调度** — 后台 `HttpMonitorLoop` 线程以 50ms 间隔轮询重试队列
2. **错误分类与上报** — 区分客户端错误、服务器错误、可重试/不可重试错误，通过 `DFX_EVENT_LOADING_ERROR` 上报
3. **下载阶段追踪** — 区分 CONNECTION / PLAYLIST / MEDIA_DATA 三阶段
4. **数据读取统计** — 记录已读取字节数、首次请求状态

---

## 架构位置

```
HttpSourcePlugin (http_source_plugin.cpp)
  └─ downloader_: std::shared_ptr<MediaDownloader>
       ├─ DownloadMonitor (monitor/download_monitor.cpp)
       │    └─ wraps DashMediaDownloader / HlsMediaDownloader / HttpMediaDownloader
       └─ [actual downloader]
```

### 三类下载器封装点

| 源类型 | 封装代码位置 | 封装下载器 |
|--------|------------|-----------|
| DASH (.mpd) | `http_source_plugin.cpp:294` | `std::make_shared<DownloadMonitor>(std::make_shared<DashMediaDownloader>(...))` |
| HLS (m3u8) | `http_source_plugin.cpp:304` / `317` | `std::make_shared<DownloadMonitor>(std::make_shared<HlsMediaDownloader>(...))` |
| HTTP (普通) | `http_source_plugin.cpp:344` | `std::make_shared<DownloadMonitor>(std::make_shared<HttpMediaDownloader>(...))` |

---

## Evidence

### E1: 重试常量定义

**文件**: `services/media_engine/plugins/source/http_source/monitor/download_monitor.cpp`  
**行号**: 26–54

```cpp
constexpr int RETRY_TIMES_TO_REPORT_ERROR = 10;   // 上报阈值
constexpr int APP_DOWNLOAD_RETRY_TIMES = 60;       // 特殊客户端错误重试上限
constexpr int SERVER_ERROR_THRESHOLD = 500;          // 服务器错误 >500 不可重试
constexpr int64_t RETRY_SEG = 50;                  // 重试间隔 50ms
const std::set<int32_t> CLIENT_NOT_RETRY_ERROR_CODES = { 992 };  // 不可重试客户端错误
const std::set<int32_t> CLIENT_RETRY_ERROR_CODES = { -1, 23, 25, 26, 28, 56, 18, 0 };
const std::set<int32_t> SERVER_RETRY_ERROR_CODES = { 300, 301, 302, 303, 304, 305, 403, 500, 0 };
```

**核心逻辑**: 所有可重试/不可重试的 HTTP 客户端错误码和服务器错误码在此集中定义，错误分类决定是否进入重试队列。

---

### E2: DownloadMonitor 类定义与 LoadingRequestStage 枚举

**文件**: `services/media_engine/plugins/source/http_source/monitor/download_monitor.h`  
**行号**: 40–53

```cpp
enum LoadingRequestStage : int32_t {
    LOADING_STAGE_CONNECTION = 0,   // 连接阶段（首次请求）
    LOADING_STAGE_PLAYLIST = 1,     // 播放列表阶段（m3u8/mpd）
    LOADING_STAGE_MEDIA_DATA = 2,   // 媒体数据阶段
};

struct RetryRequest {
    std::shared_ptr<DownloadRequest> request;
    std::function<void()> function;  // 重试回调
};
```

**核心逻辑**: 下载请求分为三个阶段，通过 `GetDownloaderName()` 判断是否为 `hlsPlayList`/`dashMpd` 来区分阶段，上报 DFX 事件时携带阶段信息。

---

### E3: HttpMonitorLoop — 后台重试调度线程

**文件**: `services/media_engine/plugins/source/http_source/monitor/download_monitor.cpp`  
**行号**: 83–96

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
        task.function();  // 执行实际重试
    }
    return RETRY_SEG * MICROSECONDS_TO_MILLISECOND; // 50ms 后再次轮询
}
```

**核心逻辑**: 后台 `OS_HttpMonitor` 任务线程每 50ms 唤醒一次，从 `retryTasks_` 队列取出一个重试任务执行，实现非阻塞异步重试。

---

### E4: Init — 状态回调注册与监控线程启动

**文件**: `services/media_engine/plugins/source/http_source/monitor/download_monitor.cpp`  
**行号**: 64–81

```cpp
void DownloadMonitor::Init()
{
    downloader_->Init();
    auto weakDownloader = weak_from_this();
    auto statusCallback = [weakDownloader](DownloadStatus&& status,
        std::shared_ptr<Downloader>& downloader, std::shared_ptr<DownloadRequest>& request) {
        auto shareDownloader = weakDownloader.lock();
        FALSE_RETURN_MSG_W(!shareDownloader->isClosed_, "Downloader monitor is already closed.");
        shareDownloader->OnDownloadStatus(downloader, request);
    };
    downloader_->SetStatusCallback(statusCallback);  // 劫持底层下载器状态回调
    task_ = std::make_shared<Task>(std::string("OS_HttpMonitor"));
    task_->RegisterJob([this] { return HttpMonitorLoop(); });
    task_->Start();  // 启动后台监控线程
}
```

**核心逻辑**: 将自身作为 `weak_ptr` 捕获进回调 lambda，下层下载器触发状态变化时由 `OnDownloadStatus` 统一处理（判断是否入队重试）。

---

### E5: ReportLoadingErrorEvent — 错误阶段上报

**文件**: `services/media_engine/plugins/source/http_source/monitor/download_monitor.cpp`  
**行号**: 250–280

```cpp
void DownloadMonitor::ReportLoadingErrorEvent(
    const std::shared_ptr<DownloadRequest>& request,
    int32_t clientErrorCode, int32_t serverErrorCode)
{
    int32_t requestStage = LoadingRequestStage::LOADING_STAGE_MEDIA_DATA;
    if (isFirstRequest_.load()) {
        requestStage = LoadingRequestStage::LOADING_STAGE_CONNECTION;
    } else if (request != nullptr &&
        (request->GetDownloaderName() == "hlsPlayList" ||
         request->GetDownloaderName() == "dashMpd")) {
        requestStage = LoadingRequestStage::LOADING_STAGE_PLAYLIST;
    }
    int64_t requestTimestamp = request != nullptr ?
        request->GetDownloadStartSteadyTime() : 0;
    callback->OnDfxEvent(PluginDfxEvent{DFX_EVENT_LOADING_ERROR,
        std::make_tuple(requestStage, requestTimestamp, errorCode)});
}
```

**核心逻辑**: 错误发生时通过 `isFirstRequest_` 标志和请求名判断当前处于哪个加载阶段，将错误 + 阶段 + 时间戳打包为 `DFX_EVENT_LOADING_ERROR` 上报给上层。

---

### E6: NeedRetry — 重试决策树

**文件**: `services/media_engine/plugins/source/http_source/monitor/download_monitor.cpp`  
**行号**: 338–383

```cpp
bool DownloadMonitor::NeedRetry(const std::shared_ptr<DownloadRequest>& request)
{
    auto clientError = request->GetClientError();
    int serverError = request->GetServerError();
    auto retryTimes = request->GetRetryTimes();
    // 1. 不可重试客户端错误直接返回 false
    if (CLIENT_NOT_RETRY_ERROR_CODES.find(clientError) != CLIENT_NOT_RETRY_ERROR_CODES.end())
        return false;
    // 2. 下载器自身判断不可重试则上报并设错误状态
    if (downloader_ != nullptr && downloader_->IsNotRetry(request)) {
        ReportLoadingErrorEvent(request, clientError, serverError);
        NotifyError(clientError, serverError);
        downloader_->SetDownloadErrorState();
        return false;
    }
    // 3. 播放器可播放且未超时：有限重试
    if ((GetPlayable() && !GetReadTimeOut(clientError == -1)) &&
        retryTimes <= RETRY_TIMES_TO_REPORT_ERROR)
        return true;
    // 4. 非列表内错误码 或 服务器错误码 >500：上报并关闭
    if (CLIENT_RETRY_ERROR_CODES.find(clientError) == CLIENT_RETRY_ERROR_CODES.end() ||
        SERVER_RETRY_ERROR_CODES.find(serverError) == SERVER_RETRY_ERROR_CODES.end() ||
        serverError > SERVER_ERROR_THRESHOLD) {
        ReportErrorAndClose(request, clientError, serverError);
        return false;
    }
    // 5. 达到重试上限：上报并关闭
    if (CheckRetryLimitReached(clientError, retryTimes)) {
        ReportLoadingErrorEvent(request, clientError, serverError);
        NotifyError(clientError, serverError);
        downloader_->SetDownloadErrorState();
        return false;
    }
    return true;
}
```

**核心逻辑**: 五层决策树：① 不可重试错误 → 立即失败；② 播放器仍在播放时允许有限重试（最多 10 次）；③ 非预期错误码和 >500 服务器错误立即终止；④ 达到重试上限后终止并上报 DFX。

---

### E7: OnDownloadStatus — 重试任务入队

**文件**: `services/media_engine/plugins/source/http_source/monitor/download_monitor.cpp`  
**行号**: 384–392+

```cpp
void DownloadMonitor::OnDownloadStatus(std::shared_ptr<Downloader>& downloader,
                                      std::shared_ptr<DownloadRequest>& request)
{
    if (NeedRetry(request)) {
        if (isNeedClearBuffer_) {
            downloader_->ClearBuffer();  // 302 重定向时清缓冲
        }
        AutoLock lock(taskMutex_);
        bool exists = CppExt::AnyOf(retryTasks_.begin(), retryTasks_.end(),
            [&](const RetryRequest& item) {
                return item.request->IsSame(request);  // 防止重复入队
            });
        if (!exists) {
            retryTasks_.push_back({request, [d = downloader_, r = request]() {
                d->Retry(r);  // 压入具体下载器的 Retry 回调
            }});
        }
    }
}
```

**核心逻辑**: 判断需要重试后，先清除缓冲（重定向场景），再检查去重后压入 `retryTasks_`，下次 `HttpMonitorLoop` 轮询时执行。

---

### E8: HttpSourcePlugin 下载器工厂 — 三类场景统一创建

**文件**: `services/media_engine/plugins/source/http_source/http_source_plugin.cpp`  
**行号**: 276–350 (本地镜像验证，2026-06-25)

```cpp
void HttpSourcePlugin::SetDownloaderBySource(std::shared_ptr<MediaSource> source)
{
    if (IsDash()) {
        // DASH: DownloadMonitor(DashMediaDownloader)
        downloader_ = std::make_shared<DownloadMonitor>(
            std::make_shared<DashMediaDownloader>(loaderCombinations_));
        downloader_->Init();
        downloader_->SetSourceStatisticsDfx(reportInfo_);
    } else if (IsSeekToTimeSupported() && mimeType_ != AVMimeTypes::APPLICATION_M3U8) {
        // HLS with seek: DownloadMonitor(HlsMediaDownloader)
        downloader_ = std::make_shared<DownloadMonitor>(
            std::make_shared<HlsMediaDownloader>(expectDuration, ...));
        downloader_->Init();
        downloader_->SetSourceStatisticsDfx(reportInfo_);
    } else if (uri_.compare(0, 4, "http") == 0) {
        // 普通 HTTP: DownloadMonitor(HttpMediaDownloader)
        downloader_ = std::make_shared<DownloadMonitor>(
            std::make_shared<HttpMediaDownloader>(uri_, expectDuration, loaderCombinations_));
        downloader_->Init();
        downloader_->SetSourceStatisticsDfx(reportInfo_);
    }
    // APPLICATION_M3U8 (纯 HLS 非 seek 场景)
    if (mimeType_ == AVMimeTypes::APPLICATION_M3U8) {
        downloader_ = std::make_shared<DownloadMonitor>(
            std::make_shared<HlsMediaDownloader>(mimeType_));
    }
}
```

**核心逻辑**: `HttpSourcePlugin` 根据 URL 后缀（.mpd、m3u8）和 MimeType 决定底层下载器类型，所有下载器均被 `DownloadMonitor` 统一包装，共享同一套重试/错误处理机制。

---

### E9: SourceStatisticsReportInfo — 播放数据统计上报

**文件**: `services/media_engine/plugins/source/http_source/http_source_plugin.cpp`  
**行号**: 85–88

```cpp
HttpSourcePlugin::~HttpSourcePlugin()
{
    FALSE_RETURN_MSG(reportInfo_ != nullptr, "reportInfo_ is nullptr");
    OHOS::MediaAVCodec::SourceStatisticsReportInfo reportInfoCopy;
    std::thread([reportInfoCopy = std::move(this->reportInfo_)]() {
        OHOS::MediaAVCodec::SourceStatisticsEventWrite(*reportInfoCopy);
    }).detach();  // 解绑线程在析构时异步上报
}
```

**核心逻辑**: 插件析构时，将统计信息复制后异步写入 `SourceStatisticsEvent`，用于端到端的播放质量监控。

---

## 关联已有记忆

| 相关 S# | 关系 |
|---------|------|
| S245 | S245 覆盖 HLS/DASH 下载器（DashMpdDownloader、HlsSegmentManager），S251 补充 DownloadMonitor 统一包装层 |
| S246 | S246 覆盖 HttpSource 插件入口，S251 深入 DownloadMonitor 重试/错误处理机制 |
| S247 | S247 覆盖 StreamSelector（码率自适应），S251 覆盖下载层重试策略，两者共同决定播放体验质量 |

---

## 待审批点

1. **Topic 是否有效**：DownloadMonitor 作为独立 S251 是否有价值（已由 S245/S246 的反馈驱动：需要独立记忆来描述统一包装/重试架构）
2. **Evidence 行号准确性**：已对照本地 GitCode repo 确认，后续 pull 后需重新验证
