# MEM-ARCH-AVCODEC-S240 — MediaSyncManager 媒体同步管理中心

> **状态**: draft
> **生成时间**: 2026-06-20 19:47 CST+8
> **Builder**: builder-agent (subagent)
> **源码**: 基于本地镜像 `/home/west/av_codec_repo`
> **待审批后移入**: `MEMORY/10_architecture/MEM-ARCH-AVCODEC-S240.md`

---

## 1. 概述

MediaSyncManager 是 OH_AVCodec/MediaSync pipeline 的**媒体同步时钟管理中心**，负责：
- 音视频时间同步（AV Sync）
- 播放速率控制（PlaybackRate）
- 暂停/恢复/Seek 状态管理
- Preroll 缓冲同步（所有轨道首帧就绪后统一开始播放）
- 媒体时间范围边界（防止音视频时间回退或超前）

**关联主题**：S22（Pipeline整体流程）/ S98（Sink模块）/ S56（音视频同步）/ S116（MediaSync相关）/ S185（AudioServerSink）

---

## 2. 核心数据结构

### 2.1 IMediaSynchronizer 优先级枚举（i_media_sync_center.h L22-32）

```cpp
struct IMediaSynchronizer {
    const static int8_t NONE = -1;         // 无优先级
    const static int8_t VIDEO_SINK = 0;     // 视频渲染器
    const static int8_t AUDIO_SINK = 2;     // 音频渲染器（最高）
    const static int8_t VIDEO_SRC = 4;      // 视频源
    const static int8_t AUDIO_SRC = 6;      // 音频源
    const static int8_t SUBTITLE_SINK = 8;  // 字幕渲染器
    virtual int8_t GetPriority() = 0;
    virtual void WaitAllPrerolled(bool shouldWait) = 0;
    virtual void NotifyAllPrerolled() = 0;
};
```

**说明**：AUDIO_SINK 优先级最高（2），VIDEO_SINK 次之（0），因为音频是主时钟源。

### 2.2 IMediaSyncCenter 接口结构（i_media_sync_center.h L37-82）

```cpp
struct IMediaSyncCenter {
    virtual Status Reset() = 0;
    virtual void AddSynchronizer(IMediaSynchronizer* syncer) = 0;
    virtual void RemoveSynchronizer(IMediaSynchronizer* syncer) = 0;
    struct IMediaTime { int64_t mediaTime; int64_t absMediaTime; int64_t maxMediaTime; } iMediaTime;
    virtual bool UpdateTimeAnchor(int64_t clockTime, int64_t delayTime, IMediaTime iMediaTime,
        IMediaSynchronizer* supplier) = 0;
    virtual int64_t GetMediaTimeNow() = 0;
    virtual int64_t GetClockTimeNow() = 0;
    virtual int64_t GetAnchoredClockTime(int64_t mediaTime) = 0;
    virtual void ReportPrerolled(IMediaSynchronizer* supplier) = 0;
    virtual void ReportEos(IMediaSynchronizer* supplier) = 0;
    virtual void SetMediaTimeRangeStart(int64_t startMediaTime, int32_t trackId,
        IMediaSynchronizer* supplier) = 0;
    virtual void SetMediaTimeRangeEnd(int64_t endMediaTime, int32_t trackId,
        IMediaSynchronizer* supplier) = 0;
    virtual int64_t GetSeekTime() = 0;
    virtual Status SetPlaybackRate(float rate) = 0;
    virtual float GetPlaybackRate() = 0;
    virtual void SetMediaStartPts(int64_t startPts) = 0;
    virtual void SetLastAudioBufferDuration(int64_t durationUs) = 0;
    virtual void SetLastVideoBufferPts(int64_t bufferPts) = 0;
    virtual void SetLastVideoBufferAbsPts(int64_t lastVideoBufferAbsPts) = 0;
    virtual double GetInitialVideoFrameRate() = 0;
    virtual int64_t GetLastVideoBufferAbsPts() const = 0;
};
```

### 2.3 MediaSyncManager 状态机（media_sync_manager.h L55-59）

```cpp
enum class State {
    RESUMED,  // 播放中
    PAUSED,   // 已暂停
};
```

### 2.4 MediaSyncManager 关键成员变量（media_sync_manager.h L63-123）

```cpp
// 同步器管理
std::vector<IMediaSynchronizer*> syncers_;           // 已注册的同步器列表
std::vector<IMediaSynchronizer*> prerolledSyncers_;  // 已报告Prerolled的同步器

// 时间锚点（核心）
int64_t currentAnchorClockTime_;   // 系统时钟锚点（纳秒）
int64_t currentAnchorMediaTime_;   // 媒体时间锚点（微秒）
int64_t delayTime_;                // 渲染延迟（微秒）
int8_t currentSyncerPriority_;     // 当前锚点来源的优先级

// 播放速率
float playRate_ = 1.0f;           // 播放速率（支持变速播放）
int64_t delayTime_ = HST_TIME_NONE;

// Seek状态
bool isSeeking_ = false;
int64_t seekingMediaTime_ = HST_TIME_NONE;
bool isFrameAfterSeeked_ = false; // Seek后第一帧标记
int64_t firstMediaTimeAfterSeek_ = HST_TIME_NONE;
std::condition_variable seekCond_; // Seek完成通知

// 媒体时间范围
int64_t minRangeStartOfMediaTime_; // 轨道最小起始PTS
int64_t maxRangeEndOfMediaTime_;   // 轨道最大结束PTS
int8_t currentRangeStartPriority_; // 范围来源优先级
int8_t currentRangeEndPriority_;

// Preroll同步
bool alreadySetSyncersShouldWait_; // 是否已通知所有同步器等待Preroll
std::atomic<int64_t> lastReportMediaTime_; // 上次报告的媒体时间（防止回退）

// 暂停状态
int64_t pausedMediaTime_;    // 暂停时的媒体时间
int64_t pausedClockTime_;    // 暂停时的系统时钟

// 视频/音频缓冲追踪（用于最大进度计算）
std::atomic<int64_t> lastAudioBufferDuration_;  // 最近音频缓冲时长
std::atomic<int64_t> lastVideoBufferPts_;        // 最近视频Buffer PTS
int64_t lastVideoBufferAbsPts_;                   // 最近视频Buffer绝对PTS
```

---

## 3. 时间同步机制

### 3.1 时间锚点更新（UpdateTimeAnchor）

**文件**: `media_sync_manager.cpp L251-275`

```cpp
bool MediaSyncManager::UpdateTimeAnchor(int64_t clockTime, int64_t delayTime, IMediaTime iMediaTime,
    IMediaSynchronizer* supplier)
{
    // 过滤无效输入
    if (clockTime == HST_TIME_NONE || iMediaTime.mediaTime == HST_TIME_NONE
        || delayTime == HST_TIME_NONE || supplier == nullptr) {
        return render;
    }
    clockTime += delayTime;  // 加入渲染延迟
    delayTime_ = delayTime;
    // 只接受更高优先级同步器更新锚点
    if (IsSupplierValid(supplier) && supplier->GetPriority() >= currentSyncerPriority_) {
        currentSyncerPriority_ = supplier->GetPriority();
        SimpleUpdateTimeAnchor(clockTime, iMediaTime.mediaTime); // 更新锚点
        if (isSeeking_) {
            isSeeking_ = false;           // 离开Seek状态
            seekCond_.notify_all();        // 通知等待Seek完成的线程
            UpdateFirstPtsAfterSeek(iMediaTime.mediaTime);
        }
    }
}
```

**关键设计**：高优先级同步器（AUDIO_SINK=2 > VIDEO_SINK=0）才能更新锚点，音频主时钟原则。

### 3.2 GetMediaTimeNow 计算链（media_sync_manager.cpp L343-351）

```cpp
int64_t MediaSyncManager::GetMediaTimeNow()
{
    OHOS::Media::AutoLock lock(clockMutex_);
    int64_t currentMediaTime = HST_TIME_NONE;
    for (const auto &func : setMediaTimeFuncs) {  // 四步检查链
        FALSE_RETURN_V_NOLOG(func(this, currentMediaTime), currentMediaTime);
    }
    currentMediaTime = BoundMediaProgress(currentMediaTime); // 边界检查
    lastReportMediaTime_ = currentMediaTime;
    return currentMediaTime;
}
```

**四步检查链**（setMediaTimeFuncs L46-49）：

| 步骤 | 函数 | 作用 |
|------|------|------|
| 1 | CheckSeekingMediaTime | Seek中直接返回 seekingMediaTime_ |
| 2 | CheckPausedMediaTime | 暂停时返回 pausedMediaTime_ |
| 3 | CheckIfMediaTimeIsNone | 无效时间设为0 |
| 4 | CheckFirstMediaTimeAfterSeek | Seek后音频未到则取首帧时间 |

### 3.3 GetMediaTime 数学公式（media_sync_manager.cpp L381-385）

```cpp
int64_t MediaSyncManager::GetMediaTime(int64_t clockTime)
{
    // mediaTime = anchorMediaTime + (clockTime - anchorClockTime + delayTime) × playRate - delayTime
    return currentAnchorMediaTime_ + (clockTime - currentAnchorClockTime_ + delayTime_)
        * static_cast<double>(playRate_) - delayTime_;
}
```

### 3.4 GetMaxMediaProgress 最大进度计算（media_sync_manager.cpp L323-328）

```cpp
int64_t MediaSyncManager::GetMaxMediaProgress()
{
    // 音频优先：当前锚点 + 最近音频缓冲时长
    FALSE_RETURN_V_NOLOG(currentSyncerPriority_ != IMediaSynchronizer::AUDIO_SINK,
        currentAnchorMediaTime_ + lastAudioBufferDuration_);
    // 视频其次：最近视频PTS
    FALSE_RETURN_V_NOLOG(currentSyncerPriority_ != IMediaSynchronizer::VIDEO_SINK,
        lastVideoBufferPts_);
    // 默认：取锚点MediaTime和已报告MediaTime的较大值
    return std::max(currentAnchorMediaTime_, lastReportMediaTime_.load());
}
```

---

## 4. Preroll 同步机制

### 4.1 Prerolled 报告链（media_sync_manager.cpp L404-418）

```cpp
void MediaSyncManager::ReportPrerolled(IMediaSynchronizer* supplier)
{
    if (supplier == nullptr) return;
    OHOS::Media::AutoLock lock(syncersMutex_);
    // 已报告则跳过
    auto ite = std::find(prerolledSyncers_.begin(), prerolledSyncers_.end(), supplier);
    if (ite != prerolledSyncers_.end()) return;
    prerolledSyncers_.emplace_back(supplier);
    // 所有同步器都报告了 → 统一触发NotifyAllPrerolled
    if (prerolledSyncers_.size() == syncers_.size()) {
        for (const auto& prerolled : prerolledSyncers_) {
            prerolled->NotifyAllPrerolled();
        }
        prerolledSyncers_.clear();
    }
}
```

**机制**：所有轨道（音/视/字幕）首帧就绪后，才通知各同步器开始渲染，避免某一轨道拖后腿导致首帧卡顿。

### 4.2 MediaSynchronousSink Preroll 等待（media_synchronous_sink.cpp L53-71）

```cpp
void MediaSynchronousSink::WriteToPluginRefTimeSync(const std::shared_ptr<AVBuffer>& buffer)
{
    if (!hasReportedPrerolled_) {
        auto syncCenter = syncCenter_.lock();
        if (syncCenter) {
            syncCenter->ReportPrerolled(this); // 报告首帧已到达
        }
        hasReportedPrerolled_ = true;
    }
    if (waitForPrerolled_) {
        OHOS::Media::AutoLock lock(prerollMutex_);
        // 等待所有同步器都报告Prerolled
        prerollCond_.WaitFor(lock, Plugins::HstTime2Ms(waitPrerolledTimeout_),
                             [&] { return waitForPrerolled_.load(); });
        waitForPrerolled_ = false; // 只等一次
    }
    int64_t actionClock = 0;
    DoSyncWrite(buffer, actionClock); // 实际写入
}
```

---

## 5. Seek 与暂停机制

### 5.1 Seek 操作（media_sync_manager.cpp L158-174）

```cpp
Status MediaSyncManager::Seek(int64_t mediaTime, bool isClosest)
{
    OHOS::Media::AutoLock lock(clockMutex_);
    FALSE_RETURN_V_NOLOG(minRangeStartOfMediaTime_ != HST_TIME_NONE &&
        maxRangeEndOfMediaTime_ != HST_TIME_NONE, Status::ERROR_INVALID_OPERATION);
    isSeeking_ = true;
    seekingMediaTime_ = mediaTime;
    alreadySetSyncersShouldWait_ = false;        // 重置Preroll标记
    SetAllSyncShouldWaitNoLock();                // 通知所有同步器重新等待Preroll
    ResetTimeAnchorNoLock();                     // 重置时间锚点
    isFrameAfterSeeked_ = true;
    if (isClosest) {
        firstMediaTimeAfterSeek_ = mediaTime;
    } else {
        firstMediaTimeAfterSeek_ = HST_TIME_NONE;
    }
    return Status::OK;
}
```

### 5.2 Pause/Resume（media_sync_manager.cpp L117-145）

```cpp
Status MediaSyncManager::Pause()
{
    OHOS::Media::AutoLock lock(clockMutex_);
    pausedClockTime_ = GetSystemClock();
    pausedMediaTime_ = std::min(GetMediaTime(pausedClockTime_), GetMaxMediaProgress());
    clockState_ = State::PAUSED;
}

Status MediaSyncManager::Resume()
{
    OHOS::Media::AutoLock lock(clockMutex_);
    // 恢复时重新设置锚点
    if (clockState_ == State::PAUSED && pausedMediaTime_ != HST_TIME_NONE
        && alreadySetSyncersShouldWait_) {
        SimpleUpdateTimeAnchor(GetSystemClock(), pausedMediaTime_);
    }
    SetAllSyncShouldWaitNoLock();
    clockState_ = State::RESUMED;
}
```

---

## 6. 播放速率控制

**文件**: `media_sync_manager.cpp L62-80`

```cpp
Status MediaSyncManager::SetPlaybackRate(float rate)
{
    FALSE_RETURN_V_MSG_W(rate >= 0, Status::ERROR_INVALID_PARAMETER,
        "Invalid playback Rate: %{public}f", rate);
    OHOS::Media::AutoLock lock(clockMutex_);
    int64_t currentClockTime = GetSystemClock();
    int64_t currentMediaTime = std::min(GetMediaTime(currentClockTime), GetMaxMediaProgress());
    if (currentMediaTime != HST_TIME_NONE) {
        SimpleUpdateTimeAnchor(currentClockTime, currentMediaTime); // 切换速率前重锚
    }
    playRate_ = rate;
    return Status::OK;
}
```

**公式**: `mediaTime = anchorMediaTime + (clockTime - anchorClockTime + delayTime) × playRate - delayTime`

---

## 7. VideoSink 集成

**文件**: `video_sink.cpp`

VideoSink 继承 `MediaSynchronousSink`（通过 `DoSyncWrite`），集成方式：

| 行号 | 功能 |
|------|------|
| L59 | `constexpr int VIDEO_SINK_START_FRAME = 4` 前4帧不丢帧 |
| L59 | `constexpr int64_t LAG_LIMIT_TIME = 100` 超过100ms视为卡顿 |
| L91 | `syncCenter->SetLastVideoBufferPts(buffer->pts_ - firstPts_)` 更新最后视频PTS |
| L92 | `syncCenter->SetLastVideoBufferAbsPts(buffer->pts_)` 更新绝对PTS |
| L98-99 | `UpdateTimeAnchor(nowCt + waitTime, latency, iMediaTime, this)` 更新时间锚点 |
| L125 | `DoSyncWrite` 同步写入 |
| L148 | `syncCenter->ReportEos(this)` 报告EOS |
| L284 | `syncCenter->GetPlaybackRate()` 获取播放速率 |
| L320 | `SetSyncCenter` 注入MediaSyncManager |

---

## 8. AudioSink 集成

**文件**: `audio_sink.cpp`

| 行号 | 功能 |
|------|------|
| L80/90 | `syncerPriority_ = IMediaSynchronizer::AUDIO_SINK` 音频Sink优先级 |
| L988 | `UpdateTimeAnchor` 音频渲染时更新锚点（音频是主时钟源） |
| L999 | 第二次 `UpdateTimeAnchor` 更新带延迟 |
| L1015-1016 | `syncCenter->GetMediaStartPts()` 获取起始PTS |
| L1029-1031 | `syncCenter->SetLastAudioBufferDuration` 追踪音频缓冲时长 |
| L1330 | `UnderrunDetector::SetLastAudioBufferDuration` |
| L1358 | `AudioLagDetector::CalcLag` 音频卡顿检测 |
| L1400-1406 | `AudioLagDetector` 使用 `syncCenter->GetClockTimeNow()` |

---

## 9. Lag Detector（卡顿检测）

**文件**: `media_synchronous_sink.h L38-46`

```cpp
class LagDetector {
public:
    virtual void Reset() = 0;
    virtual bool CalcLag(std::shared_ptr<AVBuffer> buffer) = 0;
};
```

| 类 | 文件 | 用途 |
|----|------|------|
| VideoLagDetector | video_sink.cpp | 视频卡顿检测（LAG_LIMIT_TIME=100ms） |
| AudioLagDetector | audio_sink.cpp L1358 | 音频卡顿检测 |
| UnderrunDetector | audio_sink.cpp L1330 | 音频缓冲区欠载检测 |

---

## 10. 总结架构图

```
┌─────────────────────────────────────────────────────────────┐
│                     MediaSyncManager (491行cpp+164行h)       │
│  ┌─────────────────────────────────────────────────────────┐│
│  │  IMediaSyncCenter                                        ││
│  │  - AddSynchronizer / RemoveSynchronizer                 ││
│  │  - UpdateTimeAnchor(clockTime, delayTime, mediaTime)    ││
│  │  - GetMediaTimeNow() → 四步检查链                       ││
│  │  - ReportPrerolled / ReportEos                           ││
│  │  - SetPlaybackRate / Pause / Resume / Seek               ││
│  └─────────────────────────────────────────────────────────┘│
│                                                             │
│  时间锚点域:                                                 │
│  currentAnchorClockTime_ ← 系统纳秒时钟                       │
│  currentAnchorMediaTime_ ← 媒体微秒PTS                        │
│  playRate_ ← 播放速率                                        │
│  delayTime_ ← 渲染延迟                                       │
│                                                             │
│  Preroll域:                                                 │
│  syncers_ (所有同步器)                                       │
│  prerolledSyncers_ (已报告首帧的同步器)                      │
│  alreadySetSyncersShouldWait_ (是否已通知等待)               │
│  seekCond_ (Seek完成条件变量)                                │
└─────────────────────────────────────────────────────────────┘
         ↑ UpdateTimeAnchor / ReportPrerolled
         │ NotifyAllPrerolled / WaitAllPrerolled
         │
┌────────┴────────────────────────────────────────────────┐
│     MediaSynchronousSink (同步器基类, 76行h+123行cpp)     │
│  - DoSyncWrite() 纯虚（子类实现）                          │
│  - WaitForPrerolled / prerollCond_ 等待                  │
│  - syncerPriority_ 优先级（AUDIO_SINK=2 / VIDEO_SINK=0） │
│  - VideoLagDetector / AudioLagDetector                   │
└────────────────┬─────────────────────────────────────────┘
                 │
     ┌───────────┴───────────┐
     ▼                       ▼
VideoSink (462行)       AudioSink (1793行)
VIDEO_SINK=0           AUDIO_SINK=2 (最高优先级)
LAG_LIMIT=100ms         AudioLagDetector
前4帧不丢帧             UnderrunDetector
SetLastVideoBufferPts   SetLastAudioBufferDuration
SetLastVideoBufferAbsPts
```

---

## 11. Evidence（行号级）

| # | 文件 | 行号 | 说明 |
|---|------|------|------|
| E1 | `media_sync_manager.h` | L24-32 | IMediaSynchronizer 优先级枚举（AUDIO_SINK=2 > VIDEO_SINK=0） |
| E2 | `media_sync_manager.h` | L37-82 | IMediaSyncCenter 完整接口定义（24个虚方法） |
| E3 | `media_sync_manager.h` | L55-59 | State 状态机枚举（RESUMED/PAUSED） |
| E4 | `media_sync_manager.h` | L67-75 | setMediaTimeFuncs 四步检查链函数指针数组 |
| E5 | `media_sync_manager.h` | L78-88 | syncers_/prerolledSyncers_ 同步器向量 |
| E6 | `media_sync_manager.h` | L93-101 | 时间锚点变量（currentAnchorClockTime_/currentAnchorMediaTime_/delayTime_） |
| E7 | `media_sync_manager.h` | L105-115 | Seek相关变量（isSeeking_/seekingMediaTime_/seekCond_） |
| E8 | `media_sync_manager.h` | L118-121 | 时间范围变量（minRangeStartOfMediaTime_/maxRangeEndOfMediaTime_） |
| E9 | `media_sync_manager.cpp` | L41-48 | AddSynchronizer / RemoveSynchronizer 实现 |
| E10 | `media_sync_manager.cpp` | L62-80 | SetPlaybackRate 播放速率控制（含锚点重置） |
| E11 | `media_sync_manager.cpp` | L117-145 | Pause / Resume 实现（暂停时保存媒体时间） |
| E12 | `media_sync_manager.cpp` | L158-174 | Seek 实现（isSeeking_=true → 触发所有同步器重等待Preroll） |
| E13 | `media_sync_manager.cpp` | L251-275 | UpdateTimeAnchor 核心时间锚点更新（AUDIO_SINK优先） |
| E14 | `media_sync_manager.cpp` | L277-282 | SetLastAudioBufferDuration / SetLastVideoBufferPts |
| E15 | `media_sync_manager.cpp` | L285-299 | CheckSeekingMediaTime / CheckPausedMediaTime 检查链 |
| E16 | `media_sync_manager.cpp` | L304-318 | CheckIfMediaTimeIsNone / CheckFirstMediaTimeAfterSeek 检查链 |
| E17 | `media_sync_manager.cpp` | L323-328 | GetMaxMediaProgress 最大进度计算（音频优先原则） |
| E18 | `media_sync_manager.cpp` | L343-351 | GetMediaTimeNow 四步检查链驱动 |
| E19 | `media_sync_manager.cpp` | L381-385 | GetMediaTime 时间计算公式 |
| E20 | `media_sync_manager.cpp` | L404-418 | ReportPrerolled 全部同步器报告后统一触发NotifyAllPrerolled |
| E21 | `media_sync_manager.cpp` | L421-422 | GetSeekTime / InSeeking |
| E22 | `media_sync_manager.cpp` | L424-430 | SetMediaStartPts / ResetMediaStartPts |
| E23 | `i_media_sync_center.h` | L37-82 | IMediaSyncCenter 完整接口（Reset/AddSynchronizer/UpdateTimeAnchor等） |
| E24 | `media_synchronous_sink.h` | L24-40 | MediaSynchronousSink 基类定义（DoSyncWrite纯虚/prerollCond_） |
| E25 | `media_synchronous_sink.cpp` | L39-47 | Init / ~Init 添加/移除同步器 |
| E26 | `media_synchronous_sink.cpp` | L53-71 | WriteToPluginRefTimeSync（Preroll报告+等待+DoSyncWrite） |
| E27 | `video_sink.cpp` | L59 | LAG_LIMIT_TIME=100ms / VIDEO_SINK_START_FRAME=4 |
| E28 | `video_sink.cpp` | L89-99 | VideoSink UpdateTimeAnchor + SetLastVideoBufferPts |
| E29 | `video_sink.cpp` | L125 | DoSyncWrite 视频帧同步写入 |
| E30 | `video_sink.cpp` | L320 | SetSyncCenter 注入MediaSyncManager |
| E31 | `audio_sink.cpp` | L80/90 | syncerPriority_ = AUDIO_SINK（2，最高优先级） |
| E32 | `audio_sink.cpp` | L988-999 | AudioSink UpdateTimeAnchor 音频主时钟更新 |
| E33 | `audio_sink.cpp` | L1029-1031 | SetLastAudioBufferDuration 音频缓冲时长追踪 |
| E34 | `audio_sink.cpp` | L1358 | AudioLagDetector::CalcLag 音频卡顿检测 |
| E35 | `audio_sink.cpp` | L1400-1406 | AudioLagDetector 使用 syncCenter->GetClockTimeNow() |

---

## 12. 关联主题

- S22（Pipeline整体流程）
- S56（音视频同步基础）
- S98（Sink模块架构）
- S116（MediaSyncManager相关）
- S185（AudioServerSinkPlugin）
- S179（MediaEngine Modules层架构 - MediaSyncManager是其中之一）
- S218（Native Buffer管理 - Buffer与同步关系）
