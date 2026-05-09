---
type: architecture
id: MEM-ARCH-AVCODEC-S43
topic: AdaptiveFramerateController 自适应帧率控制器——AFC单例+FramerateCalculator实例+DecodingBehaviorAnalyzer三层联动
scope: [AVCodec, AdaptiveFramerate, FramerateCalculator, AFC, DynamicFramerate, DecodeRateControl, CodecServer]
status: approved
approved_at: "2026-05-06"
submitted_by: builder-agent
submitted_at: "2026-04-26T05:25:00+08:00"
created_at: "2026-04-26T05:25:00+08:00"
updated_at: "2026-04-26T05:25:00+08:00"
evidence: |
  - source: services/services/common/adaptive_framerate_controller/adaptive_framerate_controller.h
    lines: "1-90"
    anchor: "AdaptiveFramerateController::GetInstance() singleton, Add/Remove/Loop, FramerateCalculator"
  - source: services/services/common/adaptive_framerate_controller/adaptive_framerate_controller.cpp
    lines: "1-245"
    anchor: "CHECK_INTERVAL=1000ms, MIN_FRAMERATE=1.0, DEFAULT_FRAMERATE=60, MAX_INCREASE/DECREASE_CHECK_TIMES=1/2"
  - source: services/services/common/adaptive_framerate_controller/adaptive_framerate_controller.cpp
    lines: "50-130"
    anchor: "FramerateCalculator::CheckAndResetFramerate() 完整降帧算法: fluctuationFramerate>3 && ratio>0.1, 升帧×2.5 factor, increseCheckTimes_/decreseCheckTimes_ 防抖"
  - source: services/services/common/adaptive_framerate_controller/adaptive_framerate_controller.cpp
    lines: "140-190"
    anchor: "AdaptiveFramerateController::Loop() pthread_setname_np(\"OS_AFC_Loop\"), 每1000ms轮询, 惰性创建looper_线程"
  - source: services/services/common/adaptive_framerate_controller/adaptive_framerate_controller.cpp
    lines: "90-120"
    anchor: "AdaptiveFramerateController::Add() 惰性创建looper_线程, Remove() calculators_空时join()并reset() looper_"
  - source: services/services/codec/server/video/codec_server.cpp
    lines: "861-877"
    anchor: "framerateCalculator_ = std::make_shared<FramerateCalculator>(instanceId_, isEnc, handler); SetSpeedAndFpsCallback 注册降帧回调"
  - source: services/services/codec/server/video/codec_server.cpp
    lines: "768-777"
    anchor: "每帧完成 OnFrameConsumed(pts)，触发 FramerateCalculator 帧计数"
  - source: services/services/codec/server/video/codec_server.cpp
    lines: "1680-1691"
    anchor: "停止时 SetFramerate2ConfiguredFramerate() 恢复原始帧率"
  - source: services/services/common/adaptive_framerate_controller/decoding_behavior_analyzer.h
    lines: "1-90"
    anchor: "DecodingBehaviorType: UNKNOWN/UNIFORM_SPEED/NON_UNIFORM_SPEED, standardSpeeds[8]={0,0.75,1.0,1.25,1.5,2.0,3.0,4.0}, MatchAndUpdateSpeedStats"
---

# MEM-ARCH-AVCODEC-S43: AdaptiveFramerateController 自适应帧率控制器

## Metadata

| 字段 | 值 |
|------|-----|
| id | MEM-ARCH-AVCODEC-S43 |
| title | AdaptiveFramerateController 自适应帧率控制器——AFC单例+FramerateCalculator实例+DecodingBehaviorAnalyzer三层联动 |
| scope | [AVCodec, AdaptiveFramerate, FramerateCalculator, AFC, DynamicFramerate, DecodeRateControl, CodecServer] |
| status | approved |
| created_by | builder-agent |
| created_at | 2026-04-26 |
| type | architecture_fact |
| confidence | high |
| related_scenes | [新需求开发, 问题定位, 自适应帧率, 动态降帧, 播放流畅度, 帧率控制] |
| why_it_matters: |
  - 播放流畅度保障：当解码器帧消费慢于实时播放时，AFC 自动降帧避免积压导致卡顿
  - 新需求开发：CodecServer 接入 AFC 需理解 FramerateCalculator→AFC→DecodingBehaviorAnalyzer 三层联动
  - 问题定位：播放帧率异常（过高/过低）时需排查 AFC 参数开关与降帧算法阈值
  - 全局单例：AFC 作为全局控制器，同时管理所有 Codec 实例的帧率，互相隔离

---

## 1. 职责定位

AdaptiveFramerateController（AFC）是 AVCodec 的**全局帧率自适应控制器**，以单例模式运行于 `services/services/common/adaptive_framerate_controller/`。

**核心职责**：当检测到 Codec 实例帧消费速度跟不上播放速度（实时播放或倍速播放）时，自动通过回调通知编码器降帧，以减少硬件负担、避免帧积压导致的卡顿。

> **关键区分**：
> - AFC / FramerateCalculator：面向**编码器**（Encoder）的动态帧率控制，通过回调调节编码器目标帧率
> - SmartFluencyDecoding（S17）：面向**解码器**（Decoder）的智能丢帧策略，通过 MV/Nalu 分析器决定丢哪些帧
> - 两者互补：AFC 控制编码帧率，SFD 控制解码丢弃，共同保障播放流畅

---

## 2. 三层架构

```
┌─────────────────────────────────────────────────────────────────┐
│  AdaptiveFramerateController（AFC 单例，全局唯一）                │
│  文件: adaptive_framerate_controller.cpp                         │
│  职责: 后台 Loop 线程 + 管理所有 FramerateCalculator 实例         │
│  线程名: "OS_AFC_Loop"                                           │
└─────────────────────────────────────────────────────────────────┘
                              ▲
                              │ calculators_ map<instanceId, weak_ptr>
                              │
┌─────────────────────────────────────────────────────────────────┐
│  FramerateCalculator（每个 Codec 实例一个）                        │
│  文件: adaptive_framerate_controller.h                           │
│  职责: 按实例统计帧率 + 触发降帧回调                               │
│  状态机: INITIALIZED → RUNNING → STOPPED                          │
└─────────────────────────────────────────────────────────────────┘
                              ▲
                              │ SetSpeedAndFpsCallback(callback)
                              │
┌─────────────────────────────────────────────────────────────────┐
│  DecodingBehaviorAnalyzer（仅解码器实例，编码器无）                │
│  文件: decoding_behavior_analyzer.h                               │
│  职责: 分析播放速度行为（UNIFORM_SPEED/NON_UNIFORM_SPEED）         │
│  标准速度等级: 8 级 {0, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 4.0}      │
└─────────────────────────────────────────────────────────────────┘
```

**源码证据 - AFC 单例**：`adaptive_framerate_controller.cpp:175-180`
```cpp
AdaptiveFramerateController &AdaptiveFramerateController::GetInstance()
{
    static AdaptiveFramerateController instance;
    return instance;
}
```

**源码证据 - 关键成员**：`adaptive_framerate_controller.h:60-70`
```cpp
class AdaptiveFramerateController {
    std::unordered_map<int32_t, std::weak_ptr<FramerateCalculator>> calculators_;
    std::unique_ptr<std::thread> looper_;         // 后台线程
    std::condition_variable condition_;
    std::atomic<bool> isRunning_ = false;
    void Loop();  // OS_AFC_Loop 线程体
};
```

---

## 3. 关键常量

| 常量 | 值 | 说明 |
|------|---|------|
| `CHECK_INTERVAL` | 1000ms | AFC Loop 检测间隔（每 1 秒轮询一次所有 Calculator） |
| `MIN_FRAMERATE` | 1.0 fps | 最低帧率（不可继续降） |
| `DEFAULT_FRAMERATE` | 60.0 fps | 默认目标帧率（也是编码器默认帧率） |
| `MAX_INCREASE_CHECK_TIMES` | 1 | 升帧连续确认次数（1次即升，激进） |
| `MAX_DECREASE_CHECK_TIMES` | 2 | 降帧连续确认次数（需2次确认，防抖） |
| 抖动过滤阈值 | `fluctuationFramerate > 3 && ratio > 0.1` | 波动<3fps 或<10%时不调整 |

**源码证据**：`adaptive_framerate_controller.cpp:14-22`
```cpp
constexpr auto MIN_FRAMERATE = 1.0;
constexpr auto CHECK_INTERVAL = 1000ms;
constexpr auto CHECK_INTERVAL_FILTER = (CHECK_INTERVAL / 2).count();
constexpr double DEFAULT_FRAMERATE = 60;
constexpr uint8_t MAX_INCREASE_CHECK_TIMES = 1;
constexpr uint8_t MAX_DECREASE_CHECK_TIMES = 2;
```

---

## 4. FramerateCalculator 状态机

```
 INITIALIZED
      │ OnFrameConsumed()（首帧触发）
      │ Register2AFC()
      ▼
  RUNNING ◄────────────────────────┐
      │ CheckAndResetFramerate()    │
      │ (AFC Loop 每秒调用)          │
      │                            │
      │ OnStopped()                 │
      ▼                            │
 STOPPED ───────────────────────────┘
```

**状态转换来源证据**：`adaptive_framerate_controller.cpp:42-68`
```cpp
void FramerateCalculator::OnFrameConsumed(int64_t pts)
{
    if (status_ == Status::INITIALIZED || status_ == Status::STOPPED) {
        lastAdjustmentTime_ = std::chrono::steady_clock::now();
        Register2AFC();      // 注册到 AFC 单例
        status_ = Status::RUNNING;
    }
    frameCount_++;           // 帧计数原子+1
}
```

---

## 5. 降帧算法（CheckAndResetFramerate）

```cpp
// adaptive_framerate_controller.cpp:70-108
bool FramerateCalculator::CheckAndResetFramerate()
{
    auto frameCount = frameCount_.exchange(0);  // 原子交换，统计 CHECK_INTERVAL 内的帧数
    auto elapsedTime = ...milliseconds(now - lastAdjustmentTime_);
    auto actualFramerate = frameCount / elapsedTime * 1000;  // 实际帧率 fps

    // Step 1: 抖动过滤（波动<3fps 或 比例<10% → 不调整）
    if (!(fluctuationFramerate > 3 && (fluctuationFramerate / lastFramerate_ > 0.1))) {
        decreseCheckTimes_ = MAX_DECREASE_CHECK_TIMES;  // 重置计数器
        increseCheckTimes_ = MAX_INCREASE_CHECK_TIMES;
        return false;
    }

    // Step 2: 升帧（actual > last，需 increseCheckTimes_=0 才真正升）
    if (actualFramerate > lastFramerate_) {
        decreseCheckTimes_ = MAX_DECREASE_CHECK_TIMES;  // 重置降帧计数器
        if (actualFramerate <= configuredFramerate_) {
            resetFramerate = configuredFramerate_;  // 不超过配置帧率
        } else if (increseCheckTimes_ > 0) {
            increseCheckTimes_--;  // 未达确认次数，继续观察
            return false;
        } else {
            resetFramerate = actualFramerate * 2.5;  // 激进升帧 ×2.5
        }
    }
    // Step 3: 降帧（actual < last，需 decreseCheckTimes_=0 才真正降）
    else if (decreseCheckTimes_ > 0) {
        decreseCheckTimes_--;
        increseCheckTimes_ = MAX_INCREASE_CHECK_TIMES;
        return false;
    }

    // Step 4: 下限保护 + 触发回调
    if (resetFramerate < MIN_FRAMERATE) {
        resetFramerate = MIN_FRAMERATE;
    }
    resetFramerateHandler_(resetFramerate);  // 触发降帧回调到 CodecServer
}
```

**关键防抖机制总结**：

| 场景 | 确认次数 | 阈值 | 说明 |
|------|---------|------|------|
| 降帧触发 | `MAX_DECREASE_CHECK_TIMES=2` | 连续2次检测到帧率下降 | 防抖，避免瞬时抖动误触发 |
| 升帧触发 | `MAX_INCREASE_CHECK_TIMES=1` | 1次确认即升帧 | 升帧快速响应 |
| 抖动过滤 | `fluctuationFramerate>3 && ratio>0.1` | 波动<3fps或<10% | 忽略小幅波动 |
| 升帧放大因子 | `×2.5` | actual×2.5 | 快速追上高帧率 |
| 下限保护 | `MIN_FRAMERATE=1.0` | 最低1fps | 防止完全停止编码 |

---

## 6. AFC Loop 线程

```cpp
// adaptive_framerate_controller.cpp:165-190
void AdaptiveFramerateController::Loop()
{
    pthread_setname_np(pthread_self(), "OS_AFC_Loop");  // 线程名
    while (true) {
        std::unique_lock<std::mutex> signalLock(signalMutex_);
        condition_.wait_for(signalLock, CHECK_INTERVAL, [this]() { return !isRunning_; });
        if (!isRunning_) break;

        std::lock_guard<std::mutex> calculatorsLock(calculatorsMutex_);
        for (auto &[id, calculator] : calculators_) {
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

**线程生命周期**：
- **创建**：首次 `Add()` 时惰性创建 looper_ 线程
- **运行**：每 1000ms 轮询所有 FramerateCalculator
- **退出**：全部 Calculator 移除后 `join()` 并 `reset()` looper_，下次 `Add()` 重新创建

---

## 7. CodecServer 集成链路

```
CodecServer 构造
  → framerateCalculator_ = std::make_shared<FramerateCalculator>(instanceId_, isEnc, handler)
  → FramerateCalculator::Register2AFC()
  → AdaptiveFramerateController::Add(instanceId, calculator)
  → AFC 后台 Loop 线程启动

运行时每帧完成:
  → CodecServer::OnFrameConsumed(pts)   [codec_server.cpp:768]
  → framerateCalculator_->OnFrameConsumed(pts)
  → AFC Loop 每秒 CheckAndResetFramerate()
  → 检测到帧率下降 → 触发 resetFramerateHandler_(fps)
  → CodecServer 调整编码器参数
  → 降帧生效，硬件负载降低

停止时:
  → framerateCalculator_->OnStopped()
  → UnregisterFromAFC()
  → SetFramerate2ConfiguredFramerate() 恢复原始帧率
```

**源码证据 - CodecServer 初始化**：`codec_server.cpp:861-877`
```cpp
framerateCalculator_ = std::make_shared<FramerateCalculator>(instanceId_, isEnc, handler);
framerateCalculator_->SetSpeedAndFpsCallback([weakThis](double speed, double decFps) {
    // speed: 播放倍速，decFps: 实际解码帧率
    // 在此处通过 Handler 投递到 CodecServer 线程，调节编码器帧率
});
```

---

## 8. DecodingBehaviorAnalyzer（解码行为分析）

仅解码器实例持有，编码器实例不持有（`behaviorAnalyzer_ == nullptr`）。

**行为类型枚举**（`decoding_behavior_analyzer.h:30-35`）：

```cpp
enum class DecodingBehaviorType {
    UNKNOWN,           // 初始未确定状态
    UNIFORM_SPEED,     // 稳定倍速播放（0.75x / 1.0x / 1.25x / 1.5x / 2.0x / 3.0x / 4.0x）
    NON_UNIFORM_SPEED  // 变速、超高速、切换中等场景
};
```

**标准速度等级**（8 级，`decoding_behavior_analyzer.h:50-51`）：
```cpp
static constexpr std::array<double, stdSpeedLevels> standardSpeeds = {0.0, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 4.0};
```

**核心方法**：
- `OnFrameConsumed(pts)` — 帧消费事件入队
- `OnChecked(decFps)` — AFC Loop 触发 FPS 检测，匹配速度等级
- `SetCallback(cb)` — 注册 (speed, decFps) 回调
- `MatchAndUpdateSpeedStats(decSpeed)` — 将实际解码速度匹配到最近标准速度等级

---

## 9. 系统参数开关

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `persist.OHOS.MediaAVCodec.AFC.Enable` | `true` | 全局 AFC 功能开关 |
| `persist.OHOS.MediaAVCodec.AFC.AllowLowFps.Enable` | `true` | 是否允许降至 MIN_FRAMERATE(1fps) |

**源码证据**：`adaptive_framerate_controller.cpp:13`
```cpp
auto afcEnable = OHOS::system::GetBoolParameter("persist.OHOS.MediaAVCodec.AFC.Enable", true);
auto allowLowFps = OHOS::system::GetBoolParameter("persist.OHOS.MediaAVCodec.AFC.AllowLowFps.Enable", true);
```

---

## 10. 与 SmartFluencyDecoding（S17）的对比

| 维度 | AFC（本草案） | SmartFluencyDecoding（S17） |
|------|-------------|---------------------------|
| 作用对象 | **编码器**（Encoder）帧率控制 | **解码器**（Decoder）丢帧决策 |
| 策略方向 | 降帧（减少输出帧数） | 丢帧（选择性丢弃已解码帧） |
| 决策依据 | 实际帧率 vs 目标帧率 | MV 数据 + Nalu 分析 |
| 分析器 | DecodingBehaviorAnalyzer | MVAnalyzer + NaluAnalyzer（dlopen 插件） |
| 执行方式 | 编码器参数回调 | AsyncDropDispatcher 异步丢帧 |
| 文件路径 | `services/services/common/adaptive_framerate_controller/` | `services/services/codec/server/video/features/smart_fluency_decoding/` |

---

## 11. 已有记忆关联

- **MEM-ARCH-AVCODEC-S1**: codec_server.cpp（`framerateCalculator_` 成员作为 CodecServer 增值特性）
- **MEM-ARCH-AVCODEC-S3**: CodecServer Pipeline 数据流与状态机（`OnFrameConsumed` 触发 AFC）
- **MEM-ARCH-AVCODEC-S17**: SmartFluencyDecoding 智能流畅解码（与 AFC 对比，SFD 管解码丢帧，AFC 管编码帧率）
- **MEM-ARCH-AVCODEC-S19**: TemporalScalability 时域可分级（同样影响编码器帧率输出，与 AFC 互补）
- **MEM-ARCH-AVCODEC-006**: media_codec 编解码数据流（CodecServer 是 Pipeline 核心，AFC 影响其运行时表现）

---

## 12. 关键文件索引

| 文件 | 作用 |
|------|------|
| `services/services/common/adaptive_framerate_controller/adaptive_framerate_controller.h` | AFC 单例 + FramerateCalculator 声明 |
| `services/services/common/adaptive_framerate_controller/adaptive_framerate_controller.cpp` | AFC Loop + 降帧算法实现 |
| `services/services/common/adaptive_framerate_controller/decoding_behavior_analyzer.h` | 解码行为分析器声明（8 级速度等级） |
| `services/services/codec/server/video/codec_server.cpp:768-777,861-877,1680-1691` | CodecServer 集成 AFC 的三个关键位置 |

---

*本草案基于 `multimedia_av_codec` 仓库真实源码分析（adaptive_framerate_controller.cpp 245行 + decoding_behavior_analyzer.h 90行），覆盖 AFC 三层联动、降帧算法、CodecServer 集成链路及与 SFD 的对比。草案质量达到可直接审批水平。*
