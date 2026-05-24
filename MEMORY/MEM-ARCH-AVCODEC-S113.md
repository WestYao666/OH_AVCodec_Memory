# MEM-ARCH-AVCODEC-S113

> **记忆工厂草案** | Builder Agent | 2026-05-21T06:50+08:00  
> **主题**: SeiParserFilter 与 SeiParserHelper SEI信息解析框架——AnnexB/Nalu双格式+AVC/HEVC双解析器工厂+回调驱动事件链  
> **状态**: pending_approval  
> **关联**: S10/S14/S22/S46/S63

---

## 1 架构概览

SEI (Supplemental Enhancement Information) 解析框架位于 MediaEngine Filter 层，处理视频流中的 SEI 元数据（字幕、位置信息、用户数据等）。框架由两层构成：

```
SeiParserFilter (Filter层, "builtin.player.seiParser")
    └── SeiParserListener (事件驱动, IBrokerListener)
            └── SeiParserHelperFactory → AvcSeiParserHelper / HevcSeiParserHelper
```

**证据**:
- sei_parser_filter.cpp L32: `g_registerSeiParserFilter("builtin.player.seiParser", FilterType::FILTERTYPE_SEI, ...)`
- sei_parser_helper.h L79-84: `HELPER_CONSTRUCTOR_MAP = { TYPE_AVC → AvcSeiParserHelper, TYPE_HEVC → HevcSeiParserHelper }`

---

## 2 核心数据结构

### 2.1 SEI NALU 类型常量

| 编码格式 | NALU Type | 十六进制 | 判定常量 |
|---------|-----------|---------|---------|
| AVC SEI | 6 | 0x06 | `AVC_SEI_TYPE = 0x06` (L43) |
| HEVC SEI (type 39) | 39 | 0x4E | `HEVC_SEI_TYPE_ONE = 0x4E` (L39) |
| HEVC SEI (type 40) | 40 | 0x50 | `HEVC_SEI_TYPE_TWO = 0x50` (L40) |

**关键位运算** (L41-42):
```cpp
HEVC_NAL_UNIT_TYPE_FLAG = (0x80 | 0x7E);  // 禁止位(bit7) + 类型位掩码(bit0-5)
AVC_NAL_UNIT_TYPE_FLAG = (0x80 | 0x1F);  // 禁止位(bit7) + 类型位掩码(bit0-4)
```

### 2.2 SEI 起始码

- **ANNEX_B_PREFIX_LEN = 4** (L34): 起始码 4 字节
- **NALU_START_BIG_ENDIAN = 0x00000001** (L66): 大端序
- **NALU_START_LITTLE_ENDIAN = 0x01000000** (L67): 小端序
- **GetNaluStartSeq()** (L97-103): 动态检测系统字节序，决定使用哪种起始码

### 2.3 SEI Payload 结构

```cpp
struct SeiPayloadInfo {
    int32_t payloadType;              // SEI payload 类型
    std::shared_ptr<AVBuffer> payload; // payload 内容 (SHARED_MEMORY)
};

struct SeiPayloadInfoGroup {
    int64_t playbackPosition = 0;    // PTS 毫秒 (Plugins::Us2Ms)
    std::vector<SeiPayloadInfo> vec;  // 同一帧中多个 SEI message
};
```

**证据**: sei_parser_helper.h L63-68

### 2.4 SEI 解析常量

```cpp
constexpr uint16_t SEI_UUID_LEN = 16;                              // UUID 长度
constexpr int32_t SEI_PAYLOAD_SIZE_MAX = 1024 * 1024 - SEI_UUID_LEN;  // 最大 payload
constexpr uint8_t SEI_ASSEMBLE_BYTE = 0xFF;                         // payload size 编码
constexpr uint8_t EMULATION_PREVENTION_CODE = 0x03;                 // 防伪字节 (0x000003 → 0x0000)
```

**证据**: sei_parser_helper.cpp L36-37, L46-50

---

## 3 SEI NALU 定位算法 (FindNextSeiNaluPos)

**文件**: sei_parser_helper.cpp L88-114

逐字节扫描，跳过非零字节，快速定位起始码 + SEI NALU:

```
while (startPtr < maxPtr) {
    1. 跳过非零字节 (*startPtr & 0xFE != 0) → startPtr += 4
    2. 跳过孤立零字节 (*startPtr == 0) → startPtr++
    3. 检测 "0001" 序列: (*(uint32_t*)(startPtr-3) == NALU_START_SEQ)
    4. 调用 IsSeiNalu(++startPtr) → 读取 NALU header byte，检查类型
    5. 若匹配 → return true; 否则 continue
}
```

**防伪字节处理** (L50): `0x000003` 在编码时被替换为 `0x0000`，解析时需还原

---

## 4 AVC / HEVC 双解析器工厂

**文件**: sei_parser_helper.h L79-84

```cpp
const std::map<std::string, HelperConstructFunc> SeiParserHelperFactory::HELPER_CONSTRUCTOR_MAP = {
    { "video/avc",  []() { return std::make_shared<AvcSeiParserHelper>(); } },
    { "video/hevc", []() { return std::make_shared<HevcSeiParserHelper>(); } }
};
```

### 4.1 AVC SEI 判定 (AvcSeiParserHelper::IsSeiNalu)

**文件**: sei_parser_helper.cpp L116-124

```cpp
bool AvcSeiParserHelper::IsSeiNalu(uint8_t *&headerPtr)
{
    uint8_t header = *headerPtr;
    auto naluType = header & AVC_NAL_UNIT_TYPE_FLAG;  // 0x80|0x1F = 0x9F, 保留禁止位
    headerPtr += AVC_SEI_HEAD_LEN;  // 1 字节 header 后移到 payload
    return (naluType == AVC_SEI_TYPE);  // naluType == 0x06
}
```

**注意**: `AVC_NAL_UNIT_TYPE_FLAG = 0x80 | 0x1F = 0x9F`，而 `AVC_SEI_TYPE = 0x06`。这里 `header & 0x9F` 提取 type bits，`naluType` 实际是 `header & 0x1F`（去掉禁止位），与 `0x06` 比较。

### 4.2 HEVC SEI 判定 (HevcSeiParserHelper::IsSeiNalu)

**文件**: sei_parser_helper.cpp L126-134

```cpp
bool HevcSeiParserHelper::IsSeiNalu(uint8_t *&headerPtr)
{
    uint8_t header = *headerPtr;
    auto naluType = header & HEVC_NAL_UNIT_TYPE_FLAG;  // 0x80|0x7E = 0xFE
    headerPtr += HEVC_SEI_HEAD_LEN;  // 2 字节 header
    return (naluType == HEVC_SEI_TYPE_ONE || naluType == HEVC_SEI_TYPE_TWO);
    // 即 naluType == 0x4E(39) || naluType == 0x50(40)
}
```

### 4.3 SEI Payload 解析 (ParseSeiRbsp)

**文件**: sei_parser_helper.cpp L139-168

```
while (bodyPtr + SEI_UUID_LEN < maxPtr) {
    1. GetSeiTypeOrSize(bodyPtr, maxPtr) → payloadType (L173-181: 变长解码, 0xFF 累加)
    2. GetSeiTypeOrSize(bodyPtr, maxPtr) → payloadSize
    3. 校验 payloadSize 有效性 (≤ SEI_PAYLOAD_SIZE_MAX)
    4. 若 payloadType 不在监听列表 → FillTargetBuffer(跳过)
    5. 否则 → 创建 AVBuffer(SHARED_MEMORY) + FillTargetBuffer(复制 payload 数据)
       注意: FillTargetBuffer 处理 EMULATION_PREVENTION 转义还原 (L186-205)
    6. group->vec.push_back({payloadType, avBuffer})
}
```

---

## 5 Filter 层架构

### 5.1 静态注册

**证据**: sei_parser_filter.cpp L32-35

```cpp
static AutoRegisterFilter<SeiParserFilter> g_registerSeiParserFilter(
    "builtin.player.seiParser",   // Filter 注册名
    FilterType::FILTERTYPE_SEI,   // Filter 类型枚举
    [](const std::string &name, const FilterType type) {
        return std::make_shared<SeiParserFilter>(name, FilterType::FILTERTYPE_SEI);
    });
```

### 5.2 Filter 生命周期

| 阶段 | 函数 | 说明 |
|------|------|------|
| Link 后 | `DoInitAfterLink()` (L70) | 获取 codecMimeType_ |
| Prepare | `DoPrepare()` (L75-90) | 创键 AVBufferQueue(1 buffer, 1MB) + 设置 ConsumerListener |
| 运行 | `OnLinked()` (L160-166) | 接收 trackMeta_ 和 FilterLinkCallback |
| 运行 | `DoProcessInputBuffer()` (L148-150) | 调用 DrainOutputBuffer(dropFrame) |
| 运行 | `DrainOutputBuffer()` (L156-160) | AcquireBuffer + ReleaseBuffer (消费输入 buffer) |

### 5.3 Buffer 队列配置

```cpp
capacity = videoWidth * videoHeight * 1.5F  // 默认 1.5 倍像素面积
bufferNum = 1  // 单 buffer 队列
memoryType = VIRTUAL_MEMORY
```

**证据**: sei_parser_filter.cpp L99-113

---

## 6 事件回调链路

### 6.1 SeiParserListener 构造

**文件**: sei_parser_helper.cpp L211-221

```cpp
SeiParserListener::SeiParserListener(
    const std::string &mimeType,
    sptr<AVBufferQueueProducer> producer,
    std::shared_ptr<Pipeline::EventReceiver> eventReceiver,
    bool isFlowLimited)
    : producer_(producer), eventReceiver_(eventReceiver), isFlowLimited_(isFlowLimited)
{
    seiParserHelper_ = SeiParserHelperFactory::CreateHelper(mimeType);  // 创建对应解析器
    sptr<IBrokerListener> tmpListener = this;
    producer_->SetBufferFilledListener(tmpListener);  // 注册 buffer 填充监听
}
```

### 6.2 OnBufferFilled 事件流

**文件**: sei_parser_helper.cpp L224-263

```
OnBufferFilled(avBuffer)
  → ON_SCOPE_EXIT(0) { producer_->ReturnBuffer(avBuffer, true); }  // 自动归还 buffer
  → FlowLimit(avBuffer)  // PTS 同步限流 (L265-282)
  → seiParserHelper_->ParseSeiPayload(avBuffer, group)
  → 构建 FormatseiInfoFormat
      ├── Tag::AV_PLAYER_SEI_PLAYBACK_POSITION = group->playbackPosition (ms)
      ├── Tag::AV_PLAYER_SEI_PLAYBACK_GROUP = vector<Format>
      │       └── 每个 Format 含: Tag::AV_PLAYER_SEI_PAYLOAD (buffer) + Tag::AV_PLAYER_SEI_PAYLOAD_TYPE
  → eventReceiver_->OnEvent({ "SeiParserHelper", EventType::EVENT_SEI_INFO, seiInfoFormat })
```

### 6.3 EVENT_SEI_INFO 事件类型

**证据**: sei_parser_helper.cpp L254: `EventType::EVENT_SEI_INFO`

SEI 事件携带 Format 结构，上层通过 `Tag::AV_PLAYER_SEI_PAYLOAD_TYPE` 过滤 payload 类型（type=5 为 user_data_registered_itu_t_t35，常用于字幕）。

---

## 7 FlowLimit PTS 同步机制

**文件**: sei_parser_helper.cpp L265-282

```cpp
void SeiParserListener::FlowLimit(const std::shared_ptr<AVBuffer> &avBuffer)
{
    if (!isFlowLimited_ || syncCenter_ == nullptr) return;
    
    if (startPts_ == 0) startPts_ = avBuffer->pts_;  // 首帧记录起始 PTS
    
    auto mediaTimeUs = syncCenter_->GetMediaTimeNow();  // 当前播放时间
    auto diff = avBuffer->pts_ - startPts_ - mediaTimeUs;  // PTS 差值
    if (diff > 0) {
        std::unique_lock<std::mutex> lock(mutex_);
        cond_.wait_for(lock, std::chrono::microseconds(diff),
            [this]() { return isInterruptNeeded_.load(); });
    }
}
```

**作用**: 当 SEI 数据 PTS 领先当前播放位置时，阻塞等待；对齐 SEI 事件与播放进度。

---

## 8 与其他模块的关系

| 关联模块 | 关系 | 说明 |
|---------|------|------|
| S14 (FilterChain) | 上游 Filter 链路 | DemuxerFilter → VideoDecoderFilter → SeiParserFilter → (后续 Filter) |
| S22 (MediaSyncManager) | syncCenter_ 注入 | 播放管线启动时通过 SetSyncCenter 注入 IMediaSyncCenter |
| S46 (DecoderSurfaceFilter) | 并行 Filter | DecoderSurfaceFilter 出 VideoSurfaceOutput 时分叉，一路给 SeiParserFilter |
| S63 (CodecDrmDecrypt) | 无关 | DRM 解密在更早阶段，SEI 解析在解码后 |
| S10 (SeiParserFilter 初版草案) | 互补 | S10 为初版草案，本文件为本地镜像源码深度分析 |

---

## 9 关键证据索引

| 证据 | 文件 | 行号 |
|------|------|------|
| AutoRegisterFilter 静态注册 | sei_parser_filter.cpp | L32-35 |
| HEVC SEI type 39/40 | sei_parser_helper.cpp | L39-42 |
| AVC SEI type 0x06 | sei_parser_helper.cpp | L43 |
| ANNEX_B_PREFIX_LEN / NALU_START 起始码 | sei_parser_helper.cpp | L34, L66-67 |
| HELPER_CONSTRUCTOR_MAP 工厂 | sei_parser_helper.h | L79-84 |
| FindNextSeiNaluPos 扫描算法 | sei_parser_helper.cpp | L88-114 |
| AvcSeiParserHelper::IsSeiNalu | sei_parser_helper.cpp | L116-124 |
| HevcSeiParserHelper::IsSeiNalu | sei_parser_helper.cpp | L126-134 |
| ParseSeiRbsp payload 解析 | sei_parser_helper.cpp | L139-168 |
| GetSeiTypeOrSize 变长解码 | sei_parser_helper.cpp | L173-181 |
| FillTargetBuffer 防伪字节还原 | sei_parser_helper.cpp | L186-205 |
| CreateHelper 工厂方法 | sei_parser_helper.cpp | L207-211 |
| SeiParserListener 构造 | sei_parser_helper.cpp | L211-221 |
| OnBufferFilled 事件流 | sei_parser_helper.cpp | L224-263 |
| EVENT_SEI_INFO 事件类型 | sei_parser_helper.cpp | L254 |
| FlowLimit PTS 同步 | sei_parser_helper.cpp | L265-282 |
| SetSeiMessageCbStatus 状态管理 | sei_parser_helper.cpp | L284-305 |
| SetSyncCenter 注入 | sei_parser_filter.cpp | L171-175 |
| PrepareInputBufferQueue 队列创建 | sei_parser_filter.cpp | L92-126 |
| AVBufferAvailableListener 消费监听 | sei_parser_filter.cpp | L37-44 |
| EMULATION_PREVENTION_CODE | sei_parser_helper.cpp | L50 |
| SEI_UUID_LEN / SEI_PAYLOAD_SIZE_MAX | sei_parser_helper.cpp | L35-36 |

---

## 10 工程信息

- **本地镜像路径**: `/home/west/av_codec_repo`
- **源码文件**:
  - `services/media_engine/filters/sei_parser_filter.cpp` (235 行)
  - `services/media_engine/filters/sei_parser_filter.h` (接口)
  - `services/media_engine/filters/sei_parser_helper.cpp` (347 行)
  - `interfaces/inner_api/native/sei_parser_helper.h` (接口)
- **编译产物**: `libsei_parser_filter.z.so` (推测)
- **依赖库**: `libmedia_core.z.so`, `libavbuffer.z.so`, `libsync_manager.z.so`