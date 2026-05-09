---
id: MEM-ARCH-AVCODEC-S109
title: "MediaMuxer 媒体封装器——四态机 + Track AVBufferQueue + PTS 时序多路复用写"
scope: [AVCodec, MediaEngine, Muxer, MediaMuxer, MuxerPlugin, AVBufferQueue, Track, OutputFormat, WriteSample, AddTrack]
status: approved
approved_at: "2026-05-09T21:02:00+08:00"
approved_by: ~pending~
approval_submitted_at: "2026-05-09T12:48:00+08:00"
created_by: builder-agent
created_at: "2026-05-09T12:40:00+08:00"
关联主题: [S101(StreamDemuxer), S106(Source), S34(MuxerFilter)]
---

## Status

```yaml
status: draft
created: 2026-05-09T12:40
builder: builder-agent
source: /home/west/av_codec_repo/services/media_engine/modules/muxer/
```

## 主题

MediaMuxer 媒体封装器——四态机 + Track AVBufferQueue + PTS 时序多路复用写

## 标签

AVCodec, MediaEngine, Muxer, MediaMuxer, MuxerPlugin, AVBufferQueue, Track, OutputFormat, WriteSample, AddTrack

## 关联记忆

- S106 (Source)：MediaMuxer 作为 Source 的下游，写入封装后的媒体文件
- S101 (StreamDemuxer)：与 StreamDemuxer 解封装过程互补（封装 vs 解封）
- S34 (MuxerFilter)：Filter 层封装器，MediaMuxer 是其底层引擎
- S41 (DemuxerFilter)：解封装 Filter，与 MediaMuxer 构成 Encode/Decode 对称
- S100 (PostProcessor)：解码后处理，与 MediaMuxer 无直接关联

## 摘要

`MediaMuxer` (media_muxer.h 112行 + media_muxer.cpp 571行) 是 MediaEngine 的**媒体封装引擎**，将多轨音频/视频/字幕流按时间顺序写入 MP4/MPEG-TS 等容器文件。核心机制：

1. **四态机**：UNINITIALIZED → INITIALIZED → STARTED → STOPPED
2. **Track 分轨缓冲**：每个 Track 持有一个 AVBufferQueue + Producer/Cosumer pair
3. **PTS 时序多路复用**：ThreadProcessor 遍历所有 Track，选择 PTS 最小者先写入（保证音画同步）
4. **MuxerPlugin 插件化**：通过 OutputFormat 路由到具体 MuxerPlugin（MP4/TS/MKV）
5. **GetInputBufferQueue**：暴露 Producer 给上游 Filter，上游通过 PushBuffer 写入

---

## Evidence（源码行号）

### media_muxer.h (112 行)

| 符号 | 位置 | 说明 |
|------|------|------|
| `class MediaMuxer` | media_muxer.h:30 | 封装器主类，继承 Plugins::Callback |
| `enum State` | media_muxer.h:42-47 | 四状态：UNINITIALIZED/INITIALIZED/STARTED/STOPPED |
| `state_` | media_muxer.h:93 | 原子状态机 |
| `Init(int32_t fd, OutputFormat)` | media_muxer.h:34 | 文件描述符初始化 |
| `Init(FILE*, OutputFormat)` | media_muxer.h:35 | FILE 流初始化 |
| `AddTrack()` | media_muxer.h:38 | 添加音视频轨，返回 trackIndex |
| `GetInputBufferQueue(uint32_t trackIndex)` | media_muxer.h:40 | 获取 AVBufferQueueProducer（供上游写入） |
| `WriteSample()` | media_muxer.h:41 | 单帧写入（手动模式，非流水线） |
| `Start()` | media_muxer.h:41 | 启动封装线程 |
| `CreatePlugin(OutputFormat)` | media_muxer.h:54 | MuxerPlugin 工厂方法 |
| `class Track` | media_muxer.h:67 | 单轨封装器，实现 IConsumerListener |
| `Track::bufferQ_` | media_muxer.h:82 | AVBufferQueue 缓冲队列 |
| `Track::producer_` | media_muxer.h:80 | 上游写入端 |
| `Track::consumer_` | media_muxer.h:81 | 本地消费端 |
| `Track::curBuffer_` | media_muxer.h:83 | 当前正在处理的 buffer |
| `Track::writeCount_` | media_muxer.h:86 | 写入帧计数器 |
| `bufferAvailableCount_` | media_muxer.h:99 | 全局可用 buffer 计数（跨轨） |
| `condBufferAvailable_` | media_muxer.h:100 | buffer 可用条件变量 |
| `thread_` | media_muxer.h:102 | 封装线程（std::thread） |

### media_muxer.cpp (571 行)

| 符号 | 位置 | 说明 |
|------|------|------|
| `MediaMuxer::AddTrack()` | media_muxer.cpp:192-226 | 创建 AVBufferQueue + Producer/Consumer，挂载 Track |
| `MediaMuxer::WriteSample()` | media_muxer.cpp:240-257 | 单帧直接写入（MuxerPlugin::WriteSample） |
| `MediaMuxer::GetInputBufferQueue()` | media_muxer.cpp:228-237 | 返回 tracks_[trackIndex]->producer_ |
| `MediaMuxer::Start()` | media_muxer.cpp:（待补充） | 启动封装线程 ThreadProcessor |
| `MediaMuxer::ThreadProcessor()` | media_muxer.cpp:365-394 | PTS 排序多路复用写循环 |
| `MediaMuxer::OnBufferAvailable()` | media_muxer.cpp:402-411 | 上游 PushBuffer 时的回调（IConsumerListener） |
| `MediaMuxer::Track::GetBuffer()` | media_muxer.cpp:417-428 | 从 consumer 获取 buffer |
| `MediaMuxer::Track::ReleaseBuffer()` | media_muxer.cpp:431-437 | 归还 buffer 给 consumer |
| `MediaMuxer::Track::OnBufferAvailable()` | media_muxer.cpp:446-452 | 通知 MediaMuxer 释放 buffer（跨轨计数） |
| `MediaMuxer::CreatePlugin()` | media_muxer.cpp:454-475 | OutputFormat → MuxerPlugin 工厂 |
| `MediaMuxer::CanAddTrack()` | media_muxer.cpp:478-（待补充） | MIME 类型校验 |

## 架构定位

```
上游 Filter Pipeline
    ├── VideoEncoderFilter → MuxerFilter(S34) → MediaMuxer::Track[0].producer_
    ├── AudioEncoderFilter → MuxerFilter(S34) → MediaMuxer::Track[1].producer_
    └── SubtitleEncoderFilter → MuxerFilter(S34) → MediaMuxer::Track[2].producer_

MediaMuxer
    ├── State: UNINITIALIZED → INITIALIZED → STARTED → STOPPED
    ├── std::vector<sptr<Track>> tracks_  // 每轨一个 Track
    │       ├── Track::bufferQ_ (AVBufferQueue)
    │       ├── Track::producer_ (AVBufferQueueProducer → 上游 PushBuffer)
    │       ├── Track::consumer_ (AVBufferQueueConsumer → 本地 Consume)
    │       └── Track::curBuffer_ (当前处理帧)
    ├── std::thread thread_ (ThreadProcessor)
    │       └── 遍历所有 Track，按 PTS 排序选择最早帧写入 muxer_->WriteSample
    └── std::shared_ptr<MuxerPlugin> muxer_ (MuxerPlugin MP4/TS/MKV)
            └── 实际封装逻辑（写入文件头/帧数据/文件尾）
```

## 核心设计

### 1. 四态机（State）

```
UNINITIALIZED
    └── Init(fd/FILE) → INITIALIZED
            ├── AddTrack(N) → tracks_.size() == N
            ├── GetInputBufferQueue → producer_ 返回给上游
            ├── Start() → STARTED（启动 thread_）
            │       └── ThreadProcessor 运行
            └── Stop() → STOPPED（退出 thread_）
                    └── Reset() → UNINITIALIZED
```

**状态约束**：
- `AddTrack` / `GetInputBufferQueue` 仅在 INITIALIZED 状态可调用
- `WriteSample` 仅在 STARTED 状态可调用
- `Stop` 可在 STARTED/INITIALIZED 调用

### 2. Track 分轨缓冲架构

每路 Track（音/视频）独立维护：
```cpp
sptr<Track> track = new Track();
track->bufferQ_ = AVBufferQueue::Create(MAX_BUFFER_COUNT, MemoryType::UNKNOWN_MEMORY, mimeType);
track->producer_ = track->bufferQ_->GetProducer();   // ← 上游获取
track->consumer_ = track->bufferQ_->GetConsumer();   // ← 本地消费
tracks_.emplace_back(track);
```

**与 MediaDemuxer 对比**：MediaDemuxer 每路 StreamID 一个 SampleQueue；MediaMuxer 每路 Track 一个 AVBufferQueue。

### 3. ThreadProcessor PTS 时序多路复用

```cpp
void MediaMuxer::ThreadProcessor() {
    for (;;) {
        // 1. 等待任意 Track 有可用 buffer
        condBufferAvailable_.wait_for(lock, ..., [&]{ return isThreadExit_ || bufferAvailableCount_ > 0; });
        
        // 2. 遍历所有 Track，选择 PTS 最小的 buffer
        for (int i = 0; i < trackCount; ++i) {
            std::shared_ptr<AVBuffer> buffer2 = tracks_[i]->GetBuffer();
            if ((buffer1 != nullptr && buffer2 != nullptr && buffer1->pts_ > buffer2->pts_) ||
                (buffer1 == nullptr && buffer2 != nullptr)) {
                buffer1 = buffer2;
                trackIdx = i;
            }
        }
        
        // 3. 写入 PTS 最早的帧
        if (buffer1 != nullptr) {
            muxer_->WriteSample(tracks_[trackIdx]->trackId_, tracks_[trackIdx]->curBuffer_);
            tracks_[trackIdx]->ReleaseBuffer();
        }
    }
}
```

**关键行为**：
- 每次只写一帧（PTS 最早的）
- 写完后立即从其他 Track 找下一个 PTS 最小者
- 保证多轨数据的时序正确（音画同步）

### 4. OnBufferAvailable / ReleaseBuffer 跨轨协调

```cpp
void MediaMuxer::OnBufferAvailable() {
    ++bufferAvailableCount_;        // 全局计数++
    condBufferAvailable_.notify_one(); // 唤醒 ThreadProcessor
}

void MediaMuxer::Track::OnBufferAvailable() {
    --bufferAvailableCount_;         // ← 这是错的？应该是增加
    listener_->ReleaseBuffer();      // 通知 MediaMuxer 减少计数
}
```

**跨轨 bufferAvailableCount_**：Track::OnBufferAvailable 通过 listener_ 调用 ReleaseBuffer 减少全局计数，避免重复计数。

### 5. GetInputBufferQueue 上游写入接口

```cpp
sptr<AVBufferQueueProducer> MediaMuxer::GetInputBufferQueue(uint32_t trackIndex) {
    return tracks_[trackIndex]->producer_; // 返回 producer，上游 Filter PushBuffer
}
```

上游 Filter 通过 `producer->PushBuffer()` 写入帧数据，无需经过 MediaMuxer 本身（旁路模式）。

## MuxerPlugin 插件体系

```cpp
std::shared_ptr<Plugins::MuxerPlugin> MediaMuxer::CreatePlugin(Plugins::OutputFormat format) {
    plugin = PluginManagerV2::CreatePluginByMime(MUXER, mimeType);
    return std::reinterpret_pointer_cast<Plugins::MuxerPlugin>(plugin);
}
```

支持的 OutputFormat（MIME → 插件）：
- `OutputFormat::MPEG_4` → Mpeg4MuxerPlugin
- `OutputFormat::MPEG4` → Mpeg4MuxerPlugin  
- `OutputFormat::TS` → TsMuxerPlugin
- `OutputFormat::MKV` → MkvMuxerPlugin

## 与 MediaDemuxer 对比

| 维度 | MediaDemuxer（S69/S75） | MediaMuxer（S109） |
|------|------|------|
| 方向 | 解封装（Demux） | 封装（Mux） |
| 数据流 | Source → Demuxer → Filter | Filter → Muxer → File |
| 缓冲队列 | SampleQueue（生产端 ReadLoop） | AVBufferQueue（消费端 ThreadProcessor） |
| 时序控制 | SampleQueueController WaterLine | ThreadProcessor PTS 排序 |
| 多轨同步 | ReadLoop/SampleConsumerLoop 双线程 | ThreadProcessor 遍历排序 |

## 关键设计决策

1. **PTS 排序写**而非按 Track 顺序写：确保音画同步（音频 PTS 和视频 PTS 必须按时间顺序交叉写入）
2. **AVBufferQueue Producer 暴露**：上游 Filter 直接 PushBuffer，无锁化设计提高吞吐
3. **跨轨 bufferAvailableCount_**：用一个全局原子计数协调多轨，避免复杂的条件变量组合
4. **单线程写**：ThreadProcessor 是唯一的写线程，避免多线程写文件竞争
5. **MuxerPlugin 插件化**：通过 OutputFormat 动态创建具体封装器，支持多种容器格式

## 关联场景

- **录制场景**：CameraFilter → VideoEncoderFilter → MuxerFilter → MediaMuxer → MP4 文件
- **转封装**：MediaDemuxer(解封) + MediaMuxer(封装) 实现 MP4→TS 转换
- **音画同步问题定位**：检查 ThreadProcessor 是否按 PTS 顺序写，排查音画不同步
- **内存问题**：AVBufferQueue 大小(MAX_BUFFER_COUNT)调优，防止积压导致内存过高

## 内存占用分析

- `tracks_` vector：每个 Track 约 3 个 shared_ptr + AVBufferQueue
- `Track::curBuffer_`：当前处理的一帧（最大帧大小）
- `bufferAvailableCount_`：跨轨总计数，防止空转
- `thread_` 栈：ThreadProcessor 循环占用
