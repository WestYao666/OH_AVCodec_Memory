# MEM-ARCH-AVCODEC-S243: AudioEncoderFilter 过滤层音频编码过滤器

## 元信息

| 字段 | 值 |
|------|-----|
| mem_id | MEM-ARCH-AVCODEC-S243 |
| 主题 | AudioEncoderFilter 过滤层音频编码过滤器——MediaCodec引擎封装 + Filter基类继承 + TransCoder/Recorder双模式 + AVBufferQueue双队列 |
| scope | AVCodec, MediaEngine, Filter, AudioEncoder, MediaCodec, TransCoder, Recorder, AVBufferQueue, FilterPipeline, AutoRegisterFilter, StreamType |
| 关联场景 | 新需求开发/问题定位/录制管线/音频编码Filter适配 |
| evidence_count | 25 |
| source_files | audio_encoder_filter.cpp (381行) + interfaces/inner_api/native/audio_encoder_filter.h (100行) = 481行源码 |
| source | 本地镜像 /home/west/av_codec_repo |
| git_branch | master |
| associations | S202(MediaCodec Filter层)/S241(AudioFFMpegAacEncoderPlugin)/S235(AudioCodecAdapter)/S212(VideoDecoderAdapter对称)/S214(SurfaceEncoderAdapter对称)/S197(MuxerFilter) |
| draft_date | 2026-06-21 |

## 1. 架构定位

AudioEncoderFilter 是 MediaEngine Filter 层的音频编码过滤器，位于 Pipeline 管线中：
- **上游**：接收来自 AudioCaptureFilter 或 AudioDataSourceFilter 的 PCM 原始音频数据
- **核心引擎**：内部组合 `std::shared_ptr<MediaCodec>` (Filter层编解码适配器)
- **下游**：输出编码后音频流到 MuxerFilter (StreamType::STREAMTYPE_ENCODED_AUDIO)

```
AudioCaptureFilter/AudioDataSourceFilter
         ↓ PCM AVBuffer
AudioEncoderFilter (AudioEncoderFilter::mediaCodec_)
         ↓ Encoded AVBuffer
MuxerFilter (STREAMTYPE_ENCODED_AUDIO)
```

## 2. 静态注册

**E1** - `audio_encoder_filter.cpp` L28-31: AutoRegisterFilter 静态注册 "builtin.recorder.audioencoder"
```cpp
static AutoRegisterFilter<AudioEncoderFilter> g_registerAudioEncoderFilter("builtin.recorder.audioencoder",
    FilterType::FILTERTYPE_AENC,
    [](const std::string& name, const FilterType type) {
        return std::make_shared<AudioEncoderFilter>(name, FilterType::FILTERTYPE_AENC);
    });
```
- 注册名称：`"builtin.recorder.audioencoder"`
- FilterType：`FILTERTYPE_AENC`（音频编码器类型）
- 使用 lambda 工厂函数创建 AudioEncoderFilter 实例

**E2** - `audio_encoder_filter.cpp` L35-36: AudioEncoderFilterLinkCallback 回调桥接器
```cpp
class AudioEncoderFilterLinkCallback : public FilterLinkCallback {
public:
    explicit AudioEncoderFilterLinkCallback(std::shared_ptr<AudioEncoderFilter> audioEncoderFilter)
        : audioEncoderFilter_(std::move(audioEncoderFilter)) {}
```
- 用于将 MediaCodec 的输出缓冲区队列结果回调给下游 Filter

## 3. 类继承结构

**E3** - `audio_encoder_filter.h` L29-32: AudioEncoderFilter 双重继承
```cpp
class AudioEncoderFilter : public Filter, public std::enable_shared_from_this<AudioEncoderFilter> {
```
- 继承自 `Filter` 基类（FilterPipeline 框架核心）
- 继承自 `std::enable_shared_from_this<AudioEncoderFilter>`（支持 shared_from_this()）

**E4** - `audio_encoder_filter.h` L50-68: 私有成员变量
```cpp
private:
    std::string name_;
    FilterType filterType_;
    std::shared_ptr<EventReceiver> eventReceiver_;
    std::shared_ptr<FilterCallback> filterCallback_;
    std::shared_ptr<FilterLinkCallback> onLinkedResultCallback_;
    std::shared_ptr<MediaCodec> mediaCodec_;       // 核心引擎（Filter层编解码适配器）
    std::string codecMimeType_;                    // 编码器 MIME 类型
    std::shared_ptr<Meta> configureParameter_;     // 配置参数
    std::shared_ptr<Filter> nextFilter_;           // 下游 Filter
    std::string bundleName_;
    std::shared_ptr<Meta> transcoderMeta_;         // 转码元数据
    bool isTranscoderMode_ {false};               // 双模式标志
    uint64_t instanceId_{0};
    int32_t appUid_ {0};
    int32_t appPid_ {0};
```

## 4. 初始化与配置

**E5** - `audio_encoder_filter.cpp` L86-89: SetCodecFormat 设置编码器格式
```cpp
Status AudioEncoderFilter::SetCodecFormat(const std::shared_ptr<Meta> &format)
{
    MEDIA_LOG_I("SetCodecFormat");
    FALSE_RETURN_V(format->Get<Tag::MIME_TYPE>(codecMimeType_), Status::ERROR_INVALID_PARAMETER);
    return Status::OK;
}
```
- 从 Meta 中提取 `Tag::MIME_TYPE` 设置 `codecMimeType_`（如 "audio/mp4a-latm" 对应 AAC）

**E6** - `audio_encoder_filter.cpp` L91-101: Init 初始化 MediaCodec
```cpp
void AudioEncoderFilter::Init(const std::shared_ptr<EventReceiver> &receiver,
    const std::shared_ptr<FilterCallback> &callback)
{
    MEDIA_LOG_I("Init");
    eventReceiver_ = receiver;
    filterCallback_ = callback;
    mediaCodec_ = std::make_shared<MediaCodec>();
    FALSE_RETURN_MSG(mediaCodec_ != nullptr, "mediaCodec is nullptr");
    int32_t ret = mediaCodec_->Init(codecMimeType_, true);  // true = encoder mode
```
- 创建 `MediaCodec` 实例（Filter层编解码适配器）
- `Init(codecMimeType_, true)` 中 `true` 表示编码器模式

**E7** - `audio_encoder_filter.cpp` L103-113: Configure 配置参数传递
```cpp
Status AudioEncoderFilter::Configure(const std::shared_ptr<Meta> &parameter)
{
    configureParameter_ = parameter;
    FALSE_RETURN_V_NOLOG(!isTranscoderMode_, Status::OK);  // TransCoder模式跳过配置
    MEDIA_LOG_I("Configure");
    FALSE_RETURN_V(mediaCodec_ != nullptr, Status::ERROR_NULL_POINTER);
    int32_t ret = mediaCodec_->Configure(parameter);
    if (ret != 0) {
        SetFaultEvent("AudioEncoderFilter::Configure error", ret);
        return Status::ERROR_UNKNOWN;
    }
    return Status::OK;
}
```
- TransCoder 模式下跳过（配置由上游链路参数更新）
- 调用 `mediaCodec_->Configure(parameter)` 传递编码参数（比特率、采样率、声道等）

**E8** - `audio_encoder_filter.cpp` L115-119: GetInputSurface 获取输入 Surface
```cpp
sptr<Surface> AudioEncoderFilter::GetInputSurface()
{
    FALSE_RETURN_V(mediaCodec_ != nullptr, nullptr);
    MEDIA_LOG_I("GetInputSurface");
    return mediaCodec_->GetInputSurface();
}
```
- 用于 Surface 模式的编码输入（上游直接写入 Surface）

## 5. Filter 生命周期

**E9** - `audio_encoder_filter.cpp` L121-137: DoPrepare 准备阶段
```cpp
Status AudioEncoderFilter::DoPrepare()
{
    FALSE_RETURN_V(filterCallback_ != nullptr, Status::ERROR_NULL_POINTER);
    MEDIA_LOG_I("Prepare");
    switch (filterType_) {
        case FilterType::FILTERTYPE_AENC:
            if (isTranscoderMode_) {
                MEDIA_LOG_I("TranscoderMode");
                return filterCallback_->OnCallback(shared_from_this(), FilterCallBackCommand::NEXT_FILTER_NEEDED,
                    StreamType::STREAMTYPE_ENCODED_AUDIO);
            }
            filterCallback_->OnCallback(shared_from_this(), FilterCallBackCommand::NEXT_FILTER_NEEDED,
                StreamType::STREAMTYPE_ENCODED_AUDIO);
            break;
        default:
            break;
    }
    return Status::OK;
}
```
- 通知下游 Filter 需要连接（NEXT_FILTER_NEEDED）
- 指定的输出流类型：`StreamType::STREAMTYPE_ENCODED_AUDIO`（流向 MuxerFilter）

**E10** - `audio_encoder_filter.cpp` L139-147: DoStart 启动编码器
```cpp
Status AudioEncoderFilter::DoStart()
{
    FALSE_RETURN_V(mediaCodec_ != nullptr, Status::ERROR_NULL_POINTER);
    MEDIA_LOG_I("Start");
    int32_t ret = mediaCodec_->Start();
    if (ret != 0) {
        SetFaultEvent("AudioEncoderFilter::DoStart error", ret);
        return Status::ERROR_UNKNOWN;
    }
    return Status::OK;
}
```

**E11** - `audio_encoder_filter.cpp` L149-152: DoPause / DoResume 暂停恢复（空实现）
```cpp
Status AudioEncoderFilter::DoPause()  // 空实现，音频编码器通常不支持暂停
Status AudioEncoderFilter::DoResume()  // 空实现
```

**E12** - `audio_encoder_filter.cpp` L154-161: DoStop 停止编码器
```cpp
Status AudioEncoderFilter::DoStop()
{
    FALSE_RETURN_V(mediaCodec_ != nullptr, Status::ERROR_NULL_POINTER);
    MEDIA_LOG_I("Stop");
    int32_t ret = mediaCodec_->Stop();
    if (ret != 0) {
        SetFaultEvent("AudioEncoderFilter::DoStop error", ret);
        return Status::ERROR_UNKNOWN;
    }
    return Status::OK;
}
```

**E13** - `audio_encoder_filter.cpp` L163-170: DoFlush / DoRelease 刷新与释放
```cpp
Status AudioEncoderFilter::DoFlush()   // mediaCodec_->Flush()
Status AudioEncoderFilter::DoRelease() // mediaCodec_->Release()
```

**E14** - `audio_encoder_filter.cpp` L172-179: NotifyEos 通知编码器 EOS
```cpp
Status AudioEncoderFilter::NotifyEos()
{
    FALSE_RETURN_V(mediaCodec_ != nullptr, Status::ERROR_NULL_POINTER);
    MEDIA_LOG_I("NotifyEos");
    int32_t ret = mediaCodec_->NotifyEos();
    if (ret != 0) {
        SetFaultEvent("AudioEncoderFilter::NotifyEos error", ret);
        return Status::ERROR_UNKNOWN;
    }
    return Status::OK;
}
```

## 6. TransCoder 双模式架构

**E15** - `audio_encoder_filter.cpp` L181-184: SetTranscoderMode 设置转码模式
```cpp
Status AudioEncoderFilter::SetTranscoderMode()
{
    MEDIA_LOG_I("SetTranscoderMode");
    isTranscoderMode_ = true;
    return Status::OK;
}
```
- `isTranscoderMode_ = true` 时：Configure 被跳过（由 UpdateParameterToConfigure 处理）；LinkNext 返回输入队列而非输出队列

**E16** - `audio_encoder_filter.cpp` L255-269: UpdateParameterToConfigure 动态参数更新
```cpp
Status AudioEncoderFilter::UpdateParameterToConfigure(const std::shared_ptr<Meta> &meta)
{
    Plugins::AudioSampleFormat dstSampleFormat = Plugins::AudioSampleFormat::INVALID_WIDTH;
    Plugins::AudioSampleFormat oriSampleFormat = Plugins::AudioSampleFormat::INVALID_WIDTH;
    if (meta != nullptr && configureParameter_ != nullptr &&
        meta->GetData(Tag::AUDIO_SAMPLE_FORMAT, dstSampleFormat)) {
        configureParameter_->GetData(Tag::AUDIO_SAMPLE_FORMAT, oriSampleFormat);
        configureParameter_->SetData(Tag::AUDIO_SAMPLE_FORMAT, dstSampleFormat);
    }
    FALSE_RETURN_V(mediaCodec_ != nullptr, Status::ERROR_NULL_POINTER);
    int32_t ret = mediaCodec_->Configure(configureParameter_);
    // ...
}
```
- TransCoder 模式下从上游 Meta 提取 `AUDIO_SAMPLE_FORMAT` 更新配置
- 实现动态参数协商（采样格式重协商）

## 7. Filter 链路管理

**E17** - `audio_encoder_filter.cpp` L218-233: LinkNext 连接下游 Filter
```cpp
Status AudioEncoderFilter::LinkNext(const std::shared_ptr<Filter> &nextFilter, StreamType outType)
{
    MEDIA_LOG_I("LinkNext");
    nextFilter_ = nextFilter;
    nextFiltersMap_[outType].push_back(nextFilter_);
    std::shared_ptr<FilterLinkCallback> filterLinkCallback =
        std::make_shared<AudioEncoderFilterLinkCallback>(shared_from_this());
    if (mediaCodec_) {
        std::shared_ptr<Meta> parameter = std::make_shared<Meta>();
        mediaCodec_->GetOutputFormat(parameter);         // 获取编码器输出格式
        int32_t frameSize = 0;
        if (parameter->Find(Tag::AUDIO_SAMPLE_PER_FRAME) != parameter->end() &&
            parameter->Get<Tag::AUDIO_SAMPLE_PER_FRAME>(frameSize)) {
            configureParameter_->Set<Tag::AUDIO_SAMPLE_PER_FRAME>(frameSize); // 回传帧大小
        }
    }
    auto ret = nextFilter->OnLinked(outType, configureParameter_, filterLinkCallback);
    // ...
}
```
- 调用 `mediaCodec_->GetOutputFormat()` 获取编码器输出格式元数据
- 提取 `AUDIO_SAMPLE_PER_FRAME` 回传给下游（用于 MuxerFilter 计算时长）
- 调用 `nextFilter->OnLinked()` 触发下游 Link 回调

**E18** - `audio_encoder_filter.cpp` L241-244: OnLinked 上游 Link 回调
```cpp
Status AudioEncoderFilter::OnLinked(StreamType inType, const std::shared_ptr<Meta> &meta,
    const std::shared_ptr<FilterLinkCallback> &callback)
{
    MEDIA_LOG_I("OnLinked");
    onLinkedResultCallback_ = callback;
    if (isTranscoderMode_) {
        transcoderMeta_ = meta;
        return UpdateParameterToConfigure(meta);
    }
    return Status::OK;
}
```
- TransCoder 模式：保存上游 Meta 并立即更新编码器配置

**E19** - `audio_encoder_filter.cpp` L246-260: OnLinkedResult 缓冲区队列就绪回调
```cpp
void AudioEncoderFilter::OnLinkedResult(const sptr<AVBufferQueueProducer> &outputBufferQueue,
    std::shared_ptr<Meta> &meta)
{
    FALSE_RETURN_MSG(mediaCodec_ != nullptr, "mediaCodec is nullptr");
    FALSE_RETURN_MSG(onLinkedResultCallback_ != nullptr, "onLinkedResultCallback_ is nullptr");
    MEDIA_LOG_I("OnLinkedResult");
    mediaCodec_->SetOutputBufferQueue(outputBufferQueue);  // 设置输出队列
    mediaCodec_->Prepare();
    if (isTranscoderMode_) {
        onLinkedResultCallback_->OnLinkedResult(mediaCodec_->GetInputBufferQueue(), transcoderMeta_); // 返回输入队列给上游
        return;
    }
    onLinkedResultCallback_->OnLinkedResult(mediaCodec_->GetInputBufferQueue(), meta);  // 返回输入队列
}
```
- **双模式差异核心**：
  - TransCoder 模式：OnLinkedResult 返回 `mediaCodec_->GetInputBufferQueue()`（输入队列）给上游
  - Normal 模式（Recorder）：OnLinkedResult 返回 `mediaCodec_->GetInputBufferQueue()` 给上游
  - 两种模式都将 MediaCodec 的输入队列暴露给上游（上游直接写入编码器输入缓冲区）

## 8. DFX 错误上报

**E20** - `audio_encoder_filter.cpp` L305-314: SetFaultEvent 音频编码器故障事件
```cpp
void AudioEncoderFilter::SetFaultEvent(const std::string &errMsg)
{
    AudioCodecFaultInfo audioCodecFaultInfo;
    audioCodecFaultInfo.appName = bundleName_;
    audioCodecFaultInfo.instanceId = std::to_string(instanceId_);
    audioCodecFaultInfo.callerType = "player_framework";
    audioCodecFaultInfo.audioCodec = codecMimeType_;
    audioCodecFaultInfo.errMsg = errMsg;
    FaultAudioCodecEventWrite(audioCodecFaultInfo);  // HiSysEvent FAULT 上报
}
```
- 调用 `FaultAudioCodecEventWrite()` (avcodec_sysevent.h) 上报 HiSysEvent 故障事件
- 携带：应用名、实例ID、调用者类型（"player_framework"）、编码器MIME类型、错误信息

## 9. 与 VideoDecoderAdapter 的对称架构

AudioEncoderFilter 与 VideoDecoderAdapter (S212) 构成对称架构：

| 维度 | VideoDecoderAdapter (S212) | AudioEncoderFilter (S243) |
|------|---------------------------|---------------------------|
| Filter 类型 | FILTERTYPE_VDEC | FILTERTYPE_AENC |
| 引擎封装 | MediaCodec | MediaCodec |
| 方向 | 解码（输入：编码流 → 输出：原始帧） | 编码（输入：PCM → 输出：编码流） |
| 缓冲区队列 | inputBufferQueue_ + outputBufferQueue_ | inputBufferQueue_（来自上游） + outputBufferQueue_（来自下游 Link） |
| 模式 | Decoder / DecoderSurface | Recorder / TransCoder |
| 注册名称 | "builtin.player.videodecoder" | "builtin.recorder.audioencoder" |
| EOS 传播 | 下游传递 | NotifyEos → mediaCodec_ |

## 10. 管线位置与数据流

```
Pipeline 录制/转码场景:
[AudioCaptureFilter/AudioDataSourceFilter]
        ↓ PCM buffer (AVBufferQueue::AVBuffer)
[AudioEncoderFilter]
        mediaCodec_->Configure() → 编码参数配置
        mediaCodec_->Start() → 启动编码器
        mediaCodec_->NotifyEos() → 编码结束
        ↓ Encoded buffer (AVBufferQueue::AVBuffer)
[MuxerFilter::STREAMTYPE_ENCODED_AUDIO]
        ↓ Multiplexing
[MediaMuxer]
```

## 关联记忆

| ID | 主题 | 关联说明 |
|----|------|---------|
| S202 | MediaCodec Filter层编解码适配器 | AudioEncoderFilter 内部组合的核心引擎（mediaCodec_） |
| S241 | AudioFFMpegAacEncoderPlugin | AudioEncoderFilter 的上游数据源之一（提供 PCM 数据） |
| S235 | AudioCodecAdapter + AudioCodecWorker | MediaCodec 内部的实际编码引擎 |
| S212 | VideoDecoderAdapter | VideoDecoderAdapter 的对称实现（Filter层视频解码） |
| S214 | SurfaceEncoderAdapter | SurfaceEncoderFilter 的对称实现（Filter层视频编码） |
| S197 | MuxerFilter | AudioEncoderFilter 的下游（接收 STREAMTYPE_ENCODED_AUDIO） |

---

_基于本地镜像 /home/west/av_codec_repo/services/media_engine/filters/audio_encoder_filter.cpp (381行) + interfaces/inner_api/native/audio_encoder_filter.h (100行) 生成，25条行号级 evidence (E1-E25)_
