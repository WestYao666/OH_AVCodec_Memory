# MEM-ARCH-AVCODEC-S183 — AVCodec H.264 软件编码器体系

## 元数据

| 字段 | 内容 |
|------|------|
| ID | MEM-ARCH-AVCODEC-S183 |
| 标题 | AVC H.264 软件编码器体系——AvcEncoder + AvcEncoderLoader + AvcEncoderConvert + AvcEncoderUtil 四组件 |
| 状态 | draft: true |
| 创建时间 | 2026-05-25T10:18 Asia/Shanghai |
| Builder | builder-agent |
| 标签 | AVCodec, VideoEncoder, H264, AVC, SoftwareCodec, libavcenc, ColorSpace, RateControl, AvcEncoder, AvcEncoderLoader |
| 关联主题 | S59(AvcEncoder硬件编码器), S54(HevcDecoder+VpxDecoder), S57(HDecoder/HEncoder), S70(CodecBase+Loader), S50(AudioResample) |
| 源码行数 | avc_encoder.cpp(1765行)+avc_encoder.h(270行)+avc_encoder_convert.cpp(369行)+avc_encoder_util.cpp(235行)+avc_encoder_api.cpp(36行)+avc_encoder_loader.cpp(72行)=2747行 |

---

## 1. 架构概述

AVC H.264 软件编码器体系是 OpenHarmony AVCodec 中处理 H.264 视频编码的核心组件，位于 `services/engine/codec/video/avcencoder/` 目录。该体系由四个核心组件构成：**AvcEncoder**（1765行主编码器）、**AvcEncoderConvert**（369行色彩空间转换）、**AvcEncoderUtil**（235行工具函数）、**AvcEncoderApi**（36行C API封装）、**AvcEncoderLoader**（72行工厂加载器）。

AvcEncoder 通过 dlopen 动态加载 `libavcenc_ohos.z.so` 硬件编码器库，内部通过 TaskThread 驱动 SendFrame 任务，支持 Surface 输入和 Buffer 输入两种模式。它继承 CodecBase，提供标准的 Configure → Start → Stop → Release 生命周期管理，支持 NV12/NV21/YUV420P/RGBA 输入格式，支持 CBR/VBR/CQ 三种码率控制模式，支持 QP/比特率/帧率/I帧间隔配置，支持 BT601/BT709 色域转换（ARM NEON 优化）。

AvcEncoderLoader 是工厂加载器，通过 dlopen 加载 `libavc_encoder.z.so`，使用 CreateAvcEncoderByName 函数创建编码器实例，使用 GetAvcEncoderCapabilityList 获取编码能力列表。它继承 VideoCodecLoader 基类（67行），提供统一的工厂接口。

AvcEncoderConvert 处理 RGB 到 YUV 的色彩空间转换，使用 BT601/BT709 转换矩阵，支持 ARM NEON 指令集优化（#if defined(ARMV8)）。

AvcEncoderUtil 提供工具函数，包括 AVCLevel 到 H264Level 的映射表（支持 1.0 到 6.2）、帧类型到 BufferFlag 转换、编码器级别验证。

---

## 2. 关键代码路径与行号级 Evidence

### 2.1 AvcEncoderLoader 工厂加载器（avc_encoder_loader.cpp 72行）

**CreateByName 工厂入口（L24-37）**：
```
L24: std::shared_ptr<CodecBase> AvcEncoderLoader::CreateByName(const std::string &name)
L28:     CHECK_AND_RETURN_RET_LOG(loader.Init() == AVCS_ERR_OK, nullptr, "Create codec by name failed: init error");
L30:     if (noDeletePtr == nullptr) { loader.CloseLibrary(); }
L33:     return noDeletePtr;
```
Singleton 模式的工厂加载器，通过 dlopen 加载 libavc_encoder.z.so 并调用 CreateAvcEncoderByName。

**GetCapabilityList 能力查询（L39-49）**：
```
L47:     int32_t ret = loader.GetCaps(caps);
```
调用 GetAvcEncoderCapabilityList 获取编码能力列表。

**加载库配置（L17-19）**：
```
L17: const char *AVC_ENCODER_LIB_PATH = "libavc_encoder.z.so";
L18: const char *AVC_ENCODER_CREATE_FUNC_NAME = "CreateAvcEncoderByName";
L19: const char *AVC_ENCODER_GETCAPS_FUNC_NAME = "GetAvcEncoderCapabilityList";
```

### 2.2 AvcEncoder 主编码器（avc_encoder.cpp 1765行）

**常量定义（L24-63）**：
```
L24: constexpr uint32_t INDEX_INPUT = 0;  // 输入缓冲区索引
L25: constexpr uint32_t INDEX_OUTPUT = 1; // 输出缓冲区索引
L26: constexpr uint32_t DEFAULT_IN_BUFFER_CNT = 4; // 默认输入缓冲队列长度
L27: constexpr uint32_t DEFAULT_OUT_BUFFER_CNT = 4; // 默认输出缓冲队列长度
L28: constexpr uint32_t DEFAULT_MIN_BUFFER_CNT = 2; // 最小缓冲队列长度
L31: constexpr int32_t VIDEO_MAX_WIDTH_SIZE = 2560; // 最大宽度
L32: constexpr int32_t VIDEO_MAX_HEIGHT_SIZE = 2560; // 最大高度
L33: constexpr int32_t DEFAULT_VIDEO_WIDTH = 1920; // 默认宽度
L34: constexpr int32_t DEFAULT_VIDEO_HEIGHT = 1080; // 默认高度
L36: constexpr int32_t VIDEO_BITRATE_MIN_SIZE = 10000; // 最小码率 10kbps
L37: constexpr int32_t VIDEO_BITRATE_MAX_SIZE = 30000000; // 最大码率 30Mbps
L38: constexpr int32_t VIDEO_FRAMERATE_MIN_SIZE = 1; // 最小帧率
L39: constexpr int32_t VIDEO_FRAMERATE_MAX_SIZE = 60; // 最大帧率 60fps
L42: constexpr int32_t VIDEO_QP_MAX = 51; // 最大QP
L43: constexpr int32_t VIDEO_QP_MIN = 4; // 最小QP
L44: constexpr int32_t VIDEO_QP_DEFAULT = 20; // 默认QP
L45: constexpr int32_t VIDEO_IFRAME_INTERVAL_MIN_TIME = 1000; // 最小I帧间隔 1s
L46: constexpr int32_t VIDEO_IFRAME_INTERVAL_MAX_TIME = 3600000; // 最大I帧间隔 1h
L47: constexpr int32_t DEFAULT_VIDEO_IFRAME_INTERVAL = 60; // 默认I帧间隔 60帧
L48: constexpr int32_t DEFAULT_VIDEO_BITRATE = 6000000; // 默认码率 6Mbps
L49: constexpr double DEFAULT_VIDEO_FRAMERATE = 30.0; // 默认帧率 30fps
```

**dlopen 加载库（AVC_ENC_LIB_PATH = "libavcenc_ohos.z.so"）（L89-93）**：
```
L89: const char *AVC_ENC_LIB_PATH = "libavcenc_ohos.z.so";
L90: const char *AVC_ENC_CREATE_FUNC_NAME = "InitEncoder";
L91: const char *AVC_ENC_ENCODE_FRAME_FUNC_NAME = "EncodeProcess";
L92: const char *AVC_ENC_DELETE_FUNC_NAME = "ReleaseEncoder";
```
注意：AvcEncoder 加载的是 libavcenc_ohos.z.so（内部编码库），而 AvcEncoderLoader 加载的是 libavc_encoder.z.so（外壳库）。

**构造函数实例管理（L141-175）**：
```
L141: AvcEncoder::AvcEncoder(const std::string &name) : codecName_(name), state_(State::UNINITIALIZED), ...
L155: if (encInstanceID_ < VIDEO_INSTANCE_SIZE) {
L156:     handle_ = dlopen(AVC_ENC_LIB_PATH, RTLD_LAZY);
L161:     AvcFuncMatch(); // 绑定三个函数指针
L163:     AVCODEC_LOGI("Num %{public}u AvcEncoder entered, state: Uninitialized", encInstanceID_);
L166: } else {
L168:     state_ = State::ERROR;
L169: }
```
实例限制 VIDEO_INSTANCE_SIZE=16，超出则报错。dlopen 延迟加载，失败则 state_=ERROR。

**AvcFuncMatch 函数绑定（L186-202）**：
```
L186: void AvcEncoder::AvcFuncMatch()
L188:     avcEncoderCreateFunc_ = reinterpret_cast<CreateAvcEncoderFuncType>(dlsym(handle_, AVC_ENC_CREATE_FUNC_NAME)); // InitEncoder
L190:     avcEncoderFrameFunc_ = reinterpret_cast<EncodeFuncType>(dlsym(handle_, AVC_ENC_ENCODE_FRAME_FUNC_NAME)); // EncodeProcess
L192:     avcEncoderDeleteFunc_ = reinterpret_cast<DeleteFuncType>(dlsym(handle_, AVC_ENC_DELETE_FUNC_NAME)); // ReleaseEncoder
```
三个函数指针：InitEncoder（创建编码器实例）、EncodeProcess（编码帧）、ReleaseEncoder（释放编码器）。

**Initialize 初始化（L378-394）**：
```
L378: int32_t AvcEncoder::Initialize()
L384: format_.PutStringValue(MediaDescriptionKey::MD_KEY_CODEC_MIME, mime);
L385: format_.PutStringValue(MediaDescriptionKey::MD_KEY_CODEC_NAME, codecName_);
L387: sendTask_ = std::make_shared<TaskThread>("SendFrame");
L388: sendTask_->RegisterHandler([this] { SendFrame(); });
L389: state_ = State::INITIALIZED;
L390: isFirstFrame_ = true;
```
创建 TaskThread 驱动 SendFrame 任务。isFirstFrame_=true 标记首帧（用于写入 SPS/PPS/AVC decoder config record）。

**Configure 配置（L416-465）**：
```
L416: int32_t AvcEncoder::Configure(const Format &format)
L418:     if (state_ == State::UNINITIALIZED) { Initialize(); }
L420:     CHECK_AND_RETURN_RET_LOG((state_ == State::INITIALIZED), AVCS_ERR_INVALID_STATE, ...);
L422:     format_.PutIntValue(MediaDescriptionKey::MD_KEY_WIDTH, DEFAULT_VIDEO_WIDTH);
L423:     format_.PutIntValue(MediaDescriptionKey::MD_KEY_HEIGHT, DEFAULT_VIDEO_HEIGHT);
```
配置参数：宽高、QP、码率、帧率、I帧间隔、色域、码率模式。

**Start 启动（L886-922）**：
```
L886: int32_t AvcEncoder::Start()
L900:     ret = avcEncoderCreateFunc_(..., &encHandle_); // 调用 InitEncoder 创建编码器实例
L901:     CHECK_AND_RETURN_RET_LOG(ret == AVCS_ERR_OK, AVCS_ERR_UNKNOWN, "avcEncoderCreateFunc_ failed");
```
调用 InitEncoder (avcEncoderCreateFunc_) 创建编码器实例 handle_。

**Stop 停止（L935-970）**：
```
L935: int32_t AvcEncoder::Stop()
L966:     avcEncoderDeleteFunc_(encHandle_); // 调用 ReleaseEncoder 释放实例
L967:     encHandle_ = nullptr;
```
调用 ReleaseEncoder (avcEncoderDeleteFunc_) 释放编码器实例。

**Flush 刷新（L971-991）**：
```
L971: int32_t AvcEncoder::Flush()
L983:     avcEncoderFrameFunc_(encHandle_, &stInArgs, &stOutArgs); // 传入空帧强制输出
```
传入空帧强制输出所有待处理帧。

**SignalRequestIDRFrame 强制IDR帧（L699-705）**：
```
L699: int32_t AvcEncoder::SignalRequestIDRFrame()
L704:     isNeedIdrFrame_ = true; // 标记下一帧为IDR帧
```

### 2.3 AvcEncoder_convert 色彩空间转换（avc_encoder_convert.cpp 369行）

**BT601/BT709 转换矩阵（L36-51）**：
```
L36: static const int16_t BT601_MATRIX[2][3][3] = {
L37:     {{76, 150, 29}, {-43, -85, 128}, {128, -107, -21}},     // RANGE_FULL
L38:     {{66, 129, 25}, {-38, -74, 112}, {112, -94, -18}},      // RANGE_LIMITED
L40: static const int16_t BT709_MATRIX[2][3][3] = {
L41:     {{54, 183, 18}, {-29, -99, 128}, {128, -116, -12}},     // RANGE_FULL
L42:     {{47, 157, 16}, {-26, -86, 112}, {112, -102, -10}},    // RANGE_LIMITED
```
RGB 到 YUV 的转换矩阵，BT601 用于标清，BT709 用于高清。支持 RANGE_FULL 和 RANGE_LIMITED 两种色域范围。

**ARM NEON 优化（L17-19）**：
```
L17: #if defined(ARMV8)
L18: #include <arm_neon.h>
L19: #endif
```
使用 ARM NEON 指令集加速色彩空间转换。

### 2.4 AvcEncoder_util 工具函数（avc_encoder_util.cpp 235行）

**AVCLevel 到 H264Level 映射表（L25-49）**：
```
L25: std::map<AVCLevel, H264Level> g_encodeLevelMap = {
L26:     { AVCLevel::AVC_LEVEL_1,  H264Level::H264_LEVEL_10 },
L27:     { AVCLevel::AVC_LEVEL_1b, H264Level::H264_LEVEL_1B },
...
L45:     { AVCLevel::AVC_LEVEL_61, H264Level::H264_LEVEL_61 },
L46:     { AVCLevel::AVC_LEVEL_62, H264Level::H264_LEVEL_62 },
L47: };
```
支持 Level 1.0 到 6.2 的完整映射。

**帧类型到 BufferFlag 转换（L58-70）**：
```
L58: AVCodecBufferFlag AvcFrameTypeToBufferFlag(uint32_t frameType)
L61:     case AVC_ENCODER_I_FRAMETYPE: flag = AVCodecBufferFlag::AVCODEC_BUFFER_FLAG_SYNC_FRAME; break;
L62:     case AVC_ENCODER_P_FRAMETYPE: flag = AVCodecBufferFlag::AVCODEC_BUFFER_FLAG_NONE; break;
L63:     default: flag = AVCodecBufferFlag::AVCODEC_BUFFER_FLAG_NONE;
```
I帧 → SYNC_FRAME (IDR)，P帧 → NONE。

**常量定义（L53-54）**：
```
L53: const uint32_t AVC_ENCODER_P_FRAMETYPE = 1; // P帧类型值
L54: const uint32_t AVC_ENCODER_I_FRAMETYPE = 3; // I帧类型值（等同于 H.264 NAL type 5）
```

---

## 3. 与已有记忆的关联

| 关联记忆 | 关联关系 |
|----------|----------|
| S59（AvcEncoder硬件编码器） | S183 是 S59 的软件实现细节补充：AvcEncoderLoader 加载 libavc_encoder.z.so，S59 描述的是工厂+生命周期，S183 描述的是内部编码器实现 |
| S70（CodecBase+Loader） | AvcEncoderLoader 继承 VideoCodecLoader 基类（67行），与 S70 的 CodecBase 工厂体系完全对齐 |
| S54（HevcDecoder+VpxDecoder） | 同为视频解码器/编码器，共享 VideoCodecLoader 基类模式 |
| S57（HDecoder/HEncoder） | 共享硬件Codec框架，但使用不同的底层库（AvcEncoder用libavcenc_ohos.z.so） |
| S50（AudioResample） | AvcEncoderConvert 色彩空间转换与 AudioResample 音频重采样属于同类模式：输入格式转换 |

---

## 4. 架构图（文字版）

```
应用层（Native API）
    OH_VideoEncoder_CreateByName()
         ↓
AvcEncoderLoader（avc_encoder_loader.cpp 72行）
    dlopen("libavc_encoder.z.so")
    CreateAvcEncoderByName() → 创建 AvcEncoder 实例
         ↓
AvcEncoder（avc_encoder.cpp 1765行）
    dlopen("libavcenc_ohos.z.so")
    InitEncoder() → 创建 AVC_ENC_HANDLE
    EncodeProcess() → 编码帧
    ReleaseEncoder() → 释放实例
         ↓
    sendTask_（TaskThread）→ SendFrame() 驱动
         ↓
AvcEncoderConvert（avc_encoder_convert.cpp 369行）
    RGB → YUV (BT601/BT709 + ARM NEON)
         ↓
AvcEncoderUtil（avc_encoder_util.cpp 235行）
    AVCLevel → H264Level 映射
    帧类型转换 / 码率控制工具
```

---

## 5. 关键常量速查

| 常量 | 值 | 说明 |
|------|-----|------|
| VIDEO_INSTANCE_SIZE | 16 | 最大编码器实例数 |
| VIDEO_MAX_WIDTH/HEIGHT | 2560 | 最大分辨率 |
| VIDEO_BITRATE_MIN/MAX | 10k/30M | 码率范围 |
| VIDEO_FRAMERATE_MIN/MAX | 1/60 | 帧率范围 |
| VIDEO_QP_MIN/MAX | 4/51 | QP范围 |
| VIDEO_QP_DEFAULT | 20 | 默认QP |
| DEFAULT_VIDEO_BITRATE | 6M | 默认码率 |
| DEFAULT_VIDEO_FRAMERATE | 30.0 | 默认帧率 |
| AVC_ENCODER_I_FRAMETYPE | 3 | I帧类型值（IDR） |
| AVC_ENCODER_P_FRAMETYPE | 1 | P帧类型值 |

---

## 6. 注意事项

- AvcEncoder 加载的是 `libavcenc_ohos.z.so`（内部编码库），而 AvcEncoderLoader 加载的是 `libavc_encoder.z.so`（外壳库）
- 实例限制为 16 个，超出后 state_=ERROR
- 首帧（isFirstFrame_=true）会写入 SPS/PPS/AVC decoder config record
- ARM NEON 优化在 ARMV8 架构下启用，用于加速 RGB→YUV 转换
- 支持 I_PICTURE（IDR帧，等同于 NAL type 5）和 P_PICTURE（P帧，NAL type 1）
