---
type: architecture
id: MEM-ARCH-AVCODEC-S26
status: draft
topic: AudioCaptureFilter + AudioDataSourceFilter 录制采集过滤器——AudioCaptureModule、AudioCapturer 与 SubtitleSink 字幕渲染
scope: [AVCodec, MediaEngine, Filter, AudioCapture, AudioDataSource, AudioCapturer, Subtitle, RecorderPipeline, Pipeline]
submitted_at: "2026-04-25T04:55:00+08:00"
author: builder-agent
evidence: |
  - source: services/media_engine/filters/audio_capture_filter.cpp line 33
    anchor: "static AutoRegisterFilter<AudioCaptureFilter> g_registerAudioCaptureFilter(\"builtin.recorder.audiocapture\", FilterType::AUDIO_CAPTURE, ...)"
    note: 注册名 builtin.recorder.audiocapture，FilterType::AUDIO_CAPTURE，完整录音管线起点
  - source: services/media_engine/filters/audio_capture_filter.cpp line 101-120
    anchor: "Init() audioCaptureModule_ = std::make_shared<AudioCaptureModule::AudioCaptureModule>()"
    note: AudioCaptureFilter 持有 AudioCaptureModule，封装 AudioStandard::AudioCapturer
  - source: services/media_engine/filters/audio_capture_filter.cpp line 28-32
    anchor: "constexpr int64_t AUDIO_CAPTURE_READ_FRAME_TIME = 20000000 // 20000000 ns 20ms"
    note: 音频帧周期 20ms，对应 48kHz 采样率下 960 samples/frame
  - source: services/media_engine/filters/audio_capture_filter.cpp line 55-58
    anchor: "AudioCaptureModuleCallbackImpl::OnInterrupt() → receiver_->OnEvent(EVENT_ERROR, ERROR_AUDIO_INTERRUPT)"
    note: 音频中断（插拔耳机等）通过 AudioCaptureModuleCallback → EventReceiver 回调上报
  - source: services/media_engine/filters/audio_capture_filter.cpp line 165-190
    anchor: "DoStart() audioCaptureModule_->Start() → taskPtr_->Start() ReadLoop()"
    note: 启动顺序：先 audioCaptureModule_->Start()，后 Task(ReadLoop) 线程启动
  - source: services/media_engine/filters/audio_capture_filter.cpp line 250-300
    anchor: "DoPause() audioCaptureModule_->Stop() + FillLostFrame() 时间对齐补偿"
    note: 暂停时音频采集停止，并补齐时间轴空白帧；withVideo_ 时支持音视频时间对齐
  - source: services/media_engine/filters/audio_capture_filter.cpp line 260-275
    anchor: "FillLostFrame(lostCount) 填充因视频暂停丢失的音频帧"
    note: 丢失帧数 = (pauseTime - currentTime) / AUDIO_CAPTURE_READ_FRAME_TIME，当时间差异常时跳过补帧
  - source: services/media_engine/modules/source/audio_capture/audio_capture_module.h line 35-40
    anchor: "class AudioCaptureModule: Init/Start/Stop/Read/SetParameter/GetParameter/SetAudioInterruptListener/SetAudioCapturerInfoChangeCallback"
    note: AudioCaptureModule 封装 AudioCapturer，提供 Read(Meta/uint8_t)、GetMaxAmplitude 振幅检测
  - source: services/media_engine/filters/audio_data_source_filter.cpp line 34
    anchor: "static AutoRegisterFilter<AudioDataSourceFilter> g_registerAudioDataSourceFilter(\"builtin.recorder.audiodatasource\", FilterType::AUDIO_DATA_SOURCE, ...)"
    note: 注册名 builtin.recorder.audiodatasource，FilterType::AUDIO_DATA_SOURCE，数据源模式
  - source: services/media_engine/filters/audio_data_source_filter.cpp line 95-105
    anchor: "DoStart() eos_=false → taskPtr_->Start() ReadLoop()"
    note: AudioDataSourceFilter 直接启动 ReadLoop Task，无 AudioCapturer 依赖（数据来自上层传入）
  - source: services/media_engine/filters/subtitle_sink_filter.cpp line 34-36
    anchor: "static AutoRegisterFilter<SubtitleSinkFilter> g_registerSubtitleSinkFilter(\"builtin.player.subtitlesink\", FilterType::FILTERTYPE_SSINK, ...)"
    note: 注册名 builtin.player.subtitlesink，FilterType::FILTERTYPE_SSINK，播放管线字幕渲染终点
  - source: services/media_engine/filters/subtitle_sink_filter.cpp line 80-100
    anchor: "DoPrepare() subtitleSink_->Init() → inputBufferQueueConsumer_ → SetBufferAvailableListener(AVBufferAvailableListener)"
    note: SubtitleSink 初始化后创建消费者队列，注册 OnBufferAvailable 监听驱动 ProcessInputBuffer
  - source: services/media_engine/filters/subtitle_sink_filter.cpp line 110-140
    anchor: "DoFreeze() subtitleSink_->Pause() state_=FROZEN; DoUnFreeze() subtitleSink_->Resume()"
    note: SubtitleSink 支持 Freeze/UnFreeze 冻结解码，frameCnt_ 清零重置计数
  - source: services/media_engine/filters/video_capture_filter.cpp line 28-30
    anchor: "static AutoRegisterFilter<VideoCaptureFilter> g_registerSurfaceEncoderFilter(\"builtin.recorder.videocapture\", FilterType::VIDEO_CAPTURE, ...)"
    note: 注册名 builtin.recorder.videocapture，FilterType::VIDEO_CAPTURE，视频采集 Filter
---

# MEM-ARCH-AVCODEC-S26: AudioCaptureFilter + AudioDataSourceFilter 录制采集过滤器

## Metadata

| 字段 | 值 |
|------|-----|
| id | MEM-ARCH-AVCODEC-S26 |
| title | AudioCaptureFilter + AudioDataSourceFilter 录制采集过滤器——AudioCaptureModule、AudioCapturer 与 SubtitleSink 字幕渲染 |
| scope | [AVCodec, MediaEngine, Filter, AudioCapture, AudioDataSource, AudioCapturer, Subtitle, RecorderPipeline] |
| status | draft |
| created_by | builder-agent |
| created_at | 2026-04-25 |
| type | architecture_fact |
| confidence | high |

---

## 摘要

AudioCaptureFilter 和 AudioDataSourceFilter 是 MediaEngine 录制管线的两类音频采集 Filter，分别对应**设备音频采集**和**数据源输入**两种模式。两者都位于录音管线起点，下游接入 AudioEncoderFilter → MuxerFilter。SubtitleSinkFilter 则是播放管线的字幕渲染终点。

---

## 1. AudioCaptureFilter（设备音频采集）

**文件**: `services/media_engine/filters/audio_capture_filter.cpp`

### 1.1 注册与类型

```cpp
// line 33
static AutoRegisterFilter<AudioCaptureFilter> g_registerAudioCaptureFilter(
    "builtin.recorder.audiocapture",  // 注册名
    FilterType::AUDIO_CAPTURE,         // Filter 类型
    [](...) { return std::make_shared<AudioCaptureFilter>(...); }
);
```

### 1.2 核心组件

| 组件 | 类型 | 职责 |
|------|------|------|
| `audioCaptureModule_` | `AudioCaptureModule::AudioCaptureModule` | 封装 AudioStandard::AudioCapturer，底层调用 audio_capturer.h |
| `taskPtr_` | `Task("DataReader")` | ReadLoop 后台线程，周期 20ms 读一帧 |
| `cachedAudioDataDeque_` | `deque<uint8_t>` | 音频帧缓存（暂停时用于音视频时间对齐） |
| `sourceType_` | `AudioStandard::SourceType` | 音频源类型（MIC/voiceRecognition等） |

### 1.3 生命周期

| 状态 | 关键动作 |
|------|---------|
| `DoStart()` | 先 `audioCaptureModule_->Start()`，后 `taskPtr_->Start()` 启动 ReadLoop |
| `DoPause()` | `audioCaptureModule_->Stop()` + `FillLostFrame()` 补齐时间轴音频帧 |
| `DoResume()` | 重置时间状态，重新 `Start()` |
| `DoStop()` | 先 `taskPtr_->StopAsync()`，后 `audioCaptureModule_->Stop()` |

### 1.4 ReadLoop 机制

```cpp
// 周期: 20ms (AUDIO_CAPTURE_READ_FRAME_TIME)
while (taskPtr_->IsRunning()) {
    audioCaptureModule_->Read(buffer);  // 从 AudioCapturer 读一帧
    PushToDownstream(buffer);            // 送入下游 AudioEncoderFilter
}
```

### 1.5 音频中断处理

```cpp
// AudioCaptureModuleCallbackImpl::OnInterrupt
→ receiver_->OnEvent("audio_capture_filter", EVENT_ERROR, ERROR_AUDIO_INTERRUPT)
```

音频设备插拔、声道切换等中断通过 AudioCaptureModuleCallback 回调 EventReceiver 上报。

### 1.6 音视频时间对齐（暂停补偿）

```cpp
// DoPause 中：
int64_t lostCount = ((pauseTime - currentTime) + AUDIO_CAPTURE_READ_FRAME_TIME_HALF) / AUDIO_CAPTURE_READ_FRAME_TIME;
FillLostFrame(lostCount);  // 补齐因视频暂停导致的音频帧缺失
```

---

## 2. AudioDataSourceFilter（数据源模式）

**文件**: `services/media_engine/filters/audio_data_source_filter.cpp`

### 2.1 注册与类型

```cpp
// line 34
static AutoRegisterFilter<AudioDataSourceFilter> g_registerAudioDataSourceFilter(
    "builtin.recorder.audiodatasource",  // 注册名
    FilterType::AUDIO_DATA_SOURCE,       // Filter 类型
    ...
);
```

### 2.2 与 AudioCaptureFilter 的区别

| 维度 | AudioCaptureFilter | AudioDataSourceFilter |
|------|-------------------|----------------------|
| 数据来源 | AudioStandard::AudioCapturer（硬件/MIC） | 上游 Filter 传入的 AVBuffer |
| 依赖 | AudioCaptureModule | AudioDataSource（无音频采集硬件依赖） |
| 用途 | 录音（recorder） | 数据流录制（屏幕录制/数据流处理） |
| 启动顺序 | 先 audioCaptureModule_->Start() | 直接 taskPtr_->Start() |

### 2.3 生命周期

无音频设备依赖，直接通过 ReadLoop 从上游获取数据并推送下游。

---

## 3. SubtitleSinkFilter（字幕渲染终点）

**文件**: `services/media_engine/filters/subtitle_sink_filter.cpp`

### 3.1 注册与类型

```cpp
// line 34
static AutoRegisterFilter<SubtitleSinkFilter> g_registerSubtitleSinkFilter(
    "builtin.player.subtitlesink",       // 注册名
    FilterType::FILTERTYPE_SSINK,         // Filter 类型
    ...
);
```

### 3.2 工作流程

```cpp
DoPrepare():
    subtitleSink_->Init(trackMeta_, eventReceiver_)
    → inputBufferQueueConsumer_ = subtitleSink_->GetBufferQueueConsumer()
    → SetBufferAvailableListener(new AVBufferAvailableListener)  // 驱动 ProcessInputBuffer

DoStart():
    subtitleSink_->Start(); state_ = RUNNING; frameCnt_ = 0

ProcessInputBuffer():
    从 inputBufferQueueConsumer_ 取字幕 buffer
    → subtitleSink_->Write(buffer)  // 渲染字幕
    → frameCnt_++
```

### 3.3 Freeze/UnFreeze

```cpp
DoFreeze()   → subtitleSink_->Pause(); state_ = FROZEN; frameCnt_ = 0
DoUnFreeze() → subtitleSink_->Resume(); state_ = RUNNING; frameCnt_ = 0
```

---

## 4. 录制管线拓扑

```
录音场景（AudioCaptureFilter）:
  AudioStandard::AudioCapturer
    → AudioCaptureModule
      → AudioCaptureFilter ("builtin.recorder.audiocapture")
        → AudioEncoderFilter ("builtin.recorder.audioencoder")
          → MuxerFilter ("builtin.recorder.muxer")

数据源录音场景（AudioDataSourceFilter）:
  上游数据源
    → AudioDataSourceFilter ("builtin.recorder.audiodatasource")
      → AudioEncoderFilter ("builtin.recorder.audioencoder")
        → MuxerFilter ("builtin.recorder.muxer")

视频采集场景（VideoCaptureFilter）:
  VideoCaptureFilter ("builtin.recorder.videocapture") ← FilterType::VIDEO_CAPTURE
    → SurfaceEncoderFilter
      → MuxerFilter ("builtin.recorder.muxer")

播放场景字幕终点:
  字幕源
    → SubtitleSinkFilter ("builtin.player.subtitlesink")
      → 渲染输出
```

---

## 5. 关键常量

| 常量 | 值 | 说明 |
|------|-----|------|
| `AUDIO_CAPTURE_READ_FRAME_TIME` | 20000000 ns (20ms) | 音频帧周期，对应 48kHz 下 960 samples |
| `AUDIO_CAPTURE_READ_FAILED_WAIT_TIME` | 20000000 us | 读失败等待 20ms |
| `AUDIO_CAPTURE_MAX_CACHED_FRAMES` | 256 | 暂停时最大缓存帧数 |
| `AUDIO_RECORDER_FRAME_NUM` | 5 | 录音前预缓存帧数 |