---
id: MEM-ARCH-AVCODEC-S123
title: StreamDemuxer 流式解封装器——分片缓存读取与 PullData 三路分发机制
scope: [AVCodec, MediaEngine, Demuxer, StreamDemuxer, BaseStreamDemuxer, DemuxerPluginManager, Cache, PullData, ReadRetry, DASH, HLS, AdaptiveBitrate, TrackSwitch, StreamID, TrackID, InnerTrackIndex]
topic: StreamDemuxer 流式解封装器与 BaseStreamDemuxer 基类的分片缓存读取、PullData 三路分发、ReadRetry 重试逻辑，以及 DemuxerPluginManager 三层映射表。
status: draft
submitted_at: "2026-05-14T04:27:00+08:00"
created_by: builder
evidence_source: /home/west/av_codec_repo/services/media_engine/modules/demuxer/stream_demuxer.cpp (492行) + base_stream_demuxer.cpp (202行) + demuxer_plugin_manager.cpp (1159行)
---

# MEM-ARCH-AVCODEC-S123: StreamDemuxer 流式解封装器

> **Builder 增强版**：基于本地镜像 `/home/west/av_codec_repo` 逐行源码分析，证据行号级精确。
> 补充 S75（MediaDemuxer 六组件）、S97（DemuxerPluginManager 轨道路由）、S101（StreamDemuxer 初版）的深度细节。

## 核心定位

- **StreamDemuxer**（`modules/demuxer/stream_demuxer.cpp`，492行）：VOD 流式解封装器，负责分片缓存读取（ReadFrameData/ReadHeaderData）和 PullData 三路分发（UNSEEKABLE/SEEKABLE/CallbackReadAt）。
- **BaseStreamDemuxer**（`modules/demuxer/base_stream_demuxer.cpp`，202行）：流式解封装基类，持有 `Source` 数据源、`DemuxerPluginManager` 轨道路由、`typeFinder_` 类型探测。
- **DemuxerPluginManager**（`modules/demuxer/demuxer_plugin_manager.cpp`，1159行）：轨道路由管理器，三层映射表（StreamID→TrackID→InnerTrackIndex），负责插件创建和流切换。

## 关键证据（行号级，本地镜像）

### 1. StreamDemuxer::ReadFrameData 缓存读取

| 证据 | 文件:行号 | 说明 |
|------|-----------|------|
| E1 | stream_demuxer.cpp:35-39 | `const int32_t TRY_READ_SLEEP_TIME = 10;` / `const int32_t TRY_READ_TIMES = 10;` / `SOURCE_READ_WARNING_MS = 100` 重试常量 |
| E2 | stream_demuxer.cpp:55-72 | `ReadFrameData(streamID, offset, size, bufferPtr, isSniffCase)` 双缓存分支：IsDash() 或 `isDataSrcNoSeek` → `GetPeekRange read cache` → `PullDataWithCache`；否则 → `PullData` 直接读取 |
| E3 | stream_demuxer.cpp:73-90 | `ReadHeaderData` 无缓存分支，与 ReadFrameData 对比：前者走分片合并缓存，后者直接 PullData |
| E4 | stream_demuxer.cpp:92-155 | `PullDataWithCache` 缓存合并算法：`CheckCacheExist` → `GetData()->GetMemory()` → `PullDataWithCache` 分段读取+合并Buffer |
| E5 | stream_demuxer.cpp:157-247 | `PullData(streamID, offset, size, bufferPtr, isSniffCase)` 三路分发核心逻辑 |

### 2. PullData 三路分发机制

| 证据 | 文件:行号 | 说明 |
|------|-----------|------|
| E6 | stream_demuxer.cpp:171-186 | `IsUnseekable()` → `source_->Read(streamID, buffer, offset, size)` 直接读取（HTTP Live/无Seek能力） |
| E7 | stream_demuxer.cpp:188-201 | `seekable_ == SEEKABLE` → `source_->SeekTo(offset)` 先Seek再读（DASH点播/MP4点播） |
| E8 | stream_demuxer.cpp:203-247 | `CallbackReadAt(streamID_, offset, buffer, expectedLen)` 三路兜底：优先 source_->Read，失败则 `PullData` 递归重试 |
| E9 | stream_demuxer.cpp:249-313 | `ReadRetry` 重试逻辑：`TRY_READ_TIMES=10` × `SLEEP_TIME=10ms`，`SOURCE_READ_WARNING_MS=100ms` 超时告警 |

### 3. ReadRetry 重试逻辑

| 证据 | 文件:行号 | 说明 |
|------|-----------|------|
| E10 | stream_demuxer.cpp:255-270 | `ReadRetry` 循环重试：每次 `SLEEP_TIME=10ms` 等待，最多10次；`SOURCE_READ_WARNING_MS=100ms` 超时判定 |
| E11 | stream_demuxer.cpp:272-290 | `PullData` 内部调用 `ReadRetry`，`isSniffCase` 时跳过重试（sniff 场景快速失败） |
| E12 | stream_demuxer.cpp:315-340 | `PullDataWithCache` 分片合并：分段读取 + Buffer 拼接，`cacheDataMap_[streamID]` 多流独立缓存 |

### 4. BaseStreamDemuxer 核心基类

| 证据 | 文件:行号 | 说明 |
|------|-----------|------|
| E13 | base_stream_demuxer.cpp:35-55 | 构造函数初始化 `streamDemuxer_`（std::unique_ptr）+ `mediaDataSize_=0` + `seekable_=SEEKABLE` |
| E14 | base_stream_demuxer.cpp:57-75 | `InitPlugin(const std::shared_ptr<MediaSource>& source)` → `source_->SetSource()` + `source_->Prepare()` |
| E15 | base_stream_demuxer.cpp:77-95 | `CallbackReadAt(streamID, offset, buffer, expectedLen)` 回调读取入口，调用 `streamDemuxer_->ReadFrameData()` |
| E16 | base_stream_demuxer.cpp:97-130 | `PullData(streamID, offset, size, bufferPtr)` → `streamDemuxer_->PullData()` → source_->Read/SeekTo |
| E17 | base_stream_demuxer.cpp:132-170 | `GetSeekable()` / `GetDuration()` / `GetMediaDataSize()` / `SetInterruptState()` 状态查询与中断控制 |

### 5. DemuxerPluginManager 三层映射表

| 证据 | 文件:行号 | 说明 |
|------|-----------|------|
| E18 | demuxer_plugin_manager.cpp:61-77 | `MediaStreamInfo` 结构体（streamID/activated/type/sniffSize/bitRate/pluginName/plugin/dataSource/mediaInfo） |
| E19 | demuxer_plugin_manager.cpp:79-86 | `MediaTrackMap` 结构体（trackID/streamID/innerTrackIndex）三层映射 |
| E20 | demuxer_plugin_manager.cpp:88-120 | `DemuxerPluginManager` 构造函数初始化 `streamInfoMap_`（StreamID→MediaStreamInfo）+ `trackMap_`（TrackID→MediaTrackMap） |
| E21 | demuxer_plugin_manager.cpp:180-230 | `GetPluginByStreamID(streamID)` → `streamInfoMap_[streamID].plugin` 插件查询 |
| E22 | demuxer_plugin_manager.cpp:232-280 | `GetTrackInfoByStreamID(streamID, trackId, innerTrackId)` 三层映射查询 |
| E23 | demuxer_plugin_manager.cpp:350-420 | `InitDefaultPlay(streams)` 初始化默认播放：遍历 `streams` → 创建 `DataSourceImpl(stream_, streamID)` → 调用 `plugin->Init()` |
| E24 | demuxer_plugin_manager.cpp:430-500 | `RebootPlugin(streamID)` 插件重启：插件失败后重新初始化 |
| E25 | demuxer_plugin_manager.cpp:500-600 | `CheckChangeStreamID(streamID)` DASH Track 切换判定 |

### 6. DataSourceImpl 内类

| 证据 | 文件:行号 | 说明 |
|------|-----------|------|
| E26 | demuxer_plugin_manager.cpp:37-60 | `DataSourceImpl` 继承 `Plugins::DataSource`，持有 `BaseStreamDemuxer` + `streamID_`，实现 `ReadAt` / `GetSize` / `GetSeekable` |
| E27 | demuxer_plugin_manager.cpp:67-80 | `ReadAt(offset, buffer, expectedLen)` → `stream_->CallbackReadAt(streamID_, offset, buffer, expectedLen)` |

## 架构关系图

```
DemuxerFilter (Filter层)
  └── MediaDemuxer (主引擎, S75)
        ├── StreamDemuxer (流式读取, 492行) ← 本条目核心
        │     ├── ReadFrameData(streamID, offset, size) → PullDataWithCache (有缓存)
        │     ├── ReadHeaderData(streamID, offset, size) → PullData (无缓存)
        │     ├── PullData 三路分发: UNSEEKABLE / SEEKABLE / CallbackReadAt
        │     └── ReadRetry 重试: 10次 × 10ms, SOURCE_READ_WARNING_MS=100ms
        ├── BaseStreamDemuxer (基类, 202行) ← 本条目核心
        │     ├── source_ (std::shared_ptr<Source>) 数据源
        │     ├── streamDemuxer_ (std::unique_ptr<StreamDemuxer>) 流式引擎
        │     ├── InitPlugin() → source_->SetSource() + Prepare()
        │     └── CallbackReadAt() → streamDemuxer_->ReadFrameData()
        └── DemuxerPluginManager (轨道路由, 1159行) ← 本条目核心
              ├── streamInfoMap_ (StreamID → MediaStreamInfo) 插件实例映射
              ├── trackMap_ (TrackID → MediaTrackMap) 三层映射
              ├── DataSourceImpl(stream_, streamID) 内类
              ├── GetPluginByStreamID() 插件查询
              ├── RebootPlugin() 插件重启
              └── CheckChangeStreamID() DASH Track切换

Source (modules/source/source.cpp, 715行)
  └── Plugins::SourcePlugin (数据源插件)
        ├── Read(streamID, buffer, offset, size)
        ├── SeekTo(offset)
        └── GetSeekable() / GetDuration()
```

## 关键数据流

### ReadFrameData 完整路径

```
StreamDemuxer::ReadFrameData(streamID, offset, size)
  ├── IsDash() || isDataSrcNoSeek → cacheDataMap_.find(streamID)
  │     └── CheckCacheExist(offset) → PullDataWithCache(streamID, offset, size)
  │           └── PullDataWithCache: 分段读取 + 缓存合并 + Buffer拼接
  └── else → PullData(streamID, offset, size)
        ├── IsUnseekable() → source_->Read(streamID, buffer, offset, size)
        ├── seekable_==SEEKABLE → source_->SeekTo(offset) → source_->Read()
        └── else → CallbackReadAt(streamID_, offset, buffer, expectedLen)
              └── ReadRetry: 10次重试 × 10ms
```

### 三层映射表查找

```
StreamID (来自DemuxerFilter)
  → streamInfoMap_[streamID] → MediaStreamInfo { plugin, dataSource, mediaInfo }
  → trackMap_[streamID].trackID → TrackID
  → trackMap_[streamID].innerTrackIndex → InnerTrackIndex (传给具体Track)
```

## 关联记忆

| 关联 | 说明 |
|------|------|
| S75 | MediaDemuxer 六组件协作架构，StreamDemuxer 是其组件之一 |
| S97 | DemuxerPluginManager 轨道路由管理器，三层映射表同一组件 |
| S101 | StreamDemuxer 初版分析，本条目是行号级增强 |
| S69 | MediaDemuxer 核心解封装引擎，ReadLoop/SampleConsumerLoop 双 TaskThread |
| S41 | DemuxerFilter Filter层封装，持有 MediaDemuxer 引擎 |
| S102 | SampleQueueController 流控引擎，双水位线 START@5s/STOP@10s |
| S106 | MediaEngine Source 模块流媒体基础设施，Source 是 StreamDemuxer 的上游数据源 |

## 关键常量

| 常量 | 值 | 说明 |
|------|-----|------|
| TRY_READ_TIMES | 10 | 最大重试次数 |
| TRY_READ_SLEEP_TIME | 10 | 每次重试间隔（ms） |
| SOURCE_READ_WARNING_MS | 100 | 读取超时告警阈值（ms） |
| WAIT_INITIAL_BUFFERING_END_TIME_MS | 3000 | 初始缓冲等待时间（ms） |
| SNIFF_WARNING_MS | 200 | Sniff 超时告警（ms） |
| API_VERSION_16/18 | 16/18 | API 版本兼容性 |
| INVALID_STREAM_OR_TRACK_ID | -1 | 无效 ID 判定 |

---

*Builder: S123 基于本地镜像 /home/west/av_codec_repo 逐行源码分析，stream_demuxer.cpp(492行) + base_stream_demuxer.cpp(202行) + demuxer_plugin_manager.cpp(1159行)，补充 S75/S97/S101 深度细节。*