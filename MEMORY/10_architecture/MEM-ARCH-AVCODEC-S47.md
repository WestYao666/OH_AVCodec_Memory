---
type: architecture
id: MEM-ARCH-AVCODEC-S47
title: "CodecCapability 能力查询与匹配机制——CodecAbility/CodecProfile/Level/SupportedTypes 五层能力体系"
scope: [AVCodec, Capability, CodecProfile, CodecLevel, CodecMime, CodecList, CodecAbilitySingleton, CodecListCore, CapabilityData, VideoCaps, AudioCaps, FindEncoder, FindDecoder]
status: pending_approval
created_by: builder-agent
created_at: "2026-04-26T10:36:00+08:00"
evidence_count: 12
关联主题: [S27(CodecList服务架构), S11(HCodec能力发现), S39(AVCodecVideoDecoder底层), S42(AVCodecVideoEncoder底层)]
---

# MEM-ARCH-AVCODEC-S47: CodecCapability 能力查询与匹配机制——五层能力体系

## Metadata

| 字段 | 值 |
|------|-----|
| **ID** | MEM-ARCH-AVCODEC-S47 |
| **标题** | CodecCapability 能力查询与匹配机制——CodecAbility/CodecProfile/Level/SupportedTypes 五层能力体系 |
| **Scope** | AVCodec, Capability, CodecProfile, CodecLevel, CodecMime, CodecList, CodecAbilitySingleton, CodecListCore, CapabilityData, VideoCaps, AudioCaps |
| **Status** | draft |
| **Created** | 2026-04-26T10:36:00+08:00 |
| **Evidence Count** | 12 |
| **关联主题** | S27(CodecList服务架构), S11(HCodec能力发现), S39(AVCodecVideoDecoder), S42(AVCodecVideoEncoder) |

---

## 架构正文

### 1. 能力体系总览：五层能力模型

AVCodec 的能力体系由五层结构组成，从外到内依次为：

| 层次 | 名称 | 定位 | 关键数据结构 |
|------|------|------|-------------|
| **L1** | CodecMimeType | 媒体类型顶层标识 | `std::string` (e.g. `"video/avc"`, `"audio/mp4a-latm"`) |
| **L2** | AVCodecType | 编解码方向与类型 | `enum AVCodecType` (VIDEO/AUDIO × ENCODER/DECODER) |
| **L3** | CapabilityData | 单个 Codec 实例的完整能力集 | `struct CapabilityData` |
| **L4** | CodecProfile + CodecLevel | 编码配置级别 | `std::vector<int32_t> profiles` + `profileLevelsMap` |
| **L5** | SupportedTypes (Range/Vector) | 具体参数范围 | `Range` (bitrate/w/h/frameRate) + `std::vector<int32_t>` (pixFormat/sampleRate) |

**能力查询入口（Native API）：**
```cpp
// interfaces/kits/c/native_avcapability.h
OH_AVCapability* OH_AVCodec_GetCapability(const char* mime, bool isEncoder, OH_AVCodecCategory category);
```

---

### 2. L1 — CodecMimeType：媒体类型枚举

定义于 `avcodec_info.h` 的 `CodecMimeType` 类，以 `static constexpr std::string_view` 方式定义了所有支持的 MIME 类型：

**视频 MIME 类型（部分）：**
```cpp
static constexpr std::string_view VIDEO_AVC   = "video/avc";
static constexpr std::string_view VIDEO_HEVC  = "video/hevc";
static constexpr std::string_view VIDEO_VP8   = "video/vp8";
static constexpr std::string_view VIDEO_VP9   = "video/vp9";
static constexpr std::string_view VIDEO_AV1   = "video/av1";
static constexpr std::string_view VIDEO_VVC   = "video/vvc";    // H.266
static constexpr std::string_view VIDEO_MPEG4 = "video/mp4v-es";
```

**音频 MIME 类型（部分）：**
```cpp
static constexpr std::string_view AUDIO_AAC    = "audio/mp4a-latm";
static constexpr std::string_view AUDIO_OPUS  = "audio/opus";
static constexpr std::string_view AUDIO_VORBIS = "audio/vorbis";
static constexpr std::string_view AUDIO_FLAC  = "audio/flac";
static constexpr std::string_view AUDIO_G711MU = "audio/g711mu";
```

**用途：** `FindEncoder`/`FindDecoder` 的必要输入参数，所有能力查询的起点。

---

### 3. L2 — AVCodecType：编解码方向与类型

定义于 `avcodec_info.h`：

```cpp
enum AVCodecType : int32_t {
    AVCODEC_TYPE_NONE           = -1,
    AVCODEC_TYPE_VIDEO_ENCODER  =  0,
    AVCODEC_TYPE_VIDEO_DECODER  =  1,
    AVCODEC_TYPE_AUDIO_ENCODER  =  2,
    AVCODEC_TYPE_AUDIO_DECODER  =  3,
};

enum class AVCodecCategory : int32_t {
    AVCODEC_NONE      = -1,
    AVCODEC_HARDWARE  =  0,   // 厂商（硬件）Codec
    AVCODEC_SOFTWARE  =  1,   // 软件 Codec
};
```

CodecType 用于 `CapabilityData.codecType` 字段，决定该能力属于哪类 Codec 实例。

---

### 4. L3 — CapabilityData：单个 Codec 的完整能力集

核心数据结构，定义于 `avcodec_info.h`，是整个能力体系的核心容器：

```cpp
struct CapabilityData {
    std::string codecName = "";          // Codec 实例名，如 "c2.vdec.avc"
    int32_t codecType = AVCODEC_TYPE_NONE;
    std::string mimeType = "";            // MIME 类型
    bool isVendor = false;               // 是否厂商（硬件）实现
    bool isSecure = false;               // 是否安全解码
    int32_t maxInstance = 0;            // 最大并发实例数

    // --- L5: 量化参数范围 ---
    Range bitrate;                       // 码率范围
    Range channels;                      // 音频通道数范围
    Range complexity;                    // 编码复杂度
    ImgSize alignment;                   // 宽高对齐粒度
    Range width;                         // 视频宽度范围
    Range height;                        // 视频高度范围
    Range frameRate;                     // 帧率范围
    Range encodeQuality;                 // 编码质量范围
    Range blockPerFrame;                 // 每帧块数
    Range blockPerSecond;                // 每秒块数
    ImgSize blockSize;                  // 块大小（MB/samples）

    // --- L5: 支持的类型列表 ---
    std::vector<int32_t> sampleRate;     // 支持的采样率
    std::vector<int32_t> pixFormat;      // 视频像素格式
    std::vector<int32_t> graphicPixFormat; // 图形像素格式
    std::vector<int32_t> bitDepth;       // 视频位深
    std::vector<int32_t> profiles;       // 支持的 Profile 列表（L4）
    std::vector<int32_t> bitrateMode;    // 码率模式 (CBR/VBR/CQ/SQR...)

    // --- L4: Profile → Levels 映射 ---
    std::map<int32_t, std::vector<int32_t>> profileLevelsMap;
    // 示例: {AVC_PROFILE_HIGH → [AVC_LEVEL_31, AVC_LEVEL_41, AVC_LEVEL_51]}

    // --- L5: 实测帧率表 ---
    std::map<ImgSize, Range> measuredFrameRate;

    bool supportSwapWidthHeight = false;
    std::map<int32_t, Format> featuresMap;  // AVCapabilityFeature → 配置参数
    int32_t rank = 0;                       // 优先级（供选择算法用）
    Range maxBitrate;
    Range sqrFactor;
    int32_t maxVersion = 0;
    std::vector<Range> sampleRateRanges;     // 采样率范围（6.0+）
};
```

**CapabilityData 验证规则** (`IsCapabilityValid`)：
- `codecName` 非空
- `codecType` 有效范围 [0, 3]
- `mimeType` 非空
- `maxInstance > 0`
- 视频 Codec 必须 `width.minVal > 0 && height.minVal > 0`
- SQR 码率模式时 `sqrFactor.maxVal <= 51`

---

### 5. L4 — CodecProfile + CodecLevel

**Profile 枚举**（按 Codec 类型分组）：

| Codec | Profile 枚举类 | 关键取值 |
|-------|---------------|---------|
| H.264 | `AVCProfile` | `BASELINE=0`, `HIGH=4`, `MAIN=8`, `HIGH_10=5`... |
| H.265 | `HEVCProfile` | `MAIN=0`, `MAIN_10=1`, `MAIN_STILL=2`... |
| H.266 | `VVCProfile` | `MAIN_10=1`, `MAIN_10_444=33`, `MULTI_MAIN_10=17`... |
| VP9 | `VP9Profile` | `PROFILE_0=0`, `PROFILE_1=1`, `PROFILE_2=2`, `PROFILE_3=3` |
| AV1 | `AV1Profile` | `MAIN=0`, `HIGH=1`, `PROFESSIONAL=2` |
| MPEG2 | `MPEG2Profile` | `SIMPLE=0`, `MAIN=1`, `HIGH=4`... |
| MPEG4 | `MPEG4Profile` | `SIMPLE=0` ~ `ADVANCED_SIMPLE=17` |
| H.263 | `H263Profile` | `BASELINE=0`... |
| AAC | `AACProfile` | (定义于 `avcodec_audio_common.h`) |

**Level 枚举**（按 Codec 类型分组）：

| Codec | Level 枚举类 | 典型取值 |
|-------|------------|---------|
| H.264 | `AVCLevel` | `1=0` ~ `62=19` (共20级) |
| H.265 | `HEVCLevel` | `1=0` ~ `62=12` |
| H.266 | `VVCLevel` | `1=16` ~ `155=255` (步长16) |
| VP9 | `VP9Level` | `1=0` ~ `62=13` |
| AV1 | `AV1Level` | `20=0` ~ `73=23` |
| MPEG2 | `MPEG2Level` | `LL=0`, `ML=1`, `H14=2`, `HL=3` |

**profileLevelsMap 的作用：** 建立 Profile → 支持的 Level 列表的映射，例如：
```cpp
// AVCodec AVCodecInfo 中
std::map<int32_t, std::vector<int32_t>> GetSupportedLevelsForProfile();
// Usage: avCodecInfo->GetSupportedLevelsForProfile()[AVC_PROFILE_HIGH]
// 返回: [AVC_LEVEL_41, AVC_LEVEL_42, AVC_LEVEL_5 ...]
```

---

### 6. L5 — SupportedTypes：量化参数范围与枚举列表

**Range 结构体** — 用于有范围的连续参数：
```cpp
struct Range {
    int32_t minVal;
    int32_t maxVal;
    Range Intersect(const Range& range); // 范围交集
    Range Union(const Range& range);      // 范围并集
    bool InRange(int32_t value);          // 值是否在范围内
};
```

**SupportedTypes 总览：**

| 维度 | 字段类型 | 说明 |
|------|---------|------|
| **视频宽高** | `Range width`, `Range height` | 像素单位 |
| **码率** | `Range bitrate` | bps |
| **帧率** | `Range frameRate` | fps，支持 double 类型 |
| **块大小** | `ImgSize blockSize` | MB（宏块）或 samples |
| **块率** | `Range blockPerFrame`, `Range blockPerSecond` | 每帧/秒宏块数 |
| **像素格式** | `std::vector<int32_t> pixFormat` | `VideoPixelFormat` 枚举值 |
| **图形格式** | `std::vector<int32_t> graphicPixFormat` | `GraphicPixelFormat` |
| **采样率** | `std::vector<int32_t> sampleRate` | Hz |
| **通道数** | `Range channels` | 音频通道 |
| **位深** | `std::vector<int32_t> bitDepth` | 8/10/12 bit |
| **码率模式** | `std::vector<int32_t> bitrateMode` | CBR=0, VBR=1, CQ=2, SQR=3, CBR_HIGH_QUALITY=4, CRF=11... |
| **实测帧率** | `std::map<ImgSize, Range> measuredFrameRate` | 按分辨率查实测帧率 |
| **编码质量** | `Range encodeQuality` | 编码器质量参数 |

---

### 7. 能力注册与初始化流程

**关键类：** `CodecAbilitySingleton`（单例，线程安全）

**初始化流程：**

```
CodecAbilitySingleton 构造函数:
  1. HCodecLoader::GetCapabilityList() → 获取硬件 Codec 能力列表
     → RegisterCapabilityArray(capaArray, CodecType::AVCODEC_HCODEC)
  2. GetCodecLists() → 创建各 CodecList 子类（VideoCodecList, AudioCodecList...）
     → 各 CodecList 子类 GetCapabilityList()
     → RegisterCapabilityArray(capaArray, codecType)
```

**RegisterCapabilityArray 处理逻辑：**
1. 遍历输入的 `CapabilityData` 数组
2. 验证每个 `CapabilityData` 的有效性 (`IsCapabilityValid`)
3. 按 `mimeType` 建立 `mimeCapIdxMap_` 倒排索引（一个 MIME 可能对应多个 Codec）
4. 按 `codecName` 建立 `nameCodecTypeMap_`
5. 存入 `capabilityDataArray_`

**MAP 大小限制：** `profileLevelsMap` 和 `measuredFrameRate` 超过 `MAX_MAP_SIZE=20` 的条目会被截断，并记录警告日志。

---

### 8. 能力查询与匹配机制

**主入口：** `CodecListCore::FindCodec(format, isEncoder)`

```
输入: Media::Format { "codec_mime": "video/avc", "width": 1920, "height": 1080, ... }
输出: codecName (string)，如 "c2.vdec.avc"
```

**查询流程（`FindCodec`）：**

```
1. 解析 format 中的 mimeType 和 isEncoder，确定 AVCodecType
2. 可选：从 format 取 codec_vendor_flag，过滤硬件/软件
3. 从 mimeCapIdxMap_ 取出该 mime 对应的所有 CapabilityData 索引
4. 遍历所有候选 CapabilityData:
   a. codecType 必须匹配
   b. mimeType 必须匹配
   c. 厂商标志 isVendor 必须匹配（如果指定了）
   d. 调用 IsVideoCapSupport() 或 IsAudioCapSupport() 做详细匹配
5. 返回第一个匹配的 codecName；否则返回空字符串
```

**Video Codec 能力匹配 (`IsVideoCapSupport`)：**
```cpp
bool IsVideoCapSupport(format, data) {
    return CheckVideoResolution(format, data)   // width/height 范围
        && CheckVideoPixelFormat(format, data)  // pixFormat 在列表中
        && CheckVideoFrameRate(format, data)    // 帧率范围（支持 double）
        && CheckBitrate(format, data);          // 码率范围
}
```

**Audio Codec 能力匹配 (`IsAudioCapSupport`)：**
```cpp
bool IsAudioCapSupport(format, data) {
    return CheckAudioChannel(format, data)     // channel_count 范围
        && CheckAudioSampleRate(format, data)  // samplerate 在列表中
        && CheckBitrate(format, data);         // 码率范围
}
```

**能力查询 API（按名称）：**
```cpp
// 通过 codecName 直接获取 CapabilityData
std::optional<CapabilityData> GetCapabilityByName(const std::string &name);

// 通过 MIME + isEncoder + category 获取 CapabilityData
CapabilityData* GetCapability(mime, isEncoder, category);
```

---

### 9. VideoCaps / AudioCaps 能力查询类

封装在 `avcodec_info.h` 中，提供面向对象的能力查询接口：

**VideoCaps** — 视频 Codec 能力查询：
```cpp
class VideoCaps {
    Range GetSupportedBitrate();
    Range GetSupportedWidth();         Range GetSupportedHeight();
    Range GetSupportedFrameRate();
    std::vector<int32_t> GetSupportedFormats();       // 像素格式
    std::vector<int32_t> GetSupportedProfiles();      // Profile 列表
    std::vector<int32_t> GetSupportedLevels();       // Level 列表
    bool IsSizeSupported(w, h);
    bool IsSizeAndRateSupported(w, h, frameRate);
    Range GetPreferredFrameRate(w, h);
    std::vector<int32_t> GetSupportedBitrateMode();
    std::map<int32_t, std::vector<int32_t>> GetSupportedLevelsForProfile(); // profile→levels
};
```

**AudioCaps** — 音频 Codec 能力查询：
```cpp
class AudioCaps {
    Range GetSupportedBitrate();
    Range GetSupportedChannel();
    Range GetSupportedComplexity();
    std::vector<int32_t> GetSupportedFormats();
    std::vector<int32_t> GetSupportedSampleRates();
    std::vector<Range>   GetSupportedSampleRateRanges(); // 6.0+
    std::vector<int32_t> GetSupportedProfiles();
    std::vector<int32_t> GetSupportedLevels();
};
```

---

### 10. AVCapabilityFeature 可选特性机制

`enum class AVCapabilityFeature` 定义了可选扩展能力（5.0+）：

```cpp
enum class AVCapabilityFeature : int32_t {
    VIDEO_ENCODER_TEMPORAL_SCALABILITY  = 0,  // 时域可分级（S19相关）
    VIDEO_ENCODER_LONG_TERM_REFERENCE    = 1,  // LTR
    VIDEO_LOW_LATENCY                    = 2,  // 低延迟
    VIDEO_WATERMARK                      = 3,  // 水印
    VIDEO_RPR                            = 4,  // Reference Picture Resampling
    VIDEO_ENCODER_QP_MAP                 = 5,  // QP Map
    VIDEO_DECODER_SEEK_WITHOUT_FLUSH     = 6,  // Seek 不刷新
    VIDEO_ENCODER_B_FRAME                = 7,  // B帧支持
    MAX_VALUE
};
```

查询接口：
```cpp
bool IsFeatureSupported(AVCapabilityFeature feature);
int32_t GetFeatureProperties(AVCapabilityFeature feature, Format &format);
```

特性配置存储在 `CapabilityData.featuresMap`（`std::map<int32_t, Format>`）中。

---

### 11. 关键文件索引

| 文件路径 | 内容 |
|---------|------|
| `interfaces/inner_api/native/avcodec_info.h` | CapabilityData、VideoCaps、AudioCaps、CodecMime、Profile/Level 枚举 |
| `interfaces/inner_api/native/avcodec_list.h` | AVCodecList 抽象接口、FindDecoder/FindEncoder |
| `services/engine/codeclist/codec_ability_singleton.h/cpp` | 单例能力注册与存储、mimeCapIdxMap_、nameCodecTypeMap_ |
| `services/engine/codeclist/codeclist_core.h/cpp` | FindCodec 匹配逻辑、CheckVideoResolution/CheckAudioChannel 等 |
| `services/engine/codeclist/codeclist_builder.h/cpp` | VideoCodecList、AudioCodecList 等子类，GetCapabilityList 实现 |
| `interfaces/inner_api/native/codec_capability_adapter.h` | CodecCapabilityAdapter，Pipeline 层查询封装 |
| `interfaces/kits/c/native_avcapability.h` | Native C API: OH_AVCodec_GetCapability |

---

### 12. 与其他主题的关联

- **S27 (CodecList 服务架构)：** CodecListCore + CodecAbilitySingleton + CodecListBuilder 三层关系在本主题中完整展开
- **S11 (HCodec)：** HCodecLoader::GetCapabilityList 是硬件 Codec 能力来源之一
- **S39 (AVCodecVideoDecoder)：** 通过 FindDecoder 获取的 codecName 创建解码器实例
- **S42 (AVCodecVideoEncoder)：** 通过 FindEncoder 获取的 codecName 创建编码器实例
- **S19 (TemporalScalability)：** `VIDEO_ENCODER_TEMPORAL_SCALABILITY` 作为 AVCapabilityFeature 之一

---

## 附录：关键枚举速查

**AVCodecType 快速映射：**
```
VIDEO_ENCODER=0 → FindEncoder(format)
VIDEO_DECODER=1 → FindDecoder(format)
AUDIO_ENCODER=2 → FindEncoder(format)
AUDIO_DECODER=3 → FindDecoder(format)
```

**VideoEncodeBitrateMode 枚举值：**
```
CBR=0 | VBR=1 | CQ=2 | SQR=3 | CBR_HIGH_QUALITY=4 | CBR_VIDEOCALL=10 | CRF=11
```
