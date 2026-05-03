---
type: architecture
id: MEM-ARCH-AVCODEC-S15
status: pending_approval
topic: SuperResolutionPostProcessor 超分辨率后处理器——VPE DetailEnhancer 与 VideoPostProcessor 插件注册机制
submitted_at: "2026-05-03T13:33:00+08:00"
scope: [AVCodec, MediaEngine, PostProcessor, SuperResolution, VPE, DetailEnhancer, VideoProcessingEngine, Plugin]
created_at: "2026-05-03T13:33:00+08:00"
author: builder-agent
evidence: |
  - source: services/media_engine/modules/post_processor/super_resolution_post_processor.cpp line 35-53
    anchor: "isSuperResolutionSupported() — 超分条件判断"
    note: 非DRM(AV_PLAYER_IS_DRM_PROTECTED=false)、非HDR Vivid(isHdrVivid=false)、分辨率≤1920×1080(width>0&&width<=MAX_WIDTH&&height>0&&height<=MAX_HEIGHT)
  - source: services/media_engine/modules/post_processor/super_resolution_post_processor.cpp line 55-64
    anchor: "AutoRegisterPostProcessor<SuperResolutionPostProcessor> g_registerSuperResolutionPostProcessor"
    note: 静态注册到 VideoPostProcessorFactory，type=SUPER_RESOLUTION，generator创建shared_ptr，checker=isSuperResolutionSupported
  - source: services/media_engine/modules/post_processor/super_resolution_post_processor.cpp line 125-128
    anchor: "SuperResolutionPostProcessor::SuperResolutionPostProcessor()"
    note: 构造函数调用 VpeVideo::Create(VIDEO_TYPE_DETAIL_ENHANCER) 创建 VPE DetailEnhancer 实例
  - source: services/media_engine/modules/post_processor/super_resolution_post_processor.cpp line 40-52
    anchor: "constexpr int32_t MAX_WIDTH = 1920; constexpr int32_t MAX_HEIGHT = 1080;"
    note: 超分仅支持≤1920×1080分辨率，超出条件则不创建PostProcessor
  - source: services/media_engine/modules/post_processor/super_resolution_post_processor.cpp line 279-288
    anchor: "SetQualityLevel(DEFAULT_QUALITY_LEVEL)"
    note: 默认质量级别 DETAIL_ENHANCER_LEVEL_HIGH，AutoDownshift=0禁用自动降级
  - source: services/media_engine/modules/post_processor/super_resolution_post_processor.cpp line 67-122
    anchor: "class VPECallback : public VpeVideoCallback"
    note: VPECallback桥接VPE回调与PostProcessor：OnOutputBufferAvailable驱动buffer传递，OnSuperResolutionChanged触发EVENT_SUPER_RESOLUTION_CHANGED事件
  - source: services/media_engine/modules/post_processor/base_video_post_processor.h line 20-25
    anchor: "enum VideoPostProcessorType { NONE, SUPER_RESOLUTION, CAMERA_INSERT_FRAME, CAMERA_MP_PWP }"
    note: VideoPostProcessorType枚举三种后处理器类型，SUPER_RESOLUTION=1
  - source: services/media_engine/modules/post_processor/base_video_post_processor.h line 35-68
    anchor: "class BaseVideoPostProcessor — 虚基类接口"
    note: 基类定义Init/Start/Stop/Flush/Release/GetInputSurface/SetOutputSurface/SetParameter/SetPostProcessorOn/SetVideoWindowSize等虚方法
  - source: services/media_engine/modules/post_processor/video_post_processor_factory.h line 78-97
    anchor: "template <typename T> class AutoRegisterPostProcessor"
    note: CRTP模板静态注册三参数构造(VideoPostProcessorType+Generator+Checker)，于main()前执行
  - source: services/media_engine/modules/post_processor/video_post_processor_factory.h line 30-45
    anchor: "VideoPostProcessorFactory::CreateVideoPostProcessor<T>()"
    note: 工厂模板方法：ReinterpretPointerCast<T>(CreateVideoPostProcessorPriv(type))
  - source: services/media_engine/filters/decoder_surface_filter.cpp line 1694-1707
    anchor: "DecoderSurfaceFilter::CreatePostProcessor()"
    note: DecoderSurfaceFilter创建PostProcessor：decoderOutputSurface_=postProcessor->GetInputSurface()→videoDecoder_->SetOutputSurface()→postProcessor_->SetOutputSurface(videoSurface_)
  - source: services/media_engine/filters/decoder_surface_filter.cpp line 927-929
    anchor: "DecoderSurfaceFilter::IsPostProcessorSupported()"
    note: 调用 VideoPostProcessorFactory::Instance().IsPostProcessorSupported(postProcessorType_, meta_) 判断是否支持
  - source: services/media_engine/filters/decoder_surface_filter.cpp line 977-989
    anchor: "DecoderSurfaceFilter::OnLinked() — PostProcessor初始化流程"
    note: OnLinked中InitPostProcessorType→IsPostProcessorSupported→CreatePostProcessor→设置FilterVideoPostProcessorCallback
  - source: services/media_engine/filters/decoder_surface_filter.cpp line 115-136
    anchor: "class FilterVideoPostProcessorCallback : public PostProcessorCallback"
    note: Filter层回调桥接：OnOutputBufferAvailable→filter端处理，OnOutputFormatChanged→更新Filter元数据
  - source: services/media_engine/modules/post_processor/super_resolution_post_processor.cpp line 298-317
    anchor: "SuperResolutionPostProcessor::SetVideoWindowSize()"
    note: SetVideoWindowSize通过DETAIL_ENHANCER_TARGET_SIZE参数设置输出尺寸，控制超分后输出分辨率
  - source: services/media_engine/modules/post_processor/super_resolution_post_processor.cpp line 324-333
    anchor: "SuperResolutionPostProcessor::OnSuperResolutionChanged(bool enable)"
    note: VPE回调OnSuperResolutionChanged触发EVENT_SUPER_RESOLUTION_CHANGED事件，isPostProcessorOn_标志更新
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
| created_at | 2026-05-03 |
| type | architecture_fact |
| confidence | high |

---

## 摘要

SuperResolutionPostProcessor 是 MediaEngine 视频管线中的超分辨率后处理器插件，基于 VPE（Video Processing Engine）DetailEnhancer 实现。DecoderSurfaceFilter 解码过滤器在 Surface 模式下通过 VideoPostProcessorFactory 工厂按需创建该 PostProcessor，实现≤1920×1080 视频的 AI 超分辨率增强。

---

## 1. 类层次结构

```
BaseVideoPostProcessor（抽象基类，post_processor/base_video_post_processor.h:35-68）
  └── SuperResolutionPostProcessor（super_resolution_post_processor.cpp:28-29）
        ├── enable_shared_from_this<SuperResolutionPostProcessor>
        └── 持有 std::shared_ptr<VpeVideo> postProcessor_（VPE DetailEnhancer 实例）
```

### 1.1 BaseVideoPostProcessor 虚基类接口

定义于 `base_video_post_processor.h:35-68`，包含：

| 方法 | 说明 |
|------|------|
| `Init()` / `Start()` / `Stop()` / `Flush()` / `Release()` | 生命周期管理 |
| `GetInputSurface()` / `SetOutputSurface()` | Surface 绑定 |
| `SetParameter()` / `SetQualityLevel()` | 参数配置 |
| `SetPostProcessorOn(bool)` | 使能/禁用超分 |
| `SetVideoWindowSize(w, h)` | 输出分辨率设置 |
| `SetCallback(PostProcessorCallback)` | 回调设置 |
| `NotifyEos(int64_t)` | 结束信号 |

### 1.2 VideoPostProcessorType 枚举

定义于 `base_video_post_processor.h:20-25`：

```cpp
enum VideoPostProcessorType {
    NONE,              // 0: 无后处理
    SUPER_RESOLUTION,   // 1: 超分辨率（本文档主题）
    CAMERA_INSERT_FRAME, // 2: 相机插入帧
    CAMERA_MP_PWP,       // 3: 相机 MP PWP
};
```

---

## 2. 超分条件判断（isSuperResolutionSupported）

定义于 `super_resolution_post_processor.cpp:35-53`，静态函数作为 AutoRegister 的 Checker：

```cpp
static bool isSuperResolutionSupported(const std::shared_ptr<Meta>& meta)
{
    // 条件1：分辨率 ≤ 1920×1080
    bool isVideoSizeValid = (width > 0 && width <= MAX_WIDTH) &&
                            (height > 0 && height <= MAX_HEIGHT);
    // 条件2：非 DRM 保护内容
    bool canCreatePostProcessor = !isDrmProtected && !isHdrVivid && isVideoSizeValid;
    return canCreatePostProcessor;
}
```

| 条件 | Tag | 通过条件 |
|------|-----|---------|
| 视频分辨率 | Tag::VIDEO_WIDTH/HEIGHT | 0 < w ≤ 1920 且 0 < h ≤ 1080 |
| DRM 保护 | Tag::AV_PLAYER_IS_DRM_PROTECTED | `false` |
| HDR Vivid | Tag::VIDEO_IS_HDR_VIVID | `false` |

超出以上任一条件时，VideoPostProcessorFactory.IsPostProcessorSupported() 返回 `false`，DecoderSurfaceFilter 不创建 PostProcessor 实例。

---

## 3. 插件注册机制（AutoRegisterPostProcessor）

### 3.1 静态注册

定义于 `super_resolution_post_processor.cpp:55-64`：

```cpp
static AutoRegisterPostProcessor<SuperResolutionPostProcessor> g_registerSuperResolutionPostProcessor(
    VideoPostProcessorType::SUPER_RESOLUTION, []() -> std::shared_ptr<BaseVideoPostProcessor> {
        auto postProcessor = std::make_shared<SuperResolutionPostProcessor>();
        if (postProcessor == nullptr || !postProcessor->IsValid()) {
            return nullptr;
        } else {
            return postProcessor;
        }
    }, &isSuperResolutionSupported);  // ← 第三参数：条件检查器
```

### 3.2 AutoRegisterPostProcessor CRTP 模板

定义于 `video_post_processor_factory.h:78-97`，三参数构造：

```cpp
AutoRegisterPostProcessor(
    const VideoPostProcessorType type,
    const VideoPostProcessorInstanceGenerator& generator,  // 创建函数
    const VideoPostProcessorSupportChecker& checker         // 支持条件检查
);
```

在 `main()` 之前执行，将 Generator 和 Checker 分别存入工厂的 `generators_` 和 `checkers_` 两个 `unordered_map`。

### 3.3 工厂创建流程

定义于 `video_post_processor_factory.h:30-45` 和 `.cpp`：

```cpp
// DecoderSurfaceFilter::CreatePostProcessor() — decoder_surface_filter.cpp:1694-1707
postProcessor_ = VideoPostProcessorFactory::Instance()
    .CreateVideoPostProcessor<BaseVideoPostProcessor>(postProcessorType_);

// 1. GetInputSurface → videoDecoder_->SetOutputSurface（解码器输出到 VPE）
// 2. SetOutputSurface(videoSurface_)（VPE 输出到渲染 Surface）
```

---

## 4. VPE DetailEnhancer 核心

### 4.1 VpeVideo 创建

定义于 `super_resolution_post_processor.cpp:125-128`：

```cpp
SuperResolutionPostProcessor::SuperResolutionPostProcessor()
{
    postProcessor_ = VpeVideo::Create(VIDEO_TYPE_DETAIL_ENHANCER); // ← VPE 创建 DetailEnhancer
    isPostProcessorOn_ = true;
}
```

`VpeVideo` 是 VPE（Video Processing Engine）库的封装类，通过 `VIDEO_TYPE_DETAIL_ENHANCER` 类型创建超分引擎实例。`VpeVideo::Create` 内部加载 `libvideoprocessingengine.z.so`。

### 4.2 VPECallback 回调桥接

定义于 `super_resolution_post_processor.cpp:67-122`，实现 `VpeVideoCallback` 接口：

```cpp
class VPECallback : public VpeVideoCallback {
    void OnOutputBufferAvailable(uint32_t index, const VpeBufferInfo& info)
    {
        // 转发到 Filter 层回调 filterCallback_->OnOutputBufferAvailable(index, buffer)
    }
    void OnSuperResolutionChanged(bool enable)
    {
        // 触发 EVENT_SUPER_RESOLUTION_CHANGED 事件
        eventReceiver_->OnEvent({"SuperResolutionPostProcessor",
            EventType::EVENT_SUPER_RESOLUTION_CHANGED, enable});
    }
    void OnError(VPEAlgoErrCode errorCode) { ... }
};
```

### 4.3 质量级别配置

定义于 `super_resolution_post_processor.cpp:279-288`：

```cpp
Status SuperResolutionPostProcessor::SetQualityLevel(DetailEnhancerQualityLevel level)
{
    Format parameter;
    parameter.PutIntValue(ParameterKey::DETAIL_ENHANCER_QUALITY_LEVEL, level); // HIGH
    parameter.PutIntValue(ParameterKey::DETAIL_ENHANCER_AUTO_DOWNSHIFT, 0);     // 禁用自动降级
    return postProcessor_->SetParameter(parameter);
}
```

默认级别为 `DETAIL_ENHANCER_LEVEL_HIGH`（定义于 `super_resolution_post_processor.h:40-41`）。

---

## 5. DecoderSurfaceFilter 中的集成

### 5.1 OnLinked 初始化流程

定义于 `decoder_surface_filter.cpp:977-989`：

```
OnLinked(meta)
  → InitPostProcessorType()      // 设置 postProcessorType_ = SUPER_RESOLUTION（如满足条件）
  → IsPostProcessorSupported()   // 调用 VideoPostProcessorFactory::IsPostProcessorSupported
  → CreatePostProcessor()         // 工厂创建 SuperResolutionPostProcessor
  → SetCallback(FilterVideoPostProcessorCallback)
```

### 5.2 FilterVideoPostProcessorCallback

定义于 `decoder_surface_filter.cpp:115-136`，桥接 VPE 回调到 Filter 层：

```cpp
class FilterVideoPostProcessorCallback : public PostProcessorCallback {
    void OnOutputBufferAvailable(uint32_t index, std::shared_ptr<AVBuffer> buffer)
    {
        // 驱动 DecoderSurfaceFilter 的输出buffer处理
    }
    void OnOutputFormatChanged(const Format& format)
    {
        // 更新 Filter 元数据
    }
};
```

### 5.3 SetVideoWindowSize 级联

定义于 `decoder_surface_filter.cpp:1721-1731`：

```cpp
Status DecoderSurfaceFilter::SetVideoWindowSize(int32_t width, int32_t height)
{
    postProcessorTargetWidth_ = width;
    postProcessorTargetHeight_ = height;
    return postProcessor_->SetVideoWindowSize(width, height);
    // → SuperResolutionPostProcessor::SetVideoWindowSize
    // → VPE DETAIL_ENHANCER_TARGET_SIZE 参数
}
```

---

## 6. 生命周期时序

```
DecoderSurfaceFilter 创建
  ↓
OnLinked() → InitPostProcessorType() → IsPostProcessorSupported(SUPER_RESOLUTION, meta)
  ↓ 支持条件满足
CreatePostProcessor() → VpeVideo::Create(VIDEO_TYPE_DETAIL_ENHANCER)
  ↓
Init() → SetQualityLevel(HIGH) → RegisterCallback(VPECallback)
  ↓
Start() → VPE Start
  ↓
运行中：OnOutputBufferAvailable 循环
  ↓
Stop() → Flush() → Release() → postProcessor_ = nullptr
```

---

## 7. 与 S20（PostProcessing 框架）的关系

- **S20** 描述的是 PostProcessing 框架的 DynamicController + DynamicInterface 三组件架构，以及 `libvideoprocessingengine.z.so` 的 dlopen 热加载机制（17个VPE函数符号）
- **S15** 描述的是 PostProcessing 框架的具体实例——SuperResolutionPostProcessor 超分辨率后处理器
- S15 继承自 BaseVideoPostProcessor（虚基类），通过 AutoRegisterPostProcessor CRTP 模板注册到 VideoPostProcessorFactory

---

## 关联主题

| 主题 | 关联说明 |
|------|---------|
| S12 | VideoResizeFilter 转码增强过滤器，使用 DetailEnhancerVideo 视频处理引擎 |
| S16 | SurfaceCodec 与 Surface 的绑定机制，PostProcessor 介入时的双 Surface 转发 |
| S20 | PostProcessing 后处理框架，DynamicController + DynamicInterface + VPE dlopen |
| S46 | DecoderSurfaceFilter 三组件架构（VideoDecoderAdapter + VideoSink + PostProcessor） |
