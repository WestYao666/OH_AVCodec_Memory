---
type: architecture
id: MEM-ARCH-AVCODEC-S54
title: "HevcDecoder + VpxDecoder 视频解码器——HEVC(H.265)/VP8/VP9 解码管线"
scope: [AVCodec, VideoDecoder, HevcDecoder, VpxDecoder, HEVC, H265, VP8, VP9, libhevcdec_ohos, libvpx, HardwareCodec, SoftwareCodec, HDR, VideoCodecLoader]
status: approved
approved_at: "2026-05-06"
created_by: builder-agent
created_at: "2026-04-26T18:06:00+08:00"
evidence_count: 25
关联主题: [S39(AVCodecVideoDecoder整体架构), S51(Av1Decoder软件解码器), S53(FCodec H.264软件解码器), S42(AVCodecVideoEncoder编码器), S47(CodecCapability能力体系)]
---

# MEM-ARCH-AVCODEC-S54: HevcDecoder + VpxDecoder 视频解码器——HEVC(H.265)/VP8/VP9 解码管线

## Metadata

| 字段 | 值 |
|------|-----|
| **ID** | MEM-ARCH-AVCODEC-S54 |
| **标题** | HevcDecoder + VpxDecoder 视频解码器——HEVC(H.265)/VP8/VP9 解码管线 |
| **Scope** | AVCodec, VideoDecoder, HevcDecoder, VpxDecoder, HEVC, H265, VP8, VP9, libhevcdec_ohos, libvpx, HDR |
| **Status** | draft |
| **Created** | 2026-04-26T18:06:00+08:00 |
| **Evidence Count** | 25 |
| **关联主题** | S39(VideoDecoder整体), S51(Av1Decoder), S53(FCodec H.264), S42(VideoEncoder), S47(CodecCapability) |

---

## 1. 架构总览

HevcDecoder 和 VpxDecoder 是 OpenHarmony AVCodec 体系中**两类独立的视频解码器实现**：

- **HevcDecoder**：HEVC/H.265 解码器，加载 vendor 专有库 `libhevcdec_ohos.z.so`，通过 HDI 接口调用硬件/软件混合解码
- **VpxDecoder**：VP8/VP9 解码器，基于 FFmpeg libvpx 库实现软件解码（`vpx_codec_decode` API）

两者均继承 `VideoDecoder` 基类，共享 BlockQueue 三队列、State 状态机、Surface/Buffer 双模式等基础设施。

```
HevcDecoder 类继承：
VideoDecoder (基类，BlockQueue/Surface/Buffer/State 基础设施)
    └── HevcDecoder (HEVC 解码器，libhevcdec_ohos.z.so)

VpxDecoder 类继承：
VideoDecoder (基类)
    └── VpxDecoder (VP8/VP9 解码器，libvpx)
```

---

## 2. 关键源文件索引

### HevcDecoder

| 文件路径 | 内容 |
|---------|------|
| `services/engine/codec/video/hevcdecoder/hevc_decoder.h` | HevcDecoder 类定义，继承 VideoDecoder |
| `services/engine/codec/video/hevcdecoder/hevc_decoder.cpp` | 主实现，SendFrame/DecodeFrameOnce |
| `services/engine/codec/video/hevcdecoder/HevcDec_Typedef.h` | HEVC_DEC_HANDLE/HEVC_DEC_INARGS/HEVC_DEC_OUTARGS HDI 类型定义 |
| `services/engine/codec/video/hevcdecoder/hevc_decoder_api.cpp` | 外部 C 接口：CreateHevcDecoderByName/GetHevcDecoderCapabilityList |
| `services/engine/codec/video/hevc_decoder_loader.cpp` | HevcDecoderLoader 单例，dlopen libhevcdec_ohos.z.so |

### VpxDecoder

| 文件路径 | 内容 |
|---------|------|
| `services/engine/codec/video/vpxdecoder/vpxDecoder.h` | VpxDecoder 类定义，继承 VideoDecoder |
| `services/engine/codec/video/vpxdecoder/vpxDecoder.cpp` | 主实现，SendFrame/DecodeFrameOnce，vpx_codec_decode 调用 |
| `services/engine/codec/video/vpxdecoder/VpxDec_Typedef.h` | VPX_DEC_HANDLE/VpxDecInArgs/vpx_image_t libvpx 类型定义 |
| `services/engine/codec/video/vp9_decoder_loader.cpp` | Vp9DecoderLoader 单例，dlopen libvpx_decoder.z.so |
| `services/engine/codec/video/vp8_decoder_loader.cpp` | (对应 VP8，相同 VpxDecoder 类) |

---

## 3. HevcDecoder 详解

### 3.1 类结构

```cpp
// hevc_decoder.h
class HevcDecoder : public VideoDecoder {
public:
    explicit HevcDecoder(const std::string &name);
    int32_t CreateDecoder() override;   // 调用 HEVC_CreateDecoder
    void DeleteDecoder() override;      // 调用 HEVC_DeleteDecoder
    void SendFrame() override;          // 发送压缩数据到 HEVC 解码器
    int32_t DecodeFrameOnce() override; // 单次解码调用 HEVC_DecodeFrame
    void FlushAllFrames() override;     // 调用 HEVC_FlushFrame
    void FillHdrInfo(...) override;      // HDR 元数据填充
    static int32_t GetCodecCapability(std::vector<CapabilityData> &capaArray);

private:
    void* handle_ = nullptr;  // dlopen(libhevcdec_ohos.z.so) 句柄
    HEVC_DEC_HANDLE hevcSDecoder_ = nullptr;
    CreateHevcDecoderFuncType hevcDecoderCreateFunc_;  // HEVC_CreateDecoder
    DecodeFuncType hevcDecoderDecodecFrameFunc_;       // HEVC_DecodeFrame
    FlushFuncType hevcDecoderFlushFrameFunc_;          // HEVC_FlushFrame
    DeleteFuncType hevcDecoderDeleteFunc_;              // HEVC_DeleteDecoder
    HEVC_DEC_INIT_PARAM initParams_;
    HEVC_DEC_INARGS hevcDecoderInputArgs_;
    HEVC_DEC_OUTARGS hevcDecoderOutpusArgs_;
    HEVC_COLOR_SPACE_INFO colorSpaceInfo_;
};
```

### 3.2 dlopen 加载机制

```cpp
// hevc_decoder.cpp:57 - dlopen vendor library
const char *HEVC_DEC_LIB_PATH = "libhevcdec_ohos.z.so";
handle_ = dlopen(HEVC_DEC_LIB_PATH, RTLD_LAZY);

// HevcFuncMatch() - 解析四个函数符号
hevcDecoderCreateFunc_    = dlsym(handle_, "HEVC_CreateDecoder");
hevcDecoderDecodecFrameFunc_ = dlsym(handle_, "HEVC_DecodeFrame");
hevcDecoderFlushFrameFunc_   = dlsym(handle_, "HEVC_FlushFrame");
hevcDecoderDeleteFunc_       = dlsym(handle_, "HEVC_DeleteDecoder");
```

### 3.3 解码循环（SendFrame + DecodeFrameOnce）

**注意**：HevcDecoder 与 FCodec 的关键区别——**HevcDecoder 只有 SendFrame 线程**（主线程调用 DecodeFrameOnce），而 FCodec 有 SendFrame + ReceiveFrame 双线程。

```cpp
void HevcDecoder::SendFrame()
{
    // 从 inputAvailQue_ 取输入 buffer
    uint32_t index = inputAvailQue_->Front();
    std::shared_ptr<AVBuffer> &inputAVBuffer = inputBuffer->avBuffer;

    if (inputAVBuffer->flag_ & AVCODEC_BUFFER_FLAG_EOS) {
        hevcDecoderInputArgs_.pStream = nullptr;
        isSendEos_ = true;
    } else {
        hevcDecoderInputArgs_.pStream = inputAVBuffer->memory_->GetAddr();
        hevcDecoderInputArgs_.uiStreamLen = static_cast<UINT32>(inputAVBuffer->memory_->GetSize());
        hevcDecoderInputArgs_.uiTimeStamp = static_cast<UINT64>(inputAVBuffer->pts_);
    }

    // 循环解码：同一帧可能需要多次 DecodeFrameOnce（分包场景）
    do {
        ret = DecodeFrameOnce();
        if (!isSendEos_) {
            hevcDecoderInputArgs_.uiStreamLen -= hevcDecoderOutpusArgs_.uiBytsConsumed;
            hevcDecoderInputArgs_.pStream += hevcDecoderOutpusArgs_.uiBytsConsumed;
        }
    } while ((ret != -1) && ((!isSendEos_ && hevcDecoderInputArgs_.uiStreamLen != 0) || ...));
}
```

### 3.4 HEVC HDI 数据结构

```cpp
// HEVC_DEC_INIT_PARAM - 解码器初始化参数
typedef struct TagHevcDecInitParam {
    UINT32 uiChannelID;                      // 通道 ID
    IHW265D_VIDEO_ALG_LOG_FXN logFxn;         // 日志回调
    IHW265_DECODE_MODE uiDecodeMode;          // IHW265_DECODE_VIDEO=0 / IHW265_DECODE_HEIF=1
    UINT32 eOutPutOrder;                     // 0=解码顺序 / 1=显示顺序（默认，低延迟）
} HEVC_DEC_INIT_PARAM;

// HEVC_DEC_INARGS - 输入参数
typedef struct TagHevcDecInArgs {
    UINT8 *pStream;       // 压缩数据地址
    UINT32 uiStreamLen;   // 数据长度
    UINT64 uiTimeStamp;   // PTS（纳秒）
} HEVC_DEC_INARGS;

// HEVC_DEC_OUTARGS - 输出参数
typedef struct TagHevcDecOutArgs {
    UINT32 uiDecWidth;    // 输出宽度
    UINT32 uiDecHeight;   // 输出高度
    UINT32 uiDecStride;   // 步长
    UINT32 uiDecBitDepth; // 8=8bit / 10=10bit
    UINT64 uiTimeStamp;   // PTS
    UINT32 uiBytsConsumed; // 已消费字节数（分包时推进指针）
    UINT8 *pucOutYUV[3];   // YUV 三平面地址
    HEVC_COLOR_SPACE_INFO uiColorSpaceInfo;  // 色彩空间
    HEVC_HDR_METADATA uiHdrMetadata;          // HDR 元数据
} HEVC_DEC_OUTARGS;
```

### 3.5 HEVC 能力注册（GetCodecCapability）

```cpp
// VIDEO_MAX_WIDTH_SIZE = 1920, VIDEO_MAX_HEIGHT_SIZE = 1920
// VIDEO_INSTANCE_SIZE = 64
// Profiles: HEVC_PROFILE_MAIN (8bit) / HEVC_PROFILE_MAIN_10 (10bit)
// Levels: 0~62
// Pixel formats: NV12, NV21, YCBCR_P010, YCRCB_P010 (Surface)
capsData.pixFormat = {NV12, NV21};
capsData.graphicPixFormat = {GRAPHIC_PIXEL_FMT_YCBCR_420_SP,
                              GRAPHIC_PIXEL_FMT_YCRCB_420_SP,
                              GRAPHIC_PIXEL_FMT_YCBCR_P010,
                              GRAPHIC_PIXEL_FMT_YCRCB_P010};
```

---

## 4. VpxDecoder 详解

### 4.1 类结构

```cpp
// vpxDecoder.h
class VpxDecoder : public VideoDecoder {
public:
    explicit VpxDecoder(const std::string &name);
    int32_t CreateDecoder() override;    // vpx_codec_dec_init
    void DeleteDecoder() override;         // vpx_codec_destroy
    void SendFrame() override;             // vpx_codec_decode
    int32_t DecodeFrameOnce() override;    // vpx_codec_get_frame
    static int32_t GetCodecCapability(std::vector<CapabilityData> &capaArray);

private:
    VPX_DEC_HANDLE vpxDecHandle_ = nullptr;   // vpx_codec_ctx_t*
    vpx_image_t *vpxDecOutputImg_ = nullptr;   // libvpx 输出帧
    VpxDecInArgs vpxDecoderInputArgs_;
    HdrMetadata hdrMetadata_;                 // HDR 元数据
    ColorSpaceInfo colorSpaceInfo_;           // 色彩空间信息
    static void GetVp9CapProf(...);
    static void GetVp8CapProf(...);
    int VpxCreateDecoderFunc(void**, const char*);  // vpx_codec_dec_init
    int VpxDestroyDecoderFunc(void**);              // vpx_codec_destroy
    int VpxDecodeFrameFunc(void*, const unsigned char*, unsigned int);  // vpx_codec_decode
    int VpxGetFrameFunc(void*, vpx_image_t**);      // vpx_codec_get_frame
};
```

### 4.2 libvpx 解码 API

```cpp
// VpxDecoder::VpxCreateDecoderFunc - libvpx 初始化
const VpxInterface *decoder = get_vpx_decoder_by_name(name);  // "vp8" 或 "vp9"
vpx_codec_ctx_t *ctx = (vpx_codec_ctx_t *)malloc(sizeof(*ctx));
vpx_codec_dec_init(ctx, decoder->codec_interface(), NULL, VPX_CODEC_USE_FRAME_THREADING);
*vpxDecoder = ctx;

// VpxDecoder::VpxDecodeFrameFunc - 发送压缩帧
vpx_codec_decode(codec, frame, frameSize, NULL, 0);

// VpxDecoder::VpxGetFrameFunc - 获取解码后帧
vpx_codec_err_t res = vpx_codec_get_frame(codec, &img);
```

### 4.3 VP8/VP9 能力注册（GetCodecCapability）

```cpp
// VP9: max 3840x2160, 130fps, Profile 0/1
GetVp9CapProf():
    capsData.width.maxVal = 3840; capsData.height.maxVal = 2160;
    capsData.frameRate.maxVal = 130;
    capsData.profiles = {VP9_PROFILE_0, VP9_PROFILE_1};

// VP8: max 3840x2160, 60fps
GetVp8CapProf():
    capsData.width.maxVal = 3840; capsData.height.maxVal = 2160;
    // 无 Profile 字段（VP8 只有一个 Profile）
```

---

## 5. HevcDecoder vs VpxDecoder vs FCodec vs Av1Decoder 横向对比

| 维度 | HevcDecoder | VpxDecoder | FCodec | Av1Decoder |
|------|-------------|-----------|--------|-----------|
| **格式** | HEVC/H.265 | VP8/VP9 | H.264/MPEG2/MPEG4... | AV1 |
| **底层库** | libhevcdec_ohos.z.so | libvpx.z.so | libavcodec.z.so | libdav1d.z.so |
| **API 类型** | 自定义 HDI | libvpx API | FFmpeg libavcodec | dav1d API |
| **分辨率上限** | 1920×1920 | 3840×2160 | 5120×5120 | 1920×1080 |
| **最大帧率** | 30fps | VP9=130/VP8=60 | 120fps | 300fps |
| **Profiles** | Main/Main_10 | VP9=0/1, VP8=无 | Baseline/Main/High | Main/High |
| **实例数上限** | 64 | 64 | 64 | 64 |
| **HDR 支持** | ✅ HDR10/SL-HDR1 | ✅ HDR10 | ✅ | ✅ |
| **帧线程** | ❌ 无 | ✅ VPX_CODEC_USE_FRAME_THREADING | ❌ | ❌ |
| **解码线程** | SendFrame 单线程 | SendFrame 单线程 | 双线程(Send+Receive) | SendFrame 单线程 |

---

## 6. 与 S39 VideoDecoder 基类的关系

HevcDecoder 和 VpxDecoder 均继承 VideoDecoder 基类，基类提供：

```cpp
class VideoDecoder : public RenderSurface, public CodecBase {
    // BlockQueue 三队列（继承自 CodecBase）
    std::shared_ptr<BlockQueue<uint32_t>> inputAvailQue_;  // 输入缓冲可用队列
    std::shared_ptr<BlockQueue<uint32_t>> codecAvailQue_; // 解码输出可用队列
    std::shared_ptr<BlockQueue<uint32_t>> renderAvailQue_; // 渲染可用队列

    // State 状态机（11 个状态，定义在 CodecBase）
    enum struct State { UNINITIALIZED, INITIALIZED, CONFIGURED, RUNNING, ... };

    // Surface/Buffer 双模式（RenderSurface 基类）
    int32_t SetOutputSurface(sptr<Surface> surface) override;
    int32_t FillFrameBuffer(const std::shared_ptr<CodecBuffer> &frameBuffer);
};
```

子类负责实现：
- `CreateDecoder()` / `DeleteDecoder()` - 创建/销毁底层解码器
- `SendFrame()` / `DecodeFrameOnce()` - 解码循环（各有不同的实现策略）
- `ConfigurelWidthAndHeight()` - 各自不同的分辨率范围
- `GetCodecCapability()` - 各自不同的能力注册

---

## 7. Loader 插件注册机制

HevcDecoderLoader 和 Vp9DecoderLoader 均继承 VideoCodecLoader：

```cpp
// HevcDecoderLoader
HevcDecoderLoader() : VideoCodecLoader(
    "libhevcdec_ohos.z.so",          // libPath_
    "CreateHevcDecoderByName",         // createFuncName_
    "GetHevcDecoderCapabilityList"    // getCapsFuncName_
) {}

// Vp9DecoderLoader
Vp9DecoderLoader() : VideoCodecLoader(
    "libvpx_decoder.z.so",
    "CreateVpxDecoderByName",
    "GetVpxDecoderCapabilityList"
) {}
```

外部 C 接口（`extern "C"`）通过 dlopen/dlsym 暴露：

```cpp
// hevc_decoder_api.cpp
extern "C" {
    void CreateHevcDecoderByName(const std::string &name, std::shared_ptr<CodecBase> &codec);
    int32_t GetHevcDecoderCapabilityList(std::vector<CapabilityData> &caps);
}
```

---

## 8. 与其他主题的关联

- **S39 (VideoDecoder)**：HevcDecoder/VpxDecoder 是 VideoDecoder 基类的两个具体实现子类，共享基类基础设施
- **S51 (Av1Decoder)**：对比 Av1Decoder（dav1d 独立解码库）vs HevcDecoder（vendor HDI）vs VpxDecoder（libvpx）vs FCodec（libavcodec）——四种软件解码器架构对比
- **S53 (FCodec)**：FCodec 用 FFmpeg libavcodec（avcodec_send_packet/receive_frame 双线程），HevcDecoder 用 vendor HDI（HEVC_DecodeFrame 单线程），VpxDecoder 用 libvpx（vpx_codec_decode 单线程）
- **S47 (CodecCapability)**：HevcDecoder::GetCodecCapability 注册 HEVC Main/Main_10 Profile；VpxDecoder::GetCodecCapability 注册 VP9 Profile 0/1
- **S11 (HCodec)**：HevcDecoder 是 vendor 实现（libhevcdec_ohos.z.so），与 HCodec HDI 硬件解码器体系相关联

---

## 附录：HEVC HDR 元数据填充

```cpp
void HevcDecoder::FillHdrInfo(sptr<SurfaceBuffer> surfaceBuffer)
{
    // 从 HEVC_SEI_PTL 获取 HDR10 信息
    // maxContentLightLevel / maxPicAverageLightLevel
    // displayPrimariesX[3] / displayPrimariesY[3] (GBR 三个通道)
    // whitePointX / whitePointY
    // maxDisplayMasteringLuminance / minDisplayMasteringLuminance

    ConvertHdrStaticMetadata(hevcHdrMetadata, staticMetadataVec);
    BufferRequestMetadata requestMetadata = {...};
    surfaceBuffer->SetMetaData(BufferRequestMetadata::KEY_HDR_STATIC_METADATA, requestMetadata);
}
```

## 附录：VpxDecoder HDR 元数据

```cpp
// vpxDecoder.h - HdrMetadata 结构体
struct HdrMetadata {
    float displayPrimariesX[3] = {0, 0, 0};  // G/B/R primaries
    float displayPrimariesY[3] = {0, 0, 0};
    float whitePointX = 0, whitePointY = 0;
    float maxDisplayMasteringLuminance = 0;
    float minDisplayMasteringLuminance = 0;
};

// libavutil/mastering_display_metadata.h - FFmpeg HDR 元数据格式
```
