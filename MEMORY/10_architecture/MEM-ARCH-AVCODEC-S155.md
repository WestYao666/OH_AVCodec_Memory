# MEM-ARCH-AVCODEC-S155: MediaEngine Sink/Source 核心模块架构——三路Sink同步引擎与Source协议路由

**状态**: draft
**生成时间**: 2026-05-15T20:55+08:00
**Builder**: builder-agent
**关联主题**: S31(S61/S78/S119) / S32(S49/S56/S73/S118/S116) / S22(MediaSyncManager) / S37(S86/S106/S122/S87) / S41(S69/S75/S76/S79) / S124(S23/S24) / S34/S65/S40/S91

---

## 一、三路 Sink 同步引擎架构

MediaEngine 的 Sink 模块负责音视频字幕的最终渲染输出，由 `modules/sink/` 目录下的六个核心文件组成。三路 Sink（VideoSink/AudioSink/SubtitleSink）均继承自 `MediaSynchronousSink`，在 `MediaSyncManager` 的协调下按优先级同步工作。

### 1.1 核心文件清单

| 文件 | 行数 | 职责 |
|------|------|------|
| `video_sink.cpp` | 462行 | 视频渲染同步器，DoSyncWrite渲染决策 |
| `audio_sink.cpp` | 1793行 | 音频渲染同步器，AudioVivid/焦点中断 |
| `subtitle_sink.cpp` | 517行 | 字幕渲染同步器，WAIT/SHOW/DROP三状态 |
| `media_synchronous_sink.cpp` | ~120行 | 同步基类，IMediaSynchronizer接口 |
| `media_sync_manager.cpp` | 491行 | 音视频同步管理中心，优先级调度 |
| `i_media_sync_center.h` | ~80行 | IMediaSyncCenter时间锚点接口 |

### 1.2 三路 Sink 优先级体系

**证据** (`media_sync_manager.cpp`):
- 优先级枚举：`VIDEO_SINK=0` / `AUDIO_SINK=2` / `SUBTITLE_SINK=8`
- VideoSink 是播放管线时钟锚点供应方（priority=0），AudioSink 次之（priority=2），SubtitleSink 最低（priority=8）

### 1.3 VideoSink 渲染决策算法

**核心类**：`VideoSink`（继承 `MediaSynchronousSink`）

**证据** (`video_sink.cpp`):
- `DoSyncWrite()` — 渲染决策主函数，调用 `CheckBufferLatenessMayWait` 计算 early/late
- `CalcBufferDiff()` — 三元组算法（anchorDiff/videoDiff/thresholdAdjustedVideoDiff）
- 前4帧强制渲染：`VIDEO_SINK_START_FRAME=4`
- `LAG_LIMIT_TIME=100ms` — 卡顿检测阈值

**内嵌类** `VideoLagDetector`：追踪视频卡顿，输出 lag 日志

**证据** (`video_sink.cpp:180-230`):
```cpp
class VideoLagDetector {
    void UpdateLag(bool isLagging);  // 更新卡顿状态
    bool DetectLag();                // 卡顿检测
};
```

### 1.4 AudioSink 音频渲染核心

**核心类**：`AudioSink`（继承 `MediaSynchronousSink`）

**证据** (`audio_sink.cpp`):
- `FIX_DELAY_MS_AUDIO_VIVID=80ms` — AudioVivid 固定延迟补偿
- `WriteAudioVivid()` — AudioVivid 格式写入（多声道/高采样率）
- `OnInterrupt()` — 音频焦点中断回调（FORCE_PAUSE / RESUME）
- `OnOutputDeviceChange()` — 设备切换（耳机/蓝牙/扬声器）
- `SetOffloadAllowed()` — Offload 硬件直通配置

**采样格式映射表** (`audio_sampleformat.cpp:54-78`):
- 25 种采样格式 → 位深映射（8/16/24/32/64bit）
- `CalcMaxAmplitude()` — PCM 峰值振幅计算（4种位深）

### 1.5 SubtitleSink 字幕渲染环

**核心类**：`SubtitleSink`（继承 `MediaSynchronousSink`）

**证据** (`subtitle_sink.cpp`):
- `RenderLoop` 独立线程：`SUBTITME_LOOP_RUNNING` 状态标志
- `SubtitleBufferState` 三状态：`WAIT` / `SHOW` / `DROP`
- `RemoveTextTags()` — HTML 标签剥离（<br>/<font>等）
- `NotifyRender()` — 上报 `Tag::SUBTITLE_TEXT` 事件

### 1.6 MediaSyncManager 时钟锚点管理

**核心类**：`MediaSyncManager`（单例）

**证据** (`media_sync_manager.cpp:100-150`):
- `UpdateTimeAnchor()` — 锚点建立，PTS 换算
- `DoSyncWrite()` / `CheckBufferLatenessMayWait()` — early/late 判断
- 三路 `IMediaSynchronizer` 优先级注册

---

## 二、Source 模块协议路由架构

`modules/source/` 目录包含 Source 顶层封装和 AudioCaptureModule 音频采集模块。

### 2.1 Source 核心文件

| 文件 | 行数 | 职责 |
|------|------|------|
| `source.cpp` | 715行 | 媒体源顶层封装，协议路由 |
| `source.h` | 184行 | Source 基类定义 |
| `audio_capture/audio_capture_module.cpp` | 509行 | 实时音频采集引擎 |
| `audio_capture/audio_capture_module.h` | 95行 | AudioCaptureModule 类定义 |
| `audio_capture/audio_type_translate.cpp` | 112行 | 音频类型转换 |
| `audio_capture/audio_type_translate.h` | 34行 | AudioTypeTranslate 类定义 |

### 2.2 Source 协议路由机制

**证据** (`source.cpp:100-200`):
- `ParseProtocol()` — 五协议路由（http/https/file/fd/stream）
- `g_protocolStringToType` 映射表：字符串 → ProtocolType
- `FindPlugin()` → `PluginManagerV2::CreatePluginByMime(SOURCE)` 插件创建

**SourcePlugin 基接口**（20+ 纯虚函数）：
- `Read()` / `Seek()` / `GetSize()` / `SelectBitRate()` / `Pause()` / `Resume()`
- `StreamInfo` 多轨元数据结构

### 2.3 AudioCaptureModule 实时采集

**核心类**：`AudioCaptureModule`

**证据** (`audio_capture_module.cpp:100-200`):
- `GetMaxAmplitude()` (L456) — 振幅监测，返回当前采样峰值
- `AssignSampleRateIfSupported()` (L270) — 采样率适配
- `AssignChannelNumIfSupported()` (L285) — 通道数适配
- `AUDIO_CAPTURE_MAX_CACHED_FRAMES=256` — 丢帧补偿阈值

**双 Read 模式**：
- 实时录制模式：AudioCapturer 回调驱动
- 主动拉取模式：ReadLoop 主动读取

### 2.4 AudioTypeTranslate 音频类型转换

**证据** (`audio_type_translate.cpp`):
- PCM 格式转换（采样率/通道布局/位深）
- 与 `AudioResample`（S50）和 `FFmpegAdapter`（S125）协同工作

---

## 三、PTS 与索引转换模块

`modules/pts_index_conversion/` 目录包含 MP4/MOV 容器的时间戳与帧索引互转模块。

### 3.1 核心文件

| 文件 | 行数 | 职责 |
|------|------|------|
| `pts_and_index_conversion.cpp` | 640行 | PTS↔Index 双向转换 |
| `pts_and_index_conversion.h` | 150行 | TimeAndIndexConversion 类定义 |

### 3.2 Box 解析架构

**证据** (`pts_and_index_conversion.cpp:50-100`):
- `BOX_HEAD_SIZE=8` — 标准 Box 头
- `BOX_HEAD_LARGE_SIZE=16` — 大 Box 头（64位 size）
- `PTS_AND_INDEX_CONVERSION_MAX_FRAMES=36000` — 最大帧数限制

### 3.3 双表联合查表

**STTS 表**：`sampleCount + sampleDelta`（增量累加）

**CTTS 表**：`sampleCount + sampleOffset`（B帧 PTS 补偿）

**证据** (`pts_and_index_conversion.cpp:200-300`):
```cpp
// PTS→Index：二分搜索
GetIndexByRelativePresentationTimeUs(relativePtsUs);

// Index→PTS：堆排序逆查
GetRelativePresentationTimeUsByIndex(index);
```

---

## 四、架构关联图

```
MediaSyncManager (优先级调度: VIDEO_SINK=0 / AUDIO_SINK=2 / SUBTITLE_SINK=8)
  ├── VideoSink (DoSyncWrite / CalcBufferDiff / VideoLagDetector)
  ├── AudioSink (AudioVivid 80ms / OnInterrupt / OnDeviceChange)
  └── SubtitleSink (WAIT/SHOW/DROP / RemoveTextTags / RenderLoop)

Source (协议路由: http/https/file/fd/stream)
  ├── PluginManagerV2 → SourcePlugin (Read/Seek/SelectBitRate)
  └── AudioCaptureModule (GetMaxAmplitude / AssignSampleRate / AssignChannel)

PTS ↔ Index Conversion
  ├── STTS (sampleDelta 累加)
  └── CTTS (compositionTimeOffset B帧补偿)
```

---

## 五、关键发现

1. **三路 Sink 优先级硬编码**：VideoSink=0 强制作为时钟锚点，AudioSink=2，SubtitleSink=8，不可配置
2. **AudioVivid 固定延迟**：AudioVivid 内容固定 80ms 延迟补偿，与普通音频处理路径不同
3. **SubtitleSink 独立线程**：SubtitleSink 有专属 RenderLoop，与 VideoSink/AudioSink 的 MediaSynchronousSink 共用线程模型不同
4. **Source 协议路由**：支持五种协议，HTTP/HTTPS 走 HttpSourcePlugin，file 走 FileSourcePlugin
5. **AudioCaptureModule 双模式**：实时录制（回调驱动）和主动拉取（ReadLoop）两种模式

---

## 六、关联记忆

| 关联 | 说明 |
|------|------|
| S22 | MediaSyncManager 时钟锚点 |
| S31/S61/S78/S119 | AudioSink/AudioRendering 家族 |
| S32/S49/S56/S73/S116/S118 | VideoSink/SubtitleSink 家族 |
| S37/S86/S106/S122/S87 | Source 协议路由家族 |
| S124 | AudioCaptureFilter + AudioCaptureModule |
| S50/S125 | AudioResample + FFmpegAdapter |
| S34/S65/S40/S91 | MediaMuxer Track 管理 |

---

## 七、行号级证据汇总

| 文件 | 关键行号 | 证据 |
|------|----------|------|
| `video_sink.cpp` | 462行 | 完整 VideoSink 类 |
| `video_sink.cpp` | ~200 | VideoLagDetector 内嵌类 |
| `audio_sink.cpp` | 1793行 | 完整 AudioSink 类 |
| `audio_sink.cpp` | L456 | GetMaxAmplitude |
| `audio_sink.cpp` | L270/L285 | AssignSampleRate/Channel |
| `audio_sink.cpp` | L169-185 | OnInterrupt 焦点中断 |
| `audio_sink.cpp` | L192-210 | OnOutputDeviceChange 设备切换 |
| `subtitle_sink.cpp` | 517行 | 完整 SubtitleSink 类 |
| `media_sync_manager.cpp` | 491行 | MediaSyncManager 单例 |
| `source.cpp` | 715行 | Source 协议路由 |
| `source.cpp` | ~150 | g_protocolStringToType 五协议 |
| `audio_capture_module.cpp` | 509行 | AudioCaptureModule 类 |
| `audio_capture_module.cpp` | L456 | GetMaxAmplitude 振幅监测 |
| `audio_capture_module.cpp` | L270 | AssignSampleRateIfSupported |
| `audio_capture_module.cpp` | L285 | AssignChannelNumIfSupported |
| `pts_and_index_conversion.cpp` | 640行 | PTS↔Index 双向转换 |
| `pts_and_index_conversion.cpp` | BOX_HEAD_SIZE=8 | 标准 Box 头 |
| `pts_and_index_conversion.cpp` | MAX_FRAMES=36000 | 最大帧数限制 |