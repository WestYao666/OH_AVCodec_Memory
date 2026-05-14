# MEM-ARCH-AVCODEC-S148 - SmartFluencyDecoding 智能流畅解码

**主题ID**: MEM-ARCH-AVCODEC-S148  
**主题名称**: SmartFluencyDecoding 智能流畅解码——PreDecode/PostDecode双阶段丢帧策略与MV/NaluAnalyzer分析器  
**状态**: draft  
**创建日期**: 2026-05-15  
**Builder**: Builder Agent (minimax/MiniMax-M2.7)

---

## 1. 概述

SmartFluencyDecoding (SFD) 是 AVCodec 解码端的**流畅度优化框架**，通过分析 MV (运动矢量) 和 NALU (编码单元) 信息，在解码前后双阶段智能丢帧，在低性能设备上保持播放流畅。核心定位与 AFC (AdaptiveFramerateController，编码端降帧) 互补：SFD 管**解码丢帧**，AFC 管**编码降帧**。

---

## 2. 代码证据（本地镜像）

| 文件 | 行数 | 说明 |
|------|------|------|
| `services/services/codec/server/video/features/smart_fluency_decoding/smart_fluency_decoding.h` | 95 | 核心类定义 |
| `services/services/codec/server/video/features/smart_fluency_decoding/smart_fluency_decoding.cpp` | 453 | 核心实现 |
| `services/services/codec/server/video/features/smart_fluency_decoding/smart_fluency_decoding_builder.h` | 69 | 工厂构建器 |
| `services/services/codec/server/video/features/smart_fluency_decoding/smart_fluency_decoding_builder.cpp` | 257 | 工厂实现 |
| `services/services/codec/server/video/features/smart_fluency_decoding/interfaces/smart_fluency_decoding_types.h` | 76 | 类型定义 |
| `services/services/codec/server/video/features/smart_fluency_decoding/async_drop_dispatcher.h` | ~50 | 异步丢帧调度器 |
| `services/services/codec/server/video/features/smart_fluency_decoding/drop_sync_coordinator.h` | ~60 | 成对丢帧同步器 |
| `services/services/codec/server/video/features/smart_fluency_decoding/strategies/retention_strategy.h` | - | 策略基类 |
| `services/services/codec/server/video/features/smart_fluency_decoding/strategies/adaptive_retention_strategy.h/cpp` | - | 自适应策略 |
| `services/services/codec/server/video/features/smart_fluency_decoding/strategies/fixed_ratio_retention_strategy.h/cpp` | - | 固定比例策略 |
| `services/services/codec/server/video/features/smart_fluency_decoding/strategies/full_retention_strategy.h/cpp` | - | 全保留策略 |
| `services/services/codec/server/video/features/smart_fluency_decoding/strategies/auto_fallback_retention_strategy.h/cpp` | - | 自动回退策略 |
| `services/services/codec/server/video/features/smart_fluency_decoding/analyzers/mv_analyzer.h` | - | MV 分析器接口 |
| `services/services/codec/server/video/features/smart_fluency_decoding/analyzers/nalu_analyzer.h` | - | NALU 分析器接口 |
| `services/services/codec/server/video/features/smart_fluency_decoding/analyzers/mv_analyzer_so_loader.h/cpp` | - | MV 分析器 dlopen 加载 |
| `services/services/codec/server/video/features/smart_fluency_decoding/analyzers/nalu_analyzer_so_loader.h/cpp` | - | NALU 分析器 dlopen 加载 |

---

## 3. 核心架构

### 3.1 命名空间与类层级

```
OHOS::MediaAVCodec::SFD
├── SmartFluencyDecoding           # 主引擎类 (smart_fluency_decoding.h/cpp, 548行)
├── SmartFluencyDecodingBuilder    # 工厂构建器 (builder.h/cpp, 326行)
├── AsyncDropDispatcher            # 异步丢帧调度器 (async_drop_dispatcher.h/cpp)
├── DropSyncCoordinator            # 成对丢帧同步器 (drop_sync_coordinator.h/cpp)
├── IRetentionStrategy             # 策略基类 (abstract)
│   ├── FullRetentionStrategy
│   ├── AdaptiveRetentionStrategy
│   ├── FixedRatioRetentionStrategy
│   └── AutoFallbackRetentionStrategy
├── IMvAnalyzer                    # MV 分析器接口 (dlopen 插件)
└── INaluAnalyzer                  # NALU 分析器接口 (dlopen 插件)
```

### 3.2 双阶段丢帧决策

```cpp
// smart_fluency_decoding.h (L27-28)
bool MakePreDecodeDecision(uint32_t index);      // 解码前丢帧决策
bool MakePostDecodeDecision(uint32_t index, int64_t pts, const sptr<SurfaceBuffer> surfaceBuffer); // 解码后丢帧决策
```

- **PreDecode 阶段** (`MakePreDecodeDecision`)：在输入 buffer 入队前，根据 NALU 类型（SPS/PPS/IDR/non-IDR）和 MV 统计信息提前判断是否丢弃
- **PostDecode 阶段** (`MakePostDecodeDecision`)：在解码输出后，根据 SurfaceBuffer 的 MV 元数据和当前系统负载决定是否丢弃当前帧

### 3.3 四种 RetentionStrategy

```cpp
// smart_fluency_decoding_types.h
enum class RetentionStrategyType : int32_t {
    INVALID = -1,
    FULL = 0,           // 全保留，无丢帧
    ADAPTIVE = 1,       // 自适应：基于解码速度动态调整
    FIXED_RATIO = 2,    // 固定比例：按 retentionRatio 固定丢帧
    AUTO_RATIO = 3      // 自动比例：分析 MV 数据自动确定保留比例
};
```

Strategy 路由（builder.cpp 中）：
- AVC → `ADAPTIVE`
- HEVC → `FIXED_RATIO`
- VVC → `AUTO_RATIO`
- 若初始化失败 → `FULL` (降级)

### 3.4 MV/Nalu 双分析器（dlopen 插件）

```cpp
// smart_fluency_decoding.h (L65-67)
std::unique_ptr<IMvAnalyzer> mvAnalyzer_{nullptr};
std::unique_ptr<INaluAnalyzer> naluAnalyzer_{nullptr};
void EnsureNaluAnalyzer();  // dlopen 延迟加载
void EnsureMvAnalyzer();    // dlopen 延迟加载
```

- `mv_analyzer.h` / `nalu_analyzer.h` 定义接口
- `mv_analyzer_so_loader.cpp` / `nalu_analyzer_so_loader.cpp` 负责 dlopen 热加载插件
- MV 分析器从 SurfaceBuffer 解析帧级运动矢量统计 (`MVStats`)
- NALU 分析器解析编码单元类型，辅助 pre-decode 决策

### 3.5 DropSyncCoordinator 成对丢帧同步

```cpp
// drop_sync_coordinator.h
static constexpr size_t queueCapacity = 128;
int64_t ptsRingBuffer_[queueCapacity];  // PTS 环形缓冲区
alignas(cacheLineSize) std::atomic<size_t> writeIndex_{0};
alignas(cacheLineSize) std::atomic<size_t> readIndex_{0};
double currentEmaDropRatio_{0.0};         // EMA 平滑丢帧率
double targetRetentionRatio_{0.0};       // 目标保留率

bool RecordPreDroppedFrame(int64_t droppedPts);           // 记录已丢帧 PTS
uint32_t GetAndConsumePreDroppedCount(int64_t currentPts); // 成对消费：确保 I/P 帧配对丢帧
```

核心保证：I 帧和对应的 P 帧必须**成对丢帧**，避免画面撕裂。

### 3.6 AsyncDropDispatcher 异步丢帧调度

```cpp
// async_drop_dispatcher.h
void SubmitTask(std::function<void()> task);  // 提交异步丢帧任务
void WorkerLoop();                            // 独立 worker 线程
std::thread workerThread_;                   // 后台线程
std::atomic<bool> isWorking_{false};
```

异步执行丢弃操作，不阻塞解码主线程。

### 3.7 SFDConfig 配置结构

```cpp
// smart_fluency_decoding_types.h
struct SFDConfig {
    int32_t width{0};
    int32_t height{0};
    SFDCodecType codecType{SFDCodecType::INVALID};  // AVC=0, HEVC=1, VVC=2
    RetentionStrategyType initMode{RetentionStrategyType::INVALID};
    std::optional<double> retentionRatio{std::nullopt};  // FIXED_RATIO 时使用
};
```

### 3.8 MVStats 运动矢量统计

```cpp
// smart_fluency_decoding_types.h
typedef struct {
    uint32_t totalBlocks;           // 总块数
    uint32_t validBlocks;            // 有效块
    uint32_t skipBlocks;             // skip 块数
    uint32_t zeroMotionBlocks;       // 零运动块
    double avgRefDist;               // 平均参考距离
    double perceptualMagnitude;      // 感知幅度
    double motionConsistency;        // 运动一致性
    double zeroMotionRatio;          // 零运动比例
} MVStats;
```

### 3.9 性能反馈更新

```cpp
// smart_fluency_decoding.h (L31)
void OnDecodingPerformanceUpdate(double speed, double decFps);
// speed: 当前播放速度 (e.g. 1.0x)
// decFps: 实际解码帧率
// → 更新 EMA Drop Ratio → 反馈给 DropSyncCoordinator → 调整 targetRetentionRatio
```

---

## 4. 与已有记忆的关联

| 关联 | 说明 |
|------|------|
| **S17** | SFD 早期草案（已 approved），S148 为源码增强版，基于本地镜像 `/home/west/av_codec_repo` 深度分析 |
| **S43** | AFC (AdaptiveFramerateController) 管**编码降帧**，SFD 管**解码丢帧**，两者互补 |
| **S55** | 模块间回调链路，SFD 的 `AsyncDropInputCallback` / `AsyncDropOutputCallback` 属于Codec回调体系 |
| **S39** | VideoDecoder，SFD 挂载于解码器输出端，分析 `SurfaceBuffer` MV 数据 |
| **S21** | CodecClient IPC，SFDConfig 通过 CodecServer 注入到解码器 |

---

## 5. 技术细节

### 5.1 丢帧决策流程

```
输入 Buffer
    ↓
MakePreDecodeDecision(index)  ← NaluAnalyzer 分析 NALU 类型
    ↓ (不丢弃)
AVCodec 解码
    ↓
SurfaceBuffer (含 MV 元数据)
    ↓
MakePostDecodeDecision(index, pts, surfaceBuffer)  ← MVStats + DropSyncCoordinator
    ↓ (丢弃)
AsyncDropDispatcher SubmitTask → 后台线程丢弃
    ↓ (保留)
Render 输出
```

### 5.2 DropSyncCoordinator EMA 反馈

```cpp
// drop_sync_coordinator.h/cpp
void UpdateFeedback(uint32_t preDroppedCount, bool currentDropped,
                    double targetRetentionRatio, double currentSpeed);
// currentEmaDropRatio_ 平滑更新 → 下一帧决策参考
```

### 5.3 dlopen 插件加载

```cpp
// mv_analyzer_so_loader.cpp / nalu_analyzer_so_loader.cpp
// 延迟加载 .so 插件，不在主流程阻塞
void EnsureMvAnalyzer() { if (!mvAnalyzer_) mvAnalyzer_ = MvAnalyzerSoLoader::Load(...); }
```

### 5.4 播放速度联动

```cpp
// smart_fluency_decoding.cpp
void UpdatePlaybackSpeed(double speed);  // 速度变化时重新配置策略
```

---

## 6. 关键成员变量

```cpp
// smart_fluency_decoding.h (L59-69)
mutable std::mutex configMutex_;
std::unique_ptr<DropSyncCoordinator> dropSyncCoordinator_{nullptr};
std::unique_ptr<AsyncDropDispatcher> asyncDispatcher_{nullptr};
std::unique_ptr<IRetentionStrategy> strategy_{nullptr};
std::unique_ptr<IMvAnalyzer> mvAnalyzer_{nullptr};
std::unique_ptr<INaluAnalyzer> naluAnalyzer_{nullptr};
```

---

## 7. 状态与生命周期

1. `Initialize(const SFDConfig&)` → 创建策略、分析器、协调器
2. `UpdatePlaybackSpeed(double)` → 速度变化时重配
3. `UpdateDynamicConfig(Media::Format)` → 动态格式更新（解析 retentionRatio）
4. `MakePreDecodeDecision` / `MakePostDecodeDecision` → 每帧决策
5. `Flush()` → 清空所有缓冲状态

---

## 8. 与 S17 的区别

| 维度 | S17 (早期草案) | S148 (本地镜像增强版) |
|------|---------------|---------------------|
| 源码 | 推测/早期 | 本地镜像实际行号级 evidence |
| 行数 | 未知 | 548行核心类 + 326行Builder + 各策略文件 |
| 分析器 | 提及 dlopen | 具体接口定义 + so_loader 实现 |
| DropSyncCoordinator | 提及成对丢帧 | 具体 ring buffer 实现 (128 PTS, cache line aligned) |
| 策略类型 | 四种 | 四种 + AUTO_RATIO 降级路径 |

---

**草案状态**: 待提交审批  
**下一步**: Builder 提交 pending_approval → 等待耀耀审批