---
status: pending_approval
---

# MEM-ARCH-AVCODEC-S71: CodecList 服务架构

> **ID**: MEM-ARCH-AVCODEC-S71
> **Title**: CodecList 服务架构——三层能力查询体系（CodecListServer / CodecListCore / CodecAbilitySingleton）
> **Type**: architecture
> **Scope**: AVCodec, CodecList, Capability, SA, IPC, Singleton
> **Status**: draft
> **Created**: 2026-05-02T21:03:00+08:00
> **Tags**: AVCodec, CodecList, Capability, CodecAbility, SA, IPC, Singleton, FindDecoder, FindEncoder, GetCapability, CodecMimeType

---

## 核心架构描述（中文）

AVCodec CodecList 服务是 OpenHarmony 多媒体编解码模块的能力查询中枢，负责回答"设备支持哪些 Codec"这一核心问题。

### 三层架构

```
┌─────────────────────────────────────────────────────────────┐
│                    CodecListServer                           │
│  services/services/codeclist/server/codeclist_server.cpp     │
│  └─ SystemAbility（SA）生命周期管理                          │
│  └─ 持有 CodecListCore 单例                                 │
└────────────────────┬────────────────────────────────────────┘
                     │ IPC（跨进程）
┌────────────────────▼────────────────────────────────────────┐
│                    CodecListCore                             │
│  services/engine/codeclist/codeclist_core.cpp               │
│  └─ FindCodec(format, isEncoder) 能力匹配引擎               │
│  └─ 七项 Check 校验（分辨率/像素格式/帧率/码率/通道/采样率） │
│  └─ mimeCapIdxMap MIME→能力索引映射                         │
└────────────────────┬────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────────┐
│               CodecAbilitySingleton                          │
│  services/engine/codeclist/codec_ability_singleton.cpp      │
│  └─ 单例模式，全局唯一                                        │
│  └─ RegisterCapabilityArray() 插件注册能力                   │
│  └─ capabilityDataArray_ 向量存储所有 CapabilityData         │
│  └─ mimeCapIdxMap_ MIME到索引的倒排索引                     │
│  └─ nameCodecTypeMap_ Codec名称→CodecType 映射             │
└─────────────────────────────────────────────────────────────┘
```

### 关键调用链

**FindDecoder / FindEncoder**:
```
CodecListClient::FindDecoder(format)
  → IPC CodecListServiceProxy
    → CodecListServer::FindDecoder(format)
      → CodecListCore::FindCodec(format, false)
        → CodecAbilitySingleton::GetInstance()
        → GetMimeCapIdxMap() / GetCapabilityArray()
        → 遍历 mimeCapIdxMap[mime] 索引
        → IsVideoCapSupport() / IsAudioCapSupport() 七项 Check
        → 返回匹配的 codecName
```

**GetCapability**:
```
CodecListClient::GetCapability(capabilityData, mime, isEncoder, category)
  → CodecListServer::GetCapability()
    → CodecListCore::GetCapability()
      → CodecAbilitySingleton::GetCapabilityArray()[index]
      → 按 category 过滤硬件/软件 codec
        → 返回 CapabilityData
```

### MIME 类型体系（CodecListCore.cpp）

支持 **20 种视频 MIME** + **47 种音频 MIME**，共计 67 种 MIME 类型：

```cpp
// 视频 MIME（codeclist_core.cpp:32-54）
VIDEO_AVC, VIDEO_HEVC, VIDEO_VVC, VIDEO_MPEG2, VIDEO_H263,
VIDEO_MPEG4, VIDEO_RV30, VIDEO_RV40, VIDEO_MJPEG, VIDEO_VP8,
VIDEO_VP9, VIDEO_MSVIDEO1, VIDEO_AV1, VIDEO_VC1, VIDEO_WMV3,
VIDEO_WVC1, VIDEO_MPEG1, VIDEO_DVVIDEO, VIDEO_RAWVIDEO, VIDEO_CINEPAK

// 音频 MIME（codeclist_core.cpp:55-84）
AUDIO_AMR_NB, AUDIO_AMR_WB, AUDIO_MPEG, AUDIO_AAC, AUDIO_VORBIS,
AUDIO_OPUS, AUDIO_FLAC, AUDIO_RAW, AUDIO_G711MU, AUDIO_G711A,
...（共47种）
```

### CapabilityData 能力数据结构

```cpp
// interfaces/inner_api/native/avcodec_info.h
struct CapabilityData {
    std::string codecName;      // e.g., "builtin.video_decoder.avc"
    AVCodecType codecType;      // VIDEO_DECODER / VIDEO_ENCODER / AUDIO_DECODER / AUDIO_ENCODER
    std::string mimeType;       // "video/avc"
    bool isVendor;              // true=硬件, false=软件
    int32_t width.minVal/maxVal;     // 视频分辨率范围
    int32_t height.minVal/maxVal;
    std::vector<int32_t> pixFormat;  // 支持的像素格式列表
    Range bitrate;              // 码率范围
    Range frameRate;            // 帧率范围
    Range channels;             // 音频通道数
    std::vector<int32_t> sampleRate; // 支持的采样率
};
```

### 七项 Capability Check 校验（CodecListCore）

```cpp
// services/engine/codeclist/codeclist_core.cpp
bool CodecListCore::IsVideoCapSupport(const Format &format, const CapabilityData &data)
{
    return CheckVideoResolution(format, data)   // 宽高是否在 [minVal, maxVal] 范围内
           && CheckVideoPixelFormat(format, data) // 像素格式是否在 pixFormat 列表中
           && CheckVideoFrameRate(format, data)   // 帧率范围校验（支持 int/double）
           && CheckBitrate(format, data);         // 码率是否在 [bitrate.minVal, bitrate.maxVal]
}

bool CodecListCore::IsAudioCapSupport(const Format &format, const CapabilityData &data)
{
    return CheckAudioChannel(format, data)       // 通道数是否在 [channels.minVal, channels.maxVal]
           && CheckAudioSampleRate(format, data) // 采样率是否在 sampleRate 列表中
           && CheckBitrate(format, data);
}
```

### CodecAbilitySingleton 单例注册流程

```cpp
// services/engine/codeclist/codec_ability_singleton.cpp
void CodecAbilitySingleton::RegisterCapabilityArray(std::vector<CapabilityData> &capaArray, CodecType codecType)
{
    for (size_t i = 0; i < capaArray.size(); i++) {
        // 按 MIME 建立倒排索引：mime → [capIdx1, capIdx2, ...]
        auto mime = capaArray[i].mimeType;
        mimeCapIdxMap_[mime].push_back(capabilityDataArray_.size());
        capabilityDataArray_.push_back(capaArray[i]);

        // 按名称建立类型映射：codecName → codecType
        nameCodecTypeMap_[capaArray[i].codecName] = codecType;
    }
}
```

### Native API 入口（AVCodecListFactory）

```cpp
// interfaces/inner_api/native/avcodec_list.h
class AVCodecList {
public:
    virtual std::string FindDecoder(const Format &format) = 0;
    virtual std::string FindEncoder(const Format &format) = 0;
    virtual CapabilityData *GetCapability(const std::string &mime, const bool isEncoder,
                                         const AVCodecCategory &category) = 0;
    virtual std::vector<std::shared_ptr<CapabilityData>> GetCapabilityList(int32_t codecType) = 0;
};

class AVCodecListFactory {
    static std::shared_ptr<AVCodecList> CreateAVCodecList(); // 工厂方法
};
```

### IPC 代理模式（CodecListClient）

```cpp
// services/services/codeclist/client/codeclist_client.cpp
std::string CodecListClient::FindDecoder(const Format &format)
{
    CHECK_AND_RETURN_RET_LOG(EnsureProxyValid(), "", "Find decoder failed");
    return codecListProxy_->FindDecoder(format); // 跨进程调用
}

bool CodecListClient::EnsureProxyValid()
{
    if (codecListProxy_ != nullptr) return true;
    codecListProxy_ = AVCodecServiceFactory::GetInstance().GetCodecListServiceProxy();
    // 自动重连机制
}
```

### 能力查询 GetCapabilityList 遍历模式

```cpp
// services/services/codeclist/client/codeclist_client.cpp
int32_t CodecListClient::GetCapabilityList(std::vector<std::shared_ptr<CapabilityData>> &outList)
{
    const int32_t MAX_LIMIT = 200;
    int32_t index = 0;
    while (index < MAX_LIMIT) {
        int32_t ret = codecListProxy_->GetCapabilityAt(*capabilityData, index);
        if (ret == AVCS_ERR_NOT_ENOUGH_DATA) break;  // 无更多数据，停止
        outList.emplace_back(capabilityData);
        index++;
    }
}
```

---

## Evidence 代码片段

### 文件路径 1: `services/services/codeclist/server/codeclist_server.h`
```cpp
class CodecListServer : public ICodecListService, public NoCopyable {
public:
    static std::shared_ptr<ICodecListService> Create();
    std::string FindDecoder(const Format &format) override;
    std::string FindEncoder(const Format &format) override;
    int32_t GetCapability(CapabilityData &capabilityData, const std::string &mime,
                          const bool isEncoder, const AVCodecCategory &category) override;
    int32_t GetCapabilityAt(CapabilityData &capabilityData, int32_t index) override;
private:
    bool Init();
    std::shared_ptr<CodecListCore> codecListCore_;  // 持有引擎层单例
};
```

### 文件路径 2: `services/engine/codeclist/codeclist_core.cpp`
```cpp
// FindCodec 是能力匹配的核心入口（第189行）
std::string CodecListCore::FindCodec(const Format &format, bool isEncoder)
{
    std::string targetMimeType;
    (void)format.GetStringValue("codec_mime", targetMimeType); // mime 是必要参数

    AVCodecType codecType = isVideo ? (isEncoder ? AVCODEC_TYPE_VIDEO_ENCODER
                                                  : AVCODEC_TYPE_VIDEO_DECODER)
                                    : (isEncoder ? AVCODEC_TYPE_AUDIO_ENCODER
                                                  : AVCODEC_TYPE_AUDIO_DECODER);

    // 从 CodecAbilitySingleton 获取全量能力数据
    std::vector<CapabilityData> capArray = CodecAbilitySingleton::GetInstance().GetCapabilityArray();
    std::unordered_map<std::string, std::vector<size_t>> mimeCapIdxMap =
        CodecAbilitySingleton::GetInstance().GetMimeCapIdxMap();

    std::vector<size_t> capsIdx = mimeCapIdxMap.at(targetMimeType); // MIME→索引映射
    for (auto iter = capsIdx.begin(); iter != capsIdx.end(); iter++) {
        CapabilityData capsData = capArray[*iter];
        if (isVideo) {
            if (IsVideoCapSupport(format, capsData)) {  // 七项 Check
                return capsData.codecName;
            }
        } else {
            if (IsAudioCapSupport(format, capsData)) {
                return capsData.codecName;
            }
        }
    }
    return "";
}
```

### 文件路径 3: `services/engine/codeclist/codec_ability_singleton.h`
```cpp
class CodecAbilitySingleton : public NoCopyable {
public:
    static CodecAbilitySingleton &GetInstance(); // 单例
    void RegisterCapabilityArray(std::vector<CapabilityData> &capaArray, CodecType codecType);
    std::vector<CapabilityData> GetCapabilityArray();         // 全量能力数组
    std::unordered_map<std::string, std::vector<size_t>> GetMimeCapIdxMap(); // MIME倒排索引
    std::unordered_map<std::string, CodecType> GetNameCodecTypeMap(); // 名称→类型映射
private:
    std::vector<CapabilityData> capabilityDataArray_;           // 存储所有能力
    std::unordered_map<std::string, std::vector<size_t>> mimeCapIdxMap_; // MIME→[idx]倒排
    std::unordered_map<std::string, CodecType> nameCodecTypeMap_;       // 名称→CodecType
    std::mutex mutex_;
};
```

### 文件路径 4: `interfaces/inner_api/native/avcodec_list.h`
```cpp
class AVCodecList {
public:
    virtual std::string FindDecoder(const Format &format) = 0;  // 按 Format 查找解码器
    virtual std::string FindEncoder(const Format &format) = 0;  // 按 Format 查找编码器
    virtual CapabilityData *GetCapability(const std::string &mime, const bool isEncoder,
                                         const AVCodecCategory &category) = 0;
    virtual std::vector<std::shared_ptr<CapabilityData>> GetCapabilityList(int32_t codecType) = 0;
};
class __attribute__((visibility("default"))) AVCodecListFactory {
    static std::shared_ptr<AVCodecList> CreateAVCodecList(); // Native API 工厂方法
};
```

---

## 关联主题

| 关联 ID | 关系 | 说明 |
|---------|------|------|
| MEM-ARCH-AVCODEC-S47 | 互补 | CodecCapability 能力查询与匹配机制（更上层能力模型） |
| MEM-ARCH-AVCODEC-S70 | 互补 | VideoCodec 工厂与 Loader 插件体系（能力由 Loader 插件注册） |
| MEM-ARCH-AVCODEC-P2b | 对应 | 能力查询 API（codeclist）—— 本主题是 P2b 的内部实现 |
| MEM-ARCH-AVCODEC-S39/S51/S53/S54 | 下游 | 各具体解码器实现，由 CodecList 查询返回名称 |

---

## 设计亮点

1. **三层解耦**：SA 服务层（CodecListServer）↔ 匹配引擎层（CodecListCore）↔ 数据层（CodecAbilitySingleton）
2. **MIME 倒排索引**：mimeCapIdxMap_ 实现 O(1) 级别 MIME→能力索引查找，避免全表扫描
3. **七项 Check 校验**：视频四维（分辨率/像素格式/帧率/码率）+ 音频三维（通道/采样率/码率）精确匹配
4. **自动重连**：CodecListClient 的 EnsureProxyValid() 实现了 IPC 断连自动重连
5. **硬件/软件分类**：通过 AVCodecCategory 和 isVendor 字段区分硬件编解码器和软件编解码器
6. **遍历式全量查询**：GetCapabilityList 通过 GetCapabilityAt 循环遍历最多 200 个能力条目

---

## 修订历史

| 日期 | 操作 | 说明 |
|------|------|------|
| 2026-05-02T21:03 | Builder 草案生成 | 首版草案，基于 local repo `/home/west/av_codec_repo` 源码 |
