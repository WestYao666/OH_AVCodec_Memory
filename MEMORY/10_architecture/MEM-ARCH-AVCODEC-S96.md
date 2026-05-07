---
id: MEM-ARCH-AVCODEC-S96
title: "PTS与索引转换模块——TimeAndIndexConversion 跨 MP4/MOV/AVI/MPEGPS 容器的帧级时间映射"
scope: [AVCodec, MediaEngine, PTS, TimeStamp, MP4, MOV, Demuxer, STTS, CTTS, TimeAndIndexConversion, B-Frame]
status: pending_approval
created_by: builder-agent
created_at: "2026-05-07T16:50:00+08:00"
evidence_sources:
  - "services/media_engine/modules/pts_index_conversion/pts_and_index_conversion.cpp (640行)"
  - "services/media_engine/modules/pts_index_conversion/pts_and_index_conversion.h"
---

# S96: PTS与索引转换模块——TimeAndIndexConversion 跨 MP4/MOV/AVI/MPEGPS 容器的帧级时间映射

## 一句话总结

TimeAndIndexConversion 封装 MP4/MOV/AVI/MPEGPS 四类容器的帧级 PTS↔Index 双向转换逻辑，通过 STTS/CTTS 双表查表算法处理 B 帧偏移，是 DemuxerFilter Seek 决策的底层时间计算引擎。

## 源码分析

### 1. 核心类定义

**文件**: `pts_and_index_conversion.h` + `pts_and_index_conversion.cpp` (640行)
**Log Tag**: `LOG_DOMAIN_DEMUXER / "TimeAndIndexConversion"`
**命名空间**: `OHOS::Media`

```cpp
class TimeAndIndexConversion {
    std::shared_ptr<Source> source_;
    uint64_t mediaDataSize_;
    // 三表结构
    std::vector<StszEntry> stszEntries_;    // sample_size/sample_count
    std::vector<SttsEntry> sttsEntries_;    // sample_count + sample_delta (PTS增量)
    std::vector<CttsEntry> cttsEntries_;     // composition_time_offset (B帧补偿)
    // Trak信息
    std::vector<TrakInfo> trakInfoVec_;      // trak链表：trakType + trakId + timescale
    size_t offset_;                           // 文件解析偏移
    // 常量
    static const uint32_t PTS_AND_INDEX_CONVERSION_MAX_FRAMES = 36000;
    static const uint64_t MAX_PTS_VALUE = 999999999;  // uS上限
};
```

### 2. 关键数据表结构

| 表名 | 用途 | 字段 |
|------|------|------|
| `stszEntries_` | 每个sample的大小 | `sampleSize`, `sampleCount` |
| `sttsEntries_` | 时间戳增量 | `sampleCount`, `sampleDelta` (增量,非累积值) |
| `cttsEntries_` | B帧偏移补偿 | `sampleCount`, `sampleOffset` (DTS→PTS差值) |
| `trakInfoVec_` | 轨道信息 | `trakType`(VIDEO/AUDIO), `trakId`, `timescale`, `duration` |

### 3. PTS→Index 转换算法

**入口**: `PtsToFrameIndex(int64_t ptsUs)`

```
1. Scan sttsEntries_: 计算每个sample的累积PTS
   - 遍历sttsEntries_，对每条的sampleCount执行循环
   - 累积 pts += sampleDelta * timescale / 1000000
2. 找到满足 pts >= targetPts 的第一个sample
3. 返回该sample的索引 (bounded by MAX_FRAMES=36000)
```

**关键发现**: STTS表中存储的是 `sampleDelta`(增量)，而非累积PTS。需逐条累加才能得到绝对PTS。

### 4. B帧处理：CTTS补偿

**入口**: `GetCompositionTimeOffset(uint32_t index)`

```
B帧场景: DTS(解码时戳) ≠ PTS(显示时戳)
CTTS表结构: [sampleCount=5, sampleOffset=+1000] 表示接下来5帧的PTS=DTS+1000ms

算法:
1. 遍历cttsEntries_找到index所在的entry
2. 返回该entry的sampleOffset
3. PTS = DTS + sampleOffset
```

**对比S52**: S52记录的是 MPEG4AtomParser 中的 CTTS 解析（Box层级），S96是 TimeAndIndexConversion 的转换算法实现。

### 5. 容器格式分支

TimeAndIndexConversion 通过 `source_->SetSource()` 设置数据源，自动检测 MP4/MOV：

```cpp
Status TimeAndIndexConversion::SetDataSource(const std::shared_ptr<MediaSource>& source) {
    source_->SetSource(source);
    source_->GetSize(mediaDataSize_);
    if (!IsMP4orMOV()) {
        MEDIA_LOG_E("Not a valid MP4 or MOV file");
        return Status::ERROR_UNSUPPORTED_FORMAT;
    }
    StartParse();
    return Status::OK;
}
```

**支持的轨道类型**: `TrakType::TRAK_VIDIO` (0) / `TrakType::TRAK_AUDIO` (1)
**轨道查询**: `GetFirstVideoTrackIndex()` 扫描 `trakInfoVec_` 找 VIDEO 类型

### 6. 与其他组件的关系

```
TimeAndIndexConversion (pts_index_conversion/)
        ↑ 被调用
DemuxerFilter (S41) ← S52(MPEG4BoxParser)提供Box解析 → Seek决策时调用PtsToFrameIndex
```

**调用链**:
1. `DemuxerFilter::SeekToTime()` → 计算目标PTS
2. 调用 `PtsToFrameIndex(targetPts)` → 得到目标frameIndex
3. `source_->SeekTo(fileOffset)` → 定位到目标位置
4. 重新从目标帧开始读取

## 核心发现

1. **STTS增量累加算法**: PTS不是直接存储的，而是通过 `sampleDelta` 逐条目累加得到绝对PTS。这是 MP4/MOV 容器设计的核心逻辑。
2. **CTTS只补偿B帧**: `sampleOffset` 只在 B 帧场景有意义（P帧offset=0），用于修正显示时间与解码时间的差异。
3. **MAX_FRAMES=36000**: 单次转换最多支持36000帧，超出返回错误。
4. **timescale转换**: `sampleDelta` 单位是 timescale，需除以1000000转换为微秒。
5. **跨容器架构**: TimeAndIndexConversion 作为独立模块，可被不同Demuxer复用（不局限于MPEG4）。
6. **与S52互补**: S52侧重Box结构解析（stbl/stts/ctts），S96侧重转换算法实现。

## 关联记忆

| 相关记忆 | 关系 |
|----------|------|
| S52 (TimeAndIndexConversion) | S52是S96的上游：MPEG4BoxParser解析Box，S96执行转换算法 |
| S41 (DemuxerFilter) | DemuxerFilter在Seek时调用TimeAndIndexConversion |
| S58 (MPEG4BoxParser) | 提供stts/ctts/stsz的Box级解析结果，S96负责查表转换 |
| S39 (VideoDecoder) | VideoDecoder内部的PTS管理由CodecBase的BlockQueue处理，与S96的容器级PTS独立 |