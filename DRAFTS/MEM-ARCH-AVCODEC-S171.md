# MEM-ARCH-AVCODEC-S171 — CodecCapabilityAdapter 能力查询适配器

**主题**：CodecCapabilityAdapter 能力查询适配器——Filter 层能力查询与 AVCodecList 三层桥接
**scope**：AVCodec, Capability, Filter, Adapter, CodecList, WaterMark
**关联场景**：新需求开发/问题定位/能力查询
**状态**：pending_approval
**生成时间**：2026-06-09T02:15 GMT+8
**Builder**：builder-agent

---

## 一、架构定位

CodecCapabilityAdapter 是 MediaEngine Filter 层的能力查询适配器，位于 `services/media_engine/filters/codec_capability_adapter.cpp`（113行）与 `interfaces/inner_api/native/codec_capability_adapter.h`（44行）。

它的核心职责：**封装 AVCodecList 能力查询接口，向 Filter 层提供统一的能力查询入口**，特别服务于水印能力查询（IsWatermarkSupported）和可用编码器列表查询（GetAvailableEncoder）。

```
Filter Pipeline
    ↓
CodecCapabilityAdapter（Filter层适配器）
    ↓
AVCodecListFactory::CreateAVCodecList()
    ↓
AVCodecList（CodecListCore / CodecAbilitySingleton）
```

---

## 二、关键文件与行号级 Evidence

### 2.1 头文件（codec_capability_adapter.h）

```cpp
// L24-35: CodecCapabilityAdapter 类定义
class CodecCapabilityAdapter {
public:
    explicit CodecCapabilityAdapter();           // L27
    ~CodecCapabilityAdapter();                   // L28
    void Init();                                  // L30
    Status GetAvailableEncoder( // L31
        std::vector<MediaAVCodec::CapabilityData*> &encoderInfo);
    Status IsWatermarkSupported( // L32
        std::string &codecMimeType, bool &isWatermarkSupported);
private:
    Status GetVideoEncoder(std::vector<...>&);  // L34
    Status GetAudioEncoder(std::vector<...>&);   // L35
    std::shared_ptr<MediaAVCodec::AVCodecList> codeclist_ {nullptr}; // L37
};
```

### 2.2 实现文件（codec_capability_adapter.cpp）

```cpp
// L50: Init——创建AVCodecList单例
void CodecCapabilityAdapter::Init()
{
    codeclist_ = MediaAVCodec::AVCodecListFactory::CreateAVCodecList(); // L52
    MEDIA_LOG_I("CodecCapabilityAdapter Init end"); // L53
}

// L55-59: GetAvailableEncoder——合并音视频编码器列表
Status CodecCapabilityAdapter::GetAvailableEncoder(
    std::vector<MediaAVCodec::CapabilityData*> &encoderInfo)
{
    GetAudioEncoder(encoderInfo);  // L57
    GetVideoEncoder(encoderInfo);  // L58
    return Status::OK;
}

// L61-81: IsWatermarkSupported——硬件优先、能力特性查询
Status CodecCapabilityAdapter::IsWatermarkSupported(
    std::string &codecMimeType, bool &isWatermarkSupported)
{
    // L63-70: 硬件编码器优先查询
    MediaAVCodec::CapabilityData *capabilityData =
        codeclist_->GetCapability(codecMimeType, true,
            MediaAVCodec::AVCodecCategory::AVCODEC_HARDWARE);  // L64
    if (capabilityData != nullptr) {
        if (capabilityData->featuresMap.count( // L66
            static_cast<int32_t>(MediaAVCodec::AVCapabilityFeature::VIDEO_WATERMARK))) {
            isWatermarkSupported = true;    // L68
        } else {
            isWatermarkSupported = false;   // L70
        }
        return Status::OK;
    }
    // L71-79: 软件编码器fallback查询
    capabilityData = codeclist_->GetCapability(codecMimeType, true,
        MediaAVCodec::AVCodecCategory::AVCODEC_SOFTWARE); // L73
    if (capabilityData != nullptr) {
        if (capabilityData->featuresMap.count(
            static_cast<int32_t>(MediaAVCodec::AVCapabilityFeature::VIDEO_WATERMARK))) {
            isWatermarkSupported = true;    // L77
        } else {
            isWatermarkSupported = false;   // L79
        }
        return Status::OK;
    }
    return Status::ERROR_UNKNOWN;  // L80
}

// L83-91: GetAudioEncoder——AAC软件编码器能力查询
Status CodecCapabilityAdapter::GetAudioEncoder(
    std::vector<MediaAVCodec::CapabilityData*> &encoderInfo)
{
    MediaAVCodec::CapabilityData *capabilityData =
        codeclist_->GetCapability(
            std::string(MediaAVCodec::CodecMimeType::AUDIO_AAC),  // L86
            true, MediaAVCodec::AVCodecCategory::AVCODEC_SOFTWARE); // L87
    if (capabilityData != nullptr) {
        encoderInfo.push_back(capabilityData);  // L89
    }
    return Status::OK;
}

// L93-113: GetVideoEncoder——AVC/HEVC 硬件优先、软件fallback
Status CodecCapabilityAdapter::GetVideoEncoder(
    std::vector<MediaAVCodec::CapabilityData*> &encoderInfo)
{
    // L95-102: AVC硬件优先，否则软件fallback
    MediaAVCodec::CapabilityData *capabilityDataAVC =
        codeclist_->GetCapability(
            std::string(MediaAVCodec::CodecMimeType::VIDEO_AVC),  // L96
            true, MediaAVCodec::AVCodecCategory::AVCODEC_HARDWARE); // L97
    if (capabilityDataAVC != nullptr) {
        encoderInfo.push_back(capabilityDataAVC);   // L99
    } else {
        MediaAVCodec::CapabilityData *capabilityDataAVCSoft =
            codeclist_->GetCapability(
                std::string(MediaAVCodec::CodecMimeType::VIDEO_AVC), true,
                MediaAVCodec::AVCodecCategory::AVCODEC_SOFTWARE); // L102-103
        if (capabilityDataAVCSoft != nullptr) {
            encoderInfo.push_back(capabilityDataAVCSoft);  // L104
        }
    }
    // L106-110: HEVC 硬件优先
    MediaAVCodec::CapabilityData *capabilityDataHEVC =
        codeclist_->GetCapability(
            std::string(MediaAVCodec::CodecMimeType::VIDEO_HEVC), true,
            MediaAVCodec::AVCodecCategory::AVCODEC_HARDWARE);  // L107-108
    if (capabilityDataHEVC != nullptr) {
        encoderInfo.push_back(capabilityDataHEVC);  // L110
    }
    return Status::OK;
}
```

---

## 三、核心设计模式

### 3.1 硬件优先、软件 Fallback

所有查询遵循**硬件优先**策略：

```
codecMimeType + isEncoder=true + AVCODEC_HARDWARE
    ↓ [found]
    → return capabilityData with VIDEO_WATERMARK check
    ↓ [not found]
codecMimeType + isEncoder=true + AVCODEC_SOFTWARE
    ↓ [found]
    → return capabilityData with VIDEO_WATERMARK check
    ↓ [not found]
    → return ERROR_UNKNOWN
```

### 3.2 AVCodecCategory 枚举

```cpp
// avcodec_info.h L48-51
enum class AVCodecCategory : int32_t {
    AVCODEC_HARDWARE = 0,
    AVCODEC_SOFTWARE,
};
```

### 3.3 能力特性查询（VIDEO_WATERMARK）

```cpp
// avcodec_info.h L60-64
enum class AVCapabilityFeature : int32_t {
    VIDEO_WATERMARK = 3,
};
```

capabilityData->featuresMap 是 `std::map<int32_t, int32_t>`，通过 `count()` 判断特性是否存在。

---

## 四、调用方上下文（谁在使用 CodecCapabilityAdapter）

### 4.1 Filter 层集成

CodecCapabilityAdapter 被 Filter 层组件调用，用于：
- **WaterMarkFilter**（水印过滤器）：在初始化时通过 `IsWatermarkSupported` 判断目标 Codec 是否支持水印
- **Transcoder Pipeline**：转码前查询可用编码器列表

### 4.2 UnitTest覆盖

```
codec_capability_adapter_unittest.cpp:
  - IsWatermarkSupported_001: HW支持水印 → true
  - IsWatermarkSupported_002: SW支持水印 → true
  - IsWatermarkSupported_003: 无capabilityData → ERROR_UNKNOWN
  - GetAudioEncoder_001: AAC软件编码器
  - GetVideoEncoder_001: AVC硬件编码器
  - GetVideoEncoder_002: ~CodecCapabilityAdapter后codeclist_==nullptr
```

---

## 五、与相关记忆的关联

| 关联主题 | 关系 | 说明 |
|---------|------|------|
| S162 | 上游能力体系 | CodecAbility/CodecListCore 是 CodecCapabilityAdapter 的底层能力引擎 |
| S47 | 能力模型互补 | CodecCapability 五层能力模型与 CodecCapabilityAdapter 查询入口 |
| S135 | 水印功能调用方 | WaterMarkFilter 调用 IsWatermarkSupported 判断编码器水印支持 |
| S83/S94 | CAPI能力查询 | Native C API OH_AVCapability能力查询与 CodecCapabilityAdapter Filter层查询 |

---

## 六、关键结论

1. **CodecCapabilityAdapter 是 Filter 层的能力查询桥接器**：封装 AVCodecList，向 Filter 层屏蔽底层能力查询复杂度
2. **硬件优先策略**：所有查询优先硬件编码器，不存在则 fallback 到软件编码器
3. **VIDEO_WATERMARK 特性查询**：通过 featuresMap.count() 判断，返回 bool
4. **支持的 Codec 类型**：音频 AAC（软件）、视频 AVC（硬软）、视频 HEVC（硬件）
5. **轻量级实现**：113行cpp + 44行h，专注于能力查询代理，无复杂业务逻辑