# MEM-ARCH-AVCODEC-S238: AVCodec Engine Common 工具库——codec_utils

**状态**: pending_approval  
**Builder**: builder-agent (subagent) @2026-06-09T07:38+08:00  
**源码基于**: 本地镜像 `/home/west/av_codec_repo`

---

## 主题概述

`codec_utils.cpp`（459 行）是 AVCodec Engine Common 模块的**核心工具库**，提供格式转换、色彩空间转换、视频帧缩放、Surface 数据写入等底层能力。该文件不承载业务状态，被 `VideoDecoder`、`SurfaceDecoderAdapter`、`SurfaceEncoderAdapter` 等多个模块调用。

**定位**：codec_utils 是 AVCodec 引擎的**瑞士军刀**，负责：
1. FFmpeg ↔ OHOS 像素格式互相转换
2. 视频帧格式缩放（基于 libswscale）
3. YUV/RGB 内存写入（支持 stride 不对齐场景）
4. ColorSpace 参数转换（HDR 元数据生成）
5. Surface Fence 等待 + Surface 数据写入

**关联场景**：视频编解码 / Surface 缓冲 / HDR 元数据 / 新人入项 / 问题定位

**关联 S 系列**：
- S45：`SurfaceDecoderAdapter`（Surface 数据写入的调用方）
- S39：`VideoDecoder` 基类（Frame 转换调用方）
- S80：`SurfaceBuffer` / `fsurface_memory.cpp`（Surface 内存分配）
- S130：`FFmpegConverter`（FFmpeg 封装，色彩转换互补）

---

## 一、文件架构总览

| 属性 | 值 |
|------|------|
| 实现文件 | `services/engine/common/codec_utils.cpp`（459 行） |
| 头文件 | `services/engine/common/include/codec_utils.h`（90 行） |
| 命名空间 | `OHOS::MediaAVCodec::Codec` |
| 外部依赖 | `libswscale.so`（FFmpeg swscale）、`libavutil.so`、`GraphicSurface` |
| 被调用方 | `VideoDecoder`、`SurfaceDecoderAdapter`、`SurfaceEncoderAdapter`、`AudioDecoderAdapter` |

### 1.1 核心数据结构

```cpp
// codec_utils.h L37-53
struct ScalePara {
    int32_t srcWidth = 0;
    int32_t srcHeight = 0;
    AVPixelFormat srcFfFmt = AVPixelFormat::AV_PIX_FMT_NONE;
    int32_t dstWidth = 0;
    int32_t dstHeight = 0;
    AVPixelFormat dstFfFmt = AVPixelFormat::AV_PIX_FMT_RGBA; // 默认 RGBA
    int32_t align = VIDEO_ALIGN_SIZE; // 16
};

struct Scale {
public:
    int32_t Init(const ScalePara &scalePara, uint8_t **dstData, int32_t *dstLineSize);
    int32_t Convert(uint8_t **srcData, const int32_t *srcLineSize, uint8_t **dstData, int32_t *dstLineSize);
private:
    ScalePara scalePara_;
    std::shared_ptr<SwsContext> swsCtx_ = nullptr; // FFmpeg swscale 上下文（RAII 管理）
};

struct SurfaceInfo {
    uint32_t surfaceStride = 0;
    sptr<SyncFence> surfaceFence = nullptr;
    uint8_t **scaleData = nullptr;
    int32_t *scaleLineSize = nullptr;
};
```

### 1.2 全局常量

```cpp
// codec_utils.h L34-36
const int32_t VIDEO_ALIGN_SIZE = 16;
constexpr uint32_t VIDEO_PIX_DEPTH_RGBA = 4;
constexpr int32_t UV_SCALE_FACTOR = 2;
```

---

## 二、格式映射表（四路映射）

### 2.1 PixelFormat 映射（VideoPixelFormat ↔ AVPixelFormat）

```cpp
// codec_utils.cpp L30-33
std::map<VideoPixelFormat, AVPixelFormat> g_pixelFormatMap = {
    {VideoPixelFormat::YUVI420, AV_PIX_FMT_YUV420P},
    {VideoPixelFormat::NV12,    AV_PIX_FMT_NV12},
    {VideoPixelFormat::NV21,    AV_PIX_FMT_NV21},
    {VideoPixelFormat::RGBA,   AV_PIX_FMT_RGBA},
};
```

**用途**：`ConvertPixelFormatFromFFmpeg` / `ConvertPixelFormatToFFmpeg` 双向查表转换，支持 FFmpeg 与 OHOS 格式互转。

### 2.2 Color Primaries 映射（ColorPrimary ↔ CM_ColorPrimaries）

```cpp
// codec_utils.cpp L36-42
std::map<ColorPrimary, CM_ColorPrimaries> g_colorPrimariesMap = {
    {COLOR_PRIMARY_BT709,       COLORPRIMARIES_BT709},
    {COLOR_PRIMARY_BT601_625,   COLORPRIMARIES_BT601_P},
    {COLOR_PRIMARY_BT601_525,  COLORPRIMARIES_BT601_N},
    {COLOR_PRIMARY_BT2020,      COLORPRIMARIES_BT2020},
    {COLOR_PRIMARY_P3DCI,       COLORPRIMARIES_P3_DCI},
    {COLOR_PRIMARY_P3D65,       COLORPRIMARIES_P3_D65},
};
```

### 2.3 Transfer Function 映射（TransferCharacteristic ↔ CM_TransFunc）

```cpp
// codec_utils.cpp L44-52
std::map<TransferCharacteristic, CM_TransFunc> g_transFuncMap = {
    {TRANSFER_CHARACTERISTIC_BT709,           TRANSFUNC_BT709},
    {TRANSFER_CHARACTERISTIC_BT601,           TRANSFUNC_BT709},
    {TRANSFER_CHARACTERISTIC_LINEAR,          TRANSFUNC_LINEAR},
    {TRANSFER_CHARACTERISTIC_IEC_61966_2_1,    TRANSFUNC_SRGB},
    {TRANSFER_CHARACTERISTIC_BT2020_10BIT,    TRANSFUNC_BT709},
    {TRANSFER_CHARACTERISTIC_BT2020_12BIT,    TRANSFUNC_BT709},
    {TRANSFER_CHARACTERISTIC_PQ,              TRANSFUNC_PQ}, // HDR10
    {TRANSFER_CHARACTERISTIC_HLG,              TRANSFUNC_HLG}, // HDR HLG
};
```

**用途**：`ConvertParamsToColorSpaceInfo` 将 OHOS 色彩参数转换为 CM_ColorSpaceInfo，供 Surface/Graphic 系统使用。

### 2.4 Matrix Coefficient 映射（MatrixCoefficient ↔ CM_Matrix）

```cpp
// codec_utils.cpp L54-59
std::map<MatrixCoefficient, CM_Matrix> g_matrixMap = {
    {MATRIX_COEFFICIENT_BT709,       MATRIX_BT709},
    {MATRIX_COEFFICIENT_BT601_625,   MATRIX_BT601_P},
    {MATRIX_COEFFICIENT_BT601_525,   MATRIX_BT601_N},
    {MATRIX_COEFFICIENT_BT2020_NCL,   MATRIX_BT2020},
    {MATRIX_COEFFICIENT_ICTCP,       MATRIX_BT2100_ICTCP},
};
```

---

## 三、Scale 缩放结构体（FFmpeg swscale 封装）

### 3.1 Init — swscale 上下文初始化

```cpp
// codec_utils.cpp L420-442
int32_t Scale::Init(const ScalePara &scalePara, uint8_t **dstData, int32_t *dstLineSize)
{
    scalePara_ = scalePara;
    if (swsCtx_ != nullptr) {
        return AVCS_ERR_OK; // 已初始化则直接返回（惰性单例）
    }
    auto swsContext = sws_getContext(
        scalePara_.srcWidth, scalePara_.srcHeight, scalePara_.srcFfFmt,
        scalePara_.dstWidth, scalePara_.dstHeight, scalePara_.dstFfFmt,
        SWS_FAST_BILINEAR, nullptr, nullptr, nullptr);
    if (swsContext == nullptr) {
        return AVCS_ERR_UNKNOWN;
    }
    swsCtx_ = std::shared_ptr<SwsContext>(swsContext, [](struct SwsContext *ptr) {
        if (ptr != nullptr) { sws_freeContext(ptr); } // RAII 自动释放
    });
    auto ret = av_image_alloc(dstData, dstLineSize,
                              scalePara_.dstWidth, scalePara_.dstHeight,
                              scalePara_.dstFfFmt, scalePara_.align);
    if (ret < 0) {
        return AVCS_ERR_UNKNOWN;
    }
    // 校验 scaleData 和 scaleLineSize 对齐
    for (int32_t i = 0; dstLineSize[i] > 0; i++) {
        if (dstData[i] && !dstLineSize[i]) {
            return AVCS_ERR_UNKNOWN;
        }
    }
    return AVCS_ERR_OK;
}
```

**关键特征**：
- **惰性初始化**：`swsCtx_ != nullptr` 时跳过初始化
- **RAII 管理**：`shared_ptr<SwsContext>` 自动调用 `sws_freeContext`
- **对齐校验**：`VIDEO_ALIGN_SIZE = 16`
- **默认目标格式**：`AV_PIX_FMT_RGBA`

### 3.2 Convert — 实际缩放执行

```cpp
// codec_utils.cpp L444-451
int32_t Scale::Convert(uint8_t **srcData, const int32_t *srcLineSize,
                        uint8_t **dstData, int32_t *dstLineSize)
{
    auto res = sws_scale(swsCtx_.get(), srcData, srcLineSize, 0,
                         scalePara_.srcHeight, dstData, dstLineSize);
    if (res < 0) {
        return AVCS_ERR_UNKNOWN;
    }
    return AVCS_ERR_OK;
}
```

---

## 四、帧格式转换（ConvertVideoFrame）

### 4.1 从 AVFrame 转换

```cpp
// codec_utils.cpp L86-97
int32_t ConvertVideoFrame(std::shared_ptr<Scale> *scale,
                            std::shared_ptr<AVFrame> frame,
                            uint8_t **dstData, int32_t *dstLineSize,
                            AVPixelFormat dstPixFmt)
{
    if (*scale == nullptr) {
        *scale = std::make_shared<Scale>();
        ScalePara scalePara{
            static_cast<int32_t>(frame->width),  static_cast<int32_t>(frame->height),
            static_cast<AVPixelFormat>(frame->format), static_cast<int32_t>(frame->width),
            static_cast<int32_t>(frame->height), dstPixFmt};
        CHECK_AND_RETURN_RET_LOG((*scale)->Init(scalePara, dstData, dstLineSize) == AVCS_ERR_OK,
                                 AVCS_ERR_UNKNOWN, "Scale init error");
    }
    return (*scale)->Convert(frame->data, frame->linesize, dstData, dstLineSize);
}
```

### 4.2 从原始数据转换

```cpp
// codec_utils.cpp L100-112
int32_t ConvertVideoFrame(std::shared_ptr<Scale> *scale,
                            uint8_t **srcData, int32_t *srcLineSize, AVPixelFormat srcPixFmt,
                            int32_t srcWidth, int32_t srcHeight,
                            uint8_t **dstData, int32_t *dstLineSize, AVPixelFormat dstPixFmt)
{
    if (*scale == nullptr) {
        *scale = std::make_shared<Scale>();
        ScalePara scalePara{srcWidth, srcHeight, srcPixFmt, srcWidth, srcHeight, dstPixFmt};
        CHECK_AND_RETURN_RET_LOG((*scale)->Init(scalePara, dstData, dstLineSize) == AVCS_ERR_OK,
                                 AVCS_ERR_UNKNOWN, "Scale init error");
    }
    return (*scale)->Convert(srcData, srcLineSize, dstData, dstLineSize);
}
```

---

## 五、Surface 数据写入（WriteSurfaceData）

`WriteSurfaceData` 是 codec_utils 中最复杂的函数，处理 Surface 显存与系统内存之间的数据拷贝：

```cpp
// codec_utils.cpp L233-269
int32_t WriteSurfaceData(const std::shared_ptr<AVMemory> &memory,
                          struct SurfaceInfo &surfaceInfo,
                          const Format &format)
{
    // 1. 参数校验：height > 0，pixelFormat 在 YUV420P～RGBA 范围内
    CHECK_AND_RETURN_RET_LOG(format.GetIntValue(MediaDescriptionKey::MD_KEY_HEIGHT, height) && height > 0,
                             AVCS_ERR_INVALID_VAL, "Invalid height %{public}d!", height);
    CHECK_AND_RETURN_RET_LOG(format.GetIntValue(MediaDescriptionKey::MD_KEY_PIXEL_FORMAT, fmt) &&
                             fmt >= static_cast<int32_t>(VideoPixelFormat::YUV420P) &&
                             fmt <= static_cast<int32_t>(VideoPixelFormat::RGBA),
                             AVCS_ERR_INVALID_VAL, "Cannot get pixel format");

    // 2. Fence 等待（Surface 同步）
    if (surfaceInfo.surfaceFence != nullptr) {
        int32_t waitRes = surfaceInfo.surfaceFence->Wait(WAIT_FENCE_MS); // WAIT_FENCE_MS = 1000
        EXPECT_AND_LOGD(waitRes != 0, "wait fence time out, cost more than %{public}u ms", WAIT_FENCE_MS);
    }

    // 3. YUV 格式处理（stride 对齐判断）
    if (IsYuvFormat(pixFmt)) {
        //条件：surfaceStride == yScaleLineSize && (uScaleLineSize << 1) == surfaceStride
        // → stride 对齐：WriteYuvData（直接按 scaleLineSize 写入）
        // → stride 不对齐：WriteYuvDataStride（逐行拷贝并转换 stride）
        if (surfaceInfo.surfaceStride != yScaleLineSize ||
            (uScaleLineSize << 1) != surfaceInfo.surfaceStride) {
            return WriteYuvDataStride(memory, surfaceInfo.scaleData, surfaceInfo.scaleLineSize,
                                      surfaceInfo.surfaceStride, format);
        }
        return WriteYuvData(memory, surfaceInfo.scaleData, surfaceInfo.scaleLineSize, height, pixFmt);
    }

    // 4. RGB 格式处理
    if (IsRgbFormat(pixFmt)) {
        if (surfaceInfo.surfaceStride != yScaleLineSize) {
            return WriteRgbDataStride(...);
        }
        return WriteRgbData(memory, surfaceInfo.scaleData, surfaceInfo.scaleLineSize, height);
    }

    // 5. 不支持的格式
    AVCODEC_LOGE("Fill frame buffer failed : unsupported pixel format: %{public}d", pixFmt);
    return AVCS_ERR_UNSUPPORT;
}
```

**YUV stride差异处理**（`WriteYuvDataStride`）：
```cpp
// codec_utils.cpp L133-162
// stride ≠ scaleLineSize 时：逐行按 dstStride 对齐拷贝
// Y plane：按 stride 逐行写入
// UV plane：stride / 2（UV 下采样），高度 / 2
// NV12/NV21：UV plane 合并写入
// YUV420P：Y/U/V 三 plane 独立写入
```

---

## 六、色彩空间转换（ConvertParamsToColorSpaceInfo）

```cpp
// codec_utils.cpp L363-390
int32_t ConvertParamsToColorSpaceInfo(uint32_t fullRangeFlag, uint32_t colorPrimaries,
                                      uint32_t transferCharacteristic, uint32_t matrixCoeffs,
                                      std::vector<uint8_t> &colorSpaceInfoData)
{
    colorSpaceInfoData.resize(sizeof(CM_ColorSpaceInfo));
    CM_ColorSpaceInfo* colorSpaceInfo =
        reinterpret_cast<CM_ColorSpaceInfo*>(colorSpaceInfoData.data());

    // 三路校验：colorPrimaries / transferCharacteristic / matrixCoeffs
    if (!g_colorPrimariesMap.count(static_cast<ColorPrimary>(colorPrimaries))) {
        AVCODEC_LOGE("unsupported colorPrimaries: %{public}u", colorPrimaries);
        return AVCS_ERR_UNSUPPORT;
    }
    if (!g_transFuncMap.count(static_cast<TransferCharacteristic>(transferCharacteristic))) {
        AVCODEC_LOGE("unsupported transferCharacteristic: %{public}u", transferCharacteristic);
        return AVCS_ERR_UNSUPPORT;
    }
    if (!g_matrixMap.count(static_cast<MatrixCoefficient>(matrixCoeffs))) {
        AVCODEC_LOGE("unsupported matrixCoeffs: %{public}u", matrixCoeffs);
        return AVCS_ERR_UNSUPPORT;
    }

    // 查表转换并写入 CM_ColorSpaceInfo
    colorSpaceInfo->primaries = g_colorPrimariesMap[...];
    colorSpaceInfo->transfunc = g_transFuncMap[...];
    colorSpaceInfo->matrix = g_matrixMap[...];
    colorSpaceInfo->range = fullRangeFlag ? RANGE_FULL : RANGE_LIMITED;
    return AVCS_ERR_OK;
}
```

**HDR 元数据类型判定**：
```cpp
// codec_utils.cpp L393-406
uint32_t GetMetaDataTypeByTransFunc(uint32_t transferCharacteristic)
{
    switch (static_cast<TransferCharacteristic>(transferCharacteristic)) {
        case TRANSFER_CHARACTERISTIC_PQ:  return CM_VIDEO_HDR10;  // SMPTE 2086
        case TRANSFER_CHARACTERISTIC_HLG: return CM_VIDEO_HLG;    // BBC/NHK HDR
        default:                         return CM_METADATA_NONE;
    }
}
```

---

## 七、格式旋转（TranslateSurfaceRotation）

```cpp
// codec_utils.cpp L312-327
GraphicTransformType TranslateSurfaceRotation(const VideoRotation &rotation)
{
    switch (rotation) {
        case VideoRotation::VIDEO_ROTATION_90:  return GRAPHIC_ROTATE_270; // 逆时针旋转90°=顺时针270°
        case VideoRotation::VIDEO_ROTATION_180: return GRAPHIC_ROTATE_180;
        case VideoRotation::VIDEO_ROTATION_270: return GRAPHIC_ROTATE_90;  // 逆时针旋转270°=顺时针90°
        default:                                return GRAPHIC_ROTATE_NONE;
    }
}
```

**注意**：OHOS `VideoRotation` 定义为**逆时针**旋转角度，但 `GraphicTransformType` 为**顺时针**，所以 90°↔270° 互换。

---

## 八、关键 Evidence 汇总（E1-E15）

| ID | 文件 | 行号 | 内容 |
|----|------|------|------|
| E1 | codec_utils.cpp | 30-33 | `g_pixelFormatMap` 全局映射表（VideoPixelFormat ↔ AVPixelFormat） |
| E2 | codec_utils.cpp | 36-42 | `g_colorPrimariesMap` 全局映射表（ColorPrimary ↔ CM_ColorPrimaries） |
| E3 | codec_utils.cpp | 44-52 | `g_transFuncMap` 全局映射表（TransferCharacteristic ↔ CM_TransFunc，含 PQ/HLG） |
| E4 | codec_utils.cpp | 54-59 | `g_matrixMap` 全局映射表（MatrixCoefficient ↔ CM_Matrix） |
| E5 | codec_utils.cpp | 65-72 | `IsValidPixelFormat` 参数校验（YUV420P ≤ val ≤ RGBA，排除 SURFACE_FORMAT） |
| E6 | codec_utils.cpp | 74-78 | `IsValidRotation` 参数校验（0/90/180/270 四选一） |
| E7 | codec_utils.cpp | 86-97 | `ConvertVideoFrame(AVFrame*)` 懒初始化 Scale + swscale 缩放 |
| E8 | codec_utils.cpp | 100-112 | `ConvertVideoFrame(srcData*)` 懒初始化 Scale + swscale 缩放（重载版本） |
| E9 | codec_utils.cpp | 233-246 | `WriteSurfaceData` 参数校验 + Surface Fence 等待（WAIT_FENCE_MS=1000） |
| E10 | codec_utils.cpp | 246-265 | `WriteSurfaceData` YUV/RGB 分支处理 + stride 不对齐走 Write*DataStride |
| E11 | codec_utils.cpp | 133-162 | `WriteYuvDataStride` stride 不对齐时逐行拷贝（UV plane stride/2） |
| E12 | codec_utils.cpp | 363-377 | `ConvertParamsToColorSpaceInfo` 三路映射校验（primaries/transfer/matrix） |
| E13 | codec_utils.cpp | 393-406 | `GetMetaDataTypeByTransFunc` PQ→CM_VIDEO_HDR10、HLG→CM_VIDEO_HLG |
| E14 | codec_utils.cpp | 312-327 | `TranslateSurfaceRotation` 逆时针→顺时针角度互换（90°↔270°） |
| E15 | codec_utils.cpp | 420-442 | `Scale::Init` sws_getContext + shared_ptr<SwsContext> RAII + av_image_alloc |

---

## 九、文件索引

| 角色 | 路径 | 行数 |
|------|------|------|
| 实现 | `services/engine/common/codec_utils.cpp` | 459 |
| 头文件 | `services/engine/common/include/codec_utils.h` | 90 |
| 调用方示例 | `services/engine/codec/video/surface_decoder_adapter.cpp` | ~350 |
| 相关 S | S45（SurfaceDecoderAdapter）、S39（VideoDecoder）、S80（SurfaceBuffer）、S130（FFmpegConverter） |