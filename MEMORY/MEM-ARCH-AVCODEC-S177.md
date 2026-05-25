# MEM-ARCH-AVCODEC-S177.md
# Demuxer Common 共享解析工具链

**主题**: Demuxer Common 共享解析工具链  
**Scope**: MultiStreamParserManager / StreamParser / Converter / TimeRangeManager / ReferenceParserManager 五组件  
**关联场景**: 新需求开发 / 问题定位  
**状态**: draft  
**生成时间**: 2026-05-26  
**来源**: 本地镜像 /home/west/av_codec_repo  

---

## 1. 概述

Demuxer Common 是 MediaEngine 解封装层的共享工具链，包含五个核心组件，为 FFmpegDemuxerPlugin 和 MPEG4DemuxerPlugin 提供统一的解析、色域转换、Seek 范围管理和 dlopen 插件加载能力。总计约 1103 行核心源码。

---

## 2. 五组件架构

```
plugins/demuxer/common/
├── multi_stream_parser_manager.cpp  (293行)
├── multi_stream_parser_manager.h   (100行)
├── stream_parser.h                 (96行)      ← 基类
├── converter.cpp                  (595行)
├── converter.h                    (75行)
├── time_range_manager.cpp         (77行)
├── time_range_manager.h           (~70行)
├── reference_parser.h             (77行)
├── reference_parser_manager.cpp   (138行)
├── reference_parser_manager.h
├── demuxer_data_reader.cpp        (162行)
├── demuxer_data_reader.h          (63行)
├── avc_parser_impl.cpp
├── avc_parser_impl.h
├── block_queue.h
├── block_queue_pool.h
├── rbsp_context.cpp
├── rbsp_context.h
└── demuxer_log_compressor.cpp
```

---

## 3. MultiStreamParserManager — 多轨流解析管理器

### 3.1 职责
管理 HEVC/VVC/AVC 三种视频码流的流式解析器生命周期，支持 dlopen 热加载外部 .so 插件。

### 3.2 dlopen 插件体系

**源码**: `multi_stream_parser_manager.cpp:25-26`  
```cpp
const std::string HEVC_LIB_PATH = "libav_codec_hevc_parser.z.so";
const std::string VVC_LIB_PATH = "libav_codec_vvc_parser.z.so";
```

**dlopen 加载**: `multi_stream_parser_manager.cpp:40-70` 范围内，handlerMap_ / createFuncMap_ / destroyFuncMap_ 三静态 map 管理插件句柄。

**工厂函数**: `multi_stream_parser_manager.cpp:52-67`  
```cpp
StreamParser *CreateH264StreamParser() {
    AvcParserImpl *avcParser = new AvcParserImpl();
    return avcParser;
}
void DestroyH264StreamParser(StreamParser* avcParser) {
    delete avcParser;
    avcParser = nullptr;
}
```

**Create()**: `multi_stream_parser_manager.cpp:88` 附近，`Status MultiStreamParserManager::Create(uint32_t trackId, VideoStreamType videoStreamType)`

### 3.3 VideoStreamType 枚举

定义在 stream_parser.h:96 行，包含 HEVC/VVC/AVC 等类型，用于 createFuncMap_ 路由到具体解析器。

### 3.4 ~MultiStreamParserManager 析构

**源码**: `multi_stream_parser_manager.cpp:44-59`  
遍历 streamMap_，对每个 parser 调用 destroyFuncMap_[videoStreamType](streamParser) 释放 dlopen 句柄，防止内存泄漏。

---

## 4. StreamParser — 流解析器基类

### 4.1 基类接口

**源码**: `stream_parser.h:96` 行文件，定义纯虚函数接口：
- ParseVideoStream() / ParseAudioStream() 解析入口
- 派生类：AvcParserImpl（H264）/ HEVCParser（dlopen）/ VVCParser（dlopen）

### 4.2 AvcParserImpl — AVC 内置解析器

**源码**: `avc_parser_impl.cpp` + `avc_parser_impl.h`  
实现内置 H264 NALU 解析，无需 dlopen，直接编译进 demuxer_common。

---

## 5. Converter — 色域转换器

### 5.1 功能

**源码**: `converter.h:75` 行，`converter.cpp:595` 行  
提供 FFmpeg → OHOS 颜色系统转换：

| 转换函数 | 功能 |
|---------|------|
| `ConvertFFMpegToOHColorPrimaries()` | 色彩基色 |
| `ConvertFFMpegToOHColorTrans()` | 转移特性 |
| `ConvertFFMpegToOHColorMatrix()` | 色彩矩阵 |
| `ConvertFFMpegToOHColorRange()` | 色域范围 |
| `ConvertFFMpegToOHChromaLocation()` | 色度位置 |

### 5.2 HEVC Profile/Level 转换

**源码**: `converter.h:46-47`  
```cpp
static HEVCProfile ConvertToOHHEVCProfile(int ffHEVCProfile);
static HEVCLevel ConvertToOHHEVCLevel(int ffHEVCLevel);
```

### 5.3 HdrBoxInfo 结构体

**源码**: `converter.h:26-30`  
```cpp
struct HdrBoxInfo {
    bool haveHdrDoblyVisionBox = false;
    bool haveHdrVividBox = false;
    bool isHdr = false; // have static metadata or dynamic metadata
};
```

### 5.4 ParseColorBoxInfo / ParseHdrTypeInfo

**源码**: `converter.h:52-53`  
```cpp
static void ParseColorBoxInfo(HevcParseFormat parse, Meta &format);
static void ParseHdrTypeInfo(HdrBoxInfo hdrBoxInfo, Meta &format, HevcParseFormat parse);
```

### 5.5 音频格式转换

**源码**: `converter.h:48-50`  
```cpp
static AudioSampleFormat ConvertFFMpegAVCodecIdToOHAudioFormat(AVCodecID codecId);
static AudioSampleFormat ConvertFFMpegToOHAudioFormat(AVSampleFormat ffSampleFormat);
static AudioChannelLayout ConvertFFToOHAudioChannelLayoutV2(uint64_t ffChannelLayout, int channels);
```

### 5.6 编码转换工具

**源码**: `converter.h:55-59`  
```cpp
static std::string ToLower(const std::string& str);
static bool IsUTF8(const std::string &data);
static std::string ConvertGBKToUTF8(const std::string &strGbk);
static bool IsGBK(const char* data);
```

---

## 6. TimeRangeManager — Seek 范围管理器

### 6.1 作用

管理 Demuxer Seek 操作的有效时间范围，防止跨无效区间 Seek。

### 6.2 MAX_INDEX_CACHE_SIZE

**源码**: `time_range_manager.h:26`  
```cpp
#define MAX_INDEX_CACHE_SIZE (70 * 1024) // 70KB
```

### 6.3 TimeRange 结构体

**源码**: `time_range_manager.h:29-33`  
```cpp
struct TimeRange {
    int64_t start_ts {AV_NOPTS_VALUE};
    int64_t end_ts {AV_NOPTS_VALUE};
    bool operator < (const TimeRange& other) const {
        return start_ts < other.start_ts ||
            (start_ts == other.start_ts && end_ts < other.end_ts);
    }
};
```

### 6.4 核心 API

**源码**: `time_range_manager.h:38-42`  
```cpp
bool IsInTimeRanges(const int64_t targetTs, TimeRange &timeRange);
void AddTimeRange(const TimeRange &range);
void ReduceRanges();
```

### 6.5 TimeoutGuard — 超时守卫

**源码**: `time_range_manager.h:56-70`  
RAII 风格的超时检测类，使用 `std::chrono::high_resolution_clock` 计算已用时间，用于 demuxer 读取操作的超时判断。

---

## 7. ReferenceParserManager — 参考帧解析器 dlopen 管理

### 7.1 作用

dlopen 加载 .so 插件，用于解析 I 帧位置（GOP 索引），辅助快速 Seek。

### 7.2 接口

**源码**: `reference_parser.h:77` 行文件，定义 `CreateReferenceParser()` / `DestroyReferenceParser()` 纯虚工厂接口。

### 7.3 ReferenceParserManager 实现

**源码**: `reference_parser_manager.cpp:138` 行  
持有 dlopen 句柄映射表，管理插件生命周期，与 MultiStreamParserManager 的 dlopen 模式一致。

---

## 8. DemuxerDataReader — 数据读取器

### 8.1 职责

封装 DataSource，提供带重试的字节流读取能力。

### 8.2 重试常量

**源码**: `demuxer_data_reader.cpp:19-21`  
```cpp
constexpr uint8_t BYTE_LENGTH = 8;
constexpr uint8_t READ_RETRY_TIMES = 10;
constexpr uint32_t READ_RETRY_SLEEP_TIME_US = 5000;
```

### 8.3 SetDataReader

**源码**: `demuxer_data_reader.cpp:26-30`  
`Status DemuxerDataReader::SetDataReader(const std::shared_ptr<DataSource>& source)`

---

## 9. BlockQueuePool — 内存池

### 9.1 SamplePacket 特化

**源码**: `block_queue_pool.h:40-60`  
为 FFmpeg::SamplePacket 特化 `BlockTraits`，使用 `avpacket_wrapper.h` 的 AVPacketWrapperPtr 智能指针管理 FFmpeg 数据包。

### 9.2 MPEG4::Sample / MPEG4Sample

**源码**: `block_queue_pool.h:50-75`  
MPEG4 命名空间下的 Sample 结构体，包含 pts/dts/duration/flag/size/data；MPEG4Sample 为带队列索引的包装器。

### 9.3 BlockTraits 模板特化

**源码**: `block_queue_pool.h:64-80`  
`GetDataSize()` 遍历 pkts 向量累加每个 AVPacketWrapper 的 size；`UpdateMaxPts()` 更新最大 PTS。

---

## 10. RBSP / AVC Parser — NALU 解析

### 10.1 rbsp_context — EBSP→RBSP 防伪字节

**源码**: `rbsp_context.h/cpp (71/82行)`  
EBSP (Encapsulated Byte Sequence Payload) → RBSP 转义去除 `0x000003`。

### 10.2 avc_parser_impl — AVC NALU 分析

**源码**: `avc_parser_impl.h/cpp (156/330行)`  
解析 SPS/PPS/VPS/IDR/non-IDR NAL 单元，提取 Sequence Parameter Set 和 Picture Parameter Set。

---

## 11. 与其他 S 系列记忆的关联

| 关联记忆 | 关系 |
|---------|------|
| S105 BlockQueuePool + demuxer公共组件 | S105 与 S177 有重叠，S177 聚焦 common 子目录，S105 覆盖 block_queue_pool + avc_parser + converter |
| S68/S76 FFmpegDemuxerPlugin | S177 是 FFmpegDemuxerPlugin 的底层依赖，Converter 提供 FFmpeg→OHOS 类型转换 |
| S79 MPEG4DemuxerPlugin | S177 是 MPEG4DemuxerPlugin 的底层依赖，MultiStreamParserManager 管理 MPEG4 多轨解析 |
| S97 DemuxerPluginManager | S177 工具链被 DemuxerPluginManager 调用，DemuxerPluginManager.CreateStreamDemuxer → MultiStreamParserManager.Create |
| S101 StreamDemuxer | StreamDemuxer 使用 DemuxerDataReader 读取数据，使用 TimeRangeManager 管理 Seek 范围 |
| S102 SampleQueueController | BlockQueuePool 为 SampleQueue 提供内存池，SamplePacket/MPEG4Sample 双容器 |
| S111 Demuxer共享解析工具链 | S111 与 S177 实质相同，S177 基于本地镜像行号增强，S111 为早期版本 |
| S140 Demuxer Common工具链 | S140 与 S177 实质相同，S177 基于本地镜像行号增强，S140 为早期版本 |

---

## 12. Evidence 汇总

| # | 证据 | 文件:行号 |
|---|------|----------|
| 1 | HEVC/VVC dlopen 库路径常量 | multi_stream_parser_manager.cpp:25-26 |
| 2 | dlopen 三静态 map（handler/create/destroy） | multi_stream_parser_manager.cpp:40-70 |
| 3 | CreateH264StreamParser 工厂函数 | multi_stream_parser_manager.cpp:52-67 |
| 4 | ~MultiStreamParserManager 析构释放插件 | multi_stream_parser_manager.cpp:44-59 |
| 5 | Create(uint32_t, VideoStreamType) 入口 | multi_stream_parser_manager.cpp:88 |
| 6 | StreamParser 基类 96 行文件定义 | stream_parser.h:96 |
| 7 | Converter 色域转换五函数 | converter.h:46-55 |
| 8 | HdrBoxInfo 三字段 HDR 元数据结构 | converter.h:26-30 |
| 9 | ConvertFFMpegToOHColorPrimaries 实现 | converter.cpp:全局 |
| 10 | AudioSampleFormat 音频格式转换 | converter.h:48-50 |
| 11 | MAX_INDEX_CACHE_SIZE = 70KB | time_range_manager.h:26 |
| 12 | TimeRange 结构体（start_ts/end_ts） | time_range_manager.h:29-33 |
| 13 | IsInTimeRanges/AddTimeRange/ReduceRanges API | time_range_manager.h:38-42 |
| 14 | TimeoutGuard chrono 高精度计时 | time_range_manager.h:56-70 |
| 15 | READ_RETRY_TIMES=10 / SLEEP_TIME=5000μs | demuxer_data_reader.cpp:19-21 |
| 16 | SetDataReader 入口 | demuxer_data_reader.cpp:26-30 |
| 17 | BlockTraits<SamplePacket> 特化 | block_queue_pool.h:40-80 |
| 18 | MPEG4::Sample pts/dts/flag 结构体 | block_queue_pool.h:50-68 |
| 19 | ReferenceParser dlopen 接口 | reference_parser.h:77 |
| 20 | ReferenceParserManager dlopen 管理 | reference_parser_manager.cpp:138 |