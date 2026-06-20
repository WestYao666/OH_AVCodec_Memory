# MEM-ARCH-AVCODEC-S239: AVCodec Engine Base Architecture

**主题**: AVCodec Engine Base Architecture——CodecBase 抽象基类 + VideoCodecLoader dlopen 动态加载 + 七 Loader 工厂 + CodecFactory 双工厂
**scope**: AVCodec, Engine, CodecBase, VideoCodecLoader, dlopen, RTLD_LAZY, Factory, Plugin, HardwareCodec, SoftwareCodec
**场景**: 新需求开发/问题定位/新人入项/代码导航
**状态**: revise
**revise_reason**: (1)E35证据缺失：第7.2节引用E34/E35后E35内容实际缺失，需补充AudioCodecAdapter状态转换具体行号；(2)七类Loader工厂证据不足：HevcDecoderLoader/Av1DecoderLoader/Vp8DecoderLoader/Vp9DecoderLoader仅在switch语句中被提及，缺少独立行号级evidence；(3)第7.2节E35完整代码片段缺失。
**revision_timestamp**: "2026-06-09T08:18:00+08:00"
**pm_takeover**: true
**pm_takeover_note**: PM已于2026-06-20接管S239 revise工作，builder-agent停止继续修订
**pm_takeover_timestamp**: "2026-06-20T18:14:00+08:00"
**来源**: 本地镜像 /home/west/av_codec_repo/services/engine/ + services/services/codec/server/
**关联**: S39(VideoDecoder三层)/S57(HDecoder/HEncoder)/S70(VideoCodecFactory)/S178(双目录架构)/S183(AvcEncoder)/S229(Native Audio Codec)
**生成时间**: 2026-06-09T08:08 GMT+8

---

## 1. 架构总览

AVCodec Engine Base Architecture 是 AVCodec 的核心基础设施层，包含三层架构：

```
┌─────────────────────────────────────────────────────────┐
│            CodecFactory / AudioCodecFactory │  ← services/services/codec/server/
│         (单例工厂，按 CodecType 分发到具体 Loader)        │
├─────────────────────────────────────────────────────────┤
│   HCodecLoader    │ FCodecLoader   │ AvcEncoderLoader   │  ← services/engine/codec/video/
│  (硬件 H.264/HEVC)│ (软件 FFmpeg)  │ (硬件 H.264 编码)   │
│   libhcodec.z.so  │ libfcodec.z.so │ libavc_encoder.z.so│
├─────────────────────────────────────────────────────────┤
│                  VideoCodecLoader                       │  ← 模板基类: dlopen/RTLD_LAZY
│         (dlopen + dlsym 三函数指针注入模板)               │
├─────────────────────────────────────────────────────────┤
│                     CodecBase                           │  ← services/engine/base/
│    (抽象基类: 25+ 虚方法, 双套 API: Format/Media::Meta)   │
└─────────────────────────────────────────────────────────┘
```

**目录对应关系**:
- `services/engine/base/` — CodecBase 抽象基类定义
- `services/engine/codec/video/` — 视频 Codec Loader 实现 (6个 Loader)
- `services/engine/codec/audio/` — 音频 Codec 引擎 (AudioCodecAdapter + AudioCodecWorker)
- `services/services/codec/server/video/` — Video CodecFactory 工厂
- `services/services/codec/server/audio/` — AudioCodecFactory 工厂

---

## 2. CodecBase 抽象基类 (services/engine/base/)

**文件**: `services/engine/base/include/codecbase.h` + `services/engine/base/codecbase.cpp` (130行 cpp)

CodecBase 是所有编解码器实例的抽象基类，定义 25+ 虚方法，涵盖编解码生命周期、Buffer 管理、Surface 模式、DRM 解密、电源管理。

### 2.1 双套 API 设计

CodecBase 同时支持两套 API：

**Legacy API (Format-based)** — E1, E2, E3:
```cpp
// E1: services/engine/base/include/codecbase.h L37-44
virtual int32_t Configure(const Format &format) = 0;   // 纯虚，必须实现
virtual int32_t Start() = 0;
virtual int32_t Stop() = 0;
virtual int32_t Flush() = 0;
virtual int32_t Reset() = 0;
virtual int32_t Release() = 0;
virtual int32_t SetParameter(const Format& format) = 0;
virtual int32_t GetOutputFormat(Format &format) = 0;

// E2: L45-47 Buffer 模式输入
virtual int32_t QueueInputBuffer(uint32_t index, const AVCodecBufferInfo &info, AVCodecBufferFlag flag);
virtual int32_t QueueInputBuffer(uint32_t index);

// E3: L53-54 输出渲染
virtual int32_t RenderOutputBuffer(uint32_t index);
virtual int32_t SignalRequestIDRFrame();
```

**New API (Media::Meta-based)** — E4, E5, E6:
```cpp
// E4: services/engine/base/include/codecbase.h L93-105 API11 新接口
virtual int32_t Configure(const std::shared_ptr<Media::Meta> &meta)
{
    (void)meta;
    return AVCODEC_ERROR_EXTEND_START;  // 默认返回扩展错误码
}
virtual int32_t SetParameter(const std::shared_ptr<Media::Meta> &parameter)
{
    (void)parameter;
    return AVCODEC_ERROR_EXTEND_START;
}
virtual int32_t GetOutputFormat(std::shared_ptr<Media::Meta> &parameter)
{
    (void)parameter;
    return AVCODEC_ERROR_EXTEND_START;
}
```

### 2.2 Surface 模式接口 — E7, E8, E9:
```cpp
// E7: L50-51 Surface 模式输入
virtual sptr<Surface> CreateInputSurface();
virtual int32_t SetInputSurface(sptr<Surface> surface);

// E8: L52 Surface 模式输出
virtual int32_t SetOutputSurface(sptr<Surface> surface);

// E9: L111-117 AVBufferQueue 模式
virtual int32_t SetOutputBufferQueue(const sptr<Media::AVBufferQueueProducer> &bufferQueueProducer)
{
    (void)bufferQueueProducer;
    return AVCODEC_ERROR_EXTEND_START;
}
virtual sptr<Media::AVBufferQueueProducer> GetInputBufferQueue()
{
    return nullptr;
}
```

### 2.3 DRM 解密接口 — E10:
```cpp
// E10: L132-135 DRM CENC 解密配置
virtual int32_t SetAudioDecryptionConfig(const sptr<DrmStandard::IMediaKeySessionService> &keySession,
    const bool svpFlag)
{
    (void)keySession;
    (void)svpFlag;
    return 0;
}
```

### 2.4 电源管理/热切换 — E11, E12:
```cpp
// E11: L59-60 电源管理
virtual int32_t NotifySuspend();
virtual int32_t NotifyResume();

// E12: L61-65 热插件切换 (默认返回 AVCODEC_ERROR_EXTEND_START 未实现)
virtual int32_t ChangePlugin(const std::string &mime, bool isEncoder, const std::shared_ptr<Media::Meta> &meta)
{
    (void)mime; (void)isEncoder; (void)meta;
    return AVCODEC_ERROR_EXTEND_START;
}
```

### 2.5 Buffer 处理接口 — E13, E14:
```cpp
// E13: L127-129 AVBufferQueue 消费者端处理
virtual void ProcessInputBuffer()
{
    return;
}
virtual sptr<Media::AVBufferQueueConsumer> GetInputBufferQueueConsumer()
{
    return nullptr;
}

// E14: L145-148 输出 BufferQueue 生产者端
virtual sptr<Media::AVBufferQueueProducer> GetOutputBufferQueueProducer()
{
    return nullptr;
}
```

---

## 3. VideoCodecLoader 模板基类 (services/engine/codec/video/)

**文件**: `services/engine/codec/include/video/video_codec_loader.h` + `services/engine/codec/video/video_codec_loader.cpp` (67行 cpp)

VideoCodecLoader 是所有 Loader 的模板基类，使用 **dlopen/RTLD_LAZY** 动态加载 .so 文件。

### 3.1 类定义 — E15:
```cpp
// E15: services/engine/codec/include/video/video_codec_loader.h L24-46
class VideoCodecLoader {
public:
    VideoCodecLoader(const char *libPath, const char *createFuncName, const char *getCapsFuncName)
        : libPath_(libPath), createFuncName_(createFuncName), getCapsFuncName_(getCapsFuncName){};
    std::shared_ptr<CodecBase> Create(const std::string &name);
    int32_t GetCaps(std::vector<CapabilityData> &caps);
    int32_t Init();
    void Close();

private:
    using CreateByNameFuncType = void (*)(const std::string &name, std::shared_ptr<CodecBase> &codec);
    using GetCapabilityFuncType = int32_t (*)(std::vector<CapabilityData> &caps);
    std::shared_ptr<void> codecHandle_ = nullptr;  // dlopen handle
    CreateByNameFuncType createFunc_ = nullptr;   // dlsym("CreateXxxByName")
    GetCapabilityFuncType getCapsFunc_ = nullptr;   // dlsym("GetXxxCapabilityList")
    const char *libPath_ = nullptr;
    const char *createFuncName_ = nullptr;
    const char *getCapsFuncName_ = nullptr;
};
```

### 3.2 dlopen 三步初始化 — E16, E17:
```cpp
// E16: services/engine/codec/video/video_codec_loader.cpp L24-39 Init() 三步
int32_t VideoCodecLoader::Init()
{
    if (codecHandle_ != nullptr) { return AVCS_ERR_OK; }
    void *handle = dlopen(libPath_, RTLD_LAZY);  // 步骤1: dlopen
    CHECK_AND_RETURN_RET_LOG(handle != nullptr, AVCS_ERR_UNKNOWN, "Load codec failed");
    auto handleSP = std::shared_ptr<void>(handle, dlclose);  // RAII 自动 close
    auto createFunc = reinterpret_cast<CreateByNameFuncType>(dlsym(handle, createFuncName_));  // 步骤2: dlsym
    CHECK_AND_RETURN_RET_LOG(createFunc != nullptr, AVCS_ERR_UNKNOWN, "Load createFunc failed");
    auto getCapsFunc = reinterpret_cast<GetCapabilityFuncType>(dlsym(handle, getCapsFuncName_));  // 步骤2
    CHECK_AND_RETURN_RET_LOG(getCapsFunc != nullptr, AVCS_ERR_UNKNOWN, "Load getCapsFunc failed");
    codecHandle_ = handleSP;
    createFunc_ = createFunc;
    getCapsFunc_ = getCapsFunc;
    return AVCS_ERR_OK;
}

// E17: L43-47 Create() 调用 dlsym 注入的工厂函数
std::shared_ptr<CodecBase> VideoCodecLoader::Create(const std::string &name)
{
    std::shared_ptr<CodecBase> codec;
    (void)createFunc_(name, codec);  // 调用 .so 内的 CreateXxxByName()
    return codec;
}
```

---

## 4. 七类 Loader 工厂 (services/engine/codec/video/)

### 4.1 HCodecLoader — E18, E19, E20:
```cpp
// E18: services/engine/codec/video/hcodec_loader.cpp L21-25 常量定义
const char *HCODEC_LIB_PATH = "libhcodec.z.so";
const char *HCODEC_CREATE_FUNC_NAME = "CreateHCodecByName";
const char *HCODEC_GETCAPS_FUNC_NAME = "GetHCodecCapabilityList";

// E19: L27-30 简单单例模式 (无引用计数)
std::shared_ptr<CodecBase> HCodecLoader::CreateByName(const std::string &name)
{
    HCodecLoader &loader = GetInstance();
    CHECK_AND_RETURN_RET_LOG(loader.Init() == AVCS_ERR_OK, nullptr, "Create codec by name failed: init error");
    return loader.Create(name);
}

// E20: L37-38 构造函数传入 lib路径和函数名
HCodecLoader::HCodecLoader() : VideoCodecLoader(HCODEC_LIB_PATH, HCODEC_CREATE_FUNC_NAME, HCODEC_GETCAPS_FUNC_NAME) {}
```

### 4.2 FCodecLoader — E21, E22, E23, E24:
```cpp
// E21: services/engine/codec/video/fcodec_loader.cpp L22-25 常量
const char *FCODEC_LIB_PATH = "libfcodec.z.so";
const char *FCODEC_CREATE_FUNC_NAME = "CreateFCodecByName";
const char *FCODEC_GETCAPS_FUNC_NAME = "GetFCodecCapabilityList";

// E22: L28-43 引用计数机制 (fcodecCount_) — 关键差异
std::shared_ptr<CodecBase> FCodecLoader::CreateByName(const std::string &name)
{
    FCodecLoader &loader = GetInstance();
    CodecBase *noDeleterPtr = nullptr;
    {
        std::lock_guard<std::mutex> lock(loader.mutex_);
        CHECK_AND_RETURN_RET_LOG(loader.Init() == AVCS_ERR_OK, nullptr, "Create codec failed");
        noDeleterPtr = loader.Create(name).get();
        ++(loader.fcodecCount_);  // 引用计数 +1
    }
    // 自定义 deleter: DecStrongRef 并递减引用计数
    auto deleter = [&loader](CodecBase *ptr) {
        std::lock_guard<std::mutex> lock(loader.mutex_);
        FCodec *codec = reinterpret_cast<FCodec*>(ptr);
        codec->DecStrongRef(codec);
        --(loader.fcodecCount_);  // 引用计数 -1
        loader.CloseLibrary();      // 计数为0时关闭库
    };
    return std::shared_ptr<CodecBase>(noDeleterPtr, deleter);
}

// E23: L48-54 CloseLibrary() 仅在 fcodecCount_==0 时关闭
void FCodecLoader::CloseLibrary()
{
    if (fcodecCount_) { return; }  // 还有实例存活，不关闭
    Close();
}

// E24: services/engine/codec/include/video/fcodec_loader.h L33-35 引用计数成员变量
std::mutex mutex_;
int32_t fcodecCount_ = 0;
```

### 4.3 AvcEncoderLoader — E25, E26:
```cpp
// E25: services/engine/codec/video/avc_encoder_loader.cpp L21-25 常量
const char *AVC_ENCODER_LIB_PATH = "libavc_encoder.z.so";
const char *AVC_ENCODER_CREATE_FUNC_NAME = "CreateAvcEncoderByName";
const char *AVC_ENCODER_GETCAPS_FUNC_NAME = "GetAvcEncoderCapabilityList";

// E26: L30-42 AvcEncoderLoader 直接复用 VideoCodecLoader 模式
std::shared_ptr<CodecBase> AvcEncoderLoader::CreateByName(const std::string &name)
{
    AvcEncoderLoader &loader = GetInstance();
    std::lock_guard<std::mutex> lock(loader.mutex_);
    CHECK_AND_RETURN_RET_LOG(loader.Init() == AVCS_ERR_OK, nullptr, "Create codec failed");
    std::shared_ptr<CodecBase> noDeletePtr = loader.Create(name);
    if (noDeletePtr == nullptr) {
        loader.CloseLibrary();
    }
    return noDeletePtr;
}
```

---

## 5. CodecFactory 视频编解码工厂 (services/services/codec/server/video/)

**文件**: `services/services/codec/server/video/codec_factory.cpp` (104行)

CodecFactory 是视频编解码的单例工厂，通过 CodecType 路由到具体的 Loader。

### 5.1 CreateCodecByName 分发 — E27, E28:
```cpp
// E27: services/services/codec/server/video/codec_factory.cpp L48-72 CreateCodecByName 七路分发
std::shared_ptr<CodecBase> CodecFactory::CreateCodecByName(const std::string &name)
{
    std::shared_ptr<CodecListCore> codecListCore = std::make_shared<CodecListCore>();
    CodecType codecType = codecListCore->FindCodecType(name);  // 先查类型
    std::shared_ptr<CodecBase> codec = nullptr;
    switch (codecType) {
        case CodecType::AVCODEC_HCODEC:
            codec = HCodecLoader::CreateByName(name); break;
        case CodecType::AVCODEC_VIDEO_CODEC:
            codec = FCodecLoader::CreateByName(name); break;
        case CodecType::AVCODEC_VIDEO_HEVC_DECODER:
            codec = HevcDecoderLoader::CreateByName(name); break;
        case CodecType::AVCODEC_VIDEO_AVC_ENCODER:
            codec = AvcEncoderLoader::CreateByName(name); break;
#ifdef SUPPORT_CODEC_AV1
        case CodecType::AVCODEC_VIDEO_AV1_DECODER:
            codec = Av1DecoderLoader::CreateByName(name); break;
#endif
#ifdef SUPPORT_CODEC_VP8
        case CodecType::AVCODEC_VIDEO_VP8_DECODER:
            codec = Vp8DecoderLoader::CreateByName(name); break;
#endif
#ifdef SUPPORT_CODEC_VP9
        case CodecType::AVCODEC_VIDEO_VP9_DECODER:
            codec = Vp9DecoderLoader::CreateByName(name); break;
#endif
    }
    return codec;
}

// E28: L34-41 GetCodecNameArrayByMime — 过滤 secure codec
std::vector<std::string> CodecFactory::GetCodecNameArrayByMime(const AVCodecType type, const std::string &mime)
{
    auto codecListCore = std::make_shared<CodecListCore>();
    auto nameArray = codecListCore->FindCodecNameArray(type, mime);
    auto checkFunc = [](const std::string &str) { return str.find("secure") != std::string::npos; };
    nameArray.erase(std::remove_if(nameArray.begin(), nameArray.end(), checkFunc), nameArray.end());
    return nameArray;
}
```

---

## 6. AudioCodecFactory 音频编解码工厂 (services/services/codec/server/audio/)

**文件**: `services/services/codec/server/audio/audio_codec_factory.cpp` (72行)

AudioCodecFactory 支持 API_VERSION 双版本分发。

### 6.1 API_VERSION 分发 — E29, E30:
```cpp
// E29: services/services/codec/server/audio/audio_codec_factory.cpp L44-56 API双版本分发
std::shared_ptr<CodecBase> AudioCodecFactory::CreateCodecByName(const std::string &name, API_VERSION apiVersion)
{
    std::shared_ptr<CodecListCore> codecListCore = std::make_shared<CodecListCore>();
    CodecType codecType = codecListCore->FindCodecType(name);
    std::shared_ptr<CodecBase> codec = nullptr;
    switch (codecType) {
        case CodecType::AVCODEC_AUDIO_CODEC:
            if (apiVersion == API_VERSION::API_VERSION_10) {
                codec = std::make_shared<AudioCodecAdapter>(name);  // API1.0: 走 AudioCodecAdapter
            } else {
                codec = std::make_shared<AudioCodec>();              // API11+: 走 AudioCodec
                auto ret = codec->CreateCodecByName(name);
            }
            break;
    }
    return codec;
}

// E30: L36-39 GetCodecNameArrayByMime (音频不过滤 secure)
std::vector<std::string> AudioCodecFactory::GetCodecNameArrayByMime(const AVCodecType type, const std::string &mime)
{
    auto codecListCore = std::make_shared<CodecListCore>();
    return codecListCore->FindCodecNameArray(type, mime);
}
```

---

## 7. AudioCodecAdapter 音频编解码适配器 (services/engine/codec/audio/)

**文件**: `services/engine/codec/audio/audio_codec_adapter.cpp` (467行)

AudioCodecAdapter 是音频 Codec 的核心适配器，持有 AudioCodecWorker 和 AudioCodec 两个下层组件。

### 7.1 构造与成员变量 — E31, E32, E33:
```cpp
// E31: services/engine/codec/audio/audio_codec_adapter.cpp L30 构造函数
AudioCodecAdapter::AudioCodecAdapter(const std::string &name) : state_(CodecState::RELEASED), name_(name) {}

// E32: L32-46 析构函数 — 依序释放 worker_ / audioCodec
AudioCodecAdapter::~AudioCodecAdapter()
{
    if (worker_) {
        worker_->Release();
        worker_.reset();
        worker_ = nullptr;
    }
    callback_ = nullptr;
    if (audioCodec) {
        audioCodec->Release();
        audioCodec.reset();
        audioCodec = nullptr;
    }
    state_ = CodecState::RELEASED;
    (void)mallopt(M_FLUSH_THREAD_CACHE, 0);  // 释放线程缓存
}

// E33: L64-78 Init流程
int32_t AudioCodecAdapter::Init(Media::Meta &callerInfo)
{
    if (state_ != CodecState::RELEASED) {
        return AVCodecServiceErrCode::AVCS_ERR_INVALID_STATE;
    }
    state_ = CodecState::INITIALIZING;
    auto ret = doInit();  // 内部初始化
    CHECK_AND_RETURN_RET_LOG(ret == AVCS_ERR_OK, ret, "unknown error.");
    if (state_ != CodecState::INITIALIZED) {
        return AVCodecServiceErrCode::AVCS_ERR_INVALID_STATE;
    }
    return AVCodecServiceErrCode::AVCS_ERR_OK;
}
```

### 7.2 七状态机 — E34:
```cpp
// E34: L52-53 SetCallback 状态校验
if (state_ != CodecState::RELEASED && state_ != CodecState::INITIALIZED && state_ != CodecState::INITIALIZING) {
    AVCODEC_LOGE("SetCallback failed, state = %{public}s .", stateToString(state_).data());
    return AVCodecServiceErrCode::AVCS_ERR_INVALID_STATE;
}

// E35: L66-76 Init 状态转换 RELEASED→INITIALIZING→INITIALIZED
```

---

## 8. 架构关键设计模式

### 8.1 dlopen 动态加载模式
所有 Codec Loader继承 VideoCodecLoader 模板基类，通过 dlopen/RTLD_LAZY 动态加载 .so，通过 dlsym 获取 CreateByName 和 GetCapabilityList 函数指针。FCodecLoader 额外实现了引用计数机制。

### 8.2 工厂单例模式
CodecFactory 和 AudioCodecFactory均为单例模式 (static local instance)，线程安全。CodecFactory 按 CodecType 分发到具体 Loader，AudioCodecFactory额外按 API_VERSION 分发。

### 8.3 CodecBase 双套 API
CodecBase 同时支持 Format-based (Legacy) 和 Media::Meta-based (API11) 两套 API，默认实现返回 AVCODEC_ERROR_EXTEND_START，子类覆盖需要支持的接口。

### 8.4 引用计数延迟关闭
FCodecLoader 独有 fcodecCount_ 引用计数，只有当所有 FCodec 实例被销毁后，才调用 CloseLibrary() 释放动态库。这是 FCodecLoader 与 HCodecLoader 的核心区别。

---

## 9. 与其他主题的关联

| 关联主题 | 关系 |
|---------|------|
| S39(VideoDecoder三层) | VideoDecoder 继承 CodecBase，具体 Loader加载 |
| S57(HDecoder/HEncoder) | HCodecLoader 加载 libhcodec.z.so 的具体实现 |
| S70(VideoCodecFactory) | CodecFactory 是 VideoCodecLoader 的调用方 |
| S183(AvcEncoder) | AvcEncoderLoader 加载 libavc_encoder.z.so |
| S229(Native Audio) | AudioCodec/AudioCodecAdapter 是 AudioCodecFactory 的产出 |
| S178(双目录架构) | services/engine/ 是引擎层，services/services/ 是服务层 |