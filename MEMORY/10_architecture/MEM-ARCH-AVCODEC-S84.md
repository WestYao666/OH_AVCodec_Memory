---
status: approved
mem_id: MEM-ARCH-AVCODEC-S84
approved_at: "2026-05-06"
approved_by: feishu-user:ou_60d8641be684f82e8d9cb84c3015dde7'
title: VideoEncoder C API 实现——NativeVideoEncoder 对象模型与 Surface/Buffer 双模式
scope: [AVCodec, Native API, C API, VideoEncoder, SurfaceMode, BufferMode, CodecClient, OH_AVCodec, OH_VideoEncoder]
topic: VideoEncoder C API 实现——NativeVideoEncoder 对象模型与 Surface/Buffer 双模式
confidence: high
type: architecture_fact
created_by: builder-agent
created_at: "2026-05-03T21:49:00+08:00"
approved_by: feishu-user:ou_60d8641be684f82e8d9cb84c3015dde7
---

# MEM-ARCH-AVCODEC-S84

> **主题**：VideoEncoder C API 实现——NativeVideoEncoder 对象模型与 Surface/Buffer 双模式
> **scope**：AVCodec, Native API, C API, VideoEncoder, SurfaceMode, BufferMode, CodecClient, OH_AVCodec, OH_VideoEncoder
> **关联场景**：三方应用接入/新人入项/问题定位
> **状态**：`draft`
> **证据来源**：`frameworks/native/capi/avcodec/native_video_encoder.cpp` / `video_encoder_object.h` / `native_video_decoder.cpp`
> **创建时间**：2026-05-03T21:49

---

## 1. 概述

VideoEncoder C API（`native_video_encoder.cpp`，715行）是 OpenHarmony AVCodec Native C API 的视频编码器实现层，负责将应用层 C API 调用转换为内部 `AVCodecVideoEncoder` 引擎操作。相比 VideoDecoder（`native_video_decoder.cpp`）使用 `SetSurface` 将输出 Surface 绑定到解码器，VideoEncoder 使用 `GetSurface` 从编码器获取输入 Surface——两者方向相反。

---

## 2. VideoEncoderObject 对象模型

### 2.1 类继承结构

```cpp
// video_encoder_object.h:32-33
struct VideoEncoderObject : public OH_AVCodec {
    explicit VideoEncoderObject(const std::shared_ptr<AVCodecVideoEncoder>& encoder);
```

与 `VideoDecoderObject`（`native_video_decoder.cpp:43`）完全相同的继承模式：`OH_AVCodec` 基类 + 具体编码器共享指针。`OH_AVCodec` 基类由 `AVMagic` 魔数标识类型：

```cpp
// native_video_encoder.cpp:49-51
bool IsValidVideoEncoderMagic(AVMagic magic)
{
    return magic == AVMagic::AVCODEC_MAGIC_VIDEO_ENCODER ||
           OHOS::MediaAVCodec::PreprocessorEncoder::IsPreprocEncoderMagic(magic);
}
```

支持两种编码器类型：标准 `AVCODEC_MAGIC_VIDEO_ENCODER` 和预处理器编码器（`PreprocessorEncoder`）。

### 2.2 成员变量

```cpp
// video_encoder_object.h:35-55
struct VideoEncoderObject : public OH_AVCodec {
    const std::shared_ptr<AVCodecVideoEncoder> videoEncoder_;  // 内部编码器引擎
    std::queue<OHOS::sptr<MFObjectMagic>> tempList_;
    std::unordered_map<uint32_t, OHOS::sptr<OH_AVFormat>> inputFormatMap_;   // Buffer模式输入参数Map
    std::unordered_map<uint32_t, OHOS::sptr<OH_AVMemory>> outputMemoryMap_;  // Buffer模式输出内存Map
    std::unordered_map<uint32_t, OHOS::sptr<OH_AVMemory>> inputMemoryMap_;   // Buffer模式输入内存Map
    std::unordered_map<uint32_t, OHOS::sptr<OH_AVBuffer>> outputBufferMap_;  // Buffer模式输出BufferMap
    std::unordered_map<uint32_t, OHOS::sptr<OH_AVBuffer>> inputBufferMap_;    // Buffer模式输入BufferMap
    std::shared_ptr<NativeVideoEncoderCallback> callback_ = nullptr;
    bool isSetMemoryCallback_ = false;
    bool isInputSurfaceMode_ = false;  // Surface模式标志
    std::shared_mutex objListMutex_;    // 线程安全读写锁
};
```

**双模式关键区别**：
- `isInputSurfaceMode_ = true` → Surface 模式（应用通过 `GetSurface` 获取 Surface 并写入图像数据）
- `isInputSurfaceMode_ = false` → Buffer 模式（应用通过 `PushInputBuffer` 推送编码数据）

### 2.3 与 VideoDecoderObject 对比

| 字段 | VideoDecoderObject | VideoEncoderObject |
|------|-------------------|-------------------|
| 模式标志 | `isOutputSurfaceMode_` | `isInputSurfaceMode_` |
| Surface方向 | `SetSurface`（绑定输出Surface） | `GetSurface`（获取输入Surface） |
| 编码器引擎 | `AVCodecVideoDecoder` | `AVCodecVideoEncoder` |
| 内存Map | inputMemoryMap_/outputMemoryMap_ | inputFormatMap_（参数）/ inputMemoryMap_/outputMemoryMap_ |

---

## 3. NativeVideoEncoderCallback 回调体系

```cpp
// video_encoder_object.h:70-92
class NativeVideoEncoderCallback : public AVCodecCallback,
                                   public MediaCodecCallback,
                                   public MediaCodecParameterCallback {
public:
    // 三种构造：AsyncCallback / ParameterCallback / 标准Callback
    NativeVideoEncoderCallback(struct OH_AVCodec* codec, struct OH_AVCodecAsyncCallback cb, void* userData);
    NativeVideoEncoderCallback(struct OH_AVCodec* codec, OH_VideoEncoder_OnNeedInputParameter onInputParameter,
                               void* userData);
    NativeVideoEncoderCallback(struct OH_AVCodec* codec, struct OH_AVCodecCallback cb, void* userData);
```

三层回调接口继承（`AVCodecCallback` + `MediaCodecCallback` + `MediaCodecParameterCallback`），比 `NativeVideoDecoderCallback`（`native_video_decoder.cpp:78-79`）多继承 `MediaCodecParameterCallback`，支持 `SetParameter` 运行时参数回调。

---

## 4. 创建函数：CreateByMime / CreateByName

### 4.1 CreateByMime

```cpp
// native_video_encoder.cpp:55-70
struct OH_AVCodec *OH_VideoEncoder_CreateByMime(const char *mime)
{
    CHECK_AND_RETURN_RET_LOG(mime != nullptr, nullptr, "Mime is nullptr!");
    CHECK_AND_RETURN_RET_LOG(strlen(mime) < MAX_LENGTH, nullptr, "Mime is too long!");

    static AppEventReporter appEventReporter = AppEventReporter();
    ApiInvokeRecorder apiInvokeRecorder("OH_VideoEncoder_CreateByMime", appEventReporter);

    std::shared_ptr<AVCodecVideoEncoder> videoEncoder = VideoEncoderFactory::CreateByMime(mime);
    CHECK_AND_RETURN_RET_LOG(videoEncoder != nullptr, nullptr, "Video decoder create by mime failed!");

    struct VideoEncoderObject *object = new (std::nothrow) VideoEncoderObject(videoEncoder);
    CHECK_AND_RETURN_RET_LOG(object != nullptr, nullptr, "Video decoder create by mime failed!");

    return object;
}
```

**关键路径**：`OH_VideoEncoder_CreateByMime` → `VideoEncoderFactory::CreateByMime` → 底层硬件/软件编码器选择。

### 4.2 CreateByName

```cpp
// native_video_encoder.cpp:72-87
struct OH_AVCodec *OH_VideoEncoder_CreateByName(const char *name)
{
    CHECK_AND_RETURN_RET_LOG(name != nullptr, nullptr, "Name is nullptr!");
    CHECK_AND_RETURN_RET_LOG(strlen(name) < MAX_LENGTH, nullptr, "Name is too long!");

    static AppEventReporter appEventReporter = AppEventReporter();
    ApiInvokeRecorder apiInvokeRecorder("OH_VideoEncoder_CreateByName", appEventReporter);

    std::shared_ptr<AVCodecVideoEncoder> videoEncoder = VideoEncoderFactory::CreateByName(name);
    CHECK_AND_RETURN_RET_LOG(videoEncoder != nullptr, nullptr, "Video decoder create by name failed!");

    struct VideoEncoderObject *object = new (std::nothrow) VideoEncoderObject(videoEncoder);
    CHECK_AND_RETURN_RET_LOG(object != nullptr, nullptr, "Video decoder create by name failed!");

    return object;
}
```

### 4.3 ApiInvokeRecorder

每个 API 都通过 `ApiInvokeRecorder`（`native_video_encoder.cpp:61/78`）记录调用事件，实现接口级 DFX 统计。

---

## 5. 生命周期七步曲

```cpp
// Destroy: native_video_encoder.cpp:89-113
OH_AVErrCode OH_VideoEncoder_Destroy(struct OH_AVCodec *codec)
{
    CHECK_AND_RETURN_RET_LOG(codec != nullptr, AV_ERR_INVALID_VAL, "Codec is nullptr!");
    CHECK_AND_RETURN_RET_LOG(codec->magic_ == AVMagic::AVCODEC_MAGIC_VIDEO_ENCODER, AV_ERR_INVALID_VAL,
                             "Codec magic error!");

    struct VideoEncoderObject *videoEncObj = reinterpret_cast<VideoEncoderObject *>(codec);

    if (videoEncObj != nullptr && videoEncObj->videoEncoder_ != nullptr) {
        int32_t ret = videoEncObj->videoEncoder_->Release();
        videoEncObj->StopCallback();
        videoEncObj->ClearBufferList();
        if (ret != AVCS_ERR_OK) {
            AVCODEC_LOGE("Video decoder destroy failed!");
            delete codec;
            return AVCSErrorToOHAVErrCode(static_cast<AVCodecServiceErrCode>(ret));
        }
    }
    delete codec;
    return AV_ERR_OK;
}

// Configure: native_video_encoder.cpp:133-170
OH_AVErrCode OH_VideoEncoder_Configure(struct OH_AVCodec *codec, struct OH_AVFormat *format)
{
    // 参数校验：codec!=nullptr, format!=nullptr, magic_==VIDEO_ENCODER
    struct VideoEncoderObject *videoEncObj = reinterpret_cast<VideoEncoderObject *>(codec);
    int32_t ret = videoEncObj->videoEncoder_->Configure(format->format_);
    return AVCSErrorToOHAVErrCode(ret);
}

// Prepare: native_video_encoder.cpp:172-189
OH_AVErrCode OH_VideoEncoder_Prepare(struct OH_AVCodec *codec)
{
    struct VideoEncoderObject *videoEncObj = reinterpret_cast<VideoEncoderObject *>(codec);
    int32_t ret = videoEncObj->videoEncoder_->Prepare();
    return AVCSErrorToOHAVErrCode(ret);
}

// Start: native_video_encoder.cpp:191-216
// Stop: native_video_encoder.cpp:217-240
// Flush: native_video_encoder.cpp:241-262
// Reset: native_video_encoder.cpp:263-286
```

---

## 6. Surface 模式：GetSurface

VideoEncoder 使用 **`GetSurface`** 获取输入 Surface（与 VideoDecoder 的 `SetSurface` 方向相反）：

```cpp
// native_video_encoder.cpp:287-314
OH_AVErrCode OH_VideoEncoder_GetSurface(OH_AVCodec *codec, OHNativeWindow **window)
{
    CHECK_AND_RETURN_RET_LOG(codec != nullptr, AV_ERR_INVALID_VAL, "Codec is nullptr!");
    CHECK_AND_RETURN_RET_LOG(codec->magic_ == AVMagic::AVCODEC_MAGIC_VIDEO_ENCODER ||
                                 OHOS::MediaAVCodec::PreprocessorEncoder::IsPreprocEncoderMagic(codec->magic_),
                             AV_ERR_INVALID_VAL, "Codec magic error!");

    struct VideoEncoderObject *videoEncObj = reinterpret_cast<VideoEncoderObject *>(codec);

    // 检查 magic_ 是否合法
    CHECK_AND_RETURN_RET_LOG(IsValidVideoEncoderMagic(codec->magic_), AV_ERR_INVALID_VAL,
                             "Codec magic error!");

    CHECK_AND_RETURN_RET_LOG(videoEncObj->videoEncoder_ != nullptr, AV_ERR_INVALID_VAL,
                             "Video encoder is nullptr!");

    // 调用编码器内部 GetSurface 获取 NativeWindow
    OHNativeWindow *nativeWindow = videoEncObj->videoEncoder_->GetSurface();
    CHECK_AND_RETURN_RET_LOG(nativeWindow != nullptr, AV_ERR_UNKNOWN, "NativeWindow is nullptr!");

    *window = nativeWindow;
    videoEncObj->isInputSurfaceMode_ = true;  // 标记 Surface 模式

    return AV_ERR_OK;
}
```

**Surface 模式工作流**：
1. `OH_VideoEncoder_Configure` → 配置编码参数
2. `OH_VideoEncoder_Prepare` → 准备编码器
3. `OH_VideoEncoder_GetSurface` → 获取输入 Surface（`isInputSurfaceMode_ = true`）
4. 应用向 Surface 写入图像数据（Camera 预览、EGL 渲染等）
5. `OH_VideoEncoder_Start` → 启动编码
6. 编码器自动从 Surface 读取数据并编码输出

---

## 7. Buffer 模式：PushInputBuffer / GetOutputDescription

### 7.1 PushInputBuffer（Buffer 模式输入）

```cpp
// native_video_encoder.cpp:536-552
OH_AVErrCode OH_VideoEncoder_PushInputBuffer(struct OH_AVCodec *codec, uint32_t index)
{
    CHECK_AND_RETURN_RET_LOG(codec != nullptr, AV_ERR_INVALID_VAL, "Codec is nullptr!");
    CHECK_AND_RETURN_RET_LOG(IsValidVideoEncoderMagic(codec->magic_), AV_ERR_INVALID_VAL,
                             "Codec magic error!");

    struct VideoEncoderObject *videoEncObj = reinterpret_cast<VideoEncoderObject *>(codec);
    CHECK_AND_RETURN_RET_LOG(videoEncObj->videoEncoder_ != nullptr, AV_ERR_INVALID_VAL,
                             "Video encoder is nullptr!");

    int32_t ret = videoEncObj->videoEncoder_->PushInputBuffer(index);
    return AVCSErrorToOHAVErrCode(ret);
}
```

### 7.2 GetOutputDescription（查询输出格式）

```cpp
// native_video_encoder.cpp:316-337
OH_AVFormat *OH_VideoEncoder_GetOutputDescription(struct OH_AVCodec *codec)
{
    // PreprocessorEncoder 特殊路径
    if (codec->magic_ == AVMagic::AVCODEC_MAGIC_PREPROCESSOR_ENCODER) {
        auto preprocEnc = PreprocessorEncoder::GetPreprocEncoderFromBase(codec);
        return preprocEnc->GetOutputDescription();
    }

    struct VideoEncoderObject *videoEncObj = reinterpret_cast<VideoEncoderObject *>(codec);
    auto format = videoEncObj->videoEncoder_->GetOutputDescription();
    if (format == nullptr) {
        return nullptr;
    }

    OH_AVFormat *avFormat = new (std::nothrow) OH_AVFormat();
    if (avFormat == nullptr) {
        return nullptr;
    }
    avFormat->format_ = format;
    avFormat->magic_ = MFMagic::MFMAGIC_FORMAT;
    return avFormat;
}
```

---

## 8. SetParameter 运行时参数

```cpp
// native_video_encoder.cpp:405-427
OH_AVErrCode OH_VideoEncoder_SetParameter(struct OH_AVCodec *codec, struct OH_AVFormat *format)
{
    CHECK_AND_RETURN_RET_LOG(codec != nullptr, AV_ERR_INVALID_VAL, "Codec is nullptr!");
    CHECK_AND_RETURN_RET_LOG(IsValidVideoEncoderMagic(codec->magic_), AV_ERR_INVALID_VAL,
                             "Codec magic error!");
    CHECK_AND_RETURN_RET_LOG(format != nullptr, AV_ERR_INVALID_VAL, "Format is nullptr!");

    struct VideoEncoderObject *videoEncObj = reinterpret_cast<VideoEncoderObject *>(codec);
    CHECK_AND_RETURN_RET_LOG(videoEncObj->videoEncoder_ != nullptr, AV_ERR_INVALID_VAL,
                             "Video encoder is nullptr!");

    int32_t ret = videoEncObj->videoEncoder_->SetParameter(format->format_);
    CHECK_AND_RETURN_RET_LOG(ret == AVCS_ERR_OK, AVCSErrorToOHAVErrCode(
                             static_cast<AVCodecServiceErrCode>(ret)),
                             "Video encoder set parameter failed!");
    return AV_ERR_OK;
}
```

编码过程中可动态调整参数（如码率、帧率）。`NativeVideoEncoderCallback` 支持 `MediaCodecParameterCallback`，允许编码器通过 `OnInputParameter` 回调通知应用新的参数生效。

---

## 9. 双回调注册路径

VideoEncoder 支持三种回调注册方式（比 VideoDecoder 多一种）：

```cpp
// 方式1：AsyncCallback（推荐，Buffer 模式）
// native_video_encoder.cpp:429-452
OH_AVErrCode OH_VideoEncoder_SetCallback(struct OH_AVCodec *codec,
    struct OH_AVCodecAsyncCallback callback, void *userData)
{
    struct VideoEncoderObject *videoEncObj = reinterpret_cast<VideoEncoderObject *>(codec);
    videoEncObj->callback_ = std::make_shared<NativeVideoEncoderCallback>(codec, callback, userData);
    int32_t ret = videoEncObj->videoEncoder_->SetCallback(videoEncObj->callback_);
    return AVCSErrorToOHAVErrCode(ret);
}

// 方式2：标准 Callback（双回调 onNeedInputBuffer / onNewOutputBuffer）
// native_video_encoder.cpp:454-482
OH_AVErrCode OH_VideoEncoder_RegisterCallback(struct OH_AVCodec *codec,
    struct OH_AVCodecCallback callback, void *userData)
{
    struct VideoEncoderObject *videoEncObj = reinterpret_cast<VideoEncoderObject *>(codec);
    videoEncObj->callback_ = std::make_shared<NativeVideoEncoderCallback>(codec, callback, userData);
    int32_t ret = videoEncObj->videoEncoder_->SetCallback(videoEncObj->callback_);
    return AVCSErrorToOHAVErrCode(ret);
}

// 方式3：ParameterCallback（特有，支持 SetParameter 动态参数回调）
// native_video_encoder.cpp:484-508
OH_AVErrCode OH_VideoEncoder_RegisterParameterCallback(OH_AVCodec *codec,
    OH_VideoEncoder_OnNeedInputParameter onInputParameter, void *userData)
{
    struct VideoEncoderObject *videoEncObj = reinterpret_cast<VideoEncoderObject *>(codec);
    videoEncObj->callback_ = std::make_shared<NativeVideoEncoderCallback>(codec, onInputParameter, userData);
    int32_t ret = videoEncObj->videoEncoder_->SetCallback(videoEncObj->callback_);
    return AVCSErrorToOHAVErrCode(ret);
}
```

**VideoEncoder 独有 `RegisterParameterCallback`**：允许应用在编码过程中接收新的编码参数（码率变化、IDR帧请求等）。

---

## 10. PushInputData（带属性输入）

```cpp
// native_video_encoder.cpp:510-534
OH_AVErrCode OH_VideoEncoder_PushInputData(struct OH_AVCodec *codec, uint32_t index,
    OH_AVCodecBufferAttr attr)
{
    // attr: pts (int64_t) / size (uint32_t) / offset (uint32_t) / flags (int32_t)
    // 用于 Buffer 模式：携带 PTS 和帧标志（EOS / KEY_FRAME 等）
    CHECK_AND_RETURN_RET_LOG(codec != nullptr, AV_ERR_INVALID_VAL, "Codec is nullptr!");
    CHECK_AND_RETURN_RET_LOG(IsValidVideoEncoderMagic(codec->magic_), AV_ERR_INVALID_VAL,
                             "Codec magic error!");

    struct VideoEncoderObject *videoEncObj = reinterpret_cast<VideoEncoderObject *>(codec);
    int32_t ret = videoEncObj->videoEncoder_->PushInputData(index, attr);
    return AVCSErrorToOHAVErrCode(ret);
}
```

---

## 11. CodecClient IPC 代理路径

VideoEncoder C API 的跨进程调用链与 VideoDecoder 相同：

```
OH_VideoEncoder_CreateByMime()
  → VideoEncoderFactory::CreateByMime()
    → CodecClient::Init()  (通过 Binder IPC)
      → CodecServiceProxy（C++ 客户端代理）
        → CodecServer（服务端实现）
          → AVCodecVideoEncoder 引擎
```

在 CodecServer 端，实际编码由 `SurfaceEncoderAdapter` + `AVCodecVideoEncoder` 处理（S36/S42 已覆盖）。

---

## 12. 与 VideoDecoder C API 对比速查

| 特性 | VideoDecoder | VideoEncoder |
|------|------------|-------------|
| Surface 方向 | `SetSurface`（绑定输出Surface） | `GetSurface`（获取输入Surface） |
| Surface 标志 | `isOutputSurfaceMode_` | `isInputSurfaceMode_` |
| 生命周期 | Create→Configure→Prepare→Start→Stop→Flush→Reset→Destroy | 同 |
| 参数回调 | 无 | `RegisterParameterCallback`（独有） |
| 输出描述 | `GetOutputDescription` | `GetOutputDescription` |
| Buffer输入 | `PushInputBuffer` | `PushInputBuffer` |
| 数据回调 | `OnNeedInputBuffer`/`OnNewOutputBuffer` | 同 |
| API实现文件 | `native_video_decoder.cpp:329-841` | `native_video_encoder.cpp:55-570` |
| 对象定义 | `VideoDecoderObject` | `VideoEncoderObject` |

---

## 13. 关联记忆

| ID | 说明 |
|----|------|
| `MEM-ARCH-AVCODEC-S83` | AVCodec Native C API 总览（四类 API 家族，OH_AVCodec 对象模型） |
| `MEM-ARCH-AVCODEC-S42` | AVCodecVideoEncoder 视频编码器核心实现（三层架构） |
| `MEM-ARCH-AVCODEC-S36` | VideoEncoderFilter 视频编码过滤器（Filter层封装） |
| `MEM-ARCH-AVCODEC-S2` | interfaces/kits/c/ API 使用场景与 key 搭配 |
| `MEM-ARCH-AVCODEC-S21` | AVCodec IPC 架构（CodecServiceProxy ↔ CodecServiceStub） |

---

## 14. 快速参考

**VideoEncoder Surface 模式接入最短路径**：
```c
// 1. 创建编码器
OH_AVCodec *enc = OH_VideoEncoder_CreateByMime("video/avc");

// 2. 注册异步回调
OH_AVCodecAsyncCallback cb = { .onError = MyOnError,
    .onStreamChanged = MyOnStreamChanged,
    .onNeedInputBuffer = MyOnNeedInput,
    .onNewOutputBuffer = MyOnNewOutput };
OH_VideoEncoder_SetCallback(enc, cb, userData);

// 3. Configure
OH_AVFormat *fmt = OH_AVFormat_Create();
OH_AVFormat_SetIntValue(fmt, "width", 1920);
OH_AVFormat_SetIntValue(fmt, "height", 1080);
OH_AVFormat_SetIntValue(fmt, "bitrate", 10 * 1000 * 1000);
OH_AVFormat_SetIntValue(fmt, "pixel_format", 1);  // 1=NV12
OH_AVFormat_SetStringValue(fmt, "codec_mime", "video/avc");
OH_VideoEncoder_Configure(enc, fmt);

// 4. Prepare → GetSurface → Start
OHNativeWindow *surface;
OH_VideoEncoder_Prepare(enc);
OH_VideoEncoder_GetSurface(enc, &surface);  // isInputSurfaceMode_ = true
OH_VideoEncoder_Start(enc);

// 5. 向 surface 写入图像数据（Camera/EGL）→ 编码器自动编码
// 6. onNewOutputBuffer 收到编码输出 → 写入文件/RTMP等
```

**关键约束**：
- Surface 模式：先 `Prepare` 再 `GetSurface`（`Prepare` 前调用返回 `AV_ERR_OPERATE_NOT_ALLOWED`）
- `isInputSurfaceMode_ = true` 时不能再调用 `PushInputBuffer`
- `RegisterParameterCallback` 仅 VideoEncoder 独有，VideoDecoder 不支持
- `PushInputBuffer` vs `PushInputData`：后者携带 `OH_AVCodecBufferAttr`（PTS + flags）
