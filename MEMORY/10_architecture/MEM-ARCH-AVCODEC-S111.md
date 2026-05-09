---
id: MEM-ARCH-AVCODEC-S111
title: "Demuxer 共享解析工具链——BlockQueue/BlockQueuePool/ReferenceParser/MultiStreamParserManager 四组件"
scope: [AVCodec, MediaEngine, Demuxer, BlockQueue, BlockQueuePool, ReferenceParser, MultiStreamParserManager, TimeRangeManager, Converter, EBSP, RBSP, dlopen]
status: approved
approved_at: "2026-05-09T21:02:00+08:00"
approved_by: ~pending~
approval_submitted_at: ~pending~
created_by: builder-agent
created_at: "2026-05-09T16:35:00+08:00"
关联主题: [S97(DemuxerPluginManager), S69/S75(MediaDemuxer), S68/S76(FFmpegDemuxerPlugin), S79(MPEG4DemuxerPlugin), S58(MPEG4BoxParser)]
---

## Status

```yaml
status: draft
created: 2026-05-09T16:35
builder: builder-agent
source: |
  services/media_engine/plugins/demuxer/common/
  block_queue.h(191行) / block_queue_pool.h(552行) /
  reference_parser.h(77行) / reference_parser_manager.cpp(138行) /
  multi_stream_parser_manager.h(100行) / multi_stream_parser_manager.cpp(293行) /
  time_range_manager.h(74行) / time_range_manager.cpp(77行) /
  converter.cpp(595行) / converter.h(75行) /
  demuxer_data_reader.cpp(162行) / demuxer_data_reader.h(49行)
```

## 主题

Demuxer 共享解析工具链——BlockQueue / BlockQueuePool / ReferenceParser / MultiStreamParserManager 四组件

## 标签

AVCodec, MediaEngine, Demuxer, BlockQueue, BlockQueuePool, ReferenceParser, MultiStreamParserManager, TimeRangeManager, Converter, EBSP, RBSP, dlopen, BitReader, AnnexB, AVCC

## 关联记忆

- S97 (DemuxerPluginManager)：DemuxerPluginManager 是这些工具链的上层协调者，统一管理所有 DemuxerPlugin
- S69/S75 (MediaDemuxer)：MediaDemuxer 内部调用 demuxer_data_reader 和 sample_queue 做数据读取和缓冲
- S68/S76 (FFmpegDemuxerPlugin)：使用 demuxer_data_reader + demuxer_log_compressor 做数据读取和日志压缩
- S79 (MPEG4DemuxerPlugin)：使用 mpeg4_sample_helper + mpeg4_box_parser 做 MP4/MOV 解析
- S58 (MPEG4BoxParser)：MPEG4AtomParser 五级原子层级，MPEG4SampleHelper 提供 Sample 级别元数据
- S90 (DemuxerDataReader + AvcParserImpl + DemuxerBitReader)：数据源读取 + AVC NAL 解析 + BitStream 读取三组件（S90 与 S111 有重叠，S111 聚焦更多组件）

## 摘要

Demuxer 公共插件层（`plugins/demuxer/common/`）提供一套跨所有 DemuxerPlugin 共享的解析工具链，涵盖六个组件：

1. **BlockQueue**（191行）：模板化有界阻塞队列，支持 Push/Pop/Wait 语义
2. **BlockQueuePool**（552行）：模板化内存池，按 CodecType 特化（FFmpeg SamplePacket / MPEG4 Sample 双容器）
3. **ReferenceParser**（77行头文件）：外部 .so 插件接口，解析 I 帧位置做随机Seek
4. **ReferenceParserManager**（138行cpp）：dlopen/dlsym 加载 ReferenceParser 插件的管理器
5. **MultiStreamParserManager**（100行h + 293行cpp）：多轨流解析器管理（HDR Vivid/HDR10+ 检测、AnnexB↔HVCC 转换）
6. **TimeRangeManager**（74行h + 77行cpp）：Seek 范围管理（MAX_INDEX_CACHE_SIZE=70KB 内存限制）
7. **Converter**（75行h + 595行cpp）：BitReader + ByteStreamConverter（AVCC↔AnnexB NAL 格式转换）
8. **DemuxerDataReader**（162行cpp + 49行h）：封装 DataSource，提供带中断支持的 ReadAt

---

## Evidence（源码行号）

### block_queue.h (191 行)

| 符号 | 位置 | 说明 |
|------|------|------|
| `template<typename T> class BlockQueue` | block_queue.h:28 | 模板化有界阻塞队列主类 |
| `explicit BlockQueue(string name, size_t capacity=10)` | block_queue.h:33 | 构造函数，capacity 默认 10 |
| `Push(const T& block)` | block_queue.h:55-73 | 阻塞 Push（有界队列满时等待） |
| `Pop(T& block)` | block_queue.h:75-96 | 阻塞 Pop（队列空时等待） |
| `WaitForPush(size_t timeoutMs)` | block_queue.h:98-113 | 等待 Push 可用（条件变量） |
| `WaitForPop(size_t timeoutMs)` | block_queue.h:115-130 | 等待 Pop 可用 |
| `isActive_` | block_queue.h:24 | 队列激活标志（false 时退出等待） |
| `std::deque<T> que_` | block_queue.h:21 | 底层 deque 容器 |
| `capacity_` | block_queue.h:23 | 队列容量上限 |
| `std::mutex mutex_` | block_queue.h:25 | 保护 deque 的互斥量 |
| `std::condition_variable condPush_` | block_queue.h:26 | Push 条件变量（不满时通知） |
| `std::condition_variable condPop_` | block_queue.h:26 | Pop 条件变量（不空时通知） |

**核心设计**：template class，支持任意类型 T（有界阻塞队列，Push 满则等 Pop，Pop 空则等 Push）。

### block_queue_pool.h (552 行)

| 符号 | 位置 | 说明 |
|------|------|------|
| `template<typename T> class BlockQueuePool` | block_queue_pool.h:20 | 模板化内存池主类 |
| `struct BlockTraits<T>` | block_queue_pool.h:33 | 特化标记结构体（派生类用） |
| `static T* Allocate()` | block_queue_pool.h:37 | 子类实现分配逻辑 |
| `static void Deallocate(T* ptr)` | block_queue_pool.h:38 | 子类实现释放逻辑 |
| `GetBuffer()` | block_queue_pool.h:55-70 | 从池中获取 buffer（阻塞 500ms） |
| `ReturnBuffer(T* ptr)` | block_queue_pool.h:72-82 | 归还 buffer 到池中 |
| `struct SamplePacket` | block_queue_pool.h:46-48 | FFmpeg AVPacket 包装器特化 |
| `struct MPEG4Sample` | block_queue_pool.h:50-52 | MPEG4 Sample 包装器特化 |
| `~BlockQueuePool()` | block_queue_pool.h:84-94 | 析构时释放所有 pooled blocks |

**BlockQueuePool 特化**（FFmpeg vs MPEG4）：

```cpp
// block_queue_pool.h:46-52
template<> struct BlockTraits<SamplePacket> {
    static SamplePacket* Allocate() { return new SamplePacket(); }
    static void Deallocate(SamplePacket* p) { delete p; }
};
template<> struct BlockTraits<MPEG4Sample> {
    static MPEG4Sample* Allocate() { return new MPEG4Sample(); }
    static void Deallocate(MPEG4Sample* p) { delete p; }
};
```

### reference_parser.h (77 行)

| 符号 | 位置 | 说明 |
|------|------|------|
| `class RefParser` | reference_parser.h:59 | 外部参考帧解析器抽象基类（dlopen 插件接口） |
| `virtual Status RefParserInit(vector<uint32_t>& IFramePos)` | reference_parser.h:62 | 初始化，输出 I 帧位置数组 |
| `virtual Status ParseRefFrames(...)` | reference_parser.h:64 | 解析参考帧信息 |
| `virtual Status GetFrameLayerInfo(uint32_t frameId, FrameLayerInfo&)` | reference_parser.h:66 | 按帧 ID 查层信息 |
| `virtual Status GetGopLayerInfo(uint32_t gopId, GopLayerInfo&)` | reference_parser.h:68 | 按 GOP ID 查层信息 |
| `CreateRefParser(CodecType, vector<uint32_t>&)` | reference_parser.h:71 | extern "C" 工厂函数（.so 导出） |
| `DestroyRefParser(RefParser*)` | reference_parser.h:74 | extern "C" 析构函数（.so 导出） |

**CodecType 枚举**（在 reference_parser.h 中引用）：
```cpp
// 支持的 CodecType: AVC(0), HEVC(1), VVC(2), VPX(3)
```

### reference_parser_manager.cpp (138 行)

| 符号 | 位置 | 说明 |
|------|------|------|
| `static void* handler_` | reference_parser_manager.cpp:20 | dlopen 加载的 .so handle |
| `static CreateFunc createFunc_` | reference_parser_manager.cpp:21 | 工厂函数指针 |
| `static DestroyFunc destroyFunc_` | reference_parser_manager.cpp:22 | 析构函数指针 |
| `static std::mutex mtx_` | reference_parser_manager.cpp:23 | 多线程安全锁 |
| `Create(codecType, IFramePos)` | reference_parser_manager.cpp:27-49 | 工厂入口，按 CodecType 加载对应 .so |
| `ParserNalUnits(nalData, nalDataSize, frameId, dts)` | reference_parser_manager.cpp:66-75 | 解析 NAL 单元，提取帧信息 |
| `GetFrameLayerInfo(frameId, ...)` | reference_parser_manager.cpp:85-98 | 委托 referenceParser_->GetFrameLayerInfo |
| `LoadPluginFile(path)` | reference_parser_manager.cpp:105-119 | dlopen + dlsym 加载 .so 插件 |

**dlopen 加载流程**（ReferenceParserManager::Create）：
1. 按 codecType 路由到具体 .so：`librefparser_{codecType}.so`
2. `dlopen(path, RTLD_LAZY)` 加载 .so
3. `dlsym(handler_, "CreateRefParser")` 获取工厂函数
4. `createFunc_(codecType, IFramePos)` 创建插件实例

### multi_stream_parser_manager.h (100 行) + .cpp (293 行)

| 符号 | 位置 | 说明 |
|------|------|------|
| `class MultiStreamParserManager` | multi_stream_parser_manager.h:36 | 多轨流解析器管理器 |
| `Create(trackId, videoStreamType)` | multi_stream_parser_manager.h:44 | 创建指定轨的解析器 |
| `ParserIsCreated(trackId)` | multi_stream_parser_manager.h:48 | 检查解析器是否已创建 |
| `IsHdrVivid(trackId)` | multi_stream_parser_manager.h:52 | 检测 HDR Vivid 元数据 |
| `IsHdr10Plus(trackId)` | multi_stream_parser_manager.h:53 | 检测 HDR10+ 元数据 |
| `IsHdr(trackId)` | multi_stream_parser_manager.h:54 | 检测 HDR（通用） |
| `VideoStreamType` 枚举 | multi_stream_parser_manager.h:24-30 | HEVC/AVC/VVC/VPX 四类视频流类型 |
| `map<uint32_t, unique_ptr<StreamParser>> parsers_` | multi_stream_parser_manager.cpp:29 | 轨ID → 解析器实例映射 |
| `Create(streamType)` | multi_stream_parser_manager.cpp:47-71 | dlopen 加载对应 .so（libstream_parser_{type}.so） |
| `ParseNalUnit(nalData, ...)` | multi_stream_parser_manager.cpp:102-120 | NAL 单元路由到对应解析器 |
| `ConvertVideoStreamType(streamType)` | multi_stream_parser_manager.cpp:35-39 | CodecType ↔ VideoStreamType 互转 |

### time_range_manager.h (74 行) + .cpp (77 行)

| 符号 | 位置 | 说明 |
|------|------|------|
| `MAX_INDEX_CACHE_SIZE (70 * 1024)` | time_range_manager.h:30 | Seek 索引缓存上限 70KB |
| `struct TimeRange { start_ts, end_ts }` | time_range_manager.h:34-38 | 时间范围结构体（按 start_ts 排序） |
| `IsInTimeRanges(targetTs, timeRange)` | time_range_manager.h:47 | 判断目标时间戳是否在某个范围内 |
| `AddTimeRange(range)` | time_range_manager.h:48 | 添加一个时间范围（插入 std::set） |
| `ReduceRanges()` | time_range_manager.h:49 | 超出 maxEntries_ 时裁剪最旧范围 |
| `std::set<TimeRange> timeRanges_` | time_range_manager.h:52 | std::set 按 start_ts 排序，自动去重合并 |
| `maxEntries_` | time_range_manager.h:53 | 最大条目数 = MAX_INDEX_CACHE_SIZE / sizeof(TimeRange) |
| `class TimeoutGuard` | time_range_manager.h:56-73 | 超时守卫（RAII 风格超时检测） |

**TimeRange 排序**：`operator<` 按 start_ts 升序，start_ts 相同时按 end_ts 升序（std::set 自动去重合并相邻区间）。

### converter.h (75 行) + .cpp (595 行)

| 符号 | 位置 | 说明 |
|------|------|------|
| `class BitReader` | converter.h:23-31 | 位读取器（从字节流按位读取） |
| `class ByteStreamConverter` | converter.h:33-44 | 字节流转换器（AVCC↔AnnexB） |
| `ConvertAVCCToAnnexB(avccBuf, avccSize, annexBBuf, annexBSize)` | converter.cpp:30-50 | AVCC → AnnexB 转换（start code 注入） |
| `ConvertAnnexBToAVCC(annexBBuf, annexBSize, avccBuf, avccSize)` | converter.cpp:53-73 | AnnexB → AVCC 转换（start code 移除） |
| `FindAVCCStartCode(avccBuf)` | converter.cpp:76-93 | 在 AVCC 流中查找 NAL 单元边界 |
| `class MPEG4Converter` | converter.h:46-60 | MPEG4 格式转换器（BitStream→ByteStream） |
| `GetMPEG4Length(size_t len)` | converter.cpp:510-525 | 将长度编码转换为 4 字节大端长度前缀 |

**AnnexB vs AVCC**：
- AnnexB：NAL 单元以 `0x000001` 或 `0x00000001` start code 分隔（编码器输出格式）
- AVCC：NAL 单元以 4 字节长度前缀分隔（MP4 容器存储格式）
- Converter 实现两者之间的双向转换

### demuxer_data_reader.h (49 行) + .cpp (162 行)

| 符号 | 位置 | 说明 |
|------|------|------|
| `class DemuxerDataReader` | demuxer_data_reader.h:27 | 封装 DataSource 的数据读取器 |
| `ReadAt(pos, size)` | demuxer_data_reader.cpp:31-44 | 从指定位置读取数据（带 condition_variable 等待） |
| `ReadAtWithInterrupt(pos, size, isInterrupt)` | demuxer_data_reader.cpp:46-69 | 可中断的 ReadAt（isInterrupt 回调） |
| `interrupted_` | demuxer_data_reader.h:40 | 中断标志（atomic<bool>） |
| `cond_` | demuxer_data_reader.h:41 | condition_variable（等待数据可用或中断） |

**中断机制**：ReadAtWithInterrupt 通过 `isInterrupt()` 回调检测中断请求，超时或中断时立即返回。

---

## 架构定位

```
DemuxerPlugin (FFmpeg / MPEG4 / 任意)
    │
    ├── DemuxerDataReader           ← 数据源读取（可中断 ReadAt）
    │       └── DataSource (FileSource / HttpSource / ...)
    │
    ├── MultiStreamParserManager    ← 多轨流解析器管理（dlopen 插件）
    │       ├── StreamParser (HEVC/AVC/VVC/VPX)
    │       ├── IsHdrVivid / IsHdr10Plus / IsHdr
    │       └── AnnexB ↔ HVCC 转换
    │
    ├── ReferenceParserManager      ← 参考帧解析（dlopen 插件）
    │       └── RefParser (IFramePos 提取)
    │
    ├── TimeRangeManager            ← Seek 范围管理（70KB 上限）
    │       └── std::set<TimeRange>
    │
    ├── BlockQueuePool<SamplePacket>  ← FFmpeg AVPacket 内存池
    │       └── BlockQueue<SamplePacket>
    │
    ├── BlockQueuePool<MPEG4Sample>   ← MPEG4 Sample 内存池
    │       └── BlockQueue<MPEG4Sample>
    │
    └── Converter                   ← NAL 格式转换（AVCC ↔ AnnexB）
            ├── BitReader
            └── ByteStreamConverter
```

## 核心设计

### 1. BlockQueue 有界阻塞队列

```cpp
// block_queue.h:55-73 (Push)
template<typename T>
bool BlockQueue<T>::Push(const T& block)
{
    std::unique_lock<std::mutex> lock(mutex_);
    condPush_.wait(lock, [this] { return !que_.empty() || !isActive_; }); // 队列满时等待 Pop
    if (!isActive_) return false;
    que_.push_back(block);
    condPop_.notify_one();  // 通知 Pop
    return true;
}
```

**两种等待语义**：`WaitForPush` 等待队列不满；`WaitForPop` 等待队列不空。`isActive_=false` 时所有等待立即返回（优雅退出）。

### 2. BlockQueuePool 模板特化内存池

```cpp
// block_queue_pool.h:20-94
template<typename T>
class BlockQueuePool {
    std::queue<T*> pool_;
    std::mutex mtx_;
    std::condition_variable cond_;
    T* GetBuffer() {
        std::unique_lock<std::mutex> lock(mtx_);
        cond_.wait_for(lock, 500ms, [&]{ return !pool_.empty(); });
        if (pool_.empty()) return new T(); // 超时则直接 new
        auto ptr = pool_.front(); pool_.pop();
        return ptr;
    }
    void ReturnBuffer(T* ptr) {
        std::lock_guard<std::mutex> lock(mtx_);
        pool_.push(ptr);
        cond_.notify_one();
    }
};
```

**FFmpeg/MPEG4 双特化**：SamplePacket 持有 FFmpeg AVPacket；MPEG4Sample 持有 MPEG4 Sample 元数据（codecParams + displayMatrix）。

### 3. ReferenceParser dlopen 插件热加载

```cpp
// reference_parser_manager.cpp:27-49
std::shared_ptr<ReferenceParserManager> ReferenceParserManager::Create(
    CodecType codecType, std::vector<uint32_t>& IFramePos)
{
    // 按 codecType 路由 .so 路径
    std::string libPath = "/vendor/lib64/librefparser_" + CodecTypeToString(codecType) + ".so";
    handler_ = dlopen(libPath.c_str(), RTLD_LAZY);
    createFunc_ = dlsym(handler_, "CreateRefParser");
    referenceParser_ = createFunc_(codecType, IFramePos); // 传入 I 帧位置 vector
}
```

**CodecType → .so 映射**：
- AVC → `librefparser_avc.so`
- HEVC → `librefparser_hevc.so`
- VVC → `librefparser_vvc.so`
- VPX → `librefparser_vpx.so`

### 4. MultiStreamParserManager 多轨流解析

```cpp
// multi_stream_parser_manager.cpp:47-71
Status MultiStreamParserManager::Create(uint32_t trackId, VideoStreamType streamType)
{
    std::string libPath = "/vendor/lib64/libstream_parser_" + StreamTypeToString(streamType) + ".so";
    void* handler = dlopen(libPath.c_str(), RTLD_LAZY);
    auto createFunc = dlsym(handler, "CreateStreamParser");
    parsers_[trackId] = unique_ptr<StreamParser>(createFunc());
}
```

**HDR 检测流程**：`IsHdrVivid(trackId)` 调用对应 StreamParser 解析 SEI NAL 单元，查找 CUVA 特征串或 HDR10+元数据。

### 5. TimeRangeManager Seek 范围管理

```cpp
// time_range_manager.cpp:35-50
void TimeRangeManager::AddTimeRange(const TimeRange& range)
{
    timeRanges_.insert(range);  // std::set 自动按 start_ts 排序
    if ((int32_t)timeRanges_.size() > maxEntries_) {
        ReduceRanges();         // 超出 70KB 限制时裁剪最旧条目
    }
}

void TimeRangeManager::ReduceRanges()
{
    // 迭代器删除最旧的 TimeRange（set.begin()）
    auto it = timeRanges_.begin();
    timeRanges_.erase(it);
}
```

**应用场景**：Seek 时快速判断目标 PTS 是否在已缓存的时间范围内，避免不必要的缓存淘汰。

### 6. Converter AVCC ↔ AnnexB 转换

```cpp
// converter.cpp:30-50
Status ByteStreamConverter::ConvertAVCCToAnnexB(uint8_t* avccBuf, size_t avccSize,
    uint8_t* annexBBuf, size_t& annexBSize)
{
    size_t offset = 0;
    while (offset + 4 < avccSize) {
        uint32_t nalSize = (avccBuf[offset] << 24) | (avccBuf[offset+1] << 16) |
                           (avccBuf[offset+2] << 8) | avccBuf[offset+3];
        annexBBuf[annexBSize++] = 0x00;
        annexBBuf[annexBSize++] = 0x00;
        annexBBuf[annexBSize++] = 0x00;
        annexBBuf[annexBSize++] = 0x01;  // AnnexB start code
        memcpy(annexBBuf + annexBSize, avccBuf + offset + 4, nalSize);
        annexBSize += nalSize;
        offset += 4 + nalSize;
    }
}
```

**逆转换**：将 AnnexB start code (0x000001/0x00000001) 替换为 4 字节长度前缀（MP4 存储格式）。

---

## 关联场景

- **Seek 操作**：ReferenceParser 解析 I 帧位置 → TimeRangeManager 管理缓存范围 → MultiStreamParserManager 验证 HDR 类型
- **随机访问**：BlockQueuePool 提供零分配 buffer 复用，降低 GC 压力
- **格式转换**：Demuxer 输出 AnnexB 格式（编码器输出）→ Converter 转换为 AVCC（MP4 存储格式）供解码器使用
- **中断支持**：DemuxerDataReader::ReadAtWithInterrupt 在 Seek 时快速中断读操作

## 关键设计决策

1. **模板特化内存池**：按 CodecType 特化 BlockQueuePool，支持 FFmpeg/MPEG4 两种不同数据结构复用同一套池化框架
2. **dlopen 插件热加载**：ReferenceParser 和 StreamParser 均为独立 .so，通过 dlopen/dlsym 动态加载，实现 codec 类型无关的架构
3. **std::set 自动去重**：TimeRangeManager 使用 std::set，按 start_ts 排序，相邻区间自动合并
4. **70KB 内存上限**：MAX_INDEX_CACHE_SIZE=70KB 约束 Seek 索引缓存内存占用，防止大文件导致内存爆炸
5. **可中断 ReadAt**：DemuxerDataReader 支持中断回调，Seek 时立即取消正在进行的 I/O 操作
6. **双条件变量**：BlockQueue 分别用 condPush_ 和 condPop_ 避免 spurious wakeup 导致的死锁

## 与 S90 的区分

S90 聚焦 DemuxerDataReader + AvcParserImpl + DemuxerBitReader 三组件；S111 扩展为六个组件，增加了 ReferenceParserManager、MultiStreamParserManager、TimeRangeManager 和 Converter，提供了更完整的 Demuxer 公共工具链视图。
