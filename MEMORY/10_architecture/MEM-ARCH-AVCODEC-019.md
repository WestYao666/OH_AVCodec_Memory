---
id: MEM-ARCH-AVCODEC-019
title: AudioDataSourceFilter 与 IAudioDataSource 数据源过滤器——内置录音源与 Buffer 队列
type: architecture_fact
scope: [AVCodec, MediaEngine, Filter, AudioSource, Recording]
status: approved
approved_at: "2026-05-06"
created_by: builder-agent
created_at: "2026-04-23T00:40:00+08:00"
updated_by: builder-agent
updated_at: "2026-04-23T12:21:00+08:00"
evidence:
  - kind: local_file
    path: /home/west/OH_AVCodec/services/media_engine/filters/audio_data_source_filter.cpp
    anchor: Line 32: g_registerAudioDataSourceFilter("builtin.recorder.audiodatasource"); Line 39: BUFFER_FLAG_EOS; Line 196: SetAudioDataSource(); Line 196: IAudioDataSource; Line 221: buffer->flag_ |= BUFFER_FLAG_EOS
  - kind: local_file
    path: /home/west/OH_AVCodec/services/media_engine/filters/audio_data_source_filter.cpp
    anchor: Line 21: LOG_DOMAIN_SCREENCAPTURE; Line 233-289: ReadLoop() + AudioDataSourceReadAtActionState enum
owner: 耀耀
review: pending
---

# MEM-ARCH-AVCODEC-019: AudioDataSourceFilter 与 IAudioDataSource 数据源过滤器

## Metadata

| 字段 | 值 |
|------|-----|
| id | MEM-ARCH-AVCODEC-019 |
| title | AudioDataSourceFilter 与 IAudioDataSource 数据源过滤器——内置录音源与 Buffer 队列 |
| type | architecture_fact |
| scope | [AVCodec, MediaEngine, Filter, AudioSource, Recording] |
| status | draft |
| created_by | builder-agent |
| created_at | 2026-04-23 |

## 摘要

AudioDataSourceFilter 是 media_engine filters 中专用于音频数据源的过滤器，注册名为 `"builtin.recorder.audiodatasource"`，用于将 IAudioDataSource 接口的数据送入 pipeline 的 AVBufferQueue。其与 AudioCaptureFilter 共同构成录音场景的两类音频数据来源，但数据提供机制不同：AudioCaptureFilter 走硬件采集（AudioCaptureModule），AudioDataSourceFilter 走外部 IAudioDataSource 接口注入。

## 关键类与接口

### AudioDataSourceFilter
- **文件**: `services/media_engine/filters/audio_data_source_filter.cpp`
- **注册名**: `"builtin.recorder.audiodatasource"`
- **FilterType**: `AUDIO_CAPTURE`（与 AudioCaptureFilter 相同）
- **LOG_DOMAIN**: `LOG_DOMAIN_SCREENCAPTURE`（0xD002B3D），用于屏幕录制/录屏场景

### IAudioDataSource 接口
- **定义**: 外部音频数据源接口，AudioDataSourceFilter 通过 `SetAudioDataSource()` 注入
- **关键方法**:
  - `ReadAt(buffer, bufferSize)` → `AudioDataSourceReadAtActionState`（OK / SKIP_WITHOUT_LOG / RETRY_IN_INTERVAL）
  - `GetSize(bufferSize)` → 获取数据大小
  - `SetVideoFirstFramePts(firstFramePts)` → 同步视频首帧 PTS

### AudioDataSourceReadAtActionState 枚举
| 枚举值 | 含义 | 处理策略 |
|--------|------|----------|
| `OK` | 读取成功 | 推送 buffer 到 outputQueue |
| `SKIP_WITHOUT_LOG` | 跳过（无日志） | 不打印日志，直接结束本次读取 |
| `RETRY_IN_INTERVAL` | 需重试 | 等待 20ms（AUDIO_DATASOURCE_FILTER_READ_FAILED_WAIT_TIME）后重试 |

## 数据流

```
IAudioDataSource → AudioDataSourceFilter.ReadLoop()
  → outputBufferQueue_（AVBufferQueueProducer）
  → 下游 Filter（通常是 AudioEncoderFilter）
```

关键流程：
1. **SetAudioDataSource()** 注入外部数据源
2. **DoStart()** 启动 ReadLoop 任务线程
3. **ReadLoop()** 循环调用 `audioDataSource_->ReadAt()` 读取数据
4. 读取成功 → `outputBufferQueue_->PushBuffer(buffer, true)`
5. 结束 → `SendEos()` 设置 `BUFFER_FLAG_EOS` 推送 EOS buffer

## 与 AudioCaptureFilter 的区别

| 维度 | AudioDataSourceFilter | AudioCaptureFilter |
|------|----------------------|---------------------|
| 注册名 | `builtin.recorder.audiodatasource` | `builtin.recorder.audiocapture` |
| 数据来源 | IAudioDataSource 接口注入 | AudioCaptureModule（硬件采集） |
| LOG_DOMAIN | `LOG_DOMAIN_SCREENCAPTURE` | `LOG_DOMAIN_RECORDER` |
| FilterType | AUDIO_CAPTURE | AUDIO_CAPTURE |
| 使用场景 | 外部音频数据注入/屏幕录制 | 麦克风/系统音频采集 |

## Buffer 队列机制

- **outputBufferQueue_**: 类型为 `sptr<AVBufferQueueProducer>`
- **AVBufferConfig**: 配置 `size`（从 IAudioDataSource::GetSize 获取）和 `memoryFlag: MEMORY_READ_WRITE`
- **EOS 机制**: `buffer->flag_ |= BUFFER_FLAG_EOS`（0x00000001）
- **RequestBuffer 超时**: `TIME_OUT_MS = 0`（立即返回）

## 关键常量

```cpp
static constexpr uint64_t AUDIO_NS_PER_SECOND = 1000000000;
static constexpr int64_t AUDIO_DATASOURCE_FILTER_READ_FAILED_WAIT_TIME = 21333333; // ~20ms
static constexpr int64_t AUDIO_DATASOURCE_FILTER_READ_SUCCESS_WAIT_TIME = 4000000;  // ~4ms
static constexpr uint8_t LOG_LIMIT_HUNDRED = 100;
constexpr uint32_t BUFFER_FLAG_EOS = 0x00000001;
```

## 证据

- `services/media_engine/filters/audio_data_source_filter.cpp` Line 32: `g_registerAudioDataSourceFilter`
- Line 39: `constexpr uint32_t BUFFER_FLAG_EOS = 0x00000001;`
- Line 196: `SetAudioDataSource(const std::shared_ptr<IAudioDataSource>& audioSource)`
- Line 233-289: ReadLoop + AudioDataSourceReadAtActionState
- Line 21: `LOG_DOMAIN_SCREENCAPTURE`

## 相关已有记忆

- **MEM-ARCH-AVCODEC-S8**: 音频编解码 FFmpeg 插件架构（AudioBaseCodec）
- **MEM-ARCH-AVCODEC-016**: AVBufferQueue 异步编解码——输入/输出队列与 TaskThread
- **MEM-ARCH-AVCODEC-S4**: Surface Mode 与 Buffer Mode 双模式切换机制

## 待补充

- IAudioDataSource 接口的完整定义（需查头文件）
- 与 ScreenCapture / MediaRecorder 的集成方式
- FilterType::AUDIO_CAPTURE 的实际使用场景（为何 AudioDataSourceFilter 和 AudioCaptureFilter 共用同一 FilterType？）