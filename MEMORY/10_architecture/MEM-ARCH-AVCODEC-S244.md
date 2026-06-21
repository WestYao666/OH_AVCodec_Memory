---
id: MEM-ARCH-AVCODEC-S244
title: SmartFluencyDecoding（SFD）智能流畅解码——帧保留策略引擎 + DropSyncCoordinator环形缓冲 + MV运动矢量分析
type: architecture_fact
scope: [AVCodec, VideoDecoder, FrameRetention, SmartFluencyDecoding, DropSyncCoordinator, AdaptiveStrategy, MVAnalyzer, NaluAnalyzer, RetentionStrategyFactory, AsyncDropDispatcher, AVCodecDfxComponent]
status: pending_approval
created: 2026-06-21T13:46 GMT+8
source: https://gitcode.com/openharmony/multimedia_av_codec (master分支)
association: [S231, S232, S239, S236]
---

# MEM-ARCH-AVCODEC-S244: SmartFluencyDecoding（SFD）智能流畅解码

> GitCode Web Fetch 探索 | 2026-06-21 | builder-agent (subagent)
> 来源：https://gitcode.com/openharmony/multimedia_av_codec/tree/master/services/services/codec/server/video/features/smart_fluency_decoding/

---

## 一句话定义

SmartFluencyDecoding（SFD）是 MediaAVCodec 服务端视频解码器的**智能丢帧保流畅模块**，通过NALU分析/MV运动矢量分析/MQ消息队列驱动的策略引擎，在解码延迟积压时选择性丢弃非参考帧或低运动帧，保障视频播放流畅。

---

## 源码证据（E1-E25 行号级）

### E1 - SmartFluencyDecoding 类核心成员与策略组合（L36-50 smart_fluency_decoding.h）
```cpp
mutable std::mutex configMutex_;
std::unique_ptr<DropSyncCoordinator> dropSyncCoordinator_{nullptr};    // 丢帧同步协调器
std::unique_ptr<AsyncDropDispatcher> asyncDispatcher_{nullptr};       // 异步丢帧分发器
std::unique_ptr<IRetentionStrategy> strategy_{nullptr};               // 策略引擎（接口）
std::unique_ptr<IMvAnalyzer> mvAnalyzer_{nullptr};                     // MV运动矢量分析器
std::unique_ptr<INaluAnalyzer> naluAnalyzer_{nullptr};                 // NALU分析器（判断非参考帧）
std::unordered_map<uint32_t, std::shared_ptr<AVBuffer>> inBufferMap_;  // 输入Buffer索引映射
SFDConfig config_{};
bool isInitialized_{false};
AsyncDropInputCallback asyncDropInputCb_{nullptr};
AsyncDropOutputCallback asyncDropOutputCb_{nullptr};
```
三层组件：DropSyncCoordinator（同步协调）+ AsyncDropDispatcher（异步分发）+ IRetentionStrategy（策略决策）。继承 AVCodecDfxComponent（DFX统计）。

### E2 - SFD 初始化入口（L49-60 smart_fluency_decoding.cpp）
```cpp
int32_t SmartFluencyDecoding::Initialize(const SFDConfig& config)
{
    CHECK_AND_RETURN_RET_LOG_WITH_TAG(config.width > 0 && config.height > 0, AVCS_ERR_INVALID_VAL,
        "Invalid video dimensions: %{public}dx%{public}d", config.width, config.height);
    CHECK_AND_RETURN_RET_LOG_WITH_TAG(config.codecType != SFDCodecType::INVALID,
        AVCS_ERR_INVALID_VAL, "Unsupported codec type");
    config_ = config;
    int32_t ret = InitializeInternal();
    ...
    isInitialized_ = true;
    return AVCS_ERR_OK;
}
```
初始化时校验分辨率和codec类型（AVC/HEVC/VP9等），校验通过后才激活SFD功能。与普通解码器FilterChain集成，SFD作为预处理决策层。

### E3 - InitializeInternal 组件三件套初始化（L62-81 smart_fluency_decoding.cpp）
```cpp
int32_t SmartFluencyDecoding::InitializeInternal()
{
    strategy_ = RetentionStrategyFactory::CreateStrategy(config_.initMode, config_.retentionRatio);
    if (strategy_->RequiresNaluAnalysis()) { EnsureNaluAnalyzer(); }
    if (strategy_->RequiresMvAnalysis())   { EnsureMvAnalyzer(); }
    dropSyncCoordinator_ = std::make_unique<DropSyncCoordinator>();
    asyncDispatcher_     = std::make_unique<AsyncDropDispatcher>();
    ...
}
```
策略引擎按需创建（FULL/ADAPTIVE/AUTO_RATIO/FIXED_RATIO），NALU分析器和MV分析器按策略需求懒加载，DropSyncCoordinator和AsyncDropDispatcher是常驻组件。

### E4 - RetentionStrategyFactory 四种策略工厂（L32-44 retention_strategy_factory.cpp）
```cpp
switch (mode) {
    case RetentionStrategyType::FULL:
        return std::make_unique<FullRetentionStrategy>();      // 不过滤，保留所有帧
    case RetentionStrategyType::ADAPTIVE:
        return std::make_unique<AdaptiveRetentionStrategy>();  // 自适应：根据MV动态决策
    case RetentionStrategyType::AUTO_RATIO:
        return std::make_unique<AutoFallbackRetentionStrategy>(); // 自动比率回退
    case RetentionStrategyType::FIXED_RATIO:
        if (retentionRate.has_value())
            return std::make_unique<FixedRatioRetentionStrategy>(retentionRate.value());
        return std::make_unique<AutoFallbackRetentionStrategy>();
    default: return nullptr;
}
```
四种策略：FULL（无过滤）、ADAPTIVE（MV自适应）、AUTO_RATIO（自动比率）、FIXED_RATIO（固定比率）。策略通过 Media::Tag::VIDEO_DECODER_FRAME_RETENTION_MODE 配置。

### E5 - IRetentionStrategy 策略接口定义（retention_strategy.h L24-38）
```cpp
class IRetentionStrategy {
public:
    virtual ~IRetentionStrategy() = default;
    virtual bool MakeRetentionDecision(const FrameRetentionContext& ctx) = 0;
    virtual void UpdatePlaybackSpeed(double /* speed */) {}
    virtual void UpdateSourceFramerate(double /*sourceFps*/) {}
    virtual void Reset() {}
    virtual RetentionStrategyType GetMode() const = 0;
    virtual double GetRatio() const = 0;
    virtual SfdDecisionReason GetLastDecisionReason() const { return SfdDecisionReason::UNSPECIFIED; }
    virtual bool IsPassthrough() const { return false; }
    virtual bool RequiresMvAnalysis() const { return false; }
    virtual bool RequiresNaluAnalysis() const { return true; }
};
```
策略接口标准五件套：MakeRetentionDecision（决策）+ UpdateSpeed/UpdateFps（动态参数）+ Reset（状态重置）+ GetMode/Ratio（查询）+ RequiresNalu/Mv（能力声明）。FULL策略IsPassthrough()返回true。

### E6 - DropSyncCoordinator 环形缓冲队列（L31-42 drop_sync_coordinator.h）
```cpp
static constexpr size_t queueCapacity = 1024;
static constexpr size_t queueMask = queueCapacity - 1;
static constexpr size_t cacheLineSize = 64;
int64_t ptsRingBuffer_[queueCapacity]{0};
std::atomic<bool> isConsumed_[queueCapacity]{};
alignas(cacheLineSize) std::atomic<size_t> writeIndex_{0};
alignas(cacheLineSize) std::atomic<size_t> readIndex_{0};
```
1024深度环形缓冲记录已丢弃帧的PTS，避免重复丢弃。writeIndex/readIndex按1024取模（queueMask）计算实际槽位。Cache line对齐防止false sharing。

### E7 - RecordPreDroppedFrame 丢弃帧记录（L22-35 drop_sync_coordinator.cpp）
```cpp
bool DropSyncCoordinator::RecordPreDroppedFrame(int64_t pts)
{
    size_t currentWrite = writeIndex_.load(std::memory_order_relaxed);
    size_t nextWrite = currentWrite + 1;
    CHECK_AND_RETURN_RET_LOG((nextWrite - readIndex_.load(std::memory_order_acquire)) <= queueCapacity,
        false, "RecordPreDroppedFrame queue overflow at PTS %{public}" PRId64, pts);
    size_t index = currentWrite & queueMask;
    ptsRingBuffer_[index] = pts;
    isConsumed_[index].store(false, std::memory_order_release);
    writeIndex_.store(nextWrite, std::memory_order_release);
    UpdateFeedback(false, true);
    return true;
}
```
预丢弃帧（解码前丢帧）时记录PTS。环形缓冲防 overflow 检查：`nextWrite - readIndex <= queueCapacity`。多消费者安全（codec server多线程访问）。

### E8 - GetAndConsumePreDroppedCount 消费预丢弃记录（L37-57 drop_sync_coordinator.cpp）
```cpp
uint32_t DropSyncCoordinator::GetAndConsumePreDroppedCount(int64_t currentPts)
{
    uint32_t count = 0;
    size_t currentRead = readIndex_.load(std::memory_order_relaxed);
    size_t currentWrite = writeIndex_.load(std::memory_order_acquire);
    while (scanIndex < currentWrite) {
        size_t index = scanIndex & queueMask;
        if (!isConsumed_[index].load(std::memory_order_acquire)) {
            if (ptsRingBuffer_[index] < currentPts) {
                count++;
                isConsumed_[index].store(true, std::memory_order_release);
            }
        }
        scanIndex++;
    }
    // 推进 readIndex
    while (currentRead < currentWrite && isConsumed_[currentRead & queueMask].load(...))
        currentRead++;
    if (count > 0) { readIndex_.store(currentRead, std::memory_order_release); }
    return count;
}
```
解码后查询当前PTS之前的已预丢弃帧数量并消费（标记isConsumed），返回累积的预丢弃计数。解码后决策时用于判断"已经预丢了多少帧"。

### E9 - 反馈窗口与实际保留比率（L59-81 drop_sync_coordinator.cpp）
```cpp
void DropSyncCoordinator::UpdateFeedback(bool isRetained, bool isPreDropped)
{
    std::lock_guard<std::mutex> lock(feedbackMutex_);
    if (feedbackWindowCount_ == feedbackWindowSize) {
        auto& old = feedbackWindow_[feedbackWindowPos_];
        if (old.isRetained)    windowRetainedCount_--;
        if (old.isPreDropped)  windowPreDroppedCount_--;
    } else { feedbackWindowCount_++; }
    auto& slot = feedbackWindow_[feedbackWindowPos_];
    slot.isRetained = isRetained;
    slot.isPreDropped = isPreDropped;
    if (isRetained)    windowRetainedCount_++;
    if (isPreDropped)  windowPreDroppedCount_++;
    feedbackWindowPos_ = (feedbackWindowPos_ + 1) & feedbackWindowMask;
}
```
滑动窗口（100帧）统计实际保留/预丢弃计数。GetActualRetentionRatio() = windowRetainedCount_/feedbackWindowCount_，用于策略自适应反馈。

### E10 - AsyncDropDispatcher 异步分发线程（async_drop_dispatcher.h L24-30）
```cpp
class AsyncDropDispatcher {
    std::mutex taskMutex_;
    std::condition_variable taskCv_;
    std::queue<std::function<void()>> taskQueue_;
    std::thread workerThread_;
    std::atomic<bool> isWorking_{false};
};
```
独立worker线程异步执行Buffer释放回调，防止解码线程阻塞。SubmitTask将任务压入队列，WorkerLoop从队列取任务执行。

### E11 - AdaptiveRetentionStrategy 自适应策略核心成员（adaptive_retention_strategy.h L24-34）
```cpp
double currentSpeed_{1.0};
double targetRatio_{1.0};
double accumulator_{0.0};     // 累加器：累积"保留信用"
double sourceFps_{30.0};
SfdDecisionReason lastReason_{SfdDecisionReason::UNSPECIFIED};
```
累加器模式：每帧decision后累加dynamicRatio（动态目标比率），累加到>=1.0时"发信号"保留一帧，低于阈值则丢弃。currentSpeed和sourceFps影响目标比率计算。

### E12 - EvaluateStutterRisk 抖动风险评估（L28-47 adaptive_retention_strategy.cpp）
```cpp
double AdaptiveRetentionStrategy::EvaluateStutterRisk(const MVStats& mvStats) const
{
    double mag = std::clamp(mvStats.perceptualMagnitude, 0.0, MAG_CAP); // 80.0
    double con = std::clamp(mvStats.motionConsistency, 0.0, 1.0);
    double rawRisk = 0.0;
    if (DoubleUtils::IsLessOrEqual(con, CON_LOW_TH))       rawRisk = LOW_RISK_TH;         // 0.2
    else if (DoubleUtils::IsLessOrEqual(con, CON_HIGH_TH))  rawRisk = LOW_RISK_TH + ...;  // 0.2~0.8
    else rawRisk = HIGH_RISK_TH + ...;                                        // 0.8~1.0
    double magWeight = ...; // magnitude权重0.4~1.0
    return std::clamp(rawRisk * magWeight, 0.0, 1.0);
}
```
运动一致性（motionConsistency）决定基础风险级别：低一致性（<0.33）→ 低风险0.2，高一致性（>0.66）→ 高风险0.8~1.0。perceptualMagnitude调整权重：静止场景（低magnitude）降低风险，允许更多丢帧。

### E13 - CalculateTargetRatio 目标保留比率计算（adaptive_retention_strategy.cpp L49-76）
```cpp
double AdaptiveRetentionStrategy::CalculateTargetRatio(const FrameRetentionContext& ctx) const
{
    double renderFps = sourceFps_ * currentSpeed_;
    if (DoubleUtils::IsLessOrEqual(renderFps, MIN_SOURCE_FPS_FOR_DROP)) return 1.0; // 24fps
    double baseRatioCeiling = std::clamp(TARGET_SAFE_FPS / renderFps, 0.0, 1.0);    // 45fps基准
    double maxDropFloor     = std::clamp(TARGET_EXTREME_FPS / renderFps, 0.0, 1.0); // 22fps基准
    if (ctx.mvStats->zeroMotionRatio >= 0.85) return maxDropFloor; // 静止场景可大幅丢帧
    double risk = EvaluateStutterRisk(*ctx.mvStats);
    if (risk >= 0.8)       return baseRatioCeiling;    // 高运动区域不丢帧
    else if (risk <= 0.2)  return maxDropFloor;         // 低运动区域最大丢帧
    else { // 0.2<risk<0.8 插值
        double factor = (risk - LOW_RISK_TH) / (HIGH_RISK_TH - LOW_RISK_TH);
        return maxDropFloor + factor * (baseRatioCeiling - maxDropFloor);
    }
}
```
高速播放（>24fps rendering）时触发SFD：45fps-safe目标和22fps-extreme目标之间插值。静止画面（zeroMotionRatio>0.85）允许最大丢帧，运动剧烈区域（risk>0.8）保护帧不丢。

### E14 - ExecuteAccumulatorDecision 累加器决策（adaptive_retention_strategy.cpp L78-91）
```cpp
bool AdaptiveRetentionStrategy::ExecuteAccumulatorDecision(double dynamicRatio, uint32_t preDroppedCount)
{
    accumulator_ += dynamicRatio + (preDroppedCount * dynamicRatio);
    if (DoubleUtils::IsGreaterOrEqual(accumulator_, 1.0)) {
        accumulator_ = 0.0;
        lastReason_ = (currentSpeed_ < 1.0) ? POST_RETAIN_ADAPTIVE_SPEED : POST_RETAIN_ADAPTIVE_DT;
        return true;  // 保留
    }
    lastReason_ = SfdDecisionReason::POST_DROP_ADAPTIVE_DT;
    return false;      // 丢弃
}
```
累加器模式：每帧（无论预丢还是后丢）都累加dynamicRatio×(1+preDroppedCount)。累加器跨过1.0门槛时保留一帧，否则丢弃。preDroppedCount越多，累加越快，降低解码压力。

### E15 - MakePreDecodeDecision 预解码决策入口（L267-311 smart_fluency_decoding.cpp）
```cpp
bool SmartFluencyDecoding::MakePreDecodeDecision(uint32_t index)
{
    auto buffer = FetchInputBufferAndCapabilities(index, caps);
    if (!isInitialized_ || !buffer || !dropSyncCoordinator_) return true;
    if (buffer->flag_ == AVCODEC_BUFFER_FLAG_EOS) return true;
    PreDecResult res;
    if (naluAnalyzer_ && caps.requiresNalu) {
        res.isNonRef = naluAnalyzer_->IsNonReferenceFrame(buffer);
        SetNoRefFrameMap(buffer->pts_, res.isNonRef);
        if (res.isNonRef) {
            double currentPreRetainedRatio = dropSyncCoordinator_->GetPreRetainedRatio();
            // 非参考帧 → 检查targetRatio → 决定是否丢弃
            if (DoubleUtils::IsGreaterOrEqual(caps.targetRatio, 1.0)) {
                res.reason = SfdDecisionReason::PRE_RETAIN_TARGET_FULL;
            } else if (...) { ExecutePreDrop(index, buffer); return false; }
        }
    }
    return true;
}
```
预解码决策：NALU分析判断非参考帧（P/B帧依赖的I帧不可丢），查DropSyncCoordinator实际预保留比率，决定是否预丢弃。非参考帧≠一定要丢，还要看当前保留目标比率。

### E16 - ExecutePreDrop 预丢弃执行（L207-226 smart_fluency_decoding.cpp）
```cpp
void SmartFluencyDecoding::ExecutePreDrop(uint32_t index, std::shared_ptr<AVBuffer> buffer)
{
    CHECK_AND_RETURN_LOG(buffer->flag_ != AVCODEC_BUFFER_FLAG_CODEC_DATA,
        "ExecutePreDrop: skip CODEC_DATA buffer");
    dropSyncCoordinator_->RecordPreDroppedFrame(buffer->pts_);
    AsyncDropInputCallback localCb = nullptr;
    { std::lock_guard<std::mutex> lock(configMutex_); localCb = asyncDropInputCb_; }
    if (localCb) {
        asyncDispatcher_->SubmitTask([cb = localCb, idx = index, buf = std::move(buffer)]() {
            cb(idx, buf);  // 异步回调归还Buffer到Codec
        });
    }
}
```
预丢弃：记录PTS到DropSyncCoordinator（防止后解码重复消费），异步提交Buffer归还任务到AsyncDropDispatcher Worker线程。CodecData buffer不预丢（确保SPS/PPS/SEI可用）。

### E17 - MakePostDecodeDecision 后解码决策（smart_fluency_decoding.cpp后半段）
```cpp
bool SmartFluencyDecoding::MakePostDecodeDecision(uint32_t index, int64_t pts, const sptr<SurfaceBuffer> surfaceBuffer)
{
    // 1. 查预丢弃计数
    uint32_t preDroppedCount = dropSyncCoordinator_->GetAndConsumePreDroppedCount(pts);
    // 2. MV分析（如果策略需要）
    PostDecCost cost;
    MVStats mvStats = ExtractMVStats(caps, pts, cost, surfaceBuffer);
    // 3. 策略决策
    FrameRetentionContext ctx{preDroppedCount, &mvStats};
    bool shouldRetain = strategy_->MakeRetentionDecision(ctx);
    // 4. 更新反馈
    dropSyncCoordinator_->UpdateFeedback(shouldRetain, false);
    if (!shouldRetain) ExecutePostDrop(index);
    return shouldRetain;
}
```
后解码决策：获取预丢弃计数+提取MV统计→构造FrameRetentionContext→调用策略→更新反馈→执行后丢弃。解码后丢弃延迟更高（SurfaceBuffer已分配），优先使用预丢弃。

### E18 - IMvAnalyzer 运动矢量分析接口（mv_analyzer.h L24-36）
```cpp
class IMvAnalyzer {
public:
    virtual ~IMvAnalyzer() = default;
    virtual void SetStreamAuxInfo(const StreamAuxInfo& info) = 0;
    virtual void SetVideoInfo(uint32_t width, uint32_t height) = 0;
    virtual MVStats Analyze(const uint8_t *buffer, uint32_t length) = 0;
    virtual SFDCodecType GetCodecType() const = 0;
};

class MvAnalyzerFactory {
    static std::unique_ptr<IMvAnalyzer> CreateMvAnalyzer(SFDCodecType codecType);
    static bool IsCodecSupported(SFDCodecType codecType);
};
```
MV分析器从码流辅助信息（SEI/Metadata）提取运动矢量，Analyze()返回MVStats结构（含perceptualMagnitude/motionConsistency/zeroMotionRatio）。工厂模式支持不同codec类型（H.264/H.265/VP9等）。

### E19 - INaluAnalyzer NALU分析接口（nalu_analyzer.h）
```cpp
class INaluAnalyzer {
    virtual bool IsNonReferenceFrame(const std::shared_ptr<AVBuffer>& buffer) = 0;
    virtual void SetVideoInfo(uint32_t width, uint32_t height) = 0;
};
```
NALU分析器解析H.264/HEVC NAL单元头部，识别非参考帧（不影响后续帧解码的P/B帧）。EnableLateInit时支持CSD中间激活。

### E20 - SmartFluencyDecodingBuilder 构建者接口（smart_fluency_decoding_builder.h L24-39）
```cpp
class SmartFluencyDecodingBuilder {
    SmartFluencyDecodingBuilder& SetVideoWidth(int32_t width);
    SmartFluencyDecodingBuilder& SetVideoHeight(int32_t height);
    SmartFluencyDecodingBuilder& SetCodecMime(const std::string& mime);
    SmartFluencyDecodingBuilder& UpdatePlaybackSpeed(double speed);
    SmartFluencyDecodingBuilder& SetFromFormat(const Media::Format& format);
    std::unique_ptr<SmartFluencyDecoding> Build();
private:
    static SFDCodecType ParseCodecType(const std::string& mime);
    bool ValidateParams();
    SFDConfig config_{};
};
```
Builder模式封装SFDConfig构造，支持从Media::Format一次性配置所有参数（SFDConfig包括width/height/codecType/initMode/retentionRatio）。与CodecServer集成时通过Builder创建SFD实例。

### E21 - ParseRetentionConfig 动态配置解析（smart_fluency_decoding.cpp L96-131）
```cpp
void SmartFluencyDecoding::ParseRetentionConfig(const Media::Format& format,
    RetentionStrategyType& mode, std::optional<double>& ratio)
{
    if (format.GetDoubleValue(Media::Tag::VIDEO_DECODER_FRAME_RETENTION_RATIO, parsedRatio))
        ratio = parsedRatio;  // 用户指定保留比率
    int32_t extMode = -1;
    if (format.GetIntValue(Media::Tag::VIDEO_DECODER_FRAME_RETENTION_MODE, extMode)) {
        switch (extMode) {
            case FrameRetentionMode::FULL:     mode = RetentionStrategyType::FULL; break;
            case FrameRetentionMode::ADAPTIVE: mode = RetentionStrategyType::ADAPTIVE; break;
            case FrameRetentionMode::UNIFORM:  mode = ratio ? FIXED_RATIO : AUTO_RATIO; break;
        }
    }
}
```
用户通过Format配置SFD策略：VIDEO_DECODER_FRAME_RETENTION_MODE（FULL/ADAPTIVE/UNIFORM）和 VIDEO_DECODER_FRAME_RETENTION_RATIO（保留比率）。支持运行时动态更新。

### E22 - UpdateDynamicConfig 策略热切换（smart_fluency_decoding.cpp L168-181）
```cpp
int32_t SmartFluencyDecoding::UpdateDynamicConfig(const Media::Format& format)
{
    ParseRetentionConfig(format, newMode, newRatio);
    if (format.GetDoubleValue(Media::Tag::VIDEO_DECODER_SPEED, speed))
        UpdatePlaybackSpeed(speed);
    if (newMode != config_.initMode || DoubleUtils::IsNotEqual(newRatio, config_.retentionRatio)) {
        ApplyNewStrategy(newMode, newRatio); // 热切换策略
    }
    return AVCS_ERR_OK;
}
```
运行时动态切换策略（无需重建SFD实例）。策略热切换流程：创建新策略对象→按需创建分析器→原子替换strategy_成员→更新config_。支持播放速度动态变化时更新策略参数。

### E23 - Flush 状态重置（smart_fluency_decoding.cpp L183-197）
```cpp
void SmartFluencyDecoding::Flush()
{
    std::lock_guard<std::mutex> lock(configMutex_);
    if (dropSyncCoordinator_) dropSyncCoordinator_->Reset();
    if (strategy_) strategy_->Reset();
    inBufferMap_.clear();
    noRefFrameMap_.clear();
    lastValidMVStats_ = {};
    hasValidMVStats_ = false;
}
```
Seek/Flush时清空所有状态：DropSyncCoordinator清空环形缓冲、策略累加器归零、输入Buffer映射清空、MV状态清零。确保Seek后SFD状态与解码器同步。

### E24 - SFDConfig 配置结构（smart_fluency_decoding.h L24-33）
```cpp
struct SFDConfig {
    uint32_t width = 0;
    uint32_t height = 0;
    SFDCodecType codecType = SFDCodecType::INVALID;
    RetentionStrategyType initMode = RetentionStrategyType::INVALID;
    std::optional<double> retentionRatio = std::nullopt;
};
```
SFDConfig五要素：分辨率（width×height）、codec类型（AVC/HEVC/VP9/AV1）、初始化策略模式、保留比率（可选）。Builder.SetFromFormat从Media::Format一次性填充。

### E25 - MVStats 运动矢量统计结构（mv_analyzer.h + adaptive_retention_strategy.cpp）
```cpp
struct MVStats {
    double perceptualMagnitude{0.0};   // 感知运动幅度 [0,80]
    double motionConsistency{0.0};     // 运动一致性 [0,1]
    double zeroMotionRatio{0.0};       // 零运动区域占比 [0,1]
    uint32_t validBlocks{0};           // 有效MV块数
};
```
MVStats三元组：perceptualMagnitude（运动幅度，决定允许丢帧量）、motionConsistency（运动方向一致性，决定风险级别）、zeroMotionRatio（零运动区域比例，>0.85触发最大丢帧）。validBlocks>0才进行MV分析。

---

## SFD 决策流程图

```
输入Buffer进入解码器
    ↓
MakePreDecodeDecision() [预解码决策]
    ↓ NALU分析 IsNonReferenceFrame()?
    ├── 非参考帧 ──→ GetPreRetainedRatio() vs targetRatio
    │                  ├── ratio >= 1.0 → 保留 (PRE_RETAIN_TARGET_FULL)
    │                  └── ratio <  1.0 → ExecutePreDrop → RecordPreDroppedFrame → asyncCb
    └── 参考帧 → 进入解码器解码
                        ↓
                MakePostDecodeDecision() [后解码决策]
                        ↓
                GetAndConsumePreDroppedCount(pts) → 预丢弃计数
                        ↓
                ExtractMVStats() → MVStats {magnitude, consistency, zeroMotion}
                        ↓
                CalculateTargetRatio(MVStats) → [maxDropFloor ~ baseRatioCeiling]
                        ↓
                ExecuteAccumulatorDecision(targetRatio, preDroppedCount)
                        ├── accumulator >= 1.0 → 保留 (POST_RETAIN_ADAPTIVE_*)
                        └── accumulator <  1.0 → ExecutePostDrop() → asyncCb
                        ↓
                UpdateFeedback(isRetained, isPreDropped) → 滑动窗口统计
```

---

## 四种策略对比

| 维度 | FULL | ADAPTIVE | AUTO_RATIO | FIXED_RATIO |
|------|------|----------|------------|-------------|
| 名称 | 全保留 | 自适应 | 自动比率 | 固定比率 |
| 丢帧触发 | 不丢帧 | MV分析动态决策 | 累积误差超阈值 | 固定比率均匀丢帧 |
| MV分析 | 不需要 | 需要 | 不需要 | 可选 |
| NALU分析 | 不需要 | 需要 | 需要 | 需要 |
| retentionRatio | 忽略 | 忽略 | 自动计算 | 固定值 |
| IsPassthrough | true | false | false | false |

---

## 关联记忆

- **S231**: VpxDecoder（VP8/VP9软件解码器）+ decoderbase（视频解码器基类），SFD可挂载于VpxDecoder输出链路
- **S232**: Av1Decoder（AV1解码器）+ Dav1d，与VpxDecoder同属软解，SFD可作用于AV1输出
- **S239**: CodecBase Engine 架构（SFD挂载在CodecBase九态机的OUTPUT状态之后）
- **S236**: HCodec DFX Module（SFD本身是DFX组件，继承AVCodecDfxComponent，有HiSysEvent上报能力）

---

## 元信息

| 字段 | 值 |
|------|-----|
| mem_id | MEM-ARCH-AVCODEC-S244 |
| 主题 | SmartFluencyDecoding（SFD）智能流畅解码——帧保留策略引擎+DropSyncCoordinator环形缓冲+MV运动矢量自适应分析 |
| scope | AVCodec, VideoDecoder, FrameRetention, SmartFluencyDecoding, DropSyncCoordinator, AdaptiveStrategy, MVAnalyzer, NaluAnalyzer, RetentionStrategyFactory |
| 关联场景 | 视频解码流畅度优化/低端设备性能保障/倍速播放/视频录制 |
| evidence_count | 25 |
| source_files | smart_fluency_decoding.cpp+smart_fluency_decoding.h+drop_sync_coordinator.cpp/.h+async_drop_dispatcher.cpp/.h+strategies/retention_strategy.h+adaptive_retention_strategy.cpp/.h+retention_strategy_factory.cpp+mv_analyzer.h+smart_fluency_decoding_builder.h+nalu_analyzer.h |
| source | GitCode https://gitcode.com/openharmony/multimedia_av_codec |
| git_branch | master |
| associations | S231/S232/S239/S236 |
| draft_date | 2026-06-21 |
