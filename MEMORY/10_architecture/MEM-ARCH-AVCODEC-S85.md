---
mem_id: MEM-ARCH-AVCODEC-S85
title: "PreprocessorManager 视频编码预处理器管理器——CAPI层Crop/Downsample/DropFrame三功能编排与多编码器Surface共享"
scope: [AVCodec, CAPI, Preprocessor, PreprocessorManager, PreprocessorEncoder, VideoEncoder, Surface, Crop, Downsample, FrameDrop, FastKitsInterface, FrameDropFilter, SharedSurfaceManager, DualEncoder, PrimaryEncoder, SecondaryEncoder, SurfaceMode]
status: draft
created_by: builder-agent
created_at: "2026-05-03T22:45:00+08:00"
approved_by: null
type: architecture_fact
confidence: high
summary: >
  AVCodec CAPI层视频编码预处理器由Preprocessor（FastKitsInterface+FrameDropFilter封装）、PreprocessorManager（多编码器协调与Surface共享）、PreprocessorEncoder（Primary/Secondary双编码器工厂）三层构成。
  Preprocessor支持Crop/Downsample/DropFrame三种预处理模式，Crop与Downsample互斥，ValidateCrop/ValidateDownsampling/ValidateDropFrame三步校验后写入配置。
  PreprocessorManager通过EncoderInfo::EncoderThreadLoop（OS_Preproc_{encoderId}_Loop线程）为每个编码器驱动预处理循环，
  SharedSurfaceManager创建producer/consumer Surface对供多个编码器共享输入。
  PreprocessorEncoder支持Primary+Secondary双编码器场景，Secondary共享Primary的PreprocessorManager和SharedSurface，但拥有独立的Preprocessor实例。
why_it_matters:
  - 新需求开发：需要自定义编码前图像处理（裁剪/缩放/丢帧）时，必须通过PreprocessorManager管理Surface和EncoderInfo，理解线程模型才能正确接入
  - 问题定位：多编码器场景下预处理异常，需区分是Preprocessor配置问题（Crop vs Downsample冲突）还是EncoderThreadLoop处理延迟
  - 性能优化：预处理在OS_Preproc线程执行，了解Crop→Downsample→Copy三模式分支可定位预处理瓶颈
---

## 一、整体架构

AVCodec CAPI层视频编码预处理器分为三层：

```
┌──────────────────────────────────────────────────────────────┐
│  PreprocessorEncoder（CAPI入口）                             │
│  CreatePrimary() / CreateSecondary()                         │
│  Primary: 拥有独立的PreprocessorManager + SharedSurface       │
│  Secondary: 共享Primary的PreprocessorManager + SharedSurface  │
└──────────────────────────┬───────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────┐
│  PreprocessorManager（多编码器协调器）                         │
│  RegisterEncoder() / UnregisterEncoder()                     │
│  CreateSharedSurface(): 创建SharedSurfaceManager              │
│  EncoderInfo::EncoderThreadLoop (OS_Preproc_{id}_Loop)        │
│  ConsumerListener: 监听sharedConsumerSurface的OnBufferAvailable│
└──────────────────────────┬───────────────────────────────────┘
                           │
      ┌────────────────────┼──────────────────────────────────┐
      │                    │                                  │
      ▼                    ▼                                  ▼
┌─────────────┐    ┌────────────────┐                  ┌─────────────┐
│ EncoderInfo │    │  EncoderInfo   │                  │ EncoderInfo │
│ (Primary)  │    │  (Secondary)   │                  │  (...)      │
│ Preprocessor│    │  Preprocessor  │                  │ Preprocessor│
└──────┬──────┘    └───────┬────────┘                  └──────┬──────┘
       │                    │                                  │
       │         ┌──────────▼──────────────────────────────┐  │
       │         │  SharedSurfaceManager                    │  │
       │         │  producerSurface_ ← Camera/Pipeline input │  │
       │         │  consumerSurface_ → EncoderThreadLoop    │  │
       └────────►│                                        │◄─┘
                 └──────────────────────────────────────────┘
```

**三层组件定位：**

| 组件 | 文件 | 行数 | 职责 |
|------|------|------|------|
| Preprocessor | `preprocessor.cpp/h` | 542+162行 | FastKitsInterface+FrameDropFilter封装，Process(input,output,pts)执行Crop/Downsample/DropFrame |
| PreprocessorManager | `preprocessor_manager.cpp/h` | 444+126行 | 多编码器协调，SharedSurface管理，EncoderInfo生命周期，EncoderThreadLoop驱动 |
| PreprocessorEncoder | `preprocessor_encoder.cpp/h` | 549+100行 | CAPI工厂入口，Primary/Secondary双编码器创建，Configure链路 |
| SharedSurfaceManager | `shared_surface_manager.cpp/h` | 71+44行 | producer/consumer Surface对创建 |
| VideoEncoderObject | `video_encoder_object.cpp/h` | 364+100行 | AVCodecVideoEncoder封装，Native→Codec回调映射 |

---

## 二、Preprocessor 核心实现

### 2.1 构造与初始化

**preprocessor.cpp:120-130**
```cpp
Preprocessor::Preprocessor(const std::string &mime) : mime_(mime)
{
    fastKitsInterface_.Retain();  // FastKitsInterface单例引用计数+1
}

Preprocessor::~Preprocessor()
{
    fastKitsInterface_.Release();   // FastKitsInterface单例引用计数-1
}
```

**preprocessor.h:97-100**
```cpp
std::string mime_;
PreProcessing::FastKitsInterface &fastKitsInterface_ = PreProcessing::FastKitsInterface::GetInstance();
PreProcessing::FrameDropFilter dropFilter_;
```

Preprocessor在构造时引用全局单例FastKitsInterface和FrameDropFilter。FastKitsInterface通过Retain/Release管理dlopen加载的libfast_image.so生命周期。

### 2.2 Configure 三步校验

**preprocessor.cpp:131-171**（三步校验链）：

```cpp
int32_t Preprocessor::Configure(const Media::Format &format)
{
    UpdateConfiguredValues(format, encoderConfig_);  // 从format提取width/height/pixelFormat/frameRate
    CropParams cropParams;
    DownsamplingParams dsParams;
    DropFrameParams dropParams;
    int32_t ret = ValidateCrop(format, cropParams);
    ret = (ret == AVCS_ERR_OK) ? ValidateDownsampling(format, dsParams) : ret;  // 第2步
    ret = (ret == AVCS_ERR_OK) ? ValidateDropFrame(format, dropParams) : ret;    // 第3步
    // Crop和Downsample互斥：两者不能同时启用
    if (cropParams.result == ConfigResult::ENABLED && dsParams.result == ConfigResult::ENABLED) {
        AVCODEC_LOGI("Crop and downsampling cannot be enabled simultaneously");
        return AVCS_ERR_INVALID_VAL;
    }
    cropConfig_   = CropConfig(cropParams);
    downsamplingConfig_ = DownsamplingConfig(dsParams);
    dropFrameConfig_   = DropFrameConfig(dropParams);
}
```

**preprocessor.cpp:174-213**（ValidateCrop校验细节）：
```cpp
int32_t Preprocessor::ValidateCrop(const Media::Format &format, CropParams &params)
{
    // 从format读取OH_MD_KEY_VIDEO_ENCODER_PREPROC_CROP_{LEFT|RIGHT|TOP|BOTTOM}
    bool hasLeft = format.GetIntValue(OH_MD_KEY_VIDEO_ENCODER_PREPROC_CROP_LEFT, left);
    // 若全部4个key都存在，则校验裁剪范围
    // 调用GetEncoderRange(format, encWidth, encHeight)获取编码器能力范围
    // 校验: left>=0 && left<right && right<=encoderConfig_.width
    //       && top>=0 && top<bottom && bottom<=encoderConfig_.height
    //       && encWidth.InRange(cropWidth) && encHeight.InRange(cropHeight)
}
```

**preprocessor.cpp:215-249**（ValidateDownsampling校验细节）：
```cpp
int32_t Preprocessor::ValidateDownsampling(const Media::Format &format, DownsamplingParams &params)
{
    // 从format读取OH_MD_KEY_VIDEO_ENCODER_PREPROC_DOWNSAMPLING_WIDTH/HEIGHT
    // 计算算法支持范围：minWidth = max(dAlgoWidthMin_, encWidth.minVal)
    //                   maxWidth = min(dAlgoWidthMax_, encWidth.maxVal)
    // 校验: minWidth<=width<=encoderConfig_.width<=maxWidth
    //       minHeight<=height<=encoderConfig_.height<=maxHeight
}
```

**preprocessor.cpp:251-282**（ValidateDropFrame校验细节）：
```cpp
int32_t Preprocessor::ValidateDropFrame(const Media::Format &format, DropFrameParams &params)
{
    // 从format读取targetFrameRate
    // 若targetFrameRate>0则启用丢帧
    // 调用dropFilter_.ShouldDropFrame(pts)判断是否丢帧
}
```

### 2.3 Process 三模式处理

**preprocessor.cpp:283-300**（主处理函数）：
```cpp
int32_t Preprocessor::Process(sptr<SurfaceBuffer> input, sptr<SurfaceBuffer> output, uint64_t pts)
{
    if (ShouldDropFrame(pts)) {       // 先判断是否丢帧
        return AVCS_ERR_OK;           // 丢帧：直接返回，不做任何拷贝
    }
    if (IsCropEnabled()) {
        Crop(input, output);           // 模式1: Crop（优先）
    } else if (IsDownsamplingEnabled()) {
        Downsampling(input, output);   // 模式2: Downsample
    } else {
        Copy(input, output);           // 模式3: 直接拷贝
    }
    return AVCS_ERR_OK;
}

bool Preprocessor::ShouldDropFrame(uint64_t pts)
{
    if (!dropFrameConfig_.enabled) return false;
    return dropFilter_.ShouldDropFrame(pts);   // 委托FrameDropFilter判断
}
```

**preprocessor.cpp:344-358**（Crop实现）：
```cpp
void Preprocessor::Crop(sptr<SurfaceBuffer> input, sptr<SurfaceBuffer> output)
{
    PreProcessing::CropRect rect{cropConfig_.top, cropConfig_.left, cropConfig_.bottom, cropConfig_.right};
    int32_t ret = fastKitsInterface_.Crop(input, output, rect);  // 调用libfast_image.so
}
```

**preprocessor.cpp:360-374**（Downsample实现）：
```cpp
void Preprocessor::Downsampling(sptr<SurfaceBuffer> input, sptr<SurfaceBuffer> output)
{
    int32_t ret = fastKitsInterface_.DownSample(input, output, FastResizeAlgoType::BICUBIC);
}
```

**preprocessor.cpp**（Copy实现：按像素格式分平面拷贝）：
- RGBA_8888/RGBA_1010102: 单平面，rowBytes=width*4
- YCBCR_420_SP/YCRCB_420_SP: 双平面，Y+(UV)行数=(height+1)/2
- YCBCR_P010/YCRCB_P010: 双平面，16bit容器
- YCBCR_420_P: 三平面，UV宽度=(width+1)/2

### 2.4 HEVC 10-bit特殊处理

**preprocessor.cpp**（IsHevc10BitData和ConvertVideoPixelFormat2GraphicPixelFormat）：
- HEVC Main10格式（YCBCR_P010/YCRCB_P010）映射为Codec内部NV12
- IsHevc10BitData(profile)判断HEVC 10-bit数据

---

## 三、PreprocessorManager 多编码器协调

### 3.1 SharedSurface 创建

**preprocessor_manager.cpp:92-119**（CreateSharedSurface）：
```cpp
void PreprocessorManager::CreateSharedSurface()
{
    auto sharedSurfMgr = std::make_shared<SharedSurfaceManager>();
    int32_t ret = sharedSurfMgr->Create();  // 创建consumer+producer Surface对
    sharedConsumerSurface_ = sharedSurfMgr->GetConsumerSurface();
    sharedProducerSurface_ = sharedSurfMgr->GetProducerSurface();
    // 注册ConsumerListener监听OnBufferAvailable事件
    sptr<IBufferConsumerListener> listener = sptr<ConsumerListener>::MakeSptr(shared_from_this());
    sharedConsumerSurface_->RegisterConsumerListener(listener);
}
```

**shared_surface_manager.cpp:30-53**（SharedSurfaceManager::Create）：
```cpp
int32_t SharedSurfaceManager::Create()
{
    consumerSurface_ = Surface::CreateSurfaceAsConsumer("SharedEncoderSurface");
    producer_ = consumerSurface_->GetProducer();          // 获取IBufferProducer
    producerSurface_ = Surface::CreateSurfaceAsProducer(producer_);  // 创建producer端
}
```

### 3.2 多编码器注册

**preprocessor_manager.cpp:58-66**（RegisterEncoder）：
```cpp
void PreprocessorManager::RegisterEncoder(std::string_view encoderId,
                                          std::shared_ptr<Preprocessor> preprocessor,
                                          sptr<Surface> encoderSurface)
{
    auto info = std::make_shared<EncoderInfo>(std::string(encoderId));
    info->Init(preprocessor, encoderSurface);  // EncoderInfo持有编码器专用的Preprocessor和Surface
    encoders_.emplace(std::string(encoderId), info);
}
```

### 3.3 ConsumerListener 事件驱动

**preprocessor_manager.cpp:29-38**（ConsumerListener匿名类）：
```cpp
class ConsumerListener : public OHOS::IBufferConsumerListener {
public:
    explicit ConsumerListener(std::weak_ptr<PreprocessorManager> mgr) : mgr_(mgr) {}
    void OnBufferAvailable() override {  // sharedConsumerSurface收到新buffer时触发
        auto mgr = mgr_.lock();
        if (mgr) {
            mgr->NotifyNewBufferAvailable();
        }
    }
};
```

**preprocessor_manager.cpp:121-145**（NotifyNewBufferAvailable）：
```cpp
void PreprocessorManager::NotifyNewBufferAvailable()
{
    auto bufferWrapper = std::make_shared<SurfaceBufferWrapper>(
        sharedConsumerSurface_, nullptr, nullptr, SurfaceBufferWrapper::SurfaceType::CONSUMER);
    auto ret = sharedConsumerSurface_->AcquireBuffer(
        bufferWrapper->buffer, bufferWrapper->fence, bufferWrapper->timestamp, damage);
    // 广播给所有已注册的EncoderInfo
    for (auto &[_, encoderInfo] : encoders_) {
        if (encoderInfo) {
            encoderInfo->OnNewPendingBufferAvailable(bufferWrapper);
        }
    }
}
```

### 3.4 EncoderInfo 与 EncoderThreadLoop

**preprocessor_manager.h:69-97**（EncoderInfo内部类关键成员）：
```cpp
class EncoderInfo : public std::enable_shared_from_this<EncoderInfo> {
    std::queue<std::shared_ptr<SurfaceBufferWrapper>> pendingBuffers_{};  // 待处理buffer队列
    std::queue<std::shared_ptr<SurfaceBufferWrapper>> availableInputBuffers_{}; // 可用encoder输入buffer
    std::shared_ptr<Preprocessor> preprocessor_{nullptr};
    sptr<Surface> encoderSurface_{nullptr};
    std::thread processThread_;       // OS_Preproc_{encoderId}_Loop 线程
    bool isRunning_{false};
    std::condition_variable bufferQueueCv_;
    std::mutex bufferQueueMutex_;
};
```

**preprocessor_manager.cpp:346-410**（EncoderThreadLoop核心循环）：
```cpp
void PreprocessorManager::EncoderInfo::EncoderThreadLoop()
{
    pthread_setname_np(pthread_self(), threadName.c_str());  // OS_Preproc_{encoderId}_Loop
    while (isRunning_) {
        std::unique_lock<std::mutex> lock(bufferQueueMutex_);
        bufferQueueCv_.wait(lock, [this]() {
            return !(pendingBuffers_.empty() || availableInputBuffers_.empty());
        });
        // 取出input buffer和encoder输出buffer
        inputBuffer = pendingBuffers_.front();    // sharedConsumerSurface的buffer
        pendingBuffers_.pop();
        outputBuffer = availableInputBuffers_.front(); // encoder编码器内部buffer
        availableInputBuffers_.pop();
        lock.unlock();
        // 调用Preprocessor处理
        auto ret = preprocessor_->Process(inputBuffer->buffer, outputBuffer->buffer, inputBuffer->timestamp);
        // 处理后写回encoderSurface
    }
}
```

**preprocessor_manager.cpp:298-308**（OnNewPendingBufferAvailable）：
```cpp
void PreprocessorManager::EncoderInfo::OnNewPendingBufferAvailable(std::shared_ptr<SurfaceBufferWrapper> buffer)
{
    std::lock_guard<std::mutex> lock(bufferQueueMutex_);
    pendingBuffers_.push(buffer);   // 放入待处理队列，唤醒EncoderThreadLoop
    bufferQueueCv_.notify_one();
}
```

---

## 四、PreprocessorEncoder CAPI工厂

### 4.1 Primary/Secondary双编码器工厂

**preprocessor_encoder.cpp:105-180**（CreatePrimary/CreateSecondary）：
```cpp
OH_AVErrCode PreprocessorEncoder::CreatePrimary(const char *mime, OH_AVCodec **codec)
{
    auto encoder = std::make_unique<PreprocessorEncoder>(AVMagic::AVCODEC_MAGIC_PRIMARY_VIDEO_ENCODER);
    encoder->InitAsPrimary(mime);
    // InitAsPrimary: 创建独立的VideoEncoderObject + PreprocessorManager + Preprocessor
    *codec = encoder.release();
}

OH_AVErrCode PreprocessorEncoder::CreateSecondary(OH_AVCodec *primary, OH_AVCodec **secondary)
{
    auto *primaryEnc = reinterpret_cast<PreprocessorEncoder *>(primary);
    auto encoder = std::make_unique<PreprocessorEncoder>(AVMagic::AVCODEC_MAGIC_SECONDARY_VIDEO_ENCODER);
    encoder->InitAsSecondary(primaryEnc);  // 共享primary的PreprocessorManager
    primaryEnc->secondary_ = encoder.get();  // 双向链接
}
```

**preprocessor_encoder.cpp:145-165**（InitAsPrimary vs InitAsSecondary对比）：
```cpp
// InitAsPrimary: 创建独立的manager
OH_AVErrCode PreprocessorEncoder::InitAsPrimary(const char *mime)
{
    preprocMgr_ = std::make_shared<PreprocessorManager>();  // 独立manager
    preprocMgr_->CreateSharedSurface();                      // 创建共享Surface
    auto preprocessor = std::make_shared<Preprocessor>(mime);
    preprocessors_[encoderId_] = preprocessor;
}

// InitAsSecondary: 共享primary的manager
OH_AVErrCode PreprocessorEncoder::InitAsSecondary(PreprocessorEncoder *primary)
{
    preprocMgr_ = primary->preprocMgr_;  // 共享manager和Surface
    auto preprocessor = std::make_shared<Preprocessor>(mime_);  // 独立的Preprocessor
    preprocessors_[encoderId_] = preprocessor;
    primary_ = primary;
}
```

### 4.2 Configure 链路

**preprocessor_encoder.cpp:267-295**（Configure三步链）：
```cpp
OH_AVErrCode PreprocessorEncoder::Configure(const Media::Format &format)
{
    // 第1步: ConfigureVideoEncoder → videoEncoder_->Configure(format)
    int32_t ret = ConfigureVideoEncoder(format);
    // 第2步: ConfigurePreprocessor → preprocessor->Configure(format)
    ret = ConfigurePreprocessor(format);
    // 第3步: 双编码器PixelFormat一致性校验
    if (!isPrimary_ && primary_ != nullptr) {
        GraphicPixelFormat secFmt = secondaryPreprocessor->GetConfiguredPixelFormat();
        GraphicPixelFormat priFmt = primaryPreprocessor->GetConfiguredPixelFormat();
        if (secFmt != priFmt && priFmt != GraphicPixelFormat::GRAPHIC_PIXEL_FMT_BUTT) {
            return AV_ERR_INVALID_VAL;  // PixelFormat必须一致
        }
    }
    // 第4步: CreateEncoderSurface
    ret = CreateEncoderSurface();
    // 第5步: RegisterEncoderToManager
    RegisterEncoderToManager();
}
```

### 4.3 SetParameter 动态更新

**preprocessor_encoder.cpp:300-310**：
```cpp
OH_AVErrCode PreprocessorEncoder::SetParameter(const Media::Format &format)
{
    auto preprocessor = GetPreprocessor();
    if (preprocessor) {
        int32_t ret = preprocessor->Configure(format);  // 动态更新crop/downsample配置
    }
    if (videoEncoderObject_ && videoEncoderObject_->videoEncoder_) {
        int32_t ret = videoEncoderObject_->videoEncoder_->SetParameter(format);  // 透传给编码器
    }
}
```

---

## 五、数据流完整路径

```
Camera / FilterPipeline
      │
      │  OHOS::Surface::WriteToSurface()  [producer端写入]
      ▼
SharedSurfaceManager.producerSurface_  (IBufferProducer)
      │
      │  OnBufferAvailable()  [新buffer到达事件]
      ▼
PreprocessorManager.sharedConsumerSurface_  (ConsumerListener)
      │
      │  AcquireBuffer() → OnNewPendingBufferAvailable()
      │                        │
      │  ┌─────────────────────┼─────────────────────┐
      │  ▼                     ▼                     ▼
      │ EncoderInfo(Primary)  EncoderInfo(Sec)   EncoderInfo(...)
      │ OS_Preproc_Loop      OS_Preproc_Loop    OS_Preproc_Loop
      │       │                     │                   │
      │  Preprocessor::Process(input, output, pts)  │
      │  ├── ShouldDropFrame() → true? → return (丢帧)│
      │  ├── IsCropEnabled()? → Crop()              │
      │  ├── IsDownsamplingEnabled()? → Downsample()│
      │  └── else → Copy()                          │
      │       │                                      │
      │  SetBufferFlushConfig()                     │
      │       │                                      │
      │  FlushBuffer() → encoderSurface_            │
      │       │                                      │
      │       ▼                                      │
      │  VideoEncoder (编码)                          │
      │       │                                      │
      │  OnOutputBufferAvailable() → 用户            │
      └─────────────────────────────────────────────┘
```

---

## 六、与其他主题的关联

| 关联主题 | 关系 |
|----------|------|
| S33 PreProcessing框架 | S33覆盖FastKitsInterface(CropRect/DownSample)和FrameDropFilter(丢帧策略)，S85是CAPI层整合封装 |
| S84 VideoEncoder C API | S84是VideoEncoder C API总览，S85是PreprocessorManager子系统的深度分析 |
| S20 PostProcessing | PostProcessing是Filter链路的视频后处理，S85是CAPI编码前的预处理，两者并列 |
| S8 FFmpeg音频插件 | 对比：音频Resample在AudioCodecWorker内，Preprocessor在独立CAPI线程 |

---

## Evidence 摘要

| 来源 | 文件 | 关键行号 |
|------|------|----------|
| Preprocessor三步校验 | `frameworks/native/capi/avcodec/preprocessor.cpp` | 131-171 |
| ValidateCrop | `preprocessor.cpp` | 174-213 |
| ValidateDownsampling | `preprocessor.cpp` | 215-249 |
| ValidateDropFrame | `preprocessor.cpp` | 251-282 |
| Process三模式 | `preprocessor.cpp` | 283-300 |
| ShouldDropFrame | `preprocessor.cpp` | 303-310 |
| Crop实现 | `preprocessor.cpp` | 344-358 |
| Downsample实现 | `preprocessor.cpp` | 360-374 |
| PlaneCopyInfo像素格式 | `preprocessor.cpp` | 40-100 |
| FastKitsInterface头 | `frameworks/native/avcodec/pre_processing/fast_kits_interface/fast_kits_interface.h` | 全文 |
| ConsumerListener | `preprocessor_manager.cpp` | 29-38 |
| CreateSharedSurface | `preprocessor_manager.cpp` | 92-119 |
| NotifyNewBufferAvailable | `preprocessor_manager.cpp` | 121-145 |
| RegisterEncoder | `preprocessor_manager.cpp` | 58-66 |
| EncoderThreadLoop | `preprocessor_manager.cpp` | 346-410 |
| OnNewPendingBufferAvailable | `preprocessor_manager.cpp` | 298-308 |
| PreprocessorManager头 | `frameworks/native/capi/avcodec/preprocessor_manager.h` | 全文 |
| SharedSurfaceManager::Create | `shared_surface_manager.cpp` | 30-53 |
| CreatePrimary/CreateSecondary | `preprocessor_encoder.cpp` | 105-180 |
| InitAsPrimary | `preprocessor_encoder.cpp` | 145-165 |
| InitAsSecondary | `preprocessor_encoder.cpp` | 167-183 |
| Configure链路 | `preprocessor_encoder.cpp` | 267-295 |
| SetParameter | `preprocessor_encoder.cpp` | 300-310 |
| GraphicPixelFmtToVideoPixelFmt | `preprocessor_encoder.cpp` | 24-58 |
| VideoEncoderObject头 | `frameworks/native/capi/avcodec/video_encoder_object.h` | 全文 |
