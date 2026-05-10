---
id: MEM-ARCH-AVCODEC-S113
title: SeiParserFilter 与 SeiParserHelper SEI 信息解析框架——AnnexB/Nalu双格式+AVC/HEVC双解析器工厂+回调驱动事件链
scope: [AVCodec, MediaEngine, Filter, SEI, Parser, AnnexB, AVC, HEVC, Nalu, AnyncMode, EventCallback]
status: approved
approved_at: "2026-05-11T00:47:00+08:00"
submitted_at: "2026-05-10T05:48:00+08:00"
created_at: "2026-05-10T04:32:00+08:00"
evidence_count: 12
---

# MEM-ARCH-AVCODEC-S113: SeiParserFilter 与 SeiParserHelper SEI 信息解析框架

## 核心定位

SeiParserFilter（`services/media_engine/filters/sei_parser_filter.cpp`，235行）是 **MediaEngine Filter Pipeline 中解析 SEI（Supplemental Enhancement Information）信息的专用 Filter**，注册名为 `"builtin.player.seiParser"`，FilterType 为 `FILTERTYPE_SEI`。它内部持有 `std::shared_ptr<SeiParserHelper>` 引擎实例（由 `SeiParserHelperFactory::CreateHelper` 按 MIME 类型构造），将视频 bitstream 中的 SEI NAL 单元解析为结构化信息（UUID/PayloadType/PayloadSize），通过 `EventReceiver::OnEvent(EVENT_SEI_INFO)` 向上报事件，供应用层消费。

SeiParserHelper（`services/media_engine/filters/sei_parser_helper.cpp`，347行）是 **SEI NAL 单元解析引擎**，支持 AVC（h264/mp4）和 HEVC（h265/mp4）两种格式，通过 `HELPER_CONSTRUCTOR_MAP` 工厂模式选择具体解析器（`AvcSeiParserHelper` 或 `HevcSeiParserHelper`）。

## 关键证据

| 证据 | 文件:行号 | 说明 |
|------|-----------|------|
| E1 | sei_parser_filter.cpp:36-39 | AutoRegisterFilter 注册 "builtin.player.seiParser"，FilterType::FILTERTYPE_SEI，lambda 工厂 |
| E2 | sei_parser_filter.h:26-104 | 类定义：GetBufferQueueProducer/Consumer，Init，DoPrepare，ParseSei，SetSeiMessageCbStatus，DrainOutputBuffer，DoProcessInputBuffer |
| E3 | sei_parser_filter.cpp:107-114 | PrepareInputBufferQueue 创建 AVBufferQueue(1024*1024) + SetBufferAvailableListener |
| E4 | sei_parser_filter.cpp:85-93 | PrepareState → requires seiMessageCbStatus_ == true |
| E5 | sei_parser_filter.cpp:167-171 | DoProcessInputBuffer → DrainOutputBuffer drops frame or drains parsed SEI output |
| E6 | sei_parser_filter.cpp:173-189 | OnLinked captures trackMeta + onLinkedResultCallback_；OnUnLinked teardown |
| E7 | sei_parser_helper.cpp:63-70 | HELPER_CONSTRUCTOR_MAP：AVC→AvcSeiParserHelper，HEVC→HevcSeiParserHelper |
| E8 | sei_parser_helper.cpp:74-96 | ParseSeiPayload 入口函数，FindNextSeiNaluPos 循环解析，group->playbackPosition = Us2Ms(buffer->pts_) |
| E9 | sei_parser_helper.cpp:141/152 | AvcSeiParserHelper::IsSeiNalu（NALU_TYPE=0x06）/ HevcSeiParserHelper::IsSeiNalu（HEVC_SEI_TYPE_ONE/TWO） |
| E10 | sei_parser_helper.cpp:163-198 | ParseSeiRbsp：解析 RBSP 防伪字节（EMULATION_PREVENTION CODE=0x03 转义），提取 payload |
| E11 | sei_parser_helper.cpp:200-234 | GetSeiTypeOrSize + FillTargetBuffer：提取 UUID/payloadType/payloadSize |
| E12 | sei_parser_helper.cpp:236-240 | SeiParserHelperFactory::CreateHelper：按 MIME 从 HELPER_CONSTRUCTOR_MAP 构造 |

## 架构要点

- **Filter 注册**：`"builtin.player.seiParser"`, `FilterType::FILTERTYPE_SEI`，lambda 工厂函数
- **数据流**：上游（视频解码器）→ AVBufferQueue → SeiParserFilter → ParseSei → EventReceiver → 应用层
- **双模式切换**：SetSeiMessageCbStatus(true) 激活 SEI 解析；SetParseSeiEnabled(bool) 控制是否解析
- **AVBufferQueue 双端**：GetBufferQueueProducer() 上游入队，GetBufferQueueConsumer() 下游出队
- **DoProcessInputBuffer**：入口处理函数，调用 ParseSei(buffer) 解析，触发 DrainOutputBuffer
- **Helper 工厂**：`SeiParserHelperFactory::CreateHelper(mimeType)` 按 MIME 类型构造对应解析器

## SEI NAL 单元格式

AVC SEI（AnnexB 格式）：
- Start code: 0x00000001
- NAL header: nal_unit_type = 0x06 (SEI)
- payload_type: 变长编码（0-255）
- payload_size: 变长编码（0-255）
- payload: UUID(16字节) + 用户数据

HEVC SEI：
- Start code: 0x00000001
- NAL header: nal_unit_type in {39, 40}（SEI NAL）
- 解析逻辑与 AVC 相同

## 与其他 Filter 的关系

| 关系 | 说明 |
|------|------|
| 上游 | VideoDecoderFilter / SurfaceDecoderFilter，输出含 SEI NAL 单元的 bitstream |
| 下游 | 通常透传（SEI 不影响图像像素），或接 VideoSinkFilter |
| 关联 Filter | S14（Filter Chain 三联机制）定义了 LinkNext/OnLinked 握手协议 |

## 源码文件

| 文件 | 行数 | 说明 |
|------|------|------|
| `services/media_engine/filters/sei_parser_filter.cpp` | 235 | Filter 封装层 |
| `services/media_engine/filters/sei_parser_helper.cpp` | 347 | SEI 解析引擎核心 |
| `interfaces/inner_api/native/sei_parser_filter.h` | 104 | 类定义头文件 |
| `services/media_engine/filters/sei_parser_helper.h` | ~150（未读） | Helper 头文件 |