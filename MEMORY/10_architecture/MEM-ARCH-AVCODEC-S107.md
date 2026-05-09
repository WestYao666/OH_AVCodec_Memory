# MEM-ARCH-AVCODEC-S107: VideoEncoder C API 实现——NativeVideoEncoder 对象模型与 Surface/Buffer 双模式

## Status

```
status: pending_approval
builder: subagent-builder
generated: 2026-05-09T09:50
scope: AVCodec, Native API, C API, VideoEncoder, SurfaceMode, BufferMode, CodecClient, OH_VideoEncoder
关联主题: S83(CAPI总览)/S84(VideoEncoder C API草案)/S42(VideoEncoder核心)/S70(CodecFactory)/S36(VideoEncoderFilter)
```

## 主题

VideoEncoder C API 实现——NativeVideoEncoder 对象模型与 Surface/Buffer 双模式

## 摘要

本文档基于 `native_video_encoder.cpp` (715行) + `video_encoder_object.h` (92行) + `surface_encoder_adapter.cpp` + `surface_encoder_filter.cpp` 源码，分析 OH_VideoEncoder C API 的完整实现链路。核心对象 VideoEncoderObject 持有 `videoEncoder_` (AVCodecVideoEncoder)，支持 Surface 模式（`OH_VideoEncoder_GetSurface`）和 Buffer 模式（`PushInputBuffer`）两种输入路径，通过 isInputSurfaceMode_ 标志互斥。Filter 管线层 `SurfaceEncoderFilter` 注册名为 "builtin.recorder.videoencoder"，FILTERTYPE_VENC，五状态机（IDLE→RECORDING→PAUSED→STOPPED→ERROR）。

---

## 一、NativeVideoEncoder C API 全景

### 1.1 接口定位

```
interfaces/kits/c/native_avcodec_videoencoder.h
interfaces/kits/c/native_avcodec_base.h
frameworks/native/capi/avcodec/native_video_encoder.cpp  (715行实现)
frameworks/native/capi/avcodec/video_encoder_object.h   (92行对象定义)
```

### 1.2 OH_VideoEncoder C API 清单

| API | 签名 | 功能 |
|-----|------|------|
| `OH_VideoEncoder_CreateByMime` | `(const char* mime) → OH_AVCodec*` | 按 MIME 创建编码器实例 |
| `OH_VideoEncoder_CreateByName` | `(const char* name) → OH_AVCodec*` | 按注册名创建编码器实例 |
| `OH_VideoEncoder_Destroy` | `(OH_AVCodec*)` | 销毁编码器实例 |
| `OH_VideoEncoder_Start` | `(OH_AVCodec*)` | 启动编码器 |
| `OH_VideoEncoder_Stop` | `(OH_AVCodec*)` | 停止编码器 |
| `OH_VideoEncoder_Flush` | `(OH_AVCodec*)` | 刷新编码器 |
| `OH_VideoEncoder_GetSurface` | `(OH_AVCodec*, OHNativeWindow**)` | 获取 Surface（Surface模式入口） |
| `OH_VideoEncoder_SetParameter` | `(OH_AVCodec*, OH_AVFormat*)` | 设置编码参数 |
| `OH_VideoEncoder_GetOutputDescription` | `(OH_AVCodec*) → OH_AVFormat*` | 获取输出格式 |
| `OH_VideoEncoder_FreeOutputData` | `(OH_AVCodec*, uint32_t index)` | 释放输出缓冲区 |
| `OH_VideoEncoder_FreeOutputBuffer` | `(OH_AVCodec*, uint32_t index)` | 释放输出缓冲区（Buffer模式） |
| `OH_VideoEncoder_PushInputData` | `(OH_AVCodec*, uint32_t index, OH_AVMemory*)` | 推送输入数据（Memory模式） |
| `OH_VideoEncoder_PushInputBuffer` | `(OH_AVCodec*, uint32_t index, OH_AVBuffer*)` | 推送输入Buffer（Buffer模式） |
| `OH_VideoEncoder_RegisterCallback` | `(OH_AVCodec*, OH_AVCodecCallback, void*)` | 注册回调 |
| `OH_VideoEncoder_RegisterCallbackEx` | `(OH_AVCodec*, OH_AVCodecAsyncCallback, void*)` | 注册异步回调 |
| `OH_VideoEncoder_RegisterParameterCallback` | `(OH_AVCodec*, OH_VideoEncoder_OnNeedInputParameter, void*)` | 注册参数回调 |

---

## 二、VideoEncoderObject 对象模型

### 2.1 类层次结构

```
video_encoder_object.h:34-45
struct VideoEncoderObject : public OH_AVCodec {
    const std::shared_ptr<AVCodecVideoEncoder> videoEncoder_;  // 底层引擎
    std::queue<OHOS::sptr<MFObjectMagic>> tempList_;
    std::unordered_map<uint32_t, OHOS::sptr<OH_AVFormat>> inputFormatMap_;
    std::unordered_map<uint32_t, OHOS::sptr<OH_AVMemory>> outputMemoryMap_;
    std::unordered_map<uint32_t, OHOS::sptr<OH_AVMemory>> inputMemoryMap_;
    std::unordered_map<uint32_t, OHOS::sptr<OH_AVBuffer>> outputBufferMap_;
    std::unordered_map<uint32_t, OHOS::sptr<OH_AVBuffer>> inputBufferMap_;
    std::shared_ptr<NativeVideoEncoderCallback> callback_ = nullptr;
    bool isSetMemoryCallback_ = false;
    bool isInputSurfaceMode_ = false;  // ⚠️ Surface/Buffer互斥标志
    std::shared_mutex objListMutex_;
};
```

### 2.2 双重回调桥接

`NativeVideoEncoderCallback` 继承三条回调链路：

```
video_encoder_object.h:47-73
class NativeVideoEncoderCallback : public AVCodecCallback,    // 引擎→CodecCallback
                                   public MediaCodecCallback, // 引擎内部
                                   public MediaCodecParameterCallback { // 参数回调
    OnError(...)       // 错误回调
    OnOutputFormatChanged(...) // 格式变化
    OnInputBufferAvailable(index, AVSharedMemory)   // Memory模式输入请求
    OnOutputBufferAvailable(index, info, flag, buffer) // 输出可用
    OnInputBufferAvailable(index, AVBuffer)          // Buffer模式输入请求
    OnOutputBufferAvailable(index, AVBuffer)         // Buffer模式输出
    OnInputParameterAvailable(index, Format)         // 参数输入请求
};
```

---

## 三、CreateByMime / CreateByName 工厂路由

### 3.1 C API 层工厂分发

```
native_video_encoder.cpp:55-70
struct OH_AVCodec *OH_VideoEncoder_CreateByMime(const char *mime)
{
    static AppEventReporter appEventReporter = AppEventReporter();
    ApiInvokeRecorder apiInvokeRecorder("OH_VideoEncoder_CreateByMime", appEventReporter);

    std::shared_ptr<AVCodecVideoEncoder> videoEncoder = VideoEncoderFactory::CreateByMime(mime);
    struct VideoEncoderObject *object = new (std::nothrow) VideoEncoderObject(videoEncoder);
    return object;
}

native_video_encoder.cpp:72-85
struct OH_AVCodec *OH_VideoEncoder_CreateByName(const char *name)
{
    static AppEventReporter appEventReporter = AppEventReporter();
    ApiInvokeRecorder apiInvokeRecorder("OH_VideoEncoder_CreateByName", appEventReporter);

    std::shared_ptr<AVCodecVideoEncoder> videoEncoder = VideoEncoderFactory::CreateByName(name);
    struct VideoEncoderObject *object = new (std::nothrow) VideoEncoderObject(videoEncoder);
    return object;
}
```

### 3.2 VideoEncoderFactory 四路重载

```
interfaces/inner_api/native/avcodec_video_encoder.h:337-414
class VideoEncoderFactory {
    // 路径1：C API层（无format参数）
    static std::shared_ptr<AVCodecVideoEncoder> CreateByMime(const std::string &mime);
    static std::shared_ptr<AVCodecVideoEncoder> CreateByName(const std::string &name);

    // 路径2：Filter层/内部调用（带format参数，返回int32_t错误码）
    static int32_t CreateByMime(const std::string &mime, Format &format,
                                std::shared_ptr<AVCodecVideoEncoder> &encodec);
    static int32_t CreateByName(const std::string &name, Format &format,
                                std::shared_ptr<AVCodecVideoEncoder> &encodec);
};
```

### 3.3 PreprocessorEncoder 特殊路径

C API 层通过 magic number 识别 PreprocessorEncoder（预处理器编码器）：

```
native_video_encoder.cpp:95-112
if (PreprocessorEncoder::IsPreprocEncoderMagic(codec->magic_)) {
    auto *preprocEnc = reinterpret_cast<PreprocessorEncoder*>(codec);
    (void)preprocEnc->Release();
    if (!PreprocessorEncoder::IsPrimaryEncoderMagic(codec->magic_)) {
        preprocEnc->DetachFromPrimaryEncoder();
        delete preprocEnc;
        return AV_ERR_OK;
    }
}
```

---

## 四、Surface 模式 vs Buffer 模式双路径

### 4.1 isInputSurfaceMode_ 互斥标志

```
video_encoder_object.h:50
bool isInputSurfaceMode_ = false;  // 默认Buffer模式
```

触发切换：

```
native_video_encoder.cpp:311
videoEncObj->isInputSurfaceMode_ = true;  // OH_VideoEncoder_GetSurface 调用后
```

### 4.2 Surface 模式完整链路

```
OH_VideoEncoder_GetSurface (native_video_encoder.cpp:287)
  → videoEncObj->videoEncoder_->CreateInputSurface()
  → CreateNativeWindowFromSurface(&surface)
  → videoEncObj->isInputSurfaceMode_ = true
```

在 Filter 层（SurfaceEncoderAdapter）：
- `CreateInputSurface()` → `codecServer_->CreateInputSurface()` (surface_encoder_adapter.cpp:332)
- Surface 模式时编码器状态机：IDLE → RECORDING → PAUSED → STOPPED

### 4.3 Buffer 模式输入

```
OH_VideoEncoder_PushInputBuffer(OH_AVCodec *codec, uint32_t index, OH_AVBuffer *buffer)
  → videoEncObj->videoEncoder_->PushInputBuffer(index, buffer)
```

```
OH_VideoEncoder_PushInputData(OH_AVCodec *codec, uint32_t index, OH_AVMemory *data)
  → videoEncObj->videoEncoder_->PushInputData(index, data)  // Memory模式
```

### 4.4 输出释放

```
OH_VideoEncoder_FreeOutputBuffer(OH_AVCodec *codec, uint32_t index)  // Buffer模式
  → videoEncObj->videoEncoder_->ReleaseOutputBuffer(index)

OH_VideoEncoder_FreeOutputData(OH_AVCodec *codec, uint32_t index)   // Memory模式
  → videoEncObj->videoEncoder_->ReleaseOutputBuffer(index)
```

---

## 五、Filter 层封装：SurfaceEncoderFilter

### 5.1 静态注册

```
surface_encoder_filter.cpp:33-36
static AutoRegisterFilter<SurfaceEncoderFilter> g_registerSurfaceEncoderFilter(
    "builtin.recorder.videoencoder",
    FilterType::FILTERTYPE_VENC,
    [](const std::string& name) {
        return std::make_shared<SurfaceEncoderFilter>(name, FilterType::FILTERTYPE_VENC);
    });
```

### 5.2 ProcessStateCode 五状态机

```
surface_encoder_adapter.h:47-55
enum class ProcessStateCode {
    IDLE,       // 初始
    RECORDING,  // 编码中
    PAUSED,     // 暂停
    STOPPED,    // 停止
    ERROR       // 错误
};
```

状态转换证据（surface_encoder_adapter.cpp）：

| 当前状态 | 条件 | 下一状态 | 代码行 |
|---------|------|---------|--------|
| IDLE | DoStart() | RECORDING | 354,468 |
| RECORDING | DoPause() | PAUSED | 437 |
| PAUSED | DoResume() | RECORDING | 468 |
| RECORDING/PAUSED | DoStop() | STOPPED | 409 |
| any | 错误 | ERROR | 358,413,486,505 |

### 5.3 三层架构（Filter → Adapter → CodecEngine）

```
SurfaceEncoderFilter  (Filter层)
  ↓ 持有
SurfaceEncoderAdapter  (适配层，surface_encoder_adapter.cpp)
  ↓ 调用
AVCodecVideoEncoder   (引擎层)
```

Filter 层不直接持有 AVCodecVideoEncoder，而是通过 SurfaceEncoderAdapter 间接持有。SurfaceEncoderAdapter::Init() 调用 `VideoEncoderFactory::CreateByMime(mime, format, codecServer_)` 获取编码器实例。

---

## 六、生命周期七步曲

```
① OH_VideoEncoder_CreateByMime(name)
    → VideoEncoderObject(videoEncoder_)  // 构建CAPI对象

② OH_VideoEncoder_Configure(codec, format)
    → videoEncoder_->Configure(format)   // 配置宽高/码率/帧率等

③ [Surface模式] OH_VideoEncoder_GetSurface()
    → isInputSurfaceMode_ = true
    → codecServer_->CreateInputSurface()

  [Buffer模式] 使用 PushInputBuffer 推送数据

④ OH_VideoEncoder_Start(codec)
    → videoEncoder_->Start()

⑤ [编码循环]
    - Surface模式：Surface数据自动输入
    - Buffer模式：OnInputBufferAvailable回调 → PushInputBuffer → FreeOutputData

⑥ OH_VideoEncoder_Stop(codec)
    → videoEncoder_->Stop()

⑦ OH_VideoEncoder_Destroy(codec)
    → videoEncoder_->Release()
    → delete videoEncObj
```

---

## 七、错误码转换

```
native_video_encoder.cpp
AVCSErrorToOHAVErrCode(static_cast<AVCodecServiceErrCode>(ret))
  AVCS_ERR_OK (0)           → AV_ERR_OK (0)
  AVCS_ERR_INVALID_VAL      → AV_ERR_INVALID_VAL
  AVCS_ERR_OPERATE_NOT_PERMIT → AV_ERR_OPERATE_NOT_PERMIT
  AVCS_ERR_UNKNOWN          → AV_ERR_UNKNOWN
```

---

## 八、与其他主题的关联

| 关联主题 | 关系 |
|---------|------|
| S83 (CAPI总览) | S107 是 S83 的 VideoEncoder 子主题深度展开 |
| S84 (VideoEncoder C API草案) | S107 为 S84 的源码增强版，含行号级证据 |
| S42 (VideoEncoder核心) | S107 侧重 CAPI 层，S42 侧重引擎层 CodecBase 架构 |
| S70 (CodecFactory) | VideoEncoderFactory::CreateByMime/CreateByName 是本主题工厂分发路由的实现 |
| S36 (VideoEncoderFilter) | SurfaceEncoderFilter 是本主题 Filter 层封装的下游组件 |
| S85 (PreprocessorManager) | PreprocessorEncoder 通过 magic 识别，与本主题 Surface 模式交叉 |

---

## Evidence 汇总

| 证据类型 | 文件 | 行号 | 说明 |
|---------|------|------|------|
| C API实现 | native_video_encoder.cpp | 55-70 | CreateByMime/CreateByName 工厂分发 |
| Surface模式标志 | video_encoder_object.h | 50 | isInputSurfaceMode_ 互斥标志 |
| GetSurface实现 | native_video_encoder.cpp | 287-320 | GetSurface → CreateInputSurface |
| ProcessStateCode | surface_encoder_adapter.h | 47-55 | 五状态机枚举 |
| 状态转换证据 | surface_encoder_adapter.cpp | 354,437,468,409,358 | RECORDING/PAUSED/STOPPED/ERROR |
| Filter注册 | surface_encoder_filter.cpp | 33-36 | "builtin.recorder.videoencoder" 静态注册 |
| Factory声明 | avcodec_video_encoder.h | 337-414 | CreateByMime/CreateByName 四路重载 |
| Preprocessor识别 | native_video_encoder.cpp | 95-112 | magic number 区分 PreprocessorEncoder |
| 回调桥接类 | video_encoder_object.h | 47-73 | NativeVideoEncoderCallback 三重继承 |
| Adapter.CreateInputSurface | surface_encoder_adapter.cpp | 332 | codecServer_->CreateInputSurface() |
