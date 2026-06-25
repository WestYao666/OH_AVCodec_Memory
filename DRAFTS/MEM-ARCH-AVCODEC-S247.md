# MEM-ARCH-AVCODEC-S247: AVCodec Instance Information Management

## Basic Information

| Field | Value |
|-------|-------|
| status | pending_approval |
| mem_id | MEM-ARCH-AVCODEC-S247 |
| topic | AVCodec Instance Information Management - instance_info.h & EventManager instance lifecycle tracking system |
| source | GitCode (https://gitcode.com/openharmony/multimedia_av_codec) |
| created_by | builder-agent |
| timestamp | 2026-06-21T23:46:00+08:00 |
| registered | 2026-06-25T19:07:00+08:00 |
| evidence_count | 20 |

## Topic Description

AVCodec 实例信息管理体系——instance_info.h 实例追踪数据结构 + EventManager 实例生命周期事件系统

AVCodec 实例信息管理体系包含两个核心组件：
1. **instance_info.h**: 实例追踪核心数据结构（InstanceId/CallerInfo/InstanceInfo）
2. **EventManager**: 实例生命周期事件系统（Init/Release/Memory/Encode events）

## Scope

AVCodec, InstanceId, VideoCodecType, CallerInfo, InstanceInfo, EventManager, EventType, StatisticsEventType, DFX, Lifecycle, MemoryTracking, PID, UID, ProcessName

## Associated Scenarios

DFX可观测性 / 实例管理 / 问题定位 / 性能统计 / 多实例追踪

## Evidence

### E1: instance_info.h - Type Aliases and Constants

**File**: `services/services/common/instance_info.h`

```cpp
// Line 18-20: Core type aliases and invalid-value constants
using InstanceId = int32_t;                              // L18
constexpr pid_t INVALID_PID = -1;                         // L19
constexpr InstanceId INVALID_INSTANCE_ID = -1;              // L20
```

**Key Design Patterns**:
- `InstanceId = int32_t` - single global identifier for each codec instance
- Both PID and InstanceId use -1 as sentinel invalid value

### E2: instance_info.h - VideoCodecType Enum

**File**: `services/services/common/instance_info.h`

```cpp
// Line 22-28: VideoCodecType distinguishes codec category
enum class VideoCodecType : int16_t {                     // L22
    UNKNOWN,                                               // L23
    DECODER_HARDWARE,                                      // L24
    DECODER_SOFTWARE,                                      // L25
    ENCODER_HARDWARE,                                      // L26
    ENCODER_SOFTWARE,                                     // L27
    END,                                                   // L28
};
```

**Key Design Patterns**:
- Four-way classification: Hardware/Software × Decoder/Encoder
- `END` sentinel for range checking

### E3: instance_info.h - CallerInfo Struct

**File**: `services/services/common/instance_info.h`

```cpp
// Line 30-34: CallerInfo tracks the calling process identity
struct CallerInfo {                                        // L30
    pid_t pid = -1;                                        // L31
    uid_t uid = 0;                                        // L32
    std::string processName = "";                          // L33
};                                                        // L34
```

**Purpose**: Records the process that initiated the codec operation (pid, uid, processName)

### E4: instance_info.h - InstanceInfo Struct

**File**: `services/services/common/instance_info.h`

```cpp
// Line 36-66: InstanceInfo is the primary instance tracking data structure
struct InstanceInfo {                                     // L36
    InstanceId instanceId = INVALID_INSTANCE_ID;          // L37
    CallerInfo caller;                                     // L38
    CallerInfo forwardCaller;                              // L39 - multi-layer proxy support
    AVCodecType codecType;                                 // L40
    uint32_t memoryUsage = 0;                              // L41
    std::string codecName = "";                           // L42
    std::time_t codecCreateTime = 0;                       // L43
    VideoCodecType videoCodecType = VideoCodecType::UNKNOWN; // L44

    void Print()                                          // L45 - L51
    constexpr OHOS::HiviewDFX::HiLogLabel LABEL = {LOG_CORE, LOG_DOMAIN_FRAMEWORK, "InstanceInfo"};
    AVCODEC_LOGI("InstanceId: %{public}d, Caller: [%{public}d, %{public}s], ..."
        ", CodecType: %{public}d, MemoryUsage: %{public}u", instanceId, caller.pid, ...);

    pid_t GetActualCallerPid() const                       // L53 - L59
    {
        if (forwardCaller.pid != INVALID_INSTANCE_ID) {
            return forwardCaller.pid;  // proxy returns original caller
        } else {
            return caller.pid;
        }
    }

    std::string GetActualCallerProcessName() const         // L60 - L66
    {
        if (forwardCaller.pid != INVALID_INSTANCE_ID) {
            return forwardCaller.processName;
        } else {
            return caller.processName;
        }
    }
};                                                         // L67
```

**Key Design Patterns**:
- `forwardCaller` supports multi-layer proxy calls (e.g., camera app → media framework → codec)
- `GetActualCallerPid()` resolves the true originating process even through a proxy
- `memoryUsage` enables per-instance resource monitoring
- `codecCreateTime` enables lifetime tracking

### E5: instance_info.h - GetInstanceIdFromMeta Utility

**File**: `services/services/common/instance_info.h`

```cpp
// Line 69-75: Extract instance ID from event metadata
[[maybe_unused]] static int32_t GetInstanceIdFromMeta(const Media::Meta &meta)  // L69
{
    auto instanceId = INVALID_INSTANCE_ID;
    meta.GetData(EventInfoExtentedKey::INSTANCE_ID.data(), instanceId);  // L72
    return instanceId;
}
```

**Purpose**: Extract instance ID from event metadata, enabling event-to-instance correlation

### E6: event_info_extented_key.h - Instance-Level Extended Keys

**File**: `services/services/common/event_manager/event_info_extented_key.h`

```cpp
// Line 13-16: Instance and codec type identification keys
static constexpr std::string_view INSTANCE_ID = "av_codec_event_info_instance_id";  // L13
static constexpr std::string_view CODEC_TYPE = "av_codec_event_info_codec_type";      // L14
static constexpr std::string_view IS_HARDWARE = "IS_VENDOR";                         // L15
static constexpr std::string_view BIT_DEPTH = "av_codec_event_info_bit_depth";        // L16
static constexpr std::string_view VIDEO_CODEC_TYPE = "av_codec_event_info_video_codec_type"; // L21
```

**Key Design Patterns**:
- String-based key registry for type-safe metadata access
- `IS_HARDWARE` uses `"IS_VENDOR"` as the underlying string (misnamed but intentional)
- Enables correlation between event data and instance records

### E7: event_info_extented_key.h - Performance and Speed Decoding Keys

**File**: `services/services/common/event_manager/event_info_extented_key.h`

```cpp
// Line 22-30: Performance statistics and speed bucket keys
static constexpr std::string_view TOTAL_DECODING_DURATION = "total_decoding_duration"; // L22
static constexpr std::string_view TOTAL_DECODING_CNT = "total_decoding_cnt";             // L23
static constexpr std::string_view SPEED_DECODING_INFO_TOTAL = "speed_decoding_info_total"; // L24
static constexpr std::string_view SPEED_DECODING_INFO_0_75X = "speed_decoding_info_0_75x"; // L25
static constexpr std::string_view SPEED_DECODING_INFO_1_00X = "speed_decoding_info_1_00x"; // L26
static constexpr std::string_view SPEED_DECODING_INFO_1_25X = "speed_decoding_info_1_25x"; // L27
static constexpr std::string_view SPEED_DECODING_INFO_1_50X = "speed_decoding_info_1_50x"; // L28
static constexpr std::string_view SPEED_DECODING_INFO_2_00X = "speed_decoding_info_2_00x"; // L29
static constexpr std::string_view SPEED_DECODING_INFO_3_00X = "speed_decoding_info_3_00x"; // L30
```

**Key Design Patterns**:
- Six speed buckets (0.75x to 3.00x) for adaptive playback quality analysis
- Speed buckets distinguish slow (0.75x) from fast (3.00x) playback conditions

### E8: event_info_extented_key.h - Context and Error Keys

**File**: `services/services/common/event_manager/event_info_extented_key.h`

```cpp
// Line 17-20, 31-38: Context, mode, and error keys
static constexpr std::string_view ENABLE_POST_PROCESSING = "av_codec_event_info_enable_post_processing"; // L17
static constexpr std::string_view PIXEL_FORMAT_STRING = "pixel_format_string";  // L18
static constexpr std::string_view IS_ENCODER = "is_encoder";                    // L19
static constexpr std::string_view CODEC_ERROR_CODE = "codec_error_code";         // L20
static constexpr std::string_view WIDTH = "av_codec_event_info_width";           // L33
static constexpr std::string_view HEIGHT = "av_codec_event_info_height";        // L34
static constexpr std::string_view INSTANCE_ACTION = "av_codec_event_info_instance_action"; // L36
static constexpr std::string_view APP_INDEX = "av_codec_event_info_app_index";  // L38
```

### E9: event_manager.h - Singleton Interface

**File**: `services/services/common/event_manager/event_manager.h`

```cpp
// Line 14-19: EventManager singleton class declaration
class EventManager {                                      // L14
public:
    static EventManager &GetInstance();                    // L16: Singleton access
    void OnInstanceEvent(EventType type);                 // L17
    void OnInstanceEvent(EventType type, Media::Meta &meta); // L18
    void OnInstanceEvent(StatisticsEventType type);        // L19
    void OnInstanceEvent(StatisticsEventType type, Media::Meta &meta); // L20

private:
    EventManager() {}                                     // L23: Private constructor (singleton)
```

**Key Design Patterns**:
- Singleton pattern via `GetInstance()` and private constructor
- Dual event type system: `EventType` (lifecycle) and `StatisticsEventType` (performance)
- Metadata-driven events via `Media::Meta` parameter

### E10: event_manager.h - Extended Event Handlers

**File**: `services/services/common/event_manager/event_manager.h`

```cpp
// Line 27-35: Extended event handler declarations (private)
private:
    void OnInstanceInitEvent(Media::Meta &meta);            // L28
    void OnInstanceReleaseEvent(Media::Meta &meta);          // L29
    void OnInstanceMemoryUpdateEvent(Media::Meta &meta);      // L30
    void OnInstanceMemoryResetEvent(Media::Meta &meta);      // L31
    void OnInstanceEncodeBeginEvent(Media::Meta &meta);       // L32
    void OnInstanceEncodeEndEvent(Media::Meta &meta);         // L33
    void OnStatisticsEvent(StatisticsEventType type, Media::Meta &meta);  // L34
    void OnStatisticsEventSubmit();                          // L35
    void OnStatisticsEventRegisterSubmit();                  // L36
```

**Key Design Patterns**:
- Separate handlers for Init/Release/Memory/Encode lifecycle stages
- `OnStatisticsEventSubmit()` - periodic stats report trigger
- `OnStatisticsEventRegisterSubmit()` - registers a timer for periodic submission

### E11: event_manager.cpp - GetInstance Singleton Implementation

**File**: `services/services/common/event_manager/event_manager.cpp`

```cpp
// Line 30-34: Singleton instance creation
EventManager &EventManager::GetInstance()                  // L30
{
    static EventManager manager;                           // L31: Meyer's singleton
    return manager;                                       // L32
}
```

### E12: event_manager.cpp - OnInstanceEvent Dispatch

**File**: `services/services/common/event_manager/event_manager.cpp`

```cpp
// Line 44-73: Event dispatch using bit-mask switch routing
void EventManager::OnInstanceEvent(EventType type, Media::Meta &meta)  // L44
{
    CHECK_AND_RETURN_LOG(type > EventType::UNKNOWN && type < EventType::END, "Unknown event type");
    switch (type & EventType::MASK) {                      // L47: Bit-mask routing
        case EventType::INSTANCE_INIT:                    // L48
            OnInstanceInitEvent(meta); break;              // L49
        case EventType::INSTANCE_RELEASE:                 // L50
            OnInstanceReleaseEvent(meta); break;           // L51
        case EventType::INSTANCE_MEMORY_UPDATE:           // L52
            OnInstanceMemoryUpdateEvent(meta); break;     // L53
        case EventType::INSTANCE_MEMORY_RESET:            // L54
            OnInstanceMemoryResetEvent(meta); break;      // L55
        case EventType::INSTANCE_ENCODE_BEGIN:            // L56
            OnInstanceEncodeBeginEvent(meta); break;      // L57
        case EventType::INSTANCE_ENCODE_END:              // L58
            OnInstanceEncodeEndEvent(meta); break;        // L59
        case EventType::STATISTICS_EVENT:                 // L60
            OnStatisticsEvent(static_cast<StatisticsEventType>(type), meta); break; // L61
        case EventType::STATISTICS_EVENT_SUBMIT:          // L62
            OnStatisticsEventSubmit(); break;              // L63
        case EventType::STATISTICS_EVENT_REGISTER_SUBMIT: // L64
            OnStatisticsEventRegisterSubmit(); break;     // L65
        default:                                           // L66
            AVCODEC_LOGW("Nothing to do with this event: %{public}d", ...); break; // L67
    }
}
```

**Key Design Patterns**:
- `type & EventType::MASK` extracts the top 8 bits for fast switch dispatch
- Supports 9 event categories routed to dedicated handlers

### E13: event_manager.cpp - OnInstanceInitEvent Implementation

**File**: `services/services/common/event_manager/event_manager.cpp`

```cpp
// Line 76-93: Init event - loads instance info from manager into meta
void EventManager::OnInstanceInitEvent(Media::Meta &meta)  // L76
{
    auto instanceId = GetInstanceIdFromMeta(meta);         // L77
    auto instanceInfoOpt = AVCodecServerManager::GetInstance().GetInstanceInfoByInstanceId(instanceId); // L78
    CHECK_AND_RETURN_LOG(instanceInfoOpt != std::nullopt, ...);
    auto instanceInfo = instanceInfoOpt.value();

    meta.GetData(Media::Tag::AV_CODEC_CALLER_PID, instanceInfo.caller.pid);           // L81
    meta.GetData(Media::Tag::AV_CODEC_CALLER_UID, instanceInfo.caller.uid);             // L82
    meta.GetData(Media::Tag::AV_CODEC_CALLER_PROCESS_NAME, instanceInfo.caller.processName); // L83
    meta.GetData(Media::Tag::AV_CODEC_FORWARD_CALLER_PID, instanceInfo.forwardCaller.pid); // L84
    meta.GetData(Media::Tag::AV_CODEC_FORWARD_CALLER_UID, instanceInfo.forwardCaller.uid); // L85
    meta.GetData(Media::Tag::AV_CODEC_FORWARD_CALLER_PROCESS_NAME, instanceInfo.forwardCaller.processName); // L86
    meta.GetData(EventInfoExtentedKey::CODEC_TYPE.data(), instanceInfo.codecType);     // L87
    meta.GetData(Media::Tag::MEDIA_CODEC_NAME, instanceInfo.codecName);                // L88
    meta.GetData(EventInfoExtentedKey::VIDEO_CODEC_TYPE.data(), instanceInfo.videoCodecType); // L89
    AVCodecServerManager::GetInstance().SetInstanceInfoByInstanceId(instanceId, instanceInfo); // L91
}
```

**Key Design Patterns**:
- OnInit enriches metadata with caller/process/forwardCaller information
- Integrates with AVCodecServerManager for instance info lookup/update
- Populates 8 metadata fields from InstanceInfo struct

### E14: event_manager.cpp - Memory and Encode Event Handlers

**File**: `services/services/common/event_manager/event_manager.cpp`

```cpp
// Line 95-125: Delegation to specialized event handlers
void EventManager::OnInstanceReleaseEvent(Media::Meta &meta)    // L95
{
    InstanceMemoryUpdateEventHandler::GetInstance().OnInstanceRelease(meta); // L96
}
void EventManager::OnInstanceMemoryUpdateEvent(Media::Meta &meta) // L98
{
    InstanceMemoryUpdateEventHandler::GetInstance().OnInstanceMemoryUpdate(meta); // L99
}
void EventManager::OnInstanceMemoryResetEvent(Media::Meta &meta)  // L101
{
    InstanceMemoryUpdateEventHandler::GetInstance().OnInstanceMemoryReset(meta); // L102
}
void EventManager::OnInstanceEncodeBeginEvent(Media::Meta &meta)  // L104
{
    InstanceOperationEventHandler::GetInstance().OnInstanceEncodeBegin(meta); // L105
}
void EventManager::OnInstanceEncodeEndEvent(Media::Meta &meta)    // L107
{
    InstanceOperationEventHandler::GetInstance().OnInstanceEncodeEnd(meta); // L108
}
void EventManager::OnStatisticsEvent(StatisticsEventType type, Media::Meta &meta) // L110
{
    StatisticsEventInfo::GetInstance().OnAddEventInfo(type, meta); // L111
}
void EventManager::OnStatisticsEventSubmit()                        // L113
{
    StatisticsEventInfo::GetInstance().OnSubmitEventInfo();          // L114
}
void EventManager::OnStatisticsEventRegisterSubmit()                 // L116
{
    StatisticsEventInfo::GetInstance().RegisterSubmitEventTimer();    // L117
}
```

**Key Design Patterns**:
- Delegates to four specialized handler singletons:
  - `InstanceMemoryUpdateEventHandler` - memory lifecycle
  - `InstanceOperationEventHandler` - encode begin/end operations
  - `StatisticsEventInfo` - performance statistics

### E15: event_type.h - EventType Bit-Field Layout

**File**: `services/services/common/event_manager/event_type.h`

```cpp
// Line 24-35: EventType bit-field structure
/* EventType description
 * +-------+-------------+-------------+-------------+
 * | Bit   | 31-24       | 23-16       | 15-08  | 07-00 |
 * +-------+-------------+-------------+-------------+-------------+
 * | Field | EventType   | MainEvent   | SubEvent| EventDetail |
 * +-------+-------------+-------------+-------------+-------------+
 */
enum class EventType : uint32_t {
    UNKNOWN = 0,                                  // L25
    INSTANCE_INIT = (1 << 24),                    // L26
    INSTANCE_RELEASE = (2 << 24),                 // L27
    INSTANCE_MEMORY_UPDATE = (3 << 24),           // L28
    INSTANCE_MEMORY_RESET = (4 << 24),            // L29
    INSTANCE_ENCODE_BEGIN = (5 << 24),            // L30
    INSTANCE_ENCODE_END = (6 << 24),             // L31
    STATISTICS_EVENT = (7 << 24),                 // L32
    STATISTICS_EVENT_SUBMIT = (8 << 24),         // L33
    STATISTICS_EVENT_REGISTER_SUBMIT = (9 << 24), // L34
    END,                                         // L35
    MASK = 0xFF000000,                            // L36
};
```

**Key Design Patterns**:
- 8-bit top nybble encodes event category (9 categories: 0-9)
- StatisticsEventType uses lower bits for sub-event hierarchy
- Bit-mask design enables efficient switch dispatch in `OnInstanceEvent`

### E16: event_type.h - StatisticsEventType Hierarchy

**File**: `services/services/common/event_manager/event_type.h`

```cpp
// Line 48-81: StatisticsEventType extends STATISTICS_EVENT with 4 main categories
enum class StatisticsEventType : uint32_t {
    // Category 0 (MainEvent=0): Basic info
    BASIC_INFO = EventType::STATISTICS_EVENT | (0 << 16) | (0 << 8) | 0,       // L48
    BASIC_QUERY_CAP_INFO = EventType::STATISTICS_EVENT | (0 << 16) | (0 << 8) | 1, // L49
    BASIC_CREATE_CODEC_INFO = EventType::STATISTICS_EVENT | (0 << 16) | (0 << 8) | 2, // L50
    ...
    // Category 2 (MainEvent=2): App behaviors
    APP_BEHAVIORS_INFO = EventType::STATISTICS_EVENT | (2 << 16) | (0 << 8) | 0, // L62
    DEC_ABNORMAL_OCCUPATION_INFO = EventType::STATISTICS_EVENT | (2 << 16) | (2 << 8) | 0, // L65
    SPEED_DECODING_INFO = EventType::STATISTICS_EVENT | (2 << 16) | (3 << 8) | 0, // L66
    ...
    // Category 3 (MainEvent=3): Codec abnormal
    CODEC_ABNORMAL_INFO = EventType::STATISTICS_EVENT | (3 << 16) | (0 << 8) | 0, // L70
    CODEC_ERROR_INFO = EventType::STATISTICS_EVENT | (3 << 16) | (1 << 8) | 0,     // L71
};
```

**Key Design Patterns**:
- 4 main categories: BASIC_INFO(0), APP_SPECIFICATIONS_INFO(1), APP_BEHAVIORS_INFO(2), CODEC_ABNORMAL_INFO(3)
- `APP_BEHAVIORS_INFO` category includes speed decoding and abnormal occupation tracking
- `CODEC_ABNORMAL_INFO` category handles codec error reporting

### E17: statistics_event_handler.h - StatisticsEventInfo Singleton

**File**: `services/services/common/event_manager/event_handler/statistics_event_handler/statistics_event_handler.h`

```cpp
// Line 27-65: StatisticsEventInfo manages event collection and reporting
class StatisticsEventInfo {                              // L27
public:
    using EventHook = std::function<bool(const Media::Meta &)>; // L29: return true to erase hook

    static StatisticsEventInfo &GetInstance()            // L41
    {
        static StatisticsEventInfo instance;               // L41
        return instance;
    }

    void OnAddEventInfo(StatisticsEventType eventType, const Media::Meta &eventMeta); // L46
    void OnSubmitEventInfo();                             // L47
    void RegisterEventHook(StatisticsEventType eventType, EventHook hook); // L49
    void RegisterSubmitEventTimer();                       // L51
    bool IsEventValid();                                  // L53

private:
    std::shared_mutex mutex_;                             // L57
    std::unordered_map<StatisticsEventType, std::shared_ptr<StatisticsEventInfoBase>> eventInfoMap_; // L58
    std::shared_mutex eventHookMutex_;                    // L61
    std::unordered_map<StatisticsEventType, EventHook> eventHooks_; // L62
    std::shared_ptr<AVCodecXcollieTimer> timer_;          // L65: XCollie watchdog timer
};
```

**Key Design Patterns**:
- `EventHook` callback mechanism allows external components to intercept/filter events
- Dual mutex design (mutex_/eventHookMutex_) separates event data from hook access
- `AVCodecXcollieTimer` ties statistics submission to watchdog monitoring
- Thread-safe via `std::shared_mutex` (C++17)

### E18: instance_memory_update_event_handler.h - Memory Tracking Interface

**File**: `services/services/common/event_manager/event_handler/instance_memory_update_event_handler/instance_memory_update_event_handler.h`

```cpp
// Line 23-55: InstanceMemoryUpdateEventHandler manages per-instance memory
using CalculatorType = std::function<uint32_t(uint32_t)>; // L23
class InstanceMemoryUpdateEventHandler {                   // L24
public:
    static InstanceMemoryUpdateEventHandler &GetInstance(); // L29
    void OnInstanceMemoryUpdate(const Media::Meta &meta);   // L31
    void OnInstanceMemoryReset(const Media::Meta &meta);    // L32
    void OnInstanceRelease(const Media::Meta &meta);        // L33
    void RemoveTimer(pid_t pid);                             // L35
    void AddApp2ExceedThresholdList(pid_t pid);              // L37

private:
    InstanceMemoryUpdateEventHandler();                    // L43
    std::optional<CalculatorType> GetCalculator(const Media::Meta &meta); // L44
    uint32_t GetBlockCount(const Media::Meta &meta);        // L45
    std::optional<InstanceInfo> UpdateInstanceMemory(int32_t instanceId, uint32_t memory); // L46

    static uint32_t SumAppMemory(pid_t callerPid, pid_t actualCallerPid);     // L51
    static void ReportAppMemory(pid_t callerPid, pid_t actualCallerPid, bool isInTimer = true, uint32_t memory = 0); // L52
    void DeterminAppMemoryExceedThresholdAndReport(pid_t callerPid, pid_t forwardCallerPid); // L53

    std::unordered_map<pid_t, std::shared_ptr<AVCodecXcollieTimer>> timerMap_; // L63
    std::unordered_set<pid_t> appMemoryExceedThresholdList_; // L65
```

**Key Design Patterns**:
- `CalculatorType` is a function object that converts block count to bytes
- `timerMap_` tracks per-PID watchdog timers for memory threshold monitoring
- `appMemoryExceedThresholdList_` tracks processes that exceeded memory threshold
- `DeterminAppMemoryExceedThresholdAndReport` uses actualCallerPid (forwardCaller-aware) for correct attribution

### E19: instance_info.h - Include Dependencies

**File**: `services/services/common/instance_info.h`

```cpp
// Line 1-17: Header guard and includes
#ifndef AVCODEC_INSTANCE_INFO_H                            // L1
#define AVCODEC_INSTANCE_INFO_H                           // L2
#include <sys/types.h>                                    // L3
#include <string>                                         // L4
#include "avcodec_log.h"                                  // L5
#include "avcodec_info.h"                                 // L6
#include "meta.h"                                         // L7
#include "meta/meta_key.h"                                // L8
#include "event_info_extented_key.h"                      // L9
```

**Key Design Patterns**:
- `event_info_extented_key.h` included so `GetInstanceIdFromMeta` can reference `EventInfoExtentedKey::INSTANCE_ID`
- `avcodec_info.h` provides `AVCodecType` enum used in `InstanceInfo.codecType`
- `meta.h` and `meta/meta_key.h` provide the metadata infrastructure for event correlation

### E20: event_manager.h - Include Dependencies

**File**: `services/services/common/event_manager/event_manager.h`

```cpp
// Line 1-12: Header guard and includes
#ifndef AVCODEC_EVENT_MANAGER_H                            // L1
#define AVCODEC_EVENT_MANAGER_H                            // L2
#include <mutex>                                           // L7
#include <memory>                                          // L8
#include <string>                                         // L9
#include "meta.h"                                         // L10
#include "event_type.h"                                   // L11
#include "event_info_extented_key.h"                      // L12
```

**Key Design Patterns**:
- `<mutex>` provides `std::mutex` for thread-safe singleton access
- `event_type.h` provides `EventType` and `StatisticsEventType` enums
- `event_info_extented_key.h` provides metadata key constants for event routing

## Architecture Summary

### Instance Information Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    InstanceInfo System                       │
├─────────────────────────────────────────────────────────────┤
│  instance_info.h                                            │
│  ├── InstanceId = int32_t  (global unique identifier)       │
│  ├── CallerInfo: pid/uid/processName                        │
│  ├── InstanceInfo: instanceId + caller + forwardCaller    │
│  │              + codecType + memoryUsage + codecName      │
│  │              + codecCreateTime + videoCodecType         │
│  └── GetInstanceIdFromMeta(meta) → instanceId               │
├─────────────────────────────────────────────────────────────┤
│  event_info_extented_key.h  (30+ metadata keys)            │
│  ├── Instance: INSTANCE_ID, CODEC_TYPE, VIDEO_CODEC_TYPE   │
│  ├── Performance: TOTAL_DECODING_DURATION, TOTAL_CNT       │
│  ├── Speed: SPEED_DECODING_INFO_* (6 tiers: 0.75x-3.00x) │
│  └── Context: WIDTH, HEIGHT, PIXEL_FORMAT, ERROR_CODE       │
├─────────────────────────────────────────────────────────────┤
│  event_manager.h (EventManager singleton)                   │
│  ├── OnInstanceInitEvent      - codec instance created      │
│  ├── OnInstanceReleaseEvent   - codec instance destroyed    │
│  ├── OnInstanceMemoryUpdateEvent  - memory usage changed    │
│  ├── OnInstanceEncodeBeginEvent   - encoding started       │
│  ├── OnInstanceEncodeEndEvent     - encoding finished      │
│  └── OnStatisticsEventSubmit     - periodic stats report   │
├─────────────────────────────────────────────────────────────┤
│  event_type.h (EventType bit-field dispatch)                 │
│  ├── Bit[31:24] = Event category (9 types: INIT→REGISTER_SUBMIT) │
│  └── StatisticsEventType: Category 0-3 with sub-event hierarchy │
├─────────────────────────────────────────────────────────────┤
│  event_handler/ (Specialized handler singletons)           │
│  ├── StatisticsEventInfo       - HiSysEvent上报 + EventHook │
│  ├── InstanceMemoryUpdateEventHandler - 内存阈值监控       │
│  └── InstanceOperationEventHandler   - 编码起止上报       │
└─────────────────────────────────────────────────────────────┘
```

### Multi-Instance Tracking Flow

```
App Process A (pid=1234)
    │
    ├─→ Codec Instance 1 (instanceId=1001, caller.pid=1234)
    │       VideoCodecType::DECODER_HARDWARE
    │
    ├─→ Codec Instance 2 (instanceId=1002, caller.pid=1234)
    │       VideoCodecType::ENCODER_SOFTWARE
    │
Proxy Process (pid=5678, forwardCaller)
    │
    └─→ Codec Instance 3 (instanceId=1003, caller.pid=5678, forwardCaller.pid=1234)
            GetActualCallerPid() → returns 1234 (original caller)
```

### EventType Bit-Field Dispatch

```
OnInstanceEvent(type & EventType::MASK) → switch:
  INSTANCE_INIT          → OnInstanceInitEvent       (populates caller info)
  INSTANCE_RELEASE       → OnInstanceReleaseEvent    (InstanceMemoryUpdateEventHandler)
  INSTANCE_MEMORY_UPDATE → OnInstanceMemoryUpdateEvent (InstanceMemoryUpdateEventHandler)
  INSTANCE_ENCODE_BEGIN  → OnInstanceEncodeBeginEvent  (InstanceOperationEventHandler)
  INSTANCE_ENCODE_END    → OnInstanceEncodeEndEvent    (InstanceOperationEventHandler)
  STATISTICS_EVENT       → OnStatisticsEvent           (StatisticsEventInfo)
  STATISTICS_EVENT_SUBMIT → OnStatisticsEventSubmit    (StatisticsEventInfo)
```

## Relationships

| Related S# | Relationship |
|-----------|-------------|
| S82 | Event/RSS reporting system (EventManager + StatisticsEventHandler) |
| S200/S213 | DFX/HiSysEvent infrastructure |
| S236 | HCodec instance tracking |
| S1/S83 | CAPI/AVCodec lifecycle |
| S95/S164/S201 | IPC/codec client-server |
| S239 | CodecBase instance management |

## Notes

- `forwardCaller` mechanism supports multi-layer proxy scenarios (e.g., camera app → media framework → codec)
- Speed decoding info buckets (0.75x to 3.00x) support adaptive playback quality analysis
- Memory tracking via `memoryUsage` field enables per-instance resource monitoring
- EventManager singleton is thread-safe via `std::mutex` (Meyer's singleton)
- EventType uses 8-bit top nybble for fast switch dispatch, enabling O(1) routing
- StatisticsEventType extends the base with a 3-level hierarchy: MainEvent(8-bit) + SubEvent(8-bit) + Detail(8-bit)
- `AVCodecXcollieTimer` watchdog timer ties memory threshold monitoring to system watchdog
- `EventHook` callback in StatisticsEventInfo enables external event filtering before reporting
