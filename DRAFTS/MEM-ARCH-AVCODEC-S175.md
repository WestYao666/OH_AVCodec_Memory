---
mem_id: MEM-ARCH-AVCODEC-S175
title: MediaDemuxer PTS自动维护架构——HLS断点 PTS连续性 / segmentOffset / videoAudioBasePtsDiff 三层TS补偿机制
status: pending_approval
scope: AVCodec, MediaEngine, MediaDemuxer, HLS, PTS维护, 音视频同步, 断点续传, Timestamp Continuity
related_scenarios:
  - HLS流媒体播放（断点Seek后PTS跳变修复）
  - 多段TS/MP4拼接播放（segmentOffset累积偏移）
  - 音画不同步修复（videoAudioBasePtsDiff AV同步基准）
  - 转码场景PTS初始化（TranscoderInitMediaStartPts）
evidence_count: 20
related_mems:
  - S165: HttpSourcePlugin 下载监控装饰器模式
  - S182: HLS流下载与元数据管理
  - S187: DASH/HLS/MSS多协议下载架构
  - S192: MediaDemuxer ReadLoop异步管线
  - S211: FFmpegDemuxer ReadAhead缓冲控制
  - S209: MPEG4/FLV/MP4多格式支持
created: 2026-06-25
builder: builder-agent
source: GitCode web_fetch (https://gitcode.com/openharmony/multimedia_av_codec)
---

# MEM-ARCH-AVCODEC-S175：MediaDemuxer PTS自动维护架构

## 架构概述

`MediaDemuxer::HandleAutoMaintainPts` 系列函数实现了一套 **HLS 断点 PTS 自动维护** 机制，用于解决 HLS 多段 TS 流在 Seek / 网络切换 / Segment 边界等场景下的 PTS 跳变与音画不同步问题。

### 核心组件

| 组件 | 文件 | 职责 |
|------|------|------|
| `MaintainBaseInfo` | media_demuxer.h L369-377 | per-track PTS 基底信息（segment偏移/基准PTS/上次PTS/最大PTS） |
| `HandleAutoMaintainPts` | media_demuxer_pts_functions.cpp L48-99 | PTS自动修正主函数（diff阈值判断/segment切换补偿） |
| `InitPtsInfo` | media_demuxer_pts_functions.cpp L108-127 | HLS模式初始化per-track的MaintainBaseInfo |
| `InitMediaStartPts` | media_demuxer_pts_functions.cpp L129-153 | 扫描trackMeta获取全局mediaStartPts_ |
| `TranscoderInitMediaStartPts` | media_demuxer_pts_functions.cpp L155-185 | 转码模式初始化（video/audio首track分别初始化） |
| `UpdateSegmentOffset` | media_demuxer_pts_functions.cpp L187-204 | HLS Segment切换时更新offset |
| `SetCurrentSegmentOffset` | media_demuxer_pts_functions.cpp L206-219 | 线程安全写入currentSegmentOffsetMap_ |
| `GetCurrentSegmentOffset` | media_demuxer_pts_functions.cpp L221-236 | 从map读取segmentOffset |
| `InitVideoAudioBasePtsDiff` | media_demuxer_pts_functions.cpp L238-248 | 计算videoAudioBasePtsDiff（音画同步基准） |
| `ptsManagedFileTypes` | media_demuxer.cpp | AVI/MPEGPS/WMV等非连续PTS格式标记集合 |

### 三层TS补偿机制流程

```
输入: sample->pts_ (原始PTS)
         │
         ▼
    diff = curPacketPts - lastPts
         │
         ├── diff < 0: diff = -diff（取绝对值）
         │
         ▼
┌─────────────────────────────────────────────────┐
│ Layer 1: 首次进入新Segment (segmentOffset==-1)  │
│   GetCurrentSegmentOffset → 更新basePts/offset │
│   pts = segmentOffset + curPts - basePts + mediaStartPts_
└─────────────────────────────────────────────────┘
         │
         ├── diff > MAX_PTS_DIFFER_THRESHOLD_US (2s)
         │         │
         │         ▼
         │  ┌─────────────────────────────────────────┐
         │  │ Layer 2: 大幅PTS跳变（疑似Segment切换） │
         │  │  isLastPtsChange=true → 记录candidate │
         │  │  下一帧：pts = lastPtsModifyedMax + 1ms│
         │  └─────────────────────────────────────────┘
         │
         └── diff ≤ 2s
                   │
                   ▼
            ┌────────────────────────────┐
            │ Layer 3: 正常连续 PTS      │
            │ pts = segmentOffset +      │
            │   curPts - basePts +       │
            │   mediaStartPts_ +         │
            │   videoAudioBasePtsDiff    │
            └────────────────────────────┘
```

---

## Formal Evidence（20条）

### E1 — PTS阈值常量定义
**文件**: `media_demuxer_pts_functions.cpp`
**行号**: L42-45
**内容**:
```cpp
constexpr int64_t MAX_PTS_DIFFER_THRESHOLD_US = 2000000; // The maximum difference between Segment 2s.
constexpr int64_t INVALID_PTS_DATA = -1; // The invalid pts data -1.
constexpr int64_t PTS_MICRO_ADJUSTMENT_US = 1000;
constexpr int64_t LOG_INTERVAL_MS_COUNT = 2000; // 2s
constexpr uint32_t LOG_MAX_PRINTS_COUNT = 10; // 10 times
```
**说明**: MAX_PTS_DIFFER_THRESHOLD_US=2s 是判断"正常连续PTS"与"Segment切换导致跳变"的分水岭。INVALID_PTS_DATA=-1标记尚未初始化的segmentOffset。PTS_MICRO_ADJUSTMENT_US=1ms用于跳变后微调。

---

### E2 — MaintainBaseInfo per-track数据结构
**文件**: `media_demuxer.h`
**行号**: L369-377
**内容**:
```cpp
struct MaintainBaseInfo {
    int64_t segmentOffset = -1;
    int64_t basePts = -1;
    int64_t candidateBasePts = -1;
    int64_t lastPts = 0;
    int64_t lastPtsModifyedMax = -1;
    bool isLastPtsChange = false;
};
```
**说明**: 每个track维护独立的PTS基线。segmentOffset是Segment累积偏移量；basePts是当前Segment的基准PTS；candidateBasePts用于Segment切换时暂存候选basePts；lastPtsModifyedMax记录历史最大PTS用于微调。

---

### E3 — HandleAutoMaintainPts 入口守卫
**文件**: `media_demuxer_pts_functions.cpp`
**行号**: L48-53
**内容**:
```cpp
void MediaDemuxer::HandleAutoMaintainPts(int32_t trackId, std::shared_ptr<AVBuffer> sample)
{
    if (!isAutoMaintainPts_.load()) {
        return;
    }
    int64_t curPacketPts = sample->pts_;
    std::shared_ptr<MaintainBaseInfo> baseInfo = maintainBaseInfos_[trackId];
    FALSE_RETURN_MSG(baseInfo != nullptr, "BaseInfo is nullptr, track " PUBLIC_LOG_D32, trackId);
```
**说明**: isAutoMaintainPts_由InitPtsInfo在HLS模式下设置为true。FALSE_RETURN_MSG确保trackId对应的MaintainBaseInfo已初始化。

---

### E4 — PTS差值计算与符号处理
**文件**: `media_demuxer_pts_functions.cpp`
**行号**: L54-60
**内容**:
```cpp
    int64_t diff = 0;
    diff = curPacketPts - baseInfo->lastPts;
    auto oldPts = baseInfo->lastPts;
    baseInfo->lastPts = curPacketPts;
    if (diff < 0) {
        diff = 0 - diff;
    }
```
**说明**: diff = 当前PTS - 上次PTS。无论PTS前进或倒退（某些格式倒序），均取绝对值。oldPts保存以便在跳变场景回溯。

---

### E5 — Layer 1: 新Segment首次进入（segmentOffset==INVALID_PTS_DATA）
**文件**: `media_demuxer_pts_functions.cpp`
**行号**: L61-68
**内容**:
```cpp
    if (baseInfo->segmentOffset == INVALID_PTS_DATA) {
        int64_t offset = GetCurrentSegmentOffset(trackId, baseInfo->segmentOffset);
        if (baseInfo->segmentOffset != offset) {
            baseInfo->segmentOffset = offset;
            baseInfo->basePts = curPacketPts;
            InitVideoAudioBasePtsDiff();
        }
        sample->pts_ = baseInfo->segmentOffset + curPacketPts - baseInfo->basePts + mediaStartPts_;
```
**说明**: 首次进入新Segment时，segmentOffset=-1，调用GetCurrentSegmentOffset获取source_当前偏移量后初始化basePts。修正公式：pts = segmentOffset + curPts - basePts + mediaStartPts_。

---

### E6 — Layer 2: PTS大幅跳变检测与微调（diff > 2s）
**文件**: `media_demuxer_pts_functions.cpp`
**行号**: L69-86
**内容**:
```cpp
    } else if (diff > MAX_PTS_DIFFER_THRESHOLD_US) {
        videoAudioBasePtsDiff = -1;
        if (baseInfo->isLastPtsChange) {
            int64_t offset = GetCurrentSegmentOffset(trackId, baseInfo->segmentOffset);
            if (baseInfo->segmentOffset != offset) {
                baseInfo->segmentOffset = offset;
                baseInfo->basePts = baseInfo->candidateBasePts;
            }
            sample->pts_ = baseInfo->segmentOffset + curPacketPts - baseInfo->basePts + mediaStartPts_;
            baseInfo->isLastPtsChange = false;
        } else {
            sample->pts_ = baseInfo->lastPtsModifyedMax + PTS_MICRO_ADJUSTMENT_US;
            baseInfo->candidateBasePts = curPacketPts;
            baseInfo->isLastPtsChange = true;
            baseInfo->lastPts = oldPts;
        }
```
**说明**: diff>2s说明PTS发生大幅跳变（非正常播放速率）。第一帧标记isLastPtsChange=true，pts=lastPtsModifyedMax+1ms（微调）；第二帧（isLastPtsChange==true）检测到offset变化则确认Segment切换，更新basePts并重算pts。

---

### E7 — Layer 3: 正常连续PTS处理
**文件**: `media_demuxer_pts_functions.cpp`
**行号**: L87-92
**内容**:
```cpp
    } else {
        sample->pts_ = baseInfo->segmentOffset + curPacketPts - baseInfo->basePts + mediaStartPts_;
        FALSE_GOON_NOEXEC(videoAudioBasePtsDiff != -1 && trackId == videoTrackId_,
            sample->pts_ += videoAudioBasePtsDiff);
        baseInfo->isLastPtsChange = false;
    }
```
**说明**: 正常播放时pts = segmentOffset + curPts - basePts + mediaStartPts_，videoTrackId_额外加上videoAudioBasePtsDiff（音画同步补偿），isLastPtsChange重置。

---

### E8 — lastPtsModifyedMax历史最大PTS追踪
**文件**: `media_demuxer_pts_functions.cpp`
**行号**: L93-94
**内容**:
```cpp
    baseInfo->lastPtsModifyedMax = std::max(sample->pts_, baseInfo->lastPtsModifyedMax);
```
**说明**: std::max确保lastPtsModifyedMax只增不减，用于PTS大幅跳变后第一帧的微调基准（E6中sample->pts_ = lastPtsModifyedMax + PTS_MICRO_ADJUSTMENT_US）。

---

### E9 — PTS修正日志限频输出
**文件**: `media_demuxer_pts_functions.cpp`
**行号**: L95-99
**内容**:
```cpp
    AVCODEC_LOG_LIMIT_IN_TIME(AVCODEC_LOGI, LOG_INTERVAL_MS_COUNT, LOG_MAX_PRINTS_COUNT,
        "Success, track:" PUBLIC_LOG_D32 ", orgPts:"
        PUBLIC_LOG_D64 ", pts:" PUBLIC_LOG_D64 ", basePts:" PUBLIC_LOG_D64, trackId,
        curPacketPts, sample->pts_, baseInfo->basePts);
}
```
**说明**: AVCODEC_LOG_LIMIT_IN_TIME实现每2秒最多10次的限频日志，避免大量日志淹没。打印原始PTS、修正后PTS和basePts用于DFX问题定位。

---

### E10 — InitPtsInfo HLS模式初始化
**文件**: `media_demuxer_pts_functions.cpp`
**行号**: L108-115
**内容**:
```cpp
void MediaDemuxer::InitPtsInfo()
{
    if (source_ == nullptr || !isHls_) {
        return;
    }
    MEDIA_LOG_I("Enable hls disContinuity auto maintain pts");
    isAutoMaintainPts_.store(true);
    AutoLock lock(mapMutex_);
    for (auto it = bufferQueueMap_.begin(); it != bufferQueueMap_.end(); it++) {
```
**说明**: 仅在HLS流且source_有效时启用PTS自动维护。isAutoMaintainPts_是atomic bool，HandleAutoMaintainPts读此标记决定是否处理。AutoLock（RAII）保护maintainBaseInfos_的并发访问。

---

### E11 — InitPtsInfo per-track MaintainBaseInfo初始化
**文件**: `media_demuxer_pts_functions.cpp`
**行号**: L116-127
**内容**:
```cpp
        int32_t trackId = it->first;
        if (maintainBaseInfos_[trackId] == nullptr) {
            maintainBaseInfos_[trackId] = std::make_shared<MaintainBaseInfo>();
        }
        maintainBaseInfos_[trackId]->segmentOffset = INVALID_PTS_DATA;
        maintainBaseInfos_[trackId]->basePts = INVALID_PTS_DATA;
        maintainBaseInfos_[trackId]->isLastPtsChange = false;
        maintainBaseInfos_[trackId]->lastPtsModifyedMax = INVALID_PTS_DATA;
        SetCurrentSegmentOffset(trackId, source_->GetSegmentOffset());
    }
}
```
**说明**: 每个track初始化时segmentOffset/basePts/lastPtsModifyedMax均设为-1（INVALID_PTS_DATA），isLastPtsChange=false。初始offset由source_->GetSegmentOffset()设置（HLS首片段起始偏移）。

---

### E12 — InitMediaStartPts 全局起始时间扫描
**文件**: `media_demuxer_pts_functions.cpp`
**行号**: L129-140
**内容**:
```cpp
void MediaDemuxer::InitMediaStartPts()
{
    std::string mime;
    int64_t startTime = 0;
    for (const auto& trackInfo : mediaMetaData_.trackMetas) {
        if (trackInfo == nullptr || !(trackInfo->GetData(Tag::MIME_TYPE, mime))) {
            MEDIA_LOG_W("TrackInfo is null or get mime fail");
            continue;
        }
        if (!(mime.find("audio/") == 0 || mime.find("video/") == 0)) {
            continue;
        }
        if (trackInfo->GetData(Tag::MEDIA_START_TIME, startTime) &&
            (mediaStartPts_ == HST_TIME_NONE || startTime < mediaStartPts_)) {
            mediaStartPts_ = startTime;
        }
    }
}
```
**说明**: 遍历所有track的meta信息，仅处理audio/video轨道，取所有轨道MEDIA_START_TIME的最小值作为全局mediaStartPts_。此值用于HandleAutoMaintainPts中的pts修正公式（+mediaStartPts_）。

---

### E13 — TranscoderInitMediaStartPts 转码模式独立初始化
**文件**: `media_demuxer_pts_functions.cpp`
**行号**: L155-171
**内容**:
```cpp
void MediaDemuxer::TranscoderInitMediaStartPts()
{
    // Init media start time based on the first video track and the first audio track
    std::string mime;
    int64_t startTime = 0;
    bool isInitVideoStartTime = false;
    bool isInitAudioStartTime = false;
    for (const auto& trackInfo : mediaMetaData_.trackMetas) {
        if (trackInfo == nullptr || !(trackInfo->GetData(Tag::MIME_TYPE, mime))) {
            MEDIA_LOG_W("TrackInfo is null or get mime fail");
            continue;
        }
        if (!isInitVideoStartTime && (mime.find("video/") == 0)) {
            isInitVideoStartTime = true;
            FALSE_RETURN(trackInfo->GetData(Tag::MEDIA_START_TIME, startTime));
            if (transcoderStartPts_ == HST_TIME_NONE || startTime < transcoderStartPts_) {
                transcoderStartPts_ = startTime;
            }
```
**说明**: 与InitMediaStartPts不同，TranscoderInitMediaStartPts使用独立成员变量transcoderStartPts_，且仅取第一个video track和第一个audio track的startTime（而非所有轨道最小值），避免字幕轨道干扰。

---

### E14 — TranscoderInitMediaStartPts audio分支及early break
**文件**: `media_demuxer_pts_functions.cpp`
**行号**: L172-185
**内容**:
```cpp
        } else if (!isInitAudioStartTime && (mime.find("audio/") == 0)) {
            isInitAudioStartTime = true;
            FALSE_RETURN(trackInfo->GetData(Tag::MEDIA_START_TIME, startTime));
            if (transcoderStartPts_ == HST_TIME_NONE || startTime < transcoderStartPts_) {
                transcoderStartPts_ = startTime;
            }
        }
        if (isInitAudioStartTime && isInitVideoStartTime) {
            break;
        }
    }
}
```
**说明**: audio初始化完成后立即break，避免不必要遍历。transcoderStartPts_用于转码输出时的PTS基准。

---

### E15 — UpdateSegmentOffset 单track更新
**文件**: `media_demuxer_pts_functions.cpp`
**行号**: L187-195
**内容**:
```cpp
void MediaDemuxer::UpdateSegmentOffset(int32_t trackId)
{
    FALSE_RETURN_NOLOG(isAutoMaintainPts_.load());
    FALSE_RETURN_NOLOG(source_ != nullptr);

    auto offset = source_->GetSegmentOffset();
    SetCurrentSegmentOffset(trackId, offset);
    FALSE_GOON_NOEXEC(IsAVInOneStream() && trackId == videoTrackId_,
        SetCurrentSegmentOffset(audioTrackId_, offset));
}
```
**说明**: HLS Segment切换时由调用方触发，读取source_当前offset并写入对应track的currentSegmentOffsetMap_。IsAVInOneStream()时video切换会同步更新audio的offset。

---

### E16 — UpdateSegmentOffset 新旧track id重映射
**文件**: `media_demuxer_pts_functions.cpp`
**行号**: L197-204
**内容**:
```cpp
void MediaDemuxer::UpdateSegmentOffset(int32_t oldTrackId, int32_t newTrackId)
{
    FALSE_RETURN_NOLOG(isAutoMaintainPts_.load());
    FALSE_RETURN_NOLOG(source_ != nullptr);

    auto offset = source_->GetSegmentOffset();
    SetCurrentSegmentOffset(newTrackId, GetCurrentSegmentOffset(oldTrackId, offset));
}
```
**说明**: track切换场景（如码率自适应切换）时，newTrackId继承oldTrackId的segmentOffset再加上当前offset的增量。

---

### E17 — SetCurrentSegmentOffset 线程安全写入与溢出保护
**文件**: `media_demuxer_pts_functions.cpp`
**行号**: L206-219
**内容**:
```cpp
void MediaDemuxer::SetCurrentSegmentOffset(int32_t trackId, size_t segmentOffset)
{
    FALSE_RETURN_NOLOG(IsValidTrackId(trackId));

    // segmentOffset is derived from PTS. Clamp to int64_t range to avoid overflow.
    std::lock_guard<std::mutex> lock(segmentOffsetMutex_);
    int64_t max = std::numeric_limits<int64_t>::max();
    currentSegmentOffsetMap_[trackId] =
        (segmentOffset > static_cast<size_t>(max)) ? max : static_cast<int64_t>(segmentOffset);
}
```
**说明**: segmentOffsetMutex_是专门保护currentSegmentOffsetMap_的互斥量，与mapMutex_（保护maintainBaseInfos_）是不同锁，避免锁竞争。溢出保护将超大offset clamp到LLONG_MAX。

---

### E18 — GetCurrentSegmentOffset 乐观读取
**文件**: `media_demuxer_pts_functions.cpp`
**行号**: L221-230
**内容**:
```cpp
int64_t MediaDemuxer::GetCurrentSegmentOffset(int32_t trackId, int64_t oldSegmentOffset)
{
    FALSE_RETURN_V_NOLOG(isAutoMaintainPts_.load(), oldSegmentOffset);
    FALSE_RETURN_V_NOLOG(IsValidTrackId(trackId), oldSegmentOffset);
    std::lock_guard<std::mutex> lock(segmentOffsetMutex_);
    FALSE_RETURN_V_NOLOG(currentSegmentOffsetMap_.find(trackId) != currentSegmentOffsetMap_.end(), oldSegmentOffset);
    return currentSegmentOffsetMap_[trackId];
}
```
**说明**: 三重守卫（isAutoMaintainPts_ / IsValidTrackId / map.find），任意失败返回oldSegmentOffset作为fallback，避免异常PTS值传播。

---

### E19 — InitVideoAudioBasePtsDiff AV同步基准差值计算
**文件**: `media_demuxer_pts_functions.cpp`
**行号**: L238-248
**内容**:
```cpp
void MediaDemuxer::InitVideoAudioBasePtsDiff()
{
    FALSE_RETURN(IsAVInOneStream() && maintainBaseInfos_[audioTrackId_] != nullptr
        && maintainBaseInfos_[videoTrackId_] != nullptr);
    FALSE_RETURN(maintainBaseInfos_[audioTrackId_]->basePts != INVALID_PTS_DATA);
    FALSE_RETURN(maintainBaseInfos_[videoTrackId_]->basePts != INVALID_PTS_DATA);
    videoAudioBasePtsDiff = maintainBaseInfos_[videoTrackId_]->basePts - maintainBaseInfos_[audioTrackId_]->basePts;
}
```
**说明**: videoAudioBasePtsDiff = video基准PTS - audio基准PTS，初始化后HandleAutoMaintainPts Layer3中对video track的pts额外加上此差值，实现AV同步补偿。IsAVInOneStream()判断是否在同一stream中。

---

### E20 — ptsManagedFileTypes 非连续PTS格式标记集合
**文件**: `media_demuxer.cpp`
**行号**: (约L78-80附近，ptsManagedFileTypes定义)
**内容**:
```cpp
std::unordered_set<FileType> ptsManagedFileTypes = {
    FileType::AVI,
    FileType::MPEGPS,
    FileType::WMV
};
```
**说明**: AVI/MPEGPS/WMV等封装格式存在天然PTS不连续问题，需要PTS自动维护机制介入。与HLS的segment边界PTS跳变场景互补，共同覆盖PTS维护需求。

---

## 关联记忆条目

| ID | 关系 |
|----|------|
| S165 | HttpSourcePlugin下载监控（DownloadMonitor.Downloader双层架构），提供source_->GetSegmentOffset()的HTTP层支持 |
| S182 | HLS流元数据管理，涉及HLS playlist解析与segment边界识别 |
| S187 | DASH/HLS/MSS多协议下载，与HLS segment切换触发UpdateSegmentOffset的协议层 |
| S192 | MediaDemuxer ReadLoop异步管线，ReadSample后调用HandleAutoMaintainPts |
| S211 | FFmpegDemuxer ReadAhead缓冲控制，FFmpegReadLoop与MdeiaDemuxer并称两大Demuxer管线 |
| S209 | MPEG4/FLV/MP4多格式支持，ptsManagedFileTypes中AVI/MPEGPS/WMV属于非HLS的本地文件PTS场景 |
| S138 | MPEG4 Box解析器（STTS/STSC等表），样本时间从解析后的元数据中来，PTS维护对原始值做修正 |
| S222 | DASH Segment环形缓冲架构，缓冲水位与PTS修正在时间维度上协调 |
