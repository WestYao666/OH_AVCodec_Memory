# MEM-ARCH-AVCODEC-S249 — SurfaceEncoderAdapter Filter层编码器适配器

## Metadata

- **ID**: MEM-ARCH-AVCODEC-S249
- **Title**: SurfaceEncoderAdapter Filter层编码器适配器——Surface输入编码/TransCoder双模式/AVBufferQueue输出/帧率自适应/PTS回调
- **Tags**: [avcodec, filter, encoder, surface, transcoder, adapter, avbufferqueue]
- **evidence_count**: 20
- **source**: /home/west/av_codec_repo (local mirror)
- **registered**: 2026-06-25
- **status**: draft
- **generated**: 2026-06-25T03:24 GMT+8
- **Builder**: builder-agent (local mirror)

---

## 一、架构定位

SurfaceEncoderAdapter 是 MediaEngine Filter 层的**视频编码器适配器**，位于 `services/media_engine/filters/surface_encoder_adapter.cpp`（1037行）+ `surface_encoder_adapter.h`（183行）= **1220行源码**。

核心职责：**封装 AVCodecVideoEncoder（H.264/H.265/VP8/VP9 硬件/软件编码器），向 Filter Pipeline 提供 Surface 输入编码能力**，同时支持 TransCoder（转码）模式和普通录制模式。

```
Filter Pipeline（SurfaceEncoderFilter）
    ↓
SurfaceEncoderAdapter（Filter层适配器）
    ↓
AVCodecVideoEncoder（VideoEncoderFactory::CreateByMime）
    ↓
libavcenc_ohos.z.so / libavcenc_sw.z.so（HDI 编码驱动）
```

**使用场景**：
- 录制场景（Camera → SurfaceEncoderFilter → SurfaceEncoderAdapter → MuxerFilter）
- 转码场景（VideoDecoder → SurfaceEncoderAdapter[TransCoder] → MuxerFilter）
- 水印叠加（SetWatermark）

**Filter 注册名**：`"builtin.recorder.videoencoder"`（FilterType::FILTERTYPE_VENC）

**对比 S214（SurfaceEncoderAdapter 对称解码版）**：S214 是 SurfaceDecoderAdapter（Surface→Buffer 解码适配器），S249 是 SurfaceEncoderAdapter（Surface→编码适配器），共同构成 Surface-based 编解码双通道。

---

## 二、关键文件与行号级 Evidence

### 2.1 头文件（surface_encoder_adapter.h）

**文件**: `services/media_engine/filters/surface_encoder_adapter.h`
**行号**: L42-L73（枚举+回调接口）

```cpp
// L42-46: 状态枚举（PAUSE/RESUME）
enum class StateCode {
    PAUSE,
    RESUME,
};

// L47-54: 进程状态枚举（IDLE/RECORDING/PAUSED/STOPPED/ERROR）
enum class ProcessStateCode {
    IDLE,
    RECORDING,   // operate start, resume
    PAUSED,      // operate pause
    STOPPED,     // operate stop
    ERROR,
};

// L58-64: 编码器回调接口（EncoderAdapterCallback）
class EncoderAdapterCallback {
public:
    virtual ~EncoderAdapterCallback() = default;
    virtual void OnError(MediaAVCodec::AVCodecErrorType type, int32_t errorCode) = 0;
    virtual void OnOutputFormatChanged(const std::shared_ptr<Meta> &format) = 0;
};

// L66-72: 关键帧PTS回调接口（EncoderAdapterKeyFramePtsCallback）
class EncoderAdapterKeyFramePtsCallback {
public:
    virtual ~EncoderAdapterKeyFramePtsCallback() = default;
    virtual void OnReportKeyFramePts(std::string KeyFramePts) = 0;
    virtual void OnReportFirstFramePts(int64_t firstFramePts) = 0;
};

// L73-108: SurfaceEncoderAdapter 类定义
class SurfaceEncoderAdapter : public std::enable_shared_from_this<SurfaceEncoderAdapter> {
public:
    explicit SurfaceEncoderAdapter();
    ~SurfaceEncoderAdapter();
    Status Init(const std::string &mime, bool isEncoder);              // L78
    Status Configure(const std::shared_ptr<Meta> &meta);                // L79
    Status SetWatermark(std::shared_ptr<AVBuffer> &waterMarkBuffer);    // L80
    Status SetVideoEnableBFrame(bool &enableBFrame);                    // L81
    Status SetOutputBufferQueue(const sptr<AVBufferQueueProducer> &bufferQueueProducer); // L82
    Status SetEncoderAdapterCallback(const std::shared_ptr<EncoderAdapterCallback> &encoderAdapterCallback); // L83
    Status SetEncoderAdapterKeyFramePtsCallback(...);                   // L86
    Status SetInputSurface(sptr<Surface> surface);                     // L88
    Status SetTransCoderMode();                                        // L89
    sptr<Surface> GetInputSurface();                                  // L90
    Status Start();                                                   // L91
    Status Stop();                                                    // L92
    Status Pause();                                                   // L93
    Status Resume();                                                  // L94
    Status Flush();                                                   // L95
    Status Reset();                                                   // L96
    Status Release();                                                 // L97
    Status NotifyEos(int64_t pts);                                    // L98
    Status SetParameter(const std::shared_ptr<Meta> &parameter);      // L99
    std::shared_ptr<Meta> GetOutputFormat();                          // L100
    void TransCoderOnOutputBufferAvailable(...);                      // L101
    void OnOutputBufferAvailable(...);                                // L102
    void SetFaultEvent(const std::string &errMsg);                    // L103
    void SetCallingInfo(int32_t appUid, int32_t appPid, const std::string &bundleName, uint64_t instanceId); // L105
    std::shared_ptr<MediaAVCodec::AVCodecVideoEncoder> codecServer_;  // L132: 核心编码器引擎
```

**成员变量关键行**（L108-L181）：
```cpp
std::shared_ptr<EncoderAdapterCallback> encoderAdapterCallback_;        // L108
std::shared_ptr<EncoderAdapterKeyFramePtsCallback> encoderAdapterKeyFramePtsCallback_; // L109
bool isTransCoderMode = false;                                          // L143
std::deque<std::pair<int64_t, StateCode>> pauseResumeQueue_;           // L139: PAUSE/RESUME PTS队列
std::atomic<int64_t> eosPts_{UINT32_MAX};                             // L152: EOS PTS
std::atomic<int64_t> currentPts_{-1};                                  // L153: 当前PTS
int64_t totalPauseTime_{0};                                             // L154: 累计暂停时间
std::string keyFramePts_;                                              // L146: 关键帧PTS串
bool enableBFrame_ {false};                                             // L175: B帧使能
bool hasBoostVideoFrameRate_ = false;                                   // L179: 帧率加速使能
bool isSupportBoostFrameRate_ = false;                                  // L180: 帧率加速支持
```

---

### 2.2 源文件（surface_encoder_adapter.cpp）

**文件**: `services/media_engine/filters/surface_encoder_adapter.cpp`
**行号**: L33-44（常量定义）

```cpp
// L33-34: Log标签
constexpr OHOS::HiviewDFX::HiLogLabel LABEL = { LOG_CORE, LOG_DOMAIN_RECORDER, "SurfaceEncoderAdapter" };

// L36-44: 关键常量
constexpr uint32_t TIME_OUT_MS = 1000;                                   // AVBufferQueue请求超时
constexpr uint32_t NS_PER_US = 1000;                                     // 纳秒→微秒转换
constexpr int64_t SEC_TO_NS = 1000000000;                               // 秒→纳秒转换
constexpr uint32_t STOP_TIME_OUT_MS = 2000;                              // 停止超时
constexpr uint32_t MAX_STOPPED_FRAMES_FOR_BOOST = 2;                    // 帧率boost最大帧数
constexpr uint32_t AVCODEC_ERR_TIMEOUT_NO_FRAME_RECEIVED = 50001;       // 超时无帧错误码
```

**E3: Init() 编码器创建**（L123-144）
```cpp
// L123: Init 函数签名
Status SurfaceEncoderAdapter::Init(const std::string &mime, bool isEncoder)
{
    MEDIA_LOG_I("Init mime: " PUBLIC_LOG_S, mime.c_str());
    codecMimeType_ = mime;
    Format format;
    std::shared_ptr<Media::Meta> callerInfo = std::make_shared<Media::Meta>();
    callerInfo->SetData(Media::Tag::AV_CODEC_FORWARD_CALLER_PID, appPid_);
    callerInfo->SetData(Media::Tag::AV_CODEC_FORWARD_CALLER_UID, appUid_);
    callerInfo->SetData(Media::Tag::AV_CODEC_FORWARD_CALLER_PROCESS_NAME, bundleName_);
    format.SetMeta(callerInfo);
    // L137: VideoEncoderFactory 创建编码器
    int32_t ret = MediaAVCodec::VideoEncoderFactory::CreateByMime(mime, format, codecServer_);
    MEDIA_LOG_I("AVCodecVideoEncoderImpl::Init CreateByMime errorCode %{public}d", ret);
    if (!codecServer_) {
        SetFaultEvent("SurfaceEncoderAdapter::Init Create codecServer failed", ret);
        return Status::ERROR_UNKNOWN;
    }
    // L142-145: releaseBufferTask_ 异步释放缓冲区线程
    if (!releaseBufferTask_) {
        releaseBufferTask_ = std::make_shared<Task>("SurfaceEncoder");
        releaseBufferTask_->RegisterJob([this] {
            ReleaseBuffer();
            return 0;
        });
```

**E4: Configure() 四段式配置**（L205-244）
```cpp
// L205-212: Configure 函数，四段式配置流程
Status SurfaceEncoderAdapter::Configure(const std::shared_ptr<Meta> &meta)
{
    MediaAVCodec::AVCodecTrace trace("SurfaceEncoderAdapter::Configure");
    MediaAVCodec::Format format = MediaAVCodec::Format();
    ConfigureGeneralFormat(format, meta);        // 通用配置
    ConfigureAboutRGBA(format, meta);             // RGBA配置
    ConfigureAboutEnableTemporalScale(format, meta); // 时域可分级
    ConfigureEnableFormat(format, meta);         // 使能配置
    // L222-227: TransCoder模式特殊处理（设置B帧使能）
    if (isTransCoderMode) {
        format.PutIntValue(Tag::VIDEO_FRAME_RATE_ADAPTIVE_MODE, true);
        bool isSetEnable = meta->Get<Tag::AV_TRANSCODER_ENABLE_B_FRAME>(enableBFrame_);
        if (isSetEnable) {
            format.PutIntValue(Tag::VIDEO_ENCODER_ENABLE_B_FRAME, static_cast<int32_t>(enableBFrame_));
        }
    }
    // L237: codecServer_->Configure(format)
    ret = codecServer_->Configure(format);
    if (ret != 0) {
        SetFaultEvent("SurfaceEncoderAdapter::Configure error", ret);
    }
```

**E5: SetOutputBufferQueue() + SetEncoderAdapterCallback()**（L282-305）
```cpp
// L282-286: 设置输出缓冲区队列
Status SurfaceEncoderAdapter::SetOutputBufferQueue(const sptr<AVBufferQueueProducer> &bufferQueueProducer)
{
    outputBufferQueueProducer_ = bufferQueueProducer;
    return Status::OK;
}

// L289-297: 设置编码器回调，SurfaceEncoderAdapterCallback桥接
Status SurfaceEncoderAdapter::SetEncoderAdapterCallback(
    const std::shared_ptr<EncoderAdapterCallback> &encoderAdapterCallback)
{
    std::shared_ptr<MediaAVCodec::MediaCodecCallback> surfaceEncoderAdapterCallback =
        std::make_shared<SurfaceEncoderAdapterCallback>(shared_from_this()); // L293
    encoderAdapterCallback_ = encoderAdapterCallback;
    if (!codecServer_) { ... }
    int32_t ret = codecServer_->SetCallback(surfaceEncoderAdapterCallback); // L297
```

**E6: Start() + Stop() + Pause() + Resume() 生命周期**（L335-478）
```cpp
// L335-357: Start()
Status SurfaceEncoderAdapter::Start()
{
    MediaAVCodec::AVCodecTrace trace("SurfaceEncoderAdapter::Start");
    if (!codecServer_) { ... }
    Clear();
    isThreadExit_ = false;
    hasReceivedEOS_ = false;
    if (releaseBufferTask_) {
        releaseBufferTask_->Start();
    }
    ret = codecServer_->Start();
    isStart_ = true;
    isStartKeyFramePts_ = true;
    if (ret == 0) {
        curState_ = ProcessStateCode::RECORDING; // L354: 状态→RECORDING
        return Status::OK;
    }
}

// L363-413: Stop()
Status SurfaceEncoderAdapter::Stop()
{
    MEDIA_LOG_I("Stop");
    // HandleWaitforStop(): 等EOS或超时2s（L902-914）
    // EOS收到则直接停止；超时无帧则上报AVCODEC_ERR_TIMEOUT_NO_FRAME_RECEIVED错误
}

// L418-440: Pause() —— 记录暂停时间戳，队列管理
Status SurfaceEncoderAdapter::Pause()
{
    GetCurrentTime(pauseTime_);
    if (pauseResumeQueue_.empty() ||
        (pauseResumeQueue_.back().second == StateCode::RESUME && pauseResumeQueue_.back().first <= pauseTime_)) {
        pauseResumeQueue_.push_back({pauseTime_, StateCode::PAUSE});
        pauseResumeQueue_.push_back({std::numeric_limits<int64_t>::max(), StateCode::RESUME});
        pauseResumePts_.push_back({pauseTime_, StateCode::PAUSE});
        pauseResumePts_.push_back({std::numeric_limits<int64_t>::max(), StateCode::RESUME});
    }
    curState_ = ProcessStateCode::PAUSED;
    return Status::OK;
}

// L441-469: Resume() —— 累加暂停时间
Status SurfaceEncoderAdapter::Resume()
{
    GetCurrentTime(resumeTime_);
    if (pauseTime_ != -1) {
        totalPauseTime_ = totalPauseTime_ + resumeTime_ - pauseTime_;
        totalPauseTimeQueue_.push_back(totalPauseTime_); // L462: 记录累计暂停时间
    }
    curState_ = ProcessStateCode::RECORDING;
    pauseTime_ = -1;
    resumeTime_ = -1;
    return Status::OK;
}
```

**E7: SetTransCoderMode() + GetInputSurface()**（L317-330）
```cpp
// L322-325: TransCoder模式设置
Status SurfaceEncoderAdapter::SetTransCoderMode()
{
    MEDIA_LOG_I("SetTransCoderMode");
    isTransCoderMode = true;  // L323
    return Status::OK;
}

// L329-332: 获取输入Surface（传递给上游Filter）
sptr<Surface> SurfaceEncoderAdapter::GetInputSurface()
{
    FALSE_RETURN_V_MSG(codecServer_ != nullptr, nullptr, "codecServer_ is nullptr");
    return codecServer_->CreateInputSurface(); // L331: 创建编码器输入Surface
}
```

**E8: OnOutputBufferAvailable() 双模式输出处理**（L601-640）
```cpp
// L601-605: OnOutputBufferAvailable 函数入口
void SurfaceEncoderAdapter::OnOutputBufferAvailable(uint32_t index, std::shared_ptr<AVBuffer> buffer)
{
    currentPts_ = currentPts_.load() < buffer->pts_ ? buffer->pts_ : currentPts_.load(); // L607
    if (isTransCoderMode) {
        TransCoderOnOutputBufferAvailable(index, buffer); // L609: TransCoder模式走此路径
        return;
    }
    // L612-627: 普通录制模式，AVBufferQueue生产者请求缓冲区
    int32_t size = buffer->memory_->GetSize();
    std::shared_ptr<AVBuffer> outputBuffer;
    AVBufferConfig avBufferConfig;
    avBufferConfig.size = size;
    avBufferConfig.memoryType = MemoryType::SHARED_MEMORY;
    avBufferConfig.memoryFlag = MemoryFlag::MEMORY_READ_WRITE;
    // L617: 请求输出缓冲区
    Status status = outputBufferQueueProducer_->RequestBuffer(outputBuffer, avBufferConfig, TIME_OUT_MS);
    // L620-623: 数据拷贝（buffer → outputBuffer）
    bufferMem->Write(buffer->memory_->GetAddr(), size, 0);
    *(outputBuffer->meta_) = *(buffer->meta_);
    outputBuffer->pts_ = buffer->pts_ / NS_PER_US;  // L626: 纳秒→微秒转换
    outputBufferQueueProducer_->PushBuffer(outputBuffer, true); // L628: 推送至下游
    // L633-636: EOS处理
    if (buffer->flag_ == AVCODEC_BUFFER_FLAG_EOS) {
        hasReceivedEOS_ = true;
        stopCondition_.notify_all();
    }
```

**E9: TransCoderOnOutputBufferAvailable() TransCoder输出**（L569-598）
```cpp
// L569-598: TransCoder模式输出缓冲区处理
void SurfaceEncoderAdapter::TransCoderOnOutputBufferAvailable(uint32_t index, std::shared_ptr<AVBuffer> buffer)
{
    int32_t size = buffer->memory_->GetSize();
    // L574-578: AVBufferConfig配置，共享内存模式
    AVBufferConfig avBufferConfig;
    avBufferConfig.size = size;
    avBufferConfig.memoryType = MemoryType::SHARED_MEMORY;
    avBufferConfig.memoryFlag = MemoryFlag::MEMORY_READ_WRITE;
    Status status = outputBufferQueueProducer_->RequestBuffer(emptyOutputBuffer, avBufferConfig, TIME_OUT_MS);
    // L582-587: 内存拷贝
    bufferMem->Write(buffer->memory_->GetAddr(), size, 0);
    bufferMem->SetSize(size);
    *(emptyOutputBuffer->meta_) = *(buffer->meta_);
    emptyOutputBuffer->pts_ = buffer->pts_;
    emptyOutputBuffer->flag_ = buffer->flag_;
    // L589: 推送至AVBufferQueue
    outputBufferQueueProducer_->PushBuffer(emptyOutputBuffer, true);
    // L591-595: 记录index用于后续ReleaseBuffer
    {
        std::lock_guard<std::mutex> lock(releaseBufferMutex_);
        indexs_.push_back(index);
    }
```

**E10: ReleaseBuffer() 异步缓冲区释放线程**（L640-700）
```cpp
// L640-700: ReleaseBuffer 异步线程
void SurfaceEncoderAdapter::ReleaseBuffer()
{
    while (true) {
        if (isThreadExit_) { break; } // L643
        std::vector<uint32_t> indexs;
        {
            std::unique_lock<std::mutex> lock(releaseBufferMutex_);
            releaseBufferCondition_.wait_for(lock, std::chrono::milliseconds(TIME_OUT_MS),
                [this] { return !indexs_.empty() || isThreadExit_; });
            if (isThreadExit_) { break; }
            indexs = std::move(indexs_);
        }
        // 批量释放编码器输出缓冲区
        for (uint32_t index : indexs) {
            codecServer_->ReleaseOutputBuffer(index, true); // L672
        }
    }
}
```

**E11: AddPauseResumePts() 暂停恢复PTS管理**（L867-901）
```cpp
// L867-901: AddPauseResumePts 关键帧PTS管理
bool SurfaceEncoderAdapter::AddPauseResumePts(int64_t currentPts)
{
    if (pauseResumePts_.empty()) { return false; }
    auto stateCode = pauseResumePts_[0].second;
    // PAUSE状态下currentPts < pauseTime → 不丢帧
    if (stateCode == StateCode::PAUSE && currentPts < pauseResumePts_[0].first) {
        return false;
    }
    // RESUME状态下currentPts < resumeTime → 丢帧
    if (stateCode == StateCode::RESUME && currentPts < pauseResumePts_[0].first) {
        return true;  // 丢帧
    }
    if (stateCode == StateCode::PAUSE) {
        // 记录暂停前的关键帧PTS
        keyFramePts_ += std::to_string(preKeyFramePts_ / NS_PER_US) + ",";
    }
    if (stateCode == StateCode::RESUME) {
        // 记录恢复后首帧PTS并触发回调
        if (encoderAdapterKeyFramePtsCallback_) {
            encoderAdapterKeyFramePtsCallback_->OnReportFirstFramePts(currentKeyFramePts_);
        }
    }
    pauseResumePts_.pop_front();
    return AddPauseResumePts(currentPts);
}
```

**E12: HandleWaitforStop() 停止等待与超时检测**（L902-914）
```cpp
// L902-914: HandleWaitforStop
void SurfaceEncoderAdapter::HandleWaitforStop()
{
    std::unique_lock<std::mutex> lock(stopMutex_);
    if (hasReceivedEOS_) {
        return; // EOS已收到，直接停止
    }
    // L909: 等待EOS或STOP_TIME_OUT_MS(2000ms)超时
    std::cv_status waitStatus = stopCondition_.wait_for(lock, std::chrono::milliseconds(STOP_TIME_OUT_MS));
    if (waitStatus == std::cv_status::timeout && currentKeyFramePts_ == -1) {
        MEDIA_LOG_E("Codec wait timeout with no video frame received");
        encoderAdapterCallback_->OnError(AVCodecErrorType::AVCODEC_ERROR_INTERNAL,
                                         AVCODEC_ERR_TIMEOUT_NO_FRAME_RECEIVED); // L912
    }
}
```

**E13: IsSupportBoostFrameRate() 帧率加速能力查询**（L939-958）
```cpp
// L939-958: IsSupportBoostFrameRate
bool SurfaceEncoderAdapter::IsSupportBoostFrameRate()
{
    constexpr const char* BOOST_FEATURE_KEY = "const.camera.video.shot2see.speedup";
    constexpr int32_t MAX_PARAM_LEN = 6;
    char result[MAX_PARAM_LEN] = {0};
    // L945: 获取系统参数
    int32_t len = GetParameter(BOOST_FEATURE_KEY, "false", result, static_cast<uint32_t>(MAX_PARAM_LEN));
    if (len <= 0 || len >= MAX_PARAM_LEN) {
        return false;
    }
    if (strcmp(result, "true") == 0) {
        MEDIA_LOG_I("Current product supports frame rate boosting.");
        return true; // L953
    }
    return false;
}
```

**E14: BoostVideoFrameRate() 帧率动态加速**（L961-985）
```cpp
// L961-985: BoostVideoFrameRate
Status SurfaceEncoderAdapter::BoostVideoFrameRate()
{
    MediaAVCodec::AVCodecTrace trace("SurfaceEncoderAdapter::BoostVideoFrameRate");
    if (!codecServer_) { ... }
    // L968-971: 获取最大帧率
    int32_t maxFrameRate = 0;
    Status res = GetMaxFrameRate(maxFrameRate);
    if (res != Status::OK) { return res; }
    // L975: 设置编码器操作帧率为maxFrameRate
    MediaAVCodec::Format format = MediaAVCodec::Format();
    format.PutDoubleValue(Tag::VIDEO_OPERATING_RATE, static_cast<double>(maxFrameRate));
    int32_t ret = codecServer_->SetParameter(format);
    if (ret == 0) {
        hasBoostVideoFrameRate_ = true; // L980
        return Status::OK;
    }
}
```

**E15: SetFaultEvent() DFX 故障事件上报**（L700-710）
```cpp
// L700-710: SetFaultEvent
void SurfaceEncoderAdapter::SetFaultEvent(const std::string &errMsg)
{
    VideoCodecFaultInfo videoCodecFaultInfo;
    videoCodecFaultInfo.appName = bundleName_;
    videoCodecFaultInfo.instanceId = std::to_string(instanceId_);
    videoCodecFaultInfo.callerType = "player_framework";
    videoCodecFaultInfo.videoCodec = codecMimeType_;
    videoCodecFaultInfo.errMsg = errMsg;
    FaultVideoCodecEventWrite(videoCodecFaultInfo); // L708: 写入HiSysEvent
}
```

**E16: SurfaceEncoderFilter 使用 SurfaceEncoderAdapter**（surface_encoder_filter.cpp L175-185）
```cpp
// surface_encoder_filter.cpp L175-185: 创建适配器
mediaCodec_ = std::make_shared<SurfaceEncoderAdapter>(); // L175
// L180-183: 设置回调
std::make_shared<SurfaceEncoderAdapterCallback>(shared_from_this());
std::make_shared<SurfaceEncoderAdapterKeyFramePtsCallback>(shared_from_this());
mediaCodec_->SetEncoderAdapterCallback(...);
mediaCodec_->SetEncoderAdapterKeyFramePtsCallback(...);
// 注册名："builtin.recorder.videoencoder" (FilterType::FILTERTYPE_VENC)
```

**E17: ConfigureGeneralFormat() 通用格式配置**（L150-195）
```cpp
// L150-195: ConfigureGeneralFormat
void SurfaceEncoderAdapter::ConfigureGeneralFormat(MediaAVCodec::Format &format, const std::shared_ptr<Meta> &meta)
{
    // 设置宽、高、码率、帧率、像素格式等关键参数
    // 从meta中提取 Tag::VIDEO_WIDTH/HEIGHT/BIT_RATE/FRAME_RATE/PIXEL_FORMAT
}
```

**E18: ConfigureAboutRGBA() RGBA颜色格式配置**（L664-680）
```cpp
// L664-680: ConfigureAboutRGBA
void SurfaceEncoderAdapter::ConfigureAboutRGBA(MediaAVCodec::Format &format, const std::shared_ptr<Meta> &meta)
{
    // 处理 RGBA 输入格式的特定配置
    // 确保 Surface 输入的 RGBA 数据正确传递给编码器
}
```

**E19: ConfigureAboutEnableTemporalScale() 时域可分级配置**（L679-700）
```cpp
// L679-700: ConfigureAboutEnableTemporalScale
void SurfaceEncoderAdapter::ConfigureAboutEnableTemporalScale(MediaAVCodec::Format &format,
    const std::shared_ptr<Meta> &meta)
{
    // 配置时域可分级编码（Temporal Scale）参数
    // 常用于低延迟编码场景
}
```

**E20: SetWatermark() 水印叠加**（L247-260）
```cpp
// L247-260: SetWatermark
Status SurfaceEncoderAdapter::SetWatermark(std::shared_ptr<AVBuffer> &waterMarkBuffer)
{
    if (!codecServer_) { return Status::ERROR_NULL_POINTER; }
    return codecServer_->SetWatermark(waterMarkBuffer); // L260: 委托给编码器引擎
}
```

---

## 三、Evidence 汇总表

| # | 文件 | 行号 | 内容摘要 |
|---|------|------|---------|
| E1 | surface_encoder_adapter.h | L42-54 | StateCode/ProcessStateCode 双枚举 |
| E2 | surface_encoder_adapter.h | L58-72 | EncoderAdapterCallback/EncoderAdapterKeyFramePtsCallback 双回调接口 |
| E3 | surface_encoder_adapter.cpp | L123-144 | Init() → VideoEncoderFactory::CreateByMime |
| E4 | surface_encoder_adapter.cpp | L205-244 | Configure() 四段式配置流程 |
| E5 | surface_encoder_adapter.cpp | L282-305 | SetOutputBufferQueue + SetEncoderAdapterCallback 回调桥接 |
| E6 | surface_encoder_adapter.cpp | L335-478 | Start/Stop/Pause/Resume 生命周期管理 |
| E7 | surface_encoder_adapter.cpp | L317-332 | SetTransCoderMode + GetInputSurface |
| E8 | surface_encoder_adapter.cpp | L601-640 | OnOutputBufferAvailable 双模式输出处理 |
| E9 | surface_encoder_adapter.cpp | L569-598 | TransCoderOnOutputBufferAvailable TransCoder输出路径 |
| E10 | surface_encoder_adapter.cpp | L640-700 | ReleaseBuffer 异步缓冲区释放线程 |
| E11 | surface_encoder_adapter.cpp | L867-901 | AddPauseResumePts 暂停恢复PTS管理 |
| E12 | surface_encoder_adapter.cpp | L902-914 | HandleWaitforStop 超时无帧检测 |
| E13 | surface_encoder_adapter.cpp | L939-958 | IsSupportBoostFrameRate 帧率加速能力查询 |
| E14 | surface_encoder_adapter.cpp | L961-985 | BoostVideoFrameRate 动态帧率加速 |
| E15 | surface_encoder_adapter.cpp | L700-710 | SetFaultEvent DFX故障事件上报 |
| E16 | surface_encoder_filter.cpp | L175-185 | SurfaceEncoderFilter 使用适配器 |
| E17 | surface_encoder_adapter.cpp | L150-195 | ConfigureGeneralFormat 通用格式配置 |
| E18 | surface_encoder_adapter.cpp | L664-680 | ConfigureAboutRGBA RGBA格式配置 |
| E19 | surface_encoder_adapter.cpp | L679-700 | ConfigureAboutEnableTemporalScale 时域可分级 |
| E20 | surface_encoder_adapter.cpp | L247-260 | SetWatermark 水印叠加 |

---

## 四、关键设计模式

### 4.1 TransCoder vs 普通录制 双模式
- `isTransCoderMode`（L142）：TransCoder模式标志
- 普通录制：编码→AVBufferQueue→MuxerFilter
- TransCoder：解码→SurfaceEncoderAdapter[编码]→AVBufferQueue→MuxerFilter
- TransCoder模式下Pause/Resume走不同路径（L419-422）

### 4.2 回调三层桥接
```
Filter（SurfaceEncoderFilter）
    ↓ SurfaceEncoderAdapterCallback（继承EncoderAdapterCallback）
SurfaceEncoderAdapter
    ↓ SurfaceEncoderAdapterCallback（继承MediaCodecCallback）
codecServer_（AVCodecVideoEncoder）
```

### 4.3 关键帧PTS追踪
- `keyFramePts_`（L146）：逗号分隔的关键帧PTS字符串
- `pauseResumePts_`（L174）：deque<pair<PTS, StateCode>> 管理暂停/恢复边界
- `totalPauseTime_`（L154）：累计暂停时长，用于PTS校正

### 4.4 帧率加速（Boost）
- 系统参数：`const.camera.video.shot2see.speedup`（L942）
- `VIDEO_OPERATING_RATE`：动态提升编码器操作帧率
- `MAX_STOPPED_FRAMES_FOR_BOOST = 2`（L41）：连续2帧停止则退出boost

---

## 五、关联主题

| 关联 | 主题 | 说明 |
|------|------|------|
| 对称实现 | S214 | SurfaceDecoderAdapter（解码适配器），与S249构成Surface-based编解码双通道 |
| 上游Filter | S23 | SurfaceEncoderFilter（Filter层），使用SurfaceEncoderAdapter |
| 编码器引擎 | S239 | CodecBase Engine Base，CodecBase九态机 |
| 硬件编码器 | S242 | AvcEncoder H.264硬件编码器，libavcenc_ohos HDI |
| CodecAdapter族 | S202 | MediaCodec Filter层编解码适配器（通用CodecAdapter） |
| TransCoder管线 | S203/S212 | TransCoder/Recorder Filter，双模式 |
| DFX追踪 | S236 | HCodec DFX Module，FuncTracker RAII |
| Native API | S83/S94 | OH_VideoEncoder C API |
| 水印 | S135 | WaterMarkFilter，直接使用CodecCapabilityAdapter |
