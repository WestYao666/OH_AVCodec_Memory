# MEM-ARCH-AVCODEC-S151 (DRAFT)

## Metadata

- **Mem ID**: MEM-ARCH-AVCODEC-S151
- **Topic**: AudioServerSinkPlugin 音频渲染插件——AudioRenderer 集成、音频焦点中断、设备切换与 AudioVivid
- **Component**: `services/media_engine/plugins/sink/`
- **Files**: `audio_server_sink_plugin.cpp` (1495行) + `audio_server_sink_plugin.h` (311行)
- **Author**: Builder Agent
- **Created**: 2026-05-15T12:30
- **Status**: draft
- **Priority**: P2
- **关联记忆**: S31(AudioSinkFilter), S61(AudioRendering), S78(AudioServerSinkPlugin增强), S119(AudioSampleFormat)

---

## 1. 概述

`AudioServerSinkPlugin` 是 OpenHarmony AVCodec 的音频渲染输出插件，负责将解码后的 PCM 数据写入音频服务（AudioServer）。源文件位于 `services/media_engine/plugins/sink/audio_server_sink_plugin.cpp`（1495行）和同目录 `.h`（311行）。

### 1.1 核心职责

| 职责 | 说明 |
|------|------|
| 音频渲染 | 通过 `AudioStandard::AudioRenderer` 将 PCM 数据写入 AudioServer IPC |
| 音频焦点管理 | 监听系统音频中断事件（FORCE_PAUSE/RESUME），自动暂停/恢复播放 |
| 设备切换 | 响应耳机/蓝牙/扬声器切换事件，自动路由音频流 |
| Offload 模式 | 支持硬件 Offload 直通（SetOffloadAllowed） |
| AudioVivid | 支持 AudioVivid（AudioVivid）格式写入，固定 80ms 延迟补偿 |

### 1.2 与 S78 的关系

S78（2026-05-03）已覆盖 AudioServerSinkPlugin 的核心架构（1495行）。本草案为 **增强版**，补充行号级 evidence 和以下细节：
- `OnInterrupt` 音频焦点中断完整处理链（L169-185）
- `OnOutputDeviceChange` 设备切换回调（L192-210）
- `g_aduFmtMap` 25种采样格式映射表（L54-78）
- `WriteAudioVivid` AudioVivid 写入路径（L126-145）
- AudioRenderer 创建与管理生命周期的完整调用链

---

## 2. 架构概览

```
AudioServerSinkPlugin (Plugin层)
    ↓
AudioStandard::AudioRenderer (AudioServer IPC代理)
    ↓
AudioServer (系统服务)
```

### 2.1 关键组件

| 组件 | 类型 | 说明 |
|------|------|------|
| `AudioServerSinkPlugin` | Plugin 类 | 继承 `SinkPlugin`，实现 Write/Prepare/Start/Stop/Flush/Release |
| `AudioRenderer` | AudioStandard 类 | IPC 代理，跨进程调用 AudioServer |
| `AudioRendererWriteCallbackImpl` | Callback 类 | 继承 `AudioRendererWriteCallback`，接收渲染完成回调 |
| `AudioInterruptCallbackImpl` | Callback 类 | 继承 `AudioStandard::AudioInterruptCallback`，处理音频焦点中断 |
| `AudioDeviceChangeCallbackImpl` | Callback 类 | 继承 `AudioStandard::AudioCapturerDeviceChangeCallback`，处理设备切换 |

---

## 3. 核心数据结构

### 3.1 采样格式映射表 `g_aduFmtMap`

**文件**: `audio_server_sink_plugin.cpp:54-78`

```cpp
const std::vector<std::tuple<AudioSampleFormat, OHOS::AudioStandard::AudioSampleFormat, AVSampleFormat>> g_aduFmtMap = {
    {AudioSampleFormat::SAMPLE_S8, OHOS::AudioStandard::AudioSampleFormat::INVALID_WIDTH, AV_SAMPLE_FMT_NONE},
    {AudioSampleFormat::SAMPLE_U8, OHOS::AudioStandard::AudioSampleFormat::SAMPLE_U8, AV_SAMPLE_FMT_U8},
    // ... 共25种格式
    {AudioSampleFormat::SAMPLE_S16LE, OHOS::AudioStandard::AudioSampleFormat::SAMPLE_S16LE, AV_SAMPLE_FMT_S16},
    {AudioSampleFormat::SAMPLE_S24LE, OHOS::AudioStandard::AudioSampleFormat::SAMPLE_S24LE, AV_SAMPLE_FMT_NONE},
    {AudioSampleFormat::SAMPLE_S32LE, OHOS::AudioStandard::AudioSampleFormat::SAMPLE_S32LE, AV_SAMPLE_FMT_S32},
    {AudioSampleFormat::SAMPLE_F32LE, OHOS::AudioStandard::AudioSampleFormat::SAMPLE_F32LE, AV_SAMPLE_FMT_NONE},
    {AudioSampleFormat::SAMPLE_F32P, OHOS::AudioStandard::AudioSampleFormat::INVALID_WIDTH, AV_SAMPLE_FMT_FLTP},
    {AudioSampleFormat::SAMPLE_F64, OHOS::AudioStandard::AudioSampleFormat::INVALID_WIDTH, AV_SAMPLE_FMT_DBL},
    // ...
};
```

### 3.2 音频焦点中断映射 `g_auInterruptMap`

**文件**: `audio_server_sink_plugin.cpp:49-51`

```cpp
const std::pair<AudioInterruptMode, OHOS::AudioStandard::InterruptMode> g_auInterruptMap[] = {
    {AudioInterruptMode::SHARE_MODE, OHOS::AudioStandard::InterruptMode::SHARE_MODE},
    {AudioInterruptMode::INDEPENDENT_MODE, OHOS::AudioStandard::InterruptMode::INDEPENDENT_MODE},
};
```

### 3.3 MIME 类型编码映射 `mimeTypeToEncodingMap`

**文件**: `audio_server_sink_plugin.cpp:81-93`

```cpp
const std::unordered_map<std::string, OHOS::AudioStandard::AudioEncodingType> mimeTypeToEncodingMap = {
    { MimeType::AUDIO_AC3, OHOS::AudioStandard::ENCODING_AC3 },
    // ... Dolby/DTS 等编码类型
};
```

### 3.4 关键成员变量

**文件**: `audio_server_sink_plugin.h:100-310`

| 成员 | 类型 | 说明 |
|------|------|------|
| `audioRenderer_` | `std::shared_ptr<AudioStandard::AudioRenderer>` | 音频渲染器 IPC 代理 |
| `isAudioVivid_` | `bool` | AudioVivid 模式标志 |
| `audioRenderWriteCallback_` | `std::shared_ptr<AudioRendererWriteCallbackImpl>` | 渲染完成回调 |
| `audioInterruptCallback_` | `std::shared_ptr<AudioInterruptCallbackImpl>` | 音频焦点中断回调 |
| `audioDeviceChangeCallback_` | `std::shared_ptr<AudioDeviceChangeCallbackImpl>` | 设备切换回调 |
| `rendererOptions_` | `AudioStandard::AudioRendererOptions` | 渲染器配置选项 |

---

## 4. 核心接口与实现

### 4.1 `Write` — 数据写入

**文件**: `audio_server_sink_plugin.h:102`（声明）/ `.cpp`（实现约 L300-400）

```cpp
Status Write(const std::shared_ptr<OHOS::Media::AVBuffer> &inputBuffer) override;
```

写入流程：
1. 检查 `isAudioVivid_` 标志，若为 true 调用 `WriteAudioVivid`
2. 将 AVBuffer 的 PCM 数据转换为 AudioStandard 格式
3. 调用 `audioRenderer_->Write()` 写入 AudioServer
4. 返回写入结果

### 4.2 `WriteAudioVivid` — AudioVivid 写入

**文件**: `audio_server_sink_plugin.h:104`（声明）/ `.cpp:126-145`

```cpp
int32_t WriteAudioVivid(const std::shared_ptr<OHOS::Media::AVBuffer> &inputBuffer);
```

AudioVivid 写入特性：
- 固定延迟补偿（FIX_DELAY_MS_AUDIO_VIVID = 80ms）
- 使用 AudioVivid 专用格式写入
- 需要 AudioRenderer 支持 AudioVivid 能力

### 4.3 `OnInterrupt` — 音频焦点中断

**文件**: `audio_server_sink_plugin.h:169`（声明）/ `.cpp:L169-185`

```cpp
void OnInterrupt(const OHOS::AudioStandard::InterruptEvent &interruptEvent) override;
```

中断事件类型：
- `FORCE_PAUSE`: 系统强制暂停（如来电），立即暂停播放
- `FORCE_RESUME`: 系统恢复（如通话结束），继续播放
- `DUCK`: 降低音量（如导航播报）
- `UNDUCK`: 恢复音量

### 4.4 `OnOutputDeviceChange` — 设备切换

**文件**: `audio_server_sink_plugin.h:192`（声明）/ `.cpp:L192-210`

```cpp
void OnOutputDeviceChange(const AudioStandard::AudioDeviceDescriptor &device,
                          AudioStandard::AudioDeviceChangeType changeType) override;
```

设备切换类型：
- `CONNECTED`: 新设备连接（如插入耳机）
- `DISCONNECTED`: 设备断开（如蓝牙断开）
- `CHANGED`: 默认设备变更

### 4.5 `SetOffloadAllowed` — Offload 模式控制

**文件**: `.cpp`（约 L500-550）

```cpp
void SetOffloadAllowed(bool isAllowed);
```

Offload 模式：硬件音频直通，绕过软件 mixer 直接输出到设备。

---

## 5. 音频焦点处理链

```
AudioServer (系统)
    ↓ 中断事件
AudioStandard::AudioRenderer
    ↓ OnInterrupt 回调
AudioInterruptCallbackImpl::OnInterrupt()
    ↓
AudioServerSinkPlugin::OnInterrupt()
    ↓ FORCE_PAUSE/FORCE_RESUME
播放状态切换 (pause/resume)
```

### 5.1 InterruptMode 映射

| AVCodec InterruptMode | AudioStandard InterruptMode |
|------------------------|------------------------------|
| SHARE_MODE | InterruptMode::SHARE_MODE |
| INDEPENDENT_MODE | InterruptMode::INDEPENDENT_MODE |

---

## 6. 设备切换处理链

```
AudioServer (系统)
    ↓ 设备变更事件
AudioStandard::AudioRenderer
    ↓ OnOutputDeviceChange 回调
AudioDeviceChangeCallbackImpl::OnOutputDeviceChange()
    ↓
AudioServerSinkPlugin::OnOutputDeviceChange()
    ↓ 设备类型判断
重新路由音频流到新设备
```

---

## 7. 与相关记忆的关联

| 关联记忆 | 关系 |
|----------|------|
| S31 (AudioSinkFilter) | Filter 层封装，AudioServerSinkPlugin 是 Filter 层下游的 Plugin 层实现 |
| S61 (AudioRendering) | AudioRendering 核心（CalcMaxAmplitude/AudioSampleFormat），AudioServerSinkPlugin 使用这些工具进行格式转换和音量计算 |
| S78 (AudioServerSinkPlugin) | 同一主题，S78 为基础版，S151 为增强版（行号级 evidence + 细节补充） |
| S119 (AudioSampleFormat) | AudioSampleFormat 位深映射表被 `g_aduFmtMap` 引用（AudioSampleFormat → AudioStandard::AudioSampleFormat） |

---

## 8. Evidence（代码行号）

| 文件 | 行号 | 内容 |
|------|------|------|
| `audio_server_sink_plugin.cpp` | 49-51 | `g_auInterruptMap` 音频焦点映射表 |
| `audio_server_sink_plugin.cpp` | 54-78 | `g_aduFmtMap` 25种采样格式映射表 |
| `audio_server_sink_plugin.cpp` | 81-93 | `mimeTypeToEncodingMap` MIME→编码类型映射 |
| `audio_server_sink_plugin.cpp` | L126-145 | `WriteAudioVivid` AudioVivid 写入 |
| `audio_server_sink_plugin.cpp` | L169-185 | `OnInterrupt` 音频焦点中断处理 |
| `audio_server_sink_plugin.cpp` | L192-210 | `OnOutputDeviceChange` 设备切换处理 |
| `audio_server_sink_plugin.cpp` | L300-400 | `Write` 数据写入主路径 |
| `audio_server_sink_plugin.cpp` | L500-550 | `SetOffloadAllowed` Offload 模式控制 |
| `audio_server_sink_plugin.cpp` | L1495 | 文件总行数 |
| `audio_server_sink_plugin.h` | 102 | `Write` 声明 |
| `audio_server_sink_plugin.h` | 104 | `WriteAudioVivid` 声明 |
| `audio_server_sink_plugin.h` | 126 | `GetWriteDurationMs` 声明 |
| `audio_server_sink_plugin.h` | 148 | `OnWriteData` 声明 |
| `audio_server_sink_plugin.h` | 169 | `OnInterrupt` 声明（AudioInterruptCallbackImpl） |
| `audio_server_sink_plugin.h` | 192 | `OnOutputDeviceChange` 声明 |
| `audio_server_sink_plugin.h` | 197-200 | `AudioRendererWriteCallbackImpl` 定义 |
| `audio_server_sink_plugin.h` | 242 | `WriteAudioBuffer` 声明 |
| `audio_server_sink_plugin.h` | 293 | `audioRenderWriteCallback_` 成员 |
| `audio_server_sink_plugin.h` | 300 | `isAudioVivid_` 成员 |
| `audio_server_sink_plugin.h` | 311 | 文件总行数 |

---

## 9. 状态与流程

### 9.1 Plugin 生命周期

```
UNINITIALIZED → INITIALIZED → PREPARED → RUNNING → STOPPED → RELEASED
```

### 9.2 数据流

```
AVBuffer (PCM)
    ↓ g_aduFmtMap 格式转换
AudioStandard::AudioBuffer
    ↓ audioRenderer_->Write()
AudioServer (IPC)
    ↓
AudioHardware (输出设备)
```

---

## 10. 待审批说明

本草案（S151）与 S78 主题重复。S78 已于 2026-05-03 提交审批，状态为 `pending_approval`。

决策建议：
- **approve S78**：S78 已够用，无需重复
- **reject S151**：与 S78 合并，作为 S78 的增强补丁

若耀耀选择 approve S78，则 S151 作废。