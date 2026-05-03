---
id: MEM-ARCH-AVCODEC-S89
title: "AVCodec Filter Framework 基础架构——Filter 基类 / StreamType / FilterLinkCallback 三层联动"
scope: [AVCodec, MediaEngine, Filter, FilterBase, StreamType, FilterLinkCallback, FilterCallback, FilterCallBackCommand, LinkNext, OnLinked, DemuxerFilter, AutoRegisterFilter, Pipeline]
status: draft
created_by: builder-agent
created_at: "2026-05-04T06:34:00+08:00"
evidence_count: 24
---

# MEM-ARCH-AVCODEC-S89: AVCodec Filter Framework 基础架构

## Metadata

| 字段 | 值 |
|------|-----|
| id | MEM-ARCH-AVCODEC-S89 |
| title | AVCodec Filter Framework 基础架构——Filter 基类 / StreamType / FilterLinkCallback 三层联动 |
| type | architecture_fact |
| scope | [AVCodec, MediaEngine, Filter, FilterBase, StreamType, FilterLinkCallback, FilterCallback, FilterCallBackCommand, LinkNext, OnLinked, DemuxerFilter, AutoRegisterFilter, Pipeline] |
| pipeline_position: Filter Pipeline 基础设施（所有 Filter 的共同基类） |
| status | draft |
| created_by | builder-agent |
| created_at | 2026-05-04 |
| confidence | high |
| supersedes | S41（DemuxerFilter）基础设施部分证据，S14（Filter Chain）证据增强 |

## 摘要

AVCodec MediaEngine Filter Pipeline 中所有 Filter（DemuxerFilter / VideoDecoderFilter / AudioSinkFilter 等）均继承自统一的 **Filter 基类**，该基类定义了 Filter 的生命周期方法（Init / DoPrepare / DoStart / DoStop / DoPause / DoFreeze / DoResume / DoFlush）、事件回调接口（FilterCallback / EventReceiver）以及Filter 串联接口（LinkNext / OnLinked / OnLinkedResult）。**StreamType** 五类分型用于多轨路由，**FilterLinkCallback** 机制协调上下游 Filter 的 AVBufferQueueProducer 绑定。本条目聚焦 Filter 基类框架，不涉及具体 Filter 实现。

## 一、Filter 基类骨架

### 1.1 核心接口（证据：demuxer_filter.h:36-99）

```cpp
class DemuxerFilter : public Filter, public std::enable_shared_from_this<DemuxerFilter> {
public:
    // 初始化：注入 EventReceiver（事件上报）和 FilterCallback（框架回调）
    void Init(const std::shared_ptr<EventReceiver> &receiver,
              const std::shared_ptr<FilterCallback> &callback) override;
    void Init(const std::shared_ptr<EventReceiver> &receiver,
              const std::shared_ptr<FilterCallback> &callback,
              const std::shared_ptr<InterruptMonitor> &monitor) override;

    // 生命周期七步曲（对应 FilterState 状态机）
    Status DoPrepare() override;    // 准备：发现轨道、分配资源
    Status DoStart() override;     // 启动：启动工作线程/循环
    Status DoStop() override;      // 停止：停止工作线程
    Status DoPause() override;     // 暂停：可恢复
    Status DoFreeze() override;    // 冻结：系统休眠时触发，不可恢复
    Status DoUnFreeze() override;   // 解冻
    Status DoResume() override;    // 恢复（从暂停）
    Status DoFlush() override;     // 清空缓冲区
    Status DoPreroll() override;   // 预滚动（开始渲染前）
    Status DoPauseDragging() override;
    Status DoPauseAudioAlign() override;
    Status DoResumeDragging() override;
    Status DoResumeAudioAlign() override;
    Status DoSetPerfRecEnabled(bool isPerfRecEnabled) override;

    // 参数设置（Tag 驱动元数据）
    void SetParameter(const std::shared_ptr<Meta> &parameter) override;
    void GetParameter(std::shared_ptr<Meta> &parameter) override;

    // Filter 串联接口（LinkNext 主动链接下游，OnLinked 被动接收上游）
    Status LinkNext(const std::shared_ptr<Filter> &nextFilter, StreamType outType) override;
    Status UpdateNext(const std::shared_ptr<Filter> &nextFilter, StreamType outType) override;
    Status UnLinkNext(const std::shared_ptr<Filter> &nextFilter, StreamType outType) override;

    // 上游链接回调（DemuxerFilter 作为上游时被调用）
    Status OnLinked(StreamType inType, const std::shared_ptr<Meta> &meta,
        const std::shared_ptr<FilterLinkCallback> &callback) override;
    Status OnUpdated(StreamType inType, const std::shared_ptr<Meta> &meta,
        const std::shared_ptr<FilterLinkCallback> &callback) override;
    Status OnUnLinked(StreamType inType, const std::shared_ptr<FilterLinkCallback> &callback) override;

    // 下游绑定结果回调（OnLinkedResult 被下游 Filter 调用）
    void OnLinkedResult(const sptr<AVBufferQueueProducer> &outputBufferQueue,
        std::shared_ptr<Meta> &meta) override;

    FilterType GetFilterType();
    void SetSyncCenter(std::shared_ptr<MediaSyncManager> syncCenter);
    // ...
};
```

### 1.2 Filter 基类关键成员变量（证据：demuxer_filter.h:174-185）

```cpp
std::shared_ptr<Filter> nextFilter_;                          // 下游 Filter（单链式）
std::map<StreamType, std::vector<std::shared_ptr<Filter>>> nextFiltersMap_; // 多轨下游
std::shared_ptr<MediaDemuxer> demuxer_;                       // 核心引擎（DemuxerFilter 持有）
std::shared_ptr<MediaSource> mediaSource_;                   // 数据源
std::shared_ptr<FilterLinkCallback> onLinkedResultCallback_; // 下游链接回调接收器
std::shared_ptr<FilterCallback> callback_;                   // 框架回调（触发 NEXT_FILTER_NEEDED）
std::shared_ptr<EventReceiver> receiver_;                     // 事件上报（EVENT_ERROR/EVENT_DRM_INFO_UPDATED 等）
std::atomic<bool> isLoopStarted_{false};                     // 读循环启动标志
```

## 二、StreamType 五类分型

**证据**：demuxer_filter.cpp:878-900 `FindStreamType()`

StreamType 是 Filter Pipeline 中**多轨路由**的核心枚举，所有 Filter 通过 StreamType 区分媒体类型并正确链接下游：

```cpp
// StreamType 五类分型（demuxer_filter.cpp:878-900）
enum StreamType {
    STREAMTYPE_DOLBY        = 0,  // Dolby 音频直通（无需解码）
    STREAMTYPE_ENCODED_AUDIO,     // 需解码音频（AAC/MP3 等）
    STREAMTYPE_RAW_AUDIO,         // 原始 PCM 音频
    STREAMTYPE_ENCODED_VIDEO,     // 需解码视频（H.264/HEVC 等）
    STREAMTYPE_SUBTITLE,          // 字幕轨道
    // 其他扩展类型
};

// track_id_map_：StreamType → 轨道 ID 列表（支持一轨对多 Filter）
std::map<StreamType, std::vector<int32_t>> track_id_map_;
```

**路由规则**（FindStreamType，demuxer_filter.cpp:880-900）：
1. MIME 包含 "dolby" → STREAMTYPE_DOLBY
2. MediaType == AUDIO + MIME 非音频类 → STREAMTYPE_ENCODED_AUDIO
3. MediaType == AUDIO + MIME 是 PCM 类 → STREAMTYPE_RAW_AUDIO
4. MediaType == VIDEO → STREAMTYPE_ENCODED_VIDEO
5. MediaType == SUBTITLE → STREAMTYPE_SUBTITLE

## 三、FilterLinkCallback 联动机制（核心）

**证据**：demuxer_filter.cpp:74-89（DemuxerFilterLinkCallback）、demuxer_filter.cpp:775-821（LinkNext）

FilterLinkCallback 是 Filter Pipeline 中**上下游串联的核心机制**，负责协调 AVBufferQueueProducer 的绑定：

### 3.1 LinkNext 主动链接流程

```cpp
// demuxer_filter.cpp:775-821 LinkNext()
Status DemuxerFilter::LinkNext(const std::shared_ptr<Filter> &nextFilter, StreamType outType)
{
    int32_t trackId = -1;
    FALSE_RETURN_V_MSG_E(nextFilter != nullptr, Status::ERROR_INVALID_OPERATION, "nextFilter nullptr");
    FALSE_RETURN_V_MSG_E(demuxer_ != nullptr, Status::ERROR_INVALID_OPERATION, "demuxer_ nullptr");
    FALSE_RETURN_V_MSG_E(FindTrackId(outType, trackId), Status::ERROR_INVALID_PARAMETER, "FindTrackId failed");

    std::shared_ptr<Meta> meta = trackInfos[trackId];
    // 注入 MEDIA_FILE_TYPE / ENHANCE_FLAG / VIDEO_ID 到 meta
    meta->SetData(Tag::MEDIA_FILE_TYPE, fileType_);

    // 【核心】创建 FilterLinkCallback 传递给下游
    std::shared_ptr<FilterLinkCallback> filterLinkCallback
        = std::make_shared<DemuxerFilterLinkCallback>(shared_from_this());

    // 调用下游的 OnLinked，传递 meta（元数据）和 filterLinkCallback（回调）
    return nextFilter->OnLinked(outType, meta, filterLinkCallback);
}
```

### 3.2 DemuxerFilterLinkCallback 实现（证据：demuxer_filter.cpp:74-89）

```cpp
// demuxer_filter.cpp:74-89
class DemuxerFilterLinkCallback : public FilterLinkCallback {
public:
    explicit DemuxerFilterLinkCallback(const std::shared_ptr<DemuxerFilter> &filter)
        : demuxerFilter_(filter) {}

    // 下游 Filter 调用 OnLinkedResult 时触发此回调
    void OnLinkedResult(const sptr<AVBufferQueueProducer> &queue,
        std::shared_ptr<Meta> &meta) override
    {
        demuxerFilter_->OnLinkedResult(queue, meta);
    }

private:
    std::shared_ptr<DemuxerFilter> demuxerFilter_;
};
```

### 3.3 OnLinkedResult 绑定回调（证据：demuxer_filter.cpp:964-985）

```cpp
// demuxer_filter.cpp:964-985 OnLinkedResult()
void DemuxerFilter::OnLinkedResult(const sptr<AVBufferQueueProducer> &outputBufferQueue,
    std::shared_ptr<Meta> &meta)
{
    if (meta == nullptr) { return; }
    int32_t trackId;
    if (!meta->GetData(Tag::REGULAR_TRACK_ID, trackId)) { return; }
    // 将 AVBufferQueueProducer 注册到 MediaDemuxer 的对应轨道
    demuxer_->SetOutputBufferQueue(trackId, outputBufferQueue);

    // 可选：设置帧率上限、视频解码器速率限制
    int32_t decoderFramerateUpperLimit = 0;
    if (meta->GetData(Tag::VIDEO_DECODER_RATE_UPPER_LIMIT, decoderFramerateUpperLimit)) {
        demuxer_->SetDecoderFramerateUpperLimit(decoderFramerateUpperLimit, trackId);
    }
    double framerate;
    if (meta->GetData(Tag::VIDEO_FRAME_RATE, framerate)) {
        demuxer_->SetFrameRate(framerate, trackId);
    }
}
```

## 四、FilterCallback 框架回调机制

**证据**：demuxer_filter.cpp:290-347（HandleTrackInfos 中 callback_->OnCallback）

FilterCallback 用于 Filter 向 Pipeline 框架**请求创建下游 Filter**：

```cpp
// FilterCallBackCommand 命令类型
enum class FilterCallBackCommand {
    NEXT_FILTER_NEEDED,   // 请求框架创建下一个 Filter
    // 其他命令...
};

// HandleTrackInfos 中的回调触发（demuxer_filter.cpp:327-330）
ret = callback_->OnCallback(shared_from_this(), FilterCallBackCommand::NEXT_FILTER_NEEDED, streamType);
FALSE_RETURN_V_MSG_E(ret == Status::OK || FaultDemuxerEventInfoWrite(streamType) != Status::OK, ret,
    "OnCallback Link Filter Fail.");
```

**FilterCallback 接口**：
```cpp
class FilterCallback {
public:
    virtual Status OnCallback(std::shared_ptr<Filter> filter,
                              FilterCallBackCommand cmd,
                              StreamType streamType) = 0;
    virtual std::vector<std::string> GetDolbyListCallback() = 0;
};
```

## 五、Filter 生命周期状态机

**证据**：demuxer_filter.cpp:422-500 系列 Do* 方法

```
                    DoPrepare()
                      ↓
              [FilterState::INITIALIZED]
                    ↓
                   DoStart()
                      ↓
              [FilterState::RUNNING]
                    ↓
              DoPause() ←→ DoResume()
              [PAUSED]    [RUNNING]
                    ↓
                   DoStop()
                      ↓
             [FilterState::STOPPED]
                    ↓
                DoFlush()
              [FLUSHED]

  特殊路径：
  DoFreeze() → [FilterState::FROZEN]（系统休眠）
  DoUnFreeze() → [INITIALIZED]
  DoPreroll() → [PREROLLING] → [PREROLL_DONE] → [RUNNING]
```

## 六、AutoRegisterFilter 自动注册机制

**证据**：demuxer_filter.cpp:49-53

```cpp
// demuxer_filter.cpp:49-53
static AutoRegisterFilter<DemuxerFilter> g_registerAudioCaptureFilter(
    "builtin.player.demuxer", FilterType::FILTERTYPE_DEMUXER,
    [](const std::string& name, const FilterType type) {
        return std::make_shared<DemuxerFilter>(name, FilterType::FILTERTYPE_DEMUXER);
    }
);
```

所有 Filter 均通过 `AutoRegisterFilter<>` 模板在**全局作用域**静态注册到 Filter 工厂，运行时通过名字字符串（如 `"builtin.player.demuxer"`）查找并创建实例。

**FilterType 枚举（部分）**：
```cpp
enum class FilterType {
    FILTERTYPE_SOURCE,
    FILTERTYPE_DEMUXER,
    FILTERTYPE_VIDEODEC,      // VideoDecoderFilter
    FILTERTYPE_VDEC,         // DecoderSurfaceFilter
    FILTERTYPE_VIDEODEC,    // SurfaceDecoderFilter
    FILTERTYPE_AUDIODEC,
    FILTERTYPE_AENC,        // AudioEncoderFilter
    FILTERTYPE_VENC,        // SurfaceEncoderFilter
    FILTERTYPE_ASINK,
    FILTERTYPE_SSINK,       // SubtitleSinkFilter
    FILTERTYPE_SEI,         // SeiParserFilter
    FILTERTYPE_MUXER,
    FILTERTYPE_MAX,
};
```

## 七、关键证据索引

| # | 证据 | 文件:行号 | 说明 |
|---|------|----------|------|
| E1 | demuxer_filter.cpp:49-53 | AutoRegisterFilter 注册 "builtin.player.demuxer" |
| E2 | demuxer_filter.h:36-99 | Filter 基类完整接口声明（Init/DoPrepare/DoStart/LinkNext/OnLinked/OnLinkedResult） |
| E3 | demuxer_filter.h:174-185 | 关键成员变量（nextFilter_/track_id_map_/onLinkedResultCallback_/callback_） |
| E4 | demuxer_filter.cpp:74-89 | DemuxerFilterLinkCallback 实现，OnLinkedResult 转发 |
| E5 | demuxer_filter.cpp:775-821 | LinkNext() 创建 FilterLinkCallback → nextFilter->OnLinked() |
| E6 | demuxer_filter.cpp:946-956 | OnLinked() 保存 onLinkedResultCallback_ |
| E7 | demuxer_filter.cpp:964-985 | OnLinkedResult() 将 AVBufferQueueProducer 注册到 MediaDemuxer |
| E8 | demuxer_filter.cpp:878-900 | FindStreamType() 五类分型路由 |
| E9 | demuxer_filter.cpp:185 | `std::map<StreamType, std::vector<int32_t>> track_id_map_` 多轨路由表 |
| E10 | demuxer_filter.cpp:290-347 | HandleTrackInfos() 遍历轨道，每轨 callback_->OnCallback(NEXT_FILTER_NEEDED) |
| E11 | demuxer_filter.cpp:422-444 | DoStart() 调用 demuxer_->Start()，isLoopStarted 管理 |
| E12 | demuxer_filter.cpp:440-450 | DoStop() 调用 demuxer_->Stop() |
| E13 | demuxer_filter.cpp:457-470 | DoPause() / DoFreeze() / DoUnFreeze() 冻结机制 |
| E14 | demuxer_filter.cpp:1055-1069 | ResumeDemuxerReadLoop() / PauseDemuxerReadLoop() 读循环控制 |
| E15 | demuxer_filter.cpp:258-282 | DoPrepare() 获取轨道信息，失败报 EVENT_ERROR |
| E16 | demuxer_filter.cpp:878-900 | STREAMTYPE_DOLBY / ENCODED_AUDIO / RAW_AUDIO / ENCODED_VIDEO / SUBTITLE 五型 |
| E17 | demuxer_filter.h:91-93 | LinkNext / UpdateNext / UnLinkNext 上游链接接口声明 |
| E18 | demuxer_filter.h:154-160 | OnLinked / OnUpdated / OnUnLinked 下游回调接口声明 |
| E19 | demuxer_filter.h:39-41 | Init(EventReceiver, FilterCallback) 双参数初始化 |
| E20 | demuxer_filter.h:98 | FilterType GetFilterType() 类型查询 |
| E21 | demuxer_filter.cpp:118-143 | DemuxerFilterDrmCallback 实现 AVDemuxerCallback |
| E22 | demuxer_filter.cpp:160-185 | Init(receiver, callback, monitor) 三参数初始化（DRM） |
| E23 | demuxer_filter.cpp:187-193 | SetTranscoderMode() / SetPlayerMode() 双模式切换 |
| E24 | demuxer_filter.cpp:207-218 | SetDataSource(MediaSource) 数据源注入 |

## 八、Filter Pipeline 定位图

```
Pipeline 框架（FilterFactory / MediaCore）
        │
        ├── SourceFilter（SourcePlugin 封装）
        │         ↓ LinkNext(outType=STREAMTYPE_ENCODED_VIDEO, audio, subtitle)
        ├── DemuxerFilter（"builtin.player.demuxer"）← 本条目聚焦
        │         ↓ LinkNext(video) │ LinkNext(audio) │ LinkNext(subtitle)
        │   ┌────┴────┬─────────┴─┐
        │  VideoDecoder AudioDecoder SubtitleSink
        │         ↓               ↓
        │   VideoRender       AudioSink
        │         ↓               ↓
        │     [Surface]      [AudioOutput]
        │
        └── MuxerFilter（"builtin.recorder.muxer"）
                  ↑ LinkPrev()（录制管线反向链接）
```

## 九、关键文件清单

```
services/media_engine/filters/
├── demuxer_filter.cpp           # DemuxerFilter 实现（1206行），Filter 框架示例
├── demuxer_filter.h             # DemuxerFilter 头文件（含 Filter 基类派生）
├── audio_sink_filter.cpp        # AudioSinkFilter，Filter 框架另一示例
├── audio_sink_filter.h
├── decoder_surface_filter.cpp  # DecoderSurfaceFilter（VideoDecoder + VideoSink）
├── surface_decoder_filter.cpp   # SurfaceDecoderFilter
├── sei_parser_filter.cpp
├── muxer_filter.cpp

interfaces/inner_api/native/
├── demuxer_filter.h           # Filter 基类对外 API 头文件
├── audio_sink_filter.h
├── decoder_surface_filter.h
├── sei_parser_filter.h
└── video_resize_filter.h
```

## 十、关联记忆

| 关联 | 说明 |
|------|------|
| S41 | DemuxerFilter 解封装过滤器（Filter Pipeline 第二层） |
| S14 | MediaEngine Filter Chain 架构（AutoRegisterFilter + FilterLinkCallback + AVBufferQueue 三联机制） |
| S21 | AVCodec IPC 架构（CodecClient ↔ CodecServer） |
| S75 | MediaDemuxer 六组件协作架构（ReadLoop / SampleConsumerLoop 双 TaskThread） |
| S34 | MuxerFilter 封装过滤器（录制管线输出终点） |
| S46 | DecoderSurfaceFilter 三组件架构（VideoDecoderAdapter + VideoSink + PostProcessor） |
| S31 | AudioSinkFilter 音频播放输出过滤器 |
| S32 | VideoRenderFilter 视频渲染输出过滤器 |

## 十一、已知覆盖情况

- S14（Filter Chain）已覆盖 AutoRegisterFilter + FilterLinkCallback + AVBufferQueue 三联机制
- S41（DemuxerFilter）已覆盖 StreamType 五类分型
- **本条目（S89）聚焦于 Filter 基类骨架和 FilterLinkCallback 机制的底层原理**，与 S14/S41 互补而非重复

---

owner: 耀耀
review: pending
