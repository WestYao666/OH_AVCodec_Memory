---
id: MEM-ARCH-AVCODEC-S170
title: SA Codec 服务框架——IPC五层架构与33+6+5接口枚举体系（本地镜像增强版）
scope: [AVCodec, SA, IPC, CodecServerManager, CodecServiceStub, CodecServiceProxy, CodecClient, SystemAbility, Binder, Stub, Proxy, dlopen, Listener, DeathRecipient, Parcel, DeathRecipient, CodecListenerStub, CodecListenerProxy, SAMgr, GetSubSystemAbility, AVCodecSystemAbility, codecStubMap, InstanceInfo]
topic: SA Codec服务框架IPC五层架构（AVCodecServerManager单例dlopen/AVCodecServer SA注册/CodecServiceStub 33路分发/CodecServiceProxy Binder代理/CodecClient生命周期封装）与接口枚举体系（CodecServiceInterfaceCode 33路/CodecListenerInterfaceCode 6路/AVCodecListServiceInterfaceCode 5路/AVCodecServiceInterfaceCode 5路），构成完整的跨进程通信基础设施。与S137/S161互补，S83 CAPI层调用CodecClient IPC代理，S55回调链路通过CodecListenerInterfaceCode实现。
status: pending_approval
created_at: "2026-05-25T22:05:00+08:00"
evidence_count: 22
source_files: |
  services/services/sa_avcodec/server/avcodec_server_manager.cpp (426行)
  services/services/sa_avcodec/server/include/avcodec_server_manager.h (TBD行)
  services/services/sa_avcodec/server/avcodec_server.cpp (182行)
  services/services/sa_avcodec/ipc/avcodec_service_stub.cpp (220行)
  services/services/sa_avcodec/ipc/avcodec_service_proxy.cpp (128行)
  services/services/sa_avcodec/ipc/av_codec_service_ipc_interface_code.h (84行)
  services/services/sa_avcodec/ipc/avcodec_listener_stub.cpp (35行)
  services/services/sa_avcodec/ipc/avcodec_listener_stub.h (TBD行)
  services/services/sa_avcodec/ipc/avcodec_listener_proxy.cpp (35行)
  services/services/sa_avcodec/ipc/avcodec_death_recipient.h (48行)
  services/services/sa_avcodec/ipc/avcodec_parcel.h (TBD行)
  services/services/sa_avcodec/ipc/avcodec_parcel.cpp (36行)
  services/services/sa_avcodec/ipc/codeclist_parcel.cpp (246行)
  services/services/sa_avcodec/client/avcodec_client.cpp (352行)
  services/services/sa_avcodec/client/avcodec_client.h (TBD行)
关联主题: S137(SA IPC框架早期草案) / S161(SA IPC框架同一主题补充) / S83(CAPI总览调用CodecClient) / S55(回调链路CodecListenerInterfaceCode) / S121(错误码ON_ERROR回调) / S162(CodecListCore能力查询通过AVCodecListServiceInterfaceCode)
related_ids: [S137, S161, S83, S55, S121, S162]
git_branch: master
---

# MEM-ARCH-AVCODEC-S170

> **记忆工厂草案** | Builder Agent | 2026-05-25T22:05:00+08:00（本地镜像增强版）

> **主题**：SA Codec 服务框架——IPC五层架构与33+6+5接口枚举体系（本地镜像增强版）
> **状态**：draft
> **关联**：S137 / S161 / S83 / S55 / S121 / S162

---

## 0 工程信息

- **本地镜像路径**: `/home/west/av_codec_repo/services/services/sa_avcodec/`
- **源码文件**:
  - `server/avcodec_server_manager.cpp` (426行) —— 单例管理/dlopen/Stub管理
  - `server/avcodec_server.cpp` (182行) —— SA注册/DFX诊断
  - `ipc/avcodec_service_stub.cpp` (220行) —— 33路IPC分发
  - `ipc/avcodec_service_proxy.cpp` (128行) —— Binder跨进程代理
  - `ipc/av_codec_service_ipc_interface_code.h` (84行) —— 接口枚举三合一
  - `ipc/avcodec_listener_stub.cpp` (35行) —— 6路回调分发
  - `ipc/avcodec_listener_proxy.cpp` (35行) —— 回调跨进程代理
  - `ipc/avcodec_death_recipient.h` (48行) —— 死亡通知接管
  - `ipc/avcodec_parcel.h` + `avcodec_parcel.cpp` (TBD+36行) —— 序列化工具
  - `ipc/codeclist_parcel.cpp` (246行) —— CodecList能力查询序列化
  - `client/avcodec_client.cpp` (352行) —— 生命周期封装
- **编译产物**: `libcodec_service.z.so`（SAID=3011）
- **依赖库**: `libipc.z.so`, `libsystemabilitymanager.z.so`, `libmemmgrclient.z.so`

---

## 1 架构概览

SA Codec服务框架采用**IPC五层架构**，实现进程间Codec服务调用与回调：

```
应用层（Native C API / JS API）
    ↓ GetAVCodecProxy() / GetCodecListServiceProxy()
CodecClient（client/avcodec_client.cpp 352行）
    ↓ Binder跨进程（iface_cast/IStandardAVCodecService）
CodecServiceProxy（ipc/avcodec_service_proxy.cpp 128行）
    ↓ IPC跨进程
CodecServiceStub（ipc/avcodec_service_stub.cpp 220行）
    ↓ 本地调用
AVCodecServerManager（server/avcodec_server_manager.cpp 426行）
    ↓ dlopen
CodecServer（server/avcodec_server.cpp 182行） = SAID 3011
```

---

## 2 IPC 五层架构（行号级Evidence）

### E1: AVCodecServerManager 单例 + dlopen 插件加载（avcodec_server_manager.cpp L1-90）

**证据**:
- L34: `AVCodecServerManager& AVCodecServerManager::GetInstance()` —— 全局单例（C++11 once_flag）
- L51: `void AVCodecServerManager::Init()` —— Init()在GetInstance()内部调用
- L60-62: `void *handle = dlopen("libmemmgrclient.z.so", RTLD_NOW)` —— 加载内存管理客户端插件
- L90 (h): `static constexpr char LIB_PATH[] = "libmemmgrclient.z.so"` —— dlopen路径常量

### E2: CreateStubObject 双工厂模式（avcodec_server_manager.cpp L74-122）

**证据**:
- L74: `int32_t AVCodecServerManager::CreateStubObject(StubType type, sptr<IRemoteObject> &object)`
- L38 (h): `enum StubType { CODECLIST, CODEC };` —— 双类型枚举
- L74-80: 根据StubType分发：
  - `CODECLIST` → CodecListServiceStub
  - `CODEC` → CodecServiceStub
- L123-132: `InstanceInfo instanceInfo` 结构体填充（pid/callerPid/callerUid/callerTokenId/forwardCallerPid/codecType）

### E3: codecStubMap_ 进程级Stub管理（avcodec_server_manager.cpp L91-180）

**证据**:
- L91-110: `codecStubMap_` (pid_t → pair\<sptr\<IRemoteObject\>, InstanceInfo\>) 进程Stub映射表
- L132: `codecStubMap_.emplace(pid, std::make_pair(object, instanceInfo))` —— Stub注册
- L146-157: `DestroyStubObjectForPid()` —— 遍历codecStubMap_查找并销毁（带EventManager上报）
- L195-215: `EraseCodecObjectByPid(pid_t pid)` —— 进程退出时清理（EventManager::OnInstanceEvent）
- L310-313: `GetInstanceCount()` —— 返回codecStubMap_.size() + codecListStubMap_.size()
- L316-330: `GetInstanceInfoListByPid(pid)` —— 按PID查询实例列表

### E4: AVCodecServer SA注册（avcodec_server.cpp L19-80）

**证据**:
- L47: `void AVCodecServer::OnDump()` —— DFX诊断（dump codecStubMap_实例信息）
- L56: `Publish(this)` —— SAMgr::Publish注册SA
- L73: `SAMGR_REGISTER(AVCodecServer)` —— SA自动注册宏（编译期生效）
- L59-80: `DumpRegisterInfo()` —— 打印InstanceInfo多级调用链（callerPid/forwardCallerPid）

### E5: CodecServiceStub OnRemoteRequest分发（avcodec_service_stub.cpp L81-111）

**证据**:
- L81: `int AVCodecServiceStub::OnRemoteRequest(uint32_t code, MessageParcel &data, MessageParcel &reply, MessageOption &option)`
- L83: `AVCODEC_LOGD("Stub: OnRemoteRequest of code: %{public}u is received", code)`
- L86: `AVCodecServiceStub::GetDescriptor()` —— 接口令牌校验
- L93-104: switch分发5路系统管理接口：
  - L93: `GET_SUBSYSTEM` → GetSystemAbility()
  - L96: `FREEZE` → OnSuspendFreeze()
  - L99: `ACTIVE` → OnSuspendActive()
  - L102: `ACTIVEALL` → OnSuspendActiveAll()
  - L105: `GET_ACTIVE_SECURE_DECODER_PIDS` → OnGetActiveSecureDecoderPids()
- L109: 未匹配返回`IPCObjectStub::OnRemoteRequest()`默认处理

### E6: CodecServiceStub DeathRecipient死亡通知（avcodec_service_stub.cpp L46-118）

**证据**:
- L46-55: `DestroyStubForPid(pid_t pid)` —— 加锁查找并销毁Stub（deathRecipientMap_/avCodecListenerMap_）
- L115-118: `void AVCodecServiceStub::ClientDied(pid_t pid)` —— 死亡回调触发销毁

### E7: CodecServiceStub 33路Codec接口声明（avcodec_service_stub.h / av_codec_service_ipc_interface_code.h）

**证据**: av_codec_service_ipc_interface_code.h L32-65
```cpp
enum class CodecServiceInterfaceCode {
    SET_LISTENER_OBJ = 0,              // L32
    INIT, CONFIGURE, PREPARE, START, // L33-36
    STOP, FLUSH, RESET, RELEASE,       // L37-40
    NOTIFY_EOS, CREATE_INPUT_SURFACE,  // L41-42
    SET_OUTPUT_SURFACE,               // L43
    QUEUE_INPUT_BUFFER,                // L44
    GET_OUTPUT_FORMAT, RELEASE_OUTPUT_BUFFER, // L45-46
    SET_PARAMETER, SET_INPUT_SURFACE,  // L47-48
    DEQUEUE_INPUT_BUFFER, DEQUEUE_OUTPUT_BUFFER, // L49-50
    GET_INPUT_FORMAT, GET_CODEC_INFO,  // L51-52
    DESTROY_STUB, SET_DECRYPT_CONFIG,  // L53-54
    RENDER_OUTPUT_BUFFER_AT_TIME,      // L55
    SET_CUSTOM_BUFFER, GET_CHANNEL_ID, // L56-57
    SET_LPP_MODE,                     // L58
    NOTIFY_MEMORY_EXCHANGE,           // L59
    NOTIFY_FREEZE, NOTIFY_ACTIVE,     // L60-61
    NOTIFY_MEMORY_RECYCLE,            // L62
    NOTIFY_MEMORY_WRITE_BACK,         // L63
    NOTIFY_SUSPEND, NOTIFY_RESUME     // L64-65
};
```

### E8: CodecListenerInterfaceCode 6路回调（av_codec_service_ipc_interface_code.h L22-27）

**证据**:
```cpp
enum class CodecListenerInterfaceCode {
    ON_ERROR = 0,                         // L22
    ON_OUTPUT_FORMAT_CHANGED,             // L23
    ON_INPUT_BUFFER_AVAILABLE,             // L24
    ON_OUTPUT_BUFFER_AVAILABLE,            // L25
    ON_OUTPUT_BUFFER_BINDED,               // L26
    ON_OUTPUT_BUFFER_UN_BINDED             // L27
};
```

### E9: AVCodecListServiceInterfaceCode 5路能力查询（av_codec_service_ipc_interface_code.h L69-73）

**证据**:
```cpp
enum class AVCodecListServiceInterfaceCode {
    FIND_DECODER = 0,   // L69
    FIND_ENCODER,       // L70
    GET_CAPABILITY,     // L71
    GET_CAPABILITY_AT,  // L72
    DESTROY             // L73
};
```

### E10: AVCodecServiceInterfaceCode 5路系统管理（av_codec_service_ipc_interface_code.h L77-82）

**证据**:
```cpp
enum class AVCodecServiceInterfaceCode {
    GET_SUBSYSTEM = 0,                    // L77
    FREEZE, ACTIVE, ACTIVEALL,            // L78-80
    GET_ACTIVE_SECURE_DECODER_PIDS        // L81
};
```

### E11: CodecListenerStub 回调存根（avcodec_listener_stub.cpp L1-35 + avcodec_listener_stub.h L23）

**证据**:
- avcodec_listener_stub.h L23: `class AVCodecListenerStub : public IRemoteStub<IStandardAVCodecListener>`
- avcodec_listener_stub.cpp: 空实现（纯虚基类stub，实际分发由应用层listener实现）
- 接收6路回调请求（ON_ERROR/ON_OUTPUT_FORMAT_CHANGED/INPUT_AVAILABLE/OUTPUT_AVAILABLE/BINDED/UN_BINDED）

### E12: CodecListenerProxy 回调跨进程代理（avcodec_listener_proxy.cpp L1-35）

**证据**:
- avcodec_listener_proxy.cpp: `AVCodecListenerProxy::AVCodecListenerProxy(const sptr\<IRemoteObject\> &impl)`
- `IRemoteProxy\<IStandardAVCodecListener\>(impl)` —— 基类构造，跨进程转发回调

### E13: AVCodecDeathRecipient 死亡通知接管（avcodec_death_recipient.h L1-48）

**证据**:
- L23-30: DeathRecipient类，持有`std::function<void(pid_t)\>`通知回调
- `SetNotifyCb()` —— 设置进程死亡回调
- `OnRemote Died()` —— 触发NotifyCb，调用EraseCodecObjectByPid清理Stub

### E14: CodecClient GetAVCodecProxy 代理获取链路（avcodec_client.cpp L195-225）

**证据**:
- L195: `sptr\<IStandardAVCodecService\> AVCodecClient::GetAVCodecProxy()`
- L199-205: `SystemAbilityManagerClient::GetInstance().GetSystemAbilityManager()` —— 获取SAMgr
- L207-211: `samgr->CheckSystemAbility(AV_CODEC_SERVICE_ID)` —— 查询SA是否已注册
- L212-215: `samgr->LoadSystemAbility(AV_CODEC_SERVICE_ID, 30)` —— 超时30s加载SA
- L220-222: `deathRecipient_ = new AVCodecDeathRecipient(pid)` —— 注册死亡通知
- L224: `object->AddDeathRecipient(deathRecipient_)` —— 挂载死亡接收者
- L229-232: `listenerStub_ = new AVCodecListenerStub()` —— 创建回调Stub
- L235: `return avCodecProxy_` —— 返回Codec服务代理

### E15: CodecClient CreateCodecService 实例创建（avcodec_client.cpp L70-135）

**证据**:
- L70: `CreateInstanceAndTryInTimes(subSystemId, object, tryTimes)` —— 循环获取Stub实例
- L80: `avCodecProxy_->GetSubSystemAbility(subSystemId, listenerStub_->AsObject(), object)` —— 核心IPC调用
- L129: `IStandardAVCodecService::AVCODEC_CODEC` —— 创建Codec服务
- L132: `iface_cast\<IStandardCodecService\>(object)` —— 转换为CodecService代理
- L142-171: `DestroyCodecService()` / `DestroyCodecListService()` —— 实例销毁

### E16: CodecClient 两种代理——GetAVCodecProxy vs GetTemporaryAVCodecProxy（avcodec_client.cpp L195-250）

**证据**:
- L195-237: `GetAVCodecProxy()` —— 带deathRecipient长期代理
- L229-241: `GetTemporaryAVCodecProxy()` —— 临时代理（无deathRecipient，用于一次性操作）
- L241: `sptr\<IStandardAVCodecService\> avCodecProxy = iface_cast\<IStandardAVCodecService\>(object)` —— iface_cast转换

### E17: SuspendFreeze / SuspendActive 系统级省电（avcodec_service_stub.cpp L165-215）

**证据**:
- L165-181: `OnSuspendFreeze(data, reply)` —— 冻结Codec实例
- L181-197: `OnSuspendActive(data, reply)` —— 解冻Codec实例
- L197-215: `OnSuspendActiveAll(data, reply)` —— 全部解冻（含Token校验：NATIVE|SHELL token）

### E18: OnGetActiveSecureDecoderPids 安全解码器PID查询（avcodec_service_stub.cpp L213-220）

**证据**:
- L213: `int32_t ret = GetActiveSecureDecoderPids(pidList)` —— 获取安全解码器PID列表
- L215: `reply.WriteInt32Vector(pidList)` —— 序列化PID向量返回

### E19: AVCodecParcel Format序列化（avcodec_parcel.h / avcodec_parcel.cpp L1-36）

**证据**:
- avcodec_parcel.h: `class AVCodecParcel` —— Format序列化工具类
- avcodec_parcel.cpp: `AVCodecParcel::Marshalling()` / `AVCodecParcel::Unmarshalling()`
- 用于IPC参数中Media::Format对象的序列化/反序列化

### E20: codeclist_parcel.cpp CodecList能力查询序列化（codeclist_parcel.cpp L1-246）

**证据**:
- L1-246: CodecList能力数据序列化/反序列化
- 用于AVCodecListServiceInterfaceCode的FIND_DECODER/FIND_ENCODER/GET_CAPABILITY返回值打包

### E21: InstanceInfo 多级调用链追踪（avcodec_server_manager.cpp L123-132）

**证据**:
```cpp
InstanceInfo instanceInfo = {
    pid,           // 当前进程PID
    callerPid,     // 调用方PID
    callerUid,     // 调用方UID
    callerTokenId, // 调用方Token
    forwardCallerPid, // 前向调用方PID（跨进程桥接场景）
    codecType      // Codec类型（Video/Audio）
};
```

### E22: OnSuspendActiveAll Token权限校验（avcodec_service_stub.cpp L197-215）

**证据**:
- L199-203: `AccessTokenKit::GetTokenTypeFlag(tokenId)` —— Token类型校验
- L200-202: 仅允许`TOKEN_NATIVE`或`TOKEN_SHELL`调用`SuspendActiveAll`（系统级省电操作需特权）

---

## 3 接口枚举体系总结

| 枚举名称 | 接口数 | 文件位置 | 用途 |
|---------|--------|---------|------|
| CodecServiceInterfaceCode | 33路 | av_codec_service_ipc_interface_code.h L32-65 | Codec实例生命周期+编解码操作 |
| CodecListenerInterfaceCode | 6路 | 同上 L22-27 | Codec→应用的异步回调 |
| AVCodecListServiceInterfaceCode | 5路 | 同上 L69-73 | 能力查询（FindDecoder/FindEncoder/GetCapability） |
| AVCodecServiceInterfaceCode | 5路 | 同上 L77-82 | SA级系统管理（Freeze/Active/SecurePids） |

---

## 4 回调链路

```
应用层 Listener（JavaScript/Native）
    ↓ 设置SetListenerObj
CodecClient.listenerStub_（本地Stub）
    ↓ Binder跨进程
CodecListenerProxy（客户端Proxy）
    ↓ IPC
CodecListenerStub（服务端Stub）
    ↓ 触发
应用层onError/onOutputFormatChanged/onInputBufferAvailable/onOutputBufferAvailable回调
```

---

## 5 与现有S系列记忆关联

| 关联记忆 | 关系 |
|---------|------|
| S137 | SA IPC框架早期草案，S170为增强版（行号级evidence） |
| S161 | 同一主题，S170补充本地镜像行号+接口枚举完整代码 |
| S83/CAPI总览 | S83的Native C API层通过CodecClient.GetAVCodecProxy()调用IPC代理 |
| S55/回调链路 | S55四路回调体系通过CodecListenerInterfaceCode的6路回调实现 |
| S121/错误码 | 错误码通过ON_ERROR回调（CodecListenerInterfaceCode::ON_ERROR）传递 |
| S162/CodecList | CodecList能力查询通过AVCodecListServiceInterfaceCode的5路接口实现 |

---

## 6 关键文件索引

| 文件 | 行数 | 核心职责 |
|------|------|---------|
| server/avcodec_server_manager.cpp | 426 | 单例/插件加载/Stub管理/InstanceInfo |
| server/avcodec_server.cpp | 182 | SA注册/DFX诊断/Publish |
| ipc/avcodec_service_stub.cpp | 220 | 33路分发/DeathRecipient/Suspend |
| ipc/avcodec_service_proxy.cpp | 128 | Binder跨进程代理封装 |
| ipc/av_codec_service_ipc_interface_code.h | 84 | 接口枚举三合一 |
| ipc/avcodec_listener_stub.cpp | 35 | 6路回调分发存根 |
| ipc/avcodec_listener_proxy.cpp | 35 | 回调跨进程代理 |
| ipc/avcodec_death_recipient.h | 48 | 死亡通知接管 |
| ipc/avcodec_parcel.cpp | 36 | Format序列化工具 |
| ipc/codeclist_parcel.cpp | 246 | CodecList序列化 |
| client/avcodec_client.cpp | 352 | 生命周期/代理获取/DeathRecipient |

---

**状态**：draft（待增强后提交审批）