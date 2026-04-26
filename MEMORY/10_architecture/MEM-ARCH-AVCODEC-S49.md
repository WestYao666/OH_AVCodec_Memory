---
id: MEM-ARCH-AVCODEC-S49
title: SubtitleSinkFilter 字幕渲染过滤器——SubtitleSink 引擎与 Filter 两层架构
scope: [AVCodec, MediaEngine, Filter, Subtitle, SubtitleSink, SubtitleSinkFilter, FILTERTYPE_SSINK, PlayerPipeline, MediaSync, TextTag]
status: draft
author: builder-agent
created_at: "2026-04-26T12:40:00+08:00"
type: architecture_fact
confidence: high
summary: >
  SubtitleSinkFilter 是播放管线（PlayerPipeline）的字幕渲染终点，内部委托 SubtitleSink 核心引擎。
  SubtitleSink 继承 MediaSynchronousSink（与 AudioSinkFilter/VideoRenderFilter 同级同步终点），
  运行独立的 RenderLoop 线程从 AVBufferQueue 消费字幕缓冲区，通过 CalcWaitTime/PTS 计算显示时机，
  使用 RemoveTextTags/ParseTag 剥离 HTML 标签后通过 Tag::SUBTITLE_TEXT 上报给应用。
  SubtitleSink 支持 WAIT/SHOW/DROP 三状态字幕队列，与 MediaSyncManager 同步（SetSyncCenter/DoSyncWrite），
  在 Seek 时 NotifySeek 清空字幕队列。与 DemuxerFilter(S41) 的字幕轨输出和 AudioSinkFilter(S31) 的音频渲染终点对称。
evidence_sources:
  - local_repo: /home/west/av_codec_repo
  - services/media_engine/filters/subtitle_sink_filter.cpp        # 234行，Filter层封装，AutoRegisterFilter("builtin.player.subtitlesink", FILTERTYPE_SSINK)
  - services/media_engine/filters/subtitle_sink_filter.h
  - services/media_engine/modules/sink/subtitle_sink.cpp            # 420+行，SubtitleSink 核心引擎，RenderLoop/SubtitleInfo/TextTag处理
  - interfaces/inner_api/native/subtitle_sink.h                     # SubtitleSink 类定义，SubtitleInfo/SubtitleBufferState枚举
  - interfaces/inner_api/native/subtitle_sink_filter.h
  - interfaces/plugin/source_plugin.h                               # MEDIA_TYPE_SUBTITLE 定义
related_scenes: [新需求开发, 问题定位, 字幕显示问题, 播放器问题定位]
why_it_matters: >
  SubtitleSinkFilter 是播放管线的字幕终点，与 AudioSinkFilter(S31)/VideoRenderFilter(S32) 并列构成管线三大输出终点。
  当字幕不显示、显示时机错误、格式解析失败时，需定位到此层。
---

# SubtitleSinkFilter 字幕渲染过滤器——SubtitleSink 引擎与 Filter 两层架构

> **Builder 验证记录（2026-04-26）**：基于本地仓库 `/home/west/av_codec_repo` 代码验证。
> 代码路径均来自本地镜像，与 GitCode master 分支同步。

## 1. 概述

SubtitleSinkFilter 是 **PlayerPipeline** 的字幕渲染终点，封装在 Filter 层（`builtin.player.subtitlesink`, `FilterType::FILTERTYPE_SSINK`），
内部核心逻辑委托给 `SubtitleSink`（`modules/sink/subtitle_sink.cpp`）。

**关键文件路径锚点**：

```
subtitle_sink_filter.cpp:34-37   // AutoRegisterFilter("builtin.player.subtitlesink", FILTERTYPE_SSINK)
subtitle_sink_filter.cpp:54-59   // SubtitleSinkFilter 构造，创建 SubtitleSink
subtitle_sink.cpp:65-68          // NotifySeek() 字幕队列清空
subtitle_sink.cpp:286-320        // RenderLoop() 主循环，WAIT/SHOW/DROP 三状态
subtitle_sink.cpp:334-347        // CalcWaitTime() PTS时间计算
subtitle_sink.cpp:483-520        // RemoveTextTags() HTML标签剥离
subtitle_sink.cpp:373-381        // NotifyRender() 字幕上报 Tag::SUBTITLE_TEXT
subtitle_sink.h:120              // SubtitleBufferState 枚举：WAIT/SHOW/DROP
```

## 2. 两层架构

### 2.1 Filter 层：SubtitleSinkFilter

**注册信息**：
```cpp
// subtitle_sink_filter.cpp:34-37
static AutoRegisterFilter<SubtitleSinkFilter> g_registerSubtitleSinkFilter("builtin.player.subtitlesink",
    FilterType::FILTERTYPE_SSINK, [](const std::string& name, const FilterType type) {
        return std::make_shared<SubtitleSinkFilter>(name, FilterType::FILTERTYPE_SSINK);
    });
```

**类继承**：`SubtitleSinkFilter : public Filter`

**核心成员**：
```cpp
// subtitle_sink_filter.h
std::shared_ptr<SubtitleSink> subtitleSink_;  // 核心引擎
std::shared_ptr<EventReceiver> eventReceiver_;
std::shared_ptr<FilterCallback> filterCallback_;
std::shared_ptr<InterruptMonitor> interruptMonitor_;
```

**生命周期方法**：
| 方法 | 调用时机 | 内部操作 |
|------|---------|---------|
| `DoInitAfterLink()` | Filter 链路建立后 | `subtitleSink_->SetParameter(globalMeta_)` + `subtitleSink_->Init(trackMeta_, eventReceiver_)` |
| `DoPrepare()` | 管线准备阶段 | `subtitleSink_->Prepare()` + 获取 `AVBufferQueueConsumer` |
| `DoStart()` | 管线启动 | `subtitleSink_->Start()` |
| `DoFreeze()` / `DoUnFreeze()` | 管线暂停/恢复 | `subtitleSink_->Pause()` / `subtitleSink_->Resume()` |
| `DoFlush()` | Seek时 | `subtitleSink_->Flush(isSeekFlush)` |
| `DoStop()` | 管线停止 | `subtitleSink_->Stop()` |

**证据文件**：
- `subtitle_sink_filter.cpp:54-59` — 构造，SubtitleSink 实例创建
- `subtitle_sink_filter.cpp:86-89` — DoInitAfterLink 两步初始化
- `subtitle_sink_filter.cpp:94-106` — DoPrepare + AVBufferQueueConsumer 获取
- `subtitle_sink_filter.cpp:108-121` — DoStart 启动底层引擎

### 2.2 引擎层：SubtitleSink

**类继承**：`SubtitleSink : public std::enable_shared_from_this<SubtitleSink>, public Pipeline::MediaSynchronousSink`

**SubtitleInfo 结构**（`subtitle_sink.h:62-81`）：
```cpp
struct SubtitleInfo {
    std::string text_;      // 剥离标签后的纯文本
    int64_t pts_;          // 显示时间戳（微秒）
    int64_t duration_;     // 持续时间（微秒）
    std::shared_ptr<AVBuffer> buffer_; // 原始缓冲区引用
};
```

**SubtitleBufferState 枚举**（`subtitle_sink.h:120`）：
```cpp
enum SubtitleBufferState : uint32_t {
    WAIT,   // 等待显示时机
    SHOW,   // 当前显示字幕
    DROP,   // 已过期丢弃
};
```

**证据文件**：
- `subtitle_sink.h:62-81` — SubtitleInfo 结构
- `subtitle_sink.h:120` — SubtitleBufferState 枚举

## 3. RenderLoop 字幕渲染主循环

**函数签名**：`void SubtitleSink::RenderLoop()`

**主循环逻辑**（`subtitle_sink.cpp:286-320`）：
```cpp
// 行 286: RenderLoop 入口
void SubtitleSink::RenderLoop()
{
    while (!isThreadExit_) {
        // 行 302: 计算等待时间
        int64_t waitTime = static_cast<int64_t>(CalcWaitTime(subtitleInfo));
        if (waitTime > 0) {
            // 等待指定时间后重新评估
        }
        // 行 311: 判断动作（WAIT/SHOW/DROP）
        auto actionToDo = ActionToDo(subtitleInfo);
        switch (actionToDo) {
            case SubtitleBufferState::WAIT: // 继续等待
            case SubtitleBufferState::SHOW: // 渲染字幕
            case SubtitleBufferState::DROP: // 丢弃
        }
    }
}
```

**CalcWaitTime**（`subtitle_sink.cpp:334-347`）：根据 PTS 和当前播放时间计算距离字幕显示的毫秒数。
**ActionToDo**（`subtitle_sink.cpp:347-365`）：判断当前字幕应 WAIT/SHOW/DROP。

**证据文件**：
- `subtitle_sink.cpp:286-320` — RenderLoop 主循环
- `subtitle_sink.cpp:334-347` — CalcWaitTime 计算等待时间
- `subtitle_sink.cpp:347-365` — ActionToDo 三状态判断

## 4. 文本标签处理（TextTag Stripping）

**RemoveTextTags**（`subtitle_sink.cpp:483-520`）：解析 HTML/XML 标签（如 `<b>`, `<i>`, `<font>`）并剥离，保留纯文本内容。
**ParseTag**（`subtitle_sink.cpp:426-450`）：单标签解析，支持开标签和闭标签（`isClosing` 标志）。

**关键行为**：
- 非字幕标签（如样式标签）被剥离
- 闭标签（`</tag>`）触发出栈匹配
- 无法识别的标签被还原为原始文本

**证据文件**：
- `subtitle_sink.cpp:483-520` — RemoveTextTags HTML 标签剥离
- `subtitle_sink.cpp:426-450` — ParseTag 单标签解析

## 5. 字幕上报（NotifyRender）

**函数签名**：`void SubtitleSink::NotifyRender(SubtitleInfo &subtitleInfo)`

**关键行为**（`subtitle_sink.cpp:373-381`）：
```cpp
void SubtitleSink::NotifyRender(SubtitleInfo &subtitleInfo)
{
    Meta format;
    (void)format.PutStringValue(Tag::SUBTITLE_TEXT, subtitleInfo.text_);     // 行 376：纯文本内容
    (void)format.PutIntValue(Tag::SUBTITLE_PTS, Plugins::Us2Ms(subtitleInfo.pts_));      // 行 377：PTS（毫秒）
    (void)format.PutIntValue(Tag::SUBTITLE_DURATION, Plugins::Us2Ms(subtitleInfo.duration_)); // 行 378：持续时间
    // 通过 EventReceiver 或 FilterCallback 上报给应用层
}
```

**证据文件**：
- `subtitle_sink.cpp:373-381` — NotifyRender 三字段上报

## 6. MediaSync 同步集成

**关键方法**：
```cpp
// subtitle_sink.cpp:399: 设置同步中心
void SubtitleSink::SetSyncCenter(std::shared_ptr<Pipeline::MediaSyncManager> syncCenter)

// subtitle_sink.cpp:417: 获取媒体时间
int64_t SubtitleSink::GetMediaTime()
{
    auto syncCenter = syncCenter_.lock();
    if (syncCenter) {
        int64_t clockTime;
        syncCenter->GetTime(clockTime);  // 从 MediaSyncManager 获取当前播放时间
    }
}

// subtitle_sink.cpp:368: 同步写入（MediaSynchronousSink 接口实现）
int64_t SubtitleSink::DoSyncWrite(const std::shared_ptr<OHOS::Media::AVBuffer> &buffer, int64_t& actionClock)
```

**证据文件**：
- `subtitle_sink.cpp:399-401` — SetSyncCenter
- `subtitle_sink.cpp:417-423` — GetMediaTime
- `subtitle_sink.cpp:368-371` — DoSyncWrite

## 7. Seek 时的字幕队列清空

**NotifySeek**（`subtitle_sink.cpp:65-68`）：
```cpp
void SubtitleSink::NotifySeek()
{
    std::lock_guard<std::mutex> lock(mutex_);
    subtitleInfoVec_.clear();  // 清空所有字幕信息
    latestBufferPts_ = HST_TIME_NONE;
}
```

**证据文件**：
- `subtitle_sink.cpp:65-68` — NotifySeek 队列清空

## 8. 与 Filter Pipeline 的关系

```
PlayerPipeline
  SourcePlugin (S38)
    └─ DemuxerFilter (S41)
         ├─ [Video Track] → DecoderSurfaceFilter (S46) / SurfaceDecoderFilter (S45)
         ├─ [Audio Track] → AudioDecoderFilter (S35) → AudioSinkFilter (S31)
         └─ [Subtitle Track] → SubtitleSinkFilter (S49) ← 本条目
```

SubtitleSinkFilter 是管线中唯一处理字幕轨的 Filter，与 AudioSinkFilter(S31)/VideoRenderFilter(S32) 并列构成管线三大输出终点。

## 9. 与现有 S 系列的关系

| 已有主题 | 与 S49 的关系 |
|---------|--------------|
| S31（AudioSinkFilter） | 同级同步终点，AudioSinkFilter 渲染音频，S49 渲染字幕 |
| S32（VideoRenderFilter） | 同级同步终点，VideoRenderFilter 渲染视频，S49 渲染字幕 |
| S41（DemuxerFilter） | DemuxerFilter 解封装出字幕轨（MEDIA_TYPE_SUBTITLE），输出给 SubtitleSinkFilter |
| S26（AudioCaptureFilter） | S26 的 SubtitleSink 部分是录制管线字幕渲染，S49 是播放管线字幕渲染 |
| S22（MediaSyncManager） | SubtitleSink 通过 SetSyncCenter/DoSyncWrite 与 MediaSyncManager 同步 |

## 10. 关键行号锚点速查

| 描述 | 文件 | 行号 |
|------|------|------|
| Filter 注册 | `subtitle_sink_filter.cpp` | 34-37 |
| SubtitleSinkFilter 构造 | `subtitle_sink_filter.cpp` | 54-59 |
| DoInitAfterLink 两步初始化 | `subtitle_sink_filter.cpp` | 86-89 |
| DoPrepare AVBufferQueue | `subtitle_sink_filter.cpp` | 94-106 |
| NotifySeek 清空队列 | `subtitle_sink.cpp` | 65-68 |
| RenderLoop 主循环 | `subtitle_sink.cpp` | 286-320 |
| CalcWaitTime | `subtitle_sink.cpp` | 334-347 |
| ActionToDo | `subtitle_sink.cpp` | 347-365 |
| RemoveTextTags | `subtitle_sink.cpp` | 483-520 |
| ParseTag | `subtitle_sink.cpp` | 426-450 |
| NotifyRender | `subtitle_sink.cpp` | 373-381 |
| SetSyncCenter | `subtitle_sink.cpp` | 399-401 |
| GetMediaTime | `subtitle_sink.cpp` | 417-423 |
| DoSyncWrite | `subtitle_sink.cpp` | 368-371 |
| SubtitleInfo 结构 | `subtitle_sink.h` | 62-81 |
| SubtitleBufferState | `subtitle_sink.h` | 120 |
| MEDIA_TYPE_SUBTITLE | `interfaces/plugin/source_plugin.h` | 40 |
