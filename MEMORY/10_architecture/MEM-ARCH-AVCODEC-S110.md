---
id: MEM-ARCH-AVCODEC-S110
title: "MediaSyncManager 时钟同步管理器——IMediaSyncCenter 时钟锚点与音视频同步机制"
scope: [AVCodec, MediaEngine, Sink, MediaSyncManager, IMediaSyncCenter, IMediaSynchronizer, TimeAnchor, ClockSync, PlaybackControl]
status: draft
approved_at: ~pending~
approved_by: ~pending~
approval_submitted_at: ~pending~
created_by: builder-agent
created_at: "2026-05-09T12:55:00+08:00"
关联主题: [S100(PostProcessor), S109(MediaMuxer), S102(SampleQueueController), S41(DemuxerFilter)]
---

## Status

```yaml
status: draft
created: 2026-05-09T12:55
builder: builder-agent
source: /home/west/av_codec_repo/services/media_engine/modules/sink/media_sync_manager.cpp (491行)
         /home/west/av_codec_repo/services/media_engine/modules/sink/i_media_sync_center.h
         /home/west/av_codec_repo/services/media_engine/modules/sink/media_synchronous_sink.h
```

## 主题

MediaSyncManager 时钟同步管理器——IMediaSyncCenter 时钟锚点与音视频同步机制

## 标签

AVCodec, MediaEngine, Sink, MediaSyncManager, IMediaSyncCenter, IMediaSynchronizer, TimeAnchor, ClockSync, PlaybackControl, Pause, Seek, PlayRate

## 关联记忆

- S102 (SampleQueueController)：流控引擎与 MediaSyncManager 同步控制（PlayRate/Speed）
- S109 (MediaMuxer)：写出的媒体数据依赖 MediaSyncManager 时钟同步
- S100 (PostProcessor)：VPE 后处理依赖同步时钟驱动渲染
- S41 (DemuxerFilter)：消费端Sink与 MediaSyncManager 共同完成播放控制
- S106 (Source)：时钟锚点驱动数据拉取速度

## 摘要

`MediaSyncManager` (491行 cpp) 是 Pipeline 中的**全局时钟同步管理器**，实现 `IMediaSyncCenter` 接口，管理所有音视频同步器（IMediaSynchronizer）的时钟锚点（TimeAnchor）。核心职责：

1. **时钟锚点管理**：`UpdateTimeAnchor` 建立 PTS ↔ 系统时钟的映射关系
2. **音视频同步**：多路 IMediaSynchronizer（VideoSink/AudioSink）按优先级（Priority）协同
3. **播放控制**：Pause/Seek/PlayRate 改变时钟轴，影响整体 Pipeline 节奏
4. **Preroll 协调**：`WaitAllPrerolled` 阻塞直到所有 Sink 完成首帧渲染
5. **速度控制**：`SetPlaybackRate` 快放/慢放影响 GetMediaTimeNow 推进速度

---

## Evidence（源码行号）

### IMediaSyncCenter 接口（i_media_sync_center.h）

| 符号 | 位置 | 说明 |
|------|------|------|
| `struct IMediaSynchronizer` | i_media_sync_center.h:18-26 | Sink/Source 同步器基类（优先级常量） |
| `NONE = -1` | i_media_sync_center.h:19 | 无效同步器 |
| `VIDEO_SINK = 0` | i_media_sync_center.h:20 | 视频 Sink 优先级 |
| `AUDIO_SINK = 2` | i_media_sync_center.h:21 | 音频 Sink 优先级（最低，比 VIDEO_SINK 高） |
| `VIDEO_SRC = 4` | i_media_sync_center.h:22 | 视频 Source 优先级 |
| `AUDIO_SRC = 6` | i_media_sync_center.h:23 | 音频 Source 优先级 |
| `SUBTITLE_SINK = 8` | i_media_sync_center.h:24 | 字幕 Sink 优先级 |
| `struct IMediaSyncCenter` | i_media_sync_center.h:27-75 | 时钟同步中心主接口 |
| `AddSynchronizer(IMediaSynchronizer*)` | i_media_sync_center.h:31 | 注册同步器 |
| `UpdateTimeAnchor(clockTime, delayTime, IMediaTime, supplier)` | i_media_sync_center.h:37 | 更新时钟锚点 |
| `GetMediaTimeNow()` | i_media_sync_center.h:47 | 获取当前媒体时间 |
| `GetClockTimeNow()` | i_media_sync_center.h:52 | 获取当前系统时钟时间 |
| `GetAnchoredClockTime(mediaTime)` | i_media_sync_center.h:56 | 将媒体时间映射到时钟时间 |
| `ReportPrerolled(supplier)` | i_media_sync_center.h:62 | 报告首帧渲染完成 |
| `SetPlaybackRate(rate)` | i_media_sync_center.h:69 | 设置播放速率 |
| `SetMediaStartPts(startPts)` | i_media_sync_center.h:73 | 设置媒体起始 PTS |

### MediaSyncManager 实现（media_sync_manager.cpp 491行）

| 符号 | 位置 | 说明 |
|------|------|------|
| `AddSynchronizer(syncer)` | media_sync_manager.cpp:42 | 注册同步器到 syncers_ vector |
| `RemoveSynchronizer(syncer)` | media_sync_manager.cpp:51 | 从 syncers_ 移除同步器 |
| `Pause()` | media_sync_manager.cpp:153 | 暂停播放，更新 pausedMediaTime_ |
| `Seek(mediaTime, isClosest)` | media_sync_manager.cpp:165-209 | Seek 操作，重置锚点，标记 isSeeking_ |
| `SimpleUpdateTimeAnchor(clockTime, mediaTime)` | media_sync_manager.cpp:226-237 | 简化锚点更新（Seek 后清理） |
| `UpdateTimeAnchor(...)` | media_sync_manager.cpp:249-280 | 完整锚点更新（带延时处理） |
| `UpdateFirstPtsAfterSeek(mediaTime)` | media_sync_manager.cpp:238-246 | 记录 Seek 后首帧 PTS |
| `CheckSeekingMediaTime(mediaTime)` | media_sync_manager.cpp:290-298 | Seek 状态检查 |
| `CheckPausedMediaTime(mediaTime)` | media_sync_manager.cpp:299-310 | 暂停状态检查 |
| `CheckFirstMediaTimeAfterSeek(mediaTime)` | media_sync_manager.cpp:312-319 | Seek 后首帧时间检查 |
| `GetMediaTimeNow()` | media_sync_manager.cpp:352-364 | 获取当前媒体时间（带 speed_ 倍速） |
| `GetClockTimeNow()` | media_sync_manager.cpp:365-375 | 获取当前系统时钟 |
| `GetAnchoredClockTime(mediaTime)` | media_sync_manager.cpp:392-410 | PTS → 时钟时间映射 |
| `IsPlayRateValid(playRate)` | media_sync_manager.cpp:376-386 | 速率校验（0.5x-4x） |
| `ReportPrerolled(supplier)` | media_sync_manager.cpp:（待补充） | 报告首帧完成 |
| `ReportEos(supplier)` | media_sync_manager.cpp:（待补充） | 报告播放结束 |

## 架构定位

```
Pipeline 播放引擎
    ├── MediaSyncManager（IMediaSyncCenter 单例）
    │       ├── 管理 syncers_ vector<IMediaSynchronizer*>
    │       ├── 时钟锚点：clockTime_ ↔ mediaTime_ 映射表
    │       ├── 全局状态：isSeeking_ / isPaused_ / playRate_ / speed_
    │       └── 关键变量：currentMediaTime_ / pausedMediaTime_ / firstMediaTimeAfterSeek_
    │
    ├── MediaSynchronousSink（Video/Audio Sink 基类）
    │       ├── 实现 IMediaSynchronizer 接口
    │       ├── GetPriority() 返回 VIDEO_SINK(0) / AUDIO_SINK(2)
    │       ├── DoSyncWrite() 实际写入（子类实现）
    │       └── WaitAllPrerolled() 等待首帧渲染
    │
    └── Pipeline Filter Chain
            ├── Source(S106) → DemuxerFilter(S41) → Decoder
            ├── MediaSyncManager 控制播放节奏
            └── MediaSynchronousSink 消费解码后数据
```

## 核心设计

### 1. 时钟锚点机制（Time Anchor）

**核心映射**：`mediaTime ↔ clockTime`

```cpp
void MediaSyncManager::UpdateTimeAnchor(int64_t clockTime, int64_t delayTime,
    IMediaTime iMediaTime, IMediaSynchronizer* supplier)
{
    // 1. 更新锚点
    SimpleUpdateTimeAnchor(clockTime, iMediaTime.mediaTime);
    
    // 2. Seek 状态特殊处理
    if (isSeeking_) {
        isSeeking_ = false;
        isFrameAfterSeeked_ = true;
        UpdateFirstPtsAfterSeek(iMediaTime.mediaTime);
    }
    
    // 3. 更新延时（delayTime 预渲染延时）
}
```

**锚点作用**：建立 "媒体时间 PTS" 和 "系统时钟" 的对应关系，用于：
- `GetMediaTimeNow()`：根据流逝的 wall-clock time 计算当前 mediaTime
- `GetAnchoredClockTime(mediaTime)`：已知目标 PTS，计算应该的 wall-clock 时间

### 2. IMediaSynchronizer 优先级体系

```cpp
struct IMediaSynchronizer {
    const static int8_t NONE = -1;
    const static int8_t VIDEO_SINK = 0;      // 最高优先级
    const static int8_t AUDIO_SINK = 2;       // 音频次高
    const static int8_t VIDEO_SRC = 4;         // 视频源
    const static int8_t AUDIO_SRC = 6;         // 音频源
    const static int8_t SUBTITLE_SINK = 8;    // 字幕最低
};
```

**优先级作用**：
- `GetPriority()`：各 Sink 返回自己的优先级
- **音频优先原则**：`AUDIO_SINK(2) < VIDEO_SINK(0)`，音频为主时钟（更稳定）
- `WaitAllPrerolled`：等待所有 Sink 的首帧渲染完成后才解除阻塞

### 3. Preroll 协调机制

```cpp
void MediaSynchronousSink::WaitAllPrerolled(bool shouldWait) {
    if (shouldWait) {
        prerollCond_.wait(prerollMutex_, [&] { return hasReportedPrerolled_; });
    }
}

void MediaSyncManager::ReportPrerolled(IMediaSynchronizer* supplier) {
    // 记录 supplier 已完成 preroll
    // 当所有 syncers_ 都 report 后，解除所有 WaitAllPrerolled 阻塞
}
```

**目的**：在开始播放前，确保所有 Sink（Video/Audio）已完成首帧渲染，避免黑屏/无声。

### 4. 播放控制（Pause/Seek/Speed）

**Pause**：
```cpp
Status MediaSyncManager::Pause() {
    pausedMediaTime_ = currentMediaTime_;  // 记录暂停时的 PTS
    SimpleUpdateTimeAnchor(HST_TIME_NONE, HST_TIME_NONE);  // 清除锚点
}
```

**Seek**：
```cpp
Status MediaSyncManager::Seek(int64_t mediaTime, bool isClosest) {
    isSeeking_ = true;
    // ... 处理最近关键帧 ...
    isSeeking_ = false;
    firstMediaTimeAfterSeek_ = mediaTime;
    isFrameAfterSeeked_ = true;
}
```

**SetPlaybackRate**：
```cpp
int64_t MediaSyncManager::GetMediaTimeNow() {
    if (isPaused_) return pausedMediaTime_;
    if (isSeeking_) return seekingMediaTime_;
    // currentMediaTime_ + (clockTimeNow - anchorClockTime_) * playRate_
}
```

### 5. 多 Sink 同步器管理

```cpp
void MediaSyncManager::AddSynchronizer(IMediaSynchronizer* syncer) {
    std::find(syncers_.begin(), syncers_.end(), syncer);
    syncers_.emplace_back(syncer);
}
```

**设计**：非侵入式，所有 Sink/Source 自由注册/注销，通过指针数组管理。

### 6. 时钟时间计算公式

```
GetMediaTimeNow():
    if (isPaused_) return pausedMediaTime_
    if (isSeeking_) return seekingMediaTime_
    elapsedClock = GetClockTimeNow() - anchorClockTime_
    currentMediaTime = anchorMediaTime + elapsedClock * playRate_

GetAnchoredClockTime(mediaTime):
    if (mediaTime < anchorMediaTime) return anchorClockTime
    elapsedMedia = mediaTime - anchorMediaTime
    return anchorClockTime + elapsedMedia / playRate_
```

---

## 关键设计决策

1. **时钟锚点分离**：anchor clockTime 和 anchor mediaTime 分开存储，支持 pause/resume
2. **音频为主时钟**：AUDIO_SINK(2) < VIDEO_SINK(0)，音频同步更稳定（采样率固定）
3. **Preroll 两阶段**：WaitAllPrerolled 阻塞主线程，直到所有 Sink ReportPrerolled
4. **PlayRate 实时生效**：GetMediaTimeNow 乘以 playRate，支持 0.5x/1x/2x/4x
5. **isSeeking 原子状态**：Seek 期间 isSeeking_=true，防止并发时间查询
6. **firstMediaTimeAfterSeek**：记录 Seek 后首帧 PTS，用于精确的时间恢复

## 关联场景

- **播放卡顿**：GetMediaTimeNow 返回值跳变 → 检查 anchorClockTime 是否正确更新
- **音画不同步**：Video Sink 的 DoSyncWrite 延迟 → MediaSyncManager 的 delayTime 参数
- **Seek 操作**：Seek 后媒体时间重置 → firstMediaTimeAfterSeek_ 记录新基准
- **快放/慢放**：SetPlaybackRate 2x → GetMediaTimeNow 以 2x 速度推进
- **首帧黑屏**：Preroll 未完成 → WaitAllPrerolled 超时，可能 prerollCond_ 未正确 Signal

## 与 SampleQueueController 对比

| 维度 | MediaSyncManager（S110） | SampleQueueController（S102） |
|------|------|------|
| 层级 | Pipeline 全局单例 | MediaDemuxer 内部组件 |
| 职责 | 时钟同步 + 播放控制 | 流控 + 生产/消费节奏 |
| 核心变量 | clockTime ↔ mediaTime 锚点 | produce/consume SpeedCountInfo |
| 控制对象 | 全体 Sink/Source | ReadLoop / SampleConsumerLoop TaskThread |
| 关联状态 | isSeeking / isPaused / playRate | WaterLine 阈值（5μs/10μs） |

## 内存占用分析

- `syncers_` vector：每个 Sink/Source 一个指针（可忽略）
- `mediaTime_` / `clockTime_` 等 int64_t 变量：固定 8 字节 × 若干
- `IMediaTime` struct：3 × int64_t = 24 字节
- 总计极小，主要占用为 `std::mutex` / `std::condition_variable` 同步原语
