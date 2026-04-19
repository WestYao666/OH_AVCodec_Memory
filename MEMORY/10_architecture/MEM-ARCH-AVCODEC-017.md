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
updated_at: "2026-04-19T23:20:00+08:00"
source_repo: https://gitcode.com/openharmony/multimedia_av_codec
source_commit: local clone (OH_AVCodec)
notes: |
  GitCode HTML 页面被反爬保护拦截（返回 AtomGit 登录页），代码探索使用本地 clone。
  web_fetch 无法直接访问 GitCode 仓库页面，但本地 /home/west/OH_AVCodec 与 GitCode 同步。
  DRM 解密 topic 不在当前 backlog 中（P1-P5 未覆盖），作为新增发现记录。
---

## 1. DRM 解密模块定位

DRM 解密是 AVCodec 处理 **受保护内容（DRM-encrypted content）** 的能力，不是编解码本身。
它位于 `services/drm_decryptor/` 目录，是独立于 media_codec plugin 的公共服务。

```
应用层（Player/MediaFramework）
  └── decoder_filter（设置 svpFlag_ 和 keySession）
        └── MediaCodec::SetDecryptConfig(keySession, svpFlag)
              └── CodecDrmDecrypt::SetDecryptionConfig()
                    └── decryptModuleProxy_->DecryptMediaData()
                          └── TEE 硬件 / 软件解密
```

## 2. SvpMode 三态

| SvpMode | 值 | 含义 | 解密路径 |
|---------|-----|------|---------|
| `SVP_CLEAR` | -1 | 非保护视频 | 无需解密 |
| `SVP_FALSE` | 0 | 保护视频，普通解码器 | 软件解密或普通 TEE 解密 |
| `SVP_TRUE` | 1 | 保护视频，安全解码器 | TEE 硬件安全视频路径 |

`svpFlag` (bool) → `SetDecryptionConfig` → `svpFlag_` (SvpMode enum)

## 3. CENC 解密调用链

```
输入：加密 AVBuffer（包含 CENC metadata: keyId, IV, subsamples）
  ↓
CodecDrmDecrypt::DecryptMediaData(cencInfo, inBuf, outBuf)
  ↓
CodecDrmDecrypt::SetDrmBuffer()     —— 转换 AVBuffer → DrmBuffer
  ↓                                 提取 cryptInfo: keyId, IV, pattern, subSamples
decryptModuleProxy_->DecryptMediaData(svpFlag_, cryptInfo, inDrmBuffer, outDrmBuffer)
  ↓
输出：解密后 AVBuffer（送给解码器）
```

## 4. 支持的 Codec 格式

CodecDrmDecrypt 通过 `codingType_` 成员区分不同 codec 的 NAL 单元结构：

| Codec | DRM_CodecType | Skip Bytes | NAL 起始码 |
|-------|--------------|-----------|-----------|
| H.264/AVC | `DRM_VIDEO_AVC` | 35 bytes | 00 00 01 |
| H.265/HEVC | `DRM_VIDEO_HEVC` | 68 bytes | 00 00 01 |
| AVS3 | `DRM_VIDEO_AVS` | 4 bytes | 00 00 01 |

## 5. DRM 与 Codec Plugin 的关系

- CodecDrmDecrypt **不属于** 任何 codec plugin（不是 codec_plugin.h 实现）
- 它是 MediaCodec 类的一个 **成员对象** (`drmDecryptor_`)
- 解密发生在 MediaCodec 处理 **输入 buffer** 时（HandleInputBufferInner）
- 解密完成后，清明数据才送入 plugin 层进行实际解码

## 6. 问题定位提示

| 现象 | 可能原因 | 排查方向 |
|------|---------|---------|
| AVCS_ERR_DRM_DECRYPT_FAILED | svpFlag 与硬件能力不匹配 | 确认设备是否支持 SVP_TRUE |
| 解密后画面花屏 | keyId/IV 不匹配 | 检查 DRM key session 状态 |
| 保护内容无法播放 | svpFlag 未设置 | 确认 decoder_filter 是否调用了 SetDecryptConfig |
| 不支持 DRM 的设备报错 | SUPPORT_DRM 未定义 | 确认系统是否编译了 DRM 支持 |
