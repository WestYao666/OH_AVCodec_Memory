# MEM-ARCH-AVCODEC-S124 DRAFT

## 主题
录音Pipeline音频数据源与采集过滤器链——AudioDataSourceFilter / AudioCaptureFilter / AudioEncoderFilter 三联架构

## 状态
draft_pending_approval

## 关联记忆
S23 / S24 / S31 / S119

## Evidence 来源
- 本地镜像：`/home/west/av_codec_repo`
- 核心文件：
  - `services/media_engine/filters/audio_capture_filter.cpp` (790行)
  - `services/media_engine/filters/audio_data_source_filter.cpp` (343行)
  - `services/media_engine/filters/audio_encoder_filter.cpp` (381行)
  - `interfaces/inner_api/native/audio_capture_filter.h`
  - `interfaces/inner_api/native/audio_data_source_filter.h`
  - `interfaces/inner_api/native/audio_encoder_filter.h`

---

## 一、过滤器静态注册（工厂模式）

### AudioCaptureFilter
```cpp
// audio_capture_filter.cpp:38-41
static AutoRegisterFilter<AudioCaptureFilter> g_registerAudioCaptureFilter("builtin.recorder.audiocapture",
    FilterType::AUDIO_CAPTURE,
    [](const std::string& name, const FilterType type) {
        return std::make_shared<AudioCaptureFilter>(name, FilterType::AUDIO_CAPTURE);
    });
```

### AudioDataSourceFilter
```cpp
// audio_data_source_filter.cpp:32-35
static AutoRegisterFilter<AudioDataSourceFilter> g_registerAudioDataSourceFilter("builtin.recorder.audiodatasource",
    FilterType::AUDIO_DATA_SOURCE,
    [](const std::string& name, const FilterType type) {
        return std::make_shared<AudioDataSourceFilter>(name, FilterType::AUDIO_DATA_SOURCE);
    });
```

### AudioEncoderFilter
```cpp
// audio_encoder_filter.cpp:32-35
static AutoRegisterFilter<AudioEncoderFilter> g_registerAudioEncoderFilter("builtin.recorder.audioencoder",
    FilterType::FILTERTYPE_AENC,
    [](const std::string& name, const FilterType type) {
        return std::make_shared<AudioEncoderFilter>(name, FilterType::FILTERTYPE_AENC);
    });
```

**关键发现**：
- 三个 Filter 均使用 `AutoRegisterFilter<>` 静态注册机制
- AudioDataSourceFilter 的 `GetFilterType()` 返回 `FilterType::AUDIO_CAPTURE`（错误？或共享类型）
- FilterType 分工：AUDIO_CAPTURE / AUDIO_DATA_SOURCE / FILTERTYPE_AENC

---

## 二、AudioCaptureFilter——麦克风实时采集

### 核心常量
```cpp
// audio_capture_filter.cpp:28-29
static constexpr int32_t AUDIO_CAPTURE_MAX_CACHED_FRAMES = 256;
static constexpr int64_t AUDIO_CAPTURE_READ_FRAME_TIME = 20000000; // 20ms
static constexpr int64_t AUDIO_CAPTURE_READ_FRAME_TIME_HALF = 10000000;
```

### 内部模块
```cpp
// audio_capture_filter.cpp:116
audioCaptureModule_ = std::make_shared<AudioCaptureModule::AudioCaptureModule>();
// audio_capture_filter.cpp:124-125
audioCaptureModule_->SetAudioSource(sourceType_);
audioCaptureModule_->SetParameter(audioCaptureConfig_);
// audio_capture_filter.cpp:127
Status err = audioCaptureModule_->Init();
```

### 帧号计数与首帧时间戳
```cpp
// audio_capture_filter.cpp:182-183
recordAudioFrameCount_ = 0;
firstAudioFramePts_.store(-1);
firstVideoFramePts_.store(-1);
```

### Pause 时丢帧补偿逻辑
```cpp
// audio_capture_filter.cpp:218-235
if (withVideo_) {
    lostCount = ((pauseTime_ - currentTime_) + AUDIO_CAPTURE_READ_FRAME_TIME_HALF)
        / AUDIO_CAPTURE_READ_FRAME_TIME;
} else if (currentTime_ == 0) {
    lostCount = ((pauseTime_ - startTime_ + AUDIO_CAPTURE_READ_FRAME_TIME_HALF)
        / AUDIO_CAPTURE_READ_FRAME_TIME) - static_cast<int64_t>(cachedAudioDataDeque_.size());
    MEDIA_LOG_I("[audio] no video frame return, fill audio frame by startTime");
}
if (lostCount > AUDIO_CAPTURE_MAX_CACHED_FRAMES) {
    MEDIA_LOG_W("[audio] abnormal time diff, please check");
} else {
    FillLostFrame(lostCount);
}
if (!cachedAudioDataDeque_.empty()) {
    RecordCachedData(cachedAudioDataDeque_.size());
}
```

**关键设计**：
- `cachedAudioDataDeque_`：音频帧缓冲双端队列，容量上限 256 帧
- Pause 后恢复时，通过计算时间差补偿丢失的静音帧
- 超 256 帧阈值判定为时间异常，不填帧（防止无限膨胀）
- `withVideo_` 标志决定是否需要音视频同步补偿

---

## 三、AudioDataSourceFilter——外部音频数据注入

### 与 CaptureFilter 的区别
- CaptureFilter：实时采集（麦克风输入）
- DataSourceFilter：外部注入（屏幕录制、文件回填等场景）

### 数据推送流程
```cpp
// audio_data_source_filter.cpp:213-222
if (outputBufferQueue_) {
    ret = outputBufferQueue_->RequestBuffer(buffer, avBufferConfig, TIME_OUT_MS);
    outputBufferQueue_->PushBuffer(buffer, false);
}

// audio_data_source_filter.cpp:266
status = outputBufferQueue_->PushBuffer(buffer, true); // EOS
```

### LinkCallback 回调链
```cpp
// audio_data_source_filter.cpp:273-276
void AudioDataSourceFilter::OnLinkedResult(const sptr<AVBufferQueueProducer> &queue, std::shared_ptr<Meta> &meta)
{
    outputBufferQueue_ = queue;
}
```

---

## 四、AudioEncoderFilter——音频编码

### 元数据更新与编码器配置
```cpp
// audio_encoder_filter.cpp:294-303
Status AudioEncoderFilter::UpdateParameterToConfigure(const std::shared_ptr<Meta> &meta)
{
    Plugins::AudioSampleFormat dstSampleFormat = Plugins::AudioSampleFormat::INVALID_WIDTH;
    Plugins::AudioSampleFormat oriSampleFormat = Plugins::AudioSampleFormat::INVALID_WIDTH;
    if (meta != nullptr && configureParameter_ != nullptr && meta->GetData(Tag::AUDIO_SAMPLE_FORMAT, dstSampleFormat)) {
        configureParameter_->GetData(Tag::AUDIO_SAMPLE_FORMAT, oriSampleFormat);
        configureParameter_->SetData(Tag::AUDIO_SAMPLE_FORMAT, dstSampleFormat);
    }
    FALSE_RETURN_V(mediaCodec_ != nullptr, Status::ERROR_NULL_POINTER);
    int32_t ret = mediaCodec_->Configure(configureParameter_);
```

**关键设计**：
- `configureParameter_` 持有编码器配置参数
- OnLinked 时通过 `UpdateParameterToConfigure` 更新采样格式
- mediaCodec_ 是实际编码器实例

---

## 五、三联 Filter 数据流拓扑

```
[麦克风/外部数据源]
        |
        v
AudioDataSourceFilter  --->  (注入场景)
AudioCaptureFilter     --->  (实时采集)
        |
        v
AudioEncoderFilter     --->  (编码)
        |
        v
  下游 Filter（复用到 Muxer）
```

- 三个 Filter 通过 `outputBufferQueue_` (AVBufferQueueProducer) 向下游推送
- 回调链路：`FilterLinkCallback::OnLinkedResult` 建立连接
- Pause/Resume 由 `currentTime_` 和 `firstAudioFramePts_` 驱动同步

---

## 六、与 S119 的关联

S119 记录了 AudioSampleFormat 位深映射、CalcMaxAmplitude 振幅计算、AudioVivid 固定 80ms 延迟。
S124 聚焦录音 Filter 链本身（采集/数据源/编码），共同构成完整的录音 Pipeline 音频侧视图。

---

## 七、待补充（审批通过后完善）

- [ ] AudioDataSourceFilter GetFilterType 返回 AUDIO_CAPTURE 的设计意图
- [ ] AudioCaptureModule 内部的音频采集实现细节
- [ ] 三路 Filter 的具体 Link/Unlink 序列图
- [ ] 与 MediaSyncManager 的同步交互