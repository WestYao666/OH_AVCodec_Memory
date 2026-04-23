---
id: MEM-ARCH-AVCODEC-S16
type: architecture
topic: SurfaceCodec 与 Surface 的绑定机制
scope: AVCodec,SurfaceMode,SurfaceBinding,MediaEngine,Pipeline
status: draft
author: builder-agent
created_at: 2026-04-24T05:24:00+08:00
updated_at: 2026-04-24T05:24:00+08:00
evidence_sources:
  - local_repo: /home/west/av_codec_repo/services/media_engine/filters/decoder_surface_filter.cpp
  - local_repo: /home/west/av_codec_repo/services/media_engine/filters/surface_decoder_adapter.cpp
  - local_repo: /home/west/av_codec_repo/services/media_engine/filters/surface_decoder_adapter.h
  - local_repo: /home/west/av_codec_repo/services/services/codec/server/video/codec_server.cpp
  - https://gitcode.com/openharmony/multimedia_av_codec
---
# SurfaceCodec 与 Surface 的绑定机制

## 概述
SurfaceCodec（Surface 模式下的编解码器）通过 `SetOutputSurface` 接口与渲染 Surface 绑定，输出帧直接传递到 GPU 进行渲染，跳过应用层的 Buffer 拷贝。绑定路径为 `DecoderSurfaceFilter.SetVideoSurface()` → `CodecServer.SetOutputSurface()` → `CodecBase.SetOutputSurface()`，其中 PostProcessing 链可插入滤镜 Surface 转发逻辑。Surface 模式与 Buffer 模式互斥，绑定前须处 CONFIGURED 状态。

## 关键发现
- **Surface 模式与 Buffer 模式互斥**：CodecServer 层通过 `isSurfaceMode_` 标志位区分，Buffer 模式下调用 `SetOutputSurface` 会返回 `AVCS_ERR_INVALID_OPERATION`
- **PostProcessing 链介入 Surface 转发**：当存在后处理（如超分辨率）时，`decoderOutputSurface_` 与 `videoSurface_` 分属不同 Surface 对象，滤镜通过 `postProcessor_->SetOutputSurface(videoSurface_)` 和 `videoDecoder_->SetOutputSurface(decoderOutputSurface_)` 分别设置
- **SurfaceCodec 包装类分工**：MediaEngine 层使用 `SurfaceDecoderAdapter`（继承 `enable_shared_from_this`）包装 `AVCodecVideoDecoder`，对上是 Filter 接口，对下是标准 Codec API
- **Surface 绑定须在 Configure 后**：CodecServer 要求 `SetOutputSurface` 调用时状态为 CONFIGURED/RUNNING/FLUSHED/END_OF_STREAM，且 `isModeConfirmed_` 必须为 true
- **RenderSurface 三队列支撑 ZeroCopy**：解码输出帧经由 RenderSurface 的 `renderAvailQue`/`requestSurfaceBufferQue`/`codecAvailQue` 三队列流转，保证 GPU 渲染路径零拷贝

## 代码证据

### 1. SurfaceDecoderAdapter：Surface 模式 Codec 包装类

> 源码：`services/media_engine/filters/surface_decoder_adapter.h`

```cpp
class SurfaceDecoderAdapter : public std::enable_shared_from_this<SurfaceDecoderAdapter> {
public:
    sptr<OHOS::Media::AVBufferQueueProducer> GetInputBufferQueue();
    Status SetDecoderAdapterCallback(const std::shared_ptr<DecoderAdapterCallback> &decoderAdapterCallback);
    Status SetOutputSurface(sptr<Surface> surface);    // 绑定 Surface
    sptr<Surface> GetInputSurface();                   // 获取输入 Surface（编码场景）
    // ...
private:
    std::shared_ptr<MediaAVCodec::AVCodecVideoDecoder> codecServer_;  // 底层Codec服务
    std::shared_ptr<Media::AVBufferQueue> inputBufferQueue_;
    // ...
};
```

> 源码：`services/media_engine/filters/surface_decoder_adapter.cpp`

```cpp
Status SurfaceDecoderAdapter::SetOutputSurface(sptr<Surface> surface)
{
    MEDIA_LOG_I("SetOutputSurface");
    std::shared_lock<std::shared_mutex> lock(codecServerMutex_);
    FALSE_RETURN_RTV_MSG(surface != nullptr, Status::ERROR_INVALID_PARAMETER, "surface is nullptr");
    int32_t ret = codecServer_->SetOutputSurface(surface);  // 透传到CodecServer
    if (ret == AVCS_ERR_OK) {
        MEDIA_LOG_I("SetOutputSurface success");
    } else {
        MEDIA_LOG_I("SetOutputSurface fail");
    }
    return ret == 0 ? Status::OK : Status::ERROR_UNKNOWN;
}
```

### 2. DecoderSurfaceFilter：Pipeline 中的 Surface 绑定入口

> 源码：`services/media_engine/filters/decoder_surface_filter.cpp`

```cpp
// 关键成员：
// videoDecoder_     — VideoDecoderAdapter 实例
// videoSurface_     — 应用传入的渲染 Surface（外层）
// decoderOutputSurface_ — 实际绑定到解码器的 Surface（后处理场景下可能不同于 videoSurface_）
// postProcessor_    — 后处理器（可选，如超分辨率滤镜）

Status DecoderSurfaceFilter::SetVideoSurface(sptr<Surface> videoSurface)
{
    if (!videoSurface && !isVideoMuted_.load()) {
        videoDecoder_->SetOutputSurface(nullptr);  // 清除 Surface 绑定
        return Status::OK;
    }
    videoSurface_ = videoSurface;

    // 设置缩放模式
    OHOS::ScalingMode scalingMode = ConvertMediaScaleType(...);
    (void)videoSurface_->SetScalingMode(scalingMode);

    if (postProcessor_ != nullptr) {
        // 存在后处理时：后处理接收 videoSurface，解码器接收后处理的输入 Surface
        (void)postProcessor_->SetOutputSurface(videoSurface_);           // 后处理输出 Surface
        decoderOutputSurface_ = videoSurface;                            // 默认同 videoSurface
    } else {
        decoderOutputSurface_ = videoSurface;                            // 无后处理时直接绑定
    }

    if (videoDecoder_ != nullptr) {
        int32_t res = videoDecoder_->SetOutputSurface(decoderOutputSurface_);  // 绑定到解码器
        if (res != AVCS_ERR_OK) {
            MEDIA_LOG_E("videoDecoder_ SetOutputSurface error, result is " PUBLIC_LOG_D32, res);
            return Status::ERROR_UNKNOWN;
        }
    }
    MEDIA_LOG_I("SetVideoSurface success");
    return Status::OK;
}
```

**双 Surface 绑定场景（PostProcessing 激活）**：
```cpp
// 1702-1704：后处理场景下的动态 Surface 切换
decoderOutputSurface_ = postProcessor_->GetInputSurface();   // 从后处理获取输入 Surface
videoDecoder_->SetOutputSurface(decoderOutputSurface_);        // 绑定到解码器
postProcessor_->SetOutputSurface(videoSurface_);              // 后处理输出绑定到渲染 Surface
```

### 3. CodecServer::SetOutputSurface：服务层状态校验与路由

> 源码：`services/services/codec/server/video/codec_server.cpp`

```cpp
int32_t CodecServer::SetOutputSurface(sptr<Surface> surface)
{
    std::lock_guard<std::shared_mutex> lock(mutex_);

    // 1. Buffer 模式下禁止调用
    bool isBufferMode = isModeConfirmed_ && !isSurfaceMode_;
    CHECK_AND_RETURN_RET_LOG_WITH_TAG(!isBufferMode, AVCS_ERR_INVALID_OPERATION,
        "In buffer mode");

    // 2. 状态校验：须在 CONFIGURED/RUNNING/FLUSHED/END_OF_STREAM
    bool isValidState = isModeConfirmed_
        ? isSurfaceMode_ && (status_ == CONFIGURED || status_ == RUNNING ||
                              status_ == FLUSHED || status_ == END_OF_STREAM)
        : status_ == CONFIGURED;
    CHECK_AND_RETURN_RET_LOG_WITH_TAG(isValidState, AVCS_ERR_INVALID_STATE,
        "In invalid state, %{public}s", GetStatusDescription(status_).data());

    CHECK_AND_RETURN_RET_LOG_WITH_TAG(codecBase_ != nullptr, AVCS_ERR_NO_MEMORY, "Codecbase is nullptr");
    CHECK_AND_RETURN_RET_LOG_WITH_TAG(surface != nullptr, AVCS_ERR_NO_MEMORY, "Surface is nullptr");

    // 3. PostProcessing 路由：优先走后处理链
    int32_t ret = AVCS_ERR_OK;
    if (postProcessing_) {
        ret = SetOutputSurfaceForPostProcessing(surface);   // 后处理接管
    } else {
        ret = codecBase_->SetOutputSurface(surface);        // 直接绑定到底层Codec
    }

    surfaceId_ = surface->GetUniqueId();                    // 记录 Surface ID
    isSurfaceMode_ = (ret == AVCS_ERR_OK);                  // 标记已切换 Surface 模式
    return ret;
}
```

### 4. Surface 模式与 Buffer 模式的互斥机制

CodecServer 层通过 `isSurfaceMode_` 和 `isModeConfirmed_` 两个标志位管理模式切换：

| 标志 | 含义 | 说明 |
|------|------|------|
| `isModeConfirmed_` | 是否已确认工作模式 | Configure 后置为 true |
| `isSurfaceMode_` | 当前是否为 Surface 模式 | SetOutputSurface 成功返回后置为 true |
| Buffer 模式 | `isModeConfirmed_=true && isSurfaceMode_=false` | SetOutputBufferQueue 成功后进入 |

两种模式共用同一组生命周期方法（Start/Stop/Flush/Release），但数据路径完全不同。

## 关联
- 关联记忆：MEM-ARCH-AVCODEC-S4（Surface Mode 与 Buffer Mode 双模式切换机制）
- 关联记忆：MEM-ARCH-AVCODEC-S7/S9（SurfaceBuffer 与 RenderSurface 内存管理，ZeroCopy 路径）
- 关联记忆：MEM-ARCH-AVCODEC-S15（SuperResolutionPostProcessor 介入 Surface 绑定的场景）
- 关联记忆：MEM-ARCH-AVCODEC-006（Surface 模式 API：SetOutputSurface/GetInputSurface）
- 适用场景：视频播放（Player）、转码（Transcoder）、视频录制（VideoCapture）Surface 输出路径
