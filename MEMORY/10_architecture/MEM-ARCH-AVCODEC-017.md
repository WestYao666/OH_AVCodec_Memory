---
id: MEM-ARCH-AVCODEC-017
title: DRM CENC 解密流程——SVP 安全视频路径与 CodecDrmDecrypt 三层调用链
type: architecture_fact
scope: [AVCodec, DRM, CENC, ContentProtection, SecureVideoPath, SVP]
status: draft
confidence: medium
summary: >
  AVCodec 的 DRM 解密由 CodecDrmDecrypt 类处理，位于 services/drm_decryptor/ 目录，
  支持 AVC/H264、HEVC/H265、AVS 三种视频格式的 CENC (Common Encryption) 解密。
  集成路径：decoder_filter (isDrmProtected_/svpFlag_) → MediaCodec::SetDecryptConfig() → CodecDrmDecrypt::SetDecryptionConfig()
  → decryptModuleProxy_->DecryptMediaData(svpFlag_, cryptInfo, ...)。
  SvpMode 区分安全视频路径（SVP_TRUE，走 TEE 硬件）和普通路径（SVP_FALSE，走软件解密）。
  解密发生在 raw packet 层面，在送给硬件解码器之前完成解密。
why_it_matters:
 - 三方应用：使用 DRM 保护的 content（如 Netflix、Disney+）时，需理解解密发生在解码前
 - 新需求开发：接入 DRM 需调用 SetDecryptConfig() 并正确传递 keySession 和 svpFlag
 - 问题定位：DRM 解密失败（AVCS_ERR_DRM_DECRYPT_FAILED）需确认 svpFlag 与硬件能力匹配
 - 架构理解：CodecDrmDecrypt 是独立于 codec plugin 的公共服务，不属于任何 codec 实现
evidence:
 - kind: code
   ref: services/drm_decryptor/codec_drm_decrypt.h
   anchor: SvpMode 枚举 + 类声明
   note: |
     enum SvpMode : int32_t {
         SVP_CLEAR = -1,  /* 非保护视频 */
         SVP_FALSE,       /* 保护视频，但不需要安全解码器 */
         SVP_TRUE,        /* 保护视频，需要安全解码器（TEE 硬件）*/
     };
     int32_t DrmVideoCencDecrypt(std::shared_ptr<AVBuffer> &inBuf, std::shared_ptr<AVBuffer> &outBuf, uint32_t &dataSize);
     int32_t DrmAudioCencDecrypt(std::shared_ptr<AVBuffer> &inBuf, std::shared_ptr<AVBuffer> &outBuf, uint32_t &dataSize);
     void SetDecryptionConfig(const sptr<DrmStandard::IMediaKeySessionService> &keySession, const bool svpFlag);
 - kind: code
   ref: services/drm_decryptor/codec_drm_decrypt.cpp
   anchor: SetDecryptionConfig 实现
   note: |
     svpFlag (bool) → svpFlag_ (SvpMode enum: SVP_TRUE/SVP_FALSE)
     通过 keySession->GetMediaDecryptModule() 获取 decryptModuleProxy_
     META_DRM_CENC_INFO_KEY_IV_SUBSAMPLES_SET 模式支持
 - kind: code
   ref: services/drm_decryptor/codec_drm_decrypt.cpp
   anchor: DecryptMediaData → SetDrmBuffer → decryptModuleProxy_->DecryptMediaData
   note: |
     解密调用链：
     1. DecryptMediaData(cencInfo, inBuf, outBuf)  入口
     2. SetDrmBuffer() 将 AVBuffer 转 DrmBuffer，提取 keyId/IV/subsamples 到 cryptInfo
     3. decryptModuleProxy_->DecryptMediaData(svpFlag_, cryptInfo, inDrmBuffer, outDrmBuffer) 实际解密
 - kind: code
   ref: services/drm_decryptor/codec_drm_decrypt.cpp
   anchor: DRM_CodecType 枚举
   note: |
     typedef enum {
         DRM_VIDEO_AVC  = 0x1,  /* H.264/AVC */
         DRM_VIDEO_HEVC,         /* H.265/HEVC */
         DRM_VIDEO_AVS,          /* AVS3 */
         DRM_VIDEO_NONE,
     } DRM_CodecType;
 - kind: code
   ref: services/drm_decryptor/codec_drm_decrypt.cpp
   anchor: CENC 加密模式常量
   note: |
     DRM_CRYPT_BYTE_BLOCK = 1;   /* 加密块数 */
     DRM_SKIP_BYTE_BLOCK = 9;     /* 跳过块数 */
     DrmGetSkipClearBytes() 根据 codec 类型返回 skip bytes:
       AVC: 35 bytes, HEVC: 68 bytes, AVS: 4 bytes
 - kind: code
   ref: services/media_engine/modules/media_codec/media_codec.h
   anchor: drmDecryptor_ 成员
   note: std::shared_ptr<MediaAVCodec::CodecDrmDecrypt> drmDecryptor_; 是 MediaCodec 成员
 - kind: code
   ref: services/media_engine/filters/decoder_surface_filter.cpp
   anchor: svpFlag_ 配置路径
   note: |
     svpFlag_ 在 decoder_surface_filter 中设置（行 1350）：
       svpFlag_ = svp;
     通过 videoDecoder_->SetDecryptConfig(keySessionServiceProxy_, svpFlag_) 传递（行 405, 784）
 - kind: code
   ref: services/media_engine/modules/media_codec/media_codec.cpp
   anchor: DrmAudioCencDecrypt 在 HandleInputBufferInner 中调用
   note: |
     行 877-878: MediaAVCodec::AVCodecTrace trace("...-DrmAudioCencDecrypt");
     行 878: ret = DrmAudioCencDecrypt(filledInputBuffer);
     行 730: drmDecryptor_->DrmAudioCencDecrypt(drmInBuf, drmOutBuf, bufSize);
     解密在 HandleInputBufferInner 中被调用，处理加密输入 buffer
 - kind: build
   ref: services/drm_decryptor/codec_drm_decrypt.cpp
   anchor: SUPPORT_DRM 条件编译
   note: |
     #ifdef SUPPORT_DRM ... #else ... #endif
     不支持 DRM 时 SetAudioDecryptionConfig 直接返回 OK（空实现）
     SUPPORT_DRM 宏控制 DRM 功能编译
related:
 - MEM-ARCH-AVCODEC-001  (5大层：interfaces/media_engine/services/dfx/drm)
 - MEM-ARCH-AVCODEC-009  (硬件Codec区分：IsSecure() 判断是否支持DRM)
 - MEM-ARCH-AVCODEC-015  (错误处理：AVCS_ERR_DRM_DECRYPT_FAILED)
 - MEM-DEVFLOW-003      (DFX: avcodec_xcollie 看门狗)
owner: builder-agent
review:
  owner: 待指定
  submitted_at: "2026-04-19T23:20:00+08:00"
  change_policy: update_on_code_change
update_trigger: code_change
created_at: "2026-04-19T23:20:00+08:00"
updated_at: "2026-04-20T01:25:00+08:00"
source_repo: https://gitcode.com/openharmony/multimedia_av_codec
source_commit: local clone (OH_AVCodec)
notes: |
  GitCode HTML 页面被反爬保护拦截（返回 AtomGit 登录页），代码探索使用本地 clone。
  web_fetch 无法直接访问 GitCode 仓库页面，但本地 /home/west/OH_AVCodec 与 GitCode 同步。
  DRM 解密 topic 不在当前 backlog 中（P1-P5 未覆盖），作为新增发现记录。

---
## Evidence Validation via web_fetch (2026-04-20)

GitCode 主站被 AtomGit 登录墙拦截（https://gitcode.com/openharmony/multimedia_av_codec）。
通过 Gitee 官方镜像（https://gitee.com/openharmony/multimedia_av_codec）进行 web_fetch 验证：

### ✅ 验证 1: codec_drm_decrypt.h — SvpMode 枚举
- **URL**: https://gitee.com/openharmony/multimedia_av_codec/raw/master/services/drm_decryptor/codec_drm_decrypt.h
- **状态**: ✅ 完全匹配
- **关键片段**:
  ```cpp
  enum SvpMode : int32_t {
      SVP_CLEAR = -1, /* it's not a protection video */
      SVP_FALSE, /* it's a protection video but not need secure decoder */
      SVP_TRUE, /* it's a protection video and need secure decoder */
  };
  class CodecDrmDecrypt {
  public:
      int32_t DrmVideoCencDecrypt(std::shared_ptr<AVBuffer> &inBuf, ...);
      int32_t DrmAudioCencDecrypt(std::shared_ptr<AVBuffer> &inBuf, ...);
      void SetDecryptionConfig(const sptr<DrmStandard::IMediaKeySessionService> &keySession, const bool svpFlag);
  private:
      int32_t svpFlag_ = SVP_CLEAR;
  };
  ```

### ✅ 验证 2: media_codec.h — MediaCodec DRM 集成
- **URL**: https://gitee.com/openharmony/multimedia_av_codec/raw/master/services/media_engine/modules/media_codec/media_codec.h
- **状态**: ✅ 完全匹配（MediaCodec 类包含 DRM 相关成员）
- **关键片段**:
  ```cpp
  enum class CodecErrorType : int32_t {
      CODEC_ERROR_INTERNAL,
      CODEC_DRM_DECRYTION_FAILED,  // 注意：头文件中拼写为 DECRYTION（非 DECRYPT）
      CODEC_ERROR_EXTEND_START = 0X10000,
  };
  class MediaCodec {
  public:
      int32_t SetAudioDecryptionConfig(const sptr<DrmStandard::IMediaKeySessionService> &keySession, const bool svpFlag);
  private:
      Status DrmAudioCencDecrypt(std::shared_ptr<AVBuffer> &filledInputBuffer);
  };
  ```
  ⚠️ 发现：头文件中错误码枚举为 `CODEC_DRM_DECRYTION_FAILED`（少一个 T），
  而 MEM-ARCH-AVCODEC-015 中使用 `AVCS_ERR_DRM_DECRYPT_FAILED` —— 需确认哪个是实际错误码。

### ✅ 验证 3: native_cencinfo.h — CENC API 常量
- **URL**: https://gitee.com/openharmony/multimedia_av_codec/raw/master/interfaces/kits/c/native_cencinfo.h
- **状态**: ✅ 完全匹配
- **关键常量**:
  ```c
  #define DRM_KEY_ID_SIZE 16
  #define DRM_KEY_IV_SIZE 16
  #define DRM_KEY_MAX_SUB_SAMPLE_NUM 64
  typedef enum DrmCencAlgorithm {
      DRM_ALG_CENC_UNENCRYPTED = 0x0,
      DRM_ALG_CENC_AES_CTR = 0x1,
      DRM_ALG_CENC_AES_WV = 0x2,
      DRM_ALG_CENC_AES_CBC = 0x3,
      DRM_ALG_CENC_SM4_CBC = 0x4,
      DRM_ALG_CENC_SM4_CTR = 0x5
  } DrmCencAlgorithm;
  typedef struct DrmSubsample {
      uint32_t clearHeaderLen;
      uint32_t payLoadLen;
  } DrmSubsample;
  ```

### 发现的问题

| 问题 | 影响 | 建议 |
|------|------|------|
| `CODEC_DRM_DECRYTION_FAILED` vs `AVCS_ERR_DRM_DECRYPT_FAILED` 拼写不一致 | 低：两者都可能存在，需确认错误码映射表 | 在 MEM-ARCH-AVCODEC-015 中注明差异 |
| GitCode 无法直接访问 | 中：无法通过 GitCode 验证最新提交 | 建议维护者使用 Gitee 镜像作为主要验证源 |
---

## 1. DRM 解密模块定位

DRM 解密是 AVCodec 处理 **受保护内容（DRM-encrypted content）** 的能力，不是编解码本身。
它位于 `services/drm_decryptor/` 目录，是独立于 media_codec plugin 的公共服务。

### 三层调用链（完整视图）

```
Layer 1 — 应用层配置
  Player / MediaFramework
    decoder_surface_filter.cpp（行 1349-1350）:
      isDrmProtected_ = true
      svpFlag_ = svp
    audio_decoder_filter.cpp（行 435）:
      decoder_->SetAudioDecryptionConfig(keySessionServiceProxy_, svpFlag_)

Layer 2 — DRM 框架层（CodecDrmDecrypt）
  video path:
    decoder_filter → videoDecoder_->SetDecryptConfig()
      → VideoDecoderAdapter::SetDecryptConfig()（行 551）
        → MediaCodec::SetDecryptConfig()（行 904，调用 drmDecryptor_->SetDecryptionConfig()）
          → CodecDrmDecrypt::SetDecryptionConfig()（行 661）
            → keySessionServiceProxy_->GetMediaDecryptModule(decryptModuleProxy_)（行 675）
  audio path:
    MediaCodec::HandleInputBufferInner()（行 878） → DrmAudioCencDecrypt()
      → CodecDrmDecrypt::DrmAudioCencDecrypt()（行 604）

Layer 3 — 解密执行层
  CodecDrmDecrypt::DecryptMediaData()（行 739）
    → CodecDrmDecrypt::SetDrmBuffer()（行 684）  提取 keyId/IV/subsamples → cryptInfo
      → decryptModuleProxy_->DecryptMediaData(svpFlag_, cryptInfo, inDrmBuffer, outDrmBuffer)
        → TEE 硬件（svpFlag_==SVP_TRUE）或软件/普通TEE（svpFlag_==SVP_FALSE）
```

## 2. SvpMode 三态与安全视频路径（SVP）

| SvpMode | 值 | 含义 | 解密路径 |
|---------|-----|------|----------|
| `SVP_CLEAR` | -1 | 非保护视频 | 无需解密 |
| `SVP_FALSE` | 0 | 保护视频，普通解码器 | 软件解密或普通 TEE 解密 |
| `SVP_TRUE` | 1 | 保护视频，安全解码器 | TEE 硬件安全视频路径（Secure Video Path，SVP） |

**SVP 安全视频路径**：当 `svpFlag=true` 时，内容走 TEE（Trusted Execution Environment）硬件解密，
解密后的明文数据直接送入安全硬件解码器，全程明文不经过普通内存（non-secure memory）。
`SVP_TRUE` 要求设备具备安全显示硬件（Secure Display）和 TEE 支持。
不支持 SVP 的设备使用 `SVP_FALSE` 或 `SVP_CLEAR`。

`svpFlag` (bool) → `SetDecryptionConfig` → `svpFlag_` (SvpMode enum)

## 3. CENC 加密算法支持

CodecDrmDecrypt 通过 `SetDrmAlgoAndBlocks()`（行 256）设置算法，
支持的 CENC 算法（`DrmCencAlgorithm`，定义于 `interfaces/kits/c/native_cencinfo.h`）：

| 算法 | 值 | 加密模式 | Pattern（encryptBlocks/skipBlocks） | 备注 |
|------|---|---------|--------------------------------------|------|
| `DRM_ALG_CENC_UNENCRYPTED` | 0x0 | 不加密 | — | 透传 |
| `DRM_ALG_CENC_AES_CTR` | 0x1 | AES-CTR | 1/9 | 常用 |
| `DRM_ALG_CENC_AES_WV` | 0x2 | AES-WV（Widevine） | — | Widevine 专用 |
| `DRM_ALG_CENC_AES_CBC` | 0x3 | AES-CBC | 1/9 | 常用 |
| `DRM_ALG_CENC_SM4_CBC` | 0x4 | SM4-CBC | 1/9 | 中国国密 |
| `DRM_ALG_CENC_SM4_CTR` | 0x5 | SM4-CTR | — | 中国国密 |

**Pattern 1/9**（`DRM_CRYPT_BYTE_BLOCK=1`，`DRM_SKIP_BYTE_BLOCK=9`）：
每 10 个 AES block（160 bytes）中，第 1 个 block 加密，后续 9 个 block 跳过（不加密），
这是 CENC 标准的 `pattern` 模式（`AES-CBC` 模式下的 `subsample` 变体）。

## 4. CENC 数据结构与常量

**CENC Metadata 从 AVBuffer 中提取**（通过 `DrmGetCencInfo`/`DrmGetKeyId`/`DrmGetKeyIv`）：

| 常量 | 值 | 说明 |
|------|---|------|
| `DRM_KEY_ID_SIZE` | 16 bytes | keyId 固定长度 |
| `DRM_KEY_IV_SIZE` | 16 bytes | IV 固定长度（AES block size） |
| `DRM_KEY_MAX_SUB_SAMPLE_NUM` | 64 | 最大 subsample 数量 |
| `DRM_MAX_STREAM_DATA_SIZE` | 20 MB | 最大单帧数据量（20971520 bytes） |
| `DRM_AES_BLOCK_SIZE` | 16 bytes | AES block 大小 |

**DrmSubsample 结构**（`native_cencinfo.h`）：
```cpp
struct DrmSubsample {
    uint32_t clearHeaderLen;  // NAL header 不加密部分长度
    uint32_t payLoadLen;       // 加密部分长度
};
```

**CryptInfo 结构**（传给 `decryptModuleProxy_->DecryptMediaData`）：
- `keyId[keyIdLen]`
- `iv[ivLen]`
- `pattern`（encryptBlocks, skipBlocks）
- `subSample`（vector of DrmSubsample）

## 5. 支持的 Codec 格式与 Skip Bytes

CodecDrmDecrypt 通过 `codingType_` 成员区分不同 codec 的 NAL 单元结构，
用于确定 NAL header 不加密部分（`clearHeaderLen`）：

| Codec | DRM_CodecType | Skip Bytes 计算 | NAL 起始码 |
|-------|--------------|----------------|-----------|
| H.264/AVC | `DRM_VIDEO_AVC` | 35 = (32+3) bytes | `00 00 01` |
| H.265/HEVC | `DRM_VIDEO_HEVC` | 68 = (65+3) bytes | `00 00 01` |
| AVS3 | `DRM_VIDEO_AVS` | 4 = (1+3) bytes | `00 00 01` |

NAL header 中的 SEI NAL 单元需要特殊处理（`DrmFindCeiNalUnit` 系列函数），
因为 SEI 可能包含 DRM metadata 但不影响视频解码。

## 6. DRM 与 Codec Plugin 的关系

- CodecDrmDecrypt **不属于** 任何 codec plugin（不是 `codec_plugin.h` 实现）
- 它是 MediaCodec 类的一个 **成员对象**（`drmDecryptor_`，`media_codec.h` 行 219）
- 音频解密发生在 MediaCodec 处理 **输入 buffer** 时（`HandleInputBufferInner`，行 878）
- 视频解密由 codec plugin 直接调用 `CodecDrmDecrypt::DrmVideoCencDecrypt()`
- 解密完成后，明文数据才送入 plugin 层进行实际解码

## 7. 问题定位提示

| 现象 | 可能原因 | 排查方向 |
|------|---------|---------|
| `AVCS_ERR_DRM_DECRYPT_FAILED` | svpFlag 与硬件能力不匹配 | 确认设备是否支持 `SVP_TRUE` |
| 解密后画面花屏 | keyId/IV 不匹配 | 检查 DRM key session 状态（是否过期/被撤销） |
| 保护内容无法播放 | svpFlag 未设置 | 确认 `decoder_filter` 是否调用了 `SetDecryptConfig` |
| 不支持 DRM 的设备报错 | `SUPPORT_DRM` 未定义 | 确认系统是否编译了 DRM 支持 |
| 音频解密失败 | `DrmAudioCencDecrypt` 返回非 0 | 检查 `HandleInputBufferInner` 是否正确调用了 DRM 路径 |
