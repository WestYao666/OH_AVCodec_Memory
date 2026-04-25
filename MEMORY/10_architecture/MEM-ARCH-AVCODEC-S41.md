---
type: architecture
id: MEM-ARCH-AVCODEC-S41
title: DemuxerFilter 解封装过滤器——Filter层封装与MediaDemuxer多轨数据流
scope: [AVCodec, MediaEngine, Filter, Demuxer, MediaDemuxer, FilterPipeline, StreamType, TrackManagement, AVBufferQueue, DRM]
pipeline_position: Filter Pipeline 第二层（SourceFilter→DemuxerFilter→DecoderFilter）
status: pending_approval
created_by: builder-agent
created_at: "2026-04-25T22:25:00+08:00"
evidence_count: 20
---

# MEM-ARCH-AVCODEC-S41: DemuxerFilter 解封装过滤器

## Metadata

| 字段 | 值 |
|------|-----|
| id | MEM-ARCH-AVCODEC-S41 |
| title | DemuxerFilter 解封装过滤器——Filter层封装与MediaDemuxer多轨数据流 |
| type | architecture_fact |
| scope | [AVCodec, MediaEngine, Filter, Demuxer, MediaDemuxer, FilterPipeline, StreamType, TrackManagement, AVBufferQueue, DRM] |
| status | draft |
| created_by | builder-agent |
| created_at | 2026-04-25 |
| confidence | high |

## 摘要

`DemuxerFilter`（`services/media_engine/filters/demuxer_filter.cpp`）是 **MediaEngine Filter Pipeline 中的解封装（Demuxer）Filter 封装层**，注册名为 `"builtin.player.demuxer"`，FilterType 为 `FILTERTYPE_DEMUXER`。它内部持有 `std::shared_ptr<MediaDemuxer>` 核心引擎实例，通过 `SetDataSource()` 接收上游 `MediaSource`，在 `DoPrepare()` 阶段通过 `HandleTrackInfos()` 发现音视频轨道并向管线下游（Decoder Filter）传递 `AVBufferQueueProducer`；在 `DoStart()` 后通过 `ResumeDemuxerReadLoop()` 启动多轨并发读循环，将封装容器中的压缩 bitstream 样本写入各轨 `AVBufferQueue`，由下游解码器消费。

> **与 S2（DemuxerPlugin）的关系**：S2 描述的是 `DemuxerPlugin` 插件体系（mp4/mkv/hls/dash 等容器格式支持），S41 则聚焦 DemuxerFilter 这一 Filter 封装层，关注多轨管理、Filter Link 机制、PTS 管理、以及 Filter Pipeline 中的调度角色。

## 架构要点

- **Filter 注册**：`"builtin.player.demuxer"`, `FilterType::FILTERTYPE_DEMUXER`，通过 `AutoRegisterFilter` 模板在 filter_factory 中自动注册
- **核心引擎**：`std::shared_ptr<MediaDemuxer> demuxer_` 是所有解封装逻辑的载体，DemuxerFilter 仅做 Filter 层的封装和管线调度
- **多轨并发读循环**：`MediaDemuxer::ReadSample()` 由多轨各自驱动（每轨一个 `AVBufferQueueProducer`），通过 `ResumeDemuxerReadLoop()` / `PauseDemuxerReadLoop()` 控制读循环
- **StreamType 分流**：根据 MIME/容器类型，DemuxerFilter 将轨道分为 `STREAMTYPE_DOLBY`（音频直通）、`STREAMTYPE_ENCODED_AUDIO`（需解码音频）、`STREAMTYPE_RAW_AUDIO`（原始 PCM）、`STREAMTYPE_ENCODED_VIDEO`（需解码视频）、`STREAMTYPE_SUBTITLE`（字幕）五种类型
- **PTS 管理**：AVI/MPEGPS/WMV 三种容器格式需要显式 PTS 管理（`ptsManagedFileTypes`），通过 `Tag::MEDIA_FILE_TYPE` 传递到下游解码器
- **Endianness 转换**：`g_sampleFormatBeToLe` map 处理大端音频格式（SAMPLE_S16BE → SAMPLE_S16LE 等）到小端的自动转换，解决不同编码器产生的音频格式兼容问题
- **双模式切换**：`SetTranscoderMode()` 激活转码模式（禁用在线FD缓存 `demuxer_->SetEnableOnlineFdCache(false)`），`SetPlayerMode()` 激活播放器模式
- **DRM 支持**：`DemuxerFilterDrmCallback` 实现 `AVDemuxerCallback`，在 DRM 信息变更时通过 `receiver_->OnEvent(EVENT_DRM_INFO_UPDATED)` 向上报事件
- **Seek 策略**：seekTime==0 时走 `SeekToStart` 快速起始路径；MPEGTS 走 `SeekToKeyFrame`（关键帧seek）；其他走通用 `SeekTo`
- **音频解码异步**：`IsAudioDemuxDecodeAsync()` 允许音频 demux+decode 异步联合执行（`MediaDemuxer` 层支持）
- **视频流就绪回调**：`RegisterVideoStreamReadyCallback` 注册视频流就绪回调（用于 Surface 模式视频首帧显示时机感知）

## 关键证据

| 证据 | 文件:行号 | 说明 |
|------|-----------|------|
| E1 | demuxer_filter.cpp:49-53 | 注册 "builtin.player.demuxer", FilterType::FILTERTYPE_DEMUXER |
| E2 | demuxer_filter.h:32 | `std::shared_ptr<MediaDemuxer> demuxer_` 核心引擎成员变量 |
| E3 | demuxer_filter.cpp:56-73 | `g_sampleFormatBeToLe` map，大端→小端音频格式转换表（17种格式） |
| E4 | demuxer_filter.cpp:118-143 | `DemuxerFilterDrmCallback` 实现 AVDemuxerCallback，OnDrmInfoChanged 向上报 EVENT_DRM_INFO_UPDATED |
| E5 | demuxer_filter.cpp:160-185 | `Init(receiver, callback, monitor)` 三参数重载，设置 DRM 回调和 CodecList |
| E6 | demuxer_filter.cpp:187-193 | `SetTranscoderMode()` 设置 isTransCoderMode_=true，禁用在线FD缓存 |
| E7 | demuxer_filter.cpp:195-201 | `SetPlayerMode()` 激活播放器模式 |
| E8 | demuxer_filter.cpp:207-218 | `SetDataSource(MediaSource)` 设置数据源并应用 DEFAULT_CACHE_LIMIT=50MB |
| E9 | demuxer_filter.cpp:256-282 | `DoPrepare()` 获取轨道元数据 `GetStreamMetaInfo()`，失败则发 EVENT_ERROR |
| E10 | demuxer_filter.cpp:290-347 | `HandleTrackInfos()` 遍历所有轨道，对每个有效轨道调用 `callback_->OnCallback(NEXT_FILTER_NEEDED, streamType)` 触发下游 Filter 链接 |
| E11 | demuxer_filter.cpp:878-900 | `FindStreamType()` 五类分型：STREAMTYPE_DOLBY / ENCODED_AUDIO / RAW_AUDIO / ENCODED_VIDEO / SUBTITLE |
| E12 | demuxer_filter.cpp:902-920 | `CheckIsBigendian()` 检查大端格式并通过 `g_sampleFormatBeToLe` map 转换 |
| E13 | demuxer_filter.cpp:696-698 | `GetBufferQueueProducerMap()` 返回 demuxer_ 中各轨的 AVBufferQueueProducer |
| E14 | demuxer_filter.cpp:708-719 | `SeekTo()` 三种 seek 策略：seekTime==0 → SeekToStart；MPEGTS → SeekToKeyFrame；其他 → SeekTo |
| E15 | demuxer_filter.cpp:753-806 | `LinkNext()` 链接下游 Filter，从 track_id_map_ 获取 trackId，将 MEDIA_FILE_TYPE 和增强标志注入 meta |
| E16 | demuxer_filter.cpp:842-857 | `OnLinkedResult()` 接收下游就绪的 AVBufferQueueProducer，调用 `demuxer_->SetOutputBufferQueue(trackId, queue)` |
| E17 | media_demuxer.cpp:150-156 | `ptsManagedFileTypes` = {AVI, MPEGPS, WMV}，这些格式需要 PTS 管理 |
| E18 | demuxer_filter.cpp:434-444 | `DoStart()` 调用 `demuxer_->Start()` 启动解封装循环，isLoopStarted 标志管理循环状态 |
| E19 | demuxer_filter.cpp:1055-1063 | `ResumeDemuxerReadLoop()` / `PauseDemuxerReadLoop()` 控制读循环暂停/恢复 |
| E20 | demuxer_filter.h:174-178 | 关键成员变量：isTransCoderMode_ / track_id_map_ / isLoopStarted_ / mediaSource_ / demuxer_ |

## 关键文件清单

```
services/media_engine/filters/
├── demuxer_filter.cpp                    # DemuxerFilter 实现（1206行）
├── demuxer_filter.h                      # DemuxerFilter 头文件

interfaces/inner_api/native/
├── demuxer_filter.h                     # 对外 API 头文件（Filter 基类派生）

services/media_engine/modules/demuxer/
├── media_demuxer.cpp                     # MediaDemuxer 核心引擎实现
├── media_demuxer.h                       # MediaDemuxer 接口定义（ReadSample/SeekTo等）
```

## Filter Pipeline 定位

```
[SourcePlugin / MediaSource]
        ↓ SetDataSource()
[DemuxerFilter]  ← "builtin.player.demuxer"
        ↓ LinkNext(video)    ↓ LinkNext(audio)   ↓ LinkNext(subtitle)
[VideoDecoderFilter]  [AudioDecoderFilter]  [SubtitleSinkFilter]
        ↓                     ↓
[VideoRenderFilter]   [AudioSinkFilter]
        ↓                     ↓
   [Surface]            [AudioOutput]
```

## 附录：g_sampleFormatBeToLe 映射表

| 源格式（大端） | 目标格式（小端） |
|----------------|-----------------|
| SAMPLE_S16BE   | SAMPLE_S16LE    |
| SAMPLE_S24BE   | SAMPLE_S24LE    |
| SAMPLE_S32BE   | SAMPLE_S32LE    |
| SAMPLE_F32BE   | SAMPLE_F32LE    |
| SAMPLE_F64BE   | SAMPLE_F32LE    |
| SAMPLE_S8      | SAMPLE_U8       |
| SAMPLE_F64LE   | SAMPLE_F32LE    |
| SAMPLE_S64LE   | SAMPLE_S32LE    |
| SAMPLE_S8P     | SAMPLE_U8       |
| SAMPLE_S16LEP  | SAMPLE_S16LE    |
| SAMPLE_S16BEP  | SAMPLE_S16LE    |
| SAMPLE_S24LEP  | SAMPLE_S24LE    |
| SAMPLE_S32LEP  | SAMPLE_S32LE    |
| SAMPLE_DVD     | SAMPLE_S16LE    |
| SAMPLE_BLURAY  | SAMPLE_S24LE    |

owner: 耀耀
review: pending
