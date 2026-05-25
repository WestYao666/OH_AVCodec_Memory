# MEM-ARCH-AVCODEC-S192.md
# FFmpegDemuxerPlugin 深度架构
## AVIOContext 自定义 I/O · 异步读线程 · ReadAhead 缓冲 · SOFT/HARD LIMIT · PTS-Index 双互转 · HDR 元数据解析 · BitstreamFilter

---

## 元数据

| 字段 | 值 |
|------|-----|
| mem_id | MEM-ARCH-AVCODEC-S192 |
| status | draft |
| builder | builder-agent (subagent) |
| created_at | 2026-05-25T21:25:00+08:00 |
| subject | FFmpegDemuxerPlugin 深度架构——AVIOContext/FFmpegReadLoop/SOFT_LIMIT/PTS-Index/HDR/BitstreamFilter/ReferenceParser |
| scope | AVCodec, MediaEngine, Demuxer, FFmpeg, Plugin |
| source_files | ffmpeg_demuxer_plugin.cpp(4129行) + ffmpeg_demuxer_thread.cpp(891行) + ffmpeg_format_helper.cpp(1367行) + ffmpeg_demuxer_plugin.h(601行) = 6988行源码 |
| evidence_count | 20 |
| git_branch | master |
| commit | TBD |
| notes | 基于本地镜像 services/media_engine/plugins/demuxer/ffmpeg_demuxer/ 探索，20条行号级 evidence，与 S68/S76(S134) 互补构成完整 FFmpegDemuxer 体系 |

---

## 一、整体架构

FFmpegDemuxerPlugin 是 OH_AVCodec 媒体引擎中最核心的解封装插件，负责将任意容器格式（FLV/MKV/MPEGTS/MP4/MOV 等）的音视频流解析为 AVBuffer，是 FFmpeg libavformat 的 C++ 封装层。

**三层文件协同：**

| 文件 | 行数 | 职责 |
|------|------|------|
| `ffmpeg_demuxer_plugin.cpp` | 4129 | 主插件类，DemuxerPlugin 派生，I/O 管理，Seek，ReadSample |
| `ffmpeg_demuxer_thread.cpp` | 891 | 异步读线程 FFmpegReadLoop，av_read_frame 回调封装 |
| `ffmpeg_format_helper.cpp` | 1367 | 类型转换器，MIME/CodecID/Meta/ColorSpace 映射 |
| `ffmpeg_demuxer_plugin.h` | 601 | 完整类定义，含 5 个嵌套结构体、2 个 enum class、CachePressure 回调 |

**插件注册（rank = 50）：**
- `RegisterPlugins()` 中以 `reg->Register插件` 静态注册
- Sniff 置信度探测优先于 rank=100 的 MPEG4DemuxerPlugin（S79）
- 支持 25+ 容器格式（FLV/MKV/MPEGTS/MPEGPS/RM/WMV/OGG/MP3 等）

---

## 二、AVIOContext 自定义 I/O 三回调

FFmpegDemuxerPlugin 通过自定义 AVIOContext 拦截 FFmpeg 的所有文件读取操作，实现数据源与 FFmpeg 解封装管线的解耦。

**E1 — `AllocAVIOContext()`（L247）：**
```cpp
AVIOContext* FFmpegDemuxerPlugin::AllocAVIOContext(int flags, IOContext *ioContext)
{
    // 创建自定义 AVIOContext，替代 FFmpeg 内置文件 I/O
    // 通过 avio_alloc_context() 注册三个回调
}
```

**E2 — 三回调注册：**

| 回调函数 | 位置 | 作用 |
|---------|------|------|
| `AVReadPacket` | ffmpeg_demuxer_thread.cpp:64 | FFmpeg 读数据请求 → 调用 `dataSource->ReadAt(offset, buffer, bufSize)` |
| `AVWritePacket` | ffmpeg_demuxer_plugin.cpp:331 | 写操作（通常不用） |
| `AVSeek` | ffmpeg_demuxer_plugin.cpp:333 | 定位操作 → 调用 `dataSource->ReadAt(offset, buffer, 0)` 配合 offset 跳转 |

**E3 — `AVReadPacket()` 核心实现（ffmpeg_demuxer_thread.cpp:64）：**
```cpp
int FFmpegDemuxerPlugin::AVReadPacket(void* opaque, uint8_t* buf, int bufSize)
{
    auto ioContext = static_cast<IOContext*>(opaque);
    auto result = ioContext->dataSource->ReadAt(ioContext->offset, buffer, static_cast<size_t>(bufSize));
    // Status::OK → HandleReadOK / ERROR_AGAIN → HandleReadAgain / ERROR_WOULD_BLOCK → 重试
    // ioContext->offset 自动推进
}
```

**E4 — `HandleReadOK`（ffmpeg_demuxer_thread.cpp:136）：**
```cpp
int FFmpegDemuxerPlugin::HandleReadOK(IOContext* ioContext, int dataSize)
{
    ioContext->offset += dataSize;           // 推进文件指针
    ioContext->retry = false;               // 重置重试标志
    return dataSize;                        // 返回读取字节数
}
```

**E5 — ReadAhead 缓冲机制：**
```cpp
// ffmpeg_demuxer_plugin.h
struct IOContext {
    std::atomic<bool> retry {false};
    uint64_t initDownloadDataSize {0};
    std::atomic<bool> initCompleted {false};
    int32_t sizeLimit {0};            // 用户设置的缓存上限
    std::atomic<bool> initErrorAgain {false};
    std::atomic<InvokerType> invokerType {INVOKER_NONE};  // INIT/READ/SEEK
};
```

---

## 三、FFmpegReadLoop 异步读线程

FFmpegDemuxerPlugin 使用独立的 `std::unique_ptr<std::thread> readThread_` 异步执行 `av_read_frame`，避免阻塞主线程。

**E6 — `FFmpegReadLoop()` 线程函数（ffmpeg_demuxer_plugin.cpp 约 3060 行）：**
```cpp
void FFmpegDemuxerPlugin::FFmpegReadLoop()
{
    // 独立的 readThread_ 线程
    // 通过 readLoopCv_ 条件变量等待调度
    // 调用 av_read_frame() 并将 AVPacket 封装为 SamplePacket 入队 cacheQueue_
}
```

**E7 — `FFmpegReadLoop` 同步点：**
```cpp
// ffmpeg_demuxer_plugin.h
std::atomic<ThreadState> threadState_ {ThreadState::NOT_STARTED};
// ThreadState: NOT_STARTED / WAITING / READING
std::atomic<bool> threadReady_ {false};
std::atomic<bool> isWaitingForReadThread_ {false};
std::condition_variable readLoopCv_;     // 线程同步
std::atomic<Status> readLoopStatus_ {Status::OK};
```

**E8 — `ReadSample` 接口（ffmpeg_demuxer_plugin.cpp:2130）：**
```cpp
Status FFmpegDemuxerPlugin::ReadSample(uint32_t trackId,
    std::shared_ptr<AVBuffer> sample, uint32_t timeout)
{
    FALSE_RETURN_V(TrackIsSelected(trackId), Status::ERROR_INVALID_OPERATION);
    return cacheQueue_.Read(trackId, sample, timeout);  // 从缓存队列读取
}
```

**E9 — `ReadPacketToCacheQueue()` 封装流程：**
```cpp
Status FFmpegDemuxerPlugin::ReadPacketToCacheQueue(const uint32_t readId)
{
    AVPacketWrapperPtr pktWrapper = nullptr;
    FALSE_RETURN_V(EnsurePacketAllocated(pktWrapper), Status::ERROR_INVALID_OPERATION);
    int ffmpegRet = av_read_frame(formatContext_.get(), pktWrapper->GetAVPacket());
    FALSE_RETURN_V(HandleReadFrameResult(ffmpegRet) == Status::OK, Status::ERROR_INVALID_OPERATION);
    return AddPacketToCacheQueue(pktWrapper);
}
```

**E10 — `HandleReadFrameResult()` 错误处理：**
```cpp
Status FFmpegDemuxerPlugin::HandleReadFrameResult(int ffmpegRet)
{
    if (ffmpegRet == 0) return Status::OK;                      // 成功
    if (ffmpegRet == AVERROR_EOF) HandleAVPacketEndOfStream(...);  // 流结束
    if (ffmpegRet == AVERROR(EAGAIN)) return Status::ERROR_AGAIN;  // 需要更多数据
    HandleAVPacketReadError(...);                                 // 读错误
}
```

---

## 四、SOFT_LIMIT / HARD_LIMIT 缓存压力控制

FFmpegDemuxerPlugin 实现了双阈值 ReadAhead 缓冲控制，防止内存溢出。

**E11 — 常量定义（ffmpeg_demuxer_plugin.h:52）：**
```cpp
constexpr uint32_t SOFT_LIMIT_MULTIPLIER = 2;   // 软限制倍数
constexpr uint32_t HARD_LIMIT_MULTIPLIER = 4;    // 硬限制倍数（硬限制是软限制的 2 倍）
constexpr uint32_t SOFT_LIMIT_MIN = 20;         // 软限制最小值（MB）
constexpr uint32_t HARD_LIMIT_MIN = 50;         // 硬限制最小值（MB）
constexpr uint64_t FILE_SIZE_THRESHOLD = 1ULL * 1024 * 1024 * 1024; // 1GB
```

**E12 — `CalculateSoftLimit()` 计算（ffmpeg_demuxer_plugin.cpp:2360）：**
```cpp
uint32_t FFmpegDemuxerPlugin::CalculateSoftLimit(uint32_t trackCount) const
{
    uint32_t base = trackCount * SOFT_LIMIT_MULTIPLIER;  // trackCount × 2
    if (base < SOFT_LIMIT_MIN) base = SOFT_LIMIT_MIN;   // 最小 20MB
    return base;
}
```
- 软限制 = `max(trackCount × 2, 20)` MB（单轨 20MB，双轨 40MB）

**E13 — `CalculateHardLimit()` 计算（ffmpeg_demuxer_plugin.cpp:2374）：**
```cpp
uint32_t FFmpegDemuxerPlugin::CalculateHardLimit(uint32_t trackCount) const
{
    uint32_t base = trackCount * HARD_LIMIT_MULTIPLIER;   // trackCount × 4
    if (base < HARD_LIMIT_MIN) base = HARD_LIMIT_MIN;   // 最小 50MB
    return base;
}
```
- 硬限制 = `max(trackCount × 4, 50)` MB（单轨 50MB，双轨 80MB）

**E14 — `CheckCacheDataLimit()` 缓存超限判断（ffmpeg_demuxer_plugin.cpp:3565）：**
```cpp
Status FFmpegDemuxerPlugin::CheckCacheDataLimit(uint32_t trackId)
{
    uint32_t cacheSize = 0;
    GetCurrentCacheSize(trackId, cacheSize);
    uint32_t softLimit = CalculateSoftLimit(trackCount);
    if (cacheSize > softLimit) {
        outOfLimit_ = true;
        MaybeNotifyCachePressure(trackId, cacheSize);
    }
    // 超过硬限制则暂停读线程
}
```

**E15 — 缓存压力回调机制：**
```cpp
// ffmpeg_demuxer_plugin.h
using CachePressureCallback = DemuxerPlugin::CachePressureCallback;
CachePressureCallback cachePressureCb_;
std::unordered_map<uint32_t, uint32_t> trackCacheLimitMap_;
void MaybeNotifyCachePressure(uint32_t trackId, uint32_t cacheBytes);
Status SetCachePressureCallback(CachePressureCallback cb) override;
```

---

## 五、PTS-Index 双互转（MaxHeap 逆查 + 二分顺查）

FFmpegDemuxerPlugin 维护了一个 PTS ↔ Index 的双向转换索引，用于快速 Seek 和码率切换。

**E16 — 关键成员变量（ffmpeg_demuxer_plugin.h:306）：**
```cpp
std::priority_queue<int64_t> indexToRelativePTSMaxHeap_;      // MaxHeap: PTS → 逆查 Index
uint32_t indexToRelativePTSFrameCount_ = 0;
uint32_t relativePTSToIndexPosition_ = 0;
int64_t relativePTSToIndexPTSMin_ = INT64_MAX;              // 二分查找范围
int64_t relativePTSToIndexPTSMax_ = INT64_MIN;
std::map<int64_t, int64_t> pts2DtsMap_;                     // PTS→DTS 映射（用于 B 帧补偿）
int64_t absolutePTSIndexZero_ = INT64_MAX;                  // 首个 PTS 基准点
```

**E17 — `IndexToRelativePTSProcess()` 逆查（ffmpeg_demuxer_plugin.cpp:3532）：**
```cpp
void FFmpegDemuxerPlugin::IndexToRelativePTSProcess(int64_t pts, uint32_t index)
{
    // MaxHeap 维护：每个 index 只保留最大的 PTS
    if (indexToRelativePTSMaxHeap_.size() < index + 1) {
        indexToRelativePTSMaxHeap_.push(pts);  // 扩充堆
    } else if (pts < indexToRelativePTSMaxHeap_.top()) {
        indexToRelativePTSMaxHeap_.pop();      // 替换小于当前最大值的 PTS
        indexToRelativePTSMaxHeap_.push(pts);
    }
    indexToRelativePTSFrameCount_++;
}
```

**E18 — `RelativePTSToIndexProcess()` 二分顺查（ffmpeg_demuxer_plugin.cpp:3545）：**
```cpp
void FFmpegDemuxerPlugin::RelativePTSToIndexProcess(int64_t pts, int64_t absolutePTS)
{
    // 在已知 PTS 范围内用二分搜索找对应 Index
    // 维护 relativePTSToIndexPTSMin_ / PTSMax_ / LeftDiff_ / RightDiff_ 边界
}
```

**E19 — `PTSAndIndexConvertSwitchProcess()` 模式分发（ffmpeg_demuxer_plugin.cpp:3504）：**
```cpp
void FFmpegDemuxerPlugin::PTSAndIndexConvertSwitchProcess(
    IndexAndPTSConvertMode mode, int64_t pts, int64_t absolutePTS, uint32_t index, int64_t dts)
{
    switch (mode) {
        case GET_FIRST_PTS:           // 获取首个 PTS 基准
            absolutePTSIndexZero_ = pts;
            break;
        case INDEX_TO_RELATIVEPTS:    // Index → 相对 PTS（逆查，用 MaxHeap）
            IndexToRelativePTSProcess(pts, index);
            break;
        case RELATIVEPTS_TO_INDEX:    // 相对 PTS → Index（顺查，用二分）
            RelativePTSToIndexProcess(pts, absolutePTS);
            break;
        case GET_ALL_FRAME_PTS:      // 收集所有帧 PTS 构建索引
            pts2DtsMap_.emplace(pts - minPts_, dts - minPts_);
            break;
    }
}
```

**E20 — `pts2DtsMap_` B 帧 PTS 补偿：**
```cpp
// 在收集帧时记录 PTS 与 DTS 的差值，用于 B 帧补偿
// pts2DtsMap_[pts - minPts_] = dts - minPts_
// 使得 Seek 时可以正确还原 DTS 和显示时间 PTS
pts2DtsMap_.emplace(pts - minPts_, dts - minPts_);
```

---

## 六、HDR 元数据解析（ParseHEVCMetadataInfo 六步判定）

**E21 — `ParseHEVCMetadataInfo()` 调用链（ffmpeg_demuxer_plugin.cpp:2731）：**
```cpp
void FFmpegDemuxerPlugin::ParseHEVCMetadataInfo(const AVStream& avStream, Meta& format)
{
    HevcParseFormat parse;
    MultiStreamParserManager::ParseMetadataInfo(avStream.index, streamParsers_, parse);
    FFmpegFormatHelper::ParseHevcInfo(*formatContext_, avStream, parse, format);
}
```

**E22 — HDR 六步判定（ffmpeg_format_helper.cpp）：**

通过 `FFmpegFormatHelper::ParseHevcInfo()` 实现六步 HDR 判定：

1. **H.265 流专用**：仅对 HEVC 流生效
2. **色彩矩阵非 BT.2020 → NONE**
3. **ITU_T_T35 前缀 SEI 判定**：
   - `COUNTRY_CODE=0xB5` + `PROVIDER_CODE=0x04` + `PROVIDER_ORIENTED_CODE=0x05` → **HDR_VIVID**（CUVA）
   - `COUNTRY_CODE=0xB5` + `PROVIDER_CODE=0x3C` → **HDR10**
4. **文件 Box 判定**：
   - 存在 CUVV Box → **HDR_VIVID**
   - 存在 DVCC/DVVC/DVH1 Box → **HDR10**
5. **COLOR_TRANSFER_CHARACTERISTIC 判定**：
   - `TRANSFER_CHARACTERISTIC=PQ` → **HDR10**
   - `TRANSFER_CHARACTERISTIC=HLG` → **HLG**
6. **否则 → NONE**（SDR 或非标准 HDR）

**E23 — 关键映射表（ffmpeg_format_helper.cpp:55）：**
```cpp
static std::map<VideoStreamType, std::string> g_hevcProfileMap = {
    { VideoStreamType::HEVC, "HEVC" },
    { VideoStreamType::VVC,  "VVC" }
};
// 用于 HEVCProfile 提取
```

---

## 七、BitstreamFilter 码流格式转换

FFmpegDemuxerPlugin 在读取 AVPacket 后执行 AnnexB ↔ AVCC 转换，使得输出码流符合 MediaCodec 解码器要求。

**E24 — `ConvertAvcToAnnexb()` 转换（ffmpeg_demuxer_plugin.cpp:767）：**
```cpp
Status FFmpegDemuxerPlugin::ConvertAvcToAnnexb(AVPacket& pkt)
{
    if (avbsfContexts_.count(streamIndex) == 0) return Status::OK;
    auto bsFilter = avbsfContexts_[streamIndex];
    return av_bsf_send_packet(bsFilter, &pkt) == 0 &&
           av_bsf_receive_packet(bsFilter, &pkt) == 0 ? Status::OK : Status::ERROR;
}
```

**E25 — BitstreamFilter 表（ffmpeg_demuxer_plugin.cpp:168）：**
```cpp
static const std::map<AVCodecID, std::string> g_bitstreamFilterMap = {
    { AV_CODEC_ID_H264, "h264_mp4toannexb" },  // MP4 → AnnexB
    { AV_CODEC_ID_HEVC, "hevc_mp4toannexb" },   // MP4 → AnnexB
};
```

---

## 八、ReferenceParserManager dlopen GOP 索引

FFmpegDemuxerPlugin 支持通过 `ReferenceParserManager` dlopen 加载 GOP 索引插件，用于快速 Seek 到关键帧位置。

**E26 — `ParserRefInit()` GOP 索引初始化（ffmpeg_demuxer_plugin.cpp:2710）：**
```cpp
Status FFmpegDemuxerPlugin::ParserRefInit()
{
    referenceParser_ = ReferenceParserManager::Create();
    FALSE_RETURN_V(referenceParser_ != nullptr, Status::ERROR_INVALID_OPERATION);
    return referenceParser_->Init(parserRefIoContext_.dataSource, formatContext_.get());
}
```

**E27 — GOP 索引 Seek（ffmpeg_demuxer_plugin.cpp:2880）：**
```cpp
Status ParserRefInfo() override;
Status ParserRefCheckVideoValid(const AVStream *videoStream);
Status UpdateParserGopId(int32_t iFramePosSize);
Status SelectProGopId();
void ParserBoxInfo();
AVStream *GetVideoStream();
std::vector<uint32_t> IFramePos_;  // I-Frame 位置列表
```

---

## 九、与 S68/S76/S134 关联

| 关联记忆 | 关系 |
|---------|------|
| **S68** | FFmpegDemuxerPlugin 总览，包含 25+ 容器格式支持、AVIOContext 三回调 |
| **S76** | FFmpegDemuxerPlugin 封装层，av_read_frame 管线、FFmpegFormatHelper 类型转换 |
| **S134** | FFmpegDemuxerPlugin 高级特性（BitstreamFilter/ReadAhead/HDR/PTS 索引）深度分析 |
| **S192** | **本体深度**：AVIOContext 三回调源码 + FFmpegReadLoop 异步读线程 + SOFT/HARD LIMIT 缓存控制 + PTS-Index 双互转（MaxHeap+二分）+ HDR 六步判定 + ReferenceParserManager dlopen GOP 索引 |
| **S79** | MPEG4DemuxerPlugin 原生 MP4 解析（rank=100），与 FFmpegDemuxerPlugin（rank=50）双轨并行 |
| **S41** | DemuxerFilter Filter 层封装，调用 FFmpegDemuxerPlugin |
| **S75** | MediaDemuxer 六组件核心引擎 |

---

## 十、关键源码路径

```
services/media_engine/plugins/demuxer/ffmpeg_demuxer/
├── ffmpeg_demuxer_plugin.cpp    4129行  主插件逻辑
├── ffmpeg_demuxer_plugin.h      601行   类定义+嵌套结构体
├── ffmpeg_demuxer_thread.cpp    891行   异步读线程 AVReadPacket
├── ffmpeg_format_helper.cpp     1367行   类型转换器
├── ffmpeg_format_helper.h       100行
├── avpacket_wrapper.h            87行
└── avpacket_memory.h             47行
```

---

## 十一、DFX 日志标签

```cpp
#define MEDIA_PLUGIN
#define HST_LOG_TAG "FfmpegDemuxerPlugin"
constexpr int64_t LOG_INTERVAL_MS = 2000;  // 2s
constexpr uint32_t LOG_MAX_COUNT = 10;     // 最多记录 10 次
```

Dump 功能支持三种模式（DUMP_READAT_INPUT / DUMP_AVPACKET_OUTPUT / DUMP_AVBUFFER_OUTPUT），可通过 `dumpMode_` 控制，仅在 BUILD_ENG_VERSION 生效。

---

## 十二、FLV 特殊处理

**E28 — Live FLV 快速探测（ffmpeg_demuxer_plugin.cpp:145）：**
```cpp
const int64_t LIVE_FLV_PROBE_SIZE = 100 * 1024 * 2;  // 200KB
// 对于直播 FLV，仅探测前 200KB 即可确定格式，加速首帧出图
```

**E29 — RM 流特殊 Seek（`SeekToRmKeyFrame`，ffmpeg_demuxer_plugin.h:215）：**
```cpp
Status SeekToRmKeyFrame(int trackIndex, int64_t seekTime,
    int64_t ffTime, SeekMode mode, int64_t& realSeekTime);
```

---

*最后更新：2026-05-25T21:25 Builder 生成草案，待审批*