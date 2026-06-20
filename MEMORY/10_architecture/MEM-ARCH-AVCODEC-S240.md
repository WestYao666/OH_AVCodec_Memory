# MEM-ARCH-AVCODEC-S240 — MediaSyncManager 媒体同步管理中心

> **状态**: pending_approval
> **生成时间**: 2026-06-20 19:47 CST+8
> **增强时间**: 2026-06-20 23:15 CST+8（GitCode web_fetch 验证）
> **Builder**: builder-agent (subagent)
> **源码**: 基于本地镜像 `/home/west/av_codec_repo` + GitCode web_fetch 交叉验证
> **evidence**: 35条行号级evidence（E1-E35）
> **关联**: S22/S56/S98/S116/S185/S179/S218

---

## 概述

MediaSyncManager 是 OH_AVCodec/MediaSync pipeline 的**媒体同步时钟管理中心**，负责：
- 音视频时间同步（AV Sync）
- 播放速率控制（PlaybackRate）
- 暂停/恢复/Seek 状态管理
- Preroll 缓冲同步（所有轨道首帧就绪后统一开始播放）
- 媒体时间范围边界（防止音视频时间回退或超前）

**关联主题**：S22（Pipeline整体流程）/ S98（Sink模块）/ S56（音视频同步）/ S116（MediaSync相关）/ S185（AudioServerSink）

---

## 核心架构

### IMediaSynchronizer 优先级体系

| 同步器 | 优先级 | 说明 |
|--------|--------|------|
| AUDIO_SINK | 2 | **最高**（音频主时钟） |
| VIDEO_SINK | 0 | 次高 |
| VIDEO_SRC | 4 | 中 |
| AUDIO_SRC | 6 | 中 |
| SUBTITLE_SINK | 8 | 最低 |

**设计原则**：音频作为主时钟源，优先级最高，确保音视频同步以音频为基准。

### 时间锚点机制

```
mediaTime = currentAnchorMediaTime_ + (clockTime - currentAnchorClockTime_ + delayTime_) × playRate_ - delayTime_
```

### 四步检查链 GetMediaTimeNow

1. `CheckSeekingMediaTime` — Seek中返回 seekingMediaTime_
2. `CheckPausedMediaTime` — 暂停时返回 pausedMediaTime_
3. `CheckIfMediaTimeIsNone` — 无效时间返回0
4. `CheckFirstMediaTimeAfterSeek` — Seek后首帧同步

---

## Evidence（35条行号级）

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

## 关键设计

1. **音频主时钟原则**：AUDIO_SINK=2 最高优先级，确保音视频同步以音频为基准
2. **时间锚点四元组**：(currentAnchorClockTime_, currentAnchorMediaTime_, delayTime_, playRate_)
3. **Preroll统一触发**：所有同步器报告首帧后统一 NotifyAllPrerolled
4. **Seek重置链**：isSeeking_ → 重置 Preroll → 重置锚点 → 等待首帧
5. **卡顿检测**：VideoSink LAG_LIMIT_TIME=100ms；AudioSink AudioLagDetector
6. **变速播放**：SetPlaybackRate 切换前重设锚点防止跳帧

---

## 关联主题

- S22（Pipeline整体流程）
- S56（音视频同步基础）
- S98（Sink模块架构）
- S116（MediaSyncManager相关）
- S185（AudioServerSinkPlugin）
- S179（MediaEngine Modules层架构 - MediaSyncManager是其中之一）
- S218（Native Buffer管理 - Buffer与同步关系）