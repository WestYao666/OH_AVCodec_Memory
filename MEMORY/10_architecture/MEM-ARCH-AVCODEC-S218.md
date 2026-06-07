# MEM-ARCH-AVCODEC-S218: AVCodec Native Buffer 管理架构——OH_AVBuffer / BufferConverter / CodecBufferCircular 三层体系

## 元信息

| 字段 | 值 |
|------|-----|
| mem_id | MEM-ARCH-AVCODEC-S218 |
| 主题 | AVCodec Native Buffer 管理架构——OH_AVBuffer C API / BufferConverter 格式转换 / CodecBufferCircular 同步/异步双模式缓冲管理 |
| 分类 | 架构/内存管理 |
| 状态 | pending_approval |
|关联场景 | 音频编解码/视频编解码/Filter适配/内存管理/新人入项 |
| 基于 | GitCode web_fetch + 本地镜像 /home/west/av_codec_repo |
| git commit | ffb6baa589dc4aee672e92cc07beb96feec5a35f |
| 生成时间 | 2026-06-07 |

---

## 一、架构概述

AVCodec Buffer 管理采用**三层架构**：

```
┌─────────────────────────────────────────────────────┐
│  Layer 1: Native C API（对外接口）                    │
│  OH_AVBuffer / OH_AVMemory / OH_AVCodecBufferAttr │
│  native_avbuffer.h（SDK header）                     │
└──────────────────────┬──────────────────────────────┘
                       │封装
┌──────────────────────▼──────────────────────────────┐
│  Layer 2: BufferConverter（格式转换层）               │
│  services/services/codec/client/buffer_converter.* │
│  SurfaceFormat ↔ VideoPixelFormat ↔ YUV/RGBA │
└──────────────────────┬──────────────────────────────┘
                       │ 转换
┌──────────────────────▼──────────────────────────────┐
│  Layer 3: CodecBufferCircular（缓冲管理层）           │
│  services/services/codec/client/codec_buffer_circular.*
│  同步/异步双模式 + 输入/输出双队列                     │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│  AudioBuffersManager（音频专用缓冲池）                  │
│  services/engine/codec/audio/audio_buffers_manager.*│
│  固定大小缓冲区池 + 可用队列管理                        │
└─────────────────────────────────────────────────────┘
```

---

## 二、Native C API（Layer 1）

### 2.1 OH_AVBuffer C API

C API 定义于 `native_avbuffer.h`（SDK header，由系统提供），主要函数：

```c
// 获取 buffer 地址
uint8_t *OH_AVBuffer_GetAddr(OH_AVBuffer *buffer);

// 获取 buffer 容量
int32_t OH_AVBuffer_GetCapacity(OH_AVBuffer *buffer);

// 获取 buffer 属性（含 PTS/flags/size）
int32_t OH_AVBuffer_GetBufferAttr(OH_AVBuffer *buffer, OH_AVCodecBufferAttr *attr);

// 设置 buffer 属性
int32_t OH_AVBuffer_SetBufferAttr(OH_AVBuffer *buffer, const OH_AVCodecBufferAttr *attr);

// 获取元数据参数
OH_AVFormat *OH_AVBuffer_GetParameter(OH_AVBuffer *buffer);

// 设置元数据参数
int32_t OH_AVBuffer_SetParameter(OH_AVBuffer *buffer, OH_AVFormat *format);

// 获取底层 NativeBuffer（用于 Surface）
OH_NativeBuffer *OH_AVBuffer_GetNativeBuffer(OH_AVBuffer *buffer);

// 销毁 buffer
int32_t OH_AVBuffer_Destroy(OH_AVBuffer *buffer);
```

**Evidence E1**: `avbuffer_capi_mock.cpp` L22-L71展示了 OH_AVBuffer C API 到 C++ Mock 的完整封装（GetAddr/GetCapacity/GetBufferAttr/SetBufferAttr/GetParameter/SetParameter/Destroy/GetNativeBuffer）。

### 2.2 OH_AVCodecBufferAttr 结构

```c
// native_avcodec_base.h L97-113
typedef struct OH_AVCodecBufferAttr {
    int64_t pts;         // Presentation Time Stamp（微秒）
    int32_t flags;      // Buffer flags（EOS/KEY_FRAME 等）
    int32_t size;        // 数据大小（字节）
    int32_t offset;      // 数据偏移
} OH_AVCodecBufferAttr;
```

**Evidence E2**: `native_avcodec_base.h` L97-113定义了 OH_AVCodecBufferAttr 结构体，包含 pts/flags/size/offset 四字段。

### 2.3 C API 与 C++ Internal 的桥接

`native_avcodec_base.h`（L2355行）通过 `#include "native_avbuffer.h"` 引入 C API，并通过 `OH_AVCodecOnNeedInputBuffer`（L124）和 `OH_AVCodecOnNewOutputBuffer`（L136）回调传递 `OH_AVBuffer *`。

**Evidence E3**: `native_avcodec_base.h` L36-39包含 OH_AVCodec 声明和 NativeWindow 类型定义。

---

## 三、BufferConverter 格式转换层（Layer 2）

### 3.1 核心职责

`BufferConverter`（`buffer_converter.h` L19-37）负责：
1. **Surface → Memory 格式转换**：GraphicPixelFormat → VideoPixelFormat → YUV/RGBA
2. **内存 stride 计算**：用户 stride 与硬件 stride 的对齐
3. **Buffer格式设置**：设置 output buffer 的像素格式和尺寸

### 3.2 关键文件

| 文件 | 行数 | 职责 |
|------|------|------|
| `services/services/codec/client/buffer_converter.cpp` | 441 | 格式转换实现 |
| `services/services/codec/client/buffer_converter.h` | 73 | BufferConverter 类定义 |

### 3.3 核心方法

```cpp
// buffer_converter.h L29-32
class BufferConverter : public AVCodecDfxComponent {
public:
    static std::shared_ptr<BufferConverter> Create(AVCodecType type);
    int32_t ReadFromBuffer(std::shared_ptr<AVBuffer> &buffer, std::shared_ptr<AVSharedMemory> &memory);
    int32_t WriteToBuffer(std::shared_ptr<AVBuffer> &buffer, std::shared_ptr<AVSharedMemory> &memory);
    // ...
};
```

**Evidence E4**: `buffer_converter.h` L19-37定义了 BufferConverter 类，Create/ReadFromBuffer/WriteToBuffer 三个静态/实例方法。

### 3.4 SurfaceFormat → VideoPixelFormat 转换矩阵

```cpp
// buffer_converter.cpp L35-62
VideoPixelFormat TranslateSurfaceFormat(GraphicPixelFormat surfaceFormat)
{
    switch (surfaceFormat) {
        case GRAPHIC_PIXEL_FMT_YCBCR_420_P: return YUVI420;
        case GRAPHIC_PIXEL_FMT_RGBA_8888:    return RGBA;
        case GRAPHIC_PIXEL_FMT_YCBCR_P010:
        case GRAPHIC_PIXEL_FMT_YCBCR_420_SP: return NV12;
        case GRAPHIC_PIXEL_FMT_YCRCB_P010:
        case GRAPHIC_PIXEL_FMT_YCRCB_420_SP: return NV21;
        default: return UNKNOWN;
    }
}
```

**Evidence E5**: `buffer_converter.cpp` L35-62定义了 SurfaceFormat → VideoPixelFormat 转换矩阵，支持 YUVI420/RGBA/NV12/NV21 四种格式。

### 3.5 ReadFromBuffer / WriteToBuffer

**Evidence E6**: `buffer_converter.cpp` L182-209实现了 ReadFromBuffer（AVBuffer → AVSharedMemory），处理 YUV420SP 格式转换和 padding 填充。

**Evidence E7**: `buffer_converter.cpp` L211-309实现了 WriteToBuffer（AVSharedMemory → AVBuffer），包含 SetBufferFormat 和 CalculateUserStride 调用。

### 3.6 SetBufferFormat 与 stride 计算

```cpp
// buffer_converter.cpp L366-415
bool BufferConverter::SetBufferFormat(std::shared_ptr<AVBuffer> &buffer)
{
    // 获取 SurfaceBuffer 并获取格式
    VideoPixelFormat pixelFormat = TranslateSurfaceFormat(
        static_cast<GraphicPixelFormat>(surfaceBuffer->GetFormat()));
    // 设置 stride宽高
    usrRect_.wStride = std::min(hwRect_.wStride, CalculateUserStride(width) * tempPixelSize);
    usrRect_.hStride = std::min(hwRect_.hStride, CalculateUserStride(height));
}

inline int32_t BufferConverter::CalculateUserStride(const int32_t widthHeight)
{
    // 对齐到 2 的幂次
    return ((widthHeight + OFFSET_15) & ~OFFSET_15) + OFFSET_2;
}
```

**Evidence E8**: `buffer_converter.cpp` L366-415实现了 SetBufferFormat，包含 SurfaceBuffer 格式解析和 CalculateUserStride 计算。

---

## 四、CodecBufferCircular 缓冲管理层（Layer 3）

### 4.1 核心职责

`CodecBufferCircular`（`codec_buffer_circular.h` L19-86）是 AVCodec Client 端的核心缓冲管理器：
- **双模式支持**：同步模式（QueryInputBuffer/QueryOutputBuffer 阻塞等待）和异步模式（回调驱动）
- **双缓冲队列**：input buffer 队列（inCache_）和 output buffer 队列（outCache_）
- **Buffer生命周期管理**：追踪 OWNED_BY_SERVER / OWNED_BY_CLIENT / OWNED_BY_USER 三态

### 4.2 关键文件

| 文件 | 行数 | 职责 |
|------|------|------|
| `services/services/codec/client/codec_buffer_circular.cpp` | 791 | 缓冲管理实现 |
| `services/services/codec/client/codec_buffer_circular.h` | 188 | CodecBufferCircular 类定义 |

### 4.3 关键方法

| 方法 | 行号 | 职责 |
|------|------|------|
| `HandleInputBuffer(uint32_t, AVCodecBufferInfo, AVCodecBufferFlag)` | L195 | 处理输入 buffer（带 info/flag） |
| `HandleInputBuffer(uint32_t)` | L226 | 处理输入 buffer（简化版） |
| `HandleOutputBuffer(uint32_t)` | L247 | 处理输出 buffer |
| `QueueInputBufferDone(uint32_t, bool)` | L268 | 标记输入 buffer 完成 |
| `ReleaseOutputBufferDone(uint32_t, bool)` | L290 | 释放输出 buffer |
| `QueryInputBuffer(uint32_t &, int64_t)` | L648 | 同步模式查询输入 buffer |
| `QueryOutputBuffer(uint32_t &, int64_t)` | L653 | 同步模式查询输出 buffer |
| `GetInputBuffer(uint32_t)` | L762 | 获取输入 buffer 对象 |
| `GetOutputBuffer(uint32_t)` | L777 | 获取输出 buffer 对象 |

**Evidence E9**: `codec_buffer_circular.h` L56-86定义了 CodecBufferCircular 的双模式接口（同步 Query* + 异步 Handle*）。

**Evidence E10**: `codec_buffer_circular.cpp` L195-265实现了 HandleInputBuffer/HandleOutputBuffer，包含 buffer 属性设置和 owner 状态转换。

### 4.4 同步/异步双模式切换

```cpp
// codec_buffer_circular.h L103-115
template <ModeType mode>
inline bool CanEnableMode()
{
    bool isUnconfigured = !HasFlag(FLAG_SYNC_ASYNC_CONFIGURED);
    bool modeMatched = !HasFlag(FLAG_IS_SYNC);
    if constexpr (mode == MODE_SYNC) {
        modeMatched = HasFlag(FLAG_IS_SYNC);
    }
    return isUnconfigured || modeMatched;
}

template <ModeType mode>
inline void EnableMode()
{
    if constexpr (mode == MODE_SYNC) {
        AddFlag(FLAG_IS_SYNC);
    }
    AddFlag(FLAG_SYNC_ASYNC_CONFIGURED);
}
```

**Evidence E11**: `codec_buffer_circular.h` L103-115使用 C++17 if constexpr 实现编译期模式切换（SYNC/ASYNC），FLAG_SYNC_ASYNC_CONFIGURED 标志保证只切换一次。

### 4.5 Buffer Owner 状态机

```cpp
// codec_buffer_circular.h L93-95
typedef enum : uint8_t {
    OWNED_BY_SERVER = 0,
    OWNED_BY_CLIENT = 1,
    OWNED_BY_USER = 2,
} BufferOwner;
```

**Evidence E12**: `codec_buffer_circular.h` L93-95定义了 Buffer Owner 三态枚举，用于追踪 buffer 所有权在 Server/Client/User 之间的转移。

---

## 五、AudioBuffersManager 音频缓冲池（Layer 3 音频专用）

### 5.1 核心职责

`AudioBuffersManager`（`audio_buffers_manager.h` L21-48）管理音频编解码器的固定大小缓冲区池：
- **池化分配**：预先分配固定数量的 buffer
- **可用队列**：`inBufIndexQue_` 追踪可用 buffer索引
- **原子状态**：`std::atomic<bool> isRunning_` 控制运行状态

### 5.2 关键文件

| 文件 | 行数 | 职责 |
|------|------|------|
| `services/engine/codec/audio/audio_buffers_manager.cpp` | 160 | 音频缓冲池实现 |
| `services/engine/codec/include/audio/audio_buffers_manager.h` | 72 | AudioBuffersManager 类定义 |
| `services/engine/codec/include/audio/audio_buffer_info.h` | 95 | AudioBufferInfo 单 buffer 封装 |

### 5.3 AudioBufferInfo 单 Buffer 封装

```cpp
// audio_buffer_info.h L30-59
class AudioBufferInfo : public NoCopyable {
    std::shared_ptr<Media::AVSharedMemoryBase> buffer_; // 主数据 buffer
    std::shared_ptr<Media::AVSharedMemoryBase> metadata_; // 元数据 buffer
    AVCodecBufferInfo info_;   // PTS/size/offset
    AVCodecBufferFlag flag_;  // EOS/KEY_FRAME 等标志
    std::atomic<BufferStatus> status_;  // 占用状态
    std::atomic<bool> isUsing;         // 是否使用中
};
```

**Evidence E13**: `audio_buffer_info.h` L30-59定义了 AudioBufferInfo 类，包含双 AVSharedMemoryBase（buffer_ + metadata_）和原子状态管理。

### 5.4 AudioBuffersManager 缓冲池管理

```cpp
// audio_buffers_manager.cpp L39-48
AudioBuffersManager::AudioBuffersManager(const uint32_t bufferSize,
    const std::string_view &name, const uint16_t count, const uint32_t metaSize)
    : isRunning_(true),
      inBufIndexExist(count, false),
      bufferCount_(count),
      bufferSize_(bufferSize),
      metaSize_(metaSize),
      name_(name),
      bufferInfo_(count)  // 预分配 count 个 AudioBufferInfo
{
    initBuffers();
}
```

**Evidence E14**: `audio_buffers_manager.cpp` L39-48构造时预分配 bufferInfo_(count) 向量，initBuffers() 初始化所有 buffer。

### 5.5 RequestNewBuffer 请求新 Buffer

```cpp
// audio_buffers_manager.h L27-28
bool RequestNewBuffer(uint32_t &index, std::shared_ptr<AudioBufferInfo> &buffer);
bool RequestAvailableIndex(uint32_t &index);  // 从队列取可用索引
```

**Evidence E15**: `audio_buffers_manager.h` L27-28定义了请求新 buffer 和请求可用索引的接口。

---

## 六、AVSharedMemory 共享内存层

### 6.1 AVSharedMemory 类型别名

```cpp
// av_common.h L28-29
using AVSharedMemory = Media::AVSharedMemory;

// avcodec_common.h L29
using AVSharedMemory = OHOS::Media::AVSharedMemory;
```

### 6.2 AudioBufferInfo 中的 AVSharedMemory

```cpp
// audio_buffer_info.h L37-38
std::shared_ptr<Media::AVSharedMemoryBase> GetBuffer() const noexcept;
std::shared_ptr<Media::AVSharedMemoryBase> GetMetadata() const noexcept;
```

**Evidence E16**: `audio_buffer_info.h` L37-38定义了 GetBuffer/GetMetadata 方法返回 AVSharedMemoryBase shared_ptr。

---

## 七、AVCodecBufferInfo / AVCodecBufferFlag 结构

```cpp
// avcodec_common.h L54-58
enum AVCodecBufferFlag : uint32_t {
    // EOS/KEY_FRAME 等标志位
};

struct AVCodecBufferInfo {
    int64_t pts;
    int32_t size;
    int32_t offset;
    int64_t duration;
};

struct AVCodecBufferAttr {
    int64_t pts;
    int32_t flags;
    int32_t size;
    int32_t offset;
};
```

**Evidence E17**: `avcodec_common.h` L54-88定义了 AVCodecBufferFlag枚举和 AVCodecBufferInfo/AVCodecBufferAttr 结构体家族。

---

## 八、关键设计模式

### 8.1 CodecBufferCircular 双队列设计

```
inCache_  (BufferCache = unordered_map<uint32_t, BufferItem>)
    ├── index0 → BufferItem { buffer, memory, parameter, attribute, owner=OWNED_BY_SERVER }
    ├── index 1 → BufferItem { ... }
    └── ...

outCache_ (BufferCache = unordered_map<uint32_t, BufferItem>)
    ├── index 0 → BufferItem { ... }
    └── ...
```

同步模式：EventQueue + condition_variable 等待
异步模式：回调直接驱动

**Evidence E18**: `codec_buffer_circular.h` L121-122定义 BufferCache = unordered_map<uint32_t, BufferItem>，双队列 inCache_/outCache_ 使用 std::mutex保护。

---

## 九、关联记忆

| S# | 关联主题 | 关系 |
|----|---------|------|
| S212 | VideoDecoderAdapter | 使用 CodecBufferCircular 作为回调桥接层 |
| S214 | SurfaceEncoderAdapter | 使用 BufferConverter 处理 Surface 输入 |
| S200 | AVCodec Memory DFX | DFX 层监控 buffer 生命周期 |
| S55 | CodecCallback | CodecBufferCircular 的回调目标 |
| S125 | FFmpeg Adapter | BufferConverter 处理 FFmpeg 与 native buffer 的转换 |

---

## 十、Evidence汇总

| ID | 文件 | 行号 | 内容 |
|----|------|------|------|
| E1 | `avbuffer_capi_mock.cpp` |22-71 | OH_AVBuffer C API 完整封装 |
| E2 | `native_avcodec_base.h` | 97-113 | OH_AVCodecBufferAttr 结构体定义 |
| E3 | `native_avcodec_base.h` | 36-39 | OH_AVCodec 声明和 NativeWindow 类型 |
| E4 | `buffer_converter.h` | 19-37 | BufferConverter 类定义 |
| E5 | `buffer_converter.cpp` | 35-62 | SurfaceFormat → VideoPixelFormat 转换矩阵 |
| E6 | `buffer_converter.cpp` | 182-209 | ReadFromBuffer AVBuffer→AVSharedMemory |
| E7 | `buffer_converter.cpp` | 211-309 | WriteToBuffer AVSharedMemory→AVBuffer |
| E8 | `buffer_converter.cpp` | 366-415 | SetBufferFormat + CalculateUserStride |
| E9 | `codec_buffer_circular.h` | 56-86 | CodecBufferCircular 双模式接口 |
| E10 | `codec_buffer_circular.cpp` | 195-265 | HandleInputBuffer/HandleOutputBuffer |
| E11 | `codec_buffer_circular.h` | 103-115 | C++17 if constexpr模式切换 |
| E12 | `codec_buffer_circular.h` | 93-95 | BufferOwner 三态枚举 |
| E13 | `audio_buffer_info.h` | 30-59 | AudioBufferInfo 类定义 |
| E14 | `audio_buffers_manager.cpp` | 39-48 | AudioBuffersManager 构造预分配 |
| E15 | `audio_buffers_manager.h` | 27-28 | RequestNewBuffer/RequestAvailableIndex 接口 |
| E16 | `audio_buffer_info.h` | 37-38 | GetBuffer/GetMetadata 返回 AVSharedMemoryBase |
| E17 | `avcodec_common.h` | 54-88 | AVCodecBufferFlag/AVCodecBufferInfo |
| E18 | `codec_buffer_circular.h` | 121-122 | BufferCache = unordered_map 定义 |

---

## 附录：行号级 Evidence源文件索引

| 文件路径 | 总行数 |
|---------|--------|
| `services/services/codec/client/buffer_converter.cpp` | 441 |
| `services/services/codec/client/buffer_converter.h` | 73 |
| `services/services/codec/client/codec_buffer_circular.cpp` | 791 |
| `services/services/codec/client/codec_buffer_circular.h` | 188 |
| `services/engine/codec/audio/audio_buffers_manager.cpp` | 160 |
| `services/engine/codec/include/audio/audio_buffers_manager.h` | 72 |
| `services/engine/codec/include/audio/audio_buffer_info.h` | 95 |
| `interfaces/inner_api/native/avcodec_common.h` | 306 |
| `interfaces/inner_api/native/av_common.h` | 247 |
| `interfaces/kits/c/native_avcodec_base.h` | 2355 |
| `test/unittest/common/common_mock/avbuffer/capi/avbuffer_capi_mock.cpp` | ~200 |