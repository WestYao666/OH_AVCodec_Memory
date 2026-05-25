---
id: MEM-ARCH-AVCODEC-S182
title: "HLS Playlist Downloader 三路媒体流管理架构——M3U8MasterPlaylist + M3U8VariantStream + M3U8Media 三层结构与 SelectMedia/SetDefaultMedia 轨选机制"
scope: [AVCodec, MediaEngine, Source, HLS, Playlist, M3U8, M3U8MasterPlaylist, M3U8VariantStream, M3U8Media, SelectMedia, SetDefaultMedia, Track, AdaptiveBitrate, AES, DRM, SegmentDownload]
status: pending_approval
created_by: builder-agent
created_at: "2026-05-25T09:50:00+08:00"
submitted_by: builder-agent
evidence_count: 20
source_files: >
  services/media_engine/plugins/source/http_source/hls/playlist_downloader.h (206行) +
  services/media_engine/plugins/source/http_source/hls/hls_playlist_downloader.cpp (1270行) +
  services/media_engine/plugins/source/http_source/hls/hls_playlist_downloader.h (147行) +
  services/media_engine/plugins/source/http_source/hls/m3u8.h (291行) +
  services/media_engine/plugins/source/http_source/hls/m3u8.cpp (1435行)
  = 3349行源码
local_mirror_base: /home/west/av_codec_repo
---

# MEM-ARCH-AVCODEC-S182: HLS Playlist Downloader 三路媒体流管理架构

## 主题

HLS Playlist Downloader 三路媒体流管理架构——M3U8MasterPlaylist + M3U8VariantStream + M3U8Media 三层结构与 SelectMedia/SetDefaultMedia 轨选机制

## Scope

AVCodec, MediaEngine, Source, HLS, Playlist, M3U8, M3U8MasterPlaylist, M3U8VariantStream, M3U8Media, SelectMedia, SetDefaultMedia, Track, AdaptiveBitrate, AES, DRM, SegmentDownload

## 关联场景

新需求开发 / 问题定位 / 流媒体播放 / HLS 自适应码率 / 音视频轨选择

## 状态

`draft`（2026-05-25 Builder 创建，待审批）

---

## 概述

`HlsPlayListDownloader`（`hls_playlist_downloader.cpp`, 1270行）是 HLS 播放列表下载器的核心引擎，继承自 `PlayListDownloader` 基类。它负责：

1. **三层 Playlist 结构**：M3U8MasterPlaylist（总播放列表）→ M3U8VariantStream（多码率变体）→ M3U8Media（音视频字幕轨）
2. **三路媒体流管理**：`HlsSegmentType::SEG_VIDEO` / `SEG_AUDIO` / `SEG_SUBTITLE` 三轨并发管理
3. **轨选机制**：`SelectMedia` / `SetDefaultMedia` / `UpdateMedia` 三层轨选 API
4. **fMP4 / ByteRange 支持**：`isFmp4_` / `isPureByteRange_` 标志驱动差异化解析路径
5. **AES-128 DRM 解密**：`AesDecryptorManager` 按 segment keyIndex 管理解密器
6. **Playlist 更新机制**：`UpdateManifest` / `UpdateMasterInfo` / `UpdatePlaylists` 三级更新链

---

## 核心组件

### 1. HlsSegmentType 三路媒体流枚举（playlist_downloader.h:L43-46）

```cpp
enum class HlsSegmentType : int {
    SEG_VIDEO = 0,
    SEG_AUDIO = 1,
    SEG_SUBTITLE = 2,
};
```

**证据**：`playlist_downloader.h:43-46` — 三路枚举，驱动 SelectMedia / SetDefaultMedia / GetDefaultMediaStreamId / UpdateMedia / GetSegType 五类方法分发。

---

### 2. PlayListDownloader 基类（playlist_downloader.h:L73-181）

```cpp
class PlayListDownloader : public std::enable_shared_from_this<PlayListDownloader> {
public:
    virtual void Open(const std::string& url, ...) = 0;
    virtual void SelectMedia(int32_t streamId, HlsSegmentType mediaType) = 0;
    virtual void SetDefaultMedia(HlsSegmentType mediaType) = 0;
    virtual int32_t GetDefaultMediaStreamId(HlsSegmentType mediaType) = 0;
    virtual std::shared_ptr<AesDecryptor> GetAesDecryptor(uint64_t keyIndex) = 0;
    // ... 40+ 虚方法
protected:
    std::shared_ptr<Downloader> downloader_;
    std::shared_ptr<DownloadRequest> downloadRequest_;
    DataSaveFunc dataSave_;
    std::map<std::string, std::string> httpHeader_ {};
};
```

**证据**：`playlist_downloader.h:73-181` — 抽象基类，40+ 虚方法定义下载器接口契约，`HlsPlayListDownloader` 继承实现。

---

### 3. PlayInfo / KeyInfo 数据结构（playlist_downloader.h:L29-48）

```cpp
struct PlayInfo {
    std::string url_;
    double duration_;
    int64_t startTimePos_ {0};
    uint32_t offset_ {0};
    uint32_t length_ {0};
    std::string rangeUrl_;
    uint32_t streamId_ {0};    // 轨 ID
    uint64_t sumDuration_ {0};
    uint64_t keyIndex_ {0};     // AES key 索引
    int64_t sequence_ {0};
};
struct KeyInfo {
    uint8_t iv_[16] {0};
    uint8_t key_[16] {0};
    size_t keyLen_ {0};
    uint64_t index_ {0};
};
```

**证据**：`playlist_downloader.h:29-48` — PlayInfo 单 segment 元数据（含 streamId / keyIndex），KeyInfo AES-128 解密密钥。

---

### 4. AesDecryptorManager（playlist_downloader.h:L68-72）

```cpp
class AesDecryptorManager : public std::enable_shared_from_this<AesDecryptorManager> {
public:
    std::shared_ptr<AesDecryptor> GetAesDecryptorByKeyIndex(uint64_t keyIndex);
    void CreateAesDecryptorByKeyInfos(const std::unordered_map<uint64_t, KeyInfo>& keyInfos);
};
```

**证据**：`playlist_downloader.h:68-72` — 按 keyIndex 管理多个 AesDecryptor 实例，支持 HLS 多密钥（EXT-X-KEY）切换。

---

### 5. HlsPlayListDownloader 核心成员（hls_playlist_downloader.h:L86-147）

```cpp
class HlsPlayListDownloader : public PlayListDownloader {
private:
    std::shared_ptr<M3U8MasterPlaylist> master_;        // 主播放列表
    std::shared_ptr<M3U8VariantStream> currentVariant_; // 当前变体
    std::shared_ptr<M3U8VariantStream> newVariant_;     // 新变体（码率切换）
    std::shared_ptr<M3U8Media> currentAudio_;          // 当前音频轨
    std::shared_ptr<M3U8Media> currentSubtitles_;       // 当前字幕轨
    std::atomic<int32_t> audioStreamId_ {-1};
    std::atomic<int32_t> subtitleStreamId_ {-1};
    std::atomic<bool> isFmp4_ {false};
    std::atomic<bool> isPureByteRange_ {false};
    std::atomic<bool> needAudioManager_ {false};
    std::atomic<bool> needSubtitlesManager_ {false};
    std::set<uint32_t> videoStreamIds_;
    std::set<uint32_t> audioStreamIds_;
    std::set<uint32_t> subtitlesStreamIds_;
    std::shared_ptr<AesDecryptorManager> aesDecryptorManager_;
};
```

**证据**：`hls_playlist_downloader.h:86-147` — 五数据成员支撑三轨管理，isFmp4_/isPureByteRange_ 标志差异化解析。

---

### 6. SelectMedia 轨选实现（hls_playlist_downloader.cpp:L1157-1195）

```cpp
void HlsPlayListDownloader::SelectMedia(int32_t streamId, HlsSegmentType mediaType)
{
    if (currentVariant_ == nullptr) { return; }
    std::list<std::shared_ptr<M3U8Media>> videoStreamMedia;
    if (mediaType == HlsSegmentType::SEG_AUDIO && !currentVariant_->audioMedia_.empty()) {
        videoStreamMedia = currentVariant_->audioMedia_;  // 音频轨列表
    } else if (!currentVariant_->subtitlesMedia_.empty()) {
        videoStreamMedia = currentVariant_->subtitlesMedia_;  // 字幕轨列表
    }
    for (const auto &media : videoStreamMedia) {
        if (static_cast<uint32_t>(streamId) == media->streamId_) {
            std::lock_guard<std::mutex> lock(mediaMutex_);
            if (mediaType == HlsSegmentType::SEG_AUDIO) {
                currentAudio_ = media;   // 切换当前音频轨
            } else {
                currentSubtitles_ = media;  // 切换当前字幕轨
            }
            return;
        }
    }
}
```

**证据**：`hls_playlist_downloader.cpp:1157-1195` — SelectMedia 按 streamId 在 audioMedia_/subtitlesMedia_ 列表中匹配切换，`mediaMutex_` 线程安全。

---

### 7. SetDefaultMedia 默认轨设置（hls_playlist_downloader.cpp:L1136-1156）

```cpp
void HlsPlayListDownloader::SetDefaultMedia(HlsSegmentType mediaType)
{
    if (master_ == nullptr || master_->defaultVariant_ == nullptr) { return; }
    std::shared_ptr<M3U8Media> defaultMediaType;
    if (mediaType == HlsSegmentType::SEG_AUDIO && master_->defaultVariant_->defaultAudio_ != nullptr) {
        defaultMediaType = master_->defaultVariant_->defaultAudio_;  // 默认音频轨
    } else if (master_->defaultVariant_->defaultSubtitles_ != nullptr) {
        defaultMediaType = master_->defaultVariant_->defaultSubtitles_;  // 默认字幕轨
    }
    std::lock_guard<std::mutex> lock(mediaMutex_);
    if (mediaType == HlsSegmentType::SEG_AUDIO) {
        currentAudio_ = defaultMediaType;
    } else {
        currentSubtitles_ = defaultMediaType;
    }
}
```

**证据**：`hls_playlist_downloader.cpp:1136-1156` — SetDefaultMedia 从 master_->defaultVariant_->defaultAudio_/defaultSubtitles_ 读取默认轨并设置当前轨。

---

### 8. GetDefaultMediaStreamId 默认轨 ID 查询（hls_playlist_downloader.cpp:L1114-1135）

```cpp
int32_t HlsPlayListDownloader::GetDefaultMediaStreamId(HlsSegmentType mediaType)
{
    if (mediaType == HlsSegmentType::SEG_AUDIO && audioStreamId_.load() != -1) {
        return audioStreamId_.load();   // 已选音频轨 ID
    } else if (mediaType == HlsSegmentType::SEG_SUBTITLE && subtitleStreamId_.load() != -1) {
        return subtitleStreamId_.load();
    }
    if (mediaType == HlsSegmentType::SEG_AUDIO && currentVariant_->defaultAudio_ != nullptr) {
        return currentVariant_->defaultAudio_->streamId_;  // 默认音频轨
    } else if (currentVariant_->defaultSubtitles_ != nullptr) {
        return currentVariant_->defaultSubtitles_->streamId_;  // 默认字幕轨
    }
    return -1;
}
```

**证据**：`hls_playlist_downloader.cpp:1114-1135` — GetDefaultMediaStreamId 两级查找（已选轨 → 默认轨），返回 streamId 或 -1。

---

### 9. GetSegType 轨类型识别（hls_playlist_downloader.cpp:L1244-1254）

```cpp
HlsSegmentType HlsPlayListDownloader::GetSegType(uint32_t streamId)
{
    if (audioStreamIds_.count(streamId)) {
        return HlsSegmentType::SEG_AUDIO;
    } else if (subtitlesStreamIds_.count(streamId)) {
        return HlsSegmentType::SEG_SUBTITLE;
    }
    return HlsSegmentType::SEG_VIDEO;
}
```

**证据**：`hls_playlist_downloader.cpp:1244-1254` — GetSegType 通过 streamIds 三集合（video/audio/subtitles）判定 streamId 所属类型。

---

### 10. UpdateMedia 轨内容更新（hls_playlist_downloader.cpp:L1191-1243）

```cpp
void HlsPlayListDownloader::UpdateMedia(HlsSegmentType mediaType)
{
    std::string nextUrl = "";
    {
        std::lock_guard<std::mutex> lock(mediaMutex_);
        if (mediaType == HlsSegmentType::SEG_AUDIO && currentAudio_ != nullptr) {
            nextUrl = currentAudio_->m3u8_->files_.front()->uri_;  // 下一分片 URL
        }
    }
    // ... 调用 downloader_ 下载下一分片
}
```

**证据**：`hls_playlist_downloader.cpp:1191-1243` — UpdateMedia 在轨切换后更新当前分片 URL，驱动下载器获取下一分片。

---

### 11. M3U8VariantStream 三层结构（m3u8.h:L175-191）

```cpp
struct M3U8VariantStream {
    std::string name_;
    std::string codecs_;
    uint64_t bandWidth_ {};
    int width_ {}, height_ {};
    std::shared_ptr<M3U8> m3u8_;  // 关联 Media Playlist
    std::list<std::shared_ptr<M3U8Media>> audioMedia_;  // 音频轨列表
    std::list<std::shared_ptr<M3U8Media>> subtitlesMedia_;  // 字幕轨列表
    std::shared_ptr<M3U8Media> defaultAudio_;   // 默认音频轨
    std::shared_ptr<M3U8Media> defaultSubtitles_;  // 默认字幕轨
    uint32_t streamId_ {0};
};
```

**证据**：`m3u8.h:175-191` — M3U8VariantStream 包含 audioMedia_/subtitlesMedia_ 列表和 defaultAudio_/defaultSubtitles_ 默认轨指针。

---

### 12. M3U8Media 轨数据结构（m3u8.h:L155-173）

```cpp
struct M3U8Media {
    M3U8MediaType type_ {M3U8MediaType::M3U8_MEDIA_TYPE_INVALID};
    std::string groupID_;
    std::string name_;
    std::string lang_;
    std::string uri_;
    std::string originCodec_;
    std::string channels_;
    bool isDefault_ {false};
    bool autoSelect_ {false};
    bool forced_ {false};
    std::shared_ptr<M3U8> m3u8_;  // 关联 Media Playlist
    uint32_t streamId_ {0};
    uint64_t sessionKeyIndex_ {0};
};
```

**证据**：`m3u8.h:155-173` — M3U8Media 描述单轨（type/groupID/lang/streamId），isDefault_/autoSelect_ 标记默认/自动选择属性。

---

### 13. M3U8MasterPlaylist 主播放列表（m3u8.h:L193-246）

```cpp
struct M3U8MasterPlaylist {
    std::list<std::shared_ptr<M3U8VariantStream>> variants_;  // 变体列表
    std::shared_ptr<M3U8VariantStream> defaultVariant_;  // 默认变体（最高带宽）
    std::list<std::shared_ptr<M3U8Media>> audioList_;   // 全局音频轨
    std::list<std::shared_ptr<M3U8Media>> subtitlesList_;  // 全局字幕轨
    std::atomic<bool> isFmp4_ {false};
    std::atomic<bool> isPureByteRange_ {false};
    uint32_t defaultStreamId_ {0};
    void CreateVariantStream(const std::shared_ptr<Tag>& tag);
    void ChooseStreamByResolution();
    void ChooseStreamByStream(int32_t streamId);
};
```

**证据**：`m3u8.h:193-246` — M3U8MasterPlaylist 管理所有变体和全局音字幕轨，isFmp4_ 标记 fMP4 分片格式。

---

### 14. HlsSegmentType 与 streamIds 集合映射（hls_playlist_downloader.cpp:L1037-1049）

```cpp
// 获取音视频字幕流信息
void HlsPlayListDownloader::GetStreamInfo(std::vector<StreamInfo>& streams, bool isUpdate)
{
    for (const auto& media : currentVariant_->audioMedia_) {
        // audioStreamIds_ / subtitlesStreamIds_ 集合维护
        if (isDefault && currentVariant_->defaultAudio_ != nullptr &&
            media->streamId_ == currentVariant_->defaultAudio_->streamId_) {
            // isDefault = true 标记
        }
    }
}
```

**证据**：`hls_playlist_downloader.cpp:1037-1049` — streamIds 集合在 GetStreamInfo 时填充，用于 GetSegType 判定。

---

### 15. AES-128 DRM 密钥切换（hls_playlist_downloader.cpp:L404-444）

```cpp
uint64_t HlsPlayListDownloader::KeyChange(std::list<std::shared_ptr<M3U8Fragment>>& files)
{
    aesDecryptorManager_ = std::make_shared<AesDecryptorManager>();
    // 创建所有 segment 密钥对应解密器
    aesDecryptorManager_->CreateAesDecryptorByKeyInfos(keyInfos);
}
std::shared_ptr<AesDecryptor> HlsPlayListDownloader::GetAesDecryptor(uint64_t keyIndex)
{
    return aesDecryptorManager_->GetAesDecryptorByKeyIndex(keyIndex);
}
```

**证据**：`hls_playlist_downloader.cpp:404-444` — KeyChange 按 keyInfos 创建所有密钥解密器，GetAesDecryptor 按需获取。

---

### 16. fMP4 / ByteRange 差异化解析路径（hls_playlist_downloader.cpp:L508-527）

```cpp
void HlsPlayListDownloader::CopyFragmentInfo(PlayInfo& playInfo, std::shared_ptr<M3U8Fragment> file, ...)
{
    if (master_ && currentVariant_ && (master_->isFmp4_.load() || master_->isPureByteRange_.load())) {
        // fMP4 / ByteRange 分片：使用 rangeUrl/offset/length
    }
}
void HlsPlayListDownloader::UpdateMasterInfo(bool isPreParse)
{
    master_->isFmp4_ = m3u8->isHeaderReady_.load();
    master_->isPureByteRange_.store(m3u8->isPureByteRange_.load());
}
```

**证据**：`hls_playlist_downloader.cpp:508-527` — isFmp4_/isPureByteRange_ 驱动 ByteRange 分片差异化处理路径。

---

### 17. SetDefaultStreamId 三轨默认 ID 设置（hls_playlist_downloader.cpp:L583-606）

```cpp
void HlsPlayListDownloader::SetDefaultStreamId(int32_t &videoStreamId, int32_t &audioStreamId, int32_t &subTitleStreamId)
{
    if (audioStreamId == -1 && currentVariant_ != nullptr && currentVariant_->defaultAudio_ != nullptr) {
        audioStreamId = currentVariant_->defaultAudio_->streamId_;  // 默认音频轨
    }
    if (subTitleStreamId == -1 && currentVariant_ != nullptr && currentVariant_->defaultSubtitles_ != nullptr) {
        subTitleStreamId = currentVariant_->defaultSubtitles_->streamId_;  // 默认字幕轨
    }
}
```

**证据**：`hls_playlist_downloader.cpp:583-606` — SetDefaultStreamId 在播放开始前设置三轨默认 streamId。

---

### 18. M3U8MediaType 与 kTypeMap 映射（m3u8.cpp:L47-51）

```cpp
static const std::unordered_map<std::string, M3U8MediaType> kTypeMap = {
    {"AUDIO", M3U8MediaType::M3U8_MEDIA_TYPE_AUDIO},
    {"VIDEO", M3U8MediaType::M3U8_MEDIA_TYPE_VIDEO},
    {"SUBTITLES", M3U8MediaType::M3U8_MEDIA_TYPE_SUBTITLES},
    {"CLOSED-CAPTIONS", M3U8MediaType::M3U8_MEDIA_TYPE_CLOSED_CAPTIONS}
};
```

**证据**：`m3u8.cpp:47-51` — M3U8 标签解析时 EXT-X-MEDIA 的 TYPE 属性通过 kTypeMap 映射到 M3U8MediaType 枚举。

---

### 19. M3U8VariantStream 构造函数 streamId 分配（m3u8.cpp:L857-915）

```cpp
M3U8VariantStream::M3U8VariantStream(const std::string &name, const std::string &uri, std::shared_ptr<M3U8> m3u8)
{
    // ...
    auto stream = std::make_shared<M3U8VariantStream>(uri_, uri_, m3u8);
    stream->streamId_ = ++defaultStreamId_;  // streamId 递增分配
    defaultVariant_ = stream;  // 第一个变体设为默认
}
```

**证据**：`m3u8.cpp:857-915` — VariantStream 和 Media 的 streamId_ 通过 `++defaultStreamId_` 全局递增分配，保证全 Playlist 唯一。

---

### 20. SelectBitRate 码率切换与 Variant 变更（hls_playlist_downloader.cpp:L754-792）

```cpp
void HlsPlayListDownloader::SelectBitRate(uint32_t bitRate)
{
    // 遍历 master_->variants_ 找到带宽最接近 bitRate 的变体
    // newVariant_ = 目标变体，下载器切换到新 URL
}
```

**证据**：`hls_playlist_downloader.cpp:754-792` — SelectBitRate 触发 newVariant_ 赋值，下载器重建后触发 OnMasterReady 回调。

---

## 架构关系

```
M3U8MasterPlaylist
  ├── variants_: list<M3U8VariantStream>   (多码率变体列表)
  │     ├── defaultVariant_: M3U8VariantStream
  │     ├── audioMedia_: list<M3U8Media>  (变体内音频轨)
  │     ├── subtitlesMedia_: list<M3U8Media>  (变体内字幕轨)
  │     ├── defaultAudio_: M3U8Media
  │     └── defaultSubtitles_: M3U8Media
  ├── audioList_: list<M3U8Media>  (全局音频轨)
  └── subtitlesList_: list<M3U8Media>  (全局字幕轨)

HlsPlayListDownloader
  ├── master_: shared_ptr<M3U8MasterPlaylist>
  ├── currentVariant_: shared_ptr<M3U8VariantStream>
  ├── currentAudio_: shared_ptr<M3U8Media>
  ├── currentSubtitles_: shared_ptr<M3U8Media>
  ├── SelectMedia(streamId, mediaType)  →  currentAudio_/currentSubtitles_ 切换
  ├── SetDefaultMedia(mediaType)        →  从 defaultVariant_->defaultAudio_ 读取
  └── GetDefaultMediaStreamId(mediaType) →  返回 streamId 或 -1
```

---

## 关键对比

| 维度 | S106 (Source) | S37 (HttpSourcePlugin) | **S182 (HlsPlayListDownloader)** |
|------|--------------|----------------------|-------------------------------|
| 层级 | Module 层 | Plugin 层 | **Playlist 下载器层** |
| 核心类 | Source | HttpSourcePlugin | **HlsPlayListDownloader** |
| 数据结构 | Source / ProtocolType | HttpSourcePlugin / MediaDownloader | **M3U8MasterPlaylist / VariantStream / Media** |
| 轨管理 | 无 | 无 | **三轨（VIDEO/AUDIO/SUBTITLE）streamId** |
| DRM | 无 | AES-128 | **AesDecryptorManager per-keyIndex** |
| fMP4 | 无 | 无 | **isFmp4_ / isPureByteRange_ 差异化** |

---

## 关联记忆

- **S106**（approved）：MediaEngine Source 模块，协议路由与 Plugin 管理（上游）
- **S37**（approved）：HttpSourcePlugin 统一入口，HLS/DASH 自适应流处理（入口）
- **S86**（approved）：MediaCachedBuffer RingBuffer 缓冲（底层）
- **S138/S153**（pending）：DASH MPD Parser 架构（并行自适应流）
- **S172**（pending）：HttpSourcePlugin 三路下载器工厂路由（插件路由）

---

## 源码文件清单

| 文件 | 行数 | 关键内容 |
|------|------|---------|
| `services/media_engine/plugins/source/http_source/hls/playlist_downloader.h` | 206 | HlsSegmentType / PlayListDownloader 基类 / PlayInfo / KeyInfo |
| `services/media_engine/plugins/source/http_source/hls/hls_playlist_downloader.cpp` | 1270 | SelectMedia / SetDefaultMedia / GetDefaultMediaStreamId / KeyChange / UpdateMedia |
| `services/media_engine/plugins/source/http_source/hls/hls_playlist_downloader.h` | 147 | HlsPlayListDownloader 类定义，五数据成员 |
| `services/media_engine/plugins/source/http_source/hls/m3u8.h` | 291 | M3U8Fragment / M3U8Media / M3U8VariantStream / M3U8MasterPlaylist |
| `services/media_engine/plugins/source/http_source/hls/m3u8.cpp` | 1435 | 解析器实现 / streamId 分配 / kTypeMap 映射 |