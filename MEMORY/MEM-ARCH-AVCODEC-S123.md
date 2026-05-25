# MEM-ARCH-AVCODEC-S123.md

## 文件头

- **ID**: MEM-ARCH-AVCODEC-S123
- **Type**: Architecture Memory
- **Status**: draft → pending_approval
- **Created_At**: 2026-05-25T13:05:00+08:00
- **Subject**: StreamDemuxer 流式解封装器——分片缓存读取与 PullData 三路分发机制
- **Tags**: AVCodec, MediaEngine, Demuxer, StreamDemuxer, BaseStreamDemuxer, DemuxerPluginManager, Cache, PullData, ReadRetry, DASH, HLS, AdaptiveBitrate

## 主题摘要

StreamDemuxer 是 MediaDemuxer 引擎的流式解封装组件，处理 HTTP/HTTPS/DASH/HLS 流媒体数据的拉取与缓存。三大核心机制：
1. **PullData 三路分发**：UNSEEKABLE 直接读 / SEEKABLE 先 Seek 再读 / CallbackReadAt 回调式读
2. **ReadRetry 重试**：10次 × 10ms = 最多 100ms 重试窗口，超时告警
3. **PullDataWithCache 缓存合并**：DASH 分片场景下多段数据合并读取

与 S75/S97/S101/S102 深度关联，是 MediaDemuxer 六组件架构中的流式读取引擎。

---

## Evidence（行号级）

### Evidence 1: stream_demuxer.h 类定义

**文件**: `services/media_engine/modules/demuxer/stream_demuxer.h` (492行)

**关键成员**:
```cpp
// 行40-48: 常量定义
const int32_t TRY_READ_SLEEP_TIME = 10;  // ms
const int32_t TRY_READ_TIMES = 10;
constexpr int64_t SOURCE_READ_WARNING_MS = 100;

// 行92-95: StreamDemuxer 类派生自 BaseStreamDemuxer
class StreamDemuxer : public BaseStreamDemuxer {
    explicit StreamDemuxer();
    ~StreamDemuxer() override;
    Status Init(const std::string& uri) override;
    Status Pause() override;
    Status Resume() override;
    Status Start() override;
    Status Stop() override;
    Status Flush() override;
    Status CallbackReadAt(...) override;  // 回调式读取（异步场景）
    Status ResetCache(int32_t streamID) override;
    Status ResetAllCache() override;
    int64_t GetFirstFrameDecapsulationTime() override;
private:
    Status PullData(...);                  // 核心拉取入口
    Status PullDataWithoutCache(...);       // 无缓存路径
    Status PullDataWithCache(...);          // 缓存合并路径
    Status GetPeekRange(...);               // 探测式读取
    Status ReadHeaderData(...);             // 头部读取
    Status ReadFrameData(...);              // 帧数据读取
    Status ReadRetry(...);                  // 重试逻辑
    Status HandleReadHeader(...);
    Status HandleReadPacket(...);
    Status CheckChangeStreamID(...);        // 码率切换检测
    Status ProcInnerDash(...);              // DASH 分片合并
    void SetInterruptState(bool isInterruptNeeded) override;
private:
    std::map<int32_t, CacheData> cacheDataMap_;  // 流ID → 缓存数据
    uint64_t position_;
    std::mutex mutex_;
    std::mutex cacheDataMutex_;
    std::condition_variable readCond_;
    int64_t firstFrameDecapsulationTime_ {0};
};
```

### Evidence 2: PullData 三路分发（行281-327）

**文件**: `services/media_engine/modules/demuxer/stream_demuxer.cpp`

```cpp
// 行281-327: PullData 三路分发逻辑
Status StreamDemuxer::PullData(int32_t streamID, uint64_t offset, size_t size,
    std::shared_ptr<Plugins::Buffer>& data, bool isSniffCase)
{
    Status err;
    // 路径1: UNSEEKABLE 流（直播/直播回放）直接读
    if (source_->IsSeekToTimeSupported() || source_->GetSeekable() == Plugins::Seekable::UNSEEKABLE) {
        err = ReadRetry(streamID, offset, readSize, data, isSniffCase);  // 行291
        return err;
    }
    // 路径2: SEEKABLE 流先 Seek 再读
    uint64_t totalSize = 0;
    // ... seek 操作 ...
    err = ReadRetry(streamID, offset, readSize, data, isSniffCase);  // 行319
    return err;
}
```

### Evidence 3: ReadRetry 重试机制（行245-278）

```cpp
// 行245-278: ReadRetry 重试逻辑（最多 TRY_READ_TIMES=10 次，每次间隔 10ms）
Status StreamDemuxer::ReadRetry(int32_t streamID, uint64_t offset, size_t size,
    std::shared_ptr<Plugins::Buffer>& data, bool isSniffCase)
{
    Status err = Status::OK;
    int32_t retryTimes = 0;
    do {
        err = getRange_(streamID, offset, size, data, isSniffCase);  // 行260 调用 getRange_ Lambda
        if (err == Status::OK) {
            return Status::OK;
        }
        retryTimes++;
        if (retryTimes >= TRY_READ_TIMES) {  // 行265: 最多重试10次
            MEDIA_LOG_E("ReadRetry failed after retry " PUBLIC_LOG_D32 " times", retryTimes);
            break;
        }
        MEDIA_LOG_W("ReadRetry failed, retry " PUBLIC_LOG_D32 " times", retryTimes);
        usleep(TRY_READ_SLEEP_TIME * 1000);  // 行269: 每次 sleep 10ms
    } while (true);
    // 行277: 中断检测
    FALSE_LOG_MSG(!isInterruptNeeded_.load(), "ReadRetry interrupted");
    return err;
}
```

### Evidence 4: PullDataWithCache 缓存合并算法（行133-180）

```cpp
// 行133-180: PullDataWithCache 缓存合并——DASH 分片场景核心算法
Status StreamDemuxer::PullDataWithCache(int32_t streamID, uint64_t offset, size_t size,
    std::shared_ptr<Buffer>& bufferPtr, bool isSniffCase)
{
    // 行139: 检查 cacheDataMap_ 中是否存在目标流 ID 的缓存
    uint64_t offsetInCache = offset - cacheDataMap_[streamID].GetOffset();
    // 行145-147: 计算缓存中剩余数据量和仍需读取的数据量
    uint64_t remainSize = size - (memory->GetSize() - offsetInCache);
    // 行150-151: 部分数据来自缓存，部分需要 PullData 补齐
    Status ret = PullData(streamID, remainOffset, remainSize, tempBuffer, isSniffCase);  // 行154
    // 行174-176: 记录日志
    MEDIA_LOG_I("PullDataWithCache, offset: " PUBLIC_LOG_U64 ", cache offset: " PUBLIC_LOG_U64, ...);
    return Status::OK;
}
```

### Evidence 5: ProcInnerDash DASH 分片合并（行181-205）

```cpp
// 行181-205: DASH 分片场景下的缓存合并
Status StreamDemuxer::ProcInnerDash(int32_t streamID, uint64_t offset,
    std::shared_ptr<Buffer>& bufferPtr)
{
    // 行185-188: 检查 cacheDataMap_ 是否已有该流 ID 缓存，如有则合并
    // 行196-201: DASH PullDataWithoutCache 合并前日志
    MEDIA_LOG_D("dash PullDataWithoutCache merge before: cache offset: " PUBLIC_LOG_U64, ...);
    MEDIA_LOG_D("dash PullDataWithoutCache merge after: " PUBLIC_LOG_U64 ", cache offset: " PUBLIC_LOG_U64, ...);
}
```

### Evidence 6: CallbackReadAt 回调式读取（行435-485）

```cpp
// 行435-485: CallbackReadAt 异步回调式读取
Status StreamDemuxer::CallbackReadAt(int32_t streamID, int64_t offset,
    std::shared_ptr<Buffer>& buffer, size_t expectedLen)
{
    // 行460-475: ReadAt 读取操作，带 condition_variable 等待 + 中断支持
    // source_ → Plugins::DataSource → IMediaDataSource 跨进程读取
    Status ret = getRange_(streamID, static_cast<uint64_t>(offset), expectedLen, buffer, false);
    return ret;
}
```

### Evidence 7: base_stream_demuxer.h DemuxerState 状态机（行40-46）

**文件**: `services/media_engine/modules/demuxer/base_stream_demuxer.h` (202行)

```cpp
// 行40-46: DemuxerState 三状态机
enum class DemuxerState {
    DEMUXER_STATE_NULL,           // 初始空状态
    DEMUXER_STATE_PARSE_HEADER,   // 解析容器头
    DEMUXER_STATE_PARSE_FIRST_FRAME,  // 解析首帧
    DEMUXER_STATE_PARSE_FRAME     // 解析普通帧
};

// 行47-83: CacheData 缓存结构体
class CacheData {
public:
    void Reset();
    bool CheckCacheExist(uint64_t len);  // 检查缓存是否覆盖目标范围
    uint64_t GetOffset();
    std::shared_ptr<Buffer> GetData();
    void SetData(const std::shared_ptr<Buffer>& buffer);
    void Init(const std::shared_ptr<Buffer>& buffer, uint64_t bufferOffset);
private:
    std::shared_ptr<Buffer> data = nullptr;
    uint64_t offset = 0;
};

// 行116: IsDash() 方法
bool IsDash() const;
void SetIsDash(bool flag);  // 设置是否为 DASH 直播流
```

### Evidence 8: base_stream_demuxer.h BaseStreamDemuxer 核心接口（行90-154）

```cpp
// 行90-154: BaseStreamDemuxer 基类（抽象）
class BaseStreamDemuxer {
public:
    virtual Status Init(const std::string& uri) = 0;
    virtual Status Pause() = 0;
    virtual Status Resume() = 0;
    virtual Status Start() = 0;
    virtual Status Stop() = 0;
    virtual Status Flush() = 0;
    virtual Status CallbackReadAt(...) = 0;
    void InitTypeFinder();                          // 初始化类型探测
    void SetSource(const std::shared_ptr<Source>& source);
    Plugins::Seekable GetSeekable();               // 获取可seek性
    virtual void SetInterruptState(bool isInterruptNeeded);
    virtual std::string SnifferMediaType(const StreamInfo& streamInfo);  // 类型探测
    bool IsDash() const;                           // 是否DASH流
    void SetIsDash(bool flag);
    Status SetNewAudioStreamID(int32_t streamID);
    Status SetNewVideoStreamID(int32_t streamID);
    Status SetNewSubtitleStreamID(int32_t streamID);
    virtual int32_t GetNewVideoStreamID();
    virtual int32_t GetNewAudioStreamID();
    virtual int32_t GetNewSubtitleStreamID();
    bool CanDoChangeStream();                      // 码率切换前提检查
    void SetChangeFlag(bool flag);
    virtual bool SetSourceInitialBufferSize(int32_t offset, int32_t size);
    void SetSourceType(SourceType type);
protected:
    std::shared_ptr<Source> source_;               // 数据源
    std::shared_ptr<TypeFinder> typeFinder_;
    // Lambda 函数：范围读取回调
    std::function<Status(int32_t, uint64_t, size_t)> checkRange_;
    std::function<Status(int32_t, uint64_t, size_t, std::shared_ptr<Buffer>&, bool)> peekRange_;
    std::function<Status(int32_t, uint64_t, size_t, std::shared_ptr<Buffer>&, bool)> getRange_;  // 关键：实际拉取回调
    std::map<int32_t, DemuxerState> pluginStateMap_;  // 流ID → 解析状态
    std::atomic<bool> isIgnoreParse_{false};
    std::atomic<bool> isInterruptNeeded_{false};
    bool isDash_ = {false};
    std::atomic<int32_t> newVideoStreamID_ = -1;
    std::atomic<int32_t> newAudioStreamID_ = -1;
    std::atomic<int32_t> newSubtitleStreamID_ = -1;
    std::atomic<bool> changeStreamFlag_ = true;  // 码率切换标志
};
```

### Evidence 9: demuxer_plugin_manager.h DataSourceImpl 内类（行55-107）

**文件**: `services/media_engine/modules/demuxer/demuxer_plugin_manager.h` (196行)

```cpp
// 行55-107: DataSourceImpl 内类——StreamDemuxer ↔ DemuxerPlugin 之间的桥接
class DataSourceImpl : public Plugins::DataSource {
public:
    explicit DataSourceImpl(const std::shared_ptr<BaseStreamDemuxer>& stream, int32_t streamID);
    // 行82-97: ReadAt——调用 StreamDemuxer::CallbackReadAt 实现跨层读取
    Status ReadAt(int64_t offset, std::shared_ptr<Buffer>& buffer, size_t expectedLen) override {
        MediaAVCodec::AVCodecTrace trace("DataSourceImpl::ReadAt");  // 行84: TRACE 埋点
        return stream_->CallbackReadAt(streamID_, offset, buffer, expectedLen);  // 行89
    }
    Status GetSize(uint64_t& size) override;
    Plugins::Seekable GetSeekable() override;
    Status SetStreamID(int32_t streamID);
    int32_t GetStreamID() override;
    bool IsDash() override;
    void SetIsDash(bool flag);
private:
    std::shared_ptr<BaseStreamDemuxer> stream_;  // 持有 StreamDemuxer 引用
    int32_t streamID_;
    bool isDash_ = false;
    std::mutex readMutex_;
};
```

### Evidence 10: demuxer_plugin_manager.h MediaStreamInfo / MediaTrackMap 三层映射表（行112-142）

```cpp
// 行112-142: MediaStreamInfo 流信息结构体
class MediaStreamInfo {
public:
    int32_t streamID = -1;                    // 流ID
    bool activated = false;                   // 是否激活
    StreamType type;                          // 音/视频/字幕
    uint64_t sniffSize;                       // 探测数据大小
    uint32_t bitRate;                         // 码率
    std::string pluginName = "";              // 插件名称
    std::shared_ptr<Plugins::DemuxerPlugin> plugin = nullptr;  // 具体解封装插件
    std::shared_ptr<DataSourceImpl> dataSource = nullptr;        // 数据源桥接
    Plugins::MediaInfo mediaInfo;            // 媒体信息
};

// 行144-151: MediaTrackMap 三层映射表
class MediaTrackMap {
public:
    int32_t trackID = -1;         // 外层轨道ID（暴露给调用方）
    int32_t streamID = -1;        // 流ID（StreamDemuxer 级别）
    int32_t innerTrackIndex = -1; // 内部轨道索引（插件内部）
};

// 行156-181: streamInfoMap_ 管理所有流信息（<streamId, MediaStreamInfo>）
std::map<int32_t, MediaStreamInfo> streamInfoMap_;
// 行182-184: trackInfoMap_ 保存所有轨道映射（<trackId, MediaTrackMap>）
std::map<int32_t, MediaTrackMap> trackInfoMap_;
// 行185-186: temp2TrackInfoMap_ 正在播放的轨道临时映射
std::map<int32_t, MediaTrackMap> temp2TrackInfoMap_;
// 行188-190: 当前选中的流ID
int32_t curVideoStreamID_ = -1;
int32_t curAudioStreamID_ = -1;
int32_t curSubTitleStreamID_ = -1;
```

### Evidence 11: demuxer_plugin_manager.cpp LoadDemuxerPlugin Sniffer 探测（行306-338）

**文件**: `services/media_engine/modules/demuxer/demuxer_plugin_manager.cpp` (1159行)

```cpp
// 行306-338: LoadDemuxerPlugin——类型探测 + 插件加载
Status DemuxerPluginManager::LoadDemuxerPlugin(int32_t streamID,
    std::shared_ptr<BaseStreamDemuxer> streamDemuxer)
{
    // 行317-318: 构造 StreamInfo 用于 Sniffer
    streamInfo.type = streamInfoMap_[streamID].type;
    streamInfo.sniffSize = streamInfoMap_[streamID].sniffSize;
    ScopedTimer timer("SnifferMediaType", SNIFF_WARNING_MS);  // 行319: 计时器，超时 200ms
    type = streamDemuxer->SnifferMediaType(streamInfo);      // 行320: 实际探测
    // 行326-329: 获取插件
    FALSE_RETURN_V_MSG(!type.empty(), Status::ERROR_INVALID_PARAMETER, "SnifferMediaType is failed.");
    FALSE_RETURN_V_MSG_E(streamInfoMap_[streamID].plugin != nullptr, Status::ERROR_INVALID_PARAMETER, ...);
    Status ret = streamInfoMap_[streamID].plugin->GetMediaInfo(mediaInfoTemp);  // 行332
    // 行334-337: 填充 mediaInfo
    streamInfoMap_[streamID].mediaInfo = mediaInfoTemp;
}

// 行43-48: 常量
constexpr int32_t INVALID_STREAM_OR_TRACK_ID = -1;
constexpr int32_t API_VERSION_16 = 16;
constexpr int32_t API_VERSION_18 = 18;
constexpr int64_t SNIFF_WARNING_MS = 200;  // Sniffer 超时阈值 200ms
```

### Evidence 12: demuxer_plugin_manager.cpp GetPluginByStreamID 插件获取（行271-278）

```cpp
// 行271-278: GetPluginByStreamID——通过流ID获取对应解封装插件
std::shared_ptr<Plugins::DemuxerPlugin> DemuxerPluginManager::GetPluginByStreamID(int32_t streamID)
{
    if (streamID != INVALID_STREAM_OR_TRACK_ID && streamInfoMap_.find(streamID) != streamInfoMap_.end()) {
        return streamInfoMap_[streamID].plugin;  // 行273: 返回对应流的插件实例
    }
    return nullptr;
}
```

### Evidence 13: demuxer_plugin_manager.cpp 三层 Track 映射查询（行279-300）

```cpp
// 行279-300: GetTrackInfoByStreamID——StreamID → TrackID + InnerTrackIndex
void DemuxerPluginManager::GetTrackInfoByStreamID(int32_t streamID,
    int32_t& trackId, int32_t& innerTrackId)
{
    // 行281-284: 通过 find_if 遍历 trackInfoMap_ 匹配 streamID
    [&](const std::pair<int32_t, MediaTrackMap> &item) {
        return item.second.streamID == streamID;
    };
}

// 行292-300: GetTrackInfoByStreamID 重载版本（含 TrackType 过滤）
void DemuxerPluginManager::GetTrackInfoByStreamID(int32_t streamID,
    int32_t& trackId, int32_t& innerTrackId, TrackType type);
```

### Evidence 14: demuxer_plugin_manager.cpp LoadCurrentAllPlugin 全量插件加载（行339-360）

```cpp
// 行339-360: LoadCurrentAllPlugin——加载所有流的插件
Status DemuxerPluginManager::LoadCurrentAllPlugin(
    std::shared_ptr<BaseStreamDemuxer> streamDemuxer, MediaInfo& mediaInfo)
{
    // 行342-346: 音频插件
    if (curAudioStreamID_ != INVALID_STREAM_OR_TRACK_ID) {
        Status ret = LoadDemuxerPlugin(curAudioStreamID_, streamDemuxer);
    }
    // 行347-351: 视频插件
    if (curVideoStreamID_ != INVALID_STREAM_OR_TRACK_ID) {
        Status ret = LoadDemuxerPlugin(curVideoStreamID_, streamDemuxer);
    }
    // 行352-357: 字幕插件
    if (curSubTitleStreamID_ != INVALID_STREAM_OR_TRACK_ID) {
        Status ret = LoadDemuxerPlugin(curSubTitleStreamID_, streamDemuxer);
    }
    // 行358-359: 处理混合流（MIXED 类型）
    for (auto& iter : streamInfoMap_) { ... }
}
```

---

## Cross-References（关联记忆）

- **S75**: MediaDemuxer 六组件架构（MediaDemuxer 是 StreamDemuxer 的调用方父组件）
- **S97**: DemuxerPluginManager 插件路由（StreamDemuxer ↔ DemuxerPluginManager 的 DataSourceImpl 桥接关系）
- **S101**: StreamDemuxer 分片缓存（与 S123 主题完全相同，为正式注册版）
- **S102**: SampleQueueController 流控（水位线启停依赖 StreamDemuxer 的 PullData 速度）
- **S69**: MediaDemuxer 核心引擎（StreamDemuxer 是 ReadLoop 的核心执行组件）
- **S141**: PTS 索引转换（PtsToFrameIndex 依赖 StreamDemuxer 的 PullData 读取）
- **S172**: HttpSourcePlugin 三路下载器（HttpSourcePlugin 是 PullData 的数据来源上游）

---

## 架构位置

```
MediaDemuxer (主引擎)
  └── ReadLoop TaskThread
        └── StreamDemuxer（流式读取引擎）
              ├── PullData 三路分发
              │     ├── UNSEEKABLE → ReadRetry 直接读
              │     ├── SEEKABLE → Seek + ReadRetry
              │     └── CallbackReadAt（异步回调）
              ├── PullDataWithCache（缓存合并）
              ├── ReadRetry（10次×10ms 重试）
              └── ProcInnerDash（DASH分片合并）
                    │
                    └── DemuxerPluginManager
                          ├── DataSourceImpl（桥接器）
                          ├── streamInfoMap_<streamId, MediaStreamInfo>
                          ├── trackInfoMap_<trackId, MediaTrackMap>
                          ├── temp2TrackInfoMap_（临时轨道映射）
                          ├── LoadDemuxerPlugin（Sniffer探测 200ms）
                          └── GetPluginByStreamID（插件查找）
```

---

## 关键常量速查

| 常量 | 值 | 说明 |
|------|-----|------|
| TRY_READ_TIMES | 10 | 最大重试次数 |
| TRY_READ_SLEEP_TIME | 10ms | 每次重试间隔 |
| SOURCE_READ_WARNING_MS | 100ms | 读取超时告警阈值 |
| SNIFF_WARNING_MS | 200ms | 类型探测超时阈值 |
| DEMUXER_STATE_NULL | - | 初始空状态 |
| DEMUXER_STATE_PARSE_HEADER | - | 解析容器头 |
| DEMUXER_STATE_PARSE_FIRST_FRAME | - | 解析首帧 |
| DEMUXER_STATE_PARSE_FRAME | - | 解析普通帧 |
