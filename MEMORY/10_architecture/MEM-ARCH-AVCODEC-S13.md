---
type: architecture
id: MEM-ARCH-AVCODEC-S13
status: draft
topic: AdaptiveFramerateController 自适应帧率控制器——FramerateCalculator 动态降帧与CodecServer集成
created_at: "2026-04-24T00:07:00+08:00"
evidence: |
  - source: /home/west/av_codec_repo/services/services/common/adaptive_framerate_controller/adaptive_framerate_controller.h
    anchor: "AdaptiveFramerateController::Add / Remove / Loop, FramerateCalculator::OnFrameConsumed / CheckAndResetFramerate"
  - source: /home/west/av_codec_repo/services/services/codec/server/video/codec_server.cpp
    anchor: "framerateCalculator_->OnFrameConsumed / SetSpeedAndFpsCallback / SetConfiguredFramerate"
  - source: /home/west/av_codec_repo/services/services/common/adaptive_framerate_controller/adaptive_framerate_controller.cpp
    anchor: "AdaptiveFramerateController::GetInstance() singleton, Register2AFC / UnregisterFromAFC"
---

# MEM-ARCH-AVCODEC-S13: AdaptiveFramerateController 自适应帧率控制器

## Metadata

| 字段 | 值 |
|------|-----|
| id | MEM-ARCH-AVCODEC-S13 |
| title | AdaptiveFramerateController 自适应帧率控制器——FramerateCalculator 动态降帧与CodecServer集成 |
| scope | [AVCodec, DFX, AdaptiveFramerate, FramerateCalculator, Pipeline, CodecServer] |
| status | draft |
| created_by | builder-agent |
| created_at | 2026-04-24 |
| type | architecture_fact |
| confidence | high |
| related_scenes | [新需求开发, 问题定位, 自适应帧率, 动态降帧, Pipeline调优] |
| why_it_matters: |
  - 问题定位：视频播放时帧率异常波动（卡顿/掉帧），需排查 AdaptiveFramerateController 是否触发动态降帧
  - 新需求开发：自定义 Pipeline 接入时需决定是否启用帧率自适应、是否注册到 AFC
  - 性能分析：AFC 通过检测帧消费速率动态调整帧率，影响用户感知流畅度
  - CodecServer 集成：framerateCalculator_ 是 CodecServer 的成员变量，与编码器/解码器实例生命周期绑定

## 摘要

AdaptiveFramerateController（AFC）是 AVCodec 的**全局帧率自适应控制器**，以单例模式运行。
当检测到某些 Codec 实例帧消费（OnFrameConsumed）变慢时，自动触发降帧回调（speed/fps），以减少硬件负担、避免卡顿。
CodecServer 持有 FramerateCalculator 实例，通过 SetSpeedAndFpsCallback 注册降速回调，实现编码器帧率的动态调节。

## 关键类与接口

### AdaptiveFramerateController（AFC 单例）
- **文件**: `services/services/common/adaptive_framerate_controller/adaptive_framerate_controller.h`
- **性质**: 单例（`GetInstance()`）
- **核心方法**:
  - `Add(instanceId, calculator)` — 注册一个 Codec 实例的 FramerateCalculator
  - `Remove(instanceId)` — 注销
  - `Loop()` — 后台线程，持续监测各 calculator 状态

### FramerateCalculator
- **性质**: 非单例，每个 Codec 实例持有一个
- **构造**: `FramerateCalculator(instanceId, isEnc, handler)` — isEnc 区分编码/解码，handler 是降帧回调
- **核心方法**:
  - `OnFrameConsumed(pts)` — 每帧处理完成时调用，更新帧计数
  - `CheckAndResetFramerate()` — 检查是否需要重置帧率
  - `SetConfiguredFramerate(fps)` — 设置目标帧率（默认60fps）
  - `SetSpeedAndFpsCallback(cb)` — 注册 speed/fps 回调，AFC 触发降帧时调用
  - `Register2AFC() / UnregisterFromAFC()` — 注册/注销到 AFC 单例

### CodecServer 中的 AFC 集成
- **文件**: `services/services/codec/server/video/codec_server.cpp`
- **成员**: `framerateCalculator_`（`std::shared_ptr<FramerateCalculator>`）
- **初始化**: 在 CodecServer 构造或 Configure 阶段创建 calculator 并注册到 AFC
- **回调分发**: `SetSpeedAndFpsCallback([](double speed, double fps) { ... })` — 降帧触发时自动调用

## 数据流

```
CodecServer 实例化
  → 创建 FramerateCalculator(instanceId, isEnc,降帧回调)
  → AdaptiveFramerateController::GetInstance().Add(instanceId, calculator)
  → AFC 后台 Loop 线程启动

播放/编码运行时:
  → 每帧完成 OnFrameConsumed(pts)
  → FramerateCalculator 累加 frameCount_
  → AFC Loop 定期调用 CheckAndResetFramerate()
  → 检测到帧率下降 → 触发 SetSpeedAndFpsCallback(speed, fps)
  → CodecServer 收到回调，调整编码器帧率参数
  → 降帧生效，硬件负载降低

停止时:
  → FramerateCalculator::OnStopped()
  → UnregisterFromAFC() → AdaptiveFramerateController::Remove(instanceId)
```

## 状态机

### FramerateCalculator Status
```
INITIALIZED → RUNNING → STOPPED
```
- `INITIALIZED`: Calculator 创建完成，待 Register2AFC
- `RUNNING`: 已注册，Loop 线程开始监测帧率
- `STOPPED`: Codec 实例停止，Unregister 后进入 STOPPED

### AdaptiveFramerateController 线程状态
```
!isRunning_ (初始) → isRunning_=true (Add 后) → 线程 Loop() 持续运行 → Remove 全部后退出
```

## 与其他组件的关系

| 组件 | 关系 | 说明 |
|------|------|------|
| CodecServer | 持有者 | framerateCalculator_ 是 CodecServer 成员 |
| CodecBase (Video) | 下游 | CodecServer 通过 framerateCalculator 动态调其帧率 |
| MediaCodec (API层) | 上层 | 通过 MediaCodec → CodecServer → AFC 影响帧率 |
| AdaptiveFramerateController | 单例全局 | 所有 Codec 实例共享一个 AFC 单例 |
| FramerateCalculator | 按实例 | 每个 Codec 实例一个 Calculator |
| DecodingBehaviorAnalyzer | 内部依赖 | FramerateCalculator 持有，用于分析解码行为 |

## 已有记忆关联

- **MEM-ARCH-AVCODEC-S3**: CodecServer Pipeline 数据流与状态机（AFC 作为 CodecServer 成员，S3 中仅一笔带过 framerateCalculator_，本条目补全 AFC 机制）
- **MEM-ARCH-AVCODEC-006**: media_codec 编解码数据流（CodecServer 是 Pipeline 核心，AFC 影响其运行时帧率表现）
- **MEM-ARCH-AVCODEC-S1**: codec_server.cpp 所承载的能力（CodecServer 对 AFC 的委托关系）

## 待补充

- DecodingBehaviorAnalyzer 完整实现（用于判断降帧触发条件）
- AFC 降帧阈值配置（帧率低于多少触发，间隔多久重检）
- speed 参数的具体含义（倍速 vs 降帧比例）
- 是否支持动态升帧（降帧后的恢复机制）
