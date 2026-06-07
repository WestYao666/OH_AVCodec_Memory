# MEM-ARCH-AVCODEC-S220: AVCodec Native Capability Query API
## OH_AVCodec_GetCapability 系统三层架构

**主题编号**: S220  
**scope**: AVCodec, Native API, C API, Capability, OH_AVCodec_GetCapability, CodecAbility, VideoCaps, AudioCaps  
**关联场景**: 三方应用接入/新人入项/问题定位/能力查询  
**状态**: draft  
**生成时间**: 2026-06-08T04:30 Builder基于本地镜像 `/home/west/av_codec_repo`  
**关联主题**: S47(CodecCapability能力查询体系) / S71(CodecList服务架构) / S83(C API总览) / S162(CodecAbility/CodecListCore) / S95(AudioCodec CAPI) / S171(CodecCapabilityAdapter)

---

## 1. 主题概述

AVCodec Native Capability Query API 是 AVCodec 模块对外暴露的**能力查询入口**，供三方应用在创建编解码器之前查询设备是否支持特定格式、分辨率、帧率等能力。核心 API `OH_AVCodec_GetCapability()` 是 C API 中使用频率最高的接口之一。

**三层架构**：
- **C API 层** (`native_avcapability.h/cpp`)：`OH_AVCodec_GetCapability` / `GetCapabilityByCategory` / `GetCapabilityList` 等 24 个 API 函数
- **能力引擎层** (`codec_ability_singleton.cpp` + `codeclist_core.cpp`)：`CodecAbilitySingleton` 单例 + `CodecListCore` 七项 Check 校验
- **数据模型层** (`avcodec_info.h`)：`CapabilityData` + `VideoCaps` + `AudioCaps` 三结构

---

## 2. 关键文件 Evidence（行号级）

### E1. C API Header: native_avcapability.h (572行)
**路径**: `interfaces/kits/c/native_avcapability.h`  
**用途**: C API 能力查询接口定义，572行，24个API函数

```c
// E1-a 行55: OH_AVCapability 不透明句柄
typedef struct OH_AVCapability OH_AVCapability;

// E1-b 行72-76: OH_AVCodecCategory 硬件/软件分类
typedef enum OH_AVCodecCategory {
    HARDWARE = 0,
    SOFTWARE
} OH_AVCodecCategory;

// E1-c 行82-103: OH_AVCodecType 四类编解码器枚举
typedef enum OH_AVCodecType {
    OH_AVCODEC_TYPE_VIDEO_ENCODER = 0,
    OH_AVCODEC_TYPE_VIDEO_DECODER = 1,
    OH_AVCODEC_TYPE_AUDIO_ENCODER = 2,
    OH_AVCODEC_TYPE_AUDIO_DECODER = 3
} OH_AVCodecType;

// E1-d 行111-122: OH_AVCapabilityFeature 特性位域
typedef enum OH_AVCapabilityFeature {
    VIDEO_ACCELERATION = 0,    // 硬件加速
    SECURE_CODEC = 1,          // 安全解码
    // ...
} OH_AVCapabilityFeature;

// E1-e 行133: OH_AVCodec_GetCapability 主入口（按MIME + isEncoder查询）
OH_AVCapability *OH_AVCodec_GetCapability(const char *mime, bool isEncoder);

// E1-f 行146: OH_AVCodec_GetCapabilityByCategory（带HARDWARE/SOFTWARE过滤）
OH_AVCapability *OH_AVCodec_GetCapabilityByCategory(const char *mime, bool isEncoder, OH_AVCodecCategory category);

// E1-g 行161: OH_AVCodec_GetCapabilityList（按类型批量查询）
OH_AVCapability **OH_AVCodec_GetCapabilityList(OH_AVCodecType codecType, uint32_t *count);

// E1-h 行171-221: 查询方法集
bool OH_AVCapability_IsHardware(OH_AVCapability *capability);
bool OH_AVCapability_IsSecure(OH_AVCapability *capability);
const char *OH_AVCapability_GetName(OH_AVCapability *capability);
const char *OH_AVCapability_GetMimeType(OH_AVCapability *capability);
bool OH_AVCapability_CheckMimeType(OH_AVCapability *capability, const char *mimeType);
int32_t OH_AVCapability_GetMaxSupportedInstances(OH_AVCapability *capability);

// E1-i 行234-287: 编码器能力查询
OH_AVErrCode OH_AVCapability_GetEncoderBitrateRange(OH_AVCapability *capability, OH_AVRange *bitrateRange);
bool OH_AVCapability_IsEncoderBitrateModeSupported(OH_AVCapability *capability, OH_BitrateMode bitrateMode);
OH_AVErrCode OH_AVCapability_GetEncoderQualityRange(OH_AVCapability *capability, OH_AVRange *qualityRange);
OH_AVErrCode OH_AVCapability_GetEncoderComplexityRange(OH_AVCapability *capability, OH_AVRange *complexityRange);

// E1-j 行287-330: 音频能力查询
OH_AVErrCode OH_AVCapability_GetAudioSupportedSampleRates(OH_AVCapability *capability, const int32_t **sampleRates, uint32_t *sampleRateNum);
OH_AVErrCode OH_AVCapability_GetAudioChannelCountRange(OH_AVCapability *capability, OH_AVRange *channelCountRange);

// E1-k 行330-475: 视频能力查询
OH_AVErrCode OH_AVCapability_GetVideoWidthAlignment(OH_AVCapability *capability, int32_t *widthAlignment);
OH_AVErrCode OH_AVCapability_GetVideoWidthRange(OH_AVCapability *capability, OH_AVRange *widthRange);
OH_AVErrCode OH_AVCapability_GetVideoHeightRange(OH_AVCapability *capability, OH_AVRange *heightRange);
bool OH_AVCapability_IsVideoSizeSupported(OH_AVCapability *capability, int32_t width, int32_t height);
OH_AVErrCode OH_AVCapability_GetVideoFrameRateRange(OH_AVCapability *capability, OH_AVRange *frameRateRange);
bool OH_AVCapability_AreVideoSizeAndFrameRateSupported(OH_AVCapability *capability, int32_t width, int32_t height, double frameRate);
OH_AVErrCode OH_AVCapability_GetVideoSupportedPixelFormats(OH_AVCapability *capability, const int32_t **pixelFormats, uint32_t *pixelFormatNum);

// E1-l 行513-555: Profile/Level 查询
OH_AVErrCode OH_AVCapability_GetSupportedProfiles(OH_AVCapability *capability, const int32_t **profiles, uint32_t *profileNum);
OH_AVErrCode OH_AVCapability_GetSupportedLevelsForProfile(OH_AVCapability *capability, int32_t profile, const int32_t **levels, uint32_t *levelNum);
bool OH_AVCapability_AreProfileAndLevelSupported(OH_AVCapability *capability, int32_t profile, int32_t level);

// E1-m 行555: OH_AVCapability_IsFeatureSupported
bool OH_AVCapability_IsFeatureSupported(OH_AVCapability *capability, OH_AVCapabilityFeature feature);
```

### E2. C API Implementation: native_avcapability.cpp (705行)
**路径**: `frameworks/native/capi/common/native_avcapability.cpp`  
**用途**: C API 实现，705行，实现24个API函数

```c
// E2-a 行47-51: CapabilityCache 静态缓存（MAX_CAP_NUM=200，TOTAL_CODEC_TYPES=4）
struct CapabilityCache {
    OH_AVCapability *array[MAX_CAP_NUM] = {nullptr};
    uint32_t count = 0;
};
static CapabilityCache g_caches[TOTAL_CODEC_TYPES];

// E2-b 行55-70: OH_AVCodec_GetCapability 主入口实现
// 调用流程：AVCodecListFactory::CreateAVCodecList()
// → codeclist->GetCapability(mime, isEncoder, AVCodecCategory::AVCODEC_NONE)
//        → codeclist->GetBuffer(name, sizeof(OH_AVCapability))
//        → obj->magic_ = AVMagic::AVCODEC_MAGIC_AVCAPABILITY
//        → obj->capabilityData_ = capabilityData

// E2-c 行84-128: OH_AVCodec_GetCapabilityList 实现（批量查询，带 std::call_once 缓存）
// 使用 std::call_once + g_initFlags 实现进程内单次初始化
// 循环遍历 codecType 对应的所有 CapabilityData
// 使用 g_caches[typeIndex].array[] 静态数组缓存（避免重复分配）

// E2-d 行131-162: OH_AVCodec_GetCapabilityByCategory 实现
// HARDWARE → AVCodecCategory::AVCODEC_HARDWARE
// SOFTWARE → AVCodecCategory::AVCODEC_SOFTWARE
// 调用 codeclist->GetCapability(mime, isEncoder, innerCategory)

// E2-e 行163-192: OH_AVCapability_IsHardware / IsSecure / GetName 实现
// 访问 capability->capabilityData_->isVendor (isHardware)
//访问 capability->capabilityData_->isSecure

// E2-f 行193-260: OH_AVCapability_GetSupportedProfiles 实现
// 关键实现：使用 AudioCaps 或 AVCodecInfo 包装 CapabilityData
// std::shared_ptr<AudioCaps> codecInfo = std::make_shared<AudioCaps>(capability->capabilityData_);
// codecInfo->GetSupportedProfiles() → vec
// codeclist->NewBuffer(vecSize) → memcpy_s → 返回 buf

// E2-g 行260-320: OH_AVCapability_GetSupportedLevelsForProfile 实现
// 访问 profileLevelsMap[profile] → levelsmatch->second
// 新建 buffer → memcpy_s → 返回

// E2-h 行320-350: OH_AVCapability_GetEncoderBitrateRange 实现
// 使用 AudioCaps::GetSupportedBitrate()
// bitrateRange->minVal/maxVal = bitrate.minVal/maxVal

// E2-i 行350-410: OH_AVCapability_GetEncoderQualityRange / GetEncoderComplexityRange
// Quality: std::shared_ptr<VideoCaps> codecInfo = std::make_shared<VideoCaps>(capData)
// codecInfo->GetSupportedEncodeQuality()
// Complexity: codecInfo->GetSupportedComplexity()

// E2-j 行410-440: OH_AVCapability_IsEncoderBitrateModeSupported
// codecInfo->GetSupportedBitrateMode() → find bitrateMode in bitrateModeVec

// E2-k 行440-500: OH_AVCapability_GetAudioSupportedSampleRates
// AppEventReporter + ApiInvokeRecorder 埋点
// AudioCaps::GetSupportedSampleRates()
// 返回数组指针（通过 codeclist->NewBuffer 分配）

// E2-l 行500-570: OH_AVCapability_GetVideoWidthRange / GetVideoHeightRange
// VideoCaps::GetSupportedWidth() / GetSupportedHeight()
// 返回 OH_AVRange {minVal, maxVal}

// E2-m 行570-610: OH_AVCapability_IsVideoSizeSupported
// VideoCaps::IsSizeSupported(width, height)

// E2-n 行610-650: OH_AVCapability_GetVideoFrameRateRange
// VideoCaps::GetSupportedFrameRate()
// VideoCaps::GetSupportedFrameRatesFor(width, height)

// E2-o 行650-705: OH_AVCapability_GetVideoSupportedPixelFormats
// VideoCaps::GetSupportedFormats()
// AudioCaps::GetSupportedFormats()
```

### E3. CapabilityData 数据结构: avcodec_info.h (inner API)
**路径**: `interfaces/inner_api/native/avcodec_info.h`  
**用途**: CapabilityData + VideoCaps + AudioCaps 三层数据模型

```c
// E3-a 行48-58: AVCodecCategory 内部枚举
enum class AVCodecCategory : int32_t {
    AVCODEC_NONE = -1,
    AVCODEC_HARDWARE = 0,
    AVCODEC_SOFTWARE = 1,
};

// E3-b 行60-78: AVCapabilityFeature 特性位域
enum class AVCapabilityFeature : int32_t {
    VIDEO_ACCELERATION = 0,
    SECURE_CODEC = 1,
    // ...
};

// E3-c 行78-87: Range 结构（min/max 值范围）
struct Range {
    int32_t minVal = 0;
    int32_t maxVal = 0;
};

// E3-d 行131-145: ImgSize 结构（宽高）
struct ImgSize {
    int32_t width = 0;
    int32_t height = 0;
};

// E3-e 行155-191: CapabilityData 完整数据结构
struct CapabilityData {
    std::string codecName = "";          // 编解码器名称
    int32_t codecType = AVCODEC_TYPE_NONE;
    std::string mimeType = "";           // MIME 类型（如 "video/avc"）
    bool isVendor = false;               // 是否Vendor/Hardware
    bool isSecure = false; // 是否安全解码
    int32_t maxInstance = 0;             // 最大并发实例数
    Range bitrate;                       // 码率范围
    Range channels;                      // 声道数范围
    Range complexity;                    // 复杂度范围
    ImgSize alignment;                   // 宽高对齐要求
    Range width;                         // 宽度范围
    Range height;                        // 高度范围
    Range frameRate;                     // 帧率范围
    Range encodeQuality;                 // 编码质量范围
    Range blockPerFrame;                 // 每帧块数
    Range blockPerSecond; // 每秒块数
    ImgSize blockSize;                   // 块大小
    std::vector<int32_t> sampleRate;     // 支持的采样率列表
    std::vector<int32_t> pixFormat;      // 支持的像素格式
    std::vector<int32_t> graphicPixFormat; // 支持的图形像素格式
    std::vector<int32_t> bitDepth;       // 支持的位深
    std::vector<int32_t> profiles;       // 支持的Profile列表
    std::vector<int32_t> bitrateMode;   // 支持的码率模式
    std::map<int32_t, std::vector<int32_t>> profileLevelsMap; // Profile→Level映射
    std::map<ImgSize, Range> measuredFrameRate; // 实测帧率（按分辨率）
    bool supportSwapWidthHeight = false; // 是否支持宽高互换
    std::map<int32_t, Format> featuresMap; // 特性映射表
    int32_t rank = 0;                    // 优先级
    Range maxBitrate;                    // 最大码率
    Range sqrFactor;                     // 平方因子
    int32_t maxVersion = 0;
    std::vector<Range> sampleRateRanges; //采样率范围列表
};

// E3-f 行212-260: AVCodecInfo 类（封装 CapabilityData）
class AVCodecInfo {
    CapabilityData *data_; // 持有 CapabilityData 指针
    bool IsHardwareAccelerated();       // isVendor 判断
    bool IsSecure();                    // isSecure 判断
    std::map<int32_t, std::vector<int32_t>> GetSupportedLevelsForProfile();
};

// E3-g 行319-511: VideoCaps 类（视频能力）
class VideoCaps {
    CapabilityData *data_;
    Range GetSupportedBitrate();        // E3-b
    std::vector<int32_t> GetSupportedFormats(); // 像素格式
    std::vector<int32_t> GetSupportedGraphicFormats(); // 图形格式
    int32_t GetSupportedHeightAlignment();
    int32_t GetSupportedWidthAlignment();
    Range GetSupportedWidth();
    Range GetSupportedHeight();
    std::vector<int32_t> GetSupportedProfiles();
    std::vector<int32_t> GetSupportedLevels();
    Range GetSupportedEncodeQuality();
    Range GetSupportedComplexity();
    bool IsSizeSupported(int32_t width, int32_t height);
    Range GetSupportedFrameRate();
    Range GetSupportedFrameRatesFor(int32_t width, int32_t height);
    bool IsSizeAndRateSupported(int32_t width, int32_t height, double frameRate);
    std::vector<int32_t> GetSupportedBitrateMode(); // CBR/VBR/CQ
    Range GetSupportedQuality();
    bool IsSupportDynamicIframe();
    Range GetVideoHeightRangeForWidth(int32_t width);
    Range GetVideoWidthRangeForHeight(int32_t height);
    Range GetSupportedMaxBitrate();
    Range GetSupportedSqrFactor();
};

// E3-h 行535-614: AudioCaps 类（音频能力）
class AudioCaps {
    CapabilityData *data_;
    Range GetSupportedBitrate();
    std::vector<int32_t> GetSupportedSampleRates();
    std::vector<int32_t> GetSupportedProfiles(); // AAC: LC/HE/LC+HEv2
    Range GetSupportedComplexity();
};
```

### E4. CodecAbilitySingleton 单例: codec_ability_singleton.cpp (229行)
**路径**: `services/engine/codeclist/codec_ability_singleton.cpp`  
**用途**: 能力单例管理，初始化时注册所有 CodecCapability

```c
// E4-a 行43-52: GetCodecLists 工厂方法（按 CodecType 分发）
std::unordered_map<CodecType, std::shared_ptr<CodecListBase>> GetCodecLists() {
    std::shared_ptr<CodecListBase> vcodecList = std::make_shared<VideoCodecList>();
    codecLists.insert(std::make_pair(CodecType::AVCODEC_VIDEO_CODEC, vcodecList));
    std::shared_ptr<CodecListBase> hevcDecoderList = std::make_shared<VideoHevcDecoderList>();
    codecLists.insert(std::make_pair(CodecType::AVCODEC_VIDEO_HEVC_DECODER, hevcDecoderList));
    // VP8/VP9/AV1/AVCEncoder/AudioCodec ...
}

// E4-b 行55-60: GetInstance 单例访问点
CodecAbilitySingleton &CodecAbilitySingleton::GetInstance() {
    static CodecAbilitySingleton instance;
    return instance;
}

// E4-c 行62-85: 构造函数（初始化阶段）
// 1. HCodecLoader::GetCapabilityList(videoCapaArray) → RegisterCapabilityArray(..., AVCODEC_HCODEC)
// 2. GetCodecLists() → for each codecList → GetCapabilityList → RegisterCapabilityArray

// E4-d 行89-103: IsCapabilityValid 七项校验
// codecName 非空 / codecType 有效 / mimeType 非空 / maxInstance > 0
// width 范围合法 / height 范围合法 /编码器额外校验
```

### E5. CodecListCore 查询引擎: codeclist_core.cpp (388行)
**路径**: `services/engine/codeclist/codeclist_core.cpp`  
**用途**: CapabilityData 查询引擎

```c
// E5-a 行1-50: CheckCapability 七项 Check
// 1. CheckCodecName / 2. CheckCodecType / 3. CheckMimeType
// 4. CheckMaxInstance / 5. CheckWidth / 6. CheckHeight
// 7. CheckAudioCaps（音频额外校验）

// E5-b: FindEncoder / FindDecoder 按 MIME 查找
// mimeCapIdxMap_ 倒排索引加速查询

// E5-c: GetCapability(mime, isEncoder, category)
// category = AVCODEC_NONE → 优先返回硬件Codec
// category = AVCODEC_HARDWARE / AVCODEC_SOFTWARE → 按类型过滤
```

### E6. AudioCodecList 音频能力数据: audio_codeclist_info.cpp (942行)
**路径**: `services/engine/codeclist/audio_codeclist_info.cpp`  
**用途**: 音频编解码器能力配置数据（硬编码的 CapabilityData 数组）

```c
// E6-a: audio_codecs[] CapabilityData 数组
// 包含各音频Codec的 mimeType/maxInstance/bitrate/channels/sampleRate/profiles

// E6-b: AAC 能力数据
// mimeType: "audio/mp4a-latm"
// maxInstance: 16
// profiles: AAC_LC / AAC_HE / AAC_LC_PLUS_HEV2
// sampleRate: {96000, 64000, 48000, 44100, 32000, 24000, 22050, 16000, 12000, 8000}
```

---

## 3. 架构总览

```
┌─────────────────────────────────────────────────────┐
│  三方应用层 (C API 调用方)                          │
│  OH_AVCodec_GetCapability("video/avc", false)      │
└───────────────┬─────────────────────────────────────┘
                │ native_avcapability.cpp:55-70
                ▼
┌─────────────────────────────────────────────────────┐
│  C API 层 (native_avcapability.cpp, 705行)          │
│  OH_AVCodec_GetCapability / GetCapabilityByCategory│
│  OH_AVCodec_GetCapabilityList / GetCapability_* │
│  OH_AVCapability_IsHardware / IsSecure / GetName    │
└───────────────┬─────────────────────────────────────┘
                │ AVCodecListFactory::CreateAVCodecList()
                ▼
┌─────────────────────────────────────────────────────┐
│  能力引擎层 (codec_ability_singleton.cpp, 229行)   │
│  CodecAbilitySingleton::GetInstance()               │
│  GetCodecLists() → VideoCodecList/AudioCodecList   │
└───────────────┬─────────────────────────────────────┘
                │ GetCapability(mime, isEncoder, category)
                ▼
┌─────────────────────────────────────────────────────┐
│  CodecListCore (codeclist_core.cpp, 388行)         │
│  FindEncoder/FindDecoder / mimeCapIdxMap_倒排索引  │
│  CheckCapability 七项校验 │
└───────────────┬─────────────────────────────────────┘
                │ CapabilityData 指针
                ▼
┌─────────────────────────────────────────────────────┐
│  数据模型层 (avcodec_info.h) │
│  CapabilityData 结构体 (E3-e)                      │
│  VideoCaps (E3-g) / AudioCaps (E3-h)                │
│  AVCodecInfo (E3-f)                                │
└─────────────────────────────────────────────────────┘
```

---

## 4. API 使用流程

**典型使用流程**（三方应用）：

```c
// 1. 获取 H.264 硬件解码器能力
OH_AVCapability *cap = OH_AVCodec_GetCapabilityByCategory(
    "video/avc", false, HARDWARE);

// 2. 查询是否支持 1920x1080@30fps
bool ok = OH_AVCapability_AreVideoSizeAndFrameRateSupported(
    cap, 1920, 1080, 30.0);

// 3. 查询支持的 Profile/Level
const int32_t *profiles = nullptr;
uint32_t profileNum = 0;
OH_AVCapability_GetSupportedProfiles(cap, &profiles, &profileNum);

// 4. 查询最大实例数
int32_t maxInstance = OH_AVCapability_GetMaxSupportedInstances(cap);

// 5. 释放（Capability 对象无需显式释放，从 AVCodecList 缓存池分配）
```

**GetCapabilityList 批量查询流程**：

```c
// 查询所有视频解码器（硬件）
uint32_t count = 0;
OH_AVCapability **list = OH_AVCodec_GetCapabilityList(
    OH_AVCODEC_TYPE_VIDEO_DECODER, &count);
// 返回 count 个 OH_AVCapability 指针数组（静态缓存，无需释放）
```

---

## 5. 能力查询核心算法

### FindEncoder / FindDecoder（MIME 匹配）

```
mimeCapIdxMap_: unordered_map<string, vector<int32_t>>  // MIME → CapabilityData索引列表

GetCapability(mime, isEncoder, category):
  1. mimeCapIdxMap_[mime] → indices[]
  2. for each idx in indices:
       if codecList[idx].codecType 匹配 (encoder/decoder):
         if category == AVCODEC_NONE:
          优先返回 isVendor=true 的硬件Codec
         elif category == AVCODEC_HARDWARE:
           仅返回 isVendor=true
         elif category == AVCODEC_SOFTWARE:
           仅返回 isVendor=false
  3. CheckCapability 七项校验
  4. 返回 CapabilityData*
```

### GetCapabilityList缓存机制

```
OH_AVCodec_GetCapabilityList(codecType, count):
  typeIndex = codecType (0=视频编码器/1=视频解码器/2=音频编码器/3=音频解码器)
  std::call_once(g_initFlags[typeIndex], [&]() {
    codeclist = AVCodecListFactory::CreateAVCodecList()
    capabilityDataList = codeclist->GetCapabilityList(codecType)
    for each capabilityData:
      obj = codeclist->GetBuffer(name, sizeof(OH_AVCapability))
      obj->capabilityData_ = capabilityData
      g_caches[typeIndex].array[validCount++] = obj
  })
  count = g_caches[typeIndex].count
  return g_caches[typeIndex].array
```

---

## 6. CapabilityData 字段速查表

| 字段 | 类型 | 含义 |典型值 |
|------|------|------|--------|
| codecName | string | 编解码器名称 | "OMX.rdk.h264.sw decoder" |
| mimeType | string | MIME类型 | "video/avc" |
| isVendor | bool | 是否Vendor/Hardware | true |
| isSecure | bool | 是否安全解码 | false |
| maxInstance | int32_t | 最大并发实例 | 16 |
| bitrate | Range | 码率范围 (bps) | {0, 20000000} |
| width | Range | 宽度范围 (px) | {16, 3840} |
| height | Range | 高度范围 (px) | {16, 2160} |
| alignment | ImgSize | 宽高对齐 | {16, 16} |
| frameRate | Range | 帧率范围 (fps) | {1, 120} |
| pixFormat | vector |像素格式 | NV12/I420/RGBA |
| profiles | vector | 支持的Profile | {1(Baseline), 2(Main), 3(High)} |
| sampleRate | vector | 采样率列表 | {48000, 44100, 32000} |
| channels | Range | 声道数范围 | {1, 8} |
| encodeQuality | Range | 编码质量 | {0, 100} |
| complexity | Range | 复杂度 | {0, 100} |
| bitrateMode | vector | 码率模式 | {CBR=0, VBR=1, CQ=2} |

---

## 7.关联主题

| 主题 | 关系 | 说明 |
|------|------|------|
| S47 | 互补 | CodecCapability 五层能力体系（能力模型层） |
| S71 | 互补 | CodecList 服务架构（SA 层） |
| S83 | 互补 | Native C API 总览（接口契约层） |
| S162 | 互补 | CodecAbility/CodecListCore（三层索引体系） |
| S95 | 关联 | AudioCodec CAPI（音频编解码 C API） |
| S171 | 关联 | CodecCapabilityAdapter（Filter适配层能力查询） |

---

## 8. 使用场景与 FAQ

**Q1: 如何查询设备支持哪些 H.264 解码器？**
```c
OH_AVCapability **list = OH_AVCodec_GetCapabilityList(OH_AVCODEC_TYPE_VIDEO_DECODER, &count);
for (uint32_t i = 0; i < count; i++) {
    if (OH_AVCapability_CheckMimeType(list[i], "video/avc")) {
        bool isHw = OH_AVCapability_IsHardware(list[i]);
    }
}
```

**Q2: 如何判断是否支持 4K 分辨率？**
```c
OH_AVCapability *cap = OH_AVCodec_GetCapability("video/avc", false);
OH_AVRange widthRange, heightRange;
OH_AVCapability_GetVideoWidthRange(cap, &widthRange);
OH_AVCapability_GetVideoHeightRange(cap, &heightRange);
if (widthRange.maxVal >= 3840 && heightRange.maxVal >= 2160) {
    // 支持 4K
}
```

**Q3: HARDWARE vs SOFTWARE 类别有什么区别？**
- HARDWARE: isVendor=true，返回硬件编解码器
- SOFTWARE: isVendor=false，返回软件编解码器（FFmpeg等）
- AVCODEC_NONE: 不区分，优先返回硬件（isVendor=true 优先）

**Q4: 能否同时使用硬件和软件Codec？**
- 不能通过 GetCapabilityByCategory 混合获取
- 需要分别调用 GetCapabilityByCategory(HARDWARE) 和 GetCapabilityByCategory(SOFTWARE)
- 实际运行时根据硬件可用性和性能需求选择

---

## 9. 状态与变更记录

| 日期 | 操作 | 说明 |
|------|------|------|
| 2026-06-08T04:30 | Builder 生成草案 | 基于本地镜像生成 S220 草案，行号级 evidence（E1-E6，20条） |