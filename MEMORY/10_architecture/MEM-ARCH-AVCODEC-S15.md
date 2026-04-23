---
type: architecture
id: MEM-ARCH-AVCODEC-S15
title: SuperResolutionPostProcessor 超分辨率后处理器——VPE DetailEnhancer 与 VideoPostProcessor 插件注册机制
status: draft
created_by: builder-agent
created_at: "2026-04-24T04:10:00+08:00"
scope: [AVCodec, MediaEngine, PostProcessor, SuperResolution, VPE, DetailEnhancer, VideoProcessingEngine, Plugin]
related_scenes: [新需求开发, 问题定位, 视频超分, 后处理, Pipeline增强]
confidence: medium-high
evidence:
  - source: /home/west/av_codec_repo/services/media_engine/modules/post_processor/super_resolution_post_processor.h
    anchor: Line 28-66: class SuperResolutionPostProcessor : public BaseVideoPostProcessor
  - source: /home/west/av_codec_repo/services/media_engine/modules/post_processor/super_resolution_post_processor.cpp
    anchor: Line 30: using namespace VideoProcessingEngine
  - source: /home/west/av_codec_repo/services/media_engine/modules/post_processor/super_resolution_post_processor.cpp
    anchor: Line 32-52: isSuperResolutionSupported() meta check logic
  - source: /home/west/av_codec_repo/services/media_engine/modules/post_processor/super_resolution_post_processor.cpp
    anchor: Line 55-63: AutoRegisterPostProcessor g_registerSuperResolutionPostProcessor
  - source: /home/west/av_codec_repo/services/media_engine/modules/post_processor/super_resolution_post_processor.cpp
    anchor: Line 67-120: VPECallback class
  - source: /home/west/av_codec_repo/services/media_engine/modules/post_processor/super_resolution_post_processor.cpp
    anchor: Line 125-130: SuperResolutionPostProcessor constructor, VpeVideo::Create(VIDEO_TYPE_DETAIL_ENHANCER)
  - source: /home/west/av_codec_repo/services/media_engine/modules/post_processor/super_resolution_post_processor.cpp
    anchor: Line 308-318: SetQualityLevel, DETAIL_ENHANCER_QUALITY_LEVEL
  - source: /home/west/av_codec_repo/services/media_engine/modules/post_processor/super_resolution_post_processor.cpp
    anchor: Line 319-330: SetVideoWindowSize, DETAIL_ENHANCER_TARGET_SIZE
  - source: /home/west/av_codec_repo/services/media_engine/modules/post_processor/super_resolution_post_processor.cpp
    anchor: Line 333-339: OnError, OnSuperResolutionChanged
  - source: /home/west/av_codec_repo/services/media_engine/modules/post_processor/base_video_post_processor.h
    anchor: Line 40-45: enum VideoPostProcessorType { NONE, SUPER_RESOLUTION, CAMERA_INSERT_FRAME, CAMERA_MP_PWP }
  - source: /home/west/av_codec_repo/services/media_engine/modules/post_processor/base_video_post_processor.h
    anchor: Line 47-81: BaseVideoPostProcessor abstract interface
  - source: /home/west/av_codec_repo/services/media_engine/modules/post_processor/video_post_processor_factory.cpp
    anchor: CreateVideoPostProcessorPriv, IsPostProcessorSupportedPriv
summary: |
  SuperResolutionPostProcessor 是 AVCodec MediaEngine 的**视频超分辨率（Super Resolution）后处理器**，基于 VideoProcessingEngine (VPE) 的 DetailEnhancer 算法对输入视频进行 AI 上采样。
  通过 AutoRegisterPostProcessor 插件注册机制自动接入 Pipeline；支持按视频尺寸（≤1920×1080）、DRM状态、HDR类型等条件动态判断是否启用。
  VideoPostProcessorType 枚举还包含 CAMERA_INSERT_FRAME 和 CAMERA_MP_PWP 两种后处理类型，三者共享 BaseVideoPostProcessor 框架。
why_it_matters:
  - 新需求开发：了解超分后处理的启用条件（尺寸限制、非DRM、非HDR Vivid），避免在不支持场景配置超分
  - 问题定位：超分开启后视频出现伪影/花屏，需排查 VPE DetailEnhancer 的 OnError/OnSuperResolutionChanged 回调
  - 性能分析：超分是 GPU/NPU 密集型操作，仅在 1080p 及以下生效；4K 视频不会触发超分
  - 插件扩展：AutoRegisterPostProcessor 机制与 Filter/AudioCodec 插件机制平行，可注册新的后处理类型
---

# MEM-ARCH-AVCODEC-S15: SuperResolutionPostProcessor 超分辨率后处理器

## Metadata

| 字段 | 值 |
|------|-----|
| id | MEM-ARCH-AVCODEC-S15 |
| title | SuperResolutionPostProcessor 超分辨率后处理器——VPE DetailEnhancer 与 VideoPostProcessor 插件注册机制 |
| scope | [AVCodec, MediaEngine, PostProcessor, SuperResolution, VPE, DetailEnhancer, VideoProcessingEngine, Plugin] |
| status | draft |
| created_by | builder-agent |
| created_at | 2026-04-24 |
| confidence | medium-high |
| related_scenes | [新需求开发, 问题定位, 视频超分, 后处理, Pipeline增强] |

---

## 1. 概述

SuperResolutionPostProcessor 是 MediaEngine Pipeline 中的**超分辨率（Super Resolution）后处理器**，位于视频解码器与显示输出之间，对解码帧进行 AI 上采样以提升画质。

**核心技术**：基于 VideoProcessingEngine (VPE) 的 DetailEnhancer（细节增强）算法，通过 VpeVideo::Create(VIDEO_TYPE_DETAIL_ENHANCER) 创建 VPE 实例。

**启用条件**（`isSuperResolutionSupported`）：
- 视频分辨率 ≤ 1920×1080
- 非 DRM 加密内容（`!isDrmProtected`）
- 非 HDR Vivid（`!isHdrVivid`）

---

## 2. VideoPostProcessor 架构

### 2.1 VideoPostProcessorType 枚举

**证据**：`base_video_post_processor.h` 行 40-45

```cpp
enum VideoPostProcessorType {
    NONE,
    SUPER_RESOLUTION,       // 视频超分辨率（本条目主题）
    CAMERA_INSERT_FRAME,     // 相机插帧
    CAMERA_MP_PWP,           // 相机 MP PWP
};
```

### 2.2 BaseVideoPostProcessor 抽象基类

**证据**：`base_video_post_processor.h` 行 47-81

```cpp
class BaseVideoPostProcessor {
public:
    virtual Status Init() = 0;
    virtual Status Flush() = 0;
    virtual Status Stop() = 0;
    virtual Status Start() = 0;
    virtual Status Release() = 0;
    virtual Status Pause() { return Status::OK; }
    virtual Status NotifyEos(int64_t eosPts = 0) { return Status::OK; }

    virtual sptr<Surface> GetInputSurface() = 0;           // 输入 Surface
    virtual Status SetOutputSurface(sptr<Surface> surface) = 0;  // 输出 Surface

    virtual Status ReleaseOutputBuffer(uint32_t index, bool render) = 0;
    virtual Status RenderOutputBufferAtTime(uint32_t index, int64_t renderTimestampNs) = 0;

    virtual Status SetCallback(const std::shared_ptr<PostProcessorCallback> callback) = 0;
    virtual Status SetEventReceiver(const std::shared_ptr<Pipeline::EventReceiver> &receiver) = 0;

    virtual Status SetParameter(const Format &format) = 0;
    virtual Status SetPostProcessorOn(bool isPostProcessorOn) = 0;
    virtual Status SetVideoWindowSize(int32_t width, int32_t height) = 0;
    virtual Status StartSeekContinous() { return Status::OK; }
};
```

### 2.3 VideoPostProcessorFactory 工厂

**证据**：`video_post_processor_factory.cpp`

```cpp
VideoPostProcessorFactory& VideoPostProcessorFactory::Instance()
{
    static VideoPostProcessorFactory instance;
    return instance;
}

std::shared_ptr<BaseVideoPostProcessor> VideoPostProcessorFactory::CreateVideoPostProcessorPriv(
    const VideoPostProcessorType type)
{
    auto it = generators_.find(type);
    if (it != generators_.end()) {
        return it->second();
    }
    return nullptr;
}

bool VideoPostProcessorFactory::IsPostProcessorSupportedPriv(const VideoPostProcessorType type,
                                                             const std::shared_ptr<Meta>& meta)
{
    auto it = checkers_.find(type);
    if (it != checkers_.end()) {
        return it->second(meta);
    }
    return false;
}
```

---

## 3. SuperResolutionPostProcessor 核心实现

### 3.1 类声明

**证据**：`super_resolution_post_processor.h` 行 28-66

```cpp
class SuperResolutionPostProcessor : public BaseVideoPostProcessor,
                                     public std::enable_shared_from_this<SuperResolutionPostProcessor> {
public:
    SuperResolutionPostProcessor();
    ~SuperResolutionPostProcessor() override;

    bool IsValid();
    Status Init() override;
    Status Flush() override;
    Status Stop() override;
    Status Start() override;
    Status Release() override;
    Status NotifyEos(int64_t eosPts = 0) override;

    sptr<Surface> GetInputSurface() override;
    Status SetOutputSurface(sptr<Surface> surface) override;

    Status SetCallback(const std::shared_ptr<PostProcessorCallback> callback) override;
    Status SetEventReceiver(const std::shared_ptr<Pipeline::EventReceiver> &receiver) override;

    Status SetParameter(const Format &format) override;
    Status SetPostProcessorOn(bool isPostProcessorOn) override;
    Status SetQualityLevel(DetailEnhancerQualityLevel level);

    static constexpr DetailEnhancerQualityLevel DEFAULT_QUALITY_LEVEL =
        DetailEnhancerQualityLevel::DETAIL_ENHANCER_LEVEL_HIGH;

    std::shared_ptr<VideoProcessingEngine::VpeVideo> postProcessor_ {nullptr};
    // ...
};
```

### 3.2 构造函数与 VPE 创建

**证据**：`super_resolution_post_processor.cpp` 行 125-130

```cpp
SuperResolutionPostProcessor::SuperResolutionPostProcessor()
{
    // 创建 VPE DetailEnhancer 实例
    postProcessor_ = VpeVideo::Create(VIDEO_TYPE_DETAIL_ENHANCER);
    isPostProcessorOn_ = true;
}
```

**关键**：使用 `VpeVideo::Create(VIDEO_TYPE_DETAIL_ENHANCER)` 创建 VPE 视频处理引擎实例，而非直接构造。这是华为 VPE（Video Processing Engine）库的封装。

### 3.3 Init 流程

**证据**：`super_resolution_post_processor.cpp` 行 142-154

```cpp
Status SuperResolutionPostProcessor::Init()
{
    MEDIA_LOG_D("Init in");
    std::shared_lock<std::shared_mutex> lock(mutex_);
    FALSE_RETURN_V(postProcessor_ != nullptr, Status::ERROR_INVALID_STATE);

    // 设置默认质量级别（DETAIL_ENHANCER_LEVEL_HIGH）
    auto ret = SetQualityLevel(DEFAULT_QUALITY_LEVEL);
    FALSE_RETURN_V(ret == Status::OK, ret);

    // 注册 VPECallback 到 VPE 实例
    auto callback = std::make_shared<VPECallback>(shared_from_this());
    return postProcessor_->RegisterCallback(callback) == VPEAlgoErrCode::VPE_ALGO_ERR_OK ?
        Status::OK : Status::ERROR_INVALID_STATE;
}
```

### 3.4 VPECallback 回调类

**证据**：`super_resolution_post_processor.cpp` 行 67-120

```cpp
class VPECallback : public VpeVideoCallback {
public:
    explicit VPECallback(std::shared_ptr<SuperResolutionPostProcessor> postProcessor)
        : postProcessor_(postProcessor) {}

    void OnError(VPEAlgoErrCode errorCode)
    {
        if (auto postProcessor = postProcessor_.lock()) {
            postProcessor->OnError(errorCode);
        }
    }

    void OnState(VPEAlgoState state)
    {
        if (auto postProcessor = postProcessor_.lock()) {
            // 通知超分状态变更（启用/禁用）
            postProcessor->OnSuperResolutionChanged(type == VIDEO_TYPE_DETAIL_ENHANCER);
        }
    }

    void OnOutputBufferAvailable(uint32_t index, const VpeBufferInfo& info)
    {
        if (auto postProcessor = postProcessor_.lock()) {
            postProcessor->OnOutputBufferAvailable(index, info);
        }
    }
};
```

---

## 4. 启用条件判断

### 4.1 isSuperResolutionSupported 完整逻辑

**证据**：`super_resolution_post_processor.cpp` 行 32-52

```cpp
static bool isSuperResolutionSupported(const std::shared_ptr<Meta>& meta)
{
    FALSE_RETURN_V(meta != nullptr, false);

    int32_t width = 0;
    int32_t height = 0;
    bool isDrmProtected = false;
    bool isHdrVivid = false;

    meta->GetData(Tag::VIDEO_WIDTH, width);
    meta->GetData(Tag::VIDEO_HEIGHT, height);
    meta->GetData(Tag::VIDEO_IS_HDR_VIVID, isHdrVivid);
    meta->GetData(Tag::AV_PLAYER_IS_DRM_PROTECTED, isDrmProtected);

    // 尺寸限制：最大 1920×1080
    bool isVideoSizeValid = (width > 0 && width <= MAX_WIDTH) &&
                            (height > 0 && height <= MAX_HEIGHT);

    // 三不原则：不 DRM、不 HDR Vivid、尺寸合规
    bool canCreatePostProcessor = !isDrmProtected && !isHdrVivid && isVideoSizeValid;

    if (!canCreatePostProcessor) {
        MEDIA_LOG_E("invalid input stream for super resolution! "
            "width: %{public}d, height: %{public}d, "
            "isHdrVivid: %{public}d, drm: %{public}d",
            width, height, isHdrVivid, isDrmProtected);
    }
    return canCreatePostProcessor;
}
```

### 4.2 尺寸限制常量

**证据**：`super_resolution_post_processor.cpp` 行 29-30

```cpp
namespace {
constexpr int32_t MAX_WIDTH = 1920;
constexpr int32_t MAX_HEIGHT = 1080;
}
```

**结论**：超分仅对 1920×1080 及以下的非DRM、非HDR Vivid 视频生效。

---

## 5. 质量控制

### 5.1 SetQualityLevel

**证据**：`super_resolution_post_processor.cpp` 行 308-318

```cpp
Status SuperResolutionPostProcessor::SetQualityLevel(DetailEnhancerQualityLevel level)
{
    MEDIA_LOG_D("SetQualityLevel in");
    Format parameter;
    parameter.PutIntValue(ParameterKey::DETAIL_ENHANCER_QUALITY_LEVEL, level);
    parameter.PutIntValue(ParameterKey::DETAIL_ENHANCER_AUTO_DOWNSHIFT, 0);  // 禁用自动降级
    auto ret = postProcessor_->SetParameter(parameter);
    FALSE_RETURN_V(ret == VPEAlgoErrCode::VPE_ALGO_ERR_OK, Status::ERROR_INVALID_PARAMETER);
    return Status::OK;
}
```

**默认级别**：`DETAIL_ENHANCER_LEVEL_HIGH`（高质量）

### 5.2 SetVideoWindowSize（目标分辨率）

**证据**：`super_resolution_post_processor.cpp` 行 319-330

```cpp
Status SuperResolutionPostProcessor::SetVideoWindowSize(int32_t width, int32_t height)
{
    MEDIA_LOG_D("SetVideoWindowSize in");
    std::shared_lock<std::shared_mutex> lock(mutex_);
    FALSE_RETURN_V(postProcessor_ != nullptr, Status::ERROR_INVALID_STATE);

    Format parameter;
    VpeBufferSize outputSize = { width, height };
    parameter.PutBuffer(ParameterKey::DETAIL_ENHANCER_TARGET_SIZE,
        reinterpret_cast<const uint8_t*>(&outputSize), sizeof(VpeBufferSize));
    auto ret = postProcessor_->SetParameter(parameter);
    FALSE_RETURN_V(ret == VPEAlgoErrCode::VPE_ALGO_ERR_OK, Status::ERROR_INVALID_PARAMETER);
    return Status::OK;
}
```

**注意**：`SetVideoWindowSize` 设置的是**输出目标分辨率**，而非输入分辨率。VPE 内部会将输入帧上采样到指定目标尺寸。

---

## 6. 插件注册机制

### 6.1 AutoRegisterPostProcessor 自动注册

**证据**：`super_resolution_post_processor.cpp` 行 55-63

```cpp
static AutoRegisterPostProcessor<SuperResolutionPostProcessor> g_registerSuperResolutionPostProcessor(
    VideoPostProcessorType::SUPER_RESOLUTION,   // 类型名
    []() -> std::shared_ptr<BaseVideoPostProcessor> {
        auto postProcessor = std::make_shared<SuperResolutionPostProcessor>();
        if (postProcessor == nullptr || !postProcessor->IsValid()) {
            return nullptr;  // VPE 实例创建失败则返回 nullptr
        } else {
            return postProcessor;
        }
    },
    &isSuperResolutionSupported  // 支持性检查函数
);
```

**机制**：
1. 静态对象在进程启动时自动构造
2. 调用 `VideoPostProcessorFactory` 的内部注册方法将 `(type, generator, checker)` 三元组存入 `generators_` 和 `checkers_` map
3. Pipeline 查询支持性时调用 `IsPostProcessorSupportedPriv(SUPER_RESOLUTION, meta)`
4. Pipeline 创建实例时调用 `CreateVideoPostProcessorPriv(SUPER_RESOLUTION)`

---

## 7. 生命周期

```
Pipeline 启动
  → VideoPostProcessorFactory::IsPostProcessorSupportedPriv(SUPER_RESOLUTION, meta)
      → isSuperResolutionSupported(meta) → bool
  → 若支持：CreateVideoPostProcessorPriv(SUPER_RESOLUTION)
      → new SuperResolutionPostProcessor()
      → VpeVideo::Create(VIDEO_TYPE_DETAIL_ENHANCER)
      → Init()
          → SetQualityLevel(DEFAULT_QUALITY_LEVEL)
          → RegisterCallback(VPECallback)

运行时：
  → Start() → postProcessor_->Start()
  → 每帧：GetInputSurface() → VPE 处理 → SetOutputSurface() → RenderOutputBufferAtTime()
  → SetVideoWindowSize(w, h) 可动态调整目标分辨率

停止：
  → Stop() → Flush() → Release()
  → VPE 实例销毁
```

---

## 8. 事件与回调

| 事件 | 触发条件 | 处理 |
|------|---------|------|
| `OnError` | VPE 算法错误 | 调用 `filterCallback_->OnError()` 上报 Pipeline |
| `OnSuperResolutionChanged` | VPE 内部超分状态变更 | 通过 `eventReceiver_->OnEvent(EVENT_SUPER_RESOLUTION_CHANGED)` 通知 |
| `OnOutputFormatChanged` | VPE 输出格式变化 | 转发给 Pipeline Filter 回调 |

---

## 9. 与其他记忆条目的关联

| 条目 | 关联点 |
|------|--------|
| **MEM-ARCH-AVCODEC-S14**（Filter Chain） | SuperResolutionPostProcessor 位于 Filter Chain 末端，属于 Pipeline 后处理环节 |
| **MEM-ARCH-AVCODEC-S3**（CodecServer Pipeline） | Pipeline 中的 PostProcessor slot 由 MediaEngine 管理 |
| **MEM-ARCH-AVCODEC-004**（VideoResizeFilter） | 两者都是视频处理过滤器；VideoResizeFilter 处理编码前缩放，SuperResolutionPostProcessor 处理解码后超分 |

---

## 10. 关键调试参数

```bash
# 超分开启/关闭
# 查看 SuperResolutionChanged 事件
adb shell "hidumper -s 1301 -a 0" | grep -i super

# 查看 VPE 错误
adb shell "hilog -x" | grep "SuperResolution\|VPE_ALGO_ERR\|DetailEnhancer"

# VPE Log domain
LOG_DOMAIN_SYSTEM_PLAYER (hilog domain for SuperResolutionPostProcessor)

# 启用条件判断日志（isSuperResolutionSupported 失败时输出）
"invalid input stream for super resolution! width: %d, height: %d, isHdrVivid: %d, drm: %d"
```

---

## 11. 相关文件索引

| 文件 | 作用 |
|------|------|
| `services/media_engine/modules/post_processor/super_resolution_post_processor.h` | SuperResolutionPostProcessor 类声明 |
| `services/media_engine/modules/post_processor/super_resolution_post_processor.cpp` | 完整实现（357行） |
| `services/media_engine/modules/post_processor/base_video_post_processor.h` | BaseVideoPostProcessor 基类 + VideoPostProcessorType 枚举 |
| `services/media_engine/modules/post_processor/video_post_processor_factory.cpp` | VideoPostProcessorFactory 工厂 |
| `services/media_engine/modules/post_processor/video_post_processor_factory.h` | AutoRegisterPostProcessor 注册宏 |

---

## 变更记录

| 日期 | 操作 | 说明 |
|------|------|------|
| 2026-04-24 | 新建草案 | builder-agent 探索 local repo，发现 SuperResolutionPostProcessor 后处理架构，生成 S15 草案 |
