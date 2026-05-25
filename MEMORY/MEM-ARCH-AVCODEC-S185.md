# MEM-ARCH-AVCODEC-S185

status: pending_approval

## 标题

AudioServerSinkPlugin 音频渲染输出插件——AudioStandard::AudioRenderer 集成 + Write 管线 + AVS3DA 特殊路径

## 标签

AVCodec, MediaEngine, AudioSink, AudioServerSinkPlugin, AudioRenderer, Write, AudioVivid, AVS3DA, Resample, AudioResample, g_aduFmtMap, SwrContext, AudioInterrupt, Callback, BufferCache

## 证据列表（行号级）

E1: audio_server_sink_plugin.cpp:54-73 g_aduFmtMap 三元组向量（OH::AudioSampleFormat, OHOS::AudioStandard::AudioSampleFormat, AVSampleFormat）24种音频格式映射
E2: audio_server_sink_plugin.cpp:269 AudioServerSinkPlugin(std::string name) 构造函数
E3: audio_server_sink_plugin.cpp:283-332 Init() AudioRenderer 创建流程（appPid/appUid/contentType/streamUsage/rendererFlags → AudioStandard::AudioRenderer::Create）
E4: audio_server_sink_plugin.cpp:402-430 Prepare() 三回调注册（AudioRendererCallback/AudioFirstFrameWritingCallback/AudioPolicyServerDiedCallback）
E5: audio_server_sink_plugin.cpp:468-475 Start() → audioRenderer_->Start()
E6: audio_server_sink_plugin.cpp:482-490 Stop() → StopRender() → audioRenderer_->Stop()
E7: audio_server_sink_plugin.cpp:931 Resume() / 945 PauseTransitent() / 858 SetVolume() / 912 SetSpeed()
E8: audio_server_sink_plugin.cpp:512 GetParameter() 从 AudioRendererParams 读取采样率/格式/通道数
E9: audio_server_sink_plugin.cpp:576-610 AssignSampleFmtIfSupported() needReformat_ 判断 + reSrcFfFmt_ 源格式 + reStdDestFmt_ 目标格式
E10: audio_server_sink_plugin.cpp:1070-1112 Write() 主方法：AVBuffer 输入 → 空检查 → WriteAudioVivid(AVS3DA) 或 WriteAudioBuffer → DrainCacheData → CacheData
E11: audio_server_sink_plugin.cpp:1115-1126 WriteAudioVivid() → audioRenderer_->Write(pcmBuffer, pcmBufferSize, metaData) 带 AVS3DA 元数据
E12: audio_server_sink_plugin.cpp:1027-1068 WriteAudioBuffer() → audioRenderer_->Write() 循环写入 + ret<destLength 时等待条件变量
E13: audio_server_sink_plugin.cpp:966-1013 DrainCacheData(bool render) 渲染时清空缓存/非渲染时丢弃缓存 + WriteAudioBuffer 循环消费
E14: audio_server_sink_plugin.cpp:1014-1024 CacheData() cachedBuffers_（deque）最多 DEFAULT_BUFFER_NUM=8 个缓存缓冲区
E15: audio_server_sink_plugin.cpp:1372-1394 SetRequestDataCallback() RENDER_MODE_CALLBACK + AudioRendererWriteCallback + SetBufferDuration
E16: audio_server_sink_plugin.cpp:181-202 OnInterrupt(AudioStandard::InterruptEvent) 音频中断处理（FORCE/PAUSE/HINT_PAUSE）
E17: audio_server_sink_plugin.cpp:257 OnAudioPolicyServiceDied() → EVENT_AUDIO_SERVICE_DIED 上报 Pipeline
E18: audio_server_sink_plugin.cpp:631 SetInterruptMode() audioRenderer_->SetInterruptMode()
E19: audio_server_sink_plugin.h:279 std::shared_ptr<Ffmpeg::Resample> resample_ 重采样器（用于格式不匹配时的转换）
E20: audio_server_sink_plugin.cpp:491-511 SetVolumeWithRamp() → audioRenderer_->SetVolumeWithRamp() + fade out sleep

## 源码分析

### 1. 整体架构

S185 覆盖 AudioServerSinkPlugin 音频渲染输出插件，1495 行源码，位于 `services/media_engine/plugins/sink/audio_server_sink_plugin.cpp`（对应 .h 在同目录）。

AudioServerSinkPlugin 是 MediaEngine Filter Pipeline 的**最下游音频输出节点**，负责：
- 将解码后的 PCM 数据写入 AudioStandard::AudioRenderer
- 支持 AudioVivid（AVS3DA）特殊编码格式
- 支持 Callback 模式和 BufferDesc 模式两种渲染方式
- 通过 Resample（SwrContext）处理格式不匹配

S184（FFmpeg Audio Decoder）与本草案对称：S184 是音频解码最上游，S185 是音频渲染最下游；两者通过 S130（FFMpegConverter 工具链）共享音频格式转换能力。

### 2. 核心组件与回调体系

AudioServerSinkPlugin 包含 **4 个内部回调实现类**，全部注册到 AudioStandard::AudioRenderer：

| 回调类 | 继承 | 职责 | 注册行 |
|--------|------|------|--------|
| AudioRendererCallbackImpl | AudioRendererCallback | 音频中断（InterruptEvent）+ 状态变更（StateChange）+ 设备变更（OutputDeviceChange） | Prepare:418-420 |
| AudioFirstFrameCallbackImpl | AudioRendererFirstFrameWritingCallback | 首帧写入时间回调（OnFirstFrameWriting） | Prepare:421-423 |
| AudioServiceDiedCallbackImpl | AudioRendererPolicyServiceDiedCallback | 音频策略服务死亡通知（OnAudioPolicyServiceDied） → Pipeline EVENT_AUDIO_SERVICE_DIED | Prepare:424-426 |
| AudioRendererWriteCallbackImpl | AudioRendererWriteCallback | Callback 模式数据供应（OnWriteData/NotifyFreeze/NotifyUnFreeze/NotifyInterrupt） | SetRequestDataCallback:1384 |

### 3. Write 管线（核心数据流）

```
Write(inputBuffer)
  ├── mimeType == AUDIO_AVS3DA → WriteAudioVivid() → audioRenderer_->Write(pcm, metaData)
  └── WriteAudioBuffer()
        ├── DrainCacheData(true)  // 消费 cachedBuffers_
        │     └── while cached → WriteAudioBuffer() → audioRenderer_->Write()
        ├── audioRenderer_->Write() 循环写入
        │     └── ret < destLength → wait(writeCond_, 5ms) 等音频消费
        └── CacheData() 当写入不充分时缓存剩余数据（最多 8 个缓冲区）
```

**关键设计**（audio_server_sink_plugin.cpp:1070-1112）：
- `Write` 不是直接调用 `audioRenderer_->Write`，而是经过 DrainCacheData + WriteAudioBuffer 两层抽象
- `WriteAudioBuffer` 内部是 while 循环：`destLength > 0` 时反复写入直到全部消费
- 如果写入返回 `ret < destLength`（音频渲染器消费速度慢），会等待 `writeCond_`（5ms 超时）再重试
- `CacheData` 用于缓存未写完的数据，通过 `cachedBuffers_` deque 存储（最多 8 个缓冲区）
- `DrainCacheData(true)` 在每次 Write 入口被调用，消费所有缓存数据后再写入新数据

### 4. AVS3DA（AudioVivid）特殊路径

AVS3DA（AudioVivid）是下一代音频编码格式，AudioServerSinkPlugin 对其有特殊处理：

```cpp
// audio_server_sink_plugin.cpp:1078-1079
if (mimeType_ == MimeType::AUDIO_AVS3DA) {
    ret = WriteAudioVivid(inputBuffer);  // 带元数据的 Write
}

// audio_server_sink_plugin.cpp:1115-1126
int32_t AudioServerSinkPlugin::WriteAudioVivid(const std::shared_ptr<OHOS::Media::AVBuffer> &inputBuffer)
{
    auto meta = inputBuffer->meta_;
    std::vector<uint8_t> metaData;
    meta->GetData(Tag::OH_MD_KEY_AUDIO_VIVID_METADATA, metaData);  // 提取 AVS3DA 元数据
    return audioRenderer_->Write(pcmBuffer, pcmBufferSize, metaData.data(), metaData.size());
    // 注意：Write() 多了元数据参数，EncodingType = ENCODING_AUDIOVIVID_DIRECT
}
```

**EncodingType 映射**（audio_server_sink_plugin.cpp:306）：
```cpp
mimeType_ == MimeType::AUDIO_AVS3DA 
    ? AudioStandard::ENCODING_AUDIOVIVID_DIRECT 
    : AudioStandard::ENCODING_PCM
```

### 5. g_aduFmtMap 音频格式映射表

`g_aduFmtMap`（audio_server_sink_plugin.cpp:54-73）是一个三元组向量，建立 OHOS Media 音频格式 ↔ AudioStandard 音频格式 ↔ FFmpeg AVSampleFormat 的三方映射：

```cpp
const std::vector<std::tuple<AudioSampleFormat, OHOS::AudioStandard::AudioSampleFormat, AVSampleFormat>> g_aduFmtMap = {
    {AudioSampleFormat::SAMPLE_S8,  OHOS::AudioStandard::INVALID_WIDTH,    AV_SAMPLE_FMT_NONE},
    {AudioSampleFormat::SAMPLE_U8,  OHOS::AudioStandard::SAMPLE_U8,          AV_SAMPLE_FMT_U8},
    {AudioSampleFormat::SAMPLE_S16LE, OHOS::AudioStandard::SAMPLE_S16LE,    AV_SAMPLE_FMT_S16},
    {AudioSampleFormat::SAMPLE_S32LE, OHOS::AudioStandard::SAMPLE_S32LE,    AV_SAMPLE_FMT_S32},
    {AudioSampleFormat::SAMPLE_F32P, OHOS::AudioStandard::INVALID_WIDTH,    AV_SAMPLE_FMT_FLTP},  // Planar Float
    {AudioSampleFormat::SAMPLE_F64,  OHOS::AudioStandard::INVALID_WIDTH,    AV_SAMPLE_FMT_DBL},
    // ... 共 24 种格式
};
```

**needReformat_ 判断逻辑**（audio_server_sink_plugin.cpp:576-610）：
- 从 `g_aduFmtMap` 查找目标格式（Plugins::AudioSampleFormat）
- 若 `stdFmt == INVALID_WIDTH` 且 `AV_SAMPLE_FMT != NONE` → `fmtSupported_ = true`，但 `needReformat_ = true`（需 FFmpeg Resample 转换）
- 若 `stdFmt` 不在 AudioRenderer 支持列表 → `fmtSupported_ = false`
- `reSrcFfFmt_` 保存 FFmpeg 源格式，`reStdDestFmt_` 保存 AudioStandard 目标格式

### 6. Resample 重采样器

AudioServerSinkPlugin 持有 `std::shared_ptr<Ffmpeg::Resample> resample_`（audio_server_sink_plugin.h:279），类型为 `Ffmpeg::Resample`，来自 `services/media_engine/plugins/ffmpeg_adapter/common/ffmpeg_convert.h`。

当 `AssignSampleFmtIfSupported` 发现需要格式转换时，设置 `needReformat_ = true`，`resample_` 在后续 Write 管线中被调用执行 SwrContext 重采样。

### 7. AudioVivid Callback 模式

当调用 `SetRequestDataCallback` 时（audio_server_sink_plugin.cpp:1372-1394），Plugin 进入 Callback 模式：

```cpp
audioRenderer_->SetRenderMode(AudioStandard::RENDER_MODE_CALLBACK);
audioRenderer_->SetRendererWriteCallback(audioRenderWriteCallback_);  // AudioRendererWriteCallbackImpl
audioRenderer_->SetBufferDuration(callbackBufferDuration);  // 由 GetCallbackBufferDuration 计算（FLAC 特殊处理）
```

AudioRendererWriteCallbackImpl 的 OnWriteData() 再回调到 AudioSinkDataCallback 的 OnWriteData()，形成双层回调链。

### 8. 生命周期对照表

| 状态 | 方法 | 内部操作 |
|------|------|----------|
| UNINITIALIZED | Init() | AudioRenderer::Create(rendererOptions_, appInfo) |
| INITIALIZED | Prepare() | SetRendererCallback / SetFirstFrameWritingCallback / RegisterAudioPolicyServerDiedCb |
| PREPARED | Start() | audioRenderer_->Start() |
| RUNNING | Write() | DrainCacheData + WriteAudioBuffer → audioRenderer_->Write() |
| RUNNING | Pause() | audioRenderer_->Pause() |
| RUNNING | Resume() | audioRenderer_->Start() |
| RUNNING | Stop() | StopRender() → audioRenderer_->Stop() |
| RUNNING | Reset() | StopRender + ResetAudioRendererParams + resample_.reset() |
| * | Drain() | DrainCacheData(true) |
| * | Flush() | audioRenderer_->Flush() |

## 关联主题

S184（FFmpeg Audio Decoder Plugin 对称架构）、S130（FFMpegConverter 格式转换工具链）、S50（AudioResample SwrContext）、S106（MediaEngine Source 流媒体基础设施）、S183（AvcEncoder H.264 软件编码器，上游生产者）

## 范围标签

新需求开发 / 问题定位 / 音频播放管线 / AudioVivid / 格式不匹配重采样 / AudioRenderer 集成