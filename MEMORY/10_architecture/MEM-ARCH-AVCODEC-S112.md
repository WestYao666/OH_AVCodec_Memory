---
id: MEM-ARCH-AVCODEC-S112
title: "Pipeline Controller 整体架构——FilterGraph / Port / TaskDispatch 三者联动"
scope: [AVCodec, MediaEngine, Filter, FilterGraph, Port, AVBufferQueue, TaskDispatch, TaskThread, LinkNext, OnLinked, Pipeline, MediaSyncManager, DoProcessInputBuffer]
status: approved
approved_at: "2026-05-09T21:02:00+08:00"
created_by: builder-agent
created_at: "2026-05-09T16:50:00+08:00"
evidence_count: 16
---

# MEM-ARCH-AVCODEC-S112: Pipeline Controller 整体架构

## Metadata

| 字段 | 值 |
|------|-----|
| id | MEM-ARCH-AVCODEC-S112 |
| title | Pipeline Controller 整体架构——FilterGraph / Port / TaskDispatch 三者联动 |
| type | architecture_fact |
| scope | [AVCodec, MediaEngine, Filter, FilterGraph, Port, AVBufferQueue, TaskDispatch, TaskThread, LinkNext, OnLinked, Pipeline, MediaSyncManager] |
| status | draft |
| created_by | builder-agent |
| created_at | 2026-05-09 |
| confidence | high |
| related_scenes | [新需求开发, 问题定位, Pipeline 扩展, 自定义 Filter 接入, Filter 链路调试] |
| supersedes | S14（Filter Chain 三联机制）, S89（Filter Framework 基础架构）|
| why_it_matters: |
  - 新需求开发：接入新 Filter 需理解 FilterGraph 拓扑、Port 绑定、TaskThread 驱动三者如何协同
  - 问题定位：数据流断点需区分是 Port 未正确绑定、TaskThread 未启动、还是 FilterGraph 链接失败
  - Pipeline 扩展：动态 Pipeline（多轨/多路/切换）依赖三者联动机制

## 摘要

Pipeline Controller 是 AVCodec MediaEngine 侧媒体处理 Pipeline 的**整体协调机制**，由三个子系统联动构成：

1. **FilterGraph（Filter 图）**：以 `DemuxerFilter` 为根的 Filter 单向链表，通过 `LinkNext` / `OnLinked` 握手协议串联各 Filter 节点
2. **Port（AVBufferQueue 端口）**：每对相邻 Filter 通过 `AVBufferQueueProducer`（下游输入）与 `AVBufferQueueConsumer`（上游输出）端口绑定，数据不过拷贝
3. **TaskDispatch（任务分发）**：各 Filter 自带 TaskThread 工作循环（`RenderLoop` / `ReadLoop` / `DoProcessInputBuffer`），由 Filter 自身驱动；MediaDemuxer 使用统一 `Task` 抽象调度 ReadLoop/SampleConsumerLoop

三者联动流程：`FilterGraph::LinkNext` 建立拓扑 → `OnLinkedResult` 返回 `AVBufferQueueProducer` 端口 → Filter 启动 `TaskThread` 工作循环消费/生产数据。

## 一、FilterGraph（Filter 图拓扑）

### 1.1 LinkNext 单向串联协议（证据：demuxer_filter.cpp:775-820）

```cpp
// DemuxerFilter::LinkNext（demuxer_filter.cpp:775-820）
Status DemuxerFilter::LinkNext(const std::shared_ptr<Filter> &nextFilter, StreamType outType)
{
    int32_t trackId = -1;
    FALSE_RETURN_V_MSG_E(nextFilter != nullptr, ...);
    FALSE_RETURN_V_MSG_E(demuxer_ != nullptr, ...);
    FALSE_RETURN_V_MSG_E(FindTrackId(outType, trackId), ...);
    
    std::shared_ptr<Meta> meta = trackInfos[trackId];  // 携带轨道元数据
    nextFilter_ = nextFilter;
    nextFiltersMap_[outType].push_back(nextFilter_);
    
    // 创建握手回调：下游通过此回调返回自己的输入端口
    std::shared_ptr<FilterLinkCallback> filterLinkCallback
        = std::make_shared<DemuxerFilterLinkCallback>(shared_from_this());
    return nextFilter->OnLinked(outType, meta, filterLinkCallback);  // 调用下游 OnLinked
}
```

### 1.2 OnLinked 握手与端口返回（证据：surface_decoder_filter.cpp:351-414）

```cpp
// surface_decoder_filter.cpp:351-353 —— 上游调用下游 OnLinked
nextFilter_->OnLinked(outType, configureParameter_, filterLinkCallback);

// surface_decoder_filter.cpp:407-414 —— 下游通过回调返回 Producer 端口
void SurfaceDecoderFilter::OnLinkedResult(const sptr<AVBufferQueueProducer> &outputBufferQueue,
    std::shared_ptr<Meta> &meta)
{
    onLinkedResultCallback_->OnLinkedResult(mediaCodec_->GetInputBufferQueue(), meta_);
    // mediaCodec_->GetInputBufferQueue() 返回 AVBufferQueueProducer（Decoder 的输入队列）
}
```

### 1.3 Filter 链表拓扑（证据：demuxer_filter.h:175-178）

```cpp
// demuxer_filter.h:175-178 — 多轨支持：每个 StreamType 可有多个下游 Filter
std::shared_ptr<Filter> nextFilter_;  // 主下游（单轨）
std::map<StreamType, std::vector<std::shared_ptr<Filter>>> nextFiltersMap_;  // 多轨 Map

// demuxer_filter.h:168 — 多轨 track_id 路由
std::map<StreamType, std::vector<int32_t>> track_id_map_;  // StreamType → [trackId列表]
```

典型播放 Pipeline 拓扑：
```
DemuxerFilter ("builtin.player.demuxer")
    ├─ video track → AVBufferQueue → SurfaceDecoderFilter ("builtin.player.surfacedecoder")
    │                                 └─ AVBufferQueue → VideoSink / Surface
    ├─ audio track → AVBufferQueue → AudioDecoderFilter ("builtin.player.audiodecoder")
    │                                 └─ AVBufferQueue → AudioSinkFilter ("builtin.player.audiosink")
    └─ subtitle track → AVBufferQueue → SubtitleSinkFilter ("builtin.player.subtitlesink")
```

## 二、Port（AVBufferQueue 端口机制）

### 2.1 Producer/Consumer 端口对（证据：demuxer_filter.h:169）

```cpp
// demuxer_filter.h:169 — 多轨输出端口映射
std::map<int32_t, sptr<AVBufferQueueProducer>> GetBufferQueueProducerMap();
```

### 2.2 MuxerFilter 多输入端口（证据：muxer_filter.cpp:54-84）

```cpp
// muxer_filter.cpp:54-84 — 每个 track 有独立的输入端口（BrokerListener）
class MuxerBrokerListener : public IBrokerListener {
public:
    MuFilter(std::shared_ptr<MuxerFilter> muxerFilter, int32_t trackIndex,
        StreamType streamType, sptr<AVBufferQueueProducer> inputBufferQueue)
        : muxerFilter_(...), trackIndex_(trackIndex), streamType_(streamType),
          inputBufferQueue_(inputBufferQueue) {}
    
    void OnBufferFilled(std::shared_ptr<AVBuffer> &avBuffer) override {
        muxerFilter_->OnBufferFilled(avBuffer, trackIndex_, streamType_, inputBufferQueue_.promote());
    }
private:
    std::weak_ptr<MuxerFilter> muxerFilter_;
    int32_t trackIndex_;
    StreamType streamType_;
    wptr<AVBufferQueueProducer> inputBufferQueue_;  // 每个 track 的独立端口
};

// muxer_filter.cpp:294 — 按 trackIndex 获取对应端口
sptr<AVBufferQueueProducer> inputBufferQueue = mediaMuxer_->GetInputBufferQueue(trackIndex);
```

### 2.3 Port 握手流程（证据：surface_decoder_filter.cpp:38-75, 407-414）

```cpp
// surface_decoder_filter.cpp:38-75 — 下游 Filter 创建 LinkCallback
class SurfaceDecoderFilterLinkCallback : public FilterLinkCallback {
public:
    void OnLinkedResult(const sptr<AVBufferQueueProducer> &queue, std::shared_ptr<Meta> &meta) override {
        decoderSurfaceFilter_->OnLinkedResult(queue, meta);  // 转发给 Filter
    }
    void OnUpdatedResult(std::shared_ptr<Meta> &meta) override { ... }
    void OnUnlinkedResult(std::shared_ptr<Meta> &meta) override { ... }
private:
    std::weak_ptr<DecoderSurfaceFilter> decoderSurfaceFilter_;
};

// surface_decoder_adapter.h:57,81-82 — CodecAdapter 层也有 Producer/Consumer 端口
sptr<OHOS::Media::AVBufferQueueProducer> GetInputBufferQueue();
sptr<Media::AVBufferQueueProducer> inputBufferQueueProducer_;
sptr<Media::AVBufferQueueConsumer> inputBufferQueueConsumer_;
```

## 三、TaskDispatch（任务分发驱动）

### 3.1 RenderLoop 任务线程（证据：decoder_surface_filter.cpp:529-530, 1283-1302）

```cpp
// decoder_surface_filter.cpp:529-530 — 启动 RenderLoop 线程
readThread_ = std::make_unique<std::thread>(&DecoderSurfaceFilter::RenderLoop, this);
pthread_setname_np(readThread_->native_handle(), "RenderLoop");

// decoder_surface_filter.cpp:1283-1302 — RenderLoop 实现
void DecoderSurfaceFilter::RenderLoop()
{
    MEDIA_LOG_D("RenderLoop pts: " PUBLIC_LOG_D64 "  waitTime:" PUBLIC_LOG_D64, pts, waitTime);
    // 等待上一帧渲染完成 → CheckBufferLatenessMayWait → DoSyncWrite
    // 处理 EOS / 丢帧 / 正常渲染
}
```

### 3.2 ReadLoop 任务线程（证据：audio_capture_filter.cpp:383-386）

```cpp
// audio_capture_filter.cpp:383-386 — 采集 Filter 的 ReadLoop
void AudioCaptureFilter::ReadLoop()
{
    MEDIA_LOG_D("ReadLoop");
    MediaAVCodec::AVCodecTrace trace("AudioCaptureFilter::ReadLoop");
    // 从设备读取音频数据 → PushBuffer 到下游 Port
}
```

### 3.3 Task 统一抽象调度（证据：media_demuxer.cpp:861-941）

```cpp
// media_demuxer.cpp:861 — 创建 Task 对象（Demuxer 主任务）
std::unique_ptr<Task> task = std::make_unique<Task>(taskName, playerId_, type);

// media_demuxer.cpp:909-916 — ReadLoop Task（读取输入流）
auto task = std::make_unique<Task>(taskName, playerId_, TaskType::DEMUXER);

// media_demuxer.cpp:916 — SampleConsumerLoop Task（消费解封装样本）
auto sampleConsumerTask = std::make_unique<Task>(sampleConsumerTaskName, playerId_, TaskType::DECODER);

// media_demuxer.cpp:925 — SAM_CON/SAM_PRO 双任务（生产者/消费者分离）
= std::make_unique<Task>("SAM_CON", playerId_, TaskType::DECODER, TaskPriority::HIGH, false);
= std::make_unique<Task>("SAM_PRO", playerId_, TaskType::DEMUXER, TaskPriority::HIGH, false);
```

### 3.4 DoProcessInputBuffer 任务入口（证据：audio_sink_filter.cpp:258-260, decoder_surface_filter.cpp:1175）

```cpp
// audio_sink_filter.cpp:258-260 — Sink Filter 的处理入口
Status AudioSinkFilter::DoProcessInputBuffer(int recvArg, bool dropFrame)
{
    (void)recvArg;
    audioSink_->DrainOutputBuffer(dropFrame);  // 渲染音频帧
    return Status::OK;
}

// decoder_surface_filter.cpp:1175 — Decoder Filter 的处理入口
Status DecoderSurfaceFilter::DoProcessInputBuffer(int recvArg, bool dropFrame) { ... }
```

## 四、三者联动流程

### 4.1 Pipeline 启动时三者联动（证据：demuxer_filter.cpp:422-437, surface_decoder_filter.cpp:529-530）

```
1. FilterGraph 拓扑建立
   DemuxerFilter::LinkNext(SurfaceDecoderFilter, STREAMTYPE_RAW_VIDEO)
       → SurfaceDecoderFilter::OnLinked(outType, meta, callback)
       → SurfaceDecoderFilter::OnLinkedResult(mediaCodec_->GetInputBufferQueue(), meta)
       → DemuxerFilter::OnLinkedResult(queue, meta)  // 握手完成

2. Port 绑定完成
   AVBufferQueue 创建（Producer 端 / Consumer 端配对）
   queueProducer = downstream.GetInputBufferQueue()

3. TaskDispatch 启动
   SurfaceDecoderFilter::DoStart()
       → RenderLoop 线程启动（decoder_surface_filter.cpp:529-530）
       → readThread_ = std::make_unique<std::thread>(&DecoderSurfaceFilter::RenderLoop, this)

   DemuxerFilter::DoStart()
       → demuxer_->Start() → MediaDemuxer Task 调度 ReadLoop
       → isLoopStarted = true（demuxer_filter.cpp:432）
```

### 4.2 数据流经过 Port 时 TaskDispatch 驱动（证据：media_demuxer.cpp:335, audio_capture_filter.cpp:140）

```
DemuxerFilter::ReadLoop(trackId) [Task 驱动]
    → demuxer_->ReadSample(avBuffer)  // 从容器读取压缩帧
    → AVBufferQueue::PushBuffer(queue, avBuffer)  // 写入 Port

SurfaceDecoderFilter::RenderLoop() [独立线程]
    → AVBufferQueue::AcquireBuffer()  // 从 Port 读取
    → mediaCodec_->Decode()  // 解码
    → outputQueue->PushBuffer()  // 写入下游 Port

AudioSinkFilter::DoProcessInputBuffer() [由下游/框架调用]
    → audioSink_->DrainOutputBuffer(dropFrame)  // 渲染音频
```

## 五、Filter 生命周期与三者联动状态映射

| FilterState | FilterGraph | Port | TaskDispatch |
|-------------|-------------|------|--------------|
| INITIALIZED | 未链接 | 无端口 | 无线程 |
| READY | LinkNext 完成 | Producer 已绑定 | Task 已创建，未启动 |
| RUNNING | 拓扑不变 | 数据流动 | TaskThread 运行中 |
| PAUSED | 拓扑不变 | 暂停 Push/Pull | TaskThread 暂停（可恢复） |
| FROZEN | 拓扑不变 | 保留 Port | TaskThread 暂停（系统休眠，不可恢复） |
| STOPPED | UnLinkNext 断开 | 释放端口 | TaskThread 停止并 join |
| ERROR | 拓扑不变 | 可能有残留 | 线程异常退出 |

## 六、关键源码文件索引

| 文件 | 行号 | 内容 |
|------|------|------|
| `services/media_engine/filters/demuxer_filter.cpp` | 775-820 | `LinkNext` FilterGraph 串联协议 |
| `services/media_engine/filters/demuxer_filter.cpp` | 422-437 | `DoStart` Task 启动 + Loop 标记 |
| `services/media_engine/filters/demuxer_filter.cpp` | 440-450 | `DoStop` Task 停止 |
| `services/media_engine/filters/demuxer_filter.h` | 168-178 | `nextFilter_` / `nextFiltersMap_` / `track_id_map_` |
| `services/media_engine/filters/surface_decoder_filter.cpp` | 529-530 | `RenderLoop` TaskThread 启动 |
| `services/media_engine/filters/surface_decoder_filter.cpp` | 1283-1302 | `RenderLoop` 循环体实现 |
| `services/media_engine/filters/surface_decoder_filter.cpp` | 38-75 | `SurfaceDecoderFilterLinkCallback` Port 握手 |
| `services/media_engine/filters/surface_decoder_filter.cpp` | 407-414 | `OnLinkedResult` Producer 端口返回 |
| `services/media_engine/filters/surface_decoder_filter.cpp` | 1175 | `DoProcessInputBuffer` 任务入口 |
| `services/media_engine/filters/muxer_filter.cpp` | 54-84 | `MuxerBrokerListener` 多 Port 监听器 |
| `services/media_engine/filters/muxer_filter.cpp` | 294 | `GetInputBufferQueue(trackIndex)` 按轨获取 Port |
| `services/media_engine/filters/audio_capture_filter.cpp` | 383-386 | `ReadLoop` 任务线程 |
| `services/media_engine/filters/audio_sink_filter.cpp` | 258-260 | `DoProcessInputBuffer` 消费入口 |
| `services/media_engine/modules/demuxer/media_demuxer.cpp` | 861-941 | `Task` 统一抽象（ReadLoop/SampleConsumerLoop/SAM_CON/SAM_PRO） |
| `services/media_engine/modules/demuxer/media_demuxer.cpp` | 335 | `ReadLoop(trackId)` Demuxer 主读取循环 |
| `interfaces/inner_api/native/demuxer_filter.h` | 36-99 | Filter 基类生命周期七步曲接口 |

## 七、关联记忆

| ID | 标题 | 关联关系 |
|----|------|----------|
| S14 | MediaEngine Filter Chain 架构 | S112 为 S14 的架构升级版，S14 聚焦三联机制，S112 聚焦三者联动整体图 |
| S89 | AVCodec Filter Framework 基础架构 | S112 继承 S89 的 Filter/StreamType/FilterLinkCallback 框架，聚焦 Pipeline 整体协调 |
| S41 | DemuxerFilter 解封装过滤器 | S112 的 FilterGraph 示例来源 |
| S56 | VideoSink 视频渲染同步器 | S112 的 TaskDispatch（RenderLoop）示例来源 |
| S22 | MediaSyncManager 音视频同步 | S112 TaskDispatch 与 SyncManager 的协调点 |
| S73 | 三路 Sink 引擎协作架构 | S112 Port 机制的 Sink 侧视角 |
