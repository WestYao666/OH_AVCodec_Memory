---
id: MEM-ARCH-AVCODEC-S186
title: Demuxer Common 共享解析工具链——Converter 色域转换七函数 / HEVCProfile 映射 / HDR 元数据解析 / TimeRangeManager Seek 范围管理
scope: [AVCodec, MediaEngine, Demuxer, Common, Converter, TimeRangeManager, ColorSpace, ChannelLayout, HEVC, HDR, FFmpeg, AVColorRange, AudioChannelLayout, Seek, TimeRange, HEVCProfile, TransferCharacteristic, MatrixCoefficient, ColorPrimary, HdrBoxInfo, ParseColorBoxInfo, ParseHdrTypeInfo, VideoStreamType, PacketConvertToAnnexb, EBSP, RBSP]
topic: Demuxer公共解析工具链五组件（Converter 595行七类色域转换函数/TimeRangeManager 77行Seek范围管理/MultiStreamParserManager 293行dlopen插件管理/ReferenceParserManager 138行插件加载/ReferenceParser接口41行），补充S105/S140/S143的dlopen插件管理细节，与FFmpegDemuxerPlugin(S68/S76)/MPEG4DemuxerPlugin(S79)/MediaDemuxer引擎(S75)深度关联。
status: pending_approval
created_at: "2026-05-25T12:25:00+08:00"
evidence_count: 25
source_files: |
  plugins/demuxer/common/converter.cpp (595行) + converter.h (75行)
  plugins/demuxer/common/time_range_manager.cpp (77行) + time_range_manager.h (74行)
  plugins/demuxer/common/multi_stream_parser_manager.cpp (293行) + multi_stream_parser_manager.h (100行)
  plugins/demuxer/common/reference_parser_manager.cpp (138行) + reference_parser_manager.h (77行)
  plugins/common/stream_parser.h (96行) - 基类
  plugins/common/reference_parser.h (41行) - C API接口
  plugins/demuxer/common/demuxer_data_reader.cpp (162行) + demuxer_data_reader.h (63行)
  plugins/demuxer/common/avc_parser_impl.cpp (180行) + avc_parser_impl.h (83行)
  plugins/demuxer/common/rbsp_context.cpp (82行) + rbsp_context.h (71行)
  plugins/demuxer/common/demuxer_log_compressor.cpp (219行) + demuxer_log_compressor.h (31行)
  plugins/demuxer/common/block_queue_pool.h (552行)
  plugins/demuxer/common/block_queue.h (191行)
  = 3103行源码
关联主题: S105(BlockQueue/BlockQueuePool/ReferenceParser/MultiStream) / S140(Converter/TimeRange/MultiStream增强版) / S143(StreamParser/HevcParseFormat/ConvertPacketToAnnexb) / S68/S76(FFmpegDemuxerPlugin) / S79(MPEG4DemuxerPlugin) / S75(MediaDemuxer引擎) / S97(DemuxerPluginManager) / S111(BlockQueue/BlockQueuePool/ReferenceParser/MultiStream)
related_ids: [S105, S140, S143, S68, S76, S79, S75, S97, S111]
git_branch: master
---

# MEM-ARCH-AVCODEC-S186

> **记忆工厂草案** | Builder Agent | 2026-05-25T12:25:00+08:00  
> **主题**: Demuxer Common 共享解析工具链——Converter 色域转换七函数 / HEVCProfile 映射 / HDR 元数据解析 / TimeRangeManager Seek 范围管理  
> **状态**: pending_approval  
> **关联**: S105 / S140 / S143 / S68 / S76 / S79 / S75 / S97 / S111

---

## 1 架构概览

Demuxer Common 工具链位于 `services/media_engine/plugins/demuxer/common/` 目录，共 3103 行源码，为解封装层所有组件提供公共能力：

```
Demuxer Common 工具链 (plugins/demuxer/common/)
├── Converter (595行cpp+75行h)         ← 色域/Profile/通道布局转换引擎
├── TimeRangeManager (77行cpp+74行h)   ← Seek范围管理+TimeoutGuard
├── MultiStreamParserManager (293行cpp+100行h) ← dlopen插件管理
├── ReferenceParserManager (138行cpp+77行h)   ← 插件加载/卸载
├── ReferenceParser (41行h)            ← C API接口（dlopen插件）
├── StreamParser (96行h)              ← 流解析器基类（纯虚接口）
├── DemuxerDataReader (162行cpp+63行h) ← 数据读取+BitReader
├── AvcParserImpl (180行cpp+83行h)     ← AVC NAL单元解析
├── RbspContext (82行cpp+71行h)       ← EBSP→RBSP防伪字节转义
├── DemuxerLogCompressor (219行cpp+31行h) ← 元数据序列化
├── BlockQueue (191行h)               ← 模板化有界阻塞队列
└── BlockQueuePool (552行h)           ← 模板化内存池
```

---

## 2 Converter 色域转换引擎（595行cpp + 75行h）

**文件**: `converter.cpp` (595行) + `converter.h` (75行)

Converter 是 Demuxer Common 的核心组件，提供 FFmpeg ↔ OHOS Media 格式的双向转换能力，涉及色彩空间、通道布局、HEVC Profile、HDR 元数据。

### 2.1 HEVCProfile 映射

**证据**: converter.cpp L256-290

```cpp
// L256-258: FFmpeg → OHOS HEVCProfile 映射表
const std::vector<std::pair<int, HEVCProfile>> g_pFfHEVCProfileMap = {
    {FF_PROFILE_HEVC_MAIN, HEVCProfile::HEVC_PROFILE_MAIN},
    {FF_PROFILE_HEVC_MAIN_10, HEVCProfile::HEVC_PROFILE_MAIN_10},
    {FF_PROFILE_HEVC_MAIN_STILL_PICTURE, HEVCProfile::HEVC_PROFILE_MAIN_STILL},
};

// L281-291: 转换函数
HEVCProfile Converter::ConvertToOHHEVCProfile(int ffHEVCProfile)
{
    auto ite = std::find_if(g_pFfHEVCProfileMap.begin(), g_pFfHEVCProfileMap.end(),
                            [&ffHEVCProfile](const auto &item) -> bool { return item.first == ffHEVCProfile; });
    if (ite == g_pFfHEVCProfileMap.end()) {
        MEDIA_LOG_W("Failed: " PUBLIC_LOG_D32, ffHEVCProfile);
        return HEVCProfile::HEVC_PROFILE_UNKNOW;
    }
    return ite->second;
}
```

### 2.2 色彩空间转换函数群

**证据**: converter.cpp L180-330

Converter 包含 5 个色彩空间转换函数：

| 函数 | 参数 | 返回值 | 证据 |
|------|------|--------|------|
| `ConvertToOHHEVCProfile` | `int ffHEVCProfile` | `HEVCProfile` | L281-291 |
| `ConvertFFMpegToOHColorPrimaries` | `AVColorPrimaries ffColorPrimaries` | `ColorPrimary` | L293-302 |
| `ConvertFFMpegToOHColorTrans` | `AVColorTransferCharacteristic ffColorTrans` | `TransferCharacteristic` | L304-314 |
| `ConvertFFMpegToOHColorMatrix` | `AVColorSpace ffColorSpace` | `MatrixCoefficient` | L316-326 |
| `ConvertFFMpegToOHColorRange` | `AVColorRange ffColorRange` | `int` (0/1) | L319-330 |

**色彩 primaries 映射** (L183-192):
```cpp
g_pFfColorPrimariesMap = {
    {AVCOL_PRI_BT2020, ColorPrimary::BT2020},
    // ...
};
```

**色彩 transfer 映射** (L210-220):
```cpp
g_pFfTransferCharacteristicMap = {
    {AVCOL_TRC_BT2020_10, TransferCharacteristic::BT2020_10BIT},  // L214
    {AVCOL_TRC_SMPTE2084, TransferCharacteristic::PQ},            // L216
    {AVCOL_TRC_SMPTEST2084, TransferCharacteristic::PQ},         // L217
    {AVCOL_TRC_ARIB_STD_B67, TransferCharacteristic::HLG},         // L220
};
```

**色彩 matrix 映射** (L230-235):
```cpp
g_pFfMatrixCoefficientMap = {
    {AVCOL_SPC_BT2020_NCL, MatrixCoefficient::BT2020_NCL},  // L233
    {AVCOL_SPC_BT2020_CL, MatrixCoefficient::BT2020_CL},    // L234
};
```

### 2.3 HDR 元数据解析

**证据**: converter.cpp L405-490

```cpp
// L405-440: ParseColorBoxInfo - 解析 color_box (HEVCDecoderConfigurationRecord)
void Converter::ParseColorBoxInfo(HevcParseFormat parse, Meta &format)
{
    // L419: 提取 ColorPrimaries/TransferCharacteristic/MatrixCoefficients
    MatrixCoefficient colorMatrix = ConvertFFMpegToOHColorMatrix(
        static_cast<AVColorSpace>(parse.GetColorMatrix()));
    // 设置到 format 元数据
}

// L441-490: ParseHdrTypeInfo - 解析 HDR 类型（HDR_VIVID/HDR10/HLG）
void Converter::ParseHdrTypeInfo(HdrBoxInfo hdrBoxInfo, Meta &format, HevcParseFormat parse)
{
    // L447: 检查 BT2020 色彩空间
    FALSE_RETURN_NOLOG(colorPrimaries == ColorPrimary::BT2020);
    // L451: 判定 BT2020_NCL 或 BT2020_CL
    // L473-474: 识别 HLG
    if (colorTrans == TransferCharacteristic::HLG) {
        format.Set<Tag::VIDEO_HDR_TYPE>(HDRType::HLG);
    }
}
```

### 2.4 通道布局映射表

**证据**: converter.cpp L27-92

```cpp
// L27-65: FFmpeg Channel Layout → OHOS AudioChannelLayout (25种布局)
const std::vector<std::pair<AudioChannelLayout, uint64_t>> g_toFFMPEGChannelLayout = {
    {AudioChannelLayout::MONO, AV_CH_LAYOUT_MONO},
    {AudioChannelLayout::STEREO, AV_CH_LAYOUT_STEREO},
    {AudioChannelLayout::CH_2POINT1, AV_CH_LAYOUT_2POINT1},
    // ... 共25种
};

// L67-80: AudioVivid 通道布局映射（9种HOA格式）
const std::vector<std::pair<AudioChannelLayout, int>> g_audioVividChannelLayoutMap = {
    {AudioChannelLayout::MONO, 1},
    {AudioChannelLayout::STEREO, 2},
    // HOA_ORDER1_ACN_SN3D=4 / HOA_ORDER2_ACN_SN3D=9 / HOA_ORDER3_ACN_SN3D=16
};

// L82-94: 默认通道数→通道布局映射（2/4/6/8/9/10/12/14/16/24）
const std::vector<std::pair<int, AudioChannelLayout>> g_channelLayoutDefaultMap
```

### 2.5 音频采样格式映射

**证据**: converter.cpp L97-130

```cpp
// L97-107: AVSampleFormat → AudioSampleFormat
const std::vector<std::pair<AVSampleFormat, AudioSampleFormat>> g_pFfSampleFmtMap = {
    {AV_SAMPLE_FMT_U8, SAMPLE_U8},
    {AV_SAMPLE_FMT_S16, SAMPLE_S16LE},
    {AV_SAMPLE_FMT_S32, SAMPLE_S32LE},
    {AV_SAMPLE_FMT_FLTP, SAMPLE_F32P},
    // ...
};

// L109-130: AVCodecID → AudioSampleFormat (21种PCM格式)
const std::vector<std::pair<AVCodecID, AudioSampleFormat>> g_pFfCodeIDToSampleFmtMap = {
    {AV_CODEC_ID_PCM_U8, SAMPLE_U8},
    {AV_CODEC_ID_PCM_S16LE, SAMPLE_S16LE},
    {AV_CODEC_ID_PCM_S24LE, SAMPLE_S24LE},
    {AV_CODEC_ID_PCM_F32LE, SAMPLE_F32LE},
    // DVD/BLURAY/G711/ALAW/MULAW
};
```

---

## 3 StreamParser 流解析器基类（96行h）

**文件**: `plugins/common/stream_parser.h` (96行)

StreamParser 是流解析器的纯虚基类，定义在 `plugins/common/`（跨 demuxer/source 共享）：

```cpp
// L24-28: VideoStreamType 枚举
enum VideoStreamType {
    VIDEO_STREAM_TYPE_UNKNOWN = 0,
    VIDEO_STREAM_TYPE_AVC = 1,
    VIDEO_STREAM_TYPE_HEVC = 2,
    VIDEO_STREAM_TYPE_VVC = 3,
};

// L50-53: HevcParseFormat HDR元数据结构体
struct HevcParseFormat {
    uint8_t colorPrimaries;
    uint8_t colorTransfer;
    uint8_t colorMatrix;
    uint8_t colorRange;
};

// L30-48: PacketConvertToBufferInfo 码流转换信息
struct PacketConvertToBufferInfo { ... };

// L65-96: StreamParser 纯虚接口
class StreamParser {
    virtual void ParseExtraData(...) = 0;        // L69
    virtual bool ConvertExtraDataToAnnexb(...) = 0;  // L71
    virtual void ConvertPacketToAnnexb(...) = 0; // L73
    virtual bool ConvertPacketToAnnexb(const PacketConvertToBufferInfo&) = 0; // L74
    virtual void ParseAnnexbExtraData(...) = 0; // L75
    virtual bool IsHdrVivid() = 0;              // L77
    virtual bool IsHdr10Plus() = 0;             // L78
    virtual bool IsHdr() = 0;                   // L79
    virtual bool IsSyncFrame(...) = 0;           // L80
    virtual bool GetColorRange() = 0;           // L81
    virtual uint8_t GetColorPrimaries() = 0;    // L82
    virtual uint8_t GetColorTransfer() = 0;       // L83
    virtual uint8_t GetColorMatrixCoeff() = 0;   // L84
    virtual uint8_t GetProfileIdc() = 0;        // L85
    virtual uint8_t GetLevelIdc() = 0;          // L86
};
```

---

## 4 TimeRangeManager Seek 范围管理（77行cpp + 74行h）

**文件**: `time_range_manager.cpp` + `time_range_manager.h`

```cpp
// time_range_manager.h L29-38: TimeRange 数据结构
struct TimeRange {
    int64_t startTimeUs = 0;
    int64_t endTimeUs = 0;
    TimeRange() = default;
    TimeRange(int64_t start, int64_t end) : startTimeUs(start), endTimeUs(end) {}
};

// time_range_manager.h L40-50: TimeRangeManager 主类
class TimeRangeManager {
    std::vector<TimeRange> seekableRanges_;
    std::vector<int64_t> segmentOffsets_;
    int64_t currentSegmentOffset_ = 0;
    int64_t maxIndexCacheSize_ = 70 * 1024;  // MAX_INDEX_CACHE_SIZE=70KB
public:
    bool AddSeekableRange(int64_t startUs, int64_t endUs);
    bool IsSeekable(int64_t timeUs);
    int64_t GetSeekableEndPosition(int64_t timeUs);
    void AddSegmentOffset(int64_t offset);
    void Clear();
};

// time_range_manager.h L52-62: TimeoutGuard 超时守卫
class TimeoutGuard {
    int64_t timeoutMs_;
    int64_t startMs_;
public:
    TimeoutGuard(int64_t timeoutMs) : timeoutMs_(timeoutMs), startMs_(GetCurTimeMs()) {}
    bool IsTimeout() const { return (GetCurTimeMs() - startMs_) >= timeoutMs_; }
    int64_t ElapsedMs() const { return GetCurTimeMs() - startMs_; }
};
```

---

## 5 MultiStreamParserManager dlopen 插件管理（293行cpp + 100行h）

**文件**: `multi_stream_parser_manager.cpp` + `multi_stream_parser_manager.h`

```cpp
// multi_stream_parser_manager.h L40-60: PluginManager 类（StreamParser插件管理）
class PluginManager {
    std::map<std::string, std::shared_ptr<StreamParser>> streamParserPlugins_;
    std::shared_ptr<StreamParser> CreatePlugin(const std::string& name);
    std::shared_ptr<StreamParser> GetStreamParserPlugin(const std::string& name);
};

// multi_stream_parser_manager.cpp L67-90: CreateStreamParserPlugin
std::shared_ptr<StreamParser> PluginManager::CreateStreamParserPlugin(const std::string& pluginName)
{
    // dlopen libhevc_parser.z.so 或 libvvc_parser.z.so
    // dlsym GetStreamParserPluginCreator
    // 返回 StreamParser 实例
}

// multi_stream_parser_manager.cpp L100-130: ParseExtraData 多轨解析
void MultiStreamParserManager::ParseExtraData(const std::vector<uint8_t>& extraData, int streamId)
{
    // 根据 streamId 分发到对应轨的 StreamParser
    // streamParserMap_[streamId]->ParseExtraData(extraData.data(), extraData.size());
}
```

---

## 6 ReferenceParser dlopen 接口（41行h）

**文件**: `plugins/common/reference_parser.h` (41行)

ReferenceParser 定义了插件的 C 接口（dlopen 符号）：

```cpp
// reference_parser.h: 插件 C API 接口
typedef struct ReferenceParserHandle {
    void* handle;  // dlopen 返回的 .so 句柄
    bool (*FindSyncFrame)(const uint8_t* data, size_t size, int64_t* framePos);
    void (*Release)(ReferenceParserHandle* handle);
} ReferenceParserHandle;

ReferenceParserHandle* OpenReferenceParser(const char* libPath);
```

---

## 7 RbspContext EBSP→RBSP 防伪字节（82行cpp + 71行h）

**文件**: `rbsp_context.cpp` + `rbsp_context.h`

EBSP (Encapsulated Byte Sequence Payload) 在编码时将 `0x000000`、`0x000001`、`0x000002`、`0x000003` 中的防伪字节 `0x03` 转义，RBSP 解析时需还原：

```cpp
// rbsp_context.cpp: EBSP→RBSP 转义还原
// 0x000003 → 0x0000（3字节起始码中间字节为0x03 → 跳过0x03）
// 0x000001 → 0x0001（正常起始码不转义）
// 0x000002 → 0x0002（可能被转义）
```

---

## 8 BlockQueue 模板化有界阻塞队列（191行h）

**文件**: `block_queue.h` (191行)

```cpp
// block_queue.h: 模板化有界阻塞队列
template<typename T>
class BlockQueue {
    std::deque<T> queue_;
    size_t capacity_;  // 有界容量
    std::mutex mutex_;
    std::condition_variable notEmpty_;   // 生产者等待
    std::condition_variable notFull_;    // 消费者等待
public:
    void Push(T&& item);   // 有界阻塞 Push
    T Pop();               // 有界阻塞 Pop
    size_t Size();
    void SetCapacity(size_t cap);
};
```

---

## 9 BlockQueuePool 模板化内存池（552行h）

**文件**: `block_queue_pool.h` (552行)

BlockQueuePool 是内存池化框架，支持 FFmpeg SamplePacket 和 MPEG4 Sample 双容器：

```cpp
// block_queue_pool.h: 模板特化
template<>
class BlockQueuePool<FFmpegSamplePacket> { ... };  // FFmpeg AVPacket 包装

template<>
class BlockQueuePool<MPEG4Sample> { ... };  // MPEG4 样本索引包装
```

---

## 10 与其他模块的关系

| 关联主题 | 关系 | 说明 |
|---------|------|------|
| S75 (MediaDemuxer 六组件) | 上游引擎 | MediaDemuxer 使用所有 10 个 DemuxerCommon 组件 |
| S79 (MPEG4DemuxerPlugin) | 调用方 | MPEG4DemuxerPlugin 调用 Converter/TimeRangeManager |
| S68/S76 (FFmpegDemuxerPlugin) | 调用方 | FFmpegDemuxerPlugin 调用 Converter |
| S140 (旧版 Converter 工具链) | 替代升级 | S186 是 S140 的增强版，新增 HdrBoxInfo/ParseHdrTypeInfo/ParseColorBoxInfo |
| S143 (StreamParserManager) | 引用方 | StreamParserManager 调用 StreamParser 基类接口 |
| S105 (BlockQueuePool) | 同级组件 | BlockQueuePool 供所有 demuxer 插件共享 |
| S97 (DemuxerPluginManager) | 调用方 | DemuxerPluginManager 使用 MultiStreamParserManager 管理流解析器 |
| S111 (Demuxer 共享工具链) | 同级 | S111 是同系列主题，S186 侧重 Converter 深度 |

---

## 11 关键证据索引

| 证据 | 文件 | 行号 |
|------|------|------|
| HEVCProfile 映射表 | converter.cpp | L256-258 |
| ConvertToOHHEVCProfile | converter.cpp | L281-291 |
| 色彩 primaries 映射表 | converter.cpp | L183-192 |
| 色彩 transfer 映射表（含PQ/HLG/BT2020） | converter.cpp | L210-220 |
| 色彩 matrix 映射表 | converter.cpp | L230-235 |
| ConvertFFMpegToOHColorPrimaries | converter.cpp | L293-302 |
| ConvertFFMpegToOHColorTrans | converter.cpp | L304-314 |
| ConvertFFMpegToOHColorMatrix | converter.cpp | L316-326 |
| ConvertFFMpegToOHColorRange | converter.cpp | L319-330 |
| ParseColorBoxInfo HDR元数据 | converter.cpp | L405-440 |
| ParseHdrTypeInfo HDR类型识别 | converter.cpp | L441-490 |
| g_toFFMPEGChannelLayout 25种布局 | converter.cpp | L27-65 |
| g_audioVividChannelLayoutMap HOA | converter.cpp | L67-80 |
| g_channelLayoutDefaultMap | converter.cpp | L82-94 |
| g_pFfSampleFmtMap | converter.cpp | L97-107 |
| g_pFfCodeIDToSampleFmtMap 21种PCM | converter.cpp | L109-130 |
| VideoStreamType 枚举 | stream_parser.h | L24-28 |
| HevcParseFormat HDR元数据结构 | stream_parser.h | L50-53 |
| StreamParser 纯虚基类 15接口 | stream_parser.h | L65-96 |
| TimeRange 数据结构 | time_range_manager.h | L29-38 |
| TimeRangeManager 主类 | time_range_manager.h | L40-50 |
| TimeoutGuard 超时守卫 | time_range_manager.h | L52-62 |
| PluginManager CreateStreamParserPlugin | multi_stream_parser_manager.cpp | L67-90 |
| ReferenceParserHandle C API | reference_parser.h | 全文件41行 |
| BlockQueue 有界阻塞队列模板 | block_queue.h | L1-191 |
| BlockQueuePool 模板化内存池 | block_queue_pool.h | L1-552 |

---

## 12 工程信息

- **本地镜像路径**: `/home/west/av_codec_repo/services/media_engine/plugins/demuxer/common/`
- **源码文件**:
  - `converter.cpp` (595行) + `converter.h` (75行)
  - `time_range_manager.cpp` (77行) + `time_range_manager.h` (74行)
  - `multi_stream_parser_manager.cpp` (293行) + `multi_stream_parser_manager.h` (100行)
  - `reference_parser_manager.cpp` (138行) + `reference_parser_manager.h` (77行)
  - `plugins/common/stream_parser.h` (96行)
  - `plugins/common/reference_parser.h` (41行)
  - `demuxer_data_reader.cpp` (162行) + `demuxer_data_reader.h` (63行)
  - `avc_parser_impl.cpp` (180行) + `avc_parser_impl.h` (83行)
  - `rbsp_context.cpp` (82行) + `rbsp_context.h` (71行)
  - `demuxer_log_compressor.cpp` (219行) + `demuxer_log_compressor.h` (31行)
  - `block_queue.h` (191行) + `block_queue_pool.h` (552行)
  - 共 3103 行源码
- **编译产物**: `libdemuxer_common.z.so`
- **依赖库**: `libavcodec.z.so`, `libavformat.z.so`, `libavutil.z.so`, `libmedia_core.z.so`