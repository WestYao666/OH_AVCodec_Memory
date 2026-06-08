---
id: MEM-ARCH-AVCODEC-S224
title: VideoCodecParamChecker 视频编码参数校验框架——CodecScenario三场景+20+维度校验+自动修正
type: architecture_fact
scope: [AVCodec, VideoCodec, ParamChecker, CodecScenario, TemporalScalability, BFrame, AutoCorrection]
status: draft
created: 2026-06-08T22:30
source: /home/west/av_codec_repo/services/services/codec/server/video/codec_param_checker.cpp (1005行) + codec_param_checker.h (45行) + temporal_scalability.h
association: [S19, S57, S70, S162]
---

# MEM-ARCH-AVCODEC-S224: VideoCodecParamChecker 视频编码参数校验框架

> 本地镜像源码探索 | 2026-06-08 | builder-agent (subagent)
> 来源：/home/west/av_codec_repo/services/services/codec/server/video/

---

## 主题

CodecParamChecker 是视频编解码器的参数校验与自动修正框架，在 CodecServer Configure/Parameter 两阶段对输入 Format 进行 20+ 维度校验，支持 CodecScenario 三场景自动检测与场景化校验列表。

---

## 核心架构

### 1. CodecScenario 三场景枚举

**文件**: `codec_param_checker.h:24-30`

```cpp
enum class CodecScenario : int32_t {
    CODEC_SCENARIO_ENC_NORMAL = 0,                  // 普通编码
    CODEC_SCENARIO_ENC_TEMPORAL_SCALABILITY,        // 时域可分级编码
    CODEC_SCENARIO_ENC_ENABLE_B_FRAME,               // B帧编码
    CODEC_SCENARIO_DEC_NORMAL = (1 << 30),           // 普通解码
};
```

### 2. CodecParamChecker 公开接口

**文件**: `codec_param_checker.h:32-43`

| 方法 | 阶段 | 说明 |
|------|------|------|
| `CheckConfigureValid(Format&, codecName, scenario)` | Configure | 配置校验，遍历场景对应全部 checker |
| `CheckParameterValid(format, oldFormat, codecName, scenario)` | Parameter | 参数校验，合并 format 后遍历参数专用 checker |
| `CheckCodecScenario(format, codecType, codecName)` | 场景推断 | 从 Format 自动推断 CodecScenario |

### 3. 场景检测两路 Checker

**文件**: `codec_param_checker.cpp:200-250`

```cpp
// 优先级：BFrameScenarioChecker > TemporalScalabilityChecker
const ScenarioCheckerListType VIDEO_SCENARIO_CHECKER_LIST = {
    BFrameScenarioChecker,         // 先检测 B-Frame 模式 (L247)
    TemporalScalabilityChecker,     // 再检测时域可分级模式 (L201)
};

// CheckCodecScenario 实现：遍历 LIST，找到第一个非 nullopt 即返回 (L942-956)
// 默认场景：ENCODER → ENC_NORMAL；DECODER → DEC_NORMAL
```

**BFrameScenarioChecker** (L226-248):
- Tag::VIDEO_ENCODER_ENABLE_B_FRAME = 1 时激活
- 校验 `AVCapabilityFeature::VIDEO_ENCODER_B_FRAME` 能力存在
- B-Frame 与 Temporal Scalability 互斥，优先使用 B-Frame

**TemporalScalabilityChecker** (L201-224):
- Tag::VIDEO_ENCODER_ENABLE_TEMPORAL_SCALABILITY = 1 时激活
- 校验 `AVCapabilityFeature::VIDEO_ENCODER_TEMPORAL_SCALABILITY` 能力存在

---

## 四组 Checker 列表（场景路由表）

**文件**: `codec_param_checker.cpp:100-145`

### 编码器 Configure 校验（13项，正常场景）

```cpp
const ParamCheckerListType VIDEO_ENCODER_CONFIGURE_CHECKER_LIST = {
    ResolutionChecker,             // 分辨率范围校验
    PixelFormatChecker,            // 像素格式支持性
    FramerateChecker,              // 帧率 > 0
    BitrateAndQualityChecker,      // 码率/质量/码率模式（含 SQR/CBRHQ 自动修正）
    VideoProfileChecker,           // Profile 支持性
    QPChecker,                     // QP 范围 0-51
    IFrameIntervalChecker,         // 默认填 1000ms
    ColorPrimariesChecker,         // 色域主色
    TransferCharacteristicsChecker,// 传输特性
    MatrixCoefficientsChecker,     // 矩阵系数
    LTRFrameCountChecker,          // LTR 帧数（与 Temporal Scalability 互斥）
    BFrameParamChecker,            // B-Frame GOP 模式
    VideoCodecScenarioChecker,     // 场景标识
};
```

### 编码器 Configure 校验（14项，时域可分级场景）

```cpp
const ParamCheckerListType VIDEO_ENCODER_TEMPORAL_SCALABILITY_CONFIGURE_CHECKER_LIST = {
    ResolutionChecker,             // 同上
    PixelFormatChecker,            // 同上
    FramerateChecker,              // 同上
    BitrateAndQualityChecker,      // 同上
    VideoProfileChecker,           // 同上
    QPChecker,                     // 同上
    IFrameIntervalChecker,          // 同上
    TemporalGopSizeChecker,        // GOP ≥ 2，时域 GOP < 总 GOP
    TemporalGopReferenceModeChecker,// 参考模式 ADJACENT/UNIFORMLY_SCALED
    UniformlyScaledReferenceChecker,// UNIFORMLY_SCALED 时 temporalGopSize 只能为 2 或 4
    ColorPrimariesChecker,         // 同上
    TransferCharacteristicsChecker, // 同上
    MatrixCoefficientsChecker,      // 同上
    LTRFrameCountChecker,          // ⚠️ 时域可分级场景禁止 LTR
    VideoCodecScenarioChecker,     // 同上
};
```

### 解码器 Configure 校验（7项）

```cpp
const ParamCheckerListType VIDEO_DECODER_CONFIGURE_CHECKER_LIST = {
    ResolutionChecker,             // 分辨率范围
    PixelFormatChecker,            // 像素格式
    FramerateChecker,              // 帧率 > 0
    RotationChecker,               // 仅支持 0/90/180/270
    ScalingModeChecker,            // 缩放模式 SCALE_TO_WINDOW / SCALE_CROP
    PostProcessingChecker,         // 输出色空间（仅 HEVC，支持 BT709_LTD/P3_FULL）
    TransformTypeChecker,          // 旋转变换类型
};
```

### Parameter 校验（运行时参数动态调整）

```cpp
// 编码器 Parameter：4项
const ParamCheckerListType VIDEO_ENCODER_PARAMETER_CHECKER_LIST = {
    FramerateChecker,
    BitrateAndQualityChecker,
    QPChecker,
};

// 解码器 Parameter：1项
const ParamCheckerListType VIDEO_DECODER_PARAMETER_CHECKER_LIST = {
    TransformTypeChecker,
};
```

### 场景→校验表（路由分发）

```cpp
// CONFIGURE_CHECKERS_TABLE: 4场景 × 各场景校验列表 (L163-168)
const std::unordered_map<CodecScenario, ParamCheckerListType> CONFIGURE_CHECKERS_TABLE = {
    {CODEC_SCENARIO_ENC_NORMAL,          VIDEO_ENCODER_CONFIGURE_CHECKER_LIST},
    {CODEC_SCENARIO_ENC_TEMPORAL_SCALABILITY, VIDEO_ENCODER_TEMPORAL_SCALABILITY_CONFIGURE_CHECKER_LIST},
    {CODEC_SCENARIO_ENC_ENABLE_B_FRAME,  VIDEO_ENCODER_CONFIGURE_CHECKER_LIST},  // 同正常编码
    {CODEC_SCENARIO_DEC_NORMAL,          VIDEO_DECODER_CONFIGURE_CHECKER_LIST},
};

// PARAMETER_CHECKERS_TABLE: 4场景 × 各场景参数校验列表 (L171-176)
```

---

## 核心 Checker 实现详解

### BitrateAndQualityChecker — 三码率模式自动修正

**文件**: `codec_param_checker.cpp:463-513`

三层校验逻辑：

1. **SQR 模式检测** (L467): `CheckSqrMode()` — 若 sqrFactor 超范围则降级为 VBR
2. **CBRHQ 模式检测** (L471): `CheckCBRHQMode()` — 若参数冲突则降级为 CBR
3. **VBR/CBR/CQ 模式校验** (L476-509):
   - CQ 模式未设 quality → 自动填 DEFAULT_QUALITY=50 (L458)
   - quality 与 bitrate 互斥 (L480)
   - bitrateMode 不支持 → 报错 (L505)
   - 参数超范围 → 报错 (L507)

### TemporalGopSizeChecker — 时域 GOP 校验

**文件**: `codec_param_checker.cpp:618-655`

- I-Frame 间隔为 0 时禁止全关键帧模式 (L623)
- 未设帧率 → 默认 DEFAULT_FRAMERATE=30.0 (L630)
- 未设 I-Frame 间隔 → 默认 DEFAULT_I_FRAME_INTERVAL=1000ms (L634)
- GOP Size > MIN_TEMPORAL_GOPSIZE=2 (L638)
- temporalGopSize ≥ 2 且 < gopSize (L646-649)

### LTRFrameCountChecker — LTR 与时域可分级互斥

**文件**: `codec_param_checker.cpp:726-745`

```cpp
// L722: 时域可分级场景禁止 LTR 帧数设置
CHECK_AND_RETURN_RET_LOG(scenario != CodecScenario::CODEC_SCENARIO_ENC_TEMPORAL_SCALABILITY,
    AVCS_ERR_UNSUPPORT, "Param invalid, not supported to set LTR frame count in temporal scalability scenario");

// L731: 读取能力支持的 maxLTRFrameCount
auto ltrCap = capData.featuresMap.find(VIDEO_ENCODER_LONG_TERM_REFERENCE);
// L738: 校验 0 ≤ ltrFrameCount ≤ maxLTRFrameCount
```

### BFrameParamChecker — B-Frame 模式自动修正

**文件**: `codec_param_checker.cpp:797-824`

- 未定义 GOP_MODE → 默认 ADAPTIVE_B_MODE (L813)
- VIDEO_ENCODER_MAX_B_FRAME → 不支持，直接移除 (L819)
- 未启用 B-Frame → 移除 GOP_MODE (L807)

---

## CheckConfigureValid 主入口

**文件**: `codec_param_checker.cpp:898-914`

```cpp
int32_t CodecParamChecker::CheckConfigureValid(Media::Format &format, const std::string &codecName,
                                               CodecScenario scenario)
{
    // L900: 从 CodecAbilitySingleton 获取能力数据
    auto capData = CodecAbilitySingleton::GetInstance().GetCapabilityByName(codecName);

    // L904: 从 CONFIGURE_CHECKERS_TABLE 查场景对应的 checker list
    auto checkers = CONFIGURE_CHECKERS_TABLE.find(scenario);

    // L908: 遍历全部 checker，AVCS_ERR_CODEC_PARAM_INCORRECT 累积但不终止
    for (const auto &checker : checkers->second) {
        auto ret = checker(capData.value(), format, scenario);
        if (ret == AVCS_ERR_CODEC_PARAM_INCORRECT) {
            result = AVCS_ERR_CODEC_PARAM_INCORRECT;  // 累积错误
        }
        // 其他错误码立即返回
    }
    return result;
}
```

**关键设计**: 错误累积机制 — 所有 `AVCS_ERR_CODEC_PARAM_INCORRECT` 被累积，最终返回第一个非 OK 的错误码，但继续执行所有检查（不 early return）。

---

## CheckParameterValid 主入口

**文件**: `codec_param_checker.cpp:916-940`

```cpp
int32_t CodecParamChecker::CheckParameterValid(const Media::Format &format, Media::Format &oldFormat,
                                               const std::string &codecName, CodecScenario scenario)
{
    // L918: 获取能力数据
    // L923: SQR 动态参数检查（maxBitrate/sqrFactor 超范围警告）
    SQRDynamicParameterCheck(capData.value(), format, oldFormat);

    // L925: MergeFormat — 将 format 中存在的新参数合并到 oldFormat
    MergeFormat(format, oldFormat);

    // L929: 遍历 PARAMETER_CHECKERS_TABLE（仅 1-4 项，场景化）
    for (const auto &checker : checkers->second) {
        auto ret = checker(capData.value(), oldFormat, scenario);
        CHECK_AND_RETURN_RET_LOG(ret == AVCS_ERR_OK, ret, "Param check failed");
    }
    return AVCS_ERR_OK;
}
```

**MergeFormat** (L958-1004): 将新 format 中的 7 个关键参数（bitrate/quality/framerate/qp_min/qp_max/orientation）合并到 oldFormat，支持 int32/int64/float/double/string 五种类型。

---

## 常量定义

**文件**: `codec_param_checker.cpp:37-38` + `temporal_scalability.h:29-32`

| 常量 | 值 | 定义位置 | 说明 |
|------|-----|---------|------|
| `DEFAULT_QUALITY` | 50 | cpp:37 | CQ 模式默认质量 |
| `DEFAULT_I_FRAME_INTERVAL` | 1000ms | cpp:38 | 默认 I-Frame 间隔 |
| `DEFAULT_FRAMERATE` | 30.0 | temporal_scalability.h:29 | 未设帧率时的默认值 |
| `MIN_TEMPORAL_GOPSIZE` | 2 | temporal_scalability.h:31 | 时域 GOP 最小值 |
| `DEFAULT_TEMPORAL_GOPSIZE` | 4 | temporal_scalability.h:32 | 时域 GOP 默认值 |
| `maxQP` | 51 | cpp:570 | QP 最大值 |

---

## 与 S19 TemporalScalability 关联

- S19 的 `IsLTRSolution` 判定依赖 `CodecParamChecker::CheckCodecScenario`
- `TemporalGopSizeChecker` / `TemporalGopReferenceModeChecker` / `UniformlyScaledReferenceChecker` 三项专门服务于 SVC-TL / SVC-LTR 双模式校验
- LTR 与 Temporal Scalability 互斥由 `LTRFrameCountChecker` (L722) 强制校验

---

## 与 S162 CodecAbility 关联

- `CodecAbilitySingleton::GetInstance().GetCapabilityByName(codecName)` (L900/L919/L945) — 所有校验的能力查询入口
- `capData.featuresMap` — 能力特性查询（B_FRAME/LTR/TEMPORAL_SCALABILITY 等）
- `capData.width/height/bitrate/pixFormat/profiles` — 范围校验数据来源

---

## Evidence 汇总

| # | 文件 | 行号 | 内容 |
|---|------|------|------|
| E1 | codec_param_checker.h | 24-30 | CodecScenario 四场景枚举 |
| E2 | codec_param_checker.h | 32-43 | CodecParamChecker 三公开接口 |
| E3 | codec_param_checker.cpp | 37-38 | DEFAULT_QUALITY / DEFAULT_I_FRAME_INTERVAL |
| E4 | codec_param_checker.cpp | 100-145 | 四组 ParamCheckerListType 定义 |
| E5 | codec_param_checker.cpp | 163-176 | CONFIGURE/PARAMETER_CHECKERS_TABLE 路由表 |
| E6 | codec_param_checker.cpp | 201-224 | TemporalScalabilityChecker 实现 |
| E7 | codec_param_checker.cpp | 226-248 | BFrameScenarioChecker 实现（优先级最高） |
| E8 | codec_param_checker.cpp | 256-292 | ResolutionChecker — swapWidthHeight 双轴校验 |
| E9 | codec_param_checker.cpp | 294-314 | PixelFormatChecker — SURFACE_FORMAT 跳过 |
| E10 | codec_param_checker.cpp | 316-331 | FramerateChecker — > 0 校验 |
| E11 | codec_param_checker.cpp | 333-430 | CheckSqrMode / CheckCBRHQMode — 码率模式自动修正 |
| E12 | codec_param_checker.cpp | 463-513 | BitrateAndQualityChecker — 三层码率校验 |
| E13 | codec_param_checker.cpp | 549-572 | VideoProfileChecker — Profile 支持性 |
| E14 | codec_param_checker.cpp | 574-591 | RotationChecker — 仅 0/90/180/270 |
| E15 | codec_param_checker.cpp | 593-625 | PostProcessingChecker — HEVC 色空间限制 |
| E16 | codec_param_checker.cpp | 627-655 | TemporalGopSizeChecker — GOP ≥ 2 + temporalGopSize < gopSize |
| E17 | codec_param_checker.cpp | 657-677 | TemporalGopReferenceModeChecker — 参考模式枚举校验 |
| E18 | codec_param_checker.cpp | 679-695 | UniformlyScaledReferenceChecker — 仅 2 或 4 |
| E19 | codec_param_checker.cpp | 726-745 | LTRFrameCountChecker — 与时域可分级互斥 |
| E20 | codec_param_checker.cpp | 797-824 | BFrameParamChecker — 默认 ADAPTIVE_B_MODE |
| E21 | codec_param_checker.cpp | 898-914 | CheckConfigureValid 主入口（错误累积机制） |
| E22 | codec_param_checker.cpp | 916-940 | CheckParameterValid 主入口（MergeFormat） |
| E23 | codec_param_checker.cpp | 942-956 | CheckCodecScenario 场景推断（两路 LIST 遍历） |
| E24 | codec_param_checker.cpp | 958-1004 | MergeFormat — 5 类型参数合并 |
| E25 | temporal_scalability.h | 29-32 | DEFAULT_FRAMERATE / MIN/DEFAULT_TEMPORAL_GOPSIZE |

---

**Status**: draft
**生成时间**: 2026-06-08T22:30
**来源**: 本地镜像探索 `/home/west/av_codec_repo/services/services/codec/server/video/`