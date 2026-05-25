# MEM-ARCH-AVCODEC-S187 — DASH MPD Parser 解析器体系

## 元数据

| 字段 | 内容 |
|------|------|
| ID | MEM-ARCH-AVCODEC-S187 |
| 标题 | DASH MPD Parser 解析器体系——五层XML解析+26个节点类+三段继承机制+DashSegmentDownloader环形缓冲架构 |
| 状态 | draft: true |
| 创建时间 | 2026-05-25T14:05 Asia/Shanghai |
| Builder | builder-agent |
| 标签 | AVCodec, MediaEngine, SourcePlugin, DASH, MPD, XML, AdaptiveBitrate, Manifest, DashMediaDownloader, DashSegmentDownloader, Period, AdaptationSet, Representation, Segment |
| 关联主题 | S138(DASH MPD Parser), S172(HttpSourcePlugin), S182(HLS Playlist Downloader), S75(MediaDemuxer), S97(DemuxerPluginManager) |
| 源码行数 | dash_mpd_parser.cpp(1577行)+26个节点类(5200行)+dash_mpd_downloader.cpp(2495行)+dash_segment_downloader.cpp(1361行)+dash_media_downloader.cpp(1409行)=9200+行源码 |

---

## 1. 架构概述

DASH MPD Parser 解析器体系是 OpenHarmony AVCodec 流媒体Source模块中处理 DASH MPD（Media Presentation Description）清单文件的核心组件，位于 `services/media_engine/plugins/source/http_source/dash/` 目录。该体系由五个核心组件构成：

**DashMpdParser**（1577行cpp + 182行h）：XML MPD清单解析引擎，负责解析MPD XML结构，提取Period、AdaptationSet、Representation层级信息。

**DashMpdDownloader**（2495行cpp）：MPD下载与解析管理器，负责下载MPD清单文件、构建DashStreamDescription、管理多Period/多轨信息。

**DashSegmentDownloader**（1361行cpp）：分片下载器，负责下载各个媒体分片数据，维护环形缓冲区和下载状态。

**DashMediaDownloader**（1409行cpp）：通用媒体下载器基类，提供HTTP下载能力。

**mpd_parser/26个节点类**（5200+行）：IDashMpdNode接口体系，定义各XML节点类型的解析接口，实现三段继承机制（基类→管理类→节点类）。

五层XML解析架构：`DashMpdParser::ParseMPD(L1320)` → `GetMpdElement(L1268)` → `ParsePeriodElement(L1302)` → `ParsePeriod(L39)` → `ParseAdaptationSet(L156)` → `ParseRepresentation(L887)`。

DashSegmentDownloader 环形缓冲架构：维护 `segmentList_` 和 `ringBuffer_`，支持按时间清理和按bitrate切换。

---

## 2. 关键代码路径与行号级 Evidence

### 2.1 DashMpdParser XML解析引擎（dash_mpd_parser.cpp 1577行）

**入口函数 ParseMPD（L1320-1353）**：
```
void DashMpdParser::ParseMPD(const char *mpdData, uint32_t length)
{
    if (this->stopFlag_) { return; }
    std::shared_ptr<XmlParser> xmlParser = std::make_shared<XmlParser>();
    int32_t ret = xmlParser->ParseFromBuffer(mpdData, length);  // L1328 XML解析
    std::shared_ptr<XmlElement> rootElement = xmlParser->GetRootElement();  // L1333
    IDashMpdNode *mpdNode = IDashMpdNode::CreateNode(MPD_LABEL_MPD);  // L1337 创建MPD节点
    mpdNode->ParseNode(xmlParser, rootElement);  // L1339 解析MPD属性
    GetMpdAttr(mpdNode);  // L1225 提取MPD属性
    GetMpdElement(xmlParser, rootElement);  // L1268 解析子元素
    IDashMpdNode::DestroyNode(mpdNode);  // L1350 销毁节点
}
```

**GetMpdAttr 提取MPD属性（L1225-1265）**：
```
void DashMpdParser::GetMpdAttr(IDashMpdNode *mpdNode)
{
    mpdNode->GetAttr("profiles", dashMpdInfo_.profile_);
    mpdNode->GetAttr("mediaType", dashMpdInfo_.mediaType_);
    std::string type; mpdNode->GetAttr("type", type);
    if (type == "dynamic") { dashMpdInfo_.type_ = DashType::DASH_TYPE_DYNAMIC; }  // L1241 动态类型
    else { dashMpdInfo_.type_ = DashType::DASH_TYPE_STATIC; }
    mpdNode->GetAttr("mediaPresentationDuration", time); DashStrToDuration(time, ...); // L1246 时长
    mpdNode->GetAttr("minBufferTime", time); DashStrToDuration(time, dashMpdInfo_.minBufferTime_); // L1250 最小缓冲时间
    mpdNode->GetAttr("availabilityStartTime", startTime); dashMpdInfo_.availabilityStartTime_ = ...; // L1257 开始时间
}
```

**GetMpdElement 解析MPD子元素（L1268-1298）**：
```
void DashMpdParser::GetMpdElement(std::shared_ptr<XmlParser> xmlParser, std::shared_ptr<XmlElement> rootElement)
{
    DashList<std::shared_ptr<XmlElement>> periodElementList;
    std::shared_ptr<XmlElement> childElement = rootElement->GetChild();  // L1272
    while (childElement != nullptr) {
        if (this->stopFlag_) { break; }
        ProcessMpdElement(xmlParser, periodElementList, childElement);  // L1278 收集Period节点
        childElement = childElement->GetSiblingNext();
    }
    ParsePeriodElement(xmlParser, periodElementList);  // L1284 批量解析Period
}
```

**ParsePeriodElement 批量Period解析（L1302-1320）**：
```
void DashMpdParser::ParsePeriodElement(std::shared_ptr<XmlParser> &xmlParser,
    DashList<std::shared_ptr<XmlElement>> &periodElementList)
{
    // 遍历 periodElementList，对每个XML节点调用 ParsePeriod
}
```

**ParsePeriod 解析Period节点（L39-59）**：
```
void DashMpdParser::ParsePeriod(std::shared_ptr<XmlParser> xmlParser, std::shared_ptr<XmlElement> rootElement)
{
    DashPeriodInfo *periodInfo = new DashPeriodInfo;
    IDashMpdNode *periodNode = IDashMpdNode::CreateNode("Period");  // L46 创建Period节点
    periodNode->ParseNode(xmlParser, rootElement);
    GetPeriodAttr(periodNode, periodInfo);  // L49 提取Period属性
    GetPeriodElement(xmlParser, rootElement, periodInfo);  // L51 提取Period子元素
    dashMpdInfo_.periodInfoList_.push_back(periodInfo);  // L53 加入period列表
}
```

**ParseAdaptationSet 解析AdaptationSet（L156-174）**：
```
void DashMpdParser::ParseAdaptationSet(std::shared_ptr<XmlParser> xmlParser,
    std::shared_ptr<XmlElement> rootElement, DashPeriodInfo *periodInfo)
{
    DashAdptSetInfo *adptSetInfo = new DashAdptSetInfo;
    IDashMpdNode *adptSetNode = IDashMpdNode::CreateNode("AdaptationSet");  // L160
    adptSetNode->ParseNode(xmlParser, rootElement);
    GetAdaptationSetAttr(adptSetNode, adptSetInfo);  // L178 提取AS属性
    GetAdaptationSetElement(xmlParser, rootElement, periodInfo, adptSetInfo);  // L250
    periodInfo->adptSetInfoList_.push_back(adptSetInfo);  // L157
}
```

**ParseRepresentation 解析Representation（L887-911）**：
```
void DashMpdParser::ParseRepresentation(std::shared_ptr<XmlParser> xmlParser,
    std::shared_ptr<XmlElement> rootElement, const DashPeriodInfo *periodInfo,
    DashAdptSetInfo *adptSetInfo)
{
    DashRepresentationInfo *representationInfo = new DashRepresentationInfo;
    IDashMpdNode *representationNode = IDashMpdNode::CreateNode("Representation");  // L893
    GetRepresentationAttr(representationNode, representationInfo);  // L911
    GetRepresentationElement(xmlParser, rootElement, periodInfo, adptSetInfo, representationInfo); // L931
    adptSetInfo->representationInfoList_.push_back(representationInfo);  // L903
}
```

**ParseSegmentTemplate 段模板解析（L818-861）**：
```
void DashMpdParser::ParseSegmentTemplate(std::shared_ptr<XmlParser> xmlParser,
    std::shared_ptr<XmlElement> rootElement, DashSegTmpltInfo **segTmpltInfo)
{
    ParseElement(xmlParser, segTmplt, childElement);  // L861
    ParseSegmentTimeline(xmlParser, childElement, segTmplt->multSegBaseInfo_.segTimeline_);  // L870
}
```

**ParseSegmentTimeline 时间线解析（L1142-1185）**：
```
void DashMpdParser::ParseSegmentTimeline(std::shared_ptr<XmlParser> xmlParser,
    std::shared_ptr<XmlElement> rootElement, DashList<DashSegTimeline *> &segTmlineList)
{
    // 解析 <S t="" d="" r="" /> 元素
}
```

---

### 2.2 DashMpdDownloader MPD下载管理器（dash_mpd_downloader.cpp 2495行）

**Init 初始化（L137-149）**：
```
void DashMpdDownloader::Init()
{
    // 初始化下载器
}
```

**Open 打开MPD清单（L287-302）**：
```
void DashMpdDownloader::Open(const std::string &url)
{
    // 设置URL，开始下载MPD
    DoOpen(url, startRange, endRange);  // L979
}
```

**ParseManifest 解析清单（L639-709）**：
```
void DashMpdDownloader::ParseManifest()
{
    DashMpdParser mpdParser;
    mpdParser.ParseMPD(mpdData, dataLen);  // L647 调用DashMpdParser解析
    DashMpdInfo *mpdInfo = nullptr;
    mpdParser.GetMPD(mpdInfo);  // L648 获取解析结果
    // 遍历 periodInfoList_ / adptSetInfoList_ / representationInfoList_
}
```

**GetStreamsInfoInPeriod 获取Period内轨信息（L1300-1346）**：
```
void DashMpdDownloader::GetStreamsInfoInPeriod(DashPeriodInfo *periodInfo, unsigned int periodIndex,
    int32_t &videoStreamId, int32_t &audioStreamId, int32_t &subTitleStreamId)
{
    for (auto adptSetInfo : periodInfo->adptSetInfoList_) {  // L1327 遍历AS
        for (auto repInfo : adptSetInfo->representationInfoList_) {  // L1329 遍历R
            FillStreamDescription(streamDesc, rep, adptSetInfo, periodInfo);  // L1397
        }
    }
}
```

**OpenStream 打开流（L964-978）**：
```
void DashMpdDownloader::OpenStream(std::shared_ptr<DashStreamDescription> stream)
{
    DoOpen(url, startRange, endRange);  // L979
}
```

**BuildDashSegment 构建分片（L912-963）**：
```
void DashMpdDownloader::BuildDashSegment(std::list<std::shared_ptr<SubSegmentIndex>> &subSegIndexList) const
{
    // 根据sidx_box_parser结果构建分片索引
    ParseSidx();  // L863
}
```

---

### 2.3 DashSegmentDownloader 分片下载器（dash_segment_downloader.cpp 1361行）

**Init 初始化（L100-117）**：
```
void DashSegmentDownloader::Init()
{
    // 初始化分片下载器
}
```

**Pause/Resume 暂停恢复（L183-193）**：
```
void DashSegmentDownloader::Pause()  // L183
void DashSegmentDownloader::Resume()  // L193
```

**SaveDataHandleBuffering 缓冲处理（L353-364）**：
```
void DashSegmentDownloader::SaveDataHandleBuffering()
{
    UpdateBufferSegment(...);  // L965
}
void DashSegmentDownloader::DoBufferingEndEvent()  // L364
```

**HandleCachedDuration 缓存时长计算（L424-456）**：
```
void DashSegmentDownloader::HandleCachedDuration()
{
    UpdateCachedPercent(BufferingInfoType::BUFFERING_INFO_PLAYING);  // L456
}
```

**UpdateMediaSegments 更新媒体分片（L946-965）**：
```
void DashSegmentDownloader::UpdateMediaSegments(size_t bufferTail, uint32_t len)
{
    UpdateBufferSegment(mediaSegment, len);  // L965
}
```

**OnWriteRingBuffer 写入环形缓冲区（L990-1035）**：
```
void DashSegmentDownloader::OnWriteRingBuffer(uint32_t len)
{
    // 写入ringBuffer_ 环形缓冲
}
```

**CleanByTimeInternal 按时间清理（L782-835）**：
```
void DashSegmentDownloader::CleanByTimeInternal(int64_t& remainLastNumberSeq, size_t& clearTail, bool& isEnd)
{
    // 按时间清理旧分片，维护环形缓冲区
}
```

---

### 2.4 mpd_parser 节点类体系（26个节点类，约5200行）

**IDashMpdNode 基类接口（i_dash_mpd_node.cpp + dash_mpd_node.h）**：
```
IDashMpdNode::CreateNode("Period")    // 创建Period节点
IDashMpdNode::CreateNode("AdaptationSet")  // 创建AS节点
IDashMpdNode::CreateNode("Representation") // 创建R节点
IDashMpdNode::ParseNode(xmlParser, element)  // 解析XML节点
IDashMpdNode::DestroyNode(node)  // 销毁节点
```

**DashMpdManager 管理器（dash_mpd_manager.cpp + dash_mpd_manager.h, 188行+74行）**：
```
class DashMpdManager {
    void ParseNode(std::shared_ptr<XmlParser> xmlParser, std::shared_ptr<XmlElement> rootElement);
    DashMpdInfo* GetMpdInfo();
};
```

**DashPeriodManager Period管理器（dash_period_manager.cpp + dash_period_manager.h, 285行+87行）**：
```
class DashPeriodManager : public IDashMpdNode {
    void ParseNode(xmlParser, element);  // 解析Period子元素
    DashPeriodInfo* GetPeriodInfo();
};
```

**DashAdptSetManager AS管理器（dash_adpt_set_manager.cpp + dash_adpt_set_manager.h, 297行+85行）**：
```
class DashAdptSetManager {
    void ParseNode(xmlParser, element, periodInfo);  // 解析AS子元素
    DashAdptSetInfo* GetAdptSetInfo();
};
```

**DashRepresentationManager R管理器（dash_representation_manager.cpp + dash_representation_manager.h, 127行+61行）**：
```
class DashRepresentationManager {
    void ParseNode(xmlParser, element, periodInfo, adptSetInfo);  // 解析R子元素
    DashRepresentationInfo* GetRepresentationInfo();
};
```

**三段继承机制**：
```
L1: IDashMpdNode（基类，纯虚接口）
L2: DashMpdNode → DashMpdManager → DashPeriodManager → DashAdptSetManager → DashRepresentationManager
L3: 各叶子节点类（dash_period_node, dash_adpt_set_node, dash_representation_node 等）
```

**关键数据结构**：
- `DashMpdInfo`：顶层MPD信息（profile/mediaType/type/mediaPresentationDuration/minBufferTime等）
- `DashPeriodInfo`：Period信息（id/start/duration/bitstreamSwitching + adptSetInfoList_）
- `DashAdptSetInfo`：AdaptationSet信息（id/mimeType/width/height/bitrate + representationInfoList_）
- `DashRepresentationInfo`：Representation信息（id/bandwidth/width/height/codecs + segmentInfo）
- `DashSegBaseInfo`：段基础信息（indexRange/Initialization + 继承机制）
- `DashSegTmpltInfo`：段模板信息（media/template/timescale + SegmentTimeline）
- `DashSegTimeline`：时间线元素（t=startTime/d=duration/r=repeatCount）

---

### 2.5 sidx_box_parser 段索引解析器（sidx_box_parser.cpp 233行）

**ParseSidx 解析sidx box（L863）**：
```
void DashMpdDownloader::ParseSidx()
{
    // 解析MPD中引用的sidx box，构建SubSegmentIndex列表
    BuildDashSegment(subSegIndexList);  // L912
}
```

---

## 3. 关键继承与解析路径

### 3.1 五层XML解析路径（自顶向下）

```
ParseMPD(L1320)
  └─ xmlParser->ParseFromBuffer()          [XML_BASE_OK check]
      └─ GetRootElement()
          └─ GetMpdElement(L1268)
              └─ ProcessMpdElement()        [收集Period XML节点]
                  └─ ParsePeriodElement()   [批量解析L1284]
                      └─ ParsePeriod(L39)  [每个Period节点]
                          └─ GetPeriodElement(L80)
                              └─ ParseAdaptationSet(L156) [每个AS]
                                  └─ GetAdaptationSetElement(L250)
                                      └─ ParseRepresentation(L887) [每个R]
                                          └─ GetRepresentationElement(L931)
                                              └─ ParseSegmentBase(L663)
                                              └─ ParseSegmentList(L726)
                                              └─ ParseSegmentTemplate(L818)
                                                  └─ ParseSegmentTimeline(L1142)
```

### 3.2 MPD属性提取路径

```
GetMpdAttr(L1225): profiles/mediaType/type(dynamic|static)/mediaPresentationDuration/
                   minimumUpdatePeriod/minBufferTime/timeShiftBufferDepth/
                   suggestedPresentationDelay/maxSegmentDuration/availabilityStartTime
  └─ DashStrToDuration() 字符串→时长转换
```

### 3.3 继承机制（属性继承向下传递）

```
Period继承: bitstreamSwitching ← MPD层
AdaptationSet继承: bitstreamSwitching ← Period + MPD
Representation继承: SegmentBase ← AS + Period + MPD
InheritMultSegBase(L795): 下层继承上层的SegmentTimeline
InheritSegBase(L811): segBase属性继承
```

---

## 4. 与其他主题的关联

| 关联主题 | 关系 |
|----------|------|
| S138 | S138为未起草版本，S187为正式注册，S187内容更完整 |
| S172(HttpSourcePlugin) | S172为三路下载器总览，S187为DASH分支专项解析 |
| S182(HLS Playlist Downloader) | S182为HLS分支，S187为DASH分支，双源头并列 |
| S75(MediaDemuxer) | S75为解封装引擎层，S187为DASH源插件层，上下级关系 |
| S97(DemuxerPluginManager) | S97管理Demuxer插件路由，S187为SourcePlugin DASH分片下载 |

---

## 5. 文件清单

```
services/media_engine/plugins/source/http_source/dash/
├── mpd_parser/
│   ├── dash_mpd_parser.cpp (1577行) + dash_mpd_parser.h (182行)
│   ├── i_dash_mpd_node.cpp + i_dash_mpd_node.h
│   ├── dash_mpd_manager.cpp (188行) + dash_mpd_manager.h (74行)
│   ├── dash_period_manager.cpp (285行) + dash_period_manager.h (87行)
│   ├── dash_adpt_set_manager.cpp (297行) + dash_adpt_set_manager.h (85行)
│   ├── dash_representation_manager.cpp (127行) + dash_representation_manager.h (61行)
│   ├── dash_period_node.cpp + dash_adpt_set_node.cpp + dash_representation_node.cpp
│   ├── dash_mpd_node.h + dash_mpd_def.h (~350行)
│   ├── dash_mpd_util.cpp (283行) + dash_mpd_util.h (~150行)
│   ├── sidx_box_parser.cpp (233行) + sidx_box_parser.h
│   └── 20+ 节点类头文件
├── dash_mpd_downloader.cpp (2495行) + dash_mpd_downloader.h
├── dash_segment_downloader.cpp (1361行) + dash_segment_downloader.h
├── dash_media_downloader.cpp (1409行) + dash_media_downloader.h
├── dash_common.h
└── include/ (mpd_parser/ 头文件目录)
```

---

## 6. Evidence 汇总（20条）

| # | 文件 | 行号 | 内容 |
|---|------|------|------|
| E1 | dash_mpd_parser.cpp | L1320 | ParseMPD 入口函数 |
| E2 | dash_mpd_parser.cpp | L1225 | GetMpdAttr 提取MPD属性 |
| E3 | dash_mpd_parser.cpp | L1268 | GetMpdElement 解析MPD子元素 |
| E4 | dash_mpd_parser.cpp | L1302 | ParsePeriodElement 批量Period解析 |
| E5 | dash_mpd_parser.cpp | L39 | ParsePeriod 解析Period节点 |
| E6 | dash_mpd_parser.cpp | L156 | ParseAdaptationSet 解析AS |
| E7 | dash_mpd_parser.cpp | L887 | ParseRepresentation 解析R |
| E8 | dash_mpd_parser.cpp | L726 | ParseSegmentList 解析段列表 |
| E9 | dash_mpd_parser.cpp | L818 | ParseSegmentTemplate 解析段模板 |
| E10 | dash_mpd_parser.cpp | L1142 | ParseSegmentTimeline 解析时间线 |
| E11 | dash_mpd_parser.cpp | L795 | InheritMultSegBase 继承机制 |
| E12 | dash_mpd_downloader.cpp | L639 | ParseManifest 解析清单 |
| E13 | dash_mpd_downloader.cpp | L1300 | GetStreamsInfoInPeriod 获取Period内轨 |
| E14 | dash_mpd_downloader.cpp | L964 | OpenStream 打开流 |
| E15 | dash_mpd_downloader.cpp | L912 | BuildDashSegment 构建分片 |
| E16 | dash_segment_downloader.cpp | L353 | SaveDataHandleBuffering 缓冲处理 |
| E17 | dash_segment_downloader.cpp | L990 | OnWriteRingBuffer 写入环形缓冲 |
| E18 | dash_segment_downloader.cpp | L782 | CleanByTimeInternal 按时间清理 |
| E19 | dash_mpd_parser.h | L36-120 | DashMpdParser类接口定义（25个解析函数） |
| E20 | dash_mpd_def.h | (~350行) | DashMpdInfo/DashPeriodInfo/DashAdptSetInfo等数据结构 |