---
type: architecture
id: MEM-ARCH-AVCODEC-S138
status: pending_approval
created_at: "2026-05-15T02:43:09+08:00"
updated_at: "2026-05-15T02:43:09+08:00"
created_by: builder
topic: DASH MPD 解析器架构——DashMpdParser 1577行核心引擎与 mpd_parser 子目录 26个节点类
scope: [AVCodec, MediaEngine, SourcePlugin, DASH, MPD, XML, Parser, AdaptiveBitrate, Manifest, DashMediaDownloader, DashSegmentDownloader, Period, AdaptationSet, Representation, Segment, M3U8, HTTP]
created_at: "2026-05-15T02:43:09+08:00"
summary: DASH MPD 解析器五层架构（DashMpdParser→DashMpdNode→DashMpdManager→DashPeriodManager→DashAdptSetManager），26个XML节点类处理Period/AdaptationSet/Representation/Segment四层结构，与HlsMediaDownloader(S37)并列构成自适应流双源头
source_repo: /home/west/av_codec_repo
source_root: services/media_engine/plugins/source/http_source/dash
evidence_version: local_mirror
---

## 一、架构总览

DASH（Dynamic Adaptive Streaming over HTTP）MPD（Media Presentation Description）解析器位于 `services/media_engine/plugins/source/http_source/dash/mpd_parser/` 子目录，共26个节点类文件（1577行核心解析器 + 5200行节点类），负责将 MPD XML 文档解析为内存对象模型，供 `DashMediaDownloader` 和 `DashSegmentDownloader` 使用。

**定位**：HTTP Source 插件的 DASH 分支入口，与 HLS `m3u8.cpp`（1435行）并列，同属 `HttpSourcePlugin` 流媒体协议的两种自适应协议。

## 二、文件清单与行号级证据

| 文件 | 行数 | 说明 |
|------|------|------|
| `dash_mpd_parser.cpp` | 1577 | MPD 解析器核心引擎，XML→对象模型主入口 |
| `dash_mpd_parser.h` | ~150 | DashMpdParser 类定义（ParseMpd/ParsePeriod/ParseRepresentation 等） |
| `dash_mpd_node.cpp` | ~200 | MPD 根节点解析 |
| `dash_period_node.cpp` | ~120 | Period 节点解析 |
| `dash_adpt_set_node.cpp` | 128 | AdaptationSet 节点解析 |
| `dash_representation_node.cpp` | ~150 | Representation 节点解析 |
| `dash_seg_list_node.cpp` | 128 | SegmentList 分段列表 |
| `dash_seg_template_node.cpp` | 127 | SegmentTemplate 分段模板 |
| `dash_seg_base_node.cpp` | ~100 | 分段基类（SegmentBase） |
| `dash_mpd_manager.cpp` | 188 | MPD 管理器（Bitrate/Stream/Period 管理） |
| `dash_period_manager.cpp` | 285 | Period 管理器 |
| `dash_adpt_set_manager.cpp` | 297 | AdaptationSet 管理器 |
| `dash_representation_manager.cpp` | ~150 | Representation 管理器 |
| `dash_mpd_util.cpp` | 283 | MPD 工具函数（时间/URL 解析） |
| `dash_descriptor_node.cpp` | ~80 | Descriptor 描述符节点 |
| `dash_content_comp_node.cpp` | ~80 | ContentComponent 内容组件节点 |
| `dash_event_node.cpp` | ~80 | Event 事件节点 |
| `dash_event_stream_node.cpp` | ~80 | EventStream 事件流节点 |
| `dash_com_attrs_elements.cpp` | ~80 | CommonAttributes 公共属性 |
| `dash_break_duration_node.cpp` | ~80 | BreakDuration 断点时长 |
| `dash_splice_info_section_node.cpp` | ~80 | SpliceInfoSection 拼接信息 |
| `dash_splice_insert_node.cpp` | ~80 | SpliceInsert 拼接插入节点 |
| `dash_url_type_node.cpp` | ~80 | URLType 链接类型 |
| `dash_seg_url_node.cpp` | ~80 | SegmentURL 分段链接 |
| `dash_seg_tmline_node.cpp` | ~80 | SegmentTimeline 时间线节点 |
| `sidx_box_parser.cpp` | 233 | sidx box（Segment Index Box）解析器 |
| `i_dash_mpd_node.cpp` | ~50 | DashMpdNode 接口定义 |

### 核心类定义（dash_mpd_parser.h）

```cpp
// dash_mpd_parser.h 关键类
class DashMpdParser : public std::enable_shared_from_this<DashMpdParser> {
public:
    void ParseMpd(std::shared_ptr<XmlElement> rootElement);          // 行 39+
    void ParsePeriod(std::shared_ptr<XmlParser> xmlParser, std::shared_ptr<XmlElement> rootElement); // 行 39
    void ParseRepresentation(...);                                    // 行 887
    void ParsePeriodElement(...);                                    // 行 1302
    void StopParseMpd();                                             // 行 1394
};
```

## 三、五层解析架构

### 第一层：DashMpdParser（1577行核心引擎）

```cpp
// dash_mpd_parser.cpp:39 - 入口函数链
void DashMpdParser::ParsePeriod(...)
    // → 调用 ParseRepresentation(xmlParser, representationElement, periodInfo, adptSetInfo)
    
// dash_mpd_parser.cpp:305 - Representation 解析入口
void DashMpdParser::ParseRepresentation(...)
    // → adptSetInfo->AddRepresentation(representationNode)
    
// dash_mpd_parser.cpp:1280 - PeriodElement 解析
void DashMpdParser::ParsePeriodElement(...)
    // → ParsePeriod(xmlParser, periodElement)
```

### 第二层：DashMpdNode（根节点 + 子节点基类）

```cpp
// i_dash_mpd_node.cpp - 接口定义
class IDashMpdNode {
    virtual bool ParseNode(std::shared_ptr<XmlParser> xmlParser, 
                          std::shared_ptr<XmlElement> element) = 0;
    virtual std::shared_ptr<DashMpdNode> GetNode() = 0;
};

// dash_mpd_node.cpp - MPD 根节点
class DashMpdNode : public IDashMpdNode {
    std::shared_ptr<DashMpdInfo> mpdInfo_;  // MPD 信息（type/live/静态）
    std::vector<std::shared_ptr<DashPeriodInfo>> periods_;  // Period 列表
};
```

### 第三层：DashMpdManager（MPD 级管理）

```cpp
// dash_mpd_manager.cpp:188行 - MPD 管理器
class DashMpdManager {
    std::shared_ptr<DashMpdInfo> mpdInfo_;                          // 行内成员
    std::vector<std::shared_ptr<DashPeriodInfo>> periods_;           // Period 列表
    std::vector<DashBitrateInfo> bitrateInfos_;                      // 码率列表
    std::vector<DashStreamInfo> streamInfos_;                       // 流列表
    bool CollectBitrates();                                         // 收集所有码率
    bool CollectStreams();                                          // 收集所有流
};
```

### 第四层：DashPeriodManager（Period 级管理）

```cpp
// dash_period_manager.cpp:285行 - Period 管理器
class DashPeriodManager {
    std::shared_ptr<DashPeriodInfo> curPeriodInfo_;  // 当前 Period
    void UpdatePeriodInfo(const std::shared_ptr<DashPeriodInfo>& periodInfo);
    void CollectBitrates(std::vector<DashBitrateInfo>& bitrates);
    void CollectStreams(std::vector<DashStreamInfo>& streams);
};
```

### 第五层：DashAdptSetManager（AdaptationSet 级管理）

```cpp
// dash_adpt_set_manager.cpp:297行 - AdaptationSet 管理器
class DashAdptSetManager {
    std::shared_ptr<DashAdptSetInfo> adptSetInfo_;  // AdaptationSet 信息
    std::vector<std::shared_ptr<DashRepresentationInfo>> representations_;  // Representation 列表
    void UpdateAdptSetInfo(const std::shared_ptr<DashAdptSetInfo>& adptSet);
    DashBitrateInfo GetBitrateInfo();  // 获取当前码率信息
};
```

## 四、关键数据结构

### DashMpdTrackParam（mpd_downloader.h:80）

```cpp
// dash_mpd_downloader.h:80-98
struct DashMpdTrackParam {
    int32_t trackId_;           // 轨道 ID
    int32_t width_;            // 视频宽度
    int32_t height_;           // 视频高度
    uint32_t bitrate_;         // 码率
    std::string mimeType_;      // MIME 类型（video/mp4、audio/mp4）
    int64_t duration_;         // 时长（ms）
    std::string language_;      // 语言
    int64_t startNumberSeq_;    // 起始编号（MPD 中 startNumber 属性）
};

struct MediaSegSampleInfo {    // mpd_downloader.h:99-110
    int64_t timestamp_;         // 时间戳（ms）
    uint64_t duration_;         // 持续时间（ms）
    uint64_t mediaUrl_;         // 媒体 URL（偏移）
};
```

### DashMpdBitrateParam（mpd_downloader.h:59）

```cpp
// dash_mpd_downloader.h:59-78
struct DashMpdBitrateParam {
    uint32_t bitrate_;          // 码率（bps）
    int8_t type_;               // 类型（VIDEO/AUDIO/SUBTITLE）
    int8_t isLive_;             // 是否直播
    int64_t totalDuration_;     // 总时长
};
```

### DashBufferSegment（dash_segment_downloader.h:47）

```cpp
// dash_segment_downloader.h:47-138
struct DashBufferSegment {
    uint8_t* buffer_;           // 数据缓冲区
    uint32_t size_;            // 数据大小
    int64_t segmentSeq_;       // 段序号
    int64_t timestamp_;        // 时间戳（ms）
    uint32_t duration_;        // 持续时间（ms）
    MediaAVCodec::MediaType mediaType_;  // 媒体类型
    std::string url_;           // 段 URL
};
```

## 五、关键函数流程

### ParseMpd 主流程（dash_mpd_parser.cpp:1280）

```cpp
// dash_mpd_parser.cpp:1280 - 入口
void DashMpdParser::ParsePeriodElement(std::shared_ptr<XmlParser> &xmlParser,
                                       std::vector<std::shared_ptr<XmlElement>> &periodElementList)
{
    for (auto &periodElement : periodElementList) {
        // → ParsePeriod(xmlParser, periodElement)  // 行 1313
    }
}

// dash_mpd_parser.cpp:1313 - Period 解析
void DashMpdParser::ParsePeriod(xmlParser, periodElement)
{
    // → ParseAdaptationSet(xmlParser, periodElement, periodInfo)  // 内联
    // → ParseRepresentation(...)  // 行 305
}
```

### DashMediaDownloader::SelectBitRate（dash_media_downloader.cpp:342）

```cpp
// dash_media_downloader.cpp:342 - 码率切换
bool DashMediaDownloader::SelectBitRate(uint32_t bitrate)
{
    // bitrateParam_.bitrate_ = bitrate;
    // bitrateParam_.type_ = type;
    // PUBLIC_LOG_D32(bitrateParam_.bitrate_, bitrate);  // 调试日志
    // → DashSegmentDownloader::SelectBitRate(bitrate)  // 行 356
}
```

### DashSegmentDownloader 下载流程（dash_segment_downloader.cpp:123）

```cpp
// dash_segment_downloader.cpp:123 - 打开段
bool DashSegmentDownloader::Open(const std::shared_ptr<DashSegment>& dashSegment)
{
    // initSegment → rangeBegin_/rangeEnd_ → 下载初始化段
    // mediaSegment → 下载媒体段
    // → dataSave_(...) 回调写入 RingBuffer  // 行 105
}
```

## 六、与相关 S-series 记忆的关联

| 关联记忆 | 关系 | 说明 |
|---------|------|------|
| S37（HttpSourcePlugin） | 上游 | DASH 为 HttpSourcePlugin 三路下载器之一（m3u8→HlsMediaDownloader，mpd→DashMediaDownloader，plain→HttpMediaDownloader） |
| S38（SourcePlugin） | 上游 | SourcePlugin 基接口（Read/Seek/GetSize）被 DashMediaDownloader 继承 |
| S75（MediaDemuxer 六组件） | 下游 | MediaDemuxer 通过 StreamDemuxer PullData 消费 DASH 分片缓存 |
| S86（HLS缓存引擎） | 并列 | HlsMediaDownloader（HLS）+ DashMediaDownloader（DASH）构成双路流媒体源 |
| S101（StreamDemuxer） | 下游 | StreamDemuxer::PullData 读取 DASH 分片缓存，ProcInnerDash 处理分片合并 |
| S102（SampleQueueController） | 下游 | SampleQueueController 双水位线（START@5s/STOP@10s）控制 DASH 流控 |

## 七、DASH vs HLS 架构对比

| 维度 | DASH | HLS |
|------|------|-----|
| 描述文件格式 | XML（MPD） | M3U8（playlist） |
| 核心解析器 | DashMpdParser（1577行）+ 26节点类 | m3u8.cpp（1435行）+ hls_playlist_downloader（1270行） |
| 分片下载器 | DashSegmentDownloader（1361行） | HlsSegmentManager（2582行） |
| 码率适配 | DashAdptSetManager 多 Representation | HlsMediaDownloader SelectBitRate |
| 分段类型 | SegmentList / SegmentTemplate | EXT-X-KEY / EXTINF |
| 直播支持 | timeShiftBufferDepth | EXT-X-PLAYLIST-TYPE |
| DRM 支持 | PlayReady / Widevine / CENC | AES-128 |

---

_builder-agent: S138 draft generated 2026-05-15T02:43:09+08:00, pending approval_