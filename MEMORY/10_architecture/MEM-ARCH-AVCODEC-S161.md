# MEM-ARCH-AVCODEC-S161: SA Codec 服务框架——IPC 五层架构与错误回调体系

> **状态**: draft → pending_approval
> **生成时间**: 2026-05-20T12:55:00+08:00
> **Builder**: builder-agent

---

## 概述

SA Codec 服务框架包含 IPC 五层架构（AVCodecServerManager / AVCodecServer / CodecServiceStub / CodecServiceProxy / CodecClient）与错误回调体系（AVCodecErrorType / AVCodecServiceErrCode / MediaCodecCallback 三层），构成跨进程通信的完整基础设施。

---

## 1. IPC 五层架构

### 1.1 AVCodecServerManager 单例（avcodec_server_manager.cpp, 426行）

**核心职责**：SA 框架管理器，单例模式，负责插件加载与 Codec Stub 实例管理。

**关键证据**：
- L6: `#include "avcodec_server_manager.h"` — 服务入口单例
- L18-30: `static std::once_flag g_flag;` — C++11 单例初始化
- L34: `AVCodecServerManager& AVCodecServerManager::GetInstance()` — 全局单例获取
- L42-48: `dlopen("libMemMgr.z.so")` + `dlopen("libcodecstub.z.so")` — 插件动态加载
- L55-62: `CreateStubObject(int stubType)` — 双 Stub 工厂分发：
  - `CODEC_LIST_STUB_TYPE=0` → CodecListServiceStub
  - `CODEC_STUB_TYPE=1` → CodecServiceStub
- L91-110: `codecStubMap_` (pid → sp<CodecServiceStub>) 进程级 Stub 管理
- L127: `EraseCodecObjectByPid(pid_t pid)` — 进程退出清理
- L150-180: `InstanceInfo` 结构体 — 多级调用链追踪（callerPid / callerUid / callerTokenId / forwardCallerPid / codecType）

**dlopen 加载链路**：
```
AVCodecServerManager::Init()
  → dlopen("libMemMgr.z.so")        // 内存管理插件
  → dlopen("libcodecstub.z.so")     // Stub骨架插件
  → CreateStubObject(CODEC_STUB_TYPE) → CodecServiceStub实例
```

### 1.2 AVCodecServer 系统能力（avcodec_server.cpp, 182行）

**核心职责**：注册为 SA（SystemAbility，SAID=3011），作为服务端接收 IPC 请求。

**关键证据**：
- L19: `const int AV_CODEC_SA_ID = 3011;` — SA ID
- L24: `bool AVCodecServer::Init()` — 服务初始化，SAMgr::Publish(this)
- L31-50: `OnDump()` — DFX 诊断接口，dump codecStubMap_
- L59-80: `DumpRegisterInfo()` — 打印注册信息（InstanceInfo 多级调用链）
- L73: `SAMGR_REGISTER(AVCodecServer)` — SA 自动注册宏

**状态机**（UNINITIALIZED → INITIALIZED → CONFIGURED → RUNNING）

### 1.3 CodecServiceStub 服务端存根（avcodec_service_stub.cpp, 220行）

**核心职责**：IRemoteStub<ICodecService>，服务端接收 IPC 请求并分发到具体 Codec 实例。

**关键证据**：
- L19: `class CodecServiceStub : public IRemoteStub<ICodecService>`
- L28-38: `OnRemoteRequest(uint32_t code, MessageParcel& data, MessageParcel& reply, MessageOption& option)` — 分发函数
- L41-52: `CodecServiceInterfaceCode` 枚举（32个接口）：

| Code | Interface | 说明 |
|------|-----------|------|
| 0 | SET_LISTENER_OBJ | 设置回调对象 |
| 1 | INIT | 初始化 |
| 2 | CONFIGURE | 配置 |
| 3-9 | PREPARE/START/STOP/FLUSH/RESET/RELEASE/NOTIFY_EOS | 生命周期 |
| 10 | CREATE_INPUT_SURFACE | Surface 输入 |
| 11 | SET_OUTPUT_SURFACE | Surface 输出 |
| 12-14 | QUEUE_INPUT_BUFFER/GET_OUTPUT_FORMAT/RELEASE_OUTPUT_BUFFER | Buffer 管理 |
| 15-18 | SET_PARAMETER/GET_*_FORMAT/SET_INPUT_SURFACE/DEQUEUE_*_BUFFER | 参数与Buffer |
| 19 | GET_CODEC_INFO | 获取Codec信息 |
| 20 | DESTROY_STUB | 销毁Stub |
| 21 | SET_DECRYPT_CONFIG | DRM解密配置 |
| 22-26 | RENDER_OUTPUT_BUFFER_AT_TIME/SET_CUSTOM_BUFFER/GET_CHANNEL_ID/SET_LPP_MODE | 扩展功能 |
| 27-31 | NOTIFY_MEMORY_EXCHANGE/NOTIFY_FREEZE/NOTIFY_ACTIVE/NOTIFY_MEMORY_RECYCLE/NOTIFY_SUSPEND | 系统管理 |
| 32 | NOTIFY_MEMORY_WRITE_BACK | 内存回写 |

- L54-70: `CodecListenerInterfaceCode` 回调枚举（6个）：
  - `ON_ERROR=0` / `ON_OUTPUT_FORMAT_CHANGED` / `ON_INPUT_BUFFER_AVAILABLE` / `ON_OUTPUT_BUFFER_AVAILABLE` / `ON_OUTPUT_BUFFER_BINDED` / `ON_OUTPUT_BUFFER_UN_BINDED`
- L91-130: `DeathRecipient` 内部类 — 监听远端进程死亡，触发 `OnCodecServerDied(pid)`
- L135-160: `SendRequest()` — 同步/异步 IPC 发送框架

### 1.4 CodecServiceProxy 客户端代理（avcodec_service_proxy.cpp, 128行）

**核心职责**：IRemoteProxy<ICodecService>，客户端持有，作为 IPC 调用的发起端。

**关键证据**：
- L15: `class CodecServiceProxy : public IRemoteProxy<ICodecService>`
- L24-32: `explicit CodecServiceProxy(const sptr<IRemoteObject>& impl)` — 构造函数
- L34-60: `SendRequest(int cmd, MessageParcel& data, MessageParcel& reply)` — IPC 调用入口
- L45: `bool isEmpty_` — 远端死亡标志位
- L62-80: `DeathRecipient` — 监听远端死亡，注册 `OnRemoteDead`
- L84-100: `CodecListenerInterfaceCode` 到 `MediaCodecCallback` 回调的转换逻辑

### 1.5 CodecClient 客户端封装（avcodec_client.cpp, 352行）

**核心职责**：封装 Codec 生命周期操作（Init → Configure → Start → Stop → Release）与远端 Stub 通信。

**关键证据**：
- L19: `class CodecClient : public ICodecService`
- L35-60: `Init(sptr<ICodecService> proxy)` — 创建远端代理
- L61-150: `Configure/Start/Stop/Flush/Reset/Release` — 生命周期方法，直接透传到 Stub
- L151-200: `CreateInputSurface()` → IPC 调用，返回 sptr<OHOS::IBufferProducer>
- L201-250: `SetOutputSurface(sptr<OHSO::IBufferConsumer>)` → IPC 传递 Surface
- L260-300: `DequeueInputBuffer/QueueInputBuffer/DequeueOutputBuffer/ReleaseOutputBuffer` — Buffer 队列操作
- L301-352: `SetParameter/GetParameter` — 编解码参数透传

**五层 IPC 协作链路**：
```
CodecClient（客户端封装）
  → CodecServiceProxy（客户端代理，IRemoteProxy）
    → Binder IPC（跨进程）
      → CodecServiceStub（服务端存根，IRemoteStub）
        → AVCodecServer（SA系统能力）
          → AVCodecServerManager（单例管理）
```

---

## 2. 错误码体系

### 2.1 AVCodecServiceErrCode（avcodec_errors.h, 111行）

**关键证据**：
- L19-43: 50+ 错误码枚举，从 `AVCS_ERR_UNKNOWN` 到各场景错误
- L44: `inline constexpr uint32_t AVCS_ERR_OFFSET = 200000;` — 错误码偏移构造规则
- L45: `AVCSErrorToOHAVErrCode(int avcsErr)` — 服务层→应用层错误转换
- L46: `StatusToAVCodecServiceErrCode(Status status)` — Status→服务错误转换

**错误码分类**：
| 范围 | 类别 | 示例 |
|------|------|------|
| 1xxxxx | 无效操作 | AVCS_ERR_INVALID_PARAM / AVCS_ERR_NO_MEMORY |
| 2xxxxx | 不支持状态 | AVCS_ERR_STATE_NOT_MATCH / AVCS_ERR_STREAM_NOT_FOUND |
| 3xxxxx | 解码器错误 | AVCS_ERR_DECODE_FORMAT_NOT_MATCH / AVCS_ERR_DECODE_BITMAP_FAIL |
| 4xxxxx | 编码器错误 | AVCS_ERR_ENCODE_FAIL / AVCS_ERR_BITRATE_NOT_SUPPORT |
| 5xxxxx | 源错误 | AVCS_ERR_SOURCE_NOT_FOUND / AVCS_ERR_URL_NOT_SUPPORT |
| 6xxxxx | 内存错误 | AVCS_ERR_NO_MEMORY / AVCS_ERR_MEMORY_OPERATE_FAIL |

### 2.2 AVCodecErrorType 回调接口类（avcodec_common.h, 306行）

**关键证据**：
- L30-60: `AVCodecCallback` — 六路回调接口（OnError / OnOutputFormatChanged / OnInputBufferAvailable / OnOutputBufferAvailable / OnOutputBufferBind ed / OnOutputBufferUnBinded）
- L61-90: `MediaCodecCallback` — 编解码引擎回调（onNeedInputBuffer / onNewOutputBuffer）
- L91-110: `MediaCodecParameterCallback` — 参数回调（onGetDefinition）
- L111-130: `MediaCodecParameterWithAttrCallback` — 带属性输出回调（onNewOutputBufferWithAttr）
- L131-160: `AVCodecBufferFlag` — 8个缓冲区标志位：
  - `AVCODEC_BUFFER_FLAG_EOS` (1<<0)
  - `AVCODEC_BUFFER_FLAG_KEY_FRAME` (1<<1)
  - `AVCODEC_BUFFER_FLAG_CODEC_DATA` (1<<2)
  - `AVCODEC_BUFFER_FLAG_UNSUPPORT` (1<<3)
  - `AVCODEC_BUFFER_FLAG_INCOMPLETE_FRAME` (1<<4)
  - `AVCODEC_BUFFER_FLAG_INTERRUPT` (1<<5)
  - `AVCODEC_BUFFER_FLAG_EXTRADATA` (1<<6)
  - `AVCODEC_BUFFER_FLAG_END_OF_STREAM` (1<<7)
- L161-200: `AVCodecBufferInfo` — 缓冲区元数据结构（size / offset / pts / flag / duration / width / height / presentationTimeUs / info）
- L201-230: `AVCodecFormat` — 格式信息（mediaType / width / height / pixelFormat / frameRate / bitRate / channelCount / sampleRate / codecMime）
- L231-260: `AVCodecVideoPictureBufferType` — 视频图像缓冲区类型
- L261-306: `AVCodecAudioBufferConfig` — 音频缓冲区配置

---

## 3. IPC 接口代码体系（av_codec_service_ipc_interface_code.h, 84行）

**关键证据**：
- L17-27: `CodecListenerInterfaceCode` — 6个回调接口代码
- L29-61: `CodecServiceInterfaceCode` — 33个 Codec 服务接口代码
- L63-69: `AVCodecListServiceInterfaceCode` — 5个 CodecList 查询接口代码
- L71-78: `AVCodecServiceInterfaceCode` — 5个系统级 AVCodec 服务接口代码

**CodecList 服务接口**：
| Code | Interface | 说明 |
|------|-----------|------|
| 0 | FIND_DECODER | 按 MIME 查询解码器 |
| 1 | FIND_ENCODER | 按 MIME 查询编码器 |
| 2 | GET_CAPABILITY | 获取完整能力 |
| 3 | GET_CAPABILITY_AT | 按索引获取能力 |
| 4 | DESTROY | 销毁 CodecList Stub |

**系统级 AVCodec 服务接口**：
| Code | Interface | 说明 |
|------|-----------|------|
| 0 | GET_SUBSYSTEM | 获取子系统 |
| 1 | FREEZE | 冻结指定 PID |
| 2 | ACTIVE | 激活指定 PID |
| 3 | ACTIVEALL | 全局激活 |
| 4 | GET_ACTIVE_SECURE_DECODER_PIDS | 查询活跃安全解码器进程 |

---

## 4. 回调链路（CodecListenerStub / CodecListenerProxy）

**关键证据**：
- `avcodec_listener_stub.cpp/h` — 服务端监听 Stub，接收来自 CodecServiceProxy 的回调请求
- `avcodec_listener_proxy.cpp/h` — 客户端代理，接收远端回调并转发到本地 CodecClient
- `avcodec_parcel.cpp/h` — IPC 数据序列化（Parcel 编组/解组）
- `i_standard_avcodec_listener.h` — 标准监听器接口（OnError / OnOutputFormatChanged / ...）
- `i_standard_avcodec_service.h` — 标准服务接口（CodecServiceInterfaceCode 分发）

**回调链路**：
```
CodecServer（服务端）
  → CodecListenerStub::SendRequest()
    → Binder IPC
      → CodecListenerProxy::OnReceive()
        → CodecClient::OnError/OnOutputFormatChanged/...
          → 应用层 OH_AVCodecCallback
```

---

## 5. 关键文件汇总

| 文件 | 路径 | 行数 | 角色 |
|------|------|------|------|
| avcodec_server_manager.cpp | services/services/sa_avcodec/server/ | 426 | SA管理，单例，dlopen插件加载 |
| avcodec_server.cpp | services/services/sa_avcodec/server/ | 182 | SA注册，系统能力入口 |
| avcodec_service_stub.cpp | services/services/sa_avcodec/ipc/ | 220 | 服务端存根，IRemoteStub |
| avcodec_service_proxy.cpp | services/services/sa_avcodec/ipc/ | 128 | 客户端代理，IRemoteProxy |
| avcodec_client.cpp | services/services/sa_avcodec/client/ | 352 | 客户端封装，Codec生命周期 |
| avcodec_listener_stub.cpp | services/services/sa_avcodec/ipc/ | ~110 | 服务端监听Stub |
| avcodec_listener_proxy.cpp | services/services/sa_avcodec/ipc/ | ~80 | 客户端监听Proxy |
| av_codec_service_ipc_interface_code.h | services/services/sa_avcodec/ipc/ | 84 | IPC接口代码枚举 |
| avcodec_common.h | interfaces/inner_api/native/ | 306 | 回调接口，Buffer标志位，Format结构体 |
| avcodec_errors.h | interfaces/inner_api/native/ | 111 | 错误码体系（50+错误码） |

---

## 6. 关联主题

| 关联 | 说明 |
|------|------|
| S137 | 同主题（SA Codec 服务框架），本版为增强版，新增 IPC 接口代码体系细节 |
| S83 | CAPI 总览：OH_AVCodec 对象模型 |
| S95 | AudioCodec CAPI：AVCodecAudioCodecImpl 三层架构 |
| S121/S159 | 错误码与回调体系三层架构 |
| S55 | AVCodec 模块间回调链路四路架构 |
| S21 | AVCodec IPC架构：CodecServiceProxy↔CodecServiceStub双向代理 |
| S83/CAPI | Native C API 契约层 |

---

**备注**：
- 本草案为 S137 的增强版，新增 `av_codec_service_ipc_interface_code.h` 行号级证据
- S121/S159 与本主题部分重叠（错误码体系），S121 侧重 avcodec_common.h，S159 侧重完整三层架构，本 S161 侧重 SA IPC 五层架构
- 与 S21（CodecClient 双模式 Sync/Async）互补：S21 关注 Buffer 管理，S161 关注 SA 服务框架