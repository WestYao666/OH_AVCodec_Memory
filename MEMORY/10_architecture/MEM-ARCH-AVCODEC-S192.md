# MEM-ARCH-AVCODEC-S192: FFmpegDemuxerPlugin 深度架构——libavformat管线/AVIOContext自定义IO/异步读线程/ReadAhead缓冲

## 状态
- **status**: draft
- **创建时间**: 2026-05-25T17:25:00+08:00
- **Builder**: builder-agent
- **关联主题**: S68/S76(FFmpegDemuxerPlugin草案), S75(MediaDemuxer六组件), S97(DemuxerPluginManager), S79(MPEG4DemuxerPlugin), S111(Demuxer Common工具链), S105(BlockQueuePool)

---

## 概述

FFmpegDemuxerPlugin 是 AVCodec 媒体解封装插件的 FFmpeg 封装层，封装 libavformat（libavformat/libavcodec/libavutil 三大库），负责从容器格式（FLV/MKV/MPEGTS/MP4/MOV 等）中提取压缩音视频样本。

本记忆聚焦 S68/S76 草案未覆盖的**深度机制**：
1. **自定义AVIOContext** —— AVReadPacket/AVWritePacket/AVSeek 三函数回调桥接 DataSource
2. **FFmpegReadLoop 异步读线程** —— 独立后台线程执行 av_read_frame
3. **ReadAhead 缓冲** —— SOFT_LIMIT/HARD_LIMIT 双阈值缓存压力控制
4. **PTS/Index 转换** —— IndexToRelativePTSMaxHeap_ 堆逆查 + RelativePTSToIndex 二分搜索
5. **HDR 元数据提取** —— ParseHEVCMetadataInfo + g_streamContainedXPS
6. **BitstreamFilter 注入** —— AVC/HEVC/VVC Annex B 转换
7. **GOP / I-Frame 索引** —— ReferenceParserManager + dlopen 插件

---

## 源码文件（本地镜像）

| 文件 | 行数 | 职责 |
|------|------|------|
| `services/media_engine/plugins/demuxer/ffmpeg_demuxer/ffmpeg_demuxer_plugin.cpp` | 4129 | 核心：AVIOContext初始化/AVReadPacket回调/PTS转换/HDR/Seek |
| `services/media_engine/plugins/demuxer/ffmpeg_demuxer/ffmpeg_demuxer_thread.cpp` | 895 | 异步读线程 FFmpegReadLoop |
| `services/media_engine/plugins/demuxer/ffmpeg_demuxer/ffmpeg_format_helper.cpp` | 1367 | 25+容器格式类型转换/FFmpeg→内部元数据 |
| `services/media_engine/plugins/demuxer/ffmpeg_demuxer/ffmpeg_demuxer_plugin.h` | 601 | 公开接口 + 私有成员声明 |
| `services/media_engine/plugins/demuxer/ffmpeg_demuxer/ffmpeg_utils.cpp` | 444 | FFmpeg工具函数 |
| `services/media_engine/plugins/demuxer/ffmpeg_demuxer/ffmpeg_reference_parser.cpp` | 488 | ReferenceParser I帧解析器实现 |
| `services/media_engine/plugins/demuxer/ffmpeg_demuxer/avpacket_wrapper.cpp` | 109 | AVPacketWrapper 封装 |
| `services/media_engine/plugins/demuxer/ffmpeg_demuxer/avpacket_memory.cpp` | 77 | AVPacket 内存管理 |
| `services/media_engine/plugins/demuxer/ffmpeg_demuxer/ffmpeg_demuxer_plugin.h` | ~150 private members | 大量内部状态 |

**总计**: ~8399 行核心源码

---

## 一、AVIOContext 自定义IO体系

### 1.1 三函数回调桥接

FFmpegDemuxerPlugin 通过 AllocAVIOContext() 创建自定义 AVIOContext，将 FFmpeg 的流 I/O 操作重定向到 DataSource：

```cpp
// ffmpeg_demuxer_plugin.cpp:1492-1495
int ret = avformat_open_input(&formatContext, nullptr, pluginImpl.get(), options);
// avformat_open_input 内部会调用 AVIOContext 的回调
```

关键回调函数：
```cpp
// ffmpeg_demuxer_plugin.cpp - 静态回调函数
static int AVReadPacket(void* opaque, uint8_t* buf, int bufSize);   // L89+
static int AVWritePacket(void* opaque, const uint8_t* buf, int bufSize);
static int64_t AVSeek(void* opaque, int64_t offset, int whence);
```

```cpp
// ffmpeg_demuxer_plugin.cpp:1509
formatContext->probesize = LIVE_FLV_PROBE_SIZE;  // 100KB*2=200KB
```

### 1.2 IOContext 内部状态机

```cpp
// ffmpeg_demuxer_plugin.h L113-135
struct IOContext {
    std::shared_ptr<DataSource> dataSource {nullptr};
    int64_t offset {0};
    uint64_t fileSize {0};
    bool eos {false};
    std::atomic<bool> retry {false};
    uint64_t initDownloadDataSize {0};
    std::atomic<bool> initCompleted {false};
    DumpMode dumpMode {DUMP_NONE};
    bool isLimit {false};
    bool isLimitType {false};
    int32_t sizeLimit {0};
    int32_t readSizeCnt {0};
    std::atomic<bool> initErrorAgain {false};
    std::mutex invokerTypeMutex;
    std::atomic<InvokerType> invokerType {INVOKER_NONE};
    std::atomic<bool> readCbReady {false};
    std::atomic<AVReadPacketStopState> avReadPacketStopState {UNSET};
    std::atomic<int64_t> readStartTimeMs {0};
    std::atomic<int64_t> readTimeoutMs {0};
};
```

InvokerType 枚举（调用方类型）：
```cpp
enum InvokerType : unsigned int {
    INVOKER_NONE = 0,
    INIT,
    FLUSH,
    READ,
    SEEK,
    DESTORY,
};
```

---

## 二、FFmpegReadLoop 异步读线程

### 2.1 线程启动与状态机

```cpp
// ffmpeg_demuxer_thread.cpp - FFmpegReadLoop 主体
void FFmpegDemuxerPlugin::FFmpegReadLoop()
{
    // 核心循环：从 formatContext_ 读取 AVPacket，写入 cacheQueue_
    while (threadState_ == READING) {
        auto pktWrapper = std::make_shared<AVPacketWrapper>();
        int ffmpegRet = av_read_frame(formatContext_.get(), pkt);
        if (ffmpegRet < 0) {
            // Handle ERROR_AGAIN / EOS / ERROR
        }
        // ConvertAvcToAnnexb / ConvertHevcToAnnexb
        cacheQueue_.Push(trackIndex, samplePacket);
        readCbCv_.notify_one();
    }
}
```

线程状态枚举：
```cpp
enum ThreadState : unsigned int {
    NOT_STARTED,
    WAITING,
    READING,
};
```

### 2.2 读线程与主线程同步

```cpp
// ffmpeg_demuxer_plugin.cpp:2827-2832
if (readThread_ != nullptr && threadState_ == READING) {
    MEDIA_LOG_I("Seek notify read thread to stop");
}
seekWaitCv_.wait(waitLock, [this] { return threadState_ == WAITING || threadState_ == NOT_STARTED; });
```

Flush 时暂停读线程：
```cpp
// ffmpeg_demuxer_plugin.cpp:3139-3142
if (readThread_ != nullptr && threadState_ == READING) {
    MEDIA_LOG_I("Flush wait async read thread");
}
seekWaitCv_.wait(waitLock, [this] { return threadState_ == WAITING || threadState_ == NOT_STARTED; });
```

### 2.3 ReadMode 双模式

```cpp
enum class ReadMode : uint32_t {
    NONE = 0,
    SYNC = 1U << 0,
    ASYNC = 1U << 1,
};
std::atomic<uint32_t> readModeFlags_ {0};
```

- **SYNC 模式**：主线程直接调用 av_read_frame
- **ASYNC 模式**：后台 FFmpegReadLoop 线程读，主线程从 cacheQueue_ 取

---

## 三、ReadAhead 缓冲与缓存压力控制

### 3.1 FfmpegBlockQueuePool

```cpp
// ffmpeg_demuxer_plugin.h L477
FfmpegBlockQueuePool cacheQueue_("cacheQueue");
```

FfmpegBlockQueuePool 继承自 demuxer/common/block_queue_pool.h（模板化内存池）：
- 模板特化 `SamplePacket`（FFmpeg AVPacket 封装）
- AddTrackQueue / RemoveTrackQueue / Push / Pop / Front / Back / GetCacheSize / GetCacheDataSize

### 3.2 SOFT_LIMIT / HARD_LIMIT 双阈值

```cpp
// ffmpeg_demuxer_plugin.cpp L70-78
constexpr uint64_t FILE_SIZE_THRESHOLD = 1ULL * 1024 * 1024 * 1024; // 1GB
constexpr uint32_t SOFT_LIMIT_MULTIPLIER = 2;
constexpr uint32_t HARD_LIMIT_MULTIPLIER = 4;
constexpr uint32_t SOFT_LIMIT_MIN = 20;
constexpr uint32_t HARD_LIMIT_MIN = 50;
```

```cpp
// ffmpeg_demuxer_plugin.cpp:2362-2370 CalculateSoftLimit
uint32_t base = trackCount * SOFT_LIMIT_MULTIPLIER;
if (base < SOFT_LIMIT_MIN) {
    base = SOFT_LIMIT_MIN;
}
// → SOFT_LIMIT = trackCount × 2， 最少 20

// ffmpeg_demuxer_plugin.cpp:2376-2383 CalculateHardLimit
uint32_t base = trackCount * HARD_LIMIT_MULTIPLIER;
if (base < HARD_LIMIT_MIN) {
    base = HARD_LIMIT_MIN;
}
// → HARD_LIMIT = trackCount × 4，最少 50
```

### 3.3 缓存压力回调

```cpp
// ffmpeg_demuxer_plugin.h L365-367
void MaybeNotifyCachePressure(uint32_t trackId, uint32_t cacheBytes);
CachePressureCallback cachePressureCb_{nullptr};
std::unordered_map<uint32_t, uint32_t> trackCacheLimitMap_; // per track bytes limit
```

当 trackCacheLimitMap_[trackId] 超过阈值时触发回调。

---

## 四、PTS / Index 双向转换

### 4.1 IndexToRelativePTS 逆查（堆排序）

```cpp
// ffmpeg_demuxer_plugin.h L318-320
std::priority_queue<int64_t> indexToRelativePTSMaxHeap_; // 最大堆
uint32_t indexToRelativePTSFrameCount_ = 0;
```

```cpp
// ffmpeg_demuxer_plugin.cpp:3310
indexToRelativePTSMaxHeap_ = std::priority_queue<int64_t>(); // init
```

逆查算法：Index → RelativePTS（相对时间戳）
- 用户已知 index，查对应 PTS
- 用 max-heap 找最大 index，对应 PTS 即为结果

### 4.2 RelativePTSToIndex 顺查（二分搜索）

```cpp
// ffmpeg_demuxer_plugin.h L321-326
int64_t relativePTSToIndexPTSMin_ = INT64_MAX;
int64_t relativePTSToIndexPTSMax_ = INT64_MIN;
int64_t relativePTSToIndexRightDiff_ = INT64_MAX;
int64_t relativePTSToIndexLeftDiff_ = INT64_MAX;
```

顺查算法：RelativePTS → Index
- 二分搜索在 sorted PTS 数组中找目标
- 记录左右 diff，找最近 index

### 4.3 AVStreamSnapshot 加速

```cpp
// ffmpeg_demuxer_plugin.h L155-175
struct AVStreamSnapshot {
    bool valid {false};
    AVCodecID codecId {AV_CODEC_ID_NONE};
    AVMediaType codecType {AVMEDIA_TYPE_UNKNOWN};
    AVRational timeBase {0, 1};
    int32_t sampleRate {0};
    int32_t frameSize {0};
    int32_t channels {0};
    int64_t bitRate {0};
    int64_t startTime {AV_NOPTS_VALUE};
    bool needCombineFrame {false};
    bool isVideo {false};
    bool isAudio {false};
};
std::vector<AVStreamSnapshot> streamSnapshots_; // 避免多线程竞争 FFmpeg AVStream
```

---

## 五、HDR 元数据解析

### 5.1 g_streamContainedXPS

```cpp
// ffmpeg_demuxer_plugin.cpp:139-150
const std::vector<AVCodecID> g_streamContainedXPS = {
    AVCodecID::AV_CODEC_ID_H264,
    AVCodecID::AV_CODEC_ID_H265,
    // ... AVC/HEVC 等含 SPS/PPS/VPS 的格式
};
```

### 5.2 ParseHEVCMetadataInfo

```cpp
// ffmpeg_demuxer_plugin.cpp:2731
void FFmpegDemuxerPlugin::ParseHEVCMetadataInfo(const AVStream& avStream, Meta& format)
```

HDR 判定算法（头文件注释）：
1. 仅适用于 H.265 流
2. COLOR_PRIMARIES/COLOR_MATRIX 不是 BT2020 → NONE
3. ITU_T_T35 PREFIX_SEI 存在：
   - COUNTRY_CODE 0xB5/0x26 + PROVIDER_CODE 0x04 + ORIENTED_CODE 0x05 → HDR_VIVID
   - COUNTRY_CODE 0xB5 + PROVIDER_CODE 0x3C → HDR10
4. 无 T35 → 检查 CUVV/DVCC/DVVC/DVH1 box → HDR10
5. 检查 COLOR_TRANSFER_CHARACTERISTIC：PQ → HDR10，HLG → HLG
6. 否则 → NONE（SDR 或非标准 HDR）

### 5.3 WebvttMP4 处理

```cpp
// ffmpeg_demuxer_plugin.cpp:1177
bool FFmpegDemuxerPlugin::IsWebvttMP4(const AVStream *avStream)
```

WebVTT 字幕特殊处理路径。

---

## 六、BitstreamFilter 注入

### 6.1 AVC → AnnexB 转换

```cpp
// ffmpeg_demuxer_plugin.cpp:643
Status FFmpegDemuxerPlugin::ConvertAvcToAnnexb(AVPacket& pkt)
```

当流含 XPS（SPS/PPS）时，通过 BitstreamFilter（bsf）将 MP4-style AVCC 格式转换为 Annex B 起始码格式。

### 6.2 HEVC/VVC 转换

```cpp
// ffmpeg_demuxer_plugin.cpp
Status FFmpegDemuxerPlugin::ConvertHevcToAnnexb(AVPacket& pkt, ...);
Status FFmpegDemuxerPlugin::ConvertVvcToAnnexb(AVPacket& pkt, ...);
```

### 6.3 转换参数结构体

```cpp
// ffmpeg_demuxer_plugin.h L310-325
struct ConvertToAnnexbParams {
    std::shared_ptr<SamplePacket> samplePacket {nullptr};
    uint8_t *outBuffer {nullptr};
    int32_t outBufferSize {0};
    int32_t &outDataSize;
    uint8_t *sideData {nullptr};
    size_t sideDataSize {0};
    explicit ConvertToAnnexbParams(int32_t &outSizeRef) : outDataSize(outSizeRef) {}
};
```

---

## 七、ReferenceParser I-Frame 索引

### 7.1 dlopen 机制

```cpp
// ffmpeg_demuxer_plugin.h L290-291
std::shared_ptr<ReferenceParserManager> referenceParser_{nullptr};
Status ParserRefInit();
```

ReferenceParserManager（来自 demuxer/common/reference_parser_manager.cpp）dlopen 加载 `.so` 插件，提供 I-Frame 位置解析能力。

### 7.2 GOP Layer 索引

```cpp
// ffmpeg_demuxer_plugin.h
Status GetGopLayerInfo(uint32_t gopId, GopLayerInfo &gopLayerInfo) override;
Status GetIFramePos(std::vector<uint32_t> &IFramePos) override;
Status Dts2FrameId(int64_t dts, uint32_t &frameId) override;
Status SeekMs2FrameId(int64_t seekMs, uint32_t &frameId) override;
Status FrameId2SeekMs(uint32_t frameId, int64_t &seekMs) override;
```

### 7.3 Key Frame 快速定位

```cpp
// ffmpeg_demuxer_plugin.cpp L2989
return av_seek_frame(formatContext_.get(), idx, timestamp, flags);
// Key Frame Seek: flags = AVSEEK_FLAG_BACKWARD
```

---

## 八、Seek 机制

### 8.1 多级 Seek 入口

```cpp
// ffmpeg_demuxer_plugin.h
Status SeekTo(int32_t trackId, int64_t seekTime, SeekMode mode, int64_t& realSeekTime) override;
Status SeekToKeyFrame(int32_t trackId, int64_t seekTime, ...) override;
Status SeekToFrameByDts(int32_t trackId, int64_t seekTime, ...) override;
Status SeekToStart() override;
```

### 8.2 Seek 同步流程

```cpp
// ffmpeg_demuxer_plugin.cpp:2827-2832
if (readThread_ != nullptr && threadState_ == READING) {
    MEDIA_LOG_I("Seek notify read thread to stop");
}
seekWaitCv_.wait(waitLock, [this] { return threadState_ == WAITING || threadState_ == NOT_STARTED; });
```

Seek 流程：
1. 通知读线程停止（threadState_ → WAITING）
2. 等待读线程进入 WAITING 状态
3. 执行 av_seek_frame
4. 清空 cacheQueue_
5. 恢复读线程

### 8.3 RM 流特殊 Seek

```cpp
// ffmpeg_demuxer_plugin.cpp L2991
int FFmpegDemuxerPlugin::RMSeekToStart();
```

RealMedia（RM）格式的特殊 Seek 路径。

---

## 九、25+ 容器格式支持

FFmpegFormatHelper 维护 FFmpeg 格式与内部格式的映射：

```cpp
// ffmpeg_format_helper.cpp:1367 lines
// 支持格式（不完全列举）：
// FLV → FLV
// MKV → MKV
// MPEGTS → TS
// MPEGPS → PS
// MP4/MOV → MP4
// AVI → AVI
// WAV → WAV
// RM → RM
// WMV → WMV
// OGG → OGG
// ... 共 25+ 种
```

---

## 十、多轨 Parsing

### 10.1 MultiStreamParserManager

```cpp
// ffmpeg_demuxer_plugin.h L290
std::shared_ptr<MultiStreamParserManager> streamParsers_ {nullptr};
```

来自 demuxer/common/multi_stream_parser_manager.cpp（293行），管理多轨流解析。

### 10.2 PTS 累积模式

```cpp
// ffmpeg_demuxer_plugin.cpp L3306-3310
void FFmpegDemuxerPlugin::InitPTSandIndexConvert()
{
    indexToRelativePTSMaxHeap_ = std::priority_queue<int64_t>(); // init
}
```

---

## 十一、与 S68/S76 草案的关系

| 维度 | S68/S76 草案 | S192 本记忆 |
|------|-------------|------------|
| av_read_frame 管线 | ✅ 提及 | ✅ 深度：FFmpegReadLoop 异步线程 |
| avformat_open_input | ✅ 提及 | ✅ 深度：AVIOContext 自定义三回调 |
| BitstreamFilter | ✅ 提及 | ✅ 深度：ConvertAvc/Hevc/VvcToAnnexb 完整转换链 |
| ReadAhead 缓冲 | ❌ 未覆盖 | ✅ 深度：SOFT_LIMIT/HARD_LIMIT 计算公式 |
| PTS/Index 转换 | ❌ 未覆盖 | ✅ 深度：MaxHeap逆查 + 二分顺查 |
| HDR 元数据 | ❌ 未覆盖 | ✅ 深度：ParseHEVCMetadataInfo 六步判定算法 |
| ReferenceParser | ❌ 未覆盖 | ✅ 深度：dlopen GOP/I-Frame 索引 |
| AVStreamSnapshot | ❌ 未覆盖 | ✅ 深度：无锁线程安全快照 |
| Seek 机制 | ❌ 未覆盖 | ✅ 深度：多级Seek + 读线程同步 + RM特殊Seek |
| WebVTT | ❌ 未覆盖 | ✅ 深度：IsWebvttMP4 + EOS处理 |
| LIVE_FLV_PROBE_SIZE | ❌ 未覆盖 | ✅ 200KB 直播流探针 |
| ReadMode 双模式 | ❌ 未覆盖 | ✅ SYNC/ASYNC 模式切换 |

---

## 关键行号速查

| 功能 | 文件 | 行号 |
|------|------|------|
| AVReadPacket 回调 | ffmpeg_demuxer_plugin.cpp | ~89 |
| avformat_open_input | ffmpeg_demuxer_plugin.cpp | 1492 |
| av_read_frame 调用 | ffmpeg_demuxer_plugin.cpp | 1250/1254 |
| av_seek_frame 调用 | ffmpeg_demuxer_plugin.cpp | 2863/2989 |
| LIVE_FLV_PROBE_SIZE | ffmpeg_demuxer_plugin.cpp | 80 |
| SOFT_LIMIT 计算 | ffmpeg_demuxer_plugin.cpp | 2362-2370 |
| HARD_LIMIT 计算 | ffmpeg_demuxer_plugin.cpp | 2376-2383 |
| g_streamContainedXPS | ffmpeg_demuxer_plugin.cpp | 139-150 |
| ParseHEVCMetadataInfo | ffmpeg_demuxer_plugin.cpp | 2731 |
| ConvertAvcToAnnexb | ffmpeg_demuxer_plugin.cpp | 643 |
| FFmpegReadLoop | ffmpeg_demuxer_thread.cpp | ~234+ |
| cacheQueue_.Push | ffmpeg_demuxer_plugin.cpp | 1137/1150 |
| Seek 线程同步 | ffmpeg_demuxer_plugin.cpp | 2827-2832 |
| AVStreamSnapshot | ffmpeg_demuxer_plugin.h | 155-175 |
| IsWebvttMP4 | ffmpeg_demuxer_plugin.cpp | 1177 |
| PTS 逆查堆 | ffmpeg_demuxer_plugin.cpp | 3310 |

---

## 关联记忆

- S68/S76: FFmpegDemuxerPlugin 基础草案（未覆盖深度机制）
- S75: MediaDemuxer 六组件（上游封装层）
- S79: MPEG4DemuxerPlugin（竞争插件，rank=100 自研优先）
- S97: DemuxerPluginManager（三层 TrackID 映射）
- S105: BlockQueuePool（内存池基类）
- S111: Demuxer Common（ReferenceParser/Converter/TimeRangeManager）
- S123: StreamDemuxer（PullData 三路分发）
- S134: FFmpegDemuxerPlugin 高级特性（HDR/BitstreamFilter/PTS索引/ReadAhead）