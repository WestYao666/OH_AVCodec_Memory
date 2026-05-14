---
type: architecture
id: MEM-ARCH-AVCODEC-S137
status: pending_approval
topic: SA Codec 服务框架——AVCodecServerManager + CodecClient IPC 双层架构与 SystemAbility 集成
scope: [AVCodec, SA, SystemAbility, IPC, CodecClient, CodecServiceStub, CodecServiceProxy, Singleton, SAMgr, dlopen]
created_at: "2026-05-15T01:10:00+08:00"
updated_at: "2026-05-15T01:10:00+08:00"
source_repo: /home/west/av_codec_repo
source_root: services/services/sa_avcodec
related_mem_ids: [S83, S95, S121, S94]
---

# MEM-ARCH-AVCODEC-S137: SA Codec 服务框架——AVCodecServerManager + CodecClient IPC 双层架构与 SystemAbility 集成

## 摘要

SA Codec 服务框架是 OpenHarmony AVCodec 模块的进程级基础设施层，建立在 SystemAbility（SA）框架之上，提供服务注册、实例管理、IPC 通信三大核心能力。AVCodecServerManager（单例）负责在服务端创建和管理 CodecServiceStub/CodecListServiceStub，CodecClient（客户端 IPC 代理）负责通过 CodecServiceProxy 发起跨进程调用，二者共同构成 AVCodec 的 RPC 通信骨架。本条目补充 S83（CAPI 总览）、S95（AudioCodec CAPI）、S121（错误码体系）的进程间通信底层视图。

---

## 1. 文件矩阵与行号级证据

### 1.1 服务端（SA 进程）

| 文件 | 行数 | 职责 |
|------|------|------|
| `sa_avcodec/server/avcodec_server_manager.cpp` | 426 | AVCodecServerManager 单例，服务注册与实例管理 |
| `sa_avcodec/server/avcodec_server_manager.h` | — | 类定义（GetInstance/CreateStubObject/DestroyStubObject） |
| `sa_avcodec/server/avcodec_server.cpp` | 182 | SA 服务入口，OnDump/OnGetXmlWhiteList 等回调 |
| `sa_avcodec/server/avcodec_server_dump.cpp` | — | Dump 能力实现 |
| `sa_avcodec/ipc/avcodec_service_stub.cpp` | 220 | CodecServiceStub 服务端 IPC 接收侧 |
| `sa_avcodec/ipc/avcodec_service_stub.h` | — | Stub 接口定义（CodecService 接口） |
| `sa_avcodec/ipc/avcodec_service_proxy.cpp` | 128 | CodecServiceProxy 服务端 IPC 发送侧（Stub → Proxy 镜像） |

### 1.2 客户端（沙箱进程）

| 文件 | 行数 | 职责 |
|------|------|------|
| `sa_avcodec/client/avcodec_client.cpp` | 352 | CodecClient IPC 客户端代理，CreateStub/InvokeFunc |
| `sa_avcodec/client/avcodec_client.h` | — | CodecClient 类定义 |

### 1.3 接口定义

| 文件 | 行数 | 职责 |
|------|------|------|
| `sa_avcodec/ipc/i_standard_avcodec_service.h` | — | IStandardAVCodecService 接口声明（IRemoteBroker 子类） |
| `sa_avcodec/ipc/i_standard_avcodec_listener.h` | — | 服务端回调接口（OnCodecServerDied） |
| `sa_avcodec/ipc/av_codec_service_ipc_interface_code.h` | — | IPC 方法编号枚举（COMMAND_*） |

**总计：约 1300+ 行核心代码**

---

## 2. AVCodecServerManager 单例架构

### 2.1 GetInstance 单例模式

**源码**：`avcodec_server_manager.cpp:42-45`

```cpp
AVCodecServerManager& AVCodecServerManager::GetInstance()
{
    static AVCodecServerManager instance;
    return instance;
}
```

- 标准的局部静态变量单例（线程安全 C++11）
- 服务进程启动时即初始化

### 2.2 Init：dlopen 加载 libMemMgr

**源码**：`avcodec_server_manager.cpp:60-73`

```cpp
void AVCodecServerManager::Init()
{
    void *handle = dlopen(LIB_PATH, RTLD_NOW);
    CHECK_AND_RETURN_LOG(handle != nullptr, "Load so failed:%{public}s", LIB_PATH);
    libMemMgrClientHandle_ = std::shared_ptr<void>(handle, dlclose);
    notifyProcessStatusFunc_ = reinterpret_cast<NotifyProcessStatusFunc>(
        dlsym(handle, NOTIFY_STATUS_FUNC_NAME));
    setCriticalFunc_ = reinterpret_cast<SetCriticalFunc>(
        dlsym(handle, SET_CRITICAL_FUNC_NAME));
}
```

- 通过 dlopen 动态加载 libMemMgr（内存管理客户端库）
- 获取 `notifyProcessStatusFunc_` / `setCriticalFunc_` 两个关键函数指针
- 用于进程状态上报（给 SDF 生命周期管理）

### 2.3 CreateStubObject：双 Stub 类型工厂

**源码**：`avcodec_server_manager.cpp:74-90`

```cpp
int32_t AVCodecServerManager::CreateStubObject(StubType type, sptr<IRemoteObject> &object)
{
    std::lock_guard<std::shared_mutex> lock(mutex_);
    switch (type) {
        case CODECLIST: {
            return CreateCodecListStubObject(object);
        }
        case CODEC: {
            return CreateCodecStubObject(object);
        }
        default:
            return AVCS_ERR_INVALID_OPERATION;
    }
}
```

- CODECLIST → CodecListServiceStub（能力查询服务）
- CODEC → CodecServiceStub（实际编解码操作）

### 2.4 CreateCodecStubObject：实例创建与注册

**源码**：`avcodec_server_manager.cpp:112-135`

```cpp
int32_t AVCodecServerManager::CreateCodecStubObject(sptr<IRemoteObject> &object)
{
    static std::atomic<int32_t> instanceId = 0;
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
}
```

- 原子自增 instanceId（最大 INT32_MAX 后回绕）
- codecStubMap_：`std::map<pid_t, std::pair<sptr<IRemoteObject>, InstanceInfo>>`
- 记录 caller/forwardCaller（多级调用链追踪）

### 2.5 EraseCodecObjectByPid：实例销毁与事件上报

**源码**：`avcodec_server_manager.cpp:195-206`

```cpp
void AVCodecServerManager::EraseCodecObjectByPid(pid_t pid)
{
    for (auto it = codecStubMap_.begin(); it != codecStubMap_.end();) {
        if (it->first == pid) {
            EventManager::GetInstance().OnInstanceEvent(
                StatisticsEventType::APP_BEHAVIORS_RELEASE_HDEC_INFO);
            it = codecStubMap_.erase(it);
        } else {
            ++it;
        }
    }
    if (codecStubMap_.size() == 0) { ... }
}
```

- 进程退出时按 pid 批量清理
- 触发 `APP_BEHAVIORS_RELEASE_HDEC_INFO` 统计事件

---

## 3. IPC 层架构

### 3.1 CodecServiceStub 服务端接收侧

**源码**：`avcodec_service_stub.cpp`

- 继承 `ICodecService`（定义在 `i_standard_avcodec_service.h`）
- 重写 `OnRemoteRequest` 处理 IPC 请求
- 调用实际的 CodecServer（codec_server.cpp）处理业务

### 3.2 CodecServiceProxy 服务端发送侧（Stub 的镜像）

**源码**：`avcodec_service_proxy.cpp:128 行`

- 实现 `IStandardAVCodecService` 接口
- 作为 Stub 的对端，序列化参数并通过 IPC 框架发送

### 3.3 avcodec_service_proxy.h 接口方法（部分）：

```cpp
// 方法列表（由 av_codec_service_ipc_interface_code.h 定义 COMMAND_* 编号）
// CODEC_CREATE: Create(param) → instanceId
// CODEC_CONFIGURE: Configure(instanceId, param)
// CODEC_START/STOP/FLUSH/RESET
// CODEC_GETOUTPUTDESCRIPTION
// CODEC_PUSHINPUTBUFFER/RENDEROUTPUTBUFFER
// CODEC_DESTROY
```

### 3.4 avcodec_client.cpp 客户端代理

**源码**：`avcodec_client.cpp:352 行`

```cpp
class CodecClient : public ICodecService,
                   public IRemoteProxy<IStandardAVCodecService> {
    // 通过 CodecServiceProxy 发起跨进程调用
    // 持有 codecStubMap_ 中 object 的引用
}
```

- 客户端持有 `sptr<IRemoteObject>`（即 CodecServiceStub 的代理）
- 通过 `IPCInvoker` 调用远程方法

---

## 4. SystemAbility 集成

### 4.1 服务注册与 SA 框架

**源码**：`avcodec_server.cpp`

- AVCodecServerManager 通过 SA 框架的 `SystemAbility` 机制注册
- SA ID 定义在 `system_ability_definition.h`（跨模块常量）

### 4.2 OnGetXmlWhiteList / OnDump

**源码**：`avcodec_server.cpp:182 行`

```cpp
int32_t AVCodecServer::OnGetXmlWhiteList(std::string& profile) { ... }
int32_t AVCodecServer::OnDump(int fd, const std::vector<std::string>& args) { ... }
```

- `OnGetXmlWhiteList`：返回支持的能力列表 XML
- `OnDump`：支持 `hdc shell avcodec dump` 调试

### 4.3 进程状态上报

**源码**：`avcodec_server_manager.cpp:276`

```cpp
int32_t ret = notifyProcessStatusFunc_(pid_, 1, status, AV_CODEC_SERVICE_ID);
```

- 通过 dlopen 获取的 `notifyProcessStatusFunc_` 向 SDF 上报进程状态
- `status = 1` 表示 codec service 就绪

---

## 5. 实例生命周期与多进程支持

### 5.1 codecStubMap_ 结构

```cpp
std::map<pid_t, std::pair<sptr<IRemoteObject>, InstanceInfo>> codecStubMap_;
```

- key：client process id
- value：Stub 代理 + 元信息（创建时间/调用者链/forwardCaller）

### 5.2 InstanceInfo 结构

**源码**：`avcodec_server_manager.cpp:232`

```cpp
typedef struct CodecCallerInfo {
    pid_t pid;
    uint64_t tokenId;
} CodecCallerInfo;

typedef struct InstanceInfo {
    int32_t instanceId;
    time_t codecCreateTime;
    CodecCallerInfo caller;
    CodecCallerInfo forwardCaller;
} InstanceInfo;
```

- 支持多级调用链（caller → forwardCaller）
- 用于 DFX 溯源和安全审计

### 5.3 GetInstanceInfoListByPid / GetCodecInstanceByInstanceId

**源码**：`avcodec_server_manager.cpp:316-361`

```cpp
std::vector<CodecInstance> GetInstanceInfoListByPid(pid_t pid);
std::optional<InstanceInfo> GetInstanceInfoByInstanceId(int32_t instanceId);
std::optional<CodecInstance> GetCodecInstanceByInstanceId(int32_t instanceId);
```

- 按进程或按 instanceId 查询实例信息
- 用于 HiDumper 查询 / DFX 统计

---

## 6. 与相关记忆条目的关系

| 记忆 | 关系 |
|------|------|
| S83（CAPI 总览） | S83 描述 OH_AVCodec CAPI 外观，S137 补充其底层 IPC 实现 |
| S95（AudioCodec CAPI） | AudioCodec CAPI 通过 CodecClient 走 S137 IPC 框架 |
| S121（错误码体系） | AVCS_ERR_* 错误码在 SA IPC 层传递，IPC 特有错误（CREATE_STUB_FAILED）属于 S137 范围 |
| S94（CAPI 三件套） | OH_AVSource/Demuxer/Muxer 的 IPC 调用同样经过 CodecServiceStub |

---

## 7. 关键行号速查

| 功能 | 文件:行号 |
|------|----------|
| GetInstance 单例 | avcodec_server_manager.cpp:42 |
| Init dlopen | avcodec_server_manager.cpp:60 |
| CreateStubObject | avcodec_server_manager.cpp:74 |
| CreateCodecStubObject | avcodec_server_manager.cpp:112 |
| EraseCodecObjectByPid | avcodec_server_manager.cpp:195 |
| InstanceInfo struct | avcodec_server_manager.cpp:232 |
| CodecStubMap_ | avcodec_server_manager.cpp:112+132 |
| notifyProcessStatusFunc_ 调用 | avcodec_server_manager.cpp:276 |
| setCriticalFunc_ 调用 | avcodec_server_manager.cpp:304 |

---

## 8. 版本与日期

- 创建：2026-05-15
- Builder：subagent builder-agent
- 状态：draft → pending_approval