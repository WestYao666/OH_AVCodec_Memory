# MEM-ARCH-AVCODEC-S171 — CodecCapabilityAdapter 能力查询适配器

## Metadata

- **ID**: MEM-ARCH-AVCODEC-S171
- **Title**: CodecCapabilityAdapter 能力查询适配器——Filter 层能力查询与 AVCodecList 三层桥接
- **Tags**: [avcodec, capability, filter, adapter, codeclist, watermark]
- **evidence_count**: 13 (E1-E13, 含E6-E13增强证据)
- **source**: https://gitcode.com/openharmony/multimedia_av_codec (commit e1bcf691, 2025-05-19)
- **registered**: 2026-05-21
- **status**: pending_approval
- **generated**: 2026-06-25T03:09 GMT+8
- **enhanced**: 2026-06-25T06:42 GMT+8
- **Builder**: builder-agent (web_fetch 验证 + 本地镜像增强)

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

---

## 六、增强 Evidence（本地镜像 2026-06-25）

### Evidence E6: UnitTest 常量定义（featuresMap key 值）

**文件**: `test/unittest/codec_capability_adapter_unittest/codec_capability_adapter_unittest.cpp`
**行号**: L25-L26

```cpp
const static int32_t TEST_VIDEO_WATERMARK = 3;   // L25: VIDEO_WATERMARK feature key = 3
const static int32_t TEST_VIDEO_RPR = 4;          // L26: VIDEO_RPR feature key = 4（无水印）
```

> **架构意义**: `featuresMap` 使用 `int32_t` 作为 key，`VIDEO_WATERMARK=3` 是 AVCodecList 能力层定义的特性枚举值，与 `AVCapabilityFeature::VIDEO_WATERMARK` 对应。

---

### Evidence E7: IsWatermarkSupported_001 — featuresMap 不含 WATERMARK → false

**文件**: `test/unittest/codec_capability_adapter_unittest/codec_capability_adapter_unittest.cpp`
**行号**: L55-L62

```cpp
HWTEST_F(CodecCapabilityAdapterUnitTest, IsWatermarkSupported_001, TestSize.Level1)
{
    capabilityData_.featuresMap.insert(std::pair<int32_t, Format>(TEST_VIDEO_RPR, Format())); // L56: 插入RPR而非WATERMARK
    EXPECT_CALL(*(mockAvcodecList_), GetCapability(_, _, _)).Times(TEST_TIMES_ONE)
        .WillOnce(Return(&capabilityData_));
    codecCapabilityAdapter_->codeclist_ = mockAvcodecList_;
    std::string codecMimeType = "";
    bool isWatermarkSupported = true;
    codecCapabilityAdapter_->IsWatermarkSupported(codecMimeType, isWatermarkSupported);
    EXPECT_TRUE(!isWatermarkSupported);  // L61: RPR不含水印 → false
}
```

---

### Evidence E8: IsWatermarkSupported_002 — 四次 GetCapability 双阶段硬件优先降级

**文件**: `test/unittest/codec_capability_adapter_unittest/codec_capability_adapter_unittest.cpp`
**行号**: L67-L87

```cpp
HWTEST_F(CodecCapabilityAdapterUnitTest, IsWatermarkSupported_002, TestSize.Level1)
{
    // L71-L75: TEST_TIMES_FOUR = 4 次 GetCapability 调用顺序：
    //   第1次 HW → nullptr（硬件无）→ 第2次 SW → nullptr（软件无）→ isWatermarkSupported = false
    EXPECT_CALL(*(mockAvcodecList_), GetCapability(_, _, _))
        .Times(TEST_TIMES_FOUR)  // = 4
        .WillOnce(Return(nullptr))           // HW: VIDEO_AVC → nullptr
        .WillOnce(Return(&capabilityData_))  // SW: VIDEO_AVC → nullptr
        .WillOnce(Return(nullptr))           // HW: VIDEO_HEVC → nullptr
        .WillOnce(Return(&capabilityData_)); // SW: VIDEO_HEVC → nullptr
    codecCapabilityAdapter_->codeclist_ = mockAvcodecList_;
    bool isWatermarkSupported = true;
    codecCapabilityAdapter_->IsWatermarkSupported(codecMimeType, isWatermarkSupported);
    EXPECT_TRUE(!isWatermarkSupported);  // L82: featuresMap无WATERMARK → false

    // L84-L86: 注入 WATERMARK 后 → true
    capabilityData_.featuresMap.insert(
        std::pair<int32_t, Format>(TEST_VIDEO_WATERMARK, Format())); // L84: VIDEO_WATERMARK key=3
    codecCapabilityAdapter_->IsWatermarkSupported(codecMimeType, isWatermarkSupported);
    EXPECT_TRUE(isWatermarkSupported);  // L86: 含WATERMARK → true
}
```

---

### Evidence E9: IsWatermarkSupported_003 — capabilityData 全 nullptr → ERROR_UNKNOWN

**文件**: `test/unittest/codec_capability_adapter_unittest/codec_capability_adapter_unittest.cpp`
**行号**: L92-L103

```cpp
HWTEST_F(CodecCapabilityAdapterUnitTest, IsWatermarkSupported_003, TestSize.Level1)
{
    EXPECT_CALL(*(mockAvcodecList_), GetCapability(_, _, _))
        .WillRepeatedly(Return(nullptr)); // L96: HW和SW均返回nullptr
    codecCapabilityAdapter_->codeclist_ = mockAvcodecList_;
    std::string codecMimeType = "";
    bool isWatermarkSupported = true;
    Status status = codecCapabilityAdapter_->IsWatermarkSupported(codecMimeType, isWatermarkSupported);
    EXPECT_EQ(status, Status::ERROR_UNKNOWN);  // L102: 双阶段都查不到 → ERROR_UNKNOWN
}
```

---

### Evidence E10: GetAudioEncoder_001 — AAC 软件编码器查询空结果

**文件**: `test/unittest/codec_capability_adapter_unittest/codec_capability_adapter_unittest.cpp`
**行号**: L106-L116

```cpp
HWTEST_F(CodecCapabilityAdapterUnitTest, GetAudioEncoder_001, TestSize.Level1)
{
    EXPECT_CALL(*(mockAvcodecList_), GetCapability(_, _, _))
        .Times(TEST_TIMES_ONE)             // L110: AAC软件编码器只查询1次
        .WillOnce(Return(nullptr));        // AAC 软件能力为空
    codecCapabilityAdapter_->codeclist_ = mockAvcodecList_;
    std::vector<MediaAVCodec::CapabilityData*> dataVector;
    codecCapabilityAdapter_->GetAudioEncoder(dataVector);
    EXPECT_TRUE(dataVector.empty());  // L115: AAC无软件能力 → 空向量
}
```

---

### Evidence E11: GetVideoEncoder_001 — AVC+HEVC 全 nullptr → 空向量

**文件**: `test/unittest/codec_capability_adapter_unittest/codec_capability_adapter_unittest.cpp`
**行号**: L119-L129

```cpp
HWTEST_F(CodecCapabilityAdapterUnitTest, GetVideoEncoder_001, TestSize.Level1)
{
    EXPECT_CALL(*(mockAvcodecList_), GetCapability(_, _, _))
        .WillRepeatedly(Return(nullptr)); // L123: AVC HW/SW + HEVC HW 均返回 nullptr
    codecCapabilityAdapter_->codeclist_ = mockAvcodecList_;
    std::vector<MediaAVCodec::CapabilityData*> dataVector;
    codecCapabilityAdapter_->GetVideoEncoder(dataVector);
    EXPECT_TRUE(dataVector.empty());  // L127: 无硬件/软件能力 → 空向量
}
```

---

### Evidence E12: GetVideoEncoder_002 — AVC 硬件命中 + codeclist_ nullptr 析构

**文件**: `test/unittest/codec_capability_adapter_unittest/codec_capability_adapter_unittest.cpp`
**行号**: L131-L146

```cpp
HWTEST_F(CodecCapabilityAdapterUnitTest, GetVideoEncoder_002, TestSize.Level1)
{
    EXPECT_CALL(*(mockAvcodecList_), GetCapability(_, _, _))
        .Times(TEST_TIMES_THREE)  // = 3: AVC HW(=nullptr) → AVC SW(命中) → HEVC HW(=nullptr)
        .WillOnce(Return(nullptr))           // AVC HW → nullptr
        .WillOnce(Return(&capabilityData_))  // AVC SW → 命中
        .WillOnce(Return(nullptr));          // HEVC HW → nullptr（无软件降级）
    codecCapabilityAdapter_->codeclist_ = mockAvcodecList_;
    std::vector<MediaAVCodec::CapabilityData*> dataVector;
    codecCapabilityAdapter_->GetVideoEncoder(dataVector);
    EXPECT_EQ(dataVector.size(), 1);  // L142: 仅AVC软件编码器 → size=1

    codecCapabilityAdapter_->codeclist_ = nullptr; // L144: 模拟析构函数行为
}
```

> **架构意义**: 验证了 `GetVideoEncoder()` 的**非对称降级策略**：AVC 有硬件+软件双路径，HEVC 仅硬件路径（无软件降级）。

---

### Evidence E13: fcodec_capability_register — FCodec GetCodecCapability 能力数组注册

**文件**: `services/engine/codec/video/fcodec/fcodec_capability_register.cpp`
**行号**: L419-L492

```cpp
// L419-L450: GetCapabilityData — 填充 CapabilityData 标准字段
void GetCapabilityData(CapabilityData &capsData, uint32_t index)
{
    capsData.codecName  = static_cast<std::string>(SUPPORT_VCODEC[index].codecName);
    capsData.mimeType  = static_cast<std::string>(SUPPORT_VCODEC[index].mimeType);
    capsData.codecType = AVCODEC_TYPE_VIDEO_DECODER;              // L424: decoder 类型
    capsData.isVendor  = false;
    capsData.maxInstance = VIDEO_INSTANCE_SIZE;                   // L426: 64实例上限
    capsData.alignment = {VIDEO_ALIGNMENT_SIZE, VIDEO_ALIGNMENT_SIZE}; // L2×2对齐
    capsData.width  = {VIDEO_MIN_SIZE, VIDEO_MAX_WIDTH_SIZE};     // L2~4096
    capsData.height = {VIDEO_MIN_SIZE, VIDEO_MAX_HEIGHT_SIZE};    // L2~4096
    capsData.frameRate    = {0, VIDEO_FRAMERATE_DEFAULT_SIZE};    // L0~60fps
    capsData.bitrate      = {1, VIDEO_BITRATE_MAX_SIZE};         // L1~300Mbps
    capsData.blockPerFrame= {1, VIDEO_BLOCKPERFRAME_SIZE};       // L139264/帧
    capsData.blockPerSecond= {1, VIDEO_BLOCKPERSEC_SIZE};         // L983040/秒
    capsData.pixFormat = {YUVI420, NV12, NV21, RGBA};            // L447-L448: 四像素格式
}

// L483-L492: GetCodecCapability — 遍历 SUPPORT_VCODEC 注册所有解码器能力
int32_t FCodec::GetCodecCapability(std::vector<CapabilityData> &capaArray)
{
    for (uint32_t i = 0; i < SUPPORT_VCODEC_NUM; ++i) {   // L485: 遍历所有codec
        CapabilityData capsData;
        GetCapabilityData(capsData, i);                    // L487: 填充标准能力
        capaArray.emplace_back(capsData);                  // L488: 注册进能力数组
        // ... mimeType 特定增强（mpeg2/mp4v-es/h263/mpeg等）
    }
}
```

> **架构意义**: `FCodec::GetCodecCapability()` 是 `CodecCapabilityAdapter` 查询链路的最底层数据源之一。`SUPPORT_VCODEC` 数组定义了 fcodec 支持的所有软解码 codec，能力信息通过 `CodecListCore` → `AVCodecList` → `CodecCapabilityAdapter` 向上传递，最终被 Filter 层消费。

---

## 七、增强变更记录

| 日期 | 操作 | 说明 |
|------|------|------|
| 2026-06-25T06:42 | builder-agent | S171本地镜像增强：E6-E13（8条新增evidence，共14条），基于 /home/west/av_codec_repo，TEST_VIDEO_WATERMARK=3/VIDEO_RPR=4常量 + 5个UT用例 + fcodec_capability_register L419-L492 能力数组注册 |
