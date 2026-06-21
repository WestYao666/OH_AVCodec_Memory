# MEM-ARCH-AVCODEC-S247: AVCodec Instance Information Management

## Basic Information

| Field | Value |
|-------|-------|
| status | draft |
| mem_id | MEM-ARCH-AVCODEC-S247 |
| topic | AVCodec Instance Information Management - instance_info.h & EventManager instance lifecycle tracking system |
| source | GitCode (https://gitcode.com/openharmony/multimedia_av_codec) |
| created_by | builder-agent |
| timestamp | 2026-06-21T23:46:00+08:00 |

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

### E1: instance_info.h - Core Instance Tracking Data Structures

**File**: `services/services/common/instance_info.h`

```cpp
// Line 1-87 (full file ~87 lines)
// Core type definitions for instance tracking

using InstanceId = int32_t;                              // L18
constexpr pid_t INVALID_PID = -1;                         // L19
constexpr InstanceId INVALID_INSTANCE_ID = -1;            // L20

enum class VideoCodecType : int16_t {                     // L22-28
    UNKNOWN,
    DECODER_HARDWARE,
    DECODER_SOFTWARE,
    ENCODER_HARDWARE,
    ENCODER_SOFTWARE,
    END,
};

struct CallerInfo {                                        // L30-34
    pid_t pid = -1;
    uid_t uid = 0;
    std::string processName = "";
};

struct InstanceInfo {                                      // L36-62
    InstanceId instanceId = INVALID_INSTANCE_ID;
    CallerInfo caller;
    CallerInfo forwardCaller;
    AVCodecType codecType;
    uint32_t memoryUsage = 0;
    std::string codecName = "";
    std::time_t codecCreateTime = 0;
    VideoCodecType videoCodecType = VideoCodecType::UNKNOWN;
    
    void Print() { ... }                                  // L47-53
    pid_t GetActualCallerPid() const;                      // L55-60
    std::string GetActualCallerProcessName() const;       // L62-68
};
```

**Key Design Patterns**:
- `InstanceId = int32_t` - single global identifier for each codec instance
- `CallerInfo` - tracks caller process info (pid, uid, processName)
- `forwardCaller` - supports multi-layer proxy calls (e.g., caller → proxy → codec)
- `GetActualCallerPid()` - resolves forwardCaller if set, otherwise returns caller
- `VideoCodecType` enum - distinguishes hardware/software and encoder/decoder

### E2: instance_info.h - Meta Data Extraction Utility

**File**: `services/services/common/instance_info.h`

```cpp
// Line 70-76: GetInstanceIdFromMeta - extract instance ID from metadata

[[maybe_unused]] static int32_t GetInstanceIdFromMeta(const Media::Meta &meta)  // L70
{
    auto instanceId = INVALID_INSTANCE_ID;
    meta.GetData(EventInfoExtentedKey::INSTANCE_ID.data(), instanceId);
    return instanceId;
}
```

**Purpose**: Extract instance ID from event metadata, enabling event-to-instance correlation

### E3: event_info_extented_key.h - Instance Event Extended Keys

**File**: `services/services/common/event_manager/event_info_extented_key.h`

```cpp
// Line 1-62 (full file ~62 lines)
// Extended event info keys for codec instance metadata

class EventInfoExtentedKey {                              // L10-60
public:
    static constexpr std::string_view INSTANCE_ID = "av_codec_event_info_instance_id";  // L13
    static constexpr std::string_view CODEC_TYPE = "av_codec_event_info_codec_type";    // L14
    static constexpr std::string_view IS_HARDWARE = "IS_VENDOR";                        // L15
    static constexpr std::string_view BIT_DEPTH = "av_codec_event_info_bit_depth";      // L16
    static constexpr std::string_view ENABLE_POST_PROCESSING = "...";                   // L17
    static constexpr std::string_view PIXEL_FORMAT_STRING = "pixel_format_string";      // L18
    static constexpr std::string_view IS_ENCODER = "is_encoder";                        // L19
    static constexpr std::string_view CODEC_ERROR_CODE = "codec_error_code";            // L20
    static constexpr std::string_view VIDEO_COD_TYPE = "av_codec_event_info_video_codec_type";  // L21
    static constexpr std::string_view APP_ELAPSED_TIME_IN_BG = "app_elapsed_time_in_bg";        // L22
    static constexpr std::string_view TOTAL_DECODING_DURATION = "total_decoding_duration";        // L23
    static constexpr std::string_view TOTAL_DECODING_CNT = "total_decoding_cnt";                // L24
    // Speed decoding info: 0.75x/1.00x/1.25x/1.50x/2.00x/3.00x    // L25-30
    static constexpr std::string_view SPEED_DECODING_INFO_TOTAL = "speed_decoding_info_total";  // L25
    static constexpr std::string_view SPEED_DECODING_INFO_0_75X = "speed_decoding_info_0_75x";  // L26
    // ... more speed buckets
    static constexpr std::string_view CODEC_MODE = "av_codec_event_info_codec_mode";      // L31
    static constexpr std::string_view RESOLUTION_LEVEL = "av_codec_event_info_resolution_level"; // L32
    static constexpr std::string_view INSTANCE_ACTION = "av_codec_event_info_instance_action";     // L36
    static constexpr std::string_view APP_INDEX = "av_codec_event_info_app_index";               // L38
};
```

**Key Design Patterns**:
- String-based key registry for type-safe metadata access
- Instance-level keys: INSTANCE_ID, CODEC_TYPE, IS_HARDWARE
- Performance keys: TOTAL_DECODING_DURATION, TOTAL_DECODING_CNT
- Speed buckets: 6 speed tiers (0.75x to 3.00x) for adaptive playback analysis
- Resolution level tracking for quality monitoring

### E4: event_manager.h - Event Manager Singleton Interface

**File**: `services/services/common/event_manager/event_manager.h`

```cpp
// Line 1-70 (full file ~70 lines)
#ifndef AVCODEC_EVENT_MANAGER_H                              // L1
#define AVCODEC_EVENT_MANAGER_H

#include <mutex>                                             // L7
#include <memory>
#include <string>
#include "meta.h"                                             // L10
#include "event_type.h"
#include "event_info_extented_key.h"

class EventManager {                                         // L14-69
public:
    static EventManager &GetInstance();                      // L16: Singleton access
    
    // Basic instance events
    void OnInstanceEvent(EventType type);                   // L17
    void OnInstanceEvent(EventType type, Media::Meta &meta); // L18
    
    // Statistics events
    void OnInstanceEvent(StatisticsEventType type);          // L19
    void OnInstanceEvent(StatisticsEventType type, Media::Meta &meta);  // L20

private:
    EventManager() {}                                       // L23: Private constructor (singleton)
    
    // Extended event handlers (L27-34)
    void OnInstanceInitEvent(Media::Meta &meta);            // L28
    void OnInstanceReleaseEvent(Media::Meta &meta);          // L29
    void OnInstanceMemoryUpdateEvent(Media::Meta &meta);     // L30
    void OnInstanceMemoryResetEvent(Media::Meta &meta);     // L31
    void OnInstanceEncodeBeginEvent(Media::Meta &meta);      // L32
    void OnInstanceEncodeEndEvent(Media::Meta &meta);        // L33
    void OnStatisticsEvent(StatisticsEventType type, Media::Meta &meta);  // L34
    void OnStatisticsEventSubmit();                          // L35
    void OnStatisticsEventRegisterSubmit();                  // L36
};
```

**Key Design Patterns**:
- Singleton pattern via `GetInstance()` and private constructor
- Dual event type system: `EventType` (lifecycle) and `StatisticsEventType` (performance)
- Metadata-driven events via `Media::Meta` parameter
- Separate handlers for Init/Release/Memory/Encode lifecycle stages

## Architecture Summary

### Instance Information Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    InstanceInfo System                       │
├─────────────────────────────────────────────────────────────┤
│  instance_info.h                                            │
│  ├── InstanceId = int32_t  (global unique identifier)       │
│  ├── CallerInfo: pid/uid/processName                        │
│  ├── InstanceInfo: instanceId + caller + forwardCaller      │
│  │              + codecType + memoryUsage + codecName      │
│  │              + codecCreateTime + videoCodecType         │
│  └── GetInstanceIdFromMeta(meta) → instanceId               │
├─────────────────────────────────────────────────────────────┤
│  event_info_extented_key.h  (30+ metadata keys)            │
│  ├── Instance: INSTANCE_ID, CODEC_TYPE, VIDEO_CODEC_TYPE   │
│  ├── Performance: TOTAL_DECODING_DURATION, TOTAL_CNT       │
│  ├── Speed: SPEED_DECODING_INFO_* (6 tiers: 0.75x-3.00x) │
│  └── Context: WIDTH, HEIGHT, PIXEL_FORMAT, ERROR_CODE      │
├─────────────────────────────────────────────────────────────┤
│  event_manager.h (EventManager singleton)                   │
│  ├── OnInstanceInitEvent      - codec instance created      │
│  ├── OnInstanceReleaseEvent   - codec instance destroyed    │
│  ├── OnInstanceMemoryUpdateEvent  - memory usage changed    │
│  ├── OnInstanceEncodeBeginEvent   - encoding started        │
│  ├── OnInstanceEncodeEndEvent     - encoding finished       │
│  └── OnStatisticsEventSubmit     - periodic stats report    │
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

## Relationships

| Related S# | Relationship |
|-----------|-------------|
| S82 | Event/RSS reporting system |
| S200/S213 | DFX/HiSysEvent infrastructure |
| S236 | HCodec instance tracking |
| S1/S83 | CAPI/AVCodec lifecycle |
| S95/S164/S201 | IPC/codec client-server |
| S239 | CodecBase instance management |

## Notes

- `forwardCaller` mechanism supports multi-layer proxy scenarios (e.g., camera app → media framework → codec)
- Speed decoding info buckets support adaptive playback quality analysis
- Memory tracking via `memoryUsage` field enables per-instance resource monitoring
- EventManager singleton is thread-safe via `std::mutex`
