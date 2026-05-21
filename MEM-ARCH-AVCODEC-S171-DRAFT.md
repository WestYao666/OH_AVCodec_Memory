---
mem_id: MEM-ARCH-AVCODEC-S171
title: CodecCapabilityAdapter 编解码能力查询适配器——AVCodecList工厂注入与水印能力探测
status: draft
scope: [AVCodec, Filter, CodecCapability, WaterMark, AVCodecList, Factory, Adapter, Pipeline]
assoc_scenarios: [新需求开发/问题定位/能力探测/水印叠加]
sources:
  - https://gitcode.com/openharmony/multimedia_av_codec (web_fetch verified)
created_by: builder-agent
created_at: "2026-05-21T03:20:00+08:00"
summary: CodecCapabilityAdapter Filter适配器，AVCodecList工厂注入，IsWatermarkSupported软硬双层查询，GetAvailableEncoder音视频查询
evidence_count: 12
source_files: 3
---

# MEM-ARCH-AVCODEC-S171 — CodecCapabilityAdapter 编解码能力查询适配器

## Metadata

| Field | Value |
|-------|-------|
| mem_id | MEM-ARCH-AVCODEC-S171 |
| topic | CodecCapabilityAdapter 编解码能力查询适配器——AVCodecList工厂注入与水印能力探测 |
| status | draft |
| created | 2026-05-21T03:20:00+08:00 |
| builder | builder-agent |
| source | GitCode web_fetch 验证 (raw.gitcode.com) |
| evidence | 12条行号级证据 |

---

## 一、架构定位

`CodecCapabilityAdapter` 是 MediaEngine Filter 层的能力查询适配器，位于：

- **实现**：`services/media_engine/filters/codec_capability_adapter.cpp`（113行）
- **接口**：`interfaces/inner_api/native/codec_capability_adapter.h`（60行）

它将 `AVCodecList` 的能力查询接口暴露给 Filter 管线系统，主要服务于 `WaterMarkFilter`（水印过滤器）的硬件能力探测需求。

### 1.1 在 Filter Pipeline 中的位置

```
Filter Pipeline
├── AudioCaptureFilter
├── AudioDecoderAdapter
├── CodecCapabilityAdapter  ← 能力查询适配器
├── WaterMarkFilter         ← 调用 CodecCapabilityAdapter
├── VideoDecoderFilter
└── RenderFilter
```

---

## 二、关键源码结构

### 2.1 类定义（codec_capability_adapter.h:22-36）

```cpp
class CodecCapabilityAdapter {
public:
    explicit CodecCapabilityAdapter();    // L22
    ~CodecCapabilityAdapter();             // L23

    void Init();                           // L25

    Status GetAvailableEncoder(std::vector<MediaAVCodec::CapabilityData*> &encoderInfo);  // L27
    Status IsWatermarkSupported(std::string &CodecMimeType, bool &isWatermarkSupported);    // L28
private:
    Status GetVideoEncoder(std::vector<MediaAVCodec::CapabilityData*> &encoderInfo);        // L31
    Status GetAudioEncoder(std::vector<MediaAVCodec::CapabilityData*> &encoderInfo);        // L33
    std::shared_ptr<MediaAVCodec::AVCodecList> codeclist_ {nullptr};                        // L35
};
```

**关键成员**：
- `codeclist_`：持有 `AVCodecList` 单例的共享指针，通过 `AVCodecListFactory::CreateAVCodecList()` 创建（h:35, cpp:40）
- `GetAvailableEncoder`：对外统一入口，调用 GetAudioEncoder + GetVideoEncoder
- `IsWatermarkSupported`：查询指定 MIME 类型是否支持 VIDEO_WATERMARK 功能

### 2.2 Init 初始化（codec_capability_adapter.cpp:38-42）

```cpp
void CodecCapabilityAdapter::Init()
{
    codeclist_ = MediaAVCodec::AVCodecListFactory::CreateAVCodecList();  // L40
    MEDIA_LOG_I("CodecCapabilityAdapter Init end");                      // L41
}
```

**关键行为**：
- 通过工厂模式创建 AVCodecList 实例（延迟初始化，非构造时）
- MEDIA_LOG_I 打印初始化完成日志

### 2.3 水印能力查询（codec_capability_adapter.cpp:51-79）

```cpp
Status CodecCapabilityAdapter::IsWatermarkSupported(std::string &codecMimeType, bool &isWatermarkSupported)
{
    // Step 1: 查询硬件编码器 (L53-62)
    MediaAVCodec::CapabilityData *capabilityData = codeclist_->GetCapability(
        codecMimeType, true, MediaAVCodec::AVCodecCategory::AVCODEC_HARDWARE);  // L53-54
    if (capabilityData != nullptr) {
        if (capabilityData->featuresMap.count(
            static_cast<int32_t>(MediaAVCodec::AVCapabilityFeature::VIDEO_WATERMARK))) {  // L57
            isWatermarkSupported = true;   // L58
        } else {
            isWatermarkSupported = false;  // L60
        }
        return Status::OK;                  // L61
    }

    // Step 2: fallback 到软件编码器 (L65-75)
    capabilityData = codeclist_->GetCapability(
        codecMimeType, true, MediaAVCodec::AVCodecCategory::AVCODEC_SOFTWARE);  // L65-66
    if (capabilityData != nullptr) {
        if (capabilityData->featuresMap.count(
            static_cast<int32_t>(MediaAVCodec::AVCapabilityFeature::VIDEO_WATERMARK))) {  // L69
            isWatermarkSupported = true;   // L70
        } else {
            isWatermarkSupported = false;  // L72
        }
        return Status::OK;                  // L73
    }

    return Status::ERROR_UNKNOWN;          // L76
}
```

**查询策略**：
1. **先查硬件编码器**：`AVCodecCategory::AVCODEC_HARDWARE`
2. **Hardware 不存在或不支持时**，fallback 到软件编码器：`AVCodecCategory::AVCODEC_SOFTWARE`
3. **均不存在**返回 `ERROR_UNKNOWN`

### 2.4 音视频编码器查询（codec_capability_adapter.cpp:80-107）

```cpp
Status CodecCapabilityAdapter::GetAudioEncoder(std::vector<MediaAVCodec::CapabilityData*> &encoderInfo)
{
    // 只查询 AAC 软件编码器能力 (L82-87)
    MediaAVCodec::CapabilityData *capabilityData = codeclist_->GetCapability(
        std::string(MediaAVCodec::CodecMimeType::AUDIO_AAC),
        true, MediaAVCodec::AVCodecCategory::AVCODEC_SOFTWARE);  // L83-84
    if (capabilityData != nullptr) {
        encoderInfo.push_back(capabilityData);  // L86
    }
    return Status::OK;  // L88
}

Status CodecCapabilityAdapter::GetVideoEncoder(std::vector<MediaAVCodec::CapabilityData*> &encoderInfo)
{
    // 查询 AVC 硬件，若无则 fallback 软件 (L92-100)
    MediaAVCodec::CapabilityData *capabilityDataAVC = codeclist_->GetCapability(
        std::string(MediaAVCodec::CodecMimeType::VIDEO_AVC),
        true, MediaAVCodec::AVCodecCategory::AVCODEC_HARDWARE);  // L92-94
    if (capabilityDataAVC != nullptr) {
        encoderInfo.push_back(capabilityDataAVC);  // L95
    } else {
        MediaAVCodec::CapabilityData *capabilityDataAVCSoft = codeclist_->GetCapability(
            std::string(MediaAVCodec::CodecMimeType::VIDEO_AVC), true,
            MediaAVCodec::AVCodecCategory::AVCODEC_SOFTWARE);  // L97-99
        if (capabilityDataAVCSoft != nullptr) {
            encoderInfo.push_back(capabilityDataAVCSoft);  // L100
        }
    }

    // 查询 HEVC 硬件编码器 (L105-107)
    MediaAVCodec::CapabilityData *capabilityDataHEVC = codeclist_->GetCapability(
        std::string(MediaAVCodec::CodecMimeType::VIDEO_HEVC),
        true, MediaAVCodec::AVCodecCategory::AVCODEC_HARDWARE);  // L105-106
    if (capabilityDataHEVC != nullptr) {
        encoderInfo.push_back(capabilityDataHEVC);  // L107
    }
    return Status::OK;
}
```

---

## 三、枚举体系

### 3.1 AVCodecCategory（avcodec_info.h）

```cpp
enum class AVCodecCategory : int32_t {
    AVCODEC_NONE = -1,
    AVCODEC_HARDWARE = 0,   // 硬件编解码器
    AVCODEC_SOFTWARE,        // 软件编解码器
};
```

### 3.2 AVCapabilityFeature（avcodec_info.h）

```cpp
enum class AVCapabilityFeature : int32_t {
    VIDEO_ENCODER_TEMPORAL_SCALABILITY = 0,
    VIDEO_ENCODER_LONG_TERM_REFERENCE = 1,
    VIDEO_LOW_LATENCY = 2,
    VIDEO_WATERMARK = 3,      // 视频水印功能
    VIDEO_RPR = 4,
    VIDEO_ENCODER_QP_MAP = 5,
    VIDEO_DECODER_SEEK_WITHOUT_FLUSH = 6,
    VIDEO_ENCODER_B_FRAME = 7,
    VIDEO_DECODER_OUTPUT_IN_DECODING_ORDER = 8,
    VIDEO_ENCODER_PREPROC_DOWNSAMPLING = 9,
    VIDEO_ENCODER_PREPROC_CROP = 10,
    MAX_VALUE
};
```

### 3.3 CapabilityData.featuresMap

```cpp
struct CapabilityData {
    std::string codecName = "";
    int32_t codecType = AVCODEC_TYPE_NONE;
    std::string mimeType = "";
    // ... 其他字段 ...
    // featuresMap: 特性枚举 → 存在标记
    // 通过 featuresMap.count(VIDEO_WATERMARK) 检查水印支持
};
```

---

## 四、AVCodecList 工厂体系

### 4.1 AVCodecListFactory（avcodec_list.h:43-53）

```cpp
class __attribute__((visibility("default"))) AVCodecListFactory {
public:
#ifdef UNSUPPORT_CODECLIST
    static std::shared_ptr<AVCodecList> CreateAVCodecList()
    {
        return nullptr;
    }
#else
    static std::shared_ptr<AVCodecList> CreateAVCodecList();  // 工厂方法
#endif
private:
    AVCodecListFactory() = default;
    ~AVCodecListFactory() = default;
};
```

### 4.2 GetCapability 三参数查询（avcodec_list.h:35-39）

```cpp
virtual CapabilityData *GetCapability(
    const std::string &mime,    // MIME 类型字符串（如 "video/avc"）
    const bool isEncoder,      // true=查询编码器，false=查询解码器
    const AVCodecCategory &category  // HARDWARE 或 SOFTWARE
) = 0;
```

---

## 五、单元测试证据（codec_capability_adapter_unit_test.cpp）

### 5.1 水印能力测试用例（L40-52）

```cpp
HWTEST_F(CodecCapabilityAdapterUnitTest, CodecCapabilityAdapter_IsWatermarkSupported_0100, TestSize.Level1)
{
    ASSERT_NE(codecCapabilityAdapter_, nullptr);
    codecCapabilityAdapter_->Init();
    
    // 测试不存在的 MIME 类型 → ERROR_UNKNOWN
    std::string codecMimeType = std::string("audio/test");
    bool isWatermarkSupported = true;
    EXPECT_EQ(codecCapabilityAdapter_->IsWatermarkSupported(codecMimeType, isWatermarkSupported),
        Status::ERROR_UNKNOWN);

    // 测试 VIDEO_AVC → OK
    codecMimeType = std::string(MediaAVCodec::CodecMimeType::VIDEO_AVC);
    isWatermarkSupported = true;
    EXPECT_EQ(codecCapabilityAdapter_->IsWatermarkSupported(codecMimeType, isWatermarkSupported), Status::OK);
    isWatermarkSupported = false;
    EXPECT_EQ(codecCapabilityAdapter_->IsWatermarkSupported(codecMimeType, isWatermarkSupported), Status::OK);
}
```

**测试覆盖**：
- 不支持的 MIME 类型 → `ERROR_UNKNOWN`
- 支持的 MIME 类型（VIDEO_AVC）→ `Status::OK`

### 5.2 编码器查询测试用例（L54-65）

```cpp
HWTEST_F(CodecCapabilityAdapterUnitTest, CodecCapabilityAdapter_GetAvailableEncoder_0100, TestSize.Level1)
{
    ASSERT_NE(codecCapabilityAdapter_, nullptr);
    codecCapabilityAdapter_->Init();
    std::vector<MediaAVCodec::CapabilityData*> encoderCapData;
    EXPECT_EQ(codecCapabilityAdapter_->GetAvailableEncoder(encoderCapData), Status::OK);
}
```

---

## 六、与其他 S 系列主题的关联

| 关联记忆 | 关系 |
|---------|------|
| S47 | CodecCapability 能力查询与匹配机制（五层能力体系） |
| S71 | CodecList 服务架构——CodecListServer SA 三层 |
| S162 | CodecAbility/CodecListCore 编解码能力查询体系 |
| S135 | WaterMarkFilter 水印过滤器（直接使用者） |
| S83 | AVCodec Native C API 架构（AVCodecListFactory 来源） |

---

## 七、Evidence 行号索引（GitCode web_fetch 验证）

| # | 文件 | 行号范围 | 关键内容 |
|---|------|---------|---------|
| 1 | codec_capability_adapter.h | 22-25 | 构造/析构/Init 声明 |
| 2 | codec_capability_adapter.h | 27-28 | GetAvailableEncoder/IsWatermarkSupported 公开接口 |
| 3 | codec_capability_adapter.h | 31-35 | 私有接口 + codeclist_ 成员 |
| 4 | codec_capability_adapter.cpp | 38-42 | Init() 工厂创建 AVCodecList |
| 5 | codec_capability_adapter.cpp | 51-61 | IsWatermarkSupported 硬件查询逻辑 |
| 6 | codec_capability_adapter.cpp | 65-76 | IsWatermarkSupported 软件 fallback + ERROR_UNKNOWN |
| 7 | codec_capability_adapter.cpp | 80-88 | GetAudioEncoder AAC 软件编码器查询 |
| 8 | codec_capability_adapter.cpp | 90-107 | GetVideoEncoder AVC+HEVC 双查询 |
| 9 | avcodec_info.h | (enum) | AVCodecCategory HARDWARE/SOFTWARE |
| 10 | avcodec_info.h | (enum) | AVCapabilityFeature VIDEO_WATERMARK=3 |
| 11 | avcodec_list.h | 43-53 | AVCodecListFactory::CreateAVCodecList 工厂声明 |
| 12 | avcodec_list.h | 35-39 | GetCapability(mime, isEncoder, category) 虚方法 |

---

## 八、架构要点总结

1. **Filter 层适配器**：CodecCapabilityAdapter 将 Codec 能力查询能力适配到 Filter Pipeline
2. **延迟初始化**：codeclist_ 在 Init() 时创建，非构造时
3. **软硬 fallback**：IsWatermarkSupported 先查 HARDWARE，再查 SOFTWARE，顺序不可交换
4. **featuresMap 探测**：通过 `featuresMap.count(VIDEO_WATERMARK)` 检查特性存在性
5. **工厂模式**：AVCodecListFactory::CreateAVCodecList() 提供全局单例访问入口

---

*Builder Agent | 2026-05-21T03:20+08:00 | draft → pending_approval*