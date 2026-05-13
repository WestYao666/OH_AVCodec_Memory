# MEM-ARCH-AVCODEC-S121: AVCodec 错误码与回调体系

## 基本信息

| 字段 | 值 |
|------|-----|
| ID | MEM-ARCH-AVCODEC-S121 |
| 主题 | AVCodec 错误码与回调体系——三层架构（AVCodecErrorType / AVCodecServiceErrCode / MediaCodecCallback） |
| 作用域 | AVCodec, ErrorHandling, Callback, CAPI, IPC |
| 关联场景 | 三方应用接入/问题定位/新人入项 |
| 状态 | draft |
| 创建 | 2026-05-14 |
| 来源 | S121（Builder 注册） |

---

## 一、三层错误类型体系

### 1.1 AVCodecErrorType（框架层枚举）

路径：`/home/west/av_codec_repo/interfaces/inner_api/native/avcodec_common.h:37-46`

```cpp
enum AVCodecErrorType : int32_t {
    /* internal errors, error code passed by the errorCode, and definition see "AVCodecServiceErrCode" */
    AVCODEC_ERROR_INTERNAL,
    /* extend error start. The extension error code agreed upon by the plug-in and
       the application will be transparently transmitted by the service. */
    AVCODEC_ERROR_DECRYTION_FAILED,
    /* internal errors, the extension error codes within the framework. */
    AVCODEC_ERROR_FRAMEWORK_FAILED,
    AVCODEC_ERROR_EXTEND_START = 0X10000,
};
```

- `AVCODEC_ERROR_INTERNAL`：内部错误，错误码语义由 `AVCodecServiceErrCode` 定义（第 3 层）
- `AVCODEC_ERROR_DECRYPTION_FAILED`：DRM 解密失败（扩展错误，与插件约定）
- `AVCODEC_ERROR_FRAMEWORK_FAILED`：框架内部错误
- `AVCODEC_ERROR_EXTEND_START = 0x10000`：插件自定义错误起始偏移

### 1.2 AVCodecServiceErrCode（服务层错误码）

路径：`/home/west/av_codec_repo/interfaces/inner_api/native/avcodec_errors.h:18-90`

错误码生成规则：`AVCS_ERR_OFFSET = ErrCodeOffset(SUBSYS_MULTIMEDIA, AVCS_MODULE)`，其中 `AVCS_MODULE = 10`。

```cpp
typedef enum AVCodecServiceErrCode : ErrCode {
    AVCS_ERR_OK = ERR_OK,
    AVCS_ERR_NO_MEMORY = AVCS_ERR_OFFSET + ENOMEM,         // no memory
    AVCS_ERR_INVALID_OPERATION = AVCS_ERR_OFFSET + ENOSYS, // opertation not be permitted
    AVCS_ERR_INVALID_VAL = AVCS_ERR_OFFSET + EINVAL,       // invalid argument
    AVCS_ERR_UNKNOWN = AVCS_ERR_OFFSET + 0x200,            // unknown error.
    AVCS_ERR_SERVICE_DIED,                                 // avcodec service died
    AVCS_ERR_INVALID_STATE,                                // the state is not support this operation.
    AVCS_ERR_UNSUPPORT,                                    // unsupport interface.
    AVCS_ERR_UNSUPPORT_AUD_SRC_TYPE,                       // unsupport audio source type.
    AVCS_ERR_UNSUPPORT_AUD_SAMPLE_RATE,                    // unsupport audio sample rate.
    AVCS_ERR_UNSUPPORT_AUD_CHANNEL_NUM,                    // unsupport audio channel.
    AVCS_ERR_UNSUPPORT_AUD_ENC_TYPE,                       // unsupport audio encoder type.
    AVCS_ERR_UNSUPPORT_AUD_PARAMS,                         // unsupport audio params(other params).
    AVCS_ERR_UNSUPPORT_VID_SRC_TYPE,                       // unsupport video source type.
    AVCS_ERR_UNSUPPORT_VID_ENC_TYPE,                       // unsupport video encoder type.
    AVCS_ERR_UNSUPPORT_VID_PARAMS,                         // unsupport video params(other params).
    AVCS_ERR_UNSUPPORT_FILE_TYPE,                          // unsupport file format type.
    AVCS_ERR_UNSUPPORT_PROTOCOL_TYPE,                      // unsupport protocol type.
    AVCS_ERR_UNSUPPORT_VID_DEC_TYPE,                       // unsupport video decoder type.
    AVCS_ERR_UNSUPPORT_AUD_DEC_TYPE,                       // unsupport audio decoder type.
    AVCS_ERR_UNSUPPORT_STREAM,                             // internal data stream error.
    AVCS_ERR_UNSUPPORT_SOURCE,                             // unsupport source type.
    AVCS_ERR_AUD_RENDER_FAILED,                            // audio render failed.
    AVCS_ERR_AUD_ENC_FAILED,                               // audio encode failed.
    AVCS_ERR_VID_ENC_FAILED,                               // video encode failed.
    AVCS_ERR_AUD_DEC_FAILED,                               // audio decode failed.
    AVCS_ERR_VID_DEC_FAILED,                               // video decode failed.
    AVCS_ERR_MUXER_FAILED,                                 // stream avmuxer failed.
    AVCS_ERR_DEMUXER_FAILED,                               // stream demuxer or parser failed.
    AVCS_ERR_OPEN_FILE_FAILED,                             // open file failed.
    AVCS_ERR_FILE_ACCESS_FAILED,                           // read or write file failed.
    AVCS_ERR_START_FAILED,                                 // audio/video start failed.
    AVCS_ERR_PAUSE_FAILED,                                 // audio/video pause failed.
    AVCS_ERR_STOP_FAILED,                                  // audio/video stop failed.
    AVCS_ERR_SEEK_FAILED,                                  // audio/video seek failed.
    AVCS_ERR_NETWORK_TIMEOUT,                              // network timeout.
    AVCS_ERR_NOT_FIND_FILE,                                // not find a file.
    AVCS_ERR_DATA_SOURCE_IO_ERROR,                         // avcodec data source IO failed.
    AVCS_ERR_DATA_SOURCE_OBTAIN_MEM_ERROR,                // avcodec data source get mem failed.
    AVCS_ERR_DATA_SOURCE_ERROR_UNKNOWN,                    // avcodec data source error unknow.
    AVCS_ERR_CODEC_PARAM_INCORRECT,                        // video codec param check failed.
    AVCS_ERR_IPC_UNKNOWN,                                  // avcodec ipc unknown err.
    AVCS_ERR_IPC_GET_SUB_SYSTEM_ABILITY_FAILED,            // avcodec ipc err, get sub system ability failed.
    AVCS_ERR_IPC_SET_DEATH_LISTENER_FAILED,                // avcodec ipc err, set death listener failed.
    AVCS_ERR_CREATE_CODECLIST_STUB_FAILED,                 // create codeclist sub service failed.
    AVCS_ERR_CREATE_AVCODEC_STUB_FAILED,                   // create avcodec sub service failed.
    AVCS_ERR_NOT_ENOUGH_DATA,                              // avcodec output buffer not full of a pack
    AVCS_ERR_END_OF_STREAM,                                // the end of stream
    AVCS_ERR_CONFIGURE_MISMATCH_CHANNEL_COUNT,             // not configure channel count attribute
    AVCS_ERR_MISMATCH_SAMPLE_RATE,                         // not configure channel sample rate
    AVCS_ERR_MISMATCH_BIT_RATE,                            // not configure channel bit rate
    AVCS_ERR_CONFIGURE_ERROR,                              // flac encoder configure compression level out of limit
    AVCS_ERR_INVALID_DATA,                                 // Invalid data found when processing input
    AVCS_ERR_DECRYPT_FAILED,                               // drm decrypt failed
    AVCS_ERR_TRY_AGAIN,                                    // try again later
    AVCS_ERR_STREAM_CHANGED,                               // output format changed
    AVCS_ERR_INPUT_DATA_ERROR,                             // there is somthing wrong for input data
    AVCS_ERR_VIDEO_UNSUPPORT_COLOR_SPACE_CONVERSION,       // video unsupport color space conversion
    AVCS_ERR_UNSUPPORTED_CODEC_SPECIFICATION,              // unsuported codec specification
    AVCS_ERR_ILLEGAL_PARAMETER_SETS,                       // illegal parameter sets
    AVCS_ERR_MINSSING_PARAMETER_SETS,                      // missing parameter sets
    AVCS_ERR_INSUFFICIENT_HARDWARE_RESOURCES,              // insufficient hardware resources
    AVCS_ERR_EXTEND_START = AVCS_ERR_OFFSET + 0xF000,      // extend err start.
} AVCodecServiceErrCode;
```

**总计 50+ 错误码**，分为以下类别：
- 基础错误（OK/NO_MEMORY/INVALID_OPERATION/INVALID_VAL/UNKNOWN/SERVICE_DIED）
- 参数类（UNSUPPORT_*_TYPE/PARAMS、MISMATCH_*、PARAM_INCORRECT）
- 操作类（START/PAUSE/STOP/SEEK/OPEN/ACCESS_FAILED）
- 编解码类（AUD/VID_ENC/DEC_FAILED、MUXER/DEMUXER_FAILED）
- DRM/加密类（DECRYPT_FAILED、DECRYTION_FAILED）
- IPC 类（IPC_UNKNOWN、CREATE_*_STUB_FAILED）
- 扩展起始：`AVCS_ERR_EXTEND_START = AVCS_ERR_OFFSET + 0xF000`

### 1.3 错误码转换函数

路径：`/home/west/av_codec_repo/interfaces/inner_api/native/avcodec_errors.h:91-97`

```cpp
__attribute__((visibility("default"))) std::string AVCSErrorToString(AVCodecServiceErrCode code);
__attribute__((visibility("default"))) OH_AVErrCode AVCSErrorToOHAVErrCode(AVCodecServiceErrCode code);
__attribute__((visibility("default"))) AVCodecServiceErrCode StatusToAVCodecServiceErrCode(Media::Status code);
__attribute__((visibility("default"))) AVCodecServiceErrCode VPEErrorToAVCSError(int32_t code);
```

三层错误流向：`VPEError` → `AVCodecServiceErrCode` → `OH_AVErrCode`（对外 C API 错误码）

---

## 二、四路回调接口体系

### 2.1 AVCodecCallback（Memory 模式，同步回调）

路径：`/home/west/av_codec_repo/interfaces/inner_api/native/avcodec_common.h:98-134`

```cpp
class AVCodecCallback {
public:
    virtual ~AVCodecCallback() = default;
    virtual void OnError(AVCodecErrorType errorType, int32_t errorCode) = 0;
    virtual void OnOutputFormatChanged(const Format &format) = 0;
    virtual void OnInputBufferAvailable(uint32_t index, std::shared_ptr<AVSharedMemory> buffer) = 0;
    virtual void OnOutputBufferAvailable(uint32_t index, AVCodecBufferInfo info, AVCodecBufferFlag flag,
                                         std::shared_ptr<AVSharedMemory> buffer) = 0;
};
```

- 用于 Memory 模式（OH_AVMemory）
- 4 个纯虚函数：OnError / OnOutputFormatChanged / OnInputBufferAvailable / OnOutputBufferAvailable
- `OnOutputBufferAvailable` 包含 `AVCodecBufferInfo`（presentationTimeUs/size/offset）+ `AVCodecBufferFlag`

### 2.2 MediaCodecCallback（Buffer 模式，异步回调）

路径：`/home/west/av_codec_repo/interfaces/inner_api/native/avcodec_common.h:172-210`

```cpp
class MediaCodecCallback {
public:
    virtual ~MediaCodecCallback() = default;
    virtual void OnError(AVCodecErrorType errorType, int32_t errorCode) = 0;
    virtual void OnOutputFormatChanged(const Format &format) = 0;
    virtual void OnInputBufferAvailable(uint32_t index, std::shared_ptr<AVBuffer> buffer) = 0;
    virtual void OnOutputBufferAvailable(uint32_t index, std::shared_ptr<AVBuffer> buffer) = 0;
    virtual void OnOutputBufferBinded(std::map<uint32_t, sptr<SurfaceBuffer>> &bufferMap) {}
    virtual void OnOutputBufferUnbinded() {}
};
```

- 用于 Buffer 模式（OH_AVBuffer）
- 相比 AVCodecCallback：使用 AVBuffer 替代 AVSharedMemory
- 新增 Surface 绑定回调：`OnOutputBufferBinded` / `OnOutputBufferUnbinded`

### 2.3 MediaCodecParameterCallback（参数回调）

路径：`/home/west/av_codec_repo/interfaces/inner_api/native/avcodec_common.h:220-231`

```cpp
class MediaCodecParameterCallback {
public:
    virtual ~MediaCodecParameterCallback() = default;
    virtual void OnInputParameterAvailable(uint32_t index, std::shared_ptr<Format> parameter) = 0;
};
```

- 用于 encoder parameter injection（API 5.0+）
- 仅 1 个回调：OnInputParameterAvailable（输入参数可用时触发）

### 2.4 MediaCodecParameterWithAttrCallback（带属性的参数回调）

路径：`/home/west/av_codec_repo/interfaces/inner_api/native/avcodec_common.h:233-247`

```cpp
class MediaCodecParameterWithAttrCallback {
public:
    virtual ~MediaCodecParameterWithAttrCallback() = default;
    virtual void OnInputParameterWithAttrAvailable(uint32_t index, std::shared_ptr<Format> attribute,
                                                   std::shared_ptr<Format> parameter) = 0;
};
```

- 比 MediaCodecParameterCallback 多一个 `attribute` 参数（只读 Format）
- 用于传入参数属性（如时间戳、来源信息）

### 2.5 AVDemuxerCallback（解封装回调）

路径：`/home/west/av_codec_repo/interfaces/inner_api/native/avcodec_common.h:158-170`

```cpp
class AVDemuxerCallback {
public:
    virtual ~AVDemuxerCallback() = default;
    virtual void OnDrmInfoChanged(const std::multimap<std::string, std::vector<uint8_t>> &drmInfo) = 0;
};
```

- 仅用于 DRM info 上报（HLS/DASH 流加密时触发）

### 2.6 回调体系与编解码模式对照

| 回调接口 | 模式 | Buffer 类型 | 典型用途 |
|---------|------|------------|---------|
| AVCodecCallback | Memory 模式 | AVSharedMemory | 传统 C API（OH_AVMemory） |
| MediaCodecCallback | Buffer 模式 | AVBuffer | 现代 C API（OH_AVBuffer） |
| MediaCodecParameterCallback | 编码器参数注入 | Format | VideoEncoder 参数下发 |
| MediaCodecParameterWithAttrCallback | 带属性的参数注入 | Format（attribute + parameter） | 高级参数传递 |
| AVDemuxerCallback | 解封装 | DRM info | DRM 内容保护 |

---

## 三、AVCodecBufferFlag 缓冲区标志位

路径：`/home/west/av_codec_repo/interfaces/inner_api/native/avcodec_common.h:58-87`

```cpp
enum AVCodecBufferFlag : uint32_t {
    AVCODEC_BUFFER_FLAG_NONE = 0,
    AVCODEC_BUFFER_FLAG_EOS = 1 << 0,                              // end of stream
    AVCODEC_BUFFER_FLAG_SYNC_FRAME = 1 << 1,                      // sync frame (I-frame)
    AVCODEC_BUFFER_FLAG_PARTIAL_FRAME = 1 << 2,                   // partial frame
    AVCODEC_BUFFER_FLAG_CODEC_DATA = 1 << 3,                       // codec specific data (SPS/PPS/VPS)
    AVCODEC_BUFFER_FLAG_DISCARD = 1 << 4,                          // discard after decoding (API 12)
    AVCODEC_BUFFER_FLAG_DISPOSABLE = 1 << 5,                       // disposable non-reference frame (API 12)
    AVCODEC_BUFFER_FLAG_DISPOSABLE_EXT = 1 << 6,                  // extended discardable frame (API 12)
    AVCODEC_BUFFER_FLAG_MUL_FRAME = 1 << 7,                       // multiple frames for LPP
};
```

8 个标志位，从 bit 0 到 bit 7：
- `EOS`：流结束
- `SYNC_FRAME`：关键帧（I-frame）
- `PARTIAL_FRAME`：分片帧
- `CODEC_DATA`：编解码器私有数据（如 H.264 SPS/PPS）
- `DISCARD`（API 12+）：解码后应丢弃的包
- `DISPOSABLE`（API 12+）：非参考帧可丢弃
- `DISPOSABLE_EXT`（API 12+）：扩展可丢弃帧（分支路径）
- `MUL_FRAME`：多帧用于 LPP（低功耗处理）

---

## 四、AVCodecBufferInfo 缓冲区元数据

路径：`/home/west/av_codec_repo/interfaces/inner_api/native/avcodec_common.h:89-97`

```cpp
struct AVCodecBufferInfo {
    /* The presentation timestamp in microseconds for the buffer */
    int64_t presentationTimeUs = 0;
    /* The amount of data (in bytes) in the buffer */
    int32_t size = 0;
    /* The start-offset of the data in the buffer */
    int32_t offset = 0;
};
```

- `presentationTimeUs`：PTS（微秒）
- `size`：数据长度（字节）
- `offset`：数据起始偏移（字节）

---

## 五、AVTimedMetaData 时间戳元数据

路径：`/home/west/av_codec_repo/interfaces/inner_api/native/avcodec_common.h:150-167`

```cpp
struct AVTimedMetaData {
    std::string id;               // Unique event identifier
    std::string classify;         // Classification label
    int64_t start{0};             // Start time in ms
    int64_t duration{0};           // Duration in ms
    std::map<std::string, std::string> contents;  // Key-value pairs
};
```

- 用于 HLS `#EXT-X-DATERANGE` 或 DASH `EventStream/Event`
- 时间单位为毫秒（ms），不同于 BufferInfo 的微秒（μs）

---

## 六、错误码与回调的 IPC 协作

在 IPC 场景下（CodecClient ↔ CodecServer），错误码通过 Binder 跨进程传递：

1. **CodecClient 侧**：`AVCSErrorToOHAVErrCode` 将服务错误码转换为对外 API 错误码
2. **CodecServer 侧**：`OnError(AVCodecErrorType, errorCode)` 触发 IPC 回调
3. **CodecClient Proxy**：通过 `CodecListenerStub` 接收跨进程回调

路径：`/home/west/av_codec_repo/services/services/codec/client/codec_client.cpp`（704 行）

```cpp
// CodecClient IPC 代理：CodecServiceProxy（客户端）
// CodecListenerStub：接收 CodecServer 回调的 Binder Stub
// CodecListenerProxy：CodecServer 侧 Proxy
```

---

## 七、与现有 S-series 记忆关联

| 关联记忆 | 关联内容 |
|---------|---------|
| S55 | AVCodec 模块间回调链路——四路回调架构（CodecCallback/MediaCodecCallback/CodecBaseCallback/CodecListenerCallback） |
| S83 | AVCodec Native C API 架构——四类 API 家族与 CodecClient IPC 代理 |
| S92 | MediaCodec 核心引擎架构——CodecState 十二态机与 Plugins::DataCallback 驱动机制 |
| S114 | MediaCodec 核心引擎架构——CodecState 十二态机与 Plugins::CodecPlugin 驱动机制 |

---

## 八、关键源码证据

| 文件 | 行号 | 说明 |
|------|------|------|
| avcodec_common.h | 37-46 | AVCodecErrorType 枚举定义 |
| avcodec_common.h | 58-87 | AVCodecBufferFlag 8 个标志位 |
| avcodec_common.h | 89-97 | AVCodecBufferInfo PTS/size/offset |
| avcodec_common.h | 98-134 | AVCodecCallback（Memory 模式）4 纯虚函数 |
| avcodec_common.h | 158-170 | AVDemuxerCallback（DRM 专用） |
| avcodec_common.h | 172-210 | MediaCodecCallback（Buffer 模式）6 函数 |
| avcodec_common.h | 220-247 | MediaCodecParameterCallback / MediaCodecParameterWithAttrCallback |
| avcodec_common.h | 150-167 | AVTimedMetaData 时间戳元数据结构 |
| avcodec_errors.h | 18-90 | AVCodecServiceErrCode 50+ 错误码枚举 |
| avcodec_errors.h | 91-97 | 错误码转换函数（AVCSErrorToString/ToOHAVErrCode/StatusToAVCS/VPEToAVCS） |

---

## 九、总结

S121 记忆覆盖了 AVCodec 错误处理与回调体系的完整三层架构：

1. **错误类型层**：`AVCodecErrorType`（4 枚举值）区分内部/扩展/解密/框架错误
2. **服务错误码层**：`AVCodecServiceErrCode`（50+ 错误码）覆盖从基础（OK/NO_MEMORY）到专业（DRM/IPC/CODEC_PARAM）的全谱系
3. **回调接口层**：4 个回调接口（AVCodecCallback/MediaCodecCallback/ParameterCallback/ParameterWithAttrCallback）覆盖 Memory 模式、Buffer 模式、参数注入、DRM 上报所有场景

三层错误码流向：`VPEError` → `AVCodecServiceErrCode` → `OH_AVErrCode`（对外 C API），转换函数确保各层错误码语义一致。