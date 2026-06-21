# MEM-ARCH-AVCODEC-S244: SmartFluencyDecoding（SFD）智能流畅解码

## 元信息

| 字段 | 值 |
|------|-----|
| mem_id | MEM-ARCH-AVCODEC-S244 |
| 主题 | SmartFluencyDecoding（SFD）智能流畅解码——帧保留策略引擎 + DropSyncCoordinator 环形缓冲 + MV/NaluAnalyzer 双分析器 |
| scope | AVCodec, VideoDecoder, FrameRetention, SmartFluencyDecoding, DropSyncCoordinator, AdaptiveStrategy, MVAnalyzer, NaluAnalyzer, RetentionStrategyFactory, AsyncDropDispatcher |
| 关联场景 | 新需求开发/问题定位/视频解码流畅度优化/低端设备/倍速播放 |
| 状态 | draft |
| source_verified | true |
| 来源 | 本地镜像 /home/west/av_codec_repo/services/services/codec/server/video/features/smart_fluency_decoding/ |

## 1. 架构总览

SFD 是视频解码器流畅度优化模块，位于 `services/services/codec/server/video/features/smart_fluency_decoding/`。核心设计：**解码前（PreDecode）和解码后（PostDecode）双阶段丢帧决策**，配合 MV 运动矢量自适应分析和 NALU 参考帧分析，由 DropSyncCoordinator 环形缓冲保证成对丢帧同步。

```
SmartFluencyDecoding（主控制器）
  ├── RetentionStrategyFactory → IRetentionStrategy（四策略）
  │     ├── FullRetentionStrategy（全部保留）
  │     ├── AdaptiveRetentionStrategy（MV自适应）
  │     ├── FixedRatioRetentionStrategy（固定比例）
  │     └── AutoFallbackRetentionStrategy（自动回退）
  ├── NaluAnalyzerFactory → INaluAnalyzer（dlopen）
  ├── MvAnalyzerFactory → IMvAnalyzer（dlopen）
  ├── DropSyncCoordinator（128 pts 环形缓冲）
  └── AsyncDropDispatcher（独立 worker 线程）
```

---

## 2. 核心数据结构

### 2.1 SFDConfig / RetentionStrategyType / SFDCodecType

**文件**: `interfaces/smart_fluency_decoding_types.h`

```cpp
enum class RetentionStrategyType : int32_t {
    INVALID = -1,
    FULL = 0,        // 全部保留（不丢帧）
    ADAPTIVE = 1,    // MV自适应（依赖运动矢量分析）
    FIXED_RATIO = 2, // 固定比例（如 50%）
    AUTO_RATIO = 3   // 自动比例（根据设备性能自适应）
};

enum class SFDCodecType : int32_t {
    INVALID = -1,
    AVC = 0,   // H.264/AVC
    HEVC = 1,  // H.265/HEVC
    VVC = 2    // H.266/VVC
};

struct SFDConfig {
    int32_t width{0};
    int32_t height{0};
    SFDCodecType codecType{SFDCodecType::INVALID};
    RetentionStrategyType initMode{RetentionStrategyType::INVALID};
    std::optional<double> retentionRatio{std::nullopt};
};
```

**文件**: `strategies/retention_strategy_factory.cpp`

```cpp
std::unique_ptr<IRetentionStrategy> RetentionStrategyFactory::CreateStrategy(
    RetentionStrategyType mode,
    const std::optional<double>& retentionRate)
{
    switch (mode) {
        case RetentionStrategyType::FULL:
            return std::make_unique<FullRetentionStrategy>();
        case RetentionStrategyType::ADAPTIVE:
            return std::make_unique<AdaptiveRetentionStrategy>();
        case RetentionStrategyType::AUTO_RATIO:
            return std::make_unique<AutoFallbackRetentionStrategy>();
        case RetentionStrategyType::FIXED_RATIO:
            if (retentionRate.has_value()) {
                return std::make_unique<FixedRatioRetentionStrategy>(retentionRate.value());
            }
            return std::make_unique<AutoFallbackRetentionStrategy>();
        // ...
    }
}
```

### 2.2 MVStats 运动矢量统计

```cpp
typedef struct {
    uint32_t totalBlocks;
    uint32_t validBlocks;
    uint32_t skipBlocks;           // SKIP 块数
    uint32_t zeroMotionBlocks;     // 零运动块数
    double avgRefDist;              // 平均参考距离
    double perceptualMagnitude;     // 感知幅度
    double motionConsistency;       // 运动一致性
    double zeroMotionRatio;        // 零运动比例
} MVStats;
```

---

## 3. 双阶段丢帧决策链

### 3.1 解码前决策（PreDecode）

**文件**: `smart_fluency_decoding.cpp`

```cpp
// E1: MakePreDecodeDecision 入口（第 220 行）
bool SmartFluencyDecoding::MakePreDecodeDecision(uint32_t index)
{
    // 1. 取出对应 buffer
    std::shared_ptr<AVBuffer> buffer = nullptr;
    {
        std::lock_guard<std::mutex> lock(configMutex_);
        auto it = inBufferMap_.find(index);
        if (it != inBufferMap_.end()) {
            buffer = it->second;
            inBufferMap_.erase(it);
        }
    }
    // 2. NaluAnalyzer 判断是否非参考帧
    bool isNonRef = false;
    if (naluAnalyzer_ && naluAnalyzer_->IsNonReferenceFrame(buffer)) {
        isNonRef = true;
        double currentEma = dropSyncCoordinator_->GetCurrentEma();
        double targetDropRatio = 1.0 - dropSyncCoordinator_->GetTargetRetentionRatio();
        // EMA >= 目标丢帧比例时才丢帧
        shouldRetain = currentEma >= targetDropRatio && targetDropRatio > RETENTION_RATIO_MIN_DIFF;
    }
    // 3. 丢帧执行
    if (!shouldRetain) {
        ExecutePreDrop(index, buffer);  // 异步通知
    }
}

// E2: ExecutePreDrop 异步丢帧（第 201 行）
void SmartFluencyDecoding::ExecutePreDrop(uint32_t index, std::shared_ptr<AVBuffer> buffer)
{
    dropSyncCoordinator_->RecordPreDroppedFrame(buffer->pts_); // 记录 PTS
    droppedInputFrames_++;
    // 异步线程执行回调
    if (localCb) {
        asyncDispatcher_->SubmitTask([cb = localCb, idx = index, buf = std::move(buffer)]() {
            cb(idx, buf);
        });
    }
}
```

### 3.2 解码后决策（PostDecode）

```cpp
// E3: MakePostDecodeDecision 入口（第 252 行）
bool SmartFluencyDecoding::MakePostDecodeDecision(
    uint32_t index, int64_t pts, const sptr<SurfaceBuffer> surfaceBuffer)
{
    // 1. 获取预丢帧数量（成对同步）
    int64_t currentPts = pts;
    uint32_t preDroppedCount = dropSyncCoordinator_->GetAndConsumePreDroppedCount(currentPts);
    
    // 2. MV 数据解析
    MVStats currentMvStats;
    ParseMVData(surfaceBuffer, currentMvStats);
    
    // 3. 构造上下文并调用策略引擎
    FrameRetentionContext ctx;
    ctx.ptsMs = currentPts;
    ctx.preDroppedCount = preDroppedCount;
    ctx.mvStats = &currentMvStats;
    
    bool shouldRetain = true;
    {
        std::lock_guard<std::mutex> lock(configMutex_);
        shouldRetain = strategy_->MakeRetentionDecision(ctx);
        currentRetentionRatio = strategy_->GetCurrentRetentionRatio();
    }
    
    // 4. 反馈给 DropSyncCoordinator
    dropSyncCoordinator_->UpdateFeedback(
        preDroppedCount, !shouldRetain, currentRetentionRatio, currentPlaybackSpeed_);
    
    if (!shouldRetain) {
        ExecutePostDrop(index); // 异步通知
    }
}

// E4: ParseMVData 从 SurfaceBuffer 提取 MV（第 317 行）
void SmartFluencyDecoding::ParseMVData(const sptr<SurfaceBuffer> surfaceBuffer, MVStats& mvStats)
{
    using namespace HDI::Display::Graphic::Common;
    std::vector<uint8_t> vec;
    V2_0::BlobDataType data;
    // 从 SurfaceBuffer 获取 ATTRKEY_VIDEO_DECODER_MV 元数据
    int32_t ret = surfaceBuffer->GetMetadata(V2_0::ATTRKEY_VIDEO_DECODER_MV, vec);
    uint8_t* input = reinterpret_cast<uint8_t*>(static_cast<uintptr_t>(data.vaddr + data.offset));
    mvStats = mvAnalyzer_->Analyze(input);
}
```

---

## 4. DropSyncCoordinator 环形缓冲与成对同步

**文件**: `drop_sync_coordinator.h`

```cpp
// E5: DropSyncCoordinator 128 pts 环形缓冲（第 35-50 行）
class DropSyncCoordinator {
private:
    static constexpr size_t queueCapacity = 128;      // 环形缓冲容量
    static constexpr size_t queueMask = queueCapacity - 1;
    static constexpr size_t cacheLineSize = 64;      // cache line 对齐防伪共享
    int64_t ptsRingBuffer_[queueCapacity]{0};
    alignas(cacheLineSize) std::atomic<size_t> writeIndex_{0};  // 写指针
    alignas(cacheLineSize) std::atomic<size_t> readIndex_{0};   // 读指针
    double currentEmaDropRatio_{0.0};   // EMA 丢帧比例
    double targetRetentionRatio_{0.0};   // 目标保留比例
};

// E6: RecordPreDroppedFrame 记录预丢帧 PTS（第 23 行）
bool DropSyncCoordinator::RecordPreDroppedFrame(int64_t droppedPts)
{
    size_t wIdx = writeIndex_.load(std::memory_order_relaxed);
    ptsRingBuffer_[wIdx & queueMask] = droppedPts;
    writeIndex_.store((wIdx + 1) & queueMask, std::memory_order_release);
}

// E7: GetAndConsumePreDroppedCount 成对消耗预丢帧数（第 25 行）
uint32_t DropSyncCoordinator::GetAndConsumePreDroppedCount(int64_t currentPts)
{
    uint32_t count = 0;
    size_t rIdx = readIndex_.load(std::memory_order_acquire);
    size_t wIdx = writeIndex_.load(std::memory_order_acquire);
    while (rIdx != wIdx) {
        if (ptsRingBuffer_[rIdx & queueMask] < currentPts) {
            rIdx = (rIdx + 1) & queueMask;
            count++;
        } else {
            break;
        }
    }
    readIndex_.store(rIdx, std::memory_order_release);
    return count;
}

// E8: UpdateFeedback EMA 反馈更新（第 31 行）
void DropSyncCoordinator::UpdateFeedback(
    uint32_t preDroppedCount, bool currentDropped,
    double targetRetentionRatio, double currentSpeed)
{
    double currentDropRatio = preDroppedCount > 0 ? (currentDropped ? 1.0 : 0.0) : 0.0;
    // EMA 平滑：alpha = 0.1
    currentEmaDropRatio_ = 0.1 * currentDropRatio + 0.9 * currentEmaDropRatio_;
    targetRetentionRatio_ = targetRetentionRatio;
}
```

---

## 5. 异步丢帧分发器 AsyncDropDispatcher

**文件**: `async_drop_dispatcher.h` + `async_drop_dispatcher.cpp`

```cpp
// E9: AsyncDropDispatcher 独立 worker 线程（第 28-40 行）
class AsyncDropDispatcher {
    std::mutex taskMutex_;
    std::condition_variable taskCv_;
    std::queue<std::function<void()>> taskQueue_; // 任务队列
    std::thread workerThread_;                      // 独立 worker 线程
    std::atomic<bool> isWorking_{false};
};

// E10: WorkerLoop 任务循环（第 77 行）
void AsyncDropDispatcher::WorkerLoop()
{
    while (true) {
        std::function<void()> task;
        {
            std::unique_lock<std::mutex> lock(taskMutex_);
            taskCv_.wait(lock, [this]() {
                return !isWorking_.load() || !taskQueue_.empty();
            });
            if (!isWorking_.load() && taskQueue_.empty()) break;
            if (!taskQueue_.empty()) {
                task = std::move(taskQueue_.front());
                taskQueue_.pop();
            }
        }
        if (task) task();
    }
}
```

---

## 6. 策略引擎 IRetentionStrategy

**文件**: `strategies/retention_strategy.h`

```cpp
// E11: IRetentionStrategy 接口（第 24-32 行）
class IRetentionStrategy {
public:
    virtual ~IRetentionStrategy() = default;
    virtual bool MakeRetentionDecision(const FrameRetentionContext& ctx) = 0;
    virtual void UpdatePlaybackSpeed(double speed) = 0;
    virtual void Reset() = 0;
    virtual RetentionStrategyType GetMode() const = 0;
    virtual void OnDecodingPerformanceUpdate(double speed, double decFps) {}; // 性能回调
    virtual double GetCurrentRetentionRatio() const = 0;
};

struct FrameRetentionContext {
    int64_t ptsMs;
    int64_t sysTimeMs;
    uint32_t frameCount;
    uint32_t preDroppedCount = 0;
    const MVStats* mvStats = nullptr;
};
```

### 四策略实现

```cpp
// E12: FixedRatioRetentionStrategy 固定比例策略（成员变量）
class FixedRatioRetentionStrategy : public IRetentionStrategy {
    double accumulator_{0.0};     // 累加器
    double retentionRatio_{1.0};   // 保留比例
    bool isFirstFrame_{true};
    uint32_t cnt_{0};
    uint32_t dropCnt_{0};
};

// E13: AdaptiveRetentionStrategy MV自适应策略（成员变量）
class AdaptiveRetentionStrategy : public IRetentionStrategy {
    double currentSpeed_{1.0};
    uint32_t dropCount_{0};
    double currentTargetRatio_{0.0};
};
```

---

## 7. NALU / MV 分析器（dlopen 插件）

**文件**: `analyzers/nalu_analyzer.h`

```cpp
// E14: INaluAnalyzer NALU 分析器接口（第 22-28 行）
class INaluAnalyzer {
public:
    virtual ~INaluAnalyzer() = default;
    virtual void SetAuxInfoCallback(OnStreamAuxInfoParsed callback) = 0;
    virtual bool IsNonReferenceFrame(const std::shared_ptr<AVBuffer>& inputBuffer) = 0;
};

class NaluAnalyzerFactory {
public:
    static std::unique_ptr<INaluAnalyzer> CreateNaluAnalyzer(SFDCodecType codecType);
};

// E15: IMvAnalyzer MV 运动矢量分析器接口（mv_analyzer.h 第 16-25 行）
class IMvAnalyzer {
    virtual ~IMvAnalyzer() = default;
    virtual void SetStreamAuxInfo(const StreamAuxInfo& info) = 0;
    virtual void SetVideoInfo(uint32_t width, uint32_t height) = 0;
    virtual MVStats Analyze(const uint8_t *buffer) = 0;
    virtual SFDCodecType GetCodecType() const = 0;
};

class MvAnalyzerFactory {
public:
    static std::unique_ptr<IMvAnalyzer> CreateMvAnalyzer(SFDCodecType codecType);
    static bool IsCodecSupported(SFDCodecType codecType);
};
```

---

## 8. 动态配置更新

**文件**: `smart_fluency_decoding.cpp`

```cpp
// E16: UpdateDynamicConfig 运行时策略切换（第 121 行）
int32_t SmartFluencyDecoding::UpdateDynamicConfig(const Media::Format& format)
{
    // 从 format 解析 RetentionStrategyType 和 retentionRatio
    ParseDynamicFormat(format, newMode, newRatio);
    if (needUpdateStrategy) {
        auto newStrategy = RetentionStrategyFactory::CreateStrategy(newMode, newRatio);
        // 替换策略引擎（热切换）
        std::lock_guard<std::mutex> lock(configMutex_);
        strategy_ = std::move(newStrategy);
    }
}

// E17: UpdatePlaybackSpeed 动态速度更新（第 100 行）
void SmartFluencyDecoding::UpdatePlaybackSpeed(double speed)
{
    std::lock_guard<std::mutex> lock(configMutex_);
    currentPlaybackSpeed_ = (speed > 0.0 ? speed : DEFAULT_PLAYBACK_SPEED);
    if (strategy_) {
        strategy_->UpdatePlaybackSpeed(speed);
    }
}
```

---

## 9. DFX 统计

```cpp
// E18: GetStatistics 丢帧统计（smart_fluency_decoding.cpp 第 339 行）
void SmartFluencyDecoding::GetStatistics(uint32_t& totalFrames, uint32_t& droppedFrames) const
{
    totalFrames = totalOutputFrames_.load();
    droppedFrames = droppedOutputFrames_.load();
}

// E19: OnDecodingPerformanceUpdate 性能回调（smart_fluency_decoding.cpp 第 344 行）
void SmartFluencyDecoding::OnDecodingPerformanceUpdate(double speed, double decFps)
{
    std::lock_guard<std::mutex> lock(configMutex_);
    if (strategy_) {
        strategy_->OnDecodingPerformanceUpdate(speed, decFps);
    }
}
```

---

## 10. 与其他模块的关联

| 关联模块 | 关系 |
|----------|------|
| S231 VideoDecoderBase | SFD 作为 VideoDecoder 的附加组件，通过 Callbacks 注入丢帧逻辑 |
| S232 Av1Decoder | 支持 AV1 以外的 AVC/HEVC/VVC |
| S239 CodecBase | SFD 通过 CodecBase 获取解码器实例 |
| S236 HCodec DFX | DFX 丢帧统计上报 |
| S17 SmartFluencyDecodingManager | Manager 封装层，管理多个 SFD 实例 |

---

## Evidence 汇总

| ID | 文件 | 行号 | 证据内容 |
|----|------|------|---------|
| E1 | smart_fluency_decoding.cpp | ~220 | MakePreDecodeDecision 入口 |
| E2 | smart_fluency_decoding.cpp | ~201 | ExecutePreDrop 异步丢帧 |
| E3 | smart_fluency_decoding.cpp | ~252 | MakePostDecodeDecision 入口 |
| E4 | smart_fluency_decoding.cpp | ~317 | ParseMVData 从 SurfaceBuffer 提取 MV |
| E5 | drop_sync_coordinator.h | 35-50 | DropSyncCoordinator 128环形缓冲结构 |
| E6 | drop_sync_coordinator.h | ~23 | RecordPreDroppedFrame 记录PTS |
| E7 | drop_sync_coordinator.h | ~25 | GetAndConsumePreDroppedCount 成对消耗 |
| E8 | drop_sync_coordinator.h | ~31 | UpdateFeedback EMA反馈更新 |
| E9 | async_drop_dispatcher.h | 28-40 | AsyncDropDispatcher 成员变量 |
| E10 | async_drop_dispatcher.cpp | ~77 | WorkerLoop 任务循环 |
| E11 | retention_strategy.h | 24-32 | IRetentionStrategy 接口定义 |
| E12 | fixed_ratio_retention_strategy.h | - | FixedRatioRetentionStrategy 成员 |
| E13 | adaptive_retention_strategy.h | - | AdaptiveRetentionStrategy 成员 |
| E14 | nalu_analyzer.h | 22-28 | INaluAnalyzer 接口 |
| E15 | mv_analyzer.h | 16-25 | IMvAnalyzer 接口 |
| E16 | smart_fluency_decoding.cpp | ~121 | UpdateDynamicConfig 热切换 |
| E17 | smart_fluency_decoding.cpp | ~100 | UpdatePlaybackSpeed 动态速度 |
| E18 | smart_fluency_decoding.cpp | ~339 | GetStatistics 丢帧统计 |
| E19 | smart_fluency_decoding.cpp | ~344 | OnDecodingPerformanceUpdate 性能回调 |
| E20 | smart_fluency_decoding_types.h | - | RetentionStrategyType/SFDCodecType/SFDConfig/MVStats |
| E21 | retention_strategy_factory.cpp | - | RetentionStrategyFactory::CreateStrategy 四策略分发 |
| E22 | smart_fluency_decoding.cpp | ~72 | InitializeInternal 初始化入口 |
| E23 | smart_fluency_decoding.cpp | ~287 | EnsureNaluAnalyzer 懒创建 |
| E24 | smart_fluency_decoding.cpp | ~310 | EnsureMvAnalyzer 懒创建 |
| E25 | smart_fluency_decoding.cpp | ~228 | SetCallbacks 回调注册 |
