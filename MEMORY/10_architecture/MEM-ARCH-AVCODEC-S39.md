---
type: architecture
id: MEM-ARCH-AVCODEC-S39
title: "AVCodecVideoDecoder 视频解码器核心实现——CodecBase/VideoDecoder/VideoDecoderAdapter 三层架构"
scope: [AVCodec, VideoDecoder, CodecBase, VideoDecoderAdapter, Filter, HardwareCodec, SoftwareCodec]
pipeline_position: "FilterPipeline 中游：DemuxerFilter(S41) → VideoDecoderFilter → AudioDecoderFilter(S35)"
status: approved
approved_at: "2026-05-06"
created_by: builder-agent
created_at: "2026-04-25T22:42:51+08:00"
evidence_count: 20
---

# MEM-ARCH-AVCODEC-S39: AVCodecVideoDecoder 视频解码器核心实现——CodecBase/VideoDecoder/VideoDecoderAdapter 三层架构

## Metadata

| 字段 | 值 |
|------|-----|
| **ID** | MEM-ARCH-AVCODEC-S39 |
| **标题** | AVCodecVideoDecoder 视频解码器核心实现——CodecBase/VideoDecoder/VideoDecoderAdapter 三层架构 |
| **Scope** | AVCodec, VideoDecoder, CodecBase, VideoDecoderAdapter, Filter, HardwareCodec, SoftwareCodec |
| **Pipeline Position** | FilterPipeline 中游：DemuxerFilter(S41) → VideoDecoderFilter → AudioDecoderFilter(S35) |
| **Status** | draft |
| **Created** | 2026-04-25T22:42:51+08:00 |
| **Evidence Count** | 20 |
| **关联主题** | S23(SurfaceEncoderAdapter桥接), S35(AudioDecoderFilter三层架构), S41(DemuxerFilter输出), S16(SurfaceCodec Surface绑定), S18(AudioCodecServer七状态机) |

---

## 架构正文

### 1. 三层调用链总览

AVCodecVideoDecoder 视频解码器在 AVCodec 架构中呈现**三层调用链**：

```
┌─────────────────────────────────────────────────────────────────┐
│  Filter 层（最上层）                                             │
│  VideoDecoderAdapter                                            │
│  services/media_engine/filters/video_decoder_adapter.cpp        │
│  实现 Filter 接口，内部持有 std::shared_ptr<MediaCodecCallback>  │
│  封装 MediaAVCodec::VideoDecoderFactory::CreateByMime/ByName   │
└──────────────────────────┬──────────────────────────────────────┘
                           │ std::shared_ptr<MediaCodecCallback> 回调驱动
┌──────────────────────────▼──────────────────────────────────────┐
│  Codec 引擎层（中层）                                           │
│  VideoDecoder（抽象基类）                                        │
│  services/engine/codec/video/decoderbase/video_decoder.h/cpp    │
│  继承 RenderSurface + CodecBase                                  │
│  管理缓冲区、状态机、三队列(inputAvailQue/codecAvailQue/render)  │
└──────────────────────────┬──────────────────────────────────────┘
                           │ virtual CreateDecoder()/SendFrame()
┌──────────────────────────▼──────────────────────────────────────┐
│  具体解码器实现层（底层）                                        │
│  HDecoder（硬件，hcodec/hdecoder.cpp）                           │
│  HEVCDecoder（硬件，hevcdecoder/hevc_decoder.cpp）               │
│  VPXDecoder（软件，vpxdecoder/vpxDecoder.cpp）                   │
│  AVCEncoder（视频编码，avcencoder/avc_encoder.cpp）              │
└─────────────────────────────────────────────────────────────────┘
```

**Evidence 1** - `interfaces/inner_api/native/avcodec_video_decoder.h` 行42-46：VideoDecoderFactory 工厂类声明，`CreateByMime` 和 `CreateByName` 两个静态工厂方法入口

```cpp
static std::shared_ptr<AVCodecVideoDecoder> CreateByMime(const std::string &mime);
static std::shared_ptr<AVCodecVideoDecoder> CreateByName(const std::string &name);
static int32_t CreateByMime(const std::string &mime, Format &format, std::shared_ptr<AVCodecVideoDecoder> &decoder);
static int32_t CreateByName(const std::string &name, Format &format, std::shared_ptr<AVCodecVideoDecoder> &decoder);
```

**Evidence 2** - `interfaces/inner_api/native/avcodec_video_decoder.h` 行20-41：AVCodecVideoDecoder 抽象接口（纯虚类），定义 Configure/Prepare/Start/Stop/Flush/Reset/Release/QueueInputBuffer/ReleaseOutputBuffer 等 15 个虚方法

```cpp
class AVCodecVideoDecoder {
public:
    virtual ~AVCodecVideoDecoder() = default;
    virtual int32_t Configure(const Format &format) = 0;
    virtual int32_t Prepare() = 0;
    virtual int32_t Start() = 0;
    virtual int32_t Stop() = 0;
    virtual int32_t Flush() = 0;
    virtual int32_t Reset() = 0;
    virtual int32_t Release() = 0;
    virtual int32_t SetOutputSurface(sptr<Surface> surface) = 0;
    virtual int32_t QueueInputBuffer(uint32_t index, AVCodecBufferInfo info, AVCodecBufferFlag flag) = 0;
    virtual int32_t ReleaseOutputBuffer(uint32_t index, bool render) = 0;
    virtual int32_t SetParameter(const Format &format) = 0;
    virtual int32_t SetCallback(const std::shared_ptr<AVCodecCallback> &callback) = 0;
    // ... QueryInputBuffer, QueryOutputBuffer, GetInputBuffer, GetOutputBuffer (API v6.0)
};
```

**Evidence 3** - `services/engine/codec/video/decoderbase/video_decoder.h` 行30-46：VideoDecoder 继承 RenderSurface 和 CodecBase 双基类，是所有具体解码器的抽象基类

```cpp
class VideoDecoder : public RenderSurface, public CodecBase {
public:
    explicit VideoDecoder(const std::string &name);
    ~VideoDecoder() = default;
    int32_t Init(Media::Meta &callerInfo) override;
    int32_t Start() override;
    int32_t Stop() override;
    int32_t Flush() override;
    int32_t Reset() override;
    int32_t Release() override;
    int32_t SetParameter(const Format &format) override;
    int32_t GetOutputFormat(Format &format) override;
    int32_t QueueInputBuffer(uint32_t index) override;
    int32_t ReleaseOutputBuffer(uint32_t index) override;
    int32_t SetCallback(const std::shared_ptr<MediaCodecCallback> &callback) override;
    virtual void ConfigurelWidthAndHeight(...) = 0;  // 具体解码器实现
    virtual void FlushAllFrames() {};               // 可重写
    virtual void FillHdrInfo(sptr<SurfaceBuffer>) {}; // 可重写
};
```

---

### 2. 状态机（State Machine）

**Evidence 4** - `services/engine/codec/video/decoderbase/coderstate.h` 行23-36：State 枚举定义 11 个状态，覆盖从 UNINITIALIZED 到 FROZEN 的完整生命周期

```cpp
enum class State : int32_t {
    UNINITIALIZED,   // 初始/ Release 后
    INITIALIZED,     // Initialize() 成功后
    CONFIGURED,      // Configure() 成功后
    STOPPING,        // Stop() 中
    RUNNING,         // Start() 成功后
    FLUSHED,         // Flush() 成功后
    FLUSHING,        // Flush() 中
    EOS,             // 输入 EOS 标记
    ERROR,           // 出错
    FREEZING,        // 内存冻结（内存紧张时）
    FROZEN,          // 已冻结
};
```

**Evidence 5** - `services/engine/codec/video/decoderbase/video_decoder.cpp` 行168：IsActive() 方法，只有 RUNNING/FLUSHED/EOS 状态才认为活跃

```cpp
bool VideoDecoder::IsActive() const
{
    return state_ == State::RUNNING || state_ == State::FLUSHED || state_ == State::EOS;
}
```

**Evidence 6** - `services/engine/codec/video/decoderbase/video_decoder.cpp` 行175-195：Start() 方法校验前置状态为 CONFIGURED 或 FLUSHED，调用 CreateDecoder() 创建解码器实例，然后 AllocateBuffers() 分配缓冲区，sendTask_->Start() 启动发送线程，最后 state_ → RUNNING

```cpp
int32_t VideoDecoder::Start()
{
    CHECK_AND_RETURN_RET_LOG((state_ == State::CONFIGURED || state_ == State::FLUSHED),
                             AVCS_ERR_INVALID_STATE, "Start codec failed: not in Configured or Flushed state");
    int32_t ret = CreateDecoder();  // 创建底层解码器
    int32_t allocateResult = AllocateBuffers();
    InitBuffers();
    sendTask_->Start();  // 启动 sendTask_ 线程
    state_ = State::RUNNING;
}
```

**Evidence 7** - `services/engine/codec/video/decoderbase/video_decoder.cpp` 行375-385：Flush() 方法，切换到 FLUSHING 状态，清空三个队列（inputAvailQue/codecAvailQue/sendTask_Pause），ResetBuffers()，最终 state_ → FLUSHED

```cpp
int32_t VideoDecoder::Flush()
{
    state_ = State::FLUSHING;
    inputAvailQue_->SetActive(false, false);
    codecAvailQue_->SetActive(false, false);
    sendTask_->Pause();
    ResetBuffers();
    FlushAllFrames();  // 调用具体解码器
    state_ = State::FLUSHED;
}
```

---

### 3. 缓冲区管理（Owner 枚举 + 三队列）

**Evidence 8** - `services/engine/codec/video/avcencoder/avc_encoder.h` 行81-85：Owner 枚举定义，CodecBuffer 的 owner_ 字段追踪缓冲区所有权，四种状态

```cpp
enum class Owner {
    OWNED_BY_US,      // 初始拥有者（框架层）
    OWNED_BY_CODEC,   // 解码器持有
    OWNED_BY_USER,    // 用户持有（已返回给应用）
    OWNED_BY_SURFACE, // Surface 持有（渲染中）
};
```

**Evidence 9** - `services/engine/codec/video/decoderbase/video_decoder.cpp` 行284-303：InitBuffers() 中，输入缓冲区 owner_ → OWNED_BY_USER（推入 inputAvailQue_），输出缓冲区 owner_ → OWNED_BY_CODEC（推入 codecAvailQue_）

```cpp
// 输入缓冲区
buffers_[INDEX_INPUT][i]->owner_ = Owner::OWNED_BY_USER;
callback_->OnInputBufferAvailable(i, buffers_[INDEX_INPUT][i]->avBuffer);
// 输出缓冲区（无 Surface 模式）
buffers_[INDEX_OUTPUT][i]->owner_ = Owner::OWNED_BY_CODEC;
codecAvailQue_->Push(i);
```

**Evidence 10** - `services/engine/codec/video/decoderbase/video_decoder.cpp` 行859-871：QueueInputBuffer() 将 buffer owner 从 OWNED_BY_USER 切换为 OWNED_BY_CODEC，并将 index 推入 inputAvailQue_

```cpp
int32_t VideoDecoder::QueueInputBuffer(uint32_t index)
{
    std::shared_ptr<CodecBuffer> inputBuffer = buffers_[INDEX_INPUT][index];
    CHECK_AND_RETURN_RET_LOG(inputBuffer->owner_ == Owner::OWNED_BY_USER, AVCS_ERR_INVALID_OPERATION,
                             "Queue input buffer failed: buffer not available, index=%{public}u", index);
    inputBuffer->owner_ = Owner::OWNED_BY_CODEC;
    inputAvailQue_->Push(index);
    return AVCS_ERR_OK;
}
```

**Evidence 11** - `services/engine/codec/video/decoderbase/video_decoder.cpp` 行1000-1018：ReleaseOutputBuffer() 将输出缓冲区 owner 从 OWNED_BY_USER 切换为 OWNED_BY_CODEC，并推入 codecAvailQue_

```cpp
int32_t VideoDecoder::ReleaseOutputBuffer(uint32_t index)
{
    std::shared_ptr<CodecBuffer> frameBuffer = buffers_[INDEX_OUTPUT][index];
    if (frameBuffer->owner_ == Owner::OWNED_BY_USER) {
        frameBuffer->owner_ = Owner::OWNED_BY_CODEC;
        codecAvailQue_->Push(index);
        return AVCS_ERR_OK;
    }
    return AVCS_ERR_INVALID_VAL;
}
```

**Evidence 12** - `services/engine/codec/video/decoderbase/video_decoder.cpp` 行700-750：AllocateBuffers() 创建三个 BlockQueue（inputAvailQue_/codecAvailQue_/renderAvailQue_），管理缓冲区可用性

```cpp
inputAvailQue_ = std::make_shared<BlockQueue<uint32_t>>("inputAvailQue", inputBufferCnt_);
codecAvailQue_ = std::make_shared<BlockQueue<uint32_t>>("codecAvailQue", outputBufferCnt_);
if (sInfo_.surface != nullptr) {
    renderAvailQue_ = std::make_shared<BlockQueue<uint32_t>>("renderAvailQue", outputBufferCnt_);
    requestSurfaceBufferQue_ = std::make_shared<BlockQueue<uint32_t>>("requestSurfaceBufferQue", outputBufferCnt_);
}
```

---

### 4. Surface 模式与 Buffer 模式

**Evidence 13** - `services/engine/codec/video/decoderbase/video_decoder.cpp` 行551-573：SetOutputSurface() 方法，支持在 CONFIGURED/FLUSHED/RUNNING/EOS 状态下动态切换输出 Surface；RUNNING/EOS 状态下调用 ReplaceOutputSurfaceWhenRunning()

```cpp
int32_t VideoDecoder::SetOutputSurface(sptr<Surface> surface)
{
    CHECK_AND_RETURN_RET_LOG(state_ != State::UNINITIALIZED, AV_ERR_INVALID_VAL,
                             "set output surface fail: not initialized");
    CHECK_AND_RETURN_RET_LOG((state_ == State::CONFIGURED || state_ == State::FLUSHED ||
        state_ == State::RUNNING || state_ == State::EOS), AVCS_ERR_INVALID_STATE,
        "set output surface fail: state_ %{public}d not support", state_.load());
    if (state_ == State::FLUSHED || state_ == State::RUNNING || state_ == State::EOS) {
        return ReplaceOutputSurfaceWhenRunning(surface);  // 动态热切换
    }
    sInfo_.surface = surface;
    RegisterListenerToSurface(sInfo_.surface);
}
```

**Evidence 14** - `services/engine/codec/video/decoderbase/video_decoder.cpp` 行481-510：AllocateOutputBuffer() vs AllocateOutputBuffersFromSurface() 两种分配路径——Buffer 模式（sInfo_.surface == nullptr）使用 AVAllocatorFactory 创建普通内存，Surface 模式使用 FSurfaceMemory 分配 SurfaceBuffer

```cpp
int32_t VideoDecoder::AllocateOutputBuffer(int32_t bufferCnt)  // Buffer 模式
{
    std::shared_ptr<AVAllocator> allocator =
        AVAllocatorFactory::CreateSurfaceAllocator(sInfo_.requestConfig);
    buf->avBuffer = AVBuffer::CreateAVBuffer(allocator, 0);
}

int32_t VideoDecoder::AllocateOutputBuffersFromSurface(int32_t bufferCnt)  // Surface 模式
{
    sptr<SurfaceBuffer> surfaceBuffer = nullptr;
    surfaceMemory->AllocSurfaceBuffer(width_, height_);  // DMA-BUF 内存
    surfaceMemory->isAttached = true;
}
```

---

### 5. VideoDecoderAdapter（Filter 层封装）

**Evidence 15** - `services/media_engine/filters/video_decoder_adapter.cpp` 行30-39：DECODER_USAGE 定义缓冲区用途（CPU_READ|CPU_WRITE|MEM_DMA|VIDEO_DECODER），用于 Surface 内存申请

```cpp
constexpr uint64_t DECODER_USAGE =
    BUFFER_USAGE_CPU_READ | BUFFER_USAGE_CPU_WRITE | BUFFER_USAGE_MEM_DMA | BUFFER_USAGE_VIDEO_DECODER;
```

**Evidence 16** - `services/media_engine/filters/video_decoder_adapter.cpp` 行40-55：VideoDecoderCallback 桥接类，持有 `wptr<VideoDecoderAdapter>`，将 MediaCodecCallback 回调转发给 VideoDecoderAdapter

```cpp
class VideoDecoderCallback : public MediaAVCodec::MediaCodecCallback {
public:
    explicit VideoDecoderCallback(std::shared_ptr<VideoDecoderAdapter> videoDecoder);
    void OnError(MediaAVCodec::AVCodecErrorType errorType, int32_t errorCode) override;
    void OnOutputFormatChanged(const MediaAVCodec::Format &format) override;
    void OnInputBufferAvailable(uint32_t index, std::shared_ptr<AVBuffer> buffer) override;
    void OnOutputBufferAvailable(uint32_t index, std::shared_ptr<AVBuffer> buffer) override;
};
```

**Evidence 17** - `services/media_engine/filters/video_decoder_adapter.cpp` 行139-160：VideoDecoderAdapter::Init() 调用 VideoDecoderFactory::CreateByMime 或 CreateByName，返回 std::shared_ptr<MediaCodecCallback> 并设置 appPid/appUid/bundleName 到 callerInfo Meta

```cpp
Status VideoDecoderAdapter::Init(MediaAVCodec::AVCodecType type, bool isMimeType, const std::string &name)
{
    std::shared_ptr<Media::Meta> callerInfo = std::make_shared<Media::Meta>();
    callerInfo->SetData(Media::Tag::AV_CODEC_FORWARD_CALLER_PID, appPid_);
    callerInfo->SetData(Media::Tag::AV_CODEC_FORWARD_CALLER_UID, appUid_);
    callerInfo->SetData(Media::Tag::AV_CODEC_FORWARD_CALLER_PROCESS_NAME, bundleName_);
    if (isMimeType) {
        ret = MediaAVCodec::VideoDecoderFactory::CreateByMime(name, format, mediaCodec_);
    } else {
        ret = MediaAVCodec::VideoDecoderFactory::CreateByName(name, format, mediaCodec_);
    }
}
```

**Evidence 18** - `services/media_engine/filters/video_decoder_adapter.cpp` 行330-380：AquireAvailableInputBuffer() 从 AVBufferQueueConsumer 消费输入缓冲区，处理 PTS/DTS 队列，调用 mediaCodec_->QueueInputBuffer() 提交到底层解码器

```cpp
void VideoDecoderAdapter::AquireAvailableInputBuffer()
{
    std::shared_ptr<AVBuffer> tmpBuffer;
    if (inputBufferQueueConsumer_->AcquireBuffer(tmpBuffer) == Status::OK) {
        if (ptsManagedFileTypes.find(static_cast<FileType>(fileType_)) != ptsManagedFileTypes.end()) {
            GetInputBufferDts(tmpBuffer);  // DTS 入队
        }
        RecordTimeStamp(*tmpBuffer, StallingStage::DECODER_START);
        int32_t ret = mediaCodec_->QueueInputBuffer(index);  // 提交到解码器
    }
}
```

---

### 6. 硬件解码器（HDecoder）具体实现

**Evidence 19** - `services/engine/codec/video/hcodec/hdecoder.cpp` 行59-75：HDecoder 构造函数继承 CodecHDI 硬件抽象，接收 CodecCompCapability 和 codingType（OMX_VIDEO_CODINGTYPE），设置 isReleaseWithSeq_ 参数（surface 模式下是否按序释放）

```cpp
HDecoder::HDecoder(CodecHDI::CodecCompCapability caps, OMX_VIDEO_CODINGTYPE codingType)
    : HCodec(caps, codingType, false)  // false = decoder
{
    isReleaseWithSeq_ = OHOS::system::GetBoolParameter("hcodec.surfacemode.release_with_seq", true);
}
```

**Evidence 20** - `services/engine/codec/video/hcodec/hdecoder.cpp` 行100-145：OnConfigure() 中 SetupPort() 根据 format 参数（宽/高/像素格式/帧率）配置 OMX 端口，设置颜色空间/HDR/帧率自适应/VRR 等能力

```cpp
int32_t HDecoder::OnConfigure(const Format &format)
{
    SupportBufferType type;
    InitOMXParamExt(type);
    if (GetParameter(OMX_IndexParamSupportBufferType, type) && ...) { /* buffer type */ }
    SetLowLatency(format);
    SetColorAspects(format);
    SetMasteringDisplayColourVolumeFromContainer(format);
    SetFrameRateAdaptiveMode(format);
    SetVrrEnable(format);
    return SetupPort(format);
}
```

---

## 关联记忆

| 关联ID | 关系 |
|--------|------|
| MEM-ARCH-AVCODEC-S23 | SurfaceEncoderAdapter 对应 Player 侧 SurfaceDecoderFilter |
| MEM-ARCH-AVCODEC-S35 | AudioDecoderFilter 三层架构（对称于 VideoDecoderFilter） |
| MEM-ARCH-AVCODEC-S41 | DemuxerFilter 输出到 VideoDecoderFilter 的上游关系 |
| MEM-ARCH-AVCODEC-S16 | SurfaceCodec 与 Surface 的绑定机制（SetOutputSurface） |
| MEM-ARCH-AVCODEC-S18 | AudioCodecServer 七状态机（对照 VideoDecoder 十一状态） |

## 技术栈索引

- `interfaces/inner_api/native/avcodec_video_decoder.h` — AVCodecVideoDecoder 公开 API
- `services/engine/codec/video/decoderbase/video_decoder.h` — VideoDecoder 基类定义
- `services/engine/codec/video/decoderbase/video_decoder.cpp` — VideoDecoder 实现
- `services/engine/codec/video/decoderbase/coderstate.h` — State 枚举定义
- `services/engine/codec/video/decoderbase/render_surface.h` — RenderSurface 基类
- `services/media_engine/filters/video_decoder_adapter.cpp` — VideoDecoderAdapter Filter 封装
- `services/engine/codec/video/hcodec/hdecoder.cpp` — HDecoder 硬件解码器实现
- `services/engine/codec/video/hevcdecoder/hevc_decoder.cpp` — HEVC 解码器实现
- `services/engine/codec/video/vpxdecoder/vpxDecoder.cpp` — VP8/VP9/AV1 软件解码器实现
