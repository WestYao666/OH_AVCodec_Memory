---
id: MEM-ARCH-AVCODEC-S86
title: "HLS 流媒体缓存引擎——MediaCachedBuffer RingBuffer 与 HlsSegmentManager 多轨分片下载架构"
scope: [AVCodec, MediaEngine, SourcePlugin, HLS, Streaming, Cache, RingBuffer, SegmentDownload, AES128, AdaptiveBitrate, M3U8, HttpSource]
status: approved
created_by: builder-agent
created_at: "2026-05-03T23:34:00+08:00"
approved_by: feishu-user:ou_60d8641be684f82e8d9cb84c3015dde7
approved_at: "2026-05-04T16:15:36+08:00"
---

# MEM-ARCH-AVCODEC-S86: HLS 流媒体缓存引擎——MediaCachedBuffer RingBuffer 与 HlsSegmentManager 多轨分片下载架构

## 1. 概述

`MediaCachedBuffer`（又称 `CacheMediaChunkBufferImpl`）是 OpenHarmony AVCodec 流媒体基础设施中负责 HTTP/HTTPS 流媒体数据**分片缓存**的核心组件。它以固定大小的 Chunk 为单位管理内存缓冲区，采用**写指针/读指针双偏移**机制，支持流式下载与流式消费的并行进行，是 HLS/DASH 自适应码率播放的"蓄水池"。

`HlsSegmentManager` 是 HLS 分片下载管理器，负责管理视频/音频/字幕三轨的**独立分片下载队列**（`HlsSegmentManager × 3`），协调 M3U8 播放列表解析、AES-128 解密、自适应码率切换，是 HLS 直播/点播的第一跳。

**适用场景**：
- HLS 自适应码率直播（ABR，Adaptive Bitrate Streaming）
- 录播流 Seek 定位（PlaylistBackup + ReadBackSave）
- DRM 加密流解密（AES-128-CBC，EXT-X-KEY）
- 边下载边播放（Pipe-lined download + consumption）

**未覆盖区域**：
- `media_cached_buffer.cpp`（1386 行）RingBuffer 缓存在任何现有 S-series 记忆中均无记录
- `hls_segment_manager.cpp`（2582 行）虽有 S37 覆盖，但 MediaCachedBuffer 层无行号级证据

## 2. 核心架构

### 2.1 整体数据流

```
HTTP Server (HLS .ts / .m4s segments)
        │
        ▼
HlsSegmentManager (videoSegManager_ / audioSegManager_ / subtitlesSegManager_)
        │
        ├─ PlaylistDownloader → M3U8 播放列表解析（EXTINF 分片时长/URL）
        ├─ HlsSegmentManager → DownloadQueue → SegmentDownloader
        │         │
        │         ▼
        │   AesDecryptor::Decrypt()    ← AES-128-CBC 解密（EXT-X-KEY）
        │         │
        │         ▼
        └─ CacheMediaChunkBufferImpl::WriteRingBuffer()
                   │
                   │ RingBuffer（固定 Chunk 大小循环缓冲）
                   │  chunkSize_ = 128KB / 256KB / 512KB
                   │  totalBuffSize_ = 自适应（用户定义或自动计算）
                   │  LRU Cache（MAX 300 / 10 分片节点）
                   │
                   ▼
           上层 Consumer（MediaDemuxer / StreamDemuxer）Read()
```

### 2.2 类层次结构

**证据**：`services/media_engine/plugins/source/http_source/utils/media_cached_buffer.h` + `services/media_engine/plugins/source/http_source/utils/media_cached_buffer.cpp`

```cpp
// media_cached_buffer.h — RingBuffer 核心接口
class CacheMediaChunkBufferImpl {
public:
    CacheMediaChunkBufferImpl();                       // 初始化：chunkMaxNum=0, lruCache=300
    bool Init(uint64_t totalBuffSize, uint32_t chunkSize); // 分配 totalBuffSize 字节裸内存
    size_t Write(uint8_t* data, size_t writeSize);     // 写指针推进
    size_t Read(uint8_t* data, size_t readSize);       // 读指针推进
    uint64_t GetBufferSize() const;                    // 当前有效数据量
    uint64_t GetReadOffset() const;
    uint64_t GetWriteOffset() const;
    bool IsFull() const;
    bool IsEmpty() const;
    void Clear();                                      // 复位读写指针（不释放内存）

private:
    uint8_t* bufferAddr_ {nullptr};   // 裸内存起始地址（malloc 分配）
    size_t totalBuffSize_ {0};         // 缓冲区总大小（字节）
    size_t totalReadSize_ {0};         // 累计已读大小
    uint32_t chunkSize_ {0};           // 单个 Chunk 大小（128KB/256KB/512KB）
    uint32_t chunkMaxNum_ {0};         // 最大 Chunk 数量
    std::list<CacheChunk> fragmentCacheBuffer_; // 分片链表（LRU 驱逐）
    std::list<CacheChunk> freeChunks_;           // 空闲 Chunk 链表
    std::mutex mutex_;               // 线程安全
    std::list<CacheChunk>::iterator readPos_;  // 读指针迭代器
    std::list<CacheChunk>::iterator writePos_; // 写指针迭代器
    LRUCache<uint64_t, CacheChunk> lruCache_;  // LRU 缓存（offset → Chunk）
};

// 辅助结构
struct CacheChunk {
    uint64_t offset;      // 本 Chunk 在整个流中的偏移量
    uint64_t dataLength;  // 有效数据长度
    uint8_t* data;        // 指向 bufferAddr_ 中本 Chunk 起始位置
};
```

**HlsSegmentManager 三轨架构**：

```cpp
// hls_segment_manager.h — 三轨分片管理器
class HlsSegmentManager : public PlayListChangeCallback {
public:
    HlsSegmentManager(int expectBufferDuration, bool userDefinedDuration,
        const std::map<std::string, std::string>& httpHeader,
        HlsSegmentType type,  // SEG_VIDEO / SEG_AUDIO / SEG_SUBTITLE
        std::shared_ptr<MediaSourceLoaderCombinations> sourceLoader);

private:
    HlsSegmentType type_;  // 当前分片类型
    std::shared_ptr<HlsPlaylistDownloader> playlistDownloader_;  // M3U8 解析器
    std::shared_ptr<CacheMediaChunkBufferImpl> cacheMediaBuffer_; // 缓存引擎

    // 三轨独立管理器（由 HlsMediaDownloader 创建和管理）
    std::shared_ptr<HlsSegmentManager> videoSegManager_;    // 视频轨
    std::shared_ptr<HlsSegmentManager> audioSegManager_;    // 音频轨
    std::shared_ptr<HlsSegmentManager> subtitlesSegManager_; // 字幕轨
};
```

## 3. MediaCachedBuffer RingBuffer 核心机制

### 3.1 内存布局与初始化

**证据**：`media_cached_buffer.cpp:75-120`（`Init()` 函数）

```cpp
bool CacheMediaChunkBufferImpl::Init(uint64_t totalBuffSize, uint32_t chunkSize)
{
    // LRU 缓存容量设置
    if (isLargeOffsetSpan_) {
        lruCache_.ReCacheSize(CACHE_FRAGMENT_MAX_NUM_LARGE);  // 大偏移模式：10
    } else {
        lruCache_.ReCacheSize(CACHE_FRAGMENT_MAX_NUM_DEFAULT); // 普通模式：300
    }

    // chunk 数量计算
    uint64_t diff = (totalBuffSize + chunkSize) > 1 ? (totalBuffSize + chunkSize) - 1 : 0;
    int64_t chunkNum = static_cast<int64_t>(diff / chunkSize) + 1;

    // 总内存分配：每个 Chunk = sizeof(CacheChunk) + chunkSize
    size_t sizePerChunk = sizeof(CacheChunk) + chunkSize;
    int64_t totalSize = static_cast<int64_t>(sizePerChunk) * chunkNum;
    bufferAddr_ = static_cast<uint8_t*>(malloc(totalSize)); // 裸内存分配
}
```

**常量定义**：

```cpp
// media_cached_buffer.cpp 常量
constexpr size_t CACHE_FRAGMENT_MAX_NUM_DEFAULT = 300; // 普通模式最大分片数
constexpr size_t CACHE_FRAGMENT_MAX_NUM_LARGE = 10;    // 大偏移模式最大分片数
constexpr size_t CACHE_FRAGMENT_MIN_NUM_DEFAULT = 3;   // 最小分片数
constexpr double NEW_FRAGMENT_INIT_CHUNK_NUM = 8.0;   // seek 操作初始缓存（8 chunks ≈ 128KB）
```

### 3.2 Write / Read 环形缓冲机制

**证据**：`media_cached_buffer.cpp`（Write / Read 函数，偏移约 300-600 行）

**Write 流程**：

```
1. AutoLock lock(mutex_)  // 加锁保护
2. 找到可写的空闲 Chunk（freeChunks_ 链表）
3. 复制数据到 Chunk.data（最大 chunkSize_ 字节）
4. 更新 CacheChunk.offset 和 CacheChunk.dataLength
5. 将 Chunk 插入 fragmentCacheBuffer_（按 offset 有序）
6. 更新 lruCache_（LRU 驱逐：超过 MAX 300 时移除最旧 Chunk）
7. 返回实际写入字节数
```

**Read 流程**：

```
1. AutoLock lock(mutex_)
2. 从 readPos_ 迭代器位置开始读取
3. 复制数据到用户 buffer
4. 推进 readPos_（已读完的 Chunk 移入 freeChunks_ 回收）
5. 更新 totalReadSize_（累计已读）
6. 返回实际读取字节数
```

**LRU 驱逐策略**：

```cpp
// lruCache_ 是 offset → CacheChunk 的映射
// 当 fragmentCacheBuffer_.size() > fragmentMaxNum_ 时：
//   驱逐 readPos_ 最旧的分片（已在 readPos_ 之后且不再需要的 Chunk）
//   放回 freeChunks_ 链表供复用（避免频繁 malloc/free）
```

### 3.3 Seek 与 ReadBackSave 机制

**证据**：`hls_segment_manager.cpp:900-960`（`SeekToTime`）

```cpp
bool HlsSegmentManager::SeekToTime(int64_t seekTime, SeekMode mode)
{
    AutoLock lock(switchMutex_);
    isSeekingFlag = true;
    seekTime_ = static_cast<uint64_t>(seekTime);
    PrepareToSeek();

    // 直播流 PlaylistBackup：保留历史分片供回退
    if (playlistDownloader_->IsLive()) {
        PlaylistBackup(fragment); // 保留 seekCandidates_ 供回退读取
    }

    // fMP4（HLS + CMAF）特殊处理
    if (playlistDownloader_->IsHlsFmp4()) {
        isNeedReadHeader_.store(true);
    }

    SeekToTs(seekTime, mode);  // 分片内跳转
    HandleSeekReady(curStreamId_, CheckBreakCondition());
    isSeekingFlag = false;
    isSeekedFlag_ = true;
}
```

## 4. AES-128-CBC 解密

**证据**：`services/media_engine/plugins/source/http_source/utils/aes_decryptor.cpp`

```cpp
// aes_decryptor.cpp — AES-128-CBC 解密
class AesDecryptor {
public:
    void OnSourceKeyChange(const uint8_t* key, size_t keyLen, const uint8_t* iv);
    void Decrypt(uint8_t *in, uint8_t *out, uint32_t len); // AES_cbc_encrypt

private:
    uint8_t key_[BLOCK_LEN];         // 16 字节 AES-128 密钥
    uint8_t iv_[BLOCK_LEN];          // 初始化向量（IV）
    AES_KEY aesKey_;                  // OpenSSL AES_KEY 结构
};

// EXT-X-KEY 格式：METHOD=AES-128, URI="key_uri", IV=0x...
// HLS 分片解密流程：
//   1. 从 URI 下载 AES-128 密钥（16 字节）
//   2. 解析 IV（32 字符十六进制）
//   3. AesDecryptor::OnSourceKeyChange(key, keyLen, iv) 初始化
//   4. AES_set_decrypt_key(key_, KEY_BITS=128, &aesKey_)
//   5. AES_cbc_encrypt(in, out, len, &aesKey_, iv_, AES_DECRYPT)
```

## 5. 自适应码率与流控

**证据**：`hls_segment_manager.cpp` 常量定义 + `SelectBitRate` 机制

```cpp
// 带宽估算与码率选择
constexpr int MIN_WIDTH = 480;
constexpr int SECOND_WIDTH = 720;
constexpr int THIRD_WIDTH = 1080;
constexpr uint32_t SAMPLE_INTERVAL = 1000; // 采样间隔：ms
constexpr uint64_t CURRENT_BIT_RATE = 200 * 1024; // 当前码率：200kbps

// 缓冲水位线控制
constexpr int START_PLAY_WATER_LINE = 128 * 1024;  // 开始播放所需最小缓冲
constexpr size_t PLAY_WATER_LINE = 5 * 1024;       // 播放水位线
constexpr size_t MAX_BUFFERING_TIME_OUT = 30 * 1000; // 最大缓冲超时：30s
constexpr size_t MAX_BUFFERING_TIME_OUT_DELAY = 60 * 1000; // 延迟缓冲超时：60s
```

## 6. 与其他组件的关系

| 组件 | 关系 | 说明 |
|------|------|------|
| HttpSourcePlugin（S37） | 调用方 | HttpSourcePlugin 根据 MIME/URL 类型路由到 HlsMediaDownloader |
| HlsMediaDownloader（S37） | 上层管理器 | 创建三个 HlsSegmentManager 实例（video/audio/subtitle）|
| MediaDemuxer（S41/S69） | 消费者 | 从 CacheMediaChunkBufferImpl Read() 获取解密后分片数据 |
| MPEG4DemuxerPlugin（S79） | 下游解析器 | 处理 .m4s 分片（fMP4/CMAF 格式）的 MediaMuxer 输出 |
| FFmpegDemuxerPlugin（S68/S76） | 对比 | 传统 MPEG-TS 分片 vs HLS .ts 分片 |

## 7. 证据索引

| # | 类型 | 路径 | 说明 |
|---|------|------|------|
| 1 | code | `services/media_engine/plugins/source/http_source/utils/media_cached_buffer.cpp` | RingBuffer 核心实现（1386 行），Write/Read/LRU |
| 2 | code | `services/media_engine/plugins/source/http_source/utils/media_cached_buffer.h` | 类定义、CacheChunk 结构、LRUCache 模板 |
| 3 | code | `services/media_engine/plugins/source/http_source/hls/hls_segment_manager.cpp` | 分片管理器（2582 行），Seek/ABR/PlaylistBackup |
| 4 | code | `services/media_engine/plugins/source/http_source/hls/hls_segment_manager.h` | 三轨架构（HlsSegmentManager × 3）|
| 5 | code | `services/media_engine/plugins/source/http_source/utils/aes_decryptor.cpp` | AES-128-CBC 解密（71 行），OpenSSL 封装 |
| 6 | code | `services/media_engine/plugins/source/http_source/hls/m3u8.cpp` | M3U8 解析器（1435 行），EXTINF/EXT-X-KEY 标签解析 |

## 8. 关联记忆

- **MEM-ARCH-AVCODEC-S37**：HttpSourcePlugin HLS/DASH 统一入口（上层组件，持有 HlsSegmentManager）
- **MEM-ARCH-AVCODEC-S38**：SourcePlugin 源插件体系（File/HTTP/Stream/Fd 四类）
- **MEM-ARCH-AVCODEC-S68/S76**：FFmpegDemuxerPlugin（解封装后数据流）
- **MEM-ARCH-AVCODEC-S41**：DemuxerFilter（MediaEngine Filter 层封装）

## 9. 已知限制与注意事项

1. **内存限制**：`CACHE_FRAGMENT_MAX_NUM_DEFAULT = 300`，大型直播流可能超出 LRU 容量导致重新缓冲
2. **Seek 回退限制**：直播流 PlaylistBackup 仅保留 `seekCandidates_` 有限历史，无法无限回退
3. **AES-128 仅支持 CBC 模式**：不支持 AES-GCM 或 AES-CTR（HLS 规范）
4. **fMP4（HLS + CMAF）需特殊处理**：`IsHlsFmp4()` 分支需额外读取 moov/moof Box
5. **多轨同步**：三轨 HlsSegmentManager 独立缓冲，需 MediaSyncManager 对齐播放进度

---
*Builder Agent | 草案生成时间：2026-05-03T23:34:00+08:00*
