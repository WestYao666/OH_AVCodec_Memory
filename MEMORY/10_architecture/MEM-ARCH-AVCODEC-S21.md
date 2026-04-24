---
type: architecture
id: MEM-ARCH-AVCODEC-S21
status: draft
topic: AVCodec IPC架构与CodecClient双模式——CodecServiceProxy+CodecServiceStub双向代理与CodecBufferCircular同步/异步模式切换
created_at: "2026-04-24T10:51:00+08:00"
evidence: |
  - source: /home/west/av_codec_repo/services/services/codec/ipc/codec_service_proxy.h
    anchor: "CodecServiceProxy : IRemoteProxy<IStandardCodecService> — 客户端IPC代理，SendRequest转发到Stub"
  - source: /home/west/av_codec_repo/services/services/codec/ipc/codec_service_proxy.cpp
    anchor: "CodecServiceProxy::Configure / Start / Stop / QueueInputBuffer — MessageParcel写入 + Remote()->SendRequest"
  - source: /home/west/av_codec_repo/services/services/codec/ipc/codec_service_proxy.cpp
    anchor: "CodecServiceProxy::SetOutputSurface — producer->AsObject()->WriteRemoteObject序列化Surface的IBufferProducer"
  - source: /home/west/av_codec_repo/services/services/codec/ipc/codec_service_proxy.cpp
    anchor: "CodecServiceProxy::CreateInputSurface — ReadRemoteObject + iface_cast<IBufferProducer> + CreateSurfaceAsProducer"
  - source: /home/west/av_codec_repo/services/services/codec/ipc/codec_service_proxy.cpp
    anchor: "CodecServiceProxy::Stop / Flush / Reset — listenerStub->ClearListenerCache() / FlushListenerCache()"
  - source: /home/west/av_codec_repo/services/services/codec/ipc/codec_service_stub.h
    anchor: "CodecServiceStub : IRemoteStub<IStandardCodecService> — 服务端Binder桩，OnRemoteRequest分发32个CodecServiceInterfaceCode"
  - source: /home/west/av_codec_repo/services/services/codec/ipc/codec_service_stub.cpp
    anchor: "recFuncs_ map[32 entries] — INIT/CONFIGURE/PREPARE/START/STOP/FLUSH/RESET/RELEASE等，函数指针映射到CodecServer"
  - source: /home/west/av_codec_repo/services/services/codec/ipc/codec_service_stub.cpp
    anchor: "CodecServiceStub::InitStub — codecServer_ = CodecServer::Create(instanceId)，创建视频CodecServer实例"
  - source: /home/west/av_codec_repo/services/services/codec/ipc/codec_service_stub.cpp
    anchor: "AVCODEC_FUNC_INTERACTIVE_QOS — QOS_USER_INTERACTIVE标记，服务端Stub调用CodecServer关键路径"
  - source: /home/west/av_codec_repo/services/services/codec/client/codec_client.h
    anchor: "CodecClient : MediaCodecCallback + ICodecService + enable_shared_from_this — 客户端业务封装"
  - source: /home/west/av_codec_repo/services/services/codec/client/codec_client.h
    anchor: "CodecMode : CODEC_DEFAULT_MODE / CODEC_SURFACE_INPUT / CODEC_SURFACE_OUTPUT / CODEC_ENABLE_PARAMETER / CODEC_SURFACE_MODE_WITH_PARAMETER"
  - source: /home/west/av_codec_repo/services/services/codec/client/codec_client.h
    anchor: "CallbackMode : MEMORY_CALLBACK / BUFFER_CALLBACK / INVALID_CALLBACK"
  - source: /home/west/av_codec_repo/services/services/codec/client/codec_buffer_circular.h
    anchor: "CodecBufferCircular::CanEnableSyncMode / CanEnableAsyncMode — 同步/异步模式不可切换，只能配置一次"
  - source: /home/west/av_codec_repo/services/services/codec/client/codec_buffer_circular.h
    anchor: "CodecBufferCircular::BufferOwner : OWNED_BY_SERVER / OWNED_BY_CLIENT / OWNED_BY_USER — buffer生命周期三段式"
  - source: /home/west/av_codec_repo/services/services/codec/client/codec_buffer_circular.h
    anchor: "CodecBufferCircular::FLAG_IS_SYNC — FLAG_SYNC_ASYNC_CONFIGURED一旦设置，模式不可更改"
  - source: /home/west/av_codec_repo/services/services/codec/client/codec_buffer_circular.h
    anchor: "CodecBufferCircular::EnableAsyncMode<MODE_ASYNC>() / EnableSyncMode<MODE_SYNC>() — C++17 if constexpr模式分支"
  - source: /home/west/av_codec_repo/services/services/codec/client/buffer_converter.h
    anchor: "BufferConverter::ReadFromBuffer / WriteToBuffer — 用户内存与Codec内部AVBuffer格式转换"
  - source: /home/west/av_codec_repo/services/services/codec/client/buffer_converter.h
    anchor: "BufferConverter::SetInputBufferFormat / SetOutputBufferFormat — SurfaceBuffer stride/wStride/hStride同步"
  - source: /home/west/av_codec_repo/services/services/codec/ipc/codec_listener_stub.h
    anchor: "CodecListenerStub : IRemoteStub<IStandardCodecListener> — 服务端回调IPC桩，OnRemoteRequest处理6种回调事件"
  - source: /home/west/av_codec_repo/services/services/codec/ipc/codec_listener_stub.h
    anchor: "CodecListenerStub::inputBufferCache_ / outputBufferCache_ — CodecBufferCache双缓存，WriteInputBufferToParcel/WriteOutputBufferToParcel"
---

# MEM-ARCH-AVCODEC-S21: AVCodec IPC架构与CodecClient双模式

## Metadata

| 字段 | 值 |
|------|-----|
| id | MEM-ARCH-AVCODEC-S21 |
| title | AVCodec IPC架构与CodecClient双模式——CodecServiceProxy+CodecServiceStub双向代理与CodecBufferCircular同步/异步模式切换 |
| scope | [AVCodec, IPC, CodecClient, CodecServiceProxy, CodecServiceStub, CodecListenerStub, CodecBufferCircular, Binder, SyncMode, AsyncMode] |
| status | draft |
| created_by | builder-agent |
| created_at | 2026-04-24 |
| type | architecture_fact |
| confidence | high |
| related_scenes | [新需求开发, 问题定位, IPC通信, 双缓冲, 同步/异步模式, Surface绑定] |
| why_it_matters: |
  - 问题定位：IPC通信异常（SET_LISTENER_OBJ失败/Buffer传递丢失）需理解Proxy↔Stub的Parcel序列化机制
  - 新需求开发：CodecClient是Native API层入口，理解其CodecMode和CallbackMode对理解API行为至关重要
  - 性能分析：CodecBufferCircular的双模式（Sync/Async）和三 BufferOwner 状态机是排查丢帧/卡顿的关键
  - Surface交互：CreateInputSurface/SetOutputSurface通过IBufferProducer序列化实现跨进程Surface传递

## 1. 整体IPC架构

```
┌─────────────────────────────────────────────────────────────────┐
│  应用进程（CodecClient）                                          │
│  ┌──────────────────┐    ┌─────────────────────────────────────┐ │
│  │  MediaCodec API  │───▶│  CodecClient                        │ │
│  │  (native层)       │    │  ┌──────────────────────────────┐  │ │
│  └──────────────────┘    │  │ CodecBufferCircular          │  │ │
│                           │  │ (SyncMode / AsyncMode)       │  │ │
│  ┌──────────────────┐    │  │ + BufferConverter           │  │ │
│  │ CodecServiceProxy │◀───│  │ + listenerStub_              │  │ │
│  │ (IRemoteProxy)    │    │  └──────────────────────────────┘  │ │
│  └────────┬─────────┘    └─────────────┬──────────────────────┘ │
└───────────┼────────────────────────────┼────────────────────────┘
            │ Binder IPC (SendRequest)     │ WriteRemoteObject / ReadRemoteObject
            ▼                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  codec_server进程（CodecServiceStub）                            │
│  ┌──────────────────┐    ┌─────────────────────────────────────┐ │
│  │ CodecServiceStub  │───▶│  CodecServer (视频)                 │ │
│  │ (IRemoteStub)    │    │  AudioCodecServer (音频)            │ │
│  │ recFuncs_[32]    │    │  + CodecBase (CodecEngine插件)      │ │
│  └──────────────────┘    │  + PostProcessing (VPE后处理)       │ │
│                          └─────────────────────────────────────┘ │
│  ┌──────────────────┐                                            │
│  │ CodecListenerStub│◀───回调 IPC ─── CodecServer               │
│  └────────┬─────────┘                                           │
└───────────┼─────────────────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────────────────┐
│  应用进程（CodecClient）                                          │
│  ┌──────────────────┐                                           │
│  │ CodecListenerStub│ ◀── OnInputBufferAvailable               │
│  │ (IRemoteStub)    │    OnOutputBufferAvailable               │
│  └──────────────────┘    OnError / OnOutputFormatChanged       │
└─────────────────────────────────────────────────────────────────┘
```

**双向Proxy-Stub代理**：
- `CodecServiceProxy`（客户端代理）：将CodecClient的调用封装为Binder MessageParcel，SendRequest到CodecServiceStub
- `CodecServiceStub`（服务端桩）：接收Binder请求，通过函数指针映射表`recFuncs_[32]`分发到CodecServer
- `CodecListenerStub`（回调桩）：服务端CodecServer通过CodecListenerProxy向客户端CodecListenerStub发送回调

---

## 2. CodecServiceProxy 关键行为

**文件**: `codec_service_proxy.cpp`

### 2.1 Surface相关IPC

```cpp
// SetOutputSurface: 将Surface的IBufferProducer序列化后发送给Stub
sptr<IBufferProducer> producer = surface->GetProducer();
sptr<IRemoteObject> object = producer->AsObject();
data.WriteRemoteObject(object);  // Surface格式（"SURFACE_FORMAT"）也写入Parcel
data.WriteString(format);
Remote()->SendRequest(CodecServiceInterfaceCode::SET_OUTPUT_SURFACE, ...);

// CreateInputSurface: 接收Stub返回的IBufferProducer，创建Surface
sptr<IRemoteObject> object = reply.ReadRemoteObject();
sptr<IBufferProducer> producer = iface_cast<IBufferProducer>(object);
return Surface::CreateSurfaceAsProducer(producer);
```

### 2.2 状态同步

```cpp
// Stop / Flush / Reset时清空Listener缓存
listenerStub->ClearListenerCache();  // Stop/Reset
listenerStub->FlushListenerCache();   // Flush
```

### 2.3 32个接口代码

| 接口 | 说明 |
|------|------|
| `INIT` | 初始化Codec |
| `CONFIGURE` | 配置参数（Format） |
| `PREPARE` | 准备（分配资源） |
| `START` / `STOP` / `FLUSH` / `RESET` / `RELEASE` | 生命周期 |
| `QUEUE_INPUT_BUFFER` | 送入数据 |
| `RELEASE_OUTPUT_BUFFER` / `RENDER_OUTPUT_BUFFER_AT_TIME` | 输出buffer释放 |
| `CREATE_INPUT_SURFACE` / `SET_OUTPUT_SURFACE` | Surface模式 |
| `SET_LISTENER_OBJ` | 设置回调监听器 |
| `SET_DECRYPT_CONFIG` | DRM解密配置 |
| `SET_CUSTOM_BUFFER` | 自定义Buffer模式 |
| `NOTIFY_MEMORY_EXCHANGE` | 内存交换通知 |
| `NOTIFY_FREEZE` / `NOTIFY_ACTIVE` / `NOTIFY_SUSPEND` / `NOTIFY_RESUME` | 电源/冻结管理 |
| `NOTIFY_MEMORY_RECYCLE` / `NOTIFY_MEMORY_WRITE_BACK` | 内存管理 |

---

## 3. CodecServiceStub 分发机制

**文件**: `codec_service_stub.cpp`

```cpp
// 函数指针映射表（32个接口）
recFuncs_[CodecServiceInterfaceCode::INIT] = &CodecServiceStub::Init;
recFuncs_[CodecServiceInterfaceCode::CONFIGURE] = &CodecServiceStub::Configure;
recFuncs_[CodecServiceInterfaceCode::PREPARE] = &CodecServiceStub::Prepare;
// ... 共32个

// OnRemoteRequest分发
int32_t CodecServiceStub::OnRemoteRequest(uint32_t code, MessageParcel &data, MessageParcel &reply, MessageOption &option) {
    AVCODEC_FUNC_INTERACTIVE_QOS;  // 设置USER_INTERACTIVE QoS
    auto it = recFuncs_.find(code);
    if (it != recFuncs_.end()) {
        return (this->*(it->second))(data, reply);  // 动态调度
    }
}

// 创建CodecServer视频实例
codecServer_ = CodecServer::Create(instanceId);
```

---

## 4. CodecClient 双模式（Sync / Async）

**文件**: `codec_client.h`

### 4.1 CodecMode 标志

| 模式标志 | 值 | 说明 |
|---------|---|------|
| `CODEC_DEFAULT_MODE` | 0 | 默认模式 |
| `CODEC_SURFACE_INPUT` | 1<<0 | Surface输入模式 |
| `CODEC_SURFACE_OUTPUT` | 1<<1 | Surface输出模式 |
| `CODEC_ENABLE_PARAMETER` | 1<<2 | 参数模式 |
| `CODEC_SURFACE_MODE_WITH_PARAMETER` | SURFACE_INPUT \| ENABLE_PARAMETER | Surface+参数组合 |

### 4.2 CallbackMode

| 回调模式 | 说明 |
|---------|------|
| `MEMORY_CALLBACK` | 共享内存回调模式 |
| `BUFFER_CALLBACK` | AVBuffer直接传递模式 |
| `INVALID_CALLBACK` | 未配置 |

---

## 5. CodecBufferCircular 双缓冲机制

**文件**: `codec_buffer_circular.h` / `codec_buffer_circular.cpp`

### 5.1 同步 vs 异步模式

**核心约束：配置后不可切换**

```cpp
// 模式使能检查（只能配置一次）
template <ModeType mode>
inline bool CanEnableMode() {
    bool isUnconfigured = !HasFlag(FLAG_SYNC_ASYNC_CONFIGURED);
    bool modeMatched = !HasFlag(FLAG_IS_SYNC);  // 默认异步
    if constexpr (mode == MODE_SYNC) {
        modeMatched = HasFlag(FLAG_IS_SYNC);
    }
    return isUnconfigured || modeMatched;
}

// 使能后标记为已配置
template <ModeType mode>
inline void EnableMode() {
    if constexpr (mode == MODE_SYNC) {
        AddFlag(FLAG_IS_SYNC);
    }
    AddFlag(FLAG_SYNC_ASYNC_CONFIGURED);  // 关键：一旦标记不可更改
}
```

### 5.2 BufferOwner 三段式生命周期

```cpp
typedef enum : uint8_t {
    OWNED_BY_SERVER = 0,  // Codec服务端持有
    OWNED_BY_CLIENT = 1,   // 客户端CodecClient持有
    OWNED_BY_USER = 2,     // 用户应用持有（通过GetInputBuffer/GetOutputBuffer获取）
} BufferOwner;
```

**同步模式下的Buffer流转**：
1. `QueryInputBuffer` → 从server申请index → `OWNED_BY_CLIENT`
2. `GetInputBuffer(index)` → 用户填充数据 → `OWNED_BY_USER`
3. `QueueInputBuffer` → 送入Codec → `OWNED_BY_SERVER`

### 5.3 FLAG标志系统

```cpp
typedef enum : uint8_t {
    FLAG_NONE = 0,
    FLAG_IS_RUNNING = 1 << 0,      // Codec运行中
    FLAG_IS_SYNC = 1 << 1,          // 同步模式（与FLAG_SYNC_ASYNC_CONFIGURED配合）
    FLAG_SYNC_ASYNC_CONFIGURED = 1 << 2,  // 模式已配置（不可更改）
    FLAG_ERROR = 1 << 3,           // 错误状态
    FLAG_INPUT_EOS = 1 << 4,       // 输入结束
    FLAG_OUTPUT_EOS = 1 << 5,      // 输出结束
} CodecCircularFlag;
```

### 5.4 同步模式等待机制

```cpp
// QueryInputBuffer → inCond_.wait_for
// QueryOutputBuffer → outCond_.wait_for
// EventQueue: EVENT_INPUT_BUFFER / EVENT_OUTPUT_BUFFER / EVENT_STREAM_CHANGED
bool WaitForInputBuffer(std::unique_lock<std::mutex> &lock, int64_t timeoutUs);
bool WaitForOutputBuffer(std::unique_lock<std::mutex> &lock, int64_t timeoutUs);
```

---

## 6. BufferConverter 格式转换

**文件**: `buffer_converter.h`

```cpp
class BufferConverter {
    // 用户内存 ↔ Codec内部AVBuffer 格式转换
    int32_t ReadFromBuffer(shared_ptr<AVBuffer> &buffer, shared_ptr<AVSharedMemory> &memory);
    int32_t WriteToBuffer(shared_ptr<AVBuffer> &buffer, shared_ptr<AVSharedMemory> &memory);

    // SurfaceBuffer stride同步
    int32_t GetSliceHeightFromSurfaceBuffer(sptr<SurfaceBuffer> &surfaceBuffer) const;
    bool SetRectValue(width, height, wStride, hStride);
};
```

用于同步模式下，用户内存布局与Codec内部AVBuffer格式不匹配时进行转换。

---

## 7. CodecListenerStub 回调缓存

**文件**: `codec_listener_stub.h`

```cpp
class CodecListenerStub : public IRemoteStub<IStandardCodecListener> {
    std::unique_ptr<CodecBufferCache> inputBufferCache_;   // 输入buffer缓存
    std::unique_ptr<CodecBufferCache> outputBufferCache_;  // 输出buffer缓存

    // 6种回调事件处理
    bool WriteInputBufferToParcel(uint32_t index, MessageParcel &data);   // 从缓存取出写入Parcel
    bool WriteOutputBufferToParcel(uint32_t index, MessageParcel &data);

    bool ShouldNotify(MessageParcel &data) const;  // Generation检查
    bool CheckGeneration(uint64_t messageGeneration) const;  // 防重复通知
};
```

---

## 8. 关联主题

| 主题 | 关联点 |
|------|--------|
| S2: interfaces/kits/c API | CodecClient是Native API层实现，Sync/Async模式对应不同的API使用方式 |
| S1: codec_server.cpp | CodecServiceStub在stub进程中创建CodecServer，视频CodecServer管理视频编解码 |
| S3: CodecServer Pipeline | CodecClient通过Proxy→Stub→CodecServer→CodecBase完成数据流 |
| S4: Surface Mode | SetOutputSurface/CreateInputSurface是Surface模式的核心IPC调用 |
| S5: 四层Loader插件 | CodecBase通过dlopen加载硬件/软件Codec插件 |
| P1e: Codec实例生命周期 | CodecClient.Init→Configure→Prepare→Start→Stop→Release 对应IPC各阶段 |

## 9. 关键常量汇总

| 常量 | 值 | 含义 |
|------|----|------|
| CodecServiceInterfaceCode | 32个枚举 | IPC接口代码 |
| QOS_USER_INTERACTIVE | QoS级别 | Stub端调用CodecServer时设置 |
| UID_MEDIA_SERVICE | 1013 | MediaService UID |
| MAX_TIMEOUT | ~∞ | QueryBuffer超时上限 |
| CODEC_SURFACE_MODE_WITH_PARAMETER | `SURFACE_INPUT\|ENABLE_PARAMETER` | Surface+参数组合模式 |
