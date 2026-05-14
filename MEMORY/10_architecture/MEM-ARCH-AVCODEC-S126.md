---
type: architecture
id: MEM-ARCH-AVCODEC-S126
status: pending_approval
topic: AVSource/AVDemuxer Native C API 双组件架构——OH_AVSource 三路创建与 OH_AVDemuxer 五路接口
scope: [AVCodec, Native API, C API, OH_AVSource, OH_AVDemuxer, OH_AVDataSource, IMediaDataSource, MediaDemuxer, DRM, Callback, Source, Demuxer, IPC, Filter]
created_at: "2026-05-14T08:28:00+08:00"
updated_at: "2026-05-14T08:28:00+08:00"
source_repo: /home/west/av_codec_repo
source_root: frameworks/native/capi/avsource, frameworks/native/capi/avdemuxer, frameworks/native/avsource, frameworks/native/avdemuxer, interfaces/inner_api/native
evidence_version: local_mirror
---

## 一、架构总览

AVSource / AVDemuxer 是 MediaAVCodec 对外提供**媒体源解析与解封装**能力的 Native C API 双组件：

- **OH_AVSource**：媒体源创建与元数据查询（3种创建路径，3个查询接口）
- **OH_AVDemuxer**：解封装操作与 DRM 信息回调（创建 + 5个核心操作）

```
三层架构：
Native C API 层                      引擎实现层                    底层组件层
───────────────────                  ──────────                   ─────────
OH_AVSource (native_avsource.cpp)──► AVSourceImpl (avsource_impl.cpp)──► MediaDemuxer
OH_AVDemuxer (native_avdemuxer.cpp)──► AVDemuxer (avdemuxer_impl.cpp)──► DemuxerPluginManager
```

关键文件行号：
- `native_avsource.cpp`（325行）：OH_AVSource C API 入口
- `avsource_impl.cpp`（198行）：AVSourceImpl + AVSourceFactory 工厂
- `avsource_impl.h`（40行）：AVSourceImpl 类定义
- `interfaces/inner_api/native/avsource.h`（110行）：AVSource 基类接口
- `native_avdemuxer.cpp`（318行）：OH_AVDemuxer C API 入口
- `avdemuxer_impl.cpp`（282行）：AVDemuxerImpl 引擎实现

---

## 二、OH_AVSource 三路创建架构

### 2.1 三种创建路径

`native_avsource.cpp` 提供 **3 个创建函数**，均委托 `AVSourceFactory` 分发：

| 创建函数 | 实现行 | 内部路径 |
|---------|--------|---------|
| `OH_AVSource_CreateWithURI(char *uri)` | l.140-181 | `AVSourceFactory::CreateWithURI(uri)` |
| `OH_AVSource_CreateWithFD(int32_t fd, int64_t offset, int64_t size)` | l.188-210 | `AVSourceFactory::CreateWithFD(fd, offset, size)` |
| `OH_AVSource_CreateWithDataSource(OH_AVDataSource *dataSource)` | l.216-232 | `AVSourceFactory::CreateWithDataSource(nativeAVDataSource)` |
| `OH_AVSource_CreateWithDataSourceExt(OH_AVDataSourceExt *dataSource, void *userData)` | l.309-318 | `AVSourceFactory::CreateWithDataSource(nativeAVDataSource)` |

### 2.2 NativeAVDataSource 桥接器

`native_avsource.cpp:39-89`：将 C 层 `OH_AVDataSource` 桥接至 `IMediaDataSource` 接口：

```cpp
// native_avsource.cpp:39-89
class NativeAVDataSource : public OHOS::Media::IMediaDataSource {
public:
    explicit NativeAVDataSource(OH_AVDataSource *dataSource)
        : isExt_(false), dataSource_(dataSource), dataSourceExt_(nullptr), userData_(nullptr)
    {
        if (dataSource_ != nullptr) {
            readAt_ = dataSource_->readAt;  // C函数指针 → C++方法
        }
    }

    NativeAVDataSource(OH_AVDataSourceExt* dataSourceExt, void* userData)
        : isExt_(true), dataSource_(nullptr), dataSourceExt_(dataSourceExt), userData_(userData)
    {
        if (dataSourceExt_ != nullptr) {
            readAtExt_ = dataSourceExt_->readAt;  // Ext版本带userData
        }
    }

    int32_t ReadAt(const std::shared_ptr<AVSharedMemory> &mem, uint32_t length, int64_t pos = -1)  // l.53-73
    {
        std::shared_ptr<AVBuffer> buffer = AVBuffer::CreateAVBuffer(
            mem->GetBase(), mem->GetSize(), mem->GetSize()
        );
        OH_AVBuffer avBuffer(buffer);

        if (isExt_ && readAtExt_ != nullptr) {
            return readAtExt_(&avBuffer, length, pos, userData_);  // Ext版传userData
        } else if (readAt_ != nullptr) {
            return readAt_(&avBuffer, length, pos);  // 基础版
        } else {
            return 0;
        }
    }

    int32_t GetSize(int64_t &size)  // l.75-82
    {
        if (isExt_) {
            size = dataSourceExt_->size;
        } else {
            size = dataSource_->size;
        }
        return 0;
    }
```

关键字段（`native_avsource.cpp:85-89`）：
```cpp
private:
    bool isExt_ = false;
    OH_AVDataSource* dataSource_;
    OH_AVDataSourceExt* dataSourceExt_ = nullptr;
    void* userData_ = nullptr;
    OH_AVDataSourceReadAt readAt_ = nullptr;        // 基础版回调
    OH_AVDataSourceReadAtExt readAtExt_ = nullptr;   // Ext版回调（带userData）
```

### 2.3 AVSourceImpl 引擎实现

`avsource_impl.cpp:41-89`：`AVSourceFactory` 三个工厂方法：

```cpp
// avsource_impl.cpp:41-89
std::shared_ptr<AVSource> AVSourceFactory::CreateWithURI(const std::string &uri)
{
    std::shared_ptr<AVSourceImpl> sourceImpl = std::make_shared<AVSourceImpl>();
    int32_t ret = sourceImpl->InitWithURI(uri);
    return sourceImpl;
}

std::shared_ptr<AVSource> AVSourceFactory::CreateWithFD(int32_t fd, int64_t offset, int64_t size)
{
    // 参数校验：fd >= 0, offset >= 0, size > 0
    // 检查fd可读 (F_GETFL & O_WRONLY)
    // 检查fd可seek (lseek != -1)
    std::string uri = "fd://" + std::to_string(fd) + "?offset=" + \
        std::to_string(offset) + "&size=" + std::to_string(size);
    return InitWithURI(uri);  // 转为URI路径
}

std::shared_ptr<AVSource> AVSourceFactory::CreateWithDataSource(
    const std::shared_ptr<Media::IMediaDataSource> &dataSource)
{
    std::shared_ptr<AVSourceImpl> sourceImpl = std::make_shared<AVSourceImpl>();
    int32_t ret = sourceImpl->InitWithDataSource(dataSource);
    return sourceImpl;
}
```

`avsource_impl.cpp:91-121`：`AVSourceImpl::InitWithURI` 实现：

```cpp
// avsource_impl.cpp:91-121
int32_t AVSourceImpl::InitWithURI(const std::string &uri)
{
    CHECK_AND_RETURN_RET_LOG(mediaDemuxer == nullptr, AVCS_ERR_INVALID_OPERATION, "Has been used by demuxer");
    mediaDemuxer = std::make_shared<MediaDemuxer>();
    std::shared_ptr<MediaSource> mediaSource = std::make_shared<MediaSource>(uri);
    Status ret = mediaDemuxer->SetDataSource(mediaSource);
    CHECK_AND_RETURN_RET_LOG(ret == Status::OK, StatusToAVCodecServiceErrCode(ret), "Set data source failed");

    sourceUri = uri;
    return AVCS_ERR_OK;
}
```

`avsource_impl.cpp:124-148`：`AVSourceImpl::InitWithFD` 参数校验（注意 line 137-140 的严格校验）：

```cpp
// avsource_impl.cpp:124-148
int32_t AVSourceImpl::InitWithFD(int32_t fd, int64_t offset, int64_t size)
{
    CHECK_AND_RETURN_RET_LOG(fd >= 0, AVCS_ERR_INVALID_VAL, "Input fd is negative");
    if (fd <= STDERR_FILENO) {
        AVCODEC_LOGW("Using special fd: %{public}d, isatty: %{public}d", fd, isatty(fd));  // fd 0/1/2 警告
    }
    CHECK_AND_RETURN_RET_LOG(offset >= 0, AVCS_ERR_INVALID_VAL, "Input offset is negative");
    CHECK_AND_RETURN_RET_LOG(size > 0, AVCS_ERR_INVALID_VAL, "Input size must be greater than zero");
    int32_t flag = fcntl(fd, F_GETFL, 0);
    CHECK_AND_RETURN_RET_LOG(flag >= 0, AVCS_ERR_INVALID_VAL, "Get fd status failed");
    CHECK_AND_RETURN_RET_LOG(
        (static_cast<uint32_t>(flag) & static_cast<uint32_t>(O_WRONLY)) != static_cast<uint32_t>(O_WRONLY),
        AVCS_ERR_INVALID_VAL, "Fd is not permitted to read");
    CHECK_AND_RETURN_RET_LOG(lseek(fd, 0, SEEK_CUR) != -1, AVCS_ERR_INVALID_VAL, "Fd unseekable");
    // ... 构建 fd:// URI
}
```

### 2.4 AVSource 基类接口

`interfaces/inner_api/native/avsource.h:26-50`：AVSource 抽象基类（3个纯虚函数）：

```cpp
// interfaces/inner_api/native/avsource.h:26-50
class AVSource {
public:
    virtual ~AVSource() = default;

    virtual int32_t GetSourceFormat(OHOS::Media::Format &format) = 0;    // l.32-38
    virtual int32_t GetTrackFormat(OHOS::Media::Format &format, uint32_t trackIndex) = 0;  // l.40-49
    virtual int32_t GetUserMeta(OHOS::Media::Format &format) = 0;        // l.51-57

    std::string sourceUri;                                        // l.58
    std::shared_ptr<Media::MediaDemuxer> mediaDemuxer = nullptr; // l.59
};
```

`avsource_impl.cpp:156-197`：三个查询方法实现（均委托 `mediaDemuxer`）：

```cpp
// avsource_impl.cpp:156-197
int32_t AVSourceImpl::GetSourceFormat(OHOS::Media::Format &format)
{
    std::shared_ptr<OHOS::Media::Meta> mediaInfo = mediaDemuxer->GetGlobalMetaInfo();
    bool set = format.SetMeta(mediaInfo);
    CHECK_AND_RETURN_RET_LOG(set, AVCS_ERR_INVALID_OPERATION, "Convert meta failed");
    return AVCS_ERR_OK;
}

int32_t AVSourceImpl::GetTrackFormat(OHOS::Media::Format &format, uint32_t trackIndex)
{
    std::vector<std::shared_ptr<Meta>> streamsInfo = mediaDemuxer->GetStreamMetaInfo();
    CHECK_AND_RETURN_RET_LOG(trackIndex < streamsInfo.size(), AVCS_ERR_INVALID_VAL, "index is out of range");
    bool set = format.SetMeta(streamsInfo[trackIndex]);
    CHECK_AND_RETURN_RET_LOG(set, AVCS_ERR_INVALID_OPERATION, "Convert meta failed");
    return AVCS_ERR_OK;
}

int32_t AVSourceImpl::GetUserMeta(OHOS::Media::Format &format)
{
    std::shared_ptr<OHOS::Media::Meta> userDataMeta = mediaDemuxer->GetUserMeta();
    bool set = format.SetMeta(userDataMeta);
    CHECK_AND_RETURN_RET_LOG(set, AVCS_ERR_INVALID_OPERATION, "Parse user info failed");
    return AVCS_ERR_OK;
}
```

---

## 三、OH_AVDemuxer 五路接口架构

### 3.1 DemuxerObject 对象模型

`native_avdemuxer.cpp:78-81`：DemuxerObject 结构体：

```cpp
// native_avdemuxer.cpp:78-81
struct DemuxerObject : public OH_AVDemuxer {
    explicit DemuxerObject(const std::shared_ptr<AVDemuxer> &demuxer)
        : OH_AVDemuxer(AVMagic::AVCODEC_MAGIC_AVDEMUXER), demuxer_(demuxer) {}

    std::shared_ptr<AVDemuxer> demuxer_;  // 引擎层
    std::shared_ptr<NativeDemuxerCallback> callback_;  // DRM回调
};
```

### 3.2 五路核心接口

| API 函数 | 行号 | 功能 |
|---------|------|------|
| `OH_AVDemuxer_CreateWithSource(OH_AVSource *source)` | l.134-152 | 从AVSource创建解封装器 |
| `OH_AVDemuxer_SelectTrackByID(OH_AVDemuxer *demuxer, uint32_t trackIndex)` | l.163-177 | 选择轨道 |
| `OH_AVDemuxer_UnselectTrackByID(OH_AVDemuxer *demuxer, uint32_t trackIndex)` | l.179-192 | 取消选择轨道 |
| `OH_AVDemuxer_ReadSample(OH_AVDemuxer *demuxer, uint32_t trackIndex, OH_AVMemory *sample, ...)` | l.195-218 | Memory模式读取样本 |
| `OH_AVDemuxer_ReadSampleBuffer(OH_AVDemuxer *demuxer, uint32_t trackIndex, OH_AVBuffer *sample)` | l.224-242 | Buffer模式读取样本 |
| `OH_AVDemuxer_SeekToTime(OH_AVDemuxer *demuxer, int64_t millisecond, OH_AVSeekMode mode)` | l.244-265 | 跳转到指定时间 |

### 3.3 CreateWithSource 实现

`native_avdemuxer.cpp:134-152`：

```cpp
// native_avdemuxer.cpp:134-152
struct OH_AVDemuxer *OH_AVDemuxer_CreateWithSource(OH_AVSource *source)
{
    CHECK_AND_RETURN_RET_LOG(source != nullptr, nullptr, "Input source is nullptr");
    CHECK_AND_RETURN_RET_LOG(source->magic_ == AVMagic::AVCODEC_MAGIC_AVSOURCE, nullptr, "Magic error");

    struct SourceObject *sourceObj = reinterpret_cast<struct SourceObject *>(source);
    CHECK_AND_RETURN_RET_LOG(sourceObj->source_ != nullptr, nullptr, "Get source failed");

    ApiInvokeRecorder apiInvokeRecorder("OH_AVDemuxer_CreateWithSource", appEventReporter);
    std::shared_ptr<AVDemuxer> demuxer = AVDemuxerFactory::CreateWithSource(sourceObj->source_->mediaDemuxer);
    CHECK_AND_RETURN_RET_LOG(demuxer != nullptr, nullptr, "Create demuxer failed");

    struct DemuxerObject *demuxerObj = new DemuxerObject(demuxer);
    return reinterpret_cast<OH_AVDemuxer *>(demuxerObj);
}
```

关键：`AVDemuxerFactory::CreateWithSource(sourceObj->source_->mediaDemuxer)` — 直接复用 AVSource 内部的 MediaDemuxer 实例，实现**源共享**。

### 3.4 ReadSample 双模式

`native_avdemuxer.cpp:195-218`：Memory 模式（`OH_AVMemory`）：

```cpp
// native_avdemuxer.cpp:195-218
OH_AVErrCode OH_AVDemuxer_ReadSample(OH_AVDemuxer *demuxer, uint32_t trackIndex,
    OH_AVMemory *memory, OH_AVCodecBufferInfo *bufferInfo, uint32_t *flag)
{
    CHECK_AND_RETURN_RET_LOG(demuxer != nullptr, AV_ERR_INVALID_VAL, "Input demuxer is nullptr");
    CHECK_AND_RETURN_RET_LOG(memory != nullptr, AV_ERR_INVALID_VAL, "Input memory is nullptr");

    struct DemuxerObject *demuxerObj = reinterpret_cast<DemuxerObject *>(demuxer);
    std::shared_ptr<AVSharedMemory> mem = memory->memory_;
    AVCodecBufferInfo bufferInfoInner;
    uint32_t bufferFlag = 0;

    int32_t ret = demuxerObj->demuxer_->ReadSample(trackIndex, mem, bufferInfoInner, bufferFlag);  // 引擎调用

    (void)memcpy_s(memory->memory_->GetBase(), bufferInfoInner.size, 
                   mem->GetBase(), bufferInfoInner.size);  // 复制数据

    *bufferInfo = bufferInfoInner;
    *flag = bufferFlag;
    return AVCSErrorToOHAVErrCode(static_cast<AVCodecServiceErrCode>(ret));
}
```

`native_avdemuxer.cpp:224-242`：Buffer 模式（`OH_AVBuffer`）：

```cpp
// native_avdemuxer.cpp:224-242
OH_AVErrCode OH_AVDemuxer_ReadSampleBuffer(OH_AVDemuxer *demuxer, uint32_t trackIndex, OH_AVBuffer *sample)
{
    CHECK_AND_RETURN_RET_LOG(demuxer != nullptr, AV_ERR_INVALID_VAL, "Input demuxer is nullptr");
    CHECK_AND_RETURN_RET_LOG(sample != nullptr, AV_ERR_INVALID_VAL, "Input buffer is nullptr");

    struct DemuxerObject *demuxerObj = reinterpret_cast<DemuxerObject *>(demuxer);
    int32_t ret = demuxerObj->demuxer_->ReadSampleBuffer(trackIndex, sample->buffer_);  // 直接传buffer，无copy
    return AVCSErrorToOHAVErrCode(static_cast<AVCodecServiceErrCode>(ret));
}
```

### 3.5 DRM 信息回调体系

`native_avdemuxer.cpp:266-318`：两套 DRM 回调接口：

```cpp
// native_avdemuxer.cpp:266-318
// 回调接口1：OH_AVDemuxer_SetMediaKeySystemInfoCallback
OH_AVErrCode OH_AVDemuxer_SetMediaKeySystemInfoCallback(OH_AVDemuxer *demuxer,
    DRM_MediaKeySystemInfoCallback callback)
{
    struct DemuxerObject *demuxerObj = reinterpret_cast<DemuxerObject *>(demuxer);
    demuxerObj->callback_ = std::make_shared<NativeDemuxerCallback>(demuxer, callback);
    int32_t ret = demuxerObj->demuxer_->SetCallback(demuxerObj->callback_);
    return AVCSErrorToOHAVErrCode(static_cast<AVCodecServiceErrCode>(ret));
}

// 回调接口2：OH_AVDemuxer_SetDemuxerMediaKeySystemInfoCallback
OH_AVErrCode OH_AVDemuxer_SetDemuxerMediaKeySystemInfoCallback(OH_AVDemuxer *demuxer,
    Demuxer_MediaKeySystemInfoCallback callback)
{
    // 与回调接口1相同结构，但callback类型不同
    demuxerObj->callback_ = std::make_shared<NativeDemuxerCallback>(demuxer, callback);
    int32_t ret = demuxerObj->demuxer_->SetCallback(demuxerObj->callback_);
    return AVCSErrorToOHAVErrCode(static_cast<AVCodecServiceErrCode>(ret));
}

// 查询DRM信息：OH_AVDemuxer_GetMediaKeySystemInfo
OH_AVErrCode OH_AVDemuxer_GetMediaKeySystemInfo(OH_AVDemuxer *demuxer, DRM_MediaKeySystemInfo *mediaKeySystemInfo)
{
    struct DemuxerObject *demuxerObj = reinterpret_cast<DemuxerObject *>(demuxer);
    std::multimap<std::string, std::vector<uint8_t>> drmInfos;
    int32_t ret = demuxerObj->demuxer_->GetMediaKeySystemInfo(drmInfos);
    CHECK_AND_RETURN_RET_LOG(!drmInfos.empty(), AV_ERR_OK, "DrmInfo is null");

    ret = NativeDrmTools::ProcessApplicationDrmInfo(mediaKeySystemInfo, drmInfos);  // PSSH处理
    return AV_ERR_OK;
}
```

`native_avdemuxer.cpp:24-67`：`NativeDrmTools::ProcessApplicationDrmInfo` — PSSH UUID 解析：

```cpp
// native_avdemuxer.cpp:24-67
static int32_t ProcessApplicationDrmInfo(DRM_MediaKeySystemInfo *info,
    const std::multimap<std::string, std::vector<uint8_t>> &drmInfoMap)
{
    uint32_t count = drmInfoMap.size();
    if (count <= 0 || count > MAX_PSSH_INFO_COUNT) {
        return AV_ERR_INVALID_VAL;
    }
    info->psshCount = count;
    uint32_t index = 0;
    for (auto &item : drmInfoMap) {
        // UUID字符串（如 "edef8ba979d64acea3c827dcd51d21ed"）→ 字节数组
        for (uint32_t i = 0; i < item.first.size(); i += 2) {
            std::string byteString = item.first.substr(i, 2);
            unsigned char uuidByte = (unsigned char)strtol(byteString.c_str(), NULL, 16);
            info->psshInfo[index].uuid[i / 2] = uuidByte;
        }
        info->psshInfo[index].dataLen = static_cast<int32_t>(item.second.size());
        (void)memcpy_s(info->psshInfo[index].data, item.second.size(),
                       static_cast<const void *>(item.second.data()), item.second.size());
        index++;
    }
    return AV_ERR_OK;
}
```

---

## 四、双组件关联关系

```
应用程序
  │
  ├─► OH_AVSource_CreateWithURI/FD/DataSource()
  │      └─► AVSourceImpl.InitWithURI/FD/DataSource()
  │             └─► MediaDemuxer.SetDataSource(MediaSource)
  │                    └─► DemuxerPluginManager (S41/S75/S97)
  │
  └─► OH_AVDemuxer_CreateWithSource(oh_av_source)
         └─► source->mediaDemuxer (同一实例，共享)
                └─► AVDemuxer.ReadSample/SelectTrack/SeekToTime
```

关键关联点：
- `AVSource` 内部持有 `mediaDemuxer`（`avsource_impl.h:28`）
- `AVDemuxer.CreateWithSource` 直接复用该 `mediaDemuxer`（`native_avdemuxer.cpp:149`）
- 一个媒体源可创建多个解封装器实例，实现**多轨并发读**

---

## 五、与其他记忆条目关联

| 关联记忆 | 关联说明 |
|---------|---------|
| `MEM-ARCH-AVCODEC-S94` | S94 已覆盖 OH_AVSource / OH_AVDemuxer / OH_AVMuxer CAPI 三件套总览；S126 补充 AVSourceImpl/AVDemuxerImpl 引擎层深度分析 |
| `MEM-ARCH-AVCODEC-S41` | DemuxerFilter → MediaDemuxer 上游；AVSource 内部的 MediaDemuxer 即 S41/S75 的引擎实例 |
| `MEM-ARCH-AVCODEC-S83` | S83 CAPI 总览包含 OH_AVCodec / OH_AVFormat / OH_AVBuffer；S126 补充 Source/Demuxer 专册 |
| `MEM-ARCH-AVCODEC-S63` | DRM CENC 解密与 AVDemuxer DRM 回调体系（S126 3.5节）同属 ContentProtection 场景 |
| `MEM-ARCH-AVCODEC-S69/S75/S97` | MediaDemuxer 引擎层（ReadLoop / SampleQueue / DemuxerPluginManager），AVSource 持有同一实例 |

---

## 六、关键证据索引

| 证据 | 文件 | 行号 |
|------|------|------|
| NativeAVDataSource 桥接器 | `frameworks/native/capi/avsource/native_avsource.cpp` | 39-89 |
| OH_AVSource 三路创建 | `frameworks/native/capi/avsource/native_avsource.cpp` | 140-318 |
| AVSourceImpl 工厂方法 | `frameworks/native/avsource/avsource_impl.cpp` | 41-89 |
| AVSourceImpl FD参数校验 | `frameworks/native/avsource/avsource_impl.cpp` | 124-148 |
| AVSourceImpl 元数据查询 | `frameworks/native/avsource/avsource_impl.cpp` | 156-197 |
| AVSource 基类接口 | `interfaces/inner_api/native/avsource.h` | 26-59 |
| DemuxerObject 对象模型 | `frameworks/native/capi/avdemuxer/native_avdemuxer.cpp` | 78-81 |
| AVDemuxer 五路核心接口 | `frameworks/native/capi/avdemuxer/native_avdemuxer.cpp` | 134-265 |
| ReadSample 双模式 | `frameworks/native/capi/avdemuxer/native_avdemuxer.cpp` | 195-242 |
| DRM PSSH 处理 | `frameworks/native/capi/avdemuxer/native_avdemuxer.cpp` | 24-67, 266-318 |
| AVSourceImpl 头文件 | `frameworks/native/avsource/avsource_impl.h` | 25-40 |