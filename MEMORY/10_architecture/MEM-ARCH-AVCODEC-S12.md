---
type: architecture
id: MEM-ARCH-AVCODEC-S12
status: pending_approval
topic: VideoResizeFilter 转码增强过滤器——DetailEnhancerVideo视频处理引擎与FILTERTYPE_VIDRESIZE插件注册
created_at: "2026-04-24T00:05:00+08:00"
updated_at: "2026-05-04T01:20:00+08:00"
---

# MEM-ARCH-AVCODEC-S12

## 主题
VideoResizeFilter 转码增强过滤器——DetailEnhancerVideo 视频处理引擎与 FILTERTYPE_VIDRESIZE 插件注册

## 状态
status: draft

## 源码证据

- 来源：`services/media_engine/filters/video_resize_filter.cpp:36-40`
  - AutoRegisterFilter 注册：`"builtin.transcoder.videoresize"`, `FilterType::FILTERTYPE_VIDRESIZE`
  - Lambda 工厂：`[](const std::string& name, const FilterType type)` 创建 VideoResizeFilter 实例

- 来源：`services/media_engine/filters/video_resize_filter.cpp:131-149`
  - Init() 流程：DetailEnhancerVideo::Create() 创建 VPE 引擎；ResizeDetailEnhancerVideoCallback 注册回调
  - USE_VIDEO_PROCESSING_ENGINE 编译开关：无 VPE 模块时上报 MSERR_UNKNOWN 错误

- 来源：`services/media_engine/filters/video_resize_filter.cpp:166-192`
  - Configure()：DetailEnhancerParameters = {"", DETAIL_ENH_LEVEL_MEDIUM}；videoEnhancer_->SetParameter(parameter_, SourceType::VIDEO)
  - 无 VPE 模块时返回 ERROR_NULL_POINTER / ERROR_UNKNOWN

- 来源：`services/media_engine/filters/video_resize_filter.cpp:194-214`
  - GetInputSurface()：videoEnhancer_->GetInputSurface() 获取输入 Surface
  - SetOutputSurface()：videoEnhancer_->SetOutputSurface(surface) 设置输出 Surface

- 来源：`services/media_engine/filters/video_resize_filter.cpp:270-289`
  - DoStart()：videoEnhancer_->Start() 启动 VPE；releaseBufferTask_ 后台线程释放缓冲区
  - DoStop()：videoEnhancer_->Stop() 停止 VPE；notify_all() 唤醒 releaseBufferCondition_

- 来源：`services/media_engine/filters/video_resize_filter.cpp:466-550`
  - OnOutputBufferAvailable(index, flag)：indexs_ 队列收集；flag==DETAIL_ENH_BUFFER_FLAG_EOS 时标记 eosBufferIndex_
  - ReleaseBuffer()：releaseBufferTask_ 后台线程 Loop；std::unique_lock + condition_variable 等待
  - ReleaseOutputBuffer(indexs)：videoEnhancer_->ReleaseOutputBuffer(index, isEos)；eos 时 NotifyNextFilterEos()

- 来源：`services/media_engine/filters/video_resize_filter.cpp:100-130`
  - ResizeDetailEnhancerVideoCallback：实现 DetailEnhancerVideoCallback（OnError/OnOutputBufferAvailable）；OnError → OnVPEError(errorCode)

- 来源：`interfaces/inner_api/native/video_resize_filter.h:50-85`
  - 私有成员：videoEnhancer_(DetailEnhancerVideo)、releaseBufferTask_(Task)、indexs_/eosBufferIndex_ 缓冲队列、currentFrameNum_ 原子计数器、releaseBufferMutex_/releaseBufferCondition_

- 来源：`services/media_engine/filters/video_resize_filter.cpp:352-383`
  - LinkNext()：VideoResizeFilterLinkCallback（FilterLinkCallback 实现）；nextFilter_->OnLinked() 级联链路建立
  - SetParameter(EOS)：videoEnhancer_->NotifyEos() + eosPts_ 传播到下游 Filter

## 核心发现

1. **FILTERTYPE_VIDRESIZE 注册**：注册名 "builtin.transcoder.videoresize"，AutoRegisterFilter 工厂模式，与 "builtin.player.seiParser"（S10）并列转码辅助 Filter

2. **DetailEnhancerVideo 双 Surface 模式**：GetInputSurface() 获取上游 Surface，SetOutputSurface() 注入下游 Surface，形成双 Surface 桥接；Configure() 设置 DETAIL_ENH_LEVEL_MEDIUM 增强级别

3. **VPE 编译开关 USE_VIDEO_PROCESSING_ENGINE**：整个 VPE 调用受编译开关保护，无 VPE 模块时 Filter 降级为直接报错（MSERR_UNKNOWN），不提供无 VPE fallback

4. **ReleaseBuffer 后台线程**：releaseBufferTask_（"VideoResize" 命名线程）驱动 ReleaseBuffer Loop；OnOutputBufferAvailable 回调收集 index 到 indexs_ 队列，condition_variable 同步生产-消费

5. **EOS 级联传播**：DETAIL_ENH_BUFFER_FLAG_EOS 标记最后一帧；ReleaseOutputBuffer(false) 不释放 EOS buffer → NotifyNextFilterEos() 通过 nextFilter_->SetParameter(EOS Meta) 传播到下游 Filter

## 依赖关系
- S10（SeiParserFilter）—— 同为转码/播放辅助 Filter，并列关系
- S15（SuperResolutionPostProcessor）—— 同为 VPE DetailEnhancer 系列后处理器
- S33（PreProcessing FrameDropFilter）—— 预处理丢帧，与 VideoResizeFilter 构成转码 Pipeline 前后处理

## 备注
- 当前草案（2026-04-24）证据较简略，本次重新分析源码，行号级证据已更新（566行 cpp + 113行 h）
- VideoResizeFilter 与 SuperResolutionPostProcessor（S15）均使用 DetailEnhancerVideo，但场景不同：VideoResizeFilter 用于转码分辨率变换，SuperResolutionPostProcessor 用于播放后处理超分
- DETAIL_ENH_LEVEL_MEDIUM 为固定增强级别，无动态调整接口