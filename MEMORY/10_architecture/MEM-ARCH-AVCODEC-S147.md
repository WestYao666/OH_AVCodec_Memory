# MEM-ARCH-AVCODEC-S147: DataSink 数据输出体系 + MediaMuxer Track管理 + AudioCaptureModule 采集模块

**状态**: draft  
**主题**: DataSink 数据输出体系 + MediaMuxer Track管理 + AudioCaptureModule 实时采集模块  
**Scope**: AVCodec, MediaMuxer, DataSink, AudioCapture, AudioCaptureModule, Plugin, Track, AVBufferQueue, File, FD, Pipeline

---

## 1. DataSink 数据输出抽象层

### 1.1 DataSink 接口定义

**源码**: `interfaces/plugin/data_sink.h`

DataSink 是 OHOS MediaEngine 插件体系中的数据输出抽象基类，所有 Muxer 插件通过 DataSink 输出封装后的码流。

```cpp
// L24: DataSink 基类
class DataSink {
public:
    virtual ~DataSink() = default;
    virtual int32_t Read(uint8_t *buf, int32_t bufSize) = 0;
    virtual int32_t Write(const uint8_t *buf, int32_t bufSize) = 0;
    virtual int64_t Seek(int64_t offset, int whence) = 0;
    virtual int64_t GetCurrentPosition() const = 0;
    virtual bool CanRead() = 0;
};
```

- `Read()`: 从数据源读取（用于解封装场景）
- `Write()`: 写入数据（用于封装场景）
- `Seek()`: 定位（支持 SEEK_SET/SEEK_CUR/SEEK_END）
- `GetCurrentPosition()`: 获取当前位置
- `CanRead()`: 查询是否可读

### 1.2 DataSinkFile 文件数据输出

**源码**: `services/media_engine/modules/muxer/data_sink_file.h` + `data_sink_file.cpp`

```cpp
// data_sink_file.h L24: DataSinkFile 继承自 Plugins::DataSink
class DataSinkFile : public Plugins::DataSink {
public:
    explicit DataSinkFile(FILE *file);  // L27: 构造函数接收 FILE* 
    virtual ~DataSinkFile();

    int32_t Read(uint8_t *buf, int32_t bufSize) override;  // L30
    int32_t Write(const uint8_t *buf, int32_t bufSize) override;  // L31
    int64_t Seek(int64_t offset, int whence) override;  // L32
    int64_t GetCurrentPosition() const override;  // L33
    bool CanRead() override;  // L34

private:
    FILE *file_;  // L38: 底层 FILE 指针
    int64_t pos_;  // L39: 当前读写位置
    int64_t end_;  // L39: 文件末尾位置（pos_ >= end_ 时 Read 返回 0）
    bool isCanRead_;  // L40: 是否可读标志
};
```

**实现细节**（`data_sink_file.cpp`）：

```cpp
// L34: Seek 三路分发
switch (whence) {
    case SEEK_SET:  pos_ = offset; break;
    case SEEK_CUR:  pos_ = pos_ + offset; break;
    case SEEK_END:  pos_ = end_ + offset; break;  // L49: 相对于文件末尾
}

// L40: Read 逻辑——pos_ >= end_ 时返回 0（EOF）
// L43: fseek → fread → pos_ += size

// L60: Write 逻辑——fseek → fwrite → pos_ += size, end_ = max(pos_, end_)
```

**文件大小**: `data_sink_file.cpp` 98行 + `data_sink_file.h` 49行

### 1.3 DataSinkFd 文件描述符数据输出

**源码**: `services/media_engine/modules/muxer/data_sink_fd.h` + `data_sink_fd.cpp`

```cpp
// data_sink_fd.h L24: DataSinkFd 继承自 Plugins::DataSink
class DataSinkFd : public Plugins::DataSink {
public:
    explicit DataSinkFd(int32_t fd);  // L26: 构造函数接收 fd
    DataSinkFd(const DataSinkFd &other) = delete;
    DataSinkFd& operator=(const DataSinkFd&) = delete;
    virtual ~DataSinkFd();

    int32_t Read(uint8_t *buf, int32_t bufSize) override;  // L31
    int32_t Write(const uint8_t *buf, int32_t bufSize) override;  // L32
    int64_t Seek(int64_t offset, int whence) override;  // L33
    int64_t GetCurrentPosition() const override;  // L34
    bool CanRead() override;  // L35

private:
    int32_t fd_;  // L39: 底层文件描述符
    int64_t pos_;  // L40: 当前读写位置
    int64_t end_;  // L40: 文件末尾位置
    bool isCanRead_;  // L41: 是否可读标志
};
```

**实现细节**（`data_sink_fd.cpp`）：
- L24: `constexpr OHOS::HiviewDFX::HiLogLabel LABEL = { LOG_CORE, LOG_DOMAIN_MUXER, "HiStreamer" };`
- fd 模式构造函数 L34: 检查 fd 有效性并打印错误
- Read/Write/Seek 实现逻辑与 DataSinkFile 类似，通过 `::read`/`::write`/`lseek` 系统调用

**文件大小**: `data_sink_fd.cpp` 104行 + `data_sink_fd.h` 59行

### 1.4 DataSink 双实现对比

| 维度 | DataSinkFile | DataSinkFd |
|------|-------------|------------|
| 底层句柄 | `FILE *`（C 标准库） | `int32_t fd`（POSIX 系统调用） |
| 构造方式 | `Init(FILE *file)` | `Init(int32_t fd)` |
| 适用场景 | 文件路径+`fopen` | fd 传递（IPC/匿名管道） |
| Seek 语义 | `fseek`/`ftell` | `lseek` |
| 跨进程 | ❌ 不支持 | ✅ 支持（fd 跨进程传递） |
| 文件大小 | `data_sink_file.cpp` 98行 | `data_sink_fd.cpp` 104行 |

---

## 2. MediaMuxer 封装核心引擎

### 2.1 MediaMuxer 类定义

**源码**: `services/media_engine/modules/muxer/media_muxer.h`（106行）+ `media_muxer.cpp`（571行）

```cpp
// media_muxer.h L30: MediaMuxer 继承 Plugins::Callback
class MediaMuxer : public Plugins::Callback {
public:
    virtual ~MediaMuxer();
    virtual Status Init(int32_t fd, Plugins::OutputFormat format);  // L34: fd 模式初始化
    virtual Status Init(FILE *file, Plugins::OutputFormat format);  // L35: file 模式初始化
    virtual Status SetParameter(const std::shared_ptr<Meta> &param);  // L36
    virtual Status SetUserMeta(const std::shared_ptr<Meta> &userMeta);  // L37
    virtual Status AddTrack(int32_t &trackIndex, const std::shared_ptr<Meta> &trackDesc);  // L38
    virtual sptr<AVBufferQueueProducer> GetInputBufferQueue(uint32_t trackIndex);  // L39: AVBufferQueue 模式
    virtual Status Start();  // L40
    virtual Status WriteSample(uint32_t trackIndex, const std::shared_ptr<AVBuffer> &sample);  // L41: 同步模式
    virtual Status Stop();  // L42
    virtual Status Reset();  // L43

    // L47: State 枚举
    enum class State {
        UNINITIALIZED = 0,
        INITIALIZED = 1,
        STARTED = 2,
        STOPPED = 3,
    };

    // L67: Track 内部类
    class Track : public IConsumerListener {
    public:
        virtual ~Track() {}
        // ... 详见 2.3 节
    };
};
```

### 2.2 MediaMuxer 双模式输入

MediaMuxer 支持两种数据输入模式：

**模式 A: AVBufferQueue 异步输入**（`GetInputBufferQueue` L39）
- 调用 `GetInputBufferQueue(trackIndex)` 获取对应轨的 `AVBufferQueueProducer`
- Filter 层通过 `PushBuffer` 异步写入队列
- `Track::OnBufferAvailable()` 消费者回调驱动写盘
- 适用于：MuxerFilter（S34）多轨协调场景

**模式 B: WriteSample 同步输入**（`WriteSample` L41）
- 直接调用 `WriteSample(trackIndex, sample)` 同步写入
- `sample` 包含 PTS/DTS/flags（`AVCodecBufferAttr`）
- 适用于：直接调用场景

### 2.3 MediaMuxer::Track 内部类

```cpp
// media_muxer.h L67-78: Track 内部类，继承 IConsumerListener
class Track : public IConsumerListener {
public:
    virtual ~Track() {}
    virtual Status AddTrack(const std::shared_ptr<Meta> &trackDesc, int32_t &trackIndex);  // L68
    virtual sptr<AVBufferQueueProducer> GetInputBufferQueue();  // L69
    virtual Status WriteSample(const std::shared_ptr<AVBuffer> &sample);  // L70
    virtual void OnBufferAvailable();  // L71: IConsumerListener 实现
    virtual Status Stop();  // L72
    virtual bool IsTrackValid() const;  // L73
    virtual int32_t GetTrackId() const;  // L74
    virtual int64_t GetLastPts() const;  // L75
    // ... more
};
```

**Track 生命周期**：
1. `AddTrack()` → 创建 MuxerPlugin Track，分配 trackIndex
2. `GetInputBufferQueue()` → 获取 Producer 端，绑定消费者回调
3. `Start()` → 启动写入
4. `WriteSample()` / `OnBufferAvailable()` → 持续写入样本
5. `Stop()` → 停止并 flush

### 2.4 MediaMuxer 状态机

```cpp
// media_muxer.h L47-55: 四状态机
enum class State {
    UNINITIALIZED = 0,   // 构造函数后
    INITIALIZED = 1,     // Init() 成功
    STARTED = 2,         // Start() 成功
    STOPPED = 3,         // Stop() 后可 Reset
};
```

**状态转换**：
```
UNINITIALIZED → Init() → INITIALIZED
INITIALIZED → Start() → STARTED
STARTED → Stop() → STOPPED
STOPPED → Reset() → UNINITIALIZED
```

### 2.5 MediaMuxer 与 DataSink 关系

```cpp
// MediaMuxer 持有 DataSink（通过 MuxerPlugin 间接持有）
// MediaMuxer::Init(fd) → 创建 DataSinkFd
// MediaMuxer::Init(FILE* file) → 创建 DataSinkFile
// MuxerPlugin 通过 DataSink::Write() 输出封装码流
```

---

## 3. AudioCaptureModule 实时音频采集模块

### 3.1 AudioCaptureModule 类定义

**源码**: `services/media_engine/modules/source/audio_capture/audio_capture_module.h`（95行）+ `audio_capture_module.cpp`（509行）

```cpp
// audio_capture_module.h L39: AudioCaptureModule 主类
class AudioCaptureModule {
public:
    explicit AudioCaptureModule();  // L40
    ~AudioCaptureModule();  // L41
    Status Init();  // L42
    Status Deinit();  // L43
    Status Prepare();  // L44
    Status Reset();  // L45
    Status Start();  // L46
    Status Stop();  // L47
    Status GetParameter(std::shared_ptr<Meta> &meta);  // L48
    Status SetParameter(const std::shared_ptr<Meta> &meta);  // L49
    Status Read(std::shared_ptr<AVBuffer> &buffer, size_t expectedLen);  // L50: AVBuffer 模式
    Status Read(uint8_t *cacheAudioData, size_t expectedLen);  // L51: 裸指针模式
    void GetAudioTime(int64_t &audioDataTime, bool isFirstFrame);  // L52
    Status GetSize(uint64_t &size);  // L53
    Status SetAudioInterruptListener(const std::shared_ptr<AudioCaptureModuleCallback> &callback);  // L54
    Status SetAudioCapturerInfoChangeCallback(
        const std::shared_ptr<AudioStandard::AudioCapturerInfoChangeCallback> &callback);  // L55
    Status GetCurrentCapturerChangeInfo(AudioStandard::AudioCapturerChangeInfo &changeInfo);  // L56
    int32_t GetMaxAmplitude();  // L57: 获取最大振幅（用于音量监测）
    void SetAudioSource(AudioStandard::SourceType source);  // L58: 设置音频源类型
    void SetFaultEvent(const std::string &errMsg);  // L59
    void SetFaultEvent(const std::string &errMsg, int32_t ret);  // L60
    void SetCallingInfo(int32_t appUid, int32_t appPid, const std::string &bundleName, uint64_t instanceId);  // L61
    Status SetWillMuteWhenInterrupted(bool muteWhenInterrupted);  // L62

private:
    Mutex captureMutex_ {};  // L67: 线程安全锁
    std::unique_ptr<OHOS::AudioStandard::AudioCapturer> audioCapturer_ {nullptr};  // L69: 底层 AudioCapturer
    std::shared_ptr<AudioStandard::AudioCapturerInfoChangeCallback> audioCapturerInfoChangeCallback_ {nullptr};  // L70
    AudioStandard::AudioCapturerOptions options_ {};  // L71: 采集配置选项
    std::shared_ptr<AudioCaptureModuleCallback> audioCaptureModuleCallback_ {nullptr};  // L72
    std::shared_ptr<AudioStandard::AudioCapturerCallback> audioInterruptCallback_ {nullptr};  // L73
    int64_t bitRate_ {0};  // L74
    int32_t appTokenId_ {0};  // L75
    int32_t appUid_ {0};  // L76
    int32_t appPid_ {0};  // L77
    int64_t appFullTokenId_ {0};  // L78
    size_t bufferSize_ {0};  // L79
    int32_t maxAmplitude_ {0};  // L80: 当前最大振幅
    bool isTrackMaxAmplitude {false};  // L81: 是否追踪振幅
    std::string bundleName_;  // L82
    uint64_t instanceId_{0};  // L83
};
```

### 3.2 AudioCaptureModuleCallback 中断回调接口

```cpp
// audio_capture_module.h L32-37: 音频中断监听回调
class AudioCaptureModuleCallback {
public:
    virtual ~AudioCaptureModuleCallback() = default;
    virtual void OnInterrupt(const std::string &interruptInfo) = 0;  // L36: 音频焦点中断通知
};
```

### 3.3 AudioCapturerCallbackImpl 实现

**源码**: `audio_capture_module.cpp` L44-70

```cpp
// L44: AudioCapturerCallbackImpl 继承 AudioStandard::AudioCapturerCallback
class AudioCapturerCallbackImpl : public AudioStandard::AudioCapturerCallback {
    void OnInterrupt(const AudioStandard::InterruptEvent &interruptEvent) override  // L51
};
```

**OnInterrupt 处理逻辑**（`audio_capture_module.cpp` L51-65）：
```cpp
// L53-58: 解析中断原因
// L58: FORCE_PAUSE（系统强制暂停）→ 通知 MediaCodecServer
// L60: 静音状态变化事件被忽略（"ignore..."）

// L63: audioCaptureModuleCallback_->OnInterrupt() → 上层 Filter 感知中断
```

### 3.4 参数校验三函数

```cpp
// audio_capture_module.cpp L270: 采样率校验
bool AudioCaptureModule::AssignSampleRateIfSupported(const int32_t value)
// L272: static_cast<uint32_t>(value) 转换为 AudioStandard 采样率
// L276: 检查 options_.streamInfo.samplingRate 是否在支持范围内

// audio_capture_module.cpp L285: 通道数校验
bool AudioCaptureModule::AssignChannelNumIfSupported(const int32_t value)
// L287: static_cast<uint32_t>(value)
// L290: constexpr uint32_t maxSupportChannelNum = 2（最大支持双声道）

// audio_capture_module.cpp L305: 采样格式校验
bool AudioCaptureModule::AssignSampleFmtIfSupported(const Plugins::AudioSampleFormat value)
// L310: 不支持时打印 "sample format X not supported"
```

### 3.5 Read 双模式

```cpp
// L320: Read(AVBuffer) — 音频数据封装为 AVBuffer 返回
Status AudioCaptureModule::Read(std::shared_ptr<AVBuffer> &buffer, size_t expectedLen)
// L322: MEDIA_LOG_D("AudioCaptureModule Read")
// L344: audioCapturer_->Read(*bufData->GetAddr(), expectedLen, true)
// L346: FALSE_RETURN_V_MSG_E(size >= 0, Status::ERROR_NOT_ENOUGH_DATA)
// L350: TrackMaxAmplitude() 振幅追踪（L350 内部调用）

// L355: Read(裸指针) — 直接写入调用者缓冲区
Status AudioCaptureModule::Read(uint8_t *cacheAudioData, size_t expectedLen)
// L366: audioCapturer_->Read(*cacheAudioData, expectedLen, true)
// L368: 同上错误处理
// L371: TrackMaxAmplitude() 振幅追踪
```

### 3.6 GetMaxAmplitude 振幅监测

```cpp
// L456: GetMaxAmplitude 获取当前最大振幅
int32_t AudioCaptureModule::GetMaxAmplitude()
// L458-459: if (!isTrackMaxAmplitude) { isTrackMaxAmplitude = true; }
// 用于录音音量监测 UI（音量条显示）

// L471: TrackMaxAmplitude 内部实现
void AudioCaptureModule::TrackMaxAmplitude(int16_t *data, int32_t size)
// L472: 遍历 PCM 数据，找到最大峰值
// L348/L370: Read 成功后自动调用 TrackMaxAmplitude
```

### 3.7 Start/Stop 生命周期

```cpp
// L158: Status AudioCaptureModule::Start()
// L164: audioCapturer_->Start() 启动底层 AudioCapturer
// L166: 失败时 SetFaultEvent("AudioCaptureModule::Start error")

// L174: Status AudioCaptureModule::Stop()
// L179: audioCapturer_->Stop()
// L181: 失败时 SetFaultEvent("AudioCaptureModule::Stop error")
```

### 3.8 SetParameter 音频参数配置

```cpp
// L226: SetParameter 配置音频参数
Status AudioCaptureModule::SetParameter(const std::shared_ptr<Meta> &meta)
// L236-248: 从 Meta 中提取采样率/通道数/采样格式
// L236: AssignSampleRateIfSupported(sampleRate)
// L242: AssignChannelNumIfSupported(channelCount)
// L248: AssignSampleFmtIfSupported(static_cast<Plugins::AudioSampleFormat>(sampleFormat))
// L263: 不支持 PCM 编码时 SetFaultEvent
```

---

## 4. 三组件协作关系

```
┌─────────────────────────────────────────────────────────────┐
│                     MediaMuxer                               │
│  services/media_engine/modules/muxer/media_muxer.cpp (571行) │
│                                                              │
│  State: UNINITIALIZED → INITIALIZED → STARTED → STOPPED     │
│                                                              │
│  DataSink (Plugins::DataSink)                                │
│    ├── DataSinkFile (FILE* mode)      data_sink_file.cpp     │
│    └── DataSinkFd    (fd mode)        data_sink_fd.cpp       │
│                                                              │
│  Track::IConsumerListener ──── AVBufferQueue 异步写入        │
│  WriteSample ─────────────────── 同步写入                     │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                AudioCaptureModule                            │
│  services/media_engine/modules/source/audio_capture/         │
│  audio_capture_module.cpp (509行) + audio_capture_module.h   │
│                                                              │
│  AudioCapturer (AudioStandard) ─── 实时音频采集              │
│  AudioCaptureModuleCallback ──────── OnInterrupt 中断通知     │
│                                                              │
│  双 Read 模式: AVBuffer / 裸指针                            │
│  GetMaxAmplitude / TrackMaxAmplitude ── 音量监测             │
└─────────────────────────────────────────────────────────────┘

DataSink 被 MediaMuxer 持有，通过 MuxerPlugin::Write() 输出封装码流
AudioCaptureModule 被 AudioCaptureFilter (audio_capture_filter.cpp:790行) 持有
```

---

## 5. 行号级证据索引

| 文件 | 行数 | 关键符号 |
|------|------|----------|
| `interfaces/plugin/data_sink.h` | ~30行 | `DataSink` 基类 L24 |
| `services/media_engine/modules/muxer/data_sink_file.h` | 49行 | `DataSinkFile` L24 |
| `services/media_engine/modules/muxer/data_sink_file.cpp` | 98行 | `Read/Write/Seek` L34-60 |
| `services/media_engine/modules/muxer/data_sink_fd.h` | 59行 | `DataSinkFd` L24 |
| `services/media_engine/modules/muxer/data_sink_fd.cpp` | 104行 | fd 构造 L34 |
| `services/media_engine/modules/muxer/media_muxer.h` | 106行 | `MediaMuxer` L30, State L47, Track L67 |
| `services/media_engine/modules/muxer/media_muxer.cpp` | 571行 | 全函数实现 |
| `services/media_engine/modules/source/audio_capture/audio_capture_module.h` | 95行 | `AudioCaptureModule` L39, Callback L32 |
| `services/media_engine/modules/source/audio_capture/audio_capture_module.cpp` | 509行 | `Read` L320/L355, `GetMaxAmplitude` L456, `AssignSampleRateIfSupported` L270, `AssignChannelNumIfSupported` L285, `AssignSampleFmtIfSupported` L305 |

---

## 6. 关联主题

| 主题 | 关联说明 |
|------|----------|
| S34 | MuxerFilter — MediaMuxer 的 Filter 层入口 |
| S65 | MediaMuxer Track 管理 + AVBufferQueue 异步写入 |
| S40/S91 | FFmpegMuxerPlugin / Mpeg4MuxerPlugin — 使用 DataSink 输出码流 |
| S74 | FFmpegMuxerPlugin 与 Mpeg4MuxerPlugin 双插件对比 |
| S124 | AudioCaptureFilter — AudioCaptureModule 的 Filter 层封装 |
| S119 | AudioSampleFormat — 音频采样格式位深映射，与 AudioCaptureModule 参数校验关联 |
| S78 | AudioServerSinkPlugin — 播放管线音频输出，与 AudioCaptureModule 对称（采集 vs 渲染） |