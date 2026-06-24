# MEM-ARCH-AVCODEC-S113: SeiParserFilter 与 SeiParserHelper SEI信息解析框架

## 元信息

| 字段 | 值 |
|------|-----|
| mem_id | MEM-ARCH-AVCODEC-S113 |
| 主题 | SeiParserFilter 与 SeiParserHelper SEI信息解析框架 |
| status | pending_approval |
| created | 2026-06-25 |
| 来源 | 本地源码镜像 /home/west/av_codec_repo |
| evidence_count | 23 (verified 2026-06-25 local mirror) |

## 架构概述

SEI（Supplemental Enhancement Information）解析框架分为两层：

1. **Filter 层**（SeiParserFilter）：负责与 Pipeline 对接、管理 BufferQueue、接收原始码流
2. **解析层**（SeiParserHelper/SeiParserListener）：负责在 Buffer 填充时触发解析、识别 AnnexB NALu 边界、反仿射字节剔除、组帧并向上游发事件

关键设计决策：
- **双格式支持**：AnnexB（StartCode 0x00000001）+ NaluHeader 格式，支持 AVC/HEVC 两种编码格式
- **工厂模式**：SeiParserHelperFactory 根据 MimeType 创建 AvcSeiParserHelper 或 HevcSeiParserHelper
- **回调驱动**：SeiParserListener 作为 IBrokerListener 挂载在 AVBufferQueueProducer 上，Buffer 填充时自动触发 OnBufferFilled
- **FlowLimit**：通过 SyncCenter 同步播放时间戳，防止 SEI 解析过快导致上层压力

---

## 组件图

```
Pipeline
  │
  ▼
SeiParserFilter (FILTERTYPE_SEI)
  ├─ AVBufferQueueProducer (input) ← 上游 Filter 填充
  ├─ AVBufferQueueConsumer (self) → ProcessInputBuffer
  └─ SeiParserListener (成员)
        │
        ├─ seiParserHelper_ (AvcSeiParserHelper | HevcSeiParserHelper)
        │     ├─ FindNextSeiNaluPos()    ← 扫描 AnnexB startcode
        │     ├─ IsSeiNalu()              ← AVC/HEVC NALu type 识别
        │     ├─ ParseSeiRbsp()           ← 解析 SEI RBSP payload
        │     └─ FillTargetBuffer()       ← 反仿射字节剔除
        │
        └─ eventReceiver_->OnEvent()     ← 向上游发 EVENT_SEI_INFO
```

---

## Evidence 清单（行号级）

### Evidence 1 — 工厂注册：AVC/HEVC 解析器构造函数映射
**文件**: `sei_parser_helper.cpp`
**行号**: 63-69
```cpp
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
**说明**: 工厂模式根据 MimeType 创建对应解析器实例，`TYPE_AVC="video/avc"`，`TYPE_HEVC="video/hevc"`（第 21-22 行常量定义）。

---

### Evidence 2 — Filter 自动注册
**文件**: `sei_parser_filter.cpp`
**行号**: 36-38
```cpp
static AutoRegisterFilter<SeiParserFilter> g_registerSeiParserFilter(
    "builtin.player.seiParser", FilterType::FILTERTYPE_SEI, [](const std::string &name, const FilterType type) {
        return std::make_shared<SeiParserFilter>(name, FilterType::FILTERTYPE_SEI);
    });
```
**说明**: Filter 通过 AutoRegisterFilter 机制自动注册到 Pipeline，`FilterType::FILTERTYPE_SEI` 标识 SEI 解析 Filter。

---

### Evidence 3 — Buffer 消费监听器：OnBufferAvailable 触发 ProcessInputBuffer
**文件**: `sei_parser_filter.cpp`
**行号**: 40-52
```cpp
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
**说明**: IConsumerListener 实现，Buffer 可用时自动触发 ProcessInputBuffer，将 Buffer 消费出队。

---

### Evidence 4 — DoPrepare 中设置 BufferAvailableListener
**文件**: `sei_parser_filter.cpp`
**行号**: 86-87
```cpp
sptr<IConsumerListener> listener = new AVBufferAvailableListener(shared_from_this());
inputBufferQueueConsumer_->SetBufferAvailableListener(listener);
```
**说明**: 在 Filter 的 DoPrepare 阶段，将 AVBufferAvailableListener 绑定到 Consumer，Consumer 侧 Buffer 可用时通知 Filter 消费。

---

### Evidence 5 — 开启 SEI 回调时创建 SeiParserListener
**文件**: `sei_parser_filter.cpp`
**行号**: 207-211
```cpp
if (producerListener_ == nullptr) {
    producerListener_ =
        new SeiParserListener(codecMimeType_, inputBufferQueueProducer_, eventReceiver_, true);
    FALSE_RETURN_V_MSG(
        producerListener_ != nullptr, Status::ERROR_NO_MEMORY, "sei listener create failed");
    if (syncCenter_ != nullptr) {
        producerListener_->SetSyncCenter(syncCenter_);
    } else {
        MEDIA_LOG_W("syncCenter_ is nullptr");
    }
}
```
**说明**: SetSeiMessageCbStatus(true) 时才创建 SeiParserListener，构造时传入 codecMimeType、producer、eventReceiver，后续通过 SetSyncCenter 注入同步中心。

---

### Evidence 6 — SeiParserListener 构造时创建对应 MimeType 的解析器
**文件**: `sei_parser_helper.cpp`
**行号**: 244-250
```cpp
SeiParserListener::SeiParserListener(const std::string &mimeType, sptr<AVBufferQueueProducer> producer,
    std::shared_ptr<Pipeline::EventReceiver> eventReceiver, bool isFlowLimited)
    : producer_(producer),
      eventReceiver_(eventReceiver),
      isFlowLimited_(isFlowLimited)
{
    seiParserHelper_ = SeiParserHelperFactory::CreateHelper(mimeType);
    FALSE_RETURN_MSG(seiParserHelper_ != nullptr, "Create SeiParserHelper failed for %{public}s", mimeType.c_str());
```
**说明**: Listener 构造时立即调用工厂创建对应 MimeType 的 Helper，后续 OnBufferFilled 直接使用。

---

### Evidence 7 — OnBufferFilled：Buffer 填充时触发解析主流程
**文件**: `sei_parser_helper.cpp`
**行号**: 257-279
```cpp
void SeiParserListener::OnBufferFilled(std::shared_ptr<AVBuffer> &avBuffer)
{
    FALSE_RETURN_MSG(avBuffer != nullptr, "avbuffer is nullptr");
    FALSE_RETURN_MSG(producer_ != nullptr, "report sei failed, buffer queue producer is nullptr");
    ON_SCOPE_EXIT(0)
    {
        producer_->ReturnBuffer(avBuffer, true);
    };
    FALSE_RETURN_NOLOG(seiParserHelper_ != nullptr);
    FALSE_RETURN_NOLOG(eventReceiver_ != nullptr);

    FlowLimit(avBuffer);
    std::shared_ptr<SeiPayloadInfoGroup> group = nullptr;
    auto res = seiParserHelper_->ParseSeiPayload(avBuffer, group);
    FALSE_RETURN_NOLOG(res == Status::OK);
    // ... 构造 Format 并通过 eventReceiver_->OnEvent 发送
    eventReceiver_->OnEvent({ "SeiParserHelper", EventType::EVENT_SEI_INFO, seiInfoFormat });
}
```
**说明**: IBrokerListener::OnBufferFilled 实现；Buffer 填充后先 FlowLimit 限速，再调用 Helper::ParseSeiPayload，解析成功后构造 Format 通过 EventReceiver 向上发事件。

---

### Evidence 8 — FlowLimit：根据 PTS 与 SyncCenter 限速
**文件**: `sei_parser_helper.cpp`
**行号**: 294-306
```cpp
void SeiParserListener::FlowLimit(const std::shared_ptr<AVBuffer> &avBuffer)
{
    FALSE_RETURN_NOLOG(isFlowLimited_ && syncCenter_ != nullptr);
    MediaAVCodec::AVCodecTrace trace("ParseSeiPayload FlowLimit");

    if (startPts_ == 0) {
        startPts_ = avBuffer->pts_;
    }

    auto mediaTimeUs = syncCenter_->GetMediaTimeNow();
    auto diff = avBuffer->pts_ - startPts_ - mediaTimeUs;
    FALSE_RETURN_NOLOG(diff > 0);

    std::unique_lock<std::mutex> lock(mutex_);
    cond_.wait_for(lock, std::chrono::microseconds(diff), [this] () { return isInterruptNeeded_.load(); });
}
```
**说明**: 通过计算当前 Buffer PTS 与播放头的差值，用条件变量等待对应时长，防止 SEI 解析过快。

---

### Evidence 9 — FindNextSeiNaluPos：扫描 AnnexB StartCode
**文件**: `sei_parser_helper.cpp`
**行号**: 107-128
```cpp
bool SeiParserHelper::FindNextSeiNaluPos(uint8_t *&startPtr, const uint8_t *const maxPtr)
{
    while (startPtr < maxPtr) {
        if (*startPtr & SEI_BYTE_MASK_HIGH_7BITS) {
            startPtr += SEI_SHIFT_FORWARD_BYTES;  // 跳过非 0/1 字节
            continue;
        }
        if (*startPtr == 0) {
            startPtr++;  // 跳过 0 字节
            continue;
        }
        static const uint32_t NALU_START_SEQ = GetNaluStartSeq();
        if (*(reinterpret_cast<uint32_t *>(startPtr - SEI_SHIFT_BACKWARD_BYTES)) != NALU_START_SEQ) {
            startPtr += SEI_SHIFT_FORWARD_BYTES;
            continue;
        }
        FALSE_CONTINUE_NOLOG(IsSeiNalu(++startPtr));
        return true;
    }
    return false;
}
```
**说明**: 在 AnnexB 格式中，NALu 以 0x00000001 或 0x000001 开头；本函数扫描字节流找到下一个 StartCode，再由 IsSeiNalu 判断是否为 SEI NALu。

---

### Evidence 10 — GetNaluStartSeq：跨平台 StartCode 字节序处理
**文件**: `sei_parser_helper.cpp`
**行号**: 134-138
```cpp
uint32_t SeiParserHelper::GetNaluStartSeq()
{
    uint32_t temp = 0x00000001;
    return *reinterpret_cast<uint8_t *>(&temp) == 0 ? NALU_START_BIG_ENDIAN : NALU_START_LITTLE_ENDIAN;
}
```
**说明**: 小端序机器上 `0x00000001` 低地址存低字节（0x01），大端序相反；据此动态选择 NALU_START_BIG_ENDIAN（0x00000001）或 NALU_START_LITTLE_ENDIAN（0x01000000）。

---

### Evidence 11 — AvcSeiParserHelper::IsSeiNalu：AVC SEI 类型识别
**文件**: `sei_parser_helper.cpp`
**行号**: 141-151
```cpp
bool AvcSeiParserHelper::IsSeiNalu(uint8_t *&headerPtr)
{
    uint8_t header = *headerPtr;
    auto naluType = header & AVC_NAL_UNIT_TYPE_FLAG;  // forbidden_bit(0x80) | nalu_type(0x1F)
    headerPtr += AVC_SEI_HEAD_LEN;  // 1 byte
    if (naluType == AVC_SEI_TYPE) {  // 0x06
        return true;
    }
    return false;
}
```
**说明**: AVC SEI NALu type = 6（`AVC_SEI_TYPE = 0x06`），通过 `header & 0x9F`（`AVC_NAL_UNIT_TYPE_FLAG`）提取 nalu_type 判断。

---

### Evidence 12 — HevcSeiParserHelper::IsSeiNalu：HEVC SEI 类型识别
**文件**: `sei_parser_helper.cpp`
**行号**: 152-159
```cpp
bool HevcSeiParserHelper::IsSeiNalu(uint8_t *&headerPtr)
{
    uint8_t header = *headerPtr;
    auto naluType = header & HEVC_NAL_UNIT_TYPE_FLAG;  // forbidden_bit(0x80) | nalu_type(0x7E)
    headerPtr += HEVC_SEI_HEAD_LEN;  // 2 bytes
    if (naluType == HEVC_SEI_TYPE_ONE || naluType == HEVC_SEI_TYPE_TWO) {  // 0x4E or 0x50
        return true;
    }
    return false;
}
```
**说明**: HEVC SEI NALu type = 39 或 40（`HEVC_SEI_TYPE_ONE = 0x4E`，`HEVC_SEI_TYPE_TWO = 0x50`），header 后移 2 字节。

---

### Evidence 13 — ParseSeiPayload：多 SEI NALu 解析主循环
**文件**: `sei_parser_helper.cpp`
**行号**: 74-93
```cpp
Status SeiParserHelper::ParseSeiPayload(
    const std::shared_ptr<AVBuffer> &buffer, std::shared_ptr<SeiPayloadInfoGroup> &group)
{
    FALSE_RETURN_V_MSG(!payloadTypeVec_.empty(), Status::ERROR_INVALID_DATA, "no listener type");
    FALSE_RETURN_V_MSG(buffer != nullptr, Status::ERROR_INVALID_DATA, "buffer is nullptr");
    MediaAVCodec::AVCodecTrace trace("ParseSeiPayload " + std::to_string(buffer->pts_) + " size " + ...);

    auto bufferParseRes = Status::ERROR_UNSUPPORTED_FORMAT;
    uint8_t seiNaluPrefixLen = ANNEX_B_PREFIX_LEN + 1 + 1 + SEI_UUID_LEN;  // 4+1+1+16 = 22
    uint8_t *naluStartPtr = buffer->memory_->GetAddr() + SHIFT_THREE_BYTES;  // 跳过前3字节 (0x00 0x00 0x00/0x01)
    ...
    while (FindNextSeiNaluPos(naluStartPtr, maxSeiPointer)) {
        if (!group) {
            group = std::make_shared<SeiPayloadInfoGroup>();
        }
        auto naluParseRes = ParseSeiRbsp(naluStartPtr, maxPointer, group);
        bufferParseRes = (bufferParseRes == Status::OK ? bufferParseRes : naluParseRes);
    }
    if (group != nullptr && bufferParseRes == Status::OK) {
        group->playbackPosition = Plugins::Us2Ms(buffer->pts_);
    }
    return bufferParseRes;
}
```
**说明**: 核心解析循环，在每个 Buffer 内找到所有 SEI NALu，调用 ParseSeiRbsp 解析其 RBSP body。

---

### Evidence 14 — ParseSeiRbsp：SEI RBSP body 解析（带锁保护）
**文件**: `sei_parser_helper.cpp`
**行号**: 163-193
```cpp
Status SeiParserHelper::ParseSeiRbsp(
    uint8_t *&bodyPtr, const uint8_t *const maxPtr, const std::shared_ptr<SeiPayloadInfoGroup> &group)
{
    FALSE_RETURN_V(group != nullptr, Status::ERROR_NO_MEMORY);
    Status unSupRetCode = Status::ERROR_UNSUPPORTED_FORMAT;
    AutoSpinLock lock(spinLock_);  // ← 线程安全保护
    std::vector<int32_t> payloadTypeVec = payloadTypeVec_;

    while (bodyPtr + SEI_UUID_LEN < maxPtr) {
        int32_t payloadType = GetSeiTypeOrSize(bodyPtr, maxPtr);
        int32_t payloadSize = GetSeiTypeOrSize(bodyPtr, maxPtr);
        // ... 过滤 payloadTypeVec 中未注册的类型
        group->vec.push_back({ payloadType, avBuffer });
        unSupRetCode = Status::OK;
    }
    return unSupRetCode;
}
```
**说明**: AutoSpinLock 保护下读取成员变量 payloadTypeVec；一个 SEI NALu 可包含多个 SEI message（循环解析）；未注册类型也会消费但不组帧。

---

### Evidence 15 — GetSeiTypeOrSize：SEI type/size 可变长编码
**文件**: `sei_parser_helper.cpp`
**行号**: 200-207
```cpp
int32_t SeiParserHelper::GetSeiTypeOrSize(uint8_t *&bodyPtr, const uint8_t *const maxPtr)
{
    int32_t res = 0;
    const uint8_t *const upperPtr = maxPtr - SEI_UUID_LEN;
    while (*bodyPtr == SEI_ASSEMBLE_BYTE && bodyPtr < upperPtr) {  // SEI_ASSEMBLE_BYTE = 0xFF
        res += SEI_ASSEMBLE_BYTE;
        bodyPtr++;
    }
    res += *bodyPtr++;
    return res;
}
```
**说明**: SEI payload type/size 使用 0xFF 链式编码（每个 0xFF 表示加 255），最后一个字节为余数。

---

### Evidence 16 — FillTargetBuffer：反仿射字节剔除
**文件**: `sei_parser_helper.cpp`
**行号**: 212-229
```cpp
Status SeiParserHelper::FillTargetBuffer(const std::shared_ptr<AVBuffer> buffer,
    uint8_t *&payloadPtr, const uint8_t *const maxPtr, const int32_t payloadSize)
{
    int32_t writtenSize = 0;
    uint8_t *targetPtr = (buffer == nullptr ? nullptr : buffer->memory_->GetAddr());
    for (int32_t zeroNum = 0; writtenSize < payloadSize && payloadPtr < maxPtr; payloadPtr++) {
        // in H.264 and H.265, 0x000000, 0x000001, 0x000002, 0x000003 will be replaced while encoding
        if (*payloadPtr == EMULATION_PREVENTION_CODE && zeroNum == EMULATION_GUIDE_0_LEN) {
            zeroNum = 0;
            continue;  // ← 跳过 0x03 反仿射字节
        }
        zeroNum = *payloadPtr == 0 ? zeroNum + 1 : 0;
        if (targetPtr != nullptr) {
            targetPtr[writtenSize] = *payloadPtr;
        }
        writtenSize++;
    }
    ...
}
```
**说明**: H.264/H.265 编码时在 NALu body 中插入 0x03 反仿射字节以避免 startcode；本函数在解析时还原。

---

### Evidence 17 — SetSeiMessageCbStatus：SEI 回调使能/禁能控制
**文件**: `sei_parser_helper.cpp`
**行号**: 326-342
```cpp
Status SeiParserListener::SetSeiMessageCbStatus(
    bool status, const std::vector<int32_t> &payloadTypes)
{
    MEDIA_LOG_I("seiMessageCbStatus_  = " PUBLIC_LOG_D32, status);
    if (status) {
        payloadTypes_ = payloadTypes;
        SetPayloadTypeVec(payloadTypes_);
        return Status::OK;
    }
    if (payloadTypes.empty()) {
        payloadTypes_ = {};
        SetPayloadTypeVec(payloadTypes_);
        return Status::OK;
    }
    payloadTypes_.erase(
        std::remove_if(payloadTypes_.begin(), payloadTypes_.end(), [&payloadTypes](int value) {
            return std::find(payloadTypes.begin(), payloadTypes.end(), value) != payloadTypes.end();
        }), payloadTypes_.end());
    SetPayloadTypeVec(payloadTypes_);
    return Status::OK;
}
```
**说明**: status=true 时完全替换注册类型；status=false 且 payloadTypes 空时清空；status=false 带参数时从已有列表中移除指定类型。

---

### Evidence 18 — InputBufferQueue 容量计算（基于视频分辨率）
**文件**: `sei_parser_filter.cpp`
**行号**: 115-120
```cpp
int32_t videoHeight = 0;
int32_t videoWidth = 0;
auto metaRes = trackMeta_->Get<Tag::VIDEO_HEIGHT>(videoHeight) && trackMeta_->Get<Tag::VIDEO_WIDTH>(videoWidth);
int32_t capacity = metaRes ? videoWidth * videoHeight * VIDEO_CAPACITY_RATE : DEFAULT_BUFFER_CAPACITY;
if (capacity <= 0 || capacity > INT32_MAX) {
    capacity = DEFAULT_BUFFER_CAPACITY;
}
```
**说明**: Buffer 容量 = 视频宽×高×1.5（VIDEO_CAPACITY_RATE），默认 1MB；避免大分辨率视频 Buffer 不够，小分辨率浪费。

---

### Evidence 19 — 输入 Buffer 队列创建与 Attach
**文件**: `sei_parser_filter.cpp`
**行号**: 126-141
```cpp
int32_t inputBufferNum = 1;
if (inputBufferQueue_ == nullptr) {
    inputBufferQueue_ = AVBufferQueue::Create(inputBufferNum, memoryType, INPUT_BUFFER_QUEUE_NAME);
}
FALSE_RETURN_V_MSG_E(inputBufferQueue_ != nullptr, Status::ERROR_UNKNOWN, "inputBufferQueue_ is nullptr");
inputBufferQueueProducer_ = inputBufferQueue_->GetProducer();
FALSE_RETURN_V_MSG_E(
    inputBufferQueueProducer_ != nullptr, Status::ERROR_UNKNOWN, "inputBufferQueueProducer_ is nullptr");
inputBufferQueueConsumer_ = inputBufferQueue_->GetConsumer();

for (int i = 0; i < inputBufferNum; i++) {
    std::shared_ptr<AVAllocator> avAllocator;
    avAllocator = AVAllocatorFactory::CreateVirtualAllocator();
    std::shared_ptr<AVBuffer> inputBuffer = AVBuffer::CreateAVBuffer(avAllocator, capacity);
    inputBufferQueueProducer_->AttachBuffer(inputBuffer, false);
}
```
**说明**: 创建容量为 1 的 AVBufferQueue，分别获取 Producer 和 Consumer；Producer 由上游 Filter 持有填充 Buffer，Consumer 由 SeiParserFilter 持有消费 Buffer。

---

### Evidence 20 — 内存上报 DfxEvent
**文件**: `sei_parser_filter.cpp`
**行号**: 146-147
```cpp
FALSE_RETURN_V_NOLOG(eventReceiver_ != nullptr, Status::OK);
eventReceiver_->OnMemoryUsageEvent({"SEI_BQ",
    DfxEventType::DFX_INFO_MEMORY_USAGE, inputBufferQueue_->GetMemoryUsage()});
```
**说明**: 在 Prepare 完成后通过 OnMemoryUsageEvent 上报 SEI BufferQueue 内存使用量，类型标记为 "SEI_BQ"。

---

### Evidence 21 — 数据结构：SeiPayloadInfo / SeiPayloadInfoGroup
**文件**: `sei_parser_helper.h`（interfaces/inner_api/native/）
**行号**: 86-93
```cpp
struct SeiPayloadInfo {
    int32_t payloadType;
    std::shared_ptr<AVBuffer> payload;
};

struct SeiPayloadInfoGroup {
    int64_t playbackPosition = 0;
    std::vector<SeiPayloadInfo> vec;
};
```
**说明**: SeiPayloadInfo 保存单个 SEI payload 的类型和内容；SeiPayloadInfoGroup 保存一帧所有 SEI payload 及对应的播放时间位置。

---

### Evidence 22 — OnEvent 发送 EVENT_SEI_INFO
**文件**: `sei_parser_helper.cpp`
**行号**: 290-291
```cpp
seiInfoFormat.PutFormatVector(Tag::AV_PLAYER_SEI_PLAYBACK_GROUP, vec);
eventReceiver_->OnEvent({ "SeiParserHelper", EventType::EVENT_SEI_INFO, seiInfoFormat });
```
**说明**: 解析完成后构造 Format 对象，通过 Tag::AV_PLAYER_SEI_PLAYBACK_GROUP 放入 payload 数组，Tag::AV_PLAYER_SEI_PLAYBACK_POSITION 放入 PTS，Tag::AV_PLAYER_SEI_PAYLOAD_TYPE 放入各 payload 类型，最终通过 EventReceiver 向上游发送 EVENT_SEI_INFO 事件。

---

### Evidence 23 — SetPayloadTypeVec：Helper 层 payload 类型过滤
**文件**: `sei_parser_helper.cpp`
**行号**: 101-103
```cpp
void SeiParserHelper::SetPayloadTypeVec(const std::vector<int32_t> &vector)
{
    AutoSpinLock lock(spinLock_);
    payloadTypeVec_ = vector;
}
```
**说明**: Filter 层通过 SetSeiMessageCbStatus → SetPayloadTypeVec → seiParserHelper_->SetPayloadTypeVec 将用户关心的 payloadType 注册到解析器；解析时未注册类型会被跳过（但不阻断解析流程）。

---

## 关键设计模式

| 模式 | 体现 |
|------|------|
| 工厂模式 | `SeiParserHelperFactory::CreateHelper(mimeType)` 根据 MimeType 创建 AvcSeiParserHelper / HevcSeiParserHelper |
| 策略模式 | AvcSeiParserHelper / HevcSeiParserHelper 各自实现 IsSeiNalu，对同一接口提供不同实现 |
| 模板方法 | SeiParserHelper::ParseSeiPayload 调用纯虚 IsSeiNalu，子类提供实现 |
| 观察者/回调 | IBrokerListener::OnBufferFilled 在 Buffer 填充时自动触发 |
| RAII Scope Exit | ON_SCOPE_EXIT(0) { producer_->ReturnBuffer(avBuffer, true); } 确保 Buffer 归还 |
| 限流器 | FlowLimit + SyncCenter + condition_variable 防止 SEI 解析过快 |

---

## 线程安全说明

- `SeiParserHelper::spinLock_`（AutoSpinLock）保护 `payloadTypeVec_` 的读写
- `SeiParserListener` 的 FlowLimit 使用 `std::mutex` + `std::condition_variable`
- `std::atomic<bool> isInterruptNeeded_` 用于中断信号跨线程通信

---

## 状态：pending_approval

## 本地镜像验证记录（2026-06-25）
| 字段 | 值 |
|------|-----|
| 验证时间 | 2026-06-25 07:25 |
| 本地镜像 | /home/west/av_codec_repo |
| 验证文件 | sei_parser_filter.cpp (235行) + sei_parser_helper.cpp (347行) + sei_parser_helper.h (interfaces/inner_api/native/, 134行) |
| Evidence 修正 | E1 44→63 / E2 33→36 / E4 71→86 / E5 189→207 / E6 177→244 / E7 185→257 / E8 226→294 / E9 71→107 / E10 94→134 / E11 100→141 / E12 110→152 / E13 51→74 / E14 119→163 / E15 147→200 / E16 157→212 / E17 245→326 / E18 98→115 / E19 106→126 / E20 124→146 / E21 70→86(header) / E22 221→290 / E23 56→101 |
| 状态 | pending_approval（行号已验证，builder-agent 2026-06-25） |
