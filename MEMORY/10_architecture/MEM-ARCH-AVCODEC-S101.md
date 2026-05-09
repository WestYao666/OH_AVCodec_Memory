# MEM-ARCH-AVCODEC-S101: StreamDemuxer 流式解封装器——DASH/HLS分片缓存读取与PullData三路分发机制

## Status

```yaml
status: approved
approved_at: "2026-05-09T21:02:00+08:00"
created: 2026-05-08T23:20
builder: builder-agent
source: https://gitcode.com/openharmony/multimedia_av_codec
local_mirror: /home/west/av_codec_repo/services/media_engine/modules/demuxer/
```

## Evidence

| 文件 | 行数 | 说明 |
|------|------|------|
| `stream_demuxer.h` | 492行 | StreamDemuxer 类定义，继承 BaseStreamDemuxer |
| `stream_demuxer.cpp` | ~600行 | PullData/ReadRetry/CallbackReadAt 核心实现 |
| `base_stream_demuxer.h` | （引用） | 基类定义 |

## 核心发现

### 1. StreamDemuxer 类定位与继承

位置：`stream_demuxer.h:34-92`

```cpp
class StreamDemuxer : public BaseStreamDemuxer {
public:
    explicit StreamDemuxer();
    ~StreamDemuxer() override;
    Status Init(const std::string& uri) override;
    Status Pause() override;
    Status Resume() override;
    Status Start() override;
    Status Stop() override;
    Status Flush() override;
    Status CallbackReadAt(int32_t streamID, int64_t offset, std::shared_ptr<Buffer>& buffer,
        size_t expectedLen) override;
    Status ResetCache(int32_t streamID) override;
    Status ResetAllCache() override;
    int64_t GetFirstFrameDecapsulationTime() override;
};
```

**与已有 S-series 的关系**：
- S69/S75：MediaDemuxer 核心引擎（ReadLoop/SampleConsumerLoop 双 TaskThread）
- S97：DemuxerPluginManager 轨道路由（StreamID/TrackID/InnerTrackIndex 三层映射）
- **S101（本文档）**：StreamDemuxer 数据拉取层（PullData/缓存/重试/分片合并）

三层协作：`DemuxerFilter（S41） → MediaDemuxer（S69/S75） → StreamDemuxer（S101） → SourcePlugin（S37/S38）`

---

### 2. PullData 双缓存模式——WithCache vs WithoutCache

StreamDemuxer 支持两种数据拉取策略，通过 `IsDash()` 或 `GetIsDataSrcNoSeek()` 判断：

**带缓存路径**（`ReadFrameData`）：
```cpp
// stream_demuxer.cpp:59-73
Status StreamDemuxer::ReadFrameData(int32_t streamID, uint64_t offset, size_t size,
    std::shared_ptr<Buffer>& bufferPtr, bool isSniffCase)
{
    std::unique_lock<std::mutex> lock(cacheDataMutex_);
    if (IsDash() || GetIsDataSrcNoSeek()) {
        // DASH/HLS直播流：先查缓存
        if (cacheDataMap_.find(streamID) != cacheDataMap_[streamID].end() &&
            cacheDataMap_[streamID].CheckCacheExist(offset)) {
            return PullDataWithCache(streamID, offset, size, bufferPtr, isSniffCase);
        }
    }
    return PullData(streamID, offset, size, bufferPtr, isSniffCase);
}
```

**无缓存路径**（`ReadHeaderData`）：
```cpp
// stream_demuxer.cpp:75-88
Status StreamDemuxer::ReadHeaderData(int32_t streamID, uint64_t offset, size_t size,
    std::shared_ptr<Buffer>& bufferPtr, bool isSniffCase)
{
    // Header 解析直接走无缓存路径（无需合并）
    return PullDataWithoutCache(streamID, offset, size, bufferPtr, isSniffCase);
}
```

**关键区别**：
- `ReadFrameData`：用于帧解析，支持 DASH 缓存合并（`IsDash()` 时走缓存路径）
- `ReadHeaderData`：用于头部解析，直接拉取不合并（`ProcInnerDash` 仅在 DASH 场景下合并已缓存数据）

---

### 3. PullDataWithCache 缓存合并算法

位置：`stream_demuxer.cpp:138-178`

当命中缓存时，先从缓存读取可满足的部分，再从 Source 拉取剩余数据，最后合并为完整 Buffer：

```cpp
// 1. 从缓存读取满足部分
if (size <= memory->GetSize() - offsetInCache) {
    bufferPtr->GetMemory()->Write(memory->GetReadOnlyData() + offsetInCache, size, 0);
    return Status::OK;
}
// 2. 缓存不够，先读满缓存部分
bufferPtr->GetMemory()->Write(memory->GetReadOnlyData() + offsetInCache, memory->GetSize() - offsetInCache, 0);
uint64_t remainOffset = cacheDataMap_[streamID].GetOffset() + memory->GetSize();
uint64_t remainSize = size - (memory->GetSize() - offsetInCache);
// 3. 拉取剩余数据
Status ret = PullData(streamID, remainOffset, remainSize, tempBuffer, isSniffCase);
// 4. 合并到输出 buffer
bufferPtr->GetMemory()->Write(tempBuffer->GetMemory()->GetReadOnlyData(),
    tempBuffer->GetMemory()->GetSize(), memory->GetSize() - offsetInCache);
// 5. 若为帧解析模式，缓存已合并的数据
if (pluginStateMap_[streamID] != DemuxerState::DEMUXER_STATE_PARSE_FRAME) {
    mergedBuffer->GetMemory()->Write(cacheMemory->GetReadOnlyData(), cacheMemory->GetSize(), 0);
    mergedBuffer->GetMemory()->Write(bufferMemory->GetReadOnlyData(), bufferMemory->GetSize(), cacheMemory->GetSize());
    cacheDataMap_[streamID].SetData(mergedBuffer); // 更新缓存
}
```

---

### 4. ReadRetry 重试机制——TRY_READ_TIMES × TRY_READ_SLEEP_TIME

位置：`stream_demuxer.cpp:246-270`

当 Source 返回空数据时，StreamDemuxer 等待并重试（适用于网络流媒体慢速到达场景）：

```cpp
namespace {
const int32_t TRY_READ_SLEEP_TIME = 10;  // ms
const int32_t TRY_READ_TIMES = 10;
constexpr int64_t SOURCE_READ_WARNING_MS = 100;
}

Status StreamDemuxer::ReadRetry(int32_t streamID, uint64_t offset, size_t size,
    std::shared_ptr<Plugins::Buffer>& data, bool isSniffCase)
{
    Status err = Status::OK;
    int32_t retryTimes = 0;
    while (true && !isInterruptNeeded_.load()) {
        {
            ScopedTimer timer("Source Read", SOURCE_READ_WARNING_MS);
            err = source_->Read(streamID, data, offset, size);
        }
        // ERROR_AGAIN：非阻塞模式下数据未就绪，直接返回
        if (err == Status::ERROR_AGAIN && !isSniffCase) {
            return err;
        }
        // 空数据：等待重试
        if (err != Status::END_OF_STREAM && data->GetMemory()->GetSize() == 0) {
            std::unique_lock<std::mutex> lock(mutex_);
            readCond_.wait_for(lock, std::chrono::milliseconds(TRY_READ_SLEEP_TIME),
                               [&] { return isInterruptNeeded_.load(); });
            retryTimes++;
            if (retryTimes > TRY_READ_TIMES || isInterruptNeeded_.load()) {
                break;
            }
            continue;
        }
        break;
    }
    return err;
}
```

**关键参数**：
- `TRY_READ_TIMES=10`：最多重试 10 次
- `TRY_READ_SLEEP_TIME=10ms`：每次等待 10ms
- `SOURCE_READ_WARNING_MS=100`：读操作超过 100ms 打 HiLog 警告
- `ERROR_AGAIN`：非阻塞模式立即返回，不等待

---

### 5. PullData Seekable/UNSEEKABLE 双路径

位置：`stream_demuxer.cpp:271-310`

```cpp
Status StreamDemuxer::PullData(int32_t streamID, uint64_t offset, size_t size,
    std::shared_ptr<Plugins::Buffer>& data, bool isSniffCase)
{
    if (!source_) {
        return Status::ERROR_INVALID_OPERATION;
    }
    // 路径1：支持 SeekToTime 或 UNSEEKABLE 流（HLS/直播），直接读
    if (source_->IsSeekToTimeSupported() || source_->GetSeekable() == Plugins::Seekable::UNSEEKABLE) {
        return ReadRetry(streamID, offset, readSize, data, isSniffCase);
    }
    // 路径2：SEEKABLE 文件，先 Seek 再读
    uint64_t totalSize = 0;
    if ((source_->GetSize(totalSize) == Status::OK) && (totalSize != 0)) {
        if (offset >= totalSize) {
            return Status::END_OF_STREAM;
        }
        if ((offset + readSize) > totalSize) {
            readSize = totalSize - offset;
        }
    }
    if (position_ != offset || GetIsDataSrc()) {
        err = source_->SeekTo(offset);   // ← 显式 Seek
        position_ = offset;
    }
    err = ReadRetry(streamID, offset, readSize, data, isSniffCase);
    if (err == Status::OK) {
        position_ += data->GetMemory()->GetSize(); // 更新位置
    }
    return err;
}
```

**双路径对比**：
| 场景 | 行为 | 说明 |
|------|------|------|
| UNSEEKABLE（HLS/直播） | 直接 ReadRetry，不 Seek | 流式读取，不支持倒拽 |
| SEEKABLE（本地文件） | 先 SeekTo 再 ReadRetry | position_ 跟踪当前位置 |
| IsSeekToTimeSupported | 直接读，忽略 offset | 插件自己管理时间轴 |

---

### 6. CallbackReadAt 状态机路由——HEADER vs FRAME

位置：`stream_demuxer.cpp:385-410`

```cpp
Status StreamDemuxer::CallbackReadAt(int32_t streamID, int64_t offset, std::shared_ptr<Buffer>& buffer,
    size_t expectedLen)
{
    FALSE_RETURN_V(!isInterruptNeeded_.load(), Status::ERROR_WRONG_STATE);
    switch (pluginStateMap_[streamID]) {
        case DemuxerState::DEMUXER_STATE_NULL:
            return Status::ERROR_WRONG_STATE;
        case DemuxerState::DEMUXER_STATE_PARSE_HEADER: {
            auto ret = HandleReadHeader(streamID, offset, buffer, expectedLen);
            // HandleReadHeader → getRange_(ReadHeaderData → PullDataWithoutCache)
            break;
        }
        case DemuxerState::DEMUXER_STATE_PARSE_FIRST_FRAME:
        case DemuxerState::DEMUXER_STATE_PARSE_FRAME: {
            auto ret = HandleReadPacket(streamID, offset, buffer, expectedLen);
            // HandleReadPacket → getRange_(ReadFrameData → PullDataWithCache)
            break;
        }
        default:
            return Status::ERROR_WRONG_STATE;
    }
    return CheckChangeStreamID(streamID, buffer);
}
```

**状态转换**：NULL → PARSE_HEADER → PARSE_FIRST_FRAME → PARSE_FRAME

---

### 7. DASH Track 切换——CheckChangeStreamID

位置：`stream_demuxer.cpp:357-377`

在 DASH 自适应码率切换时，StreamDemuxer 检测到 streamID 变化并更新三路 Track 映射：

```cpp
Status StreamDemuxer::CheckChangeStreamID(int32_t streamID, std::shared_ptr<Buffer>& buffer)
{
    if (IsDash()) {
        if (buffer != nullptr && buffer->streamID != streamID) {
            if (GetNewVideoStreamID() == streamID) {
                SetNewVideoStreamID(buffer->streamID);   // 视频轨切换
            } else if (GetNewAudioStreamID() == streamID) {
                SetNewAudioStreamID(buffer->streamID);    // 音频轨切换
            } else if (GetNewSubtitleStreamID() == streamID) {
                SetNewSubtitleStreamID(buffer->streamID);  // 字幕轨切换
            }
            MEDIA_LOG_I("Demuxer parse dash change, oldStreamID = %d, newStreamID = %d",
                streamID, buffer->streamID);
            return Status::END_OF_STREAM; // 返回 EOS，触发上游切换
        }
    }
    return Status::OK;
}
```

---

### 8. ProcInnerDash 分片缓存合并

位置：`stream_demuxer.cpp:178-195`

DASH 场景下，前一个分片数据会缓存并与新分片合并：

```cpp
Status StreamDemuxer::ProcInnerDash(int32_t streamID, uint64_t offset,
    std::shared_ptr<Buffer>& bufferPtr)
{
    if (IsDash()) {
        // 合并前一个分片缓存 + 当前分片数据
        std::shared_ptr<Buffer> mergedBuffer = Buffer::CreateDefaultBuffer(
            bufferMemory->GetSize() + cacheMemory->GetSize());
        mergeMemory->Write(cacheMemory->GetReadOnlyData(), cacheMemory->GetSize(), 0);
        mergeMemory->Write(bufferMemory->GetReadOnlyData(), bufferMemory->GetSize(),
            cacheMemory->GetSize());
        cacheDataMap_[streamID].SetData(mergedBuffer);
    }
    return Status::OK;
}
```

---

### 9. 关键常量与数据结构

**缓存控制**：
- `cacheDataMap_：std::map<int32_t, CacheData>` — 每路 streamID 一个缓存
- `position_：uint64_t` — SEEKABLE 文件当前位置跟踪
- `firstFrameDecapsulationTime_：int64_t` — 首帧解封装时间（PTS 基准）

**重试策略**：
- `TRY_READ_TIMES = 10`：最多重试 10 次
- `TRY_READ_SLEEP_TIME = 10ms`：每次等待 10ms
- `SOURCE_READ_WARNING_MS = 100`：读操作超过 100ms 打警告日志

**缓存合并条件**：
- 仅 `IsDash()` 场景下执行 `ProcInnerDash` 合并
- Header 解析模式不合并（`DEMUXER_STATE_PARSE_HEADER`）
- Frame 解析模式合并（`DEMUXER_STATE_PARSE_FRAME`）

## 关联记忆

- **S69/S75**（MediaDemuxer）：StreamDemuxer 是 MediaDemuxer 的数据供给层
- **S97**（DemuxerPluginManager）：StreamDemuxer 通过 DemuxerPluginManager 创建和管理
- **S37/S38**（SourcePlugin）：StreamDemuxer 最终调用 SourcePlugin 的 Read/Seek 接口
- **S41**（DemuxerFilter）：StreamDemuxer 数据通过 Filter Pipeline 传递给下游 Filter
- **S68/S76/S79**（DemuxerPlugin）：FFmpeg/MPEG4 DemuxerPlugin 依赖 StreamDemuxer 拉取数据

## Scope

AVCodec, MediaEngine, Demuxer, StreamDemuxer, DASH, HLS, Cache, PullData, ReadRetry, AdaptiveBitrate, TrackSwitch
