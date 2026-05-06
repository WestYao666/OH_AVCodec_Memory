---
id: MEM-ARCH-AVCODEC-S34
title: MuxerFilter 封装过滤器——录制管线输出终点与多轨 AVBufferQueue 协调
type: architecture_fact
scope: [AVCodec, MediaEngine, Filter, Muxer, RecorderPipeline, AVBufferQueue, MultiTrack]
status: approved
approved_at: "2026-05-07"
created_by: builder-agent
created_at: "2026-04-25T16:40:00+08:00"
confidence: high
summary: >
  MuxerFilter（services/media_engine/filters/muxer_filter.cpp）是录制/转码管线的输出终点过滤器，
  注册名为 builtin.recorder.muxer，FilterType 为 FILTERTYPE_MUXER。
  内部封装 MediaMuxer，通过多轨 AVBufferQueue 接收来自 AudioEncoderFilter/SurfaceEncoderFilter 的编码后样本。
  关键机制：preFilterCount_ 协调所有上游编码器停止信号，duration/size 上限触发异步停止，
  双模式（Recorder vs TransCoder）区分输出路径，PTS Map 同步音视频时基。
why_it_matters:
 - 录制管线完整性：MuxerFilter 是 capture → encode → mux 管线的最后一环，与 AudioEncoderFilter(S24) 和 SurfaceEncoderFilter(S23) 共同构成完整录制数据流
 - 多轨同步：音频/视频/timed-metadata 三类轨道各持有一个 AVBufferQueue，通过 bufferPtsMap_ 同步 PTS，防止音视频不同步
 - 停止协调：preFilterCount_ 确保所有上游编码器 EOS 后才停止 MediaMuxer，避免截断
 - 问题定位：录制文件不完整（截断）时首先检查 preFilterCount_ vs stopCount_ 是否匹配
 - 新需求开发：新增封装格式（如 FLV）需在 MuxerFilter FORMAT_TABLE 和 MediaMuxer OutputFormat 中同时注册

evidence:
  - kind: code
    path: /home/west/av_codec_repo/services/media_engine/filters/muxer_filter.cpp
    anchor: Line 54-56
    note: |
      static AutoRegisterFilter<MuxerFilter> g_registerMuxerFilter(
          "builtin.recorder.muxer", FilterType::FILTERTYPE_MUXER, ...)
      注册名：builtin.recorder.muxer，FilterType::FILTERTYPE_MUXER

  - kind: code
    path: /home/west/av_codec_repo/services/media_engine/filters/muxer_filter.cpp
    anchor: Line 100-113
    note: |
      SetOutputParameter: mediaMuxer_ = make_shared<MediaMuxer>(appUid, appPid);
      mediaMuxer_->Init(fd, (Plugins::OutputFormat)format)
      MediaMuxer 初始化，绑定文件描述符 fd 和 OutputFormat

  - kind: code
    path: /home/west/av_codec_repo/services/media_engine/filters/muxer_filter.cpp
    anchor: Line 260-308
    note: |
      OnLinked: mediaMuxer_->AddTrack(trackIndex, meta) 添加轨道
      mediaMuxer_->GetInputBufferQueue(trackIndex) 获取该轨的 AVBufferQueueProducer
      MuxerBrokerListener 监听 AVBufferQueue，OnBufferFilled 回调将样本送往 MediaMuxer
      trackIndexMap_.emplace(mimeType, trackIndex) 建立 MIME→轨道索引映射
      preFilterCount_++ 统计上游编码器数量

  - kind: code
    path: /home/west/av_codec_repo/interfaces/inner_api/native/muxer_filter.h
    anchor: Line 72-79
    note: |
      int32_t preFilterCount_{0};   // 上游编码器数量（音频+视频+metadata）
      int32_t stopCount_{0};         // 已收到停止信号的编码器数量
      int32_t eosCount_{0};          // 已发送 EOS 的轨数量
      std::map<int32_t, int64_t> bufferPtsMap_;  // 每轨最后一个 PTS，用于音视频同步
      std::map<std::string, int32_t> trackIndexMap_; // MIME→轨道索引映射

  - kind: code
    path: /home/west/av_codec_repo/services/media_engine/filters/muxer_filter.cpp
    anchor: Line 173-182
    note: |
      DoStop: stopCount_++ 后与 preFilterCount_ 比较
      if (stopCount_ == preFilterCount_) { mediaMuxer_->Stop(); }
      只有当所有上游编码器都已停止，才停止 MediaMuxer
      防止媒体文件截断

  - kind: code
    path: /home/west/av_codec_repo/services/media_engine/filters/muxer_filter.cpp
    anchor: Line 331-351
    note: |
      OnBufferFilled: !isTransCoderMode 时检查 maxDuration_
      if (currentBufferPts / US_TO_MS > maxDuration_ * S_TO_MS && !isReachMaxDuration_)
          isReachMaxDuration_.store(true); EventCompleteStopAsync();
      到达最大录制时长后异步触发停止（3000ms 超时等待其他轨）

  - kind: code
    path: /home/west/av_codec_repo/services/media_engine/filters/muxer_filter.cpp
    anchor: Line 370-390
    note: |
      EOS 处理：eosCount_++ 计数各轨 EOS
      isCompleted = (eosCount_ == preFilterCount_) || (videoIsEos && audioIsEos)
      双判停条件：所有轨 EOS 或 音视频各自 EOS（支持无视频/纯音频场景）

  - kind: code
    path: /home/west/av_codec_repo/services/media_engine/filters/muxer_filter.cpp
    anchor: Line 113
    note: |
      SetTransCoderMode(): isTransCoderMode = true
      转码模式下 MuxerFilter 接收来自其他 MuxerFilter 的已编码样本流，
      与录音模式的直接 fd 输出路径不同

  - kind: code
    path: /home/west/av_codec_repo/services/media_engine/filters/muxer_filter.cpp
    anchor: Line 65-95
    note: |
      MuxerBrokerListener::OnBufferFilled
      实现 IBrokerListener 接口，持有 wptr<AVBufferQueueProducer>
      在 AVBufferAvailableListener 回调中调用 MuxerFilter::OnBufferFilled
      将上游编码器样本从 AVBufferQueue 路由到 MuxerFilter 处理

  - kind: code
    path: /home/west/av_codec_repo/interfaces/inner_api/native/muxer_filter.h
    anchor: Line 88-90
    note: |
      int64_t lastVideoPts_{0}; int64_t lastAudioPts_{0};
      bool videoIsEos{false}; bool audioIsEos{false};
      独立记录音视频最后 PTS 和 EOS 状态，用于 GetCurrentPtsMs() 查询和双轨 EOS 判停

pipeline_position:
  recording_input: AudioCaptureFilter(S26) / VideoCaptureFilter(S28)
  encoding: AudioEncoderFilter(S24) / SurfaceEncoderFilter(S23)
  muxing: MuxerFilter (this topic)
  output: MediaMuxer → fd/FILE (MEM-ARCH-AVCODEC-008)

related:
  - MEM-ARCH-AVCODEC-008  # MediaMuxer 底层封装模块
  - MEM-ARCH-AVCODEC-S23  # SurfaceEncoderFilter 视频编码过滤
  - MEM-ARCH-AVCODEC-S24  # AudioEncoderFilter 音频编码过滤
  - MEM-ARCH-AVCODEC-S26  # AudioCaptureFilter 音频采集
  - MEM-ARCH-AVCODEC-S28  # VideoCaptureFilter 视频采集
  - MEM-ARCH-AVCODEC-S14  # Filter Chain 架构（FilterLinkCallback + AVBufferQueue）

owner: builder-agent
review:
  status: pending_approval
  submitted_at: "2026-04-25T16:40:00+08:00"
