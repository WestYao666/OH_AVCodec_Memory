---
id: MEM-ARCH-AVCODEC-S95
title: "AudioCodec C API 实现——AudioCodecObject + AVCodecAudioCodecImpl 三层架构"
scope: [AVCodec, Native API, C API, AudioCodec, AudioEncoder, AudioDecoder, BufferMode, OH_AVBuffer, OH_AVCodec, IPC, CodecClient]
status: draft
created_by: builder-agent
created_at: "2026-05-07T14:45:00+08:00"
evidence_source: /home/west/av_codec_repo/frameworks/native/capi/avcodec/native_audio_codec.cpp (573行)
evidence_source2: /home/west/av_codec_repo/frameworks/native/avcodec/avcodec_audio_codec_impl.cpp (未知行数)
evidence_source3: /home/west/av_codec_repo/frameworks/native/capi/avcodec/native_audio_encoder.cpp (495行)
---

# MEM-ARCH-AVCODEC-S95: AudioCodec C API 实现——AudioCodecObject + AVCodecAudioCodecImpl 三层架构

## 1. 概述

AVCodec Native C API 中存在**两套**音频 Codec API：

| API | 对象类型 | 封装引擎 | 缓冲区模式 | 用途 |
|-----|---------|---------|-----------|------|
| `OH_AudioCodec_*` (统一 API) | `AudioCodecObject` | `AVCodecAudioCodecImpl` | **Buffer 模式** (`OH_AVBuffer`) | 统一创建 Encoder/Decoder |
| `OH_AudioEncoder_*` (专用 API) | `AudioEncoderObject` | `AVCodecAudioEncoder` | **Memory 模式** (`OH_AVMemory`) | 专用编码器 |

**核心定位**：`OH_AudioCodec_*` 是 OpenHarmony AVCodec 统一音频 Codec C API，可通过 `isEncoder` 参数同时创建音频编码器和解码器，底层由 `AVCodecAudioCodecImpl` 驱动，使用 Buffer 模式（`OH_AVBuffer`）进行数据传递，与 Memory 模式的 `OH_AudioEncoder_*` 形成互补。

**适用场景**：
- 三方应用通过统一 API 接入音频编码/解码
- 需要使用 Buffer 模式（`OH_AVBuffer`）进行音频数据传递
- 需要动态切换编码器/解码器类型
- DRM 解密配置（`OH_AudioCodec_SetDecryptionConfig`）

**未覆盖区域**：
- `AVCodecAudioCodecImpl` 的状态机此前无独立记忆条目
- `AudioCodecProducerListener`（`IRemoteStub<IProducerListener>`）此前无证据
- `OH_AudioCodec_QueryInputBuffer`/`QueryOutputBuffer` 超时查询此前无证据
- `OH_AudioCodec_SetDecryptionConfig` DRM 配置此前无独立分析

## 2. 核心架构

### 2.1 两套 Audio C API 对比

```
OH_AudioCodec_* (统一 API)                    OH_AudioEncoder_* (专用 API)
├── AudioCodecObject(OH_AVCodec)              AudioEncoderObject(OH_AVCodec)
│   └── AVCodecAudioCodecImpl                └── AVCodecAudioEncoder
├── OH_AVCodecCallback (Buffer模式)            NativeAudioEncoderCallback (Memory模式)
│   ├── onNeedInputBuffer(index, buffer)      ├── onInputBufferAvailable(index, buffer)
│   └── onNewOutputBuffer(index, buffer)      └── onOutputBufferAvailable(index, buffer)
├── OH_AVBuffer (Buffer模式)                   OH_AVMemory (Memory模式)
└── isEncoder 标志决定类型                     仅限 Encoder
```

**关键区别**：

| 特性 | `OH_AudioCodec_*` | `OH_AudioEncoder_*` |
|------|-------------------|---------------------|
| 对象封装 | `AudioCodecObject` | `AudioEncoderObject` |
| 底层引擎 | `AVCodecAudioCodecImpl` | `AVCodecAudioEncoder` |
| 缓冲区类型 | `OH_AVBuffer` | `OH_AVMemory` |
| 创建方式 | `OH_AudioCodec_CreateByMime(mime, isEncoder)` | `OH_AudioEncoder_CreateByMime(mime)` |
| DRM 支持 | ✅ `SetDecryptionConfig` | ❌ |
| 回调类型 | `OH_AVCodecCallback` | `OH_AVCodecAsyncCallback` |

### 2.2 AudioCodecObject 对象模型

**所在文件**：`native_audio_codec.cpp:42`（结构体定义）

```cpp
struct AudioCodecObject : public OH_AVCodec {
    explicit AudioCodecObject(const std::shared_ptr<AVCodecAudioCodecImpl> &decoder)
        : OH_AVCodec(AVMagic::AVCODEC_MAGIC_AUDIO_DECODER), audioCodec_(decoder)
    {
    }

    const std::shared_ptr<AVCodecAudioCodecImpl> audioCodec_;
    std::list<OHOS::sptr<OH_AVBuffer>> bufferObjList_;   // Buffer 模式缓冲区列表
    std::shared_ptr<NativeAudioCodec> callback_ = nullptr;
    std::atomic<bool> isFlushing_ = false;
    std::atomic<bool> isFlushed_ = false;
    std::atomic<bool> isStop_ = false;
    std::atomic<bool> isEOS_ = false;
    std::shared_mutex memoryObjListMutex_;
};
```

**AudioEncoderObject 对象模型**（对比）：
- **所在文件**：`native_audio_encoder.cpp:37`
- **底层引擎**：`AVCodecAudioEncoder`（非 `AVCodecAudioCodecImpl`）
- **缓冲区类型**：`OH_AVMemory`（Memory 模式）

```cpp
struct AudioEncoderObject : public OH_AVCodec {
    explicit AudioEncoderObject(const std::shared_ptr<AVCodecAudioEncoder> &encoder)
        : OH_AVCodec(AVMagic::AVCODEC_MAGIC_AUDIO_ENCODER), audioEncoder_(encoder)
    {
    }

    const std::shared_ptr<AVCodecAudioEncoder> audioEncoder_;
    std::list<OHOS::sptr<OH_AVMemory>> memoryObjList_;   // Memory 模式缓冲区列表
    std::shared_ptr<NativeAudioEncoderCallback> callback_ = nullptr;
    std::atomic<bool> isFlushing_ = false;
    std::atomic<bool> isFlushed_ = false;
    std::atomic<bool> isStop_ = false;
    std::atomic<bool> isEOS_ = false;
};
```

### 2.3 AVCodecAudioCodecImpl 引擎类

**所在文件**：`avcodec_audio_codec_impl.h:32`（类定义）

**关键组件**：

```cpp
class AVCodecAudioCodecImpl {
    // 内部回调（继承 MediaCodecCallback）
    class AVCodecInnerCallback : public MediaCodecCallback { ... };

    // 缓冲区信息
    class OutputInfo { ... };

    // 异步任务线程
    std::unique_ptr<TaskThread> inputTask_;   // OS_ACodecIn
    std::unique_ptr<TaskThread> outputTask_;   // OS_ACodecOut

    // 消费者/生产者监听器
    AudioCodecConsumerListener* implConsumer_;  // 输入侧监听器
    AudioCodecProducerListener* implProducer_;  // 输出侧监听器
};
```

**关键设计**：

- **双 TaskThread 异步驱动**：`OS_ACodecIn`（输入处理）和 `OS_ACodecOut`（输出处理）
- **`AudioCodecConsumerListener`**：实现 `Media::IConsumerListener`，当输入缓冲区可用时通过 `Notify()` 驱动
- **`AudioCodecProducerListener`**：实现 `IRemoteStub<Media::IProducerListener>`，当输出缓冲区可用时通知消费者
- **`AVCodecInnerCallback`**：继承 `MediaCodecCallback`，接收底层引擎的缓冲区事件

### 2.4 NativeAudioCodec 回调桥接器

**所在文件**：`native_audio_codec.cpp:83`（类定义）

```cpp
class NativeAudioCodec : public AVCodecCallback {
    NativeAudioCodec(OH_AVCodec *codec, struct OH_AVCodecCallback cb, void *userData)
        : codec_(codec), callback_(cb), userData_(userData) {}

    // 错误回调
    void OnError(AVCodecCallback::ExtErrorCode extErr) override
    {
        if (codec_ != nullptr && callback_.onError != nullptr)
            callback_.onError(codec_, extErr, userData_);
    }

    // 格式变化回调
    void OnStreamChanged(std::shared_ptr<AVBuffer> object) override
    {
        if (codec_ != nullptr && callback_.onStreamChanged != nullptr)
            callback_.onStreamChanged(codec_, reinterpret_cast<OH_AVFormat *>(object.GetRefPtr()), userData_);
    }

    // 输入缓冲区需求回调
    void OnNeedInputBuffer(uint32_t index, std::shared_ptr<AVBuffer> buffer) override
    {
        if (codec_ != nullptr && callback_.onNeedInputBuffer != nullptr) {
            struct AudioCodecObject *audioCodecObj = reinterpret_cast<AudioCodecObject *>(codec_);
            uint8_t *data = buffer->GetMemory()->GetBase();
            callback_.onNeedInputBuffer(codec_, index, data, userData_);
        }
    }

    // 输出缓冲区就绪回调
    void OnNewOutputBuffer(uint32_t index, std::shared_ptr<AVBuffer> buffer) override
    {
        if (codec_ != nullptr && callback_.onNewOutputBuffer != nullptr) {
            struct AudioCodecObject *audioCodecObj = reinterpret_cast<AudioCodecObject *>(codec_);
            uint8_t *data = buffer->GetMemory()->GetBase();
            callback_.onNewOutputBuffer(codec_, index, data, userData_);
        }
    }

    struct OH_AVCodec *codec_;
    struct OH_AVCodecCallback callback_;
    void *userData_;
};
```

## 3. API 函数族

### 3.1 统一 AudioCodec API（Buffer 模式）

**所在文件**：`native_audio_codec.cpp`

| API 函数 | 功能 | 关键参数 |
|----------|------|---------|
| `OH_AudioCodec_CreateByMime(mime, isEncoder)` | 创建 Codec（Encoder/Decoder 统一入口） | `isEncoder=true` → 编码器 |
| `OH_AudioCodec_CreateByName(name)` | 按名称创建 Codec | |
| `OH_AudioCodec_Destroy(codec)` | 销毁 Codec | |
| `OH_AudioCodec_Configure(codec, format)` | 配置编码器参数 | `OH_AVFormat`（采样率/通道数/码率等）|
| `OH_AudioCodec_Prepare(codec)` | 准备解码器 | |
| `OH_AudioCodec_Start(codec)` | 启动编解码 | |
| `OH_AudioCodec_Stop(codec)` | 停止编解码 | `bufferObjList_.clear()` |
| `OH_AudioCodec_Flush(codec)` | 刷新缓冲区 | |
| `OH_AudioCodec_Reset(codec)` | 重置 Codec | |
| `OH_AudioCodec_PushInputBuffer(codec, index)` | 推送输入缓冲区 | Buffer 模式专用 |
| `OH_AudioCodec_QueryInputBuffer(codec, index, timeoutUs)` | 查询输入缓冲区 | 超时等待 |
| `OH_AudioCodec_QueryOutputBuffer(codec, index, timeoutUs)` | 查询输出缓冲区 | 超时等待 |
| `OH_AudioCodec_GetInputBuffer(codec, index)` | 获取输入缓冲区 | 返回 `OH_AVBuffer*` |
| `OH_AudioCodec_GetOutputBuffer(codec, index)` | 获取输出缓冲区 | 返回 `OH_AVBuffer*` |
| `OH_AudioCodec_FreeOutputBuffer(codec, index)` | 释放输出缓冲区 | |
| `OH_AudioCodec_GetOutputDescription(codec)` | 获取输出格式描述 | 返回 `OH_AVFormat*` |
| `OH_AudioCodec_SetParameter(codec, format)` | 设置动态参数 | |
| `OH_AudioCodec_RegisterCallback(codec, callback, userData)` | 注册回调 | `OH_AVCodecCallback` |
| `OH_AudioCodec_IsValid(codec, isValid)` | 查询 Codec 有效性 | |
| `OH_AudioCodec_SetDecryptionConfig(codec, session, encryptBuffersAlign, subSample, IV)` | DRM 解密配置 | DRM 专用 |

### 3.2 专用 AudioEncoder API（Memory 模式）

**所在文件**：`native_audio_encoder.cpp`

| API 函数 | 功能 | 与 AudioCodec 差异 |
|----------|------|-------------------|
| `OH_AudioEncoder_CreateByMime(mime)` | 创建音频编码器 | 专用，无 `isEncoder` 标志 |
| `OH_AudioEncoder_CreateByName(name)` | 按名称创建 | |
| `OH_AudioEncoder_Destroy(codec)` | 销毁编码器 | |
| `OH_AudioEncoder_Configure(codec, format)` | 配置编码器参数 | |
| `OH_AudioEncoder_Prepare(codec)` | 准备编码器 | |
| `OH_AudioEncoder_Start(codec)` | 启动编码 | |
| `OH_AudioEncoder_Stop(codec)` | 停止编码 | |
| `OH_AudioEncoder_Flush(codec)` | 刷新缓冲区 | |
| `OH_AudioEncoder_Reset(codec)` | 重置编码器 | |
| `OH_AudioEncoder_GetInputBuffer(codec, index)` | 获取输入缓冲区 | 返回 `OH_AVMemory*` |
| `OH_AudioEncoder_GetOutputBuffer(codec, index)` | 获取输出缓冲区 | 返回 `OH_AVMemory*` |
| `OH_AudioEncoder_GetOutputDescription(codec)` | 获取输出格式描述 | |
| `OH_AudioEncoder_SetParameter(codec, format)` | 设置动态参数 | |
| `OH_AudioEncoder_RegisterCallback(codec, callback, userData)` | 注册回调 | `OH_AVCodecAsyncCallback` |
| `OH_AudioEncoder_IsValid(codec, isValid)` | 查询有效性 | |

### 3.3 创建流程对比

**统一 API 创建（AudioCodec）**：
```cpp
// native_audio_codec.cpp:162-181
struct OH_AVCodec *OH_AudioCodec_CreateByMime(const char *mime, bool isEncoder)
{
    ApiInvokeRecorder apiInvokeRecorder("OH_AudioCodec_CreateByMime", appEventReporter);

    AVCodecType type = AVCODEC_TYPE_AUDIO_DECODER;
    if (isEncoder) {
        type = AVCODEC_TYPE_AUDIO_ENCODER;
    }

    std::shared_ptr<AVCodecAudioCodecImpl> audioCodec = std::make_shared<AVCodecAudioCodecImpl>();
    int32_t ret = audioCodec->Init(type, true, mime);  // isMimeType=true

    struct AudioCodecObject *object = new (std::nothrow) AudioEncoderObject(audioCodec);
    return object;
}
```

**专用 API 创建（AudioEncoder）**：
```cpp
// native_audio_encoder.cpp:190-205
struct OH_AVCodec *OH_AudioEncoder_CreateByMime(const char *mime)
{
    ApiInvokeRecorder apiInvokeRecorder("OH_AudioEncoder_CreateByMime", appEventReporter);

    std::shared_ptr<AVCodecAudioEncoder> audioEncoder = AudioEncoderFactory::CreateByMime(mime);
    struct AudioEncoderObject *object = new (std::nothrow) AudioEncoderObject(audioEncoder);
    return object;
}
```

## 4. 生命周期

```
OH_AudioCodec_CreateByMime/CreateByName
         ↓
    AudioCodecObject 创建
    AVCodecAudioCodecImpl 实例化
         ↓
    OH_AudioCodec_Configure(format)
         ↓
    OH_AudioCodec_Prepare()
         ↓ 初始化 inputTask_/outputTask_
    OH_AudioCodec_RegisterCallback(callback)
         ↓
    OH_AudioCodec_Start()
         ↓ TaskThread OS_ACodecIn/OS_ACodecOut 启动
    [编解码循环]
         ↓
    OH_AudioCodec_Stop() → bufferObjList_.clear()
         ↓
    OH_AudioCodec_Release()
         ↓
    AudioCodecObject 销毁
```

**关键生命周期方法（AVCodecAudioCodecImpl）**：

| 方法 | 职责 | 关键行为 |
|------|------|---------|
| `Stop()` | 停止编解码 | `StopTaskAsync()` → `codecService_->Stop()` → `StopTask()` |
| `Release()` | 释放资源 | 调用 `Stop()` 后 `codecService_->Release()` |
| `ReleaseOutputBuffer(index)` | 释放输出缓冲 | `implConsumer_->ReleaseBuffer(buffer)` |

## 5. DRM 解密配置

**所在文件**：`native_audio_codec.cpp:470-512`

`OH_AudioCodec_SetDecryptionConfig` 是 AudioCodec 统一 API 独有的 DRM 配置接口，支持在解码器创建后配置解密参数。

```cpp
// 函数重载 1：完整参数
OH_AVErrCode OH_AudioCodec_SetDecryptionConfig(
    OH_AVCodec *codec,
    MediaKeySession *mediaKeySession,
    bool encryptBuffersAlign,
    const char *subSample,
    const char *IV);

// 函数重载 2：简化参数
OH_AVErrCode OH_AudioCodec_SetDecryptionConfig(
    OH_AVCodec *codec,
    MediaKeySession *mediaKeySession);
```

**AudioEncoder 不支持此接口**，因为编码器输出是明文数据，无需解密配置。

## 6. 与相关记忆的关联

| 相关记忆 | 关系 |
|----------|------|
| S83 (Native C API 总览) | S95 是 AudioCodec/AudioEncoder 垂类深化 |
| S88 (AudioDecoder C API) | AudioDecoder 使用 `AVCodecAudioDecoder`，AudioCodec 使用 `AVCodecAudioCodecImpl`（统一引擎） |
| S84 (VideoEncoder C API) | VideoEncoder 使用 `VideoEncoderObject`，AudioEncoder 使用 `AudioEncoderObject`（并行结构） |
| S18 (AudioCodecServer) | `AVCodecAudioCodecImpl` 是客户端侧实现，CodecServer 是服务端实现 |
| S35 (AudioDecoderFilter) | Filter 层封装 `AudioCodec`，C API 层封装 `AVCodecAudioCodecImpl` |
| S60 (AAC FFmpeg 插件) | AAC 编码器底层由 FFmpeg 插件实现（`AudioFFMpegAacEncoderPlugin`）|

## 7. 要点总结

1. **`OH_AudioCodec_*` 是统一 API**：通过 `isEncoder` 参数同时支持 Encoder/Decoder，`AudioCodecObject` 封装 `AVCodecAudioCodecImpl`
2. **`OH_AudioEncoder_*` 是专用 API**：仅支持 Encoder，`AudioEncoderObject` 封装 `AVCodecAudioEncoder`，使用 Memory 模式
3. **Buffer 模式 vs Memory 模式**：`AudioCodec` 使用 `OH_AVBuffer`（Buffer 模式），`AudioEncoder` 使用 `OH_AVMemory`（Memory 模式）
4. **双 TaskThread 驱动**：`AVCodecAudioCodecImpl` 使用 `OS_ACodecIn` 和 `OS_ACodecOut` 两个异步线程
5. **DRM 支持**：`AudioCodec` 统一 API 支持 `SetDecryptionConfig`，AudioEncoder 专用 API 不支持
6. **三层调用链**：`NativeAudioCodec`（回调桥接）→ `AudioCodecObject`（对象封装）→ `AVCodecAudioCodecImpl`（引擎实现）
