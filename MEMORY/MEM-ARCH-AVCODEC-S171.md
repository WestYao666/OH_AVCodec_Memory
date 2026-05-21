---
id: MEM-ARCH-AVCODEC-S171
subject: CodecCapabilityAdapter 编解码能力查询适配器——AVCodecList工厂注入与水印能力探测
status: draft
created_at: 2026-05-21T21:00:00+08:00
evidence_count: 12
source_files:
  - services/media_engine/filters/codec_capability_adapter.cpp (113行)
  - interfaces/inner_api/native/codec_capability_adapter.h (44行)
datasource: /home/west/av_codec_repo
tags:
  - AVCodec
  - CodecCapability
  - Filter
  - Adapter
  - AVCodecList
  - Watermark
关联:
  - S47: CodecCapability能力查询与匹配机制
  - S71: CodecList服务架构
  - S162: CodecAbility/CodecListCore编解码能力查询体系
  - S135: WaterMarkFilter水印过滤器（直接使用者）
---

# S171｜CodecCapabilityAdapter 编解码能力查询适配器

## 一、定位与背景

`CodecCapabilityAdapter` 是 Filter 层与 CodecCapability 能力查询体系的桥接适配器。它封装 `AVCodecListFactory::CreateAVCodecList()` 工厂方法，提供统一的能力查询入口（Encoder查询、水印支持探测）。

## 二、源文件证据

| 文件 | 行数 | 说明 |
|------|------|------|
| `codec_capability_adapter.cpp` | 113 | Filter适配器实现 |
| `codec_capability_adapter.h` | 44 | 类定义头文件 |

### 2.1 类定义（codec_capability_adapter.h:18-35）

```cpp
class CodecCapabilityAdapter {
public:
    explicit CodecCapabilityAdapter();
    ~CodecCapabilityAdapter();

    void Init();

    Status GetAvailableEncoder(std::vector<MediaAVCodec::CapabilityData*> &encoderInfo);
    Status IsWatermarkSupported(std::string &CodecMimeType, bool &isWatermarkSupported);
private:
    Status GetVideoEncoder(std::vector<MediaAVCodec::CapabilityData*> &encoderInfo);
    Status GetAudioEncoder(std::vector<MediaAVCodec::CapabilityData*> &encoderInfo);
    std::shared_ptr<MediaAVCodec::AVCodecList> codeclist_ {nullptr};
};
```

### 2.2 Init初始化（codec_capability_adapter.cpp:34-38）

```cpp
void CodecCapabilityAdapter::Init()
{
    codeclist_ = MediaAVCodec::AVCodecListFactory::CreateAVCodecList();
    MEDIA_LOG_I("CodecCapabilityAdapter Init end");
}
```

- `AVCodecListFactory::CreateAVCodecList()` 是工厂方法，创建能力查询单例
- 持有 `codeclist_` 成员变量，`shared_ptr` 线程安全引用计数

### 2.3 GetAvailableEncoder（codec_capability_adapter.cpp:44-49）

```cpp
Status CodecCapabilityAdapter::GetAvailableEncoder(std::vector<MediaAVCodec::CapabilityData*> &encoderInfo)
{
    GetAudioEncoder(encoderInfo);
    GetVideoEncoder(encoderInfo);
    return Status::OK;
}
```

- 对外统一入口，内部调用 `GetAudioEncoder` + `GetVideoEncoder`
- 返回 `std::vector<CapabilityData*>` 指针列表

### 2.4 IsWatermarkSupported硬件优先两段查询（codec_capability_adapter.cpp:51-73）

```cpp
Status CodecCapabilityAdapter::IsWatermarkSupported(std::string &codecMimeType, bool &isWatermarkSupported)
{
    // 第一段：查询硬件编码器
    MediaAVCodec::CapabilityData *capabilityData = codeclist_->GetCapability(codecMimeType,
        true, MediaAVCodec::AVCodecCategory::AVCODEC_HARDWARE);
    if (capabilityData != nullptr) {
        if (capabilityData->featuresMap.count(
            static_cast<int32_t>(MediaAVCodec::AVCapabilityFeature::VIDEO_WATERMARK))) {
            isWatermarkSupported = true;
        } else {
            isWatermarkSupported = false;
        }
        return Status::OK;
    }

    // 第二段：查询软件编码器
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

- **硬件优先策略**：`AVCODEC_HARDWARE` 优先查，查不到再查 `AVCODEC_SOFTWARE`
- `featuresMap.count(VIDEO_WATERMARK)` 检测水印能力特性
- 双层查询逻辑：硬件有则返回，软件有也返回，都无则 `ERROR_UNKNOWN`

### 2.5 GetAudioEncoder（codec_capability_adapter.cpp:75-86）

```cpp
Status CodecCapabilityAdapter::GetAudioEncoder(std::vector<MediaAVCodec::CapabilityData*> &encoderInfo)
{
    MediaAVCodec::CapabilityData *capabilityData = codeclist_->GetCapability(
        std::string(MediaAVCodec::CodecMimeType::AUDIO_AAC), true,
        MediaAVCodec::AVCodecCategory::AVCODEC_SOFTWARE);
    if (capabilityData != nullptr) {
        encoderInfo.push_back(capabilityData);
    }
    return Status::OK;
}
```

- 仅查询 `AUDIO_AAC` 软件编码器能力
- 返回 AAC 能力数据指针

### 2.6 GetVideoEncoder三路查询（codec_capability_adapter.cpp:88-113）

```cpp
Status CodecCapabilityAdapter::GetVideoEncoder(std::vector<MediaAVCodec::CapabilityData*> &encoderInfo)
{
    // 第一路：AVC 硬件编码器
    MediaAVCodec::CapabilityData *capabilityDataAVC = codeclist_->GetCapability(
        std::string(MediaAVCodec::CodecMimeType::VIDEO_AVC), true,
        MediaAVCodec::AVCodecCategory::AVCODEC_HARDWARE);
    if (capabilityDataAVC != nullptr) {
        encoderInfo.push_back(capabilityDataAVC);
    } else {
        // 降级：AVC 软件编码器
        MediaAVCodec::CapabilityData *capabilityDataAVCSoft = codeclist_->GetCapability(
            std::string(MediaAVCodec::CodecMimeType::VIDEO_AVC), true,
            MediaAVCodec::AVCodecCategory::AVCODEC_SOFTWARE);
        if (capabilityDataAVCSoft != nullptr) {
            encoderInfo.push_back(capabilityDataAVCSoft);
        }
    }

    // 第二路：HEVC 硬件编码器
    MediaAVCodec::CapabilityData *capabilityDataHEVC = codeclist_->GetCapability(
        std::string(MediaAVCodec::CodecMimeType::VIDEO_HEVC), true,
        MediaAVCodec::AVCodecCategory::AVCODEC_HARDWARE);
    if (capabilityDataHEVC != nullptr) {
        encoderInfo.push_back(capabilityDataHEVC);
    }
    return Status::OK;
}
```

- **AVC 编码器**：硬件优先，硬件无则降级查软件
- **HEVC 编码器**：仅查硬件，无软件降级
- 最终返回 AVC（硬件或软件）+ HEVC（硬件）共 1-2 个能力数据

## 三、关键设计总结

| 设计点 | 实现 |
|--------|------|
| 工厂模式 | `AVCodecListFactory::CreateAVCodecList()` |
| 硬件优先 | `AVCODEC_HARDWARE` 先于 `AVCODEC_SOFTWARE` 查询 |
| 特性探测 | `featuresMap.count(VIDEO_WATERMARK)` |
| 三路Encoder | AAC(软)、AVC(硬→软降级)、HEVC(硬) |
| 生命周期 | 析构时 `codeclist_ = nullptr`（shared_ptr自动释放） |

## 四、关联

- **S47/S71/S162**：CodecCapability能力查询体系，`AVCodecList` 是核心组件
- **S135**：WaterMarkFilter 直接使用 `CodecCapabilityAdapter::IsWatermarkSupported` 查询水印能力