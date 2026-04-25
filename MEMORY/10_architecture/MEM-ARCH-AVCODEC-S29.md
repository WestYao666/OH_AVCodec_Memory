---
id: MEM-ARCH-AVCODEC-S29
title: AudioDataSourceFilter 音频数据源过滤器——IAudioDataSource 接口注入与 ReadLoop 主动拉取机制
type: architecture_fact
scope: [AVCodec, MediaEngine, Filter, AudioSource, RecorderPipeline, Pipeline, ScreenCapture]
status: pending_approval
created_by: builder-agent
created_at: "2026-04-25T10:06:00+08:00"
updated_by: builder-agent
updated_at: "2026-04-25T10:06:00+08:00"
submitted_at: "2026-04-25T10:10:00+08:00"
evidence: |
  - source: services/media_engine/filters/audio_data_source_filter.cpp line 33-37
    anchor: "AutoRegisterFilter<AudioDataSourceFilter> g_registerAudioDataSourceFilter(\"builtin.recorder.audiodatasource\", FilterType::AUDIO_DATA_SOURCE, ...)"
    note: 注册名builtin.recorder.audiodatasource，FilterType::AUDIO_DATA_SOURCE（非AUDIO_CAPTURE）
  - source: services/media_engine/filters/audio_data_source_filter.cpp line 173-179
    anchor: "FilterType AudioDataSourceFilter::GetFilterType() { return FilterType::AUDIO_CAPTURE; }"
    note: "【关键矛盾】注册时用AUDIO_DATA_SOURCE，但GetFilterType()返回AUDIO_CAPTURE——二者不一致，需确认实际使用的类型"
  - source: services/media_engine/filters/audio_data_source_filter.cpp line 196
    anchor: "void AudioDataSourceFilter::SetAudioDataSource(const std::shared_ptr<IAudioDataSource>& audioSource)"
    note: SetAudioDataSource注入外部IAudioDataSource接口，由应用层实现ReadAt/GetSize/SetVideoFirstFramePts
  - source: services/media_engine/filters/audio_data_source_filter.cpp line 233-289
    anchor: "void AudioDataSourceFilter::ReadLoop() — 完整拉取循环：RequestBuffer→audioDataSource_->ReadAt()→PushBuffer→RelativeSleep"
    note: ReadLoop是Task线程主动拉取循环，非硬件中断；失败重试等待20ms(21333333ns)，成功等待4ms(4000000ns)
  - source: services/media_engine/filters/audio_data_source_filter.cpp line 253-268
    anchor: "AudioDataSourceReadAtActionState readAtRet = audioDataSource_->ReadAt(buffer, bufferSize); 三状态分支：OK/SKIP_WITHOUT_LOG/RETRY_IN_INTERVAL"
    note: ReadAt返回三状态枚举；RETRY_IN_INTERVAL触发20ms重试；SKIP_WITHOUT_LOG静默跳过
  - source: services/media_engine/filters/audio_data_source_filter.cpp line 196-209
    anchor: "Status AudioDataSourceFilter::SendEos() — RequestBuffer→buffer->flag_|=BUFFER_FLAG_EOS→PushBuffer"
    note: EOS通过outputBufferQueue_推送flag=EOS的buffer实现，非独立消息
  - source: services/media_engine/filters/audio_data_source_filter.cpp line 279-296
    anchor: "int32_t RelativeSleep(int64_t nanoTime) — clock_nanosleep(CLOCK_MONOTONIC, relativeFlag, &time, nullptr)"
    note: 精准相对睡眠使用CLOCK_MONOTONIC+RelaSleep而非usleep/osalseSleep，保证睡眠精度
  - source: test/unittest/filter_test/audio_data_source_filter_unit_test.h line 66-72
    anchor: "class MockAudioDataSource : public IAudioDataSource { MOCK_METHOD(AudioDataSourceReadAtActionState, ReadAt, (std::shared_ptr<AVBuffer>, uint32_t), (override)); MOCK_METHOD(int32_t, GetSize, (int64_t&), (override)); MOCK_METHOD(void, SetVideoFirstFramePts, (int64_t), (override)); }"
    note: IAudioDataSource接口三方法：ReadAt→AudioDataSourceReadAtActionState；GetSize→int32_t；SetVideoFirstFramePts→void
  - source: services/media_engine/filters/audio_data_source_filter.cpp line 21
    anchor: "constexpr OHOS::HiviewDFX::HiLogLabel LABEL = { LOG_CORE, LOG_DOMAIN_SCREENCAPTURE, \"AudioDataSourceFilter\" }"
    note: LOG_DOMAIN_SCREENCAPTURE用于屏幕录制/录屏场景，与AudioCaptureFilter(LOG_DOMAIN_RECORDER)不同
  - source: services/media_engine/filters/audio_data_source_filter.cpp line 97-104
    anchor: "Status DoStart() { eos_=false; if (taskPtr_) taskPtr_->Start(); return Status::OK; }"
    note: DoStart重置eos_标志并启动ReadLoop Task；与AudioCaptureFilter不同，无AudioCapturer依赖
  - source: services/media_engine/filters/audio_data_source_filter.cpp line 31
    anchor: "constexpr uint32_t TIME_OUT_MS = 0; // RequestBuffer立即返回"
    note: RequestBuffer超时为0（立即返回），适合主动拉取模式
owner: 耀耀
review: pending
---

# MEM-ARCH-AVCODEC-S29: AudioDataSourceFilter 音频数据源过滤器

## Metadata

| 字段 | 值 |
|------|-----|
| id | MEM-ARCH-AVCODEC-S29 |
| title | AudioDataSourceFilter 音频数据源过滤器——IAudioDataSource 接口注入与 ReadLoop 主动拉取机制 |
| type | architecture_fact |
| scope | [AVCodec, MediaEngine, Filter, AudioSource, RecorderPipeline, Pipeline, ScreenCapture] |
| status | pending_approval |
| created_by | builder-agent |
| created_at | 2026-04-25T10:06:00+08:00 |
| updated_by | builder-agent |
| updated_at | 2026-04-25T10:06:00+08:00 |

## 摘要

AudioDataSourceFilter 是 media_engine filters 中专用于外部音频数据源注入的过滤器，注册名为 `"builtin.recorder.audiodatasource"`，FilterType 为 `AUDIO_DATA_SOURCE`。与 AudioCaptureFilter（走 AudioCaptureModule 硬件采集）不同，AudioDataSourceFilter 通过应用层实现的 `IAudioDataSource` 接口主动拉取音频数据，适用于屏幕录制等场景。

**⚠️ 关键矛盾**：注册时使用 `FilterType::AUDIO_DATA_SOURCE`，但 `GetFilterType()` 方法返回 `FilterType::AUDIO_CAPTURE`，二者不一致。

## 关键类与接口

### AudioDataSourceFilter
| 属性 | 值 |
|------|-----|
| 文件 | `services/media_engine/filters/audio_data_source_filter.cpp` |
| 注册名 | `"builtin.recorder.audiodatasource"` |
| FilterType（注册） | `AUDIO_DATA_SOURCE` |
| FilterType（GetFilterType） | `AUDIO_CAPTURE` ⚠️ |
| LOG_DOMAIN | `LOG_DOMAIN_SCREENCAPTURE`（屏幕录制场景） |
| Task 线程名 | `"DataReader"` |
| RequestBuffer 超时 | `TIME_OUT_MS = 0`（立即返回） |

### IAudioDataSource 接口（应用层实现）
```cpp
class IAudioDataSource {
    AudioDataSourceReadAtActionState ReadAt(std::shared_ptr<AVBuffer> buffer, uint32_t length);
    int32_t GetSize(int64_t& size);
    void SetVideoFirstFramePts(int64_t firstFramePts);
};
```

### AudioDataSourceReadAtActionState 枚举
| 枚举值 | 含义 | 处理策略 |
|--------|------|----------|
| `OK` | 读取成功 | 推送 buffer 到 outputQueue_ |
| `SKIP_WITHOUT_LOG` | 静默跳过 | 不打印日志，直接结束本次读取 |
| `RETRY_IN_INTERVAL` | 需重试 | 等待 20ms 后重试（`AUDIO_DATASOURCE_FILTER_READ_FAILED_WAIT_TIME = 21333333ns`） |

## 数据流

```
IAudioDataSource（应用层实现）
  → AudioDataSourceFilter::SetAudioDataSource() 注入
  → AudioDataSourceFilter::DoStart() → taskPtr_->Start()
  → ReadLoop() Task线程循环：
      1. audioDataSource_->GetSize(bufferSize)
      2. outputBufferQueue_->RequestBuffer(buffer)
      3. audioDataSource_->ReadAt(buffer, bufferSize)
         → OK: buffer->memory_->SetSize(bufferSize) → PushBuffer(true)
         → SKIP_WITHOUT_LOG: PushBuffer(false) 结束
         → RETRY_IN_INTERVAL: RelativeSleep(21333333ns=20ms) 后重试
      4. RelativeSleep(4000000ns=4ms) 控制读取频率
  → outputBufferQueue_（AVBufferQueueProducer）
  → 下游 Filter（通常是 AudioEncoderFilter）
```

## 生命周期状态机

| 方法 | 动作 |
|------|------|
| `Init()` | 创建 Task("DataReader")，注册 ReadLoop Job |
| `DoPrepare()` | 回调 NEXT_FILTER_NEEDED（请求下游 Filter） |
| `DoStart()` | eos_=false，启动 taskPtr_ |
| `DoPause()` | taskPtr_->Pause() |
| `DoResume()` | taskPtr_->Start() |
| `DoStop()` | taskPtr_->Stop() |
| `DoRelease()` | taskPtr_->Stop()+nullptr，audioDataSource_=nullptr |
| `SendEos()` | RequestBuffer→buffer->flag_|=BUFFER_FLAG_EOS→PushBuffer |

## 与 AudioCaptureFilter 的核心区别

| 维度 | AudioDataSourceFilter | AudioCaptureFilter |
|------|----------------------|-------------------|
| 注册名 | `builtin.recorder.audiodatasource` | `builtin.recorder.audiocapture` |
| 数据来源 | IAudioDataSource 接口（应用层拉取） | AudioCaptureModule（硬件采集） |
| LOG_DOMAIN | `LOG_DOMAIN_SCREENCAPTURE` | `LOG_DOMAIN_RECORDER` |
| FilterType | `AUDIO_DATA_SOURCE`（注册）/ `AUDIO_CAPTURE`（GetFilterType）⚠️ | `AUDIO_CAPTURE` |
| 数据拉取 | Task 线程 ReadLoop 主动轮询 | AudioCaptureModule 硬件中断回调 |
| 重试机制 | 20ms 等待后重试（RelativeSleep） | 无（硬件保证） |
| 使用场景 | 屏幕录制、外部音频注入 | 麦克风/系统音频采集 |

## 关键常量

```cpp
static constexpr uint64_t AUDIO_NS_PER_SECOND = 1000000000;
static constexpr int64_t AUDIO_DATASOURCE_FILTER_READ_FAILED_WAIT_TIME = 21333333; // ~20ms
static constexpr int64_t AUDIO_DATASOURCE_FILTER_READ_SUCCESS_WAIT_TIME = 4000000;  // ~4ms
static constexpr uint8_t LOG_LIMIT_HUNDRED = 100;
constexpr uint32_t BUFFER_FLAG_EOS = 0x00000001;
constexpr uint32_t TIME_OUT_MS = 0;
```

## 待确认问题

1. **⚠️ FilterType 矛盾**：注册用 `AUDIO_DATA_SOURCE`，`GetFilterType()` 返回 `AUDIO_CAPTURE`。pipeline 实际使用哪个类型？
2. IAudioDataSource 接口定义在哪个头文件中？（`media_data_source.h` 不在 multimedia_av_codec 仓库中）
3. ScreenCapture 场景下 AudioDataSourceFilter 与 MediaRecorder 的完整集成路径

## 相关已有记忆

- **MEM-ARCH-AVCODEC-S26**: AudioCaptureFilter + AudioDataSourceFilter 录制采集过滤器（含 SubtitleSink）
- **MEM-ARCH-AVCODEC-016**: AVBufferQueue 异步编解码
- **MEM-ARCH-AVCODEC-008**: MediaCodec 封装架构
