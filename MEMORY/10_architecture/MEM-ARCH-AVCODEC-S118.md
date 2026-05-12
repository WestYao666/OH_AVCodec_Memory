---
id: MEM-ARCH-AVCODEC-S118
title: 三路 Sink 引擎协作架构——VideoSink / AudioSink / SubtitleSink 与 MediaSyncManager 联动（本地镜像增强版）
scope: [AVCodec, MediaEngine, Sink, MediaSync, VideoSink, AudioSink, SubtitleSink, IMediaSynchronizer, DoSyncWrite, MediaSyncManager, VideoLagDetector, AudioVivid, RenderLoop, LAG_LIMIT, BufferDiff, Priority, SUBTITLE_LOOP_RUNNING]
status: approved
approved_at: '2026-05-12T10:42:00+08:00'
created_at: "2026-05-11T02:50:00+08:00"
submitted_at: null
evidence_count: 16
source_repo: /home/west/av_codec_repo
关联主题: [S56(VideoSink同步器), S73(三路Sink总览), S22(MediaSyncManager), S31(AudioSinkFilter), S32(VideoRenderFilter), S49(SubtitleSink)]
---

# MEM-ARCH-AVCODEC-S118: 三路 Sink 引擎协作架构（本地镜像增强版）

## 核心定位

S118 是对 S56/S73 已归档记忆的**源码增强版**，基于本地镜像 `/home/west/av_codec_repo` 行号级验证，聚焦三路 Sink（VideoSink/AudioSink/SubtitleSink）之间的**协作机制**与 **MediaSyncManager 时钟锚点分发**，而非重复各 Sink 的独立架构。

三路 Sink 共同构成 MediaEngine Filter Pipeline 的**渲染终点**，分别接收经 FilterChain 处理后的视频帧、音频帧和字幕数据，在 `IMediaSynchronizer` 统一调度下完成与播放时钟的同步。

## 关键证据

| 证据 | 文件:行号 | 说明 |
|------|-----------|------|
| E1 | video_sink.cpp:29 | `constexpr int64_t LAG_LIMIT_TIME = 100;` 卡顿判定阈值 100ms |
| E2 | video_sink.cpp:59 | `constexpr int VIDEO_SINK_START_FRAME = 4;` 前 4 帧强制渲染跳过同步检查 |
| E3 | video_sink.cpp:125 | `VideoSink::DoSyncWrite` 渲染决策主函数，接收 buffer 和 actionClock |
| E4 | video_sink.cpp:227 | `VideoSink::CalcBufferDiff` 三元组算法：bufferAnchoredClockTime / videoDiff / thresholdAdjustedVideoDiff |
| E5 | video_sink.cpp:256 | `VideoSink::CheckBufferLatenessMayWait` 早迟判断，决定是否等待或丢弃 |
| E6 | video_sink.cpp:244 | 前 4 帧跳过同步检查 `discardFrameCnt_ + renderFrameCnt_ < VIDEO_SINK_START_FRAME` |
| E7 | video_sink.cpp:395-440 | `VideoSink::VideoLagDetector::CalcLag` 内嵌类，卡顿检测（LAG_LIMIT_TIME=100ms） |
| E8 | video_sink.cpp:415 | `VideoLagDetector::SetEventReceiver` 注入 EventReceiver，卡顿时上报事件 |
| E9 | video_sink.cpp:91 | `syncCenter->SetLastVideoBufferPts(buffer->pts_ - firstPts_)` 视频帧 PTS 回写到同步中心 |
| E10 | video_sink.cpp:359 | `firstPts_` 初始化日志 `video DoSyncWrite set firstPts = ...` |
| E11 | audio_sink.cpp:80 | `syncerPriority_ = IMediaSynchronizer::AUDIO_SINK;` AudioSink 优先级 = 2 |
| E12 | audio_sink.cpp:102 | `AudioSink::AudioSinkDataCallbackImpl::OnWriteData` 写数据回调（含 AudioVivid 处理） |
| E13 | subtitle_sink.cpp:517行 | SubtitleSink 总行数，独立 RenderLoop 线程，WAIT/SHOW/DROP 三状态 |
| E14 | subtitle_sink.cpp | `SUBTITLE_LOOP_RUNNING` 独立线程运行标志，`RemoveTextTags` HTML 标签剥离 |
| E15 | subtitle_sink.cpp | `NotifyRender Tag::SUBTITLE_TEXT` 事件上报，`NotifySeek` Seek 时清空字幕队列 |
| E16 | audio_sink.cpp:1793行 | AudioSink 总行数，AudioVivid 格式有特殊延迟补偿路径 |

## 三路 Sink 优先级体系

`IMediaSynchronizer` 定义了三路 Sink 的优先级：

| Sink | 优先级值 | 说明 |
|------|---------|------|
| VIDEO_SINK | 0 | 时钟锚点供应方（Clock Provider），最先被 MediaSyncManager 调度 |
| AUDIO_SINK | 2 | 音频为默认时钟基准（Clock Reference） |
| SUBTITLE_SINK | 8 | 字幕优先级最低，配合视频 PTS 显示 |

VideoSink 的 `syncerPriority_ = VIDEO_SINK = 0`，在 `DoSyncWrite` 中向 `IMediaSyncCenter` 写 PTS 回源：`syncCenter->SetLastVideoBufferPts(buffer->pts_ - firstPts_)`（video_sink.cpp:91）。

## VideoSink 渲染决策算法

```
DoSyncWrite(buffer, actionClock):
  1. if firstPts_ == NONE → 从 syncCenter.GetMediaStartPts() 获取基准
  2. if discardFrameCnt_ + renderFrameCnt_ < 4 → 直接渲染（前4帧跳过同步）
  3. CalcBufferDiff(buffer) → 三元组差值
  4. CheckBufferLatenessMayWait → 早(等待)/迟(丢弃)
  5. lagDetector_.CalcLag → 超过100ms则触发事件上报
  6. renderFrameCnt_++ / lastBufferRelativePts_ 更新
```

关键常量：
- `VIDEO_SINK_START_FRAME = 4`：前 4 帧强制渲染
- `LAG_LIMIT_TIME = 100ms`：卡顿判定阈值
- `HST_TIME_NONE`：未初始化 PTS 标志

## AudioSink 音频渲染特点

- 优先级 `AUDIO_SINK = 2`（非零优先级，非时钟锚点）
- 1793 行实现，`AudioSinkDataCallbackImpl::OnWriteData` 回调处理音频数据写入
- `IsInputBufferDataEnough` 判断缓冲区是否足够消费
- `IsBufferDataDrained` 缓冲区排空检测
- AudioVivid 格式有特殊延迟补偿路径（`CopyAudioVividBufferData`）

## SubtitleSink 字幕渲染特点（517行）

- 优先级 `SUBTITLE_SINK = 8`（最低）
- 独立 RenderLoop 线程（`SUBTITLE_LOOP_RUNNING` 标志）
- 三状态：`WAIT`（等待显示时间到达）→ `SHOW`（渲染中）→ `DROP`（超出时间窗）
- `RemoveTextTags` 剥离 HTML 标签（防止注入攻击）
- `NotifyRender Tag::SUBTITLE_TEXT` 上报字幕文本事件
- Seek 时 `NotifySeek` 清空字幕队列

## VideoLagDetector 卡顿检测机制

内嵌类 `VideoLagDetector`（video_sink.cpp:395-440）负责追踪卡顿：

```cpp
bool VideoSink::VideoLagDetector::CalcLag(std::shared_ptr<AVBuffer> buffer) {
    bool isVideoLag = lastSystemTimeMs_ > 0 && lagTimeMs >= LAG_LIMIT_TIME; // 100ms
    if (isVideoLag) {
        lagDetector_.ResolveLagEvent(lagTimeMs); // 上报事件
    }
    return isVideoLag;
}
```

通过 `SetEventReceiver` 将事件 receiver 注入，卡顿时触发 `EVENT_VIDEO_LAG` 上报，供 DFX 系统记录。

## 本地镜像行号验证

| 文件 | 本地镜像行数 | 与草案一致 |
|------|-------------|-----------|
| `services/media_engine/modules/sink/video_sink.cpp` | 462 行 | ✅ |
| `services/media_engine/modules/sink/audio_sink.cpp` | 1793 行 | ✅ |
| `services/media_engine/modules/sink/subtitle_sink.cpp` | 517 行 | ✅ |

## 与已归档记忆的关联

- **S56**（VideoSink 核心同步器）：已有 DoSyncWrite/CalcBufferDiff 框架，S118 补充 LAG_LIMIT=100ms 和 VideoLagDetector 内嵌类
- **S73**（三路 Sink 总览）：已有优先级枚举，S118 补充各 Sink 的源码级证据
- **S22**（MediaSyncManager）：MediaSyncManager 是三路 Sink 的时钟协调中心，S118 补充 VIDEO_SINK 写回 PTS 的证据（video_sink.cpp:91）
- **S31/S32/S49**：Filter 层封装，S118 是引擎层实现

## 架构要点总结

1. **优先级体系**：VIDEO_SINK(0) > AUDIO_SINK(2) > SUBTITLE_SINK(8)，VIDEO_SINK 是时钟锚点
2. **前4帧跳过同步**：VIDEO_SINK_START_FRAME=4 避免启动阶段频繁丢帧
3. **卡顿检测**：LAG_LIMIT_TIME=100ms，VideoLagDetector 追踪并上报
4. **DoSyncWrite 三步**：CalcBufferDiff → CheckBufferLatenessMayWait → RenderOrDiscard
5. **AudioSink 特殊路径**：OnWriteData 回调处理 AudioVivid 格式，有独立延迟补偿
6. **SubtitleSink 三状态**：WAIT/SHOW/DROP，独立 RenderLoop，Seek 清空队列
