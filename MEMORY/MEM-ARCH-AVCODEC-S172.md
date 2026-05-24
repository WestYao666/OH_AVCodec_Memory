# MEM-ARCH-AVCODEC-S172.md — HttpSourcePlugin 三路下载器工厂路由

> **草案状态**：draft  
> **Builder**：builder-agent (subagent)  
> **生成时间**：2026-05-25T06:50+08:00  
> **源码目录**：/home/west/av_codec_repo/services/media_engine/plugins/source/http_source/  
> **关联主题**：S37(S86)/S106/S122/S87/S38/S172  
> **状态**：pending_approval

---

## 一、架构概述

`HttpSourcePlugin` 是媒体源插件的 **HTTP/HTTPS 协议入口**，通过 `SetDownloaderBySource` 将不同的下载器实现（ Dash / HLS / HTTP ）动态注入。核心模式为 **装饰器模式**：真正的下载器（`HlsMediaDownloader` / `DashMediaDownloader` / `HttpMediaDownloader`）被 `DownloadMonitor` 包装，添加限速、缓存、离线下载等横切能力。

---

## 二、核心组件

### 2.1 HttpSourcePlugin 入口

**源码**：`http_source_plugin.cpp(769行) + http_source_plugin.h(115行)`

[http_source_plugin.h:45] `HttpSourcePlugin` 继承 `SourcePlugin`，实现 `SelectBitRate` / `AutoSelectBitRate` / `ReadAt` 等接口  
[http_source_plugin.cpp:229] `ParseAndSetSource` 调用 `SetDownloaderBySource` 路由到具体下载器  
[http_source_plugin.cpp:270] `SetDownloaderBySource` 是路由核心：根据 `IsDash()` / `IsHls()` 分发到三路下载器

### 2.2 DownloadMonitor 装饰器

**源码**：`monitor/download_monitor.h(232行) + monitor/download_monitor.cpp(610行)`

[download_monitor.h:43] `DownloadMonitor` 双重继承：`public MediaDownloader, public std::enable_shared_from_this<DownloadMonitor>`  
[download_monitor.h:45] `explicit DownloadMonitor(std::shared_ptr<MediaDownloader> downloader)` 装饰器构造函数  
[download_monitor.cpp:270-320] `ReadAt` 方法：先查离线缓存（`loaderCombinations_`），未命中则透传给底层下载器

### 2.3 三路下载器

| 下载器 | 类型 | 路由条件 |
|--------|------|----------|
| `DashMediaDownloader` | DASH MPD | `IsDash()` |
| `HlsMediaDownloader` | HLS m3u8 | `IsHls()` |
| `HttpMediaDownloader` | 普通HTTP | fallback |

---

## 三、路由决策链

### 3.1 SetDownloaderBySource 路由

[http_source_plugin.cpp:287] `if (IsDash())` → DASH 优先  
[http_source_plugin.cpp:288-290] `std::make_shared<DashMediaDownloader>(loaderCombinations_)` 创建 DASH 下载器 + DownloadMonitor 包装  
[http_source_plugin.cpp:297] `else if (IsHlsFmp4())` → HLS fMP4  
[http_source_plugin.cpp:298-300] `std::make_shared<DownloadMonitor>(std::make_shared<HlsMediaDownloader>(loaderCombinations_))` HLS 下载器 + DownloadMonitor 装饰  
[http_source_plugin.cpp:310] `else if (IsHls())` → 普通 HLS  
[http_source_plugin.cpp:311-313] HLS 下载器 + DownloadMonitor  
[http_source_plugin.cpp:337] `else` → 普通 HTTP  
[http_source_plugin.cpp:338-340] `std::make_shared<DownloadMonitor>(std::make_shared<HttpMediaDownloader>(uri_, expectDuration, loaderCombinations_))`

### 3.2 MediaSourceLoaderCombinations 离线缓存

[http_source_plugin.cpp:276] `loaderCombinations_ = std::make_shared<MediaSourceLoaderCombinations>(source->GetSourceLoader())` 离线缓存管理器  
[http_source_plugin.cpp:277] `loaderCombinations_->EnableOfflineCache(source->GetenableOfflineCache())` 启用离线缓存  
[http_source_plugin.cpp:278-279] Cookie 检查 + 存储空间不足时关闭缓存  
[http_source_plugin.cpp:282] 存储空间不足时 `loaderCombinations_->Close(-1)`

### 3.3 SelectBitRate / AutoSelectBitRate 码率切换

[http_source_plugin.cpp:526] `Status HttpSourcePlugin::SelectBitRate(uint32_t bitRate)` 人工指定码率  
[http_source_plugin.cpp:530] `downloader_->SelectBitRate(bitRate)` 委托给下载器  
[http_source_plugin.cpp:536] `Status HttpSourcePlugin::AutoSelectBitRate(uint32_t bitRate)` 自适应码率  
[http_source_plugin.cpp:539] `downloader_->AutoSelectBitRate(bitRate)` 委托给下载器

### 3.4 IsDash / IsHls 判断

[http_source_plugin.cpp:720] `bool HttpSourcePlugin::IsDash()` 判断是否为 DASH 流  
[http_source_plugin.cpp:759] `bool HttpSourcePlugin::IsHls()` 判断是否为 HLS 流  
[http_source_plugin.cpp:729] `bool HttpSourcePlugin::IsHlsFmp4()` 判断是否为 HLS fMP4  
[http_source_plugin.cpp:732] `return downloader_->IsHlsFmp4()` 委托给下载器查询

---

## 四、DownloadMonitor 装饰器实现

[download_monitor.cpp:270] `ReadAt` 入口：先查离线缓存 `loaderCombinations_->ReadAt`，未命中则调用底层 `downloader_->ReadAt`  
[download_monitor.h:43-45] `DownloadMonitor` 持有被装饰的 `MediaDownloader`（通过 `shared_from_this` 保留引用）  
[download_monitor.cpp:285] `Seek` 透传：`downloader_->Seek(position, mode)`  
[download_monitor.cpp:295] `GetSize` 透传：`downloader_->GetSize(totalSize)`  
[download_monitor.cpp:300] `GetLastModificationTime` 透传

---

## 五、关键证据汇总

| # | 源码文件 | 行号 | 描述 |
|---|----------|------|------|
| 1 | http_source_plugin.h | 45 | HttpSourcePlugin 类继承 SourcePlugin |
| 2 | http_source_plugin.cpp | 229 | ParseAndSetSource 调用 SetDownloaderBySource |
| 3 | http_source_plugin.cpp | 270 | SetDownloaderBySource 路由入口 |
| 4 | http_source_plugin.cpp | 276-277 | MediaSourceLoaderCombinations 离线缓存初始化 |
| 5 | http_source_plugin.cpp | 278-279 | Cookie + 存储空间检查 |
| 6 | http_source_plugin.cpp | 282 | 存储不足时关闭缓存 |
| 7 | http_source_plugin.cpp | 287 | IsDash() 判断 → DashMediaDownloader |
| 8 | http_source_plugin.cpp | 288-290 | DASH 下载器 + DownloadMonitor 装饰 |
| 9 | http_source_plugin.cpp | 297 | IsHlsFmp4() 判断 |
| 10 | http_source_plugin.cpp | 298-300 | HLS fMP4 下载器 + DownloadMonitor 装饰 |
| 11 | http_source_plugin.cpp | 310 | IsHls() 判断 |
| 12 | http_source_plugin.cpp | 311-313 | 普通 HLS 下载器 + DownloadMonitor 装饰 |
| 13 | http_source_plugin.cpp | 337-340 | 普通 HTTP 下载器 + DownloadMonitor 装饰（fallback） |
| 14 | http_source_plugin.cpp | 526-534 | SelectBitRate 人工码率切换 |
| 15 | http_source_plugin.cpp | 536-541 | AutoSelectBitRate 自适应码率切换 |
| 16 | http_source_plugin.cpp | 720 | IsDash() DASH 判断 |
| 17 | http_source_plugin.cpp | 729 | IsHlsFmp4() HLS fMP4 判断 |
| 18 | http_source_plugin.cpp | 732 | IsHlsFmp4() 委托下载器查询 |
| 19 | http_source_plugin.cpp | 759-764 | IsHls() HLS 判断 |
| 20 | download_monitor.h | 43 | DownloadMonitor 双重继承 MediaDownloader + enable_shared_from_this |
| 21 | download_monitor.h | 45 | 装饰器构造函数签名 |
| 22 | download_monitor.cpp | 270 | ReadAt 离线缓存优先策略 |
| 23 | download_monitor.cpp | 285 | Seek 透传底层下载器 |
| 24 | download_monitor.cpp | 295 | GetSize 透传底层下载器 |