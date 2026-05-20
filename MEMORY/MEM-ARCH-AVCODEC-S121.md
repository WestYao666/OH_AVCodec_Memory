---
id: MEM-ARCH-AVCODEC-S121
title: "AVCodec 错误码与回调体系——三层架构（AVCodecErrorType / AVCodecServiceErrCode / MediaCodecCallback）"
status: pending_approval
ticket_id: S121
scope: "AVCodec, ErrorHandling, Callback, CAPI, IPC"
关联场景: "三方应用接入/问题定位/新人入项"
关联记忆: "S55(回调链路)/S83(CAPI总览)/S92/S114(MediaCodec核心)"
生成时间: "2026-05-21T04:10"
---

# S121：AVCodec 错误码与回调体系——三层架构

## 主题

AVCodec Native API 层的**三层回调+双层错误码**架构，从接口契约（avcodec_common.h）→服务实现（avcodec_errors.h）→IPC传输（codec_service_stub/proxy）的完整链路。

## Code Evidence

### 1. 三层回调接口（avcodec_common.h:306行）

#### AVCodecCallback 基类（L96-115）
```cpp
// avcodec_common.h:96-115
class AVCodecCallback {
public:
    virtual ~AVCodecCallback() = default;
    virtual void OnError(AVCodecErrorType errorType, int32_t errorCode) = 0;
    virtual void OnOutputFormatChanged(const Format &format) = 0;
    virtual void OnInputBufferAvailable(OH_AVCodec *codec, uint32_t index) = 0;
    virtual void OnOutputBufferAvailable(OH_AVCodec *codec, uint32_t index, OH_AVBuffer *buffer) = 0;
    virtual void OnOutputFormatChanged(OH_AVCodec *codec, OH_AVFormat *format) = 0;
};
```

#### AVCodecErrorType 枚举（L24-34）
```cpp
// avcodec_common.h:24-34
enum AVCodecErrorType : int32_t {
    AVCODEC_ERROR_INTERNAL,           // 服务端错误码通过 errorCode 透传
    AVCODEC_ERROR_DECRYTION_FAILED,   // 扩展：解密失败
    AVCODEC_ERROR_FRAMEWORK_FAILED,   // 框架层内部错误
    AVCODEC_ERROR_EXTEND_START = 0X10000,  // 插件自定义错误起点
};
```

#### AVCodecBufferFlag 八标志位（L46-60）
```cpp
// avcodec_common.h:46-60
enum AVCodecBufferFlag : uint32_t {
    AVCODEC_BUFFER_FLAG_NONE        = 0,
    AVCODEC_BUFFER_FLAG_EOS         = 1 << 0,   // 流结束
    AVCODEC_BUFFER_FLAG_SYNC_FRAME  = 1 << 1,   // 关键帧
    AVCODEC_BUFFER_FLAG_PARTIAL_FRAME = 1 << 2, // 分片帧
    AVCODEC_BUFFER_FLAG_CODEC_DATA   = 1 << 3,   // 编解码数据
    AVCODEC_BUFFER_FLAG_DISCARD     = 1 << 4,   // 可丢弃帧（since 12）
    AVCODEC_BUFFER_FLAG_DISPOSABLE  = 1 << 5,   // 非参考帧（since 12）
    AVCODEC_BUFFER_FLAG_DISPOSABLE_EXT = 1 << 6, // 扩展丢弃帧（since 12）
    AVCODEC_BUFFER_FLAG_MUL_FRAME   = 1 << 7,   // 多帧 for LPP
};
```

#### MediaCodecCallback 继承链（扩展回调）
```cpp
// avcodec_common.h - 实际使用中常以 MediaCodecCallback/AVCodecCallbackWithAttr 等扩展接口出现
// 视频编码器额外支持 MediaCodecParameterCallback（编码参数回调）
```

---

### 2. 双层错误码体系（avcodec_errors.h:111行）

#### AVCodecServiceErrCode 服务端错误码（L30-75）
```cpp
// avcodec_errors.h:30-75
constexpr AVCSErrCode AVCS_MODULE = 10;
constexpr AVCSErrCode AVCS_ERR_OFFSET = ErrCodeOffset(SUBSYS_MULTIMEDIA, AVCS_MODULE);
// 错误码构成：bit28-21=subsys(多媒体), bit20-16=module(AVCS_MODULE=10), bit15-0=code

typedef enum AVCodecServiceErrCode : ErrCode {
    AVCS_ERR_OK = ERR_OK,
    AVCS_ERR_NO_MEMORY = AVCS_ERR_OFFSET + ENOMEM,
    AVCS_ERR_INVALID_OPERATION = AVCS_ERR_OFFSET + ENOSYS,
    AVCS_ERR_INVALID_VAL = AVCS_ERR_OFFSET + EINVAL,
    AVCS_ERR_UNKNOWN = AVCS_ERR_OFFSET + 0x200,
    AVCS_ERR_SERVICE_DIED,            // 服务死亡
    AVCS_ERR_INVALID_STATE,           // 状态机不支持此操作
    AVCS_ERR_UNSUPPORT,               // 不支持接口
    AVCS_ERR_INVALID_DATA,            // 输入数据无效
    AVCS_ERR_DECRYPT_FAILED,          // DRM解密失败
    AVCS_ERR_TRY_AGAIN,               // 稍后重试
    AVCS_ERR_STREAM_CHANGED,          // 输出格式变化
    AVCS_ERR_INPUT_DATA_ERROR,        // 输入数据错误
    AVCS_ERR_ILLEGAL_PARAMETER_SETS,  // 非法参数集（SPS/PPS）
    AVCS_ERR_MISSSING_PARAMETER_SETS, // 缺少参数集
    AVCS_ERR_INSUFFICIENT_HARDWARE_RESOURCES, // 硬件资源不足
    AVCS_ERR_IPC_UNKNOWN,             // IPC未知错误
    AVCS_ERR_IPC_GET_SUB_SYSTEM_ABILITY_FAILED, // 获取SA失败
    AVCS_ERR_IPC_SET_DEATH_LISTENER_FAILED,    // 设置死亡监听失败
    AVCS_ERR_CREATE_CODECLIST_STUB_FAILED,     // 创建CodecList存根失败
    AVCS_ERR_CREATE_AVCODEC_STUB_FAILED,       // 创建AVCodec存根失败
    AVCS_ERR_EXTEND_START = AVCS_ERR_OFFSET + 0xF000, // 扩展错误起点
} AVCodecServiceErrCode;
```

#### 错误码转换函数（L78-83）
```cpp
// avcodec_errors.h:78-83
OH_AVErrCode AVCSErrorToOHAVErrCode(AVCodecServiceErrCode code);        // 服务→API错误码
AVCodecServiceErrCode StatusToAVCodecServiceErrCode(Media::Status code); // Status→服务错误码
AVCodecServiceErrCode VPEErrorToAVCSError(int32_t code);                 // VPE→服务错误码
```

---

### 3. IPC 传输层（codec_service_stub.cpp:220行 / codec_service_proxy.cpp:128行）

#### 服务端 Stub（avcodec_service_stub.cpp）
```cpp
// avcodec_service_stub.cpp:220行 - 33个接口代码（CODEC_INTERFACE_CODE_XXX）
// 6路回调监听器代码：
//   CODEC_LISTENER_ON_ERROR          -> OnError
//   CODEC_LISTENER_ON_OUTPUT_FORMAT  -> OnOutputFormatChanged  
//   CODEC_LISTENER_ON_INPUT_BUFFER   -> OnInputBufferAvailable
//   CODEC_LISTENER_ON_OUTPUT_BUFFER  -> OnOutputBufferAvailable
//   CODEC_LISTENER_ON_STREAM_CHANGED -> OnOutputFormatChanged(v2)
//   CODEC_LISTENER_ON_NEED_INPUT_DATA -> 扩展：需要输入数据
```

#### 错误码透传示例
```cpp
// IPC层：AVCodecServiceErrCode（服务端定义）
//        ↓ AVCSErrorToOHAVErrCode 转换
//      OH_AVErrCode（API层公开错误码，范围 223001-223099）
// 其中 200000 = AVCS_ERR_OFFSET（多媒体SA模块偏移）
```

---

## 架构总结

```
应用层（Native C API）
  └─ OH_AVCodec / OH_AVFormat / OH_AVBuffer
       │
       ▼
接口契约层（avcodec_common.h:306行）
  ├─ AVCodecCallback（5路回调）
  ├─ MediaCodecCallback（媒体Codec专用）
  ├─ AVCodecBufferFlag（8标志位）
  ├─ AVCodecBufferInfo（PTS/size/offset）
  └─ AVCodecErrorType（ERROR_INTERNAL/EXTEND_START）
       │
       ▼
错误码转换函数
  AVCSErrorToOHAVErrCode()
  StatusToAVCodecServiceErrCode()
  VPEErrorToAVCSError()
       │
       ▼
服务端错误码层（avcodec_errors.h:111行）
  └─ AVCodecServiceErrCode（50+错误码）
     错误码 = AVCS_ERR_OFFSET(200000) + 细分错误码
     范围：AVCS_ERR_OK(0) ~ AVCS_ERR_EXTEND_START
       │
       ▼
IPC传输层（codec_service_stub.cpp:220行 / codec_service_proxy.cpp:128行）
  ├─ 33个 CodecServiceInterfaceCode 接口
  ├─ 6路 CodecListenerInterfaceCode 回调
  └─ 错误码通过 Binder 跨进程透传
```

## 关联

- **S55**（回调链路）：四路回调完整链路
- **S83**（CAPI总览）：OH_AVCodec 对象模型
- **S92/S114**（MediaCodec核心）：CodecState十二态机

## 备注

- **pending_approval**（2026-05-14T01:30 Builder提交审批）
- 三层架构与实际 IPC 层强关联，IPC 层才是真正的跨进程通信桥梁
- 错误码偏移 AVCS_ERR_OFFSET=200000 是与服务层约定俗成的模块边界