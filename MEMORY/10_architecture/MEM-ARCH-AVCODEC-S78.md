# MEM-ARCH-AVCODEC-S78: AudioServerSinkPlugin 音频渲染插件

> **ID**: MEM-ARCH-AVCODEC-S78
> **Title**: AudioServerSinkPlugin 音频渲染插件——AudioRenderer 集成、音频焦点中断与设备切换
> **Type**: architecture
> **Scope**: AVCodec, AudioCodec, AudioSink, AudioRenderer, AudioServer, Plugin, Interrupt, Offload, DeviceChange, AudioVivid
> **Status**: draft
> **Created**: 2026-05-03T11:40:00+08:00
> **Tags**: AudioCodec, AudioSinkPlugin, AudioRenderer, AudioServer, Interrupt, Offload, DeviceChange, AudioVivid, Plugin, Pipeline

---

## 核心架构描述（中文）

AudioServerSinkPlugin 是 OpenHarmony AVCodec 音频播放管线末端的硬件抽象插件，注册为 AudioSinkPlugin("audio/raw")，内部持有 OHOS::AudioStandard::AudioRenderer 实例，负责将音频采样数据写入音频服务（AudioServer）进行硬件渲染，同时处理音频焦点中断、输出设备切换、Offload 直通模式等系统级事件。

### 架构位置

```
DemuxerFilter → AudioDecoderFilter → AudioSinkFilter → AudioSink
                                                          └─► [AudioServerSinkPlugin] ──► AudioServer ──► AudioRender
```

**相关现有记忆**：
- S31（AudioSinkFilter）：Filter 层封装，介绍了 AudioSink + MediaSynchronousSink + AudioSinkPlugin 三层架构
- S61（Audio rendering 核心）：AudioSampleFormat / CalcMaxAmplitude / AudioSink 三层引擎

**本记忆（S78）聚焦**：AudioSinkPlugin 的具体实现——AudioServerSinkPlugin 如何创建 AudioRenderer、如何处理音频中断/设备切换/Offload 模式

---

## 源码位置

| 组件 | 路径 |
|------|------|
| 插件实现 | `services/media_engine/plugins/sink/audio_server_sink_plugin.cpp` (1495行) |
| 插件头文件 | `services/media_engine/plugins/sink/audio_server_sink_plugin.h` |
| Plugin 接口定义 | `interfaces/plugin/audio_sink_plugin.h` |
| 音频渲染抽象 | `interfaces/inner_api/native/audio_sink.h` |

---

## AudioServerSinkPlugin 类架构

### 继承关系

```cpp
class AudioServerSinkPlugin : public Plugins::AudioSinkPlugin,
    public std::enable_shared_from_this<AudioServerSinkPlugin>
```

### 关键成员

| 成员 | 类型 | 说明 |
|------|------|------|
| `audioRenderer_` | `std::shared_ptr<AudioStandard::AudioRenderer>` | 音频渲染器句柄，指向 AudioServer 内核 |
| `audioRenderInfo_` | `AudioRenderInfo` | 渲染信息（contentType / streamUsage / rendererFlags） |
| `audioInterruptMode_` | `AudioInterruptMode` | 音频焦点模式（SHARE_MODE / INDEPENDENT_MODE） |
| `volumeMode_` | `AudioVolumeMode` | 音量模式（同步/独立） |
| `audioRenderSetFlag_` | `bool` | 是否设置音频渲染参数 |
| `isTranscodingMode_` | `bool` | 是否转码模式 |

---

## AudioRenderer 创建流程

### 1. Create 入口（Prepare 阶段）

```cpp
// audio_server_sink_plugin.cpp:316
audioRenderer_ = AudioStandard::AudioRenderer::Create(rendererOptions_, appInfo);
```

### 2. AudioRendererOptions 构建

```cpp
// audio_server_sink_plugin.cpp:288-298
AudioRendererOptions rendererOptions_;
rendererOptions_.rendererInfo.contentType = static_cast<AudioStandard::ContentType>(audioRenderInfo_.contentType);
rendererOptions_.rendererInfo.streamUsage = static_cast<AudioStandard::StreamUsage>(audioRenderInfo_.streamUsage);
rendererOptions_.rendererInfo.rendererFlags = audioRenderInfo_.rendererFlags;
```

### 3. Offload 模式判断

```cpp
// audio_server_sink_plugin.cpp:322-326
if (audioRenderSetFlag_ && 
    (audioRenderInfo_.streamUsage == AudioStandard::STREAM_USAGE_MUSIC ||
     audioRenderInfo_.streamUsage == AudioStandard::STREAM_USAGE_AUDIOBOOK)) {
    audioRenderer_->SetOffloadAllowed(true);
} else {
    audioRenderer_->SetOffloadAllowed(false);
}
```

**Offload 条件**：仅 MUSIC / AUDIOBOOK stream usage 时允许 Offload 硬件直通，其他用途走软件混音路径

### 4. Interrupt 模式设置

```cpp
// audio_server_sink_plugin.cpp:328
audioRenderer_->SetInterruptMode(audioInterruptMode_);
```

---

## 音频焦点中断处理

### AudioInterruptMode 映射表

```cpp
// audio_server_sink_plugin.cpp:49-51
const std::pair<AudioInterruptMode, OHOS::AudioStandard::InterruptMode> g_auInterruptMap[] = {
    {AudioInterruptMode::SHARE_MODE, OHOS::AudioStandard::InterruptMode::SHARE_MODE},
    {AudioInterruptMode::INDEPENDENT_MODE, OHOS::AudioStandard::InterruptMode::INDEPENDENT_MODE},
};
```

### AudioRendererCallbackImpl 回调实现

```cpp
// audio_server_sink_plugin.cpp:162-205
class AudioRendererCallbackImpl : public AudioStandard::AudioRendererCallback {
    void OnInterrupt(const OHOS::AudioStandard::InterruptEvent &interruptEvent);
    void OnStateChange(const AudioStandard::RendererState state, 
                       const AudioStandard::StateChangeCmdType cmdType);
    void OnOutputDeviceChange(const AudioDeviceDescriptor &deviceInfo,
                              const AudioStreamDeviceChangeReason reason);
};
```

### Interrupt 事件类型

| ForceType | 含义 | 处理策略 |
|-----------|------|---------|
| FORCE_PAUSE | 强制暂停 | 暂停播放，保存播放位置 |
| FORCE_RESUME | 强制恢复 | 恢复播放 |
| IGNORE | 忽略 | 仅记录日志 |

---

## 输出设备切换处理

```cpp
// audio_server_sink_plugin.cpp:226-229
void AudioServerSinkPlugin::AudioRendererCallbackImpl::OnOutputDeviceChange(
    const AudioStandard::AudioDeviceDescriptor &deviceInfo,
    const AudioStreamDeviceChangeReason reason)
{
    MEDIA_LOG_D_T("DeviceChange reason is " PUBLIC_LOG_D32, static_cast<int32_t>(reason));
    // 通知上游 Filter（通过 playerEventReceiver_）重新配置音频路由
}
```

**设备切换场景**：有线耳机 ↔ 蓝牙耳机 ↔ 扬声器 ↔ USB 声卡

---

## Write 音频数据流

### 写入路径

```
AudioSink::Write() 
  → AudioServerSinkPlugin::Write(inputBuffer)
    → AudioRenderer::Write(inputBuffer->buffer_)
      → AudioServer (跨进程 IPC)
        → AudioRender HAL
          → 硬件音频输出
```

### Write 函数签名

```cpp
// audio_server_sink_plugin.cpp:102
Status AudioServerSinkPlugin::Write(const std::shared_ptr<OHOS::Media::AVBuffer> &inputBuffer);

// AudioVivid 特殊路径
int32_t AudioServerSinkPlugin::WriteAudioVivid(const std::shared_ptr<OHOS::Media::AVBuffer> &inputBuffer);
```

---

## 音量与速度控制

### 音量设置

```cpp
Status AudioServerSinkPlugin::SetVolume(float volume);  // 0.0 ~ 1.0
Status AudioServerSinkPlugin::GetVolume(float &volume);
Status AudioServerSinkPlugin::SetVolumeWithRamp(float targetVolume, int32_t duration); // 音量渐变
```

### 速度控制

```cpp
Status AudioServerSinkPlugin::SetSpeed(float speed);  // 播放倍速
Status AudioServerSinkPlugin::GetSpeed(float &speed);
```

### 音效模式

```cpp
Status AudioServerSinkPlugin::SetAudioEffectMode(int32_t effectMode);
Status AudioServerSinkPlugin::GetAudioEffectMode(int32_t &effectMode);
```

---

## 音频中断状态管理

```cpp
// audio_server_sink_plugin.cpp:144
void AudioServerSinkPlugin::SetInterruptState(bool isInterruptNeeded);
```

**中断状态**：
- `true`：允许音频服务强制暂停当前播放（如来电）
- `false`：忽略音频焦点请求（如后台录音时不打断音乐）

---

## AudioVivid 支持

```cpp
// audio_server_sink_plugin.cpp:104
int32_t WriteAudioVivid(const std::shared_ptr<OHOS::Media::AVBuffer> &inputBuffer);
```

AudioVivid 是华为自主音频格式，AudioServerSinkPlugin 支持通过专用 WriteAudioVivid 路径写入，需要 AudioRenderer 支持 ENCODING_AUDIOVIVID 采样格式。

---

## Plugin 注册机制

```cpp
// PluginManagerV2 通过 MimeType "audio/raw" 路由到 AudioServerSinkPlugin
auto plugin = PluginManagerV2::Instance().CreatePluginByMime(
    Plugins::PluginType::AUDIO_SINK, "audio/raw");
```

**Filter → AudioSink → AudioServerSinkPlugin 三层调用链**：
1. **AudioSinkFilter**（Filter 层）：接收解码后音频帧，管理同步
2. **AudioSink**（Engine 层）：实现 MediaSynchronousSink 同步逻辑，持有 AudioSinkPlugin 指针
3. **AudioServerSinkPlugin**（Plugin 层）：调用 AudioRenderer API，写入 AudioServer

---

## 与现有记忆的关联

| 已有记忆 | 关联内容 |
|---------|---------|
| S31（AudioSinkFilter） | Filter 层入口，内部通过 AudioSink 持有本插件 |
| S61（Audio rendering 核心） | AudioSampleFormat（采样格式）+ CalcMaxAmplitude（峰值计算）未涉及 Plugin 细节 |
| S73（三路 Sink 同步） | MediaSyncManager 协调 AudioSink / VideoSink / SubtitleSink 同步，本插件是 AudioSink 的底层 |
| S21（AVCodec IPC） | AudioRenderer → AudioServer 跨进程路径属于另一个 SA，与 CodecServer IPC 并行 |

---

## 关键工程细节

| 项目 | 数值 |
|------|------|
| 文件行数 | 1495 行 |
| Plugin 类型 | AUDIO_SINK ("audio/raw") |
| AudioRenderer Create 方式 | `AudioStandard::AudioRenderer::Create(rendererOptions_, appInfo)` |
| Offload 支持条件 | MUSIC / AUDIOBOOK stream usage |
| Interrupt 模式数 | 2（SHARE_MODE / INDEPENDENT_MODE） |
| AudioVivid 路径 | 独立 WriteAudioVivid() 函数 |

---

## Evidence 摘要

```yaml
source_files:
  - services/media_engine/plugins/sink/audio_server_sink_plugin.cpp
  - services/media_engine/plugins/sink/audio_server_sink_plugin.h
  - interfaces/plugin/audio_sink_plugin.h

key_classes:
  - AudioServerSinkPlugin (PluginBase subclass)
  - AudioRendererCallbackImpl (AudioRenderer::AudioRendererCallback)

key_functions:
  - AudioRenderer::Create (AudioServer 进程内创建)
  - AudioRenderer::Write (写入音频采样数据)
  - AudioRenderer::SetOffloadAllowed (Offload 直通开关)
  - AudioRenderer::SetInterruptMode (音频焦点模式)
  - AudioServerSinkPlugin::OnInterrupt (焦点中断回调)
  - AudioServerSinkPlugin::OnOutputDeviceChange (设备切换回调)
  - AudioServerSinkPlugin::WriteAudioVivid (AudioVivid 格式写入)
```
