# MEM-ARCH-AVCODEC-S233: AppClient + IMediaSourceLoader 双路由下载架构

**mem_id**: MEM-ARCH-AVCODEC-S233  
**status**: pending_approval  
**last_updated**: 2026-06-09  
**builder**: builder-agent (subagent)  
**evidence_count**: 20  
**source**: 基于本地镜像 /home/west/av_codec_repo/services/media_engine/plugins/source/http_source/download/

## 主题

AppClient + IMediaSourceLoader 双路由下载架构——HttpCurlClient(libcurl)与AppClient(IMediaSourceLoader)双NetworkClient实现 + MediaSourceLoadingRequest五回调管理

## scope

AVCodec, MediaEngine, SourcePlugin, HttpSourcePlugin, NetworkClient, AppClient, HttpCurlClient, IMediaSourceLoader, IMediaSourceLoadingRequest, MediaSourceLoadingRequest, MediaSourceLoaderCombinations, DownloadRequest, Downloader, LoadingRequestError, AVSharedMemory, CallbackRouter

## 关联

- S195: HttpSourcePlugin Downloader 网络下载架构（上层 Downloader + DownloadRequest）
- S210: HttpSourcePlugin 下载监控装饰器模式（DownloadMonitor）
- S209: 待注册（HttpSourcePlugin 整体架构）
- S172: MediaSourceLoader 离线缓存

---

## 一、架构概览：双 NetworkClient 路由

HttpSourcePlugin 支持两种底层 HTTP 客户端，通过 `NetworkClient::GetInstance()` 工厂方法选择：

| 实现类 | 底层 | 路径 | 用途 |
|--------|------|------|------|
| `HttpCurlClient` | libcurl | `network_client/http_curl_client.cpp` (453行) | 标准 HTTP/HTTPS 下载 |
| `AppClient` | IMediaSourceLoader | `download/app_client.cpp` (261行) + `.h` (93行) | App级媒体源加载（离线缓存/云端协同） |

两个实现类都继承自 `NetworkClient` 基类，接口完全一致，上层 `Downloader` 无感知差异。

---

## 二、NetworkClient 基类接口

定义于 `network/network_client.h`：

### E1: `network_client.h` — NetworkClient 基类（L1-L30）

```cpp
class NetworkClient {
public:
    virtual ~NetworkClient() = default;
    virtual Status Init() = 0;
    virtual Status Open(const string& url, const map<string,string>& httpHeader, int32_t timeoutMs) = 0;
    virtual Status RequestData(long startPos, int len, const RequestInfo& requestInfo,
                               HandleResponseCbFunc completedCb) = 0;
    virtual Status Close(bool isAsync) = 0;
    virtual Status Deinit() = 0;
    virtual Status GetIp(string& ip) = 0;
    virtual void SetAppUid(int32_t appUid) = 0;
    // AppClient 特有扩展：
    virtual void SetLoader(shared_ptr<IMediaSourceLoader> sourceLoader) = 0;
    virtual int32_t RespondHeader(int64_t uuid, const map<string,string>& httpHeader, string redirectUrl) = 0;
    virtual int32_t RespondData(int64_t uuid, int64_t offset, const shared_ptr<AVSharedMemory>& memory) = 0;
    virtual int32_t FinishLoading(int64_t uuid, LoadingRequestError state) = 0;
    virtual void SetUuid(int64_t uuid) = 0;
    virtual string GetRedirectUrl() = 0;
};
```

工厂方法：
```cpp
// HttpCurlClient 工厂
std::shared_ptr<NetworkClient> NetworkClient::GetInstance(RxHeader, RxBody, void*);
// AppClient 工厂
std::shared_ptr<NetworkClient> NetworkClient::GetAppInstance(RxHeader, RxBody, void*);
```

---

## 三、AppClient 实现（261行 cpp）

### E2: `app_client.h` — AppClient 类定义（L24-L93）

```cpp
class AppClient : public NetworkClient {
    RxHeader rxHeader_; RxBody rxBody_; void* userParam_;
    shared_ptr<IMediaSourceLoader> sourceLoader_; // 核心：IMediaSourceLoader 注入
    int64_t uuid_ {0}; // 请求唯一标识
    atomic<bool> isResponseCompleted_ {false};
    ConditionVariable responseCondition_;
    LoadingRequestError requestState_ = LoadingRequestError::LOADING_ERROR_SUCCESS;
    FairMutex mutex_;
    int dataInFlight_ {0};
    long startPos_ {0}; int len_ {0};
    int64_t curOffset_ {-2}; // 当前偏移，双向同步
    string redirectUrl_;
};
```

### E3: `app_client.cpp` — 常量定义（L18-L27）

```cpp
namespace {
    constexpr OHOS::HiviewDFX::HiLogLabel LABEL = { LOG_CORE, LOG_DOMAIN_SYSTEM_PLAYER, "HiStreamer" };
    constexpr size_t MAX_MAP_SIZE = 100;
    constexpr int DROP_APP_DATA = -2;
    constexpr int64_t DEFAULT_CURRENT_OFFSET = -2;
    constexpr int BUFFER_FULL = -3;
    constexpr int RETRY_SLEEP_TIME = 500; // ms
    constexpr int FINISHLOADING_SLEEP_TIME = 10; // ms
}
```

### E4: `app_client.cpp` — RequestData 回调驱动（L86-L120）

```cpp
Status AppClient::RequestData(long startPos, int len, const RequestInfo& requestInfo,
    HandleResponseCbFunc completedCb)
{
    MediaAVCodec::AVCodecTrace trace("AppClient RequestData, startPos: " +
        std::to_string(startPos) + ", len: " + std::to_string(len));
    if (startPos == -1) { len = -1; startPos = 0; }
    len_ = len;
    startPos_ = startPos;
    curOffset_ = static_cast<int64_t>(startPos);
    dataInFlight_ = len;

    int32_t clientCode = 0;
    int32_t serverCode = 0;
    LoadingRequestError requestState;
    {
        AutoLock lock(mutex_);
        isResponseCompleted_.store(false);
        int32_t res = sourceLoader_->Read(uuid_, static_cast<int64_t>(startPos), static_cast<int64_t>(len));
        FALSE_LOG_MSG(res == 0, "sourceLoader read fail.");
        // 等待 RespondData/RespondHeader 回调完成
        responseCondition_.Wait(lock, [this] { return isResponseCompleted_.load(); });
        requestState = requestState_;
    }
    clientCode = static_cast<int32_t>(requestState) * (-1);
    // ...
}
```

**关键差异**：HttpCurlClient 调用 `curl_easy_perform()` 同步等待响应；AppClient 调用 `sourceLoader_->Read()` 后立即返回，由外部通过 `RespondData`/`RespondHeader` 回调驱动后续流程。

### E5: `app_client.cpp` — RespondData 回调写入（L173-L193）

```cpp
int32_t AppClient::RespondData(int64_t uuid, int64_t offset, const shared_ptr<AVSharedMemory>& memory)
{
    void* buffer = reinterpret_cast<void*>(memory->GetBase());
    size_t res = rxBody_(buffer, memory->GetSize(), 1, userParam_);  // 写回调
    curOffset_ += static_cast<int64_t>(res); // 偏移同步
    dataInFlight_ -= memory->GetSize(); // 剩余量递减
    if (len_ > 0 && dataInFlight_ <= 0) {
        NotifyResponseDataEnd(LoadingRequestError::LOADING_ERROR_SUCCESS);
    }
    return receiveDataSize;
}
```

### E6: `app_client.cpp` — NotifyResponseDataEnd 状态同步（L153-L162）

```cpp
void AppClient::NotifyResponseDataEnd(LoadingRequestError state)
{
    AutoLock lock(mutex_);
    requestState_ = state;
    isResponseCompleted_.store(true);
    responseCondition_.NotifyOne();  // 唤醒 RequestData 等待线程
    if (state == LoadingRequestError::LOADING_ERROR_SUCCESS) {
        curOffset_ = DEFAULT_CURRENT_OFFSET;  // -2，恢复初态
    }
}
```

### E7: `app_client.cpp` — SetLoader 注入 IMediaSourceLoader（L199-L204）

```cpp
void AppClient::SetLoader(shared_ptr<IMediaSourceLoader> sourceLoader)
{
    MEDIA_LOG_I("0x%{public}06" PRIXPTR " AppClient SetLoader", FAKE_POINTER(this));
    sourceLoader_ = sourceLoader;
}
```

---

## 四、IMediaSourceLoader 回调接口体系

### E8: `media_source_loading_request.h` — 核心数据结构（L27-L79）

```cpp
class LoadingRequestElements {
    int64_t uuid_ {0};
    shared_ptr<NetworkClient> client_ {};  // 持有 AppClient 弱引用
public:
    int32_t RespondData(int64_t uuid, int64_t offset, const shared_ptr<AVSharedMemory>& data);
    int32_t RespondHeader(int64_t uuid, map<string,string> header, string redirectUrl);
    int32_t FinishLoading(int64_t uuid, LoadingRequestError state);
};

class MediaSourceLoadingRequest : public IMediaSourceLoadingRequest {
    map<int64_t, shared_ptr<LoadingRequestElements>> requestMap_;  // uuid → Elements 映射
    FairMutex clientMutex_;
public:
    int64_t Open(int64_t uuid, const shared_ptr<NetworkClient>& client);  // 注册
    int32_t Close(int64_t uuid);                                          // 注销
    int32_t RespondData(...) override;   // 路由至对应 Elements
    int32_t RespondHeader(...) override;
    int32_t FinishLoading(...) override;
};
```

### E9: `media_source_loading_request.cpp` — Open 注册（L47-L62）

```cpp
int64_t MediaSourceLoadingRequest::Open(int64_t uuid, const shared_ptr<NetworkClient>& client)
{
    MediaAVCodec::AVCodecTrace trace("MediaSourceLoadingRequest Open, uuid: " + std::to_string(uuid));
    AutoLock lock(clientMutex_);
    auto it = requestMap_.find(uuid);
    if (it != requestMap_.end()) return 0;  // 防重复
    auto element = make_shared<LoadingRequestElements>(uuid, client);
    requestMap_.emplace(uuid, element);  // uuid 分发路由表
    return 0;
}
```

### E10: `media_source_loading_request.cpp` — RespondData 路由（L101-L117）

```cpp
int32_t MediaSourceLoadingRequest::RespondData(int64_t uuid, int64_t offset,
    const shared_ptr<AVSharedMemory>& request)
{
    MediaAVCodec::AVCodecTrace trace("MediaSourceLoadingRequest RespondData, uuid: " + std::to_string(uuid) +
        ", offset: " + std::to_string(offset));
    AutoLock lock(clientMutex_);
    auto it = requestMap_.find(uuid);
    if (it != requestMap_.end() && it->second != nullptr) {
        return it->second->RespondData(uuid, offset, request);  // 分发至对应 AppClient
    }
    return 0;
}
```

---

## 五、MediaSourceLoaderCombinations 组合器

### E11: `media_source_loading_request.h` — MediaSourceLoaderCombinations（L70-L79）

```cpp
class MediaSourceLoaderCombinations {
    shared_ptr<IMediaSourceLoader> loader_;
    shared_ptr<MediaSourceLoadingRequest> request_;
    bool enable_ {false};  // 离线缓存开关
public:
    int64_t Open(const string& url, const map<string,string>& header,
                  shared_ptr<NetworkClient>& client);
    int32_t Close(int64_t uuid);
    void EnableOfflineCache(bool enable);
    bool GetenableOfflineCache();
};
```

### E12: `media_source_loading_request.cpp` — Open 两阶段初始化（L159-L172）

```cpp
int64_t MediaSourceLoaderCombinations::Open(const string& url,
    const map<string,string>& header, shared_ptr<NetworkClient>& client)
{
    FALSE_RETURN_V_MSG(loader_ != nullptr, 0, "Open no loader!");
    if (request_ == nullptr) {
        request_ = make_shared<MediaSourceLoadingRequest>();
        std::shared_ptr<IMediaSourceLoadingRequest> request =
            std::static_pointer_cast<IMediaSourceLoadingRequest>(request_);
        loader_->Init(request);  // 注入 IMediaSourceLoadingRequest
    }
    int64_t uuid = loader_->Open(url, header);  // 获取全局唯一 uuid
    request_->Open(uuid, client);                // 在本地映射表中注册
    return uuid;
}
```

---

## 六、Downloader 双客户端工厂

### E13: `downloader.cpp` — Downloader 双模式构造函数（L264-L283）

```cpp
Downloader::Downloader(const string& name) noexcept : name_(std::move(name))
{
    shouldStartNextRequest_ = true;
    // 默认使用 HttpCurlClient（libcurl）
    client_ = NetworkClient::GetInstance(&RxHeaderData, &RxBodyData, this);
}
 
Downloader::Downloader(const string& name, shared_ptr<MediaSourceLoaderCombinations> sourceLoader) noexcept
{
    name_ = name;
    shouldStartNextRequest_ = true;
    if (sourceLoader != nullptr) {
        isNotBlock_ = true;
        sourceLoader_ = sourceLoader;
        // 使用 AppClient（IMediaSourceLoader）
        client_ = NetworkClient::GetAppInstance(&RxHeaderData, &RxBodyData, this);
        client_->SetLoader(sourceLoader->loader_);
        MEDIA_LOG_I("0x%{public}06" PRIXPTR "Get app instance success", FAKE_POINTER(this));
    } else {
        MEDIA_LOG_I("0x%{public}06" PRIXPTR "Get libcurl instance success", FAKE_POINTER(this));
        client_ = NetworkClient::GetInstance(&RxHeaderData, &RxBodyData, this);
    }
}
```

### E14: `downloader.h` — Downloader 成员变量（L242-L260）

```cpp
class Downloader : public std::enable_shared_from_this<Downloader> {
    // ...
private:
    std::string name_;
    std::shared_ptr<NetworkClient> client_;  // 统一接口，双客户端实现
    std::shared_ptr<BlockingQueue<std::shared_ptr<DownloadRequest>>> requestQue_;
    std::shared_ptr<DownloadRequest> currentRequest_;
    
    int64_t sourceId_ {0};
    std::shared_ptr<MediaSourceLoaderCombinations> sourceLoader_;  // AppClient 专用
    std::shared_ptr<IMediaSourceLoadingRequest> loadingReques_;
    bool isNotBlock_ {false};  // AppClient 模式标志
    // ...
};
```

---

## 七、HttpDownloadLoop 与 RequestData

### E15: `downloader.cpp` — HttpDownloadLoop 主循环（L599-L626）

```cpp
void Downloader::HttpDownloadLoop()
{
    AutoLock lock(operatorMutex_);
    MEDIA_LOGI_LIMIT(LOOP_LOG_FEQUENCE, "Downloader loop shouldStartNextRequest %{public}d",
        shouldStartNextRequest_.load());
    if (shouldStartNextRequest_) {
        std::shared_ptr<DownloadRequest> tempRequest = requestQue_->Pop(1000);
        if (!tempRequest) {
            MEDIA_LOG_W("HttpDownloadLoop tempRequest is null.");
            noTaskLoopTimes_++;
            if (noTaskLoopTimes_ >= LOOP_TIMES) {
                PauseLoop(true);
            }
            return;
        }
        noTaskLoopTimes_ = 0;
        currentRequest_ = tempRequest;
        BeginDownload();
        shouldStartNextRequest_ = currentRequest_->IsClosed();
    }
    if (currentRequest_ == nullptr || client_ == nullptr) {
        PauseLoop(true);
        return;
    }
    RequestData();  // 调用 client_->RequestData()，双客户端统一入口
    return;
}
```

### E16: `downloader.cpp` — BeginDownload 初始化（L568-L587）

```cpp
bool Downloader::BeginDownload()
{
    MEDIA_LOG_I("BeginDownload %{public}s", name_.c_str());
    std::string url = currentRequest_->url_;
    std::map<std::string, std::string> httpHeader = currentRequest_->httpHeader_;
    if (currentRequest_->httpHeader_.count(USER_AGENT) <= 0) {
        currentRequest_->httpHeader_[USER_AGENT] = GetUserAgent();
        httpHeader[USER_AGENT] = GetUserAgent();
    }
    int32_t timeoutMs = currentRequest_->requestInfo_.timeoutMs;
    FALSE_RETURN_V(!url.empty(), false);
    if (client_) {
        client_->Open(url, httpHeader, timeoutMs);  // 双客户端 Open
    }
    // 设置起始位置和请求大小
    if (currentRequest_->endPos_ <= 0) {
        currentRequest_->startPos_ = 0;
        currentRequest_->requestSize_ = FIRST_REQUEST_SIZE;
    } else {
        int64_t temp = currentRequest_->endPos_ - currentRequest_->startPos_ + 1;
        currentRequest_->requestSize_ = static_cast<int>(std::min(temp,
            static_cast<int64_t>(std::max(currentRequest_->bitRateToRequestSize_, PER_REQUEST_SIZE))));
    }
    // ...
}
```

---

## 八、OpenAppUri AppClient 路由

### E17: `downloader.cpp` — OpenAppUri 调用 AppClient（L638-L666）

```cpp
void Downloader::OpenAppUri()
{
    AutoLock lock(closeMutex_);
    if (currentRequest_ != nullptr) {
        appPreviousRequestUrl_ = currentRequest_->GetUrl();
    }
    if (sourceLoader_ != nullptr && currentRequest_ != nullptr) {
        if (sourceId_ != 0) {
            sourceLoader_->Close(sourceId_);  // 关闭旧 uuid
            MEDIA_LOG_D("Close uuid " PUBLIC_LOG_D64, sourceId_);
        }
        int64_t uuid = 0;
        for (int i = 0; i < APP_OPEN_RETRY_TIMES; i++) {
            // 调用 AppClient 路由：sourceLoader_->Open() 获取 uuid
            uuid = sourceLoader_->Open(appPreviousRequestUrl_, currentRequest_->GetHttpHeader(), client_);
            if (uuid > 0) break;
        }
        if (uuid != 0) {
            client_->SetUuid(uuid);  // 设置 uuid 到 AppClient
            sourceId_ = uuid;
        } else {
            // 打开失败，回退到 HttpCurlClient
            std::shared_ptr<Downloader> unused;
            currentRequest_->statusCallback_(DownloadStatus::PARTTAL_DOWNLOAD, unused, currentRequest_);
        }
    }
}
```

---

## 九、HttpCurlClient 对比

### E18: `http_curl_client.h` — HttpCurlClient 类定义（L38-L72）

```cpp
class HttpCurlClient : public NetworkClient {
public:
    HttpCurlClient(RxHeader headCallback, RxBody bodyCallback, void* userParam);
    ~HttpCurlClient() override;
    Status Init() override;
    Status Open(const string& url, const map<string,string>& httpHeader,
                int32_t timeoutMs) override;
    Status RequestData(long startPos, int len, const RequestInfo& requestInfo,
        HandleResponseCbFunc completedCb) override;
    Status Close(bool isAsync) override;
    Status Deinit() override;
    Status GetIp(string &ip) override;
    void SetAppUid(int32_t appUid) override;
private:
    // libcurl 专用
    CURL* easyHandle_ {nullptr};
    struct curl_slist* headerList_ {nullptr};
    std::string ip_ {};
    bool ipFlag_ {false};
    bool isFirstRequest_ {true};
    bool isFirstOpen_ {true};
    volatile int32_t appUid_ {-1};
};
```

---

## 十、双客户端对比总结

### E19: `downloader.cpp` — 双客户端选择逻辑（L264-L283）

| 维度 | HttpCurlClient | AppClient |
|------|---------------|-----------|
| 工厂方法 | `GetInstance()` | `GetAppInstance()` |
| 底层 | libcurl (curl_easy_perform) | IMediaSourceLoader |
| 线程模型 | 同步阻塞 | 异步回调驱动 |
| 响应方式 | curl内部缓冲，直接回调 rxBody/rxHeader | 外部主动调用 RespondData/RespondHeader |
| 离线缓存 | 不支持 | 通过 IMediaSourceLoader 支持 |
| URL参数 | 直接传递 | 通过 sourceLoader_->Open() 获取 uuid |
| 错误处理 | CURLcode | LoadingRequestError |

### E20: `app_client.cpp` — AppClient 错误码映射（L134-L147）

```cpp
Status ret = Status::OK;
if (requestState_ == LoadingRequestError::LOADING_ERROR_SUCCESS) {
    MEDIA_LOG_I("AppClient RequestData success");
} else if (requestState_ == LoadingRequestError::LOADING_ERROR_SERVER) {
    ret = Status::ERROR_SERVER;
} else if (requestState_ == LoadingRequestError::LOADING_ERROR_NONE) {
    ret = Status::ERROR_INVALID_PARAMETER;
} else {
    clientCode = static_cast<int32_t>(requestState_) * (-1);
    ret = Status::ERROR_UNKNOWN;
}
completedCb(clientCode, serverCode, string(), ret);
```

---

## 十一、关键调用链

```
Downloader::HttpDownloadLoop()
  └─> client_->RequestData(startPos, len, ...)
        ├─> HttpCurlClient::RequestData()
        │     └─> curl_easy_perform() → rxBody/rxHeader 回调
        └─> AppClient::RequestData()
              └─> sourceLoader_->Read(uuid, startPos, len)
                    └─> [外部回调]
                          ├─> AppClient::RespondHeader(uuid, header, redirectUrl)
                          ├─> AppClient::RespondData(uuid, offset, AVSharedMemory)
                          │ └─> rxBody_(buffer, size, ...) → 上层消费者
                          └─> AppClient::FinishLoading(uuid, state)
                                └─> NotifyResponseDataEnd() → 唤醒 RequestData
```

---

## 十二、LoadingRequestError 错误码体系

| 错误码 | 含义 | 处理方式 |
|--------|------|----------|
| LOADING_ERROR_SUCCESS (0) | 成功 | completedCb(0, 0, "", OK) |
| LOADING_ERROR_SERVER (1) | 服务器错误 | completedCb(-1, 416+, "", ERROR_SERVER) |
| LOADING_ERROR_NONE (-1) | 参数错误 | completedCb(-1, 0, "", ERROR_INVALID_PARAMETER) |
| LOADING_ERROR_TIMEOUT (2) | 超时 | 重试 |
| LOADING_ERROR_NETWORK (3) | 网络错误 | 重试 |
| LOADING_ERROR_ABORT (4) | 用户取消 | 停止 |

---

## 十三、文件统计

| 文件 | 行数 | 说明 |
|------|------|------|
| app_client.cpp | 261行 | AppClient 实现 |
| app_client.h | 93行 | AppClient 类定义 |
| media_source_loading_request.cpp | 193行 | MediaSourceLoadingRequest + Combinations |
| media_source_loading_request.h | 79行 | 核心数据结构 |
| downloader.cpp | 1361行 | Downloader 主逻辑 |
| downloader.h | 302行 | Downloader 类定义 |
| http_curl_client.cpp | 453行 | HttpCurlClient 实现（对比） |
| http_curl_client.h | 72行 | HttpCurlClient 类定义（对比） |

---

## 关联记忆

- S195: HttpSourcePlugin Downloader 网络下载架构（上层 Downloader + DownloadRequest）
- S210: HttpSourcePlugin 下载监控装饰器模式（DownloadMonitor）
- S172: MediaSourceLoader 离线缓存