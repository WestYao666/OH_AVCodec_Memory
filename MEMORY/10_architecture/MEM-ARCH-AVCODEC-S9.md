---
id: MEM-ARCH-AVCODEC-S9
title: VideoResizeFilter 转码视频增强过滤器——VPE DetailEnhancer 与 FILTERTYPE_VIDRESIZE
scope: [AVCodec, Transcoder, VideoResize, VideoProcessingEngine, VPE, Filter, DetailEnhancer]
status: pending_approval
created_by: builder-agent
created_at: "2026-04-23T12:55:00+08:00"
type: architecture_fact
confidence: medium
summary: >
  VideoResizeFilter 是 media_engine filters 中专用于转码（Transcoder）场景的视频增强过滤器，
  注册名为 "builtin.transcoder.videoresize"，FilterType 为 FILTERTYPE_VIDRESIZE。
  内部通过 VideoProcessingEngine（VPE）的 DetailEnhancerVideo 实现视频质量增强与尺寸调整，
  与 VideoCaptureFilter（采集）、SeiParserFilter（SEI 解析）、SubtitleSinkFilter（字幕）等共同构成
  转码 Pipeline 的辅助 Filter 体系。
  当 USE_VIDEO_PROCESSING_ENGINE 未定义时，Filter 启动失败并上报 EVENT_ERROR。
evidence:
  - kind: local_file
    path: /home/west/OH_AVCodec/services/media_engine/filters/video_resize_filter.cpp
    anchor: Line 37: g_registerVideoResizeFilter("builtin.transcoder.videoresize", FILTERTYPE_VIDRESIZE); Line 21-22: #include "detail_enhancer_video.h" + "detail_enhancer_video_common.h"; Line 138: DetailEnhancerVideo::Create(); Line 175: DetailEnhancerLevel::DETAIL_ENH_LEVEL_MEDIUM; Line 253: case FilterType::FILTERTYPE_VIDRESIZE
owner: 耀耀
review: pending
---

# MEM-ARCH-AVCODEC-S9: VideoResizeFilter 转码视频增强过滤器

## Metadata

| 字段 | 值 |
|------|-----|
| id | MEM-ARCH-AVCODEC-S9 |
| title | VideoResizeFilter 转码视频增强过滤器——VPE DetailEnhancer 与 FILTERTYPE_VIDRESIZE |
| type | architecture_fact |
| scope | [AVCodec, Transcoder, VideoResize, VideoProcessingEngine, VPE, Filter, DetailEnhancer] |
| status | draft |
| created_by | builder-agent |
| created_at | 2026-04-23 |
| confidence | medium |

## 摘要

VideoResizeFilter 是 media_engine filters 中专用于**转码（Transcoder）场景**的视频增强过滤器，注册名为 `"builtin.transcoder.videoresize"`，FilterType 为 `FILTERTYPE_VIDRESIZE`。

其核心能力依赖 **VideoProcessingEngine（VPE）** 的 `DetailEnhancerVideo` 模块，在 transcoder pipeline 中对输入视频帧进行质量增强处理。当 VPE 模块不可用（`USE_VIDEO_PROCESSING_ENGINE` 未定义）时，Filter 启动失败并向 eventReceiver_ 上报 `EVENT_ERROR`。

该 Filter 与 VideoCaptureFilter（采集）、SeiParserFilter（SEI 解析）、SubtitleSinkFilter（字幕）等共同构成转码 Pipeline 的辅助 Filter 体系。

## 关键类与接口

### VideoResizeFilter
- **文件**: `services/media_engine/filters/video_resize_filter.cpp`
- **注册名**: `"builtin.transcoder.videoresize"`
- **FilterType**: `FILTERTYPE_VIDRESIZE`
- **LOG_DOMAIN**: `LOG_DOMAIN_SYSTEM_PLAYER`（"VideoResizeFilter"）
- **编译宏**: `USE_VIDEO_PROCESSING_ENGINE`（VPE 模块可用性开关）

### ResizeDetailEnhancerVideoCallback
- **继承**: `DetailEnhancerVideoCallback`
- **职责**: 将 VPE 回调（OnOutputBufferAvailable / OnError / OnState）转发给 VideoResizeFilter
- **关键方法**:
  - `OnOutputBufferAvailable(index, flag)` → VideoResizeFilter::OnOutputBufferAvailable
  - `OnError(errorCode)` → VideoResizeFilter::OnVPEError
  - `OnState(state)` → VideoResizeFilter 内部状态更新

### DetailEnhancerVideo（VPE）
- **来源**: `VideoProcessingEngine` 命名空间
- **创建**: `DetailEnhancerVideo::Create()`
- **关键方法**:
  - `RegisterCallback(DetailEnhancerVideoCallback*)` → 注册回调
  - `SetParameter(DetailEnhancerParameters, SourceType::VIDEO)` → 配置增强级别
  - `Start()` / `Stop()` → 生命周期控制
  - `NotifyEos()` → 通知结束
  - `ReleaseOutputBuffer(index, recycle)` → 释放输出 buffer

## 生命周期

| 阶段 | 方法 | 关键操作 |
|------|------|----------|
| Init | `VideoResizeFilter::Init()` | 创建 DetailEnhancerVideo::Create()，注册 ResizeDetailEnhancerVideoCallback |
| Configure | `VideoResizeFilter::Configure()` | SetParameter(DETAIL_ENH_LEVEL_MEDIUM) |
| DoPrepare | `VideoResizeFilter::DoPrepare()` | 判断 FilterType，打印日志 |
| DoStart | `VideoResizeFilter::DoStart()` | releaseBufferTask_->Start()，videoEnhancer_->Start() |
| DoStop | `VideoResizeFilter::DoStop()` | isThreadExit_=true，notify_all，videoEnhancer_->Stop() |
| DoPause/Resume | - | 空实现（直接返回 OK） |
| DoFlush | - | 空实现 |
| DoRelease | - | 空实现 |

## 数据流

```
输入 Surface（来自上一 Filter）
  → VideoResizeFilter.GetInputSurface()
  → DetailEnhancerVideo（VPE 内部处理）
  → ResizeDetailEnhancerVideoCallback.OnOutputBufferAvailable(index, flag)
  → VideoResizeFilter.OnOutputBufferAvailable()
  → releaseBufferTask_（"VideoResize" 线程）批量释放
  → NotifyNextFilterEos()（当 flag == DETAIL_ENH_BUFFER_FLAG_EOS）
  → 输出至下一 Filter
```

## VPE 增强级别

```cpp
const DetailEnhancerParameters parameter_ = {"", DetailEnhancerLevel::DETAIL_ENH_LEVEL_MEDIUM};
videoEnhancer_->SetParameter(parameter_, SourceType::VIDEO);
```

目前硬编码为 `DETAIL_ENH_LEVEL_MEDIUM`，不支持运行时动态调整增强级别。

## 错误处理

| 错误场景 | 处理方式 |
|----------|----------|
| Init 时 videoEnhancer_ == nullptr | 上报 EVENT_ERROR，MSERR_UNKNOWN |
| Configure/DoStart 时 videoEnhancer_ == nullptr | 上报 EVENT_ERROR，返回 ERROR_NULL_POINTER |
| VPE OnError 回调 | 上报 EVENT_ERROR，MSERR_VID_RESIZE_FAILED，设置 isVPEReportError_=true（仅上报一次） |
| USE_VIDEO_PROCESSING_ENGINE 未定义 | 所有需要 VPE 的路径返回 ERROR_UNKNOWN 并上报 EVENT_ERROR |

## 与其他 Filter 的关系

| Filter | 注册名 | FilterType | 关系 |
|--------|--------|-----------|------|
| VideoResizeFilter | builtin.transcoder.videoresize | FILTERTYPE_VIDRESIZE | **本主题** |
| VideoCaptureFilter | builtin.transcoder.videocapture | FILTERTYPE_VIDCAP | 同属 transcoder 体系 |
| SeiParserFilter | builtin.player.seiParser | FILTERTYPE_SEI | 辅助解析 |
| SubtitleSinkFilter | builtin.player.subtitlesink | FILTERTYPE_SSINK | 辅助字幕 |

## 相关已有记忆

- **MEM-ARCH-AVCODEC-S4**: Surface Mode 与 Buffer Mode 双模式切换机制（VideoResizeFilter 用于 Surface 输出场景）
- **MEM-ARCH-AVCODEC-S3**: CodecServer Pipeline 数据流与状态机（VideoResizeFilter 位于 transcoder pipeline 中间处理节点）
- **MEM-ARCH-AVCODEC-003**: Plugin 架构（AutoRegisterFilter 注册机制）

## 待补充

- DetailEnhancerVideo 的完整接口定义（需要 VPE 头文件）
- VideoResizeFilter 在 transcoder pipeline 中的具体插入位置（上游/下游 Filter 类型）
- FilterType::FILTERTYPE_VIDRESIZE 在 filter_type.h 中的枚举定义
- VideoResizeFilter 与 MediaRecorder/MediaCodec 的协作方式
- transcoder 场景下多实例（多路并发转码）的资源隔离机制
