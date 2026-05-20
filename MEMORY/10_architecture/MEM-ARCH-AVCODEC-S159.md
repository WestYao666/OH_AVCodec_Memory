# MEM-ARCH-AVCODEC-S159

> **主题**: AVCodec 错误码与回调体系——三层架构（AVCodecErrorType / AVCodecServiceErrCode / MediaCodecCallback）
>
> **状态**: draft
>
> **scope**: AVCodec, ErrorHandling, Callback, CAPI, IPC, ErrorCode, EventDriven
>
> **关联场景**: 三方应用接入/问题定位/新人入项
>
> **关联记忆**: S55(回调链路)/S83(CAPI总览)/S92(S114 MediaCodec核心)/S121(S83增强版)
>
> **draft_created**: 2026-05-20T08:15:00+08:00
>
> **builder**: builder-agent (subagent)

---

## 一、主题概述

AVCodec 模块的错误码与回调体系是贯穿 C API → IPC → CodecEngine 三层的关键基础设施。本记忆聚焦 **inner_api/native** 层面的三层回调架构与错误码体系，包含：

1. **AVCodecErrorType** — 错误类型顶层枚举
2. **AVCodecServiceErrCode** — 服务层错误码（50+条目）
3. **MediaCodecCallback / MediaCodecParameterCallback / MediaCodecParameterWithAttrCallback** — 三层回调接口
4. **错误码转换函数** — AVCSErrorToOHAVErrCode / StatusToAVCodecServiceErrCode

---

## 二、AVCodecErrorType 错误类型枚举

**文件**: `interfaces/inner_api/native/avcodec_common.h` (306行)

```cpp
enum AVCodecErrorType : int32_t {
    // 内部错误，错误码由 errorCode 传递，定义见 AVCodecServiceErrCode
    AVCODEC_ERROR_INTERNAL,
    // 扩展错误起点。插件与应用约定的扩展错误码通过服务透明传递
    AVCODEC_ERROR_DECRYTION_FAILED,
    // 框架内部扩展错误码
    AVCODEC_ERROR_FRAMEWORK_FAILED,
    // 扩展错误起始值
    AVCODEC_ERROR_EXTEND_START = 0X10000,
};
```

**Evidence**:
- L37-42: AVCodecErrorType 三层分类（INTERNAL/DECRYTION_FAILED/FRAMEWORK_FAILED/EXTEND_START）
- 扩展错误码（EXTEND_START=0x10000）用于插件自定义错误

---

## 三、AVCodecServiceErrCode 服务层错误码

**文件**: `interfaces/inner_api/native/avcodec_errors.h` (111行)

### 3.1 错误码构造规则

```cpp
// bit 28~21 is subsys, bit 20~16 is Module. bit 15~0 is code
// AVCS_MODULE = 10 (多媒体子系统第10模块)
constexpr AVCSErrCode AVCS_ERR_OFFSET = ErrCodeOffset(SUBSYS_MULTIMEDIA, AVCS_MODULE);
typedef enum AVCodecServiceErrCode : ErrCode {
    AVCS_ERR_OK = ERR_OK,
    AVCS_ERR_NO_MEMORY = AVCS_ERR_OFFSET + ENOMEM,         // 无内存
    AVCS_ERR_INVALID_OPERATION = AVCS_ERR_OFFSET + ENOSYS, // 操作不允许
    AVCS_ERR_INVALID_VAL = AVCS_ERR_OFFSET + EINVAL,       // 无效参数
    AVCS_ERR_UNKNOWN = AVCS_ERR_OFFSET + 0x200,           // 未知错误
    AVCS_ERR_SERVICE_DIED,                                 // 服务死亡
    AVCS_ERR_INVALID_STATE,                                // 状态不支持此操作
    AVCS_ERR_UNSUPPORT,                                    // 不支持接口
    // ... (共50+条目)
};
```

**Evidence**:
- `avcodec_errors.h:32`: 错误码偏移计算规则 `AVCS_ERR_OFFSET = ErrCodeOffset(SUBSYS_MULTIMEDIA, AVCS_MODULE)`
- `avcodec_errors.h:34-62`: 50+错误码枚举覆盖内存/状态/不支持/服务死亡等场景

### 3.2 主要错误码分类

| 类别 | 错误码 | 说明 |
|------|--------|------|
| 通用 | OK / NO_MEMORY / INVALID_OPERATION / INVALID_VAL / UNKNOWN | 基础错误 |
| 服务态 | SERVICE_DIED / INVALID_STATE | 服务健康/状态机 |
| 接口能力 | UNSUPPORT / UNSUPPORT_* | 功能不支持 |
| 音视频参数 | UNSUPPORT_AUD_* / UNSUPPORT_VID_* | 音频/视频参数不支持 |
| 操作失败 | AUD_RENDER_FAILED / AUD_ENC_FAILED / VID_ENC_FAILED / AUD_DEC_FAILED / VID_DEC_FAILED / MUXER_FAILED / DEMUXER_FAILED | 具体操作失败 |

**Evidence**:
- `avcodec_errors.h:39-62`: 50+错误码完整列表

---

## 四、三层回调接口架构

**文件**: `interfaces/inner_api/native/avcodec_common.h` (306行)

### 4.1 AVCodecCallback（C API 层回调）

```cpp
class AVCodecCallback {
public:
    virtual ~AVCodecCallback() = default;
    virtual void OnError(AVCodecErrorType errorType, int32_t errorCode) = 0;
    virtual void OnOutputFormatChanged(const Format &format) = 0;
    virtual void OnInputBufferAvailable(uint32_t index, std::shared_ptr<AVSharedMemory> buffer) = 0;
    virtual void OnOutputBufferAvailable(uint32_t index, AVCodecBufferInfo info, AVCodecBufferFlag flag,
                                         std::shared_ptr<AVSharedMemory> buffer) = 0;
};
```

**Evidence**:
- `avcodec_common.h:98-130`: AVCodecCallback 四方法（OnError/OnOutputFormatChanged/OnInputBufferAvailable/OnOutputBufferAvailable）
- 使用 AVSharedMemory（C API 级别内存对象）
- OnOutputBufferAvailable 携带 AVCodecBufferInfo（presentationTimeUs/offset/size）+ AVCodecBufferFlag

### 4.2 MediaCodecCallback（引擎层回调）

```cpp
class MediaCodecCallback {
public:
    virtual ~MediaCodecCallback() = default;
    virtual void OnError(AVCodecErrorType errorType, int32_t errorCode) = 0;
    virtual void OnOutputFormatChanged(const Format &format) = 0;
    virtual void OnInputBufferAvailable(uint32_t index, std::shared_ptr<AVBuffer> buffer) = 0;
    virtual void OnOutputBufferAvailable(uint32_t index, std::shared_ptr<AVBuffer> buffer) = 0;
};
```

**Evidence**:
- `avcodec_common.h:172-211`: MediaCodecCallback 四方法
- 使用 AVBuffer（Native 级别缓冲区）替代 AVSharedMemory
- OnOutputBufferAvailable 签名简化（无 AVCodecBufferInfo 参数，直接从 AVBuffer 获取元数据）

### 4.3 MediaCodecParameterCallback（参数回调）

```cpp
class MediaCodecParameterCallback {
public:
    virtual ~MediaCodecParameterCallback() = default;
    virtual void OnInputBufferAvailable(uint32_t index, std::shared_ptr<AVBuffer> buffer) = 0;
    virtual void OnOutputBufferAvailable(uint32_t index, std::shared_ptr<AVBuffer> buffer) = 0;
};
```

**Evidence**:
- `avcodec_common.h:220-233`: MediaCodecParameterCallback（仅缓冲区回调，无 OnError/OnOutputFormatChanged）
- 缺少错误处理方法，用于纯参数驱动场景

### 4.4 MediaCodecParameterWithAttrCallback（带属性参数回调）

```cpp
class MediaCodecParameterWithAttrCallback {
public:
    virtual ~MediaCodecParameterWithAttrCallback() = default;
    // ... (带属性信息的缓冲区回调)
};
```

**Evidence**:
- `avcodec_common.h:233+`: MediaCodecParameterWithAttrCallback

---

## 五、AVCodecBufferFlag 缓冲区标志枚举

**文件**: `interfaces/inner_api/native/avcodec_common.h` (L58-86)

```cpp
enum AVCodecBufferFlag : uint32_t {
    AVCODEC_BUFFER_FLAG_NONE = 0,
    AVCODEC_BUFFER_FLAG_EOS = 1 << 0,                  // 流结束
    AVCODEC_BUFFER_FLAG_SYNC_FRAME = 1 << 1,          // 同步帧（关键帧）
    AVCODEC_BUFFER_FLAG_PARTIAL_FRAME = 1 << 2,       // 部分帧
    AVCODEC_BUFFER_FLAG_CODEC_DATA = 1 << 3,          // 编解码数据（如 SPS/PPS）
    AVCODEC_BUFFER_FLAG_DISCARD = 1 << 4,              // 丢弃（v12+）
    AVCODEC_BUFFER_FLAG_DISPOSABLE = 1 << 5,           // 可丢弃帧（v12+）
    AVCODEC_BUFFER_FLAG_DISPOSABLE_EXT = 1 << 6,       // 扩展可丢弃帧（v12+）
    AVCODEC_BUFFER_FLAG_MUL_FRAME = 1 << 7,            // 多帧for LPP
};
```

**Evidence**:
- `avcodec_common.h:58-86`: AVCodecBufferFlag 8个标志位（EOS/SYNC_FRAME/PARTIAL_FRAME/CODEC_DATA/DISCARD/DISPOSABLE/DISPOSABLE_EXT/MUL_FRAME）
- DISCARD/DISPOSABLE/DISPOSABLE_EXT 为 v12+ 新增，用于丢帧策略

---

## 六、错误码转换函数

### 6.1 AVCSErrorToOHAVErrCode

**Evidence**: `avcodec_errors.h` 或对应转换实现文件
- 将 AVCodecServiceErrCode 转换为 OH_AVCodec 标准错误码
- 对外 C API 使用的统一错误码体系

### 6.2 StatusToAVCodecServiceErrCode

**Evidence**: 同上
- 将 MediaFramework Status 转换为 AVCodecServiceErrCode
- 引擎层到服务层的错误码映射

---

## 七、三层架构全景图

```
┌─────────────────────────────────────────────────────────┐
│                  C API 层（对外）                         │
│  interfaces/kits/c/                                       │
│  native_avcodec_*.h                                       │
│  OH_AVCodec / OH_AVFormat / OH_AVMemory                  │
│  ─────────────────────────────────────────              │
│  AVCodecCallback (AVSharedMemory)                        │
│  OnError / OnOutputFormatChanged                         │
│  OnInputBufferAvailable / OnOutputBufferAvailable       │
└──────────────────────┬──────────────────────────────────┘
                       │ IPC (Binder)
┌──────────────────────▼──────────────────────────────────┐
│                  服务层（IPC Stub/Proxy）                 │
│  services/services/codec/ipc/                           │
│  codec_service_stub.cpp (863行) / codec_service_proxy.cpp│
│  codec_listener_stub.cpp (447行) / codec_listener_proxy.cpp│
│  ─────────────────────────────────────────              │
│  AVCodecServiceErrCode (50+错误码)                       │
│  OnCodecServerDied 死亡通知链                            │
└──────────────────────┬──────────────────────────────────┘
                       │ CodecBase Callback
┌──────────────────────▼──────────────────────────────────┐
│                  引擎层（CodecBase/CodecEngine）          │
│  services/engine/codec/                                   │
│  media_codec.cpp / audio_codec.cpp / video_decoder.cpp  │
│  ─────────────────────────────────────────              │
│  MediaCodecCallback (AVBuffer)                           │
│  MediaCodecParameterCallback                             │
│  MediaCodecParameterWithAttrCallback                     │
│  AVCodecErrorType (三层分类)                             │
└─────────────────────────────────────────────────────────┘
```

**Evidence**:
- 三层回调：avcodec_common.h L98-233
- 三层错误码：avcodec_common.h L37-42 + avcodec_errors.h L34-62
- IPC 层：services/services/codec/ipc/ 四文件（codec_service_proxy 574行/codec_service_stub 863行）

---

## 八、关键关联

- **S55**: AVCodec 模块间回调链路（CodecCallback/MediaCodecCallback/CodecBaseCallback/CodecListenerCallback 四路）
- **S83**: AVCodec Native C API 架构（四类 API 家族与 CodecClient IPC 代理）
- **S92/S114**: MediaCodec 核心引擎架构（CodecState 十二态机与 Plugins::CodecPlugin 驱动）
- **S121**: 相同主题（草案已生成，pending_approval）

---

## 九、证据索引

| 证据 | 文件 | 行号 | 说明 |
|------|------|------|------|
| E1 | interfaces/inner_api/native/avcodec_common.h | 37-42 | AVCodecErrorType 三层分类 |
| E2 | interfaces/inner_api/native/avcodec_common.h | 58-86 | AVCodecBufferFlag 8标志位 |
| E3 | interfaces/inner_api/native/avcodec_common.h | 98-130 | AVCodecCallback 四方法 |
| E4 | interfaces/inner_api/native/avcodec_common.h | 172-211 | MediaCodecCallback 四方法 |
| E5 | interfaces/inner_api/native/avcodec_common.h | 220-233 | MediaCodecParameterCallback |
| E6 | interfaces/inner_api/native/avcodec_errors.h | 32-62 | AVCodecServiceErrCode 50+条目 |
| E7 | services/services/codec/ipc/codec_service_stub.cpp | 863行 | IPC 服务端 Stub |
| E8 | services/services/codec/ipc/codec_service_proxy.cpp | 574行 | IPC 客户端 Proxy |

---

> **审查意见**:
> - (pending)