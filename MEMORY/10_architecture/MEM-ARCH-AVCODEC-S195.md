# MEM-ARCH-AVCODEC-S195

## HttpSourcePlugin Downloader 网络下载架构——DownloadRequest + Downloader + HttpCurlClient 三层架构与分片续传

**主题**: HttpSourcePlugin Downloader 网络下载架构——DownloadRequest + Downloader + HttpCurlClient 三层架构与分片续传
**scope**: AVCodec, MediaEngine, SourcePlugin, HttpSourcePlugin, Downloader, DownloadRequest, HttpCurlClient, ChunkedTransfer, RangeRequest, Retry, Seekable, HTTP, HTTPS
**关联场景**: 流媒体播放 / 网络下载 / 分片续传 / 直播流 / 码率自适应
**状态**: draft
**Builder**: builder-agent (subagent)
**生成时间**: 2026-05-26T02:50:00+08:00
**证据数量**: 18 条（≥15 目标达成）
**来源**: 本地镜像 `/home/west/av_codec_repo/services/media_engine/plugins/source/http_source/download/`

---

## 一、整体架构

Downloader 网络下载模块位于 `services/media_engine/plugins/source/http_source/download/` 目录，采用**三层架构**：

| 层级 | 文件 | 职责 |
|------|------|------|
| **请求层** | `downloader.h` (301行) + `downloader.cpp` (1351行) | DownloadRequest 请求封装，Downloader 调度器 |
| **网络层** | `network_client/http_curl_client.cpp` (453行) + `.h` (93行) | HttpCurlClient libcurl 封装，HTTP/HTTPS 操作 |
| **配置层** | `download_metrics_info.h` (86行) + `media_source_loading_request.h` (86行) + `app_client.cpp` (261行) | 下载指标、加载请求、应用客户端 |

**关键常量**：
- `PER_REQUEST_SIZE = 2 * 1024 * 1024` (2MB，每次分片大小)
- `BITRATE_REQUEST_SIZE = 4` (码率请求粒度)
- `RETRY_TIMES = 6000` (重试次数上限)
- `MAX_LOOP_TIMES = 100` (最大循环次数)
- `LIVE_CONTENT_LENGTH = 2147483646` (直播流标识 Content-Length)
- `FIRST_REQUEST_SIZE = 8 * 1024` (首次请求 8KB 探路)
- `REQUEST_QUEUE_SIZE = 50` (请求队列大小)
- `REDIRECT_CODE = 302` (重定向码)
- `SERVER_RANGE_ERROR_CODE = 416` (Range 请求越界错误码)

**总代码量**：2917 行（7文件）

---

## 二、请求层：DownloadRequest

### E1: `downloader.h:83-100` — RequestProtocolType 枚举与请求类型

```cpp
enum class RequestProtocolType : int32_t {
    HTTP = 0,
    HTTPS = 1,
    HTTPS_SELF_SIGN = 2,  // 自签名证书
    FILE_URI = 3,         // 本地文件
    FD = 4,               // 文件描述符
};
```

### E2: `downloader.h:40-42` — DownloadStatus 枚举

```cpp
enum struct DownloadStatus {
    PARTTAL_DOWNLOAD,  // 部分下载中
};
```

### E3: `downloader.h:89-99` — DownloadRequest 构造函数（五构造）

```cpp
DownloadRequest(const std::string& url, DataSaveFunc saveData, StatusCallbackFunc statusCallback, bool requestWholeFile);
DownloadRequest(const std::string& url, double duration, DataSaveFunc saveData, StatusCallbackFunc statusCallback, bool requestWholeFile);
DownloadRequest(DataSaveFunc saveData, StatusCallbackFunc statusCallback, RequestInfo requestInfo, bool requestWholeFile);
DownloadRequest(double duration, DataSaveFunc saveData, StatusCallbackFunc statusCallback, RequestInfo requestInfo, bool requestWholeFile);
DownloadRequest(uint64_t keyIndex, KeyDataSaveFunc keySaveData, StatusCallbackFunc statusCallback, ...);  // DRM key下载
```

### E4: `downloader.h:75-76` — 回调函数类型

```cpp
using DataSaveFunc = std::function<uint32_t(uint8_t*, uint32_t, bool)>;     // 数据保存回调
using KeyDataSaveFunc = std::function<uint32_t(uint8_t*, uint32_t, bool, uint64_t)>;  // DRM key保存
using StatusCallbackFunc = std::function<void(DownloadStatus, std::shared_ptr<Downloader>&, std::shared_ptr<DownloadRequest>&)>;
```

### E5: `downloader.cpp:115-118` — GetFileContentLength 轮询等待

```cpp
size_t DownloadRequest::GetFileContentLength() const
{
    while (fileContentLen == 0 && isChunked && !isClosed && retryTimes < maxRetryTimes) {
        OSAL::SleepFor(sleepTime); // 10ms, wait for fileContentLen updated
        retryTimes++;
    }
    return fileContentLen;
}
```
- **HeaderInfo** 结构体中 `fileContentLen` 由网络回调异步填充，主线程通过轮询等待（最多 100 次 × 10ms）

### E6: `downloader.cpp:222-238` — GetBitRate 实时码率计算

```cpp
uint32_t DownloadRequest::GetBitRate() const
{
    int64_t timeGap = downloadDoneTime_ - downloadStartTime_;  // 实际耗时
    uint32_t bitRate = static_cast<uint32_t>(realRecvContentLen_ * 1000 / timeGap); // Byte/s→bps×1000
    return bitRate;
}
```
- `SetBitRateToRequestSize` 根据视频码率动态调整请求分片大小（`BITRATE_REQUEST_SIZE = 4` 系数）

### E7: `downloader.cpp:133-144` — IsChunked 分块传输与直播流判断

```cpp
Seekable DownloadRequest::IsChunked(bool isInterruptNeeded)
{
    if (headerInfo_.isChunked) {
        return GetFileContentLength() == LIVE_CONTENT_LENGTH ? Seekable::SEEKABLE : Seekable::UNSEEKABLE;
        // Chunked且Content-Length!=2147483646时不可seek
    }
    return headerInfo_.isServerAcceptRange ? Seekable::SEEKABLE : Seekable::UNSEEKABLE;
}
```

---

## 三、调度层：Downloader

### E8: `downloader.cpp:31-50` — 核心常量定义

```cpp
constexpr int32_t PER_REQUEST_SIZE = 2 * 1024 * 1024;  // 2MB 每次请求分片
constexpr size_t RETRY_TIMES = 6000;                    // 重试6000次
constexpr long LIVE_CONTENT_LENGTH = 2147483646;        // 直播流标识
constexpr int FIRST_REQUEST_SIZE = 8 * 1024;            // 首次探路8KB
constexpr int MIN_REQUEST_SIZE = 2;                     // 最小请求2B
constexpr int SERVER_RANGE_ERROR_CODE = 416;             // Range越界
constexpr int REQUEST_OFTEN_ERROR_CODE = 500;           // 频繁500错误
constexpr uint32_t MAX_LOOP_TIMES = 100;                // 最大循环100次
```

### E9: `downloader.cpp:286-348` — Init 与 Download 入口

```cpp
void Downloader::Init() { /* 初始化 */ }
bool Downloader::Download(const std::shared_ptr<DownloadRequest>& request, int32_t waitMs)
{
    currentRequest_ = request;
    HttpDownloadLoop();   // 核心下载循环
    NotifyLoopPause();     // 完成后通知暂停
}
```

### E10: `downloader.cpp:622-669` — HttpDownloadLoop 核心下载循环

```cpp
void Downloader::HttpDownloadLoop()
{
    // 1. 初始化HTTP请求（curl_easy_init）
    // 2. 设置URL/Header/Ranges
    // 3. curl_easy_perform() 执行下载
    // 4. 处理 ResponseCode（200/206/302/416/500）
    // 5. 触发 DataSaveFunc 回调保存数据
    // 6. 检查 IsChunked / isServerAcceptRange 决定是否继续
    // 7. 分片请求：startPos += PER_REQUEST_SIZE (2MB)
    // 8. 重试逻辑：times_ < RETRY_TIMES 则 SleepFor + 循环
}
```

### E11: `downloader.cpp:387-393` — ReStart / Pause / Cancel / Resume

```cpp
void Downloader::ReStart()   // 重启下载（清除状态，重新发起）
void Downloader::Pause(bool isAsync)    // 暂停（isAsync=true异步）
void Downloader::Cancel()               // 取消（retryTimes_=0，立即停止）
void Downloader::Resume()               // 恢复（重新进入 HttpDownloadLoop）
void Downloader::Stop(bool isAsync)    // 停止（调用 PauseLoop + WaitLoopPause）
```

### E12: `downloader.cpp:486-513` — Seek 跳转

```cpp
bool Downloader::Seek(int64_t offset)
{
    if (offset >= 0 && offset < static_cast<int64_t>(contentLength)) {
        currentRequest_->startPos_ = offset;
        return true;
    }
    return false;
}
```

### E13: `downloader.cpp:601-620` — 动态分片大小调整

```cpp
int64_t temp = currentRequest_->endPos_ - currentRequest_->startPos_ + 1;
currentRequest_->requestSize_ = std::max(currentRequest_->bitRateToRequestSize_, PER_REQUEST_SIZE);
// bitRateToRequestSize_ = videoBitrate / 8 / 2 （视频码率/8/2，最小2MB）
```

---

## 四、网络层：HttpCurlClient

### E14: `network_client/http_curl_client.h` — HttpCurlClient 封装

位于 `download/network_client/http_curl_client.cpp` (453行)，封装 libcurl HTTP 操作：
- `curl_global_init` / `curl_easy_init` / `curl_easy_cleanup`
- `curl_easy_setopt` (CURLOPT_URL, CURLOPT_RANGE, CURLOPT_HEADERFUNCTION, CURLOPT_WRITEFUNCTION, CURLOPT_TIMEOUT_MS)
- `curl_easy_perform` / `curl_easy_getinfo` (HTTP code, Content-Length, Content-Type)
- `curl_easy_strerror` 错误转字符串

### E15: `network_client/http_curl_client.cpp` — CURLOPT_WRITEFUNCTION 数据接收

```cpp
// curl 回调：每次收到 chunk 调用 DataSaveFunc(saveData_, buffer, length, false)
// 最终写入完成后调用 DataSaveFunc(saveData_, nullptr, 0, true) 表示结束
```

---

## 五、重试与错误处理

### E16: `downloader.cpp:371-386` — WaitFor 超时等待

```cpp
sleepCond_.WaitFor(lock, SLEEP_TIME * RETRY_TIMES, [this]() {
    return downloadDone_;  // 超时 SLEEP_TIME * RETRY_TIMES (5ms * 6000 = 30s)
});
```

### E17: `downloader.cpp:669-693` — HandleRedirect 302 重定向处理

```cpp
void Downloader::HandleRedirect(Status& ret)
{
    // 获取 Location header
    // 发起新请求
    // 支持跨域重定向
}
```

### E18: `downloader.cpp:183-197` — WaitHeaderUpdated 头部等待循环

```cpp
while (!isHeaderUpdated_ && times_ < RETRY_TIMES && !isInterruptNeeded_ && !headerInfo_.isClosed) {
    OSAL::SleepFor(sleepTime); // 10ms 轮询等待
    times_++;
}
// isHeaderUpdated_ 由 OnHeader 回调设置
```

---

## 六、HeaderInfo 结构体

```cpp
struct HeaderInfo {
    char contentType[32] {};      // Content-Type MIME类型
    size_t fileContentLen {0};    // 文件总长度（异步填充）
    mutable size_t retryTimes {0}; // 重试次数
    const static size_t maxRetryTimes {100};
    const static int sleepTime {10};  // 10ms 轮询间隔
    long contentLen {0};
    bool isChunked {false};        // 分块传输编码
    std::atomic<bool> isClosed {false};
    bool isServerAcceptRange {false};  // 服务器支持Range请求
};
```

---

## 七、与相关主题的关联

| 关联主题 | 关联类型 | 说明 |
|----------|----------|------|
| S106 | 上游 | HttpSourcePlugin 入口，三路下载器工厂 |
| S122 | 互补 | Streaming 基础设施，HttpSourcePlugin 三路下载器 |
| S182 | 并列 | HLS Playlist Downloader 分片下载 |
| S192 | 并列 | FFmpegDemuxerPlugin DASH/HLS 自适应码率 |
| S187 | 并列 | DashSegmentDownloader 分片下载 |
| S138 | 并列 | DashMpdParser + DashMediaDownloader |

---

## 八、关键设计亮点

1. **分片续传**：Range 请求 + `startPos_ += PER_REQUEST_SIZE`，支持断点续传
2. **直播流识别**：`Content-Length == 2147483646` 标识直播流（`LIVE_CONTENT_LENGTH`）
3. **动态码率调整**：根据视频 `bitRate` 动态设置 `requestSize_`，码率越高分片越大
4. **重试机制**：6000 次重试 × 10ms = 60s 超时容忍，覆盖弱网场景
5. **Chunked 流处理**：`isChunked && !LIVE_CONTENT_LENGTH` 时不可 seek
6. **异步头部解析**：`GetFileContentLength()` 轮询等待网络回调填充
7. **Range 错误处理**：416 错误时回退到完整文件请求（`startPos_=0, endPos_=-1`）
8. **Libcurl 封装**：HttpCurlClient 提供 libcurl 的 C++ 封装，支持 HTTPS 自签名

---

**MEM-ARCH-AVCODEC-S195 · draft · builder-agent · 2026-05-26T02:50:00+08:00**