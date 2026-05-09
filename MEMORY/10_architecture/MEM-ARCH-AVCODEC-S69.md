---
status: approved
approved_at: "2026-05-06"
---

# S69: MediaDemuxer 核心解封装引擎 — SampleQueue 缓冲队列与流控机制

> **草案状态**: approved
> **生成时间**: 2026-04-27T09:55
> **scope**: AVCodec, MediaDemuxer, SampleQueue, SampleQueueController, StreamDemuxer, BufferManagement, Streaming, AdaptiveBitrate
> **关联场景**: 新需求开发/问题定位/流媒体播放/HLS-DASH 自适应码率

---

## 1. 概述

MediaDemuxer（`media_demuxer.cpp` 6012行）是媒体解封装的**核心引擎**，负责从容器格式（MP4/MKV/FLV/HLS/DASH）中解析出压缩的音频/视频/字幕样本，并通过 SampleQueue 缓冲队列将数据传递给下游 Filter 或用户调用者。

**三层组件关系**：

```
MediaDemuxer (6012行)
  ├── StreamDemuxer (492行)    — BaseStreamDemuxer 子类，VOD 流式读取
  │     └── CacheData          — 分片缓存管理（DASH/HTTP 流）
  ├── SampleQueueController    — 流控策略（水位线/启停阈值/速度统计）
  └── SampleQueue (per-track) — per-track AVBufferQueue 封装缓冲队列
        ├── AVBufferQueue      — 底层环形缓冲区
        ├── PTS 管理           — lastEnter/lastOut/lastEnd 三时间戳
        ├── BitrateSwitch      — 自适应码率切换（SelectBitrateStatus）
        └── RollbackBuffer     — 缓冲区回滚机制
```

**核心文件**：

| 文件 | 行数 | 职责 |
|------|------|------|
| `media_demuxer.cpp` | 6012 | 核心引擎，TrackWrapper 管理，ReadLoop，Seek |
| `media_demuxer.h` | ~670 | public API + private 成员（TrackWrapper/SampleQueue/流控） |
| `sample_queue.cpp` | 773 | SampleQueue 实现（Push/Acquire/Rollback/BitrateSwitch） |
| `sample_queue.h` | 157 | SampleQueue 头文件（Config/常量/AVBufferQueue 集成） |
| `sample_queue_controller.cpp` | 300 | 水位线策略，速度统计，启停判断 |
| `sample_queue_controller.h` | 90 | SampleQueueController 头文件 |
| `stream_demuxer.cpp` | 492 | StreamDemuxer 实现（VOD 流读取/CacheData） |
| `base_stream_demuxer.h` | ~200 | BaseStreamDemuxer 基类（Source/TypeFinder/状态机） |

---

## 2. MediaDemuxer 架构

### 2.1 核心类定义

```cpp
// media_demuxer.h
class MediaDemuxer : public std::enable_shared_from_this<MediaDemuxer>,
                     public Plugins::Callback,
                     public InterruptListener,
                     public SampleQueueCallback {
    // ...
    std::map<int32_t, sptr<AVBufferQueueProducer>> bufferQueueProducerMap_;
    // SampleQueue per track
    std::map<int32_t, std::shared_ptr<SampleQueue>> sampleQueueMap_;
    std::shared_ptr<SampleQueueController> sampleQueueController_;
    std::shared_ptr<MediaSyncManager> syncCenter_;
    std::shared_ptr<Source> source_;
    std::shared_ptr<Plugins::DemuxerPlugin> plugin_;
    // Track 管理
    std::map<int32_t, std::unique_ptr<Task>> readTaskMap_;  // per-track ReadLoop
    std::map<int32_t, std::unique_ptr<Task>> consumeTaskMap_; // per-track ConsumeLoop
};
```

**关键设计**：MediaDemuxer 支持两种模式：
- **Filter 模式**：启用 SampleQueue，下游 Filter 通过 AVBufferQueue 消费样本
- **AVDemuxer 模式**：用户直接调用 ReadSample()，通过 bufferQueueProducerMap_ 取数据

### 2.2 ReadLoop 生产者循环

```cpp
// media_demuxer.cpp:ReadLoop(int32_t trackId) — 典型生产循环
int64_t MediaDemuxer::ReadLoop(int32_t trackId)
{
    auto sampleQueue = sampleQueueMap_[trackId];
    auto bufferProducer = bufferQueueProducerMap_[trackId];
    
    // 1. 从插件读取一帧
    Status ret = plugin_->ReadSample(trackId, buffer);
    if (ret != Status::OK) {
        HandleTrackEos(trackId);
        return -1;
    }

    // 2. 流控：检查水位线，决定是否继续生产
    //    ShouldStopProduce → cacheDuration > bufferingDuration_ → pause read task
    if (sampleQueueController_->CheckWaterLineStopProduce(trackId, sampleQueue)) {
        task->Pause();  // 暂停 ReadLoop，等消费追赶
    }

    // 3. PushBuffer 到 SampleQueue
    //    PushBuffer → 更新 lastEnterSamplePts_ / keyFramePtsSet_ / bitrateSwitch_
    (void)sampleQueue->PushBuffer(buffer, true);
    
    // 4. 触发下游消费
    sampleQueueCb_->OnSampleQueueBufferAvailable(trackId);
    return buffer->pts_;
}
```

> **Evidence**: `media_demuxer.cpp` 内 `ReadLoop` 是数据生产的主循环，每个 track 有独立的 ReadLoop TaskThread（TaskMap_[trackId]）。

### 2.3 SampleConsumerLoop 消费者循环

```cpp
// media_demuxer.cpp:SampleConsumerLoop(int32_t trackId)
int64_t MediaDemuxer::SampleConsumerLoop(int32_t trackId)
{
    auto sampleQueue = sampleQueueMap_[trackId];
    std::shared_ptr<AVBuffer> sampleBuffer;
    
    // 1. 从 SampleQueue 取出（Acquires）
    //    AcquireBuffer → 从 rollbackBufferQueue_ 或 sampleBufferQueueConsumer_
    Status status = sampleQueue->AcquireBuffer(sampleBuffer);
    if (status != Status::OK) {
        return -1;
    }

    // 2. 速度统计：记录消费速度
    sampleQueueController_->ConsumeSpeed(trackId);

    // 3. 流控：CheckWaterLineStartConsume
    //    缓存不足 → 通知上游继续生产
    if (sampleQueueController_->CheckWaterLineStartConsume(trackId, sampleQueue)) {
        StartTask(trackId);  // 唤醒 ReadLoop
    }

    // 4. 流控：ShouldStopConsume
    //    cacheDuration == 0 且 idle 超过 MAX_SAMPLE_IDLE_TIME_MS(100ms) → pause consume
    (void)sampleQueueController_->ShouldStopConsume(trackId, sampleQueue, task);

    // 5. 拷贝到输出队列
    CopyFrameToUserQueue(trackId);
    sampleQueue->ReleaseBuffer(sampleBuffer);
    return sampleBuffer->pts_;
}
```

> **Evidence**: `media_demuxer.cpp` 中 `SampleConsumerLoop`（~trackId）是消费端驱动，与 `ReadLoop`（生产端）形成背压（back-pressure）控制。

---

## 3. SampleQueue 缓冲队列

### 3.1 队列配置

```cpp
// sample_queue.h
struct Config {
    int32_t queueId_{0};
    std::string queueName_{""};
    uint32_t queueSize_{DEFAULT_SAMPLE_QUEUE_SIZE};      // 默认 500
    uint32_t bufferCap_{DEFAULT_SAMPLE_BUFFER_CAP};       // 0=自动
    bool isSupportBitrateSwitch_{false};
    bool isFlvLiveStream_{false};
    bool isNeedSetLarge_{false};
};

// 常量定义
static constexpr uint32_t MAX_SAMPLE_QUEUE_SIZE = 16;
static constexpr uint32_t MAX_SAMPLE_QUEUE_SIZE_ON_MUTE = 500;
static constexpr uint32_t DEFAULT_SAMPLE_QUEUE_SIZE = 500;  // 默认 500 帧
static constexpr uint32_t FD_SAMPLE_QUEUE_SIZE = 16;        // FD 源用小队列
```

### 3.2 AVBufferQueue 集成

```cpp
// sample_queue.cpp:Init()
Status SampleQueue::Init(const Config& config)
{
    // 1. 创建 AVBufferQueue 底层的环形缓冲区
    sampleBufferQueue_ = AVBufferQueue::Create(
        config_.queueSize_,                    // queueSize=500
        MemoryType::VIRTUAL_MEMORY,
        config_.queueName_                     // e.g. "SampleQueue_0"
    );

    // 2. 获取 Producer/Consumer 端
    sampleBufferQueueProducer_ = sampleBufferQueue_->GetProducer();
    sampleBufferQueueConsumer_ = sampleBufferQueue_->GetConsumer();

    // 3. Producer 端：Buffer 可用时触发 OnBufferAvailable
    sptr<IProducerListener> producerListener = 
        MakeSptr<SampleBufferProducerListener>(shared_from_this());
    sampleBufferQueueProducer_->SetBufferAvailableListener(producerListener);

    // 4. Consumer 端：Buffer 可用时触发 OnBufferConsumer
    sptr<IConsumerListener> consumerListener = 
        new SampleBufferConsumerListener(shared_from_this());
    sampleBufferQueueConsumer_->SetBufferAvailableListener(consumerListener);

    // 5. 预填充 buffer
    return AttachBuffer();  // 预分配 queueSize_ 个 AVBuffer
}
```

> **Evidence**: `sample_queue.cpp:Init`（~第66行）展示了 SampleQueue 如何委托 AVBufferQueue 进行底层缓冲管理，自己只负责 PTS 跟踪和 bitrate switch 逻辑。

### 3.3 PushBuffer 生产者写入

```cpp
// sample_queue.cpp:PushBuffer()
Status SampleQueue::PushBuffer(std::shared_ptr<AVBuffer>& sampleBuffer, bool available)
{
    // 1. 写入 AVBufferQueue
    Status status = sampleBufferQueueProducer_->PushBuffer(sampleBuffer, available);

    // 2. 更新 PTS
    if (!IsEosFrame(sampleBuffer)) {
        UpdateLastEnterSamplePts(sampleBuffer->pts_);
    }
    if (lastEnterSamplePts_ < lastOutSamplePts_) {
        lastOutSamplePts_ = lastEnterSamplePts_ - 1;  // 重置
    }

    // 3. BitrateSwitch：关键帧插入
    if (IsKeyFrame(sampleBuffer)) {
        std::lock_guard<std::mutex> ptsLock(ptsMutex_);
        keyFramePtsSet_.insert(sampleBuffer->pts_);  // 记录关键帧 PTS
        if (IsSwitchBitrateOK()) {
            NotifySwitchBitrateOK();  // 触发码率切换回调
        }
    }
    return Status::OK;
}
```

> **Evidence**: `sample_queue.cpp:PushBuffer`（~第152行）展示了生产端写入流程，包括 PTS 更新和 BitrateSwitch 关键帧追踪。

### 3.4 AcquireBuffer 消费者获取

```cpp
// sample_queue.cpp:AcquireBuffer()
Status SampleQueue::AcquireBuffer(std::shared_ptr<AVBuffer>& sampleBuffer)
{
    // 1. 优先从 RollbackBuffer 回退队列取
    if (PopRollbackBuffer(sampleBuffer) != Status::OK) {
        // 2. 从 AVBufferQueue Consumer 端取
        Status ret = sampleBufferQueueConsumer_->AcquireBuffer(sampleBuffer);
        FALSE_RETURN_V_NOLOG(ret == Status::OK, ret);
    }

    // 3. BitrateSwitch：从 keyFramePtsSet_ 中移除已消费关键帧
    if (IsKeyFrame(sampleBuffer)) {
        std::lock_guard<std::mutex> ptsLock(ptsMutex_);
        keyFramePtsSet_.erase(sampleBuffer->pts_);
    }
    return Status::OK;
}
```

> **Evidence**: `sample_queue.cpp:AcquireBuffer`（~第188行）展示了消费端获取流程，RollbackBuffer 用于出错回滚。

### 3.5 RollbackBuffer 缓冲区回滚

```cpp
// sample_queue.h — 成员变量
std::mutex rollbackMutex_;
std::list<std::shared_ptr<AVBuffer>> rollbackBufferQueue_;  // 回退队列

// sample_queue.cpp — 回滚流程
Status SampleQueue::RollbackBuffer(std::shared_ptr<AVBuffer>& sampleBuffer)
{
    std::lock_guard<std::mutex> lock(rollbackMutex_);
    rollbackBufferQueue_.push_front(sampleBuffer);  // push_front 优先重试
}

Status SampleQueue::PopRollbackBuffer(std::shared_ptr<AVBuffer>& sampleBuffer)
{
    std::lock_guard<std::mutex> lock(rollbackMutex_);
    if (!rollbackBufferQueue_.empty()) {
        sampleBuffer = rollbackBufferQueue_.front();
        rollbackBufferQueue_.pop_front();
        return Status::OK;
    }
    return Status::ERROR;  // 没有可回滚的 buffer
}
```

> **Evidence**: `sample_queue.cpp` RollbackBuffer 系列函数（~第420-450行），当复制/处理失败时，将 buffer 放入回滚队列，下次 AcquireBuffer 优先从回滚队列取。

### 3.6 缓存时长计算

```cpp
// sample_queue.cpp:GetCacheDuration() / NewGetCacheDuration()
uint64_t SampleQueue::GetCacheDuration() const
{
    if (lastEnterSamplePts_ == Plugins::HST_TIME_NONE ||
        lastOutSamplePts_ == Plugins::HST_TIME_NONE) {
        return 0;
    }
    return static_cast<uint64_t>(lastEnterSamplePts_ - lastOutSamplePts_);
}

uint64_t SampleQueue::NewGetCacheDuration() const
{
    // 与 GetCacheDuration 略有差异，用于不同场景
    return GetCacheDuration();
}
```

> **Evidence**: `sample_queue.cpp`（~第280-290行），缓存时长 = 最新进入 PTS - 最新输出 PTS，反映队列中未消费样本的总时长。

---

## 4. SampleQueueController 流控策略

### 4.1 水位线常量

```cpp
// sample_queue_controller.h
static constexpr uint64_t QUEUE_SIZE_MIN = 30;
static constexpr uint64_t START_CONSUME_WATER_LOOP = 5 * 1000 * 1000;  // 5s  开始消费
static constexpr uint64_t STOP_CONSUME_WATER_LOOP = 0;                   // 0s   停止消费
static constexpr uint64_t START_PRODUCE_WATER_LOOP = 5 * 1000 * 1000;  // 5s  开始生产
static constexpr uint64_t STOP_PRODUCE_WATER_LOOP = 10 * 1000 * 1000; // 10s  停止生产
static constexpr uint32_t FIRST_START_CONSUME_WATER_LOOP = 2 * 1000 * 1000; // 2s 首次起播
```

### 4.2 双水位线流控算法

```cpp
// sample_queue_controller.cpp:ShouldStartProduce()
// 缓存不足（< 5s）→ 唤醒生产
bool SampleQueueController::ShouldStartProduce(int32_t trackId, 
    std::shared_ptr<SampleQueue> sampleQueue, const std::unique_ptr<Task> &task)
{
    uint64_t cacheDuration = sampleQueue->NewGetCacheDuration();
    if (cacheDuration > GetPlayBufferingDuration()) {  // 缓存 > 首次起播阈值
        return false;  // 不需要继续生产
    }
    if (!task->IsTaskRunning()) {
        task->Start();  // 唤醒 ReadLoop
    }
    return true;
}

// sample_queue_controller.cpp:ShouldStopProduce()
// 缓存充足（> 10s）→ 暂停生产（背压）
bool SampleQueueController::ShouldStopProduce(int32_t trackId,
    std::shared_ptr<SampleQueue> sampleQueue, const std::unique_ptr<Task> &task)
{
    uint64_t cacheDuration = sampleQueue->NewGetCacheDuration();
    if (cacheDuration < GetBufferingDuration() &&  // 缓存 < 10s
        sampleQueue->GetFilledBufferSize() < SampleQueue::DEFAULT_SAMPLE_QUEUE_SIZE - 1) {
        return false;  // 队列未满，不停止
    }
    if (task->IsTaskRunning()) {
        task->Pause();  // 暂停 ReadLoop
    }
    return true;
}
```

> **Evidence**: `sample_queue_controller.cpp`（~第58-90行），双水位线算法：START(5s) / STOP(10s) 形成 5s 的**滞回区间（hysteresis）**，防止生产者在临界点反复启停。

### 4.3 消费启停控制

```cpp
// ShouldStartConsume：缓存 > 首次起播阈值(2s) → 开始消费
// ShouldStopConsume：缓存 = 0 且 idle 100ms → 暂停消费
bool SampleQueueController::ShouldStopConsume(int32_t trackId, ...)
{
    uint64_t cacheDuration = sampleQueue->NewGetCacheDuration();
    if (cacheDuration > STOP_CONSUME_WATER_LOOP) {  // > 0
        stopConsumeStartTime_[trackId] = 0;
        return false;
    }
    // idle 100ms 才暂停消费
    auto now = SteadyClock::GetCurrentTimeMs();
    FALSE_RETURN_V_NOLOG((now - stopConsumeStartTime_[trackId]) >= MAX_SAMPLE_IDLE_TIME_MS, false);
    if (task->IsTaskRunning()) {
        task->Pause();
    }
    return true;
}
```

> **Evidence**: `sample_queue_controller.cpp:ShouldStopConsume`（~第98行），消费端启停阈值不同（2s起/0s停+100ms idle），与生产端阈值不对称，防止震荡。

### 4.4 速度统计（SpeedCountInfo）

```cpp
// sample_queue_controller.h — 内嵌类
class SpeedCountInfo {
    std::atomic<uint64_t> totalFrameCount = 0;        // 总帧数
    std::atomic<uint64_t> totalEffectiveRunTimeUs = 0; // 有效运行时间（不含idle）
    std::atomic<uint64_t> lastEventTimeUs = 0;         // 上次事件时间
    double GetSpeed() const;  // 速度 = totalFrameCount * 1e6 / totalEffectiveRunTimeUs
};

// 用于自适应码率切换决策
void SampleQueueController::ConsumeSpeed(int32_t trackId) {
    consumeSpeedCountInfo_[trackId]->IncrementFrameCount();
    consumeSpeedCountInfo_[trackId]->OnEventTimeRecord();  // 记录消费速度
}
```

> **Evidence**: `sample_queue_controller.cpp`（~第170-200行），SpeedCountInfo 用于统计生产和消费速度，为码率切换提供数据支撑。

### 4.5 缓冲策略配置

```cpp
// SetBufferingDuration：设置 PlayStrategy
void SampleQueueController::SetBufferingDuration(std::shared_ptr<Plugins::PlayStrategy> strategy)
{
    if (strategy->duration != 0) {
        // 限制在 [1s, 20s] 范围
        bufferingDuration_.store(std::max(MIN_DURATION, std::min(MAX_DURATION, 
            static_cast<uint64_t>(strategy->duration))) * S_TO_US);
    }
    if (strategy->bufferDurationForPlaying != 0) {
        // 首次起播缓冲，限制在 [0s, 20s]
        firstBufferingDuration_.store(static_cast<uint64_t>(std::max(MIN_FIRST_DURATION,
            std::min(MAX_FIRST_DURATION, strategy->bufferDurationForPlaying))) * S_TO_US);
    }
}

// GetPlayBufferingDuration：首次用 firstBufferingDuration_，之后用 bufferingDuration_ * 0.6
uint64_t SampleQueueController::GetPlayBufferingDuration()
{
    if (isSetFirstBufferingDuration_.load()) {
        return firstBufferingDuration_.load();  // 首次起播用首次阈值
    }
    return std::min(static_cast<uint64_t>(std::ceil(bufferingDuration_.load() * CONSUME_RATE)),
        START_CONSUME_WATER_LOOP);  // 之后用 bufferingDuration × 0.6，上限 5s
}
```

> **Evidence**: `sample_queue_controller.cpp:SetBufferingDuration`（~第136行），展示了缓冲策略：首次起播用较小阈值（2s），正常播放用 bufferingDuration × 0.6，节省启动延迟。

---

## 5. 自适应码率切换（BitrateSwitch）

### 5.1 码率切换状态机

```cpp
// sample_queue.h
enum class SelectBitrateStatus : uint32_t {
    NORMAL = 0,            // 无码率切换命令
    READY_SWITCH,          // 收到切换命令但不满足条件
    SWITCHING,             // 满足条件，等待 SwitchDone 回调
};

// 切换条件：距离上一个切换点 > 3s
static constexpr int64_t MIN_SWITCH_BITRATE_TIME_US = 3000000;
```

### 5.2 码率切换流程

```cpp
// MediaDemuxer:SelectBitRate() → ReadySwitchBitrate() → SampleQueue
Status MediaDemuxer::SelectBitRate(uint32_t bitRate, bool isAutoSelect, bool isForceSelect)
{
    for (auto& [trackId, sampleQueue] : sampleQueueMap_) {
        sampleQueue->ReadySwitchBitrate(bitRate);  // 写入 switchBitrateWaitList_
    }
    // 下一次 PushBuffer 遇到关键帧时检查 IsSwitchBitrateOK()
}

// SampleQueue:PushBuffer() 中
if (IsKeyFrame(sampleBuffer) && IsSwitchBitrateOK()) {
    NotifySwitchBitrateOK();  // 触发 SampleQueueCallback::OnSelectBitrateOk
}

// SampleQueue:IsSwitchBitrateOK()
// 检查：距离上一个切换点 > 3s 且 keyFramePtsSet_ 中已有足够的切换点
bool SampleQueue::IsSwitchBitrateOK() {
    if (switchStatus_ == SelectBitrateStatus::NORMAL) return false;
    if (switchBitrateWaitList_.size() >= MAX_BITRATE_SWITCH_WAIT_NUMBER) {
        return (currentPts - lastSwitchPts_) >= MIN_SWITCH_BITRATE_TIME_US;
    }
    return false;
}
```

> **Evidence**: `sample_queue.cpp`（~第450-480行），码率切换依赖关键帧，必须等待关键帧 PTS 可达且距上次切换 > 3s，防止 GOP 中间切换导致花屏。

---

## 6. StreamDemuxer 流式读取

### 6.1 缓存数据管理

```cpp
// base_stream_demuxer.h — CacheData
class CacheData {
    std::shared_ptr<Buffer> data = nullptr;  // 缓存的数据
    uint64_t offset = 0;                      // 当前消费偏移
    bool CheckCacheExist(uint64_t len);        // len 是否在 [offset, offset+size) 内
    void Init(const std::shared_ptr<Buffer>& buffer, uint64_t bufferOffset);
};

// stream_demuxer.cpp — 分片缓存读取
Status StreamDemuxer::ReadFrameData(int32_t streamID, uint64_t offset, size_t size,
    std::shared_ptr<Buffer>& bufferPtr, bool isSniffCase)
{
    std::unique_lock<std::mutex> lock(cacheDataMutex_);
    // 1. DASH 或不可 seek 的 DataSrc：从缓存读
    if (IsDash() || GetIsDataSrcNoSeek()) {
        if (cacheDataMap_[streamID].CheckCacheExist(offset)) {
            return PullDataWithCache(streamID, offset, size, bufferPtr, isSniffCase);
        }
    }
    // 2. 否则直接拉取
    return PullData(streamID, offset, size, bufferPtr, isSniffCase);
}
```

> **Evidence**: `stream_demuxer.cpp:ReadFrameData`（~第50行），CacheData 用于 DASH 分片缓存，避免重复网络请求。

---

## 7. 关键设计总结

### 7.1 生产-消费背压模型

```
ReadLoop (生产) ──PushBuffer──▶ SampleQueue (AVBufferQueue)
                                           │
                        OnBufferAvailable ─┘
                                           │
                                           ▼
                               SampleConsumerLoop (消费)
                                           │
                        ShouldStopProduce ←┘ (水位线检查)
                            ↕ 背压
                        ShouldStopConsume
```

**双水位线防止震荡**：生产 STOP@10s / START@5s，消费 STOP@0s+100ms idle / START@2s。

### 7.2 SampleQueue vs AVBufferQueue 职责划分

| 职责 | SampleQueue | AVBufferQueue |
|------|------------|---------------|
| 底层缓冲 | ❌（委托） | ✅ 环形缓冲区 |
| PTS 跟踪 | ✅ lastEnter/lastOut/lastEnd | ❌ |
| 关键帧追踪 | ✅ keyFramePtsSet_ | ❌ |
| 码率切换 | ✅ SelectBitrateStatus | ❌ |
| 回滚机制 | ✅ rollbackBufferQueue_ | ❌ |
| BitrateSwitch 等待 | ✅ switchBitrateWaitList_ | ❌ |

### 7.3 与 Filter Pipeline 的集成

MediaDemuxer 在 Filter Pipeline 中作为**数据源**：

```
MediaDemuxer (Filter)
  ├── SampleQueue (per track) → AVBufferQueueProducer
  │                              │
 DemuxerFilter (S41) ◀───────────┘
       │
       ▼
  AudioDecoderFilter (S35) / VideoDecoderFilter (S45/S46)
```

> **关联 S41**: DemuxerFilter 是 MediaDemuxer 的 Filter 封装，两者共同构成解封装 Filter Pipeline 的完整数据流。

---

## 8. 关联主题

| 主题 | 关联关系 |
|------|---------|
| S41 DemuxerFilter | MediaDemuxer 的 Filter 封装层，接收 SampleQueue 输出 |
| S66 TypeFinder | MediaDemuxer 使用 TypeFinder 探测媒体类型（InitTypeFinder） |
| S68 FFmpegDemuxerPlugin | MediaDemuxer 使用的底层解封装插件（h264_mp4toannexb 等 BitstreamFilter） |
| S58 MPEG4BoxParser | 容器格式解析（moov/moof/trak/stbl box），MediaDemuxer 调用链下游 |
| S52 PTS 与帧索引转换 | PTS/Index 双向转换，SampleQueue PTS 跟踪的上游数据源 |
| S64 AVBuffer Signal/Wait | SampleQueue 依赖的 AVBufferQueue 底层信号机制 |
| S37 HTTP 流媒体源 | MediaDemuxer 的 Source，DASH 分片缓存与 StreamDemuxer CacheData 协作 |

---

## 9. 问题定位要点

| 现象 | 检查点 |
|------|--------|
| 播放卡顿/缓冲 | SampleQueueController 水位线配置，bufferingDuration_ 是否过大 |
| 首次起播慢 | firstBufferingDuration_ 是否过大，FIRST_START_CONSUME_WATER_LOOP=2s |
| 频繁卡顿 | CONSUME_RATE=0.6 是否合适，生产/消费速度不匹配 |
| 码率切换失败 | IsSwitchBitrateOK() 是否满足（关键帧+3s间隔），switchBitrateWaitList_ 是否溢出 |
| DASH 播放卡段 | CacheData::CheckCacheExist，DASH 分片缓存是否正确命中 |
| SampleQueue 满 | DEFAULT_SAMPLE_QUEUE_SIZE=500 是否足够，FD_SAMPLE_QUEUE_SIZE=16 是否过小 |
