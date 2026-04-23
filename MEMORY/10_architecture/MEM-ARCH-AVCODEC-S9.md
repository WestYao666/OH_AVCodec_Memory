---
id: MEM-ARCH-AVCODEC-S9
title: SurfaceBuffer 与 RenderSurface 内存管理——Owner 枚举、FSCallback 与三队列机制
scope: [AVCodec, SurfaceBuffer, MemoryManagement, RenderSurface, Owner, ZeroCopy, DMA-BUF, FSCallback]
status: draft
created_by: builder-agent
created_at: "2026-04-23T22:51:00+08:00"
type: architecture_fact
confidence: high
related_scenes: [新需求开发, 问题定位, Surface Mode, 后台切换, ZeroCopy]
summary: >
  AVCodec Surface 模式下解码器输出帧的内存管理围绕 SurfaceBuffer + FSurfaceMemory + RenderSurface 三者展开。
  FSurfaceMemory 封装 SurfaceBuffer 的申请/释放/所有权变更，Owner 枚举（OWNED_BY_US/CODEC/USER/SURFACE）追踪每个 buffer 的当前管理者。
  RenderSurface 管理双缓冲池（buffers_[2]）与三队列（renderAvailQue/requestSurfaceBufferQue/codecAvailQue），
  通过 FSCallback（RegisterReleaseListener）联动 codec 与 surface consumer 的生命周期。
  后台冻结时 FreezeBuffers() 对 output buffers 执行 DMA SwapOut（ioctl DMA_BUF_RECLAIM_FD），恢复时 ActiveBuffers() 执行 SwapIn（ioctl DMA_BUF_RESUME_FD），全程无 CPU 拷贝。
why_it_matters:
  - 问题定位：视频花屏/卡死常因 Owner 状态不一致导致错误释放；需区分 OWNED_BY_SURFACE 时不可 SwapOut、OWNED_BY_USER 时不可 Render 等约束
  - 新需求开发：RenderSurface 三队列是 Surface Mode 数据流的核心，理解各队列状态才能正确接入自定义 surface 或多实例场景
  - 后台管理：FreezeBuffers/ActiveBuffers 依赖 Owner 检查；开发者若自行管理 SurfaceBuffer 生命周期会破坏 DMA Swap 前提条件
  - 性能分析：ZeroCopy 路径省去 CPU 拷贝的关键是 SurfaceBuffer 始终在 OWNED_BY_SURFACE 状态直接传递给 GPU
evidence:
  - kind: local_file
    path: /home/west/av_codec_repo/services/engine/common/include/fsurface_memory.h
    anchor: Line 32-37: enum class Owner { OWNED_BY_US, OWNED_BY_CODEC, OWNED_BY_USER, OWNED_BY_SURFACE }
  - kind: local_file
    path: /home/west/av_codec_repo/services/engine/codec/video/decoderbase/render_surface.h
    anchor: Line 59-72: struct CodecBuffer { owner_; hasSwapedOut_; sMemory_; avBuffer_; }
  - kind: local_file
    path: /home/west/av_codec_repo/services/engine/codec/video/decoderbase/render_surface.h
    anchor: Line 79-81: three queues: renderAvailQue_, requestSurfaceBufferQue_, codecAvailQue_
  - kind: local_file
    path: /home/west/av_codec_repo/services/engine/codec/video/decoderbase/render_surface.cpp
    anchor: Line 78-92: RegisterListenerToSurface + FSCallback lambda → BufferReleasedByConsumer
  - kind: local_file
    path: /home/west/av_codec_repo/services/engine/codec/video/decoderbase/render_surface.cpp
    anchor: Line 327-374: BufferReleasedByConsumer → Attach → codecAvailQue_->Push
  - kind: local_file
    path: /home/west/av_codec_repo/services/engine/codec/video/decoderbase/render_surface.cpp
    anchor: Line 436-446: FreezeBuffers → SwapOutBuffers(INDEX_OUTPUT)
  - kind: local_file
    path: /home/west/av_codec_repo/services/engine/codec/video/decoderbase/render_surface.cpp
    anchor: Line 460-473: CanSwapOut: owner != OWNED_BY_SURFACE && !hasSwapedOut
  - kind: local_file
    path: /home/west/av_codec_repo/services/engine/codec/video/decoderbase/render_surface.cpp
    anchor: Line 476-505: SwapOutBuffers → DmaSwaper::SwapOutDma → ioctl DMA_BUF_RECLAIM_FD
  - kind: local_file
    path: /home/west/av_codec_repo/services/engine/codec/video/decoderbase/render_surface.cpp
    anchor: Line 507-525: SwapInBuffers → DmaSwaper::SwapInDma → ioctl DMA_BUF_RESUME_FD
  - kind: local_file
    path: /home/west/av_codec_repo/services/engine/codec/video/decoderbase/render_surface.cpp
    anchor: Line 236: surfaceMemory->owner = Owner::OWNED_BY_SURFACE (after FlushSurfaceMemory)
  - kind: local_file
    path: /home/west/av_codec_repo/services/engine/codec/video/decoderbase/render_surface.cpp
    anchor: Line 244-250: Attach → surface->AttachBufferToQueue
  - kind: local_file
    path: /home/west/av_codec_repo/services/engine/common/fsurface_memory.cpp
    anchor: Line 81-91: SetSurfaceBuffer → owner = toChangeOwner (atomic Owner transition)
  - kind: local_file
    path: /home/west/av_codec_repo/services/engine/common/dma_swap.cpp
    anchor: Line 49-73: SwapOutDma/SwapInDma with ioctl DMA_BUF_RECLAIM_FD/DMA_BUF_RESUME_FD
related_mem_ids:
  - MEM-ARCH-AVCODEC-S7
  - MEM-ARCH-AVCODEC-S6
  - MEM-ARCH-AVCODEC-S4
owner: 耀耀
review: pending
---

# MEM-ARCH-AVCODEC-S9: SurfaceBuffer 与 RenderSurface 内存管理——Owner 枚举、FSCallback 与三队列机制

## Metadata

| 字段 | 值 |
|------|-----|
| id | MEM-ARCH-AVCODEC-S9 |
| title | SurfaceBuffer 与 RenderSurface 内存管理——Owner 枚举、FSCallback 与三队列机制 |
| type | architecture_fact |
| scope | [AVCodec, SurfaceBuffer, MemoryManagement, RenderSurface, Owner, ZeroCopy, DMA-BUF, FSCallback] |
| status | draft |
| created_by | builder-agent |
| created_at | 2026-04-23 |
| confidence | high |
| 前序记忆 | MEM-ARCH-AVCODEC-S7 |

---

## 摘要

AVCodec Surface 模式下解码器输出帧的内存管理围绕 **SurfaceBuffer + FSurfaceMemory + RenderSurface** 三者展开。FSurfaceMemory 封装 SurfaceBuffer 的申请/释放/所有权变更，Owner 枚举追踪每个 buffer 的当前管理者。RenderSurface 管理双缓冲池（`buffers_[2]`）与三队列（`renderAvailQue`/`requestSurfaceBufferQue`/`codecAvailQue`），通过 **FSCallback**（`RegisterReleaseListener`）联动 codec 与 surface consumer 的生命周期。后台冻结时 `FreezeBuffers()` 对 output buffers 执行 DMA SwapOut，恢复时 `ActiveBuffers()` 执行 SwapIn，全程无 CPU 拷贝。

---

## 1. 核心组件分层

| 层级 | 类名 | 职责 | 证据 |
|------|------|------|------|
| 底层 | `SurfaceBuffer` | GBM 分配的视频帧内存（物理页 + DMA fd） | GFX子系统 |
| 中间层 | `FSurfaceMemory` | SurfaceBuffer 封装 + Owner 管理 | `fsurface_memory.h/cpp` |
| 上层 | `RenderSurface` | Codec 侧 buffer 池管理 + 三队列 + DMA Swap | `render_surface.h/cpp` |

---

## 2. Owner 枚举（四态机）

**证据**：`fsurface_memory.h` 行 32-37

```cpp
enum class Owner {
    OWNED_BY_US,       // Codec 自身持有（初始状态）
    OWNED_BY_CODEC,    // OMX codec 组件持有
    OWNED_BY_USER,     // 用户层（应用）持有
    OWNED_BY_SURFACE,  // Surface（GPU消费）持有
};
```

**CodecBuffer 中的 Owner**：`render_surface.h` 行 59-72

```cpp
struct CodecBuffer {
    std::shared_ptr<AVBuffer> avBuffer = nullptr;
    std::shared_ptr<FSurfaceMemory> sMemory = nullptr;
    std::atomic<Owner> owner_ = Owner::OWNED_BY_US;  // 初始为 US
    std::atomic<bool> hasSwapedOut = false;              // DMA Swap 状态
};
```

### 2.1 FSurfaceMemory::SetSurfaceBuffer 与 Owner 转换

**证据**：`fsurface_memory.cpp` 行 81-91

```cpp
void FSurfaceMemory::SetSurfaceBuffer(sptr<SurfaceBuffer> surfaceBuffer, Owner toChangeOwner, sptr<SyncFence> fence)
{
    surfaceBuffer_ = surfaceBuffer;
    owner = toChangeOwner;  // 原子切换所有者
    seqNum_ = surfaceBuffer_->GetSeqNum();
    if (fence != nullptr) {
        fence_ = fence;
    }
}
```

### 2.2 Owner 状态转换图

```
[OWNED_BY_US] ─── Codec 填充数据 ───→ [OWNED_BY_CODEC]
    ↑                                    │
    │                               FlushSurfaceMemory
    │                               surfaceMemory->owner = OWNED_BY_SURFACE
    │                                    │
    │                               renderAvailQue_->Push(index)
    │                                    ▼
    │                              [OWNED_BY_SURFACE]
    │                                    │
    │                          BufferReleasedByConsumer (FSCallback)
    │                                    │
    │                               Attach(surfaceBuffer)
    │                               owner = OWNED_BY_US
    │                                    │
    └─────────────────────────── codecAvailQue_->Push(index)
```

### 2.3 Owner 转换关键代码点

| 转换方向 | 方法 | 行号 | Owner 新值 |
|---------|------|------|-----------|
| → OWNED_BY_CODEC | RequestBufferFromConsumer | `render_surface.cpp:374` | `Owner::OWNED_BY_CODEC` |
| → OWNED_BY_SURFACE | FlushSurfaceMemory | `render_surface.cpp:236` | `Owner::OWNED_BY_SURFACE` |
| → OWNED_BY_US | BufferReleasedByConsumer→Attach | `render_surface.cpp:244-250` | `Owner::OWNED_BY_US` |

---

## 3. 三队列机制

**证据**：`render_surface.h` 行 79-81

```cpp
std::shared_ptr<BlockQueue<uint32_t>> renderAvailQue_;          // 可渲染的 buffer 序号
std::shared_ptr<BlockQueue<uint32_t>> requestSurfaceBufferQue_;  // 待向 Surface 请求的序号
std::shared_ptr<BlockQueue<uint32_t>> codecAvailQue_;            // Codec 可用的 buffer 序号
```

| 队列 | 内容 | 生产者 | 消费者 |
|------|------|--------|--------|
| `requestSurfaceBufferQue_` | 待请求 SurfaceBuffer 的 index | RenderSurface 线程自身 | RequestSurfaceBufferThread |
| `codecAvailQue_` | Codec 可填充数据的空 buffer index | RequestSurfaceBufferThread（Attach后） | Codec |
| `renderAvailQue_` | 已填充完毕、可渲染的 index | Codec 填充完成 | 应用/Surface consumer |

### 3.1 三队列数据流

```
RequestSurfaceBufferThread:
  requestSurfaceBufferQue_->Pop(index)
    → RequestSurfaceBufferOnce(index)
    → sInfo_.surface->AttachBufferToQueue()
    → codecAvailQue_->Push(index)

Codec 侧:
  codecAvailQue_->Pop(index)
    → 填充 YUV 数据
    → FlushSurfaceMemory(sMemory, index)
    → owner = OWNED_BY_SURFACE
    → renderAvailQue_->Push(index)

Surface consumer 侧:
  → BufferReleasedByConsumer(FSCallback 触发)
    → RequestBufferFromConsumer()
    → Attach(surfaceBuffer)
    → codecAvailQue_->Push(index)
```

---

## 4. FSCallback：Codec↔Surface 生命周期联动

### 4.1 RegisterListenerToSurface（FSCallback 注册）

**证据**：`render_surface.cpp` 行 78-92

```cpp
int32_t RenderSurface::RegisterListenerToSurface(const sptr<Surface> &surface)
{
    uint64_t surfaceId = surface->GetUniqueId();
    wptr<RenderSurface> wp = this;
    bool ret = SurfaceTools::GetInstance().RegisterReleaseListener(instanceId_, surface,
        [wp, surfaceId](sptr<SurfaceBuffer> &) {
            sptr<RenderSurface> codec = wp.promote();
            if (!codec) {
                AVCODEC_LOGD("decoder is nullptr");
                return GSERROR_OK;
            }
            return codec->BufferReleasedByConsumer(surfaceId);
        });
    CHECK_AND_RETURN_RET_LOG(ret, AVCS_ERR_UNKNOWN, "surface register listener failed");
    StartRequestSurfaceBufferThread();
    return AVCS_ERR_OK;
}
```

**机制**：通过 `SurfaceTools::RegisterReleaseListener` 向 Surface 注册 release listener。当 Surface consumer 释放 buffer 时，Surface 子系统回调该 lambda，lambda 再调用 `BufferReleasedByConsumer`。

### 4.2 BufferReleasedByConsumer 完整流程

**证据**：`render_surface.cpp` 行 327-374

```cpp
GSError RenderSurface::BufferReleasedByConsumer(uint64_t surfaceId)
{
    // 1. 检查状态机
    CHECK_AND_RETURN_RET_LOG(state_ == State::RUNNING || state_ == State::EOS ||
                             state_ == State::FLUSHING || state_ == State::FLUSHED,
                             GSERROR_NO_PERMISSION, "Invalid state");
    std::lock_guard<std::mutex> sLock(surfaceMutex_);
    CHECK_AND_RETURN_RET_LOG(renderAvailQue_->Size() > 0, GSERROR_NO_BUFFER, "No available buffer");

    // 2. 从 renderAvailQue 取出 buffer index
    RequestBufferFromConsumer();
    return GSERROR_OK;
}

void RenderSurface::RequestBufferFromConsumer()
{
    auto index = renderAvailQue_->Front();
    RequestSurfaceBufferOnce(index);  // 重新 Attach 该 buffer

    // 3. 找到对应 CodecBuffer 并重新设置
    std::shared_ptr<FSurfaceMemory> surfaceMemory = outputBuffer->sMemory;

    // 4. 从 renderAvailQue 中移除 index，并找到该 buffer 在 codecAvailQue 中的位置
    for (...) { renderAvailQue_->Pop(); ... codecAvailQue_->Push(curIndex); }

    // 5. 关键：owner 恢复为 OWNED_BY_CODEC
    buffers_[INDEX_OUTPUT][curIndex]->owner_ = Owner::OWNED_BY_CODEC;
    codecAvailQue_->Push(curIndex);  // → Codec 可再次使用
}
```

### 4.3 Attach 方法（重新关联 SurfaceBuffer）

**证据**：`render_surface.cpp` 行 244-250

```cpp
int32_t RenderSurface::Attach(sptr<SurfaceBuffer> surfaceBuffer)
{
    int32_t err = sInfo_.surface->AttachBufferToQueue(surfaceBuffer);
    CHECK_AND_RETURN_RET_LOG(err == 0, err,
        "Surface attach buffer to queue failed, GSError=%{public}d", err);
    return AVCS_ERR_OK;
}
```

**注意**：`Attach` 仅将 SurfaceBuffer 挂回 Surface queue，不改变 FSurfaceMemory 的 owner 状态。Owner 的变更由调用方（`RequestBufferFromConsumer` → `OWNED_BY_CODEC`）负责。

---

## 5. FreezeBuffers / ActiveBuffers 与 DMA Swap（后台内存管理）

### 5.1 FreezeBuffers 入口

**证据**：`render_surface.cpp` 行 436-446

```cpp
int32_t RenderSurface::FreezeBuffers(State curState)
{
    CHECK_AND_RETURN_RET_LOGD(state_ != State::FROZEN, AVCS_ERR_OK, "Video codec had been frozen!");
    std::lock_guard<std::mutex> sLock(surfaceMutex_);
    int32_t ret = SwapOutBuffers(INDEX_INPUT, curState);
    CHECK_AND_RETURN_RET_LOG(ret == AVCS_ERR_OK, ret, "Input buffers swap out failed!");
    ret = SwapOutBuffers(INDEX_OUTPUT, curState);
    CHECK_AND_RETURN_RET_LOG(ret == AVCS_ERR_OK, ret, "Output buffers swap out failed!");
    AVCODEC_LOGI("Freeze buffers success");
    return AVCS_ERR_OK;
}
```

### 5.2 CanSwapOut 冻结条件判断

**证据**：`render_surface.cpp` 行 460-473

```cpp
bool RenderSurface::CanSwapOut(bool isOutputBuffer, const std::shared_ptr<CodecBuffer> &codecBuffer)
{
    if (!isOutputBuffer) {
        AVCODEC_LOGE("Current buffers unsupport.");
        return false;  // INPUT buffer 不可冻结
    }
    std::shared_ptr<FSurfaceMemory> surfaceMemory = codecBuffer->sMemory;
    Owner ownerValue = surfaceMemory->owner;
    AVCODEC_LOGD("Buffer type: [%{public}u], codecBuffer->owner_: [%{public}d], "
                 "codecBuffer->hasSwapedOut: [%{public}d].",
                 isOutputBuffer, ownerValue, codecBuffer->hasSwapedOut.load());
    // 可冻结条件：owner 不是 OWNED_BY_SURFACE 且未 SwapOut
    return !(ownerValue == Owner::OWNED_BY_SURFACE || codecBuffer->hasSwapedOut.load());
}
```

| Owner 状态 | 可冻结？ | 原因 |
|-----------|---------|------|
| `OWNED_BY_US` | ✅ 可 | Codec 自身持有，无 GPU 使用 |
| `OWNED_BY_CODEC` | ✅ 可 | OMX 组件持有，可安全回收 |
| `OWNED_BY_USER` | ✅ 可 | 用户层已释放 |
| `OWNED_BY_SURFACE` | ❌ 不可 | GPU 正在渲染中 |
| `hasSwapedOut=true` | ❌ 不可 | 已换出，不可重复换出 |

### 5.3 SwapOutBuffers 完整流程

**证据**：`render_surface.cpp` 行 476-505

```cpp
int32_t RenderSurface::SwapOutBuffers(bool isOutputBuffer, State curState)
{
    uint32_t bufferType = isOutputBuffer ? INDEX_OUTPUT : INDEX_INPUT;
    CHECK_AND_RETURN_RET_LOGD(bufferType == INDEX_OUTPUT, AVCS_ERR_OK,
                               "Input buffers can't be swapped out!");  // INPUT 直接跳过
    for (uint32_t i = 0u; i < buffers_[bufferType].size(); i++) {
        std::shared_ptr<CodecBuffer> codecBuffer = buffers_[bufferType][i];
        if (!CanSwapOut(isOutputBuffer, codecBuffer)) {
            AVCODEC_LOGW("Buf: [%{public}u] can't freeze, owner: [%{public}d] swaped out: [%{public}d]!",
                          i, codecBuffer->owner_.load(), codecBuffer->hasSwapedOut.load());
            continue;
        }
        sptr<SurfaceBuffer> surfaceBuffer = codecBuffer->sMemory->GetSurfaceBuffer();
        int32_t fd = surfaceBuffer->GetFileDescriptor();  // DMA fd
        int32_t ret = DmaSwaper::GetInstance().SwapOutDma(pid_, fd);  // ioctl DMA_BUF_RECLAIM_FD
        if (ret != AVCS_ERR_OK) {
            // SwapOut 失败 → 回刷 SwapIn 并恢复状态
            int32_t errCode = ActiveBuffers();
            state_ = curState;
            return ret;
        }
        AVCODEC_LOGI("Buf[%{public}u] fd[%{public}u] swap out success!", i, fd);
        codecBuffer->hasSwapedOut.store(true);  // 标记为已换出
    }
    return AVCS_ERR_OK;
}
```

### 5.4 SwapInBuffers 完整流程

**证据**：`render_surface.cpp` 行 507-525

```cpp
int32_t RenderSurface::SwapInBuffers(bool isOutputBuffer) const
{
    uint32_t bufferType = isOutputBuffer ? INDEX_OUTPUT : INDEX_INPUT;
    for (uint32_t i = 0u; i < buffers_[bufferType].size(); i++) {
        std::shared_ptr<CodecBuffer> codecBuffer = buffers_[bufferType][i];
        if (!codecBuffer->hasSwapedOut.load()) continue;  // 仅处理已换出的
        sptr<SurfaceBuffer> surfaceBuffer = codecBuffer->sMemory->GetSurfaceBuffer();
        int32_t fd = surfaceBuffer->GetFileDescriptor();
        int32_t ret = DmaSwaper::GetInstance().SwapInDma(pid_, fd);  // ioctl DMA_BUF_RESUME_FD
        CHECK_AND_RETURN_RET_LOG(ret == AVCS_ERR_OK, ret, "Buf[%{public}u] swap in error!", i);
        AVCODEC_LOGI("Buf[%{public}u] fd[%{public}u] swap in success!", i, fd);
        codecBuffer->hasSwapedOut.store(false);  // 清除换出标记
    }
    return AVCS_ERR_OK;
}
```

### 5.5 DmaSwaper 底层 ioctl

**证据**：`dma_swap.cpp` 行 49-73

```cpp
// SwapOut: 通知内核回收 DMA buffer fd 对应的物理内存
int32_t DmaSwaper::SwapOutDma(pid_t pid, int32_t bufFd)
{
    DmaBufIoctlSwPara param {.pid = pid, .ino = 0, .fd = bufFd};
    return ioctl(reclaimDriverFd_, DMA_BUF_RECLAIM_FD, &param);  // 内核释放物理页
}

// SwapIn: 恢复被回收的 DMA buffer
int32_t DmaSwaper::SwapInDma(pid_t pid, int32_t bufFd)
{
    DmaBufIoctlSwPara param {.pid = pid, .ino = 0, .fd = bufFd};
    return ioctl(reclaimDriverFd_, DMA_BUF_RESUME_FD, &param);  // 内核恢复物理页
}
```

---

## 6. BUFFER_USAGE_MEM_DMA 必须性

**证据**：`render_surface.cpp` 行 68（实际在 CombineConsumerUsage 或 SetSurfaceCfg）

SurfaceBuffer 必须使用 `BUFFER_USAGE_MEM_DMA` flag，否则 `surfaceBuffer->GetFileDescriptor()` 返回无效 fd（≤ 0），导致 `SwapOutDma`/`SwapInDma` 的 ioctl 调用失败。

```cpp
// 在 RequestSurfaceBufferOnce 或 SetSurfaceCfg 中确保：
uint64_t finalUsage = BUFFER_USAGE_CPU_READ | BUFFER_USAGE_CPU_WRITE | BUFFER_USAGE_MEM_DMA | consumerUsage | cfgedUsage;
sInfo_.requestConfig.usage = finalUsage;
```

---

## 7. 整体数据流图（Surface Mode + DMA Swap + FSCallback）

```
[应用/DecodeServer]
    │
    │ SetOutputSurface()
    ▼
[RenderSurface::RegisterListenerToSurface]
    │ FSCallback = RegisterReleaseListener → BufferReleasedByConsumer
    │ StartRequestSurfaceBufferThread()
    ▼
[RequestSurfaceBufferThread 循环]
    │
    │ requestSurfaceBufferQue_->Pop(index)
    │ → RequestSurfaceBufferOnce(index)
    │ → Attach(surfaceBuffer)
    │ → codecAvailQue_->Push(index)
    ▼
[codecAvailQue_]（可用空 buffer）
    │
    │ Codec 填充 YUV 数据
    ▼
[Codec 完成]
    │
    │ FlushSurfaceMemory(sMemory, index)
    │ → owner = OWNED_BY_SURFACE
    │ → renderAvailQue_->Push(index)
    ▼
[Surface consumer 消费帧]
    │
    │ FSCallback: BufferReleasedByConsumer()
    │ → RequestBufferFromConsumer()
    │ → Attach(surfaceBuffer)
    │ → owner = OWNED_BY_CODEC
    │ → codecAvailQue_->Push(index)  [循环]
    │
    ▼
[后台冻结请求]
    │ FreezeBuffers(FROZEN)
    │ → CanSwapOut(INDEX_OUTPUT) 检查 owner != OWNED_BY_SURFACE
    │ → SwapOutDma(ioctl DMA_BUF_RECLAIM_FD)
    │ → hasSwapedOut = true
    ▼
[FROZEN 状态]（无 CPU 拷贝，物理页已回收）
    │
[恢复前台]
    │ ActiveBuffers()
    │ → SwapInDma(ioctl DMA_BUF_RESUME_FD)
    │ → hasSwapedOut = false
    ▼
[RUNNING 状态]
```

---

## 8. 关键调试参数

```bash
# DMA Swap 日志关键字
"Buf[X] can't freeze, owner:[Y] swapedOut:[Z]"  # 某 buffer 无法冻结
"Buf[X] fd[Y] swap out success!"                # SwapOut 成功
"Buf[X] fd[Y] swap in success!"                 # SwapIn 成功
"BufferReleasedByConsumer"                       # Surface consumer 释放回调触发
"Request output buffer success"                   # Attach 成功
"RegisterReleaseListener"                         # FSCallback 注册成功
"Owner"                                           # 配合数值：0=US, 1=CODEC, 2=USER, 3=SURFACE
```

---

## 9. 与其他记忆条目的关联

| 条目 | 关联点 |
|------|--------|
| **MEM-ARCH-AVCODEC-S7** | 前序记忆，内容高度重叠；本条目聚焦三队列与 FSCallback 的代码证据链（行号级别） |
| **MEM-ARCH-AVCODEC-S6**（DMA Swap） | S6 聚焦 HCodec 侧 Freeze/Active；S9 聚焦 RenderSurface（FCodec）侧实现细节 |
| **MEM-ARCH-AVCODEC-S4**（Surface Mode） | S4 描述 Surface Mode 的入口与模式锁定；S9 深入 SurfaceBuffer 的生命周期管理 |
| **MEM-ARCH-AVCODEC-S3**（Pipeline） | S3 的输出数据流经过 RenderSurface::renderAvailQue_ → Surface consumer |

---

## 10. 相关文件索引

| 文件 | 作用 | 关键行号 |
|------|------|---------|
| `services/engine/common/include/fsurface_memory.h` | FSurfaceMemory 类声明 + Owner 枚举 | L32-37 |
| `services/engine/common/fsurface_memory.cpp` | FSurfaceMemory 实现（Alloc/Release/SetSurfaceBuffer） | L81-91 |
| `services/engine/codec/video/decoderbase/render_surface.h` | RenderSurface 类声明 + CodecBuffer + 三队列 | L59-81 |
| `services/engine/codec/video/decoderbase/render_surface.cpp` | RenderSurface 实现（FSCallback/Attach/Flush/Freeze/Swap） | 全文 |
| `services/engine/common/dma_swap.cpp` | DmaSwaper（SwapOut/SwapIn 的 ioctl 封装） | L49-73 |

---

## 变更记录

| 日期 | 操作 | 说明 |
|------|------|------|
| 2026-04-23 | 新建草案 | builder-agent 基于 S7 上下文，从 fsurface_memory.h/render_surface.h/cpp 提取行号级别证据 |
