---
id: MEM-ARCH-AVCODEC-S30
title: AVCodec DFX 模块——HiSysEvent 上报、XCollie 超时监控与 Dump 工具链
type: architecture_fact
scope: [AVCodec, DFX, Monitoring, FaultInjection, SysEvent, XCollie, Dump]
status: approved
approved_at: "2026-05-06"
created_by: builder-agent
created_at: "2026-04-25T03:22:00+08:00"
updated_by: builder-agent
updated_at: "2026-04-25T03:22:00+08:00"
submitted_at: "2026-04-25T03:30:00+08:00"
evidence: |
  - source: services/dfx/avcodec_sysevent.cpp line 48-56
    anchor: "HiSysEventWrite(HISYSEVENT_DOMAIN_AVCODEC, \"FAULT\", OHOS::HiviewDFX::HiSysEvent::EventType::FAULT, \"MODULE\", module, \"FAULTTYPE\", FAULT_TYPE_TO_STRING.at(faultType), \"MSG\", msg)"
    note: FAULT事件三要素：MODULE + FAULTTYPE(Freeze/Crash/InnerError) + MSG；Domain为"AV_CODEC"
  - source: services/dfx/avcodec_sysevent.cpp line 66-82
    anchor: "HiSysEventWrite(HISYSEVENT_DOMAIN_AVCODEC, \"CODEC_START_INFO\", BEHAVIOR, \"CLIENT_PID\", codecDfxInfo.clientPid, \"CODEC_NAME\", codecDfxInfo.codecName, ...)"
    note: CODEC_START_INFO记录完整Codec实例参数（PID/UID/分辨率/帧率/码率/采样率），用于行为分析
  - source: services/dfx/avcodec_sysevent.cpp line 98-109
    anchor: "HiSysEventWrite(MULTI_MEDIA, \"DEMUXER_FAILURE\", FAULT, \"APP_NAME\", demuxerFaultInfo.appName, \"SOURCE_TYPE\", demuxerFaultInfo.sourceType, \"CONTAINER_FORMAT\", demuxerFaultInfo.containerFormat, ...)"
    note: Demuxer/Muxer/AudioCodec/VideoCodec各有独立FAULT事件，携带容器格式、流类型、错误信息
  - source: services/dfx/avcodec_sysevent.cpp line 150-167
    anchor: "SourceStatisticsEventWrite — 使用EVP_sha256计算CA证书hash，每4小时批量上报一次SOURCE_STATISTICS"
    note: 数据源统计（来源类型/URI/码率/流数量/DRM证书信息）定时上报，证书信息做SHA256脱敏
  - source: services/dfx/avcodec_xcollie.cpp line 70-91
    anchor: "SetTimer() — XCollie::GetInstance().SetTimer(name, timeout, callback, timerInfo.get(), flag) 其中flag=HIVIEWDFX::XCOLLIE_FLAG_RECOVERY|XCOLLIE_FLAG_LOG"
    note: XCollie看门狗支持RECOVERY+LOG双标志；timerInfo保存name/startTime/timeout用于超时后Dump输出
  - source: services/dfx/avcodec_xcollie.cpp line 123-138
    anchor: "ServiceInterfaceTimerCallback — threadDeadlockCount_++ >= threshold(1) → _exit(-1) 进程直接退出"
    note: 服务端任务超时不恢复，超1次直接进程退出；客户端仅记录EVENT不退出
  - source: services/dfx/avcodec_xcollie.cpp line 170-190
    anchor: "Dump(fd) — 遍历dfxDumper_，按DUMP_XCOLLIE_INDEX+层级偏移构建dumpIdx，写入[timerName, startTime, timeLeft]"
    note: Dump接口从fd输出XCollie活跃timer列表，含timer名称、启动时间、剩余超时时间
  - source: services/dfx/avcodec_xcollie.h line 66-81
    anchor: "COLLIE_LISTEN(statement, args...) — RAII包装：构造时SetInterfaceTimer，析构时CancelTimer"
    note: COLLIE_LISTEN宏实现接口超时监听，作用域结束自动取消timer；默认30s超时，isService=true
  - source: services/dfx/avcodec_dump_utils.cpp line 28-42
    anchor: "AVCodecDumpControler::AddInfo — dumpIdx高8位决定层级(level 2-4)，相同index覆盖，level决定缩进"
    note: dumpIdx编码结构：0xXX'YY'ZZ'WW，高字节为层级标识；AddInfo自动对齐列宽（取同level最大name长度）
  - source: services/dfx/avcodec_dump_utils.cpp line 68-81
    anchor: "GetValueFromFormat — switch-case处理FORMAT_TYPE_INT32/INT64/FLOAT/DOUBLE/STRING，适配Format统型格式"
    note: Dump工具支持从Format提取各类类型值转为字符串，无需知道具体类型
  - source: services/dfx/avcodec_dfx_component.cpp line 31-46
    anchor: "CreateVideoLogTag — instanceId+codecName含\"omx\"→\"h.\"否则\"s.\"；含\"decode\"→\"vdec\"含\"encode\"→\"venc\""
    note: LogTag生成规则：[instanceId][h.|s.][vdec|venc]，用于日志中快速识别硬件/软件解码器实例
  - source: hisysevent.yaml domain: AV_CODEC
    anchor: "STATISTICS_INFO: {type: STATISTIC, level: CRITICAL, desc: AVCodec statistics event info, preserve: true} 含QUERY_CAP_TIMES/CREATE_CODEC_TIMES/CODEC_SPECIFIED_INFO/APP_NAME_DICT等"
    note: 统计类事件含preserve=true，保证关键数据不丢失；记录能力查询次数/Codec创建次数/APP分布/异常占用统计
owner: 耀耀
review: pending
---

# MEM-ARCH-AVCODEC-S30: AVCodec DFX 模块——HiSysEvent 上报、XCollie 超时监控与 Dump 工具链

## 1. 模块架构概述

AVCodec DFX 模块位于 `services/dfx/`，由四个核心组件构成，形成从**实时监控→超时看门狗→结构化Dump→事件上报**的完整链路：

```
┌─────────────────────────────────────────────────────────────┐
│                   AVCodec DFX Module                         │
├─────────────────┬──────────────────┬─────────────────────────┤
│ AVCodecDfxComponent│ AVCodecXCollie │ AVCodecDumpControler │
│ LogTag生成器     │ XCollie超时监控  │ 结构化Dump格式化        │
│ [instanceId]     │ 看门狗+进程退出   │ 分层缩进+列对齐         │
│ [h.|s.][vdec|venc]│ 服务/客户端双模式 │ dumpIdx编码层级        │
├─────────────────┴──────────────────┴─────────────────────────┤
│              avcodec_sysevent.cpp (HiSysEvent)               │
│  FAULT(BEHAVIOR/STATISTIC) → HiSysEventWrite() → hived       │
└─────────────────────────────────────────────────────────────┘
```

**Domain**: `AV_CODEC`（定义于 `hisysevent.yaml`）

---

## 2. HiSysEvent 上报体系

### 2.1 事件类型与等级

| 事件名 | 类型 | Level | 用途 |
|--------|------|-------|------|
| `FAULT` | FAULT | CRITICAL | 解码器冻结/崩溃/内部错误 |
| `CODEC_START_INFO` | BEHAVIOR | MINOR | Codec实例创建参数 |
| `CODEC_STOP_INFO` | BEHAVIOR | MINOR | Codec实例销毁 |
| `SERVICE_START_INFO` | BEHAVIOR | MINOR | 服务启动耗时+内存 |
| `DEMUXER_FAILURE` | FAULT | CRITICAL | 解复用器失败 |
| `AUDIO_CODEC_FAILURE` | FAULT | CRITICAL | 音频解码器失败 |
| `VIDEO_CODEC_FAILURE` | FAULT | CRITICAL | 视频解码器失败 |
| `MUXER_FAILURE` | FAULT | CRITICAL | 封装器失败 |
| `RECORD_AUDIO_FAILURE` | FAULT | CRITICAL | 录音源失败 |
| `SOURCE_STATISTICS` | STATISTIC | CRITICAL | 数据源统计（4h批量） |
| `MEDIAKIT_STATISTICS` | STATISTIC | - | 媒体套件调用统计 |

### 2.2 FAULT 事件结构（avcodec_sysevent.cpp:48）

```cpp
HiSysEventWrite(HISYSEVENT_DOMAIN_AVCODEC, "FAULT",
    OHOS::HiviewDFX::HiSysEvent::EventType::FAULT,
    "MODULE", module,          // "Service" 或 "Client"
    "FAULTTYPE", FAULT_TYPE_TO_STRING.at(faultType), // Freeze/Crash/Inner error
    "MSG", msg);               // 自由文本错误描述
```

**FaultType 枚举**（`avcodec_sysevent.h:24`）：
- `FAULT_TYPE_FREEZE` = 0：任务/线程冻结（超时未响应）
- `FAULT_TYPE_CRASH` = 1：进程崩溃
- `FAULT_TYPE_INNER_ERROR` = 2：内部逻辑错误

### 2.3 CODEC_START_INFO 完整参数集（avcodec_sysevent.cpp:66）

```cpp
CodecDfxInfo {
    pid_t clientPid;            // 客户端进程ID
    uid_t clientUid;           // 客户端用户ID
    int32_t codecInstanceId;    // Codec实例唯一ID
    std::string codecName;      // Codec名称（如"OMX.rk.video_decoder.avc"）
    std::string codecIsVendor;  // "true"=硬件Codec "false"=软件Codec
    std::string codecMode;      // "buffer"=Buffer模式 或 "surface"=Surface模式
    int64_t encoderBitRate;    // 编码器输出码率
    int32_t videoWidth/Height;  // 视频宽高
    double videoFrameRate;      // 视频帧率
    std::string videoPixelFormat; // 像素格式
    int32_t audioChannelCount;  // 音频声道数
    int32_t audioSampleRate;   // 音频采样率
}
```

### 2.4 SOURCE_STATISTICS 定时上报（avcodec_sysevent.cpp:150）

```cpp
// 每4小时批量上报一次，数据含：
SourceStatisticsReportInfo {
    appName_, sourceType_, sourceUri_,
    playStrategyDuration_, playStrateBufferDurationForPlaying_,
    bitRate_, videoStreamCnt_, audioStreamCnt_, subtitleCnt_,
    ca_  // DRM证书信息
};
// 证书信息用EVP_sha256做hash脱敏后再上报
```

---

## 3. XCollie 超时看门狗

### 3.1 架构设计

XCollie 是 HiviewDFX 的超时监控框架，AVCodec 用于监控关键路径是否发生死锁或永久阻塞。

**关键文件**: `services/dfx/avcodec_xcollie.cpp`

### 3.2 TimerInfo 数据结构（avcodec_xcollie.h:85）

```cpp
struct TimerInfo {
    std::string name;       // timer名称，用于标识监控点
    std::time_t startTime; // 启动时间（绝对时间戳）
    uint32_t timeout;      // 超时时间（秒）
};
```

### 3.3 SetTimer 流程（avcodec_xcollie.cpp:70）

```cpp
int32_t AVCodecXCollie::SetTimer(
    const std::string &name,   // 监控项名称
    bool recovery,             // 是否自愈（一般false）
    bool dumpLog,              // 是否Dump日志（一般true）
    uint32_t timeout,         // 超时秒数
    std::function<void(void*)> callback) // 超时回调
{
    unsigned int flag = XCOLLIE_FLAG_NOOP;
    flag |= (recovery ? XCOLLIE_FLAG_RECOVERY : 0);
    flag |= (dumpLog ? XCOLLIE_FLAG_LOG : 0);
    auto timerInfo = std::make_shared<TimerInfo>(name, now(), timeout);
    auto id = XCollie::GetInstance().SetTimer(name, timeout, callback, timerInfo.get(), flag);
    dfxDumper_.emplace(id, timerInfo); // 保存timerInfo用于后续Dump
    return id;
}
```

### 3.4 服务端 vs 客户端行为差异（avcodec_xcollie.cpp:123-145）

```cpp
// 服务端超时回调 — 超阈值直接进程退出
void ServiceInterfaceTimerCallback(void *data) {
    threadDeadlockCount_++;
    AVCODEC_LOGE("Service task %{public}s timeout", name);
    FaultEventWrite(FAULT_TYPE_FREEZE, ...);
    if (threadDeadlockCount_ >= 1) {  // 阈值=1，立即退出
        FaultEventWrite(FAULT_TYPE_FREEZE,
            "Process timeout, AVCodec service process exit.");
        _exit(-1);  // 直接终止进程！
    }
}

// 客户端超时回调 — 仅记录不退出
void ClientInterfaceTimerCallback(void *data) {
    AVCODEC_LOGE("Client task %{public}s timeout", name);
    FaultEventWrite(FAULT_TYPE_FREEZE, ...); // 仅写事件，不退出进程
}
```

### 3.5 COLLIE_LISTEN 宏（RAII 模式）

```cpp
#define COLLIE_LISTEN(statement, args...)                               \
    {                                                                   \
        AVCodecXcollieInterfaceTimer xCollie(args);  /* 构造SetTimer */ \
        statement;                                    /*执行业务代码*/   \
    }  // 作用域结束自动CancelTimer

// 用法示例：
COLLIE_LISTEN(DoSomething(), "CodecServer::ProcessRequest", true, false, 30);
// 等价于：
{
    AVCodecXcollieInterfaceTimer xCollie("CodecServer::ProcessRequest", true, false, 30);
    DoSomething();
}
```

---

## 4. Dump 工具链

### 4.1 AVCodecDumpControler 分层索引

**dumpIdx 编码规则**（`avcodec_dump_utils.cpp:28`）：

```
dumpIdx = 0xXX'YY'ZZ'WW
  ├─ XX = level标记（0x04=level4, 0x00=level3, 0x00=level2...）
  ├─ YY = level3子索引
  ├─ ZZ = level2子索引
  └─ WW = level1数据
```

**层级缩进**：level决定左侧空格数（`(level-1)*4`空格），同一level的name列自动对齐到最大长度。

### 4.2 XCollie Dump 输出格式（avcodec_xcollie.cpp:170）

```
[AVCodec_XCollie]
Timer_1
    TimerName - xxx
    StartTime - 2025-01-01 10:00:00
    TimeLeft - 15
Timer_2
    TimerName - yyy
    StartTime - 2025-01-01 10:01:00
    TimeLeft - 45
```

---

## 5. AVCodecDfxComponent LogTag

```cpp
// avcodec_dfx_component.cpp:31
// 生成格式: [instanceId][h.|s.][vdec|venc]
// h. = hardware (codecName含"omx")，s. = software
// vdec = decoder，venc = encoder
std::string CreateVideoLogTag(const Meta &callerInfo) {
    // 从Meta提取INSTANCE_ID和CODEC_NAME
    // "omx.rk.video.decoder.avc" → [123][h.vdec]
}
```

---

## 6. 与 S17 DRM/SVP 的关系

S17 覆盖了 DRM 解密模块 `codec_drm_decrypt.cpp`，而本 S30 的 `hisysevent.yaml` 中 `STATISTICS_INFO` 含 `APP_NAME_DICT` 和 `DEC_ABNORMAL_OCCUPATION_INFO`，可间接反映 DRM 加密内容的解码占用情况。CERT 信息（`ca_`）通过 SHA256 hash 脱敏后经 `SOURCE_STATISTICS` 定期上报，形成 DRM 内容访问的可观测性闭环。

---

## 7. 关键设计决策

1. **进程级熔断**：服务端 XCollie 超时不恢复，直接 `_exit(-1)` —— 这是主动暴露而非静默吞掉问题
2. **批量上报防抖动**：SOURCE_STATISTICS 每 4 小时才上报一次，避免高频事件淹没系统
3. **证书脱敏**：DRM CA 证书用 SHA256 hash 脱敏，满足隐私合规要求
4. **RAII 自动取消**：COLLIE_LISTEN 宏确保 timer 不会泄漏，异常路径也能正确清理
5. **dumpIdx 层级编码**：避免大量独立 dump key，用编码代替命名约定
