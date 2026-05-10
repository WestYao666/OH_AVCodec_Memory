---
id: MEM-ARCH-AVCODEC-S115
title: "AVCodec DFX 模块——HiSysEvent / HiTrace / XCollie / Dump 四工具链"
scope: [AVCodec, DFX, HiSysEvent, HiTrace, XCollie, Dump, Trace, SysEvent, FaultType, CodecDfxInfo, AVCodecTrace, AVCodecDumpControler, AVCodecXCollie, avcodec_dfx_component, avcodec_sysevent, avcodec_dump_utils, avcodec_xcollie]
status: approved
approved_at: "2026-05-11T00:47:00+08:00"
approval_submitted_at: "2026-05-10T10:03:00+08:00"
created_by: builder-agent
created_at: "2026-05-10T10:03:00+08:00"
关联主题: [S83(CAPI总览), S114(MediaCodec核心引擎), S109(MediaMuxer)]
priority: P3a
---

## Status

```yaml
created: 2026-05-10T10:03
builder: builder-agent
source: |
  services/dfx/avcodec_dfx_component.h (68行)
  services/dfx/avcodec_dfx_component.cpp (68行)
  services/dfx/avcodec_sysevent.h (96行)
  services/dfx/avcodec_sysevent.cpp (197行)
  services/dfx/avcodec_dump_utils.h (64行)
  services/dfx/avcodec_dump_utils.cpp (150行)
  services/dfx/avcodec_xcollie.cpp (177行)
  services/dfx/include/avcodec_trace.h (90行)
  services/dfx/include/avcodec_log.h
```

## 摘要

AVCodec DFX 模块位于 `services/dfx/`，是 MediaAVCodec 命名空间下的**观测性基础设施**，包含四个独立工具：

| 工具 | 文件 | 职责 |
|------|------|------|
| **AVCodecDfxComponent** | `avcodec_dfx_component.cpp/h` | 实例级 LogTag 管理，输出格式 `[instanceId][vdec/h.venc/s.venc]` |
| **AVCodecSysEvent** | `avcodec_sysevent.cpp/h` | HiSysEvent 写事件（FAULT/BEHAVIOR/STATISTIC 三类） |
| **AVCodecTrace** | `include/avcodec_trace.h` | HiTrace 链路追踪（同步/异步 Trace、CounterTrace） |
| **AVCodecXCollie** | `avcodec_xcollie.cpp/h` | 看门狗定时器，超时自动 dump 现场 |
| **AVCodecDumpControler** | `avcodec_dump_utils.cpp/h` | Dump 控制器，按 dumpIdx 聚合信息输出 |

---

## 1. AVCodecDfxComponent — LogTag 管理

**Evidence**: `services/dfx/avcodec_dfx_component.h` 全文件

```cpp
class AVCodecDfxComponent {
public:
    void SetTag(const std::string &str);
    const std::string &GetTag();
private:
    std::atomic<const char*> tag_;
    std::string tagContent_;
};
```

**Tag 格式规则**（`avcodec_dfx_component.cpp:26-38`）：
```
[instanceId][v.xxx] = 视频解码器
[instanceId][h.venc] = 硬件视频编码器
[instanceId][s.venc] = 软件视频编码器
```

---

## 2. AVCodecSysEvent — 三类 HiSysEvent

**Evidence**: `services/dfx/include/avcodec_sysevent.h:15-52` + `avcodec_sysevent.cpp`

### 2.1 FaultType 枚举（avcodec_sysevent.h:15-21）

```cpp
enum class FaultType : int32_t {
    FAULT_TYPE_FREEZE = 0,
    FAULT_TYPE_CRASH,
    FAULT_TYPE_INNER_ERROR,
    FAULT_TYPE_END,
};
```

### 2.2 HiSysEvent 写入（avcodec_sysevent.cpp）

**FAULT 事件**（`FaultEventWrite`，`avcodec_sysevent.cpp:50-55`）：
```
HiSysEventWrite("AV_CODEC", "FAULT", EventType::FAULT,
    "MODULE", module, "FAULTTYPE", FaultTypeString, "MSG", msg)
```

**SERVICE_START 事件**（`ServiceStartEventWrite`，`avcodec_sysevent.cpp:57-60`）：
```
HiSysEventWrite("AV_CODEC", "SERVICE_START_INFO", EventType::BEHAVIOR,
    "MODULE", module, "TIME", useTime, "MEMORY", useMemory)
```

**CODEC_START_INFO 事件**（`CodecStartEventWrite`，`avcodec_sysevent.cpp:71-77`）：
```
HiSysEventWrite("AV_CODEC", "CODEC_START_INFO", EventType::BEHAVIOR,
    "CLIENT_PID", ..., "CLIENT_UID", ..., "CODEC_INSTANCE_ID", ...,
    "CODEC_NAME", ..., "CODEC_IS_VENDOR", ..., "CODEC_MODE", ...)
```

### 2.3 各组件 FaultInfo 结构体（avcodec_sysevent.h:53-94）

| 结构体 | 用途 | 关键字段 |
|--------|------|---------|
| `CodecDfxInfo` | 编解码实例 | clientPid/uid, codecInstanceId, codecName, videoW/H, frameRate |
| `DemuxerFaultInfo` | 解封装故障 | appName, sourceType(DfxSourceType枚举), containerFormat, streamType |
| `MuxerFaultInfo` | 封装故障 | videoCodec, audioCodec, containerFormat |
| `AudioCodecFaultInfo` | 音频Codec故障 | audioCodec, errMsg |
| `VideoCodecFaultInfo` | 视频Codec故障 | videoCodec, errMsg |
| `AudioSourceFaultInfo` | 音频Source故障 | audioSourceType |
| `SourceStatisticsReportInfo` | 播放策略统计 | playStrategyDuration, bufferDuration, bitRate |

### 2.4 DfxSourceType 枚举（avcodec_sysevent.h:29-37）

```cpp
enum class DfxSourceType : int8_t {
    NONE = 0, DASHVOD, HTTPVOD, HLSVOD, FMP4VOD,
    FMP4LIVE, HLSLIVE, HTTPLIVE, DASHLIVE,
};
```

---

## 3. AVCodecTrace — HiTrace 链路追踪

**Evidence**: `services/dfx/include/avcodec_trace.h` 全文件（90行）

### 3.1 宏定义（avcodec_trace.h:27-38）

```cpp
#define AVCODEC_SYNC_TRACE         AVCodecTrace trace(__FUNCTION__)
#define AVCODEC_FUNC_TRACE_WITH_TAG   // 带自定义 Tag 的 Function Trace
#define AVCODEC_FUNC_TRACE_WITH_TAG_CLIENT  // 客户端 Trace
#define AVCODEC_FUNC_TRACE_WITH_TAG_SERVER  // 服务端 Trace
```

### 3.2 AVCodecTrace 类（avcodec_trace.h:40-87）

- **构造函数**：自动 `StartTraceEx(level, HITRACE_TAG_ZMEDIA, funcName)`
- **析构函数**：自动 `FinishTraceEx(level, HITRACE_TAG_ZMEDIA)`
- **静态方法**：`TraceBegin(taskId)` / `TraceEnd(taskId)` — 异步 Trace 配对
- **静态方法**：`CounterTrace(varName, val)` — 指标打点

### 3.3 条件编译

```cpp
#ifdef MEDIA_TRACE_DEBUG_ENABLE
#define MEDIA_TRACE_DEBUG(name) MediaAVCodec::AVCodecTrace trace(name)
#endif
```

---

## 4. AVCodecXCollie — 看门狗定时器

**Evidence**: `services/dfx/avcodec_xcollie.cpp`（177行）

- 基于 `xcollie/xcollie.h` 实现超时检测
- **DUMP_XCOLLIE_INDEX** = `0x01'00'00'00`（`avcodec_xcollie.cpp:24`）
- 当定时器超时，触发 dump 操作记录现场
- 单例模式：`AVCodecXCollie::GetInstance()`（`avcodec_xcollie.cpp:47`）

---

## 5. AVCodecDumpControler — Dump 信息聚合

**Evidence**: `services/dfx/avcodec_dump_utils.h` + `avcodec_dump_utils.cpp`（150行）

```cpp
class AVCodecDumpControler {
public:
    int32_t AddInfo(uint32_t dumpIdx, const std::string &name, const std::string &value = "");
    int32_t AddInfoFromFormat(uint32_t dumpIdx, const Media::Format &format,
                              const string_view &key, const string &name);
    int32_t AddInfoFromFormatWithMapping(uint32_t dumpIdx, const Media::Format &,
                                         key, name, mapping);
    int32_t GetDumpString(std::string &dumpString);
    uint32_t GetSpaceLength(uint32_t dumpIdx);
private:
    std::map<uint32_t, std::pair<std::string, std::string>> dumpInfoMap_;
    std::vector<uint32_t> length_ = std::vector<uint32_t>(4, 0);  // 4级 dump
};
```

**Dump 级别**（`length_` 数组固定 4 个元素）：
- Level 0: 最小信息
- Level 3: 最详细信息

---

## 6. 关键证据汇总

| # | 文件路径 | 行号 | 内容 |
|---|---------|------|------|
| 1 | `services/dfx/avcodec_dfx_component.cpp` | 26-38 | LogTag 格式规则（vdec/h.venc/s.venc） |
| 2 | `services/dfx/include/avcodec_sysevent.h` | 15-21 | FaultType 枚举定义 |
| 3 | `services/dfx/avcodec_sysevent.cpp` | 50-55 | FaultEventWrite HiSysEvent 写入 |
| 4 | `services/dfx/avcodec_sysevent.cpp` | 71-77 | CodecStartEventWrite 参数列表 |
| 5 | `services/dfx/include/avcodec_trace.h` | 40-87 | AVCodecTrace 类完整定义 |
| 6 | `services/dfx/avcodec_xcollie.cpp` | 24 | DUMP_XCOLLIE_INDEX = 0x01'00'00'00 |
| 7 | `services/dfx/avcodec_dump_utils.cpp` | 150 | AddInfoFromFormatWithMapping 完整实现 |

---

## 7. 与其他记忆的关联

- **S83（CAPI 总览）**：CAPI 是 DFX 数据的消费者（如 CodecStartEventWrite）
- **S114（MediaCodec 核心引擎）**：MediaCodec 是 DFX 主要报告对象（CodecDfxInfo）
- **S109（MediaMuxer）**：MuxerFaultInfo 关联 muxer 故障上报

---

## 8. 已知限制

1. **无独立 DFX Filter**：DFX 模块不是 Pipeline Filter，只是纯工具类库
2. **Dump 级别固定为 4 级**：`length_` 数组硬编码为 4 个元素，不可扩展
3. **XCollie 依赖 `HICOLLIE_ENABLE`**：未启用时 XCollie 为空操作
4. **SourceStatisticsReportInfo 未在上文看到写事件函数**：可能为后续扩展预留