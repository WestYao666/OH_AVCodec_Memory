---
id: MEM-ARCH-AVCODEC-S22
title: MediaSyncManager 音视频同步管理中心——IMediaSyncCenter时间锚点与IMediaSynchronizer优先级同步链
status: pending_approval
created_at: "2026-04-24T10:37:00Z"
scope: [AVCodec, MediaEngine, Sync, MediaSyncManager, IMediaSyncCenter, PTS, AVSync, Clock]
---
## 一、核心问题
**MediaSyncManager**（`services/media_engine/modules/sink/media_sync_manager.cpp`）是 HiStreamer Pipeline 的音视频同步核心组件，负责：
1. **时间锚点管理**：`UpdateTimeAnchor` 建立 PTS（媒体时间）与系统时钟的映射关系
2. **AV 同步协调**：通过 `IMediaSynchronizer` 接口管理 Video Sink / Audio Sink / Video Source / Audio Source 四类同步器，按优先级（`GetPriority()`）决定谁主导时钟
3. **播放控制**：Pause / Resume / Seek / PlaybackRate 多状态切换
4. **Preroll 协调**：`WaitAllPrerolled` / `NotifyAllPrerolled` 确保所有同步器在首帧渲染前等待
5. **PTS 换算**：`GetAnchoredClockTime` / `GetMediaTimeNow` 实现 PTS → 系统时钟的双向换算，支持 Seek 操作

**核心矛盾**：Demuxer Filter 以 PTS 推送数据，渲染器以系统时钟播放，MediaSyncManager 是这两者之间的"翻译器"。

## 二、关键代码路径

### 核心类

| 类名 | 文件路径 | 职责 |
|------|---------|------|
| `MediaSyncManager` | `interfaces/inner_api/native/media_sync_manager.h` + `services/media_engine/modules/sink/media_sync_manager.cpp` | 同步中心，实现 `IMediaSyncCenter` |
| `IMediaSyncCenter` | `interfaces/inner_api/native/i_media_sync_center.h` | 同步中心抽象接口 |
| `IMediaSynchronizer` | `interfaces/inner_api/native/i_media_sync_center.h` | 同步器抽象接口（被 Sink/Source 实现） |
| `MediaSynchronousSink` | `services/media_engine/modules/sink/media_synchronous_sink.h` | 同步渲染基类，实现 `IMediaSynchronizer` |
| `VideoSink` | `services/media_engine/modules/sink/video_sink.cpp` | 视频渲染器，同步消费者 |
| `AudioSink` | `services/media_engine/modules/sink/audio_sink.cpp` | 音频渲染器，同步消费者 |
| `TimeAndIndexConversion` | `services/media_engine/modules/pts_index_conversion/pts_and_index_conversion.cpp` | MP4/MOV 的 PTS↔Index 换算 |

### 关键方法签名

```cpp
// IMediaSyncCenter 接口（media_sync_manager.h）
bool UpdateTimeAnchor(int64_t clockTime, int64_t delayTime, IMediaTime iMediaTime,
    IMediaSynchronizer* supplier);  // 建立时间锚点
int64_t GetMediaTimeNow() override;  // 当前媒体时间
int64_t GetClockTimeNow() override;  // 当前系统时钟
int64_t GetAnchoredClockTime(int64_t mediaTime) override;  // PTS→时钟换算
void AddSynchronizer(IMediaSynchronizer* syncer) override;  // 注册同步器
void ReportPrerolled(IMediaSynchronizer* supplier) override;  // 首帧报到
Status Seek(int64_t mediaTime, bool isClosest = false);  // 跳转
Status SetPlaybackRate(float rate) override;  // 倍速

// IMediaSynchronizer 接口
int8_t GetPriority();  // 优先级：VIDEO_SINK=0, AUDIO_SINK=2, VIDEO_SRC=4, AUDIO_SRC=6
void WaitAllPrerolled(bool shouldWait);
void NotifyAllPrerolled();
```

## 三、数据流 / 状态机

### 同步器优先级链

```
IMediaSynchronizer GetPriority() 返回值:
  VIDEO_SINK    = 0   ← 最高优先级（通常由视频主导时钟）
  AUDIO_SINK    = 2   
  VIDEO_SRC     = 4   
  AUDIO_SRC     = 6   ← 最低优先级
  NONE         = -1
```

### 时间锚点建立流程

```
1. VideoSink 收到第一帧 → ReportPrerolled(syncer)
2. 所有同步器 Prerolled 后 → WaitAllPrerolled(false) 解除阻塞
3. VideoSink 渲染帧时 → UpdateTimeAnchor(clockTime, delayTime, {mediaTime, absMediaTime, maxMediaTime}, syncer)
4. MediaSyncManager 记录: currentAnchorClockTime_ / currentAnchorMediaTime_
5. 其他同步器查询 → GetMediaTimeNow() / GetAnchoredClockTime(pts)
```

### MediaSyncManager 状态机

```
状态: RESUMED ←→ PAUSED
isSeeking_ ∈ {true, false}

关键状态组合:
- RESUMED + !isSeeking_: 正常播放，MediaTime = AnchorMediaTime + (ClockTime - AnchorClockTime) * PlayRate
- PAUSED + !isSeeking_: 暂停，MediaTime = pausedMediaTime_
- RESUMED + isSeeking_: Seek 中，MediaTime = seekingMediaTime_
- 任意 + isSeeking_: Seek 结束后触发 UpdateTimeAnchor，切换到 RESUMED + !isSeeking_
```

### PTS 换算公式

```cpp
// GetMediaTimeNow() 核心逻辑（media_sync_manager.cpp）
int64_t MediaSyncManager::GetMediaTime(int64_t clockTime) {
    return currentAnchorMediaTime_ + (clockTime - currentAnchorClockTime_) * playRate_;
}
```

### Seek 流程

```
Seek(mediaTime) → isSeeking_=true → 各同步器丢弃旧数据
→ Demuxer 跳转到对应位置 → 新数据到达
→ UpdateTimeAnchor(新clockTime, 新mediaTime) → isSeeking_=false
→ 恢复 GetMediaTimeNow() 正常换算
```

## 四、关联场景

| 场景 | 涉及类 |
|------|--------|
| 视频播放正常 AV 同步 | MediaSyncManager + VideoSink + AudioSink |
| Seek 操作 PTS 换算 | MediaSyncManager + TimeAndIndexConversion |
| 音频主导（无视频） | MediaSyncManager + AudioSink（priority=2） |
| 倍速播放 | MediaSyncManager.SetPlaybackRate + UpdateTimeAnchor |
| 首帧等待（Preroll） | MediaSyncManager.WaitAllPrerolled + NotifyAllPrerolled |
| 解码器丢帧（SmartFluencyDecoding） | MediaSyncManager + S17 AsyncDropDispatcher |
| Pipeline 暂停/恢复 | MediaSyncManager.Pause/Resume |

## 五、证据

```cpp
// IMediaSynchronizer 优先级定义（i_media_sync_center.h）
struct IMediaSynchronizer {
    const static int8_t NONE = -1;
    const static int8_t VIDEO_SINK = 0;    // 视频主导时钟
    const static int8_t AUDIO_SINK = 2;
    const static int8_t VIDEO_SRC = 4;
    const static int8_t AUDIO_SRC = 6;
    const static int8_t SUBTITLE_SINK = 8;
    virtual int8_t GetPriority() = 0;
    virtual void WaitAllPrerolled(bool shouldWait) = 0;
    virtual void NotifyAllPrerolled() = 0;
};

// MediaSyncManager.AddSynchronizer（media_sync_manager.cpp）
void MediaSyncManager::AddSynchronizer(IMediaSynchronizer* syncer) {
    OHOS::Media::AutoLock lock(syncersMutex_);
    syncers_.emplace_back(syncer);
}

// MediaSyncManager.UpdateTimeAnchor 核心锚点更新
bool MediaSyncManager::UpdateTimeAnchor(int64_t clockTime, int64_t delayTime, IMediaTime iMediaTime,
    IMediaSynchronizer* supplier) {
    currentAnchorClockTime_ = clockTime;
    currentAnchorMediaTime_ = iMediaTime.mediaTime;
    // ...
}

// TimeAndIndexConversion MP4 PTS→Index（pts_and_index_conversion.cpp）
Status TimeAndIndexConversion::GetPtsFromFileOffset(uint64_t offset, uint64_t& pts);
Status TimeAndIndexConversion::GetFileOffsetFromPts(uint64_t pts, uint64_t& offset);
```

### 目录索引

```
services/media_engine/modules/sink/
├── media_sync_manager.cpp          # MediaSyncManager 实现
├── media_sync_manager.h            # （位于 interfaces/inner_api/native/）
├── media_synchronous_sink.h        # MediaSynchronousSink 基类
├── i_media_sync_center.h           # IMediaSyncCenter + IMediaSynchronizer 接口
├── video_sink.cpp
├── audio_sink.cpp
└── media_sync_manager.cpp          # 实现文件

services/media_engine/modules/pts_index_conversion/
└── pts_and_index_conversion.cpp    # MP4/MOV PTS↔Index 换算器
```
