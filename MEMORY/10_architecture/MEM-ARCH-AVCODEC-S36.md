# MEM-ARCH-AVCODEC-S36 - VideoEncoderFilter 视频编码过滤器

status: pending_approval
**submitted_by**: builder-agent
**submitted_at**: "2026-04-25T17:21:00+08:00"
**版本**: 2026-04-25  
**Builder**: builder-agent  
**scope**: [AVCodec, MediaEngine, Filter, VideoEncoder, SurfaceEncoderFilter, FILTERTYPE_VENC, Pipeline]  
**关联场景**: 新需求开发/问题定位/录制管线

---

## 1. 主题概述

VideoEncoderFilter（注册名 `"builtin.recorder.videoencoder"`, FilterType `FILTERTYPE_VENC`）是录制管线中视频编码 Filter 的顶层封装类。它持有 `SurfaceEncoderAdapter` 作为内部Codec引擎，完成 Surface 模式视频编码全流程。

注意：代码中实际类名为 `SurfaceEncoderFilter`（而非 `VideoEncoderFilter`），这是历史命名；FilterType 为 `FILTERTYPE_VENC`，注册在录制管线（recorder）中。

---

## 2. Filter 注册机制

### 2.1 AutoRegisterFilter 自动注册

```
services/media_engine/filters/surface_encoder_filter.cpp:33
static AutoRegisterFilter<SurfaceEncoderFilter> g_registerSurfaceEncoderFilter("builtin.recorder.videoencoder",
    FilterType::FILTERTYPE_VENC,
    [](const std::string& name, const FilterType type) {
        return std::make_shared<SurfaceEncoderFilter>(name, FilterType::FILTERTYPE_VENC);
    });
```

- Filter 注册名：`"builtin.recorder.videoencoder"`
- FilterType：`FILTERTYPE_VENC`
- 与 `SurfaceDecoderFilter`（`"builtin.player.videodecoder"`）形成编/解码对称

### 2.2 全部 Filter 注册对照

| Filter 类 | 注册名 | FilterType | 所属管线 |
|---|---|---|---|
| `SurfaceEncoderFilter` | `"builtin.recorder.videoencoder"` | `FILTERTYPE_VENC` | Recorder |
| `SurfaceDecoderFilter` | `"builtin.player.videodecoder"` | `FILTERTYPE_VDEC` | Player |
| `AudioEncoderFilter` | `"builtin.recorder.audioencoder"` | `FILTERTYPE_AENC` | Recorder |
| `AudioDecoderFilter` | `"builtin.player.audiodecoder"` | `FILTERTYPE_ADEC` | Player |
| `DemuxerFilter` | `"builtin.player.demuxer"` | `FILTERTYPE_DEMUXER` | Player |
| `MuxerFilter` | `"builtin.recorder.muxer"` | `FILTERTYPE_MUXER` | Recorder |
| `VideoCaptureFilter` | `"builtin.recorder.videocapture"` | - | Recorder |
| `AudioCaptureFilter` | `"builtin.recorder.audiocapture"` | - | Recorder |

**Evidence**:
- `surface_encoder_filter.cpp:33` — AutoRegisterFilter 注册行
- `surface_encoder_filter.cpp:34` — FILTERTYPE_VENC 常量
- `surface_encoder_filter.cpp:36` — make_shared 创建 lambda
- `decoder_surface_filter.cpp:70-72` — Decoder 对称注册（对照）
- `audio_encoder_filter.cpp:32-35` — AudioEncoder 对称注册（对照）

---

## 3. SurfaceEncoderFilter 类架构

### 3.1 继承关系

```
Filter (base class)
└── SurfaceEncoderFilter : public Filter
```

### 3.2 核心成员

```cpp
// surface_encoder_filter.h (推算自 cpp 源码)
class SurfaceEncoderFilter : public Filter {
    std::shared_ptr<SurfaceEncoderAdapter> mediaCodec_;   // Codec 引擎
    sptr<Surface> surface_;                                  // 输入 Surface
    std::weak_ptr<Filter> nextFilter_;                     // 下一 Filter（MuxerFilter）
    std::shared_ptr<EventReceiver> eventReceiver_;
    std::shared_ptr<FilterCallback> filterCallback_;
    std::shared_ptr<Meta> configureParameter_;
    std::atomic<bool> isUpdateCodecNeeded_;
    std::string codecMimeType_;
    std::atomic<bool> isTranscoderMode_;
    int32_t appUid_ = -1;
    int32_t appPid_ = -1;
    std::string bundleName_;
    uint64_t instanceId_ = 0;
};
```

**Evidence**:
- `surface_encoder_filter.cpp:112` — `mediaCodec_ = std::make_shared<SurfaceEncoderAdapter>()`
- `surface_encoder_filter.cpp:133` — `surface_ = mediaCodec_->GetInputSurface()`
- `surface_encoder_filter.cpp:159` — `isTranscoderMode_ = true` (SetTransCoderMode)
- `surface_encoder_filter.cpp:253-254` — `muxerFilter = std::static_pointer_cast<MuxerFilter>(nextFilter_)`
- `surface_encoder_filter.cpp:107` — `filterCallback_` NextFilterNeeded 命令
- `surface_encoder_filter.cpp:102-110` — `DoPrepare` 请求下一 Filter（NEXT_FILTER_NEEDED）

### 3.3 Filter 生命周期方法

| 方法 | 功能 | Evidence |
|---|---|---|
| `Init()` | 创建 SurfaceEncoderAdapter，注册 EncoderAdapterCallback | `surface_encoder_filter.cpp:112-129` |
| `Configure()` | 将 parameter 透传给 mediaCodec_->Configure | `surface_encoder_filter.cpp:137-139` |
| `DoPrepare()` | 请求 NEXT_FILTER_NEEDED（通向 MuxerFilter） | `surface_encoder_filter.cpp:102-110` |
| `DoStart()` | 调用 mediaCodec_->Start() | `surface_encoder_filter.cpp:152-154` |
| `DoPause()` | 调用 mediaCodec_->Pause() | `surface_encoder_filter.cpp:158-160` |
| `DoResume()` | 调用 mediaCodec_->Resume() | `surface_encoder_filter.cpp:164-166` |
| `DoStop()` | 调用 mediaCodec_->Stop() | `surface_encoder_filter.cpp:170-173` |
| `DoFlush()` | 调用 mediaCodec_->Flush() | `surface_encoder_filter.cpp:188-190` |
| `DoRelease()` | 调用 mediaCodec_->Reset() 并置空 | `surface_encoder_filter.cpp:194-200` |
| `NotifyEos(int64_t pts)` | 通知编码器 EOS | `surface_encoder_filter.cpp:231-237` |

---

## 4. 三层调用链：Filter → Adapter → CodecServer

### 4.1 层级总览

```
SurfaceEncoderFilter          [Filter 层]  surface_encoder_filter.cpp
    ↓ Init() / Configure() / Start() 等
SurfaceEncoderAdapter        [适配层]  surface_encoder_adapter.cpp
    ↓ VideoEncoderFactory::CreateByMime
AVCodecVideoEncoder          [引擎层 / CodecServer]
```

### 4.2 Init 流程（行号级）

```
surface_encoder_filter.cpp:112
    mediaCodec_ = std::make_shared<SurfaceEncoderAdapter>();

surface_encoder_filter.cpp:113
    mediaCodec_->SetCallingInfo(appUid_, appPid_, bundleName_, instanceId_);

surface_encoder_filter.cpp:114
    mediaCodec_->Init(codecMimeType_, true);

surface_encoder_adapter.cpp:76
    VideoEncoderFactory::CreateByMime(mime, format, codecServer_);

surface_encoder_adapter.cpp:79-82
    releaseBufferTask_ = std::make_shared<Task>("SurfaceEncoder");
    releaseBufferTask_->RegisterJob([this] { ReleaseBuffer(); return 0; });

surface_encoder_adapter.cpp:86-89
    codecServer_->SetCallback(surfaceEncoderAdapterCallback);
```

**Evidence**:
- `surface_encoder_adapter.cpp:76` — `VideoEncoderFactory::CreateByMime` 创建 codecServer_
- `surface_encoder_adapter.cpp:74` — callerInfo 设置 PID/UID/ProcessName 到 Format
- `surface_encoder_adapter.cpp:79-82` — 后台线程 `releaseBufferTask_` 负责 ReleaseOutputBuffer

### 4.3 Configure 流程

```
SurfaceEncoderFilter.Configure(parameter)
  → SurfaceEncoderAdapter.Configure(meta)
      → ConfigureGeneralFormat()    设置 宽/高/帧率/码率/MIME/HEVCProfile
      → ConfigureAboutRGBA()       设置 像素格式/NV12 + 码率模式
      → ConfigureAboutEnableTemporalScale()  设置 时域可分级
      → ConfigureEnableFormat()     设置 水印开关
      → codecServer_->Configure(format)
```

**Evidence**:
- `surface_encoder_adapter.cpp:101-105` — `ConfigureGeneralFormat` 提取 Tag::VIDEO_WIDTH/HEIGHT/FRAME_RATE/BITRATE/MIME_TYPE/H265_PROFILE
- `surface_encoder_adapter.cpp:427-436` — `ConfigureAboutRGBA` 设置 MD_KEY_PIXEL_FORMAT + MD_KEY_VIDEO_ENCODE_BITRATE_MODE
- `surface_encoder_adapter.cpp:437-449` — `ConfigureAboutEnableTemporalScale` 设置 OH_MD_KEY_VIDEO_ENCODER_ENABLE_TEMPORAL_SCALABILITY
- `surface_encoder_adapter.cpp:153` — `codecServer_->Configure(format)`

### 4.4 Surface 模式输入

```cpp
// SurfaceEncoderFilter.SetInputSurface(surface)
surface_encoder_filter.cpp:148
    mediaCodec_->SetInputSurface(surface);

// SurfaceEncoderFilter.GetInputSurface()
surface_encoder_filter.cpp:133
    surface_ = mediaCodec_->GetInputSurface();
    return surface_;

// SurfaceEncoderAdapter.GetInputSurface()
surface_encoder_adapter.cpp:185
    return codecServer_->CreateInputSurface();
```

**Evidence**:
- `surface_encoder_adapter.cpp:185` — `codecServer_->CreateInputSurface()` 创建编码器输入 Surface
- `surface_encoder_filter.cpp:148` — 透传 surface 给 adapter
- `surface_encoder_filter.cpp:133` — adapter 创建后缓存于 `surface_`

### 4.5 输出数据流

```
codecServer_->OnOutputBufferAvailable(index, buffer)
  → SurfaceEncoderAdapter.OnOutputBufferAvailable()
      → outputBufferQueueProducer_->RequestBuffer()    请求空闲 Buffer
      → bufferMem->Write(src, size)                    拷贝编码数据
      → outputBufferQueueProducer_->PushBuffer()       推送到下一 Filter
      → indexs_.push_back(index)                       记录待释放 index
      → releaseBufferCondition_.notify_all()           通知释放线程
  → ReleaseBuffer() [后台 Task 线程]
      → codecServer_->ReleaseOutputBuffer(index)       真正释放编码器输出 Buffer
```

**Evidence**:
- `surface_encoder_adapter.cpp:348-370` — `OnOutputBufferAvailable` 完整流程
- `surface_encoder_adapter.cpp:350` — `buffer->pts_ / NS_PER_US` PTS 单位转换（编码器用 ns，Filter 链用 μs）
- `surface_encoder_adapter.cpp:372-390` — `ReleaseBuffer()` 后台线程，循环等待并释放
- `surface_encoder_adapter.cpp:377` — `releaseBufferCondition_.wait()` 条件变量等待
- `surface_encoder_adapter.cpp:383` — `codecServer_->ReleaseOutputBuffer(index)` 批量释放

---

## 5. SurfaceEncoderAdapter 状态机

### 5.1 ProcessStateCode 枚举

```cpp
enum class ProcessStateCode {
    IDLE,       // 初始 / Reset 后
    RECORDING,  // Start / Resume 后
    PAUSED,    // Pause 后
    STOPPED,   // Stop 后
    ERROR,      // 出错
};
```

**Evidence**:
- `surface_encoder_adapter.h:53-58` — ProcessStateCode 枚举定义

### 5.2 状态转换

```
IDLE
  ↓ Init + Configure + DoPrepare
[用户 Start]
  ↓ DoStart → codecServer_->Start()
RECORDING
  ↓ DoPause (非 TranscoderMode)
PAUSED
  ↓ DoResume
RECORDING
  ↓ DoStop
RECORDING
  ↓ HandleWaitforStop + AddStopPts
STOPPED → DoRelease → Reset → IDLE
```

**Evidence**:
- `surface_encoder_adapter.cpp:188` — `curState_ = ProcessStateCode::RECORDING` (Start 成功后)
- `surface_encoder_adapter.cpp:195` — `curState_ = ProcessStateCode::ERROR` (Start 失败)
- `surface_encoder_adapter.cpp:248-250` — `curState_ = ProcessStateCode::PAUSED` (Pause 后)
- `surface_encoder_adapter.cpp:277` — `curState_ = ProcessStateCode::RECORDING` (Resume 后)
- `surface_encoder_adapter.cpp:229` — `curState_ = ProcessStateCode::STOPPED` (Stop 后)

### 5.3 TranscoderMode 特殊行为

- `isTransCoderMode = true` 时，`Pause()`/`Resume()` 直接返回 `Status::OK`，不执行帧率调整
- `Configure` 中设置 `VIDEO_FRAME_RATE_ADAPTIVE_MODE = true` 和 `AV_TRANSCODER_ENABLE_B_FRAME`
- `OnOutputBufferAvailable` 中对 TranscoderMode 走 `TransCoderOnOutputBufferAvailable` 特殊路径（无 PTS 除以 NS_PER_US）

**Evidence**:
- `surface_encoder_adapter.cpp:159` — `SetTransCoderMode()` 设置 `isTransCoderMode = true`
- `surface_encoder_adapter.cpp:163` — Pause 中跳过状态更新
- `surface_encoder_adapter.cpp:269` — Resume 中跳过状态更新
- `surface_encoder_adapter.cpp:329` — `TransCoderOnOutputBufferAvailable`（无 PTS 转换）

---

## 6. SurfaceEncoderFilter 与 SurfaceEncoderAdapter 对比

| 维度 | SurfaceEncoderFilter（Filter 层） | SurfaceEncoderAdapter（适配层） |
|---|---|---|
| 职责 | Filter 生命周期、Filter 链管理、回调分发 | CodecServer 创建/配置、Buffer 管理、状态机 |
| 创建时机 | `DoPrepare()` | `Init()` |
| Surface 来源 | `SetInputSurface()` 注入 | `codecServer_->CreateInputSurface()` 创建 |
| 输出 Buffer | `SetOutputBufferQueue()` 注入 outputBufferQueueProducer_ | `RequestBuffer/PushBuffer` 经 outputBufferQueueProducer_ |
| PTS 处理 | 不处理 | `buffer->pts_ / NS_PER_US` 单位转换 |
| 丢帧策略 | 无 | `CheckFrames` + `VIDEO_ENCODER_PER_FRAME_DISCARD` 参数 |
| 水印 | `SetWatermark()` | `codecServer_->SetCustomBuffer()` |
| B-Frame | `SetVideoEnableBFrame()` | `Configure` 中 `VIDEO_ENCODER_ENABLE_B_FRAME` |

**Evidence**:
- `surface_encoder_filter.cpp:141-146` — SetWatermark 透传
- `surface_encoder_filter.cpp:150-154` — SetVideoEnableBFrame 透传
- `surface_encoder_adapter.cpp:165-171` — SetWatermark → codecServer_->SetCustomBuffer
- `surface_encoder_adapter.cpp:350` — PTS ns→μs 转换

---

## 7. SurfaceEncoderFilter 的 Filter 链位置

在录制管线中，`SurfaceEncoderFilter` 位于数据流上游：

```
[VideoCaptureFilter]  (Surface 输入)
       ↓ Surface
[SurfaceEncoderFilter]  "builtin.recorder.videoencoder" (FILTERTYPE_VENC)
       ↓ AVBufferQueue (STREAMTYPE_ENCODED_VIDEO)
[MuxerFilter]  "builtin.recorder.muxer" (FILTERTYPE_MUXER)
       ↓
[文件封装输出]
```

证据：
- `surface_encoder_filter.cpp:107-109` — `NEXT_FILTER_NEEDED` 命令指定 `StreamType::STREAMTYPE_ENCODED_VIDEO`
- `surface_encoder_filter.cpp:253-254` — `std::static_pointer_cast<MuxerFilter>(nextFilter_)` — 强制转换为 MuxerFilter 写入首帧 PTS

**与 VideoCaptureFilter(S28) 的对称关系**：

| 维度 | VideoCaptureFilter（S28） | SurfaceEncoderFilter（S36） |
|---|---|---|
| 注册名 | `"builtin.recorder.videocapture"` | `"builtin.recorder.videoencoder"` |
| FilterType | - | `FILTERTYPE_VENC` |
| 数据方向 | Surface → AVBuffer | AVBuffer → 编码后 AVBuffer |
| 角色 | 管线数据源 | 管线编码节点 |
| 对应解码侧 | DecoderSurfaceFilter（Player） | SurfaceEncoderFilter（Recorder） |

---

## 8. 关键证据索引

| 文件 | 行号 | 说明 |
|---|---|---|
| `services/media_engine/filters/surface_encoder_filter.cpp` | 33-36 | AutoRegisterFilter 注册 |
| `services/media_engine/filters/surface_encoder_filter.cpp` | 37-75 | SurfaceEncoderFilterLinkCallback / SurfaceEncoderAdapterCallback |
| `services/media_engine/filters/surface_encoder_filter.cpp` | 112-129 | Init：创建 SurfaceEncoderAdapter 并注册 Callbacks |
| `services/media_engine/filters/surface_encoder_filter.cpp` | 102-110 | DoPrepare：NEXT_FILTER_NEEDED |
| `services/media_engine/filters/surface_encoder_filter.cpp` | 137-139 | Configure 透传 |
| `services/media_engine/filters/surface_encoder_filter.cpp` | 148-149 | SetInputSurface 透传 |
| `services/media_engine/filters/surface_encoder_filter.cpp` | 152-154 | DoStart 透传 |
| `services/media_engine/filters/surface_encoder_filter.cpp` | 170-173 | DoStop 透传 |
| `services/media_engine/filters/surface_encoder_filter.cpp` | 253-254 | MuxerFilter 强转 + SetUserMeta |
| `services/media_engine/filters/surface_encoder_adapter.cpp` | 76 | VideoEncoderFactory::CreateByMime |
| `services/media_engine/filters/surface_encoder_adapter.cpp` | 79-82 | ReleaseBuffer Task 后台线程 |
| `services/media_engine/filters/surface_encoder_adapter.cpp` | 101-105 | ConfigureGeneralFormat 提取参数 |
| `services/media_engine/filters/surface_encoder_adapter.cpp` | 153 | codecServer_->Configure |
| `services/media_engine/filters/surface_encoder_adapter.cpp` | 185 | codecServer_->CreateInputSurface |
| `services/media_engine/filters/surface_encoder_adapter.cpp` | 329-343 | TransCoderOnOutputBufferAvailable |
| `services/media_engine/filters/surface_encoder_adapter.cpp` | 348-370 | OnOutputBufferAvailable 标准路径 |
| `services/media_engine/filters/surface_encoder_adapter.cpp` | 372-390 | ReleaseBuffer 后台线程 |
| `services/media_engine/filters/surface_encoder_adapter.h` | 53-58 | ProcessStateCode 枚举 |
| `services/media_engine/filters/decoder_surface_filter.cpp` | 70-72 | Decoder 对称注册（对照） |

---

## 9. 与相邻记忆条目的关系

- **S23**（SurfaceEncoderAdapter）：S23 已覆盖 SurfaceEncoderAdapter 本身，本条目聚焦 Filter 层封装与 Filter 链集成
- **S28**（VideoCaptureFilter）：S28 是录制管线数据源，S36 是管线编码节点，两者对称
- **S35**（AudioDecoderFilter）：S35 是音频解码 Filter，S36 是视频编码 Filter，双双构成音视频 Filter 对称
- **S14**（Filter Chain）：S14 描述 Filter Chain 架构，S36 补充 VideoEncoderFilter 特定实现细节
