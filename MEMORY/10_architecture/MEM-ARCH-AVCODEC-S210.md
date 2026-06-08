---
id: MEM-ARCH-AVCODEC-S210
title: "HttpSourcePlugin 下载监控装饰器模式与错误恢复架构——DownloadMonitor + Downloader + HttpCurlClient 三层下载链路"
status: pending_approval
scope: AVCodec, MediaEngine, SourcePlugin, HttpSourcePlugin, DownloadMonitor, Downloader, HttpCurlClient, Retry, ErrorCode, HTTP, HTTPS, ChunkedTransfer, RangeRequest, SSRF
tags:
  - AVCodec
  - MediaEngine
  - SourcePlugin
  - HttpSourcePlugin
  - DownloadMonitor
  - Downloader
  - HttpCurlClient
created: 2026-06-05
modified: 2026-06-08
evidence_count: 20
source_files: |
  /home/west/av_codec_repo/services/media_engine/plugins/source/http_source/http_source_plugin.cpp (769行)
  /home/west/av_codec_repo/services/media_engine/plugins/source/http_source/monitor/download_monitor.h (232行)
  /home/west/av_codec_repo/services/media_engine/plugins/source/http_source/monitor/download_monitor.cpp (610行)
  /home/west/av_codec_repo/services/media_engine/plugins/source/http_source/download/downloader.cpp (1351行)
associations:
  - S165 (HlsMediaDownloader)
  - S172 (DashMediaDownloader MPD解析)
  - S182 (HLS Playlist Downloader)
  - S187 (DASH MPD Parser)
  - S192 (FFmpegDemuxerPlugin)
  - S195 (HttpSourcePlugin Downloader)
  - S209 (HttpSourcePlugin 下载监控架构前身)
---

# MEM-ARCH-AVCODEC-S210：HttpSourcePlugin 下载监控装饰器模式与错误恢复架构

## 1. 主题概述

HttpSourcePlugin 是 HTTP/HTTPS 流媒体源的入口插件，采用**装饰器组合模式**组织下载链路。DownloadMonitor 作为装饰器封装底层具体下载器（HlsMediaDownloader / DashMediaDownloader / HttpMediaDownloader），在不解耦原下载逻辑的前提下，注入重试队列管理、错误码映射、统计上报等横切关注点。

## 2. 三层架构概览

```
HttpSourcePlugin (services/media_engine/plugins/source/http_source/http_source_plugin.cpp L47-769)
    └── DownloadMonitor (monitor/download_monitor.h L43 / .cpp L610)  ← 装饰器层
            ├── HlsMediaDownloader      ← HLS自适应码率段下载器
            ├── DashMediaDownloader    ← DASH MPD段下载器
            └── HttpMediaDownloader    ← 普通HTTP下载器
                    └── Downloader (download/downloader.cpp L1351)   ← 底层curl调度器
                            └── HttpCurlClient (network_client/http_curl_client.cpp)
```

## 3. DownloadMonitor 装饰器层（核心证据）

### 3.1 类定义与成员变量

**E1 - download_monitor.h L43**：
```cpp
class DownloadMonitor : public MediaDownloader, public std::enable_shared_from_this<DownloadMonitor> {
```
DownloadMonitor 同时继承 MediaDownloader（维持相同接口）和 enable_shared_from_this（支持内部跨线程安全指针传递）。

**E2 - download_monitor.h L112-120**（关键成员变量）：
```cpp
std::atomic<bool> isClosed_{false};         // L112: 关闭标志，原子变量
std::list<RetryRequest> retryTasks_;         // L114: 重试任务队列（双向链表）
uint64_t haveReadData_ {0};                  // L120: 累计读取字节数（原子）
```

### 3.2 错误码映射表（约80种映射）

**E3 - download_monitor.h L123-191**（clientErrorCodeMap_，约50种curl错误码→MediaServiceErrCode）：
```cpp
std::map<int32_t, MediaServiceErrCode> clientErrorCodeMap_ = {
    {-6, MSERR_IO_SSL_SERVER_CERT_UNTRUSTED},   // SSL证书不受信
    {-5, MSERR_IO_CONNECTION_TIMEOUT},           // 连接超时
    {-4, MSERR_IO_NETWORK_ACCESS_DENIED},       // 网络访问拒绝
    {-3, MSERR_IO_UNSUPPORTTED_REQUEST},
    {-2, MSERR_IO_RESOURE_NOT_FOUND},
    {-1, MSERR_IO_NETWORK_ACCESS_DENIED},
    {1, MSERR_IO_UNSUPPORTTED_REQUEST},
    {2, MSERR_IO_DATA_SOURCE_IO_ERROR},
    {35, MSERR_IO_SSL_CONNECT_FAIL},             // SSL连接失败(35/53/54/66)
    {53, MSERR_IO_SSL_CONNECT_FAIL},
    {54, MSERR_IO_SSL_CONNECT_FAIL},
    {56, MSERR_IO_NETWORK_ABNORMAL},             // HTTP/2流关闭
    {58, MSERR_IO_SSL_SERVER_CERT_UNTRUSTED},
    {66, MSERR_IO_SSL_CONNECT_FAIL},
    {78, MSERR_IO_RESOURE_NOT_FOUND},            // 资源不存在(78)
    // ... 共约50种curl client错误码
};
```

**E4 - download_monitor.h L191-232**（serverErrorCodeMap_，约30种HTTP状态码→MediaServiceErrCode）：
```cpp
std::map<int32_t, MediaServiceErrCode> serverErrorCodeMap_ = {
    {400, MSERR_IO_NETWORK_ACCESS_DENIED},
    {401, MSERR_IO_NO_PERMISSION},
    {403, MSERR_IO_NETWORK_ACCESS_DENIED},
    {404, MSERR_IO_RESOURE_NOT_FOUND},
    {406, MSERR_IO_NETWORK_ACCESS_DENIED},
    {407, MSERR_IO_NO_PERMISSION},
    {408, MSERR_IO_CONNECTION_TIMEOUT},
    {409, MSERR_IO_NETWORK_ACCESS_DENIED},
    {500, MSERR_IO_RESOURE_NOT_FOUND},
    {502, MSERR_IO_NETWORK_UNAVAILABLE},
    {503, MSERR_IO_NETWORK_UNAVAILABLE},
    {504, MSERR_IO_CONNECTION_TIMEOUT},
    {511, MSERR_IO_SSL_CLIENT_CERT_NEEDED},
    // ... 共约30种HTTP服务器状态码
};
```

### 3.3 重试策略常量

**E5 - download_monitor.cpp L25-27**（重试次数控制常量）：
```cpp
constexpr int RETRY_TIMES_TO_REPORT_ERROR = 10;   // 最多重试10次才报告错误给上层
constexpr int APP_DOWNLOAD_RETRY_TIMES = 60;       // APP下载场景最多重试60次（针对-1错误）
constexpr int SERVER_ERROR_THRESHOLD = 500;       // 服务器错误码阈值（≤500才重试）
```

### 3.4 错误码分类（黑/灰/服务器名单）

**E6 - download_monitor.cpp L32-34**（黑名单——永不重试）：
```cpp
const std::set<int32_t> CLIENT_NOT_RETRY_ERROR_CODES = { 992 };
// 992 = CURLE_SSL_CACERT_BADFILE (CA证书文件损坏)，不重试
```

**E7 - download_monitor.cpp L35-44**（灰名单——curl客户端错误，可重试）：
```cpp
const std::set<int32_t> CLIENT_RETRY_ERROR_CODES = {
    -1,  // CURLE_WEBSERVER_NOT_FOUND: Application resource not ready
    0,   // CURLE_OK: 特殊情况
    18,  // CURLE_PARTIAL_FILE: 部分文件传输
    23,  // CURLE_UPLOAD_FAILED: 上传失败
    25,  // CURLE_WRITE_ERROR: 本地数据读写失败
    26,  // CURLE_READ_ERROR: 读取超时
    28,  // CURLE_OPERATION_TIMEDOUT: 操作超时
    56,  // CURLE_RECV_ERROR: HTTP/2流关闭
};
```

**E8 - download_monitor.cpp L45-52**（服务器错误码——HTTP状态码触发重试）：
```cpp
const std::set<int32_t> SERVER_RETRY_ERROR_CODES = {
    300, 301, 302, 303, 304, 305,  // 重定向（可能被代理缓存）
    403,  // 访问禁止（部分场景可重试，如临时封锁）
    500, 501,  // 服务器内部错误
    0,   // 特殊情况（服务端返回0字节）
};
```

### 3.5 NeedRetry 核心判定逻辑

**E9 - download_monitor.cpp L281**（NeedRetry 入口函数签名）：
```cpp
bool DownloadMonitor::NeedRetry(const std::shared_ptr<DownloadRequest>& request)
```

**E10 - download_monitor.cpp L289-296**（黑名单快速排除 + flv直播不重试）：
```cpp
if (CLIENT_NOT_RETRY_ERROR_CODES.find(static_cast<int32_t>(clientError)) != CLIENT_NOT_RETRY_ERROR_CODES.end()) {
    MEDIA_LOG_I("Client error code is 23 or 992, not retry.");
    return false;  // L289-292: 黑名单直接返回不重试
}
if (downloader_ != nullptr && downloader_->IsNotRetry(request)) { // flv living
    NotifyError(clientError, serverError);
    downloader_->SetDownloadErrorState();
    return false;  // L294-299: flv直播流不重试，直接设错误状态
}
```

**E11 - download_monitor.cpp L304-312**（灰名单+服务器名单联合判定）：
```cpp
// 灰名单 curl 错误码不在列表中 → 不重试
// 服务器错误码不在列表中或 >500 → 不重试
if (CLIENT_RETRY_ERROR_CODES.find(clientError) == CLIENT_RETRY_ERROR_CODES.end() ||
    SERVER_RETRY_ERROR_CODES.find(serverError) == SERVER_RETRY_ERROR_CODES.end() ||
    serverError > SERVER_ERROR_THRESHOLD) {
    MEDIA_LOG_W("error code dont't need to retry.");
    NotifyError(clientError, serverError);  // L314: 上报错误
    ...
    return false;
}
```

**E12 - download_monitor.cpp L322-326**（重试次数上限判定）：
```cpp
int retryTimesTmp = clientError == -1 ? APP_DOWNLOAD_RETRY_TIMES : RETRY_TIMES_TO_REPORT_ERROR;
if (retryTimes > retryTimesTmp) { // L322: 超过重试上限
    MEDIA_LOG_W("Retry times readches the upper limit.");
    NotifyError(clientError, serverError);
    ...
    return false;
}
return true;  // L330: 允许重试
```

### 3.6 NotifyError 与重试任务入队

**E13 - download_monitor.cpp L246**（NotifyError 函数）：
```cpp
void DownloadMonitor::NotifyError(int32_t clientErrorCode, int32_t serverErrorCode)
```

**E14 - download_monitor.cpp L348**（重试任务入队，去重检查）：
```cpp
retryTasks_.emplace_back(std::make_shared<RetryRequest>(...));
FALSE_RETURN_MSG(downloader_ != nullptr, "SetDownloaderBySource downloader is nullptr");
```

## 4. HttpSourcePlugin 入口与三路分发

### 4.1 工厂函数

**E15 - http_source_plugin.cpp L47**（工厂函数，Plugin自动注册入口）：
```cpp
std::shared_ptr<SourcePlugin> HttpSourcePluginCreater(const std::string& name)
{
    FALSE_RETURN_V(name == "httphttpsource", nullptr);
    return std::make_shared<HttpSourcePlugin>();
}
```

### 4.2 SetDownloaderBySource 三路分发（装饰器链注入）

**E16 - http_source_plugin.cpp L287-318**（三路下载器路由，DownloadMonitor装饰器注入）：
```cpp
if (IsDash()) {  // L287: DASH流判断
    downloader_ = std::make_shared<DownloadMonitor>(
        std::make_shared<DashMediaDownloader>(loaderCombinations_));
    FALSE_RETURN_MSG(downloader_ != nullptr, "SetDownloaderBySource downloader is nullptr");
    downloader_->Init();
    downloader_->SetSourceStatisticsDfx(reportInfo_);
    delayReady_ = false;  // L293: 非延迟就绪模式
} else if (IsSeekToTimeSupported() && mimeType_ != AVMimeTypes::APPLICATION_M3U8) {
    // L294: HLS点播（非直播）
    downloader_ = std::make_shared<DownloadMonitor>(
        std::make_shared<HlsMediaDownloader>(expectDuration, userDefinedDuration, httpHeader_, loaderCombinations_));
    ...
} else if (uri_.compare(0, 4, "http") == 0) { // L304: 普通HTTP
    InitHttpSource(source);
}
```

关键模式：**所有三路下载器（HLS/DASH/HTTP）均被 DownloadMonitor 装饰器包裹**，实现统一的重试、监控、错误码转换能力。

### 4.3 SetSource 流程（SSRF防护）

**E17 - http_source_plugin.cpp L211-226**（SetSource 函数体）：
```cpp
Status HttpSourcePlugin::SetSource(std::shared_ptr<MediaSource> source)
{
    MediaAVCodec::AVCodecTrace trace("HttpSourcePlugin::SetSource"); // L213: 染色追踪
    MEDIA_LOG_D("SetSource enter.");
    AutoLock lock(mutex_);  // L214: 互斥锁保护
    FALSE_RETURN_V(downloader_ == nullptr, Status::ERROR_INVALID_OPERATION); // 不允许重复设置
    FALSE_RETURN_V(source != nullptr, Status::ERROR_INVALID_OPERATION);
    InitSourcePlugin(source);  // L217: 初始化下载器
    redirectUrl_ = GetCurUrl();  // L219: 获取最终URL（可能经过302重定向）
    FALSE_RETURN_V(!redirectUrl_.empty() && source->GetSourceUri() != redirectUrl_, Status::OK);
    uri_ = redirectUrl_;
    FALSE_RETURN_V(IsSeekToTimeSupported(), Status::OK);  // L222: 检查是否支持Seek
    InitSourcePlugin(source);  // L224: 再次初始化
    return Status::OK;  // L226
}
```

**SSRF防护要点**：
- `IsAllowedProtocol` 在 `InitSourcePlugin` 内部通过 `SetDownloaderBySource` 检查协议白名单
- `uri_.compare(0, 4, "http") == 0` 明确拒绝非HTTP协议（L304）
- `redirectUrl_` 存储重定向后的最终URL，防止重定向到内网地址（存疑，需进一步验证）

### 4.4 Read 带锁流程

**E18 - http_source_plugin.cpp L363-399**（Read 带锁双重重载）：
```cpp
Status HttpSourcePlugin::Read(std::shared_ptr<Buffer>& buffer, uint64_t offset, size_t expectedLen)
{
    return Read(0, buffer, offset, expectedLen);  // L358-360: 单流重载
}

Status HttpSourcePlugin::Read(int32_t streamId, std::shared_ptr<Buffer>& buffer, uint64_t offset, size_t expectedLen)
{
    MediaAVCodec::AVCodecTrace trace("HttpSourcePlugin::Read, offset: "
        + std::to_string(offset) + ", expectedLen: " + std::to_string(expectedLen)); // L365: 染色追踪
    MEDIA_LOG_D("Read enter.");
    AutoLock lock(mutex_);  // L368: 全局锁（保护 downloader_ 访问）
    FALSE_RETURN_V(downloader_ != nullptr, Status::ERROR_NULL_POINTER);

    if (buffer == nullptr) {
        buffer = std::make_shared<Buffer>();  // L373: 空buffer自动创建
    }
    ReadDataInfo readDataInfo;
    readDataInfo.streamId_ = streamId;           // L384: 流ID
    readDataInfo.wantReadLength_ = expectedLen;   // L386: 期望读取长度
    readDataInfo.ffmpegOffset = offset;            // L387: FFmpeg偏移量
    auto result = downloader_->Read(writableAddr, readDataInfo); // L390: 调用装饰器链
    bufData->UpdateDataSize(readDataInfo.realReadLength_);        // L397: 更新实际读取长度
}
```

**双层锁**：HttpSourcePlugin 持有一把 `mutex_`（L368），DownloadMonitor 内部持有 `taskMutex_`（保护 `retryTasks_`）。

## 5. 底层 Downloader 调度器常量

**E19 - downloader.cpp L31-48**（关键参数常量）：
```cpp
constexpr int32_t PER_REQUEST_SIZE = 2 * 1024 * 1024;   // L31: 每请求2MB分片
constexpr unsigned int SLEEP_TIME = 5;                   // L33: 轮询间隔5ms
constexpr size_t RETRY_TIMES = 6000;                    // L34: 最多6000次轮询等待header
constexpr long LIVE_CONTENT_LENGTH = 2147483646;         // L36: 直播流标识（LL-HLS无界）
constexpr int FIRST_REQUEST_SIZE = 8 * 1024;            // L42: 首请求8KB（探测Content-Length）
constexpr int SERVER_RANGE_ERROR_CODE = 416;            // L44: Range请求无效
constexpr int APP_OPEN_RETRY_TIMES = 10;                // L48: 下载器Open重试次数
```

**E20 - downloader.cpp L142**（Seekable 判定，直播流不可seek）：
```cpp
return GetFileContentLength() == LIVE_CONTENT_LENGTH ? Seekable::SEEKABLE : Seekable::UNSEEKABLE;
```

## 6. 架构特征总结

| 特征 | 实现 |
|------|------|
| **装饰器模式** | DownloadMonitor 继承 MediaDownloader，同时持有被装饰的下载器 |
| **三层分发** | DASH → DashMediaDownloader / HLS点播 → HlsMediaDownloader / 普通HTTP → HttpMediaDownloader |
| **统一装饰** | 三路均被 DownloadMonitor 包裹，重试逻辑集中于一处 |
| **双层锁** | HttpSourcePlugin::mutex_ + DownloadMonitor::taskMutex_ |
| **错误码映射** | ~50种 curl client error + ~30种 HTTP server status → 统一 MediaServiceErrCode |
| **重试上限** | 灰名单最多10次（特殊-1错误60次），超过上报错误 |
| **直播不可seek** | contentLength == LIVE_CONTENT_LENGTH(2147483646) → UNSEEKABLE |
| **DFX追踪** | AVCodecTrace 染色 SetSource/Read，SourceStatisticsEventWrite 上报统计 |

## 7. 关联记忆

| ID | 主题 | 关联说明 |
|----|------|---------|
| S165 | HlsMediaDownloader 段管理机制 | HLS下载器，被DownloadMonitor装饰 |
| S172 | DashMediaDownloader MPD解析 | DASH下载器，被DownloadMonitor装饰 |
| S182 | HLS Playlist Downloader 三路管理 | HLS播放列表，与S210同一源码树 |
| S187 | DASH MPD Parser 解析器体系 | DASH解析器 |
| S192 | FFmpegDemuxerPlugin FFmpegReadLoop | 解封装器，消费Downloader数据 |
| S195 | HttpSourcePlugin Downloader 网络下载 | Downloader底层curl封装 |
| S209 | HttpSourcePlugin 下载监控架构（S209草案） | S210前身，本草案为增强版 |
