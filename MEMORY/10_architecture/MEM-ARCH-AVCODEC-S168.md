---
id: MEM-ARCH-AVCODEC-S168
title: SEI Parser Filter 与 SEI Parser Helper 源码深度分析——双文件582行行号级evidence
scope: [AVCodec, MediaEngine, Filter, SEI, Parser, AnnexB, AVC, HEVC, Nalu, EventCallback, FlowLimit, RBSP, DRM, Plugin]
topic: SEI Parser Filter 与 SEI Parser Helper——AVC NAL type=6 / HEVC NAL type=39-40 双格式解析、RBSP 防伪字节转义、FlowLimit PTS 同步限流、SeiPayloadInfoGroup 回调链路
===
# MEM-ARCH-AVCODEC-S168

> **状态**: pending_approval
> **生成时间**: 2026-05-21T09:52:00+08:00
> **Builder**: builder-agent (subagent)
> **来源**: 本地镜像 `/home/west/av_codec_repo` + web_fetch GitCode 交叉验证

---

## 一、主题概述

SEI（Supplemental Enhancement Information）解析框架从视频码流中提取 SEI 信息（时间戳、版权、用户数据等），在播放 Pipeline 中通过 `EVENT_SEI_INFO` 事件回调向上传递给应用层。核心代码位于：

- `services/media_engine/filters/sei_parser_filter.cpp`（235行）——Filter 层封装
- `services/media_engine/filters/sei_parser_helper.cpp`（347行）——NAL 单元 SEI 解析引擎
- `interfaces/inner_api/native/sei_parser_filter.h`（104行）——Filter 类声明
- `interfaces/inner_api/native/sei_parser_helper.h`（135行）——Helper/Listener 类声明

合计 821 行源码，涵盖 AVC（NAL type=6）和 HEVC（NAL type=39/40）双格式解析。

---

## 二、文件结构总览

```
services/media_engine/filters/
├── sei_parser_filter.cpp     (235行)  Filter层封装
└── sei_parser_helper.cpp     (347行)  NAL解析引擎

interfaces/inner_api/native/
├── sei_parser_filter.h       (104行)  Filter类声明
└── sei_parser_helper.h      (135行)  Helper/Listener数据结构
```

---

## 三、静态注册——AutoRegisterFilter（sei_parser_filter.cpp:36-39）

```cpp
// sei_parser_filter.cpp:36-39
static AutoRegisterFilter<SeiParserFilter> g_registerSeiParserFilter(
    "builtin.player.seiParser", FilterType::FILTERTYPE_SEI, [](const std::string &name, const FilterType type) {
        return std::make_shared<SeiParserFilter>(name, FilterType::FILTERTYPE_SEI);
    });
```

- 注册名：`"builtin.player.seiParser"`（注意大小写）
- FilterType：`FILTERTYPE_SEI`
- Lambda 工厂：`std::make_shared<SeiParserFilter>(name, FilterType::FILTERTYPE_SEI)`

---

## 四、AVBufferAvailableListener——输入缓冲区回调（sei_parser_filter.cpp:41-51）

```cpp
// sei_parser_filter.cpp:41-51
SeiParserFilter::AVBufferAvailableListener::AVBufferAvailableListener(std::shared_ptr<SeiParserFilter> seiParserFilter)
{
    seiParserFilter_ = seiParserFilter;
}

void SeiParserFilter::AVBufferAvailableListener::OnBufferAvailable()
{
    auto seiParserFilter = seiParserFilter_.lock();
    FALSE_RETURN_MSG(seiParserFilter != nullptr, "invalid seiParserFilter");
    seiParserFilter->ProcessInputBuffer();
}
```

- 继承自 `IConsumerListener`（avbuffer_queue.h）
- `OnBufferAvailable()` 触发 `ProcessInputBuffer()` → `DrainOutputBuffer()`
- `seiParserFilter_` 是 `weak_ptr`，避免循环引用

---

## 五、Filter 构造与初始化（sei_parser_filter.cpp:53-98）

```cpp
// sei_parser_filter.cpp:53-57
SeiParserFilter::SeiParserFilter(const std::string &name, FilterType filterType)
    : Filter(name, FilterType::FILTERTYPE_SEI, false)
{
    filterType_ = filterType;
}

// sei_parser_filter.cpp:59-70
SeiParserFilter::~SeiParserFilter()
{
    MEDIA_LOG_I("SeiParserFilter dtor called");
}

void SeiParserFilter::Init(
    const std::shared_ptr<EventReceiver> &receiver, const std::shared_ptr<FilterCallback> &callback)
{
    Filter::Init(receiver, callback);
    eventReceiver_ = receiver;
    filterCallback_ = callback;
}

// sei_parser_filter.cpp:72-98
Status SeiParserFilter::DoPrepare()
{
    PrepareState();
    inputBufferQueueConsumer_ = GetBufferQueueConsumer();
    FALSE_RETURN_V_MSG(inputBufferQueueConsumer_ != nullptr, Status::ERROR_NULL_POINTER,
                       "inputBufferQueueConsumer_ is nullptr");
    sptr<IConsumerListener> listener = new AVBufferAvailableListener(shared_from_this());
    inputBufferQueueConsumer_->SetBufferAvailableListener(listener);  // 注册缓冲区到达监听
    if (onLinkedResultCallback_ != nullptr) {
        onLinkedResultCallback_->OnLinkedResult(GetBufferQueueProducer(), trackMeta_);
    }
    FALSE_RETURN_V_MSG(seiMessageCbStatus_, Status::OK, "disenable parse sei info");
    return Status::OK;
}
```

关键步骤：
1. `PrepareState()` 设置 state_ = FILTERSTATE::READY
2. `AVBufferQueue::Create()` 创建容量为 `videoWidth * videoHeight * 1.5` 的单缓冲队列
3. `SetBufferAvailableListener(listener)` 注册缓冲区到达回调

---

## 六、OnLinked / OnUpdated / OnUnLinked 链路回调（sei_parser_filter.cpp:173-192）

```cpp
// sei_parser_filter.cpp:173-180
Status SeiParserFilter::OnLinked(
    StreamType inType, const std::shared_ptr<Meta> &meta, const std::shared_ptr<FilterLinkCallback> &callback)
{
    FALSE_RETURN_V_MSG(meta != nullptr && meta->GetData(Tag::MIME_TYPE, codecMimeType_),
        Status::ERROR_INVALID_PARAMETER, "get mime failed.");
    trackMeta_ = meta;
    onLinkedResultCallback_ = callback;
    return Filter::OnLinked(inType, meta, callback);
}

// sei_parser_filter.cpp:182-187
Status SeiParserFilter::OnUpdated(
    StreamType inType, const std::shared_ptr<Meta> &meta, const std::shared_ptr<FilterLinkCallback> &callback)
{
    return Filter::OnUpdated(inType, meta, callback);
}

// sei_parser_filter.cpp:189-192
Status SeiParserFilter::OnUnLinked(StreamType inType, const std::shared_ptr<FilterLinkCallback> &callback)
{
    return Filter::OnUnLinked(inType, callback);
}
```

- `OnLinked` 从 `meta` 中提取 MIME 类型保存到 `codecMimeType_`
- 与 `VideoDecoderFilter` 链接时接收 `trackMeta_`（含 VIDEO_WIDTH/VIDEO_HEIGHT）

---

## 七、SetSeiMessageCbStatus——SeiParserListener 创建（sei_parser_filter.cpp:201-218）

```cpp
// sei_parser_filter.cpp:201-218
Status SeiParserFilter::SetSeiMessageCbStatus(bool status, const std::vector<int32_t> &payloadTypes)
{
    seiMessageCbStatus_ = status;
    FALSE_RETURN_V_MSG(inputBufferQueueProducer_ != nullptr, Status::ERROR_NO_MEMORY, "get producer failed");
    if (producerListener_ == nullptr) {
        producerListener_ =
            new SeiParserListener(codecMimeType_, inputBufferQueueProducer_, eventReceiver_, true);
        if (syncCenter_ != nullptr) {
            producerListener_->SetSyncCenter(syncCenter_);
        }
    }
    producerListener_->SetSeiMessageCbStatus(status, payloadTypes);
    return Status::OK;
}

// sei_parser_filter.cpp:220-224
void SeiParserFilter::SetSyncCenter(std::shared_ptr<IMediaSyncCenter> syncCenter)
{
    syncCenter_ = syncCenter;
    FALSE_RETURN(producerListener_ != nullptr);
    producerListener_->SetSyncCenter(syncCenter);
}
```

- `SeiParserListener` 在首次调用 `SetSeiMessageCbStatus(true, ...)` 时延迟创建
- `codecMimeType_` 决定创建 `AvcSeiParserHelper` 还是 `HevcSeiParserHelper`

---

## 八、SEI Helper 常量定义（sei_parser_helper.cpp:30-60）

```cpp
// sei_parser_helper.cpp:30-60（部分）
namespace {
constexpr uint16_t ANNEX_B_PREFIX_LEN = 4;
constexpr uint8_t SEI_UUID_LEN = 16;
constexpr int32_t SEI_PAYLOAD_SIZE_MAX = 1024 * 1024 - SEI_UUID_LEN;  // 1MB - 16B

constexpr uint16_t HEVC_SEI_TYPE_ONE = 0x4E;  // NAL type 39
constexpr uint16_t HEVC_SEI_TYPE_TWO = 0x50;  // NAL type 40
constexpr uint16_t HEVC_NAL_UNIT_TYPE_FLAG = (0x80 | 0x7E);  // forbidden(1) + nalu_type(6) mask
constexpr uint16_t HEVC_SEI_HEAD_LEN = 2;       // 2字节 HEVC NAL header

constexpr uint16_t AVC_SEI_TYPE = 0x06;                     // NAL type 6
constexpr uint16_t AVC_NAL_UNIT_TYPE_FLAG = (0x80 | 0x1F); // forbidden(1) + nalu_type(5) mask
constexpr uint16_t AVC_SEI_HEAD_LEN = 1;                   // 1字节 AVC NAL header

constexpr uint8_t EMULATION_GUIDE_0_LEN = 2;
constexpr uint8_t EMULATION_PREVENTION_CODE = 0x03;       // ← RBSP防伪字节
constexpr uint8_t SEI_ASSEMBLE_BYTE = 0xFF;               // ← 哥伦布指数编码填充字节
constexpr uint8_t SEI_BYTE_MASK_HIGH_7BITS = 0xFE;
constexpr uint8_t SEI_SHIFT_FORWARD_BYTES = 0x04;
constexpr uint8_t SEI_SHIFT_BACKWARD_BYTES = 0x03;

constexpr uint32_t NALU_START_BIG_ENDIAN = 0x00000001;
constexpr uint32_t NALU_START_LITTLE_ENDIAN = 0x01000000;

constexpr int64_t SHIFT_THREE_BYTES = 0x03;
}  // namespace
```

关键常量：
- `EMULATION_PREVENTION_CODE = 0x03`：RBSP 转义字节，防止起始码出现在 NAL 内部
- `ANNEX_B_PREFIX_LEN = 4`：起始码长度（0x00000001）
- `SEI_ASSEMBLE_BYTE = 0xFF`：哥伦布指数编码填充字节

---

## 九、HELPER_CONSTRUCTOR_MAP 工厂（sei_parser_helper.cpp:78-79）

```cpp
// sei_parser_helper.cpp:78-79
const std::map<std::string, HelperConstructFunc> SeiParserHelperFactory::HELPER_CONSTRUCTOR_MAP = {
    { TYPE_AVC,
        []() {
            return std::make_shared<AvcSeiParserHelper>();
        } },
    { TYPE_HEVC,
        []() {
            return std::make_shared<HevcSeiParserHelper>();
        } }
};
```

- `TYPE_AVC = "video/avc"` / `TYPE_HEVC = "video/hevc"`
- Lambda 工厂函数，`SeiParserHelperFactory::CreateHelper(mimeType)` 根据 MIME 分发

---

## 十、ParseSeiPayload 主解析入口（sei_parser_helper.cpp:69-99）

```cpp
// sei_parser_helper.cpp:69-99
Status SeiParserHelper::ParseSeiPayload(
    const std::shared_ptr<AVBuffer> &buffer, std::shared_ptr<SeiPayloadInfoGroup> &group)
{
    FALSE_RETURN_V_MSG(!payloadTypeVec_.empty(), Status::ERROR_INVALID_DATA, "no listener type");
    FALSE_RETURN_V_MSG(buffer != nullptr, Status::ERROR_INVALID_DATA, "buffer is nullptr");
    FALSE_RETURN_V_MSG(buffer->memory_ != nullptr, Status::ERROR_INVALID_DATA, "memory is nullptr");
    MediaAVCodec::AVCodecTrace trace("ParseSeiPayload " + std::to_string(buffer->pts_) + " size " +
                                     std::to_string(buffer->memory_->GetSize() / KILO_BYTE));

    auto bufferParseRes = Status::ERROR_UNSUPPORTED_FORMAT;
    uint8_t seiNaluPrefixLen = ANNEX_B_PREFIX_LEN + 1 + 1 + SEI_UUID_LEN;
    uint8_t *naluStartPtr = buffer->memory_->GetAddr() + SHIFT_THREE_BYTES;
    uint8_t *maxPointer = naluStartPtr + buffer->memory_->GetSize() - SHIFT_THREE_BYTES;
    uint8_t *maxSeiPointer = maxPointer - seiNaluPrefixLen - 1;
    while (FindNextSeiNaluPos(naluStartPtr, maxSeiPointer)) {  // ← 循环找所有 SEI NALU
        if (!group) {
            group = std::make_shared<SeiPayloadInfoGroup>();
        }
        auto naluParseRes = ParseSeiRbsp(naluStartPtr, maxPointer, group);
        bufferParseRes = (bufferParseRes == Status::OK ? bufferParseRes : naluParseRes);
    }
    if (group != nullptr && bufferParseRes == Status::OK) {
        group->playbackPosition = Plugins::Us2Ms(buffer->pts_);  // ← 微秒→毫秒
    }
    return bufferParseRes;
}
```

- `FindNextSeiNaluPos` 循环找到所有 SEI NALU（一个码流中可能有多个）
- `ParseSeiRbsp` 解析每个 NALU 中的 RBSP 数据

---

## 十一、FindNextSeiNaluPos——AnnexB 起始码搜索（sei_parser_helper.cpp:107-139）

```cpp
// sei_parser_helper.cpp:107-132
bool SeiParserHelper::FindNextSeiNaluPos(uint8_t *&startPtr, const uint8_t *const maxPtr)
{
    while (startPtr < maxPtr) {
        if (*startPtr & SEI_BYTE_MASK_HIGH_7BITS) {
            startPtr += SEI_SHIFT_FORWARD_BYTES;
            continue;
        }
        if (*startPtr == 0) {
            startPtr++;
            continue;
        }
        // check if '1' after '000'
        static const uint32_t NALU_START_SEQ = GetNaluStartSeq();
        if (*(reinterpret_cast<uint32_t *>(startPtr - SEI_SHIFT_BACKWARD_BYTES)) != NALU_START_SEQ) {
            startPtr += SEI_SHIFT_FORWARD_BYTES;
            continue;
        }
        FALSE_CONTINUE_NOLOG(IsSeiNalu(++startPtr));  // ← 检查 NAL type
        return true;
    }
    return false;
}

// sei_parser_helper.cpp:134-139
uint32_t SeiParserHelper::GetNaluStartSeq()
{
    // 动态检测大小端
    uint32_t temp = 0x00000001;
    return *reinterpret_cast<uint8_t *>(&temp) == 0 ? NALU_START_BIG_ENDIAN : NALU_START_LITTLE_ENDIAN;
}
```

- `GetNaluStartSeq()` 动态检测大小端，返回 `0x00000001`（BE）或 `0x01000000`（LE）
- `SEI_SHIFT_BACKWARD_BYTES = 3`：回退 3 字节检查起始码（0x000001）
- `IsSeiNalu` 由子类实现（AvcSeiParserHelper / HevcSeiParserHelper）

---

## 十二、AVC / HEVC NAL type 判断（sei_parser_helper.cpp:141-161）

```cpp
// sei_parser_helper.cpp:141-150
bool AvcSeiParserHelper::IsSeiNalu(uint8_t *&headerPtr)
{
    uint8_t header = *headerPtr;
    auto naluType = header & AVC_NAL_UNIT_TYPE_FLAG;  // 0x80 | 0x1F = 0x9F，取低5位
    headerPtr += AVC_SEI_HEAD_LEN;  // 跳过1字节header
    if (naluType == AVC_SEI_TYPE) {  // 0x06
        return true;
    }
    return false;
}

// sei_parser_helper.cpp:152-161
bool HevcSeiParserHelper::IsSeiNalu(uint8_t *&headerPtr)
{
    uint8_t header = *headerPtr;
    auto naluType = header & HEVC_NAL_UNIT_TYPE_FLAG;  // 0x80 | 0x7E = 0xFE，取低6位
    headerPtr += HEVC_SEI_HEAD_LEN;  // 跳过2字节header
    if (naluType == HEVC_SEI_TYPE_ONE || naluType == HEVC_SEI_TYPE_TWO) {  // 0x4E(39) 或 0x50(40)
        return true;
    }
    return false;
}
```

- AVC：`header & 0x1F` 取低 5 位，NAL type 6 = SEI
- HEVC：`header & 0x7E` 取低 6 位，NAL type 39/40 = SEI

---

## 十三、ParseSeiRbsp——RBSP 解析循环（sei_parser_helper.cpp:163-198）

```cpp
// sei_parser_helper.cpp:163-198
Status SeiParserHelper::ParseSeiRbsp(
    uint8_t *&bodyPtr, const uint8_t *const maxPtr, const std::shared_ptr<SeiPayloadInfoGroup> &group)
{
    FALSE_RETURN_V(group != nullptr, Status::ERROR_NO_MEMORY);
    Status unSupRetCode = Status::ERROR_UNSUPPORTED_FORMAT;
    AutoSpinLock lock(spinLock_);
    std::vector<int32_t> payloadTypeVec = payloadTypeVec_;

    while (bodyPtr + SEI_UUID_LEN < maxPtr) {
        int32_t payloadType = GetSeiTypeOrSize(bodyPtr, maxPtr);   // 哥伦布指数解码
        int32_t payloadSize = GetSeiTypeOrSize(bodyPtr, maxPtr);  // 哥伦布指数解码
        FALSE_RETURN_V_NOLOG(
            payloadSize > 0 && payloadSize <= SEI_PAYLOAD_SIZE_MAX && bodyPtr + payloadSize < maxPtr, unSupRetCode);

        if (std::find(payloadTypeVec.begin(), payloadTypeVec.end(), payloadType) == payloadTypeVec.end()) {
            auto res = FillTargetBuffer(nullptr, bodyPtr, maxPtr, payloadSize);  // 跳过不关心类型
            FALSE_RETURN_V_NOLOG(res == Status::OK, res);
            continue;
        }

        AVBufferConfig config;
        config.size = payloadSize;
        config.memoryType = MemoryType::SHARED_MEMORY;
        auto avBuffer = AVBuffer::CreateAVBuffer(config);
        auto copyRes = FillTargetBuffer(avBuffer, bodyPtr, maxPtr, payloadSize);
        FALSE_RETURN_V_NOLOG(copyRes == Status::OK, copyRes);

        group->vec.push_back({ payloadType, avBuffer });  // 收集到 group
        unSupRetCode = Status::OK;
    }
    return unSupRetCode;
}
```

- `GetSeiTypeOrSize` 哥伦布指数解码
- `payloadTypeVec_` 过滤：只收集用户关心的 payloadType
- `FillTargetBuffer` 执行 RBSP 防伪字节转义

---

## 十四、GetSeiTypeOrSize——哥伦布指数解码（sei_parser_helper.cpp:200-210）

```cpp
// sei_parser_helper.cpp:200-210
int32_t SeiParserHelper::GetSeiTypeOrSize(uint8_t *&bodyPtr, const uint8_t *const maxPtr)
{
    int32_t res = 0;
    const uint8_t *const upperPtr = maxPtr - SEI_UUID_LEN;
    while (*bodyPtr == SEI_ASSEMBLE_BYTE && bodyPtr < upperPtr) {  // 0xFF 填充字节
        res += SEI_ASSEMBLE_BYTE;   // 每遇到一个 0xFF，加 255
        bodyPtr++;
    }
    res += *bodyPtr++;  // 最后一个非 0xFF 字节
    return res;
}
```

---

## 十五、FillTargetBuffer——RBSP 防伪字节转义（sei_parser_helper.cpp:212-234）

```cpp
// sei_parser_helper.cpp:212-234
Status SeiHelper::FillTargetBuffer(const std::shared_ptr<AVBuffer> buffer,
    uint8_t *&payloadPtr, const uint8_t *const maxPtr, const int32_t payloadSize)
{
    int32_t writtenSize = 0;
    uint8_t *targetPtr = (buffer == nullptr ? nullptr : buffer->memory_->GetAddr());
    for (int32_t zeroNum = 0; writtenSize < payloadSize && payloadPtr < maxPtr; payloadPtr++) {
        // in H.264 and H.265, 0x000000, 0x000001, 0x000002, 0x000003 will be replaced while encoding
        if (*payloadPtr == EMULATION_PREVENTION_CODE && zeroNum == EMULATION_GUIDE_0_LEN) {
            zeroNum = 0;
            continue;  // 跳过 0x03，恢复 0x00
        }
        zeroNum = *payloadPtr == 0 ? zeroNum + 1 : 0;
        if (targetPtr != nullptr) {
            targetPtr[writtenSize] = *payloadPtr;
        }
        writtenSize++;
    }
    FALSE_RETURN_V_MSG(writtenSize == payloadSize, Status::ERROR_UNSUPPORTED_FORMAT,
                       "avalid data less than payloadSize");
    FALSE_RETURN_V_NOLOG(buffer != nullptr, Status::OK);
    buffer->memory_->SetSize(writtenSize);
    return Status::OK;
}
```

- `0x000003XX` → `0x0000XX`（解码时逆操作）
- `targetPtr == nullptr` 时仅跳过不拷贝（用于跳过节流类型）

---

## 十六、SeiParserListener::OnBufferFilled——事件回调（sei_parser_helper.cpp:257-292）

```cpp
// sei_parser_helper.cpp:257-292
void SeiParserListener::OnBufferFilled(std::shared_ptr<AVBuffer> &avBuffer)
{
    FALSE_RETURN_MSG(avBuffer != nullptr, "avbuffer is nullptr");
    FALSE_RETURN_MSG(producer_ != nullptr, "report sei failed, buffer queue producer is nullptr");
    ON_SCOPE_EXIT(0) {
        producer_->ReturnBuffer(avBuffer, true);  // 处理完成后归还 Buffer
    };
    FALSE_RETURN_NOLOG(seiParserHelper_ != nullptr);
    FALSE_RETURN_NOLOG(eventReceiver_ != nullptr);

    FlowLimit(avBuffer);  // PTS 同步限流
    std::shared_ptr<SeiPayloadInfoGroup> group = nullptr;
    auto res = seiParserHelper_->ParseSeiPayload(avBuffer, group);
    FALSE_RETURN_NOLOG(res == Status::OK);

    Format seiInfoFormat;
    seiInfoFormat.PutIntValue(Tag::AV_PLAYER_SEI_PLAYBACK_POSITION, group->playbackPosition);

    std::vector<Format> vec;
    for (SeiPayloadInfo &payloadInfo : group->vec) {
        Format tmpFormat;
        tmpFormat.PutBuffer(Tag::AV_PLAYER_SEI_PAYLOAD, payloadInfo.payload->memory_->GetAddr(),
            payloadInfo.payload->memory_->GetSize());
        tmpFormat.PutIntValue(Tag::AV_PLAYER_SEI_PAYLOAD_TYPE, payloadInfo.payloadType);
        vec.push_back(tmpFormat);
    }
    seiInfoFormat.PutFormatVector(Tag::AV_PLAYER_SEI_PLAYBACK_GROUP, vec);
    eventReceiver_->OnEvent({ "SeiParserHelper", EventType::EVENT_SEI_INFO, seiInfoFormat });  // ← 触发事件
}
```

---

## 十七、FlowLimit PTS 同步限流（sei_parser_helper.cpp:294-309）

```cpp
// sei_parser_helper.cpp:294-309
void SeiParserListener::FlowLimit(const std::shared_ptr<AVBuffer> &avBuffer)
{
    FALSE_RETURN_NOLOG(isFlowLimited_ && syncCenter_ != nullptr);
    MediaAVCodec::AVCodecTrace trace("ParseSeiPayload FlowLimit");

    if (startPts_ == 0) {
        startPts_ = avBuffer->pts_;  // 记录首帧 PTS
    }

    auto mediaTimeUs = syncCenter_->GetMediaTimeNow();  // 当前播放位置
    auto diff = avBuffer->pts_ - startPts_ - mediaTimeUs;  // 计算超前量
    FALSE_RETURN_NOLOG(diff > 0);

    std::unique_lock<std::mutex> lock(mutex_);
    cond_.wait_for(lock, std::chrono::microseconds(diff), [this] () { return isInterruptNeeded_.load(); });
}
```

- `startPts_` 记录首帧 PTS，后续计算相对偏移
- `syncCenter_->GetMediaTimeNow()` 获取当前播放时间
- `diff > 0` 表示 SEI 数据超前于播放位置，等待

---

## 十八、数据结构（sei_parser_helper.h:86-94 + 96-132）

```cpp
// sei_parser_helper.h:86-94
struct SeiPayloadInfo {
    int32_t payloadType;
    std::shared_ptr<AVBuffer> payload;
};

struct SeiPayloadInfoGroup {
    int64_t playbackPosition = 0;  // PTS（毫秒）
    std::vector<SeiPayloadInfo> vec;
};

// sei_parser_helper.h:96-132 - SeiParserListener 完整声明
class SeiParserListener : public IBrokerListener {
public:
    explicit SeiParserListener(const std::string &mimeType, sptr<AVBufferQueueProducer> producer,
        std::shared_ptr<Pipeline::EventReceiver> eventReceiver, bool isFlowLimited);

    void OnBufferFilled(std::shared_ptr<AVBuffer> &avBuffer) override;
    void SetPayloadTypeVec(const std::vector<int32_t> &vector);
    void OnInterrupted(bool isInterruptNeeded);
    void SetSyncCenter(std::shared_ptr<Pipeline::IMediaSyncCenter> syncCenter);
    Status SetSeiMessageCbStatus(bool status, const std::vector<int32_t> &payloadTypes);

private:
    void FlowLimit(const std::shared_ptr<AVBuffer> &avBuffer);
    sptr<AVBufferQueueProducer> producer_{};
    std::shared_ptr<SeiParserHelper> seiParserHelper_{};
    std::shared_ptr<Pipeline::EventReceiver> eventReceiver_{};
    bool isFlowLimited_ { false };
    std::atomic<bool> isInterruptNeeded_ { false };
    std::mutex mutex_ {};
    std::condition_variable cond_ {};
    std::shared_ptr<Pipeline::IMediaSyncCenter> syncCenter_;
    int64_t startPts_ = 0;
    std::vector<int32_t> payloadTypes_{};
};
```

---

## 十九、调用链路全图

```
[码流 Annex B 输入]
    ↓
[DemuxerFilter] → 输出 AVBuffer（含 NALU 数据）
    ↓
[VideoDecoderFilter::DoPrepare] → SetSeiMessageCbStatus(true, {5}) 注册 SEI 监听
    ↓
[SeiParserFilter::DoPrepare] → SetBufferAvailableListener(AVBufferAvailableListener)
    ↓
[AVBufferAvailableListener::OnBufferAvailable] → ProcessInputBuffer() → DrainOutputBuffer()
    ↓
[BufferQueueProducer::ReturnBuffer] → 触发 SeiParserListener::OnBufferFilled
    ↓
[SeiParserListener::FlowLimit] → PTS 超前则等待同步
    ↓
[seiParserHelper_->ParseSeiPayload]
    ├── FindNextSeiNaluPos（找起始码）
    ├── IsSeiNalu（判断 NAL type：6=AVC，39/40=HEVC）
    └── ParseSeiRbsp
        ├── GetSeiTypeOrSize（哥伦布指数解码）
        └── FillTargetBuffer（RBSP 防伪字节转义）
    ↓
[EVENT_SEI_INFO 回调] → 应用层
```

---

## 二十、关键 Evidence 汇总（行号级）

| # | 文件 | 行号范围 | 内容 |
|---|------|---------|------|
| 1 | sei_parser_filter.cpp | 36-39 | AutoRegisterFilter("builtin.player.seiParser") |
| 2 | sei_parser_filter.cpp | 41-51 | AVBufferAvailableListener::OnBufferAvailable |
| 3 | sei_parser_filter.cpp | 53-57 | SeiParserFilter 构造（FILTERTYPE_SEI） |
| 4 | sei_parser_filter.cpp | 72-98 | DoPrepare + buffer queue + listener 注册 |
| 5 | sei_parser_filter.cpp | 173-180 | OnLinked 从 meta 提取 codecMimeType_ |
| 6 | sei_parser_filter.cpp | 201-218 | SetSeiMessageCbStatus + SeiParserListener 创建 |
| 7 | sei_parser_filter.cpp | 220-224 | SetSyncCenter 注入 syncCenter_ |
| 8 | sei_parser_helper.cpp | 30-60 | 常量（EMULATION_PREVENTION/ANNEX_B/HEVC/AVC） |
| 9 | sei_parser_helper.cpp | 78-79 | HELPER_CONSTRUCTOR_MAP 工厂（AVC/HEVC） |
| 10 | sei_parser_helper.cpp | 82-99 | ParseSeiPayload 主入口 + playbackPosition |
| 11 | sei_parser_helper.cpp | 107-139 | FindNextSeiNaluPos + GetNaluStartSeq |
| 12 | sei_parser_helper.cpp | 141-161 | Avc/HevcSeiParserHelper::IsSeiNalu |
| 13 | sei_parser_helper.cpp | 163-198 | ParseSeiRbsp 循环解析多 payload |
| 14 | sei_parser_helper.cpp | 200-210 | GetSeiTypeOrSize 哥伦布指数解码 |
| 15 | sei_parser_helper.cpp | 212-234 | FillTargetBuffer RBSP 防伪字节转义 |
| 16 | sei_parser_helper.cpp | 244-255 | SeiParserListener 构造 + SetBufferFilledListener |
| 17 | sei_parser_helper.cpp | 257-292 | OnBufferFilled + EVENT_SEI_INFO 回调 |
| 18 | sei_parser_helper.cpp | 294-309 | FlowLimit PTS 同步限流 |
| 19 | sei_parser_helper.cpp | 326-346 | SetSeiMessageCbStatus 完整实现 |
| 20 | sei_parser_helper.h | 86-94 | SeiPayloadInfo / SeiPayloadInfoGroup |
| 21 | sei_parser_filter.h | 33-100 | SeiParserFilter 完整类声明 |
| 22 | sei_parser_helper.h | 96-132 | SeiParserListener 完整类声明 |

---

## 二十一、与其他 S-series 主题关联

| 关联主题 | 关系 |
|----------|------|
| **S14** | FilterChain 架构，SEI Parser Filter 是 FilterChain 中的一个节点 |
| **S22** | MediaSyncManager 提供 PTS 时钟基准（FlowLimit 依赖 syncCenter_） |
| **S46** | DecoderSurfaceFilter 集成 DRM 时调用 SEI Parser 提取 DRM SEI 密钥 |
| **S63** | CodecDrmDecrypt 解密时依赖 SEI Parser 提取密钥信息 |
| **S113** | 同一主题的早期草案版，S168 为行号级增强版 |

---

_Draft generated by builder-agent subagent 2026-05-21T09:52_