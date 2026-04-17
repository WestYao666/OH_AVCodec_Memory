# B4 Scout Report: AVCodec 新增 DFX 统计事件接入流程

**主题**: 如何在 AVCodec 中新增一个 DFX 统计事件  
**Scout Agent**: B4 Explorer  
**日期**: 2026-04-17  
**证据来源**: /home/west/OH_AVCodec (gitcode.com/openharmony/multimedia_av_codec)

---

## 一、AVCodec DFX 事件框架全貌

AVCodec 的 DFX 事件系统位于 `services/dfx/` 目录，核心文件：

| 文件 | 作用 |
|------|------|
| `services/dfx/include/avcodec_sysevent.h` | 事件 Info 结构体声明 + Write 函数声明 |
| `services/dfx/avcodec_sysevent.cpp` | Write 函数实现（调用 HiSysEventWrite） |
| `hisysevent.yaml`（仓库根目录） | 事件字段类型定义（仅 AV_CODEC domain） |
| `services/dfx/BUILD.gn` | DFX 共享库编译配置 |

---

## 二、现有事件分类（按 HiSysEventWrite 调用方式）

### 类型 A：AV_CODEC domain（走 hisysevent.yaml 声明）
- `CODEC_START_INFO` — BEHAVIOR 级别，CodecDfxInfo 结构体
- `CODEC_STOP_INFO` — BEHAVIOR 级别，仅 clientPid/clientUid/codecInstanceId
- `FAULT` — FAULT 级别，通用故障
- `STATISTICS_INFO` — STATISTIC 级别，聚合统计

### 类型 B：MULTI_MEDIA domain（平台预定义，yaml 中无定义）
- `DEMUXER_FAILURE`
- `AUDIO_CODEC_FAILURE`
- `VIDEO_CODEC_FAILURE`
- `MUXER_FAILURE`
- `RECORD_AUDIO_FAILURE`
- `MEDIAKIT_STATISTICS`
- `SOURCE_STATISTICS`

---

## 三、新增事件的两种路径

### 路径 1：在 AV_CODEC domain 新增事件（需修改 3 个文件）

**Step 1**: 在 `avcodec_sysevent.h` 中定义 Info 结构体 + Write 函数声明  
**Step 2**: 在 `avcodec_sysevent.cpp` 中实现 Write 函数，调用 `HiSysEventWrite(HISYSEVENT_DOMAIN_AVCODEC, ...)`  
**Step 3**: 在 `hisysevent.yaml` 中添加事件名和字段定义（类型/描述）  
**Step 4**: 在调用点填充结构体并调用 Write 函数  
**Step 5**: 确认 DFX 模块构建配置（`services/dfx/BUILD.gn`）已包含对应源文件（通常已包含 avcodec_sysevent.cpp）

> **示例结构**（以 CodecStartEventWrite 为模板）：
> ```cpp
> // avcodec_sysevent.h
> struct MyEventInfo {
>     int32_t fieldA;
>     std::string fieldB;
> };
> void MyEventWrite(MyEventInfo& info);
>
> // avcodec_sysevent.cpp
> void MyEventWrite(MyEventInfo& info) {
>     HiSysEventWrite(HISYSEVENT_DOMAIN_AVCODEC, "MY_EVENT",
>                     OHOS::HiviewDFX::HiSysEvent::EventType::BEHAVIOR,
>                     "FIELD_A", info.fieldA,
>                     "FIELD_B", info.fieldB);
> }
>
> // hisysevent.yaml
> MY_EVENT:
>   __BASE: {type: BEHAVIOR, level: MINOR, desc: xxx}
>   FIELD_A: {type: INT32, desc: xxx}
>   FIELD_B: {type: STRING, desc: xxx}
> ```

### 路径 2：在 MULTI_MEDIA domain 新增事件（仅需修改 .h 和 .cpp）

当事件属于平台级 multimedia domain 时，yaml 不在 AVCodec 仓管理，仅需：
- 在 `avcodec_sysevent.h` 声明结构体和函数
- 在 `avcodec_sysevent.cpp` 实现，使用 `HiSysEventWrite(OHOS::HiviewDFX::HiSysEvent::Domain::MULTI_MEDIA, ...)`
- 调用点调用

---

## 四、CodecDfxInfo 结构体各字段来源分析

```
codecDfxInfo.clientPid         = caller_.pid                          // 从 CodecServer caller_ 成员获取
codecDfxInfo.clientUid         = caller_.uid                          // 同上
codecDfxInfo.codecInstanceId   = FAKE_POINTER(this)                   // this 指针做 ID
codecDfxInfo.codecName         = format.GetStringValue(MD_KEY_CODEC_NAME)
codecDfxInfo.codecIsVendor     = "True"/"False"                       // IS_VENDOR flag
codecDfxInfo.codecMode         = isSurfaceMode_ ? "Surface mode" : "Buffer Mode"
codecDfxInfo.encoderBitRate    = format.GetLongValue(MD_KEY_BITRATE)
codecDfxInfo.videoWidth        = format.GetIntValue(MD_KEY_WIDTH)
codecDfxInfo.videoHeight       = format.GetIntValue(MD_KEY_HEIGHT)
codecDfxInfo.videoFrameRate    = format.GetDoubleValue(MD_KEY_FRAME_RATE)
codecDfxInfo.videoPixelFormat  = PIXEL_FORMAT_STRING_MAP.at(...)       // pixel format int -> string
codecDfxInfo.audioChannelCount= format.GetIntValue(MD_KEY_CHANNEL_COUNT)
codecDfxInfo.audioSampleRate  = format.GetIntValue(MD_KEY_SAMPLE_RATE)
```
**数据来源**: `codecBase_->GetOutputFormat(format)` → Format 对象

---

## 五、关键发现

1. **hisysevent.yaml 中只定义了 4 个 AV_CODEC 事件**，其余 7+ 个事件（DEMUXER_FAILURE 等）使用 MULTI_MEDIA domain，不在本地 yaml 管理
2. **Info 结构体和 Write 函数总是一一配对**，每个事件有独立的结构体（如 DemuxerFaultInfo）和独立的 Write 函数
3. **调用点分散在多个层次**：CodecServer（BEHAVIOR 事件） + media_engine filters（FAULT 事件）
4. **新增事件最小改动**：如果走 AV_CODEC domain，需改 3 个文件（.h / .cpp / yaml）；如果走 MULTI_MEDIA domain，仅需改 2 个文件（.h / .cpp）
5. **无新增事件的显式文档或模板注释**，代码中未发现"如何新增 DFX 事件"的指引，全靠读现有代码理解模式
6. **SourceStatisticsEventWrite 展示了非标准路径**：使用 JSON + 定期批量上报而非每调用的单次上报，带本地聚合逻辑

---

## 六、证据文件索引

| ID | 文件 | 关键内容 |
|----|------|----------|
| E1 | `services/dfx/include/avcodec_sysevent.h` | CodecDfxInfo 结构体定义 |
| E2 | `services/dfx/avcodec_sysevent.cpp` | 全部 11 个 Write 函数实现 |
| E3 | `hisysevent.yaml` | AV_CODEC domain 事件声明 |
| E4 | `services/services/codec/server/video/codec_server.cpp` | GetCodecDfxInfo + CodecStartEventWrite 调用 |
| E5 | `codec_server.cpp` | CodecStopEventWrite 多处调用点 |
| E6 | `media_engine/filters/*.cpp` | 各类 FaultEventWrite 调用点 |
| E7 | `avcodec_sysevent.cpp` | HiSysEventWrite API 调用模式 |
| E8 | `services/dfx/BUILD.gn` | DFX 模块构建配置 |
| E9 | `avcodec_sysevent.cpp` | SourceStatisticsEventWrite 批量上报逻辑 |
| E10 | `avcodec_sysevent.h` | 全部 Write 函数声明列表 |

---

## 七、待确认缺口

1. **MULTI_MEDIA domain 的 hisysevent.yaml 在哪个仓管理？** — 代码仓中未找到，可能在平台层（hiview）或需要向平台申请
2. **新增事件是否需要走代码审查流程中的 DFX Approver？** — 未找到相关流程文档
3. **STATISTICS_INFO 事件是如何被填充和周期性上报的？** — yaml 中有定义，但 avcodec_sysevent.cpp 中未找到对应 Write 函数（可能被 Xcollie 或其他机制驱动）
