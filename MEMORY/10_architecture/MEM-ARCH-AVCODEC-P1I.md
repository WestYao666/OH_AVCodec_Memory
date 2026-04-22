id: MEM-ARCH-AVCODEC-P1I
title: DRM CENC 解密流程——SVP 安全视频路径与 CodecDrmDecrypt 三层调用链
type: architecture_fact
scope: [AVCodec, DRM, CENC, ContentProtection, SVP]
status: draft
confidence: high
summary: >
  OpenHarmony AVCodec 模块中，DRM CENC 加密内容的解密通过 CodecDrmDecrypt 类实现，
  分为三层调用链：① Filter 层（DecoderSurfaceFilter）根据 DRM protected 标志和 svpFlag 决定
  是否创建 secure decoder；② MediaCodec 层通过 SetDecryptConfig 注入 keySession 和 SVP 配置，
  初始化 CodecDrmDecrypt；③ CodecDrmDecrypt 层解析 CENC 加密信息（Key ID、IV、Algorithm、SubSample）
  并通过 DRM plugin 的 DecryptMediaData 完成 AES-CBC/CTR 或 SM4-CBC 解密。
  SVP（Secure Video Path）通过 svpFlag 区分两种模式：SVP_FALSE（普通解密，仅 DRM 解密），
  SVP_TRUE（安全路径，需使用 .secure 后缀的硬件 decoder）。
why_it_matters:
 - 三方应用定位接入点：SetDecryptConfig 是配置 DRM 解密的唯一入口
 - 新需求开发：新增 DRM 算法支持需在 SetDrmAlgoAndBlocks 中扩展
 - 问题定位：svpFlag 与 secure decoder 命名一致性检查（CheckDrmSvpConsistency）是排查 DRM 失败的关键路径
 - SVP 安全路径与普通路径的区分决定了解密是否经过安全硬件
evidence:
 - kind: code
   ref: services/drm_decryptor/codec_drm_decrypt.h
   anchor: 类定义
   note: CodecDrmDecrypt 类定义，包含 DrmVideoCencDecrypt/DrmAudioCencDecrypt/SetDecryptionConfig 关键方法
 - kind: code
   ref: services/drm_decryptor/codec_drm_decrypt.cpp
   anchor: 解密实现
   note: DrmVideoCencDecrypt/DrmAudioCencDecrypt 解析 CENC info 并调用 DecryptMediaData
 - kind: code
   ref: services/media_engine/modules/media_codec/media_codec.cpp
   anchor: SetDecryptConfig
   note: SetDecryptConfig 调用 drmDecryptor_->SetDecryptionConfig(keySession, svpFlag)
 - kind: code
   ref: services/media_engine/filters/decoder_surface_filter.cpp
   anchor: SVP 安全路径选择逻辑
   note: isDrmProtected_ && svpFlag_ 时创建 secure decoder（codecName + ".secure"）
 - kind: code
   ref: services/media_engine/filters/decoder_surface_filter.cpp
   anchor: SetDecryptConfig
   note: SetDecryptConfig 设置 isDrmProtected_=true 和 svpFlag_
 - kind: code
   ref: services/services/codec/server/video/codec_server.cpp
   anchor: CheckDrmSvpConsistency
   note: svpFlag 与 secure decoder 命名一致性校验，svpFlag=true 但 decoder 无 .secure 后缀时报错
 - kind: code
   ref: services/drm_decryptor/codec_drm_decrypt.cpp
   anchor: SetDrmAlgoAndBlocks
   note: CENC 算法映射：algo=0x1→SM4-CBC，algo=0x2→AES-CBCS，algo=0x5→AES-CBC1，algo=0x3→SM4-CBC(flat)，algo=0x0→UNENCRYPTED
 - kind: code
   ref: services/media_engine/modules/media_codec/media_codec.cpp
   anchor: DrmAudioCencDecrypt
   note: 音频解密流程：分配 drm buffer → memcpy 输入数据 → CodecDrmDecrypt 解密 → memcpy 输出数据
 - kind: code
   ref: services/media_engine/modules/media_codec/media_codec.cpp
   anchor: DrmVideoCencDecrypt
   note: 视频解密流程：从 inBuf.meta_ 提取 DRM_CENC_INFO，解析 NAL/SEI/SubSample 结构
related:
 - MEM-ARCH-AVCODEC-001
 - MEM-ARCH-AVCODEC-002
 - MEM-ARCH-AVCODEC-006
owner: 耀耀
review:
  owner: 耀耀
  change_policy: update_on_code_change
update_trigger: code_change
created_at: "2026-04-22"
updated_at: "2026-04-22"
---

## 背景与问题

### 为什么需要 DRM CENC 解密

在数字版权管理（DRM）场景下，视频内容通常以 CENC（Common Encryption）格式加密分发。
解密后的裸码流不得经由普通路径传输，必须在 TEE（Trusted Execution Environment）或
安全硬件中完成解密，再送给硬件解码器。这个完整路径称为 **SVP（Secure Video Path）**。

AVCodec 模块需要处理两类 DRM 场景：
1. **普通 DRM 解密（SVP_FALSE）**：解密在普通内存中进行，适合软件解码或非高安全级别内容
2. **安全视频路径（SVP_TRUE）**：解密在安全环境中完成，必须使用带 `.secure` 后缀的硬件 decoder

### 核心问题
- CENC 加密信息（Key ID、IV、Algorithm、SubSample 结构）如何从码流/元数据中提取？
- SVP 标志如何决定 decoder 类型和内存路径？
- 三层调用链（Filter → MediaCodec → CodecDrmDecrypt）的数据流和接口契约是什么？

---

## 关键代码路径

### 第一层：Filter 层（入口 + SVP 路径决策）

**文件**: `services/media_engine/filters/decoder_surface_filter.cpp`

```cpp
// DoInitAfterLink() 中，SVP 安全路径决策：
if (isDrmProtected_ && svpFlag_) {
    std::string baseName = GetCodecName(codecMimeType_);
    std::string secureDecoderName = baseName + ".secure";  // 追加 .secure 后缀
    ret = videoDecoder_->Init(MediaAVCodec::AVCodecType::AVCODEC_TYPE_VIDEO_DECODER,
                              false, secureDecoderName);  // 使用安全硬件 decoder
}

// SetDecryptConfig 配置解密会话
Status DecoderSurfaceFilter::SetDecryptConfig(keySessionProxy, svp) {
    isDrmProtected_ = true;
    svpFlag_ = svp;
    keySessionServiceProxy_ = keySessionProxy;
}
```

**SVP 三态枚举**（定义在 `codec_drm_decrypt.h`）:
```cpp
enum SvpMode : int32_t {
    SVP_CLEAR = -1,  // 非保护视频
    SVP_FALSE,       // 保护视频，但不需要安全 decoder
    SVP_TRUE,        // 保护视频，需要安全 decoder
};
```

### 第二层：MediaCodec 层（会话注入 + 加解密调度）

**文件**: `services/media_engine/modules/media_codec/media_codec.cpp`

```cpp
// SetDecryptConfig 注入 DRM 会话
int32_t MediaCodec::SetDecryptConfig(keySession, svpFlag) {
    if (drmDecryptor_ == nullptr) {
        drmDecryptor_ = std::make_shared<CodecDrmDecrypt>();
    }
    drmDecryptor_->SetDecryptionConfig(keySession, svpFlag);  // 传递给 DRM plugin
}

// HandleInputBufferInner 中，对音频 buffer 执行 CENC 解密
if (drmDecryptor_ != nullptr) {
    ret = DrmAudioCencDecrypt(filledInputBuffer);  // 音频解密
}

// DrmAudioCencDecrypt 流程：
// 1. AttachDrmBufffer() 分配临时的加解密 buffer 对
// 2. memcpy_s 输入数据到 drmInBuf
// 3. drmDecryptor_->DrmAudioCencDecrypt(drmInBuf, drmOutBuf, bufSize)
// 4. memcpy_s 解密数据从 drmOutBuf 回到 filledInputBuffer
```

### 第三层：CodecDrmDecrypt 层（实际解密逻辑）

**文件**: `services/drm_decryptor/codec_drm_decrypt.cpp`

#### 视频解密 `DrmVideoCencDecrypt`

```
DrmVideoCencDecrypt(inBuf, outBuf, dataSize)
  ├── inBuf.meta_->GetData(Tag::DRM_CENC_INFO)     // 从元数据获取加密信息
  ├── DrmGetCencInfo()                              // 解析 SEI 中的 CENC info（Key ID/IV/Algorithm）
  ├── DrmModifyCencInfo()                          // 计算 SubSample 结构（clear + encrypted 分段）
  ├── DecryptMediaData(cencInfo, inBuf, outBuf)    // 调用 DRM plugin 执行解密
  │     └── SetDrmBuffer()                         // 构建 DrmBuffer + CryptInfo
  │         └── decryptModuleProxy_->DecryptMediaData(svpFlag, cryptInfo, inDrm, outDrm)
  └── SetDrmAlgoAndBlocks(algo, cencInfo)          // 算法映射表
        algo=0x1 → SM4-CBC, encryptBlocks=1, skipBlocks=9
        algo=0x2 → AES-CBCS, encryptBlocks=1, skipBlocks=9
        algo=0x5 → AES-CBC1, encryptBlocks=0, skipBlocks=0
        algo=0x3 → SM4-CBC(flat), encryptBlocks=0, skipBlocks=0
        algo=0x0 → UNENCRYPTED
```

#### 音频解密 `DrmAudioCencDecrypt`

```
DrmAudioCencDecrypt(inBuf, outBuf, dataSize)
  ├── inBuf.meta_->GetData(Tag::DRM_CENC_INFO)    // 从元数据获取加密信息
  ├── 根据 algo 类型决定 SubSample 分段方式
  │     ├── AES-CTR / SM4-CTR → subSampleNum=1，整段加密
  │     └── AES-CBC / SM4-CBC → subSampleNum=2，按 block 对齐分段
  └── DecryptMediaData(cencInfo, inBuf, outBuf)    // 调用 DRM plugin
```

#### CEI 解析（视频）

`DrmFindCeiPos()` 扫描 NAL 单元中的 SEI（Supplement Enhancement Information）来定位 CENC 数据：

```
DrmFindCeiPos(data, dataSize)
  └── 遍历 0x00 0x00 0x01 start code
      ├── H.264: NAL type=39/6 (SEI) → 匹配 user_data_unregistered UUID
      ├── H.265: NAL type=39 → 匹配相同 UUID
      └── AVS:  NAL type=0xb5 (extension) → 匹配相同 UUID
```

UUID: `70:c1:db:9f:66:ae:41:27:bf:c0:bb:19:81:69:4b:66`

---

## 三层调用链总结

```
┌─────────────────────────────────────────────────────────────┐
│ Layer 1: DecoderSurfaceFilter（Filter 层）                   │
│   入口：SetDecryptConfig(keySession, svpFlag)                │
│   职责：SVP 路径决策 + 注入 keySession                        │
│   svpFlag=true → 使用 codecName.secure 硬件 decoder          │
│   svpFlag=false → 使用普通 decoder                           │
├─────────────────────────────────────────────────────────────┤
│ Layer 2: MediaCodec（编解码核心层）                            │
│   入口：SetDecryptConfig / SetAudioDecryptionConfig          │
│   职责：管理 CodecDrmDecrypt 生命周期                          │
│   HandleInputBufferInner 中调度音频解密                      │
│   DrmAudioCencDecrypt: buffer 拷贝 + 解密 + 拷贝回来          │
├─────────────────────────────────────────────────────────────┤
│ Layer 3: CodecDrmDecrypt（解密执行层）                        │
│   入口：DrmVideoCencDecrypt / DrmAudioCencDecrypt            │
│   职责：解析 CENC info → 计算 SubSample → DRM plugin 解密    │
│   DRM plugin: decryptModuleProxy_->DecryptMediaData()       │
│   支持算法：AES-CBC/AES-CBCS/AES-CTR / SM4-CBC/SM4-CTR       │
└─────────────────────────────────────────────────────────────┘
```

---

## SVP 安全路径一致性校验

**文件**: `services/services/codec/server/video/codec_server.cpp`

```cpp
int32_t CodecServer::CheckDrmSvpConsistency(keySession, svpFlag) {
    // svpFlag=false，但 decoder 名称含 .secure → 报错
    if (svpFlag == false && codecName.find(".secure") != npos) return ERROR;
    // svpFlag=true，但 decoder 名称不含 .secure → 报错
    if (svpFlag == true && codecName.find(".secure") == npos) return ERROR;
    // SVP=true 时，还需校验 session 级别的 ContentProtectionLevel
    if (svpFlag == true) {
        keySession->GetContentProtectionLevel(sessionLevel);
        // 校验 level 是否满足安全路径要求
    }
}
```

---

## 关联场景

| 场景 | 关键路径 |
|------|---------|
| 三方应用播放 DRM 加密视频 | Filter.SetDecryptConfig → MediaCodec.SetDecryptConfig → CodecDrmDecrypt |
| 问题定位：DRM 解密失败 | CheckDrmSvpConsistency 日志 / SetDrmAlgoAndBlocks 算法枚举 |
| 新需求：支持新 DRM 算法 | CodecDrmDecrypt::SetDrmAlgoAndBlocks 增加分支 |
| SVP 路径与普通路径切换 | svpFlag 决定是否使用 .secure decoder |
| 问题定位：音频 DRM 解密数据错乱 | DrmAudioCencDecrypt 的 buffer memcpy 逻辑 |

---

## 术语表

| 术语 | 全称 | 说明 |
|------|------|------|
| CENC | Common Encryption | ISO/IEC 23001-7 定义的通用加密格式 |
| DRM | Digital Rights Management | 数字版权管理 |
| SVP | Secure Video Path | 安全视频路径，解密在安全硬件/TEE 中完成 |
| CEI | Codec Enhancement Information | 位于 SEI NAL 单元中的 DRM 元数据 |
| SubSample | SubSample | CENC 加密的最小单元，由 clearHeaderLen + payLoadLen 组成 |
| keySession | MediaKeySession | DRM 密钥会话，持有解密密钥 |
| IMediaDecryptModuleService | DRM 解密模块服务 | 实际执行 AES/SM4 解密的 DRM plugin |
| IMediaKeySessionService | 密钥会话服务 | 管理密钥生命周期 |

---

## 文件索引

| 文件 | 职责 |
|------|------|
| `services/drm_decryptor/codec_drm_decrypt.h/cpp` | CodecDrmDecrypt 核心实现 |
| `services/media_engine/modules/media_codec/media_codec.cpp` | MediaCodec DRM 调度层 |
| `services/media_engine/filters/decoder_surface_filter.cpp` | Filter 层 SVP 决策 |
| `services/media_engine/filters/audio_decoder_filter.cpp` | 音频 Filter DRM 配置 |
| `services/services/codec/server/video/codec_server.cpp` | CheckDrmSvpConsistency 一致性校验 |
| `services/services/codec/ipc/codec_service_proxy.cpp` | IPC proxy 层 |
| `interfaces/inner_api/native/drm_i_keysession_service.h` | DRM key session 接口定义 |
| `interfaces/inner_api/native/drm_i_mediadecryptmodule_service.h` | DRM decrypt module 接口定义 |
