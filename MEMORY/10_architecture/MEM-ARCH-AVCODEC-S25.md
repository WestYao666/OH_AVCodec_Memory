---
type: architecture
id: MEM-ARCH-AVCODEC-S25
status: pending_approval
topic: AdaptiveFramerateController 自适应帧率控制器——FramerateCalculator 动态降帧算法与CodecServer集成
submitted_at: "2026-04-25T02:51:00+08:00"
evidence: |
  - source: services/services/common/adaptive_framerate_controller/adaptive_framerate_controller.h
    lines: 35-54
    anchor: "AdaptiveFramerateController::GetInstance() singleton, Add/Remove/Loop, FramerateCalculator"
  - source: services/services/common/adaptive_framerate_controller/adaptive_framerate_controller.cpp
    lines: 20-25
    anchor: "CHECK_INTERVAL=1000ms, MIN_FRAMERATE=1.0, DEFAULT_FRAMERATE=60, MAX_INCREASE/DECREASE_CHECK_TIMES=1/2"
  - source: services/services/common/adaptive_framerate_controller/adaptive_framerate_controller.cpp
    lines: 50-78
    anchor: "FramerateCalculator::CheckAndResetFramerate() 完整降帧算法: fluctuationFramerate>5 && ratio>0.1, 升帧×2.5 factor, increseCheckTimes_/decreseCheckTimes_ 防抖"
  - source: services/services/common/adaptive_framerate_controller/adaptive_framerate_controller.cpp
    lines: 120-140
    anchor: "AdaptiveFramerateController::Loop() pthread_setname_np(\"OS_AFC_Loop\"), 每1000ms轮询, 自动停止条件: calculators_.empty()"
  - source: services/services/common/adaptive_framerate_controller/adaptive_framerate_controller.cpp
    lines: 95-118
    anchor: "AdaptiveFramerateController::Add() 惰性创建looper_线程, Remove() calculators_空时join()并reset() looper_"
  - source: services/services/codec/server/video/codec_server.cpp
    lines: 861-877
    anchor: "framerateCalculator_ = std::make_shared<FramerateCalculator>(instanceId_, isEnc, handler); SetSpeedAndFpsCallback 注册降帧回调"
  - source: services/services/codec/server/video/codec_server.cpp
    lines: 768-777
    anchor: "每帧完成 OnFrameConsumed(pts)，触发 FramerateCalculator 帧计数"
  - source: services/services/codec/server/video/codec_server.cpp
    lines: 1680-1691
    anchor: "停止时 SetFramerate2ConfiguredFramerate() 恢复原始帧率"
  - source: services/services/common/adaptive_framerate_controller/decoding_behavior_analyzer.h
    lines: 30-50
    anchor: "DecodingBehaviorType: UNKNOWN/UNIFORM_SPEED/NON_UNIFORM_SPEED, SpeedStats, MatchAndUpdateSpeedStats"
---

# MEM-ARCH-AVCODEC-S25: AdaptiveFramerateController 自适应帧率控制器

## Metadata

| 字段 | 值 |
|------|-----|
| id | MEM-ARCH-AVCODEC-S25 |
| title | AdaptiveFramerateController 自适应帧率控制器——FramerateCalculator 动态降帧算法与CodecServer集成 |
| scope | [AVCodec, AdaptiveFramerate, FramerateCalculator, CodecServer, AFC, DynamicFramerate] |
| status | draft |
| created_by | builder-agent |
| created_at | 2026-04-25T02:51 |
| type | architecture_fact |
| confidence | high |
| related_scenes | [新需求开发, 问题定位, 自适应帧率, 动态降帧, Pipeline调优, 播放流畅度] |

## 摘要

AdaptiveFramerateController（AFC）是 AVCodec 的**全局帧率自适应控制器**，以单例模式运行。
当检测到 Codec 实例帧消费变慢时，自动触发降帧回调，以减少硬件负担、避免卡顿。
CodecServer 持有 FramerateCalculator 实例，通过 SetSpeedAndFpsCallback 注册降速回调，实现编码器帧率的动态调节。

## 关键常量（来源证据）

```
adaptive_framerate_controller.cpp:20-25
  CHECK_INTERVAL = 1000ms        // AFC Loop 检测间隔
  MIN_FRAMERATE = 1.0           // 最低帧率（不可继续降）
  DEFAULT_FRAMERATE = 60        // 默认目标帧率
  MAX_INCREASE_CHECK_TIMES = 1  // 升帧连续确认次数
  MAX_DECREASE_CHECK_TIMES = 2  // 降帧连续确认次数
  afcEnable = GetBoolParameter("persist.OHOS.MediaAVCodec.AFC.Enable", true)
  allowLowFps = GetBoolParameter("persist.OHOS.MediaAVCodec.AFC.AllowLowFps.Enable", true)
```

## 关键类与接口

### AdaptiveFramerateController（AFC 单例）
- **文件**: `services/services/common/adaptive_framerate_controller/adaptive_framerate_controller.h`
- **性质**: 单例（`GetInstance()` 返回引用，后台线程运行）
- **核心方法**:
  - `Add(instanceId, calculator)` — 注册 FramerateCalculator 实例
  - `Remove(instanceId)` — 注销
  - `Loop()` — 后台线程，每 `CHECK_INTERVAL`(1000ms) 轮询所有 calculator 的 `CheckAndResetFramerate()`

### FramerateCalculator（按 Codec 实例）
- **性质**: 非单例，每个 Codec 实例持有一个 `shared_ptr`
- **构造**: `FramerateCalculator(instanceId, isEnc, handler)` — isEnc 区分编码/解码
- **核心方法**:
  - `OnFrameConsumed(pts)` — 每帧处理完成时调用；首次调用时注册到 AFC 并置 status_=RUNNING
  - `CheckAndResetFramerate()` — 检查是否需要动态调整帧率
  - `SetConfiguredFramerate(fps)` — 设置目标帧率（默认60fps）
  - `SetSpeedAndFpsCallback(cb)` — 注册 (speed, decFps) 回调，AFC 触发降帧时调用
  - `SetFramerate2ConfiguredFramerate()` — 停止时恢复原始帧率
  - `Register2AFC() / UnregisterFromAFC()` — 注册/注销到 AFC 单例
- **内部状态**: `Status { INITIALIZED → RUNNING → STOPPED }`

### DecodingBehaviorAnalyzer（解码行为分析）
- **文件**: `services/services/common/adaptive_framerate_controller/decoding_behavior_analyzer.h`
- **行为类型**:
  - `UNKNOWN` — 初始未确定
  - `UNIFORM_SPEED` — 稳定倍速播放（如 0.75x, 1.0x, 1.25x, 1.5x, 2.0x, 3.0x, 4.0x）
  - `NON_UNIFORM_SPEED` — 变速、超高速、切换中等场景
- **标准速度等级**: 8级（`stdSpeedLevels=8`）
  - `standardSpeeds = {0.0, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 4.0}`
- **核心方法**:
  - `OnFrameConsumed(pts)` — 帧消费事件
  - `OnChecked(double decFps)` — FPS检测
  - `SetCallback(cb)` — 设置 speed/fps 回调

## CodecServer 集成链路（来源证据）

```
codec_server.cpp:861
  framerateCalculator_ = std::make_shared<FramerateCalculator>(instanceId_, isEnc, handler);

codec_server.cpp:873-877
  framerateCalculator_->SetSpeedAndFpsCallback([weakThis](double speed, double decFps) {
      // speed: 播放倍速
      // decFps: 实际解码帧率
  });

codec_server.cpp:768-777
  if (framerateCalculator_ && status_ == RUNNING) {
      framerateCalculator_->OnFrameConsumed(pts);   // 每帧完成时调用
  }

codec_server.cpp:1680-1691
  // 停止时恢复原始帧率
  framerateCalculator_->OnStopped();
  framerateCalculator_->SetFramerate2ConfiguredFramerate();
```

## 数据流

```
CodecServer 构造
  → 创建 FramerateCalculator(instanceId, isEnc, resetHandler)
  → AdaptiveFramerateController::GetInstance().Add(instanceId, calculator)
  → AFC 后台 Loop 线程启动（每 1000ms 轮询）

运行时每帧完成:
  → OnFrameConsumed(pts)
  → behaviorAnalyzer_->OnFrameConsumed(pts)（解码器）
  → frameCount_++
  → AFC Loop 调用 CheckAndResetFramerate()
  → 检测到帧率下降 → 触发 SetSpeedAndFpsCallback(speed, decFps)
  → CodecServer 收到回调，调整编码器参数
  → 降帧生效，硬件负载降低

停止时:
  → FramerateCalculator::OnStopped()
  → UnregisterFromAFC()
  → SetFramerate2ConfiguredFramerate() 恢复原始帧率
```

## 状态机

### FramerateCalculator Status
```
INITIALIZED ──(首帧OnFrameConsumed)──► RUNNING ──(OnStopped)──► STOPPED
```
- `INITIALIZED`: Calculator 创建完成，待首次帧消费
- `RUNNING`: 已注册，AFC Loop 持续监测
- `STOPPED`: 实例停止，Unregister 后进入 STOPPED

### AdaptiveFramerateController 线程状态
```
!isRunning_(初始) → isRunning_=true(Add后) → Loop线程持续运行 → Remove全部后退出
```

## 降帧算法详解（来源证据）

```cpp
// adaptive_framerate_controller.cpp:50-78
bool FramerateCalculator::CheckAndResetFramerate()
{
    auto frameCount = frameCount_.exchange(0);    // 原子交换，统计CHECK_INTERVAL内的帧数
    auto elapsedTime = ...milliseconds(now - lastAdjustmentTime_); // 经过的时间
    auto actualFramerate = frameCount / elapsedTime * 1000;       // 实际帧率 fps

    // 抖动过滤：actual与last差距<5fps 且 比例<10% → 不调整
    if (!(fluctuationFramerate > 5 && (fluctuationFramerate / lastFramerate_ > 0.1))) {
        decreseCheckTimes_ = MAX_DECREASE_CHECK_TIMES; // 重置计数器
        increseCheckTimes_ = MAX_INCREASE_CHECK_TIMES;
        return false;
    }

    // 升帧（actual > last）：2.5倍放大factor，increseCheckTimes_确认后才真正升
    if (actualFramerate > lastFramerate_) {
        if (actualFramerate <= configuredFramerate_) {
            resetFramerate = configuredFramerate_;  // 不超过配置帧率
        } else if (increseCheckTimes_ > 0) {
            increseCheckTimes_--;
            return false;  // 未达确认次数，继续观察
        } else {
            resetFramerate = actualFramerate * 2.5;  // 激进升帧
        }
    }
    // 降帧（actual < last）：decreseCheckTimes_=2次确认后才降
    resetFramerateHandler_(resetFramerate);  // 触发回调
}
```

### 关键防抖机制

| 场景 | 确认次数 | 说明 |
|------|---------|------|
| 降帧触发 | `MAX_DECREASE_CHECK_TIMES=2` | 连续2次检测到帧率下降才真正降帧 |
| 升帧触发 | `MAX_INCREASE_CHECK_TIMES=1` | 1次确认即升帧 |
| 抖动过滤 | `fluctuationFramerate>5 && ratio>0.1` | 波动<5fps或<10%时不调整 |

### AFC Loop 线程（来源证据）

```cpp
// adaptive_framerate_controller.cpp:120-140
void AdaptiveFramerateController::Loop() {
    pthread_setname_np(pthread_self(), "OS_AFC_Loop");  // 线程名
    while (true) {
        condition_.wait_for(signalLock, CHECK_INTERVAL, [this]() { return !isRunning_; });
        if (!isRunning_) break;
        for (auto& [id, calculator] : calculators_) {
            if (auto calc = calculator.lock()) {
                calc->CheckAndResetFramerate();  // 驱动所有实例
            }
        }
        if (calculators_.empty()) {  // 空队列自动退出
            isRunning_ = false;
            break;
        }
    }
}
```

### AFC Add/Remove 生命周期（来源证据）

```cpp
// Add: 惰性创建looper_线程
void AdaptiveFramerateController::Add(int32_t intanceId, shared_ptr<FramerateCalculator> calc) {
    calculators_[intanceId] = calc;
    if (!isRunning_) {
        isRunning_ = true;
        if (!looper_) {
            looper_ = make_unique<thread>(&AFC::Loop, this);  // 首次Add时创建线程
        }
    }
}

// Remove: 全部移除后join()并reset() looper_
void AdaptiveFramerateController::Remove(int32_t instanceId) {
    calculators_.erase(instanceId);
    if (calculators_.empty()) {
        isRunning_ = false;
        condition_.notify_all();  // 唤醒Loop退出
        if (looper_->joinable()) looper_->join();
        looper_.reset();  // 重置，下次Add重新创建
    }
}
```

## 系统参数（运行时开关）

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `persist.OHOS.MediaAVCodec.AFC.Enable` | true | 全局 AFC 功能开关 |
| `persist.OHOS.MediaAVCodec.AFC.AllowLowFps.Enable` | true | 是否允许降至 MIN_FRAMERATE(1fps) |

## 与其他组件的关系

| 组件 | 关系 | 说明 |
|------|------|------|
| CodecServer | 持有者 | framerateCalculator_ 是 CodecServer 成员 |
| VideoEncoderBase | 下游 | CodecServer 通过 framerateCalculator 动态调其帧率 |
| MediaCodec (API层) | 上层 | 通过 MediaCodec → CodecServer → AFC 影响帧率 |
| AdaptiveFramerateController | 单例全局 | 所有 Codec 实例共享一个 AFC 单例 |
| DecodingBehaviorAnalyzer | 内部依赖 | 仅解码器使用，分析播放速度行为并决定是否降帧 |

## 已有记忆关联

- **MEM-ARCH-AVCODEC-S3**: CodecServer Pipeline 数据流与状态机（AFC 作为 CodecServer 成员，S3 中仅一笔带过 framerateCalculator_）
- **MEM-ARCH-AVCODEC-006**: media_codec 编解码数据流（CodecServer 是 Pipeline 核心，AFC 影响其运行时帧率表现）
- **MEM-ARCH-AVCODEC-S1**: codec_server.cpp 所承载的能力（CodecServer 对 AFC 的委托关系）
- **MEM-ARCH-AVCODEC-S17**: SmartFluencyDecoding 智能流畅解码（与 AFC 类似，同属帧率/流畅度调控，但 AFC 面向编码器，SmartFluency 面向解码器丢帧策略）

## Builder 注（2026-04-25T02:51）

- S25 由 builder-agent 基于 S13 draft 内容增强注册（orphan draft → S25 正式注册）
- S13 原文件同步保留，S25 作为本次审批队列唯一编号
- evidence 源自 openharmony multimedia_av_codec 仓库实际源码分析
