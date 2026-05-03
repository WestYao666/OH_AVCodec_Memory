# MEM-ARCH-AVCODEC-S83

> **主题**：AVCodec Native C API 架构——OH_AVCodec 对象模型、四类 API 家族与 CodecClient IPC 代理
> **scope**：AVCodec, Native API, C API, IPC, CodecClient, interfaces/kits
> **关联场景**：三方应用接入/新人入项/问题定位
> **状态**：`pending_approval`
> **证据来源**：`interfaces/kits/c/native_avcodec_*.h` / `services/services/codec/client/codec_client.cpp` / `interfaces/inner_api/native/avcodec_errors.h`
> **创建时间**：2026-05-03T16:33

---

## 1. 概述

AVCodec Native C API 是 OpenHarmony 多媒体框架对外暴露的核心编程接口，位于 `interfaces/kits/c/` 目录（合计 4675 行头文件）。该 API 基于**句柄对象模型**：应用层持有 `OH_AVCodec *` / `OH_AVDemuxer *` / `OH_AVMuxer *` 等不透明指针，通过 C 函数操作底层 CodecService IPC 代理（CodecClient）。

### 1.1 头文件体系

| 头文件 | 行数 | 职责 |
|--------|------|------|
| `native_avcodec_base.h` | 2355 | 核心类型（OH_AVCodec/O_H_AVFormat/O_H_AVBuffer）、67+ MIME常量、回调结构体、Profile/Level枚举、错误码 |
| `native_avcodec_videodecoder.h` | 578 | VideoDecoder API（CreateByMime/CreateByName/Configure/Start/Stop/Flush/Reset/GetOutputDescription/PushInputBuffer/RenderOutputBuffer） |
| `native_avcodec_videoencoder.h` | 631 | VideoEncoder API（额外：SetParameter/GetInputDescription/PushInputBuffer/GetOutputBuffer） |
| `native_avcodec_audiodecoder.h` | 272 | AudioDecoder API（CreateByMime/CreateByName/Configure/Start/Stop/Flush/Reset） |
| `native_avcodec_audioencoder.h` | 267 | AudioEncoder API（CreateByMime/CreateByName/Configure/Start/Stop/Flush/Reset/IsValid） |
| `native_avcodec_audiocodec.h` | 374 | AudioCodec 统一 API（CreateByMime/CreateByName，内含 isEncoder 参数区分编解码） |
| `native_avcapability.h` | 572 | Capability 查询 API（GetCapabilityList/GetSupportedProfiles/GetSupportedLevels/IsHardwareSupport） |
| `native_avdemuxer.h` | 261 | Demuxer API（CreateWithSource/SelectTrack/UnselectTrack/ReadSample/ReadSampleBuffer/SeekToTime） |
| `native_avmuxer.h` | 192 | Muxer API（Create/SetRotation/SetFormat/AddTrack/Start/WriteSample/WriteSampleBuffer/Stop/Destroy） |
| `native_avsource.h` | 184 | Source API（CreateWithUri/CreateWithFd） |
| `native_cencinfo.h` | ~200 | DRM CENC 加密信息结构（MediaKeySession/DRM_MediaKeySystemInfo） |

---

## 2. 核心类型对象模型

### 2.1 OH_AVCodec 句柄

```c
// native_avcodec_base.h:52
typedef struct OH_AVCodec OH_AVCodec;  // 不透明指针
```

`OH_AVCodec` 是所有编解码实例的顶层句柄，被 VideoDecoder/VideoEncoder/AudioDecoder/AudioEncoder 四个 API 族共享。应用层不直接操作内存，而是通过函数指针传递该句柄。

### 2.2 OH_AVFormat 格式描述对象

```c
// OH_AVFormat 是可读写的 Key-Value 参数容器，编解码器通过它传递：
//   - Configure 阶段：输入/输出媒体描述（宽/高/码率/采样率等）
//   - GetOutputDescription/GetInputDescription：运行时查询实际参数
// 通过 OH_AVFormat_SetIntValue/OH_AVFormat_GetIntValue 等函数操作
```

### 2.3 OH_AVBuffer 缓冲区对象（AVBuffer 模式）

```c
// native_avcodec_base.h:115-136
// Buffer 模式下的输入/输出容器（非 Memory 模式）
typedef void (*OH_AVCodecOnNeedInputBuffer)(OH_AVCodec *codec, uint32_t index,
    OH_AVBuffer *buffer, void *userData);
typedef void (*OH_AVCodecOnNewOutputBuffer)(OH_AVCodec *codec, uint32_t index,
    OH_AVBuffer *buffer, void *userData);
```

OH_AVBuffer 携带元数据（pts/size/flags）和原始数据指针，是 Surface 模式之外的主要数据传递方式。

### 2.4 OH_MediaType 媒体轨道类型

```c
// native_avcodec_base.h:1512
typedef enum OH_MediaType {
    MEDIA_TYPE_AUD = 0,         // 音频轨道
    MEDIA_TYPE_VID = 1,         // 视频轨道
    MEDIA_TYPE_SUBTITLE = 2,    // 字幕轨道
    MEDIA_TYPE_TIMED_METADATA = 5,
    MEDIA_TYPE_AUXILIARY = 6,
} OH_MediaType;
```

---

## 3. 四类 Codec API 家族

### 3.1 VideoDecoder API（native_avcodec_videodecoder.h）

```c
// 创建实例（两种途径）
OH_AVCodec *OH_VideoDecoder_CreateByMime(const char *mime);  // 按 MIME 类型，框架自动选择实现
OH_AVCodec *OH_VideoDecoder_CreateByName(const char *name);   // 按具体解码器名称（如 "avcdecoder"）

// 生命周期七步曲
OH_AVErrCode OH_VideoDecoder_Configure(OH_AVCodec *codec, const OH_AVFormat *format);
OH_AVErrCode OH_VideoDecoder_Prepare(OH_AVCodec *codec);
OH_AVErrCode OH_VideoDecoder_Start(OH_AVCodec *codec);
OH_AVErrCode OH_VideoDecoder_Stop(OH_AVCodec *codec);
OH_AVErrCode OH_VideoDecoder_Flush(OH_AVCodec *codec);
OH_AVErrCode OH_VideoDecoder_Reset(OH_AVCodec *codec);   // Reset 可重新 Configure
OH_AVErrCode OH_VideoDecoder_Destroy(OH_AVCodec *codec);

// 数据操作（Buffer 模式）
OH_AVErrCode OH_VideoDecoder_PushInputBuffer(OH_AVCodec *codec, uint32_t index);
OH_AVErrCode OH_VideoDecoder_RenderOutputBuffer(OH_AVCodec *codec, uint32_t index, int64_t renderTimestamp);
OH_AVErrCode OH_VideoDecoder_FreeOutputBuffer(OH_AVCodec *codec, uint32_t index);

// 运行时信息查询
OH_AVFormat *OH_VideoDecoder_GetOutputDescription(OH_AVCodec *codec);
```

**Surface 模式**：`OH_VideoDecoder_Configure` 时通过 `OH_AVFormat_SetIntValue(format, "pixel_format", ...)` 指定 Surface 输入，绑定 `OH_AVCodecCallback` 的 `onStreamChanged` 回调。

### 3.2 VideoEncoder API（native_avcodec_videoencoder.h）

```c
// 创建
OH_AVCodec *OH_VideoEncoder_CreateByMime(const char *mime);
OH_AVCodec *OH_VideoEncoder_CreateByName(const char *name);

// 生命周期（比 Decoder 多 SetParameter 运行时配置）
OH_AVErrCode OH_VideoEncoder_Configure(OH_AVCodec *codec, const OH_AVFormat *format);
OH_AVErrCode OH_VideoEncoder_Prepare(OH_AVCodec *codec);
OH_AVErrCode OH_VideoEncoder_Start(OH_AVCodec *codec);
OH_AVErrCode OH_VideoEncoder_Stop(OH_AVCodec *codec);
OH_AVErrCode OH_VideoEncoder_Flush(OH_AVCodec *codec);
OH_AVErrCode OH_VideoEncoder_Reset(OH_AVCodec *codec);
OH_AVErrCode OH_VideoEncoder_Destroy(OH_AVCodec *codec);

// 运行时参数（编码过程中可动态调整）
OH_AVErrCode OH_VideoEncoder_SetParameter(OH_AVCodec *codec, const OH_AVFormat *format);

// Surface 模式输入，Buffer 模式输出
OH_AVErrCode OH_VideoEncoder_GetInputDescription(OH_AVCodec *codec);  // Surface 模式输入格式
OH_AVErrCode OH_VideoEncoder_GetOutputBuffer(OH_AVCodec *codec, uint32_t index, OH_AVBuffer **buffer);
```

**VideoEncoder 特有参数键**（`native_avcodec_base.h`）：

| Key | 类型 | 说明 |
|-----|------|------|
| `bitrate` | int64_t | 目标码率（Configure 阶段） |
| `rc_mode` | int32_t | 码率控制模式（CBR/VBR/CQ） |
| `profile` | int32_t | H.264 Profile（Baseline/Main/High） |
| `level` | int32_t | H.264 Level |
| `quality` | int32_t | 编码质量（Quality 模式） |
| `request_i_frame` | bool | 请求立即生成 IDR 帧 |
| `video_encoder_frame_rate` | double | 目标帧率 |
| `video_peak_bitrate` | int64_t | 峰值码率 |

### 3.3 AudioDecoder API（native_avcodec_audiodecoder.h）

```c
OH_AVCodec *OH_AudioDecoder_CreateByMime(const char *mime);
OH_AVCodec *OH_AudioDecoder_CreateByName(const char *name);

OH_AVErrCode OH_AudioDecoder_Configure(OH_AVCodec *codec, const OH_AVFormat *format);
OH_AVErrCode OH_AudioDecoder_Prepare(OH_AVCodec *codec);
OH_AVErrCode OH_AudioDecoder_Start(OH_AVCodec *codec);
OH_AVErrCode OH_AudioDecoder_Stop(OH_AVCodec *codec);
OH_AVErrCode OH_AudioDecoder_Flush(OH_AVCodec *codec);
OH_AVErrCode OH_AudioDecoder_Reset(OH_AVCodec *codec);
OH_AVErrCode OH_AudioDecoder_Destroy(OH_AVCodec *codec);
```

### 3.4 AudioEncoder API（native_avcodec_audioencoder.h）

```c
OH_AVCodec *OH_AudioEncoder_CreateByMime(const char *mime);
OH_AVCodec *OH_AudioEncoder_CreateByName(const char *name);

OH_AVErrCode OH_AudioEncoder_Configure(OH_AVCodec *codec, const OH_AVFormat *format);
OH_AVErrCode OH_AudioEncoder_Prepare(OH_AVCodec *codec);
OH_AVErrCode OH_AudioEncoder_Start(OH_AVCodec *codec);
OH_AVErrCode OH_AudioEncoder_Stop(OH_AVCodec *codec);
OH_AVErrCode OH_AudioEncoder_Flush(OH_AVCodec *codec);
OH_AVErrCode OH_AudioEncoder_Reset(OH_AVCodec *codec);
OH_AVErrCode OH_AudioEncoder_Destroy(OH_AVCodec *codec);

// AudioEncoder 特有
bool OH_AudioEncoder_IsValid(OH_AVCodec *codec, bool *isValid);  // 检查是否有效
```

### 3.5 AudioCodec 统一 API（native_avcodec_audiocodec.h）

```c
// 统一的 AudioCodec API，通过 isEncoder 参数区分编解码方向
OH_AVCodec *OH_AudioCodec_CreateByMime(const char *mime, bool isEncoder);  // isEncoder=true→编码器，false→解码器
OH_AVCodec *OH_AudioCodec_CreateByName(const char *name);

// 生命周期 API 与 AudioDecoder/AudioEncoder 相同
```

`OH_AudioCodec_*` 是 `OH_AudioDecoder_*` / `OH_AudioEncoder_*` 的超集，提供统一的 AudioCodec 创建接口。底层复用相同的 AudioCodecServer。

---

## 4. MIME 类型常量体系（67+ 类型）

```c
// native_avcodec_base.h:246-460
// 视频 MIME
extern const char *OH_AVCODEC_MIMETYPE_VIDEO_AVC;       // H.264/AVC
extern const char *OH_AVCODEC_MIMETYPE_VIDEO_HEVC;      // H.265/HEVC
extern const char *OH_AVCODEC_MIMETYPE_VIDEO_AV1;       // AV1
extern const char *OH_AVCODEC_MIMETYPE_VIDEO_VP8;       // VP8
extern const char *OH_AVCODEC_MIMETYPE_VIDEO_VP9;       // VP9
extern const char *OH_AVCODEC_MIMETYPE_VIDEO_MPEG4;     // MPEG-4 Part 2
extern const char *OH_AVCODEC_MIMETYPE_VIDEO_MPEG1;     // MPEG-1
extern const char *OH_AVCODEC_MIMETYPE_VIDEO_MPEG2;     // MPEG-2
extern const char *OH_AVCODEC_MIMETYPE_VIDEO_H263;      // H.263
extern const char *OH_AVCODEC_MIMETYPE_VIDEO_WMV3;      // WMV3
extern const char *OH_AVCODEC_MIMETYPE_VIDEO_WVC1;       // WVC1
extern const char *OH_AVCODEC_MIMETYPE_VIDEO_VC1;        // VC1
extern const char *OH_AVCODEC_MIMETYPE_VIDEO_MSVIDEO1;   // MS Video 1
extern const char *OH_AVCODEC_MIMETYPE_VIDEO_RV30;       // RealVideo 3.0
extern const char *OH_AVCODEC_MIMETYPE_VIDEO_RV40;       // RealVideo 4.0
extern const char *OH_AVCODEC_MIMETYPE_VIDEO_MJPEG;      // Motion JPEG
extern const char *OH_AVCODEC_MIMETYPE_VIDEO_DVVIDEO;    // DV Video
extern const char *OH_AVCODEC_MIMETYPE_VIDEO_RAWVIDEO;   // 原始视频
extern const char *OH_AVCODEC_MIMETYPE_VIDEO_VVC;        // H.266/VVC
extern const char *OH_AVCODEC_MIMETYPE_VIDEO_CINEPAK;    // Cinepak
extern const char *OH_AVCODEC_MIMETYPE_VIDEO_MPEG4_PART2; // MPEG-4 Part 2

// 音频 MIME
extern const char *OH_AVCODEC_MIMETYPE_AUDIO_AAC;       // AAC
extern const char *OH_AVCODEC_MIMETYPE_AUDIO_FLAC;      // FLAC
extern const char *OH_AVCODEC_MIMETYPE_AUDIO_VORBIS;     // Vorbis
extern const char *OH_AVCODEC_MIMETYPE_AUDIO_MPEG;       // MP3
extern const char *OH_AVCODEC_MIMETYPE_AUDIO_AMR_NB;     // AMR-NB
extern const char *OH_AVCODEC_MIMETYPE_AUDIO_AMR_WB;     // AMR-WB
extern const char *OH_AVCODEC_MIMETYPE_AUDIO_OPUS;       // Opus
extern const char *OH_AVCODEC_MIMETYPE_AUDIO_G711MU;     // G.711 μ-law
extern const char *OH_AVCODEC_MIMETYPE_AUDIO_LBVC;       // Low Bitrate Voice Codec
extern const char *OH_AVCODEC_MIMETYPE_AUDIO_APE;       // Monkey's Audio
extern const char *OH_AVCODEC_MIMETYPE_AUDIO_RAW;        // 原始 PCM
extern const char *OH_AVCODEC_MIMETYPE_AUDIO_VIVID;      // AudioVivid

// 图片 MIME
extern const char *OH_AVCODEC_MIMETYPE_IMAGE_JPG;
extern const char *OH_AVCODEC_MIMETYPE_IMAGE_PNG;
extern const char *OH_AVCODEC_MIMETYPE_IMAGE_BMP;

// 字幕 MIME
extern const char *OH_AVCODEC_MIMETYPE_SUBTITLE_SRT;
extern const char *OH_AVCODEC_MIMETYPE_SUBTITLE_WEBVTT;
```

---

## 5. Profile / Level 枚举体系

`native_avcodec_base.h` 中定义了 15+ 个 Profile/Level 枚举，支撑能力查询：

| 枚举 | 包含值 |
|------|--------|
| `OH_AVCProfile` | Baseline(66), Main(77), High(100), Extended, Constrained Baseline |
| `OH_HEVCProfile` | Main, Main_10, Main_10_StillPicture, ScreenExt |
| `OH_AV1Profile` | Main, High, Professional |
| `OH_AV1Level` | Level 2-13（共 12 级） |
| `OH_VP9Profile` | Profile 0, Profile 1, Profile 2, Profile 3 |
| `OH_MPEG2Profile` | SP, PP, SNR, Spatial, High |
| `OH_MPEG2Level` | Low, Main, High 1440, High |
| `OH_MPEG4Profile` | Simple, Advanced Simple, Advanced Real Time Simple |
| `OH_H263Profile` | Baseline, H320CODEC, Advanced Coding Efficiency |
| `OH_WMV3Profile` | Simple, Main |
| `OH_WVC1Profile` | Simple, Main, Professional |
| `OH_VVCProfile` | Main, Main_10, Main_10_StillPicture, MultiView, Scalable |
| `OH_VVCLevel` | 1-6（共 16 级） |

---

## 6. 回调驱动模型

### 6.1 OH_AVCodecCallback（Buffer 模式，推荐）

```c
// native_avcodec_base.h:170
typedef struct OH_AVCodecCallback {
    OH_AVCodecOnError;             // 错误回调（errorCode: OH_AVErrCode）
    OH_AVCodecOnStreamChanged;     // 流信息变更回调（format: OH_AVFormat*）
    OH_AVCodecOnNeedInputBuffer;   // 需要输入数据（index: buffer 索引）
    OH_AVCodecOnNewOutputBuffer;   // 输出新 buffer（index + OH_AVBuffer*）
} OH_AVCodecCallback;
```

### 6.2 OH_AVCodecAsyncCallback（Memory 模式，legacy）

```c
// native_avcodec_base.h:152
typedef struct OH_AVCodecAsyncCallback {
    OH_AVCodecOnError;
    OH_AVCodecOnStreamChanged;
    OH_AVCodecOnNeedInputData;     // 旧版 Memory 模式（OH_AVMemory*）
    OH_AVCodecOnNewOutputData;     // 旧版 Memory 模式
} OH_AVCodecAsyncCallback;
```

**双模式区别**：
- `OH_AVCodecCallback` 使用 `OH_AVBuffer`（推荐，携带元数据）
- `OH_AVCodecAsyncCallback` 使用 `OH_AVMemory`（legacy，AVBuffer attr 通过额外参数传递）

---

## 7. Demuxer / Muxer / Source API

### 7.1 Demuxer API（native_avdemuxer.h:261 行）

```c
// 通过 Source 创建 Demuxer
OH_AVDemuxer *OH_AVDemuxer_CreateWithSource(OH_AVSource *source);

// 轨道选择（解封装前需 SelectTrack）
OH_AVErrCode OH_AVDemuxer_SelectTrackByID(OH_AVDemuxer *demuxer, uint32_t trackIndex);
OH_AVErrCode OH_AVDemuxer_UnselectTrackByID(OH_AVDemuxer *demuxer, uint32_t trackIndex);

// 读样点（Buffer 模式）
OH_AVErrCode OH_AVDemuxer_ReadSampleBuffer(OH_AVDemuxer *demuxer, uint32_t trackIndex,
    OH_AVBuffer *buffer);

// 定位
OH_AVErrCode OH_AVDemuxer_SeekToTime(OH_AVDemuxer *demuxer, int64_t millisecond, OH_AVSeekMode mode);

// DRM 回调
OH_AVErrCode OH_AVDemuxer_SetDemuxerMediaKeySystemInfoCallback(
    OH_AVDemuxer *demuxer, DRM_MediaKeySystemInfoCallback callback);
```

### 7.2 Muxer API（native_avmuxer.h:192 行）

```c
// 创建（fd: 文件描述符，format: 输出格式）
OH_AVMuxer *OH_AVMuxer_Create(int32_t fd, OH_AVOutputFormat format);

// 配置
OH_AVErrCode OH_AVMuxer_SetRotation(OH_AVMuxer *muxer, int32_t rotation);
OH_AVErrCode OH_AVMuxer_SetFormat(OH_AVMuxer *muxer, OH_AVFormat *format);

// 写入流程
OH_AVErrCode OH_AVMuxer_AddTrack(OH_AVMuxer *muxer, int32_t *trackIndex, OH_AVFormat *trackFormat);
OH_AVErrCode OH_AVMuxer_Start(OH_AVMuxer *muxer);
OH_AVErrCode OH_AVMuxer_WriteSampleBuffer(OH_AVMuxer *muxer, uint32_t trackIndex, OH_AVBuffer *buffer);
OH_AVErrCode OH_AVMuxer_Stop(OH_AVMuxer *muxer);
OH_AVErrCode OH_AVMuxer_Destroy(OH_AVMuxer *muxer);
```

### 7.3 OH_AVOutputFormat 枚举（9 种封装格式）

```c
// native_avcodec_base.h:1822
typedef enum OH_AVOutputFormat {
    FORMAT_MPEG4 = 0,   // MP4/M4A
    FORMAT_AMR = 1,     // AMR
    FORMAT_MP3 = 2,     // MP3
    FORMAT_WAV = 3,     // WAV
    FORMAT_AAC = 4,     // AAC
    FORMAT_FLAC = 5,    // FLAC
    FORMAT_OGG = 6,     // OGG
    FORMAT_OPUS = 7,    // Opus
    FORMAT_AC3 = 8,     // AC3
    FORMAT_FLVDAT = 9,  // FLV
    FORMAT_MPEG2TS = 10, // MPEG-2 TS
    FORMAT_AAC_ADTS = 11, // AAC ADTS
} OH_AVOutputFormat;
```

---

## 8. Capability API（native_avcapability.h:572 行）

```c
// 获取所有编解码能力
OH_AVCapability *OH_AVCodec_GetCapabilityList();

// 按 MIME 类型查询解码能力
OH_AVCapability *OH_AVCodec_GetCapability(const char *mime, bool isEncoder);

// Capability 对象关键方法
bool OH_AVCapability_IsHardwareSupport(OH_AVCapability *capability);
char *OH_AVCapability_GetName(OH_AVCapability *capability);
char **OH_AVCapability_GetSupportedProfiles(OH_AVCapability *capability, int32_t *profileCount);
int32_t *OH_AVCapability_GetSupportedLevels(OH_AVCapability *capability, int32_t *levelCount);

// 查询能力属性（通过 OH_AVFormat Key）
//   VIDEO_MAX_WIDTH / VIDEO_MAX_HEIGHT / VIDEO_MAX_SURFACE_WIDTH / VIDEO_MAX_SURFACE_HEIGHT
//   VIDEO_SUPPORT_ENCODER_BITRATE_MODE / VIDEO_SUPPORT_ENCODER_TEMPORAL_LAYERS
//   SUPPORT_HDR_VIVID / IS_HARDWARE_SUPPORTED
```

---

## 9. CodecClient IPC 代理

### 9.1 CodecClient 定位

`CodecClient`（`services/services/codec/client/codec_client.cpp:704 行`）是应用层 C API 到系统服务 CodecServer 的 IPC 桥接器。应用层通过 `OH_VideoDecoder_CreateByMime` → `CodecClient::Init` → `IStandardCodecService`（Binder IPC）→ `CodecServer`。

```c
// codec_client.cpp:68-83
int32_t CodecClient::Create(const sptr<IStandardCodecService> &ipcProxy,
    std::shared_ptr<ICodecService> &codec)
{
    std::shared_ptr<CodecClient> codecClient = std::make_shared<CodecClient>(ipcProxy);
    codec = codecClient;
    return AVCS_ERR_OK;
}

// codec_client.cpp:83 - 构造函数保存 IPC 代理
CodecClient::CodecClient(const sptr<IStandardCodecService> &ipcProxy)
    : codecProxy_(ipcProxy)
{ }
```

### 9.2 服务端死亡回调

```c
// codec_client.cpp:102-111
void CodecClient::AVCodecServerDied()
{
    // 当 CodecServer SA 进程崩溃时，Binder 代理失效
    // 触发 onError(OH_AVCodec *codec, AV_ERR_SERVICE_DIED, userData)
    // 应用需销毁当前 OH_AVCodec 句柄并重新创建
}
```

### 9.3 CodecClient 与 CodecServiceProxy 关系

`CodecClient` 持有 `codecProxy_`（`CodecServiceProxy*`），通过 Binder 调用远程 `CodecServer` 上的服务方法。调用链：

```
应用层 OH_VideoDecoder_*()
  → CodecClient::Init()
    → CodecServiceProxy（客户端 Binder Proxy）
      → IPC (Binder Driver)
        → CodecServiceStub（服务端 Binder Stub）
          → CodecServer 方法实现
```

---

## 10. 错误码体系

```c
// interfaces/inner_api/native/avcodec_errors.h
// 服务端 CodecServiceErrCode → 客户端 OH_AVErrCode 转换
OH_AVErrCode AVCSErrorToOHAVErrCode(AVCodecServiceErrCode code);

// 常见 AV_ERR_*（通过 OH_AVCodecCallback::onError 回调传递）
AV_ERR_OK = 0;
AV_ERR_INVALID_VAL;      // 无效参数
AV_ERR_UNKNOWN;          // 未知错误
AV_ERR_NO_MEMORY;        // 内存不足
AV_ERR_SERVICE_DIED;    // 服务端死亡（ServerDiedCallback）
AV_ERR_NO_PERMISSION;    // 无权限
AV_ERR_OPERATE_NOT_ALLOWED;  // 操作不允许（如 Start 前未 Prepare）
AV_ERR_TIMEOUT;          // 超时

// VideoEncoder 特定
AV_ERR_VIDEO_UNSUPPORTED_COLOR_SPACE_CONVERSION;  // 不支持的色彩空间转换
```

---

## 11. 关联记忆条目

| 关联 | 说明 |
|------|------|
| `MEM-ARCH-AVCODEC-S2` | interfaces/kits/c/ API 使用场景与 key 搭配（已入库） |
| `MEM-ARCH-AVCODEC-S11` | HCodec CodecComponentManager 工厂与插件注册机制（pending_approval） |
| `MEM-ARCH-AVCODEC-S21` | AVCodec IPC 架构，CodecServiceProxy ↔ CodecServiceStub 双向代理（in_approval） |
| `MEM-ARCH-AVCODEC-S47` | CodecCapability 能力查询与匹配机制（pending_approval） |
| `MEM-ARCH-AVCODEC-S71` | CodecList 服务架构——三层能力查询体系（pending_approval） |

---

## 12. 快速参考

**VideoDecoder 三方接入最短路径**：
```c
// 1. 创建（按 MIME 自动选择硬件/软件解码器）
OH_AVCodec *dec = OH_VideoDecoder_CreateByMime("video/avc");

// 2. 注册回调
OH_AVCodecCallback cb = { .onError = MyOnError, .onStreamChanged = MyOnStreamChanged,
    .onNeedInputBuffer = MyOnNeedInput, .onNewOutputBuffer = MyOnNewOutput };
OH_AVDecoder_RegisterCallback(dec, &cb, userData);

// 3. Configure
OH_AVFormat *fmt = OH_AVFormat_Create();
OH_AVFormat_SetIntValue(fmt, "width", 1920);
OH_AVFormat_SetIntValue(fmt, "height", 1080);
OH_AVDecoder_Configure(dec, fmt);

// 4. Prepare → Start → 循环 PushInputBuffer/RenderOutputBuffer → Stop → Destroy
```

**关键约定**：
- `Configure` 前必须先 `RegisterCallback`
- `Start` 前必须先 `Prepare`
- `Flush` 不改变已注册的回调和 format
- `Reset` 后需重新 `Configure`
- `Destroy` 自动释放所有内部资源
