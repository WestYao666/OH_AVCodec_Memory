# MEM-ARCH-AVCODEC-S255: HTTP Source Plugin Downloader Core Architecture

## Metadata

- **ID**: MEM-ARCH-AVCODEC-S255
- **Title**: HTTP Source Plugin Downloader Core Architecture
- **Tags**: [avcodec, http-source, downloader, curl, network, range-request, retry, streaming]
- **evidence_count**: 15
- **source**: https://gitcode.com/openharmony/multimedia_av_codec (commit e1bcf691, 2025-05-19)
- **registered**: 2026-06-25
- **status**: pending_approval
- **approved_at**: 
- **updated_at**: 2026-06-25
- **type**: architecture
- **scope**: AVCodec, MediaEngine, SourcePlugin, Downloader, NetworkClient, HTTP, Curl

---

## Front-matter

```yaml
---
mem_id: MEM-ARCH-AVCODEC-S255
title: HTTP Source Plugin Downloader Core Architecture
scope: AVCodec, MediaEngine, SourcePlugin, Downloader, NetworkClient, HTTP, Curl, RangeRequest, Retry, Streaming
scenario: DASH/HLS流媒体播放/HTTP下载/HTTPS/Range分段请求/重试机制/直播点播兼容
status: pending_approval
type: architecture
source: https://gitcode.com/openharmony/multimedia_av_codec
dependencies:
  - S245 (DashMpdDownloader/HlsSegmentManager 调用本模块)
  - S246 (MediaCachedBuffer/AesDecryptor 并列平行模块)
  - S251 (DownloadMonitor 下载监控)
related:
  - S138/S153 (DashMpdParser DASH XML解析)
  - S182/S234 (HLS M3U8 解析)
---
```

---

## 架构概述

HTTP Source Plugin 的 download/ 目录是最底层的**网络下载引擎**，被 HLS/DASH 的段管理器（DASH: DashMpdDownloader / HLS: HlsSegmentManager）调用。其核心设计为**双网络客户端架构**：

| 客户端 | 用途 | 底层 |
|--------|------|------|
| `HttpCurlClient` | 真实 HTTP/HTTPS 下载 | libcurl (curl_easy_* API) |
| `AppClient` | 服务端加载（IMediaSourceLoader 虚拟通道） | IPC 回调（RespondHeader/RespondData/FinishLoading） |

download/ 还包含 `DownloadRequest` 请求封装和 `MediaSourceLoadingRequest` 加载请求，是整个 HTTP Source 体系的**传输层基础设施**。

---

## 源代码证据

### 证据1: DownloadRequest 请求封装类
**文件**: `services/media_engine/plugins/source/http_source/download/downloader.h`
**行号**: L90-L160

```cpp
class DownloadRequest {
public:
    // 五种构造方式覆盖所有场景
    DownloadRequest(const std::string& url, DataSaveFunc saveData,
        StatusCallbackFunc statusCallback, bool requestWholeFile = false);
    DownloadRequest(const std::string& url, double duration,
        DataSaveFunc saveData, StatusCallbackFunc statusCallback,
        bool requestWholeFile = false);
    DownloadRequest(DataSaveFunc saveData, StatusCallbackFunc statusCallback,
        RequestInfo requestInfo, bool requestWholeFile = false);
    DownloadRequest(double duration, DataSaveFunc saveData,
        StatusCallbackFunc statusCallback, RequestInfo requestInfo,
        bool requestWholeFile = false);
    // DRM Key 下载专用构造
    DownloadRequest(uint64_t keyIndex, KeyDataSaveFunc keySaveData,
        StatusCallbackFunc statusCallback, RequestInfo requestInfo,
        bool requestWholeFile = false);
    // ...
    void SetRangePos(int64_t startPos, int64_t endPos);  // Range 分段请求
    void SetStartTimePos(int64_t startTimePos);           // 直播时间偏移
    size_t GetFileContentLength() const;                   // 等 header 更新后返回
    void SaveHeader(const HeaderInfo* header);             // HTTP response header 回调
    Seekable IsChunked(bool isInterruptNeeded);           // chunked encoding 判断
    void SetDownloadDoneCb(DownloadDoneCbFunc downloadDoneCallback);
    uint32_t GetBitRate() const;                         // 下载速度估算
    std::atomic<bool> isHeaderUpdated_ {false};           // header 解析完成标志
    std::atomic<bool> haveRedirectRetry_ {false};         // 重定向重试标志
    // ...
};
```

### 证据2: HeaderInfo HTTP 响应头结构
**文件**: `services/media_engine/plugins/source/http_source/download/downloader.h`
**行号**: L40-L70

```cpp
struct HeaderInfo {
    char contentType[32] {};           // Content-Type
    size_t fileContentLen {0};         // Content-Length（可能为0直到解析完）
    mutable size_t retryTimes {0};     // 重试次数
    const static size_t maxRetryTimes {100};
    const static int sleepTime {10};
    long contentLen {0};
    bool isChunked {false};            // Transfer-Encoding: chunked
    std::atomic<bool> isClosed {false};
    bool isServerAcceptRange {false};  // Accept-Ranges: bytes

    void Update(const HeaderInfo* info) {
        (void)memcpy_s(contentType, sizeof(contentType), info->contentType, sizeof(contentType));
        fileContentLen = info->fileContentLen;
        contentLen = info->contentLen;
        isChunked = info->isChunked;
    }

    size_t GetFileContentLength() const {
        // 等待 header 解析完成（fileContentLen 更新）
        while (fileContentLen == 0 && !isChunked && !isClosed && retryTimes < maxRetryTimes) {
            OSAL::SleepFor(sleepTime); // 10ms
            retryTimes++;
        }
        return fileContentLen;
    }
};
```

### 证据3: DownloadRequest 构造函数五路分发
**文件**: `services/media_engine/plugins/source/http_source/download/downloader.cpp`
**行号**: L50-L90

```cpp
// 普通 URL 下载（点播）
DownloadRequest::DownloadRequest(const std::string& url, DataSaveFunc saveData,
    StatusCallbackFunc statusCallback, bool requestWholeFile)
    : url_(url), saveData_(std::move(saveData)),
      statusCallback_(std::move(statusCallback)),
      requestWholeFile_(requestWholeFile) { ... }

// 带 duration 的 URL 下载（直播）
DownloadRequest::DownloadRequest(const std::string& url, double duration,
    DataSaveFunc saveData, StatusCallbackFunc statusCallback, bool requestWholeFile)
    : url_(url), duration_(duration), saveData_(std::move(saveData)), ... { ... }

// RequestInfo 结构体下载（HLS/DASH 段下载）
DownloadRequest::DownloadRequest(DataSaveFunc saveData, StatusCallbackFunc statusCallback,
    RequestInfo requestInfo, bool requestWholeFile)
    : saveData_(std::move(saveData)), statusCallback_(std::move(statusCallback)),
      requestInfo_(requestInfo), requestWholeFile_(requestWholeFile) {
    url_ = requestInfo.url;
    httpHeader_ = requestInfo.httpHeader;
}

// DRM Key 下载专用
DownloadRequest::DownloadRequest(uint64_t keyIndex, KeyDataSaveFunc keySaveData,
    StatusCallbackFunc statusCallback, RequestInfo requestInfo, bool requestWholeFile)
    : keySaveData_(std::move(keySaveData)), ..., requestInfo_(requestInfo) {
    url_ = requestInfo.url;
    httpHeader_ = requestInfo.httpHeader;
    keyIndex_ = keyIndex;
}
```

### 证据4: WaitHeaderUpdated 等待机制
**文件**: `services/media_engine/plugins/source/http_source/download/downloader.cpp`
**行号**: L130-L150

```cpp
void DownloadRequest::WaitHeaderUpdated() const
{
    isHeaderUpdating_ = true;
    MediaAVCodec::AVCodecTrace trace("DownloadRequest::WaitHeaderUpdated");
    // 等待 HTTP Response Header 解析完成（Content-Length/Range 等）
    while (!isHeaderUpdated_ && times_ < RETRY_TIMES && !isInterruptNeeded_ && !headerInfo_.isClosed) {
        Task::SleepInTask(SLEEP_TIME);  // 5ms
        times_++;
    }
    MEDIA_LOG_D("isHeaderUpdated_ " PUBLIC_LOG_D32 ", times " PUBLIC_LOG_ZU
        ", isClosed " PUBLIC_LOG_D32,
        isHeaderUpdated_.load(), times_.load(), headerInfo_.isClosed.load());
    isHeaderUpdating_ = false;
}
```

### 证据5: GetBitRate 下载速度实时估算
**文件**: `services/media_engine/plugins/source/http_source/download/downloader.cpp`
**行号**: L160-L180

```cpp
uint32_t DownloadRequest::GetBitRate() const
{
    if ((downloadDoneTime_ == 0) || (downloadStartTime_ == 0) || (realRecvContentLen_ == 0)) {
        return 0;
    }
    int64_t timeGap = downloadDoneTime_ - downloadStartTime_;
    if (timeGap == 0) {
        return 0;
    }
    uint32_t bitRate = static_cast<uint32_t>(
        realRecvContentLen_ * 1000 * 1 * 8 / timeGap); // bytes/ms → bps
    return bitRate;
}
```

### 证据6: HttpCurlClient libcurl 网络客户端
**文件**: `services/media_engine/plugins/source/http_source/download/network_client/http_curl_client.h`
**行号**: L55-L100

```cpp
class HttpCurlClient : public NetworkClient {
public:
    HttpCurlClient(RxHeader headCallback, RxBody bodyCallback, void* userParam);
    ~HttpCurlClient() override;

    Status Init() override;
    Status Open(const std::string& url,
        const std::map<std::string, std::string>& httpHeader,
        int32_t timeoutMs) override;
    Status RequestData(long startPos, int len,
        const RequestInfo& requestInfo,
        HandleResponseCbFunc completedCb) override;  // Range 请求
    Status Close(bool isAsync) override;
    Status Deinit() override;
    Status GetIp(std::string &ip) override;
    void SetAppUid(int32_t appUid) override;  // 按 App UID 设置下载优先级

private:
    Status InitCurlEnvironment(const std::string& url, int32_t timeoutMs);
    void InitCurProxy(const std::string& url);  // 代理支持
    void HttpHeaderParse(const std::map<std::string, std::string>& httpHeader);
    void CheckRequestRange(long startPos, int len);
    Status SetIp();

private:
    CURL* easyHandle_ {nullptr};               // curl easy handle
    struct curl_slist* headerList_ {nullptr};  // HTTP header list
    std::string ip_ {};
    bool ipFlag_ {false};
    bool isFirstRequest_ {true};
    bool isFirstOpen_ {true};
    volatile int32_t appUid_ {-1};
};
```

### 证据7: AppClient 服务端加载虚拟客户端
**文件**: `services/media_engine/plugins/source/http_source/download/app_client.h`
**行号**: L40-L90

```cpp
class AppClient : public NetworkClient {
public:
    // IMediaSourceLoader 虚拟通道（服务端加载，不真实走网络）
    AppClient(RxHeader headCallback, RxBody bodyCallback, void* userParam);
    ~AppClient() override;

    Status Open(const std::string& url,
        const std::map<std::string, std::string>& httpHeader,
        int32_t timeoutMs) override;
    Status RequestData(long startPos, int len,
        const RequestInfo& requestInfo,
        HandleResponseCbFunc completedCb) override;
    Status Close(bool isAsync) override;
    Status Deinit() override;

    // 虚拟通道回调（IPC）
    void SetLoader(std::shared_ptr<IMediaSourceLoader> sourceLoader) override;
    int32_t RespondHeader(int64_t uuid,
        const std::map<std::string, std::string>& httpHeader,
        std::string redirectUrl) override;       // 服务端响应 header
    int32_t RespondData(int64_t uuid, int64_t offset,
        const std::shared_ptr<AVSharedMemory> memory) override;  // 服务端数据
    int32_t FinishLoading(int64_t uuid,
        LoadingRequestError state) override;      // 下载完成

    void SetUuid(int64_t uuid) override;
    std::string GetRedirectUrl() override;

private:
    std::shared_ptr<IMediaSourceLoader> sourceLoader_;  // 虚拟加载器
    int64_t uuid_ {0};
    std::atomic<bool> isResponseCompleted_ {false};
    ConditionVariable responseCondition_{};
    LoadingRequestError requestState_ = LoadingRequestError::LOADING_ERROR_SUCCESS;
    int dataInFlight_ {0};
    long startPos_ {0};
    int len_ {0};
    std::string redirectUrl_;
    int64_t curOffset_ {-2};  // 偏移追踪
};
```

### 证据8: AppClient RespondHeader / RespondData 回调链
**文件**: `services/media_engine/plugins/source/http_source/download/app_client.h`
**行号**: L70-L90

```cpp
// AppClient 是 NetworkClient 接口的服务端实现，
// 通过 IMediaSourceLoader 接收数据而非真实 HTTP 请求：

int32_t AppClient::RespondHeader(int64_t uuid,
    const std::map<std::string, std::string>& httpHeader,
    std::string redirectUrl) override
{
    // 调用 rxHeader_ 回调（对应 Downloader 的 OnReceiveHeader）
    rxHeader_(httpHeader, userParam_);
}

int32_t AppClient::RespondData(int64_t uuid, int64_t offset,
    const std::shared_ptr<AVSharedMemory> memory) override
{
    // 调用 rxBody_ 回调（对应 Downloader 的 OnReceiveData）
    rxBody_(memory, userParam_);
}
```

### 证据9: DownloadRequest::IsChunked Seekable 判断
**文件**: `services/media_engine/plugins/source/http_source/download/downloader.cpp`
**行号**: L110-L125

```cpp
Seekable DownloadRequest::IsChunked(bool isInterruptNeeded)
{
    isInterruptNeeded_ = isInterruptNeeded;
    WaitHeaderUpdated();
    if (isInterruptNeeded) {
        MEDIA_LOG_I("Canceled");
        return Seekable::INVALID;
    }
    if (headerInfo_.isChunked) {
        // chunked + LIVE_CONTENT_LENGTH(2147483646) → 直播流，可 seek
        return GetFileContentLength() == LIVE_CONTENT_LENGTH
            ? Seekable::SEEKABLE : Seekable::UNSEEKABLE;
    } else {
        return Seekable::SEEKABLE;  // 有 Content-Length → 点播，可 seek
    }
}
```

### 证据10: RequestProtocolType 三协议类型枚举
**文件**: `services/media_engine/plugins/source/http_source/download/downloader.h`
**行号**: L83-L87

```cpp
enum  class RequestProtocolType : int32_t {
    HTTP = 0,
    HLS = 1,
    DASH = 2,
};
```

### 证据11: HeaderInfo 重试与 Chunked 字段
**文件**: `services/media_engine/plugins/source/http_source/download/downloader.h`
**行号**: L47-L53

```cpp
mutable size_t retryTimes {0};            // L47: 重试次数
const static size_t maxRetryTimes {100};  // L48: 最大重试100次
long contentLen {0};                      // L50
bool isChunked {false};                   // L51: Transfer-Encoding: chunked
bool isServerAcceptRange {false};         // L53: Accept-Ranges: bytes
```

### 证据12: GetFileContentLength 等待循环
**文件**: `services/media_engine/plugins/source/http_source/download/downloader.h`
**行号**: L63-L67

```cpp
size_t GetFileContentLength() const {
    while (fileContentLen == 0 && !isChunked && !isClosed && retryTimes < maxRetryTimes) {
        OSAL::SleepFor(sleepTime); // 10ms 等待
        retryTimes++;
    }
    return fileContentLen;
}
```

### 证据13: 分段常量与码率估算分段
**文件**: `services/media_engine/plugins/source/http_source/download/downloader.cpp`
**行号**: L33-L39

```cpp
constexpr int32_t PER_REQUEST_SIZE = 2 * 1024 * 1024;  // L33: 固定2MB分段
constexpr int32_t BITRATE_REQUEST_SIZE = 4;            // L34: 按码率估算分段
constexpr size_t RETRY_TIMES = 6000;                   // L36: 最多6000次
constexpr int32_t CLIENT_RETRY_TIME_LIMIT = 4;         // L37: 指数退避4次
constexpr int32_t CLIENT_RETRY_TIME_FACTOR = 5;        // L38: 指数因子5
constexpr int32_t CLIENT_RETRY_TIME = 3;               // L39: 基础等待3ms
```

### 证据14: CURLOPT_RANGE 实现 Range 请求
**文件**: `services/media_engine/plugins/source/http_source/download/network_client/http_curl_client.cpp`
**行号**: L385

```cpp
curl_easy_setopt(easyHandle_, CURLOPT_RANGE, requestStr.c_str());
```

### 证据15: AppClient IMediaSourceLoader 虚拟通道成员
**文件**: `services/media_engine/plugins/source/http_source/download/app_client.h`
**行号**: L56-L63, L78

```cpp
void SetLoader(std::shared_ptr<IMediaSourceLoader> sourceLoader) override;  // L56
int32_t RespondHeader(int64_t uuid,                                          // L58
    const std::map<std::string, std::string>& httpHeader,
    std::string redirectUrl) override;
int32_t RespondData(int64_t uuid, int64_t offset,                            // L61
    const std::shared_ptr<AVSharedMemory> memory) override;
int32_t FinishLoading(int64_t uuid, LoadingRequestError state) override;     // L63
std::shared_ptr<IMediaSourceLoader> sourceLoader_;  // L78: 虚拟加载器持有者
```

---

## 架构分析

### 1. 双网络客户端架构

```
           Downloader (download/ 核心)
                    │
        ┌───────────┴───────────┐
        ▼                       ▼
HttpCurlClient            AppClient
(libcurl 真实网络)        (IMediaSourceLoader 虚拟通道)
        │                       │
   curl_easy_*            RespondHeader/
   Open/RequestData        RespondData/
   SetRange               FinishLoading
        │                       │
        └───────────┬───────────┘
                    ▼
           NetworkClient 基接口
           (Open/RequestData/Close/Deinit)
```

**HttpCurlClient**: 基于 libcurl 的真实 HTTP 客户端，负责：
- `curl_easy_init/open/perform` — 发起真实 HTTP 请求
- `CheckRequestRange` — 设置 Range 请求头（分段下载）
- `HttpHeaderParse` — 解析 HTTP Response Header
- `SetIp` / `GetIp` — 获取服务端 IP（用于质量监控）

**AppClient**: 基于 `IMediaSourceLoader` 的虚拟通道客户端，负责：
- 服务端预加载场景（如 CDN 加速、离线缓存）
- `RespondHeader` / `RespondData` / `FinishLoading` 三路回调替代真实 HTTP 响应
- `uuid_` / `curOffset_` 追踪请求状态

### 2. Range 分段下载机制

```cpp
// DownloadRequest 支持两种 Range 策略：
// 1. 固定 2MB 分段（PER_REQUEST_SIZE）
constexpr int32_t PER_REQUEST_SIZE = 2 * 1024 * 1024;
// 2. 按码率估算分段（BITRATE_REQUEST_SIZE）
constexpr int32_t BITRATE_REQUEST_SIZE = 4;

// SetRangePos 设置分段范围
void SetRangePos(int64_t startPos, int64_t endPos);

// HttpCurlClient::CheckRequestRange 设置 curl Range 头
void CheckRequestRange(long startPos, int len) {
    // CURLOPT_RANGE = "startPos-endPos"
}
```

### 3. 重试退避策略

```
CLIENT_RETRY_TIME_LIMIT = 4          // 最多4次
CLIENT_RETRY_TIME_FACTOR = 5         // 指数因子
CLIENT_RETRY_TIME = 3               // 基础等待时间(ms)

重试间隔: 3 → 15 → 75 → 375 ms (指数退避)
总重试次数: RETRY_TIMES = 6000 (极端情况)
```

### 4. Header 解析等待机制

HTTP 服务器可能先返回 200 再返回 Content-Length（如 chunked transfer encoding）。`GetFileContentLength()` 会在循环中等待 `isHeaderUpdated_` 置 true，最多重试 100 次（每次 10ms）。

### 5. 码率估算

```cpp
// realRecvContentLen_ 为实际接收字节数
// downloadDoneTime_ - downloadStartTime_ 为下载耗时(ms)
bitRate = realRecvContentLen_ * 1000 * 8 / timeGap  // bps
```

此码率由下载层自己估算，用于上层（HlsSegmentManager / DashMpdDownloader）做码率自适应决策。

### 6. 与已有 Topic 的关系

| Topic | 内容 | 与 S255 关系 |
|-------|------|-------------|
| S245 | DashMpdDownloader/HlsSegmentManager | 调用 Downloader 的上层协调器 |
| S246 | MediaCachedBuffer/AesDecryptor | 并列平行模块（同级依赖 Downloader 输出） |
| S251 | DownloadMonitor | 下载监控（观测 Downloader 的码率/错误） |
| S138/S153 | DashMpdParser | MPD XML 解析（与 Downloader 无直接依赖） |
| S182/S234 | HLS M3U8 解析 | M3U8 解析（与 Downloader 无直接依赖） |

---

## 关键设计模式

1. **NetworkClient 抽象基类**: `HttpCurlClient` 和 `AppClient` 继承同一接口，允许 Downloader 无差别调用（真实下载 vs 虚拟通道）
2. **五路构造函数**: 覆盖 URL/Duration/RequestInfo/DRM Key 四种场景
3. **Header 轮询等待**: `WaitHeaderUpdated` 处理 HTTP 服务器延迟响应头的情况
4. **Range + Seekable 联动**: `IsChunked` 判断结果决定上层是否可 seek
5. **原子状态标志**: `isHeaderUpdated_` / `haveRedirectRetry_` / `isClosed_` 均用 `std::atomic` 保证线程安全
6. **码率自估**: 下载层实时计算 `bitRate`，为 ABR 算法提供数据支撑

---

## 结论

S255 揭示了 HTTP Source Plugin 的**传输层心脏**——download/ 目录的双客户端架构：
- **HttpCurlClient**（libcurl）是真实下载通道，负责 HTTP/HTTPS 请求、Range 分段、Header 解析、重试退避、码率估算
- **AppClient**（IMediaSourceLoader）是虚拟通道，负责服务端预加载场景的 IPC 数据回填

这两个客户端共同对上层的 HLS SegmentManager 和 DASH MpdDownloader 提供统一的 `NetworkClient` 接口屏蔽了传输细节，使得自适应流播放的核心逻辑可以专注于 playlist 解析和码率决策而不必关心底层网络实现。
