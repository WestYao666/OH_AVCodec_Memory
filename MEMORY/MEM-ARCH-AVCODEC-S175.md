---
id: MEM-ARCH-AVCODEC-S175
subject: MediaDemuxer PTS自动维护机制——media_demuxer_pts_functions.cpp 219行PTS分段校正与HandleAutoMaintainPts双轨同步
status: draft
created_at: 2026-05-21T21:39:00+08:00
evidence_count: 14
source_files:
  - services/media_engine/modules/demuxer/media_demuxer_pts_functions.cpp
  - services/media_engine/modules/demuxer/media_demuxer.h
git_branch: master
---

# S175｜MediaDemuxer PTS 自动维护机制

## 一、定位与背景

HLS/DASH 等流媒体场景下，分片切换时 PTS 可能发生不连续跳跃（discontinuity）。`media_demuxer_pts_functions.cpp`（219行）实现 PTS 自动维护逻辑，对跳跃进行校正，保证音视频同步。TransCoder 场景使用专用变体。

---

## 二、核心数据结构

### 2.1 MaintainBaseInfo（per-track 状态）

**文件**: `media_demuxer.h:230-237`

```cpp
struct MaintainBaseInfo {
    int64_t segmentOffset = -1;        // 当前分片PTS偏移量
    int64_t basePts = -1;               // 基准PTS
    int64_t candidateBasePts = -1;      // 候选基准PTS（跳跃时）
    int64_t lastPts = 0;                // 上一个样本PTS
    int64_t lastPtsModifyedMax = -1;   // 已校正最大PTS
    bool isLastPtsChange = false;      // 是否处于跳跃状态
};
```

> **Evidence**: `media_demuxer.h:230-237`

### 2.2 核心常量

| 常量 | 值 | 含义 |
|------|-----|------|
| `MAX_PTS_DIFFER_THRESHOLD_US` | 2,000,000 µs = **2s** | 分片切换判定阈值 |
| `INVALID_PTS_DATA` | -1 | 无效 PTS 标记 |
| `PTS_MICRO_ADJUSTMENT_US` | 1000 µs | 微调步长 |
| `LOG_INTERVAL_MS_COUNT` | 2000 ms | 日志节流间隔 |
| `LOG_MAX_PRINTS_COUNT` | 10 次 | 日志最大打印次数 |

> **Evidence**: `media_demuxer_pts_functions.cpp:50-54`

### 2.3 MediaDemuxer 成员变量

**文件**: `media_demuxer.h:548-553`

```cpp
std::atomic<bool> isAutoMaintainPts_ {false};                                    // L548: 自动维护开关
std::map<int32_t, std::shared_ptr<MaintainBaseInfo>> maintainBaseInfos_;           // L549: per-track状态
std::map<int32_t, int64_t> currentSegmentOffsetMap_;                             // L550: per-track分片偏移
std::mutex segmentOffsetMutex_;                                                   // L551: 线程安全锁
int64_t mediaStartPts_ {HST_TIME_NONE};                                          // L552: 起播PTS基准
int64_t transcoderStartPts_ {HST_TIME_NONE};                                     // L553: TransCoder专用基准
```

---

## 三、核心函数

### 3.1 HandleAutoMaintainPts（核心校正逻辑）

**文件**: `media_demuxer_pts_functions.cpp:56-107`

函数签名：
```cpp
void MediaDemuxer::HandleAutoMaintainPts(int32_t trackId, std::shared_ptr<AVBuffer> sample)
```

**三段分支逻辑**：

**分支1**（L75-81）：首次进入分片，初始化偏移
```cpp
if (baseInfo->segmentOffset == INVALID_PTS_DATA) {
    int64_t offset = GetCurrentSegmentOffset(trackId, baseInfo->segmentOffset);
    if (baseInfo->segmentOffset != offset) {
        baseInfo->segmentOffset = offset;
        baseInfo->basePts = curPacketPts;
    }
    sample->pts_ = baseInfo->segmentOffset + curPacketPts - baseInfo->basePts + mediaStartPts_; // L81
}
```

**分支2**（L82-96）：检测到 2s 以上跳跃，两步处理
```cpp
else if (diff > MAX_PTS_DIFFER_THRESHOLD_US) { // L82: 2s阈值
    if (baseInfo->isLastPtsChange) {          // 第二次确认跳跃
        int64_t offset = GetCurrentSegmentOffset(trackId, baseInfo->segmentOffset);
        baseInfo->segmentOffset = offset;
        baseInfo->basePts = baseInfo->candidateBasePts;
        sample->pts_ = baseInfo->segmentOffset + curPacketPts - baseInfo->basePts + mediaStartPts_; // L89
        baseInfo->isLastPtsChange = false;
    } else {                                  // 第一次检测到跳跃，候选
        sample->pts_ = baseInfo->lastPtsModifyedMax + PTS_MICRO_ADJUSTMENT_US; // L92: 微调
        baseInfo->candidateBasePts = curPacketPts;
        baseInfo->isLastPtsChange = true;     // L94: 标记等待第二次确认
        baseInfo->lastPts = oldPts;
    }
}
```

**分支3**（L97-100）：正常情况，直接校正
```cpp
else {
    sample->pts_ = baseInfo->segmentOffset + curPacketPts - baseInfo->basePts + mediaStartPts_; // L98
    baseInfo->isLastPtsChange = false;
}
```

L101：更新最大PTS
```cpp
baseInfo->lastPtsModifyedMax = std::max(sample->pts_, baseInfo->lastPtsModifyedMax);
```

> **Evidence**: `media_demuxer_pts_functions.cpp:56-107`

**设计要点**：
- **两步确认**：2s 跳跃需要连续两次检测才正式采纳，防止误触
- **微调策略**：第一次跳跃只给出一个微调 PTS（+1ms），不直接跳变
- **per-track 隔离**：每个 trackId 独立 MaintainBaseInfo，支持多轨

---

### 3.2 InitPtsInfo（HLS 初始化）

**文件**: `media_demuxer_pts_functions.cpp:109-128`

```cpp
void MediaDemuxer::InitPtsInfo()
{
    if (source_ == nullptr || !isHls_) {  // L111: 仅HLS启用
        return;
    }
    MEDIA_LOG_I("Enable hls disContinuity auto maintain pts");
    isAutoMaintainPts_.store(true);        // L115: 开启自动维护
    AutoLock lock(mapMutex_);
    for (auto it = bufferQueueMap_.begin(); it != bufferQueueMap_.end(); it++) {
        int32_t trackId = it->first;
        if (maintainBaseInfos_[trackId] == nullptr) {
            maintainBaseInfos_[trackId] = std::make_shared<MaintainBaseInfo>(); // L120
        }
        maintainBaseInfos_[trackId]->segmentOffset = INVALID_PTS_DATA;           // L122
        maintainBaseInfos_[trackId]->basePts = INVALID_PTS_DATA;               // L123
        maintainBaseInfos_[trackId]->isLastPtsChange = false;                  // L124
        maintainBaseInfos_[trackId]->lastPtsModifyedMax = INVALID_PTS_DATA;    // L125
        SetCurrentSegmentOffset(trackId, source_->GetSegmentOffset());          // L126
    }
}
```

> **Evidence**: `media_demuxer_pts_functions.cpp:109-128`

---

### 3.3 InitMediaStartPts（起播初始化）

**文件**: `media_demuxer_pts_functions.cpp:130-147`

```cpp
void MediaDemuxer::InitMediaStartPts()
{
    for (const auto& trackInfo : mediaMetaData_.trackMetas) {
        if (trackInfo == nullptr || !(trackInfo->GetData(Tag::MIME_TYPE, mime))) {
            continue;
        }
        if (!(mime.find("audio/") == 0 || mime.find("video/") == 0)) {
            continue;
        }
        if (trackInfo->GetData(Tag::MEDIA_START_TIME, startTime) &&
            (mediaStartPts_ == HST_TIME_NONE || startTime < mediaStartPts_)) { // L143
                mediaStartPts_ = startTime;                                   // L144: 取所有轨道最早时间
        }
    }
}
```

> **Evidence**: `media_demuxer_pts_functions.cpp:130-147`

---

### 3.4 TranscoderInitMediaStartPts（TransCoder 专用初始化）

**文件**: `media_demuxer_pts_functions.cpp:149-178`

```cpp
void MediaDemuxer::TranscoderInitMediaStartPts()
{
    // L151: Init media start time based on the first video track and the first audio track
    bool isInitVideoStartTime = false;
    bool isInitAudioStartTime = false;
    for (const auto& trackInfo : mediaMetaData_.trackMetas) {
        // ...
        if (!isInitVideoStartTime && (mime.find("video/") == 0)) {
            isInitVideoStartTime = true;
            if (transcoderStartPts_ == HST_TIME_NONE || startTime < transcoderStartPts_) {
                transcoderStartPts_ = startTime;                             // L165: 首个视频轨
            }
        } else if (!isInitAudioStartTime && (mime.find("audio/") == 0)) {
            isInitAudioStartTime = true;
            if (transcoderStartPts_ == HST_TIME_NONE || startTime < transcoderStartPts_) {
                transcoderStartPts_ = startTime;                             // L171: 首个音轨
            }
        }
        if (isInitAudioStartTime && isInitVideoStartTime) {
            break;                                                          // L174: 只取第一个视频+第一个音频
        }
    }
}
```

> **Evidence**: `media_demuxer_pts_functions.cpp:149-178`

**与 InitMediaStartPts 的区别**：
- 普通播放取所有轨道中最早时间
- TransCoder **只取第一个视频轨 + 第一个音频轨**，不采集字幕/元数据轨
- 使用 `transcoderStartPts_` 而非 `mediaStartPts_`

---

### 3.5 UpdateSegmentOffset（码率切换时更新）

**文件**: `media_demuxer_pts_functions.cpp:180-197`

```cpp
void MediaDemuxer::UpdateSegmentOffset(int32_t trackId)         // L180: 单track更新
{
    FALSE_RETURN_NOLOG(isAutoMaintainPts_.load());
    auto offset = source_->GetSegmentOffset();
    SetCurrentSegmentOffset(trackId, offset);
    FALSE_GOON_NOEXEC(IsAVInOneStream() && trackId == videoTrackId_,
        SetCurrentSegmentOffset(audioTrackId_, offset)); // L187: 音视频同流时同步更新音频track
}

void MediaDemuxer::UpdateSegmentOffset(int32_t oldTrackId, int32_t newTrackId) // L190: track切换
{
    FALSE_RETURN_NOLOG(isAutoMaintainPts_.load());
    auto offset = source_->GetSegmentOffset();
    SetCurrentSegmentOffset(newTrackId, GetCurrentSegmentOffset(oldTrackId, offset)); // L196
}
```

> **Evidence**: `media_demuxer_pts_functions.cpp:180-197`

---

### 3.6 SetCurrentSegmentOffset / GetCurrentSegmentOffset（线程安全读写）

**文件**: `media_demuxer_pts_functions.cpp:199-217`

```cpp
void MediaDemuxer::SetCurrentSegmentOffset(int32_t trackId, size_t segmentOffset) // L199
{
    FALSE_RETURN_NOLOG(IsValidTrackId(trackId));
    std::lock_guard<std::mutex> lock(segmentOffsetMutex_); // L204: 线程安全锁
    int64_t max = std::numeric_limits<int64_t>::max();
    currentSegmentOffsetMap_[trackId] =
        (segmentOffset > static_cast<size_t>(max)) ? max : static_cast<int64_t>(segmentOffset); // L206-207
}

int64_t MediaDemuxer::GetCurrentSegmentOffset(int32_t trackId, int64_t oldSegmentOffset) // L210
{
    FALSE_RETURN_V_NOLOG(isAutoMaintainPts_.load(), oldSegmentOffset);
    std::lock_guard<std::mutex> lock(segmentOffsetMutex_); // L214: 线程安全锁
    FALSE_RETURN_V_NOLOG(currentSegmentOffsetMap_.find(trackId) != currentSegmentOffsetMap_.end(), oldSegmentOffset);
    return currentSegmentOffsetMap_[trackId];
}
```

> **Evidence**: `media_demuxer_pts_functions.cpp:199-217`

---

## 四、PTS 校正公式

```
校正PTS = segmentOffset + curPacketPts - basePts + mediaStartPts_
```

| 变量 | 含义 |
|------|------|
| `segmentOffset` | 当前分片偏移量（GetSegmentOffset()） |
| `curPacketPts` | 样本原始 PTS |
| `basePts` | 该分片的基准 PTS（首次进入分片时记录） |
| `mediaStartPts_` | 起播时间基准（InitMediaStartPts） |

---

## 五、关联分析

| 关联主题 | 关系 |
|---------|------|
| S69/S75（MediaDemuxer 六组件/ReadLoop） | 调用 HandleAutoMaintainPts 的上游框架 |
| S101（StreamDemuxer PullData 分片缓存） | 分片 offset 来源 |
| S106/S122（Source HLS 分片下载） | HLS 分片管理，调用 InitPtsInfo |
| S139（SampleQueue 流控架构） | HandleAutoMaintainPts 作用于 SampleQueue 中的 AVBuffer |
| S149（Transcoder Pipeline） | TranscoderInitMediaStartPts 的调用方 |

---

## 六、关键结论

1. **PTS 自动维护仅针对 HLS 启用**（`isHls_` 判断）——普通 MP4 文件不解锁此逻辑
2. **2s 阈值跳跃需要两步确认**：防止误触发，第一次仅微调 +1ms，第二次才正式更新 basePts
3. **TransCoder 使用独立变量** `transcoderStartPts_`，只采集第一个视频轨 + 第一个音频轨
4. **segmentOffsetMutex_ 锁保证线程安全**，但 GetCurrentSegmentOffset 也需要锁（可重入场景）
5. **音视频同流时自动同步**（`IsAVInOneStream()`），码率切换同时更新 videoTrackId + audioTrackId

---

## status

```
status: draft
pending_approval: MEM-ARCH-AVCODEC-S175
submitted_at: 2026-05-21T21:39:00+08:00
```