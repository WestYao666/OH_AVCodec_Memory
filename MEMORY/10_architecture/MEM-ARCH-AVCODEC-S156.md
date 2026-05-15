# MEM-ARCH-AVCODEC-S156 (DRAFT → pending_approval)

## Metadata

- **Mem ID**: MEM-ARCH-AVCODEC-S156
- **Topic**: MPEG4 Box Parser架构——MPEG4AtomParser 4378行解析引擎与MPEG4SampleHelper样本索引构建
- **Component**: `services/media_engine/plugins/demuxer/mpeg4_demuxer/`
- **Files**: `mpeg4_box_parser.cpp` (4378行) + `mpeg4_box_parser.h` (287行) + `mpeg4_sample_helper.cpp` (1009行) + `mpeg4_sample_helper.h` (164行)
- **Author**: Builder Agent
- **Created**: 2026-05-15
- **Status**: ⏳ pending_approval
- **Source**: 本地镜像 `/home/west/av_codec_repo`

---

## 一、主题概述

MPEG4 Box Parser 是 OH AVCodec 中 MP4/M4A/M4V/3GP/3G2/MOV 容器解析的核心引擎，负责将 ISO Base Media File Format（ISO/IEC 14496-12）的树状 Box 结构解析为可用的 Track 元数据与样本索引。与 FFmpegDemuxerPlugin（S123 分片流式）并列，构成 demuxer 插件体系的双引擎之一。

---

## 二、核心数据结构

### 2.1 MPEG4AtomParser 类

路径：`services/media_engine/plugins/demuxer/mpeg4_demuxer/mpeg4_box_parser.h:36-139`

```cpp
class MPEG4AtomParser {
public:
    explicit MPEG4AtomParser();
    ~MPEG4AtomParser();
    struct CodecParams {
        std::unique_ptr<uint8_t[]> data = nullptr;
        int64_t extradataSize = 0;
        TrackType trackType = INVALID_TYPE;
        HdrBoxInfo hdrBoxInfo {false, false, false};
    };
    struct Track {
        std::shared_ptr<Track> next = nullptr;
        uint32_t trackIndex = 0;
        int32_t trackId = 0;
        std::shared_ptr<MPEG4SampleHelper> sampleHelper = nullptr;
        std::unique_ptr<int32_t[]> displayMatrix = nullptr;  // 3x3 display matrix
        bool hasDisplayMatrix = false;
        uint32_t currentSampleIndex = 0;
        int64_t duration = 0;
        int64_t totalElstDuration = 0;
        int64_t sidxDuration = 0;
        int64_t elstInitEmptyEdit = 0;
        int64_t elstShiftStartTime = 0;
        CodecParams codecParms{};
    };
    struct FragmentEntry {
        int64_t firstDts = -1;
        int64_t moofOffset;
        int64_t nextAtomOffset = -1;
        int64_t duration = -1;
        bool hasRead = false;
    };
    // ... 省略 getter 方法
private:
    std::shared_ptr<Track> firstTrack_;
    std::shared_ptr<Track> lastTrack_;
    std::shared_ptr<Track> currentTrack_;
    using ParseFunction = Status (MPEG4AtomParser::*)(MPEG4Atom atom, int32_t depth, ParseContext* ctx);
    ParseFunction FindAtomParser(const MPEG4Atom& atom, ParseContext* ctx);
    std::unordered_map<int32_t, ParseFunction> MPEG4ParseTable_;
    // ... 私有成员
};
```

**证据1**：`mpeg4_box_parser.h:139` — `ParseFunction` 类型别名定义，60+个原子解析函数指针表

**证据2**：`mpeg4_box_parser.h:36-130` — `Track` 双链表结构（含sampleHelper/displayMatrix/elst偏移）

**证据3**：`mpeg4_box_parser.h:66-73` — `FragmentEntry` 分片条目（moofOffset/firstDts/nextAtomOffset）

### 2.2 MPEG4SampleHelper 类

路径：`services/media_engine/plugins/demuxer/mpeg4_demuxer/mpeg4_sample_helper.h:31-164`

```cpp
class MPEG4SampleHelper {
public:
    enum TrunFlag : uint32_t {
        TRUN_DATA_OFFSET        = 0x01,
        TRUN_FIRST_SAMPLE_FLAGS = 0x04,
        TRUN_SAMPLE_DURATION    = 0x100,
        TRUN_SAMPLE_SIZE        = 0x200,
        TRUN_SAMPLE_FLAGS       = 0x400,
        TRUN_SAMPLE_CTS         = 0x800
    };
    struct SampleIndexEntry {
        int64_t dts;
        int64_t pts;
        int64_t pos;
        uint32_t flag;
        int32_t size;
    };
    struct CttsEntry {
        uint32_t count;
        int32_t delta;
    };
    // 9个 Set*Params 方法 + BuildSampleIndexEntries
    Status FindSyncSampleAtTime(int64_t reqTime, bool isBaseTrack, SeekMode flag, uint32_t &sampleIndex);
    Status SetTimeToSampleParams(int64_t dataOffset, size_t dataSize);
    Status SetCompositionTimeToSampleParams(int64_t dataOffset, size_t dataSize);
    Status SetSyncSampleParams(int64_t dataOffset, size_t dataSize);
    Status SetSampleSizeParams(uint32_t type, int64_t dataOffset, size_t dataSize);
    Status SetChunkOffsetParams(uint32_t type, int64_t dataOffset, size_t dataSize);
    Status SetSampleToChunkParams(int64_t dataOffset, size_t dataSize);
    Status SetTrackExtendsParams(int64_t dataOffset, size_t dataSize);
    Status SetTrackFragmentHeaderParams(int64_t dataOffset, int64_t dataSize, uint32_t flag, int64_t moofOffset);
    Status SetTrackFragmentDecodeTimeParams(int64_t dataOffset, int64_t dataSize);
    Status SetTrackFragmentRunParams(int64_t dataOffset, int64_t dataSize, int64_t sidxDts,
        int64_t &moofDts, int64_t &duration);
    Status BuildSampleIndexEntries();
    Status GetSampleDuration(uint32_t index, uint32_t &delta);
private:
    std::vector<SampleIndexEntry> sampleIndexEntry_;
    std::vector<CttsEntry> cttsEntry_;
    std::vector<SttsEntry> sttsEntry_;       // time-to-sample
    std::vector<StscEntry> stscEntry_;       // sample-to-chunk
    std::vector<StssEntry> stssEntry_;       // sync samples
    std::vector<int32_t> sampleSizes_;
    std::vector<int64_t> chunkOffsets_;     // stco/co64
    TrackExtendsInfo trex_;
    TrackFragmentHeaderInfo tfhd_;
    int64_t tfdtDts_ = -1;
    int64_t baseFragmentDts_ = -1;
    int64_t firstMoofSttsIndex_ = 0;
    uint32_t numMoovSamples_ = 0;
    bool hasTfhd_ = false;
    bool hasDefaultStszSize_ = false;
};
```

**证据4**：`mpeg4_sample_helper.h:31-44` — `TrunFlag` 6种TRUN标志位枚举

**证据5**：`mpeg4_sample_helper.h:46-57` — `SampleIndexEntry` + `CttsEntry` 样本索引结构

**证据6**：`mpeg4_sample_helper.h:82-164` — 私有成员6类表（stts/stsc/stss/sampleSizes/chunkOffsets/tfhd）

---

## 三、解析函数表与派发机制

### 3.1 原子解析函数表 MPEG4ParseTable_

路径：`services/media_engine/plugins/demuxer/mpeg4_demuxer/mpeg4_box_parser.cpp:3876-3912`

```cpp
void MPEG4AtomParser::InitParseTable()
{
    MPEG4ParseTable_ = {
        {FourccType("ftyp"), &MPEG4AtomParser::ParseFtyp},
        {FourccType("moov"), &MPEG4AtomParser::ParseMoov},
        {FourccType("wide"), &MPEG4AtomParser::ParseWide},
        {FourccType("mdat"), &MPEG4AtomParser::ParseMdat},
        {FourccType("trak"), &MPEG4AtomParser::ParseTrak},
        {FourccType("mvhd"), &MPEG4AtomParser::ParseMvhd},
        {FourccType("tkhd"), &MPEG4AtomParser::ParseTkhd},
        {FourccType("edts"), &MPEG4AtomParser::ParseEdts},
        {FourccType("elst"), &MPEG4AtomParser::ParseElst},
        {FourccType("tref"), &MPEG4AtomParser::ParseTref},
        {FourccType("cdsc"), &MPEG4AtomParser::ParseCdsc},
        {FourccType("mdia"), &MPEG4AtomParser::ParseMdia},
        {FourccType("mdhd"), &MPEG4AtomParser::ParseMdhd},
        {FourccType("hdlr"), &MPEG4AtomParser::ParseHdlr},
        {FourccType("minf"), &MPEG4AtomParser::ParseMinf},
        {FourccType("stbl"), &MPEG4AtomParser::ParseStbl},
        {FourccType("stsd"), &MPEG4AtomParser::ParseStsd},
        {FourccType("btrt"), &MPEG4AtomParser::ParseBtrt},
        {FourccType("pasp"), &MPEG4AtomParser::ParsePasp},
        {FourccType("esds"), &MPEG4AtomParser::ParseEsds},
        {FourccType("avcC"), &MPEG4AtomParser::ParseCodecConfig},
        {FourccType("hvcC"), &MPEG4AtomParser::ParseCodecConfig},
        {FourccType("vvcC"), &MPEG4AtomParser::ParseCodecConfig},
        {FourccType("d263"), &MPEG4AtomParser::ParseCodecConfig},
        {FourccType("dfLa"), &MPEG4AtomParser::ParseDfla},
        {FourccType("dOps"), &MPEG4AtomParser::ParseDops},
        {FourccType("pcmC"), &MPEG4AtomParser::ParsePcmc},
        {FourccType("enda"), &MPEG4AtomParser::ParseEnda},
        {FourccType("colr"), &MPEG4AtomParser::ParseColr},
        {FourccType("aclr"), &MPEG4AtomParser::ParseAclr},
        {FourccType("glbl"), &MPEG4AtomParser::ParseGlbl},
        {FourccType("stts"), &MPEG4AtomParser::ParseStts},
        {FourccType("stss"), &MPEG4AtomParser::ParseStss},
        {FourccType("ctts"), &MPEG4AtomParser::ParseCtts},
        {FourccType("stsc"), &MPEG4AtomParser::ParseStsc},
        {FourccType("stsz"), &MPEG4AtomParser::ParseStsz},
        {FourccType("stz2"), &MPEG4AtomParser::ParseStsz},
        {FourccType("stco"), &MPEG4AtomParser::ParseStco},
        {FourccType("co64"), &MPEG4AtomParser::ParseStco},
        {FourccType("fiel"), &MPEG4AtomParser::ParseFiel},
        {FourccType("mvex"), &MPEG4AtomParser::ParseMvex},
        {FourccType("trex"), &MPEG4AtomParser::ParseTrex},
        {FourccType("sidx"), &MPEG4AtomParser::ParseSidx},
        {FourccType("udta"), &MPEG4AtomParser::ParseUdta},
        {FourccType("meta"), &MPEG4AtomParser::ParseMeta},
        {FourccType("ilst"), &MPEG4AtomParser::ParseIlst},
        // ... 共50+ entries
    };
}
```

**证据7**：`mpeg4_box_parser.cpp:3876-3912` — InitParseTable() 填充50+个fourcc→ParseFunction映射

**证据8**：`mpeg4_box_parser.cpp:3999` — `ret = ParseMoof(firstTrack_, ctx->offset);` Moof解析触发

**证据9**：`mpeg4_box_parser.cpp:4011` — `FindAtomParser()` 函数查找实现，返回ParseFunction指针

---

## 四、关键解析函数实现

### 4.1 ParseMoov 容器解析

路径：`services/media_engine/plugins/demuxer/mpeg4_demuxer/mpeg4_box_parser.cpp:617-628`

```cpp
Status MPEG4AtomParser::ParseMoov(MPEG4Atom currentAtom, int32_t depth, ParseContext* ctx)
{
    FALSE_RETURN_V_MSG_E(depth == MPEG4_ROOT_DEPTH, Status::ERROR_INVALID_PARAMETER, "Invalid moov depth");
    FALSE_RETURN_V_MSG_E(!moovFound_, Status::ERROR_INVALID_DATA, "Duplicate moov atom");
    Status ret = ParseContainerAtom(currentAtom, depth, ctx);
    FALSE_RETURN_V_MSG_E(ret == Status::OK, ret, "Parse moov atom failed");
    moovFound_ = true;
    return ret;
}
```

**证据10**：`mpeg4_box_parser.cpp:617-628` — ParseMoov入口，检查depth+duplicate moov，委托ParseContainerAtom

### 4.2 ParseContainerAtom 递归容器解析

路径：`services/media_engine/plugins/demuxer/mpeg4_demuxer/mpeg4_box_parser.cpp:557-575`

```cpp
Status MPEG4AtomParser::ParseContainerAtom(const MPEG4Atom& containerAtom, int32_t depth, ParseContext* ctx)
{
    int64_t endOffset = 0;
    if (__builtin_add_overflow(ctx->dataOffset, containerAtom.dataSize, &endOffset)) {
        MEDIA_LOG_E("Container atom size overflow");
        return Status::ERROR_INVALID_DATA;
    }
    ctx->offset = ctx->dataOffset;
    while (ctx->offset < endOffset) {
        Status ret = MPEG4ParseAtom(depth + 1, ctx);
        FALSE_RETURN_V_MSG_E(ret == Status::OK, ret, "Failed to parse atom at offset " PUBLIC_LOG_D64, ctx->offset);
    }
    FALSE_RETURN_V_MSG_E(ctx->offset == endOffset, Status::ERROR_INVALID_DATA, ...);
    return Status::OK;
}
```

**证据11**：`mpeg4_box_parser.cpp:557-575` — ParseContainerAtom递归解析容器内所有子Atom

### 4.3 ParseStbl 样本表解析

路径：`services/media_engine/plugins/demuxer/mpeg4_demuxer/mpeg4_box_parser.cpp:1335-1342`

```cpp
Status MPEG4AtomParser::ParseStbl(MPEG4Atom currentAtom, int32_t depth, ParseContext* ctx)
{
    Status ret = ParseContainerAtom(currentAtom, depth, ctx);
    return ret;
}
```

**证据12**：`mpeg4_box_parser.cpp:1335-1342` — ParseStbl只是容器解析，真正解析由stts/stsc/stsz/stss/ctts/stco负责

### 4.4 STTS/CTTS/STSC/STSZ/STCO 样本表五件套

路径：`services/media_engine/plugins/demuxer/mpeg4_demuxer/mpeg4_box_parser.cpp:2674-2758`

```cpp
Status MPEG4AtomParser::ParseStts(MPEG4Atom currentAtom, int32_t depth, ParseContext* ctx)
{
    // L2674: 检查lastTrack_和sampleHelper非空
    ctx->offset += currentAtom.size;
    if (currentAtom.size > MIN_BOX_SIZE) {
        Status ret = lastTrack_->sampleHelper->SetTimeToSampleParams(ctx->dataOffset, currentAtom.dataSize);
        FALSE_RETURN_V_MSG_E(ret == Status::OK, ret, "Set time to sample params failed");
    }
    return Status::OK;
}

Status MPEG4AtomParser::ParseCtts(MPEG4Atom currentAtom, int32_t depth, ParseContext* ctx)
{
    ctx->offset += currentAtom.size;
    return lastTrack_->sampleHelper->SetCompositionTimeToSampleParams(ctx->dataOffset, currentAtom.dataSize);
}

Status MPEG4AtomParser::ParseStsc(MPEG4Atom currentAtom, int32_t depth, ParseContext* ctx)
{
    ctx->offset += currentAtom.size;
    if (currentAtom.size > MIN_BOX_SIZE) {
        return lastTrack_->sampleHelper->SetSampleToChunkParams(ctx->dataOffset, currentAtom.dataSize);
    }
    return Status::OK;
}

Status MPEG4AtomParser::ParseStsz(MPEG4Atom currentAtom, int32_t depth, ParseContext* ctx)
{
    ctx->offset += currentAtom.size;
    constexpr int64_t minStszSize = 20;
    if (currentAtom.size >= minStszSize) {
        return lastTrack_->sampleHelper->SetSampleSizeParams(currentAtom.type, ctx->dataOffset, currentAtom.dataSize);
    }
    return Status::OK;
}

Status MPEG4AtomParser::ParseStco(MPEG4Atom currentAtom, int32_t depth, ParseContext* ctx)
{
    ctx->offset += currentAtom.size;
    if (currentAtom.size > MIN_BOX_SIZE) {
        return lastTrack_->sampleHelper->SetChunkOffsetParams(currentAtom.type, ctx->dataOffset, currentAtom.dataSize);
    }
    return Status::OK;
}
```

**证据13**：`mpeg4_box_parser.cpp:2674-2758` — 5个样本表解析函数，全部委托给MPEG4SampleHelper

**证据14**：`mpeg4_box_parser.cpp:3900-3903` — 解析表注册：stts/stss/ctts/stsc/stsz/stz2/stco/co64

### 4.5 ParseMoof 分片Moof解析

路径：`services/media_engine/plugins/demuxer/mpeg4_demuxer/mpeg4_box_parser.cpp:3035-3104`

```cpp
Status MPEG4AtomParser::ParseMoof(const std::shared_ptr<Track>& track, int64_t offset)
{
    uint32_t atomSize = 0;
    int64_t headerOffset = offset;
    Status ret = FindNextMoof(headerOffset, atomSize);  // L3036
    FALSE_RETURN_V_MSG_E(ret == Status::OK, ret, "Find next moof atom failed");
    hasMoofBox_ = true;
    moofOffset_ = headerOffset;
    // L3053: FragmentEntry构建，查找已存在entry
    // L3066: currentOffset遍历moof内所有atom
    while (currentOffset < moofEndOffset) {
        MPEG4Atom atom;
        uint8_t atomHeader[8];
        ret = dataReader_->ReadUintData(currentOffset, atomHeader, atom.headerSize);
        atom.size = GetU32Value(&atomHeader[0]);
        atom.type = static_cast<int32_t>(GetU32Value(&atomHeader[typeOffset]));
        atom.dataSize = atom.size - atom.headerSize;
        atom.dataOffset = currentOffset + atom.headerSize;
        // L3080: UpdataMoofInfo处理tfhd/tfdt/trun
        FALSE_RETURN_V_NOLOG(UpdataMoofInfo(atom, ret, currentOffset, frag, sidxDts), ret);
    }
    ret = UpdateFragmentEntryAndOffset(inEntry, fragIndex, frag, moofOffset_, currentOffset);
    return ret;
}
```

**证据15**：`mpeg4_box_parser.cpp:3035-3104` — ParseMoof完整流程（FindNextMoof→遍历atom→UpdataMoofInfo→UpdateFragmentEntry）

### 4.6 ProcessTfhdAtom TFHD处理

路径：`services/media_engine/plugins/demuxer/mpeg4_demuxer/mpeg4_box_parser.cpp:3107-3134`

```cpp
Status MPEG4AtomParser::ProcessTfhdAtom(const MPEG4Atom& atom)
{
    // L3109: 检查atom.dataOffset和dataSize
    uint8_t tfhdHeader[8];
    Status ret = dataReader_->ReadUintData(atom.dataOffset, tfhdHeader, sizeof(tfhdHeader));
    uint32_t tfhdFlag = GetU32Value(&tfhdHeader[0]);
    uint32_t trackId = GetU32Value(&tfhdHeader[4]);
    // L3121: 遍历Track链表找匹配trackId
    while (currentTrack_ && static_cast<uint32_t>(currentTrack_->trackId) != trackId) {
        currentTrack_ = currentTrack_->next;
    }
    // L3127: 委托sampleHelper处理
    ret = currentTrack_->sampleHelper->SetTrackFragmentHeaderParams(
        tfhdDataOffset, dataSize, tfhdFlag, moofOffset_);
    return ret;
}
```

**证据16**：`mpeg4_box_parser.cpp:3107-3134` — ProcessTfhdAtom提取tfhdFlag/trackId，委托sampleHelper

---

## 五、MPEG4SampleHelper 样本索引构建

### 5.1 BuildSampleIndexEntries 索引构建主入口

路径：`services/media_engine/plugins/demuxer/mpeg4_demuxer/mpeg4_sample_helper.cpp` (1009行)

核心方法：
- `SetTimeToSampleParams` → 解析 STTS 构建 sttsEntry_ 表
- `SetCompositionTimeToSampleParams` → 解析 CTTS 构建 cttsEntry_ 表
- `SetSyncSampleParams` → 解析 STSS 构建 stssEntry_ 表（关键帧索引）
- `SetSampleSizeParams` → 解析 STSZ/STZ2 构建 sampleSizes_ 表
- `SetChunkOffsetParams` → 解析 STCO/CO64 构建 chunkOffsets_ 表
- `SetSampleToChunkParams` → 解析 STSC 构建 stscEntry_ 表
- `SetTrackFragmentHeaderParams` → 解析 TFHD 构建 tfhd_ 结构
- `SetTrackFragmentRunParams` → 解析 TRUN 计算分片样本duration/CTS
- `BuildSampleIndexEntries` → 汇总6张表生成 sampleIndexEntry_ 向量

**证据17**：`mpeg4_sample_helper.h:38-54` — 12个公开方法（9个Set*Params + BuildSampleIndexEntries + FindSyncSampleAtTime + GetSampleDuration）

**证据18**：`mpeg4_sample_helper.h:133-158` — 私有6张表+TrackExtendsInfo+TrackFragmentHeaderInfo

---

## 六、编解码参数解析（avcC/hvcC/vvcC）

路径：`services/media_engine/plugins/demuxer/mpeg4_demuxer/mpeg4_box_parser.cpp:1524-1550`

```cpp
Status MPEG4AtomParser::ParseCodecConfig(MPEG4Atom currentAtom, int32_t depth, ParseContext* ctx)
{
    // L1524: avcC/hvcC/vvcC/d263 共用同一解析函数
    FALSE_RETURN_V_MSG_E(lastTrack_ != nullptr, Status::ERROR_INVALID_POINTER, "Current track is null");
    ctx->offset += currentAtom.size;
    auto codecParamsData = std::make_unique<uint8_t[]>(currentAtom.dataSize);
    Status ret = dataReader_->ReadUintData(ctx->dataOffset, codecParamsData.get(), currentAtom.dataSize);
    lastTrack_->codecParms.data = std::move(codecParamsData);
    lastTrack_->codecParms.extradataSize = currentAtom.dataSize;
    lastTrack_->codecParms.trackType = trackType_;
    return ret;
}
```

**证据19**：`mpeg4_box_parser.cpp:3894-3895` — 解析表：`{FourccType("avcC"), &MPEG4AtomParser::ParseCodecConfig}` + hvcC + vvcC + d263

**证据20**：`mpeg4_box_parser.cpp:1524-1550` — ParseCodecConfig统一处理AVC/HEVC/VVC/D263 CodecConfig

---

## 七、关键设计模式

### 7.1 双链表 Track 管理

路径：`mpeg4_box_parser.h:48-65`

`firstTrack_` / `lastTrack_` / `currentTrack_` 三指针维护 Track 双链表，每ParseTrak创建新Track并链入。

### 7.2 函数指针表派发

`MPEG4ParseTable_` unordered_map 实现 fourcc→ParseFunction O(1) 查找，无需 if-else 链。

### 7.3 委托模式

Box解析后，样本表5件套（STTS/CTTS/STSC/STSZ/STCO）全部委托给 `MPEG4SampleHelper`，实现解析职责分离。

### 7.4 分片独立解析

`FragmentEntry` 管理每个moof的分片元数据，`firstDts`/`moofOffset`/`hasRead` 支持多moof独立解析与缓存。

---

## 八、关联记忆

| 关联ID | 关系 | 说明 |
|--------|------|------|
| S123 | 互补 | StreamDemuxer 流式解封装，S144 DemuxerPluginManager 插件管理 |
| S141 | 互补 | PTS索引转换 TimeAndIndexConversion，MP4 moov 遍历依赖本解析器 |
| S130 | 互补 | FFmpegAdapter 通用工具链，FFmpegDemuxerPlugin 使用本解析器 |
| S96 | 引用 | TimeRangeManager Seek范围，moov/mdat 布局影响Seek有效性 |

---

## 九、Evidence 清单（20条）

| # | 文件 | 行号 | 内容 |
|---|------|------|------|
| 1 | mpeg4_box_parser.h | 139 | ParseFunction 类型别名定义 |
| 2 | mpeg4_box_parser.h | 36-130 | Track 双链表结构定义 |
| 3 | mpeg4_box_parser.h | 66-73 | FragmentEntry 分片条目 |
| 4 | mpeg4_sample_helper.h | 31-44 | TrunFlag 6种标志位枚举 |
| 5 | mpeg4_sample_helper.h | 46-57 | SampleIndexEntry + CttsEntry |
| 6 | mpeg4_sample_helper.h | 82-164 | 私有6张表成员 |
| 7 | mpeg4_box_parser.cpp | 3876-3912 | InitParseTable() 50+映射 |
| 8 | mpeg4_box_parser.cpp | 3999 | ParseMoof触发调用 |
| 9 | mpeg4_box_parser.cpp | 4011 | FindAtomParser函数实现 |
| 10 | mpeg4_box_parser.cpp | 617-628 | ParseMoov容器解析 |
| 11 | mpeg4_box_parser.cpp | 557-575 | ParseContainerAtom递归 |
| 12 | mpeg4_box_parser.cpp | 1335-1342 | ParseStbl样本表容器 |
| 13 | mpeg4_box_parser.cpp | 2674-2758 | STTS/CTTS/STSC/STSZ/STCO五件套 |
| 14 | mpeg4_box_parser.cpp | 3900-3903 | 解析表注册5样本表 |
| 15 | mpeg4_box_parser.cpp | 3035-3104 | ParseMoof完整流程 |
| 16 | mpeg4_box_parser.cpp | 3107-3134 | ProcessTfhdAtom |
| 17 | mpeg4_sample_helper.h | 38-54 | 12个公开方法 |
| 18 | mpeg4_sample_helper.h | 133-158 | 私有成员详细定义 |
| 19 | mpeg4_box_parser.cpp | 3894-3895 | avcC/hvcC/vvcC/d263注册 |
| 20 | mpeg4_box_parser.cpp | 1524-1550 | ParseCodecConfig统一处理 |

---

## 十、文件规模

| 文件 | 行数 |
|------|------|
| mpeg4_box_parser.cpp | 4378 |
| mpeg4_box_parser.h | 287 |
| mpeg4_sample_helper.cpp | 1009 |
| mpeg4_sample_helper.h | 164 |
| **合计** | **5838行** |