# MEM-ARCH-AVCODEC-S146: VideoResizeFilter + MetaDataFilter 双过滤器架构

**状态**: draft
**生成时间**: 2026-05-15T04:37+08:00
**Builder**: builder-agent
**关联主题**: S12(S14) / S15(S20,S100) / S22(MediaSyncManager) / S44(MetaDataFilter) / S127(PostProcessorFramework)

---

## 一、VideoResizeFilter 转码增强过滤器

### 1.1 架构定位

VideoResizeFilter 是 MediaEngine Filter 管线中负责视频尺寸调整/增强的过滤器，注册名 `"builtin.transcoder.videoresize"`，FilterType 为 `FILTERTYPE_VIDRESIZE`。它封装了 VPE（Video Processing Engine）模块的 DetailEnhancerVideo 引擎，是转码管线（Transcoder Pipeline）的可选增强节点。与 S15/S20/S100 的 PostProcessing 框架互补——后者处理色域转换/超分，VideoResizeFilter 处理尺寸缩放/视频增强。

**证据**:
- `video_resize_filter.cpp:37-40` — AutoRegisterFilter 注册
  ```cpp
  static AutoRegisterFilter<VideoResizeFilter> g_registerVideoResizeFilter("builtin.transcoder.videoresize",
      FilterType::FILTERTYPE_VIDRESIZE,
      [](const std::string& name, const FilterType type) {
          return std::make_shared<VideoResizeFilter>(name, FilterType::FILTERTYPE_VIDRESIZE);
      });
  ```

### 1.2 DetailEnhancerVideo 封装

VideoResizeFilter 的核心引擎是 `DetailEnhancerVideo::Create()`（来自 VPE 模块 libvideoprocessingengine.z.so），通过 `VideoEnhancerVideoCallback`（继承 `DetailEnhancerVideoCallback`）桥接 VPE 事件与 Filter 事件。

**证据**:
- `video_resize_filter.cpp:83-110` — ResizeDetailEnhancerVideoCallback 内类定义，继承 DetailEnhancerVideoCallback
  ```cpp
  class ResizeDetailEnhancerVideoCallback : public DetailEnhancerVideoCallback {
      explicit ResizeDetailEnhancerVideoCallback(std::shared_ptr<VideoResizeFilter> videoResizeFilter)
          : videoEnhancer_(videoResizeFilter) {}
      void OnError(int32_t errorCode) override;
      void OnState(int32_t state) override;
      void OnOutputBufferAvailable(uint32_t index, uint32_t flag) override;
  private:
      std::weak_ptr<VideoResizeFilter> videoEnhancer_;
  };
  ```
- `video_resize_filter.cpp:138-142` — 创建 DetailEnhancerVideo 并注册回调
  ```cpp
  videoEnhancer_ = DetailEnhancerVideo::Create();
  std::shared_ptr<DetailEnhancerVideoCallback> detailEnhancerVideoCallback =
      std::make_shared<ResizeDetailEnhancerVideoCallback>(shared_from_this());
  videoEnhancer_->RegisterCallback(detailEnhancerVideoCallback);
  ```

### 1.3 配置与生命周期

VideoResizeFilter 支持通过 Configure() 设置缩放参数，DoPrepare/DoStart/DoStop/DoPause/DoResume 实现 Filter 标准七生命周期。

**证据**:
- `video_resize_filter.cpp:166-225` — Configure 方法：检查 videoEnhancer_ 非空→构建 DetailEnhancerParameters（DetailEnhancerLevel::DETAIL_ENH_LEVEL_MEDIUM）→SetParameter(SourceType::VIDEO)→获取 InputSurface→设置输出 Surface
  ```cpp
  Status VideoResizeFilter::Configure(const std::shared_ptr<Meta> &parameter) {
      if (videoEnhancer_ == nullptr) { MEDIA_LOG_E("Configure videoEnhancer is null"); return AVCODEC_NODEVICE; }
      const DetailEnhancerParameters parameter_ = {"", DetailEnhancerLevel::DETAIL_ENH_LEVEL_MEDIUM};
      int32_t ret = videoEnhancer_->SetParameter(parameter_, SourceType::VIDEO);
      sptr<Surface> inputSurface = videoEnhancer_->GetInputSurface();
      ...
      int32_t ret = videoEnhancer_->SetOutputSurface(surface);
  }
  ```
- `video_resize_filter.cpp:246` — DoPrepare()
- `video_resize_filter.cpp:263` — DoStart()：videoEnhancer_->Start()
- `video_resize_filter.cpp:293` — DoPause()
- `video_resize_filter.cpp:299` — DoResume()
- `video_resize_filter.cpp:305` — DoStop()：videoEnhancer_->Stop()

### 1.4 VPE 三状态回调

VideoResizeFilter 通过 ResizeDetailEnhancerVideoCallback 桥接 VPE 三类回调：
- `OnError(int32_t errorCode)` → Filter OnError 回调
- `OnState(int32_t state)` → Filter 状态变化
- `OnOutputBufferAvailable(uint32_t index, uint32_t flag)` → Filter 输出缓冲区就绪

**证据**:
- `video_resize_filter.cpp:92-106` — 三回调实现
  ```cpp
  void ResizeDetailEnhancerVideoCallback::OnError(int32_t errorCode) override {
      auto videoResizeFilter = videoEnhancer_.lock();
      FALSE_RETURN_MSG(videoResizeFilter != nullptr, "invalid videoResizeFilter");
      videoResizeFilter->OnVPEError(errorCode);
  }
  void ResizeDetailEnhancerVideoCallback::OnOutputBufferAvailable(uint32_t index, uint32_t flag) override {
      if (auto videoResizeFilter = videoEnhancer_.lock()) {
          videoResizeFilter->OnOutputBufferAvailable(index, flag);
      }
  }
  ```
- `video_resize_filter.cpp:515-530` — ReleaseOutputBuffer(index,-dropFlag)：丢弃标记控制

---

## 二、MetaDataFilter 时域元数据过滤器

### 2.1 架构定位

MetaDataFilter（420行）是 Filter 管线中处理时域元数据（TimedMetadata）的过滤器，注册名从 FilterType::TIMED_METADATA 推断为 `"builtin.player.timedmetadata"`。它在录制管线（Recorder Pipeline）中负责注入录制元数据，与 Surface 模式时 SurfaceBuffer 的元数据通道配合工作。

**证据**:
- `metadata_filter.cpp:34-36` — AutoRegisterFilter 注册
  ```cpp
  static AutoRegisterFilter<MetaDataFilter> g_registerMetaDataFilter(
      [](const std::string& name, const FilterType type) {
          return std::make_shared<MetaDataFilter>(name, FilterType::TIMED_METADATA);
      });
  ```

### 2.2 Surface 模式绑定

MetaDataFilter 核心特性是支持 Surface 模式输入，通过 `SetInputMetaSurface(sptr<Surface> surface)` 创建消费者 Surface，通过 `GetInputMetaSurface()` 获取生产者 Surface，实现录制场景的元数据注入通道。

**证据**:
- `metadata_filter.cpp:130-133` — SetInputMetaSurface 入口
  ```cpp
  Status MetaDataFilter::SetInputMetaSurface(sptr<Surface> surface) {
      MEDIA_LOG_I("SetInputMetaSurface");
      MediaAVCodec::AVCodecTrace trace("MetaDataFilter::SetInputMetaSurface");
      // ...创建消费者 Surface
  }
  ```
- `metadata_filter.cpp:144-148` — GetInputMetaSurface 创建 ConsumerSurface
  ```cpp
  sptr<Surface> MetaDataFilter::GetInputMetaSurface() {
      MEDIA_LOG_I("GetInputMetaSurface");
      MediaAVCodec::AVCodecTrace trace("MetaDataFilter::GetInputMetaSurface");
      sptr<Surface> consumerSurface = Surface::CreateSurfaceAsConsumer("MetadataSurface");
      ...
  }
  ```

### 2.3 MetaDataFilterLinkCallback 三路回调

MetaDataFilter 通过 MetaDataFilterLinkCallback 桥接 Filter 链路事件，OnBufferAvailable 驱动元数据消费流程。

**证据**:
- `metadata_filter.cpp:39-88` — MetaDataFilterLinkCallback 内类：LinkNext/OnLinked/OnLinkedResult 三路回调
  ```cpp
  class MetaDataFilterLinkCallback : public FilterLinkCallback {
      void OnLinkedResult(const std::shared_ptr<Meta> &parameter, int32_t portId) override;
      void OnUnlinked(int32_t portId) override;
      void OnOutputBufferAvailable(uint32_t index, uint32_t flag, int64_t timestamp) override;
  private:
      std::weak_ptr<MetaDataFilter> metaDataFilter_;
  };
  ```
- `metadata_filter.cpp:323-325` — OnBufferAvailable
  ```cpp
  void MetaDataFilter::OnBufferAvailable() {
      MediaAVCodec::AVCodecTrace trace("MetaDataFilter::OnBufferAvailable");
      ...
  }
  ```

---

## 三、双过滤器对比与管线位置

| 维度 | VideoResizeFilter | MetaDataFilter |
|------|------------------|----------------|
| 注册名 | builtin.transcoder.videoresize | builtin.player.timedmetadata |
| FilterType | FILTERTYPE_VIDRESIZE | TIMED_METADATA |
| 行数 | 566行 | 420行 |
| 封装引擎 | DetailEnhancerVideo (VPE) | 原生 Filter 实现 |
| 管线位置 | Transcoder（转码管线） | Player/Recorder（播放/录制管线） |
| 核心能力 | 视频尺寸缩放/增强 | 时域元数据注入 |
| Surface 模式 | 输出 Surface（VPE→Surface） | 输入 Surface（外部→Filter） |
| 生命周期 | DoPrepare/DoStart/DoStop/DoPause/DoResume | 同左（推断） |
| 调用链 | Filter→ResizeDetailEnhancerVideoCallback→VPE | 外部Surface→MetaDataFilter→管线下游 |
| 关联主题 | S12/S15/S20/S127(PostProcessor) | S44/S22(MediaSyncManager) |

---

## 四、与 S12/S15/S127 关联分析

### 4.1 VideoResizeFilter vs SuperResolutionPostProcessor

VideoResizeFilter 使用 DetailEnhancerVideo（VPE 引擎）进行尺寸处理，S127（SuperResolutionPostProcessor）也使用 VPE DetailEnhancer 但目的是超分辨率而非尺寸调整。二者共享 VPE 引擎但目的不同：

- VideoResizeFilter：尺寸缩放（Resize/Scale）
- SuperResolutionPostProcessor：超分辨率（Detail Enhancement，1920×1080/非DRM/非HDRVivid 限制）

### 4.2 与 S12 关系

S12（VideoResizeFilter DetailEnhancerVideo 视频处理引擎与 FILTERTYPE_VIDRESIZE 插件注册）已覆盖 VideoResizeFilter 基础架构。S146 在 S12 基础上补充了：
- ResizeDetailEnhancerVideoCallback 三状态回调桥接
- Configure 参数设置（DetailEnhancerParameters/DetailEnhancerLevel）
- DoPrepare/DoStart/DoStop/DoPause/DoResume 完整生命周期
- ReleaseOutputBuffer 丢弃标记逻辑

### 4.3 与 MetaDataFilter S44 互补

S44 描述了 MetaDataFilter 的 Surface 模式时元数据注入与录制管线时戳同步，S146 补充了：
- SetInputMetaSurface/GetInputMetaSurface 完整实现
- MetaDataFilterLinkCallback 三路回调体系
- OnBufferAvailable 消费驱动

---

## 五、关键文件清单

| 文件 | 行数 | 职责 |
|------|------|------|
| video_resize_filter.cpp | 566 | VideoResizeFilter 主体实现 |
| metadata_filter.cpp | 420 | MetaDataFilter 主体实现 |
| DetailEnhancerVideo (VPE) | - | 共享视频处理引擎（dlopen libvideoprocessingengine.z.so） |

---

## 六、总结

S146 覆盖了两个互补的 MediaEngine Filter：

1. **VideoResizeFilter**：转码管线尺寸增强过滤器，封装 VPE DetailEnhancerVideo，ResizeDetailEnhancerVideoCallback 三路回调桥接，完整七生命周期，与 S12/S15/S20/S127 共享 VPE 引擎资源
2. **MetaDataFilter**：时域元数据过滤器，Surface 模式绑定（SetInputMetaSurface/GetInputMetaSurface），MetaDataFilterLinkCallback 三路链路回调，与 S44 互补

二者构成 MediaEngine Filter 管线中"视频处理增强"与"元数据注入"两个不同方向的扩展节点。