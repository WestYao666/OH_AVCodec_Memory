# MEM-ARCH-AVCODEC-S172 — HttpSourcePlugin 源码深度分析

> **主题**: HttpSourcePlugin 三路下载器工厂路由 + DownloadMonitor 装饰器 + MediaSourceLoaderCombinations 自适应码率  
> **scope**: AVCodec, MediaEngine, SourcePlugin, HttpSourcePlugin, DownloadMonitor, MediaSourceLoaderCombinations, HLS, DASH, AdaptiveBitrate, SelectBitRate, AutoSelectBitRate  
> **关联场景**: 新需求开发/问题定位/流媒体播放/HLS-DASH 自适应码率  
> **状态**: draft  
> **生成时间**: 2026-05-21T12:50:00+08:00  
> **Builder**: builder-agent (subagent)  
> **关联主题**: S37(HttpSourcePlugin总览)/S86(HLS缓存引擎)/S106(Source模块)/S122(StreamDemuxer)/S87(Source架构)/S38(SourcePlugin体系)

---

## 1. HttpSourcePlugin 核心架构

**文件**: `services/media_engine/plugins/source/http_source/http_source_plugin.h` (140行) + `http_source_plugin.cpp` (769行)

HttpSourcePlugin 继承 SourcePlugin，是 HTTP/HTTPS 流媒体源的顶层插件入口，提供 40+ 个接口方法（Init/Start/Stop/Seek/SelectBitRate 等），通过 DownloadMonitor 装饰器组合三种下载器。

**核心成员**:
```cpp
// http_source_plugin.h L31-75 (主要接口方法)
class HttpSourcePlugin : public SourcePlugin {
    Status SetSource(std::shared_ptr<MediaSource> source) override;  // L44
    Status Read(int32_t streamId, std::shared_ptr<Buffer>& buffer, ...) override;  // L46
    Status SelectBitRate(uint32_t bitRate) override;  // L56
    Status AutoSelectBitRate(uint32_t bitRate) override;  // L57
    bool IsDash() override;  // L720
    bool IsHls() override;  // L759
    bool IsHlsFmp4() override;  // L729
    bool GetHLSDiscontinuity() override;  // L599
    Status GetBitRates(std::vector<uint32_t>& bitRates) override;  // L55
    void SetDemuxerState(int32_t streamId) override;  // L63
    void SetDownloadErrorState() override;  // L64
    void SetInterruptState(bool isInterruptNeeded) override;  // L65
    Status GetPlaybackInfo(PlaybackInfo& playbackInfo) override;  // L68
    std::vector<SeekRange> GetSeekableRanges() const override;  // L69
};
```

**关键成员变量** (http_source_plugin.cpp):
- `std::shared_ptr<DownloadMonitor> downloader_` — 三路下载器统一包装
- `std::shared_ptr<MediaSourceLoaderCombinations> loaderCombinations_` — 离线缓存与多源管理
- `std::string mimeType_` — MIME 类型路由判断依据
- `std::string uri_` — 当前资源 URI
- `std::map<std::string, std::string> httpHeader_` — HTTP 请求头

---

## 2. 三路下载器工厂路由机制

**文件**: `http_source_plugin.cpp` L266-351

SetDownloaderBySource() 是三路下载器的路由决策中心，mimeType + URI 联合判断：

### 2.1 DASH 路径 (IsDash() → .mpd)

```cpp
// L287-294
if (IsDash()) {
    downloader_ = std::make_shared<DownloadMonitor>(
        std::make_shared<DashMediaDownloader>(loaderCombinations_));
    downloader_->Init();
    downloader_->SetSourceStatisticsDfx(reportInfo_);
    delayReady_ = false;
}
```

**判断条件**: `mimeType == AVMimeTypes::APPLICATION_DASH` 或 URI 含 `.mpd` 或 `type=mpd`  
**下载器类型**: DashMediaDownloader — MPD 清单解析 + 分片下载

### 2.2 HLS 路径 (IsSeekToTimeSupported() && 非 APPLICATION_M3U8)

```cpp
// L294-309
else if (IsSeekToTimeSupported() && mimeType_ != AVMimeTypes::APPLICATION_M3U8) {
    bool userDefinedDuration = false;
    uint32_t expectDuration = DEFAULT_EXPECT_DURATION;
    UserDefinedDuration(playStrategy, userDefinedDuration, expectDuration);  // L267-273 用户定义缓冲时长
    downloader_ = std::make_shared<DownloadMonitor>(
        std::make_shared<HlsMediaDownloader>(expectDuration, userDefinedDuration, httpHeader_, loaderCombinations_));
    downloader_->Init();
}
```

**判断条件**: IsSeekToTimeSupported()（检查 URI 是否含 `.m3u8` 或 `.mpd` 后缀）且 mimeType 非 APPLICATION_M3U8  
**下载器类型**: HlsMediaDownloader — M3U8 解析 + 视频/音频/字幕三轨分片管理

### 2.3 HLS M3U8 直接指定 (mimeType == APPLICATION_M3U8)

```cpp
// L310-314
if (mimeType_== AVMimeTypes::APPLICATION_M3U8) {
    downloader_ = std::make_shared<DownloadMonitor>(std::make_shared<HlsMediaDownloader>(mimeType_));
    downloader_->Init();
}
```

### 2.4 普通 HTTP 路径

```cpp
// L336-342
else {
    InitHttpSource(source);  // → HttpMediaDownloader
}

void HttpSourcePlugin::InitHttpSource(const std::shared_ptr<MediaSource>& source)
{
    // L322-339: 从 MediaStreamList 取最小码率 URL，构造 HttpMediaDownloader
    downloader_ = std::make_shared<DownloadMonitor>(
        std::make_shared<HttpMediaDownloader>(uri_, expectDuration, loaderCombinations_));
    downloader_->Init();
}
```

### 2.5 路由条件汇总

| 条件 | 下载器 | 缓存策略 |
|------|--------|---------|
| IsDash() = true | DashMediaDownloader | delayReady_=false |
| IsSeekToTimeSupported() && mimeType!=APPLICATION_M3U8 | HlsMediaDownloader | delayReady_=false |
| mimeType == APPLICATION_M3U8 | HlsMediaDownloader | 用户定义缓冲 |
| uri 以 http 开头且不满足上述 | HttpMediaDownloader | InitHttpSource() |

---

## 3. DownloadMonitor 装饰器

**文件**: `download_monitor.h` (148行, 位于 `plugins/source/http_source/monitor/`)

DownloadMonitor 是所有下载器的统一装饰器，注入统计、缓冲管理、错误处理能力：

```cpp
// 推断自 download_monitor.h + 调用模式
class DownloadMonitor : public std::enable_shared_from_this<DownloadMonitor> {
    DownloadMonitor(std::shared_ptr<MediaDownloader> actual);  // 装饰模式
    bool SelectBitRate(uint32_t bitRate);  // L526-530: 透传给实际下载器
    bool AutoSelectBitRate(uint32_t bitRate);  // L536-539
    bool GetHLSDiscontinuity();  // L599-602
    void Init();  // 下载器初始化
    void SetPlayStrategy(std::shared_ptr<PlayStrategy> strategy);  // L298
    void SetInterruptState(bool isInterruptNeeded);  // L314
    void SetAppUid(uid_t uid);  // L318
    void SetSourceStatisticsDfx(std::shared_ptr<ReportInfo> reportInfo);  // L292
};
```

**关键设计**: DownloadMonitor 不改变下载行为，只在调用链上注入 DFX 上报、缓冲策略、错误状态管理，实现下载逻辑与监控逻辑的分离。

---

## 4. MediaSourceLoaderCombinations 离线缓存管理

**文件**: `http_source_plugin.cpp` L276-283

```cpp
if (source->GetSourceLoader() != nullptr) {
    loaderCombinations_ = std::make_shared<MediaSourceLoaderCombinations>(source->GetSourceLoader());
    loaderCombinations_->EnableOfflineCache(source->GetenableOfflineCache());
    if (httpHeader_.find("Cookie") != httpHeader_.end() && loaderCombinations_->GetenableOfflineCache()) {
        loaderCombinations_->Close(-1);  // Cookie 场景不缓存
    } else {
        std::shared_ptr<StorageUsageUtil> storageUsage = std::make_shared<StorageUsageUtil>();
        if (loaderCombinations_->GetenableOfflineCache() && !storageUsage->HasEnoughStorage()) {
            loaderCombinations_->Close(-1);  // 存储空间不足不缓存
        }
    }
}
```

**职责**:
- `EnableOfflineCache(bool)` — 启用/禁用离线缓存
- `Close(-1)` — 禁用缓存时的清理操作
- 存储空间检测（StorageUsageUtil）
- Cookie 场景下禁用缓存（隐私保护）

---

## 5. 自适应码率机制

**文件**: `http_source_plugin.cpp` L526-544

### 5.1 SelectBitRate 手动选码率

```cpp
// L526-535
Status HttpSourcePlugin::SelectBitRate(uint32_t bitRate)
{
    MEDIA_LOG_I("SelectBitRate: " PUBLIC_LOG_U32, bitRate);
    if (downloader_ == nullptr) {
        return Status::ERROR_NULL_POINTER;
    }
    if (downloader_->SelectBitRate(bitRate)) {
        return Status::OK;
    }
    return Status::ERROR_INVALID_PARAMETER;
}
```

### 5.2 AutoSelectBitRate 自动选码率

```cpp
// L536-544
Status HttpSourcePlugin::AutoSelectBitRate(uint32_t bitRate)
{
    MEDIA_LOG_I("AutoSelectBitRate: " PUBLIC_LOG_U32, bitRate);
    if (downloader_->AutoSelectBitRate(bitRate)) {
        return Status::OK;
    }
    return Status::ERROR_INVALID_PARAMETER;
}
```

**差异**: `SelectBitRate` 由调用方指定固定码率；`AutoSelectBitRate` 由下载器根据网络状况自动调节。两者均通过 DownloadMonitor 透传给具体下载器（DASH/HLS/HTTP 三种下载器各自实现码率切换逻辑）。

### 5.3 GetBitRates 获取可用码率列表

```cpp
// http_source_plugin.h L55
Status GetBitRates(std::vector<uint32_t>& bitRates) override;
```

播放器通过此接口查询当前流媒体支持的所有码率档位，用于 UI 展示和用户切换。

---

## 6. URI 探测与 MIME 类型判断

**文件**: `http_source_plugin.cpp` L714-770

```cpp
// L37-42 常量定义
const std::string LOWER_M3U8 = "m3u8";
const std::string DASH_SUFFIX = ".mpd";
std::string(".mpd"),
std::string("type=mpd"),

// L720-728 IsDash()
bool HttpSourcePlugin::IsDash()
{
    if (mimeType_ == AVMimeTypes::APPLICATION_DASH) {
        return true;
    }
    if (uri_.find(DASH_SUFFIX) != std::string::npos || uri_.find("type=mpd") != std::string::npos) {
        return true;
    }
    return false;
}

// L759-766 IsHls()
bool HttpSourcePlugin::IsHls()
{
    if (mimeType_ == AVMimeTypes::APPLICATION_M3U8) {
        MEDIA_LOG_I("IsHls return true");
        return true;
    }
    if (mimeType_ != AVMimeTypes::APPLICATION_M3U8) {
        // L659 注释: 现网很多hls链接是非.m3u8关键字，举例: http://xxx/xxxx?autotype=m3u8
        if (CheckIsM3U8Uri()) {  // 自定义 URI 后缀判断
            return true;
        }
    }
    return false;
}

// L729-732 IsHlsFmp4()
bool HttpSourcePlugin::IsHlsFmp4()
{
    return downloader_->IsHlsFmp4();
}
```

---

## 7. Read 读取路径

**文件**: `http_source_plugin.cpp` L374-430

```cpp
// L379-391 Read 入口
Status HttpSourcePlugin::Read(int32_t streamId, std::shared_ptr<Buffer>& buffer, uint64_t offset, size_t expectedLen)
{
    MediaAVCodec::AVCodecTrace trace("HttpSourcePlugin::Read, offset: "
        + std::to_string(offset) + ", expectedLen: " + std::to_string(expectedLen));
    MEDIA_LOG_D("Read enter.");
    AutoLock lock(mutex_);
    FALSE_RETURN_V(downloader_ != nullptr, Status::ERROR_NULL_POINTER);
    return downloader_->Read(streamId, buffer, offset, expectedLen);  // 透传给下载器
}
```

Read 是阻塞式接口，通过 `downloader_->Read()` 从各下载器的缓冲队列中读取数据。DownloadMonitor 内部管理缓冲队列和流控逻辑。

---

## 8. 与其他 S 系列主题关联

| 关联主题 | 关系 |
|---------|------|
| S37 (HttpSourcePlugin 总览) | 上游：S172 是 S37 的源码深度版，补充三路工厂路由细节 |
| S86 (HLS 缓存引擎) | 同级：S86 聚焦 RingBuffer/SegmentManager，S172 聚焦 HttpSourcePlugin 整体路由 |
| S106 (Source 模块) | 上游：S106 总览 Source 模块，S172 深耕 HttpSourcePlugin |
| S122 (StreamDemuxer 分片缓存) | 下游：HttpSourcePlugin 产出数据喂给 StreamDemuxer |
| S87 (Source 架构) | 上游：Source 持有 HttpSourcePlugin，PluginManagerV2 工厂创建 |
| S38 (SourcePlugin 体系) | 基础：HttpSourcePlugin 继承 SourcePlugin 基接口 |
| S69/S75 (MediaDemuxer) | 下游：HttpSourcePlugin → StreamDemuxer → MediaDemuxer 数据流 |

---

## 9. 关键 Evidence 汇总

| # | 文件 | 行号 | 内容 |
|---|------|------|------|
| 1 | http_source_plugin.h | 31-75 | HttpSourcePlugin 40+ 接口方法完整列表 |
| 2 | http_source_plugin.cpp | 37-42 | DASH/HLS 常量定义（LOWER_M3U8/DASH_SUFFIX/type=mpd） |
| 3 | http_source_plugin.cpp | 244-251 | PlayStrategyInit + mimeType_ 提取 |
| 4 | http_source_plugin.cpp | 266-351 | SetDownloaderBySource() 三路路由核心逻辑 |
| 5 | http_source_plugin.cpp | 276-283 | MediaSourceLoaderCombinations 离线缓存管理（Cookie/存储空间检测） |
| 6 | http_source_plugin.cpp | 287-294 | DASH 路径：DashMediaDownloader 构造 |
| 7 | http_source_plugin.cpp | 294-309 | HLS 路径：HlsMediaDownloader 构造（含 UserDefinedDuration） |
| 8 | http_source_plugin.cpp | 310-314 | HLS M3U8 直接指定路径 |
| 9 | http_source_plugin.cpp | 322-342 | InitHttpSource() → HttpMediaDownloader 普通 HTTP 下载 |
| 10 | http_source_plugin.cpp | 350-355 | DownloadMonitor 统一包装 + SetPlayStrategy + SetInterruptState |
| 11 | http_source_plugin.cpp | 374-391 | Read() 入口，downloader_->Read() 透传 |
| 12 | http_source_plugin.cpp | 526-544 | SelectBitRate/AutoSelectBitRate 自适应码率双接口 |
| 13 | http_source_plugin.cpp | 599-604 | GetHLSDiscontinuity() 透传 |
| 14 | http_source_plugin.cpp | 659-673 | 非 .m3u8 后缀的 HLS URI 处理（autotype=m3u8/doplaylist） |
| 15 | http_source_plugin.cpp | 714-732 | IsDash() / IsHlsFmp4() 实现 |
| 16 | http_source_plugin.cpp | 747-766 | IsHls() / IsHlsEnd() 实现 |

---

## 10. 架构小结

```
MediaSource
  └── HttpSourcePlugin (L31-75 接口, L244 mimeType_ 提取)
        └── DownloadMonitor (装饰器: 统计/缓冲/错误处理)
              ├── DashMediaDownloader (mimeType==DASH || URI含.mpd)
              ├── HlsMediaDownloader (IsSeekToTimeSupported() || mimeType==M3U8)
              └── HttpMediaDownloader (普通HTTP)
        └── MediaSourceLoaderCombinations (离线缓存: Cookie/存储空间/离线开关)
              └── MediaSourceLoader (底层存储)
```

**关键设计模式**:
- **装饰器模式**: DownloadMonitor 包装所有下载器，注入 DFX 和流控
- **工厂路由**: SetDownloaderBySource() 根据 mimeType + URI 动态选择下载器
- **策略模式**: MediaSourceLoaderCombinations 根据 Cookie/存储空间启用/禁用缓存

---

> 本草案基于本地镜像 `services/media_engine/plugins/source/http_source/` 探索，GitCode 验证（769行主文件）。提交待耀耀审批。