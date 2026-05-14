---
type: architecture
id: MEM-ARCH-AVCODEC-S144
status: pending_approval
created_at: "2026-05-15T03:02:38+08:00"
updated_at: "2026-05-15T03:02:38+08:00"
created_by: builder
topic: DemuxerPluginManager 插件管理与 BaseStreamDemuxer 流式解封装——1159行cpp/多StreamDemuxer/TrackMap/临时映射/Plugin加载/Sniffer路由/StreamID分配
scope: [AVCodec, MediaEngine, DemuxerPluginManager, BaseStreamDemuxer, StreamDemuxer, Plugin, Sniffer, Track, StreamID, TrackMap, MediaStreamInfo, LoadDemuxerPlugin, GetPluginByStreamID, DASH, HTTP]
created_at: "2026-05-15T03:02:38+08:00"
summary: DemuxerPluginManager插件管理(1159行cpp)+BaseStreamDemuxer流式解封装(202行cpp)，多StreamDemuxer架构/TrackMap临时映射/Plugin加载Sniffer路由/StreamID分配，与S75/S101/S102关联
source_repo: /home/west/av_codec_repo
source_root: services/media_engine/modules/demuxer
evidence_version: local_mirror
---

## 一、架构总览

DemuxerPluginManager 与 BaseStreamDemuxer 是 MediaDemuxer 体系中的**插件管理层**与**流式解封装基类**，位于 `services/media_engine/modules/demuxer/` 目录：

- **DemuxerPluginManager**（`demuxer_plugin_manager.cpp`，1159行）：负责 Demuxer 插件加载、Sniffer 路由、StreamID/TrackID 映射管理
- **BaseStreamDemuxer**（`base_stream_demuxer.cpp`，202行 / `base_stream_demuxer.h`，161行）：流式解封装基类，持有 CacheData 分片缓存，支持 DASH/HTTP 多流

**定位**：S75（MediaDemuxer 六组件）中 DemuxerPluginManager 与 StreamDemuxer 的源码级深度分析，补充 S101/S102 的具体实现。

## 二、文件清单与行号级证据

| 文件 | 行数 | 说明 |
|------|------|------|
| `demuxer_plugin_manager.cpp` | 1159 | DemuxerPluginManager 插件管理器（LoadDemuxerPlugin/GetPluginByStreamID/TrackMap） |
| `demuxer_plugin_manager.h` | 196 | DemuxerPluginManager 类定义 + MediaStreamInfo/MediaTrackMap 结构体 |
| `base_stream_demuxer.cpp` | 202 | BaseStreamDemuxer 基类实现 |
| `base_stream_demuxer.h` | 161 | BaseStreamDemuxer 类定义 + DemuxerState/CacheData 结构体 |

## 三、DemuxerPluginManager 核心设计

### 3.1 关键结构体（demuxer_plugin_manager.h:51-90）

```cpp
// demuxer_plugin_manager.h:51-66 - DataSourceImpl（Plugin 数据源适配器）
class DataSourceImpl : public Plugins::DataSource {
    std::shared_ptr<BaseStreamDemuxer> stream_;  // 持有 StreamDemuxer 引用
    int32_t streamID_;
    bool isDash_ = false;  // DASH 流标志
    Status ReadAt(int64_t offset, std::shared_ptr<Buffer>& buffer, size_t expectedLen) override;  // 行 55
    Status GetSize(uint64_t& size) override;
    bool IsDash() override;  // 行 60，区分 DASH/普通流
    bool IsOffsetValid(int64_t offset) const;  // 行 63，偏移有效性检查
};

// demuxer_plugin_manager.h:71-79 - MediaStreamInfo（流信息）
struct MediaStreamInfo {
    int32_t streamID = -1;           // 流 ID
    bool activated = false;          // 是否激活
    uint64_t sniffSize;              // 嗅探大小
    uint32_t bitRate;               // 码率
    // ...
};

// demuxer_plugin_manager.h:84-88 - MediaTrackMap（Track 映射）
struct MediaTrackMap {
    int32_t trackID = -1;           // 轨道 ID
    int32_t streamID = -1;          // 流 ID
    int32_t innerTrackIndex = -1;   // 内部轨道索引
};
```

### 3.2 DemuxerPluginManager 核心接口（demuxer_plugin_manager.h:91-110）

```cpp
// demuxer_plugin_manager.h:97 - 获取插件
std::shared_ptr<Plugins::DemuxerPlugin> GetPluginByStreamID(int32_t streamID);

// demuxer_plugin_manager.h:98 - Track 信息查询
void GetTrackInfoByStreamID(int32_t streamID, int32_t& trackId, int32_t& innerTrackId);

// demuxer_plugin_manager.h:101 - 临时映射查询（TempMap）
int32_t GetTmpStreamIDByTrackID(int32_t trackId);
int32_t GetTmpInnerTrackIDByTrackID(int32_t trackId);
TrackType GetTmpTrackTypeByTrackID(int32_t trackId);

// demuxer_plugin_manager.h:104-106 - 临时映射更新
void UpdateTempTrackMapInfo(int32_t oldTrackId, int32_t newTrackId, int32_t newInnerTrackIndex);
void UpdateTempTrackMapByStreamId(int32_t oldTrackId, int32_t newStreamId, TrackType type);

// demuxer_plugin_manager.h:119 - 插件加载
Status LoadDemuxerPlugin(int32_t streamID, std::shared_ptr<BaseStreamDemuxer> streamDemuxer);
```

### 3.3 插件加载流程（demuxer_plugin_manager.cpp:1159）

```cpp
// demuxer_plugin_manager.cpp:119 - 插件加载入口
Status DemuxerPluginManager::LoadDemuxerPlugin(int32_t streamID, 
    std::shared_ptr<BaseStreamDemuxer> streamDemuxer)
{
    // 1. DataSourceImpl 适配 StreamDemuxer → Plugins::DataSource
    //    streamID → DataSourceImpl(streamID)
    // 2. PluginRegistry.Sniff(dataSource, probeData)
    //    → 返回评分最高的 DemuxerPlugin
    // 3. plugin->Init(source)
    // 4. 记录 plugin → streamID 映射
    // 5. 返回 Status::OK
}
```

## 四、BaseStreamDemuxer 核心设计

### 4.1 DemuxerState 枚举（base_stream_demuxer.h:40-45）

```cpp
// base_stream_demuxer.h:40-45 - 解封装状态机
enum class DemuxerState {
    IDLE = 0,
    INITIALIZED = 1,
    PREPARING = 2,
    READY = 3,
    // ...
};
```

### 4.2 CacheData 分片缓存（base_stream_demuxer.h:47-96）

```cpp
// base_stream_demuxer.h:47-96 - 分片缓存结构
class CacheData {
    uint64_t offset = 0;              // 缓存起始偏移
    uint64_t size = 0;                // 缓存大小
    std::shared_ptr<Buffer> buffer_;  // 缓存数据
    bool isValid_ = false;            // 缓存有效性
    int32_t streamId_ = -1;           // 所属流 ID

    bool CheckCacheExist(uint64_t len);   // 检查缓存是否存在
    uint64_t GetOffset();                  // 获取缓存偏移
    void SetData(const std::shared_ptr<Buffer>& buffer);  // 设置数据
    void Init(const std::shared_ptr<Buffer>& buffer, uint64_t bufferOffset);  // 初始化
};
```

### 4.3 BaseStreamDemuxer 核心接口（base_stream_demuxer.h:90-126）

```cpp
// base_stream_demuxer.h:90-126 - 流式解封装基类
class BaseStreamDemuxer {
    virtual Status ResetCache(int32_t streamID) = 0;  // 重置缓存
    void InitTypeFinder();  // 初始化类型探测
    void SetSource(const std::shared_ptr<Source>& source);  // 设置数据源
    virtual Status CallbackReadAt(int32_t streamID, int64_t offset, 
        std::shared_ptr<Buffer>& buffer, size_t expectedLen) = 0;  // 回调读取
    virtual void SetDemuxerState(int32_t streamId, DemuxerState state);  // 设置状态
    bool IsDash() const;  // 是否 DASH 流
    void SetIsDash(bool flag);  // 设置 DASH 标志
    Status SetNewAudioStreamID(int32_t streamID);  // 设置新音频流 ID
    Status SetNewVideoStreamID(int32_t streamID);  // 设置新视频流 ID
    Status SetNewSubtitleStreamID(int32_t streamID);  // 设置新字幕流 ID
    virtual int32_t GetNewVideoStreamID();  // 获取新视频流 ID
    virtual int32_t GetNewAudioStreamID();  // 获取新音频流 ID
    virtual int64_t GetFirstFrameDecapsulationTime() { return 0; }  // 首帧解封装时间
    bool CanDoChangeStream();  // 是否可以切换流
};
```

## 五、StreamID/TrackID 映射机制

```cpp
// DemuxerPluginManager 维护两套映射：
// 1. 正式映射 MediaTrackMap（streamID ↔ trackID ↔ innerTrackIndex）
// 2. 临时映射 TempTrackMap（oldTrackID → newTrackID/newInnerTrackIndex，用于流切换）

// 临时映射更新场景（demuxer_plugin_manager.cpp）：
// - SelectStreamId(int32_t streamId) → 切换轨道时
// - UpdateTempTrackMapInfo(oldTrackId, newTrackId, newInnerTrackIndex)
// - UpdateTempTrackMapByStreamId(oldTrackId, newStreamId, trackType)

// GetTmpStreamIDByTrackID：查询临时映射
// GetInnerTrackIDByTrackID：查询正式映射
// GetStreamTypeByTrackID：获取轨道类型（VIDEO/AUDIO/SUBTITLE）
```

## 六、与相关 S-series 记忆的关联

| 关联记忆 | 关系 | 说明 |
|---------|------|------|
| S75（MediaDemuxer 六组件） | 上游概述 | S75 是 MediaDemuxer 六组件概述，S144 补充 DemuxerPluginManager/BaseStreamDemuxer 源码 |
| S101（StreamDemuxer） | 下游实现 | BaseStreamDemuxer 的子类实现（StreamDemuxer VOD 流式读取） |
| S102（SampleQueueController） | 同级 | 并列同为 MediaDemuxer 子组件 |
| S128（HttpSourcePlugin 三路） | 并列 | StreamDemuxer 处理 DASH 分片，HttpSourcePlugin 处理 HTTP 分片 |
| S76（FFmpegDemuxerPlugin） | 下游插件 | DemuxerPluginManager Sniffer 路由后加载的插件 |

---

_builder-agent: S144 draft generated 2026-05-15T03:02:38+08:00, pending approval_