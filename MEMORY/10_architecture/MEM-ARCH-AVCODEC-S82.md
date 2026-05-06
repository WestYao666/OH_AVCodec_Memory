---
status: approved
approved_at: "2026-05-06"
---

# MEM-ARCH-AVCODEC-S82

## AVCodec Event Manager 事件管理框架——EventManager + 四类Handler协作架构

### 基本信息

| 字段 | 值 |
|------|------|
| **mem_id** | MEM-ARCH-AVCODEC-S82 |
| **scope** | AVCodec, DFX, EventManager, BackgroundProcessing, MemoryManagement |
| **关联场景** | 问题定位/系统运维/性能分析 |
| **approved_by** | feishu-user:ou_60d8641be684f82e8d9cb84c3015dde7 |
| **created** | 2026-05-03T14:10 |
| **来源文件** | `services/services/common/event_manager/` (2275行源码) |

---

## 1. 架构总览

EventManager 是 AVCodec 模块的**中央事件调度器**，以单例模式运行，负责将 Codec 实例生命周期事件、内存更新事件、后台/活跃切换事件、统计事件分发给四个专用 Handler 处理。

```
EventManager::OnInstanceEvent(type, meta)
    ├── INSTANCE_INIT        → StatisticsEventHandler (BASIC_CREATE_CODEC_INFO)
    ├── INSTANCE_RELEASE     → StatisticsEventHandler + InstanceMemoryUpdateEventHandler
    ├── INSTANCE_MEMORY_UPDATE → InstanceMemoryUpdateEventHandler
    ├── INSTANCE_MEMORY_RESET → InstanceMemoryUpdateEventHandler
    ├── INSTANCE_ENCODE_BEGIN → InstanceOperationEventHandler
    ├── INSTANCE_ENCODE_END   → InstanceOperationEventHandler
    └── STATISTICS_EVENT      → StatisticsEventHandler (定时 cJSON 上报)
```

**关键证据**：`event_manager.cpp:43-62`，switch 分发 7 种 EventType

---

## 2. EventType 位域设计

EventManager 使用 32-bit uint32_t 表示事件类型，采用 4 层位域结构（event_type.h:14-17）：

```
Bit 31-24: EventType 主类型 (1-9)
Bit 23-16: MainEvent 主事件类别
Bit 15-08: SubEvent 子事件类别
Bit 07-00: EventDetail 事件细节
```

**证据**：`event_type.h:14-17`
```cpp
enum class EventType : uint32_t {
    UNKNOWN                  = 0,
    INSTANCE_INIT            = (1 << 24),   // 0x01_00_00_00
    INSTANCE_RELEASE         = (2 << 24),   // 0x02_00_00_00
    INSTANCE_MEMORY_UPDATE   = (3 << 24),   // 0x03_00_00_00
    INSTANCE_MEMORY_RESET    = (4 << 24),   // 0x04_00_00_00
    INSTANCE_ENCODE_BEGIN    = (5 << 24),   // 0x05_00_00_00
    INSTANCE_ENCODE_END      = (6 << 24),   // 0x06_00_00_00
    STATISTICS_EVENT         = (7 << 24),   // 0x07_00_00_00
    STATISTICS_EVENT_SUBMIT  = (8 << 24),
    STATISTICS_EVENT_REGISTER_SUBMIT = (9 << 24),
    END,
    MASK = 0xFF000000,  // 取最高字节
};
```

StatisticsEventType 在此基础上继续细分（event_type.h:44-65），例如：
- `BASIC_INFO = STATISTICS_EVENT | (0<<16) | (0<<8) | 0`
- `CAP_UNSUPPORTED_INFO = STATISTICS_EVENT | (1<<16) | (1<<8) | 0`
- `CODEC_ERROR_INFO = STATISTICS_EVENT | (3<<16) | (1<<8) | 0`

---

## 3. StatisticsEventHandler 统计事件处理（845行）

### 3.1 职责

采集、上报 Codec 使用统计信息，包括：能力查询次数、Codec创建次数、各类型Codec使用分布、应用行为异常（解码器异常占用、快解码）、错误统计。

### 3.2 上报格式

使用 cJSON 构建 HiSysEvent 上报数据（statistics_event_handler.cpp:35-48）：

```cpp
static constexpr const char EVENT_DOMAIN[] = "AV_CODEC";
static constexpr const char EVENT_STATISTICS_INFO[] = "STATISTICS_INFO";
static constexpr const char QUERY_CAP_TIMES[] = "QUERY_CAP_TIMES";
static constexpr const char CREATE_CODEC_TIMES[] = "CREATE_CODEC_TIMES";
static constexpr const char CODEC_SPECIFIED_INFO[] = "CODEC_SPECIFIED_INFO";
static constexpr const char CAP_UNSUPPORTED_INFO[] = "CAP_UNSUPPORTED_INFO";
static constexpr const char DEC_ABNORMAL_OCCUPATION_INFO[] = "DEC_ABNORMAL_OCCUPATION_INFO";
static constexpr const char SPEED_DECODING_INFO[] = "SPEED_DECODING_INFO";
static constexpr const char CODEC_ERROR_INFO[] = "CODEC_ERROR_INFO";
```

**证据**：`statistics_event_handler.cpp:37-47`

### 3.3 VideoCodecType 字符串映射（statistics_event_handler.cpp:50-54）

```cpp
const std::unordered_map<VideoCodecType, std::string> VIDEO_CODEC_TYPE_TO_STRING = {
    { VideoCodecType::DECODER_HARDWARE, "HDec" },
    { VideoCodecType::DECODER_SOFTWARE, "SDec" },
    { VideoCodecType::ENCODER_HARDWARE, "HEnc" },
    { VideoCodecType::ENCODER_SOFTWARE, "SEnc" },
};
```

**证据**：`statistics_event_handler.cpp:50-54`

### 3.4 AppName 字典压缩

StatisticsEventHandler 对 App 名称进行字典压缩（statistics_event_handler.cpp:187-213）：最多 50 个 App 名称，每个 App 分配一个 int32_t index，上报时用 index 替代完整 App 名称字符串以减少数据量。

### 3.5 统计事件子类（statistics_event_handler.cpp:280+）

| 事件类型 | 说明 |
|---------|------|
| `BASIC_QUERY_CAP_INFO` | 能力查询次数 |
| `BASIC_CREATE_CODEC_INFO` | Codec 创建次数 |
| `BASIC_CREATE_CODEC_SPEC_INFO` | 按 CodecType+MimeType 分布 |
| `CAP_UNSUPPORTED_INFO` | 不支持的能力查询 |
| `DEC_ABNORMAL_OCCUPATION_INFO` | 解码器异常占用（超时/后台长时占用）|
| `SPEED_DECODING_INFO` | 快解码统计 |
| `CODEC_ERROR_INFO` | Codec 错误统计 |

---

## 4. InstanceMemoryUpdateEventHandler 内存更新处理（256行 + 572行Calculator）

### 4.1 职责

计算 Codec 实例内存占用，更新应用级内存阈值，超阈值时上报。

### 4.2 内存计算器 (InstanceMemoryCalculator, 572行)

基于 `CalculatorParameter` 结构计算内存占用（instance_memory_calculator.cpp:54-74）：

```cpp
struct CalculatorParameter {
    AVCodecType codecType = AVCODEC_TYPE_VIDEO_DECODER;
    std::string mimeType = CodecMimeType::VIDEO_AVC.data();
    CalculatorParameterPixelFormat pixelFormat = CalculatorParameterPixelFormat::YUV420;
    BitDepth bitDepth = BitDepth::BIT_8;
    bool isHardware = false;
    bool enablePostProcessing = false;
};
```

**证据**：`instance_memory_calculator.cpp:54-74`

### 4.3 预定义计算参数

系统预置了 15+ 种计算参数组合（instance_memory_calculator.cpp:86-152），包括：
- `HARDWARE_DECODER_HEVC_10BIT_YUV420_PARAMETER` — HEVC 10bit 硬件解码
- `HARDWARE_DECODER_AVC_YUV420_PARAMETER` — AVC 硬件解码
- `HARDWARE_ENCODER_HEVC_10BIT_YUV420_PARAMETER` — HEVC 10bit 硬件编码
- `SOFTWARE_DECODER_*` — 软件解码参数

**证据**：`instance_memory_calculator.cpp:86-152`

### 4.4 内存阈值

`appMemoryThreshold_` 通过 `ThresholdParser::GetThreshold()` 动态获取，应用 PID 内存超标时触发 `AddApp2ExceedThresholdList` 记录并上报（instance_memory_update_event_handler.h:34-35）。

---

## 5. BackgroundEventHandler 后台事件处理（284行）

### 5.1 职责

监听应用进入后台/恢复活跃事件，触发 Codec 实例的 Freeze（MemoryRecycle + Suspend）或 Resume（MemoryWriteBack + Resume）。

### 5.2 后台阈值

```cpp
constexpr auto APP_IN_BG_ELAPSED_TIME_THRESHOLD = 600; // 600秒 = 10分钟
```

**证据**：`background_event_handler.cpp:26`

### 5.3 Freeze 链路（background_event_handler.cpp:136-155）

```cpp
void BackGroundEventHandler::NotifyFreeze(InstanceId instanceId)
{
    auto codecInstance = AVCodecServerManager::GetInstance().GetCodecInstanceByInstanceId(instanceId);
    MemoryRecycleHandler(memoryRecycleList_, actualPid, codecInstance); // DMA回收
    SuspendHandler(suspendList_, actualPid, codecInstance);             // Codec挂起
}
```

**证据**：`background_event_handler.cpp:136-155`

### 5.4 Resume 链路（background_event_handler.cpp:168-195）

```cpp
void BackGroundEventHandler::NotifyActive(InstanceId instanceId)
{
    MemoryWriteBackHandler(memoryRecycleList_, actualPid, codecInstance); // 内存回写
    ResumeHandler(suspendList_, actualPid, codecInstance);               // Codec恢复
    // 若后台时长超600s，触发 DEC_ABNORMAL_OCCUPATION_LONG_TIME_IN_BG_INFO 事件
}
```

**证据**：`background_event_handler.cpp:168-195`

### 5.5 四类 Handler

| Handler | 触发条件 | 动作 |
|---------|---------|------|
| `MemoryRecycleHandler` | NotifyFreeze | `NOTIFY_MEMORY_RECYCLE` → DMA回收 |
| `SuspendHandler` | NotifyFreeze | `NOTIFY_SUSPEND` → Codec FROZEN |
| `MemoryWriteBackHandler` | NotifyActive | `NOTIFY_MEMORY_WRITE_BACK` → 恢复内存 |
| `ResumeHandler` | NotifyActive | `NOTIFY_RESUME` → Codec RESUMING |

**证据**：`background_event_handler.cpp:83-133`

---

## 6. InstanceOperationEventHandler 实例操作处理（104行）

### 6.1 职责

记录编码任务开始/结束事件，上报至 ResourceSchedule（资源调度子系统）。

### 6.2 编码开始事件（instance_operation_event_handler.cpp:40-52）

```cpp
void InstanceOperationEventHandler::OnInstanceEncodeBegin(Media::Meta &meta)
{
    pid_t pid; uid_t uid; int32_t instanceId; std::string processName;
    GetInstanceEncodeOperationMeta(meta, pid, uid, instanceId, processName);
    // 调用 ResSchedClient 上报编码开始事件
    ResSchedClient::GetInstance().ReportData(...);
}
```

**证据**：`instance_operation_event_handler.cpp:40-52`

---

## 7. 事件上报至 HiSysEvent

StatisticsEventHandler 最终通过 HiSysEvent C API 上报（statistics_event_handler.cpp:17）：
```cpp
#include "hisysevent.h"
```

EVENT_DOMAIN = `"AV_CODEC"`，与 S30（DFX模块）的 `HiSysEvent` 上报共享同一 domain。

---

## 8. 与 S30(DFX) 的关系

- S30 覆盖 AVCodecDumpControler + AVCodecDfxComponent + XCollie
- S82 覆盖 EventManager + 4类Handler 的**事件产生**层面
- 两者共同构成 AVCodec 的完整 DFX 体系：S30 偏重 dump/主动查询，S82 偏重事件驱动上报

---

## 9. 关键文件清单

| 文件 | 行数 | 职责 |
|------|------|------|
| `event_manager/event_manager.h` | 51 | EventManager 单例，7种事件类型定义 |
| `event_manager/event_manager.cpp` | 151 | 事件分发 switch |
| `event_manager/event_type.h` | 82 | EventType/StatisticsEventType 位域定义 |
| `event_handler/statistics_event_handler/statistics_event_handler.h` | 56 | StatisticsEventInfo 单例 |
| `event_handler/statistics_event_handler/statistics_event_handler.cpp` | 845 | cJSON HiSysEvent 上报，BasicInfo/CodecSpecInfo/ErrorInfo |
| `event_handler/instance_memory_update_event_handler/instance_memory_update_event_handler.h` | 66 | 内存更新 Handler |
| `event_handler/instance_memory_update_event_handler/instance_memory_update_event_handler.cpp` | 256 | 内存阈值管理，超时定时器 |
| `event_handler/instance_memory_update_event_handler/instance_memory_calculator.cpp` | 572 | 内存计算器，15+预置参数 |
| `event_handler/background_event_handler/background_event_handler.h` | 51 | 后台事件 Handler |
| `event_handler/background_event_handler/background_event_handler.cpp` | 284 | Freeze/Resume/MemoryRecycle/MemoryWriteBack |
| `event_handler/instance_operation_event_handler/instance_operation_event_handler.h` | 41 | 编码操作 Handler |
| `event_handler/instance_operation_event_handler/instance_operation_event_handler.cpp` | 104 | 编码起止上报 ResSchedClient |

---

## 10. 关联主题

- **S30** (MEM-ARCH-AVCODEC-S30): AVCodec DFX 模块——HiSysEvent/XCollie/AVCodecDumpControler（DFX 上报通道）
- **S57** (MEM-ARCH-AVCODEC-S57): HDecoder/HEncoder——FROZEN 态与 Suspend/Resume 机制（Codec侧实现）
- **S81** (MEM-ARCH-AVCODEC-S81): AVCodecSuspend 三模式——SuspendFreeze/SuspendActive（Codec侧接口）
