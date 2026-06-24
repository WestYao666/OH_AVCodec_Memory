# MEM-ARCH-AVCODEC-S203: AVCodec DFX 可观测性模块架构

## 概要信息

| 字段 | 值 |
|------|-----|
| status | pending_approval |
| mem_id | MEM-ARCH-AVCODEC-S203 |
| title | AVCodec DFX 可观测性模块架构 |
| category | 架构/dfx |
| layer | services/dfx |
| domain | multimedia_av_codec |

---

## 摘要

AVCodec DFX 模块（`services/dfx/`）是 av_codec 部件的可观测性基础设施，提供四大能力：**HiSysEvent 系统事件上报**、**XCollie 超时看门狗**、**HiTrace 性能追踪**、**Dump 工具格式化**。所有引擎模块（codec/demuxer/muxer）均依赖 DFX 模块实现故障检测、行为埋点和调试信息输出。

---

## 架构描述

### 1. 模块定位

DFX 位于 `services/dfx/`，被 `services/engine/` 下所有子模块直接依赖。模块间引用关系：

```
engine/codec  ──> dfx/avcodec_sysevent   (故障/行为事件)
engine/demuxer ──> dfx/avcodec_sysevent   (故障事件)
engine/muxer  ──> dfx/avcodec_sysevent   (故障事件)
services/*    ──> dfx/avcodec_xcollie    (超时监控)
services/*    ──> dfx/avcodec_trace      (性能追踪)
services/*    ──> dfx/avcodec_dump_utils (调试信息)
```

### 2. 子模块详述

#### 2.1 avcodec_sysevent — HiSysEvent 系统事件上报

**文件**: `services/dfx/avcodec_sysevent.cpp`, `services/dfx/include/avcodec_sysevent.h`

**Domain**: `AV_CODEC`，事件通过 `HiSysEventWrite()` 上报到 HiviewDFX 系统。

**核心数据结构**（`avcodec_sysevent.h`）：

- `FaultType` 枚举（L24-28）：`FAULT_TYPE_FREEZE / CRASH / INNER_ERROR`
- 故障信息结构体：`DemuxerFaultInfo`, `AudioCodecFaultInfo`, `VideoCodecFaultInfo`, `MuxerFaultInfo`, `AudioSourceFaultInfo`
- `CodecDfxInfo`：编解码器启动时的详细信息（PID/UID/分辨率/码率等，行57-70）
- `SourceStatisticsReportInfo`：流媒体播放策略统计（L104-112）

**核心函数**：

| 函数 | 功能 | 事件类型 |
|------|------|---------|
| `FaultEventWrite` | 通用故障事件 | FAULT |
| `CodecStartEventWrite` | 编解码器启动 | BEHAVIOR |
| `CodecStopEventWrite` | 编解码器停止 | BEHAVIOR |
| `FaultDemuxerEventWrite` | 解封装器故障 | FAULT |
| `FaultAudioCodecEventWrite` | 音频解码器故障 | FAULT |
| `FaultVideoCodecEventWrite` | 视频解码器故障 | FAULT |
| `FaultMuxerEventWrite` | 封装器故障 | FAULT |
| `FaultRecordAudioEventWrite` | 录音故障 | FAULT |
| `StreamAppPackageNameEventWrite` | 媒体API调用统计 | STATISTIC |
| `SourceStatisticsEventWrite` | 流媒体播放策略上报（每4小时，行158-175） | STATISTIC |

**关键实现细节**：

- `SourceStatisticsEventWrite` 使用 OpenSSL EVP_sha256 对 CA 证书内容做哈希，保护隐私（L167）
- `FAULT_TYPE_TO_STRING` 映射表将枚举转为字符串供 HiSysEvent 使用（L32-37 in cpp）
- 统计事件域为 `MULTI_MEDIA`，故障事件域为 `AV_CODEC`（L40-51 in cpp）

#### 2.2 avcodec_xcollie — 超时看门狗与死锁检测

**文件**: `services/dfx/avcodec_xcollie.cpp`, `services/dfx/include/avcodec_xcollie.h`

**定位**: 基于 HiviewDFX XCollie 框架的接口超时监控。

**核心类**：

- `AVCodecXCollie`：单例，提供 `SetTimer`/`SetInterfaceTimer`/`CancelTimer`/`Dump`
- `AVCodecXcollieTimer`：RAII 包装器，自动在析构时取消定时器
- `AVCodecXcollieInterfaceTimer`：专用于服务/客户端接口超时，默认30秒

**超时回调行为**（`avcodec_xcollie.cpp`）：

- `ServiceInterfaceTimerCallback`（L151-169）：服务侧超时写 `FAULT_TYPE_FREEZE`，累计≥1次触发服务进程退出（`_exit(-1)`）
- `ClientInterfaceTimerCallback`（L170-176）：客户端超时仅写日志和事件，不退出进程

**宏便捷封装**（`avcodec_xcollie.h` 行99-107）：

```cpp
#define COLLIE_LISTEN(statement, args...) \
  { AVCodecXcollieInterfaceTimer xCollie(args); statement; }
#define CLIENT_COLLIE_LISTEN(statement, name) \
  { AVCodecXcollieInterfaceTimer xCollie(name, false, false, 30); statement; }
```

#### 2.3 avcodec_trace — HiTrace 性能追踪

**文件**: `services/dfx/include/avcodec_trace.h`

**定位**: 基于 HiTrace 体系的同步/异步函数耗时追踪。

**宏**：

| 宏 | 说明 |
|----|------|
| `AVCODEC_SYNC_TRACE` | 自动追踪当前函数（`HITRACE_LEVEL_INFO`） |
| `AVCODEC_SYNC_CUSTOM_TRACE(level, fmt, ...)` | 自定义级别和格式的同步追踪 |
| `AVCODEC_FUNC_TRACE_WITH_TAG` | 带实例标签的函数入口追踪 |
| `AVCODEC_FUNC_TRACE_WITH_TAG_CLIENT` | 客户端函数入口（后缀`:C`） |
| `AVCODEC_FUNC_TRACE_WITH_TAG_SERVER` | 服务端函数入口（后缀`:S`） |

**异步追踪 API**：`TraceBegin`/`TraceEnd`/`CounterTrace`，支持 `taskId` 关联起止

**Tag 机制**：`AVCodecDfxComponent::tag_` 原子变量存储实例标签，追踪宏通过 `customArg` 参数注入（L37-55）

#### 2.4 avcodec_dump_utils — Dump 信息格式化工具

**文件**: `services/dfx/avcodec_dump_utils.cpp`, `services/dfx/include/avcodec_dump_utils.h`

**定位**: 统一的分级调试信息格式化输出，支持从 `Format` 元数据对象直接提取值。

**核心能力**：

- `AVCodecDumpControler::AddInfo`：按 `dumpIdx` 分层（4级）存储 name/value 对
- `AddInfoFromFormat`：从 `Format` 对象自动提取 int32/int64/float/double/string 值
- `AddInfoFromMapping`：将整数值映射为字符串后存储
- `GetDumpString`：生成缩进格式的层级 dump 文本

**dumpIdx 编码约定**：高字节表示层级深度（level 1-4），低字节表示同级的子索引（行66-73 `GetLevel` 函数）

#### 2.5 avcodec_dfx_component — 实例级 DFX 标签

**文件**: `services/dfx/avcodec_dfx_component.cpp`, `services/dfx/include/avcodec_dfx_component.h`

**定位**: 为每个编解码实例生成可读标签（如 `[123][h.vdec]`），用于日志和追踪中的实例识别。

**`CreateVideoLogTag`**（L25-49）：从 `Meta` 元数据提取 `INSTANCE_ID` 和 `CODEC_NAME`，判断是硬件(`h.`)还是软件(`s.`)解码器，判断是视频解码(`vdec`)还是视频编码(`venc`)

#### 2.6 hisysevent.yaml — 事件元数据声明

**文件**: `hisysevent.yaml`

声明所有 HiSysEvent 事件的域、字段名、类型和描述：

- `CODEC_START_INFO`：行为事件，记录创建编解码器的完整参数（行16-28）
- `CODEC_STOP_INFO`：行为事件，仅记录 PID/UID/实例ID（行30-37）
- `FAULT`：故障事件，记录模块名、故障类型、描述（行39-45）
- `STATISTICS_INFO`：统计事件，包含能力查询次数、创建次数、应用名词典等（L44-52）

---

## 依赖关系

```
hisysevent.yaml  ──> HiSysEvent C API
avcodec_sysevent.cpp ──> hiseevent.h, nlohmann/json, openssl/evp.h
avcodec_xcollie.cpp  ──> xcollie.h (HICOLLIE_ENABLE)
avcodec_trace.h     ──> hitrace_meter.h
avcodec_dump_utils.cpp ──> meta/format.h
```

---


## Evidence 列表（本地镜像验证，2026-06-25）

1. `services/dfx/include/avcodec_sysevent.h` L24-28：`FaultType` 枚举（FAULT_TYPE_FREEZE=0 / FAULT_TYPE_CRASH / FAULT_TYPE_INNER_ERROR）
2. `services/dfx/avcodec_sysevent.cpp` L32-37：`FAULT_TYPE_TO_STRING` 映射表（Freeze/Crash/Inner error）
3. `services/dfx/include/avcodec_sysevent.h` L44-58：`CodecDfxInfo` 结构体，12个字段（pid_t/uid_t/codecInstanceId/codecName/codecIsVendor/codecMode/encoderBitRate/videoWidth/videoHeight/videoFrameRate/videoPixelFormat/audioChannelCount/audioSampleRate）
4. `services/dfx/include/avcodec_sysevent.h` L60-69：`DemuxerFaultInfo` 结构体（sourceType/errorCode/stuckCount/stuckLastTime）
5. `services/dfx/include/avcodec_sysevent.h` L70-80：`MuxerFaultInfo` 结构体（muxerMode/filePath/suffix/encrypted/tracksInfo）
6. `services/dfx/include/avcodec_sysevent.h` L81-88：`AudioCodecFaultInfo` 结构体（audioEncBitrate/sampleRate/channelCount）
7. `services/dfx/include/avcodec_sysevent.h` L89-103：`VideoCodecFaultInfo` 结构体（videoWidth/videoHeight/frameRate/encBitrate/pixelFormat）
8. `services/dfx/include/avcodec_sysevent.h` L104-112：`SourceStatisticsReportInfo` 结构体（ca_/strategyType/sourceType/durationUs）
9. `services/dfx/avcodec_sysevent.cpp` L157-180：`SourceStatisticsEventWrite` 函数，EVP_sha256() L167 行哈希 CA 证书隐私保护，SOURCE_STATISTICS_REPORT_HOURS=4
10. `services/dfx/include/avcodec_xcollie.h` L29-59：`AVCodecXCollie` 类接口（GetInstance/SetTimer/SetInterfaceTimer/CancelTimer/Dump，timerTimeout=10）
11. `services/dfx/include/avcodec_xcollie.h` L61-75：`AVCodecXcollieTimer` RAII 包装器（构造设置Timer/析构Cancel）
12. `services/dfx/include/avcodec_xcollie.h` L77-92：`AVCodecXcollieInterfaceTimer` RAII 包装器（isService/recovery/timeout=30 默认）
13. `services/dfx/include/avcodec_xcollie.h` L93-107：`COLLIE_LISTEN(statement, args...)` / `CLIENT_COLLIE_LISTEN(statement, name)` 宏
14. `services/dfx/avcodec_xcollie.cpp` L151-169：`ServiceInterfaceTimerCallback`，threadDeadlockCount_≥1 触发 L166 `_exit(-1)` 服务进程退出
15. `services/dfx/include/avcodec_trace.h` L25-35：`AVCODEC_SYNC_TRACE` / `AVCODEC_SYNC_CUSTOM_TRACE` / `AVCODEC_FUNC_TRACE_WITH_TAG` 系列宏
16. `services/dfx/include/avcodec_trace.h` L37-55：`AVCodecTrace` 类，StartTraceEx/FinishAsyncTraceEx，HITRACE_TAG_ZMEDIA
17. `services/dfx/include/avcodec_dump_utils.h` L18-39：`AVCodecDumpControler` 类声明，AddInfo/AddInfoFromFormat/GetDumpString/GetLevel
18. `services/dfx/avcodec_dump_utils.cpp` L144-154：`GetLevel` 函数，dumpIdx 高字节判定层级 1-4（DUMP_OFFSET_24/16/8）
19. `services/dfx/avcodec_dfx_component.cpp` L25-49：`CreateVideoLogTag` 函数，L36 判断 h./s.（omx=hardware），L37-40 判断 vdec/venc
20. `services/dfx/include/avcodec_log.h` L20-36：LOG_DOMAIN_FRAMEWORK=0xD002B30 / AUDIO=0xD002B31 / HCODEC=0xD002B32 / SFD=0xD002B33 / DEMUXER=0xD002B3A / MUER=0xD002B3B
21. `hisysevent.yaml` L44-52：`STATISTICS_INFO` 事件，QUERY_CAP_TIMES / CREATE_CODEC_TIMES / APP_NAME_DICT / CAP_UNSUPPORTED_INFO 等字段
