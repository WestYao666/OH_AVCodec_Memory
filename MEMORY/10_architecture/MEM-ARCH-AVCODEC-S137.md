---
type: architecture
id: MEM-ARCH-AVCODEC-S137
status: pending_approval
topic: SA Codec 服务框架——AVCodecServerManager + CodecClient IPC 双层架构与 SystemAbility 集成
scope: [AVCodec, SA, SystemAbility, IPC, CodecClient, CodecServiceStub, CodecServiceProxy, Singleton, SAMgr, dlopen]
created_at: "2026-05-15T01:10:00+08:00"
updated_at: "2026-05-21T12:25:00+08:00"
source_repo: /home/west/av_codec_repo
source_root: services/services/sa_avcodec
related_mem_ids: [S83, S95, S121, S94, S161]
---

# MEM-ARCH-AVCODEC-S137: SA Codec 服务框架——AVCodecServerManager + CodecClient IPC 双层架构与 SystemAbility 集成

## 摘要

SA Codec 服务框架是 OpenHarmony AVCodec 模块的进程级基础设施层，建立在 SystemAbility（SA）框架之上，提供服务注册、实例管理、IPC 通信三大核心能力。AVCodecServerManager（单例）负责在服务端创建和管理 CodecServiceStub/CodecListServiceStub，CodecClient（客户端 IPC 代理）负责通过 CodecServiceProxy 发起跨进程调用，二者共同构成 AVCodec 的 RPC 通信骨架。本条目补充 S83（CAPI 总览）、S95（AudioCodec CAPI）、S121（错误码体系）的进程间通信底层视图。

> **Builder 备注（2026-05-21）**：草案已存在（2026-05-15T01:10），本轮增强行号级 evidence，补充 S161 接口枚举体系，验证本地镜像源码。

---

## 1. 文件矩阵与行号级证据

### 1.1 服务端（SA 进程：`services/services/sa_avcodec`）

| 文件 | 行数 | 职责 |
|------|------|------|
| `server/avcodec_server_manager.cpp` | 426 | AVCodecServerManager 单例，服务注册与实例管理 |
| `server/include/avcodec_server_manager.h` | ~130 | 类定义（GetInstance/CreateStubObject/DestroyStubObject） |
| `server/avcodec_server.cpp` | 182 | SA 服务入口，OnDump/OnGetXmlWhiteList 等回调 |
| `server/avcodec_server_dump.cpp` | — | Dump 能力实现 |
| `ipc/avcodec_service_stub.cpp` | 220 | CodecServiceStub 服务端 IPC 接收侧 |
| `ipc/avcodec_service_proxy.cpp` | 128 | CodecServiceProxy 服务端 IPC 发送侧（Stub 的镜像） |
| `ipc/av_codec_service_ipc_interface_code.h` | 84 | IPC 方法编号枚举（CodecListener/CodecService/AVCodecList/AVCodecService 四组） |
| `ipc/avcodec_listener_stub.cpp` | 35 | 服务端回调接收侧（6路回调分发） |
| `ipc/avcodec_death_recipient.h` | 48 | 死亡通知代理（OnCodecServerDied） |
| `ipc/avcodec_parcel.cpp` | 36 | Parcel 序列化工具 |

### 1.2 客户端（沙箱进程）

| 文件 | 行数 | 职责 |
|------|------|------|
| `client/avcodec_client.cpp` | 352 | AVCodecClient 全局单例，CodecServiceProxy 代理创建与自动重连 |

### 1.3 公共数据结构

| 文件 | 行数 | 职责 |
|------|------|------|
| `services/common/instance_info.h` | — | InstanceInfo / CallerInfo / VideoCodecType 定义 |

**总计：约 1900+ 行核心代码**

---

## 2. AVCodecServerManager 单例架构

### 2.1 GetInstance 单例模式

**源码**：`server/avcodec_server_manager.cpp:42`

```cpp
AVCodecServerManager& AVCodecServerManager::GetInstance()
{
    static AVCodecServerManager instance;
    return instance;
}
```

- 局部静态变量单例（线程安全 C++11）
- 服务进程启动时即初始化

### 2.2 Init：dlopen 加载 libmemmgrclient.z.so

**源码**：`server/avcodec_server_manager.cpp:62-69`

```cpp
void *handle = dlopen(LIB_PATH, RTLD_NOW); // LIB_PATH = "libmemmgrclient.z.so"
CHECK_AND_RETURN_LOG(handle != nullptr, "Load so failed:%{public}s", LIB_PATH);
libMemMgrClientHandle_ = std::shared_ptr<void>(handle, dlclose);
notifyProcessStatusFunc_ = reinterpret_cast<NotifyProcessStatusFunc>(dlsym(handle, NOTIFY_STATUS_FUNC_NAME));
// NOTIFY_STATUS_FUNC_NAME = "notify_process_status"
// SET_CRITICAL_FUNC_NAME = "set_critical"
setCriticalFunc_ = reinterpret_cast<SetCriticalFunc>(dlsym(handle, SET_CRITICAL_FUNC_NAME));
```

- dlopen 动态加载 libmemmgrclient.z.so（内存管理客户端库）
- 获取 `notifyProcessStatusFunc_` / `setCriticalFunc_` 两个函数指针
- shared_ptr 自动 dlclose（引用计数生命周期）

### 2.3 CreateStubObject：双 Stub 类型工厂

**源码**：`server/avcodec_server_manager.cpp:74-90`

```cpp
int32_t AVCodecServerManager::CreateStubObject(StubType type, sptr<IRemoteObject> &object)
{
    std::lock_guard<std::shared_mutex> lock(mutex_);
    switch (type) {
        case CODECLIST: { return CreateCodecListStubObject(object); }
        case CODEC:     { return CreateCodecStubObject(object); }
        default:        { return AVCS_ERR_INVALID_OPERATION; }
    }
}
```

- CODECLIST → CodecListServiceStub（能力查询服务，SA ID 3002）
- CODEC → CodecServiceStub（实际编解码操作，SA ID 3011）

### 2.4 CreateCodecStubObject：实例创建与注册

**源码**：`server/avcodec_server_manager.cpp:112-135`

```cpp
sptr<CodecServiceStub> stub = CodecServiceStub::Create(instanceId);
pid_t pid = IPCSkeleton::GetCallingPid();
InstanceInfo instanceInfo = {
    .instanceId = instanceId,
    .codecCreateTime = std::chrono::system_clock::to_time_t(std::chrono::system_clock::now()),
    .caller = {pid, IPCSkeleton::GetCallingTokenID()},
    .forwardCaller = {INVALID_PID, INVALID_TOKEN},
};
instanceId++;
codecStubMap_.emplace(pid, std::make_pair(object, instanceInfo));
```

- 原子自增 instanceId（最大 INT32_MAX 后回绕）
- `codecStubMap_`：`std::unordered_multimap<pid_t, CodecInstance>`（同一 PID 可对应多实例）
- 记录 caller/forwardCaller（多级调用链追踪）

### 2.5 EraseCodecObjectByPid：实例销毁与事件上报

**源码**：`server/avcodec_server_manager.cpp:195-206`

```cpp
void AVCodecServerManager::EraseCodecObjectByPid(pid_t pid)
{
    for (auto it = codecStubMap_.begin(); it != codecStubMap_.end();) {
        if (it->first == pid) {
            EventManager::GetInstance().OnInstanceEvent(
                StatisticsEventType::APP_BEHAVIORS_RELEASE_HDEC_INFO);
            it = codecStubMap_.erase(it);
        } else { ++it; }
    }
}
```

- 进程退出时按 pid 批量清理
- 触发 `APP_BEHAVIORS_RELEASE_HDEC_INFO` 统计事件

### 2.6 GetActiveSecureDecoderPids：安全解码器进程查询

**源码**：`server/avcodec_server_manager.h`

```cpp
std::vector<pid_t> GetActiveSecureDecoderPids();
```

- 查询所有活跃安全解码器进程（用于 DRM 权限校验）

---

## 3. IPC 层架构

### 3.1 四组接口枚举（接口编号体系）

**源码**：`ipc/av_codec_service_ipc_interface_code.h:84 行`

```cpp
enum class CodecListenerInterfaceCode {
    ON_ERROR = 0, ON_OUTPUT_FORMAT_CHANGED,
    ON_INPUT_BUFFER_AVAILABLE, ON_OUTPUT_BUFFER_AVAILABLE,
    ON_OUTPUT_BUFFER_BINDED, ON_OUTPUT_BUFFER_UN_BINDED
};  // 6 路回调

enum class CodecServiceInterfaceCode {
    SET_LISTENER_OBJ = 0, INIT, CONFIGURE, PREPARE, START, STOP, FLUSH, RESET, RELEASE,
    NOTIFY_EOS, CREATE_INPUT_SURFACE, SET_OUTPUT_SURFACE, QUEUE_INPUT_BUFFER,
    GET_OUTPUT_FORMAT, RELEASE_OUTPUT_BUFFER, SET_PARAMETER, SET_INPUT_SURFACE,
    DEQUEUE_INPUT_BUFFER, DEQUEUE_OUTPUT_BUFFER, GET_INPUT_FORMAT, GET_CODEC_INFO,
    DESTROY_STUB, SET_DECRYPT_CONFIG, RENDER_OUTPUT_BUFFER_AT_TIME, SET_CUSTOM_BUFFER,
    GET_CHANNEL_ID, SET_LPP_MODE, NOTIFY_MEMORY_EXCHANGE, NOTIFY_FREEZE, NOTIFY_ACTIVE,
    NOTIFY_MEMORY_RECYCLE, NOTIFY_MEMORY_WRITE_BACK, NOTIFY_SUSPEND, NOTIFY_RESUME
};  // 33 路接口

enum class AVCodecListServiceInterfaceCode {
    FIND_DECODER = 0, FIND_ENCODER, GET_CAPABILITY, GET_CAPABILITY_AT, DESTROY
};  // 5 路

enum class AVCodecServiceInterfaceCode {
    GET_SUBSYSTEM = 0, FREEZE, ACTIVE, ACTIVEALL, GET_ACTIVE_SECURE_DECODER_PIDS
};  // 5 路（SA 级管理接口）
```

- CodecServiceInterfaceCode 33 路 + CodecListenerInterfaceCode 6 路 = 39 个 IPC 接口
- 所有接口均通过 Binder 驱动 OnRemoteRequest 分发

### 3.2 CodecServiceStub 服务端接收侧

**源码**：`ipc/avcodec_service_stub.cpp:220 行`

- 继承 `ICodecService`（定义在 `i_standard_avcodec_service.h`）
- 重写 `OnRemoteRequest` 处理 IPC 请求
- 根据 CodecServiceInterfaceCode 编号路由到实际 CodecServer 方法

### 3.3 CodecServiceProxy 服务端发送侧（Stub 的镜像）

**源码**：`ipc/avcodec_service_proxy.cpp:128 行`

- 实现 `IStandardAVCodecService` 接口
- 作为 Stub 的对端，序列化参数并通过 IPC 框架发送

### 3.4 avcodec_listener_stub.cpp 回调分发

**源码**：`ipc/avcodec_listener_stub.cpp:35 行`

- 实现 CodecListenerInterfaceCode 6 路回调分发
- 服务端向客户端推送 ON_ERROR / ON_OUTPUT_FORMAT_CHANGED 等事件

### 3.5 avcodec_death_recipient.h 死亡通知

**源码**：`ipc/avcodec_death_recipient.h:48 行`

```cpp
class AvcodecDeathRecipient : public IRemoteObject::DeathRecipient {
    void OnRemoteDied(const wptr<IRemoteObject>& remote) override;
    // CodecServer 死亡时自动清理 client 端代理并触发重连
};
```

### 3.6 CodecClient 客户端代理

**源码**：`client/avcodec_client.cpp:352 行`

```cpp
class AVCodecClient : public IAVCodecService, public IRemoteProxy<IStandardAVCodecService> {
    static AVCodecClient g_avCodecClientInstance;
    sptr<IStandardAVCodecService> avCodecProxy_;
    bool IsAlived();
    int32_t CreateInstanceAndTryInTimes(AVCodecSystemAbility subSystemId,
        sptr<IRemoteObject>& object, uint32_t tryTimes);
    // GetSubSystemAbility(subSystemId, listenerStub_->AsObject(), object)
    // 自动重连机制：IsAlived 检测 → 100ms 重试
};
```

- AVCodecClient 全局单例（g_avCodecClientInstance）
- 通过 `IServiceRegistry::GetInstance()->GetSystemAbilityManager()` 获取 SA 代理
- listenerStub_ 持有回调对象，传入 GetSubSystemAbility 注册客户端监听

---

## 4. SystemAbility 集成

### 4.1 服务注册与 SA 框架

**源码**：`server/avcodec_server.cpp:182 行`

- AVCodecServerManager 通过 SA 框架的 SystemAbility 机制注册
- SA ID：3011（CODEC）/ 3002（CODECLIST）
- OnGetXmlWhiteList / OnDump 支持 hdc shell 调试

### 4.2 进程状态上报

**源码**：`server/avcodec_server_manager.cpp:275-276`

```cpp
CHECK_AND_RETURN_LOG(notifyProcessStatusFunc_ != nullptr, ...);
int32_t ret = notifyProcessStatusFunc_(pid_, 1, status, AV_CODEC_SERVICE_ID);
```

- 通过 dlopen 获取的 `notifyProcessStatusFunc_` 向 SDF 上报进程状态
- `status = 1` 表示 codec service 就绪

### 4.3 关键服务标记

**源码**：`server/avcodec_server_manager.cpp:303-304`

```cpp
int32_t ret = setCriticalFunc_(pid_, isKeyService, AV_CODEC_SERVICE_ID);
```

- setCriticalFunc_ 将进程标记为关键服务（系统级联崩溃保护）

---

## 5. 实例生命周期与多进程支持

### 5.1 codecStubMap_ 结构

```cpp
std::unordered_multimap<pid_t, CodecInstance> codecStubMap_;
// key: client process id
// value: CodecInstance = std::pair<sptr<IRemoteObject>, InstanceInfo>
```

- 同一 PID 可对应多个 codec 实例（多路解码同时运行）
- 用 unordered_multimap 而非 map 支持批量删除

### 5.2 InstanceInfo 结构

**源码**：`services/common/instance_info.h`

```cpp
struct CallerInfo {
    pid_t pid = -1;
    uid_t uid = 0;
    std::string processName = "";
};

struct InstanceInfo {
    InstanceId instanceId = INVALID_INSTANCE_ID;
    CallerInfo caller;       // 直接调用方
    CallerInfo forwardCaller; // 转发调用方（如跨进程桥接）
    AVCodecType codecType;
    uint32_t memoryUsage = 0;
    std::string codecName = "";
    std::time_t codecCreateTime = 0;
    VideoCodecType videoCodecType = VideoCodecType::UNKNOWN;
};
```

- 支持多级调用链（caller → forwardCaller）
- GetActualCallerPid() 优先取 forwardCaller（跨进程桥接场景）

### 5.3 Query 接口

**源码**：`server/avcodec_server_manager.cpp:316-382`

```cpp
std::vector<CodecInstance> GetInstanceInfoListByPid(pid_t pid);
std::vector<CodecInstance> GetInstanceInfoListByActualPid(pid_t pid);
std::optional<InstanceInfo> GetInstanceInfoByInstanceId(int32_t instanceId);
std::unordered_map<std::string, uint32_t> GetHDecUsageStatistics();
```

- 按进程或按 instanceId 查询实例信息
- GetHDecUsageStatistics() 用于 DFX 统计硬件解码器使用率

---

## 6. 与相关记忆条目的关系

| 记忆 | 关系 |
|------|------|
| S83（CAPI 总览） | S83 描述 OH_AVCodec CAPI 外观，S137 补充其底层 IPC 实现 |
| S95（AudioCodec CAPI） | AudioCodec CAPI 通过 CodecClient 走 S137 IPC 框架 |
| S121（错误码体系） | AVCS_ERR_* 错误码在 SA IPC 层传递，IPC 特有错误（CREATE_STUB_FAILED）属于 S137 范围 |
| S94（CAPI 三件套） | OH_AVSource/Demuxer/Muxer 的 IPC 调用同样经过 CodecServiceStub |
| S161（SA IPC 五层架构） | S161 是 S137 的增强版，补充完整的六文件行号级 evidence 与接口枚举体系 |

---

## 7. 关键行号速查

| 功能 | 文件:行号 |
|------|----------|
| GetInstance 单例 | avcodec_server_manager.cpp:42 |
| dlopen libmemmgrclient.z.so | avcodec_server_manager.cpp:62 |
| NOTIFY_STATUS_FUNC_NAME = "notify_process_status" | avcodec_server_manager.cpp:68 |
| CreateStubObject 双分发 | avcodec_server_manager.cpp:74 |
| CreateCodecStubObject 实例创建 | avcodec_server_manager.cpp:112 |
| EraseCodecObjectByPid | avcodec_server_manager.cpp:195 |
| InstanceInfo struct | services/common/instance_info.h:43 |
| codecStubMap_ 类型 | avcodec_server_manager.h（unordered_multimap） |
| notifyProcessStatusFunc_ 调用 | avcodec_server_manager.cpp:276 |
| setCriticalFunc_ 调用 | avcodec_server_manager.cpp:304 |
| CodecServiceInterfaceCode 33路 | av_codec_service_ipc_interface_code.h:31 |
| CodecListenerInterfaceCode 6路 | av_codec_service_ipc_interface_code.h:22 |
| AVCodecClient 全局单例 | avcodec_client.cpp:38-41 |
| IsAlived 自动重连 | avcodec_client.cpp:50 |
| AvcodecDeathRecipient 死亡通知 | avcodec_death_recipient.h:48 |

---

## 8. 版本与日期

- 创建：2026-05-15
- Builder：subagent builder-agent
- 状态：pending_approval
- 本次增强：2026-05-21（补充行号 evidence、S161 接口枚举体系、InstanceInfo 完整结构、额外 IPC 文件）