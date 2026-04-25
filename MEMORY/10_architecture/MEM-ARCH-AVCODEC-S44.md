---
type: architecture
id: MEM-ARCH-AVCODEC-S44
topic: MetaDataFilter 元数据过滤器——Surface模式时元数据注入与录制管线时戳同步
scope: [AVCodec, MediaEngine, Filter, MetaData, TimedMetadata, Surface, RecorderPipeline, PTS, SurfaceBuffer]
status: draft
submitted_by: builder-agent
submitted_at: "2026-04-26T06:35:00+08:00"
created_at: "2026-04-26T06:35:00+08:00"
updated_at: "2026-04-26T06:35:00+08:00"
evidence: |
  - source: services/media_engine/filters/metadata_filter.cpp
    lines: "33-36"
    anchor: "AutoRegisterFilter<MetaDataFilter> 注册 \"builtin.recorder.timed_metadata\"，FilterType::TIMED_METADATA，MetaDataFilterLinkCallback 三路回调（OnLinkedResult/OnUnlinkedResult/OnUpdatedResult）"
  - source: interfaces/inner_api/native/metadata_filter.h
    lines: "35-55"
    anchor: "MetaDataFilter 类定义：SetInputMetaSurface(sptr<Surface>)→GetInputMetaSurface()→OnBufferAvailable()→AcquireInputBuffer( SurfaceBuffer&/timestamp/bufferSize )→ProcessAndPushOutputBuffer"
  - source: services/media_engine/filters/metadata_filter.cpp
    lines: "100-140"
    anchor: "SetInputMetaSurface(sptr<Surface>) 注册 MetaDataSurfaceBufferListener 消费监听；GetInputMetaSurface() 创建 ConsumerSurface→SetDefaultUsage(METASURFACE_USAGE=BUFFER_USAGE_CPU_READ|CPU_WRITE|MEM_DMA)→返回 ProducerSurface 给上游"
  - source: services/media_engine/filters/metadata_filter.cpp
    lines: "330-400"
    anchor: "AcquireInputBuffer() 输入 Surface.AcquireBuffer(buffer/fence/timestamp/damage)；extraData->ExtraGet(\"timeStamp\"/\"dataSize\")；检查 timestamp 有效性（>0 && >latestBufferTime_）"
  - source: services/media_engine/filters/metadata_filter.cpp
    lines: "400-420"
    anchor: "ProcessAndPushOutputBuffer() AVBufferQueueProducer::RequestBuffer→memory_->Write( bufferSize )→PushBuffer；UpdateBufferConfig() 计算 PTS: buffer->pts_ = timestamp - startBufferTime_ - totalPausedTime_"
  - source: interfaces/inner_api/native/metadata_filter.h
    lines: "68-78"
    anchor: "totalPausedTime_(int64_t)、latestPausedTime_、refreshTotalPauseTime_ 暂停时间补偿机制；DoPause() 时 latestPausedTime_=latestBufferTime_；DoResume() 时 refreshTotalPauseTime_=true 触发累加"
  - source: services/media_engine/filters/metadata_filter.cpp
    lines: "280-320"
    anchor: "LinkNext(shared_ptr<Filter>/StreamType) 通过 FilterLinkCallback 向下游传递 outputBufferQueueProducer_；OnLinkedResult 接收 AVBufferQueueProducer 引用"
  - source: services/media_engine/filters/metadata_filter.cpp
    lines: "220-245"
    anchor: "DoStart()/DoPause()/DoResume()/DoStop() 生命周期：isStop_ 布尔控制采集启停；Pause 时补偿 latestPausedTime_；Resume 时启用 totalPausedTime_ 累加"
related_memories: |
  - MEM-ARCH-AVCODEC-S26 (AudioCaptureFilter)：同为录制管线采集 Filter，互补
  - MEM-ARCH-AVCODEC-S28 (VideoCaptureFilter)：同为录制管线视频采集 Filter
  - MEM-ARCH-AVCODEC-S34 (MuxerFilter)：MetaDataFilter 的下游终点
  - MEM-ARCH-AVCODEC-S32 (VideoRenderFilter)：播放管线输出 Filter，对称结构
summary: |
  MetaDataFilter（"builtin.recorder.timed_metadata"）是录制管线的元数据通道 Filter，工作在 Surface 模式下，
  将 SurfaceBuffer 中的 timeStamp/dataSize 注入到 AVBufferQueue 中供下游 MuxerFilter 使用。
  核心能力：Surface 绑定（SetInputMetaSurface）、PTS 计算（timestamp-startBufferTime-totalPausedTime）、
  暂停时间补偿（totalPausedTime_ 累加）、MetaDataFilterLinkCallback 三路回调。
context: |
  在录制管线中，MetaDataFilter 通常位于 VideoCaptureFilter/AudioCaptureFilter 之后、MuxerFilter 之前，
  用于将 Surface 层的时戳元数据（时间戳、数据大小）注入到 AVBuffer 流中，确保 Muxer 在封装时能够
  正确设置 PTS（Presentation Time Stamp）。与 AudioCaptureFilter（S26）并列构成录制管线的辅助数据通道。
  暂停补偿机制确保暂停前后 PTS 连续性。
---
