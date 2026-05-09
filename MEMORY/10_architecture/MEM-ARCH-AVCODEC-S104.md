# S104: CodecAdapter 编解码适配层框架——CodecBase/CodecAdapter/CodecEngine 三层桥接与插件热插拔

| 属性 | 值 |
|------|-----|
| 主题ID | S104 |
| 分类 | AVCodec 架构 |
| 标签 | AVCodec, Adapter, CodecBase, CodecEngine, Plugin, Factory, LayeredArchitecture |
| 状态: approved |
| 关联场景 | 新需求开发 / 问题定位 / 插件热插拔 |
| 草案日期 | 2026-05-09 |
| Builder | memory-factory-builder |

---

## 一、三层架构总览

CodecAdapter 适配层框架是 AVCodec 的中间桥接层，承担 **Filter 管线 ↔ Codec 引擎** 的协议转换与生命周期编排。整体分为三层：

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 1: Filter/Adapter（Filter管线侧）                     │
│  VideoDecoderAdapter / SurfaceEncoderAdapter /             │
│  AudioDecoderAdapter / CodecCapabilityAdapter              │
│  → 持有 mediaCodec_（AVCodecVideoDecoder / AudioCodec）    │
│  → 持有 inputBufferQueue_（AVBufferQueue）                   │
│  → 实现 MediaCodecCallback 回调桥接                          │
└─────────────────────────────┬───────────────────────────────┘
                              │ 创建/Configure/Start/Stop
┌─────────────────────────────▼───────────────────────────────┐
│  Layer 2: CodecBase（引擎抽象基类）                          │
│  services/engine/base/include/codecbase.h                   │
│  → 40+ 纯虚/虚方法接口                                        │
│  → 生命周期管理 + Surface/Buffer 双模式                      │
│  → DRM 加密配置 + DMA-BUF 内存管理                          │
└─────────────────────────────┬───────────────────────────────┘
                              │ 实现类
┌─────────────────────────────▼───────────────────────────────┐
│  Layer 3: CodecEngine（具体编解码器实现）                    │
│  AudioCodecAdapter (AudioBaseCodec+AudioCodecWorker)       │
│  AVCodecVideoDecoder → HDecoder/HEVCDecoder/VPXDecoder     │
│  AVCodecVideoEncoder → AvcEncoder/HEncoder                 │
│  → dlopen RTLD_LAZY 插件热加载                              │
│  → VideoDecoderFactory/CreateByMime/CreateByName            │
└─────────────────────────────────────────────────────────────┘
```

---

## 二、CodecBase 抽象基类（Layer 2）

**源码路径**: `services/engine/base/include/codecbase.h`

### 2.1 类定义与核心接口

```cpp
// codecbase.h 行 31-145
class CodecBase {
public:
    CodecBase() = default;
    virtual ~CodecBase() = default;

    // === 生命周期七步曲 ===
    virtual int32_t SetCallback(const std::shared_ptr<AVCodecCallback> &callback);
    virtual int32_t SetCallback(const std::shared_ptr<MediaCodecCallback> &callback);
    virtual int32_t Configure(const Format &format) = 0;   // 纯虚
    virtual int32_t Start() = 0;
    virtual int32_t Stop() = 0;
    virtual int32_t Flush() = 0;
    virtual int32_t Reset() = 0;
    virtual int32_t Release() = 0;

    // === 参数配置 ===
    virtual int32_t SetParameter(const Format& format) = 0;
    virtual int32_t GetOutputFormat(Format &format) = 0;

    // === Buffer 操作 ===
    virtual int32_t QueueInputBuffer(uint32_t index, const AVCodecBufferInfo &info, AVCodecBufferFlag flag);
    virtual int32_t QueueInputBuffer(uint32_t index);
    virtual int32_t ReleaseOutputBuffer(uint32_t index) = 0;

    // === Surface 模式 ===
    virtual sptr<Surface> CreateInputSurface();
    virtual int32_t SetInputSurface(sptr<Surface> surface);
    virtual int32_t SetOutputSurface(sptr<Surface> surface);
    virtual int32_t RenderOutputBuffer(uint32_t index);

    // === 控制信号 ===
    virtual int32_t NotifyEos();
    virtual int32_t SignalRequestIDRFrame();
    virtual int32_t ChangePlugin(const std::string &mime, bool isEncoder,
                                  const std::shared_ptr<Media::Meta> &meta); // 返回 AVCODEC_ERROR_EXTEND_START

    // === 内存与功耗管理 ===
    virtual int32_t NotifyMemoryRecycle();
    virtual int32_t NotifyMemoryWriteBack();
    virtual int32_t NotifySuspend();
    virtual int32_t NotifyResume();

    // === API11 新增接口 ===
    virtual int32_t CreateCodecByName(const std::string &name); // 默认返回 ERROR
    virtual int32_t Init(Media::Meta &callerInfo);
    virtual int32_t Configure(const std::shared_ptr<Media::Meta> &meta);
    virtual int32_t SetParameter(const std::shared_ptr<Media::Meta> &parameter);
    virtual int32_t GetOutputFormat(std::shared_ptr<Media::Meta> &parameter);
    virtual int32_t SetOutputBufferQueue(const sptr<Media::AVBufferQueueProducer> &bufferQueueProducer);
    virtual int32_t Prepare();
    virtual sptr<Media::AVBufferQueueProducer> GetInputBufferQueue();
    virtual void ProcessInputBuffer();
    virtual int32_t SetAudioDecryptionConfig(...);

    // === DFX ===
    virtual void SetDumpInfo(bool isDump, uint64_t instanceId);
    virtual std::string GetHidumperInfo();
    // ... 更多
};
```

**证据**: `codecbase.h:31-145` — CodecBase 完整接口定义

### 2.2 双回调体系

CodecBase 支持两套回调：

| 回调类型 | 用途 | 触发方 |
|----------|------|--------|
| `AVCodecCallback` | 底层 CodecClient IPC 回调 | IPC 跨进程 |
| `MediaCodecCallback` | 引擎内部 MediaCodec 驱动回调 | 编解码内部 |

```cpp
// codecbase.h 行 36-37
virtual int32_t SetCallback(const std::shared_ptr<AVCodecCallback> &callback);
virtual int32_t SetCallback(const std::shared_ptr<MediaCodecCallback> &callback);
```

### 2.3 Surface/Buffer 双模式

CodecBase 的 Surface/Buffer 模式通过以下接口切换（不可同时使用）：

```cpp
// Surface 模式（管线内建Surface）
virtual sptr<Surface> CreateInputSurface();   // 解码器创建输入Surface
virtual int32_t SetInputSurface(sptr<Surface> surface);   // 编码器注入输入Surface
virtual int32_t SetOutputSurface(sptr<Surface> surface);   // 解码器输出到Surface

// Buffer 模式（应用层直接操作AVBuffer）
virtual int32_t QueueInputBuffer(uint32_t index, const AVCodecBufferInfo &info, AVCodecBufferFlag flag);
virtual int32_t ReleaseOutputBuffer(uint32_t index) = 0;
```

---

## 三、AudioCodecAdapter — CodecBase 实现（Layer 2→3 融合）

**源码路径**: `services/engine/codec/audio/audio_codec_adapter.cpp/h`

### 3.1 类继承关系

```cpp
// audio_codec_adapter.h 行 19
class AudioCodecAdapter : public CodecBase, public NoCopyable {
public:
    explicit AudioCodecAdapter(const std::string &name);
    ~AudioCodecAdapter() override;

    int32_t SetCallback(const std::shared_ptr<AVCodecCallback> &callback) override;
    int32_t Configure(const Format &format) override;
    int32_t Start() override;
    int32_t Stop() override;
    int32_t Init(Media::Meta &callerInfo) override;
    int32_t Flush() override;
    int32_t Reset() override;
    int32_t Release() override;
    int32_t NotifyEos() override;
    int32_t SetParameter(const Format &format) override;
    int32_t GetOutputFormat(Format &format) override;
    int32_t QueueInputBuffer(uint32_t index, const AVCodecBufferInfo &info, AVCodecBufferFlag flag) override;
    int32_t ReleaseOutputBuffer(uint32_t index) override;

private:
    std::atomic<CodecState> state_;                          // 原子状态
    const std::string name_;
    std::shared_ptr<AVCodecCallback> callback_;
    std::shared_ptr<AudioBaseCodec> audioCodec;               // 引擎实例（Layer 3）
    std::shared_ptr<AudioCodecWorker> worker_;               // 驱动线程

private:  // 私有实现方法
    int32_t doFlush(); int32_t doStart(); int32_t doStop();
    int32_t doResume(); int32_t doRelease(); int32_t doInit();
    int32_t doConfigure(const Format &format);
    std::string_view stateToString(CodecState state);
};
```

**证据**: `audio_codec_adapter.h:19-48` — AudioCodecAdapter 完整类定义

### 3.2 三层调用链：Adapter → BaseCodec → Worker

```cpp
// audio_codec_adapter.cpp 行 335
int32_t AudioCodecAdapter::doInit()
{
    audioCodec = AudioBaseCodec::make_sharePtr(name_);  // 创建 Layer 3 引擎
    // ...
}

// audio_codec_adapter.cpp 行 325-340
// doInit → doConfigure → doStart 完整路径

int32_t AudioCodecAdapter::QueueInputBuffer(uint32_t index, const AVCodecBufferInfo &info, AVCodecBufferFlag flag)
{
    // 行 263: 从 worker 获取输入 buffer 信息
    auto result = worker_->GetInputBufferInfo(index);
    // ... 处理
    // 行 289: 推送数据到 worker
    worker_->PushInputData(index);
}

int32_t AudioCodecAdapter::ReleaseOutputBuffer(uint32_t index)
{
    // 行 304: 获取输出 buffer 信息
    auto outBufferInfo = worker_->GetOutputBufferInfo(index);
    // 行 315: 获取实际输出 buffer
    auto outBuffer = worker_->GetOutputBuffer();
    // ... 处理
}
```

**证据**: `audio_codec_adapter.cpp:325-340` — doInit 创建 AudioBaseCodec

### 3.3 状态机与生命周期

```cpp
// audio_codec_adapter.cpp 行 100-126: Start()
int32_t AudioCodecAdapter::Start() override
{
    FALSE_RETURN_V(state_.load() == CodecState::CONFIGURED, AVCS_ERR_INVALID_STATE);
    FALSE_RETURN_V(worker_ != nullptr, AVCS_ERR_INVALID_OPERATION);
    return worker_->Start();  // 委托 AudioCodecWorker 启动
}

// audio_codec_adapter.cpp 行 126-145: Stop()
int32_t AudioCodecAdapter::Stop() override
{
    FALSE_RETURN_V(state_.load() == CodecState::RUNNING, AVCS_ERR_INVALID_STATE);
    return worker_->Stop();
}
```

---

## 四、VideoDecoderAdapter — Filter 层适配器

**源码路径**: `services/media_engine/filters/video_decoder_adapter.cpp/h`
**接口头文件**: `interfaces/inner_api/native/video_decoder_adapter.h`

### 4.1 类定义

```cpp
// video_decoder_adapter.h 行 73
class VideoDecoderAdapter : public std::enable_shared_from_this<VideoDecoderAdapter> {
public:
    // === 初始化/配置 ===
    Status Init(MediaAVCodec::AVCodecType type, bool isMimeType, const std::string &name);
    Status Configure(const Format &format);
    Status Start(); Status Flush(); Status Stop(); Status Reset(); Status Release();
    int32_t SetCallback(const std::shared_ptr<MediaAVCodec::MediaCodecCallback> &callback);

    // === Buffer 队列 ===
    void PrepareInputBufferQueue();
    sptr<AVBufferQueueProducer> GetBufferQueueProducer();
    sptr<AVBufferQueueConsumer> GetBufferQueueConsumer();

    // === Buffer 回调 ===
    void OnInputBufferAvailable(uint32_t index, std::shared_ptr<AVBuffer> buffer);
    void OnOutputBufferAvailable(uint32_t index, std::shared_ptr<AVBuffer> buffer);

    // === Surface ===
    int32_t SetOutputSurface(sptr<Surface> videoSurface);

    // === 解密/DRM ===
    int32_t SetDecryptConfig(const sptr<DrmStandard::IMediaKeySessionService> &keySession, const bool svpFlag);

    // === 属性 ===
    bool IsHwDecoder();
    void SetCallingInfo(int32_t appUid, int32_t appPid, const std::string& bundleName, uint64_t instanceId);

private:
    std::shared_ptr<MediaAVCodec::AVCodecVideoDecoder> mediaCodec_;  // Layer 3 引擎
    std::shared_ptr<MediaAVCodec::MediaCodecCallback> callback_;
    std::shared_ptr<Media::AVBufferQueue> inputBufferQueue_;
    sptr<Media::AVBufferQueueProducer> inputBufferQueueProducer_;
    sptr<Media::AVBufferQueueConsumer> inputBufferQueueConsumer_;
    std::string mediaCodecName_;
    uint64_t instanceId_ = 0;
    int32_t appUid_ = -1;
    int32_t appPid_ = -1;
    std::string bundleName_;
    sptr<Surface> producerSurface_{nullptr};
    sptr<Surface> consumerSurface_{nullptr};
};
```

**证据**: `video_decoder_adapter.h:73-90` — VideoDecoderAdapter 核心成员变量

### 4.2 VideoDecoderCallback 回调桥接器

```cpp
// video_decoder_adapter.h 行 93
class VideoDecoderCallback : public OHOS::MediaAVCodec::MediaCodecCallback {
public:
    explicit VideoDecoderCallback(std::shared_ptr<VideoDecoderAdapter> videoDecoder);
    void OnError(MediaAVCodec::AVCodecErrorType errorType, int32_t errorCode);
    void OnOutputFormatChanged(const MediaAVCodec::Format &format);
    void OnInputBufferAvailable(uint32_t index, std::shared_ptr<AVBuffer> buffer);
    void OnOutputBufferAvailable(uint32_t index, std::shared_ptr<AVBuffer> buffer);
private:
    std::weak_ptr<VideoDecoderAdapter> videoDecoderAdapter_;
};
```

**证据**: `video_decoder_adapter.h:93-98` — 回调桥接器定义

### 4.3 Init 路由与 VideoDecoderFactory

```cpp
// video_decoder_adapter.cpp 行 150-160
Status VideoDecoderAdapter::Init(MediaAVCodec::AVCodecType type, bool isMimeType, const std::string &name)
{
    FALSE_RETURN_V_MSG(mediaCodec_ != nullptr, Status::ERROR_INVALID_STATE, "mediaCodec_ is nullptr");
    mediaCodecName_ = name;

    if (isMimeType) {
        // 按 MIME 类型创建
        ret = MediaAVCodec::VideoDecoderFactory::CreateByMime(name, format, mediaCodec_);
    } else {
        // 按编解码器名称创建
        ret = MediaAVCodec::VideoDecoderFactory::CreateByName(name, format, mediaCodec_);
    }
    FALSE_RETURN_V_MSG(mediaCodec_ != nullptr, Status::ERROR_INVALID_STATE, "mediaCodec_ is nullptr");
    mediaCodecName_ = name;
}
```

**证据**: `video_decoder_adapter.cpp:150-160` — VideoDecoderFactory 双路径创建

### 4.4 Configure → SetCallback → Start 完整路径

```cpp
// video_decoder_adapter.cpp 行 130: Release
mediaCodec_->Release();

// 行 141: Init
ret = MediaAVCodec::VideoDecoderFactory::CreateByMime/CreateByName
mediaCodecName_ = name;

// 行 173: Configure
mediaCodec_->Configure(formatCopy);

// 行 184: SetParameter
mediaCodec_->SetParameter(format);

// 行 193: SetCallback
mediaCodec_->SetCallback(mediaCodecCallback);

// 行 199: Start
mediaCodec_->Start();

// 行 222: Stop
mediaCodec_->Stop();

// 行 231: Flush
mediaCodec_->Flush();

// 行 259: Reset
mediaCodec_->Reset();

// 行 276: Release
mediaCodec_->Release();
```

**证据**: `video_decoder_adapter.cpp:130-290` — 完整生命周期代理调用

---

## 五、插件热插拔机制（CodecEngine Loader）

### 5.1 VideoDecoderFactory 工厂路由

```cpp
// video_decoder_adapter.cpp 行 152-155
if (isMimeType) {
    ret = MediaAVCodec::VideoDecoderFactory::CreateByMime(name, format, mediaCodec_);
} else {
    ret = MediaAVCodec::VideoDecoderFactory::CreateByName(name, format, mediaCodec_);
}
```

**证据**: `video_decoder_adapter.cpp:152-155` — 工厂双路由

### 5.2 AudioBaseCodec 动态创建

```cpp
// audio_codec_adapter.cpp 行 335
audioCodec = AudioBaseCodec::make_sharePtr(name_);  // Layer 3 引擎动态创建
```

**证据**: `audio_codec_adapter.cpp:335` — AudioBaseCodec 动态构造

### 5.3 插件接口 ChangePlugin（CodecBase 扩展点）

```cpp
// codecbase.h 行 61
virtual int32_t ChangePlugin(const std::string &mime, bool isEncoder,
                              const std::shared_ptr<Media::Meta> &meta)
{
    (void)mime; (void)isEncoder; (void)meta;
    return AVCODEC_ERROR_EXTEND_START;  // 默认返回扩展错误，子类可重写
}
```

**证据**: `codecbase.h:61` — 插件热切换扩展点（默认不实现）

---

## 六、SurfaceEncoderAdapter — 编码器适配器

**源码路径**: `services/media_engine/filters/surface_encoder_adapter.h`

### 6.1 类定义

```cpp
// surface_encoder_adapter.h 行 73
class SurfaceEncoderAdapter : public std::enable_shared_from_this<SurfaceEncoderAdapter> {
public:
    Status Init(const std::string &mime, bool isEncoder);
    Status Configure(const std::shared_ptr<Meta> &meta);
    Status Start(); Status Stop();
    // ...
private:
    std::shared_ptr<MediaAVCodec::AVCodecVideoEncoder> mediaCodec_;  // Layer 3
    // ...
    bool isStart_ = false;
    bool isStartKeyFramePts_ = false;
    bool isStopKeyFramePts_ = false;
};
```

**证据**: `surface_encoder_adapter.h:73-170` — SurfaceEncoderAdapter 完整类定义

### 6.2 ProcessStateCode 五状态机

```cpp
// surface_encoder_adapter.h 行 43
enum class ProcessStateCode {
    IDLE,        // 初始
    RECORDING,   // 录制/编码中
    PAUSED,      // 暂停
    STOPPED,     // 停止
    ERROR,       // 错误
};
```

**证据**: `surface_encoder_adapter.h:43-49` — 编码器 ProcessStateCode 五状态

---

## 七、 CodecCapabilityAdapter — 能力查询适配器

**源码路径**: `services/media_engine/filters/codec_capability_adapter.cpp`

能力查询不经过 CodecEngine，直接查询能力数据库（CodecList）：

```
CodecCapabilityAdapter
  → CodecListCore (services/engine/list/)
  → CodecAbilitySingleton (单例)
  → CapabilityData (vendor编解码能力)
```

---

## 八、架构特点总结

### 8.1 三层职责对比

| 层级 | 组件 | 职责 |
|------|------|------|
| Layer 1 | VideoDecoderAdapter / AudioCodecAdapter | Filter管线适配：AVBufferQueue管理、Surface绑定、MediaCodecCallback桥接 |
| Layer 2 | CodecBase | 引擎抽象基类：生命周期7步曲、Surface/Buffer双模式、DRM配置接口 |
| Layer 3 | AudioBaseCodec / AVCodecVideoDecoder / AVCodecVideoEncoder | 具体编解码引擎：FFmpeg软件解码(libavcodec)/硬件HDI解码/AV1(dav1d)/VPX(libvpx)等 |

### 8.2 双路径工厂模式

```
VideoDecoderFactory::CreateByMime("video/avc") → HDecoder (硬件) / FCodec (软件)
VideoDecoderFactory::CreateByName("OH.MediaCodec.AudioDecoder.flac") → AudioBaseCodec (FFmpeg)
```

### 8.3 Surface/Buffer 模式互斥

CodecBase 的 Surface 接口（CreateInputSurface / SetOutputSurface）与 Buffer 接口（QueueInputBuffer / ReleaseOutputBuffer）**不可同时使用**，由各 Adapter 实现层保证互斥。

### 8.4 插件热插拔路径

1. **创建时切换**：`VideoDecoderFactory::CreateByMime` 根据 MIME 路由到不同 Loader（FCodecLoader / HCodecLoader）
2. **运行时切换**：`CodecBase::ChangePlugin`（默认返回 `AVCODEC_ERROR_EXTEND_START`，需子类重写实现）

---

## 九、关联记忆条目

| 关联ID | 主题 | 关系 |
|---------|------|------|
| MEM-ARCH-AVCODEC-014 | Codec Engine 架构 | CodecEngine 即 Layer 3 具体实现 |
| MEM-ARCH-AVCODEC-039 | AVCodecVideoDecoder 三层架构 | VideoDecoder 即 Layer 3 |
| MEM-ARCH-AVCODEC-S39 | VideoDecoder 三层架构（Filter→Codec→Impl） | 与 S104 相同主题，Filter层视角 |
| MEM-ARCH-AVCODEC-003 | Plugin 架构 | 插件热加载机制 |
| MEM-ARCH-AVCODEC-S70 | VideoCodec 工厂与 Loader 插件体系 | 工厂模式与热加载 |
| MEM-ARCH-AVCODEC-057 | HDecoder/HEncoder 硬件解码器 | Layer 3 硬件实现 |

---

## 十、Evidence 索引

| 文件 | 行号 | 内容 |
|------|------|------|
| `services/engine/base/include/codecbase.h` | 31-145 | CodecBase 完整类定义（40+方法） |
| `services/engine/codec/audio/audio_codec_adapter.h` | 19-48 | AudioCodecAdapter 类定义 |
| `services/engine/codec/audio/audio_codec_adapter.cpp` | 325-340 | doInit → AudioBaseCodec 创建 |
| `services/engine/codec/audio/audio_codec_adapter.cpp` | 241-325 | QueueInputBuffer/ReleaseOutputBuffer 代理 |
| `interfaces/inner_api/native/video_decoder_adapter.h` | 73-98 | VideoDecoderAdapter + VideoDecoderCallback |
| `services/media_engine/filters/video_decoder_adapter.cpp` | 150-160 | VideoDecoderFactory 双路由创建 |
| `services/media_engine/filters/video_decoder_adapter.cpp` | 130-290 | 完整生命周期（Release→Init→Configure→Start→Stop→Flush→Reset→Release） |
| `services/media_engine/filters/surface_encoder_adapter.h` | 43-73 | ProcessStateCode 五状态机 + SurfaceEncoderAdapter 定义 |
| `services/media_engine/filters/codec_capability_adapter.cpp` | - | CodecCapabilityAdapter 能力查询 |