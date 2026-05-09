---
id: MEM-ARCH-AVCODEC-S108
title: "TimeAndIndexConversion 时间戳索引转换器——MP4 STTS/CTTS Box 解析与 PTS/Index 双向转换"
scope: [AVCodec, MediaEngine, Demuxer, PTS, Index, MP4, MOV, STTS, CTTS, TimeAndIndexConversion, BitrateSwitch]
status: approved
approved_at: "2026-05-09T21:02:00+08:00"
approved_by: ~pending~
approval_submitted_at: "2026-05-09T12:48:00+08:00"
created_by: builder-agent
created_at: "2026-05-09T12:30:00+08:00"
关联主题: [S101(StreamDemuxer), S102(SampleQueueController), S97(DemuxerPluginManager), S69(MediaDemuxer)]
---

## Status

```yaml
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

1. **Index → RelativePTS**：已知 sample index，反向查找对应 PTS（堆排序查找）
2. **RelativePTS → Index**：已知相对 PTS，正向查找对应 sample index（二分搜索）
3. **MP4 Box 递归解析**：ftyp → moov → trak → mdia → minf → stbl → stts/ctts/hdlr/mdhd
4. **首帧 PTS 定位**：扫描 stts 找到第一帧的 PTS 基准（absolutePTSIndexZero_）

---

## Evidence（源码行号）

### pts_and_index_conversion.h (150 行)

| 符号 | 位置 | 说明 |
|------|------|------|
| `BOX_TYPE_FTYP/MOOV/TRAK/MDIA/MINF/STBL/STTS/CTTS/HDLR/MDHD` | pts_and_index_conversion.h:30-40 | MP4 Box 类型常量（4字符标识） |
| `class TimeAndIndexConversion` | pts_and_index_conversion.h:46 | PTS/Index 转换主类 |
| `IndexAndPTSConvertMode` 枚举 | pts_and_index_conversion.h:59-61 | 三模式枚举：GET_FIRST_PTS / INDEX_TO_RELATIVEPTS / RELATIVEPTS_TO_INDEX |
| `TrakType` 枚举 | pts_and_index_conversion.h:63-65 | 轨类型：TRAK_OTHER / TRAK_AUDIO / TRAK_VIDIO |
| `struct BoxHeader { largeSize, type, size }` | pts_and_index_conversion.h:71-74 | MP4 Box 头（8或16字节变长） |
| `struct STTSEntry { sampleCount, sampleDelta }` | pts_and_index_conversion.h:76-80 | STTS 表条目：连续相同时间戳的帧数+帧间隔 |
| `struct CTTSEntry { sampleCount, sampleOffset }` | pts_and_index_conversion.h:82-86 | CTTS 表条目：连续相同组合时间的帧数+偏移量 |
| `struct TrakInfo { trakId, trakType, timeScale, sttsEntries, cttsEntries }` | pts_and_index_conversion.h:88-94 | 单轨元数据（ID/类型/时间基/STTS/CTTS） |
| `boxParsers` 分发表 | pts_and_index_conversion.h:103-112 | Box 解析器函数指针映射（9个 Box 类型路由） |
| `Status GetFirstVideoTrackIndex(uint32_t&)` | pts_and_index_conversion.h:53 | 获取第一个视频轨索引 |
| `Status GetIndexByRelativePresentationTimeUs(uint32_t, int64_t, uint32_t&)` | pts_and_index_conversion.h:54-58 | RelativePTS → Index（正向查找） |
| `Status GetRelativePresentationTimeUsByIndex(uint32_t, uint32_t, int64_t&)` | pts_and_index_conversion.h:56-58 | Index → RelativePTS（反向查找） |
| `Status GetPresentationTimeUsFromFfmpegMOV(...)` | pts_and_index_conversion.h:126-128 | 驱动转换的主函数（四参数分发） |
| `std::vector<TrakInfo> trakInfoVec_` | pts_and_index_conversion.h:97 | 多轨元数据 vector |
| `int64_t absolutePTSIndexZero_` | pts_and_index_conversion.h:115 | 首帧 PTS 基准（INT64_MAX 初始值） |
| `std::priority_queue<int64_t> indexToRelativePTSMaxHeap_` | pts_and_index_conversion.h:116 | Index→RelativePTS 最大堆 |
| `int64_t relativePTSToIndexLeftDiff_ / RightDiff_` | pts_and_index_conversion.h:122-123 | RelativePTS→Index 二分搜索左右边界差值 |

### pts_and_index_conversion.cpp (640 行)

| 符号 | 位置 | 说明 |
|------|------|------|
| `LABEL` 日志标签 | pts_and_index_conversion.cpp:27 | `LOG_DOMAIN_DEMUXER / "TimeAndIndexConversion"` |
| `BOX_HEAD_SIZE = 8` | pts_and_index_conversion.cpp:32 | 标准 Box 头大小 |
| `BOX_HEAD_LARGE_SIZE = 16` | pts_and_index_conversion.cpp:34 | 扩展 Box 头大小（大文件 >2GB） |
| `PTS_AND_INDEX_CONVERSION_MAX_FRAMES = 36000` | pts_and_index_conversion.cpp:33 | 最大帧数保护上限 |
| `ReadBufferFromDataSource()` | pts_and_index_conversion.cpp:77-93 | 从 DataSource 读取指定大小数据 |
| `StartParse()` | pts_and_index_conversion.cpp:94-115 | 启动解析入口，先读 ftyp 再递归 moov |
| `ReadLargeSize()` | pts_and_index_conversion.cpp:127-144 | 读取 64 位 Box 尺寸（ntohl 网络字节序） |
| `ReadBoxHeader()` | pts_and_index_conversion.cpp:146-176 | 解析 Box 头（8或16字节），区分 small/large size |
| `ParseMoov()` | pts_and_index_conversion.cpp:178-209 | 解析 moov Container Box（递归子 Box） |
| `ParseTrak()` | pts_and_index_conversion.cpp:210-220 | 解析 trak Track Box |
| `ParseBox()` | pts_and_index_conversion.cpp:221-253 | 通用 Box 递归解析器（跳转到 stbl 层） |
| `ParseCtts()` | pts_and_index_conversion.cpp:254-290 | 解析 ctts Composition Time-to-Sample（网络字节序 ntohl） |
| `ParseStts()` | pts_and_index_conversion.cpp:291-326 | 解析 stts Time-to-Sample（网络字节序 ntohl） |
| `ParseHdlr()` | pts_and_index_conversion.cpp:327-362 | 解析 hdlr Handler Box（识别 video/audio 轨） |
| `ParseMdhd()` | pts_and_index_conversion.cpp:363-405 | 解析 mdhd Media Header Box（提取 timeScale） |
| `InitPTSandIndexConvert()` | pts_and_index_conversion.cpp:406-422 | 初始化转换器，重置所有成员状态 |
| `GetFirstVideoTrackIndex()` | pts_and_index_conversion.cpp:66-75 | 遍历 trakInfoVec_ 找第一个 TRAK_VIDIO |
| `GetIndexByRelativePresentationTimeUs()` | pts_and_index_conversion.cpp:429-465 | RelativePTS → Index 主入口 |
| `GetRelativePresentationTimeUsByIndex()` | pts_and_index_conversion.cpp:460-486 | Index → RelativePTS 主入口 |
| `GetPresentationTimeUsFromFfmpegMOV()` | pts_and_index_conversion.cpp:576-588 | 驱动转换的主函数（三模式分发） |
| `PTSAndIndexConvertSwitchProcess()` | pts_and_index_conversion.cpp:589-604 | 模式分发器（GET_FIRST_PTS 记录 absolutePTSIndexZero_） |
| `IndexToRelativePTSProcess()` | pts_and_index_conversion.cpp:608-620 | Index → RelativePTS 堆排序逆查 |
| `RelativePTSToIndexProcess()` | pts_and_index_conversion.cpp:621-640 | RelativePTS → Index 二分搜索 |

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

MP4 文件结构：

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

**Box 解析器分发表**（函数指针路由）：
```cpp
// pts_and_index_conversion.h:103-112
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
// pts_and_index_conversion.h:76-80
struct STTSEntry {
    uint32_t sampleCount;   // 该组有多少帧
    uint32_t sampleDelta;   // 每帧的时间增量（× timeScale）
};
```

**例子**：`[(4, 1000), (2, 2000)]` 表示前 4 帧每帧间隔 1000us，后 2 帧每帧间隔 2000us。

### 3. CTTS 组合时间偏移表

CTTS 表记录解码时间（PTS）和显示时间（CTS）之间的偏移（B/P 帧重排序）：

```cpp
// pts_and_index_conversion.h:82-86
struct CTTSEntry {
    uint32_t sampleCount;   // 连续相同偏移的帧数
    int32_t sampleOffset;   // CTS - DTS 偏移量（可负值，B帧）
};
```

### 4. PTS/Index 双向转换算法

**Index → RelativePTS（IndexToRelativePTSProcess）**：
```cpp
// pts_and_index_conversion.cpp:608-620
void TimeAndIndexConversion::IndexToRelativePTSProcess(int64_t pts, uint32_t index)
{
    // 从 STTS 累计帧数找到目标 index 所在 sttsEntry
    // 用 indexToRelativePTSMaxHeap_ 维护已转换 PTS 的最大堆
    // 堆顶 PTS ≥ 查询 PTS 时，二分查找精确匹配
}
```

**RelativePTS → Index（RelativePTSToIndexProcess）**：
```cpp
// pts_and_index_conversion.cpp:621-640
void TimeAndIndexConversion::RelativePTSToIndexProcess(int64_t pts, int64_t absolutePTS)
{
    // 从首帧 PTS 开始逐 entry 累加: cumulativePTS += sampleCount × sampleDelta
    // 用 relativePTSToIndexLeftDiff_/RightDiff_ 二分搜索精确匹配
}
```

### 5. 三模式分发（GetPresentationTimeUsFromFfmpegMOV）

```cpp
// pts_and_index_conversion.cpp:576-588
Status TimeAndIndexConversion::GetPresentationTimeUsFromFfmpegMOV(
    IndexAndPTSConvertMode mode, uint32_t trackIndex, int64_t absolutePTS, uint32_t index)
{
    return HasCTTS
        ? PTSAndIndexConvertSttsAndCttsProcess(mode, absolutePTS, index)  // B/P 帧
        : PTSAndIndexConvertOnlySttsProcess(mode, absolutePTS, index);     // 无 B 帧
}
```

### 6. 首帧 PTS 基准（absolutePTSIndexZero_）

```cpp
// pts_and_index_conversion.cpp:594
absolutePTSIndexZero_ = pts < absolutePTSIndexZero_ ? pts : absolutePTSIndexZero_;
```

### 7. MAX_FRAMES 边界保护

```cpp
// pts_and_index_conversion.cpp:33,424
const uint32_t PTS_AND_INDEX_CONVERSION_MAX_FRAMES = 36000;
// pts_and_index_conversion.cpp:424
FALSE_RETURN_V_MSG_E(frames <= PTS_AND_INDEX_CONVERSION_MAX_FRAMES, false,
    "Frame count exceeds limit");
```

## 关键设计决策

1. **函数指针分发表**（boxParsers）：用 `std::map<string, member_function_pointer>` 替代 if-else，实现灵活的 Box 类型路由
2. **堆排序逆查**（IndexToRelativePTSProcess）：用 `std::priority_queue<int64_t>` 实现高效的相对 PTS 逆查
3. **双表分支**（HasCTTS 判定）：有 B/P 帧时联合 STTS+CTTS；无 B 帧时仅用 STTS（避免无谓开销）
4. **INT64_MAX 哨兵值**：`absolutePTSIndexZero_` 初始值用于判断是否已找到首帧 PTS
5. **网络字节序**（ntohl）：MP4 容器使用大端序，解析时需字节序转换
6. **timeScale 归一化**：所有 PTS 以 timeScale 为分母归一化到微秒（×1000000 / timeScale）

## 关联场景

- **Seek 操作**：用户拖动进度条 → 已知播放时间 → RelativePTSToIndexProcess → 找到对应 sample index → 解码器跳转
- **码率切换**（BitrateSwitch）：切换码率后需要找到关键帧位置 → IndexToRelativePTSProcess → 确认切换点
- **首帧渲染**：获取首帧 PTS 作为基准 → GET_FIRST_PTS 模式 → 初始化播放时间轴
- **ABR 自适应**：相对 PTS 用于计算缓冲时长（对应 S102 WaterLine 机制）
