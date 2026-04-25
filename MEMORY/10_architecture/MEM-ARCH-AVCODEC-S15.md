---
type: architecture
id: MEM-ARCH-AVCODEC-S15
status: pending_approval
topic: SurfaceCodec 软件编解码器插件架构——CodecBase 插件基类、软硬编解码器 Loader 与适配流程
submitted_at: "2026-04-25T09:12:00+08:00"
scope: [AVCodec, SoftwareCodec, Plugin, CodecBase, Adapter, FCodec, HCodec, SurfaceDecoderAdapter, SurfaceEncoderAdapter]
created_at: "2026-04-24T03:50:00+08:00"
author: builder-agent
evidence: |
  - source: services/engine/base/include/codecbase.h
    anchor: "CreateInputSurface()/SetInputSurface()/SetOutputSurface() virtual 方法"
    note: CodecBase 基类定义了 Surface 相关的三个虚方法
  - source: services/engine/codec/video/fcodec/include/fcodec.h line 48
    anchor: "class FCodec : public CodecBase, public RefBase"
    note: FCodec 继承 CodecBase，实现软件编解码
  - source: services/engine/codec/video/fcodec_loader.cpp line 25-26
    anchor: "const char *FCODEC_LIB_PATH = \"libfcodec.z.so\""
    note: FCodecLoader 动态加载 libfcodec.z.so
  - source: services/engine/codec/video/hcodec_loader.cpp line 22-23
    anchor: "const char *HCODEC_LIB_PATH = \"libhcodec.z.so\""
    note: HCodecLoader 动态加载 libhcodec.z.so
  - source: services/media_engine/filters/surface_decoder_adapter.cpp line 147-166
    anchor: "avCodecList->GetCapability(mime, false, AVCodecCategory::AVCODEC_HARDWARE)"
    note: SurfaceDecoderAdapter 通过 capability.isVendor 判断软/硬解码路径
  - source: services/services/codec/server/video/codec_factory.cpp line 52-75
    anchor: "CodecListCore::FindCodecType → FCodecLoader::CreateByName / HCodecLoader::CreateByName"
    note: CodecFactory 根据 codec type 分发到 FCodecLoader 或 HCodecLoader
---

# MEM-ARCH-AVCODEC-S15: SurfaceCodec 软件编解码器插件架构

## Metadata

| 字段 | 值 |
|------|-----|
| id | MEM-ARCH-AVCODEC-S15 |
| title | SurfaceCodec 软件编解码器插件架构——CodecBase 插件基类、软硬编解码器 Loader 与适配流程 |
| scope | [AVCodec, SoftwareCodec, Plugin, CodecBase, Adapter, FCodec, HCodec] |
| status | draft |
| created_by | builder-agent |
| created_at | 2026-04-24 |
| type | architecture_fact |
| confidence | high |

---

## 摘要

SurfaceCodec 软件编解码器插件体系包含三层结构：

1. **CodecBase 基类**（`services/engine/base/include/codecbase.h`）—— 所有编解码器的统一抽象，定义了 Surface 相关虚方法
2. **FCodec / HCodec** —— 软件/硬件编解码器实现类，前者位于 `services/engine/codec/video/fcodec/`，后者封装为 `libhcodec.z.so`
3. **FCodecLoader / HCodecLoader** —— 分别通过 `dlopen` 动态加载 `libfcodec.z.so`（软件）和 `libhcodec.z.so`（硬件）插件
4. **SurfaceDecoderAdapter / SurfaceEncoderAdapter** —— Filter 层适配器，通过 `CodecListCore` + `isVendor` 字段判断走硬件还是软件路径，再通过 `CodecFactory` 分发到对应 Loader

---

## 1. CodecBase 基类（插件统一接口）

**文件**: `services/engine/base/include/codecbase.h`

CodecBase 是所有编解码器插件的基类，定义了编解码器生命周期方法 + Surface 相关方法：

```cpp
// services/engine/base/include/codecbase.h line 50-52
virtual sptr<Surface> CreateInputSurface();
virtual int32_t SetInputSurface(sptr<Surface> surface);
virtual int32_t SetOutputSurface(sptr<Surface> surface);
```

| 方法 | 作用 |
|------|------|
| `Init(format)` | 初始化编解码器 |
| `Start()/Stop()` | 启动/停止 |
| `Configure(format)` | 配置编码参数 |
| `Flush()/Release()` | 刷新/释放资源 |
| `QueueInputBuffer()/ReleaseOutputBuffer()` | buffer 管理 |
| `SetOutputSurface(surface)` | 设置输出 Surface（Surface 路径专用） |
| `SetCallback(callback)` | 设置异步回调 |

> **关键设计**：CodecBase 只定义了 Surface 虚方法，不区分软/硬实现。子类通过 override 实现自己的 Surface 策略。

---

## 2. 软件编解码器：FCodec（libfcodec.z.so）

**文件**: `services/engine/codec/video/fcodec/include/fcodec.h`

```cpp
// line 48
class FCodec : public CodecBase, public RefBase {
public:
    explicit FCodec(const std::string &name);
    ~FCodec() override;
    int32_t Init(Media::Meta &callerInfo) override;
    int32_t Configure(const Format &format) override;
    int32_t Start() override;
    int32_t Stop() override;
    int32_t Flush() override;
    int32_t Reset() override;
    int32_t Release() override;
    int32_t SetParameter(const Format &format) override;
    int32_t GetOutputFormat(Format &format) override;
    int32_t QueueInputBuffer(uint32_t index) override;
    int32_t ReleaseOutputBuffer(uint32_t index) override;
    int32_t SetCallback(const std::shared_ptr<MediaCodecCallback> &callback) override;
    int32_t SetOutputSurface(sptr<Surface> surface) override;  // line 65
    int32_t RenderOutputBuffer(uint32_t index) override;
    int32_t NotifyMemoryRecycle() override;
    int32_t NotifyMemoryWriteBack() override;
    static int32_t GetCodecCapability(std::vector<CapabilityData> &capaArray);
};
```

**FCodec 的职责**：
- 软件编解码实现，基于 FFmpeg（`g_convertFfmpegPixFmt` 等）
- 通过 `SetOutputSurface()` 支持 Surface 模式输出
- 支持内存回收（`NotifyMemoryRecycle()/NotifyMemoryWriteBack()`）

---

## 3. 插件加载器：FCodecLoader vs HCodecLoader

### 3.1 FCodecLoader（软件 Codec 加载器）

**文件**: `services/engine/codec/video/fcodec_loader.cpp`

```cpp
// line 25-26
const char *FCODEC_LIB_PATH = "libfcodec.z.so";
const char *FCODEC_CREATE_FUNC_NAME = "CreateFCodecByName";
const char *FCODEC_GETCAPS_FUNC_NAME = "GetFCodecCapabilityList";

std::shared_ptr<CodecBase> FCodecLoader::CreateByName(const std::string &name)
{
    FCodecLoader &loader = GetInstance();
    CHECK_AND_RETURN_RET_LOG(loader.Init() == AVCS_ERR_OK, nullptr, ...);
    return loader.Create(name);  // dlopen + dlsym
}
```

- 通过 `dlopen("libfcodec.z.so", RTLD_LAZY)` 加载
- 导出符号：`CreateFCodecByName`（创建）、`GetFCodecCapabilityList`（能力查询）
- 引用计数管理（`fcodecCount_`），最后引用释放时 CloseLibrary

### 3.2 HCodecLoader（硬件 Codec 加载器）

**文件**: `services/engine/codec/video/hcodec_loader.cpp`

```cpp
// line 22-23
const char *HCODEC_LIB_PATH = "libhcodec.z.so";
const char *HCODEC_CREATE_FUNC_NAME = "CreateHCodecByName";
const char *HCODEC_GETCAPS_FUNC_NAME = "GetHCodecCapabilityList";

std::shared_ptr<CodecBase> HCodecLoader::CreateByName(const std::string &name)
{
    HCodecLoader &loader = GetInstance();
    CHECK_AND_RETURN_RET_LOG(loader.Init() == AVCS_ERR_OK, nullptr, ...);
    return loader.Create(name);  // dlopen + dlsym
}
```

- 通过 `dlopen("libhcodec.z.so", RTLD_LAZY)` 加载
- 导出符号：`CreateHCodecByName`、`GetHCodecCapabilityList`
- 硬件编解码器由芯片厂商提供 so 库实现

---

## 4. CodecFactory 分发逻辑（软/硬分流核心）

**文件**: `services/services/codec/server/video/codec_factory.cpp`

```cpp
// line 52-75
std::shared_ptr<CodecBase> CodecFactory::CreateCodecByName(const std::string &name)
{
    auto codecListCore = std::make_shared<CodecListCore>();
    CodecType codecType = codecListCore->FindCodecType(name);  // 由 codec name 识别类型
    std::shared_ptr<CodecBase> codec = nullptr;
    switch (codecType) {
        case CodecType::AVCODEC_HCODEC:
            codec = HCodecLoader::CreateByName(name);   // → 硬件
            break;
        case CodecType::AVCODEC_VIDEO_CODEC:
            codec = FCodecLoader::CreateByName(name);   // → 软件
            break;
        case CodecType::AVCODEC_VIDEO_HEVC_DECODER:
            codec = HevcDecoderLoader::CreateByName(name);
            break;
        case CodecType::AVCODEC_VIDEO_AVC_ENCODER:
            codec = AvcEncoderLoader::CreateByName(name);
            break;
        // ... VP8/VP9/AV1 等
        default:
            AVCODEC_LOGE("Create codec %{public}s failed", name.c_str());
            break;
    }
    return codec;
}
```

**分发决策树**：
```
codec name → FindCodecType(name)
  ├── AVCODEC_HCODEC          → HCodecLoader::CreateByName (硬件 so)
  ├── AVCODEC_VIDEO_CODEC    → FCodecLoader::CreateByName (软件 so)
  ├── AVCODEC_VIDEO_HEVC_DECODER → HevcDecoderLoader (HEVC 专用硬件)
  └── AVCODEC_VIDEO_AVC_ENCODER  → AvcEncoderLoader (AVC 硬件编码器)
```

---

## 5. SurfaceDecoderAdapter 的软硬判断逻辑

**文件**: `services/media_engine/filters/surface_decoder_adapter.cpp`

### 5.1 HDR 场景（硬解码优先）

```cpp
// line 147-166
Status SurfaceDecoderAdapter::Init(const std::string &mime, bool isHdr)
{
    FALSE_RETURN_V_NOLOG(isHdr, Init(mime));  // 非 HDR 走普通路径

    std::shared_ptr<MediaAVCodec::AVCodecList> avCodecList =
        MediaAVCodec::AVCodecListFactory::CreateAVCodecList();
    FALSE_RETURN_V_MSG(avCodecList != nullptr, Status::ERROR_UNKNOWN, "get codec list failed");

    // 查询硬件解码器能力
    MediaAVCodec::CapabilityData *capabilityData = avCodecList->GetCapability(
        mime, false, MediaAVCodec::AVCodecCategory::AVCODEC_HARDWARE);

    FALSE_RETURN_V_MSG(capabilityData->isVendor, Status::ERROR_UNKNOWN, "not hw decoder");
    FALSE_RETURN_V_MSG(
        capabilityData->codecType == static_cast<int32_t>(MediaAVCodec::AVCodecType::AVCODEC_TYPE_VIDEO_DECODER),
        Status::ERROR_UNKNOWN, "not video decoder");
    FALSE_RETURN_V_MSG(capabilityData->mimeType == mime, Status::ERROR_UNKNOWN, "not correct mime");
    FALSE_RETURN_V_MSG(capabilityData->codecName != "", Status::ERROR_UNKNOWN, "empty codec name");

    // 使用硬件解码器名称创建
    int ret = MediaAVCodec::VideoDecoderFactory::CreateByName(
        capabilityData->codecName, format, codecServer_);
    ...
}
```

**关键逻辑**：
- 查询 `AVCodecList::GetCapability(mime, false, AVCODEC_HARDWARE)` 获取硬件 decoder
- 判断 `capabilityData->isVendor == true`（厂商提供=硬件）
- 使用 `VideoDecoderFactory::CreateByName(codecName)` 创建硬件 Codec 实例

### 5.2 普通场景（软/硬自动选择）

```cpp
// line 125-128
Status SurfaceDecoderAdapter::Init(const std::string &mime)
{
    int ret = MediaAVCodec::VideoDecoderFactory::CreateByMime(mime, format, codecServer_);
    // CreateByMime 内部通过 MIME 类型自动选择 codec（可能软可能硬）
}
```

- `VideoDecoderFactory::CreateByMime` 根据 MIME 类型自动选择合适的 codec
- 由工厂内部根据系统能力决定走软件还是硬件

---

## 6. SurfaceEncoderAdapter 的编码路径

**文件**: `services/media_engine/filters/surface_encoder_adapter.cpp`

```cpp
// line 131-134
Status SurfaceEncoderAdapter::Init(const std::string &mime, bool isEncoder)
{
    // 不区分软硬，统一走 CreateByMime
    int32_t ret = MediaAVCodec::VideoEncoderFactory::CreateByMime(mime, format, codecServer_);
    if (!codecServer_) {
        MEDIA_LOG_I("Create codecServer failed");
        return Status::ERROR_UNKNOWN;
    }
    ...
}
```

**特点**：
- 编码器统一通过 `VideoEncoderFactory::CreateByMime` 创建
- 不做显式的软/硬判断（由工厂层自动选择）
- Surface 编码场景走 `SurfaceEncoderAdapter` → `VideoEncoderFactory::CreateByMime`

---

## 7. 软件编解码插件注册机制

### 7.1 能力注册（GetCodecCapability）

FCodec 通过 `fcodec_capability_register.cpp` 注册自己的能力到系统 CodecList：

```cpp
// services/engine/codec/video/fcodec/fcodec_capability_register.cpp
int32_t FCodec::GetCodecCapability(std::vector<CapabilityData> &capaArray)
{
    // 填充支持的 MIME 类型、分辨率、profile 等能力
}
```

### 7.2 创建函数导出

```cpp
// libfcodec.z.so 导出的两个标准符号
extern "C" __attribute__((visibility("default")))
std::shared_ptr<OHOS::MediaAVCodec::CodecBase> CreateFCodecByName(const std::string &name)
{
    return std::make_shared<FCodec>(name);
}

extern "C" __attribute__((visibility("default")))
int32_t GetFCodecCapabilityList(std::vector<OHOS::MediaAVCodec::CapabilityData> &caps)
{
    return FCodec::GetCodecCapability(caps);
}
```

**每个 Codec 插件必须导出两个符号**：
- `Create<FCodec/HCodec>ByName` — 按名称创建实例
- `Get<FCodec/HCodec>CapabilityList` — 查询能力列表

---

## 8. 关键文件索引

| 文件 | 职责 |
|------|------|
| `services/engine/base/include/codecbase.h` | CodecBase 基类（虚方法定义） |
| `services/engine/codec/video/fcodec/include/fcodec.h` | FCodec 软件编解码实现类 |
| `services/engine/codec/video/fcodec_loader.cpp` | FCodecLoader（dlopen 加载 libfcodec.z.so） |
| `services/engine/codec/video/hcodec_loader.cpp` | HCodecLoader（dlopen 加载 libhcodec.z.so） |
| `services/services/codec/server/video/codec_factory.cpp` | CodecFactory（软/硬分发决策） |
| `services/media_engine/filters/surface_decoder_adapter.cpp` | SurfaceDecoderAdapter（软硬判断 + 适配） |
| `services/media_engine/filters/surface_encoder_adapter.cpp` | SurfaceEncoderAdapter（编码适配） |
| `services/media_engine/filters/surface_encoder_filter.cpp` | SurfaceEncoderFilter（Filter 层编码 Filter） |
| `interfaces/inner_api/native/surface_decoder_filter.h` | SurfaceDecoderFilter 头文件 |

---

## 9. 关联已入库条目

| 关联 | 说明 |
|------|------|
| **MEM-ARCH-AVCODEC-003** | Plugin 架构（demuxer/muxer/source/sink 四类插件） |
| **MEM-ARCH-AVCODEC-009** | 硬件 vs 软件 Codec 区分（isVendor / IsSoftwareOnly） |
| **MEM-ARCH-AVCODEC-014** | Codec Engine 架构（CodecBase + Loader + Factory 三层） |
| **MEM-ARCH-AVCODEC-015** | Codec 实例生命周期（Create→Configure→Start→Stop→Release） |
| **MEM-ARCH-AVCODEC-016** | AVBufferQueue 异步编解码（输入/输出队列与 TaskThread） |

---

## 10. 场景关联

| 场景 | 说明 |
|------|------|
| **新人入项** | 理解 CodecBase 基类 → FCodec/HCodec 分工 → Loader 加载逻辑 → 分发决策 |
| **软硬切换问题定位** | SurfaceDecoderAdapter Init 中 isVendor 判断 → CodecFactory 分发 → FCodecLoader vs HCodecLoader |
| **新需求开发** | 新增软件 Codec → 实现 FCodec 子类 + 注册 FCodecLoader 路径 + 导出两个标准符号 |