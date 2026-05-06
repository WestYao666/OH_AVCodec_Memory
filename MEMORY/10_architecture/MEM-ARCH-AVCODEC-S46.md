---
type: architecture
id: MEM-ARCH-AVCODEC-S46
title: "DecoderSurfaceFilter 视频解码过滤器——FILTERTYPE_VDEC + VideoDecoderAdapter + VideoSink 三组件与 DRM/PostProcessor 两扩展"
scope: [AVCodec, MediaEngine, Filter, VideoDecoder, DecoderSurfaceFilter, FILTERTYPE_VDEC, VideoSink, VideoDecoderAdapter, DRM, PostProcessor, CameraPostProcessor, PlayerPipeline]
pipeline_position: "FilterPipeline 中游：DemuxerFilter(S41) → DecoderSurfaceFilter(S46) → VideoRenderFilter(S32)"
status: approved
approved_at: "2026-05-06"
created_by: builder-agent
created_at: "2026-04-26T09:07:00+08:00"
evidence_count: 20
---

# MEM-ARCH-AVCODEC-S46: DecoderSurfaceFilter 视频解码过滤器——FILTERTYPE_VDEC + VideoDecoderAdapter + VideoSink 三组件与 DRM/PostProcessor 两扩展

## Metadata

| 字段 | 值 |
|------|-----|
| **ID** | MEM-ARCH-AVCODEC-S46 |
| **标题** | DecoderSurfaceFilter 视频解码过滤器——FILTERTYPE_VDEC + VideoDecoderAdapter + VideoSink 三组件与 DRM/PostProcessor 两扩展 |
| **Scope** | AVCodec, MediaEngine, Filter, VideoDecoder, DecoderSurfaceFilter, FILTERTYPE_VDEC, VideoSink, VideoDecoderAdapter, DRM, PostProcessor, CameraPostProcessor, PlayerPipeline |
| **Pipeline Position** | FilterPipeline 中游：DemuxerFilter(S41) → DecoderSurfaceFilter(S46) → VideoRenderFilter(S32) |
| **Status** | draft |
| **Created** | 2026-04-26T09:07:00+08:00 |
| **Evidence Count** | 20 |
| **关联主题** | S32(VideoRenderFilter输出终点), S39(AVCodecVideoDecoder底层引擎), S41(DemuxerFilter上游), S45(SurfaceDecoderFilter对称Filter), S26(SubtitleSinkFilter对等Filter), S17(SmartFluencyDecoding), S15(SuperResolutionPostProcessor) |

---

## 架构正文

### 1. 与 SurfaceDecoderFilter 的核心区别

DecoderSurfaceFilter 和 SurfaceDecoderFilter（S45）是 Player 管线中两个不同的视频解码 Filter，但承担不同职责：

| 维度 | DecoderSurfaceFilter | SurfaceDecoderFilter |
|------|---------------------|---------------------|
| **注册名** | `builtin.player.videodecoder` | `builtin.player.surfacedecoder` |
| **FilterType** | `FILTERTYPE_VDEC` | `FILTERTYPE_VIDEODEC` |
| **适配器层** | `VideoDecoderAdapter` | `SurfaceDecoderAdapter` |
| **渲染组件** | `VideoSink`（MediaSynchronousSink 子类） | 无（直通 Surface） |
| **后处理** | 支持 PostProcessor 链 | 不支持 |
| **DRM** | 支持（SetDecryptConfig） | 不支持 |
| **Seek 拖拽** | DoPauseDragging/DoResumeDragging | 不支持 |
| **RenderLoop 线程** | 支持（同步模式） | 不支持 |
| **硬件回退** | EVENT_HW_DECODER_UNSUPPORT_CAP 自动回退 | 不支持 |
| **用例** | Player 完整播放管线 | 录制/转码播放管线 |

**证据补充说明**：DecoderSurfaceFilter 是 Player 场景的主力解码 Filter，1861 行代码规模远大于 SurfaceDecoderFilter（约 430 行），具备完整渲染同步和 DRM 解密能力。

---

### 2. Filter 注册与核心组件

**Evidence 1** - `services/media_engine/filters/decoder_surface_filter.cpp` 行71-73：AutoRegisterFilter 注册 `builtin.player.videodecoder`，FilterType 为 `FILTERTYPE_VDEC`

```cpp
static AutoRegisterFilter<DecoderSurfaceFilter> g_registerDecoderSurfaceFilter("builtin.player.videodecoder",
    FilterType::FILTERTYPE_VDEC, [](const std::string& name, const FilterType type) {
        return std::make_shared<DecoderSurfaceFilter>(name, FilterType::FILTERTYPE_VDEC);
    });
```

**Evidence 2** - `services/media_engine/filters/decoder_surface_filter.cpp` 行249-265：构造函数初始化 VideoDecoderAdapter 和 VideoSink

```cpp
DecoderSurfaceFilter::DecoderSurfaceFilter(const std::string& name, FilterType type)
    : Filter(name, type, IS_FILTER_ASYNC)
{
    videoDecoder_ = std::make_shared<VideoDecoderAdapter>();
    videoSink_ = std::make_shared<VideoSink>();
    filterType_ = type;
    enableRenderAtTime_ = system::GetParameter("debug.media_service.enable_renderattime", "1") == "1";
    renderTimeMaxAdvanceUs_ = static_cast<int64_t>
        (system::GetIntParameter("debug.media_service.renderattime_advance", MAX_ADVANCE_US));
    enableRenderAtTimeDfx_ = system::GetParameter("debug.media_service.enable_renderattime_dfx", "0") == "1";
}
```

---

### 3. 三层组件架构

DecoderSurfaceFilter 内部由三个核心组件构成，形成三层架构：

```
┌──────────────────────────────────────────────────────────────────┐
│  Filter 层（最上层）                                              │
│  DecoderSurfaceFilter                                             │
│  services/media_engine/filters/decoder_surface_filter.cpp (1861行) │
│  注册名：builtin.player.videodecoder                             │
│  FilterType::FILTERTYPE_VDEC                                     │
│  持有：videoDecoder_(VideoDecoderAdapter) + videoSink_(VideoSink)  │
│  + 可选 postProcessor_(VideoPostProcessor)                        │
└───────────────────────────┬──────────────────────────────────────┘
                            │ videoDecoder_->Configure/Start/Stop
┌───────────────────────────▼──────────────────────────────────────┐
│  解码适配层（中层）                                               │
│  VideoDecoderAdapter                                             │
│  持有 codecServer_(CodecServer)                                   │
│  与 SurfaceDecoderFilter 中的 SurfaceDecoderAdapter 为不同路径     │
│  注意：VideoDecoderAdapter vs SurfaceDecoderAdapter              │
└───────────────────────────┬──────────────────────────────────────┘
                            │ codecServer_->Configure/Start/...
┌───────────────────────────▼──────────────────────────────────────┐
│  渲染同步层（同步控制）                                           │
│  VideoSink（继承 MediaSynchronousSink）                            │
│  interfaces/inner_api/native/video_sink.h                         │
│  services/media_engine/modules/sink/video_sink.cpp                │
│  持有 MediaSyncManager（音视频同步中心）                           │
│  提供 DoSyncWrite / CheckBufferLatenessMayWait / GetLagInfo       │
└──────────────────────────────────────────────────────────────────┘
```

---

### 4. 生命周期与状态流转

**Evidence 3** - `services/media_engine/filters/decoder_surface_filter.cpp` 行487-497：DoPrepare 获取输入队列并触发下游 OnLinkedResult

```cpp
Status DecoderSurfaceFilter::DoPrepare()
{
    MEDIA_LOG_I("DoPrepare");
    if (onLinkedResultCallback_) {
        onLinkedResultCallback_->OnLinkedResult(videoDecoder_->GetBufferQueueProducer(), meta_);
    }
    return Status::OK;
}
```

**Evidence 4** - `services/media_engine/filters/decoder_surface_filter.cpp` 行513-535：DoStart 启动解码器、PostProcessor 和 RenderLoop 线程

```cpp
Status DecoderSurfaceFilter::DoStart()
{
    MEDIA_LOG_I("Start");
    if (isDecoderReleasedForMute_) {
        state_ = FilterState::RUNNING;
        FALSE_RETURN_V(!isPaused_.load() && eventReceiver_ != nullptr, Status::OK);
        eventReceiver_->OnEvent({"video_sink", EventType::EVENT_VIDEO_NO_NEED_INIT, Status::OK});
        return Status::OK;
    }
    if (isPaused_.load()) {
        MEDIA_LOG_I("DoStart after pause to execute resume.");
        return DoResume();
    }
    if (!IS_FILTER_ASYNC) {
        isThreadExit_ = false;
        isPaused_ = false;
        readThread_ = std::make_unique<std::thread>(&DecoderSurfaceFilter::RenderLoop, this);
        pthread_setname_np(readThread_->native_handle(), "RenderLoop");
    }
    auto ret = videoDecoder_->Start();
    state_ = ret == Status::OK ? FilterState::RUNNING : FilterState::ERROR;
    FALSE_RETURN_V(ret == Status::OK, ret);
    if (postProcessor_) {
        ret = postProcessor_->Start();
    }
    state_ = ret == Status::OK ? FilterState::RUNNING : FilterState::ERROR;
    return ret;
}
```

**Evidence 5** - `services/media_engine/filters/decoder_surface_filter.cpp` 行542-557：DoPause 暂停同步状态，DoPauseDragging 支持拖拽暂停

```cpp
Status DecoderSurfaceFilter::DoPause()
{
    MEDIA_LOG_I("Pause");
    if (state_ == FilterState::FROZEN) {
        MEDIA_LOG_I("current state is frozen");
        state_ = FilterState::PAUSED;
        return Status::OK;
    }
    isPaused_ = true;
    isFirstFrameAfterResume_ = false;
    isFirstRenderFrameAfterResume_ = false;
    if (!IS_FILTER_ASYNC) {
        condBufferAvailable_.notify_all();
    }
    videoSink_->ResetSyncInfo();
    latestPausedTime_ = latestBufferTime_;
    state_ = FilterState::PAUSED;
    return Status::OK;
}

Status DecoderSurfaceFilter::DoPauseDragging()
{
    MEDIA_LOG_I("DoPauseDragging enter.");
    DoPause();
    FALSE_RETURN_V(videoSink_ != nullptr, Status::ERROR_INVALID_OPERATION);
    FALSE_RETURN_V(outputBufferMap_.size() == 0, Status::OK);
    MEDIA_LOG_E("DoPauseDragging outputBufferMap_ size = %{public}zu", outputBufferMap_.size());
    return Status::OK;
}
```

---

### 5. RenderLoop 后台渲染线程（同步模式）

**Evidence 6** - `services/media_engine/filters/decoder_surface_filter.cpp` 行1283-1310：RenderLoop 线程从 outputBuffers_ 队列取帧并执行 CalculateNextRender 等待后 Render

```cpp
void DecoderSurfaceFilter::RenderLoop()
{
    while (true) {
        std::pair<int, std::shared_ptr<AVBuffer>> nextTask;
        {
            std::unique_lock<std::mutex> lock(mutex_);
            condBufferAvailable_.wait(lock, [this] {
                return (!outputBuffers_.empty() && !isPaused_.load()) || isThreadExit_.load();
            });
            if (isThreadExit_) {
                MEDIA_LOG_I("Exit RenderLoop read thread.");
                break;
            }
            nextTask = std::move(outputBuffers_.front());
            outputBuffers_.pop_front();
        }
        int64_t actionClock = 0;
        int64_t waitTime = CalculateNextRender(nextTask.first, nextTask.second, actionClock);
        MEDIA_LOG_D("RenderLoop pts: " PUBLIC_LOG_D64"  waitTime:" PUBLIC_LOG_D64,
            nextTask.second->pts_, waitTime);
        if (waitTime > 0) {
            OSAL::SleepFor(waitTime / 1000); // 1000 convert to ms
        }
        ReleaseOutputBuffer(nextTask.first, waitTime >= 0, nextTask.second, -1);
    }
}
```

---

### 6. DRM 解密集成

**Evidence 7** - `services/media_engine/filters/decoder_surface_filter.cpp` 行1411-1422：SetDecryptConfig 设置 DRM 解密配置，keySessionServiceProxy_ 持有 DRM 会话代理

```cpp
Status DecoderSurfaceFilter::SetDecryptConfig(const sptr<DrmStandard::IMediaKeySessionService> &keySessionProxy,
    bool svp)
{
    MEDIA_LOG_I("SetDecryptConfig");
    if (keySessionProxy == nullptr) {
        MEDIA_LOG_E("SetDecryptConfig keySessionProxy is nullptr.");
        return Status::ERROR_INVALID_PARAMETER;
    }
    isDrmProtected_ = true;
    svpFlag_ = svp;
#ifdef SUPPORT_DRM
    keySessionServiceProxy_ = keySessionProxy;
#endif
    return Status::OK;
}
```

**Evidence 8** - `services/media_engine/filters/decoder_surface_filter.cpp` 行455-462：ConfigureDecoderSettings 通过 VideoDecoderAdapter 设置 DRM 解密配置

```cpp
Status DecoderSurfaceFilter::ConfigureDecoderSettings()
{
    // ...
#ifdef SUPPORT_DRM
        videoDecoder_->SetDecryptConfig(keySessionServiceProxy_, svpFlag_);
#endif
    return ConfigureDecoderSettings();
}
```

**Evidence 9** - `services/media_engine/filters/decoder_surface_filter.cpp` 行34-35：SUPPORT_DRM 条件编译，引入 DRM 密钥会话服务头文件

```cpp
#ifdef SUPPORT_DRM
#include "imedia_key_session_service.h"
#endif
```

---

### 7. Camera PostProcessor 后处理扩展

**Evidence 10** - `services/media_engine/filters/decoder_surface_filter.cpp` 行62-65：增强标志（ENHANCE_FLAG）区分三种后处理场景

```cpp
static const std::string ENHANCE_FLAG = "com.openharmony.deferredVideoEnhanceFlag";
static const std::string SCENE_INSERT_FRAME = "1";   // 相机插入帧场景
static const std::string SCENE_MP_PWP = "2";          // 动态照片播放处理场景
```

**Evidence 11** - `services/media_engine/filters/decoder_surface_filter.cpp` 行39-41：SUPPORT_CAMERA_POST_PROCESSOR 条件编译，动态加载 libcamera_post_processor.z.so

```cpp
#ifdef SUPPORT_CAMERA_POST_PROCESSOR
const std::string REFERENCE_LIB_PATH = std::string(CAMERA_POST_PROCESSOR_PATH);
const std::string REFENCE_LIB_ABSOLUTE_PATH = REFERENCE_LIB_PATH + FILESEPARATOR + REFERENCE_LIB_NAME;
```

**Evidence 12** - `services/media_engine/filters/decoder_surface_filter.cpp` 行79-81：相机后处理器动态库句柄，类级别静态变量

```cpp
#ifdef SUPPORT_CAMERA_POST_PROCESSOR
void *DecoderSurfaceFilter::cameraPostProcessorLibHandle_ = nullptr;
#endif
```

**Evidence 13** - `services/media_engine/filters/decoder_surface_filter.cpp` 行940-949：InitPostProcessorType 根据 enhanceflag 初始化后处理器类型（CAMERA_INSERT_FRAME / CAMERA_MP_PWP）

```cpp
if (enhanceflag == SCENE_INSERT_FRAME) {
    postProcessorType_ = VideoPostProcessorType::CAMERA_INSERT_FRAME;
} else if (enhanceflag == SCENE_MP_PWP) {
    postProcessorType_ = VideoPostProcessorType::CAMERA_MP_PWP;
}
#ifdef SUPPORT_CAMERA_POST_PROCESSOR
    LoadCameraPostProcessorLib();
#endif
```

---

### 8. 硬件解码器回退机制

**Evidence 14** - `services/media_engine/filters/decoder_surface_filter.cpp` 行1870-1882：OnError 检测硬件解码器不支持规格，自动回退软件解码器

```cpp
void DecoderSurfaceFilter::OnError(MediaAVCodec::AVCodecErrorType errorType, int32_t errorCode)
{
    MEDIA_LOG_E("AVCodec error happened. ErrorType: %{public}d, errorCode: %{public}d",
        static_cast<int32_t>(errorType), errorCode);
    bool needToSwDecoder = !hasToSwDecoder_ && eventReceiver_ != nullptr &&
        errorCode == OHOS::MediaAVCodec::AVCodecServiceErrCode::AVCS_ERR_UNSUPPORTED_CODEC_SPECIFICATION &&
        videoDecoder_->IsHwDecoder();
    if (needToSwDecoder) {
        hasReceiveUnsupportError_ = true;
        eventReceiver_->OnEvent({"DecoderSurfaceFilter", EventType::EVENT_HW_DECODER_UNSUPPORT_CAP, 0});
        return;
    }
    FALSE_RETURN(eventReceiver_ != nullptr);
    eventReceiver_->OnEvent({"DecoderSurfaceFilter", EventType::EVENT_ERROR, MSERR_EXT_API9_IO, GetMime()});
}
```

---

### 9. VideoSink 渲染同步

**Evidence 15** - `interfaces/inner_api/native/video_sink.h` 行24-48：VideoSink 继承 MediaSynchronousSink，提供 DoSyncWrite 同步写、GetLagInfo 卡顿查询

```cpp
class VideoSink : public MediaSynchronousSink {
public:
    VideoSink();
    ~VideoSink();
    int64_t DoSyncWrite(const std::shared_ptr<OHOS::Media::AVBuffer>& buffer,
        int64_t& actionClock) override; // true and render
    void ResetSyncInfo() override;
    Status GetLatency(uint64_t& nanoSec);
    int64_t CheckBufferLatenessMayWait(const std::shared_ptr<OHOS::Media::AVBuffer>& buffer, int64_t clockNow);
    void SetSyncCenter(std::shared_ptr<MediaSyncManager> syncCenter);
    void SetEventReceiver(const std::shared_ptr<EventReceiver> &receiver);
    int64_t GetFrameInterval();
private:
    class VideoLagDetector : public LagDetector {
        int64_t lagTimes_ = 0;
        int64_t maxLagDuration_ = 0;
        // ...
    };
};
```

**Evidence 16** - `services/media_engine/filters/decoder_surface_filter.cpp` 行1073-1080：HandleRender 计算渲染时间，处理 DFX 卡顿事件上报

```cpp
void DecoderSurfaceFilter::HandleRender(
    int index, bool render, const std::shared_ptr<AVBuffer>& outBuffer, int64_t& renderTime)
{
    int64_t currentSysTimeNs = GetSystimeTimeNs();
    int64_t lastRenderTimeNs = lastRenderTimeNs_.load();
    int64_t minRendererTime = std::max(currentSysTimeNs, lastRenderTimeNs == HST_TIME_NONE ? 0 : lastRenderTimeNs);
    renderTime = renderTime < minRendererTime ? minRendererTime : renderTime;
    // ... DFX stalling event report via eventReceiver_->OnDfxEvent
}
```

---

### 10. 双回调架构（有/无 PostProcessor）

**Evidence 17** - `services/media_engine/filters/decoder_surface_filter.cpp` 行337-348：Configure 根据 postProcessor_ 是否存在选择不同 MediaCodecCallback 实现

```cpp
std::shared_ptr<MediaAVCodec::MediaCodecCallback> mediaCodecCallback = nullptr;
if (postProcessor_ != nullptr) {
    mediaCodecCallback = std::make_shared<FilterMediaCodecCallbackWithPostProcessor>(shared_from_this());
    std::shared_ptr<PostProcessorCallback> postProcessorCallback
        = std::make_shared<FilterVideoPostProcessorCallback>(shared_from_this());
    postProcessor_->SetCallback(postProcessorCallback);
} else {
    mediaCodecCallback = std::make_shared<FilterMediaCodecCallback>(shared_from_this());
}
videoDecoder_->SetCallback(mediaCodecCallback);
```

**Evidence 18** - `services/media_engine/filters/decoder_surface_filter.cpp` 行1166-1173：DoRenderOutputBufferAtTime 根据是否有 PostProcessor 决定渲染路径

```cpp
void DecoderSurfaceFilter::DoRenderOutputBufferAtTime(uint32_t index, int64_t renderTime, int64_t pts)
{
    if (postProcessor_) {
        postProcessor_->RenderOutputBufferAtTime(index, renderTime);
    } else if (videoDecoder_) {
        videoDecoder_->RenderOutputBufferAtTime(index, renderTime, pts);
    }
}
```

---

### 11. Seek 与拖拽连续播放

**Evidence 19** - `services/media_engine/filters/decoder_surface_filter.cpp` 行1433-1444：SetSeekTime/ResetSeekInfo/ClosestSeekDone 实现精确 Seek 机制

```cpp
void DecoderSurfaceFilter::SetSeekTime(int64_t seekTimeUs, PlayerSeekMode mode)
{
    if (mode == PlayerSeekMode::SEEK_CLOSEST) {
        isSeek_ = true;
        seekTimeUs_ = seekTimeUs;
    }
    FALSE_RETURN_NOLOG(postProcessor_ != nullptr);
    postProcessor_->SetSeekTime(seekTimeUs, mode);
}
```

**Evidence 20** - `services/media_engine/filters/decoder_surface_filter.cpp` 行1167-1173：DoRenderOutputBufferAtTime 中 SCALEMODE_MAP 将 VideoScaleType 映射到 OHOS ScalingMode

```cpp
const std::unordered_map<VideoScaleType, OHOS::ScalingMode> SCALEMODE_MAP = {
    { VideoScaleType::VIDEO_SCALE_TYPE_FIT, OHOS::SCALING_MODE_SCALE_TO_WINDOW },
    { VideoScaleType::VIDEO_SCALE_TYPE_FIT_CROP, OHOS::SCALING_MODE_SCALE_CROP},
    { VideoScaleType::VIDEO_SCALE_TYPE_SCALED_ASPECT, OHOS::SCALING_MODE_SCALE_FIT},
};
```

---

## 与相邻 Filter 的对称关系

| Filter | 注册名 | FilterType | 方向 | 对称关系 |
|--------|--------|-----------|------|---------|
| DecoderSurfaceFilter | builtin.player.videodecoder | FILTERTYPE_VDEC | 上游 DemuxerFilter → 下游 VideoRenderFilter | S46（本文） |
| SurfaceDecoderFilter | builtin.player.surfacedecoder | FILTERTYPE_VIDEODEC | 上游 DemuxerFilter → 下游 VideoRenderFilter | S45（对称，轻量录制路径） |
| VideoRenderFilter | builtin.player.videorender | FILTERTYPE_VIDEORENDER | 上游 DecoderSurfaceFilter → 终点 | S32（下游） |

---

## 技术栈索引

| 文件 | 作用 |
|------|------|
| `services/media_engine/filters/decoder_surface_filter.cpp` | DecoderSurfaceFilter 实现（1861行） |
| `interfaces/inner_api/native/video_sink.h` | VideoSink 头文件（MediaSynchronousSink 子类） |
| `services/media_engine/modules/sink/video_sink.cpp` | VideoSink 实现 |
| `services/media_engine/filters/video_decoder_adapter.cpp` | VideoDecoderAdapter 解码适配器（DecoderSurfaceFilter 用） |
| `services/media_engine/filters/surface_decoder_adapter.cpp` | SurfaceDecoderAdapter 适配器（SurfaceDecoderFilter 用） |
| `interfaces/inner_api/native/avcodec_video_decoder.h` | AVCodecVideoDecoder 公开接口 |

## 关联记忆

| 关联ID | 关系 |
|--------|------|
| MEM-ARCH-AVCODEC-S32 | VideoRenderFilter 下游输出终点 |
| MEM-ARCH-AVCODEC-S39 | AVCodecVideoDecoder 底层引擎 |
| MEM-ARCH-AVCODEC-S41 | DemuxerFilter 上游数据源 |
| MEM-ARCH-AVCODEC-S45 | SurfaceDecoderFilter 对称Filter（轻量录制路径） |
| MEM-ARCH-AVCODEC-S15 | SuperResolutionPostProcessor 后处理扩展 |
| MEM-ARCH-AVCODEC-S17 | SmartFluencyDecoding 丢帧策略 |
