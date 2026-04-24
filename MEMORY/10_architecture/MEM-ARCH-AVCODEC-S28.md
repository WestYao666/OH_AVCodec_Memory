---
type: architecture
id: MEM-ARCH-AVCODEC-S28
status: pending_approval
topic: VideoCaptureFilter 视频采集过滤器——Surface模式输入与录制管线数据源
created_at: "2026-04-25T07:40:00+08:00"
evidence:
  - kind: code
    path: /home/west/OH_AVCodec/services/media_engine/filters/video_capture_filter.cpp
    anchor: Line 33-37: static AutoRegisterFilter<VideoCaptureFilter> g_registerSurfaceEncoderFilter("builtin.recorder.videocapture", FilterType::VIDEO_CAPTURE)
    note: Filter注册名builtin.recorder.videocapture，类型VIDEO_CAPTURE，用于录制管线视频采集
  - kind: code
    path: /home/west/OH_AVCodec/services/media_engine/filters/video_capture_filter.cpp
    anchor: Line 98-107: VideoCaptureFilter构造函数，DoPrepare→OnCallback(NEXT_FILTER_NEEDED, STREAMTYPE_ENCODED_VIDEO)
    note: DoPrepare通知管线需要下一级Filter（SurfaceEncoderAdapter），输出类型STREAMTYPE_ENCODED_VIDEO
  - kind: code
    path: /home/west/OH_AVCodec/services/media_engine/filters/video_capture_filter.cpp
    anchor: Line 184-208: DoStart/DoPause/DoResume生命周期，isStop_标志控制采集
    note: DoStart开启采集，DoPause暂停并记录latestPausedTime_，DoResume恢复并刷新暂停时间
  - kind: code
    path: /home/west/OH_AVCodec/services/media_engine/filters/video_capture_filter.cpp
    anchor: Line 210-230: DoStop重置所有时间状态latestBufferTime_/latestPausedTime_/totalPausedTime_
    note: 停止时重置时间状态，确保下次录制时间戳连续性
  - kind: code
    path: /home/west/OH_AVCodec/services/media_engine/filters/video_capture_filter.cpp
    anchor: Line 321-350: OnBufferAvailable→AcquireInputBuffer→ProcessAndPushOutputBuffer完整采集流程
    note: ConsumerSurfaceBufferListener触发OnBufferAvailable，从Surface获取Buffer后处理并推送下游
  - kind: code
    path: /home/west/OH_AVCodec/services/media_engine/filters/video_capture_filter.cpp
    anchor: Line 352-375: AcquireInputBuffer→inputSurface_->AcquireBuffer+SyncFence.Wait+extraData提取timestamp/dataSize/isKeyFrame
    note: AcquireBuffer从Surface消费Buffer，等待SyncFence，从extraData提取关键帧标志和时间戳
  - kind: code
    path: /home/west/OH_AVCodec/services/media_engine/filters/video_capture_filter.cpp
    anchor: Line 377-400: ProcessAndPushOutputBuffer→RequestBuffer+Write+PushBuffer将视频帧写入下游编码器
    note: outputBufferQueueProducer_ RequestBuffer获取空Buffer，写入数据后PushBuffer推送下游SurfaceEncoderAdapter
  - kind: code
    path: /home/west/OH_AVCodec/services/media_engine/filters/video_capture_filter.cpp
    anchor: Line 120-145: SetInputSurface(sptr<Surface>)→RegisterConsumerListener(ConsumerSurfaceBufferListener)
    note: 外部通过SetInputSurface注入Surface，VideoCaptureFilter注册Consumer监听器消费Buffer
  - kind: code
    path: /home/west/OH_AVCodec/services/media_engine/filters/video_capture_filter.cpp
    anchor: Line 147-168: GetInputSurface()→CreateSurfaceAsConsumer+SetDefaultUsage(ENCODE_USAGE)+CreateSurfaceAsProducer返回
    note: 创建ENCODE_USAGE消费者Surface，返回对应Producer Surface给上游，上游写入视频帧后VideoCaptureFilter消费
  - kind: code
    path: /home/west/OH_AVCodec/interfaces/inner_api/native/video_capture_filter.h
    anchor: Line 81-106: 成员变量outputBufferQueueProducer_/inputSurface_/isStop_/startBufferTime_/latestBufferTime_等
    note: outputBufferQueueProducer_连接下游SurfaceEncoderAdapter，isStop_控制采集暂停，总暂停时间totalPausedTime_用于时间校正
  - kind: code
    path: /home/west/OH_AVCodec/services/media_engine/filters/video_capture_filter.cpp
    anchor: Line 402-420: UpdateBufferConfig→startBufferTime_初始化+SYNC_FRAME/CODEC_DATA标志+totalPausedTime_时间补偿
    note: 首帧设置SYNC_FRAME+CODEC_DATA标志，暂停期间时间不计入有效时间戳
  - kind: code
    path: /home/west/OH_AVCodec/services/media_engine/filters/video_capture_filter.cpp
    anchor: Line 78-93: ConsumerSurfaceBufferListener::OnBufferAvailable封装，IBufferConsumerListener实现
    note: ConsumerSurfaceBufferListener持有VideoCaptureFilter弱引用，OnBufferAvailable触发采集工作
owner: 耀耀
review: pending
---

# MEM-ARCH-AVCODEC-S28: VideoCaptureFilter 视频采集过滤器

## Metadata

| 字段 | 值 |
|------|-----|
| id | MEM-ARCH-AVCODEC-S28 |
| title | VideoCaptureFilter 视频采集过滤器——Surface模式输入与录制管线数据源 |
| type | architecture_fact |
| scope | [AVCodec, MediaEngine, Filter, VideoCapture, RecorderPipeline, SurfaceMode, Source] |
| status | draft |
| created_by | builder-agent |
| created_at | 2026-04-25 |
| confidence | high |

## 摘要

VideoCaptureFilter 是 media_engine filters 中专用于**录制管线视频采集 Source Filter** 的组件，注册名为 `"builtin.recorder.videocapture"`，FilterType 为 `VIDEO_CAPTURE`。它从上游 Surface（Camera 或虚拟显示）消费视频帧 Buffer，经处理后通过 `AVBufferQueueProducer` 推送至下游 `SurfaceEncoderAdapter` 进行视频编码。

其核心职责：**录制管线的视频数据源**——与 `AudioCaptureFilter`（S26）并列，构成录音录像双路采集的入口。

## 关键类与接口

### VideoCaptureFilter
- **文件**: `services/media_engine/filters/video_capture_filter.cpp`
- **头文件**: `interfaces/inner_api/native/video_capture_filter.h`
- **LOG_DOMAIN**: `LOG_DOMAIN_RECORDER`（"VideoCaptureFilter"）
- **Filter注册名**: `"builtin.recorder.videocapture"`
- **FilterType**: `VIDEO_CAPTURE`

### ConsumerSurfaceBufferListener
- **性质**: `IBufferConsumerListener` 实现类
- **职责**: 封装对 `VideoCaptureFilter` 的弱引用，当 `inputSurface_` 有 Buffer 可用时触发 `OnBufferAvailable()`

### 核心成员变量

| 成员 | 类型 | 说明 |
|------|------|------|
| `inputSurface_` | `sptr<Surface>` | 消费端 Surface（由上游写入视频帧） |
| `outputBufferQueueProducer_` | `sptr<AVBufferQueueProducer>` | 输出队列生产者，连接下游编码器 |
| `isStop_` | `bool` | 采集暂停标志（DoPause 设置，DoResume/DoStop 重置） |
| `startBufferTime_` | `int64_t` | 首帧时间戳（TIME_NONE 表示未开始） |
| `latestBufferTime_` | `int64_t` | 最近帧时间戳 |
| `latestPausedTime_` | `int64_t` | 最近一次暂停时间点 |
| `totalPausedTime_` | `int64_t` | 累计暂停时长（用于时间补偿） |
| `refreshTotalPauseTime_` | `bool` | 恢复后刷新暂停时间标志 |
| `ENCODE_USAGE` | `static constexpr` | `BUFFER_USAGE_CPU_READ\|CPU_WRITE\|MEM_DMA\|VIDEO_ENCODER` |

## 注册机制

```cpp
// video_capture_filter.cpp:33-37
static AutoRegisterFilter<VideoCaptureFilter> g_registerSurfaceEncoderFilter(
    "builtin.recorder.videocapture",
    FilterType::VIDEO_CAPTURE,
    [](const std::string& name, const FilterType type) {
        return std::make_shared<VideoCaptureFilter>(name, FilterType::VIDEO_CAPTURE);
    });
```

**AutoRegisterFilter 自动注册**，管线初始化时由 Filter 工厂实例化，无需手动创建。

## Surface 注入机制（两种模式）

### 模式1：外部注入（SetInputSurface）

```cpp
// video_capture_filter.cpp:120-135
Status VideoCaptureFilter::SetInputSurface(sptr<Surface> surface)
{
    inputSurface_ = surface;
    sptr<IBufferConsumerListener> listener = new ConsumerSurfaceBufferListener(shared_from_this());
    inputSurface_->RegisterConsumerListener(listener);  // 注册消费者监听
    return Status::OK;
}
```

适用于 CameraService 或其他 Surface 生产者主动注入 Surface 的场景。

### 模式2：自建生产者（GetInputSurface）

```cpp
// video_capture_filter.cpp:147-168
sptr<Surface> VideoCaptureFilter::GetInputSurface()
{
    // 创建消费者 Surface（ENCODE_USAGE = VIDEO_ENCODER 可用）
    sptr<Surface> consumerSurface = Surface::CreateSurfaceAsConsumer("EncoderSurface");
    consumerSurface->SetDefaultUsage(ENCODE_USAGE);  // VIDEO_ENCODER 用途

    // 获取生产者 Surface 返回给上游
    sptr<IBufferProducer> producer = consumerSurface->GetProducer();
    sptr<Surface> producerSurface = Surface::CreateSurfaceAsProducer(producer);

    inputSurface_ = consumerSurface;
    sptr<IBufferConsumerListener> listener = new ConsumerSurfaceBufferListener(shared_from_this());
    inputSurface_->RegisterConsumerListener(listener);
    return producerSurface;  // 返回给 Camera/上游写入
}
```

适用于 VideoCaptureFilter 主动创建 Surface 并将 Producer 交给上游的场景。

## 生命周期

| 阶段 | 方法 | 关键操作 |
|------|------|----------|
| **Prepare** | `DoPrepare()` | 触发 `NEXT_FILTER_NEEDED(STREAMTYPE_ENCODED_VIDEO)`，通知管线需要下游编码器 |
| **Start** | `DoStart()` | `isStop_ = false`，开始处理 Buffer |
| **Pause** | `DoPause()` | `isStop_ = true`，记录 `latestPausedTime_ = latestBufferTime_` |
| **Resume** | `DoResume()` | `isStop_ = false`，`refreshTotalPauseTime_ = true` 刷新暂停时间 |
| **Stop** | `DoStop()` | `isStop_ = true`，重置 `startBufferTime_/latestBufferTime_/latestPausedTime_/totalPausedTime_` |
| **Release** | `DoRelease()` | 释放资源 |

## 采集工作流（OnBufferAvailable 核心路径）

```
上游 Surface（Camera/虚拟显示）写入帧
  → ConsumerSurfaceBufferListener::OnBufferAvailable()
  → VideoCaptureFilter::OnBufferAvailable()

Step 1: AcquireInputBuffer
  → inputSurface_->AcquireBuffer(buffer, fence, timestamp, damage)
  → fence->Wait(waitForEver)  同步等待 Buffer 就绪
  → extraData->ExtraGet("timeStamp")  提取时间戳
  → extraData->ExtraGet("isKeyFrame")  提取关键帧标志
  → 如果 isStop_==true → ReleaseBuffer 后直接返回（暂停期间丢弃）

Step 2: ProcessAndPushOutputBuffer
  → outputBufferQueueProducer_->RequestBuffer(emptyBuffer)
  → 空Buffer写入视频数据（memcpy）
  → 首帧：flag_ = SYNC_FRAME | CODEC_DATA
  → 非首帧：flag_ = isKeyFrame ? SYNC_FRAME : 0
  → UpdateBufferConfig：totalPausedTime_ 时间补偿
  → outputBufferQueueProducer_->PushBuffer(outputBuffer, true)

Step 3: Release
  → inputSurface_->ReleaseBuffer(buffer, -1)  归还输入Buffer
```

## 时间戳管理

```cpp
// video_capture_filter.cpp:402-420
void VideoCaptureFilter::UpdateBufferConfig(std::shared_ptr<AVBuffer> buffer, int64_t timestamp)
{
    if (startBufferTime_ == TIME_NONE) {
        // 首帧：设置关键标志
        buffer->flag_ = SYNC_FRAME | CODEC_DATA;
        startBufferTime_ = timestamp;
    }
    latestBufferTime_ = timestamp;

    // 恢复后累加暂停时长
    if (refreshTotalPauseTime_) {
        if (latestPausedTime_ != TIME_NONE && latestBufferTime_ > latestPausedTime_) {
            totalPausedTime_ += latestBufferTime_ - latestPausedTime_;
        }
        refreshTotalPauseTime_ = false;
    }
}
```

| 标志 | 含义 |
|------|------|
| `SYNC_FRAME` | 关键帧（I帧），用于解码同步 |
| `CODEC_DATA` | Codec 私有数据（序列头/参数集），仅首帧设置 |
| `totalPausedTime_` | 暂停期间时长不计入有效 PTS，保证时间轴连续 |

## 与录制管线其他组件的关系

| 组件 | 关系 | 说明 |
|------|------|------|
| SurfaceEncoderAdapter（S23） | 下游 | VideoCaptureFilter 输出至 SurfaceEncoderAdapter 进行视频编码 |
| AudioCaptureFilter（S26） | 并列 | 音频采集 Source Filter，与 VideoCaptureFilter 构成录音录像双路入口 |
| AudioEncoderFilter（S24） | 下游（音频） | AudioCaptureFilter 输出至 AudioEncoderFilter 编码 |
| Surface（Camera/虚拟显示） | 上游数据源 | 通过 SetInputSurface 或 GetInputSurface 注入 Surface |

## 录制管线完整数据流（视频支路）

```
Camera Surface / 虚拟显示 Surface
  ↓ (写入视频帧)
VideoCaptureFilter（"builtin.recorder.videocapture"）
  ↓ STREAMTYPE_ENCODED_VIDEO + AVBufferQueue
SurfaceEncoderAdapter（S23，"builtin.recorder.videoencoder"）
  ↓ 编码后的视频 BitStream
MuxerFilter（"builtin.recorder.muxer"）
  ↓ MP4/MKV 封装
最终文件输出
```

## 与 AudioCaptureFilter（S26）对比

| 维度 | VideoCaptureFilter | AudioCaptureFilter |
|------|-------------------|-------------------|
| 注册名 | `"builtin.recorder.videocapture"` | `"builtin.recorder.audiocapture"` |
| FilterType | `VIDEO_CAPTURE` | `AUDIO_CAPTURE` |
| 数据源 | Surface（视频帧） | AudioCapturer（PCM 音频） |
| Buffer 类型 | SurfaceBuffer | AVBuffer（PCM） |
| 关键帧处理 | isKeyFrame 标志提取 + SYNC_FRAME | 无关键帧概念 |
| 下游 | SurfaceEncoderAdapter | AudioEncoderFilter |
| 暂停机制 | isStop_ + totalPausedTime_ 补偿 | isStop_ |

## Builder 注（2026-04-25T07:40）

- S28 填补录制管线视频采集 Source Filter 的记忆空白，与 S23（SurfaceEncoderAdapter 编码）、S26（AudioCaptureFilter 音频采集）构成完整录制管线三元件
- VideoCaptureFilter 与 AudioCaptureFilter 并列，共同作为录制管线双路采集入口，上接 Surface/AudioCapturer，下连编码器 Filter
- ConsumerSurfaceBufferListener 是 Surface 与 Filter 之间的桥接器，将 Surface 的 Buffer 可用事件转换为 Filter 的采集动作
