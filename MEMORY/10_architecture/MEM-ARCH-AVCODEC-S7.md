---
id: MEM-ARCH-AVCODEC-S7
title: SurfaceBuffer 与 RenderSurface 内存管理——Owner 枚举、FSCallback 与三队列机制
scope: [AVCodec, SurfaceBuffer, MemoryManagement, RenderSurface, Owner, ZeroCopy]
status: draft
created_at: "2026-04-22T17:45:00+08:00"
author: builder-agent
evidence_sources:
  - local_repo: /home/west/av_codec_repo
  - services/engine/common/include/fsurface_memory.h
  - services/engine/codec/video/decoderbase/render_surface.h
  - services/engine/codec/video/decoderbase/render_surface.cpp
  - services/engine/common/dma_swap.cpp
related_scenes: [新需求开发, 问题定位, Surface Mode, 后台切换, ZeroCopy]
summary: >
  AVCodec Surface 模式下解码器输出帧的内存管理围绕 SurfaceBuffer + FSurfaceMemory + RenderSurface 三者展开。
  FSurfaceMemory 封装 SurfaceBuffer 的申请/释放/所有权变更，Owner 枚举（OWNED_BY_US/CODEC/USER/SURFACE）追踪每个 buffer 的当前管理者。
  RenderSurface 管理双缓冲池（buffers_[2]）与三队列（renderAvailQue/requestSurfaceBufferQue/codecAvailQue），通过 FSCallback 联动 codec 与 surface consumer 的生命周期。
  后台冻结时 FreezeBuffers() 对 output buffers 执行 DMA SwapOut，恢复时 ActiveBuffers() 执行 SwapIn，全程无 CPU 拷贝。
why_it_matters:
 - 问题定位：视频花屏/卡死常因 Owner 状态不一致导致错误释放；需区分 OWNED_BY_SURFACE 时不可 SwapOut、OWNED_BY_USER 时不可 Render 等约束
 - 新需求开发：RenderSurface 三队列是 Surface Mode 数据流的核心，理解各队列状态才能正确接入自定义 surface 或多实例场景
 - 后台管理：FreezeBuffers/ActiveBuffers 依赖 Owner 检查；开发者若自行管理 SurfaceBuffer 生命周期会破坏 DMA Swap 前提条件
 - 性能分析：ZeroCopy 路径省去 CPU 拷贝的关键是 SurfaceBuffer 始终在 OWNED_BY_SURFACE 状态直接传递给 GPU
---

## 1. 核心组件分层

AVCodec Surface Mode 内存管理涉及三层结构：

| 层级 | 类名 | 职责 | 所在文件 |
|------|------|------|----------|
| 底层 | `SurfaceBuffer` | GBM 分配的视频帧内存（物理页） | GFX子系统 |
| 中间层 | `FSurfaceMemory` | SurfaceBuffer 的封装 + Owner 管理 | `fsurface_memory.h/cpp` |
| 上层 | `RenderSurface` | Codec 侧 buffer 池管理 + 三队列 + DMA Swap | `render_surface.h/cpp` |

---

## 2. FSurfaceMemory：SurfaceBuffer 的封装与 Owner 管理

### 2.1 Owner 枚举（四态机）

**证据**：`services/engine/common/include/fsurface_memory.h` 行 27-32

```cpp
enum class Owner {
    OWNED_BY_US,       // Codec 自身持有（初始状态）
    OWNED_BY_CODEC,    // OMX codec 组件持有
    OWNED_BY_USER,     // 用户层（应用）持有
    OWNED_BY_SURFACE,  // Surface（GPU消费）持有
};
```

**RenderSurface::CodecBuffer 中的 Owner 状态**（`render_surface.h` 行 57）：

```cpp
struct CodecBuffer {
    std::shared_ptr<AVBuffer> avBuffer = nullptr;
    std::shared_ptr<FSurfaceMemory> sMemory = nullptr;
    std::atomic<Owner> owner_ = Owner::OWNED_BY_US;  // 初始为 US
    std::atomic<bool> hasSwapedOut = false;            // DMA Swap 状态
};
```

### 2.2 FSurfaceMemory 核心方法

```cpp
// fsurface_memory.h
class FSurfaceMemory {
    sptr<SurfaceBuffer> surfaceBuffer_ = nullptr;
    sptr<SyncFence> fence_ = nullptr;
    std::atomic<Owner> owner = Owner::OWNED_BY_US;
    std::atomic<bool> isAttached = false;

public:
    int32_t AllocSurfaceBuffer(int32_t width, int32_t height);  // 请求 Surface 分配 buffer
    void ReleaseSurfaceBuffer();                                 // 释放 buffer（回池）
    sptr<SurfaceBuffer> GetSurfaceBuffer();                     // 获取 SurfaceBuffer
    void SetSurfaceBuffer(sptr<SurfaceBuffer>, Owner toChangeOwner, sptr<SyncFence> fence = nullptr);
    uint8_t *GetBase() const;    // 获取 CPU 可访问虚拟地址
    int32_t GetSize() const;     // 获取 buffer 大小
    sptr<SyncFence> GetFence();  // 获取同步 fence（用于 GPU 渲染完成信号）
};
```

**AllocSurfaceBuffer 源码证据**（`fsurface_memory.cpp`）：
```cpp
int32_t FSurfaceMemory::AllocSurfaceBuffer(int32_t width, int32_t height)
{
    // 调用 sInfo_->surface->RequestBuffer(requestConfig) 获取 SurfaceBuffer
    // 设置 isAttached = true, owner = OWNED_BY_US
    // 结合 BUFFER_USAGE_MEM_DMA 保证 DMA-BUF 可用
}
```

### 2.3 SetSurfaceBuffer 与 Owner 转换

```cpp
// fsurface_memory.cpp
void FSurfaceMemory::SetSurfaceBuffer(sptr<SurfaceBuffer> surfaceBuffer, Owner toChangeOwner, sptr<SyncFence> fence)
{
    surfaceBuffer_ = surfaceBuffer;
    fence_ = fence;
    owner.store(toChangeOwner);  // 原子切换所有者
    AVCODEC_LOGD("SurfaceBuffer owner changed to: %{public}d", toChangeOwner);
}
```

**Owner 状态转换规则**：

```
[OWNED_BY_US] ─── Codec 填充数据 ───→ [OWNED_BY_CODEC]
    ↑                                    │
    │                                Render/
    │                              AttachBuffer
    │                                    │
    │                                    ▼
    │                              [OWNED_BY_SURFACE]
    │                                    │
    │                               Consumer 释放
    │                                    │
    └─────────────────────────── SurfaceBuffer 回池
```

### 2.4 BUFFER_USAGE_MEM_DMA 必须性

**证据**：`render_surface.cpp` 行 68-72

```cpp
uint64_t defaultUsage = BUFFER_USAGE_CPU_READ | BUFFER_USAGE_CPU_WRITE | BUFFER_USAGE_MEM_DMA;
uint64_t consumerUsage = sInfo_.surface->GetDefaultUsage();
uint64_t cfgedUsage = sInfo_.requestConfig.usage;
uint64_t finalUsage = defaultUsage | consumerUsage | cfgedUsage;
sInfo_.requestConfig.usage = finalUsage;
```

**没有 BUFFER_USAGE_MEM_DMA**：`surfaceBuffer->GetFileDescriptor()` 返回无效 fd，DMA Swap 路径完全失效。

---

## 3. RenderSurface：三队列与双缓冲池

### 3.1 三队列机制

```cpp
// render_surface.h
std::shared_ptr<BlockQueue<uint32_t>> renderAvailQue_;          // 可渲染的 buffer 序号
std::shared_ptr<BlockQueue<uint32_t>> requestSurfaceBufferQue_;  // 待向 Surface 请求的序号
std::shared_ptr<BlockQueue<uint32_t>> codecAvailQue_;            // Codec 可用的 buffer 序号
```

**队列语义**：

| 队列 | 内容 | 生产者 | 消费者 |
|------|------|--------|--------|
| `requestSurfaceBufferQue_` | 待请求 SurfaceBuffer 的 index | CodecServer | RenderSurface 线程 |
| `codecAvailQue_` | Codec 可填充数据的空 buffer index | RenderSurface（Attach后） | Codec |
| `renderAvailQue_` | 已填充完毕、可渲染的 index | Codec 填充完成 | 应用/Surface consumer |

**数据流**：

```
requestSurfaceBufferQue_ → [RequestSurfaceBufferThread] → codecAvailQue_
                                                        ↓（Codec 填充 YUV 数据）
                                                     renderAvailQue_
                                                        ↓（应用/自动 Render）
                                                     Surface consumer
```

### 3.2 双缓冲池结构

```cpp
// render_surface.h
std::vector<std::shared_ptr<CodecBuffer>> buffers_[2];
// buffers_[0] = INDEX_INPUT（输入缓冲，未使用）
// buffers_[1] = INDEX_OUTPUT（输出缓冲，主要使用）
```

每个 `CodecBuffer` 包含：
- `avBuffer`：AVBuffer 包装
- `sMemory`：FSurfaceMemory（SurfaceBuffer 的封装）
- `owner_`：当前所有者（Owner 枚举）
- `hasSwapedOut_`：是否已 DMA SwapOut

### 3.3 FSCallback：Codec↔Surface 生命周期联动

**证据**：`render_surface.cpp` 行 83-98（RegisterListenerToSurface）

```cpp
bool ret = SurfaceTools::GetInstance().RegisterReleaseListener(instanceId_, surface,
    [wp, surfaceId](sptr<SurfaceBuffer> &) {
        sptr<RenderSurface> codec = wp.promote();
        if (!codec) return GSERROR_OK;
        return codec->BufferReleasedByConsumer(surfaceId);  // Surface consumer 释放时触发
    });
```

**BufferReleasedByConsumer 完整路径**（`render_surface.cpp`）：

```cpp
GSError RenderSurface::BufferReleasedByConsumer(uint64_t surfaceId)
{
    std::lock_guard<std::mutex> lock(outputMutex_);
    // 从 renderSurfaceBufferMap_ 中找到释放的 buffer 对应的 index
    // 调用 Attach(index) → 将 SurfaceBuffer 重新 Attach 到 CodecBuffer
    // 设置 owner = OWNED_BY_US（Codec 重新持有）
    // codecAvailQue_->Push(index) → buffer 重新可用
}
```

---

## 4. FreezeBuffers / ActiveBuffers 与 DMA Swap（后台内存管理）

### 4.1 RenderSurface 中的 FreezeBuffers

**证据**：`render_surface.cpp` 行 436-448

```cpp
int32_t RenderSurface::FreezeBuffers(State curState)
{
    std::lock_guard<std::mutex> sLock(surfaceMutex_);
    int32_t ret = SwapOutBuffers(INDEX_INPUT, curState);  // INPUT 实际跳过多检查
    CHECK_AND_RETURN_RET_LOG(ret == AVCS_ERR_OK, ret, "Input buffers swap out failed!");
    ret = SwapOutBuffers(INDEX_OUTPUT, curState);
    CHECK_AND_RETURN_RET_LOG(ret == AVCS_ERR_OK, ret, "Output buffers swap out failed!");
    AVCODEC_LOGI("Freeze buffers success");
    return AVCS_ERR_OK;
}
```

**SwapOut 约束**（`render_surface.cpp` 行 460-473）：

```cpp
bool RenderSurface::CanSwapOut(bool isOutputBuffer, const std::shared_ptr<CodecBuffer> &codecBuffer)
{
    // 仅有 Output buffers 可 SwapOut（INPUT 不可）
    CHECK_AND_RETURN_RET_LOGD(bufferType == INDEX_OUTPUT, AVCS_ERR_OK, "Input buffers can't be swapped out!");
    Owner ownerValue = surfaceMemory->owner;
    // 关键：只有 OWNED_BY_SURFACE 或已 SwapOut 才不可冻结
    return !(ownerValue == Owner::OWNED_BY_SURFACE || codecBuffer->hasSwapedOut.load());
}
```

**可冻结条件**：`owner == OWNED_BY_US || OWNED_BY_CODEC || OWNED_BY_USER`
**不可冻结条件**：`owner == OWNED_BY_SURFACE`（GPU 正在使用）或 `hasSwapedOut == true`（已换出）

### 4.2 SwapOut 完整流程

**证据**：`render_surface.cpp` 行 476-505

```cpp
int32_t RenderSurface::SwapOutBuffers(bool isOutputBuffer, State curState)
{
    for (uint32_t i = 0u; i < buffers_[bufferType].size(); i++) {
        std::shared_ptr<CodecBuffer> codecBuffer = buffers_[bufferType][i];
        if (!CanSwapOut(isOutputBuffer, codecBuffer)) {
            AVCODEC_LOGW("Buf[%{public}u] can't freeze, owner[%{public}d] swapedOut[%{public}d]!",
                         i, codecBuffer->owner_.load(), codecBuffer->hasSwapedOut.load());
            continue;
        }
        sptr<SurfaceBuffer> surfaceBuffer = surfaceMemory->GetSurfaceBuffer();
        int32_t fd = surfaceBuffer->GetFileDescriptor();  // DMA fd
        int32_t ret = DmaSwaper::GetInstance().SwapOutDma(pid_, fd);  // ioctl SwapOut
        if (ret != AVCS_ERR_OK) {
            // SwapOut 失败，回刷（SwapIn）并恢复状态
            int32_t errCode = ActiveBuffers();
            return ret;
        }
        codecBuffer->hasSwapedOut.store(true);
    }
    return AVCS_ERR_OK;
}
```

### 4.3 SwapIn 完整流程

**证据**：`render_surface.cpp` 行 507-525

```cpp
int32_t RenderSurface::SwapInBuffers(bool isOutputBuffer) const
{
    for (uint32_t i = 0u; i < buffers_[bufferType].size(); i++) {
        std::shared_ptr<CodecBuffer> codecBuffer = buffers_[bufferType][i];
        if (!codecBuffer->hasSwapedOut.load()) continue;
        sptr<SurfaceBuffer> surfaceBuffer = surfaceMemory->GetSurfaceBuffer();
        int32_t fd = surfaceBuffer->GetFileDescriptor();
        int32_t ret = DmaSwaper::GetInstance().SwapInDma(pid_, fd);  // ioctl SwapIn
        CHECK_AND_RETURN_RET_LOG(ret == AVCS_ERR_OK, ret, "Swap in error!");
        codecBuffer->hasSwapedOut.store(false);
    }
    return AVCS_ERR_OK;
}
```

### 4.4 RenderSurface vs HDecoder Freeze/Active 差异

| 维度 | RenderSurface（FCodec） | HDecoder（HCodec） |
|------|------------------------|-------------------|
| Owner 枚举 | `Owner::OWNED_BY_US/CODEC/USER/SURFACE` | `BufferOwner::OWNED_BY_US/USER/OMX/SURFACE` |
| SwapOut 目标 | SurfaceBuffer（GPU 消费） | OMX buffer（硬件解码器） |
| 适用场景 | Surface Mode 解码（FCodec） | 硬件解码（HCodec） |
| Input Buffer | 不可 SwapOut | 可 SwapOut（但有条件） |

---

## 5. Attach 流程与 Owner 转换

**证据**：`render_surface.cpp` 行 110-165（Attach 方法）

```cpp
int32_t RenderSurface::Attach(sptr<SurfaceBuffer> surfaceBuffer)
{
    // 1. 从 codecAvailQue_ 取出可用 index
    uint32_t index;
    bool ret = codecAvailQue_->Pop(index);
    CHECK_AND_RETURN_RET_LOG(ret, AVCS_ERR_UNKNOWN, "No available codec buffer!");
    // 2. 找到对应的 CodecBuffer 并 Attach
    std::shared_ptr<CodecBuffer> codecBuffer = buffers_[INDEX_OUTPUT][index];
    std::shared_ptr<FSurfaceMemory> surfaceMemory = codecBuffer->sMemory;
    // 3. 设置 SurfaceBuffer 到 FSurfaceMemory，owner = OWNED_BY_US
    surfaceMemory->SetSurfaceBuffer(surfaceBuffer, Owner::OWNED_BY_US, nullptr);
    surfaceMemory->isAttached = true;
    // 4. 设置 avBuffer 的内存地址
    codecBuffer->avBuffer = AVBuffer::CreateAVBuffer(surfaceMemory->GetBase(), surfaceMemory->GetSize());
    // 5. codecAvailQue_ 已有该 index（由 RequestSurfaceBufferThread 生产）
    return AVCS_ERR_OK;
}
```

**FlushSurfaceMemory**：将填充好的 buffer 交付 Surface consumer，Owner 转为 `OWNED_BY_SURFACE`：

```cpp
int32_t RenderSurface::FlushSurfaceMemory(std::shared_ptr<FSurfaceMemory> &surfaceMemory, uint32_t index)
{
    // surfaceMemory->SetSurfaceBuffer(buffer, Owner::OWNED_BY_SURFACE, fence);
    // renderAvailQue_->Push(index) → 通知渲染
}
```

---

## 6. 整体数据流图（Surface Mode + DMA Swap）

```
[应用/DecodeServer]
    │
    │ SetOutputSurface()
    ▼
[RenderSurface 初始化]
    │
    │ StartRequestSurfaceBufferThread()
    │ 循环：requestSurfaceBufferQue_ → RequestSurfaceBuffer() → codecAvailQue_->Push(index)
    ▼
[codecAvailQue_]（可用空 buffer）
    │
    │ Codec 填充 YUV 数据
    ▼
[Codec 完成回调]
    │
    │ FlushSurfaceMemory(sMemory, index)
    │ → owner = OWNED_BY_SURFACE
    │ → renderAvailQue_->Push(index)
    ▼
[Surface consumer 消费帧]
    │
    │ BufferReleasedByConsumer()
    │ → Attach(surfaceBuffer)
    │ → owner = OWNED_BY_US
    │ → codecAvailQue_->Push(index) 循环
    │
    ▼
[后台冻结请求]
    │ FreezeBuffers()
    │ → SwapOutBuffers(INDEX_OUTPUT)
    │     ├── CanSwapOut() 检查 owner != OWNED_BY_SURFACE && !hasSwapedOut
    │     ├── DmaSwaper::SwapOutDma(pid_, fd) → ioctl DMA_BUF_RECLAIM_FD
    │     └── hasSwapedOut = true
    ▼
[FROZEN 状态]
    │
[恢复前台]
    │ ActiveBuffers()
    │ → SwapInBuffers(INDEX_OUTPUT)
    │     └── DmaSwaper::SwapInDma(pid_, fd) → ioctl DMA_BUF_RESUME_FD
    ▼
[RUNNING 状态]（继续正常数据流）
```

---

## 7. 关键调试参数

```bash
# DMA Swap 日志关键字
# "Buf[X] can't freeze, owner:[Y] swapedOut:[Z]" → 某 buffer 无法冻结
# "Buf[X] fd[Y] swap out success!" → SwapOut 成功
# "Buf[X] fd[Y] swap in success!" → SwapIn 成功
# "BufferReleasedByConsumer" → Surface consumer 释放回调
# "Attach buffer success" → Attach 成功
```

---

## 8. 相关文件索引

| 文件 | 作用 |
|------|------|
| `services/engine/common/include/fsurface_memory.h` | FSurfaceMemory 类声明 + Owner 枚举 |
| `services/engine/common/fsurface_memory.cpp` | FSurfaceMemory 实现（Alloc/Release/SetSurfaceBuffer） |
| `services/engine/codec/video/decoderbase/render_surface.h` | RenderSurface 类声明 + CodecBuffer 结构 + 三队列 |
| `services/engine/codec/video/decoderbase/render_surface.cpp` | RenderSurface 实现（Attach/Flush/Freeze/Swap） |
| `services/engine/common/dma_swap.cpp` | DmaSwaper（SwapOut/SwapIn 的 ioctl 封装） |
| `services/engine/codec/video/hcodec/hcodec_bg.cpp` | HDecoder Freeze/Active（HCodec 侧对应实现） |

---

## 9. 与其他记忆条目的关联

| 条目 | 关联点 |
|------|--------|
| **MEM-ARCH-AVCODEC-S6**（DMA Swap） | S6 聚焦 HCodec 侧 Freeze/Active；S7 聚焦 RenderSurface（FCodec）侧实现 |
| **MEM-ARCH-AVCODEC-S4**（Surface Mode） | S4 描述 Surface Mode 的入口与模式锁定；S7 深入 SurfaceBuffer 的生命周期管理 |
| **MEM-ARCH-AVCODEC-S3**（Pipeline） | S3 的输出数据流经过 RenderSurface::renderAvailQue_ → Surface consumer |
| **MEM-ARCH-AVCODEC-S5**（Loader） | FCodec/HCodec 是 RenderSurface 的下游，输出 SurfaceBuffer |
| **MEM-ARCH-AVCODEC-016**（AVBufferQueue） | AVBuffer 包装 SurfaceBuffer 的方式与本条目 AVBuffer->sMemory->SurfaceBuffer 层级对应 |

---

## 变更记录

| 日期 | 操作 | 说明 |
|------|------|------|
| 2026-04-22 | 新建草案 | builder-agent 从 fsurface_memory.h / render_surface.h/cpp 提取 SurfaceBuffer 内存管理架构 |
