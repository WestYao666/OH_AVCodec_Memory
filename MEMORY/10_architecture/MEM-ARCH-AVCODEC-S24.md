---
id: MEM-ARCH-AVCODEC-S24
title: AudioEncoderFilter 音频编码过滤器——MediaCodec封装与录音管线
type: architecture_fact
scope: [AVCodec, MediaEngine, Filter, AudioEncoder, Recorder, FILTERTYPE_AENC]
status: approved
approved_at: "2026-05-06"
created_by: builder-agent
created_at: "2026-04-25T00:55:00+08:00"
updated_by: builder-agent
updated_at: "2026-04-25T00:55:00+08:00"
evidence:
  - kind: local_file
    path: /home/west/OH_AVCodec/services/media_engine/filters/audio_encoder_filter.cpp
    anchor: "Line 32-35: static AutoRegisterFilter<AudioEncoderFilter> g_registerAudioEncoderFilter(\"builtin.recorder.audioencoder\", FilterType::FILTYPE_AENC, ...)"
    note: |
      注册名为 "builtin.recorder.audioencoder"，FilterType 为 FILTERTYPE_AENC（音频编码器类型）。
      使用 AutoRegisterFilter 模板注册到 FilterFactory。
  - kind: local_file
    path: /home/west/OH_AVCodec/services/media_engine/filters/audio_encoder_filter.cpp
    anchor: "Line 95-107: AudioEncoderFilter::Init()"
    note: |
      Init 方法：
      - 创建 std::shared_ptr<MediaCodec> 实例（mediaCodec_）
      - 调用 mediaCodec_->Init(codecMimeType_, true) 初始化
      - 支持 isTranscoderMode_ 标志（SetTranscoderMode 设置）
  - kind: local_file
    path: /home/west/OH_AVCodec/services/media_engine/filters/audio_encoder_filter.cpp
    anchor: "Line 111-130: AudioEncoderFilter::Configure()"
    note: |
      Configure 方法：
      - 保存 configureParameter_
      - 如果 isTranscoderMode_ 则直接返回 OK（透传）
      - 调用 mediaCodec_->Configure(parameter) 配置编码器
      - 失败时调用 SetFaultEvent("AudioEncoderFilter::Configure error", ret)
  - kind: local_file
    path: /home/west/OH_AVCodec/services/media_engine/filters/audio_encoder_filter.cpp
    anchor: "Line 152-163: AudioEncoderFilter::DoStart()"
    note: |
      DoStart 调用 mediaCodec_->Start()，失败时 SetFaultEvent("AudioEncoderFilter::DoStart error", ret)
  - kind: local_file
    path: /home/west/OH_AVCodec/services/media_engine/filters/audio_encoder_filter.cpp
    anchor: "Line 176-187: AudioEncoderFilter::DoStop()"
    note: |
      DoStop 调用 mediaCodec_->Stop()，失败时 SetFaultEvent("AudioEncoderFilter::DoStop error", ret)
  - kind: local_file
    path: /home/west/OH_AVCodec/services/media_engine/filters/audio_encoder_filter.cpp
    anchor: "Line 212-223: AudioEncoderFilter::NotifyEos()"
    note: |
      NotifyEos 调用 mediaCodec_->NotifyEos()，失败时 SetFaultEvent
  - kind: local_file
    path: /home/west/OH_AVCodec/services/media_engine/filters/audio_encoder_filter.cpp
    anchor: "Line 224-229: AudioEncoderFilter::SetTranscoderMode()"
    note: |
      SetTranscoderMode 设置 isTranscoderMode_ = true，用于转码模式。
      Configure 时如果 isTranscoderMode_ 为 true 则跳过 mediaCodec_->Configure 直接返回 OK。
  - kind: local_file
    path: /home/west/OH_AVCodec/services/media_engine/filters/audio_encoder_filter.cpp
    anchor: "Line 243-268: AudioEncoderFilter::LinkNext()"
    note: |
      LinkNext 方法将下一个 Filter 存入 nextFiltersMap_[outType]。
      创建 AudioEncoderFilterLinkCallback 回调，通过 mediaCodec_ 的回调链处理结果。
      调用 mediaCodec_->SetCodecCallback 注册编码输出回调。
  - kind: local_file
    path: /home/west/OH_AVCodec/services/media_engine/filters/audio_encoder_filter.cpp
    anchor: "Line 231-241: AudioEncoderFilter::SetParameter/GetParameter"
    note: |
      SetParameter 调用 mediaCodec_->SetParameter(parameter) 下发编码参数。
      GetParameter 空实现（未调用 mediaCodec_->GetParameter）。
owner: 耀耀
summary: >
  AudioEncoderFilter 是 MediaEngine 录音管线中的音频编码过滤器，注册名为
  "builtin.recorder.audioencoder"，FilterType 为 FILTERTYPE_AENC。
  其内部封装 std::shared_ptr<MediaCodec>，将上层 Filter 的音频 PCM 数据编码为
  压缩音频码流（AAC/OGG等），然后通过 LinkNext 链路发送给下游的 MuxerFilter。
  支持普通录音模式和转码模式（SetTranscoderMode），转码模式下 Configure 步骤被跳过，
  编码器参数由外部配置。所有生命周期方法（Start/Stop/Flush/Release）均通过
  mediaCodec_ 实例代理，失败时通过 SetFaultEvent 上报 DFX 故障事件。
  与 AudioDecoderFilter（播放管线）形成镜像对称，是 recorder 管线的重要组成部分。
why_it_matters:
  - 录音场景接入：知道 "builtin.recorder.audioencoder" 就找到了录音编码入口
  - 转码场景：isTranscoderMode_ 决定 Configure 是否透传，是转码模式的关键判断点
  - 问题定位：编码失败通过 SetFaultEvent 上报，可用于故障归因
  - 生命周期：编码器 Start→Stop→Release 链路完整，资源管理清晰
key_components:
  - FilterName: "builtin.recorder.audioencoder"
  - FilterType: FILTERTYPE_AENC
  - 内部组件: std::shared_ptr<MediaCodec> (mediaCodec_)
  - 回调: AudioEncoderFilterLinkCallback（处理 OnLinkedResult/OnUnlinkedResult/OnUpdatedResult）
  - 转码模式: isTranscoderMode_ 标志 + SetTranscoderMode() 方法
related:
  - MEM-ARCH-AVCODEC-020: AudioDecoderAdapter（镜像：解码适配器）
  - MEM-ARCH-AVCODEC-S14: MediaEngine Filter Chain（管线整体架构）
  - MEM-ARCH-AVCODEC-S18: AudioCodecServer（AudioCodec 服务端架构）
  - MEM-ARCH-AVCODEC-S8: 音频 FFmpeg 插件（软件编码支持）
pipeline_role: |
  录音管线（Recorder Pipeline）典型拓扑：
  [AudioCaptureFilter/AudioDataSourceFilter] → [AudioEncoderFilter] → [MuxerFilter] → [输出文件]
  其中 AudioEncoderFilter 负责将 PCM 数据编码为压缩码流，是录音管线的核心变换节点。
  播放管线中对称的解码节点是 AudioDecoderFilter/SurfaceDecoderAdapter。
