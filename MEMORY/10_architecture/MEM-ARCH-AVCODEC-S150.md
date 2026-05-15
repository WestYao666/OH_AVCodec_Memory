# MEM-ARCH-AVCODEC-S150 (DRAFT → pending_approval)

## Metadata

- **Mem ID**: MEM-ARCH-AVCODEC-S150
- **Topic**: CodecDrmDecrypt CENC 解密引擎——H.264/H.265/AVS3 NAL单元解析与SEI密钥提取764行cpp全析
- **Component**: `services/drm_decryptor/`
- **Files**: `codec_drm_decrypt.h` (全量) + `codec_drm_decrypt.cpp` (764行)
- **Author**: Builder Agent
- **Created**: 2026-05-15
- **Status**: draft
- **Priority**: P1

## 1. 概述

`CodecDrmDecrypt` 是 OpenHarmony AVCodec 的 DRM CENC（Common Encryption）解密引擎，负责对 H.264/H.265/AVS3 加密视频流和音频流进行实时解密。源文件位于 `services/drm_decryptor/codec_drm_decrypt.cpp`（764行）和同目录 `.h`（约180行）。

### 1.1 核心入口函数

| 函数 | 用途 | 代码位置 |
|------|------|---------|
| `DrmVideoCencDecrypt` | 视频 CENC 解密主入口 | cpp:537-579 |
| `DrmAudioCencDecrypt` | 音频 CENC 解密主入口 | cpp:580-615 |
| `DecryptMediaData` | 调用 DRM 解密模块 | cpp:714-735 |
| `SetDrmBuffer` | 填充 CryptInfo 并发起 RPC | cpp:671-711 |

### 1.2 支持的编解码器

```cpp
typedef enum {
    DRM_VIDEO_AVC = 0x1,   // H.264
    DRM_VIDEO_HEVC,         // H.265/HEVC
    DRM_VIDEO_AVS,          // AVS3
    DRM_VIDEO_NONE,
} DRM_CodecType;           // cpp:68
```

## 2. 常量定义（cpp:22-53）

```cpp
#define DRM_VIDEO_FRAME_ARR_LEN            3
#define DRM_AMBIGUITY_ARR_LEN              3
constexpr uint32_t DRM_LEGACY_LEN = 3;                     // 起始码 0x00 00 01
constexpr uint32_t DRM_AES_BLOCK_SIZE = 16;
constexpr uint8_t  DRM_AMBIGUITY_START_NUM = 0x00;
constexpr uint8_t  DRM_AMBIGUITY_END_NUM = 0x03;
constexpr uint32_t DRM_CRYPT_BYTE_BLOCK = 1;               // AES CBC 加密块数
constexpr uint32_t DRM_SKIP_BYTE_BLOCK = 9;                // AES CBC 跳过块数
constexpr uint32_t DRM_H264_VIDEO_SKIP_BYTES = 35;         // 32字节起始码 + 3字节
constexpr uint32_t DRM_H265_VIDEO_SKIP_BYTES = 68;         // 65字节起始码 + 3字节
constexpr uint32_t DRM_AVS3_VIDEO_SKIP_BYTES = 4;         // 1字节 + 3字节
constexpr uint32_t DRM_MAX_STREAM_DATA_SIZE = 20971520;    // 20MB 上限
static const uint8_t VIDEO_FRAME_ARR[DRM_VIDEO_FRAME_ARR_LEN] = { 0x00, 0x00, 0x01 };
static const uint8_t AMBIGUITY_ARR[DRM_AMBIGUITY_ARR_LEN] = { 0x00, 0x00, 0x03 };
```

## 3. SvpMode 三段式标志体系（h:55-62）

```cpp
enum SvpMode : int32_t {
    SVP_CLEAR = -1,  // 非加密视频
    SVP_FALSE,       // 加密但不需要安全解码器
    SVP_TRUE,        // 加密且需要安全解码器
};
```

由 `SetDecryptionConfig`（cpp:617-628）根据安全视频播放标志设置。

## 4. NAL 单元解析三步函数

### 4.1 DrmGetNalTypeAndIndex（cpp:73-103）

在 bitstream 中搜索 `0x00 00 01` 起始码，返回 NAL type 和位置索引。

```cpp
// H.264 NAL type mask: 0x1f（5位）
nalType = data[i + 3] & 0x1f;
// H.265 NAL type mask: 0x3f（6位，右移1位）
nalType = (data[i + 3] >> 1) & 0x3f;
// AVS3: NAL type = data[i + 3]，type=0 为有效帧
```

### 4.2 DrmGetSyncHeaderIndex（cpp:105-119）

找同步头位置（0x00 00 01），供 `DrmGetFinalNalTypeAndIndex` 使用。

### 4.3 DrmGetFinalNalTypeAndIndex（cpp:121-147）

核心函数：在 skipBytes 之后寻找第一个加密 NAL 单元的起止位置。

```cpp
// 流程（cpp:121-147）：
// 1. DrmGetSkipClearBytes() 获取 skipBytes（codec 决定起始码长度）
// 2. while(1) 循环搜索 NAL 单元
// 3. 找到 NAL 后判断：posEndIndex > posStartIndex + skipBytes + AES_BLOCK_SIZE
//    若是则找到有效加密NAL；否则继续找下一个
// 返回：nalType, posStartIndex（NAL开始）, posEndIndex（下一NAL开始）
```

## 5. 歧义字节去除 DrmRemoveAmbiguityBytes（cpp:149-171）

CENC 规范在加密区前插入防歧义字节 `0x00 00 03 XX`（XX ∈ [0x00, 0x03]），解密前必须去除：

```cpp
// 遍历数据，发现 0x00 00 03 Xn 模式时：
memmove_s(data + i + 2, ... , data + i + 3, ...);  // 去掉 0x03
```

## 6. CENC Info 提取链路

### 6.1 DrmGetCencInfo（cpp:516-535）

从 AVBuffer 的 meta 中读取 `Tag::DRM_CENC_INFO`，若无则视为明文。

```cpp
bool res = inBuf->meta_->GetData(Media::Tag::DRM_CENC_INFO, drmCencVec);
```

### 6.2 DrmSetKeyInfo（cpp:493-514）

在 CEI（Content Encryption Information）NAL 单元中解析密钥信息：

```cpp
// 1. DrmFindEncryptionFlagPos：定位加密标志位（跳过起始码）
// 2. 从 ceiStartPos 开始解析：
//    - encryptionFlag（bit7）：是否加密
//    - nextKeyIdFlag（bit6）：是否有下一个KeyId
//    - drmDescriptorFlag（bit5）：是否有DRM描述符
//    - drmNotAmbiguityFlag（bit4）：是否无歧义
```

### 6.3 DrmGetKeyId / DrmGetKeyIv（cpp:430-480）

```cpp
// KeyId：固定 META_DRM_KEY_ID_SIZE 字节（通常16字节）
memcpy_s(cencInfo->keyId, META_DRM_KEY_ID_SIZE, data + offset, META_DRM_KEY_ID_SIZE);
// IV：变长（1字节长度 + N字节IV）
uint32_t ivLen = data[offset];  // cpp:455
```

### 6.4 SetDrmAlgoAndBlocks（cpp:269-288）

从 DRM descriptor algo 字段设置加密算法：

| algo 值 | 算法 | 加密块 | 跳过块 |
|---------|------|--------|--------|
| 0x0 | `META_DRM_ALG_CENC_UNENCRYPTED` | 0 | 0 |
| 0x1 | `META_DRM_ALG_CENC_SM4_CBC` | 1 | 9 |
| 0x2 | `META_DRM_ALG_CENC_AES_CBC` | 1 | 9 |
| 0x3 | `META_DRM_ALG_CENC_SM4_CBC` | 0 | 0 |
| 0x5 | `META_DRM_ALG_CENC_AES_CBC` | 0 | 0 |

### 6.5 DrmModifyCencInfo（cpp:225-267）

根据 NAL 位置计算 `clearHeaderLen` 和 `payLoadLen`：

```cpp
uint32_t clearHeaderLen = posStartIndex + skipBytes;  // 明文头部长度
uint32_t payLoadLen = posEndIndex - clearHeaderLen - delLen;  // 加密负载
// AES CBC 块对齐：payLoadLen - (payLoadLen % 16)
// 剩余部分（<16字节）归入第二个 subSample（明文尾部）
```

## 7. 视频解密主流程 DrmVideoCencDecrypt（cpp:537-579）

```cpp
// 1. GetCodingType() 从 codecName 推断编解码类型（AVC/HEVC/AVS）
// 2. 从 inBuf->meta 读取 DRM_CENC_INFO
//    - 若 algo==UNENCRYPTED：subSampleNum=1，clearHeaderLen=dataSize
//    - 若无 meta：构造全明文 cencInfo
// 3. 若 cencInfo->mode==KEY_IV_SUBSAMPLES_NOT_SET：
//    - DrmGetCencInfo：提取SEI中的密钥信息
//    - DrmModifyCencInfo：计算subSample
//    - subSampleNum 固定为 DRM_TS_SUB_SAMPLE_NUM(2)
// 4. DecryptMediaData：实际解密
```

## 8. 音频解密主流程 DrmAudioCencDecrypt（cpp:580-615）

与视频类似但更简洁：
- 无需 NAL 解析，直接从 `DRM_CENC_INFO` meta 读取
- 若 `subSampleNum==0`，根据算法类型自动补全：
  - CTR 类：subSampleNum=1，payLoadLen=dataSize
  - CBC 类：subSampleNum=2，尾部不满16字节归入第二子样

## 9. 解密 RPC 调用链（cpp:671-735）

```cpp
// SetDrmBuffer（cpp:671-711）:
// 1. 填充 DrmBuffer（in/out）：memoryType, fd, bufferLen, filledLen, offset
// 2. 构造 CryptInfo：algo, keyId, iv, pattern(encryptBlocks/skipBlocks), subSamples
// 3. decryptModuleProxy_->DecryptMediaData(svpFlag_, cryptInfo, inDrmBuffer, outDrmBuffer)

// DecryptMediaData（cpp:714-735）:
// 1. 参数校验（keyIdLen<=META_DRM_KEY_ID_SIZE, subSampleNum<=META_DRM_MAX_SUB_SAMPLE_NUM）
// 2. 调用 SetDrmBuffer
// 3. 返回 AVCS_ERR_OK 或错误码
```

## 10. SEI 解析三Codec特化（cpp:290-370）

### 10.1 DrmFindCeiNalUnit（cpp:364-375）

根据 `codingType_` 分发到对应 codec 的解析函数。

### 10.2 H.264 SEI 解析 DrmFindH264CeiNalUnit（cpp:346-362）

- NAL type 39（SEI）或 6（user_data_unregistered）
- payload_type_offset = 5（跳过nal_header）
- 判断 UUID（16字节）是否为 `USER_REGISTERED_UUID`

### 10.3 H.265 SEI 解析 DrmFindHevcCeiNalUnit（cpp:323-343）

- NAL type 39（保留），payload_type_offset = 5
- `nalType >> 1 & 0x3f` 提取（因为HEVC NAL头格式不同）

### 10.4 AVS3 SEI 解析 DrmFindAvsCeiNalUnit（cpp:290-321）

- `0xb5` 是 video_extension 标记，`0xd0` 是 extension_user_data 标记
- 在 `sequence_header` 之后第一个 `extension_and_user_data` 中找 CEI

## 11. 与已有记忆的关系

| 已有记忆 | 关联点 |
|---------|--------|
| S17（SmartFluencyDecoding） | 仅提到 `drmDecryptor_` 成员存在 |
| S46（DecoderSurfaceFilter DRM） | 仅提到 DRM 路径，未深入解密细节 |
| S63（ContentProtection） | 提到 SVP/DRM 场景，未覆盖 CodecDrmDecrypt 实现 |
| S129（CodecServer + PostProcessing） | 提到 PostProcessing 集成 VPE/DRM，未展开 |

**本文档（S150）**：首次对 `codec_drm_decrypt.cpp`（764行）逐函数分析。

## 12. 证据行号索引

| 证据项 | 位置 |
|--------|------|
| SvpMode 枚举 | h:55-62 |
| DrmVideoCencDecrypt | cpp:537-579 |
| DrmAudioCencDecrypt | cpp:580-615 |
| SetDecryptionConfig | cpp:617-628 |
| DrmGetNalTypeAndIndex | cpp:73-103 |
| DrmGetFinalNalTypeAndIndex | cpp:121-147 |
| DrmRemoveAmbiguityBytes | cpp:149-171 |
| DrmModifyCencInfo | cpp:225-267 |
| SetDrmAlgoAndBlocks | cpp:269-288 |
| DrmFindCeiNalUnit | cpp:364-375 |
| DrmFindH264CeiNalUnit | cpp:346-362 |
| DrmFindHevcCeiNalUnit | cpp:323-343 |
| DrmFindAvsCeiNalUnit | cpp:290-321 |
| DrmGetCencInfo | cpp:516-535 |
| DrmSetKeyInfo | cpp:493-514 |
| DrmGetKeyId | cpp:430-451 |
| DrmGetKeyIv | cpp:453-471 |
| DecryptMediaData | cpp:714-735 |
| SetDrmBuffer | cpp:671-711 |
| DRM 算法常量 | cpp:22-53 |

## 13. 变更记录

- 2026-05-15: 初稿创建，基于 `codec_drm_decrypt.cpp`（764行）+ `codec_drm_decrypt.h` 全量源码