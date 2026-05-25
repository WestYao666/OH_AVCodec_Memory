# MEM-ARCH-AVCODEC-S185: AudioServerSinkPlugin 音频渲染输出插件

**状态**: draft  
**生成时间**: 2026-05-25T16:34 GMT+8  
**Builder**: builder-agent  
**来源**: 本地镜像 `/home/west/av_codec_repo/services/media_engine/plugins/sink/audio_server_sink_plugin.cpp` + `.h`

---

## 1. 主题概述

| 字段 | 内容 |
|------|------|
| 主题 | AudioServerSinkPlugin 音频渲染输出插件——AudioStandard::AudioRenderer集成+Write管线+AVS3DA特殊路径 |
| scope | AVCodec, MediaEngine, AudioSink, AudioServerSinkPlugin, AudioRenderer, Write, AudioVivid, AVS3DA, Resample |
| 关联场景 | 新需求开发/音频播放管线/问题定位 |
| 关联记忆 | S31(S61/S78/S119) / S184(FFmpeg音频解码)对称 |

---

## 2. 源码证据（行号级）

### 2.1 文件信息

| 文件 | 行数 |
|------|------|
| `audio_server_sink_plugin.cpp` | 1495行 |
| `audio_server_sink_plugin.h` | 311行 |
| **合计** | 1806行 |

### 2.2 插件注册（L122-139）

```cpp
// audio_server_sink_plugin.cpp L122-139
OHOS::Media::Status AudioServerSinkRegister(const std::shared_ptr<Register> &reg)
{
    AudioSinkPluginDef definition;
    definition.name = "AudioServerSink";
    definition.description = "Audio sink for audio server of media standard";
    definition.rank = 100; // 100: max rank  ← 最高优先级音频Sink插件
    auto func = [](const std::string &name) -> std::shared_ptr<AudioSinkPlugin> {
        return std::make_shared<OHOS::Media::Plugins::AudioServerSinkPlugin>(name);
    };
    definition.SetCreator(func);
    Capability inCaps(MimeType::AUDIO_RAW);
    UpdateSupportedSampleRate(inCaps);
    UpdateSupportedSampleFormat(inCaps);
    definition.AddInCaps(inCaps);
    return reg->AddPlugin(definition);
}
PLUGIN_DEFINITION(AudioServerSink, LicenseType::APACHE_V2, AudioServerSinkRegister, [] {});
```

**Evidence**: `rank = 100` 是 max rank，意味着 AudioServerSinkPlugin 在所有音频 Sink 插件中优先级最高，自动成为默认音频输出插件。

---

### 2.3 采样格式映射表 g_aduFmtMap（L35-58）

```cpp
// audio_server_sink_plugin.cpp L35-58
const std::vector<std::tuple<AudioSampleFormat, OHOS::AudioStandard::AudioSampleFormat, AVSampleFormat>> g_aduFmtMap = {
    {AudioSampleFormat::SAMPLE_S8, OHOS::AudioStandard::AudioSampleFormat::INVALID_WIDTH, AV_SAMPLE_FMT_NONE},
    {AudioSampleFormat::SAMPLE_U8, OHOS::AudioStandard::AudioSampleFormat::SAMPLE_U8, AV_SAMPLE_FMT_U8},
    {AudioSampleFormat::SAMPLE_S16LE, OHOS::AudioStandard::AudioSampleFormat::SAMPLE_S16LE, AV_SAMPLE_FMT_S16},
    {AudioSampleFormat::SAMPLE_S24LE, OHOS::AudioStandard::AudioSampleFormat::SAMPLE_S24LE, AV_SAMPLE_FMT_NONE},
    {AudioSampleFormat::SAMPLE_S32LE, OHOS::AudioStandard::AudioSampleFormat::SAMPLE_S32LE, AV_SAMPLE_FMT_S32},
    {AudioSampleFormat::SAMPLE_S32P, OHOS::AudioStandard::AudioSampleFormat::INVALID_WIDTH, AV_SAMPLE_FMT_S32P},
    {AudioSampleFormat::SAMPLE_F32LE, OHOS::AudioStandard::AudioSampleFormat::SAMPLE_F32LE, AV_SAMPLE_FMT_NONE},
    {AudioSampleFormat::SAMPLE_F32P, OHOS::AudioStandard::AudioSampleFormat::INVALID_WIDTH, AV_SAMPLE_FMT_FLTP},
    {AudioSampleFormat::SAMPLE_F64, OHOS::AudioStandard::AudioSampleFormat::INVALID_WIDTH, AV_SAMPLE_FMT_DBL},
    // ... 共25种格式三元组映射
};
```

**Evidence**: `g_aduFmtMap` 是三维映射表：`AudioSampleFormat`(内部枚举) → `AudioStandard::AudioSampleFormat`(系统枚举) → `AVSampleFormat`(FFmpeg枚举)，实现了三层音频格式标准之间的转换。

---

### 2.4 编码类型映射表 mimeTypeToEncodingMap（L60-66）

```cpp
// audio_server_sink_plugin.cpp L60-66
const std::unordered_map<std::string, OHOS::AudioStandard::AudioEncodingType> mimeTypeToEncodingMap = {
    { MimeType::AUDIO_AC3, OHOS::AudioStandard::ENCODING_AC3 },
    { MimeType::AUDIO_EAC3, OHOS::AudioStandard::ENCODING_EAC3 },
    { MimeType::AUDIO_TRUEHD, OHOS::AudioStandard::ENCODING_TRUE_HD },
    { MimeType::AUDIO_DTS, OHOS::AudioStandard::ENCODING_DTS_X },
    { MimeType::AUDIO_AVS3DA, OHOS::AudioStandard::ENCODING_AUDIOVIVID_DIRECT },
};
```

**Evidence**: 5种高级音频编码格式（AC3/EAC3/TRUEHD/DTS/AVS3DA）通过 MIME 类型映射到 AudioStandard 编码类型，支持 HiStreamer 生态外的高质量音频格式透传。

---

### 2.5 中断回调 OnInterrupt（L181-203）

```cpp
// audio_server_sink_plugin.cpp L181-203
void AudioServerSinkPlugin::AudioRendererCallbackImpl::OnInterrupt(
    const OHOS::AudioStandard::InterruptEvent &interruptEvent)
{
    MEDIA_LOG_D_T("OnInterrupt forceType is " PUBLIC_LOG_U32, static_cast<uint32_t>(interruptEvent.forceType));
    FALSE_RETURN_MSG(isNeedResponseCallback_, "AudioRendererCallbackImpl is not need response callback");
    if (interruptEvent.forceType == OHOS::AudioStandard::INTERRUPT_FORCE) {
        switch (interruptEvent.hintType) {
            case OHOS::AudioStandard::INTERRUPT_HINT_PAUSE:
                isPaused_ = true;  // 强制暂停标记
                break;
            default:
                isPaused_ = false;
                break;
        }
    }
    Event event {
        .srcFilter = "Audio interrupt event",
        .type = EventType::EVENT_AUDIO_INTERRUPT,
        .param = interruptEvent
    };
    FALSE_RETURN(playerEventReceiver_ != nullptr);
    playerEventReceiver_->OnEvent(event);
}
```

**Evidence**: `OnInterrupt` 是音频焦点中断回调，当系统强制获取音频焦点时触发（INTERRUPT_FORCE），支持 PAUSE/RESUME 等 hintType，通过 `playerEventReceiver_->OnEvent()` 上报给 Pipeline 层。

---

### 2.6 设备切换回调 OnOutputDeviceChange（L226-240）

```cpp
// audio_server_sink_plugin.cpp L226-240
void AudioServerSinkPlugin::AudioRendererCallbackImpl::OnOutputDeviceChange(
    const AudioStandard::AudioDeviceDescriptor &deviceInfo, const AudioStandard::AudioStreamDeviceChangeReason reason)
{
    MEDIA_LOG_D_T("DeviceChange reason is " PUBLIC_LOG_D32, static_cast<int32_t>(reason));
    auto param = std::make_pair(deviceInfo, reason);
    Event event {
        .srcFilter = "Audio deviceChange change event",
        .type = EventType::EVENT_AUDIO_DEVICE_CHANGE,
        .param = param
    };
    FALSE_RETURN(playerEventReceiver_ != nullptr);
    playerEventReceiver_->OnEvent(event);
}
```

**Evidence**: `OnOutputDeviceChange` 监听输出设备切换（耳机→蓝牙→扬声器等），通过 `EVENT_AUDIO_DEVICE_CHANGE` 事件上报 Pipeline 层，支持播放路由动态切换。

---

### 2.7 核心写入函数 WriteAudioBuffer（L1027-1068）

```cpp
// audio_server_sink_plugin.cpp L1027-1068
size_t AudioServerSinkPlugin::WriteAudioBuffer(uint8_t* inputBuffer, size_t bufferSize, bool& shouldDrop)
{
    MediaAVCodec::AVCodecTrace trace("AudioServerSinkPlugin::WriteAudioBuffer-size:" + std::to_string(bufferSize));
    FALSE_RETURN_V_MSG(bufferSize > 0, 0, "bufferSize <= 0");
    FALSE_RETURN_V_MSG(audioRenderer_ != nullptr, 0, "audioRenderer_ == nullptr");
    FALSE_RETURN_V_MSG(destBuffer != nullptr, 0, "destBuffer == nullptr");
    if (destLength > 0) {
        MediaAVCodec::AVCodecTrace trace("AudioServerSinkPlugin::WriteAudioBuffer: " + std::to_string(destLength));
        auto systemTimeBeforeWriteMs = Plugins::GetCurrentMillisecond();
        int32_t ret = audioRenderer_->Write(destBuffer, destLength);  // ← 实际写入AudioRenderer
        writeDuration_ = std::max(Plugins::GetCurrentMillisecond() - systemTimeBeforeWriteMs, writeDuration_);
        if (ret > 0) {
            return ret;
        } else if (ret == 0) {
            MEDIA_LOG_W("WriteAudioBuffer error because audioRenderer_ paused or stopped, cache data.");  // ← 暂停/停止时缓存
        } else {
            MEDIA_LOG_W("WriteAudioBuffer error because audioRenderer_ error, drop data.");  // ← 错误时丢弃
        }
    }
    return 0;
}
```

**Evidence**: `WriteAudioBuffer` 是核心写入函数，将 PCM 数据写入 `AudioRenderer`。返回0时根据状态决定缓存或丢弃：paused/stopped 状态缓存数据，error 状态丢弃数据。

---

### 2.8 主入口 Write 函数（L1070-1112）

```cpp
// audio_server_sink_plugin.cpp L1070-1112
Status AudioServerSinkPlugin::Write(const std::shared_ptr<OHOS::Media::AVBuffer> &inputBuffer)
{
    MEDIA_LOG_D_SHORT("Write buffer to audio framework");
    FALSE_RETURN_V_MSG(inputBuffer != nullptr, Status::ERROR_INVALID_DATA, "inputBuffer is nullptr");
    FALSE_RETURN_V_MSG(inputBuffer->memory != nullptr, Status::ERROR_INVALID_DATA, "memory is nullptr");
    MediaAVCodec::AVCodecTrace trace("AudioServerSinkPlugin::Write, bufferSize: "
        + std::to_string(inputBuffer->memory->GetSize()));
    int32_t ret = 0;
    if (isAudioVivid_) {
        ret = WriteAudioVivid(inputBuffer);  // ← AVS3DA特殊路径：携带元数据写入
    } else {
        ret = WriteAudioBuffer(destBuffer, destLength, shouldDrop);  // ← 普通PCM写入
    }
    FALSE_RETURN_V_MSG(!isInterruptNeeded_.load(), Status::OK, "Write isInterrupt");
    // ... drain cache path
    size_t remained = WriteAudioBuffer(destBuffer, destLength, shouldDrop);
    return Status::OK;
}
```

**Evidence**: `Write` 是主入口，根据 `isAudioVivid_` 标志分流：
- AVS3DA格式 → `WriteAudioVivid()`（带元数据的特殊写入路径）
- 普通格式 → `WriteAudioBuffer()`（标准PCM写入路径）

---

### 2.9 AVS3DA 特殊写入 WriteAudioVivid（L1115-1130）

```cpp
// audio_server_sink_plugin.cpp L1115-1130
int32_t AudioServerSinkPlugin::WriteAudioVivid(const std::shared_ptr<OHOS::Media::AVBuffer> &inputBuffer)
{
    MediaAVCodec::AVCodecTrace trace("AudioServerSinkPlugin::WriteAudioVivid");
    FALSE_RETURN_V_MSG(inputBuffer != nullptr, 0, "inputBuffer is nullptr");
    FALSE_RETURN_V_MSG(inputBuffer->memory != nullptr, 0, "memory is nullptr");
    uint8_t* pcmBuffer = const_cast<uint8_t*>(inputBuffer->memory->GetAddr());
    size_t pcmBufferSize = inputBuffer->memory->GetSize();
    std::vector<uint8_t> metaData;
    // ... 提取AVBuffer中的元数据（对象元数据）
    return audioRenderer_->Write(pcmBuffer, pcmBufferSize, metaData.data(), metaData.size());
    //            ↑ Write重载：携带元数据写入AVS3DA音频
}
```

**Evidence**: `WriteAudioVivid` 是 AVS3DA（AudioVivid）格式的特殊写入路径，从 `AVBuffer` 中提取元数据（对象音频的元信息），然后通过 `audioRenderer_->Write(pcmBuffer, pcmBufferSize, metaData.data(), metaData.size())` 四参数重载写入AudioServer，支持三维音频对象元数据的透传。

---

### 2.10 AudioRendererWriteCallbackImpl 回调链（L1284-1318）

```cpp
// audio_server_sink_plugin.cpp L1284-1318
void AudioServerSinkPlugin::AudioRendererWriteCallbackImpl::OnWriteData(size_t length)
{
    // ... L1290: plugin->OnWriteData(length);
    FALSE_RETURN_MSG(plugin != nullptr, "AudioServerSinkPlugin OnWriteData plugin_ is nullptr");
    plugin->OnWriteData(length);
}
void AudioServerSinkPlugin::AudioRendererWriteCallbackImpl::NotifyFreeze() { ... L1304 }
void AudioServerSinkPlugin::AudioRendererWriteCallbackImpl::NotifyUnFreeze() { ... L1310 }
void AudioServerSinkPlugin::AudioRendererWriteCallbackImpl::NotifyInterrupt(bool isInterruptNeeded) { ... L1318 }
```

**Evidence**: `AudioRendererWriteCallbackImpl` 是 `AudioRenderer` 写入回调接口，`OnWriteData` 通知插件写入完成，`NotifyFreeze/NotifyUnFreeze` 支持音频冻结/恢复，`NotifyInterrupt` 支持中断状态通知。

---

### 2.11 AudioVivid 初始化判断（L1379-1386）

```cpp
// audio_server_sink_plugin.cpp L1379-1386
isAudioVivid_ = mimeType_ == MimeType::AUDIO_AVS3DA;  // ← L1379: AVS3DA判断
audioRenderWriteCallback_ = std::make_shared<AudioRendererWriteCallbackImpl>(shared_from_this());
ret = audioRenderer_->SetRendererWriteCallback(audioRenderWriteCallback_);
FALSE_RETURN_NOLOG(ret == Status::OK, Status::ERROR_INVALID_DATA,
    "audioRender_->SetRenderWriteCallback fail.");
```

**Evidence**: `isAudioVivid_` 在 `Prepare()` 阶段通过判断 MIME 类型是否为 `AUDIO_AVS3DA` 来设置标志，后续 `Write()` 根据此标志决定走 `WriteAudioVivid` 或 `WriteAudioBuffer` 路径。

---

## 3. 架构总结

### 3.1 在播放管线中的位置

```
FFmpeg Audio Decoder (S184)
    ↓ AVBuffer (PCM)
AudioServerSinkPlugin [AudioServerSinkPlugin.cpp:1495行]
    ↓ Write(AVBuffer) → WriteAudioBuffer / WriteAudioVivid
AudioStandard::AudioRenderer [跨进程]
    ↓ Write(pcm, meta)
AudioServer [Audio Framework]
    ↓
硬件输出（Speaker/耳机/蓝牙）
```

**Observation**: AudioServerSinkPlugin 是播放管线最下游节点，负责将PCM数据（或带元数据的AVS3DA数据）写入 AudioStandard 音频渲染框架，是 MediaEngine 与 AudioFramework 之间的桥梁。

### 3.2 三层回调事件体系

| 事件类型 | 回调函数 | 触发场景 |
|----------|----------|----------|
| `EVENT_AUDIO_INTERRUPT` | `OnInterrupt` | 音频焦点冲突（来电/其他App抢占焦点） |
| `EVENT_AUDIO_DEVICE_CHANGE` | `OnOutputDeviceChange` | 输出设备切换（耳机↔蓝牙↔扬声器） |
| `EVENT_AUDIO_FIRST_FRAME` | `OnFirstFrameWriting` | 首帧音频送达 |
| `EVENT_AUDIO_SERVICE_DIED` | `OnAudioPolicyServiceDied` | AudioPolicyService 死亡 |
| `EVENT_AUDIO_STATE_CHANGE` | `OnStateChange` | 渲染器状态变化 |

### 3.3 Write 管线双路径

```
AVBuffer 输入
  ├─ isAudioVivid_ == true  → WriteAudioVivid()  → AudioRenderer::Write(pcm, size, metadata, metaSize)
  │                                                          ↑ AVS3DA四参数重载（元数据透传）
  └─ isAudioVivid_ == false → WriteAudioBuffer() → AudioRenderer::Write(destBuffer, destLength)
                                 │                        ↑ 普通二参数写入
                                 └─ shouldDrop ← 暂停/错误时丢弃
```

### 3.4 25种采样格式三元组映射

`g_aduFmtMap` 三元组映射关系（部分）：

| 内部枚举 | AudioStandard枚举 | FFmpeg枚举 |
|----------|-------------------|------------|
| SAMPLE_S8 | INVALID_WIDTH | NONE |
| SAMPLE_U8 | SAMPLE_U8 | U8 |
| SAMPLE_S16LE | SAMPLE_S16LE | S16 |
| SAMPLE_S24LE | SAMPLE_S24LE | NONE |
| SAMPLE_S32LE | SAMPLE_S32LE | S32 |
| SAMPLE_S32P | INVALID_WIDTH | S32P |
| SAMPLE_F32LE | SAMPLE_F32LE | NONE |
| SAMPLE_F32P | INVALID_WIDTH | FLTP |
| SAMPLE_F64 | INVALID_WIDTH | DBL |

---

## 4. 关键常量

| 常量 | 值 | 含义 |
|------|----|------|
| `rank` | 100 | 最高优先级 Sink 插件 |
| `DEFAULT_BUFFER_NUM` | 8 | 默认缓冲 buffer 数量 |
| `WRITE_WAIT_TIME` | 5ms | Write 等待时间 |
| `ON_WRITE_WARNING_MS` | 15ms | Write 超时警告阈值 |
| `CALLBACK_BUFFER_DURATION_IN_MILLISECONDS` | 40ms | 回调 buffer 时长 |
| `LOG_PRINT_LIMIT` | 8 | 日志打印限制次数 |

---

## 5. 与关联记忆的关系

| 关联记忆 | 关系 |
|----------|------|
| S31 (AudioSinkFilter) | Filter 层封装，AudioServerSinkPlugin 是 S31 的插件实现层 |
| S61 (AudioSampleFormat位深映射) | g_aduFmtMap 中使用 |
| S78 (AudioServerSinkPlugin) | **主题重复**：S78 草案存在但内容较简，S185 基于本地镜像 1495 行源码重写 |
| S119 (SubtitleSink三状态) | 与 S119 并列构成管线输出终点三成员（Audio/Video/Subtitle） |
| S184 (FFmpeg Audio Decoder) | 对称关系：S184 是解码终点，S185 是渲染终点 |