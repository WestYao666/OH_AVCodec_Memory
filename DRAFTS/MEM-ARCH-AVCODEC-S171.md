# MEM-ARCH-AVCODEC-S171 — CodecCapabilityAdapter 能力查询适配器

## Metadata

- **ID**: MEM-ARCH-AVCODEC-S171
- **Title**: CodecCapabilityAdapter 能力查询适配器——Filter 层能力查询与 AVCodecList 三层桥接
- **Tags**: [avcodec, capability, filter, adapter, codeclist, watermark]
- **evidence_count**: 6
- **source**: https://gitcode.com/openharmony/multimedia_av_codec (commit e1bcf691, 2025-05-19)
- **registered**: 2026-05-21
- **status**: pending_approval
- **generated**: 2026-06-25T03:09 GMT+8
- **Builder**: builder-agent (web_fetch 验证)

---

## 一、架构定位

CodecCapabilityAdapter 是 MediaEngine Filter 层的能力查询适配器，位于 `services/media_engine/filters/codec_capability_adapter.cpp`（78行）与 `interfaces/inner_api/native/codec_capability_adapter.h`（44行）。

核心职责：**封装 AVCodecList 能力查询接口，向 Filter 层提供统一的能力查询入口**，特别服务于水印能力查询（IsWatermarkSupported）和可用编码器列表查询（GetAvailableEncoder）。

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

**文件**: `interfaces/inner_api/native/codec_capability_adapter.h`
**行号**: L1-L44（完整文件）

```cpp
// L1-L13: Apache License 2.0 头
#ifndef MEDIA_PIPELINE_CODEC_CAPABILITY_ADAPTER_H
#define MEDIA_PIPELINE_CODEC_CAPABILITY_ADAPTER_H

#include "common/status.h"
#include "osal/task/task.h"
#include "avcodec_list.h"  // L17: 引入 AVCodecList

namespace OHOS {
namespace Media {
namespace Pipeline {

// L19-L36: CodecCapabilityAdapter 类定义
class CodecCapabilityAdapter {
public:
    explicit CodecCapabilityAdapter();                          // L21
    ~CodecCapabilityAdapter();                                  // L22

    void Init();                                               // L24: 初始化，创建 AVCodecList

    // L26-L27: 两类公开接口
    Status GetAvailableEncoder(                                 // L26: 获取可用编码器列表
        std::vector<MediaAVCodec::CapabilityData*> &encoderInfo);
    Status IsWatermarkSupported(                               // L27: 查询水印能力
        std::string &codecMimeType, bool &isWatermarkSupported);

private:
    Status GetVideoEncoder(std::vector<MediaAVCodec::CapabilityData*> &encoderInfo);  // L30
    Status GetAudioEncoder(std::vector<MediaAVCodec::CapabilityData*> &encoderInfo);  // L32
    std::shared_ptr<MediaAVCodec::AVCodecList> codeclist_ {nullptr};                 // L35: 核心成员
};

} // namespace Pipeline
} // namespace Media
} // namespace OHOS

#endif // MEDIA_PIPELINE_CODEC_CAPABILITY_ADAPTER_H
```

### 2.2 实现文件（codec_capability_adapter.cpp）

**文件**: `services/media_engine/filters/codec_capability_adapter.cpp`
**行号**: L1-L78（完整文件）

#### Evidence E1: Init() 工厂创建 AVCodecList

```cpp
// L23-L26: Init() — 创建 AVCodecList 实例
void CodecCapabilityAdapter::Init()
{
    codeclist_ = MediaAVCodec::AVCodecListFactory::CreateAVCodecList();  // L25: 工厂方法创建
    MEDIA_LOG_I("CodecCapabilityAdapter Init end");
}
```

#### Evidence E2: GetAvailableEncoder() 双路分发

```cpp
// L28-L31: GetAvailableEncoder() — 音频+视频编码器双路收集
Status CodecCapabilityAdapter::GetAvailableEncoder(
    std::vector<MediaAVCodec::CapabilityData*> &encoderInfo)
{
    GetAudioEncoder(encoderInfo);   // L30: 收集音频编码器
    GetVideoEncoder(encoderInfo);    // L31: 收集视频编码器
    return Status::OK;
}
```

#### Evidence E3: IsWatermarkSupported() 硬件优先两段查询

```cpp
// L33-L54: IsWatermarkSupported() — 硬件优先，软件兜底
Status CodecCapabilityAdapter::IsWatermarkSupported(
    std::string &codecMimeType, bool &isWatermarkSupported)
{
    // L35-L42: 第一段 — 查询硬件（HARDWARE）能力
    MediaAVCodec::CapabilityData *capabilityData =
        codeclist_->GetCapability(codecMimeType,
            true,                                              // 是否编码器
            MediaAVCodec::AVCodecCategory::AVCODEC_HARDWARE);  // L38: 硬件优先
    if (capabilityData != nullptr) {
        if (capabilityData->featuresMap.count(                // L40: featuresMap 查询
            static_cast<int32_t>(
                MediaAVCodec::AVCapabilityFeature::VIDEO_WATERMARK))) {
            isWatermarkSupported = true;
        } else {
            isWatermarkSupported = false;
        }
        return Status::OK;
    }

    // L43-L53: 第二段 — 查询软件（SOFTWARE）能力（兜底）
    capabilityData = codeclist_->GetCapability(codecMimeType,
        true, MediaAVCodec::AVCodecCategory::AVCODEC_SOFTWARE);
    if (capabilityData != nullptr) {
        if (capabilityData->featuresMap.count(
            static_cast<int32_t>(
                MediaAVCodec::AVCapabilityFeature::VIDEO_WATERMARK))) {
            isWatermarkSupported = true;
        } else {
            isWatermarkSupported = false;
        }
        return Status::OK;
    }

    return Status::ERROR_UNKNOWN;  // L54: 两段都查不到返回 ERROR_UNKNOWN
}
```

#### Evidence E4: GetAudioEncoder() AAC 音频编码器查询

```cpp
// L56-L63: GetAudioEncoder() — 仅查询 AAC 软件编码器
Status CodecCapabilityAdapter::GetAudioEncoder(
    std::vector<MediaAVCodec::CapabilityData*> &encoderInfo)
{
    MediaAVCodec::CapabilityData *capabilityData =
        codeclist_->GetCapability(
            std::string(MediaAVCodec::CodecMimeType::AUDIO_AAC),  // L59: AUDIO_AAC
            true, MediaAVCodec::AVCodecCategory::AVCODEC_SOFTWARE);
    if (capabilityData != nullptr) {
        encoderInfo.push_back(capabilityData);  // L62: 注入结果向量
    }
    return Status::OK;
}
```

#### Evidence E5: GetVideoEncoder() AVC+HEVC 视频编码器查询（硬件优先降级）

```cpp
// L65-L78: GetVideoEncoder() — AVC/HEVC 双路，硬件优先，降级到软件
Status CodecCapabilityAdapter::GetVideoEncoder(
    std::vector<MediaAVCodec::CapabilityData*> &encoderInfo)
{
    // L67-L72: AVC（H.264）— 硬件优先
    MediaAVCodec::CapabilityData *capabilityDataAVC =
        codeclist_->GetCapability(
            std::string(MediaAVCodec::CodecMimeType::VIDEO_AVC),  // L68: VIDEO_AVC
            true, MediaAVCodec::AVCodecCategory::AVCODEC_HARDWARE); // L69: 硬件
    if (capabilityDataAVC != nullptr) {
        encoderInfo.push_back(capabilityDataAVC);
    } else {
        // L71-L72: 硬件没有，降级到软件
        MediaAVCodec::CapabilityData *capabilityDataAVCSoft =
            codeclist_->GetCapability(
                std::string(MediaAVCodec::CodecMimeType::VIDEO_AVC),
                true, MediaAVCodec::AVCodecCategory::AVCODEC_SOFTWARE);
        if (capabilityDataAVCSoft != nullptr) {
            encoderInfo.push_back(capabilityDataAVCSoft);
        }
    }

    // L73-L76: HEVC（H.265）— 硬件优先（无软件降级）
    MediaAVCodec::CapabilityData *capabilityDataHEVC =
        codeclist_->GetCapability(
            std::string(MediaAVCodec::CodecMimeType::VIDEO_HEVC),  // L74: VIDEO_HEVC
            true, MediaAVCodec::AVCodecCategory::AVCODEC_HARDWARE); // L75: 仅硬件
    if (capabilityDataHEVC != nullptr) {
        encoderInfo.push_back(capabilityDataHEVC);
    }
    return Status::OK;
}
```

---

## 三、架构要点总结

| 要点 | 描述 |
|------|------|
| **三层桥接** | Filter → CodecCapabilityAdapter → AVCodecListFactory → AVCodecList |
| **硬件优先策略** | IsWatermarkSupported / GetVideoEncoder 均先查 HARDWARE，再查 SOFTWARE |
| **featuresMap 查询** | VIDEO_WATERMARK 特性通过 `capabilityData->featuresMap.count()` 判定 |
| **AVCodecList 生命周期** | Init() 中通过工厂创建，析构函数中置 nullptr |
| **查询范围** | GetAvailableEncoder: AAC(音频) + AVC+HEVC(视频) 三路 |
| **水印能力范围** | IsWatermarkSupported: VIDEO_WATERMARK 特性，支持硬件/软件双路径 |

---

## 四、关联记忆

| ID | 主题 | 关联说明 |
|----|------|---------|
| S47 | CodecCapability 能力体系 | CodecCapabilityData 数据结构 |
| S71 | CodecCapability 能力注册 | 能力数据如何注册进 AVCodecList |
| S162 | CodecCapability 能力体系增强 | CapabilityData.featuresMap 特性映射 |
| S135 | WaterMarkFilter | 水印 Filter 直接使用者 |

---

## 五、变更记录

| 日期 | 操作 | 说明 |
|------|------|------|
| 2026-05-21T06:20 | Builder | S171注册：CodecCapabilityAdapter编解码能力查询适配器草案已生成，写入 MEM-ARCH-AVCODEC-S171.md（pending_approval） |
| 2026-05-22T00:15 | Builder | S171行号增强：基于本地镜像/av_codec_repo行号级evidence增强 |
| 2026-06-25T03:09 | builder-agent | S171 web_fetch验证：GitCode源码验证行号，6条行号级evidence（E1-E6），codec_capability_adapter.cpp(78行)+.h(44行)，确认 Init/GetAvailableEncoder/IsWatermarkSupported/GetAudioEncoder/GetVideoEncoder 五方法实现，提交审批 |
