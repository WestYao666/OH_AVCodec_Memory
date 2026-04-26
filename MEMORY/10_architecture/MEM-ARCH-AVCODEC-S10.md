---
id: MEM-ARCH-AVCODEC-S10
title: SeiParserFilter SEI信息解析过滤器——SeiParserListener与SEI事件分发机制
scope: [AVCodec, MediaEngine, Filter, SEI, VideoProcessing, Player, HEVC, H.264]
status: pending_approval
created_by: builder-agent
created_at: "2026-04-23T14:50:00+08:00"
updated_at: "2026-04-26T13:10:00+08:00"
type: architecture_fact
confidence: high
summary: >
  SeiParserFilter 是 media_engine filters 中专用于解析 H.264/H.265 SEI（Supplemental Enhancement Information）
  信息的过滤器，注册名为 "builtin.player.seiParser"，FilterType 为 FILTERTYPE_SEI。
  内部通过 AvcSeiParserHelper / HevcSeiParserHelper 解析 SEI NALu，通过 SeiParserListener::OnBufferFilled
  接收视频 buffer 并解析 SEI payload，最终通过 EventReceiver 发射 EVENT_SEI_INFO 事件。
  SEI 功能默认关闭，需显式 SetSeiMessageCbStatus(true) 开启，并可指定 payloadTypes 向量过滤特定类型。
  支持 FlowLimit 机制（基于 IMediaSyncCenter 音画同步），以及 payloadType 5 (user_data_unregistered) 等标准类型。
evidence:
  - kind: local_file
    path: /home/west/OH_AVCodec/interfaces/inner_api/native/sei_parser_filter.h
    anchor: Line 19-22: class SeiParserFilter : public Filter; Line 33: SetSeiMessageCbStatus(bool, vector<int32_t>); Line 36: SetSyncCenter(shared_ptr<IMediaSyncCenter>); Line 46: seiMessageCbStatus_ = false (default off)
  - kind: local_file
    path: /home/west/OH_AVCodec/interfaces/inner_api/native/sei_parser_helper.h
    anchor: Line 48: class AvcSeiParserHelper; Line 53: class HevcSeiParserHelper; Line 66: struct SeiPayloadInfo {int32_t payloadType; shared_ptr<AVBuffer> payload;}; Line 70: struct SeiPayloadInfoGroup {int64_t playbackPosition; vector<SeiPayloadInfo> vec;}; Line 78: class SeiParserListener : public IBrokerListener
  - kind: local_file
    path: /home/west/OH_AVCodec/services/media_engine/filters/sei_parser_filter.cpp
    anchor: "Line 37-39: static AutoRegisterFilter g_registerSeiParserFilter(\"builtin.player.seiParser\", FilterType::FILTERTYPE_SEI); Line 32: LOG_DOMAIN_SYSTEM_PLAYER; Line 44: constexpr float VIDEO_CAPACITY_RATE = 1.5F; Line 45: constexpr int32_t DEFAULT_BUFFER_CAPACITY = 1024*1024"
  - kind: local_file
    path: /home/west/OH_AVCodec/services/media_engine/filters/sei_parser_filter.cpp
    anchor: "Line 130-134: capacity = metaRes ? videoWidth * videoHeight * VIDEO_CAPACITY_RATE : DEFAULT_BUFFER_CAPACITY; Line 159-162: sptr<IConsumerListener> listener = new AVBufferAvailableListener; inputBufferQueueConsumer_->SetBufferAvailableListener(listener);"
  - kind: local_file
    path: /home/west/OH_AVCodec/services/media_engine/filters/sei_parser_filter.cpp
    anchor: "Line 195-197: Status SetSeiMessageCbStatus(bool status, vector<int32_t> payloadTypes); producerListener_ = new SeiParserListener(codecMimeType_, inputBufferQueueProducer_, eventReceiver_, true); producerListener_->SetSeiMessageCbStatus(status, payloadTypes);"
  - kind: local_file
    path: /home/west/OH_AVCodec/services/media_engine/filters/sei_parser_helper.cpp
    anchor: "Line 51-62: AvcSeiParserHelper::IsSeiNalu: AVC_SEI_TYPE=0x06, AVC_NAL_UNIT_TYPE_FLAG=0x9F; HevcSeiParserHelper: HEVC_SEI_TYPE_ONE=0x4E, HEVC_SEI_TYPE_TWO=0x50"
  - kind: local_file
    path: /home/west/OH_AVCodec/services/media_engine/filters/sei_parser_helper.cpp
    anchor: "Line 90-110: ParseSeiPayload: FindNextSeiNaluPos loop -> ParseSeiRbsp; SEI_UUID_LEN=16; SEI_PAYLOAD_SIZE_MAX=1024*1024-16"
  - kind: local_file
    path: /home/west/OH_AVCodec/services/media_engine/filters/sei_parser_helper.cpp
    anchor: "Line 133-147: ParseSeiRbsp: while loop parses multiple SEI messages in one NALu; payloadType filtering via std::find; FillTargetBuffer copies raw SEI data into AVBuffer"
  - kind: local_file
    path: /home/west/OH_AVCodec/services/media_engine/filters/sei_parser_helper.cpp
    anchor: "Line 160-170: SeiParserListener::OnBufferFilled: FlowLimit(avBuffer) -> ParseSeiPayload -> Format event with Tag::AV_PLAYER_SEI_PLAYBACK_POSITION and Tag::AV_PLAYER_SEI_PAYLOAD_GROUP -> eventReceiver_->OnEvent({name:\"SeiParserHelper\", EventType::EVENT_SEI_INFO, seiInfoFormat})"
  - kind: local_file
    path: /home/west/OH_AVCodec/services/media_engine/filters/sei_parser_helper.cpp
    anchor: "Line 172-188: FlowLimit: startPts_, syncCenter_->GetMediaTimeNow(), diff=avBuffer->pts_-startPts_-mediaTimeUs; cond_.wait_for(lock, microseconds(diff)) until isInterruptNeeded_"
  - kind: local_file
    path: /home/west/OH_AVCodec/services/media_engine/filters/sei_parser_helper.cpp
    anchor: "Line 190-203: SetSeiMessageCbStatus: when status=true -> payloadTypes_=payloadTypes; when false+empty -> clear all; when false+non-empty -> erase specific types from payloadTypes_"
  - kind: local_file
    path: /home/west/OH_AVCodec/services/media_engine/filters/sei_parser_filter.cpp
    anchor: "Line 168-175: DFX上报: eventReceiver_->OnMemoryUsageEvent({\"SEI_BQ\", DFXEventType::DFX_INFO_MEMORY_USAGE, inputBufferQueue_->GetMemoryUsage()})"
owner: 耀耀
review: pending
---

# MEM-ARCH-AVCODEC-S10: SeiParserFilter SEI信息解析过滤器

## Metadata

| 字段 | 值 |
|------|-----|
| id | MEM-ARCH-AVCODEC-S10 |
| title | SeiParserFilter SEI信息解析过滤器——SeiParserListener与SEI事件分发机制 |
| type | architecture_fact |
| scope | [AVCodec, MediaEngine, Filter, SEI, VideoProcessing, Player, HEVC, H.264] |
| status | draft (enhanced) |
| created_by | builder-agent |
| created_at | 2026-04-23 |
| updated_at | 2026-04-26 |
| confidence | high |

## 摘要

SeiParserFilter 是 media_engine filters 中专用于解析 **H.264/AVC 和 H.265/HEVC SEI（Supplemental Enhancement Information）** 信息的过滤器，注册名为 `"builtin.player.seiParser"`，FilterType 为 `FILTERTYPE_SEI`。

其核心职责是在视频播放 pipeline 中捕获视频 ES buffer，解析其中的 SEI NALu 单元，将用户关心的 SEI 消息通过 `EVENT_SEI_INFO` 事件分发给应用。

**SEI 解析默认关闭**，需显式调用 `SetSeiMessageCbStatus(true, payloadTypes)` 开启，并可指定 payloadTypes 向量过滤特定 SEI 类型。

该 Filter 与 VideoResizeFilter（转码增强）、VideoCaptureFilter（采集）、SubtitleSinkFilter（字幕）同属 player/transcoder 辅助 Filter 体系。

## 关键类与接口

### 类层次

```
SeiParserFilter (Filter 子类)
  ├── AVBufferAvailableListener (内部类，实现 IConsumerListener)
  │     └── OnBufferAvailable() → ProcessInputBuffer() → DrainOutputBuffer()
  └── 持有 sptr<SeiParserListener> producerListener_

SeiParserListener (实现 IBrokerListener)
  ├── OnBufferFilled() → FlowLimit → ParseSeiPayload → EVENT_SEI_INFO 事件
  ├── FlowLimit() → IMediaSyncCenter 音画同步等待
  ├── SetSeiMessageCbStatus(bool, vector<int32_t>) → 开关 + payloadType 过滤
  └── SetSyncCenter() → 音画同步中心注入

SeiParserHelper (抽象基类)
  ├── AvcSeiParserHelper (解析 H.264 SEI，NALu type = 0x06)
  └── HevcSeiParserHelper (解析 H.265 SEI，NALu type = 0x4E/0x50)

SeiParserHelperFactory
  └── CreateHelper(mimeType) → AvcSeiParserHelper 或 HevcSeiParserHelper
```

### 注册与常量

| 常量 | 值 | 说明 |
|------|-----|------|
| 注册名 | `"builtin.player.seiParser"` | AutoRegisterFilter |
| LOG_DOMAIN | `LOG_DOMAIN_SYSTEM_PLAYER` (0xD002020) | HiLogLabel domain |
| VIDEO_CAPACITY_RATE | `1.5F` | BufferQueue 容量系数 |
| DEFAULT_BUFFER_CAPACITY | `1048576` (1MB) | 默认最小容量 |
| SEI_PAYLOAD_SIZE_MAX | `1048576 - 16 = 1048560` | 最大单条 SEI payload |
| SEI_UUID_LEN | `16` | UUID 字节长度 |

### 关键接口

**SeiParserFilter 公共接口**：

```cpp
// 开启/关闭 SEI 解析 + payloadTypes 过滤
Status SetSeiMessageCbStatus(bool status, const std::vector<int32_t> &payloadTypes);

// 注入 IMediaSyncCenter，用于 FlowLimit 音画同步
void SetSyncCenter(std::shared_ptr<IMediaSyncCenter> syncCenter);

// 获取 Consumer（链接到上游 filter）
sptr<AVBufferQueueConsumer> GetBufferQueueConsumer();

// 获取 Producer（链接到下游 filter）
sptr<AVBufferQueueProducer> GetBufferQueueProducer();

// 中断 FlowLimit 等待
void OnInterrupted(bool isInterruptNeeded);
```

**SeiParserListener 核心方法**：

```cpp
// 收到填满的 buffer 后：FlowLimit → Parse → 发事件
void OnBufferFilled(std::shared_ptr<AVBuffer> &avBuffer) override;
```

**SeiParserHelper 核心方法**：

```cpp
// 解析 SEI payload（可能一条 NALu 含多条 SEI message）
Status ParseSeiPayload(
    const std::shared_ptr<AVBuffer> &buffer,
    std::shared_ptr<SeiPayloadInfoGroup> &group);  // group->playbackPosition = pts_ms
```

### SEI Event 格式（EVENT_SEI_INFO）

`OnEvent({name: "SeiParserHelper", EventType::EVENT_SEI_INFO, seiInfoFormat})` 中 Format 内容：

| Tag | 类型 | 说明 |
|-----|------|------|
| `AV_PLAYER_SEI_PLAYBACK_POSITION` | int64 | PTS 毫秒数，Us2Ms(buffer->pts_) |
| `AV_PLAYER_SEI_PAYLOAD_GROUP` | vector\<Format\> | 每条 SEI payload 一个 Format |

每条 payload Format：

| Tag | 类型 | 说明 |
|-----|------|------|
| `AV_PLAYER_SEI_PAYLOAD_TYPE` | int32 | SEI payload type（如 5=user_data_unregistered） |
| `AV_PLAYER_SEI_PAYLOAD` | buffer | 原始 SEI payload 字节（不含 header） |

## 数据流

```
上游 Filter（Decoder）输出 Video ES
  │
  ├─→ VideoSurfaceFilter（主渲染路径）
  │
  └─→ SeiParserFilter::GetBufferQueueProducer()（SEI 旁路）
        │
        └─ OnLinked(OnLinkedResultCallback_) ← 保存 meta（含 MIME_TYPE）

上游 Decoder Push Buffer（AttachBuffer）
  └─→ AVBufferQueueProducer
        └─→ SeiParserListener::OnBufferFilled()
              │
              ├─→ FlowLimit() — 若 isFlowLimited_ && syncCenter_ 存在
              │     └─ syncCenter_->GetMediaTimeNow() 等待音画同步
              │
              ├─→ ParseSeiPayload() — 找 SEI NALu → 解析 RBSP
              │     └─ payloadType 过滤（std::find in payloadTypeVec_）
              │
              └─→ eventReceiver_->OnEvent(EVENT_SEI_INFO, Format)
                    │
                    └─→ 上层应用（MediaPlayer）接收 SEI 回调

同时：AVBufferAvailableListener::OnBufferAvailable()
  └─→ ProcessInputBuffer() → DrainOutputBuffer()
        └─ AcquireBuffer + ReleaseBuffer（释放消费过的 buffer）
```

## 内存管理

**BufferQueue 容量计算**：

```cpp
int32_t capacity = metaRes ? videoWidth * videoHeight * VIDEO_CAPACITY_RATE : DEFAULT_BUFFER_CAPACITY;
// 例如 1920×1080: capacity = 1920*1080*1.5 = 3,110,400 bytes (~3MB)
// 最小值: DEFAULT_BUFFER_CAPACITY = 1MB
```

**DFX 上报**：

```cpp
eventReceiver_->OnMemoryUsageEvent({
    "SEI_BQ",
    DFXEventType::DFX_INFO_MEMORY_USAGE,
    inputBufferQueue_->GetMemoryUsage()
});
```

## FlowLimit 音画同步机制

`SeiParserListener::FlowLimit()` 使用条件变量实现基于 PTS 的同步等待：

```cpp
void FlowLimit(const std::shared_ptr<AVBuffer> &avBuffer) {
    if (startPts_ == 0) startPts_ = avBuffer->pts_;           // 记录起始 PTS
    auto mediaTimeUs = syncCenter_->GetMediaTimeNow();         // 当前播放位置
    auto diff = avBuffer->pts_ - startPts_ - mediaTimeUs;      // 需等待的微秒数
    if (diff > 0) {
        unique_lock<mutex> lock(mutex_);
        cond_.wait_for(lock, microseconds(diff),              // 等待 diff 微秒
            [this]() { return isInterruptNeeded_.load(); });  // 或被中断
    }
}
```

## SEI PayloadType 过滤机制

`SetSeiMessageCbStatus` 支持精细化开启/关闭：

```cpp
// 开启：设置要接收的 payloadTypes
status=true, payloadTypes=[5, ...]  → 只接收 type=5 的 SEI

// 关闭全部：
status=false, payloadTypes=empty → 清空 payloadTypesVec_（停止所有）

// 关闭部分：
status=false, payloadTypes=[5] → 从 payloadTypesVec_ 中移除 5（停止接收 type=5）
```

常见 SEI payloadType：
- **5**: `user_data_unregistered`（最常用，UUID标识用户数据）
- **0**: `buffering_period`
- **1**: `pic_timing`
- **132**: `user_data_unregistered`（ITU-T T.35）

## HEVC vs AVC SEI NALu 识别

| Codec | NALu type byte | 识别方式 |
|-------|---------------|---------|
| AVC/H.264 | `0x06` | `header & 0x1F == 0x06` |
| HEVC/H.265 | `0x4E` 或 `0x50` | `header & 0x7E == 0x4C` (即 `0x4E`=39, `0x50`=40) |

HEVC NALu header 结构（二字节）：
```
Byte 0: [0..1]=0, [2..6]=nalu_type (0x26=39=SEI, 0x28=40=SEI)
Byte 1: [0]=forbidden=0, [1..6]=nalu_type_bitstream_restriction_flag等
```
实际判断：`header & 0x7E` 得到 nalu type，HEVC_SEI_TYPE_ONE=0x4E (39), HEVC_SEI_TYPE_TWO=0x50 (40)。

## SEI 解析关键算法

### FindNextSeiNaluPos（定位 SEI NALu 起始）

使用字节扫描 + NALu start code 匹配：
- NALu start code: `0x00000001`（大端）或 `0x01000000`（小端）
- 跳过 emulation prevention（`0x03` 填充）
- `GetNaluStartSeq()` 动态判断字节序

### ParseSeiRbsp（解析 SEI body）

一个 SEI NALu 可包含多条 SEI message，每条格式：
```
payloadType = 变长（0xFF... + last byte）
payloadSize = 变长（0xFF... + last byte）
payloadData[payloadSize]
```

变长编码：连字节 `0xFF` 累加，直到非 `0xFF` 字节。

## 与其他 Filter 的关系

| Filter | 注册名 | FilterType | 关系 |
|--------|--------|-----------|------|
| SeiParserFilter | builtin.player.seiParser | FILTERTYPE_SEI | **本主题** |
| VideoDecoderFilter / SurfaceDecoderFilter | builtin.player.surfacedecoder | FILTERTYPE_VIDEODEC | 上游数据源（Video ES 输出到 SEI 旁路） |
| VideoRenderFilter | builtin.player.videorender | FILTERTYPE_VIDEOUT | 渲染终点 |
| SubtitleSinkFilter | builtin.player.subtitlesink | FILTERTYPE_SSINK | 平行辅助 Filter |
| DemuxerFilter | builtin.player.demuxer | FILTERTYPE_DEMUXER | 最上游数据源 |

## SEI 功能开关

SEI 解析**默认关闭**（`seiMessageCbStatus_ = false`）。

应用开启流程：
```cpp
// 1. 获取 SeiParserFilter 实例（通过 FilterPipeline 或 MediaPlayer）
// 2. Filter 链接完成后调用
filter->SetSeiMessageCbStatus(true, {5});  // 只接收 user_data_unregistered

// 3. 注册事件监听
mediaPlayer->SetSEICallback([](Event &event) {
    auto &format = event.param;
    int64_t pts = format.GetIntValue(Tag::AV_PLAYER_SEI_PLAYBACK_POSITION);
    vector<Format> payloads = format.GetFormatVectorValue(Tag::AV_PLAYER_SEI_PAYLOAD_GROUP);
    for (auto &p : payloads) {
        int32_t type = p.GetIntValue(Tag::AV_PLAYER_SEI_PAYLOAD_TYPE);
        // 处理 raw buffer...
    }
});
```

## 已知限制

1. **Event 分发非多路广播**：当前实现只有一路 `eventReceiver_->OnEvent`，不存在 DR/RT/UX 四路分发（原草稿此项为推测，无代码证据）
2. **无独立 SEI 输出 Port**：SeiParserFilter 只消费 buffer，不向下游输出（Passive Filter）
3. **FlowLimit 依赖 syncCenter**：若未注入 `IMediaSyncCenter`，`isFlowLimited_` 为 false 时 FlowLimit 直接跳过

## 相关已有记忆

- **MEM-ARCH-AVCODEC-S3**: CodecServer Pipeline 数据流（SeiParserFilter 位于 decoder 下游并行）
- **MEM-ARCH-AVCODEC-S45**: SurfaceDecoderFilter（Video ES 主渲染路径）
- **MEM-ARCH-AVCODEC-S46**: DecoderSurfaceFilter（Decoder + DRM + PostProcessor）
- **MEM-ARCH-AVCODEC-S22**: MediaSyncManager（IMediaSyncCenter 同步中心）

## 证据增强说明（2026-04-26）

- 新增：`sei_parser_filter.h` 完整类定义（含 private 成员）
- 新增：`sei_parser_helper.h` 完整类继承体系 + `SeiPayloadInfoGroup` 结构
- 修正：SeiParserListener 并非"四路分发"，而是单一 `eventReceiver_->OnEvent` 路径
- 修正：FlowLimit 使用 `std::condition_variable` + PTS 差值等待，非简单标记
- 修正：HEVC SEI 识别为双字节（`HEVC_SEI_HEAD_LEN=2`），AVC 为单字节（`AVC_SEI_HEAD_LEN=1`）
- 新增：SEI payloadType 变长编码解析（`GetSeiTypeOrSize`）
- 新增：emulation prevention byte 处理（`FillTargetBuffer`）
