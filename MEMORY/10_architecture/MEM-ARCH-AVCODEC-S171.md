# MEM-ARCH-AVCODEC-S171

**主题**：CodecCapabilityAdapter 编解码能力查询适配器——AVCodecList工厂注入与水印能力探测

**状态**：pending_approval

**日期**：2026-05-21

---

## 一、架构定位

`CodecCapabilityAdapter` 是 MediaEngine Filter 层中的能力查询适配器，位于 `services/media_engine/filters/codec_capability_adapter.cpp`（113行）和 `interfaces/inner_api/native/codec_capability_adapter.h`。它负责将 AVCodecList 的能力查询接口暴露给 Filter 管线系统，主要服务于水印过滤器（WaterMarkFilter）的硬件能力探测需求。

Filter 层位置：`services/media_engine/filters/`（与 audio_capture_filter.cpp、audio_decoder_adapter.cpp 等并列）

---

## 二、关键源码结构

### 2.1 类定义（codec_capability_adapter.h）

```cpp
class CodecCapabilityAdapter {
public:
    explicit CodecCapabilityAdapter();
    ~CodecCapabilityAdapter();
    void Init();
    Status GetAvailableEncoder(std::vector<MediaAVCodec::CapabilityData*> &encoderInfo);
    Status IsWatermarkSupported(std::string &codecMimeType, bool &isWatermarkSupported);
private:
    Status GetVideoEncoder(std::vector<MediaAVCodec::CapabilityData*> &encoderInfo);
    Status GetAudioEncoder(std::vector<MediaAVCodec::CapabilityData*> &encoderInfo);
    std::shared_ptr<MediaAVCodec::AVCodecList> codeclist_ {nullptr};
};
```

**关键成员**：
- `codeclist_`：持有 `AVCodecList` 单例的共享指针，通过 `AVCodecListFactory::CreateAVCodecList()` 创建（L45）
- `GetAvailableEncoder`：对外统一入口，调用 GetAudioEncoder + GetVideoEncoder
- `IsWatermarkSupported`：查询指定 MIME 类型是否支持 VIDEO_WATERMARK 功能

### 2.2 Init 初始化（codec_capability_adapter.cpp:44）

```cpp
void CodecCapabilityAdapter::Init()
{
    codeclist_ = MediaAVCodec::AVCodecListFactory::CreateAVCodecList();
    MEDIA_LOG_I("CodecCapabilityAdapter Init end");
}
```

- 通过工厂模式创建 AVCodecList 实例
- 延迟初始化（在 WaterMarkFilter 需要时 Init，非构造时）

### 2.3 水印能力查询（codec_capability_adapter.cpp:51-79）

```cpp
Status CodecCapabilityAdapter::IsWatermarkSupported(std::string &codecMimeType, bool &isWatermarkSupported)
{
    // 先查硬件编码器
    MediaAVCodec::CapabilityData *capabilityData = codeclist_->GetCapability(
        codecMimeType, true, MediaAVCodec::AVCodecCategory::AVCODEC_HARDWARE);
    if (capabilityData != nullptr) {
        if (capabilityData->featuresMap.count(
            static_cast<int32_t>(MediaAVCodec::AVCapabilityFeature::VIDEO_WATERMARK))) {
            isWatermarkSupported = true;
        } else {
            isWatermarkSupported = false;
        }
        return Status::OK;
    }
    // 再查软件编码器作为 fallback
    capabilityData = codeclist_->GetCapability(
        codecMimeType, true, MediaAVCodec::AVCodecCategory::AVCODEC_SOFTWARE);
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

**查询策略**：
1. 先查询硬件编码器（AVCODEC_HARDWARE）
2. Hardware 不存在或不支持时，fallback 到软件编码器（AVCODEC_SOFTWARE）
3. 均不存在返回 `ERROR_UNKNOWN`

### 2.4 音视频编码器查询（codec_capability_adapter.cpp:80-107）

```cpp
Status CodecCapabilityAdapter::GetAudioEncoder(std::vector<MediaAVCodec::CapabilityData*> &encoderInfo)
{
    // 只查询 AAC 软件编码器能力
    MediaAVCodec::CapabilityData *capabilityData = codeclist_->GetCapability(
        std::string(MediaAVCodec::CodecMimeType::AUDIO_AAC),
        true, MediaAVCodec::AVCodecCategory::AVCODEC_SOFTWARE);
    if (capabilityData != nullptr) {
        encoderInfo.push_back(capabilityData);
    }
    return Status::OK;
}

Status CodecCapabilityAdapter::GetVideoEncoder(std::vector<MediaAVCodec::CapabilityData*> &encoderInfo)
{
    // 查询 AVC 硬件，若无则 fallback 软件
    MediaAVCodec::CapabilityData *capabilityDataAVC = codeclist_->GetCapability(
        std::string(MediaAVCodec::CodecMimeType::VIDEO_AVC),
        true, MediaAVCodec::AVCodecCategory::AVCODEC_HARDWARE);
    if (capabilityDataAVC != nullptr) {
        encoderInfo.push_back(capabilityDataAVC);
    } else {
        MediaAVCodec::CapabilityData *capabilityDataAVCSoft = codeclist_->GetCapability(
            std::string(MediaAVCodec::CodecMimeType::VIDEO_AVC),
            true, MediaAVCodec::AVCodecCategory::AVCODEC_SOFTWARE);
        if (capabilityDataAVCSoft != nullptr) {
            encoderInfo.push_back(capabilityDataAVCSoft);
        }
    }
    // 查询 HEVC 硬件编码器
    MediaAVCodec::CapabilityData *capabilityDataHEVC = codeclist_->GetCapability(
        std::string(MediaAVCodec::CodecMimeType::VIDEO_HEVC),
        true, MediaAVCodec::AVCodecCategory::AVCODEC_HARDWARE);
    if (capabilityDataHEVC != nullptr) {
        encoderInfo.push_back(capabilityDataHEVC);
    }
    return Status::OK;
}
```

---

## 三、能力查询接口体系

### 3.1 AVCodecList 工厂创建

- `AVCodecListFactory::CreateAVCodecList()` 是全局单例工厂
- 返回 `std::shared_ptr<MediaAVCodec::AVCodecList>`
- 由 `codeclist_` 持有，析构时自动释放（引用计数归零时销毁）

### 3.2 GetCapability 三参数查询

```cpp
codeclist_->GetCapability(mime, isEncoder, category);
```

- `mime`：MIME 类型字符串（如 "video/avc", "audio/aac"）
- `isEncoder`：true=查询编码器，false=查询解码器
- `category`：`AVCodecCategory::AVCODEC_HARDWARE` 或 `AVCODEC_SOFTWARE`
- 返回 `CapabilityData*` 指针，外部不持有生命周期

### 3.3 featuresMap 特性探测

```cpp
capabilityData->featuresMap.count(
    static_cast<int32_t>(MediaAVCodec::AVCapabilityFeature::VIDEO_WATERMARK))
```

- `featuresMap` 是 `std::map<int, int>` 类型（特性枚举→存在标记）
- 通过 count() 检查特性是否存在

---

## 四、在 Filter Pipeline 中的角色

### 4.1 被 WaterMarkFilter 调用

`CodecCapabilityAdapter` 主要服务于 `WaterMarkFilter`（services/media_engine/filters/water_mark_filter.cpp, 1001行），用于：
- 判断当前编码器是否支持视频水印叠加
- 在不支持时跳过水印处理或 fallback 到软件编码路径

### 4.2 与 S47/S71/S162 CodecCapability 的关系

| 对比项 | S47 | S71 | S162 | S171 |
|--------|-----|-----|------|------|
| 层级 | CapabilityData 结构体 | CodecListServer SA 服务 | CodecListCore 查询引擎 | Filter 适配层 |
| 范围 | 能力数据结构 | 跨进程 SA 查询 | 查询逻辑层 | Filter 查询入口 |
| 与 Pipeline 关系 | 底层数据结构 | SA 服务端 | 查询引擎 | Filter→CodecListAdapter |

---

## 五、证据摘要

| 文件 | 行数 | 关键内容 |
|------|------|---------|
| codec_capability_adapter.cpp | 113 | 主实现：Init/IsWatermarkSupported/GetAudioEncoder/GetVideoEncoder |
| codec_capability_adapter.h | 60 | 类定义：codeclist_成员、5个公开接口、2个私有接口 |
| interfaces/inner_api/native/ | - | 头文件路径，与 S84/S162 同目录 |

---

## 六、关联主题

- **S47**：CodecCapability 能力查询与匹配机制（五层能力体系）
- **S71**：CodecList 服务架构——CodecListServer SA 三层
- **S162**：CodecAbility/CodecListCore 编解码能力查询体系
- **S135**：WaterMarkFilter 水印过滤器（直接使用者）
- **S83**：AVCodec Native C API 架构（AVCodecListFactory 来源）

---

**_builder**：west @ 2026-05-21T06:20