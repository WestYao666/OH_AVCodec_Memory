# MEM-ARCH-AVCODEC-S121: AVCodec 错误码与回调体系——三层架构

**状态**: draft  
**生成时间**: 2026-05-14  
**Builder**: builder agent  
**scope**: AVCodec, ErrorHandling, Callback, CAPI, IPC  
**关联场景**: 三方应用接入/问题定位/新人入项  

---

## 1. 主题概述

AVCodec 模块的错误处理体系由三层组成：

| 层级 | 文件 | 职责 |
|------|------|------|
| L1 错误类型 | `avcodec_common.h` | `AVCodecErrorType` 枚举，定义错误分类 |
| L2 服务错误码 | `avcodec_errors.h` | `AVCodecServiceErrCode` 枚举，50+ 具体错误码 |
| L3 回调接口 | `avcodec_common.h` | `MediaCodecCallback` / `MediaCodecParameterCallback` / `MediaCodecParameterWithAttrCallback` 三类回调接口 |

三层协作路径：Codec 引擎层产生错误 → 服务层映射为 `AVCodecServiceErrCode` → 通过 `AVCodecCallback::OnError` 回调通知应用层。

---

## 2. L1: AVCodecErrorType 错误分类

**文件**: `interfaces/inner_api/native/avcodec_common.h:37-46`

```cpp
enum AVCodecErrorType : int32_t {
    /* internal errors, error code passed by the errorCode */
    AVCODEC_ERROR_INTERNAL,
    /* extend error start. The extension error code agreed upon
       by the plug-in and the application will be transparently transmitted. */
    AVCODEC_ERROR_DECRYTION_FAILED,
    /* internal errors, the extension error codes within the framework. */
    AVCODEC_ERROR_FRAMEWORK_FAILED,
    AVCODEC_ERROR_EXTEND_START = 0X10000,
};
```

**文件**: `interfaces/inner_api/native/avcodec_common.h:58-76`

```cpp
enum AVCodecBufferFlag : uint32_t {
    AVCODEC_BUFFER_FLAG_NONE = 0,
    AVCODEC_BUFFER_FLAG_EOS = 1 << 0,          // 流结束
    AVCODEC_BUFFER_FLAG_SYNC_FRAME = 1 << 1, // 关键帧
    AVCODEC_BUFFER_FLAG_PARTIAL_FRAME = 1 << 2, // 部分帧
    AVCODEC_BUFFER_FLAG_CODEC_DATA = 1 << 3,  // 编解码数据（如 SPS/PPS）
    AVCODEC_BUFFER_FLAG_DISCARD = 1 << 4,     // 可丢弃帧
    AVCODEC_BUFFER_FLAG_DISPOSABLE = 1 << 5,  // 非参考帧
    AVCODEC_BUFFER_FLAG_DISPOSABLE_EXT = 1 << 6, // 扩展可丢弃帧
    AVCODEC_BUFFER_FLAG_MUL_FRAME = 1 << 7,   // 多帧合一
};
```

**文件**: `interfaces/inner_api/native/avcodec_common.h:89-98`

```cpp
struct AVCodecBufferInfo {
    int64_t presentationTimeUs = 0; // PTS（微秒）
    int32_t size = 0;               // 数据大小（字节）
    int32_t offset = 0;              // 数据起始偏移
};
```

---

## 3. L2: AVCodecServiceErrCode 服务层错误码

**文件**: `interfaces/inner_api/native/avcodec_errors.h`（111行）

### 3.1 错误码定义规则

错误码结构：bit 28~21 为 subsystem，bit 20~16 为 Module，bit 15~0 为具体错误码。

```cpp
constexpr AVCSErrCode AVCS_MODULE = 10;
constexpr AVCSErrCode AVCS_ERR_OFFSET = ErrCodeOffset(SUBSYS_MULTIMEDIA, AVCS_MODULE);
```

### 3.2 AVCodecServiceErrCode 枚举（50+ 错误码）

```cpp
typedef enum AVCodecServiceErrCode : ErrCode {
    AVCS_ERR_OK = ERR_OK,
    AVCS_ERR_NO_MEMORY = AVCS_ERR_OFFSET + ENOMEM,         // 无内存
    AVCS_ERR_INVALID_OPERATION = AVCS_ERR_OFFSET + ENOSYS, // 操作不允许
    AVCS_ERR_INVALID_VAL = AVCS_ERR_OFFSET + EINVAL,       // 参数无效
    AVCS_ERR_UNKNOWN = AVCS_ERR_OFFSET + 0x200,           // 未知错误
    AVCS_ERR_SERVICE_DIED,                                 // 服务已死亡
    AVCS_ERR_INVALID_STATE,                               // 状态不支持此操作
    AVCS_ERR_UNSUPPORT,                                    // 不支持接口
    // 音频相关
    AVCS_ERR_UNSUPPORT_AUD_SRC_TYPE,
    AVCS_ERR_UNSUPPORT_AUD_SAMPLE_RATE,
    AVCS_ERR_UNSUPPORT_AUD_CHANNEL_NUM,
    AVCS_ERR_UNSUPPORT_AUD_ENC_TYPE,
    AVCS_ERR_UNSUPPORT_AUD_PARAMS,
    AVCS_ERR_AUD_RENDER_FAILED,
    AVCS_ERR_AUD_ENC_FAILED,
    AVCS_ERR_AUD_DEC_FAILED,
    // 视频相关
    AVCS_ERR_UNSUPPORT_VID_SRC_TYPE,
    AVCS_ERR_UNSUPPORT_VID_ENC_TYPE,
    AVCS_ERR_UNSUPPORT_VID_PARAMS,
    AVCS_ERR_UNSUPPORT_VID_DEC_TYPE,
    AVCS_ERR_VID_ENC_FAILED,
    AVCS_ERR_VID_DEC_FAILED,
    // 封装/解封装
    AVCS_ERR_UNSUPPORT_FILE_TYPE,
    AVCS_ERR_MUXER_FAILED,
    AVCS_ERR_DEMUXER_FAILED,
    // 文件/IO
    AVCS_ERR_OPEN_FILE_FAILED,
    AVCS_ERR_FILE_ACCESS_FAILED,
    AVCS_ERR_SEEK_FAILED,
    AVCS_ERR_NOT_FIND_FILE,
    // 数据源
    AVCS_ERR_DATA_SOURCE_IO_ERROR,
    AVCS_ERR_DATA_SOURCE_OBTAIN_MEM_ERROR,
    AVCS_ERR_DATA_SOURCE_ERROR_UNKNOWN,
    AVCS_ERR_UNSUPPORT_STREAM,
    AVCS_ERR_UNSUPPORT_SOURCE,
    // 启动/停止/暂停
    AVCS_ERR_START_FAILED,
    AVCS_ERR_PAUSE_FAILED,
    AVCS_ERR_STOP_FAILED,
    AVCS_ERR_NETWORK_TIMEOUT,
    // 参数校验
    AVCS_ERR_CODEC_PARAM_INCORRECT,
    AVCS_ERR_CONFIGURE_MISMATCH_CHANNEL_COUNT,
    AVCS_ERR_MISMATCH_SAMPLE_RATE,
    AVCS_ERR_MISMATCH_BIT_RATE,
    AVCS_ERR_CONFIGURE_ERROR,
    AVCS_ERR_INVALID_DATA,
    AVCS_ERR_DECRYPT_FAILED,
    AVCS_ERR_TRY_AGAIN,            // 稍后重试
    AVCS_ERR_STREAM_CHANGED,       // 输出格式变化
    AVCS_ERR_INPUT_DATA_ERROR,
    AVCS_ERR_UNSUPPORTED_CODEC_SPECIFICATION,
    AVCS_ERR_ILLEGAL_PARAMETER_SETS,
    AVCS_ERR_MINSSING_PARAMETER_SETS,
    AVCS_ERR_INSUFFICIENT_HARDWARE_RESOURCES,
    // IPC
    AVCS_ERR_IPC_UNKNOWN,
    AVCS_ERR_IPC_GET_SUB_SYSTEM_ABILITY_FAILED,
    AVCS_ERR_IPC_SET_DEATH_LISTENER_FAILED,
    AVCS_ERR_CREATE_CODECLIST_STUB_FAILED,
    AVCS_ERR_CREATE_AVCODEC_STUB_FAILED,
    AVCS_ERR_NOT_ENOUGH_DATA,
    AVCS_ERR_END_OF_STREAM,
    AVCS_ERR_VIDEO_UNSUPPORT_COLOR_SPACE_CONVERSION,
    AVCS_ERR_EXTEND_START = AVCS_ERR_OFFSET + 0xF000,
} AVCodecServiceErrCode;
```

### 3.3 错误码转换函数

```cpp
std::string AVCSErrorToString(AVCodecServiceErrCode code);
OH_AVErrCode AVCSErrorToOHAVErrCode(AVCodecServiceErrCode code);
AVCodecServiceErrCode StatusToAVCodecServiceErrCode(Media::Status code);
AVCodecServiceErrCode VPEErrorToAVCSError(int32_t code);
```

---

## 4. L3: 回调接口三层架构

**文件**: `interfaces/inner_api/native/avcodec_common.h:98-233`

### 4.1 AVCodecCallback（基础错误回调）

```cpp
class AVCodecCallback {
public:
    virtual ~AVCodecCallback() = default;
    virtual void OnError(AVCodecErrorType errorType, int32_t errorCode) = 0;
    virtual void OnOutputFormatChanged(const Format &format) = 0;
};
```

### 4.2 MediaCodecCallback（编解码器输出回调）

```cpp
class MediaCodecCallback : public AVCodecCallback {
public:
    virtual void OnOutputBufferAvailable(uint32_t index,
        std::shared_ptr<AVBuffer> buffer) = 0;
    virtual void OnInputBufferAvailable(uint32_t index,
        std::shared_ptr<AVBuffer> buffer) = 0;
    virtual void OnError(AVCodecErrorType errorType, int32_t errorCode) override = 0;
    virtual void OnOutputFormatChanged(const Format &format) override = 0;
    virtual void OnStreamChanged(uint32_t width, uint32_t height,
        uint32_t frameRate) = 0;
};
```

### 4.3 MediaCodecParameterCallback（编码器参数回调）

```cpp
class MediaCodecParameterCallback {
public:
    virtual ~MediaCodecParameterCallback() = default;
    virtual void OnInputParameterReceived(uint32_t index,
        std::shared_ptr<AVBuffer> buffer) = 0;
    virtual void OnOutputParameterReceived(uint32_t index,
        std::shared_ptr<AVBuffer> buffer) = 0;
};
```

### 4.4 MediaCodecParameterWithAttrCallback（带属性参数回调）

```cpp
class MediaCodecParameterWithAttrCallback {
public:
    virtual ~MediaCodecParameterWithAttrCallback() = default;
    virtual void OnInputBufferAvailableWithAttr(uint32_t index,
        std::shared_ptr<AVBuffer> buffer,
        AVCodecBufferAttr &attr) = 0;
    virtual void OnOutputFormatChanged(const Format &format) = 0;
    virtual void OnError(AVCodecErrorType errorType, int32_t errorCode) = 0;
};
```

---

## 5. 三层协作关系

```
CodecEngine (e.g. VideoDecoder)
    ↓ AVCodecErrorType errorType + int32_t errorCode
AVCodecServiceErrCode (avcodec_errors.h)
    ↓ AVCSErrorToOHAVErrCode()
OH_AVErrCode (Native C API 错误码)
    ↓ OnError(errorType, errorCode)
MediaCodecCallback::OnError()
    → 应用层处理
```

**关联记忆**:
- S55: AVCodec 模块间回调链路（CodecCallback/CodecBaseCallback/CodecListenerCallback 四路）
- S83: AVCodec Native C API 架构（四类 API 家族）
- S92/S114: MediaCodec 核心引擎架构（CodecState 十二态机）

---

## 6. Evidence 清单

| # | 文件 | 行号 | 内容 |
|---|------|------|------|
| 1 | avcodec_common.h | 37-46 | AVCodecErrorType 枚举 |
| 2 | avcodec_common.h | 58-76 | AVCodecBufferFlag 枚举（8个标志位）|
| 3 | avcodec_common.h | 89-98 | AVCodecBufferInfo 结构体 |
| 4 | avcodec_common.h | 98-170 | AVCodecCallback 类定义 |
| 5 | avcodec_common.h | 172-219 | MediaCodecCallback 类定义 |
| 6 | avcodec_common.h | 220-247 | MediaCodecParameterCallback + MediaCodecParameterWithAttrCallback |
| 7 | avcodec_errors.h | 全文（111行）| AVCodecServiceErrCode（50+错误码）+ 转换函数 |

---

## 7. 本地镜像路径

```
/home/west/av_codec_repo/interfaces/inner_api/native/avcodec_common.h
/home/west/av_codec_repo/interfaces/inner_api/native/avcodec_errors.h
```