# MEM-ARCH-AVCODEC-S221: VideoCodecEncoder 输入/输出端口配置与Surface/PixelFormat/Profile参数体系

> **状态**: draft → pending_approval
> **主题**: S221 - VideoCodecEncoder 输入/输出端口配置与Surface/PixelFormat/Profile参数体系
> **探索日期**: 2026-06-08
> **源码路径**: `/home/west/av_codec_repo/services/engine/codec/video/avcencoder/`
> **接口路径**: `/home/west/av_codec_repo/interfaces/inner_api/native/avcodec_video_encoder.h`

---

## 1. 架构概述

VideoCodecEncoder 输入/输出端口配置体系是 AVCodec 视频编码器的核心配置子系统，负责管理编码器的**输入端口**（Surface/Buffer双模式）、**像素格式**（PixelFormat/YUV420/RGBA）、**编码Profile**（Baseline/Main/High）、**编码Level**（1.0~6.2）、以及**码率控制模式**（CBR/VBR/CQ）。

三层调用链：
```
CAPI层 (avcodec_video_encoder.h 417行)
  → AVCodecVideoEncoder 接口 (Configure/CreateInputSurface/QueueInputBuffer)
  → AvcEncoder 实现 (avc_encoder.cpp 1765行 + avc_encoder.h 270行)
  → libavcenc_ohos.z.so HDI层 (CreateAvcEncoderFunc/EncodeFunc/DeleteFunc)
```

---

## 2. 输入端口配置（Input Port Configuration）

### 2.1 双模式输入：Surface模式 vs Buffer模式

AVCodecVideoEncoder 接口定义了两个互斥的输入路径：

**Surface模式**（行118）：
- `CreateInputSurface()` - 创建生产者Surface，返回给应用层
- 应用通过Surface注入图像数据（相机预览/视频采集）
- 配置后、启动前调用（Configure之后、Start之前）

**Buffer模式**（行121-151）：
- `QueueInputBuffer(index)` - 直接提交AVBuffer
- `QueueInputParameter(index)` - 提交编码参数（5.0+）
- 需要先通过`QueryInputBuffer`获取可用buffer索引

### 2.2 AvcEncoder 输入端口实现

**avc_encoder.h:261** - inputSurface_成员：
```cpp
sptr<Surface> inputSurface_ = nullptr;
```

**avc_encoder.cpp:315-352** - CreateInputSurface实现：
```cpp
sptr<Surface> AvcEncoder::CreateInputSurface()
{
    sptr<Surface> consumerSurface = Surface::CreateSurfaceAsConsumer("HEncoderSurface");
    GSError err = consumerSurface->SetDefaultUsage(SURFACE_MODE_CONSUMER_USAGE); // 行327
    sptr<IBufferProducer> producer = consumerSurface->GetProducer(); // 行334
    sptr<Surface> producerSurface = Surface::CreateSurfaceAsProducer(producer);
    inputSurface_ = consumerSurface; // 行346
    if (DEFAULT_IN_BUFFER_CNT > inputSurface_->GetQueueSize()) {
        inputSurface_->SetQueueSize(DEFAULT_IN_BUFFER_CNT); // 行348
    }
    return producerSurface;
}
```

**avc_encoder.h:220** - Surface消费端Usage常量：
```cpp
static constexpr uint32_t SURFACE_MODE_CONSUMER_USAGE = 0x1; // GRAPHIC_PRODUCER_USAGE
```

### 2.3 SetInputSurface 外部Surface注入

**avc_encoder.cpp:355-372** - SetInputSurface实现：
```cpp
int32_t AvcEncoder::SetInputSurface(sptr<Surface> surface)
{
    if (!surface->IsConsumer()) {
        AVCODEC_LOGE("expect consumer surface"); // 行366
    }
    inputSurface_ = surface; // 行370
    if (DEFAULT_IN_BUFFER_CNT > inputSurface_->GetQueueSize()) {
        inputSurface_->SetQueueSize(DEFAULT_IN_BUFFER_CNT); // 行371
    }
}
```

### 2.4 输入端口缓冲区数量

**avc_encoder.h:37** - 默认缓冲区配置：
```cpp
constexpr uint32_t DEFAULT_IN_BUFFER_CNT = 4;
constexpr uint32_t DEFAULT_OUT_BUFFER_CNT = 8;
```

---

## 3. SetupPort 输入端口参数校验

**avc_encoder.cpp:675-692** - SetupPort实现（输入端口宽高校验）：
```cpp
int32_t AvcEncoder::SetupPort(const Format &format)
{
    int32_t width;
    if (!format.GetIntValue(MediaDescriptionKey::MD_KEY_WIDTH, width) ||
        width <= 0 || width > VIDEO_MAX_WIDTH_SIZE) {
        AVCODEC_LOGE("format should contain width"); // 行681
        return AVCS_ERR_INVALID_VAL;
    }
    int32_t height;
    if (!format.GetIntValue(MediaDescriptionKey::MD_KEY_HEIGHT, height) ||
        height <= 0 || height > VIDEO_MAX_HEIGHT_SIZE) {
        AVCODEC_LOGE("format should contain height"); // 行689
        return AVCS_ERR_UNKNOWN;
    }
    if ((width % EVEN_NUMBER_DIVISOR != 0) || (height % EVEN_NUMBER_DIVISOR != 0)) {
        AVCODEC_LOGE("The frame's width and height must both be even numbers"); // 行693
        return AVCS_ERR_UNKNOWN;
    }
    encWidth_ = width;
    encHeight_ = height;
}
```

---

## 4. PixelFormat 像素格式体系

### 4.1 VideoPixelFormat 枚举（编码器输入格式）

**avc_encoder.cpp:518-526** - GetPixelFmtFromUser解析用户配置的PixelFormat：
```cpp
void AvcEncoder::GetPixelFmtFromUser(const Format &format)
{
    VideoPixelFormat innerFmt;
    if (format.GetIntValue(MediaDescriptionKey::MD_KEY_PIXEL_FORMAT, *(int *)&innerFmt) &&
        innerFmt != VideoPixelFormat::SURFACE_FORMAT) {
        srcPixelFmt_ = innerFmt; // 行523
        AVCODEC_LOGI("configuread pixel fmt %{public}d", static_cast<int32_t>(innerFmt));
    } else {
        AVCODEC_LOGI("user don't set pixel fmt, use default yuv420"); // 行526
    }
}
```

### 4.2 GraphicPixelFormat ↔ VideoPixelFormat 双向转换

**avc_encoder_util.cpp:73-95** - TranslateVideoPixelFormat（Surface格式→编码器格式）：
```cpp
VideoPixelFormat TranslateVideoPixelFormat(GraphicPixelFormat surfaceFormat)
{
    switch (surfaceFormat) {
        case GraphicPixelFormat::GRAPHIC_PIXEL_FMT_YCBCR_420_P: { // 行76
            return VideoPixelFormat::YUVI420; // 行77
        }
        case GraphicPixelFormat::GRAPHIC_PIXEL_FMT_RGBA_8888: {
            return VideoPixelFormat::RGBA; // 行79
        }
        case GraphicPixelFormat::GRAPHIC_PIXEL_FMT_YCBCR_P010: // 行82
        case GraphicPixelFormat::GRAPHIC_PIXEL_FMT_YCBCR_420_SP: {
            return VideoPixelFormat::NV12; // 行83
        }
        case GraphicPixelFormat::GRAPHIC_PIXEL_FMT_YCRCB_P010: // 行86
        case GraphicPixelFormat::GRAPHIC_PIXEL_FMT_YCRCB_420_SP: {
            return VideoPixelFormat::NV21; // 行87
        }
        default:
            AVCODEC_LOGE("Invalid graphic pixel format:%{public}d", ...); // 行91
    }
}
```

**avc_encoder_util.cpp:96-113** - TranslateSurfacePixFormat（编码器格式→Surface格式）：
```cpp
GraphicPixelFormat TranslateSurfacePixFormat(const VideoPixelFormat &pixelFormat)
{
    switch (pixelFormat) {
        case VideoPixelFormat::YUVI420:
            return GraphicPixelFormat::GRAPHIC_PIXEL_FMT_YCBCR_420_P; // 行100
        case VideoPixelFormat::RGBA:
            return GraphicPixelFormat::GRAPHIC_PIXEL_FMT_RGBA_8888; // 行103
        case VideoPixelFormat::NV12:
            return GraphicPixelFormat::GRAPHIC_PIXEL_FMT_YCBCR_420_SP; // 行106
        case VideoPixelFormat::NV21:
            return GraphicPixelFormat::GRAPHIC_PIXEL_FMT_YCRCB_420_SP; // 行109
        default:
            return GraphicPixelFormat::GRAPHIC_PIXEL_FMT_BUTT; // 行112
    }
}
```

### 4.3 VideoPixelFormat → COLOR_FORMAT（HDI层格式）

**avc_encoder_util.cpp:182-200** - TranslateVideoFormatToAvc（编码器格式→HDI格式）：
```cpp
COLOR_FORMAT TranslateVideoFormatToAvc(const VideoPixelFormat &pixelFormat)
{
    switch (pixelFormat) {
        case VideoPixelFormat::YUVI420:
            return COLOR_FORMAT::YUV_420P; // 行186
        case VideoPixelFormat::NV12:
            return COLOR_FORMAT::YUV_420SP_VU; // 行189
        case VideoPixelFormat::NV21:
            return COLOR_FORMAT::YUV_420SP_UV; // 行192
        case VideoPixelFormat::RGBA:
            return COLOR_FORMAT::YUV_420SP_VU; // 行195
        default:
            AVCODEC_LOGE("Invalid video pixel format:%{public}d", ...); // 行198
    }
    return COLOR_FORMAT::YUV_420P; // 行200
}
```

---

## 5. Profile 参数体系

### 5.1 AVCProfile 枚举（应用层Profile）

**avcodec_info.h** - AVCProfile枚举定义：
- `AVC_PROFILE_BASELINE` - 基本Profile
- `AVC_PROFILE_CONSTRAINED_BASELINE` - 约束Baseline
- `AVC_PROFILE_MAIN` - 主Profile
- `AVC_PROFILE_HIGH` - 高Profile
- `AVC_PROFILE_HIGH_10/422/444` - 高10位/422/444
- `AVC_PROFILE_EXTENDED` - 扩展Profile
- `AVC_PROFILE_CONSTRAINED_HIGH` - 约束High

### 5.2 ENC_PROFILE（HDI层Profile）

**AvcEnc_Typedef.h:45-50** - HDI层Profile枚举：
```cpp
typedef enum {
    PROFILE_BASE        = 0x0,  // 对应AVC_PROFILE_BASELINE
    PROFILE_MAIN        = 0x1,  // 对应AVC_PROFILE_MAIN
    PROFILE_HIGH        = 0x2,  // 对应AVC_PROFILE_HIGH
    PROFILE_SIMPLE      = 0x3,
    PROFILE_ADVSIMPLE   = 0x4,
} ENC_PROFILE;
```

### 5.3 TranslateEncProfile 映射函数

**avc_encoder_util.cpp:203-224** - Profile映射实现：
```cpp
ENC_PROFILE TranslateEncProfile(AVCProfile profile)
{
    switch (profile) {
        case AVCProfile::AVC_PROFILE_BASELINE: // 行206
        case AVCProfile::AVC_PROFILE_CONSTRAINED_BASELINE: {
            return ENC_PROFILE::PROFILE_BASE; // 行208
        }
        case AVCProfile::AVC_PROFILE_CONSTRAINED_HIGH: // 行210
        case AVCProfile::AVC_PROFILE_EXTENDED: // 行211
        case AVCProfile::AVC_PROFILE_HIGH: // 行212
        case AVCProfile::AVC_PROFILE_HIGH_10: // 行213
        case AVCProfile::AVC_PROFILE_HIGH_422: // 行214
        case AVCProfile::AVC_PROFILE_HIGH_444: {
            return ENC_PROFILE::PROFILE_HIGH; // 行216
        }
        case AVCProfile::AVC_PROFILE_MAIN: {
            return ENC_PROFILE::PROFILE_MAIN; // 行218
        }
        default:
            AVCODEC_LOGE("Invalid profile format:%{public}d", ...); // 行222
    }
    return ENC_PROFILE::PROFILE_BASE; // 行224
}
```

### 5.4 GetBitRateModeFromUser 解析Profile

**avc_encoder.cpp:548-576** - Profile/Level解析入口：
```cpp
void AvcEncoder::GetBitRateModeFromUser(const Format &format)
{
    VideoEncodeBitrateMode mode;
    AVCProfile profile;
    AVCLevel level;
    if (format.GetIntValue(MediaDescriptionKey::MD_KEY_PROFILE, *reinterpret_cast<int *>(&profile))) {
        AVCODEC_LOGI("user set avc profile %{public}d", static_cast<int>(profile)); // 行570
        avcProfile_ = profile; // 行571
    }
    if (format.GetIntValue(MediaDescriptionKey::MD_KEY_LEVEL, *reinterpret_cast<int *>(&level))) {
        AVCODEC_LOGI("user set avc level %{public}d", static_cast<int>(level)); // 行575
        avcLevel_ = level; // 行576
    }
}
```

---

## 6. Level 参数体系

### 6.1 AVCLevel 枚举（应用层Level）

Level范围：1.0 ~ 6.2，共17个等级（行550-576）：
- `AVC_LEVEL_1` / `AVC_LEVEL_1b` / `AVC_LEVEL_11` ~ `AVC_LEVEL_62`

### 6.2 H264Level（HDI层Level）

**avc_encoder_util.cpp:27-47** - 17级映射表：
```cpp
std::map<AVCLevel, H264Level> g_encodeLevelMap = {
    { AVCLevel::AVC_LEVEL_1,  H264Level::H264_LEVEL_10 },  // 行28
    { AVCLevel::AVC_LEVEL_1b, H264Level::H264_LEVEL_1B },  // 行29
    { AVCLevel::AVC_LEVEL_11, H264Level::H264_LEVEL_11 },  // 行30
    // ... 中间省略 ...
    { AVCLevel::AVC_LEVEL_4,  H264Level::H264_LEVEL_40 },  // 行39
    { AVCLevel::AVC_LEVEL_41, H264Level::H264_LEVEL_41 },  // 行40
    // ... 省略 ...
    { AVCLevel::AVC_LEVEL_61, H264Level::H264_LEVEL_61 },  // 行46
    { AVCLevel::AVC_LEVEL_62, H264Level::H264_LEVEL_62 },  // 行47
};
```

### 6.3 TranslateEncLevel 映射函数

**avc_encoder_util.cpp:227-232** - Level映射实现：
```cpp
H264Level TranslateEncLevel(AVCLevel level)
{
    auto iter = std::find_if(g_encodeLevelMap.begin(), g_encodeLevelMap.end(),
        [&](const std::pair<AVCLevel, H264Level> &tmp) -> bool { return tmp.first == level; }); // 行230
    return iter == g_encodeLevelMap.end() ? H264Level::H264_LEVEL_41 : iter->second; // 行232
}
```

### 6.4 FillAvcInitParams 写入HDI层

**avc_encoder.cpp:854-885** - InitParams填充：
```cpp
void AvcEncoder::FillAvcInitParams(AVC_ENC_INIT_PARAM &param)
{
    param.level = static_cast<uint32_t>(TranslateEncLevel(avcLevel_)); // 行882
    param.profile = TranslateEncProfile(avcProfile_); // 行883
}
```

---

## 7. 能力注册（GetCodecCapability）

### 7.1 CapabilityData 像素格式列表

**avc_encoder.cpp:1717-1745** - GetCapabilityData能力注册：
```cpp
void AvcEncoder::GetCapabilityData(CapabilityData &capsData, uint32_t index)
{
    capsData.codecName = SUPPORT_VCODEC[index].codecName;
    capsData.mimeType = SUPPORT_VCODEC[index].mimeType;
    GetBaseCapabilityData(capsData);

    if (SUPPORT_VCODEC[index].isEncoder) {
        capsData.complexity.minVal = 1;
        capsData.complexity.maxVal = 1;
        capsData.encodeQuality.minVal = VIDEO_QUALITY_MIN;
        capsData.encodeQuality.maxVal = VIDEO_QUALITY_MAX;
    }
    capsData.pixFormat = { // 行1726-1731
        static_cast<int32_t>(VideoPixelFormat::YUVI420),
        static_cast<int32_t>(VideoPixelFormat::NV12),
        static_cast<int32_t>(VideoPixelFormat::NV21),
        static_cast<int32_t>(VideoPixelFormat::RGBA)
    };
    capsData.graphicPixFormat = { // 行1733-1737
        static_cast<int32_t>(GraphicPixelFormat::GRAPHIC_PIXEL_FMT_YCBCR_420_P),
        static_cast<int32_t>(GraphicPixelFormat::GRAPHIC_PIXEL_FMT_YCBCR_420_SP),
        static_cast<int32_t>(GraphicPixelFormat::GRAPHIC_PIXEL_FMT_YCRCB_420_SP),
        static_cast<int32_t>(GraphicPixelFormat::GRAPHIC_PIXEL_FMT_RGBA_8888)
    };
    capsData.profiles = { // 行1740-1741
        static_cast<int32_t>(AVC_PROFILE_BASELINE),
        static_cast<int32_t>(AVC_PROFILE_MAIN)
    };
    std::vector<int32_t> levels;
    for (int32_t j = 0; j <= static_cast<int32_t>(AVCLevel::AVC_LEVEL_51); ++j) {
        levels.emplace_back(j); // 行1744
    }
    capsData.profileLevelsMap.insert(std::make_pair(static_cast<int32_t>(AVC_PROFILE_MAIN), levels));
    capsData.profileLevelsMap.insert(std::make_pair(static_cast<int32_t>(AVC_PROFILE_BASELINE), levels));
}
```

---

## 8. 关键 Evidence 汇总

| # | 文件 | 行号 | 内容 |
|---|------|------|------|
| E1 | avc_encoder.h | 261 | `sptr<Surface> inputSurface_` 输入Surface成员 |
| E2 | avc_encoder.h | 220 | `SURFACE_MODE_CONSUMER_USAGE = 0x1` Surface消费端Usage |
| E3 | avc_encoder.h | 37 | `DEFAULT_IN_BUFFER_CNT = 4` 输入缓冲区默认数量 |
| E4 | avc_encoder.cpp | 315-352 | `CreateInputSurface()` Surface模式创建 |
| E5 | avc_encoder.cpp | 355-372 | `SetInputSurface()` 外部Surface注入 |
| E6 | avc_encoder.cpp | 518-526 | `GetPixelFmtFromUser()` PixelFormat解析 |
| E7 | avc_encoder.cpp | 548-576 | `GetBitRateModeFromUser()` Profile/Level解析 |
| E8 | avc_encoder.cpp | 675-692 | `SetupPort()` 输入端口宽高校验 |
| E9 | avc_encoder.cpp | 854-885 | `FillAvcInitParams()` HDI参数填充 |
| E10 | avc_encoder.cpp | 1687-1755 | `GetCodecCapability()` 能力注册 |
| E11 | avc_encoder.cpp | 1717-1745 | `GetCapabilityData()` PixelFormat/Profile/Level能力列表 |
| E12 | avc_encoder_util.cpp | 27-47 | `g_encodeLevelMap` AVCLevel→H264Level 17级映射表 |
| E13 | avc_encoder_util.cpp | 73-95 | `TranslateVideoPixelFormat()` Surface→Video格式转换 |
| E14 | avc_encoder_util.cpp | 96-113 | `TranslateSurfacePixFormat()` Video→Surface格式转换 |
| E15 | avc_encoder_util.cpp | 182-200 | `TranslateVideoFormatToAvc()` Video→HDI COLOR_FORMAT转换 |
| E16 | avc_encoder_util.cpp | 203-224 | `TranslateEncProfile()` AVCProfile→ENC_PROFILE映射 |
| E17 | avc_encoder_util.cpp | 227-232 | `TranslateEncLevel()` AVCLevel→H264Level映射 |
| E18 | avc_encoder_util.cpp | 73-95 | 四种GraphicPixelFormat (YCBCR_420_P/RGBA/YCBCR_420_SP/YCRCB_420_SP) |
| E19 | AvcEnc_Typedef.h | 33-36 | `COLOR_FORMAT` YUV_420P/YUV_420SP_UV/YUV_420SP_VU三态枚举 |
| E20 | AvcEnc_Typedef.h | 45-50 | `ENC_PROFILE` PROFILE_BASE/MAIN/HIGH三态枚举 |
| E21 | AvcEnc_Typedef.h | 15-18 | `AVC_ENC_INIT_PARAM` level/profile/colorFmt完整结构体 |
| E22 | avc_encoder.cpp | 476-477 | `ConfigureContext()` 调用GetPixelFmtFromUser和SetupPort |
| E23 | avc_encoder.cpp | 912-915 | `Start()` RegisterConsumerListener绑定Surface输入 |
| E24 | avc_encoder.cpp | 263-311 | `GetBufferFromSurface()` AcquireBuffer消费Surface图像 |

---

## 9. 关联主题

- **S59** - AvcEncoder 硬件H.264编码器（九状态机/FBuffer四态/Surface模式）
- **S70** - VideoCodec工厂与Loader插件体系（CodecFactory双工厂）
- **S84** - VideoEncoder C API实现（NativeVideoEncoder对象模型）
- **S83** - AVCodec Native C API架构（四类API家族）
- **S57** - HDecoder/HEncoder硬件编解码器（HDI四层调用链）

---

## 10. 配置参数速查表

| 参数Key | 类型 | 默认值 | 校验范围 | 映射函数 |
|--------|------|--------|---------|---------|
| MD_KEY_WIDTH | int32 | - | VIDEO_MIN_SIZE~VIDEO_MAX_WIDTH_SIZE | - |
| MD_KEY_HEIGHT | int32 | - | VIDEO_MIN_SIZE~VIDEO_MAX_HEIGHT_SIZE | - |
| MD_KEY_PIXEL_FORMAT | VideoPixelFormat | YUVI420 | YUVI420/NV12/NV21/RGBA | TranslateVideoPixelFormat |
| MD_KEY_PROFILE | AVCProfile | AVC_PROFILE_BASELINE | BASELINE/MAIN/HIGH | TranslateEncProfile |
| MD_KEY_LEVEL | AVCLevel | AVC_LEVEL_41 | 1.0~6.2 (17级) | TranslateEncLevel |
| MD_KEY_FRAME_RATE | double | 30.0 | VIDEO_FRAMERATE_MIN~MAX | - |
| MD_KEY_BITRATE | int32 | - | VIDEO_BITRATE_MIN~MAX | - |
| MD_KEY_VIDEO_ENCODE_BITRATE_MODE | VideoEncodeBitrateMode | CBR | CBR/VBR/CQ | - |

---

## 11. Surface/Buffer 双模式互斥约束

1. **互斥性**：`CreateInputSurface()` 和 `QueueInputBuffer()` 不可同时使用
2. **Surface模式**：`inputSurface_ != nullptr` → 使用SurfaceConsumerListener消费
3. **Buffer模式**：`inputSurface_ == nullptr` → 使用OnInputBufferAvailable回调
4. **切换时机**：Configure之后、Start之前配置输入模式，之后不可更改
5. **默认行为**：未配置PixelFormat时默认使用YUVI420（行526）