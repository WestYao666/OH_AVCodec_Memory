---
id: MEM-ARCH-AVCODEC-S1
title: codec_server.cpp 所承载的能力、插件与类上下文
scope: [AVCodec, Core, Server]
status: draft
created: 2026-04-21
updated: 2026-04-21
evidence_sources:
  - https://gitcode.com/openharmony/multimedia_av_codec
  - local_repo: /home/west/av_codec_repo
---

# MEM-ARCH-AVCODEC-S1

> **codec_server.cpp** — AVCodec 服务的核心类实例载体

## 1. 职责定位

`CodecServer`（`services/services/codec/server/video/codec_server.cpp`）是 **AVCodec 模块的视频编解码服务实例容器**，不是独立进程，也不是 SA（System Ability）本身。它的核心定位：

| 职责 | 说明 |
|------|------|
| Codec 实例生命周期管理 | 每一路编解码（encode/decode）对应一个独立的 `CodecServer` 实例 |
| 插件选择与初始化 | 根据 codec name 或 MIME 类型，通过 `CodecFactory` 选择对应插件（软编/硬编） |
| 数据流编排 | 管理输入/输出缓冲区、Surface 模式、回调分发 |
| 状态机维护 | 维护 `UNINITIALIZED→INITIALIZED→CONFIGURED→RUNNING→FLUSHED/END_OF_STREAM→ERROR` 状态 |
| 增值特性注入 | 可选注入 TemporalScalability、PostProcessing、SmartFluencyDecoding 等特性 |

> **关键区分**：`CodecServer` 是实例级（per-codec），而 SA 服务注册/进程管理由 `CodecServiceStub`（`codec_service_stub.cpp`）处理。

---

## 2. 类上下文与成员结构

### 2.1 核心成员

```
CodecServer 类成员（按功能分组）

生命周期与状态
├── status_ : CodecStatus                // UNINITIALIZED|INITIALIZED|CONFIGURED|RUNNING|FLUSHED|EOS|ERROR
├── codecBase_ : shared_ptr<CodecBase>   // ⭐ 实际插件实例，编解码逻辑的委托对象
├── codecBaseCb_ : shared_ptr<CodecBaseCallback>  // CodecBase→CodecServer 的回调桥接
├── codecType_ : AVCodecType             // VIDEO_ENCODER / VIDEO_DECODER / AUDIO_xxx
├── codecName_ : string                  // 具体插件名，如 "avcdecoder" / "h265decoder_venc"
├── codecMime_ : string                  // MIME 类型，如 "video/avc"
└── instanceId_ : int32_t                // 实例唯一 ID

编解码插件工厂
├── CodecFactory::Instance()             // 单例工厂，根据 codec name 加载对应 CodecBase 插件
│   ├── FCodecLoader  → libfcodec.z.so   (软件编解码)
│   ├── HCodecLoader  → libhcodec.z.so   (硬件编解码)
│   ├── HevcDecoderLoader                 (HEVC 硬件解码)
│   └── AvcEncoderLoader                  (AVC 硬件编码)
└── CodecListCore / CodecAbilitySingleton  // 能力查询：MIME→CodecName 映射

输入/输出管理
├── videoCb_ : shared_ptr<MediaCodecCallback>  // 上层回调（应用侧）
├── inputParamTask_ : shared_ptr<TaskThread>  // 输入参数异步处理线程
├── releaseBufferTask_ : shared_ptr<TaskThread> // Surface 模式输出缓冲区释放线程
└── outPtsMap_ : unordered_map<uint32_t, int64_t>  // 输出 PTS 映射

视频特定能力
├── temporalScalability_ : shared_ptr<TemporalScalability> // 时域可分级（SVC）
├── postProcessing_ : unique_ptr<DynamicPostProcessing>     // 后处理（视频解码+Surface 模式）
├── framerateCalculator_ : shared_ptr<FramerateCalculator> // 帧率计算（用于 DFX）
├── isSurfaceMode_ : bool    // 是否 Surface 输入/输出模式
├── isCreateSurface_ : bool   // 是否由 CodecServer 创建 Surface
├── isLpp_ : bool             // Low-Power Player 模式
└── scenario_ : CodecScenario  // 编码场景（普通/低延迟/屏幕录制等）

DRM 相关
├── drmDecryptor_ : shared_ptr<CodecDrmDecrypt>  // DRM 解密（CENC）
└── decryptVideoBufs_ : unordered_map<uint32_t, DrmDecryptVideoBuf>  // DRM 缓冲映射

智能解码（可选特性，SFD_ENABLED）
└── smartFluencyDecoding_ : unique_ptr<SFD::SmartFluencyDecoding>
```

### 2.2 CodecServer 状态机

```
UNINITIALIZED
    │ Init() [by name or by MIME]
    ▼
INITIALIZED
    │ Configure(format)
    ▼
CONFIGURED
    │ Start()
    ▼
RUNNING ◄────────────────┐
    │ Flush()            │
    ▼                    │
FLUSHED                  │
    │ Start() ──────────┘
    │
    │ NotifyEos() / 编码器输出 EOS
    ▼
END_OF_STREAM
    │ Reset() / Release()
    ▼
ERROR / UNINITIALIZED
```

**源码证据**：`codec_server.h` 行 40-48
```cpp
enum CodecStatus {
    UNINITIALIZED = 0,
    INITIALIZED,
    CONFIGURED,
    RUNNING,
    FLUSHED,
    END_OF_STREAM,
    ERROR,
};
```

---

## 3. 插件加载机制（三层工厂模式）

### 3.1 第一层：CodecFactory（按名称实例化）

```
CodecFactory::CreateCodecByName(codecName)
    │
    ├── CodecListCore::FindCodecType(name)  // 查询 name→CodecType 映射
    │
    ├── CodecType::AVCODEC_HCODEC     → HCodecLoader::CreateByName(name)
    │                                    加载 libhcodec.z.so（HDI 硬件编解码）
    ├── CodecType::AVCODEC_VIDEO_CODEC → FCodecLoader::CreateByName(name)
    │                                    加载 libfcodec.z.so（软件编解码）
    ├── CodecType::AVCODEC_VIDEO_HEVC_DECODER → HevcDecoderLoader::CreateByName(name)
    ├── CodecType::AVCODEC_VIDEO_AVC_ENCODER  → AvcEncoderLoader::CreateByName(name)
    └── CodecType::AVCODEC_VIDEO_AV1_DECODER  → Av1DecoderLoader::CreateByName(name)
```

**源码证据**：`codec_factory.cpp` 行 49-83
```cpp
std::shared_ptr<CodecBase> CodecFactory::CreateCodecByName(const std::string &name)
{
    std::shared_ptr<CodecListCore> codecListCore = std::make_shared<CodecListCore>();
    CodecType codecType = codecListCore->FindCodecType(name);
    std::shared_ptr<CodecBase> codec = nullptr;
    switch (codecType) {
        case CodecType::AVCODEC_HCODEC:
            codec = HCodecLoader::CreateByName(name);
            break;
        case CodecType::AVCODEC_VIDEO_CODEC:
            codec = FCodecLoader::CreateByName(name);
            break;
        // ...
    }
    return codec;
}
```

### 3.2 第二层：各 Loader（dlopen 动态库）

以 `FCodecLoader` 为例：

```
FCodecLoader::CreateByName(name)
    │
    ├── dlopen("libfcodec.z.so", RTLD_NOW)
    ├── dlsym("CreateFCodecByName") → CreateFCodecByName(name, codec)
    └── 返回 shared_ptr<CodecBase>(codec, deleter)
         其中 deleter 会 DecStrongRef() 并在引用计数归零时 CloseLibrary()
```

**源码证据**：`fcodec_loader.cpp` 行 21-47
```cpp
const char *FCODEC_LIB_PATH = "libfcodec.z.so";
const char *FCODEC_CREATE_FUNC_NAME = "CreateFCodecByName";
const char *FCODEC_GETCAPS_FUNC_NAME = "GetFCodecCapabilityList";

std::shared_ptr<CodecBase> FCodecLoader::CreateByName(const std::string &name)
{
    FCodecLoader &loader = GetInstance();
    std::lock_guard<std::mutex> lock(loader.mutex_);
    CHECK_AND_RETURN_RET_LOG(loader.Init() == AVCS_ERR_OK, nullptr, ...);
    noDeleterPtr = loader.Create(name).get();  // dlopen + dlsym
    ++(loader.fcodecCount_);
    // deleter: DecStrongRef() + CloseLibrary() 当引用计数归零
}
```

### 3.3 第三层：CodecBase（插件抽象基类）

所有编解码插件均实现 `CodecBase` 抽象接口：

```cpp
// codecbase.h
class CodecBase {
    virtual int32_t Configure(const Format &format) = 0;
    virtual int32_t Start() = 0;
    virtual int32_t Stop() = 0;
    virtual int32_t Flush() = 0;
    virtual int32_t Reset() = 0;
    virtual int32_t Release() = 0;
    virtual int32_t SetParameter(const Format& format) = 0;
    virtual int32_t GetOutputFormat(Format &format) = 0;
    virtual int32_t ReleaseOutputBuffer(uint32_t index) = 0;
    // ...
};
```

---

## 4. 实例初始化路径（两种模式）

### 4.1 按 Codec Name（显式指定）

```
CodecServer::Init(type=VIDEO_DECODER, isMimeType=false, name="avcdecoder")
    → CodecServer::InitByName(name="avcdecoder")
      → CodecFactory::Instance().CreateCodecByName("avcdecoder")
        → 查 CodecListCore::FindCodecType("avcdecoder") → FCodecLoader
        → FCodecLoader::CreateByName("avcdecoder") → shared_ptr<CodecBase>
      → codecBase_->Init(callerInfo)
```

**源码证据**：`codec_server.cpp` 行 157-166
```cpp
int32_t CodecServer::InitByName(const std::string &codecName, Meta &callerInfo)
{
    codecBase_ = CodecFactory::Instance().CreateCodecByName(codecName);
    if (codecBase_ == nullptr) {
        return AVCS_ERR_NO_MEMORY;
    }
    codecName_ = codecName;
    auto ret = codecBase_->Init(callerInfo);
    return ret;
}
```

### 4.2 按 MIME Type（自动选择）

```
CodecServer::Init(type=VIDEO_DECODER, isMimeType=true, name="video/avc")
    → CodecServer::InitByMime(type, codecMime="video/avc")
      → CodecFactory::Instance().GetCodecNameArrayByMime(type, "video/avc")
        → CodecListCore::FindCodecNameArray(AVCODEC_TYPE_VIDEO_DECODER, "video/avc")
        → 返回 ["avcdecoder", "avcdecoder.secure"] 等
      → 遍历 nameArray，依次 InitByName，直到成功
```

**源码证据**：`codec_server.cpp` 行 172-188
```cpp
int32_t CodecServer::InitByMime(const AVCodecType type, const std::string &codecMime, Meta &callerInfo)
{
    auto nameArray = CodecFactory::Instance().GetCodecNameArrayByMime(type, codecMime);
    for (const auto &name : nameArray) {
        ret = InitByName(name, callerInfo);
        CHECK_AND_CONTINUE_LOG_WITH_TAG(ret == AVCS_ERR_OK, "Skip init failure. name: %{public}s", name.c_str());
        break;
    }
    return ret;
}
```

---

## 5. 生命周期关键方法

### 5.1 Start()

```
CodecServer::Start()
    │
    ├── isLocalReleaseMode_ ? → 启动 releaseBufferTask_（Surface 模式）
    ├── temporalScalability_ && isCreateSurface_ && !isSetParameterCb_ ? → StartInputParamTask()
    ├── StartPostProcessing()
    ├── codecBase_->Start()
    ├── StatusChanged(RUNNING)
    ├── CodecStartEventWrite(codecDfxInfo)  // DFX 事件
    ├── OnInstanceMemoryUpdateEvent()
    └── OnInstanceEncodeBeginEvent()
```

### 5.2 Stop()

```
CodecServer::Stop()
    │
    ├── SetFreeStatus(true)
    ├── isLocalReleaseMode_ ? → 通知 releaseBufferTask_ 停止
    ├── temporalScalability_ ? → inputParamTask_->Stop()
    ├── StopPostProcessing()
    ├── codecBase_->Stop()
    ├── SurfaceTools::CleanCache()  // 如果 pushBlankBufferOnShutdown_
    └── CodecStopEventWrite()  // DFX 事件
```

### 5.3 Release()

```
CodecServer::Release()
    │
    ├── releaseBufferTask_ ? → releaseBufferTask_->Stop()
    ├── postProcessing_ ? → ReleasePostProcessing()
    ├── codecBase_->Release()
    └── codecBase_ = nullptr; codecBaseCb_ = nullptr
```

---

## 6. IPC 调用链路

```
Native API层（应用进程）
    │
AVCodec::AVCodec（framework/native）
    │ CreateByName/Mime
    ▼
CodecServiceStub::Create(instanceId)     [ipc/codec_service_stub.cpp]
    │ 分配 instanceId
    ▼
CodecServer::Create(instanceId)           [server/video/codec_server.cpp]
    │ Init() → Configure() → Start()
    ▼
CodecBase（插件层，实际编解码）          [engine/codec/video/]
    │
    ├── FCodecLoader → libfcodec.z.so    (软件)
    └── HCodecLoader → libhcodec.z.so    (硬件/HDI)

返回路径：
CodecBase → CodecBaseCallback → CodecServer（状态更新/回调分发）→ CodecServiceStub → CodecServiceProxy → 应用
```

---

## 7. 能力查询体系

```
CodecAbilitySingleton（单例）
    │ RegisterCapabilityArray(capaArray, codecType)
    │ 存放：capabilityDataArray_, mimeCapIdxMap_, nameCodecTypeMap_
    │
    ├── GetCapabilityByName(codecName) → CapabilityData
    ├── GetCodecNameArrayByMime(type, mime) → vector<string>
    └── GetCapabilityArray() → 所有已注册能力

CodecListCore
    ├── FindCodecNameArray(type, mime)  // MIME → [codecNames]
    ├── FindCodecType(name)             // codecName → CodecType
    └── IsXxxCapSupport(format, cap)   // 检查分辨率/码率/帧率是否支持
```

---

## 8. 关键文件索引

| 文件 | 作用 |
|------|------|
| `services/services/codec/server/video/codec_server.cpp` | CodecServer 主类实现（~1800行） |
| `services/services/codec/server/video/codec_server.h` | CodecServer 类声明 |
| `services/services/codec/server/video/codec_factory.cpp` | CodecFactory 插件工厂 |
| `services/services/codec/server/video/codec_factory.h` | CodecFactory 单例声明 |
| `services/engine/codec/include/video/fcodec_loader.cpp` | 软件编解码插件加载器 |
| `services/engine/codec/include/video/hcodec_loader.cpp` | 硬件编解码插件加载器 |
| `services/engine/codec/include/video/video_codec_loader.h` | 加载器基类（dlopen 封装） |
| `services/engine/base/include/codecbase.h` | CodecBase 抽象基类 |
| `services/engine/codeclist/codec_ability_singleton.cpp` | 能力单例（name→能力映射） |
| `services/engine/codeclist/codeclist_core.cpp` | 能力查询核心逻辑 |
| `services/services/codec/ipc/codec_service_stub.cpp` | IPC 入口，每实例创建 CodecServer |
| `services/include/i_codec_service.h` | ICodecService 接口声明 |
| `services/services/codec/server/video/post_processing/` | 后处理模块（解码+Surface 模式） |
| `services/services/codec/server/video/features/` | 增值特性（SFD/TemporalScalability） |

---

## 9. 与旧版本草案的差异（旧版有误，此版已更正）

| 旧版（错误） | 新版（基于代码） |
|-------------|----------------|
| codec_server 是独立进程/SA | CodecServer 是**实例类**，`CodecServiceStub`才是IPC桩 |
| 插件目录 `/vendor/lib/codec/` + `codec_plugins.json` | 插件通过编译时链接的 Loader 类加载，dlopen 对应 .z.so |
| `CodecServerAbility` / `CodecPluginManager` 类 | 实际类为 `CodecFactory` + 各 `Loader` |
| SA 发布流程 | 实际是 `CodecServiceStub::Create()` 为每个 IPC 连接创建 CodecServer 实例 |

---

*本草案基于 `multimedia_av_codec` 仓库真实代码分析，覆盖 `codec_server.cpp` 的实例载体角色、插件加载三层架构、生命周期管理*
