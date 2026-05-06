---
status: approved
approved_at: "2026-05-06"
mem_id: MEM-ARCH-AVCODEC-S59
title: "AvcEncoder 硬件 H.264 编码器——libavcenc_ohos.z.so 封装与九状态机"
scope:
  - AVCodec
  - VideoEncoder
  - HardwareCodec
  - H.264
  - AVC
  - dlopen
  - StateMachine
  - BlockQueue
  - MediaCodecCallback
created_by: builder-agent
created_at: "2026-04-27T01:10:00+08:00"
related:
  - S42: AVCodecVideoEncoder（上层框架）
  - S57: HDecoder/HEncoder（OMX/HDI硬件编解码通用架构）
  - S36: VideoEncoderFilter（Filter层封装）
  - S23: SurfaceEncoderAdapter（Filter→Codec适配层）
  - S17: SmartFluencyDecoding（编码降帧）
evidence_count: 25+
pipeline_position: "SurfaceEncoderAdapter(S23) → AvcEncoder（S59本主题）→ SurfaceEncoderFilter(S36)"
---

# AvcEncoder 硬件 H.264 编码器

## 1. 架构定位

AvcEncoder 是 OH_AVCodec 中硬件 H.264/AVC 编码器的具体实现类，继承自 CodecBase（avc_encoder.h:43）。它通过 dlopen 加载 vendor 专有库 `libavcenc_ohos.z.so`，是 S57（HDecoder/HEncoder 通用硬件编解码框架）的具体编码器实例。

**调用链**：
```
SurfaceEncoderFilter(S36)
  → SurfaceEncoderAdapter(S23)
    → AVCodecVideoEncoder (VideoEncoder基类)
      → AvcEncoder (S59本主题, avc_encoder.h)
        → libavcenc_ohos.z.so (vendor HDI)
```

## 2. HDI 接口定义（AvcEnc_Typedef.h）

AvcEncoder 通过函数指针调用 vendor HDI：

```cpp
// avc_encoder.h:37-39
using CreateAvcEncoderFuncType = uint32_t (*)(AVC_ENC_HANDLE *phEncoder, AVC_ENC_INIT_PARAM *pstInitParam);
using EncodeFuncType = uint32_t (*)(AVC_ENC_HANDLE hEncoder, AVC_ENC_INARGS *pstInArgs, AVC_ENC_OUTARGS *pstOutArgs);
using DeleteFuncType = uint32_t (*)(AVC_ENC_HANDLE hEncoder);

// avc_encoder.cpp:83
const char *AVC_ENC_LIB_PATH = "libavcenc_ohos.z.so";
```

关键类型定义（AvcEnc_Typedef.h）：
- `AVC_ENC_HANDLE`：编码器实例句柄（`typedef void *AVC_ENC_HANDLE`）
- `AVC_ENC_INIT_PARAM`：初始化参数（width/height/frameRate/bitrate/qp/encMode/colorFmt/profile/level）
- `AVC_ENC_INARGS`：输入参数（colorFmt/timestamp/...）
- `AVC_ENC_OUTARGS`：输出参数（返回编码后数据）

编码模式枚举（AvcEnc_Typedef.h）：
```cpp
typedef enum {
    MODE_CQP = 0x0,   // Constant QP
    MODE_CBR = 0x1,   // Constant Bitrate
    MODE_VBR = 0x2,   // Variable Bitrate
} ENC_MODE;

typedef enum {
    PROFILE_BASE  = 0x0,
    PROFILE_MAIN  = 0x1,
    PROFILE_HIGH  = 0x2,
    PROFILE_SIMPLE = 0x3,
    PROFILE_ADVSIMPLE = 0x4,
} ENC_PROFILE;
```

## 3. 动态库加载（AvcFuncMatch）

```cpp
// avc_encoder.cpp:158-211
void AvcEncoder::AvcFuncMatch()
{
    handle_ = dlopen(AVC_ENC_LIB_PATH, RTLD_LAZY);  // libavcenc_ohos.z.so
    if (handle_ != nullptr) {
        avcEncoderCreateFunc_ = reinterpret_cast<CreateAvcEncoderFuncType>(dlsym(handle_, "..."));
        avcEncoderFrameFunc_   = reinterpret_cast<EncodeFuncType>(dlsym(handle_, "..."));
        avcEncoderDeleteFunc_  = reinterpret_cast<DeleteFuncType>(dlsym(handle_, "..."));
    }
    // ReleaseHandle(): dlclose(handle_) when done
}
```

## 4. 九状态机

```cpp
// avc_encoder.h:163-171
enum struct State : int32_t {
    UNINITIALIZED,  // 默认初始状态 (avc_encoder.cpp:133)
    INITIALIZED,    // Initialize()后 (avc_encoder.cpp:397)
    CONFIGURED,      // Configure()后 (avc_encoder.cpp:461)
    STOPPING,       // Stop()中 (avc_encoder.cpp:251,269,283)
    RUNNING,        // Start()后
    FLUSHED,        // Flush()完成
    FLUSHING,       // Flush()中
    EOS,            // EOS发送完成 (avc_encoder.cpp:1626)
    ERROR,          // 错误状态 (avc_encoder.cpp:166)
};
```

状态转换关键路径：
- `UNINITIALIZED → INITIALIZED`：Initialize()（avc_encoder.cpp:397）
- `INITIALIZED → CONFIGURED`：Configure()（avc_encoder.cpp:461）
- `CONFIGURED → RUNNING`：Start()（avc_encoder.cpp:708-709）
- `RUNNING → EOS`：EOS帧发送完成（avc_encoder.cpp:1626）
- `任意 → STOPPING`：Stop()（avc_encoder.cpp:251,269,283）

## 5. 双 BlockQueue 缓冲管理

```cpp
// avc_encoder.h:202-203
std::shared_ptr<BlockQueue<uint32_t>> inputAvailQue_;   // 输入可用缓冲区队列
std::shared_ptr<BlockQueue<uint32_t>> codecAvailQue_;  // 编码输出可用队列

// avc_encoder.cpp:817-818（分配时）
inputAvailQue_ = std::make_shared<BlockQueue<uint32_t>>("inputAvailQue", inputBufferCnt);
codecAvailQue_ = std::make_shared<BlockQueue<uint32_t>>("codecAvailQue", outputBufferCnt);
```

## 6. FBuffer 缓冲区所有权管理

```cpp
// avc_encoder.h:58-68
class FBuffer {
public:
    enum class Owner {
        OWNED_BY_US,      // 默认
        OWNED_BY_CODEC,   // 编码器持有
        OWNED_BY_USER,     // 用户持有
        OWNED_BY_SURFACE,  // Surface持有
    };
    std::shared_ptr<AVBuffer> avBuffer_ = nullptr;
    sptr<SurfaceBuffer> surfaceBuffer_ = nullptr;
    sptr<SyncFence> fence_ = nullptr;
    std::atomic<Owner> owner_ = Owner::OWNED_BY_US;
};
```

## 7. SendFrame 线程驱动

```cpp
// avc_encoder.cpp:395-396（初始化）
sendTask_ = std::make_shared<TaskThread>("SendFrame");
sendTask_->RegisterHandler([this] { SendFrame(); });

// avc_encoder.cpp:1601-1652（SendFrame主循环）
void AvcEncoder::SendFrame() {
    if (state_ != State::RUNNING) return;
    uint32_t index = inputAvailQue_->Front();
    if (isFirstFrame_) EncoderAvcHeader();  // 首帧写入SPS/PPS
    ret = EncoderAvcFrame(avcEncInputArgs_, avcEncOutputArgs_);
    if (ret == AVCS_ERR_OK) {
        inputBuffer->owner_ = FBuffer::Owner::OWNED_BY_USER;
        inputAvailQue_->Pop();
        NotifyUserToFillBuffer(index, inputAVBuffer);
    }
}
```

关键步骤：
1. `EncoderAvcHeader()`：首帧写入 SPS/PPS/VUI（avc_encoder.cpp:1570-1575）
2. `FillAvcEncoderInArgs()`：NV12/NV21/YUV420/RGBA → AVC_ENC_INARGS（avc_encoder.cpp:1519-1520）
3. `EncoderAvcFrame()`：调用 `avcEncoderFrameFunc_()` 执行硬件编码（avc_encoder.cpp:1532-1566）
4. `EncoderAvcTailer()`：EOS写入（avc_encoder.cpp:1578-1583）

## 8. 像素格式转换

```cpp
// avc_encoder.h:179-193（InputFrame结构）
struct InputFrame {
    uint8_t *buffer = nullptr;
    int32_t width = 0, height = 0, stride = 0, size = 0, uvOffset = 0;
    VideoPixelFormat format = VideoPixelFormat::UNKNOWN;
    int64_t pts = 0;
};

// avc_encoder.cpp:1519-1520（格式路由）
if (srcPixelFmt_ == VideoPixelFormat::NV12) return Nv12ToAvcEncoderInArgs(inFrame, inArgs);
if (srcPixelFmt_ == VideoPixelFormat::NV21) return Nv21ToAvcEncoderInArgs(inFrame, inArgs);
```

支持的输入像素格式（avc_encoder.cpp:1723-1725）：
- YUVI420（软件YUV420 planar）
- NV12（YUV420 semi-planar，UV交错）
- NV21（YUV420 semi-planar，VU交错）
- RGBA（转换为YUV420后编码）

## 9. 能力注册（GetCodecCapability）

```cpp
// avc_encoder.cpp:1747-1756
int32_t AvcEncoder::GetCodecCapability(std::vector<CapabilityData> &capaArray)
{
    for (uint32_t i = 0; i < SUPPORT_VCODEC_NUM; ++i) {
        CapabilityData capsData;
        GetCapabilityData(capsData, i);
        capaArray.emplace_back(capsData);
    }
}

// avc_encoder.cpp:77-81（SUPPORT_VCODEC数组）
SUPPORT_VCODEC[] = {
    {AVCodecCodecName::VIDEO_ENCODER_AVC_NAME, CodecMimeType::VIDEO_AVC, "h264", true},
};

// avc_encoder.cpp:1707-1743（能力详情）
capsData.width.maxVal = VIDEO_MAX_WIDTH_SIZE;   // 最大分辨率
capsData.height.maxVal = VIDEO_MAX_HEIGHT_SIZE;
capsData.frameRate.maxVal = VIDEO_FRAMERATE_MAX_SIZE;
capsData.bitrate.maxVal = VIDEO_BITRATE_MAX_SIZE;
capsData.bitrateMode = {CBR, VBR, CQ};           // 三种码率模式
capsData.profiles = {AVC_PROFILE_BASELINE, AVC_PROFILE_MAIN};  // 不支持HIGH
capsData.maxInstance = VIDEO_INSTANCE_SIZE;
```

## 10. 默认参数

```cpp
// avc_encoder.cpp:45-67
constexpr int32_t DEFAULT_VIDEO_WIDTH = 1920;
constexpr int32_t DEFAULT_VIDEO_HEIGHT = 1080;
constexpr int32_t DEFAULT_VIDEO_BITRATE = 6000000;  // 6 Mbps
constexpr double DEFAULT_VIDEO_FRAMERATE = 30.0;
constexpr int32_t DEFAULT_VIDEO_IFRAME_INTERVAL = 60;  // 60帧一个IDR
constexpr int32_t DEFAULT_VIDEO_INTERVAL_TIME = 2000;  // 2s
```

## 11. 与 S42/S57 的关系

| 维度 | S42 (VideoEncoder基类) | S59 (AvcEncoder具体) | S57 (HDecoder/HEncoder通用) |
|------|----------------------|---------------------|--------------------------|
| 层级 | 基类/框架 | 具体编码器实现 | 硬件Codec基类 |
| 继承 | CodecBase | CodecBase | CodecBase |
| 库 | - | libavcenc_ohos.z.so | vendor OMX/HDI |
| Profile | - | Baseline/Main | 通用 |
| 码率控制 | - | CBR/VBR/CQ | 通用 |
| 状态机 | CodecBase七态 | 九态（扩展FLUSHED/FLUSHING/EOS） | HCodec八态 |

## 12. 关键证据来源

| 文件 | 行号 | 内容 |
|------|------|------|
| `services/engine/codec/video/avcencoder/avc_encoder.h` | 35-211 | 类定义、函数指针类型、FBuffer |
| `services/engine/codec/video/avcencoder/avc_encoder.cpp` | 45-67 | 默认参数、SUPPORT_VCODEC数组 |
| `services/engine/codec/video/avcencoder/avc_encoder.cpp` | 83 | AVC_ENC_LIB_PATH = "libavcenc_ohos.z.so" |
| `services/engine/codec/video/avcencoder/avc_encoder.cpp` | 158-211 | AvcFuncMatch / dlopen / dlsym |
| `services/engine/codec/video/avcencoder/avc_encoder.cpp` | 378-397 | Initialize() |
| `services/engine/codec/video/avcencoder/avc_encoder.cpp` | 817-818 | BlockQueue 初始化 |
| `services/engine/codec/video/avcencoder/avc_encoder.cpp` | 1601-1652 | SendFrame() 线程 |
| `services/engine/codec/video/avcencoder/avc_encoder.cpp` | 1687-1756 | GetCodecCapability 能力注册 |
| `services/engine/codec/video/avcencoder/AvcEnc_Typedef.h` | 全文 | HDI类型定义 |
