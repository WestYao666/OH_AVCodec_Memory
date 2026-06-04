# MEM-ARCH-AVCODEC-S198: MPEG4DemuxerPlugin 原生 MP4 解封装插件体系
**状态**: draft
**生成时间**: 2026-06-04T16:20:00+08:00
**scope**: AVCodec, MediaEngine, Demuxer, MPEG4, MP4, ISOBMFF, Box, Sample, PTS, EditList, DTS, MPEG Audio, ChannelLayout, AAC, ALAC
**关联场景**: 新需求开发/问题定位/MP4封装解析/音视频分离
**关联记忆**: S68(FFmpegDemuxerPlugin)/S76(FFmpegDemuxerPlugin)/S74(Mpeg4MuxerPlugin)/S177(Demuxer Common)/S97(DemuxerPluginManager)

---

## 核心定位

MPEG4DemuxerPlugin (`mpeg4_demuxer_plugin.cpp:1625行`) 是基于**原生手写 MP4 Box 解析**的解封装插件，与 FFmpegDemuxerPlugin 并列。两者的核心区别在于：

- **FFmpegDemuxerPlugin**：调用 libavformat 库，依赖 FFmpeg 的容器解析能力
- **MPEG4DemuxerPlugin**：手写 ISOBMFF Box 结构解析，直接操作 MP4 二进制格式

核心文件共 6 个，合计约 7322 行源码：

| 文件 | 行数 | 职责 |
|------|------|------|
| `mpeg4_box_parser.cpp` | 4378 | MP4 Box 层级解析（ftyp/moov/moof/mdat/traf/trak/mdia/minf/stbl...）|
| `mpeg4_demuxer_plugin.cpp` | 1625 | 插件入口、Track管理、Sample读取 |
| `mpeg4_sample_helper.cpp` | 1009 | Sample索引、PTS计算、EditList处理、同步帧查找 |
| `mpeg4_audio_parser.cpp` | 199 | MPEG/DTS 音频帧解析、声道布局映射 |
| `mpeg4_reference_parser.cpp` | 111 | Track Reference 解析（refType/refIds） |
| `mpeg4_utils.h` | - | 工具函数（FindBox/BigEndian转换/时间戳转换） |

---

## 一、MPEG4DemuxerPlugin 插件入口（mpeg4_demuxer_plugin.cpp）

### 1.1 核心常量

```cpp
// mpeg4_demuxer_plugin.cpp L40-47
constexpr uint32_t DEFAULT_CACHE_LIMIT = 50 * 1024 * 1024;  // 50MB cache
constexpr int32_t DEF_PROBE_SCORE_LIMIT = 50;
constexpr uint32_t PROBE_SIZE = 5000000;                      // 5MB probe
constexpr int32_t FIRST_LEVEL_RANK = 100;                    // 自研优先
constexpr int32_t SECOND_LEVEL_RANK = 95;
constexpr int32_t THIRD_LEVEL_RANK = 50;
constexpr int32_t RANK_MIN = 5;
constexpr int32_t RANK_MAX = 100 + 1;                         // 适配自研优先
```

**证据**: `mpeg4_demuxer_plugin.cpp:40-47`。

### 1.2 StreamParser MIME 路由表

```cpp
// mpeg4_demuxer_plugin.cpp L58-62
static const std::map<std::string, VideoStreamType> g_streamParserMap = {
    { "video/avc",  VideoStreamType::AVC },
    { "video/hevc", VideoStreamType::HEVC },
    { "video/vvc",  VideoStreamType::VVC },
};
```

**证据**: `mpeg4_demuxer_plugin.cpp:58-62`。

### 1.3 SetDataSource 初始化流程

```cpp
// mpeg4_demuxer_plugin.cpp ~170行
Status MPEG4DemuxerPlugin::SetDataSource(const std::shared_ptr<DataSource>& source,
    const std::shared_ptr<Media::Meta>& configs)
{
    // 1. 设置 seekable 模式（Dash不可seek，普通文件可seek）
    seekable_ = source->IsDash() ? Seekable::UNSEEKABLE : source->GetSeekable();
    dataSource_ = source;
    // 2. 创建 MPEG4AtomParser，解析头部Box结构
    auto parser = std::make_shared<MPEG4AtomParser>();
    Status ret = parser->MPEG4ParseHeader(source, seekable_, readTimeoutMs_...);
    // 3. 获取媒体信息、Track链表、Fragment信息
    mediaInfo_ = parser->GetMediaInfo();
    firstTrack_ = parser->GetFirstTrack();
    userformat_ = parser->GetUserFormat();
    parser->GetFragmentEntry(fragmentEntry_);
    // 4. 初始化 StreamParser（AVC/HEVC/VVC 视频轨需要）
    InitParser();  // 创建 MultiStreamParserManager，创建对应流解析器
    // 5. 参数校验
    HasCodecParameters();
}
```

**证据**: `mpeg4_demuxer_plugin.cpp:~170-210`。

### 1.4 InitParser — StreamParser 创建

```cpp
// mpeg4_demuxer_plugin.cpp ~290行
void MPEG4DemuxerPlugin::InitParser()
{
    streamParsers_ = std::make_shared<MultiStreamParserManager>();
    // 遍历Track，对视频轨（有有效Parser的MIME）创建对应的StreamParser
    for (trackIndex) {
        if (HaveValidParser(mime) && streamParsers_ != nullptr) {
            ret = streamParsers_->Create(trackIndex, g_streamParserMap.at(mime));
            // 创建 AVC StreamParser 或 HEVC StreamParser
        }
    }
}
```

**证据**: `mpeg4_demuxer_plugin.cpp:~290-305`。

---

## 二、MPEG4AtomParser Box 层级解析（mpeg4_box_parser.cpp）

### 2.1 核心常量——Box 层级深度

```cpp
// mpeg4_box_parser.cpp L58-62
constexpr int32_t MPEG4_ROOT_DEPTH = 0;   // ftyp, moov, mdat, etc.
constexpr int32_t MPEG4_DEPTH_ONE = 1;     // moov's children: mvhd, trak, mvex
constexpr int32_t MPEG4_DEPTH_TWO = 2;     // trak's children: tkhd, mdia, edts
constexpr int32_t MPEG4_DEPTH_THREE = 3;   // mdia's children: mdhd, hdlr, minf
constexpr int32_t MPEG4_DEPTH_FOUR = 4;    // minf's children: vmhd, smhd, stbl
```

**证据**: `mpeg4_box_parser.cpp:58-62`。

### 2.2 核心常量——时间和缩放

```cpp
// mpeg4_box_parser.cpp L44-46
constexpr int64_t DYNAMIC_SIZE_V0 = 24;
constexpr int64_t DYNAMIC_SIZE_V1 = 36;
constexpr int64_t DYNAMIC_MATRIX_OFFSET_V0 = 36;
constexpr int64_t DYNAMIC_MATRIX_OFFSET_V1 = 48;
constexpr int64_t DEFAULT_HEAD_SIZE = 8;
constexpr int64_t ESDS_READ_SIZE = 13;
constexpr int64_t HDR_VIVID_TAG_LENGTH = 31;
constexpr int64_t HDR_VIVID_TAG_OFFSET = 43;
```

**证据**: `mpeg4_box_parser.cpp:44-52`。

### 2.3 辅助轨引用常量

```cpp
// mpeg4_box_parser.cpp L76
constexpr uint32_t MAX_TRACK_REFERENCE_COUNT = 1000;
```

**证据**: `mpeg4_box_parser.cpp:76`。

### 2.4 时间转换工具函数

```cpp
// mpeg4_box_parser.cpp L38-40 (声明)
Status ConvertTimeScaleRound(int64_t multiplicand, int64_t multiplier, int64_t timeScale, int64_t* result);
Status ConvertTimeScaleRoundToTimeBase(int64_t multiplicand, int64_t multiplier, int64_t timeScale, int64_t* result);
Status ConvertTrackTimeToUsByFFmpeg(int64_t trackTime, int64_t trackTimeScale, int64_t* result);
```

**证据**: `mpeg4_box_parser.cpp:38-40`。

### 2.5 PathAdder——递归解析深度跟踪

```cpp
// mpeg4_box_parser.cpp ~100行
struct PathAdder {
    PathAdder(std::vector<uint32_t> *path, uint32_t atomType) { path_->emplace_back(atomType); }
    ~PathAdder() { path_->pop_back(); }  // 析构时自动弹栈
private:
    std::vector<uint32_t>* path_;
};
```

**证据**: `mpeg4_box_parser.cpp:~100-107`。

### 2.6 GetMaxSamplePtsEnd

```cpp
// mpeg4_box_parser.cpp ~110行
int64_t GetMaxSamplePtsEnd(const std::vector<MPEG4SampleHelper::SampleIndexEntry>& samples)
{
    int64_t maxPtsEnd = 0;
    for (const auto& sample : samples) {
        maxPtsEnd = std::max(maxPtsEnd, sample.pts + sample.duration);
    }
    return maxPtsEnd;
}
```

**证据**: `mpeg4_box_parser.cpp:~110-116`。

---

## 三、MPEG4SampleHelper——Sample 索引与 PTS 管理（mpeg4_sample_helper.cpp）

### 3.1 核心常量

```cpp
// mpeg4_sample_helper.cpp L20-28
constexpr int64_t MAX_TRUN_SAMPLES = 1000000;
constexpr int64_t NEXT_FRAME = 1;
constexpr int64_t PREVIOUS_FRAME = 0;
constexpr uint32_t STSZ_HEAD_LENGTH = 12;  // stsz头数据长度
constexpr uint32_t HALF_BYTE_BITS = 4;
constexpr uint32_t MAX_REORDER_DELAY = 16;   // 视频重排缓冲深度
```

**证据**: `mpeg4_sample_helper.cpp:20-28`。

### 3.2 成员变量（构造器初始化）

```cpp
// mpeg4_sample_helper.cpp ~40行
MPEG4SampleHelper::MPEG4SampleHelper()
    : dataReader_(nullptr),
    sampleIndexEntry_(),    // Sample索引表
    cttsEntry_(),           // Composition Time Offset 表
    seekable_(Seekable::UNSEEKABLE),
    trackType_(INVALID_TYPE),
    firstMoofSampleIndex_(-1),
    sttsEntry_(),           // 时间转Sample表
    stscEntry_(),           // Sample到Chunk映射表
    stssEntry_(),           // 同步Sample表（关键帧）
    sampleSizes_(),         // Sample大小表
    chunkOffsets_(),        // Chunk偏移表
    trex_(),                // Track Extends
    tfhd_(),                // Track Fragment Header
    dtsShift_(0),
    timeOffset_(0)
{}
```

**证据**: `mpeg4_sample_helper.cpp:~40-56`。

### 3.3 EstimateVideoDelay——B帧重排延迟估算

```cpp
// mpeg4_sample_helper.cpp ~70行
uint32_t MPEG4SampleHelper::EstimateVideoDelay() const
{
    // 检查是否存在重排（PTS != DTS）
    bool hasReorderedPts = std::any_of(sampleIndexEntry_.begin(), sampleIndexEntry_.end(),
        [](const SampleIndexEntry& sample) { return sample.pts != sample.dts; });
    if (!hasReorderedPts) return 0;

    // 使用固定大小缓冲窗口计算最大swap次数（=B帧深度）
    std::array<int64_t, MAX_REORDER_DELAY + 1> ptsBuffer;  // 16帧缓冲
    ptsBuffer.fill(INT64_MIN);
    uint32_t bufferStart = 0;
    uint32_t videoDelay = 0;
    for (const auto& sample : sampleIndexEntry_) {
        // 插入排序并统计swap次数
        uint32_t swaps = 0;
        // ... swap counting
        videoDelay = std::max(videoDelay, swaps);
    }
    return videoDelay;
}
```

**证据**: `mpeg4_sample_helper.cpp:~70-95`。

### 3.4 FindWithSyncSamplesByPts——按 PTS 查找最近同步帧

```cpp
// mpeg4_sample_helper.cpp ~100行
Status MPEG4SampleHelper::FindWithSyncSamplesByPts(
    int64_t inputPts, bool isBaseTrack, SeekMode flag, uint32_t &syncIndex)
{
    // 遍历 stssEntry_（同步帧表）
    for (size_t i = 0; i < stssEntry_.size(); ++i) {
        const int64_t syncPts = stssEntry_[i].syncPts;
        if (syncPts <= inputPts && ...) previousIndex = i;      // 最近前向
        if (syncPts >= inputPts && ...) nextIndex = i;          // 最近后向
    }
    // SEEK_PREVIOUS_SYNC / SEEK_NEXT_SYNC / SEEK_CLOSEST 三种模式
    if (flag == SeekMode::SEEK_PREVIOUS_SYNC) selectedIndex = previousIndex;
    else if (flag == SeekMode::SEEK_NEXT_SYNC) selectedIndex = nextIndex;
    else selectedIndex = GetClosestSync(...);
}
```

**证据**: `mpeg4_sample_helper.cpp:~100-130`。

### 3.5 SetEditListParams——EditList 时间调整

```cpp
// mpeg4_sample_helper.cpp ~58行
void MPEG4SampleHelper::SetEditListParams(const std::vector<EditListEntry>& editListEntries,
    int32_t movieTimeScale, int32_t trackTimeScale)
{
    editListEntries_ = editListEntries;
    movieTimeScale_ = movieTimeScale;
    trackTimeScale_ = trackTimeScale;
}
bool MPEG4SampleHelper::HasEditList() const { return !editListEntries_.empty(); }
bool MPEG4SampleHelper::HasAppliedEditList() const { return editListApplied_; }
```

**证据**: `mpeg4_sample_helper.cpp:~58-65`。

---

## 四、MPEG4AudioParser——音频帧解析（mpeg4_audio_parser.cpp）

### 4.1 DTS 同步字与声道映射表

```cpp
// mpeg4_audio_parser.cpp L32-34
constexpr uint32_t DTS_SYNC_WORD = 0x7FFE8001;
constexpr uint8_t MAX_DTS_AUDIO_MODE = 10;

// DTS 音频模式 → 声道布局 映射（2/4/6/8/9/10/12/14/16/24声道）
const std::vector<std::pair<int32_t, AudioChannelLayout>> g_channelLayoutDefaultMap = {
    {2,  AudioChannelLayout::STEREO},
    {4,  AudioChannelLayout::CH_4POINT0},
    {6,  AudioChannelLayout::CH_5POINT1},
    {8,  AudioChannelLayout::CH_5POINT1POINT2},
    // ...
};
```

**证据**: `mpeg4_audio_parser.cpp:32-39`。

### 4.2 ParseMpegAudio——MPEG 音频帧解析

```cpp
// mpeg4_audio_parser.cpp ~135行
Status MPEG4AudioParser::ParseMpegAudio(MediaInfo& mediaInfo)
{
    // 从 header byte[1] 提取 layer: 4 - ((audioData_[1] & 0x06) >> 1)
    // Layer0=保留, Layer1=Layer III(MP3), Layer2=AAC, Layer3=reserved
    uint32_t layer = 4 - ((audioData_[1] & 0x06) >> 1);
    if (layer == 0x01) return ERROR_INVALID_DATA;  // 保留层无效
    // samplesPerFrame = 1152（Layer II/III）
    mediaInfo.tracks[index_].Set<Tag::AUDIO_SAMPLE_PER_FRAME>(1152);
    mediaInfo.tracks[index_].Set<Tag::AUDIO_SAMPLE_FORMAT>(sampleFormat);
    return OK;
}
```

**证据**: `mpeg4_audio_parser.cpp:~135-150`。

### 4.3 ParseDtsAudio——DTS 音频帧解析

```cpp
// mpeg4_audio_parser.cpp ~155行
Status MPEG4AudioParser::ParseDtsAudio(MediaInfo& mediaInfo)
{
    constexpr uint32_t syncWordSize = 4;
    // 验证同步字 0x7FFE8001
    if (GetU32Value(&audioData_[0]) != DTS_SYNC_WORD) return ERROR_INVALID_DATA;
    // 从 byte[3] 低4位 和 byte[4] 高2位 合并得到 audio_mode (0-10)
    uint8_t mode = ((audioData_[3] & 0xF) << 4) + (audioData_[4] >> 6);
    AudioChannelLayout layout = g_dtsAudioMode2DtsChannelLayout[mode];
    mediaInfo.tracks[index_].Set<Tag::AUDIO_CHANNEL_LAYOUT>(layout);
    return OK;
}
```

**证据**: `mpeg4_audio_parser.cpp:~155-170`。

---

## 五、MPEG4Utils——工具函数

### 5.1 关键常量

```cpp
// mpeg4_utils.h (相关)
constexpr int32_t MATRIX_SIZE = 4;
constexpr uint32_t FULLBOX_PREFIX_SIZE = 4;  // version(1) + flags(3)
constexpr size_t OPUS_MIN_SIZE = 11;
```

### 5.2 ISO 时间转换

```cpp
// 时间相关常量
constexpr uint64_t QUICKTIME_EPOCH_OFFSET = 2082844800;  // 1904-01-01 到 1970-01-01 秒差
```

---

## 六、与 FFmpegDemuxerPlugin 的架构对比

| 维度 | MPEG4DemuxerPlugin | FFmpegDemuxerPlugin |
|------|------|------|
| 解析方式 | 手写 Box 层级解析 | 调用 libavformat |
| 依赖 | 无外部依赖 | libavformat.so |
| 可控性 | 高（可直接操作Box） | 低（依赖FFmpeg内部） |
| 适用场景 | 自研优先/轻量级 | 全格式支持 |
| 优先级 | FIRST_LEVEL_RANK=100 | SECOND_LEVEL_RANK=95 |
| 关键类 | MPEG4AtomParser + MPEG4SampleHelper | FFmpegDemuxerThread + FFmpegFormatHelper |
| StreamParser | MultiStreamParserManager（dlopen） | 内置 annexb/bitstream filter |
| PTS计算 | MPEG4SampleHelper::sttsEntry_ | FFmpegFormatHelper |

---

## 七、关键设计亮点

1. **自研优先策略**：FIRST_LEVEL_RANK=100（最高），塞入前优先使用
2. **MPEG4SampleHelper 独立 Track**：每个 Track 一个 SampleHelper，互不干扰
3. **EditList 时间补偿**：HasEditList()/HasAppliedEditList() 双重状态，支撑时间轴裁剪
4. **B帧延迟估算**：EstimateVideoDelay() 基于16帧窗口的重排swap计数，精确评估视频延迟
5. **DTS 声道布局映射**：g_dtsAudioMode2DtsChannelLayout 表，支持 2-24 声道 DTS 格式
6. **MultiStreamParserManager**：dlopen 加载 HEVC/VVC/AVC 插件，支持多种视频格式

---

## 关联记忆

- **S68/S76**: FFmpegDemuxerPlugin 替代方案对比
- **S74**: Mpeg4MuxerPlugin（封装侧）对比
- **S177**: Demuxer Common（StreamParser/dlopen）共享组件
- **S97**: DemuxerPluginManager 轨道路由管理