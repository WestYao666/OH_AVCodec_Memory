# MEM-ARCH-AVCODEC-S98

## 主题

三路 Sink 引擎协作架构——VideoSink / AudioSink / SubtitleSink 与 MediaSyncManager 联动

## 状态

approved

## 标签

AVCodec, MediaEngine, Sink, MediaSync, VideoSink, AudioSink, SubtitleSink, IMediaSynchronizer, DoSyncWrite, MediaSyncManager, ReferenceParserManager, TimeRangeManager, VideoLagDetector

## 关联记忆

- S22 (MediaSyncManager 音视频同步管理中心)
- S31 (AudioSinkFilter Filter 层封装)
- S32 (VideoRenderFilter 视频渲染输出过滤器)
- S49 (SubtitleSinkFilter 字幕渲染过滤器)
- S56 (VideoSink 视频渲染同步器)
- S73 (三路 Sink 引擎同步架构，已入库)
- S77 (AVCodec DFX 子系统)
- S89 (AVCodec Filter Framework 基础架构)

## 摘要

本记忆聚焦于三路 Sink 引擎（VideoSink / AudioSink / SubtitleSink）的核心实现协作架构，以及 MediaSyncManager 作为时钟锚点供应方如何统一调度三者。

关键机制：

- **VideoSink**：前 4 帧强制渲染（`VIDEO_SINK_START_FRAME = 4`），`DoSyncWrite` 渲染决策，`CalcBufferDiff` 三元组算法，`CheckBufferLatenessMayWait` 早迟判断，`VideoLagDetector` 内嵌类追踪卡顿，`LAG_LIMIT_TIME = 100ms` 阈值，`DROP_FRAME_CONTINUOUSLY_MAX_CNT = 2` 最大连续丢帧
- **AudioSink**：双 `AVSharedMemoryBase`（数据+元数据），`AudioSinkDataCallbackImpl` 写回调，`GetBufferDesc`/`EnqueueBufferDesc` 缓冲区操作，`SetBuffering`/`SetAudioPassFlag` 状态控制
- **SubtitleSink**：`SubtitleBufferState` 三状态（WAIT/SHOW/DROP），`RenderLoop` 独立线程，`RemoveTextTags` HTML 标签剥离，`NotifyRender Tag::SUBTITLE_TEXT` 上报，`NotifySeek` 清空字幕队列
- **MediaSyncManager**：`IMediaSynchronizer` 三路优先级（`VIDEO_SINK=0` / `AUDIO_SINK=2` / `SUBTITLE_SINK=8`），`UpdateTimeAnchor` 时钟锚点，`CheckBufferLatenessMayWait` 同步等待
- **TimeRangeManager**：播放范围管理（Seek 辅助），`TimeRange` 结构体（start_ts/end_ts），`IsInTimeRanges` 时间范围查询，`ReduceRanges` 范围缩减，`TimeoutGuard` 超时监控
- **ReferenceParserManager**：GOP / I-Frame 解析，`dlopen` 加载 `.so` 插件（`CreateRefParser`/`DestroyRefParser`），`ParserNalUnits` NAL 单元解析，`ParserExtraData` 编解码器额外数据，`ParserSdtpData` 时间戳依赖解析，`GetFrameLayerInfo`/`GetGopLayerInfo` GOP 层信息查询

## Evidence（源码行号）

### VideoSink 核心（video_sink.cpp:462 行）

| 符号 | 位置 | 说明 |
|------|------|------|
| `VIDEO_SINK_START_FRAME = 4` | video_sink.cpp:59 | 前 4 帧强制渲染，无视同步决策 |
| `DoSyncWrite` | video_sink.cpp:125 | 渲染决策入口，调用 `CheckBufferLatenessMayWait` |
| `CalcBufferDiff` | video_sink.cpp:227 | 三元组算法（锚点差/视频帧差/初始等待期） |
| `CheckBufferLatenessMayWait` | video_sink.cpp:256 | 早迟判断，返回 waitTime |
| `VideoLagDetector::CalcLag` | video_sink.cpp:395 | 卡顿计算 |
| `VideoLagDetector::ResolveLagEvent` | video_sink.cpp:420 | 卡顿事件处理 |
| `LAG_LIMIT_TIME = 100` | video_sink.cpp:20 | 卡顿阈值 100ms |
| `DROP_FRAME_CONTINUOUSLY_MAX_CNT = 2` | video_sink.cpp:21 | 最大连续丢帧数 |
| `MAX_ADVANCE_US = 80000` | video_sink.cpp:23 | 最大提前量 80ms |
| `WAIT_TIME_US_THRESHOLD = 1500000` | video_sink.cpp:56 | 最大等待时间 1.5s |
| `PER_SINK_TIME_THRESHOLD_MAX = 33000` | video_sink.cpp:52 | 最大单帧下沉时间 33ms（30Hz） |
| `PER_SINK_TIME_THRESHOLD_MIN = 8333` | video_sink.cpp:53 | 最小单帧下沉时间 8.33ms（120Hz） |

### AudioSink 核心（audio_sink.cpp:1793 行）

| 符号 | 位置 | 说明 |
|------|------|------|
| `AudioSink::AudioSink()` | audio_sink.cpp:70 | 构造函数 |
| `AudioSinkDataCallbackImpl::OnWriteData` | audio_sink.cpp:102 | 数据写入回调 |
| `AudioSink::GetBufferDesc` | audio_sink.cpp:175 | 获取缓冲区描述符 |
| `AudioSink::EnqueueBufferDesc` | audio_sink.cpp:182 | 入队缓冲区描述符 |
| `AudioSink::SetBuffering` | audio_sink.cpp:136 | 设置缓冲状态 |
| `AudioSink::SetAudioPassFlag` | audio_sink.cpp:141 | 设置直通标志 |
| `HandleAudioRenderRequest` | audio_sink.cpp:146 | 渲染请求处理 |

### SubtitleSink 核心（subtitle_sink.cpp:517 行）

| 符号 | 位置 | 说明 |
|------|------|------|
| `SubtitleBufferState` 枚举 | subtitle_sink.cpp（定义处） | WAIT/SHOW/DROP 三状态 |
| `RemoveTextTags` | subtitle_sink.cpp（调用处） | HTML 标签剥离 |
| `NotifyRender Tag::SUBTITLE_TEXT` | subtitle_sink.cpp（调用处） | 字幕文本上报事件 |
| `NotifySeek` | subtitle_sink.cpp（调用处） | Seek 时清空字幕队列 |

### MediaSynchronousSink 基类（media_synchronous_sink.h:31）

```cpp
class MediaSynchronousSink : public IMediaSynchronizer, public InterruptListener { ... }
```

### TimeRangeManager（time_range_manager.h/cpp，77+74=151 行）

| 符号 | 位置 | 说明 |
|------|------|------|
| `TimeRange` 结构体 | time_range_manager.h:24-28 | start_ts/end_ts 范围结构 |
| `MAX_INDEX_CACHE_SIZE = 70*1024` | time_range_manager.h:19 | 最大缓存 70KB |
| `IsInTimeRanges` | time_range_manager.h:38 | 时间范围查询 |
| `AddTimeRange` | time_range_manager.h:39 | 添加范围 |
| `ReduceRanges` | time_range_manager.h:40 | 范围缩减 |
| `TimeoutGuard` | time_range_manager.h:44-58 | 超时监控 RAII 封装 |

### ReferenceParserManager（reference_parser_manager.cpp/h，138+54=192 行）

| 符号 | 位置 | 说明 |
|------|------|------|
| `RefParser` 基类 | reference_parser.h:59 | 抽象基类，dlopen 插件接口 |
| `CreateRefParser` | reference_parser.h:71 | `.so` 导出创建函数 |
| `DestroyRefParser` | reference_parser.h:74 | `.so` 导出销毁函数 |
| `ReferenceParserManager::Create` | reference_parser_manager.cpp:56 | 工厂方法 |
| `ReferenceParserManager::ParserNalUnits` | reference_parser_manager.cpp:71 | NAL 单元解析 |
| `ReferenceParserManager::ParserExtraData` | reference_parser_manager.cpp:77 | 编解码额外数据解析 |
| `ReferenceParserManager::ParserSdtpData` | reference_parser_manager.cpp:83 | SDTP 数据解析 |
| `ReferenceParserManager::GetFrameLayerInfo` | reference_parser_manager.cpp:89,95 | 帧层信息查询 |
| `ReferenceParserManager::GetGopLayerInfo` | reference_parser_manager.cpp:101 | GOP 层信息查询 |
| `handler_` 静态句柄 | reference_parser_manager.cpp:31 | dlopen 加载的 `.so` 句柄 |
| `CreateFunc` / `DestroyFunc` 函数指针 | reference_parser_manager.cpp:32-33 | `.so` 导出函数指针 |

## 架构图

```
MediaSyncManager (IMediaSynchronizer 时钟锚点)
    ├── VideoSink (VIDEO_SINK=0, 优先级最高)
    │       ├── DoSyncWrite()
    │       ├── CalcBufferDiff()
    │       ├── CheckBufferLatenessMayWait()
    │       └── VideoLagDetector (内嵌类)
    ├── AudioSink (AUDIO_SINK=2)
    │       ├── AudioSinkDataCallbackImpl
    │       └── GetBufferDesc/EnqueueBufferDesc
    └── SubtitleSink (SUBTITLE_SINK=8)
            ├── RenderLoop (独立线程)
            ├── SubtitleBufferState (WAIT/SHOW/DROP)
            └── RemoveTextTags()

Demuxer 层
    ├── ReferenceParserManager (dlopen RefParser .so)
    │       └── RefParser (GOP/I-Frame 解析插件)
    └── TimeRangeManager (Seek 范围管理)
            └── TimeRange (start_ts/end_ts)
```

## 关键设计决策

1. **VideoSink 前 4 帧强制渲染**：避免首帧卡顿，同步决策在前 4 帧不生效
2. **三路 Sink 优先级固定**：VIDEO_SINK=0 为时钟锚点供应方，AUDIO_SINK=2 次之，SUBTITLE_SINK=8 最低
3. **ReferenceParserManager dlopen 插件**：GOP 解析逻辑封装在独立 `.so`，通过 `CreateRefParser`/`DestroyRefParser` C 接口导出
4. **TimeRangeManager 用 `std::set<TimeRange>` 管理 Seek 范围**：自动有序，支持范围重叠时的合并缩减
5. **TimeoutGuard RAII 超时监控**：构造函数记录起始时间，`IsTimeout()` 轻量查询，避免手动计时

## 关联场景

- 新需求开发：三路 Sink 定制、MediaSyncManager 同步策略调整
- 问题定位：视频卡顿（VideoLagDetector）、音画不同步（CalcBufferDiff）、字幕显示异常（SubtitleBufferState）
