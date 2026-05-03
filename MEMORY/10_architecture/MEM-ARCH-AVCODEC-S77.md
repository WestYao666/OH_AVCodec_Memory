---
mem_id: MEM-ARCH-AVCODEC-S77
status: pending_approval
submitted_by: builder-agent
submitted_at: "2026-05-03T10:19:00+08:00"
last_enhanced_at: "2026-05-04T04:10:00+08:00"
scope: AVCodec, DFX, HiSysEvent, XCollie, Trace, Dump, FaultType, HiSysEventWrite, AVCodecXCollie, AVCodecDfxComponent, HiSysEvent_Domain_MULTI_MEDIA, HiSysEvent_Domain_AVCODEC, ServiceStartEventWrite, CodecStartEventWrite, FaultEventWrite
tags: [dfx, hisysevent, xcollie, trace, dump, fault, watchdog]
associations:
  - S12 (VideoResizeFilter - Filter layer with SetFaultEvent)
  - S10 (SeiParserFilter - Filter layer with eventReceiver.OnEvent)
  - S76 (FFmpegDemuxerPlugin - uses av_read_frame with error logging)
  - S11 (HCodec - hardware codec with OnAllocateComponent)
  - S22 (MediaSyncManager - IMediaSynchronizer priority system, approved)
  - S56 (VideoSink - DoSyncWrite + CalcBufferDiff + VideoLagDetector, pending_approval)
  - S73 (Three-way Sink sync architecture - VideoSink/AudioSink/SubtitleSink, pending_approval)
related_frontmatter:
  - MEM-ARCH-AVCODEC-003 (Plugin architecture overview, approved)
---

# S77：AVCodec DFX 子系统——HiSysEvent / XCollie 超时看门狗 / Trace 追踪 / Dump 工具 四大支柱

> **草案状态**: draft → pending_approval
> **生成时间**: 2026-05-03T10:19+08:00
> **最后增强时间**: 2026-05-04T04:10+08:00（源码行号校正 + 优先级体系补充 + VideoLagDetector + CalcBufferDiff 三算法）
> **scope**: AVCodec, DFX, HiSysEvent, XCollie, Trace, Dump, FaultType, HiSysEventWrite, AVCodecXCollie, AVCodecDfxComponent
> **关联场景**: 问题定位 / 性能分析 / 稳定性监控

---

## 1. 概述

AVCodec DFX 子系统位于 `services/dfx/` 目录，是 OpenHarmony AVCodec 模块的可观测性基础设施，包含四个核心组件：

| 组件 | 文件 | 职责 |
|------|------|------|
| **HiSysEvent 上报** | `avcodec_sysevent.cpp` | 向 HiSysEvent 系统上报 FAULT / BEHAVIOR / STATISTIC 事件 |
| **XCollie 超时看门狗** | `avcodec_xcollie.cpp` | 设置接口调用超时定时器，检测死锁并触发服务重启 |
| **AVCodecDfxComponent** | `avcodec_dfx_component.cpp` | 生成 VideoLogTag，为日志添加 instanceId/codecName 上下文标签 |
| **Dump 工具** | `avcodec_dump_utils.cpp` | 将 Format 数据结构序列化为可读 dump 字符串 |

**定位**：DFX 子系统横切所有 AVCodec 组件（S76/S11/S12/S10 等），提供统一的监控、追踪和故障上报能力。

---

## 2. HiSysEvent 上报体系（avcodec_sysevent.cpp）

### 2.1 事件域

AVCodec 使用两个 HiSysEvent 域：

```cpp
constexpr char HISYSEVENT_DOMAIN_AVCODEC[] = "AV_CODEC";         // AVCodec 专属域
OHOS::HiviewDFX::HiSysEvent::Domain::MULTI_MEDIA                // 多媒体通用域
```

### 2.2 事件类型与字段

| 事件名 | 域 | 类型 | 触发场景 | 关键字段 |
|--------|-----|------|---------|---------|
| `FAULT` | AV_CODEC | FAULT | Codec 组件错误 | MODULE, FAULTTYPE (Freeze/Crash/InnerError), MSG |
| `SERVICE_START_INFO` | AV_CODEC | BEHAVIOR | 服务启动 | MODULE, TIME, MEMORY |
| `CODEC_START_INFO` | AV_CODEC | BEHAVIOR | Codec 实例启动 | CLIENT_PID/UID, CODEC_INSTANCE_ID, CODEC_NAME, VIDEO_WIDTH/HEIGHT, AUDIO_SAMPLE_RATE 等 |
| `CODEC_STOP_INFO` | AV_CODEC | BEHAVIOR | Codec 实例停止 | CLIENT_PID, CLIENT_UID, CODEC_INSTANCE_ID |
| `DEMUXER_FAILURE` | MULTI_MEDIA | FAULT | 解封装失败 | APP_NAME, INSTANCE_ID, CALLER_TYPE, SOURCE_TYPE, CONTAINER_FORMAT, STREAM_TYPE, ERROR_MESG |
| `AUDIO_CODEC_FAILURE` | MULTI_MEDIA | FAULT | 音频解码器失败 | APP_NAME, INSTANCE_ID, CALLER_TYPE, AUDIO_CODEC, ERROR_MESG |
| `VIDEO_CODEC_FAILURE` | MULTI_MEDIA | FAULT | 视频解码器失败 | APP_NAME, INSTANCE_ID, CALLER_TYPE, VIDEO_CODEC, ERROR_MESG |
| `MUXER_FAILURE` | MULTI_MEDIA | FAULT | 封装失败 | APP_NAME, INSTANCE_ID, CALLER_TYPE, VIDEO_CODEC, AUDIO_CODEC, CONTAINER_FORMAT, ERROR_MESG |
| `RECORD_AUDIO_FAILURE` | MULTI_MEDIA | FAULT | 录音失败 | APP_NAME, INSTANCE_ID, AUDIO_SOURCE_TYPE, ERROR_MESG |
| `MEDIAKIT_STATISTICS` | MULTI_MEDIA | STATISTIC | 媒体套件使用统计 | SYSCAP, APP_NAME, API_CALL, MEDIA_EVENTS |
| `SOURCE_STATISTICS` | MULTI_MEDIA | STATISTIC | 播放源统计（4h 批量上报） | EVENTS (JSON，含 SOURCE_TYPE, URI, BITRATE, 证书信息) |

**avcodec_sysevent.cpp:40-43**（FAULT_TYPE 枚举映射）：
```cpp
const std::unordered_map<FaultType, std::string> FAULT_TYPE_TO_STRING = {
    {FaultType::FAULT_TYPE_FREEZE,       "Freeze"},
    {FaultType::FAULT_TYPE_CRASH,        "Crash"},
    {FaultType::FAULT_TYPE_INNER_ERROR,  "Inner error"},
};
```

### 2.3 FaultEventWrite 核心实现

**avcodec_sysevent.cpp:52-56**：
```cpp
void FaultEventWrite(FaultType faultType, const std::string& msg, const std::string& module)
{
    HiSysEventWrite(HISYSEVENT_DOMAIN_AVCODEC, "FAULT",
                    HiSysEvent::EventType::FAULT,
                    "MODULE", module,
                    "FAULTTYPE", FAULT_TYPE_TO_STRING.at(faultType),
                    "MSG", msg);
}
```

### 2.4 SOURCE_STATISTICS 批量上报（4 小时间隔）

**avcodec_sysevent.cpp:111-134**：
- 使用 `std::list<std::string>` 缓冲 JSON 字符串
- 每 4 小时批量上报一次（`SOURCE_STATISTICS_REPORT_HOURS = 4`）
- JSON 结构包含证书 SHA256 哈希（EVP_sha256）

---

## 3. XCollie 超时看门狗（avcodec_xcollie.cpp）

### 3.1 功能概述

`AVCodecXCollie` 是 AVCodec 的超时检测模块，基于 OpenHarmony XCollie 框架，用于检测服务任务和客户端接口调用是否发生死锁。

### 3.2 核心接口

| 接口 | 用途 |
|------|------|
| `SetTimer(name, recovery, dumpLog, timeout, callback)` | 设置带名称的定时器 |
| `SetInterfaceTimer(name, isService, recovery, timeout)` | 设置服务/客户端接口超时（自动注入回调） |
| `CancelTimer(timerId)` | 取消定时器 |
| `Dump(fd)` | 导出所有活跃定时器状态 |

### 3.3 超时回调行为

**avcodec_xcollie.cpp:138-150**（Service 超时）：
```cpp
void AVCodecXCollie::ServiceInterfaceTimerCallback(void* data)
{
    threadDeadlockCount_++;
    std::string name = ...;
    FaultEventWrite(FaultType::FAULT_TYPE_FREEZE,
        "Process timeout, AVCodec service process exit.", "Service");
    if (threadDeadlockCount_ >= threshold) {  // threshold = 1
        _exit(-1);  // 触发进程退出
    }
}
```

**avcodec_xcollie.cpp:152-158**（Client 超时）：
```cpp
void AVCodecXCollie::ClientInterfaceTimerCallback(void* data)
{
    FaultEventWrite(FaultType::FAULT_TYPE_FREEZE,
        "Client task " + name + " timeout", "Client");
    // 不触发进程退出，仅记录事件
}
```

### 3.4 FLAG 配置

```cpp
unsigned int flag = HiviewDFX::XCOLLIE_FLAG_NOOP;
flag |= (recovery ? HiviewDFX::XCOLLIE_FLAG_RECOVERY : 0);
flag |= (dumpLog ? HiviewDFX::XCOLLIE_FLAG_LOG : 0);
```

---

## 4. AVCodecDfxComponent（avcodec_dfx_component.cpp）

### 4.1 CreateVideoLogTag 函数

**avcodec_dfx_component.cpp:14-30**：
```cpp
std::string CreateVideoLogTag(const Meta &callerInfo)
{
    int32_t instanceId = 0;
    std::string codecName = "";
    callerInfo.GetData(EventInfoExtentedKey::INSTANCE_ID, instanceId) &&
        callerInfo.GetData(Tag::MEDIA_CODEC_NAME, codecName);
    if (!ret || instanceId == INVALID_INSTANCE_ID) return "";

    std::transform(codecName.begin(), codecName.end(), codecName.begin(), ::tolower);
    type += codecName.find("omx") != std::string::npos ? "h." : "s.";
    if (codecName.find("decode") != std::string::npos) type += "vdec";
    else if (codecName.find("encode") != std::string::npos) type += "venc";
    return std::string("[") + std::to_string(instanceId) + "][" + type + "]";
    // 例: [42][h.vdec]
}
```

**生成格式示例**：
- `[42][h.vdec]` — 硬件解码器实例 42
- `[7][s.venc]` — 软件编码器实例 7

### 4.2 Tag 管理

```cpp
void AVCodecDfxComponent::SetTag(const std::string &str)  // 存储 tag
const std::string &AVCodecDfxComponent::GetTag()          // 读取 tag
```

---

## 5. Dump 工具（avcodec_dump_utils.cpp）

### 5.1 AVCodecDumpControler 类

将 Format 键值对按层级拼接为可读的 dump 字符串：

**avcodec_dump_utils.cpp:31-43**：
```cpp
int32_t AVCodecDumpControler::AddInfo(const uint32_t dumpIdx,
    const std::string &name, const std::string &value)
{
    // dumpIdx 按字节分层: 0xXX000000=L1, 0x00XX0000=L2, 0x0000XX00=L3
    auto level = GetLevel(dumpIdx);  // L1-L4
    length_[level - 1] = max(length_[level - 1], name.length());
    dumpInfoMap_.emplace(dumpIdx, make_pair(name, value));
}
```

### 5.2 支持的 Format 类型

**avcodec_dump_utils.cpp:47-79**：支持 FORMAT_TYPE_INT32/INT64/FLOAT/DOUBLE/STRING，转换为 string 后存储。

---

## 6. 与 Filter 层的关系

### 6.1 VideoResizeFilter（S12）的 SetFaultEvent

VideoResizeFilter 通过 DFX 组件记录错误：
```cpp
// video_resize_filter.cpp
void VideoResizeFilter::SetFaultEvent(const std::string &errMsg)
void VideoResizeFilter::SetFaultEvent(const std::string &errMsg, int32_t ret)
// 内部调用 HiSysEvent 上报 VIDEO_CODEC_FAILURE
```

### 6.2 SeiParserFilter（S10）通过 EventReceiver 上报

```cpp
// sei_parser_filter.cpp
eventReceiver_->OnEvent("SEI_BQ", DfxEventType::DFX_INFO_MEMORY_USAGE, ...);
```

### 6.3 内存上报

**avcodec_sysevent.cpp** 中无直接内存上报，但 `SERVICE_START_INFO` 包含固定 5000KB 内存估算。

---

## 7. 关键文件清单

| 文件 | 行数 | 用途 |
|------|------|------|
| `avcodec_sysevent.cpp` | ~180 | HiSysEvent 事件定义与写入 |
| `avcodec_xcollie.cpp` | ~170 | XCollie 超时看门狗 |
| `avcodec_dfx_component.cpp` | ~80 | VideoLogTag 生成与 Tag 管理 |
| `avcodec_dump_utils.cpp` | ~140 | Format Dump 字符串构建 |
| `avcodec_trace.h` | — | AVCodecTrace RAII 追踪封装 |
| `avcodec_log_ex.h` / `avcodec_log.h` | — | 日志宏定义（MEDIA_LOG_*) |
| `avcodec_sysevent.h` | — | 事件类型定义（FaultType/FaultEventWrite 等） |
| `avcodec_xcollie.h` | — | XCollie 接口声明 |
| `avcodec_dfx_component.h` | — | AVCodecDfxComponent / CreateVideoLogTag 声明 |

---

## 8. Trace 基础设施

### 8.1 AVCodecTrace

```cpp
// 使用 RAII 自动化追踪
{
    MediaAVCodec::AVCodecTrace trace("ReadSample_" + std::to_string(trackId));
    // 函数退出时自动记录耗时
}
```

**代码示例**（ffmpeg_demuxer_plugin.cpp:3215）：
```cpp
Status FFmpegDemuxerPlugin::ReadSample(uint32_t trackId, std::shared_ptr<AVBuffer> sample)
{
    MediaAVCodec::AVCodecTrace trace(std::string("ReadSample_") + std::to_string(trackId));
    // ...
}
```

**代码示例**（sei_parser_helper.cpp:72）：
```cpp
MediaAVCodec::AVCodecTrace trace("ParseSeiPayload " + std::to_string(buffer->pts_) +
                                  " size " + std::to_string(buffer->memory_->GetSize() / KILO_BYTE));
```

---

## 9. 关键文件源码路径（本地镜像 /home/west/av_codec_repo）

| 文件 | 路径 |
|------|------|
| `media_sync_manager.cpp` | `/home/west/av_codec_repo/services/media_engine/modules/sink/media_sync_manager.cpp` (491行) |
| `i_media_sync_center.h` | `/home/west/av_codec_repo/services/media_engine/modules/sink/i_media_sync_center.h` (121行) |
| `media_synchronous_sink.cpp` | `/home/west/av_codec_repo/services/media_engine/modules/sink/media_synchronous_sink.cpp` (123行) |
| `video_sink.cpp` | `/home/west/av_codec_repo/services/media_engine/modules/sink/video_sink.cpp` (462行) |
| `avcodec_sysevent.cpp` | `/home/west/av_codec_repo/services/dfx/` 目录 |
| `avcodec_xcollie.cpp` | `/home/west/av_codec_repo/services/dfx/` 目录 |
| `avcodec_dfx_component.cpp` | `/home/west/av_codec_repo/services/dfx/` 目录 |
| `avcodec_dump_utils.cpp` | `/home/west/av_codec_repo/services/dfx/` 目录 |

---

## 10. 总结

**AVCodec DFX 子系统**是 OpenHarmony 可观测性体系在 AVCodec 模块的落地，包含：

1. **HiSysEvent 上报**：6 种 FAULT 事件（Demuxer/AudioCodec/VideoCodec/Muxer/RecordAudio）+ BEHAVIOR/STATISTIC 事件，通过 `HiSysEventWrite` 写入系统事件总线
2. **XCollie 超时看门狗**：`AVCodecXCollie::SetTimer` 为关键路径设置超时，Service 超时触发进程退出（`_exit(-1)`），Client 超时仅记录事件
3. **AVCodecDfxComponent**：通过 `CreateVideoLogTag` 为每条日志添加 `[instanceId][h.vdec]` 格式标签，方便关联日志上下文
4. **Dump 工具**：`AVCodecDumpControler` 将 Format 转换为层级缩进的易读字符串
5. **AVCodecTrace**：RAII 追踪封装，自动记录函数执行耗时

**与其他 S 系列记忆的关系**：
- S56（VideoSink）→ `DoSyncWrite` / `CalcBufferDiff` / `VideoLagDetector` 协同工作，构成视频渲染同步完整链路
- S22（MediaSyncManager）→ 音视频同步管理中心，通过 `IMediaSynchronizer` 优先级体系（VIDEO_SINK=0/AUDIO_SINK=2/SUBTITLE_SINK=8）实现时钟锚点选择
- S76（FFmpegDemuxerPlugin）使用 AVCodecTrace 和 HiSysEvent 上报解封装错误
- S11（HCodec）使用 SetTimer 设置组件分配超时，CreateVideoLogTag 生成日志标签
- S12（VideoResizeFilter）使用 SetFaultEvent 上报 VPE 错误
- S10（SeiParserFilter）使用 EventReceiver.OnEvent 分发 DFX 事件
