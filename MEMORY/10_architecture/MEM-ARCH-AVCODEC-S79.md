# MEM-ARCH-AVCODEC-S79: MPEG4DemuxerPlugin 原生 MP4/MOV 解封装插件

> **ID**: MEM-ARCH-AVCODEC-S79
> **Title**: MPEG4DemuxerPlugin 原生 MP4/MOV 解封装插件——MPEG4AtomParser 五级原子层级与 FFmpegDemuxerPlugin 双轨并行
> **Type**: architecture
> **Scope**: AVCodec, Demuxer, MPEG4, MP4, MOV, Container, BoxParser, DemuxerPlugin, AtomParser, Track
> **Status**: draft
> **Created**: 2026-05-03T11:50:00+08:00
> **Tags**: Demuxer, MPEG4, MP4, MOV, BoxParser, Atom, DemuxerPlugin, Track, SampleTable, Sniff

---

## 核心架构描述（中文）

MPEG4DemuxerPlugin 是 OpenHarmony AVCodec 的原生 MP4/MOV 容器解封装插件，封装自研 MPEG4AtomParser 实现完整的 Box 层级解析，支持 AVC/HEVC/VVC 视频轨、音频轨、字幕轨的 Sample 提取。与 FFmpegDemuxerPlugin（S68/S76）构成双轨并行：原生插件优先（rank=100），FFmpeg 兜底（rank=50）。

### 架构位置

```
FilterPipeline
  └─ DemuxerFilter
       └─ MediaDemuxer
            └─ DemuxerPluginManager
                 ├─ MPEG4DemuxerPlugin (native, rank=100) ← 本记忆
                 └─ FFmpegDemuxerPlugin (FFmpeg, rank=50)  ← S68/S76
```

**相关现有记忆**：
- S41（DemuxerFilter）：Filter 层封装
- S58（MPEG4BoxParser）：Box 解析引擎（五级深度），本插件使用该引擎
- S68/S76（FFmpegDemuxerPlugin）：FFmpeg libavformat 封装，支持 25+ 容器格式
- S69（MediaDemuxer）：核心解封装引擎，含 SampleQueue 缓冲

**本记忆（S79）聚焦**：MPEG4DemuxerPlugin 原生插件的实现架构、与 FFmpegDemuxerPlugin 的并行机制、MPEG4AtomParser 的调用方式

---

## 源码位置

| 组件 | 路径 |
|------|------|
| 插件实现 | `services/media_engine/plugins/demuxer/mpeg4_demuxer/mpeg4_demuxer_plugin.cpp` (1625行) |
| 插件头文件 | `services/media_engine/plugins/demuxer/mpeg4_demuxer/mpeg4_demuxer_plugin.h` |
| Box 解析引擎 | `services/media_engine/plugins/demuxer/mpeg4_demuxer/mpeg4_box_parser.cpp` (4396行，见 S58) |
| Sample 辅助 | `services/media_engine/plugins/demuxer/mpeg4_demuxer/mpeg4_sample_helper.cpp` |
| 音频解析 | `services/media_engine/plugins/demuxer/mpeg4_demuxer/mpeg4_audio_parser.cpp` |
| 参考信息解析 | `services/media_engine/plugins/demuxer/mpeg4_demuxer/mpeg4_reference_parser.cpp` |

---

## MPEG4DemuxerPlugin 类架构

### 继承关系

```cpp
namespace OHOS {
namespace Media {
namespace Plugins {
namespace MPEG4 {

class MPEG4DemuxerPlugin : public Plugins::DemuxerPlugin {
    // DemuxerPlugin 是 PluginBase 子类，定义 ParseHead / ReadSample / SeekTo 等接口
};
} // namespace MPEG4
} // namespace Media
} // namespace OHOS
```

### 核心成员

| 成员 | 类型 | 说明 |
|------|------|------|
| `parser_` | `std::shared_ptr<MPEG4AtomParser>` | Box 解析引擎（见 S58） |
| `tracks_` | `std::vector<std::shared_ptr<MPEG4AtomParser::Track>>` | Track 链表 |
| `firstFrameMap_` | `std::map<uint32_t, std::shared_ptr<AVBuffer>>` | 首帧缓存 |
| `seekable_` | `bool` | 是否支持 Seek |
| `dataSource_` | `std::shared_ptr<DataSource>` | 数据源抽象 |

---

## 双轨并行机制

### Rank 优先级

| 插件 | Rank | 适用格式 | 优先级 |
|------|------|---------|--------|
| MPEG4DemuxerPlugin | 100（最高） | MP4 / MOV / M4A / 3GP | 第一优先 |
| FFmpegDemuxerPlugin | 50 | 所有 FFmpeg 支持格式（FLV/MKV/MPEGTS 等） | 降级兜底 |

### Sniff 探测流程

```cpp
// mpeg4_demuxer_plugin.cpp:1575-1610
int Sniff(const std::string& pluginName, std::shared_ptr<DataSource> source)
{
    // 读取前 2048 字节（SNIFF_DATA_SIZE）
    // 调用 MPEG4AtomParser 尝试解析 ftyp / moov / moof 等原子
    // 返回置信度（0-100），>50 分则判定为 MPEG4 格式
    // 由 TypeFinder 遍历所有 DemuxerPlugin 执行 Sniff()
}
```

### 解析入口

```cpp
// mpeg4_demuxer_plugin.cpp:199-213
Status MPEG4DemuxerPlugin::SetDataSource(const std::shared_ptr<DataSource>& source)
{
    auto parser = std::make_shared<MPEG4AtomParser>();
    Status ret = parser->MPEG4ParseHeader(source, seekable_);  // 解析 moov box
    // 建立 Track 链表（CodecParams + MPEG4SampleHelper + displayMatrix）
}
```

---

## 关键数据结构：Track 链表

每个 Track 代表一个媒体流（视频/音频/字幕），Track 结构由 MPEG4AtomParser 构建：

```cpp
// MPEG4AtomParser::Track 包含：
struct Track {
    int32_t trackId_;              // 轨道 ID
    CodecParams codecParams_;      // 编解码参数（CodecSpecificData）
    std::shared_ptr<MPEG4SampleHelper> sampleHelper_; // Sample 表辅助
    std::vector<uint8_t> displayMatrix_; // 旋转/翻转矩阵（8类变换）
    int64_t duration_;            // 时长（movie timescale）
    int32_t width_;                // 视频宽度
    int32_t height_;              // 视频高度
    int32_t timescale_;            // 时间基
};
```

---

## 关键函数解析

### ParseAVFirstFrames

```cpp
// mpeg4_demuxer_plugin.cpp:355-385
Status MPEG4DemuxerPlugin::ParseAVFirstFrames()
// 目的：在 Prepare 阶段提前解析视频和音频的首帧
// 用于：首帧快速预览 + Codec 参数预配置
// 流程：
//   1. 遍历所有 Track
//   2. 对每个 Track 调用 GetSampleBySeekableStatus() 获取首 Sample
//   3. 缓存到 firstFrameMap_
```

### GetSampleBySeekableStatus

根据流是否 seekable 决定读取策略：

- **seekable=true**：跳到指定位置精确读取
- **seekable=false**：顺序读（直播流场景）

### SeekTo

```cpp
// mpeg4_demuxer_plugin.cpp:829
Status MPEG4DemuxerPlugin::SeekTo(int32_t trackId, int64_t seekTime, SeekMode mode, int64_t &realSeekTime)
{
    MediaAVCodec::AVCodecTrace trace("SeekTo");
    // 1. 查找最近的关键帧（GOP）
    // 2. 通过 MPEG4SampleHelper 换算 PTS → Sample 索引
    // 3. 更新 dataSource_ 读取位置
    // 4. 返回实际 Seek 到的 PTS
}
```

### SeekToKeyFrame

```cpp
// mpeg4_demuxer_plugin.cpp:175
Status MPEG4DemuxerPlugin::SeekToKeyFrame(int32_t trackId, int64_t seekTime);
// 仅 Seek 到关键帧，用于解码器重同步
```

---

## 与 S58（MPEG4BoxParser）的分工

| 功能 | 负责组件 |
|------|---------|
| Box 原子层级解析（ftyp / moov / moof / trak / mdia / minf / stbl 等） | MPEG4AtomParser（见 S58） |
| Sample 提取（stts / stss / ctts / stsc / stsz / stco 表查表） | MPEG4SampleHelper |
| 音频特殊性处理（AAC / FLAC / PCM 通道布局） | MPEG4AudioParser |
| 参考帧解析（H.264 SVC / MVC） | MPEG4ReferenceParser |
| Track 链表构建 + Codec 参数关联 | MPEG4DemuxerPlugin（SetDataSource 时调用 parser） |
| DemuxerPlugin 接口实现（ReadSample / Seek / Flush） | MPEG4DemuxerPlugin |

---

## 与 FFmpegDemuxerPlugin（S68/S76）的对比

| 维度 | MPEG4DemuxerPlugin（S79） | FFmpegDemuxerPlugin（S68/S76） |
|------|--------------------------|-------------------------------|
| 底层库 | 自研 MPEG4AtomParser | FFmpeg libavformat |
| 支持格式 | MP4 / MOV / M4A / 3GP | 25+ 格式（FLV/MKV/MPEGTS/MPEGPS/WMV/OGG 等） |
| 代码行数 | 1625 行 | 4129 行 |
| Fragmented MP4 | 支持（解析 moof + mfhd） | 支持 |
| 优先级 | rank=100（最高） | rank=50 |
| 优势 | 内存占用低、延迟可控 | 格式覆盖广 |
| HDR Vivid | 支持（通过 CUVA 特征串检测） | 支持 |
| 音频 AAC | 自研 MPEG4AudioParser | FFmpeg 内部解码 |
| Seek 策略 | 精确关键帧定位 | av_seek_frame |

---

## Sniff 置信度机制

```cpp
// mpeg4_demuxer_plugin.cpp:45-52
constexpr int32_t FIRST_LEVEL_RANK = 100;   // 明确的 MP4/MOV
constexpr int32_t SECOND_LEVEL_RANK = 95;    // 可能是 MP4
constexpr int32_t THIRD_LEVEL_RANK = 50;    // 边界情况
constexpr int32_t RANK_MIN = 5;
constexpr int32_t RANK_MAX = 101;           // 适配自研优先（+1）

// ProbeSize：前 5MB（PROBE_SIZE = 5000000 字节）用于格式探测
```

**RANK_MAX = 101 的特殊处理**：确保自研 MPEG4DemuxerPlugin 优先于 FFmpegDemuxerPlugin

---

## 关键工程细节

| 项目 | 数值 |
|------|------|
| 文件行数 | 1625 行 |
| Box 解析引擎行数 | 4396 行（MPEG4AtomParser，见 S58） |
| 支持的视频 Codec | AVC（H.264）/ HEVC（H.265）/ VVC（H.266） |
| 支持的音频 Codec | AAC / ALAC / FLAC / PCM |
| 探测数据量 | 5MB（PROBE_SIZE）|
| Sniff 超时数据量 | 2KB（SNIFF_DATA_SIZE）|
| 关键帧 Seek | 支持（SeekToKeyFrame）|
| Edit List（elst）| 支持（用于时间偏移）|
| displayMatrix | 支持 8 类旋转/翻转变换 |

---

## Evidence 摘要

```yaml
source_files:
  - services/media_engine/plugins/demuxer/mpeg4_demuxer/mpeg4_demuxer_plugin.cpp
  - services/media_engine/plugins/demuxer/mpeg4_demuxer/mpeg4_demuxer_plugin.h
  - services/media_engine/plugins/demuxer/mpeg4_demuxer/mpeg4_box_parser.cpp
  - services/media_engine/plugins/demuxer/mpeg4_demuxer/mpeg4_sample_helper.cpp
  - services/media_engine/plugins/demuxer/mpeg4_demuxer/mpeg4_audio_parser.cpp
  - services/media_engine/plugins/demuxer/mpeg4_demuxer/mpeg4_reference_parser.cpp

key_classes:
  - MPEG4DemuxerPlugin (DemuxerPlugin subclass)
  - MPEG4AtomParser (Box 解析引擎，见 S58)
  - MPEG4SampleHelper (Sample 表辅助)
  - MPEG4AudioParser (音频轨辅助)
  - MPEG4ReferenceParser (参考帧辅助)

key_functions:
  - Sniff() — 格式探测，返回置信度
  - SetDataSource() — 调用 parser->MPEG4ParseHeader 建立 Track 链表
  - ParseAVFirstFrames() — 首帧预解析
  - GetSampleBySeekableStatus() — 根据 seekable 状态读取 Sample
  - SeekTo() / SeekToKeyFrame() — 关键帧 Seek

key_constants:
  - PROBE_SIZE = 5000000 (5MB 探测)
  - SNIFF_DATA_SIZE = 2048 (2KB sniff)
  - FIRST_LEVEL_RANK = 100
  - RANK_MAX = 101 (自研优先+1)
```
