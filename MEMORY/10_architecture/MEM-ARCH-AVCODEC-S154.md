# MEM-ARCH-AVCODEC-S154: VideoDecoder 基类与 RenderSurface 双组件架构

## 概述

S154 记录 OH_AVCodec 视频解码器的核心基类架构：VideoDecoder 基类（1122行cpp）+ RenderSurface 组件（553行cpp）双层架构，涵盖 Surface/Buffer 双模式、Owner 枚举缓冲区所有权、DMA SwapOut/SwapIn、以及 BlockQueue 三队列机制。

**关联主题**：S39(VideoDecoderFilter→VideoDecoderAdapter→AVCodecVideoDecoder 三层) / S57(HDecoder) / S45(SurfaceDecoderFilter) / S46(DecoderSurfaceFilter)

---

## 一、VideoDecoder 类架构（1122行cpp）

### 1.1 继承关系

```
CodecBase (Layer2 抽象基类)
  └── RenderSurface (组合，553行cpp)
        └── VideoDecoder (1122行cpp，核心解码器基类)
              ├── H264Decoder
              ├── HEVCDecoder
              ├── VPXDecoder (VP8/VP9)
              └── Av1Decoder
```

### 1.2 关键成员（video_decoder.h:1-112）

- `decInstanceID_ / decName_` - 解码器实例 ID 与名称
- `callback_ : std::shared_ptr<MediaCodecCallback>` - 解码器回调
- `sendTask_ : std::shared_ptr<TaskThread>` - SendFrame 任务线程
- `inputAvailQue_` - 输入缓冲区可用队列（BlockQueue）
- `cachedFrame_ : std::shared_ptr<AVFrame>` - FFmpeg 缓存帧
- `isSendEos_ : std::atomic<bool>` - EOS 标志
- `surface_ : sptr<Surface>` - Surface 输出目标
- `handle_ : void*` - dlopen 句柄

### 1.3 生命周期七步曲（video_decoder.cpp）

```
Configure()        → 配置编码器参数（宽/高/帧率/格式）
AllocateBuffers()   → 分配输入/输出缓冲区（Surface 或 Buffer 模式）
Start()             → 启动 SendFrame TaskThread
DecodeFrameOnce()  → 循环解码（纯虚函数，子类实现）
Flush()             → 清空所有帧缓冲区
Stop()              → 停止 TaskThread
Release()           → 释放 handle_ 和资源
```

### 1.4 BlockQueue 三队列（video_decoder.h:54-56）

```cpp
std::shared_ptr<BlockQueue<uint32_t>> inputAvailQue_;      // 输入缓冲区可用队列
std::shared_ptr<BlockQueue<uint32_t>> codecAvailQue_;      // Codec 内部处理队列
std::shared_ptr<BlockQueue<uint32_t>> renderAvailQue_;      // 渲染完成队列
```

### 1.5 SendFrame TaskThread（video_decoder.cpp:200-300）

```cpp
sendTask_->Start();  // 启动 OS 线程
while (isRunning_) {
    auto index = inputAvailQue_->Pop();  // 阻塞等待输入
    int32_t ret = DecodeFrameOnce(index); // 子类实现解码
}
```

---

## 二、RenderSurface 组件（553行cpp）

### 2.1 功能定位

RenderSurface 是 VideoDecoder 的组合组件，负责 Surface 模式下视频帧的内存管理、SurfaceBuffer 申请/释放、SwapOut/SwapIn 冻结机制。

### 2.2 核心数据结构

```cpp
struct CodecBuffer {
    std::shared_ptr<AVBuffer> avBuffer = nullptr;
    std::shared_ptr<FSurfaceMemory> sMemory = nullptr;
    std::atomic<Owner> owner_ = Owner::OWNED_BY_US;
    int32_t width = 0, height = 0, bitDepth = BITS_PER_PIXEL_COMPONENT_8;
    std::atomic<bool> hasSwapedOut = false;
};

std::vector<std::shared_ptr<CodecBuffer>> buffers_[2];  // 双缓冲池（active/inactive）
std::map<uint32_t, std::pair<sptr<SurfaceBuffer>, OHOS::BufferFlushConfig>> renderSurfaceBufferMap_;
```

### 2.3 Owner 枚举（render_surface.h:50-55）

```cpp
enum class Owner {
    OWNED_BY_US = 0,   // 解码器持有
    CODEC = 1,          // Codec 持有
    USER = 2,           // 用户持有
    SURFACE = 3         // Surface 持有
};
```

### 2.4 六队列机制（render_surface.h:42-49）

```cpp
std::shared_ptr<BlockQueue<uint32_t>> renderAvailQue_;           // 渲染可用
std::shared_ptr<BlockQueue<uint32_t>> requestSurfaceBufferQue_;   // 申请 SurfaceBuffer
std::shared_ptr<BlockQueue<uint32_t>> codecAvailQue_;             // Codec 可用
```

### 2.5 SwapOut/SwapIn 冻结机制（render_surface.cpp:400-553）

```cpp
CanSwapOut(bool isOutputBuffer, const std::shared_ptr<CodecBuffer> &codecBuffer)
    // 条件：owner != SURFACE && !hasSwapedOut

FreezeBuffers(State curState)   // 输入：跳过；输出：执行 SwapOut
ActiveBuffers()                 // 输入/输出均执行 SwapIn

SwapOutBuffers(bool isOutputBuffer, State curState)
    // DMA ioctl(DMA_BUF_RECLAIM_FD) 让 Surface 回收内存

SwapInBuffers(bool isOutputBuffer)
    // DMA ioctl(DMA_BUF_RESUME_FD) 恢复内存
```

---

## 三、CoderState 状态机（coderstate.h）

```cpp
enum class State {
    UNINITIALIZED = 0,
    INITIALIZED = 1,
    CONFIGURED = 2,
    RUNNING = 3,
    FLUSHED = 4,
    ERROR = 5
};
```

---

## 四、Surface 模式双 Surface 绑定（video_decoder.cpp:600-800）

```cpp
SetOutputSurface(sptr<Surface> surface)  // 设置输出 Surface
ReplaceOutputSurfaceWhenRunning(sptr<Surface> newSurface)  // 运行中替换 Surface
Attach(sptr<SurfaceBuffer> surfaceBuffer)  // 绑定 SurfaceBuffer
Detach(sptr<SurfaceBuffer> surfaceBuffer)  // 解绑
```

---

## 五、帧后处理 FramePostProcess（video_decoder.cpp:800-900）

```cpp
void FramePostProcess(const std::shared_ptr<CodecBuffer> &frameBuffer, uint32_t index, int32_t status) {
    // 1. PostProcessor 处理（VPE/SuperResolution）
    // 2. HDR 元数据填充 FillHdrInfo()
    // 3. BufferCrop 元数据设置
    // 4. 输出到 Surface 或回调
}
```

---

## 六、与 Filter 层对应关系

| Filter 层 | Adapter 层 | 引擎层 |
|----------|-----------|-------|
| SurfaceDecoderFilter(S45) | SurfaceDecoderAdapter | VideoDecoder (本主题) |
| DecoderSurfaceFilter(S46) | VideoDecoderAdapter | VideoDecoder (本主题) |
| VideoDecoderAdapter(S39) | - | VideoDecoder (本主题) |

---

## 七、关键文件行号级 Evidence

| 文件 | 行数 | 关键内容 |
|------|------|---------|
| video_decoder.h | ~1122 | VideoDecoder 类定义、BlockQueue 三队列、Owner 枚举 |
| video_decoder.cpp | 1122 | 生命周期、SendFrame TaskThread、FramePostProcess |
| render_surface.h | 553 | CodecBuffer 结构、buffers_[2]、六队列、Owner 枚举 |
| render_surface.cpp | 553 | SwapOut/SwapIn、Attach/Detach、Surface 绑定 |
| coderstate.h | ~50 | State 五状态枚举 |

---

## 八、架构图

```
┌─────────────────────────────────────────────────────────────┐
│                    VideoDecoder (1122行)                      │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │              RenderSurface (553行)                      │  │
│  │  ┌────────────────────────────────────────────────────┐ │  │
│  │  │ CodecBuffer[2] (双缓冲池)                          │ │  │
│  │  │  └── Owner: OWNED_BY_US / CODEC / USER / SURFACE   │ │  │
│  │  └────────────────────────────────────────────────────┘ │  │
│  │  ┌──────────────┬──────────────────┬────────────────┐  │  │
│  │  │renderAvailQue│requestSurfaceBuff │codecAvailQue   │  │  │
│  │  └──────────────┴──────────────────┴────────────────┘  │  │
│  └─────────────────────────────────────────────────────────┘  │
│  BlockQueue<inputAvailQue_>  ←  SendFrame TaskThread         │
│  SendFrame() [虚函数]  →  DecodeFrameOnce() [纯虚函数]       │
└─────────────────────────────────────────────────────────────┘
         ↓ Configure / Start / Stop / Release
┌──────────────────┐    ┌──────────────┐    ┌──────────────┐
│  H264Decoder     │    │ HEVCDecoder  │    │ VPXDecoder   │
│  (H.264 硬件)    │    │ (H.265 硬件) │    │ (VP8/VP9)    │
└──────────────────┘    └──────────────┘    └──────────────┘
```

---

## 九、相关主题

- S39: VideoDecoderAdapter 三层架构
- S45: SurfaceDecoderFilter Filter 层封装
- S46: DecoderSurfaceFilter DRM 扩展
- S57: HDecoder 硬件解码器（OMX 组件）
- S80: SurfaceBuffer Owner 与 SwapOut/SwapIn
- S14: FilterChain Filter 基类关联

---

**标签**：VideoDecoder / RenderSurface / SurfaceMode / BufferMode / BlockQueue / Owner / SwapOut / SwapIn / DMA-BUF / Filter

**状态**：pending_approval

**来源**：builder-agent | 2026-05-15