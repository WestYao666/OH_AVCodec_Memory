---
id: MEM-ARCH-AVCODEC-S97
title: "DemuxerPluginManager 轨道路由管理器——StreamID/TrackID/InnerTrackIndex 三层映射表与 Seek/Reboot 策略"
scope: [AVCodec, MediaEngine, Demuxer, DemuxerPluginManager, Track, StreamDemuxer, Seek, SnifferMediaType, TrackType, RebootPlugin, StreamInfo]
status: draft
created_by: builder-agent
created_at: "2026-05-08T02:45:00+08:00"
evidence_sources:
  - "services/media_engine/modules/demuxer/demuxer_plugin_manager.cpp (1159行)"
  - "services/media_engine/modules/demuxer/demuxer_plugin_manager.h (69行头文件定义)"
---

# S97: DemuxerPluginManager 轨道路由管理器——StreamID/TrackID/InnerTrackIndex 三层映射表与 Seek/Reboot 策略

## 一句话总结

DemuxerPluginManager（1159行cpp）是 MediaDemuxer 的**轨道路由与插件加载中枢**，管理 StreamID↔TrackID↔InnerTrackIndex 三层映射表，通过 SnifferMediaType 识别容器格式并加载对应 DemuxerPlugin，负责 Seek/Reboot/EOS 等多轨协调操作，是 DemuxerFilter 下游调用最频繁的 Manager。

## 源码分析

### 1. 核心类定义

**文件**: `demuxer_plugin_manager.cpp` (1159行) + `demuxer_plugin_manager.h` (69行)
**Log Tag**: `LOG_DOMAIN_SYSTEM_PLAYER / "DemuxerPluginManager"`
**命名空间**: `OHOS::Media`

```cpp
class DemuxerPluginManager {
    // 三层映射核心
    std::map<int32_t, MediaStreamInfo> streamInfoMap_;   // <streamID, MediaStreamInfo>
    std::map<int32_t, MediaTrackMap> trackInfoMap_;      // <trackId, MediaTrackMap>
    std::map<int32_t, MediaTrackMap> temp2TrackInfoMap_; // <trackId, MediaTrackMap> 播放时活跃track

    // 当前激活的 StreamID
    int32_t curVideoStreamID_ = -1;
    int32_t curAudioStreamID_ = -1;
    int32_t curSubTitleStreamID_ = -1;
    
    bool isDash_ = false;
    bool isHlsFmp4_ = false;
    std::string pluginName_ {};  // 已识别到的插件名（如 "mpeg4" / "ffmpeg"）
};
```

### 2. 三层映射结构

定义于 `demuxer_plugin_manager.h:71-89`:

```cpp
struct MediaStreamInfo {
    Plugins::DemuxerPlugin plugin;
    StreamType type;
    Plugins::MediaInfo mediaInfo;
    int64_t sniffSize;
};

struct MediaTrackMap {
    int32_t streamID;
    int32_t trackID;
    int32_t innerTrackIndex;  // Plugin 内部的 track index
};
```

**三层转换路径**：
- `trackId` → `GetTmpStreamIDByTrackID()` → `streamID` → `streamInfoMap_[streamID].plugin`
- `trackId` → `GetTmpInnerTrackIDByTrackID()` → `innerTrackIndex` → Plugin 接口参数

### 3. 容器格式嗅探（SnifferMediaType）

**关键代码** `demuxer_plugin_manager.cpp:306-326`:
```cpp
Status DemuxerPluginManager::LoadDemuxerPlugin(int32_t streamID, std::shared_ptr<BaseStreamDemuxer> streamDemuxer)
{
    StreamInfo streamInfo;
    streamInfo.streamId = streamID;
    streamInfo.type = streamInfoMap_[streamID].type;
    streamInfo.sniffSize = streamInfoMap_[streamID].sniffSize;
    ScopedTimer timer("SnifferMediaType", SNIFF_WARNING_MS);  // 超时告警阈值200ms
    type = streamDemuxer->SnifferMediaType(streamInfo);  // 调用 BaseStreamDemuxer 嗅探
    if (!type.empty() && pluginName_.empty()) {
        pluginName_ = type;  // 缓存识别到的插件名
    }
    MediaTypeFound(streamDemuxer, type, streamID);  // 触发插件加载
    // ...
}
```

**SnifferMediaType** 是容器识别入口，`SNIFF_WARNING_MS = 200ms` 超时会打日志警告。

### 4. 轨道初始化

| 方法 | 行号 | 职责 |
|------|------|------|
| `InitAudioTrack` | 151 | 初始化音频轨道：设置 MIME/BitRate/Channels/SampleRate |
| `InitVideoTrack` | 181 | 初始化视频轨道：加 VIDEO_WIDTH/HEIGHT/HDR_VIVID |
| `InitSubtitleTrack` | 215 | 初始化字幕轨道 |
| `InitDefaultPlay` | 233 | 按 StreamInfo 列表初始化默认播放轨道 |

### 5. Seek 策略（多层级）

| 方法 | 行号 | 策略 |
|------|------|------|
| `SeekTo` | 763 | 主 Seek 接口，调用单轨或全局 Seek |
| `SeekToKeyFrame` | 811 | 按关键帧 Seek，支持 `DemuxerCallerType` 区分调用者 |
| `SeekToFrameByDts` | 840 | 按 DTS 精确到帧（`SEEKTOFRAMEBYDTS_TIMEOUT_MS = 200ms` 超时监控） |
| `SeekToStart` | 787 | Seek 到起始位置（用于外挂字幕重置） |
| `SingleStreamSeekTo` | 751 | 单轨独立 Seek（字幕轨道专用） |

### 6. 插件生命周期管理

| 方法 | 行号 | 职责 |
|------|------|------|
| `StartPlugin` | 630 | 启动指定 streamID 的 DemuxerPlugin |
| `StopPlugin` | 650 | 停止指定 streamID 的 DemuxerPlugin |
| `RebootPlugin` | 666 | 重新启动（如切换码率后重启） |
| `StartAllPlugin` | - | 启动所有已加载插件 |
| `StopAllPlugin` | - | 停止所有插件 |
| `Flush` | 853 | 清空所有轨道缓冲 |
| `Pause` / `Resume` / `Reset` | 954/978/885 | 状态切换 |

### 7. 码率与媒体信息更新

**关键代码** `demuxer_plugin_manager.cpp:978-1012`:
```cpp
Status DemuxerPluginManager::UpdateDefaultStreamID(Plugins::MediaInfo& mediaInfo, StreamType type, int32_t newStreamID)
Status DemuxerPluginManager::UpdateMediaInfo(int32_t streamID)
uint32_t GetCurrentBitRate()
```

HLS/DASH 自适应码率切换时，`UpdateMediaInfo` 更新轨道元数据，`UpdateDefaultStreamID` 切换主轨。

### 8. 字幕外挂支持

```cpp
int32_t AddExternalSubtitle()  // 行 1095
Status localSubtitleSeekTo(int64_t seekTime)   // 行 729
Status localSubtitleSeekToStart(int64_t seekTime) // 行 740
```

外挂字幕（srt/vtt/lrc/sami/ass）通过独立 StreamID 管理，不走主 DemuxerPlugin。

### 9. 与 DemuxerFilter 的协作

DemuxerPluginManager 被 MediaDemuxer（`media_demuxer.cpp` 6012行）持有，作为**内部组件**而非独立 Filter。对外暴露的接口通过 MediaDemuxer 间接调用：
- `MediaDemuxer::SeekTo` → `DemuxerPluginManager::SeekTo`
- `MediaDemuxer::SelectTrack` → 更新 `temp2TrackInfoMap_`
- `MediaDemuxer::ReadSample` → 通过 streamID 路由到对应 Plugin

## 关键设计模式

### 三层映射表设计

```
StreamID (来自 Source/Protocol 层)
  ↓ streamInfoMap_[streamID]
StreamType (AUDIO/VIDEO/SUBTITLE)
  ↓ trackInfoMap_[trackId] 
TrackID (外部 API 使用的统一track标识)
  ↓ temp2TrackInfoMap_[trackId]
InnerTrackIndex (Plugin内部索引)
```

`temp2TrackInfoMap_` 支持**动态轨道切换**（如外挂字幕替换），仅修改映射不重建表。

### 超时监控

- `SNIFF_WARNING_MS = 200`：容器格式识别超时
- `SEEKTOKEYFRAME_WARNING_MS = 0`：Seek 关键帧超时（无声告警）
- `SEEKTOFRAMEBYDTS_TIMEOUT_MS = 200`：DTS 帧定位超时

## 关联记忆

| 关联 | 说明 |
|------|------|
| S41（DemuxerFilter） | 上游 Filter，通过 MediaDemuxer 间接调用本 Manager |
| S69（MediaDemuxer） | 本 Manager 的直接容器（1159行cpp是该容器的内部组件） |
| S79（MPEG4DemuxerPlugin） | SnifferMediaType 识别后加载的具体插件之一 |
| S76（FFmpegDemuxerPlugin） | 另一个插件选项，rank=50 低于原生插件 rank=100 |
| S96（TimeAndIndexConversion） | Seek 时 PTS 计算依赖本 Manager 的轨道映射 |

## 适用场景

- **问题定位**：多轨 Seek 定位不准 / 码率切换后轨道错乱 / 外挂字幕不同步
- **新需求开发**：新增容器格式支持（扩展 SnifferMediaType 分支）
- **性能分析**：Sniff 超时告警（200ms）→ 慢容器识别优化