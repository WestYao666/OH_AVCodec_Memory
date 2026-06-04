# MEM-ARCH-AVCODEC-S198: MPEG4DemuxerPlugin 原生MP4解封装插件体系

## 摘要

MPEG4DemuxerPlugin 是 OpenHarmony 多媒体引擎的原生 MP4/ISOBMFF 解封装插件，基于 services/media_engine/plugins/demuxer/mpeg4_demuxer/ 目录下的六个源码文件构建，总计约 7322 行。体系包含 MPEG4AtomParser(Box 层级解析)、MPEG4SampleHelper(Sample 索引/PTS/EditList)、MPEG4AudioParser(DTS/声道布局)、MPEG4ReferenceParser(TrackReference) 四大解析器，以及 MultiStreamParserManager dlopen 动态加载机制，支持 AVC/HEVC/VVC 三路视频流和 MPEG/DTS 音频流解析。

---

## 1. 插件注册与识别机制

**Evidence 1** — `mpeg4_demuxer_plugin.cpp` L46-58：插件探测常量定义
```cpp
constexpr uint32_t DEFAULT_CACHE_LIMIT = 50 * 1024 * 1024; // 50MB
constexpr uint32_t PROBE_SIZE = 5000000;                    // 5MB
constexpr int32_t FIRST_LEVEL_RANK = 100;                   // 最高置信度
constexpr int32_t SECOND_LEVEL_RANK = 95;
constexpr int32_t THIRD_LEVEL_RANK = 50;
constexpr int32_t RANK_MIN = 5;
constexpr int32_t RANK_MAX = 100 + 1; // 适配自研优先
constexpr int64_t SNIFF_DATA_SIZE = 2048;
```
MPEG4 插件探测优先级 FIRST_LEVEL_RANK=100，自研优先。PROBE_SIZE=5MB 用于文件头探测。

**Evidence 2** — `mpeg4_demuxer_plugin.cpp` L60-68：视频流类型路由映射
```cpp
static const std::map<std::string, VideoStreamType> g_streamParserMap = {
    { "video/avc",  VideoStreamType::AVC },
    { "video/hevc", VideoStreamType::HEVC },
    { "video/vvc",  VideoStreamType::VVC },
};
bool HaveValidParser(const std::string mime)
{
    return g_streamParserMap.count(mime) != 0;
}
```
三个 MIME 类型路由到三种 VideoStreamType，用于 MultiStreamParserManager dlopen 加载对应解码器插件。

**Evidence 3** — `mpeg4_demuxer_plugin.cpp` L1557-1610：Sniff 探测入口与注册
```cpp
int Sniff(const std::string& pluginName, std::shared_ptr<DataSource> source)
{
    // ... 探测逻辑：扫描前 SNIFF_DATA_SIZE=2048 字节
    // 查找 ftyp/moov/moof/ftyp 等 Atom
    // 置信度评分：FIRST_LEVEL_RANK/SECOND_LEVEL_RANK/THIRD_LEVEL_RANK
    regInfo.SetSniffer(Sniff);
    // L1610
    Status ret = RegisterMpeg4Plugin(reg);
}
```
Sniff 函数负责文件格式探测，通过查找 ftyp/moov/moof 等 Box 判断是否为 MP4 文件。

---

## 2. MPEG4AtomParser Box 层级解析

**Evidence 4** — `mpeg4_box_parser.cpp` L617：`ParseMoov` 入口
```cpp
Status MPEG4AtomParser::ParseMoov(MPEG4Atom currentAtom, int32_t depth, ParseContext* ctx)
```
ParseMoov 负责解析 moov Atom，进而递归解析子级 trak/mdia 等 Atom。depth 参数控制解析深度。

**Evidence 5** — `mpeg4_box_parser.cpp` L892：`ParseTrak` Track 创建
```cpp
Status MPEG4AtomParser::ParseTrak(MPEG4Atom currentAtom, int32_t depth, ParseContext* ctx)
{
    auto track = std::make_shared<Track>();  // L893
    // 创建 Track 对象，加入 mediaInfo_.tracks 链表
    lastTrack_->trackIndex = trackCount_;    // L913
    lastTrack_->sampleHelper = std::make_shared<MPEG4SampleHelper>(); // L914
    lastTrack_->sampleHelper->BuildSampleIndexEntries();             // L929
    SetCodecConfig(lastTrack_);                              // L933
}
```
每个 Track 独立创建 MPEG4SampleHelper，通过 BuildSampleIndexEntries 构建 Sample 索引。

**Evidence 6** — `mpeg4_box_parser.cpp` L692：`ParseMvhd` 媒体头解析
```cpp
Status MPEG4AtomParser::ParseMvhd(MPEG4Atom currentAtom, int32_t depth, ParseContext* ctx)
```
解析 mvhd Box 获取文件级 timescale/duration 等全局元数据。

**Evidence 7** — `mpeg4_box_parser.cpp` L1335：`ParseStbl` Sample Table 解析
```cpp
Status MPEG4AtomParser::ParseStbl(MPEG4Atom currentAtom, int32_t depth, ParseContext* ctx)
```
解析 stbl Box 及其子级 stts/stsz/stsc/stco/stss/ctts 等 Sample Table 原子，获取编解码配置和 Sample 映射关系。

**Evidence 8** — `mpeg4_box_parser.cpp` L485-530：`ParseOrientationFromMatrix` / `ParseRotationTypeFromMatrix`
```cpp
void MPEG4AtomParser::ParseOrientationFromMatrix(std::shared_ptr<Track> track) // L485
void MPEG4AtomParser::ParseRotationTypeFromMatrix(std::shared_ptr<Track> track) // L525
```
从 Track 的 displayMatrix (3x3 矩阵) 解析视频旋转/方向信息。displayMatrix 按行存储 9 个 int32_t。

---

## 3. MPEG4SampleHelper Sample 索引与 PTS 管理

**Evidence 9** — `mpeg4_sample_helper.cpp` L60-67：构造初始化所有 Sample 相关 Entry 容器
```cpp
cttsEntry_(),   // composition time to sample
sttsEntry_(),   // time to sample (DTS)
stscEntry_(),   // sample to chunk
stssEntry_(),   // sync sample (I-Frame)
```
四个核心 Entry 数组：cttsEntry_(B帧延迟)/sttsEntry_(DTS)/stscEntry_(Chunk映射)/stssEntry_(I帧)。

**Evidence 10** — `mpeg4_sample_helper.cpp` L230-233：`SetTimeToSampleParams` 解析 STTS
```cpp
Status MPEG4SampleHelper::SetTimeToSampleParams(int64_t dataOffset, size_t dataSize)
{
    sttsEntry_.reserve(numSttsEntries);
    for (uint32_t i = 0; i < numSttsEntries; i++) {
        sttsEntry_.emplace_back(SttsEntry{ ... });
    }
}
```
STTS(Decoding Time to Sample) 解析，将 DTS 映射到 Sample 索引。

**Evidence 11** — `mpeg4_sample_helper.cpp` L242-274：`SetCompositionTimeToSampleParams` 解析 CTTS
```cpp
Status MPEG4SampleHelper::SetCompositionTimeToSampleParams(int64_t dataOffset, size_t dataSize) // L242
{
    cttsEntry_.reserve(numCttsEntries);
    cttsEntry_.emplace_back(CttsEntry { ... });
}
```
CTTS(Composition Time to Sample) 解析，存储 B 帧与 P 帧之间的 composition offset。

**Evidence 12** — `mpeg4_sample_helper.cpp` L283-319：`SetSyncSampleParams` 解析 STSS
```cpp
Status MPEG4SampleHelper::SetSyncSampleParams(int64_t dataOffset, size_t dataSize) // L283
{
    stssEntry_.reserve(numSyncs);
    stssEntry_.emplace_back(StssEntry{ ... });
}
```
STSS(Sync Sample Table) 解析，标识 I-Frame 位置，用于 Seek 定位。

**Evidence 13** — `mpeg4_sample_helper.cpp` L79-150：`FindSyncSampleAtTime` 同步帧查找
```cpp
Status MPEG4SampleHelper::FindSyncSampleAtTime(int64_t inputPTS, bool isBaseTrack,
    SeekMode flag, uint32_t &sampleIndex) // L151
{
    if (!stssEntry_.empty()) {
        ret = FindWithSyncSamples(inputPTS, isBaseTrack, flag, syncIndex);
        currentIndex = stssEntry_[syncIndex].index;
    } else {
        currentIndex = stssEntry_.empty() ? 0 : stssEntry_[0].index; // 无STSS则默认首帧
    }
}
```
Seek 时通过 STSS 定位最近的 I-Frame。

---

## 4. MPEG4AudioParser DTS/声道布局解析

**Evidence 14** — `mpeg4_audio_parser.cpp` L33-43：声道数→声道布局映射表
```cpp
const std::vector<std::pair<int32_t, AudioChannelLayout>> g_channelLayoutDefaultMap = {
    {2, AudioChannelLayout::STEREO},              // 2ch → STEREO
    {4, AudioChannelLayout::CH_4POINT0},         // 4ch → 4.0
    {6, AudioChannelLayout::CH_5POINT1},         // 6ch → 5.1
    {8, AudioChannelLayout::CH_5POINT1POINT2},   // 8ch → 5.1.2
    {9, AudioChannelLayout::HOA_ORDER2_ACN_N3D}, // 9ch → HOA
    {10, AudioChannelLayout::CH_7POINT1POINT2},  // 10ch
    {12, AudioChannelLayout::CH_7POINT1POINT4},  // 12ch
    {14, AudioChannelLayout::CH_9POINT1POINT4},  // 14ch
    {16, AudioChannelLayout::CH_9POINT1POINT6},  // 16ch
    {24, AudioChannelLayout::CH_22POINT2},       // 24ch
};
```
MPEG4 音频根据 channel_count 查表映射到 AudioChannelLayout，支持最高 24 声道。

**Evidence 15** — `mpeg4_audio_parser.h` L21-25：音频解析器接口
```cpp
class MPEG4AudioParser {
public:
    explicit MPEG4AudioParser();
    AudioChannelLayout FindValidChannelLayout(uint64_t layoutMask); // L28
    AudioChannelLayout GetDefaultChannelLayout(int32_t channels);  // L29
    Status ParseAudioFrame(uint8_t* data, uint32_t size, std::string mime,
        uint32_t trackIndex, MediaInfo& mediaInfo);               // L30
    Status ParseMpegAudio(MediaInfo& mediaInfo);                   // L32
    Status ParseDtsAudio(MediaInfo& mediaInfo);                    // L33
};
```
音频解析器支持 MPEG Audio 和 DTS Audio 两种格式。

---

## 5. MultiStreamParserManager dlopen 动态加载

**Evidence 16** — `mpeg4_demuxer_plugin.cpp` L321-326：HEVC/AVC/VVC 动态加载
```cpp
streamParsers_ = std::make_shared<MultiStreamParserManager>(); // L321
// ...
if (HaveValidParser(mime) && streamParsers_ != nullptr) {
    Status ret = streamParsers_->Create(trackIndex, g_streamParserMap.at(mime)); // L326
}
```
根据 VideoStreamType(AVC/HEVC/VVC) 通过 MultiStreamParserManager dlopen 动态加载对应的 AnnexB/HEVC-VVC 解码器插件。

**Evidence 17** — `mpeg4_demuxer_plugin.cpp` L499-516：ParseHEVCMetadataInfo HEVC 元数据提取
```cpp
void MPEG4DemuxerPlugin::ParseHEVCMetadataInfo(const MPEG4AtomParser::Track& track, Meta& format) // L499
{
    MultiStreamParserManager::ParseMetadataInfo(trackIndex, streamParsers_, parse);
    HEVCProfile profile = Converter::ConvertToOHHEVCProfile(static_cast<int>(parse.profile));    // L508
    HEVCLevel level = Converter::ConvertToOHHEVCLevel(static_cast<int>(parse.level));           // L515
}
```
通过 MultiStreamParserManager 提取 HEVC profile/level 元数据并转换为 OpenHarmony 标准枚举值。

---

## 6. Fragment 解析 (Moof)

**Evidence 18** — `mpeg4_demuxer_plugin.cpp` L844：`ParseMoof` 分片解析入口
```cpp
Status MPEG4DemuxerPlugin::ParseMoof(int64_t offset)
{
    Status ret = parser->ParseMoof(firstTrack_, offset); // L854
}
```
支持 CMAFB(Fragmented MP4) 格式，ParseMoof 解析 moof Atom 及其 trun/traf 子原子。

---

## 文件清单

| 文件 | 行数 | 职责 |
|------|------|------|
| `mpeg4_box_parser.cpp` | 4378 | MPEG4AtomParser: Box 层级解析、moov/moof/trak/mdia/stbl |
| `mpeg4_demuxer_plugin.cpp` | 1625 | MPEG4DemuxerPlugin: DemuxerPlugin 实现、Sniff 探测、API |
| `mpeg4_sample_helper.cpp` | 1009 | MPEG4SampleHelper: Sample 索引、PTS/STTS/CTTS/STSS 管理 |
| `mpeg4_audio_parser.cpp` | 199 | MPEG4AudioParser: DTS/MPEG 音频解析、声道布局映射 |
| `mpeg4_reference_parser.cpp` | 111 | MPEG4ReferenceParser: TrackReference 引用关系 |
| `mpeg4_utils.h` | 119 | 工具函数、Fourcc、Atom 定义 |
| `mpeg4_box_parser.h` | 287 | MPEG4AtomParser Track 结构体、CodecParams、HdrBoxInfo |
| `mpeg4_demuxer_plugin.h` | 191 | MPEG4DemuxerPlugin 类完整接口 |
| `mpeg4_sample_helper.h` | 164 | MPEG4SampleHelper 类完整接口 |
| `mpeg4_audio_parser.h` | 43 | MPEG4AudioParser 类接口 |

**总计约 7322 行**，覆盖 ISOBMFF 完整解析链路。

---

## 关联记忆

- **S177** Demuxer Common 共享解析工具链：MultiStreamParserManager / StreamParser / Converter / TimeRangeManager / ReferenceParserManager 五组件
- **S97/S68/S74** MPEG4/FFmpegDemuxer 关联体系
- **S192** FFmpegDemuxerPlugin — 互补：FFmpeg 接入 vs 原生接入
- **S187** DASH MPD Parser — 并列：自适应流双源头

---

*草案文件 | Builder Agent | 2026-06-04*
*基于 /home/west/av_codec_repo/services/media_engine/plugins/demuxer/mpeg4_demuxer/ 源码*
