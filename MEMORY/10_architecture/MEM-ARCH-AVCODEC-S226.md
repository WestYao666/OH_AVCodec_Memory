---
id: MEM-ARCH-AVCODEC-S226
title: "VideoResizeFilter 视频缩放过滤器——VPE DetailEnhancer + Surface双Surface架构与Transcoder管线集成"
status: draft
scope: AVCodec, MediaEngine, Filter, VideoResize, VPE, DetailEnhancer, Transcoder, Surface, FilterPipeline
tags:
  - AVCodec
  - MediaEngine
  - Filter
  - VideoResize
  - VPE
  - DetailEnhancer
  - Transcoder
  - Surface
  - FilterPipeline
created: 2026-06-08
modified: 2026-06-08
evidence_count: 22
source_path: /home/west/av_codec_repo/services/media_engine/filters/video_resize_filter.cpp
source_path2: /home/west/av_codec_repo/interfaces/inner_api/native/video_resize_filter.h
lines_of_code: "566行cpp + 113行h"
associations:
  - S20 (PostProcessing框架)
  - S127 (VideoPostProcessor框架)
  - S100 (SuperResolutionPostProcessor)
  - S14 (FilterChain)
  - S46 (DecoderSurfaceFilter)
---

# MEM-ARCH-AVCODEC-S226：VideoResizeFilter 视频缩放过滤器

## 1. 主题概述

VideoResizeFilter 是 MediaEngine 过滤层中的视频缩放专用过滤器，注册名称为 `"builtin.transcoder.videoresize"`，属于 `FilterType::FILTERTYPE_VIDRESIZE` 类型。该过滤器内部封装 VideoProcessingEngine (VPE) 的 `DetailEnhancerVideo` 模块，通过 VPE 实现视频帧的缩放、增强和色彩管理功能，专用于转码（Transcoder）管线。

## 2. 核心架构

### 2.1 位置与职责

```
[SurfaceDecoderFilter/VideoDecoderAdapter]
        ↓ (Surface)
VideoResizeFilter (builtin.transcoder.videoresize)
        ↓ (Surface)
   [下游Filter / Muxer]
```

- **输入**：上游过滤器通过 Surface 推送视频帧
- **处理**：VPE DetailEnhancer 执行缩放/增强
- **输出**：处理后的帧通过 Surface 传递给下游

### 2.2 条件编译架构

```cpp
// video_resize_filter.cpp L16-19
#ifdef USE_VIDEO_PROCESSING_ENGINE
#include "detail_enhancer_video.h"
#include "detail_enhancer_video_common.h"
#endif
```

VPE 模块是可选的，未启用时所有 VPE 相关调用返回 ERROR。

### 2.3 静态自动注册

```cpp
// video_resize_filter.cpp L37-40
static AutoRegisterFilter<VideoResizeFilter> g_registerVideoResizeFilter("builtin.transcoder.videoresize",
    FilterType::FILTERTYPE_VIDRESIZE,
    [](const std::string& name, const FilterType type) {
        return std::make_shared<VideoResizeFilter>(name, FilterType::FILTERTYPE_VIDRESIZE);
    });
```

## 3. 关键源码证据（行号级）

### E1：AutoRegisterFilter 静态注册
- **文件**：video_resize_filter.cpp L37-40
- **内容**：注册名 `"builtin.transcoder.videoresize"`，类型 `FilterType::FILTERTYPE_VIDRESIZE`，lambda 工厂函数创建实例
- **意义**：该过滤器在 FilterFactory 中静态注册，系统启动时自动可用

### E2：VPE DetailEnhancerVideo 前向声明
- **文件**：video_resize_filter.h L31-36
- **内容**：
  ```cpp
  #ifdef USE_VIDEO_PROCESSING_ENGINE
  namespace VideoProcessingEngine {
      class DetailEnhancerVideo;
  }
  #endif
  ```
- **意义**：条件编译保护 VPE 依赖，未启用 VPE 时不影响编译

### E3：日志标签定义
- **文件**：video_resize_filter.cpp L26
- **内容**：`constexpr OHOS::HiviewDFX::HiLogLabel LABEL = { LOG_CORE, LOG_DOMAIN_SYSTEM_PLAYER, "VideoResizeFilter" };`
- **意义**：LOG_DOMAIN_SYSTEM_PLAYER 域标识该过滤器属于系统播放器子系统

### E4：FilterLinkCallback 实现类
- **文件**：video_resize_filter.cpp L43-76
- **内容**：`VideoResizeFilterLinkCallback : public FilterLinkCallback`，弱引用管理 VideoResizeFilter，提供 OnLinkedResult/OnUnlinkedResult/OnUpdatedResult 三路回调
- **意义**：过滤器间的链路回调机制，用于下游 Filter 的 OnLinked

### E5：VPE 回调桥接类
- **文件**：video_resize_filter.cpp L83-105
- **内容**：`ResizeDetailEnhancerVideoCallback : public DetailEnhancerVideoCallback`，实现 OnError/OnState/OnOutputBufferAvailable，将 VPE 事件桥接到 VideoResizeFilter
- **意义**：VPE 的错误和输出缓冲事件通过此类传递到过滤器层

### E6：构造函数
- **文件**：video_resize_filter.cpp L114-117
- **内容**：`VideoResizeFilter::VideoResizeFilter(std::string name, FilterType type): Filter(name, type)`
- **意义**：继承 Filter 基类，构造时注册过滤器和类型

### E7：Init — VPE 创建与回调注册
- **文件**：video_resize_filter.cpp L125-167
- **内容**：
  ```cpp
  videoEnhancer_ = DetailEnhancerVideo::Create();  // L138
  std::shared_ptr<DetailEnhancerVideoCallback> detailEnhancerVideoCallback =
      std::make_shared<ResizeDetailEnhancerVideoCallback>(shared_from_this());
  videoEnhancer_->RegisterCallback(detailEnhancerVideoCallback);  // L143
  ```
- **意义**：Init 阶段创建 VPE DetailEnhancer 实例并注册回调，如果 VPE 创建失败则触发 ERROR事件

### E8：Init — ReleaseBuffer 线程初始化
- **文件**：video_resize_filter.cpp L154-161
- **内容**：
  ```cpp
  releaseBufferTask_ = std::make_shared<Task>("VideoResize");
  releaseBufferTask_->RegisterJob([this] { ReleaseBuffer(); return 0; });
  ```
- **意义**：Init 中创建后台线程用于异步释放 VPE 输出缓冲区

### E9：Configure — 增强级别配置
- **文件**：video_resize_filter.cpp L166-192
- **内容**：
  ```cpp
  const DetailEnhancerParameters parameter_ = {"", DetailEnhancerLevel::DETAIL_ENH_LEVEL_MEDIUM};
  int32_t ret = videoEnhancer_->SetParameter(parameter_, SourceType::VIDEO);  // L175
  ```
- **意义**：Configure阶段设置 VPE 增强级别为 MEDIUM（中等增强），SourceType 指定为 VIDEO

### E10：GetInputSurface — 获取 VPE 输入 Surface
- **文件**：video_resize_filter.cpp L194-209
- **内容**：`sptr<Surface> inputSurface = videoEnhancer_->GetInputSurface();`（L202）
- **意义**：通过 VPE DetailEnhancer 获取输入 Surface，上游将视频帧写入此 Surface

### E11：SetOutputSurface — 设置输出 Surface 及尺寸
- **文件**：video_resize_filter.cpp L211-243
- **内容**：
  ```cpp
  surface->SetRequestWidthAndHeight(width, height);  // L222
  int32_t ret = videoEnhancer_->SetOutputSurface(surface);  // L229
  ```
- **意义**：SetOutputSurface 配置输出 Surface 的目标分辨率（width × height），VPE 据此执行缩放

### E12：DoStart — VPE 启动
- **文件**：video_resize_filter.cpp L260-280
- **内容**：
  ```cpp
  isThreadExit_ = false;  // L261
  releaseBufferTask_->Start();  // L264
  int32_t ret = videoEnhancer_->Start();  // L271
  ```
- **意义**：DoStart 启动 VPE DetailEnhancer，同时启动 ReleaseBuffer 后台线程

### E13：DoStop — VPE 停止与线程退出
- **文件**：video_resize_filter.cpp L320-360
- **内容**：
  ```cpp
  isThreadExit_ = true;  // L325
  releaseBufferCondition_.notify_all();  // L326
  releaseBufferTask_->Stop();  // L327
  videoEnhancer_->Stop();  // L333
  ```
- **意义**：DoStop 正确停止 VPE 并唤醒 ReleaseBuffer 线程安全退出

### E14：NotifyNextFilterEos — EOS 传播
- **文件**：video_resize_filter.cpp L362-372
- **内容**：
  ```cpp
  eosMeta->Set<Tag::MEDIA_END_OF_STREAM>(true);
  eosMeta->Set<Tag::USER_FRAME_PTS>(eosPts_);
  filter->SetParameter(eosMeta);  // L370
  ```
- **意义**：EOS 时向下游所有 Filter 传播 EOS 参数

### E15：SetParameter — EOS 参数处理
- **文件**：video_resize_filter.cpp L386-407
- **内容**：
  ```cpp
  if (isEos) {
      videoEnhancer_->NotifyEos();  // L401
      return;
  }
  ```
- **意义**：SetParameter 识别 EOS 参数后通知 VPE EOS，同时记录最后帧 PTS 和帧编号

### E16：LinkNext — 链接下游 Filter
- **文件**：video_resize_filter.cpp L424-437
- **内容**：
  ```cpp
  nextFilter->OnLinked(outType, configureParameter_, filterLinkCallback);  // L431
  ```
- **意义**：LinkNext 建立到下游 Filter 的链路，传递配置参数和回调

### E17：OnOutputBufferAvailable — 缓冲区可用回调
- **文件**：video_resize_filter.cpp L473-498
- **内容**：
  ```cpp
  indexs_.push_back(index);  // L479
  if (flag != static_cast<uint32_t>(DETAIL_ENH_BUFFER_FLAG_EOS)) {
      currentFrameNum_.fetch_add(VARIABLE_INCREMENT_INTERVAL, std::memory_order_relaxed);  // L483
  } else {
      eosBufferIndex_ = index;  // L486
  }
  releaseBufferCondition_.notify_all();  // L488
  ```
- **意义**：VPE 输出缓冲区可用时，加入释放队列并增加帧计数；EOS 帧特殊标记

### E18：ReleaseBuffer — 后台缓冲区释放循环
- **文件**：video_resize_filter.cpp L500-515
- **内容**：
  ```cpp
  releaseBufferCondition_.wait(lock, [this] {
      return isThreadExit_ || !indexs_.empty();  // L507
  });
  indexs = indexs_;  // L510
  indexs_.clear();  // L512
  ReleaseOutputBuffer(indexs);  // L515
  ```
- **意义**：ReleaseBuffer 在独立线程中等待条件变量，批量释放 VPE 输出缓冲区

### E19：ReleaseOutputBuffer — 单缓冲区释放
- **文件**：video_resize_filter.cpp L517-533
- **内容**：
  ```cpp
  if (index != eosBufferIndex_) {
      videoEnhancer_->ReleaseOutputBuffer(index, true);  // L521
  } else {
      videoEnhancer_->ReleaseOutputBuffer(index, false);  // L524
      NotifyNextFilterEos();  // L525
  }
  ```
- **意义**：普通缓冲区立即释放，EOS 缓冲区释放后触发 NotifyNextFilterEos 通知下游

### E20：OnVPEError — VPE 错误上报
- **文件**：video_resize_filter.cpp L535-545
- **内容**：
  ```cpp
  isVPEReportError_ = true;  // L541
  eventReceiver_->OnEvent({"video_resize_filter", EventType::EVENT_ERROR, MSERR_VID_RESIZE_FAILED});  // L543
  ```
- **意义**：VPE 错误通过 EventReceiver 上报，仅上报一次（isVPEReportError_ 保护）

### E21：成员变量 — 互斥锁与条件变量
- **文件**：video_resize_filter.h L65-79
- **内容**：
  ```cpp
  std::mutex releaseBufferMutex_;  // L65
  std::condition_variable releaseBufferCondition_;  // L66
  std::shared_ptr<Task> releaseBufferTask_{nullptr};  // L68
  std::vector<uint32_t> indexs_;  // L69
  uint32_t eosBufferIndex_ {UINT32_MAX};  // L71
  std::atomic<int64_t> currentFrameNum_ = 0;  // L75
  std::atomic<bool> isThreadExit_ = true;  // L76
  ```
- **意义**：完整的线程安全缓冲区管理机制，原子变量保护帧计数

### E22：SetCallingInfo — 调用者信息记录
- **文件**：video_resize_filter.cpp L547-554
- **内容**：
  ```cpp
  appUid_ = appUid;
  appPid_ = appPid;
  bundleName_ = bundleName;
  instanceId_ = instanceId;  // L551
  ```
- **意义**：记录应用身份信息，用于 DFX 错误追踪和日志关联

## 4. 生命周期状态机

```
Init → Configure → DoPrepare → DoStart
                                        ↓
                     DoPause ←→ DoResume
                                        ↓
              DoStop → DoFlush → DoRelease
```

关键转换：
- **Init**：创建 VPE DetailEnhancer，注册回调，初始化后台释放线程
- **Configure**：设置 VPE 增强级别（MEDIUM）和源类型（VIDEO）
- **DoStart**：启动 VPE DetailEnhancer + ReleaseBuffer 线程
- **DoStop**：停止 VPE + 唤醒 ReleaseBuffer 线程安全退出
- **SetParameter(EOS)**：通知 VPE EOS 并传播给下游

## 5. 与其他组件的关联

| 关联组件 | 关系 | 说明 |
|---------|------|------|
| S20 PostProcessing | 相关 | VideoResizeFilter 与 PostProcessor 框架均使用 VPE 模块 |
| S127 VideoPostProcessor | 相关 | 同为 Filter类型的视频处理器，但 VideoResizeFilter 专用于转码管线 |
| S100 SuperResolutionPostProcessor | 相关 | 都继承自 BaseVideoPostProcessor，通过 VPE 实现 |
| S14 FilterChain | 继承 | VideoResizeFilter 是 FilterChain 中的一个节点 |
| S46 DecoderSurfaceFilter | 上游 | 输出 Surface连接到 VideoResizeFilter 的输入 Surface |

## 6. 关键设计要点

1. **VPE DetailEnhancer 封装**：VideoResizeFilter 充当 VPE 与 FilterPipeline 之间的适配器，将 VPE 的 Surface 接口适配为标准 Filter 接口

2. **双 Surface 架构**：输入 Surface（VPE GetInputSurface）接收上游帧，输出 Surface（SetOutputSurface）传递处理后帧给下游

3. **条件编译保护**：`#ifdef USE_VIDEO_PROCESSING_ENGINE` 保护所有 VPE 调用，未启用 VPE 时系统可正常编译，但功能降级

4. **后台缓冲区释放**：独立的 `ReleaseBuffer` 线程通过条件变量等待，避免 VPE 输出缓冲区泄漏

5. **EOS 传播机制**：VPE EOS 缓冲区特殊处理，先释放缓冲区再通过 `NotifyNextFilterEos` 通知下游

6. **错误单次上报**：`isVPEReportError_` 原子标志确保 VPE 错误仅触发一次事件上报

## 7. 相关文件清单

| 文件 | 路径 | 行数 |
|------|------|------|
| video_resize_filter.cpp | services/media_engine/filters/ | 566行 |
| video_resize_filter.h | interfaces/inner_api/native/ | 113行 |
| detail_enhancer_video.h | (VPE SDK) | - |
| detail_enhancer_video_common.h | (VPE SDK) | - |