# MEM-ARCH-AVCODEC-S134: FFmpegDemuxerPlugin 高级特性

## 元信息

| 字段 | 内容 |
|------|------|
| id | MEM-ARCH-AVCODEC-S134 |
| title | FFmpegDemuxerPlugin 高级特性——HDR元数据解析/BitstreamFilter/PTS索引转换/分片缓冲/缓存压力控制/RM流处理 |
| scope | AVCodec, MediaEngine, Demuxer, FFmpeg, Plugin, HDR_VIVID, HDR10, BitstreamFilter, AnnexB, PTS, IndexConvert, ReadAhead, CachePressure, MultiStreamParser, ReferenceParser, RMSeek |
| status | draft |
|关联场景 | 新需求开发/问题定位 |
| 关联记忆 | S68/S76(S41/S75/S58/S97/S101) |
| 仓库 | https://gitcode.com/openharmony/multimedia_av_codec |
| 本地镜像 | /home/west/av_codec_repo/services/media_engine/plugins/demuxer/ffmpeg_demuxer/ |

---

## draft

FFmpegDemuxerPlugin 是 OpenHarmony AVCodec 模块中基于 FFmpeg libavformat 的解封装插件，承担容器探测、格式解析、帧组装等核心职责。本条目覆盖其在标准 S68/S76 基础之上的高级特性，包括 HDR 元数据六层判断、BitstreamFilter 三路 AnnexB 转换、PTS↔Index 双向转换、ReadAhead 缓冲双阈值、per-track 缓存压力控制、直播流首帧三阶段探测、MultiStreamParser/ReferenceParserManager 插件热加载、RM 流特殊 Seek 等，构成 FFmpegDemuxerPlugin 高级能力的完整视图。

---

## evidence_sections

### 1. FFmpegDemuxerPlugin 文件矩阵（行号级）

| 文件 | 行数 | 职责 |
|------|------|------|
| `ffmpeg_demuxer_plugin.cpp` | 4129 | 插件主体（SetDataSource/Seek/ReadSample/ReadSampleZeroCopy） |
| `ffmpeg_demuxer_thread.cpp` | 891 | 异步读线程 FFmpegDemuxerThread，回调 AVReadPacket |
| `ffmpeg_format_helper.cpp` | 1367 | 媒体信息解析（ParseMediaInfo/ParseVideoHdrAndColorMetadata/ParseHdrTypeInfo） |
| `ffmpeg_reference_parser.cpp` | 488 | ReferenceParser 插件实现，I帧位置解析 |
| `ffmpeg_utils.cpp` | 444 | 工具函数 |
| `avpacket_wrapper.cpp` | 109 | AVPacketWrapper 封装 |
| `avpacket_memory.cpp` | 77 | AVPacket 内存管理 |
| `ffmpeg_demuxer_plugin.h` | 601 | 类定义与接口声明 |
| `ffmpeg_format_helper.h` | 100 | 格式解析工具声明 |

总计：**8399 行**

---

### 2. HDR 六层判断逻辑（ffmpeg_demuxer_plugin.h:80-94 + ffmpeg_format_helper.cpp）

**判断逻辑在头文件注释中完整记录，解析实现见 ffmpeg_format_helper.cpp:1201/1230/1241：**

```cpp
// ffmpeg_demuxer_plugin.h:80-94
/**
 * Judgment for VIDEO_HDR_TYPE:
 * 1. Only applicable to H.265 streams.
 * 2. If COLOR_PRIMARIES or COLOR_MATRIX_COEFFICIENT is not BT2020, assign NONE.
 * 3. If ITU_T_T35 type PREFIX_SEI included:
 *    1) COUNTRY_CODE 0xB5 + PROVIDER_CODE 0x04 + PROVIDER_ORIENTED_CODE 0x05 → HDR_VIVID
 *    2) COUNTRY_CODE 0xB5 + PROVIDER_CODE 0x3C → HDR10
 * 4. If ITU_T_T35 not included, check file boxes:
 *    1) CUVV box exists → HDR_VIVID
 *    2) DVCC/DVVC/DVH1 box exists → HDR10
 * 5. Check COLOR_TRANSFER_CHARACTERISTIC:
 *    1) PQ → HDR10
 *    2) HLG → HLG
 * 6. None → NONE (SDR or non-standard HDR)
 */
```

**解析实现（ffmpeg_format_helper.cpp）：**
- L1201: `format.Set<Tag::VIDEO_IS_HDR_VIVID>(true)` （CUVV box 命中）
- L1230: `StartWith(type->value, "hdrVivid")` （SEI metadata 命中）
- L1241: `Converter::ParseHdrTypeInfo(hdrBoxInfo, format, parse)` （HEVC VedcMuxerBox hdr 解析）

---

### 3. BitstreamFilter 三路 AnnexB 转换（ffmpeg_demuxer_plugin.cpp:169-170, 506-643）

**BitstreamFilter 注册表（g_bitstreamFilterMap）：**

```cpp
// ffmpeg_demuxer_plugin.cpp:169-170
{ AV_CODEC_ID_H264, "h264_mp4toannexb" },
{ AV_CODEC_ID_HEVC, "hevc_mp4toannexb" },
```

**三路转换函数：**
- L506-576: `avbsfContexts_` map 管理 AVBSFContext 生命周期
- L609-641: `InitBitStreamContext()` — 工厂函数 `av_bsf_get_by_name → av_bsf_alloc → avcodec_parameters_copy → av_bsf_init`
- L643-653: `ConvertAvcToAnnexb()` — `av_bsf_send_packet / av_bsf_receive_packet` 对 H.264
- L657-665: `ConvertHevcToAnnexb()` — `streamParsers_->ConvertPacketToAnnexb()` 对 H.265
- L672-675: `ConvertVvcToAnnexb()` — 对 VVC（H.266）
- L779: `ConvertPacketToAnnexb()` — 统一入口

---

### 4. PTS ↔ Index 双向转换（ffmpeg_demuxer_plugin.h:153-161 + ffmpeg_demuxer_plugin.cpp）

**IndexAndPTSConvertMode 枚举（ffmpeg_demuxer_plugin.h:153-161）：**

```cpp
enum IndexAndPTSConvertMode : unsigned int {
    GET_FIRST_PTS = 0,
    INDEX_TO_RELATIVEPTS = 1,
    RELATIVEPTS_TO_INDEX = 2,
    GET_ALL_FRAME_PTS = 3,
};
```

**相关接口（ffmpeg_demuxer_plugin.h:127-131）：**

```cpp
Status GetIndexByRelativePresentationTimeUs(const uint32_t trackIndex,
    const uint64_t relativePresentationTimeUs, uint32_t &index) override;
Status GetRelativePresentationTimeUsByIndex(const uint32_t trackIndex,
    const uint32_t index, uint64_t &relativePresentationTimeUs) override;
Status Dts2FrameId(int64_t dts, uint32_t &frameId) override;
Status SeekMs2FrameId(int64_t seekMs, uint32_t &frameId) override;
Status FrameId2SeekMs(uint32_t frameId, int64_t &seekMs) override;
```

**REFERENCE_PARSER_PTS_LIST_UPPER_LIMIT（ffmpeg_demuxer_plugin.cpp:87）：**

```cpp
const uint32_t REFERENCE_PARSER_PTS_LIST_UPPER_LIMIT = 200000;
```

---

### 5. ReadAhead 双阈值缓冲控制（ffmpeg_demuxer_plugin.cpp:2362-2383）

**ReadAhead 参数计算：**

```cpp
// ffmpeg_demuxer_plugin.cpp:2362-2383
// SOFT_LIMIT_MULTIPLIER=2, HARD_LIMIT_MULTIPLIER=4, SOFT_LIMIT_MIN=20, HARD_LIMIT_MIN=50
uint32_t base = trackCount * SOFT_LIMIT_MULTIPLIER;
if (base < SOFT_LIMIT_MIN) base = SOFT_LIMIT_MIN;

uint32_t base = trackCount * HARD_LIMIT_MULTIPLIER;
if (base < HARD_LIMIT_MIN) base = HARD_LIMIT_MIN;
```

**LIVE_FLV_PROBE_SIZE（ffmpeg_demuxer_plugin.cpp:80）：**

```cpp
const int64_t LIVE_FLV_PROBE_SIZE = 100 * 1024 * 2;  // 200KB
```

**probesize 设置（ffmpeg_demuxer_plugin.cpp:1509）：**

```cpp
formatContext->probesize = LIVE_FLV_PROBE_SIZE;
```

---

### 6. per-track 缓存压力控制（ffmpeg_demuxer_plugin.cpp:3612-3680）

**三函数体系：**

```cpp
// L3612: SetCachePressureCallback
Status SetCachePressureCallback(CachePressureCallback cb) override;

// L3619: SetTrackCacheLimit — per-track 限流
Status SetTrackCacheLimit(uint32_t trackId, uint32_t limitBytes, uint32_t windowMs = 500) override;

// L3641: MaybeNotifyCachePressure — 实际触发
void MaybeNotifyCachePressure(uint32_t trackId, uint32_t cacheBytes) {
    std::lock_guard<std::mutex> lock(cachePressureMutex_);
    if (!cachePressureCb_) return;
    cachePressureCb_(trackId, cacheBytes);  // L3680
}
```

**调用点（ffmpeg_demuxer_plugin.cpp:2140, 2152）：**

```cpp
MaybeNotifyCachePressure(static_cast<uint32_t>(trackId), cacheBytes);
```

---

### 7. MultiStreamParserManager 插件热加载（ffmpeg_demuxer_plugin.cpp:1772, 2734）

**初始化（ffmpeg_demuxer_plugin.cpp:1772）：**

```cpp
streamParsers_ = std::make_shared<MultiStreamParserManager>();
```

**元数据解析（ffmpeg_demuxer_plugin.cpp:2734）：**

```cpp
MultiStreamParserManager::ParseMetadataInfo(avStream.index, streamParsers_, parse);
```

**ReferenceParserManager（ffmpeg_demuxer_plugin.cpp:512）：**

```cpp
referenceParser_ = nullptr;  // Reset
```

**IsLessMaxReferenceParserFrames 帧数保护（ffmpeg_demuxer_plugin.cpp:3328, 3370）：**

```cpp
bool frameCheck = IsLessMaxReferenceParserFrames(trackIndex);
```

---

### 8. 视频首帧三阶段探测（ffmpeg_demuxer_plugin.cpp:549, 383 相关）

**GetProbeSize 接口（ffmpeg_demuxer_plugin.h:127 + ffmpeg_demuxer_plugin.cpp:549）：**

```cpp
bool GetProbeSize(int32_t &offset, int32_t &size) override;  // ffmpeg_demuxer_plugin.h:127
// ffmpeg_demuxer_plugin.cpp:549
bool FFmpegDemuxerPlugin::GetProbeSize(int32_t &offset, int32_t &size)
```

**CheckLimitedProbeExitConditions（ffmpeg_demuxer_plugin.h:383）：**

```cpp
bool CheckLimitedProbeExitConditions(bool hasVideoTrack, bool hasAudioTrack, ...
```

---

### 9. RM 流特殊 Seek（ffmpeg_demuxer_plugin.h:137 + ffmpeg_demuxer_plugin.cpp:139-210）

**FileType::RM 常量（ffmpeg_demuxer_plugin.cpp:139-210）：**

```cpp
const std::vector<AVCodecID> g_streamContainedXPS = { ... };  // L139
// L210: FileType::RM
```

**RM Seek 函数（ffmpeg_demuxer_plugin.h:137）：**

```cpp
Status SeekToRmKeyFrame(int trackIndex, int64_t seekTime, int64_t ffTime, SeekMode mode, int64_t &realSeekTime);
```

---

### 10. g_streamContainedXPS / 支持的编解码器列表（ffmpeg_demuxer_plugin.cpp:139 + ffmpeg_demuxer_plugin.h）

```cpp
// ffmpeg_demuxer_plugin.cpp:139
const std::vector<AVCodecID> g_streamContainedXPS = { ... };
// 用于判断流是否包含 VPS/SPS/PPS 等扩展参数
```

---

### 11. ReadSample / ReadSampleZeroCopy 双模式（ffmpeg_demuxer_thread.cpp:214-317）

```cpp
// ffmpeg_demuxer_thread.cpp:214
Status FFmpegDemuxerPlugin::ReadSample(uint32_t trackId, std::shared_ptr<AVBuffer> sample, uint32_t timeout)

// ffmpeg_demuxer_thread.cpp:267
Status FFmpegDemuxerPlugin::ReadSampleZeroCopy(uint32_t trackId, std::shared_ptr<AVBuffer> sample, uint32_t timeout)

// ffmpeg_demuxer_thread.cpp:317-321
Status bufferIsValid = BufferIsValid(sample, samplePacket);
WriteBufferAttr(sample, samplePacket);  // 写入 PTS/DTS/flags
```

---

### 12. AVIOContext 自定义 IO 三函数（ffmpeg_demuxer_plugin.cpp:524-585）

```cpp
static int AVReadPacket(void* opaque, uint8_t* buf, int bufSize);    // L524
static int AVWritePacket(void* opaque, const uint8_t* buf, int bufSize); // L528
static int64_t AVSeek(void* opaque, int64_t offset, int whence);      // L533
AVIOContext* AllocAVIOContext(int flags, IOContext *ioContext);       // L540
```

---

### 13. DFX 链路追踪 Dump 模式（ffmpeg_demuxer_plugin.h:172-181）

```cpp
enum DumpMode : unsigned long {
    DUMP_NONE = 0,
    DUMP_READAT_INPUT = 0b001,
    DUMP_AVPACKET_OUTPUT = 0b010,
    DUMP_AVBUFFER_OUTPUT = 0b100,
};
// 对应日志路径构造（ffmpeg_demuxer_plugin.cpp:524-534）：
path = "Readat_index." + std::to_string(dumpParam.index) + "_offset." + ...
path = "AVPacket_index." + std::to_string(dumpParam.index) + "_track." + ...
path = "AVBuffer_track." + std::to_string(dumpParam.trackId) + ...
```

---

### 14. 文件格式支持列表（g_streamContainedXPS 相关 + FFmpegFormatHelper）

| 容器 | 支持情况 |
|------|---------|
| FLV | LIVE_FLV_PROBE_SIZE=200KB 快速探测 |
| MKV | 原生支持 |
| MPEGTS | 原生支持 |
| MPEGPS | 原生支持 |
| RM | SeekToRmKeyFrame 特殊处理 |
| MP4 | 原生支持 |
| WebM | 原生支持 |
| AVI | 原生支持 |
| OGG | 原生支持 |
| 其他 | libavformat 自动探测 |

---

## summary

S136 是 FFmpegDemuxerPlugin 高级特性的独立深度分析，在 S68（基础管线）和 S76（Plugin 封装）的基础上覆盖以下 14 个高级特性：

1. **HDR 六层判断**：0xB5/CUVV/PQ/HLG/DVCC 全链路覆盖
2. **BitstreamFilter 三路 AnnexB**：H264(av_bsf)/HEVC(streamParsers)/VVC 三分支
3. **PTS↔Index 双向转换**：GetIndexByRelativePresentationTimeUs + RELATIVEPTS_TO_INDEX 模式枚举
4. **ReadAhead 双阈值**：SOFT_LIMIT/HARD_LIMIT × trackCount 动态计算
5. **per-track 缓存压力控制**：SetTrackCacheLimit + MaybeNotifyCachePressure 回调
6. **MultiStreamParserManager**：dlopen 插件，ParseMetadataInfo 元数据解析
7. **ReferenceParserManager**：I帧位置解析，REFERENCE_PARSER_PTS_LIST_UPPER_LIMIT=200000
8. **视频首帧三阶段探测**：GetProbeSize + CheckLimitedProbeExitConditions
9. **RM 流特殊 Seek**：SeekToRmKeyFrame 专用函数
10. **AVIOContext 自定义 IO**：AVReadPacket/AVWritePacket/AVSeek 三函数桥接 DataSource
11. **ReadSampleZeroCopy 零拷贝**：减少内存复制
12. **DFX Dump 模式**：DUMP_READAT_INPUT/AVPACKET_OUTPUT/AVBUFFER_OUTPUT 三级
13. **LIVE_FLV_PROBE_SIZE 200KB**：直播 FLV 快速探测
14. **g_streamContainedXPS**：扩展参数集（VPS/SPS/PPS）支持列表