---
id: MEM-ARCH-AVCODEC-S31
title: AudioSinkFilter 音频播放输出过滤器——AudioSink + MediaSynchronousSink + AudioSinkPlugin 三层架构
type: architecture_fact
scope: [AVCodec, MediaEngine, Filter, AudioOutput, Pipeline, MediaSync, Plugin]
status: submitted
author: builder-agent
created: 2026-04-25
updated: 2026-04-25
submitted_at: 2026-04-25T16:06:00+08:00

summary: AudioSinkFilter 是播放 Pipeline 的音频终点过滤器，注册为 "builtin.player.audiosink"，内部封装 AudioSink（实现 MediaSynchronousSink），通过 PluginManagerV2 创建 AudioSinkPlugin("audio/raw")，接入 IMediaSynchronizer 同步链（优先级 AUDIO_SINK=2），提供音量/速度/音效/循环/切轨等播放控制能力。

## 架构位置

AudioSinkFilter 位于播放 Pipeline 的最下游（音频渲染输出），是解码后的音频数据进入硬件渲染前的最后处理节点。

```
DemuxerFilter → AudioDecoderFilter → AudioSinkFilter → [AudioSinkPlugin] → 硬件音频渲染
```

## 三层封装结构

### 第1层：AudioSinkFilter（Filter 子类，Pipeline 组件）

注册为 `"builtin.player.audiosink"`，FilterType 为 `FILTERTYPE_ASINK`：

```cpp
// services/media_engine/filters/audio_sink_filter.cpp 行 36
static AutoRegisterFilter<AudioSinkFilter> g_registerAudioSinkFilter("builtin.player.audiosink",
    FilterType::FILTERTYPE_ASINK, [](const std::string& name, const FilterType type) {
        return std::make_shared<AudioSinkFilter>(name, FilterType::FILTERTYPE_ASINK);
    });
```

关键成员：
- `audioSink_`: `std::shared_ptr<AudioSink>`，内部核心引擎
- `inputBufferQueueConsumer_`: `sptr<AVBufferQueueConsumer>`，接收上游音频帧
- `isRenderCallbackMode_`: bool，调试标志，控制是否使用渲染回调模式（默认 1）
- `isProcessInputMerged_`: bool，调试标志，控制是否合并处理输入（默认 1）

关键控制接口（全部透传到内部 AudioSink）：
- `SetVolume(float)` / `SetVolumeMode(int32_t)` / `SetVolumeWithRamp(float, int32_t)` 音量控制
- `SetSpeed(float)` 播放速度
- `SetAudioEffectMode(int32_t)` / `GetAudioEffectMode(int32_t&)` 音效模式
- `SetMuted(bool)` 静音
- `SetLooping(bool)` 循环播放
- `ChangeTrack(std::shared_ptr<Meta>&)` 音轨切换
- `SetSyncCenter(std::shared_ptr<MediaSyncManager>)` 注入同步管理器
- `GetMaxAmplitude()` 获取最大振幅（用于音量探测）

生命周期方法：
- `DoPrepare()`: 调用 `audioSink_->Prepare()`，向上游 link 暴露 `GetBufferQueueProducer()`
- `DoStart()` / `DoPause()` / `DoResume()` / `DoStop()` / `DoRelease()` 透传到 AudioSink
- `DoProcessInputBuffer(int recvArg, bool dropFrame)`: 调用 `audioSink_->DrainOutputBuffer(dropFrame)` 驱动渲染

### 第2层：AudioSink（MediaSynchronousSink 子类，同步引擎）

`AudioSink` 继承 `Pipeline::MediaSynchronousSink`，实现 `IMediaSynchronizer` 接口，是同步引擎的核心：

```cpp
// interfaces/inner_api/native/audio_sink.h 行 36
class AudioSink : public std::enable_shared_from_this<AudioSink>,
                  public Pipeline::MediaSynchronousSink {
```

**IMediaSynchronizer 优先级设定**：

```cpp
// services/media_engine/modules/sink/audio_sink.cpp 行 80, 90
syncerPriority_ = IMediaSynchronizer::AUDIO_SINK;  // = 2

// i_media_sync_center.h 行 29-30
const static int8_t VIDEO_SINK = 0;
const static int8_t AUDIO_SINK = 2;
```

**插件创建**：

```cpp
// services/media_engine/modules/sink/audio_sink.cpp 行 543-549
std::shared_ptr<Plugins::AudioSinkPlugin> AudioSink::CreatePlugin()
{
    auto plugin = Plugins::PluginManagerV2::Instance().CreatePluginByMime(
        Plugins::PluginType::AUDIO_SINK, "audio/raw");
    return std::reinterpret_pointer_cast<Plugins::AudioSinkPlugin>(plugin);
}
```

**音频数据同步写入**（IMediaSynchronizer 核心）：

```cpp
// services/media_engine/modules/sink/audio_sink.cpp 行 1442-1454
int64_t AudioSink::DoSyncWrite(const std::shared_ptr<OHOS::Media::AVBuffer>& buffer,
                                int64_t& actionClock)
{
    // ...
    MEDIA_LOG_I("audio DoSyncWrite set firstPts = " PUBLIC_LOG_D64, firstPts_);
    // → 调用 AudioSinkPlugin->Write() 写入硬件渲染
}
```

### 第3层：AudioSinkPlugin（Plugin 子类，硬件抽象）

`AudioSinkPlugin` 是 `PluginBase` 子类，通过 `PluginManagerV2` 加载，定义在 `interfaces/plugin/audio_sink_plugin.h`：

```cpp
// interfaces/plugin/audio_sink_plugin.h
struct AudioSinkPlugin : public Plugins::PluginBase {
    virtual Status GetMute(bool& mute) = 0;
    virtual Status SetMute(bool mute) = 0;
    virtual Status GetVolume(float& volume) = 0;
    virtual Status SetVolume(float volume) = 0;
    virtual Status SetVolumeMode(int32_t mode) = 0;
    virtual Status GetSpeed(float& speed) = 0;
    virtual Status SetSpeed(float speed) = 0;
    virtual Status SetAudioRendererInfo(const AudioRendererInfo& rendererInfo) = 0;
    virtual Status GetAudioLatency(uint64_t& latency) = 0;
    virtual Status RenderFrame([[maybe_unused]] const Format& params) = 0;
    // ... 更多音频硬件操作接口
};
```

## 数据流

```
AVBufferQueue（上游）
    ↓ ProcessInputBuffer()
AudioSinkFilter::DoProcessInputBuffer()
    ↓ DrainOutputBuffer(flushed)
AudioSink::DriveBufferCircle()
    ↓ DequeueBuffer → CopyDataToBufferDesc
AudioSink::DoSyncWrite()
    ↓ WriteToPluginRefTimeSync
AudioSinkPlugin::Write()
    ↓ 硬件 Audio Renderer
```

关键时间常量：
- `MAX_BUFFER_DURATION_US = 200000`（200ms 最大缓冲）
- `ANCHOR_UPDATE_PERIOD_US = 200000`（200ms 更新一次时间锚点）
- `kMinAudioClockUpdatePeriodUs = 20 * HST_USECOND`（最小时钟更新周期）
- `kMaxAllowedAudioSinkDelayUs = 1500 * HST_MSECOND`（最大允许延迟 1.5s）

## 同步机制

AudioSink 通过 `MediaSynchronousSink` 基类接入 `MediaSyncManager`：

- `syncerPriority_ = AUDIO_SINK (2)`：音频同步优先级低于视频（VIDEO_SINK = 0）
- `innerSynchroizer_`：内部 `AudioDataSynchroizer`，跟踪缓冲区 PTS 和渲染时钟时间
- `AudioLagDetector`：检测音频延迟
- `UnderrunDetector`：检测音频缓冲区欠载（underrun）事件

## 播放控制

| 控制接口 | 功能说明 |
|---------|---------|
| `SetVolume` | 音量设置（0.0-1.0），会透传到 AudioSinkPlugin |
| `SetVolumeMode` | 音量模式（正常/通话/媒体等） |
| `SetVolumeWithRamp` | 带渐变的音量调整 |
| `SetSpeed` | 播放速度（0.0-∞），>1.0 快进，<1.0 慢放 |
| `SetAudioEffectMode` | 音效模式（无效果/影院/音乐厅等） |
| `SetMuted` | 静音 |
| `SetLooping` | 循环播放 |
| `ChangeTrack` | 切换音轨 |
| `GetMaxAmplitude` | 获取最大音频振幅 |
| `SetLoudnessGain` | 响度增益设置 |
| `SetAudioHapticsSyncId` | 音频触觉同步 ID |
| `SetPlayRange` | 设置播放范围（start/end 时间） |
| `CacheBuffer` | 缓冲预加载 |
| `SetBuffering` | 缓冲状态通知 |

## 状态机

AudioSink 继承 `FilterState`：
- `UNINITIALIZED` → `INITIALIZED` → `RUNNING` → `PAUSED` / `FLUSHED` → `STOPPED` → `ERROR`

## 与 S22（MediaSyncManager）的关系

S22 定义了 `MediaSyncManager`（IMediaSyncCenter + IMediaSynchronizer 链），AudioSinkFilter 通过 `SetSyncCenter()` 注入同步管理器，以 AUDIO_SINK=2 优先级接入全局同步链，与 VideoSink（优先级 0）配合完成音视频同步。

## 与 S18（AudioCodecServer）的区别

- `AudioCodecServer`：服务端编解码服务，处理编码/解码请求（SA 进程）
- `AudioSinkFilter`：播放 Pipeline 的音频渲染输出 Filter，运行在 Player 进程

## evidence

- source: services/media_engine/filters/audio_sink_filter.cpp:36
  anchor: "static AutoRegisterFilter<AudioSinkFilter> g_registerAudioSinkFilter(\"builtin.player.audiosink\", FilterType::FILTERTYPE_ASINK, ...)"
  note: AudioSinkFilter 注册名 "builtin.player.audiosink"，FilterType 为 FILTERTYPE_ASINK

- source: services/media_engine/filters/audio_sink_filter.cpp:282-297
  anchor: "Status AudioSinkFilter::OnLinked(StreamType inType, const std::shared_ptr<Meta>& meta, const std::shared_ptr<FilterLinkCallback>& callback)"
  note: OnLinked 时将 AudioRenderInfo 和 InterruptMode 透传到 meta，调用 Filter::OnLinked 向 LinkCallback 暴露 GetBufferQueueProducer

- source: services/media_engine/filters/audio_sink_filter.cpp:258
  anchor: "Status AudioSinkFilter::DoProcessInputBuffer(int recvArg, bool dropFrame) { audioSink_->DrainOutputBuffer(dropFrame); return Status::OK; }"
  note: DoProcessInputBuffer 直接透传给 AudioSink::DrainOutputBuffer，是播放管线的驱动入口

- source: services/media_engine/filters/audio_sink_filter.cpp:329-332
  anchor: "void AudioSinkFilter::SetSyncCenter(std::shared_ptr<MediaSyncManager> syncCenter) { audioSink_->SetSyncCenter(syncCenter); }"
  note: AudioSinkFilter 将 MediaSyncManager 透传给 AudioSink，接入全局同步链

- source: services/media_engine/filters/audio_sink_filter.cpp:316-324
  anchor: "Status AudioSinkFilter::SetVolume(float volume) { volume_ = volume; auto err = audioSink_->SetVolume(volume); ... }"
  note: 音量控制通过 AudioSink 透传到 AudioSinkPlugin

- source: interfaces/inner_api/native/audio_sink.h:36
  anchor: "class AudioSink : public std::enable_shared_from_this<AudioSink>, public Pipeline::MediaSynchronousSink"
  note: AudioSink 继承 MediaSynchronousSink，实现 IMediaSynchronizer 接口，是音频同步引擎

- source: services/media_engine/modules/sink/audio_sink.cpp:80
  anchor: "syncerPriority_ = IMediaSynchronizer::AUDIO_SINK;"
  note: AudioSink 设置同步优先级为 AUDIO_SINK=2

- source: services/media_engine/modules/sink/audio_sink.cpp:543-549
  anchor: "std::shared_ptr<Plugins::AudioSinkPlugin> AudioSink::CreatePlugin() { auto plugin = Plugins::PluginManagerV2::Instance().CreatePluginByMime(Plugins::PluginType::AUDIO_SINK, \"audio/raw\"); return ...; }"
  note: AudioSink 通过 PluginManagerV2 创建 AudioSinkPlugin("audio/raw")

- source: services/media_engine/modules/sink/audio_sink.cpp:1442-1454
  anchor: "int64_t AudioSink::DoSyncWrite(const std::shared_ptr<OHOS::Media::AVBuffer>& buffer, int64_t& actionClock) { ... MEDIA_LOG_I(\"audio DoSyncWrite set firstPts = \" PUBLIC_LOG_D64, firstPts_); }"
  note: DoSyncWrite 是 IMediaSynchronizer 的核心同步写入方法，将音频帧写入底层插件

- source: services/media_engine/modules/sink/i_media_sync_center.h:29-30
  anchor: "const static int8_t VIDEO_SINK = 0; const static int8_t AUDIO_SINK = 2;"
  note: 同步优先级定义：VIDEO_SINK=0（最高），AUDIO_SINK=2（次高）

- source: services/media_engine/modules/sink/audio_sink.cpp:1242-1268
  anchor: "void AudioSink::DrainOutputBuffer(bool flushed) { ... DriveBufferCircle(); ... MEDIA_LOG_W(\"DrainOutputBuffer, drop audio buffer pts = \" ...); }"
  note: DrainOutputBuffer 驱动音频缓冲圈流转，包含丢帧处理逻辑

- source: services/media_engine/modules/sink/audio_sink.cpp:152
  anchor: "void AudioSink::SyncWriteByRenderInfo() { ... DriveBufferCircle(); }"
  note: DriveBufferCircle 在 SyncWriteByRenderInfo 中被调用，处理音频缓冲区的循环消费

- source: interfaces/plugin/audio_sink_plugin.h
  anchor: "struct AudioSinkPlugin : public Plugins::PluginBase { virtual Status GetMute(bool& mute) = 0; virtual Status SetVolume(float volume) = 0; virtual Status SetSpeed(float speed) = 0; ... }"
  note: AudioSinkPlugin 定义音频渲染硬件抽象接口，包括音量/静音/速度/音效等

- source: services/media_engine/modules/sink/audio_sink.cpp:336
  anchor: "playerEventReceiver_->OnMemoryUsageEvent({\"AUDIO_SINK_BQ\", ...});"
  note: AudioSink 会上报 AUDIO_SINK_BQ 内存使用事件到 DFX 模块

- source: interfaces/inner_api/native/audio_sink.h:50-51
  anchor: "static const int64_t kMinAudioClockUpdatePeriodUs = 20 * HST_USECOND; static const int64_t kMaxAllowedAudioSinkDelayUs = 1500 * HST_MSECOND;"
  note: AudioSink 关键时间常量：最小音频时钟更新周期 20s，最大允许延迟 1.5s
