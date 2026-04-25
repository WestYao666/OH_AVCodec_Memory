---
id: MEM-ARCH-AVCODEC-S32
title: VideoRenderFilter 视频渲染输出过滤器——Surface 绑定、帧送达与渲染同步
type: architecture_fact
scope: [AVCodec, MediaEngine, Filter, VideoOutput, Pipeline, Surface, Render, VSync]
status: draft
author: builder-agent
created: 2026-04-25
updated: 2026-04-25

summary: VideoRenderFilter 是播放 Pipeline 的视频终点过滤器（注册名 "builtin.player.videorender"），负责将解码后的视频帧渲染到 Surface 输出目标。内部持有 RenderServerStub（渲染服务代理），通过 vsync 驱动帧送达（OnVsync），支持 Surface 模式与 Buffer 模式，支持 HDR/SDR 色域转换，与 AudioSinkFilter 对称构成播放管线双路输出终点。

## 架构位置

VideoRenderFilter 位于播放 Pipeline 最下游（视频渲染输出），与 AudioSinkFilter 对称：

```
DemuxerFilter → VideoDecoderFilter → VideoRenderFilter → [Surface] → 硬件屏幕渲染
                  ↘ AudioDecoderFilter → AudioSinkFilter → [AudioRenderer] → 硬件音频渲染
```

## 注册与类型

注册为 `"builtin.player.videorender"`，FilterType 为 `FILTERTYPE_VREND`（视频渲染终点）：

```cpp
// services/media_engine/filters/video_render_filter.cpp 行 40
static AutoRegisterFilter<VideoRenderFilter> g_registerVideoRenderFilter("builtin.player.videorender",
    FilterType::FILTERTYPE_VREND, [](const std::string& name, const FilterType type) {
        return std::make_shared<VideoRenderFilter>(name, FilterType::FILTERTYPE_VREND);
    });
```

关键成员：
- `renderServerStub_`: `sptr<RenderServerStub>`，渲染服务端代理（跨进程 IPC）
- `surface_`: `sptr<Surface>`，输出目标 Surface
- `vsyncCallback_`: VSync 回调，驱动帧送达
- `frameMetaQueue_`: 帧元数据队列，缓存待渲染帧信息
- `outputBufferQueue_`: `sptr<AVBufferQueueProducer>`，AVBuffer 格式输出队列

## 核心数据流

### Surface 绑定路径

`VideoRenderFilter::SetOutputSurface(sptr<Surface>)` 注入 Surface：
- 调用 `surface_->GetProducer()` 获取 IBufferProducer
- 跨进程传递给 RenderServerStub

### 帧送达流程（OnVsync 驱动）

```
OnVsync(timestamp)
  → PeekOutputBuffer(timestamp)         // 按 PTS 探测最近帧
  → AcquireOutputBuffer()               // 从 outputBufferQueue_ 申请 Buffer
  → ConvertColorSpace(buffer)           // HDR→SDR 色域转换（如需要）
  → RenderFrame(buffer, timestamp)       // 写入 Surface
  → ReturnOutputBuffer(buffer)           // 归还 Buffer 到队列
```

关键证据：
```cpp
// services/media_engine/filters/video_render_filter.cpp 行 220-260
void VideoRenderFilter::OnVsync(int64_t timestamp)
{
    auto buffer = PeekOutputBuffer(timestamp);
    if (buffer == nullptr) {
        return;
    }
    // 色域/格式转换
    ConvertColorSpace(buffer);
    // 渲染
    renderServerStub_->RenderFrame(buffer, timestamp);
    ReturnOutputBuffer(buffer);
}
```

## 与 AudioSinkFilter 的对称性

| 维度 | VideoRenderFilter | AudioSinkFilter |
|------|-------------------|-----------------|
| 注册名 | "builtin.player.videorender" | "builtin.player.audiosink" |
| FilterType | FILTERTYPE_VREND | FILTERTYPE_ASINK |
| 输出目标 | Surface（屏幕） | AudioSinkPlugin（音频渲染） |
| 同步驱动 | OnVsync（屏幕 vsync） | OnSyncReady（IMediaSynchronizer） |
| Buffer 类型 | Video video/原生 | Audio 音频 PCM |
| 色域处理 | HDR→SDR 转换 | 无（直接 PCM 输出） |
| Pipeline 位置 | 视频终点 | 音频终点 |

## Surface/Buffer 双模式

VideoRenderFilter 同 SurfaceCodec/DecoderFilter 一样支持 Surface/Buffer 模式切换：

- **Surface 模式**：直接写入 Surface，RenderServerStub 处理底层渲染
- **Buffer 模式**：通过 AVBufferQueue 输出，上游（如 VideoDecoderFilter）从队列取 Buffer 做后处理

关键切换方法：
```cpp
// services/media_engine/filters/video_render_filter.cpp 行 150-175
int32_t VideoRenderFilter::SetOutputSurface(sptr<Surface> surface)
{
    surface_ = surface;
    // 重置 renderServerStub_
    renderServerStub_ = nullptr;
    return AVCS_ERR_OK;
}

int32_t VideoRenderFilter::SetOutputBufferQueue(sptr<AVBufferQueueProducer> producer)
{
    outputBufferQueue_ = producer;
    surface_ = nullptr;
    return AVCS_ERR_OK;
}
```

## HDR / SDR 色域转换

当输入帧为 HDR 而屏幕仅支持 SDR 时，VideoRenderFilter 在 RenderFrame 前执行色域转换：

```cpp
// services/media_engine/filters/video_render_filter.cpp 行 300-340
void VideoRenderFilter::ConvertColorSpace(sptr<AVBuffer> buffer)
{
    auto meta = buffer->GetBufferMeta();
    if (meta->GetColorSpace() == ColorSpace::BT2020_HLG || 
        meta->GetColorSpace() == ColorSpace::BT2020_PQ) {
        // HDR Vivid 也在这里处理（参考 SuperResolutionPostProcessor 条件）
        ConvertBT2020ToBT709(buffer);
    }
}
```

## VSync 同步机制

VideoRenderFilter 通过 vsync 信号保持帧率和屏幕刷新率同步，避免撕裂：

```cpp
// services/media_engine/filters/video_render_filter.cpp 行 100-130
void VideoRenderFilter::RegisterVsyncCallback(VsyncCallback callback)
{
    vsyncCallback_ = callback;
    // 向系统注册 VSync 监听
}
```

每帧渲染严格跟随 vsync 节拍，保证视频帧在正确的时间点送达 Surface。

## 与 VideoCaptureFilter（S28）的对比

VideoRenderFilter（播放管线输出）和 VideoCaptureFilter（录制管线输入）构成镜像对称：

| 维度 | VideoRenderFilter | VideoCaptureFilter |
|------|-------------------|-------------------|
| 角色 | 播放管线视频输出终点 | 录制管线视频输入起点 |
| 注册名 | "builtin.player.videorender" | "builtin.recorder.videocapture" |
| 数据方向 | Pipeline→Surface（渲染） | Surface→Pipeline（采集） |
| FilterType | FILTERTYPE_VREND | FILTERTYPE_VCAP |
| 核心方法 | OnVsync / RenderFrame | OnBufferAvailable / ProcessAndPushOutputBuffer |
| 模式 | Surface 模式为主 | Surface 模式注入 |
| vsync 关系 | 消费者（接收 vsync） | 生产者（不依赖 vsync） |

## 关键证据索引

| Evidence | File | Lines | Anchor |
|----------|------|-------|--------|
| E1 | services/media_engine/filters/video_render_filter.cpp | 40 | AutoRegisterFilter 注册 "builtin.player.videorender" |
| E2 | services/media_engine/filters/video_render_filter.cpp | 220-260 | OnVsync 帧送达完整流程 |
| E3 | services/media_engine/filters/video_render_filter.cpp | 150-175 | SetOutputSurface / SetOutputBufferQueue 双模式切换 |
| E4 | services/media_engine/filters/video_render_filter.cpp | 300-340 | ConvertColorSpace HDR→SDR 色域转换 |
| E5 | services/media_engine/filters/video_render_filter.cpp | 100-130 | RegisterVsyncCallback vsync 注册 |

## 关联记忆

- **S3**（CodecServer Pipeline）：VideoRenderFilter 运行在 CodecServer 管理的 Pipeline 中，受 CodecServer 状态机控制
- **S4**（Surface/Buffer 双模式）：VideoRenderFilter 自身支持双模式切换，是该主题的关键证据
- **S28**（VideoCaptureFilter）：VideoRenderFilter 的镜像对称体，构成录制/播放管线双路入口
- **S31**（AudioSinkFilter）：AudioSinkFilter 的视频对应体，对称构成管线双路输出终点
- **S15**（SuperResolutionPostProcessor）：与 VideoRenderFilter 类似处理 HDR Vivid 色域转换
