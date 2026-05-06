---
id: MEM-ARCH-AVCODEC-S35
title: AudioDecoderFilter 音频解码过滤器——Filter层封装与 AudioDecoderAdapter 三层调用链
type: architecture_fact
scope: [AVCodec, MediaEngine, Filter, AudioDecoder, Pipeline, AVBufferQueue, AsyncMode]
status: approved
approved_at: "2026-05-06"
created_by: builder-agent
created_at: "2026-04-25T16:51:00+08:00"
confidence: high
summary: >
  AudioDecoderFilter（services/media_engine/filters/audio_decoder_filter.cpp）是播放管线的音频解码环节过滤器，
  注册名为 builtin.player.audiodecoder，FilterType 为 FILTERTYPE_ADEC（播放）/FILTERTYPE_AENC（转码）。
  采用 Filter层（AudioDecoderFilter）→ 适配层（AudioDecoderAdapter）→ 引擎层（AudioCodec）三层架构。
  关键机制：bufferStatus_ 位标志状态机驱动双端（输入/输出）处理，AudioDecInputPortConsumerListener +
  AudioDecOutPortProducerListener 双监听器实现 AVBufferQueue 事件驱动，异步模式下由 AudioCodec 内部
  ProcessInputBufferInner 驱动完整编解码循环，FormatChange 时通过 HandleFormatChange 通知下游。
  与 AudioEncoderFilter(S24) 对称，构成播放管线解码终点/编码起点。
why_it_matters:
 - 播放管线完整性：AudioDecoderFilter 是 DemuxerFilter → AudioDecoderFilter → AudioSinkFilter 播放管线的中间解码环节
 - 三层架构分离：Filter层专注管线调度（bufferStatus_状态机/双端驱动），适配层专注Codec实例化（AudioCodecFactory双路径），
   引擎层专注具体编解码逻辑，符合单一职责
 - 双监听器事件驱动：AudioDecInputPortConsumerListener（输入端）和 AudioDecOutPortProducerListener（输出端），
   通过 HandleInputBuffer(isTriggeredByOutPort) 驱动整个处理循环，无需主动轮询
 - 异步模式核心：IS_FILTER_ASYNC 决定 Filter 的 TaskThread 是否启用，AudioCodec::ProcessInputBufferInner
   在 AudioCodec 内部线程驱动输入/输出 buffer 传递，AudioDecoderCallback::OnOutputBufferAvailable 是空实现（no-op）
 - 格式协商：UpdateTrackInfoSampleFormat 将 APE/FLAC 高于16bit的采样格式强制升频至 S32LE，
   防止解码输出精度丢失
 - 问题定位：bufferStatus_ 状态错乱导致解码无输出；ChangePlugin 动态切换编码器时注意重新绑定 AVBufferQueue 监听器
 - DRM 支持：SetDecryptionConfig 将 DRM keySessionProxy 传递给底层 AudioCodec，支持安全视频路径（SVP）

evidence:
  - kind: code
    path: /home/west/av_codec_repo/services/media_engine/filters/audio_decoder_filter.cpp
    anchor: Line 65-68
    note: |
      static AutoRegisterFilter<AudioDecoderFilter> g_registerAudioDecoderFilter("builtin.player.audiodecoder",
          FilterType::FILTERTYPE_ADEC, [](const std::string& name, const FilterType type) {
          bool isAsyncMode = system::GetParameter("debug.media_service.audio.audiodecoder_async", "1") == "1";
          return std::make_shared<AudioDecoderFilter>(name, FilterType::FILTERTYPE_ADEC, isAsyncMode);
      注册名：builtin.player.audiodecoder，FilterType::FILTERTYPE_ADEC（播放）/FILTERTYPE_AENC（转码）
      isAsyncMode 由 debug.media_service.audio.audiodecoder_async 参数控制（默认"1"）

  - kind: code
    path: /home/west/av_codec_repo/services/media_engine/filters/audio_decoder_filter.cpp
    anchor: Line 71
    note: |
      static const bool IS_FILTER_ASYNC = system::GetParameter("persist.media_service.async_filter", "1") == "1";
      IS_FILTER_ASYNC 作为 Filter 构造参数，控制 Filter 的 TaskThread 是否激活

  - kind: code
    path: /home/west/av_codec_repo/interfaces/inner_api/native/audio_decoder_filter.h
    anchor: Line 123-150
    note: |
      FilterType filterType_;
      std::shared_ptr<Meta> meta_;
      std::shared_ptr<Filter> nextFilter_;
      std::shared_ptr<EventReceiver> eventReceiver_;
      std::shared_ptr<FilterCallback> filterCallback_;
      std::shared_ptr<AudioDecoderAdapter> decoder_;  // 适配层，持有 AudioCodec 智能指针
      std::mutex releaseMutex_;
      std::mutex bufferStatusMutex_;
      uint32_t bufferStatus_{static_cast<uint32_t>(InOutPortBufferStatus::INIT)};
      // bufferStatus_ 位标志状态机，驱动双端处理决策

  - kind: code
    path: /home/west/av_codec_repo/services/media_engine/filters/audio_decoder_filter.cpp
    anchor: Line 40-56
    note: |
      constexpr uint32_t BUFFER_STATUS_INIT_PROCESS_ALWAYS =
          static_cast<uint32_t>(InOutPortBufferStatus::INIT_IGNORE_RET);
      constexpr uint32_t BUFFER_STATUS_INIT_IGNORE_RET = static_cast<uint32_t>(InOutPortBufferStatus::INIT_IGNORE_RET);
      constexpr uint32_t BUFFER_STATUS_INIT = static_cast<uint32_t>(InOutPortBufferStatus::INIT);
      constexpr uint32_t BUFFER_STATUS_AVAIL_IN_OUT = static_cast<uint32_t>(InOutPortBufferStatus::INPORT_AVAIL) |
          static_cast<uint32_t>(InOutPortBufferStatus::OUTPORT_AVAIL);
      // BUFFER_STATUS_* 是 bufferStatus_ 的合法取值，通过位或组合表示输入/输出端可用性

  - kind: code
    path: /home/west/av_codec_repo/services/media_engine/filters/audio_decoder_filter.cpp
    anchor: Line 183-213
    note: |
      void AudioDecoderFilter::Init(const std::shared_ptr<EventReceiver> &receiver,
          const std::shared_ptr<FilterCallback> &callback)
      {
          eventReceiver_ = receiver;
          filterCallback_ = callback;
          decoder_ = std::make_shared<AudioDecoderAdapter>();  // 创建适配层
      }
      // Init 中实例化 AudioDecoderAdapter（适配层），Filter层持有其 shared_ptr

  - kind: code
    path: /home/west/av_codec_repo/services/media_engine/filters/audio_decoder_filter.cpp
    anchor: Line 391-441
    note: |
      Status AudioDecoderFilter::OnLinked(StreamType inType, const std::shared_ptr<Meta> &meta,
          const std::shared_ptr<FilterLinkCallback> &callback)
      {
          // 1. UpdateTrackInfoSampleFormat: 修正音频格式元数据
          // 2. decoder_->Init(true, mime) 或 Init(false, name): 初始化 AudioCodec
          // 3. SetCodecCallback(mediaCodecCallback): 设置 AudioDecoderCallback
          // 4. decoder_->Configure(meta): 配置解码器参数
          // 5. decoder_->SetDumpInfo(isDump_, instanceId_): DFX dump信息
      }
      // OnLinked 是 LinkNext 的对端回调，完成 AudioCodec 层面的初始化（区别于 DoPrepare 的 Filter 层初始化）

  - kind: code
    path: /home/west/av_codec_repo/services/media_engine/filters/audio_decoder_adapter.cpp
    anchor: Line 44-55
    note: |
      Status AudioDecoderAdapter::Init(bool isMimeType, const std::string &name)
      {
          if (isMimeType) {
              audiocodec_ = MediaAVCodec::AudioCodecFactory::CreateByMime(name, false);
          } else {
              audiocodec_ = MediaAVCodec::AudioCodecFactory::CreateByName(name);
          }
          FALSE_RETURN_V_MSG(audiocodec_ != nullptr, Status::ERROR_INVALID_STATE, "audiocodec_ is nullptr");
          return Status::OK;
      }
      // AudioDecoderAdapter::Init 双路径：按 MIME 类型（外部输入源）或按名称（硬编码注册名）创建 AudioCodec 实例

  - kind: code
    path: /home/west/av_codec_repo/services/media_engine/filters/audio_decoder_adapter.cpp
    anchor: Line 178-182
    note: |
      void AudioDecoderAdapter::ProcessInputBufferInner(bool isTriggeredByOutPort, bool isFlushed, uint32_t &bufferStatus)
      {
          FALSE_RETURN_MSG(audiocodec_ != nullptr, "ProcessInputBufferInner audiocodec_ is nullptr");
          audiocodec_->ProcessInputBufferInner(isTriggeredByOutPort, isFlushed, bufferStatus);
      }
      // ProcessInputBufferInner 是异步模式核心：AudioCodec 内部线程驱动输入/输出 buffer 传递，
      // bufferStatus 由 AudioCodec 更新后回传给 AudioDecoderFilter

  - kind: code
    path: /home/west/av_codec_repo/services/media_engine/filters/audio_decoder_filter.cpp
    anchor: Line 110-130
    note: |
      class AudioDecInputPortConsumerListener : public OHOS::Media::IConsumerListener {
          explicit AudioDecInputPortConsumerListener(std::shared_ptr<AudioDecoderFilter> audioDecoderFilter)
              : audioDecoderFilter_(audioDecoderFilter) {}
          void OnBufferAvailable() override {
              MEDIA_LOG_D("AudioDecInputPortConsumerListener OnBufferAvailable");
              if (auto audioDecoderFilter = audioDecoderFilter_.lock()) {
                  audioDecoderFilter->HandleInputBuffer(false);  // false = 输入端触发
              }
          }
      private:
          std::weak_ptr<AudioDecoderFilter> audioDecoderFilter_;
      };
      // 输入端监听器：AVBufferQueue 输入端可用时触发 HandleInputBuffer(false)

  - kind: code
    path: /home/west/av_codec_repo/services/media_engine/filters/audio_decoder_filter.cpp
    anchor: Line 132-151
    note: |
      class AudioDecOutPortProducerListener : public IRemoteStub<IProducerListener> {
          explicit AudioDecOutPortProducerListener(std::shared_ptr<AudioDecoderFilter> audioDecoderFilter)
              : audioDecoderFilter_(audioDecoderFilter) {}
          void OnBufferAvailable() override {
              MEDIA_LOG_D("AudioDecOutPortProducerListener OnBufferAvailable");
              if (auto audioDecoderFilter = audioDecoderFilter_.lock()) {
                  audioDecoderFilter->HandleInputBuffer(true);  // true = 输出端触发
              }
          }
      private:
          std::weak_ptr<AudioDecoderFilter> audioDecoderFilter_;
      };
      // 输出端监听器：AVBufferQueue 输出端可用（解码输出就绪）时触发 HandleInputBuffer(true)

  - kind: code
    path: /home/west/av_codec_repo/services/media_engine/filters/audio_decoder_filter.cpp
    anchor: Line 561-587
    note: |
      bool AudioDecoderFilter::IsNeedProcessInput(bool isOutPort)
      {
          // bufferStatus_ 状态机决策逻辑：
          // - BUFFER_STATUS_AVAIL_IN: 输入可用，无需处理输出端
          // - BUFFER_STATUS_AVAIL_OUT: 输出可用，无需处理输入端
          // - BUFFER_STATUS_AVAIL_IN_OUT: 两端都可用，按 isOutPort 决策
          // - BUFFER_STATUS_INIT: 初始状态，按 isOutPort 决策
          // - BUFFER_STATUS_OUT_EOS_START: EOS 开始阶段，强制处理输出端
          // 返回 false 表示无需当前处理（另一端需优先处理）
      }
      // IsNeedProcessInput 是双端驱动的决策核心，确保输入/输出均衡处理

  - kind: code
    path: /home/west/av_codec_repo/services/media_engine/filters/audio_decoder_filter.cpp
    anchor: Line 441-480
    note: |
      void AudioDecoderFilter::UpdateTrackInfoSampleFormat(const std::string& mime, const std::shared_ptr<Meta> &meta)
      {
          // APE/FLAC 高分辨率格式处理：
          // if (sampleDepth > SAMPLE_FORMAT_BIT_DEPTH_16) { SAMPLE_S32LE }
          // 其他非RAW格式：统一 SAMPLE_S16LE
          // 48kHz 以下：统一 SAMPLE_S16LE
          // 防止高于16bit的采样在输出时精度丢失
      }
      // UpdateTrackInfoSampleFormat 保证解码输出统一为 16bit 或 32bit PCM

  - kind: code
    path: /home/west/av_codec_repo/services/media_engine/filters/audio_decoder_filter.cpp
    anchor: Line 363-386
    note: |
      Status AudioDecoderFilter::ChangePlugin(std::shared_ptr<Meta> meta)
      {
          decoder_->ChangePlugin(mime, false, meta);  // false = 解码器
          if (IsAsyncMode()) {
              SetInputBufferQueueConsumerListener();  // 重新绑定输入监听器
              SetOutputBufferQueueProducerListener(); // 重新绑定输出监听器
          }
      }
      // ChangePlugin 动态切换底层 Codec 实现（如软解→硬解），必须重新绑定 AVBufferQueue 监听器

  - kind: code
    path: /home/west/av_codec_repo/services/media_engine/filters/audio_decoder_filter.cpp
    anchor: Line 213-236
    note: |
      Status AudioDecoderFilter::DoStart()
      {
          MEDIA_LOG_I("AudioDecoderFilter::Start.");
          // decoder_->Start(): 启动 AudioCodec
          // FaultAudioCodecEventWrite: DFX 上报启动失败事件
          struct AudioCodecFaultInfo audioCodecFaultInfo;
          audioCodecFaultInfo.errMsg = "AudioDecoder start failed";
          FaultAudioCodecEventWrite(audioCodecFaultInfo);
      }
      // DoStart 启动底层 AudioCodec，失败时上报 DFX 故障事件

  - kind: code
    path: /home/west/av_codec_repo/services/media_engine/filters/audio_decoder_filter.cpp
    anchor: Line 761-780
    note: |
      void AudioDecoderCallback::OnOutputBufferAvailable(uint32_t index, std::shared_ptr<AVBuffer> buffer)
      {
          (void)index;
          (void)buffer;
          // 空实现（no-op）
      }
      // AudioDecoderCallback::OnOutputBufferAvailable 是空实现，
      // 实际 buffer 路由通过 AudioDecOutPortProducerListener::OnBufferAvailable 驱动（AVBufferQueue 事件）
      // AudioCodec 内部线程处理完解码后直接写入 output AVBufferQueue，由 ProducerListener 通知 Filter

  - kind: code
    path: /home/west/av_codec_repo/services/media_engine/filters/audio_decoder_filter.cpp
    anchor: Line 197-202
    note: |
      Status AudioDecoderFilter::DoPrepare()
      {
          switch (filterType_) {
              case FilterType::FILTERTYPE_AENC:
                  ret = filterCallback_->OnCallback(shared_from_this(), FilterCallBackCommand::NEXT_FILTER_NEEDED,
                      StreamType::STREAMTYPE_ENCODED_AUDIO);
                  break;
              case FilterType::FILTERTYPE_ADEC:
                  ret = filterCallback_->OnCallback(shared_from_this(), FilterCallBackCommand::NEXT_FILTER_NEEDED,
                      StreamType::STREAMTYPE_RAW_AUDIO);
                  break;
          }
          state_ = FilterState::READY;
      }
      // DoPrepare 时根据 FilterType 向 FilterCallback 申请下一个 Filter（转码路径：ENCODED_AUDIO，播放路径：RAW_AUDIO）
      // 构成管线：DemuxerFilter → AudioDecoderFilter → AudioSinkFilter（播放）
      // 构成管线：AudioEncoderFilter → AudioDecoderFilter → MuxerFilter（转码）

  - kind: code
    path: /home/west/av_codec_repo/services/media_engine/filters/audio_decoder_filter.cpp
    anchor: Line 696-726
    note: |
      void AudioDecoderFilter::OnOutputFormatChanged(const Format& format)
      {
          // 从 AudioCodecCallback 回调中提取 format 参数
          // 解析 sampleRate/channels/sampleFormat
          // 与之前 meta_ 对比，有变化则调用 nextFilter_->HandleFormatChange(meta_)
          // 通知下游 AudioSinkFilter 格式变化
      }
      // OnOutputFormatChanged 处理运行时格式变化（如采样率切换），通知下游 Filter

  - kind: code
    path: /home/west/av_codec_repo/services/media_engine/filters/audio_decoder_filter.cpp
    anchor: Line 191
    note: |
      decoder_ = std::make_shared<AudioDecoderAdapter>();  // Filter::Init 中调用
      AudioDecoderAdapter 使用 AudioCodecFactory::CreateByMime/CreateByName 创建 AudioCodec
      支持软解（FFmpeg audio decoder plugin）和硬解（平台相关 AudioCodec）两种路径

pipeline_position:
  demuxing: DemuxerFilter (MEM-ARCH-AVCODEC-007)
  decoding: AudioDecoderFilter (this topic)
  rendering: AudioSinkFilter (MEM-ARCH-AVCODEC-S31)
  output: Speaker / Audio HAL

related:
  - MEM-ARCH-AVCODEC-S31  # AudioSinkFilter 音频播放输出
  - MEM-ARCH-AVCODEC-S24  # AudioEncoderFilter 音频编码过滤（对称）
  - MEM-ARCH-AVCODEC-007  # DemuxerFilter 音频流解复用
  - MEM-ARCH-AVCODEC-S14  # Filter Chain 架构（FilterLinkCallback + AVBufferQueue）
  - MEM-ARCH-AVCODEC-S23  # SurfaceEncoderFilter（视频编码对比）
  - MEM-ARCH-AVCODEC-009  # 软硬Codec区分（codecIsVendor）

owner: builder-agent
review:
  status: pending_approval
  submitted_at: "2026-04-25T16:51:00+08:00"
