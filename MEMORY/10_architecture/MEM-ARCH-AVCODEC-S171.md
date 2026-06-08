---
id: MEM-ARCH-AVCODEC-S171
type: architecture
status: draft
subject: "CodecCapabilityAdapter 能力查询适配器——CodecList工厂+GetAvailableEncoder双层分发+水印能力探测"
scope: "AVCodec, MediaEngine, Filter, Capability, AVCodecList, CodecCapability, VideoEncoder, AudioEncoder, Watermark"
evidence_count: 10
source_files:
  - "/home/west/av_codec_repo/services/media_engine/filters/codec_capability_adapter.cpp (113行)"
  - "/home/west/av_codec_repo/interfaces/inner_api/native/codec_capability_adapter.h (44行)"
  - "/home/west/av_codec_repo/test/unittest/codec_capability_adapter_unittest/codec_capability_adapter_unittest.cpp (159行)"
关联记忆:
  - S162 (CodecAbility/CodecListCore能力查询体系)
  - S83/S94 (Native C API能力查询)
  - S47 (CodecCapability五层能力模型)
  - S70 (VideoCodecLoader插件体系)
---

# S171 CodecCapabilityAdapter 能力查询适配器

## 1. 架构概述

CodecCapabilityAdapter 是 MediaEngine Filter 层与 AVCodecList 能力查询系统之间的**适配器桥接类**，位于 `services/media_engine/filters/` 目录。自身不维护能力数据，仅委托 `AVCodecList` 单例查询硬件/软件编解码器能力，主要服务于水印功能探测和可用编码器列表查询两个场景。

```
CodecCapabilityAdapter（Pipeline命名空间，113行cpp）
    ├── Init()                              — AVCodecListFactory::CreateAVCodecList() 创建codeclist_
    ├── GetAvailableEncoder() — 驱动GetAudioEncoder+GetVideoEncoder双分发
    ├── GetVideoEncoder()                   — 优先查硬件AVC(HARDWARE)→回退软件AVC→查询硬件HEVC
    ├── GetAudioEncoder()                   — 仅查软件AAC
    └── IsWatermarkSupported()              — 先查硬件codec→再查软件codec，featuresMap特征探测
```

---

## 2. 核心文件定位

| 文件 | 行数 | 角色 |
|------|------|------|
| `codec_capability_adapter.cpp` | 113 | 实现层 |
| `codec_capability_adapter.h` | 44 | 接口声明，Pipeline命名空间 |
| `codec_capability_adapter_unittest.cpp` | 159 | 单元测试 |

---

## 3. 关键方法分析

### 3.1 Init()

E1: `codec_capability_adapter.cpp L37-40` — Init() 通过工厂方法创建 AVCodecList 单例：

```cpp
void CodecCapabilityAdapter::Init()
{
    codeclist_ = MediaAVCodec::AVCodecListFactory::CreateAVCodecList(); // E1: 创建能力查询单例
    MEDIA_LOG_I("CodecCapabilityAdapter Init end");
}
```

### 3.2 GetAvailableEncoder()

E2: `codec_capability_adapter.cpp L42-46` — GetAvailableEncoder 顺序调用音频和视频编码器查询：

```cpp
Status CodecCapabilityAdapter::GetAvailableEncoder(
    std::vector<MediaAVCodec::CapabilityData*> &encoderInfo)
{
    GetAudioEncoder(encoderInfo);   // E2: 先查音频
    GetVideoEncoder(encoderInfo);   // E2: 再查视频
    return Status::OK;
}
```

### 3.3 GetVideoEncoder() — 硬件优先回退逻辑

E3: `codec_capability_adapter.cpp L70-90` — 视频编码器查询优先硬件 AVC，回退软件 AVC，再查硬件 HEVC：

```cpp
Status CodecCapabilityAdapter::GetVideoEncoder(
    std::vector<MediaAVCodec::CapabilityData*> &encoderInfo)
{
    // E3: 优先查硬件AVC编码器
    MediaAVCodec::CapabilityData *capabilityDataAVC = codeclist_->GetCapability(
        std::string(MediaAVCodec::CodecMimeType::VIDEO_AVC),
        true, MediaAVCodec::AVCodecCategory::AVCODEC_HARDWARE);
    if (capabilityDataAVC != nullptr) {
        encoderInfo.push_back(capabilityDataAVC);
    } else {
        // E3: 硬件不存在则回退到软件AVC
        MediaAVCodec::CapabilityData *capabilityDataAVCSoft = codeclist_->GetCapability(
            std::string(MediaAVCodec::CodecMimeType::VIDEO_AVC), true,
            MediaAVCodec::AVCodecCategory::AVCODEC_SOFTWARE);
        if (capabilityDataAVCSoft != nullptr) {
            encoderInfo.push_back(capabilityDataAVCSoft);
        }
    }

    // E3: 额外查询硬件HEVC编码器
    MediaAVCodec::CapabilityData *capabilityDataHEVC = codeclist_->GetCapability(
        std::string(MediaAVCodec::CodecMimeType::VIDEO_HEVC), true,
        MediaAVCodec::AVCodecCategory::AVCODEC_HARDWARE);
    if (capabilityDataHEVC != nullptr) {
        encoderInfo.push_back(capabilityDataHEVC);
    }
    return Status::OK;
}
```

### 3.4 GetAudioEncoder()

E4: `codec_capability_adapter.cpp L63-68` — 音频编码器仅查询软件 AAC（无硬件优先逻辑）：

```cpp
Status CodecCapabilityAdapter::GetAudioEncoder(
    std::vector<MediaAVCodec::CapabilityData*> &encoderInfo)
{
    MediaAVCodec::CapabilityData *capabilityData = codeclist_->GetCapability(
        std::string(MediaAVCodec::CodecMimeType::AUDIO_AAC),
        true, MediaAVCodec::AVCodecCategory::AVCODEC_SOFTWARE);
    if (capabilityData != nullptr) {
        encoderInfo.push_back(capabilityData);
    }
    return Status::OK;
}
```

### 3.5 IsWatermarkSupported() — 水印能力探测

E5: `codec_capability_adapter.cpp L48-62` — 先查硬件，再查软件，通过 featuresMap 计数 VIDEO_WATERMARK 特征：

```cpp
Status CodecCapabilityAdapter::IsWatermarkSupported(
    std::string &codecMimeType, bool &isWatermarkSupported)
{
    // E5: 优先查硬件codec的水印能力
    MediaAVCodec::CapabilityData *capabilityData =
        codeclist_->GetCapability(codecMimeType, true,
            MediaAVCodec::AVCodecCategory::AVCODEC_HARDWARE);
    if (capabilityData != nullptr) {
        if (capabilityData->featuresMap.count( // E5: featuresMap计数判有水印
            static_cast<int32_t>(MediaAVCodec::AVCapabilityFeature::VIDEO_WATERMARK))) {
            isWatermarkSupported = true;
        } else {
            isWatermarkSupported = false;
        }
        return Status::OK;
    }

    // E5: 硬件未命中则回退查软件codec
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
    return Status::ERROR_UNKNOWN; // E5: 两者都查不到返回ERROR_UNKNOWN
}
```

---

## 4. 设计模式分析

### 4.1 工厂 + 单例模式

E1: `codec_capability_adapter.cpp L39` — CodecCapabilityAdapter 通过 `AVCodecListFactory::CreateAVCodecList()` 获取 AVCodecList 实例（实际为单例），而非自行构造。codeclist_ 以 `shared_ptr<MediaAVCodec::AVCodecList>` 管理生命周期。

### 4.2 硬件优先回退策略

E3/E5: GetVideoEncoder 和 IsWatermarkSupported 均遵循"硬件优先，失败回退软件"的双层查询策略：
- HARDWARE → SOFTARE 两层递进
- 每层通过 `GetCapability(mime, isEncoder, category)` 查询

### 4.3 能力特征探测

E5: IsWatermarkSupported 通过 `CapabilityData.featuresMap.count(VIDEO_WATERMARK)` 而非布尔标志判断水印支持，featuresMap 是 `std::map<int32_t, Format>` 结构，支持运行时扩展特征。

---

## 5. 与 CodecList/CodecAbility体系的关系

| 对比维度 | CodecCapabilityAdapter | CodecAbility/CodecListCore |
|---------|----------------------|--------------------------|
| 命名空间 | Pipeline | MediaAVCodec |
| 查询范围 | 仅限 AVC/HEVC/AAC 三种 MIME | 全部67+ MIME 类型 |
| 返回类型 | CapabilityData* 指针 | CapabilityData 结构体 |
| 典型场景 | 水印探测/可用编码器列表 | Native C API(OH_AVCapability) |
| 层级 | Filter → CodecListAdapter | CodecListCore → CodecAbilitySingleton |

---

## 6. 单元测试关键用例

E6: `codec_capability_adapter_unittest.cpp L69-82` — IsWatermarkSupported_002 测试两次硬件查空后回退软件命中：

```cpp
HWTEST_F(CodecCapabilityAdapterUnitTest, IsWatermarkSupported_002, TestSize.Level1)
{
    // E6: Times(4) = HW_null + HW_hit + SW_null + SW_hit
    EXPECT_CALL(*(mockAvcodecList_), GetCapability(_, _, _))
        .Times(TEST_TIMES_FOUR)
        .WillOnce(Return(nullptr))        //硬件第一次返回空
        .WillOnce(Return(&capabilityData_)) // 硬件第二次返回空
        .WillOnce(Return(nullptr))        // 软件第一次返回空
        .WillOnce(Return(&capabilityData_)); // 软件第二次命中
    codecCapabilityAdapter_->IsWatermarkSupported(codecMimeType, isWatermarkSupported);
    EXPECT_TRUE(!isWatermarkSupported);
}
```

E7: `codec_capability_adapter_unittest.cpp L53-68` — IsWatermarkSupported_001 测试 featuresMap 中无 VIDEO_WATERMARK 键时返回 false：

```cpp
HWTEST_F(CodecCapabilityAdapterUnitTest, IsWatermarkSupported_001, TestSize.Level1)
{
    capabilityData_.featuresMap.insert(std::pair<int32_t, Format>(TEST_VIDEO_RPR, Format()));
    // E7: featuresMap中没有VIDEO_WATERMARK只有VIDEO_RPR，返回false
    EXPECT_CALL(*(mockAvcodecList_), GetCapability(_, _, _)).Times(1).WillOnce(Return(&capabilityData_));
    codecCapabilityAdapter_->IsWatermarkSupported(codecMimeType, isWatermarkSupported);
    EXPECT_TRUE(!isWatermarkSupported);
}
```

---

## 7. 关键发现

1. **独立无依赖**：CodecCapabilityAdapter 仅在 media_engine/filters/ 下定义，无其他 Filter 直接调用它，说明它是中间层工具类，非 Filter Pipeline 节点
2. **查询范围受限**：GetVideoEncoder 仅覆盖 AVC+HEVC，GetAudioEncoder 仅覆盖 AAC，不支持其他视频编码器（VP8/VP9/AV1）
3. **水印特化**：IsWatermarkSupported 是最完整的 capability 查询方法，体现了 OpenHarmony 水印功能对编解码器能力的特定要求
4. **TEST_VIDEO_WATERMARK=3 / TEST_VIDEO_RPR=4**：单元测试中 VIDEO_WATERMARK 和 VIDEO_RPR 是两个独立的 AVCapabilityFeature 枚举值

---

## 8. 关联索引

- **S162** CodecAbility/CodecListCore：AVCodecList 底层能力查询引擎
- **S47** CodecCapability五层能力模型：CapabilityData.featuresMap 结构说明
- **S83** AVCodec Native C API：OH_AVCapability 能力查询入口
- **S135** WaterMarkFilter：水印过滤器使用 CodecCapabilityAdapter::IsWatermarkSupported