---
id: MEM-ARCH-AVCODEC-S105
title: "BlockQueuePool 内存池化框架与 Demuxer 公共组件——SamplePacket/MPEG4Sample 双容器体系与格式转换"
scope: [AVCodec, Demuxer, MemoryPool, BlockQueue, RBSP, AVC, Converter, MultiStream, LogCompressor]
status: approved
approved_at: "2026-05-09T04:20:00+08:00"
approved_by: ou_60d8641be684f82e8d9cb84c3015dde7
approval_submitted_at: "2026-05-09T04:50:00+08:00"
created_by: builder-agent
created_at: "2026-05-09T04:20:00+08:00"
evidence_sources:
  - "services/media_engine/plugins/demuxer/common/block_queue_pool.h (552行)"
  - "services/media_engine/plugins/demuxer/common/block_queue.h"
  - "services/media_engine/plugins/demuxer/common/avc_parser_impl.h (156行)"
  - "services/media_engine/plugins/demuxer/common/avc_parser_impl.cpp (330行)"
  - "services/media_engine/plugins/demuxer/common/rbsp_context.h (71行)"
  - "services/media_engine/plugins/demuxer/common/rbsp_context.cpp (82行)"
  - "services/media_engine/plugins/demuxer/common/converter.h (88行)"
  - "services/media_engine/plugins/demuxer/common/converter.cpp (176行)"
  - "services/media_engine/plugins/demuxer/common/demuxer_data_reader.h (63行)"
  - "services/media_engine/plugins/demuxer/common/demuxer_log_compressor.h (31行)"
  - "services/media_engine/plugins/demuxer/common/demuxer_log_compressor.cpp (219行)"
---

# S105: BlockQueuePool 内存池化框架与 Demuxer 公共组件——SamplePacket/MPEG4Sample 双容器体系与格式转换

## 一句话总结

BlockQueuePool 是 FFmpegDemuxerPlugin 和 MPEG4DemuxerPlugin 共用的**内存池化与阻塞队列框架**，通过模板化 BlockTraits 特化机制支持 FFmpeg SamplePacket 和 MPEG4 Sample 双容器体系，配合 RBSP 上下文解析、AVC NAL 单元转换和格式转换器，构成解封装插件的**底层基础设施层**。

## 源码分析

### 1. 核心文件架构

```
services/media_engine/plugins/demuxer/common/
├── block_queue_pool.h      (552行)  ← 模板化内存池核心
├── block_queue.h           ← 阻塞队列实现
├── avc_parser_impl.h       (156行)  ← AVC NAL 单元解析器
├── avc_parser_impl.cpp    (330行)
├── rbsp_context.h         (71行)    ← RBSP ↔ EBSP 转换
├── rbsp_context.cpp       (82行)
├── converter.h            (88行)    ← BitReader / ByteStream 转换
├── converter.cpp          (176行)
├── demuxer_data_reader.h  (63行)    ← 数据源读取 + BitReader
├── demuxer_log_compressor.h (31行)  ← 元数据序列化
└── demuxer_log_compressor.cpp (219行)
```

### 2. BlockQueuePool 模板化内存池

**文件**: `block_queue_pool.h:1-100`

BlockQueuePool 是一个模板化的内存池，通过 `BlockTraits<T>` 特化来适配不同的数据类型：

```cpp
// 模板特化 - FFmpeg SamplePacket
template<>
struct BlockTraits<Ffmpeg::SamplePacket> {
    static uint32_t GetDataSize(const std::shared_ptr<Ffmpeg::SamplePacket>& block);
    static void UpdateMaxPts(const std::shared_ptr<Ffmpeg::SamplePacket>& block, int64_t& maxPts);
};

// 模板特化 - MPEG4 Sample
template<>
struct BlockTraits<MPEG4::MPEG4Sample> {
    static uint32_t GetDataSize(const std::shared_ptr<MPEG4::MPEG4Sample>& block);
    static void UpdateMaxPts(const std::shared_ptr<MPEG4::MPEG4Sample>& block, int64_t& maxPts);
};
```

**FFmpeg SamplePacket 结构** (`block_queue_pool.h:35-50`):
```cpp
namespace Ffmpeg {
struct SamplePacket {
    uint32_t offset = 0;
    std::vector<AVPacketWrapperPtr> pkts {};  // 多包聚合
    bool isEOS = false;
    bool isAnnexb = false;                     // AnnexB vs AVCC 格式标志
    uint32_t queueIndex = 0;
};
}
```

**MPEG4 Sample 结构** (`block_queue_pool.h:50-70`):
```cpp
namespace MPEG4 {
struct Sample {
    enum SampleFlag : uint32_t {
        NONE = 0,
        EOS = 1 << 0,
        SYNC_FRAME = 1 << 1,
        DISCARD = 1 << 4,
    };
    int64_t pts;
    int64_t dts;
    int64_t duration;
    uint32_t flag;       // EOS/SYNC_FRAME/DISCARD 标志
    int32_t size;
    std::unique_ptr<uint8_t[]> data;  // 独立内存申请
};

struct MPEG4Sample {
    int32_t offset = 0;
    std::shared_ptr<Sample> sample = nullptr;
    bool isAnnexb = false;
    uint32_t queueIndex = 0;
};
}
```

**BlockQueuePool 核心接口** (`block_queue_pool.h:100-200`):
- `Pop() / Push()` — 阻塞队列操作
- `GetPoolSize() / SetPoolSize()` — 内存池大小配置
- `Clear()` — 清空所有缓冲

### 3. AVC Parser 实现——NAL 单元解析

**文件**: `avc_parser_impl.h:28-80`

```cpp
class AvcParserImpl {
public:
    int32_t ParseSps(const uint8_t *data, size_t len);
    int32_t ParsePps(const uint8_t *data, size_t len);
    int32_t ParseVps(const uint8_t *data, size_t len);
    int32_t ParseNalu(const uint8_t *data, size_t len, NaluInfo &naluInfo);
    // ... 其他方法
private:
    std::vector<SpsPpsInfo> spsPpsInfoVec_;
    std::vector<VpsInfo> vpsInfoVec_;
    int32_tParseSpsData(const uint8_t *data, size_t len, SpsPpsInfo &spsPpsInfo);
    int32_tParsePpsData(const uint8_t *data, size_t len, SpsPpsInfo &spsPpsInfo);
    int32_tParseVpsData(const uint8_t *data, size_t len, VpsInfo &vpsInfo);
    bool DecodeSps(const uint8_t *data, size_t len, SpsPpsInfo &spsPpsInfo);
};
```

**NAL 单元类型** (`avc_parser_impl.h:15-25`):
- SPS (0x67) — 序列参数集
- PPS (0x68) — 图像参数集
- VPS (0x67 with vps_id) — 视频参数集
- IDR (0x65) — 关键帧
- non-IDR (0x41) — P/B 帧

### 4. RBSP 上下文——EBSP → RBSP 转换

**文件**: `rbsp_context.h:20-60`

RBSP (Raw Byte Sequence Payload) 是 NAL 单元的语法元素编码格式，需要将 EBSP (Encapsulated Byte Sequence Payload) 中的防伪字节 (0x000003) 转义还原：

```cpp
class RbspContext {
public:
    int32_t ProcessNalu(const uint8_t *ebspData, size_t ebspSize,
                        uint8_t *rbspData, size_t *rbspSize);
    // 防伪字节转义：0x000003 → 0x0000 (删除 03)
    // START_CODE 恢复：0x000001 → 0x00000001
};
```

关键转义规则 (`rbsp_context.cpp:20-40`):
- `0x000003` → 删除中间 `03` → `0x0000`
- `0x000001` → 恢复为完整的 start code

### 5. Converter —— BitReader 与格式转换

**文件**: `converter.h:30-88`

```cpp
class BitReader {
public:
    uint32_t ReadBits(uint8_t numBits);
    uint32_t ShowBits(uint8_t numBits);
    bool SkipBits(uint8_t numBits);
    bool HasBits(size_t numBits) const;
private:
    const uint8_t* data_;
    size_t byteOffset_;
    uint8_t bitOffset_;
    size_t totalBytes_;
};

class ByteStreamConverter {
public:
    static Status ConvertAvccToAnnexb(const uint8_t *avccData, size_t avccSize,
                                      uint8_t *annexbData, size_t *annexbSize);
    // AVCC (length prefix) → AnnexB (start code) 转换
};
```

### 6. DemuxerDataReader —— 数据源 + BitReader

**文件**: `demuxer_data_reader.h:30-63`

```cpp
class DemuxerDataReader {
public:
    Status SetDataReader(const std::shared_ptr<DataSource>& source);
    Status ReadUintData(int64_t offset, uint8_t* buffer, size_t size);
};

class DemuxerBitReader {
public:
    DemuxerBitReader(const uint8_t* data, size_t size);
    uint16_t ShowBits(uint8_t numBits);
    uint8_t ReadBits(uint8_t numBits);
    bool HasBits(size_t numBits) const;
    bool SkipBits(uint8_t numBits);
};
```

### 7. DemuxerLogCompressor —— 元数据序列化

**文件**: `demuxer_log_compressor.h:20-31`

```cpp
class DemuxerLogCompressor {
public:
    static std::string FormatTagSerialize(Format& format);
    static void StringifyMeta(Meta meta, int32_t trackIndex);
};
```

将 Format 元数据（宽/高/码率/帧率/色彩空间等）序列化为字符串，供日志和调试使用。

## 关联记忆

- **S58** (MEM-ARCH-AVCODEC-S58): MPEG4BoxParser — 容器 Box 解析，block_queue_pool.h 中的 MPEG4Sample 即来自 S58 的解析结果
- **S68** (MEM-ARCH-AVCODEC-S68): FFmpegDemuxerPlugin — 使用 SamplePacket 容器和 BitstreamFilter 转换
- **S75** (MEM-ARCH-AVCODEC-S75): MediaDemuxer 六组件 — BlockQueuePool 是 SampleQueue 的底层支撑
- **S76** (MEM-ARCH-AVCODEC-S76): FFmpegDemuxerPlugin — 同 S68，双轨并行
- **S69** (MEM-ARCH-AVCODEC-S69): MediaDemuxer SampleQueue — 流控引擎上游
- **S41** (MEM-ARCH-AVCODEC-S41): DemuxerFilter — Filter 层封装

## 架构定位

```
┌─────────────────────────────────────────────────────────┐
│           FFmpegDemuxerPlugin / MPEG4DemuxerPlugin       │
├─────────────────────────────────────────────────────────┤
│  MultiStreamParserManager (多轨 Parser)                  │
│  ↕                                                        │
│  BlockQueuePool (模板化内存池)                            │
│  ├── BlockTraits<Ffmpeg::SamplePacket>  (FFmpeg路径)     │
│  └── BlockTraits<MPEG4::MPEG4Sample>   (MPEG4路径)        │
├─────────────────────────────────────────────────────────┤
│  公共组件层                                               │
│  ├── AvcParserImpl (NAL单元解析)                         │
│  ├── RbspContext (EBSP↔RBSP转义)                        │
│  ├── Converter / ByteStreamConverter (格式转换)          │
│  ├── DemuxerDataReader / DemuxerBitReader (数据读取)     │
│  └── DemuxerLogCompressor (元数据序列化)                 │
└─────────────────────────────────────────────────────────┘
```

BlockQueuePool 是 FFmpeg 和 MPEG4 两条 Demuxer 路径共用的内存池基础设施，通过模板特化机制支持双容器体系，是解封装层的底层支撑组件。