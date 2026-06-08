# MEM-ARCH-AVCODEC-S233: AppClient + IMediaSourceLoader 双路由下载架构

**mem_id**: MEM-ARCH-AVCODEC-S233  
**status**: draft  
**last_updated**: 2026-06-08  
**builder**: builder-agent  

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

### E1: `app_client.h` — AppClient 类定义（L24-L93）

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

### E2: `app_client.cpp` — RequestData 回调驱动（L108-L129）

```cpp
Status AppClient::RequestData(long startPos, int len, const RequestInfo& requestInfo,
    HandleResponseCbFunc completedCb)
{
    // 启动 IMediaSourceLoader 异步 Read
    int32_t res = sourceLoader_->Read(uuid_, static_cast<int64_t>(startPos), static_cast<int64_t>(len));
    // 等待 RespondData/RespondHeader 回调完成
    responseCondition_.Wait(lock, [this] { return isResponseCompleted_.load(); });
    requestState = requestState_; // 通过回调更新状态
    completedCb(clientCode, serverCode, string(), ret);
}
```

**关键差异**：HttpCurlClient 调用 `curl_easy_perform()` 同步等待响应；AppClient 调用 `sourceLoader_->Read()` 后立即返回，由外部通过 `RespondData`/`RespondHeader` 回调驱动后续流程。

### E3: `app_client.cpp` — RespondData 回调写入（L173-L193）

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

### E4: `app_client.cpp` — NotifyResponseDataEnd 状态同步（L153-L162）

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

### E5: `app_client.cpp` — 常量定义（L18-L23）

```cpp
constexpr size_t MAX_MAP_SIZE = 100;
constexpr int DROP_APP_DATA = -2;
constexpr int64_t DEFAULT_CURRENT_OFFSET = -2;
constexpr int BUFFER_FULL = -3;
constexpr int RETRY_SLEEP_TIME = 500;  // ms
constexpr int FINISHLOADING_SLEEP_TIME = 10;  // ms
```

---

## 四、IMediaSourceLoader 回调接口体系

### E6: `media_source_loading_request.h` — 核心数据结构（L27-L69）

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

### E7: `media_source_loading_request.cpp` — Open 注册（L47-L62）

```cpp
int64_t MediaSourceLoadingRequest::Open(int64_t uuid, const shared_ptr<NetworkClient>& client)
{
    auto it = requestMap_.find(uuid);
    if (it != requestMap_.end()) return 0;  // 防重复
    auto element = make_shared<LoadingRequestElements>(uuid, client);
    requestMap_.emplace(uuid, element);  // uuid 分发路由表
    return 0;
}
```

### E8: `media_source_loading_request.cpp` — RespondData 路由（L101-L117）

```cpp
int32_t MediaSourceLoadingRequest::RespondData(int64_t uuid, int64_t offset,
    const shared_ptr<AVSharedMemory>& request)
{
    auto it = requestMap_.find(uuid);
    if (it != requestMap_.end() && it->second != nullptr) {
        return it->second->RespondData(uuid, offset, request);  // 分发至对应 AppClient
    }
    return 0;
}
```

---

## 五、MediaSourceLoaderCombinations 组合器

### E9: `media_source_loading_request.h` — MediaSourceLoaderCombinations（L70-L79）

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

### E10: `media_source_loading_request.cpp` — Open 两阶段初始化（L159-L172）

```cpp
int64_t MediaSourceLoaderCombinations::Open(const string& url,
    const map<string,string>& header, shared_ptr<NetworkClient>& client)
{
    if (request_ == nullptr) {
        request_ = make_shared<MediaSourceLoadingRequest>();
        // 将 MediaSourceLoadingRequest 作为 IMediaSourceLoadingRequest 注入 loader
        loader_->Init(static_pointer_cast<IMediaSourceLoadingRequest>(request_));
    }
    int64_t uuid = loader_->Open(url, header);  // 获取全局唯一 uuid
    request_->Open(uuid, client);                // 在本地映射表中注册
    return uuid;
}
```

---

## 六、双客户端对比

| 维度 | HttpCurlClient | AppClient |
|------|---------------|-----------|
| 底层 | libcurl | IMediaSourceLoader |
| 线程模型 | curl_easy_perform 同步阻塞 | Read异步发起，等待回调 |
| 响应方式 | curl内部缓冲，直接回调 rxBody/rxHeader | 外部主动调用 RespondData/RespondHeader |
| 离线缓存 | 不支持 | 通过 IMediaSourceLoader 支持 |
| HTTP代理 | InitCurProxy + GetHttpProxyInfo | 由 IMediaSourceLoader 处理 |
| 工厂方法 | `GetInstance()` | `GetAppInstance()` |

---

## 七、Downloader 中的双路由选择

在 `downloader.cpp` 中，`Downloader`持有 `shared_ptr<NetworkClient> client_`。根据配置选择：
- `HttpCurlClient`: 标准流媒体下载
- `AppClient`: 需要 App 介入的媒体源（离线缓存场景）

两种客户端通过统一的 `NetworkClient` 接口被 `Downloader::HttpDownloadLoop()` 调用，无需感知具体实现。

---

## 八、关键调用链

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