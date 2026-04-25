---
type: architecture
id: MEM-ARCH-AVCODEC-S17
status: pending_approval
submitted_by: builder-agent
submitted_at: "2026-04-25T17:36:00+08:00"
topic: SmartFluencyDecoding 智能流畅解码——IRetentionStrategy四策略+MV/Nalu双分析器+AsyncDropDispatcher异步丢帧
created_at: "2026-04-24T05:55:00+08:00"
evidence: |
  - source: /home/west/av_codec_repo/services/services/codec/server/video/features/smart_fluency_decoding/smart_fluency_decoding.h
    anchor: "SmartFluencyDecoding::MakePreDecodeDecision / MakePostDecodeDecision / ExecutePreDrop / ExecutePostDrop"
  - source: /home/west/av_codec_repo/services/services/codec/server/video/features/smart_fluency_decoding/smart_fluency_decoding.cpp
    anchor: "SmartFluencyDecoding::Initialize / InitializeInternal / EnsureNaluAnalyzer / EnsureMvAnalyzer"
  - source: /home/west/av_codec_repo/services/services/codec/server/video/features/smart_fluency_decoding/interfaces/smart_fluency_decoding_types.h
    anchor: "RetentionStrategyType::FULL / ADAPTIVE / FIXED_RATIO / AUTO_RATIO, SFDCodecType::AVC / HEVC / VVC, SFDConfig"
  - source: /home/west/av_codec_repo/services/services/codec/server/video/features/smart_fluency_decoding/strategies/retention_strategy.h
    anchor: "IRetentionStrategy::MakeRetentionDecision / UpdatePlaybackSpeed / GetCurrentRetentionRatio"
  - source: /home/west/av_codec_repo/services/services/codec/server/video/features/smart_fluency_decoding/strategies/adaptive_retention_strategy.h
    anchor: "AdaptiveRetentionStrategy::MakeRetentionDecision"
  - source: /home/west/av_codec_repo/services/services/codec/server/video/features/smart_fluency_decoding/analyzers/mv_analyzer.h
    anchor: "IMvAnalyzer::ParseMVData"
  - source: /home/west/av_codec_repo/services/services/codec/server/video/features/smart_fluency_decoding/analyzers/nalu_analyzer.h
    anchor: "INaluAnalyzer::AnalyzeNalu"
  - source: /home/west/av_codec_repo/services/services/codec/server/video/features/smart_fluency_decoding/async_drop_dispatcher.h
    anchor: "AsyncDropDispatcher::SubmitTask / WorkerLoop — std::thread + std::mutex + std::condition_variable 异步线程模式"
  - source: /home/west/av_codec_repo/services/services/codec/server/video/features/smart_fluency_decoding/drop_sync_coordinator.h
    anchor: "DropSyncCoordinator::ptsRingBuffer_[128] — PTS环形缓冲 / currentEmaDropRatio_ EMA反馈 / GetTargetRetentionRatio"
---

# MEM-ARCH-AVCODEC-S17: SmartFluencyDecoding 智能流畅解码

## Metadata

| 字段 | 值 |
|------|-----|
| id | MEM-ARCH-AVCODEC-S17 |
| title | SmartFluencyDecoding 智能流畅解码——IRetentionStrategy四策略+MV/Nalu双分析器+AsyncDropDispatcher异步丢帧 |
| scope | [AVCodec, SmartFluencyDecoding, SFD, RetentionStrategy, MVAnalyzer, NaluAnalyzer, AsyncDrop, VideoPipeline, CodecServer] |
| status | draft |
| created_by | builder-agent |
| created_at | 2026-04-24 |
| type | architecture_fact |
| confidence | high |
| related_scenes | [新需求开发, 问题定位, 智能丢帧, 流畅度优化, 视频播放性能, 高效播放] |
| why_it_matters: |
  - 视频播放流畅度优化：智能丢帧（Smart Drop）比盲目丢帧更好地平衡画面流畅与硬件负担
  - 新需求开发：CodecServer 视频解码接入 SFD 时需理解四策略与双分析器的关系
  - 问题定位：播放卡顿、花屏时需排查 SFD 丢帧策略是否误触发
  - 插件热加载：MVAnalyzer 和 NaluAnalyzer 均以 dlopen 插件形式加载，架构与四层 Loader 一致

## 摘要

SmartFluencyDecoding（SFD）是 AVCodec 解码 Pipeline 中的**智能流畅度优化组件**，位于 Demuxer 和 Decoder 之间（PreDecode）以及 Decoder 输出后（PostDecode）。
通过 MV/Nalu 双分析器感知视频内容复杂度，结合四种 RetentionStrategy（丢帧策略）动态决定是否丢帧。
丢帧执行通过 AsyncDropDispatcher 异步分发，不阻塞解码主线程。

## 关键类与接口

### SmartFluencyDecoding（主体）

| 字段 | 值 |
|------|-----|
| 文件 | `services/services/codec/server/video/features/smart_fluency_decoding/smart_fluency_decoding.h` |
| 命名空间 | `OHOS::MediaAVCodec::SFD` |

**核心公共接口**:

```cpp
// 初始化（策略类型 + 视频规格 + Codec类型）
int32_t Initialize(const SFDConfig& config);

// PreDecode 决策（Demuxer 已提取数据，尚未送入解码器）
bool MakePreDecodeDecision(uint32_t index);

// PostDecode 决策（解码完成，尚未输出到 Surface）
bool MakePostDecodeDecision(uint32_t index, int64_t pts, sptr<SurfaceBuffer> surfaceBuffer);

// 回调注册（SFD 执行丢帧时通知 Pipeline）
void SetCallbacks(AsyncDropInputCallback inCb, AsyncDropOutputCallback outCb);

// 播速更新（策略随播速动态调整）
void UpdatePlaybackSpeed(double speed);

// 统计
void GetStatistics(uint32_t& totalFrames, uint32_t& droppedFrames) const;
```

### SFDConfig 配置结构

```cpp
struct SFDConfig {
    int32_t width{0};
    int32_t height{0};
    SFDCodecType codecType{SFDCodecType::INVALID}; // AVC / HEVC / VVC
    RetentionStrategyType initMode{RetentionStrategyType::INVALID}; // 初始策略
    std::optional<double> retentionRatio{std::nullopt}; // 固定丢帧比例（FIXED_RATIO 时生效）
};
```

### RetentionStrategyType 四种策略

| 策略 | 说明 | 丢帧触发 |
|------|------|---------|
| `FULL` | 不丢帧，保留所有帧 | 从不 |
| `ADAPTIVE` | 自适应，根据 MV 分析器动态调整 | 依赖 AnalyzeMVData |
| `FIXED_RATIO` | 固定比例丢帧（如 50% 丢一帧） | retentionRatio 配置 |
| `AUTO_RATIO` | 自动比例，根据内容和播速动态计算 | 依赖 NALU 分析器 + 播速 |

**IRetentionStrategy 接口**:

```cpp
class IRetentionStrategy {
    virtual bool MakeRetentionDecision(const FrameRetentionContext& ctx) = 0;
    virtual void UpdatePlaybackSpeed(double speed) = 0;
    virtual void Reset() = 0;
    virtual RetentionStrategyType GetMode() const = 0;
    virtual double GetCurrentRetentionRatio() const = 0;
    virtual void OnDecodingPerformanceUpdate(double speed, double decFps) {}
};
```

### MVAnalyzer（运动矢量分析器）

| 字段 | 值 |
|------|-----|
| 接口文件 | `analyzers/mv_analyzer.h` |
| SO 加载器 | `mv_analyzer_so_loader.h` |
| 接口 | `IMvAnalyzer::ParseMVData(surfaceBuffer, MVStats&)` |

**MVStats 统计数据**:

```cpp
struct MVStats {
    uint32_t totalBlocks;        // 总块数
    uint32_t validBlocks;        // 有效块
    uint32_t skipBlocks;         // Skip 块数
    uint32_t zeroMotionBlocks;   // 零运动块
    double avgRefDist;           // 平均参考距离
    double perceptualMagnitude;  // 感知运动幅度
    double motionConsistency;    // 运动一致性
    double zeroMotionRatio;     // 零运动比例
};
```

### NaluAnalyzer（NALU 分析器）

| 字段 | 值 |
|------|-----|
| 接口文件 | `analyzers/nalu_analyzer.h` |
| SO 加载器 | `nalu_analyzer_so_loader.h` |
| 接口 | `INaluAnalyzer::AnalyzeNalu(buffer, ...)` |

### AsyncDropDispatcher（异步丢帧分发器）

- **作用**: 异步执行丢帧，不阻塞解码线程
- **公共接口**:
  - 投递丢帧任务到独立线程/队列
  - 与 DropSyncCoordinator 配合，确保丢帧与解码同步

### DropSyncCoordinator（丢帧同步协调器）

- **作用**: 确保同一次决策的 PreDrop 和 PostDrop 成对执行，防止丢帧导致画面状态不一致

## 数据流

```
Demuxer 输出 ES 数据
    ↓
SmartFluencyDecoding::MakePreDecodeDecision(index)
    → IRetentionStrategy::MakeRetentionDecision(ctx)
    → IMvAnalyzer::ParseMVData(buffer, mvStats)  [ADAPTIVE/AUTO_RATIO]
    → INaluAnalyzer::AnalyzeNalu(buffer)          [AUTO_RATIO]
    → 返回是否 PreDrop

如果 PreDrop:
    → AsyncDropDispatcher::ExecutePreDrop(index, buffer)
    → 通知 asyncDropInputCb_(index, buffer)
    → 数据不进入 Decoder

如果不禁用 PreDrop:
    → Decoder 解码
    ↓
SmartFluencyDecoding::MakePostDecodeDecision(index, pts, surfaceBuffer)
    → 再次调用 Strategy 决策（参考帧信息更完整）
    → 如果 PostDrop:
        → AsyncDropDispatcher::ExecutePostDrop(index)
        → 通知 asyncDropOutputCb_(index)
        → 帧不输出到 Surface
```

## 关键成员变量

```cpp
std::unique_ptr<DropSyncCoordinator> dropSyncCoordinator_;
std::unique_ptr<AsyncDropDispatcher> asyncDispatcher_;
std::unique_ptr<IRetentionStrategy> strategy_;           // 四策略之一
std::unique_ptr<IMvAnalyzer> mvAnalyzer_;                  // dlopen 插件
std::unique_ptr<INaluAnalyzer> naluAnalyzer_;             // dlopen 插件
std::unordered_map<uint32_t, std::shared_ptr<AVBuffer>> inBufferMap_; // 待决策帧缓存
std::shared_ptr<AVBuffer> csdBuffer_{nullptr};             // 编解码参数（CodecSpecificData）

std::atomic<uint32_t> totalInputFrames_{0};
std::atomic<uint32_t> droppedInputFrames_{0};
std::atomic<uint32_t> totalOutputFrames_{0};
std::atomic<uint32_t> droppedOutputFrames_{0};

double currentPlaybackSpeed_{1.0};
```

## 策略决策上下文（FrameRetentionContext）

```cpp
struct FrameRetentionContext {
    int64_t ptsMs;           // 帧时间戳
    int64_t sysTimeMs;      // 系统时间（用于性能计算）
    uint32_t frameCount;    // 当前帧计数
    uint32_t preDroppedCount = 0; // PreDrop 数量
    const MVStats* mvStats = nullptr; // MV 分析结果（ADAPTIVE）
};
```

## 与 CodecServer 的关系

- SFD 是 CodecServer 视频解码 Pipeline 的一个可选 Feature（通过 `features/smart_fluency_decoding/` 目录承载）
- CodecServer 在 Configure 时创建 SFD 实例并传入 SFDConfig（宽高/Codec类型/策略模式）
- SFD 的丢帧回调（asyncDropInputCb_ / asyncDropOutputCb_）注册到 Pipeline 中对应 Filter
- SFD 统计丢帧率，供 DFX 上报 `totalFrames` / `droppedFrames`

## 与其他组件的关系

| 组件 | 关系 | 说明 |
|------|------|------|
| CodecServer | 持有者 | SFD 实例由 CodecServer 管理 |
| Decoder (CodecBase) | 下游 | PreDrop 跳过解码；PostDrop 跳过输出 |
| Demuxer | 前置 | MakePreDecodeDecision 依赖 Demuxer 已提取的 ES 数据 |
| IMvAnalyzer | 分析器 | 以 dlopen 插件加载，分析运动矢量 |
| INaluAnalyzer | 分析器 | 以 dlopen 插件加载，分析 NALU 类型 |
| IRetentionStrategy | 策略抽象 | 四种策略实现，全策略模式统一入口 |
| AsyncDropDispatcher | 执行器 | 异步执行丢帧，不阻塞解码主线程 |
| DropSyncCoordinator | 同步器 | 保证 Pre/Post 成对丢帧 |
| AdaptiveFramerateController | 互补 | AFC 控制帧率，SFD 控制丢帧，共同优化播放体验 |

## 已有记忆关联

- **MEM-ARCH-AVCODEC-S3**: CodecServer Pipeline 数据流（Pipeline 中集成 SFD 丢帧机制）
- **MEM-ARCH-AVCODEC-S5**: 四层 Loader 插件热加载（MVAnalyzer/NaluAnalyzer 使用相同 dlopen/RTLD_LAZY 机制）
- **MEM-ARCH-AVCODEC-006**: media_codec 编解码数据流（SFD 位于 Demuxer 和 Decoder 之间）
- **MEM-ARCH-AVCODEC-S4**: Surface Mode 与 Buffer Mode 双模式（SFD 影响 Surface 输出帧率）

## 待补充

- MVAnalyzer SO 插件路径与加载条件（何时降级为无插件）
- NaluAnalyzer SO 插件路径与 NALU 类型判断逻辑
- FIXED_RATIO 策略的具体丢帧比例计算方式
- AUTO_RATIO 策略根据播速自动调整比例的公式
- SFDConfig 中 retentionRatio 的配置入口（Format key）
- 与 MediaCodec API 的对接方式（三方应用如何启用 SFD）
- Build 宏 `BUILD_ENG_VERSION` 下的 SmartFluencyDecodingDumper 机制
