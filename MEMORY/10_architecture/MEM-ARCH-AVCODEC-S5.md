---
id: MEM-ARCH-AVCODEC-S5
title: 四层 Loader 插件热加载机制——dlopen/RTLD_LAZY 与引用计数 lifecycle
scope: [AVCodec, Plugin, Loader, dlopen, Lifecycle]
status: draft
created_at: 2026-04-22
evidence_sources:
  - local_repo: /home/west/av_codec_repo
  - https://gitcode.com/openharmony/multimedia_av_codec
---

# 四层 Loader 插件热加载机制——dlopen/RTLD_LAZY 与引用计数 lifecycle

> **Builder 验证记录（2026-04-22）**：基于本地仓库 `/home/west/av_codec_repo` 代码验证，聚焦四层 Loader 体系与引用计数生命周期管理。覆盖 `VideoCodecLoader::Init()` dlopen 路径、`FCodecLoader` 引用计数闭包、`HevcDecoderLoader` 专用 Loader、`CodecFactory` 分发逻辑。

## 1. 概述

AVCodec 插件不通过编译时链接，而是通过 **dlopen 动态加载 .z.so** 实现运行时绑定。插件层分为四层结构：

| 层级 | 类名 | 职责 | 关键库 |
|------|------|------|--------|
| 第一层 | `CodecFactory` | name→CodecType 路由 | 内置逻辑 |
| 第二层 | `VideoCodecLoader` | dlopen/dlsym 封装基类 | 模板类 |
| 第三层 | `FCodecLoader` / `HCodecLoader` | 软/硬编解码器分发 | libfcodec.z.so / libhcodec.z.so |
| 第四层 | `HevcDecoderLoader` / `AvcEncoderLoader` / ... | 专用硬件 Loader | libhevc_decoder.z.so 等 |

**与 S1/S3 的互补**：
- **S1**：`CodecServer` 是实例载体，`CodecFactory` 负责按 name 实例化插件
- **S3**：Pipeline 数据流经过 `codecBase_`（即 Loader 创建的插件实例）
- **MEM-ARCH-AVCODEC-014**："三层插件机制" 仅涵盖 CodecBase/Factory/Loader，未深入专用 Loader 的引用计数差异

---

## 2. 第四层详解（按特化程度）

### 2.1 VideoCodecLoader 基类（dlopen 封装）

```cpp
// video_codec_loader.h
class VideoCodecLoader {
    std::shared_ptr<void> codecHandle_ = nullptr;  // dlopen 返回的句柄
    CreateByNameFuncType createFunc_ = nullptr;     // dlsym("CreateXxxByName")
    GetCapabilityFuncType getCapsFunc_ = nullptr;   // dlsym("GetXxxCapabilityList")
    const char *libPath_;
    const char *createFuncName_;
    const char *getCapsFuncName_;
};
```

**Init() 源码**（`video_codec_loader.cpp`）：
```cpp
int32_t VideoCodecLoader::Init()
{
    if (codecHandle_ != nullptr) return AVCS_ERR_OK;  // 已加载则跳过
    void *handle = dlopen(libPath_, RTLD_LAZY);
    auto handleSP = std::shared_ptr<void>(handle, dlclose);  // shared_ptr 自动 dlclose
    auto createFunc = reinterpret_cast<CreateByNameFuncType>(dlsym(handle, createFuncName_));
    auto getCapsFunc = reinterpret_cast<GetCapabilityFuncType>(dlsym(handle, getCapsFuncName_));
    codecHandle_ = handleSP;
    createFunc_ = createFunc;
    getCapsFunc_ = getCapsFunc;
    return AVCS_ERR_OK;
}
```

**关键设计**：
- `RTLD_LAZY`（延迟解析），仅在使用时才解析符号
- `codecHandle_` 用 `shared_ptr<void>(handle, dlclose)` 管理，引用计数归零时自动 `dlclose`
- `Init()` 可被多次调用（线程安全检查 `codecHandle_ != nullptr`）

### 2.2 FCodecLoader（软件编解码，引用计数 + 延迟 dlclose）

```cpp
// fcodec_loader.cpp
const char *FCODEC_LIB_PATH = "libfcodec.z.so";
const char *FCODEC_CREATE_FUNC_NAME = "CreateFCodecByName";
const char *FCODEC_GETCAPS_FUNC_NAME = "GetFCodecCapabilityList";

std::shared_ptr<CodecBase> FCodecLoader::CreateByName(const std::string &name)
{
    FCodecLoader &loader = GetInstance();
    CodecBase *noDeleterPtr = nullptr;
    {
        std::lock_guard<std::mutex> lock(loader.mutex_);
        CHECK_AND_RETURN_RET_LOG(loader.Init() == AVCS_ERR_OK, nullptr, "Create codec by name failed: init error");
        noDeleterPtr = loader.Create(name).get();
        ++(loader.fcodecCount_);  // 引用计数++
    }
    // deleter：引用计数--，归零时 CloseLibrary()
    auto deleter = [&loader](CodecBase *ptr) {
        std::lock_guard<std::mutex> lock(loader.mutex_);
        FCodec *codec = reinterpret_cast<FCodec*>(ptr);
        codec->DecStrongRef(codec);
        --(loader.fcodecCount_);
        loader.CloseLibrary();
    };
    return std::shared_ptr<CodecBase>(noDeleterPtr, deleter);
}

void FCodecLoader::CloseLibrary()
{
    if (fcodecCount_) return;  // 仍有实例存活，不 close
    Close();                  // 最终关闭 .so
}
```

**关键设计**：
- `fcodecCount_` 追踪**当前活跃 Codec 实例数**
- 每次 `CreateByName` 时 `++fcodecCount_`
- 每次实例销毁时 `DecStrongRef` 后 `--fcodecCount_`
- `fcodecCount_==0` 才执行 `Close()`（对应 `dlclose`）
- **dlclose 不会立即卸载 .so**：只有当 .so 的符号引用计数也归零时才真正卸载

### 2.3 HCodecLoader（硬件编解码，无引用计数，直接共享）

```cpp
// hcodec_loader.cpp
std::shared_ptr<CodecBase> HCodecLoader::CreateByName(const std::string &name)
{
    HCodecLoader &loader = GetInstance();
    CHECK_AND_RETURN_RET_LOG(loader.Init() == AVCS_ERR_OK, nullptr, "Create codec by name failed: init error");
    return loader.Create(name);  // 直接返回，无引用计数包装
}
```

**与 FCodecLoader 的关键差异**：

| 特性 | FCodecLoader | HCodecLoader |
|------|-------------|-------------|
| 引用计数 | ✅ `fcodecCount_` | ❌ 无 |
| custom deleter | ✅ | ❌ |
| .so 延迟卸载 | ✅（Count==0 才 dlclose） | ❌（Init 后不主动 dlclose） |
| 适用场景 | 多个软件 codec 实例切换 | 硬件 codec 通常单例 |
| 线程安全 | mutex_ 保护 | 无需（硬件编解码通常进程内单例） |

### 2.4 专用 Loader（HevcDecoderLoader、AvcEncoderLoader 等）

```cpp
// hevc_decoder_loader.cpp
const char *HEVC_DECODER_LIB_PATH = "libhevc_decoder.z.so";
const char *HEVC_DECODER_CREATE_FUNC_NAME = "CreateHevcDecoderByName";
const char *HEVC_DECODER_GETCAPS_FUNC_NAME = "GetHevcDecoderCapabilityList";

std::shared_ptr<CodecBase> HevcDecoderLoader::CreateByName(const std::string &name)
{
    HevcDecoderLoader &loader = GetInstance();
    CodecBase *noDeleterPtr = nullptr;
    {
        std::lock_guard<std::mutex> lock(loader.mutex_);
        loader.Init();
        noDeleterPtr = loader.Create(name).get();
        ++(loader.hevcDecoderCount_);  // 引用计数++
    }
    auto deleter = [&loader](CodecBase *ptr) {
        std::lock_guard<std::mutex> lock(loader.mutex_);
        HevcDecoder *codec = static_cast<HevcDecoder*>(ptr);
        codec->DecStrongRef(codec);
        --(loader.hevcDecoderCount_);
        loader.CloseLibrary();
    };
    return std::shared_ptr<CodecBase>(noDeleterPtr, deleter);
}

void HevcDecoderLoader::CloseLibrary()
{
    if (hevcDecoderCount_ != 0) return;
    Close();
}
```

**专用 Loader 清单**（`codec_factory.cpp`）：

| Loader | 库文件 | 支持的 Codec |
|--------|--------|-------------|
| `FCodecLoader` | libfcodec.z.so | 软件编解码（avcdecoder、vp8decoder 等） |
| `HCodecLoader` | libhcodec.z.so | 硬件编解码 |
| `HevcDecoderLoader` | libhevc_decoder.z.so | HEVC 硬件解码 |
| `AvcEncoderLoader` | libavc_encoder.z.so | AVC 硬件编码 |
| `Av1DecoderLoader` | libav1_decoder.z.so | AV1 解码 |
| `Vp8DecoderLoader` | libvp8_decoder.z.so | VP8 解码 |
| `Vp9DecoderLoader` | libvp9_decoder.z.so | VP9 解码 |

每个专用 Loader 继承 `VideoCodecLoader`，各自维护独立的 `mutex_` 和引用计数。

---

## 3. CodecFactory 路由逻辑

```cpp
// codec_factory.cpp
std::shared_ptr<CodecBase> CodecFactory::CreateCodecByName(const std::string &name)
{
    CodecListCore codecListCore;
    CodecType codecType = codecListCore.FindCodecType(name);  // 查 CodecListCore
    switch (codecType) {
        case CodecType::AVCODEC_HCODEC:
            return HCodecLoader::CreateByName(name);
        case CodecType::AVCODEC_VIDEO_CODEC:
            return FCodecLoader::CreateByName(name);
        case CodecType::AVCODEC_VIDEO_HEVC_DECODER:
            return HevcDecoderLoader::CreateByName(name);
        case CodecType::AVCODEC_VIDEO_AVC_ENCODER:
            return AvcEncoderLoader::CreateByName(name);
#ifdef SUPPORT_CODEC_AV1
        case CodecType::AVCODEC_VIDEO_AV1_DECODER:
            return Av1DecoderLoader::CreateByName(name);
#endif
        // ...
    }
}
```

**CodecType 来源**：`CodecListCore::FindCodecType(name)` — 从编译时注册的能力列表中查询 name→CodecType 映射。

---

## 4. 四层调用链总览

```
应用层（CodecServer）
    │
    │ CodecServer::Init() → CodecServer::InitByName(name)
    │     or CodecServer::InitByMime(type, mime)
    ▼
CodecFactory::CreateCodecByName(name)
    │
    │ CodecListCore::FindCodecType(name) → CodecType
    ▼
[第一层路由]
    │
    ├── CodecType::AVCODEC_VIDEO_CODEC  → FCodecLoader::CreateByName(name)
    │     ├── dlopen("libfcodec.z.so", RTLD_LAZY)
    │     ├── dlsym("CreateFCodecByName")
    │     └── shared_ptr<CodecBase>(codec, custom_deleter) [引用计数]
    │
    ├── CodecType::AVCODEC_HCODEC  → HCodecLoader::CreateByName(name)
    │     ├── dlopen("libhcodec.z.so", RTLD_LAZY)
    │     ├── dlsym("CreateHCodecByName")
    │     └── shared_ptr<CodecBase>(codec) [无引用计数]
    │
    └── CodecType::AVCODEC_VIDEO_HEVC_DECODER → HevcDecoderLoader::CreateByName(name)
          ├── dlopen("libhevc_decoder.z.so", RTLD_LAZY)
          ├── dlsym("CreateHevcDecoderByName")
          └── shared_ptr<CodecBase>(codec, custom_deleter) [引用计数]
              │
              ▼
        [第四层] VideoCodecLoader::Create(name)
              │
              ▼
        dlsym("CreateXxxByName")(name, codec)
              │
              ▼
        [返回 CodecBase 插件实例]
```

---

## 5. 引用计数 lifecycle 详解（以 FCodecLoader 为例）

```
时间线：
T1: CreateByName("avcdecoder") 
    → fcodecCount_ = 1
    → dlopen("libfcodec.z.so") // 首次加载

T2: CreateByName("avcdecoder")  // 第二个实例
    → fcodecCount_ = 2
    → .so 已加载，不重复 dlopen

T3: 第一个实例析构（DecStrongRef）
    → fcodecCount_ = 1
    → CloseLibrary() → 不关闭（仍 > 0）

T4: 第二个实例析构
    → fcodecCount_ = 0
    → CloseLibrary() → Close() → dlclose(libfcodec.z.so)
    → .so 卸载完成
```

**关键机制**：
- `dlopen` 在第一次 `CreateByName` 时执行
- `dlclose`（通过 `Close()`）在**最后一个实例销毁且引用计数归零**时才执行
- `FCodecLoader` 使用**自定义 shared_ptr deleter** 实现引用计数
- `HCodecLoader` 不使用引用计数，`.so 加载后不会主动卸载`

---

## 6. 关键文件索引

| 文件 | 作用 |
|------|------|
| `services/engine/codec/include/video/video_codec_loader.h` | 基类声明（dlopen 模板） |
| `services/engine/codec/video/video_codec_loader.cpp` | Init/Create/GetCaps 实现 |
| `services/engine/codec/include/video/fcodec_loader.h/cpp` | 软件编解码 Loader（引用计数） |
| `services/engine/codec/include/video/hcodec_loader.h/cpp` | 硬件编解码 Loader（无引用计数） |
| `services/engine/codec/video/hevc_decoder_loader.cpp` | HEVC 专用 Loader（引用计数） |
| `services/services/codec/server/video/codec_factory.cpp` | CodecFactory 路由分发 |
| `services/engine/base/include/codecbase.h` | CodecBase 抽象基类 |
| `services/engine/codeclist/codeclist_core.cpp` | name→CodecType 映射查询 |

---

## 7. 与 MEM-ARCH-AVCODEC-014 的差异

| 维度 | MEM-ARCH-AVCODEC-014 | 本篇 S5 |
|------|---------------------|---------|
| 层级 | 三层：CodecBase/Loader/Factory | 四层：+ 专用 Loader（Hevc/AvcEncoder 等） |
| FCodecLoader | 有 | 深入引用计数机制 |
| HCodecLoader | 有 | 揭示其无引用计数的特殊性 |
| dlclose 延迟卸载 | 未覆盖 | 详细解析 fcodecCount_ 控制逻辑 |
| custom deleter | 未覆盖 | 展示 lambda deleter 与 DecStrongRef 联动 |
| 专用 Loader 列表 | 未覆盖 | 完整枚举 7 类 Loader |

---

## 8. 关联记忆

- **MEM-ARCH-AVCODEC-S1**：`CodecServer` 实例载体 + `CodecFactory` 角色
- **MEM-ARCH-AVCODEC-S3**：Pipeline 数据流经过 `codecBase_`（Loader 创建的插件实例）
- **MEM-ARCH-AVCODEC-014**："CodecBase + Loader + Factory 三层插件机制"（S1 的插件部分补充）
- **MEM-ARCH-AVCODEC-018**：硬件编解码 HDI 架构（HCodecLoader 加载的 libhcodec.z.so 的下游）
