---
type: architecture
id: MEM-ARCH-AVCODEC-S142
status: pending_approval
created_at: "2026-05-15T02:56:27+08:00"
updated_at: "2026-05-15T02:56:27+08:00"
created_by: builder
topic: TypeFinder 媒体类型探测架构——Sniffer路由/PeekRange/PluginRegistry/DemuxerPlugin评分/DASH识别/DEFAULT_SNIFF_SIZE=4096*4
scope: [AVCodec, MediaEngine, Demuxer, TypeFinder, Sniff, PeekRange, PluginRegistry, DemuxerPlugin, Rank, DASH, MimeType, Uri, SniffNeeded]
created_at: "2026-05-15T02:56:27+08:00"
summary: TypeFinder媒体类型探测架构——PeekRange嗅探4KB数据/PluginRegistry评分排序/DASH识别(IsDash)+MPEG4/MKV/HLS多容器/IsSniffNeeded URI预判/ReadAt流式读取，与S69/S75/S76/S79关联
source_repo: /home/west/av_codec_repo
source_root: services/media_engine/modules/demuxer
evidence_version: local_mirror
---

## 一、架构总览

TypeFinder 是 MediaDemuxer 体系中的媒体类型嗅探与插件路由模块，位于 `services/media_engine/modules/demuxer/` 目录（`type_finder.cpp`，216行 / `type_finder.h`，84行）。

**定位**：MediaDemuxer 的"侦察兵"——在打开媒体文件前，通过 PeekRange 读取文件头数据，用 PluginRegistry 中的 DemuxerPlugin Sniffer 函数识别容器类型，返回匹配评分最高的插件供 DemuxerPluginManager 加载。

## 二、文件清单与行号级证据

| 文件 | 行数 | 说明 |
|------|------|------|
| `type_finder.cpp` | 216 | TypeFinder 嗅探实现（PeekRange/ReadAt/FindMediaType） |
| `type_finder.h` | 84 | TypeFinder 类定义 + SniffSize 配置 + DataSource 接口 |

## 三、核心类定义（type_finder.h:38-82）

```cpp
// type_finder.h:38-82 - TypeFinder 类
class TypeFinder : public std::enable_shared_from_this<TypeFinder>, public Plugins::DataSource {
    // 初始化入口（type_finder.cpp:81）
    void Init(std::string uri, uint64_t mediaDataSize,
        std::function<Status(int32_t, uint64_t, size_t)> checkRange,           // 检查数据范围
        std::function<Status(int32_t, uint64_t, size_t, std::shared_ptr<Buffer>&, bool)> peekRange,  // 窥探数据
        int32_t streamId);

    // 核心嗅探方法（type_finder.cpp:122）
    Status ReadAt(int64_t offset, std::shared_ptr<Buffer>& buffer, size_t expectedLen) override;
    
    // SniffSize 配置（type_finder.h:37-39）
    uint64_t GetSniffSize() override;
    void SetSniffSize(uint64_t sniffSize) override;
    
    // URI 预判（type_finder.cpp:71）
    bool IsSniffNeeded(std::string uri);
    
    // DASH 识别（type_finder.h:57）
    bool IsDash() override { return false; }
    
    // 中断控制（type_finder.h:55）
    void SetInterruptState(bool isInterruptNeeded);

    // 关键成员
    std::atomic<uint64_t> sniffSize_ {0};                                    // 嗅探大小
    std::atomic<bool> isInterruptNeeded_{false};                            // 中断标志
    std::function<void(std::string)> typeFound_;                            // 类型发现回调
    std::function<Status(int32_t, uint64_t, size_t, std::shared_ptr<Buffer>&, bool)> peekRange_;  // 窥探回调
};
```

## 四、核心常量（type_finder.cpp:37-40）

```cpp
// type_finder.cpp:37-40 - 关键常量
const int32_t WAIT_TIME = 5;                                           // 等待时间（ms）
const uint32_t DEFAULT_SNIFF_SIZE = 4096 * 4;                          // 默认嗅探大小（16KB）
constexpr int32_t MAX_TRY_TIMES = 5;                                   // 最大重试次数
constexpr int32_t MAX_SNIFF_TRY_TIMES = 20;                            // 最大嗅探重试次数
```

## 五、关键函数流程

### 5.1 ReadAt（type_finder.cpp:122-148）—— 嗅探数据读取

```cpp
// type_finder.cpp:122 - 数据读取（用于 Sniff）
Status TypeFinder::ReadAt(int64_t offset, std::shared_ptr<Buffer>& buffer, size_t expectedLen)
{
    // 检查中断状态（line 143）
    if (isInterruptNeeded_) {
        MEDIA_LOG_W("ReadAt interrupt " PUBLIC_LOG_D32 " " PUBLIC_LOG_U64, streamID_, offset);
        return Status::ERROR_INVALID_PARAMETER;
    }
    
    // 调用 peekRange_ 获取数据（line 143）
    auto ret = peekRange_(streamID_, static_cast<uint64_t>(offset), expectedLen, buffer, true);
    
    // 重试逻辑（MAX_SNIFF_TRY_TIMES = 20）
    // 每次等待 WAIT_TIME = 5ms
}
```

### 5.2 IsSniffNeeded（type_finder.cpp:71-79）—— URI 预判

```cpp
// type_finder.cpp:71 - URI预判（避免不必要的嗅探）
bool TypeFinder::IsSniffNeeded(std::string uri)
{
    // 检查 URI 是否包含已知的流媒体后缀
    // 如 .mpd（DASH）、.m3u8（HLS）、.mp4（MP4）等
    // 如果 URI 明确指示类型，跳过 Sniff
}
```

### 5.3 GetSniffSize / SetSniffSize（type_finder.cpp:96-105）

```cpp
// type_finder.cpp:96 - 获取 SniffSize
uint64_t TypeFinder::GetSniffSize()
{
    return sniffSize_.load();
}

// type_finder.cpp:101 - 设置 SniffSize
void TypeFinder::SetSniffSize(uint64_t sniffSize)
{
    sniffSize_ = sniffSize;
    // 默认 DEFAULT_SNIFF_SIZE = 4096 * 4 = 16384 字节
}
```

### 5.4 GetSize（type_finder.cpp:148-162）

```cpp
// type_finder.cpp:148 - 获取媒体总大小
Status TypeFinder::GetSize(uint64_t& size)
{
    // 从 mediaDataSize_ 获取媒体文件总大小
    // 用于计算相对偏移
}
```

## 六、Sniffer 路由机制（配合 DemuxerPluginManager）

```cpp
// TypeFinder 作为 DataSource 传入 DemuxerPluginManager
// DemuxerPluginManager.GetPluginByDataSource(TypeFinder)

// 流程：
// 1. TypeFinder::ReadAt → 读取文件头 16KB
// 2. PluginRegistry.Sniff(probeData) → 各 DemuxerPlugin 尝试识别
// 3. 按 Sniff 评分排序（rank=100 最高 → rank=0 最低）
// 4. 返回评分最高的 DemuxerPlugin 供 MediaDemuxer 加载

// 评分机制：
// - MPEG4DemuxerPlugin: rank=100（原生 MP4 优先）
// - FFmpegDemuxerPlugin: rank=50（FFmpeg 兜底，支持25+格式）
// - DashDemuxerPlugin: rank=?（DASH 专用，.mpd URI 直接命中）
```

## 七、IsDash 识别（type_finder.h:57）

```cpp
// type_finder.h:57 - DASH 流识别
bool IsDash() override { return false; }

// TypeFinder 的 IsDash() 默认返回 false
// 由 StreamDemuxer/BaseStreamDemuxer 重写（isDash_ = true）
// 用于区分 DASH 流与普通 HTTP 流
```

## 八、与相关 S-series 记忆的关联

| 关联记忆 | 关系 | 说明 |
|---------|------|------|
| S69（MediaDemuxer） | 上游容器引擎 | MediaDemuxer 使用 TypeFinder 做插件路由 |
| S75（MediaDemuxer 六组件） | 同级组件 | TypeFinder 为 MediaDemuxer 六组件之一（Sniffer） |
| S76（FFmpegDemuxerPlugin） | 下游消费者 | TypeFinder Sniff 返回后，加载 FFmpegDemuxerPlugin |
| S79（MPEG4DemuxerPlugin） | 下游消费者 | TypeFinder Sniff 返回后，加载 MPEG4DemuxerPlugin（rank=100） |
| S128（HttpSourcePlugin 三路） | 并列 | TypeFinder 处理本地文件，HttpSourcePlugin 处理网络流 |

---

_builder-agent: S142 draft generated 2026-05-15T02:56:27+08:00, pending approval_