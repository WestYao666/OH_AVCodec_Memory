---
type: architecture
id: MEM-ARCH-AVCODEC-S143
status: pending_approval
created_at: "2026-05-15T02:58:55+08:00"
updated_at: "2026-05-15T02:58:55+08:00"
created_by: builder
topic: StreamParserManager 流式解析管理——StreamParser基类/HevcParseFormat HDR元数据/PacketConvertToBufferInfo/HEVCProfile+ColorRange提取/ConvertPacketToAnnexb
scope: [AVCodec, MediaEngine, StreamParser, StreamParserManager, HevcParseFormat, PacketConvertToBufferInfo, HEVC, VVC, AVC, Bitstream, AnnexB, ConvertPacketToAnnexb, ParseExtraData, HDR, ColorRange]
created_at: "2026-05-15T02:58:55+08:00"
summary: StreamParserManager流式解析管理——StreamParser接口(96行h)/HevcParseFormat HDR元数据/PacketConvertToBufferInfo转换结构/ConvertPacketToAnnexb AnnexB转换/GetColorPrimaries+GetLevelIdc提取，与S105(S130)/S141关联
source_repo: /home/west/av_codec_repo
source_root: services/media_engine/plugins/common
evidence_version: local_mirror
---

## 一、架构总览

StreamParser 流式解析基础设施位于 `services/media_engine/plugins/common/` 目录，包含 StreamParser 基类（96行h）、StreamParserManager 管理器（227行cpp）、HevcParseFormat HDR 元数据结构、PacketConvertToBufferInfo 转换结构。

**定位**：HEVC/VVC/AVC 码流解析的核心基础设施，介于 DemuxerPlugin（输出原始 H.26x 分组）和 FFmpegDecoder（输入 AnnexB 格式）之间，负责 ExtraData 处理、Bitstream 格式转换（HVCC→AnnexB）、HDR 元数据提取。

## 二、文件清单与行号级证据

| 文件 | 行数 | 说明 |
|------|------|------|
| `stream_parser.h` | 96 | StreamParser 基类 + HevcParseFormat + PacketConvertToBufferInfo |
| `stream_parser_manager.cpp` | 227 | StreamParserManager 管理器实现 |
| `stream_parser_manager.h` | 73 | StreamParserManager 类定义 |
| `hdi_codec.cpp` | 365 | HdiCodec（用于硬件编解码参数传递） |
| `hdi_codec.h` | 140 | HdiCodec 类定义 + AudioCodecOmxParam |

## 三、核心数据结构

### 3.1 VideoStreamType 枚举（stream_parser.h:24-28）

```cpp
// stream_parser.h:24-28 - 视频流类型
enum VideoStreamType {
    HEVC = 0,  // H.265/HEVC
    VVC  = 1,  // H.266/VVC
    AVC  = 2,  // H.264/AVC
};
```

### 3.2 PacketConvertToBufferInfo（stream_parser.h:30-47）

```cpp
// stream_parser.h:30-47 - 码流转换结构（输入+输出缓冲区）
struct PacketConvertToBufferInfo {
    // 原始输入数据
    const uint8_t *srcData {nullptr};   // 源数据指针（HVCC格式）
    int32_t srcDataSize {0};           // 源数据大小

    // 输出缓冲区（外部申请）
    uint8_t *outBuffer {nullptr};      // 输出缓冲区指针
    int32_t outBufferSize {0};         // 输出缓冲区大小

    // 转换后的实际输出大小（输出参数）
    int32_t &outDataSize;              // 引用返回实际输出大小

    // 可选的 sideData 信息
    uint8_t *sideData {nullptr};
    size_t sideDataSize {0};

    explicit PacketConvertToBufferInfo(int32_t &outSizeRef) : outDataSize(outSizeRef) {}
};
```

### 3.3 HevcParseFormat（stream_parser.h:50-62）

```cpp
// stream_parser.h:50-62 - HEVC 格式解析结果
struct HevcParseFormat {
    bool isHdrVivid = false;           // HDR Vivid 标志
    bool isHdr10Plus = false;          // HDR10+ 标志
    bool isHdr = false;                // HDR 标志
    int32_t colorRange = 0;            // 色域范围（0=有限，1=完整）
    uint8_t colorPrimaries = 0x02;    // 色原（默认值 0x02=reserved）
    uint8_t colorTransfer = 0x02;      // 传递特性
    uint8_t colorMatrixCoeff = 0x02;   // 矩阵系数
    uint8_t profile = 0;              // HEVC Profile
    uint8_t level = 0;                // HEVC Level
    uint32_t chromaLocation = 0;       // 色度位置
    uint32_t picWidInLumaSamples = 0; // 图像宽度（luma采样）
    uint32_t picHetInLumaSamples = 0; // 图像高度（luma采样）
};
```

## 四、StreamParser 抽象基类（stream_parser.h:65-93）

```cpp
// stream_parser.h:65-93 - 流式解析器抽象接口
class StreamParser {
public:
    virtual void ParseExtraData(const uint8_t *sample, int32_t size,
                                uint8_t **extraDataBuf, int32_t *extraDataSize) = 0;  // 解析额外数据（VPS/SPS/PPS）
    virtual bool ConvertExtraDataToAnnexb(uint8_t *extraData, int32_t extraDataSize) = 0;  // ExtraData → AnnexB
    virtual void ConvertPacketToAnnexb(uint8_t **hvccPacket, int32_t &hvccPacketSize,
        uint8_t *sideData, size_t sideDataSize, bool isExtradata) = 0;  // Packet → AnnexB
    virtual bool ConvertPacketToAnnexb(const PacketConvertToBufferInfo &convertInfo) = 0;  // 重载版
    virtual void ParseAnnexbExtraData(const uint8_t *sample, int32_t size) = 0;  // 解析 AnnexB 额外数据
    virtual void ResetXPSSendStatus() = 0;  // 重置 XPS 发送状态
    virtual bool IsHdrVivid() = 0;         // 是否 HDR Vivid
    virtual bool IsHdr10Plus() = 0;        // 是否 HDR10+
    virtual bool IsHdr() = 0;              // 是否 HDR
    virtual bool IsSyncFrame(const uint8_t *sample, int32_t size) = 0;  // 是否同步帧（IDR帧）
    virtual bool GetColorRange() = 0;      // 获取色域范围
    virtual bool GetColorPrimaries(...) = 0;  // 获取色原
    virtual bool GetColorTransfer(...) = 0;  // 获取传递特性
    virtual bool GetColorMatrixCoeff(...) = 0; // 获取矩阵系数
    virtual uint8_t GetProfileIdc() = 0;      // 获取 Profile
    virtual uint8_t GetLevelIdc() = 0;        // 获取 Level
    virtual uint32_t GetChromaLocation() = 0; // 获取色度位置
    virtual uint32_t GetPicWidInLumaSamples() = 0; // 获取图像宽度
    virtual uint32_t GetPicHetInLumaSamples() = 0; // 获取图像高度
};
```

## 五、StreamParserManager 管理器（stream_parser_manager.h:29-52）

```cpp
// stream_parser_manager.h:29-52 - StreamParser 管理器
class StreamParserManager {
public:
    // 初始化（stream_parser_manager.cpp:56）
    static bool Init(VideoStreamType videoStreamType);
    // 解析 ExtraData
    void ParseExtraData(const uint8_t *sample, int32_t size,
                        uint8_t **extraDataBuf, int32_t *extraDataSize);
    // AnnexB 转换
    bool ConvertExtraDataToAnnexb(uint8_t *extraData, int32_t extraDataSize);
    bool ConvertPacketToAnnexb(uint8_t **hvccPacket, int32_t &hvccPacketSize,
        uint8_t *sideData, size_t sideDataSize, bool isExtradata);
    // HDR 查询
    bool IsHdrVivid();
    bool IsSyncFrame(const uint8_t *sample, int32_t size);
    // ColorPrimaries/Transfer/Matrix 提取
    uint8_t GetColorPrimaries();
    uint8_t GetColorTransfer();
    uint8_t GetColorMatrixCoeff();
    // Profile/Level 提取
    uint8_t GetProfileIdc();
    uint8_t GetLevelIdc();
    // 色度/尺寸查询
    uint32_t GetChromaLocation();
    uint32_t GetPicWidInLumaSamples();
    uint32_t GetPicHetInLumaSamples();
    // 状态重置
    void ResetXPSSendStatus();

private:
    std::unique_ptr<StreamParser> streamParser_;  // 实际解析器实例
};

// stream_parser_manager.h:29 - DestroyFunc 类型别名
using DestroyFunc = void (*)(StreamParser *);

// dlopen 动态加载 StreamParser 实现
```

## 六、转换流程（HVCC → AnnexB）

```cpp
// StreamParserManager::ConvertPacketToAnnexb
// 输入：HVCC (HEVC Bitstream Format, with length prefix)
// 输出：AnnexB (start codes 0x00 0x00 0x00 0x01)

// 关键转换逻辑：
// 1. 找到 HVCC 中的 NAL 单元（NAL header + RBSP）
// 2. 添加 AnnexB start code (0x00000001)
// 3. 处理 RBSP → EBSP（防竞争字节插入）
// 4. 输出到 outBuffer

// stream_parser_manager.cpp:37 - dlopen 加载
// streamParser_ = std::unique_ptr<StreamParser>(LoadStreamParser(videoStreamType));
```

## 七、与相关 S-series 记忆的关联

| 关联记忆 | 关系 | 说明 |
|---------|------|------|
| S105（HEVC 解码器） | 下游消费者 | HEVC 解码器接收 AnnexB 格式的 bitstream |
| S130（FFmpegAdapter Common） | 并列 | S130 色域转换（AVColorRange/ColorPrimaries），S143 流式解析（HVCC→AnnexB） |
| S141（PTS索引转换） | 同级 | 并列同为 MediaEngine 的辅助模块 |

---

_builder-agent: S143 draft generated 2026-05-15T02:58:55+08:00, pending approval_