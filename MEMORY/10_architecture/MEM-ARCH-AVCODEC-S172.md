---
type: architecture
id: MEM-ARCH-AVCODEC-S172
status: pending_approval
topic: HttpSourcePlugin 三路下载器工厂路由——DownloadMonitor装饰器 + Dash/Hls/HttpMediaDownloader 三路分发
scope: [AVCodec, MediaEngine, SourcePlugin, HttpSourcePlugin, DownloadMonitor, HLS, DASH, AdaptiveBitrate, SelectBitRate, AutoSelectBitRate, Decorator]
assoc_scenarios: [新需求开发/问题定位/流媒体播放/HLS-DASH自适应码率]
sources:
  - /home/west/av_codec_repo/services/media_engine/plugins/source/http_source/http_source_plugin.cpp (769行, 本地镜像)
  - /home/west/av_codec_repo/services/media_engine/plugins/source/http_source/http_source_plugin.h (115行, 本地镜像)
  - /home/west/av_codec_repo/services/media_engine/plugins/source/http_source/monitor/download_monitor.h (232行, 本地镜像)
  - /home/west/av_codec_repo/services/media_engine/plugins/source/http_source/monitor/download_monitor.cpp (610行, 本地镜像)
created_by: builder-agent
created_at: "2026-05-25T07:35:00+08:00"
updated_at: "2026-05-25T07:35:00+08:00"
evidence_source: local_mirror /home/west/av_codec_repo
evidence_count: 15
source_files: 4
git_branch: master
git_url: https://github.com/WestYao666/OH_AVCodec_Memory
summary: HttpSourcePlugin三路下载器工厂路由，DownloadMonitor装饰器模式，DASH/HLS/HTTP三路分发，SetDownloaderBySource路由核心，loaderCombinations_离线缓存，SelectBitRate/AutoSelectBitRate码率管理
review_status: pending_approval
---

# MEM-ARCH-AVCODEC-S172 — HttpSourcePlugin 三路下载器工厂路由

## Metadata

| Field | Value |
|-------|-------|
| mem_id | MEM-ARCH-AVCODEC-S172 |
| topic | HttpSourcePlugin 三路下载器工厂路由——DownloadMonitor装饰器 + Dash/Hls/HttpMediaDownloader 三路分发 |
| status | pending_approval |
| created | 2026-05-25T07:35:00+08:00 |
| builder | builder-agent |
| source | 本地镜像 /home/west/av_codec_repo |
| evidence | 15条行号级证据 |

---

## 一、架构概述

`HttpSourcePlugin` 是媒体源插件的 **HTTP/HTTPS 协议入口**，位于 `services/media_engine/plugins/source/http_source/`。

核心设计模式为 **装饰器模式 + 工厂路由**：
- `HttpSourcePlugin::SetDownloaderBySource` 是路由核心，根据媒体类型分发到三种下载器
- `DownloadMonitor` 作为装饰器（Decorator）包装所有下载器，添加离线缓存、限速、统计等横切能力
- 三路下载器：`DashMediaDownloader`（DASH）、`HlsMediaDownloader`（HLS）、`HttpMediaDownloader`（普通HTTP）

---

## 二、核心组件

### 2.1 HttpSourcePlugin 入口

**源码**：`http_source_plugin.cpp(769行) + http_source_plugin.h(115行)`

**Evidence [E1]** `http_source_plugin.h:28`：`HttpSourcePlugin` 类继承 `SourcePlugin`
```cpp
class __attribute__((visibility("default"))) HttpSourcePlugin : public SourcePlugin {
```

**Evidence [E2]** `http_source_plugin.cpp:229`：`ParseAndSetSource` 调用 `SetDownloaderBySource` 路由
```cpp
    SetDownloaderBySource(source);
```

**Evidence [E3]** `http_source_plugin.cpp:270`：`SetDownloaderBySource` 路由核心函数
```cpp
void HttpSourcePlugin::SetDownloaderBySource(std::shared_ptr<MediaSource> source)
```

### 2.2 DownloadMonitor 装饰器

**源码**：`download_monitor.h(232行) + download_monitor.cpp(610行)`

**Evidence [E4]** `download_monitor.h:43`：DownloadMonitor 双重继承装饰器
```cpp
class DownloadMonitor : public MediaDownloader, public std::enable_shared_from_this<DownloadMonitor> {
```

**Evidence [E5]** `download_monitor.h:45`：装饰器构造函数
```cpp
    explicit DownloadMonitor(std::shared_ptr<MediaDownloader> downloader) noexcept;
```

### 2.3 三路下载器

| 下载器 | 类型 | 路由条件 | 代码行 |
|--------|------|----------|--------|
| `DashMediaDownloader` | DASH MPD | `IsDash()` | cpp:287 |
| `HlsMediaDownloader` | HLS m3u8 | `IsHlsFmp4()` / `IsHls()` | cpp:297 / 310 |
| `HttpMediaDownloader` | 普通HTTP | fallback | cpp:319 |

---

## 三、路由决策链

### 3.1 SetDownloaderBySource 完整路由链

**Evidence [E6]** `http_source_plugin.cpp:287-290`：DASH 优先路由
```cpp
    if (IsDash()) {
        downloader_ = std::make_shared<DownloadMonitor>(
                      std::make_shared<DashMediaDownloader>(loaderCombinations_));
```

**Evidence [E7]** `http_source_plugin.cpp:297-300`：HLS fMP4 路由
```cpp
    } else if (IsSeekToTimeSupported() && mimeType_ != AVMimeTypes::APPLICATION_M3U8) {
        // ...
        downloader_ = std::make_shared<DownloadMonitor>(std::make_shared<HlsMediaDownloader>
                      (expectDuration, userDefinedDuration, httpHeader_, loaderCombinations_));
```

**Evidence [E8]** `http_source_plugin.cpp:310-313`：普通 HLS 路由
```cpp
    } else if (IsHls()) {
        downloader_ = std::make_shared<DownloadMonitor>(
            std::make_shared<HlsMediaDownloader>(mimeType_));
```

**Evidence [E9]** `http_source_plugin.cpp:319-322`：普通 HTTP fallback
```cpp
    } else if (uri_.compare(0, 4, "http") == 0) {
        InitHttpSource(source);
    }
```

### 3.2 IsDash / IsHls / IsHlsFmp4 判断函数

**Evidence [E10]** `http_source_plugin.cpp:720`：`IsDash()` 实现
```cpp
bool HttpSourcePlugin::IsDash()
```

**Evidence [E11]** `http_source_plugin.cpp:729`：`IsHlsFmp4()` 实现
```cpp
bool HttpSourcePlugin::IsHlsFmp4()
```

**Evidence [E12]** `http_source_plugin.cpp:759`：`IsHls()` 实现
```cpp
bool HttpSourcePlugin::IsHls()
```

---

## 四、DownloadMonitor 装饰器能力

### 4.1 ReadAt 缓存优先逻辑

**Evidence [E13]** `http_source_plugin.cpp:276`：离线缓存管理器初始化
```cpp
        loaderCombinations_ = std::make_shared<MediaSourceLoaderCombinations>(source->GetSourceLoader());
        loaderCombinations_->EnableOfflineCache(source->GetenableOfflineCache());
```

### 4.2 SelectBitRate / AutoSelectBitRate 码率管理

**Evidence [E14]** `http_source_plugin.cpp:526-530`：人工指定码率
```cpp
Status HttpSourcePlugin::SelectBitRate(uint32_t bitRate)
{
    FALSE_RETURN_V(PrepareParam(bitRate), Status::ERROR_INVALID_PARAMETER);
    if (downloader_->SelectBitRate(bitRate)) {
```

**Evidence [E15]** `http_source_plugin.cpp:536-539`：自适应码率
```cpp
Status HttpSourcePlugin::AutoSelectBitRate(uint32_t bitRate)
{
    if (downloader_->AutoSelectBitRate(bitRate)) {
```

---

## 五、架构小结

```
HttpSourcePlugin (SourcePlugin 实现)
    │
    ├── SetDownloaderBySource() 路由决策
    │       │
    │       ├── IsDash() → DashMediaDownloader + DownloadMonitor 装饰
    │       ├── IsHlsFmp4() / IsHls() → HlsMediaDownloader + DownloadMonitor 装饰
    │       └── fallback → HttpMediaDownloader + DownloadMonitor 装饰
    │
    └── DownloadMonitor (Decorator)
            ├── 离线缓存 (loaderCombinations_)
            ├── SelectBitRate / AutoSelectBitRate 码率管理
            ├── 限速
            └── 统计上报 (SetSourceStatisticsDfx)
```

---

## 六、关联记忆

| 关联记忆 | 关系 |
|---------|------|
| MEM-ARCH-AVCODEC-S86 | HLS 流媒体缓存引擎（HlsSegmentManager） |
| MEM-ARCH-AVCODEC-S106 | MediaEngine Source 模块流媒体基础设施 |
| MEM-ARCH-AVCODEC-S122 | MediaEngine Streaming 基础设施 |
| MEM-ARCH-AVCODEC-S87 | MediaSource 核心架构 |
| MEM-ARCH-AVCODEC-S37 | HttpSourcePlugin 统一入口（HLS/DASH 自适应流处理） |
| MEM-ARCH-AVCODEC-S38 | SourcePlugin 源插件体系 |

---

## Evidence Summary

| # | Evidence | Source | Line |
|---|----------|--------|-------|
| E1 | HttpSourcePlugin 类继承 SourcePlugin | http_source_plugin.h | 28 |
| E2 | ParseAndSetSource 调用 SetDownloaderBySource | http_source_plugin.cpp | 229 |
| E3 | SetDownloaderBySource 路由核心函数 | http_source_plugin.cpp | 270 |
| E4 | DownloadMonitor 双重继承装饰器 | download_monitor.h | 43 |
| E5 | DownloadMonitor 装饰器构造函数 | download_monitor.h | 45 |
| E6 | IsDash() → DASH 下载器路由 | http_source_plugin.cpp | 287 |
| E7 | IsHlsFmp4() / IsSeekToTimeSupported → HLS 下载器路由 | http_source_plugin.cpp | 297 |
| E8 | IsHls() → 普通 HLS 下载器路由 | http_source_plugin.cpp | 310 |
| E9 | http URI → HttpMediaDownloader fallback | http_source_plugin.cpp | 319 |
| E10 | IsDash() 判断函数 | http_source_plugin.cpp | 720 |
| E11 | IsHlsFmp4() 判断函数 | http_source_plugin.cpp | 729 |
| E12 | IsHls() 判断函数 | http_source_plugin.cpp | 759 |
| E13 | loaderCombinations_ 离线缓存管理器初始化 | http_source_plugin.cpp | 276 |
| E14 | SelectBitRate 人工码率指定 | http_source_plugin.cpp | 526 |
| E15 | AutoSelectBitRate 自适应码率 | http_source_plugin.cpp | 536 |