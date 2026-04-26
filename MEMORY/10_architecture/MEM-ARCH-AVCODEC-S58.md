---
status: pending_approval
memory_id: MEM-ARCH-AVCODEC-S58
title: "MPEG4BoxParser MP4/MOV容器Box解析器——原子层级五级深度递归+Track元数据提取+Fragmented MP4解析"
scope: AVCodec, Demuxer, MPEG4, MOV, Container, BoxParser, MP4, FragmentedMP4, MSE, Track, SampleTable
scenario: 三方应用/新需求开发/问题定位
source: repo_tmp/services/media_engine/plugins/demuxer/mpeg4_demuxer/mpeg4_box_parser.cpp
created: 2026-04-26T22:30
submitted: 2026-04-26T23:25
---

# MEM-ARCH-AVCODEC-S58: MPEG4BoxParser MP4/MOV容器Box解析器  
**scope**: AVCodec, Demuxer, MPEG4, MOV, Container, BoxParser, MP4, FragmentedMP4, MSE, Track, SampleTable  
**关联场景**: 三方应用/新需求开发/问题定位  
**mem_id**: MEM-ARCH-AVCODEC-S58  
**状态**: draft_pending_approval  
**草案版本**: v1.0 (Builder 2026-04-26)  
**来源文件**: `repo_tmp/services/media_engine/plugins/demuxer/mpeg4_demuxer/mpeg4_box_parser.cpp` (4396行) + `mpeg4_box_parser.h`

---

## 架构定位

MPEG4AtomParser 是 MP4/MOV 容器格式的底层解析引擎，位于 MPEG4DemuxerPlugin 内部，负责从字节流中解析出 Box（原子）层级结构，并提取 Track 媒体元信息（编解码参数、时长、分辨率、采样信息）。

```
文件层级关系:
mpeg4_box_parser.cpp (MPEG4AtomParser 主体 4396行)
  ├── mpeg4_utils.h          (FourccToString / GetU32Value 等工具函数)
  ├── mpeg4_audio_parser.h   (ESDS/AAC音频参数解析)
  └── mpeg4_sample_helper.h  (SampleTable六表: stts/stss/ctts/stsc/stsz/stco管理)
```

**在整体管线中的位置**:
```
DataSource → MPEG4DemuxerPlugin → MPEG4AtomParser → MPEG4SampleHelper
                                        ↓
                            MediaInfo + Track列表 → DemuxerFilter → FilterPipeline
```

---

## 核心数据结构

### 1. MPEG4Atom 原子结构 (mpeg4_box_parser.h:131-140)

```cpp
struct MPEG4Atom {
    int32_t type = 0;         // FourCC类型码 (如 'avc1', 'moov')
    uint64_t size = 0;        // Atom总大小 (包含header)
    uint64_t dataSize = 0;    // 数据部分大小 (= size - 8)
    int64_t dataOffset = 0;   // 数据起始偏移
    uint64_t headerSize = 0;  // Header大小 (8 或 16字节)
};
```

**Header格式**: `[4字节size][4字节type]`，若size==1则用8字节扩展size

### 2. Track 轨道结构 (mpeg4_box_parser.h:40-57)

每个Track对应一个媒体轨道（视频/音频/字幕），持有该轨道的完整元数据:

```cpp
struct Track {
    std::shared_ptr<Track> next = nullptr;    // 链表下一个Track
    uint32_t trackIndex = 0;                  // Track在MediaInfo中的索引
    int32_t trackId = 0;                      // 轨道ID (tkhd box定义)
    std::shared_ptr<MPEG4SampleHelper> sampleHelper = nullptr;  // 采样表辅助器
    std::unique_ptr<int32_t[]> displayMatrix = nullptr;         // 3x3显示旋转矩阵
    bool hasDisplayMatrix = false;
    uint32_t currentSampleIndex = 0;           // 当前采样索引
    int64_t duration = 0;                     // Track时长 (来自mdhd)
    int64_t totalElstDuration = 0;            // EditList总segment时长
    int64_t sidxDuration = 0;                 // SIDX索引段时长
    int64_t elstInitEmptyEdit = 0;            // 空Edit偏移
    int64_t elstShiftStartTime = 0;           // Edit时间偏移
    CodecParams codecParms{};                  // 编解码参数 (见下)
};
```

### 3. CodecParams 编解码参数结构 (mpeg4_box_parser.h:24-30)

```cpp
struct CodecParams {
    std::unique_ptr<uint8_t[]> data = nullptr;  // CodecConfig原始数据
    int64_t extradataSize = 0;                  // CodecConfig大小
    TrackType trackType = INVALID_TYPE;         // VIDEO/AUDIO/SUBTITLE/TIMEDMETA
    HdrBoxInfo hdrBoxInfo {false, false, false}; // HDR_VIVID/HDR_DOBLYVISION标志
};
```

### 4. ParseContext 解析上下文 (mpeg4_box_parser.h:155-167)

```cpp
struct ParseContext {
    int64_t offset = 0;              // 当前解析位置
    int64_t dataOffset = 0;          // 数据偏移位置
    std::set<uint32_t> compatibleBrands;  // ftyp兼容品牌
    std::vector<uint32_t> path;       // 当前解析路径 (用于调试)
    std::vector<std::string> metaKeys; // 元数据key列表
    int32_t movieDisplayMatrix[3][3] = {{0}};  // moov级显示矩阵
    bool hasMovieDisplayMatrix = false;
    bool foundHdlrMdta = false;
    bool founditunesMetadata = false;
};
```

### 5. FragmentEntry 分片条目 (mpeg4_box_parser.h:64-70)

```cpp
struct FragmentEntry {
    int64_t firstDts = -1;           // 第一个sample的DTS
    int64_t moofOffset;              // moof在文件中的偏移
    int64_t nextAtomOffset = -1;    // 下一个atom偏移
    int64_t duration = -1;           // 分片时长
    bool hasRead = false;            // 是否已解析
};
```

---

## 五级层级深度结构

解析器使用 **MAX_DEPTH=10** 的深度限制，但标准MP4有明确的5级深度约定:

| Depth常量 | 值 | 含义 | 典型Atom |
|-----------|-----|------|----------|
| MPEG4_ROOT_DEPTH | 0 | 文件根级 | ftyp, moov, mdat |
| MPEG4_DEPTH_ONE | 1 | moov子级 | mvhd, trak, mvex |
| MPEG4_DEPTH_TWO | 2 | trak子级 | tkhd, mdia, edts |
| MPEG4_DEPTH_THREE | 3 | mdia子级 | mdhd, hdlr, minf |
| MPEG4_DEPTH_FOUR | 4 | minf子级 | vmhd, smhd, stbl |

---

## 函数指针路由表 (InitParseTable)

MPEG4AtomParser 在构造函数中初始化 `MPEG4ParseTable_`（mpeg4_box_parser.cpp:3883-3910），这是一个 **47项的 ParseFunction 路由表**：

```cpp
void MPEG4AtomParser::InitParseTable()
{
    MPEG4ParseTable_ = {
        // === 根级 ===
        {FourccType("ftyp"), &MPEG4AtomParser::ParseFtyp},  // line 3887
        {FourccType("moov"), &MPEG4AtomParser::ParseMoov},
        {FourccType("wide"), &MPEG4AtomParser::ParseWide},
        {FourccType("mdat"), &MPEG4AtomParser::ParseMdat},
        // === Track级 ===
        {FourccType("trak"), &MPEG4AtomParser::ParseTrak},
        // === Movie Header ===
        {FourccType("mvhd"), &MPEG4AtomParser::ParseMvhd},  // line 3889
        // === Track Header ===
        {FourccType("tkhd"), &MPEG4AtomParser::ParseTkhd},
        // === Edit ===
        {FourccType("edts"), &MPEG4AtomParser::ParseEdts},
        {FourccType("elst"), &MPEG4AtomParser::ParseElst},
        // === Media ===
        {FourccType("mdia"), &MPEG4AtomParser::ParseMdia},
        {FourccType("mdhd"), &MPEG4AtomParser::ParseMdhd},
        {FourccType("hdlr"), &MPEG4AtomParser::ParseHdlr},
        // === Media Information ===
        {FourccType("minf"), &MPEG4AtomParser::ParseMinf},
        // === Sample Table ===
        {FourccType("stbl"), &MPEG4AtomParser::ParseStbl},  // line 3894
        {FourccType("stsd"), &MPEG4AtomParser::ParseStsd},
        {FourccType("stts"), &MPEG4AtomParser::ParseStts},
        {FourccType("stss"), &MPEG4AtomParser::ParseStss},
        {FourccType("ctts"), &MPEG4AtomParser::ParseCtts},
        {FourccType("stsc"), &MPEG4AtomParser::ParseStsc},
        {FourccType("stsz"), &MPEG4AtomParser::ParseStsz},
        {FourccType("stz2"), &MPEG4AtomParser::ParseStsz},  // 紧凑格式stsz
        {FourccType("stco"), &MPEG4AtomParser::ParseStco},
        {FourccType("co64"), &MPEG4AtomParser::ParseStco},   // 64位chunk偏移
        // === Codec Config ===
        {FourccType("avcC"), &MPEG4AtomParser::ParseCodecConfig},  // line 3897
        {FourccType("hvcC"), &MPEG4AtomParser::ParseCodecConfig},
        {FourccType("vvcC"), &MPEG4AtomParser::ParseCodecConfig},
        {FourccType("d263"), &MPEG4AtomParser::ParseCodecConfig},
        {FourccType("esds"), &MPEG4AtomParser::ParseEsds},
        // === Audio Codec ===
        {FourccType("dfLa"), &MPEG4AtomParser::ParseDfla},   // FLAC
        {FourccType("dOps"), &MPEG4AtomParser::ParseDops},   // Opus
        // === Color ===
        {FourccType("colr"), &MPEG4AtomParser::ParseColr},
        {FourccType("aclr"), &MPEG4AtomParser::ParseAclr},
        // === Fragment ===
        {FourccType("sidx"), &MPEG4AtomParser::ParseSidx},   // line 3904
        {FourccType("mvex"), &MPEG4AtomParser::ParseMvex},
        {FourccType("trex"), &MPEG4AtomParser::ParseTrex},
        // === Meta ===
        {FourccType("meta"), &MPEG4AtomParser::ParseMeta},
        {FourccType("ilst"), &MPEG4AtomParser::ParseIlst},
        // === 等等... 共47项
    };
}
```

---

## 核心解析流程

### 主入口: MPEG4ParseHeader

流程：ftyp → moov(递归) → mdat(可选) → moof(分片)

```cpp
// mpeg4_box_parser.cpp:577
Status MPEG4AtomParser::ParseFtyp(MPEG4Atom currentAtom, int32_t depth, ParseContext* ctx);
// 解析ftyp: majorBrand/minorVersion/compatibleBrands

// mpeg4_box_parser.cpp:617
Status MPEG4AtomParser::ParseMoov(MPEG4Atom currentAtom, int32_t depth, ParseContext* ctx);
// 解析moov容器，递归调用MPEG4ParseAtom深度遍历

// mpeg4_box_parser.cpp:629
Status MPEG4AtomParser::ParseMdat(MPEG4Atom currentAtom, int32_t depth, ParseContext* ctx);
// 记录mdat位置，但不解析数据（数据由上层按需读取）

// mpeg4_box_parser.cpp:3034
Status MPEG4AtomParser::ParseMoof(const std::shared_ptr<Track>& track, int64_t offset);
// 解析Fragmented MP4的moof box
```

### ParseMoof Fragmented MP4解析流程

```cpp
Status MPEG4AtomParser::ParseMoof(const std::shared_ptr<Track>& track, int64_t offset)
{
    // 1. FindNextMoof: 定位下一个moof atom
    // 2. 遍历moof子atom: mfhd, tfhd, trun, etc.
    // 3. ProcessTfhdAtom: 解析TFHD (Track Fragment Header)
    // 4. ProcessTrunAtom: 解析TRUN (Track Fragment Run)
    // 5. FragmentEntry: 记录分片DTS和偏移
}
```

---

## 关键Atom解析详解

### 1. ParseMvhd: 电影头解析 (mpeg4_box_parser.cpp:692)

```cpp
Status MPEG4AtomParser::ParseMvhd(...)
{
    // version=0: 32位时间 [offset 16] 
    // version=1: 64位时间 [offset 24]
    // 文件时间 = duration / timescale
    // QUICKTIME_EPOCH_OFFSET = 2082844800 (Mac OS X → Unix epoch转换)
    mediaInfo_.general.Set<Tag::MEDIA_TIME_SCALE>(timeScale);
    mediaInfo_.general.Set<Tag::MEDIA_DURATION>(durationUs);
    // ParseDisplayMatrix: 从3x3矩阵提取旋转/翻转信息
}
```

**关键常量**:
- `OFFSET_V0 = 12`, `OFFSET_V1 = 20` (version不同时时间字段偏移)
- `QUICKTIME_EPOCH_OFFSET = 2082844800` (Mac时间→Unix时间戳转换)
- `DURATION_OFFSET_V0 = 16`, `DURATION_OFFSET_V1 = 24`

### 2. ParseTkhd: Track头解析 (mpeg4_box_parser.cpp:988)

解析Track ID、时长、宽高、矩阵

### 3. ParseMdhd: Media头解析 (mpeg4_box_parser.cpp:1174)

解析timescale和语言代码

### 4. ParseElst: EditList编辑列表解析 (mpeg4_box_parser.cpp:1077)

**EditList机制**:
- 每个entry: `segmentDuration + mediaTime + mediaRate`
- `elstInitEmptyEdit`: 空Edit初始化偏移
- `elstShiftStartTime`: 时间偏移量
- 用于实现起始延迟、循环播放、修剪等功能

### 5. ParseStbl: SampleTable解析 (mpeg4_box_parser.cpp:1335)

stbl是SampleTable的核心容器，解析函数:

| Atom | Parser函数 | 委托给 | 作用 |
|------|-----------|--------|------|
| stts | ParseStts | MPEG4SampleHelper::SetTimeToSampleParams | DTS间隔 |
| stss | ParseStss | MPEG4SampleHelper::SetSyncSampleParams | 关键帧索引 |
| ctts | ParseCtts | MPEG4SampleHelper::SetCompositionTimeToSampleParams | PTS偏移(CttsEntry) |
| stsc | ParseStsc | MPEG4SampleHelper::SetSampleToChunkParams | chunk→sample映射 |
| stsz | ParseStsz | MPEG4SampleHelper::SetSampleSizeParams | sample大小 |
| stco | ParseStco | MPEG4SampleHelper::SetChunkOffsetParams | chunk文件偏移 |
| stsd | ParseStsd | 直接解析 | Codec描述符 |

**ParseStsd: Codec描述符解析** (mpeg4_box_parser.cpp:1344)

```cpp
// 根据trackType分发到不同解析器:
// - VIDEO_TYPE → ParseVideoSampleEntry (avc1/hvc1/vvc1/mp4v)
// - AUDIO_TYPE → ParseAudioSampleEntry (mp4a/alac/flac/opus)
// - SUBTITLE_TYPE → ParseSubtitleSampleEntry (wvtt)
// - TIMEDMETA_TYPE → ParseMebx (timed metadata)
```

### 6. ParseVideoSampleEntry: 视频SampleEntry (mpeg4_box_parser.cpp:1401)

```cpp
// 固定字段78字节: pre_defined(2)+reserved(2)+pre_defined(12)+width(2)+height(2)
// +horizresolution(4)+vertresolution(4)+reserved(4)+frame_count(2)+compressorname(32)+depth(2)+pre_defined(2)
uint16_t width = GetU16Value(&sampleEntryInfo[24]);
uint16_t height = GetU16Value(&sampleEntryInfo[26]);

// HDR VIVID检测: 检查"CUVA HDR Video"特征字符串
// HDR_VIVID_TAG_OFFSET=43, HDR_VIVID_TAG_LENGTH=31
```

### 7. ParseAudioSampleEntry: 音频SampleEntry (mpeg4_box_parser.cpp:1550)

支持格式: mp4a(AAC), alac, flac, opus, amr, ac3, eac3, dts, g711等

### 8. ParseCodecConfig: 编码配置解析 (mpeg4_box_parser.cpp:1524)

```cpp
// avcC: AVC/H.264 SPS+PPS
// hvcC: HEVC/H.265 VPS+SPS+PPS  
// vvcC: VVC/H.266
// d263: H.263
// 数据存入 CodecParams.data/extradataSize
```

### 9. ParseEsds: MPEG4音频描述符 (mpeg4_box_parser.cpp:1943)

解析ES_Descriptor (MPEG4 Audio)，提取AudioSpecificConfig (ASC)

### 10. ParseSidx: 分片索引 (mpeg4_box_parser.cpp:2820)

```cpp
// sidx解析: firstDts + referenceId + 多个reference
// reference: subsegmentDuration + SAP类型
// 用于Fragmented MP4的随机访问
```

---

## FourCC → MimeType 映射表 (mpeg4_box_parser.cpp:151-199)

```cpp
static std::map<int32_t, std::string> typeToMime = {
    {FourccType("mp4v"), MimeType::VIDEO_MPEG4},
    {FourccType("avc1"), MimeType::VIDEO_AVC},
    {FourccType("hvc1"), MimeType::VIDEO_HEVC},
    {FourccType("hev1"), MimeType::VIDEO_HEVC},
    {FourccType("vvc1"), MimeType::VIDEO_VVC},
    {FourccType("fLaC"), MimeType::AUDIO_FLAC},
    {FourccType("mp4a"), MimeType::AUDIO_AAC},
    {FourccType("alac"), MimeType::AUDIO_ALAC},
    {FourccType("Opus"), MimeType::AUDIO_OPUS},
    {FourccType("samr"), MimeType::AUDIO_AMR_NB},
    {FourccType("dtsc"), MimeType::AUDIO_DTS},
    {FourccType("wvtt"), MimeType::TEXT_WEBVTT},
    // ... 共30+映射
};
```

---

## 音频通道布局表 (mpeg4_box_parser.cpp:215-258)

### AAC Channel Layout
```cpp
static const AudioChannelLayout AAC_CHANNEL_LAYOUT_TABLE[14] = {
    UNKNOWN, MONO, STEREO, SURROUND, CH_4POINT0, CH_5POINT0_BACK,
    CH_5POINT1_BACK, CH_7POINT1, UNKNOWN, UNKNOWN, UNKNOWN,
    CH_6POINT1_BACK, CH_7POINT1, CH_22POINT2
};
```

### FLAC/ALAC/PCM Channel Layout
```cpp
static const std::map<int32_t, AudioChannelLayout> FLAC_CHANNEL_LAYOUT_TABLE = {
    {1, MONO}, {2, STEREO}, {3, SURROUND}, {4, QUAD}, 
    {5, CH_5POINT0}, {6, CH_5POINT1}, {7, CH_6POINT1}, {8, CH_7POINT1}
};
```

### AAC Sample Rate
```cpp
static const uint32_t AAC_SAMPLE_RATE_TABLE[] = {
    96000, 88200, 64000, 48000, 44100, 32000, 24000, 22050, 16000, 12000, 11025, 8000, 7350
};
```

---

## DisplayMatrix显示矩阵解析

显示矩阵是3x3 int32_t数组，决定视频的旋转/翻转方向：

```cpp
// matrixTypes映射 (mpeg4_box_parser.cpp:202-211):
"0 -1 1 0"    → ROTATE_90
"-1 0 0 -1"  → ROTATE_180
"0 1 -1 0"   → ROTATE_270
"-1 0 0 1"   → FLIP_H
"1 0 0 -1"   → FLIP_V

// CONVERT_SCALE = 1 << 16 用于定点数转换
// Extract2x2Transform: 提取2x2变换矩阵
// ConvFp: 定点数→整数转换
```

---

## Fragmented MP4 (fMP4) / MSE 支持

### 分片检测
```cpp
bool isDistributedSidx_;  // 是否为SIDX分片
bool hasMoofBox_;         // 是否有moof
int64_t moofOffset_;      // moof文件偏移
```

### FragmentEntry管理
- ParseMoof时创建FragmentEntry
- Track链表: firstTrack_ → lastTrack_
- FragmentEntry_向量: 按moofOffset去重

### TFHD/TRUN解析
- **ProcessTfhdAtom**: 解析TrackFragmentHeaderDataBox
- **ProcessTrunAtom**: 解析TrackFragmentRunBox，获取sample计数、偏移

---

## 与S52 (TimeAndIndexConversion) 的关系

| 维度 | MPEG4BoxParser (S58) | TimeAndIndexConversion (S52) |
|------|---------------------|------------------------------|
| 层级 | 容器解析(文件结构) | 时戳换算(应用层) |
| 职责 | 解析Box提取元数据 | PTS↔帧索引互相转换 |
| 核心表 | stts/stss/ctts/stsc/stsz/stco | MP4Box结构(stbl系列) |
| 数据来源 | 文件字节流 | BoxParser解析后的元信息 |

S58负责**解析**，S52负责**换算**——两者上下游关系

---

## 证据列表 (Evidence)

| # | 文件路径 | 行号 | 内容 |
|---|----------|------|------|
| 1 | `plugins/demuxer/mpeg4_demuxer/mpeg4_box_parser.h` | 24-70 | Track、CodecParams、FragmentEntry结构体定义 |
| 2 | `plugins/demuxer/mpeg4_demuxer/mpeg4_box_parser.h` | 131-140 | MPEG4Atom结构体定义 |
| 3 | `plugins/demuxer/mpeg4_demuxer/mpeg4_box_parser.h` | 155-167 | ParseContext结构体定义 |
| 4 | `plugins/demuxer/mpeg4_demuxer/mpeg4_box_parser.cpp` | 151-199 | FourCC→MimeType映射表 |
| 5 | `plugins/demuxer/mpeg4_demuxer/mpeg4_box_parser.cpp` | 215-258 | AAC/FLAC/ALAC/PCM通道布局表 |
| 6 | `plugins/demuxer/mpeg4_demuxer/mpeg4_box_parser.cpp` | 577 | ParseFtyp函数入口 |
| 7 | `plugins/demuxer/mpeg4_demuxer/mpeg4_box_parser.cpp` | 617 | ParseMoov函数入口 |
| 8 | `plugins/demuxer/mpeg4_demuxer/mpeg4_box_parser.cpp` | 629 | ParseMdat函数入口 |
| 9 | `plugins/demuxer/mpeg4_demuxer/mpeg4_box_parser.cpp` | 692-752 | ParseMvhd完整实现(v1/v2时间戳处理) |
| 10 | `plugins/demuxer/mpeg4_demuxer/mpeg4_box_parser.cpp` | 988 | ParseTkhd函数入口 |
| 11 | `plugins/demuxer/mpeg4_demuxer/mpeg4_box_parser.cpp` | 1045 | ParseEdts函数入口 |
| 12 | `plugins/demuxer/mpeg4_demuxer/mpeg4_box_parser.cpp` | 1077-1096 | ParseElst完整实现(segment解析) |
| 13 | `plugins/demuxer/mpeg4_demuxer/mpeg4_box_parser.cpp` | 1174 | ParseMdia函数入口 |
| 14 | `plugins/demuxer/mpeg4_demuxer/mpeg4_box_parser.cpp` | 1327 | ParseMinf函数入口 |
| 15 | `plugins/demuxer/mpeg4_demuxer/mpeg4_box_parser.cpp` | 1335-1337 | ParseStbl入口(委托MPEG4SampleHelper) |
| 16 | `plugins/demuxer/mpeg4_demuxer/mpeg4_box_parser.cpp` | 1344-1392 | ParseStsd完整实现(entryCount/类型分发) |
| 17 | `plugins/demuxer/mpeg4_demuxer/mpeg4_box_parser.cpp` | 1401-1472 | ParseVideoSampleEntry完整实现(78字节固定头+HDR) |
| 18 | `plugins/demuxer/mpeg4_demuxer/mpeg4_box_parser.cpp` | 1524-1543 | ParseCodecConfig(avcC/hvcC/vvcC) |
| 19 | `plugins/demuxer/mpeg4_demuxer/mpeg4_box_parser.cpp` | 1550-1600 | ParseAudioSampleEntry入口 |
| 20 | `plugins/demuxer/mpeg4_demuxer/mpeg4_box_parser.cpp` | 1943 | ParseEsds入口(MPEG4音频描述符) |
| 21 | `plugins/demuxer/mpeg4_demuxer/mpeg4_box_parser.cpp` | 2358 | ParseDfla入口(FLAC) |
| 22 | `plugins/demuxer/mpeg4_demuxer/mpeg4_box_parser.cpp` | 2429 | ParseDops入口(Opus) |
| 23 | `plugins/demuxer/mpeg4_demuxer/mpeg4_box_parser.cpp` | 2673-2746 | stts/stss/ctts/stsc/stsz/stco六表解析 |
| 24 | `plugins/demuxer/mpeg4_demuxer/mpeg4_box_parser.cpp` | 2820-2860 | ParseSidx(分片索引) |
| 25 | `plugins/demuxer/mpeg4_demuxer/mpeg4_box_parser.cpp` | 3034-3090 | ParseMoof完整实现(Fragmented MP4) |
| 26 | `plugins/demuxer/mpeg4_demuxer/mpeg4_box_parser.cpp` | 3883-3910 | InitParseTable(47项ParseFunction路由表) |
| 27 | `plugins/demuxer/mpeg4_demuxer/mpeg4_box_parser.cpp` | 4003 | FindAtomParser路由查找 |
| 28 | `plugins/demuxer/mpeg4_demuxer/mpeg4_box_parser.cpp` | 202-211 | displayMatrix旋转/翻转类型映射 |

---

## Key Findings

1. **五级递归解析**: MPEG4AtomParser使用函数指针表+深度递进解析MP4的Box层级结构，从ftyp/moov根级到stbl表级，共47种atom类型

2. **Track链表管理**: 每个Track独立持有CodecParams、MPEG4SampleHelper和displayMatrix，通过firstTrack_/lastTrack_/currentTrack_链表管理

3. **CodecConfig三大格式**: avcC(H.264)、hvcC(HEVC)、vvcC(VVC)共享ParseCodecConfig统一处理，extra data存入CodecParams供解码器初始化

4. **Fragmented MP4支持**: ParseMoof通过FragmentEntry管理moof位置，通过TFHD/TRUN解析分片sample的偏移和DTS

5. **HDR元数据**: 通过"CUVA HDR Video"特征串检测HDR VIVID，通过dbBox(set)检测Dolby Vision

6. **EditList编辑列表**: ParseElst处理segmentDuration+mediaTime，用于时间偏移/空编辑/播放范围控制

7. **SampleTable六表委托**: 除stsd外，其他5个stbl子表(stts/stss/ctts/stsc/stsz/stco)全部委托给MPEG4SampleHelper管理

8. **版本兼容**: mvhd同时支持version 0(32位)和version 1(64位)时间戳，QuickTime时间→Unix epoch有2082844800秒偏移

9. **分片防重解析**: FragmentEntry.hasRead标志防止同一moof重复解析，fragmentEntry_向量按moofOffset去重

---

*草案生成时间: 2026-04-26T14:30*  
*Builder Agent: subagent 2e6d2d27*
