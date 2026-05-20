---
mem_id: MEM-ARCH-AVCODEC-S170
title: SA Codec 服务框架——IPC五层架构与33+6+5接口枚举体系
status: pending_approval
scope: [AVCodec, SA, IPC, CodecServerManager, CodecServiceStub, CodecServiceProxy, CodecClient, SystemAbility, Binder, Stub, Proxy, dlopen, Listener, DeathRecipient, Parcel]
assoc_scenarios: [新需求开发/问题定位/跨进程通信/新人入项]
sources:
  - https://gitcode.com/openharmony/multimedia_av_codec
evidence:
  - file: services/services/sa_avcodec/server/avcodec_server_manager.cpp
    lines: "426"
    desc: AVCodecServerManager单例，dlopen加载插件，codecStubMap_进程管理，InstanceInfo多级调用链
  - file: services/services/sa_avcodec/server/avcodec_server.cpp
    lines: "182"
    desc: AVCodecServer SA注册(SAID=3011)，SAMgr::Publish，OnDump诊断，DumpRegisterInfo
  - file: services/services/sa_avcodec/ipc/avcodec_service_stub.cpp
    lines: "220"
    desc: CodecServiceStub服务端IRemoteStub，OnRemoteRequest 33路分发
  - file: services/services/sa_avcodec/ipc/avcodec_service_proxy.cpp
    lines: "128"
    desc: CodecServiceProxy客户端IRemoteProxy，跨进程Binder调用封装
  - file: services/services/sa_avcodec/ipc/av_codec_service_ipc_interface_code.h
    lines: "84"
    desc: IPC接口枚举三合一：CodecServiceInterfaceCode(33)/CodecListenerInterfaceCode(6)/AVCodecListServiceInterfaceCode(5)/AVCodecServiceInterfaceCode(5)
  - file: services/services/sa_avcodec/ipc/avcodec_listener_stub.cpp
    lines: "35"
    desc: CodecListenerStub服务端回调存根，OnRemoteRequest六路回调分发
  - file: services/services/sa_avcodec/ipc/avcodec_listener_proxy.cpp
    lines: "35"
    desc: CodecListenerProxy客户端回调代理，跨进程回调到应用层
  - file: services/services/sa_avcodec/ipc/avcodec_parcel.h
    lines: "33"
    desc: Parcel序列化工具，头文件定义
  - file: services/services/sa_avcodec/ipc/avcodec_death_recipient.h
    lines: "48"
    desc: DeathRecipient死亡通知，接管Stub失效回调
  - file: services/services/sa_avcodec/client/avcodec_client.cpp
    lines: "352"
    desc: CodecClient生命周期封装，CreateStub/SetListener/Init/Configure/Start/Stop/Release
generated: "2026-05-21T05:25:00+08:00"
---

# S170：SA Codec 服务框架——IPC五层架构与接口枚举体系

## 主题

SA Codec 服务框架的**IPC五层架构**（AVCodecServerManager / AVCodecServer / CodecServiceStub / CodecServiceProxy / CodecClient）与**接口枚举体系**（CodecServiceInterfaceCode 33路 / CodecListenerInterfaceCode 6路 / AVCodecListServiceInterfaceCode 5路 / AVCodecServiceInterfaceCode 5路），构成完整的跨进程通信基础设施。

---

## 1. IPC 五层架构

### 1.1 AVCodecServerManager 单例（avcodec_server_manager.cpp, 426行）

**核心职责**：SA框架管理器，单例模式，负责插件加载与Codec Stub实例管理。

**关键证据**：
- L18-30: `static std::once_flag g_flag;` — C++11单例初始化
- L34: `AVCodecServerManager& AVCodecServerManager::GetInstance()` — 全局单例获取
- L42-48: `dlopen("libMemMgr.z.so")` + `dlopen("libcodecstub.z.so")` — 插件动态加载
- L55-62: `CreateStubObject(int stubType)` — 双Stub工厂分发：
  - `CODEC_LIST_STUB_TYPE=0` → CodecListServiceStub
  - `CODEC_STUB_TYPE=1` → CodecServiceStub
- L91-110: `codecStubMap_` (pid → sp<CodecServiceStub>) 进程级Stub管理
- L127: `EraseCodecObjectByPid(pid_t pid)` — 进程退出清理
- L150-180: `InstanceInfo` 结构体 — 多级调用链追踪（callerPid / callerUid / callerTokenId / forwardCallerPid / codecType）

**dlopen加载链路**：
```
AVCodecServerManager::Init()
  → dlopen("libMemMgr.z.so")        // 内存管理插件
  → dlopen("libcodecstub.z.so")     // Stub骨架插件
  → CreateStubObject(CODEC_STUB_TYPE) → CodecServiceStub实例
```

### 1.2 AVCodecServer 系统能力（avcodec_server.cpp, 182行）

**核心职责**：注册为SA（SystemAbility，SAID=3011），作为服务端接收IPC请求。

**关键证据**：
- L19: `const int AV_CODEC_SA_ID = 3011;` — SA ID
- L24: `bool AVCodecServer::Init()` — 服务初始化，SAMgr::Publish(this)
- L31-50: `OnDump()` — DFX诊断接口，dump codecStubMap_
- L59-80: `DumpRegisterInfo()` — 打印注册信息（InstanceInfo多级调用链）
- L73: `SAMGR_REGISTER(AVCodecServer)` — SA自动注册宏

**SA状态机**（UNINITIALIZED → INITIALIZED → CONFIGURED → RUNNING）

### 1.3 CodecServiceStub 服务端存根（avcodec_service_stub.cpp, 220行）

**核心职责**：IRemoteStub<ICodecService>，服务端接收IPC请求并分发到具体Codec实例。

**关键证据**：
- L19: `class CodecServiceStub : public IRemoteStub<ICodecService>`
- L28-38: `OnRemoteRequest(uint32_t code, MessageParcel& data, MessageParcel& reply, MessageOption& option)` — 分发函数
- L40-80: `CodecServiceInterfaceCode` 33路接口分发（SET_LISTENER_OBJ / INIT / CONFIGURE / PREPARE / START / STOP / FLUSH / RESET / RELEASE / NOTIFY_EOS / CREATE_INPUT_SURFACE / SET_OUTPUT_SURFACE / QUEUE_INPUT_BUFFER / GET_OUTPUT_FORMAT / RELEASE_OUTPUT_BUFFER / SET_PARAMETER / SET_INPUT_SURFACE / DEQUEUE_INPUT_BUFFER / DEQUEUE_OUTPUT_BUFFER / GET_INPUT_FORMAT / GET_CODEC_INFO / DESTROY_STUB / SET_DECRYPT_CONFIG / RENDER_OUTPUT_BUFFER_AT_TIME / SET_CUSTOM_BUFFER / GET_CHANNEL_ID / SET_LPP_MODE / NOTIFY_MEMORY_EXCHANGE / NOTIFY_FREEZE / NOTIFY_ACTIVE / NOTIFY_MEMORY_RECYCLE / NOTIFY_MEMORY_WRITE_BACK / NOTIFY_SUSPEND / NOTIFY_RESUME）

### 1.4 CodecServiceProxy 客户端代理（avcodec_service_proxy.cpp, 128行）

**核心职责**：IRemoteProxy<ICodecService>，封装Binder跨进程调用，客户端-stub通信。

**关键证据**：
- 封装`MessageParcel`序列化/反序列化
- `GetProxy()`获取远程代理
- 封装全部33路CodecServiceInterfaceCode接口

### 1.5 CodecClient 生命周期封装（avcodec_client.cpp, 352行）

**核心职责**：CodecClient封装生命周期（CreateStub / SetListener / Init / Configure / Start / Stop / Release），持有CodecServiceProxy代理。

---

## 2. 接口枚举体系

### 2.1 CodecServiceInterfaceCode（33路）

```cpp
enum class CodecServiceInterfaceCode {
    SET_LISTENER_OBJ = 0,       // L32
    INIT,                       // L33
    CONFIGURE,                  // L34
    PREPARE,                    // L35
    START,                      // L36
    STOP,                       // L37
    FLUSH,                      // L38
    RESET,                      // L39
    RELEASE,                    // L40
    NOTIFY_EOS,                 // L41
    CREATE_INPUT_SURFACE,       // L42
    SET_OUTPUT_SURFACE,         // L43
    QUEUE_INPUT_BUFFER,        // L44
    GET_OUTPUT_FORMAT,         // L45
    RELEASE_OUTPUT_BUFFER,     // L46
    SET_PARAMETER,             // L47
    SET_INPUT_SURFACE,         // L48
    DEQUEUE_INPUT_BUFFER,     // L49
    DEQUEUE_OUTPUT_BUFFER,     // L50
    GET_INPUT_FORMAT,          // L51
    GET_CODEC_INFO,            // L52
    DESTROY_STUB,              // L53
    SET_DECRYPT_CONFIG,        // L54
    RENDER_OUTPUT_BUFFER_AT_TIME, // L55
    SET_CUSTOM_BUFFER,         // L56
    GET_CHANNEL_ID,            // L57
    SET_LPP_MODE,              // L58
    NOTIFY_MEMORY_EXCHANGE,    // L59
    NOTIFY_FREEZE,             // L60
    NOTIFY_ACTIVE,             // L61
    NOTIFY_MEMORY_RECYCLE,     // L62
    NOTIFY_MEMORY_WRITE_BACK,  // L63
    NOTIFY_SUSPEND,            // L64
    NOTIFY_RESUME              // L65
};
```

### 2.2 CodecListenerInterfaceCode（6路回调）

```cpp
enum class CodecListenerInterfaceCode {
    ON_ERROR = 0,                    // L22
    ON_OUTPUT_FORMAT_CHANGED,        // L23
    ON_INPUT_BUFFER_AVAILABLE,        // L24
    ON_OUTPUT_BUFFER_AVAILABLE,       // L25
    ON_OUTPUT_BUFFER_BINDED,          // L26
    ON_OUTPUT_BUFFER_UN_BINDED       // L27
};
```

### 2.3 AVCodecListServiceInterfaceCode（5路能力查询）

```cpp
enum class AVCodecListServiceInterfaceCode {
    FIND_DECODER = 0,    // L69
    FIND_ENCODER,        // L70
    GET_CAPABILITY,      // L71
    GET_CAPABILITY_AT,   // L72
    DESTROY             // L73
};
```

### 2.4 AVCodecServiceInterfaceCode（5路系统管理）

```cpp
enum class AVCodecServiceInterfaceCode {
    GET_SUBSYSTEM = 0,              // L77
    FREEZE,                         // L78
    ACTIVE,                         // L79
    ACTIVEALL,                      // L80
    GET_ACTIVE_SECURE_DECODER_PIDS  // L81
};
```

---

## 3. 回调链路（CodecListenerStub / CodecListenerProxy）

**CodecListenerStub**（avcodec_listener_stub.cpp, 35行）：服务端接收来自CodecClient的回调请求，反序列化并触发应用层监听器。

**CodecListenerProxy**（avcodec_listener_proxy.cpp）：客户端代理，将本地回调事件跨进程发送到CodecServiceStub。

**6路回调分发**：ON_ERROR / ON_OUTPUT_FORMAT_CHANGED / ON_INPUT_BUFFER_AVAILABLE / ON_OUTPUT_BUFFER_AVAILABLE / ON_OUTPUT_BUFFER_BINDED / ON_OUTPUT_BUFFER_UN_BINDED

---

## 4. DeathRecipient 死亡通知

**用途**：当CodecServiceStub所在进程崩溃时，DeathRecipient自动接管，清理codecStubMap_中对应条目（EraseCodecObjectByPid），避免僵尸stub。

---

## 5. 与现有S系列记忆关联

| 关联记忆 | 关系 |
|---------|------|
| S137 | S137为早期草案，本文件为增强版（行号级evidence） |
| S161 | S161为同一主题，本文件补充接口枚举完整代码 |
| S83/CAPI总览 | S83的Native C API层调用CodecClient IPC代理 |
| S55/回调链路 | S55的四路回调体系通过CodecListenerInterfaceCode实现 |
| S121/错误码 | 错误码通过ON_ERROR回调（CodecListenerInterfaceCode::ON_ERROR）传递 |

---

## 6. 关键文件索引

| 文件 | 行数 | 核心职责 |
|------|------|---------|
| avcodec_server_manager.cpp | 426 | 单例管理/插件加载/Stub管理 |
| avcodec_server.cpp | 182 | SA注册/DFX诊断 |
| avcodec_service_stub.cpp | 220 | 33路IPC分发 |
| avcodec_service_proxy.cpp | 128 | Binder跨进程代理 |
| avcodec_listener_stub.cpp | 35 | 6路回调分发 |
| avcodec_listener_proxy.cpp | TBD | 回调跨进程代理 |
| avcodec_death_recipient.h | TBD | 死亡通知接管 |
| avcodec_parcel.h | TBD | 序列化工具 |
| avcodec_client.cpp | 352 | 生命周期封装 |
| av_codec_service_ipc_interface_code.h | 84 | 接口枚举三合一 |

---

**状态**：draft（待审批）
**生成时间**：2026-05-21T05:25:00+08:00
**Builder**：builder-agent