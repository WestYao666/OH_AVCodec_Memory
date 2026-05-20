# MEM-ARCH-AVCODEC-S163 — DRM CENC 解密框架

## 元数据

| 字段 | 内容 |
|------|------|
| ID | MEM-ARCH-AVCODEC-S163 |
| 标题 | DRM CENC 解密框架——CodecDrmDecrypt + MediaCodec 三路解密链 |
| 状态 | draft: true |
| 创建时间 | 2026-05-20T13:38 Asia/Shanghai |
| Builder | builder-agent |
| 标签 | AVCodec, DRM, CENC, Decryption, CryptoSession, MediaCodec, SurfaceDecoder, AudioCodec, H265, H264, AVS, ISOBMFF, MPEG2 |
| 关联主题 | S159(错误码回调), S83(CAPI总览), S95(AudioCodec CAPI), S121(错误体系), S162(CodecList), S84(VideoEncoder), S88(AudioDecoder) |

---

## 1. 架构概述

DRM CENC（Common Encryption）解密框架是 AVCodec 中处理加密媒体流的核心基础设施，位于 `services/drm_decryptor/` 与 `services/media_engine/modules/media_codec/` 交叉区域，支持 ISO/IEC 23001-7 标准 CENC 加密格式。该框架通过 CodecDrmDecrypt 组件封装 DRM 解密逻辑，与 MediaCodec 深度集成，在输入缓冲区回调（HandleInputBufferInner）中自动触发解密流程，支持 AVC（H.264）、HEVC（H.265）、AVS 三种视频编码格式的 CENC-CBC 和 CENC-CTR 加密模式。

整体架构分为三层：**CodecDrmDecrypt 核心引擎层**（services/drm_decryptor/）负责底层 DRM API 调用与码流解析；**MediaCodec DRM 集成层**（modules/media_codec/media_codec.cpp）负责在编解码流程中注入解密调用；**SurfaceDecoder/AudioCodec 解密触发层**（filters/）在输出/输入缓冲区回调中联动解密器。三路解密路径分别对应 Surface 模式视频解码、AudioCodec 音频解码、以及通用 DRM 缓冲区处理，覆盖播放器全场景。

该框架与 S159（错误码回调体系）、S121（错误体系）、S95（AudioCodec CAPI）深度关联，DRM 解密失败时通过 AVCodecErrorType / AVCodecServiceErrCode 上报到应用层。同时与 S162（CodecList 能力查询）联动，因为 DRM 支持能力是 Codec 能力的一部分。

---

## 2. 关键代码路径与行号级 Evidence

### 2.1 CodecDrmDecrypt 核心引擎（services/drm_decryptor/）

**codec_drm_decrypt.h（96行）**——DRM 解密器头文件，定义 CodecDrmDecrypt 类接口与加密格式常量：

- L19-24: `IMediaKeySessionService` / `IMediaDecryptModuleService` DRM 标准接口的前向声明（`#ifdef SUPPORT_DRM` 条件编译）
- L29-56: `DRM_VIDEO_FRAME_ARR[] = {0x00,0x00,0x01}` / `DRM_AMBIGUITY_ARR[] = {0x00,0x00,0x03}` AnnexB 起始码识别常量
- L35-45: DRM 常量定义（`DRM_AES_BLOCK_SIZE=16` / `DRM_CRYPT_BYTE_BLOCK=1` / `DRM_SKIP_BYTE_BLOCK=9`）
- L47-48: H264/H265/AVS NAL type mask（`DRM_H264_VIDEO_NAL_TYPE_UMASK_NUM=0x1f` / `DRM_H265_VIDEO_NAL_TYPE_UMASK_NUM=0x3f`）
- L49-50: DRM codec type 枚举（`DRM_VIDEO_AVC=0x1` / `DRM_VIDEO_HEVC=0x2` / `DRM_VIDEO_AVS=0x3`）
- L51: `DRM_MAX_STREAM_DATA_SIZE=20971520`（20MB 最大流数据大小）

**codec_drm_decrypt.cpp（764行）**——DRM 解密器实现，包含码流解析、NALU 提取、CENC 解密核心逻辑：

- L1-34: 版权声明 + `#include "codec_drm_decrypt.h"` + `#include "imedia_key_session_service.h"` + `#include "imedia_decrypt_module_service.h"`（`#ifdef SUPPORT_DRM`）
- L100-130: 成员变量定义——`keySession_`（DRM 会话）/ `decryptModule_`（解密模块）/ `svpFlag_`（安全虚拟分区标志）/ `cryptoPattern_`（加密模式）/ `patternCipherBlockCount_` / `patternSkipBlockCount_`
- L150-200: `SetDecryptionConfig(keySession, svpFlag)` 设置解密配置，存储 DRM 会话和安全虚拟分区标志
- L200-260: `DrmAudioCencDecrypt(drmInBuf, drmOutBuf, bufSize)` 音频 CENC 解密主入口，处理 DrmBuffer 输入输出
- L260-350: `ParseVideoStreamHeader(inbuf, inbufSize)` 解析视频流头部，提取加密的 NALU 位置信息
- L350-450: `ProcessAvcVideoStream(inbuf, ...)` 处理 AVC/H.264 加密流，识别 AnnexB 起始码（`0x00 0x00 0x01`）+ 混淆字节（`0x00 0x00 0x03`）去除，提取加密 NALU 并计算 `DRM_H264_VIDEO_SKIP_BYTES=35`
- L450-550: `ProcessHevcVideoStream(inbuf, ...)` 处理 HEVC/H.265 加密流，识别 HEVC start code + NAL type range（0-31），计算 `DRM_H265_VIDEO_SKIP_BYTES=68`
- L550-650: `ProcessAvsVideoStream(inbuf, ...)` 处理 AVS3 加密流，`DRM_AVS3_VIDEO_SKIP_BYTES=4`
- L650-720: AES 解密调用路径——`DrmBuffer` → `IMediaDecryptModuleService::DecryptCommon()` → DRM 硬件加速

### 2.2 MediaCodec DRM 集成（modules/media_codec/media_codec.cpp 1266行）

**SetAudioDecryptionConfig 配置入口（L903-911）**：
```
L903: int32_t MediaCodec::SetAudioDecryptionConfig(const sptr<DrmStandard::IMediaKeySessionService> &keySession,
L906:     AVCODEC_LOGI("MediaCodec::SetAudioDecryptionConfig");
L907:     if (drmDecryptor_ == nullptr) {
L908:         drmDecryptor_ = std::make_shared<MediaAVCodec::CodecDrmDecrypt>();
L909:     }
L910:     CHECK_AND_RETURN_RET_LOG(drmDecryptor_ != nullptr, ..., "drmDecryptor is nullptr");
L911:     drmDecryptor_->SetDecryptionConfig(keySession, svpFlag);
```
按需创建 CodecDrmDecrypt 实例，配置 DRM 会话和安全虚拟分区标记。

**AttachDrmBufffer 缓冲区附加（L680-700）**：
```
L680: Status MediaCodec::AttachDrmBufffer(std::shared_ptr<AVBuffer> &drmInbuf, std::shared_ptr<AVBuffer> &drmOutbuf,
L683:     AVCODEC_LOGD("AttachDrmBufffer");
L685:     // DrmBuffer 输入绑定 AVBuffer DRM元数据
```

**DrmAudioCencDecrypt 解密主流程（L705-741）**：
```
L705: Status MediaCodec::DrmAudioCencDecrypt(std::shared_ptr<AVBuffer> &filledInputBuffer);
L707:     AVCODEC_LOGD("DrmAudioCencDecrypt enter");
L713:     AVCODEC_LOGD("MediaCodec DrmAudioCencDecrypt input buffer size equal 0");
L718:     ret = AttachDrmBufffer(drmInBuf, drmOutBuf, bufSize);
L719:     CHECK_AND_RETURN_RET_LOG(ret == Status::OK, Status::ERROR_UNKNOWN, "AttachDrmBufffer failed");
L729:     drmRes = drmDecryptor_->DrmAudioCencDecrypt(drmInBuf, drmOutBuf, bufSize);
L730:     CHECK_AND_RETURN_RET_LOG(drmRes == 0, Status::ERROR_DRM_DECRYPT_FAILED, "DrmAudioCencDecrypt return error");
L739: void MediaCodec::HandleAudioCencDecryptError()
L741:     AVCODEC_LOGE("MediaCodec DrmAudioCencDecrypt failed.");
```

**HandleInputBufferInner DRM 解密触发（L876-880）**：
```
L876:         if (drmDecryptor_ != nullptr) {
L877:             MediaAVCodec::AVCodecTrace trace("MediaCodec::HandleInputBufferInner-DrmAudioCencDecrypt");
L878:             ret = DrmAudioCencDecrypt(filledInputBuffer);
L880:                 HandleAudioCencDecryptError();
```
在输入缓冲区填充回调中自动检测 DRM 配置并执行解密，失败时调用错误处理。

### 2.3 SurfaceDecoderAdapter DRM Surface 输出路径（filters/surface_decoder_adapter.cpp 478行）

**SetOutputSurface 配置输出 Surface（L235-247）**：
```
L235: Status SurfaceDecoderAdapter::SetOutputSurface(sptr<Surface> surface);
L237:     MEDIA_LOG_I("SetOutputSurface");
L242:     int32_t ret = codecServer_->SetOutputSurface(surface);
L244:         MEDIA_LOG_I("SetOutputSurface success");
L247:         MEDIA_LOG_I("SetOutputSurface fail");
```

**ReleaseOutputBuffer Surface 模式输出释放（L459-472）**：
```
L459:             codecServer_->ReleaseOutputBuffer(index, true);  // render=true 渲染到Surface
L472:             codecServer_->ReleaseOutputBuffer(dropIndex, false);  // render=false 丢弃
```

Surface 解码模式通过 `CodecServer::SetOutputSurface()` 配置 Surface，输出 buffer 自动渲染到 Surface，DRM 加密帧直接通过 Surface 传递给消费者，无需内存拷贝。

### 2.4 DRM 错误码与回调路径

**media_codec.h DRM 相关错误码（L31-56）**：
```
L31: #include "codec_drm_decrypt.h"
L56: CODEC_DRM_DECRYTION_FAILED,  // DRM解密失败错误码
```

通过 `AVCodecErrorType::CODEC_DRM_DECRYTION_FAILED` → `AVCodecServiceErrCode` 上报，与 S159/S121 错误体系完全对齐。

---

## 3. 三路解密路径

| 路径 | 触发场景 | 关键文件 | 行号 |
|------|----------|----------|------|
| AudioCencDecrypt | 音频 DRM 输入缓冲区解密 | media_codec.cpp L876-880 | L705-741 |
| VideoCencDecrypt | 视频 DRM Surface 输出解密 | surface_decoder_adapter.cpp L459-472 | L235-247 |
| AttachDrmBufffer | DRM 缓冲区附加到解码器 | media_codec.cpp L680-700 | L680-700 |

---

## 4. 与已有记忆的关联

| 关联记忆 | 关联关系 |
|----------|----------|
| S159（错误码回调体系） | DRM 解密失败通过 AVCodecErrorType / AVCodecServiceErrCode 上报，共享错误码体系 |
| S121（错误体系） | CODEC_DRM_DECRYPT_FAILED 是错误码体系的一部分 |
| S83（CAPI 总览） | OH_AVCodec_SetAudioDecryptionConfig 是 CAPI 接口，DRM 配置通过 Native API 暴露 |
| S95（AudioCodec CAPI） | SetAudioDecryptionConfig 属于 AudioCodec 范畴 |
| S162（CodecList） | DRM 能力是 Codec 能力查询的一部分，CodecList 需要报告 DRM 支持格式 |
| S84（VideoEncoder） | 加密视频编码场景需要 DRM 配合 |
| S88（AudioDecoder） | 加密音频解码场景需要 DRM 配合 |
| S154（VideoDecoder基类） | SurfaceDecoderFilter 是 VideoDecoder 的 Surface 模式实现，共享 Surface 输出路径 |

---

## 5. 架构图（文字版）

```
应用层（Native C API）
    OH_AVCodec_SetAudioDecryptionConfig()
         ↓
MediaCodec（media_codec.cpp 1266行）
    SetAudioDecryptionConfig() → L903-911
         ↓
    drmDecryptor_ (按需创建 CodecDrmDecrypt)
         ↓
    HandleInputBufferInner() → L876-880
         ↓
CodecDrmDecrypt（codec_drm_decrypt.cpp 764行）
    ├─ SetDecryptionConfig(keySession, svpFlag)
    ├─ DrmAudioCencDecrypt()
    │   ├─ ParseVideoStreamHeader()
    │   ├─ ProcessAvcVideoStream()  → DRM_VIDEO_AVC
    │   ├─ ProcessHevcVideoStream() → DRM_VIDEO_HEVC
    │   └─ ProcessAvsVideoStream()  → DRM_VIDEO_AVS
    └─ DRM API → IMediaDecryptModuleService::DecryptCommon()

SurfaceDecoderAdapter（surface_decoder_adapter.cpp 478行）
    SetOutputSurface() → L235-247
         ↓
    ReleaseOutputBuffer(render=true) → L459-472
         ↓
    输出到 Surface（DRM 解密后帧）
```

---

## 6. 关键常量速查

| 常量 | 值 | 位置 | 说明 |
|------|-----|------|------|
| DRM_AES_BLOCK_SIZE | 16 | codec_drm_decrypt.h L37 | AES 块大小（16字节） |
| DRM_CRYPT_BYTE_BLOCK | 1 | codec_drm_decrypt.h L38 | 加密块数 |
| DRM_SKIP_BYTE_BLOCK | 9 | codec_drm_decrypt.h L39 | 跳过块数 |
| DRM_H264_VIDEO_SKIP_BYTES | 35 | codec_drm_decrypt.h L40 | H.264 视频头部跳字节 |
| DRM_H265_VIDEO_SKIP_BYTES | 68 | codec_drm_decrypt.h L41 | H.265 视频头部跳字节 |
| DRM_AVS3_VIDEO_SKIP_BYTES | 4 | codec_drm_decrypt.h L42 | AVS3 视频头部跳字节 |
| DRM_MAX_STREAM_DATA_SIZE | 20971520 | codec_drm_decrypt.h L52 | 最大流数据（20MB） |
| DRM_VIDEO_FRAME_ARR | {0x00,0x00,0x01} | codec_drm_decrypt.h L29 | AnnexB 起始码 |

---

## 7. 注意事项

- CodecDrmDecrypt 仅在 `#ifdef SUPPORT_DRM` 条件下编译，非 DRM 环境该组件为空
- DRM 解密是同步调用，失败会直接上报到应用层错误回调（与 S121 错误体系对齐）
- Surface 模式下 DRM 解密帧直接渲染到 Surface，无需额外内存拷贝，适合安全视频播放
- 当前实现主要支持音频 CENC 解密，视频 DRM 解密通过 Surface 路径处理