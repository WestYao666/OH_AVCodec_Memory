---
type: architecture
id: MEM-ARCH-AVCODEC-S127
status: draft
topic: Video PostProcessor Framework 视频后处理框架——BaseVideoPostProcessor + VideoPostProcessorFactory + SuperResolutionPostProcessor 三层架构
scope: [AVCodec, PostProcessor, VPE, SuperResolution, VideoPostProcessorType, AutoRegisterPostProcessor, Surface, Factory, VideoProcessingEngine, DetailEnhancer, BaseVideoPostProcessor, VideoPostProcessorFactory]
created_at: "2026-05-14T08:43:00+08:00"
updated_at: "2026-05-14T08:43:00+08:00"
source_repo: /home/west/av_codec_repo
source_root: services/media_engine/modules/post_processor
evidence_version: local_mirror
---

## 一、架构总览

Video PostProcessor Framework 位于 `services/media_engine/modules/post_processor/` 目录下，分为三个层次：

1. **抽象基类**：`BaseVideoPostProcessor`（`base_video_post_processor.h`，112行）—— 定义七生命周期接口
2. **工厂单例**：`VideoPostProcessorFactory`（`video_post_processor_factory.h`，140行）—— 插件注册与实例化
3. **具体实现**：`SuperResolutionPostProcessor`（`super_resolution_post_processor.h`，77行 / `.cpp`，357行）—— 超分处理器

调用链：**DecoderSurfaceFilter / SurfaceDecoderFilter → VideoPostProcessorFactory::CreateVideoPostProcessor() → SuperResolutionPostProcessor → VpeVideo::Create(VIDEO_TYPE_DETAIL_ENHANCER)**

**关联记忆**：
- S20：PostProcessing 后处理框架（VPE dlopen + DynamicController 三组件）
- S100：PostProcessor Framework 草案（BaseVideoPostProcessor + SuperResolutionPostProcessor + VPE 三层架构）
- S15：SuperResolutionPostProcessor 超分辨率后处理器（VPE DetailEnhancer + 过滤条件）
- S46：DecoderSurfaceFilter 三组件架构（VideoDecoderAdapter + VideoSink + PostProcessor）

---

## 二、BaseVideoPostProcessor 抽象基类

**源码路径**：`services/media_engine/modules/post_processor/base_video_post_processor.h`

### 2.1 头文件结构

```cpp
// base_video_post_processor.h:1-112
enum VideoPostProcessorType {
    NONE,                  // 无后处理
    SUPER_RESOLUTION,      // 超分辨率
    CAMERA_INSERT_FRAME,   // 相机插入帧
    CAMERA_MP_PWP,         // 相机 MP PWP
};

class PostProcessorCallback {
    virtual void OnError(int32_t errorCode) = 0;
    virtual void OnOutputFormatChanged(const Format &format) = 0;
    virtual void OnInputBufferAvailable(uint32_t index, std::shared_ptr<AVBuffer> buffer) = 0;
    virtual void OnOutputBufferAvailable(uint32_t index, std::shared_ptr<AVBuffer> buffer) = 0;
};

class BaseVideoPostProcessor {
    virtual Status Init() = 0;
    virtual Status Flush() = 0;
    virtual Status Stop() = 0;
    virtual Status Start() = 0;
    virtual Status Release() = 0;
    virtual Status Pause() { return Status::OK; }
    virtual Status NotifyEos(int64_t eosPts = 0) { return Status::OK; }

    virtual sptr<Surface> GetInputSurface() = 0;
    virtual Status SetOutputSurface(sptr<Surface> surface) = 0;
    virtual Status ReleaseOutputBuffer(uint32_t index, bool render) = 0;
    virtual Status RenderOutputBufferAtTime(uint32_t index, int64_t renderTimestampNs) = 0;

    virtual Status SetCallback(const std::shared_ptr<PostProcessorCallback> callback) = 0;
    virtual Status SetEventReceiver(const std::shared_ptr<EventReceiver> &receiver) = 0;
    virtual Status SetParameter(const Format &format) = 0;
    virtual Status SetPostProcessorOn(bool isPostProcessorOn) = 0;
    virtual Status SetVideoWindowSize(int32_t width, int32_t height) = 0;
    virtual Status SetFd(int32_t fd) { (void)fd; return Status::OK; }
    virtual Status SetCameraPostProcessing(bool isOpen) { (void)isOpen; return Status::OK; }
    virtual void SetSeekTime(int64_t seekTimeUs, PlayerSeekMode mode) { ... }
    virtual void ResetSeekInfo() {}
    virtual Status SetSpeed(float speed) { (void)speed; return Status::OK; }
};
```

### 2.2 七生命周期接口

| 方法 | 说明 |
|------|------|
| `Init()` | 初始化 |
| `Flush()` | 清空缓冲区 |
| `Stop()` | 停止 |
| `Start()` | 启动 |
| `Release()` | 释放资源 |
| `Pause()` | 暂停（默认 OK 空实现） |
| `NotifyEos()` | EOS 通知（默认 OK 空实现） |

---

## 三、VideoPostProcessorFactory 工厂单例

**源码路径**：`services/media_engine/modules/post_processor/video_post_processor_factory.h`

### 3.1 工厂类结构

```cpp
// video_post_processor_factory.h:1-140
using VideoPostProcessorInstanceGenerator = std::function<std::shared_ptr<BaseVideoPostProcessor>()>;
using VideoPostProcessorSupportChecker = std::function<bool(const std::shared_ptr<Meta>& meta)>;

class VideoPostProcessorFactory {
    static VideoPostProcessorFactory& Instance();

    template <typename T>
    std::shared_ptr<T> CreateVideoPostProcessor(const VideoPostProcessorType type);

    bool IsPostProcessorSupported(const VideoPostProcessorType type, const std::shared_ptr<Meta>& meta);

    template <typename T>
    void RegisterPostProcessor(const VideoPostProcessorType type,
        const VideoPostProcessorInstanceGenerator& generator = nullptr);

    void RegisterChecker(const VideoPostProcessorType type,
        const VideoPostProcessorSupportChecker& checker = nullptr);

private:
    std::unordered_map<VideoPostProcessorType, VideoPostProcessorInstanceGenerator> generators_;
    std::unordered_map<VideoPostProcessorType, VideoPostProcessorSupportChecker> checkers_;
};
```

### 3.2 AutoRegisterPostProcessor CRTP 自动注册模板

```cpp
// video_post_processor_factory.h:80-98
template <typename T>
class AutoRegisterPostProcessor {
public:
    explicit AutoRegisterPostProcessor(const VideoPostProcessorType type,
        const VideoPostProcessorInstanceGenerator& generator = nullptr,
        const VideoPostProcessorSupportChecker& checker = nullptr)
    {
        VideoPostProcessorFactory::Instance().RegisterPostProcessor<T>(type, generator);
        VideoPostProcessorFactory::Instance().RegisterChecker(type, checker);
    }
};
```

---

## 四、SuperResolutionPostProcessor 超分辨率后处理器

**源码路径**：`services/media_engine/modules/post_processor/super_resolution_post_processor.h` + `.cpp`

### 4.1 头文件

```cpp
// super_resolution_post_processor.h:1-77
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
    Status SetEventReceiver(const std::shared_ptr<EventReceiver> &receiver) override;
    Status SetParameter(const Format &format) override;
    Status SetPostProcessorOn(bool isPostProcessorOn) override;
    Status SetVideoWindowSize(int32_t width, int32_t height) override;
    Status ReleaseOutputBuffer(uint32_t index, bool render) override;
    Status RenderOutputBufferAtTime(uint32_t index, int64_t renderTimestampNs) override;

    void OnOutputFormatChanged(const Format &format);
    void OnOutputBufferAvailable(uint32_t index, VideoProcessingEngine::VpeBufferFlag flag);
    void OnOutputBufferAvailable(uint32_t index, const VideoProcessingEngine::VpeBufferInfo& info);
    void OnSuperResolutionChanged(bool enable);
    void OnError(VideoProcessingEngine::VPEAlgoErrCode errorCode);

private:
    Status SetQualityLevel(VideoProcessingEngine::DetailEnhancerQualityLevel level);

    static constexpr DetailEnhancerQualityLevel DEFAULT_QUALITY_LEVEL =
        VideoProcessingEngine::DETAIL_ENHANCER_LEVEL_HIGH;
    std::shared_ptr<VideoProcessingEngine::VpeVideo> postProcessor_ {nullptr};
    bool isPostProcessorOn_ {false};
    std::shared_ptr<PostProcessorCallback> filterCallback_;
    std::shared_ptr<Pipeline::EventReceiver> eventReceiver_ {nullptr};
    std::shared_mutex mutex_ {};
};
```

### 4.2 自动注册与过滤条件

```cpp
// super_resolution_post_processor.cpp:24-65
namespace {
constexpr int32_t MAX_WIDTH = 1920;   // line 24
constexpr int32_t MAX_HEIGHT = 1080;  // line 25
}

static bool isSuperResolutionSupported(const std::shared_ptr<Meta>& meta)
{
    // line 34-49
    int32_t width = 0, height = 0;
    bool isDrmProtected = false, isHdrVivid = false;
    meta->GetData(Tag::VIDEO_WIDTH, width);
    meta->GetData(Tag::VIDEO_HEIGHT, height);
    meta->GetData(Tag::VIDEO_IS_HDR_VIVID, isHdrVivid);
    meta->GetData(Tag::AV_PLAYER_IS_DRM_PROTECTED, isDrmProtected);
    bool isVideoSizeValid = (width > 0 && width <= MAX_WIDTH) &&
                            (height > 0 && height <= MAX_HEIGHT);
    bool canCreatePostProcessor = !isDrmProtected && !isHdrVivid && isVideoSizeValid;
    return canCreatePostProcessor;
}

static AutoRegisterPostProcessor<SuperResolutionPostProcessor> g_registerSuperResolutionPostProcessor(
    VideoPostProcessorType::SUPER_RESOLUTION, []() -> std::shared_ptr<BaseVideoPostProcessor> {
        auto postProcessor = std::make_shared<SuperResolutionPostProcessor>();
        if (postProcessor == nullptr || !postProcessor->IsValid()) {
            return nullptr;
        } else {
            return postProcessor;
        }
    }, &isSuperResolutionSupported);  // line 55-65
```

**超分启用四条件（同时满足）**：
1. `width > 0 && width <= 1920`
2. `height > 0 && height <= 1080`
3. `!isDrmProtected`（非 DRM 保护内容）
4. `!isHdrVivid`（非 HDR Vivid 内容）

### 4.3 初始化与 VPE 创建

```cpp
// super_resolution_post_processor.cpp:127
postProcessor_ = VpeVideo::Create(VIDEO_TYPE_DETAIL_ENHANCER);

// super_resolution_post_processor.cpp:137
bool SuperResolutionPostProcessor::IsValid()
{
    return postProcessor_ != nullptr;
}

// super_resolution_post_processor.cpp:148
auto ret = SetQualityLevel(DEFAULT_QUALITY_LEVEL);

// super_resolution_post_processor.cpp:308-310
Status SuperResolutionPostProcessor::SetQualityLevel(DetailEnhancerQualityLevel level)
{
    MEDIA_LOG_D("SetQualityLevel in");
    // ...
}
```

### 4.4 VPECallback 回调桥接器

```cpp
// super_resolution_post_processor.cpp:65-80
class VPECallback : public VpeVideoCallback {
public:
    explicit VPECallback(std::shared_ptr<SuperResolutionPostProcessor> postProcessor)
        : postProcessor_(postProcessor) {}
    ~VPECallback() = default;

    void OnError(VPEAlgoErrCode errorCode)
    {
        if (auto postProcessor = postProcessor_.lock()) {
            postProcessor->OnError(errorCode);
        } else {
            MEDIA_LOG_I("invalid decoderSurfaceFilter");
        }
    }
    void OnState(VPEAlgoState state) { ... }
    void OnOutputBufferAvailable(uint32_t index, const VideoProcessingEngine::VpeBufferInfo& info) { ... }
};
```

---

## 五、四种 VideoPostProcessorType

| 类型 | 说明 | 是否启用超分 |
|------|------|------------|
| `NONE` | 无后处理 | 不适用 |
| `SUPER_RESOLUTION` | 超分辨率（DetailEnhancer） | 是 |
| `CAMERA_INSERT_FRAME` | 相机插入帧 | 否 |
| `CAMERA_MP_PWP` | 相机 MP PWP | 否 |

---

## 六、与 S20/S100 对比

| 维度 | S20 PostProcessing | S127 VideoPostProcessor |
|------|-------------------|----------------------|
| 架构 | CRTP+DynamicController+DynamicInterface | BaseVideoPostProcessor+Factory |
| 核心库 | libvideoprocessingengine.z.so (dlopen RTLD_LAZY) | VpeVideo::Create(VIDEO_TYPE_DETAIL_ENHANCER) |
| 注册方式 | 运行时动态注册 | 静态 AutoRegisterPostProcessor |
| 具体实现 | VPE 17 函数符号 | SuperResolutionPostProcessor |
| 过滤条件 | 无明确条件 | 1920×1080 / 非 DRM / 非 HDR Vivid |
| 应用场景 | 视频后处理通用框架 | 播放管线解码后超分增强 |

**核心差异**：S20 描述的是 **VPE dlopen 动态加载** 的通用后处理框架（17个函数符号、色域转换）；S127 描述的是 **VideoPostProcessor 抽象层 + 超分具体实现**（Base→Factory→具体处理器三层架构）。

---

## 七、关键行号证据索引

| 证据 | 文件 | 行号 |
|------|------|------|
| BaseVideoPostProcessor 抽象基类 | base_video_post_processor.h | 1-112 |
| VideoPostProcessorType 枚举 | base_video_post_processor.h | 26-31 |
| PostProcessorCallback 接口 | base_video_post_processor.h | 20-25 |
| 七生命周期 | base_video_post_processor.h | 33-55 |
| VideoPostProcessorFactory 工厂单例 | video_post_processor_factory.h | 1-140 |
| generators_/checkers_ 映射表 | video_post_processor_factory.h | 106-108 |
| AutoRegisterPostProcessor CRTP | video_post_processor_factory.h | 80-98 |
| SuperResolutionPostProcessor 类定义 | super_resolution_post_processor.h | 1-77 |
| MAX_WIDTH=1920 / MAX_HEIGHT=1080 | super_resolution_post_processor.cpp | 24-25 |
| isSuperResolutionSupported 四条件 | super_resolution_post_processor.cpp | 34-49 |
| AutoRegisterPostProcessor 静态注册 | super_resolution_post_processor.cpp | 55-65 |
| VpeVideo::Create(VIDEO_TYPE_DETAIL_ENHANCER) | super_resolution_post_processor.cpp | 127 |
| IsValid() 检查 | super_resolution_post_processor.cpp | 137 |
| SetQualityLevel(DETAIL_ENHANCER_LEVEL_HIGH) | super_resolution_post_processor.cpp | 148, 308-310 |
| VPECallback 回调桥接器 | super_resolution_post_processor.cpp | 65-80 |
| OnSuperResolutionChanged 事件上报 | super_resolution_post_processor.cpp | 353 |