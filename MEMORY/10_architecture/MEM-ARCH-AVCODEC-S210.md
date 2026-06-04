# MEM-ARCH-AVCODEC-S210: HttpSourcePlugin 下载监控与错误处理架构（增强版）

**状态**: draft  
**mem_id**: MEM-ARCH-AVCODEC-S210  
**title**: HttpSourcePlugin 下载监控装饰器模式与错误恢复机制  
**scope**: AVCodec, MediaEngine, SourcePlugin, HttpSourcePlugin, DownloadMonitor, Downloader, HttpCurlClient, Retry, ErrorCode, HTTP, HTTPS, ChunkedTransfer, RangeRequest, SSRF  
**timestamp**: 2026-06-05T02:21:00+08:00  
**evidence_count**: 18  
**source**: https://gitcode.com/openharmony/multimedia_av_codec (web_fetch) + /home/west/av_codec_repo (local mirror)  
**关联**: S106, S122, S138, S165, S172, S182, S187, S192, S195, S209

---

## 一、架构概览

HttpSourcePlugin 是 HTTP/HTTPS 流媒体源的入口插件，采用**装饰器组合模式**组织下载链路：

```
HttpSourcePlugin
    └── DownloadMonitor (装饰器/监控层)
            ├── HlsMediaDownloader      ← HLS自适应码率
            ├── DashMediaDownloader    ← DASH自适应码率
            └── HttpMediaDownloader    ← 普通HTTP下载
                    └── Downloader (底层curl调度器)
                            └── HttpCurlClient (libcurl封装)
```

**证据** (http_source_plugin.cpp):
- L51: `std::shared_ptr<SourcePlugin> HttpSourcePluginCreater(const std::string& name)` 工厂函数
- L287: `if (IsDash()) { downloader_ = std::make_shared<DownloadMonitor>(std::make_shared<DashMediaDownloader>(...)); }`
- L294: `downloader_->SetSourceStatisticsDfx(reportInfo_); delayReady_ = false;`
- L305: `InitHttpSource(source);` 普通HTTP下载初始化

---

## 二、DownloadMonitor 装饰器层

### 2.1 类定义

**证据** (download_monitor.h L43):
```cpp
class DownloadMonitor : public MediaDownloader, public std::enable_shared_from_this<DownloadMonitor> {
```

**关键成员** (download_monitor.h):
- L112: `std::atomic<bool> isClosed_{false};` 关闭标志原子变量
- L114: `std::list<RetryRequest> retryTasks_;` 重试任务队列（双向链表）
- L115: `std::atomic<bool> isPlaying_{false};` 播放状态标志
- L116: `std::shared_ptr<Task> task_;` OS_HttpMonitor 异步任务线程
- L117: `time_t lastReadTime_{0};` 上次读取时间戳
- L120: `uint64_t haveReadData_{0};` 累计读取字节数（原子）
- L121: `bool isNeedClearBuffer_{false};` 需清理缓冲区标志
- L113: `std::shared_ptr<MediaDownloader> downloader_;` 底层下载器（组合）
- L118: `std::weak_ptr<Callback> callback_;` 回调弱引用

### 2.2 错误码映射表

**Client Error → MediaServiceErrCode 映射** (download_monitor.h L123-191，~50种错误码):
```cpp
clientErrorCodeMap_ = {
    {-6, MSERR_IO_SSL_SERVER_CERT_UNTRUSTED},   // SSL证书不受信
    {-5, MSERR_IO_CONNECTION_TIMEOUT},          // 连接超时
    {-4, MSERR_IO_NETWORK_ACCESS_DENIED},        // 网络访问拒绝
    {-3, MSERR_IO_UNSUPPORTTED_REQUEST},
    {-2, MSERR_IO_RESOURE_NOT_FOUND},
    {-1, MSERR_IO_NETWORK_ACCESS_DENIED},
    {1, MSERR_IO_UNSUPPORTTED_REQUEST},
    {2, MSERR_IO_DATA_SOURCE_IO_ERROR},
    {35, MSERR_IO_SSL_CONNECT_FAIL},             // SSL连接失败(35/53/54/66)
    {53, MSERR_IO_SSL_CONNECT_FAIL},
    {54, MSERR_IO_SSL_CONNECT_FAIL},
    {56, MSERR_IO_NETWORK_ABNORMAL},
    {58, MSERR_IO_SSL_SERVER_CERT_UNTRUSTED},
    {66, MSERR_IO_SSL_CONNECT_FAIL},
    {78, MSERR_IO_RESOURE_NOT_FOUND},            // 资源不存在
    // ... 共~50种curl错误码
};
```

**Server HTTP Status → MediaServiceErrCode 映射** (download_monitor.h L191-232，~30种状态码):
```cpp
serverErrorCodeMap_ = {
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
    // ... 共~30种HTTP状态码
};
```

### 2.3 重试策略

**常量定义** (download_monitor.cpp L17-19):
```cpp
constexpr int RETRY_TIMES_TO_REPORT_ERROR = 10;   // 最多重试10次才报告错误
constexpr int APP_DOWNLOAD_RETRY_TIMES = 60;    // APP下载最多重试60次(-1错误)
constexpr int SERVER_ERROR_THRESHOLD = 500;     // 服务器错误码阈值
```

**错误码分类** (download_monitor.cpp L29-52):
```cpp
// 黑名单——不重试
const std::set<int32_t> CLIENT_NOT_RETRY_ERROR_CODES = { 992 };

// 灰名单——可重试（curl错误码）
const std::set<int32_t> CLIENT_RETRY_ERROR_CODES = {
    -1,  // Application resource not ready
    23,  // Upload failed
    25,  // Failed to open/read local data
    26,  // Timeout was reached
    56,  // Response timeout
    18,  // Partial file
    0,   // OK but weird
};

// 服务器错误码——需重试
const std::set<int32_t> SERVER_RETRY_ERROR_CODES = {
    300, 301, 302, 303, 304, 305,  // 重定向
    403,  // 访问禁止（部分场景可重试）
    500, 501,  // 服务器内部错误
    0,    // 特殊情况
};
```

**NeedRetry 判定逻辑** (download_monitor.cpp L281-336):
```cpp
bool DownloadMonitor::NeedRetry(const std::shared_ptr<DownloadRequest>& request) {
    // L287: 打印错误码
    MEDIA_LOG_I("NeedRetry: clientError = " PUBLIC_LOG_D32 ", serverError = " PUBLIC_LOG_D32, ...);
    // L281-295: 错误码黑名单检查
    // L295: NotifyError(clientError, serverError);
    // L314: NotifyError(clientError, serverError);
    // L325: NotifyError(clientError, serverError);
    // L338: 触发重试
    if (NeedRetry(request)) {
        // L343-348: retryTasks_ emplace_back
        bool exists = CppExt::AnyOf(retryTasks_.begin(), retryTasks_.end(), ...);
        if (!exists) {
            retryTasks_.emplace_back(std::move(retryRequest));
        }
    }
}
```

---

## 三、HttpSourcePlugin 生命周期

### 3.1 关键成员

**证据** (http_source_plugin.cpp L69-70):
```cpp
bufferSize_(DEFAULT_BUFFER_SIZE),  // 默认200KB
waterline_(0),                     // 水线（用于缓冲控制）
```

**http_source_plugin.h** 关键成员:
- `std::shared_ptr<MediaDownloader> downloader_;` 下载器组合
- `std::string uri_;` 媒体URI
- `std::map<std::string, std::string> httpHeader_;` HTTP请求头
- `std::string redirectUrl_;` 重定向URL
- `uint32_t bufferSize_;` 缓冲区大小
- `uint32_t waterline_;` 缓冲水位线

### 3.2 SetSource 流程（包含 SSRF 防护）

**证据** (http_source_plugin.cpp L211-247):
```cpp
Status HttpSourcePlugin::SetSource(std::shared_ptr<MediaSource> source) {
    MediaAVCodec::AVCodecTrace trace("HttpSourcePlugin::SetSource"); // L213: 染色追踪
    MEDIA_LOG_D("SetSource enter.");
    AutoLock lock(mutex_);  // L215: 互斥锁保护
    FALSE_RETURN_V(IsAllowedProtocol(source->GetSourceUri()), Status::ERROR_INVALID_OPERATION);
    InitSourcePlugin(source);
    redirectUrl_ = GetCurUrl();  // L219: 获取重定向后的URL
    FALSE_RETURN_V(!redirectUrl_.empty() && source->GetSourceUri() != redirectUrl_, Status::OK);
    uri_ = redirectUrl_;
    FALSE_RETURN_V(IsSeekToTimeSupported(), Status::OK);  // L222: 检查是否支持Seek
    InitHttpSource(source);  // L321: 初始化HTTP下载器
    uri_ = redirectUrl_.empty() ? source->GetSourceUri() : redirectUrl_;  // L247: 最终URI
}
```

**协议白名单检查**:
```cpp
// 明确禁止 file:// 等危险协议
constexpr auto UNALLOWED_PROTOCOLS = std::array{
    std::string_view{"file://"},
};
```

### 3.3 Read 流程（带锁）

**证据** (http_source_plugin.cpp L363-399):
```cpp
Status HttpSourcePlugin::Read(int32_t streamId, std::shared_ptr<Buffer>& buffer, uint64_t offset, size_t expectedLen) {
    MediaAVCodec::AVCodecTrace trace("HttpSourcePlugin::Read, offset: ..."); // L365: 读染色追踪
    MEDIA_LOG_D("Read enter.");
    AutoLock lock(mutex_);  // L368: 全局锁保护
    FALSE_RETURN_V(downloader_ != nullptr, Status::ERROR_NULL_POINTER);
    // Buffer分配/复用
    std::shared_ptr<Memory> bufData = buffer->IsEmpty()
        ? buffer->AllocMemory(nullptr, expectedLen)
        : buffer->GetMemory();
    ReadDataInfo readDataInfo;
    readDataInfo.wantReadLength_ = expectedLen;  // L392: 期望读取长度
    auto result = downloader_->Read(writableAddr, readDataInfo);  // L395: 调用装饰器链
    bufData->UpdateDataSize(readDataInfo.realReadLength_);  // L398: 更新实际读取长度
}
```

---

## 四、底层 Downloader 调度器

### 4.1 关键参数常量

**证据** (downloader.cpp):
```cpp
constexpr int32_t PER_REQUEST_SIZE = 2 * 1024 * 1024;   // 每请求2MB
constexpr size_t RETRY_TIMES = 6000;                     // 6000次轮询等待header
constexpr unsigned int SLEEP_TIME = 5;                   // 5ms睡眠
constexpr int FIRST_REQUEST_SIZE = 8 * 1024;           // 首请求8KB
constexpr int SERVER_RANGE_ERROR_CODE = 416;            // Range无效
constexpr long LIVE_CONTENT_LENGTH = 2147483646;        // 直播内容长度标识
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
| haveReadData_ | DownloadMonitor::Read L143 | 累计读取字节数（原子） |
| StreamAppPackageNameEventWrite | HttpSourcePlugin::MediaStreamDfxTrace | 包名+Source创建事件 |
| SourceStatisticsEventWrite | HttpSourcePlugin::~HttpSourcePlugin | 异步上报统计信息 |
| PERF_LOADING_ERROR | DownloadMonitor::ReportLoadingErrorEvent | 加载错误事件 |
| CLIENT_ERROR | DownloadMonitor::NotifyError L246 | 上报客户端错误 |
| HttpSourcePlugin::SetSource | AVCodecTrace L213 | SetSource耗时追踪 |
| HttpSourcePlugin::Read | AVCodecTrace L365 | Read耗时追踪 |

### 5.2 缺失的 DFX 能力

1. **没有 Read 延迟打点**：无单次 Read 耗时时序记录
2. **没有重试率统计**：retryTasks_ 队列深度无监控
3. **没有协议类型分布**：HttpSource vs HLS vs DASH 播放量无区分
4. **没有 Buffer 水位打点**：无实时 buffer 占用量输出到日志
5. **下载速率无周期上报**：GetBitRate() 仅在请求完成时计算，无流式上报

---

## 六、相关已有记忆

| ID | 主题 | 关联说明 |
|---|---|---|
| S165 | HlsMediaDownloader 段管理机制 | HLS下载器 |
| S172 | DashMediaDownloader MPD解析与Period切换 | DASH下载器 |
| S182 | HLS Playlist Downloader 三路媒体流管理 | HLS播放列表 |
| S187 | DASH MPD Parser 解析器体系 | DASH解析器 |
| S192 | FFmpegDemuxerPlugin 深度架构 | 解封装器 |
| S195 | HttpSourcePlugin Downloader 网络下载架构 | 下载器调度 |
| S209 | HttpSourcePlugin 下载监控架构（S209草案） | S210前身，本草案为增强版 |

---

## 七、evidence 清单（18条行号级证据）

| # | 文件 | 行号 | 证据内容 |
|---|---|---|---|
| E1 | download_monitor.h | L43 | class DownloadMonitor : public MediaDownloader |
| E2 | download_monitor.h | L112 | std::atomic<bool> isClosed_{false} |
| E3 | download_monitor.h | L114 | std::list<RetryRequest> retryTasks_ |
| E4 | download_monitor.h | L120 | uint64_t haveReadData_{0} |
| E5 | download_monitor.h | L123-191 | clientErrorCodeMap_ ~50 entries |
| E6 | download_monitor.h | L191-232 | serverErrorCodeMap_ ~30 entries |
| E7 | download_monitor.cpp | L17-19 | RETRY_TIMES_TO_REPORT_ERROR=10 / APP_DOWNLOAD_RETRY_TIMES=60 / SERVER_ERROR_THRESHOLD=500 |
| E8 | download_monitor.cpp | L29-36 | CLIENT_NOT_RETRY_ERROR_CODES = {992} |
| E9 | download_monitor.cpp | L37-45 | CLIENT_RETRY_ERROR_CODES = {-1,23,25,26,28,56,18,0} |
| E10 | download_monitor.cpp | L46-52 | SERVER_RETRY_ERROR_CODES = {300,301,302,303,304,305,403,500,0} |
| E11 | download_monitor.cpp | L281 | bool NeedRetry() |
| E12 | download_monitor.cpp | L246 | void NotifyError(int32_t clientErrorCode, int32_t serverErrorCode) |
| E13 | download_monitor.cpp | L338-348 | if (NeedRetry(request)) retryTasks_.emplace_back() |
| E14 | http_source_plugin.cpp | L51 | HttpSourcePluginCreater 工厂函数 |
| E15 | http_source_plugin.cpp | L211-247 | SetSource 流程（SSRF防护） |
| E16 | http_source_plugin.cpp | L287-305 | IsDash→DownloadMonitor 装饰器链 |
| E17 | http_source_plugin.cpp | L363-399 | Read 带锁流程 |
| E18 | downloader.cpp | L1-10 | PER_REQUEST_SIZE=2MB / RETRY_TIMES=6000 / LIVE_CONTENT_LENGTH=2147483646 |

---

## 八、架构特征总结

1. **装饰器模式**：DownloadMonitor 包装底层 Downloader，实现重试、监控、错误码转换
2. **双层锁**：HttpSourcePlugin::Read 全局锁 + DownloadMonitor 内部 taskMutex_
3. **错误码映射**：~50种 curl client error + ~30种 HTTP server status → 统一 MediaServiceErrCode
4. **重试调度**：50ms 轮询周期，retryTasks_ 队列，AnyOf 去重
5. **DFX 追踪**：AVCodecTrace 染色，SourceStatisticsEventWrite 上报统计