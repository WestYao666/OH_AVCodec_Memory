---
id: MEM-ARCH-AVCODEC-S37
title: HTTP 流媒体源插件架构——HttpSourcePlugin 统一入口与 HLS/DASH 自适应流处理
scope: [AVCodec, MediaEngine, SourcePlugin, HLS, DASH, Streaming, AdaptiveBitrate, M3U8, MPD, HttpSource, SegmentDownload]
status: pending_approval
created_at: "2026-04-25T18:40:00+08:00"
author: builder-agent
type: architecture_fact
confidence: high
summary: >
  AVCodec 模块的 HTTP 流媒体源插件体系以 HttpSourcePlugin 为统一入口，根据 URL/MIME 类型自动路由到
  HlsMediaDownloader（HLS m3u8）或 DashMediaDownloader（DASH mpd）。HlsMediaDownloader 内部由
  HlsSegmentManager 管理多轨（视频/音频/字幕）分片下载，支持 AES-128 解密（EXT-X-KEY）；
  M3U8 解析器（HlsTag 枚举，25+ 标签类型）负责 playlist 解析。DashMediaDownloader 内部由
  DashMpdDownloader（MPD 元数据）+ DashSegmentDownloader（分片下载）构成，支持自适应码率切换。
  三者均实现 MediaDownloader 基类，向 SourcePlugin 层提供统一 Read/Seek 接口。
evidence_sources:
  - local_repo: /home/west/av_codec_repo
  - services/media_engine/plugins/source/http_source/http_source_plugin.cpp        # 769行，统一入口，路由逻辑
  - services/media_engine/plugins/source/http_source/http_source_plugin.h
  - services/media_engine/plugins/source/http_source/hls/hls_media_downloader.cpp   # 704行，HLS下载器
  - services/media_engine/plugins/source/http_source/hls/hls_media_downloader.h
  - services/media_engine/plugins/source/http_source/hls/hls_segment_manager.cpp     # 2582行，分片管理核心
  - services/media_engine/plugins/source/http_source/hls/hls_segment_manager.h
  - services/media_engine/plugins/source/http_source/hls/m3u8.cpp                    # M3U8解析器
  - services/media_engine/plugins/source/http_source/hls/m3u8.h
  - services/media_engine/plugins/source/http_source/hls/hls_tags.cpp                # 25+ HLS标签枚举
  - services/media_engine/plugins/source/http_source/hls/hls_tags.h
  - services/media_engine/plugins/source/http_source/dash/dash_media_downloader.cpp # 2495行，DASH下载器
  - services/media_engine/plugins/source/http_source/dash/dash_media_downloader.h
  - services/media_engine/plugins/source/http_source/dash/dash_mpd_downloader.cpp
  - services/media_engine/plugins/source/http_source/dash/dash_mpd_downloader.h
  - services/media_engine/plugins/source/http_source/dash/dash_segment_downloader.cpp
  - services/media_engine/plugins/source/http_source/dash/mpd_parser/dash_mpd_parser.cpp
related_scenes: [新需求开发, 问题定位, HLS流播放, DASH流播放, 自适应码率, 流媒体问题定位]
why_it_matters: >
  HTTP 流媒体源插件是 AVCodec 播放网络直播/点播内容的第一跳，负责 m3u8/MPD 元数据解析、
  分片下载、AES 解密、自适应码率切换。与本地文件播放（FileSourcePlugin）完全独立。
  当播放卡顿、码率不匹配、解密失败时，需定位到此层。
---

# HTTP 流媒体源插件架构——HttpSourcePlugin 统一入口与 HLS/DASH 自适应流处理

> **Builder 验证记录（2026-04-25）**：基于本地仓库 `/home/west/av_codec_repo` 代码验证。
> 代码路径均来自本地镜像，与 GitCode master 分支同步。

## 1. 概述

AVCodec 模块的流媒体源插件体系位于 `services/media_engine/plugins/source/http_source/` 目录，
以 **HttpSourcePlugin** 为统一入口，根据 URL 后缀和 MIME 类型自动路由到：

| 下载器 | 触发条件 | 核心类 |
|--------|---------|--------|
| **HlsMediaDownloader** | URL 含 `.m3u8` 或 MIME=`application/vnd.apple.mpegurl` | `http_source_plugin.cpp:298` |
| **DashMediaDownloader** | URL 含 `.mpd` 或 DASH_LIST 中的后缀 | `http_source_plugin.cpp:289` |
| **DownloadMonitor** | 其他 HTTP URL（普通点播） | `http_source_plugin.cpp:294` |

三者均继承/实现 `MediaDownloader` 基类，向 `SourcePlugin` 层提供统一的 `Read()`/`SeekToTime()` 接口。

**关键文件路径锚点**：

```
http_source_plugin.cpp:37-40   // LOWER_M3U8 / DASH_SUFFIX 常量定义
http_source_plugin.cpp:289     // DashMediaDownloader 创建
http_source_plugin.cpp:294     // DownloadMonitor（普通HTTP）创建
http_source_plugin.cpp:298     // HlsMediaDownloader 创建
http_source_plugin.cpp:645-674 // CheckIsM3U8Uri() 多策略判断
http_source_plugin.cpp:722-727 // DASH_LIST 后缀判断
```

## 2. HttpSourcePlugin 统一入口

**类继承关系**：`HttpSourcePlugin` : public `SourcePlugin`

**关键成员**：
```cpp
// http_source_plugin.h
std::shared_ptr<MediaDownloader> downloader_;  // 三种下载器之一
std::string uri_;
std::string mimeType_;  // AVMimeTypes::APPLICATION_M3U8 等
```

**路由决策逻辑**（`http_source_plugin.cpp:285-311`）：
```cpp
// 行 289: DASH 优先判断
if (IsDashUri()) {
    downloader_ = std::make_shared<DashMediaDownloader>(loaderCombinations_);
}
// 行 294: 普通HTTP
else if (IsSeekToTimeSupported() && mimeType_ != AVMimeTypes::APPLICATION_M3U8) {
    downloader_ = std::make_shared<DownloadMonitor>(...);
}
// 行 298: HLS
else {
    downloader_ = std::make_shared<HlsMediaDownloader>(...);
}
// 行 310-311: 强制MIME类型时直接覆盖
if (mimeType_ == AVMimeTypes::APPLICATION_M3U8) {
    downloader_ = std::make_shared<HlsMediaDownloader>(mimeType_);
}
```

**自适应码率切换**：
```cpp
// http_source_plugin.cpp:526-539
Status HttpSourcePlugin::SelectBitRate(uint32_t bitRate)   // 行 526
Status HttpSourcePlugin::AutoSelectBitRate(uint32_t bitRate) // 行 536
```

**HLS URL 自动识别策略**（`CheckIsM3U8Uri()`，行 645-674）：
1. 检查 URL 参数 `=m3u8`（`EQUAL_M3U8 = "=m3u8"`）
2. 检查 URL 路径包含 `.m3u8`
3. 检查自定义后缀列表
4. 兼容非标准 HLS 链接（如 `?autotype=m3u8`）

**证据文件**：
- `http_source_plugin.cpp:37-40` — 常量定义
- `http_source_plugin.cpp:285-311` — 路由决策
- `http_source_plugin.cpp:645-674` — HLS URL 判断
- `http_source_plugin.cpp:526-539` — 码率切换

## 3. HLS 流媒体架构

### 3.1 HlsMediaDownloader 类

**类定义**：`HlsMediaDownloader` : public `MediaDownloader`, public `std::enable_shared_from_this<HlsMediaDownloader>`

**核心成员**：
```cpp
// hls_media_downloader.h
std::shared_ptr<HlsSegmentManager> videoSegManager_;   // 视频分片管理器
std::shared_ptr<HlsSegmentManager> audioSegManager_;   // 音频分片管理器（混流时）
std::shared_ptr<HlsSegmentManager> subtitlesSegManager_; // 字幕分片管理器
```

**构造时序**（`hls_media_downloader.cpp:44-106`）：
1. 行 44: 构造 `videoSegManager_`（`SEG_VIDEO` 类型）
2. 行 55: `videoSegManager_` 初始化下载器
3. 行 73: 注册缓冲回调 `BufferingCallback`
4. 行 94: 若有独立音频流，构造 `audioSegManager_`（`SEG_AUDIO` 类型）
5. 行 102: 若有字幕流，构造 `subtitlesSegManager_`（`SEG_SUBTITLE` 类型）

**多轨选择**（`hls_media_downloader.cpp:580-608`）：
```cpp
// 行 580: 视频轨选择
if (segType == HlsSegmentType::SEG_VIDEO) {
    // 行 593: 音频轨联动选择
    audioSegManager_->SelectMedia(defaultAudioStreamId, HlsSegmentType::SEG_AUDIO);
    // 行 597: 字幕轨联动选择
    subtitlesSegManager_->SelectMedia(defaultSubtitlesStreamId, HlsSegmentType::SEG_SUBTITLE);
}
```

**证据文件**：
- `hls_media_downloader.cpp:44-106` — 构造与多轨初始化
- `hls_media_downloader.cpp:580-608` — 多轨选择逻辑
- `hls_media_downloader.cpp:649-674` — 缓冲事件分发

### 3.2 HlsSegmentManager 分片管理器

**类定义**：`HlsSegmentManager` : public `PlayListChangeCallback`

**核心成员**：
```cpp
// hls_segment_manager.h
std::shared_ptr<Downloader> downloader_;                    // HTTP下载器
std::shared_ptr<HlsPlayListDownloader> playlistDownloader_; // Playlist下载器
std::shared_ptr<AesDecryptor> aesDecryptor_;               // AES解密器（可选）
RingBuffer* ringBuffer_;                                    // 环形缓冲
HlsSegmentType segType_;                                    // SEG_VIDEO/AUDIO/SUBTITLE
```

**初始化**（`hls_segment_manager.cpp:190-217`）：
```cpp
// 行 190: 创建 HTTP 下载器
downloader_ = std::make_shared<Downloader>("hlsMedia", sourceLoader_);
// 行 196: 设置下载回调
downloader_->SetDownloadCallback(downloadCallback_);
// 行 201-204: dataSave_ lambda，数据直接写入环形缓冲
dataSave_ = [weakDownloader] (uint8_t*&& data, uint32_t&& len, bool&& notBlock) -> uint32_t {
    return shareDownloader->SaveData(std::forward<...>(data), ...);
};
// 行 208-212: 创建 Playlist 下载器
playlistDownloader_ = std::make_shared<HlsPlayListDownloader>(httpHeader_, sourceLoader_);
```

**AES-128 解密**（`hls_segment_manager.cpp:29`，`hls_tags.cpp`）：
```cpp
#include "openssl/aes.h"  // 行 29
// M3U8 Fragment 包含 AES 密钥信息：
// hls_tags.h: {"ext-x-key", HlsTag::EXTXKEY}
// M3U8Fragment 结构含 iv_[16], key_[16] 成员
```

**证据文件**：
- `hls_segment_manager.cpp:29` — OpenSSL AES 头文件
- `hls_segment_manager.cpp:190-217` — 初始化流程
- `hls_segment_manager.cpp:201-204` — 数据保存 lambda
- `hls_segment_manager.cpp:262-273` — 下载回调状态处理

### 3.3 M3U8 解析器

**核心解析流程**（`m3u8.cpp:151-212`）：
```cpp
// 行 151: 必须以 #EXTM3U 开头
if (!StrHasPrefix(playList, "#EXTM3U")) { ... }
// 行 893: 判断是 master playlist 还是 media playlist
if (playList_.find("\n#EXTINF:") != std::string::npos) { /* media playlist */ }
```

**M3U8 Fragment 结构**（`m3u8.h`）：
```cpp
struct M3U8Fragment {
    std::string uri_;          // 分片 URL
    double duration_;          // EXTINF 持续时间（秒）
    int64_t sequence_;        // EXT-X-MEDIA-SEQUENCE 序号
    bool discont_;            // EXT-X-DISCONTINUITY 标志
    uint8_t iv_[16];          // AES 解密 IV
    uint8_t key_[16];         // AES 密钥
    uint32_t offset_;         // 分片偏移
    uint32_t length_;         // 分片长度
};
```

**HLS 标签支持**（`hls_tags.cpp:40-78`）：
| 标签 | HlsTag 枚举值 | 用途 |
|------|-------------|------|
| `#EXTM3U` | — | playlist 头部标志 |
| `#EXTINF:` | `EXTINF` | 分片持续时间 |
| `#EXT-X-KEY:` | `EXTXKEY` | AES 加密参数（METHOD/URI/IV） |
| `#EXT-X-TARGETDURATION:` | `EXTXTARGETDURATION` | 最大分片时长 |
| `#EXT-X-MEDIA-SEQUENCE:` | `EXTXMEDIASEQUENCE` | 首分片序号 |
| `#EXT-X-DISCONTINUITY` | `EXTXDISCONTINUITY` | 编码不连续标志 |
| `#EXT-X-STREAM-INF:` | `EXTXSTREAMINF` | 多码率变体流（master playlist） |
| `#EXT-X-MEDIA:` | `EXTXMEDIA` | 备选音频/字幕轨 |
| `#EXT-X-ENDLIST` | `EXTXENDLIST` | 直播结束（VOD 标志） |

**证据文件**：
- `m3u8.cpp:151` — EXTM3U 头部检查
- `m3u8.cpp:893` — media playlist 判断
- `m3u8.h` — M3U8Fragment 结构
- `hls_tags.cpp:40-78` — HLS 标签映射表

## 4. DASH 流媒体架构

### 4.1 DashMediaDownloader 类

**类定义**：`DashMediaDownloader` : public `MediaDownloader`, public `DashMpdCallback`

**核心成员**：
```cpp
// dash_media_downloader.h
std::shared_ptr<DashMpdDownloader> mpdDownloader_;    // MPD 元数据下载/解析
std::shared_ptr<DashPreparedAction> preparedAction_;  // 码率/轨预选信息
```

**初始化**（`dash_media_downloader.cpp:41-61`）：
```cpp
// 行 41: 创建 MPD 下载器
mpdDownloader_ = std::make_shared<DashMpdDownloader>(sourceLoader);
// 行 47: MPD 下载器关闭
mpdDownloader_->Close(false);
// 行 60: 设置 MPD 回调（指向 DashMediaDownloader 自身）
mpdDownloader_->SetMpdCallback(shared_from_this());
```

**关键方法**：
```cpp
// 行 66: 打开 URL
mpdDownloader_->Open(url);
// 行 159/182: 获取流描述
streamDescription = mpdDownloader_->GetStreamByStreamId(streamId);
// 行 200: 获取下一分片
getRet = mpdDownloader_->GetNextSegmentByStreamId(streamId, seg);
// 行 339: 获取可用码率列表
return mpdDownloader_->GetBitRates();
```

**码率切换策略**（`dash_media_downloader.cpp:358-377`）：
```cpp
// 行 358: 平滑切换（SMOOTH）
preparedAction_.preparedBitrateParam_.type_ = DASH_MPD_SWITCH_TYPE_SMOOTH;
// 行 363: 当前码率参数也设为 SMOOTH
bitrateParam_.type_ = DASH_MPD_SWITCH_TYPE_SMOOTH;
```

**证据文件**：
- `dash_media_downloader.cpp:41-61` — 初始化
- `dash_media_downloader.cpp:159-211` — 流读取
- `dash_media_downloader.cpp:358-377` — 码率切换
- `dash_media_downloader.cpp:314-315` — 获取寻址范围

### 4.2 MPD 解析器（DashMpdParser）

**文件位置**：`services/media_engine/plugins/source/http_source/dash/mpd_parser/`

**主要文件**：
| 文件 | 用途 |
|------|------|
| `dash_mpd_parser.cpp` | MPD 根节点解析 |
| `dash_period_node.cpp` | Period 节点（时间分段） |
| `dash_representation_node.cpp` | Representation 节点（码率变体） |
| `dash_segment_template_node.cpp` | SegmentTemplate（分片URL模板） |
| `dash_seg_timeline_node.cpp` | SegmentTimeline（时间线分片） |
| `dash_adpt_set_node.cpp` | AdaptationSet（自适应集） |

**关键回调**（`DashMpdCallback`）：
```cpp
// dash_media_downloader.h
void OnMpdInfoUpdate(DashMpdEvent mpdEvent) override;  // MPD 更新事件
void OnDrmInfoChanged(...) override;                    // DRM 信息变化
void OnTimedMetaDataChanged(...) override;              // 定时元数据变化
```

### 4.3 DashSegmentDownloader 分片下载

**文件**：`services/media_engine/plugins/source/http_source/dash/dash_segment_downloader.cpp`

**功能**：根据 MPD 解析出的 `SegmentURL` 模板，构造实际分片 URL 并下载。

## 5. 与 Filter Pipeline 的关系

```
HTTP URL
  └─ HttpSourcePlugin (http_source_plugin.cpp)
       ├─ [m3u8] → HlsMediaDownloader
       │    └─ HlsSegmentManager (video/audio/subtitle 分片下载)
       │         └─ RingBuffer → DemuxerFilter
       ├─ [.mpd] → DashMediaDownloader
       │    └─ DashMpdDownloader + DashSegmentDownloader
       │         └─ RingBuffer → DemuxerFilter
       └─ [other] → DownloadMonitor
            └─ RingBuffer → DemuxerFilter
```

流媒体数据通过 `RingBuffer`（环形缓冲）传递给下游 **DemuxerFilter**（已覆盖于 S14 Filter Chain），
由 DemuxerFilter 解析出音频/视频 ES 流，再送入对应的 Decoder Filter。

## 6. 与现有 S 系列的关系

| 已有主题 | 与 S37 的关系 |
|---------|--------------|
| S14（Filter Chain） | S37 的输出目标为 DemuxerFilter |
| S8（音频 FFmpeg） | HLS/DASH 解封装后的音频流进入 FFmpeg 软解路径 |
| S16（SurfaceCodec） | S37 的视频帧最终送入 SurfaceCodec 解码渲染 |
| S22（MediaSyncManager） | 流媒体播放的 PTS/AVSync 同步由 MediaSyncManager 管理 |
| S25（AdaptiveFramerate） | 码率自适应与帧率自适应同属自适应体验优化体系 |

## 7. 关键行号锚点速查

| 描述 | 文件 | 行号 |
|------|------|------|
| HLS/DASH 常量 | `http_source_plugin.cpp` | 37-40 |
| DASH 下载器创建 | `http_source_plugin.cpp` | 289 |
| HTTP 下载器创建 | `http_source_plugin.cpp` | 294 |
| HLS 下载器创建 | `http_source_plugin.cpp` | 298 |
| M3U8 URL 自动识别 | `http_source_plugin.cpp` | 645-674 |
| 码率选择 | `http_source_plugin.cpp` | 526-539 |
| HLS 多轨初始化 | `hls_media_downloader.cpp` | 44-106 |
| HLS 分片管理构造 | `hls_segment_manager.cpp` | 190-217 |
| AES 头文件 | `hls_segment_manager.cpp` | 29 |
| M3U8 头部检查 | `m3u8.cpp` | 151 |
| HLS 标签表 | `hls_tags.cpp` | 40-78 |
| DASH MPD 创建 | `dash_media_downloader.cpp` | 41 |
| DASH 码率切换 | `dash_media_downloader.cpp` | 358-377 |
