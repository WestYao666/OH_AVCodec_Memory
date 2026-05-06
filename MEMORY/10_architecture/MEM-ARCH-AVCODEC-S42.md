---
status: approved
approved_at: "2026-05-06"
mem_id: MEM-ARCH-AVCODEC-S42
title: "AVCodecVideoEncoder 视频编码器核心实现——CodecBase/VideoEncoder/VideoEncoderAdapter 三层架构"
scope: [AVCodec, VideoEncoder, CodecBase, VideoEncoderAdapter, Filter, SurfaceEncoderAdapter, SoftwareCodec, HardwareCodec]
created_at: "2026-04-26T00:10:00+08:00"
created_by: builder-agent-S42
---

# AVCodecVideoEncoder 视频编码器核心实现——三层架构

## 概述

AVCodec 视频编码器采用 **Filter 层 → Codec 层 → Engine 层** 三层插件架构，从 MediaEngine Filter 管线到底层编码引擎逐层封装。

---

## 三层调用链总览

```
MediaEngine Filter Pipeline
└── SurfaceEncoderAdapter (Filter层, OHOS::Media)
    └── AVCodecVideoEncoder (Codec层接口, OHOS::MediaAVCodec)
        └── VideoEncoder (Engine层实现, Codec::VideoEncoder)
            ├── H264EncoderPlugin (硬件/软件编码插件)
            ├── H265EncoderPlugin
            └── VPXEncoderPlugin
```

---

## Evidence

### E1: SurfaceEncoderAdapter 过滤器层

**文件**: `services/media_engine/filters/surface_encoder_adapter.h`

`SurfaceEncoderAdapter` 是 Filter 管线中的编码器适配器，持有 `codecServer_` (AVCodecVideoEncoder)：

```cpp
class SurfaceEncoderAdapter : public std::enable_shared_from_this<SurfaceEncoderAdapter> {
    std::shared_ptr<MediaAVCodec::AVCodecVideoEncoder> codecServer_;
    std::shared_ptr<Task> releaseBufferTask_{nullptr};
    ProcessStateCode curState_{ProcessStateCode::IDLE};
    // 五状态机: IDLE → RECORDING → PAUSED → STOPPED → ERROR
```

- 注册名: `builtin.recorder.videoencoder` (FILTERTYPE_VENC)
- ProcessStateCode 五状态: `IDLE / RECORDING / PAUSED / STOPPED / ERROR`
- ReleaseBuffer 后台线程异步释放输出Buffer
- PTS ns→μs 转换
- 支持 SetTransCoderMode 转码模式

**来源**: `surface_encoder_adapter.h` 行 15-100

---

### E2: AVCodecVideoEncoder 公共接口层

**文件**: `interfaces/inner_api/native/avcodec_video_encoder.h`

`AVCodecVideoEncoder` 是纯虚接口类，定义编码器生命周期方法：

```cpp
class AVCodecVideoEncoder {
    virtual int32_t Configure(const Format &format) = 0;
    virtual int32_t Prepare() = 0;
    virtual int32_t Start() = 0;
    virtual int32_t Stop() = 0;
    virtual int32_t Flush() = 0;
    virtual int32_t NotifyEos() = 0;
    virtual int32_t Reset() = 0;
    virtual int32_t Release() = 0;
    virtual sptr<Surface> CreateInputSurface() = 0;
    virtual int32_t QueueInputBuffer(uint32_t index, AVCodecBufferInfo info, AVCodecBufferFlag flag) = 0;
    virtual int32_t ReleaseOutputBuffer(uint32_t index) = 0;
    virtual int32_t SetParameter(const Format &format) = 0;
    virtual int32_t GetOutputFormat(Format &format) = 0;
    virtual int32_t GetInputFormat(Format &format) = 0;
    virtual int32_t SetCallback(const std::shared_ptr<MediaCodecCallback> &callback) = 0;
    virtual int32_t SetCustomBuffer(std::shared_ptr<AVBuffer> buffer) = 0;
    virtual int32_t QueryInputBuffer(uint32_t &index, int64_t timeoutUs) = 0;
    virtual int32_t QueryOutputBuffer(uint32_t &index, int64_t timeoutUs) = 0;
    virtual std::shared_ptr<AVBuffer> GetInputBuffer(uint32_t index) = 0;
    virtual std::shared_ptr<AVBuffer> GetOutputBuffer(uint32_t index) = 0;
```

- 命名空间: `OHOS::MediaAVCodec`
- 创建工厂: `VideoEncoderFactory::CreateByMime()` / `CreateByName()`
- SetCallback 支持三种回调: AVCodecCallback (旧) / MediaCodecCallback / MediaCodecParameterCallback / MediaCodecParameterWithAttrCallback

**来源**: `avcodec_video_encoder.h` 行 20-210

---

### E3: VideoEncoderFactory 双工厂创建方法

**文件**: `interfaces/inner_api/native/avcodec_video_encoder.h`

```cpp
class VideoEncoderFactory {
    static std::shared_ptr<AVCodecVideoEncoder> CreateByMime(const std::string &mime);
    static std::shared_ptr<AVCodecVideoEncoder> CreateByName(const std::string &name);
    static int32_t CreateByMime(const std::string &mime, Format &format,
                                std::shared_ptr<AVCodecVideoEncoder> &encodec);
    static int32_t CreateByName(const std::string &name, Format &format,
                                std::shared_ptr<AVCodecVideoEncoder> &encodec);
```

- CreateByMime: 按 MIME 类型创建首选编码器
- CreateByName: 按具体编码器名称创建
- Format 参数用于传递调用者信息

**来源**: `avcodec_video_encoder.h` 行 216-240

---

### E4: VideoEncoder 基类 (Engine 层)

**文件**: `services/engine/codec/video/decoderbase/video_decoder.h`

VideoDecoder 基类示例展示了 CodecBase + RenderSurface 双继承模式，VideoEncoder 应为类似结构：

```cpp
class VideoDecoder : public RenderSurface, public CodecBase {
    std::shared_ptr<MediaCodecCallback> callback_;
    std::shared_ptr<TaskThread> sendTask_ = nullptr;
    std::atomic<bool> isSendEos_ = false;
    std::shared_ptr<BlockQueue<uint32_t>> inputAvailQue_;
    sptr<Surface> surface_ = nullptr;
    virtual int32_t DecodeFrameOnce() = 0;
    virtual void SendFrame() = 0;
    virtual void InitParams() = 0;
    virtual int32_t Initialize() = 0;
    virtual void ConfigureOutPutOrder(bool isDisplay) {};
    virtual void ConfigureHdrColorSpaceIno(const Format &format) {};
    virtual void ConfigureHdrStaticMetadata(const Format &format) {};
```

- CodecBase 提供标准Codec生命周期
- RenderSurface 提供 Surface 渲染能力
- BlockQueue 三队列: inputAvailQue / codecAvailQue / renderAvailQue
- sendTask_ 发送帧线程

**来源**: `video_decoder.h` 行 35-110

---

### E5: CodecBase 抽象基类

**文件**: `services/engine/base/include/codecbase.h`

所有编解码器继承自 CodecBase，定义统一接口：

```cpp
class CodecBase {
    virtual int32_t Configure(const Format &format) = 0;
    virtual int32_t Start() = 0;
    virtual int32_t Stop() = 0;
    virtual int32_t Flush() = 0;
    virtual int32_t Reset() = 0;
    virtual int32_t Release() = 0;
    virtual int32_t SetParameter(const Format &format) = 0;
    virtual int32_t GetOutputFormat(Format &format) = 0;
    virtual int32_t ReleaseOutputBuffer(uint32_t index) = 0;
    virtual int32_t NotifyEos();
    virtual sptr<Surface> CreateInputSurface();
    virtual int32_t SetInputSurface(sptr<Surface> surface);
    virtual int32_t SetOutputSurface(sptr<Surface> surface);
    virtual int32_t RenderOutputBuffer(uint32_t index);
    virtual int32_t SignalRequestIDRFrame();
    virtual int32_t SetCustomBuffer(std::shared_ptr<AVBuffer> buffer);
    virtual int32_t NotifyMemoryRecycle();
    virtual int32_t NotifySuspend();
    virtual int32_t NotifyResume();
    virtual int32_t ChangePlugin(const std::string &mime, bool isEncoder,
                                const std::shared_ptr<Media::Meta> &meta);
    virtual int32_t SetOutputBufferQueue(const sptr<Media::AVBufferQueueProducer> &bufferQueueProducer);
    virtual sptr<Media::AVBufferQueueProducer> GetInputBufferQueue();
    virtual void ProcessInputBuffer();
```

- 命名空间: `OHOS::MediaAVCodec`
- 支持 Surface 模式: CreateInputSurface / SetInputSurface / SetOutputSurface
- 支持 AVBufferQueue: GetInputBufferQueue / SetOutputBufferQueue / ProcessInputBuffer
- 支持插件热切换: ChangePlugin

**来源**: `codecbase.h` 行 20-130

---

### E6: HevcDecoder 具体实现示例

**文件**: `services/engine/codec/video/hevcdecoder/hevc_decoder.h`

HEVC 解码器继承 VideoDecoder，展示具体编解码器实现：

```cpp
class HevcDecoder : public VideoDecoder {
    void* handle_ = nullptr;
    HEVC_DEC_INIT_PARAM initParams_;
    HEVC_DEC_INARGS hevcDecoderInputArgs_;
    HEVC_DEC_OUTARGS hevcDecoderOutpusArgs_;
    HEVC_DEC_HANDLE hevcSDecoder_ = nullptr;

    using CreateHevcDecoderFuncType = INT32 (*)(HEVC_DEC_HANDLE *phDecoder, HEVC_DEC_INIT_PARAM *pstInitParam);
    using DecodeFuncType = INT32 (*)(HEVC_DEC_HANDLE hDecoder, HEVC_DEC_INARGS *pstInArgs, HEVC_DEC_OUTARGS *pstOutArgs);
    using FlushFuncType = INT32 (*)(HEVC_DEC_HANDLE hDecoder, HEVC_DEC_OUTARGS *pstOutArgs);
    using DeleteFuncType = INT32 (*)(HEVC_DEC_HANDLE hDecoder);
```

- 函数指针类型通过 dlopen 加载编码库动态绑定
- H.265 硬编解码器通过 HDF (Hardware Driver Framework) 调用

**来源**: `hevc_decoder.h` 行 30-90

---

### E7: VpxDecoder 多格式支持

**文件**: `services/engine/codec/video/vpxdecoder/vpxDecoder.h`

VPX 解码器支持 VP8/VP9：

```cpp
class VpxDecoder : public VideoDecoder {
    VPX_DEC_HANDLE vpxDecHandle_ = nullptr;
    vpx_image_t *vpxDecOutputImg_ = nullptr;
    static void GetVp9CapProf(std::vector<CapabilityData> &capaArray);
    static void GetVp8CapProf(std::vector<CapabilityData> &capaArray);

    struct HdrMetadata { /* mastering display metadata */ };
    struct ColorSpaceInfo { /* color description fields */ };
    AVPixelFormat ConvertVpxFmtToAVPixFmt(vpx_img_fmt_t fmt);
```

- libvpx 软件编解码器 (FFmpeg 生态)
- 支持 HDR 元数据提取和转换
- 色彩空间信息转换

**来源**: `vpxDecoder.h` 行 30-90

---

### E8: SurfaceDecoderAdapter Filter 层实现

**文件**: `services/media_engine/filters/surface_decoder_adapter.h`

`SurfaceDecoderAdapter` 是 Filter 层解码器，持有 `codecServer_`：

```cpp
class SurfaceDecoderAdapter : public std::enable_shared_from_this<SurfaceDecoderAdapter> {
    std::shared_ptr<MediaAVCodec::AVCodecVideoDecoder> codecServer_;
    std::shared_ptr<Media::AVBufferQueue> inputBufferQueue_;
    sptr<Media::AVBufferQueueProducer> inputBufferQueueProducer_;
    sptr<Media::AVBufferQueueConsumer> inputBufferQueueConsumer_;
    std::shared_ptr<Task> releaseBufferTask_{nullptr};
    std::atomic<int64_t> frameNum_ = 0;
    std::atomic<bool> isThreadExit_ = true;
```

- 注册名: `builtin.player.videodecoder`
- 通过 AVBufferQueue 与上游 Filter 通信
- ReleaseBuffer 异步后台线程

**来源**: `surface_decoder_adapter.h` 行 40-80

---

### E9: VideoDecoderAdapter Filter 层实现

**文件**: `interfaces/inner_api/native/video_decoder_adapter.h`

`VideoDecoderAdapter` 是 Filter 层解码器适配器：

```cpp
class VideoDecoderAdapter : public std::enable_shared_from_this<VideoDecoderAdapter> {
    std::shared_ptr<MediaAVCodec::AVCodecVideoDecoder> mediaCodec_;
    std::shared_ptr<Media::AVBufferQueue> inputBufferQueue_;
    sptr<Media::AVBufferQueueProducer> inputBufferQueueProducer_;
    sptr<Media::AVBufferQueueConsumer> inputBufferQueueConsumer_;
    void OnInputBufferAvailable(uint32_t index, std::shared_ptr<AVBuffer> buffer);
    void OnOutputBufferAvailable(uint32_t index, std::shared_ptr<AVBuffer> buffer);
```

- 通过 MediaCodecCallback 接收 AVCodecVideoDecoder 事件
- 转发到 Pipeline::EventReceiver

**来源**: `video_decoder_adapter.h` 行 25-65

---

### E10: CodecFactory 单例工厂

**文件**: `services/services/codec/server/video/codec_factory.h`

```cpp
class CodecFactory {
    static CodecFactory &Instance();
    std::vector<std::string> GetCodecNameArrayByMime(const AVCodecType type, const std::string &mime);
    std::shared_ptr<CodecBase> CreateCodecByName(const std::string &name);
```

- 单例模式: `Instance()`
- 按 MIME 类型查询可用编码器列表
- 按名称创建具体 CodecBase 实例

**来源**: `codec_factory.h` 行 15-30

---

### E11: CodecServer 服务层（七状态机）

**文件**: `services/services/codec/server/video/codec_server.h`

CodecServer 是 IPC 服务端代理，实现 ICodecService 接口：

```cpp
class CodecServer : public std::enable_shared_from_this<CodecServer>,
                    public ICodecService {
    enum CodecStatus {
        UNINITIALIZED = 0,
        INITIALIZED,
        CONFIGURED,
        RUNNING,
        FLUSHED,
        END_OF_STREAM,
        ERROR,
    };
    std::shared_ptr<CodecBase> codecBase_;
```

- 七状态机: UNINITIALIZED → INITIALIZED → CONFIGURED → RUNNING → FLUSHED/END_OF_STREAM/ERROR
- 持有 codecBase_ 指向具体编码器实例

**来源**: `codec_server.h` 行 35-60

---

### E12: 编码器能力查询 (CodecCapability)

**文件**: `interfaces/inner_api/native/avcodec_video_encoder.h`

VideoEncoderFactory 提供能力查询：

```cpp
static int32_t CreateByMime(const std::string &mime, Format &format,
                            std::shared_ptr<AVCodecVideoEncoder> &encodec);
static int32_t CreateByName(const std::string &name, Format &format,
                            std::shared_ptr<AVCodecVideoEncoder> &encodec);
```

- 能力通过 CodecList 服务 (SA) 获取
- Format 参数携带调用者信息用于权限校验

**来源**: `avcodec_video_encoder.h` 行 220-235

---

### E13: AVBuffer 接口 (Codec 数据单元)

**文件**: `interfaces/inner_api/native/avcodec_video_encoder.h`

编码器输入输出以 AVBuffer 为数据单元：

```cpp
virtual int32_t SetCustomBuffer(std::shared_ptr<AVBuffer> buffer) = 0;
virtual std::shared_ptr<AVBuffer> GetInputBuffer(uint32_t index);
virtual std::shared_ptr<AVBuffer> GetOutputBuffer(uint32_t index);
```

- AVBuffer 包含: 数据指针、元数据（PTS/DTS）、内存描述符
- 支持 QueryInputBuffer / QueryOutputBuffer 轮询模式

**来源**: `avcodec_video_encoder.h` 行 175-210

---

### E14: Native C API 封装

**文件**: `interfaces/kits/c/native_avcodec_videoencoder.h`

Native C API 提供给应用调用：

```cpp
// 应用层调用链
OH_AVCodec *OH_VideoEncoder_CreateByMime(const char *mime);
OH_AVCodec *OH_VideoEncoder_CreateByName(const char *name);
int32_t OH_VideoEncoder_Configure(OH_AVCodec *codec, OH_AVFormat *format);
int32_t OH_VideoEncoder_Start(OH_AVCodec *codec);
int32_t OH_VideoEncoder_Stop(OH_AVCodec *codec);
int32_t OH_VideoEncoder_PushInputData(OH_AVCodec *codec, uint32_t index,
                                       OH_AVCodecBufferInfo info, OH_AVCodecBufferFlag flag);
int32_t OH_VideoEncoder_FreeOutputData(OH_AVCodec *codec, uint32_t index);
```

- 命名空间: `OHOS::MediaAVCodec` → C API wrapper
- Format 使用 OH_AVFormat 传递编解码参数

**来源**: `native_avcodec_videoencoder.h` (内联 API 声明)

---

### E15: Surface 模式与 Buffer 模式互斥

**文件**: `services/media_engine/filters/surface_encoder_adapter.h`

编码器支持两种输入模式：

```cpp
Status SetInputSurface(sptr<Surface> surface);  // Surface 模式
Status SetOutputBufferQueue(const sptr<AVBufferQueueProducer> &bufferQueueProducer);  // Buffer 模式
```

- Surface 模式: CreateInputSurface() → sptr<Surface> → 输入到编码器
- Buffer 模式: AVBufferQueue → PushBuffer 循环
- Surface/Buffer 双模式互斥，Configure 时确定，运行时不可切换

**来源**: `surface_encoder_adapter.h` 行 60-70

---

### E16: TemporalScalability 时域可分级支持

**文件**: `services/services/codec/server/video/codec_server.h`

CodecServer 持有时域可分级编码器：

```cpp
#include "temporal_scalability.h"
class CodecServer {
    std::shared_ptr<CodecBase> codecBase_;
    // SVC-TL: 时域可分级
    // SVC-LTR: 长期参考帧
```

- 编码器支持 temporalGopSize / tRefMode 参数
- 通过 CodecParamChecker 七步校验链验证

**来源**: `codec_server.h` 行 15-30

---

### E17: SmartFluencyDecoding 智能流畅解码

**文件**: `services/services/codec/server/video/codec_server.h`

CodecServer 集成智能丢帧：

```cpp
#include "smart_fluency_decoding_manager.h"
class CodecServer {
    std::shared_ptr<SmartFluencyDecodingManager> smartFluencyDecodingManager_;
```

- IRetentionStrategy 四策略: FULL / ADAPTIVE / FIXED_RATIO / AUTO_RATIO
- MV/Nalu 双分析器 (dlopen 插件)
- AsyncDropDispatcher 异步丢帧

**来源**: `codec_server.h` 行 20-25

---

### E18: 编码器实例 ID 管理

**文件**: `services/engine/codec/video/decoderbase/video_decoder.h`

编码器实例通过静态集合管理：

```cpp
class VideoDecoder {
    static std::mutex decoderCountMutex_;
    static std::vector<uint32_t> freeIDSet_;
    uint32_t decInstanceID_ = 0;
    static std::vector<uint32_t> decInstanceIDSet_;
    bool isValid_ = true;
    std::string codecName_;
```

- freeIDSet_ 管理空闲实例 ID 池
- decInstanceIDSet_ 记录所有活跃实例
- isValid_ 标志编码器是否有效

**来源**: `video_decoder.h` 行 40-55

---

### E19: RenderSurface 基类能力

**文件**: `services/engine/codec/video/decoderbase/video_decoder.h`

VideoDecoder 继承 RenderSurface，提供 Surface 渲染能力：

```cpp
class VideoDecoder : public RenderSurface, public CodecBase {
    void FramePostProcess(const std::shared_ptr<CodecBuffer> &frameBuffer, uint32_t index, int32_t status);
    int32_t FillFrameBuffer(const std::shared_ptr<CodecBuffer> &frameBuffer);
    int32_t UpdateOutputBuffer(uint32_t index);
    int32_t UpdateSurfaceMemory(uint32_t index);
    int32_t GetSurfaceBufferStride(const std::shared_ptr<CodecBuffer> &frameBuffer);
    void SetSurfaceParameter();
```

- FramePostProcess: 解码后帧后处理（色域转换/HDR映射）
- Surface 内存分配和更新
- 支持 HDR 元数据注入

**来源**: `video_decoder.h` 行 50-80

---

### E20: 错误处理与回调体系

**文件**: `interfaces/inner_api/native/avcodec_video_decoder.h`

编码器通过回调报告事件：

```cpp
virtual int32_t SetCallback(const std::shared_ptr<AVCodecCallback> &callback) = 0;
virtual int32_t SetCallback(const std::shared_ptr<MediaCodecCallback> &callback) = 0;
// MediaCodecCallback 定义:
void OnError(MediaAVCodec::AVCodecErrorType errorType, int32_t errorCode);
void OnOutputFormatChanged(const MediaAVCodec::Format &format);
void OnInputBufferAvailable(uint32_t index, std::shared_ptr<AVBuffer> buffer);
void OnOutputBufferAvailable(uint32_t index, std::shared_ptr<AVBuffer> buffer);
```

- AVCodecErrorType: 错误类型分类
- 异步事件驱动模型

**来源**: `avcodec_video_decoder.h` 行 180-220

---

## 架构总结

### 三层职责

| 层级 | 类名 | 命名空间 | 职责 |
|------|------|----------|------|
| Filter 层 | SurfaceEncoderAdapter | Media | Filter 管线集成，PTS 管理，五状态机 |
| Codec 层 | AVCodecVideoEncoder | MediaAVCodec | 公共接口定义，工厂创建 |
| Engine 层 | VideoEncoder (基类) | Codec | CodecBase 生命周期，BlockQueue，Surface 渲染 |

### 工厂创建路径

```
VideoEncoderFactory::CreateByMime("video/hevc")
  → CodecFactory::Instance().CreateCodecByName("OH.Media.Codec.Encoder.Audio ...)
  → CodecServer (ICodecService 代理)
  → VideoEncoder (Engine 层)
```

### 对比 S39 (VideoDecoder)

| 维度 | VideoDecoder (S39) | VideoEncoder (S42) |
|------|-------------------|-------------------|
| 基类 | RenderSurface + CodecBase | RenderSurface + CodecBase |
| 输入 | AVBuffer / Surface | Surface (CreateInputSurface) / AVBuffer |
| 输出 | Surface / AVBuffer | AVBuffer |
| 状态 | 十一状态 (UNINIT..FROZEN) | 七状态 (CodecServer) + 五状态 (Adapter) |
| 丢帧 | SmartFluencyDecoding | SmartFluencyDecoding (编码侧适应性) |
| Seek | 不适用 | 不适用 |

---

## 关联记忆

- S39: `MEM-ARCH-AVCODEC-S39` — AVCodecVideoDecoder 三层架构（Decoder 对应主题）
- S36: `MEM-ARCH-AVCODEC-S36` — VideoEncoderFilter (SurfaceEncoderAdapter)
- S14: `MEM-ARCH-AVCODEC-S14` — Filter Chain 整体架构
- S21: `MEM-ARCH-AVCODEC-S21` — AVCodec IPC 架构
- P1f: `MEM-ARCH-AVCODEC-014` — Codec Engine 架构 (CodecBase+Loader+Factory)
