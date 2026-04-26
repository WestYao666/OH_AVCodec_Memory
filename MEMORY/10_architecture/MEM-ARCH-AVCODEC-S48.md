---
type: architecture
id: MEM-ARCH-AVCODEC-S48
title: "CodecServer 生命周期管理——CodecServer/CodecBase/AVCodecServerManager 三层架构与七状态机"
scope: [AVCodec, CodecServer, CodecBase, AVCodecServerManager, SystemAbility, SA, Lifecycle, StateMachine, ICodecService, CodecFactory, IPC, PostProcessing, TemporalScalability]
status: draft
created_by: builder-agent
created_at: "2026-04-26T03:55:00+08:00"
evidence_count: 14
关联主题: [S3(CodecServer Pipeline数据流), S19(TemporalScalability), S20(PostProcessing), S21(AVCodec IPC), S39(AVCodecVideoDecoder), S42(AVCodecVideoEncoder)]
---

# MEM-ARCH-AVCODEC-S48: CodecServer 生命周期管理——三层架构与七状态机

## Metadata

| 字段 | 值 |
|------|-----|
| **ID** | MEM-ARCH-AVCODEC-S48 |
| **标题** | CodecServer 生命周期管理——CodecServer/CodecBase/AVCodecServerManager 三层架构与七状态机 |
| **Scope** | AVCodec, CodecServer, CodecBase, AVCodecServerManager, SystemAbility, SA, Lifecycle, StateMachine, ICodecService, CodecFactory, IPC, PostProcessing, TemporalScalability |
| **Status** | draft |
| **Created** | 2026-04-26T03:55:00+08:00 |
| **Evidence Count** | 14 |
| **关联主题** | S3(Pipeline数据流), S19(TemporalScalability), S20(PostProcessing), S21(AVCodec IPC), S39(VideoDecoder), S42(VideoEncoder) |

---

## 架构正文

### 1. 三层架构总览

CodecServer 的生命周期管理涉及三层：

| 层次 | 组件 | 职责 | 所在进程 |
|------|------|------|---------|
| **L1** | `AVCodecServer` | SystemAbility (SA) 入口，进程生命周期 | codecserver 进程（SA_MANAGER） |
| **L2** | `AVCodecServerManager` | 实例池管理，IPC 对象创建/销毁，进程状态通知 | codecserver 进程 |
| **L3** | `CodecServer` | 单个 Codec 实例生命周期，七状态机 | codecserver 进程 |
| **L3.5** | `CodecBase` | 底层编解码引擎插件 | codecserver 进程 |
| **L4** | `CodecFactory` | CodecBase 创建工厂 | codecserver 进程 |

**关键类继承链：**
```cpp
CodecServer
  : public ICodecService       // 43个虚函数接口
  : public std::enable_shared_from_this<CodecServer>

CodecBaseCallback
  : public MediaCodecCallback  // 回调桥接 CodecBase → CodecServer
```

---

### 2. L1 — AVCodecServer (SystemAbility)

**定义文件：** `services/services/sa_avcodec/server/avcodec_server.cpp`

**SA 注册：**
```cpp
REGISTER_SYSTEM_ABILITY_BY_ID(AVCodecServer, AV_CODEC_SERVICE_ID, true)
// 参数3=true: runOnCreate = false（延迟启动，按需加载）
```

**SA 生命周期钩子：**

| 钩子 | 触发时机 | 关键行为 |
|------|---------|---------|
| `OnStart()` | SA 首次被请求时 | `Publish(this)` 发布到 SAMgr；`SetMaxWorkThreadNum(64)`；监听 MEMORY_MANAGER_SA_ID |
| `OnIdle()` | SA 空闲时 | 检查 `AVCodecServerManager::GetInstanceCount() == 0`，否则拒绝进入空闲态 |
| `OnStop()` | 所有实例释放后 | `NotifyProcessStatus(0)` 通知内存管理器 |

**延迟加载机制：**
- `runOnCreate = false`：SA 进程不在系统启动时立即加载，而是第一次被客户端请求时（通过 `GetSystemAbility(AV_CODEC_SERVICE_ID)`）才启动
- 进程最大 IPC 线程数：64

---

### 3. L2 — AVCodecServerManager (实例池管理)

**定义文件：** `services/services/sa_avcodec/server/include/avcodec_server_manager.h`

**单例模式：**
```cpp
static AVCodecServerManager& GetInstance();  // 线程安全单例
```

**核心能力：**

| 方法 | 说明 |
|------|------|
| `CreateStubObject(StubType, object)` | 创建 CodecListStub 或 CodecStub 的 IPC 对象 |
| `DestroyStubObject(StubType, object)` | 销毁指定 Stub 对象 |
| `DestroyStubObjectForPid(pid)` | 进程退出时清理该进程所有实例 |
| `GetInstanceCount()` | 获取当前活跃实例数（供 OnIdle 判断） |
| `GetInstanceInfoByInstanceId(id)` | 按实例ID查询 InstanceInfo |
| `GetHDecUsageStatistics()` | 获取硬件解码器使用统计（多进程共享） |
| `SetInstanceInfoByInstanceId(id, info)` | 更新实例的 InstanceInfo（uid/pid/bundleName） |
| `GetActiveSecureDecoderPids()` | 获取活跃的安全解码器进程列表 |

**StubType 枚举：**
```cpp
enum StubType { CODECLIST, CODEC };
// CODECLIST: CodecList 服务（能力查询，SA 独立）
// CODEC: Codec 服务（实例管理，按需创建）
```

**进程内存管理集成：**
```cpp
// libmemmgrclient.z.so 动态加载
static constexpr char LIB_PATH[] = "libmemmgrclient.z.so";
int32_t NotifyProcessStatus(int32_t pid, int32_t type, int32_t status, int32_t saId);
int32_t SetCritical(bool isCritical, int32_t saId);
// 当关键服务（如安全解码器）运行时，调用 SetCritical(true) 防止进程被回收
```

---

### 4. L3 — CodecServer 七状态机

**定义文件：** `services/services/codec/server/video/codec_server.h`

```cpp
enum CodecStatus {
    UNINITIALIZED = 0,  // 刚创建，未 Init
    INITIALIZED,         // 已 InitByName 或 InitByMime
    CONFIGURED,          // 已 Configure
    RUNNING,            // 已 Start
    FLUSHED,            // 已 Flush
    END_OF_STREAM,       // 已 EOS
    ERROR,               // 错误状态
};
```

**状态转换图：**

```
UNINITIALIZED
    │
    ├─ InitByName/InitByMime ──→ INITIALIZED
    │                                │
    │                           Configure ──→ CONFIGURED
    │                                │            │
    │                           Start ───────────┼──→ RUNNING
    │                                │            │       │
    │                                │      Flush─┼───────┼──→ FLUSHED
    │                                │            │       │    │
    │                                │      Stop──┼───────┼────┘
    │                                │            │       │
    │                          NotifyEos ────────┼───────┼──→ END_OF_STREAM
    │                                │            │       │
    └─────────────────────────────── ERROR ←───────┴───────┘
```

**状态转换 API 约束（部分）：**

| API | 要求前置状态 | 状态转换结果 |
|-----|-----------|------------|
| `Init()` | UNINITIALIZED | → INITIALIZED |
| `Configure()` | INITIALIZED | → CONFIGURED |
| `Start()` | CONFIGURED 或 FLUSHED | → RUNNING |
| `Flush()` | RUNNING | → FLUSHED |
| `Stop()` | RUNNING 或 FLUSHED | 停止底层引擎 |
| `Reset()` | 任意（除 UNINITIALIZED） | → INITIALIZED |
| `Release()` | 任意 | 释放所有资源 |

**线程安全：** `std::shared_mutex mutex_` 保护状态变更，所有公有 API 都加锁。

---

### 5. L3.5 — CodecBase 底层引擎

**创建路径：**
```cpp
// CodecServer::InitByName()
codecBase_ = CodecFactory::Instance().CreateCodecByName(codecName);
// 示例 codecName: "c2.vdec.avc", "c2.venc.avc", "omx.h264enc" 等

// CodecServer::InitByMime()
// 遍历 CodecFactory::GetCodecNameArrayByMime() 返回的名称数组
// 尝试创建，第一个成功即停止
```

**CodecBase 生命周期由 CodecServer 持有：**
```cpp
std::shared_ptr<CodecBase> codecBase_;  // CodecServer 成员变量
// ~CodecServer() 中: codecBase_ = nullptr; 触发 CodecBase 析构
```

---

### 6. 初始化路径详解

**CodecServer 实例创建（静态工厂）：**
```cpp
// codec_server.h
static std::shared_ptr<ICodecService> Create(int32_t instanceId = INVALID_INSTANCE_ID) {
    std::shared_ptr<CodecServer> server = std::make_shared<CodecServer>();
    int32_t ret = server->InitServer(instanceId);
    return (ret == AVCS_ERR_OK) ? server : nullptr;
}
```

**InitByName 路径（指定 Codec 名）：**
```
客户端: GetCodecNameByMime(mime, isEncoder) → "c2.vdec.avc"
       CreateByName("c2.vdec.avc")
         → AVCodecServiceProxy → IPC → CodecServiceStub
         → CodecServerManager::CreateStubObject(CODEC)
         → AVCodecServer::GetSubSystemAbility(CODEC)
         → CodecServer::Create(CodecServer)
         → CodecServer::Init(..., isMimeType=false, name="c2.vdec.avc")
         → InitByName("c2.vdec.avc")
         → CodecFactory::CreateCodecByName("c2.vdec.avc")
         → 加载对应 .so 插件
```

**InitByMime 路径（按 MIME 自动选择）：**
```
客户端: CreateByMime(mime, isEncoder)
       → CodecServer::Init(..., isMimeType=true, mime)
       → InitByMime(type, mime)
         → CodecFactory::GetCodecNameArrayByMime(type, mime) → ["c2.vdec.avc", "omx.h264dec"]
         → for each name: InitByName(name)
           第一个成功即返回
```

---

### 7. CodecServer 关键成员组件

| 组件 | 类型 | 说明 |
|------|------|------|
| `codecBase_` | `shared_ptr<CodecBase>` | 底层编解码引擎（插件） |
| `temporalScalability_` | `shared_ptr<TemporalScalability>` | 时域可分级（S19相关） |
| `drmDecryptor_` | `shared_ptr<CodecDrmDecrypt>` | DRM 解密（S17相关） |
| `postProcessing_` | `unique_ptr<DynamicPostProcessing>` | 后处理（S20相关） |
| `inputParamTask_` | `shared_ptr<TaskThread>` | 时域可分级首帧任务线程 |
| `releaseBufferTask_` | `shared_ptr<TaskThread>` | Surface 模式输出释放线程 |
| `framerateCalculator_` | `shared_ptr<FramerateCalculator>` | 自适应帧率（S43相关） |
| `decodedBufferInfoQueue_` | `shared_ptr<LockFreeQueue<DecodedBufferInfo, 20>>` | 解码输出无锁队列 |
| `postProcessingInputBufferInfoQueue_` | `shared_ptr<LockFreeQueue<DecodedBufferInfo, 8>>` | 后处理输入无锁队列 |

**无锁队列（LockFreeQueue）：**
```cpp
using DecodedBufferInfoQueue = LockFreeQueue<DecodedBufferInfo, 20>; // 20: 队列深度
using PostProcessingBufferInfoQueue = LockFreeQueue<DecodedBufferInfo, 8>; // 8: 队列深度
// 生产者：CodecBase 回调（OnOutputBufferAvailable）
// 消费者：PostProcessing TaskThread
```

---

### 8. 实例信息跟踪 (InstanceInfo)

**InstanceInfo 结构（`instance_info.h`）：**
```cpp
struct InstanceInfo {
    int32_t instanceId;
    pid_t pid;              // 客户端进程ID
    pid_t actualPid;        // 实际进程ID（可能是渲染进程）
    int32_t appUid;
    int32_t appPid;
    std::string bundleName;  // 客户端包名
    uint64_t instanceId;    // 实例唯一标识
    AVCodecType codecType;
    std::string codecName;
    std::string mime;       // MIME 类型
    int64_t createTime;     // 创建时间戳
    // ... 更多字段
};
```

**InstanceInfo 的用途：**
- DFX 统计：按进程/应用统计 Codec 使用量
- 内存管理：配合 MEMORY_MANAGER_SA 进程回收
- 权限校验：区分不同应用的 Codec 实例
- 安全解码器追踪：`GetActiveSecureDecoderPids()`

---

### 9. 进程间通信与 CodecServiceStub

**CodecServiceStub 分发（`codec_service_stub.cpp`）：**
- 32 个 `CodecServiceInterfaceCode` 函数指针，通过 `OnRemoteRequest()` 统一分发
- 跨进程调用通过 Binder 机制，CodecServer 作为服务进程

**CodecServiceProxy（客户端代理）：**
- 封装 Binder 调用，客户端进程持有
- 通过 `GetSystemAbility(AV_CODEC_SERVICE_ID)` 获取 SA proxy

---

### 10. 与其他主题的关联

| 主题 | 关联点 |
|------|--------|
| **S3 (CodecServer Pipeline)** | CodecServer 持有 CodecBase，Pipeline 数据流经由 CodecServer 的输入/输出队列 |
| **S19 (TemporalScalability)** | `temporalScalability_` 成员，`CodecScenarioInit()` 在 Configure 时初始化 |
| **S20 (PostProcessing)** | `postProcessing_` 成员，`DecodedBufferInfoQueue` 作为解码与后处理的桥梁 |
| **S21 (AVCodec IPC)** | CodecServer 通过 CodecServiceStub 处理 IPC 请求，AVCodecServerManager 管理 Stub 生命周期 |
| **S39 (VideoDecoder)** | CodecServer 持有 VideoDecoder（通过 CodecBase 多态） |
| **S42 (VideoEncoder)** | CodecServer 持有 VideoEncoder（通过 CodecBase 多态） |
| **S43 (AFC)** | `framerateCalculator_` 成员，在 Init 时创建 |

---

### 11. 关键文件索引

| 文件路径 | 内容 |
|---------|------|
| `services/services/sa_avcodec/server/avcodec_server.cpp` | AVCodecServer SA 生命周期，OnStart/OnIdle/OnStop，SA 注册宏 |
| `services/services/sa_avcodec/server/include/avcodec_server_manager.h` | AVCodecServerManager 单例，实例池管理，进程内存管理集成 |
| `services/services/codec/server/video/codec_server.h` | CodecServer 类定义，七状态机，43个 ICodecService 接口 |
| `services/services/codec/server/video/codec_server.cpp` | CodecServer 实现，Init/Configure/Start/Stop/Release 状态转换 |
| `services/include/i_codec_service.h` | ICodecService 抽象接口（43个纯虚函数） |
| `services/services/codec/ipc/codec_service_stub.cpp` | IPC 请求分发，32个 CodecServiceInterfaceCode |
| `services/engine/codec/include/codecbase.h` | CodecBase 底层引擎基类 |

---

## 附录：CodecServer 状态转换速查

```
UNINITIALIZED
    └─ Init() → INITIALIZED
              └─ Configure() → CONFIGURED
                             └─ Start() → RUNNING
                                        ├─ Flush() → FLUSHED
                                        │            └─ Start() → RUNNING（再次）
                                        ├─ Stop() → (停止引擎)
                                        ├─ NotifyEos() → END_OF_STREAM
                                        └─ 错误 → ERROR
    └─ 任意时刻 Reset() → INITIALIZED
    └─ 任意时刻 Release() → (资源释放)
```
