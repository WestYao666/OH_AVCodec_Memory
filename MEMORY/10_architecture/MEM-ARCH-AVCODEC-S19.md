---
type: architecture
id: MEM-ARCH-AVCODEC-S19
status: pending_approval
topic: TemporalScalability 时域可分级视频编码——SVC-TL/SVC-LTR双模式与CodecParamChecker七步校验链
created_at: "2026-04-24T08:51:00+08:00"
evidence: |
  - source: /home/west/av_codec_repo/services/services/codec/server/video/temporal_scalability.h
    anchor: "Line 31-32: constexpr int32_t MIN_TEMPORAL_GOPSIZE = 2; constexpr int32_t DEFAULT_TEMPORAL_GOPSIZE = 4;"
  - source: /home/west/av_codec_repo/services/services/codec/server/video/temporal_scalability.h
    anchor: "Line 39: bool svcLTR_ = false; // true: LTR mode"
  - source: /home/west/av_codec_repo/services/services/codec/server/video/temporal_scalability.h
    anchor: "Line 57-59: int32_t gopSize_; int32_t temporalGopSize_; int32_t tRefMode_;"
  - source: /home/west/av_codec_repo/services/services/codec/server/video/temporal_scalability.cpp
    anchor: "Line 42-55: TemporalScalability::IsLTRSolution() — LTR判定逻辑"
  - source: /home/west/av_codec_repo/services/services/codec/server/video/temporal_scalability.cpp
    anchor: "Line 57-63: TemporalScalability::LTRFrameNumCalculate() — LTR帧数计算"
  - source: /home/west/av_codec_repo/services/services/codec/server/video/temporal_scalability.cpp
    anchor: "Line 66-86: TemporalScalability::ValidateTemporalGopParam() — 参数校验与默认值填充"
  - source: /home/west/av_codec_repo/services/services/codec/server/video/codec_param_checker.h
    anchor: "Line 24-27: CodecScenario::CODEC_SCENARIO_ENC_TEMPORAL_SCALABILITY / CODEC_SCENARIO_ENC_NORMAL"
  - source: /home/west/av_codec_repo/services/services/codec/server/video/codec_param_checker.cpp
    anchor: "Line 40-44: CODEC_SCENARIO_TO_STRING map — 4种CodecScenario"
  - source: /home/west/av_codec_repo/services/services/codec/server/video/codec_param_checker.cpp
    anchor: "Line 84-89: TemporalScalabilityChecker / BFrameScenarioChecker 函数声明"
  - source: /home/west/av_codec_repo/services/services/codec/server/video/codec_param_checker.cpp
    anchor: "Line 98-100: TemporalGopSizeChecker / TemporalGopReferenceModeChecker / UniformlyScaledReferenceChecker"
  - source: /home/west/av_codec_repo/services/services/codec/server/video/codec_param_checker.cpp
    anchor: "Line 104: LTRFrameCountChecker — LTR帧数合法性校验"
---

## 1. 概述

TemporalScalability（时域可分级编码）是 OpenHarmony AVCodec 视频编码器的一种增强能力，通过在码流中插入时域分层（Temporal Layer），实现：

- **码率自适应**：低算力设备可只解码低层帧，高算力设备解码全部帧
- **丢帧策略友好**：分层结构天然支持时间域的帧丢弃，不需要复杂参考链重算
- **LTR（Long Term Reference）支持**：跨 GOP 维持参考，提高压缩效率

> 对应 CodecScenario::CODEC_SCENARIO_ENC_TEMPORAL_SCALABILITY

---

## 2. 核心数据结构

### 2.1 CodecScenario 枚举

```cpp
// codec_param_checker.h, Line 24-27
enum class CodecScenario : int32_t {
    CODEC_SCENARIO_ENC_NORMAL = 0,
    CODEC_SCENARIO_ENC_TEMPORAL_SCALABILITY,  // 时域可分级编码
    CODEC_SCENARIO_ENC_ENABLE_B_FRAME,         // 启用B帧
    CODEC_SCENARIO_DEC_NORMAL = (1 << 30),    // 解码器普通模式
};
```

### 2.2 TemporalScalability 关键成员

```cpp
// temporal_scalability.h, Line 39, 49-59
bool svcLTR_ = false;          // true: LTR模式; false: SVC-TL模式
bool isMarkLTR_ = false;       // 当前帧是否标记为LTR
bool isUseLTR_ = false;        // 是否使用LTR参考
int32_t ltrPoc_ = 0;            // LTR帧的POC（Picture Order Count）
int32_t poc_ = 0;               // 当前帧POC
int32_t temporalPoc_ = 0;       // 时域POC（分层标记）
int32_t gopSize_ = DEFAULT_GOPSIZE;        // 30
int32_t temporalGopSize_ = 0;   // 时域GOP大小（默认4）
int32_t tRefMode_ = 0;          // 时域参考模式
```

---

## 3. 双模式判定：SVC-TL vs SVC-LTR

### 3.1 IsLTRSolution() 判定逻辑

```cpp
// temporal_scalability.cpp, Line 42-55
bool TemporalScalability::IsLTRSolution()
{
    // 条件1：参考模式非 UNIFORMLY_SCALED_REFERENCE
    if (tRefMode_ != static_cast<int32_t>(TemporalGopReferenceMode::UNIFORMLY_SCALED_REFERENCE)) {
        return true; // → LTR 模式
    }
    // 条件2：temporalGopSize > 默认GOP(30)
    if (temporalGopSize_ > DEFAULT_TEMPORAL_GOPSIZE) { // 4
        return true; // → LTR 模式
    }
    // 条件3：AVC编码器且 temporalGopSize > 最小值(2)
    if (name_.find("avc") != string::npos && temporalGopSize_ > MIN_TEMPORAL_GOPSIZE) { // 2
        return true; // → LTR 模式
    }
    return false; // → SVC-TL 模式
}
```

**判定结论**：
- 返回 `true` → **SVC-LTR 模式**（Long Term Reference，适合复杂场景）
- 返回 `false` → **SVC-TL 模式**（Temporal Layer，均匀分层）

### 3.2 LTR 帧数计算

```cpp
// temporal_scalability.cpp, Line 57-63
int32_t TemporalScalability::LTRFrameNumCalculate(int32_t tGopSize) const
{
    if (tRefMode_ != static_cast<int32_t>(TemporalGopReferenceMode::UNIFORMLY_SCALED_REFERENCE)) {
        return DEFAULT_VIDEO_LTR_FRAME_NUM; // 固定返回2
    }
    return (tGopSize / DEFAULT_TEMPORAL_GOPSIZE) + 1; // e.g. 30/4+1=8
}
```

---

## 4. 参数校验流程

### 4.1 ValidateTemporalGopParam() — 三参 数提取与填充

```cpp
// temporal_scalability.cpp, Line 66-86
void TemporalScalability::ValidateTemporalGopParam(Format &format)
{
    // 1. 提取 gopSize（无则用默认值30）
    format.GetIntValue("video_encoder_gop_size", gopSize_);

    // 2. 提取 temporalGopSize
    if (!format.GetIntValue(Tag::VIDEO_ENCODER_TEMPORAL_GOP_SIZE, temporalGopSize_)) {
        // 默认策略：gopSize <= 4 ? 2 : 4
        temporalGopSize_ = (gopSize_ <= DEFAULT_TEMPORAL_GOPSIZE) ? MIN_TEMPORAL_GOPSIZE : DEFAULT_TEMPORAL_GOPSIZE;
        format.PutIntValue(Tag::VIDEO_ENCODER_TEMPORAL_GOP_SIZE, temporalGopSize_);
    }

    // 3. 提取参考模式（无则用 ADJACENT_REFERENCE）
    if (!format.GetIntValue(Tag::VIDEO_ENCODER_TEMPORAL_GOP_REFERENCE_MODE, tRefMode_)) {
        tRefMode_ = static_cast<int32_t>(TemporalGopReferenceMode::ADJACENT_REFERENCE);
        format.PutIntValue(Tag::VIDEO_ENCODER_TEMPORAL_GOP_REFERENCE_MODE, tRefMode_);
    }

    // 4. 判定双模式
    svcLTR_ = IsLTRSolution();

    // 5. LTR模式下：自动填充LTR帧数，关闭surface input callback
    if (svcLTR_) {
        int32_t ltrFrameNum = LTRFrameNumCalculate(temporalGopSize_);
        format.RemoveKey(Tag::VIDEO_ENCODER_ENABLE_TEMPORAL_SCALABILITY);
        format.PutIntValue(Tag::VIDEO_ENCODER_LTR_FRAME_COUNT, ltrFrameNum);
        format.PutIntValue(Tag::VIDEO_ENCODER_ENABLE_SURFACE_INPUT_CALLBACK, ENABLE_PARAMETER_CALLBACK);
    }
}
```

### 4.2 CodecParamChecker 七步校验链

当 CodecScenario = CODEC_SCENARIO_ENC_TEMPORAL_SCALABILITY 时，CodecParamChecker 按以下顺序校验：

```cpp
// codec_param_checker.cpp, Line 84-109
std::optional<CodecScenario> TemporalScalabilityChecker(...);   // 步骤1: 场景识别
int32_t TemporalGopSizeChecker(...);        // 步骤2: 时域GOP大小
int32_t TemporalGopReferenceModeChecker(...); // 步骤3: 参考模式
int32_t UniformlyScaledReferenceChecker(...); // 步骤4: 均匀分级参考
int32_t LTRFrameCountChecker(...);         // 步骤5: LTR帧数
int32_t ScalingModeChecker(...);           // 步骤6: 缩放模式
int32_t PostProcessingChecker(...);        // 步骤7: 后处理能力
```

> 对应 VideoTranscoder（转码器）或高配置编码器场景

---

## 5. 与 CodecServer 的集成

### 5.1 集成点

TemporalScalability 由 **CodecServer**（video codec server）在编码配置阶段持有和使用：

```
CodecServer::Configure()
  → CodecParamChecker::CheckConfigureValid()
    → CodecScenario::CODEC_SCENARIO_ENC_TEMPORAL_SCALABILITY 识别
  → TemporalScalability::ValidateTemporalGopParam()
  → svcLTR_ 判定 + LTR参数自动填充
  → 后续编码流程使用 temporalGopSize_ / tRefMode_ / svcLTR_
```

### 5.2 编码过程使用

```cpp
// temporal_scalability.h, Line 43-45
void ConfigureLTR(uint32_t index);              // 配置指定索引帧为LTR
void SetDisposableFlag(shared_ptr<AVBuffer>);  // 设置可丢弃标记
void MarkLTRDecision();                        // LTR标记决策（temporalPoc_%temporalGopSize_==0）
```

---

## 6. 与相关主题的关联

| 主题 | 关联点 |
|------|--------|
| S3: CodecServer Pipeline | CodecServer 是 TemporalScalability 的持有者 |
| S4: Surface/Buffer Mode | Surface输入模式下，EnableSurfaceInputCallback 与 TemporalScalability 联动 |
| S12: VideoResizeFilter | VideoResizeFilter 是转码后处理链的一员，与 TemporalScalability 同属 CodecServer video features |
| S17: SmartFluencyDecoding | 智能丢帧与时域分层共享"帧可丢弃"的语义，但侧重点不同 |
| P1f: Codec Engine 架构 | TemporalScalability 属于 CodecServer（服务层），通过 HDI 调用底层硬件编码器 |

---

## 7. 关键常量汇总

| 常量 | 值 | 含义 |
|------|----|------|
| DEFAULT_GOPSIZE | 30 | 默认 GOP 大小（帧数） |
| MIN_TEMPORAL_GOPSIZE | 2 | 最小时域 GOP |
| DEFAULT_TEMPORAL_GOPSIZE | 4 | 默认时域 GOP（temporalGopSize） |
| DEFAULT_VIDEO_LTR_FRAME_NUM | 2 | LTR 模式默认 LTR 帧数 |
| ENABLE_PARAMETER_CALLBACK | 1 | 启用参数回调标志 |
