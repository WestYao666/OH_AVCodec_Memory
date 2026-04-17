id: MEM-ARCH-AVCODEC-008
title: Muxer 封装流程与 OutputFormat 枚举
type: architecture_fact
scope: [AVCodec, Muxer, Container, OutputFormat]
status: approved
confidence: high
summary: >
  AVCodec 封装（muxer）核心类是 MediaMuxer（services/media_engine/modules/muxer/media_muxer.cpp），
  支持三种 OutputFormat：OUTPUT_FORMAT_DEFAULT（mp4）、OUTPUT_FORMAT_MPEG_4（mp4）、OUTPUT_FORMAT_M4A（m4a）。
  注意：muxer 目前只支持这三种本地文件输出格式，不支持 mkv/webm 等其他容器。
  完整封装流程：MediaMuxer.Init(fd/FILE, format) → AddTrack() → GetInputBufferQueue() →
  Start() → WriteSample() → Stop()。
  输出目标通过 DataSink 抽象（支持 FILE* 或 fd），通过 MuxerPlugin 实现具体编码。
  Track 以 AVBufferQueueProducer 形式暴露给上游，上游将压缩样本写入队列，MediaMuxer 在独立线程消费。
why_it_matters:
 - 三方应用接入：封装输出只支持 mp4/m4a，需要其他格式需要扩展 MuxerPlugin
 - 问题定位：封装失败时首先检查 OutputFormat 是否合法、fd 是否可写、Track 是否正确 Add
 - 新需求开发：新增封装格式需要实现 MuxerPlugin 接口，并在 OutputFormat 枚举中注册
 - 性能分析：MediaMuxer 在独立线程中消费 AVBufferQueue，写入线程与编码线程解耦
evidence:
 - kind: code
   ref: services/media_engine/modules/muxer/media_muxer.h
   anchor: MediaMuxer 核心方法
   note: |
     Init(fd, format) / Init(FILE*, format) 初始化输出
     AddTrack() → GetInputBufferQueue() → Start() → WriteSample() → Stop()
     内部 State 机：UNINITIALIZED → INITIALIZED → STARTED → STOPPED
 - kind: code
   ref: interfaces/inner_api/native/av_common.h
   anchor: OutputFormat 枚举
   note: |
     OUTPUT_FORMAT_DEFAULT(0) = mp4 / OUTPUT_FORMAT_MPEG_4(2) = mp4 / OUTPUT_FORMAT_M4A(6) = m4a
     三种格式，无 mkv/webm/flv 等
 - kind: code
   ref: services/media_engine/modules/muxer/media_muxer.h
   anchor: DataSink 抽象
   note: DataSinkFd / DataSinkFile 两种输出目标实现
 - kind: code
   ref: interfaces/plugin/muxer_plugin.h
   anchor: MuxerPlugin 接口
   note: 封装插件基类，MediaMuxer 通过 CreatePlugin(format) 工厂创建具体插件
 - kind: code
   ref: services/media_engine/modules/muxer/media_muxer.h
   anchor: AVBufferQueueProducer 暴露
   note: GetInputBufferQueue(trackIndex) 返回 AVBufferQueueProducer，上游编码器将样本写入队列
 - kind: code
   ref: services/media_engine/modules/muxer/media_muxer.cpp
   anchor: 独立消费线程
   note: MediaMuxer 启动独立线程消费 AVBufferQueue，OnBufferAvailable 回调触发消费
related:
 - MEM-ARCH-AVCODEC-007
 - MEM-ARCH-AVCODEC-006
 - FAQ-SCENE2-002
 - FAQ-SCENE3-004
owner: 耀耀
review:
  owner: 耀耀
  approved_at: "2026-04-17"
  change_policy: update_on_code_change
update_trigger: code_change
created_at: "2026-04-17"
updated_at: "2026-04-17"
