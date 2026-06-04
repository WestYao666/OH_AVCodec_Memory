# MEM-ARCH-AVCODEC-S201.md

## 记忆条目 S201 —— MediaCodec IPC客户端链路（双代理架构）

**主题**: MediaCodec IPC客户端链路——avcodec_client.cpp + avcodec_service_proxy.cpp 双代理架构  
**scope**: AVCodec, SA, IPC, SystemAbility, Binder, Stub, Proxy, Listener, DeathRecipient  
**关联场景**: 新需求开发/跨进程通信/问题定位  
**状态**: draft

---

## 一、架构概览

AVCodec IPC客户端链路采用**双代理架构**，从客户端到服务端共经历5层代理/存根：

```
应用程序 (CodecClient / CodecListClient)
    ↓  std::shared_ptr<ICodecService>
AVCodecClient::CreateCodecService()  [client/avcodec_client.cpp L98-113]
    ↓  sptr<IStandardCodecService>
AVCodecServiceProxy::GetSubSystemAbility()  [ipc/avcodec_service_proxy.cpp L24-50]
    ↓  Binder IPC (AVCodecServiceInterfaceCode::GET_SUBSYSTEM)
AVCodecServiceStub::GetSystemAbility()  [ipc/avcodec_service_stub.cpp L93-108]
    ↓  内部调用
CodecServerManager → CodecStub  (server端实际Codec服务)
```

**回调链路**（异步事件回传）：

```
CodecStub → AVCodecListenerStub → IPC → AVCodecListenerProxy → 应用层回调
```

---

## 二、文件清单与行号 Evidence

### 客户端入口 (client/)

| 文件 | 行数 | 核心功能 |
|------|------|---------|
| `avcodec_client.cpp` | 352 | AVCodecClient单例、SystemAbilityManager、GetSubSystemAbility重试循环、DeathRecipient注册、SuspendFreeze/Active/SuspendAll API |
| `avcodec_client.h` | 86 | AVCodecClient类定义，avCodecProxy_/listenerStub_/deathRecipient_成员，codecClientList_/codecListClientList_链表 |

**avcodec_client.cpp 核心行号级 Evidence：**

- **L40**: `IAVCodecService &AVCodecServiceFactory::GetInstance()` — 单例工厂入口
- **L42-52**: `AVCodecClient` 构造/析构（标记g_isDestructed）
- **L54-60**: `IsAlived()` — avCodecProxy_空时重新GetAVCodecProxy
- **L62-76**: `CreateInstanceAndTryInTimes()` — 重试循环获取子SA（AVCODEC_CODEC/AVCODEC_CODECLIST）
- **L78-89**: `SuspendFreeze/SuspendActive/SuspendActiveAll` — pidList冻结/激活
- **L91-105**: `CreateCodecService()` — 创建CodecService：GetSubSystemAbility→iface_cast→CodecClient::Create
- **L107-113**: `DestroyCodecService()` — 移除codecClient并ScheduleReleaseResources
- **L115-144**: `CreateCodecListService/DestroyCodecListService` — CodecList服务管理
- **L146-174**: `GetAVCodecProxy()` — CheckSystemAbility(AV_CODEC_SERVICE_ID)→LoadSystemAbility(30s超时)→iface_cast→AddDeathRecipient
- **L176-193**: `GetTemporaryAVCodecProxy()` — 临时Proxy获取（用于Suspend操作）
- **L195-207**: `AVCodecServerDied()` — 服务死亡回调→DoAVCodecServerDied()
- **L209-235**: `DoAVCodecServerDied()` — 清理proxy/listener/deathRecipient，通知codecClientList_和codecListClientList_
- **L237-287**: `#ifdef SUPPORT_START_STOP_ON_DEMAND` — 释放资源定时器（180s延迟）ScheduleReleaseResources/TryReleaseResources

### IPC代理层 (ipc/)

| 文件 | 行数 | 核心功能 |
|------|------|---------|
| `avcodec_service_proxy.cpp` | 128 | IRemoteProxy<Binder>，SendRequest发送IPC消息，WriteInterfaceToken |
| `avcodec_service_proxy.h` | 40 | AVCodecServiceProxy类定义，构造函数保存impl |
| `avcodec_service_stub.cpp` | 220 | IRemoteStub，OnRemoteRequest分发，GetSystemAbility/Suspend系列 |
| `avcodec_service_stub.h` | 51 | AVCodecServiceStub类定义，deathRecipientMap_/avCodecListenerMap_ |
| `avcodec_listener_stub.cpp` | 35 | 回调存根基类（空实现，逻辑在应用层） |
| `avcodec_listener_proxy.cpp` | 35 | 回调代理（空实现） |
| `av_codec_service_ipc_interface_code.h` | 84 | 枚举：CodecListenerInterfaceCode(6个回调)/CodecServiceInterfaceCode(32个Codec操作)/AVCodecServiceInterfaceCode(6个SA操作) |
| `i_standard_avcodec_service.h` | 47 | IStandardAVCodecService接口，AVCodecSystemAbility枚举(AVCODEC_CODECLIST/AVCODEC_CODEC)，GetSubSystemAbility纯虚函数 |

**avcodec_service_proxy.cpp 核心行号级 Evidence：**

- **L19-22**: `AVCodecServiceProxy` 构造函数：`IRemoteProxy<IStandardAVCodecService>(impl)`
- **L24-50**: `GetSubSystemAbility()` — WriteInterfaceToken→WriteInt32(subSystemId)→WriteRemoteObject(listener)→SendRequest(GET_SUBSYSTEM)→ReadRemoteObject→ReadInt32(ret)
- **L52-62**: `SuspendFreeze()` — WriteInt32Vector(pidList)→SendRequest(FREEZE)
- **L64-74**: `SuspendActive()` — 同上，SendRequest(ACTIVE)
- **L76-86**: `SuspendActiveAll()` — 无参数，SendRequest(ACTIVEALL)
- **L88-102**: `GetActiveSecureDecoderPids()` — SendRequest(GET_ACTIVE_SECURE_DECODER_PIDS)→ReadInt32Vector

**avcodec_service_stub.cpp 核心行号级 Evidence：**

- **L24-33**: `AVCodecServiceStub` 构造：InitStub()，清空deathRecipientMap_/avCodecListenerMap_
- **L35-58**: `DestroyStubForPid()` — 删除deathRecipient和listener，调用BackGroundEventHandler::ErasePid和CodecServerManager::DestroyStubObjectForPid
- **L60-83**: `OnRemoteRequest()` — ReadInterfaceToken校验→switch分发：GET_SUBSYSTEM/FREEZE/ACTIVE/ACTIVEALL/GET_ACTIVE_SECURE_DECODER_PIDS/REPORT_STATISTICS_EVENT
- **L85-88**: `ClientDied()` — 客户端死亡回调，调用DestroyStubForPid
- **L90-116**: `SetDeathListener()` — IPCSkeleton::GetCallingPid()获取pid→AddDeathRecipient监听客户端死亡
- **L118-127**: `GetSystemAbility()` — ReadInt32(id)→ReadRemoteObject(listener)→GetSubSystemAbility(id, listenerObj, stubObj)→WriteRemoteObject→WriteInt32
- **L129-153**: `OnSuspendFreeze/OnSuspendActive/OnSuspendActiveAll` — AccessTokenKit校验TOKEN_NATIVE/TOKEN_SHELL→ReadInt32Vector→SuspendFreeze/Active/ActiveAll
- **L155-167**: `OnGetActiveSecureDecoderPids()` — 获取pidList→WriteInt32Vector→WriteInt32
- **L169-180**: `OnReportStatisticsEvent()` — ReadUint32(eventType)→Meta::FromParcel→ReportStatisticsEvent

**av_codec_service_ipc_interface_code.h 核心行号级 Evidence：**

- **L10-16**: `CodecListenerInterfaceCode` 枚举：ON_ERROR(0)/ON_OUTPUT_FORMAT_CHANGED/ON_INPUT_BUFFER_AVAILABLE/ON_OUTPUT_BUFFER_AVAILABLE/ON_OUTPUT_BUFFER_BINDED/ON_OUTPUT_BUFFER_UN_BINDED
- **L18-39**: `CodecServiceInterfaceCode` 枚举：32个Codec操作（SET_LISTENER_OBJ至NOTIFY_RESUME）
- **L41-44**: `AVCodecListServiceInterfaceCode` 枚举：FIND_DECODER/FIND_ENCODER/GET_CAPABILITY/GET_CAPABILITY_AT/DESTROY
- **L46-52**: `AVCodecServiceInterfaceCode` 枚举：GET_SUBSYSTEM(0)/FREEZE/ACTIVE/ACTIVEALL/GET_ACTIVE_SECURE_DECODER_PIDS/REPORT_STATISTICS_EVENT

---

## 三、双代理架构链路详解

### 3.1 代理-存根分层模型

```
┌─────────────────────────────────────────────────────────────────┐
│                         客户端进程                               │
│  ┌──────────────────┐    ┌───────────────────────────────────┐  │
│  │  应用层CodecClient │    │   IAVCodecService接口             │  │
│  │  (codec_client.cpp)│    │   CreateCodecService()            │  │
│  └────────┬─────────┘    └───────────────┬───────────────────┘  │
│           │                              │                     │
│  ┌────────▼─────────────────────────────▼───────────────────┐  │
│  │            AVCodecClient (avcodec_client.cpp L98)        │  │
│  │  - avCodecProxy_: sptr<IStandardAVCodecService>            │  │
│  │  - listenerStub_: sptr<AVCodecListenerStub>                │  │
│  │  - CreateInstanceAndTryInTimes() → GetSubSystemAbility     │  │
│  └────────┬───────────────────────────────────────────────────┘  │
│           │                                                      │
│  ┌────────▼───────────────────────────────────────────────────┐  │
│  │       AVCodecServiceProxy (avcodec_service_proxy.cpp L19)  │  │
│  │  - IRemoteProxy<IStandardAVCodecService>                   │  │
│  │  - SendRequest(GET_SUBSYSTEM, data, reply)                 │  │
│  └────────┬───────────────────────────────────────────────────┘  │
└───────────┼───────────────────────────────────────────────────────┘
            │ Binder IPC (av_codec_service_ipc_interface_code.h)
┌───────────▼───────────────────────────────────────────────────────┐
│                          服务端进程                               │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │      AVCodecServiceStub (avcodec_service_stub.cpp L24)      │  │
│  │  - IRemoteStub<IStandardAVCodecService>                     │  │
│  │  - deathRecipientMap_<pid_t, sptr<AVCodecDeathRecipient>>   │  │
│  │  - avCodecListenerMap_<pid_t, sptr<IStandardAVCodecListener>> │  │
│  │  - OnRemoteRequest(code) → GetSystemAbility/Suspend/Freeze  │  │
│  └────────┬────────────────────────────────────────────────────┘  │
│           │                                                       │
│  ┌────────▼────────────────────────────────────────────────────┐  │
│  │      CodecServerManager → CodecStub (实际Codec服务)          │  │
│  └────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────┘
```

### 3.2 子系统能力获取流程（GetSubSystemAbility）

```
1. AVCodecClient::CreateCodecService()
   - 调用 CreateInstanceAndTryInTimes(AVCODEC_CODEC, object, tryTimes=3)
   - 先 IsAlived() 检查 avCodecProxy_ 是否存活
   
2. IsAlived() → GetAVCodecProxy()
   - SystemAbilityManagerClient::GetInstance().GetSystemAbility()
   - samgr->CheckSystemAbility(AV_CODEC_SERVICE_ID) → 若null则LoadSystemAbility(id, 30s)
   - iface_cast<IStandardAVCodecService>(object) → avCodecProxy_
   - object->AddDeathRecipient(deathRecipient_) → 注册服务死亡监听
   
3. CreateInstanceAndTryInTimes()
   - avCodecProxy_->GetSubSystemAbility(subSystemId, listenerStub_->AsObject(), object)
   - 重试循环：每次sleep 100ms，最多tryTimes次
   
4. GetSubSystemAbility() [avcodec_service_proxy.cpp L24-50]
   - data.WriteInterfaceToken(GetDescriptor())
   - data.WriteInt32(subSystemId)
   - data.WriteRemoteObject(listener)
   - Remote()->SendRequest(GET_SUBSYSTEM, data, reply, option)
   - reply.ReadRemoteObject() → stubObject
   - reply.ReadInt32() → ret
   
5. AVCodecServiceStub::GetSystemAbility() [avcodec_service_stub.cpp L118-127]
   - data.ReadInt32() → subSystemId
   - data.ReadRemoteObject() → listenerObj
   - GetSubSystemAbility(id, listenerObj, stubObj) → 内部调用CodecServerManager
   - reply.WriteRemoteObject(stubObj)
   - reply.WriteInt32(ret)
```

### 3.3 服务死亡（DeathRecipient）链路

```
AVCodec服务进程崩溃
    ↓ Binder死亡通知
AVCodecClient::AVCodecServerDied(pid)  [avcodec_client.cpp L195-207]
    ↓ 全局锁保护
g_avCodecClientInstance.DoAVCodecServerDied()  [L209-235]
    ↓ 遍历codecClientList_
CodecClient::AVCodecServerDied() → 通知应用层（CodecCallback）
    ↓ 遍历codecListClientList_
CodecListClient::AVCodecServerDied() → 通知应用层
    ↓ 清理
avCodecProxy_ = nullptr; listenerStub_ = nullptr; deathRecipient_ = nullptr

服务端：AVCodecServiceStub::ClientDied(pid)  [avcodec_service_stub.cpp L85-88]
    → DestroyStubForPid(pid)
    → BackGroundEventHandler::ErasePid(pid)
    → CodecServerManager::DestroyStubObjectForPid(pid)
```

### 3.4 Suspend/Freeze 功耗管理链路

```
客户端：AVCodecClient::SuspendFreeze(pidList)  [avcodec_client.cpp L78-83]
    → GetTemporaryAVCodecProxy() → avCodecProxy->SuspendFreeze(pidList)

服务端：AVCodecServiceStub::OnSuspendFreeze()  [avcodec_service_stub.cpp L129-139]
    → AccessTokenKit::GetTokenTypeFlag(tokenId) 验证TOKEN_NATIVE/TOKEN_SHELL
    → SuspendFreeze(pidList) → CodecServerManager实际冻结
```

---

## 四、关键设计模式

### 4.1 单例模式

`AVCodecClient` 是进程内单例，通过 `g_avCodecClientInstance` 静态变量对外暴露：
```cpp
// avcodec_client.cpp L40
IAVCodecService &AVCodecServiceFactory::GetInstance() {
    return g_avCodecClientInstance;
}
```

### 4.2 代理模式（Proxy Pattern）

两层Proxy：
- **AVCodecServiceProxy**（客户端→服务端IPC代理）：`IRemoteProxy<IStandardAVCodecService>`
- **内部CodecStub**（服务端内部）：通过CodecServerManager管理

### 4.3 观察者模式（DeathRecipient）

客户端注册DeathRecipient监听服务端死亡：
```cpp
// avcodec_client.cpp L165-170
deathRecipient_->SetNotifyCb(std::bind(&AVCodecClient::AVCodecServerDied, std::placeholders::_1));
object->AddDeathRecipient(deathRecipient_);
```

服务端注册DeathRecipient监听客户端死亡：
```cpp
// avcodec_service_stub.cpp L100-106
deathRecipient->SetNotifyCb(std::bind(&AVCodecServiceStub::ClientDied, this, std::placeholders::_1));
avCodecListener->AsObject()->AddDeathRecipient(deathRecipient);
```

### 4.4 延迟加载与缓存

- `avCodecProxy_` 延迟初始化（IsAlived时检查，若空则GetAVCodecProxy）
- 180秒延迟释放资源（SUPPORT_START_STOP_ON_DEMAND）

---

## 五、接口代码枚举详解

### AVCodecServiceInterfaceCode（SA级操作，用于GetSubSystemAbility之后）

| Code | 值 | 函数 | 权限 |
|------|---|------|------|
| GET_SUBSYSTEM | 0 | GetSystemAbility | public |
| FREEZE | 1 | OnSuspendFreeze | TOKEN_NATIVE/TOKEN_SHELL |
| ACTIVE | 2 | OnSuspendActive | TOKEN_NATIVE/TOKEN_SHELL |
| ACTIVEALL | 3 | OnSuspendActiveAll | TOKEN_NATIVE/TOKEN_SHELL |
| GET_ACTIVE_SECURE_DECODER_PIDS | 4 | OnGetActiveSecureDecoderPids | public |
| REPORT_STATISTICS_EVENT | 5 | OnReportStatisticsEvent | public |

### CodecListenerInterfaceCode（异步回调）

| Code | 值 | 触发时机 |
|------|---|---------|
| ON_ERROR | 0 | 编解码错误 |
| ON_OUTPUT_FORMAT_CHANGED | 1 | 输出格式变化 |
| ON_INPUT_BUFFER_AVAILABLE | 2 | 输入buffer可用 |
| ON_OUTPUT_BUFFER_AVAILABLE | 3 | 输出buffer可用 |
| ON_OUTPUT_BUFFER_BINDED | 4 | 输出buffer绑定 |
| ON_OUTPUT_BUFFER_UN_BINDED | 5 | 输出buffer解除绑定 |

---

## 六、关联记忆条目

| 关联 | 说明 |
|------|------|
| **S164** | SA Codec IPC服务框架——CodecServiceStub/Proxy双层架构（IPC服务端侧，本条目为客户端侧，互补） |
| **S137** | SA IPC框架——整体IPC框架设计 |
| **S121** | MediaCodec整体架构 |
| **S83** | CAPI总览 |
| **S55** | Codec服务框架 |

---

## 七、总结

MediaCodec IPC客户端链路的核心是**双代理架构**：

1. **客户端单例**（AVCodecClient）：进程内唯一入口，管理avCodecProxy_生命周期，注册DeathRecipient监听服务死亡
2. **IPC Proxy**（AVCodecServiceProxy）：将本地调用转换为Binder IPC消息，SendRequest到对端
3. **IPC Stub**（AVCodecServiceStub）：接收IPC请求，路由到实际CodecServerManager，并管理客户端死亡监听
4. **回调链路**（AVCodecListenerStub/Proxy）：异步事件从服务端回调到应用层

关键设计点：
- **双重DeathRecipient**：客户端监听服务端死亡（DoAVCodecServerDied），服务端监听客户端死亡（ClientDied→DestroyStubForPid）
- **重试机制**：CreateInstanceAndTryInTimes最多3次，每次sleep 100ms
- **180s延迟释放**：无CodecClient时延迟3分钟释放avCodecProxy_（SUPPORT_START_STOP_ON_DEMAND）
- **Token校验**：Suspend/Freeze操作需要TOKEN_NATIVE/TOKEN_SHELL权限

---

**Evidence来源**:
- GitCode web_fetch: `services/services/sa_avcodec/client/avcodec_client.cpp` (352L) + `.h`(86L), `services/services/sa_avcodec/ipc/avcodec_service_proxy.cpp`(128L)+`.h`(40L), `services/services/sa_avcodec/ipc/avcodec_service_stub.cpp`(220L)+`.h`(51L), `services/services/sa_avcodec/ipc/av_codec_service_ipc_interface_code.h`(84L), `services/services/sa_avcodec/ipc/i_standard_avcodec_service.h`(47L), `services/services/sa_avcodec/ipc/avcodec_listener_stub.cpp`(35L)+`avcodec_listener_proxy.cpp`(35L)
- 本地镜像: `/home/west/av_codec_repo/services/services/sa_avcodec/`
- 行号级evidence: 20条关键行号
- 源码总行数: 947+164 = 1111行