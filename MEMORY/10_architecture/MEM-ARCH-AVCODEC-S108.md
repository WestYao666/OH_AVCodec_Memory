---
id: MEM-ARCH-AVCODEC-S108
title: "TimeAndIndexConversion 时间戳索引转换器——MP4 STTS/CTTS Box 解析与 PTS/Index 双向转换"
scope: [AVCodec, MediaEngine, Demuxer, PTS, Index, MP4, MOV, STTS, CTTS, TimeAndIndexConversion, BitrateSwitch]
status: draft
approved_at: ~pending~
approved_by: ~pending~
approval_submitted_at: ~pending~
created_by: builder-agent
created_at: "2026-05-09T12:30:00+08:00"
关联主题: [S101(StreamDemuxer), S102(SampleQueueController), S97(DemuxerPluginManager), S69(MediaDemuxer)]
---

## Status

```yaml
status: draft
created: 2026-05-09T12:30
builder: builder-agent
source: /home/west/av_codec_repo/services/media_engine/modules/pts_index_conversion/
```

## 主题

TimeAndIndexConversion 时间戳索引转换器——MP4 STTS/CTTS Box 解析与 PTS/Index 双向转换

## 标签

AVCodec, MediaEngine, Demuxer, PTS, Index, MP4, MOV, STTS, CTTS, TimeAndIndexConversion, BitrateSwitch

## 关联记忆

- S101 (StreamDemuxer 流式解封装器)：TimeAndIndexConversion 通过 Source 读取 MP4/MOV 容器数据
- S102 (SampleQueueController 流控引擎)：PTS/Index 转换用于 Seek 和码率切换定位
- S69/S75 (MediaDemuxer)：TimeAndIndexConversion 属于 MediaDemuxer 内部工具模块
- S97 (DemuxerPluginManager)：与 MP4/MOV DemuxerPlugin 协同工作
- S41 (DemuxerFilter)：Filter 层使用 PTS 做时间同步

## 摘要

`TimeAndIndexConversion` (640行 .cpp + 150行 .h) 是 MediaEngine 中的 **PTS/Index 双向转换引擎**，直接解析 MP4/MOV 容器中的 STTS（time-to-sample）和 CTTS（composition time-to-sample）Atom Box，实现：

1. **Index → RelativePTS**：已知 sample index，反向查找对应 PTS
2. **RelativePTS → Index**：已知相对 PTS，正向查找对应 sample index
3. **MP4 Box 递归解析**：ftyp → moov → trak → mdia → minf → stbl → stts/ctts/hdlr/mdhd
4. **首帧 PTS 定位**：扫描 stts 找到第一帧的 PTS 基准（absolutePTSIndexZero_）

---

## Evidence（源码行号）

### pts_and_index_conversion.h (150 行)

| 符号 | 位置 | 说明 |
|------|------|------|
| `class TimeAndIndexConversion` | pts_and_index_conversion.h:46 | PTS/Index 转换主类 |
| `STTSEntry { sampleCount, sampleDelta }` | pts_and_index_conversion.h:74 | STTS 表条目：连续相同时间戳的帧数+帧间隔 |
| `CTTSEntry { sampleCount, sampleOffset }` | pts_and_index_conversion.h:78 | CTTS 表条目：连续相同组合时间的帧数+偏移量 |
| `TrakInfo { trakId, trakType, timeScale, sttsEntries, cttsEntries }` | pts_and_index_conversion.h:80-86 | 单轨元数据（ID/类型/时间基/STTS/CTTS） |
| `boxParsers` | pts_and_index_conversion.h:89-95 | Box 解析器分发表（函数指针映射） |
| `IndexAndPTSConvertMode` | pts_and_index_conversion.h:54-58 | 转换模式枚举：GET_FIRST_PTS / INDEX_TO_RELATIVEPTS / RELATIVEPTS_TO_INDEX |
| `TrakType` | pts_and_index_conversion.h:61-65 | 轨类型：TRAK_OTHER / TRAK_AUDIO / TRAK_VIDIO |
| `absolutePTSIndexZero_` | pts_and_index_conversion.h:115 | 首帧 PTS 基准（INT64_MAX 初始值） |
| `indexToRelativePTSMaxHeap_` | pts_and_index_conversion.h:116 | Index→RelativePTS 最大堆 |
| `relativePTSToIndexPosition_` | pts_and_index_conversion.h:119 | RelativePTS→Index 遍历游标 |
| `relativePTSToIndexPTSMin_ / PTSMax_` | pts_and_index_conversion.h:120-121 | RelativePTS→Index 二分搜索边界 |
| `SetDataSource()` | pts_and_index_conversion.h:49 | 设置数据源（std::shared_ptr<MediaSource>） |
| `GetFirstVideoTrackIndex()` | pts_and_index_conversion.h:50 | 获取第一个视频轨索引 |
| `GetIndexByRelativePresentationTimeUs()` | pts_and_index_conversion.h:51 | RelativePTS → Index（正向查找） |
| `GetRelativePresentationTimeUsByIndex()` | pts_and_index_conversion.h:52 | Index → RelativePTS（反向查找） |

### pts_and_index_conversion.cpp (640 行)

| 符号 | 位置 | 说明 |
|------|------|------|
| `StartParse()` | pts_and_index_conversion.cpp:（待补充） | 启动递归 Box 解析流程 |
| `ParseMoov()` | pts_and_index_conversion.cpp:（待补充） | 解析 moov Container Box |
| `ParseTrak()` | pts_and_index_conversion.cpp:（待补充） | 解析 trak Track Box，识别 TRAK_VIDIO/TRAK_AUDIO |
| `ParseStts()` | pts_and_index_conversion.cpp:（待补充） | 解析 stts Time-to-Sample Atom |
| `ParseCtts()` | pts_and_index_conversion.cpp:（待补充） | 解析 ctts Composition Time-to-Sample Atom |
| `ParseHdlr()` | pts_and_index_conversion.cpp:（待补充） | 解析 hdlr Handler Box（识别 video/audio 轨） |
| `ParseMdhd()` | pts_and_index_conversion.cpp:（待补充） | 解析 mdhd Media Header Box（提取 timeScale） |
| `GetPresentationTimeUsFromFfmpegMOV()` | pts_and_index_conversion.cpp:（待补充） | 驱动转换的主函数（三模式分发） |
| `PTSAndIndexConvertSttsAndCttsProcess()` | pts_and_index_conversion.cpp:（待补充） | 同时使用 STTS+CTTS 的转换算法 |
| `PTSAndIndexConvertOnlySttsProcess()` | pts_and_index_conversion.cpp:（待补充） | 仅使用 STTS 的转换算法（GOP 内 B/P 帧场景） |
| `IndexToRelativePTSProcess()` | pts_and_index_conversion.cpp:（待补充） | Index → RelativePTS 的堆排序查找 |
| `RelativePTSToIndexProcess()` | pts_and_index_conversion.cpp:（待补充） | RelativePTS → Index 的二分搜索 |
| `InitPTSandIndexConvert()` | pts_and_index_conversion.cpp:（待补充） | 初始化转换器 |
| `IsWithinPTSAndIndexConversionMaxFrames()` | pts_and_index_conversion.cpp:（待补充） | 边界保护：防止查找超出 STTS 表范围 |

## 架构定位

```
MP4/MOV 文件（FileSourcePlugin）
    └── Source (S106)
            └── TimeAndIndexConversion ← S108
                    ├── ParseMoov → ParseTrak → ParseMdhd（提取 timeScale）
                    ├── ParseStts（构建 sampleCount/sampleDelta 数组）
                    ├── ParseCtts（构建 compositionTime 偏移数组）
                    └── GetIndexByRelativePresentationTimeUs / GetRelativePresentationTimeUsByIndex
```

## 核心设计

### 1. MP4 Box 层级解析模型

MP4 文件结构（部分）：

```
ftyp (File Type Box)
moov (Movie Box)
    └── trak (Track Box) × N
            └── mdia (Media Box)
                    ├── mdhd (Media Header Box) → timeScale
                    └── minf (Media Information Box)
                            └── stbl (Sample Table Box)
                                    ├── stts (Time-to-Sample)
                                    ├── ctts (Composition Time-to-Sample)
                                    └── hdlr (Handler Reference)
```

**Box 解析器分发表**：
```cpp
std::map<std::string, void(TimeAndIndexConversion::*)(uint32_t)> boxParsers = {
    {BOX_TYPE_STTS, &TimeAndIndexConversion::ParseStts},
    {BOX_TYPE_CTTS, &TimeAndIndexConversion::ParseCtts},
    {BOX_TYPE_HDLR, &TimeAndIndexConversion::ParseHdlr},
    {BOX_TYPE_MDHD, &TimeAndIndexConversion::ParseMdhd},
    {BOX_TYPE_STBL, &TimeAndIndexConversion::ParseBox},
    {BOX_TYPE_MINF, &TimeAndIndexConversion::ParseBox},
    {BOX_TYPE_MDIA, &TimeAndIndexConversion::ParseBox},
};
```

### 2. STTS 时间戳映射表

STTS 表将连续相同帧间隔的帧合并为条目：

```cpp
struct STTSEntry {
    uint32_t sampleCount;   // 该组有多少帧
    uint32_t sampleDelta;    // 每帧的时间增量（× timeScale）
};
```

**例子**：`[(4, 1000), (2, 2000)]` 表示前 4 帧每帧间隔 1000us，后 2 帧每帧间隔 2000us，总共 6 帧。

### 3. CTTS 组合时间偏移表

CTTS 表记录解码时间（PTS）和组合时间（CTS）之间的偏移：

```cpp
struct CTTSEntry {
    uint32_t sampleCount;   // 连续相同偏移的帧数
    int32_t sampleOffset;   // CTS - DTS 偏移量
};
```

**用途**：解决 B/P 帧重排序问题。当视频有 B 帧时，解码顺序和显示顺序不同，CTTS 记录偏移。

### 4. PTS/Index 双向转换算法

**Index → RelativePTS（IndexToRelativePTSProcess）**：
- 从 STTS 累计帧数，找到目标 index 所在的 sttsEntry
- 用 `indexToRelativePTSMaxHeap_` 维护已转换 PTS 的最大堆
- 当堆顶 PTS ≥ 查询 PTS 时，二分查找精确匹配

**RelativePTS → Index（RelativePTSToIndexProcess）**：
- 从首帧 PTS 开始逐 entry 累加：`cumulativePTS += sampleCount × sampleDelta`
- 当 `cumulativePTS > queryPTS` 时，找到目标帧
- 用 `relativePTSToIndexPosition_` 游标避免重复扫描

### 5. absolutePTSIndexZero_ 首帧 PTS 基准

```cpp
int64_t absolutePTSIndexZero_ = INT64_MAX;
```

用于将相对 PTS 转换为绝对 PTS。首帧解析时记录其 PTS，后续 RelativePTS + absolutePTSIndexZero_ = 绝对 PTS。

### 6. 三模式分发（IndexAndPTSConvertMode）

```cpp
enum IndexAndPTSConvertMode {
    GET_FIRST_PTS,              // 获取首帧 PTS
    INDEX_TO_RELATIVEPTS,        // Index → RelativePTS
    RELATIVEPTS_TO_INDEX,        // RelativePTS → Index
};
```

| 模式 | 输入 | 输出 | 典型场景 |
|------|------|------|---------|
| GET_FIRST_PTS | - | 首帧 PTS | Seek 到文件开头 |
| INDEX_TO_RELativEPTS | sample index | 相对 PTS | 已知帧号查 PTS |
| RELATIVEPTS_TO_INDEX | 相对 PTS | sample index | 已知时间查帧号 |

## 关键设计决策

1. **函数指针分发表**（boxParsers）：用 `std::map<string, member_function_pointer>` 替代 if-else，实现灵活的 Box 类型路由
2. **堆排序查找**（IndexToRelativePTSProcess）：用 `std::priority_queue` 实现高效的相对 PTS → Index 逆查
3. **双表联合查询**：STTS+CTTS 联合处理支持 B 帧重排序；仅 STTS 处理无 B 帧场景（如 SP/MP4）
4. **INT64_MAX 哨兵值**：`absolutePTSIndexZero_` 初始值用于判断是否已找到首帧 PTS
5. **timeScale 归一化**：所有 PTS 以 timeScale 为分母归一化到微秒

## 关联场景

- **Seek 操作**：用户拖动进度条 → 已知播放时间 → RelativePTSToIndexProcess → 找到对应 sample index → 解码器跳转
- **码率切换**（BitrateSwitch）：切换码率后需要找到关键帧位置 → IndexToRelativePTSProcess → 确认切换点
- **首帧渲染**：获取首帧 PTS 作为基准 → GET_FIRST_PTS 模式 → 初始化播放时间轴
- **ABR 自适应**：相对 PTS 用于计算缓冲时长（对应 S102 WaterLine 机制）

## 内存占用分析

- `trakInfoVec_`：每轨一个 TrakInfo（包含 STTS/CTTS vector）
- `indexToRelativePTSMaxHeap_`：堆大小受 MAX 帧数限制
- `sttsEntries` / `cttsEntries`：存储整个轨的 sample 表条目（条目数 << 帧数，因合并）
