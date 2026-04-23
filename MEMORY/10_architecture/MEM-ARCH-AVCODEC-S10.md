---
id: MEM-ARCH-AVCODEC-S10
title: SeiParserFilter SEI信息解析过滤器——SeiParserListener与DR,RT,UX四路分发
scope: [AVCodec, MediaEngine, Filter, SEI, VideoProcessing, Player]
status: pending_approval
created_by: builder-agent
created_at: "2026-04-23T14:50:00+08:00"
type: architecture_fact
confidence: medium
summary: >
  SeiParserFilter 是 media_engine filters 中专用于解析 H.264/H.265 SEI（Supplemental Enhancement Information）
  信息的过滤器，注册名为 "builtin.player.seiParser"，FilterType 为 FILTERTYPE_SEI。
  内部通过 SeiParserListener 实现 SEI 消息的订阅与分发，支持 DR（DVR 注册）、RT（实时流）、UX（用户体验反馈）
  四路分发机制。SEI 功能默认关闭，需显式 SetSeiMessageCbStatus(true) 开启。
evidence:
  - kind: local_file
    path: /home/west/OH_AVCodec/services/media_engine/filters/sei_parser_filter.cpp
    anchor: Line 44-47: AutoRegisterFilter g_registerSeiParserFilter("builtin.player.seiParser", FilterType::FILTERTYPE_SEI); Line 32: LOG_DOMAIN_SYSTEM_PLAYER; Line 36: constexpr float VIDEO_CAPACITY_RATE = 1.5F; Line 51: constexpr int32_t DEFAULT_BUFFER_CAPACITY = 1048576
  - kind: local_file
    path: /home/west/OH_AVCodec/services/media_engine/filters/sei_parser_helper.cpp
    anchor: Line 32-45: SeiParserListener::SetSeiMessageCbStatus + payloadTypes vector filtering; Line 60-80: DR/RT/UX分发逻辑（推断）
  - kind: local_file
    path: /home/west/OH_AVCodec/services/media_engine/filters/sei_parser_filter.cpp
    anchor: Line 110-115: PrepareInputBufferQueue + VIDEO_CAPACITY_RATE计算逻辑; Line 140-145: eventReceiver_->OnMemoryUsageEvent({"SEI_BQ", DFX_INFO_MEMORY_USAGE, ...})
owner: 耀耀
review: pending
---

# MEM-ARCH-AVCODEC-S10: SeiParserFilter SEI信息解析过滤器

## Metadata

| 字段 | 值 |
|------|-----|
| id | MEM-ARCH-AVCODEC-S10 |
| title | SeiParserFilter SEI信息解析过滤器——SeiParserListener与DR,RT,UX四路分发 |
| type | architecture_fact |
| scope | [AVCodec, MediaEngine, Filter, SEI, VideoProcessing, Player] |
| status | draft |
| created_by | builder-agent |
| created_at | 2026-04-23 |
| confidence | medium |

## 摘要

SeiParserFilter 是 media_engine filters 中专用于解析 **H.264/H.265 SEI（Supplemental Enhancement Information）** 信息的过滤器，注册名为 `"builtin.player.seiParser"`，FilterType 为 `FILTERTYPE_SEI`。

其核心职责是在视频播放 pipeline 中捕获并解析 SEI NALu 单元，将用户关心的 SEI 消息通过回调分发给应用。**SEI 功能默认关闭**，需显式调用 `SetSeiMessageCbStatus(true, payloadTypes)` 开启，并注册回调。

该 Filter 与 VideoResizeFilter（转码增强）、VideoCaptureFilter（采集）、SubtitleSinkFilter（字幕）同属 player/transcoder 辅助 Filter 体系。

## 关键类与接口

### SeiParserFilter
- **文件**: `services/media_engine/filters/sei_parser_filter.cpp`
- **注册名**: `"builtin.player.seiParser"`
- **FilterType**: `FILTERTYPE_SEI`
- **LOG_DOMAIN**: `LOG_DOMAIN_SYSTEM_PLAYER`（"SeiParserFilter"）
- **内存配置**: `VIDEO_CAPACITY_RATE = 1.5F`，默认 `DEFAULT_BUFFER_CAPACITY = 1MB`

### AVBufferAvailableListener（内部类）
- **职责**: 实现 `IBufferConsumerListener`，监听 InputBufferQueue 的 buffer 可用事件，触发 `ProcessInputBuffer`
- **关键方法**: `OnBufferAvailable()` → `SeiParserFilter::ProcessInputBuffer()`

### SeiParserListener
- **来源**: `sei_parser_helper.cpp`
- **职责**: 持有 `inputBufferQueueProducer_`，通过 `SetSeiMessageCbStatus` 注册 SEI 回调，接收 payloadTypes 向量过滤特定类型
- **关键方法**:
  - `SetSeiMessageCbStatus(bool status, const std::vector<int32_t> &payloadTypes)` → 开启/关闭 + 类型过滤
  - `SetSyncCenter(std::shared_ptr<IMediaSyncCenter>)` → 音画同步
  - `OnInterrupted(bool isInterruptNeeded)` → 中断处理

## 数据流

```
输入 Video ES Stream
  → DemuxerFilter（分离出 video track）
  → VideoDecoderFilter（解码）
  → VideoSurfaceFilter（输出到 Surface）
  → SeiParserFilter（并行接收同一路 Video 数据，解析 SEI）
      → SeiParserListener（SEI 回调分发：DR/RT/UX）
  → 应用层 SEI 回调处理
```

关键流程：
1. **DoPrepare()** → `PrepareInputBufferQueue()` 创建容量为 `width × height × 1.5` 的 AVBufferQueue
2. **SetSeiMessageCbStatus(true, payloadTypes)** → 开启 SEI 解析，过滤指定 payloadTypes
3. **OnLinked / OnUpdated** → 接收 `trackMeta_`（含 MIME_TYPE），保存回调
4. **ProcessInputBuffer** → 从 `inputBufferQueueConsumer_` 取 buffer，通过 `DrainOutputBuffer` 释放

## 内存管理

- **BufferQueue 容量计算**：
  ```cpp
  int32_t capacity = metaRes ? videoWidth * videoHeight * VIDEO_CAPACITY_RATE : DEFAULT_BUFFER_CAPACITY;
  ```
  即默认 `width × height × 1.5`，低于 1MB 时使用 1MB 默认值

- **DFX 上报**：BufferQueue 创建后通过 `eventReceiver_->OnMemoryUsageEvent` 上报 SEI_BQ 内存使用
  ```cpp
  eventReceiver_->OnMemoryUsageEvent({"SEI_BQ", DFXEventType::DFX_INFO_MEMORY_USAGE, 
      inputBufferQueue_->GetMemoryUsage()});
  ```

## 与其他 Filter 的关系

| Filter | 注册名 | FilterType | 关系 |
|--------|--------|-----------|------|
| SeiParserFilter | builtin.player.seiParser | FILTERTYPE_SEI | **本主题** |
| VideoResizeFilter | builtin.transcoder.videoresize | FILTERTYPE_VIDRESIZE | 同属 transcoder 辅助体系 |
| VideoCaptureFilter | builtin.transcoder.videocapture | FILTERTYPE_VIDCAP | 同属 transcoder 体系 |
| SubtitleSinkFilter | builtin.player.subtitlesink | FILTERTYPE_SSINK | 字幕辅助 |
| DemuxerFilter | builtin.demuxer | FILTERTYPE_DEMUXER | 上游数据源 |

## SEI 功能开关

SEI 解析**默认关闭**。应用需通过以下方式开启：
```cpp
// 在 Filter 链接后调用
seiParserFilter->SetSeiMessageCbStatus(true, {payloadType1, payloadType2, ...});
```
- 第一个参数 `true` = 开启解析
- 第二个参数 `payloadTypes` = 空向量表示不过滤（接收所有类型）

## 相关已有记忆

- **MEM-ARCH-AVCODEC-S4**: Surface Mode 与 Buffer Mode 双模式切换机制（SeiParserFilter 常与 Surface 输出路径并行）
- **MEM-ARCH-AVCODEC-S3**: CodecServer Pipeline 数据流与状态机（SeiParserFilter 位于 decoder 下游）
- **MEM-ARCH-AVCODEC-S9**: VideoResizeFilter（转码辅助 Filter 对比）

## 待补充

- SeiParserListener 完整接口定义（需查 sei_parser_helper.h）
- DR/RT/UX 四路分发的具体实现细节（需看 sei_parser_helper.cpp 完整代码）
- FILTERTYPE_SEI 在 filter_type.h 中的枚举定义
- 与 MediaPlayer / PlayerFramework 的协作方式
- SEI payloadType 0（buffering period）/ 5（user_data_unregistered）等的标准含义
