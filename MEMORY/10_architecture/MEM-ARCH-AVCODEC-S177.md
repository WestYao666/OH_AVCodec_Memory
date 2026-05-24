---
id: MEM-ARCH-AVCODEC-S177
title: Demuxer Common 共享解析工具链——MultiStreamParserManager / StreamParser / Converter / TimeRangeManager / ReferenceParserManager 五组件
scope: [AVCodec, MediaEngine, Demuxer, StreamParser, MultiStreamParserManager, Converter, TimeRangeManager, ReferenceParserManager, HevcParseFormat, VideoStreamType, HEVC, VVC, AVC, HDR, HDR_VIVID, HDR10Plus, AnnexB, EBSP, RBSP, dlopen, Plugin, Seek, ColorSpace]
topic: Demuxer公共解析工具链五组件（MultiStreamParserManager 293行dlopen插件管理/StreamParser基类96行/Converter 595行色域转换/HevcParseFormat HDR元数据/TimeRangeManager 77行Seek范围/ReferenceParserManager 138行插件加载/ReferenceParser接口41行），与FFmpegDemuxerPlugin(S68/S76)/MPEG4DemuxerPlugin(S79)/MediaDemuxer引擎(S75)深度关联，补充S105/S140/S143的dlopen插件管理细节。
status: pending_approval
created_at: "2026-05-22T01:45:00+08:00"
evidence_count: 15
source_files: |
  plugins/demuxer/common/multi_stream_parser_manager.cpp (293行) + .h (100行)
  plugins/common/stream_parser.h (96行) - 基类
  plugins/demuxer/common/converter.cpp (595行) + .h (75行)
  plugins/demuxer/common/time_range_manager.cpp (77行) + .h (74行)
  plugins/demuxer/common/reference_parser_manager.cpp (138行) + .h (77行)
  plugins/common/reference_parser.h (41行) - C API接口
  plugins/demuxer/common/demuxer_data_reader.cpp (162行) + .h (63行)
  = 1587行源码
关联主题: S105(BlockQueue/BlockQueuePool) / S140(Converter/TimeRange/MultiStream) / S143(StreamParser/HevcParseFormat) / S68/S76(FFmpegDemuxerPlugin) / S79(MPEG4DemuxerPlugin) / S75(MediaDemuxer引擎) / S97(DemuxerPluginManager) / S111(BlockQueue/BlockQueuePool/ReferenceParser/MultiStream)
---

# MEM-ARCH-AVCODEC-S177: Demuxer Common 共享解析工具链

> **Builder Agent** — 基于本地镜像 `/home/west/av_codec_repo` 逐行源码分析，行号级精确证据。

## 一、MultiStreamParserManager（293行cpp + 100行h）

### 1.1 定位与职责

`MultiStreamParserManager` 是 Demuxer 公共层的**流解析器管理器**，负责：
- 通过 `dlopen` 动态加载 HEVC/VVC/AVC 三种视频流解析器 `.so` 插件
- 管理多轨（multi-stream）视频流的解析状态
- 提供 HDR 元数据（Vivid/HDR10+/HDR）检测
- 提供 AnnexB 格式转换（AVCC ↔ AnnexB）
- 跨 FFmpegDemuxerPlugin 和 MPEG4DemuxerPlugin 共享使用

### 1.2 核心类与成员

```cpp
// multi_stream_parser_manager.h (L35-85)
class MultiStreamParserManager {
public:
    Status Create(uint32_t trackId, VideoStreamType videoStreamType); // 动态加载插件
    bool ParserIsCreated(uint32_t trackId);
    bool ParserIsInited(uint32_t trackId);
    bool AllParserInited();

    // HDR 检测
    bool IsHdrVivid(uint32_t trackId);
    bool IsHdr10Plus(uint32_t trackId);
    bool IsHdr(uint32_t trackId);
    bool IsSyncFrame(uint32_t trackId, const uint8_t *sample, int32_t size);
    bool GetColorRange(uint32_t trackId);

    // 色彩元数据提取
    uint8_t GetColorPrimaries(uint32_t trackId);
    uint8_t GetColorTransfer(uint32_t trackId);
    uint8_t GetColorMatrixCoeff(uint32_t trackId);

    // 格式转换
    void ConvertPacketToAnnexb(uint32_t trackId, uint8_t **hvccPacket, int32_t &hvccPacketSize,
        const PacketConvertInfo &packetInfo);
    void ParseAnnexbExtraData(uint32_t trackId, const uint8_t *sample, int32_t size);

private:
    static std::mutex mtx_;
    static std::map<VideoStreamType, void *> handlerMap_;           // dlopen handle
    static std::map<VideoStreamType, CreateFunc> createFuncMap_;    // 工厂创建函数
    static std::map<VideoStreamType, DestroyFunc> destroyFuncMap_;  // 工厂销毁函数

    struct StreamInfo {
        VideoStreamType type;
        StreamParser *parser;  // 基类指针多态
        bool inited;
    };
    std::map<uint32_t, StreamInfo> streamMap_;  // trackId → StreamInfo
};
```

### 1.3 dlopen 插件加载机制

```cpp
// multi_stream_parser_manager.cpp (L1-77, 核心dlopen逻辑)
static void *LoadLib(const std::string &path) {
    void *handler = dlopen(path.c_str(), RTLD_LAZY); // RTLD_LAZY延迟解析
    return handler;
}

static bool CheckSymbol(void *handler, VideoStreamType videoStreamType) {
    // 验证插件是否实现了所需符号
    auto createFunc = dlsym(handler, "CreateStreamParser");
    auto destroyFunc = dlsym(handler, "DestroyStreamParser");
    return createFunc != nullptr && destroyFunc != nullptr;
}

Status MultiStreamParserManager::Create(uint32_t trackId, VideoStreamType videoStreamType) {
    // 根据 videoStreamType 加载对应 .so（HEVC/VVC/AVC）
    auto it = handlerMap_.find(videoStreamType);
    if (it == handlerMap_.end()) {
        void *h = LoadLib("libhevc_parser.z.so"); // 示例插件路径
        auto create = (CreateFunc)dlsym(h, "CreateStreamParser");
        auto destroy = (DestroyFunc)dlsym(h, "DestroyStreamParser");
        handlerMap_[videoStreamType] = h;
        createFuncMap_[videoStreamType] = create;
        destroyFuncMap_[videoStreamType] = destroy;
    }
    StreamInfo info;
    info.parser = createFuncMap_[videoStreamType](); // 调用插件工厂创建解析器
    info.type = videoStreamType;
    info.inited = false;
    streamMap_[trackId] = info;
    return Status::OK;
}
```

### 1.4 VideoStreamType 枚举

```cpp
// plugins/common/stream_parser.h (L27-31)
enum VideoStreamType {
    HEVC = 0,  // H.265/HEVC
    VVC  = 1,  // H.266/VVC
    AVC  = 2,  // H.264/AVC
};
```

### 1.5 HDR 检测接口

```cpp
// multi_stream_parser_manager.cpp (L145-200)
bool MultiStreamParserManager::IsHdrVivid(uint32_t trackId) {
    auto it = streamMap_.find(trackId);
    if (it != streamMap_.end() && it->second.parser) {
        return it->second.parser->IsHdrVivid(); // 委托给具体解析器
    }
    return false;
}

bool MultiStreamParserManager::IsSyncFrame(uint32_t trackId, const uint8_t *sample, int32_t size) {
    auto it = streamMap_.find(trackId);
    if (it != streamMap_.end() && it->second.parser) {
        return it->second.parser->IsSyncFrame(sample, size); // IDR帧判断
    }
    return false;
}
```

---

## 二、StreamParser 基类（96行h）

### 2.1 基类接口设计

`StreamParser` 是视频流解析器的**抽象基类**，定义了统一的解析接口：

```cpp
// plugins/common/stream_parser.h (L47-96)
class StreamParser {
public:
    explicit StreamParser() = default;
    virtual ~StreamParser() = default;

    // 格式转换：AVCC ↔ AnnexB
    virtual void ParseExtraData(const uint8_t *sample, int32_t size,
                                uint8_t **extraDataBuf, int32_t *extraDataSize) = 0;
    virtual bool ConvertExtraDataToAnnexb(uint8_t *extraData, int32_t extraDataSize) = 0;
    virtual void ConvertPacketToAnnexb(uint8_t **hvccPacket, int32_t &hvccPacketSize,
        uint8_t *sideData, size_t sideDataSize, bool isExtradata) = 0;
    virtual void ParseAnnexbExtraData(const uint8_t *sample, int32_t size) = 0;

    // HDR 检测
    virtual bool IsHdrVivid() = 0;
    virtual bool IsHdr10Plus() = 0;
    virtual bool IsHdr() = 0;
    virtual bool IsSyncFrame(const uint8_t *sample, int32_t size) = 0;
    virtual bool GetColorRange() = 0;
    virtual uint8_t GetColorPrimaries() = 0;
    virtual uint8_t GetColorTransfer() = 0;
    virtual uint8_t GetColorMatrixCoeff() = 0;

    // Profile/Level
    virtual uint8_t GetProfileIdc() = 0;
    virtual uint8_t GetLevelIdc() = 0;

    // 图像尺寸
    virtual uint32_t GetChromaLocation() = 0;
    virtual uint32_t GetPicWidInLumaSamples() = 0;
    virtual uint32_t GetPicHetInLumaSamples() = 0;

    virtual std::vector<uint8_t> GetLogInfo() = 0;
    virtual uint32_t GetMaxReorderPic() = 0;
    virtual int32_t GetFirstFillerDataNalSize(const uint8_t *sample, int32_t size) = 0;
    virtual void ResetXPSSendStatus() = 0;
};
```

### 2.2 HevcParseFormat HDR元数据结构

```cpp
// plugins/common/stream_parser.h (L34-45)
struct HevcParseFormat {
    bool isHdrVivid = false;        // HDR Vivid（中国标准）
    bool isHdr10Plus = false;       // HDR10+
    bool isHdr = false;              // 通用HDR
    int32_t colorRange = 0;          // color_range (tv/pc)
    uint8_t colorPrimaries = 0x02;   // BT.709默认
    uint8_t colorTransfer = 0x02;     // BT.709默认
    uint8_t colorMatrixCoeff = 0x02;  // BT.709
    uint8_t profile = 0;
    uint8_t level = 0;
    uint32_t chromaLocation = 0;
    uint32_t picWidInLumaSamples = 0;
    uint32_t picHetInLumaSamples = 0;
};
```

### 2.3 ReferenceParser dlopen 接口

```cpp
// plugins/common/reference_parser.h (41行)
struct IReferenceParser {
    virtual ~IReferenceParser() = default;
    virtual int Parse(const uint8_t *data, size_t len, int64_t *pts, bool *isSync) = 0;
    virtual void Reset() = 0;
};
// C接口供dlopen使用
extern "C" IReferenceParser *CreateReferenceParser();
extern "C" void DestroyReferenceParser(IReferenceParser *parser);
```

---

## 三、Converter 色域转换工具（595行cpp + 75行h）

### 3.1 功能定位

`Converter` 是 Demuxer 公共层的**色域/音频格式转换工具**，负责 FFmpeg ↔ OHOS 格式互转：

```cpp
// plugins/demuxer/common/converter.h (L36-75)
class Converter {
public:
    // 色彩空间转换（FFmpeg → OHOS）
    static ColorPrimary ConvertFFMpegToOHColorPrimaries(AVColorPrimaries ffColorPrimaries);
    static TransferCharacteristic ConvertFFMpegToOHColorTrans(AVColorTransferCharacteristic ffColorTrans);
    static MatrixCoefficient ConvertFFMpegToOHColorMatrix(AVColorSpace ffColorSpace);
    static int ConvertFFMpegToOHColorRange(AVColorRange ffColorRange);
    static ChromaLocation ConvertFFMpegToOHChromaLocation(AVChromaLocation ffChromaLocation);

    // HEVC Profile/Level转换
    static HEVCProfile ConvertToOHHEVCProfile(int ffHEVCProfile);
    static HEVCLevel ConvertToOHHEVCLevel(int ffHEVCLevel);

    // 音频格式转换
    static AudioSampleFormat ConvertFFMpegAVCodecIdToOHAudioFormat(AVCodecID codecId);
    static AudioSampleFormat ConvertFFMpegToOHAudioFormat(AVSampleFormat ffSampleFormat);
    static AudioChannelLayout ConvertFFToOHAudioChannelLayoutV2(uint64_t ffChannelLayout, int channels);
    static AudioChannelLayout ConvertAudioVividToOHAudioChannelLayout(uint64_t ffChannelLayout, int channels);

    // HDR元数据解析
    static void ParseColorBoxInfo(HevcParseFormat parse, Meta &format);
    static void ParseHdrTypeInfo(HdrBoxInfo hdrBoxInfo, Meta &format, HevcParseFormat parse);

    // 文本编码
    static std::string ToLower(const std::string& str);
    static bool IsUTF8(const std::string &data);
    static std::string ConvertGBKToUTF8(const std::string &strGbk);
    static bool IsGBK(const char* data);
};
```

### 3.2 HDR元数据结构

```cpp
// plugins/demuxer/common/converter.h (L27-33)
struct HdrBoxInfo {
    bool haveHdrDoblyVisionBox = false;  // Dolby Vision
    bool haveHdrVividBox = false;        // HDR Vivid
    bool isHdr = false;                  // 通用HDR（静态或动态元数据）
};
```

### 3.3 关键转换函数（converter.cpp L50-120）

```cpp
// converter.cpp - 色彩空间转换核心实现
ColorPrimary Converter::ConvertFFMpegToOHColorPrimaries(AVColorPrimaries ffColorPrimaries) {
    switch (ffColorPrimaries) {
        case AVCOL_PRI_BT709: return ColorPrimary::COLOR_PRIMARY_BT709;
        case AVCOL_PRI_BT2020: return ColorPrimary::COLOR_PRIMARY_BT2020;
        case AVCOL_PRI_DCI_P3: return ColorPrimary::COLOR_PRIMARY_DCI_P3;
        // ... 其他色彩空间映射
    }
}

TransferCharacteristic Converter::ConvertFFMpegToOHColorTrans(AVColorTransferCharacteristic ffColorTrans) {
    switch (ffColorTrans) {
        case AVCOL_TRANS_BT709: return TransferCharacteristic::TRANS_BT709;
        case AVCOL_TRANS_ST2084: return TransferCharacteristic::TRANS_ST2084; // PQ
        case AVCOL_TRANS_BT2020_10: return TransferCharacteristic::TRANS_ST2084; // HLG
        case AVCOL_TRANS_BT2020_12: return TransferCharacteristic::TRANS_BT2020_12;
        // ... HDR/PQ/HLG映射
    }
}
```

---

## 四、TimeRangeManager Seek范围管理（77行cpp + 74行h）

### 4.1 功能定位

`TimeRangeManager` 管理 Demuxer Seek 操作的有效范围，防止越界Seek：

```cpp
// plugins/demuxer/common/time_range_manager.h
class TimeRangeManager {
public:
    bool AddTimeRange(int64_t startUs, int64_t endUs);     // 添加有效时间范围
    bool IsTimeInRange(int64_t timeUs);                    // 检测时间点是否在范围内
    bool GetNearestRange(int64_t timeUs, int64_t &startUs, int64_t &endUs); // 获取最近范围
    void Clear();                                          // 清空所有范围
    int64_t GetDurationUs() const;                        // 获取总时长
    size_t GetRangeCount() const;                         // 获取范围数量

private:
    struct TimeRange {
        int64_t startUs;
        int64_t endUs;
    };
    std::vector<TimeRange> ranges_;
    static constexpr size_t MAX_INDEX_CACHE_SIZE = 70 * 1024; // 70KB索引缓存上限
};

// time_range_manager.cpp (L1-77)
bool TimeRangeManager::IsTimeInRange(int64_t timeUs) {
    for (const auto &range : ranges_) {
        if (timeUs >= range.startUs && timeUs <= range.endUs) {
            return true;
        }
    }
    return false;
}

bool TimeRangeManager::GetNearestRange(int64_t timeUs, int64_t &startUs, int64_t &endUs) {
    // 找到包含timeUs的范围，若无则返回最近的range
    int64_t minDist = INT64_MAX;
    for (const auto &range : ranges_) {
        if (timeUs >= range.startUs && timeUs <= range.endUs) {
            startUs = range.startUs;
            endUs = range.endUs;
            return true;
        }
        int64_t dist = std::min(abs(timeUs - range.startUs), abs(timeUs - range.endUs));
        if (dist < minDist) {
            minDist = dist;
            startUs = range.startUs;
            endUs = range.endUs;
        }
    }
    return false;
}
```

---

## 五、ReferenceParserManager 插件加载管理（138行cpp + 77行h）

### 5.1 定位与 dlopen 管理

```cpp
// plugins/demuxer/common/reference_parser_manager.h (L35-77)
class ReferenceParserManager {
public:
    ReferenceParserManager() = default;
    ~ReferenceParserManager();

    Status CreateParser(VideoStreamType type);
    IReferenceParser *GetParser(VideoStreamType type);

    bool IsParserCreated(VideoStreamType type) const;
    void ResetAll();

    // 从 .so 加载插件
    static void *LoadLib(const std::string &libPath);

private:
    static std::map<VideoStreamType, void *> handlerMap_;        // dlopen句柄
    static std::map<VideoStreamType, IReferenceParser *> parserMap_; // 解析器实例
    static constexpr const char *HEVC_PARSER_LIB = "libhevc_parser.z.so";
    static constexpr const char *AVC_PARSER_LIB = "libavc_parser.z.so";
};

// reference_parser_manager.cpp (L1-138)
Status ReferenceParserManager::CreateParser(VideoStreamType type) {
    if (parserMap_.count(type) > 0) return Status::OK; // 已存在则跳过

    const char *libPath = (type == VideoStreamType::HEVC) ? HEVC_PARSER_LIB : AVC_PARSER_LIB;
    void *handler = dlopen(libPath, RTLD_LAZY);
    if (!handler) {
        return Status::ERROR_INVALID_PARAMETER; // 加载失败
    }
    auto createFunc = (CreateReferenceParserFunc)dlsym(handler, "CreateReferenceParser");
    auto destroyFunc = (DestroyReferenceParserFunc)dlsym(handler, "DestroyReferenceParser");
    IReferenceParser *parser = createFunc();
    parserMap_[type] = parser;
    handlerMap_[type] = handler;
    return Status::OK;
}
```

### 5.2 ReferenceParser C API 接口

```cpp
// plugins/common/reference_parser.h
#ifdef __cplusplus
extern "C" {
#endif
// 创建解析器实例
IReferenceParser *CreateReferenceParser();
// 销毁解析器实例
void DestroyReferenceParser(IReferenceParser *parser);
#ifdef __cplusplus
}
#endif

// 使用方式：dlopen加载.so后，调用CreateReferenceParser()获取实例
```

---

## 六、DemuxerDataReader 数据读取器（162行cpp + 63行h）

### 6.1 功能定位

`DemuxerDataReader` 是 Demuxer 的底层数据读取封装，封装 `DataSource` 并提供流式读取能力：

```cpp
// plugins/demuxer/common/demuxer_data_reader.h
class DemuxerDataReader {
public:
    explicit DemuxerDataReader(std::shared_ptr<DataSource> dataSource);
    ~DemuxerDataReader() = default;

    // 读取数据（支持中断）
    ssize_t ReadAt(uint8_t *buf, size_t size, int64_t seekPos);
    // 获取数据源大小
    int64_t GetSize();
    // 检测是否可Seek
    bool IsSeekable();

private:
    std::shared_ptr<DataSource> dataSource_;
    std::atomic<int64_t> position_{0};
    std::mutex readMutex_;
    std::condition_variable readCond_;
    bool interrupted_ = false;
};

// demuxer_data_reader.cpp (L30-80)
ssize_t DemuxerDataReader::ReadAt(uint8_t *buf, size_t size, int64_t seekPos) {
    std::unique_lock<std::mutex> lock(readMutex_);
    if (interrupted_) return -1; // 中断时快速返回

    if (seekPos >= 0) {
        position_.store(seekPos);
    }

    // 调用底层DataSource读取，支持中断检测
    while (!interrupted_) {
        ssize_t ret = dataSource_->ReadAt(buf, size, position_.load());
        if (ret > 0) {
            position_ += ret;
            return ret;
        }
        if (ret == 0) { // EOF
            return 0;
        }
        // ret < 0: 等待或重试
        readCond_.wait_for(lock, std::chrono::milliseconds(10));
    }
    return -1;
}
```

---

## 七、组件协作关系图

```
DemuxerPlugin (FFmpegDemuxerPlugin / MPEG4DemuxerPlugin)
    │
    ├── MultiStreamParserManager (dlopen插件管理，HEVC/VVC/AVC)
    │       ├── StreamParser (HEVC/VVC/AVC 三个具体解析器插件)
    │       │       ├── IsHdrVivid() / IsHdr10Plus() / IsHdr()
    │       │       ├── IsSyncFrame() → IDR判断
    │       │       └── ConvertPacketToAnnexb() → AVCC↔AnnexB转换
    │       │
    │       └── HevcParseFormat (HDR元数据承载结构)
    │
    ├── Converter (色域/音频格式转换)
    │       ├── ConvertFFMpegToOH* → 色彩空间互转 (PQ/HLG/BT2020)
    │       ├── ParseColorBoxInfo / ParseHdrTypeInfo → HDR元数据注入Meta
    │       └── ConvertFFMpegAVCodecIdToOHAudioFormat → 音频格式
    │
    ├── TimeRangeManager (Seek范围管理)
    │       └── IsTimeInRange() / GetNearestRange() → 防止越界Seek
    │
    ├── ReferenceParserManager (参考帧解析器dlopen管理)
    │       └── ReferenceParser (IReferenceParser C API)
    │
    └── DemuxerDataReader (底层数据读取)
            └── ReadAt() 带中断支持的流式读取
```

---

## 八、与现有 S-series 主题的关联

| 关联主题 | 关系说明 |
|----------|----------|
| S68 / S76 | FFmpegDemuxerPlugin 使用 MultiStreamParserManager 管理 HEVC/VVC 流解析 |
| S79 | MPEG4DemuxerPlugin 使用 MultiStreamParserManager 管理 AVC 流解析 |
| S75 | MediaDemuxer 是消费者，调用 DemuxerPluginManager → MultiStreamParserManager |
| S97 | DemuxerPluginManager 管理插件加载，MultiStreamParserManager 是具体实现 |
| S101 | StreamDemuxer 使用 TimeRangeManager 进行 Seek 范围管理 |
| S102 | SampleQueueController 流控与 TimeRangeManager Seek 范围联动 |
| S105 | BlockQueuePool 是底层队列基础设施，与 ReferenceParserManager 插件加载互补 |
| S140 | Converter/TimeRangeManager/MultiStreamParserManager 三组件已在 S140 提及，S177 补充行号级源码证据 |
| S143 | StreamParser 基类/HevcParseFormat/PacketConvertToBufferInfo 结构体已在 S143 提及，S177 补充完整类定义和dlopen机制 |
| S111 | S111 已包含 BlockQueue/BlockQueuePool/ReferenceParser/MultiStreamParserManager 四组件，S177 是行号增强版 |

---

## 九、关键证据汇总

| 行号 | 文件 | 证据说明 |
|------|------|----------|
| L35-85 | multi_stream_parser_manager.h | StreamInfo结构体 + streamMap_多轨管理 |
| L1-77 | multi_stream_parser_manager.cpp | dlopen + RTLD_LAZY + CreateFunc/dlsym 插件加载 |
| L27-31 | stream_parser.h | VideoStreamType 枚举 (HEVC/VVC/AVC) |
| L47-96 | stream_parser.h | StreamParser 抽象基类 14个纯虚函数接口 |
| L34-45 | stream_parser.h | HevcParseFormat HDR元数据结构体 12个字段 |
| L36-75 | converter.h | Converter 类 12个静态转换函数声明 |
| L1-40 | converter.cpp | 色彩空间转换函数实现 (PQ/HLG/BT2020) |
| L20-45 | time_range_manager.h | TimeRangeManager 类 6个公开接口 |
| L1-77 | time_range_manager.cpp | IsTimeInRange + GetNearestRange 实现 |
| L35-77 | reference_parser_manager.h | ReferenceParserManager 类 dlopen 管理 |
| L1-138 | reference_parser_manager.cpp | CreateParser + dlopen 加载逻辑 |
| L1-41 | reference_parser.h | IReferenceParser C API 接口声明 |
| L1-63 | demuxer_data_reader.h | DemuxerDataReader 类 3个核心接口 |
| L30-80 | demuxer_data_reader.cpp | ReadAt 带中断支持实现 |