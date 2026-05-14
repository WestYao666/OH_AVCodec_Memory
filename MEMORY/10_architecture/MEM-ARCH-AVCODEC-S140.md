---
type: architecture
id: MEM-ARCH-AVCODEC-S140
status: pending_approval
created_at: "2026-05-15T02:49:15+08:00"
updated_at: "2026-05-15T02:49:15+08:00"
created_by: builder
topic: Demuxer Common 工具链——Converter 色域转换 / TimeRangeManager Seek范围 / MultiStreamParserManager 多轨 / Converter 色域转换映射表
scope: [AVCodec, MediaEngine, Demuxer, Common, Converter, TimeRangeManager, MultiStreamParserManager, ColorSpace, ChannelLayout, HEVC, HDR, FFmpeg, AVColorRange, AudioChannelLayout, Seek, TimeRange, NALU]
created_at: "2026-05-15T02:49:15+08:00"
summary: Demuxer Common 工具链——Converter 595行cpp（AVColorRange/HEVCProfile/ChannelLayout七类转换）+TimeRangeManager Seek范围管理（77行）+MultiStreamParserManager多轨Parser管理（293行）+HdrBoxInfo/ParseColorBoxInfo/ParseHdrTypeInfo HDR元数据解析，与S8/S50/S105/S125关联
source_repo: /home/west/av_codec_repo
source_root: services/media_engine/plugins/demuxer/common
evidence_version: local_mirror
---

## 一、架构总览

Demuxer Common 工具链位于 `services/media_engine/plugins/demuxer/common/` 目录，包含 Demuxer 级别的通用工具类，供所有 Demuxer 插件（FFmpegDemuxerPlugin / MPEG4DemuxerPlugin）共享使用。

**定位**：Demuxer 插件的公共基础设施，类似于 FFmpeg Adapter Common（S130）为编解码器提供通用工具，Demuxer Common 为解封装器提供通用工具。

## 二、文件清单与行号级证据

| 文件 | 行数 | 说明 |
|------|------|------|
| `converter.cpp` | 595 | Converter 色域/Profile/ChannelLayout 转换工具 |
| `converter.h` | 75 | Converter 类定义 + HdrBoxInfo 结构体 |
| `time_range_manager.cpp` | 77 | TimeRangeManager Seek 范围管理器 |
| `time_range_manager.h` | ~70 | TimeRangeManager 类定义 + TimeRange/TimeoutGuard 结构体 |
| `multi_stream_parser_manager.cpp` | 293 | MultiStreamParserManager 多轨 Parser 管理器 |
| `multi_stream_parser_manager.h` | ~100 | MultiStreamParserManager 类定义 |
| `demuxer_data_reader.cpp` | 162 | Demuxer 数据读取器 |
| `demuxer_data_reader.h` | ~100 | Demuxer 数据读取器类定义 |
| `reference_parser_manager.cpp` | 138 | ReferenceParser 管理器（dlopen 插件） |
| `reference_parser_manager.h` | ~100 | ReferenceParserManager 类定义 |
| `demuxer_log_compressor.cpp` | 219 | 日志压缩器 |
| `demuxer_log_compressor.h` | ~80 | 日志压缩器类定义 |
| `avc_parser_impl.cpp` | 180 | AVC NALU 解析器实现 |
| `avc_parser_impl.h` | ~80 | AVC 解析器接口 |
| `rbsp_context.cpp` | 82 | RBSP 上下文 |
| `rbsp_context.h` | ~80 | RBSP 上下文类定义 |
| `block_queue.h` | ~200 | 无锁阻塞队列 |
| `block_queue_pool.h` | ~100 | 队列池 |

## 三、Converter 核心设计

### 3.1 七类转换函数（converter.cpp）

| 函数 | 行号 | 说明 |
|------|------|------|
| `ConvertToOHHEVCLevel` | 270 | FFmpeg HEVC Level → OH HEVCLevel |
| `ConvertToOHHEVCProfile` | 281 | FFmpeg HEVC Profile → OH HEVCProfile |
| `ConvertFFMpegToOHColorRange` | 319 | FFmpeg AVColorRange → OH ColorRange |
| `ConvertFFToOHAudioChannelLayoutV2` | 373 | FFmpeg ChannelLayout → OH AudioChannelLayout |
| `ConvertAudioVividToOHAudioChannelLayout` | 393 | AudioVivid ChannelLayout → OH |
| `GetDefaultChannelLayout` | 361 | 默认通道布局（channels → layout） |
| `ParseColorBoxInfo` | 405 | 解析 ColorBox 信息（HevcParseFormat → Meta） |
| `ParseHdrTypeInfo` | 441 | 解析 HDR 类型信息（HdrBoxInfo → Meta） |

### 3.2 HDRBoxInfo 结构体（converter.h:41-45）

```cpp
// converter.h:41-45 - HDR 盒子信息
struct HdrBoxInfo {
    bool haveHdrDoblyVisionBox = false;  // Dolby Vision 盒子
    bool haveHdrVividBox = false;        // HDR Vivid 盒子
    bool isHdr = false;                  // 是否有静态/动态元数据
};

// converter.cpp:405 - ColorBox 解析
void Converter::ParseColorBoxInfo(HevcParseFormat parse, Meta &format)
{
    // HevcParseFormat → color_primaries / transfer / matrix
    // 写入 format[Tag::VIDEO_COLOR_PRIMARIES] 等标签
}

// converter.cpp:441 - HDR 类型解析
void Converter::ParseHdrTypeInfo(HdrBoxInfo hdrBoxInfo, Meta &format, HeveParseFormat parse)
{
    // hdrBoxInfo.haveHdrDoblyVisionBox → Dolby Vision
    // hdrBoxInfo.haveHdrVividBox → HDR Vivid
    // hdrBoxInfo.isHdr → 静态/动态元数据标记
}
```

### 3.3 七类转换映射表（converter.cpp:37-262）

```cpp
// converter.cpp:37-66 - AudioChannelLayout 映射表（18种）
const std::vector<std::pair<AudioChannelLayout, uint64_t>> g_toFFMPEGChannelLayout = {
    {AudioChannelLayout::MONO, AV_CH_LAYOUT_MONO},
    {AudioChannelLayout::STEREO, AV_CH_LAYOUT_STEREO},
    {AudioChannelLayout::SURROUND, AV_CH_LAYOUT_2_1},
    // ... 共18种
};

// converter.cpp:68-82 - AudioVivid 通道布局映射
const std::vector<std::pair<AudioChannelLayout, int>> g_audioVividChannelLayoutMap = {
    // AudioVivid 特有映射
};

// converter.cpp:83-100 - 默认通道布局
const std::vector<std::pair<int, AudioChannelLayout>> g_channelLayoutDefaultMap = {
    {1, AudioChannelLayout::MONO},
    {2, AudioChannelLayout::STEREO},
    // ...
};

// converter.cpp:241-260 - ColorRange 映射
const std::vector<std::pair<AVColorRange, int>> g_pFfColorRangeMap = {
    {AVCOL_RANGE_UNSPECIFIED, 0},
    {AVCOL_RANGE_MPEG, 1},   // limited range
    {AVCOL_RANGE_JPEG, 2},   // full range
};

// converter.cpp:256-262 - HEVC Profile/Level 映射
const std::vector<std::pair<int, HEVCProfile>> g_pFfHEVCProfileMap = {
    {FF_PROFILE_HEVC_MAIN, HEVCProfile::MAIN},
    {FF_PROFILE_HEVC_MAIN_10, HEVCProfile::MAIN_10},
};
const std::vector<std::pair<int, HEVCLevel>> g_pFfHEVCLevelMap = {
    {FF_LEVEL_HEVC_1, HEVCLevel::HEVC_LEVEL_1},
    // ...
};
```

## 四、TimeRangeManager Seek 范围管理

### 4.1 TimeRange 结构体（time_range_manager.h:29-33）

```cpp
// time_range_manager.h:29-38 - 时间范围
struct TimeRange {
    int64_t start_ts {AV_NOPTS_VALUE};  // 起始时间戳
    int64_t end_ts {AV_NOPTS_VALUE};    // 结束时间戳
    bool operator < (const TimeRange& other) const { return start_ts < other.start_ts; }
};
```

### 4.2 TimeRangeManager 类（time_range_manager.h:40-51）

```cpp
// time_range_manager.h:40-51 - 时间范围管理器
class TimeRangeManager {
public:
    bool IsInTimeRanges(const int64_t targetTs, TimeRange &timeRange);  // 检查时间戳是否在范围内
    void AddTimeRange(const TimeRange &range);                         // 添加时间范围
    void ReduceRanges();                                               // 缩减范围（合并相邻范围）
    static constexpr int32_t MAX_INDEX_CACHE_SIZE = ...;
    int32_t maxEntries_ = MAX_INDEX_CACHE_SIZE / sizeof(TimeRange);   // 最大条目数
};

// time_range_manager.cpp - 关键实现
bool TimeRangeManager::IsInTimeRanges(int64_t targetTs, TimeRange &timeRange)
{
    // 二分查找 targetTs 所属的 TimeRange
    // 用于 Seek 时判断目标时间戳是否在有效范围内
}

void TimeRangeManager::AddTimeRange(const TimeRange &range)
{
    // 添加新的时间范围（去重+合并相邻）
    // ReduceRanges() 合并重叠/相邻范围
}
```

### 4.3 TimeoutGuard 超时守卫（time_range_manager.h:52-71）

```cpp
// time_range_manager.h:52-71 - 超时守卫结构
class TimeoutGuard {
    explicit TimeoutGuard(uint32_t timeoutMs);
    bool IsTimeout() const;  // 是否超时
    // 内部使用 high_resolution_clock
};

// time_range_manager.cpp - 用法
TimeoutGuard guard(timeoutMs);
while (!guard.IsTimeout()) {
    // 执行操作，有超时保护
}
```

## 五、MultiStreamParserManager 多轨 Parser 管理

```cpp
// multi_stream_parser_manager.h - 多轨 Parser 管理器
class MultiStreamParserManager {
    std::map<int32_t, std::shared_ptr<BaseStreamParser>> streamParserMap_;  // streamId → Parser
    std::shared_ptr<BaseStreamParser> GetStreamParser(int32_t streamId);
    void AddStreamParser(int32_t streamId, std::shared_ptr<BaseStreamParser> parser);
    void RemoveStreamParser(int32_t streamId);
    // 多轨并行解析（如 DASH 多轨道同时下载）
};

// multi_stream_parser_manager.cpp:293行
// 管理多个流的 NALU Parser 实例，支持:
// - 视频轨 + 音频轨 + 字幕轨并行解析
// - 动态添加/删除轨道
// - Parser 实例池化（避免重复创建）
```

## 六、Demuxer 数据读取器（demuxer_data_reader.cpp:162行）

```cpp
// demuxer_data_reader.h - Demuxer 数据读取器接口
class DemuxerDataReader {
    virtual Status ReadBuf(uint8_t* buf, size_t len, size_t& readLen);
    virtual Status ReadAt(int64_t offset, size_t size, uint8_t* buffer, size_t& readLen);
    virtual int64_t GetStreamSize();
    virtual bool IsSeekable();
};

// demuxer_data_reader.cpp:162行实现
// 封装底层数据源（FileSource/DataStreamSource/HTTP）的读取接口
// 提供统一的 Read/ReadAt/GetSize 接口
// 支持 Seek 能力检测（IsSeekable）
```

## 七、与相关 S-series 记忆的关联

| 关联记忆 | 关系 | 说明 |
|---------|------|------|
| S8（FFmpegAdapter Common） | 同级 | S130 FFmpegAdapter Common（Resample/ColorSpace/ChannelLayout工具），S140 Demuxer Common（色域转换/Seek范围/多轨Parser） |
| S50（FFmpegDemuxerPlugin） | 上游消费者 | FFmpegDemuxerPlugin 使用 Converter 转换 HEVC Profile/Level/ColorRange |
| S105（HEVC 解码器） | 下游消费者 | HEVC 解码器接收 Converter 转换后的 Meta 信息 |
| S125（FFmpegDecoder） | 下游消费者 | FFmpegDecoder 使用 FFmpegAdapter Common 的 ChannelLayout 映射，S140 Demuxer Common 专用于解封装 |
| S96（PTS索引转换） | 并列 | TimeRangeManager Seek 范围管理 与 PTS 索引转换 并列同为 Demuxer 工具组件 |

---

_builder-agent: S140 draft generated 2026-05-15T02:49:15+08:00, pending approval_