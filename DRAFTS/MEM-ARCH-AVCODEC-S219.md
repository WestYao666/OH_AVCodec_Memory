# MEM-ARCH-AVCODEC-S219: MediaEngine Source Plugin 三件套——FileFd / File / DataStream 三路源插件体系

**状态**: draft
**生成时间**: 2026-06-07T22:37
**来源**: 本地镜像探索 `/home/west/av_codec_repo/services/media_engine/plugins/source/`

---

## 主题概述

MediaEngine Source 模块的三大源插件——FileFdSourcePlugin、FileSourcePlugin、DataStreamSourcePlugin——构成完整的本地文件读取与数据流支持矩阵。三者统一继承 SourcePlugin 基类，通过 ProtocolType 路由（FD/File/Stream），覆盖所有本地媒体源类型。

| 插件 | 文件 | 行数 | URI格式 | 核心能力 |
|------|------|------|---------|---------|
| FileFdSourcePlugin | file_fd_source_plugin.cpp/.h | 893+157 | `fd://fd?offset=X&size=Y` | FD读写/云文件缓冲/Seek |
| FileSourcePlugin | file_source_plugin.cpp/.h | 377+79 | `file:///path` | 文件路径读写/Seek |
| DataStreamSourcePlugin | data_stream_source_plugin.cpp/.h | 338+71 | `stream://` | 数据流读写/预读取/重试 |

---

## Evidence（行号级）

### E1: FileFdSourcePlugin 注册与能力定义（L116-135）

```cpp
Status FileFdSourceRegister(const std::shared_ptr<Register>& reg)
{
    MEDIA_LOG_I("fileSourceRegister is started");
    SourcePluginDef definition;
    definition.name = "FileFdSource";
    definition.description = "File Fd source";
    definition.rank = MAX_RANK; // 100: max rank
    Capability capability;
    capability.AppendFixedKey<std::vector<ProtocolType>>(Tag::MEDIA_PROTOCOL_TYPE, {ProtocolType::FD});
    definition.AddInCaps(capability);
    // ...
}
```

rank=100（最高优先级），注册 ProtocolType::FD 能力。

### E2: FileFdSourcePlugin URI 解析正则（L381-415）

```cpp
FALSE_RETURN_V_MSG_E(std::regex_match(uri, fdUriMatch, std::regex("^fd://(.*)\\?offset=(.*)&size=(.*)")) ||
    std::regex_match(uri, fdUriMatch, std::regex("^fd://(.*)")),
    Status::ERROR_INVALID_PARAMETER, "Invalid fd uri format");
// 解析 fd://N?offset=X&size=Y 格式，支持 fd 编号 + 可选偏移量 + 可选大小
```

### E3: FileFdSourcePlugin 云文件 RingBuffer 预读（L185-196）

```cpp
if (isCloudFile_ && isEnableFdCache_) {
    ringBuffer_ = std::make_shared<RingBuffer>(CACHE_SIZE); // CACHE_SIZE=40MB
    FALSE_RETURN_V_MSG_E(!(ringBuffer_ == nullptr || !ringBuffer_->Init()),
        Status::ERROR_NO_MEMORY, "memory is not enough ringBuffer_");
    downloadTask_ = std::make_shared<Task>(std::string("downloadTaskFD"));
    downloadTask_->RegisterJob([this] { CacheDataLoop(); return 0; });
    downloadTask_->Start();
}
```

云文件开启 40MB RingBuffer 缓冲，后台 Task 线程预读数据。

### E4: FileFdSourcePlugin 离线文件读（L206-235）

```cpp
Status FileFdSourcePlugin::ReadOfflineFile(int32_t streamId, std::shared_ptr<Buffer>& buffer,
    uint64_t offset, size_t expectedLen)
{
    std::shared_ptr<Memory> bufData = GetBufferPtr(buffer, expectedLen);
    // ...
    auto size = read(fd_, bufData->GetWritableAddr(expectedLen), expectedLen);
    if (size <= 0) {
        HandleReadResult(expectedLen, size);
        // ...
        return Status::END_OF_STREAM;
    }
    bufData->UpdateDataSize(size);
    position_ += static_cast<uint64_t>(size);
    // ...
}
```

离线文件直接 read(fd_) 读取，本地 Seek 通过 lseek(fd_, offset, SEEK_SET)。

### E5: FileFdSourcePlugin 云文件缓冲读取（L281-320）

```cpp
Status FileFdSourcePlugin::ReadOnlineFile(int32_t streamId, std::shared_ptr<Buffer>& buffer,
    uint64_t offset, size_t expectedLen)
{
    if (isBuffering_) {
        if (HandleBuffering()) {
            FALSE_RETURN_V_MSG_E(!isInterrupted_, Status::OK, "please not retry read, isInterrupted true");
            FALSE_RETURN_V_MSG_E(isReadBlocking_, Status::OK, "please not retry read, isReadBlocking false");
            return Status::ERROR_AGAIN;
        }
    }
    // ringBuffer_->GetSize() < expectedLen && !HasCacheData() → 等待预读
}
```

云文件通过 RingBuffer 缓冲读取，支持 buffering 状态管理和 ERROR_AGAIN 重试。

### E6: FileFdSourcePlugin HMDFS IOCTL 云文件元数据（L84-87）

```cpp
#define HMDFS_IOC_HAS_CACHE _IOW(HMDFS_IOC, 6, struct HmdfsHasCache)
#define HMDFS_IOC_GET_LOCATION _IOR(HMDFS_IOC, 7, __u32)
#define HMDFS_IOC_CANCEL_READ _IO(HMDFS_IOC, 8)
#define HMDFS_IOC_RESTORE_READ _IO(HMDFS_IOC, 9)
```

HMDFS 分布式文件系统 IOCTL 接口，用于查询云文件缓存状态。

### E7: FileFdSourcePlugin 常量定义（L82-100）

```cpp
constexpr size_t CACHE_SIZE                     = 40 * 1024 * 1024; // 40MB ringbuffer
constexpr size_t PER_CACHE_SIZE                 = 48 * 10 * 1024;   // 480KB per batch
constexpr int32_t SEEK_TIME_LOWER               = 20;   // seek 20ms内认为 seekable
constexpr int32_t SEEK_TIME_UPPER               = 1000; // seek >1000ms 认为不可 seekable
constexpr int32_t RETRY_TIMES                   = 3;
constexpr float CACHE_LEVEL_1                   = 0.3; // 30% 缓冲水位线
```

### E8: FileSourcePlugin 注册与能力定义（L60-75）

```cpp
Status FileSourceRegister(const std::shared_ptr<Register>& reg)
{
    SourcePluginDef definition;
    definition.name = "FileSource";
    definition.description = "File source";
    definition.rank = MAX_RANK; // 100: max rank
    Plugins::Capability capability;
    capability.AppendFixedKey<std::vector<Plugins::ProtocolType>>(
        Tag::MEDIA_PROTOCOL_TYPE, {Plugins::ProtocolType::FILE});
    definition.AddInCaps(capability);
    definition.SetCreator(FileSourcePluginCreator);
    return reg->AddPlugin(definition);
}
```

注册 ProtocolType::FILE 能力，rank=100。

### E9: FileSourcePlugin Seek 实现（L200-230）

```cpp
Status FileSourcePlugin::SeekTo(uint64_t offset)
{
    FALSE_RETURN_V_MSG_E(seekable_ == Seekable::SEEKABLE, Status::ERROR_WRONG_STATE, "file is not seekable");
    int32_t ret = lseek(fd_, offset, SEEK_SET);
    if (ret == -1) {
        MEDIA_LOG_E("SeekTo failed, fd_ " PUBLIC_LOG_D32 ", offset " PUBLIC_LOG_U64, fd_, offset);
        return Status::ERROR_UNKNOWN;
    }
    position_ = offset;
    return Status::OK;
}
```

### E10: DataStreamSourcePlugin 注册与能力定义（L45-60）

```cpp
Status DataStreamSourceRegister(const std::shared_ptr<Plugins::Register>& reg)
{
    Plugins::SourcePluginDef definition;
    definition.name = "DataStreamSource";
    definition.description = "Data stream source";
    definition.rank = 100; // 100: max rank
    Plugins::Capability capability;
    capability.AppendFixedKey<std::vector<Plugins::ProtocolType>>(
        Tag::MEDIA_PROTOCOL_TYPE, {Plugins::ProtocolType::STREAM});
    definition.AddInCaps(capability);
    definition.SetCreator(DataStreamSourcePluginCreator);
    return reg->AddPlugin(definition);
}
```

注册 ProtocolType::STREAM 能力，支持数据流式读取。

### E11: DataStreamSourcePlugin 预读取机制（L33-37）

```cpp
constexpr uint32_t INIT_MEM_CNT = 10;
constexpr int32_t MEM_SIZE = 10240;
constexpr uint32_t MAX_MEM_CNT = 10 * 1024;
constexpr size_t DEFAULT_PREDOWNLOAD_SIZE_BYTE = 10 * 1024 * 1024; // 10MB 预取
constexpr uint32_t DEFAULT_RETRY_TIMES = 20;
```

预读取 10MB，支持最多 10*1024 个内存块，每个 10KB。

### E12: DataStreamSourcePlugin Read 重试机制（L200-280）

```cpp
constexpr uint32_t READ_AGAIN_RETRY_TIME_ONE = 100;   // 100ms 重试
constexpr uint32_t READ_AGAIN_RETRY_TIME_TWO = 200;   // 200ms 重试
constexpr uint32_t READ_AGAIN_RETRY_TIME_THREE = 500; // 500ms 重试
// 支持 ERROR_AGAIN 返回后三重间隔重试（100/200/500ms）
```

### E13: SourcePlugin 基类接口（file_source_plugin.h / file_fd_source_plugin.h / data_stream_source_plugin.h）

三大插件均继承自 `SourcePlugin` 基类，核心接口：
- `SetSource(MediaSource)` — 设置媒体源 URI
- `Read(Buffer, offset, expectedLen)` — 读取数据
- `SeekTo(offset)` — Seek 到指定位置
- `GetSize()` — 获取媒体总长度
- `SetCallback(Callback)` — 设置回调

### E14: FileFdSourcePlugin 统计分析事件上报（L193-195）

```cpp
auto uuid = source->GetAppUid();
std::string bundleName = OHOS::Media::HttpMediaUtils::GetClientBundleName(uuid);
MediaAVCodec::StreamAppPackageNameEventWrite("AVSource", bundleName,
    "OH_AVSource_CreateWithFD", "{\"result\": \"success\"}");
```

创建 FD Source 时上报 APP 包名和结果到 DFX。

### E15: 三插件协议类型枚举（SourcePluginDef.capability）

| 插件 | ProtocolType | URI示例 |
|------|-------------|---------|
| FileFdSourcePlugin | FD | `fd://3?offset=0&size=1024000` |
| FileSourcePlugin | FILE | `file:///data/media/123.mp4` |
| DataStreamSourcePlugin | STREAM | `stream://` (内存数据流) |

---

## 架构分析

### 三路源插件定位

```
MediaSource URI
    │
    ├── fd://N?offset=X&size=Y  → FileFdSourcePlugin  (文件描述符，高效云文件)
    ├── file:///path            → FileSourcePlugin    (文件路径，本地文件)
    └── stream://               → DataStreamSourcePlugin (内存数据流)
```

### FileFdSourcePlugin 双模式

```
FileFdSourcePlugin
    ├── 本地文件：read(fd_) → 直接读
    └── 云文件（HMDFS）：RingBuffer(40MB) + CacheDataLoop Task预读 → 缓冲读
```

RingBuffer 缓冲策略：30% 水位线（`CACHE_LEVEL_1=0.3`），Seek 时清空缓冲区。

### 与 HttpSourcePlugin 的关系

HttpSourcePlugin（`https://`）与 FileFdSourcePlugin/FileSourcePlugin/DataStreamSourcePlugin 三者共同构成完整的 Source 协议矩阵：
- HttpSourcePlugin → 网络流（HTTP/HTTPS）
- FileFdSourcePlugin → FD 描述符（云文件/本地FD）
- FileSourcePlugin → 文件路径
- DataStreamSourcePlugin → 内存数据流

### 与 S106/S122 的关联

S106（MediaEngine Source 模块流媒体基础设施）覆盖 HttpSourcePlugin 和 Source 模块总览；S122（MediaEngine Streaming 基础设施）覆盖 HttpSourcePlugin 三路下载器路由。S219 补充本地文件三插件体系，与 S106/S122 互补。

---

## 关键发现

1. **FileFdSourcePlugin 云文件特性**：通过 HMDFS IOCTL 查询云端缓存状态，支持云文件 RingBuffer 预读（40MB）和后台 CacheDataLoop Task 线程。
2. **Seekable 判断**：通过 SEEK_TIME_LOWER=20ms 和 SEEK_TIME_UPPER=1000ms 双阈值判断 Seek 延迟决定是否可Seek。
3. **DFX 事件上报**：FileFdSource 创建时上报 APP 包名和创建结果到 `MediaAVCodec::StreamAppPackageNameEventWrite`。
4. **DataStreamSource 重试三级跳**：ERROR_AGAIN 后支持 100ms→200ms→500ms 三级递增重试间隔。
5. **三者统一继承 SourcePlugin**，通过 ProtocolType 路由，rank 均为 100（最高优先级）。

---

## 关联主题

- **S106**（MediaEngine Source 模块流媒体基础设施）— HttpSourcePlugin 总览
- **S122**（MediaEngine Streaming 基础设施）— HttpSourcePlugin 三路下载器
- **S195**（HttpSourcePlugin Downloader 网络下载架构）— Downloader 三层架构
- **S210**（HttpSourcePlugin 下载监控装饰器模式）— DownloadMonitor 装饰器
