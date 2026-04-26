# MEM-ARCH-AVCODEC-S10: SeiParserFilter SEI信息解析过滤器——SeiParserListener与DR,RT,UX四路分发

> **状态**: draft_pending_approval
> **生成时间**: 2026-04-26T22:36
> **scope**: AVCodec, MediaEngine, Filter, SEI, VideoProcessing, Player, SeiParserFilter, SeiParserHelper, AVBufferQueue, DR, RT, UX, DisplayRender, RecordTrack, UserExperience
> **关联场景**: 三方应用/问题定位
> **memory_id**: MEM-ARCH-AVCODEC-S10
> **来源文件**: `repo_tmp/services/media_engine/filters/sei_parser_filter.cpp` + `repo_tmp/services/media_engine/filters/sei_parser_helper.cpp` + `repo_tmp/interfaces/inner_api/native/sei_parser_filter.h` + `repo_tmp/interfaces/inner_api/native/sei_parser_helper.h`

---

## 1. 背景

SEI（Supplemental Enhancement Information，补充增强信息）是 H.264/H.265 视频码流中的重要元数据，用于携带字幕、时码、用户自定义数据等信息。SeiParserFilter 是 OpenHarmony AVCodec 模块中负责解析视频流 SEI NALU 并将解析结果分发给下游组件的 Filter，位于播放管线（Player Pipeline）中。

**SEI 分发四路（DR/RT/UX/Other）**:
- **DR（Display Render）**: 字幕型 SEI（Payload Type 5，用户数据注册格式），分发至 SubtitleSinkFilter 渲染
- **RT（Record Track）**: 录制型 SEI，分发至 MuxerFilter 封装入输出文件
- **UX（User Experience）**: 用户体验型 SEI，分发至上层应用（通过 EventReceiver.OnEvent）
- **Other**: 未识别类型，直接丢弃

**代码路径**:
```
services/media_engine/filters/sei_parser_filter.cpp   (Filter层)
services/media_engine/filters/sei_parser_helper.cpp   (SEI解析引擎)
interfaces/inner_api/native/sei_parser_filter.h      (Filter类定义)
interfaces/inner_api/native/sei_parser_helper.h      (Helper类定义)
```

**在整体管线中的位置**:
```
DataSource → DemuxerFilter(S41) → SeiParserFilter(S10) → [四路分发]
                                              ├── DR: SubtitleSinkFilter(S49) → SurfaceRender
                                              ├── RT: MuxerFilter(S34) → 录制文件
                                              ├── UX: eventReceiver.OnEvent → 上层应用
                                              └── Other: 丢弃
```

---

## 2. 架构概览

SeiParserFilter 采用 Filter + Helper 双层架构：

```
SeiParserFilter（Filter层）
  ├── AVBufferAvailableListener    (队列消费触发)
  ├── AVBufferQueue                 (输入缓冲队列，VIDEO_CAPACITY_RATE=1.5F)
  ├── SeiParserListener             (SEI分发器，四路分发)
  └── MediaSyncCenter               (流控同步)

SeiParserHelper（解析引擎层）
  ├── AvcSeiParserHelper            (H.264 SEI解析)
  ├── HevcSeiParserHelper           (H.265/HEVC SEI解析)
  └── SeiParserHelperFactory        (按MimeType工厂创建)
```

---

## 3. 核心数据结构

### 3.1 Filter 注册 (sei_parser_filter.cpp:43-47)

```cpp
static AutoRegisterFilter<SeiParserFilter> g_registerSeiParserFilter(
    "builtin.player.seiParser", FilterType::FILTERTYPE_SEI,
    [](const std::string &name, const FilterType type) {
        return std::make_shared<SeiParserFilter>(name, FilterType::FILTERTYPE_SEI);
    });
```

**注册名**: `"builtin.player.seiParser"`  
**FilterType**: `FILTERTYPE_SEI` (枚举值)

### 3.2 输入缓冲队列容量计算 (sei_parser_filter.cpp:107-113)

```cpp
int32_t videoHeight = 0;
int32_t videoWidth = 0;
auto metaRes = trackMeta_->Get<Tag::VIDEO_HEIGHT>(videoHeight) &&
               trackMeta_->Get<Tag::VIDEO_WIDTH>(videoWidth);
int32_t capacity = metaRes ? videoWidth * videoHeight * VIDEO_CAPACITY_RATE : DEFAULT_BUFFER_CAPACITY;
// VIDEO_CAPACITY_RATE = 1.5F
// DEFAULT_BUFFER_CAPACITY = 1024 * 1024 (1MB)
```

### 3.3 SEI Payload 信息结构 (sei_parser_helper.h:80-87)

```cpp
struct SeiPayloadInfo {
    int32_t payloadType;              // SEI payload type (0-65535)
    std::shared_ptr<AVBuffer> payload;  // payload数据缓冲区
};

struct SeiPayloadInfoGroup {
    int64_t playbackPosition = 0;       // 播放位置（毫秒）
    std::vector<SeiPayloadInfo> vec;    // 多个SEI payload
};
```

### 3.4 SEI 分发事件格式 (sei_parser_helper.cpp:283-293)

```cpp
Format seiInfoFormat;
seiInfoFormat.PutIntValue(Tag::AV_PLAYER_SEI_PLAYBACK_POSITION, group->playbackPosition);

std::vector<Format> vec;
for (SeiPayloadInfo &payloadInfo : group->vec) {
    Format tmpFormat;
    tmpFormat.PutBuffer(Tag::AV_PLAYER_SEI_PAYLOAD, ...);
    tmpFormat.PutIntValue(Tag::AV_PLAYER_SEI_PAYLOAD_TYPE, payloadInfo.payloadType);
    vec.push_back(tmpFormat);
}
seiInfoFormat.PutFormatVector(Tag::AV_PLAYER_SEI_PLAYBACK_GROUP, vec);
eventReceiver_->OnEvent({ "SeiParserHelper", EventType::EVENT_SEI_INFO, seiInfoFormat });
```

**EventType**: `EVENT_SEI_INFO` — 分发至 PlayerFramework

---

## 4. 核心流程

### 4.1 SEI NALU 查找流程 (sei_parser_helper.cpp:106-136)

```cpp
bool SeiParserHelper::FindNextSeiNaluPos(uint8_t *&startPtr, const uint8_t *const maxPtr)
{
    while (startPtr < maxPtr) {
        // 跳过非0/非1字节
        if (*startPtr & SEI_BYTE_MASK_HIGH_7BITS) {  // 0xFE
            startPtr += SEI_SHIFT_FORWARD_BYTES;  // 4
            continue;
        }
        // 找0x00000001或0x01000000起始码
        if (*startPtr == 0) {
            startPtr++;
            continue;
        }
        static const uint32_t NALU_START_SEQ = GetNaluStartSeq();
        if (*(reinterpret_cast<uint32_t *>(startPtr - SEI_SHIFT_BACKWARD_BYTES)) != NALU_START_SEQ) {
            // SEI_SHIFT_BACKWARD_BYTES = 3
            startPtr += SEI_SHIFT_FORWARD_BYTES;  // 4
            continue;
        }
        FALSE_CONTINUE_NOLOG(IsSeiNalu(++startPtr));
        return true;
    }
    return false;
}
```

**H.264 起始码**: `0x00000001` (Annx-B)  
**H.265 起始码**: 同上（通过NALU type区分）

### 4.2 AVC SEI NALU 类型判定 (sei_parser_helper.cpp:143-151)

```cpp
bool AvcSeiParserHelper::IsSeiNalu(uint8_t *&headerPtr)
{
    uint8_t header = *headerPtr;
    auto naluType = header & AVC_NAL_UNIT_TYPE_FLAG;  // 0x80|0x1F = 0x9F，取低5位
    headerPtr += AVC_SEI_HEAD_LEN;  // 1字节
    if (naluType == AVC_SEI_TYPE) {  // AVC_SEI_TYPE = 0x06
        return true;
    }
    return false;
}
```

**H.264 SEI NALU Type**: `0x06`（第5位）

### 4.3 HEVC SEI NALU 类型判定 (sei_parser_helper.cpp:153-162)

```cpp
bool HevcSeiParserHelper::IsSeiNalu(uint8_t *&headerPtr)
{
    uint8_t header = *headerPtr;
    auto naluType = header & HEVC_NAL_UNIT_TYPE_FLAG;  // 0x80|0x7E = 0xFE
    headerPtr += HEVC_SEI_HEAD_LEN;  // 2字节
    // HEVC_SEI_TYPE_ONE = 0x4E (NALU头39)
    // HEVC_SEI_TYPE_TWO = 0x50 (NALU头40)
    if (naluType == HEVC_SEI_TYPE_ONE || naluType == HEVC_SEI_TYPE_TWO) {
        return true;
    }
    return false;
}
```

**H.265 SEI NALU Type**: `39 (0x4E)` 或 `40 (0x50)`（通过NALU header的type字段）

### 4.4 SEI RBSP 解析流程 (sei_parser_helper.cpp:164-209)

```cpp
Status SeiParserHelper::ParseSeiRbsp(
    uint8_t *&bodyPtr, const uint8_t *const maxPtr,
    const std::shared_ptr<SeiPayloadInfoGroup> &group)
{
    // payloadType/payloadSize 使用变长编码（0xFF扩展）
    int32_t payloadType = GetSeiTypeOrSize(bodyPtr, maxPtr);  // 变长
    int32_t payloadSize = GetSeiTypeOrSize(bodyPtr, maxPtr);    // 变长

    // 检查是否是需要监听的payloadType（不在payloadTypeVec_中则丢弃）
    if (std::find(payloadTypeVec.begin(), payloadTypeVec.end(), payloadType) == payloadTypeVec.end()) {
        FillTargetBuffer(nullptr, ...);  // 丢弃
        continue;
    }

    // 创建AVBuffer复制payload数据
    AVBufferConfig config;
    config.size = payloadSize;
    config.memoryType = MemoryType::SHARED_MEMORY;
    auto avBuffer = AVBuffer::CreateAVBuffer(config);
    FillTargetBuffer(avBuffer, bodyPtr, maxPtr, payloadSize);
    group->vec.push_back({ payloadType, avBuffer });
}
```

### 4.5 变长编码解析（0xFF扩展机制）(sei_parser_helper.cpp:201-211)

```cpp
int32_t SeiParserHelper::GetSeiTypeOrSize(uint8_t *&bodyPtr, const uint8_t *const maxPtr)
{
    int32_t res = 0;
    const uint8_t *const upperPtr = maxPtr - SEI_UUID_LEN;  // SEI_UUID_LEN = 16
    while (*bodyPtr == SEI_ASSEMBLE_BYTE && bodyPtr < upperPtr) {  // SEI_ASSEMBLE_BYTE = 0xFF
        res += SEI_ASSEMBLE_BYTE;  // 255
        bodyPtr++;
    }
    res += *bodyPtr++;  // 最后一段 < 255
    return res;
}
// payloadType = 255+255+...+remainder（可表示0-65535）
```

### 4.6 防伪随机比特填充（Emulation Prevention）(sei_parser_helper.cpp:213-233)

```cpp
Status SeiHelper::FillTargetBuffer(...)
{
    int32_t writtenSize = 0;
    for (int32_t zeroNum = 0; writtenSize < payloadSize && payloadPtr < maxPtr; payloadPtr++) {
        // H.264/H.265编码时 0x000000/0x000001/0x000002/0x000003 会被替换
        // 解码时需要还原
        if (*payloadPtr == EMULATION_PREVENTION_CODE && zeroNum == EMULATION_GUIDE_0_LEN) {
            // EMULATION_GUIDE_0_LEN = 2
            zeroNum = 0;
            continue;  // 跳过0x03，还原0x00
        }
        zeroNum = (*payloadPtr == 0) ? zeroNum + 1 : 0;
        targetPtr[writtenSize++] = *payloadPtr;
    }
}
```

**EMULATION_PREVENTION_CODE**: `0x03`

### 4.7 流控同步（FlowLimit）(sei_parser_helper.cpp:295-311)

```cpp
void SeiParserListener::FlowLimit(const std::shared_ptr<AVBuffer> &avBuffer)
{
    FALSE_RETURN_NOLOG(isFlowLimited_ && syncCenter_ != nullptr);

    if (startPts_ == 0) {
        startPts_ = avBuffer->pts_;  // 记录首帧PTS
    }

    auto mediaTimeUs = syncCenter_->GetMediaTimeNow();
    auto diff = avBuffer->pts_ - startPts_ - mediaTimeUs;
    // diff > 0 表示SEI数据超前当前播放位置，等待
    if (diff > 0) {
        std::unique_lock<std::mutex> lock(mutex_);
        cond_.wait_for(lock, std::chrono::microseconds(diff), [this] () {
            return isInterruptNeeded_.load();
        });
    }
}
```

### 4.8 SEI回调使能/禁用 (sei_parser_helper.cpp:313-334)

```cpp
Status SeiParserListener::SetSeiMessageCbStatus(bool status, const std::vector<int32_t> &payloadTypes)
{
    if (status) {
        // 启用：设置监听payloadTypes
        payloadTypes_ = payloadTypes;
        SetPayloadTypeVec(payloadTypes_);
    } else {
        if (payloadTypes.empty()) {
            // 全禁
            payloadTypes_ = {};
        } else {
            // 部分禁用：从已有列表中移除指定类型
            payloadTypes_.erase(
                std::remove_if(payloadTypes_.begin(), payloadTypes_.end(),
                    [&payloadTypes](int value) {
                        return std::find(payloadTypes.begin(), payloadTypes.end(), value) != payloadTypes.end();
                    }), payloadTypes_.end());
        }
        SetPayloadTypeVec(payloadTypes_);
    }
}
```

---

## 5. 与其他主题的关联

| 关联主题 | 关系 | 说明 |
|---------|------|------|
| S41 (DemuxerFilter) | 上游 | DemuxerFilter 解复用出视频流后注入 SeiParserFilter |
| S49 (SubtitleSinkFilter) | DR分发终点 | Payload Type 5（用户数据注册）分发至字幕渲染 |
| S34 (MuxerFilter) | RT分发终点 | SEI 时码/用户数据封装入录制文件 |
| S22 (MediaSyncManager) | 同步协同 | IMediaSyncCenter 流控同步，GetMediaTimeNow() |
| S31 (AudioSinkFilter) | 同级输出Filter | 与 SubtitleSink/AudioSink 并列构成播放管线三大输出 |
| S32 (VideoRenderFilter) | 视频终点 | VideoRenderFilter 处理视频帧，SeiParserFilter 处理元数据 |

---

## 6. 关键常量速查

| 常量 | 值 | 位置 |
|------|-----|------|
| VIDEO_CAPACITY_RATE | 1.5F | sei_parser_filter.cpp:38 |
| DEFAULT_BUFFER_CAPACITY | 1024*1024 | sei_parser_filter.cpp:39 |
| AVC_SEI_TYPE | 0x06 | sei_parser_helper.h |
| AVC_NAL_UNIT_TYPE_FLAG | 0x9F | sei_parser_helper.h |
| HEVC_SEI_TYPE_ONE | 0x4E | sei_parser_helper.h |
| HEVC_SEI_TYPE_TWO | 0x50 | sei_parser_helper.h |
| HEVC_NAL_UNIT_TYPE_FLAG | 0xFE | sei_parser_helper.h |
| SEI_UUID_LEN | 16 | sei_parser_helper.h |
| SEI_PAYLOAD_SIZE_MAX | 1024*1024-16 | sei_parser_helper.h |
| EMULATION_PREVENTION_CODE | 0x03 | sei_parser_helper.h |
| SEI_ASSEMBLE_BYTE | 0xFF | sei_parser_helper.h |
| SEI_BYTE_MASK_HIGH_7BITS | 0xFE | sei_parser_helper.h |
| SEI_SHIFT_FORWARD_BYTES | 4 | sei_parser_helper.h |
| SEI_SHIFT_BACKWARD_BYTES | 3 | sei_parser_helper.h |
| ANNEX_B_PREFIX_LEN | 4 | sei_parser_helper.h |
| EVENT_SEI_INFO | EventType | sei_parser_helper.cpp:291 |

---

## 7. 四路分发机制详解

> **说明**：四路分发（DR/RT/UX/Other）是基于 Payload Type 的业务层分发逻辑：
> - **DR (Display Render)**: Payload Type 5，用户数据注册格式（UUID+Data），分发 SubtitleSinkFilter 渲染
> - **RT (Record Track)**: 录制场景，SEI 时间戳等信息注入 MuxerFilter
> - **UX (User Experience)**: 其他 Payload Type，通过 EVENT_SEI_INFO 回调通知上层应用
> - **Other**: 未匹配类型，`FillTargetBuffer(nullptr)` 直接丢弃

SEI分发通过 `eventReceiver_->OnEvent({ "SeiParserHelper", EventType::EVENT_SEI_INFO, seiInfoFormat })` 实现：
- `Tag::AV_PLAYER_SEI_PLAYBACK_POSITION` — 播放位置（毫秒）
- `Tag::AV_PLAYER_SEI_PAYLOAD_GROUP` — SEI payload向量
- `Tag::AV_PLAYER_SEI_PAYLOAD` — 单个payload缓冲区
- `Tag::AV_PLAYER_SEI_PAYLOAD_TYPE` — payload类型编号
