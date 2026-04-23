---
type: architecture
id: MEM-ARCH-AVCODEC-S14
status: draft
topic: MediaEngine Filter Chain 架构——AutoRegisterFilter + FilterLinkCallback + AVBufferQueue 三联数据流
created_at: "2026-04-24T00:30:00+08:00"
evidence: |
  - source: /home/west/av_codec_repo/services/media_engine/filters/sei_parser_filter.cpp
    anchor: "Line 44-47: static AutoRegisterFilter<SeiParserFilter> g_registerSeiParserFilter('builtin.player.seiParser', FilterType::FILTERTYPE_SEI)"
  - source: /home/west/av_codec_repo/services/media_engine/filters/demuxer_filter.cpp
    anchor: "Line 60-64: static AutoRegisterFilter<DemuxerFilter> g_registerAudioCaptureFilter('builtin.player.demuxer', FilterType::FILTERTYPE_DEMUXER)"
  - source: /home/west/av_codec_repo/services/media_engine/filters/video_resize_filter.cpp
    anchor: "Line 44-48: static AutoRegisterFilter<VideoResizeFilter> g_registerVideoResizeFilter('builtin.transcoder.videoresize', FilterType::FILTERTYPE_VIDRESIZE)"
  - source: /home/west/av_codec_repo/services/media_engine/filters/surface_decoder_filter.cpp
    anchor: "Line 37-42: static AutoRegisterFilter<SurfaceDecoderFilter> g_registerSurfaceDecoderFilter('builtin.player.surfacedecoder', FilterType::FILTERTYPE_VIDEODEC)"
  - source: /home/west/av_codec_repo/services/media_engine/filters/surface_decoder_filter.cpp
    anchor: "Line 349-353: nextFilter_->OnLinked(outType, configureParameter_, filterLinkCallback) // Filter A links to Filter B"
  - source: /home/west/av_codec_repo/services/media_engine/filters/surface_decoder_filter.cpp
    anchor: "Line 407-414: OnLinkedResult: onLinkedResultCallback_->OnLinkedResult(mediaCodec_->GetInputBufferQueue(), meta_) // Filter B returns producer"
  - source: /home/west/av_codec_repo/interfaces/inner_api/native/sei_parser_filter.h
    anchor: "class SeiParserFilter : public Filter, FilterType::FILTERTYPE_SEI; sptr<AVBufferQueueProducer> GetBufferQueueProducer(); sptr<AVBufferQueueConsumer> GetBufferQueueConsumer()"
  - source: /home/west/av_codec_repo/services/media_engine/filters/demuxer_filter.cpp
    anchor: "Line 964-980: OnLinkedResult: demuxer_->SetOutputBufferQueue(trackId, outputBufferQueue) // Demuxer writes decoded frames to the queue"
  - source: /home/west/av_codec_repo/services/media_engine/filters/sei_parser_filter.cpp
    anchor: "Line 100-140: PrepareInputBufferQueue + AVBufferAvailableListener + SetBufferAvailableListener // Consumer-side buffer available notification"
  - source: /home/west/av_codec_repo/services/media_engine/filters/video_resize_filter.cpp
    anchor: "Line 246-257: DoPrepare: filterCallback_->OnCallback(NEXT_FILTER_NEEDED, STREAMTYPE_RAW_VIDEO) // Filter requests next filter by stream type"
---

# MEM-ARCH-AVCODEC-S14: MediaEngine Filter Chain 架构

## Metadata

| 字段 | 值 |
|------|-----|
| id | MEM-ARCH-AVCODEC-S14 |
| title | MediaEngine Filter Chain 架构——AutoRegisterFilter + FilterLinkCallback + AVBufferQueue 三联数据流 |
| scope | [AVCodec, MediaEngine, Filter, FilterChain, Pipeline, AVBufferQueue] |
| status | draft |
| created_by | builder-agent |
| created_at | 2026-04-24 |
| type | architecture_fact |
| confidence | high |
| related_scenes | [新需求开发, 问题定位, Pipeline 扩展, 自定义 Filter 接入] |
| why_it_matters: |
  - 新需求开发：接入新的媒体处理 Filter（转码/SEI/缩放）需理解 Filter 注册与链接机制
  - 问题定位：Filter 链中数据流断点需通过 AVBufferQueue 日志排查链接是否成功
  - Pipeline 扩展：MediaEngine Filter 体系支持动态插入/替换 Filter（如 VideoResizeFilter）
  - 性能分析：Filter 间的 AVBufferQueue 是潜在瓶颈点（队列长度、ZME模式）

## 摘要

MediaEngine 的 Filter Chain 是 AVCodec 服务侧媒体处理 Pipeline 的核心架构，采用**三联机制**：

1. **AutoRegisterFilter<T>**：静态插件注册，每个 Filter 类型以单例工厂方式注册到 FilterFactory
2. **FilterLinkCallback**：点对点链接协议，通过 OnLinked/OnLinkedResult 握手建立 Filter 间的数据通道
3. **AVBufferQueue（Producer/Consumer）**：无锁队列，串联相邻 Filter，Buffer 在 Filter 间流动不过拷贝

整个 Filter Chain 在播放场景的典型拓扑为：

```
DemuxerFilter ("builtin.player.demuxer")
    → AVBufferQueue (video track)
    → SurfaceDecoderFilter ("builtin.player.surfacedecoder")
    → AVBufferQueue (decoded video)
    → [SeiParserFilter ("builtin.player.seiParser")]  // optional
    → AVBufferQueue (SEI info)
    → Surface (输出到显示)
```

## 核心机制详解

### 1. Filter 注册（AutoRegisterFilter）

每个 Filter 通过静态 `AutoRegisterFilter<T>` 对象在**编译时**注册到全局 FilterFactory：

```cpp
// sei_parser_filter.cpp
static AutoRegisterFilter<SeiParserFilter> g_registerSeiParserFilter(
    "builtin.player.seiParser",               // 注册名（全局唯一）
    FilterType::FILTERTYPE_SEI,              // FilterType 枚举
    [](const std::string& name, const FilterType type) {
        return std::make_shared<SeiParserFilter>(name, type);
    });
```

已知的注册名与 FilterType：

| 注册名 | FilterType | 说明 |
|--------|-----------|------|
| `"builtin.player.demuxer"` | FILTERTYPE_DEMUXER | 容器解封装 |
| `"builtin.player.surfacedecoder"` | FILTERTYPE_VIDEODEC | 视频解码 |
| `"builtin.player.seiParser"` | FILTERTYPE_SEI | SEI 信息解析 |
| `"builtin.transcoder.videoresize"` | FILTERTYPE_VIDRESIZE | 视频缩放/转码增强 |
| `"builtin.recorder.audiocapture"` | AUDIO_CAPTURE | 音频采集 |
| `"builtin.recorder.audiodatasource"` | AUDIO_DATA_SOURCE | 音频数据源 |
| `FilterType::FILTERTYPE_ASINK` | (audio sink) | 音频输出 |
| `FilterType::FILTERTYPE_VENC` | (video encoder) | 视频编码 |

FilterFactory 根据注册名动态创建 Filter 实例。

### 2. Filter 链接协议（FilterLinkCallback）

Filter 链接通过**双向握手**完成，以 Filter A（上游）链接 Filter B（下游）为例：

**Step 1：A 请求链接 B**
```cpp
// surface_decoder_filter.cpp Line 349-353
std::shared_ptr<FilterLinkCallback> filterLinkCallback =
    std::make_shared<SurfaceDecoderFilterLinkCallback>(shared_from_this());
nextFilter->OnLinked(outType, configureParameter_, filterLinkCallback);
```

**Step 2：B 处理链接并返回输入队列 Producer**
```cpp
// surface_decoder_filter.cpp Line 407-414
void SurfaceDecoderFilter::OnLinkedResult(
    const sptr<AVBufferQueueProducer> &outputBufferQueue,
    std::shared_ptr<Meta> &meta)
{
    if (onLinkedResultCallback_) {
        onLinkedResultCallback_->OnLinkedResult(
            mediaCodec_->GetInputBufferQueue(),  // B 的输入队列 Producer
            meta_);
    }
}
```

**Step 3：A 获知 B 的输入队列，开始发送 Buffer**
```cpp
// demuxer_filter.cpp Line 964-975
void DemuxerFilter::OnLinkedResult(
    const sptr<AVBufferQueueProducer> &outputBufferQueue,
    std::shared_ptr<Meta> &meta)
{
    demuxer_->SetOutputBufferQueue(trackId, outputBufferQueue); // A 获知 B 的输入队列
}
```

Filter 链接协议还支持 `OnUpdated`（Format 变更）和 `OnUnLinked`（断链）。

### 3. 数据流（AVBufferQueue）

相邻 Filter 通过共享的 `AVBufferQueue` 传递数据，**零拷贝**：

```
[A Filter]  --producer.write()-->  [AVBufferQueue]  --consumer.acquire()-->  [B Filter]
```

**Consumer 侧通知机制**：
```cpp
// sei_parser_filter.cpp Line 110-120
sptr<IConsumerListener> listener = new AVBufferAvailableListener(shared_from_this());
inputBufferQueueConsumer_->SetBufferAvailableListener(listener);
```

当 B 的输入队列有可用 Buffer 时，`AVBufferAvailableListener::OnBufferAvailable()` 被触发，调用 `ProcessInputBuffer()` 开始处理。

### 4. Filter 生命周期

每个 Filter 实现标准状态机：

```
CREATED → PREPARING → PREPARED → STARTING → RUNNING
                                        ↓
                               PAUSING ← PAUSED
                                        ↓
                               STOPPING ← STOPPED
                                        ↓
                                     RELEASED
```

对应的虚函数：`DoPrepare()` → `DoStart()` → `DoPause()` → `DoResume()` → `DoStop()` → `DoRelease()`

Filter 可通过 `filterCallback_->OnCallback(NEXT_FILTER_NEEDED, streamType)` 向 Pipeline 请求下一个 Filter。

## 典型播放 Pipeline 拓扑

```
[DemuxerFilter] ──video track queue──> [SurfaceDecoderFilter] ──decoded queue──> [Surface]
                                       │
                                       ├──> [SeiParserFilter] ──> [Player App] (SEI callback)
                                       │
                                       └──> [VideoResizeFilter] ──> [Surface] (VPE post-processing)
    
[DemuxerFilter] ──audio track queue──> [AudioDecoderFilter] ──PCM queue──> [AudioSinkFilter] ──> [Audio Output]
```

## 与其他组件的关系

| 组件 | 关系 | 说明 |
|------|------|------|
| CodecServer | 持有者 | CodecServer 是服务端 Codec 实例，FilterChain 是 MediaEngine 的 Pipeline |
| MediaCodec (API) | 上层 | MediaCodec 通过 CodecServer 间接使用 FilterChain |
| AVBufferQueue | 数据通道 | Filter 间不过拷贝，Buffer 引用传递 |
| FilterFactory | 注册中心 | 维护 "注册名 → Filter 创建函数" 的映射表 |
| VideoResizeFilter | 可选插件 | 使用 VPE（VideoProcessingEngine）进行超分/缩放 |
| SeiParserFilter | 可选插件 | 默认关闭，需 SetSeiMessageCbStatus 开启 |

## 已有记忆关联

- **MEM-ARCH-AVCODEC-S3**: CodecServer Pipeline 数据流与状态机（FilterChain 是 CodecServer 的下游 Pipeline）
- **MEM-ARCH-AVCODEC-S10**: SeiParserFilter SEI 解析过滤器（SeiParserFilter 是 FilterChain 中的一个处理节点）
- **MEM-ARCH-AVCODEC-S12**: VideoResizeFilter 转码增强过滤器（VideoResizeFilter 是 FilterChain 中的 VPE 处理节点）
- **MEM-ARCH-AVCODEC-006**: media_codec 编解码数据流（FilterChain 串联 Demuxer→Decoder→Surface 的完整路径）

## 待补充

- FilterFactory 的具体实现（如何根据注册名查找和创建 Filter 实例）
- `DoProcessInputBuffer` 在不同 Filter 中的具体实现差异
- Filter 链的错误传播机制（Filter 出错如何通知上下游）
- 动态 Filter 插入/替换的具体时机和实现（PipelineBuilder）
