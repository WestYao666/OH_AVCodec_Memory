---
id: MEM-ARCH-AVCODEC-S23
title: SurfaceEncoderAdapter 视频编码器适配器——Surface模式输入与编码流程
type: architecture_fact
scope: [AVCodec, MediaEngine, Filter, SurfaceEncoderAdapter, SurfaceMode, VideoEncoder, FILTERTYPE_VENC]
status: draft
created_by: builder-agent
created_at: "2026-04-24T20:55:00+08:00"
updated_by: builder-agent
updated_at: "2026-04-24T20:55:00+08:00"
evidence_sources:
  - local_repo: /home/west/av_codec_repo
owner: 耀耀
review: pending
---

# MEM-ARCH-AVCODEC-S23: SurfaceEncoderAdapter 视频编码器适配器

## 概述

`SurfaceEncoderAdapter`（`services/media_engine/filters/surface_encoder_adapter.cpp`）是 **MediaEngine Filter 层的 Surface 模式视频编码适配器**，负责将相机/GPU Surface 的原始帧编码为压缩视频 bitstream。它是 `SurfaceDecoderAdapter` 的对称实现（编码端），桥接 MediaEngine Filter pipeline 与底层 `AVCodecVideoEncoder`（CodecServer）实例。

> **定位对照**：
> - `SurfaceDecoderAdapter`（解码）：Surface 输入 → 解码输出 Surface
> - `SurfaceEncoderAdapter`（编码）：Camera/GPU Surface 输入 → 编码 bitstream 输出

## 关键发现

- **双层适配架构**：`SurfaceEncoderFilter` 是 Filter 级别封装（注册为 `"builtin.recorder.videoencoder"`, `FilterType::FILTERTYPE_VENC`），`SurfaceEncoderAdapter` 是 Codec 级别适配器，持有 `shared_ptr<AVCodecVideoEncoder> codecServer_`
- **Surface 模式编码路径**：`Init` → `VideoEncoderFactory::CreateByMime(mime, format, codecServer_)` 创建底层编码器；`GetInputSurface()` → `codecServer_->CreateInputSurface()` 获取可写 Surface 供相机注入帧
- **四类回调体系**：`EncoderAdapterCallback`（错误/格式变化上报）、`EncoderAdapterKeyFramePtsCallback`（关键帧 PTS + 首帧 PTS 回调）、`DroppedFramesCallback`（`MediaCodecParameterWithAttrCallback`，丢帧参数属性通知）、`SurfaceEncoderAdapterCallback`（`MediaCodecCallback`，编码器原始回调）
- **TransCoder 模式**：`SetTransCoderMode()` 激活转码模式，启用 `TransCoderOnOutputBufferAvailable` 路径，禁用 `DroppedFramesCallback`
- **七状态 ProcessStateCode**：`IDLE → RECORDING → PAUSED → STOPPED`，独立于 CodecBase 的 CodecStatus 状态机（UNINITIALIZED/INITIALIZED/CONFIGURED/RUNNING/FLUSHED/EOS/ERROR）
- **ReleaseBuffer 后台线程**：`Start()` 时启动独立 Task 线程，循环等待 `releaseBufferCondition_`，批量释放编码器输出 buffer（`codecServer_->ReleaseOutputBuffer(index)`）
- **TemporalScalability 支持**：`ConfigureAboutEnableTemporalScale` 调用 `OH_MD_KEY_VIDEO_ENCODER_ENABLE_TEMPORAL_SCALABILITY` 参数
- **B-Frame 支持**：`SetVideoEnableBFrame` 控制 B-frame 使能；TransCoder 模式下通过 `AV_TRANSCODER_ENABLE_B_FRAME` 配置

---

## Architecture

### 分层架构

```
应用层（相机/录屏）
    ↓ 原始帧 Surface
SurfaceEncoderFilter（Filter 层，"builtin.recorder.videoencoder"）
    ↓ SetInputSurface / GetInputSurface
SurfaceEncoderAdapter（Codec 适配层）
    ↓ Init: VideoEncoderFactory::CreateByMime
AVCodecVideoEncoder / CodecServer（底层编码器实例）
    ↓ 编码后 bitstream
AVBufferQueueProducer（输出缓冲区队列）
    ↓ PushBuffer
下游 Filter（MuxerFilter / 复用器）
```

### 与 SurfaceDecoderAdapter 的对称关系

| 维度 | SurfaceDecoderAdapter | SurfaceEncoderAdapter |
|------|----------------------|----------------------|
| 方向 | 解码（输入 bitstream → 输出 Surface） | 编码（输入 Surface → 输出 bitstream） |
| Filter 注册名 | `"builtin.player.videodecoder"` | `"builtin.recorder.videoencoder"` |
| FilterType | FILTERTYPE_VDEC | FILTERTYPE_VENC |
| 底层工厂 | `VideoDecoderFactory::CreateByMime` | `VideoEncoderFactory::CreateByMime` |
| 输入 | bitstream（AVBuffer） | Surface（sptr<Surface>） |
| 输出 | Surface（GPU 渲染） | AVBufferQueue（编码 bitstream） |
| Surface 获取 | `SetOutputSurface` 由外部设置 | `GetInputSurface` 主动创建 |

---

## Key Components

### SurfaceEncoderAdapter（codec 适配层）

| 成员/方法 | 类型 | 作用 |
|----------|------|------|
| `codecServer_` | `shared_ptr<AVCodecVideoEncoder>` | 底层编码器实例 |
| `outputBufferQueueProducer_` | `sptr<AVBufferQueueProducer>` | 输出 bitstream 队列生产者 |
| `releaseBufferTask_` | `shared_ptr<Task>` | 后台 buffer 释放线程（"SurfaceEncoder"） |
| `curState_` | `ProcessStateCode` | 本地状态机：IDLE/RECORDING/PAUSED/STOPPED |
| `isTransCoderMode` | `bool` | 是否为转码模式 |
| `encoderAdapterCallback_` | `shared_ptr<EncoderAdapterCallback>` | Filter 层错误/格式变化回调 |
| `encoderAdapterKeyFramePtsCallback_` | `shared_ptr<EncoderAdapterKeyFramePtsCallback>` | 关键帧/首帧 PTS 回调 |
| `videoWidth_/videoHeight_` | `int32_t` | 配置的视频分辨率 |
| `videoFrameRate_` | `int32_t` | 配置的帧率 |
| `enableBFrame_` | `bool` | B-frame 使能标志 |
| `pauseResumeQueue_` | `deque<pair<int64_t, StateCode>>` | 暂停/恢复时间戳队列（用于 PTS 计算） |

### SurfaceEncoderFilter（Filter 层）

| 成员/方法 | 作用 |
|----------|------|
| `mediaCodec_`（`SurfaceEncoderAdapter`） | 持有的编码器适配器实例 |
| `surface_`（`sptr<Surface>`） | 输入 Surface 缓存 |
| `isTranscoderMode_` | 转发 `SurfaceEncoderAdapter::isTransCoderMode` |
| `Configure(parameter)` | 配置参数透传至 `mediaCodec_->Configure()` |
| `GetInputSurface()` | 优先返回缓存 `surface_`，否则从 `mediaCodec_->GetInputSurface()` 获取 |
| `DoPrepare()` | TransCoder 模式下回调 `NEXT_FILTER_NEEDED(STREAMTYPE_ENCODED_VIDEO)` |

### 回调类体系

| 回调类 | 父类 | 关键方法 |
|--------|------|---------|
| `SurfaceEncoderAdapterCallback` | `MediaCodecCallback` | `OnError` → `encoderAdapterCallback_->OnError`；`OnOutputBufferAvailable` → `SurfaceEncoderAdapter::OnOutputBufferAvailable` |
| `DroppedFramesCallback` | `MediaCodecParameterWithAttrCallback` | `OnInputParameterWithAttrAvailable` → `SurfaceEncoderAdapter::OnInputParameterWithAttrAvailable`（仅非 TransCoder 模式） |
| `EncoderAdapterCallback` | interface | `OnError`，`OnOutputFormatChanged` |
| `EncoderAdapterKeyFramePtsCallback` | interface | `OnReportKeyFramePts`，`OnReportFirstFramePts` |

---

## Data Flow

### 初始化流程

```
1. SurfaceEncoderFilter::Init()
   └─ mediaCodec_ = make_shared<SurfaceEncoderAdapter>()
   └─ mediaCodec_->SetCallingInfo(appUid, appPid, bundleName, instanceId)
   └─ mediaCodec_->Init(codecMimeType_, true)   // isEncoder=true
       └─ VideoEncoderFactory::CreateByMime(mime, format, codecServer_)
           └─ codecServer_ = AVCodecVideoEncoder instance
   └─ mediaCodec_->SetEncoderAdapterCallback(cb)
   └─ mediaCodec_->SetEncoderAdapterKeyFramePtsCallback(ptsCb)
```

### 配置流程（Configure）

```
SurfaceEncoderFilter::Configure(meta)
└─ mediaCodec_->Configure(parameter)
    └─ ConfigureGeneralFormat(format, meta)      // 宽/高/码率/帧率/MIME/Profile
    └─ ConfigureAboutRGBA(format, meta)           // 像素格式/码率模式
    └─ ConfigureAboutEnableTemporalScale(format, meta) // 时域可分级
    └─ ConfigureEnableFormat(format, meta)       // 水印使能
    └─ codecServer_->Configure(format)
```

### Surface 输入绑定流程

```
SurfaceEncoderFilter::SetInputSurface(surface)
└─ mediaCodec_->SetInputSurface(surface)   // 目前直接返回 OK

SurfaceEncoderFilter::GetInputSurface()
├─ 若 surface_ 已缓存 → 直接返回
└─ 若无 → mediaCodec_->GetInputSurface()
           └─ codecServer_->CreateInputSurface()   // 创建可写输入 Surface
```

### 编码输出流程（OnOutputBufferAvailable）

```
codecServer_->Start()
    └─ ReleaseBuffer Task 线程启动
    └─ codecServer_->Start()

编码器编码完成 → MediaCodecCallback::OnOutputBufferAvailable(index, buffer)
    └─ SurfaceEncoderAdapterCallback::OnOutputBufferAvailable
        └─ SurfaceEncoderAdapter::OnOutputBufferAvailable(index, buffer)
            ├─ [TransCoder 模式] → TransCoderOnOutputBufferAvailable
            └─ [普通编码模式]
                ├─ outputBufferQueueProducer_->RequestBuffer(...)   // 申请输出 buffer
                ├─ bufferMem->Write(encodedData)                    // 拷贝编码数据
                ├─ outputBuffer->pts_ = buffer->pts_ / NS_PER_US    // PTS 单位转换
                ├─ outputBufferQueueProducer_->PushBuffer(outputBuffer) // 推送下游
                └─ indexs_.push_back(index) + notify ReleaseBuffer 线程
                    └─ ReleaseBuffer 线程: codecServer_->ReleaseOutputBuffer(index)
```

### 生命周期状态

```
SurfaceEncoderAdapter ProcessStateCode:
  IDLE →（Start）→ RECORDING →（Pause）→ PAUSED →（Resume）→ RECORDING
                         ↓（Stop）        ↓（Stop）
                       STOPPED          STOPPED
                                   
CodecServer CodecStatus（独立状态机）:
  UNINITIALIZED →（Configure）→ CONFIGURED →（Start）→ RUNNING
      ↑                                              ↓（Stop）
    （Reset）                                   FLUSHED / END_OF_STREAM
      ↓                                              ↓（Release）
  UNINITIALIZED                              ERROR →（Reset）→ UNINITIALIZED
```

---

## Evidence

### SurfaceEncoderAdapter 核心文件

| 文件 | 关键代码位置 | 说明 |
|------|------------|------|
| `services/media_engine/filters/surface_encoder_adapter.cpp` | Line 123-137 | `Init`: `VideoEncoderFactory::CreateByMime` 创建 codecServer_ |
| `services/media_engine/filters/surface_encoder_adapter.cpp` | Line 150-194 | `ConfigureGeneralFormat`: 宽/高/码率/帧率/MIME/Profile 配置 |
| `services/media_engine/filters/surface_encoder_adapter.cpp` | Line 205-243 | `Configure`: 组合 ConfigureGeneralFormat + ConfigureAboutRGBA + ConfigureAboutEnableTemporalScale + ConfigureEnableFormat |
| `services/media_engine/filters/surface_encoder_adapter.cpp` | Line 282-286 | `SetOutputBufferQueue`: 设置输出 AVBufferQueue |
| `services/media_engine/filters/surface_encoder_adapter.cpp` | Line 317-328 | `SetInputSurface` / `GetInputSurface`: Surface 绑定 |
| `services/media_engine/filters/surface_encoder_adapter.cpp` | Line 329-338 | `GetInputSurface`: `codecServer_->CreateInputSurface()` |
| `services/media_engine/filters/surface_encoder_adapter.cpp` | Line 335-360 | `Start`: 清状态 + 启动 ReleaseBuffer Task + `codecServer_->Start()` |
| `services/media_engine/filters/surface_encoder_adapter.cpp` | Line 363-407 | `Stop`: 发送停止信号 + HandleWaitforStop + 停止 ReleaseBuffer Task |
| `services/media_engine/filters/surface_encoder_adapter.cpp` | Line 418-439 | `Pause`: 记录暂停 PTS 到 `pauseResumePts_` |
| `services/media_engine/filters/surface_encoder_adapter.cpp` | Line 441-472 | `Resume`: 计算总暂停时长，调整后续 PTS |
| `services/media_engine/filters/surface_encoder_adapter.cpp` | Line 601-646 | `OnOutputBufferAvailable`: 普通编码模式下的输出 buffer 处理 + ReleaseBuffer 通知 |
| `services/media_engine/filters/surface_encoder_adapter.cpp` | Line 648-680 | `ReleaseBuffer`: 后台 Task 线程，批量调用 `codecServer_->ReleaseOutputBuffer` |
| `services/media_engine/filters/surface_encoder_adapter.cpp` | Line 683-698 | `ConfigureAboutRGBA`: 像素格式 + 码率模式 |
| `services/media_engine/filters/surface_encoder_adapter.cpp` | Line 700-720 | `ConfigureAboutEnableTemporalScale`: `OH_MD_KEY_VIDEO_ENCODER_ENABLE_TEMPORAL_SCALABILITY` |
| `services/media_engine/filters/surface_encoder_adapter.h` | Line 47-54 | `ProcessStateCode`: IDLE/RECORDING/PAUSED/STOPPED 枚举 |
| `services/media_engine/filters/surface_encoder_adapter.h` | Line 59-66 | `EncoderAdapterCallback` / `EncoderAdapterKeyFramePtsCallback` 接口定义 |
| `services/media_engine/filters/surface_encoder_adapter.h` | Line 68-158 | `SurfaceEncoderAdapter` 类完整声明 |

### SurfaceEncoderFilter 文件

| 文件 | 关键代码位置 | 说明 |
|------|------------|------|
| `services/media_engine/filters/surface_encoder_filter.cpp` | Line 37-41 | `AutoRegisterFilter`: 注册为 `"builtin.recorder.videoencoder"`, `FilterType::FILTERTYPE_VENC` |
| `services/media_engine/filters/surface_encoder_filter.cpp` | Line 168-189 | `Init`: 创建 `SurfaceEncoderAdapter` + 设置回调链 |
| `services/media_engine/filters/surface_encoder_filter.cpp` | Line 233-240 | `Configure`: 参数透传 |
| `services/media_engine/filters/surface_encoder_filter.cpp` | Line 250-258 | `SetInputSurface` / `GetInputSurface`: Surface 绑定 |
| `services/media_engine/filters/surface_encoder_filter.cpp` | Line 265-276 | `DoPrepare`: TransCoder 模式返回 `NEXT_FILTER_NEEDED(STREAMTYPE_ENCODED_VIDEO)` |
| `services/media_engine/filters/surface_encoder_filter.cpp` | Line 280-295 | `DoStart`: 调用 `mediaCodec_->Start()` |

### 工厂与接口

| 文件 | 说明 |
|------|------|
| `interfaces/inner_api/native/avcodec_video_encoder.h` Line 337 | `VideoEncoderFactory::CreateByMime` 声明 |
| `interfaces/inner_api/native/avcodec_video_encoder.h` Line 413 | `VideoEncoderFactory` 析构 |

---

## Related

### 直接关联

| 记忆ID | 标题 | 关系 |
|--------|------|------|
| MEM-ARCH-AVCODEC-S16 | SurfaceCodec 与 Surface 的绑定机制 | Decoder 侧对应关系（SurfaceDecoderAdapter） |
| MEM-ARCH-AVCODEC-020 | AudioDecoderAdapter 音频解码适配器 | 对称架构（编码 vs 解码，音频 vs 视频） |
| MEM-ARCH-AVCODEC-S14 | MediaEngine Filter Chain 架构 | SurfaceEncoderFilter 在 Filter Chain 中的位置 |
| MEM-ARCH-AVCODEC-S19 | TemporalScalability 时域可分级视频编码 | SurfaceEncoderAdapter 支持 TemporalScalability |
| MEM-ARCH-AVCODEC-S3 | CodecServer Pipeline 数据流与状态机 | codecServer_ 的 CodecStatus 状态机 |

### 平行 Filter（Filter Pipeline 编码侧）

| Filter | 注册名 | 类型 | 说明 |
|--------|--------|------|------|
| `SurfaceEncoderFilter` | `"builtin.recorder.videoencoder"` | FILTERTYPE_VENC | Surface 模式视频编码 |
| `VideoEncoderFilter` | ? | FILTERTYPE_VENC | Buffer 模式视频编码 |
| `AudioEncoderFilter` | `"builtin.recorder.audioencoder"` | FILTERTYPE_AENC | 音频编码 |
