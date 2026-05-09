# MEM-ARCH-AVCODEC-S102: SampleQueueController 流控引擎 —— SpeedCountInfo 双路统计与 WaterLine 双水位线机制

## Status

```yaml
status: approved
approved_at: "2026-05-09T21:02:00+08:00"
created: 2026-05-08T23:47
builder: builder-agent
source: /home/west/av_codec_repo/services/media_engine/modules/demuxer/sample_queue_controller.{h,cpp}
```

## 主题

SampleQueueController 流控引擎 —— SpeedCountInfo 双路统计与 WaterLine 双水位线机制

## 标签

AVCodec, MediaEngine, Demuxer, SampleQueueController, FlowControl, SpeedCountInfo, WaterLine, SampleQueue, TaskThread, BitrateSwitch, BufferingDuration

## 关联记忆

- S69 (MediaDemuxer 核心解封装引擎)
- S75 (MediaDemuxer 六组件协作架构)
- S97 (DemuxerPluginManager 轨道路由管理器)
- S101 (StreamDemuxer 流式解封装器)
- S41 (DemuxerFilter Filter 层封装)

## 摘要

`SampleQueueController` 是 MediaDemuxer 内部的**流控引擎**，管理 ReadLoop 生产端和 SampleConsumerLoop 消费端之间的缓冲队列平衡。其核心机制包括：

1. **SpeedCountInfo 双路统计**：对每个 trackId 分别统计生产端（Produce）和消费端（Consume）的帧率
2. **WaterLine 双水位线**：START_CONSUME=5μs / STOP_CONSUME=0 / START_PRODUCE=5μs / STOP_PRODUCE=10μs 四阈值驱动 TaskThread 启停
3. **BitrateSwitch 三状态机**：基于 consumeSpeed 触发码率切换

## Evidence（源码行号）

### sample_queue_controller.h (90 行)

| 符号 | 位置 | 说明 |
|------|------|------|
| `struct SpeedCountInfo` | sample_queue_controller.h:29-40 | 生产/消费双路帧率统计结构 |
| `totalFrameCount` | sample_queue_controller.h:30 | 原子帧计数器 |
| `totalEffectiveRunTimeUs` | sample_queue_controller.h:31 | 原子有效运行时间（微秒） |
| `lastEventTimeUs` | sample_queue_controller.h:32 | 原子上次事件时间 |
| `GetCurrentTimeUs()` | sample_queue_controller.h:33 | 当前时间（微秒） |
| `IncrementFrameCount()` | sample_queue_controller.h:34 | 帧计数原子递增 |
| `OnEventTimeRecord()` | sample_queue_controller.h:35 | 事件时间记录 |
| `GetSpeed()` | sample_queue_controller.h:36 | 计算实时速率（帧/微秒） |
| `GetTotalFrameCount()` | sample_queue_controller.h:37 | 获取总帧数 |
| `GetTotalEffectiveRunTimeUs()` | sample_queue_controller.h:38 | 获取总运行时间 |
| `class SampleQueueController` | sample_queue_controller.h:42 | 流控主类 |
| `ShouldStartConsume` | sample_queue_controller.h:48 | 判断是否启动消费（ReadLoop） |
| `ShouldStopConsume` | sample_queue_controller.h:49 | 判断是否停止消费 |
| `ShouldStartProduce` | sample_queue_controller.h:51 | 判断是否启动生产（SampleConsumerLoop） |
| `ShouldStopProduce` | sample_queue_controller.h:52 | 判断是否停止生产 |
| `CheckWaterLineStartConsume` | sample_queue_controller.h:63 | 水位线启动消费阈值检查 |
| `CheckWaterLineStopProduce` | sample_queue_controller.h:62 | 水位线停止生产阈值检查 |
| `ConsumeSpeed` | sample_queue_controller.h:60 | 消费端速率统计 |
| `SetSpeed` | sample_queue_controller.h:59 | 设置播放速度（快放/慢放） |
| `GetSpeed` | sample_queue_controller.h:60 | 获取当前速度 |
| `GetBufferingDuration` | sample_queue_controller.h:57 | 获取缓冲时长 |
| `GetPlayBufferingDuration` | sample_queue_controller.h:58 | 获取播放缓冲时长 |
| `SetBufferingDuration` | sample_queue_controller.h:56 | 设置目标缓冲时长 |
| `produceSpeedCountInfo_` | sample_queue_controller.h:79 | 生产端速率统计 map（per trackId） |
| `consumeSpeedCountInfo_` | sample_queue_controller.h:80 | 消费端速率统计 map（per trackId） |
| `QUEUE_SIZE_MIN = 30` | sample_queue_controller.h:71 | 最小队列大小 |
| `START_CONSUME_WATER_LOOP = 5 * 1000 * 1000` | sample_queue_controller.h:71 | 启动消费水位线 5μs |
| `STOP_CONSUME_WATER_LOOP = 0` | sample_queue_controller.h:72 | 停止消费水位线 0μs |
| `START_PRODUCE_WATER_LOOP = 5 * 1000 * 1000` | sample_queue_controller.h:73 | 启动生产水位线 5μs |
| `STOP_PRODUCE_WATER_LOOP = 10 * 1000 * 1000` | sample_queue_controller.h:74 | 停止生产水位线 10μs |
| `FIRST_START_CONSUME_WATER_LOOP = 2 * 1000 * 1000` | sample_queue_controller.h:75 | 首次启动消费水位线 2μs（预缓冲更快启动） |

### sample_queue_controller.cpp (300 行)

| 符号 | 位置 | 说明 |
|------|------|------|
| `SampleQueueController::SetSpeed(float speed)` | sample_queue_controller.cpp:168 | 设置播放倍速（快放 2x/4x / 慢放 0.5x） |
| `SampleQueueController::GetSpeed()` | sample_queue_controller.cpp:173 | 获取当前速度 |
| `SampleQueueController::ProduceIncrementFrameCount` | sample_queue_controller.cpp:178 | 生产端帧计数（ReadLoop 入队列时） |
| `SampleQueueController::ProduceOnEventTimeRecord` | sample_queue_controller.cpp:187 | 生产端事件时间记录 |
| `SampleQueueController::ConsumeSpeed` | sample_queue_controller.cpp:196 | 消费端速率统计（SampleConsumerLoop 出队列时） |
| `SampleQueueController::ShouldStartConsume` | sample_queue_controller.cpp:（待补充） | 队列大小 ≥ START_CONSUME_WATER_LOOP 时启动 ReadLoop |
| `SampleQueueController::ShouldStopConsume` | sample_queue_controller.cpp:（待补充） | 队列大小 ≤ STOP_CONSUME_WATER_LOOP 时停止 ReadLoop |
| `SampleQueueController::ShouldStartProduce` | sample_queue_controller.cpp:（待补充） | 队列大小 ≤ START_PRODUCE_WATER_LOOP 时启动 SampleConsumerLoop |
| `SampleQueueController::ShouldStopProduce` | sample_queue_controller.cpp:（待补充） | 队列大小 ≥ STOP_PRODUCE_WATER_LOOP 时停止 SampleConsumerLoop |
| `SampleQueueController::CheckWaterLineStopProduce` | sample_queue_controller.cpp:（待补充） | 水位线阈值检查 |
| `SampleQueueController::CheckWaterLineStartConsume` | sample_queue_controller.cpp:（待补充） | 水位线阈值检查 |
| `SpeedCountInfo::GetCurrentTimeUs()` | sample_queue_controller.cpp:257 | 微秒级时间戳 |
| `SpeedCountInfo::IncrementFrameCount()` | sample_queue_controller.cpp:264 | 原子递增 totalFrameCount |
| `SpeedCountInfo::OnEventTimeRecord()` | sample_queue_controller.cpp:269 | 更新 lastEventTimeUs 和 totalEffectiveRunTimeUs |
| `SpeedCountInfo::GetSpeed()` | sample_queue_controller.cpp:280 | 计算速率 = totalFrameCount / totalEffectiveRunTimeUs |

## 架构定位

```
MediaDemuxer (6012行主引擎)
    ├── ReadLoop TaskThread（生产端）
    │       ├── SampleQueue::PushBuffer (入队列)
    │       └── SampleQueueController::ShouldStartConsume / ShouldStopConsume
    │
    ├── SampleConsumerLoop TaskThread（消费端）
    │       ├── SampleQueue::PopBuffer (出队列)
    │       └── SampleQueueController::ShouldStartProduce / ShouldStopProduce
    │
    └── SampleQueueController (流控引擎) ← S102
            ├── 双路 SpeedCountInfo (produce/consume per trackId)
            ├── 四 WaterLine 阈值 (5μs/0/5μs/10μs)
            ├── CheckWaterLineStartConsume / CheckWaterLineStopProduce
            └── SetSpeed / GetSpeed (快放/慢放倍速)
```

## 核心设计

### 1. SpeedCountInfo 双路统计

每个 trackId 独立维护生产端和消费端两个 `SpeedCountInfo` 实例：

```cpp
// sample_queue_controller.h:79-80
std::map<int32_t, std::shared_ptr<SpeedCountInfo>> produceSpeedCountInfo_;
std::map<int32_t, std::shared_ptr<SpeedCountInfo>> consumeSpeedCountInfo_;
```

**速率计算公式**：`GetSpeed() = totalFrameCount / totalEffectiveRunTimeUs`（帧/微秒）

**典型场景**：
- consumeSpeed < produceSpeed → 消费追不上生产 → 触发码率切换（BitrateSwitch）
- produceSpeed < consumeSpeed → 生产追不上消费 → 可能触发卡顿

### 2. WaterLine 双水位线机制

四阈值控制 TaskThread 启停：

| 阈值 | 值 | 作用 |
|------|------|------|
| START_CONSUME_WATER_LOOP | 5μs | ReadLoop 启动水位线（队列≥5μs 才开始消费） |
| STOP_CONSUME_WATER_LOOP | 0μs | ReadLoop 停止水位线（队列空则停止） |
| START_PRODUCE_WATER_LOOP | 5μs | SampleConsumerLoop 启动水位线 |
| STOP_PRODUCE_WATER_LOOP | 10μs | SampleConsumerLoop 停止水位线（队列积压≥10μs 则停止生产，防止内存溢出） |

**FIRST_START_CONSUME_WATER_LOOP = 2μs**：首次启动时使用更低的 2μs 水位线，使首次缓冲更快

### 3. SetSpeed 倍速控制

```cpp
// sample_queue_controller.cpp:168
void SampleQueueController::SetSpeed(float speed) {
    speed_.store(speed, std::memory_order_relaxed);
}
```

支持 0.5x（慢放）、1x（正常）、2x/4x（快放）等场景，speed_ 影响 consumeSpeed 统计和 GetBufferingDuration 计算。

## 关键设计决策

1. **双路独立统计**：生产端和消费端独立统计，避免互相干扰；用 `std::map<int32_t, shared_ptr<SpeedCountInfo>>` 支持多轨
2. **μs 级精度**：所有时间用微秒而非毫秒，避免高速场景下精度丢失
3. **STOP_PRODUCE_WATER_LOOP > START_PRODUCE_WATER_LOOP**： hysteresis 防止震荡（10μs > 5μs）
4. **FIRST_START_CONSUME_WATER_LOOP < START_CONSUME_WATER_LOOP**：首次预缓冲时更快启动消费，提升首帧速度
5. **QUEUE_SIZE_MIN = 30**：防止队列过小导致频繁启停

## 流控决策流程

```
SampleQueueController::ShouldStartConsume(trackId, sampleQueue, task):
    if (队列持续时间 >= START_CONSUME_WATER_LOOP):
        task->Start()  // 启动 ReadLoop

SampleQueueController::ShouldStopConsume(trackId, sampleQueue, task):
    if (队列持续时间 <= STOP_CONSUME_WATER_LOOP):
        task->Stop()  // 停止 ReadLoop

SampleQueueController::ShouldStartProduce(trackId, sampleQueue, task):
    if (队列持续时间 <= START_PRODUCE_WATER_LOOP):
        task->Start()  // 启动 SampleConsumerLoop

SampleQueueController::ShouldStopProduce(trackId, sampleQueue, task):
    if (队列持续时间 >= STOP_PRODUCE_WATER_LOOP):
        task->Stop()  // 停止 SampleConsumerLoop
```

## 关联场景

- 新需求开发：流控参数调优（调整 WaterLine 阈值适配不同设备）、倍速播放（SetSpeed 2x/4x/0.5x）
- 问题定位：播放卡顿（consumeSpeed < produceSpeed）、内存积压（STOP_PRODUCE_WATER_LOOP 太低导致生产过旺）、首帧慢（FIRST_START_CONSUME_WATER_LOOP 调整）
- 流媒体自适应码率：ConsumeSpeed 统计驱动 BitrateSwitch 三状态机
