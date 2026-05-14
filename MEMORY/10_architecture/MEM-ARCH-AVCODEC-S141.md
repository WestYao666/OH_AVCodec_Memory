---
type: architecture
id: MEM-ARCH-AVCODEC-S141
status: pending_approval
created_at: "2026-05-15T02:53:55+08:00"
updated_at: "2026-05-15T02:53:55+08:00"
created_by: builder
topic: PTS索引转换模块——TimeAndIndexConversion 640行cpp（Box解析/moov遍历/STTS+CTTS+STSC+STSZ解析）/相对时间戳↔样本索引互转
scope: [AVCodec, MediaEngine, PTS, Index, Conversion, TimeAndIndexConversion, MP4, MOV, STTS, CTTS, STSC, STSZ, Sample, RelativePresentationTime, Track, Box, moov, trak, mdia]
created_at: "2026-05-15T02:53:55+08:00"
summary: PTS索引转换模块——TimeAndIndexConversion 640行cpp（Box解析/moov遍历/STTS+CTTS+STSC+STSZ解析）+相对时间戳↔样本索引互转（GetIndexByRelativePresentationTimeUs/GetRelativePresentationTimeUsByIndex）+TrakInfo/STTSEntry/CTTSEntry三数据结构，与S79(S58)/S96关联
source_repo: /home/west/av_codec_repo
source_root: services/media_engine/modules/pts_index_conversion
evidence_version: local_mirror
---

## 一、架构总览

TimeAndIndexConversion PTS索引转换模块位于 `services/media_engine/modules/pts_index_conversion/` 目录，共 640行 cpp + 150行 h，负责将 MP4/MOV 容器中的绝对时间戳（PTS）转换为相对呈现时间（RelativePresentationTimeUs）和样本索引（SampleIndex）的互转。

**定位**：用于 MP4 点播场景的 Seek 辅助，根据目标 PTS 找到最近的 Keyframe 索引，或根据索引反查 PTS。与 MPEG4DemuxerPlugin（S79/S58）配合使用，是 MP4 解封装的辅助模块。

## 二、文件清单与行号级证据

| 文件 | 行数 | 说明 |
|------|------|------|
| `pts_and_index_conversion.cpp` | 640 | PTS 索引转换实现（Box解析/moov遍历/索引查询） |
| `pts_and_index_conversion.h` | 150 | TimeAndIndexConversion 类定义 + TrakInfo/STTSEntry/CTTSEntry/BoxHeader 结构体 |

## 三、核心类定义（pts_and_index_conversion.h:46-115）

```cpp
// pts_and_index_conversion.h:46-65 - 索引/PTS转换模式枚举
enum IndexAndPTSConvertMode : unsigned int {
    INDEX_TO_PTS = 0,  // 样本索引 → 相对呈现时间
    PTS_TO_INDEX = 1   // 相对呈现时间 → 样本索引
};

enum TrakType : unsigned int {
    TRAK_TYPE_VIDEO = 0,
    TRAK_TYPE_AUDIO = 1,
    TRAK_TYPE_UNKNOWN = 2
};

// pts_and_index_conversion.h:66-100 - 关键成员变量
class TimeAndIndexConversion {
    std::map<std::string, void(TimeAndIndexConversion::*)(uint32_t)> boxParsers; // Box解析器注册表
    uint64_t mediaDataSize_ = 0;
    uint64_t offset_ = 0;          // 当前读取偏移
    uint64_t fileSize_ = 0;        // 文件总大小
    uint32_t curTrakInfoIndex_ = 0; // 当前trak索引
    std::vector<TrakInfo> trakInfos_; // 所有轨道信息
    std::map<uint32_t, uint32_t> indexMap_;  // 索引映射
};
```

## 四、核心数据结构

### 4.1 STTSEntry / CTTSEntry（pts_and_index_conversion.h:76-84）

```cpp
// pts_and_index_conversion.h:76-84 - 时间到样本次数映射
struct STTSEntry {
    uint32_t sampleCount;   // 样本次数
    uint32_t sampleDelta;    // 样本次数增量（时间增量）
};

struct CTTSEntry {
    uint32_t sampleCount;    // 样本次数
    int32_t sampleOffset;    // 时间偏移（CTTS =Composition Time Stamp）
};

// pts_and_index_conversion.cpp - STTS/CTTS 解析
// 用于计算每个样本的 PTS = sum(sampleDelta * i) + CTTS_offset
```

### 4.2 TrakInfo（pts_and_index_conversion.h:86-93）

```cpp
// pts_and_index_conversion.h:86-93 - 轨道信息
struct TrakInfo {
    uint32_t trakId;         // 轨道ID
    uint32_t trakType;       // 轨道类型（VIDEO/AUDIO/UNKNOWN）
    uint32_t timeScale;      // 时间刻度（timeScale=90000 表示90kHz）
    // STTSEntry/CTTSEntry/STSCEntry/STSZEntry 表
};
```

### 4.3 BoxHeader（pts_and_index_conversion.h:71-75）

```cpp
// pts_and_index_conversion.h:71-75 - MP4 Box 头
struct BoxHeader {
    uint32_t size;          // Box 大小（包含头）
    uint32_t type;          // Box 类型（ftyp/moov/trak/mdia/minf/stbl 等）
};
```

## 五、核心函数流程

### 5.1 StartParse 主流程（pts_and_index_conversion.cpp:94-127）

```cpp
// pts_and_index_conversion.cpp:94 - 解析入口
void TimeAndIndexConversion::StartParse()
{
    // 1. 读取 BoxHeader (size + type)
    // BOX_HEAD_SIZE = 8
    // → ReadBoxHeader(buffer, header)
    
    // 2. 解析 Box 类型
    // header.size = ntohl(ptr)     // 行 155
    // header.type = ntohl(ptr + 4) // 行 159
    
    // 3. 递归解析：
    // boxParsers["ftyp"] = &TimeAndIndexConversion::ParseFtyp
    // boxParsers["moov"] = &TimeAndIndexConversion::ParseMoov    // 行 178
    // boxParsers["trak"] = &TimeAndIndexConversion::ParseTrak
    // boxParsers["mdia"] = &TimeAndIndexConversion::ParseMdia
    // boxParsers["stbl"] = &TimeAndIndexConversion::ParseStbl
}
```

### 5.2 GetFirstVideoTrackIndex（pts_and_index_conversion.cpp:66）

```cpp
// pts_and_index_conversion.cpp:66 - 获取第一个视频轨道索引
Status TimeAndIndexConversion::GetFirstVideoTrackIndex(uint32_t &trackIndex)
{
    // 遍历 trakInfos_，找到第一个 trakType == TRAK_TYPE_VIDEO
    // trackIndex = trakInfos_[index].trakId
}
```

### 5.3 GetIndexByRelativePresentationTimeUs（pts_and_index_conversion.cpp:54-55）

```cpp
// pts_and_index_conversion.h:54 - PTS → 索引转换
Status GetIndexByRelativePresentationTimeUs(
    const uint32_t trackIndex,
    const uint64_t relativePresentationTimeUs,
    uint32_t &index);

// 实现逻辑：
// 1. 找到 trackIndex 对应的 TrakInfo
// 2. 遍历 STTSEntry 表，计算累计时间
// 3. 找到 relativePresentationTimeUs 所属的样本区间
// 4. 返回样本索引
```

### 5.4 GetRelativePresentationTimeUsByIndex（pts_and_index_conversion.cpp:56-57）

```cpp
// pts_and_index_conversion.h:56 - 索引 → PTS 转换
Status GetRelativePresentationTimeUsByIndex(
    const uint32_t trackIndex,
    const uint32_t index,
    uint64_t &relativePresentationTimeUs);

// 实现逻辑：
// 1. 找到 trackIndex 对应的 TrakInfo
// 2. 遍历 STTSEntry 表，计算 index 的累计时间
// 3. 应用 CTTS 偏移（sampleOffset）
// 4. 返回 relativePresentationTimeUs
```

### 5.5 ReadLargeSize（pts_and_index_conversion.cpp:127-145）

```cpp
// pts_and_index_conversion.cpp:127-145 - 大端读取64位整数
void TimeAndIndexConversion::ReadLargeSize(std::shared_ptr<Buffer> buffer, uint64_t &largeSize)
{
    // uint64_t largeSize = (high << 32) | low
    // 使用 ntohl 转换字节序（大端→主机序）
    // BOX_HEAD_LARGE_SIZE = 16（当 Box size == 1 时使用）
}
```

## 六、Box 解析器注册表

```cpp
// pts_and_index_conversion.h:103-113 - Box 解析器注册表
std::map<std::string, void(TimeAndIndexConversion::*)(uint32_t)> boxParsers = {
    {"ftyp", &TimeAndIndexConversion::ParseFtyp},
    {"moov", &TimeAndIndexConversion::ParseMoov},
    {"trak", &TimeAndIndexConversion::ParseTrak},
    {"mdia", &TimeAndIndexConversion::ParseMdia},
    {"minf", &TimeAndIndexConversion::ParseMinf},
    {"stbl", &TimeAndIndexConversion::ParseStbl},
    {"stts", &TimeAndIndexConversion::ParseStts},
    {"ctts", &TimeAndIndexConversion::ParseCtts},
    {"stsc", &TimeAndIndexConversion::ParseStsc},
    {"stsz", &TimeAndIndexConversion::ParseStsz},
    {"stco", &TimeAndIndexConversion::ParseStco},
    // ... 更多 Box 类型
};

// pts_and_index_conversion.cpp:94 - 解析调度
void TimeAndIndexConversion::StartParse()
{
    while (offset_ < fileSize_) {
        ReadBoxHeader(buffer, header);
        auto parser = boxParsers.find(header.typeStr);
        if (parser != boxParsers.end()) {
            (this->*parser->second)(header.size);
        }
        offset_ += header.size;
    }
}
```

## 七、与相关 S-series 记忆的关联

| 关联记忆 | 关系 | 说明 |
|---------|------|------|
| S79（MPEG4DemuxerPlugin） | 上游容器解析 | MPEG4DemuxerPlugin 解析 MP4/MOV 容器，TimeAndIndexConversion 辅助 Seek |
| S58（MPEG4BoxParser） | 并列 | S58 聚焦 Box 解析器引擎（五级原子），S141 聚焦 PTS 索引转换 |
| S96（PTS 索引转换） | 同级 | S96 为概述，S141 提供行号级证据 |
| S75（MediaDemuxer 六组件） | 下游消费者 | MediaDemuxer 使用 TimeAndIndexConversion 做 Seek 辅助 |

---

_builder-agent: S141 draft generated 2026-05-15T02:53:55+08:00, pending approval_