# MEM-ARCH-AVCODEC-S149: Transcoder Pipeline 架构——视频转码 Encode→Decode 桥接与 Filter 链路

## 1. 概述

**S149 主题**：Transcoder Pipeline 架构——视频转码 Encode→Decode 桥接与 Filter 链路

**scope**: AVCodec, TransCoder, Pipeline, FilterChain, Encode, Decode, SurfaceEncoderAdapter, MuxerFilter, VideoResizeFilter, AudioEncoderFilter

**关联场景**: 新需求开发 / 问题定位 / 转码场景接入

**状态**: 🚧 pending_approval

---

## 2. TransCoder 模式核心概念

TransCoder 模式是 AVCodec 录音/录制管线的一个特殊分支，用于**转码场景**（Encode→Decode桥接）。与普通录制管线的核心区别在于：

| 维度 | 录制模式（Recorder） | 转码模式（TransCoder） |
|------|---------------------|----------------------|
| 数据流方向 | 摄像头/麦克风 → Encoder → Muxer | Decoder → (ResizeFilter) → Encoder → Muxer |
| 输入源 | 实时采集（Camera/Mic） | 已编码的媒体文件/流 |
| 关键标志 | `isTransCoderMode = false` | `isTransCoderMode = true` |
| PTS 起点 | 相对 PTS（从0开始） | `transcoderStartPts_`（偏移补偿） |
| B-Frame 支持 | 受限 | 由 `AV_TRANSCODER_ENABLE_B_FRAME` 控制 |
| 帧率自适应 | VIDEO_FRAME_RATE_ADAPTIVE_MODE | 强制启用 |
| 错误回调 | 正常上报 | 首次错误吞掉（`transCoderErrorCbOnce_`） |

---

## 3. TransCoder 相关类与文件

| 类/文件 | 路径 | 行数 | 职责 |
|---------|------|------|------|
| SurfaceEncoderAdapter | services/media_engine/filters/surface_encoder_adapter.cpp/.h | 1037/183 | 视频编码器适配层，TransCoderMode 核心控制点 |
| SurfaceEncoderFilter | services/media_engine/filters/surface_encoder_filter.cpp/.h | 478/~200 | Filter 层封装，持有 SurfaceEncoderAdapter |
| AudioEncoderFilter | services/media_engine/filters/audio_encoder_filter.cpp/.h | 381/~200 | 音频编码过滤器，支持 TransCoderMode |
| MuxerFilter | services/media_engine/filters/muxer_filter.cpp/.h | ~480/~150 | 封装过滤器，OnTransCoderBufferFilled 处理转码输入 |
| VideoResizeFilter | services/media_engine/filters/video_resize_filter.cpp/.h | 566/155 | VPE 转码增强过滤器，"builtin.transcoder.videoresize" 注册 |
| MediaDemuxer | services/media_engine/modules/demuxer/media_demuxer.cpp/.h | 6012/619 | 源解封装，`transcoderStartPts_` PTS 偏移补偿 |

---

## 4. TransCoderMode 标志体系

### 4.1 标志分布

```
SurfaceEncoderAdapter          isTransCoderMode        (L142: bool isTransCoderMode = false;)
    └── SurfaceEncoderFilter    isTranscoderMode_       (Filter 层包装)
        └── AudioEncoderFilter  isTranscoderMode_       (L227: isTranscoderMode_ = true;)
            └── MuxerFilter     isTransCoderMode        (L113: isTransCoderMode = true;)
                └── MediaDemuxer transcoderStartPts_    (L553: int64_t transcoderStartPts_ {HST_TIME_NONE})
```

### 4.2 启用链路（设置顺序）

1. **MuxerFilter::SetTransCoderMode()** (muxer_filter.cpp:110-113)
   ```cpp
   Status MuxerFilter::SetTransCoderMode()
   {
       MEDIA_LOG_I("SetTransCoderMode");
       isTransCoderMode = true;
       return Status::OK;
   }
   ```

2. **SurfaceEncoderFilter::SetTransCoderMode()** (surface_encoder_filter.cpp:241-245)
   ```cpp
   Status SurfaceEncoderFilter::SetTransCoderMode()
   {
       MEDIA_LOG_I("SetTransCoderMode");
       isTranscoderMode_ = true;
       mediaCodec_->SetTransCoderMode();  // 透传给 MediaCodec
       return Status::OK;
   }
   ```

3. **AudioEncoderFilter** (audio_encoder_filter.cpp:227)
   ```cpp
   isTranscoderMode_ = true;  // 在 Configure/OnLinked 时触发
   ```

4. **SurfaceEncoderAdapter::SetTransCoderMode()** (surface_encoder_adapter.cpp:322-325)
   ```cpp
   Status SurfaceEncoderAdapter::SetTransCoderMode()
   {
       MEDIA_LOG_I("SetTransCoderMode");
       isTransCoderMode = true;
       return Status::OK;
   }
   ```

---

## 5. SurfaceEncoderAdapter 核心实现

### 5.1 类结构（surface_encoder_adapter.h:183行）

```cpp
class SurfaceEncoderAdapter : public std::enable_shared_from_this<SurfaceEncoderAdapter> {
public:
    Status SetTransCoderMode();                    // L322
    bool GetIsTransCoderMode();                   // L1033
    void TransCoderOnOutputBufferAvailable(uint32_t index, std::shared_ptr<AVBuffer> buffer); // L569
    void OnOutputBufferAvailable(uint32_t index, std::shared_ptr<AVBuffer> buffer);          // L591

private:
    bool isTransCoderMode = false;                // L142
    bool transCoderErrorCbOnce_ = false;          // L54,57: TransCoder 错误吞掉机制
    std::shared_ptr<MediaAVCodec::AVCodecVideoEncoder> codecServer_;  // 底层编码器
    sptr<AVBufferQueueProducer> outputBufferQueueProducer_;          // 输出队列
};
```

### 5.2 TransCoder 模式配置差异（surface_encoder_adapter.cpp:219-237）

```cpp
Status SurfaceEncoderAdapter::Configure(const std::shared_ptr<Meta> &meta)
{
    // 非 TransCoder 模式：设置丢帧回调
    if (!isTransCoderMode) {
        auto droppedFramesCallback = std::make_shared<DroppedFramesCallback>(shared_from_this());
        ret = codecServer_->SetCallback(droppedFramesCallback);  // L224-231
    }
    // TransCoder 模式：启用帧率自适应 + B-Frame 控制
    if (isTransCoderMode) {
        format.PutIntValue(Tag::VIDEO_FRAME_RATE_ADAPTIVE_MODE, true);  // L229
        bool isSetEnable = meta->Get<Tag::AV_TRANSCODER_ENABLE_B_FRAME>(enableBFrame_);
        if (isSetEnable) {
            format.PutIntValue(Tag::VIDEO_ENCODER_ENABLE_B_FRAME, static_cast<int32_t>(enableBFrame_)); // L232-234
        }
    }
    // 非 TransCoder 模式：B-Frame 按配置
    if (!isTransCoderMode) {
        format.PutIntValue(Tag::VIDEO_ENCODER_ENABLE_B_FRAME, enableBFrame_); // L237
    }
}
```

### 5.3 TransCoder 错误吞掉机制（surface_encoder_adapter.cpp:54-57）

```cpp
class SurfaceEncoderAdapterCallback : public MediaAVCodec::MediaCodecCallback {
    void OnError(MediaAVCodec::AVCodecErrorType errorType, int32_t errorCode) override {
        if (auto surfaceEncoderAdapter = surfaceEncoderAdapter_.lock()) {
            // TransCoder 模式：首次错误吞掉（不回调给上层）
            if (surfaceEncoderAdapter->GetIsTransCoderMode() && transCoderErrorCbOnce_) {  // L54
                return;  // 第二次及以后才真正报错
            }
            if (surfaceEncoderAdapter->GetIsTransCoderMode()) {
                transCoderErrorCbOnce_ = true;  // L57: 标记已吞掉一次
            }
            surfaceEncoderAdapter->encoderAdapterCallback_->OnError(errorType, errorCode);
        }
    }
};
```

### 5.4 TransCoder 输出缓冲区处理（surface_encoder_adapter.cpp:569-607）

```cpp
// 专门处理 TransCoder 模式输出的回调
void SurfaceEncoderAdapter::TransCoderOnOutputBufferAvailable(uint32_t index, std::shared_ptr<AVBuffer> buffer)
{
    int32_t size = buffer->memory_->GetSize();
    std::shared_ptr<AVBuffer> emptyOutputBuffer;
    AVBufferConfig avBufferConfig;
    avBufferConfig.size = size;
    avBufferConfig.memoryType = MemoryType::SHARED_MEMORY;
    avBufferConfig.memoryFlag = MemoryFlag::MEMORY_READ_WRITE;
    // 从 outputBufferQueueProducer_ 请求空 buffer
    Status status = outputBufferQueueProducer_->RequestBuffer(emptyOutputBuffer, avBufferConfig, TIME_OUT_MS); // L575
    if (status != Status::OK) {
        MEDIA_LOG_I("RequestBuffer fail.");
        return;
    }
    // 拷贝编码后的数据到输出队列
    bufferMem->Write(buffer->memory_->GetAddr(), size, 0);  // L587
    bufferMem->SetSize(size);
    *(emptyOutputBuffer->meta_) = *(buffer->meta_);
    emptyOutputBuffer->pts_ = buffer->pts_;
    emptyOutputBuffer->flag_ = buffer->flag_;
    outputBufferQueueProducer_->PushBuffer(emptyOutputBuffer, true);  // L589: 推入下游
    // 归还编码器输入 buffer
    {
        std::lock_guard<std::mutex> lock(releaseBufferMutex_);
        indexs_.push_back(index);  // L591
    }
    releaseBufferCondition_.notify_all();
}

// 统一输出回调：TransCoder vs 普通模式分叉
void SurfaceEncoderAdapter::OnOutputBufferAvailable(uint32_t index, std::shared_ptr<AVBuffer> buffer)
{
    currentPts_ = currentPts_.load() < buffer->pts_? buffer->pts_ : currentPts_.load();
    MediaAVCodec::AVCodecTrace trace("SurfaceEncoderAdapter::OnOutputBufferAvailable");
    if (isTransCoderMode) {
        TransCoderOnOutputBufferAvailable(index, buffer);  // L606-607: TransCoder 走专用路径
        return;
    }
    // 普通模式：PTS 单位转换 ns→μs
    outputBuffer->pts_ = buffer->pts_ / NS_PER_US;  // L619: 普通模式除以1000
    // ... 普通输出处理
}
```

### 5.5 TransCoder 模式 Pause/Stop 等待逻辑（surface_encoder_adapter.cpp:375-422）

```cpp
Status SurfaceEncoderAdapter::Stop()
{
    // PAUSED 状态下，非 TransCoder 模式需要等待最后一帧
    if (curState_ == ProcessStateCode::PAUSED && !isTransCoderMode) {  // L375
        stopTime_ = pauseTime_;
        if (currentKeyFramePts_ <= pauseTime_ - (SEC_TO_NS / videoFrameRate_)) {
            MEDIA_LOG_D("paused state -> stop, wait for stop.");
            HandleWaitforStop();  // 等待最后一帧
        }
        AddStopPts();
    }
    // RECORDING 状态下，非 TransCoder 模式需要等待停止帧
    if (curState_ == ProcessStateCode::RECORDING && !isTransCoderMode) {  // L386
        MEDIA_LOG_D("recording state -> stop, wait for stop.");
        HandleWaitforStop();
        AddStopPts();
    }
    // TransCoder 模式：直接停止，不等待
    if (isTransCoderMode) {  // L422
        MEDIA_LOG_I("isTransCoderMode stop directly");
    }
}
```

### 5.6 TransCoder 模式 PTS 映射（surface_encoder_adapter.cpp:729）

```cpp
void SurfaceEncoderAdapter::OnInputParameterWithAttrAvailable(..., std::shared_ptr<Format> &parameter)
{
    if (isTransCoderMode) {
        HandleTranscoderMode(index, parameter);  // L729: TransCoder 专用 PTS 处理
        return;
    }
    // 普通模式：丢帧检测 + PTS 映射
    std::lock_guard<std::mutex> lock(checkFramesMutex_);
    CheckAndAdjustFrameRate();
    int64_t currentPts = 0;
    attribute->GetLongValue(Tag::MEDIA_TIME_STAMP, currentPts);
    bool isDroppedFrames = CheckFrames(currentPts, checkFramesPauseTime_);
    // PTS 映射：adjustPts = currentPts - totalPauseTimeQueue_[0] + checkFramesPauseTime_
    std::lock_guard<std::mutex> mappingLock(mappingPtsMutex_);
    int64_t adjustPts = currentPts - totalPauseTimeQueue_[0] + checkFramesPauseTime_;
}
```

---

## 6. AudioEncoderFilter TransCoder 支持

### 6.1 TransCoder 模式配置（audio_encoder_filter.cpp:290-338）

```cpp
Status AudioEncoderFilter::OnLinked(StreamType inType, const std::shared_ptr<Meta> &meta,
    const std::shared_ptr<FilterLinkCallback> &callback)
{
    onLinkedResultCallback_ = callback;
    if (isTranscoderMode_) {  // L290
        transcoderMeta_ = meta;  // L291: 缓存转码元数据
        return UpdateParameterToConfigure(meta);  // 立即用下游 meta 配置编码器
    }
    return Status::OK;
}

Status AudioEncoderFilter::OnLinkedResult(const sptr<AVBufferQueueProducer> &outputBufferQueue,
    std::shared_ptr<Meta> &meta)
{
    mediaCodec_->SetOutputBufferQueue(outputBufferQueue);
    mediaCodec_->Prepare();
    if (isTranscoderMode_) {  // L337
        // TransCoder 模式：使用缓存的 transcoderMeta_ 作为 LinkNext 的 meta
        onLinkedResultCallback_->OnLinkedResult(mediaCodec_->GetInputBufferQueue(), transcoderMeta_); // L338
        return;
    }
    onLinkedResultCallback_->OnLinkedResult(mediaCodec_->GetInputBufferQueue(), meta);  // 普通模式
}

Status AudioEncoderFilter::UpdateParameterToConfigure(const std::shared_ptr<Meta> &meta)
{
    // TransCoder 模式：使用下游传来的 sampleFormat 更新 configureParameter_
    Plugins::AudioSampleFormat dstSampleFormat = Plugins::AudioSampleFormat::INVALID_WIDTH;
    Plugins::AudioSampleFormat oriSampleFormat = Plugins::AudioSampleFormat::INVALID_WIDTH;
    if (meta != nullptr && configureParameter_ != nullptr &&
        meta->GetData(Tag::AUDIO_SAMPLE_FORMAT, dstSampleFormat)) {
        configureParameter_->GetData(Tag::AUDIO_SAMPLE_FORMAT, oriSampleFormat);
        configureParameter_->SetData(Tag::AUDIO_SAMPLE_FORMAT, dstSampleFormat);  // L306: 覆盖为下游格式
    }
    FALSE_RETURN_V(mediaCodec_ != nullptr, Status::ERROR_NULL_POINTER);
    int32_t ret = mediaCodec_->Configure(configureParameter_);  // L310: 用更新后的参数配置
    return Status::OK;
}
```

---

## 7. MuxerFilter TransCoder 处理

### 7.1 OnTransCoderBufferFilled（muxer_filter.cpp:366-407）

```cpp
void MuxerFilter::OnTransCoderBufferFilled(std::shared_ptr<AVBuffer> &inputBuffer, int32_t trackIndex,
    StreamType streamType, sptr<AVBufferQueueProducer> inputBufferQueue)
{
    MEDIA_LOG_D("OnTransCoderBufferFilled");
    bool isCompleted = false;
    // EOS 计数
    if ((inputBuffer->flag_ & BUFFER_IS_EOS) == 1) {  // L370
        std::unique_lock<std::mutex> lock(eosMutex_);
        eosCount_++;
        if (streamType == StreamType::STREAMTYPE_ENCODED_VIDEO) {
            videoIsEos = true;
        } else if (streamType == StreamType::STREAMTYPE_ENCODED_AUDIO) {
            audioIsEos = true;
        }
        isCompleted = (eosCount_ == preFilterCount_) || (videoIsEos && audioIsEos);  // L379-380: 双轨 EOS
    }
    // 音频处理：等待视频 PTS 追上（音视频同步）
    if (streamType == StreamType::STREAMTYPE_ENCODED_AUDIO) {
        if (videoCodecMimeType_.empty()) {
            inputBufferQueue->ReturnBuffer(inputBuffer, true);  // 无视频则直接通过
        } else if (inputBuffer->pts_ <= lastVideoPts_ || videoIsEos) {
            inputBufferQueue->ReturnBuffer(inputBuffer, true);  // 视频已追上则通过
        } else {
            // 视频 PTS 落后，等待
            std::unique_lock<std::mutex> lock(stopMutex_);
            stopCondition_.wait_for(lock, std::chrono::milliseconds(US_TO_MS));  // L396: 等待
            inputBufferQueue->ReturnBuffer(inputBuffer, true);
        }
    } else if (streamType == StreamType::STREAMTYPE_ENCODED_VIDEO) {
        if (!videoIsEos) {
            lastVideoPts_ = inputBuffer->pts_;  // L401: 更新视频 PTS
        }
        std::unique_lock<std::mutex> lock(stopMutex_);
        stopCondition_.notify_all();  // L403: 唤醒音频等待线程
        inputBufferQueue->ReturnBuffer(inputBuffer, true);
    }
    // 全部 EOS 则触发完成
    if (eventReceiver_ != nullptr && isCompleted) {
        HandleTransCoderComplete();  // L407: 触发完成
    }
}
```

### 7.2 HandleTransCoderComplete（muxer_filter.cpp:411-421）

```cpp
void MuxerFilter::HandleTransCoderComplete()
{
    MEDIA_LOG_I("HandleTransCoderComplete");
    if (isReachMaxDuration_.load()) {
        return;
    }
    // 非 TransCoder 模式：正常结束
    if (!isTransCoderMode) {
        eventReceiver_->OnEvent({"muxer_filter", EventType::EVENT_COMPLETE, Status::OK});
        return;
    }
    // TransCoder 模式：异步停止所有 preFilter
    std::shared_ptr<AVBuffer> eosBuffer = nullptr;
    for (size_t i = 0; i < preFilterCount_; ++i) {
        filterCallback_->OnCallback(shared_from_this(), FilterCallBackCommand::SEND_EOS, ...);  // L419
    }
}
```

---

## 8. VideoResizeFilter 转码增强过滤器

### 8.1 注册与类型（video_resize_filter.cpp:37-40）

```cpp
static AutoRegisterFilter<VideoResizeFilter> g_registerVideoResizeFilter("builtin.transcoder.videoresize",
    FilterType::FILTERTYPE_VIDRESIZE,
    [](const std::string& name, const FilterType type) {
        return std::make_shared<VideoResizeFilter>(name, FilterType::FILTERTYPE_VIDRESIZE);
    });
```

### 8.2 VPE DetailEnhancer 集成（video_resize_filter.cpp:83-141）

```cpp
class ResizeDetailEnhancerVideoCallback : public DetailEnhancerVideoCallback {
    void OnError(int32_t errorType, int32_t errorCode) override {
        if (auto resizeFilter = videoResizeFilter_.lock()) {
            resizeFilter->OnError(static_cast<MediaAVCodec::AVCodecErrorType>(errorType), errorCode);
        }
    }
    void OnState(int32_t state) override { /* VPE 状态回调 */ }
    void OnOutputBufferAvailable(std::shared_ptr<AVBuffer> buffer) override {
        if (auto resizeFilter = videoResizeFilter_.lock()) {
            resizeFilter->OnOutputBufferAvailable(buffer);
        }
    }
};

// DoPrepare: 请求上游 Filter 提供 Surface
Status VideoResizeFilter::DoPrepare()
{
    switch (filterType_) {
        case FilterType::FILTERTYPE_VIDRESIZE:
            filterCallback_->OnCallback(shared_from_this(), FilterCallBackCommand::NEXT_FILTER_NEEDED,
                StreamType::STREAMTYPE_RAW_VIDEO);  // L252-254: 请求 Surface 输入
            break;
    }
    return Status::OK;
}

// DoStart: 启动 VPE DetailEnhancer
Status VideoResizeFilter::DoStart()
{
    isThreadExit_ = false;
    if (releaseBufferTask_) {
        releaseBufferTask_->Start();
    }
#ifdef USE_VIDEO_PROCESSING_ENGINE
    if (videoEnhancer_ == nullptr) {
        MEDIA_LOG_E("DoStart videoEnhancer is null");
        return Status::ERROR_NULL_POINTER;
    }
    int32_t ret = videoEnhancer_->Start();  // L279: 启动 VPE
    if (ret != 0) {
        MEDIA_LOG_E("videoEnhancer Start fail");
        if (eventReceiver_) {
            eventReceiver_->OnEvent({"video_resize_filter", EventType::EVENT_ERROR, MSERR_UNKNOWN});
        }
        return Status::ERROR_UNKNOWN;
    }
    return Status::OK;
#else
    MEDIA_LOG_E("no VPE module");
    return Status::ERROR_UNKNOWN;
#endif
}
```

---

## 9. MediaDemuxer PTS 偏移补偿

### 9.1 transcoderStartPts_ 记录（media_demuxer.h:553）

```cpp
class MediaDemuxer {
    int64_t transcoderStartPts_ {HST_TIME_NONE};  // 转码起始 PTS
};
```

### 9.2 PTS 补偿逻辑（media_demuxer.cpp:3338-3339, media_demuxer_pts_functions.cpp:164-171）

```cpp
// media_demuxer.cpp:3338-3339
if (transcoderStartPts_ > 0 && outputBuffer != nullptr) {
    outputBuffer->pts_ -= transcoderStartPts_;  // 减去转码偏移，得到相对 PTS
}

// media_demuxer_pts_functions.cpp:164-171
if (transcoderStartPts_ == HST_TIME_NONE || startTime < transcoderStartPts_) {
    transcoderStartPts_ = startTime;  // 首次更新转码起始 PTS
}
```

---

## 10. TransCoder Pipeline 完整拓扑

```
数据流拓扑（TransCoder 模式）：

MediaDemuxer (MediaDemuxer)
  │ pts -= transcoderStartPts_ (media_demuxer.cpp:3338-3339)
  ▼
DecoderSurfaceFilter / SurfaceDecoderFilter (FILTERTYPE_VDEC)
  │ 解码已加密/编码的媒体流
  ▼
SurfaceDecoderAdapter
  │ 输出 Surface
  ▼
VideoResizeFilter (FILTERTYPE_VIDRESIZE, "builtin.transcoder.videoresize")
  │ VPE DetailEnhancer 视频处理（可选）
  │ GetInputSurface() / SetOutputSurface()
  ▼
SurfaceEncoderFilter (FILTERTYPE_VENC, "builtin.recorder.videoencoder")
  │ SurfaceEncoderAdapter.isTransCoderMode = true
  │ VideoEncoderConfig: VIDEO_FRAME_RATE_ADAPTIVE_MODE=true, B-Frame可控
  ▼
MuxerFilter
  │ isTransCoderMode = true
  │ OnTransCoderBufferFilled: 双轨EOS计数, 音视频PTS同步
  ▼
MediaMuxer
  │ Track管理, AVBufferQueue异步写入
  ▼
输出文件 (MP4/MKV/FLV)
```

---

## 11. 关键差异总结

| 功能 | 录制模式 | TransCoder 模式 |
|------|---------|----------------|
| 输入源 | Camera/Mic Surface | 解码后的 Surface |
| 丢帧回调 | 启用 DroppedFramesCallback | 禁用（isTransCoderMode 跳过） |
| 错误回调 | 正常上报 | 首次吞掉（transCoderErrorCbOnce_） |
| 帧率自适应 | 按配置 | 强制启用 VIDEO_FRAME_RATE_ADAPTIVE_MODE |
| B-Frame | 按配置 | 由 AV_TRANSCODER_ENABLE_B_FRAME 控制 |
| PTS 单位 | ns（原始） | ns（编码输出）→除以1000→μs（普通模式） |
| Stop 等待 | 等待最后一帧 HandleWaitforStop | 直接停止（不等待） |
| Pause 行为 | HandleWaitforStop 等待 | 不等待 |
| PTS 起点 | 相对（从0开始） | transcoderStartPts_ 偏移补偿 |
| 音频同步 | 无（实时采集） | OnTransCoderBufferFilled 等待视频 PTS |

---

## 12. 关联主题

- **S23** SurfaceEncoderAdapter 视频编码器适配器（Filter→Adapter→Encoder 三层）
- **S36** VideoEncoderFilter 视频编码过滤器（FILTERTYPE_VENC）
- **S34** MuxerFilter 封装过滤器（OnTransCoderBufferFilled）
- **S12** VideoResizeFilter 转码增强过滤器（FILTERTYPE_VIDRESIZE）
- **S46** DecoderSurfaceFilter 视频解码过滤器（FILTERTYPE_VDEC，TransCoder 上游）
- **S45** SurfaceDecoderFilter 视频解码过滤器（Surface 模式，TransCoder 上游）
- **S75** MediaDemuxer 六组件架构（transcoderStartPts_ PTS 补偿）
- **S124** 录音Pipeline音频数据源与采集过滤器链（AudioEncoderFilter isTranscoderMode_）
- **S41** DemuxerFilter 解封装过滤器（TransCoder 数据源入口）

---

## 13. Evidence 行号索引

| 文件 | 行号 | 关键代码 |
|------|------|---------|
| surface_encoder_adapter.cpp | 54-57 | TransCoderErrorCbOnce_ 错误吞掉 |
| surface_encoder_adapter.cpp | 88 | SetTransCoderMode() 声明 |
| surface_encoder_adapter.cpp | 110 | GetIsTransCoderMode() 声明 |
| surface_encoder_adapter.cpp | 142 | `bool isTransCoderMode = false;` |
| surface_encoder_adapter.cpp | 219-237 | Configure 中 TransCoder vs 普通配置差异 |
| surface_encoder_adapter.cpp | 322-325 | SetTransCoderMode() 实现 |
| surface_encoder_adapter.cpp | 375, 386 | Stop 中 `!isTransCoderMode` 等待逻辑 |
| surface_encoder_adapter.cpp | 422, 445 | `isTransCoderMode` 分支 |
| surface_encoder_adapter.cpp | 569-589 | TransCoderOnOutputBufferAvailable 实现 |
| surface_encoder_adapter.cpp | 591-607 | OnOutputBufferAvailable 分叉 |
| surface_encoder_adapter.cpp | 729 | HandleTranscoderMode 调用 |
| surface_encoder_adapter.cpp | 1033-1035 | GetIsTransCoderMode() 实现 |
| surface_encoder_filter.cpp | 241-245 | SetTransCoderMode() 透传 |
| surface_encoder_filter.cpp | 261-265 | DoPrepare 中 TransCoderMode 请求 NEXT_FILTER |
| audio_encoder_filter.cpp | 227 | `isTranscoderMode_ = true;` |
| audio_encoder_filter.cpp | 290-291 | OnLinked 中 TransCoder 处理 |
| audio_encoder_filter.cpp | 337-338 | OnLinkedResult 中 TransCoder 处理 |
| muxer_filter.cpp | 110-113 | SetTransCoderMode() |
| muxer_filter.cpp | 285 | isTransCoderMode 检查 |
| muxer_filter.cpp | 331 | 条件分支 |
| muxer_filter.cpp | 356 | OnTransCoderBufferFilled 调用 |
| muxer_filter.cpp | 366-407 | OnTransCoderBufferFilled 实现（EOS计数/音视频同步） |
| muxer_filter.cpp | 411-421 | HandleTransCoderComplete |
| video_resize_filter.cpp | 37 | "builtin.transcoder.videoresize" 注册 |
| video_resize_filter.cpp | 83-110 | ResizeDetailEnhancerVideoCallback VPE回调 |
| video_resize_filter.cpp | 252-254 | DoPrepare 请求 NEXT_FILTER_NEEDED |
| video_resize_filter.cpp | 279 | videoEnhancer_->Start() |
| media_demuxer.h | 553 | `int64_t transcoderStartPts_;` |
| media_demuxer.cpp | 3338-3339 | PTS 偏移补偿 `outputBuffer->pts_ -= transcoderStartPts_;` |
| media_demuxer_pts_functions.cpp | 164-171 | transcoderStartPts_ 首次更新逻辑 |

---

_Draft generated 2026-05-15 by Builder Agent_  
_Local mirror: /home/west/av_codec_repo_