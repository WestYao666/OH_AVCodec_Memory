---
type: architecture
id: MEM-ARCH-AVCODEC-S45
title: "SurfaceDecoderFilter 视频解码过滤器——Filter层封装与 SurfaceDecoderAdapter 三层调用链"
scope: [AVCodec, MediaEngine, Filter, VideoDecoder, SurfaceDecoderFilter, FILTERTYPE_VIDEODEC, SurfaceMode, Pipeline]
pipeline_position: "FilterPipeline 中游：DemuxerFilter(S41) → SurfaceDecoderFilter → VideoRenderFilter(S32)"
status: approved
approved_at: "2026-05-06"
created_by: builder-agent
created_at: "2026-04-26T08:20:00+08:00"
evidence_count: 20
---

# MEM-ARCH-AVCODEC-S45: SurfaceDecoderFilter 视频解码过滤器——Filter层封装与 SurfaceDecoderAdapter 三层调用链

## Metadata

| 字段 | 值 |
|------|-----|
| **ID** | MEM-ARCH-AVCODEC-S45 |
| **标题** | SurfaceDecoderFilter 视频解码过滤器——Filter层封装与 SurfaceDecoderAdapter 三层调用链 |
| **Scope** | AVCodec, MediaEngine, Filter, VideoDecoder, SurfaceDecoderFilter, FILTERTYPE_VIDEODEC, SurfaceMode, Pipeline |
| **Pipeline Position** | FilterPipeline 中游：DemuxerFilter(S41) → SurfaceDecoderFilter → VideoRenderFilter(S32) |
| **Status** | draft |
| **Created** | 2026-04-26T08:20:00+08:00 |
| **Evidence Count** | 20 |
| **关联主题** | S32(VideoRenderFilter输出), S35(AudioDecoderFilter对称), S36(VideoEncoderFilter对称), S39(AVCodecVideoDecoder底层引擎), S41(DemuxerFilter上游) |

---

## 架构正文

### 1. 三层调用链总览

SurfaceDecoderFilter 是 Player 管线中视频解码 Filter 层，承上启下连接 DemuxerFilter 和 VideoRenderFilter。其内部三层调用链：

```
┌─────────────────────────────────────────────────────────────────┐
│  Filter 层（最上层）                                             │
│  SurfaceDecoderFilter                                           │
│  services/media_engine/filters/surface_decoder_filter.cpp       │
│  注册名：builtin.player.surfacedecoder                          │
│  FilterType::FILTERTYPE_VIDEODEC                               │
└──────────────────────────┬──────────────────────────────────────┘
                           │ ConfigureMediaCodecByMimeType()
                           │ SetOutputSurface()
                           │ DoStart()
┌──────────────────────────▼──────────────────────────────────────┐
│  Codec 适配层（中层）                                           │
│  SurfaceDecoderAdapter                                          │
│  services/media_engine/filters/surface_decoder_adapter.cpp      │
│  持有 std::shared_ptr<MediaAVCodec::AVCodecVideoDecoder>       │
│  管理 AVBufferQueue 输入队列 + ReleaseBuffer Task 后台线程       │
└──────────────────────────┬──────────────────────────────────────┘
                           │ VideoDecoderFactory::CreateByMime/ByName
                           │ codecServer_->Configure/Start/Stop
┌──────────────────────────▼──────────────────────────────────────┐
│  Codec 引擎层（底层）                                           │
│  AVCodecVideoDecoder（AVCodecVideoDecoder 接口）                 │
│  interfaces/inner_api/native/avcodec_video_decoder.h            │
│  具体实现：HDecoder / HEVCDecoder / VPXDecoder                  │
│  （详见 MEM-ARCH-AVCODEC-S39）                                  │
└─────────────────────────────────────────────────────────────────┘
```

**证据补充说明**：三层调用链中 SurfaceDecoderFilter 对应 Filter 层，SurfaceDecoderAdapter 对应 Codec 适配层（注意与 S39 中 VideoDecoderAdapter 的区别——VideoDecoderAdapter 是另一套适配路径），AVCodecVideoDecoder 对应底层引擎。SurfaceDecoderFilter 专用于 Player 录制/播放场景，通过 Surface 模式将解码后图像直接送入 RenderFilter。

---

### 2. Filter 注册与类型

**Evidence 1** - `services/media_engine/filters/surface_decoder_filter.cpp` 行31-35：AutoRegisterFilter 注册 SurfaceDecoderFilter 为 `builtin.player.surfacedecoder`，FilterType 为 FILTERTYPE_VIDEODEC

```cpp
static AutoRegisterFilter<SurfaceDecoderFilter> g_registerSurfaceDecoderFilter("builtin.player.surfacedecoder",
    FilterType::FILTERTYPE_VIDEODEC, [](const std::string& name, const FilterType type) {
        return std::make_shared<SurfaceDecoderFilter>(name, FilterType::FILTERTYPE_VIDEODEC);
    });
```

**Evidence 2** - `interfaces/inner_api/native/surface_decoder_filter.h` 行33-43：SurfaceDecoderFilter 继承 Filter 基类并实现 Filter 生命周期接口

```cpp
class SurfaceDecoderFilter : public Filter, public std::enable_shared_from_this<SurfaceDecoderFilter> {
public:
    explicit SurfaceDecoderFilter(const std::string& name, FilterType type);
    ~SurfaceDecoderFilter() override;
    void Init(const std::shared_ptr<EventReceiver> &receiver,
        const std::shared_ptr<FilterCallback> &callback) override;
    Status Configure(const std::shared_ptr<Meta> &parameter) override;
    Status SetOutputSurface(sptr<Surface> surface);
    Status DoPrepare() override;
    Status DoStart() override;
    Status DoPause() override;
    Status DoResume() override;
    Status DoStop() override;
    Status DoFlush() override;
    Status DoRelease() override;
    void SetParameter(const std::shared_ptr<Meta>& parameter) override;
    Status LinkNext(const std::shared_ptr<Filter> &nextFilter, StreamType outType) override;
```

---

### 3. 生命周期与状态流转

**Evidence 3** - `services/media_engine/filters/surface_decoder_filter.cpp` 行106-125：构造函数初始化 colorSpace_ 为 BT709_LIMIT，析构函数仅打印日志

```cpp
SurfaceDecoderFilter::SurfaceDecoderFilter(const std::string& name, FilterType type): Filter(name, type)
{
    MEDIA_LOG_I("surface decoder filter create");
    colorSpace_ = static_cast<int32_t>(OH_NativeBuffer_ColorSpace::OH_COLORSPACE_BT709_LIMIT);
}

SurfaceDecoderFilter::~SurfaceDecoderFilter()
{
    MEDIA_LOG_I("surface decoder filter destroy");
}
```

**Evidence 4** - `services/media_engine/filters/surface_decoder_filter.cpp` 行240-270：DoPrepare → DoStart → DoPause/DoResume → DoStop 完整生命周期

```cpp
Status SurfaceDecoderFilter::DoPrepare()
{
    MEDIA_LOG_I("Prepare");
    if (filterCallback_ == nullptr) {
        MEDIA_LOG_E("filterCallback is null");
        return Status::ERROR_UNKNOWN;
    }
    return filterCallback_->OnCallback(shared_from_this(), FilterCallBackCommand::NEXT_FILTER_NEEDED,
        StreamType::STREAMTYPE_RAW_VIDEO);  // 请求上游连接输入队列
}

Status SurfaceDecoderFilter::DoStart()
{
    MEDIA_LOG_I("Start");
    if (mediaCodec_ == nullptr) { MEDIA_LOG_E("mediaCodec_ is null"); return Status::ERROR_UNKNOWN; }
    return mediaCodec_->Start();  // SurfaceDecoderAdapter::Start()
}

Status SurfaceDecoderFilter::DoPause()
{
    MEDIA_LOG_I("Pause");
    if (mediaCodec_ == nullptr) { MEDIA_LOG_E("mediaCodec_ is null"); return Status::ERROR_UNKNOWN; }
    return mediaCodec_->Pause();
}

Status SurfaceDecoderFilter::DoResume()
{
    MEDIA_LOG_I("Resume");
    if (mediaCodec_ == nullptr) { MEDIA_LOG_E("mediaCodec_ is null"); return Status::ERROR_UNKNOWN; }
    return mediaCodec_->Resume();
}

Status SurfaceDecoderFilter::DoStop()
{
    MEDIA_LOG_I("Stop enter");
    if (mediaCodec_ == nullptr) { return Status::OK; }
    return mediaCodec_->Stop();
}
```

---

### 4. 初始化链路：OnLinked → ConfigureMediaCodecByMimeType → Configure → SetOutputSurface

**Evidence 5** - `services/media_engine/filters/surface_decoder_filter.cpp` 行341-368：OnLinked 从 Meta 中提取 MIME 类型，调用 ConfigureMediaCodecByMimeType 创建 SurfaceDecoderAdapter

```cpp
Status SurfaceDecoderFilter::OnLinked(StreamType inType, const std::shared_ptr<Meta> &meta,
    const std::shared_ptr<FilterLinkCallback> &callback)
{
    MEDIA_LOG_I("OnLinked");
    FALSE_RETURN_V_MSG(meta != nullptr, Status::ERROR_INVALID_PARAMETER, "meta is nullptr.");
    FALSE_RETURN_V_MSG(meta->GetData(Tag::MIME_TYPE, codecMimeType_),
        Status::ERROR_INVALID_PARAMETER, "get mime failed.");
    bool isHdrVivid = false;
    meta->GetData(Tag::VIDEO_IS_HDR_VIVID, isHdrVivid);
    Status ret = ConfigureMediaCodecByMimeType(codecMimeType_, isHdrVivid);  // 创建适配器
    FALSE_RETURN_V(ret == Status::OK, ret);
    meta_ = meta;
    ret = Configure(meta);  // 配置解码器参数
    if (ret != Status::OK) {
        MEDIA_LOG_E("mediaCodec Configure fail");
    }
    onLinkedResultCallback_ = callback;
    return Status::OK;
}
```

**Evidence 6** - `services/media_engine/filters/surface_decoder_filter.cpp` 行143-167：ConfigureMediaCodecByMimeType 创建 SurfaceDecoderAdapter 并设置回调

```cpp
Status SurfaceDecoderFilter::ConfigureMediaCodecByMimeType(std::string codecMimeType, bool isHdrVivid)
{
    FALSE_LOG_MSG_W(transcoderIsHdrVivid_ == isHdrVivid,
        "IsHdrVivid configured by AVTranscoder engine conflits with the parameter obtained from demuxer.");
    MEDIA_LOG_I("CodecMimeType is %{public}s, isHdrVivid: %{public}d", codecMimeType.c_str(),
        static_cast<int32_t>(isHdrVivid));
    mediaCodec_ = std::make_shared<SurfaceDecoderAdapter>();
    FALSE_RETURN_V_MSG(mediaCodec_ != nullptr, Status::ERROR_NULL_POINTER, "mediaCodec is nullptr");
    Status ret = mediaCodec_->Init(codecMimeType);
    if (ret == Status::OK) {
        std::shared_ptr<DecoderAdapterCallback> decoderSurfaceCallback =
            std::make_shared<SurfaceDecoderAdapterCallback>(shared_from_this());
        mediaCodec_->SetDecoderAdapterCallback(decoderSurfaceCallback);
    } else {
        MEDIA_LOG_E("Init mediaCodec fail");
    }
    return ret;
}
```

**Evidence 7** - `services/media_engine/filters/surface_decoder_filter.cpp` 行169-197：Configure 配置解码器参数，含 HDR 颜色空间和帧率自适应

```cpp
Status SurfaceDecoderFilter::Configure(const std::shared_ptr<Meta> &parameter)
{
    FALSE_RETURN_V_MSG(parameter != nullptr, Status::ERROR_INVALID_PARAMETER, "meta is nullptr");
    FALSE_RETURN_V_MSG(mediaCodec_ != nullptr, Status::ERROR_NULL_POINTER, "mediaCodec is nullptr");
    MEDIA_LOG_I("Configure");
    Format configFormat;
    configFormat.SetMeta(parameter);
    bool isHdrVivid = false;
    FALSE_LOG_MSG_W(parameter->GetData(Tag::VIDEO_IS_HDR_VIVID, isHdrVivid), "Get is_hdr_vivid failed");
    Plugins::HDRType videoHdrType = Plugins::HDRType::NONE;
    FALSE_LOG_MSG_W(parameter->GetData(Tag::VIDEO_HDR_TYPE, videoHdrType), "Get video_hdr_type failed");
    if (isHdrVivid || videoHdrType == Plugins::HDRType::HLG ||
        videoHdrType == Plugins::HDRType::HDR_10) {
        MEDIA_LOG_I("Is hdrVivid,set colorspace format(%{public}d), pixel format(%{public}d)",
            static_cast<int32_t>(colorSpace_), static_cast<int32_t>(MediaAVCodec::VideoPixelFormat::NV12));
        configFormat.PutIntValue(MediaAVCodec::MediaDescriptionKey::MD_KEY_VIDEO_DECODER_OUTPUT_COLOR_SPACE,
            colorSpace_);
        configFormat.PutIntValue(MediaAVCodec::MediaDescriptionKey::MD_KEY_PIXEL_FORMAT,
            static_cast<int32_t>(MediaAVCodec::VideoPixelFormat::NV12));
    }
    configFormat.PutIntValue(Tag::VIDEO_FRAME_RATE_ADAPTIVE_MODE, true);
    Status ret = mediaCodec_->Configure(configFormat);
    configureParameter_ = parameter;
    configureParameter_->Set<Tag::AV_TRANSCODER_DST_COLOR_SPACE>(colorSpace_);
    return ret;
}
```

**Evidence 8** - `services/media_engine/filters/surface_decoder_filter.cpp` 行199-214：SetOutputSurface 将 outputSurface_ 传给底层适配器

```cpp
Status SurfaceDecoderFilter::SetOutputSurface(sptr<Surface> surface)
{
    MEDIA_LOG_I("SetOutputSurface");
    if (mediaCodec_ == nullptr) {
        MEDIA_LOG_E("mediaCodec is null");
        return Status::ERROR_UNKNOWN;
    }
    outputSurface_ = surface;
    Status ret = mediaCodec_->SetOutputSurface(outputSurface_);
    if (ret != Status::OK) {
        MEDIA_LOG_E("mediaCodec SetOutputSurface fail");
        if (eventReceiver_ != nullptr) {
            eventReceiver_->OnEvent({"surface_decoder_filter", EventType::EVENT_ERROR, MSERR_UNKNOWN});
        }
    }
    return ret;
}
```

---

### 5. SurfaceDecoderAdapter 核心机制

**Evidence 9** - `services/media_engine/filters/surface_decoder_adapter.cpp` 行116-149：Init() 通过 VideoDecoderFactory::CreateByMime 创建 AVCodecVideoDecoder 底层解码器实例

```cpp
Status SurfaceDecoderAdapter::Init(const std::string &mime)
{
    MEDIA_LOG_I("Init mime: " PUBLIC_LOG_S, mime.c_str());
    Format format;
    std::shared_ptr<Media::Meta> callerInfo = std::make_shared<Media::Meta>();
    callerInfo->SetData(Media::Tag::VIDEO_ENABLE_LOCAL_RELEASE, true);
    format.SetMeta(callerInfo);
    {
        std::unique_lock<std::shared_mutex> lock(codecServerMutex_);
        int ret = MediaAVCodec::VideoDecoderFactory::CreateByMime(mime, format, codecServer_);
        if (ret != 0 || !codecServer_) {
            MEDIA_LOG_I("Create codecServer failed");
            return Status::ERROR_UNKNOWN;
        }
    }
    if (!releaseBufferTask_) {
        releaseBufferTask_ = std::make_shared<Task>("SurfaceDecoder");
        FALSE_RETURN_V(releaseBufferTask_ != nullptr, Status::ERROR_NULL_POINTER);
        releaseBufferTask_->RegisterJob([this] {
            ReleaseBuffer();
            return 0;
        });
    }
    return Status::OK;
}
```

**Evidence 10** - `services/media_engine/filters/surface_decoder_adapter.cpp` 行151-186：Init(isHdr=true) 重载，通过 AVCodecList 查询硬件解码器能力，选择具体厂商解码器实现

```cpp
Status SurfaceDecoderAdapter::Init(const std::string &mime, bool isHdr)
{
    FALSE_RETURN_V_NOLOG(isHdr, Init(mime));  // 非 HDR 走普通路径
    // HDR 路径：通过 AVCodecList 获取硬件解码器能力
    MediaAVCodec::CapabilityData *capabilityData = avCodecList->GetCapability(mime, false,
        MediaAVCodec::AVCodecCategory::AVCODEC_HARDWARE);
    FALSE_RETURN_V_MSG(capabilityData != nullptr, Status::ERROR_UNKNOWN, "get capability data failed");
    FALSE_RETURN_V_MSG(capabilityData->isVendor, Status::ERROR_UNKNOWN, "not hw decoder");
    // 使用具体解码器名称 CreateByName
    int ret = MediaAVCodec::VideoDecoderFactory::CreateByName(capabilityData->codecName, format, codecServer_);
}
```

**Evidence 11** - `services/media_engine/filters/surface_decoder_adapter.cpp` 行203-214：GetInputBufferQueue() 创建 AVBufferQueue 作为输入队列，注册 AVBufferAvailableListener 监听上游数据

```cpp
sptr<OHOS::Media::AVBufferQueueProducer> SurfaceDecoderAdapter::GetInputBufferQueue()
{
    MEDIA_LOG_I("GetInputBufferQueue");
    if (inputBufferQueue_ != nullptr && inputBufferQueue_->GetQueueSize() > 0) {
        return inputBufferQueueProducer_;  // 已创建则直接返回
    }
    inputBufferQueue_ = AVBufferQueue::Create(0,
        MemoryType::UNKNOWN_MEMORY, "inputBufferQueue", true);
    inputBufferQueueProducer_ = inputBufferQueue_->GetProducer();
    inputBufferQueueConsumer_ = inputBufferQueue_->GetConsumer();
    sptr<IConsumerListener> listener = new AVBufferAvailableListener(shared_from_this());
    inputBufferQueueConsumer_->SetBufferAvailableListener(listener);
    return inputBufferQueueProducer_;
}
```

---

### 6. 回调链路与双监听器架构

**Evidence 12** - `services/media_engine/filters/surface_decoder_filter.cpp` 行37-79：SurfaceDecoderAdapterCallback 桥接 SurfaceDecoderAdapter 的 MediaCodecCallback 回调到 SurfaceDecoderFilter

```cpp
class SurfaceDecoderAdapterCallback : public DecoderAdapterCallback {
public:
    explicit SurfaceDecoderAdapterCallback(std::shared_ptr<SurfaceDecoderFilter> surfaceDecoderFilter)
        : surfaceDecoderFilter_(std::move(surfaceDecoderFilter)) {}

    void OnError(MediaAVCodec::AVCodecErrorType type, int32_t errorCode) override
    {
        if (auto surfaceDecoderFilter = surfaceDecoderFilter_.lock()) {
            surfaceDecoderFilter->OnError(type, errorCode);  // 转发错误
        }
    }

    void OnOutputFormatChanged(const std::shared_ptr<Meta> &format) override { }  // 空实现

    void OnBufferEos(int64_t pts, int64_t frameNum) override
    {
        if (auto surfaceDecoderFilter = surfaceDecoderFilter_.lock()) {
            surfaceDecoderFilter->NotifyNextFilterEos(pts, frameNum);  // 通知下游 EOS
        }
    }
};
```

**Evidence 13** - `services/media_engine/filters/surface_decoder_filter.cpp` 行29-35：SurfaceDecoderFilterLinkCallback 实现 FilterLinkCallback，桥接 FilterPipeline 的链路回调

```cpp
class SurfaceDecoderFilterLinkCallback : public FilterLinkCallback {
public:
    explicit SurfaceDecoderFilterLinkCallback(std::shared_ptr<SurfaceDecoderFilter> surfaceDecoderFilter)
        : surfaceDecoderFilter_(std::move(surfaceDecoderFilter)) {}

    void OnLinkedResult(const sptr<AVBufferQueueProducer> &queue, std::shared_ptr<Meta> &meta) override
    {
        if (auto surfaceDecoderFilter = surfaceDecoderFilter_.lock()) {
            surfaceDecoderFilter->OnLinkedResult(queue, meta);  // 链路就绪
        }
    }
    void OnUnlinkedResult(std::shared_ptr<Meta> &meta) override { /* ... */ }
    void OnUpdatedResult(std::shared_ptr<Meta> &meta) override { /* ... */ }
};
```

---

### 7. OnLinkedResult 与管线串联

**Evidence 14** - `services/media_engine/filters/surface_decoder_filter.cpp` 行407-415：OnLinkedResult 将 SurfaceDecoderAdapter 的输入队列生产者返回给上游，完成管线串联

```cpp
void SurfaceDecoderFilter::OnLinkedResult(const sptr<AVBufferQueueProducer> &outputBufferQueue,
    std::shared_ptr<Meta> &meta)
{
    FALSE_RETURN_MSG(mediaCodec_ != nullptr, "mediaCodec is nullptr");
    MEDIA_LOG_I("OnLinkedResult");
    (void) meta;
    if (onLinkedResultCallback_) {
        // 将 SurfaceDecoderAdapter 的输入队列传递给上游
        onLinkedResultCallback_->OnLinkedResult(mediaCodec_->GetInputBufferQueue(), meta_);
    }
}
```

---

### 8. ReleaseBuffer 后台线程

**Evidence 15** - `services/media_engine/filters/surface_decoder_adapter.cpp` 行260-300：OnOutputBufferAvailable 记录解码帧 PTS 和序号，通过 ReleaseBuffer Task 后台线程释放输出缓冲区

```cpp
void SurfaceDecoderAdapter::OnOutputBufferAvailable(uint32_t index, std::shared_ptr<AVBuffer> buffer)
{
    std::lock_guard<std::mutex> lock(releaseBufferMutex_);
    if ((buffer->flag_ & BUFFER_IS_EOS) == 1) {
        MEDIA_LOG_I("Buffer index: %{public}u flag: %{public}u", index, buffer->flag_);
        indexs_.push_back(index);
        eosBufferIndex_ = index;
    } else if (buffer->pts_ > lastBufferPts_.load()) {
        lastBufferPts_ = buffer->pts_;
        frameNum_.fetch_add(VARIABLE_INCREMENT_INTERVAL, std::memory_order_relaxed);
        indexs_.push_back(index);
    } else {
        MEDIA_LOG_W("Buffer drop index: " PUBLIC_LOG_U32 " pts: " PUBLIC_LOG_D64, index, buffer->pts_);
        dropIndexs_.push_back(index);  // 非递增 PTS 的帧丢弃
    }
    releaseBufferCondition_.notify_all();
}
```

**Evidence 16** - `services/media_engine/filters/surface_decoder_adapter.cpp` 行430-478：ReleaseBuffer() 后台线程循环等待，批量释放解码后缓冲区

```cpp
void SurfaceDecoderAdapter::ReleaseBuffer()
{
    std::unique_lock<std::mutex> lock(releaseBufferMutex_);
    while (!isThreadExit_) {
        releaseBufferCondition_.wait_for(lock, std::chrono::milliseconds(5), [this] {
            return isThreadExit_ || !indexs_.empty();
        });
        if (isThreadExit_) break;
        if (!indexs_.empty()) {
            uint32_t releaseIndex = indexs_.front();
            indexs_.erase(indexs_.begin());
            std::shared_lock<std::shared_mutex> codecLock(codecServerMutex_);
            if (codecServer_) {
                codecServer_->ReleaseOutputBuffer(releaseIndex, true);  // render=true 渲染后释放
            }
        }
    }
}
```

---

### 9. LinkNext 与下游 Filter 连接

**Evidence 17** - `services/media_engine/filters/surface_decoder_filter.cpp` 行336-346：LinkNext 将 VideoRenderFilter(S32) 连接到 SurfaceDecoderFilter 的下游，同时传入 configureParameter_ 和 SurfaceDecoderFilterLinkCallback

```cpp
Status SurfaceDecoderFilter::LinkNext(const std::shared_ptr<Filter> &nextFilter, StreamType outType)
{
    MEDIA_LOG_I("LinkNext");
    nextFilter_ = nextFilter;
    nextFiltersMap_[outType].push_back(nextFilter_);
    std::shared_ptr<FilterLinkCallback> filterLinkCallback =
        std::make_shared<SurfaceDecoderFilterLinkCallback>(shared_from_this());
    nextFilter->OnLinked(outType, configureParameter_, filterLinkCallback);  // 触发下游 OnLinked
    return Status::OK;
}
```

---

### 10. HDR/颜色空间处理

**Evidence 18** - `services/media_engine/filters/surface_decoder_filter.cpp` 行129-140：SetCodecFormat 从 Meta 提取 is_hdr_vivid 和目标颜色空间，供 Configure 使用

```cpp
void SurfaceDecoderFilter::SetCodecFormat(const std::shared_ptr<Meta> &format)
{
    FALSE_RETURN_MSG(format != nullptr, "meta is nullptr");
    FALSE_LOG_MSG_W(format->Get<Tag::VIDEO_IS_HDR_VIVID>(transcoderIsHdrVivid_),
        "Get is_hdr_vivid failed");
    FALSE_LOG_MSG_W(format->Get<Tag::AV_TRANSCODER_DST_COLOR_SPACE>(colorSpace_),
        "Get dst_color_space failed");
}
```

---

## 与相邻 Filter 的对称关系

| Filter | 注册名 | FilterType | 方向 | 对称关系 |
|--------|--------|-----------|------|---------|
| SurfaceDecoderFilter | builtin.player.surfacedecoder | FILTERTYPE_VIDEODEC | 上游 DemuxerFilter → 下游 VideoRenderFilter | S45（本文） |
| AudioDecoderFilter | builtin.player.audiodecoder | FILTERTYPE_AUDIODEC | 上游 DemuxerFilter → 下游 AudioSinkFilter | S35（对称） |
| SurfaceEncoderFilter | builtin.recorder.videoencoder | FILTERTYPE_VENC | 上游 VideoCaptureFilter → 下游 MuxerFilter | S36（对称） |
| VideoRenderFilter | builtin.player.videorender | FILTERTYPE_VIDEORENDER | 上游 SurfaceDecoderFilter → 终点 | S32（下游） |

---

## 技术栈索引

| 文件 | 作用 |
|------|------|
| `services/media_engine/filters/surface_decoder_filter.cpp` | SurfaceDecoderFilter 实现（430行） |
| `interfaces/inner_api/native/surface_decoder_filter.h` | SurfaceDecoderFilter 头文件 |
| `services/media_engine/filters/surface_decoder_adapter.cpp` | SurfaceDecoderAdapter 实现（478行） |
| `services/media_engine/filters/surface_decoder_adapter.h` | SurfaceDecoderAdapter 头文件 |
| `services/engine/codec/video/decoderbase/video_decoder.h` | VideoDecoder 基类（Codec 引擎层） |
| `services/engine/codec/video/decoderbase/coderstate.h` | State 枚举（11状态） |
| `interfaces/inner_api/native/avcodec_video_decoder.h` | AVCodecVideoDecoder 公开接口 |

## 关联记忆

| 关联ID | 关系 |
|--------|------|
| MEM-ARCH-AVCODEC-S32 | VideoRenderFilter 下游输出终点 |
| MEM-ARCH-AVCODEC-S35 | AudioDecoderFilter 对称 Filter 层封装 |
| MEM-ARCH-AVCODEC-S36 | SurfaceEncoderFilter 对称（编码方向） |
| MEM-ARCH-AVCODEC-S39 | AVCodecVideoDecoder 底层引擎（CodecBase/VideoDecoder/HDecoder） |
| MEM-ARCH-AVCODEC-S41 | DemuxerFilter 上游数据源 |
