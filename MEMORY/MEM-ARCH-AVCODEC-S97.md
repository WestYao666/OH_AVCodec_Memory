# MEM-ARCH-AVCODEC-S97: DemuxerPluginManager 轨道路由管理器
**审批状态**: approved
**生成时间**: 2026-05-08T04:05
**scope**: AVCodec, MediaEngine, Demuxer, DemuxerPluginManager, Track, StreamDemuxer, Seek, SnifferMediaType, TrackType, RebootPlugin, StreamInfo
**关联场景**: 新需求开发/问题定位
**关联记忆**: S69(MediaDemuxer容器)/S79(MPEG4DemuxerPlugin)/S76(FFmpegDemuxerPlugin)

---

## 核心定位

DemuxerPluginManager(demuxer_plugin_manager.cpp:1159行)是MediaDemuxer引擎的**轨道路由与插件加载中枢**，负责：
- 多流(音视频字幕)插件管理
- StreamID/TrackID/InnerTrackIndex三层ID映射
- 容器格式探测(SnifferMediaType)
- Seek策略分发
- 插件重启(Reboot)

## 源码实证

### 1. 三层映射表

```cpp
// demuxer_plugin_manager.h:162-166 (三map结构)
std::map<int32_t, MediaStreamInfo> streamInfoMap_;      // <streamId, MediaStreamInfo>
std::map<int32_t, MediaTrackMap> trackInfoMap_;         // <trackId, MediaTrackMap>
std::map<int32_t, MediaTrackMap> temp2TrackInfoMap_;    // <trackId, MediaTrackMap> 当前播放中的track

// MediaStreamInfo (stream层，每streamId一个)
struct MediaStreamInfo {
    int32_t streamID = -1;
    bool activated = false;
    StreamType type;                                     // VIDEO/AUDIO/SUBTITLE
    uint64_t sniffSize;
    uint32_t bitRate;
    std::string pluginName = "";
    std::shared_ptr<Plugins::DemuxerPlugin> plugin;      // 插件实例
    std::shared_ptr<DataSourceImpl> dataSource;         // 数据源回调
    Plugins::MediaInfo mediaInfo;
};

// MediaTrackMap (track层，每track一个)
struct MediaTrackMap {
    int32_t trackID = -1;        // 外部分配的track ID
    int32_t streamID = -1;       // 所属stream ID
    int32_t innerTrackIndex = -1;// 插件内部的track索引
};
```

### 2. TrackType 枚举

```cpp
// demuxer_plugin_manager.h:46-51
enum TrackType {
    TRACK_VIDEO = 0,
    TRACK_AUDIO,
    TRACK_SUBTITLE,
    TRACK_INVALID
};
```

### 3. 三层ID互相转换函数

```cpp
// demuxer_plugin_manager.cpp

// TrackID → InnerTrackIndex
int32_t DemuxerPluginManager::GetInnerTrackIDByTrackID(int32_t trackId)
// 调用: trackInfoMap_[trackId].innerTrackIndex

// TrackID → StreamID
int32_t DemuxerPluginManager::GetStreamIDByTrackID(int32_t trackId)
// 调用: trackInfoMap_[trackId].streamID

// StreamID → TrackID + InnerTrackIndex (重载)
void DemuxerPluginManager::GetTrackInfoByStreamID(int32_t streamID, int32_t& trackId, int32_t& innerTrackId)
// 实现: find_if遍历trackInfoMap_，匹配item.second.streamID == streamID

// TrackType → StreamID
int32_t DemuxerPluginManager::GetStreamIDByTrackType(TrackType type)
// TRACK_VIDEO→curVideoStreamID_ / TRACK_AUDIO→curAudioStreamID_ / TRACK_SUBTITLE→curSubTitleStreamID_

// StreamID → Plugin实例
std::shared_ptr<Plugins::DemuxerPlugin> DemuxerPluginManager::GetPluginByStreamID(int32_t streamID)
// 调用: streamInfoMap_[streamID].plugin
```

### 4. 容器格式探测 SnifferMediaType (200ms超时监控)

```cpp
// demuxer_plugin_manager.cpp:319-326
constexpr int64_t SNIFF_WARNING_MS = 200;  // 超时警告阈值
// ...
ScopedTimer timer("SnifferMediaType", SNIFF_WARNING_MS);
type = streamDemuxer->SnifferMediaType(streamInfo);
// 返回非空type → 调用MediaTypeFound → LoadDemuxerPlugin加载对应插件

void DemuxerPluginManager::MediaTypeFound(
    std::shared_ptr<BaseStreamDemuxer> streamDemuxer,
    const std::string& pluginName,
    int32_t id  // streamID
) {
    // 依次尝试加载audio/video/subtitle三个track的插件
    if (curAudioStreamID_ != INVALID_STREAM_OR_TRACK_ID) {
        Status ret = LoadDemuxerPlugin(curAudioStreamID_, streamDemuxer);
    }
    if (curVideoStreamID_ != INVALID_STREAM_OR_TRACK_ID) {
        Status ret = LoadDemuxerPlugin(curVideoStreamID_, streamDemuxer);
    }
    if (curSubTitleStreamID_ != INVALID_STREAM_OR_TRACK_ID) {
        Status ret = LoadDemuxerPlugin(curSubTitleStreamID_, streamDemuxer);
    }
}
```

### 5. Seek 五策略

```cpp
// demuxer_plugin_manager.h:105-109
Status SeekTo(int64_t seekTime, Plugins::SeekMode mode, int64_t& realSeekTime);
Status SeekToStart(int64_t seekTime, int64_t& realSeekTime);
Status SeekToKeyFrame(int64_t seekTime, Plugins::SeekMode mode,
    int64_t& realSeekTime, DemuxerCallerType callerType);
Status SeekToFrameByDts(int32_t streamID, int32_t trackId, int64_t seekTime,
    Plugins::SeekMode mode, int64_t& realSeekTime);
Status SingleStreamSeekTo(int64_t seekTime, Plugins::SeekMode mode,
    int32_t streamID, int64_t& realSeekTime);

// SeekTo实现 (demuxer_plugin_manager.cpp:763-779)
// 遍历audio/video/subtitle三个track，各自调用plugin->SeekTo
// realSeekTime取三个track中最小的实际seek时间

// SingleStreamSeekTo (demuxer_plugin_manager.cpp:751-759)
// 仅对指定streamID的track执行SeekTo
// 用于字幕独立seek场景

// localSubtitleSeekTo (demuxer_plugin_manager.cpp:729-737)
// 字幕seek特殊实现：先SEEK_PREVIOUS_SYNC，再SEEK_NEXT_SYNC兜底
```

### 6. RebootPlugin 插件重启机制

```cpp
// demuxer_plugin_manager.cpp:666-698
Status DemuxerPluginManager::RebootPlugin(
    int32_t streamId,
    TrackType trackType,
    std::shared_ptr<BaseStreamDemuxer> streamDemuxer,
    bool& isRebooted
) {
    // 1. 释放旧插件：streamInfoMap_[streamId].plugin = nullptr
    // 2. 重新探测：streamInfoMap_[streamId].pluginName = streamDemuxer->SnifferMediaType(streamInfo)
    // 3. 重新加载：LoadDemuxerPlugin(streamId, streamDemuxer)
    // 4. isRebooted = true
}
```

### 7. AddExternalSubtitle 外挂字幕

```cpp
// demuxer_plugin_manager.h:151
int32_t AddExternalSubtitle();
// 返回新分配的streamID，独立于主streams管理
```

## 架构位置

```
MediaDemuxer (主引擎)
  └── DemuxerPluginManager (轨道路由中枢)
        ├── StreamDemuxer (流式读取)
        ├── TypeFinder (类型探测)
        └── DemuxerPlugin (具体解封插件)
              ├── MPEG4DemuxerPlugin (rank=100 自研优先)
              └── FFmpegDemuxerPlugin (rank=50 FFmpeg兜底)
```

## 与S69/S79/S76关系

| 主题 | 层级 | 说明 |
|------|------|------|
| S69 | MediaDemuxer引擎 | 6012行主引擎，含DemuxerPluginManager |
| S75 | 六组件协作架构 | DemuxerPluginManager作为独立组件之一 |
| S97 | **本次主题** | DemuxerPluginManager单组件深度分析 |
| S79 | MPEG4DemuxerPlugin | rank=100自研MP4解析，Sniff置信度探测 |
| S76 | FFmpegDemuxerPlugin | rank=50 libavformat封装，av_read_frame管线 |
| S41 | DemuxerFilter | Filter层封装，track_id_map_路由表 |

## 关键设计点

1. **三层ID映射**：
   - StreamID：数据流维度(每个媒体流一个)
   - TrackID：外部分配的统一track标识
   - InnerTrackIndex：插件内部track索引

2. **SnifferMediaType超时监控**：200ms阈值ScopedTimer，超时打印警告日志

3. **RebootPlugin**：插件故障后自动重新探测+加载，不重启整个Demuxer

4. **外挂字幕独立StreamID**：AddExternalSubtitle返回新streamID，不走主tracks体系

5. **五路Seek策略**：SeekTo(全轨道)/SeekToStart/SeekToKeyFrame/SeekToFrameByDts/SingleStreamSeekTo(单轨)

---

**审批状态**: approved
**提交时间**: 2026-05-08T04:05
