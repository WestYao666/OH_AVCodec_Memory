---
id: MEM-ARCH-AVCODEC-S56
title: VideoSink 视频渲染同步器——DoSyncWrite 渲染决策与 VideoLagDetector 卡顿追踪
scope: [AVCodec, MediaEngine, Sink, VideoSync, VideoRender, Sync, DoSyncWrite, VideoLagDetector, LagDetector, MediaSynchronousSink, IMediaSynchronizer, IMediaSyncCenter, CheckBufferLatenessMayWait, CalcBufferDiff, LagReport]
status: approved
approved_at: "2026-05-06"
author: builder-agent
created_at: "2026-04-26T20:25:00+08:00"
type: architecture_fact
confidence: high
summary: >
  VideoSink 是播放管线视频输出的同步与渲染决策单元，继承 MediaSynchronousSink（与 AudioSinkFilter/VideoRenderFilter 共享基类），
  运行 DoSyncWrite 决策逻辑：CheckBufferLatenessMayWait 计算 diff 判 early/late，CalcBufferDiff 综合锚点差/视频帧差/初始等待期三元组，
  决定 waitTime（>0 等待）或 -1（丢弃）。前 VIDEO_SINK_START_FRAME=4 帧强制渲染。
  内嵌 VideoLagDetector 追踪 lagTimes/maxLagDuration/avgLagDuration，通过 ResolveLagEvent 上报 DFX 事件。
  与 IMediaSyncCenter 交互（SetSyncCenter/UpdateTimeAnchor/GetAnchoredClockTime），
  通过 IMediaSynchronizer::VIDEO_SINK=0 优先级成为播放管线的时钟锚点供应方（优先于 AUDIO_SINK=2）。
evidence_sources:
  - local_repo: /home/west/av_codec_repo
  - services/media_engine/modules/sink/video_sink.cpp           # 462行，DoSyncWrite/CheckBufferLatenessMayWait/CalcBufferDiff
  - services/media_engine/modules/sink/video_sink.h              # 114行，VideoSink类定义，VideoLagDetector内嵌类
  - services/media_engine/modules/sink/media_synchronous_sink.h  # MediaSynchronousSink基类，IMediaSynchronizer优先级
  - services/media_engine/modules/sink/media_sync_manager.cpp    # 491行，MediaSyncManager实现
  - interfaces/inner_api/native/video_sink.h                   # VideoSink对外类定义
  - interfaces/inner_api/native/i_media_sync_center.h          # IMediaSyncCenter/IMediaSynchronizer接口
related_scenes: [新需求开发, 问题定位, 视频卡顿, 音视频同步, 帧率抖动, 视频早到/晚到处理]
why_it_matters: >
  VideoSink 是播放管线视频渲染的最后一环，负责"什么时候渲染/丢弃哪一帧"的决策。
  当视频出现卡顿、花屏（丢帧时机错误）、音画不同步时，需定位到此层。
  VideoLagDetector 的 lag 上报是 DFX 的重要输入。
关联主题: [S31(AudioSinkFilter), S32(VideoRenderFilter), S22(MediaSyncManager)]
---

# MEM-ARCH-AVCODEC-S56: VideoSink 视频渲染同步器

## Metadata

| 字段 | 值 |
|------|-----|
| **ID** | MEM-ARCH-AVCODEC-S56 |
| **标题** | VideoSink 视频渲染同步器——DoSyncWrite 渲染决策与 VideoLagDetector 卡顿追踪 |
| **Scope** | AVCodec, MediaEngine, Sink, VideoSync, VideoRender, Sync, DoSyncWrite, VideoLagDetector, LagDetector, MediaSynchronousSink, IMediaSynchronizer, CheckBufferLatenessMayWait, CalcBufferDiff |
| **Status** | draft |
| **Created** | 2026-04-26T20:25:00+08:00 |
| **关联主题** | S31(AudioSinkFilter), S32(VideoRenderFilter), S22(MediaSyncManager) |

---

## 架构位置

VideoSink 位于播放管线下游，是视频渲染决策单元：

```
DemuxerFilter → VideoDecoderFilter → VideoRenderFilter → VideoSink → [Surface] → 屏幕渲染
                                        内部持有VideoSink
```

在 HiStreamer 分层中：
- **MediaSynchronousSink**（基类）：提供与 MediaSyncManager 的同步原语
- **VideoSink**（子类）：实现 DoSyncWrite 渲染决策逻辑与 VideoLagDetector 卡顿追踪
- **VideoRenderFilter**：持有 VideoSink 实例，通过 SetSyncCenter 注入 MediaSyncManager

---

## 继承体系

```
IMediaSynchronizer (interface, priority = 0 for VIDEO_SINK)
    ↑
MediaSynchronousSink (基类，共享Sync原语)
    ↑
VideoSink (子类，实现DoSyncWrite + VideoLagDetector)
```

- `MediaSynchronousSink` 定义：`DoSyncWrite` = `=0`（纯虚），`ResetSyncInfo` = `=0`
- `VideoSink` 实现 `DoSyncWrite` 和 `ResetSyncInfo`
- 同步中心通过 `SetSyncCenter(shared_ptr<MediaSyncManager>)` 注入（`video_sink.cpp:373`）

---

## 关键常量

| 常量 | 值 | 说明 |
|------|---|------|
| `LAG_LIMIT_TIME` | 100 | 卡顿阈值（ms） |
| `DROP_FRAME_CONTINUOUSLY_MAX_CNT` | 2 | 连续丢帧上限 |
| `MAX_ADVANCE_US` | 80000 | 最大提前渲染时间（80ms） |
| `WAIT_TIME_US_THRESHOLD` | 1500000 | 最大等待时间（1.5s） |
| `SINK_TIME_US_THRESHOLD` | 100000 | 最大同步时间（100ms） |
| `PER_SINK_TIME_THRESHOLD_MAX` | 33000 | 最大每帧时长（33ms@30Hz） |
| `PER_SINK_TIME_THRESHOLD_MIN` | 8333 | 最小每帧时长（8.33ms@120Hz） |
| `VIDEO_SINK_START_FRAME` | 4 | 前4帧强制渲染（不丢帧） |
| `WAIT_TIME_US_THRESHOLD_WARNING` | 40000 | 早到警告阈值（40ms） |
| `WAIT_TIME_US_THRESHOLD_RENDER` | 70000 | 渲染警告阈值（70ms） |
| `DELTA_TIME_THRESHOLD` | 5000 | 抖动平滑阈值（5ms） |
| `BUFFER_FLAG_KEY_FRAME` | 0x00000002 | 关键帧标志 |

---

## 核心数据流

### DoSyncWrite 渲染决策入口

`VideoSink::DoSyncWrite(buffer, actionClock)`（`video_sink.cpp:75-120`）：

```
输入: AVBuffer（包含pts/flag/duration）
  ├─ EOS检查: flag & BUFFER_FLAG_EOS → ReportEos → return -1
  ├─ 首帧处理: isFirstFrame_ → 记录 firstFrameClockTime_/firstPts_/isFirstFrame_=false
  ├─ 非首帧: CheckBufferLatenessMayWait(buffer, nowCt) → waitTime
  ├─ UpdateTimeAnchorIfNeeded(nowCt, waitTime, buffer)
  ├─ lagDetector_.CalcLag(buffer) — 记录卡顿数据
  ├─ ReportPts(buffer->pts_) — PTS单调性检查
  │
  ├─ render条件: (render && waitTime >= 0) || dropFrameContinuouslyCnt_ >= 2
  │    → return waitTime (等待微秒数)
  │
  └─ discard条件: waitTime < 0（太晚）且非关键帧
       → discardFrameCnt_++ → return -1
```

### CheckBufferLatenessMayWait 三段式判决

`video_sink.cpp:245-280` 执行 diff 计算：

**第一段：边界检测**
```
if (lastBufferAnchoredClockTime_ != HST_TIME_NONE && seekFlag_ == false) {
    currentBufferRelativeClockTime = lastBufferAnchoredClockTime_ + relativePts - lastBufferRelativePts_;
    deltaTime = bufferAnchoredClockTime - currentBufferRelativeClockTime;
    deltaTimeAccu_ = SmoothDeltaTime(deltaTimeAccu_, deltaTime); // 平滑抖动
    if (|deltaTimeAccu_| < 5000) { bufferAnchoredClockTime = currentBufferRelativeClockTime; }
}
```

**第二段：diff 计算（CalcBufferDiff）**
- **锚点差**：currentClockTime + latency - bufferAnchoredClockTime + fixDelay_
- **视频帧差**：Δct - Δpts/播放速率
- **阈值调整**：videoDiff - initialVideoWaitPeriod_/2
- diff = anchorDiff（正常情况）
- **前4帧特殊处理**：diff = firstFrameClockTime - pts/speed（强制渲染）

**第三段：early/late 判决**
```
if (diff < 0)                    → 帧早到（需等待）
    waitTime = 0 - diff
    if waitTime > 1500000:       → 等待时间过长，取 ptsDiff 或 1.5s 上限
elif (diff > 0 && diff > 40ms)  → 帧晚到（tooLate=true）
    dropFlag = tooLate && !(flag & KEY_FRAME)
    return dropFlag ? -1 : waitTime
```

### CalcBufferDiff 三元组算法

`video_sink.cpp:300-330`：
```
anchorDiff  = currentClockTime + latency - bufferAnchoredClockTime + fixDelay_
videoDiff   = (currentClockTime - lastClockTime_) - (ptsDiff / playbackRate)
adjusted    = videoDiff - initialVideoWaitPeriod_ / 2
diff        = anchorDiff

if (前4帧) {
    ptsDiffWithSpeed = (buffer->pts_ - firstFramePts_) / AdjustPlaybackRate(playbackRate)
    diff = (currentClockTime - firstFrameClockTime_) - ptsDiffWithSpeed
} else if (diff > 0 && videoDiff < 100ms && diff < thresholdAdjustedVideoDiff) {
    diff = thresholdAdjustedVideoDiff  // 取平滑后的值
}
return diff
```

---

## VideoLagDetector 卡顿追踪

`video_sink.h:47-61` 内嵌类：

```cpp
class VideoLagDetector : public LagDetector {
public:
    void Reset() override;
    bool CalcLag(std::shared_ptr<AVBuffer> buffer) override;
    void GetLagInfo(int32_t& lagTimes, int32_t& maxLagDuration,
                    int32_t& avgLagDuration);
    void ResolveLagEvent(const int64_t &lagTimeMs);
    void SetEventReceiver(const std::shared_ptr<EventReceiver> eventReceiver);
private:
    int64_t lagTimes_ = 0;
    int64_t maxLagDuration_ = 0;
    int64_t lastSystemTimeMs_ = 0;
    int64_t lastBufferTimeMs_ = 0;
    int64_t totalLagDuration_ = 0;
    std::shared_ptr<EventReceiver> eventReceiver_ { nullptr };
};
```

**LagDetector 基类接口**（`media_synchronous_sink.h:56-63`）：
```cpp
class LagDetector {
public:
    virtual void Reset() = 0;
    virtual bool CalcLag(std::shared_ptr<AVBuffer> buffer) = 0;
};
```

**CalcLag 触发路径**：`DoSyncWrite` → `lagDetector_.CalcLag(buffer)`（每帧计算）

**上报路径**：`lagDetector_.ResolveLagEvent(lagTimeMs)` → `eventReceiver_->OnDfxEvent({ "VSINK", DFX_INFO_PERF_REPORT, perfData })`

**PerfRecorder**：`perfRecorder_.Record(waitTimeMs)` → 满时通过 `eventReceiver_->OnDfxEvent` 上报

---

## 同步中心交互

### IMediaSynchronizer 优先级

`i_media_sync_center.h:16-22`：
```cpp
struct IMediaSynchronizer {
    const static int8_t NONE = -1;
    const static int8_t VIDEO_SINK = 0;   // 最高优先级，锚点供应方
    const static int8_t AUDIO_SINK = 2;   // 次优先级
    const static int8_t VIDEO_SRC = 4;
    const static int8_t AUDIO_SRC = 6;
    const static int8_t SUBTITLE_SINK = 8;
};
```

VideoSink 作为 `VIDEO_SINK=0`，通过 `UpdateTimeAnchor` 建立时间锚点，是整个播放管线的时钟参考。

### IMediaSyncCenter 关键接口

| 接口 | 说明 |
|------|------|
| `UpdateTimeAnchor(clockTime, latency, IMediaTime, VIDEO_SINK)` | 建立时间锚点 |
| `GetAnchoredClockTime(relativePts)` | 根据相对PTS查锚点时钟 |
| `GetClockTimeNow()` | 当前播放时钟 |
| `SetPlaybackRate/GetPlaybackRate` | 播放速率 |
| `ReportPrerolled/ReportEos` | Preroll/EOS 上报 |
| `GetInitialVideoFrameRate()` | 获取初始帧率（用于初始等待期） |
| `SetLastVideoBufferPts/AbsPts` | 记录最新视频PTS（用于音视频同步） |

---

## 关键函数证据索引

| 证据 | 文件:行号 | 说明 |
|------|-----------|------|
| E1 | video_sink.cpp:42-51 | 常量定义（LAG_LIMIT_TIME/DROP_FRAME_CONTINUOUSLY_MAX_CNT等） |
| E2 | video_sink.cpp:75-120 | DoSyncWrite 渲染决策入口 |
| E3 | video_sink.cpp:102-120 | RecordStallingTimestamp DFX卡顿阶段记录 |
| E4 | video_sink.cpp:245-280 | CheckBufferLatenessMayWait 三段式判决 |
| E5 | video_sink.cpp:300-330 | CalcBufferDiff 三元组算法 |
| E6 | video_sink.cpp:370-380 | SmoothDeltaTime 抖动平滑 |
| E7 | video_sink.cpp:86-100 | UpdateTimeAnchorIfNeeded 时间锚点更新 |
| E8 | video_sink.cpp:380-390 | RenderAtTimeLog 早到日志 |
| E9 | video_sink.h:47-61 | VideoLagDetector 内嵌类定义 |
| E10 | video_sink.h:23-26 | SetSyncCenter/SetEventReceiver 接口 |
| E11 | video_sink.h:35 | DoSyncWrite 纯虚声明（基类） |
| E12 | video_sink.h:53-54 | SetMediaMuted/SetPerfRecEnabled |
| E13 | i_media_sync_center.h:16-22 | IMediaSynchronizer 优先级常量 |
| E14 | i_media_sync_center.h:24-55 | IMediaSyncCenter 接口清单 |
| E15 | media_synchronous_sink.h:26-30 | MediaSynchronousSink 基类定义 |
| E16 | media_synchronous_sink.h:34-37 | WriteToPluginRefTimeSync 时间同步写入 |
| E17 | video_sink.cpp:373-376 | SetSyncCenter → Init() 调用链 |
| E18 | video_sink.cpp:121-135 | PerfRecord → perfRecorder_.Record → eventReceiver_->OnDfxEvent |

---

## 与相关主题的关系

| 主题 | 关系 | 说明 |
|------|------|------|
| S32 VideoRenderFilter | 持有方 | VideoRenderFilter 持有 VideoSink 实例 |
| S31 AudioSinkFilter | 对称 | AudioSink 同继承 MediaSynchronousSink，优先级=2 |
| S22 MediaSyncManager | 协同 | VideoSink 通过 IMediaSyncCenter 建立锚点，优先级=0 |
| S49 SubtitleSinkFilter | 对称 | SubtitleSink 同继承 MediaSynchronousSink，优先级=8 |
