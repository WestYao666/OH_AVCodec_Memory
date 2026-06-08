# MEM-ARCH-AVCODEC-S234

## HLS M3U8 Tag Parsing Framework

**状态**: draft
**主题**: HLS M3U8 Tag Parsing Framework —— hls_tags.cpp (648行) + m3u8.cpp (1435行) 双文件架构  
**Scope**: AVCodec, MediaEngine, SourcePlugin, HLS, M3U8, TagParser, Playlist, DRM, AES-128
**关联场景**: 新需求开发 / 流媒体播放 / HLS自适应码率 / 内容解密 / 问题定位  
**关联**: S37(HttpSourcePlugin) / S86(MediaCachedBuffer) / S187(HLS流下载架构) / S138/S153(DASH MPD Parser)

---

## 1. 架构总览

HLS M3U8 Tag Parsing Framework 是 AVCodec 流媒体 Source 模块的核心解析组件，由两个紧耦合文件组成：

| 文件 | 行数 | 职责 |
|------|------|------|
| `hls_tags.cpp` | 648行 | HLS Tag 词法解析器（Tag工厂 + Attribute解析 + EXT-X-DEFINE变量替换） |
| `m3u8.cpp` | 1435行 | M3U8 Playlist 语义解析器（tagUpdatersMap_驱动更新 + DRM密钥管理 + 分片下载） |

```
M3U8Playlist (raw text)
    │
    ▼ ParseEntries() [hls_tags.cpp L437-473]
    │
    ▼ TagFactory::CreateTagByName() [hls_tags.cpp L288-318]
    │
    ▼ Tag 对象列表 + tagDefineMap
    │
    ▼ M3U8::UpdateFromTags() [m3u8.cpp L524+]
    │
    ▼ tagUpdatersMap_ 驱动更新 [m3u8.cpp L201-250]
    │
    ▼ M3U8Fragment 列表
```

---

## 2. hls_tags.cpp：Tag 解析引擎

### 2.1 HlsTag 枚举（22个标签类型）

**E1**: `hls_tags.h L52-68` — HlsTag 四段式枚举（REGULAR / SINGLE_VALUE / ATTRIBUTES / VALUES_LIST）

```cpp
enum struct HlsTag : uint32_t {
    SECTION_REGULAR_START = static_cast<uint8_t>(HlsTagSection::REGULAR) << 16U,
    EXTXDISCONTINUITY = SECTION_REGULAR_START,   // REGULAR: 无值标签
    EXTXENDLIST,
    EXTXIFRAMESONLY,

    URI = SECTION_SINGLE_VALUE_START,              // SINGLE_VALUE: 单值标签
    EXTXVERSION,
    EXTXBYTERANGE,
    EXTXMEDIASEQUENCE,
    // ...

    EXTXKEY = SECTION_ATTRIBUTES_START,            // ATTRIBUTES: 属性标签
    EXTXMAP,
    EXTXMEDIA,
    EXTXSTREAMINF,
    // ...

    EXTINF = SECTION_VALUES_LIST_START,           // VALUES_LIST: 列表标签
};
```

### 2.2 Tag 类层次结构

**E2**: `hls_tags.h L71-108` — Tag 基类 + 三层派生类

```cpp
class Tag { HlsTag type_; }; // 基类

class SingleValueTag : public Tag {               // 单值标签
    Attribute attr_; // value only
};

class AttributesTag : public Tag {               // 属性标签
    std::list<std::shared_ptr<Attribute>> attributes;
    void ParseAttributes(field);                 // NAME=VALUE,NAME=VALUE...
};

class ValuesListTag : public AttributesTag {     // 列表标签 (EXTINF: duration,title)
    void ParseAttributes(field) override;      // 特殊解析: DURATION,TITLE
};
```

### 2.3 Attribute 类（8种值解析方法）

**E3**: `hls_tags.cpp L33-122` — Attribute 8种值解析方法

```cpp
class Attribute {
    std::string name_; value_;
    uint64_t Decimal() const;                   // 十进制整数
    double FloatingPoint() const;                // 浮点数
    std::vector<uint8_t> HexSequence() const;   // 0xNN十六进制序列
    std::string QuotedString() const;            // 带引号字符串（含\转义）
    std::pair<size_t, size_t> GetByteRange() const;  // n@offset字节范围
    std::pair<int, int> GetResolution() const;   // WIDTHxHEIGHT 分辨率
    bool SafeStringToInt(str, result, base);    // 安全字符串转整数
    Attribute UnescapeQuotes() const;            // 去除引号
};
```

### 2.4 g_exttagmapping 标签注册表

**E4**: `hls_tags.cpp L27-50` — 22个 HLS 标签注册表

```cpp
struct { const char* name; HlsTag type; } const g_exttagmapping[] = {
    {"ext-x-byterange",              HlsTag::EXTXBYTERANGE},
    {"ext-x-discontinuity",          HlsTag::EXTXDISCONTINUITY},
    {"ext-x-key",                   HlsTag::EXTXKEY},
    {"ext-x-map",                   HlsTag::EXTXMAP},
    {"ext-x-endlist",               HlsTag::EXTXENDLIST},
    {"ext-x-media",                 HlsTag::EXTXMEDIA},
    {"ext-x-stream-inf",            HlsTag::EXTXSTREAMINF},
    {"extinf",                      HlsTag::EXTINF},
    {"", HlsTag::URI},  // URI无前缀
    // ...
};
```

### 2.5 ParseEntries 入口函数

**E5**: `hls_tags.cpp L437-473` — ParseEntries 三段式解析（DEFINE解析 → 变量替换 → Tag/URI解析）

```cpp
std::pair<std::list<std::shared_ptr<Tag>>,
          std::unordered_map<std::string, std::string>>
ParseEntries(const std::string& s,
            const std::unordered_map<std::string, std::string>& tagMasterMap,
            const std::unordered_map<std::string, std::string>& tagUriMap)
{
    // 1. ParseTag: #EXT-X-* 行 → Tag对象
    // 2. ParseURI: 非#行 → URI Tag (或合并到STREAMINF)
    // 3. ParseDefine: #EXT-X-DEFINE →变量替换 {NAME=VALUE}
    // 4. ReplacePlaceholders: {$VAR} → 实际值
}
```

### 2.6 ParseAttributeValue 属性值解析

**E6**: `hls_tags.cpp L223-246` — ParseAttributeValue 带引号状态机解析

```cpp
// bQuoted标志处理引号内逗号分隔
// NAME=VALUE,NAME="quoted,value,with,commas"
// 支持转义符: \"
while (!iss.eof()) {
    char c = iss.peek();
    if (c == '\\' && bQuoted) { iss.get(); } // 转义符
    else if (c == ',' && !bQuoted) { break; }  // 属性分隔符
    else if (c == '"') { bQuoted = !bQuoted; } // 引号切换
}
```

### 2.7 UriDecode URL解码

**E7**: `hls_tags.cpp L342-366` — UriDecode 三段式解码（%XX hex / +空格 / 原始字符）

```cpp
// %20 → 空格, %3A → :, + → 空格
while (i < uri.size()) {
    if (uri[i] == '%' && i + 2 <= uri.size()) {
        UriInsert(result, hex, 16); i += 3;
    } else if (uri[i] == '+') { result += ' '; i++; }
    else { result += uri[i]; i++; }
}
```

---

## 3. m3u8.cpp：Playlist 语义解析

### 3.1 M3U8 类核心成员

**E8**: `m3u8.h L64-90` — M3U8 核心成员（tagUpdatersMap_ 是解析驱动核心）

```cpp
struct M3U8 : public std::enable_shared_from_this<M3U8> {
    std::unordered_map<HlsTag,
        std::function<void(std::shared_ptr<Tag>&, M3U8Info&)>> tagUpdatersMap_;
    std::list<std::shared_ptr<M3U8Fragment>> files_; // 分片列表
    double targetDuration_ {0.0};
    bool bLive_ {};
    uint64_t sequence_ {1};
    uint8_t key_[16] {0}; iv_[16] {0}; // AES-128密钥
    std::shared_ptr<Downloader> downloader_; // 分片下载器
    std::multimap<std::string, std::vector<uint8_t>> localDrmInfos_;
    std::atomic<bool> isDecryptAble_ {false};
    std::atomic<bool> isDecryptKeyReady_ {false};
    // ...
};
```

### 3.2 M3U8Fragment 分片数据结构

**E9**: `m3u8.h L43-59` — M3U8Fragment 分片元数据（URI + duration + sequence + AES key）

```cpp
struct M3U8Fragment {
    std::string uri_; // 分片URI
    double duration_;                  // 时长（秒）
    int64_t sequence_;                // 序号
    bool discont_ {false};             // 不连续标志
    uint8_t iv_[16] {0};              // AES IV
    uint8_t key_[16] {0}; // AES KEY
    uint32_t offset_ {0};             // 字节范围偏移
    uint32_t length_ {0};             // 字节范围长度
    uint64_t keyIndex_ {0}; // 密钥索引
};
```

### 3.3 tagUpdatersMap_ 驱动更新机制

**E10**: `m3u8.cpp L201-250` — tagUpdatersMap_ 7个 tag处理器（EXTXPLAYLISTTYPE → EXTXMEDIASEQUENCE）

```cpp
void M3U8::InitTagUpdaters()
{
    tagUpdatersMap_[HlsTag::EXTXPLAYLISTTYPE] = [this](auto& tag, auto& info) {
        bLive_ = GetValue().QuotedString() != "VOD";  // VOD vs Live
    };
    tagUpdatersMap_[HlsTag::EXTXTARGETDURATION] = [this](auto& tag, auto& info) {
        targetDuration_ = GetValue().FloatingPoint();  // 最大分片时长
    };
    tagUpdatersMap_[HlsTag::EXTXMEDIASEQUENCE] = [this](auto& tag, auto& info) {
        sequence_ = GetValue().Decimal();              // 起始序号
    };
    tagUpdatersMap_[HlsTag::EXTINF] = [this](const auto& tag, M3U8Info& info) {
        GetExtInf(tag, info.duration);                 // 分片时长
    };
    tagUpdatersMap_[HlsTag::URI] = [this](auto& tag, M3U8Info& info) {
        info.uri = UriJoin(uri_, GetValue().QuotedString()); // 相对→绝对URI
    };
    tagUpdatersMap_[HlsTag::EXTXBYTERANGE] = [this](auto& tag, auto& info) {
        auto attr = make_shared<Attribute>("BYTERANGE", value);
        offset_ = attr->GetByteRange().first + 1;
        length_ = attr->GetByteRange().second;
    };
}
```

### 3.4 M3U8::Update 解析入口

**E11**: `m3u8.cpp L129-167` — M3U8::Update 验证 + ParseEntries + UpdateFromTags 三步曲

```cpp
bool M3U8::Update(const std::string& playList, bool isNeedCleanFiles, uint64_t totalKeyIndex)
{
    if (!StrHasPrefix(playList, "#EXTM3U")) return false;  // 必须以#EXTM3U开头
    if (playList.find("\n#EXT-X-STREAM-INF:") != npos)
        return false;  // Master playlist 拒绝（由M3U8MasterPlaylist处理）
    ret = ParseEntries(playList);  // hls_tags.cpp:ParseEntries
    UpdateFromTags(tags); // 驱动tagUpdatersMap_
    return true;
}
```

### 3.5 UpdateFromTags 分片累积逻辑

**E12**: `m3u8.cpp L524-600` — UpdateFromTags 遍历Tags累积分片（duration累加 + discontinuity检测）

```cpp
void M3U8::UpdateFromTags(std::list<std::shared_ptr<Tag>>& tags)
{
    M3U8Info info;
    for (auto& tag : tags) {
        HlsTag hlsTag = tag->GetType();
        if (hlsTag == HlsTag::EXTXENDLIST) { info.bVod = true; bLive_ = false; }
        if (hlsTag == HlsTag::EXTXDISCONTINUITY) {
            segmentTimeOffset = duration; hasDiscontinuity_ = true;
        }
        if (hlsTag == HlsTag::EXTINF) { GetExtInf(tag, info.duration); }
        if (hlsTag == HlsTag::URI) {
            info.uri = UriJoin(uri_, ...);
            auto frag = make_shared<M3U8Fragment>(info.uri, info.duration,
                                                  info.sequence_++, info.discontinuity);
            AddFile(frag, duration);  // 累积到files_
        }
    }
}
```

### 3.6 UriJoin 相对路径→绝对路径

**E13**: `m3u8.cpp L72-93` — UriJoin 五路分支（绝对URL / //协议相对 / /根路径相对 / 查询参数拼接 / 同目录相对）

```cpp
std::string UriJoin(std::string& baseUrl, const std::string& uri)
{
    if (uri.find("http") == 0) return uri;     // 已是绝对路径
    if (uri.find("//") == 0)                   // "//cdn.example.com/..."
        return baseUrl.substr(0, baseUrl.find('/')) + uri;
    if (uri.find('/') == 0)                     // "/path/to/frag.m3u8"
        return baseUrl.substr(0, pos) + uri;
    auto pos = uriMain.rfind('/');              // "frag.m3u8" → 同目录拼接
    return uriMain.substr(0, pos + 1) + uri;
}
```

### 3.7 DRM PrepareDecryptionKeys + AES-128

**E14**: `m3u8.cpp L273-295` — PrepareDecryptionKeys 三分支（PSSH / AES-URI / SESSION-KEY）

```cpp
void M3U8::PrepareDecrptionKeys(std::shared_ptr<Tag>& tag)
{
    isDecryptAble_ = true;
    ParseKey(AttributesTag); // 解析METHOD/URI/IV/KEYFORMAT
    auto keyUri = GetAttributeByName("URI");
    if (keyUri->substr(0, DRM_PSSH_TITLE_LEN) == "data:text/plain;") {
        ProcessDrmInfos();               // 嵌入式PSSH（data: URI）
    } else {
        KeyInfo keyInfo; // AES-128 URI下载
        keyInfos_[keyInfo.index_] = keyInfo;
        DownloadKey(true); // 异步下载AES密钥
    }
}
```

### 3.8 EXTXMAP fmp4头部下载

**E15**: `m3u8.cpp L420-455` — ParseMap + DownloadMap + SaveMapData fmp4初始化向量（IV）下载链

```cpp
void M3U8::ParseMap(const std::shared_ptr<AttributesTag>& tag)
{
    uri = UriJoin(uri_, uriAttribute->QuotedString());
    auto byteRange = tag->GetAttributeByName("BYTERANGE"); // 可选字节范围
    DownloadMap(uri, offset, length); // 下载init.mp4
    sleepCond_.WaitFor(lock, WAIT_KEY_SLEEP_TIME * MAX_DOWNLOAD_TIME,
        [this]() { return isInterruptNeeded_ || isHeaderReady_; });
}
```

---

## 4. M3U8MasterPlaylist：Master Playlist 解析

### 4.1 M3U8VariantStream 变种流

**E16**: `m3u8.h L153-169` — M3U8VariantStream 变种流（bandwidth + resolution + codecs + audio/subtitle媒体）

```cpp
struct M3U8VariantStream {
    uint64_t bandWidth_ {};              // 码率（bps）
    uint32_t frameRate_ {0};
    int width_ {}, height_ {};
    std::string codecs_; // mp4a.40.2 / avc1.64001f
    std::string audio_;                  // AUDIO组
    std::string subtitles_;              // SUBTITLES组
    std::shared_ptr<M3U8> m3u8_; // 子Playlist
    std::list<std::shared_ptr<M3U8Media>> audioMedia_; // 多轨Audio
    std::list<std::shared_ptr<M3U8Media>> subtitlesMedia_;
};
```

### 4.2 选择策略（按分辨率 / 按StreamId）

**E17**: `m3u8.cpp L700-750` — ChooseStreamByResolution / ChooseStreamByStream 变种流选择

```cpp
void M3U8MasterPlaylist::ChooseStreamByResolution()
{
    // 选择最接近initResolution_的VariantStream
    // IsNearToInitResolution:宽高差在阈值内
}
void M3U8MasterPlaylist::ChooseStreamByStream(int32_t streamId)
{
    // 按streamId精确选择
}
```

---

## 5. 关键数据流图

```
#EXTM3U
#EXT-X-TARGETDURATION:10
#EXT-X-MEDIA-SEQUENCE:1
#EXT-X-KEY:METHOD=AES-128,URI="key.bin",IV=0x...
#EXTINF:9.9
segment1.ts
#EXTINF:10.0
segment2.ts
#EXT-X-ENDLIST

         │
         ▼ ParseEntries() [E5]
   ┌─────────────────────────────────┐
    │ #EXT-X-KEY  → AttributesTag     │
    │ #EXTINF → ValuesListTag     │
    │ segment1.ts → URI Tag │
    └─────────────────────────────────┘
         │
         ▼ M3U8::UpdateFromTags() [E12]
    ┌─────────────────────────────────┐
    │ tagUpdatersMap_ 驱动更新         │
    │ EXTXKEY → PrepareDecryptionKeys │  [E14]
    │ EXTINF   → info.duration         │  [E10]
    │ URI      → AddFile(fragment)     │  [E12]
    └─────────────────────────────────┘
         │
         ▼ M3U8Fragment列表 + AES密钥
   ┌─────────────────────────────────┐
    │ files_ → M3U8Fragment列表 │
    │ key_/iv_ → AES-128参数 │
    │ bLive_ / bVod_ → 直播/VOD判断 │
    └─────────────────────────────────┘
```

---

## 6. 与相关记忆条目关联

| 关联 | 说明 |
|------|------|
| S37(HttpSourcePlugin) | 上游SourcePlugin，HLS入口路由 |
| S86(MediaCachedBuffer) | RingBuffer缓冲，HlsSegmentManager分片缓存 |
| S187(HLS流下载架构) | HlsMediaDownloader + HlsSegmentManager 下载链路 |
| S138/S153(DASH MPD Parser) | DASH并列模块，DASH MPD解析 vs HLS M3U8解析 |
| S210(DownloadMonitor) | HTTP下载监控装饰器 |
| S195(HttpSourcePlugin Downloader) | Downloader组件 |

---

## 7. Evidence 汇总

| # | 文件 | 行号 | 内容 |
|---|------|------|------|
| E1 | hls_tags.h | 52-68 | HlsTag四段式枚举 |
| E2 | hls_tags.h | 71-108 | Tag类层次结构 |
| E3 | hls_tags.cpp | 33-122 | Attribute 8种值解析方法 |
| E4 | hls_tags.cpp | 27-50 | g_exttagmapping 22标签注册表 |
| E5 | hls_tags.cpp | 437-473 | ParseEntries 入口函数 |
| E6 | hls_tags.cpp | 223-246 | ParseAttributeValue 引号状态机 |
| E7 | hls_tags.cpp | 342-366 | UriDecode URL解码 |
| E8 | m3u8.h | 64-90 | M3U8核心成员 |
| E9 | m3u8.h | 43-59 | M3U8Fragment分片结构 |
| E10 | m3u8.cpp | 201-250 | tagUpdatersMap_ 7个处理器 |
| E11 | m3u8.cpp | 129-167 | M3U8::Update 解析入口 |
| E12 | m3u8.cpp | 524-600 | UpdateFromTags 分片累积 |
| E13 | m3u8.cpp | 72-93 | UriJoin 五路相对路径 |
| E14 | m3u8.cpp | 273-295 | PrepareDecryptionKeys DRM |
| E15 | m3u8.cpp | 420-455 | ParseMap + DownloadMap fmp4 |
| E16 | m3u8.h | 153-169 | M3U8VariantStream变种流 |
| E17 | m3u8.cpp | 700-750 | ChooseStreamByResolution/StreamId |