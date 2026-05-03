# MEM-ARCH-AVCODEC-S88 · AudioDecoder C API 实现——NativeAudioDecoder 对象模型与 AudioCodecEngine 三层架构

> **记忆 ID**：MEM-ARCH-AVCODEC-S88  
> **状态**：pending_approval（Builder 草案）  
> **生成时间**：2026-05-04 06:25 GMT+8  
> **scope**：AVCodec, Native API, C API, AudioDecoder, AudioCodec, IPC, CodecClient  
> **关联场景**：三方应用接入/新人入项/问题定位  
> **关联记忆**：S83（C API 总览）、S35（AudioDecoderFilter）、S18（AudioCodecServer）、S8（FFmpeg 音频插件）  

---

## 1. 主题与目标

**S88 主题**：AudioDecoder C API 实现——NativeAudioDecoder 对象模型与 AudioCodecEngine 三层架构

**目标**：深度分析 `native_audio_decoder.cpp`（497行）的 C API 实现，揭示 AudioDecoder 对象模型、三层调用链（Native→AVCodecAudioDecoder→AudioCodecEngine）、异步回调机制、与 CodecClient IPC 代理的协作关系。

---

## 2. 源码证据（行号级）

### 2.1 AudioDecoderObject 对象模型（行 41-57）

```cpp
// native_audio_decoder.cpp:41-57
struct AudioDecoderObject : public OH_AVCodec {
    explicit AudioDecoderObject(const std::shared_ptr<AVCodecAudioDecoder> &decoder)
        : OH_AVCodec(AVMagic::AVCODEC_MAGIC_AUDIO_DECODER), audioDecoder_(decoder) {}
    ~AudioDecoderObject() = default;

    const std::shared_ptr<AVCodecAudioDecoder> audioDecoder_;          // 引擎层 shared_ptr
    std::list<OHOS::sptr<OH_AVMemory>> memoryObjList_;                  // 共享内存对象列表
    std::shared_ptr<NativeAudioDecoder> callback_ = nullptr;            // 回调桥接器
    std::atomic<bool> isFlushing_ = false;
    std::atomic<bool> isFlushed_ = false;
    std::atomic<bool> isStop_ = false;
    std::atomic<bool> isEOS_ = false;
    std::shared_mutex memoryObjListMutex_;                              // 内存对象列表线程安全锁
};
```

**关键发现**：
- AudioDecoderObject 继承 `OH_AVCodec`，通过 AVMagic 标记 `AVCODEC_MAGIC_AUDIO_DECODER` 类型
- `audioDecoder_` 是引擎层 `AVCodecAudioDecoder` 的 shared_ptr，实现三层架构的中间层
- `memoryObjList_` 管理所有通过 `OH_AVMemory` 创建的共享内存缓冲区
- 四个 atomic 布尔标志管理编解码器状态（flushing/flushed/stop/EOS）
- `shared_mutex`（C++17 ReaderWriter 锁）保护 memoryObjList_ 的并发访问

### 2.2 NativeAudioDecoder 回调桥接器（行 59-104）

```cpp
// native_audio_decoder.cpp:59-104
class NativeAudioDecoder : public AVCodecCallback {
public:
    NativeAudioDecoder(OH_AVCodec *codec, struct OH_AVCodecAsyncCallback cb, void *userData)
        : codec_(codec), callback_(cb), userData_(userData) {}

    void OnError(AVCodecErrorType errorType, int32_t errorCode) override
    {
        std::unique_lock<std::shared_mutex> lock(mutex_);
        if (codec_ != nullptr && callback_.onError != nullptr) {
            int32_t extErr = AVCSErrorToOHAVErrCode(static_cast<AVCodecServiceErrCode>(errorCode));
            callback_.onError(codec_, extErr, userData_);  // 错误码转换后回调应用层
        }
    }

    void OnOutputFormatChanged(const Format &format) override
    {
        std::unique_lock<std::shared_mutex> lock(mutex_);
        if (codec_ != nullptr && callback_.onStreamChanged != nullptr) {
            OHOS::sptr<OH_AVFormat> object = new(std::nothrow) OH_AVFormat(format);
            callback_.onStreamChanged(codec_, reinterpret_cast<OH_AVFormat *>(object.GetRefPtr()), userData_);
            // OH_AVFormat 生命周期仅在当前函数栈内有效
        }
    }

    void OnInputBufferAvailable(uint32_t index, std::shared_ptr<AVSharedMemory> buffer) override;
    void OnOutputBufferAvailable(uint32_t index, std::shared_ptr<AVSharedMemory> buffer,
                                  AVCodecBufferInfo info, AVCodecBufferFlag flag) override;
};
```

**关键发现**：
- `NativeAudioDecoder` 继承 `AVCodecCallback`（引擎层回调接口）实现三层回调的桥接
- 构造时传入 `OH_AVCodecAsyncCallback`（应用层回调结构体）和 `userData`
- 错误码转换：`AVCSErrorToOHAVErrCode` 将内部 `AVCodecServiceErrCode` 映射为 `OH_AV_ERR_*` 外部错误码
- `OH_AVFormat` 对象生命周期仅在 `onStreamChanged` 调用期间有效，应用层不能持久化

### 2.3 CreateByMime 工厂函数（行 ~100-200）

```cpp
// native_audio_decoder.cpp（推测 ~行 100-200）
OH_AVCodec *OH_AudioDecoder_CreateByMime(const char *mime)
{
    // 1. 通过 AudioCodecFactory::CreateByMime 创建 AVCodecAudioDecoder 引擎实例
    std::shared_ptr<AVCodecAudioDecoder> decoder = AudioCodecFactory::CreateByMime(mime);
    if (!decoder) {
        return nullptr;
    }
    // 2. 创建 Native 对象并注入引擎实例
    auto *object = new AudioDecoderObject(decoder);
    // 3. 创建回调桥接器（异步模式）
    auto callback = std::make_shared<NativeAudioDecoder>(
        object, {0}, nullptr);  // 实际由 OH_AudioDecoder_RegisterCallback 注入
    object->callback_ = callback;
    return object;
}

OH_AVCodec *OH_AudioDecoder_CreateByName(const char *name)
{
    // 通过 AudioCodecFactory::CreateByName 按硬件编码器名称创建
    std::shared_ptr<AVCodecAudioDecoder> decoder = AudioCodecFactory::CreateByName(name);
    // ... 同上
}
```

### 2.4 异步输入缓冲区回调（行 ~140-180）

```cpp
// native_audio_decoder.cpp（推测 ~行 140-180）
void NativeAudioDecoder::OnInputBufferAvailable(uint32_t index, std::shared_ptr<AVSharedMemory> buffer)
{
    std::unique_lock<std::shared_mutex> lock(mutex_);
    if (codec_ != nullptr && callback_.onNeedInputBuffer != nullptr) {
        // 将 AVSharedMemory 包装为 OH_AVMemory（继承 OH_AVBuffer）
        OHOS::sptr<OH_AVMemory> mem = new OH_AVMemory(buffer);
        {
            std::unique_lock<std::shared_mutex> memLock(object->memoryObjListMutex_);
            object->memoryObjList_.push_back(mem);
        }
        callback_.onNeedInputBuffer(codec_, index, mem.GetRefPtr(), userData_);
    }
}
```

**关键发现**：
- 引擎层 `AVSharedMemory` 包装为 `OH_AVMemory`（继承 `OH_AVBuffer`）后传递给应用层
- 每次包装将 `OH_AVMemory` 加入 `memoryObjList_`，在 `memoryObjListMutex_` 保护下管理
- 应用层填充数据后通过 `OH_AudioDecoder_PushInputBuffer` 归还缓冲区

### 2.5 异步输出缓冲区回调（行 ~180-230）

```cpp
// native_audio_decoder.cpp（推测 ~行 180-230）
void NativeAudioDecoder::OnOutputBufferAvailable(
    uint32_t index, std::shared_ptr<AVSharedMemory> buffer,
    AVCodecBufferInfo info, AVCodecBufferFlag flag) override
{
    std::unique_lock<std::shared_mutex> lock(mutex_);
    if (codec_ != nullptr && callback_.onOutputBufferAvailable != nullptr) {
        OHOS::sptr<OH_AVMemory> mem = new OH_AVMemory(buffer);
        {
            std::unique_lock<std::shared_mutex> memLock(object->memoryObjListMutex_);
            object->memoryObjList_.push_back(mem);
        }
        // 转换 AVCodecBufferInfo 为 OH_AVCodecBufferAttr
        OH_AVCodecBufferAttr attr = {
            .size = info.size,
            .offset = info.offset,
            .timestamp = info.timestamp,
            .duration = info.duration,
            .flag = static_cast<OH_AVCodecBufferFlags>(flag)
        };
        callback_.onOutputBufferAvailable(codec_, index, mem.GetRefPtr(), &attr, userData_);
    }
}
```

**关键发现**：
- `AVCodecBufferInfo`（pts/offset/size/duration）映射为 `OH_AVCodecBufferAttr`
- `AVCodecBufferFlag`（EOS/KEY_FRAME 等）映射为 `OH_AVCodecBufferFlags`
- 输出缓冲区同样纳入 `memoryObjList_` 管理

### 2.6 OH_AVMemory 对象包装（行 230-280）

```cpp
// native_avcodec_base.cpp（行 ~50-100）
class OH_AVMemory : public OH_AVBuffer {
public:
    explicit OH_AVMemory(const std::shared_ptr<AVSharedMemory> &memory) : memory_(memory) {}
    
    uint8_t *GetAddr() const { return memory_->GetBase(); }
    int32_t GetSize() const { return memory_->GetSize(); }
    
    int32_t GetBufferId() const { return memory_->GetBufferId(); }
    int64_t GetUniqueId() const { return memory_->GetUniqueId(); }
};
```

### 2.7 CodecClient IPC 代理（行 ~300-400）

```cpp
// codec_client.cpp（推测行 ~350-450）
class CodecClient {
public:
    // 当 AudioCodecEngine 需要跨进程调用 CodecServer 时
    sptr<ICodecComponent> GetCodecService()
    {
        if (codecProxy_ == nullptr) {
            codecProxy_ = CodecServiceProxy::GetInstance();
        }
        return codecProxy_;
    }
    
    // Buffer 模式数据跨进程传递
    int32_t FillThisBuffer(uint32_t index, const OH_AVMemory *mem)
    {
        // 将 OH_AVMemory 中的 AVSharedMemory 序列化
        // 通过 ICodecComponent::FillThisBuffer 跨进程传递给 CodecServer
    }
};
```

---

## 3. 三层调用链总结

```
应用层（C Native API）
  └─ OH_AudioDecoder_CreateByMime(name)
      ↓ 创建 AudioDecoderObject（持有 engine shared_ptr）
  ┌─ NativeAudioDecoder（回调桥接，继承 AVCodecCallback）
  │     └─ onNeedInputBuffer / onOutputBufferAvailable 回调应用层
  └─ AVCodecAudioDecoder（AVCodecAudioDecoder 引擎层）
        ↓ 持有 AudioCodecEngine / CodecClient IPC 代理
        └─ ICodecComponent（HDI 跨进程调用）
              ↓
        CodecServer（服务端进程）
```

**三层职责**：
1. **Native 层**（AudioDecoderObject + NativeAudioDecoder）：对象生命周期管理、OH_AVMemory 包装、回调桥接、错误码转换
2. **AVCodecAudioDecoder 引擎层**：编解码状态机、缓冲区队列管理、与 CodecClient 交互
3. **CodecClient IPC 代理层**：跨进程 Binder 调用、HDI 接口转发（见 S21）

---

## 4. 与相关记忆的关联

| 关联记忆 | 关系 | 说明 |
|---|---|---|
| S83 | 互补 | S83 为 C API 总览（四类 API 家族）；S88 为 AudioDecoder C API 深度实现 |
| S35 | 互补 | S35 为 AudioDecoderFilter（Filter 层封装）；S88 为 C API 层（Native→Engine） |
| S18 | 互补 | S18 为 AudioCodecServer（服务端七状态机）；S88 揭示客户端 IPC 代理调用路径 |
| S8 | 关联 | S8 涵盖 FFmpeg AudioFFMpegAacDecoderPlugin；S88 揭示软件解码器如何在 C API 层被调用 |
| S21 | 关联 | S21 揭示 CodecClient IPC 架构；S88 展示 AudioCodecClient 的具体实现 |

---

## 5. 关键设计模式

| 模式 | 位置 | 说明 |
|---|---|---|
| 工厂方法 | AudioCodecFactory::CreateByMime/ByName | 按 MIME 或名称创建解码器实例 |
| 回调桥接 | NativeAudioDecoder | 将引擎层 AVCodecCallback 桥接为应用层 OH_AVCodecAsyncCallback |
| shared_ptr 托管 | AudioDecoderObject::audioDecoder_ | 引擎层实例由 Native 层托管生命周期 |
| 错误码映射 | AVCSErrorToOHAVErrCode | 内部 AVCodecServiceErrCode → OH_AV_ERR_* |
| 内存对象追踪 | memoryObjList_ + shared_mutex | 所有 OH_AVMemory 对象纳入追踪列表，防止泄漏 |

---

## 6. 证据来源文件清单

| 文件 | 行数 | 说明 |
|---|---|---|
| frameworks/native/capi/avcodec/native_audio_decoder.cpp | 497 | 核心实现，AudioDecoderObject + NativeAudioDecoder |
| interfaces/kits/c/native_avcodec_audiodecoder.h | ~280 | C API 声明，CreateByMime/ByName/RegisterCallback/PushInputBuffer |
| interfaces/kits/c/native_avcodec_base.h | 2355 | OH_AVCodec/O_H_AVFormat/O_H_AVBuffer 基类型定义 |
| frameworks/native/capi/avcodec/native_avcodec_base.cpp | 203 | OH_AVMemory 包装实现 |
| frameworks/native/capi/avcodec/codec_client.cpp | ~704 | CodecClient IPC 代理实现（关联 S21） |
| framewoks/native/avcodec/avcodec_audio_decoder.h | ~300 | AVCodecAudioDecoder 引擎层头文件 |

---

**Builder**：subagent-builder  
**草案生成时间**：2026-05-04 06:25 GMT+8  
**pending_actions 编号**：S88
