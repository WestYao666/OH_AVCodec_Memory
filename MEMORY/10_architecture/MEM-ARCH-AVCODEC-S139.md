---
type: architecture
id: MEM-ARCH-AVCODEC-S139
status: draft
created_at: "2026-05-15T02:46:58+08:00"
updated_at: "2026-05-15T02:46:58+08:00"
created_by: builder
topic: SampleQueue 与 SampleQueueController 双组件流控架构——MAX_SAMPLE_QUEUE_SIZE=16~500/水位线启停/码率切换状态机
scope: [AVCodec, MediaEngine, Demuxer, SampleQueue, SampleQueueController, Buffer, Queue, WaterLine, BitrateSwitch, FlowControl, SpeedControl, MediaDemuxer, StreamDemuxer, Track]
created_at: "2026-05-15T02:46:58+08:00"
summary: SampleQueue样本队列(770行cpp)+SampleQueueController流控器(300行cpp)双组件架构，MAX_SAMPLE_QUEUE_SIZE=16~500六种规格/水位线启停算法/码率切换状态机，与S101(StreamDemuxer)/S102(SampleQueueController)关联
source_repo: /home/west/av_codec_repo
source_root: services/media_engine/modules/demuxer
evidence_version: local_mirror
---

## 一、架构总览

SampleQueue 与 SampleQueueController 是 MediaDemuxer（及 StreamDemuxer）体系中的样本队列与流控管理双组件，位于 `services/media_engine/modules/demuxer/` 目录。

- **SampleQueue**（`sample_queue.cpp`，770行 / `sample_queue.h`，157行）：解封装样本的环形队列，持有 AVBuffer，负责 Push/Pop/Rollback 操作。
- **SampleQueueController**（`sample_queue_controller.cpp`，300行 / `sample_queue_controller.h`，90行）：流控大脑，基于水位线和缓存时长决定队列的 Produce/Consume 启停。

**定位**：S102 中描述的流控逻辑的具体实现层，与 MediaDemuxer::CreateSampleQueue 工厂方法配合使用。

## 二、文件清单与行号级证据

| 文件 | 行数 | 说明 |
|------|------|------|
| `sample_queue.cpp` | 770 | SampleQueue 样本队列实现（Push/Pop/Rollback/BufferRequest） |
| `sample_queue.h` | 157 | SampleQueue 类定义 + Config 结构体 + SelectBitrateStatus 枚举 |
| `sample_queue_controller.cpp` | 300 | SampleQueueController 流控器实现（6大判断函数） |
| `sample_queue_controller.h` | 90 | SampleQueueController 类定义 + SpeedCountInfo 结构体 |

## 三、SampleQueue 关键设计

### 3.1 队列规模配置（sample_queue.h:45-61）

```cpp
// sample_queue.h:45-61 - 六种队列规格
static constexpr uint32_t MAX_SAMPLE_QUEUE_SIZE = 16;           // 最小（实时流）
static constexpr uint32_t MAX_SAMPLE_QUEUE_SIZE_ON_MUTE = 500;  // 最大（静音模式）
static constexpr uint32_t DEFAULT_SAMPLE_QUEUE_SIZE = 500;     // 默认（点播）
static constexpr uint32_t FD_SAMPLE_QUEUE_SIZE = 16;           // 文件描述符（本地FD）
static constexpr uint32_t DEFAULT_SAMPLE_BUFFER_CAP = 0;         // 默认buffer容量（0=无限）
static constexpr uint32_t MAX_SAMPLE_BUFFER_CAP = DEFAULT_SAMPLE_BUFFER_CAP;

// Config 结构体（sample_queue.h:54-61）
struct Config {
    int32_t queueId_{0};
    MediaType mediaType_{MediaType::MEDIA_TYPE_AUDIO};
    uint32_t queueSize_{DEFAULT_SAMPLE_QUEUE_SIZE};        // 队列大小
    uint32_t bufferCap_{DEFAULT_SAMPLE_BUFFER_CAP};         // buffer容量
    bool isSupportBitrateSwitch_{false};                   // 是否支持码率切换
    bool isFlvLiveStream_{false};                          // 是否FLV直播
    bool isNeedSetLarge_{false};                           // 是否需要大队列
};
```

### 3.2 核心操作函数（sample_queue.cpp）

| 函数 | 行号 | 说明 |
|------|------|------|
| `SampleQueue::RequestBuffer` | 146 | 请求缓冲区（Config + timeoutMs） |
| `SampleQueue::PushBuffer` | 157 | 压入样本（Push + available标志） |
| `SampleQueue::PushRollbackBuffer` | 429 | 回滚压入（码率切换失败时回退） |
| `SampleQueue::OnBufferAvailable` | 84 | 缓冲区可用回调（IConsumerListener 实现） |
| `SampleQueue::OnBufferConsumer` | 85 | 消费者回调（触发取样） |
| `SampleQueue::GetCacheDuration` | 86 | 获取缓存时长（us） |
| `SampleQueue::NewGetCacheDuration` | 87 | 新版缓存时长计算 |

### 3.3 SelectBitrateStatus 状态机（sample_queue.h:37-41）

```cpp
// sample_queue.h:37-41 - 码率切换状态机
enum class SelectBitrateStatus : uint32_t {
    IDLE = 0,             // 空闲态
    READY_SWITCH = 1,     // 就绪切换
    SWITCHING = 2,        // 切换中
    SWITCH_DONE = 3,      // 切换完成
    SWITCH_FAILED = 4     // 切换失败
};

// sample_queue.cpp - 码率切换状态转换
Status SampleQueue::ReadySwitchBitrate(uint32_t bitrate);     // 行 78 → READY_SWITCH
Status SampleQueue::ResponseForSwitchDone(int64_t startPts); // 行 82 → SWITCH_DONE
Status SampleQueue::UpdateLastEndSamplePts(int64_t pts);     // 行 80 → 更新pts
```

### 3.4 SampleQueueCallback 接口（sample_queue.h:29-34）

```cpp
// sample_queue.h:29-34 - 回调接口
class SampleQueueCallback {
    virtual Status OnSelectBitrateOk(int64_t startPts, uint32_t bitRate) = 0;
    virtual Status OnSampleQueueBufferAvailable(int32_t queueId) = 0;  // 流控水位触发
    virtual Status OnSampleQueueBufferConsume(int32_t queueId) = 0;    // 消费触发
};
```

## 四、SampleQueueController 流控器关键设计

### 4.1 六种启停判断函数（sample_queue_controller.cpp）

| 函数 | 行号 | 返回 | 说明 |
|------|------|------|------|
| `ShouldStartConsume` | 62 | bool | 消费线程是否应启动（预播放+水位线判断） |
| `ShouldStopConsume` | 106 | bool | 消费线程是否应停止（水位线判断） |
| `ShouldStartProduce` | 132 | bool | 生产线程（Demuxer）是否应启动 |
| `ShouldStopProduce` | 149 | bool | 生产线程是否应停止（水位线判断） |
| `CheckWaterLineStopProduce` | 85 | bool | 水位线停止生产（双水位线：START@5s/STOP@10s） |
| `CheckWaterLineStartConsume` | 91 | bool | 水位线启动消费 |

```cpp
// sample_queue_controller.cpp:62 - 消费启动判断
bool SampleQueueController::ShouldStartConsume(int32_t trackId, 
    std::shared_ptr<SampleQueue> sampleQueue, const std::unique_ptr<Task> &task, bool inPreroll)
{
    // inPreroll=true 时预播放阶段，即使水位未达也会启动消费
    // inPreroll=false 时需满足：(1) 水位线达标 或 (2) 队列非空
}

// sample_queue_controller.cpp:85 - 水位线停止生产
bool SampleQueueController::CheckWaterLineStopProduce(int32_t trackId, 
    std::shared_ptr<SampleQueue> sampleQueue)
{
    // GetCacheDuration() >= bufferingDurationMax_ → 停止生产
}

// sample_queue_controller.cpp:91 - 水位线启动消费
bool SampleQueueController::CheckWaterLineStartConsume(int32_t trackId, 
    std::shared_ptr<SampleQueue> sampleQueue)
{
    // GetCacheDuration() >= bufferingDurationStart_ → 启动消费
}
```

### 4.2 缓存时长管理（sample_queue_controller.cpp:206-248）

```cpp
// sample_queue_controller.cpp:206 - 设置缓冲策略
void SampleQueueController::SetBufferingDuration(std::shared_ptr<Plugins::PlayStrategy> strategy)
{
    // strategy->maxBufferDuration = bufferingDurationMax_ (停止生产阈值)
    // strategy->startBufferDuration = bufferingDurationStart_ (启动消费阈值)
    // 双水位线设计：START(5s) → 启动消费，STOP(10s) → 停止生产
}

// sample_queue_controller.cpp:235/248 - 缓存时长查询
uint64_t SampleQueueController::GetBufferingDuration();      // 当前已缓存时长
uint64_t SampleQueueController::GetPlayBufferingDuration(); // 播放缓冲时长
```

### 4.3 速度控制（sample_queue_controller.cpp:168-196）

```cpp
// sample_queue_controller.cpp:168 - 设置播放速度
void SampleQueueController::SetSpeed(float speed)
{
    // speed_ = speed;
    // 变速播放时调整生产/消费速率
}

// sample_queue_controller.cpp:196 - 消费者速度统计
void SampleQueueController::ConsumeSpeed(int32_t trackId)
{
    // SpeedCountInfo::OnEventTimeRecord() → 记录消费时间戳
    // SpeedCountInfo::IncrementFrameCount() → 增加帧计数
}

// sample_queue_controller.h:29-41 - SpeedCountInfo 速度统计结构
struct SpeedCountInfo {
    std::atomic<uint64_t> totalFrameCount = 0;          // 总帧数
    std::atomic<uint64_t> totalEffectiveRunTimeUs = 0; // 总有效运行时长
    std::atomic<uint64_t> lastEventTimeUs = 0;          // 上次事件时间戳
    uint64_t GetCurrentTimeUs();
    void IncrementFrameCount();
    void OnEventTimeRecord();
};
```

### 4.4 队列规模管理（sample_queue_controller.cpp:41-60）

```cpp
// sample_queue_controller.cpp:41 - 获取队列大小
uint64_t SampleQueueController::GetQueueSize(int32_t trackId);

// sample_queue_controller.cpp:49 - 设置队列大小
void SampleQueueController::SetQueueSize(int32_t trackId, uint64_t size);

// sample_queue_controller.cpp:54 - 增加队列大小
void SampleQueueController::AddQueueSize(int32_t trackId, uint64_t size);

// 静态常量（sample_queue_controller.h:70）
static constexpr uint64_t QUEUE_SIZE_MIN = 30;
```

### 4.5 生产帧计数（sample_queue_controller.cpp:178-196）

```cpp
// sample_queue_controller.cpp:178 - 生产帧计数
void SampleQueueController::ProduceIncrementFrameCount(int32_t trackId)
{
    // SpeedCountInfo[trackId].IncrementFrameCount();
}

// sample_queue_controller.cpp:187 - 生产事件时间记录
void SampleQueueController::ProduceOnEventTimeRecord(int32_t trackId)
{
    // SpeedCountInfo[trackId].OnEventTimeRecord();
}
```

## 五、与相关 S-series 记忆的关联

| 关联记忆 | 关系 | 说明 |
|---------|------|------|
| S101（StreamDemuxer） | 上游消费者 | StreamDemuxer::PullData → SampleQueue::PushBuffer |
| S102（SampleQueueController 双水位线） | S102为概述，S139为源码层 | S102描述双水位线（5s/10s），S139提供行号级证据 |
| S75（MediaDemuxer 六组件） | 下游管理 | MediaDemuxer 创建并管理 SampleQueue 集合 |
| S76（FFmpegDemuxerPlugin） | 数据生产者 | FFmpegDemuxerPlugin 产生的 AVPacket 推入 SampleQueue |
| S97（MediaDemuxer PTS 函数） | 时间参考 | PTS 函数计算样本时间，用于 GetCacheDuration 估算 |

## 六、SampleQueue 与码率切换时序

```
MediaDemuxer::SelectBitRate(bitrate)
  → SampleQueue::ReadySwitchBitrate(bitrate)   // READY_SWITCH
  → FFmpegDemuxerPlugin 刷新解码器
  → DemuxerFilter 暂停推流
  → SampleQueue::ResponseForSwitchDone(startPts) // SWITCH_DONE
  → 若失败 → SampleQueue::PushRollbackBuffer(sample) // 回滚
```

---

_builder-agent: S139 draft generated 2026-05-15T02:46:58+08:00, pending approval_