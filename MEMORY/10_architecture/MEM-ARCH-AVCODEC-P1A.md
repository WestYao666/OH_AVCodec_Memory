# MEM-ARCH-AVCODEC-P1A: MediaCodec 编解码数据流

## Metadata

| Field | Value |
|-------|-------|
| mem_id | MEM-ARCH-AVCODEC-P1A |
| title | MediaCodec 编解码数据流 |
| topic_id | P1a |
| scope | AVCodec, Core, DataFlow |
| status | draft |
| created | 2026-05-07T15:20:00+08:00 |
| source | 飞书审批流 |
| evidence_sources | AVCodec GitCode 仓库本地镜像 |

---

## 1. 概述

MediaCodec 编解码数据流描述的是**应用层数据**从输入到输出的完整路径，涉及**五层架构**的协作：

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 1: Native C API（应用调用层）                          │
│  OH_VideoDecoder_* / OH_VideoEncoder_*                       │
│  文件：frameworks/native/capi/avcodec/native_video_decoder.cpp│
├─────────────────────────────────────────────────────────────┤
│  Layer 2: AVCodecVideoDecoderImpl（框架实现层）              │
│  codecClient_ → AVCodecServiceFactory                       │
│  文件：frameworks/native/avcodec/avcodec_video_decoder_impl.cpp
├─────────────────────────────────────────────────────────────┤
│  Layer 3: CodecClient（IPC代理层）                           │
│  CodecServiceProxy + CodecBufferCircular                    │
│  文件：services/services/codec/client/codec_client.cpp     │
│        services/services/codec/client/codec_buffer_circular.cpp
├─────────────────────────────────────────────────────────────┤
│  Layer 4: CodecServer（服务层）                              │
│  IPC Stub → CodecBase                                       │
│  文件：services/services/codec/server/                      │
├─────────────────────────────────────────────────────────────┤
│  Layer 5: CodecBase/VideoDecoder（引擎层）                  │
│  BlockQueue × 3 + TaskThread × 2                           │
│  文件：services/engine/base/include/codecbase.h              │
│        services/engine/codec/video/decoderbase/              │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. Native C API 七步生命周期

证据：`native_video_decoder.cpp`（852行）

```cpp
// 创建解码器
struct OH_AVCodec *OH_VideoDecoder_CreateByMime(const char *mime)
// → VideoDecoderFactory::CreateByMime(mime)  // line 337

OH_AVErrCode OH_VideoDecoder_Configure(...)    // line 388
OH_AVErrCode OH_VideoDecoder_Prepare(...)      // line 406
OH_VideoDecoder_Start(...)                     // line 422

// 数据输入（两种方式）
OH_AVErrCode OH_VideoDecoder_PushInputData(codec, index, attr)  // line 517
    // → videoDecoder_->QueueInputBuffer(index, bufferInfo, bufferFlag)
OH_AVErrCode OH_VideoDecoder_PushInputBuffer(codec, index)      // line 541
    // → videoDecoder_->QueueInputBuffer(index)

// 输出获取
OH_AVFormat *OH_VideoDecoder_GetOutputDescription(...) // line 558
OH_AVErrCode OH_VideoDecoder_RenderOutputData(...)     // line 577
    // → videoDecoder_->ReleaseOutputBuffer(index, true)
OH_AVErrCode OH_VideoDecoder_FreeOutputData(...)      // line 595
    // → videoDecoder_->ReleaseOutputBuffer(index, false)

// 查询可用输入缓冲区
OH_AVErrCode OH_VideoDecoder_QueryInputBuffer(...)    // line 664
```

---

## 3. Framework 层 AVCodecVideoDecoderImpl

证据：`avcodec_video_decoder_impl.cpp`（84-100行）

AVCodecVideoDecoderImpl 是框架层的 codec 封装类，通过 **AVCodecServiceFactory** 创建 codecClient_：

```cpp
// line 84-86: 创建 codec 服务客户端
int32_t ret = AVCodecServiceFactory::GetInstance().CreateCodecService(codecClient_);
ret = codecClient_->Init(type, isMimeType, name, *format.GetMeta());

// 所有操作均委托给 codecClient_（line 107-196）
codecClient_->Configure(format);   // line 110
codecClient_->Start();              // line 126
codecClient_->Stop();               // line 134
codecClient_->Flush();              // line 142
codecClient_->QueueInputBuffer(...); // line 171-182
codecClient_->GetOutputBuffer(...);  // line 190
codecClient_->ReleaseOutputBuffer(...);
codecClient_->SetOutputSurface(...); // line 166
```

---

## 4. CodecClient IPC 代理层

证据：`codec_client.cpp`（704行）

CodecClient 是跨进程 IPC 代理，持有一个 `codecProxy_`（IRemoteProxy）向 CodecServer 发起调用：

```cpp
// line 371-386: QueueInputBuffer（同步模式）
int32_t CodecClient::QueueInputBuffer(uint32_t index, AVCodecBufferInfo info, AVCodecBufferFlag flag)
{
    ret = codecProxy_->QueueInputBuffer(index, info, flag);  // IPC 调用
    circular_.QueueInputBufferDone(index, isSuccess);        // 环形缓冲标记完成
}

// line 513-515: GetOutputBuffer
std::shared_ptr<AVBuffer> CodecClient::GetOutputBuffer(uint32_t index)
{
    return circular_.GetOutputBuffer(index);
}
```

### CodecBufferCircular 缓冲管理

证据：`codec_buffer_circular.h`（28-89行）

CodecBufferCircular 内部维护三组缓冲状态：

```cpp
// BufferOwner 枚举（line 91-93）
typedef enum : uint8_t {
    OWNED_BY_SERVER = 0,  // 服务端持有
    OWNED_BY_CLIENT = 1,  // 客户端持有
    OWNED_BY_USER = 2,    // 用户持有
} BufferOwner;

// CodecCircularFlag 枚举（line 80-88）
typedef enum : uint8_t {
    FLAG_NONE = 0,
    FLAG_IS_RUNNING = 1 << 0,
    FLAG_IS_SYNC = 1 << 1,              // 同步模式
    FLAG_SYNC_ASYNC_CONFIGURED = 1 << 2, // 不可切换
    FLAG_ERROR = 1 << 3,
    FLAG_INPUT_EOS = 1 << 4,
    FLAG_OUTPUT_EOS = 1 << 5,
} CodecCircularFlag;
```

---

## 5. CodecBase 引擎基类接口

证据：`codecbase.h`（170行）

CodecBase 是所有编解码器的统一基类，定义了编解码操作的标准接口：

```cpp
// 核心生命周期接口（line 28-57）
virtual int32_t Configure(const Format &format) = 0;
virtual int32_t Start() = 0;
virtual int32_t Stop() = 0;
virtual int32_t Flush() = 0;
virtual int32_t Reset() = 0;
virtual int32_t Release() = 0;

// Buffer 操作接口
virtual int32_t QueueInputBuffer(uint32_t index);           // line 51
virtual int32_t ReleaseOutputBuffer(uint32_t index) = 0;

// Surface 模式接口
virtual sptr<Surface> CreateInputSurface();                // line 59
virtual int32_t SetOutputSurface(sptr<Surface> surface);   // line 62

// AVBufferQueue 模式接口
virtual int32_t SetOutputBufferQueue(
    const sptr<Media::AVBufferQueueProducer> &bufferQueueProducer); // line 134
virtual sptr<Media::AVBufferQueueProducer> GetOutputBufferQueueProducer() // line 149
virtual void ProcessInputBuffer()   // line 150
```

---

## 6. VideoDecoder 三队列 BlockQueue 架构

证据：`video_decoder.h`（106-133行）

VideoDecoder 继承 RenderSurface，管理三组 BlockQueue：

```cpp
// line 106: 输入可用队列
std::shared_ptr<BlockQueue<uint32_t>> inputAvailQue_;

// line 72 (render_surface.h): 渲染可用队列
std::shared_ptr<BlockQueue<uint32_t>> renderAvailQue_;

// line 77 (render_surface.h): 请求 SurfaceBuffer 队列
std::shared_ptr<BlockQueue<uint32_t>> requestSurfaceBufferQue_;

// line 133: 发送帧线程（纯虚，由子类实现）
virtual void SendFrame() = 0;

// 关键成员（line 120-132）
std::shared_ptr<TaskThread> sendTask_ = nullptr;   // SendFrame 线程
std::atomic<bool> isSendEos_ = false;
```

Owner 枚举（缓冲区所有权）：

```cpp
// video_decoder.h CodecBuffer 结构体
struct CodecBuffer {
    std::shared_ptr<AVBuffer> avBuffer = nullptr;
    std::shared_ptr<FSurfaceMemory> sMemory = nullptr;
    std::atomic<Owner> owner_ = Owner::OWNED_BY_US;  // 四态所有权
    int32_t width = 0;
    int32_t height = 0;
    int32_t bitDepth = BITS_PER_PIXEL_COMPONENT_8;
    std::atomic<bool> hasSwapedOut = false;
};
```

---

## 7. Codec 十一状态机

证据：`coderstate.h` + `video_decoder.cpp`

```cpp
enum class State : int32_t {
    UNINITIALIZED,  // 初始态
    INITIALIZED,    // 已初始化
    CONFIGURED,    // 已配置
    STOPPING,       // 停止中
    RUNNING,        // 运行中
    FLUSHED,        // 已刷新
    FLUSHING,       // 刷新中
    EOS,            // 流结束
    ERROR,          // 错误态
    FREEZING,       // 冻结中
    FROZEN,         // 已冻结（功耗管理）
};
```

状态转换关键路径：

```
UNINITIALIZED → INITIALIZED (Init)
INITIALIZED → CONFIGURED (Configure)     // video_decoder.cpp:268
CONFIGURED → RUNNING (Start)             // video_decoder.cpp:195
RUNNING → FLUSHED (Flush)                // video_decoder.cpp:385
RUNNING → EOS (NotifyEos)                // video_decoder.cpp:168
RUNNING → STOPPING → INITIALIZED (Stop)  // video_decoder.cpp:422
ANY → ERROR (Error)
RUNNING → FREEZING → FROZEN (Suspend)   // 功耗管理路径
```

---

## 8. 数据流完整路径

### 解码输入路径（Buffer 模式）

```
应用层
  OH_VideoDecoder_PushInputData(index, attr)
    → AVCodecVideoDecoderImpl::QueueInputBuffer(index, info, flag)
      → CodecClient::QueueInputBuffer(index, info, flag)
        → CodecServiceProxy::QueueInputBuffer(index, info, flag)  [IPC 跨进程]
          → CodecServer → VideoDecoder → RenderSurface
            → BlockQueue<uint32_t> inputAvailQue_ 入队
              → SendFrame() TaskThread 消费
                → DecodeFrameOnce() 底层解码
```

### 解码输出路径（Buffer 模式）

```
底层解码完成
  → BlockQueue<uint32_t> renderAvailQue_ 入队
    → CodecClient::GetOutputBuffer(index) [IPC]
      → CodecBufferCircular::GetOutputBuffer(index)
        → 应用层
          OH_VideoDecoder_RenderOutputData(index)
            → CodecClient::ReleaseOutputBuffer(index, true)
              → CodecServiceProxy::ReleaseOutputBuffer(index, render) [IPC]
```

### Surface 模式路径

```
应用层 SetOutputSurface
  → CodecClient::SetOutputSurface(surface) [IPC]
    → VideoDecoder::SetOutputSurface(surface)
      → RenderSurface 持有 surface_
        → SurfaceBuffer 通过 Surface 传递
          → 渲染到屏幕（无需应用层手动 ReleaseOutputBuffer）
```

---

## 9. 双 TaskThread 驱动机制

证据：`video_decoder.h`（line 120）

VideoDecoder 使用双线程模型：

| 线程 | 职责 | 触发方式 |
|------|------|---------|
| SendFrame TaskThread (sendTask_) | 消费 inputAvailQue_，向解码器喂入数据 | 队列非空触发 |
| ReceiveFrame TaskThread | 消费解码完成帧，写入 renderAvailQue_ | 解码完成回调触发 |

```cpp
// video_decoder.cpp:175 - 状态检查确保只有 CONFIGURED/FLUSHED 可 QueueInputBuffer
CHECK_AND_RETURN_RET_LOG((state_ == State::CONFIGURED || state_ == State::FLUSHED),
    AVCS_ERR_INVALID_STATE, "QueueInputBuffer in invalid state");

// video_decoder.cpp:565 - Flush 时清空所有队列
if (state_ == State::FLUSHED || state_ == State::RUNNING || state_ == State::EOS) {
    // 清空 inputAvailQue_, renderAvailQue_
}
```

---

## 10. Surface/Buffer 双模式互斥

证据：`avcodec_video_decoder_impl.cpp`（line 166）

Surface 模式和 Buffer 模式通过 **isOutBufSetted_** 标志互斥：

```cpp
// avcodec_video_decoder_impl.h
bool isOutBufSetted_ = false;  // 是否设置了输出 Surface
sptr<Surface> surface_ = nullptr;  // Surface 模式
```

CodecBufferCircular 的 FLAG_SYNC_ASYNC_CONFIGURED（`codec_buffer_circular.h:84`）标注了**不可切换**约束：

```cpp
FLAG_SYNC_ASYNC_CONFIGURED = 1 << 2,  // 一旦 Configure，不可切换 Sync/Async 模式
```

---

## 关联记忆

| mem_id | 主题 | 关系 |
|--------|------|------|
| MEM-ARCH-AVCODEC-006 | P1a 旧版（若有） | 本记忆替代 |
| MEM-ARCH-AVCODEC-S39 | AVCodecVideoDecoder 视频解码器核心实现 | 本 P1a 的引擎层实现细节 |
| MEM-ARCH-AVCODEC-S55 | AVCodec 模块间回调链路 | 数据流中的回调驱动机制 |
| MEM-ARCH-AVCODEC-S21 | AVCodec IPC架构与CodecClient双模式 | 数据流的 IPC 层 |
| MEM-ARCH-AVCODEC-S83 | AVCodec Native C API 架构 | 数据流的应用层入口 |

---

## 待验证

- [ ] AVCodecServiceFactory 工厂创建路径（codec_service_factory.cpp）
- [ ] SendFrame TaskThread 具体实现（video_decoder.cpp 中 SendFrame 调用链）
- [ ] DecodeFrameOnce 底层解码虚函数实现路径
