# MEM-ARCH-AVCODEC-S66 — TypeFinder 媒体类型探测框架

| 字段 | 值 |
|------|-----|
| mem_id | MEM-ARCH-AVCODEC-S66 |
| title | TypeFinder 媒体类型探测框架——SnifferPlugin 路由与 BaseStreamDemuxer 集成 |
| scope | AVCodec, MediaEngine, Demuxer, Sniff, Plugin, TypeFinder, DataSource, StreamDemuxer |
| created_by | builder-agent |
| created_at | 2026-04-27T07:52:00+08:00 |
| backlog_section | 新增主题（Builder 2026-04-27 S66注册） |
---
status: draft
approved_at: "2026-05-06"
---


| draft_path | MEMORY/10_architecture/MEM-ARCH-AVCODEC-S66.md |

---

## 1. 架构定位

TypeFinder是**媒体类型自动探测模块**，位于解封装管线最前端：

```
DataSource (HTTP/FILE/FD)
    ↓
TypeFinder::FindMediaType()  ← 媒体类型探测（SnifferPlugin路由）
    ↓
DemuxerPlugin (found by SnifferPlugin)
    ↓
MediaDemuxer / StreamDemuxer  ← 实际解封装
```

TypeFinder本身继承`std::enable_shared_from_this`（支持`shared_from_this()`）和`Plugins::DataSource`（数据源接口），是DemuxerPlugin数据源与探测框架的桥梁。

---

## 2. 类定义与核心成员

### 2.1 TypeFinder 类（type_finder.h:20-84 + type_finder.cpp:226行）

```cpp
// type_finder.h:20
class TypeFinder : public std::enable_shared_from_this<TypeFinder>, 
                   public Plugins::DataSource {
public:
    TypeFinder();
    ~TypeFinder() override;

    void Init(std::string uri, uint64_t mediaDataSize,
              std::function<Status(int32_t, uint64_t, size_t)> checkRange,
              std::function<Status(int32_t, uint64_t, size_t, 
                                   std::shared_ptr<Buffer>&, bool)> peekRange,
              int32_t streamId);

    std::string FindMediaType();      // 同步入口
    uint64_t GetSniffSize() override;
    void SetSniffSize(uint64_t sniffSize) override;
    Status ReadAt(...) override;      // DataSource接口
    Status GetSize(uint64_t& size) override;
    Plugins::Seekable GetSeekable() override;
    int32_t GetStreamID() override;
    void SetInterruptState(bool isInterruptNeeded);

    bool IsDash() override { return false; }

private:
    std::string SniffMediaType();    // 探测实现
    bool IsOffsetValid(int64_t offset) const;
    bool IsSniffNeeded(std::string uri);

    bool sniffNeeded_;                // 是否需要探测
    std::string uri_;                 // 媒体URI
    uint64_t mediaDataSize_;          // 数据总大小
    std::string pluginName_;          // 探测到的插件名
    std::atomic<bool> pluginRegistryChanged_;  // 插件注册表变更标志
    std::shared_ptr<Task> task_;      // 异步任务
    std::function<...> checkRange_;  // 范围检查回调
    std::function<...> peekRange_;    // 数据读取回调
    std::function<void(std::string)> typeFound_;  // 类型发现回调
    int32_t streamID_ = -1;
    std::atomic<uint64_t> sniffSize_ {0};
    std::mutex mutex_;
    std::condition_variable readCond_;
    std::atomic<bool> isInterruptNeeded_{false};
};
```

### 2.2 核心常量

```cpp
// type_finder.cpp:28-32
const int32_t WAIT_TIME = 5;                      // 条件变量等待时间(ms)
const uint32_t DEFAULT_SNIFF_SIZE = 4096 * 4;      // 默认探测数据量 16KB
constexpr int32_t MAX_TRY_TIMES = 5;              // ReadAt重试次数
constexpr int32_t MAX_SNIFF_TRY_TIMES = 20;       // 探测循环最大尝试次数
```

---

## 3. FindMediaType() 入口流程

### 3.1 同步入口（type_finder.cpp:96-107）

```cpp
std::string TypeFinder::FindMediaType()
{
    MediaAVCodec::AVCodecTrace trace("TypeFinder::FindMediaType");
    if (sniffNeeded_) {
        pluginName_ = SniffMediaType();   // 实际探测
        if (!pluginName_.empty()) {
            sniffNeeded_ = false;         // 缓存结果
        }
    }
    return pluginName_;   // 返回找到的Demuxer插件名
}
```

**设计要点**：
- 同步接口，直接返回插件名
- 首次探测后缓存`pluginName_`，后续直接返回（短路逻辑）
- `sniffNeeded_`标志控制是否跳过缓存

### 3.2 Init() 参数注入（type_finder.cpp:66-77）

```cpp
void TypeFinder::Init(std::string uri, uint64_t mediaDataSize,
    std::function<Status(int32_t, uint64_t, size_t)> checkRange,
    std::function<Status(int32_t uint64_t, size_t, 
                         std::shared_ptr<Buffer>&, bool)> peekRange,
    int32_t streamId)
{
    streamID_ = streamId;
    mediaDataSize_ = mediaDataSize;
    checkRange_ = std::move(checkRange);
    peekRange_ = std::move(peekRange);
    sniffNeeded_ = IsSniffNeeded(uri);   // URI变化→重新探测
    if (sniffNeeded_) {
        uri_.swap(uri);
        pluginName_.clear();
    }
}
```

**设计要点**：
- `checkRange_`：检查指定偏移数据是否可用（用于ReadAt重试）
- `peekRange_`：从DataSource读取实际数据
- URI变化触发重新探测（`IsSniffNeeded`）

---

## 4. SniffMediaType() 探测核心

### 4.1 探测流程（type_finder.cpp:161-214）

```cpp
std::string TypeFinder::SniffMediaType()
{
    std::string pluginName;
    auto dataSource = shared_from_this();   // 自身作为DataSource
    std::vector<uint8_t> buff(DEFAULT_SNIFF_SIZE);  // 16KB缓冲区
    auto buffer = std::make_shared<Buffer>();
    
    // 计算实际探测大小
    size_t expectSize = DEFAULT_SNIFF_SIZE;
    uint64_t totalSize = 0;
    if (dataSource->GetSize(totalSize) == Status::OK && 
        totalSize > 0 && totalSize < DEFAULT_SNIFF_SIZE) {
        expectSize = static_cast<size_t>(totalSize);
    }

    // 循环读取数据（处理数据源ERROR_AGAIN情况）
    int32_t tryCnt = 0;
    while (tryCnt < MAX_SNIFF_TRY_TIMES) {
        auto memory = buffer->GetMemory();
        memory->Reset();
        ret = dataSource->ReadAt(0, buffer, expectSize);
        getDataSize = memory->GetSize();
        if (ret == Status::OK && getDataSize == expectSize) {
            break;   // 成功读取
        }
        // ... ERROR_AGAIN处理：等待WAIT_TIME后重试
        ++tryCnt;
    }
    
    FALSE_RETURN_V_MSG_E(ret == Status::OK && getDataSize > 0, "", 
        "Not data for sniff");
    
    // 核心：调用PluginManagerV2的SnifferPlugin
    pluginName = Plugins::PluginManagerV2::Instance()
        .SnifferPlugin(PluginType::DEMUXER, dataSource);
    return pluginName;
}
```

### 4.2 SnifferPlugin 路由机制

```cpp
// type_finder.cpp:213
pluginName = Plugins::PluginManagerV2::Instance()
    .SnifferPlugin(PluginType::DEMUXER, dataSource);
```

`PluginManagerV2::SnifferPlugin()`遍历所有已注册的Demuxer插件，逐个调用各插件的Sniffer函数，传入dataSource和16KB样本数据，由插件判断是否支持该媒体类型。

---

## 5. ReadAt() 重试与中断机制

### 5.1 ReadAt() 实现（type_finder.cpp:110-130）

```cpp
Status TypeFinder::ReadAt(int64_t offset, std::shared_ptr<Buffer>& buffer, 
                           size_t expectedLen)
{
    if (!buffer || expectedLen == 0 || !IsOffsetValid(offset)) {
        return Status::ERROR_INVALID_PARAMETER;
    }

    // 带重试的读取循环
    int i = 0;
    while ((checkRange_(streamID_, offset, expectedLen) != Status::OK) &&
           (i < MAX_TRY_TIMES) && !isInterruptNeeded_.load()) {
        i++;
        std::unique_lock<std::mutex> lock(mutex_);
        readCond_.wait_for(lock, std::chrono::milliseconds(WAIT_TIME),
                          [&] { return isInterruptNeeded_.load(); });
    }
    
    FALSE_RETURN_V_MSG_E(!isInterruptNeeded_.load(), Status::ERROR_WRONG_STATE,
        "ReadAt interrupt");
        
    if (i == MAX_TRY_TIMES) {
        return Status::ERROR_NOT_ENOUGH_DATA;
    }
    
    auto ret = peekRange_(streamID_, static_cast<uint64_t>(offset), 
                          expectedLen, buffer, true);
    FALSE_RETURN_V_MSG_E(ret == Status::OK, ret, "PeekRange failed");
    return ret;
}
```

**设计要点**：
- `checkRange_`先验证数据可用性（避免读到不完整数据）
- 重试机制最多5次，每次等待5ms
- `isInterruptNeeded_`原子标志支持外部中断（`SetInterruptState`）
- 返回`ERROR_WRONG_STATE`表示被中断

---

## 6. BaseStreamDemuxer 集成

### 6.1 typeFinder_ 成员（base_stream_demuxer.h:104-143）

```cpp
// base_stream_demuxer.h
class BaseStreamDemuxer {
public:
    void InitTypeFinder();
    void SetSource(const std::shared_ptr<Source>& source);
    virtual std::string SnifferMediaType(const StreamInfo& streamInfo);
    virtual void SetInterruptState(bool isInterruptNeeded);

protected:
    std::shared_ptr<TypeFinder> typeFinder_;   // h:134 关键成员
    std::function<...> checkRange_;
    std::function<...> peekRange_;
    std::function<...> getRange_;
    std::atomic<bool> isInterruptNeeded_{false};

private:
    bool isDash_ = {false};
    SourceType sourceType_ = {SourceType::SOURCE_TYPE_FD};
    std::atomic<int32_t> newVideoStreamID_ = -1;
    std::atomic<int32_t> newAudioStreamID_ = -1;
    std::atomic<int32_t> newSubtitleStreamID_ = -1;
};
```

### 6.2 InitTypeFinder()（base_stream_demuxer.cpp:82）

```cpp
// base_stream_demuxer.cpp:82
void BaseStreamDemuxer::InitTypeFinder()
{
    typeFinder_ = std::make_shared<TypeFinder>();   // 创建TypeFinder实例
    // ... 初始化DataSource回调链
}
```

TypeFinder的`checkRange_`/`peekRange_`回调由BaseStreamDemuxer在InitTypeFinder()时注入，数据实际来源于Source层。

---

## 7. DataSource 接口实现

TypeFinder实现`Plugins::DataSource`接口，使其可作为媒体数据源传递给SnifferPlugin：

| 接口方法 | 功能 |
|---------|------|
| `GetSize()` | 返回`mediaDataSize_` |
| `GetSeekable()` | 返回`Seekable::INVALID`（TypeFinder不关心seekability） |
| `ReadAt()` | 带重试的数据读取，带中断支持 |
| `IsDash()` | 返回`false` |

---

## 8. 中断机制

### 8.1 SetInterruptState()（type_finder.cpp:216-222）

```cpp
void TypeFinder::SetInterruptState(bool isInterruptNeeded)
{
    MEDIA_LOG_I("TypeFinder OnInterrupted %{public}d", isInterruptNeeded);
    std::unique_lock<std::mutex> lock(mutex_);
    isInterruptNeeded_ = isInterruptNeeded;
    readCond_.notify_all();   // 唤醒所有等待的ReadAt
}
```

### 8.2 TypeFinderInterrupt()（base_stream_demuxer.cpp:113-116）

```cpp
void BaseStreamDemuxer::TypeFinderInterrupt(bool isInterruptNeeded)
{
    if (typeFinder_) {
        typeFinder_->SetInterruptState(isInterruptNeeded);
    }
}
```

上层通过`SetInterruptState`向TypeFinder发送中断信号，唤醒等待中的ReadAt线程，实现Seek/Stop时的快速响应。

---

## 9. 关键设计总结

| 设计要点 | 实现 |
|---------|------|
| 媒体类型探测 | PluginManagerV2::SnifferPlugin遍历所有Demuxer插件 |
| 探测数据量 | 默认16KB，数据源不足时取实际大小 |
| 重试逻辑 | ReadAt最多5次重试，每次等待5ms，处理ERROR_AGAIN |
| 中断机制 | condition_variable + atomic isInterruptNeeded_ |
| 缓存策略 | 首次探测后pluginName_缓存，URI变化才重新探测 |
| 双继承 | enable_shared_from_this（创建shared_ptr）+ DataSource（数据源接口） |
| 错误处理 | ERROR_NOT_ENOUGH_DATA（重试超限）/ ERROR_WRONG_STATE（中断） |

---

## 10. 关联关系

| 关联模块 | 关系 |
|---------|------|
| S41 DemuxerFilter | 上游Consumer，DemuxerFilter持有MediaDemuxer |
| S58 MPEG4BoxParser | 互补：TypeFinder探测媒体类型，MPEG4BoxParser解析Box结构 |
| S38 SourcePlugin | 底层数据源，TypeFinder通过Source读取探测数据 |
| S40 FFmpegMuxerPlugin | 互补：TypeFinder管解封装前的探测，FFmpegMuxerPlugin管封装 |
| S37 HTTP流媒体源 | HTTP数据通过TypeFinder探测媒体类型后路由到对应DemuxerPlugin |

---

## 11. Evidence 清单

| # | 证据 | 文件位置 |
|---|------|---------|
| 1 | TypeFinder类定义（双继承） | type_finder.h:20 |
| 2 | DEFAULT_SNIFF_SIZE=16KB常量 | type_finder.cpp:30 |
| 3 | MAX_TRY_TIMES=5 / MAX_SNIFF_TRY_TIMES=20常量 | type_finder.cpp:31-32 |
| 4 | FindMediaType()同步入口 | type_finder.cpp:96-107 |
| 5 | SniffMediaType()探测实现 | type_finder.cpp:161-214 |
| 6 | SnifferPlugin路由调用 | type_finder.cpp:213 |
| 7 | ReadAt()重试+condition_variable | type_finder.cpp:110-130 |
| 8 | SetInterruptState()中断机制 | type_finder.cpp:216-222 |
| 9 | TypeFinder::Init()参数注入 | type_finder.cpp:66-77 |
| 10 | BaseStreamDemuxer持有typeFinder_ | base_stream_demuxer.h:134 |
| 11 | InitTypeFinder()初始化 | base_stream_demuxer.cpp:82 |
| 12 | TypeFinderInterrupt()代理中断 | base_stream_demuxer.cpp:113-116 |
| 13 | Plugins::DataSource接口继承 | type_finder.h:21 |
| 14 | enable_shared_from_this继承 | type_finder.h:20 |
| 15 | PluginManagerV2::SnifferPlugin声明 | interfaces/plugin/plugin_manager_v2.h |
