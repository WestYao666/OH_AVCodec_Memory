# MEM-ARCH-AVCODEC-S231: VideoDecoder Base Class + RenderSurface + VpxDecoder 三层架构

> 本地镜像探索版 | 2026-06-08 | builder-agent (subagent)
> 来源：/home/west/av_codec_repo/services/engine/codec/video/decoderbase/ + vpxdecoder/
> 关联：S39/S54/S45/S46/S55/S57/S70

## 主题

VideoDecoder 基类 + RenderSurface 双组件核心架构——视频解码器基类（1122行cpp+157行h）+ Surface缓冲管理（553行cpp+120行h）+ VpxDecoder VP8/VP9软件解码器（625行cpp+86行h）三层继承体系。

---

## 一、VideoDecoder 基类架构（video_decoder.h/cpp）

### 1.1 多继承结构

**E1: video_decoder.h L39-40 — 多继承：VideoDecoder 继承 RenderSurface + CodecBase**
```cpp
class VideoDecoder : public RenderSurface, public CodecBase {
```
VideoDecoder 同时继承 RenderSurface（Surface缓冲管理）和 CodecBase（编解码器通用接口），构成双继承结构。

**E2: video_decoder.h L46-65 — CodecBase 虚接口实现**
```cpp
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
int32_t NotifyMemoryRecycle() override;
int32_t NotifyMemoryWriteBack() override;
int32_t Configure(const Format &format) override;
int32_t SetOutputSurface(sptr<Surface> surface) override;
int32_t RenderOutputBuffer(uint32_t index) override;
```
覆盖 CodecBase 全部14个虚接口，实现完整的编解码生命周期管理。

**E3: video_decoder.h L82-93 — 核心成员变量**
```cpp
uint32_t decInstanceID_ = 0;
static std::vector<uint32_t> freeIDSet_;
static std::vector<uint32_t> decInstanceIDSet_;
void* handle_ = nullptr;
std::string codecName_;
bool isValid_ = true;
std::shared_ptr<MediaCodecCallback> callback_;
std::shared_ptr<TaskThread> sendTask_ = nullptr;
std::shared_ptr<AVFrame> cachedFrame_ = nullptr;
std::atomic<bool> isSendEos_ = false;
std::shared_ptr<BlockQueue<uint32_t>> inputAvailQue_;
std::shared_ptr<Scale> scale_ = nullptr;
```
关键成员：实例ID池（freeIDSet_/decInstanceIDSet_）、TaskThread驱动的SendFrame异步任务、cachedFrame_解码帧缓存。

### 1.2 生命周期管理

**E4: video_decoder.cpp L230-270 — Configure状态迁移：INITIALIZED→CONFIGURED**
```cpp
format_.PutIntValue(MediaDescriptionKey::MD_KEY_WIDTH, DEFAULT_VIDEO_WIDTH);  // 1920
format_.PutIntValue(MediaDescriptionKey::MD_KEY_HEIGHT, DEFAULT_VIDEO_HEIGHT); // 1080
format_.PutIntValue(MediaDescriptionKey::MD_KEY_MAX_OUTPUT_BUFFER_COUNT, DEFAULT_OUT_BUFFER_CNT); // 3
format_.PutIntValue(MediaDescriptionKey::MD_KEY_MAX_INPUT_BUFFER_COUNT, DEFAULT_IN_BUFFER_CNT); // 4
```
Configure在INITIALIZED状态执行，设置默认宽高（1920×1080）和缓冲计数后迁移至CONFIGURED。

**E5: video_decoder.cpp L157-180 — Start 状态迁移：CONFIGURED/FLUSHED→RUNNING**
```cpp
CHECK_AND_RETURN_RET_LOG((state_ == State::CONFIGURED || state_ == State::FLUSHED), AVCS_ERR_INVALID_STATE, ...);
int32_t ret = CreateDecoder();
int32_t allocateResult = AllocateBuffers();
sendTask_->Start();
state_ = State::RUNNING;
```
Start在CONFIGURED或FLUSHED状态执行，创建解码器+分配缓冲+启动SendFrame线程后迁移至RUNNING。

**E6: video_decoder.cpp L352-370 — Stop 状态迁移：RUNNING→CONFIGURED**
```cpp
state_ = State::STOPPING;
inputAvailQue_->SetActive(false, false);
codecAvailQue_->SetActive(false, false);
sendTask_->Stop();
DeleteDecoder();
ReleaseBuffers();
state_ = State::CONFIGURED;
```
Stop停止线程、释放解码器和缓冲，回退至CONFIGURED（而非UNINITIALIZED）。

**E7: video_decoder.cpp L372-390 — Flush 状态迁移：RUNNING/EOS→FLUSHED**
```cpp
state_ = State::FLUSHING;
inputAvailQue_->SetActive(false, false);
codecAvailQue_->SetActive(false, false);
sendTask_->Pause();
ResetBuffers();
FlushAllFrames();
state_ = State::FLUSHED;
```
Flush暂停SendFrame线程、清空缓冲队列后迁移至FLUSHED，保留解码器实例（可快速恢复）。

**E8: video_decoder.cpp L392-403 — Reset 完整重置流程**
```cpp
int32_t ret = Release();  // → UNINITIALIZED
ret = Initialize(); // → INITIALIZED
```
Reset调用Release（→UNINITIALIZED）再调用Initialize（→INITIALIZED），完整重置而非仅重配置。

### 1.3 三队列缓冲管理

**E9: video_decoder.cpp L272-310 — InitBuffers 三队列激活**
```cpp
inputAvailQue_->SetActive(true);
codecAvailQue_->SetActive(true);
if (sInfo_.surface != nullptr) {
    renderAvailQue_->SetActive(true);
    requestSurfaceBufferQue_->SetActive(true);
}
for (uint32_t i = 0; i < buffers_[INDEX_INPUT].size(); i++) {
    buffers_[INDEX_INPUT][i]->owner_ = Owner::OWNED_BY_USER;
    callback_->OnInputBufferAvailable(i, buffers_[INDEX_INPUT][i]->avBuffer);
}
```
InitBuffers激活三队列（inputAvailQue_/codecAvailQue_/+render/requestSurfaceBufferQue_）并向用户回调可用输入缓冲。

**E10: video_decoder.cpp L430-470 — AllocateOutputBuffer/AllocateOutputBuffersFromSurface 双模式**
```cpp
// Buffer模式（非Surface）：使用AVAllocator分配普通AVBuffer
int32_t AllocateOutputBuffer(int32_t bufferCnt) {
    buf->avBuffer = AVBuffer::CreateAVBuffer(allocator, 0);
    SetCallerToBuffer(buf->avBuffer->memory_->GetSurfaceBuffer());
    buffers_[INDEX_OUTPUT].emplace_back(buf);
}
// Surface模式：使用SurfaceAllocator分配SurfaceBuffer
int32_t AllocateOutputBuffersFromSurface(int32_t bufferCnt) {
    surfaceMemory->AllocSurfaceBuffer(width_, height_);
    sptr<SurfaceBuffer> surfaceBuffer = surfaceMemory->GetSurfaceBuffer();
    Attach(surfaceBuffer);  // AttachBufferToQueue
    buf->avBuffer = AVBuffer::CreateAVBuffer(buf->sMemory->GetBase(), buf->sMemory->GetSize());
    buffers_[INDEX_OUTPUT].emplace_back(buf);
}
```
输出缓冲分配分Buffer模式和Surface模式：Buffer模式用AVAllocator，Surface模式用SurfaceAllocator+AttachBufferToQueue。

**E11: video_decoder.cpp L545-580 — CalculateBufferSize 按codec计算输入缓冲大小**
```cpp
} else if (codecName_ == AVCodecCodecName::VIDEO_DECODER_VP8_NAME) {
    inputBufferSize_ = static_cast<UINT32>(width_ * height_ * VIDEO_PLANE_COUNT_YUV) >> 1; // 1.5x
} else if (codecName_ == AVCodecCodecName::VIDEO_DECODER_VP9_NAME ||
           codecName_ == AVCodecCodecName::VIDEO_DECODER_AV1_NAME) {
    inputBufferSize_ = static_cast<UINT32>(width_ * height_ * VIDEO_PLANE_COUNT_YUV * VIDEO_PLANE_SIZE_YUVP10) >> 3; // 10bit×1.5/8
}
if (inputBufferSize_ <= VIDEO_MIN_BUFFER_SIZE) {
    inputBufferSize_ = VIDEO_MIN_BUFFER_SIZE; // 1474560 (1280×768×1.5)
}
```
VP8输入缓冲=宽×高×1.5，VP9/AV1=宽×高×1.5×10/8，最低1474560字节。

### 1.4 实例池管理

**E12: video_decoder.h L77-78 — 静态实例池**
```cpp
static std::mutex decoderCountMutex_;
static std::vector<uint32_t> freeIDSet_;
static std::vector<uint32_t> decInstanceIDSet_;
uint32_t decInstanceID_ = 0;
```
全局静态互斥锁保护两个向量：freeIDSet_（已释放ID回收池）+decInstanceIDSet_（当前活跃ID集合），实现实例ID池化复用。

**E13: vpxDecoder.cpp L63-82 — 实例ID分配/回收**
```cpp
if (!freeIDSet_.empty()) {
    decInstanceID_ = freeIDSet_[0];
    freeIDSet_.erase(freeIDSet_.begin());
    decInstanceIDSet_.push_back(decInstanceID_);
} else if (freeIDSet_.size() + decInstanceIDSet_.size() < VIDEO_INSTANCE_SIZE) {
    decInstanceID_ = freeIDSet_.size() + decInstanceIDSet_.size();
    decInstanceIDSet_.push_back(decInstanceID_);
} else {
    decInstanceID_ = VIDEO_INSTANCE_SIZE + 1; // 超限
}
~VpxDecoder() { freeIDSet_.push_back(decInstanceID_); ... }
```
析构时将ID推回freeIDSet_，新实例优先复用已回收ID；VIDEO_INSTANCE_SIZE=64上限。

### 1.5 Surface模式输出

**E14: video_decoder.cpp L550-575 — SetOutputSurface 支持运行时切换Surface**
```cpp
int32_t VideoDecoder::SetOutputSurface(sptr<Surface> surface)
{
    if (state_ == State::FLUSHED || state_ == State::RUNNING || state_ == State::EOS) {
        return ReplaceOutputSurfaceWhenRunning(surface); // 运行时热切换
    }
    sInfo_.surface = surface;
    CombineConsumerUsage();
    RegisterListenerToSurface(sInfo_.surface);
}
```
SetOutputSurface在FLUSHED/RUNNING/EOS状态时调用ReplaceOutputSurfaceWhenRunning热切换Surface，在其他状态时直接设置。

**E15: video_decoder.cpp L600-640 — RenderOutputBuffer 三状态Owner管理**
```cpp
if (frameBuffer->owner_ == Owner::OWNED_BY_USER) {
    frameBuffer->owner_ = Owner::OWNED_BY_SURFACE;
    FlushSurfaceMemory(surfaceMemory, index);  // FlushBuffer到Surface
}
```
RenderOutputBuffer要求owner为OWNED_BY_USER，切换为OWNED_BY_SURFACE后FlushBuffer交付给Consumer。

---

## 二、RenderSurface 组件（render_surface.h/cpp）

### 2.1 三缓冲队列架构

**E16: render_surface.h L47-55 — 三缓冲队列**
```cpp
std::shared_ptr<BlockQueue<uint32_t>> renderAvailQue_;      // Surface Consumer归还的缓冲
std::shared_ptr<BlockQueue<uint32_t>> requestSurfaceBufferQue_; // 从Surface请求新缓冲
std::shared_ptr<BlockQueue<uint32_t>> codecAvailQue_; // Codec输出可用缓冲
std::vector<std::shared_ptr<CodecBuffer>> buffers_[2];     // [0]=输入缓冲，[1]=输出缓冲
```
三队列+双缓冲向量（INPUT/OUTPUT）构成完整的缓冲循环管理体系。

**E17: render_surface.h L57-62 — CodecBuffer结构体（Owner原子状态）**
```cpp
struct CodecBuffer {
    std::shared_ptr<AVBuffer> avBuffer = nullptr;
    std::shared_ptr<FSurfaceMemory> sMemory = nullptr;
    std::atomic<Owner> owner_ = Owner::OWNED_BY_US;
    int32_t width = 0, height = 0, bitDepth =8;
    std::atomic<bool> hasSwapedOut = false;
};
```
CodecBuffer持有多态缓冲（AVBuffer或FSurfaceMemory），Owner原子状态标识缓冲归属（OWNED_BY_US/OWNER_BY_USER/OWNED_BY_SURFACE）。

**E18: render_surface.h L67-74 — 状态与Surface配置**
```cpp
std::atomic<State> state_ = State::UNINITIALIZED;
SurfaceControl sInfo_;
int32_t width_ = 0, height_ = 0;
VideoPixelFormat outputPixelFmt_ = VideoPixelFormat::UNKNOWN;
int32_t outputBufferCnt_ = 0;
std::atomic<GraphicTransformType> transform_ = GraphicTransformType::GRAPHIC_ROTATE_NONE;
int32_t bitDepth_ = BITS_PER_PIXEL_COMPONENT_8;
```
RenderSurface直接持有state_原子变量（与VideoDecoder共享，通过继承），构成状态协调基础。

### 2.2 运行时Surface切换

**E19: render_surface.cpp L25-75 — ReplaceOutputSurfaceWhenRunning 热切换流程**
```cpp
int32_t RenderSurface::ReplaceOutputSurfaceWhenRunning(sptr<Surface> newSurface)
{
    sptr<Surface> curSurface = sInfo_.surface;
    uint64_t oldId = curSurface->GetUniqueId();
    uint64_t newId = newSurface->GetUniqueId();
    RegisterListenerToSurface(newSurface);  // 注册新Surface监听
    SetQueueSize(newSurface, outputBufferCnt_);
    SwitchBetweenSurface(newSurface);        // 切换缓冲映射
    UnRegisterListenerToSurface(curSurface); // 注销旧Surface
    curSurface->CleanCache(true);            // 清空旧Surface
}
```
热切换四步：注册新监听→设队列大小→SwitchBetweenSurface迁移缓冲→注销旧Surface并清空。

**E20: render_surface.cpp L107-180 — SwitchBetweenSurface 缓冲映射迁移**
```cpp
int32_t RenderSurface::SwitchBetweenSurface(const sptr<Surface> &newSurface)
{
    newSurface->Connect();
    newSurface->CleanCache();
    newSurface->Disconnect();
    for (uint32_t index = 0; index < buffers_[INDEX_OUTPUT].size(); index++) {
        if (buffers_[INDEX_OUTPUT][index]->owner_ == Owner::OWNED_BY_SURFACE) {
            // 从旧Surface detach，重新Attach到新Surface
            surfaceBuffer = surfaceMemory->GetSurfaceBuffer();
            newSurface->AttachBufferToQueue(surfaceBuffer);
        }
    }
    sInfo_.surface = newSurface;
    CombineConsumerUsage();
}
```
SwitchBetweenSurface遍历所有输出缓冲，对OWNED_BY_SURFACE的缓冲执行detach→AttachBufferToQueue→FlushBuffer迁移到新Surface。

### 2.3 Consumer缓冲归还

**E21: render_surface.cpp L340-380 — BufferReleasedByConsumer 消费者归还回调**
```cpp
GSError RenderSurface::BufferReleasedByConsumer(uint64_t surfaceId)
{
    CHECK_AND_RETURN_RET_LOG(state_ == State::RUNNING || state_ == State::EOS ||
        state_ == State::FLUSHING || state_ == State::FLUSHED, GSERROR_NO_PERMISSION, "Invalid state");
    RequestBufferFromConsumer();
    return GSERROR_OK;
}
void RenderSurface::RequestBufferFromConsumer()
{
    auto index = renderAvailQue_->Front();
    RequestSurfaceBufferOnce(index);  // 向Consumer请求新缓冲
    buffers_[INDEX_OUTPUT][curIndex]->owner_ = Owner::OWNED_BY_CODEC;
    codecAvailQue_->Push(curIndex); // 推入codec可用队列
}
```
Consumer释放缓冲时触发BufferReleasedByConsumer回调，从renderAvailQue_取出索引，请求新SurfaceBuffer后推入codecAvailQue_。

### 2.4 请求缓冲线程

**E22: render_surface.cpp L93-102 — StartRequestSurfaceBufferThread 后台线程**
```cpp
void RenderSurface::StartRequestSurfaceBufferThread()
{
    if (!mRequestSurfaceBufferThread_.joinable()) {
        requestBufferThreadExit_ = false;
        mRequestSurfaceBufferThread_ = std::thread(&RenderSurface::RequestSurfaceBufferThread, this);
    }
}
std::thread mRequestSurfaceBufferThread_;
std::atomic<bool> requestBufferThreadExit_ = false;
```
RenderSurface持有独立后台线程mRequestSurfaceBufferThread_持续向Surface Consumer请求可用缓冲，实现缓冲预获取。

**E23: render_surface.cpp L182-210 — RequestSurfaceBufferOnce 同步请求模式**
```cpp
bool RenderSurface::RequestSurfaceBufferOnce(uint32_t index)
{
    requestSurfaceBufferQue_->Push(index);
    requestBufferCV_.notify_one();
    requestBufferOnceDoneCV_.wait(lck, [this]() { return requestBufferFinished_.load(); });
    CHECK_AND_RETURN_RET_LOG(requestSucceed_.load(), false, "Output surface memory allocate failed");
    return true;
}
```
RequestSurfaceBufferOnce推入请求索引→通知线程→等待requestBufferOnceDoneCV_条件变量，实现同步阻塞请求模式。

---

## 三、VpxDecoder VP8/VP9软件解码器（vpxDecoder.h/cpp/api）

### 3.1 多格式支持

**E24: vpxDecoder.cpp L32-39 — SUPPORT_VPX_DECODER 表驱动注册**
```cpp
constexpr struct {
    const std::string_view codecName;
    const std::string_view mimeType;
} SUPPORT_VPX_DECODER[] = {
#ifdef SUPPORT_CODEC_VP8
    {AVCodecCodecName::VIDEO_DECODER_VP8_NAME, CodecMimeType::VIDEO_VP8},
#endif
#ifdef SUPPORT_CODEC_VP9
    {AVCodecCodecName::VIDEO_DECODER_VP9_NAME, CodecMimeType::VIDEO_VP9},
#endif
};
```
SUPPORT_VPX_DECODER表驱动codecName→mimeType映射，通过编译宏SUPPORT_CODEC_VP8/VP9条件编译实现变体。

**E25: vpxDecoder.cpp L40-58 — 能力参数（分辨率/帧率/块数）**
```cpp
constexpr int32_t VIDEO_INSTANCE_SIZE = 64;
constexpr int32_t VP8_MAX_WIDTH_SIZE = 3840, VP8_MAX_HEIGHT_SIZE = 2160;
constexpr int32_t VP9_MAX_WIDTH_SIZE = 3840, VP9_MAX_HEIGHT_SIZE = 2160;
constexpr int32_t VP9_BLOCKPERSEC_SIZE = 648000;
constexpr int32_t VP8_BLOCKPERSEC_SIZE = 972000;
constexpr int32_t VP9_FRAMERATE_MAX_SIZE = 130;
constexpr int32_t VIDEO_FRAMERATE_DEFAULT_SIZE = 60;
```
VP8最大支持972000块/秒，VP9最大648000块/秒（因VP9压缩率更高）；VP9最大帧率130fps vs 默认60fps。

### 3.2 libvpx集成

**E26: vpxDecoder.cpp L547-565 — VpxCreateDecoderFunc 创建libvpx解码器上下文**
```cpp
int VpxDecoder::VpxCreateDecoderFunc(void **vpxDecoder, const char *name)
{
    vpx_codec_ctx_t *ctx = (vpx_codec_ctx_t *)malloc(sizeof(*ctx));
    decoder = get_vpx_decoder_by_name(name);
    if (vpx_codec_dec_init(ctx, decoder->codec_interface(), NULL, VPX_CODEC_USE_FRAME_THREADING)) {
        free(ctx);
        return -1;
    }
    *vpxDecoder = ctx;
    return 0;
}
```
直接malloc分配vpx_codec_ctx_t，通过get_vpx_decoder_by_name按名称查找解码器接口，VPX_CODEC_USE_FRAME_THREADING启用帧级多线程。

**E27: vpxDecoder.cpp L567-580 — VpxDecodeFrameFunc/VpxGetFrameFunc 管线**
```cpp
int VpxDecoder::VpxDecodeFrameFunc(void *vpxDecoder, const unsigned char *frame, unsigned int frameSize)
{
    vpx_codec_ctx_t *codec = (vpx_codec_ctx_t *)vpxDecoder;
    int ret = vpx_codec_decode(codec, frame, frameSize, NULL, 0);
}
int VpxDecoder::VpxGetFrameFunc(void *vpxDecoder, vpx_image_t **outputImg)
{
    vpx_codec_ctx_t *codec = (vpx_codec_ctx_t *)vpxDecoder;
    vpx_codec_iter_t iter = NULL;
    *outputImg = vpx_codec_get_frame(codec, &iter);
}
```
libvpx解码两段式：DecodeFrameFunc注入压缩数据→GetFrameFunc迭代获取解码图像（与avcodec_send_packet/avcodec_receive_frame对称）。

### 3.3 SendFrame线程驱动

**E28: vpxDecoder.cpp L335-380 — SendFrame EOS处理**
```cpp
void VpxDecoder::SendFrame()
{
    if (state_ == State::STOPPING || state_ == State::FLUSHING) return;
    if (state_ != State::RUNNING || isSendEos_ || codecAvailQue_->Size() == 0u) {
        std::this_thread::sleep_for(std::chrono::milliseconds(DEFAULT_TRY_DECODE_TIME)); // 1ms轮询
    }
    if (inputAVBuffer->flag_ & AVCODEC_BUFFER_FLAG_EOS) {
        isSendEos_ = true;
    }
    do { ret = DecodeFrameOnce(); } while (isSendEos_ && ret == 0);  // EOS时消费所有待解码帧
    if (isSendEos_) {
        frameBuffer->avBuffer->flag_ = AVCODEC_BUFFER_FLAG_EOS;
        FramePostProcess(buffers_[INDEX_OUTPUT][outIndex], outIndex, AVCS_ERR_OK);
        state_ = State::EOS;
    }
}
```
SendFrame在非RUNNING或空队列时sleep1ms轮询；EOS时do-while循环消费所有待解码帧后发送EOS标志。

**E29: vpxDecoder.cpp L382-420 — DecodeFrameOnce 帧级解码**
```cpp
int32_t VpxDecoder::DecodeFrameOnce()
{
    if (!isSendEos_) {
        ret = VpxDecodeFrameFunc(vpxDecHandle_, vpxDecoderInputArgs_.pStream, ...);
    }
    VpxGetFrameFunc(vpxDecHandle_, &vpxDecOutputImg_);
    if (vpxDecOutputImg_ != nullptr) {
        int32_t bitDepth = static_cast<int32_t>(vpxDecOutputImg_->bit_depth);
        ConvertDecOutToAVFrame();
        auto index = codecAvailQue_->Front();
        if (CheckFormatChange(...) == AVCS_ERR_OK) {
            status = FillFrameBuffer(frameBuffer);
        } else {
            callback_->OnError(...); state_ = State::ERROR; return -1;
        }
        FramePostProcess(frameBuffer, index, status);
    }
}
```
DecodeFrameOnce先Decode再GetFrame，bit_depth>8时触发10bit路径；CheckFormatChange检测分辨率变化。

### 3.4 HDR元数据注入

**E30: vpxDecoder.cpp L125-155 — ConfigureHdrMetadata HDR参数提取**
```cpp
void VpxDecoder::ConfigureHdrMetadata(const Format &format)
{
    format.GetIntValue(MediaDescriptionKey::MD_KEY_RANGE_FLAG, colorSpaceInfo_.fullRangeFlag);
    format.GetIntValue(MediaDescriptionKey::MD_KEY_COLOR_PRIMARIES, colorSpaceInfo_.colorPrimaries);
    format.GetIntValue(MediaDescriptionKey::MD_KEY_TRANSFER_CHARACTERISTICS, colorSpaceInfo_.transferCharacteristic);
    format.GetIntValue(MediaDescriptionKey::MD_KEY_MATRIX_COEFFICIENTS, colorSpaceInfo_.matrixPrimaries);
    uint8_t *extraData = nullptr;
    format.GetBuffer(MediaDescriptionKey::MD_KEY_VIDEO_HDR_METADATA, &extraData, extraSize);
    const AVMasteringDisplayMetadata *metadata = (AVMasteringDisplayMetadata *)extraData;
    hdrMetadata_.displayPrimariesX[0] = safeDiv(metadata->display_primaries[0][0].num, ...);
    // ... 提取6个display_primaries + white_point + max/min_luminance
    colorSpaceInfo_.colorDescriptionPresentFlag = 1;
}
```
从Format提取AVMasteringDisplayMetadata（libavutil结构），解析display_primaries[3]三基色+white_point+max/min_luminance。

**E31: vpxDecoder.cpp L538-548 — FillHdrInfo SurfaceBuffer元数据注入**
```cpp
void VpxDecoder::FillHdrInfo(sptr<SurfaceBuffer> surfaceBuffer)
{
    surfaceBuffer->SetMetadata(ATTRKEY_COLORSPACE_INFO, colorSpaceInfoVec);
    surfaceBuffer->SetMetadata(ATTRKEY_HDR_STATIC_METADATA, staticMetadataVec);
    surfaceBuffer->SetMetadata(ATTRKEY_HDR_METADATA_TYPE, metadataTypeVec);
}
```
向SurfaceBuffer注入三种HDI元数据：colorspace_info（HDR10）/hdr_static_metadata（SMPTE2086）/hdr_metadata_type（转换函数类型）。

---

## 四、CoderState十一态机

**E32: coderstate.h — 状态枚举**
```cpp
enum class State : int32_t {
    UNINITIALIZED,  // 初始
    INITIALIZED, // Initialize()后
    CONFIGURED,     // Configure()后
    STOPPING,       // Stop()中
    RUNNING,        // Start()后
    FLUSHED,        // Flush()后
    FLUSHING,       // Flush()中
    EOS,            // 解码结束
    ERROR,          // 错误
    FREEZING,       // 冻结中
    FROZEN,         // 已冻结
};
```
11个状态：UNINITIALIZED→INITIALIZED→CONFIGURED→RUNNING→(EOS/FLUSHED/ERROR/FREEZING/FROZEN/STOPPING)。

---

## 五、关系总结

### 架构继承链
```
CodecBase (虚接口基类)
    ↑
VideoDecoder (1122行cpp+157行h，继承RenderSurface+CodecBase)
    ↑
VpxDecoder (625行cpp+86行h，VP8/VP9软件解码器)
```

### 关键设计模式
1. **多继承分工**：RenderSurface管Surface缓冲+三队列+Consumer回调，VideoDecoder管编解码生命周期+实例池
2. **三队列循环**：inputAvailQue_（用户→解码器）→codecAvailQue_（解码器→用户）→renderAvailQue_（Surface Consumer→解码器）
3. **Owner三态原子**：OWNED_BY_USER / OWNED_BY_CODEC / OWNED_BY_SURFACE，通过atomic实现无锁状态切换
4. **实例ID池化**：freeIDSet_回收池（O(1)push/pop）+decInstanceIDSet_活跃集，最多64实例
5. **SendFrame线程**：TaskThread驱动，每1ms轮询inputAvailQue_+codecAvailQue_，EOS时消费所有待解码帧
6. **Surface热切换**：运行时ReplaceOutputSurfaceWhenRunning→SwitchBetweenSurface迁移缓冲映射→CleanCache清空旧Surface
7. **libvpx两段式**：VpxDecodeFrameFunc（注入）→VpxGetFrameFunc（迭代提取），无帧级多Buffer缓冲

### 关联记忆
- **S39**（VideoDecoderFilter）：Filter层适配VideoDecoder Base Class
- **S45/S46**（DecoderSurfaceFilter）：Surface模式输出到FilterPipeline
- **S54**（HevcDecoder/VpxDecoder）：VPX解码器能力注册
- **S55**（CodecCallback）：OnInputBufferAvailable/OnOutputBufferAvailable回调
- **S57/S70**（AvcEncoder/HevcDecoder）：硬件编码器对比参考