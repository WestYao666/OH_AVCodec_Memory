# MEM-ARCH-AVCODEC-S223: MPEG4BoxParser — ISOBMFF/MP4 Box 解析器架构与五层递归解析框架

## 主题

MPEG4BoxParser — ISOBMFF/MP4 Box 解析器架构与五层递归解析框架

## 范围

AVCodec, MediaEngine, MPEG4DemuxerPlugin, MPEG4AtomParser, MPEG4SampleHelper, ISOBMFF, MP4, Box Parser, Atom, Track, Sample, Fragment, Moof, Sidx, DemuxerPlugin

## 关联场景

新人入项/问题定位/MP4文件解析/流媒体/分片播放/DRM/码流分析

## 状态

pending_approval

## 摘要

MPEG4BoxParser 是 OHOS AVCodec 中 MPEG4/ISOBMFF 格式的 Box 解析引擎，封装在 MPEG4AtomParser 类中，与 MPEG4DemuxerPlugin、MPEG4SampleHelper 协作完成 MP4/AAF 容器解析。解析器采用五层递归深度控制（ROOT/DEPTH_ONE/DEPTH_TWO/DEPTH_THREE/DEPTH_FOUR），通过函数表驱动（55+ Box 类型）实现容器树解析，Track 结构管理多轨道，FragmentEntry 管理分片，SampleIndexEntry 管理样本索引。Box 解析支持 ftyp/moov/mdat/moof/TKHD/MDIA/STBL 等全部 ISOBMFF 规范原子。

---

## 详细说明

### 1. 架构概览

MPEG4BoxParser 解析体系由三个核心类构成：

- **MPEG4AtomParser**：Box 解析引擎，负责 ISOBMFF 容器树递归解析，维护 ParseContext（偏移/路径/元数据键），解析 ftyp/moov/mdat/moof 等 55+ 种 Box 类型
- **MPEG4DemuxerPlugin**：DemuxerPlugin 子类，实现 SetDataSource/ReadSample/SeekTo 等接口，内部持有 MPEG4AtomParser 实例
- **MPEG4SampleHelper**：样本索引管理，维护 SampleIndexEntry 向量、STTS/STSC/STSS/CTTS 表，实现 FindSyncSampleAtTime/BuildSampleIndexEntries 等关键方法

文件分布：
- `mpeg4_box_parser.cpp`：4378 行，Box 解析核心逻辑
- `mpeg4_box_parser.h`：601 行，类/结构体定义与解析函数声明
- `mpeg4_demuxer_plugin.cpp`：1625 行，DemuxerPlugin 接口实现与插件入口
- `mpeg4_sample_helper.h/cpp`：样本索引结构与查找算法

### 2. 五层递归解析深度

MPEG4AtomParser 通过 depth 参数控制解析深度，每层对应特定的容器层级：

```
MPEG4_ROOT_DEPTH(0)     → ftyp, moov, mdat, moof, sidx
MPEG4_DEPTH_ONE(1)     → moov 的子原子：mvhd, trak, mvex
MPEG4_DEPTH_TWO(2)     → trak 的子原子：tkhd, mdia, edts
MPEG4_DEPTH_THREE(3)   → mdia 的子原子：mdhd, hdlr, minf
MPEG4_DEPTH_FOUR(4)   → minf 的子原子：vmhd, smhd, stbl
```

E1: mpeg4_box_parser.cpp 行 56-60，五层深度常量定义：
```cpp
constexpr int32_t MPEG4_ROOT_DEPTH = 0;  // Root level atom, ftyp, moov, mdat etc.
constexpr int32_t MPEG4_DEPTH_ONE = 1;  // moov's children atom, mvhd, trak, mvex etc.
constexpr int32_t MPEG4_DEPTH_TWO = 2;  // trak's direct children atom, tkhd, mdia, edts etc.
constexpr int32_t MPEG4_DEPTH_THREE = 3;  // mdia's direct children atom, mdhd, hdlr, minf etc.
constexpr int32_t MPEG4_DEPTH_FOUR = 4;  // minf's direct children atom, vmhd, smhd, stbl etc.
```

### 3. MPEG4AtomParser::Track 结构

Track 是解析器内部的核心数据结构，管理每个媒体的轨道信息：

E2: mpeg4_box_parser.h 行 48-66，Track 结构体：
```cpp
struct Track {
    std::shared_ptr<Track> next = nullptr;
    uint32_t trackIndex = 0;
    int32_t trackId = 0;
    std::shared_ptr<MPEG4SampleHelper> sampleHelper = nullptr;
    std::unique_ptr<int32_t[]> displayMatrix = nullptr;  // 3x3 display matrix
    bool hasDisplayMatrix = false;
    uint32_t currentSampleIndex = 0;
    int64_t duration = 0; // mdhd box duration
    int64_t totalElstDuration = 0; // elst box segment duration之和
    int64_t sidxDuration = 0; // sidx box dts
    int64_t elstInitEmptyEdit = 0;
    int64_t elstShiftStartTime = 0;
    CodecParams codecParms{};
    Track() = default;
};
```

E3: mpeg4_box_parser.h 行 40-47，CodecParams 结构体：
```cpp
struct CodecParams {
    std::unique_ptr<uint8_t[]> data = nullptr;
    int64_t extradataSize = 0;
    TrackType trackType = INVALID_TYPE;
    HdrBoxInfo hdrBoxInfo {false, false, false};
    CodecParams() = default;
};
```

### 4. FragmentEntry 分片管理

FragmentEntry 管理 MP4 分片（Fragment），用于 DASH/FMP4 场景：

E4: mpeg4_box_parser.h 行 66-75，FragmentEntry 结构体：
```cpp
struct FragmentEntry {
    int64_t firstDts = -1;
    int64_t moofOffset;
    int64_t nextAtomOffset = -1;
    int64_t duration = -1;
    bool hasRead = false;
};
```

E5: mpeg4_demuxer_plugin.cpp 行 844-860，ParseMoof 使用 FragmentEntry：
```cpp
Status MPEG4DemuxerPlugin::ParseMoof(int64_t offset)
{
    auto parser = std::make_shared<MPEG4AtomParser>();
    FALSE_RETURN_V_MSG_E(parser != nullptr, Status::ERROR_NO_MEMORY, "parser allocation failed");
    Status ret = parser->ParseMoof(firstTrack_, offset);
    FALSE_RETURN_V_MSG_E(ret == Status::OK, Status::ERROR_INVALID_PARAMETER, "ParseMoof failed");
    fragmentEntry_.clear();
    parser->GetFragmentEntry(fragmentEntry_);
    ...
}
```

### 5. 函数表驱动的 Box 解析

MPEG4AtomParser 使用 `std::map<FourccType, ParseFunction>` 函数表驱动解析，55+ 种 Box 类型映射到对应解析函数：

E6: mpeg4_box_parser.cpp 行 3883-3912，函数表定义（部分）：
```cpp
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
    {FourccType("mdia"), &MPEG4AtomParser::ParseMdia},
    {FourccType("mdhd"), &MPEG4AtomParser::ParseMdhd},
    {FourccType("hdlr"), &MPEG4AtomParser::ParseHdlr},
    {FourccType("minf"), &MPEG4AtomParser::ParseMinf},
    {FourccType("stbl"), &MPEG4AtomParser::ParseStbl},
    {FourccType("stsd"), &MPEG4AtomParser::ParseStsd},
    {FourccType("avcC"), &MPEG4AtomParser::ParseCodecConfig},
    {FourccType("hvcC"), &MPEG4AtomParser::ParseCodecConfig},
    {FourccType("vvcC"), &MPEG4AtomParser::ParseCodecConfig},
    {FourccType("stts"), &MPEG4AtomParser::ParseStts},
    {FourccType("stss"), &MPEG4AtomParser::ParseStss},
    {FourccType("ctts"), &MPEG4AtomParser::ParseCtts},
    {FourccType("stsc"), &MPEG4AtomParser::ParseStsc},
    {FourccType("stsz"), &MPEG4AtomParser::ParseStsz},
    {FourccType("stco"), &MPEG4AtomParser::ParseStco},
    {FourccType("mvex"), &MPEG4AtomParser::ParseMvex},
    {FourccType("trex"), &MPEG4AtomParser::ParseTrex},
    {FourccType("sidx"), &MPEG4AtomParser::ParseSidx},
    ...
};
```

### 6. ParseMoov 与 Track 链表构建

ParseMoov 递归解析 moov 容器的子原子，逐个创建 Track 节点并加入链表：

E7: mpeg4_box_parser.cpp 行 617-692，ParseMoov 实现（部分）：
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

E8: mpeg4_box_parser.cpp 行 892-1174，ParseTrak 创建 Track 节点（部分）：
```cpp
Status MPEG4AtomParser::ParseTrak(MPEG4Atom currentAtom, int32_t depth, ParseContext* ctx)
{
    FALSE_RETURN_V_MSG_E(depth == MPEG4_DEPTH_ONE, Status::ERROR_INVALID_DATA, "Invalid trak depth");
    // 创建新 Track 节点
    auto track = std::make_shared<Track>();
    FALSE_RETURN_V_MSG_E(track != nullptr, Status::ERROR_NO_MEMORY, "track allocation failed");
    track->trackIndex = trackCount_;
    // 加入链表
    if (lastTrack_ == nullptr) {
        firstTrack_ = track;
    } else {
        lastTrack_->next = track;
    }
    lastTrack_ = track;
    ++trackCount_;
    ...
}
```

### 7. ParseMvhd 时间轴解析

ParseMvhd 解析 movie header atom，提取 timescale 和 duration：

E9: mpeg4_box_parser.cpp 行 692-750，ParseMvhd 实现（部分）：
```cpp
Status MPEG4AtomParser::ParseMvhd(MPEG4Atom currentAtom, int32_t depth, ParseContext* ctx)
{
    FALSE_RETURN_V_MSG_E(depth == MPEG4_DEPTH_ONE, Status::ERROR_INVALID_DATA, "Invalid mvhd depth");
    FALSE_RETURN_V_MSG_E(currentAtom.dataSize >= MIN_MVHD_SIZE && currentAtom.dataSize <= MAX_DATA_SIZE,
        Status::ERROR_INVALID_DATA, "Invalid atom size");
    ctx->offset += currentAtom.size;
    uint8_t headerInfo[currentAtom.dataSize];
    Status ret = dataReader_->ReadUintData(ctx->dataOffset, headerInfo, sizeof(headerInfo));
    ...
}
```

### 8. ParseStbl 样本表解析

ParseStbl 是 stbl（Sample Table Box）容器解析入口，递归解析 STTS/STSC/STSS/STSD 等子 Box：

E10: mpeg4_box_parser.cpp 行 1335-1390，ParseStbl 实现：
```cpp
Status MPEG4AtomParser::ParseStbl(MPEG4Atom currentAtom, int32_t depth, ParseContext* ctx)
{
    FALSE_RETURN_V_MSG_E(depth == MPEG4_DEPTH_FOUR, Status::ERROR_INVALID_DATA, "Invalid stbl depth");
    Status ret = ParseContainerAtom(currentAtom, depth, ctx);
    FALSE_RETURN_V_MSG_E(ret == Status::OK, ret, "Parse stbl container failed");
    return ret;
}
```

### 9. ParseVideoSampleEntry 视频编码参数解析

ParseVideoSampleEntry 解析 avc1/hvc1/vvc1/encv 等视频采样条目，提取宽高和 HDR Vivid 标记：

E11: mpeg4_box_parser.cpp 行 1392-1440，ParseVideoSampleEntry 实现（部分）：
```cpp
Status MPEG4AtomParser::ParseVideoSampleEntry(MPEG4Atom currentAtom, int32_t depth, ParseContext* ctx)
{
    FALSE_RETURN_V_MSG_E(lastTrack_ != nullptr, Status::ERROR_INVALID_DATA, "Track is nullptr");
    FALSE_RETURN_V_MSG_E(currentAtom.dataSize >= MIN_VIDEO_SAMPLE_ENTRY_SIZE, Status::ERROR_INVALID_DATA,
        "Invalid video codec atom size");
    /* Video SampleEntry 数据大小至少 78 字节：
     * pre_defined(2) + reserved(2) + pre_defined(12) + width(2) + height(2) +
     * horizresolution(4) + vertresolution(4) + reserved(4) + frame_count(2) +
     * compressorname(32) + depth(2) + pre_defined(2)
    */
    uint8_t sampleEntryInfo[78];
    Status ret = dataReader_->ReadUintData(ctx->dataOffset, sampleEntryInfo, sizeof(sampleEntryInfo));
    uint16_t width = GetU16Value(&sampleEntryInfo[24]);
    uint16_t height = GetU16Value(&sampleEntryInfo[26]);
    mediaInfo_.tracks[lastTrack_->trackIndex].Set<Tag::VIDEO_WIDTH>(static_cast<int32_t>(width));
    mediaInfo_.tracks[lastTrack_->trackIndex].Set<Tag::VIDEO_HEIGHT>(static_cast<int32_t>(height));
    ...
}
```

### 10. ParseSidx 分片索引解析

ParseSidx 解析 Segment Index Box，提取 referenceId、timeScale、firstOffset 和分段条目：

E12: mpeg4_box_parser.cpp 行 2820-2870，ParseSidx 实现（部分）：
```cpp
Status MPEG4AtomParser::ParseSidx(MPEG4Atom currentAtom, int32_t depth, ParseContext* ctx)
{
    FALSE_RETURN_V_MSG_E(depth == 0, Status::ERROR_INVALID_DATA, "Invalid sidx depth");
    FALSE_RETURN_V_MSG_E(currentAtom.dataSize >= MIN_SIDX_SIZE, Status::ERROR_INVALID_DATA, "Invalid sidx atom size");
    if (isDistributedSidx_) {
        ctx->offset += currentAtom.size;
        MEDIA_LOG_W("Distributed sidx, skip parse");
        return Status::OK;
    }
    auto headerInfo = std::make_unique<uint8_t[]>(currentAtom.dataSize);
    Status ret = dataReader_->ReadUintData(ctx->dataOffset, headerInfo.get(), currentAtom.dataSize);
    uint8_t version = headerInfo[0];
    uint32_t referenceId = GetU32Value(&headerInfo[4]);
    uint32_t timeScale = GetU32Value(&headerInfo[8]);
    ...
}
```

### 11. ParseTrex Track Extends 解析

ParseTrex 解析 Track Extends Box，设置默认样本描述符索引和样本Duration：

E13: mpeg4_box_parser.cpp 行 2801-2820，ParseTrex 实现：
```cpp
Status MPEG4AtomParser::ParseTrex(MPEG4Atom currentAtom, int32_t depth, ParseContext* ctx)
{
    FALSE_RETURN_V_MSG_E(depth == MPEG4_DEPTH_TWO, Status::ERROR_INVALID_PARAMETER, "Invalid trex depth");
    ctx->offset += currentAtom.size;
    static uint32_t trexIndex = 0;
    auto track = firstTrack_;
    for (uint32_t i = 0; i < trexIndex && track != nullptr; ++i) {
        track = track->next;
    }
    if (track && track->sampleHelper) {
        Status ret = track->sampleHelper->SetTrackExtendsParams(ctx->dataOffset, currentAtom.dataSize);
        FALSE_RETURN_V_MSG_E(ret == Status::OK, ret, "Set track extends params failed");
    }
    ++trexIndex;
    return Status::OK;
}
```

### 12. MPEG4SampleHelper 样本索引结构

MPEG4SampleHelper 维护样本索引表，包含 STTS（时间到样本）、STSC（样本到chunk）、STSS（同步样本）、CTTS（Composition Time Offset）：

E14: mpeg4_sample_helper.h 行 56-102，SampleIndexEntry 和相关结构体：
```cpp
struct SampleIndexEntry {
    int64_t pos = 0;       // chunk偏移
    int64_t pts = 0;        // 显示时间戳
    int64_t dts = 0;        // 解码时间戳
    uint32_t size = 0;      // 样本大小
    uint32_t flag = 0;      // 同步帧标记
};
struct SttsEntry { int64_t count = 0; int64_t duration = 0; };
struct StscEntry { uint32_t firstChunk = 0; uint32_t samplesPerChunk = 0; uint32_t sampleDescriptionIndex = 0; };
struct StssEntry { uint32_t index = 0; }; // 同步帧表
struct CttsEntry { uint32_t count = 0; int32_t compositionOffset = 0; };
```

### 13. FindSyncSampleAtTime 同步帧查找

FindSyncSampleAtTime 实现三种 SeekMode 下的同步帧查找：SEEK_PREVIOUS_SYNC/SEEK_NEXT_SYNC/SEEK_CLOSEST_SYNC：

E15: mpeg4_sample_helper.cpp 行 57-115，FindSyncSampleAtTime 实现（部分）：
```cpp
Status MPEG4SampleHelper::FindWithSyncSamples(int64_t inputPTS, bool isBaseTrack, SeekMode flag, uint32_t &syncIndex)
{
    if (flag == SeekMode::SEEK_PREVIOUS_SYNC) {
        currentIndex = findPrevSync(currentIndex - 1);
        if (currentIndex < 0) {
            currentIndex = stssEntry_.empty() ? 0 : stssEntry_[0].index;
            ...
        }
        return Status::OK;
    }
    if (flag == SeekMode::SEEK_NEXT_SYNC) {
        currentIndex = findNextSync(currentIndex);
        ...
    }
    // SEEK_CLOSEST_SYNC
    int64_t prevSync = findPrevSync(currentIndex);
    int64_t nextSync = findNextSync(currentIndex);
    if (prevSync >= 0 && nextSync < static_cast<int64_t>(numSamples)) {
        currentIndex = GetClosestSync(entry[prevSync].pts, entry[nextSync].pts, inputPTS) ? nextSync : prevSync;
    }
    ...
}
```

### 14. MPEG4DemuxerPlugin::SetDataSource 入口流程

SetDataSource 是插件初始化入口，创建 MPEG4AtomParser 并调用 MPEG4ParseHeader 解析容器：

E16: mpeg4_demuxer_plugin.cpp 行 200-240，SetDataSource 实现（部分）：
```cpp
Status MPEG4DemuxerPlugin::SetDataSource(const std::shared_ptr<DataSource>& source,
    const std::shared_ptr<Media::Meta>& configs)
{
    std::lock_guard<std::shared_mutex> lock(sharedMutex_);
    FALSE_RETURN_V_MSG_E(!inited_, Status::ERROR_WRONG_STATE, "Plugin has been initialized");
    FALSE_RETURN_V_MSG_E(source != nullptr, Status::ERROR_INVALID_PARAMETER, "DataSource is nullptr");
    seekable_ = source->IsDash() ? Seekable::UNSEEKABLE : source->GetSeekable();
    dataSource_ = source;
    auto parser = std::make_shared<MPEG4AtomParser>();
    FALSE_RETURN_V_MSG_E(parser != nullptr, Status::ERROR_NO_MEMORY, "parser allocation failed");
    Status ret = parser->MPEG4ParseHeader(source, seekable_);
    FALSE_RETURN_V_MSG_E(ret == Status::OK, ret, "MPEG4ParseHeader failed");
    mediaInfo_ = parser->GetMediaInfo();
    firstTrack_ = parser->GetFirstTrack();
    userformat_ = parser->GetUserFormat();
    fragmentEntry_.clear();
    parser->GetFragmentEntry(fragmentEntry_);
    ...
    inited_ = true;
    return Status::OK;
}
```

### 15. BlockQueuePool 缓冲管理

MPEG4DemuxerPlugin 使用 BlockQueuePool 管理样本缓冲，支持 DASH 流式场景下的分片缓冲与消费：

E17: mpeg4_demuxer_plugin.cpp 行 330-360，InitParser 初始化 MultiStreamParserManager：
```cpp
void MPEG4DemuxerPlugin::InitParser()
{
    auto track = firstTrack_;
    FALSE_RETURN_MSG(track != nullptr, "track is nullptr");
    streamParsers_ = std::make_shared<MultiStreamParserManager>();
    for (uint32_t trackIndex = 0; track != nullptr; ++trackIndex) {
        std::string mime;
        mediaInfo_.tracks[trackIndex].Get<Tag::MIME_TYPE>(mime);
        if (HaveValidParser(mime) && streamParsers_ != nullptr) {
            Status ret = streamParsers_->Create(trackIndex, g_streamParserMap.at(mime));
            ...
        }
        track = track->next;
    }
}
```

### 16. MPEG4Atom 结构体

MPEG4Atom 是每个 Box 的解析结果，包含类型、大小、数据偏移等：

E18: mpeg4_box_parser.h 行 96-104，MPEG4Atom 结构体：
```cpp
struct MPEG4Atom {
    int32_t type = 0;
    uint64_t size = 0;
    uint64_t dataSize = 0;
    int64_t dataOffset = 0;
    uint64_t headerSize = 0;
};
```

### 17. ParseContext 解析上下文

ParseContext 维护解析过程中的状态，包括当前偏移、路径、元数据键、movie display matrix 等：

E19: mpeg4_box_parser.h 行 106-122，ParseContext 结构体：
```cpp
struct ParseContext {
    int64_t offset = 0; // 当前解析位置
    int64_t dataOffset = 0; // 数据偏移位置
    std::set<uint32_t> compatibleBrands;
    std::vector<uint32_t> path;
    std::vector<std::string> metaKeys;
    int32_t movieDisplayMatrix[3][3] = {{0}}; // movie level 3x3显示变换矩阵
    uint32_t metaKeysCount = 0;
    bool hasMovieDisplayMatrix = false;
    bool foundHdlrMdta = false;
    bool founditunesMetadata = false;
};
```

### 18. DemuxerDataReader 数据读取抽象

DemuxerDataReader 提供统一的数据读取接口，封装 DataSource 的 Read 操作：

E20: demuxer_data_reader.h 行 18-30，DemuxerDataReader 类：
```cpp
class DemuxerDataReader {
public:
    Status SetDataReader(const std::shared_ptr<DataSource>& source);
    Status ReadUintData(int64_t offset, uint8_t* buffer, size_t size);
private:
    std::shared_ptr<DataSource> dataSource_ {nullptr};
};
```

---

## 关联主题

- S138: DASH MPD Parser — MPD 解析与 Sidx 配合完成分片定位
- S219: MediaEngine Source Plugin 三件套 — 数据源接入
- S195: HttpSourcePlugin Downloader 架构 — HTTP 流式数据源
- S187: DASH 流下载架构 — Fragment 下载与缓冲管理
- S222: DASH Segment Downloader 环形缓冲架构 — 分片下载管理

## 补充说明

MPEG4BoxParser 是 MP4/AAF 容器解析的核心引擎，与 FFmpegDemuxerPlugin（基于 libavformat）并列存在。两者都实现 DemuxerPlugin 接口，但 MPEG4BoxParser 使用自研 ISOBMFF 解析器，支持 DRM、Fragment 解析、HDR Vivid 检测等高级特性。解析器依赖 DemuxerDataReader 抽象数据源，通过 MultiStreamParserManager 管理视频流解析器（AVC/HEVC/VVC），通过 ReferenceParserManager 支持参考帧解析。