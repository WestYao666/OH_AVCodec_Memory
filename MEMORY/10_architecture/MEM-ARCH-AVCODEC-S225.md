---
id: MEM-ARCH-AVCODEC-S225
title: "CodecDrmDecrypt：CODEC DRM CENC 解密框架——H.264/HEVC/AVS3 全Codec统一内容解密引擎"
status: pending_approval
scope: AVCodec, DRM, CENC, SVP, Decryption, H.264, HEVC, AVS3, SecureVideoPath
created_at: "2026-06-08T08:08:00+08:00"
evidence_count: 20
source_files: |
  /home/west/av_codec_repo/services/drm_decryptor/codec_drm_decrypt.cpp (764行)
  /home/west/av_codec_repo/services/drm_decryptor/codec_drm_decrypt.h (88行)
  /home/west/av_codec_repo/interfaces/inner_api/native/drm_i_keysession_service.h
  /home/west/av_codec_repo/interfaces/inner_api/native/drm_i_mediadecryptmodule_service.h
关联主题: S114(MediaCodec DRM持有)/S121(DRM错误码)/S104(CodecBase DRM配置)/S63(CodecDrmDecrypt关联SEI解析)
---

# MEM-ARCH-AVCODEC-S225: CodecDrmDecrypt：CODEC DRM CENC 解密框架

**状态**: draft
**生成时间**: 2026-06-08T08:08:00+08:00
**来源**: 本地镜像探索 `/home/west/av_codec_repo/services/drm_decryptor/`

---

## 主题概述

CodecDrmDecrypt 是 AVCodec 的 **CENC（Common Encryption）内容解密引擎**，位于 `services/drm_decryptor/` 目录（cpp:764行，h:88行）。它为 VideoDecoder 和 AudioDecoder 提供统一的 DRM 解密能力，支持 H.264(AVC)、HEVC(H.265)、AVS3 三代 Codec 的加密内容解密，通过 SVP（Secure Video Path）模式与 DRM 服务（IMediaKeySessionService / IMediaDecryptModuleService）交互，完成从加密 ES（Elementary Stream）到明文 ES 的转换。

**核心价值**：在解码前将 CENC 加密的媒体流解密为明文，保护数字版权内容；同一 CodecDrmDecrypt 实例在 `svpFlag_` 控制下自动决定是否走安全视频路径（SVP_TRUE/SVP_FALSE）。

---

## 1. SvpMode 三态安全标识

### 1.1 SvpMode 枚举定义（codec_drm_decrypt.h L30-35）

```cpp
enum SvpMode : int32_t {
    SVP_CLEAR = -1, /* it's not a protection video */
    SVP_FALSE,      /* it's a protection video but not need secure decoder */
    SVP_TRUE,       /* it's a protection video and need secure decoder */
};
```

**E1** (codec_drm_decrypt.h L30-35): SvpMode 三态枚举：SVP_CLEAR(-1)表示非保护视频；SVP_FALSE(0)表示保护视频但无需安全解码器；SVP_TRUE(1)表示保护视频且需要安全解码器。SVP_CLEAR=-1 便于与 bool 型（0/1）区分。

### 1.2 svpFlag_ 成员变量（codec_drm_decrypt.h L80）

```cpp
int32_t svpFlag_ = SVP_CLEAR;  // 默认非保护视频
```

**E2** (codec_drm_decrypt.h L80): svpFlag_ 初始化为 SVP_CLEAR(-1)，即默认认为内容未加密。SetDecryptionConfig() 根据 svpFlag 参数更新为 SVP_TRUE 或 SVP_FALSE（L644-652）。

---

## 2. DRM 服务代理与配置

### 2.1 DRM 代理成员（codec_drm_decrypt.h L73-79）

```cpp
#ifdef SUPPORT_DRM
    sptr<DrmStandard::IMediaKeySessionService> keySessionServiceProxy_;
    sptr<DrmStandard::IMediaDecryptModuleService> decryptModuleProxy_;
#endif
    int32_t svpFlag_ = SVP_CLEAR;
    MetaDrmCencInfoMode mode_ = META_DRM_CENC_INFO_KEY_IV_SUBSAMPLES_SET;
```

**E3** (codec_drm_decrypt.h L73-79): 两层 DRM 代理架构：IMediaKeySessionService（密钥会话服务）和 IMediaDecryptModuleService（媒体解密模块服务），均在 `#ifdef SUPPORT_DRM` 条件编译下存在；mode_ 默认为 KEY_IV_SUBSAMPLES_SET 模式（L81）。

### 2.2 SetDecryptionConfig 配置入口（codec_drm_decrypt.cpp L644-652）

```cpp
void CodecDrmDecrypt::SetDecryptionConfig(
    const sptr<DrmStandard::IMediaKeySessionService> &keySession,
    const bool svpFlag)
{
    std::lock_guard<std::mutex> drmLock(configMutex_);
    if (svpFlag) {
        svpFlag_ = SVP_TRUE;
    } else {
        svpFlag_ = SVP_FALSE;
    }
    mode_ = MetaDrmCencInfoMode::META_DRM_CENC_INFO_KEY_IV_SUBSAMPLES_SET;
    keySessionServiceProxy_ = keySession;
    keySessionServiceProxy_->GetMediaDecryptModule(decryptModuleProxy_);
}
```

**E4** (codec_drm_decrypt.cpp L644-652): SetDecryptionConfig 先锁住 configMutex_ 再更新配置，防止并发；svpFlag 直接映射为 SVP_TRUE/SVP_FALSE；调用 GetMediaDecryptModule() 同步获取解密模块代理。

---

## 3. Codec 类型识别与 NAL 单元解析

### 3.1 GetCodingType 编码类型推断（codec_drm_decrypt.cpp L653-662）

```cpp
void CodecDrmDecrypt::GetCodingType()
{
    codingType_ = DRM_VIDEO_NONE;
    if (codecName_.find("avc") != codecName_.npos) {
        codingType_ = DRM_VIDEO_AVC;
    } else if (codecName_.find("hevc") != codecName_.npos) {
        codingType_ = DRM_VIDEO_HEVC;
    } else if (codecName_.find("avs") != codecName_.npos) {
        codingType_ = DRM_VIDEO_AVS;
    }
}
```

**E5** (codec_drm_decrypt.cpp L653-662): GetCodingType 根据 codecName 字符串匹配推断编码类型：含"avc"→DRM_VIDEO_AVC(0x1)；含"hevc"→DRM_VIDEO_HEVC(0x2)；含"avs"→DRM_VIDEO_AVS(0x3)；都不匹配→DRM_VIDEO_NONE(0x0)。

### 3.2 DRM_CodecType 枚举（codec_drm_decrypt.cpp L92-98）

```cpp
typedef enum {
    DRM_VIDEO_AVC = 0x1,
    DRM_VIDEO_HEVC,
    DRM_VIDEO_AVS,
    DRM_VIDEO_NONE,
} DRM_CodecType;
```

**E6** (codec_drm_decrypt.cpp L92-98): DRM_CodecType 使用十六进制字面值（0x1/0x2/0x3），与 SvpMode 三态体系并列，构成 CodecDrmDecrypt 的两种分类维度。

---

## 4. NAL 单元起始码扫描与类型解析

### 4.1 DrmGetNalTypeAndIndex NAL 类型解析（codec_drm_decrypt.cpp L90-119）

```cpp
int32_t CodecDrmDecrypt::DrmGetNalTypeAndIndex(const uint8_t *data, uint32_t dataSize,
    uint8_t &nalType, uint32_t &posIndex) const
{
    for (i = posIndex; (i + DRM_LEGACY_LEN) < dataSize; i++) {
        if ((data[i] != VIDEO_FRAME_ARR[0]) || (data[i+1] != VIDEO_FRAME_ARR[1]) || (data[i+2] != VIDEO_FRAME_ARR[2])) continue;
        if (codingType_ == DRM_VIDEO_AVC) {
            nalType = data[i+3] & DRM_H264_VIDEO_NAL_TYPE_UMASK_NUM; // 0x1f
            if ((nalType == DRM_H264_VIDEO_START_NAL_TYPE) || (nalType == DRM_H264_VIDEO_END_NAL_TYPE)) { ... }
        } else if (codingType_ == DRM_VIDEO_HEVC) {
            nalType = (data[i+3] >> DRM_SHIFT_LEFT_NUM) & DRM_H265_VIDEO_NAL_TYPE_UMASK_NUM; // 0x3f
            if ((nalType >= DRM_H265_VIDEO_START_NAL_TYPE) && (nalType <= DRM_H265_VIDEO_END_NAL_TYPE)) { ... }
        }
    }
}
```

**E7** (codec_drm_decrypt.cpp L90-119): DrmGetNalTypeAndIndex 遍历查找 0x000001 起始码（H.264用`&0x1f`取5位NAL类型，HEVC用`>>1 &0x3f`取6位NAL类型），命中 IDR/SPS/PPS 等关键 NAL 则返回。

### 4.2 DrmGetFinalNalTypeAndIndex 首个加密 NAL 定位（codec_drm_decrypt.cpp L153-182）

```cpp
uint8_t CodecDrmDecrypt::DrmGetFinalNalTypeAndIndex(const uint8_t *data, uint32_t dataSize,
    uint32_t &posStartIndex, uint32_t &posEndIndex) const
{
    DrmGetSkipClearBytes(skipBytes); // H.264=35, HEVC=68, AVS3=4
    while (1) {
        int32_t ret = DrmGetNalTypeAndIndex(data, dataSize, tmpNalType, tmpPosIndex);
        if (ret == 0) {
            nalType = tmpNalType;
            posStartIndex = tmpPosIndex;
            DrmGetSyncHeaderIndex(data, dataSize, tmpPosIndex);
            posEndIndex = tmpPosIndex;
            if (tmpPosIndex > posStartIndex + skipBytes + DRM_AES_BLOCK_SIZE) break;
        }
    }
    return nalType;
}
```

**E8** (codec_drm_decrypt.cpp L153-182): DrmGetFinalNalTypeAndIndex 循环找首个加密 NAL（跳过 clear header 后剩余数据 > skipBytes+AES_BLOCK_SIZE 则认为该 NAL 进入了加密区）；skipBytes 对三种 Codec 不同（H.264/HEVC/AVS3 分别为35/68/4字节）。

---

## 5. 加密算法映射与子样本公司

### 5.1 SetDrmAlgoAndBlocks 算法选择（codec_drm_decrypt.cpp L255-282）

```cpp
void CodecDrmDecrypt::SetDrmAlgoAndBlocks(uint8_t algo, MetaDrmCencInfo *cencInfo)
{
    if (algo == 0x1) { // SM4-SAMPL SM4S
        cencInfo->algo = META_DRM_ALG_CENC_SM4_CBC;
        cencInfo->encryptBlocks = DRM_CRYPT_BYTE_BLOCK; // 1
        cencInfo->skipBlocks = DRM_SKIP_BYTE_BLOCK;     // 9
    } else if (algo == 0x2) { // AES CBCS
        cencInfo->algo = META_DRM_ALG_CENC_AES_CBC;
        cencInfo->encryptBlocks = 1; cencInfo->skipBlocks = 9;
    } else if (algo == 0x5) { // AES CBC1
        cencInfo->algo = META_DRM_ALG_CENC_AES_CBC;
        cencInfo->encryptBlocks = 0; cencInfo->skipBlocks = 0;
    } else if (algo == 0x3) { // SM4-CBC SM4C
        cencInfo->algo = META_DRM_ALG_CENC_SM4_CBC;
        cencInfo->encryptBlocks = 0; cencInfo->skipBlocks = 0;
    } else if (algo == 0x0) { // NONE
        cencInfo->algo = META_DRM_ALG_CENC_UNENCRYPTED;
        cencInfo->encryptBlocks = 0; cencInfo->skipBlocks = 0;
    }
}
```

**E9** (codec_drm_decrypt.cpp L255-282): SetDrmAlgoAndBlocks 将 1-byte 算法标识映射为 META_DRM_ALG_CENC_* 枚举；CBCS 模式（algo=0x2）使用 encryptBlocks=1/skipBlocks=9 的标准 pattern；CBC1 模式（algo=0x5）blocks 全为0。

---

## 6. SEI（补充增强信息）解析与 DRM 描述符提取

### 6.1 DrmFindCeiNalUnit 多Codec SEI定位（codec_drm_decrypt.cpp L356-399）

```cpp
int CodecDrmDecrypt::DrmFindCeiNalUnit(const uint8_t *data, uint32_t dataSize, uint32_t &ceiStartPos,
    uint32_t index) const
{
    if (codingType_ == DRM_VIDEO_AVS) {
        ret = DrmFindAvsCeiNalUnit(data, dataSize, ceiStartPos, index);
    } else if (codingType_ == DRM_VIDEO_HEVC) {
        ret = DrmFindHevcCeiNalUnit(data, dataSize, ceiStartPos, index);
    } else if (codingType_ == DRM_VIDEO_AVC) {
        ret = DrmFindH264CeiNalUnit(data, dataSize, ceiStartPos, index);
    }
    return ret;
}
```

**E10** (codec_drm_decrypt.cpp L356-399): DrmFindCeiNalUnit 是多Codec分派器，根据 codingType_ 调用 DrmFindAvsCeiNalUnit/DrmFindHevcCeiNalUnit/DrmFindH264CeiNalUnit，HEVC NAL type 39（SEI）且 payload type=0x05（ unregistered）为 DRM 信息所在。

### 6.2 DrmFindHevcCeiNalUnit HEVC SEI查找（codec_drm_decrypt.cpp L322-354）

```cpp
int CodecDrmDecrypt::DrmFindHevcCeiNalUnit(const uint8_t *data, uint32_t dataSize, uint32_t &ceiStartPos,
    uint32_t index)
{
    uint8_t nalType = (data[i + DRM_LEGACY_LEN] >> DRM_SHIFT_LEFT_NUM) & DRM_H265_VIDEO_NAL_TYPE_UMASK_NUM;
    if (nalType <= DRM_H265_VIDEO_END_NAL_TYPE) { return 0; } // 帧数据，跳出
    } else if ((nalType == 39) && (i + DRM_H265_PAYLOAD_TYPE_OFFSET < dataSize)) {
        if (data[i + DRM_H265_PAYLOAD_TYPE_OFFSET] == DRM_USER_DATA_UNREGISTERED_TAG) {
            ceiStartPos = i;
        }
    }
    // 在 UNREGISTERED SEI 中查找用户注册 UUID（DRM descriptor）
    for (; (startPos + DRM_USER_DATA_REGISTERED_UUID_SIZE < endPos); startPos++) {
        if (memcmp(data + startPos, USER_REGISTERED_UUID, ...) == 0) { ceiStartPos = i; }
    }
}
```

**E11** (codec_drm_decrypt.cpp L322-354): HEVC SEI 定位：NAL type=39 且 payload_type=0x05（unregistered user data）为 DRM 信息携带者；通过比对16字节 USER_REGISTERED_UUID `{0x70,0xc1,0xdb,0x9f,0x66,0xae,0x41,0x27,0xbf,0xc0,0xbb,0x19,0x81,0x69,0x4b,0x66}` 确认 DRM descriptor 存在。

---

## 7. DRM 描述符解析与 Key 信息提取

### 7.1 DrmSetKeyInfo 总入口（codec_drm_decrypt.cpp L485-518）

```cpp
void CodecDrmDecrypt::DrmSetKeyInfo(const uint8_t *data, uint32_t dataSize, uint32_t ceiStartPos,
    uint8_t &isAmbiguity, MetaDrmCencInfo *cencInfo)
{
    ceiBuf = malloc(dataSize); memcpy_s(ceiBuf, dataSize, data, dataSize);
    DrmFindEncryptionFlagPos(ceiBuf, totalSize, pos);
    drmDescriptorFlag = (ceiBuf[pos] & 0x20) >> 5; // 第5位
    drmNotAmbiguityFlag = (ceiBuf[pos] & 0x10) >> 4; // 第4位
    if (drmNotAmbiguityFlag == 1) isAmbiguity = 0; else isAmbiguity = 1;
    ret = DrmGetKeyId(ceiBuf, totalSize, pos, cencInfo); // 提取KeyId
    if (ret == 0) {
        ret = DrmGetKeyIv(ceiBuf, totalSize, pos, cencInfo); // 提取IV
        if (ret == 0) {
            (void)DrmParseDrmDescriptor(ceiBuf, totalSize, pos, drmDescriptorFlag, cencInfo);
        }
    }
    free(ceiBuf);
}
```

**E12** (codec_drm_decrypt.cpp L485-518): DrmSetKeyInfo 依次解析 EncryptionFlag（第7位）、nextKeyIdFlag（第6位）、drmDescriptorFlag（第5位）、drmNotAmbiguityFlag（第4位）；分三步提取 KeyId → IV → DRM Descriptor。

### 7.2 DrmGetKeyId KeyId 提取（codec_drm_decrypt.cpp L419-438）

```cpp
int CodecDrmDecrypt::DrmGetKeyId(uint8_t *data, uint32_t &dataSize, uint32_t &pos, MetaDrmCencInfo *cencInfo)
{
    uint8_t encryptionFlag = (data[offset] & 0x80) >> 7;
    uint8_t nextKeyIdFlag = (data[offset] & 0x40) >> 6;
    offset += 1;
    DrmRemoveAmbiguityBytes(data, dataSize, offset, dataSize);
    if (encryptionFlag != 0) {
        errno_t res = memcpy_s(cencInfo->keyId, META_DRM_KEY_ID_SIZE, data + offset, META_DRM_KEY_ID_SIZE);
        cencInfo->keyIdLen = META_DRM_KEY_ID_SIZE;
        offset += META_DRM_KEY_ID_SIZE;
    } else {
        cencInfo->algo = META_DRM_ALG_CENC_UNENCRYPTED; // 无加密标识则标记为未加密
    }
}
```

**E13** (codec_drm_decrypt.cpp L419-438): encryptionFlag=0 表示该内容未加密，直接设置 algo=UNENCRYPTED；encryptionFlag=1 时才从 CEI buffer 提取 META_DRM_KEY_ID_SIZE（16字节）长度的 keyId。

---

## 8. 子样本公司（SubSample）结构与 CENC 加密模式

### 8.1 DrmModifyCencInfo 子样本构造（codec_drm_decrypt.cpp L207-253）

```cpp
void CodecDrmDecrypt::DrmModifyCencInfo(std::shared_ptr<AVBuffer> inBuf, uint32_t &dataSize, uint8_t isAmbiguity,
    MetaDrmCencInfo *cencInfo) const
{
    nalType = DrmGetFinalNalTypeAndIndex(data, dataSize, posStartIndex, posEndIndex);
    if (isAmbiguity == 1) DrmRemoveAmbiguityBytes(data, posEndIndex, posStartIndex, dataSize);
    uint32_t clearHeaderLen = posStartIndex + skipBytes;
    uint32_t payLoadLen = (posEndIndex > clearHeaderLen + delLen) ? (posEndIndex - clearHeaderLen - delLen) : 0;
    if (payLoadLen > 0) {
        uint32_t lastClearLen = (payLoadLen % DRM_AES_BLOCK_SIZE == 0) ? DRM_AES_BLOCK_SIZE : (payLoadLen % DRM_AES_BLOCK_SIZE);
        payLoadLen = payLoadLen - lastClearLen;
        cencInfo->subSamples[0].clearHeaderLen = clearHeaderLen;
        cencInfo->subSamples[0].payLoadLen = payLoadLen;
        cencInfo->subSamples[1].clearHeaderLen = lastClearLen + delLen + (dataSize - posEndIndex);
        cencInfo->subSamples[1].payLoadLen = 0;
    }
    cencInfo->subSampleNum = DRM_TS_SUB_SAMPLE_NUM; // 2
}
```

**E14** (codec_drm_decrypt.cpp L207-253): DrmModifyCencInfo 将加密 NAL 分为两个 SubSample：subSamples[0]含 clearHeader（起始码+clear）+加密payload；subSamples[1]含AES块对齐尾部（lastClearLen）+歧义字节删除区+NAL后数据；subSampleNum=2（DRM_TS_SUB_SAMPLE_NUM）。

### 8.2 DrmVideoCencDecrypt 视频解密主入口（codec_drm_decrypt.cpp L528-575）

```cpp
int32_t CodecDrmDecrypt::DrmVideoCencDecrypt(std::shared_ptr<AVBuffer> &inBuf, std::shared_ptr<AVBuffer> &outBuf,
    uint32_t &dataSize)
{
    GetCodingType();
    if (inBuf->meta_ != nullptr) {
        std::vector<uint8_t> drmCencVec;
        MetaDrmCencInfo *cencInfo = nullptr;
        bool res = inBuf->meta_->GetData(Media::Tag::DRM_CENC_INFO, drmCencVec);
        if (res) { cencInfo = ...; } else { clearCencInfo.algo = UNENCRYPTED; cencInfo = &clearCencInfo; }
        if (cencInfo->mode == META_DRM_CENC_INFO_KEY_IV_SUBSAMPLES_NOT_SET ||
            mode_ == META_DRM_CENC_INFO_KEY_IV_SUBSAMPLES_NOT_SET) {
            uint8_t isAmbiguity = 1;
            DrmGetCencInfo(inBuf, dataSize, isAmbiguity, cencInfo);  // 从SEI提取
            DrmModifyCencInfo(inBuf, dataSize, isAmbiguity, cencInfo); // 构造subsample
            cencInfo->subSampleNum = DRM_TS_SUB_SAMPLE_NUM;
            mode_ = cencInfo->mode;
        }
        ret = DecryptMediaData(cencInfo, inBuf, outBuf);
    }
    return ret;
}
```

**E15** (codec_drm_decrypt.cpp L528-575): DrmVideoCencDecrypt 先尝试从 AVBuffer 的 meta 中获取 DRM_CENC_INFO（外部已解析的）；若未设置（KEY_IV_SUBSAMPLES_NOT_SET），则自己从 SEI 解析 DRM 信息并构造 SubSample；最后统一调用 DecryptMediaData。

---

## 9. 音频 CENC 解密与 SubSample 自动构造

### 9.1 DrmAudioCencDecrypt 音频解密主入口（codec_drm_decrypt.cpp L577-626）

```cpp
int32_t CodecDrmDecrypt::DrmAudioCencDecrypt(std::shared_ptr<AVBuffer> &inBuf, std::shared_ptr<AVBuffer> &outBuf,
    uint32_t &dataSize)
{
    CHECK_AND_RETURN_RET_LOG((inBuf->meta_ != nullptr), ret, "DrmCencDecrypt meta null");
    std::vector<uint8_t> drmCencVec;
    MetaDrmCencInfo *cencInfo = nullptr;
    bool res = inBuf->meta_->GetData(Media::Tag::DRM_CENC_INFO, drmCencVec);
    if (res) {
        if (cencInfo->algo == META_DRM_ALG_CENC_AES_CTR || cencInfo->algo == META_DRM_ALG_CENC_SM4_CTR) {
            cencInfo->subSampleNum = 1;
            cencInfo->subSamples[0].clearHeaderLen = 0;
            cencInfo->subSamples[0].payLoadLen = dataSize;
        }
        if (cencInfo->algo == META_DRM_ALG_CENC_AES_CBC || cencInfo->algo == META_DRM_ALG_CENC_SM4_CBC) {
            cencInfo->subSampleNum = 2;
            cencInfo->subSamples[0].clearHeaderLen = 0;
            cencInfo->subSamples[0].payLoadLen = (dataSize / 16) * 16; // 16字节对齐
            cencInfo->subSamples[1].clearHeaderLen = dataSize % 16;
            cencInfo->subSamples[1].payLoadLen = 0;
        }
    } else { ... clearCencInfo ... }
    ret = DecryptMediaData(cencInfo, inBuf, outBuf);
}
```

**E16** (codec_drm_decrypt.cpp L577-626): DrmAudioCencDecrypt 根据算法类型自动构造 SubSample：CTR/SM4-CTR（流式）用1个 SubSample 全量 payload；CBC/SM4-CBC（块模式）用2个 SubSample（16字节对齐的加密块 + 不足16字节的尾部明文）。

---

## 10. DRM 解密缓冲区与 CryptInfo 组装

### 10.1 SetDrmBuffer DrmBuffer/CryptInfo 组装（codec_drm_decrypt.cpp L667-715）

```cpp
int32_t CodecDrmDecrypt::SetDrmBuffer(const MetaDrmCencInfo * const cencInfo,
    const std::shared_ptr<AVBuffer> &inBuf, const std::shared_ptr<AVBuffer> &outBuf) const
{
    DrmBuffer inDrmBuffer, outDrmBuffer;
    inDrmBuffer.bufferType = static_cast<uint32_t>(inBuf->memory_->GetMemoryType());
    inDrmBuffer.fd = inBuf->memory_->GetFileDescriptor();
    inDrmBuffer.allocLen = static_cast<uint32_t>(inBuf->memory_->GetCapacity());
    inDrmBuffer.filledLen = static_cast<uint32_t>(inBuf->memory_->GetSize());
    inDrmBuffer.offset = static_cast<uint32_t>(inBuf->memory_->GetOffset());
    DrmStandard::CryptInfo cryptInfo;
    cryptInfo.type = static_cast<DrmStandard::CryptAlgorithmType>(cencInfo->algo);
    std::vector<uint8_t> keyIdVector(cencInfo->keyId, cencInfo->keyId + cencInfo->keyIdLen);
    cryptInfo.keyId = keyIdVector;
    cryptInfo.pattern.encryptBlocks = cencInfo->encryptBlocks;
    cryptInfo.pattern.skipBlocks = cencInfo->skipBlocks;
    for (uint32_t i = 0; i < cencInfo->subSampleNum; i++) {
        DrmStandard::SubSample temp({ cencInfo->subSamples[i].clearHeaderLen,
            cencInfo->subSamples[i].payLoadLen });
        cryptInfo.subSample.emplace_back(temp);
    }
    retCode = decryptModuleProxy_->DecryptMediaData(svpFlag_, cryptInfo, inDrmBuffer, outDrmBuffer);
}
```

**E17** (codec_drm_decrypt.cpp L667-715): SetDrmBuffer 将 AVBuffer 的内存信息映射为 DrmBuffer（包含 fd/offset/allocLen/filledLen）；将 MetaDrmCencInfo 映射为 CryptInfo（type/keyId/iv/pattern/subSamples）；通过 decryptModuleProxy_->DecryptMediaData(svpFlag_, ...) 传入 SVP 标识。

---

## 11. 歧义字节移除与加密常量

### 11.1 DrmRemoveAmbiguityBytes 歧义字节移除（codec_drm_decrypt.cpp L184-202）

```cpp
void CodecDrmDecrypt::DrmRemoveAmbiguityBytes(uint8_t *data, uint32_t &posEndIndex, uint32_t offset,
    uint32_t &dataSize)
{
    for (i = offset; (i + DRM_LEGACY_LEN) < len; i++) {
        if ((data[i] == AMBIGUITY_ARR[0]) && (data[i+1] == AMBIGUITY_ARR[1]) && (data[i+2] == AMBIGUITY_ARR[2])) {
            if (data[i+3] >= DRM_AMBIGUITY_START_NUM && data[i+3] <= DRM_AMBIGUITY_END_NUM) {
                // 0x000003xx → 0x0000xx (移除第3字节)
                errno_t res = memmove_s(data + i + DRM_LEGACY_LEN - 1, len - ..., data + i + DRM_LEGACY_LEN, ...);
                len -= 1; i++;
            }
        }
    }
    dataSize = dataSize - (posEndIndex - len);
    posEndIndex = len;
}
```

**E18** (codec_drm_decrypt.cpp L184-202): CENC 规范要求去除 start code 歧义字节（0x000003xx → 0x0000xx），其中 xx 范围 0x00-0x03（DRM_AMBIGUITY_START_NUM/END_NUM）；歧义字节移除后 dataSize 和 posEndIndex 同步更新。

### 11.2 DRM 加解密常量（codec_drm_decrypt.cpp L27-56）

```cpp
#define DRM_VIDEO_FRAME_ARR_LEN            3
#define DRM_USER_DATA_REGISTERED_UUID_SIZE 16
constexpr uint32_t DRM_LEGACY_LEN = 3;
constexpr uint32_t DRM_AES_BLOCK_SIZE = 16;
constexpr uint8_t DRM_AMBIGUITY_START_NUM = 0x00;
constexpr uint8_t DRM_AMBIGUITY_END_NUM = 0x03;
constexpr uint32_t DRM_CRYPT_BYTE_BLOCK = 1;
constexpr uint32_t DRM_SKIP_BYTE_BLOCK = 9;
constexpr uint32_t DRM_H264_VIDEO_SKIP_BYTES = 35;  // 32+3
constexpr uint32_t DRM_H265_VIDEO_SKIP_BYTES = 68;  // 65+3
constexpr uint32_t DRM_AVS3_VIDEO_SKIP_BYTES = 4;   // 1+3
constexpr uint32_t DRM_MAX_STREAM_DATA_SIZE = 20971520; // 20MB
```

**E19** (codec_drm_decrypt.cpp L27-56): 核心常量：DRM_LEGACY_LEN=3（起始码 0x000001 的长度）；DRM_AES_BLOCK_SIZE=16（AES 块大小）；skipBytes 三Codec各异（H.264=35=32字节NAL头+3，HEVC=68=65+3，AVS3=4=1+3）；DRM_MAX_STREAM_DATA_SIZE=20MB。

---

## 12. DecryptMediaData 最终解密调用

### 12.1 DecryptMediaData 解密入口（codec_drm_decrypt.cpp L718-748）

```cpp
int32_t CodecDrmDecrypt::DecryptMediaData(const MetaDrmCencInfo * const cencInfo,
    std::shared_ptr<AVBuffer> &inBuf, std::shared_ptr<AVBuffer> &outBuf)
{
#ifdef SUPPORT_DRM
    std::lock_guard<std::mutex> drmLock(configMutex_);
    CHECK_AND_RETURN_RET_LOG(((cencInfo->keyIdLen <= META_DRM_KEY_ID_SIZE) &&
        (cencInfo->ivLen <= META_DRM_IV_SIZE) &&
        (cencInfo->subSampleNum <= META_DRM_MAX_SUB_SAMPLE_NUM)), retCode, "parameter err");
    retCode = SetDrmBuffer(cencInfo, inBuf, outBuf);
    CHECK_AND_RETURN_RET_LOG((retCode == AVCS_ERR_OK), retCode, "SetDecryptConfig failed");
    return AVCS_ERR_OK;
#else
    return AVCS_ERR_OK;
#endif
}
```

**E20** (codec_drm_decrypt.cpp L718-748): DecryptMediaData 先做三上限校验（keyIdLen ≤ KEY_ID_SIZE，ivLen ≤ IV_SIZE，subSampleNum ≤ MAX_SUB_SAMPLE_NUM）；然后通过 SetDrmBuffer 组装 DRM 调用；在 `#ifdef SUPPORT_DRM` 外层，不支持 DRM 时直接返回 OK（透明通道）。

---

## 附录：CodecDrmDecrypt 与相关 S 系列记忆关联

| 关联记忆 | 关联内容 |
|---------|---------|
| `MEM-ARCH-AVCODEC-S114` | MediaCodec 持有 `std::shared_ptr<CodecDrmDecrypt> drmDecryptor_`（media_codec.h:219），在解码流程中调用 DrmVideoCencDecrypt |
| `MEM-ARCH-AVCODEC-S121` | DRM 解密失败错误码 `AVCS_ERR_DECRYPT_FAILED`，DRM info 上报通道 |
| `MEM-ARCH-AVCODEC-S104` | CodecBase DRM 配置接口与 DMA-BUF 内存管理 |
| `MEM-ARCH-AVCODEC-S63` | SEI 解析器 SeiParserFilter 与 CodecDrmDecrypt 的执行顺序（DRM解密在SEI解析之前）|
| `MEM-ARCH-AVCODEC-S113` | SEI 信息解析框架（SEI 通常内嵌于加密 NAL 之后，需先解密再解析）|

---

## 附录：核心数据结构一览

| 数据结构 | 所在文件 | 用途 |
|---------|---------|------|
| `SvpMode` | codec_drm_decrypt.h:30 | 安全视频路径三态标识 |
| `MetaDrmCencInfo` | drm_i_keysession_service.h | CENC 加密信息（KeyId/IV/SubSamples/Algo） |
| `MetaDrmCencAlgorithm` | Plugins 命名空间 | 算法枚举（SM4-CBC/AES-CBC/CTR/UNENCRYPTED） |
| `DrmBuffer` | DrmStandard 命名空间 | DRM 解密输入输出缓冲区抽象 |
| `CryptInfo` | DrmStandard 命名空间 | 加密参数（type/keyId/iv/pattern/subSamples） |
| `IMediaKeySessionService` | drm_i_keysession_service.h | DRM 密钥会话服务（SetDecryptionConfig获取） |
| `IMediaDecryptModuleService` | drm_i_mediadecryptmodule_service.h | 媒体解密模块（DecryptMediaData调用） |
---

## 13. SEI NALU 三Codec专用解析器

### 13.1 DrmFindAvsCeiNalUnit AVS3 SEI定位（codec_drm_decrypt.cpp L282-305）

```cpp
int CodecDrmDecrypt::DrmFindAvsCeiNalUnit(const uint8_t *data, uint32_t dataSize, uint32_t &ceiStartPos,
    uint32_t index)
{
    uint32_t i = index;
    if (((data[i + DRM_LEGACY_LEN] > 0) && (data[i + DRM_LEGACY_LEN] < 0xb8)) &&
        (data[i + DRM_LEGACY_LEN] != 0xb0) && (data[i + DRM_LEGACY_LEN] != 0xb5) &&
        (data[i + DRM_LEGACY_LEN] != 0xb1)) {
        return 0; // avs frame found
    }
    if ((data[i + DRM_LEGACY_LEN] == 0xb5) && (i + DRM_LEGACY_LEN + 1 < dataSize)) {
        if ((data[i + DRM_LEGACY_LEN + 1] & 0xf0) == 0xd0) { // extension user data tag
            ceiStartPos = i;
        }
    }
    return -1;
}
```

**E21** (codec_drm_decrypt.cpp L282-305): AVS3 SEI定位：AVS3 NALU header 0xb5（extension_and_user_data）中的 extension user data tag（0xd0）与 H.264/HEVC完全不同；AVS3 不使用 NAL type 而是使用0xb0-0xb5 范围判断帧 vs SEI。

### 13.2 DrmFindHevcCeiNalUnit HEVC SEI定位（codec_drm_decrypt.cpp L307-337）

```cpp
int CodecDrmDecrypt::DrmFindHevcCeiNalUnit(const uint8_t *data, uint32_t dataSize, uint32_t &ceiStartPos,
    uint32_t index)
{
    uint32_t i = index;
    uint8_t nalType = (data[i + DRM_LEGACY_LEN] >> DRM_SHIFT_LEFT_NUM) & DRM_H265_VIDEO_NAL_TYPE_UMASK_NUM;
    if (nalType <= DRM_H265_VIDEO_END_NAL_TYPE) { return 0; } // 帧数据
    } else if ((nalType == 39) && (i + DRM_H265_PAYLOAD_TYPE_OFFSET < dataSize)) {
        if (data[i + DRM_H265_PAYLOAD_TYPE_OFFSET] == DRM_USER_DATA_UNREGISTERED_TAG) {
            ceiStartPos = i;
        }
    }
    // UUID比对确认DRM descriptor
    for (; (startPos + DRM_USER_DATA_REGISTERED_UUID_SIZE < endPos); startPos++) {
        if (memcmp(data + startPos, USER_REGISTERED_UUID, ...) == 0) { ceiStartPos = i; break; }
    }
}
```

**E22** (codec_drm_decrypt.cpp L307-337): HEVC SEI 定位：NAL type=39 且 payload_type=0x05；使用右移 DRM_SHIFT_LEFT_NUM 提取 6-bit NAL type；UUID 比对确认 DRM descriptor 存在于 UNREGISTERED SEI 中。

### 13.3 DrmFindH264CeiNalUnit H.264 SEI定位（codec_drm_decrypt.cpp L339-370）

```cpp
int CodecDrmDecrypt::DrmFindH264CeiNalUnit(const uint8_t *data, uint32_t dataSize, uint32_t &ceiStartPos,
    uint32_t index)
{
    uint32_t i = index;
    uint8_t nalType = data[i + DRM_LEGACY_LEN] & DRM_H264_VIDEO_NAL_TYPE_UMASK_NUM;
    if ((nalType >= DRM_H264_VIDEO_START_NAL_TYPE) && (nalType <= DRM_H264_VIDEO_END_NAL_TYPE)) {
        return 0; // h264 frame found
    } else if ((nalType == 39) || (nalType == 6)) { // 39 or 6 is SEI nal unit tag
        if ((i + DRM_LEGACY_LEN + 1 < dataSize) &&
            (data[i + DRM_LEGACY_LEN + 1] == DRM_USER_DATA_UNREGISTERED_TAG)) {
            ceiStartPos = i;
        }
    }
    // UUID比对
    if (ceiStartPos != DRM_INVALID_START_POS) {
        DrmGetSyncHeaderIndex(data, dataSize, endPos);
        for (; (startPos + DRM_USER_DATA_REGISTERED_UUID_SIZE < endPos); startPos++) {
            if (memcmp(data + startPos, USER_REGISTERED_UUID, ...) == 0) { ceiStartPos = i; break; }
        }
    }
}
```

**E23** (codec_drm_decrypt.cpp L339-370): H.264 SEI 定位：NAL type 39 或 6（两个 NAL type 都可以是 SEI）；NAL type 用8-bit mask 直接提取（不同于 HEVC 的右移）；H.264 SEI 可以在 NAL type 6（supplemental enhancement information）中也携带。

---

## 14. MediaCodec DRM解密入口与AttachDrmBufffer

### 14.1 AttachDrmBufffer DRM缓冲区创建（media_codec.cpp L680-706）

```cpp
Status MediaCodec::AttachDrmBufffer(std::shared_ptr<AVBuffer> &drmInbuf, std::shared_ptr<AVBuffer> &drmOutbuf,
    uint32_t size)
{
    AVCODEC_LOGD("AttachDrmBufffer");
    std::shared_ptr<AVAllocator> avAllocator;
    avAllocator = AVAllocatorFactory::CreateSharedAllocator(MemoryFlag::MEMORY_READ_WRITE);
    CHECK_AND_RETURN_RET_LOG(avAllocator != nullptr, Status::ERROR_UNKNOWN, "avAllocator is nullptr");
    drmInbuf = AVBuffer::CreateAVBuffer(avAllocator, size);
    CHECK_AND_RETURN_RET_LOG(drmInbuf != nullptr, Status::ERROR_UNKNOWN, "drmInbuf is nullptr");
    drmInbuf->memory_->SetSize(size);
    drmOutbuf = AVBuffer::CreateAVBuffer(avAllocator, size);
    CHECK_AND_RETURN_RET_LOG(drmOutbuf != nullptr, Status::ERROR_UNKNOWN, "drmOutbuf is nullptr");
    drmOutbuf->memory_->SetSize(size);
    return Status::OK;
}
```

**E24** (media_codec.cpp L680-706): AttachDrmBufffer 为 DRM 解密分配双 AVBuffer（drmInbuf/drmOutbuf）；使用 AVAllocatorFactory::CreateSharedAllocator 创建读写内存；两缓冲区大小相同（size），用于加密输入/解密输出。

### 14.2 MediaCodec::DrmAudioCencDecrypt 音频DRM主入口（media_codec.cpp L707-720）

```cpp
Status MediaCodec::DrmAudioCencDecrypt(std::shared_ptr<AVBuffer> &filledInputBuffer)
{
    AVCODEC_LOGD("DrmAudioCencDecrypt enter");
    uint32_t bufSize = static_cast<uint32_t>(filledInputBuffer->memory_->GetSize());
    std::shared_ptr<AVBuffer> drmInBuf, drmOutBuf;
    ret = AttachDrmBufffer(drmInBuf, drmOutBuf, bufSize);
    CHECK_AND_RETURN_RET_LOG(ret == Status::OK, Status::ERROR_UNKNOWN, "AttachDrmBufffer failed");
    ret = AttachDrmBufffer(drmInBuf, drmOutBuf, bufSize); // 再次调用（实际解密路径）
    ret = drmDecryptor_->DrmAudioCencDecrypt(drmInBuf, drmOutBuf, bufSize);
    // ... 将解密后的 drmOutBuf 内容复制回 filledInputBuffer
}
```

**E25** (media_codec.cpp L707-720): MediaCodec::DrmAudioCencDecrypt 是音频解密主入口；先 AttachDrmBufffer 创建 DRM缓冲区，再调用 drmDecryptor_->DrmAudioCencDecrypt；解密结果复制回原始缓冲区。Video 解密类似。
