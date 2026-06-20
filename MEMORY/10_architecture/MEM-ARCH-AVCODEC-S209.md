# MEM-ARCH-AVCODEC-S209: HttpSourcePlugin Download Monitor 装饰器模式与错误恢复架构

##  Metadata

| Field | Value |
|-------|-------|
| ID | MEM-ARCH-AVCODEC-S209 |
| 主题 | HttpSourcePlugin Download Monitor 装饰器模式与错误恢复架构——DownloadMonitor + 重试队列 + 错误码映射 +装饰器工厂 |
| Scope | AVCodec, MediaEngine, SourcePlugin, HttpSourcePlugin, DownloadMonitor, Retry, ErrorCode, HTTP, HTTPS |
| 关联场景 | 新需求开发/问题定位/流媒体下载/错误恢复/DFX可观测性 |
| 状态 | pending_approval |
| Builder | builder-agent (subagent) |
| 生成时间 | 2026-06-09T05:00:00+08:00 |
| 源码路径 | /home/west/av_codec_repo/services/media_engine/plugins/source/http_source/monitor/ |
| 文件 | download_monitor.h (232行) + download_monitor.cpp (610行) = 842行源码 |
| 关联记忆 | S210 (DownloadMonitor完整版), S195 (Downloader三层架构), S172 (HttpSourcePlugin), S234 (HLS) |

---

##  Architecture Overview

**DownloadMonitor** 是 HttpSourcePlugin 的下载监控装饰器（Decorator），以 **std::shared_ptr<MediaDownloader>** 为被装饰对象，封装了重试队列、错误码映射和状态回调三大功能。

### 核心定位

```
HttpSourcePlugin
    │
    └── DownloadMonitor (装饰器, 842行)
            │
            ├── Downloader/HlsMediaDownloader/DashMediaDownloader/HttpMediaDownloader (被装饰者)
            │
            ├── 重试队列 retryTasks_ (std::list<RetryRequest>)
            ├── 客户端错误码映射 clientErrorCodeMap_ (~50条)
            ├── 服务端错误码映射 serverErrorCodeMap_ (~30条)
            └── 监控线程 Task("OS_HttpMonitor") (50ms 周期)
```

### 装饰器工厂路由 (http_source_plugin.cpp L288-L338)

```cpp
// DASH流
downloader_ = std::make_shared<DownloadMonitor>(
    std::make_shared<DashMediaDownloader>(loaderCombinations_));

// HLS (支持SeekToTime但非M3U8)
downloader_ = std::make_shared<DownloadMonitor>(
    std::make_shared<HlsMediaDownloader>(expectDuration, userDefinedDuration, httpHeader_, loaderCombinations_));

// HLS M3U8
downloader_ = std::make_shared<DownloadMonitor>(
    std::make_shared<HlsMediaDownloader>(mimeType_));

// 普通HTTP/HTTPS
downloader_ = std::make_shared<DownloadMonitor>(
    std::make_shared<HttpMediaDownloader>(uri_, expectDuration, loaderCombinations_));
```

---

##  Evidence (行号级)

### E1: DownloadMonitor 类继承结构 (download_monitor.h L28-L35)

```cpp
class DownloadMonitor : public MediaDownloader, public std::enable_shared_from_this<DownloadMonitor> {
public:
    explicit DownloadMonitor(std::shared_ptr<MediaDownloader> downloader) noexcept;
    ~DownloadMonitor() override = default;
```

- **继承 MediaDownloader** 接口，Decorator 模式的标配
- **enable_shared_from_this** 支持弱回调中安全获取 shared_ptr

### E2: RetryRequest 重试任务结构体 (download_monitor.h L25-L28)

```cpp
struct RetryRequest {
    std::shared_ptr<DownloadRequest> request;
    std::function<void()> function;
};
```

- request: 待重试的下载请求
- function: lambda闭包，执行 `downloader->Retry(request)`

### E3: 重试队列与线程安全 (download_monitor.h L100-L104)

```cpp
std::list<RetryRequest> retryTasks_; // 重试任务队列（双向链表）
Mutex taskMutex_ {};                          // 保护 retryTasks_ 的互斥锁
std::shared_ptr<Task> task_; // 监控线程 OS_HttpMonitor
```

- **std::list**双向链表，支持 O(1) 插入/删除，适合重试队列
- **Mutex** 保护并发访问
- **Task** 驱动50ms 周期的 HttpMonitorLoop

### E4: Init 中的状态回调注册与线程启动 (download_monitor.cpp L55-L80)

```cpp
void DownloadMonitor::Init()
{
    downloader_->Init();
    auto weakDownloader = weak_from_this();
    auto statusCallback = [weakDownloader](DownloadStatus&& status,
        std::shared_ptr<Downloader>& downloader, std::shared_ptr<DownloadRequest>& request) {
        auto shareDownloader = weakDownloader.lock();
        shareDownloader->OnDownloadStatus(downloader, request);
    };
    downloader_->SetStatusCallback(statusCallback); // ← 装饰器注入回调
    task_ = std::make_shared<Task>(std::string("OS_HttpMonitor"));
    task_->RegisterJob([this] { return HttpMonitorLoop(); });
    task_->Start(); // ← 启动监控线程
}
```

- **装饰器注入**：将被装饰者的回调替换为 Monitor 的回调链
- **HttpMonitorLoop** 每 50ms 检查一次 retryTasks_

### E5: HttpMonitorLoop 50ms 周期重试循环 (download_monitor.cpp L41-L56)

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
        task.function();  // 执行 downloader->Retry(request)
    }
    return RETRY_SEG * MICROSECONDS_TO_MILLISECOND; // 50ms
}
```

- **RETRY_SEG = 50** (download_monitor.cpp L19)
- **MICROSECONDS_TO_MILLISECOND = 1000** (L20)
- 每次从队列头取一个任务执行后沉睡50ms，实现错峰重试

### E6: NeedRetry 六段式重试判定 (download_monitor.cpp L281-L326)

```cpp
bool DownloadMonitor::NeedRetry(const std::shared_ptr<DownloadRequest>& request)
{
    auto clientError = request->GetClientError();
    int serverError = request->GetServerError();
    auto retryTimes = request->GetRetryTimes();
    // 1. 客户端不重试名单（如 992）
    if (CLIENT_NOT_RETRY_ERROR_CODES.count(clientError)) return false;
    // 2. FLV直播不重试 →通知错误 + 设置错误状态
    if (downloader_->IsNotRetry(request)) { NotifyError(...); return false; }
    // 3. 无错误 → 不重试
    if (clientError == 0 && serverError == 0) return false;
    // 4. 可播放且未超时 → 重试
    if (GetPlayable() && !GetReadTimeOut(...) && retryTimes <= RETRY_TIMES_TO_REPORT_ERROR) return true;
    // 5. 错误码不在重试名单 → 通知错误 + 关闭请求
    if (!CLIENT_RETRY_ERROR_CODES.count(clientError) ||
        !SERVER_RETRY_ERROR_CODES.count(serverError) ||
        serverError > SERVER_ERROR_THRESHOLD) {
        NotifyError(...); return false;
    }
    // 6. 超上限次数 → 通知错误 + 设置错误状态
    if (retryTimes > retryTimesTmp) { NotifyError(...); return false; }
    return true;
}
```

- **RETRY_TIMES_TO_REPORT_ERROR = 10** (L16)
- **APP_DOWNLOAD_RETRY_TIMES = 60** (L17)
- **SERVER_ERROR_THRESHOLD = 500** (L18)
- 六段式判定逻辑清晰，防止无限重试

### E7: OnDownloadStatus 状态回调驱动重试入队 (download_monitor.cpp L328-L345)

```cpp
void DownloadMonitor::OnDownloadStatus(std::shared_ptr<Downloader>& downloader,
                                        std::shared_ptr<DownloadRequest>& request)
{
    if (NeedRetry(request)) {
        if (isNeedClearBuffer_) downloader_->ClearBuffer();
        AutoLock lock(taskMutex_);
        bool exists = CppExt::AnyOf(retryTasks_.begin(), retryTasks_.end(),
            [&](const RetryRequest& item) { return item.request->IsSame(request); });
        if (!exists) {
            RetryRequest retryRequest{request, [downloader, request] { downloader->Retry(request); }};
            retryTasks_.emplace_back(std::move(retryRequest));
        }
    }
}
```

- **去重逻辑**：AnyOf 检查防止同一请求重复入队
- **Lambda闭包**：捕获 downloader 和 request 的 shared_ptr

### E8: clientErrorCodeMap_ 客户端错误码映射表 (download_monitor.h L106-L141)

```cpp
std::map<int32_t, MediaServiceErrCode> clientErrorCodeMap_ = {
    {-6, MediaServiceErrCode::MSERR_IO_SSL_SERVER_CERT_UNTRUSTED},
    {-5, MediaServiceErrCode::MSERR_IO_CONNECTION_TIMEOUT},
    {-4, MediaServiceErrCode::MSERR_IO_NETWORK_ACCESS_DENIED},
    ...
    {35, MediaServiceErrCode::MSERR_IO_SSL_CONNECT_FAIL},
    {53, MediaServiceErrCode::MSERR_IO_SSL_CONNECT_FAIL},
    {77, MediaServiceErrCode::MSERR_IO_SSL_SERVER_CERT_UNTRUSTED},
    ...
};
```

- **~50种 libcurl 客户端错误码**映射为 MediaServiceErrCode
- 覆盖 SSL证书不受信、连接超时、网络拒绝、无法找到主机等

### E9: serverErrorCodeMap_ 服务端 HTTP 状态码映射表 (download_monitor.h L143-L164)

```cpp
std::map<int32_t, MediaServiceErrCode> serverErrorCodeMap_ = {
    {400, MediaServiceErrCode::MSERR_IO_NETWORK_ACCESS_DENIED},
    {401, MediaServiceErrCode::MSERR_IO_NO_PERMISSION},
    {403, MediaServiceErrCode::MSERR_IO_NETWORK_ACCESS_DENIED},
    {404, MediaServiceErrCode::MSERR_IO_RESOURE_NOT_FOUND},
    {408, MediaServiceErrCode::MSERR_IO_CONNECTION_TIMEOUT},
    {429, MediaServiceErrCode::MSERR_IO_NETWORK_ACCESS_DENIED},  // 429 Too Many Requests
    {500, MediaServiceErrCode::MSERR_IO_RESOURE_NOT_FOUND},
    {502, MediaServiceErrCode::MSERR_IO_NETWORK_UNAVAILABLE},
    {503, MediaServiceErrCode::MSERR_IO_NETWORK_UNAVAILABLE},
    {504, MediaServiceErrCode::MSERR_IO_CONNECTION_TIMEOUT},
    {506, MediaServiceErrCode::MSERR_IO_UNSUPPORTTED_REQUEST},
    ...
};
```

- **~30种 HTTP 状态码**映射为 MediaServiceErrCode
- 覆盖 4xx 客户端错误、5xx 服务端错误

### E10: CLIENT_RETRY_ERROR_CODES / CLIENT_NOT_RETRY_ERROR_CODES 重试决策名单 (download_monitor.cpp L28-L50)

```cpp
const std::set<int32_t> CLIENT_NOT_RETRY_ERROR_CODES = { 992 };
const std::set<int32_t> CLIENT_RETRY_ERROR_CODES = {
    -1, // Application resource not ready for access
    23,   // notBlock
    25,   // Upload failed
    26,   // Failed to open/read local data
    28,   // Timeout was reached
    56, 18, 0,
};
const std::set<int32_t> SERVER_RETRY_ERROR_CODES = {
    300, 301, 302, 303, 304, 305, 403, 500, 0,
};
```

- **CLIENT_NOT_RETRY_ERROR_CODES** = {992} — 不重试名单（仅1个）
- **CLIENT_RETRY_ERROR_CODES** — 可重试的客户端错误（8个）
- **SERVER_RETRY_ERROR_CODES** — 可重试的服务端状态码（9个，含302 重定向）

### E11: NotifyError 错误上报 (download_monitor.cpp L246-L272)

```cpp
void DownloadMonitor::NotifyError(int32_t clientErrorCode, int32_t serverErrorCode)
{
    auto callback = callback_.lock();
    if (callback == nullptr) return;
    if (clientErrorCode != 0) {
        int32_t errorCode = MediaServiceErrCode::MSERR_DATA_SOURCE_IO_ERROR;
        GetClientMediaServiceErrorCode(clientErrorCode, errorCode);
        downloader_->SetIsReportedErrorCode();
        callback->OnEvent({PluginEventType::SERVER_ERROR, {errorCode}, "client error"});
    }
    if (serverErrorCode != 0) { ... }
}
```

- **PluginEventType::SERVER_ERROR** 事件上报给上层
- **GetClientMediaServiceErrorCode** 从 clientErrorCodeMap_ 查表转换

### E12: GetClientMediaServiceErrorCode / GetServerMediaServiceErrorCode 错误码转换 (download_monitor.cpp L506-L526)

```cpp
void DownloadMonitor::GetServerMediaServiceErrorCode(int32_t errorCode, int32_t& serverCode)
{
    if (serverErrorCodeMap_.find(errorCode) == serverErrorCodeMap_.end()) {
        MEDIA_LOG_W("Unknown server error code.");
    } else {
        serverCode = serverErrorCodeMap_[errorCode];
    }
}

void DownloadMonitor::GetClientMediaServiceErrorCode(int32_t errorCode, int32_t& clientCode)
{
    if (clientErrorCodeMap_.find(errorCode) == clientErrorCodeMap_.end()) {
        MEDIA_LOG_W("Unknown client error code.");
    } else {
        clientCode = clientErrorCodeMap_[errorCode];
    }
}
```

- 查表转换，查不到时仅 Warning 日志，不崩溃
- libcurl 错误码（负数）和 HTTP 状态码（正数）分表管理

### E13: RETRY_TIMES = 6000 下载器最大重试次数 (downloader.cpp L34)

```cpp
constexpr size_t RETRY_TIMES = 6000;  // Retry 6000 times
```

- 下载器层允许6000 次重试（DownloadMonitor 层限 10/60 次后上报）
- 6000 × 50ms = 5分钟理论最大等待

### E14: Open 重置重试队列 (download_monitor.cpp L83-L90)

```cpp
bool DownloadMonitor::Open(const std::string& url,
                           const std::map<std::string, std::string>& httpHeader)
{
    isPlaying_ = true;
    {
        AutoLock lock(taskMutex_);
        retryTasks_.clear();  // ← 新建连接时清空重试队列
    }
    return downloader_->Open(url, httpHeader);
}
```

- 每次 Open 新 URL 时清空队列，防止旧重试任务残留

### E15: Close 异步/同步安全关闭 (download_monitor.cpp L95-L105)

```cpp
void DownloadMonitor::Close(bool isAsync)
{
    isClosed_ = true;
    {
        AutoLock lock(taskMutex_);
        retryTasks_.clear();
    }
    if (isAsync) {
        downloader_->Close(true);
        task_->Stop(); // 先停下载器，再停监控线程
    } else {
        task_->Stop();
        downloader_->Close(false);   // 先停监控线程，再停下载器
    }
    isPlaying_ = false;
}
```

- **isAsync=true**（异步）：下载器先关，监控线程后关
- **isAsync=false**（同步）：监控线程先关，下载器后关
- isClosed_ 原子标志防止回调在关闭后继续触发

### E16: Read 读取计数 (download_monitor.cpp L107-L123)

```cpp
Status DownloadMonitor::Read(unsigned char* buff, ReadDataInfo& readDataInfo)
{
    auto ret = downloader_->Read(buff, readDataInfo);
    time(&lastReadTime_);
    if (ULLONG_MAX - haveReadData_ > readDataInfo.realReadLength_) {
        haveReadData_ += readDataInfo.realReadLength_;  // ← 累计读取量统计
    }
    MEDIA_LOG_I_LIMIT(READ_LOG_FEQUENCE, "DownloadMonitor: haveReadData " PUBLIC_LOG_U64, haveReadData_);
    ...
}
```

- **haveReadData_** 累计已读取字节数，用于 DFX 监控
- **READ_LOG_FEQUENCE = 50** (L22)：每50次读操作才打一次日志，防刷屏

### E17: isNeedClearBuffer_ 重定向清缓存标志 (download_monitor.cpp L276-L278)

```cpp
bool DownloadMonitor::NeedRetry(const std::shared_ptr<DownloadRequest>& request)
{
    ...
    isNeedClearBuffer_ = serverError == REDIRECT_CODE;  // ← 302 时清缓存
    ...
}
```

- **302 重定向**时设置 isNeedClearBuffer_=true
- 再次重试时触发 ClearBuffer() 清空环形缓冲区

### E18: Seek 相关操作清除重试队列 (download_monitor.cpp L160-L170, L192-L199)

```cpp
bool DownloadMonitor::SeekToPos(int64_t offset, bool& isSeekHit)
{
    isPlaying_ = true;
    bool res = downloader_->SeekToPos(offset, isSeekHit);
    if (!isSeekHit) {
        AutoLock lock(taskMutex_);
        retryTasks_.clear();  // ← Seek 未命中时清重试队列
    }
    return res;
}

bool DownloadMonitor::SeekToTime(int64_t seekTime, SeekMode mode)
{
    isPlaying_ = true;
    {
        AutoLock lock(taskMutex_);
        retryTasks_.clear();  // ← SeekToTime 时清重试队列
    }
    return downloader_->SeekToTime(seekTime, mode);
}
```

- Seek 操作后清空 retryTasks_，防止旧的重试任务在新位置错误执行

### E19: MediaDownloader 接口代理方法群

DownloadMonitor 代理了 MediaDownloader 的 **50+ 个方法**，全部透传给 downloader_：

```cpp
void SetMediaDuration(int64_t duration)    → downloader_->SetMediaDuration()
void Pause()/Resume()                    → downloader_->Pause()/Resume()
size_t GetContentLength() const         → downloader_->GetContentLength()
int64_t GetDuration() const             → downloader_->GetDuration()
Seekable GetSeekable() const → downloader_->GetSeekable()
void SetCallback(cb)                    → downloader_->SetCallback(cb)
bool GetPlayable()                      → downloader_->GetPlayable()
uint64_t GetBufferSize() const         → downloader_->GetBufferSize()
std::string GetContentType()           → downloader_->GetContentType()
...
```

-装饰器透明转发所有接口，调用方无感知

### E20: GetDownloadInfo / GetPlaybackInfo 透传 (download_monitor.cpp L402-L418)

```cpp
void DownloadMonitor::GetDownloadInfo(DownloadInfo& downloadInfo)
{
    if (downloader_ != nullptr) {
        downloader_->GetDownloadInfo(downloadInfo);
    }
}

void DownloadMonitor::GetPlaybackInfo(PlaybackInfo& playbackInfo)
{
    if (downloader_ != nullptr) {
        downloader_->GetPlaybackInfo(playbackInfo);
    }
}
```

- DownloadMonitor 自身不维护下载信息，全部透传给被装饰者

### E21: SetCallback 回调双路注册 (download_monitor.cpp L229-L233)

```cpp
void DownloadMonitor::SetCallback(const std::shared_ptr<Callback>& cb)
{
    callback_ = cb;                    // ← Monitor 自身持有弱回调
    downloader_->SetCallback(cb);      // ← 同时透传给被装饰者
}
```

- **双路注册**：callback_ 存 Monitor 弱引用（用于错误上报），cb 透传给 downloader_（用于数据回调）
- **weak_ptr 安全性**：错误上报时用 `callback_.lock()` 防止 Monitor 已析构后回调

### E22: SetSourceStatisticsDfx DFX统计上报透传 (download_monitor.cpp L273-L278)

```cpp
void DownloadMonitor::SetSourceStatisticsDfx(
    std::shared_ptr<OHOS::MediaAVCodec::SourceStatisticsReportInfo> rpInfoPtr)
{
    if (downloader_ != nullptr) {
        downloader_->SetSourceStatisticsDfx(rpInfoPtr);  // ← 透传给下载器
    }
}
```

- DownloadMonitor 不独立统计，透传给底层 downloader_ 合并上报
- SourceStatisticsReportInfo 包含已下载字节数、缓冲时长等 DFX 信息

### E23: SelectBitRate / AutoSelectBitRate 自适应码率选择 (download_monitor.cpp L219-L228)

```cpp
bool DownloadMonitor::SelectBitRate(uint32_t bitRate)
{
    return downloader_->SelectBitRate(bitRate);  // ← 手动选码率透传
}

bool DownloadMonitor::AutoSelectBitRate(uint32_t bitRate)
{
    return downloader_->AutoSelectBitRate(bitRate);  // ← 自动选码率透传
}
```

- ABR（Adaptive Bitrate）两层：上层选码率，DownloadMonitor 透传给底层下载器
- GetBitRates()（cpp L214）透传 `downloader_->GetBitRates()` 获取可选码率列表
- 与 HLS M3U8 / DASH MPD 的自适应码率体系（S234/S138）联动

### E24: Pause / Resume 下载器暂停恢复代理 (download_monitor.cpp L108-L118)

```cpp
void DownloadMonitor::Pause()
{
    if (downloader_ != nullptr) {
        downloader_->Pause();  // ← 透传暂停
    }
}

void DownloadMonitor::Resume()
{
    if (downloader_ != nullptr) {
        downloader_->Resume();  // ← 透传恢复
    }
}
```

- Pause/Resume 控制底层下载器暂停/恢复下载
- 与上层录制/播放管线生命周期联动
- 重试队列 retryTasks_ 在 Pause 时不自动清空（由 Close 负责）

### E25: GetDuration / GetStartInfo / GetContentLength 流信息查询代理 (cpp L169-L184)

```cpp
int64_t DownloadMonitor::GetDuration() const
{
    return downloader_->GetDuration();  // ← 总时长透传
}

std::pair<int64_t, bool> DownloadMonitor::GetStartInfo() const
{
    return downloader_->GetStartInfo();  // ← 起播信息透传
}

size_t DownloadMonitor::GetContentLength() const  // ← h L56
{
    return downloader_->GetContentLength();  // ← 文件大小透传
}
```

- 流媒体元信息查询全部透传给底层 downloader_
- GetStartInfo 返回 `{起始时间, 是否成功}`，Seek 操作依赖此信息
- 与 MediaSyncManager 的 GetMaxMediaProgress / 时间范围管理联动（S240）

---

##  Key Design Patterns

### 1. Decorator Pattern (装饰器模式)

```
MediaDownloader (抽象基类，接口定义)
    ↑
    │ implements
    │
DownloadMonitor (装饰器，包裹 + 功能增强)
    │
    │ wraps
    │
HlsMediaDownloader / DashMediaDownloader / HttpMediaDownloader (具体被装饰者)
```

- **功能增强**：重试队列、错误码映射、DFX统计
- **透明转发**：50+ 代理方法，上层无需感知装饰器存在

### 2. Strategy Pattern — 错误码映射表

- **clientErrorCodeMap_** (~50条)：libcurl 客户端错误码 → MediaServiceErrCode
- **serverErrorCodeMap_** (~30条)：HTTP 服务端状态码 → MediaServiceErrCode
-查表转换，解耦 libcurl 与 MediaAVCodec 错误码体系

### 3. Observer Pattern — 状态回调链

```
Downloader (被观察者)
    ↓ OnDownloadStatus(status, downloader, request)
DownloadMonitor (观察者/装饰者)
    ↓ OnDownloadStatus(status, downloader, request)
HttpSourcePlugin (最终观察者)
```

- Downloader 通过 SetStatusCallback 回调通知 DownloadMonitor
- DownloadMonitor注入 lambda 闭包捕获自身 weak_ptr，安全管理生命周期

### 4. Command Pattern — RetryRequest

```cpp
struct RetryRequest {
    std::shared_ptr<DownloadRequest> request;
    std::function<void()> function;  // command: downloader->Retry(request)
};
```

- Lambda 闭包作为命令对象，支持捕获上下文
- 存入 retryTasks_ 队列，HttpMonitorLoop 异步执行

---

##  重试决策流程

```
DownloadRequest 发生错误
        ↓
OnDownloadStatus(downloader, request)
        ↓
NeedRetry(request) 六段判定
   ├─ [NO] CLIENT_NOT_RETRY_ERROR_CODES(992) → 终止
   ├─ [NO] IsNotRetry(FLV直播) → 通知错误 + SetErrorState → 终止
   ├─ [NO] clientError=0 && serverError=0 → 终止
   ├─ [YES] GetPlayable() && !GetReadTimeOut() && retryTimes≤10 → 入队
   ├─ [NO] 错误码不在重试名单 → 通知错误 + Close() → 终止
   └─ [NO] retryTimes > 10/60 → 通知错误 + SetErrorState → 终止
        ↓
HttpMonitorLoop() 50ms 后取出执行
        ↓
downloader->Retry(request) → 重试 HTTP 请求
```

---

##  关联记忆

| ID | 关系 | 说明 |
|----|------|------|
| S210 | 包含/增强 | S210 是 DownloadMonitor + Downloader + HttpCurlClient 三层完整版（E1-E20） |
| S195 | 上游 | Downloader层的 downloader.cpp 实现 Retry逻辑 |
| S172 | 并列 | HttpSourcePlugin 三路下载器工厂路由 |
| S234 | 关联 | HLS M3U8 标签解析框架，通过 DownloadMonitor 提供下载支持 |
| S153 | 关联 | HLS 流下载架构，与 DownloadMonitor 协同 |
| S138 | 关联 | DASH MPD Parser，与 DownloadMonitor 协同 |

---

##  附录：常量速查

| 常量 | 值 | 位置 | 说明 |
|------|---|------|------|
| RETRY_SEG | 50 | monitor cpp:L19 | 监控循环周期50ms |
| RETRY_TIMES_TO_REPORT_ERROR | 10 | monitor cpp:L16 | 普通错误重试上限 |
| APP_DOWNLOAD_RETRY_TIMES | 60 | monitor cpp:L17 | APP_DOWNLOAD 场景重试上限 |
| SERVER_ERROR_THRESHOLD | 500 | monitor cpp:L18 | 服务端错误码阈值 |
| RETRY_TIMES | 6000 | downloader cpp:L34 | 下载器层最大重试次数 |
| READ_LOG_FEQUENCE | 50 | monitor cpp:L22 | 读日志频率控制 |
| REDIRECT_CODE | 302 | monitor cpp:L18, downloader cpp:L41 | HTTP 重定向码 |
| CLIENT_NOT_RETRY_ERROR_CODES | {992} | monitor cpp:L28 | 固定不重试客户端错误码 |