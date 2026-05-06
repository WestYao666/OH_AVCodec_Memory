---
id: MEM-ARCH-AVCODEC-S52
title: "TimeAndIndexConversion PTS与帧索引转换——MP4/MOV容器STTS/CTTS解析与时域映射"
scope: [AVCodec, MediaEngine, PTS, TimeStamp, MP4, MOV, Demuxer, STTS, CTTS, TimeAndIndexConversion]
status: approved
approved_at: "2026-05-06"
created_by: builder-agent
created_at: "2026-04-26T16:25:00+08:00"
---

# MEM-ARCH-AVCODEC-S52: TimeAndIndexConversion PTS与帧索引转换——MP4/MOV容器STTS/CTTS解析与时域映射

## 1. 概述

`TimeAndIndexConversion` 是 OpenHarmony AVCodec 体系中负责 MP4/MOV 容器文件的时间戳（ PTS ，Presentation Time Stamp ）与帧索引（ Frame Index ）双向转换的核心模块。它直接解析 MP4/MOV 文件的 Box 结构，从中提取 STTS（ Sample Table Time to Sample ）、CTTS（ Composition Time to Sample ）、MDHD（ Media Header ）、HDLR（ Handler ）等原子盒，计算出每个视频帧的播放时间，并建立 PTS ↔ Index 的双向映射关系。

**适用场景**：
- Seek 定位：给定目标 PTS ，查找对应的帧索引位置
- 音视频同步：已知帧索引，计算该帧的 PTS 以与音频轨对齐
- 问题定位：PTS 计算错误导致播放花屏、声音不同步，需排查 STTS/CTTS 解析或 timescale 单位

**关键概念**：
- STTS：解码时间戳（ DTS ）到 sample 序号的映射，记录每个 sample 的持续时间（ sampleDelta ）
- CTTS：PTS 与 DTS 的差值（ composition offset ），用于处理 B 帧（双向预测帧）导致的 PTS ≠ DTS 情况
- PTS = DTS + CTTS_offset（当 CTTS 存在时）

## 2. 核心机制

### 2.1 类层次结构与核心接口

**证据**：`services/media_engine/modules/pts_index_conversion/pts_and_index_conversion.h`

```cpp
class TimeAndIndexConversion {
public:
    TimeAndIndexConversion();
    ~TimeAndIndexConversion();

    // 初始化数据源，解析 MP4/MOV 文件结构
    Status SetDataSource(const std::shared_ptr<MediaSource>& source);

    // 根据相对 PTS（微秒）查询帧索引
    Status GetIndexByRelativePresentationTimeUs(const uint32_t trackIndex,
        const uint64_t relativePresentationTimeUs, uint32_t &index);

    // 根据帧索引查询相对 PTS（微秒）
    Status GetRelativePresentationTimeUsByIndex(const uint32_t trackIndex,
        const uint32_t index, uint64_t &relativePresentationTimeUs);

    // 获取第一个视频轨的 track ID
    Status GetFirstVideoTrackIndex(uint32_t &trackIndex);

private:
    // MP4 Box 解析入口
    void StartParse();                  // 遍历文件所有 Box
    void ParseMoov(uint32_t boxSize);   // 解析 moov 盒
    void ParseTrak(uint32_t boxSize);   // 解析 trak 盒（单个轨道）
    void ParseBox(uint32_t boxSize);    // 递归解析 stbl/minf/mdia

    // STTS / CTTS / MDHD / HDLR 解析
    void ParseStts(uint32_t boxSize);   // 解析 STTS 盒：sampleCount + sampleDelta
    void ParseCtts(uint32_t boxSize);   // 解析 CTTS 盒：sampleCount + sampleOffset
    void ParseMdhd(uint32_t boxSize);   // 解析 MDHD 盒：timescale + duration
    void ParseHdlr(uint32_t boxSize);   // 解析 HDLR 盒：判断 vide/soun/other

    // PTS ↔ Index 转换核心算法
    enum IndexAndPTSConvertMode { GET_FIRST_PTS, INDEX_TO_RELATIVEPTS, RELATIVEPTS_TO_INDEX };
    Status GetPresentationTimeUsFromFfmpegMOV(IndexAndPTSConvertMode mode,
        uint32_t trackIndex, int64_t absolutePTS, uint32_t index);
    Status PTSAndIndexConvertSttsAndCttsProcess(...);  // 同时处理 STTS + CTTS（B帧场景）
    Status PTSAndIndexConvertOnlySttsProcess(...);      // 仅处理 STTS（无 B 帧场景）
    void InitPTSandIndexConvert();                      // 重置转换状态
    void IndexToRelativePTSProcess(int64_t pts, uint32_t index);
    void RelativePTSToIndexProcess(int64_t pts, int64_t absolutePTS);
    void PTSAndIndexConvertSwitchProcess(...);
};
```

**关键数据结构**：

```cpp
struct STTSEntry {
    uint32_t sampleCount;   // 连续相同 duration 的 sample 数
    uint32_t sampleDelta;  // 每个 sample 的持续时间（ timescale 为单位）
};

struct CTTSEntry {
    uint32_t sampleCount;  // 连续相同 composition offset 的 sample 数
    int32_t  sampleOffset; // PTS 与 DTS 的差值（ composition offset ）
};

struct TrakInfo {
    uint32_t trakId;                    // track ID
    TrakType trakType;                  // TRAK_VIDIO / TRAK_AUDIO / TRAK_OTHER
    uint32_t timeScale;                 // 时间刻度（如 90000 ）
    std::vector<STTSEntry> sttsEntries; // STTS 表
    std::vector<CTTSEntry> cttsEntries; // CTTS 表（可能为空）
};

enum IndexAndPTSConvertMode {
    GET_FIRST_PTS,       // 获取首个 PTS
    INDEX_TO_RELATIVEPTS, // 帧索引 → 相对 PTS
    RELATIVEPTS_TO_INDEX // 相对 PTS → 帧索引
};
```

### 2.2 MP4/MOV Box 结构解析流程

**证据**：`services/media_engine/modules/pts_index_conversion/pts_and_index_conversion.cpp` `StartParse()` / `ParseMoov()` / `ParseTrak()` / `ParseBox()`

```
MP4/MOV 文件（File Byte Stream）
│
├─ ftyp (File Type Box)          ← IsMP4orMOV() 通过此盒判断文件类型
│
└─ moov (Movie Box)             ← StartParse() 找到 moov 后进入解析
    │
    ├─ mvhd (Movie Header)       ← 暂未解析
    │
    └─ trak (Track Box) × N     ← ParseMoov() 遍历每个 trak
        │
        ├─ tkhd (Track Header)
        ├─ mdia (Media Box)     ← ParseTrak() 进入 mdia
        │   │
        │   ├─ mdhd (Media Header)  ← ParseMdhd()：读取 timescale
        │   ├─ hdlr (Handler)       ← ParseHdlr()：判断 vide/soun
        │   └─ minf (Media Information)
        │       └─ stbl (Sample Table)
        │           ├─ stts (Sample Table Time)   ← ParseStts()：STTS 表
        │           ├─ ctts (Composition Time)    ← ParseCtts()：CTTS 表（B帧）
        │           ├─ stsz / stz2 (Sample Size)
        │           ├─ stco / co64 (Chunk Offset)
        │           └─ ...其他 sample 表
```

**MP4 Box 解析核心逻辑**（递归深度优先）：

```cpp
void TimeAndIndexConversion::StartParse()
{
    source_->GetSize(fileSize_);
    while (offset_ < fileSize_) {
        BoxHeader header;
        ReadBoxHeader(buffer, header);          // 读取 [size][type] 8 字节头
        uint64_t boxSize = (header.size == 1) ?
            ReadLargeSize(buffer) : header.size; // 大盒（64-bit size）
        if (strncmp(header.type, BOX_TYPE_MOOV, ...) == 0) {
            ParseMoov(boxSize - BOX_HEAD_SIZE);
        } else {
            offset_ += boxSize; // 跳过其他顶级盒
        }
    }
}

void TimeAndIndexConversion::ParseMoov(uint32_t boxSize)
{
    uint64_t parentSize = offset_ + boxSize;
    while (offset_ < parentSize) {
        BoxHeader header;
        ReadBoxHeader(buffer, header);
        if (strncmp(header.type, BOX_TYPE_TRAK, ...) == 0) {
            offset_ += BOX_HEAD_SIZE;
            ParseTrak(header.size - BOX_HEAD_SIZE); // 递归解析 trak
        } else {
            offset_ += header.size; // 跳过非 trak 盒
        }
    }
}
```

**Box 头结构**：

```cpp
struct BoxHeader {
    uint32_t size;   // Box 长度（字节），size=1 时使用 64-bit large size
    char type[5];    // Box 类型（如 "moov", "trak", "stts"），末尾自动填 \0
};
```

**关键约束**：
- `PTS_AND_INDEX_CONVERSION_MAX_FRAMES = 36000`：最大支持 36000 帧/轨道，超出则报错
- 仅支持 MP4/MOV（ ISO Base Media File Format ），`IsMP4orMOV()` 通过检查 ftyp 盒判断文件类型
- 文件偏移量 `offset_` 全程维护，确保顺序读取所有 Box

### 2.3 STTS 与 CTTS 解析

**证据**：`ParseStts()` / `ParseCtts()` 实现

**STTS（ Time to Sample Box ）解析**：

```cpp
void TimeAndIndexConversion::ParseStts(uint32_t boxSize)
{
    // STTS 格式：[version_and_flags(4)][entry_count(4)][entry(8)*N]
    // 每条 entry：[sample_count(4)][sample_delta(4)]
    // sample_delta = 该 sample 的持续时间，以 media timescale 为单位
    uint32_t entryCount = ntohl(*(ptr + 4)); // 网络字节序转换
    for (uint32_t i = 0; i < entryCount; ++i) {
        STTSEntry entry;
        entry.sampleCount = ntohl(*entryPtr);
        entry.sampleDelta = ntohl(*(entryPtr + 4));
        curTrakInfo_.sttsEntries.push_back(entry);
        entryPtr += sizeof(STTSEntry);
    }
}
```

**CTTS（ Composition Time to Sample Box ）解析**：

```cpp
void TimeAndIndexConversion::ParseCtts(uint32_t boxSize)
{
    // CTTS 格式：[version_and_flags(4)][entry_count(4)][entry(8)*N]
    // 每条 entry：[sample_count(4)][sample_offset(4)]
    // sample_offset = PTS - DTS（正数表示 P/B 帧延迟，负数表示 reorder 前的帧）
    uint32_t entryCount = ntohl(*(ptr + 4));
    for (uint32_t i = 0; i < entryCount; ++i) {
        CTTSEntry entry;
        entry.sampleCount = ntohl(*entryPtr);
        entry.sampleOffset = static_cast<int32_t>(ntohl(*(entryPtr + 4)));
        curTrakInfo_.cttsEntries.push_back(entry);
        entryPtr += sizeof(CTTSEntry);
    }
}
```

**CTTS 的作用**：
- I/P 帧：PTS = DTS，CTTS entry 的 offset = 0
- B 帧：PTS > DTS（显示延迟），CTTS entry 的 offset > 0
- 当 CTTS 表为空时（无 B 帧的纯 I/P 编码流），所有帧的 PTS = DTS

### 2.4 PTS ↔ Index 双向转换算法

**证据**：`GetIndexByRelativePresentationTimeUs()` / `GetRelativePresentationTimeUsByIndex()` / `PTSAndIndexConvertSttsAndCttsProcess()`

**PTS → Index（ Seek 场景）**：

```cpp
Status TimeAndIndexConversion::GetIndexByRelativePresentationTimeUs(
    const uint32_t trackIndex,
    const uint64_t relativePresentationTimeUs,
    uint32_t &index)
{
    // 1. 获取首个 PTS（ absolutePTSIndexZero_ ）：建立时间零点基准
    InitPTSandIndexConvert();
    GetPresentationTimeUsFromFfmpegMOV(GET_FIRST_PTS, trackIndex,
        relativePresentationTimeUs, index);

    // 2. 计算绝对 PTS（相对 PTS + 时间零点）
    int64_t absolutePTS = static_cast<int64_t>(relativePresentationTimeUs)
                           + absolutePTSIndexZero_;

    // 3. 在 STTS/CTTS 联合遍历中找到目标 PTS 对应的帧序号
    GetPresentationTimeUsFromFfmpegMOV(RELATIVEPTS_TO_INDEX, trackIndex,
        absolutePTS, index);

    // 4. 二分选择：选择 PTS 差值最小的那一帧
    if (relativePTSToIndexLeftDiff_ < relativePTSToIndexRightDiff_) {
        index = relativePTSToIndexPosition_ - 1;
    } else {
        index = relativePTSToIndexPosition_;
    }
    return Status::OK;
}
```

**Index → PTS（音视频同步场景）**：

```cpp
Status TimeAndIndexConversion::GetRelativePresentationTimeUsByIndex(
    const uint32_t trackIndex,
    const uint32_t index,
    uint64_t &relativePresentationTimeUs)
{
    InitPTSandIndexConvert();
    GetPresentationTimeUsFromFfmpegMOV(GET_FIRST_PTS, trackIndex,
        0, index);

    // 累积遍历 STTS 表，计算第 index 帧的累积 PTS
    GetPresentationTimeUsFromFfmpegMOV(INDEX_TO_RELATIVEPTS, trackIndex,
        0, index);

    // 从最大堆中取出该帧的 PTS
    int64_t relativepts = indexToRelativePTSMaxHeap_.top() - absolutePTSIndexZero_;
    relativePresentationTimeUs = static_cast<uint64_t>(relativepts);
    return Status::OK;
}
```

**STTS + CTTS 联合遍历算法**（ `PTSAndIndexConvertSttsAndCttsProcess` ）：

```
输入：目标 PTS（或目标 Index），STTS entries[], CTTS entries[]

STTS entry: [sampleCount, sampleDelta]   → 该 entry 包含 sampleCount 个 sample，
                                          每个 sample 持续 sampleDelta 微秒（× timescale）

CTTS entry: [sampleCount, sampleOffset] → 该 entry 包含 sampleCount 个 sample，
                                           每个 sample 的 PTS = DTS + sampleOffset

算法：双指针同时遍历 STTS 和 CTTS，累加 sample 数，直到找到目标帧

示例（ B 帧流）：
  STTS: [count=2, delta=1000][count=3, delta=1000]  → 5 个 sample，DTS: 0, 1000, 2000, 3000, 4000
  CTTS: [count=1, offset=0][count=2, offset=500][count=2, offset=0]
       → sample 0: PTS=0,  sample 1-2: PTS=1500/2000,  sample 3-4: PTS=3000/4000
```

**MDHD（ Media Header Box ）解析**：

```cpp
void TimeAndIndexConversion::ParseMdhd(uint32_t boxSize)
{
    // MDHD 格式（version=0）：[version_and_flags][creation_time][modification_time]
    //                         [timescale(4)][duration]
    uint8_t version = ptr[0];
    size_t timeScaleOffset = (version == 1) ?
        sizeof(uint32_t)*3 + sizeof(uint64_t)*2 : // version=1 用 64-bit 时间
        sizeof(uint32_t)*3;                         // version=0 用 32-bit 时间
    uint32_t timeScale = ntohl(*(ptr + timeScaleOffset));
    curTrakInfo_.timeScale = timeScale; // 通常是 90000、48000、44100 等
}
```

### 2.5 HDLR 解析与轨道类型判断

**证据**：`ParseHdlr()`

```cpp
void TimeAndIndexConversion::ParseHdlr(uint32_t boxSize)
{
    // HDLR 盒中 handler_type 在 offset=8 位置（ version_flags(4) + reserved(4) 后）
    std::string handlerType = "";
    handlerType.append(1, static_cast<char>(ptr[8]));  // 第 1 字符
    handlerType.append(1, static_cast<char>(ptr[9]));  // 第 2 字符
    handlerType.append(1, static_cast<char>(ptr[10])); // 第 3 字符
    handlerType.append(1, static_cast<char>(ptr[11])); // 第 4 字符

    if (handlerType == "soun") {
        curTrakInfo_.trakType = TrakType::TRAK_AUDIO;
    } else if (handlerType == "vide") {
        curTrakInfo_.trakType = TrakType::TRAK_VIDIO;
    } else {
        curTrakInfo_.trakType = TrakType::TRAK_OTHER;
    }
}
```

### 2.6 与其他组件的关系

| 组件 | 关系 | 说明 |
|------|------|------|
| MediaDemuxer（S41） | 调用方 | MediaDemuxer 使用 TimeAndIndexConversion 进行 Seek 和 PTS 查询 |
| MediaSource | 数据源 | TimeAndIndexConversion 持有 MediaSource，从文件读取 Box 数据 |
| Av1Decoder / H264Decoder（S39/S51） | PTS 用户 | 解码器输出帧的 PTS 由本模块计算 |
| MediaSyncManager（S22） | PTS 消费者 | 音视频同步使用本模块提供的 PTS 进行对齐 |

## 3. 证据索引

| # | 类型 | 路径 | 说明 |
|---|------|------|------|
| 1 | code | `services/media_engine/modules/pts_index_conversion/pts_and_index_conversion.h` | 类定义、公开接口、私有成员、枚举、结构体 |
| 2 | code | `services/media_engine/modules/pts_index_conversion/pts_and_index_conversion.cpp` | 完整实现（640 行），StartParse / ParseMoov / ParseTrak / ParseStts / ParseCtts / PTS 转换算法 |
| 3 | test | `test/fuzztest/ptsandindexconversion_fuzzer/` | 模糊测试用例，验证边界条件 |

## 4. 关联记忆

- **MEM-ARCH-AVCODEC-S41**：DemuxerFilter 解封装过滤器，MediaDemuxer 使用本模块
- **MEM-ARCH-AVCODEC-S22**：MediaSyncManager 音视频同步，以本模块输出的 PTS 为锚点
- **MEM-ARCH-AVCODEC-S39**：AVCodecVideoDecoder，视频解码器消费本模块计算的 PTS

## 5. 已知限制与注意事项

1. **仅支持 MP4/MOV**：`IsMP4orMOV()` 只识别 ftyp 盒，不支持 MKV、AVI 等其他容器
2. **最大帧数限制**：`PTS_AND_INDEX_CONVERSION_MAX_FRAMES = 36000`，长视频可能超出此限制
3. **B 帧支持**：CTTS 表为空时视为无 B 帧的简单流；CTTS 存在时仅支持 version=0（32-bit offset）
4. **字节序**：MP4 规范要求大端序（ network byte order ），所有多字节数值需用 `ntohl()` 转换
5. **不支持加密轨**：本模块不解析 sgpd/sgpp 等样本组描述盒

---
*Builder Agent | 草案生成时间：2026-04-26T16:25:00+08:00*
