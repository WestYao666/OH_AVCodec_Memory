---
status: pending_approval
mem_id: MEM-ARCH-AVCODEC-S213
title: "AVCodec DFX 五组件协作框架——avcodec_trace / avcodec_sysevent / avcodec_dfx_component / avcodec_xcollie / avcodec_dump_utils 五组件协同架构"
scope: "AVCodec, DFX, HiSysEvent, HiTrace, XCollie, Dump, Trace, FaultEvent, HiLog, Statistics, InstanceInfo, RAII, Singleton, Timer, EventManager"
timestamp: "2026-06-05T06:21:00+08:00"
evidence_count: 18
source_files:
  - "/home/west/av_codec_repo/services/dfx/include/avcodec_trace.h (94行)"
  - "/home/west/av_codec_repo/services/dfx/avcodec_dfx_component.cpp (70行)"
  - "/home/west/av_codec_repo/services/dfx/include/avcodec_dfx_component.h (58行)"
  - "/home/west/av_codec_repo/services/dfx/include/avcodec_sysevent.h (95行)"
  - "/home/west/av_codec_repo/services/dfx/avcodec_sysevent.cpp (198行)"
  - "/home/west/av_codec_repo/services/dfx/include/avcodec_xcollie.h (113行)"
  - "/home/west/av_codec_repo/services/dfx/avcodec_xcollie.cpp (175行)"
  - "/home/west/av_codec_repo/services/dfx/include/avcodec_dump_utils.h (57行)"
  - "/home/west/av_codec_repo/services/dfx/avcodec_dump_utils.cpp (126行)"
  - "/home/west/av_codec_repo/services/services/common/instance_info.h (93行)"
关联记忆:
  - S82 (AVCodec Event Manager事件管理框架)
  - S200 (AVCodec Memory子系统 DFX五层架构草案)
  - S137 (SA Codec IPC框架)
  - S83 (Native C API总览)
  - S55 (CodecCallback回调链路)
---

# S213 AVCodec DFX 五组件协作框架

## 1. 架构概述

AVCodec DFX 模块位于 `services/dfx/`，由五个独立组件构成，形成完整的可观测性保障体系：

| 组件 | 文件 | 职责 | 关键特性 |
|------|------|------|---------|
| avcodec_trace | avcodec_trace.h (94行) | HiTrace链路追踪 + ScopeGuard RAII | HITRACE_TAG_ZMEDIA + StartTraceEx/FinishTraceEx |
| avcodec_sysevent | avcodec_sysevent.h/cpp (95+198行) | HiSysEvent事件打点 | FAULT/BEHAVIOR/STATISTIC三类事件 |
| avcodec_dfx_component | avcodec_dfx_component.h/cpp (58+70行) | 日志Tag生成器 | CreateVideoLogTag + tag_原子变量 |
| avcodec_xcollie | avcodec_xcollie.h/cpp (113+175行) | XCollie超时看门狗 | SetTimer/CancelTimer + RAII包装器 |
| avcodec_dump_utils | avcodec_dump_utils.h/cpp (57+126行) | Dump工具链 | AVCodecDumpControler + dumpIdx编码 |

```
DFX Layer (services/dfx/)
├── avcodec_trace.h (94行)           — HiTrace链路染色 + ScopeGuard RAII析构自动FinishTrace
├── avcodec_sysevent.h (95行)        — HiSysEvent声明 + FaultType枚举 + CodecDfxInfo等结构体
├── avcodec_sysevent.cpp (198行)     — HiSysEventWrite实现 + FAULT_TYPE_TO_STRING映射
├── avcodec_dfx_component.h (58行)   — AVCodecDfxComponent日志Tag组件 + CreateVideoLogTag声明
├── avcodec_dfx_component.cpp (70行) — CreateVideoLogTag实现 + tag_原子变量
├── avcodec_xcollie.h (113行)        — AVCodecXCollie单例 + SetTimer/CancelTimer + RAII包装器
├── avcodec_xcollie.cpp (175行)      — XCollie定时器实现 + DUMP_XCOLLIE_INDEX编码
├── avcodec_dump_utils.h (57行)      — AVCodecDumpControler dump工具 + dumpInfoMap_
└── avcodec_dump_utils.cpp (126行)  — Dump字符串拼接实现
```

## 2. 组件详细分析

### 2.1 avcodec_trace — HiTrace链路追踪

avcodec_trace.h 是 HiTrace Meter 封装的轻量级 RAII 工具类，通过析构函数自动调用 `FinishTraceEx` 实现零开销的函数级染色：

**E1: avcodec_trace.h L15-L50** — AVCodecTrace RAII 类 + 宏定义
```cpp
class AVCodecTrace : public NoCopyable {
public:
    AVCodecTrace(const std::string& funcName, HiTraceOutputLevel level = HITRACE_LEVEL_INFO) : level_(level)
    {
        StartTraceEx(level, HITRACE_TAG_ZMEDIA, funcName.c_str()); // L27: 构造时自动开始追踪
    }
    ~AVCodecTrace() {
        FinishTraceEx(level_, HITRACE_TAG_ZMEDIA);                 // L42: RAII析构自动结束追踪
    }
    static void TraceBegin(const std::string& funcName, int32_t taskId, HiTraceOutputLevel level = HITRACE_LEVEL_INFO) {
        StartAsyncTraceEx(level, HITRACE_TAG_ZMEDIA, funcName.c_str(), taskId, ""); // L30: 异步追踪开始
    }
    static void TraceEnd(const std::string& funcName, int32_t taskId, HiTraceOutputLevel level = HITRACE_LEVEL_INFO) {
        FinishAsyncTraceEx(level, HITRACE_TAG_ZMEDIA, funcName.c_str(), taskId);    // L34: 异步追踪结束
    }
    static void CounterTrace(const std::string& varName, int32_t val, HiTraceOutputLevel level = HITRACE_LEVEL_INFO) {
        CountTraceEx(level, HITRACE_TAG_ZMEDIA, varName.c_str(), val);             // L38: 计数追踪
    }
    template <typename... Args>
    AVCodecTrace(HiTraceOutputLevel level, const char *customArg, const char *fmt, Args&&... args) : level_(level) {
        StartTraceArgsEx(level, HITRACE_TAG_ZMEDIA, customArg, fmt, args...);      // L41: 变参模板追踪
    }
};
```

**E2: avcodec_trace.h L19-L23** — 便捷宏定义
```cpp
#define AVCODEC_SYNC_CUSTOM_TRACE(level, fmt, ...) AVCodecTrace trace(level, "", fmt, ##__VA_ARGS__)
#define AVCODEC_SYNC_TRACE AVCODEC_SYNC_CUSTOM_TRACE(HITRACE_LEVEL_INFO, "%s", __FUNCTION__)
#define AVCODEC_FUNC_TRACE_WITH_TAG        AVCODEC_SYNC_CUSTOM_TRACE_WITH_TAG(HITRACE_LEVEL_INFO, "", "%s", __FUNCTION__)
```

所有宏均使用 `HITRACE_TAG_ZMEDIA` (L26/L31/L35/L39/L41) 标记 AVCodec 追踪链，便于在 `hitrace` 工具中过滤。

---

### 2.2 avcodec_sysevent — HiSysEvent事件打点框架

avcodec_sysevent.h 声明了完整的 HiSysEvent 体系，包括故障类型枚举、数据结构和打点函数：

**E3: avcodec_sysevent.h L22-L43** — FaultType枚举 + DfxSourceType + CodecDfxInfo
```cpp
enum class FaultType : int32_t {
    FAULT_TYPE_INVALID = -1,
    FAULT_TYPE_FREEZE = 0,
    FAULT_TYPE_CRASH,
    FAULT_TYPE_INNER_ERROR,
    FAULT_TYPE_END,
};

enum class DfxSourceType :int8_t {
    NONE = 0, DASHVOD, HTTPVOD, HLSVOD, FMP4VOD, FMP4LIVE, HLSLIVE, HTTPLIVE, DASHLIVE,
};

struct CodecDfxInfo {
    pid_t clientPid; uid_t clientUid; int32_t codecInstanceId;
    std::string codecName; std::string codecIsVendor; std::string codecMode;
    int64_t encoderBitRate; int32_t videoWidth; int32_t videoHeight;
    double videoFrameRate; std::string videoPixelFormat;
    int32_t audioChannelCount; int32_t audioSampleRate;
}; // L35-L46: 完整Codec实例信息结构体
```

**E4: avcodec_sysevent.h L71-L95** — HiSysEventWrite接口声明
```cpp
void FaultEventWrite(FaultType faultType, const std::string& msg, const std::string& module);
void ServiceStartEventWrite(uint32_t useTime, const std::string& module);
void CodecStartEventWrite(CodecDfxInfo& codecDfxInfo);
void CodecStopEventWrite(pid_t clientPid, uid_t clientUid, int32_t codecInstanceId);
void FaultDemuxerEventWrite(DemuxerFaultInfo& demuxerFaultInfo);
void FaultAudioCodecEventWrite(AudioCodecFaultInfo& audioCodecFaultInfo);
void FaultVideoCodecEventWrite(VideoCodecFaultInfo& videoCodecFaultInfo);
void FaultMuxerEventWrite(MuxerFaultInfo& muxerFaultInfo);
void StreamAppPackageNameEventWrite(...);    // L87: 媒体应用统计上报
void SourceStatisticsEventWrite(SourceStatisticsReportInfo& sourceReportInfo); // L89: 每4h上报
```

**E5: avcodec_sysevent.cpp L48-L50** — 常量定义与事件域
```cpp
constexpr OHOS::HiviewDFX::HiLogLabel LABEL = {LOG_CORE, LOG_DOMAIN_FRAMEWORK, "AVCodecSysEvent"};
constexpr char HISYSEVENT_DOMAIN_AVCODEC[] = "AV_CODEC";
constexpr static int32_t SOURCE_STATISTICS_REPORT_HOURS = 4; // L50: 统计上报周期4小时
```

**E6: avcodec_sysevent.cpp L42-L46** — FAULT_TYPE字符串映射
```cpp
const std::unordered_map<OHOS::MediaAVCodec::FaultType, std::string> FAULT_TYPE_TO_STRING = {
    {OHOS::MediaAVCodec::FaultType::FAULT_TYPE_FREEZE,     "Freeze"},
    {OHOS::MediaAVCodec::FaultType::FAULT_TYPE_CRASH,      "Crash"},
    {OHOS::MediaAVCodec::FaultType::FAULT_TYPE_INNER_ERROR,"Inner error"},
};
```

**E7: avcodec_sysevent.cpp L52-L60** — FaultEventWrite实现
```cpp
void FaultEventWrite(FaultType faultType, const std::string& msg, const std::string& module)
{
    CHECK_AND_RETURN_LOG(faultType >= FaultType::FAULT_TYPE_FREEZE && faultType < FaultType::FAULT_TYPE_END,
        "Invalid fault type: %{public}d", faultType);
    HiSysEventWrite(HISYSEVENT_DOMAIN_AVCODEC, "FAULT",
                    OHOS::HiviewDFX::HiSysEvent::EventType::FAULT,
                    "MODULE", module, "FAULTTYPE", FAULT_TYPE_TO_STRING.at(faultType), "MSG", msg);
}
```

**E8: avcodec_sysevent.cpp L62-L73** — CodecStartEventWrite / CodecStopEventWrite
```cpp
void CodecStartEventWrite(CodecDfxInfo& codecDfxInfo) {
    HiSysEventWrite(HISYSEVENT_DOMAIN_AVCODEC, "CODEC_START_INFO",
                    OHOS::HiviewDFX::HiSysEvent::EventType::BEHAVIOR,
                    "CLIENT_PID", codecDfxInfo.clientPid, "CLIENT_UID", codecDfxInfo.clientUid,
                    "CODEC_INSTANCE_ID", codecDfxInfo.codecInstanceId,
                    "CODEC_NAME", codecDfxInfo.codecName,
                    "CODEC_IS_VENDOR", codecDfxInfo.codecIsVendor,
                    "ENCODER_BITRATE", codecDfxInfo.encoderBitRate, ...);
}
void CodecStopEventWrite(pid_t clientPid, uid_t clientUid, int32_t codecInstanceId) {
    HiSysEventWrite(HISYSEVENT_DOMAIN_AVCODEC, "CODEC_STOP_INFO",
                    OHOS::HiviewDFX::HiSysEvent::EventType::BEHAVIOR,
                    "CLIENT_PID", clientPid, "CLIENT_UID", clientUid, "CODEC_INSTANCE_ID", codecInstanceId);
}
```

---

### 2.3 avcodec_dfx_component — 日志Tag生成器

avcodec_dfx_component.h/cpp 提供进程内统一的日志Tag生成和存储机制：

**E9: avcodec_dfx_component.h L33-L57** — AVCodecDfxComponent类定义
```cpp
class AVCodecDfxComponent {
public:
    AVCodecDfxComponent();
    void SetTag(const std::string &str);
    const std::string &GetTag();
    std::atomic<const char *> tag_;  // L43: 原子指针避免锁竞争
private:
    std::string tagContent_ = "";
};
std::string CreateVideoLogTag(const OHOS::Media::Meta &meta); // L54: 从Meta生成日志Tag
```

**E10: avcodec_dfx_component.cpp L27-L44** — CreateVideoLogTag实现
```cpp
std::string CreateVideoLogTag(const Meta &callerInfo) {
    int32_t instanceId = 0; std::string codecName = "";
    bool ret = callerInfo.GetData(EventInfoExtentedKey::INSTANCE_ID.data(), instanceId) &&
               callerInfo.GetData(Tag::MEDIA_CODEC_NAME, codecName);
    if (!ret || instanceId == INVALID_INSTANCE_ID) { return ""; }
    std::transform(codecName.begin(), codecName.end(), codecName.begin(), ::tolower);
    type += codecName.find("omx") != std::string::npos ? "h." : "s."; // L38: h.=硬件 s.=软件
    if (codecName.find("decode") != std::string::npos) { type += "vdec"; }      // L40: 视频解码
    else if (codecName.find("encode") != std::string::npos) { type += "venc"; } // L42: 视频编码
    return std::string("[") + std::to_string(instanceId) + "][" + type + "]";     // L44: [instanceId][h.vdec]
}
```

---

### 2.4 avcodec_xcollie — XCollie超时看门狗

avcodec_xcollie 是 XCollie 系统服务的 AVCodec 封装，提供超时检测、自动恢复和日志Dump：

**E11: avcodec_xcollie.h L22-L65** — AVCodecXCollie单例 + SetTimer/CancelTimer
```cpp
class AVCodecXCollie {
public:
    static AVCodecXCollie &GetInstance();                                      // L22: 单例访问
    int32_t SetTimer(const std::string &name, bool recovery, bool dumpLog,
                     uint32_t timeout, std::function<void(void *)> callback); // L23: 注册定时器
    int32_t SetInterfaceTimer(const std::string &name, bool isService,
                             bool recovery, uint32_t timeout);                // L25: 接口级定时器
    void CancelTimer(int32_t timerId);                                        // L26: 取消定时器
    int32_t Dump(int32_t fd);                                                 // L27: Dump所有定时器
    constexpr static uint32_t timerTimeout = 10;                               // L28: 默认超时10s
private:
    std::shared_mutex mutex_;                                                  // L32: 读写锁保护dfxDumper_
    std::map<int32_t, std::shared_ptr<TimerInfo>> dfxDumper_;                  // L33: 定时器信息映射
    std::atomic<bool> destroyed_{false};                                       // L34: 析构标记
};
```

**E12: avcodec_xcollie.h L68-L93** — RAII包装器 + COLLIE_LISTEN宏
```cpp
class AVCodecXcollieTimer {  // L68: 普通定时器RAII包装器
public:
    AVCodecXcollieTimer(const std::string &name, bool recovery, bool dumpLog,
                        uint32_t timeout, std::function<void(void *)> callback) {
        index_ = AVCodecXCollie::GetInstance().SetTimer(name, recovery, dumpLog, timeout, callback);
    };
    ~AVCodecXcollieTimer() { AVCodecXCollie::GetInstance().CancelTimer(index_); } // L76: RAII自动Cancel
};

class AVCodecXcollieInterfaceTimer {  // L79: 接口级定时器RAII包装器（默认30s超时）
public:
    AVCodecXcollieInterfaceTimer(const std::string &name, bool isService = true,
                                  bool recovery = false, uint32_t timeout = 30) {
        index_ = AVCodecXCollie::GetInstance().SetInterfaceTimer(name, isService, recovery, timeout);
    };
    ~AVCodecXcollieInterfaceTimer() { AVCodecXCollie::GetInstance().CancelTimer(index_); } // L88: RAII自动Cancel
};

#define COLLIE_LISTEN(statement, args...) \
    { AVCodecXcollieInterfaceTimer xCollie(args); statement; }  // L91: 接口超时监控宏
#define CLIENT_COLLIE_LISTEN(statement, name) \
    { AVCodecXcollieInterfaceTimer xCollie(name, false, false, 30); statement; } // L95: 客户端30s超时
```

**E13: avcodec_xcollie.cpp L28-L35** — DUMP_XCOLLIE_INDEX编码常量
```cpp
constexpr OHOS::HiviewDFX::HiLogLabel LABEL = {LOG_CORE, LOG_DOMAIN_FRAMEWORK, "AVCodecXCollie"};
constexpr uint32_t DUMP_XCOLLIE_INDEX = 0x01'00'00'00;  // L30: XCollie Dump索引编码
constexpr uint8_t DUMP_OFFSET_16 = 16;
constexpr uint8_t DUMP_OFFSET_8 = 8;
constexpr uint64_t COLLIE_INVALID_INDEX = 0;
```

**E14: avcodec_xcollie.cpp L47-L64** — SetTimer实现
```cpp
int32_t AVCodecXCollie::SetTimer(const std::string &name, bool recovery, bool dumpLog,
                                 uint32_t timeout, std::function<void(void *)> callback) {
    unsigned int flag = HiviewDFX::XCOLLIE_FLAG_NOOP;
    flag |= (recovery ? HiviewDFX::XCOLLIE_FLAG_RECOVERY : 0);    // L52: 恢复标志
    flag |= (dumpLog ? HiviewDFX::XCOLLIE_FLAG_LOG : 0);          // L53: Dump日志标志
    auto timerInfo = std::make_shared<TimerInfo>(name, ...);      // L55: 定时器信息
    auto id = HiviewDFX::XCollie::GetInstance().SetTimer(         // L57: 调用XCollie系统服务
        name.data(), timeout, callback, reinterpret_cast<void *>(timerInfo.get()), flag);
    if (id != HiviewDFX::INVALID_ID) { dfxDumper_.emplace(id, timerInfo); } // L59: 登记到映射表
}
```

---

### 2.5 avcodec_dump_utils — Dump工具链

AVCodecDumpControler 负责将 Codec 运行信息格式化为可读 Dump 字符串：

**E15: avcodec_dump_utils.h L35-L57** — AVCodecDumpControler类定义
```cpp
class AVCodecDumpControler {
public:
    int32_t AddInfo(const uint32_t dumpIdx, const std::string &name, const std::string &value = "");
    int32_t AddInfoFromFormat(const uint32_t dumpIdx, const Media::Format &format,
                               const std::string_view &key, const std::string &name);
    int32_t AddInfoFromFormatWithMapping(const uint32_t dumpIdx, const Media::Format &format,
                                         const std::string_view &key, const std::string &name,
                                         std::map<int32_t, const std::string> mapping);
    int32_t GetDumpString(std::string &dumpString);  // L44: 获取格式化Dump字符串
    uint32_t GetSpaceLength(const uint32_t dumpIdx);
    static bool GetValueFromFormat(const Media::Format &format,
                                    const std::string_view &key, std::string &value);
private:
    uint32_t GetLevel(const uint32_t dumpIdx);  // L47: 从dumpIdx解析层级
    std::map<uint32_t, std::pair<std::string, std::string>> dumpInfoMap_; // L48: <dumpIdx, <name, value>>
    std::vector<uint32_t> length_ = std::vector<uint32_t>(4, 0);  // L49: 4级长度记录
};
```

---

### 2.6 instance_info — Codec实例标识体系

**E16: instance_info.h L22-L37** — 实例标识体系核心类型
```cpp
using InstanceId = int32_t;
constexpr pid_t INVALID_PID = -1;
constexpr InstanceId INVALID_INSTANCE_ID = -1;  // L26: 无效实例ID标记

enum class VideoCodecType : int16_t {
    UNKNOWN, DECODER_HARDWARE, DECODER_SOFTWARE, ENCODER_HARDWARE, ENCODER_SOFTWARE, END,
};

struct CallerInfo {
    pid_t pid = -1; uid_t uid = 0; std::string processName = "";  // L32: 调用方信息
};

struct InstanceInfo {
    InstanceId instanceId = INVALID_INSTANCE_ID;  // L36: Codec实例唯一ID
    CallerInfo caller; CallerInfo forwardCaller;
    AVCodecType codecType;
    uint32_t memoryUsage = 0; std::string codecName = "";
    std::time_t codecCreateTime = 0;
    VideoCodecType videoCodecType = VideoCodecType::UNKNOWN;  // L40: 软硬Codec区分
};
```

---


### 2.7 avcodec_log — LOG_DOMAIN六域定义与AVCODEC_LOG宏

**E17: avcodec_log.h L24-L62** — LOG_DOMAIN六域定义 + AVCODEC_LOG宏族 + 频率限制宏
```cpp
#undef  LOG_DOMAIN_FRAMEWORK
#define LOG_DOMAIN_FRAMEWORK     0xD002B30  // L25: 框架域
#undef  LOG_DOMAIN_AUDIO
#define LOG_DOMAIN_AUDIO         0xD002B31  // L27: 音频域
#undef  LOG_DOMAIN_HCODEC
#define LOG_DOMAIN_HCODEC        0xD002B32  // L29: 硬件Codec域
#undef  LOG_DOMAIN_SFD
#define LOG_DOMAIN_SFD           0xD002B33  // L31: 流媒体域
#undef  LOG_DOMAIN_DEMUXER
#define LOG_DOMAIN_DEMUXER       0xD002B3A  // L35: 解封装域
#undef  LOG_DOMAIN_MUXER
#define LOG_DOMAIN_MUXER         0xD002B3B  // L37: 封装域

#define POINTER_MASK 0x00FFFFFF  // L47: 地址脱敏掩码
#define FAKE_POINTER(addr) (POINTER_MASK & reinterpret_cast<uintptr_t>(addr))  // L48: 日志脱敏

#define AVCODEC_LOG(level, fmt, args...)  \
    (void)HILOG_IMPL(LABEL.type, level, LABEL.domain, LABEL.tag,  // L51-53: 核心日志宏
#define AVCODEC_LOGF(fmt, ...) AVCODEC_LOG(LOG_FATAL, fmt, ##__VA_ARGS__)  // L58: FATAL级
#define AVCODEC_LOGE(fmt, ...) AVCODEC_LOG(LOG_ERROR, fmt, ##__VA_ARGS__)  // L59: ERROR级
#define AVCODEC_LOGW(fmt, ...) AVCODEC_LOG(LOG_WARN,  fmt, ##__VA_ARGS__)  // L60: WARN级
#define AVCODEC_LOGI(fmt, ...) AVCODEC_LOG(LOG_INFO,  fmt, ##__VA_ARGS__)  // L61: INFO级
#define AVCODEC_LOGD(fmt, ...) AVCODEC_LOG(LOG_DEBUG, fmt, ##__VA_ARGS__)  // L62: DEBUG级

#define AVCODEC_LOG_LIMIT(logger, frequency, fmt, ...)  // L65: 频率限制日志
#define AVCODEC_LOG_LIMIT_POW2(logger, pow2, fmt, ...)  // L75: 指数退避日志
#define AVCODEC_LOG_LIMIT_IN_TIME(logger, intervalMs, maxCount, fmt, ...)  // L85: 时间窗口日志
```
本地镜像路径：`/home/west/av_codec_repo/services/dfx/include/avcodec_log.h`

---


### 2.8 avcodec_log_ex — AVCODEC_LOG_WITH_TAG带实例Tag日志宏

**E18: avcodec_log_ex.h L22-L149** — AVCODEC_LOG_WITH_TAG + CHECK/EXPECT宏族 + Tag频率限制宏
```cpp
#define AVCODEC_LOG_WITH_TAG(level, fmt, args...)  \
    (void)HILOG_IMPL(LABEL.type, level, LABEL.domain, LABEL.tag,  // L22-24: 带Tag日志宏
#define AVCODEC_LOGF_WITH_TAG(fmt, ...) AVCODEC_LOG_WITH_TAG(LOG_FATAL, fmt, ##__VA_ARGS__)  // L28
#define AVCODEC_LOGE_WITH_TAG(fmt, ...) AVCODEC_LOG_WITH_TAG(LOG_ERROR, fmt, ##__VA_ARGS__)  // L29
#define AVCODEC_LOGW_WITH_TAG(fmt, ...) AVCODEC_LOG_WITH_TAG(LOG_WARN, fmt, ##__VA_ARGS__)  // L30
#define AVCODEC_LOGI_WITH_TAG(fmt, ...) AVCODEC_LOG_WITH_TAG(LOG_INFO, fmt, ##__VA_ARGS__)  // L31
#define AVCODEC_LOGD_WITH_TAG(fmt, ...) AVCODEC_LOG_WITH_TAG(LOG_DEBUG, fmt, ##__VA_ARGS__)  // L32

#define CHECK_AND_RETURN_RET_LOG_WITH_TAG(cond, ret, fmt, ...)  // L43: 条件检查+Tag日志+返回
#define CHECK_AND_RETURN_LOG_WITH_TAG(cond, fmt, ...)  // L123: 条件检查+Tag日志
#define EXPECT_AND_LOGE_WITH_TAG(cond, fmt, ...)  // L88: 断言+Tag Error日志
#define CHECK_AND_RETURN_RET_LOG_LIMIT_IN_TIME_WITH_TAG(cond, ret, intervalMs, maxCount, fmt, ...)  // L149: 时间窗口限制
```
本地镜像路径：`/home/west/av_codec_repo/services/dfx/include/avcodec_log_ex.h`

---

## 3. 五组件协作流程

### 3.1 Codec启动事件链

```
应用层 CreateAVCodec
  → CodecServer::GetSubSystemAbility
    → 创建InstanceInfo (instanceId, caller, codecType)          [E16 instance_info.h]
    → AVCodecXCollie::SetInterfaceTimer (30s超时)                [E12 E14 avcodec_xcollie]
      → COLLIE_LISTEN(statement, name, true, false, 30)          [E12 L91宏]
    → CodecStartEventWrite(codecDfxInfo)                         [E8 avcodec_sysevent.cpp]
      → HiSysEventWrite("AV_CODEC", "CODEC_START_INFO", BEHAVIOR, ...) [E8 L62-73]
    → AVCodecDfxComponent::SetTag(CreateVideoLogTag(meta))        [E10 avcodec_dfx_component.cpp]
      → tagContent_ = "[instanceId][h.vdec]"                     [E10 L44]
    → AVCodecDumpControler::AddInfo(dumpIdx, "codecName", ...)   [E15 avcodec_dump_utils.h]
```

### 3.2 故障事件链

```
Codec异常 (freeze/crash/inner_error)
  → FaultEventWrite(FaultType::FAULT_TYPE_FREEZE, msg, module)   [E7 avcodec_sysevent.cpp]
    → FAULT_TYPE_TO_STRING.at(faultType)                         [E6 L42-46]
    → HiSysEventWrite("AV_CODEC", "FAULT", FAULT, MODULE/FAULTTYPE/MSG) [E7 L52-60]
  → AVCodecXCollie CancelTimer (超时取消)                         [E14 avcodec_xcollie.cpp L26]
  → AVCodecDumpControler::GetDumpString → 输出到fd               [E15 L44]
```

### 3.3 HiTrace追踪链

```
AVCODEC_SYNC_TRACE  // 函数入口宏
  → AVCodecTrace构造 (StartTraceEx + HITRACE_TAG_ZMEDIA)        [E1 avcodec_trace.h L27]
  → 函数体执行
  → ~AVCodecTrace析构 (FinishTraceEx)                          [E1 L42 RAII自动]
```

## 4. 与S82/S200的关系

- **S82 (EventManager)**：EventManager 是更高层的 DFX 事件分发器，内部调用 avcodec_sysevent 的 HiSysEventWrite 接口（E7-E8），管理 StatisticsEventHandler / InstanceMemoryUpdateEventHandler / BackgroundEventHandler 三类处理器
- **S200 (DFX五层架构草案)**：S200 是本草案（S213）的早期版本，基于 GitCode 探索；S213 是基于本地镜像 `/home/west/av_codec_repo/services/dfx/` 的增强版，新增了 E13（DUMP_XCOLLIE_INDEX）、E15（AVCodecDumpControler）、E16（InstanceInfo）的行号级证据

## 5. 关键设计总结

| 设计点 | 证据 | 说明 |
|--------|------|------|
| RAII自动追踪 | E1 L42 | ~AVCodecTrace析构自动FinishTraceEx，无需手动End |
| 原子Tag | E9 L43 | std::atomic<const char*> tag_ 避免锁竞争 |
| RAII定时器 | E12 L76/L88 | 析构自动CancelTimer，防止泄漏 |
| COLLIE_LISTEN宏 | E12 L91 | 零侵入式接口超时监控 |
| DUMP_XCOLLIE_INDEX | E13 L30 | 0x01'00'00'00 编码XCollie Dump类别 |
| HiSysEvent三类 | E5-E8 | FAULT/BEHAVIOR/STATISTIC (STATISTIC每4h上报) |
| CreateVideoLogTag | E10 L38-L44 | 从Meta提取instanceId+codecType生成可读Tag |
| SOURCE_STATISTICS_REPORT_HOURS | E5 L50 | 4h周期统计上报 |