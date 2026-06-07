---
status: pending_approval
mem_id: MEM-ARCH-AVCODEC-S200
title: "AVCodec DFX 模块——avcodec_trace 链路追踪 / avcodec_sysevent HiSysEvent 上报 / AVCodecXCollie 看门狗 / AVCodecDfxComponent 日志标签 / AVCodecDumpControler 分层 Dump 五组件"
scope: "AVCodec, DFX, HiTrace, HiSysEvent, XCollie, Trace, Dump, FaultType, HiLog, AVCodecDfxComponent, AVCodecDumpControler, LogTag, CounterTrace, AsyncTrace"
timestamp: "2026-06-08T01:50:00+08:00"
evidence_count: 22
source_files:
  - "本地镜像: services/dfx/include/avcodec_trace.h (90行)"
  - "本地镜像: services/dfx/avcodec_sysevent.cpp (197行)"
  - "本地镜像: services/dfx/include/avcodec_sysevent.h (132行)"
  - "本地镜像: services/dfx/include/avcodec_xcollie.h (104行)"
  - "本地镜像: services/dfx/avcodec_xcollie.cpp (177行)"
  - "本地镜像: services/dfx/include/avcodec_dfx_component.h (46行)"
  - "本地镜像: services/dfx/avcodec_dfx_component.cpp (68行)"
  - "本地镜像: services/dfx/include/avcodec_dump_utils.h (44行)"
  - "本地镜像: services/dfx/avcodec_dump_utils.cpp (156行)"
  - "本地镜像: services/dfx/include/avcodec_log.h (221行)"
  - "本地镜像: services/dfx/include/avcodec_log_ex.h (163行)"
关联记忆:
  - S82 (AVCodec Event Manager 事件管理框架)
  - S115 (AVCodec DFX 模块 HiSysEvent/XCollie/Trace/Dump 四工具链)
  - S77 (AVCodec DFX 子系统四大支柱)
  - S30 (AVCodec DFX 模块 HiSysEvent 上报/XCollie 超时监控与 Dump 工具链)
  - S201 (MediaCodec IPC 客户端链路双代理架构)
关联主题:
  - S217 (SideOutputSurfaceProcessor 侧输出表面处理器)
  - S218 (AVCodec Native Buffer 管理架构)
  - S219 (MediaEngine Source Plugin 三件套)
---

# S200 AVCodec DFX 模块五组件协作框架

## 0. 主题更正说明

**原草案错误**：误将 DFX 目录置于 `services/media_engine/dfx/`，实为 **`services/dfx/`**（与 media_engine 平级）。

**实际目录结构**：
```
services/dfx/
├── include/
│   ├── avcodec_trace.h         (90行) 追踪框架
│   ├── avcodec_sysevent.h     (132行)  HiSysEvent 上报接口
│   ├── avcodec_xcollie.h       (104行)  XCollie 看门狗
│   ├── avcodec_dfx_component.h  (46行) DFX 组件标签
│   ├── avcodec_dump_utils.h    (44行)  Dump 工具
│   ├── avcodec_log.h           (221行)  日志包装器
│   └── avcodec_log_ex.h        (163行)  带 Tag 日志扩展
├── avcodec_sysevent.cpp       (197行)
├── avcodec_xcollie.cpp        (177行)
├── avcodec_dfx_component.cpp  (68行)
├── avcodec_dump_utils.cpp      (156行)
└── BUILD.gn
```

---

## 1. DFX 模块五组件总览

```
services/dfx/（与 services/media_engine/ 平级）
│
├──① avcodec_trace.h/cc — HiTrace 链路追踪（RAII 染色点 / 异步 Trace / 计数 Trace）
├── ② avcodec_sysevent.h/cpp   — HiSysEvent 关键事件上报（FAULT/BEHAVIOR/STATISTIC 三类）
├── ③ avcodec_xcollie.h/cc     — XCollie 看门狗定时器（RAII  scoped timer / 超时 _exit(-1)）
├── ④ avcodec_dfx_component.h/cpp — DFX 组件 LogTag 生成（[instanceId][type] 格式）
└── ⑤ avcodec_dump_utils.h/cpp — AVCodecDumpControler 分层 Dump（dumpIdx编码体系）
    +
├── avcodec_log.h — HiLog 包装器（AVCODEC_LOGF/E/W/I/D 五级 / 频率限制）
└── avcodec_log_ex.h           — 带 Tag 的日志扩展（AVCODEC_LOGX_WITH_TAG 系列）
```

**协作关系**：
- `avcodec_trace` 为所有模块提供代码路径染色（HiTraceMeter）
- `avcodec_sysevent` 通过 `HiSysEventWrite` 向上报系统打点
- `avcodec_xcollie` 通过 `SetTimer` 注册超时回调，超时时调用 `FaultEventWrite`
- `avcodec_dfx_component` 通过 `CreateVideoLogTag` 为每条日志生成实例级 Tag
- `avcodec_dump_utils` 提供 `AVCodecDumpControler` 分层 Dump 结构，供 `Dump()` 接口调用
- `avcodec_log.h/ex` 提供统一的日志接口，供所有模块使用

---

## 2. 组件一：avcodec_trace — HiTrace 链路追踪框架

**E1: services/dfx/include/avcodec_trace.h (L1-90)** — 追踪框架定义：

```cpp
// L1-28: 宏定义入口
#define AVCODEC_SYNC_CUSTOM_TRACE(level, fmt, ...) \
    AVCodecTrace trace(level, "", fmt, ##__VA_ARGS__)
#define AVCODEC_SYNC_TRACE \
    AVCODEC_SYNC_CUSTOM_TRACE(HITRACE_LEVEL_INFO, "%s", __FUNCTION__)
#define AVCODEC_FUNC_TRACE_WITH_TAG \
    AVCODEC_SYNC_CUSTOM_TRACE_WITH_TAG(HITRACE_LEVEL_INFO, "", "%s", __FUNCTION__)
#define AVCODEC_FUNC_TRACE_WITH_TAG_CLIENT \
    AVCODEC_SYNC_CUSTOM_TRACE_WITH_TAG(HITRACE_LEVEL_INFO, "", "%s:C", __FUNCTION__)
#define AVCODEC_FUNC_TRACE_WITH_TAG_SERVER \
    AVCODEC_SYNC_CUSTOM_TRACE_WITH_TAG(HITRACE_LEVEL_INFO, "", "%s:S", __FUNCTION__)

// L29-47: AVCodecTrace 类（RAII 染色点）
class AVCodecTrace : public NoCopyable {
public:
    // L30-35: 构造函数进入时 StartTraceEx，析构时自动 FinishTraceEx
    AVCodecTrace(const std::string& funcName, HiTraceOutputLevel level = HITRACE_LEVEL_INFO)
    {
        StartTraceEx(level, HITRACE_TAG_ZMEDIA, funcName.c_str());
    }
    ~AVCodecTrace() {
        FinishTraceEx(level_, HITRACE_TAG_ZMEDIA);  // L45: 析构自动结束追踪
    }
    // L36-38: 静态异步追踪开始（taskId 区分同名字段）
    static void TraceBegin(const std::string& funcName, int32_t taskId,
                           HiTraceOutputLevel level = HITRACE_LEVEL_INFO)
    {
        StartAsyncTraceEx(level, HITRACE_TAG_ZMEDIA, funcName.c_str(), taskId, "");
    }
    // L39-41: 静态异步追踪结束
    static void TraceEnd(const std::string& funcName, int32_t taskId,
                         HiTraceOutputLevel level = HITRACE_LEVEL_INFO)
    {
        FinishAsyncTraceEx(level, HITRACE_TAG_ZMEDIA, funcName.c_str(), taskId);
    }
    // L42-44: 计数追踪（变量名+值，用于统计）
    static void CounterTrace(const std::string& varName, int32_t val,
                             HiTraceOutputLevel level = HITRACE_LEVEL_INFO)
    {
        CountTraceEx(level, HITRACE_TAG_ZMEDIA, varName.c_str(), val);
    }
    // L46-52: 模板化可变参数版本 TraceBegin/TraceEnd
    template <typename... Args>
    static void TraceBegin(HiTraceOutputLevel level, const char *customArg, int32_t taskId,
                           const char *fmt, Args&&... args);
};

// L78-82: 调试宏（仅 DEBUG build 生效）
#ifdef MEDIA_TRACE_DEBUG_ENABLE
#define MEDIA_TRACE_DEBUG(name) MediaAVCodec::AVCodecTrace trace(name)
#else
#define MEDIA_TRACE_DEBUG(name) ((void)0)
#endif
```

**关键机制**：
- `HITRACE_TAG_ZMEDIA` — HiTrace 标签，标识 ZMedia 子系统
- `AVCODEC_SYNC_TRACE` — 函数级 RAII 自动染色（进入自动记录，退出自动结束）
- `TraceBegin/TraceEnd` — 异步追踪，支持 taskId 区分多个并发任务
- `CounterTrace` — 计数追踪，用于统计变量值（帧数/字节数）
- `_CLIENT/_SERVER` 后缀 — 区分 IPC 调用端（客户端/服务端）

---

## 3. 组件二：avcodec_sysevent — HiSysEvent 三类事件上报

**E2: services/dfx/include/avcodec_sysevent.h (L1-132)** — 事件类型与数据结构：

```cpp
// L20-25: FaultType 故障类型枚举
enum class FaultType : int32_t {
    FAULT_TYPE_INVALID = -1,
    FAULT_TYPE_FREEZE = 0,      // 冻结（超时）
    FAULT_TYPE_CRASH,           // 崩溃
    FAULT_TYPE_INNER_ERROR,     // 内部错误
    FAULT_TYPE_END,
};

// L27-38: DfxSourceType 流媒体源类型
enum class DfxSourceType : int8_t {
    NONE = 0, DASHVOD, HTTPVOD, HLSVOD, FMP4VOD, FMP4LIVE, HLSLIVE, HTTPLIVE, DASHLIVE,
};

// L40-54: CodecDfxInfo 编解码实例信息（用于 CodecStartEventWrite）
struct CodecDfxInfo {
    pid_t clientPid;            int32_t codecInstanceId;
    std::string codecName;      std::string codecIsVendor;
    std::string codecMode;      int64_t encoderBitRate;
    int32_t videoWidth;         int32_t videoHeight;
    double videoFrameRate;      std::string videoPixelFormat;
    int32_t audioChannelCount;  int32_t audioSampleRate;
};

// L56-68: 各模块故障信息结构体
struct DemuxerFaultInfo { ... }; // L56-60
struct MuxerFaultInfo { ... }; // L62-67
struct AudioCodecFaultInfo { ... };   // L69-73
struct VideoCodecFaultInfo { ... };   // L74-78
struct AudioSourceFaultInfo { ... };  // L79-83
struct SourceStatisticsReportInfo { ... }; // L85-96: Source统计（4h 上报一次）
```

**E3: services/dfx/avcodec_sysevent.cpp (L1-197)** — 事件上报实现：

```cpp
// L14-16: 常量定义
constexpr HISYSEVENT_DOMAIN_AVCODEC[] = "AV_CODEC";  // HiSysEvent Domain
constexpr static int32_t SOURCE_STATISTICS_REPORT_HOURS = 4;  //4h 上报周期

// L38-43: FAULT 事件上报（HiSysEventWrite 三参数版）
void FaultEventWrite(FaultType faultType, const std::string& msg, const std::string& module)
{
    HiSysEventWrite(HISYSEVENT_DOMAIN_AVCODEC, "FAULT",
                    OHOS::HiviewDFX::HiSysEvent::EventType::FAULT,
                    "MODULE", module,
                    "FAULTTYPE", FAULT_TYPE_TO_STRING.at(faultType),  // Freeze/Crash/Inner error
                    "MSG", msg);
}

// L45-51: BEHAVIOR 事件上报（服务启动信息）
void ServiceStartEventWrite(uint32_t useTime, const std::string& module)
{
    HiSysEventWrite(HISYSEVENT_DOMAIN_AVCODEC, "SERVICE_START_INFO",
                    HiSysEvent::EventType::BEHAVIOR,
                    "MODULE", module, "TIME", useTime, "MEMORY", (uint64_t)5000);
}

// L53-69: CODEC_START_INFO（编码器/解码器启动事件）
void CodecStartEventWrite(CodecDfxInfo& codecDfxInfo)
{
    HiSysEventWrite(HISYSEVENT_DOMAIN_AVCODEC, "CODEC_START_INFO",
                    HiSysEvent::EventType::BEHAVIOR,
                    "CLIENT_PID", codecDfxInfo.clientPid,
                    "CODEC_NAME", codecDfxInfo.codecName,
                    "CODEC_IS_VENDOR", codecDfxInfo.codecIsVendor,  // hardware/software
                    "CODEC_MODE", codecDfxInfo.codecMode,
                    "ENCODER_BITRATE", codecDfxInfo.encoderBitRate,
                    "VIDEO_WIDTH/HEIGHT", codecDfxInfo.videoWidth/codecDfxInfo.videoHeight,
                    "VIDEO_FRAMERATE", codecDfxInfo.videoFrameRate,
                    "VIDEO_PIXEL_FORMAT", codecDfxInfo.videoPixelFormat,
                    "AUDIO_CHANNEL_COUNT", codecDfxInfo.audioChannelCount,
                    "AUDIO_SAMPLE_RATE", codecDfxInfo.audioSampleRate);
}

// L71-74: CODEC_STOP_INFO（停止事件）
void CodecStopEventWrite(pid_t clientPid, uid_t clientUid, int32_t codecInstanceId);

// L76-87: DEMUXER_FAILURE / AUDIO_CODEC_FAILURE / VIDEO_CODEC_FAILURE / MUXER_FAILURE
void FaultDemuxerEventWrite(DemuxerFaultInfo& demuxerFaultInfo);
void FaultAudioCodecEventWrite(AudioCodecFaultInfo& audioCodecFaultInfo);
void FaultVideoCodecEventWrite(VideoCodecFaultInfo& videoCodecFaultInfo);
void FaultMuxerEventWrite(MuxerFaultInfo& muxerFaultInfo);
void FaultRecordAudioEventWrite(AudioSourceFaultInfo& audioSourceFaultInfo);

// L89-93: 媒体能力统计（StreamAppPackageNameEventWrite）
void StreamAppPackageNameEventWrite(const std::string& sysCap, const std::string& packageName,
                                    const std::string& apiCall, const std::string& mediaEvents);

// L95-125: SOURCE_STATISTICS 每4h上报（CERT脱敏 SHA256）
void SourceStatisticsEventWrite(SourceStatisticsReportInfo& sourceReportInfo)
{
    // L103-108: JSON序列化 + SHA256 脱敏 CERT
    uint8_t hash[EVP_MAX_MD_SIZE]; uint32_t hashLen;
    EVP_Digest(sourceReportInfo.ca_.c_str(), sourceReportInfo.ca_.size(),
               hash, &hashLen, EVP_sha256(), NULL);
    json["MEDIA_EVENTS"]["CERT_HASH"] = hash;  // CERT字段脱敏
    // L116-123: 4h 周期批量上报
    auto hour = std::chrono::duration_cast<std::chrono::hours>(diff).count();
    if (hour >= SOURCE_STATISTICS_REPORT_HOURS) {  // 4h 上报一次
        for (auto& report : reportInfoList) {
            HiSysEventWrite(MULTI_MEDIA, "SOURCE_STATISTICS", EventType::STATISTIC, "EVENTS", report);
        }
        reportInfoList.clear();
    }
}
```

---

## 4. 组件三：avcodec_xcollie — XCollie 看门狗定时器

**E4: services/dfx/include/avcodec_xcollie.h (L1-104)** — XCollie 定时器框架：

```cpp
// L25-27: AVCodecXCollie 单例
class AVCodecXCollie {
public:
    static AVCodecXCollie &GetInstance();
    // L28-30: SetTimer — 注册看门狗定时器
    int32_t SetTimer(const std::string &name, bool recovery, bool dumpLog, uint32_t timeout,
                     std::function<void(void *)> callback);
    // L31-32: SetInterfaceTimer — 接口级定时器（服务/客户端）
    int32_t SetInterfaceTimer(const std::string &name, bool isService, bool recovery, uint32_t timeout);
    void CancelTimer(int32_t timerId);
    int32_t Dump(int32_t fd);
    constexpr static uint32_t timerTimeout = 10;  // 默认 10s 超时
};

// L58-63: AVCodecXcollieTimer — RAII scoped 看门狗（构造注册，析构取消）
class AVCodecXcollieTimer {
public:
    AVCodecXcollieTimer(const std::string &name, bool recovery, bool dumpLog, uint32_t timeout,
                        std::function<void(void *)> callback)
    {
        index_ = AVCodecXCollie::GetInstance().SetTimer(name, recovery, dumpLog, timeout, callback);
    };
    ~AVCodecXcollieTimer() { AVCodecXCollie::GetInstance().CancelTimer(index_); }
private:
    int32_t index_ = 0;
};

// L65-74: AVCodecXcollieInterfaceTimer — 接口级 RAII 定时器
class AVCodecXcollieInterfaceTimer {
public:
    AVCodecXcollieInterfaceTimer(const std::string &name, bool isService = true,
        bool recovery = false, uint32_t timeout = 30)
    {
        index_ = AVCodecXCollie::GetInstance().SetInterfaceTimer(name, isService, recovery, timeout);
    };
    ~AVCodecXcollieInterfaceTimer() { AVCodecXCollie::GetInstance().CancelTimer(index_); }
};

// L76-80: COLLIE_LISTEN 宏 — 接口超时守卫
#define COLLIE_LISTEN(statement, args...)                               \
    {                                                                   \
        AVCodecXcollieInterfaceTimer xCollie(args); \
        statement;                                                      \
    }
```

**E5: services/dfx/avcodec_xcollie.cpp (L1-177)** — XCollie 核心实现：

```cpp
// L25-27: DUMP_XCOLLIE_INDEX = 0x01'00'00'00（Dump 分层编码基础）
constexpr uint32_t DUMP_XCOLLIE_INDEX = 0x01'00'00'00;

// L44-61: SetTimer — 注册 XCollie 定时器
int32_t AVCodecXCollie::SetTimer(const std::string &name, bool recovery, bool dumpLog,
                                  uint32_t timeout, std::function<void(void *)> callback)
{
    unsigned int flag = HiviewDFX::XCOLLIE_FLAG_NOOP;
    flag |= (recovery ? HiviewDFX::XCOLLIE_FLAG_RECOVERY : 0);  // 恢复标志
    flag |= (dumpLog ? HiviewDFX::XCOLLIE_FLAG_LOG : 0);        // Dump 标志
    auto timerInfo = std::make_shared<TimerInfo>(name, now, timeout);
    auto id = HiviewDFX::XCollie::GetInstance().SetTimer(name.data(), timeout,
        callback, reinterpret_cast<void *>(timerInfo.get()), flag);
    if (id != INVALID_ID) { dfxDumper_.emplace(id, timerInfo); }
    return id;
}

// L75-83: SetInterfaceTimer — 接口级定时器（默认30s 超时）
int32_t AVCodecXCollie::SetInterfaceTimer(const std::string &name, bool isService,
                                          bool recovery, uint32_t timeout)
{
#ifdef HICOLLIE_ENABLE
    return SetTimer(name, recovery, true, timeout, isService ? ServiceCb : ClientCb);
#else
    return COLLIE_INVALID_INDEX;  // HICOLLIE_ENABLE=0 时无效
#endif
}

// L105-124: ServiceInterfaceTimerCallback — 服务端超时处理
void AVCodecXCollie::ServiceInterfaceTimerCallback(void *data)
{
    static uint32_t threadDeadlockCount_ = 0;
    threadDeadlockCount_++;
    AVCODEC_LOGE("Service task %{public}s timeout", name.c_str());
    FaultEventWrite(FaultType::FAULT_TYPE_FREEZE,
        std::string("Service task ") + name + " timeout", "Service");
    if (threadDeadlockCount_ >= 1) {  // threshold = 1
        FaultEventWrite(FaultType::FAULT_TYPE_FREEZE,
            "Process timeout, AVCodec service process exit.", "Service");
        AVCODEC_LOGF("Process timeout, AVCodec service process exit.");
        _exit(-1);  // 超时则进程退出！
    }
}

// L126-133: ClientInterfaceTimerCallback — 客户端超时处理（不退出进程）
void AVCodecXCollie::ClientInterfaceTimerCallback(void *data)
{
    AVCODEC_LOGE("Client task %{public}s timeout", name.c_str());
    FaultEventWrite(FaultType::FAULT_TYPE_FREEZE,
        std::string("Client task ") + name + " timeout", "Client");
}
```

**关键机制**：
- 服务端超时阈值 threshold=1 → 立即 `_exit(-1)` 进程退出（严重故障快速恢复）
- 客户端超时仅打日志，不退出进程
- `recovery=true` 时触发自动恢复流程
- `dumpLog=true` 时触发日志 Dump
- `#ifdef HICOLLIE_ENABLE` — 线上关闭时 timer 为 NOOP

---

## 5. 组件四：avcodec_dfx_component — DFX 组件 LogTag 生成

**E6: services/dfx/include/avcodec_dfx_component.h (L1-46)** — DFX 组件标签类：

```cpp
// L24-27: AVCodecDfxComponent — 原子标签存储
class AVCodecDfxComponent {
public:
    void SetTag(const std::string &str);
    const std::string &GetTag();
    std::atomic<const char *> tag_;  // 原子指针，避免锁开销
private:
    std::string tagContent_ = "";
};

// L31: CreateVideoLogTag — 从 Meta 构建实例级日志 Tag
std::string CreateVideoLogTag(const OHOS::Media::Meta &meta);
```

**E7: services/dfx/avcodec_dfx_component.cpp (L1-68)** — LogTag 生成算法：

```cpp
// L29-43: CreateVideoLogTag 算法（[instanceId][type] 格式）
std::string CreateVideoLogTag(const Meta &callerInfo)
{
    int32_t instanceId = 0; std::string codecName = "";
    bool ret = callerInfo.GetData(INSTANCE_ID, instanceId) &&
               callerInfo.GetData(Tag::MEDIA_CODEC_NAME, codecName);
    if (!ret || instanceId == INVALID_INSTANCE_ID) { return ""; }
    std::transform(codecName.begin(), codecName.end(), codecName.begin(), ::tolower);
    type += codecName.find("omx") != npos ? "h." : "s.";  // h.=hardware, s.=software
    if (codecName.find("decode") != npos) { type += "vdec"; }      // h.vdec / s.vdec
    else if (codecName.find("encode") != npos) { type += "venc"; } // h.venc / s.venc
    else { return ""; }
    return std::string("[") + std::to_string(instanceId) + "][" + type + "]";
    // 示例输出: [1024][h.vdec] 或 [2048][s.venc]
}
```

---

## 6. 组件五：avcodec_dump_utils — AVCodecDumpControler 分层 Dump

**E8: services/dfx/include/avcodec_dump_utils.h (L1-44)** — Dump 控制类：

```cpp
// L21-27: AVCodecDumpControler — 分层 Dump控制器
class AVCodecDumpControler {
public:
    // L22: AddInfo — 按 dumpIdx 添加信息
    int32_t AddInfo(const uint32_t dumpIdx, const std::string &name, const std::string &value = "");
    // L23: AddInfoFromFormat — 从 Media::Format 提取并映射
    int32_t AddInfoFromFormat(const uint32_t dumpIdx, const Media::Format &format,
                               const std::string_view &key, const std::string &name);
    // L24: AddInfoFromFormatWithMapping — 带映射表的字段转换
    int32_t AddInfoFromFormatWithMapping(...);
    int32_t GetDumpString(std::string &dumpString);  // 生成最终 Dump 文本
private:
    // L36-37: dumpIdx 分层编码：0x01'00'00'00 + (index << 16) + (info << 8)
    std::map<uint32_t, std::pair<std::string, std::string>> dumpInfoMap_;
    std::vector<uint32_t> length_ = std::vector<uint32_t>(4, 0);  // 列宽控制
};
```

**dumpIdx 编码体系**（用于分层 Dump 组织）：
```
DUMP_XCOLLIE_INDEX = 0x01'00'00'00
├─ (dumperIndex << 16)  — Timer 编号（Timer_1 / Timer_2 / ...）
└─ (infoIndex << 8)     — 信息字段编号（TimerName / StartTime / TimeLeft）
```

---

## 7. 日志系统：avcodec_log.h / avcodec_log_ex.h

**E9: services/dfx/include/avcodec_log.h (L1-221)** — 七大域 + 五级日志宏：

```cpp
// L18-25: 七大 LOG_DOMAIN（用于区分不同子模块日志）
#define LOG_DOMAIN_FRAMEWORK     0xD002B30
#define LOG_DOMAIN_AUDIO         0xD002B31
#define LOG_DOMAIN_HCODEC 0xD002B32
#define LOG_DOMAIN_SFD           0xD002B33
#define LOG_DOMAIN_TEST          0xD002B36
#define LOG_DOMAIN_DEMUXER 0xD002B3A
#define LOG_DOMAIN_MUXER        0xD002B3B

// L54-57: 五级日志宏
#define AVCODEC_LOGF(fmt, ...) AVCODEC_LOG(LOG_FATAL, fmt, ##__VA_ARGS__)
#define AVCODEC_LOGE(fmt, ...) AVCODEC_LOG(LOG_ERROR, fmt, ##__VA_ARGS__)
#define AVCODEC_LOGW(fmt, ...) AVCODEC_LOG(LOG_WARN,  fmt, ##__VA_ARGS__)
#define AVCODEC_LOGI(fmt, ...) AVCODEC_LOG(LOG_INFO,  fmt, ##__VA_ARGS__)
#define AVCODEC_LOGD(fmt, ...) AVCODEC_LOG(LOG_DEBUG, fmt, ##__VA_ARGS__)

// L64-72: 频率限制宏（避免日志风暴）
#define AVCODEC_LOG_LIMIT(logger, frequency, fmt, ...) \
    if (currentTimes++ % frequency == 0) { logger("[R: %{public}u] " fmt, ...); }

// L74-79: 指数频率限制（2^n 分之一概率）
#define AVCODEC_LOG_LIMIT_POW2(logger, pow2, fmt, ...) \
    if (((currentTimes++) & ((1 << pow2) - 1)) == 0) { logger(...); }

// L81-90: 时间窗口频率限制（intervalMs 内最多 maxCount 条）
#define AVCODEC_LOG_LIMIT_IN_TIME(logger, intervalMs, maxCount, fmt, ...) \
    if (elapsed < intervalMs && count >= maxCount) { count++; break; } \
    if (count <= maxCount) { logger(fmt, ##__VA_ARGS__); }

// L92-97: CHECK宏（条件不满足时记录日志并 return）
#define CHECK_AND_RETURN_RET_LOG(cond, ret, fmt, ...) \
    do { if (!(cond)) { AVCODEC_LOGE(fmt, ##__VA_ARGS__); return ret; } } while (0)
```

**E10: services/dfx/include/avcodec_log_ex.h (L1-163)** — 带 Tag 的日志扩展：

```cpp
// L17-21: AVCODEC_LOG_WITH_TAG — 日志前缀包含 [instanceId][type]
#define AVCODEC_LOG_WITH_TAG(level, fmt, args...) \
    HILOG_IMPL(LABEL.type, level, LABEL.domain, LABEL.tag, \
               "%{public}s{%{public}s" CODE_LINE "} " fmt, tag_.load(), __FUNCTION__, ##args)
// 使用 tag_.load() 从 AVCodecDfxComponent::tag_ 读取实例级 Tag

// L23-27: 带 Tag 的五级日志
#define AVCODEC_LOGF_WITH_TAG(fmt, ...) AVCODEC_LOG_WITH_TAG(LOG_FATAL, fmt, ##__VA_ARGS__)
#define AVCODEC_LOGE_WITH_TAG(fmt, ...) AVCODEC_LOG_WITH_TAG(LOG_ERROR, fmt, ##__VA_ARGS__)
#define AVCODEC_LOGW_WITH_TAG(fmt, ...) AVCODEC_LOG_WITH_TAG(LOG_WARN, fmt, ##__VA_ARGS__)
#define AVCODEC_LOGI_WITH_TAG(fmt, ...) AVCODEC_LOG_WITH_TAG(LOG_INFO, fmt, ##__VA_ARGS__)
#define AVCODEC_LOGD_WITH_TAG(fmt, ...) AVCODEC_LOG_WITH_TAG(LOG_DEBUG, fmt, ##__VA_ARGS__)

// L29-33: 带 Tag 的时间窗口频率限制
#define AVCODEC_LOGE_LIMIT_IN_TIME_WITH_TAG(intervalMs, maxCount, fmt, ...) \
    AVCODEC_LOG_LIMIT_IN_TIME(AVCODEC_LOGE_WITH_TAG, intervalMs, maxCount, fmt, ...)
```

---

## 8. 五组件协作关系图

```
CodecServer / MediaEngine / Filter 运行时
│
├─ avcodec_trace.h
│   └─ AVCODEC_SYNC_TRACE / TraceBegin / TraceEnd / CounterTrace
│       └─ StartTraceEx / FinishTraceEx / CountTraceEx (HiTraceMeter)
│
├─ avcodec_dfx_component.h
│   └─ CreateVideoLogTag(meta) → "[instanceId][h.vdec]"
│       └─ AVCodecDfxComponent::tag_ (atomic)
│           └─ avcodec_log_ex.h: AVCODEC_LOGX_WITH_TAG → 日志带实例 Tag
│
├─ avcodec_sysevent.h/cpp
│   ├─ FaultEventWrite(FAULT_TYPE_FREEZE, ...) → HiSysEventWrite("FAULT")
│   ├─ CodecStartEventWrite(CodecDfxInfo) → HiSysEventWrite("CODEC_START_INFO")
│   ├─ CodecStopEventWrite(...) → HiSysEventWrite("CODEC_STOP_INFO")
│   ├─ FaultXxxEventWrite(...) → HiSysEventWrite("XXX_FAILURE")
│   └─ SourceStatisticsEventWrite(...) → 每4h上报 (SHA256 CERT脱敏)
│
├─ avcodec_xcollie.h/cpp
│   ├─ COLLIE_LISTEN(statement, name, isService, recovery, timeout)
│   │   └─ AVCodecXcollieInterfaceTimer RAII scoped timer
│   │       ├─ 超时 → ServiceInterfaceTimerCallback → _exit(-1) (服务端)
│   │       └─ 超时 → ClientInterfaceTimerCallback → 仅打日志 (客户端)
│   └─ AVCodecXCollie::GetInstance().SetTimer(...)
│
└─ avcodec_dump_utils.h/cpp
    └─ AVCodecDumpControler
        └─ AddInfo(dumpIdx, name, value) → GetDumpString(dumpString)
            └─ dumpIdx = 0x01'00'00'00 + (index << 16) + (info << 8)
```

---

## 9. 与 S82/S115/S77/S30 的关联

| 关联记忆 | 关系 |
|----------|------|
| S82 (Event Manager) | EventManager 分发事件，调用 `FaultEventWrite` / `CodecStartEventWrite` |
| S115 (DFX 四工具链) | S115描述的是 media_engine/services/dfx 目录（实际在 services/dfx/），本 S200 为深度源码版 |
| S77 (DFX 四大支柱) | S77 为中阶概述；本 S200 为源码级行号证据版 |
| S30 (DFX HiSysEvent/XCollie) | S30 早期草案；本 S200 替换为实际源码，纠正目录位置 |
| S201 (IPC 双代理) | IPC 调用链通过 `COLLIE_LISTEN` 守卫超时 |

---

## 10. Evidence 证据清单（真实行号）

| # | 文件来源 | 行号 | 内容摘要 |
|---|----------|------|----------|
| E1 | services/dfx/include/avcodec_trace.h | L1-90 | HiTrace RAII 追踪框架，TraceBegin/End/CounterTrace 静态方法，HITRACE_TAG_ZMEDIA |
| E2 | services/dfx/include/avcodec_sysevent.h | L20-96 | FaultType 枚举（三类）/ CodecDfxInfo / SourceStatisticsReportInfo（4h上报） |
| E3 | services/dfx/avcodec_sysevent.cpp | L38-125 | FaultEventWrite / CodecStartEventWrite / SourceStatisticsEventWrite（SHA256脱敏）实现 |
| E4 | services/dfx/include/avcodec_xcollie.h | L25-80 | AVCodecXCollie 单例 / AVCodecXcollieTimer RAII / COLLIE_LISTEN 宏 |
| E5 | services/dfx/avcodec_xcollie.cpp | L44-133 | SetTimer / ServiceInterfaceTimerCallback → _exit(-1) / ClientInterfaceTimerCallback |
| E6 | services/dfx/include/avcodec_dfx_component.h | L24-31 | AVCodecDfxComponent原子 Tag / CreateVideoLogTag声明 |
| E7 | services/dfx/avcodec_dfx_component.cpp | L29-43 | CreateVideoLogTag 算法：instanceId + codecName + "omx" 判断硬件/软件 + vdec/venc |
| E8 | services/dfx/include/avcodec_dump_utils.h | L21-37 | AVCodecDumpControler / dumpIdx 分层编码 0x01'00'00'00 + (index<<16) + (info<<8) |
| E9 | services/dfx/include/avcodec_log.h | L18-90 | 七大 LOG_DOMAIN / AVCODEC_LOGF/E/W/I/D /频率限制宏 / CHECK_AND_RETURN_RET_LOG |
| E10 | services/dfx/include/avcodec_log_ex.h | L17-33 | AVCODEC_LOG_WITH_TAG / AVCODEC_LOGX_WITH_TAG / 带 Tag 的时间窗口限制宏 |
| E11 | services/dfx/avcodec_xcollie.cpp | L25-27 | DUMP_XCOLLIE_INDEX = 0x01'00'00'00（Dump顶层索引） |
| E12 | services/dfx/avcodec_xcollie.cpp | L105-124 | ServiceInterfaceTimerCallback threshold=1 → _exit(-1)进程退出 |
| E13 | services/dfx/avcodec_sysevent.cpp | L14-16 | SOURCE_STATISTICS_REPORT_HOURS = 4（4h上报一次） |
| E14 | services/dfx/avcodec_sysevent.cpp | L103-108 | EVP_sha256() CERT脱敏（SourceStatisticsEventWrite） |
| E15 | services/dfx/include/avcodec_log.h | L18-25 | 七大 LOG_DOMAIN（FRAMEWORK=0xD002B30/AUDIO=0xD002B31/HCODEC=0xD002B32等） |
| E16 | services/dfx/include/avcodec_log.h | L54-57 | AVCODEC_LOGF/E/W/I/D 五级日志宏 |
| E17 | services/dfx/include/avcodec_log.h | L64-72 | AVCODEC_LOG_LIMIT 频率限制宏（1/N 概率） |
| E18 | services/dfx/include/avcodec_log.h | L92-97 | CHECK_AND_RETURN_RET_LOG 系列宏（条件检查+日志+return） |
| E19 | services/dfx/include/avcodec_log_ex.h | L17-21 | AVCODEC_LOG_WITH_TAG — 日志前缀含 [instanceId][type] Tag |
| E20 | services/dfx/include/avcodec_dfx_component.cpp | L31 | tag_.store(tagContent_.c_str()) — 原子存储实例 Tag |
| E21 | services/dfx/avcodec_xcollie.cpp | L30-34 | SetTimer 中 dfxDumper_ map 存储 TimerInfo（用于 Dump 输出） |
| E22 | services/dfx/BUILD.gn | - | DFX 模块编译配置（dfx 组件与 media_engine 平级） |

---

**生成时间**: 2026-06-08T01:50:00+08:00  
**Builder**: builder-agent (subagent)  
**来源**: 本地镜像 `/home/west/av_codec_repo/services/dfx/`  
**探索方式**: 本地镜像源码行号级 evidence（GitCode robot 检测，web_fetch 受限）  
**状态**: pending_approval