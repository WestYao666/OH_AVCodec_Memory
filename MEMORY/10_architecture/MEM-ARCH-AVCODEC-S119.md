---
id: MEM-ARCH-AVCODEC-S119
title: AudioSampleFormat位深映射 + CalcMaxAmplitude振幅计算 + AudioVivid固定80ms延迟补偿 + SubtitleSink三状态渲染环
type: architecture
status: draft
author: builder
created_at: 2026-05-11T08:03:00+08:00
tags: [openharmony, avcodec, audio, sink, media_engine]
---

## 摘要
AudioSampleFormat 25种采样格式到位深的映射表、CalcMaxAmplitude PCM峰值振幅计算（8/16/24/32bit）、AudioVivid固定80ms延迟补偿，以及SubtitleSink独立渲染线程中WAIT/SHOW/DROP三状态机与HTML标签剥离机制。

## 背景
Sink模块是播放管线的输出终点，其中音频渲染和字幕渲染需要基础支撑组件：AudioSampleFormat提供位深信息供音量计算和音频写入使用；CalcMaxAmplitude用于计算音频峰值振幅；AudioVivid需要固定延迟补偿保证音频与视频同步；SubtitleSink则需要独立的渲染线程和精确的时间状态机来保证字幕显示的及时性与正确性。

## 架构设计

### 1. AudioSampleFormat — 25种采样格式位深映射

**源文件**: `services/media_engine/modules/sink/audio_sampleformat.cpp` (58行) + `audio_sampleformat.h`

**位深映射表** (`audio_sampleformat.cpp:15-36`):
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
    // ... 20余种其他格式 ...
    {Plugins::INVALID_WIDTH, -1},
};
```

**导出接口** (`audio_sampleformat.cpp:39-45`):
```cpp
int32_t AudioSampleFormatToBitDepth(Plugins::AudioSampleFormat sampleFormat)
{
    if (SAMPLEFORMAT_INFOS.count(sampleFormat) != 0) {
        return SAMPLEFORMAT_INFOS.at(sampleFormat);
    }
    return -1;  // INVALID_WIDTH
}
```
**调用方**: `audio_sink.cpp:711-721` 在 `CopyDataToBufferDesc` 中根据格式分支写入对应字节数；`calc_max_amplitude.cpp` 内部使用独立枚举。

---

### 2. CalcMaxAmplitude — PCM峰值振幅计算

**源文件**: `services/media_engine/modules/sink/calc_max_amplitude.cpp` (139行)

**内部枚举** (`calc_max_amplitude.cpp:17-21`):
```cpp
constexpr int32_t SAMPLE_U8_C = 0;
constexpr int32_t SAMPLE_S16_C = 1;
constexpr int32_t SAMPLE_S24_C = 2;
constexpr int32_t SAMPLE_S32_C = 3;
```

**四函数实现**:

| 位深 | 函数 | 归一化除数 | 实现位置 |
|------|------|-----------|---------|
| 8bit | `CalculateMaxAmplitudeForPCM8Bit` | `SCHAR_MAX` (127) | calc_max_amplitude.cpp:31-48 |
| 16bit | `CalculateMaxAmplitudeForPCM16Bit` | `SHRT_MAX` (32767) | calc_max_amplitude.cpp:51-66 |
| 24bit | `CalculateMaxAmplitudeForPCM24Bit` | `MAX_VALUE_OF_SIGNED_24_BIT` (8388607) | calc_max_amplitude.cpp:69-86 |
| 32bit | `CalculateMaxAmplitudeForPCM32Bit` | `MAX_VALUE_OF_SIGNED_32_BIT` (2147483647) | calc_max_amplitude.cpp:89-103 |

**24bit特殊处理** — 3字节小端序手动拼接:
```cpp
for (uint32_t j = 0; j < SAMPLE_S24_BYTE_NUM; ++j) {
    curValue += (*(curPos + j) << (ONE_BYTE_BITS * j));  // LSB first
}
```

**统一入口** (`calc_max_amplitude.cpp:106-123`):
```cpp
float UpdateMaxAmplitude(char *frame, uint64_t replyBytes, int32_t adapterFormat)
{
    switch (adapterFormat) {
        case SAMPLE_U8_C:  return CalculateMaxAmplitudeForPCM8Bit(...);
        case SAMPLE_S16_C: return CalculateMaxAmplitudeForPCM16Bit(...);
        case SAMPLE_S24_C: return CalculateMaxAmplitudeForPCM24Bit(...);
        case SAMPLE_S32_C: return CalculateMaxAmplitudeForPCM32Bit(...);
        default: return 0;
    }
}
```
**调用方**: `audio_sink.cpp:642` / `audio_sink.cpp:826` / `audio_sink.cpp:829` 在写入 AudioRenderer 前计算峰值。

---

### 3. AudioVivid 固定80ms延迟补偿

**源文件**: `services/media_engine/modules/sink/audio_sink.cpp`

```cpp
// audio_sink.cpp:45
constexpr int64_t FIX_DELAY_MS_AUDIO_VIVID = 80;  // 固定80ms延迟补偿
```

**AudioVivid写入路径** (`audio_sink.cpp:761-798`):
- `CopyAudioVividBufferData`: AudioVivid格式专用写入，处理 `cacheBufferSize <= size` 判断
- `isAudioPass_` 标志 (`audio_sink.cpp:770, 794-798`): AudioVivid直通模式跳过部分逻辑
- `HandleAudioRenderRequest` (`audio_sink.cpp:146-149`): 调用 `CopyDataToBufferDesc` 或 `CopyAudioVividBufferData`

**回调** (`audio_sink.cpp:102-116`):
```cpp
void AudioSink::AudioSinkDataCallbackImpl::OnWriteData(int32_t size, bool isAudioVivid)
{
    if (sink->IsInputBufferDataEnough(size, isAudioVivid)) {
        sink->HandleAudioRenderRequest(size, isAudioVivid, bufferDesc);
    }
}
```

---

### 4. SubtitleSink独立渲染线程 — WAIT/SHOW/DROP三状态机

**源文件**: `services/media_engine/modules/sink/subtitle_sink.cpp` (517行)

**线程启动** (`subtitle_sink.cpp:144-145`):
```cpp
readThread_ = std::make_unique<std::thread>(&SubtitleSink::RenderLoop, this);
pthread_setname_np(readThread_->native_handle(), "SubtitleRenderLoop");
```

**RenderLoop主循环** (`subtitle_sink.cpp:286-319`):
```cpp
void SubtitleSink::RenderLoop()
{
    while (SUBTITME_LOOP_RUNNING) {  // 源码拼写: SUBTITME (typo)
        std::unique_lock<std::mutex> lock(mutex_);
        updateCond_.wait(lock, [this] {
            return isThreadExit_.load() ||
                   (!subtitleInfoVec_.empty() && state_ == Pipeline::FilterState::RUNNING);
        });
        if (isFlush_) { /* flush */ }
        SubtitleInfo subtitleInfo = subtitleInfoVec_.front();
        int64_t waitTime = CalcWaitTime(subtitleInfo);
        updateCond_.wait_for(lock, std::chrono::microseconds(waitTime), ...);
        auto actionToDo = ActionToDo(subtitleInfo);
        if (actionToDo == SubtitleBufferState::DROP) {
            subtitleInfoVec_.pop_front();
            inputBufferQueueConsumer_->ReleaseBuffer(subtitleInfo.buffer_);
        } else if (actionToDo == SubtitleBufferState::WAIT) {
            continue;
        }
        NotifyRender(subtitleInfo);
    }
}
```

**三状态决策** (`subtitle_sink.cpp:353-363`):
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
**关键**: `state_ == Pipeline::FilterState::RUNNING` 条件使暂停时字幕自动等待而非丢弃。

**NotifyRender事件上报** (`subtitle_sink.cpp:373-379`):
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

**RemoveTextTags** (`subtitle_sink.cpp:483+`): 剥离 `<b>/<i>/<u>/<font>` 等HTML标签，只保留纯文本显示。

---

## Evidence

- [audio_sampleformat.cpp:15-36] 25种AudioSampleFormat→位深映射表 SAMPLEFORMAT_INFOS
- [audio_sampleformat.cpp:39-45] AudioSampleFormatToBitDepth 查询接口实现
- [calc_max_amplitude.cpp:17-21] 内部枚举 SAMPLE_U8_C/SAMPLE_S16_C/SAMPLE_S24_C/SAMPLE_S32_C
- [calc_max_amplitude.cpp:31-103] 8/16/24/32bit 四函数 PCM 峰值振幅计算实现
- [calc_max_amplitude.cpp:106-123] UpdateMaxAmplitude 统一入口
- [audio_sink.cpp:45] FIX_DELAY_MS_AUDIO_VIVID = 80 固定80ms延迟常量
- [audio_sink.cpp:102-116] OnWriteData AudioVivid 回调
- [audio_sink.cpp:642,826,829] CalcMaxAmplitude 调用点
- [audio_sink.cpp:761-798] CopyAudioVividBufferData AudioVivid写入路径
- [subtitle_sink.cpp:144-145] 独立渲染线程启动
- [subtitle_sink.cpp:286-319] RenderLoop 主循环
- [subtitle_sink.cpp:353-363] ActionToDo 三状态决策函数 WAIT/SHOW/DROP
- [subtitle_sink.cpp:373-379] NotifyRender 事件上报 Tag::SUBTITLE_TEXT/PTS/DURATION
- [subtitle_sink.cpp:483+] RemoveTextTags HTML标签剥离