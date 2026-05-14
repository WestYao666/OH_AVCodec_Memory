# MEM-ARCH-AVCODEC-S124: 录音 Pipeline 音频数据源与采集过滤器链——AudioDataSourceFilter / AudioCaptureFilter / AudioEncoderFilter 三联架构

**状态**: approved  
**approved_at**: 2026-05-15T00:39  
**主题**: 录音 Pipeline 音频数据源与采集过滤器链——AudioDataSourceFilter / AudioCaptureFilter / AudioEncoderFilter 三联架构  
**生成时间**: 2026-05-14T04:42  
**关联主题**: S23(SurfaceEncoderAdapter), S24(AudioEncoderFilter), S31(AudioSinkFilter), S78(MediaSyncManager), S119(AudioSampleFormat)  
**Scope**: AVCodec, MediaEngine, Filter, AudioCapture, AudioDataSource, AudioEncoder, Recorder, Pipeline, FilterChain

---

## 1. 录音 Pipeline 音频过滤器全景

录音 Pipeline 在 MediaEngine FilterChain 中存在两类音频数据源过滤器，分别服务不同场景：

| Filter | 注册名 | FilterType | 场景 | 数据来源 |
|--------|--------|------------|------|----------|
| AudioCaptureFilter | `builtin.recorder.audiocapture` | AUDIO_CAPTURE | 麦克风录音 | AudioCaptureModule (实时音频采集) |
| AudioDataSourceFilter | `builtin.recorder.audiodatasource` | AUDIO_DATA_SOURCE | 屏幕录制/回声 | 外部 AudioDataSource 数据注入 |
| AudioEncoderFilter | `builtin.recorder.audioencoder` | AUDIO_ENCODER | 编码 | 前级 filter 输出 |
| AudioSinkFilter | `builtin.player.audiosink` | AUDIO_SINK | 播放 | 解码后音频 |

**与 S23 对比**：S23 的 SurfaceEncoderAdapter 服务视频编码器（FilterType::VIDEO_CAPTURE）；S124 服务录音 Pipeline 音频链路。

---

## 2. AudioCaptureFilter 架构（790行cpp）

### 2.1 静态注册与 FilterType

**源码**: `services/media_engine/filters/audio_capture_filter.cpp`

```cpp
// L38-41: AutoRegisterFilter 静态注册
static AutoRegisterFilter<AudioCaptureFilter> g_registerAudioCaptureFilter("builtin.recorder.audiocapture",
    FilterType::AUDIO_CAPTURE,
    [](const std::string& name, const FilterType type) {
        return std::make_shared<AudioCaptureFilter>(name, FilterType::AUDIO_CAPTURE);
    });
```

- 注册名：`builtin.recorder.audiocapture`
- FilterType：`AUDIO_CAPTURE`
- 用途：麦克风实时音频采集，专为 Recorder 场景设计

### 2.2 核心成员与依赖

```cpp
// L99: 构造函数
AudioCaptureFilter::AudioCaptureFilter(std::string name, FilterType type): Filter(name, type)

// L116: Init 中创建 AudioCaptureModule
audioCaptureModule_ = std::make_shared<AudioCaptureModule::AudioCaptureModule>();

// L119-127: Init 初始化链
FALSE_RETURN_MSG(audioCaptureModule_ != nullptr, "AudioCaptureFilter audioCaptureModule_ is nullptr, Init fail.");
Status cbError = audioCaptureModule_->SetAudioInterruptListener(cb);  // L120: 中断监听
audioCaptureModule_->SetAudioSource(sourceType_);  // L124: 设置音频源类型（麦克风/回声等）
audioCaptureModule_->SetParameter(audioCaptureConfig_);  // L125: 设置采集参数（采样率/通道/位深）
audioCaptureModule_->SetCallingInfo(appUid_, appPid_, bundleName_, instanceId_);  // L126: 调用者信息
Status err = audioCaptureModule_->Init();  // L127: 初始化
```

### 2.3 生命周期状态机

```cpp
// L188-213: DoStart 启动序列
Status AudioCaptureFilter::DoStart() {
    eos_ = false;
    currentTime_ = 0;
    recordAudioFrameCount_ = 0;
    firstAudioFramePts_.store(-1);  // L196: 首帧PTS初始化
    firstVideoFramePts_.store(-1);
    hasCalculateAVTime_ = false;
    GetCurrentTime(startTime_);
    // L191: 先启动 AudioCaptureModule
    if (audioCaptureModule_) {
        res = audioCaptureModule_->Start();
    }
    // L193: 再启动 Task（ReadLoop 线程）
    if (taskPtr_) {
        taskPtr_->Start();
    }
}

// L200-245: DoPause 暂停（含丢帧补偿）
Status AudioCaptureFilter::DoPause() {
    if (taskPtr_) {
        taskPtr_->Pause();
    }
    if (audioCaptureModule_) {
        ret = audioCaptureModule_->Stop();  // L209: 底层 Stop
    }
    GetCurrentTime(pauseTime_);
    if (withVideo_) {
        // L215-232: 计算丢失帧数并填充静音帧
        lostCount = ((pauseTime_ - currentTime_) + AUDIO_CAPTURE_READ_FRAME_TIME_HALF)
            / AUDIO_CAPTURE_READ_FRAME_TIME;
        if (lostCount > AUDIO_CAPTURE_MAX_CACHED_FRAMES) {  // L228: 上限 256 帧
            MEDIA_LOG_W("[audio] abnormal time diff, please check");
        } else {
            FillLostFrame(lostCount);  // 补偿静音帧
        }
    }
}

// L247-271: DoResume 恢复
Status AudioCaptureFilter::DoResume() {
    currentTime_ = 0;
    firstAudioFramePts_.store(-1);
    firstVideoFramePts_.store(-1);
    hasCalculateAVTime_ = false;
    GetCurrentTime(startTime_);
    if (taskPtr_) {
        taskPtr_->Start();
    }
    if (audioCaptureModule_) {
        ret = audioCaptureModule_->Start();
    }
}

// L273-297: DoStop 停止
Status AudioCaptureFilter::DoStop() {
    if (taskPtr_) {
        taskPtr_->StopAsync();  // L277: 先停 Task
    }
    if (audioCaptureModule_) {
        ret = audioCaptureModule_->Stop();  // L280: 再停 AudioCaptureModule
    }
    if (ret != Status::OK) {
        MEDIA_LOG_E("audioCaptureModule stop fail");
    }
    return ret;
}
```

### 2.4 ReadLoop 数据读取线程

```cpp
// L138-143: Prepare 中注册 ReadLoop Job
Status AudioCaptureFilter::PrepareAudioCapture() {
    if (!taskPtr_) {
        taskPtr_ = std::make_shared<Task>("DataReader", groupId_, TaskType::AUDIO);
        taskPtr_->RegisterJob([this] {
            ReadLoop();
            return 0;
        });
    }
    // L148: audioCaptureModule_->Prepare()
}

// L383-446: ReadLoop 实现
void AudioCaptureFilter::ReadLoop() {
    // L394: 队列上限检查
    if (cachedAudioDataDeque_.size() > AUDIO_CAPTURE_MAX_CACHED_FRAMES) {  // 256 帧
        RelativeSleep(AUDIO_CAPTURE_READ_FAILED_WAIT_TIME);  // L399: 等待 20ms
    }
    // L411: 读取音频数据并放入缓存队列
    auto buffer = audioCaptureModule_->Read();  // 底层 AudioCaptureModule
    cachedAudioDataDeque_.push_back(buffer);
}
```

### 2.5 常量定义

```cpp
// L26-31: 关键常量
static constexpr int64_t AUDIO_CAPTURE_READ_FAILED_WAIT_TIME = 20000000;  // 20ms
static constexpr int64_t AUDIO_CAPTURE_READ_FRAME_TIME = 20000000;       // 20ms 帧间隔
static constexpr int64_t AUDIO_CAPTURE_READ_FRAME_TIME_HALF = 10000000;   // 10ms 半帧
static constexpr int32_t AUDIO_CAPTURE_MAX_CACHED_FRAMES = 256;          // 最大缓存帧数
static constexpr int32_t AUDIO_RECORDER_FRAME_NUM = 5;
static constexpr uint64_t MAX_CAPTURE_BUFFER_SIZE = 100000;
```

---

## 3. AudioDataSourceFilter 架构（343行cpp）

### 3.1 静态注册

**源码**: `services/media_engine/filters/audio_data_source_filter.cpp`

```cpp
// L32-35: AutoRegisterFilter 静态注册
static AutoRegisterFilter<AudioDataSourceFilter> g_registerAudioDataSourceFilter("builtin.recorder.audiodatasource",
    FilterType::AUDIO_DATA_SOURCE,
    [](const std::string& name, const FilterType type) {
        return std::make_shared<AudioDataSourceFilter>(name, FilterType::AUDIO_DATA_SOURCE);
    });
```

- 注册名：`builtin.recorder.audiodatasource`
- FilterType：`AUDIO_DATA_SOURCE`
- 用途：屏幕录制场景的音频数据注入（非麦克风），也用于回声消除等场景

### 3.2 Init 与 Task 线程

```cpp
// L88-100: Init 实现
void AudioDataSourceFilter::Init(const std::shared_ptr<EventReceiver> &receiver,
    const std::shared_ptr<FilterCallback> &callback) {
    receiver_ = receiver;
    callback_ = callback;
    if (!taskPtr_) {
        taskPtr_ = std::make_shared<Task>("DataReader", groupId_, TaskType::AUDIO);
        taskPtr_->RegisterJob([this] { ReadLoop(); return 0; });  // L96: 注册 ReadLoop
    }
}

// L88: 常量定义
static constexpr int64_t AUDIO_DATASOURCE_FILTER_READ_FAILED_WAIT_TIME = 21333333; // 约21ms
static constexpr int64_t AUDIO_DATASOURCE_FILTER_READ_SUCCESS_WAIT_TIME = 4000000;   // 4ms
```

### 3.3 与 AudioCaptureFilter 的关键区别

| 特性 | AudioCaptureFilter | AudioDataSourceFilter |
|------|-------------------|----------------------|
| 数据来源 | AudioCaptureModule (实时采集) | 外部 AudioDataSource 注入 |
| 注册名 | `builtin.recorder.audiocapture` | `builtin.recorder.audiodatasource` |
| FilterType | AUDIO_CAPTURE | AUDIO_DATA_SOURCE |
| 使用场景 | 麦克风录音 | 屏幕录制/回声 |
| 缓存上限 | 256帧 | 无（外部控制） |
| 丢帧补偿 | 支持（FillLostFrame） | 不支持 |

---

## 4. AudioEncoderFilter 编码过滤器（S24 已有，补充链接）

**源码**: `services/media_engine/filters/audio_encoder_filter.cpp`  
**注册名**: `builtin.recorder.audioencoder`  
**FilterType**: AUDIO_ENCODER

关键证据（S24 草案已有，此处补充 FilterChain 上下文）：

```cpp
// 录音 Pipeline 串联：
// AudioCaptureFilter → (AVBufferQueue) → AudioEncoderFilter → (AVBufferQueue) → MuxerFilter
// 或
// AudioDataSourceFilter → (AVBufferQueue) → AudioEncoderFilter → (AVBufferQueue) → MuxerFilter
```

---

## 5. FilterChain 中的串联机制

### 5.1 FilterLinkCallback 握手协议

```cpp
// audio_capture_filter.cpp L46-74: AudioCaptureFilterLinkCallback
class AudioCaptureFilterLinkCallback : public FilterLinkCallback {
public:
    void OnLinkedResult(const sptr<AVBufferQueueProducer> &queue, std::shared_ptr<Meta> &meta) override;
    void OnUnlinkedResult(std::shared_ptr<Meta> &meta) override;
    void OnUpdatedResult(std::shared_ptr<Meta> &meta) override;
private:
    std::weak_ptr<AudioCaptureFilter> audioCaptureFilter_;
};
```

### 5.2 录音 Pipeline 完整链路

```
[AudioCaptureFilter / AudioDataSourceFilter]
         ↓ (AVBufferQueueProducer)
    [AudioEncoderFilter]
         ↓ (AVBufferQueueProducer)
    [MuxerFilter]
         ↓
    [FileOutput] (MP4/MKV)
```

### 5.3 与 S119(AudioSampleFormat) 的关联

- AudioCaptureFilter 输出的 PCM 数据位深由 `audioCaptureConfig_`（L125）决定
- AudioSampleFormatToBitDepth (audio_sampleformat.cpp:58) 负责位深映射
- AudioEncoderFilter 接收前需通过 CalcMaxAmplitude (calc_max_amplitude.cpp:139) 校验音量

---

## 6. 与已有记忆的关联分析

| 已有记忆 | 关联点 | 补充内容 |
|----------|--------|----------|
| S23 (SurfaceEncoderAdapter) | 同为 recorder 管线 filter | S23 视频，S124 音频 |
| S24 (AudioEncoderFilter) | 录音管线下一站 | S124 提供输入，S24 执行编码 |
| S31 (AudioSinkFilter) | FilterChain 模式一致 | AudioSink 用于播放，AudioCapture 用于录音 |
| S78 (MediaSyncManager) | 音视频同步 | 录音场景的 AV 同步点（firstAudioFramePts_） |
| S119 (AudioSampleFormat) | 音频格式处理 | AudioCapture 输出 PCM 格式映射 |
| S14 (FilterChain) | FilterLinkCallback 机制 | FilterChain 通用握手协议 |

---

## 7. 行号级证据汇总

| 文件 | 行数 | 关键 evidence |
|------|------|--------------|
| `services/media_engine/filters/audio_capture_filter.cpp` | 790行 | L38-41 AutoRegisterFilter / L99 构造 / L116 AudioCaptureModule 创建 / L120-127 Init 链 / L188-213 DoStart / L200-245 DoPause+FillLostFrame / L247-271 DoResume / L273-297 DoStop / L383-446 ReadLoop / L26-31 常量 |
| `services/media_engine/filters/audio_data_source_filter.cpp` | 343行 | L32-35 AutoRegisterFilter / L88-100 Init+Task / L96 ReadLoop 注册 |
| `services/media_engine/filters/audio_encoder_filter.cpp` | (见S24) | FilterChain 串联节点 |

---

## 8. 主题编号确认

- S123 已存在（StreamDemuxer 流式解封装器）
- 本主题编号：**S124**
- backlog.yaml 需新增注册条目（status: pending_approval）