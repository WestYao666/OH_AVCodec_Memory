---
mem_id: MEM-ARCH-AVCODEC-S75
status: approved
approved_at: "2026-05-06"
submitted_by: builder-agent
submitted_at: "2026-05-03T07:05:00+08:00"
---

# S75：MediaDemuxer 核心解封装引擎——六组件协作架构

## 主题

MediaDemuxer 核心解封装引擎——MediaDemuxer + DemuxerPluginManager + StreamDemuxer + SampleQueue + SampleQueueController + TypeFinder 六组件协作

## 分类

AVCodec, Demuxer, MediaDemuxer, StreamDemuxer, SampleQueue, Plugin, Pipeline

## 描述

### 架构总览

MediaDemuxer 是 OpenHarmony AVCodec 模块的**解封装核心引擎**，负责将容器格式（MP4/MKV/FLV 等）中的压缩音视频流分离出来，输出给下游 Filter（AudioDecoderFilter / VideoDecoderFilter）。

其内部由六个核心组件构成：

| 组件 | 文件 | 行数 | 职责 |
|------|------|------|------|
| **MediaDemuxer** | `media_demuxer.cpp` | 6012 | 解封装主引擎，持有所有子组件，协调 ReadLoop |
| **DemuxerPluginManager** | `demuxer_plugin_manager.cpp` | 1159 | 插件加载、Sniffer 路由、Demuxer 生命周期 |
| **StreamDemuxer** | `stream_demuxer.cpp` | 492 | 流式数据读取，分片缓存，支持 DASH/直播流 |
| **BaseStreamDemuxer** | `base_stream_demuxer.cpp` | 202 | Source 绑定、媒体类型嗅探基类 |
| **SampleQueue** | `sample_queue.cpp` | 773 | AVBufferQueue 封装，队列状态管理 |
| **SampleQueueController** | `sample_queue_controller.cpp` | 300 | 流控：双水位线（START@5s/STOP@10s），消费起停决策 |
| **TypeFinder** | `type_finder.cpp` | 226 | 媒体类型探测，Sniffer 路由 |

**六组件调用关系**：

```
DataSource (File/HTTP/...)
        │
        ▼
BaseStreamDemuxer ──SetSource()──► Source
        │
        ▼
StreamDemuxer ──PullData/CacheData──► 读取/缓存分片数据
        │
        ▼
DemuxerPluginManager ──DemuxerPlugin──► 插件执行解封装
        │
        ├─ ReadLoop (TaskThread) ──► MediaDemuxer 主导读循环
        │         │
        │         ▼
        │   SampleQueue ──AVBufferQueue──► 下游 Filter (Audio/Video Decoder)
        │         ▲
        │         │
        │   SampleQueueController ──消费起停决策（水位线控制）
        │
        └─ TypeFinder ──Sniffer路由──► 插件选择
```

### MediaDemuxer 主引擎（6012行）

**职责**：解封装主控制器，协调 ReadLoop、Seek、Track 管理。

**关键文件**：
- `modules/demuxer/media_demuxer.cpp` — 6012行主引擎
- `modules/demuxer/media_demuxer.h` — 619行头文件

**核心数据结构**：

```cpp
class MediaDemuxer : public std::enable_shared_from_this<MediaDemuxer>,
                     public Plugins::Callback,
                     public InterruptListener,
                     public SampleQueueCallback {
    // Source 绑定
    std::shared_ptr<BaseStreamDemuxer> baseStreamDemuxer_;
    
    // 插件管理层
    std::shared_ptr<DemuxerPluginManager> demuxerPluginManager_;
    
    // 流式读取器
    std::shared_ptr<StreamDemuxer> streamDemuxer_;
    
    // 轨道管理
    std::vector<TrackInfo> tracks_;  // VIDEO/AUDIO/SUBTITLE
    
    // Sample 队列（每轨道一个）
    std::map<int32_t, std::shared_ptr<SampleQueue>> sampleQueues_;
    std::map<int32_t, std::shared_ptr<SampleQueueController>> queueControllers_;
    
    // 读循环线程
    std::unique_ptr<Task> readLoopTask_;   // ReadLoop 主导读循环
    std::unique_ptr<Task> consumeTask_;     // SampleConsumerLoop 消费驱动
};
```

**ReadLoop 双 TaskThread 机制**：

1. **ReadLoop**（主读线程）：
   - 调用 `demuxerPluginManager_->ReadSample()` 获取压缩帧
   - 写入对应轨的 `SampleQueue`
   - 触发 `SampleQueueController` 水位线检查

2. **SampleConsumerLoop**（消费线程）：
   - 等待 `SampleQueue` 有数据
   - 驱动 `SampleQueueController` 流控决策
   - 通过 `AVBufferQueue` 推送给下游 Filter

### DemuxerPluginManager 插件管理层（1159行）

**职责**：解封装插件的加载、路由、生命周期管理。

**关键文件**：
- `modules/demuxer/demuxer_plugin_manager.cpp` — 1159行
- `modules/demuxer/demuxer_plugin_manager.h` — 196行

**插件路由机制**：

```cpp
// 1. TypeFinder Sniffer 探测媒体类型
std::string DemuxerPluginManager::SnifferMediaType(const StreamInfo& streamInfo)
{
    // 调用 PluginManagerV2::SnifferPlugin(PluginType::DEMUXER)
    // 遍历所有 DemuxerPlugin，执行 Sniffer 函数匹配
}

// 2. 按类型选择插件
Status DemuxerPluginManager::CreateDemuxerPlugin(const std::string& mime)
{
    auto plugin = Plugins::PluginManagerV2::GetInstance()
        ->CreatePluginWithMime(PluginType::DEMUXER, mime);
}

// 3. 按 Track 轨道类型选择插件
Status DemuxerPluginManager::CreateTrackDemuxerPlugin(TrackInfo& trackInfo)
```

**支持的 Demuxer 插件**：
- `FFmpegDemuxerPlugin` — 基于 FFmpeg libavformat，支持 25+ 容器格式
- `MPEG4DemuxerPlugin` — 原生 MP4 box 解析（avcC/hvcC/vvcC codec config）

### StreamDemuxer 流式读取器（492行）

**职责**：处理流式数据源（DASH/HLS/HTTP 直播流），提供分片缓存和随机读取。

**关键文件**：
- `modules/demuxer/stream_demuxer.cpp` — 492行
- `modules/demuxer/stream_demuxer.h` — 87行

**DASH/流媒体特殊处理**：

```cpp
Status StreamDemuxer::ReadFrameData(int32_t streamID, uint64_t offset, size_t size,
    std::shared_ptr<Buffer>& bufferPtr, bool isSniffCase)
{
    std::unique_lock<std::mutex> lock(cacheDataMutex_);
    if (IsDash() || GetIsDataSrcNoSeek()) {
        // DASH/直播流：优先从分片缓存读取
        if (cacheDataMap_[streamID].CheckCacheExist(offset)) {
            return PullDataWithCache(streamID, offset, size, bufferPtr, isSniffCase);
        }
    }
    return PullData(streamID, offset, size, bufferPtr, isSniffCase);
}
```

**分片缓存管理**：
- `cacheDataMap_` — 每轨一个环形缓存
- `PullData()` — 从 Source 读取新分片
- `PullDataWithCache()` — 从缓存读取（命中缓存）

### BaseStreamDemuxer 基类（202行）

**职责**：Source 绑定、媒体类型嗅探基类实现。

**关键方法**：

```cpp
void BaseStreamDemuxer::SetSource(const std::shared_ptr<Source>& source)
{
    source_ = source;
    source_->GetSize(mediaDataSize_);
    seekable_ = source_->GetSeekable();
}

std::string BaseStreamDemuxer::SnifferMediaType(const StreamInfo& streamInfo)
{
    // 调用 TypeFinder 探测媒体类型
}
```

### SampleQueue 缓冲队列（773行）

**职责**：封装 `AVBufferQueue`，管理样本的入队/出队/状态。

**关键文件**：
- `modules/demuxer/sample_queue.cpp` — 773行
- `modules/demuxer/sample_queue.h` — 157行

**双 Listener 机制**：

```cpp
class SampleBufferConsumerListener : public IConsumerListener {
    void OnBufferAvailable() override { sampleQueue_->OnBufferConsumer(); }
};

class SampleBufferProducerListener : public IRemoteStub<IProducerListener> {
    void OnBufferAvailable() override { /* 通知生产者 */ }
};
```

**队列状态标志**（`SampleBufferState`）：
- `WAIT` — 等待数据填充
- `AVAILABLE` — 数据就绪，可消费
- `IN_USE` — 正在被消费

### SampleQueueController 流控（300行）

**职责**：基于双水位线（START/STOP）的消费起停决策，防止缓冲区膨胀或枯竭。

**关键参数**：

| 参数 | 值 | 说明 |
|------|-----|------|
| FIRST_START_CONSUME_WATER_LOOP | 5s | 首次开始消费的水位线 |
| PLAY_BUFFERING_DURATION | 10s | 停止继续填充的水位线 |
| QUEUE_SIZE_MIN | 自适应 | 最小队列深度 |
| MAX_SAMPLE_IDLE_TIME_MS | 100ms | 最大空闲时间 |

**判断逻辑**：

```cpp
bool SampleQueueController::ShouldStartConsume(int32_t trackId, 
    std::shared_ptr<SampleQueue> sampleQueue, const std::unique_ptr<Task> &task, bool inPreroll)
{
    uint64_t cacheDuration = sampleQueue->NewGetCacheDuration();
    if (cacheDuration < GetPlayBufferingDuration() &&    // < 10s
        sampleQueue->GetFilledBufferSize() < DEFAULT_SAMPLE_QUEUE_SIZE - 1 &&
        (isFirstArrived_[trackId] || cacheDuration < FIRST_START_CONSUME_WATER_LOOP) && // < 5s
        !inPreroll) {
        return false;  // 数据不足，不开始消费
    }
    // 达到水位线，启动消费
    task->Start();
    isFirstArrived_[trackId] = true;
}
```

### TypeFinder 媒体类型探测（226行）

**职责**：通过 Sniffer 插件遍历匹配，确定媒体类型。

**关键文件**：
- `modules/demuxer/type_finder.cpp` — 226行
- `modules/demuxer/type_finder.h` — 84行

```cpp
std::string TypeFinder::FindMediaType(std::shared_ptr<Buffer>& buffer)
{
    // 调用 PluginManagerV2::SnifferPlugin()
    // 遍历所有 Demuxer 插件的 Sniffer 函数
    // 返回匹配的 MIME 类型
}
```

### 与 Filter 层对接

```
MediaDemuxer (ReadLoop → SampleQueue → AVBufferQueue)
        │
        ▼
DemuxerFilter (Filter 层) ──AVBufferQueue──►
    ├─ AudioDecoderFilter
    ├─ VideoDecoderFilter
    └─ SubtitleSinkFilter
```

### Evidence 来源

| 文件 | 行数 | 说明 |
|------|------|------|
| `modules/demuxer/media_demuxer.cpp` | 6012 | 解封装主引擎，ReadLoop 双线程 |
| `modules/demuxer/demuxer_plugin_manager.cpp` | 1159 | 插件加载、Sniffer 路由 |
| `modules/demuxer/stream_demuxer.cpp` | 492 | 流式读取、分片缓存、DASH支持 |
| `modules/demuxer/base_stream_demuxer.cpp` | 202 | Source 绑定、嗅探基类 |
| `modules/demuxer/sample_queue.cpp` | 773 | AVBufferQueue 封装 |
| `modules/demuxer/sample_queue_controller.cpp` | 300 | 双水位线流控 |
| `modules/demuxer/type_finder.cpp` | 226 | 媒体类型探测 |
| `services/media_engine/filters/demuxer_filter.cpp` | — | Filter 层入口 |

## 关联主题

| 关联 | 说明 |
|------|------|
| S41 | DemuxerFilter — Filter 层封装（上游） |
| S66 | TypeFinder — 媒体类型探测框架 |
| S68 | FFmpegDemuxerPlugin — FFmpeg 解封装插件 |
| S58 | MPEG4DemuxerPlugin — MP4 box 解析插件 |
| S69 | SampleQueue 缓冲队列 — MediaDemuxer 内部的队列管理 |
| S39/S45/S46 | VideoDecoderFilter — 下游消费者 |

## 标签

- AVCodec
- Demuxer
- MediaDemuxer
- StreamDemuxer
- SampleQueue
- SampleQueueController
- TypeFinder
- DemuxerPluginManager
- ReadLoop
- FlowControl