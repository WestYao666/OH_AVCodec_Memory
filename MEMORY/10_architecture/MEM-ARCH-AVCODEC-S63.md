---
status: pending_approval
---

# MEM-ARCH-AVCODEC-S63

> **状态**: draft  
> **创建时间**: 2026-04-27T05:37+08:00  
> **创建者**: builder-agent  
> **scope**: AVCodec, DRM, CENC, Decrypt, SVP, NALU, Subsample, CodecDrmDecrypt, ContentProtection  

---

## 一、主题概述

**CodecDrmDecrypt** 是 OpenHarmony AVCodec 模块的 DRM CENC 解密核心引擎，负责对受保护视频/音频流进行解密预处理。位于 `services/drm_decryptor/codec_drm_decrypt.cpp`（764行），被 `CodecServer`（`codec_server.cpp:752`）持有并调用。

本条目聚焦 CodecDrmDecrypt 的内部解密流程、NAL 单元解析逻辑、subsample 加密结构、以及 SVP 安全视频路径决策机制。

---

## 二、核心类型与常量

| 符号 | 定义位置 | 说明 |
|------|----------|------|
| `SvpMode` 枚举 | codec_drm_decrypt.h:29-33 | `SVP_CLEAR=-1`(非保护视频) / `SVP_FALSE`(保护但非安全解码器) / `SVP_TRUE`(保护且需安全解码器) |
| `DRM_CodecType` | codec_drm_decrypt.cpp:104-109 | `DRM_VIDEO_AVC=0x1` / `DRM_VIDEO_HEVC` / `DRM_VIDEO_AVS` / `DRM_VIDEO_NONE` |
| `DRM_MAX_STREAM_DATA_SIZE` | codec_drm_decrypt.cpp:93 | `20971520` (20MB) |
| `DRM_H264_VIDEO_SKIP_BYTES` | codec_drm_decrypt.cpp:82 | `35` (32 + 3) 用于 H.264 NALU 头后数据 |
| `DRM_H265_VIDEO_SKIP_BYTES` | codec_drm_decrypt.cpp:83 | `68` (65 + 3) 用于 H.265 |
| `DRM_AVS3_VIDEO_SKIP_BYTES` | codec_drm_decrypt.cpp:84 | `4` (1 + 3) 用于 AVS3 |
| `DRM_LEGACY_LEN` | codec_drm_decrypt.cpp:79 | `3` 起始码 `0x00, 0x00, 0x01` 长度 |
| `DRM_AES_BLOCK_SIZE` | codec_drm_decrypt.cpp:80 | `16` AES 块大小 |
| `MetaDrmCencInfo` | codec_drm_decrypt.h:24 | 来自 `Plugins` 命名空间的 CENC 信息结构体 |
| `MetaDrmCencAlgorithm` | codec_drm_decrypt.h:25 | AES-CTR 加密算法标识 |
| `keySessionServiceProxy_` | codec_drm_decrypt.h:107 | `IMediaKeySessionService` DRM Session 代理（HDI） |
| `decryptModuleProxy_` | codec_drm_decrypt.h:108 | `IMediaDecryptModuleService` 解密模块代理（HDI） |
| `svpFlag_` | codec_drm_decrypt.h:110 | 当前 SVP 模式（`SvpMode`枚举） |

---

## 三、类架构

```cpp
class CodecDrmDecrypt {
public:
    // 公共 API：视频/音频 CENC 解密入口
    int32_t DrmVideoCencDecrypt(AVBuffer& inBuf, AVBuffer& outBuf, uint32_t& dataSize); // codec_drm_decrypt.cpp:551
    int32_t DrmAudioCencDecrypt(AVBuffer& inBuf, AVBuffer& outBuf, uint32_t& dataSize); // codec_drm_decrypt.cpp:595
    void SetCodecName(const std::string &codecName);
    void SetDecryptionConfig(sptr<IMediaKeySessionService> keySession, bool svpFlag);    // codec_drm_decrypt.cpp:661

private:
    // 内部核心解密
    int32_t DecryptMediaData(const MetaDrmCencInfo* cencInfo, AVBuffer& inBuf, AVBuffer& outBuf); // codec_drm_decrypt.cpp:737
    int32_t SetDrmBuffer(...);  // codec_drm_decrypt.cpp:684

    // NAL 单元解析
    uint8_t DrmGetFinalNalTypeAndIndex(...);  // codec_drm_decrypt.cpp:152
    int32_t DrmGetNalTypeAndIndex(...);        // codec_drm_decrypt.cpp:133
    static void DrmGetSyncHeaderIndex(...);   // codec_drm_decrypt.cpp:148
    int DrmFindCeiNalUnit(...);                // codec_drm_decrypt.cpp:372
    int DrmFindCeiPos(...);                    // codec_drm_decrypt.cpp:390

    // SEI 信息处理
    static int DrmFindH264CeiNalUnit(...);
    static int DrmFindHevcCeiNalUnit(...);
    static int DrmFindAvsCeiNalUnit(...);

    // Subsample 处理
    void DrmGetCencInfo(AVBuffer inBuf, uint32_t dataSize, uint8_t& isAmbiguity, MetaDrmCencInfo* cencInfo); // codec_drm_decrypt.cpp:534
    static void SetDrmAlgoAndBlocks(uint8_t algo, MetaDrmCencInfo* cencInfo);
    void DrmModifyCencInfo(AVBuffer inBuf, uint32_t& dataSize, uint8_t isAmbiguity, MetaDrmCencInfo* cencInfo) const;
    void DrmGetSkipClearBytes(uint32_t& skipBytes) const;  // codec_drm_decrypt.cpp:121

    // 去混淆字节
    static void DrmRemoveAmbiguityBytes(uint8_t* data, uint32_t& posEndIndex, uint32_t offset, uint32_t& dataSize);

    // DRM 信息提取
    static int DrmGetKeyId(...);
    static int DrmGetKeyIv(...);
    static int DrmParseDrmDescriptor(...);
    static void DrmFindEncryptionFlagPos(...);
    static void DrmSetKeyInfo(...);
    void GetCodingType();
    static void SetDrmAlgoAndBlocks(uint8_t algo, MetaDrmCencInfo* cencInfo);

private:
    std::mutex configMutex_;
    std::string codecName_;
    int32_t codingType_ = 0;   // DRM_CodecType 枚举值
    sptr<IMediaKeySessionService> keySessionServiceProxy_;    // 仅 SUPPORT_DRM 编译
    sptr<IMediaDecryptModuleService> decryptModuleProxy_;     // 仅 SUPPORT_DRM 编译
    int32_t svpFlag_ = SVP_CLEAR;
    MetaDrmCencInfoMode mode_ = MetaDrmCencInfoMode::META_DRM_CENC_INFO_KEY_IV_SUBSAMPLES_SET;
};
```

---

## 四、解密流程详解

### 4.1 视频解密入口：`DrmVideoCencDecrypt`

**位置**: `codec_drm_decrypt.cpp:551-592`

```
输入: inBuf（加密 ES 流）→ CodecDrmDecrypt::DrmVideoCencDecrypt → 输出: outBuf（解密后 ES 流）
```

**三步骤**:

1. **DRM 信息提取** — `codec_drm_decrypt.cpp:585`
   ```cpp
   DrmGetCencInfo(inBuf, dataSize, isAmbiguity, cencInfo);
   ```
   遍历NAL起始码(0x00000001)定位加密块，提取`subsamples`结构（`clearBytes`+`cryptBytes`）

2. **CENC 信息修改**（处理防伪字节填充）— `codec_drm_decrypt.cpp:586`
   ```cpp
   DrmModifyCencInfo(inBuf, dataSize, isAmbiguity, cencInfo);
   ```
   当 `isAmbiguity==1` 时，调用 `DrmRemoveAmbiguityBytes` 去除 `0x000003xx` 中的防伪字节(0x03)

3. **底层解密调用** — `codec_drm_decrypt.cpp:590`
   ```cpp
   ret = DecryptMediaData(cencInfo, inBuf, outBuf);
   ```

### 4.2 音频解密入口：`DrmAudioCencDecrypt`

**位置**: `codec_drm_decrypt.cpp:595-642`

音频路径不经过 NAL 单元解析，直接调用 `DrmGetCencInfo` + `DecryptMediaData`：
```cpp
codec_drm_decrypt.cpp:639:
ret = DecryptMediaData(cencInfo, inBuf, outBuf);
```

### 4.3 底层解密：`DecryptMediaData` → HDI 代理

**位置**: `codec_drm_decrypt.cpp:737-764`

```
DecryptMediaData
  ├─ SetDrmBuffer()          // codec_drm_decrypt.cpp:684 — 将 AVBuffer 转换为 DrmBuffer
  │     ├─ DrmBuffer inDrmBuffer(inBuf->memory_->GetAddr(), ...)
  │     └─ DrmBuffer outDrmBuffer(outBuf->memory_->GetAddr(), ...)
  └─ decryptModuleProxy_->DecryptMediaData(svpFlag_, cryptInfo, inDrmBuffer, outDrmBuffer)
                                              // codec_drm_decrypt.cpp:730 — HDI 调用
```

`DecryptMediaData` 持有 `decryptModuleProxy_`（`IMediaDecryptModuleService`）引用，通过 DRM HDI 接口完成实际 AES-CTR 解密。

---

## 五、NAL 单元解析与 Subsample 结构

### 5.1 NAL 类型识别

**H.264** (`codingType_ == DRM_VIDEO_AVC`):
```cpp
nalType = data[i + 3] & 0x1f;  // codec_drm_decrypt.cpp:139
// 有效 NAL: type 1-5 (IDR/Slice)
// 起始码: 0x00 0x00 0x01
```

**H.265** (`codingType_ == DRM_VIDEO_HEVC`):
```cpp
nalType = (data[i + 3] >> 1) & 0x3f;  // codec_drm_decrypt.cpp:142
// 起始码: 0x00 0x00 0x01
// 有效 NAL: type 0-31
```

### 5.2 Subsample 结构（CENC 标准）

`MetaDrmCencInfo` 包含:
- **subsamples[]**: `clearBytes`(明文长度) + `cryptBytes`(密文长度) 交替
- **keyId**: 16字节内容密钥 ID
- **IV**: 16字节初始化向量（AES-CTR）

**解密模式**（`mode_`）:
```cpp
// codec_drm_decrypt.h:110
MetaDrmCencInfoMode mode_ = MetaDrmCencInfoMode::META_DRM_CENC_INFO_KEY_IV_SUBSAMPLES_SET;
// 已知值: META_DRM_CENC_INFO_KEY_IV_SUBSAMPLES_SET
```

### 5.3 SEI 信息处理（DRM 加密区检测）

DRM CENC 中 SEI NALU 需特殊处理：

```cpp
// codec_drm_decrypt.cpp:372
int CodecDrmDecrypt::DrmFindCeiNalUnit(const uint8_t* data, uint32_t dataSize, uint32_t& ceiStartPos, uint32_t index)
{
    // 委托给编码格式专用函数:
    //   DrmFindH264CeiNalUnit  (type=0x06, H.264)
    //   DrmFindHevcCeiNalUnit  (type=0x4E/0x50, H.265)
    //   DrmFindAvsCeiNalUnit   (AVS3)
}
```

---

## 六、SVP 安全视频路径

### 6.1 SvpMode 决策链

```
CodecServer::SetDecryptConfig(keySession, svpFlag)    // codec_server.cpp:742
  ├─ CheckDrmSvpConsistency(keySession, svpFlag)      // codec_server.cpp:703
  │     ├─ svpFlag==false && decoder==secure → ERROR  (codec_server.cpp:711-713)
  │     └─ svpFlag==true && decoder==non-secure → ERROR (codec_server.cpp:721-723)
  ├─ svpFlag==true  → svpFlag_ = SVP_TRUE
  └─ svpFlag==false → svpFlag_ = SVP_FALSE

CodecDrmDecrypt::SetDecryptionConfig(keySession, svpFlag)  // codec_drm_decrypt.cpp:661
  ├─ svpFlag=true  → svpFlag_ = SVP_TRUE
  ├─ svpFlag=false → svpFlag_ = SVP_FALSE
  ├─ keySessionServiceProxy_ = keySession
  └─ keySessionServiceProxy_->GetMediaDecryptModule(decryptModuleProxy_)
```

### 6.2 三种 SVP 状态

| SvpMode 值 | 含义 | 解密行为 |
|-----------|------|---------|
| `SVP_CLEAR` (-1) | 非 DRM 保护流 | 直接复制，不解密 |
| `SVP_FALSE` (0) | DRM 保护但普通解码器 | 调用 DRM 解密 |
| `SVP_TRUE` (1) | DRM 保护且安全解码器（SVP） | 调用 DRM 解密 + 安全路径 |

---

## 七、与 CodecServer 集成

**CodecServer 持有**:
```cpp
// codec_server.h:166
std::shared_ptr<CodecDrmDecrypt> drmDecryptor_ = nullptr;

// codec_server.cpp:752 — 懒初始化
if (drmDecryptor_ == nullptr) {
    drmDecryptor_ = std::make_shared<CodecDrmDecrypt>();
}

// codec_server.cpp:600 — 视频解密入口
int32_t CodecServer::DrmVideoCencDecrypt(uint32_t index) {
    if (drmDecryptor_ != nullptr) {
        drmDecryptor_->SetCodecName(codecName_);  // 设置编码类型(AVC/HEVC/AVS)
        ret = drmDecryptor_->DrmVideoCencDecrypt(
            decryptVideoBufs_[index].inBuf,
            decryptVideoBufs_[index].outBuf,
            decryptVideoBufs_[index].dataSize);
    }
}
```

---

## 八、关联主题

| 关联 | 主题编号 | 说明 |
|------|---------|------|
| 上游 | MEM-ARCH-AVCODEC-017 | DRM CENC 解密流程整体（包含三层调用链） |
| 对等 | MEM-ARCH-AVCODEC-S57 | HDecoder/HEncoder 硬件编解码器（含 DRM 解密集成点） |
| Filter层 | MEM-ARCH-AVCODEC-S46 | DecoderSurfaceFilter（含 DRM/PostProcessor 扩展） |
| Pipeline | MEM-ARCH-AVCODEC-S41 | DemuxerFilter（含 DRM 回调） |

---

## 九、关键代码位置索引

| 符号 | 文件 | 行号 |
|------|------|------|
| `CodecDrmDecrypt::DrmVideoCencDecrypt` | codec_drm_decrypt.cpp | 551 |
| `CodecDrmDecrypt::DrmAudioCencDecrypt` | codec_drm_decrypt.cpp | 595 |
| `CodecDrmDecrypt::DecryptMediaData` | codec_drm_decrypt.cpp | 737 |
| `CodecDrmDecrypt::SetDrmBuffer` | codec_drm_decrypt.cpp | 684 |
| `CodecDrmDecrypt::SetDecryptionConfig` | codec_drm_decrypt.cpp | 661 |
| `CodecDrmDecrypt::DrmGetCencInfo` | codec_drm_decrypt.cpp | 534 |
| `CodecDrmDecrypt::DrmModifyCencInfo` | codec_drm_decrypt.cpp | 221 |
| `CodecDrmDecrypt::DrmGetNalTypeAndIndex` | codec_drm_decrypt.cpp | 133 |
| `CodecDrmDecrypt::DrmGetFinalNalTypeAndIndex` | codec_drm_decrypt.cpp | 152 |
| `CodecDrmDecrypt::DrmRemoveAmbiguityBytes` | codec_drm_decrypt.cpp | 195 |
| `CodecDrmDecrypt::DrmFindCeiNalUnit` | codec_drm_decrypt.cpp | 372 |
| `CodecDrmDecrypt::DrmGetSkipClearBytes` | codec_drm_decrypt.cpp | 121 |
| `CodecServer::drmDecryptor_` | codec_server.h | 166 |
| `CodecServer::SetDecryptConfig` | codec_server.cpp | 742 |
| `CodecServer::DrmVideoCencDecrypt` | codec_server.cpp | 600 |
| `CodecServer::CheckDrmSvpConsistency` | codec_server.cpp | 703 |
| `SvpMode` 枚举定义 | codec_drm_decrypt.h | 29-33 |
| `DRM_CodecType` 枚举 | codec_drm_decrypt.cpp | 104-109 |
