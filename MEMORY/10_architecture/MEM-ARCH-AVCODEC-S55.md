---
type: architecture
id: MEM-ARCH-AVCODEC-S55
title: "AVCodec 模块间回调链路——CodecCallback、MediaCodecCallback、CodecBaseCallback、CodecListenerCallback 四路回调架构"
scope: [AVCodec, Callback, IPC, CodecClient, CodecServer, AudioCodecServer, CodecBase, MediaCodec, CodecListenerCallback, CodecListenerStub, CodecListenerProxy, ICodecComponentCallback, Binder]
status: draft
created_by: builder-agent
created_at: "2026-04-26T19:10:00+08:00"
evidence_count: 28
关联主题: [S21(AVCodec IPC架构), S39(AVCodecVideoDecoder), S18(AudioCodecServer), S48(CodecServer生命周期)]
---

# MEM-ARCH-AVCODEC-S55: AVCodec 模块间回调链路——CodecCallback、MediaCodecCallback、CodecBaseCallback、CodecListenerCallback 四路回调架构

## Metadata

| 字段 | 值 |
|------|-----|
| **ID** | MEM-ARCH-AVCODEC-S55 |
| **标题** | AVCodec 模块间回调链路——CodecCallback、MediaCodecCallback、CodecBaseCallback、CodecListenerCallback 四路回调架构 |
| **Scope** | AVCodec, Callback, IPC, CodecClient, CodecServer, CodecBase, MediaCodec, CodecListenerCallback, Binder |
| **Status** | draft |
| **Created** | 2026-04-26T19:10:00+08:00 |
| **Evidence Count** | 28 |
| **关联主题** | S21(IPC架构), S39(VideoDecoder), S18(AudioCodecServer), S48(CodecServer生命周期) |

---

## 1. 架构总览

AVCodec 系统存在**四路独立又互联的回调通道**，分别位于不同的模块边界：

| 回调类型 | 所在层 | 接口类型 | 调用方向 | 用途 |
|----------|--------|----------|----------|------|
| `CodecCallback` | MediaCodec (引擎) | 内部抽象 | 引擎→MediaCodec | HDI 解码器事件上报 |
| `MediaCodecCallback` | MediaCodec (引擎) | 内部抽象 | 引擎→MediaCodec | Buffer 模式解码事件上报 |
| `CodecBaseCallback` | CodecServer/AudioCodecServer | `MediaCodecCallback`/`AVCodecCallback` | CodecBase→CodecServer | 引擎层事件注入服务层 |
| `CodecListenerCallback` | IPC (跨进程) | `IStandardCodecListener` | CodecServer→CodecClient | 跨进程回调转发 |

```
用户应用
  │
  │ SetCallback(MediaCodecCallback)
  ▼
CodecClient ──────────────────────────────────────────────── CodecServer
  │                                                                │
  │  CreateListenerObject()  ─── IPCBinder ──►  CodecServiceStub   │
  │  (CodecListenerStub)                                   │        │
  │                                                    SetCallback│
  │                                                    (Codec    │
  │                                                     Listener │
  │                                                      Callback)│
  │                                                         │
  │                                                   videoCb_ ◄─┘
  │                                                   (MediaCodecCallback)
  │                                                         │
  │                                                   CodecBase ►──► CodecBaseCallback
  │                                                   (CodecBase)       │
  │                                                                   │
  │                                                   codecBaseCb_ ◄──┘
  │                                                   (weak_ptr<CodecServer>)
  │                                                         │
  │                                                   MediaCodec ◄──► CodecCallback
  │                                                   (HDI适配层)        │
  │                                                           │
  └───────────────────────────────────────────────────────►  HDI 解码器
         OnOutputBufferAvailable(index, buffer) ◄────────────┘
```

---

## 2. 关键源文件索引

| 文件 | 作用 |
|------|------|
| `services/media_engine/modules/media_codec/media_codec.h` | CodecCallback、MediaCodec 引擎接口定义 |
| `services/engine/base/codecbase.h` | CodecBase 基类 |
| `services/services/codec/ipc/codec_listener_proxy.h` | CodecListenerCallback、CodecListenerProxy |
| `services/services/codec/ipc/codec_listener_stub.h` | CodecListenerStub |
| `services/services/codec/ipc/codec_service_proxy.h` | CodecServiceProxy |
| `services/services/codec/ipc/codec_service_stub.h` | CodecServiceStub，SetListenerObject 实现 |
| `services/services/codec/ipc/i_standard_codec_listener.h` | IStandardCodecListener 接口 |
| `services/services/codec/client/codec_client.h/cpp` | CodecClient，SetCallback + CreateListenerObject |
| `services/services/codec/server/video/codec_server.h/cpp` | CodecServer，CodecBaseCallback |
| `services/services/codec/server/audio/audio_codec_server.h/cpp` | AudioCodecServer，CodecBaseCallback + VCodecBaseCallback |
| `services/media_engine/plugins/ffmpeg_adapter/common/hdi_codec.h` | HdiCallback 封装 |

---

## 3. 第一路：CodecCallback（HDI 解码器→MediaCodec）

### 3.1 接口定义

**文件**: `services/media_engine/modules/media_codec/media_codec.h:67-74`
```cpp
class CodecCallback {
public:
    virtual ~CodecCallback() = default;
    virtual void OnError(CodecErrorType errorType, int32_t errorCode) = 0;
    virtual void OnOutputFormatChanged(const std::shared_ptr<Meta> &format) = 0;
};
```

### 3.2 HdiCallback 封装

**文件**: `services/media_engine/plugins/ffmpeg_adapter/common/hdi_codec.h:85-100`
```cpp
class HdiCodec::HdiCallback : public ICodecCallback {
public:
    explicit HdiCallback(std::shared_ptr<HdiCodec> hdiCodec);
    virtual ~HdiCallback() = default;
    void OnError(CodecErrorType errorType, int32_t errorCode) override;
    void OnOutputFormatChanged(const std::shared_ptr<Meta> &format) override;
    void OnInputBufferAvailable(uint32_t portIndex, std::shared_ptr<AVBuffer> buffer) override;
    void OnOutputBufferAvailable(uint32_t portIndex, std::shared_ptr<AVBuffer> buffer) override;
private:
    std::weak_ptr<HdiCodec> hdiCodec_;
};
```

### 3.3 MediaCodec 使用 CodecCallback

**文件**: `services/media_engine/modules/media_codec/media_codec.h:104`
```cpp
class MediaCodec : public std::enable_shared_from_this<MediaCodec>, public Plugins::DataCallback {
    int32_t SetCodecCallback(const std::shared_ptr<CodecCallback> &codecCallback);  // line 104
    std::weak_ptr<CodecCallback> codecCallback_;  // line 202
};
```

**触发场景**: 当 HDI 解码器（如 libhevcdec_ohos）产生错误或输出格式变化时，HdiCallback 调用 `codecCallback_->OnError()` / `OnOutputFormatChanged()`，通知到 MediaCodec 引擎。

---

## 4. 第二路：MediaCodecCallback（Buffer 模式引擎回调）

### 4.1 接口定义

**文件**: `services/media_engine/modules/media_codec/media_codec.h:79-82`
```cpp
class AudioBaseCodecCallback {
public:
    virtual ~AudioBaseCodecCallback() = default;
    virtual void OnError(CodecErrorType errorType, int32_t errorCode) = 0;
    virtual void OnOutputBufferDone(const std::shared_ptr<AVBuffer> &outputBuffer) = 0;
    virtual void OnOutputFormatChanged(const std::shared_ptr<Meta> &format) = 0;
};
```

MediaCodec 内部使用 `CodecCallback` 接口将引擎事件转发为 `MediaCodecCallback` 格式，MediaCodec 本身实现 `Plugins::DataCallback` 接口供上层（CodecBase）消费。

---

## 5. 第三路：CodecBaseCallback（CodecBase→CodecServer）

### 5.1 VideoCodecServer 路径

**文件**: `services/services/codec/server/video/codec_server.cpp:146-148`
```cpp
codecBaseCb_ = std::make_shared<CodecBaseCallback>(shared_from_this());  // line 146
ret = codecBase_->SetCallback(codecBaseCb_);                              // line 147
```

**CodecBaseCallback 定义**: `services/services/codec/server/video/codec_server.h:242-243`
```cpp
class CodecBaseCallback : public MediaCodecCallback, public NoCopyable {
    explicit CodecBaseCallback(const std::shared_ptr<CodecServer> &codec);  // line 242
```

**CodecBaseCallback 实现**: `services/services/codec/server/video/codec_server.cpp:1177-1218`
```cpp
CodecBaseCallback::CodecBaseCallback(const std::shared_ptr<CodecServer> &codec) : weakCodec_(codec) {}  // line 1177

void CodecBaseCallback::OnOutputBufferAvailable(uint32_t index, std::shared_ptr<AVBuffer> buffer)  // line 1203
{
    std::shared_ptr<CodecServer> codec = weakCodec_.lock();
    codec->OnOutputBufferAvailable(index, buffer);  // 转发到 CodecServer
}
```

### 5.2 AudioCodecServer 路径（双回调）

**文件**: `services/services/codec/server/audio/audio_codec_server.cpp:112-117`
```cpp
shareBufCallback_ = std::make_shared<CodecBaseCallback>(shared_from_this());  // AVCodecCallback 模式
ret = codecBase_->SetCallback(shareBufCallback_);                              // line 113

avBufCallback_ = std::make_shared<VCodecBaseCallback>(shared_from_this());   // MediaCodecCallback 模式
ret = codecBase_->SetCallback(avBufCallback_);                                 // line 117
```

AudioCodecServer 同时注册 `CodecBaseCallback`（继承 `AVCodecCallback`）和 `VCodecBaseCallback`（继承 `MediaCodecCallback`），分别对应 SharedMemory 模式和 AVBuffer 模式。

**VCodecBaseCallback 定义**: `services/services/codec/server/audio/audio_codec_server.h:149-152`
```cpp
class VCodecBaseCallback : public MediaCodecCallback, public NoCopyable {
    explicit VCodecBaseCallback(const std::shared_ptr<AudioCodecServer> &codec);
```

---

## 6. 第四路：CodecListenerCallback（IPC 跨进程回调）

### 6.1 完整 IPC 回调链路

这是最复杂的一路，涉及跨进程通信：

```
用户应用 SetCallback(MediaCodecCallback)
        │
        ▼
CodecClient.SetCallback(callback)  ── 保存到 CodecClient 内部 ◄─────────┐
        │                                                        │
   CreateListenerObject() ── 创建 CodecListenerStub ─────────────┤
   (codec_client.cpp:112)  (codec_listener_stub.h)                │
        │                                                        │
   codecProxy_->SetListenerObject(object)                         │
        │                                                        │
   MessageParcel.WriteRemoteObject(stub对象)                      │
        │                                                        │
   SendRequest(SET_LISTENER_OBJ) ──► IPC Binder ──►               │
                                                    │              
                                       CodecServiceStub.SetListenerObject()
                                       (codec_service_stub.cpp:208-218)
                                                    │
                                              listener_ = iface_cast<IStandardCodecListener>(object)
                                                    │
                                              codecServer_->SetCallback(
                                                CodecListenerCallback(listener_)
                                              )
                                                    │
                                              videoCb_ = CodecListenerCallback
                                                    │
                                     ┌─────────────┴──────────────────┐
                                     │                                  │
                              CodecServer                            CodecServer
                              OnOutputBufferAvailable()              OnError()
                                     │                                  │
                              videoCb_->OnOutputBufferAvailable()   videoCb_->OnError()
                              (CodecListenerCallback)               (CodecListenerCallback)
                                     │                                  │
                              CodecListenerCallback::OnOutputBufferAvailable()
                              (codec_listener_proxy.h:30-31)
                                     │
                              listener_->OnOutputBufferAvailable()
                              (IStandardCodecListener 跨进程调用)
                                     │
                              MessageParcel ──► IPC Binder ──►
                                                        │
                                       CodecListenerStub.OnRemoteRequest()
                                       (codec_listener_stub.h)
                                              │
                                       callback_->OnOutputBufferAvailable()
                                              │
                                       CodecClient.OnOutputBufferAvailable()
                                       (codec_client.cpp:685-689)
                                              │
                                       circular_.OnOutputBufferAvailable()
                                              │
                                       用户注册的 MediaCodecCallback
                                       (OnOutputBufferAvailable)
```

### 6.2 CodecListenerCallback 定义

**文件**: `services/services/codec/ipc/codec_listener_proxy.h:28-32`
```cpp
class CodecListenerCallback : public MediaCodecCallback, public NoCopyable, public AVCodecDfxComponent {
public:
    explicit CodecListenerCallback(const sptr<IStandardCodecListener> &listener);  // line 30
    void OnError(AVCodecErrorType errorType, int32_t errorCode) override;
    void OnOutputFormatChanged(const Format &format) override;
    void OnInputBufferAvailable(uint32_t index, std::shared_ptr<AVBuffer> buffer) override;
    void OnOutputBufferAvailable(uint32_t index, std::shared_ptr<AVBuffer> buffer) override;
    void OnOutputBufferBinded(std::map<uint32_t, sptr<SurfaceBuffer>> &bufferMap) override;
    void OnOutputBufferUnbinded() override;
private:
    sptr<IStandardCodecListener> listener_ = nullptr;  // line 41
};
```

### 6.3 CodecListenerStub 定义

**文件**: `services/services/codec/ipc/codec_listener_stub.h:34-78`
```cpp
class CodecListenerStub : public IRemoteStub<IStandardCodecListener>, public AVCodecDfxComponent {
public:
    void SetCallback(const std::shared_ptr<MediaCodecCallback> &callback);  // line 47
    std::weak_ptr<MediaCodecCallback> callback_;  // line 78
```

### 6.4 IStandardCodecListener 接口

**文件**: `services/services/codec/ipc/i_standard_codec_listener.h:32-44`
```cpp
class IStandardCodecListener : public IRemoteBroker {
public:
    virtual ~IStandardCodecListener() = default;
    virtual void OnError(AVCodecErrorType errorType, int32_t errorCode) = 0;
    virtual void OnOutputFormatChanged(const Format &format) = 0;
    virtual void OnInputBufferAvailable(uint32_t index, std::shared_ptr<AVBuffer> buffer) = 0;
    virtual void OnOutputBufferAvailable(uint32_t index, std::shared_ptr<AVBuffer> buffer) = 0;
    virtual void OnOutputBufferBinded(std::map<uint32_t, sptr<SurfaceBuffer>> &bufferMap) = 0;
    virtual void OnOutputBufferUnbinded() = 0;
```

### 6.5 CodecServiceStub.SetListenerObject

**文件**: `services/services/codec/ipc/codec_service_stub.cpp:208-218`
```cpp
int32_t CodecServiceStub::SetListenerObject(const sptr<IRemoteObject> &object)
{
    std::lock_guard<std::shared_mutex> lock(mutex_);
    CHECK_AND_RETURN_RET_LOG(object != nullptr, AVCS_ERR_NO_MEMORY, "Object is nullptr");

    listener_ = iface_cast<IStandardCodecListener>(object);  // 将跨进程 Proxy 转型为接口
    std::shared_ptr<MediaCodecCallback> callback = std::make_shared<CodecListenerCallback>(listener_);
    (void)codecServer_->SetCallback(callback);  // 注入 CodecServer
    return AVCS_ERR_OK;
}
```

### 6.6 CodecClient.CreateListenerObject

**文件**: `services/services/codec/client/codec_client.cpp:112-134`
```cpp
int32_t CodecClient::CreateListenerObject()
{
    listenerStub_ = new (std::nothrow) CodecListenerStub();  // line 117
    const std::shared_ptr<MediaCodecCallback> callback = shared_from_this();  // CodecClient 自身
    listenerStub_->SetCallback(callback);  // line 121
    sptr<IRemoteObject> object = listenerStub_->AsObject();
    int32_t ret = codecProxy_->SetListenerObject(object);  // line 126，发送到服务端
    ...
}
```

---

## 7. 回调事件类型总表

所有回调链路的统一事件类型：

| 事件 | 触发时机 | 跨进程 | Surface 模式 |
|------|----------|--------|-------------|
| `OnError` | 解码错误、服务终止 | ✅ | ✅ |
| `OnOutputFormatChanged` | 格式变化（分辨率等） | ✅ | ✅ |
| `OnInputBufferAvailable` | 输入缓冲区就绪 | ✅ | ❌（Surface 模式无输入回调） |
| `OnOutputBufferAvailable` | 输出缓冲区就绪 | ✅ | ✅ |
| `OnOutputBufferBinded` | Surface Buffer 绑定 | ✅ | ✅（仅 Surface） |
| `OnOutputBufferUnbinded` | Surface Buffer 解绑 | ✅ | ✅（仅 Surface） |

---

## 8. CodecClient 双回调模式

**文件**: `services/services/codec/client/codec_client.h`
```cpp
typedef enum : uint8_t {
    MEMORY_CALLBACK = 1,   // AVSharedMemory 模式（legacy）
    BUFFER_CALLBACK,      // AVBuffer 模式
    INVALID_CALLBACK,
} CallbackMode;
```

CodecClient 支持两种回调模式：
- **MEMORY_CALLBACK**: 使用 `AVCodecCallback` + `CodecBufferCircular`（旧模式）
- **BUFFER_CALLBACK**: 使用 `MediaCodecCallback` + `CodecBufferCircular`（新模式）

**文件**: `services/services/codec/client/codec_client.cpp:528-554`
```cpp
int32_t CodecClient::SetCallback(const std::shared_ptr<AVCodecCallback> &callback)  // line 528
int32_t CodecClient::SetCallback(const std::shared_ptr<MediaCodecCallback> &callback)  // line 543
```

---

## 9. PostProcessing 特殊回调（第五路/分支）

当配置了后处理（VideoPostProcessor）时，解码输出被 PostProcessing 拦截，回调路径变为：

**文件**: `services/services/codec/server/video/codec_server.cpp:67-95`
```cpp
struct PostProcessingCallbackUserData {
    std::shared_ptr<OHOS::MediaAVCodec::CodecServer> codecServer;
};

void PostProcessingCallbackOnError(int32_t errorCode, void* userData)  // line 71
void PostProcessingCallbackOnOutputBufferAvailable(uint32_t index, int32_t flag, void* userData)  // line 80
void PostProcessingCallbackOnOutputFormatChanged(const OHOS::Media::Format& format, void* userData)  // line 89
```

注册方式：`services/services/codec/server/video/codec_server.cpp:1348-1352`
```cpp
postProcessingCallback_.onError = std::bind(PostProcessingCallbackOnError, _1, _2);
postProcessingCallback_.onOutputBufferAvailable =
    std::bind(PostProcessingCallbackOnOutputBufferAvailable, _1, _2, _3);
postProcessingCallback_.onOutputFormatChanged =
    std::bind(PostProcessingCallbackOnOutputFormatChanged, _1, _2);
```

PostProcessing 不经过 CodecListenerCallback，直接通过 `PostProcessingCallbackUserData` 中的 `shared_ptr<CodecServer>` 调用到 `CodecServer::PostProcessingOn*()` 方法，在 `PostProcessingOnOutputBufferAvailable` 中再调用 `videoCb_->OnOutputBufferAvailable()` 注入主回调链。

---

## 10. 总结：四路回调架构图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          用户进程 (CodecClient)                          │
│                                                                         │
│   用户应用                                                                │
│      │                                                                   │
│      │ SetCallback(MediaCodecCallback)                                  │
│      ▼                                                                   │
│   CodecClient ──────────────────────────────────────────────────────► │
│      │          CreateListenerObject()                                   │
│      │          codecProxy_->SetListenerObject(stub对象)                 │
│      │                                                                   │
│   CodecListenerStub (IRemoteStub)                                       │
│      │ SetCallback(shared_from_this)                                    │
│      │ OnOutputBufferAvailable() ───────────────────────────────────────┘
│      │
│      │ IPC跨进程 ────────────────────────────────────────────►
└──────┼───────────────────────────────────────────────────────────┘
       │                                                              
┌──────┼───────────────────────────────────────────────────────────┐
       │                                                              
│   CodecServiceStub (IRemoteStub)                                  │
│      │ SetListenerObject(object)                                   │
│      │ listener_ = iface_cast<IStandardCodecListener>(object)    │
│      │ codecServer_->SetCallback(CodecListenerCallback(listener_))│
│      │                                                       CodecServer (服务端进程)
│      ▼                                                           │
│   CodecListenerCallback                                           │
│   (IStandardCodecListener跨进程proxy → listener_)                │
│      │                                                           │
│      │ listener_->OnOutputBufferAvailable()                       │
│      │ (IPC调用)                                                  │
│      │                                                           │
│   videoCb_->OnOutputBufferAvailable()                             │
│      │                                                           │
│      │ 【有PostProcessing时】                                     │
│      ├─► PostProcessingCallback ──► PostProcessingOnOutputBufferAvailable()
│      │                                                           │
│      └─► CodecBaseCallback ◄────── codecBaseCb_ = CodecBaseCallback(codecServer)
│      │   (weak_ptr<CodecServer>)                                  │
│      │                                                           │
│   CodecBase.OnOutputBufferAvailable()                             │
│      │                                                           │
│   MediaCodec ─────────────────────────────────────────────────►  │
│      │                                                           │
│   CodecCallback ──► HdiCallback ◄──► HDI解码器 (libhevcdec_ohos) │
│   (MediaCodec内部)                                                 │
└────────────────────────────────────────────────────────────────────┘
```

**关键设计要点**：
1. CodecListenerStub 持有 CodecClient 自身（shared_from_this）作为 callback，形成 IPC 回调环
2. CodecListenerCallback 持有 IStandardCodecListener（跨进程 proxy），将服务端事件通过 IPC 发回客户端
3. CodecServiceStub 在接收到 SetListenerObject 后，将 IPC stub 对象包装成 CodecListenerCallback 注入 CodecServer
4. CodecBaseCallback 通过 weak_ptr 持有 CodecServer，避免循环引用
5. AudioCodecServer 有独立的 CodecBaseCallback（AVCodecCallback）和 VCodecBaseCallback（MediaCodecCallback），分别处理 SharedMemory 和 AVBuffer 模式
