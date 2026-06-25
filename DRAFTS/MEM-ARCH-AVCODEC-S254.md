# MEM-ARCH-AVCODEC-S254

## ROI Video Encoding 区域-of-Interest 视频编码

**Status**: draft
**Priority**: P1
**Created**: 2026-06-25T13:40:00+08:00
**Updated**: 2026-06-25T13:40:00+08:00
**Requester**: builder-agent subagent

---

## 1. Overview

ROI (Region of Interest) encoding 是 OpenHarmony AVCodec 硬件视频编码器的先进帧级控制特性，允许应用对视频帧中的特定矩形区域（ROI）施加不同的量化参数（QP），从而在相同码率下提升该区域的画质，或在保持质量的同时降低非 ROI 区域的码率。

**关键约束**：
- 最多 6 个 ROI 区域同时生效
- ROI 总面积不得超过帧面积的 1/5
- 仅硬件编码器（hcodec）支持，软件编码器（fcodec）不支持
- 支持 Surface 模式和 Buffer 模式

---

## 2. Native API

### 2.1 主 Key（v20 起）

**文件**: `interfaces/kits/c/native_avcodec_base.h` L1197-L1226

```c
// ROI 参数字符串格式 (value type: string)
// "Top1,Left1-Bottom1,Right1[=Params1];Top2,Left2-Bottom2,Right2[=Params2];..."
//
// Params 格式 (v20): 单个 int32_t deltaQP, 例如 "=Offset"
// Params 格式 (v26+ 推荐): Key-Value 格式 "dqp:-6" 或 "slb:1"
// 格式示例:
//   "100,200-300,400"                              // 基础矩形，无额外参数
//   "100,200-300,400=-6"                           // v20 格式，deltaQP=-6
//   "100,200-300,400=dqp:-6;slb:1"                 // v26 格式，deltaQP=-6，语义标签=FACE
//   "100,200-300,400=dqp:-6;500,600-700,800"       // 两个 ROI
extern const char *OH_MD_KEY_VIDEO_ENCODER_ROI_PARAMS;
```

**使用场景**：
- Surface 模式：在 `OH_VideoEncoder_OnNeedInputParameter` 回调中设置
- Buffer 模式：通过 `OH_AVBuffer_SetParameter` 设置

### 2.2 细粒度 Key（v26 起）

**文件**: `interfaces/kits/c/native_avcodec_videobase.h` L40-L157

```c
// ROI 矩形坐标 key（均为 mandatory）
extern const char *OH_MD_KEY_VIDEO_METADATA_ROI_TOP;    // int32_t, 范围 [0, ROI_BOTTOM)
extern const char *OH_MD_KEY_VIDEO_METADATA_ROI_LEFT;   // int32_t, 范围 [0, ROI_RIGHT)
extern const char *OH_MD_KEY_VIDEO_METADATA_ROI_BOTTOM; // int32_t, 范围 (ROI_TOP, VIDEO_HEIGHT]
extern const char *OH_MD_KEY_VIDEO_METADATA_ROI_RIGHT;  // int32_t, 范围 (ROI_LEFT, VIDEO_WIDTH]

// ROI 参数 key（均为 optional）
extern const char *OH_MD_KEY_VIDEO_METADATA_ROI_DELTA_QP;  // int32_t, 范围 [-51, 51]
extern const char *OH_MD_KEY_VIDEO_METADATA_ROI_SEM_LABEL; // int32_t, 对应枚举

// 语义标签枚举
typedef enum OH_VideoMetadataRoiSemanticLabel {
    OH_VIDEO_METADATA_ROI_SEM_LABEL_OTHER = 0,  // 未指定/其他
    OH_VIDEO_METADATA_ROI_SEM_LABEL_FACE = 1   // 人脸区域
} OH_VideoMetadataRoiSemanticLabel;
```

### 2.3 安全字符串构造 API（v26 起）

**文件**: `interfaces/kits/c/native_avcodec_videobase.h` L157

```c
// 从 OH_AVFormat 构造/追加 ROI 字符串（推荐替代手动拼接）
OH_AVErrCode OH_VideoMetadata_AppendRoiString(char **roiStrInOut, OH_AVFormat *format);
// caller 需用 free() 释放 *roiStrInOut
// 返回 AV_ERR_OK / AV_ERR_INVALID_VAL / AV_ERR_NO_MEMORY
```

---

## 3. 内部实现

### 3.1 RoiRect 结构体

**文件**: `services/engine/codec/video/hcodec/hencoder.h` L74-L81

```cpp
struct RoiRect {
    int32_t top = 0;
    int32_t left = 0;
    int32_t bottom = 0;
    int32_t right = 0;
    int32_t deltaQP = DEFAULT_DELTAQP; // 默认 QP 偏移量
};
```

### 3.2 ROI 数量限制

**文件**: `services/engine/codec/video/hcodec/hencoder.h` L227

```cpp
static constexpr size_t roiNum = 6; // 最多 6 个 ROI 区域
```

### 3.3 ROI 字符串解析

**文件**: `services/engine/codec/video/hcodec/hencoder.cpp` L1412-L1439

```cpp
bool HEncoder::ParseOneRoi(const std::string& roi, RoiRect &roiRect,
                            int32_t width, int32_t height)
{
    // 正则匹配格式: Top,Left-Bottom,Right[(=dqp:Offset)|(=slb:label)|(=Offset)]
    std::regex pat("(\\d+),(\\d+)-(\\d+),(\\d+)(?:=(?:dqp:)?(-?\\d+)|slb:(\\d+))?");
    std::smatch match;
    if (!std::regex_match(roi, match, pat)) {
        return false;
    }
    roiRect.top    = std::clamp(std::stoi(match[TOP_INDEX].str()), 0, height);
    roiRect.left   = std::clamp(std::stoi(match[LEFT_INDEX].str()), 0, width);
    roiRect.bottom = std::clamp(std::stoi(match[BOTTOM_INDEX].str()), 0, height);
    roiRect.right  = std::clamp(std::stoi(match[RIGHT_INDEX].str()), 0, width);
    // 解析 deltaQP 或 semantic label
    if (kvStr.has_value()) {
        if (kvStr->find("dqp:") == 0) {
            roiRect.deltaQP = std::stoi(kvStr->substr(4));
        } else if (kvStr->find("slb:") == 0) {
            // semantic label 解析
        } else {
            roiRect.deltaQP = std::stoi(*kvStr); // v20 兼容: 直接数字
        }
    }
    return true;
}
```

### 3.4 ROI 参数验证与注入

**文件**: `services/engine/codec/video/hcodec/hencoder.cpp` L1439-L1475

```cpp
void HEncoder::ParseRoiStringValid(const std::string& roiValue,
                                   shared_ptr<CodecHDI::OmxCodecBuffer>& omxBuffer)
{
    AppendToVector(omxBuffer->alongParam, OMX_IndexParamRoi); // 标记 OMX 参数类型
    CodecRoiParam param;

    if (roiValue.empty()) {
        // 空字符串：取消历史 ROI 配置
        param.roiInfo[0].regionEnable = false;
        return;
    }
    std::regex sepPat(";");
    std::sregex_token_iterator it(roiValue.begin(), roiValue.end(), sepPat, -1);
    std::sregex_token_iterator end;

    size_t count = 0;
    while (it != end && count < roiNum) {
        std::string reg = *it++;
        RoiRect roiRect;
        if (ParseOneRoi(reg, roiRect, width_, height_)) {
            param.roiInfo[count].regionEnable = true;
            param.roiInfo[count].absQp = 0;
            param.roiInfo[count].roiQp = roiRect.deltaQP;
            param.roiInfo[count].roiStartX = roiRect.left;
            param.roiInfo[count].roiStartY = roiRect.top;
            param.roiInfo[count].roiWidth  = roiRect.right - roiRect.left;
            param.roiInfo[count].roiHeight = roiRect.bottom - roiRect.top;
            HLOGD("Get a valid roi: %d,%d-%d,%d qp=%d",
                  roiRect.top, roiRect.left, roiRect.bottom, roiRect.right, roiRect.deltaQP);
            count++;
        }
    }
}
```

### 3.5 Surface 模式 ROI 提取

**文件**: `services/engine/codec/video/hcodec/hencoder.cpp` L1809-L1830

```cpp
bool HEncoder::GetROIBySurfaceBuffer(sptr<SurfaceBuffer> surfaceBuffer, string &roiStr)
{
    using namespace OHOS::HDI::Display::Graphic::Common::V2_2;
    if (surfaceBuffer == nullptr) {
        return false;
    }
    vector<uint8_t> vec;
    // ATTRKEY_ROI_METADATA: Surface 层传递的 ROI 元数据 key
    GSError err = surfaceBuffer->GetMetadata(ATTRKEY_ROI_METADATA, vec);
    if (err != GSERROR_OK || vec.empty()) {
        return false;
    }
    if (vec.back() != 0) {
        vec.push_back(static_cast<uint8_t>('\0'));
    }
    roiStr.assign(vec.begin(), vec.end());
    // 清理尾部 null 字符
    size_t pos = roiStr.find('\0');
    if (pos != std::string::npos) {
        roiStr.erase(pos);
    }
    HLOGD("Get roiStr %s, len %zu, vecSize %zu", roiStr.c_str(), roiStr.length(), vec.size());
    // 提取后立即清除，避免重复处理
    if (surfaceBuffer->EraseMetadataKey(ATTRKEY_ROI_METADATA) != GSERROR_OK) {
        HLOGW("erase roi key failed");
    }
    return true;
}
```

### 3.6 ROI 编码事件上报

**文件**: `services/engine/codec/video/hcodec/hencoder.cpp` L1503-L1511

```cpp
void HEncoder::ReportROIUsageEvent()
{
    if (roiReported_) {
        return;
    }
    auto eventMeta = std::make_shared<Media::Meta>();
    eventMeta->SetData(EventInfoExtentedKey::ADVANCED_FEATURE.data(), "ROI");
    // 上报 STATISTICS_INFO 事件，标记 ADVANCED_FEATURE_INFO 类型
    ReportStatisticsEvent(StatisticsEventType::ADVANCED_FEATURE_INFO, eventMeta);
    roiReported_ = true;
}
```

### 3.7 ROI 参数打包到 OMX Buffer

**文件**: `services/engine/codec/video/hcodec/hencoder.cpp` L1476-L1490

```cpp
void HEncoder::WrapRoiParamIntoOmxBuffer(
    shared_ptr<CodecHDI::OmxCodecBuffer>& omxBuffer,
    shared_ptr<AVBuffer>& buffer,
    sptr<SurfaceBuffer>& surfaceBuffer)
{
    std::string roiValue;
    // 优先从 buffer meta 获取用户设置的 ROI 参数
    if (!meta->GetData(Tag::VIDEO_ENCODER_ROI_PARAMS, roiValue) &&
        // 其次尝试从 SurfaceBuffer 的 ATTRKEY_ROI_METADATA 获取
        (!GetROIBySurfaceBuffer(surfaceBuffer, roiValue))) {
        return; // 无 ROI 参数
    }
    ParseRoiStringValid(roiValue, omxBuffer);
    ReportROIUsageEvent();
}
```

---

## 4. 数据流

```
应用层 (Surface 模式)
    │
    ├─ SurfaceBuffer::SetMetadata(ATTRKEY_ROI_METADATA, roiStringBytes)
    │              或
    │   OH_VideoEncoder_OnNeedInputParameter → OH_AVFormat_SetStringValue
    │       (OH_MD_KEY_VIDEO_ENCODER_ROI_PARAMS)
    │
    ▼
HEncoder::SubmitOneBuffer()
    │
    ├─ GetROIBySurfaceBuffer(surfaceBuffer, roiStr)  // Surface 模式
    │   └─ surfaceBuffer->GetMetadata(ATTRKEY_ROI_METADATA)
    │
    ├─ WrapPerFrameParamIntoOmxBuffer()
    │   └─ WrapRoiParamIntoOmxBuffer()
    │       ├─ ParseRoiStringValid(roiValue, omxBuffer)
    │       │   ├─ std::regex_split ROI 字符串
    │       │   ├─ ParseOneRoi() 逐区域解析
    │       │   └─ 填充 CodecRoiParam 结构
    │       └─ ReportROIUsageEvent()  // 仅首次上报
    │
    ├─ AppendToVector(omxBuffer->alongParam, OMX_IndexParamRoi)
    │
    ▼
InBufUsToOmx() → 提交到 HDI 层
    │
    ▼
CodecHDI (OMX_IndexParamRoi)
    │
    ▼
硬件编码器 (ROI-aware H.264/HEVC encoder)
```

---

## 5. ROI 使用示例

### 5.1 Buffer 模式（逐帧设置）

```cpp
// 创建编码器
OH_AVCodec *encoder = OH_VideoEncoder_CreateByMime(OH_AVMimeTypePair::AV_VIDEO_MIME_TYPE_H264);

// 配置（常规参数省略）
OH_AVFormat *configure = OH_AVFormat_Create();
// ... 设置分辨率、码率等 ...
OH_VideoEncoder_Configure(encoder, configure);

// 准备编码
OH_VideoEncoder_Start(encoder);

// 逐帧输入并设置 ROI
uint8_t index = 0;
OH_AVMemory *inputBuffer = OH_VideoEncoder_GetInputBuffer(encoder, &index);
OH_AVCodecBufferAttr attr;
attr.size = frameSize;
attr.offset = 0;
attr.pts = pts;
attr.flags = 0;

// 在 Surface 模式下使用 onEncInputParamRoi 回调
// 在 Buffer 模式下使用 OH_AVBuffer_SetParameter
OH_AVFormat *param = OH_AVFormat_Create();
OH_AVFormat_SetStringValue(param, OH_MD_KEY_VIDEO_ENCODER_ROI_PARAMS,
    "100,200-300,400=dqp:-6;slb:1");
OH_AVBuffer_SetParameter(buffer, param);
OH_AVFormat_Destroy(param);

OH_VideoEncoder_PushInputBuffer(encoder, index);
```

### 5.2 Surface 模式（回调方式）

```cpp
// 注册输入参数回调（Surface 模式）
auto callback = std::make_shared<AVCodecCallback>();
callback->onEncInputParam_ = [](OH_AVCodec *codec, uint32_t index,
                                  OH_AVFormat *parameter, void *userData) {
    // 设置 ROI 参数
    OH_AVFormat_SetStringValue(parameter,
        OH_MD_KEY_VIDEO_ENCODER_ROI_PARAMS,
        "100,200-300,400=dqp:-6");  // QP 偏移 -6，提升该区域质量
    OH_VideoEncoder_PushInputParameter(codec, index);
};
```

### 5.3 v26+ 推荐：使用 OH_VideoMetadata_AppendRoiString

```cpp
char *roiStr = nullptr;
OH_AVFormat *format = OH_AVFormat_Create();

// 方式1：v26 细粒度 key
OH_AVFormat_SetIntValue(format, OH_MD_KEY_VIDEO_METADATA_ROI_TOP, 100);
OH_AVFormat_SetIntValue(format, OH_MD_KEY_VIDEO_METADATA_ROI_LEFT, 200);
OH_AVFormat_SetIntValue(format, OH_MD_KEY_VIDEO_METADATA_ROI_BOTTOM, 300);
OH_AVFormat_SetIntValue(format, OH_MD_KEY_VIDEO_METADATA_ROI_RIGHT, 400);
OH_AVFormat_SetIntValue(format, OH_MD_KEY_VIDEO_METADATA_ROI_DELTA_QP, -6);
OH_AVFormat_SetIntValue(format, OH_MD_KEY_VIDEO_METADATA_ROI_SEM_LABEL,
    OH_VIDEO_METADATA_ROI_SEM_LABEL_FACE);

// 安全构造 ROI 字符串
OH_VideoMetadata_AppendRoiString(&roiStr, format); // roiStr 由函数分配
// roiStr = "100,200-300,400=dqp:-6;slb:1"

// 应用到编码器
OH_AVFormat_SetStringValue(param, OH_MD_KEY_VIDEO_ENCODER_ROI_PARAMS, roiStr);
free(roiStr); // 必须释放
```

---

## 6. 约束与限制

| 约束项 | 值 |
|--------|-----|
| 最大 ROI 数量 | 6 个（`roiNum = 6`） |
| ROI 总面积上限 | 不超过帧面积的 1/5 |
| deltaQP 范围 | [-51, 51] |
| 语义标签 | OTHER=0, FACE=1 |
| 支持的编码器 | 仅硬件编码器（hcodec），fcodec 不支持 |
| API 版本 | v20 起支持字符串格式，v26 起支持细粒度 key |

---

## 7. 相关文件

| 文件路径 | 说明 |
|---------|------|
| `interfaces/kits/c/native_avcodec_base.h` L1197-L1226 | `OH_MD_KEY_VIDEO_ENCODER_ROI_PARAMS` |
| `interfaces/kits/c/native_avcodec_videobase.h` L40-L157 | v26 ROI 细粒度 key + `AppendRoiString` |
| `services/engine/codec/video/hcodec/hencoder.h` L74-L81 | `RoiRect` 结构体定义 |
| `services/engine/codec/video/hcodec/hencoder.h` L140-L141 | `GetROIBySurfaceBuffer` / `ParseRoiStringValid` |
| `services/engine/codec/video/hcodec/hencoder.h` L227 | `static constexpr size_t roiNum = 6` |
| `services/engine/codec/video/hcodec/hencoder.cpp` L1412-L1439 | `ParseOneRoi` 解析实现 |
| `services/engine/codec/video/hcodec/hencoder.cpp` L1439-L1475 | `ParseRoiStringValid` 验证与填充 |
| `services/engine/codec/video/hcodec/hencoder.cpp` L1476-L1490 | `WrapRoiParamIntoOmxBuffer` OMX 打包 |
| `services/engine/codec/video/hcodec/hencoder.cpp` L1503-L1511 | `ReportROIUsageEvent` 事件上报 |
| `services/engine/codec/video/hcodec/hencoder.cpp` L1809-L1830 | `GetROIBySurfaceBuffer` Surface 提取 |
| `test/moduletest/vcodec/encoder/src/videoenc_api11_sample.cpp` L118-L130 | ROI 测试用例 |

---

## 8. Evidence Summary

- **E1**: `native_avcodec_base.h` L1197-1226: `OH_MD_KEY_VIDEO_ENCODER_ROI_PARAMS` 字符串格式定义
- **E2**: `native_avcodec_videobase.h` L40-157: v26 细粒度 ROI key + `OH_VideoMetadataRoiSemanticLabel` 枚举 + `AppendRoiString` API
- **E3**: `hencoder.h` L74-81: `RoiRect` 结构体（top/left/bottom/right/deltaQP）
- **E4**: `hencoder.h` L140: `GetROIBySurfaceBuffer` 方法声明
- **E5**: `hencoder.h` L227: `static constexpr size_t roiNum = 6` 最大 ROI 数量
- **E6**: `hencoder.cpp` L1412-1439: `ParseOneRoi` 正则解析实现
- **E7**: `hencoder.cpp` L1439-1475: `ParseRoiStringValid` ROI 验证与 `CodecRoiParam` 填充
- **E8**: `hencoder.cpp` L1476-1490: `WrapRoiParamIntoOmxBuffer` OMX 参数打包
- **E9**: `hencoder.cpp` L1503-1511: `ReportROIUsageEvent` 高级特性事件上报
- **E10**: `hencoder.cpp` L1809-1830: `GetROIBySurfaceBuffer` Surface ATTRKEY_ROI_METADATA 提取

---

## 9. 关联记忆

| ID | 主题 | 关联说明 |
|----|------|---------|
| S23 | VideoEncoder 编码器框架 | ROI 编码器基类 |
| S24 | VideoEncoder Format 配置 | `ConfigureAdvancedParams` 中处理 ROI |
| S42 | HDI Codec Adapter | ROI 通过 OMX_IndexParamRoi 传递到 HDI 层 |
| S167 | MediaCodec Native API | ROI API 入口 |
| S203 | AVCodec DFX 可观测性 | ROI 使用事件上报 (`ADVANCED_FEATURE_INFO`) |
