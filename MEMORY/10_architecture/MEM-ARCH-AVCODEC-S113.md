---
id: MEM-ARCH-AVCODEC-S113
title: SeiParserFilter 与 SeiParserHelper SEI 信息解析框架——AnnexB/Nalu双格式+AVC/HEVC双解析器工厂+回调驱动事件链
scope: [AVCodec, MediaEngine, Filter, SEI, Parser, AnnexB, AVC, HEVC, Nalu, AsyncMode, EventCallback, FlowLimit, IMediaSyncCenter]
topic: MediaEngine Filter Pipeline 中 SEI（Supplemental Enhancement Information）信息解析的专用 Filter 框架。SeiParserFilter 负责 Filter 层封装（注册、Link、数据流），SeiParserHelper 负责 SEI NAL 单元解析引擎（AVC/HEVC 双格式），SeiParserListener 负责事件上报与流控同步。
status: pending_approval
submitted_at: "2026-05-14T03:28:00+08:00"
created_by: builder
evidence_source: /home/west/av_codec_repo/services/media_engine/filters/sei_parser_filter.cpp (235行) + sei_parser_helper.cpp (347行) + /home/west/av_codec_repo/interfaces/inner_api/native/sei_parser_filter.h (104行) + sei_parser_helper.h (150行)
---

# MEM-ARCH-AVCODEC-S113: SeiParserFilter 与 SeiParserHelper SEI 信息解析框架

> **Builder 增强版**：基于本地镜像 `/home/west/av_codec_repo` 逐行源码分析，证据行号级精确。
> 原草案已存在（approved，2026-05-11），本版本为源码逐行分析增强版。

## 核心定位

- **SeiParserFilter**（`services/media_engine/filters/sei_parser_filter.cpp`，235行）：MediaEngine Filter Pipeline 中解析 SEI（Supplemental Enhancement Information）信息的专用 Filter，注册名为 `"builtin.player.seiParser"`，FilterType 为 `FILTERTYPE_SEI`。持有 `std::shared_ptr<SeiParserHelper>` 引擎实例 + `sptr<SeiParserListener>` 事件监听器。
- **SeiParserHelper**（`services/media_engine/filters/sei_parser_helper.cpp`，347行）：SEI NAL 单元解析引擎，支持 AVC（h264/mp4）和 HEVC（h265/mp4），通过 `HELPER_CONSTRUCTOR_MAP` 工厂模式选择 `AvcSeiParserHelper` 或 `HevcSeiParserHelper`。
- **SeiParserListener**（`sei_parser_helper.h`，内嵌类）：`IBrokerListener` 实现，负责 `OnBufferFilled` 回调、`FlowLimit` 流控同步、`SetSeiMessageCbStatus` payloadType 过滤。

## 关键证据（行号级，本地镜像）

| 证据 | 文件:行号 | 说明 |
|------|-----------|------|
| E1 | sei_parser_filter.cpp:36-39 | `AutoRegisterFilter<SeiParserFilter>` 静态注册 `"builtin.player.seiParser"`, `FilterType::FILTERTYPE_SEI`，lambda 工厂 `make_shared<SeiParserFilter>` |
| E2 | sei_parser_filter.cpp:26-33 | `AVBufferAvailableListener` 内嵌类，继承 `IConsumerListener`，`OnBufferAvailable()` → `ProcessInputBuffer()` 消费驱动 |
| E3 | sei_parser_filter.cpp:47-50 | 构造函数 `SeiParserFilter(name, filterType)` 调用 `Filter(name, FILTERTYPE_SEI, false)` 基类构造 |
| E4 | sei_parser_filter.cpp:57-60 | `Init(receiver, callback)` 设置 `eventReceiver_` + `filterCallback_` |
| E5 | sei_parser_filter.cpp:64-66 | `DoInitAfterLink()` 仅记录 MIME 类型日志，返回 `Status::OK` |
| E6 | sei_parser_filter.cpp:68-80 | `DoPrepare()` → `PrepareState()` → `PrepareInputBufferQueue()` → 创建 `AVBufferQueue` |
| E7 | sei_parser_filter.cpp:82-97 | `PrepareState()` 状态机：`INITIALIZED` → `PREPARING` → `READY`，失败回滚 `INITIALIZED` |
| E8 | sei_parser_filter.cpp:99-145 | `PrepareInputBufferQueue()` 创建虚拟内存分配器（`AVAllocatorFactory::CreateVirtualAllocator`）+ `AVBuffer::CreateAVBuffer` + `AttachBuffer` 到队列 |
| E9 | sei_parser_filter.cpp:107-109 | 容量计算：`videoWidth * videoHeight * VIDEO_CAPACITY_RATE(1.5)`，兜底 `DEFAULT_BUFFER_CAPACITY=1024*1024` |
| E10 | sei_parser_filter.cpp:138-141 | `eventReceiver_->OnMemoryUsageEvent({SEI_BQ, DFX_INFO_MEMORY_USAGE, ...})` DFX 内存上报 |
| E11 | sei_parser_filter.cpp:155-157 | `GetBufferQueueProducer()` / `GetBufferQueueConsumer()` 仅在 `FilterState::READY` 时返回非空 |
| E12 | sei_parser_filter.cpp:163-166 | `DoProcessInputBuffer(recvArg, dropFrame)` → `DrainOutputBuffer(dropFrame)` 数据流驱动 |
| E13 | sei_parser_filter.cpp:171-179 | `OnLinked(inType, meta, callback)` 捕获 `trackMeta_` + `onLinkedResultCallback_`，`OnLinkedResult(producer, meta)` 握手 |
| E14 | sei_parser_filter.cpp:181-188 | `OnUnLinked(inType, callback)` 资源清理（基类实现） |
| E15 | sei_parser_filter.cpp:194-200 | `DrainOutputBuffer(flushed)` → `AcquireBuffer` + `ReleaseBuffer` 清空队列 |
| E16 | sei_parser_filter.cpp:205-220 | `SetSeiMessageCbStatus(status, payloadTypes)` 创建 `SeiParserListener`（`codecMimeType_` + `producer_` + `eventReceiver_`）|
| E17 | sei_parser_filter.cpp:222-225 | `SetSyncCenter(syncCenter)` 注入 `IMediaSyncCenter`，用于流控同步 |
| E18 | sei_parser_filter.cpp:227-229 | `OnInterrupted(isInterruptNeeded)` 中断 `FlowLimit` 等待 |
| E19 | sei_parser_helper.cpp:20-32 | 常量定义：`SEI_UUID_LEN=16`，`SEI_PAYLOAD_SIZE_MAX=1024*1024-16`，`ANNEX_B_PREFIX_LEN=4`，EMULATION_PREVENTION_CODE=0x03 |
| E20 | sei_parser_helper.cpp:34-37 | `TYPE_AVC="video/avc"`，`TYPE_HEVC="video/hevc"` MIME 类型常量 |
| E21 | sei_parser_helper.cpp:39-43 | `HEVC_SEI_TYPE_ONE=0x4E`(39), `HEVC_SEI_TYPE_TWO=0x50`(40)，HEVC NALU type mask `0x7E` |
| E22 | sei_parser_helper.cpp:45-49 | `AVC_SEI_TYPE=0x06`，AVC NALU type mask `0x1F`，`NALU_START_BIG_ENDIAN/LITTLE_ENDIAN=0x00000001` |
| E23 | sei_parser_helper.cpp:63-70 | `HELPER_CONSTRUCTOR_MAP`：AVC → `AvcSeiParserHelper`，HEVC → `HevcSeiParserHelper`，lambda 工厂 |
| E24 | sei_parser_helper.cpp:74-93 | `ParseSeiPayload(buffer, group)` 入口，`while(FindNextSeiNaluPos)` 循环查找 SEI NALU，`group->playbackPosition = Us2Ms(buffer->pts_)` |
| E25 | sei_parser_helper.cpp:95-121 | `FindNextSeiNaluPos(startPtr, maxPtr)` 查找 AnnexB 起始码（`0x00000001`），字节对齐 mask `SEI_BYTE_MASK_HIGH_7BITS=0xFE` |
| E26 | sei_parser_helper.cpp:123-130 | `GetNaluStartSeq()` 跨平台大小端判断，返回 `NALU_START_BIG_ENDIAN` 或 `LITTLE_ENDIAN` |
| E27 | sei_parser_helper.cpp:134-141 | `AvcSeiParserHelper::IsSeiNalu(headerPtr)`：NALU type = `0x06`（`AVC_SEI_TYPE`），`AVC_NAL_UNIT_TYPE_FLAG=0x1F` |
| E28 | sei_parser_helper.cpp:143-150 | `HevcSeiParserHelper::IsSeiNalu(headerPtr)`：NALU type = `0x4E`(39) 或 `0x50`(40)，`HEVC_NAL_UNIT_TYPE_FLAG=0x7E` |
| E29 | sei_parser_helper.cpp:154-204 | `ParseSeiRbsp(bodyPtr, maxPtr, group)` 解析 RBSP：`while` 循环 `GetSeiTypeOrSize` 提取 payloadType/payloadSize，`FillTargetBuffer` 复制负载，`payloadType==5` 时创建 `AVBuffer` 存入 `group->vec` |
| E30 | sei_parser_helper.cpp:206-217 | `GetSeiTypeOrSize(bodyPtr, maxPtr)` 变长解码：累加 `0xFF` 字节 + 最后字节，低 7 位有效（SEI spec） |
| E31 | sei_parser_helper.cpp:219-244 | `FillTargetBuffer(buffer, payloadPtr, maxPtr, payloadSize)` 防伪字节处理：`EMULATION_PREVENTION_CODE=0x03` 在两个 `0x00` 后需跳过 |
| E32 | sei_parser_helper.cpp:246-250 | `SeiParserHelperFactory::CreateHelper(mimeType)` 从 `HELPER_CONSTRUCTOR_MAP` 查找构造器 |
| E33 | sei_parser_helper.h:88-105 | `SeiParserListener` 类定义：`IBrokerListener` 实现，`OnBufferFilled` → `FlowLimit` → `ParseSeiPayload` → `OnEvent(EVENT_SEI_INFO)` 上报 |
| E34 | sei_parser_helper.h:98-104 | `SeiPayloadInfo`（payloadType + AVBuffer）和 `SeiPayloadInfoGroup`（playbackPosition + vec）结构体 |
| E35 | sei_parser_helper.cpp:253-270 | `SeiParserListener::OnBufferFilled(avBuffer)`：① `ReturnBuffer(avBuffer, true)`  ScopeExit ② `FlowLimit` 流控 ③ `ParseSeiPayload` ④ `Format` 封装 ⑤ `eventReceiver_->OnEvent({SeiParserHelper, EVENT_SEI_INFO, seiInfoFormat})` |
| E36 | sei_parser_helper.cpp:272-287 | `FlowLimit(avBuffer)`：计算 `diff = avBuffer->pts_ - startPts_ - mediaTimeUs`，`cond_.wait_for(diff)` 等待同步，`isInterruptNeeded_` 可打断 |
| E37 | sei_parser_helper.cpp:289-294 | `SetPayloadTypeVec(vector)` 将 payloadType 白名单注入 `SeiParserHelper`，`spinLock_` 保护 |
| E38 | sei_parser_helper.cpp:296-302 | `OnInterrupted(isInterruptNeeded)` 设置 `isInterruptNeeded_` + `notify_all` 唤醒 |
| E39 | sei_parser_helper.cpp:304-327 | `SetSeiMessageCbStatus(status, payloadTypes)`：status=true → 设置白名单；status=false → 从现有列表中移除指定类型 |

## 架构设计说明

### 整体架构

```
VideoDecoder/SurfaceDecoder（上游）
    ↓ AVBufferQueue（bitstream 含 SEI NALU）
SeiParserFilter
    ↓ OnLinked + AVBufferAvailableListener
SeiParserListener::OnBufferFilled
    ↓ FlowLimit（IMediaSyncCenter 同步）
    ↓ ParseSeiPayload
SeiParserHelper（AvcSeiParserHelper / HevcSeiParserHelper）
    ↓ FindNextSeiNaluPos + ParseSeiRbsp
    ↓ Format 封装 + OnEvent(EVENT_SEI_INFO)
EventReceiver → 应用层
```

### 关键类 / 函数列表

| 类/函数 | 文件:行号 | 说明 |
|---------|-----------|------|
| `SeiParserFilter::AVBufferAvailableListener` | sei_parser_filter.cpp:26-33 | `IConsumerListener` 实现，消费驱动 |
| `SeiParserFilter::DoPrepare()` | sei_parser_filter.cpp:68-80 | Filter 生命周期 Prepare |
| `SeiParserFilter::PrepareInputBufferQueue()` | sei_parser_filter.cpp:99-145 | 创建 AVBufferQueue + 虚拟内存缓冲 |
| `SeiParserFilter::GetBufferQueueProducer()` | sei_parser_filter.cpp:155-157 | Filter 链路握手，提供 Producer 给下游 |
| `SeiParserFilter::SetSeiMessageCbStatus()` | sei_parser_filter.cpp:205-220 | 激活 SEI 解析（创建 SeiParserListener） |
| `SeiParserFilter::DrainOutputBuffer()` | sei_parser_filter.cpp:194-200 | 清空队列缓冲 |
| `AvcSeiParserHelper::IsSeiNalu()` | sei_parser_helper.cpp:134-141 | AVC SEI NALU 判断：type=0x06 |
| `HevcSeiParserHelper::IsSeiNalu()` | sei_parser_helper.cpp:143-150 | HEVC SEI NALU 判断：type=39/40 |
| `SeiParserHelper::FindNextSeiNaluPos()` | sei_parser_helper.cpp:95-121 | AnnexB 起始码搜索（0x00000001） |
| `SeiParserHelper::ParseSeiRbsp()` | sei_parser_helper.cpp:154-204 | SEI payload 提取（RBSP → payload） |
| `SeiParserHelper::FillTargetBuffer()` | sei_parser_helper.cpp:219-244 | RBSP 防伪字节逆转（0x000003→0x0000） |
| `SeiParserHelperFactory::CreateHelper()` | sei_parser_helper.cpp:246-250 | MIME 类型 → 具体 Helper 工厂 |
| `SeiParserListener::OnBufferFilled()` | sei_parser_helper.cpp:253-270 | 缓冲填充回调事件链入口 |
| `SeiParserListener::FlowLimit()` | sei_parser_helper.cpp:272-287 | PTS 同步等待（IMediaSyncCenter） |
| `SeiParserListener::SetSeiMessageCbStatus()` | sei_parser_helper.cpp:304-327 | payloadType 白名单过滤配置 |
| `SeiPayloadInfo` struct | sei_parser_helper.h:98-101 | 单个 SEI payload 元数据 |
| `SeiPayloadInfoGroup` struct | sei_parser_helper.h:103-105 | SEI payload 组（含 playbackPosition） |

### 数据流

1. **输入**：上游视频解码器输出的 AVBuffer（bitstream，含 SEI NALU 单元，起始码 AnnexB 格式）
2. **入队**：`inputBufferQueueProducer_->AttachBuffer/ReturnBuffer` 入 AVBufferQueue
3. **消费驱动**：`AVBufferAvailableListener::OnBufferAvailable` → `ProcessInputBuffer`
4. **解析**：`SeiParserListener::OnBufferFilled` → `FlowLimit`（同步等待）→ `SeiParserHelper::ParseSeiPayload`
5. **查找 SEI NALU**：`FindNextSeiNaluPos` 搜索起始码 `0x00000001`，判断 NALU type（AVC=0x06，HEVC=39/40）
6. **解析 RBSP**：`ParseSeiRbsp` 提取 payloadType（变长）+ payloadSize（变长）+ payload（UUID+数据）
7. **防伪字节**：`FillTargetBuffer` 逆转 RBSP 防伪字节（EMULATION_PREVENTION_CODE=0x03）
8. **上报**：`Format` 封装 playbackPosition + payload 组 → `OnEvent(EVENT_SEI_INFO)` 向上报事件

### SEI NAL 单元格式（技术细节）

**AVC（AnnexB）**：
```
0x00000001 06 [payload_type...][payload_size...] [UUID(16B)][payload_data]
           └─ NALU type=0x06（SEI）
```

**HEVC（AnnexB）**：
```
0x00000001 4E/50 [payload_type...][payload_size...] [UUID(16B)][payload_data]
           └─── NALU type=39/40（SEI）
```

**变长编码（SEI spec）**：payload_type/payload_size 均为变长编码，字节值 0xFF 表示后面还有字节，低 7 位有效。

### FlowLimit 同步机制

`FlowLimit` 通过 `IMediaSyncCenter::GetMediaTimeNow()` 获取当前播放时间，计算 `diff = buffer_pts - start_pts - media_time`，使用 `condition_variable` 等待 `diff` 微秒后继续解析，确保 SEI 信息与对应视频帧时序对齐。

### 与其他 Filter 的关系

| 关系 | 说明 |
|------|------|
| 上游 | VideoDecoderFilter / SurfaceDecoderFilter / DecoderSurfaceFilter，输出含 SEI NALU 的 bitstream |
| 下游 | 通常透传（SEI 不影响像素），或接 VideoSinkFilter |
| 关联 Filter | S14（Filter Chain 三联机制）定义 LinkNext/OnLinked 握手协议 |
| 同步关联 | S22（MediaSyncManager）提供 `IMediaSyncCenter` 时间锚点 |

## 关联的记忆条目

- `MEM-ARCH-AVCODEC-S14`：MediaEngine Filter Chain 架构（AutoRegisterFilter + FilterLinkCallback + AVBufferQueue 三联机制）
- `MEM-ARCH-AVCODEC-S22`：MediaSyncManager 音视频同步管理中心（IMediaSyncCenter 时钟锚点）
- `MEM-ARCH-AVCODEC-S46`：DecoderSurfaceFilter DRM 解密（DRM 路径可能注入 SEI）
- `MEM-ARCH-AVCODEC-S45`：SurfaceDecoderFilter（Surface 模式视频解码）

## 源码文件

| 文件 | 路径 | 行数 | 说明 |
|------|------|------|------|
| sei_parser_filter.cpp | services/media_engine/filters/ | 235 | Filter 封装层 |
| sei_parser_filter.h | interfaces/inner_api/native/ | 104 | 类定义头文件 |
| sei_parser_helper.cpp | services/media_engine/filters/ | 347 | SEI 解析引擎核心 |
| sei_parser_helper.h | interfaces/inner_api/native/ | ~150 | Helper + Listener + Struct 定义 |

## evidence 引用

- commit hash（本地镜像）：使用 HEAD
- 代码行号：`sei_parser_filter.cpp:36-39`（AutoRegisterFilter 注册）
- 代码行号：`sei_parser_helper.cpp:63-70`（HELPER_CONSTRUCTOR_MAP 工厂）
- 代码行号：`sei_parser_helper.cpp:253-270`（SeiParserListener::OnBufferFilled 完整事件链）
- 代码行号：`sei_parser_helper.cpp:272-287`（FlowLimit PTS 同步等待）