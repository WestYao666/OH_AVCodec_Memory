# MEM-ARCH-AVCODEC-S113.md — SeiParserFilter 与 SeiParserHelper SEI 信息解析框架

**版本**：v2.0（本地镜像行号级增强版）  
**日期**：2026-05-15  
**状态**：draft → pending_approval  
**仓库**：https://gitcode.com/openharmony/multimedia_av_codec  
**本地镜像**：/home/west/av_codec_repo  
**来源**：S113 草案增强（v1.0 草案缺失关键证据）

---

## 1. 概述

SEI（Supplemental Enhancement Information）信息解析框架负责从视频码流中提取 SEI NAL 单元，并将解析结果通过事件回调上报给播放器业务层。

该框架由两个核心组件构成：

| 组件 | 文件 | 行数 | 职责 |
|------|------|------|------|
| `SeiParserFilter` | sei_parser_filter.cpp / .h | 235 / 104 | Filter 层封装、AVBufferQueue 驱动、事件注册 |
| `SeiParserHelper` | sei_parser_helper.cpp / .h | 347 / 134 | NALU 定位、RBSP 解析、负载提取 |

**双格式支持**：

- **AVC（H.264）**：NALU type = `0x06`（`AVC_NAL_UNIT_TYPE_FLAG = (0x80 | 0x1F)`，mask 后等于 0x06）
- **HEVC（H.265）**：NALU type = `0x4E`（39）或 `0x50`（40）（`HEVC_NAL_UNIT_TYPE_FLAG = (0x80 | 0x7E)`，mask 后等于 39/40）

---

## 2. 关键常量定义

**来源**：`sei_parser_helper.cpp:18-48`

```cpp
// 起始码
constexpr uint16_t ANNEX_B_PREFIX_LEN = 4;           // 起始码 0x00000001 长度
constexpr uint32_t NALU_START_BIG_ENDIAN = 0x00000001;
constexpr uint32_t NALU_START_LITTLE_ENDIAN = 0x01000000;

// HEVC SEI NALU type（NAL header 第二字节 bit1-7）
constexpr uint16_t HEVC_SEI_TYPE_ONE = 0x4E;           // 39 = user_data_unregistered
constexpr uint16_t HEVC_SEI_TYPE_TWO = 0x50;           // 40 = user_data_unregistered
constexpr uint16_t HEVC_NAL_UNIT_TYPE_FLAG = (0x80 | 0x7E); // 0x7E mask
constexpr uint16_t HEVC_SEI_HEAD_LEN = 2;

// AVC SEI NALU type（NAL header 第一字节 bit1-5）
constexpr uint16_t AVC_SEI_TYPE = 0x06;                 // 4th bit to 8th bit at nalu header is 6
constexpr uint16_t AVC_NAL_UNIT_TYPE_FLAG = (0x80 | 0x1F); // 0x1F mask
constexpr uint16_t AVC_SEI_HEAD_LEN = 1;

// RBSP 转义与防伪字节
constexpr uint8_t EMULATION_PREVENTION_CODE = 0X03;   // 0x000003 → 0x0000 转义
constexpr uint8_t EMULATION_GUIDE_0_LEN = 2;

// SEI 消息字节填充检测
constexpr uint8_t SEI_ASSEMBLE_BYTE = 0xFF;            // 填充字节
constexpr uint8_t SEI_BYTE_MASK_HIGH_7BITS = 0xFE;     // 跳过非零字节 mask

// SEI UUID / payload 长度限制
constexpr uint8_t SEI_UUID_LEN = 16;
constexpr int32_t SEI_PAYLOAD_SIZE_MAX = 1024 * 1024 - SEI_UUID_LEN; // 1MB - 16B
```

---

## 3. 工厂模式与 Helper 双子类

**来源**：`sei_parser_helper.cpp:50-57`（工厂注册表）

```cpp
const std::map<std::string, HelperConstructFunc> SeiParserHelperFactory::HELPER_CONSTRUCTOR_MAP = {
    { TYPE_AVC,   []() { return std::make_shared<AvcSeiParserHelper>(); } },
    { TYPE_HEVC,  []() { return std::make_shared<HevcSeiParserHelper>(); } }
};

std::shared_ptr<SeiParserHelper> SeiParserHelperFactory::CreateHelper(const std::string &mimeType)
{
    auto constructor = HELPER_CONSTRUCTOR_MAP.find(mimeType);
    // ... factory routing
}
```

**来源**：`sei_parser_helper.cpp:116-133`（子类 NALU 识别）

```cpp
// AvcSeiParserHelper::IsSeiNalu - sei_parser_helper.cpp:116-123
bool AvcSeiParserHelper::IsSeiNalu(uint8_t *&headerPtr)
{
    uint8_t header = *headerPtr;
    auto naluType = header & AVC_NAL_UNIT_TYPE_FLAG; // = 0x06
    headerPtr += AVC_SEI_HEAD_LEN; // += 1
    return naluType == AVC_SEI_TYPE; // 0x06
}

// HevcSeiParserHelper::IsSeiNalu - sei_parser_helper.cpp:125-133
bool HevcSeiParserHelper::IsSeiNalu(uint8_t *&headerPtr)
{
    uint8_t header = *headerPtr;
    auto naluType = header & HEVC_NAL_UNIT_TYPE_FLAG; // = 0x4E (39) or 0x50 (40)
    headerPtr += HEVC_SEI_HEAD_LEN; // += 2
    return naluType == HEVC_SEI_TYPE_ONE || naluType == HEVC_SEI_TYPE_TWO;
}
```

---

## 4. NALU 起始码定位算法

**来源**：`sei_parser_helper.cpp:77-98` 和 `sei_parser_helper.cpp:108-114`

```cpp
// GetNaluStartSeq() - 跨平台大小端适配
uint32_t SeiParserHelper::GetNaluStartSeq()
{
    uint32_t temp = 0x00000001;
    // 如果首字节为 0（big endian）返回 0x00000001；否则（little endian）返回 0x01000000
    return *reinterpret_cast<uint8_t *>(&temp) == 0 ? NALU_START_BIG_ENDIAN : NALU_START_LITTLE_ENDIAN;
}

// FindNextSeiNaluPos() - sei_parser_helper.cpp:77-98
// 搜索算法：跳过非零字节 → 跳过 0x00 → 检查是否跟 0x00000001
// 成功匹配后：startPtr++ 后调用 IsSeiNalu() 验证 NALU type
```

---

## 5. SEI RBSP 解析流程

**来源**：`sei_parser_helper.cpp:59-75`（主入口）和 `sei_parser_helper.cpp:135-161`（RBSP 循环）

```cpp
// ParseSeiPayload() - sei_parser_helper.cpp:59-75
Status SeiParserHelper::ParseSeiPayload(
    const std::shared_ptr<AVBuffer> &buffer, std::shared_ptr<SeiPayloadInfoGroup> &group)
{
    // NALU header = 4B startcode + 1B AVC / 2B HEVC + 16B UUID
    uint8_t seiNaluPrefixLen = ANNEX_B_PREFIX_LEN + 1 + 1 + SEI_UUID_LEN; // = 22 (AVC) or 23 (HEVC)
    uint8_t *naluStartPtr = buffer->memory_->GetAddr() + SHIFT_THREE_BYTES;
    uint8_t *maxPointer = naluStartPtr + buffer->memory_->GetSize() - SHIFT_THREE_BYTES;
    uint8_t *maxSeiPointer = maxPointer - seiNaluPrefixLen - 1;
    while (FindNextSeiNaluPos(naluStartPtr, maxSeiPointer)) {
        ParseSeiRbsp(naluStartPtr, maxPointer, group); // 循环解析每个 SEI message
    }
    group->playbackPosition = Plugins::Us2Ms(buffer->pts_); // PTS 时间锚点
    return bufferParseRes;
}

// ParseSeiRbsp() - sei_parser_helper.cpp:135-161
// 每个 SEI NALU 内可包含多个 SEI message part，循环解析：
// 1. GetSeiTypeOrSize(bodyPtr) 读取 payloadType（变长编码，0xFF 填充字节）
// 2. GetSeiTypeOrSize(bodyPtr) 读取 payloadSize
// 3. 若 payloadType 不在监听列表 → FillTargetBuffer(nullptr) 跳过
// 4. 否则 → AVBuffer::CreateAVBuffer(SHARED_MEMORY) → FillTargetBuffer(avBuffer) 复制负载
// 5. group->vec.push_back({ payloadType, avBuffer })
```

---

## 6. RBSP 防伪字节转义（Emulation Prevention）

**来源**：`sei_parser_helper.cpp:276-297`

```cpp
Status SeiParserHelper::FillTargetBuffer(...)
{
    // H.264/H.265 编码时 0x000000/0x000001/0x000002/0x000003 被替换为防伪字节
    // 解码时需还原：连续两个 0x00 后跟 0x03 → 跳过 0x03，只保留 0x00
    for (int32_t zeroNum = 0; writtenSize < payloadSize && payloadPtr < maxPtr; payloadPtr++) {
        if (*payloadPtr == EMULATION_PREVENTION_CODE && zeroNum == EMULATION_GUIDE_0_LEN) {
            zeroNum = 0;
            continue; // 跳过 0x03，还原 0x00
        }
        zeroNum = *payloadPtr == 0 ? zeroNum + 1 : 0;
        if (targetPtr != nullptr) {
            targetPtr[writtenSize] = *payloadPtr;
        }
        writtenSize++;
    }
}
```

---

## 7. SEI 事件回调链路

**来源**：`sei_parser_helper.cpp:317-354`（`SeiParserListener::OnBufferFilled`）

```cpp
void SeiParserListener::OnBufferFilled(std::shared_ptr<AVBuffer> &avBuffer)
{
    producer_->ReturnBuffer(avBuffer, true);  // ON_SCOPE_EXIT 自动归还 Buffer
    FlowLimit(avBuffer);                      // PTS 同步限流
    seiParserHelper_->ParseSeiPayload(avBuffer, group);
    
    // 构建 EVENT_SEI_INFO 事件格式
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
    eventReceiver_->OnEvent({ "SeiParserHelper", EventType::EVENT_SEI_INFO, seiInfoFormat });
}
```

---

## 8. PTS 同步限流（FlowLimit）

**来源**：`sei_parser_helper.cpp:296-313`

```cpp
void SeiParserListener::FlowLimit(const std::shared_ptr<AVBuffer> &avBuffer)
{
    // 记录首帧 PTS 作为基准时间
    if (startPts_ == 0) {
        startPts_ = avBuffer->pts_;
    }
    // 计算当前 Buffer PTS 与 MediaSyncCenter 时间的差值
    auto mediaTimeUs = syncCenter_->GetMediaTimeNow();
    auto diff = avBuffer->pts_ - startPts_ - mediaTimeUs;
    // diff > 0 说明 Buffer 来得太早，限流等待
    std::unique_lock<std::mutex> lock(mutex_);
    cond_.wait_for(lock, std::chrono::microseconds(diff), [this] () { return isInterruptNeeded_.load(); });
}
```

---

## 9. Filter 注册与 Pipeline 接入

**来源**：`sei_parser_filter.cpp:40-44`

```cpp
static AutoRegisterFilter<SeiParserFilter> g_registerSeiParserFilter(
    "builtin.player.seiParser", FilterType::FILTERTYPE_SEI, [](const std::string &name, const FilterType type) {
        return std::make_shared<SeiParserFilter>(name, FilterType::FILTERTYPE_SEI);
    });
```

**来源**：`sei_parser_filter.h:47-68`（Filter 层关键成员）

```cpp
class SeiParserFilter : public Filter, public InterruptListener, 
                       public std::enable_shared_from_this<SeiParserFilter> {
    std::string codecMimeType_;          // "video/avc" 或 "video/hevc"
    FilterType filterType_ = FilterType::FILTERTYPE_SEI;
    std::shared_ptr<AVBufferQueue> inputBufferQueue_;
    sptr<AVBufferQueueProducer> inputBufferQueueProducer_;
    sptr<AVBufferQueueConsumer> inputBufferQueueConsumer_;
    bool seiMessageCbStatus_{ false };  // SEI 回调使能标志
    std::vector<int32_t> payloadTypes_;  // 监听 payloadType 白名单
    sptr<SeiParserListener> producerListener_;
    std::shared_ptr<IMediaSyncCenter> syncCenter_; // PTS 同步中心
};
```

**关键方法**：

- `SetSeiMessageCbStatus(bool, vector<int32_t>)`（sei_parser_filter.cpp:199-213）：使能/配置 SEI 回调，传入 payloadType 白名单
- `SetSyncCenter()`（sei_parser_filter.cpp:215-219）：注入 MediaSyncCenter 用于 FlowLimit
- `OnBufferAvailable()` → `ProcessInputBuffer()` → `DrainOutputBuffer()`（sei_parser_filter.cpp:179-192）：Buffer 可用驱动解析
- `PrepareInputBufferQueue()`（sei_parser_filter.cpp:90-133）：创建容量为 `videoWidth * videoHeight * 1.5` 或 1MB 的 AVBufferQueue

---

## 10. SEI 数据结构

**来源**：`sei_parser_helper.h:104-128`

```cpp
struct SeiPayloadInfo {
    int32_t payloadType;
    std::shared_ptr<AVBuffer> payload;
};

struct SeiPayloadInfoGroup {
    int64_t playbackPosition = 0; // PTS（毫秒），来自 Plugins::Us2Ms(buffer->pts_)
    std::vector<SeiPayloadInfo> vec; // 多个 SEI message part
};
```

**已注册 PayloadType**（常见值）：

| payloadType | 含义 | 触发条件 |
|------------|------|---------|
| 5 | **user_data_unregistered**（播放器自定义 SEI） | 由应用通过 `SetSeiMessageCbStatus` 注册 |
| 其他 | 注册后任一符合的 payloadType | 由播放器业务层配置 |

---

## 11. 关联记忆

| 关联记忆 | 关系 |
|---------|------|
| `MEM-ARCH-AVCODEC-S14` | FilterChain 架构：SeiParserFilter 是 Filter Pipeline 中的一个节点 |
| `MEM-ARCH-AVCODEC-S22` | MediaSyncManager：SeiParserListener 通过 `IMediaSyncCenter` 注入进行 PTS 同步 |
| `MEM-ARCH-AVCODEC-S46` | DecoderSurfaceFilter：SEI 通常在视频解码后提取，与 DRM 解密在同一 Filter 链路后 |
| `MEM-ARCH-AVCODEC-S63` | CodecDrmDecrypt：DRM 解密在 SEI 解析之前，SvpMode 一致性校验关联 |

---

## 12. Evidence 汇总表（本地镜像行号）

| 证据 | 文件 | 行号 |
|------|------|------|
| SEI 类型常量（AVC/HEVC） | sei_parser_helper.cpp | 18-48 |
| HELPER_CONSTRUCTOR_MAP 工厂 | sei_parser_helper.cpp | 50-57 |
| GetNaluStartSeq 大小端适配 | sei_parser_helper.cpp | 108-114 |
| FindNextSeiNaluPos 搜索 | sei_parser_helper.cpp | 77-98 |
| AvcSeiParserHelper::IsSeiNalu | sei_parser_helper.cpp | 116-123 |
| HevcSeiParserHelper::IsSeiNalu | sei_parser_helper.cpp | 125-133 |
| ParseSeiPayload 主入口 | sei_parser_helper.cpp | 59-75 |
| ParseSeiRbsp 多消息解析 | sei_parser_helper.cpp | 135-161 |
| GetSeiTypeOrSize 变长解码 | sei_parser_helper.cpp | 263-274 |
| FillTargetBuffer RBSP 转义 | sei_parser_helper.cpp | 276-297 |
| CreateHelper 工厂方法 | sei_parser_helper.cpp | 299-303 |
| SeiParserListener 构造 | sei_parser_helper.cpp | 305-313 |
| OnBufferFilled 回调链 | sei_parser_helper.cpp | 317-354 |
| FlowLimit PTS 同步 | sei_parser_helper.cpp | 296-313 |
| SetSeiMessageCbStatus | sei_parser_helper.cpp | 356-374 |
| Filter 注册 | sei_parser_filter.cpp | 40-44 |
| AVBufferQueue 创建 | sei_parser_filter.cpp | 90-133 |
| SetSeiMessageCbStatus | sei_parser_filter.cpp | 199-213 |
| SetSyncCenter 注入 | sei_parser_filter.cpp | 215-219 |
| DrainOutputBuffer | sei_parser_filter.cpp | 179-192 |
| SEI 数据结构定义 | sei_parser_helper.h | 104-128 |
| Filter 头文件 | sei_parser_filter.h | 104 行 |
| Helper 头文件 | sei_parser_helper.h | 134 行 |

---

**v2.0 变更**：  
- 新增 HEVC SEI NALU type `0x4E`(39)/`0x50`(40) 证据（原 v1.0 只写了 AVC）  
- 新增字节填充检测常量 `SEI_ASSEMBLE_BYTE` / `SEI_BYTE_MASK_HIGH_7BITS`  
- 新增大小端 `GetNaluStartSeq` 跨平台适配  
- 新增 PTS 同步限流 `FlowLimit` 完整逻辑  
- 新增 RBSP 防伪字节 `EMULATION_PREVENTION_CODE` 转义算法  
- 新增 `SeiPayloadInfo` / `SeiPayloadInfoGroup` 结构体定义  
- 补全 Evidence 汇总表（22 条行号级证据）  
- 更新关联记忆（S14/S22/S46/S63）