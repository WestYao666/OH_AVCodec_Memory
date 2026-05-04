---
type: architecture
id: MEM-ARCH-AVCODEC-S12
status: approved
approved_at: '2026-05-04T16:15:36.119260'
approved_by: feishu-user:ou_60d8641be684f82e8d9cb84c3015dde7
topic: VideoResizeFilter 转码增强过滤器——DetailEnhancerVideo视频处理引擎与FILTERTYPE_VIDRESIZE插件注册
created_at: "2026-04-24T00:05:00+08:00"
updated_at: "2026-05-04T06:05:00+08:00"
scope: [AVCodec, MediaEngine, Filter, Transcoder, VideoProcessingEngine, VPE, Plugin, DetailEnhancerVideo, FILTERTYPE_VIDRESIZE]
关联主题: [S10(SeiParserFilter), S15(SuperResolutionPostProcessor), S33(PreProcessing)]
---

# MEM-ARCH-AVCODEC-S12: VideoResizeFilter 转码增强过滤器

## 主题
VideoResizeFilter 转码增强过滤器——DetailEnhancerVideo 视频处理引擎与 FILTERTYPE_VIDRESIZE 插件注册

## 状态
status: draft（待审批）

## 摘要

VideoResizeFilter 是转码 Pipeline 中的分辨率增强 Filter，基于 VPE（Video Processing Engine）DetailEnhancerVideo 实现。注册名为 "builtin.transcoder.videoresize"，通过双 Surface 桥接上下游 Filter，在转码过程中对视频进行超分/增强处理。

---

## 源码证据

### 1. 插件注册（AutoRegisterFilter 工厂模式）

- 来源：`services/media_engine/filters/video_resize_filter.cpp:37-40`
  ```cpp
  static AutoRegisterFilter<VideoResizeFilter> g_registerVideoResizeFilter(
      "builtin.transcoder.videoresize",
      FilterType::FILTERTYPE_VIDRESIZE,
      [](const std::string& name, const FilterType type) {
          return std::make_shared<VideoResizeFilter>(name, FilterType::FILTERTYPE_VIDRESIZE);
      });
  ```
  - 注册名：`"builtin.transcoder.videoresize"`
  - FilterType：`FILTERTYPE_VIDRESIZE`
  - Lambda 工厂创建 VideoResizeFilter 实例，与 S10（SeiParserFilter）并列转码辅助 Filter

- 来源：`services/media_engine/filters/video_resize_filter.cpp:36`（外层命名空间）
  ```cpp
  constexpr OHOS::HiviewDFX::HiLogLabel LABEL = { LOG_CORE, LOG_DOMAIN_SYSTEM_PLAYER, "VideoResizeFilter" };
  ```

### 2. ResizeDetailEnhancerVideoCallback 回调类

- 来源：`services/media_engine/filters/video_resize_filter.cpp:83-106`
  ```cpp
  class ResizeDetailEnhancerVideoCallback : public DetailEnhancerVideoCallback {
  public:
      explicit ResizeDetailEnhancerVideoCallback(std::shared_ptr<VideoResizeFilter> videoResizeFilter);
      void OnError(VPEAlgoErrCode errorCode) override;
      void OnState(VPEAlgoState state) override;
      void OnOutputBufferAvailable(uint32_t index, DetailEnhBufferFlag flag) override;
  private:
      std::weak_ptr<VideoResizeFilter> videoResizeFilter_;
  };
  ```
  - 实现 DetailEnhancerVideoCallback 三接口：OnError / OnState / OnOutputBufferAvailable
  - OnError 转发至 `OnVPEError(errorCode)` → `eventReceiver_->OnEvent(EVENT_ERROR)`
  - OnOutputBufferAvailable 转发至 `OnOutputBufferAvailable(index, static_cast<uint32_t>(flag))`

### 3. Init 初始化（VPE 引擎创建）

- 来源：`services/media_engine/filters/video_resize_filter.cpp:131-149`
  ```cpp
  void VideoResizeFilter::Init(const std::shared_ptr<EventReceiver> &receiver,
      const std::shared_ptr<FilterCallback> &callback)
  {
      eventReceiver_ = receiver;
      filterCallback_ = callback;
  #ifdef USE_VIDEO_PROCESSING_ENGINE
      videoEnhancer_ = DetailEnhancerVideo::Create();
      if (videoEnhancer_ != nullptr) {
          auto detailEnhancerVideoCallback =
              std::make_shared<ResizeDetailEnhancerVideoCallback>(shared_from_this());
          videoEnhancer_->RegisterCallback(detailEnhancerVideoCallback);
      } else {
          if (eventReceiver_) {
              eventReceiver_->OnEvent({"video_resize_filter", EventType::EVENT_ERROR, MSERR_UNKNOWN});
          }
          return;
      }
  #else
      if (eventReceiver_) {
          eventReceiver_->OnEvent({"video_resize_filter", EventType::EVENT_ERROR, MSERR_UNKNOWN});
      }
  #endif
      if (!releaseBufferTask_) {
          releaseBufferTask_ = std::make_shared<Task>("VideoResize");
          releaseBufferTask_->RegisterJob([this] { ReleaseBuffer(); return 0; });
      }
  }
  ```
  - `DetailEnhancerVideo::Create()` 创建 VPE 引擎（USE_VIDEO_PROCESSING_ENGINE 编译开关保护）
  - 注册回调到 videoEnhancer_
  - 创建 "VideoResize" 命名的 Task 后台线程用于 ReleaseBuffer

### 4. Configure 配置（增强级别参数）

- 来源：`services/media_engine/filters/video_resize_filter.cpp:166-192`
  ```cpp
  Status VideoResizeFilter::Configure(const std::shared_ptr<Meta> &parameter)
  {
      configureParameter_ = parameter;
  #ifdef USE_VIDEO_PROCESSING_ENGINE
      if (videoEnhancer_ == nullptr) { return Status::ERROR_NULL_POINTER; }
      const DetailEnhancerParameters parameter_ = {"", DetailEnhancerLevel::DETAIL_ENH_LEVEL_MEDIUM};
      int32_t ret = videoEnhancer_->SetParameter(parameter_, SourceType::VIDEO);
      if (ret != 0) {
          if (eventReceiver_) {
              eventReceiver_->OnEvent({"video_resize_filter", EventType::EVENT_ERROR,
                  MSERR_UNSUPPORT_VID_PARAMS});
          }
          return Status::ERROR_UNKNOWN;
      }
  #else
      if (eventReceiver_) {
          eventReceiver_->OnEvent({"video_resize_filter", EventType::EVENT_ERROR, MSERR_UNKNOWN});
      }
      return Status::ERROR_UNKNOWN;
  #endif
  }
  ```
  - 固定增强级别 `DETAIL_ENH_LEVEL_MEDIUM`（无动态调整接口）
  - SourceType::VIDEO 指定视频源类型

### 5. 双 Surface 绑定（输入/输出 Surface）

- 来源：`services/media_engine/filters/video_resize_filter.cpp:194-214`
  ```cpp
  sptr<Surface> VideoResizeFilter::GetInputSurface()
  {
      if (videoEnhancer_ == nullptr) { return nullptr; }
      return videoEnhancer_->GetInputSurface();  // 获取上游输入 Surface
  }

  Status VideoResizeFilter::SetOutputSurface(sptr<Surface> surface, int32_t width, int32_t height)
  {
      if (surface == nullptr) { return Status::ERROR_NULL_POINTER; }
      return videoEnhancer_->SetOutputSurface(surface);  // 注入下游输出 Surface
  }
  ```
  - `GetInputSurface()` 向上游获取输入 Surface → 形成 Producer
  - `SetOutputSurface()` 向下游注入输出 Surface → 形成 Consumer
  - 双 Surface 桥接转码 Pipeline 上/下游 Filter

### 6. DoPrepare 准备阶段（申请下一个 Filter）

- 来源：`services/media_engine/filters/video_resize_filter.cpp:246-259`
  ```cpp
  Status VideoResizeFilter::DoPrepare()
  {
      if (filterCallback_ == nullptr) { return Status::ERROR_UNKNOWN; }
      switch (filterType_) {
          case FilterType::FILTERTYPE_VIDRESIZE:
              filterCallback_->OnCallback(shared_from_this(), FilterCallBackCommand::NEXT_FILTER_NEEDED,
                  StreamType::STREAMTYPE_RAW_VIDEO);
              break;
          default:
              break;
      }
      return Status::OK;
  }
  ```
  - 向 FilterPipeline 申请下一个 Filter（NEXT_FILTER_NEEDED）
  - StreamType::STREAMTYPE_RAW_VIDEO 视频类型筛选

### 7. DoStart / DoStop 生命周期

- 来源：`services/media_engine/filters/video_resize_filter.cpp:263-298`
  ```cpp
  Status VideoResizeFilter::DoStart()
  {
      isThreadExit_ = false;
      if (releaseBufferTask_) { releaseBufferTask_->Start(); }
  #ifdef USE_VIDEO_PROCESSING_ENGINE
      if (videoEnhancer_ == nullptr) { return Status::ERROR_NULL_POINTER; }
      int32_t ret = videoEnhancer_->Start();
      if (ret != 0) { ... return Status::ERROR_UNKNOWN; }
      return Status::OK;
  #else
      ... return Status::ERROR_UNKNOWN;
  #endif
  }

  Status VideoResizeFilter::DoStop()
  {
      if (releaseBufferTask_) {
          isThreadExit_ = true;
          releaseBufferCondition_.notify_all();
          releaseBufferTask_->Stop();
      }
  #ifdef USE_VIDEO_PROCESSING_ENGINE
      if (!videoEnhancer_) { return Status::OK; }
      int32_t ret = videoEnhancer_->Stop();
      ...
  #endif
  }
  ```
  - DoStart：releaseBufferTask_ 启动 + videoEnhancer_->Start()
  - DoStop：退出标志 isThreadExit_=true → notify_all() 唤醒 → videoEnhancer_->Stop()

### 8. LinkNext 级联链路

- 来源：`services/media_engine/filters/video_resize_filter.cpp:411-425`
  ```cpp
  Status VideoResizeFilter::LinkNext(const std::shared_ptr<Filter> &nextFilter, StreamType outType)
  {
      auto ret = nextFilter->OnLinked(outType, configureParameter_, filterLinkCallback);
      if (ret != Status::OK) {
          eventReceiver_->OnEvent({"VideoResizeFilter::LinkNext error",
              EventType::EVENT_ERROR, MSERR_UNKNOWN});
      }
      return ret;
  }
  ```
  - VideoResizeFilterLinkCallback（FilterLinkCallback 实现）桥接回调事件
  - `OnLinkedResult(nullptr, meta)` 将元数据传递到下游 Filter

### 9. OnOutputBufferAvailable 输出缓冲可用回调

- 来源：`services/media_engine/filters/video_resize_filter.cpp:485-500`
  ```cpp
  void VideoResizeFilter::OnOutputBufferAvailable(uint32_t index, uint32_t flag)
  {
      if (flag != static_cast<uint32_t>(DETAIL_ENH_BUFFER_FLAG_EOS)) {
          std::lock_guard<std::mutex> lock(releaseBufferMutex_);
          indexs_.push_back(index);  // 收集可用 buffer index
      } else {
          eosBufferIndex_ = index;  // 标记 EOS buffer
      }
  }
  ```
  - 非 EOS buffer：压入 indexs_ 缓冲队列等待 ReleaseBuffer 消费
  - EOS buffer：标记 eosBufferIndex_，稍后触发 NotifyNextFilterEos()

### 10. ReleaseBuffer 后台线程（消费循环）

- 来源：`services/media_engine/filters/video_resize_filter.cpp:502-540`
  ```cpp
  void VideoResizeFilter::ReleaseBuffer()
  {
      while (!isThreadExit_) {
          std::vector<uint32_t> indexs;
          {
              std::unique_lock<std::mutex> lock(releaseBufferMutex_);
              releaseBufferCondition_.wait(lock, [this] {
                  return isThreadExit_ || !indexs_.empty();
              });
              indexs = indexs_;
              indexs_.clear();
          }
          if (videoEnhancer_) { ReleaseOutputBuffer(indexs); }
      }
  }

  void VideoResizeFilter::ReleaseOutputBuffer(std::vector<uint32_t> &indexs)
  {
      for (auto &index : indexs) {
          if (index != eosBufferIndex_) {
              videoEnhancer_->ReleaseOutputBuffer(index, true);  // 普通 buffer 立即释放
          } else {
              videoEnhancer_->ReleaseOutputBuffer(index, false);  // EOS buffer 暂不释放
              NotifyNextFilterEos();  // 传播 EOS 到下游 Filter
          }
      }
  }
  ```
  - "VideoResize" 后台线程（Task）驱动 ReleaseBuffer 消费循环
  - condition_variable 同步生产-消费（indexs_ 队列）
  - EOS buffer 单独处理：ReleaseOutputBuffer(index, false) + NotifyNextFilterEos()

### 11. NotifyNextFilterEos EOS 传播

- 来源：`services/media_engine/filters/video_resize_filter.cpp:341-360`
  ```cpp
  Status VideoResizeFilter::NotifyNextFilterEos()
  {
      for (auto iter : nextFiltersMap_) {
          for (auto filter : iter.second) {
              std::shared_ptr<Meta> eosMeta = std::make_shared<Meta>();
              eosMeta->Set<Tag::MEDIA_END_OF_STREAM>(true);
              eosMeta->Set<Tag::USER_FRAME_PTS>(eosPts_);
              filter->SetParameter(eosMeta);  // SetParameter 传播 EOS 元数据
          }
      }
      return Status::OK;
  }
  ```
  - 遍历所有下游 Filter，通过 SetParameter(EOS Meta) 级联传播

### 12. 头文件完整成员变量

- 来源：`interfaces/inner_api/native/video_resize_filter.h:33-109`
  ```cpp
  class VideoResizeFilter : public Filter, public std::enable_shared_from_this<VideoResizeFilter> {
  private:
      std::shared_ptr<EventReceiver> eventReceiver_;
      std::shared_ptr<FilterCallback> filterCallback_;
      std::shared_ptr<FilterLinkCallback> onLinkedResultCallback_;
  #ifdef USE_VIDEO_PROCESSING_ENGINE
      std::shared_ptr<VideoProcessingEngine::DetailEnhancerVideo> videoEnhancer_;
      bool isVPEReportError_ {false};
  #endif
      std::shared_ptr<Filter> nextFilter_;
      std::mutex releaseBufferMutex_;
      std::condition_variable releaseBufferCondition_;
      std::shared_ptr<Task> releaseBufferTask_{nullptr};  // "VideoResize" 后台线程
      std::vector<uint32_t> indexs_;                      // 缓冲 index 队列
      uint32_t eosBufferIndex_ {UINT32_MAX};              // EOS buffer 标记
      int64_t eosPts_ {UINT32_MAX};
      std::atomic<int64_t> currentFrameNum_ = 0;
      std::atomic<bool> isThreadExit_ = true;
  };
  ```

---

## 核心发现

### 1. FILTERTYPE_VIDRESIZE 注册与工厂模式
- 注册名 `"builtin.transcoder.videoresize"`，AutoRegisterFilter 静默注册
- Lambda 工厂模式，按 FilterType 分发创建
- 与 S10 SeiParserFilter（"builtin.player.seiParser"）并列转码辅助 Filter

### 2. DetailEnhancerVideo 双 Surface 桥接
- `GetInputSurface()`：从上游 Filter 获取 Surface 作为 Producer
- `SetOutputSurface()`：向下游 Filter 注入 Surface 作为 Consumer
- 形成转码 Pipeline 双 Surface 桥接拓扑

### 3. VPE 编译开关（USE_VIDEO_PROCESSING_ENGINE）
- 所有 VPE 调用受编译开关保护，无 VPE 模块时直接上报 MSERR_UNKNOWN/EVENT_ERROR
- **无 VPE fallback**：整个 Filter 降级为仅报错，不提供软件 fallback

### 4. DETAIL_ENH_LEVEL_MEDIUM 固定增强级别
- Configure() 固定设置 DETAIL_ENH_LEVEL_MEDIUM，增强级别不可动态调整
- 与 S15 SuperResolutionPostProcessor（同样使用 DetailEnhancerVideo）场景不同

### 5. ReleaseBuffer 后台线程（生产-消费模式）
- "VideoResize" TaskThread 驱动 ReleaseBuffer 消费循环
- OnOutputBufferAvailable 收集 buffer index 到 indexs_ 队列（生产端）
- ReleaseBuffer 线程阻塞等待 indexs_ 非空（消费端），condition_variable 同步
- EOS buffer 与普通 buffer 分流处理（ReleaseOutputBuffer 参数 false vs true）

### 6. EOS 级联传播链
- EOS buffer 触发 `NotifyNextFilterEos()`
- 通过 `filter->SetParameter(eosMeta)` 将 Tag::MEDIA_END_OF_STREAM 传递到下游 Filter
- 下游 Filter 收到 EOS Meta 后自行处理停止/flush 逻辑

---

## 架构位置

```
转码Pipeline（Transcoder Pipeline）：
  [上游Filter] 
    ↓ GetInputSurface() / SetOutputSurface()
  [VideoResizeFilter] ← "builtin.transcoder.videoresize" / FILTERTYPE_VIDRESIZE
    ↕ DetailEnhancerVideo::Create() / Start() / Stop()
  [下游Filter]
    ↓ SetParameter(EOS Meta) 级联传播
```

---

## 依赖关系

| 关联主题 | 关系 | 说明 |
|---------|------|------|
| S10（SeiParserFilter） | 并列 | 同为转码辅助 Filter，并列关系 |
| S15（SuperResolutionPostProcessor） | 引擎共用 | 同为 VPE DetailEnhancer 系列后处理器 |
| S33（PreProcessing） | 前后处理 | 预处理丢帧，与 VideoResizeFilter 构成转码 Pipeline 前后处理 |
| S20（PostProcessing） | 关联 | PostProcessing 框架可能调用 VideoResizeFilter |

---

## 备注

- VideoResizeFilter 与 SuperResolutionPostProcessor（S15）均使用 DetailEnhancerVideo，但场景不同：
  - VideoResizeFilter：转码分辨率变换
  - SuperResolutionPostProcessor：播放后处理超分
- DETAIL_ENH_LEVEL_MEDIUM 为固定增强级别，无动态调整接口
- 无 VPE fallback，编译时若无 VPE 模块整个 Filter 降级为纯报错
- 566行 cpp + 113行 h，行号级证据已完整（2026-05-04 更新）
