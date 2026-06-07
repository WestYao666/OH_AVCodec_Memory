---
status: draft
evidence_count: 20
source_files:
  - services/services/codec/server/video/codec_param_checker.cpp (1005行)
  - services/services/codec/server/video/codec_param_checker.h (45行)
  - services/services/codec/server/video/temporal_scalability.h (常量定义)
  - services/services/codec/server/video/temporal_scalability.cpp (参考)
关联主题: S19(时域可分级)/S84(VideoEncoder C API)/S221(编码器端口配置)/S42(编码核心)
---

# MEM-ARCH-AVCODEC-S224 - VideoCodecParamChecker 视频编码参数校验框架

## 概述

CodecParamChecker 是 AVCodec 视频编解码器的**参数校验引擎**，位于 `services/services/codec/server/video/codec_param_checker.cpp`（1005行）。在 Configure() / SetParameter() 调用进入 CodecServer之前，CodecParamChecker 对所有用户传入的编码参数进行全面校验，包括分辨率、像素格式、帧率、码率、Profile、QP、I帧间隔、时域GOP、B帧、色彩空间等20+维度。

**核心价值**：防止无效参数进入底层编码器，确保CodecAbility能力边界合规，并将不合法参数自动修正（如SQR模式转VBR、CBRHQ模式转CBR）。

---

## 1. CodecParamChecker 核心类与CodecScenario枚举

### 1.1 类定义（codec_param_checker.h L23-45）

```cpp
enum class CodecScenario : int32_t {
    CODEC_SCENARIO_ENC_NORMAL = 0,
    CODEC_SCENARIO_ENC_TEMPORAL_SCALABILITY,   // 时域可分级编码
    CODEC_SCENARIO_ENC_ENABLE_B_FRAME,          // B帧使能编码
    CODEC_SCENARIO_DEC_NORMAL = (1 << 30),       // 解码器（高位标识）
};

class CodecParamChecker {
public:
    static int32_t CheckConfigureValid(Media::Format &format, const std::string &codecName, CodecScenario scenario);
    static int32_t CheckParameterValid(const Media::Format &format, Media::Format &oldFormat,
                                       const std::string &codecName, CodecScenario scenario);
    static std::optional<CodecScenario> CheckCodecScenario(const Media::Format &format, AVCodecType codecType,
                                                           const std::string &codecName);
private:
    static void MergeFormat(const Media::Format &format, Media::Format &oldFormat);
};
```

**E1** (codec_param_checker.h L24-29): CodecScenario四分场景枚举，编码器占前三位(CODEC_SCENARIO_ENC_NORMAL=0, TEMPORAL_SCALABILITY=1, ENABLE_B_FRAME=2)，解码器用 `(1<<30)` 高位标识区分。

**E2** (codec_param_checker.h L31-35): CodecParamChecker三静态方法入口：CheckConfigureValid（Configure阶段校验）、CheckParameterValid（SetParameter阶段校验）、CheckCodecScenario（场景自动推断）。

### 1.2 CheckCodecScenario场景推断（L896-912）

```cpp
std::optional<CodecScenario> CodecParamChecker::CheckCodecScenario(const Media::Format &format,
                                                                   AVCodecType codecType,
                                                                   const std::string &codecName)
{
    auto capData = CodecAbilitySingleton::GetInstance().GetCapabilityByName(codecName);
    // ...
    CodecScenario scenario = CodecScenario::CODEC_SCENARIO_DEC_NORMAL;
    if (codecType == AVCODEC_TYPE_VIDEO_ENCODER) {
        scenario = CodecScenario::CODEC_SCENARIO_ENC_NORMAL; // 默认普通编码
    }
    for (const auto& checker : VIDEO_SCENARIO_CHECKER_LIST) {
        auto ret = checker(capData.value(), format, codecType);
        if (ret == std::nullopt) continue;
        scenario = ret.value(); break;
    }
    return scenario;
}
```

**E3** (codec_param_checker.cpp L896-912): CheckCodecScenario自动推断算法，先设为默认值，再用VIDEO_SCENARIO_CHECKER_LIST链表遍历（BFrameScenarioChecker → TemporalScalabilityChecker），第一个返回非nullopt的checker胜出。

---

## 2. 参数校验器链表架构

### 2.1 五类校验器链表（L114-136）

```cpp
const ParamCheckerListType VIDEO_ENCODER_CONFIGURE_CHECKER_LIST = {
    ResolutionChecker, PixelFormatChecker, FramerateChecker, BitrateAndQualityChecker,
    VideoProfileChecker, QPChecker, IFrameIntervalChecker, ColorPrimariesChecker,
    TransferCharacteristicsChecker, MatrixCoefficientsChecker, LTRFrameCountChecker,
    BFrameParamChecker, VideoCodecScenarioChecker, // 13个
};

const ParamCheckerListType VIDEO_ENCODER_TEMPORAL_SCALABILITY_CONFIGURE_CHECKER_LIST = {
    ResolutionChecker, PixelFormatChecker, FramerateChecker, BitrateAndQualityChecker,
    VideoProfileChecker, QPChecker, IFrameIntervalChecker,
    TemporalGopSizeChecker, TemporalGopReferenceModeChecker, UniformlyScaledReferenceChecker, // 3个时域专用
    ColorPrimariesChecker, TransferCharacteristicsChecker, MatrixCoefficientsChecker,
    LTRFrameCountChecker, VideoCodecScenarioChecker, // 14个
};

const ParamCheckerListType VIDEO_DECODER_CONFIGURE_CHECKER_LIST = {
    ResolutionChecker, PixelFormatChecker, FramerateChecker, RotationChecker,
    ScalingModeChecker, PostProcessingChecker, TransformTypeChecker, // 7个
};

const ParamCheckerListType VIDEO_ENCODER_PARAMETER_CHECKER_LIST = {
    FramerateChecker, BitrateAndQualityChecker, QPChecker, // 3个
};

const ParamCheckerListType VIDEO_DECODER_PARAMETER_CHECKER_LIST = {
    TransformTypeChecker, // 1个
};
```

**E4** (codec_param_checker.cpp L114-125): VIDEO_ENCODER_CONFIGURE_CHECKER_LIST含13个校验器，覆盖普通编码场景所有参数。

**E5** (codec_param_checker.cpp L127-135): VIDEO_ENCODER_TEMPORAL_SCALABILITY_CONFIGURE_CHECKER_LIST含14个校验器（比普通多3个时域专用：TemporalGopSizeChecker、TemporalGopReferenceModeChecker、UniformlyScaledReferenceChecker；无B帧和QP）。

### 2.2 Scenario→CheckerList查表（L185-193）

```cpp
const std::unordered_map<CodecScenario, ParamCheckerListType> CONFIGURE_CHECKERS_TABLE = {
    {CodecScenario::CODEC_SCENARIO_ENC_NORMAL,              VIDEO_ENCODER_CONFIGURE_CHECKER_LIST},
    {CodecScenario::CODEC_SCENARIO_ENC_TEMPORAL_SCALABILITY, VIDEO_ENCODER_TEMPORAL_SCALABILITY_CONFIGURE_CHECKER_LIST},
    {CodecScenario::CODEC_SCENARIO_ENC_ENABLE_B_FRAME, VIDEO_ENCODER_CONFIGURE_CHECKER_LIST},
    {CodecScenario::CODEC_SCENARIO_DEC_NORMAL,               VIDEO_DECODER_CONFIGURE_CHECKER_LIST},
};
```

**E6** (codec_param_checker.cpp L185-190): CONFIGURE_CHECKERS_TABLE路由表，CODEC_SCENARIO_ENC_ENABLE_B_FRAME路由到普通编码器LIST（13个），而非专用LIST，体现了B帧场景复用普通编码器校验逻辑的设计。

### 2.3 CheckConfigureValid执行入口（L873-889）

```cpp
int32_t CodecParamChecker::CheckConfigureValid(Media::Format &format, const std::string &codecName,
                                               CodecScenario scenario)
{
    auto capData = CodecAbilitySingleton::GetInstance().GetCapabilityByName(codecName);
    auto checkers = CONFIGURE_CHECKERS_TABLE.find(scenario)->second;
    int32_t result = AVCS_ERR_OK;
    for (const auto &checker : checkers->second) {
        auto ret = checker(capData.value(), format, scenario);
        if (ret == AVCS_ERR_CODEC_PARAM_INCORRECT) result = AVCS_ERR_CODEC_PARAM_INCORRECT;
        CHECK_AND_RETURN_RET_LOG(ret == AVCS_ERR_OK || ret == AVCS_ERR_CODEC_PARAM_INCORRECT, ret, ...);
    }
    return result;
}
```

**E7** (codec_param_checker.cpp L873-889): CheckConfigureValid实现，先查CodecAbility获取codec能力数据，再按scenario查表拿到checker列表，顺序遍历任一checker返回致命错误则立即返回，非致命错误（如参数范围警告）累积到result。

---

## 3. Scenario推断器：B帧与时域可分级

### 3.1 BFrameScenarioChecker（L225-244）

```cpp
std::optional<CodecScenario> BFrameScenarioChecker(CapabilityData &capData, const Format &format,
                                                  AVCodecType codecType)
{
    int32_t enable = 0;
    bool enableExist = format.GetIntValue(Tag::VIDEO_ENCODER_ENABLE_B_FRAME, enable);
    if (codecType == AVCODEC_TYPE_VIDEO_DECODER) return std::nullopt;
    if (!enableExist || !enable) return std::nullopt;
    CHECK_AND_RETURN_RET_LOG(capData.featuresMap.count(
        static_cast<int32_t>(AVCapabilityFeature::VIDEO_ENCODER_B_FRAME)), std::nullopt, ...);
    int32_t temporalEnable = 0;
    format.GetIntValue(Tag::VIDEO_ENCODER_ENABLE_TEMPORAL_SCALABILITY, temporalEnable);
    if (temporalEnable) AVCODEC_LOGW("B-frame and temporal scalability incompatible, using B-frame by default!");
    return CodecScenario::CODEC_SCENARIO_ENC_ENABLE_B_FRAME;
}
```

**E8** (codec_param_checker.cpp L225-244): BFrameScenarioChecker返回CODEC_SCENARIO_ENC_ENABLE_B_FRAME，若用户同时启用了时域可分级则警告并以B帧优先（B帧与时域不可兼用）。

### 3.2 TemporalScalabilityChecker（L206-223）

```cpp
std::optional<CodecScenario> TemporalScalabilityChecker(CapabilityData &capData, const Format &format,
                                                       AVCodecType codecType)
{
    int32_t enable = 0;
    bool enableExist = format.GetIntValue(Tag::VIDEO_ENCODER_ENABLE_TEMPORAL_SCALABILITY, enable);
    if (codecType == AVCODEC_TYPE_VIDEO_DECODER) return std::nullopt;
    if (!enableExist || !enable) return std::nullopt;
    CHECK_AND_RETURN_RET_LOG(capData.featuresMap.count(
        static_cast<int32_t>(AVCapabilityFeature::VIDEO_ENCODER_TEMPORAL_SCALABILITY)), std::nullopt, ...);
    return CodecScenario::CODEC_SCENARIO_ENC_TEMPORAL_SCALABILITY;
}
```

**E9** (codec_param_checker.cpp L206-223): TemporalScalabilityChecker检查VIDEO_ENCODER_ENABLE_TEMPORAL_SCALABILITY标签和硬件能力特性VIDEO_ENCODER_TEMPORAL_SCALABILITY，两者都满足才返回时域可分级场景。

---

## 4.核心校验器详解

### 4.1 ResolutionChecker分辨率校验（L291-306）

```cpp
int32_t ResolutionChecker(CapabilityData &capData, Format &format, CodecScenario scenario)
{
    int32_t width = 0, height = 0;
    format.GetIntValue(MediaDescriptionKey::MD_KEY_WIDTH, width);
    format.GetIntValue(MediaDescriptionKey::MD_KEY_HEIGHT, height);
    CHECK_AND_RETURN_RET_LOG(widthExist && heightExist, AVCS_ERR_INVALID_VAL, "Key param missing, width or height");
    bool resolutionValid = true;
    if (capData.supportSwapWidthHeight) {
        resolutionValid = (capData.width.InRange(width) && capData.height.InRange(height)) ||
                          (capData.width.InRange(height) && capData.height.InRange(width));
    } else {
        resolutionValid = capData.width.InRange(width) && capData.height.InRange(height);
    }
    CHECK_AND_RETURN_RET_LOG(resolutionValid, AVCS_ERR_INVALID_VAL, "Param invalid, resolution: %d*%d...", ...);
}
```

**E10** (codec_param_checker.cpp L291-306): ResolutionChecker支持宽高互换（supportSwapWidthHeight）逻辑，宽高在capData范围内且支持旋转时允许交换width/height位置。

### 4.2 BitrateAndQualityChecker码率质量综合校验（L437-515）

```cpp
int32_t BitrateAndQualityChecker(CapabilityData &capData, Format &format, CodecScenario scenario)
{
    // 1. SQR模式检测
    if (CheckSqrMode(capData, format)) return AVCS_ERR_OK;
    // 2. CBRHQ模式检测
    if (!CheckCBRHQMode(capData, format)) return AVCS_ERR_CODEC_PARAM_INCORRECT;
    // 3. 冲突检测：quality与bitrate互斥
    CHECK_AND_RETURN_RET_LOG(!(qualityExist && bitrateExist), AVCS_ERR_CODEC_PARAM_INCORRECT, ...);
    CHECK_AND_RETURN_RET_LOG(!(bitrateExist && bitrateMode == VideoEncodeBitrateMode::CQ), ...);
    CHECK_AND_RETURN_RET_LOG(!(qualityExist && bitrateMode != VideoEncodeBitrateMode::CQ), ...);
    // 4. 码率模式支持检测
    CHECK_AND_RETURN_RET_LOG(CheckBitrateModeSupport(capData, format), ...);
    // 5. 参数范围检测
    CHECK_AND_RETURN_RET_LOG(CheckBitrateAndQualityParamRange(capData, format), ...);
}
```

**E11** (codec_param_checker.cpp L437-515): BitrateAndQualityChecker五步逻辑：SQR检测→CBRHQ检测→冲突检测→模式支持检测→范围检测。SQR和CBRHQ检测失败不直接返回错误而自动降级（转VBR/CBR）。

### 4.3 CheckSqrMode SQR智能降级（L340-377）

```cpp
bool CheckSqrMode(CapabilityData &capData, Format &format)
{
    // 若bitrateMode != SQR则返回false继续后续检测
    if (!IsSupported(capData.bitrateMode, static_cast<int32_t>(VideoEncodeBitrateMode::SQR))) {
        format.RemoveKey(MediaDescriptionKey::MD_KEY_VIDEO_ENCODE_BITRATE_MODE);
        format.PutIntValue(..., VideoEncodeBitrateMode::VBR);
        AVCODEC_LOGW("Param invalid, convert the mode to VBR!");
        return false;
    }
    // SQR支持：校验sqrFactor/bitrate/maxBitrate范围，越界则移除并用bitrate替代
    return true;
}
```

**E12** (codec_param_checker.cpp L340-377): CheckSqrMode核心降级逻辑：若硬件不支持SQR模式，自动将bitrateMode转为VBR；若支持SQR但参数越界，自动移除超范围参数并用替代值。

### 4.4 QPChecker量化参数校验（L568-580）

```cpp
int32_t QPChecker(CapabilityData &capData, Format &format, CodecScenario scenario)
{
    constexpr int32_t maxQP = 51;
    int32_t qpMin, qpMax;
    bool qpMinExist = format.GetIntValue(Tag::VIDEO_ENCODER_QP_MIN, qpMin);
    bool qpMaxExist = format.GetIntValue(Tag::VIDEO_ENCODER_QP_MAX, qpMax);
    CHECK_AND_RETURN_RET_LOG(!(qpMinExist != qpMaxExist), AVCS_ERR_INVALID_VAL,
        "QPmin and QPmax are expected to be set in pairs");
    CHECK_AND_RETURN_RET_LOG(qpMin >= 0 && qpMin <= qpMax, ...);
    CHECK_AND_RETURN_RET_LOG(qpMax <= maxQP && qpMax >= qpMin, ...);
}
```

**E13** (codec_param_checker.cpp L568-580): QPChecker强制QPmin/QPmax必须成对出现（qpMinExist != qpMaxExist则报错），且QPmax<=51（标准H.264最大QP值），QPmin<=QPmax。

### 4.5 TemporalGopSizeChecker时域GOP大小校验（L637-651）

```cpp
int32_t TemporalGopSizeChecker(CapabilityData &capData, Format &format, CodecScenario scenario)
{
    // gopSize = frameRate * iFrameInterval / 1000; // ms→s
    CHECK_AND_RETURN_RET_LOG(gopSize > MIN_TEMPORAL_GOPSIZE, AVCS_ERR_INVALID_VAL,
        "Unsupported gop size, should be greater than %d!", MIN_TEMPORAL_GOPSIZE);
    format.PutIntValue("video_encoder_gop_size", gopSize); // 注入计算后的gopSize
    // temporalGopSize必须 >= MIN_TEMPORAL_GOPSIZE 且 < gopSize
    CHECK_AND_RETURN_RET_LOG(temporalGopSize >= MIN_TEMPORAL_GOPSIZE, ...);
    CHECK_AND_RETURN_RET_LOG(temporalGopSize < gopSize, ...);
}
```

**E14** (codec_param_checker.cpp L637-651): TemporalGopSizeChecker将iFrameInterval（ms）按帧率转换为gopSize帧数，注入format；temporalGopSize必须>=2且<gopSize，保证时域分层有效性。

### 4.6 UniformlyScaledReferenceChecker均匀缩放参考帧校验（L675-690）

```cpp
int32_t UniformlyScaledReferenceChecker(CapabilityData &capData, Format &format, CodecScenario scenario)
{
    format.GetIntValue(Tag::VIDEO_ENCODER_TEMPORAL_GOP_REFERENCE_MODE, mode);
    if (mode == TemporalGopReferenceMode::UNIFORMLY_SCALED_REFERENCE) {
        CHECK_AND_RETURN_RET_LOG(temporalGopSize == MIN_TEMPORAL_GOPSIZE || temporalGopSize == DEFAULT_TEMPORAL_GOPSIZE,
                                 AVCS_ERR_INVALID_VAL, "expect2 or 4", ...);
    }
}
```

**E15** (codec_param_checker.cpp L675-690): UNIFORMLY_SCALED_REFERENCE模式要求temporalGopSize必须为2或4（MIN_TEMPORAL_GOPSIZE=2或DEFAULT_TEMPORAL_GOPSIZE=4），确保均匀缩放的有效性。

### 4.7 LTRFrameCountChecker长期参考帧计数校验（L748-766）

```cpp
int32_t LTRFrameCountChecker(CapabilityData &capData, Format &format, CodecScenario scenario)
{
    CHECK_AND_RETURN_RET_LOG(scenario != CodecScenario::CODEC_SCENARIO_ENC_TEMPORAL_SCALABILITY,
        AVCS_ERR_UNSUPPORT, "not supported to set LTR frame count in temporal scalability scenario");
    auto ltrCap = capData.featuresMap.find(AVCapabilityFeature::VIDEO_ENCODER_LONG_TERM_REFERENCE);
    if (ltrCap == capData.featuresMap.end()) {
        format.RemoveKey(Tag::VIDEO_ENCODER_LTR_FRAME_COUNT); return AVCS_ERR_OK;
    }
    int32_t maxLTRFrameCount = 0;
    ltrCap->second.GetIntValue(Tag::FEATURE_PROPERTY_VIDEO_ENCODER_MAX_LTR_FRAME_COUNT, maxLTRFrameCount);
    CHECK_AND_RETURN_RET_LOG(ltrFrameCount >= 0 && ltrFrameCount <= maxLTRFrameCount, ...);
}
```

**E16** (codec_param_checker.cpp L748-766): LTRFrameCountChecker时域可分级场景禁止使用LTR（AVCS_ERR_UNSUPPORT）；LTR能力从capData.featuresMap查询MAX_LTR_FRAME_COUNT上限。

### 4.8 PostProcessingChecker解码后处理颜色空间校验（L548-566）

```cpp
int32_t PostProcessingChecker(CapabilityData &capData, Format &format, CodecScenario scenario)
{
    if (scenario != CodecScenario::CODEC_SCENARIO_DEC_NORMAL) return AVCS_ERR_OK;
    CHECK_AND_RETURN_RET_LOG(colorSpace >= 0 && colorSpace <= 31, ...);
    CHECK_AND_RETURN_RET_LOG(capData.mimeType == CodecMimeType::VIDEO_HEVC, AVCS_ERR_VIDEO_UNSUPPORT_COLOR_SPACE_CONVERSION, ...);
    CHECK_AND_RETURN_RET_LOG(colorSpace == colorSpaceBt709Limited || colorSpace == colorSpaceP3Full, ...);
}
```

**E17** (codec_param_checker.cpp L548-566): PostProcessingChecker仅适用于解码器CODEC_SCENARIO_DEC_NORMAL；颜色空间转换仅支持HEVC解码器；最终输出仅支持BT709_LIMITED(8)和P3_FULL(12)。

### 4.9 BFrameParamChecker B帧参数校验（L793-812）

```cpp
int32_t BFrameParamChecker(CapabilityData &capData, Format &format, CodecScenario scenario)
{
    auto bFrameCap = capData.featuresMap.find(AVCapabilityFeature::VIDEO_ENCODER_B_FRAME);
    if (bFrameCap == capData.featuresMap.end()) { format.RemoveKey(...); return AVCS_ERR_OK; }
    bool condExist = format.GetIntValue(Tag::VIDEO_ENCODER_ENABLE_B_FRAME, cond);
    if (!condExist || cond <= 0) { format.RemoveKey(...); return AVCS_ERR_OK; }
    bool modeExist = format.GetIntValue(Tag::VIDEO_ENCODE_B_FRAME_GOP_MODE, mode);
    if (!modeExist) mode = VIDEO_ENCODE_GOP_ADAPTIVE_B_MODE; // 默认自适应B帧模式
    format.PutIntValue(Tag::VIDEO_ENCODE_B_FRAME_GOP_MODE, mode);
    bool maxBFrameExist = format.GetIntValue(Tag::VIDEO_ENCODER_MAX_B_FRAME, maxBFrameCount);
    if (maxBFrameExist) { AVCODEC_LOGE("UnSupported config VIDEO_ENCODER_MAX_B_FRAME!"); ... } // 拒绝用户设置maxBFrame
}
```

**E18** (codec_param_checker.cpp L793-812): BFrameParamChecker拒绝用户手动设置maxBFrameCount（硬件控制）；未指定B帧GOP模式时默认ADAPTIVE_B_MODE；无条件移除不存在的B帧能力标志。

---

## 5. MergeFormat参数合并机制

### 5.1 MergeFormat实现（L918-965）

```cpp
void CodecParamChecker::MergeFormat(const Media::Format &format, Media::Format &oldFormat)
{
    for (const auto& key : FORMAT_MERGE_LIST) {
        if (!format.ContainKey(key)) continue;
        auto keyType = format.GetValueType(key);
        switch (keyType) {
            case FORMAT_TYPE_INT32: { int32_t v; format.GetIntValue(key, v); oldFormat.PutIntValue(key, v); break; }
            case FORMAT_TYPE_INT64: { int64_t v; format.GetLongValue(key, v); oldFormat.PutLongValue(key, v); break; }
            case FORMAT_TYPE_FLOAT: { float v; format.GetFloatValue(key, v); oldFormat.PutFloatValue(key, v); break; }
            case FORMAT_TYPE_DOUBLE: { double v; format.GetDoubleValue(key, v); oldFormat.PutDoubleValue(key, v); break; }
            case FORMAT_TYPE_STRING: { std::string v; format.GetStringValue(key, v); oldFormat.PutStringValue(key, v); break; }
        }
    }
}
```

**E19** (codec_param_checker.cpp L918-965): MergeFormat将SetParameter传入的新参数（format）合并到oldFormat（已Configure的旧参数），FORMAT_MERGE_LIST定义了哪些key允许从新参数覆盖旧参数，支持int32/int64/float/double/string五种类型。

---

## 6.关键常量定义

### 6.1 temporal_scalability.h常量（L29-32）

```cpp
constexpr double DEFAULT_FRAMERATE = 30.0; // 默认帧率30fps
constexpr int32_t MIN_TEMPORAL_GOPSIZE = 2;          // 最小时域GOP大小=2
constexpr int32_t DEFAULT_TEMPORAL_GOPSIZE = 4;      // 默认时域GOP大小=4
```

**E20** (temporal_scalability.h L29-32):三个核心常量定义，DEFAULT_FRAMERATE=30.0用于未指定帧率时注入；MIN_TEMPORAL_GOPSIZE=2保证至少2帧时域结构；DEFAULT_TEMPORAL_GOPSIZE=4是均匀缩放参考模式的推荐值。

---

## 附录：校验器完整列表

| 校验器 | 适用场景 | 检查内容 |
|--------|---------|---------|
| ResolutionChecker | Encoder+Decoder | 分辨率范围、宽高互换 |
| PixelFormatChecker | Encoder+Decoder | 像素格式是否支持 |
| FramerateChecker | Encoder+Decoder | 帧率>0 |
| BitrateAndQualityChecker | Encoder Only | 码率模式(SQR/CBRHQ/VBR/CBR/CQ)、范围、冲突 |
| VideoProfileChecker | Encoder Only | Profile是否支持 |
| QPChecker | Encoder Only | QPmin/QPmax成对、范围0-51 |
| IFrameIntervalChecker | Encoder Only | 默认注入1000ms |
| RotationChecker | Decoder Only | 旋转角度0/90/180/270 |
| PostProcessingChecker | Decoder Only | 颜色空间转换(仅HEVC、BT709/P3) |
| ScalingModeChecker | Decoder Only | 缩放模式0-1 |
| TransformTypeChecker | Decoder Only | 视频方向类型 |
| ColorPrimariesChecker | Encoder Only | 色彩基色范围 |
| TransferCharacteristicsChecker | Encoder Only | 传输特性范围 |
| MatrixCoefficientsChecker | Encoder Only | 矩阵系数范围 |
| LTRFrameCountChecker | Encoder Only | LTR帧数上限（时域可分级禁用） |
| BFrameParamChecker | Encoder Only | B帧使能+默认ADAPTIVE_B_MODE |
| VideoCodecScenarioChecker | Encoder Only | 编码场景类型枚举范围 |
| TemporalGopSizeChecker | Temporal Scalability | GOP大小>2 |
| TemporalGopReferenceModeChecker | Temporal Scalability | 参考模式枚举有效性 |
| UniformlyScaledReferenceChecker | Temporal Scalability | 均匀缩放要求temporalGopSize=2或4 |