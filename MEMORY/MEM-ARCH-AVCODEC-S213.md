---
id: MEM-ARCH-AVCODEC-S213
title: "AVCodec FFmpeg Adapter Common 工具链 + DFX 四工具支柱——ffmpeg_utils/ffmpeg_convert/ffmpeg_converter/hdi_codec/stream_parser_manager 五组件与HiSysEvent/XCollie/Trace/Dump四大DFX支柱"
status: draft
ticket_id: S213
scope: "AVCodec, FFmpeg, Adapter, Common, Utils, DFX, HiSysEvent, XCollie, Trace, Dump, Resample, ColorSpace, ChannelLayout, SwrContext, SwsContext"
关联场景: "新需求开发/问题定位/FFmpeg集成/DFX监控"
关联记忆: "S125(FFmpegDecoder)/S130(FFmpegAdapterCommon)/S115(DFX四大支柱)/S77(DFX子系统)/S145(S181)"
生成时间: "2026-06-05T09:20"
来源: "GitCode GitCode仓库源码探索 2026-06-05"
---

# S213：AVCodec FFmpeg Adapter Common 工具链 + DFX 四工具支柱

## 主题

AVCodec FFmpeg Adapter 通用工具链（ffmpeg_utils / ffmpeg_convert / ffmpeg_converter / hdi_codec / stream_parser_manager 五组件 1685 行）与 services/dfx 四工具支柱（HiSysEvent / XCollie / AVCodecTrace / AVCodecDfxComponent）构成的**工具层+DFX监控层**联合架构。

## 架构分层

```
┌─────────────────────────────────────────────────────────────┐
│  应用层 / Filter层                                            │
├─────────────────────────────────────────────────────────────┤
│  FFmpeg Adapter Common 工具链（五组件）                          │
│  ffmpeg_utils · ffmpeg_convert · ffmpeg_converter            │
│  hdi_codec · stream_parser_manager                           │
├─────────────────────────────────────────────────────────────┤
│  services/dfx 四工具支柱                                      │
│  HiSysEvent · XCollie · AVCodecTrace · AVCodecDfxComponent   │
├─────────────────────────────────────────────────────────────┤
│  libavcodec / libavutil / libswresample / libswscale (FFmpeg) │
└─────────────────────────────────────────────────────────────┘
```

## Code Evidence

### 1. FFmpeg Adapter Common 五组件目录结构

**Evidence**: GitCode `services/media_engine/plugins/ffmpeg_adapter/common/` 目录文件列表

```
ffmpeg_convert.cpp · ffmpeg_convert.h
ffmpeg_converter.cpp · ffmpeg_converter.h
ffmpeg_utils.cpp · ffmpeg_utils.h
hdi_codec.cpp · hdi_codec.h
stream_parser_manager.cpp · stream_parser_manager.h
```

最新提交（2026-06）：
- `ffmpeg_utils.cpp`: "add audio vivid for flv" (cailei24, 1 month ago)
- `ffmpeg_convert.cpp`: "Modify avcodec to adapt to the upgrade of ffmpeg" (zzm_gitcode, 5 months ago)
- `hdi_codec.cpp`: "fix hdi log" (lintaicheng, 14 days ago)
- `stream_parser_manager.cpp`: "avCodecContext_ check" (zhou412, 4 months ago)

---

### 2. Resample 重采样器（ffmpeg_convert.h + ffmpeg_convert.cpp）

**Evidence**: `ffmpeg_convert.h` 头文件全量代码

```cpp
// ffmpeg_convert.h
struct ResamplePara {
    uint32_t channels{2};           // 2: STEREO
    uint32_t sampleRate{0};
    uint32_t bitsPerSample{0};
    AVChannelLayout channelLayout;
    AVSampleFormat srcFfFmt{AV_SAMPLE_FMT_NONE};
    uint32_t destSamplesPerFrame{0};
    AVSampleFormat destFmt{AV_SAMPLE_FMT_S16};
};

class Resample {
public:
    Status Init(const ResamplePara &resamplePara);
    Status InitSwrContext(const ResamplePara &resamplePara);
    Status Convert(const uint8_t *srcBuffer, const size_t srcLength,
                  uint8_t *&destBuffer, size_t &destLength);
    Status ConvertFrame(AVFrame *outputFrame, const AVFrame *inputFrame);
    uint32_t GetSampleOffset();
private:
    ResamplePara resamplePara_{};
    uint32_t sampleOffset_ = 0;
    std::shared_ptr<SwrContext> swrCtx_{nullptr};  // FFmpeg SwrContext封装
};
```

**关键依赖**:
- `#include "libavcodec/avcodec.h"`
- `#include "libavutil/channel_layout.h"`
- `#include "libavutil/error.h"`
- `#include "libavutil/frame.h"`
- `#include "libavutil/pixdesc.h"`
- `#include "libavutil/pixfmt.h"`
- `#include "libswresample/swresample.h"`
- `#include "libswscale/swscale.h"`

**Evidence**: `converter.cpp`（services/media_engine/plugins/demuxer/common/）含 18+ 声道布局映射表：

```cpp
const std::vector<std::pair<AudioChannelLayout, uint64_t>> g_toFFMPEGChannelLayout = {
    {AudioChannelLayout::MONO, AV_CH_LAYOUT_MONO},
    {AudioChannelLayout::STEREO, AV_CH_LAYOUT_STEREO},
    {AudioChannelLayout::CH_2POINT1, AV_CH_LAYOUT_2POINT1},
    // ... 共 27 种声道布局映射
    {AudioChannelLayout::HEXADECAGONAL, AV_CH_LAYOUT_HEXADECAGONAL},
    {AudioChannelLayout::STEREO_DOWNMIX, AV_CH_LAYOUT_STEREO_DOWNMIX},
};
```

---

### 3. AVCodecDfxComponent 日志标签组件（services/dfx/include/avcodec_dfx_component.h）

**Evidence**: GitCode 源码 `avcodec_dfx_component.h` 全量代码（2025 Huawei）

```cpp
class AVCodecDfxComponent {
public:
    AVCodecDfxComponent();
    ~AVCodecDfxComponent();
    void SetTag(const std::string &str);
    const std::string &GetTag();
    std::atomic<const char *> tag_;   // 原子标签

private:
    std::string tagContent_ = "";
};

std::string CreateVideoLogTag(const OHOS::Media::Meta &meta);
```

**职责**: 为每个 Codec 实例创建唯一 LogTag，用于 DFX 日志追踪和过滤。

---

### 4. AVCodecXCollie 看门狗定时器（services/dfx/include/avcodec_xcollie.h）

**Evidence**: GitCode 源码 `avcodec_xcollie.h` 全量代码（2023 Huawei）

```cpp
class AVCodecXCollie {
public:
    static AVCodecXCollie &GetInstance();
    int32_t SetTimer(const std::string &name, bool recovery, bool dumpLog,
                     uint32_t timeout,
                     std::function<void(void *)> callback);
    int32_t SetInterfaceTimer(const std::string &name, bool isService,
                              bool recovery, uint32_t timeout);
    void CancelTimer(int32_t timerId);
    int32_t Dump(int32_t fd);
    constexpr static uint32_t timerTimeout = 10;  // 默认10秒超时

private:
    struct TimerInfo {
        std::string name;
        std::time_t startTime;
        uint32_t timeout;
    };
    std::shared_mutex mutex_;
    std::map<int32_t, std::shared_ptr<TimerInfo>> dfxDumper_;
    std::atomic<bool> destroyed_{false};
};
```

**RAII 包装器**（自动取消定时器）：

```cpp
class AVCodecXcollieTimer {
public:
    AVCodecXcollieTimer(const std::string &name, bool recovery, bool dumpLog,
                        uint32_t timeout, std::function<void(void *)> callback)
    {
        index_ = AVCodecXCollie::GetInstance().SetTimer(name, recovery, dumpLog, timeout, callback);
    };
    ~AVCodecXcollieTimer() { AVCodecXCollie::GetInstance().CancelTimer(index_); }
};

#define COLLIE_LISTEN(statement, args...) \
    { AVCodecXcollieInterfaceTimer xCollie(args); statement; }
#define CLIENT_COLLIE_LISTEN(statement, name) \
    { AVCodecXcollieInterfaceTimer xCollie(name, false, false, 30); statement; }
```

---

### 5. HiSysEvent 系统事件（services/dfx/include/avcodec_sysevent.h）

**Evidence**: GitCode 源码 `avcodec_sysevent.h`（2023 Huawei）

```cpp
enum class FaultType : int32_t {
    FAULT_TYPE_INVALID = -1,
    FAULT_TYPE_FREEZE = 0,
    FAULT_TYPE_CRASH,
    FAULT_TYPE_INNER_ERROR,
    FAULT_TYPE_END,
};

enum class DfxSourceType : int8_t {
    NONE = 0,
    DASHVOD, HTTPVOD, HLSVOD,
    FMP4VOD, FMP4LIVE, HLSLIVE, HTTPLIVE, DASHLIVE,
};

struct CodecDfxInfo {
    pid_t clientPid;
    uid_t clientUid;
    int32_t codecInstanceId;
    std::string codecName;
    std::string codecIsVendor;
    std::string codecMode;
    int64_t encoderBitRate;
    int32_t videoWidth;
    int32_t videoHeight;
    double videoFrameRate;
    std::string videoPixelFormat;
    int32_t audioChannelCount;
    int32_t audioSampleRate;
};

struct SourceStatisticsReportInfo {
    std::string appName_;
    int8_t sourceType_;
    std::string sourceUri_;
    uint32_t playStrategyDuration_;
    double playStrateBufferDurationForPlaying_;
    int32_t bitRate_;
    uint32_t videoStreamCnt_;
    uint32_t audioStreamCnt_;
    uint32_t subtitleCnt_;
    std::string ca_;
};
```

**事件写入函数**:
- `FaultEventWrite(FaultType, msg, module)`
- `CodecStartEventWrite(CodecDfxInfo&)`
- `CodecStopEventWrite(clientPid, clientUid, codecInstanceId)`
- `FaultDemuxerEventWrite(DemuxerFaultInfo&)`
- `StreamAppPackageNameEventWrite(...)`

---

### 6. AVCodecTrace 链路追踪（services/dfx/include/avcodec_trace.h）

**Evidence**: GitCode 源码 `avcodec_trace.h`（2023 Huawei）

```cpp
#define AVCODEC_SYNC_TRACE AVCODEC_SYNC_CUSTOM_TRACE(HITRACE_LEVEL_INFO, "%s", __FUNCTION__)
#define AVCODEC_FUNC_TRACE_WITH_TAG       \
    AVCODEC_SYNC_CUSTOM_TRACE_WITH_TAG(HITRACE_LEVEL_INFO, "", "%s", __FUNCTION__)
#define AVCODEC_FUNC_TRACE_WITH_TAG_CLIENT \
    AVCODEC_SYNC_CUSTOM_TRACE_WITH_TAG(HITRACE_LEVEL_INFO, "", "%s:C", __FUNCTION__)
#define AVCODEC_FUNC_TRACE_WITH_TAG_SERVER \
    AVCODEC_SYNC_CUSTOM_TRACE_WITH_TAG(HITRACE_LEVEL_INFO, "", "%s:S", __FUNCTION__)

class AVCodecTrace : public NoCopyable {
public:
    AVCodecTrace(const std::string& funcName, HiTraceOutputLevel level = HITRACE_LEVEL_INFO);
    ~AVCodecTrace() { FinishTraceEx(level_, HITRACE_TAG_ZMEDIA); }

    static void TraceBegin(const std::string& funcName, int32_t taskId, HiTraceOutputLevel level);
    static void TraceEnd(const std::string& funcName, int32_t taskId, HiTraceOutputLevel level);
    static void CounterTrace(const std::string& varName, int32_t val, HiTraceOutputLevel level);
};
```

---

### 7. TimeRangeManager Seek范围管理（services/media_engine/plugins/demuxer/common/）

**Evidence**: GitCode 源码 `time_range_manager.cpp`（2025-2026 Huawei）

```cpp
class TimeRangeManager {
public:
    bool IsInTimeRanges(const int64_t targetTs, TimeRange &timeRange);
    void AddTimeRange(const TimeRange &range);

private:
    void ReduceRanges();  // 超过maxEntries_时稀疏化（等间隔采样）
    std::map<TimeRange, TimeRange> timeRanges_;  // 有序map，TimeRange作key
    int32_t maxEntries_ = 64;  // 默认最大条目数
};
```

**AddTimeRange 合并算法**：区间有重叠时自动合并（start_ts取小，end_ts取大），超出 maxEntries_ 时按 IDX_INTERVAL=2 等间隔稀疏化。

---

## 架构要点

### FFmpeg Adapter Common 五组件职责

| 组件 | 职责 | 关键FFmpeg类型 |
|------|------|---------------|
| ffmpeg_utils | MIME↔CodecId映射、NALU起始码查找、色域矩阵转换 | avcodec_find_encoder_by_name |
| ffmpeg_convert | Resample重采样+Scale缩放+Format转换 | SwrContext/SwsContext |
| ffmpeg_converter | 通用格式转换封装（色域/声道/分辨率） | libav* |
| hdi_codec | Codec HDI抽象接口层（3.0→4.0升级） | HdiCodec |
| stream_parser_manager | 流式解析管理器，dlopen加载HEVC/VVC插件 | StreamParser |

### DFX 四工具支柱

| 工具 | 职责 | 关键接口 |
|------|------|---------|
| HiSysEvent | 故障/行为/统计三类事件上报 | FaultEventWrite/CodecStartEventWrite |
| XCollie | 接口超时看门狗（默认10s，自动取消） | SetTimer/CancelTimer/RAII包装器 |
| AVCodecTrace | HiTrace链路追踪，支持异步Begin/End | TraceBegin/TraceEnd/CounterTrace |
| AVCodecDfxComponent | Codec实例LogTag管理 | SetTag/GetTag/CreateVideoLogTag |

### 关联关系

```
S213
 ├── S130/S125/S145/S181 (FFmpegAdapter Common工具链)
 ├── S115/S77/S82/S30   (DFX四工具支柱)
 └── S125/S132/S158     (编解码插件共享Resample/ColorSpace/ChannelLayout)
```

## 状态

- [ ] 待审批（pending_approval）
- [ ] 草案（draft）