---
type: architecture
id: MEM-ARCH-AVCODEC-S53
title: "FCodec 软件视频解码器——H.264/AVC FFmpeg 解码管线"
scope: [AVCodec, VideoDecoder, FCodec, FFmpeg, SoftwareCodec, libavcodec, avcodec_send_packet, avcodec_receive_frame, H264, AVC, DecoderPipeline, BlockQueue]
status: approved
approved_at: "2026-05-06"
created_by: builder-agent
created_at: "2026-04-26T17:40:00+08:00"
evidence_count: 15
关联主题: [S39(AVCodecVideoDecoder整体架构), S42(AVCodecVideoEncoder整体架构), S51(Av1Decoder软件解码器), S47(CodecCapability能力体系)]
---

# MEM-ARCH-AVCODEC-S53: FCodec 软件视频解码器——H.264/AVC FFmpeg 解码管线

## Metadata

| 字段 | 值 |
|------|-----|
| **ID** | MEM-ARCH-AVCODEC-S53 |
| **标题** | FCodec 软件视频解码器——H.264/AVC FFmpeg 解码管线 |
| **Scope** | AVCodec, VideoDecoder, FCodec, FFmpeg, SoftwareCodec, libavcodec, H264, AVC |
| **Status** | draft |
| **Created** | 2026-04-26T17:40:00+08:00 |
| **Evidence Count** | 15 |
| **关联主题** | S39(AVCodecVideoDecoder), S42(VideoEncoder), S51(Av1Decoder), S47(CodecCapability) |

---

## 1. 架构总览

FCodec（Flexible Codec）是 OpenHarmony AVCodec 体系中**纯软件视频解码器**的实现类，基于 FFmpeg libavcodec 实现。它通过统一的 FCodec 类支持多种软件解码格式，包括 H.264/AVC、MPEG-2、MPEG-4、H.263、MJPEG、WMV3、VC-1 等。

**重要区别**：与 S51（Av1Decoder）拥有独立类目录不同，H.264 解码**没有独立的 `h264decoder` 目录**，而是复用 FCodec 类，通过 FFmpeg 的 `avcodec_find_decoder_by_name("h264")` 动态创建具体解码器。

```
FCodec 类继承关系：
CodecBase (基类，生命周期管理)
    └── FCodec (软件解码器统一封装)
            ├── avcodec_find_decoder_by_name("h264") → FFmpeg h264 解码器
            ├── avcodec_open2() → 打开解码器
            ├── avcodec_send_packet() / avcodec_receive_frame() → 解码管线
            └── 14种软件解码格式统一支持
```

---

## 2. 关键源文件索引

| 文件路径 | 内容 |
|---------|------|
| `services/engine/codec/video/fcodec/fcodec.cpp` | FCodec 主实现，SendFrame/ReceiveFrame 解码循环 |
| `services/engine/codec/video/fcodec/include/fcodec.h` | FCodec 类定义，State 枚举，Buffer 管理 |
| `services/engine/codec/video/fcodec/fcodec_capability_register.cpp` | GetAvcCapProf() H.264 能力注册 |
| `services/engine/codec/video/fcodec/include/fcodec_surport_codec.h` | SUPPORT_VCODEC 数组，codecName/mimeType/FFmpeg 名称映射 |
| `services/engine/codec/include/video/avcodec_codec_name.h` | AVCodecCodecName 枚举（codec 名称常量） |
| `interfaces/inner_api/native/avcodec_info.h` | CapabilityData, AVCProfile, AVCLevel 枚举 |

---

## 3. 支持的解码格式（SUPPORT_VCODEC 数组）

`fcodec_surport_codec.h` 定义了 FCodec 支持的所有软件解码格式：

```cpp
constexpr CodecInfo SUPPORT_VCODEC[] = {
    {AVCodecCodecName::VIDEO_DECODER_AVC_NAME,      CodecMimeType::VIDEO_AVC,      "h264"},       // H.264/AVC
    {AVCodecCodecName::VIDEO_DECODER_H263_NAME,      CodecMimeType::VIDEO_H263,     "h263"},       // H.263
    {AVCodecCodecName::VIDEO_DECODER_MPEG2_NAME,      CodecMimeType::VIDEO_MPEG2,    "mpeg2video"}, // MPEG-2
    {AVCodecCodecName::VIDEO_DECODER_MPEG4_NAME,     CodecMimeType::VIDEO_MPEG4,    "mpeg4"},      // MPEG-4
    {AVCodecCodecName::VIDEO_DECODER_MPEG1_NAME,     CodecMimeType::VIDEO_MPEG1,    "mpeg1video"}, // MPEG-1
#ifdef SUPPORT_CODEC_VC1
    {AVCodecCodecName::VIDEO_DECODER_VC1_NAME,        CodecMimeType::VIDEO_VC1,      "vc1"},
    {AVCodecCodecName::VIDEO_DECODER_WVC1_NAME,      CodecMimeType::VIDEO_WVC1,     "vc1"},
#endif
    {AVCodecCodecName::VIDEO_DECODER_MSVIDEO1_NAME,  CodecMimeType::VIDEO_MSVIDEO1, "msvideo1"},
    {AVCodecCodecName::VIDEO_DECODER_WMV3_NAME,      CodecMimeType::VIDEO_WMV3,    "wmv3"},
    {AVCodecCodecName::VIDEO_DECODER_MJPEG_NAME,     CodecMimeType::VIDEO_MJPEG,   "mjpeg"},
    {AVCodecCodecName::VIDEO_DECODER_DVVIDEO_NAME,   CodecMimeType::VIDEO_DVVIDEO,  "dvvideo"},
    {AVCodecCodecName::VIDEO_DECODER_RAWVIDEO_NAME,  CodecMimeType::VIDEO_RAWVIDEO, "rawvideo"},
    {AVCodecCodecName::VIDEO_DECODER_CINEPAK_NAME,   CodecMimeType::VIDEO_CINEPAK, "cinepak"},
#ifdef SUPPORT_CODEC_RV
    {AVCodecCodecName::VIDEO_DECODER_RV30_NAME,       CodecMimeType::VIDEO_RV30,     "rv30"},
    {AVCodecCodecName::VIDEO_DECODER_RV40_NAME,      CodecMimeType::VIDEO_RV40,    "rv40"},
#endif
};
```

**FFmpeg codec name 映射**：H.264 对应 FFmpeg 内部 `"h264"` codec（libavcodec 的 h264dec.c 实现）。

---

## 4. H.264 能力注册（GetAvcCapProf）

`fcodec_capability_register.cpp` 中 GetAvcCapProf() 填充 H.264 专有能力：

```cpp
void GetAvcCapProf(std::vector<CapabilityData> &capaArray)
{
    if (!capaArray.empty()) {
        CapabilityData& capsData = capaArray.back();
        capsData.width.maxVal  = AVC_MAX_WIDTH_SIZE;      // 5120
        capsData.height.maxVal = AVC_MAX_HEIGHT_SIZE;     // 5120
        capsData.supportSwapWidthHeight = true;            // 支持宽高交换
        capsData.frameRate.maxVal = AVC_VIDEO_FRAMERATE_MAX_SIZE;  // 120 fps
        capsData.blockPerFrame.maxVal = AVC_VIDEO_BLOCKPERFRAME_SIZE;  // 139264
        capsData.blockPerSecond.maxVal = AVC_VIDEO_BLOCKPERSEC_SIZE;   // 16711680

        // H.264 Profile：Baseline / Main / High
        capsData.profiles = {
            static_cast<int32_t>(AVC_PROFILE_BASELINE),
            static_cast<int32_t>(AVC_PROFILE_MAIN),
            static_cast<int32_t>(AVC_PROFILE_HIGH)
        };

        // H.264 Level：0~62（全部20个级别）
        std::vector<int32_t> levels;
        for (int32_t j = 0; j <= static_cast<int32_t>(AVCLevel::AVC_LEVEL_62); ++j) {
            levels.emplace_back(j);
        }
        capsData.profileLevelsMap.insert(std::make_pair(AVC_PROFILE_MAIN,     levels));
        capsData.profileLevelsMap.insert(std::make_pair(AVC_PROFILE_HIGH,     levels));
        capsData.profileLevelsMap.insert(std::make_pair(AVC_PROFILE_BASELINE, levels));
    }
}
```

**H.264 分辨率范围**（GetResolutionRange）：
```cpp
if (codecName == AVCodecCodecName::VIDEO_DECODER_AVC_NAME) {
    range = {2, 5120, 2, 5120}; // H.264/AVC: [2, 5120] x [2, 5120]
}
```

---

## 5. 初始化流程（FCodec::Initialize）

FCodec 通过 FFmpeg 初始化解码器：

```cpp
int32_t FCodec::Initialize()
{
    // 1. 根据 codecName_ 查找 FFmpeg codec
    std::string fcodecName = GetCodecString(codecName_);
    avCodec_ = std::shared_ptr<AVCodec>(
        const_cast<AVCodec *>(avcodec_find_decoder_by_name(fcodecName.c_str())),
        [](AVCodec *p) { });  // 不自动释放，由 FFmpeg 内部管理
    CHECK_AND_RETURN_RET_LOG(avCodec_ != nullptr, AVCS_ERR_INVALID_VAL,
                             "Init codec failed: cannot find codec");

    // 2. 创建解码线程
    sendTask_    = std::make_shared<TaskThread>("SendFrame");
    receiveTask_ = std::make_shared<TaskThread>("ReceiveFrame");
    sendTask_->RegisterHandler([this] { SendFrame(); });
    receiveTask_->RegisterHandler([this] { ReceiveFrame(); });

    return AVCS_ERR_OK;
}
```

**关键 FFmpeg API**（对应 H.264）：
- `avcodec_find_decoder_by_name("h264")` → 查找 FFmpeg H.264 解码器
- `avcodec_alloc_context3(avCodec_.get())` → 分配解码器上下文
- `avcodec_open2(avCodecContext_.get(), avCodec_.get(), nullptr)` → 打开解码器

---

## 6. Configure 流程与 H.264 特殊处理

```cpp
int32_t FCodec::ConfigureContext(const Format &format)
{
    // ... 设置 width_, height_, format_ ...

    avCodecContext_ = std::shared_ptr<AVCodecContext>(
        avcodec_alloc_context3(avCodec_.get()),
        [](AVCodecContext *p) { avcodec_free_context(&p); });

    // Configure extradata（H.264 必需）
    if (codecName_ == AVCodecCodecName::VIDEO_DECODER_AVC_NAME) {
        FreeExtraData();  // 清理旧的 extradata
    }

    return AVCS_ERR_OK;
}
```

---

## 7. 解码循环：SendFrame / ReceiveFrame 双线程

FCodec 使用**双线程驱动解码管线**：

### SendFrame 线程（发送压缩数据包）
```cpp
void FCodec::SendFrame()
{
    if (state_ != State::RUNNING || isSendEos_ || inputAvailQue_->Size() == 0u) {
        std::this_thread::sleep_for(std::chrono::milliseconds(DEFAULT_TRY_DECODE_TIME));
        return;
    }
    uint32_t index = inputAvailQue_->Front();
    std::shared_ptr<AVBuffer> &inputAVBuffer = buffers_[INDEX_INPUT][index]->avBuffer_;

    if (inputAVBuffer->flag_ & AVCODEC_BUFFER_FLAG_Eos) {
        avPacket_->data = nullptr;
        avPacket_->size = 0;
        avPacket_->pts  = 0;
        isSendEos_ = true;
    } else {
        avPacket_->data = inputAVBuffer->memory_->GetAddr();
        avPacket_->size = static_cast<int32_t>(inputAVBuffer->memory_->GetSize());
        avPacket_->pts  = inputAVBuffer->pts_;
    }

    // 核心 FFmpeg API：发送压缩包
    int ret = avcodec_send_packet(avCodecContext_.get(), avPacket_.get());

    if (ret == 0 || ret == AVERROR_INVALIDDATA) {
        recvCv_.notify_one();   // 通知 ReceiveFrame 线程
        inputAvailQue_->Pop();
        callback_->OnInputBufferAvailable(index, inputAVBuffer);
    } else if (ret == AVERROR(EAGAIN)) {
        isSendWait_ = true;     // 需要先 receive 才能继续 send
        sendCv_.wait_for(sendLock, ...);
    } else {
        callback_->OnError(...); // 解码失败
        state_ = State::ERROR;
    }
}
```

### ReceiveFrame 线程（接收解码后原始帧）
```cpp
void FCodec::ReceiveFrame()
{
    if (state_ != State::RUNNING || codecAvailQue_->Size() == 0u) {
        std::this_thread::sleep_for(std::chrono::milliseconds(DEFAULT_TRY_DECODE_TIME));
        return;
    }

    // 核心 FFmpeg API：接收解码帧
    int ret = avcodec_receive_frame(avCodecContext_.get(), cachedFrame_.get());

    if (ret >= 0) {
        // 格式变化检测
        if (CheckFormatChange(index, cachedFrame_->width, cachedFrame_->height) == AVCS_ERR_OK) {
            status = FillFrameBuffer(frameBuffer);  // 像素格式转换
        }
        frameBuffer->avBuffer_->flag_ = AVCODEC_BUFFER_FLAG_NONE;
        callback_->OnOutputBufferAvailable(index, frameBuffer->avBuffer_);
    } else if (ret == AVERROR_EOF) {
        frameBuffer->avBuffer_->flag_ = AVCODEC_BUFFER_FLAG_EOS;
        state_ = State::EOS;
    } else if (ret == AVERROR(EAGAIN)) {
        sendCv_.notify_one();   // 通知 SendFrame 可继续发送
        recvCv_.wait_for(recvLock, ...);
    } else {
        callback_->OnError(...);
        state_ = State::ERROR;
    }
}
```

---

## 8. State 状态机

```cpp
enum struct State : int32_t {
    UNINITIALIZED,  // 初始状态
    INITIALIZED,    // 解码器已初始化（线程已创建）
    CONFIGURED,     // 已配置参数
    STOPPING,       // 正在停止
    RUNNING,        // 运行中
    FLUSHED,        // 已刷新
    FLUSHING,       // 正在刷新
    EOS,            // 流结束
    ERROR,          // 错误状态
    FREEZING,       // 正在冻结
    FROZEN,         // 已冻结
};
```

状态转换：
```
UNINITIALIZED → Init() → INITIALIZED
INITIALIZED   → Configure() → CONFIGURED
CONFIGURED    → Start() → RUNNING
RUNNING       → Flush() → FLUSHED
RUNNING       → Stop() → STOPPING → INITIALIZED
RUNNING       → EOS → EOS
任意状态      → Error → ERROR
```

---

## 9. Buffer 管理：三队列机制

FCodec 继承 CodecBase 的三队列机制（来自 S39 VideoDecoder 架构）：

```cpp
std::shared_ptr<BlockQueue<uint32_t>> inputAvailQue_;   // 可用输入缓冲区队列
std::shared_ptr<BlockQueue<uint32_t>> codecAvailQue_;   // 可用解码输出队列
// （renderAvailQue_ 继承自基类）
```

**FBuffer 结构**（FCodec 私有缓冲区封装）：
```cpp
struct FBuffer {
    std::shared_ptr<AVBuffer>    avBuffer_;     // 解码器 Buffer
    std::shared_ptr<FSurfaceMemory> sMemory_;   // Surface 内存（Surface 模式）
    std::atomic<Owner>           owner_;         // 缓冲区所有权
    int32_t width_  = 0;
    int32_t height_ = 0;
    int32_t format_ = 0;
    uint64_t usage_ = SURFACE_DEFAULT_USAGE;
    std::atomic<bool> hasSwapedOut_ = false;
};

enum class Owner { OWNED_BY_US, OWNED_BY_CODEC, OWNED_BY_USER, OWNED_BY_SURFACE };
```

---

## 10. 与 S51 Av1Decoder 的架构对比

| 维度 | S53 FCodec H.264 | S51 Av1Decoder |
|------|-----------------|----------------|
| **实现方式** | FCodec 统一类 + FFmpeg "h264" | 独立 Av1Decoder 类 + FFmpeg "libdav1d" |
| **源码目录** | `video/fcodec/` | `video/av1decoder/` |
| **FFmpeg API** | `avcodec_send_packet/receive_frame` | `dav1d_send_data/get_picture` |
| **依赖库** | libavcodec.z.so (h264) | libdav1d.z.so |
| **最大实例数** | 64 | 64 |
| **分辨率上限** | 5120×5120 | 1920×1080 |
| **最大帧率** | 120fps | 300fps |
| **Profiles** | Baseline/Main/High | Main/High |
| **Pixel Format** | YUVI420/NV12/NV21/RGBA | I400/I420/I422/I444 |

---

## 11. 与 S39/S42 的架构层级对比

```
S39 VideoDecoder（Filter 引擎层）
    └── VideoDecoderAdapter（S42: VideoEncoder 同级）
            └── VideoDecoder / VideoEncoder（基类）
                    ├── HDecoder / HEncoder（硬件，hcodec 目录）
                    ├── FCodec（H.264 软件解码，video/fcodec 目录）
                    └── Av1Decoder（AV1 软件解码，video/av1decoder 目录）
```

FCodec 处于**软件解码引擎层**，直接调用 FFmpeg libavcodec，是 HDecoder（硬件解码器）的对称实现。

---

## 12. 与其他主题的关联

- **S39 (AVCodecVideoDecoder)**：FCodec 是 VideoDecoder 基类的软件实现之一，对应 S39 的软件解码路径
- **S42 (AVCodecVideoEncoder)**：FCodec 与 avcencoder（H.264 编码器）是同一 codec 目录下的软编码实现；FCodec 解码 vs avcencoder 编码
- **S51 (Av1Decoder)**：对比 FCodec（统一类多格式）和 Av1Decoder（独立类单格式）两种软件解码器架构
- **S47 (CodecCapability)**：FCodec::GetCodecCapability() 注册 H.264 能力（Profile/Level/分辨率范围/帧率上限）
- **S21 (AVCodec IPC)**：FCodec 实例通过 CodecClient IPC 暴露给客户端

---

## 附录：关键 FFmpeg 错误码处理

| FFmpeg ret | 含义 | FCodec 处理 |
|-----------|------|------------|
| `0` | 成功 | 触发 `recvCv_.notify_one()` |
| `AVERROR_INVALIDDATA` | 非法数据（H.264 特有，帧缺失时正常） | `EXPECT_AND_LOGD()` 记录日志，继续处理 |
| `AVERROR(EAGAIN)` | 需要先 receive 才能继续 send | 等待 `sendCv_` 信号 |
| `AVERROR_EOF` | 流结束 | 设置 `BUFFER_FLAG_EOS`，状态切 EOS |

---

## 附录：H.264 Extradata 处理

H.264 需要在 Configure 阶段处理 SPS/PPS extradata：

```cpp
// fcodec.cpp:374 — AVCodecName 判断
if (codecName_ == AVCodecCodecName::VIDEO_DECODER_AVC_NAME) {
    FreeExtraData();  // 清理旧 extradata，为重新 Configure 做准备
}

// Extradata 设置在 ConfigureContext 中：
#if (defined SUPPORT_CODEC_RV) || (defined SUPPORT_CODEC_MP4V_ES) || (defined SUPPORT_CODEC_VC1)
    int32_t SetCodecExtradata(const Format &format);
#endif
// H.264 的 extradata（AVCDecoderConfigurationRecord）通过此路径设置
```
