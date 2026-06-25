---
id: MEM-ARCH-AVCODEC-S242
title: AvcEncoder 硬件H.264编码器——libavcenc_ohos.z.so HDI三层接口与CodecBase九态机
type: architecture_fact
scope: [AVCodec, VideoEncoder, HardwareCodec, HDI, AVC, H.264, dlopen, SurfaceMode, CodecBase, RefBase]
status: pending_approval
created: 2026-06-21T10:46 GMT+8
source: /home/west/av_codec_repo/services/engine/codec/video/avcencoder/
association: [S57, S70, S183, S229, S236, S239]
---

# MEM-ARCH-AVCODEC-S242: AvcEncoder 硬件H.264编码器

> 本地镜像源码探索 | 2026-06-21 | builder-agent (subagent)
> 来源：/home/west/av_codec_repo/services/engine/codec/video/avcencoder/

---

## 主题

AvcEncoder 是 MediaEngine Engine 层的硬件 H.264/AVC 编码器封装，通过 dlopen 加载 `libavcenc_ohos.z.so` HDI Codec 接口，实现 Surface 输入模式与 AVBuffer 两种输入模式，继承 CodecBase 九态机，与 S236(HCodec DFX)/S239(CodecBase)/S229(原生AudioCodec)构成 OHOS Codec 硬件编解码完整体系。

---

## 源码证据（E1-E20 行号级）

### E1 - AvcEncoder 类定义与继承关系（L51-53 avc_encoder.h）
```cpp
class AvcEncoder : public CodecBase, public RefBase {
public:
    explicit AvcEncoder(const std::string &name);
    ~AvcEncoder() override;
    int32_t Configure(const Format &format) override;
    int32_t Start() override;
    int32_t Stop() override;
    ...
    sptr<Surface> CreateInputSurface() override;  // Surface模式入口
    int32_t SignalRequestIDRFrame() override;       // IDR帧请求
    static int32_t GetCodecCapability(std::vector<CapabilityData> &capaArray); // 能力查询
```
继承 CodecBase（编码器基类虚接口）+ RefBase（生命周期管理）。与 SurfaceEncoderAdapter（S214）的 Filter 层封装形成对比：AvcEncoder 是 Engine 层直接封装，SurfaceEncoderAdapter 是 Filter 层适配器。

### E2 - HDI dlopen 三函数指针（L83-86 avc_encoder.cpp）
```cpp
const char *AVC_ENC_LIB_PATH = "libavcenc_ohos.z.so";
const char *AVC_ENC_CREATE_FUNC_NAME = "InitEncoder";
const char *AVC_ENC_ENCODE_FRAME_FUNC_NAME = "EncodeProcess";
const char *AVC_ENC_DELETE_FUNC_NAME = "ReleaseEncoder";
```
HDI Codec 三段式 API：InitEncoder（创建编码器实例）→ EncodeProcess（编码一帧）→ ReleaseEncoder（释放实例）。dlopen 延迟加载（RTLD_LAZY），在 AvcFuncMatch() 中初始化。

### E3 - HDI 函数指针类型定义（L37-40 avc_encoder.h）
```cpp
using CreateAvcEncoderFuncType = uint32_t (*)(AVC_ENC_HANDLE *phEncoder, AVC_ENC_INIT_PARAM *pstInitParam);
using EncodeFuncType = uint32_t (*)(AVC_ENC_HANDLE hEncoder, AVC_ENC_INARGS *pstInArgs, AVC_ENC_OUTARGS *pstOutArgs);
using DeleteFuncType = uint32_t (*)(AVC_ENC_HANDLE hEncoder);
```
HDI 接口三函数签名。AVC_ENC_HANDLE 是编码器实例句柄（类似 OMX_HANDLETYPE）。AVC_ENC_INIT_PARAM 包含编码参数（profile/level/bitrate/QP等），AVC_ENC_INARGS/OUTARGS 为编码输入输出参数。

### E4 - 编码器实例句柄与函数指针成员（L219-225 avc_encoder.h）
```cpp
AVC_ENC_HANDLE avcEncoder_ = nullptr;
CreateAvcEncoderFuncType avcEncoderCreateFunc_ = nullptr;
EncodeFuncType avcEncoderFrameFunc_ = nullptr;
DeleteFuncType avcEncoderDeleteFunc_ = nullptr;
AVC_ENC_INIT_PARAM initParams_;
AVC_ENC_INARGS avcEncInputArgs_;
AVC_ENC_OUTARGS avcEncOutputArgs_;
```
avcEncoder_ 为编码器实例句柄。initParams_ 在 Configure 阶段填充（E13），avcEncInputArgs_/avcEncOutputArgs_ 在每帧编码时复用（E16-E18）。

### E5 - AvcFuncMatch 动态库加载与函数解析（L186-203 avc_encoder.cpp）
```cpp
void AvcEncoder::AvcFuncMatch()
{
    handle_ = dlopen(AVC_ENC_LIB_PATH, RTLD_LAZY);
    if (handle_ != nullptr) {
        avcEncoderCreateFunc_ = reinterpret_cast<CreateAvcEncoderFuncType>(
            dlsym(handle_, AVC_ENC_CREATE_FUNC_NAME));
        avcEncoderFrameFunc_ = reinterpret_cast<EncodeFuncType>(
            dlsym(handle_, AVC_ENC_ENCODE_FRAME_FUNC_NAME));
        avcEncoderDeleteFunc_ = reinterpret_cast<DeleteFuncType>(
            dlsym(handle_, AVC_ENC_DELETE_FUNC_NAME));
        ...
    }
}
```
AvcFuncMatch() 在 Initialize() 中被调用（L158），延迟加载 libavcenc_ohos.z.so 并解析三函数指针。与 Hcodec(S236) 的 DFX FuncTracker 形成对比：FuncTracker 是 DFX RAII 追踪层，AvcFuncMatch 是真正的 HDI 加载层。

### E6 - CodecBase 九态机状态枚举（L196-206 avc_encoder.h）
```cpp
enum struct State : int32_t {
    UNINITIALIZED,  // 0：创建后未初始化
    INITIALIZED,    // 1：已初始化（库加载成功）
    CONFIGURED,     // 2：已配置参数
    STOPPING,       // 3：正在停止
    RUNNING,        // 4：运行中（编码进行）
    FLUSHED,        // 5：已刷新（缓冲区清空）
    FLUSHING,       // 6：正在刷新
    EOS,            // 7：输入结束
    ERROR,          // 8：错误
};
std::atomic<State> state_ = State::UNINITIALIZED;
```
CodecBase 九态机（对比 S239 CodecBase 七态机，S228 HevcDecoder 有自己的状态机）。UNINITIALIZED→INITIALIZED（Initialize）→CONFIGURED（Configure）→RUNNING（Start）→EOS/ERROR。FLUSHING/FLUSHED 用于 Flush 操作。std::atomic<State> 保证线程安全的状态切换。

### E7 - Surface 输入模式：CreateInputSurface 创建生产者 Surface（L315-352 avc_encoder.cpp）
```cpp
sptr<Surface> AvcEncoder::CreateInputSurface()
{
    sptr<Surface> consumerSurface = Surface::CreateSurfaceAsConsumer("HEncoderSurface");
    GSError err = consumerSurface->SetDefaultUsage(SURFACE_MODE_CONSUMER_USAGE);
    // SURFACE_MODE_CONSUMER_USAGE = BUFFER_USAGE_MEM_DMA | BUFFER_USAGE_CPU_READ | BUFFER_USAGE_MEM_MMZ_CACHE
    sptr<IBufferProducer> producer = consumerSurface->GetProducer();
    sptr<Surface> producerSurface = Surface::CreateSurfaceAsProducer(producer);
    inputSurface_ = consumerSurface;
    if (DEFAULT_IN_BUFFER_CNT > inputSurface_->GetQueueSize()) {
        inputSurface_->SetQueueSize(DEFAULT_IN_BUFFER_CNT); // 4
    }
    return producerSurface; // 返回给上游（SurfaceEncoderAdapter 或 App）
}
```
Surface 模式输入：创建名为 "HEncoderSurface" 的 Surface 对（Consumer+Producer），设置 DMA 内存用途，返回 Producer Surface 给调用方。上游通过 ProduceSurface 写入数据，AvcEncoder 通过 ConsumerSurface 消费（E9）。与 SurfaceEncoderAdapter（S214）的 Surface 模式相同架构。

### E8 - Surface 消费监听器：EncoderBuffersConsumerListener 驱动 SendFrame（L308-313 avc_encoder.cpp + L233-237 avc_encoder.h）
```cpp
// avc_encoder.cpp
void AvcEncoder::EncoderBuffersConsumerListener::OnBufferAvailable()
{
    codec_->GetBufferFromSurface();  // 从 Surface 取一帧
    if (inputAvailQue_) {
        inputAvailQue_->Push(index);  // 入队列等待 SendFrame 处理
    }
}

// avc_encoder.h
class EncoderBuffersConsumerListener : public IBufferConsumerListener {
public:
    explicit EncoderBuffersConsumerListener(AvcEncoder *codec) : codec_(codec) {}
    void OnBufferAvailable() override;
private:
    AvcEncoder *codec_ = nullptr;
};
```
当 Surface 有新Buffer可用时（上游 Produce），OnBufferAvailable 被 Surface 框架回调，触发 GetBufferFromSurface 取帧并压入 inputAvailQue_ 队列，唤醒 SendFrame 线程处理。

### E9 - GetBufferFromSurface：从 Surface AcquireBuffer 取帧（L263-306 avc_encoder.cpp）
```cpp
void AvcEncoder::GetBufferFromSurface()
{
    CHECK_AND_RETURN_LOG(inputSurface_ != nullptr, "inputSurface_ not exists");
    if (inputSurface_ == nullptr) {
        return;
    }
    sptr<SurfaceBuffer> buffer = nullptr;
    GSError ret = inputSurface_->AcquireBuffer(buffer, fence, pts, damage);
    if (ret != GSERROR_OK) {
        ReleaseSurfaceBuffer();  // 取失败则释放
        return;
    }
    if (buffer == nullptr) {
        ReleaseSurfaceBuffer();
        return;
    }
    // Fence 等待（同步等待 GPU 完成）
    if (fence != nullptr) {
        fence->Wait(waitForEver);  // waitForEver = -1（无限等待）
    }
    uint32_t index = index;  // buffer 索引
    inputAvailQue_->Push(index);  // 入队列
}
```
AcquireBuffer 从 Surface 取到 SurfaceBuffer（含图像数据+Fence同步），Fence 等待确保 GPU 操作完成后再编码。

### E10 - SendFrame 线程驱动：TaskThread + BlockQueue 队列（L395-396 + L1601-1655 avc_encoder.cpp）
```cpp
// Initialize 中创建发送线程
sendTask_ = std::make_shared<TaskThread>("SendFrame");
sendTask_->RegisterHandler([this] { SendFrame(); });

// SendFrame 核心流程
void AvcEncoder::SendFrame()
{
    SCOPED_TRACE_AVC("SendFrame");
    CHECK_AND_RETURN_LOG(state_ != State::STOPPING && state_ != State::FLUSHING, "Invalid state");
    if (state_ != State::RUNNING || isSendEos_) {
        std::this_thread::sleep_for(std::chrono::milliseconds(DEFAULT_TRY_ENCODE_TIME));
        return;
    }
    uint32_t index = inputAvailQue_->Front();  // 阻塞等待
    std::shared_ptr<FBuffer> &inputBuffer = buffers_[INDEX_INPUT][index];
    std::shared_ptr<AVBuffer> inputAVBuffer = GetAvBuffer(inputBuffer);
    // 处理 EOS 帧
    if (inputAVBuffer->flag_ & AVCODEC_BUFFER_FLAG_EOS) { ... state_ = State::EOS; }
    // Fence 等待
    sptr<SyncFence> fence = inputBuffer->fence_;
    if (fence != nullptr) { fence->Wait(waitForEver); }
    // 填充编码参数
    ret = FillAvcEncoderInArgs(inputAVBuffer, avcEncInputArgs_);
    // 首帧编码前插入 SPS/PPS
    if (isFirstFrame_) { EncoderAvcHeader(); isFirstFrame_ = false; }
    // 调用 HDI 编码
    ret = EncoderAvcFrame(avcEncInputArgs_, avcEncOutputArgs_);
    if (ret == AVCS_ERR_OK) {
        inputBuffer->owner_ = FBuffer::Owner::OWNED_BY_USER;
        inputAvailQue_->Pop();
        NotifyUserToFillBuffer(index, inputAVBuffer);  // 归还输入Buffer
    } else { state_ = State::ERROR; }
}
```
SendFrame 是编码器核心工作线程：TaskThread("SendFrame") 驱动 + BlockQueue(inputAvailQue_) 流量控制 + HDI EncodeProcess 调用 + Fence 同步。DEFAULT_TRY_ENCODE_TIME = 100ms（等待间隔）。与 AudioCodecWorker（S235）的双 TaskThread 架构对称。

### E11 - EncoderAvcFrame HDI 编码调用（L1655-1680 avc_encoder.cpp）
```cpp
int32_t AvcEncoder::EncoderAvcFrame(AVC_ENC_INARGS &inArgs, AVC_ENC_OUTARGS &outArgs)
{
    if (avcEncoderFrameFunc_ == nullptr) {
        AVCODEC_LOGE("avcEncoderFrameFunc_ is null");
        return AVCS_ERR_UNKNOWN;
    }
    uint32_t ret = avcEncoderFrameFunc_(avcEncoder_, &inArgs, &outArgs);
    if (ret != AVCS_ERR_OK) {
        AVCODEC_LOGE("EncodeFrame failed: %{public}d", ret);
        return ret;
    }
    FillEncodedBuffer(frameBuffer);  // 处理编码输出
    return AVCS_ERR_OK;
}
```
EncoderAvcFrame 是 HDI EncodeProcess 的封装。三函数指针（avcEncoderCreateFunc_/avcEncoderFrameFunc_/avcEncoderDeleteFunc_）在 Initialize 阶段通过 AvcFuncMatch() 初始化。

### E12 - EncoderAvcHeader：首帧前插入 SPS/PPS（L864-900 avc_encoder.cpp）
```cpp
void AvcEncoder::EncoderAvcHeader()
{
    AVC_ENC_INARGS headerInArgs = {};
    AVC_ENC_OUTARGS headerOutArgs = {};
    headerInArgs.isIFrame = true;
    headerInArgs.forceIFrame = true;
    // 调用 HDI 获取 SPS/PPS
    avcEncoderFrameFunc_(avcEncoder_, &headerInArgs, &headerOutArgs);
    // 将 headerOutArgs 中的 SPS/PPS 数据复制到输出 Buffer
    ...
}
```
首帧编码前强制插入 I 帧（H.264 SPS+PPS Sequence Parameter Set + Picture Parameter Set）。forceIFrame=true 触发 HDI 返回 Codec 配置信息。H.264 码流必须以 SPS→PPS→IDR 开头。

### E13 - ConfigureDefaultVal 配置默认参数（L403-415 + L136-143 avc_encoder.cpp）
```cpp
// avc_encoder.cpp L136-143 成员初始化默认值
encBitrate_(DEFAULT_VIDEO_BITRATE),     // 6000000 (6Mbps)
encQp_(VIDEO_QP_DEFAULT),               // 20
encQpMax_(VIDEO_QP_MAX),               // 51
encQpMin_(VIDEO_QP_MIN),               // 4
// L403-415 Configure 入口
int32_t AvcEncoder::Configure(const Format &format)
{
    int32_t ret = ConfigureContext(format);  // L466
    ...
}
// L864-900 FillAvcInitParams 填充 HDI 参数
void AvcEncoder::FillAvcInitParams(AVC_ENC_INIT_PARAM &param)
{
    param.level = static_cast<uint32_t>(TranslateEncLevel(avcLevel_));
    param.profile = static_cast<uint32_t>(TranslateEncProfile(avcProfile_));
    param.bitrate = static_cast<uint32_t>(encBitrate_);
    param.qp = static_cast<uint32_t>(encQp_);
    ...
}
```
Configure 阶段从 Format 中提取用户参数（E14 详述），FillAvcInitParams 将内存成员变量（H.264 Level/Profile/bitrate/QP）翻译为 HDI 参数。HDI 参数通过 InitEncoder 传给硬件编码器。

### E14 - ConfigureContext 关键参数提取（L466-612 avc_encoder.cpp）
```cpp
GetBitRateFromUser(format);       // L498-516: 从 VIDEO_BITRATE 提取 encBitrate_
GetBitRateModeFromUser(format);   // L551-580: CQ/CBR/VBR 模式 + quality→QP 推导
GetFrameRateFromUser(format);     // L531-549: 从 VIDEO_FRAME_RATE 提取 encFrameRate_
GetIFrameIntervalTimeSupport(interval); // L582-602: I帧间隔
GetColorAspects(format);          // L603-633: ColorPrimary/Transfer/Matrix
CheckBitRateSupport(bitrate);    // L644-653: 范围校验
CheckFrameRateSupport(framerate); // L654-663: 范围校验
// L486-497 QP 范围
if (!format.GetIntValue(OHOS::Media::Tag::VIDEO_ENCODER_QP_MIN, minQp) ||
    !format.GetIntValue(OHOS::Media::Tag::VIDEO_ENCODER_QP_MAX, maxQp)) {
    encQpMax_ = VIDEO_QP_MAX; encQpMin_ = VIDEO_QP_MIN; }
```
ConfigureContext 从 Format（键值对）提取 7 类参数：BitRate、BitrateMode、FrameRate、IFrameInterval、QP范围、Profile/Level、ColorAspects。与 VideoCodecParamChecker（S224）的参数校验形成互补：S224 校验配置的合法性，AvcEncoder 提取配置值。

### E15 - 编码器能力：VIDEO_INSTANCE_SIZE=16 + 分辨率/帧率/码率范围（L52-78 avc_encoder.cpp）
```cpp
constexpr int32_t VIDEO_INSTANCE_SIZE = 16;           // 最多16个并发实例
constexpr int32_t VIDEO_MAX_WIDTH_SIZE = 2560;
constexpr int32_t VIDEO_MAX_HEIGHT_SIZE = 2560;
constexpr int32_t DEFAULT_VIDEO_WIDTH = 1920;
constexpr int32_t DEFAULT_VIDEO_HEIGHT = 1080;
constexpr int32_t VIDEO_BITRATE_MIN_SIZE = 10000;     // 10kbps
constexpr int32_t VIDEO_BITRATE_MAX_SIZE = 30000000;   // 30Mbps
constexpr int32_t VIDEO_FRAMERATE_MIN_SIZE = 1;
constexpr int32_t VIDEO_FRAMERATE_MAX_SIZE = 60;       // 60fps
constexpr int32_t VIDEO_QP_MAX = 51;
constexpr int32_t VIDEO_QP_MIN = 4;
constexpr int32_t VIDEO_QP_DEFAULT = 20;
constexpr int32_t DEFAULT_VIDEO_BITRATE = 6000000;     // 6Mbps
constexpr double DEFAULT_VIDEO_FRAMERATE = 30.0;
constexpr int32_t DEFAULT_VIDEO_IFRAME_INTERVAL = 60; // 60帧 = 2秒@30fps
constexpr int32_t VIDEO_ALIGN_SIZE = 16;               // 16像素对齐
```
硬件编码器能力约束：16实例上限，2560×2560最大分辨率，1-60fps，10k-30Mbps，QP 4-51。与软解（VpxDecoder S231/S232）的 64实例池化形成对比，硬件编码器实例更稀缺。

### E16 - SignalRequestIDRFrame 强制 IDR 帧请求（L699-705 avc_encoder.cpp）
```cpp
int32_t AvcEncoder::SignalRequestIDRFrame()
{
    if (state_ != State::RUNNING) {
        return AVCS_ERR_INVALID_STATE;
    }
    std::shared_lock<std::shared_mutex> lock(encMutex_);
    encIdrRequest_ = true;  // 标记 IDR 请求
    avcEncInputArgs_.forceIFrame = true;  // 下一帧强制 I 帧
    return AVCS_ERR_OK;
}
```
encIdrRequest_ 原子标志 + forceIFrame HDI 参数双重机制。调用方（App/SurfaceEncoderAdapter）可在运行期请求 IDR 帧（SAR/分辨率变化时特别重要）。

### E17 - ReleaseHandle 释放编码器句柄与动态库（L204-215 avc_encoder.cpp）
```cpp
void AvcEncoder::ReleaseHandle()
{
    if (avcEncoder_ != nullptr && avcEncoderDeleteFunc_ != nullptr) {
        avcEncoderDeleteFunc_(avcEncoder_);  // 调用 HDI ReleaseEncoder
        avcEncoder_ = nullptr;
    }
    if (handle_ != nullptr) {
        dlclose(handle_);  // 关闭动态库
        handle_ = nullptr;
    }
    avcEncoderCreateFunc_ = nullptr;
    avcEncoderFrameFunc_ = nullptr;
    avcEncoderDeleteFunc_ = nullptr;
}
```
ReleaseHandle 在 Release() / ~AvcEncoder / 错误处理时被调用。dlclose 释放 libavcenc_ohos.z.so。与 AvcFuncMatch（E5）形成加载/释放对称生命周期。

### E18 - Buffer 管理体系：FBuffer 封装 + 双 BlockQueue（L93-98 + L817-820 avc_encoder.h + avc_encoder.cpp）
```cpp
// FBuffer 封装 AVBuffer + SurfaceBuffer + Fence + Owner 状态
class FBuffer {
public:
    std::shared_ptr<AVBuffer> avBuffer_ = nullptr;
    sptr<SurfaceBuffer> surfaceBuffer_ = nullptr;
    sptr<SyncFence> fence_ = nullptr;
    std::atomic<Owner> owner_ = Owner::OWNED_BY_US;  // OWNED_BY_US/CODEC/USER/SURFACE
    int32_t width_ = 0; int32_t height_ = 0;
};

// 缓冲区初始化
inputAvailQue_ = std::make_shared<BlockQueue<uint32_t>>("inputAvailQue", inputBufferCnt); // L817
codecAvailQue_ = std::make_shared<BlockQueue<uint32_t>>("codecAvailQue", outBufferCnt);   // L818
```
FBuffer.Owner 四态机（US→CODEC→USER→SURFACE→US）管理 Buffer 所有权流转。inputAvailQue_ 是输入 Buffer 的就绪队列，codecAvailQue_ 是编码完成输出 Buffer 的就绪队列。BlockQueue 是线程安全的无锁/有锁队列（E10 SendFrame 从 inputAvailQue_.Front() 阻塞取帧）。

### E19 - Format 转换：FillAvcEncoderInArgs + Yuv420To/Nv12To/RgbaTo 格式转换（L1287-1315 + avc_encoder_convert.cpp）
```cpp
// avc_encoder.cpp L1287 填充编码参数
int32_t AvcEncoder::FillAvcEncoderInArgs(std::shared_ptr<AVBuffer> &buffer, AVC_ENC_INARGS &inArgs)
{
    InputFrame inFrame;
    GetInputFrameFromAVBuffer(buffer, inFrame);  // 从 AVBuffer 提取帧信息
    VideoPixelFormat fmt = srcPixelFmt_;
    if (fmt == VideoPixelFormat::NV12) {
        Nv12ToAvcEncoderInArgs(inFrame, inArgs);  // NV12 YUV 格式转换
    } else if (fmt == VideoPixelFormat::NV21) {
        Nv21ToAvcEncoderInArgs(inFrame, inArgs);
    } else if (fmt == VideoPixelFormat::RGBA) {
        RgbaToAvcEncoderInArgs(inFrame, inArgs);  // RGBA→YUV420 转换
    } else {
        Yuv420ToAvcEncoderInArgs(inFrame, inArgs);  // YUV420 planar
    }
    inArgs.pts = GetBufferPts(buffer);  // 时间戳
    inArgs.isIFrame = encIdrRequest_;    // IDR 帧标志
    encIdrRequest_ = false;
}
```
FillAvcEncoderInArgs 是格式适配层：支持 NV12/NV21（移动设备 Camera 默认格式）、RGBA（渲染场景）、YUV420（标准格式）四种像素格式，自动选择对应的格式转换函数。avc_encoder_convert.cpp（369行）实现格式转换逻辑。

### E20 - GetCodecCapability 静态能力查询（L1660-1765 avc_encoder.cpp）
```cpp
int32_t AvcEncoder::GetCodecCapability(std::vector<CapabilityData> &capaArray)
{
    // L1739-1744 Profile/Level 组合构建
    capsData.profileLevelsMap.insert(std::make_pair(static_cast<int32_t>(AVC_PROFILE_BASELINE), levels));
    capsData.profileLevelsMap.insert(std::make_pair(static_cast<int32_t>(AVC_PROFILE_MAIN), levels));
    capsData.profileLevelsMap.insert(std::make_pair(static_cast<int32_t>(AVC_PROFILE_HIGH), levels));
    // 返回 CodecList（OH_AVCodec_GetCodecList）可查询的能力
    // 支持的 Profile: BASELINE(0x01)/MAIN(0x02)/HIGH(0x08)
    // 支持的 Level: 1~6.2 (10/11/12/13/20/21/22/30/31/32/40/41/42/50/51/52/60/61/62)
}
```
GetCodecCapability 是 AVCodecList 工厂查询能力的入口（与 S171 CodecCapabilityAdapter 的能力查询互补）。只支持 AVC（H.264），不支持 HEVC（由 HevcEncoder 单独处理，S228）。

---

## 架构总结

### AvcEncoder 在 AVCodec 体系中的位置

```
OH_AVCodec API (interfaces/)
    ↓
CodecBase (services/engine/common/)
    ├── AvcEncoder (H.264 HW Encoder) ← S242 本主题
    ├── HevcEncoder (HEVC HW Encoder)
    ├── VpxDecoder (VP8/VP9 SW Decoder) ← S231
    ├── Av1Decoder (AV1 SW Decoder) ← S232
    └── AudioCodec (Audio HW/SW Codec) ← S229/S235
            ↓
    libavcenc_ohos.z.so (HDI Codec SO, dlopen加载)
            ↓
    硬件 AVC 编码器 (H.264 HW Encoder ASIC)
```

### AvcEncoder vs S214 SurfaceEncoderAdapter vs S228 HevcDecoder

| 维度 | AvcEncoder（S242） | SurfaceEncoderAdapter（S214） | HevcDecoder（S228） |
|------|-------------------|-------------------------------|---------------------|
| 类型 | Hardware Encoder | Filter 适配器（封装 HW） | Hardware Decoder |
| Codec | AVC (H.264) only | AVCodecVideoEncoder 封装 | HEVC (H.265) |
| 架构层 | Engine 层直接封装 | Filter 层适配器 | Engine 层直接封装 |
| 输入模式 | Surface + AVBuffer | Surface | Surface |
| 态机 | CodecBase 9态机 | ProcessStateCode 5态机 | 自有态机 |
| 实例上限 | 16 | 无限制（Surface模式） | 64（InstancePool） |
| 驱动线程 | TaskThread SendFrame | pauseResumeQueue 暂停恢复 | SendFrame 1ms 轮询 |

### AvcEncoder 编码管线（Surface 模式）

```
上游（Camera/Filter）
    ↓ ProduceSurface (yuv数据)
SurfaceBuffer (ProducerSurface)
    ↓
Surface::AcquireBuffer (ConsumerSurface被AvcEncoder持有)
    ↓
EncoderBuffersConsumerListener::OnBufferAvailable()
    ↓ Push index → inputAvailQue_
SendFrame() [TaskThread 驱动]
    ↓ Front() inputAvailQue_
FBuffer[index] (含 AVBuffer + SurfaceBuffer + Fence)
    ↓ FillAvcEncoderInArgs (NV12/RGBA/YUV420 格式转换)
    ↓ isFirstFrame_ ? EncoderAvcHeader() : (NOP) [SPS/PPS 注入]
    ↓ EncoderAvcFrame → avcEncoderFrameFunc_(EncodeProcess HDI)
HDI libavcenc_ohos.z.so → 硬件 ASIC
    ↓
avcEncOutputArgs_ (H.264 NALU 码流)
    ↓ FillEncodedBuffer → codecAvailQue_
回调 OnOutputBufferAvailable → App
    ↓ ReleaseOutputBuffer
```

---

## 关联记忆

- **S183**: AvcEncoder 软件编码器（FFmpeg 实现，对比本主题的硬件实现）
- **S229**: Native Audio Codec 插件体系（FFmpeg/G711mu/Opus 三层路径，与 AvcEncoder 平级的 Engine 层 Codec）
- **S236**: HCodec DFX Module（HCodec 硬件编解码 DFX 追踪，与 AvcEncoder 同属 Hardware Codec）
- **S239**: CodecBase Engine 架构（CodecBase 基类+Loader+Factory，AvcEncoder 继承 CodecBase）
- **S214**: SurfaceEncoderAdapter（Filter 层编码适配器，封装 AvcEncoder 的 Surface 模式）
- **S228**: HevcDecoder（HEVC 硬件解码器，与 AvcEncoder 构成编码/解码对称）
- **S231**: VpxDecoder（VP8/VP9 软件解码器，与 AvcEncoder 对比软硬架构）
