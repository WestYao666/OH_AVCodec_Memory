# MEM-ARCH-AVCODEC-S148 (DRAFT)

> **Status:** pending_approval
> **Submitted at:** 2026-05-15T09:40:48+08:00  
> **Topic:** SmartFluencyDecoding 智能流畅解码——PreDecode/PostDecode 双阶段丢帧策略与 MV/NaluAnalyzer 分析器  
> **Tags:** AVCodec, MediaEngine, Decoder, SmartFluencyDecoding, SFD, DropStrategy, MVAnalyzer, NaluAnalyzer, AsyncDrop, RetentionStrategy, DropSyncCoordinator, MediaCodec, DecoderAdapter  
> **Domain:** 新需求开发/问题定位/流畅度优化  
> **Backlog:** S148 | **pending_approval**  
> **Evidence source:** repo_tmp (本地镜像) + GitCode https://gitcode.com/openharmony/multimedia_av_codec  

---

## 1. 概述

SmartFluencyDecoding（SFD）是 AVCodec 解码器的**智能流畅度优化组件**，位于 `services/codec/server/video/features/smart_fluency_decoding/` 目录。通过**双阶段丢帧决策**（PreDecode + PostDecode）结合 NALU 分析器（识别非参考帧）和 MV 分析器（运动矢量统计），在保证播放质量的前提下主动丢弃冗余帧，提升解码流畅度。

**支持编解码器：** AVC / HEVC / VVC（三者均通过 `SFDCodecType` 枚举标识）

**核心文件（共 10+ 个源文件，总计约 2900 行）：**
- smart_fluency_decoding.cpp (L1-582) — 核心引擎，双阶段决策
- smart_fluency_decoding.h (L1-126) — 核心类声明
- smart_fluency_decoding_manager.cpp (L1-358) — Manager 封装
- smart_fluency_decoding_manager.h (L1-87) — Manager 类声明
- smart_fluency_decoding_types.h (L1-101, interfaces/) — 类型与枚举
- smart_fluency_decoding_builder.cpp (L1-127) — Builder 构造器
- smart_fluency_decoding_builder.h (L1-52) — Builder 声明
- drop_sync_coordinator.cpp (L1-113) + .h (L1-53) — 丢帧同步协调
- async_drop_dispatcher.cpp (L1-97) + .h (L1-48) — 异步丢帧调度
- strategies/ — 5 种保留策略子目录
  - retention_strategy.h (L1-50) — 策略基类 IRetentionStrategy
  - retention_strategy_factory.cpp (L1-55) + .h — 策略工厂
  - fixed_ratio_retention_strategy.cpp (L1-94) + .h (L1-50)
  - adaptive_retention_strategy.cpp (L1-160) + .h (L1-47)
  - full_retention_strategy.cpp (L1-71) + .h (L1-42)
  - auto_fallback_retention_strategy.cpp (L1-67) + .h (L1-45)
- interfaces/nalu_analyzer_c_api.h (L1-41) — NALU 分析器 C 接口
- interfaces/mv_analyzer_c_api.h (L1-41) — MV 分析器 C 接口

---

## 2. 双阶段丢帧决策架构

### 2.1 PreDecode 阶段（L1-300）

**触发位置：** `smart_fluency_decoding.cpp:341-390` (`MakePreDecodeDecision`)

```
NALU 分析器（NaluAnalyzer）
    ↓ IsNonReferenceFrame(buffer)
非参考帧判断 → EMA 比率饱和检测 → 丢帧 / 保留
```

**决策逻辑源码（smart_fluency_decoding.cpp:365-386）：**
- L365: `if (naluAnalyzer_ && caps.requiresNalu)` — 非参考帧检测
- L366-368: `res.isNonRef = naluAnalyzer_->IsNonReferenceFrame(buffer)` — 核心判断
- L370-376: EMA 比率比较（`GetEmaRatio()` vs `targetRatio`）决定 PRE_DROP / PRE_RETAIN
- L383: `ExecutePreDrop(index, buffer)` — 异步提交丢帧任务

**关键数据结构（smart_fluency_decoding.h:67-78）：**
- `PreDecResult { shouldRetain, isNonRef, reason, naluCostUs }`
- `StrategyCaps { isPassthrough, requiresNalu, requiresMv, targetRatio }`

### 2.2 PostDecode 阶段（L450-480）

**触发位置：** `smart_fluency_decoding.cpp:450-480` (`MakePostDecodeDecision`)

```
SurfaceBuffer 元数据 (ATTRKEY_VIDEO_DECODER_MV)
    ↓ ParseMVData(surfaceBuffer)
MVStats { totalBlocks, validBlocks, skipBlocks, zeroMotionBlocks,
          avgRefDist, perceptualMagnitude, motionConsistency, zeroMotionRatio }
    ↓ IRetentionStrategy->MakeRetentionDecision(ctx)
保留 / 丢帧
```

**MV 数据提取源码（smart_fluency_decoding.cpp:494-512）：**
- L497-499: `surfaceBuffer->GetMetadata(V2_0::ATTRKEY_VIDEO_DECODER_MV, vec)` — 获取 MV 元数据
- L503: `mvStats = mvAnalyzer_->Analyze(input, data.length)` — 调用 MV 分析器
- L470-476: `strategy_->MakeRetentionDecision(ctx)` — 策略决策

**关键数据结构（smart_fluency_decoding_types.h:32-40）：**
```cpp
typedef struct {
    uint32_t totalBlocks;
    uint32_t validBlocks;
    uint32_t skipBlocks;
    uint32_t zeroMotionBlocks;
    double avgRefDist;
    double perceptualMagnitude;
    double motionConsistency;
    double zeroMotionRatio;
} MVStats;
```

---

## 3. 五大保留策略体系

### 3.1 策略类型枚举（smart_fluency_decoding_types.h:58-64）

```cpp
enum class RetentionStrategyType : int32_t {
    INVALID = -1,
    FULL = 0,         // 全保留，不丢帧
    ADAPTIVE = 1,     // 自适应决策树
    FIXED_RATIO = 2,  // 固定比率
    AUTO_RATIO = 3    // 自动比率
};
```

### 3.2 策略工厂（retention_strategy_factory.cpp:retention_strategy_factory.h）

L1-55 `CreateStrategy(mode, retentionRate)` 根据 `RetentionStrategyType` 创建对应策略实例。

### 3.3 各策略特性

| 策略 | NALU分析 | MV分析 | 典型应用场景 |
|------|----------|--------|--------------|
| FULL | ✅ | ❌ | 质量优先 |
| ADAPTIVE | ✅ | ✅ | 决策树+速度自适应 |
| FIXED_RATIO | ✅ | ❌ | 固定丢帧比率 |
| AUTO_RATIO | ✅ | ❌ | 自动比率调整 |

---

## 4. 丢帧同步协调器（DropSyncCoordinator）

**位置：** drop_sync_coordinator.cpp (L1-113) + .h (L1-53)

**核心机制：** 环形缓冲区（RingBuffer）+ EMA 指数移动平均

**关键设计（drop_sync_coordinator.h:30-40）：**
- L30-31: `queueCapacity = 1024`, `queueMask = 1023` — 1024 循环队列
- L34-37: `ptsRingBuffer_[1024]`, `isConsumed_[1024]` — PTS 记录 + 消费标记
- L39-40: `writeIndex_` / `readIndex_` — 原子操作（`alignas(cacheLineSize)` 防止伪共享）
- L42: `emaRatio_` — EMA 平滑后的丢帧比率

**丢帧协调流程（drop_sync_coordinator.cpp）：**
- L1-30: `RecordPreDroppedFrame(pts, speed)` — 记录 PreDrop 的 PTS
- L31-60: `GetAndConsumePreDroppedCount(currentPts)` — 查询并消费对应数量的 PreDrop
- L61-90: `UpdateFeedback(isRetained, speed)` — 根据实际保留情况更新 EMA

---

## 5. 异步丢帧调度器（AsyncDropDispatcher）

**位置：** async_drop_dispatcher.cpp (L1-97) + .h (L1-48)

使用 `std::function` 异步提交丢帧任务，与主解码线程解耦。

**关键接口：**
- L1-48.h: `SubmitTask(std::function<void()> task)` — 提交异步任务

---

## 6. NALU 分析器接口（nalu_analyzer_c_api.h）

**L1-41 C API 定义：**
```c
typedef void* NaluAnalyzerHandle;
NaluAnalyzerHandle CreateNaluAnalyzer(int32_t codecType);  // codecType: 0=AVC, 1=HEVC, 2=VVC
void DestroyNaluAnalyzer(NaluAnalyzerHandle analyzer);
bool IsNonReferenceFrame(NaluAnalyzerHandle analyzer, const uint8_t* bufferAddr, uint32_t bufferSize);
typedef void (*NaluStreamAuxInfoCallback)(const StreamAuxInfo* info, void* userData);
void SetCallback(NaluAnalyzerHandle analyzer, NaluStreamAuxInfoCallback cb, void* userData);
```

**StreamAuxInfo（smart_fluency_decoding_types.h:26-31）：**
```c
typedef struct {
    uint32_t directSpatialMvPredFlag;
    uint32_t direct8x8InferenceFlag;
    uint32_t frameMbsOnlyFlag;
    uint32_t ctuSize;
} StreamAuxInfo;
```

**在 SmartFluencyDecoding 中的集成（smart_fluency_decoding.cpp:514-541）：**
- L514-531: `EnsureNaluAnalyzer()` — 懒创建，`NaluAnalyzerFactory::CreateNaluAnalyzer`
- L533-541: 回调注册 `SetAuxInfoCallback` 接收 `StreamAuxInfo` 并转发给 `mvAnalyzer_->SetStreamAuxInfo`

---

## 7. Manager 封装层（SmartFluencyDecodingManager）

**位置：** smart_fluency_decoding_manager.h (L1-87) + .cpp (L1-358)

Manager 是对 SmartFluencyDecoding 引擎的封装，提供给 DecoderAdapter 等外部组件调用。

**核心接口（smart_fluency_decoding_manager.h:27-43）：**
- L28: `Configure(const Media::Format& format)` — 配置 SFD 参数
- L29: `SetCallbacks(...)` — 设置输入/输出丢帧回调
- L32: `MakePreDecodeDecision(index)` / L33: `MakePostDecodeDecision(...)` — 双阶段决策入口
- L34: `EnableMVOutput(format)` — 启用 MV 元数据输出
- L36: `CacheCsdData(index)` / `ExtractCsdData(buffer)` — CSD 数据缓存与提取

**关键成员（smart_fluency_decoding_manager.h:47-60）：**
- `std::unique_ptr<SmartFluencyDecoding> sfd_` — 核心引擎实例
- `std::vector<uint8_t> cachedCsdData_` — CSD 数据缓存
- `std::unordered_map<int64_t, sptr<SurfaceBuffer>> surfaceBufMap_` — 帧级 SurfaceBuffer 映射

---

## 8. Builder 构造器模式（SmartFluencyDecodingBuilder）

**位置：** smart_fluency_decoding_builder.h (L1-52) + .cpp (L1-127)

采用 Builder 模式构造 `SmartFluencyDecoding` 实例，分离配置与构造。

**Builder 接口（smart_fluency_decoding_builder.h:24-32）：**
```cpp
SmartFluencyDecodingBuilder& SetVideoWidth(int32_t width);
SmartFluencyDecodingBuilder& SetVideoHeight(int32_t height);
SmartFluencyDecodingBuilder& SetCodecMime(const std::string& mime);
SmartFluencyDecodingBuilder& UpdatePlaybackSpeed(double speed);
SmartFluencyDecodingBuilder& SetFromFormat(const Media::Format& format);
std::unique_ptr<SmartFluencyDecoding> Build();
```

---

## 9. 配置与动态更新

### 9.1 静态配置（smart_fluency_decoding.cpp:48-67）

```cpp
config_.width > 0 && config_.height > 0  // 尺寸校验（L48）
config_.codecType != SFDCodecType::INVALID  // 编解码器类型校验（L52）
```

### 9.2 动态配置（smart_fluency_decoding.cpp:157-178）

**`UpdateDynamicConfig` 支持运行时更新：**
- L157-159: 从 `Media::Format` 解析 `VIDEO_DECODER_FRAME_RETENTION_RATIO`
- L160-173: 从 `Media::Format` 解析 `VIDEO_DECODER_FRAME_RETENTION_MODE` → 映射到 `RetentionStrategyType`
- L175-178: 若模式变更，调用 `ApplyNewStrategy()` 热更新策略

### 9.3 速度更新（smart_fluency_decoding.cpp:101-117）

**`UpdatePlaybackSpeed` 动态更新播放速度：**
- L104: 速度值通过 `DoubleUtils::IsGreater(speed, 0.0)` 合法性校验
- L105: `currentPlaybackSpeed_` 成员变量更新
- L106: 策略层同步更新 `strategy_->UpdatePlaybackSpeed(speed)`

---

## 10. 决策原因枚举（SfdDecisionReason）

**位置：** smart_fluency_decoding_types.h:42-56

```cpp
enum class SfdDecisionReason : int32_t {
    // Pre-Decode
    PRE_RETAIN_REFERENCE = 1,         // 保留：参考帧
    PRE_RETAIN_TARGET_FULL = 2,        // 保留：目标比率 100%（FULL 模式）
    PRE_RETAIN_EMA_SATISFIED = 3,      // 保留：EMA 比率已满足目标
    PRE_DROP_EMA_UNSATISFIED = 4,      // 丢弃：EMA 比率过高需补偿

    // Post-Decode
    POST_BYPASSED = 10,               // 绕过：PreDecode 已丢帧
    POST_RETAIN_FULL = 11,            // 保留：Passthrough (FULL) 策略
    POST_RETAIN_FIXED_ACC = 12,       // 保留：FixedRatio 累加器达阈值
    POST_DROP_FIXED_ACC = 13,         // 丢弃：FixedRatio 累加器低于阈值
    POST_RETAIN_ADAPTIVE_SPEED = 14,  // 保留：Adaptive 低速播放
    POST_RETAIN_ADAPTIVE_DT = 15,      // 保留：Adaptive 决策树允许保留
    POST_RETAIN_ADAPTIVE_MAX_DROP = 16,// 保留：Adaptive 最大连续丢帧+强制释放
    POST_DROP_ADAPTIVE_DT = 17,       // 丢弃：Adaptive 决策树建议丢弃
    POST_RETAIN_AUTO_FALLBACK = 18,   // 保留：AutoFallback 安全间隔释放
};
```

---

## 11. 关联主题

| 关联 | 关系 |
|------|------|
| S14 (FilterChain) | FilterPipeline 体系，SFD 嵌入 Decoder Filter |
| S20 (CodecServer) | CodecServer 生命周期管理 |
| S46 (Transcoder) | Transcoder 场景下 VideoResizeFilter 与 SFD 联动 |
| S121 (错误码) | SFD 错误码映射到 `AVCodecServiceErrCode` |
| S137 (SA Codec) | IPC 通信层，SFD Manager 通过 CodecClient 跨进程 |
| S149 (Transcoder Pipeline) | 转码场景 Encode→Decode 桥接与 SFD 配合 |

---

## 12. Evidence 汇总

| # | 源文件 | 行号 | 描述 |
|---|--------|------|------|
| 1 | smart_fluency_decoding.h | 41-50 | 核心类 SmartFluencyDecoding 声明，双阶段决策方法 |
| 2 | smart_fluency_decoding.cpp | 48-67 | Initialize 配置校验逻辑 |
| 3 | smart_fluency_decoding.cpp | 101-117 | UpdatePlaybackSpeed 动态速度更新 |
| 4 | smart_fluency_decoding.cpp | 157-178 | UpdateDynamicConfig 运行时策略热更新 |
| 5 | smart_fluency_decoding.cpp | 341-390 | MakePreDecodeDecision PreDecode 决策核心（含 EMA 比较） |
| 6 | smart_fluency_decoding.cpp | 450-480 | MakePostDecodeDecision PostDecode 决策核心 |
| 7 | smart_fluency_decoding.cpp | 494-512 | ParseMVData 从 SurfaceBuffer 提取 MV 元数据 |
| 8 | smart_fluency_decoding.cpp | 514-541 | EnsureNaluAnalyzer 懒创建 + StreamAuxInfo 回调链 |
| 9 | smart_fluency_decoding_types.h | 26-40 | MVStats / StreamAuxInfo 数据结构定义 |
| 10 | smart_fluency_decoding_types.h | 58-64 | RetentionStrategyType 五种策略枚举 |
| 11 | smart_fluency_decoding_types.h | 42-56 | SfdDecisionReason 18 种决策原因枚举 |
| 12 | drop_sync_coordinator.h | 30-40 | RingBuffer 1024 + EMA + 原子上下文 |
| 13 | retention_strategy.h | 24-39 | IRetentionStrategy 接口（MakeRetentionDecision） |
| 14 | nalu_analyzer_c_api.h | 29-37 | NALU 分析器 C API 四函数接口 |
| 15 | smart_fluency_decoding_manager.h | 27-43 | Manager 类双阶段决策入口 + CSD 缓存 |
| 16 | smart_fluency_decoding_builder.h | 24-32 | Builder 模式五配置方法 + Build() |
| 17 | smart_fluency_decoding.cpp | 248-261 | ExecutePreDrop 异步丢帧提交机制 |
| 18 | smart_fluency_decoding.cpp | 393-412 | ExecutePostDrop 异步输出缓冲丢弃 |

---

## 13. 附录：关键常量

| 常量 | 值 | 定义位置 |
|------|-----|----------|
| MIN_RETENTION_RATIO | 0.01 | smart_fluency_decoding_types.h:54 |
| MAX_RETENTION_RATIO | 1.0 | smart_fluency_decoding_types.h:54 |
| queueCapacity | 1024 | drop_sync_coordinator.h:30 |
| cacheLineSize | 64 | drop_sync_coordinator.h:32 |
| DOMAIN_SFD | LOG_DOMAIN_SFD | smart_fluency_decoding.cpp:33 |