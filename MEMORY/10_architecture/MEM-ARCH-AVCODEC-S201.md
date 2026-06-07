# MEM-ARCH-AVCODEC-S201: MediaCodec IPC客户端链路——双代理架构

> **主题**: S201 — MediaCodec IPC客户端链路——avcodec_client.cpp + avcodec_service_proxy.cpp 双代理架构  
> **scope**: AVCodec, SA, IPC, SystemAbility, Binder, Stub, Proxy, Listener, DeathRecipient  
> **关联场景**: 新需求开发/跨进程通信/问题定位  
> **状态**: submitted  
> **mem_id**: MEM-ARCH-AVCODEC-S201  
> **来源**: 基于本地镜像 `/home/west/av_codec_repo/services/services/sa_avcodec/` 探索
> **生成时间**: 2026-06-08T01:10 GMT+8  
> **关联**: S164(S137/S121/S83/S55)

---

## 一、架构总览

AVCodec IPC 客户端链路采用**双代理架构**，五层组件协作：

```
┌─────────────────────────────────────────────────────────────────┐
│                    应用层（Native C API）                        │
│              native_avcodec_*.cpp → CodecClient                  │
└─────────────────────┬───────────────────────────────────────────┘
                      │ CreateCodecService()
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│ AVCodecClient（单例，IAVCodecService接口）               │ client/avcodec_client.cpp:50-352
│  · GetAVCodecProxy() → samgr → AV_CODEC_SERVICE_ID:3011         │
│  · CreateInstanceAndTryInTimes() 重试3次×100ms                   │
│  · deathRecipient_/listenerStub_ 双向死亡监听 │
│  · RELEASE_DELAY_SECONDS=180s 延迟释放资源 │
└─────────────────────┬───────────────────────────────────────────┘
                      │ GetSubSystemAbility(AVCODEC_CODEC/CODECLIST)
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│ AVCodecServiceProxy（IRemoteProxy，客户端IPC代理）          │  ipc/avcodec_service_proxy.cpp:23-128
│  · SendRequest(GET_SUBSYSTEM/FREEZE/ACTIVE/ACTIVEALL/...) │
│  · MessageParcel序列化 → Binder驱动 → 服务端                     │
└─────────────────────┬───────────────────────────────────────────┘
                      │ Binder IPC
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│ AVCodecServiceStub（IRemoteStub，服务端分发）             │  ipc/avcodec_service_stub.cpp:32-220
│  · OnRemoteRequest() 5路case分发 │
│  · SetDeathListener() → avCodecListenerMap_[pid]                │
│  · ClientDied() → DestroyStubForPid() → 清理资源 │
│  · TOKEN_NATIVE/SHELL权限校验                                    │
└─────────────────────┬───────────────────────────────────────────┘
                      │ CreateCodecService()
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│           CodecClient（引擎客户端，生命周期管理）                  │  codec_client.cpp
│  · codecClientList_/codecListClientList_追踪 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 二、五层接口枚举体系

### 2.1 AVCodecServiceInterfaceCode（服务管理层，5个）

来源：`av_codec_service_ipc_interface_code.h:67-73`

| 枚举值 | 代码 | 功能 |
|--------|------|------|
| GET_SUBSYSTEM | 0 | 获取Codec/CodecList子系统Stub对象 |
| FREEZE | 1 | 冻结指定PID列表的Codec实例 |
| ACTIVE | 2 | 激活指定PID列表的Codec实例 |
| ACTIVEALL | 3 | 全局激活所有Codec实例 |
| GET_ACTIVE_SECURE_DECODER_PIDS | 4 | 查询活跃安全解码器进程列表 |

### 2.2 CodecServiceInterfaceCode（Codec生命周期，33个）

来源：`av_codec_service_ipc_interface_code.h:26-56`

覆盖 Init/Configure/Prepare/Start/Stop/Flush/Reset/Release 等33个接口，是 CodecClient ↔ CodecServer IPC 的主要通道。

### 2.3 CodecListenerInterfaceCode（回调，6个）

来源：`av_codec_service_ipc_interface_code.h:18-24`

| 枚举值 | 功能 |
|--------|------|
| ON_ERROR | 错误回调 |
| ON_OUTPUT_FORMAT_CHANGED | 格式变化 |
| ON_INPUT_BUFFER_AVAILABLE | 输入Buffer就绪 |
| ON_OUTPUT_BUFFER_AVAILABLE | 输出Buffer就绪 |
| ON_OUTPUT_BUFFER_BINDED | Buffer绑定 |
| ON_OUTPUT_BUFFER_UN_BINDED | Buffer解绑 |

### 2.4 AVCodecListServiceInterfaceCode（能力查询，5个）

来源：`av_codec_service_ipc_interface_code.h:59-65`

FindDecoder/FindEncoder/GetCapability/GetCapabilityAt/Destroy。

---

## 三、AVCodecClient 单例工厂

来源：`client/avcodec_client.cpp:37-352` + `client/avcodec_client.h:29-68`

### 3.1 核心成员

```cpp
// avcodec_client.h:50-68
sptr<IStandardAVCodecService> avCodecProxy_ = nullptr; // Codec服务代理
sptr<AVCodecListenerStub> listenerStub_ = nullptr;        // 回调存根
sptr<AVCodecDeathRecipient> deathRecipient_ = nullptr;   // 死亡监听
std::list<std::shared_ptr<ICodecService>> codecClientList_; // CodecClient列表
std::list<std::shared_ptr<ICodecListService>> codecListClientList_; // CodecListClient列表
#ifdef SUPPORT_START_STOP_ON_DEMAND
int32_t releaseTimerId_ = 0;
static constexpr uint32_t RELEASE_DELAY_SECONDS = 180;   // 3分钟延迟释放
#endif
std::mutex mutex_;
```

### 3.2 GetAVCodecProxy 获取服务代理

来源：`avcodec_client.cpp:175-203`

```cpp
sptr<IStandardAVCodecService> AVCodecClient::GetAVCodecProxy()
{
    // E1: avcodec_client.cpp:178-180 samgr获取
    sptr<ISystemAbilityManager> samgr = SystemAbilityManagerClient::GetInstance().GetSystemAbilityManager();
    
    // E2: avcodec_client.cpp:183 CheckSystemAbility
    sptr<IRemoteObject> object = samgr->CheckSystemAbility(OHOS::AV_CODEC_SERVICE_ID);
    
    // E3: avcodec_client.cpp:185-186 LoadSystemAbility 30s超时
    if (object == nullptr) {
        object = samgr->LoadSystemAbility(OHOS::AV_CODEC_SERVICE_ID, 30);
    }
    
    // E4: avcodec_client.cpp:190 iface_cast创建代理
    avCodecProxy_ = iface_cast<IStandardAVCodecService>(object);
    
    // E5: avcodec_client.cpp:193-205 添加死亡监听
    deathRecipient_ = new AVCodecDeathRecipient(pid);
    deathRecipient_->SetNotifyCb(std::bind(&AVCodecClient::AVCodecServerDied, ...));
    object->AddDeathRecipient(deathRecipient_);
    
    // E6: avcodec_client.cpp:207-209 创建监听器存根
    listenerStub_ = new AVCodecListenerStub();
    return avCodecProxy_;
}
```

**流程**：CheckSystemAbility → 若null则LoadSystemAbility（30s超时）→ iface_cast → AddDeathRecipient → 返回代理

### 3.3 CreateInstanceAndTryInTimes 重试机制

来源：`avcodec_client.cpp:62-76`

```cpp
// E7: avcodec_client.cpp:64-76 重试循环
int32_t AVCodecClient::CreateInstanceAndTryInTimes(
    IStandardAVCodecService::AVCodecSystemAbility subSystemId,
    sptr<IRemoteObject> &object, uint32_t tryTimes)
{
    do {
        if (!IsAlived()) {
            std::this_thread::sleep_for(std::chrono::milliseconds(100)); // 100ms
            continue;
        }
        // E8: avcodec_client.cpp:69 GetSubSystemAbility调用
        ret = avCodecProxy_->GetSubSystemAbility(subSystemId, listenerStub_->AsObject(), object);
        if (object != nullptr) break;
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
        continue;
    } while (--tryTimes);
}
```

**重试策略**：默认3次，每次间隔100ms（`tryTimes = 3`）。

### 3.4 CreateCodecService 创建Codec客户端

来源：`avcodec_client.cpp:98-115`

```cpp
// E9: avcodec_client.cpp:100-115
int32_t AVCodecClient::CreateCodecService(std::shared_ptr<ICodecService> &codecClient)
{
    std::lock_guard<std::mutex> lock(mutex_);
    CancelTimer();
    
    sptr<IRemoteObject> object = nullptr;
    // E10: avcodec_client.cpp:104 CreateInstanceAndTryInTimes
    int32_t ret = CreateInstanceAndTryInTimes(
        IStandardAVCodecService::AVCodecSystemAbility::AVCODEC_CODEC, object);
    
    sptr<IStandardCodecService> codecProxy = iface_cast<IStandardCodecService>(object);
    ret = CodecClient::Create(codecProxy, codecClient);
    
    codecClientList_.push_back(codecClient); // E11: 追踪列表
    return AVCS_ERR_OK;
}
```

### 3.5 180秒延迟释放机制

来源：`avcodec_client.h:65` + `avcodec_client.cpp:278-335`

```cpp
// E12: avcodec_client.h:65 180秒常量
static constexpr uint32_t RELEASE_DELAY_SECONDS = 180;

// E13: avcodec_client.cpp:299-307 ScheduleReleaseResources
void AVCodecClient::ScheduleReleaseResources()
{
    CancelTimer();
    bool hasAnyClient = !codecClientList_.empty(); // 只检查CodecClient
    if (!hasAnyClient) {
        // E14: 设置180s定时器
        releaseTimerId_ = AVCodecXCollie::GetInstance().SetTimer(
            "AVCodecClient_ReleaseResources", false, false,
            RELEASE_DELAY_SECONDS, ReleaseTimerCallback);
    }
}
```

**设计意图**：当所有CodecClient销毁后，延迟180秒再释放IPC代理资源，避免频繁创建/销毁。

---

## 四、AVCodecServiceProxy 客户端IPC代理

来源：`ipc/avcodec_service_proxy.cpp:23-128` + `ipc/avcodec_service_proxy.h:24-36`

```cpp
// E15: avcodec_service_proxy.h:24-36 类定义
class AVCodecServiceProxy : public IRemoteProxy<IStandardAVCodecService>, public NoCopyable {
public:
    explicit AVCodecServiceProxy(const sptr<IRemoteObject> &impl);
    int32_t GetSubSystemAbility(...) override;
    int32_t SuspendFreeze(const std::vector<pid_t> &pidList) override;
    int32_t SuspendActive(const std::vector<pid_t> &pidList) override;
    int32_t SuspendActiveAll() override;
    int32_t GetActiveSecureDecoderPids(std::vector<pid_t> &pidList) override;
};
```

### 4.1 GetSubSystemAbility 获取子系统

来源：`avcodec_service_proxy.cpp:36-57`

```cpp
// E16: avcodec_service_proxy.cpp:36-57
int32_t AVCodecServiceProxy::GetSubSystemAbility(
    IStandardAVCodecService::AVCodecSystemAbility subSystemId,
    const sptr<IRemoteObject> &listener, sptr<IRemoteObject> &object)
{
    MessageParcel data, reply;
    MessageOption option;
    
    data.WriteInterfaceToken(AVCodecServiceProxy::GetDescriptor()); // E17: 写入token
    data.WriteInt32(static_cast<int32_t>(subSystemId));             // E18: 写入子系统ID
    data.WriteRemoteObject(listener);                                 // E19: 写入监听器对象
    
    // E20: SendRequest通过Binder发送，code=GET_SUBSYSTEM(0)
    int error = Remote()->SendRequest(
        static_cast<uint32_t>(AVCodecServiceInterfaceCode::GET_SUBSYSTEM),
        data, reply, option);
    
    object = reply.ReadRemoteObject(); // E21: 读取返回的Stub对象
    return reply.ReadInt32();
}
```

### 4.2 SuspendFreeze/Active/ActiveAll

来源：`avcodec_service_proxy.cpp:59-100`

```cpp
// E22: avcodec_service_proxy.cpp:59-73 SuspendFreeze
int32_t AVCodecServiceProxy::SuspendFreeze(const std::vector<pid_t> &pidList)
{
    MessageParcel data, reply;
    data.WriteInt32Vector(pidList); // E23: 写入PID列表
    int error = Remote()->SendRequest(
        static_cast<uint32_t>(AVCodecServiceInterfaceCode::FREEZE), data, reply, option);
    return reply.ReadInt32();
}
```

---

## 五、AVCodecServiceStub 服务端分发

来源：`ipc/avcodec_service_stub.cpp:32-220`

```cpp
// E24: avcodec_service_stub.cpp:32-65 OnRemoteRequest分发
int AVCodecServiceStub::OnRemoteRequest(uint32_t code, MessageParcel &data,
                                         MessageParcel &reply, MessageOption &option)
{
    auto remoteDescriptor = data.ReadInterfaceToken();
    // E25: 验证token
    if (AVCodecServiceStub::GetDescriptor() != remoteDescriptor) {
        return AVCS_ERR_INVALID_OPERATION;
    }
    switch (code) {
        case GET_SUBSYSTEM: ret = GetSystemAbility(data, reply); break;
        case FREEZE:          ret = OnSuspendFreeze(data, reply); break;
        case ACTIVE:          ret = OnSuspendActive(data, reply); break;
        case ACTIVEALL:       ret = OnSuspendActiveAll(data, reply); break;
        case GET_ACTIVE_SECURE_DECODER_PIDS: ret = OnGetActiveSecureDecoderPids(data, reply); break;
        default: return IPCObjectStub::OnRemoteRequest(code, data, reply, option);
    }
}
```

### 5.1 SetDeathListener 客户端死亡监听

来源：`avcodec_service_stub.cpp:96-129`

```cpp
// E26: avcodec_service_stub.cpp:96-129
int32_t AVCodecServiceStub::SetDeathListener(const sptr<IRemoteObject> &object)
{
    pid_t pid = IPCSkeleton::GetCallingPid(); // E27: 获取调用方PID
    
    // E28: avcodec_listener_map_[pid] 存储监听器
    avCodecListenerMap_[pid] = avCodecListener;
    deathRecipientMap_[pid] = deathRecipient;
    
    avCodecListener->AsObject()->AddDeathRecipient(deathRecipient); // E29: 注册死亡监听
    return AVCS_ERR_OK;
}
```

### 5.2 DestroyStubForPid 按PID清理

来源：`avcodec_service_stub.cpp:37-63`

```cpp
// E30: avcodec_service_stub.cpp:37-63
int32_t AVCodecServiceStub::DestroyStubForPid(pid_t pid)
{
    std::lock_guard<std::mutex> lock(mutex_);
    
    // E31: 清理deathRecipientMap_和avCodecListenerMap_
    (void)deathRecipientMap_.erase(itDeath);
    (void)avCodecListenerMap_.erase(itListener);
    
    // E32: BackGroundEventHandler擦除PID
    BackGroundEventHandler::GetInstance().ErasePid(pid);
    
    // E33: AVCodecServerManager销毁Stub
    AVCodecServerManager::GetInstance().DestroyStubObjectForPid(pid);
}
```

### 5.3 TOKEN_NATIVE/SHELL权限校验

来源：`avcodec_service_stub.cpp:133-157`

```cpp
// E34: avcodec_service_stub.cpp:135-137权限校验
auto tokenId = IPCSkeleton::GetCallingTokenID();
auto tokenType = AccessTokenKit::GetTokenTypeFlag(tokenId);
CHECK_AND_RETURN_RET_LOG(
    tokenType == ATokenTypeEnum::TOKEN_NATIVE || tokenType == ATokenTypeEnum::TOKEN_SHELL,
    AVCS_ERR_INVALID_OPERATION, "Only native|shell tokens allowed");
```

**安全设计**：FREEZE/ACTIVE/ACTIVEALL操作仅允许Native或Shell Token调用。

---

## 六、AVCodecDeathRecipient 死亡监听

来源：`ipc/avcodec_death_recipient.h:24-47`

```cpp
// E35: avcodec_death_recipient.h:24-47
class AVCodecDeathRecipient : public IRemoteObject::DeathRecipient, public NoCopyable {
public:
    explicit AVCodecDeathRecipient(pid_t pid) : pid_(pid) {}
    
    void OnRemoteDied(const wptr<IRemoteObject> &remote) override // E36: 死亡回调
    {
        if (diedCb_ != nullptr) {
            diedCb_(pid_); // E37: 触发回调，传入PID
        }
    }
    
    void SetNotifyCb(NotifyCbFunc func) { diedCb_ = func; } // E38: 设置回调
private:
    pid_t pid_ = 0;
    NotifyCbFunc diedCb_ = nullptr;
};
```

---

## 七、双向死亡监听链

```
客户端进程 服务端进程
┌────────────────────────┐         ┌────────────────────────┐
│ AVCodecClient │         │ AVCodecServiceStub    │
│  avCodecProxy_(Proxy) │◄────────│ avCodecListenerMap_  │
│  deathRecipient_  ─────┼──Add───▶│  deathRecipientMap_   │
│  listenerStub_    ─────┼────────▶│  IStandardAVCodec     │
└────────────────────────┘         │  Listener(passed in)  │
       │                           └────────────────────────┘
       │                                    ▲
       │       Binder IPC                   │
       │◄───────────────────────────────────┘
       ▼ ClientDied(pid)
┌────────────────────────┐
│ CodecServerManager │  DoAVCodecServerDied()
│ (服务端单例)           │  → 清理codecClientList_
└────────────────────────┘ → 清理codecListClientList_
```

来源：`avcodec_client.cpp:206-249`

- **客户端侧**：在`GetAVCodecProxy()`中注册`AVCodecDeathRecipient`，当服务端死亡时触发`AVCodecServerDied(pid)`
- **服务端侧**：在`SetDeathListener()`中注册`AVCodecDeathRecipient`，当客户端死亡时触发`ClientDied(pid)` → `DestroyStubForPid(pid)`

---

## 八、关联文件清单

| 文件 | 路径 | 行数 | 说明 |
|------|------|------|------|
| avcodec_client.cpp | services/services/sa_avcodec/client/ | 352 | AVCodecClient单例实现 |
| avcodec_client.h | services/services/sa_avcodec/client/ | 86 | AVCodecClient类定义 |
| avcodec_service_proxy.cpp | services/services/sa_avcodec/ipc/ | 128 | AVCodecServiceProxy IPC代理 |
| avcodec_service_proxy.h | services/services/sa_avcodec/ipc/ | 40 | AVCodecServiceProxy类定义 |
| avcodec_service_stub.cpp | services/services/sa_avcodec/ipc/ | 220 | AVCodecServiceStub服务端分发 |
| avcodec_service_stub.h | services/services/sa_avcodec/ipc/ | 51 | AVCodecServiceStub类定义 |
| avcodec_death_recipient.h | services/services/sa_avcodec/ipc/ | 48 | DeathRecipient定义 |
| avcodec_listener_stub.cpp | services/services/sa_avcodec/ipc/ | 35 | ListenerStub实现 |
| avcodec_listener_stub.h | services/services/sa_avcodec/ipc/ | 35 | ListenerStub类定义 |
| avcodec_listener_proxy.cpp | services/services/sa_avcodec/ipc/ | 35 | ListenerProxy实现 |
| avcodec_listener_proxy.h | services/services/sa_avcodec/ipc/ | 35 | ListenerProxy类定义 |
| av_codec_service_ipc_interface_code.h | services/services/sa_avcodec/ipc/ | 84 | IPC接口枚举定义 |
| i_standard_avcodec_service.h | services/services/sa_avcodec/ipc/ | 47 | IStandardAVCodecService接口 |
| i_standard_avcodec_listener.h | services/services/sa_avcodec/ipc/ | 35 | IStandardAVCodecListener接口 |

---

## 九、关键设计模式

| 模式 | 位置 | 说明 |
|------|------|------|
| 单例模式 | `avcodec_client.cpp:37-39` | `g_avCodecClientInstance` 全局单例 |
| 代理模式 | `avcodec_service_proxy.h:24` | `IRemoteProxy<IStandardAVCodecService>` |
| 存根模式 | `avcodec_service_stub.cpp:32` | `IRemoteStub<IStandardAVCodecService>` |
| 死亡监听 | `avcodec_death_recipient.h:24` | `IRemoteObject::DeathRecipient` |
| 延迟释放 | `avcodec_client.cpp:278-335` | 180s XCollie定时器 |
| 重试机制 | `avcodec_client.cpp:64-76` | 3次×100ms |
| 权限校验 | `avcodec_service_stub.cpp:135-137` | TOKEN_NATIVE/SHELL |

---

## 十、关联记忆

| ID | 主题 |
|----|------|
| S164 | SA Codec IPC服务框架（avcodec_service_stub.cpp+proxy.cpp双层架构） |
| S137 | SA Codec服务框架（AVCodecServerManager+dlopen） |
| S121 | AVCodec错误码与回调体系 |
| S83 | AVCodec Native C API架构 |
| S55 | AVCodec模块间回调链路 |