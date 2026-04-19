---
id: MEM-ARCH-AVCODEC-015
title: Codec 错误处理与恢复机制——错误码/HiSysEvent/XCollie 三层联动
type: architecture_fact
status: approved
approved_at: "2026-04-19T22:40:00+08:00"
created_at: 2026-04-19T12:22:00+08:00
updated_at: 2026-04-19T22:40:00+08:00
author: builder-agent
tags: [AVCodec, ErrorHandling, Recovery, DFX, HiSysEvent, XCollie, ErrorCode]
related_scenes: [问题定位, 三方应用, 新需求开发]
scope: [AVCodec, ErrorHandling, DFX]
service_scenario: 问题定位 / 三方应用 / 新需求开发
summary: >
  AVCodec 错误处理采用三层联动机制：
  (1) 错误码层——AVCS_ERR_* 返回值，对应 API 调用层面的同步失败；
  (2) HiSysEvent 层——FaultEventWrite 将严重故障写入持久化系统日志（AV_CODEC domain 和 MULTI_MEDIA domain）；
  (3) XCollie 看门狗层——Timer 超时检测卡死/冻结，Service 侧超时杀进程（_exit(-1)），Client 侧超时仅写事件不杀进程。
  三层各自独立触发，也可联合触发（如 XCollie 超时 → FaultEventWrite + _exit）。
why_it_matters:
 - 问题定位：遇到崩溃/卡死时，知道是哪个层面的防御机制触发的，对症排查
 - 三方应用：理解 AVCS_ERR_* 与 HiSysEvent 的关系，判断是否需要查系统日志
 - 新需求开发：新增 codec 路径时需遵循三层错误处理契约，避免漏写错误码或 fault 事件
 - 故障归因：同一故障可能在多个层面留下痕迹，需要关联分析
---

## 1. 三层联动总览

```
API Call (返回 AVCS_ERR_*)
    │
    ▼
┌─────────────────────────────────────────────┐
│ 层1：错误码层  (avcodec_errors.h)           │
│ 同步返回值：AVCS_ERR_OK / UNKNOWN / ...     │
│ 触发方：API 函数内部主动检查参数/状态        │
└──────────────┬──────────────────────────────┘
               │ 严重故障（freeze/crash/inner_error）
               ▼
┌─────────────────────────────────────────────┐
│ 层2：HiSysEvent 层  (avcodec_sysevent.cpp)  │
│ 异步持久化：AV_CODEC 或 MULTI_MEDIA domain   │
│ 触发方：业务层主动调用 FaultEventWrite()     │
└──────────────┬──────────────────────────────┘
               │
               ▼ (XCollie Timer 超时)
┌─────────────────────────────────────────────┐
│ 层3：XCollie 看门狗  (avcodec_xcollie.cpp)  │
│ 独立计时器：Service 超时杀进程 / Client 仅告警 │
│ 触发方：XCollie 定时器回调（独立于错误码）    │
└─────────────────────────────────────────────┘
```

> Evidence: `services/dfx/avcodec_sysevent.cpp` — FaultEventWrite + 5 个模块故障函数；`services/dfx/avcodec_xcollie.cpp` — Service/Client 超时回调

---

## 2. 层1：错误码层（AVCS_ERR_*）

错误码定义在 `services/dfx/avcodec_errors.h`，所有 AVCodec API 的返回值均遵循此约定。

**核心错误码**：

| 错误码 | 含义 | 触发场景 |
|--------|------|---------|
| `AVCS_ERR_OK` | 成功 | 正常路径 |
| `AVCS_ERR_NO_MEMORY` | 内存不足 | buffer 分配失败 |
| `AVCS_ERR_INVALID_STATE` | 状态非法 | 未初始化时调用 Start |
| `AVCS_ERR_INVALID_PARAM` | 参数非法 | null pointer / 非法值 |
| `AVCS_ERR_UNSUPPORT` | 能力不支持 | 不支持的 codec / format（注意：无 ED 后缀） |
| `AVCS_ERR_UNKNOWN` | 未知错误 | dlopen 失败 / 插件加载失败 |

**错误码使用模式**：

所有 AVCodec API 函数返回 `int32_t`，调用方通过检查返回值判断是否成功：

```cpp
// frameworks/native/avcodec/avcodec_audio_codec_impl.cpp
int32_t AVCodecAudioCodecImpl::Init(AVCodecType type, bool isMimeType, const std::string &name)
{
    codecService_ = AudioCodecServer::Create();
    CHECK_AND_RETURN_RET_LOG(codecService_ != nullptr, AVCS_ERR_UNKNOWN,
        "failed to create codec service");  // ← 返回 AVCS_ERR_UNKNOWN
    return codecService_->Init(type, isMimeType, name, *format.GetMeta(), API_VERSION::API_VERSION_11);
}
```

**CHECK_AND_RETURN_RET_LOG 宏**：错误码路径的标准写法，自动写 HiLog 并返回指定错误码：

```cpp
// services/dfx/include/avcodec_log.h
#define CHECK_AND_RETURN_RET_LOG(cond, ret, fmt, ...)                       \
    do {                                                                    \
        if (!(cond)) {                                                      \
            AVCODEC_LOGE(fmt, ##__VA_ARGS__);                               \
            return ret;                                                     \
        }                                                                   \
    } while (0)
```

**限频日志宏**（高频错误路径避免刷屏）：

```cpp
// services/dfx/include/avcodec_log.h
#define AVCODEC_LOGE_LIMIT(frequency, fmt, ...) \
    AVCODEC_LOG_LIMIT(AVCODEC_LOGE, frequency, fmt, ##__VA_ARGS__)
// 用法：每 100 次才打印一次
AVCODEC_LOGE_LIMIT(100, "codec error occurred");
```

> Evidence: `interfaces/inner_api/native/avcodec_errors.h` — 完整错误码定义（50+错误码，已验证）；`services/dfx/include/avcodec_log.h` — CHECK_AND_RETURN_RET_LOG + 限频宏

---

## 3. 层2：HiSysEvent 层（FaultEventWrite）

HiSysEvent 是系统级持久化日志，即使进程崩溃也能查到。AVCodec 的 HiSysEvent 分两个 domain：

### 3.1 AV_CODEC domain（本地 hisysevent.yaml 定义）

**FaultType 枚举**（`avcodec_sysevent.h`）：

```cpp
enum class FaultType : int32_t {
    FAULT_TYPE_INVALID = -1,
    FAULT_TYPE_FREEZE = 0,   // 超时/卡死
    FAULT_TYPE_CRASH,        // 崩溃
    FAULT_TYPE_INNER_ERROR,  // 内部错误
    FAULT_TYPE_END,
};
```

**FAULT_TYPE_TO_STRING 映射**（`avcodec_sysevent.cpp`）：

```cpp
const std::unordered_map<FaultType, std::string> FAULT_TYPE_TO_STRING = {
    {FAULT_TYPE_FREEZE,      "Freeze"},
    {FAULT_TYPE_CRASH,       "Crash"},
    {FAULT_TYPE_INNER_ERROR, "Inner error"},
};
```

**FaultEventWrite 实现**：

```cpp
// services/dfx/avcodec_sysevent.cpp
void FaultEventWrite(FaultType faultType, const std::string& msg, const std::string& module)
{
    CHECK_AND_RETURN_LOG(faultType >= FaultType::FAULT_TYPE_FREEZE && faultType < FaultType::FAULT_TYPE_END,
        "Invalid fault type: %{public}d", faultType);
    HiSysEventWrite(HISYSEVENT_DOMAIN_AVCODEC, "FAULT",
                    OHOS::HiviewDFX::HiSysEvent::EventType::FAULT,
                    "MODULE", module,
                    "FAULTTYPE", FAULT_TYPE_TO_STRING.at(faultType),
                    "MSG", msg);
}
```

AV_CODEC domain 的事件（`avcodec_sysevent.cpp`）：

| 事件名 | Type | 用途 |
|--------|------|------|
| `FAULT` | FAULT | FREEZE/CRASH/INNER_ERROR |
| `SERVICE_START_INFO` | BEHAVIOR | 服务启动 |
| `CODEC_START_INFO` | BEHAVIOR | codec 实例启动（含完整参数） |
| `CODEC_STOP_INFO` | BEHAVIOR | codec 实例停止 |

### 3.2 MULTI_MEDIA domain（5 类模块故障，不在本地 yaml 定义）

以下 5 类故障走平台 MULTI_MEDIA domain，hisysevent.yaml 无 AVCodec 本地定义：

| 事件名 | Type | 触发函数 |
|--------|------|---------|
| `DEMUXER_FAILURE` | FAULT | `FaultDemuxerEventWrite(DemuxerFaultInfo&)` |
| `AUDIO_CODEC_FAILURE` | FAULT | `FaultAudioCodecEventWrite(AudioCodecFaultInfo&)` |
| `VIDEO_CODEC_FAILURE` | FAULT | `FaultVideoCodecEventWrite(VideoCodecFaultInfo&)` |
| `MUXER_FAILURE` | FAULT | `FaultMuxerEventWrite(MuxerFaultInfo&)` |
| `RECORD_AUDIO_FAILURE` | FAULT | `FaultRecordAudioEventWrite(AudioSourceFaultInfo&)` |

**FaultDemuxerEventWrite 示例**：

```cpp
void FaultDemuxerEventWrite(DemuxerFaultInfo& demuxerFaultInfo)
{
    HiSysEventWrite(OHOS::HiviewDFX::HiSysEvent::Domain::MULTI_MEDIA, "DEMUXER_FAILURE",
                    OHOS::HiviewDFX::HiSysEvent::EventType::FAULT,
                    "APP_NAME",         demuxerFaultInfo.appName,
                    "INSTANCE_ID",      demuxerFaultInfo.instanceId,
                    "CALLER_TYPE",      demuxerFaultInfo.callerType,
                    "SOURCE_TYPE",      demuxerFaultInfo.sourceType,
                    "CONTAINER_FORMAT", demuxerFaultInfo.containerFormat,
                    "STREAM_TYPE",      demuxerFaultInfo.streamType,
                    "ERROR_MESG",       demuxerFaultInfo.errMsg);
}
```

### 3.3 CodecStartEventWrite——最完整的 DFX 信息

```cpp
void CodecStartEventWrite(CodecDfxInfo& codecDfxInfo)
{
    HiSysEventWrite(HISYSEVENT_DOMAIN_AVCODEC, "CODEC_START_INFO",
                    OHOS::HiviewDFX::HiSysEvent::EventType::BEHAVIOR,
                    "CLIENT_PID",           codecDfxInfo.clientPid,
                    "CLIENT_UID",           codecDfxInfo.clientUid,
                    "CODEC_INSTANCE_ID",    codecDfxInfo.codecInstanceId,
                    "CODEC_NAME",           codecDfxInfo.codecName,
                    "CODEC_IS_VENDOR",      codecDfxInfo.codecIsVendor,
                    "CODEC_MODE",           codecDfxInfo.codecMode,
                    "ENCODER_BITRATE",      codecDfxInfo.encoderBitRate,
                    "VIDEO_WIDTH",          codecDfxInfo.videoWidth,
                    "VIDEO_HEIGHT",         codecDfxInfo.videoHeight,
                    "VIDEO_FRAMERATE",      codecDfxInfo.videoFrameRate,
                    "VIDEO_PIXEL_FORMAT",   codecDfxInfo.videoPixelFormat,
                    "AUDIO_CHANNEL_COUNT",  codecDfxInfo.audioChannelCount,
                    "AUDIO_SAMPLE_RATE",    codecDfxInfo.audioSampleRate);
}
```

**关键字段**：
- `CODEC_IS_VENDOR`：区分硬件（true）还是软件（false）codec
- `CODEC_MODE`：软解/硬解/混合模式

> Evidence: `services/dfx/avcodec_sysevent.cpp` — 所有事件写入实现；`services/dfx/include/avcodec_sysevent.h` — 6 个 FaultInfo struct 定义

---

## 4. 层3：XCollie 看门狗（Timer-based Freeze Detection）

XCollie 是独立的计时器系统，不依赖 API 返回值，专门检测"API 调用卡死无响应"的情况。

### 4.1 核心概念

- XCollie 计时器独立于业务逻辑，一旦 SetTimer 开始计时，biz 逻辑必须按时完成
- 超时后触发 callback，biz 逻辑不可控
- Service 侧超时 → 进程退出（_exit(-1)）
- Client 侧超时 → 仅写 HiSysEvent，不杀进程

### 4.2 时间阈值

```cpp
// services/dfx/include/avcodec_xcollie.h
class AVCodecXcollieInterfaceTimer {
public:
    AVCodecXcollieInterfaceTimer(const std::string &name, bool isService = true,
        bool recovery = false, uint32_t timeout = 30)  // ← 默认 30s
    {
        index_ = AVCodecXCollie::GetInstance().SetInterfaceTimer(name, isService, recovery, timeout);
    }
};

// constexpr 默认值（SetTimer）
constexpr static uint32_t timerTimeout = 10;  // ← 默认 10s
```

| Timer 类型 | 默认超时 | 调用场景 |
|-----------|---------|---------|
| `SetTimer` | 10s | 通用 timer |
| `SetInterfaceTimer` (isService=true) | 30s | Service 侧接口 |
| `SetInterfaceTimer` (isService=false) | 30s | Client 侧接口 |

### 4.3 Service 侧超时回调——杀进程

```cpp
// services/dfx/avcodec_xcollie.cpp
void AVCodecXCollie::ServiceInterfaceTimerCallback(void *data)
{
    static uint32_t threadDeadlockCount_ = 0;
    threadDeadlockCount_++;
    std::string name = data != nullptr ? reinterpret_cast<TimerInfo *>(data)->name.c_str() : "";

    AVCODEC_LOGE("Service task %{public}s timeout", name.c_str());
    FaultEventWrite(FaultType::FAULT_TYPE_FREEZE,
        std::string("Service task ") + name + std::string(" timeout"), "Service");

    static constexpr uint32_t threshold = 1; // >= 1 Restart service
    if (threadDeadlockCount_ >= threshold) {
        FaultEventWrite(FaultType::FAULT_TYPE_FREEZE,
            "Process timeout, AVCodec service process exit.", "Service");
        AVCODEC_LOGF("Process timeout, AVCodec service process exit.");
        _exit(-1);  // ← 超时杀进程
    }
}
```

**关键规律**：
- `threadDeadlockCount_` 是 static 变量，跨所有 timer 共享计数
- `threshold = 1`：首次 Service 超时即触发杀进程条件
- `_exit(-1)` 后进程立即终止，无法继续处理任何请求

### 4.4 Client 侧超时回调——仅告警

```cpp
// services/dfx/avcodec_xcollie.cpp
void AVCodecXCollie::ClientInterfaceTimerCallback(void *data)
{
    std::string name = data != nullptr ? reinterpret_cast<TimerInfo *>(data)->name.c_str() : "";
    AVCODEC_LOGE("Client task %{public}s timeout", name.c_str());
    FaultEventWrite(FaultType::FAULT_TYPE_FREEZE,
        std::string("Client task ") + name + std::string(" timeout"), "Client");
    // ← 不杀进程，不调用 _exit
}
```

### 4.5 RAII 便捷宏（COLLIE_LISTEN）

`avcodec_xcollie.h` 提供两个宏简化 timer 管理：

```cpp
// 通用宏：isService=true → Service 侧 timer
#define COLLIE_LISTEN(statement, args...)                               \
    {                                                                   \
        AVCodecXcollieInterfaceTimer xCollie(args);                     \
        statement;                                                      \
    }

// Client 专用宏：isService=false, timeout=30s
#define CLIENT_COLLIE_LISTEN(statement, name)                           \
    {                                                                   \
        AVCodecXcollieInterfaceTimer xCollie(name, false, false, 30);   \
        statement;                                                      \
    }
```

**用法示例**：

```cpp
// Service 侧：默认 30s 超时
COLLIE_LISTEN(someCodecOperation(), "EncodeFrame", true, false, 30);

// Client 侧：30s 超时
CLIENT_COLLIE_LISTEN(someCodecOperation(), "DecodeFrame");
```

Timer 在 `AVCodecXcollieInterfaceTimer` 对象析构时自动 Cancel：

```cpp
// ~AVCodecXcollieInterfaceTimer()
~AVCodecXcollieInterfaceTimer()
{
    AVCodecXCollie::GetInstance().CancelTimer(index_);
}
```

### 4.6 XCollie Dump——查看活跃 Timer

```cpp
// services/dfx/avcodec_xcollie.cpp
int32_t AVCodecXCollie::Dump(int32_t fd)
{
    std::string dumpString = "[AVCodec_XCollie]\n";
    for (const auto &iter : dfxDumper_) {
        // 输出 Timer_N: TimerName / StartTime / TimeLeft
    }
    write(fd, dumpString.c_str(), dumpString.size());
}
```

> Evidence: `services/dfx/include/avcodec_xcollie.h` — timer class 定义 + COLLIE_LISTEN 宏；`services/dfx/avcodec_xcollie.cpp` — Service/Client callback 实现 + Dump 实现

---

## 5. 三层联动场景分析

### 场景1：dlopen 加载插件失败

```
dlopen(so_path) 返回 nullptr
    │
    ▼
CHECK_AND_RETURN_RET_LOG(handle != nullptr, AVCS_ERR_UNKNOWN, "Load codec failed")
    │
    ├─ AVCODEC_LOGE("Load codec failed: %{public}s", libPath_)  // HiLog
    │
    ▼
返回 AVCS_ERR_UNKNOWN  (层1：错误码)
```

**恢复**：调用方收到 AVCS_ERR_UNKNOWN，检查 libPath_ 是否正确配置

### 场景2：API 调用超时（Service 侧）

```
XCollie SetInterfaceTimer(name="DecodeFrame", isService=true, timeout=30)
    │
    ▼ (30s 内 codec 未返回)
ServiceInterfaceTimerCallback()
    │
    ├─ FaultEventWrite(FAULT_TYPE_FREEZE, "Service task DecodeFrame timeout", "Service")
    │      │
    │      ▼ HiSysEvent (AV_CODEC domain)
    │
    ├─ threadDeadlockCount_ == 1 >= threshold → _exit(-1)  // 杀进程
    │
    └─ AVCODEC_LOGF("Process timeout, AVCodec service process exit.")
```

**恢复**：进程重启，由系统或上层监控恢复

### 场景3：API 调用超时（Client 侧）

```
XCollie SetInterfaceTimer(name="EncodeFrame", isService=false, timeout=30)
    │
    ▼ (30s 内 codec 未返回)
ClientInterfaceTimerCallback()
    │
    ├─ FaultEventWrite(FAULT_TYPE_FREEZE, "Client task EncodeFrame timeout", "Client")
    │      │
    │      ▼ HiSysEvent (AV_CODEC domain)
    │
    └─ 不杀进程，Client 侧继续运行
```

**恢复**：应用层收到超时错误，可选择重试或切换 codec

### 场景4：Demuxer 失败

```
demuxer->Read() 返回错误
    │
    ▼
FaultDemuxerEventWrite(DemuxerFaultInfo{
    appName, instanceId, callerType, sourceType,
    containerFormat, streamType, errMsg
})
    │
    ▼
HiSysEventWrite(MULTI_MEDIA domain, "DEMUXER_FAILURE", FAULT, ...)
```

**恢复**：应用层收到错误码 + HiSysEvent 持久记录

---

## 6. 关键文件索引

| 文件 | 职责 |
|------|------|
| `interfaces/inner_api/native/avcodec_errors.h` | 错误码常量定义（AVCS_ERR_*，共50+个） |
| `services/dfx/include/avcodec_log.h` | 日志宏 + CHECK_AND_RETURN_RET_LOG + 限频宏 |
| `services/dfx/avcodec_sysevent.cpp` | HiSysEvent 写入实现（7个 Write 函数） |
| `services/dfx/include/avcodec_sysevent.h` | FaultType 枚举 + 6 个 FaultInfo struct |
| `services/dfx/include/avcodec_xcollie.h` | XCollie 类 + COLLIE_LISTEN 宏 |
| `services/dfx/avcodec_xcollie.cpp` | Timer 回调 + Service/Client 分支处理 |

---

## 7. 错误码速查（精选）

> 完整50+错误码见 `interfaces/inner_api/native/avcodec_errors.h`（已验证）

| 错误码 | 含义 | 错误码 | 含义 |
|--------|------|--------|------|
| `AVCS_ERR_OK` | 成功 | `AVCS_ERR_STREAM_CHANGED` | 输出格式变化 |
| `AVCS_ERR_NO_MEMORY` | 内存不足 | `AVCS_ERR_INPUT_DATA_ERROR` | 输入数据错误 |
| `AVCS_ERR_INVALID_OPERATION` | 操作不允许 | `AVCS_ERR_VIDEO_UNSUPPORT_COLOR_SPACE_CONVERSION` | 色彩空间不支持 |
| `AVCS_ERR_INVALID_VAL` | 参数非法 | `AVCS_ERR_ILLEGAL_PARAMETER_SETS` | 非法的参数集 |
| `AVCS_ERR_UNKNOWN` | 未知错误 | `AVCS_ERR_MISSING_PARAMETER_SETS` | 缺少参数集 |
| `AVCS_ERR_SERVICE_DIED` | 服务已死 | `AVCS_ERR_INSUFFICIENT_HARDWARE_RESOURCES` | 硬件资源不足 |
| `AVCS_ERR_INVALID_STATE` | 状态非法 | `AVCS_ERR_UNSUPPORTED_CODEC_SPECIFICATION` | 不支持的 codec spec |
| `AVCS_ERR_UNSUPPORT` | 能力不支持 | `AVCS_ERR_TRY_AGAIN` | 稍后重试 |
| `AVCS_ERR_DEMUXER_FAILED` | 解封装失败 | `AVCS_ERR_DECRYPT_FAILED` | DRM 解密失败 |
| `AVCS_ERR_MUXER_FAILED` | 封装失败 | `AVCS_ERR_NOT_ENOUGH_DATA` | 输出 buffer 未满 |
| `AVCS_ERR_AUD_DEC_FAILED` | 音频解码失败 | `AVCS_ERR_END_OF_STREAM` | 流结束 |
| `AVCS_ERR_VID_DEC_FAILED` | 视频解码失败 | `AVCS_ERR_IPC_UNKNOWN` | IPC 未知错误 |

---

## 8. 相关已入库条目

- **MEM-DEVFLOW-008** — 问题定位首查路径（四步决策树 + XCollie/HiSysEvent）
- **MEM-ARCH-AVCODEC-002** — DFX 统计事件框架职责边界
- **MEM-ARCH-AVCODEC-014** — Codec Engine 三层插件架构（CodecBase + Loader + Factory）

---

## 9. Q&A（已验证）

| # | 问题 | 答案 |
|---|------|------|
| Q1 | ~~错误码文件在哪里？~~ | ✅ `interfaces/inner_api/native/avcodec_errors.h`（已验证） |
| Q2 | `AVCS_ERR_UNSUPPORTED` 还是 `AVCS_ERR_UNSUPPORT`？ | ✅ 正确为 `AVCS_ERR_UNSUPPORT`（无 ED 后缀） |
| Q3 | 限频宏 AVCODEC_LOGE_LIMIT 的 frequency 参数含义？ | ✅ 每 N 次调用打印一次（第 N 次触发打印） |
| Q4 | COLLIE_LISTEN 的 recovery 参数作用？ | recovery=true → XCollie FLAG 带 RECOVERY 标志，用于自动恢复场景 |
| Q5 | SetInterfaceTimer 的 dumpLog 参数作用？ | 设为 true 时超时会触发额外日志转储（需进一步确认） |