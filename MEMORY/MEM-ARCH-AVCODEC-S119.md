---
id: MEM-ARCH-AVCODEC-S119
title: AudioSampleFormat位深映射 + CalcMaxAmplitude振幅计算 + AudioVivid延迟补偿 + SubtitleSink三状态渲染环
scope: [AVCodec, MediaEngine, Sink, AudioSampleFormat, CalcMaxAmplitude, AudioVivid, SubtitleSink, RenderLoop, AudioSink, MediaSync, FIX_DELAY_MS_AUDIO_VIVID, 80ms, AudioSampleFormatToBitDepth, UpdateMaxAmplitude, SAMPLE_S24, PCM, SubtitleBufferState, WAIT, SHOW, DROP, RemoveTextTags, NotifyRender, SUBTITLE_LOOP, SUBTITME_LOOP_RUNNING, Tag::SUBTITLE_TEXT, Tag::SUBTITLE_PTS, Tag::SUBTITLE_DURATION]
status: pending_approval
created_at: "2026-05-11T07:10:00+08:00"
submitted_at: "2026-05-11T07:18:00+08:00"
evidence_count: 22
source_repo: /home/west/av_codec_repo
关联主题: [S31(AudioSinkFilter), S32(VideoRenderFilter), S49(SubtitleSink), S56(VideoSink同步器), S61(AudioRendering), S73(三路Sink总览), S78(AudioServerSinkPlugin)]
---

# MEM-ARCH-AVCODEC-S119: AudioSampleFormat位深 + CalcMaxAmplitude + AudioVivid + SubtitleSink渲染环

## 核心定位

本记忆聚焦 Sink 模块中两个基础但关键的支撑性子模块：

1. **AudioSampleFormat** (`audio_sampleformat.cpp`): 25种音频采样格式→位深映射表，供 CalcMaxAmplitude 和 AudioSink 使用
2. **CalcMaxAmplitude** (`calc_max_amplitude.cpp`): PCM 峰值振幅计算，支持 8/16/24/32bit
3. **AudioVivid** 固定 80ms 延迟补偿 (`audio_sink.cpp:45`)
4. **SubtitleSink RenderLoop** (`subtitle_sink.cpp`): 独立渲染线程 + WAIT/SHOW/DROP 三状态机 + HTML标签剥离

与 S31 Filter层 / S61 AudioRendering / S78 AudioServerSinkPlugin 构成完整音频渲染链路。

---

## 1. AudioSampleFormat — 25种采样格式位深映射

**Evidence**: `services/media_engine/modules/sink/audio_sampleformat.cpp` (全文) + `audio_sampleformat.h`

### 1.1 位深映射表 (audio_sampleformat.cpp:15-36)

```cpp
const std::map<Plugins::AudioSampleFormat, int32_t> SAMPLEFORMAT_INFOS = {
    // 交错格式 (interleaved)
    {Plugins::SAMPLE_U8,      8},
    {Plugins::SAMPLE_S16LE,  16},
    {Plugins::SAMPLE_S24LE,  24},
    {Plugins::SAMPLE_S32LE,  32},
    {Plugins::SAMPLE_F32LE,  32},
    // 平面格式 (planar)
    {Plugins::SAMPLE_U8P,     8},
    {Plugins::SAMPLE_S16P,   16},
    {Plugins::SAMPLE_S24P,   24},
    {Plugins::SAMPLE_S32P,   32},
    {Plugins::SAMPLE_F32P,   32},
    // 其他变体
    {Plugins::SAMPLE_S8,      8},
    {Plugins::SAMPLE_S8P,     8},
    {Plugins::SAMPLE_U16,    16},
    {Plugins::SAMPLE_U16P,   16},
    {Plugins::SAMPLE_U24,    24},
    {Plugins::SAMPLE_U24P,   24},
    {Plugins::SAMPLE_U32,    32},
    {Plugins::SAMPLE_U32P,   32},
    {Plugins::SAMPLE_S64,    64},
    {Plugins::SAMPLE_U64,    64},
    {Plugins::SAMPLE_S64P,   64},
    {Plugins::SAMPLE_U64P,   64},
    {Plugins::SAMPLE_F64,    64},
    {Plugins::SAMPLE_F64P,   64},
    {Plugins::INVALID_WIDTH, -1},  // 未知格式返回-1
};
```

### 1.2 查询接口 (audio_sampleformat.h + audio_sampleformat.cpp:39-45)

```cpp
// audio_sampleformat.h
__attribute__((visibility("default"))) int32_t AudioSampleFormatToBitDepth(Plugins::AudioSampleFormat sampleFormat);

// audio_sampleformat.cpp:39-45
int32_t AudioSampleFormatToBitDepth(Plugins::AudioSampleFormat sampleFormat)
{
    if (SAMPLEFORMAT_INFOS.count(sampleFormat) != 0) {
        return SAMPLEFORMAT_INFOS.at(sampleFormat);
    }
    return -1;  // INVALID_WIDTH
}
```

**调用方**: `audio_sink.cpp:711-721` 在 `CopyDataToBufferDesc` 中 switch-case 格式分支；
`calc_max_amplitude.cpp` 内部使用 `SAMPLE_S16_C` 等枚举常数（注意：CalcMaxAmplitude 用独立枚举，不是 AudioSampleFormat 直接映射）。

---

## 2. CalcMaxAmplitude — PCM 峰值振幅计算

**Evidence**: `services/media_engine/modules/sink/calc_max_amplitude.cpp` (全文139行)

### 2.1 常量定义 (calc_max_amplitude.cpp:22-27)

```cpp
constexpr int32_t SAMPLE_S24_BYTE_NUM = 3;           // 24bit = 3字节
constexpr int32_t ONE_BYTE_BITS = 8;
constexpr int32_t MAX_VALUE_OF_SIGNED_24_BIT = 0x7FFFFF;   // 24bit最大值
constexpr int32_t MAX_VALUE_OF_SIGNED_32_BIT = 0x7FFFFFFF;  // 32bit最大值
```

### 2.2 四种位深处理函数

| 位深 | 函数 | 归一化除数 | 调用方式 |
|------|------|-----------|---------|
| 8bit | `CalculateMaxAmplitudeForPCM8Bit` (calc_max_amplitude.cpp:31-48) | `SCHAR_MAX` (127) | `(int8_t* frame, nSamples)` |
| 16bit | `CalculateMaxAmplitudeForPCM16Bit` (calc_max_amplitude.cpp:51-66) | `SHRT_MAX` (32767) | `(int16_t* frame, nSamples)` |
| 24bit | `CalculateMaxAmplitudeForPCM24Bit` (calc_max_amplitude.cpp:69-86) | `MAX_VALUE_OF_SIGNED_24_BIT` (8388607) | `(char* frame, 3字节/样本)` 手动拼24bit整数 |
| 32bit | `CalculateMaxAmplitudeForPCM32Bit` (calc_max_amplitude.cpp:89-103) | `MAX_VALUE_OF_SIGNED_32_BIT` (2147483647) | `(int32_t* frame, nSamples)` |

**24bit特殊处理** (calc_max_amplitude.cpp:73-80): 3字节小端序拼接：
```cpp
for (uint32_t j = 0; j < SAMPLE_S24_BYTE_NUM; ++j) {
    curValue += (*(curPos + j) << (ONE_BYTE_BITS * j));  // LSB first
}
```

### 2.3 统一入口 (calc_max_amplitude.cpp:106-123)

```cpp
float UpdateMaxAmplitude(char *frame, uint64_t replyBytes, int32_t adapterFormat)
{
    switch (adapterFormat) {
        case SAMPLE_U8_C:   return CalculateMaxAmplitudeForPCM8Bit(...);
        case SAMPLE_S16_C: return CalculateMaxAmplitudeForPCM16Bit(...);
        case SAMPLE_S24_C: return CalculateMaxAmplitudeForPCM24Bit(...);
        case SAMPLE_S32_C: return CalculateMaxAmplitudeForPCM32Bit(...);
        default: MEDIA_LOG_I("getMaxAmplitude: Unsupported audio format: %{public}d", adapterFormat);
                 return 0;
    }
}
```

**注意**: `adapterFormat` 使用 `SAMPLE_U8_C/SAMPLE_S16_C/SAMPLE_S24_C/SAMPLE_S32_C` 内部枚举，不是 `Plugins::AudioSampleFormat`。
**调用方**: `audio_sink.cpp:642` + `audio_sink.cpp:826` + `audio_sink.cpp:829` 在音频数据写入 AudioRenderer 前计算峰值。

### 2.4 内部枚举 (calc_max_amplitude.cpp:17-21)

```cpp
constexpr int32_t SAMPLE_U8_C = 0;
constexpr int32_t SAMPLE_S16_C = 1;
constexpr int32_t SAMPLE_S24_C = 2;
constexpr int32_t SAMPLE_S32_C = 3;
```

---

## 3. AudioVivid 固定 80ms 延迟补偿

**Evidence**: `services/media_engine/modules/sink/audio_sink.cpp:45` + `audio_sink.cpp:761-798`

```cpp
// audio_sink.cpp:45
constexpr int64_t FIX_DELAY_MS_AUDIO_VIVID = 80;  // 固定80ms延迟补偿
```

**AudioVivid 写入路径** (audio_sink.cpp:761-798):
- `CopyAudioVividBufferData` (audio_sink.cpp:761-785): AudioVivid格式专用写入，处理 `cacheBufferSize <= size` 判断
- `isAudioPass_` 标志 (audio_sink.cpp:770, 794-798): AudioVivid直通模式跳过部分逻辑
- `HandleAudioRenderRequest` (audio_sink.cpp:146-149): 调用 `CopyDataToBufferDesc` 或 `CopyAudioVividBufferData`

**AudioSink 回调** (audio_sink.cpp:102-116):
```cpp
void AudioSink::AudioSinkDataCallbackImpl::OnWriteData(int32_t size, bool isAudioVivid)
{
    if (sink->IsInputBufferDataEnough(size, isAudioVivid)) {
        sink->HandleAudioRenderRequest(size, isAudioVivid, bufferDesc);
    }
}
```

---

## 4. SubtitleSink 独立渲染线程 — WAIT/SHOW/DROP 三状态机

**Evidence**: `services/media_engine/modules/sink/subtitle_sink.cpp` (517行)

### 4.1 线程启动 (subtitle_sink.cpp:144-145)

```cpp
readThread_ = std::make_unique<std::thread>(&SubtitleSink::RenderLoop, this);
pthread_setname_np(readThread_->native_handle(), "SubtitleRenderLoop");
```

### 4.2 RenderLoop 主循环 (subtitle_sink.cpp:286-319)

```cpp
void SubtitleSink::RenderLoop()
{
    while (SUBTITME_LOOP_RUNNING) {  // 注意: 源码中拼写为 SUBTITME (typo)
        std::unique_lock<std::mutex> lock(mutex_);
        updateCond_.wait(lock, [this] {
            return isThreadExit_.load() ||
                   (!subtitleInfoVec_.empty() && state_ == Pipeline::FilterState::RUNNING);
        });
        if (isFlush_) { /* flush and continue */ }
        FALSE_RETURN(!isThreadExit_.load());
        SubtitleInfo subtitleInfo = subtitleInfoVec_.front();
        int64_t waitTime = static_cast<int64_t>(CalcWaitTime(subtitleInfo));
        updateCond_.wait_for(lock, std::chrono::microseconds(waitTime), ...);
        auto actionToDo = ActionToDo(subtitleInfo);
        if (actionToDo == SubtitleBufferState::DROP) {
            subtitleInfoVec_.pop_front();
            inputBufferQueueConsumer_->ReleaseBuffer(subtitleInfo.buffer_);
        } else if (actionToDo == SubtitleBufferState::WAIT) {
            continue;  // 等待下一帧，重新计算waitTime
        }
        NotifyRender(subtitleInfo);
        subtitleInfoVec_.pop_front();
        inputBufferQueueConsumer_->ReleaseBuffer(subtitleInfo.buffer_);
    }
}
```

### 4.3 三状态决策 (subtitle_sink.cpp:353-363)

```cpp
uint32_t SubtitleSink::ActionToDo(SubtitleInfo &subtitleInfo)
{
    auto curTime = GetMediaTime();
    if (subtitleInfo.pts_ + subtitleInfo.duration_ < curTime) {
        return SubtitleBufferState::DROP;  // 已过期末端丢弃
    }
    if (subtitleInfo.pts_ > curTime || state_ != Pipeline::FilterState::RUNNING) {
        return SubtitleBufferState::WAIT;  // 未到时间或非运行态等待
    }
    subtitleInfo.duration_ -= curTime - subtitleInfo.pts_;  // 缩短剩余显示时长
    return SubtitleBufferState::SHOW;  // 显示
}
```

**关键**: `state_ == Pipeline::FilterState::RUNNING` 条件，暂停时字幕自动等待而非丢弃。

### 4.4 NotifyRender 事件上报 (subtitle_sink.cpp:373-379)

```cpp
void SubtitleSink::NotifyRender(SubtitleInfo &subtitleInfo)
{
    Format format;
    (void)format.PutStringValue(Tag::SUBTITLE_TEXT, subtitleInfo.text_);
    (void)format.PutIntValue(Tag::SUBTITLE_PTS, Plugins::Us2Ms(subtitleInfo.pts_));
    (void)format.PutIntValue(Tag::SUBTITLE_DURATION, Plugins::Us2Ms(subtitleInfo.duration_));
    Event event{ .srcFilter = "SubtitleSink",
                .type = EventType::EVENT_SUBTITLE_TEXT_UPDATE,
                .param = format };
    playerEventReceiver_->OnEvent(event);
}
```

### 4.5 RemoveTextTags HTML标签剥离 (subtitle_sink.cpp:483+)

`RemoveTextTags` 函数剥离 `<b>/<i>/<u>/<font>` 等 HTML 标签，只保留纯文本显示。
**Evidence**: `subtitle_sink.cpp:483` (函数定义，全文约34行)。

### 4.6 暂停/Flush 机制

- `isFlush_` 标志: RenderLoop 中检测到 flush 时跳过本帧处理 (subtitle_sink.cpp:295-306)
- `isInterruptNeeded_`: 中断标记，驱动 `isThreadExit_` 退出线程 (subtitle_sink.cpp:377-378)
- `shouldUpdate_`: 时间戳更新标记，触发提前唤醒 (subtitle_sink.cpp:327-333)

---

## 5. 组件关联总览

```
AudioSampleFormat (audio_sampleformat.cpp)
  └─ AudioSampleFormatToBitDepth() → AudioSink::CopyDataToBufferDesc
  └─ 25种格式 → 位深映射表

CalcMaxAmplitude (calc_max_amplitude.cpp)
  └─ UpdateMaxAmplitude(char*, replyBytes, adapterFormat)
  └─ AudioSink::DoSyncWrite → CalcMaxAmplitude()
      └─ audio_sink.cpp:642 / 826 / 829

AudioSink (audio_sink.cpp)
  ├─ FIX_DELAY_MS_AUDIO_VIVID = 80ms (audio_sink.cpp:45)
  ├─ isAudioVivid flag → CopyAudioVividBufferData
  ├─ CalcMaxAmplitude 调用
  └─ DoSyncWrite → AudioRenderer

SubtitleSink (subtitle_sink.cpp)
  ├─ RenderLoop 独立线程 (pthread: "SubtitleRenderLoop")
  ├─ WAIT/SHOW/DROP 三状态机 (ActionToDo)
  ├─ RemoveTextTags HTML标签剥离
  ├─ NotifyRender → Tag::SUBTITLE_TEXT/PTS/DURATION 上报
  └─ IMediaSynchronizer 时钟锚点 (GetMediaTime)
```

---

## 6. 与相关记忆的互补关系

| 记忆 | 聚焦层次 | S119 补充内容 |
|------|---------|-------------|
| S31 AudioSinkFilter | Filter 层封装 | 本记忆深入 Filter 引擎层 (AudioSink.cpp) |
| S61 AudioRendering | AudioSampleFormat/CalcMaxAmplitude | 本记忆补充完整位深映射表 + CalcMaxAmplitude 四函数实现 |
| S49 SubtitleSink | Filter 层封装 | 本记忆深入 RenderLoop 线程 + 三状态机 + HTML剥离 |
| S56 VideoSink | 视频 Sink | 与 SubtitleSink 并列，SubtitleSink 有独立线程(video_sink 无) |
| S73 三路Sink总览 | 总览 | 补充 AudioVivid 80ms 关键常数 |
| S78 AudioServerSinkPlugin | Plugin 层 | 本记忆聚焦引擎层 |

---

## 7. 关键 evidence 汇总

| 文件 | 行数 | 关键 evidence |
|------|------|-------------|
| `audio_sampleformat.cpp` | 58行 | 25种格式→位深映射表 `SAMPLEFORMAT_INFOS` |
| `audio_sampleformat.h` | 全文 | 导出 `AudioSampleFormatToBitDepth` |
| `calc_max_amplitude.cpp` | 139行 | 8/16/24/32bit 峰值计算四函数 |
| `audio_sink.cpp` | 1793行 | `FIX_DELAY_MS_AUDIO_VIVID=80` / `CalcMaxAmplitude` / `OnWriteData` |
| `subtitle_sink.cpp` | 517行 | `RenderLoop` / `ActionToDo` 三状态 / `RemoveTextTags` / `NotifyRender` |
