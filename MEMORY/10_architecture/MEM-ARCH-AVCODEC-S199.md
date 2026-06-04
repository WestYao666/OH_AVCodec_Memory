# MEM-ARCH-AVCODEC-S199: VideoCodecLoader 视频编解码器动态加载架构

> **状态**: draft  
> **主题**: VideoCodecLoader 视频编解码器动态加载架构——dlopen/RTLD_LAZY双函数指针注入与七类Loader工厂  
> **scope**: AVCodec, VideoCodecLoader, dlopen, RTLD_LAZY, CreateByName, GetCapabilityList, CodecBase, CodecFactory, FCodec, HevcDecoder, AvcEncoder, AV1, VP8, VP9, Hcodec, VideoCodec  
> **关联场景**: 新人入项/代码导航/动态库加载/Factory模式  
> **来源**: 基于 GitCode web_fetch 源码 + 本地镜像 `/home/west/av_codec_repo`  
> **生成时间**: 2026-06-04T18:25 Builder  
> **关联主题**: S178(双目录架构)/S183(AvcEncoder软件编码器)

---

## 1. 架构总览

VideoCodecLoader 是 AVCodec 引擎的视频编解码器**动态加载基座**，采用 dlopen + dlsym 实现运行时符号解析，支持 7 类独立 Loader 的工厂模式。

```
VideoCodecLoader（基座，67行cpp + 46行h）
    ├── dlopen(libPath_, RTLD_LAZY)        // 动态加载 .z.so
    ├── dlsym(createFuncName_)             // 解析 CreateByName 符号
    ├── dlsym(getCapsFuncName_)            // 解析 GetCapabilityList 符号
    └── std::shared_ptr<void> codecHandle_ // 自动析构时 dlclose

七类 Loader（各自单例）
    ├── FCodecLoader        → libfcodec.z.so        → CreateFCodecByName
    ├── HevcDecoderLoader   → libhevc_decoder.z.so  → CreateHevcDecoderByName
    ├── AvcEncoderLoader    → libavc_encoder.z.so   → CreateAvcEncoderByName
    ├── Vp8DecoderLoader     → libvpx_decoder.z.so   → CreateVpxDecoderByName
    ├── Vp9DecoderLoader     → (同VP8)                → CreateVpxDecoderByName
    ├── Av1DecoderLoader     → (待查)                 → (待查)
    └── HCodecLoader        → libhcodec.z.so         → CreateHCodecByName
```

---

## 2. VideoCodecLoader 基座（video_codec_loader.cpp, 67行）

### 2.1 Init() 动态加载（L22-43）

```cpp
// video_codec_loader.cpp L22-43
int32_t VideoCodecLoader::Init()
{
    if (codecHandle_ != nullptr) {
        return AVCS_ERR_OK;
    }
    void *handle = dlopen(libPath_, RTLD_LAZY);  // L27: RTLD_LAZY 延迟绑定
    CHECK_AND_RETURN_RET_LOG(handle != nullptr, AVCS_ERR_UNKNOWN, "Load codec failed: %{public}s", libPath_);
    auto handleSP = std::shared_ptr<void>(handle, dlclose);  // L29: shared_ptr 自动 dlclose
    auto createFunc = reinterpret_cast<CreateByNameFuncType>(dlsym(handle, createFuncName_));  // L31
    CHECK_AND_RETURN_RET_LOG(createFunc != nullptr, AVCS_ERR_UNKNOWN, "Load createFunc failed");
    auto getCapsFunc = reinterpret_cast<GetCapabilityFuncType>(dlsym(handle, getCapsFuncName_));  // L34
    CHECK_AND_RETURN_RET_LOG(getCapsFunc != nullptr, AVCS_ERR_UNKNOWN, "Load getCapsFunc failed");
    codecHandle_ = handleSP;
    createFunc_ = createFunc;
    getCapsFunc_ = getCapsFunc;
    return AVCS_ERR_OK;
}
```

**关键设计**：
- L27: `RTLD_LAZY` 延迟绑定，只在函数首次调用时才解析符号
- L29: `shared_ptr<void>(handle, dlclose)` — 自动引用计数关闭句柄
- L31-36: 双函数指针注入，保存 `createFunc_` 和 `getCapsFunc_`

### 2.2 Close() 释放资源（L45-52）

```cpp
// video_codec_loader.cpp L45-52
void VideoCodecLoader::Close()
{
    codecHandle_ = nullptr;     // 触发 shared_ptr dlclose
    createFunc_ = nullptr;
    getCapsFunc_ = nullptr;
}
```

### 2.3 Create() / GetCaps() 调用（L54-65）

```cpp
// video_codec_loader.cpp L54-65
std::shared_ptr<CodecBase> VideoCodecLoader::Create(const std::string &name)
{
    std::shared_ptr<CodecBase> codec;
    (void)createFunc_(name, codec);  // L56: 通过函数指针创建实例
    return codec;
}

int32_t VideoCodecLoader::GetCaps(std::vector<CapabilityData> &caps)
{
    return getCapsFunc_(caps);  // L63: 通过函数指针获取能力列表
}
```

---

## 3. VideoCodecLoader.h 模板定义（46行）

```cpp
// video_codec_loader.h L17-41
class VideoCodecLoader {
public:
    VideoCodecLoader(const char *libPath, const char *createFuncName, const char *getCapsFuncName)
        : libPath_(libPath), createFuncName_(createFuncName), getCapsFuncName_(getCapsFuncName){};

    std::shared_ptr<CodecBase> Create(const std::string &name);
    int32_t GetCaps(std::vector<CapabilityData> &caps);
    int32_t Init();
    void Close();

private:
    using CreateByNameFuncType = void (*)(const std::string &name, std::shared_ptr<CodecBase> &codec);  // L30
    using GetCapabilityFuncType = int32_t (*)(std::vector<CapabilityData> &caps);  // L31
    std::shared_ptr<void> codecHandle_ = nullptr;  // L33: .so 句柄
    CreateByNameFuncType createFunc_ = nullptr;    // L34: CreateByName 函数指针
    GetCapabilityFuncType getCapsFunc_ = nullptr;  // L35: GetCaps 函数指针
    const char *libPath_ = nullptr;
    const char *createFuncName_ = nullptr;
    const char *getCapsFuncName_ = nullptr;
};
```

---

## 4. 七类 Loader 工厂实现

### 4.1 FCodecLoader（fcodec_loader.cpp）—— 软件解码器工厂

```cpp
// fcodec_loader.cpp L34-47
std::shared_ptr<CodecBase> FCodecLoader::CreateByName(const std::string &name)
{
    FCodecLoader &loader = GetInstance();
    CodecBase *noDeleterPtr = nullptr;
    {
        std::lock_guard<std::mutex> lock(loader.mutex_);
        CHECK_AND_RETURN_RET_LOG(loader.Init() == AVCS_ERR_OK, nullptr, "Create codec by name failed: init error");
        noDeleterPtr = loader.Create(name).get();  // L40: 调用基座 Create
        ++(loader.fcodecCount_);                  // L41: 引用计数++
    }
    auto deleter = [&loader](CodecBase *ptr) {
        std::lock_guard<std::mutex> lock(loader.mutex_);
        FCodec *codec = reinterpret_cast<FCodec*>(ptr);
        codec->DecStrongRef(codec);
        --(loader.fcodecCount_);
        loader.CloseLibrary();  // L46: 引用归零时 Close
    };
    return std::shared_ptr<CodecBase>(noDeleterPtr, deleter);  // L47: 自定义删除器
}

// fcodec_loader.cpp L53-60
int32_t FCodecLoader::GetCapabilityList(std::vector<CapabilityData> &caps)
{
    FCodecLoader &loader = GetInstance();
    std::lock_guard<std::mutex> lock(loader.mutex_);
    CHECK_AND_RETURN_RET_LOG(loader.Init() == AVCS_ERR_OK, AVCS_ERR_UNKNOWN, "Get capability failed: init error");
    int32_t ret = loader.GetCaps(caps);
    loader.CloseLibrary();  // L58: 查完即Close
    return ret;
}

// fcodec_loader.cpp L61: 构造函数注入
FCodecLoader::FCodecLoader() : VideoCodecLoader(
    "libfcodec.z.so",           // L18: libPath
    "CreateFCodecByName",       // L19: createFuncName
    "GetFCodecCapabilityList"    // L20: getCapsFuncName
) {}
```

**特征**：引用计数延迟关闭 + 自定义删除器

### 4.2 HevcDecoderLoader（hevc_decoder_loader.cpp）—— HEVC硬件解码器工厂

```cpp
// hevc_decoder_loader.cpp L34-46（模式同 FCodecLoader）
HevcDecoderLoader::HevcDecoderLoader() : VideoCodecLoader(
    "libhevc_decoder.z.so",          // HEVC 独立动态库
    "CreateHevcDecoderByName",
    "GetHevcDecoderCapabilityList"
) {}

void HevcDecoderLoader::CloseLibrary()
{
    if (hevcDecoderCount_ != 0) {   // L55: 引用计数非零不关闭
        return;
    }
    Close();                         // L58: 基座 Close
}
```

### 4.3 AvcEncoderLoader（avc_encoder_loader.cpp）—— AVC编码器工厂

```cpp
// avc_encoder_loader.cpp L27-40
std::shared_ptr<CodecBase> AvcEncoderLoader::CreateByName(const std::string &name)
{
    AvcEncoderLoader &loader = GetInstance();
    std::lock_guard<std::mutex> lock(loader.mutex_);
    CHECK_AND_RETURN_RET_LOG(loader.Init() == AVCS_ERR_OK, nullptr, "Create codec by name failed: init error");
    std::shared_ptr<CodecBase> noDeletePtr = loader.Create(name);  // L33
    if (noDeletePtr == nullptr) {
        AVCODEC_LOGE("Loader create coder by name failed!");
        loader.CloseLibrary();
    }
    return noDeletePtr;
}

// avc_encoder_loader.cpp L41-52
int32_t AvcEncoderLoader::GetCapabilityList(std::vector<CapabilityData> &caps)
{
    AvcEncoderLoader &loader = GetInstance();
    std::lock_guard<std::mutex> lock(loader.mutex_);
    CHECK_AND_RETURN_RET_LOG(loader.Init() == AVCS_ERR_OK, AVCS_ERR_UNKNOWN, "Get capability failed: init error");
    int32_t ret = loader.GetCaps(caps);
    if (ret != AVCS_ERR_OK) {
        AVCODEC_LOGE("Loader get caps failed!");
        loader.CloseLibrary();
    }
    return ret;
}

AvcEncoderLoader::AvcEncoderLoader() : VideoCodecLoader(
    "libavc_encoder.z.so",
    "CreateAvcEncoderByName",
    "GetAvcEncoderCapabilityList"
) {}
```

### 4.4 Vp8DecoderLoader（vp8_decoder_loader.cpp）—— VP8解码器工厂

```cpp
// vp8_decoder_loader.cpp L34-46（模式同 HevcDecoderLoader）
const char *VP8_DECODER_LIB_PATH = "libvpx_decoder.z.so";
const char *VP8_DECODER_CREATE_FUNC_NAME = "CreateVpxDecoderByName";
const char *VP8_DECODER_GETCAPS_FUNC_NAME = "GetVpxDecoderCapabilityList";

Vp8DecoderLoader::Vp8DecoderLoader() : VideoCodecLoader(
    VP8_DECODER_LIB_PATH,
    VP8_DECODER_CREATE_FUNC_NAME,
    VP8_DECODER_GETCAPS_FUNC_NAME
) {}
```

### 4.5 HCodecLoader（hcodec_loader.cpp）—— 硬件编解码器工厂

```cpp
// hcodec_loader.cpp L26-39
std::shared_ptr<CodecBase> HCodecLoader::CreateByName(const std::string &name)
{
    HCodecLoader &loader = GetInstance();
    CHECK_AND_RETURN_RET_LOG(loader.Init() == AVCS_ERR_OK, nullptr, "Create codec by name failed: init error");
    return loader.Create(name);  // L30: 无引用计数逻辑，直接返回
}

int32_t HCodecLoader::GetCapabilityList(std::vector<CapabilityData> &caps)
{
    HCodecLoader &loader = GetInstance();
    CHECK_AND_RETURN_RET_LOG(loader.Init() == AVCS_ERR_OK, AVCS_ERR_UNKNOWN, "Get capability failed: init error");
    return loader.GetCaps(caps);
}

HCodecLoader::HCodecLoader() : VideoCodecLoader(
    "libhcodec.z.so",
    "CreateHCodecByName",
    "GetHCodecCapabilityList"
) {}
```

**特征**：无引用计数，与 FCodecLoader/HevcDecoderLoader 不同（硬件 Codec 生命周期由外部管理）

---

## 5. 七类 Loader 汇总

| Loader | 动态库 | Create函数 | GetCaps函数 | 引用计数 | 特殊逻辑 |
|--------|--------|-----------|-------------|---------|---------|
| FCodecLoader | libfcodec.z.so | CreateFCodecByName | GetFCodecCapabilityList | ✅ fcodecCount_ | 自定义删除器 |
| HevcDecoderLoader | libhevc_decoder.z.so | CreateHevcDecoderByName | GetHevcDecoderCapabilityList | ✅ hevcDecoderCount_ | 引用归零Close |
| AvcEncoderLoader | libavc_encoder.z.so | CreateAvcEncoderByName | GetAvcEncoderCapabilityList | ❌ 无 | 失败立即Close |
| Vp8DecoderLoader | libvpx_decoder.z.so | CreateVpxDecoderByName | GetVpxDecoderCapabilityList | ✅ vp8DecoderCount_ | 自定义删除器 |
| Vp9DecoderLoader | (同VP8) | (同VP8) | (同VP8) | (同上) | — |
| Av1DecoderLoader | (待查) | (待查) | (待查) | (待查) | — |
| HCodecLoader | libhcodec.z.so | CreateHCodecByName | GetHCodecCapabilityList | ❌ 无 | 硬件生命周期外部管理 |

---

## 6. 与 CodecBase / FCodec 的关系

```cpp
// fcodec.h L48
class FCodec : public CodecBase, public RefBase {
    // FCodec 继承 CodecBase，是 dlopen 加载后的实例类型
    // L175: std::shared_ptr<AVCodec> avCodec_ = nullptr;  // FFmpeg AVCodec 上下文
    // L178: std::shared_ptr<AVCodecContext> avCodecContext_ = nullptr;
    // L200: std::shared_ptr<TaskThread> sendTask_ = nullptr;  // 发送线程
    // L201: std::shared_ptr<TaskThread> receiveTask_ = nullptr; // 接收线程
    // L192: std::vector<std::shared_ptr<AVBuffer>> outAVBuffer4Surface_;
};
```

**调用链**：
1. FCodecLoader::CreateByName(name) → VideoCodecLoader::Init() → dlopen(libfcodec.z.so)
2. dlsym("CreateFCodecByName") → createFunc_(name, codec) → new FCodec()
3. FCodec 内部持有 FFmpeg libavcodec 上下文，执行软解

---

## 7. 关联主题

| 主题 | 关联说明 |
|------|---------|
| S178 | 双目录架构（video/ 子目录），VideoCodecLoader 所在目录 |
| S183 | AvcEncoder 软件编码器，AvcEncoderLoader 对应的编码器实现在 avcencoder/ |
| S162 | CodecList/CodecAbility 能力查询，VideoCodecLoader::GetCaps 为其提供数据源 |
| S125 | FFmpeg 音频解码器体系，与 FCodec（FFmpeg视频解码）对称 |
| S137/S161 | SA IPC 服务框架，CodecClient 通过 VideoCodecLoader 访问编解码器 |

---

**行号级证据汇总（共18条）**：

| # | 文件 | 行号 | 内容摘要 |
|---|------|------|---------|
| 1 | video_codec_loader.cpp | L27 | dlopen(libPath_, RTLD_LAZY) 延迟绑定 |
| 2 | video_codec_loader.cpp | L29 | shared_ptr<void>(handle, dlclose) 自动析构 |
| 3 | video_codec_loader.cpp | L31-34 | dlsym 加载 createFunc/getCapsFunc |
| 4 | video_codec_loader.cpp | L56 | createFunc_(name, codec) 函数指针调用 |
| 5 | video_codec_loader.cpp | L63 | getCapsFunc_(caps) 函数指针调用 |
| 6 | video_codec_loader.h | L30-31 | CreateByNameFuncType / GetCapabilityFuncType 函数指针类型定义 |
| 7 | video_codec_loader.h | L33-35 | codecHandle_/createFunc_/getCapsFunc_ 三成员 |
| 8 | fcodec_loader.cpp | L18-20 | FCODEC_LIB_PATH / CREATE_FUNC_NAME / GETCAPS_FUNC_NAME 三常量 |
| 9 | fcodec_loader.cpp | L40-41 | loader.Create(name) + fcodecCount_++ |
| 10 | fcodec_loader.cpp | L46 | CloseLibrary() 引用归零关闭 |
| 11 | fcodec_loader.cpp | L47 | shared_ptr 带自定义删除器返回 |
| 12 | fcodec_loader.cpp | L61 | FCodecLoader 构造函数注入三参数 |
| 13 | hevc_decoder_loader.cpp | L55-58 | hevcDecoderCount_ 引用计数 + CloseLibrary |
| 14 | avc_encoder_loader.cpp | L27-33 | AvcEncoderLoader::CreateByName 全流程 |
| 15 | avc_encoder_loader.cpp | L47-53 | GetCapabilityList + 失败即 Close |
| 16 | avc_encoder_loader.cpp | L54 | "libavc_encoder.z.so" 编码器库名 |
| 17 | vp8_decoder_loader.cpp | L34-46 | Vp8DecoderLoader 与 HevcDecoderLoader 模式相同 |
| 18 | hcodec_loader.cpp | L26-30 | HCodecLoader 无引用计数逻辑 |

---

*本草案基于本地镜像源码生成，行号可能因版本迭代略有偏差，建议以实际文件为准。*