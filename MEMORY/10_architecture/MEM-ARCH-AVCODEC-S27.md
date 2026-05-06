---
type: architecture
id: MEM-ARCH-AVCODEC-S27
status: approved
approved_at: "2026-05-06"
topic: CodecList 服务架构——CodecListCore + CodecAbilitySingleton + CodecListBuilder 三层能力查询体系
scope: [AVCodec, CodecList, Capability, CodecAbilitySingleton, CodecListCore, AVCodecList, Factory, SA, SystemAbility]
submitted_at: "2026-04-25T06:21:00+08:00"
author: builder-agent
evidence: |
  - source: interfaces/inner_api/native/avcodec_list.h line 25-73
    anchor: "class AVCodecList { virtual string FindDecoder/FindEncoder/GetCapability/GetCapabilityList; class AVCodecListFactory { static shared_ptr<AVCodecList> CreateAVCodecList(); }"
    note: AVCodecList 对外抽象接口，FindDecoder/FindEncoder/三个GetCapability变体，AVCodecListFactory 单例工厂
  - source: services/services/codeclist/server/codeclist_server.h line 26
    anchor: "class CodecListServer : public ICodecListService, public NoCopyable { static shared_ptr<ICodecListService> Create(); std::shared_ptr<CodecListCore> codecListCore_; }"
    note: CodecListServer 服务端实现，持有 CodecListCore，AVCodecSystemAbility::AVCODEC_CODECLIST 子系统
  - source: services/engine/codeclist/codeclist_core.h line 23-43
    anchor: "class CodecListCore { FindEncoder/FindDecoder/FindCodecType/FindCodecNameArray/GetCapability/GetCapabilityAt; mutex_; bool IsVideoCapSupport/IsAudioCapSupport; CheckBitrate/CheckVideoResolution/CheckVideoPixelFormat/CheckVideoFrameRate/CheckAudioChannel/CheckAudioSampleRate }"
    note: CodecListCore 核心实现层，七大Check函数覆盖分辨率/帧率/码率/像素格式/声道/采样率；FindCodec按codec_vendor_flag筛选软硬编
  - source: services/engine/codeclist/codec_ability_singleton.cpp line 60-76
    anchor: "CodecAbilitySingleton::GetInstance() static instance; CodecAbilitySingleton() { #ifndef CLIENT_SUPPORT_CODEC HCodecLoader::GetCapabilityList(videoCapaArray) → RegisterCapabilityArray; #endif codecLists = GetCodecLists() → AudioCodecList::GetCapabilityList(capaArray) → RegisterCapabilityArray }"
    note: CodecAbilitySingleton 单例初始化：硬件编解码通过HCodecLoader加载，软件编解码通过VideoCodecList/AudioCodecList，合并后通过RegisterCapabilityArray注册到全局能力数组
  - source: services/engine/codeclist/codeclist_core.cpp line 260-280
    anchor: "FindCodec() std::vector<CapabilityData> capabilityDataArray = CodecAbilitySingleton::GetInstance().GetCapabilityArray(); mimeCapIdxMap = CodecAbilitySingleton::GetInstance().GetMimeCapIdxMap(); for capsIdx: IsVideoCapSupport/IsAudioCapSupport"
    note: FindCodec 遍历匹配 mime → codecType → isVendor 三重过滤，IsVideoCapSupport五项校验（分辨率+像素格式+帧率+码率），IsAudioCapSupport三项校验
  - source: services/engine/codeclist/codeclist_builder.cpp line 32-120
    anchor: "VideoCodecList::GetCapabilityList → FCodecLoader::GetCapabilityList; VideoAvcEncoderList::GetCapabilityList → AvcEncoderLoader::GetCapabilityList; AudioCodecList::GetCapabilityList → AudioCodeclistInfo::GetInstance().GetAudioCapabilities()"
    note: CodecListBuilder 分Loader加载能力：FCodecLoader软件视频解码器、AvcEncoderLoader软件视频编码器、AudioCodeclistInfo音频能力单例
  - source: services/engine/codeclist/audio_codeclist_info.h line 25
    anchor: "class AudioCodeclistInfo { static AudioCodeclistInfo &GetInstance(); std::vector<CapabilityData> GetAudioCapabilities(); }"
    note: AudioCodeclistInfo 音频能力单例，GetAudioCapabilities 返回音频编解码能力数组
  - source: services/engine/codeclist/codec_ability_singleton.cpp line 111-165
    anchor: "void RegisterCapabilityArray(std::vector<CapabilityData> &capaArray, CodecType codecType) { for cap in capaArray: codecName_ → nameCodecTypeMap_; mime → mimeCapIdxMap_; isVendor ? codecVendorName_ : codecSoftwareName_; }"
    note: RegisterCapabilityArray 三路注册：nameCodecTypeMap_（codec名→CodecType）、mimeCapIdxMap_（mime→索引数组）、codecVendorName_/codecSoftwareName_（软硬件名列表）
  - source: services/engine/codeclist/codec_ability_singleton.h line 28-41
    anchor: "class CodecAbilitySingleton { static CodecAbilitySingleton &GetInstance(); std::vector<CapabilityData> GetCapabilityArray(); std::optional<CapabilityData> GetCapabilityByName(const string &name); std::string GetMimeByCodecName(const string &name); std::unordered_map<string, CodecType> GetNameCodecTypeMap(); std::unordered_map<string, vector<size_t>> GetMimeCapIdxMap(); int32_t GetVideoCodecTypeByCodecName(const string &codecName); }"
    note: CodecAbilitySingleton 五大数据源：能力数组、按名查询、Mime反查、codec名→CodecType映射、mime→索引映射
  - source: services/services/sa_avcodec/server/avcodec_server.cpp line 37-113
    anchor: "AVCodecServer(int32_t systemAbilityId, bool runOnCreate) : SystemAbility(systemAbilityId, runOnCreate); case AVCodecSystemAbility::AVCODEC_CODECLIST: codecListServer_ = CodecListServer::Create(); case AVCodecSystemAbility::AVCODEC_CODEC: codecServer_ = CodecServer::Create();"
    note: AVCodecServer 是 SA 主入口，按 AVCodecSystemAbility 子类型分发：AVCODEC_CODECLIST → CodecListServer，AVCODEC_CODEC → CodecServer
  - source: services/services/codeclist/ipc/codeclist_service_stub.cpp line 30-39
    anchor: "enum AVCodecListServiceInterfaceCode { FIND_DECODER=0, FIND_ENCODER, GET_CAPABILITY, GET_CAPABILITY_AT, DESTROY }"
    note: CodecListServiceStub 分发5个接口：FindDecoder/FindEncoder/GetCapability/GetCapabilityAt/Destroy
  - source: services/services/codeclist/server/codeclist_server.cpp line 40-68
    anchor: "CodecListServer() Init() → codecListCore_ = make_shared<CodecListCore>(); GetSubSystemAbility() → codecListServer_->FindDecoder(format)"
    note: CodecListServer 通过 IPC 调用 CodecListCore 完成任务
---

# MEM-ARCH-AVCODEC-S27: CodecList 服务架构——CodecListCore + CodecAbilitySingleton + CodecListBuilder 三层能力查询体系

## Metadata

| 字段 | 值 |
|------|-----|
| id | MEM-ARCH-AVCODEC-S27 |
| title | CodecList 服务架构——CodecListCore + CodecAbilitySingleton + CodecListBuilder 三层能力查询体系 |
| scope | [AVCodec, CodecList, Capability, CodecAbilitySingleton, CodecListCore, AVCodecList, Factory, SA, SystemAbility] |
| status | draft |
| created_by | builder-agent |
| created_at | 2026-04-25 |
| type | architecture_fact |
| confidence | high |

---

## 摘要

CodecList 是 AVCodec 对外提供能力查询的服务体系，位于 SA（SystemAbility）层。通过 CodecListServiceStub IPC 接收请求，CodecListCore 核心层执行七项 Check 校验，CodecAbilitySingleton 单例聚合硬件（HCodecLoader）和软件（FCodecLoader/AvcEncoderLoader/AudioCodeclistInfo）两路能力数据，三层协作完成 FindDecoder/FindEncoder/GetCapability 等能力查询 API。

---

## 1. 整体架构

```
外部调用（Native C API / Inner API）
  → AVCodecListFactory::CreateAVCodecList()
  → CodecListServiceStub（IPC，跨进程）
  → CodecListServer
  → CodecListCore
  → CodecAbilitySingleton（单例数据源）
    ├── HCodecLoader（硬件编解码能力，dlopen插件）
    ├── VideoCodecList → FCodecLoader（软件视频解码器能力）
    ├── VideoAvcEncoderList → AvcEncoderLoader（软件视频编码器能力）
    └── AudioCodecList → AudioCodeclistInfo（音频编解码能力）
```

---

## 2. SA 层入口：AVCodecServer

**文件**: `services/services/sa_avcodec/server/avcodec_server.cpp`

### 2.1 系统能力分发

```cpp
// line 37-113
AVCodecServer::AVCodecServer(int32_t systemAbilityId, bool runOnCreate)
    : SystemAbility(systemAbilityId, runOnCreate)
// OnAddSystemAbility 时按 subSystemId 分发
case AVCodecSystemAbility::AVCODEC_CODECLIST:  // 4501
    codecListServer_ = CodecListServer::Create();
case AVCodecSystemAbility::AVCODEC_CODEC:  // 4502
    codecServer_ = CodecServer::Create();
```

### 2.2 两个 SA 子系统

| SA ID | 子系统 | 职责 |
|-------|--------|------|
| 4501 | AVCODEC_CODECLIST | 能力查询：FindDecoder/FindEncoder/GetCapability |
| 4502 | AVCODEC_CODEC | 编解码执行：CodecBase/CodecServer |

---

## 3. CodecListServer 服务端

**文件**: `services/services/codeclist/server/codeclist_server.h`

### 3.1 类定义

```cpp
class CodecListServer : public ICodecListService, public NoCopyable {
public:
    static std::shared_ptr<ICodecListService> Create();
    CodecListServer();
    std::string FindDecoder(const Format &format) override;
    std::string FindEncoder(const Format &format) override;
    int32_t GetCapability(CapabilityData &capabilityData, const std::string &mime,
                          const bool isEncoder, const AVCodecCategory &category) override;
    int32_t GetCapabilityAt(CapabilityData &capabilityData, int32_t index) override;
private:
    bool Init();
    std::shared_ptr<CodecListCore> codecListCore_;  // 持有核心层
};
```

### 3.2 IPC 接口分发

**文件**: `services/services/codeclist/ipc/codeclist_service_stub.cpp`

```cpp
// line 30-39
enum AVCodecListServiceInterfaceCode {
    FIND_DECODER = 0,  // 0
    FIND_ENCODER,      // 1
    GET_CAPABILITY,    // 2
    GET_CAPABILITY_AT, // 3
    DESTROY            // 4
};
// CodecListServiceStub::OnRemoteRequest 五大接口分发
```

---

## 4. CodecListCore 核心实现层

**文件**: `services/engine/codeclist/codeclist_core.h` + `codeclist_core.cpp`

### 4.1 七大 Check 校验函数

| Check 函数 | 校验内容 | 对应 Format 字段 |
|-----------|---------|-----------------|
| `CheckBitrate` | 码率范围 | bitrate |
| `CheckVideoResolution` | 宽高范围 | width, height |
| `CheckVideoPixelFormat` | 像素格式是否支持 | pixel_format |
| `CheckVideoFrameRate` | 帧率范围（支持 int/double） | frame_rate |
| `CheckAudioChannel` | 声道数范围 | channel_count |
| `CheckAudioSampleRate` | 采样率是否支持 | samplerate |
| `IsVideoCapSupport` | 五项联合校验 | 视频用 |
| `IsAudioCapSupport` | 三项联合校验 | 音频用 |

### 4.2 FindCodec 查找流程

```cpp
// line 240-285
std::string FindCodec(const Format &format, bool isEncoder) {
    // 1. 从 format 提取 mime + codec_vendor_flag
    format.GetStringValue("codec_mime", targetMimeType);
    format.GetIntValue("codec_vendor_flag", isVendor);  // -1/0/1
    // 2. 确定 CodecType（AVCODEC_TYPE_VIDEO_DECODER/ENCODER 等）
    codecType = isVideo ? (isEncoder? VIDEO_ENCODER : VIDEO_DECODER)
                        : (isEncoder? AUDIO_ENCODER : AUDIO_DECODER);
    // 3. 从 CodecAbilitySingleton 获取 capabilityDataArray + mimeCapIdxMap
    // 4. 遍历 mimeCapIdxMap[targetMimeType] 索引数组
    for (idx : capsIdx) {
        if (codecType匹配 && mime匹配 && isVendor匹配) {
            if (isVideo && IsVideoCapSupport(format, capsData)) return codecName;
            if (!isVideo && IsAudioCapSupport(format, capsData)) return codecName;
        }
    }
}
```

### 4.3 GetCapabilityAt 按索引查询

```cpp
// line 356-366
int32_t GetCapabilityAt(CapabilityData &capabilityData, int32_t index) {
    auto capsDataArray = CodecAbilitySingleton::GetInstance().GetCapabilityArray();
    if (index < 0 || index >= capsDataArray.size()) return AVCS_ERR_NOT_ENOUGH_DATA;
    capabilityData = capsDataArray[index];
    return AVCS_ERR_OK;
}
```

---

## 5. CodecAbilitySingleton 单例数据源

**文件**: `services/engine/codeclist/codec_ability_singleton.cpp`

### 5.1 初始化流程

```cpp
// line 60-76
CodecAbilitySingleton::CodecAbilitySingleton() {
#ifndef CLIENT_SUPPORT_CODEC
    // 硬件编解码能力（HCodecLoader → dlopen 插件）
    HCodecLoader::GetCapabilityList(videoCapaArray);
    RegisterCapabilityArray(videoCapaArray, CodecType::AVCODEC_HCODEC);
#endif
    // 软件编解码能力（CodecListBuilder）
    codecLists = GetCodecLists();
    for (iter : codecLists) {
        iter->second->GetCapabilityList(capaArray);  // 视频/音频软件能力
        RegisterCapabilityArray(capaArray, codecType);
    }
}
```

### 5.2 三路注册（RegisterCapabilityArray）

```cpp
// line 111-165
void RegisterCapabilityArray(std::vector<CapabilityData> &capaArray, CodecType codecType) {
    for (cap : capaArray) {
        // 1. nameCodecTypeMap_: codec名 → CodecType
        nameCodecTypeMap_[cap.codecName] = codecType;
        // 2. mimeCapIdxMap_: mime → 索引数组（一个mime可能对应多个codec）
        auto &vec = mimeCapIdxMap_[cap.mimeType];
        vec.push_back(capabilityDataArray_.size());
        // 3. codecVendorName_ / codecSoftwareName_
        if (cap.isVendor) codecVendorName_.push_back(cap.codecName);
        else codecSoftwareName_.push_back(cap.codecName);
    }
}
```

### 5.3 五大查询接口

| 接口 | 返回 |
|------|------|
| `GetCapabilityArray()` | 全部 CapabilityData 数组 |
| `GetCapabilityByName(name)` | 按 codec 名查 CapabilityData |
| `GetMimeByCodecName(name)` | 按 codec 名反查 mime |
| `GetNameCodecTypeMap()` | codec名 → CodecType 映射 |
| `GetMimeCapIdxMap()` | mime → 索引数组映射 |
| `GetVideoCodecTypeByCodecName(name)` | codec名 → 视频CodecType |

---

## 6. CodecListBuilder 分 Loader 加载

**文件**: `services/engine/codeclist/codeclist_builder.cpp`

### 6.1 各 CodecList 实现

| 类 | Loader | 能力类型 |
|----|--------|---------|
| `VideoCodecList` | `FCodecLoader::GetCapabilityList` | 软件视频解码器 |
| `VideoHevcDecoderList` | `HevcDecoderLoader::GetCapabilityList` | HEVC 解码器 |
| `VideoAvcEncoderList` | `AvcEncoderLoader::GetCapabilityList` | AVC 编码器 |
| `AudioCodecList` | `AudioCodeclistInfo::GetInstance().GetAudioCapabilities()` | 音频编解码器 |

### 6.2 软件视频解码器（FCodecLoader）

```cpp
// codeclist_builder.cpp line 32-37
int32_t VideoCodecList::GetCapabilityList(std::vector<CapabilityData> &caps) {
    return FCodecLoader::GetCapabilityList(caps);
}
```

### 6.3 音频能力（AudioCodeclistInfo）

```cpp
// audio_codeclist_info.cpp line 932
AudioCodeclistInfo &AudioCodeclistInfo::GetInstance() {
    static AudioCodeclistInfo instance;
    return instance;
}
// GetAudioCapabilities() 返回音频编解码能力数组
```

---

## 7. 硬件能力加载：HCodecLoader

**文件**: `services/engine/codec/video/hcodec/`

```cpp
// codec_ability_singleton.cpp line 69
#ifndef CLIENT_SUPPORT_CODEC
HCodecLoader::GetCapabilityList(videoCapaArray);  // dlopen libhdi_codec.z.so
#endif
```

---

## 8. 数据流总结

```
Native API / Inner API
  → AVCodecListFactory::CreateAVCodecList()
  → CodecListServiceStub（IPC跨进程）
  → CodecListServer::FindDecoder(format)
  → CodecListCore::FindCodec(format, isEncoder=false)
  → CodecAbilitySingleton::GetCapabilityArray()
  → IsVideoCapSupport(format, capData) 五项Check
  → 返回匹配的 codecName
```

---

## 9. 关键类和函数索引

| 类/函数 | 文件 | 行号 |
|--------|------|------|
| `AVCodecList` | interfaces/inner_api/native/avcodec_list.h | 25 |
| `AVCodecListFactory::CreateAVCodecList` | interfaces/inner_api/native/avcodec_list.h | 61 |
| `CodecListServer` | services/services/codeclist/server/codeclist_server.h | 26 |
| `CodecListCore::FindCodec` | services/engine/codeclist/codeclist_core.cpp | 240 |
| `CodecListCore::IsVideoCapSupport` | services/engine/codeclist/codeclist_core.cpp | 198 |
| `CodecListCore::IsAudioCapSupport` | services/engine/codeclist/codeclist_core.cpp | 204 |
| `CodecAbilitySingleton::GetInstance` | services/engine/codeclist/codec_ability_singleton.cpp | 60 |
| `CodecAbilitySingleton::RegisterCapabilityArray` | services/engine/codeclist/codec_ability_singleton.cpp | 111 |
| `CodecListBuilder::VideoCodecList` | services/engine/codeclist/codeclist_builder.cpp | 32 |
| `AudioCodeclistInfo::GetInstance` | services/engine/codeclist/audio_codeclist_info.cpp | 932 |
| `AVCodecServer` | services/services/sa_avcodec/server/avcodec_server.cpp | 37 |
| `CodecListServiceStub` | services/services/codeclist/ipc/codeclist_service_stub.cpp | 30 |