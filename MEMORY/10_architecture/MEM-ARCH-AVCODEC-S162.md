---
type: architecture
id: MEM-ARCH-AVCODEC-S162
status: pending_approval
topic: CodecAbility/CodecListCore 编解码能力查询体系——CodecAbilitySingleton 单例 + CodecListCore 查询引擎 + audio_codeclist_info 能力数据
scope: [AVCodec, CodecList, Capability, CodecAbility, FindDecoder, FindEncoder, MimeMap, Profile, Level, HCodec, AudioCodec, VideoCodec]
created_at: "2026-05-20T13:15:00+08:00"
updated_at: "2026-05-20T13:15:00+08:00"
source_repo: /home/west/av_codec_repo
source_root: services/engine/codeclist/, interfaces/inner_api/native/
evidence_version: local_mirror
---

# MEM-ARCH-AVCODEC-S162: CodecAbility/CodecListCore 编解码能力查询体系

> **状态**: draft → pending_approval
> **生成时间**: 2026-05-20T13:15:00+08:00
> **Builder**: builder-agent

---

## 一、架构总览

编解码能力查询体系是 AVCodec 对外提供"我的硬件/软件支持哪些格式"能力的核心模块，由三个层次构成：

| 层次 | 文件 | 行数 | 职责 |
|------|------|------|------|
| **数据注册层** | `codec_ability_singleton.cpp` | 229 | 单例管理器，HCodecLoader加载硬件能力 + 软件CodecList注册 |
| **查询引擎层** | `codeclist_core.cpp` | 388 | FindEncoder/FindDecoder 核心查询 + 能力校验（分辨率/帧率/码率/声道/采样率） |
| **能力构建层** | `codeclist_builder.cpp` | 109 | 构造 CodecListBase 派生类，AudioCodecList / VideoCodecList 等 |
| **能力数据** | `audio_codeclist_info.cpp` | 942 | 音频编解码能力定义（MIME/通道/采样率/比特率/格式矩阵） |
| **数据结构** | `avcodec_info.h` | 1225 | CapabilityData / CodecType / VideoCodecType / Range 结构体定义 |

**查询链路**：
```
OH_AVCodec_GetCodecInfo() / OH_AVCodec_FindEncoder()
  → CodecListCore::FindEncoder/FindDecoder()
    → CodecAbilitySingleton::GetCapabilityArray()/GetMimeCapIdxMap()
      → CodecListBase::GetCapabilityList() → audio_codeclist_info.cpp / video_codeclist_info.cpp
```

**关联记忆**：
- S83/S94/S95：CAPI 总览（OH_AVCodec 三件套）
- S137/S161：SA IPC 服务框架（CodecServiceStub/Proxy 五层架构）
- S121/S159：错误码与回调体系

---

## 二、CodecAbilitySingleton 单例管理器

**源码路径**：`services/engine/codeclist/codec_ability_singleton.cpp`

### 2.1 初始化链路

**证据**：`codec_ability_singleton.cpp:40-83`

```cpp
// L40-83: 构造函数初始化顺序
CodecAbilitySingleton::CodecAbilitySingleton()
{
#ifndef CLIENT_SUPPORT_CODEC
    // 1. HCodecLoader 加载硬件编解码器能力（仅在非客户端支持模式）
    std::vector<CapabilityData> videoCapaArray;
    if (HCodecLoader::GetCapabilityList(videoCapaArray) == AVCS_ERR_OK) {
        RegisterCapabilityArray(videoCapaArray, CodecType::AVCODEC_HCODEC);
    }
#endif
    // 2. 软件编解码器列表注册
    std::unordered_map<CodecType, std::shared_ptr<CodecListBase>> codecLists = GetCodecLists();
    for (auto iter = codecLists.begin(); iter != codecLists.end(); iter++) {
        CodecType codecType = iter->first;
        std::vector<CapabilityData> capaArray;
        int32_t ret = iter->second->GetCapabilityList(capaArray);
        if (ret == AVCS_ERR_OK) {
            RegisterCapabilityArray(capaArray, codecType);
        }
    }
}
```

**GetCodecLists() 返回的 CodecList 类型**（L21-39）：
- `AVCODEC_VIDEO_CODEC` → VideoCodecList（AVC 编码器）
- `AVCODEC_VIDEO_HEVC_DECODER` → VideoHevcDecoderList（HEVC 解码器）
- `AVCODEC_VIDEO_VP8_DECODER` → VideoVp8DecoderList（条件编译）
- `AVCODEC_VIDEO_VP9_DECODER` → VideoVp9DecoderList（条件编译）
- `AVCODEC_VIDEO_AV1_DECODER` → VideoAv1DecoderList（条件编译）
- `AVCODEC_VIDEO_AVC_ENCODER` → VideoAvcEncoderList（AVC 编码器）
- `AVCODEC_AUDIO_CODEC` → AudioCodecList（音频编解码器）

### 2.2 三层索引结构

**证据**：`codec_ability_singleton.h:26-29`

```cpp
// L26-29: 三层索引数据结构
std::vector<CapabilityData> capabilityDataArray_;           // 能力数组（扁平索引）
std::unordered_map<std::string, std::vector<size_t>> mimeCapIdxMap_;  // MIME → 能力索引数组
std::unordered_map<std::string, CodecType> nameCodecTypeMap_;         // CodecName → CodecType
```

**注册逻辑**（L98-126）：按 MIME 分组注册，同一 MIME 可能对应多个能力条目（硬件/软件）

### 2.3 能力校验

**证据**：`codec_ability_singleton.cpp:85-110`

```cpp
// L85-110: IsCapabilityValid 校验六项
bool CodecAbilitySingleton::IsCapabilityValid(const CapabilityData &cap)
{
    CHECK_AND_RETURN_RET_LOGW(!cap.codecName.empty(), false, "codecName is empty");
    CHECK_AND_RETURN_RET_LOG(cap.codecType > AVCodecType::AVCODEC_TYPE_NONE && ...
    CHECK_AND_RETURN_RET_LOG(!cap.mimeType.empty(), false, "mimeType is empty");
    CHECK_AND_RETURN_RET_LOG(cap.maxInstance > 0, false, "maxInstance is invalid");
    // 视频：校验 width/height 范围
    // 编码器含 SQR：校验 sqrFactor ≤ 51
}
```

---

## 三、CodecListCore 查询引擎

**源码路径**：`services/engine/codeclist/codeclist_core.cpp`

### 3.1 MIME 向量定义

**证据**：`codeclist_core.cpp:17-36`

```cpp
// L17-36: MIME 类型向量（MIME_VEC）
const std::vector<std::string_view> MIME_VEC = {
    // 视频 21 种
    VIDEO_AVC, VIDEO_HEVC, VIDEO_VVC, VIDEO_MPEG2, VIDEO_H263, VIDEO_MPEG4,
    VIDEO_RV30, VIDEO_RV40, VIDEO_MJPEG, VIDEO_VP8, VIDEO_VP9, VIDEO_MSVIDEO1,
    VIDEO_AV1, VIDEO_VC1, VIDEO_WMV3, VIDEO_WVC1, VIDEO_MPEG1, VIDEO_DVVIDEO,
    VIDEO_RAWVIDEO, VIDEO_CINEPAK,
    // 音频 30+ 种
    AUDIO_AMR_NB, AUDIO_AMR_WB, AUDIO_MPEG, AUDIO_AAC, AUDIO_VORBIS, AUDIO_OPUS,
    AUDIO_FLAC, AUDIO_RAW, AUDIO_G711MU, AUDIO_G711A, AUDIO_GSM_MS, AUDIO_GSM,
    AUDIO_COOK, AUDIO_AC3, AUDIO_WMAV1, AUDIO_WMAV2, AUDIO_WMAPRO, ...
};
```

### 3.2 查询接口

**证据**：`codeclist_core.cpp:60-100`

| 接口 | 说明 |
|------|------|
| `FindEncoder(format)` | 按 Media::Format 查询编码器名称 |
| `FindDecoder(format)` | 按 Media::Format 查询解码器名称 |
| `FindCodecType(codecName)` | 按名称查询 CodecType |
| `FindCodecNameArray(type, mime)` | 按类型+MIME 批量查询 |
| `GetCapability(capData, mime, isEncoder, category)` | 获取单个能力 |
| `GetCapabilityAt(capabilityData, index)` | 按索引获取能力 |

### 3.3 能力校验六项

**证据**：`codeclist_core.h:25-40`

```cpp
// L25-40: 六项能力校验
bool CheckBitrate(const Media::Format &format, const CapabilityData &data);         // 码率范围
bool CheckVideoResolution(const Media::Format &format, const CapabilityData &data);  // 分辨率 [min, max]
bool CheckVideoPixelFormat(const Media::Format &format, const CapabilityData &data); // 像素格式
bool CheckVideoFrameRate(const Media::Format &format, const CapabilityData &data);   // 帧率范围
bool CheckAudioChannel(const Media::Format &format, const CapabilityData &data);     // 声道数
bool CheckAudioSampleRate(const Media::Format &format, const CapabilityData &data);  // 采样率
```

### 3.4 视频/音频能力判定

**证据**：`codeclist_core.cpp:150-200`

```cpp
// L150-170: IsVideoCapSupport 视频能力判定
bool CodecListCore::IsVideoCapSupport(const Media::Format &format, const CapabilityData &data)
{
    return CheckBitrate(format, data) && CheckVideoResolution(format, data) &&
           CheckVideoPixelFormat(format, data) && CheckVideoFrameRate(format, data);
}

// L180+: IsAudioCapSupport 音频能力判定
bool CodecListCore::IsAudioCapSupport(const Media::Format &format, const CapabilityData &data)
{
    return CheckAudioChannel(format, data) && CheckAudioSampleRate(format, data);
}
```

---

## 四、audio_codeclist_info 音频能力数据

**源码路径**：`services/engine/codeclist/audio_codeclist_info.cpp:942行`

### 4.1 音频能力定义范围

音频能力数据定义了 30+ 种音频格式的支持规格，包括：

| 格式 | 典型通道 | 典型采样率 | 典型比特率 |
|------|---------|-----------|-----------|
| AAC | 1/2/6/8 | 8000-96000 | 32-512000 |
| FLAC | 1/2/4/6/8 | 8000-192000 | lossless |
| MP3 | 1/2 | 8000-48000 | 8-320000 |
| G.711 μ/A | 1 | 8000 | 64kbps |
| AMR-NB/WB | 1 | 8000/16000 | 4750-12200 |
| OPUS | 1/2 | 8000-48000 | 6-510000 |
| VORBIS | 1/2 | 8000-192000 | 可变 |

### 4.2 CapabilityData 核心字段

**证据**：`interfaces/inner_api/native/avcodec_info.h:1225行`

```cpp
// avcodec_info.h: CapabilityData 结构体核心字段
struct CapabilityData {
    std::string codecName;        // 编解码器名称（如 "avc_encoder"）
    std::string mimeType;         // MIME 类型（如 "video/avc"）
    CodecType codecType;          // CodecType 枚举（视频/音频/硬件）
    bool isVendor;                // 是否厂商实现（硬件=true，软件=false）
    int32_t maxInstance;          // 最大实例数
    Range width;                  // 视频分辨率范围 [min, max]
    Range height;                 // 视频高度范围
    Range bitrate;                // 码率范围
    std::vector<BitrateMode> bitrateMode;  // CBR/VBR/CQ
    Range<int32_t> sqrFactor;     // 质量缩放因子（SQR模式）
    std::vector<int32_t> profiles;  // Profile 列表
    std::map<int32_t, std::vector<int32_t>> profileLevelsMap;  // Profile→Level 映射
    std::map<ImgSize, Range> measuredFrameRate;  // 实测帧率表
    std::vector<AudioSampleFormat> supportSampleFormats;  // 支持的采样格式
    std::vector<int32_t> supportChannelLayouts;  // 支持的通道布局
    std::vector<int32_t> supportSampleRates;     // 支持的采样率
};
```

---

## 五、codeclist_builder 能力构建器

**源码路径**：`services/engine/codeclist/codeclist_builder.cpp:109行`

### 5.1 CodecListBase 派生类体系

**证据**：`codeclist_builder.cpp:40-109`

```cpp
// L40-70: CodecListBase 派生类工厂
class CodecListBuilder {
    std::shared_ptr<CodecListBase> CreateVideoCodecList();
    std::shared_ptr<CodecListBase> CreateAudioCodecList();
    std::shared_ptr<CodecListBase> CreateVideoHevcDecoderList();
    std::shared_ptr<CodecListBase> CreateVideoAvcEncoderList();
    // ... VP8/VP9/AV1 解码器列表（条件编译）
};
```

### 5.2 AudioCodecList 音频能力注册

**证据**：`audio_codeclist_info.cpp:1-100`

音频编解码器能力通过 `AudioCodecList::GetCapabilityList(capaArray)` 批量注册到 `CodecAbilitySingleton`。

---

## 六、VideoCodecType 视频编解码器类型判定

**证据**：`codec_ability_singleton.cpp:180-210`

```cpp
// L180-210: GetVideoCodecTypeByCodecName 四态判定
int32_t CodecAbilitySingleton::GetVideoCodecTypeByCodecName(const std::string &codecName)
{
    // 四态枚举：DECODER_HARDWARE / DECODER_SOFTWARE / ENCODER_HARDWARE / ENCODER_SOFTWARE
    constexpr auto hdecPair = std::pair(true,  static_cast<int32_t>(AVCODEC_TYPE_VIDEO_DECODER));
    constexpr auto sdecPair = std::pair(false, static_cast<int32_t>(AVCODEC_TYPE_VIDEO_DECODER));
    constexpr auto hencPair = std::pair(true,  static_cast<int32_t>(AVCODEC_TYPE_VIDEO_ENCODER));
    constexpr auto sencPair = std::pair(false, static_cast<int32_t>(AVCODEC_TYPE_VIDEO_ENCODER));

    auto vcodecTypePair = std::make_pair(it->isVendor, it->codecType);
    if (vcodecTypePair == hdecPair) return DECODER_HARDWARE;
    else if (vcodecTypePair == hencPair) return ENCODER_HARDWARE;
    else if (vcodecTypePair == sdecPair) return DECODER_SOFTWARE;
    else if (vcodecTypePair == sencPair) return ENCODER_SOFTWARE;
    return UNKNOWN;
}
```

---

## 七、关键文件汇总

| 文件 | 路径 | 行数 | 角色 |
|------|------|------|------|
| codec_ability_singleton.cpp | services/engine/codeclist/ | 229 | 单例管理器，三层索引注册，isVendor四态判定 |
| codec_ability_singleton.h | services/engine/codeclist/ | ~90 | CapabilityDataArray + MIME索引 + Name索引 |
| codeclist_core.cpp | services/engine/codeclist/ | 388 | 查询引擎，六项能力校验，MIME向量 |
| codeclist_core.h | services/engine/codeclist/ | ~80 | CodecListCore 类定义，六校验函数声明 |
| codeclist_builder.cpp | services/engine/codeclist/ | 109 | CodecListBase 派生类工厂 |
| audio_codeclist_info.cpp | services/engine/codeclist/ | 942 | 音频编解码能力数据定义（30+格式） |
| avcodec_info.h | interfaces/inner_api/native/ | 1225 | CapabilityData / Range / CodecType 结构体 |

---

## 八、关联主题

| 关联 | 说明 |
|------|------|
| S83/S94/S95 | CAPI 总览：OH_AVCodec 对象模型与 FindEncoder/GetCodecInfo |
| S137/S161 | SA IPC 服务框架（CodecServiceStub ↔ CodecServiceProxy 五层架构） |
| S121/S159 | 错误码与回调体系（AVCodecServiceErrCode 50+条目） |
| S21 | AVCodec IPC 架构：CodecServiceProxy ↔ CodecServiceStub 双向代理 |
| S95 | AudioCodec CAPI：AVCodecAudioCodecImpl 三层架构 |
| S84/S88 | VideoEncoder / VideoDecoder / AudioDecoder CAPI 实现 |

---

## 九、备注

- 本主题（S162）与 S83/S94/S95 CAPI 体系紧密关联，CAPI 层调用 CodecListCore 查询能力
- HCodecLoader 在非 CLIENT_SUPPORT_CODEC 模式下加载硬件能力，否则仅使用软件 CodecList
- AudioCodecList 能力数据由 `audio_codeclist_info.cpp` 定义（942行），是音频接入的重要参考
- VideoCodecType 四态（DECODER_HARDWARE/SOFTWARE, ENCODER_HARDWARE/SOFTWARE）由 `isVendor` 字段判定