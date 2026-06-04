# MEM-ARCH-AVCODEC-S209: HttpSourcePlugin 下载监控与错误处理架构

**状态**: draft  
**主题**: http_source_plugin 下载监控装饰器模式与错误恢复机制  
**发现时间**: 2026-06-05  
**来源**: https://gitcode.com/openharmony/multimedia_av_codec (multimedia_av_codec)

---

## 一、架构概览

HttpSourcePlugin 是 HTTP/HTTPS 流媒体源的入口插件，采用**装饰器组合模式**组织下载链路：

```
HttpSourcePlugin
    └── DownloadMonitor (装饰器/监控层)
            ├── HlsMediaDownloader
            ├── DashMediaDownloader
            └── HttpMediaDownloader
                    └── Downloader (底层curl封装)
```

**证据** (http_source_plugin.cpp):
```cpp
// 根据协议类型选择 Downloader
if (IsDash()) {
    downloader_ = std::make_shared<DownloadMonitor>(
        std::make_shared<DashMediaDownloader>(loaderCombinations_));
} else if (IsSeekToTimeSupported() && mimeType_ != AVMimeTypes::APPLICATION_M3U8) {
    downloader_ = std::make_shared<DownloadMonitor>(
        std::make_shared<HlsMediaDownloader>(...));
} else if (uri_.compare(0, 4, "http") == 0) {
    InitHttpSource(source);
}
```

---

## 二、DownloadMonitor 装饰器层

### 2.1 职责

DownloadMonitor 继承 MediaDownloader，实现以下功能：
- **重试调度**：维护 retryTasks_ 队列，每 50ms 轮询执行
- **错误码映射**：将 client/server 错误码转换为 MediaServiceErrCode
- **状态回调**：接收 DownloadRequest 状态变化通知
- **统计打点**：记录 haveReadData_ 累计读取量

**证据** (download_monitor.h):
```cpp
class DownloadMonitor : public MediaDownloader, public std::enable_shared_from_this<DownloadMonitor> {
    std::list<RetryRequest> retryTasks_;
    std::map<int32_t, MediaServiceErrCode> clientErrorCodeMap_;  // ~50种错误码
    std::map<int32_t, MediaServiceErrCode> serverErrorCodeMap_;   // ~30种错误码
    std::shared_ptr<Task> task_;  // OS_HttpMonitor 异步任务
    uint64_t haveReadData_ {0};
    std::atomic<bool> isClosed_{false};
};
```

### 2.2 重试策略

**证据** (download_monitor.cpp NeedRetry):
```cpp
// 重试触发条件
if ((GetPlayable() && !GetReadTimeOut(clientError == -1)) && retryTimes <= RETRY_TIMES_TO_REPORT_ERROR) {
    return true;  // 可播放状态下，-1错误最多重试60次(APP_DOWNLOAD_RETRY_TIMES)
}

// 客户端错误码黑名单（不重试）
const std::set<int32_t> CLIENT_NOT_RETRY_ERROR_CODES = { 992, };

// 客户端错误码灰名单（可重试）
const std::set<int32_t> CLIENT_RETRY_ERROR_CODES = { -1, 23, 25, 26, 28, 56, 18, 0 };

// 服务器错误码：300/301/302/303/304/305/403/500/0 需重试
const std::set<int32_t> SERVER_RETRY_ERROR_CODES = { 300, 301, 302, 303, 304, 305, 403, 500, 0 };
```

### 2.3 错误码映射表（关键 DFX 知识）

**Client → MediaServiceErrCode 映射** (download_monitor.h):
| Client Error | MediaServiceErrCode | 含义 |
|---|---|---|
| -6 | MSERR_IO_SSL_SERVER_CERT_UNTRUSTED | SSL证书不受信 |
| -5 | MSERR_IO_CONNECTION_TIMEOUT | 连接超时 |
| -4/-1 | MSERR_IO_NETWORK_ACCESS_DENIED | 网络访问拒绝 |
| 35/53/54/66 | MSERR_IO_SSL_CONNECT_FAIL | SSL连接失败 |
| 28 | MSERR_IO_CONNECTION_TIMEOUT | 超时 |
| 78 | MSERR_IO_RESOURE_NOT_FOUND | 资源不存在 |

**Server HTTP Status → MediaServiceErrCode 映射**:
| Status | MediaServiceErrCode | 含义 |
|---|---|---|
| 400 | MSERR_IO_NETWORK_ACCESS_DENIED | 坏请求 |
| 403/409/411-417/421-429/431/451 | MSERR_IO_NETWORK_ACCESS_DENIED | 访问拒绝 |
| 404/421/507/508/510 | MSERR_IO_RESOURE_NOT_FOUND | 资源不存在 |
| 401/407 | MSERR_IO_NO_PERMISSION | 需认证 |
| 408/504 | MSERR_IO_CONNECTION_TIMEOUT | 服务器超时 |
| 500/501 | MSERR_IO_RESOURE_NOT_FOUND | 服务器错误 |
| 502/503 | MSERR_IO_NETWORK_UNAVAILABLE | 服务不可用 |
| 511 | MSERR_IO_SSL_CLIENT_CERT_NEEDED | 需客户端证书 |

---

## 三、HttpSourcePlugin 生命周期

### 3.1 关键成员

**证据** (http_source_plugin.h):
```cpp
class HttpSourcePlugin : public SourcePlugin {
    uint32_t bufferSize_;           // BUFFERING_SIZE 参数
    uint32_t waterline_;            // WATERLINE_HIGH 水线
    std::weak_ptr<Callback> callback_;
    std::shared_ptr<MediaDownloader> downloader_;  // 组合而非继承
    Mutex mutex_;
    std::string uri_;
    std::map<std::string, std::string> httpHeader_;
    std::shared_ptr<MediaSourceLoaderCombinations> loaderCombinations_; // 离线缓存
    std::string redirectUrl_;
    std::shared_ptr<SourceStatisticsReportInfo> reportInfo_;
};
```

### 3.2 SetSource 流程（包含 SSRF 防护）

**证据** (http_source_plugin.cpp SetSource):
```cpp
Status HttpSourcePlugin::SetSource(std::shared_ptr<MediaSource> source) {
    // 1. 检查是否为允许的协议
    FALSE_RETURN_V(IsAllowedProtocol(source->GetSourceUri()), Status::ERROR_INVALID_OPERATION);
    InitSourcePlugin(source);
    redirectUrl_ = GetCurUrl();  // 获取重定向后的URL
    // 2. 检查重定向URL是否安全
    FALSE_RETURN_V(IsAllowedProtocol(redirectUrl_), Status::ERROR_INVALID_OPERATION);
    uri_ = redirectUrl_;
    FALSE_RETURN_V(IsSeekToTimeSupported(), Status::OK);
    InitSourcePlugin(source);
}
```

**协议白名单**:
```cpp
constexpr auto UNALLOWED_PROTOCOLS = std::array{
    std::string_view{"file://"},  // 明确禁止 file://
};
```

### 3.3 Read 流程（带锁）

**证据** (http_source_plugin.cpp Read):
```cpp
Status HttpSourcePlugin::Read(int32_t streamId, std::shared_ptr<Buffer>& buffer, uint64_t offset, size_t expectedLen) {
    AutoLock lock(mutex_);  // 全局锁保护
    FALSE_RETURN_V(downloader_ != nullptr, Status::ERROR_NULL_POINTER);
    // Buffer分配/复用
    std::shared_ptr<Memory> bufData = buffer->IsEmpty()
        ? buffer->AllocMemory(nullptr, expectedLen)
        : buffer->GetMemory();
    // 传递给 downloader_->Read()
}
```

---

## 四、底层 Downloader

### 4.1 关键参数常量

**证据** (downloader.cpp):
```cpp
constexpr int32_t PER_REQUEST_SIZE = 2 * 1024 * 1024;   // 每请求2MB
constexpr size_t RETRY_TIMES = 6000;                     // 6000次轮询等待header
constexpr unsigned int SLEEP_TIME = 5;                   // 5ms睡眠
constexpr int FIRST_REQUEST_SIZE = 8 * 1024;             // 首请求8KB
constexpr int SERVER_RANGE_ERROR_CODE = 416;            // Range无效
constexpr long LIVE_CONTENT_LENGTH = 2147483646;        // 直播内容长度
```

### 4.2 Seek 行为

**证据** (downloader.cpp Seek):
```cpp
bool Downloader::Seek(int64_t offset) {
    if (offset >= 0 && offset < static_cast<int64_t>(contentLength)) {
        currentRequest_->startPos_ = offset;
    }
    currentRequest_->requestSize_ = std::min(remaining, std::max(bitRateToRequestSize_, PER_REQUEST_SIZE));
    currentRequest_->isEos_ = false;
    shouldStartNextRequest_ = false;  // 复用当前请求
    currentRequest_->retryTimes_ = 0;
}
```

---

## 五、DFX 可观测性

### 5.1 已有打点

| 打点项 | 位置 | 说明 |
|---|---|---|
| haveReadData_ | DownloadMonitor::Read | 累计读取字节数 |
| StreamAppPackageNameEventWrite | HttpSourcePlugin::MediaStreamDfxTrace | 包名+Source创建事件 |
| SourceStatisticsEventWrite | HttpSourcePlugin::~HttpSourcePlugin | 异步上报统计信息 |
| PERF_LOADING_ERROR | DownloadMonitor::ReportLoadingErrorEvent | 加载错误事件 |
| CLIENT_ERROR | DownloadMonitor::NotifyError | 上报客户端错误 |

### 5.2 缺失的 DFX 能力

1. **没有 Read 延迟打点**：无单次 Read 耗时时序记录
2. **没有重试率统计**：retryTasks_ 队列深度无监控
3. **没有协议类型分布**：HttpSource vs HLS vs DASH 播放量无区分
4. **没有 Buffer 水位打点**：无实时 buffer 占用量输出到日志
5. **下载速率无周期上报**：GetBitRate() 仅在请求完成时计算，无流式上报

---

## 六、相关已有记忆

- MEM-ARCH-AVCODEC-S165: HlsMediaDownloader 段管理机制
- MEM-ARCH-AVCODEC-S172: DashMediaDownloader MPD解析与Period切换

---

## 七、待补充

- [ ] network_client 层 curl_easy_* 调用链路
- [ ] MediaSourceLoaderCombinations 离线缓存机制
- [ ] HlsSegmentManager 多码率自适应逻辑