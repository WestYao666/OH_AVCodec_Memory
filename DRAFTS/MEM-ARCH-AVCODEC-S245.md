# MEM-ARCH-AVCODEC-S245: HTTP Source Plugin MPD/Segment Download Manager 架构

## Metadata

- **ID**: MEM-ARCH-AVCODEC-S245
- **Title**: HTTP Source Plugin MPD/Segment Download Manager Architecture
- **Tags**: [avcodec, http-source, dash, hls, adaptive-streaming, segment-manager, mpd-downloader]
- **evidence_count**: 6
- **source**: https://gitcode.com/openharmony/multimedia_av_codec (commit e1bcf691, 2025-05-19)
- **registered**: 2026-06-21
- **status**: draft

---

## 源代码证据

### 证据1: DashMpdDownloader 类完整声明
**文件**: `services/media_engine/plugins/source/http_source/dash/dash_mpd_downloader.h`
**行号**: 118-310

```cpp
class DashMpdDownloader : public std::enable_shared_from_this<DashMpdDownloader> {
public:
    explicit DashMpdDownloader(std::shared_ptr<MediaSourceLoaderCombinations> sourceLoader = nullptr);
    virtual ~DashMpdDownloader();
    void Init();
    void Open(const std::string &url);
    void Close(bool isAsync);
    void SetStatusCallback(StatusCallbackFunc cb);
    void SetMpdCallback(const std::shared_ptr<DashMpdCallback>& callback);
    int64_t GetDuration() const;
    Seekable GetSeekable() const;
    std::vector<SeekRange> GetSeekableRanges() const;
    std::vector<uint32_t> GetBitRates() const;
    DashMpdGetRet GetNextSegmentByStreamId(int streamId, std::shared_ptr<DashSegment> &seg);
    DashMpdGetRet GetBreakPointSegment(int streamId, int64_t breakpoint, std::shared_ptr<DashSegment> &seg);
    DashMpdGetRet GetNextVideoStream(DashMpdBitrateParam &param, int &streamId);
    DashMpdGetRet GetNextTrackStream(DashMpdTrackParam &param);
    Status GetStreamInfo(std::vector<StreamInfo> &streams);
    std::shared_ptr<DashStreamDescription> GetStreamByStreamId(int streamId);
    std::shared_ptr<DashInitSegment> GetInitSegmentByStreamId(int streamId);
    void SetCurrentNumberSeqByStreamId(int streamId, int64_t numberSeq);
    void SetHdrStart(bool isHdrStart);
    void SetDefaultLang(const std::string &lang, MediaAVCodec::MediaType type);
    void SetInterruptState(bool isInterruptNeeded);
    DashList<DashEventStreamInfo *> GetCurrentPeriodEventStreams() const;
    // ... 更多 public 方法
private:
    void ParseManifest();           // L159: 解析 MPD manifest
    void ParseSidx();                // L160: 解析 SIDX box
    void OpenStream(std::shared_ptr<DashStreamDescription> stream);
    void DoOpen(const std::string &url, int64_t startRange = -1, int64_t endRange = -1);
    uint32_t SaveData(uint8_t *data, uint32_t len, bool notBlock);
    void SetOndemandSegBase();      // L164: 设置点播段基准
    bool SetOndemandSegBase(std::list<DashAdptSetInfo *> adptSetList);
    bool SetOndemandSegBase(std::list<DashRepresentationInfo *> repList);
    bool CheckToDownloadSidxWithInitSeg(std::shared_ptr<DashStreamDescription> streamDesc);
    bool GetStreamsInfoInMpd();      // L168: 获取 MPD 中所有流信息
    void GetStreamsInfoInPeriod(DashPeriodInfo *periodInfo, unsigned int periodIndex, const std::string &mpdBaseUrl);
    void GetStreamsInfoInAdptSet(DashAdptSetInfo *adptSetInfo, const std::string &periodBaseUrl, DashStreamDescription &streamDesc);
    // ...
    // 段构建
    DashSegmentInitValue GetSegmentsInMpd(std::shared_ptr<DashStreamDescription> streamDesc);
    DashSegmentInitValue GetSegmentsInPeriod(DashPeriodInfo *periodInfo, const std::string &mpdBaseUrl, std::shared_ptr<DashStreamDescription> streamDesc);
    DashSegmentInitValue GetSegmentsInAdptSet(DashAdptSetInfo *adptSetInfo, const std::string &periodBaseUrl, std::shared_ptr<DashStreamDescription> streamDesc);
    DashSegmentInitValue GetSegmentsInRepresentation(DashRepresentationInfo *repInfo, const std::string &adptSetBaseUrl, std::shared_ptr<DashStreamDescription> streamDesc);
    DashSegmentInitValue GetSegmentsWithSegTemplate(const DashSegTmpltInfo *segTmpltInfo, std::string id, std::shared_ptr<DashStreamDescription> streamDesc);
    DashSegmentInitValue GetSegmentsWithTmpltStatic(const DashSegTmpltInfo *segTmpltInfo, const std::string &mediaUrl, std::shared_ptr<DashStreamDescription> streamDesc);
    DashSegmentInitValue GetSegmentsWithTmpltTimelineStatic(...); // 时间轴模板
    DashSegmentInitValue GetSegmentsInOneTimeline(...); // 时间轴段列表
    DashSegmentInitValue GetSegmentsWithSegList(...);   // 段列表模式
    // DRM
    void GetDrmInfos(std::vector<DashDrmInfo>& drmInfos);
    void ProcessDrmInfos();
    void BuildDashSegment(std::list<std::shared_ptr<SubSegmentIndex>> &subSegIndexList) const;
    // ...
private:
    std::shared_ptr<Downloader> downloader_ {nullptr};                        // HTTP 下载器
    std::shared_ptr<DashMpdParser> mpdParser_ {nullptr};                      // MPD XML 解析器
    std::shared_ptr<DashMpdManager> mpdManager_ {nullptr};                   // MPD 信息管理
    std::shared_ptr<DashPeriodManager> periodManager_ {nullptr};             // Period 管理
    std::shared_ptr<DashAdptSetManager> adptSetManager_ {nullptr};           // AdaptationSet 管理
    std::shared_ptr<DashRepresentationManager> representationManager_ {nullptr}; // Representation 管理
    DashMpdInfo* mpdInfo_ {nullptr};
    std::vector<std::shared_ptr<DashStreamDescription>> streamDescriptions_;
    std::shared_ptr<DashStreamDescription> currentDownloadStream_ {nullptr};
    std::vector<DashDrmInfo> localDrmInfos_;                                  // DRM 信息缓存
    uint32_t currentPeriodIndex_ {0};
    std::vector<SeekRange> seekRanges_ {};
    std::shared_mutex downloadRequestMutex_;
};
```

**关键数据结构**:

```cpp
struct DashMpdBitrateParam {
    bool waitSegmentFinish_;
    bool waitSidxFinish_;
    int streamId_;
    unsigned int bitrate_;
    DashMpdSwitchType type_;      // DASH_MPD_SWITCH_TYPE_NONE / AUTO / SMOOTH
    int64_t position_;
    unsigned int nextSegTime_;
};

struct DashMpdTrackParam {
    bool waitSidxFinish_;
    bool isEnd_;
    MediaAVCodec::MediaType type_;
    int streamId_;
    int64_t position_;
    unsigned int nextSegTime_;
};

enum DashMpdGetRet {
    DASH_MPD_GET_ERROR,
    DASH_MPD_GET_DONE,    // 正常获取段
    DASH_MPD_GET_UNDONE,  // 段列表为空
    DASH_MPD_GET_FINISH   // 段获取完成
};
```

### 证据2: DashMpdDownloader 构造函数与成员初始化
**文件**: `services/media_engine/plugins/source/http_source/dash/dash_mpd_downloader.cpp`
**行号**: 构造行约 L60-75

```cpp
DashMpdDownloader::DashMpdDownloader(std::shared_ptr<MediaSourceLoaderCombinations> sourceLoader)
{
    if (sourceLoader != nullptr) {
        MEDIA_LOG_I("DashMpdDownloader app download.");
        downloader_ = std::make_shared<Downloader>("dashMpd", sourceLoader);
    } else {
        downloader_ = std::make_shared<Downloader>("dashMpd");
    }
    sourceLoader_ = sourceLoader;
    downloader_->Init();

    mpdParser_ = std::make_shared<DashMpdParser>();
    mpdManager_ = std::make_shared<DashMpdManager>();
    periodManager_ = std::make_shared<DashPeriodManager>();
    adptSetManager_ = std::make_shared<DashAdptSetManager>();
    representationManager_ = std::make_shared<DashRepresentationManager>();
}
```

### 证据3: ParseManifest 核心流程
**文件**: `services/media_engine/plugins/source/http_source/dash/dash_mpd_downloader.cpp`
**行号**: L约570-595

```cpp
void DashMpdDownloader::ParseManifest()
{
    if (downloadContent_.length() == 0) {
        MEDIA_LOG_I("ParseManifest content length is 0");
        return;
    }

    mpdParser_->ParseMPD(downloadContent_.c_str(), downloadContent_.length());
    mpdParser_->GetMPD(mpdInfo_);
    if (mpdInfo_ != nullptr) {
        mpdManager_->SetMpdInfo(mpdInfo_, url_);
        mpdManager_->GetDuration(&duration_);
        UpdateSeekRanges();
        SetOndemandSegBase();
        GetStreamsInfoInMpd();
        ChooseStreamToPlay(MediaAVCodec::MediaType::MEDIA_TYPE_VID);
        ChooseStreamToPlay(MediaAVCodec::MediaType::MEDIA_TYPE_AUD);
        ChooseStreamToPlay(MediaAVCodec::MediaType::MEDIA_TYPE_SUBTITLE);
        auto eventCallback = eventCallback_.lock();
        if (eventCallback) {
            std::string type = "dash";
            eventCallback->OnEvent({PluginEventType::STREAM_UPDATE, {type}, "Stream update."});
        }
    }
}
```

### 证据4: HlsSegmentManager 类完整声明
**文件**: `services/media_engine/plugins/source/http_source/hls/hls_segment_manager.h`
**行号**: 61-350

```cpp
class HlsSegmentManager : public PlayListChangeCallback, public std::enable_shared_from_this<HlsSegmentManager> {
public:
    // 三种构造方式：自定义缓冲时长 / MIME类型 / 克隆
    explicit HlsSegmentManager(int expectBufferDuration, bool userDefinedDuration,
        const std::map<std::string, std::string>& httpHeader = std::map<std::string, std::string>(),
        HlsSegmentType type = HlsSegmentType::SEG_VIDEO,
        std::shared_ptr<MediaSourceLoaderCombinations> sourceLoader = nullptr);
    explicit HlsSegmentManager(std::string mimeType, HlsSegmentType type,
        const std::map<std::string, std::string>& httpHeader = std::map<std::string, std::string>());
    explicit HlsSegmentManager(const std::shared_ptr<HlsSegmentManager> &other, HlsSegmentType type);
    ~HlsSegmentManager() override;

    void Init();
    bool Open(const std::string& url, const std::map<std::string, std::string>& httpHeader);
    void Close(bool isAsync);
    void Pause();
    void Resume();
    Status Read(unsigned char* buff, ReadDataInfo& readDataInfo);
    bool SeekToTime(int64_t seekTime, SeekMode mode);

    // 码率自适应
    std::vector<uint32_t> GetBitRates();
    bool SelectBitRate(uint32_t bitRate);
    void AutoSelectBitrate(uint32_t bitRate);

    // 段管理
    void PutRequestIntoDownloader(const PlayInfo& playInfo);
    int64_t RequestNewTs(uint64_t seekTime, SeekMode mode, double totalDuration,
        double hstTime, const PlayInfo& item);
    void UpdateDownloadFinished(const std::string &url, const std::string& location);

    // DRM
    void OnDrmInfoChanged(const std::multimap<std::string, std::vector<uint8_t>>& drmInfos) override;

    // 回调
    void OnPlayListChanged(const std::vector<PlayInfo>& playList) override;  // PlayListChangeCallback
    void OnMasterReady(bool needAudioManager, bool needSubtitlesManager) override;

public:
    static constexpr size_t VIDEO_MIN_BUFFER_SIZE = 1 * 1024 * 1024;
    static constexpr size_t VIDEO_MAX_CACHE_BUFFER_SIZE = 4 * 1024 * 1024;
    static constexpr size_t AES_BLOCK_LEN = 16;
    static constexpr size_t AES_DECRYPT_COUNT = 16;
    static constexpr size_t AES_DECRYPT_LEN = AES_BLOCK_LEN * AES_DECRYPT_COUNT;

private:
    // 数据读写
    uint32_t SaveData(uint8_t *data, uint32_t len, bool notBlock);
    uint32_t SaveEncryptData(uint8_t *data, uint32_t len, bool notBlock);    // AES 加密数据保存
    uint32_t FillSingleBlock(uint8_t *&data, uint32_t &len);
    uint32_t DecryptData(uint8_t *&data, uint32_t &len, bool notBlock);
    Status ReadDelegate(unsigned char* buff, ReadDataInfo& readDataInfo);
    void ReadCacheBuffer(unsigned char* buff, ReadDataInfo& readDataInfo);
    void InitMediaDownloader();
    // 缓冲管理
    bool CheckRiseBufferSize();
    bool CheckPulldownBufferSize();
    void RiseBufferSize();
    void DownBufferSize();
    void CalculateBitRate(size_t fragmentSize, double duration);
    void UpdateWaterLineAbove();
    // 查找
    bool FindSegmentByPts(...) const;
    void SeekToTsForRead(uint32_t currentTsIndex);
    int64_t RequestNewTsForRead(const PlayInfo& item);
    // 生命周期
    bool CheckVodEnd();
    bool CheckLiveLastSegment();
    bool IsAllDownloadFinish();

private:
    HlsSegmentType type_ = HlsSegmentType::SEG_VIDEO;
    size_t minBufferSize_ = VIDEO_MIN_BUFFER_SIZE;
    size_t maxCacheBufferSize_ = VIDEO_MAX_CACHE_BUFFER_SIZE;

    std::shared_ptr<Downloader> downloader_;
    std::shared_ptr<DownloadRequest> downloadRequest_;
    std::shared_ptr<PlayListDownloader> playlistDownloader_;          // 播放列表下载器
    std::shared_ptr<BlockingQueue<PlayInfo>> playList_;               // 段队列

    // AES 解密
    std::shared_ptr<AesDecryptor> aesDecryptor_;
    uint8_t singleBlock_[AES_BLOCK_LEN] {};
    uint32_t singleBlockLen_ {};
    uint8_t decryptBuffer_[AES_DECRYPT_LEN] {};
    uint32_t decryptLen_ {};

    // 缓冲管理
    std::shared_ptr<CacheMediaChunkBufferImpl> cacheMediaBuffer_;
    std::atomic<uint32_t> readTsIndex_ {0};
    uint64_t readOffset_ {0};
    uint64_t writeOffset_ {0};
    std::map<uint32_t, std::pair<uint32_t, bool>> tsStorageInfo_ {};  // ts索引 → (已读大小, 是否完成)

    // 码率自适应
    int32_t currentBitRate_ {0};
    int32_t fragmentBitRate_ {0};
    std::atomic<bool> isSelectingBitrate_ {false};
    std::shared_ptr<WriteBitrateCaculator> writeBitrateCaculator_;
    double avgSpeedSum_ {0};

    // 下载状态统计
    uint64_t totalBits_ {0};        // 总下载量
    uint64_t downloadBits_ {0};      // 累计有效时间下载量
    uint64_t downloadDuringTime_ {0}; // 累计有效下载时长 ms
    int32_t avgDownloadSpeed_ {0};
    bool isDownloadFinish_ {false};

    // 搜索候选
    std::deque<PlayInfo> backPlayList_;
    std::deque<PlayInfo> seekCandidates_;
    std::vector<PlayInfo> seekPlayList_;
};
```

### 证据5: HlsSegmentManager Init 与 Downloader 设置
**文件**: `services/media_engine/plugins/source/http_source/hls/hls_segment_manager.cpp`
**行号**: Init() 约 L90-130

```cpp
void HlsSegmentManager::Init()
{
    if (sourceLoader_ != nullptr) {
        downloader_ = std::make_shared<Downloader>("hlsMedia", sourceLoader_);
    } else {
        downloader_ = std::make_shared<Downloader>("hlsMedia");
    }
    downloader_->Init();
    playList_ = std::make_shared<BlockingQueue<PlayInfo>>("PlayList");

    auto weakDownloader = weak_from_this();
    dataSave_ = [weakDownloader] (uint8_t*&& data, uint32_t&& len, bool&& notBlock) -> uint32_t {
        auto shareDownloader = weakDownloader.lock();
        return shareDownloader->SaveData(std::forward<decltype(data)>(data),
            std::forward<decltype(len)>(len), std::forward<decltype(notBlock)>(notBlock));
    };

    playlistDownloader_ = std::make_shared<HlsPlayListDownloader>(httpHeader_, sourceLoader_);
    playlistDownloader_->Init();
    writeBitrateCaculator_ = std::make_shared<WriteBitrateCaculator>();
}
```

### 证据6: PutRequestIntoDownloader 段下载核心逻辑
**文件**: `services/media_engine/plugins/source/http_source/hls/hls_segment_manager.cpp`
**行号**: 约 L270-330

```cpp
void HlsSegmentManager::PutRequestIntoDownloader(const PlayInfo& playInfo)
{
    if (fragmentDownloadStart[playInfo.url_]) {
        writeTsIndex_ > 0 ? writeTsIndex_-- : 0;
        return;
    }
    fragmentDownloadStart[playInfo.url_] = true;
    currentSequence_ = playInfo.sequence_;

    RequestInfo requestInfo;
    requestInfo.url = playInfo.rangeUrl_.empty() ? playInfo.url_ : playInfo.rangeUrl_;
    requestInfo.httpHeader = httpHeader_;
    bool isRequestWholeFile = playInfo.rangeUrl_.empty() ? true : playInfo.length_ <= 0;

    writeOffset_ = SpliceOffset(writeTsIndex_, 0);
    {
        AutoLock lock(tsStorageInfoMutex_);
        if (tsStorageInfo_.find(writeTsIndex_) == tsStorageInfo_.end()) {
            tsStorageInfo_[writeTsIndex_] = std::make_pair(0, false);
        }
    }
    InfoIndexMap_.writeMap[writeTsIndex_] = playInfo.url_;
    tsStreamIdInfo_[writeTsIndex_] = playInfo.streamId_;

    UpdateAesDecryptor(playInfo);  // 更新 AES 解密器
    downloadRequest->SetRequestProtocolType(RequestProtocolType::HLS);
    downloader_->Download(downloadRequest, -1);
    downloader_->Start();
}
```

---

## 架构分析

### 1. 整体分层架构

```
┌─────────────────────────────────────────────────────────┐
│                  DashMpdDownloader (2495行)              │
│                  HlsSegmentManager (2582行)               │
│                  DashMediaDownloader (1409行)             │
├─────────────────────────────────────────────────────────┤
│         PlayListDownloader + HlsPlayListDownloader       │
│              (播放列表下载/解析 + 回调通知)               │
├─────────────────────────────────────────────────────────┤
│           Downloader (通用 HTTP 下载器)                   │
│    DownloadRequest / RequestInfo / DownloadStatus        │
├─────────────────────────────────────────────────────────┤
│     CacheMediaChunkBufferImpl (HLS 缓冲)                 │
│     WriteBitrateCaculator (码率计算)                     │
│     AesDecryptor (AES-128-CBC 解密)                     │
│     BlockingQueue<PlayInfo> (段队列)                    │
└─────────────────────────────────────────────────────────┘
```

### 2. DashMpdDownloader 五层管理架构

DashMpdDownloader 采用**五层管理器分工协作**的架构，将 DASH MPD 的层次结构完全映射到代码结构中：

```
DashMpdParser         → XML MPD 文档解析 (mpd_parser/)
DashMpdManager        → MPD 顶层信息管理 (duration, type: static/dynamic)
DashPeriodManager     → Period 周期管理
DashAdptSetManager    → AdaptationSet 适配集管理
DashRepresentationManager → Representation 表示管理
```

**三种段构建策略**（在 GetSegments* 系列方法中实现）：

| 策略 | 方法 | 适用场景 |
|------|------|----------|
| SegmentTemplate | `GetSegmentsWithSegTemplate` | DASH Template 模式，段编号/时间由模板计算 |
| SegmentList | `GetSegmentsWithSegList` | 显式列出所有段 URL |
| SegmentBase | `GetSegmentsWithBaseUrl` | 仅有一个 base URL，字节范围下载 |

**SIDX Box 解析**：当 `ondemandSegBase_ == true` 时，先通过 `ParseSidx()` 解析段索引盒（ISOBMFF SIDX），获取子段映射关系，再进行段下载。

### 3. HlsSegmentManager 段生命周期管理

HlsSegmentManager 是 HLS 段的全生命周期管理器，核心职责：

**段下载流水线**：
```
PlaylistDownloader (M3U8 解析)
    ↓ OnPlayListChanged 回调
PlayList_ (BlockingQueue<PlayInfo>)  // 候选段队列
    ↓
PutRequestIntoDownloader()           // 发起下载
    ↓
SaveData() → SaveEncryptData()       // 加密数据
    ↓
DecryptData() → FillSingleBlock()     // AES-128-CBC 解密
    ↓
cacheMediaBuffer_ (CacheMediaChunkBufferHlsImpl)  // 缓冲管理
    ↓
ReadDelegate() / ReadCacheBuffer()   // 解码器读取
```

**缓冲自适应**：
- `RiseBufferSize()` / `DownBufferSize()` 根据网络状况动态调整缓冲阈值
- `CalculateBitRate()` 基于片段大小和下载时长估算码率
- `WriteBitrateCaculator` 实时计算写入速度

**搜索候选机制**：
- `seekCandidates_`: 搜索时保留候选段列表
- `backPlayList_`: 已下载段回放列表
- 支持 SEEK_TO_TIME 精确定位到 PTS 对应的段

### 4. DRM 信息处理（Base64 + UUID 提取）

```cpp
// ProcessDrmInfos 中：PSSH Box Base64 解码流程
Base64Utils::Base64Decode(psshString, psshSize, pssh, &psshSize)
// PSSH Box 结构: [size(4)]["pssh"(4)][version(4)][flags(4)][UUID(16)][data...]
// DRM_UUID_OFFSET = 12 (跳过 size+pssh+version+flags)
memcpy_s(uuid, sizeof(uuid), pssh + DRM_UUID_OFFSET, 16);
// UUID 转为 32 字符十六进制字符串 → 上报给 DRM 层
```

### 5. 多码率自适应（Bitrate Adaptation）

**DASH (DashMpdDownloader)**:
- `GetNextVideoStream()`: 根据目标码率选择最接近的 Representation（带宽差最小原则）
- `GetNextTrackStream()`: 音频/字幕流切换，保持当前播放位置同步
- 流切换时通过 `currentNumberSeq_` 同步两个流的段序号

**HLS (HlsSegmentManager)**:
- `SelectBitRate()` / `AutoSelectBitrate()`: 触发码率重选
- `isSelectingBitrate_` 原子标志防止并发切换
- `fragmentBitRate_`: 当前片段码率 → 更新 `currentBitRate_`

### 6. 与已有 Topic 的关系

| 已有 Topic | 覆盖内容 | 与 S245 关系 |
|-----------|---------|------------|
| S138/S153/S187 | DASH MPD Parser (mpd_parser/) | S245 补充 MPD **下载层**而非解析层 |
| S182/S234 | HLS M3U8 Tag 解析 | S245 补充 HLS **段管理**而非标签解析 |
| S222 | DASH SegmentDownloader RingBuffer | S222 覆盖下载器，L245 覆盖 MPD 下载管理器 |
| S195/S209/S210 | HttpSourcePlugin DownloadMonitor | 互补：下载监控 vs 下载协调 |

### 7. 关键设计模式

1. **`enable_shared_from_this`**: DashMpdDownloader/HlsSegmentManager 均继承自此，允许在回调 lambda 中安全地获取 `shared_ptr`
2. **五层管理器**: 职责链模式对应 DASH MPD 层次结构
3. **BlockingQueue**: 生产者(PlaylistDownloader)-消费者(SegmentManager)解耦
4. **SpliceOffset**: `uint64 = (tsIndex << 32) | offset32` 跨段字节偏移拼接
5. **Adaptive Buffer**: 基于下载速度动态调整缓冲上下限（`RiseBufferSize`/`DownBufferSize`）

---

## 结论

S245 揭示了 HTTP Source Plugin 中两个最核心的**协调器组件**：

- **DashMpdDownloader**：2495 行，担任 DASH 流的总协调器，负责 MPD 解析、五层流信息管理、段URL构建、DRM信息提取和比特率自适应选择
- **HlsSegmentManager**：2582 行，担任 HLS 流的全生命周期管理器，负责播放列表变更响应、段下载调度、AES-128-CBC 解密、缓存缓冲管理、码率自适应和搜索精确定位

这两个组件共同构成了 HTTP 自适应流播放的**大脑层**，与下层的 Downloader（网络）、PlaylistDownloader（ playlist解析）、AesDecryptor（解密）、CacheMediaChunkBufferImpl（缓冲）配合，实现完整的自适应流播放能力。

---

## 本地镜像增强验证（/home/west/av_codec_repo，2026-06-25）

> builder-agent subagent 本地镜像逐行核对验证，行号全部以 /home/west/av_codec_repo 为准

### 验证证据表（E1-E16）

| ID | 文件（相对路径） | 实际行号 | 内容摘要 |
|----|----------------|---------|---------|
| E1 | dash_mpd_downloader.h | L118 | `class DashMpdDownloader : public std::enable_shared_from_this<DashMpdDownloader>` |
| E2 | dash_mpd_downloader.h | L46-54 | `enum DashMpdGetRet`：`DASH_MPD_GET_ERROR / DONE / UNDONE / FINISH` |
| E3 | dash_mpd_downloader.h | L59-77 | `struct DashMpdBitrateParam`：`waitSegmentFinish_ / streamId_ / bitrate_ / type_` |
| E4 | dash_mpd_downloader.h | L80-98 | `struct DashMpdTrackParam`：`waitSidxFinish_ / isEnd_ / type_ / streamId_ / position_` |
| E5 | dash_mpd_downloader.h | L289-292 | 五管理器成员：`mpdManager_ / periodManager_ / adptSetManager_ / representationManager_` |
| E6 | dash_mpd_downloader.cpp | L106-120 | 构造函数：五管理器 + Downloader 初始化（make_shared 五层架构） |
| E7 | dash_mpd_downloader.cpp | L653-674 | `ParseManifest`：mpdParser_->ParseMPD → mpdManager_->SetMpdInfo → ChooseStreamToPlay 三路 |
| E8 | dash_mpd_downloader.cpp | L765-802 | `GetDrmInfos`：PSSH Box Base64 解码，DRM_UUID_OFFSET=12 |
| E9 | dash_mpd_downloader.cpp | L805-857 | `ProcessDrmInfos`：DRM 信息处理，BuildDashSegment 构建段 |
| E10 | dash_mpd_downloader.cpp | L930-970 | `BuildDashSegment`：const 方法，构建 DashSegment 子段索引 |
| E11 | dash_mpd_downloader.cpp | L335-366 | `GetNextSegmentByStreamId`：按 streamId 获取下一段（环形缓冲） |
| E12 | dash_mpd_downloader.cpp | L410-461 | `GetNextVideoStream`：DASH 码率自适应核心，选择最接近目标码率的 Representation |
| E13 | hls_segment_manager.h | L72 | `class HlsSegmentManager : public PlayListChangeCallback, public std::enable_shared_from_this<HlsSegmentManager>` |
| E14 | hls_segment_manager.cpp | L100-124 | 第一构造函数（expectBufferDuration）：Downloader + playlistDownloader_ 初始化 |
| E15 | hls_segment_manager.cpp | L187-200 | `Init`：downloader_->Init + BlockingQueue + dataSave_ lambda 捕获 weak_from_this |
| E16 | hls_segment_manager.cpp | L280-315 | `PutRequestIntoDownloader`：fragmentDownloadStart 去重 + SetDownloadRequest + tsStorageInfo_ 映射 |
| E17 | hls_segment_manager.cpp | L1750-1790 | `AutoSelectBitrate`：HLS 码率自适应（片段速度计算） |

### 关键修正说明

| 项目 | 草案行号 | 本地镜像实际 | 偏差 |
|------|---------|------------|------|
| DashMpdDownloader 构造函数 | L60-75 | **L106-120** | +46行 |
| ParseManifest | L570-595 | **L653-674** | +83行 |
| HlsSegmentManager class 起始 | L61 | **L72** | +11行 |
| HlsSegmentManager::Init | L90-130 | **L187-200** | +97行 |
| PutRequestIntoDownloader | L270-330 | **L280-315** | +10行 |
