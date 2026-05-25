# MEM-ARCH-AVCODEC-S187

## 草案信息

| 字段 | 内容 |
|------|------|
| mem_id | MEM-ARCH-AVCODEC-S187 |
| status | pending_approval |
| 主题 | DASH MPD Parser 解析器体系——DashMpdParser五层XML解析+26个节点类+三段继承机制+DashSegmentDownloader环形缓冲架构 |
| scope | AVCodec, MediaEngine, SourcePlugin, DASH, MPD, XML, AdaptiveBitrate, MPD, ISO-IEC23009-1 |
| 关联场景 | DASH流媒体播放 / 自适应码率切换 / MPD动态更新 |
| builder | builder-agent (subagent) |
| timestamp | 2026-05-25T14:05:00+08:00 |
| source_repo | https://gitcode.com/openharmony/multimedia_av_codec |
| 本地镜像 | /home/west/av_codec_repo/services/media_engine/plugins/source/http_source/dash/ |
| 关联 | S138(DASH MPD Parser), S172(HttpSourcePlugin), S182(HLS Playlist), S106(HLS+DASH自适应) |

---

## 一、源码文件清单及行数

### 1.1 MPD Parser 核心（mpd_parser/ 子目录，26个文件，5200行）

| 文件 | 行数 | 职责 |
|------|------|------|
| dash_mpd_parser.cpp | 1577 | MPD五层XML解析引擎，ParseMPD入口 |
| dash_mpd_parser.h | 182 | DashMpdParser类声明 |
| dash_mpd_manager.cpp | 188 | MPD数据管理器，Period遍历/BaseURL构建 |
| dash_mpd_manager.h | 74 | DashMpdManager类声明 |
| dash_adpt_set_manager.cpp | 297 | AdaptationSet管理器，Representation按带宽选轨 |
| dash_adpt_set_manager.h | 85 | DashAdptSetManager类声明 |
| dash_period_manager.cpp | 285 | Period管理器，切换Period获取时间范围 |
| dash_period_manager.h | 87 | DashPeriodManager类声明 |
| dash_representation_manager.cpp | 127 | Representation管理器，InitSegment解析 |
| dash_representation_manager.h | 61 | DashRepresentationManager类声明 |
| i_dash_mpd_node.cpp | 90 | IDashMpdNode工厂，CreateNode/DestroyNode |
| i_dash_mpd_node.h | 62 | IDashMpdNode纯虚基类，7种GetAttr模板 |
| dash_mpd_def.h | ~350 | MPD元素结构体定义（DashMpdInfo/DashPeriodInfo/DashAdptSetInfo/DashRepresentationInfo等） |
| dash_mpd_util.cpp | 283 | MPD工具函数（URL拼接/Duration解析/ColorInfo/BT2020） |
| dash_mpd_util.h | ~150 | DashMpdUtil工具函数声明 |
| dash_manager_util.cpp | 40 | Manager层通用工具 |
| dash_manager_util.h | ~40 | ManagerUtil声明 |
| sidx_box_parser.cpp | 233 | MP4 sidx box解析器，Segment索引box |
| dash_mpd_node.h | ~80 | MPD节点类（继承自IDashMpdNode） |
| dash_period_node.h | ~80 | Period节点类 |
| dash_adpt_set_node.h | ~80 | AdaptationSet节点类 |
| dash_representation_node.h | ~80 | Representation节点类 |
| dash_seg_template_node.h | ~80 | SegmentTemplate节点类 |
| dash_seg_list_node.h | ~80 | SegmentList节点类 |
| dash_seg_base_node.h | ~80 | SegmentBase节点类 |
| dash_mult_seg_base_node.h | ~80 | MultSegmentBase节点类 |
| dash_descriptor_node.h | ~80 | Descriptor节点类（ContentProtection/EssentialProperty） |
| dash_event_node.h / dash_event_stream_node.h | ~80×2 | Event事件节点 |
| dash_com_attrs_elements.h | ~80 | 通用属性节点 |
| dash_content_comp_node.h | ~80 | ContentComponent节点 |
| dash_url_type_node.h | ~80 | URLType节点（Initialization/Index） |
| dash_break_duration_node.h | ~80 | BreakDuration节点 |
| dash_seg_url_node.h | ~80 | SegmentURL节点 |
| dash_seg_tmline_node.h | ~80 | SegmentTimeline节点 |
| dash_splice_insert_node.h / dash_splice_info_section_node.h | ~80×2 | SCTE-35拼接节点 |
| mpd_parser_def.h | ~200 | MPD标签常量（MPD_LABEL_*） |

### 1.2 MPD Downloader（dash_mpd_downloader.cpp，2495行）

| 文件 | 行数 | 职责 |
|------|------|------|
| dash_mpd_downloader.cpp | 2495 | MPD文件下载+更新管理+CollectPeriodRanges |
| dash_mpd_downloader.h | ~200 | DashMpdDownloader类声明 |

### 1.3 Segment Downloader（dash_segment_downloader.cpp，1361行）

| 文件 | 行数 | 职责 |
|------|------|------|
| dash_segment_downloader.cpp | 1361 | DASH分片下载+环形缓冲+水位线管理 |
| dash_segment_downloader.h | ~150 | DashSegmentDownloader类声明 |

**源码总行数：约9200+行**

---

## 二、架构概览

```
DASH MPD Parser 五层XML解析架构
───────────────────────────────────────────────
Layer 5: DashMpdParser        [dash_mpd_parser.cpp:1577行]
  └─ ParseMPD() L1320          [主入口]
       GetMpdAttr()           [解析MPD属性]
       GetMpdElement()        [遍历子元素]
         ParsePeriod()        L39  [Period层]
           ParseAdaptationSet() L156 [AdptSet层]
             ParseRepresentation() L887 [Rep层]
               ParseSegmentTemplate() L818 [三段机制]
               ParseSegmentList()     L726
               ParseSegmentBase()    L663
               ParseContentProtection() L1023
               ParseSegmentTimeline() L1142
             ParseEventStream()  L397 [SCTE-35事件]
───────────────────────────────────────────────
Layer 4: DashMpdManager       [dash_mpd_manager.cpp:188行]
  └─ GetPeriods() / GetFirstPeriod() / GetNextPeriod()
     GetBaseUrl() / MakeBaseUrl()
───────────────────────────────────────────────
Layer 3: DashAdptSetManager  [dash_adpt_set_manager.cpp:297行]
  └─ Init() → ParseInitSegment()
     GetHighRepresentation() / GetRepresentationByBandwidth()
     SortByBitrate()        [按带宽排序选轨]
───────────────────────────────────────────────
Layer 2: DashPeriodManager    [dash_period_manager.cpp:285行]
  └─ 管理Period切换/时间范围
───────────────────────────────────────────────
Layer 1: IDashMpdNode Factory [i_dash_mpd_node.cpp:90行]
  └─ IDashMpdNode::CreateNode(LABEL) [工厂模式]
     IDashMpdNode::DestroyNode(node)
     7种GetAttr<T>模板重载
───────────────────────────────────────────────
辅助: DashMpdUtil(dash_mpd_util.cpp:283行)
  └─ DashStrToDuration() / DashAppendBaseUrl()
     DashUrlIsAbsolute() / BuildSrcUrl()
     BT2020色彩矩阵常量 [MATRIX_COEFFICIENTS_BT_2020=9]
───────────────────────────────────────────────
分片下载:
DashMpdDownloader    (2495行)  [下载MPD文件]
  └─ CollectPeriodRanges() [计算Period Seek范围]
DashSegmentDownloader (1361行) [下载Media Segments]
  └─ RingBuffer [VID=4MB/AUD=400KB/SUB=200KB]
     水位线管理 [VIDEO=128KB/AUDIO=24KB]
```

---

## 三、行号级 Evidence（20条）

**E1.** `dash_mpd_parser.cpp:L34` — `DashMpdParser::~DashMpdParser()` 析构函数入口，清理dashMpdInfo_的period列表

**E2.** `dash_mpd_parser.cpp:L39` — `void DashMpdParser::ParsePeriod()` Period层解析入口，创建DashPeriodInfo并调用IDashMpdNode::CreateNode("Period")

**E3.** `dash_mpd_parser.cpp:L61` — `GetPeriodAttr()` 解析Period的id/start/duration/bitstreamSwitching四个XML属性

**E4.** `dash_mpd_parser.cpp:L80` — `GetPeriodElement()` 遍历Period子元素，分离SegBase/SegList/SegTemplate和AdaptationSet三路

**E5.** `dash_mpd_parser.cpp:L156` — `ParseAdaptationSet()` AdptSet层解析入口，创建DashAdptSetInfo并解析mimeType/lang/contentType/videoType/codecs等属性（L178-L233）

**E6.** `dash_mpd_parser.cpp:L250` — `GetAdaptationSetElement()` 递归继承机制：若AdptSet的SegTemplate为nullptr则继承Period的SegTemplate（L286-292），通过InheritMultSegBase实现（L795）

**E7.** `dash_mpd_parser.cpp:L349` — `ParseSegmentUrl()` 解析\<SegmentURL\>的media和mediaRange属性，构建DashSegUrl

**E8.** `dash_mpd_parser.cpp:L397` — `ParseEventStream()` 解析SCTE-35事件流，支持EventStream多事件链表

**E9.** `dash_mpd_parser.cpp:L663` — `ParseSegmentBase()` 解析\<SegmentBase\>，提取timeScale/presentationTimeOffset/indexRange/Initialization（InitSegment URL）

**E10.** `dash_mpd_parser.cpp:L726` — `ParseSegmentList()` 解析\<SegmentList\>并调用ParseSegmentListElement(L766)遍历每个\<SegmentURL\>

**E11.** `dash_mpd_parser.cpp:L795` — `InheritMultSegBase()` 段继承核心函数：下层（Rep/AdptSet）SegTemplate/SegList/SegBase继承上层（Period）对应元素，实现DRY原则

**E12.** `dash_mpd_parser.cpp:L818` — `ParseSegmentTemplate()` 解析\<SegmentTemplate\>，提取$Number$,$Time$,$Bandwidth$模板变量，支持SegmentTimeline（$t$/$d$/$r$）动态段号计算

**E13.** `dash_mpd_parser.cpp:L887` — `ParseRepresentation()` Rep层解析入口，解析bandwidth/id/commonAttrs并注册到adptSetInfo->representationList_

**E14.** `dash_mpd_parser.cpp:L1023` — `ParseContentProtection()` 解析ContentProtection（DRM），提取schemeIdUrl_/defaultKid_/elementMap_，支持cenc:pssh DRM方案

**E15.** `dash_mpd_parser.cpp:L1142` — `ParseSegmentTimeline()` 解析SegmentTimeline的$t$（时间戳）/$d$（持续时间）/$r$（重复次数）三元组，填充DashSegTimeline链表

**E16.** `dash_mpd_parser.cpp:L1320` — `ParseMPD()` 主入口：xmlParser->ParseFromBuffer()→IDashMpdNode::CreateNode("MPD")→GetMpdAttr()→GetMpdElement()，StopParseMpd()通过stopFlag_支持中止解析

**E17.** `dash_mpd_def.h:L29-32` — `enum DashVideoType { DASH_VIDEO_TYPE_SDR, DASH_VIDEO_TYPE_HDR_VIVID, DASH_VIDEO_TYPE_HDR_10 }` HDR类型枚举，在AdaptationSet的videoType_字段中使用

**E18.** `dash_mpd_def.h:L60-78` — `struct DashSegBaseInfo / DashMultSegBaseInfo / DashSegTmpltInfo` 三段机制数据结构：SegBase（单段索引）+SegList（显式段列表）+SegTemplate（模板生成），initialization_指向InitSegment

**E19.** `dash_adpt_set_manager.cpp:L24-27` — `SortByBitrate()` 静态比较函数：按bandwidth升序排列Representation列表，用于GetHighRepresentation()找最高码率轨

**E20.** `dash_segment_downloader.cpp:L27-37` — `BUFFER_SIZE_MAP`: VID_RING_BUFFER_SIZE=4MB / AUD_RING_BUFFER_SIZE=400KB / SUBTITLE_RING_BUFFER_SIZE=200KB；PLAY_WATER_LINE=5KB / DEFAULT_VIDEO_WATER_LINE=128KB / DEFAULT_AUDIO_WATER_LINE=24KB；支持自适应码率切换时的环形缓冲重填充

---

## 四、关键函数/类/数据结构分析

### 4.1 DashMpdParser（XML五层解析引擎）

**核心职责**：将XML MPD文档解析为DashMpdInfo内存结构

**五层解析顺序**：
1. **MPD层** — mediaPresentationDuration / minBufferTime / profiles / type（static/dynamic）
2. **Period层** — start / duration / id / bitstreamSwitching；子元素含AdaptationSet/SegmentBase/SegmentList/SegmentTemplate
3. **AdaptationSet层** — mimeType / codecs / lang / contentType；segmentAlignment / subSegmentAlignment / bitstreamSwitching；支持ContentProtection（DRM）
4. **Representation层** — bandwidth / id / width / height / frameRate；含三段机制之一（SegBase/SegList/SegTemplate）
5. **Segment层** — media / mediaRange / indexRange；InitSegment URL

**三段机制（Segment Inheritance）**：
```
Period (顶层) ──┬─ periodSegBase_ / periodSegList_ / periodSegTmplt_
                │
                ▼ (InheritMultSegBase / InheritSegBase 继承)
AdaptationSet ──┼─ adptSetSegBase_ / adptSetSegList_ / adptSetSegTmplt_
                │
                ▼ (Rep层使用AdptSet继承后的配置)
Representation ──┴─ representationSegBase_ / representationSegList_ / representationSegTmplt_
```

**SegmentTemplate模板变量**：
- `$Number$` → 段序号（startNumber_+segmentIndex）
- `$Time$` → 段时间戳（startTime_+index*duration）
- `$Bandwidth$` → 当前Representation的bandwidth
- `$t$/$d$/$r$`（SegmentTimeline模式）→ 显式时间轴三元组

### 4.2 IDashMpdNode 工厂模式

```cpp
// i_dash_mpd_node.h
class IDashMpdNode {
    static IDashMpdNode *CreateNode(const std::string &nodeName); // "MPD"/"Period"/...
    static void DestroyNode(IDashMpdNode *node);
    virtual void ParseNode(...) = 0;
    virtual void GetAttr<T>(const string &name, T &val) = 0; // 7个模板重载
};
```

节点类列表：DashMpdNode / DashPeriodNode / DashAdptSetNode / DashRepresentationNode / DashSegTemplateNode / DashSegListNode / DashSegBaseNode / DashMultSegBaseNode / DashDescriptorNode(ContentProtection/EssentialProperty) / DashEventNode / DashEventStreamNode

### 4.3 DashMpdManager（数据管理）

**核心职责**：管理解析后的DashMpdInfo，暴露Period遍历/BaseURL构建/时间范围查询接口

**关键方法**：
- `GetPeriods()` — 返回periodInfoList_链表
- `GetNextPeriod(period)` — Period切换，遍历链表找下一个
- `GetBaseUrl()` — 从MPD URL提取目录路径；若MPD无BaseURL则自动从MPD URL推导
- `MakeBaseUrl()` — 合并MPD BaseURL与Representation BaseURL，支持绝对URL和相对路径

### 4.4 DashAdptSetManager（轨选管理）

**核心职责**：管理AdaptationSet内多个Representation的初始化解析和带宽选择

**Init() → SortByBitrate()** — 按bandwidth升序排列，GetHighRepresentation()返回最高带宽轨

**ParseInitSegment()三路径**：
1. AdptSetSegBase → initialization_
2. AdptSetSegList → multSegBaseInfo_.segBaseInfo_.initialization_
3. AdptSetSegTemplate → ParseInitSegmentBySegTmplt()

### 4.5 DashVideoType HDR体系

```cpp
enum DashVideoType { DASH_VIDEO_TYPE_SDR, DASH_VIDEO_TYPE_HDR_VIVID, DASH_VIDEO_TYPE_HDR_10 };
```

与dash_mpd_util.cpp中的BT2020色彩矩阵（MATRIX_COEFFICIENTS_BT_2020=9 / COLOUR_PRIMARIES_BT_2020=9 / TRANSFER_CHARACTERISTICS_BT_2020=14）配合，支持HDR10和HDR VIVID元数据

### 4.6 DashSegmentDownloader 环形缓冲架构

**RingBuffer尺寸映射**（MEDIA_TYPE→SIZE）：
- VIDEO: 4MB（VID_RING_BUFFER_SIZE）
- AUDIO: 400KB（AUD_RING_BUFFER_SIZE）
- SUBTITLE: 200KB（SUBTITLE_RING_BUFFER_SIZE）

**水位线体系**：
- PLAY_WATER_LINE = 5KB（通用播放水位线）
- DEFAULT_VIDEO_WATER_LINE = 128KB（视频下载水位线，触发解码）
- DEFAULT_AUDIO_WATER_LINE = 24KB（音频下载水位线）
- DEFAULT_MIN_CACHE_TIME = 0.3s / DEFAULT_MAX_CACHE_TIME = 10.0s

**SCTE-35拼接支持**：ParseSpliceInfoSection(L523) → ParseSpliceInsert(L579) → ParseBreakDuration(L640)，支持广告插入触发点

---

## 五、与其他主题的关联

| 关联S# | 关系 |
|--------|------|
| S172 | HttpSourcePlugin的DownloadMonitor→DashMediaDownloader→DashMpdDownloader依赖链 |
| S182 | HLS Playlist Downloader是同级的另一流媒体协议，DASH/HLS自适应码率切换在S106中对比 |
| S138 | S187为S138的DASH MPD Parser草案（S138未起草，本S187即填补该空白） |
| S75/S97/S101 | MediaDemuxer通用的Seek/Timeline/PTS机制与DASH segment download协同 |
| S68/S76 | 底层容器解析（MP4/TS）与DASH segment format解析 |
| S106 | DASH+HLS双协议自适应码率架构（双MpdParser对比） |

---

## 六、关键技术点

1. **XML五层递归解析**：MPD→Period→AdaptationSet→Representation→Segment，stopFlag_支持中途中止
2. **三段继承机制（InheritMultSegBase/InheritSegBase）**：避免重复配置，lower层自动继承upper层SegTemplate/SegList/SegBase
3. **SegmentTemplate $变量替换**：支持$Number$/$Time$/$Bandwidth$动态计算media URL，支持SegmentTimeline显式时间轴
4. **带宽选轨**：SortByBitrate升序排列，GetHighRepresentation()选择最高码率轨
5. **HDR VIVID支持**：DashVideoType枚举 + BT.2020色彩矩阵常量（dash_mpd_util.cpp L24-27）
6. **ContentProtection/DRM**：cenc:pssh方案，schemeIdUrl+defaultKid双字段
7. **环形缓冲水位线**：视频128KB/音频24KB，支持自适应码率切换时的缓冲重填充
8. **SCTE-35事件**：ParseSpliceInsert/ParseBreakDuration支持广告插入点触发
9. **sidx box解析**：dash_mpd_parser/sidx_box_parser.cpp（233行）解析MP4 sidx box获取Segment索引
10. **MPD动态更新**：DashMpdDownloader支持type_=DASH_TYPE_DYNAMIC的定期更新
