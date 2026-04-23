---
type: architecture
id: MEM-ARCH-AVCODEC-S12
status: draft
topic: VideoResizeFilter 转码增强过滤器——DetailEnhancerVideo视频处理引擎与FILTERTYPE_VIDRESIZE插件注册
created_at: "2026-04-23T23:22:00+08:00"
evidence: |
  - source: /home/west/av_codec_repo/interfaces/inner_api/native/video_resize_filter.h
    anchor: "AutoRegisterFilter g_registerVideoResizeFilter(\"builtin.transcoder.videoresize\", FilterType::FILTERTYPE_VIDRESIZE)"
  - source: /home/west/av_codec_repo/services/media_engine/filters/video_resize_filter.cpp
    anchor: "DetailEnhancerVideo::Create(), videoEnhancer_->GetInputSurface()/SetOutputSurface()"
  - source: /home/west/av_codec_repo/services/media_engine/filters/sei_parser_filter.cpp
    anchor: "AutoRegisterFilter g_registerSeiParserFilter(\"builtin.player.seiParser\", FilterType::FILTERTYPE_SEI)"
---

# MEM-ARCH-AVCODEC-S12: VideoResizeFilter 转码增强过滤器

## Metadata

| 字段 | 值 |
|------|-----|
| id | MEM-ARCH-AVCODEC-S12 |
| title | VideoResizeFilter 转码增强过滤器——DetailEnhancerVideo视频处理引擎与FILTERTYPE_VIDRESIZE插件注册 |
| scope | [AVCodec, MediaEngine, Filter, Transcoder, VideoProcessingEngine, VPE, Plugin] |
| status | draft |
| created_by | builder-agent |
| created_at | 2026-04-23 |
| type | architecture_fact |
| confidence | medium |

## 摘要

VideoResizeFilter 是 media_engine filters 中专用于**视频转码（Transcoder）场景**的 Filter，注册名为 `"builtin.transcoder.videoresize"`，FilterType 为 `FILTERTYPE_VIDRESIZE`。

其核心职责是在转码 Pipeline 中接收上一个 Filter 输出的 Video Surface，通过 **VideoProcessingEngine（VPE）DetailEnhancerVideo** 模块对视频进行分辨率变换（resize）和细节增强（detail enhance），输出到下一个 Filter 的 Surface。

该 Filter 与 SeiParserFilter（SEI 解析）、VideoCaptureFilter（采集）同属 player/transcoder 辅助 Filter 体系。与播放 Pipeline 不同，转码 Pipeline 依赖 VideoResizeFilter 实现视频增强而非依赖硬件解码器直接输出 Surface。

## 关键类与接口

### VideoResizeFilter
- **文件**: `services/media_engine/filters/video_resize_filter.cpp`
- **头文件**: `interfaces/inner_api/native/video_resize_filter.h`
- **注册名**: `"builtin.transcoder.videoresize"`
- **FilterType**: `FILTERTYPE_VIDRESIZE`
- **LOG_DOMAIN**: `LOG_DOMAIN_SYSTEM_PLAYER`（"VideoResizeFilter"）

#### 核心方法

| 方法 | 职责 |
|------|------|
| `GetInputSurface()` | 获取 VPE DetailEnhancerVideo 的输入 Surface，供上游 Filter 写入 |
| `SetOutputSurface(surface, width, height)` | 设置输出 Surface 及目标分辨率 |
| `Configure(parameter)` | 配置转码参数，内部调用 VPE 配置接口 |
| `SetCodecFormat(format)` | 设置 Codec 格式元数据 |
| `LinkNext / UpdateNext / UnLinkNext` | 链式连接下游 Filter |
| `OnOutputBufferAvailable(index, flag)` | 处理 VPE 输出 buffer，完成后回调通知下游 |

### DetailEnhancerVideo（VPE 模块）
- **来源**: `VideoProcessingEngine`（`USE_VIDEO_PROCESSING_ENGINE` 宏控制）
- **创建**: `DetailEnhancerVideo::Create()`
- **职责**: 视频细节增强与分辨率变换的硬件/软件协同处理
- **回调**: `ResizeDetailEnhancerVideoCallback : DetailEnhancerVideoCallback`

### VideoResizeFilterLinkCallback（内部类）
- **职责**: 实现 `FilterLinkCallback`，将链式链接结果（AVBufferQueueProducer）转发给 VideoResizeFilter

## 数据流

```
转码 Pipeline（典型场景）:
  DemuxerFilter（解封装）
    → VideoDecoderFilter（解码）
      → VideoResizeFilter（并行处理 Surface）
          → DetailEnhancerVideo（VPE 视频增强）
            → GetInputSurface() / SetOutputSurface()
      → AudioEncoderFilter（编码）
    → MuxerFilter（封装）
```

关键流程：
1. **DoPrepare()** → `videoEnhancer_ = DetailEnhancerVideo::Create()`
2. **Configure(parameter)** → `videoEnhancer_->SetOutputSurface()` + 元数据配置
3. **GetInputSurface()** → 将 VPE 输入 Surface 返回给上游 Filter（Decoder）作为渲染目标
4. **OnOutputBufferAvailable(index, flag)** → VPE 回调，标记 buffer 完成，增强后推送给下游

## VPE（VideoProcessingEngine）集成

VPE 是独立视频处理引擎模块，通过 `USE_VIDEO_PROCESSING_ENGINE` 宏控制编译：

```cpp
#ifdef USE_VIDEO_PROCESSING_ENGINE
#include "detail_enhancer_video.h"
#include "detail_enhancer_video_common.h"
std::shared_ptr<VideoProcessingEngine::DetailEnhancerVideo> videoEnhancer_;
videoEnhancer_ = DetailEnhancerVideo::Create();
std::shared_ptr<DetailEnhancerVideoCallback> detailEnhancerVideoCallback =
    std::make_shared<ResizeDetailEnhancerVideoCallback>(shared_from_this());
videoEnhancer_->SetCallback(detailEnhancerVideoCallback);
#endif
```

**ResizeDetailEnhancerVideoCallback** 处理来自 VPE 的两类回调：
- `OnError(VPEAlgoErrCode)` → 调用 `VideoResizeFilter::OnVPEError(errorCode)` 上报错误
- `OnState(VPEAlgoState)` → 预留状态通知（当前为空实现）

## Buffer 管理

- VPE 处理完成后通过 `OnOutputBufferAvailable` 回调通知
- `ReleaseBufferTask` 异步任务处理 buffer 释放，避免同步阻塞
- 释放 mutex + condition_variable 控制并发释放

```cpp
std::mutex releaseBufferMutex_;
std::condition_variable releaseBufferCondition_;
std::shared_ptr<Task> releaseBufferTask_{nullptr};
std::vector<uint32_t> indexs_;  // 待释放 buffer 索引
```

## 与其他 Filter 的关系

| Filter | 注册名 | FilterType | 关系 |
|--------|--------|-----------|------|
| VideoResizeFilter | builtin.transcoder.videoresize | FILTERTYPE_VIDRESIZE | **本主题** |
| VideoCaptureFilter | builtin.transcoder.videocapture | FILTERTYPE_VIDCAP | 同属 transcoder 辅助体系 |
| VideoDecoderFilter | builtin.player.videodecoder | FILTERTYPE_VDEC | 上游数据源（写入 Surface） |
| MuxerFilter | builtin.muxer | FILTERTYPE_MUXER | 下游数据汇（接收编码后数据） |
| SeiParserFilter | builtin.player.seiParser | FILTERTYPE_SEI | 同属辅助 Filter（SEI 解析） |
| AudioEncoderFilter | builtin.audioencoder | FILTERTYPE_AENC | 同级（音频编码） |

## 调用者信息追踪

VideoResizeFilter 实现了 `SetCallingInfo` 以支持按调用方（AppUid/AppPid/BundleName/InstanceId）上报错误：

```cpp
void SetCallingInfo(int32_t appUid, int32_t appPid, const std::string &bundleName, uint64_t instanceId);
void SetFaultEvent(const std::string &errMsg);
void SetFaultEvent(const std::string &errMsg, int32_t ret);
```

## Filter 注册机制（与 S5/S10 对比）

VideoResizeFilter 与 SeiParserFilter 均通过 `AutoRegisterFilter` 模板注册到 Filter 工厂：

```cpp
// VideoResizeFilter
static AutoRegisterFilter<VideoResizeFilter> g_registerVideoResizeFilter(
    "builtin.transcoder.videoresize",
    FilterType::FILTERTYPE_VIDRESIZE,
    [](const std::string& name, const FilterType type) {
        return std::make_shared<VideoResizeFilter>(name, type);
    });

// SeiParserFilter（S10）
static AutoRegisterFilter<SeiParserFilter> g_registerSeiParserFilter(
    "builtin.player.seiParser",
    FilterType::FILTERTYPE_SEI,
    [](const std::string &name, const FilterType type) {
        return std::make_shared<SeiParserFilter>(name, type);
    });
```

两者模式完全一致，差异仅在 FilterType 枚举值和具体 Filter 实现类。

## 相关已有记忆

- **MEM-ARCH-AVCODEC-S10**: SeiParserFilter SEI 解析过滤器（同属 transcoder/player 辅助 Filter）
- **MEM-ARCH-AVCODEC-S5**: 四层 Loader 插件热加载机制（AutoRegisterFilter 注册机制同出一源）
- **MEM-ARCH-AVCODEC-S3**: CodecServer Pipeline 数据流与状态机（VideoResizeFilter 位于 decoder 下游、muxer 上游）

## 待补充

- FILTERTYPE_VIDRESIZE 在 filter_type.h 中的枚举定义
- DetailEnhancerVideo 完整 API（需查 VPE 模块头文件）
- VideoResizeFilter 与 VideoCaptureFilter 的并用场景
- VPE 错误码与 MediaAVCodec 错误码的映射关系
- Transcoder 场景下 VideoResizeFilter 与 SurfaceCodec 的协作流程
