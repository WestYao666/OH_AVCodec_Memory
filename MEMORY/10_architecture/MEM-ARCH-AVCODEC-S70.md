---
id: MEM-ARCH-AVCODEC-S70
title: VideoCodec 工厂与 Loader 插件体系——CodecFactory 双工厂路由与四层 dlopen 热加载
status: pending_approval
created_by: builder-agent
created_at: 2026-05-02T16:45:00+08:00
scope: [AVCodec, Factory, Loader, Plugin, dlopen, RTLD_LAZY, VideoDecoder, VideoEncoder, HardwareCodec, SoftwareCodec]
summary: VideoCodec 工厂与 Loader 插件体系采用 CodecFactory（入口）→ CodecType 路由 → 专用 Loader（dlopen/dlsym）→ 具体 Codec 实例的四层架构。CodecFactory::CreateCodecByName() 通过 FindCodecType() 识别类型后分发到 HCodecLoader/FCodecLoader/HevcDecoderLoader/AvcEncoderLoader/Av1DecoderLoader/Vp8DecoderLoader/Vp9DecoderLoader 七条路径，每条路径独立 dlopen 对应 .so 库（RTLD_LAZY），通过引用计数 CloseLibrary() 控制库卸载时机。
---

## 1. 架构概览

```
CodecFactory::CreateCodecByName(name)
    │
    ├─ CodecListCore::FindCodecType(name) → CodecType 枚举
    │
    ▼ switch(CodecType)
    │
    ├─ AVCODEC_HCODEC         → HCodecLoader::CreateByName()        → libhcodec.z.so
    ├─ AVCODEC_VIDEO_CODEC    → FCodecLoader::CreateByName()        → libfcodec.z.so
    ├─ AVCODEC_VIDEO_HEVC_DECODER → HevcDecoderLoader::CreateByName() → libhevcdec_ohos.z.so
    ├─ AVCODEC_VIDEO_AVC_ENCODER → AvcEncoderLoader::CreateByName() → libavcenc_ohos.z.so
    ├─ AVCODEC_VIDEO_AV1_DECODER → Av1DecoderLoader::CreateByName() → libdav1d.z.so
    ├─ AVCODEC_VIDEO_VP8_DECODER → Vp8DecoderLoader::CreateByName() → libvpx.z.so
    └─ AVCODEC_VIDEO_VP9_DECODER → Vp9DecoderLoader::CreateByName() → libvpx.z.so
```

### CodecType 枚举（七型分发）

**证据**：`services/engine/codeclist/codeclist_utils.h:26-34`

```cpp
enum class CodecType : int32_t {
    AVCODEC_HCODEC = 0,           // 硬件编解码器
    AVCODEC_VIDEO_CODEC,          // FFmpeg 统一软件解码器（AVC/MP4V/RV/VC1等）
    AVCODEC_VIDEO_HEVC_DECODER,  // 独立 HEVC 解码器
    AVCODEC_VIDEO_AVC_ENCODER,   // 硬件 AVC 编码器
    AVCODEC_VIDEO_VP8_DECODER,   // VP8 解码器
    AVCODEC_VIDEO_VP9_DECODER,   // VP9 解码器
    AVCODEC_VIDEO_AV1_DECODER,   // AV1 解码器
};
```

---

## 2. CodecFactory 入口路由

**证据**：`services/services/codec/server/video/codec_factory.cpp`

```cpp
std::shared_ptr<CodecBase> CodecFactory::CreateCodecByName(const std::string &name)
{
    std::shared_ptr<CodecListCore> codecListCore = std::make_shared<CodecListCore>();
    CodecType codecType = codecListCore->FindCodecType(name);  // 名字→类型查询
    switch (codecType) {
        case CodecType::AVCODEC_HCODEC:
            codec = HCodecLoader::CreateByName(name);
            break;
        case CodecType::AVCODEC_VIDEO_CODEC:
            codec = FCodecLoader::CreateByName(name);          // 统一 FFmpeg 软件解码
            break;
        case CodecType::AVCODEC_VIDEO_HEVC_DECODER:
            codec = HevcDecoderLoader::CreateByName(name);
            break;
        case CodecType::AVCODEC_VIDEO_AVC_ENCODER:
            codec = AvcEncoderLoader::CreateByName(name);
            break;
#ifdef SUPPORT_CODEC_AV1
        case CodecType::AVCODEC_VIDEO_AV1_DECODER:
            codec = Av1DecoderLoader::CreateByName(name);
            break;
#endif
        // ... VP8/VP9 类似
        default:
            AVCODEC_LOGE("Create codec %{public}s failed", name.c_str());
            break;
    }
    return codec;
}
```

**Include 树**：共引入 8 个 Loader 头文件（6 个 always + 2 个 conditional）

| Loader | 头文件 | 条件编译 |
|--------|--------|---------|
| FCodecLoader | `fcodec_loader.h` | always |
| HevcDecoderLoader | `hevc_decoder_loader.h` | always |
| HCodecLoader | `hcodec_loader.h` | always |
| AvcEncoderLoader | `avc_encoder_loader.h` | always |
| Av1DecoderLoader | `av1_decoder_loader.h` | `SUPPORT_CODEC_AV1` |
| Vp8DecoderLoader | `vp8_decoder_loader.h` | `SUPPORT_CODEC_VP8` |
| Vp9DecoderLoader | `vp9_decoder_loader.h` | `SUPPORT_CODEC_VP9` |

---

## 3. VideoCodecLoader 基类——dlopen/dlsym 基础设施

**证据**：`services/engine/codec/video/video_codec_loader.h` + `video_codec_loader.cpp`

### 3.1 基类接口

```cpp
class VideoCodecLoader {
public:
    // 构造时注入库路径和符号名
    VideoCodecLoader(const char *libPath, const char *createFuncName, const char *getCapsFuncName)
        : libPath_(libPath_), createFuncName_(createFuncName), getCapsFuncName_(getCapsFuncName) {};

    std::shared_ptr<CodecBase> Create(const std::string &name);  // 调用 dlsym CreateByName
    int32_t GetCaps(std::vector<CapabilityData> &caps);          // 调用 dlsym GetCapabilityList
    int32_t Init();   // dlopen(RTLD_LAZY) + dlsym 两个函数
    void Close();      // dlclose，引用计数清零后调用

private:
    using CreateByNameFuncType = void (*)(const std::string &, std::shared_ptr<CodecBase> &);
    using GetCapabilityFuncType = int32_t (*)(std::vector<CapabilityData> &);
    std::shared_ptr<void> codecHandle_;          // dlopen 句柄，自动析构 dlclose
    CreateByNameFuncType createFunc_ = nullptr;
    GetCapabilityFuncType getCapsFunc_ = nullptr;
    const char *libPath_;                         // e.g. "libfcodec.z.so"
    const char *createFuncName_;                  // e.g. "CreateFCodecByName"
    const char *getCapsFuncName_;                 // e.g. "GetFCodecCapabilityList"
};
```

### 3.2 Init()——RTLD_LAZY 懒加载

```cpp
int32_t VideoCodecLoader::Init()
{
    if (codecHandle_ != nullptr) return AVCS_ERR_OK;  // 已有句柄直接返回
    void *handle = dlopen(libPath_, RTLD_LAZY);         // 懒加载，不解析未用符号
    auto handleSP = std::shared_ptr<void>(handle, dlclose);  // 自动 dlclose
    auto createFunc = reinterpret_cast<CreateByNameFuncType>(dlsym(handle, createFuncName_));
    auto getCapsFunc = reinterpret_cast<GetCapabilityFuncType>(dlsym(handle, getCapsFuncName_));
    codecHandle_ = handleSP;
    createFunc_ = createFunc;
    getCapsFunc_ = getCapsFunc;
    return AVCS_ERR_OK;
}
```

**关键特性**：RTLD_LAZY 只在首次调用函数时解析符号，允许库中部分符号不存在而不报错（对应条件编译的 codec 类型）。

### 3.3 Close()——库卸载

```cpp
void VideoCodecLoader::Close()
{
    codecHandle_ = nullptr;   // shared_ptr 引用计数归零 → dlclose
    createFunc_ = nullptr;
    getCapsFunc_ = nullptr;
}
```

---

## 4. 七类专用 Loader 详解

### 4.1 FCodecLoader——FFmpeg 统一软件解码

**证据**：`services/engine/codec/video/fcodec_loader.cpp`

| 参数 | 值 |
|------|-----|
| 库路径 | `libfcodec.z.so` |
| 创建函数 | `CreateFCodecByName` |
| 能力函数 | `GetFCodecCapabilityList` |

**引用计数机制**：

```cpp
std::mutex mutex_;
int32_t fcodecCount_ = 0;  // 当前实例数

std::shared_ptr<CodecBase> FCodecLoader::CreateByName(const std::string &name)
{
    FCodecLoader &loader = GetInstance();   // 单例
    std::lock_guard<std::mutex> lock(loader.mutex_);
    CHECK_AND_RETURN_RET_LOG(loader.Init() == AVCS_ERR_OK, nullptr, ...);
    noDeleterPtr = loader.Create(name).get();  // 调用 dlsym 得到的函数
    ++(loader.fcodecCount_);                   // 引用计数 +1

    // 自定义 deleter：实例销毁时计数 -1，计数归零时卸载库
    auto deleter = [&loader](CodecBase *ptr) {
        std::lock_guard<std::mutex> lock(loader.mutex_);
        codec->DecStrongRef(codec);            // 通知 FCodec 释放自身
        --(loader.fcodecCount_);
        loader.CloseLibrary();                 // fcodecCount_ == 0 时 dlclose
    };
    return std::shared_ptr<CodecBase>(noDeleterPtr, deleter);
}

void FCodecLoader::CloseLibrary()
{
    if (fcodecCount_) return;   // 仍有实例，不卸载
    Close();                    // 引用归零，执行 dlclose
}
```

**FCodec 统一软件解码器覆盖的格式**（`fcodec.h`）：AVC、HEVC（可切换至独立 HevcDecoder）、MP4V、MPEG2、MPEG4、H263、MJPEG、RV、VC1、WMV3 等。

### 4.2 HCodecLoader——硬件编解码器

**证据**：`services/engine/codec/video/hcodec_loader.cpp`

| 参数 | 值 |
|------|-----|
| 库路径 | `libhcodec.z.so` |
| 创建函数 | `CreateHCodecByName` |
| 能力函数 | `GetHCodecCapabilityList` |

HCodecLoader **无引用计数**（`GetInstance()` 直接返回静态局部变量），无自定义 deleter。库在 Init() 后保持加载状态。

### 4.3 HevcDecoderLoader——独立 HEVC 解码器

**证据**：`services/engine/codec/include/video/hevc_decoder_loader.h`

| 参数 | 值 |
|------|-----|
| 库路径 | `libhevcdec_ohos.z.so`（HDI vendor 库） |
| 创建函数 | 符号名通过构造函数注入 |
| 能力函数 | 同上 |

**引用计数机制同 FCodecLoader**：

```cpp
class HevcDecoderLoader : public VideoCodecLoader {
    std::mutex mutex_;
    int32_t hevcDecoderCount_ = 0;  // 实例计数
};
```

### 4.4 AvcEncoderLoader——硬件 AVC 编码器

**证据**：`services/engine/codec/include/video/avc_encoder_loader.h`

| 参数 | 值 |
|------|-----|
| 库路径 | `libavcenc_ohos.z.so` |
| 创建函数 | 注入（见 S59 AvcEncoder 草案） |

AvcEncoderLoader **无引用计数**（无 `CloseLibrary()` 调用），库加载后常驻。

### 4.5 Av1DecoderLoader / Vp8DecoderLoader / Vp9DecoderLoader

| Loader | 库 | 条件编译 | 证据 |
|--------|----|---------|------|
| Av1DecoderLoader | `libdav1d.z.so` | `SUPPORT_CODEC_AV1` | S51 Av1Decoder |
| Vp8DecoderLoader | `libvpx.z.so` | `SUPPORT_CODEC_VP8` | S54 HevcDecoder+VpxDecoder |
| Vp9DecoderLoader | `libvpx.z.so` | `SUPPORT_CODEC_VP9` | S54 HevcDecoder+VpxDecoder |

VP8/VP9 共用 `libvpx.z.so`，通过不同创建函数名区分。

---

## 5. 文件物理布局

**证据**：`services/engine/codec/video/`

```
video_codec_loader.cpp          ← 基类，dlopen/dlsym 基础设施
fcodec_loader.cpp              ← FCodecLoader（引用计数）
hcodec_loader.cpp              ← HCodecLoader（无引用计数）
hevc_decoder_loader.cpp        ← HevcDecoderLoader（引用计数）
avc_encoder_loader.cpp         ← AvcEncoderLoader（无引用计数）
vp8_decoder_loader.cpp         ← Vp8DecoderLoader
vp9_decoder_loader.cpp         ← Vp9DecoderLoader
av1_decoder_loader.cpp         ← Av1DecoderLoader
avcodec/
    fcodec/
        include/fcodec.h       ← FCodec 统一软件解码器类定义
        fcodec.cpp            ← FFmpeg libavcodec 封装
    hcodec/                   ← HDecoder/HEncoder 硬件编解码器
    hevcdecoder/              ← 独立 HEVC 解码器
    avcencoder/               ← AvcEncoder 硬件编码器
    av1decoder/               ← Av1Decoder dav1d 封装
    vpxdecoder/               ← VpxDecoder libvpx 封装
```

---

## 6. 与现有草案的关联

| 关联草案 | 关系 |
|---------|------|
| S39: AVCodecVideoDecoder | VideoDecoder 基类（CodecBase 子类），由 FCodecLoader 或 HevcDecoderLoader 创建 |
| S51: Av1Decoder | Av1DecoderLoader 创建，libdav1d.z.so 封装 |
| S53: FCodec | FCodecLoader 创建，libfcodec.z.so，FFmpeg libavcodec 封装 |
| S54: HevcDecoder+VpxDecoder | HevcDecoderLoader/VpxDecoderLoader 创建 |
| S57: HDecoder/HEncoder | HCodecLoader 创建，libhcodec.z.so |
| S59: AvcEncoder | AvcEncoderLoader 创建，libavcenc_ohos.z.so |
| S42: VideoEncoder 基类 | VideoEncoder 基类由各 EncoderLoader 创建 |
| S47: CodecCapability | CodecListCore::FindCodecType(name) 为本架构提供类型识别服务 |

---

## 7. 关键设计模式总结

| 设计点 | 实现 |
|--------|------|
| **入口单例** | `CodecFactory::Instance()` 静态局部变量单例 |
| **类型路由** | `CodecListCore::FindCodecType(name)` 字符串→CodecType |
| **插件加载** | `dlopen(RTLD_LAZY)` 懒加载 + `dlsym` 符号解析 |
| **库生命周期** | shared_ptr + 自定义 deleter，引用计数归零触发 `dlclose` |
| **实例单例 Loader** | `GetInstance()` 返回静态局部变量，多实例共享 Loader |
| **能力发现** | `GetCapsFunc` 库内符号，`VideoCodecLoader::GetCaps()` 透传 |
| **条件编译** | `#ifdef SUPPORT_CODEC_AV1/VP8/VP9` 编译期裁剪 |
