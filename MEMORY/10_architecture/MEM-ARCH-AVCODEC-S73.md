---
status: pending_approval
---

# MEM-ARCH-AVCODEC-S73: 三路 Sink 引擎同步架构——VideoSink / AudioSink / SubtitleSink 与 MediaSyncManager 协作机制

> **ID**: MEM-ARCH-AVCODEC-S73
> **Title**: 三路 Sink 引擎同步架构——VideoSink / AudioSink / SubtitleSink 与 MediaSyncManager 协作机制
> **Type**: architecture
> **Status**: draft
> **Created**: 2026-05-03T05:18:00+08:00
> **Scope**: [AVCodec, MediaEngine, Sink, MediaSync, VideoSink, AudioSink, SubtitleSink, IMediaSynchronizer, DoSyncWrite, MediaSyncManager, AVBufferQueue, Synchronizer, SyncCenter]
> **Confidence**: high
> **Author**: builder-agent
> **Related**: [S31(AudioSinkFilter), S32(VideoRenderFilter), S49(SubtitleSinkFilter), S22(MediaSyncManager), S56(VideoSink同步详情), S61(AudioSink详情)]
> **Evidence Source**: 本地仓库 `/home/west/.openclaw/workspace-main/avcodec-dfx-memory/repo_tmp`

---

## 1. 概述

AVCodec 播放管线的三路 Sink 引擎（VideoSink / AudioSink / SubtitleSink）均继承 `MediaSynchronousSink`，通过 `MediaSyncManager` 实现音视频字幕三路同步。三者共享 `IMediaSynchronizer` 接口，各自承担不同优先级：

| Sink | syncerPriority | 同步优先级值 | 角色 |
|------|---------------|------------|------|
| VideoSink | VIDEO_SINK | 0 | 时钟锚点供应方（播放管线时钟基准） |
| AudioSink | AUDIO_SINK | 2 | 主要音频渲染终点 |
| SubtitleSink | SUBTITLE_SINK | 8 | 字幕渲染终点（最低优先级） |

**三路 Sink 在播放管线中的位置**：Filter Pipeline 的最下游终点，数据流为：
```
DemuxerFilter(S41) → VideoDecoderFilter(S45/S46) → VideoRenderFilter(S32) → VideoSink
                                                        ↓
                                              AudioDecoderFilter(S35) → AudioSinkFilter(S31) → AudioSink
                                                        ↓
                                              SubtitleSinkFilter(S49) → SubtitleSink
```

**关键文件路径锚点**：
```
i_media_sync_center.h:27-34     // IMediaSynchronizer 接口定义，syncerPriority 三路优先级常量
video_sink.cpp:72               // VideoSink syncerPriority_ = VIDEO_SINK (0)
audio_sink.cpp:80,90            // AudioSink syncerPriority_ = AUDIO_SINK (2)
subtitle_sink.cpp:40            // SubtitleSink syncerPriority_ = SUBTITLE_SINK (8)
media_synchronous_sink.cpp:52   // GetSyncerPriority() 返回 syncerPriority_
media_sync_manager.cpp          // MediaSyncManager AddSynchronizer/RemoveSynchronizer
```

---

## 2. IMediaSynchronizer 接口与三路优先级体系

### 2.1 接口定义（i_media_sync_center.h）

```cpp
// services/media_engine/modules/sink/i_media_sync_center.h:27-34
struct IMediaSynchronizer {
    const static int8_t VIDEO_SINK = 0;     // 最高优先级，时钟锚点供应方
    const static int8_t AUDIO_SINK = 2;      // 中优先级，音频渲染终点
    const static int8_t SUBTITLE_SINK = 8;   // 最低优先级，字幕渲染终点
    virtual ~IMediaSynchronizer() = default;
    virtual int8_t GetSyncerPriority() = 0;
    virtual void SetSyncCenter(std::shared_ptr<Pipeline::MediaSyncManager> syncCenter) = 0;
    virtual void AddSynchronizer(IMediaSynchronizer* syncer) = 0;
    virtual void RemoveSynchronizer(IMediaSynchronizer* syncer) = 0;
    virtual int64_t GetMediaTimeNow() = 0;
    // ... 时间锚点/PTS/Seek 等接口
};
```

### 2.2 三路 Sink 的 syncerPriority 初始化

**VideoSink** (`video_sink.cpp:72`)：
```cpp
VideoSink::VideoSink()
{
    refreshTime_ = 0;
    syncerPriority_ = IMediaSynchronizer::VIDEO_SINK;  // = 0
    // ...
}
```

**AudioSink** (`audio_sink.cpp:80,90`)：
```cpp
AudioSink::AudioSink()
{
    // ...
    syncerPriority_ = IMediaSynchronizer::AUDIO_SINK;  // = 2
}

// 或者在 Init 中：
syncerPriority_ = IMediaSynchronizer::AUDIO_SINK;
```

**SubtitleSink** (`subtitle_sink.cpp:40`)：
```cpp
SubtitleSink::SubtitleSink()
{
    MEDIA_LOG_I("SubtitleSink ctor");
    syncerPriority_ = IMediaSynchronizer::SUBTITLE_SINK;  // = 8
}
```

### 2.3 MediaSynchronousSink 基类

```cpp
// services/media_engine/modules/sink/media_synchronous_sink.cpp:52
int8_t MediaSynchronousSink::GetSyncerPriority()
{
    return syncerPriority_;
}

// media_synchronous_sink.cpp:79 - DoSyncWrite 回调驱动
DoSyncWrite(buffer, actionClock);
```

三路 Sink 均继承 `MediaSynchronousSink`，`DoSyncWrite` 是各自的虚函数实现，由 `MediaSynchronousSink` 基类统一调用。

---

## 3. VideoSink 视频渲染同步器

### 3.1 DoSyncWrite 渲染决策（video_sink.cpp:125）

```cpp
// video_sink.cpp:125
int64_t VideoSink::DoSyncWrite(const std::shared_ptr<OHOS::Media::AVBuffer>& buffer, int64_t& actionClock)
{
    // ...
    int64_t waitTime = CheckBufferLatenessMayWait(buffer, nowCt);
    // waitTime > 0: 早到等待；waitTime < 0: 迟到需追赶
}
```

**前 4 帧强制渲染**（`video_sink.cpp:244`）：
```cpp
if (discardFrameCnt_ + renderFrameCnt_ < VIDEO_SINK_START_FRAME) {  // VIDEO_SINK_START_FRAME = 4
    // 前 4 帧强制渲染，不做任何延迟
}
```

### 3.2 CalcBufferDiff 三元组算法（video_sink.cpp:227-248）

```cpp
int64_t VideoSink::CalcBufferDiff(..., int64_t bufferAnchoredClockTime, int64_t currentClockTime, float playbackRate)
{
    uint64_t latency = 0;
    GetLatency(latency);
    // anchorDiff: 当前时钟与缓冲锚点的差值（含延迟补偿）
    auto anchorDiff = currentClockTime + (int64_t) latency - bufferAnchoredClockTime + fixDelay_;
    // videoDiff: 实际帧间隔与理论帧间隔的差值
    auto videoDiff = (currentClockTime - lastClockTime_)
        - static_cast<int64_t>((buffer->pts_ - lastPts_) / AdjustPlaybackRate(playbackRate));
    // thresholdAdjustedVideoDiff: 初始等待期调整后的 videoDiff
    auto thresholdAdjustedVideoDiff = videoDiff
        - static_cast<int64_t>(initialVideoWaitPeriod_ / STARTUP_FRAME_INTERVAL_FACTOR);
    // ...
}
```

### 3.3 CheckBufferLatenessMayWait 早迟判断（video_sink.cpp:256-304）

```cpp
int64_t VideoSink::CheckBufferLatenessMayWait(const std::shared_ptr<OHOS::Media::AVBuffer>& buffer, int64_t clockNow)
{
    InitWaitPeriod();
    auto syncCenter = syncCenter_.lock();
    auto relativePts = buffer->pts_ - firstPts_;
    auto bufferAnchoredClockTime = syncCenter->GetAnchoredClockTime(relativePts);
    // 三元组：锚点差(anchorDiff) / 视频帧差(videoDiff) / 初始等待期(initialVideoWaitPeriod_)
    auto diff = CalcBufferDiff(buffer, bufferAnchoredClockTime, clockNow, ...);
    // ...
}
```

### 3.4 VideoLagDetector 卡顿追踪（video_sink.cpp:395-440）

```cpp
// VideoSink 内嵌类
bool VideoSink::VideoLagDetector::CalcLag(std::shared_ptr<AVBuffer> buffer)
{
    // 追踪 lag 事件：卡顿时长统计
}

void VideoSink::VideoLagDetector::ResolveLagEvent(const int64_t &lagTimeMs)
{
    // 上报 lag 事件
}
```

---

## 4. AudioSink 音频渲染引擎

### 4.1 syncerPriority = AUDIO_SINK（audio_sink.cpp:80）

```cpp
AudioSink::AudioSink()
{
    syncerPriority_ = IMediaSynchronizer::AUDIO_SINK;  // = 2
    // ...
}
```

AudioSink 继承 `MediaSynchronousSink`，通过 `OnWriteData` 回调链写入底层音频插件。

### 4.2 关键行为

- **双缓冲区队列**：`AUDIO_SINK_BQ` 内存使用事件上报（`audio_sink.cpp:336`）
- **AudioVivid 固定延迟补偿**：80ms 固定延迟（与 S61 草案一致）
- **插件创建**：`audio_sink.cpp:545`
  ```cpp
  auto plugin = Plugins::PluginManagerV2::Instance().CreatePluginByMime(
      Plugins::PluginType::AUDIO_SINK, "audio/raw");
  ```

---

## 5. SubtitleSink 字幕渲染引擎

### 5.1 syncerPriority = SUBTITLE_SINK（subtitle_sink.cpp:40）

```cpp
SubtitleSink::SubtitleSink()
{
    syncerPriority_ = IMediaSynchronizer::SUBTITLE_SINK;  // = 8
}
```

### 5.2 SubtitleBufferState 三状态（subtitle_sink.h:120）

```cpp
// interfaces/inner_api/native/subtitle_sink.h:120
enum SubtitleBufferState : uint32_t {
    WAIT,   // 字幕尚未到显示时间，等待
    SHOW,   // 字幕在显示时间窗口内，显示
    DROP,   // 字幕已过期，丢弃
};
```

### 5.3 RenderLoop 主循环（subtitle_sink.cpp:286-320）

```cpp
void SubtitleSink::RenderLoop()
{
    while (SUBTITME_LOOP_RUNNING) {  // SUBTITME_LOOP_RUNNING = true
        std::unique_lock<std::mutex> lock(mutex_);
        updateCond_.wait(lock, [this] {
            return isThreadExit_.load() ||
                   (!subtitleInfoVec_.empty() && state_ == Pipeline::FilterState::RUNNING);
        });
        // ...
        SubtitleInfo subtitleInfo = subtitleInfoVec_.front();
        int64_t waitTime = static_cast<int64_t>(CalcWaitTime(subtitleInfo));
        updateCond_.wait_for(lock, std::chrono::microseconds(waitTime), ...);
        auto actionToDo = ActionToDo(subtitleInfo);
        if (actionToDo == SubtitleBufferState::DROP) {
            subtitleInfoVec_.pop_front();
            inputBufferQueueConsumer_->ReleaseBuffer(subtitleInfo.buffer_);
            continue;
        } else if (actionToDo == SubtitleBufferState::WAIT) {
            continue;
        }
        NotifyRender(subtitleInfo);
        subtitleInfoVec_.pop_front();
        inputBufferQueueConsumer_->ReleaseBuffer(subtitleInfo.buffer_);
    }
}
```

### 5.4 ActionToDo 三状态判断（subtitle_sink.cpp:347-363）

```cpp
uint32_t SubtitleSink::ActionToDo(SubtitleInfo &subtitleInfo)
{
    auto curTime = GetMediaTime();
    if (subtitleInfo.pts_ + subtitleInfo.duration_ < curTime) {
        return SubtitleBufferState::DROP;  // 过期丢弃
    }
    if (subtitleInfo.pts_ > curTime || state_ != Pipeline::FilterState::RUNNING) {
        return SubtitleBufferState::WAIT;  // 未到显示时间，等待
    }
    subtitleInfo.duration_ -= curTime - subtitleInfo.pts_;
    return SubtitleBufferState::SHOW;  // 显示
}
```

### 5.5 RemoveTextTags HTML 标签剥离（subtitle_sink.cpp:483-520）

```cpp
// subtitle_sink.cpp:28
static const std::unordered_set<std::string> SUPPORTED_TAGS = {"b", "i", "u", "s", "font"};

// subtitle_sink.cpp:483
std::string SubtitleSink::RemoveTextTags(const std::string& text)
{
    // 剥离 <b>/<i>/<u>/<s>/<font> 等支持的 HTML 标签
    // 未支持的标签直接移除内容
}
```

### 5.6 NotifyRender 字幕上报（subtitle_sink.cpp:373-381）

```cpp
void SubtitleSink::NotifyRender(SubtitleInfo &subtitleInfo)
{
    Format format;
    (void)format.PutStringValue(Tag::SUBTITLE_TEXT, subtitleInfo.text_);
    (void)format.PutIntValue(Tag::SUBTITLE_PTS, Plugins::Us2Ms(subtitleInfo.pts_));
    (void)format.PutIntValue(Tag::SUBTITLE_DURATION, Plugins::Us2Ms(subtitleInfo.duration_));
    Event event{ .srcFilter = "SubtitleSink", .type = EventType::EVENT_SUBTITLE_TEXT_UPDATE, .param = format };
    playerEventReceiver_->OnEvent(event);
}
```

### 5.7 NotifySeek 字幕队列清空（subtitle_sink.cpp:65-68）

```cpp
void SubtitleSink::NotifySeek()
{
    Flush(true);  // Seek 时清空字幕队列
}
```

---

## 6. MediaSyncManager 同步管理中心

### 6.1 三路同步器注册

MediaSyncManager 通过 `AddSynchronizer` 接口将三个 Sink 的 `IMediaSynchronizer*` 指针注册到统一管理：
```cpp
// i_media_sync_center.h:42
virtual void AddSynchronizer(IMediaSynchronizer* syncer) = 0;
virtual void RemoveSynchronizer(IMediaSynchronizer* syncer) = 0;
```

### 6.2 SetSyncCenter 三路绑定

每个 Sink 在 `SetSyncCenter` 时传入 `MediaSyncManager` 弱引用：
```cpp
// video_sink.cpp:320
void VideoSink::SetSyncCenter(std::shared_ptr<Pipeline::MediaSyncManager> syncCenter)
{
    syncCenter_ = syncCenter;
    MediaSynchronousSink::Init();
}
```

### 6.3 GetMediaTimeNow 时间查询

```cpp
int64_t VideoSink::GetMediaTime()
{
    auto syncCenter = syncCenter_.lock();
    if (!syncCenter) { return 0; }
    return syncCenter->GetMediaTimeNow();
}
```

---

## 7. 三路 Sink 架构对比

| 属性 | VideoSink | AudioSink | SubtitleSink |
|------|-----------|-----------|--------------|
| syncerPriority | 0 (VIDEO_SINK) | 2 (AUDIO_SINK) | 8 (SUBTITLE_SINK) |
| 是否时钟锚点 | ✓ 是（Clock Supplier） | ✗ | ✗ |
| DoSyncWrite 实现 | CheckBufferLatenessMayWait + CalcBufferDiff | 继承基类 AudioVivid 80ms 补偿 | DoSyncWrite 返回 0（直接 RenderLoop） |
| 前几帧处理 | 前 4 帧强制渲染（VIDEO_SINK_START_FRAME=4） | 无特殊处理 | 无特殊处理 |
| 缓冲队列 | AVBufferQueue | AUDIO_SINK_BQ | subtitleInfoVec_ 内存队列 |
| RenderLoop | ✗ 无独立线程 | ✗ 无独立线程 | ✓ 独立线程（"SubtitleRenderLoop"） |
| HTML 标签剥离 | N/A | N/A | ✓ RemoveTextTags |
| 卡顿检测 | VideoLagDetector 内嵌类 | N/A | N/A |
| 状态机 | FilterState（继承） | FilterState（继承） | FilterState（继承） |

---

## 8. 关联关系

- **S31**（AudioSinkFilter）= Filter 层封装 → 底层调用 AudioSink
- **S32**（VideoRenderFilter）= Filter 层封装 → 底层调用 VideoSink
- **S49**（SubtitleSinkFilter）= Filter 层封装 → 底层调用 SubtitleSink
- **S22**（MediaSyncManager）= 同步管理中心 → 管理三路同步
- **S56**（VideoSink详情）= VideoSink 深度分析（DoSyncWrite/CalcBufferDiff/LagDetector）
- **S61**（AudioSink详情）= AudioSink 深度分析（AudioSampleFormat/AudioVivid）

---

## 9. 关键行号索引

| 文件 | 行号 | 内容 |
|------|------|------|
| i_media_sync_center.h | 27-34 | IMediaSynchronizer 接口，三路优先级常量 |
| video_sink.cpp | 72 | VideoSink syncerPriority_ = VIDEO_SINK (0) |
| video_sink.cpp | 59 | VIDEO_SINK_START_FRAME = 4 |
| video_sink.cpp | 125 | DoSyncWrite 渲染决策入口 |
| video_sink.cpp | 227-248 | CalcBufferDiff 三元组算法 |
| video_sink.cpp | 256-304 | CheckBufferLatenessMayWait 早迟判断 |
| video_sink.cpp | 395-440 | VideoLagDetector 卡顿追踪 |
| audio_sink.cpp | 80,90 | AudioSink syncerPriority_ = AUDIO_SINK (2) |
| subtitle_sink.cpp | 40 | SubtitleSink syncerPriority_ = SUBTITLE_SINK (8) |
| subtitle_sink.cpp | 65-68 | NotifySeek → Flush |
| subtitle_sink.cpp | 144 | readThread_ = std::thread(&SubtitleSink::RenderLoop, ...) |
| subtitle_sink.cpp | 286-320 | RenderLoop 主循环 |
| subtitle_sink.cpp | 347-363 | ActionToDo 三状态判断 |
| subtitle_sink.cpp | 373-381 | NotifyRender 字幕上报 |
| subtitle_sink.cpp | 483-520 | RemoveTextTags HTML 标签剥离 |
| subtitle_sink.h | 120 | SubtitleBufferState 枚举：WAIT/SHOW/DROP |
| media_synchronous_sink.cpp | 52 | GetSyncerPriority() 返回 syncerPriority_ |
| media_synchronous_sink.cpp | 79 | DoSyncWrite(buffer, actionClock) 统一调用 |
