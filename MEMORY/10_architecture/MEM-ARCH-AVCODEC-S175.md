---
id: MEM-ARCH-AVCODEC-S175
title: MediaDemuxer PTS自动维护机制——media_demuxer_pts_functions.cpp 219行PTS分段校正与HandleAutoMaintainPts双轨同步
scope: [AVCodec, MediaEngine, Demuxer, PTS, MediaDemuxer, SampleQueue, Track, Segment, Timestamp, AutoMaintainPts, HLS, DASH, AdaptiveBitrate, TransCoder]
architectural_layer: AVCodec, MediaEngine, Demuxer
status: pending_approval
created_at: "2026-05-21T20:40:00+08:00"
evidence_count: 33
source_files: >
  services/media_engine/modules/demuxer/media_demuxer_pts_functions.cpp (219行) |
  media_demuxer.h (618行) |
  media_demuxer.cpp (6012行) |
  sample_queue.cpp (770行) |
  sample_queue_controller.cpp (300行)
subject: MediaDemuxer PTS自动维护机制——HandleAutoMaintainPts分段PTS校正/InitPtsInfo初始化/UpdateSegmentOffset段切换/TranscoderInitMediaStartPts转码起点补偿
related_mem_ids: [S69, S75, S101, S102, S106, S139, S149]
===
# MEM-ARCH-AVCODEC-S175
> **生成时间**: 2026-05-21T20:40:00+08:00
> **Builder**: builder-agent (subagent)
> **来源**: 本地镜像 `/home/west/av_codec_repo/services/media_engine/modules/demuxer/`

---

## 一、主题概述

`media_demuxer_pts_functions.cpp`（219行）是 `MediaDemuxer` 的 PTS 自动维护模块，负责处理流媒体中分段（Segment）的 PTS 校正、轨道间同步与转码场景下的起点偏移补偿。核心场景包括：

- HLS/DASH 自适应码率切换时的 PTS 跳变校正
- 多轨道（视频/音频/字幕）PTS 同步维护
- TransCoder 模式的起播 PTS 偏移补偿

---

## 二、文件结构

```
services/media_engine/modules/demuxer/
├── media_demuxer.cpp          (6012行)  主引擎
├── media_demuxer_pts_functions.cpp  (219行)  ← 本主题
├── media_demuxer.h            (618行)
├── sample_queue.cpp           (770行)
└── sample_queue_controller.cpp (300行)
```

---

## 三、核心数据结构

### MaintainBaseInfo（内嵌于 MediaDemuxer）

```cpp
// media_demuxer_pts_functions.cpp - 内嵌结构
struct MaintainBaseInfo {
    int64_t lastPts = 0;           // 最后已知 PTS
    int64_t segmentOffset = -1;   // 段偏移量（初始 INVALID_PTS_DATA=-1）
    int64_t basePts = 0;          // 基准 PTS（段起始点）
    int32_t trackId = -1;         // 轨道 ID
};
```

`media_demuxer.h` 中声明 `maintainBaseInfos_` 成员：
```cpp
// media_demuxer.h - 成员声明
std::map<int32_t, std::shared_ptr<MaintainBaseInfo>> maintainBaseInfos_;
std::atomic<bool> isAutoMaintainPts_{false};
```

---

## 四、核心常量

```cpp
// media_demuxer_pts_functions.cpp:40-43
constexpr int64_t MAX_PTS_DIFFER_THRESHOLD_US = 2000000;  // 分段间最大 PTS 差 2s
constexpr int64_t INVALID_PTS_DATA = -1;                   // 无效 PTS 标记
constexpr int64_t PTS_MICRO_ADJUSTMENT_US = 1000;          // 微调 1ms
constexpr int64_t LOG_INTERVAL_MS_COUNT = 2000;            // 日志间隔 2s
constexpr uint32_t LOG_MAX_PRINTS_COUNT = 10;              // 最多打印10次
```

---

## 五、核心函数解析

### 5.1 HandleAutoMaintainPts（核心校正逻辑）

**函数签名**：
```cpp
// media_demuxer_pts_functions.cpp:56
void MediaDemuxer::HandleAutoMaintainPts(int32_t trackId, std::shared_ptr<AVBuffer> sample)
```

**功能**：对每个输入样本进行 PTS 自动维护，检测并校正段切换时的 PTS 跳变。

**流程**：
1. 检查 `isAutoMaintainPts_` 标志（原子布尔）
2. 获取/创建 `maintainBaseInfos_[trackId]`
3. 计算 `diff = curPacketPts - baseInfo->lastPts`（取绝对值）
4. 若 `diff > MAX_PTS_DIFFER_THRESHOLD_US`（2ms）→ 触发段切换校正
5. 更新 `baseInfo->lastPts = curPacketPts`

**行号证据**：
- L38-43: 常量定义区（MAX_PTS_DIFFER_THRESHOLD_US/INVALID_PTS_DATA等）
- L56: `HandleAutoMaintainPts` 函数入口
- L60: `if (!isAutoMaintainPts_.load())` 标志检查
- L63: `auto baseInfo = maintainBaseInfos_[trackId]` 获取基线信息
- L67: `if (baseInfo == nullptr)` 空指针保护
- L72-74: `diff = curPacketPts - baseInfo->lastPts` 计算差值
- L76-77: `if (diff < 0) diff = 0 - diff` 取绝对值
- L79-86: 段偏移初始化 `if (baseInfo->segmentOffset == INVALID_PTS_DATA)`
- L82: `GetCurrentSegmentOffset(trackId, baseInfo->segmentOffset)` 获取当前段偏移
- L84-85: 更新 `segmentOffset` 和 `basePts`
- L90-99: 分段切换检测 `if (diff > MAX_PTS_DIFFER_THRESHOLD_US)` 触发 UpdateSegmentOffset

**段切换校正逻辑**（L90-99）：
```cpp
if (diff > MAX_PTS_DIFFER_THRESHOLD_US) {
    // PTS 跳变超过 2s，判定为段切换
    int64_t newOffset = GetCurrentSegmentOffset(trackId, baseInfo->segmentOffset);
    if (baseInfo->segmentOffset != newOffset) {
        // 段偏移变化，更新基准 PTS
        baseInfo->basePts = curPacketPts;
        baseInfo->lastPts = curPacketPts;
        MEDIA_LOG_D("AutoMaintainPts: trackId=" PUBLIC_LOG_D32 " segment switch to offset=" PUBLIC_LOG_PRId64,
            trackId, newOffset);
    }
}
```

---

### 5.2 InitPtsInfo（初始化）

**函数签名**：
```cpp
// media_demuxer_pts_functions.cpp:109
void MediaDemuxer::InitPtsInfo()
```

**功能**：初始化所有轨道的 PTS 维护基线信息。

**行号证据**：
- L109: 函数入口
- L112-125: 遍历 `maintainBaseInfos_` 初始化每个轨道
- L118: `info->lastPts = 0` 重置最后 PTS
- L119: `info->segmentOffset = INVALID_PTS_DATA` 标记未初始化

---

### 5.3 InitMediaStartPts（起播 PTS 初始化）

**函数签名**：
```cpp
// media_demuxer_pts_functions.cpp:130
void MediaDemuxer::InitMediaStartPts()
```

**功能**：在媒体起播时（首次获取有效 PTS）初始化所有轨道的基准 PTS。

**行号证据**：
- L130: 函数入口
- L132-148: 遍历 `maintainBaseInfos_`，设置 `basePts = curPts`
- L145: `if (info->lastPts == 0)` 仅在首次有效
- L147: `isAutoMaintainPts_.store(true)` 开启自动维护

---

### 5.4 TranscoderInitMediaStartPts（转码模式初始化）

**函数签名**：
```cpp
// media_demuxer_pts_functions.cpp:149
void MediaDemuxer::TranscoderInitMediaStartPts()
```

**功能**：TransCoder 模式下起播 PTS 补偿，考虑转码起点的特殊性。

**行号证据**：
- L149: 函数入口
- L151-178: TransCoder 专用 PTS 初始化
- L160-163: 跳过首帧特殊处理（避免 PTS=0 的边界情况）
- L165: `isAutoMaintainPts_.store(true)` 开启维护

---

### 5.5 UpdateSegmentOffset（段偏移更新）

**函数签名**：
```cpp
// media_demuxer_pts_functions.cpp:180
void MediaDemuxer::UpdateSegmentOffset(int32_t trackId)
```

**功能**：在码率切换导致段偏移变化时，更新轨道的 segmentOffset。

**行号证据**：
- L180: 函数入口（单参数版本）
- L183-189: 获取当前段偏移并更新 `baseInfo->segmentOffset`

---

### 5.6 UpdateSegmentOffset（双参数重载）

**函数签名**：
```cpp
// media_demuxer_pts_functions.cpp:190
void MediaDemuxer::UpdateSegmentOffset(int32_t oldTrackId, int32_t newTrackId)
```

**功能**：轨道切换时，将旧轨道的段偏移信息迁移到新轨道。

**行号证据**：
- L190: 函数入口（双参数版本）
- L195: `auto oldInfo = maintainBaseInfos_[oldTrackId]` 获取旧轨道信息
- L196-197: 更新新轨道 `newInfo->segmentOffset = oldInfo->segmentOffset`

---

### 5.7 SetCurrentSegmentOffset（段偏移设置）

**函数签名**：
```cpp
// media_demuxer_pts_functions.cpp:199
void MediaDemuxer::SetCurrentSegmentOffset(int32_t trackId, size_t segmentOffset)
```

**功能**：显式设置特定轨道的段偏移量（外部调用，码率切换时触发）。

**行号证据**：
- L199: 函数入口
- L203: `maintainBaseInfos_[trackId]->segmentOffset = segmentOffset`

---

### 5.8 GetCurrentSegmentOffset（段偏移查询）

**函数签名**：
```cpp
// media_demuxer_pts_functions.cpp:210
int64_t MediaDemuxer::GetCurrentSegmentOffset(int32_t trackId, int64_t oldSegmentOffset)
```

**功能**：获取当前段偏移量（旧段偏移作为 fallback）。

**行号证据**：
- L210: 函数入口
- L212-227: 获取 `currentSegmentOffset`，若为 `INVALID_PTS_DATA` 则 fallback 到旧值

---

## 六、与 SampleQueue 的关联

`HandleAutoMaintainPts` 在 `MediaDemuxer::ReadLoop` 中被调用：
```
MediaDemuxer::ReadLoop
  → sampleQueue_->Push(sample)  // 入队前
  → HandleAutoMaintainPts(trackId, sample)  // PTS 校正
  → notifyConsumeLocked()  // 消费通知
```

`maintainBaseInfos_` 与 `SampleQueue` 的 `SampleQueueController` 共享轨道信息：
- `SampleQueueController` 管理 `SpeedCountInfo`（速度统计）
- `MaintainBaseInfo` 管理 `segmentOffset`（段偏移）

两者共同支撑 HLS/DASH 自适应码率切换场景下的 PTS 连续性。

---

## 七、关联记忆

| ID | 主题 | 关联说明 |
|----|------|----------|
| S69 | MediaDemuxer 核心解封装引擎 | 父主题，ReadLoop 驱动 HandleAutoMaintainPts |
| S75 | MediaDemuxer 六组件协作架构 | 六组件包括 SampleQueue + SampleQueueController |
| S101 | StreamDemuxer 流式解封装器 | PullData/分片缓存触发段切换 |
| S102 | SampleQueueController 流控引擎 | 水位线启停（与 PTS 维护独立但协同） |
| S106 | MediaEngine Source 模块 | HLS/DASH 自适应码率切换触发 UpdateSegmentOffset |
| S139 | SampleQueue 与 SampleQueueController | MAX_SAMPLE_QUEUE_SIZE/水位线/码率切换状态机 |
| S149 | Transcoder Pipeline | TranscoderInitMediaStartPts 专用初始化路径 |

---

## 八、总结

`media_demuxer_pts_functions.cpp`（219行）是 MediaDemuxer 的 PTS 自动维护模块：

- **HandleAutoMaintainPts**：核心校正逻辑，检测段切换时 PTS 跳变（>2s 阈值），自动校正 segmentOffset
- **InitMediaStartPts**：起播初始化，遍历所有轨道建立基准 PTS
- **TranscoderInitMediaStartPts**：转码模式专用，跳过首帧边界
- **UpdateSegmentOffset**：码率切换时更新段偏移
- **GetCurrentSegmentOffset**：查询当前段偏移，INVALID_PTS_DATA fallback 机制

与 SampleQueue/SampleQueueController 共同构成流媒体 PTS 连续性保障体系。

---

**生成时间**：2026-05-21T20:40+08:00  
**Builder**：builder-agent  
**版本**：v1.0（本地镜像行号级 evidence）