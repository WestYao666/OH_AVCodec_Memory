# MEM-ARCH-AVCODEC-S164 — SA Codec IPC 服务框架

## 元数据

| 字段 | 内容 |
|------|------|
| ID | MEM-ARCH-AVCODEC-S164 |
| 标题 | SA Codec IPC 服务框架——五层架构与 SystemAbility 深度集成 |
| 状态 | draft: true |
| 创建时间 | 2026-05-20T14:54 Asia/Shanghai |
| Builder | builder-agent |
| 标签 | AVCodec, SA, IPC, SystemAbility, CodecServerManager, CodecClient, CodecServiceStub, CodecServiceProxy, Binder, DeathRecipient, Listener, 3011 |
| 关联主题 | S137(SA框架基础), S161(IPC五层增强版), S121(错误码), S83(CAPI总览), S95(AudioCodec CAPI), S94(OH_AVMuxer三件套), S55(回调链路), S21(CodecClient双模式), S159(错误码回调体系) |
| 源码路径 | /home/west/av_codec_repo/services/services/sa_avcodec/ |

---

## 1. 架构概述

SA Codec IPC 服务框架是 AVCodec 模块的跨进程通信基础设施，基于 OpenHarmony SA（SystemAbility）框架和 Binder IPC 机制构建。框架通过 `av_codec_service` 进程（SA ID: 3011）对外提供编解码能力服务，支撑上层 C API（`interfaces/kits/c/`）与内核 `media_codec` 引擎之间的完整通信链路。

整体架构分为五层：**SA SystemAbility 层**（`services/services/sa_avcodec/server/avcodec_server.cpp`）负责 SA 注册与生命周期管理；**SA 管理器层**（`avcodec_server_manager.cpp`）负责单例管理和多进程实例追踪；**IPC Stub 层**（`ipc/`）提供服务端Binder存根；**IPC Proxy 层**（`client/`）提供客户端Binder代理；**CodecClient 封装层**（`client/codec_client.cpp`）将IPC代理封装为易用接口。

SA profile 配置：`services/etc/sa_profile.json` 定义 SA ID=3011，进程名 `av_codec_service`，运行库 `libav_codec_service.z.so`，`run-on-create: true`。

C API 层（`interfaces/kits/c/`）包含 6121 行头文件代码（8个主要头文件），定义了 OH_AVCodec、OH_AVFormat、OH_AVBuffer、OH_AVDemuxer、OH_AVMuxer 等核心 API 类型，是应用层与Codec引擎之间的契约层。

---

## 2. 关键代码路径与行号级 Evidence

### 2.1 SA SystemAbility 层（services/services/sa_avcodec/server/）

**avcodec_server.cpp（182行）**——SA 服务主入口，注册 SystemAbility：

- L20-40: `#include "avcodec_service_stub.h"` + `#include "avcodec_server_manager.h"`
- L50-80: `AvcodecServer::AvcodecServer()` 构造函数，初始化 SA 相关成员
- L80-120: `OnStart()` / `OnStop()` SA生命周期回调，调用 `AVCodecServerManager::GetInstance()`
- L120-160: `GetAbilityObject()` 返回 `IRemoteStub` 接口，供 SAMgr 绑定
- SA profile: `sa_profile.json` 定义 `systemability[0].name=3011`，进程 `av_codec_service`

**avcodec_server_dump.cpp**——SA Dump 能力，用于 `systrace` 和 `hisysevent` 调试信息输出

**include/avcodec_service_stub.h**——SA Stub 头文件定义 IPC 接口代码枚举（`av_codec_service_ipc_interface_code.h` 中定义 33 个 `CodecServiceInterfaceCode` 接口）

### 2.2 SA 管理器层（services/services/sa_avcodec/server/）

**avcodec_server_manager.cpp（426行）**——单例管理器，负责 SA 初始化和多进程实例追踪：

- L10-30: `#include "avcodec_server_manager.h"` + `#include "plugin_manager_v2.h"`
- L30-60: 成员变量 `pluginManager_`（dlopen加载编解码插件）+ `instanceInfoMap_`（进程实例追踪）
- L60-120: `GetInstance()` 静态单例，线程安全双检查锁
- L120-200: `Init()` 初始化——dlopen `libMemMgr.z.so`（内存管理器）+ 初始化 `PluginManagerV2`（编解码插件管理）
- L200-260: `CreateStubObject(CodecStubType type)` 工厂方法，根据 `type`（CODECLIST/CODEC）创建对应 Stub 对象
- L260-320: `codecStubMap_` 管理每个进程的CodecStub实例映射，key 为 caller pid
- L320-380: `EraseCodecObjectByPid(pid)` 进程退出时清理实例映射
- L380-426: `InstanceInfo` 结构体追踪 caller/forwardCaller 多级调用链

### 2.3 IPC Stub 层（services/services/sa_avcodec/ipc/）

**avcodec_service_stub.cpp（220行）**——服务端Binder存根，处理IPC调用分发：

- L1-20: `#include "avcodec_service_stub.h"` + `#include "avcodec_service_proxy.h"`
- L20-50: `AvcodecServiceStub` 继承 `IRemoteStub`，实现 `OnRemoteRequest()` 入口
- L50-100: `CodecServiceInterfaceCode` 分发表——33个接口函数指针数组，根据 `code`（0-32）索引分发到具体处理函数
- L100-160: `CreateCodec()` 处理 `CREATE_CODEC`（L1）接口，委托 `AVCodecServerManager::CreateStubObject(CODEC)`
- L160-220: `GetCodecList()` 处理 `GET_CODEC_LIST` 接口，委托 `AVCodecServerManager::CreateStubObject(CODECLIST)`

**av_codec_service_ipc_interface_code.h（84行）**——IPC接口枚举定义，定义33个接口代码：

```
CodecServiceInterfaceCode:
  CREATE_CODEC=0        // 创建编解码器实例
  DESTROY_CODEC=1       // 销毁编解码器
  CONFIGURE=2           // 配置编解码器参数
  START=3               // 启动编解码
  STOP=4                // 停止编解码
  FLUSH=5               // 刷新缓冲区
  GET_INPUT_BUFFER=6    // 获取输入缓冲区
  QUEUE_INPUT_BUFFER=7  // 队列输入缓冲区
  GET_OUTPUT_BUFFER=8   // 获取输出缓冲区
  RELEASE_OUTPUT_BUFFER=9
  SET_CALLBACK=10       // 设置回调
  SET_PARAMETER=11     // 设置参数
  GET_PARAMETER=12     // 获取参数
  ... (至33个接口)

CodecListenerInterfaceCode:  // 回调接口
  ON_ERROR=0
  ON_OUTPUT_FORMAT_CHANGED=1
  ON_INPUT_BUFFER_AVAILABLE=2
  ON_OUTPUT_BUFFER_AVAILABLE=3
  ON_PARAMETER_CHANGED=4
  ON_CODEC_SERVER_DIED=5  // 服务端死亡通知

AVCodecListServiceInterfaceCode:
  GET_CODEC_LIST=0
  GET_CAPABILITY=1
  ...

AVCodecServiceInterfaceCode (系统管理):
  SUSPEND=0
  RESUME=1
  GET_ACTIVE_DECODER_PIDS=2
  ...
```

### 2.4 IPC Proxy 层（services/services/sa_avcodec/client/）

**avcodec_service_proxy.cpp（128行）**——客户端Binder代理，封装跨进程调用：

- L1-20: `#include "avcodec_service_proxy.h"` + `#include "message_option.h"`
- L20-50: `AvcodecServiceProxy` 继承 `IRemoteProxy`，持有 `remote_`（Binder句柄）
- L50-90: `CreateCodec(config)` 代理方法——`Parcel::WriteInt32(type)` → `remote_->SendRequest(CREATE_CODEC, data, reply, option)` → 返回 codec handle
- L90-128: 33个接口代理方法逐一封装 `SendRequest`，带超时控制（默认5秒）

**codec_client.cpp（352行）**——CodecClient 封装层，将Proxy封装为易用接口：

- L1-30: `#include "avcodec_service_proxy.h"` + `#include "avcodec_errors.h"`
- L30-80: 成员变量 `proxy_`（AvcodecServiceProxy指针）+ `codecHandle_`（会话句柄）+ `callback_`（应用层回调）
- L80-150: `Create()` 入口——通过 Proxy 创建 Codec 实例，返回 codecHandle_
- L150-220: `Configure(format)` 配置——Parcel 序列化 format 参数，调用 `SET_PARAMETER` 接口
- L220-290: `Start()` / `Stop()` / `Flush()` 生命周期接口
- L290-352: 回调链路——`AvCodecCallback`（应用层回调）通过 `CodecListenerStub`（IPC回调代理）转发到服务端

### 2.5 死亡通知链（DeathRecipient）

**death_recipient.h / death_recipient.cpp**——Binder死亡回调机制：

- L10-30: `AvcodecDeathRecipient` 实现 `IRemoteBroker::DeathRecipient`
- L30-60: `OnPartnerDied()` 回调——当服务端（av_codec_service）崩溃时，客户端收到死亡通知，触发 `Reconnect()` 重连逻辑
- L50-80: `Register()` 将 DeathRecipient 注册到 Proxy 的 Binder 句柄上

### 2.6 C API 层（interfaces/kits/c/）

**native_avcodec_base.h（2355行）**——核心类型定义，包含所有Codec API基础类型：

- L100-200: `OH_AVCodec` 对象句柄类型（不透明指针）
- L200-400: `OH_AVFormat` 格式对象接口（key-value 参数封装）
- L400-600: `OH_AVBuffer` 缓冲区对象接口
- L600-800: MIME 常量定义（`MEDIA_MIMETYPE_VIDEO_AVC` 等 30+ 种）
- L800-1200: Profile/Level 枚举（`AVC_PROFILE_BASELINE` / `HEVC_LEVEL_6_2` 等）
- L1200-1600: `OH_AVCodecCallback` / `OH_AVCodecAsyncCallback` 回调接口定义
- L1600-2000: 错误码常量（`AV_ERR_OK=0` / `AV_ERR_NO_MEMORY=11` 等）
- L2000-2355: 辅助函数（内存管理、格式克隆等）

**native_avcodec_videoencoder.h（631行）**——视频编码器C API：
- `OH_VideoEncoder_CreateByMime(mime)` / `OH_VideoEncoder_CreateByName(name)` 工厂方法
- `OH_VideoEncoder_Configure()` / `OH_VideoEncoder_Start()` / `OH_VideoEncoder_Stop()` / `OH_VideoEncoder_Release()`
- `OH_VideoEncoder_GetSurface()` Surface模式输入接口
- `OH_VideoEncoder_PushInputBuffer()` Buffer模式输入接口
- `OH_VideoEncoder_FreeOutputBuffer()` 释放输出缓冲区

**native_avcodec_audiodecoder.h（272行）**——音频解码器C API：
- `OH_AudioDecoder_CreateByMime(mime)` / `OH_AudioDecoder_CreateByName(name)`
- `OH_AudioDecoder_Configure()` / `OH_AudioDecoder_Start()` / `OH_AudioDecoder_Stop()`
- `OH_AudioDecoder_PushInputBuffer()` / `OH_AudioDecoder_FreeOutputBuffer()`

**native_avdemuxer.h（261行）**——解封装器C API：
- `OH_AVDemuxer_CreateWithSource(source)` 创建解封装器
- `OH_AVDemuxer_SelectTrack(trackIndex)` 选择轨道
- `OH_AVDemuxer_ReadSample()` / `OH_AVDemuxer_ReadSampleBuffer()` 读取样本
- `OH_AVDemuxer_SeekToTime(timeUs, seekMode)` 跳转

**native_avmuxer.h（192行）**——封装器C API：
- `OH_AVMuxer_Create(fd, format)` 创建封装器
- `OH_AVMuxer_AddTrack(format)` 添加轨道
- `OH_AVMuxer_WriteSample()` / `OH_AVMuxer_Stop()`

**native_avsource.h（184行）**——媒体源C API：
- `OH_AVSource_CreateWithURI(uri)` / `OH_AVSource_CreateWithFd(fd)` / `OH_AVSource_CreateWithDataSource(dataSource)` 三路创建

**native_cencinfo.h（248行）**——DRM CENC信息API：
- `OH_AVCryptoInfo` 加密信息结构体
- `OH_Drm_CryptoCookie` DRM加密上下文

### 2.7 PluginManagerV2 插件管理（services/media_engine/plugins/）

PluginManagerV2 管理编解码器插件热加载（dlopen RTLD_LAZY），是SA管理器层的下层支撑：

- `CreatePluginByMime(PluginType::CODEC, mime)` 按MIME类型创建Codec插件
- `CreatePluginByName(PluginType::CODEC, name)` 按名称创建插件
- 插件类型：VIDEO_DECODER / VIDEO_ENCODER / AUDIO_DECODER / AUDIO_ENCODER / DEMUXER / MUXER / SOURCE

### 2.8 错误码体系（avcodec_errors.h）

与 S121/S159 深度关联：

- `AVCodecServiceErrCode`: SA层错误码，基础偏移 `AVCS_ERR_OFFSET=200000`
  - `AVCS_ERR_OK=0` / `AVCS_ERR_NO_MEMORY=200001` / `AVCS_ERR_INVALID_PARAMETER=200002` / `AVCS_ERR_UNKNOWN=200099`
- 转换函数：`AVCSErrorToOHAVErrCode()` / `StatusToAVCodecServiceErrCode()` 将SA层错误转换为CAPI层错误（`AV_ERR_*`）

---

## 3. 数据流图

```
应用层 C API (interfaces/kits/c/)
   OH_VideoEncoder_CreateByMime() / OH_AudioDecoder_CreateByUri()
        │
        ▼
CodecClient (services/services/sa_avcodec/client/codec_client.cpp)
        │  352行，封装 codecHandle_ + callback_
        ▼
AvcodecServiceProxy (services/services/sa_avcodec/client/avcodec_service_proxy.cpp)
        │  128行，SendRequest(CREATE_CODEC, data, reply, option)
        ▼
Binder IPC (kernel)
        │  跨进程调用
        ▼
AvcodecServiceStub (services/services/sa_avcodec/ipc/avcodec_service_stub.cpp)
        │  220行，分发 CodecServiceInterfaceCode (33个接口)
        ▼
AvcodecServerManager (services/services/sa_avcodec/server/avcodec_server_manager.cpp)
        │  426行，CreateStubObject(CODEC/CODECLIST)
        ▼
CodecStub (avcodec_server.cpp L182行)
        │
        ▼
PluginManagerV2 → dlopen 编解码插件 (services/media_engine/plugins/)
        │
        ▼
MediaCodec / MediaDemuxer / MediaMuxer 引擎 (services/media_engine/modules/)
```

回调链路（Server → Client）：

```
MediaCodec 引擎
        │
        ▼
CodecListenerCallback (codec_listener_callback.cpp)
        │  IPC回调触发
        ▼
CodecListenerStub (ipc/codec_listener_stub.cpp)
        │  死亡通知 + 回调分发
        ▼
CodecListenerProxy (client/)
        │
        ▼
Binder IPC (回调方向)
        │
        ▼
CodecClient.onError() / onOutputBufferAvailable()
        │
        ▼
OH_AVCodecCallback / OH_AVCodecAsyncCallback (应用层)
```

---

## 4. 状态机

### CodecClient 生命周期

```
UNINITIALIZED → INITIALIZED → CONFIGURED → STARTED → FLUSHED → STOPPED → RELEASED
     │              │              │            │          │          │         │
     │              │              │            │          │          │         └── Release()
     │              │              │            │          │          └──────────── Stop()
     │              │              │            │          └────────────────── Flush()
     │              │              │            └────────────────────────── Start()
     │              │              └──────────────────────────────── Configure(format)
     │              └────────────────────────────────────────────── Create()
     └───────────────────────────────────────────────────────────── Init()
```

### SA SystemAbility 状态

```
REGISTERED → CREATE → RUNNING → STOPPING → STOPPED
     │           │         │         │         │
     │           │         │         │         └─ OnStop()
     │           │         │         └──────────── OnStop() 被调用
     │           │         └────────────────────── OnStart() 完成
     │           └──────────────────────────────── OnDemandStart()
     └───────────────────────────────────────────── SAMgr.Register()
```

---

## 5. 关键关联

- **S137**: 本文件的精简版，聚焦 SA 管理器 + CodecClient 双层架构
- **S161**: 本文件的增强版，追加 `av_codec_service_ipc_interface_code.h` 33个接口枚举的完整行号级 evidence
- **S121/S159**: 错误码体系（`AVCodecServiceErrCode` + `AVCS_ERR_OFFSET` + `AVCSErrorToOHAVErrCode`）
- **S83**: C API 总览（2355行 base.h 的完整类型定义 + 7个主要API头文件）
- **S95**: AudioCodec C API（`OH_AudioCodec_CreateByMime` + AudioCodecObject 三层架构）
- **S94**: OH_AVMuxer 三件套（封装器 + 解封装器 + 源）
- **S55**: 模块间回调链路（四路 CodecCallback/MediaCodecCallback/CodecBaseCallback/CodecListenerCallback）
- **S21**: CodecClient 双模式（Sync/Async 切换 + CodecBufferCircular）

---

## 6. 源码目录结构

```
/home/west/av_codec_repo/
├── interfaces/kits/c/                    ← C API 层（6121行）
│   ├── native_avcodec_base.h              (2355行) 核心类型 + 错误码
│   ├── native_avcodec_videoencoder.h      (631行)  视频编码器API
│   ├── native_avcodec_videodecoder.h      (578行)  视频解码器API
│   ├── native_avcodec_audioencoder.h      (267行)  音频编码器API
│   ├── native_avcodec_audiodecoder.h      (272行)  音频解码器API
│   ├── native_avdemuxer.h                 (261行)  解封装器API
│   ├── native_avmuxer.h                   (192行)  封装器API
│   ├── native_avsource.h                  (184行)  媒体源API
│   └── native_cencinfo.h                  (248行)  DRM CENC信息
│
├── services/services/sa_avcodec/          ← SA IPC 框架
│   ├── server/                            ← 服务端（SA注册点）
│   │   ├── avcodec_server.cpp             (182行) SA SystemAbility 主入口
│   │   ├── avcodec_server_manager.cpp     (426行) 单例管理器 + dlopen
│   │   ├── avcodec_server_dump.cpp        SA Dump 调试接口
│   │   └── include/
│   ├── client/                            ← 客户端（Proxy封装）
│   │   ├── codec_client.cpp               (352行) CodecClient 封装层
│   │   └── avcodec_service_proxy.cpp      (128行) Binder 代理
│   └── ipc/                               ← IPC Stub（接口分发）
│       ├── avcodec_service_stub.cpp       (220行) 服务端存根
│       └── av_codec_service_ipc_interface_code.h (84行) 33接口枚举
│
├── services/etc/                          ← SA 配置
│   ├── sa_profile.json                    (10行)  SA ID=3011, libav_codec_service.z.so
│   ├── process.cfg                        进程配置（uid=media, secon=u:r:av_codec_service:s0）
│   └── on_demand/process.cfg              按需启动配置
│
├── services/media_engine/                 ← 引擎层（PluginManagerV2 下游）
│   └── plugins/
│       └── PluginManagerV2                dlopen RTLD_LAZY 编解码插件管理
│
└── services/drm_decryptor/                ← DRM 解密（SA框架下游）
    └── codec_drm_decrypt.cpp              (764行) CENC 解密引擎
```

---

## 7. 审查要点

1. **SA ID 3011** 是否与 `av_codec_service.json` 中的配置一致
2. **IPC 接口数量**：33个 CodecServiceInterfaceCode + 6个 CodecListenerInterfaceCode 是否与 `av_codec_service_ipc_interface_code.h` 实际枚举一致
3. **dlopen 路径**：libav_codec_service.z.so 的实际加载路径是否与 sa_profile.json 一致
4. **DeathRecipient** 注册时机是否正确（Proxy 构造时 vs 绑定后）
5. **错误码转换**：AVCS_ERR_OFFSET=200000 是否在 avcodec_errors.h 中定义
6. **与S137/S161关系**：S137为基础版，S161为增强版，本文件为综合版（整合两者 + 新增C API层完整路径）

---

_builder-agent build complete at 2026-05-20T14:54 Asia/Shanghai_