# MEM-ARCH-AVCODEC-S171: CodecCapabilityAdapter 编解码能力查询适配器

**状态**: draft  
**主题**: CodecCapabilityAdapter 编解码能力查询适配器——AVCodecList工厂注入与水印能力探测  
**scope**: AVCodec, MediaEngine, Filter, CodecCapability, AVCodecList, CapabilityData, Watermark, WaterMarkFilter, Adapter  
**生成时间**: 2026-05-21T13:09  
**来源**: GitCode 仓库 https://gitcode.com/openharmony/multimedia_av_codec / 本地镜像 /home/west/av_codec_repo  
**builder**: builder-agent (subagent)  
**关联**: S47/S71/S162(CodecCapability体系), S135(WaterMarkFilter)

---

## 一、架构定位

CodecCapabilityAdapter 是 MediaEngine Filter 层的**能力查询适配器**，位于 Filter 适配层（Layer 1），负责：
1. 注入 AVCodecList 工厂单例
2. 查询可用编码器（视频 AVC/HEVC、音频 AAC）
3. 探测水印能力（硬件优先两段查询）

```
Filter 适配层（CodecCapabilityAdapter）
    ↓ codeclist_
AVCodecList 工厂 → AVCodecList 单例
    ↓ GetCapability()
CodecListCore 能力查询引擎
    ↓
CapabilityData (featuresMap)
```

---

## 二、关键源文件

| 文件 | 行数 | 路径 |
|------|------|------|
| codec_capability_adapter.h | 44行 | interfaces/inner_api/native/codec_capability_adapter.h |
| codec_capability_adapter.cpp | 113行 | services/media_engine/filters/codec_capability_adapter.cpp |
| avcodec_list.h | 77行 | interfaces/inner_api/native/avcodec_list.h |
| avcodec_info.h | ~320行 | interfaces/inner_api/native/avcodec_info.h |

---

## 三、CodecCapabilityAdapter 类定义

**文件**: codec_capability_adapter.h

```cpp
class CodecCapabilityAdapter {
public:
    explicit CodecCapabilityAdapter();
    ~CodecCapabilityAdapter();
    void Init();  // L30: 创建 AVCodecList 单例
    Status GetAvailableEncoder(std::vector<MediaAVCodec::CapabilityData*> &encoderInfo);  // L32-33
    Status IsWatermarkSupported(std::string &CodecMimeType, bool &isWatermarkSupported);  // L34
private:
    Status GetVideoEncoder(...);  // L37: 查询视频编码器
    Status GetAudioEncoder(...);  // L38: 查询音频编码器
    std::shared_ptr<MediaAVCodec::AVCodecList> codeclist_ {nullptr};  // L40: 工厂注入
};
```

**关键证据点**:
- L40: `std::shared_ptr<MediaAVCodec::AVCodecList> codeclist_ {nullptr};` — Filter适配层持有AVCodecList单例的shared_ptr
- L30: `void Init();` — Init()调用AVCodecListFactory::CreateAVCodecList()

---

## 四、Init() 实现——AVCodecList 工厂注入

**文件**: codec_capability_adapter.cpp

```cpp
// L38-42
void CodecCapabilityAdapter::Init()
{
    codeclist_ = MediaAVCodec::AVCodecListFactory::CreateAVCodecList();  // L40: 工厂方法创建
    MEDIA_LOG_I("CodecCapabilityAdapter Init end");
}
```

**关键证据点**:
- L40: `MediaAVCodec::AVCodecListFactory::CreateAVCodecList()` — 工厂模式创建AVCodecList单例
- 工厂方法定义在 avcodec_list.h L67-74，UNSUPPORT_CODECLIST 条件编译开关

---

## 五、GetAvailableEncoder() 实现——三路编码器查询

**文件**: codec_capability_adapter.cpp

```cpp
// L44-47
Status CodecCapabilityAdapter::GetAvailableEncoder(std::vector<MediaAVCodec::CapabilityData*> &encoderInfo)
{
    GetAudioEncoder(encoderInfo);  // L45: 查询音频 AAC 软件编码器
    GetVideoEncoder(encoderInfo);  // L46: 查询视频 AVC/HEVC 编码器
    return Status::OK;
}
```

### 5.1 GetVideoEncoder()——AVC/HEVC 硬件优先

**文件**: codec_capability_adapter.cpp

```cpp
// L84-103
Status CodecCapabilityAdapter::GetVideoEncoder(std::vector<MediaAVCodec::CapabilityData*> &encoderInfo)
{
    // L86-93: 查询 AVC 硬件编码器
    MediaAVCodec::CapabilityData *capabilityDataAVC = codeclist_->GetCapability(
        std::string(MediaAVCodec::CodecMimeType::VIDEO_AVC), true, 
        MediaAVCodec::AVCodecCategory::AVCODEC_HARDWARE);  // L87-88
    if (capabilityDataAVC != nullptr) {
        encoderInfo.push_back(capabilityDataAVC);
    } else {
        // L91-96: 硬件不支持则 fallback 到软件
        MediaAVCodec::CapabilityData *capabilityDataAVCSoft = codeclist_->GetCapability(
            std::string(MediaAVCodec::CodecMimeType::VIDEO_AVC), true,
            MediaAVCodec::AVCodecCategory::AVCODEC_SOFTWARE);
        if (capabilityDataAVCSoft != nullptr) {
            encoderInfo.push_back(capabilityDataAVCSoft);
        }
    }

    // L97-101: 查询 HEVC 硬件编码器
    MediaAVCodec::CapabilityData *capabilityDataHEVC = codeclist_->GetCapability(
        std::string(MediaAVCodec::CodecMimeType::VIDEO_HEVC), true,
        MediaAVCodec::AVCodecCategory::AVCODEC_HARDWARE);
    if (capabilityDataHEVC != nullptr) {
        encoderInfo.push_back(capabilityDataHEVC);
    }
    return Status::OK;
}
```

**关键证据点**:
- L87-88: `GetCapability(VIDEO_AVC, true, AVCODEC_HARDWARE)` — 查询硬件编码器
- L91-96: 软件 fallback — 硬件不支持时自动切换到 AVCODEC_SOFTWARE
- L97-101: HEVC 硬件编码器单独查询

### 5.2 GetAudioEncoder()——AAC 软件编码器

**文件**: codec_capability_adapter.cpp

```cpp
// L77-82
Status CodecCapabilityAdapter::GetAudioEncoder(std::vector<MediaAVCodec::CapabilityData*> &encoderInfo)
{
    MediaAVCodec::CapabilityData *capabilityData = codeclist_->GetCapability(
        std::string(MediaAVCodec::CodecMimeType::AUDIO_AAC), true,
        MediaAVCodec::AVCodecCategory::AVCODEC_SOFTWARE);  // L79
    if (capabilityData != nullptr) {
        encoderInfo.push_back(capabilityData);
    }
    return Status::OK;
}
```

**关键证据点**:
- L79: `GetCapability(AUDIO_AAC, true, AVCODEC_SOFTWARE)` — 音频只查软件编码器

---

## 六、IsWatermarkSupported()——硬件优先两段查询

**文件**: codec_capability_adapter.cpp

```cpp
// L49-75
Status CodecCapabilityAdapter::IsWatermarkSupported(std::string &codecMimeType, bool &isWatermarkSupported)
{
    // L50-58: 第一段——硬件编码器查询
    MediaAVCodec::CapabilityData *capabilityData = codeclist_->GetCapability(codecMimeType,
        true, MediaAVCodec::AVCodecCategory::AVCODEC_HARDWARE);
    if (capabilityData != nullptr) {
        if (capabilityData->featuresMap.count(
            static_cast<int32_t>(MediaAVCodec::AVCapabilityFeature::VIDEO_WATERMARK))) {  // L54
            isWatermarkSupported = true;
        } else {
            isWatermarkSupported = false;
        }
        return Status::OK;
    }

    // L60-72: 第二段——软件编码器 fallback
    capabilityData = codeclist_->GetCapability(codecMimeType, true,
        MediaAVCodec::AVCodecCategory::AVCODEC_SOFTWARE);
    if (capabilityData != nullptr) {
        if (capabilityData->featuresMap.count(
            static_cast<int32_t>(MediaAVCodec::AVCapabilityFeature::VIDEO_WATERMARK))) {
            isWatermarkSupported = true;
        } else {
            isWatermarkSupported = false;
        }
        return Status::OK;
    }

    return Status::ERROR_UNKNOWN;
}
```

**关键证据点**:
- L50-58: 硬件优先查询 `GetCapability(mime, true, AVCODEC_HARDWARE)`
- L54: `featuresMap.count(VIDEO_WATERMARK)` — 从 CapabilityData.featuresMap 查询 VIDEO_WATERMARK 特性
- L60-72: 软件 fallback 查询 `GetCapability(mime, true, AVCODEC_SOFTWARE)`
- 硬件优先于软件——水印能力优先检查硬件编码器

---

## 七、CapabilityData 与 featuresMap 数据结构

**文件**: avcodec_info.h

```cpp
// L60-64: 特性枚举
enum class AVCapabilityFeature : int32_t {
    VIDEO_WATERMARK = 3,  // L64: 水印特性值=3
    // ...
};

// L294-309: CapabilityData 核心方法
class CapabilityData {
    bool IsFeatureSupported(AVCapabilityFeature feature);  // L299
    int32_t GetFeatureProperties(AVCapabilityFeature feature, Format &format);  // L309
    std::unordered_map<int32_t, std::vector<uint8_t>> featuresMap;  // 特性map
    // ...
};
```

**关键证据点**:
- L64: `VIDEO_WATERMARK = 3` — 特性枚举值
- `featuresMap` 是 `unordered_map<int32_t, vector<uint8_t>>`，键为 AVCapabilityFeature 枚举值

---

## 八、AVCodecList 工厂与接口

**文件**: avcodec_list.h

```cpp
// L27-35: GetCapability 纯虚接口
virtual CapabilityData *GetCapability(const std::string &mime, const bool isEncoder,
                                      const AVCodecCategory &category) = 0;

// L67-76: 工厂方法
class AVCodecListFactory {
#ifdef UNSUPPORT_CODECLIST
    static std::shared_ptr<AVCodecList> CreateAVCodecList() { return nullptr; }
#else
    static std::shared_ptr<AVCodecList> CreateAVCodecList();  // L71
#endif
};
```

**关键证据点**:
- L39: `AVCodecCategory` 枚举参数 —— `AVCODEC_HARDWARE` / `AVCODEC_SOFTWARE`
- L71: 工厂方法返回 `shared_ptr<AVCodecList>`

---

## 九、与 WaterMarkFilter 的关联

**文件**: water_mark_filter.cpp (~1001行)

CodecCapabilityAdapter 的 `IsWatermarkSupported()` 是 WaterMarkFilter 的前置能力探测：
1. WaterMarkFilter 初始化前调用 CodecCapabilityAdapter::IsWatermarkSupported() 查询是否支持水印
2. 支持则启用 WaterMarkFilter，否则跳过
3. VIDEO_WATERMARK 特性从 featuresMap 中读取

---

## 十、总结

| 维度 | 内容 |
|------|------|
| 架构位置 | Filter适配层（Layer 1），Filter基类 + AVCodecList工厂 |
| 核心功能 | GetAvailableEncoder（三路查询）+ IsWatermarkSupported（两段查询） |
| 关键成员 | `codeclist_` (shared_ptr<AVCodecList>) |
| 工厂注入 | `Init()` → `AVCodecListFactory::CreateAVCodecList()` |
| 查询顺序 | 硬件优先 → 软件fallback |
| 水印探测 | featuresMap.count(VIDEO_WATERMARK=3) |
| 关联主题 | S47/S71/S162(CodecCapability体系)、S135(WaterMarkFilter直接使用者) |
