---
id: MEM-ARCH-AVCODEC-S6
title: 内存复用（ZeroCopy）与 DMA-BUF 机制——SwapOut/SwapIn 与 BufferOwner 生命周期
scope: [AVCodec, ZeroCopy, DMA-BUF, MemoryReclaim, BufferOwner, BackgroundSwap]
status: draft
created_at: "2026-04-22T10:10:00+08:00"
author: builder-agent
evidence_sources:
  - local_repo: /home/west/av_codec_repo
  - "services/engine/codec/video/hcodec/hcodec_bg.cpp"
  - "services/engine/common/dma_swap.cpp"
  - "services/engine/common/include/dma_swap.h"
  - "services/engine/codec/video/hcodec/hcodec.h"
  - "services/engine/codec/video/decoderbase/render_surface.cpp"
related_scenes: [新需求开发, 问题定位, Surface Mode, 硬件Codec后台切换, 低功耗管理]
summary: >
  AVCodec 的 ZeroCopy 内存复用建立在 DMA-BUF 机制上。硬件 Codec（HCodec）输出帧不经过 CPU 拷贝，直接通过
  SurfaceBuffer + DMA 文件描述符传递给 GPU/显示层。Codec 进入后台时，通过 DmaSwaper 对 /dev/dma_reclaim
  发送 SwapOut（回收）ioctl，将 DMA 缓冲区从物理内存换出；恢复时发送 SwapIn（唤醒）ioctl。
  BufferOwner 枚举（OWNED_BY_US/USER/OMX/SURFACE）追踪每个 buffer 的当前管理者，FreezeBuffers 和
  ActiveBuffers 成对使用，实现后台不丢帧、恢复即续的零拷贝视频路径。
why_it_matters:
 - 问题定位：DMA Swap 失败会导致视频花屏、冻结或 EOS 异常；需区分 SwapOut（用户层持 buffer 时不可换出） vs SwapIn（driver ioctl 失败）错误
 - 新需求开发：Surface Mode 下必须使用 BUFFER_USAGE_MEM_DMA，否则 DMA fd 无法获取，ZeroCopy 降级为拷贝路径
 - 低功耗管理：FreezeBuffers 后 OMX 层降频；ActiveBuffers 后恢复频率，理解此机制才能正确接入功耗管理需求
 - 性能分析：ZeroCopy 路径省去解码→CPU→GPU 的两次数据拷贝，适合低延迟视频播放和相机预览场景
---

## 1. 核心概念：什么是 DMA-BUF ZeroCopy

传统视频解码路径（Buffer Mode）：

```
HWCodec 解码 → 解码 buffer（物理内存）
    → CPU memcpy → 用户态 buffer
    → CPU memcpy → GPU texture
```

ZeroCopy 路径（Surface Mode + DMA-BUF）：

```
HWCodec 解码 → 解码 buffer（DMA-BUF fd）
    → 通过 SurfaceBuffer fd 直接传递给 GPU → 显示
    （全程无 CPU 拷贝）
```

**关键**：DMA-BUF 允许不同进程（Codec 进程、GPU 进程）通过**共享文件描述符**访问同一块物理内存，无需 CPU 拷贝数据。

---

## 2. DMA 交换设备与 ioctl 接口

**证据**：`services/engine/codec/video/hcodec/hcodec_bg.cpp:33-47`（同 `services/engine/common/dma_swap.cpp`）

```cpp
#define DMA_DEVICE_FILE "/dev/dma_reclaim"
#define DMA_BUF_RECLAIM_IOC_MAGIC 'd'
#define DMA_BUF_RECLAIM_FD _IOWR(DMA_BUF_RECLAIM_IOC_MAGIC, 0x07, int)  // SwapOut
#define DMA_BUF_RESUME_FD   _IOWR(DMA_BUF_RECLAIM_IOC_MAGIC, 0x08, int)  // SwapIn

struct DmaBufIoctlSwPara {
    pid_t pid;         // 持有 buffer 的进程 PID
    unsigned long ino; // DMA buffer inode（未使用，设为 0）
    unsigned int fd;   // DMA buffer 的文件描述符
};
```

**ioctl 语义**：
- `DMA_BUF_RECLAIM_FD`（SwapOut）：通知 DMA 驱动将指定 buffer 的物理页换出到辅助存储（zRAM），释放物理内存
- `DMA_BUF_RESUME_FD`（SwapIn）：将已换出的 buffer 重新加载回物理内存

**两种实现**：DmaSwaper 类同时存在于：
- `services/engine/common/dma_swap.cpp`（通用路径）
- `services/engine/codec/video/hcodec/hcodec_bg.cpp`（HCodec 内部，重复定义）

两者逻辑完全相同，均通过 `DmaSwaper::GetInstance()` 单例访问 `/dev/dma_reclaim`。

---

## 3. DmaSwaper 单例封装

**证据**：`hcodec_bg.cpp:50-107`

```cpp
class DmaSwaper {
private:
    int reclaimDriverFd_ = -1;  // 打开 /dev/dma_reclaim 的 fd

public:
    int32_t SwapOutDma(pid_t pid, int bufFd)  // SwapOut = 回收
    {
        if (reclaimDriverFd_ <= 0) return AVCS_ERR_UNKNOWN;
        DmaBufIoctlSwPara param { .pid = pid, .ino = 0, .fd = bufFd };
        return ioctl(reclaimDriverFd_, DMA_BUF_RECLAIM_FD, &param);
    }

    int32_t SwapInDma(pid_t pid, int bufFd)   // SwapIn = 唤醒
    {
        if (reclaimDriverFd_ <= 0) return AVCS_ERR_UNKNOWN;
        DmaBufIoctlSwPara param { .pid = pid, .ino = 0, .fd = bufFd };
        return ioctl(reclaimDriverFd_, DMA_BUF_RESUME_FD, &param);
    }

    static DmaSwaper& GetInstance();  // C++11 magic static，线程安全单例
};
```

**初始化时机**：首次调用 `GetInstance()` 时打开 `/dev/dma_reclaim`（O_RDWR | O_CLOEXEC | O_NONBLOCK）。

---

## 4. BufferOwner 枚举与所有权追踪

**证据**：`services/engine/codec/video/hcodec/hcodec.h:115-119`

```cpp
enum BufferOwner {
    OWNED_BY_US = 0,       // Codec 组件自身持有
    OWNED_BY_USER = 1,     // 用户层（应用）持有
    OWNED_BY_OMX = 2,      // OMX 组件持有
    OWNED_BY_SURFACE = 3,  // Surface（GPU消费）持有
    OWNER_CNT              // 总计 4 种状态
};
```

**所有权决定 SwapOut 可行性**：

```cpp
// hcodec_bg.cpp:193-205
bool HDecoder::CanSwapOut(OMX_DIRTYPE portIndex, BufferInfo& info)
{
    if (portIndex == OMX_DirInput) {
        // 输入端口：用户持有或已换出 → 不可 SwapOut
        if (info.owner == BufferOwner::OWNED_BY_USER || info.hasSwapedOut) {
            return false;
        }
    }
    if (portIndex == OMX_DirOutput) {
        if (currSurface_.surface_) {
            // Surface Mode：Surface 持有 → 不可 SwapOut
            return !(info.owner == BufferOwner::OWNED_BY_SURFACE ||
                     info.hasSwapedOut || info.surfaceBuffer == nullptr);
        } else {
            // Buffer Mode：用户或 Surface 持有 → 不可 SwapOut
            return !(info.owner == BufferOwner::OWNED_BY_SURFACE ||
                     info.surfaceBuffer == nullptr ||
                     info.owner == BufferOwner::OWNED_BY_USER ||
                     info.hasSwapedOut);
        }
    }
    return true;
}
```

**设计原则**：只有当 buffer 处于 Codec 自身或 OMX 持有状态时才能 SwapOut；用户层正在使用的 buffer 不能回收，以防止数据损坏。

---

## 5. FreezeBuffers（后台冻结）完整流程

**证据**：`hcodec_bg.cpp:207-223`

```cpp
int32_t HDecoder::FreezeBuffers()
{
    if (isSecure_) {
        return AVCS_ERR_OK;  // 安全 Codec 不支持 DMA SwapOut
    }
    // 1. 通知 OMX 层停止填充 buffer（进入后台模式）
    OMX_CONFIG_BOOLEANTYPE param {};
    InitOMXParam(param);
    param.bEnabled = OMX_TRUE;
    if (!SetParameter(OMX_IndexParamBufferRecycle, param)) {
        return AVCS_ERR_UNKNOWN;  // OMX 降频/冻结失败
    }
    // 2. 对输入端口所有可换出 buffer 执行 SwapOut
    if (SwapOutBufferByPortIndex(OMX_DirInput) != AVCS_ERR_OK) {
        return AVCS_ERR_UNKNOWN;
    }
    // 3. 对输出端口所有可换出 buffer 执行 SwapOut
    if (SwapOutBufferByPortIndex(OMX_DirOutput) != AVCS_ERR_OK) {
        return AVCS_ERR_UNKNOWN;
    }
    return AVCS_ERR_OK;
}
```

**SwapOutBufferByPortIndex**（`hcodec_bg.cpp:159-175`）：
```cpp
for (BufferInfo& info : pool) {
    if (CanSwapOut(portIndex, info) == false) {
        continue;  // 用户/Surface 持有的 buffer 跳过
    }
    // 获取 DMA buffer fd（输入从 avBuffer->memory_，输出从 surfaceBuffer）
    int fd = (portIndex == OMX_DirInput)
        ? info.avBuffer->memory_->GetFileDescriptor()
        : info.surfaceBuffer->GetFileDescriptor();
    DmaSwaper::GetInstance().SwapOutDma(pid_, fd);
    info.hasSwapedOut = true;
}
```

---

## 6. ActiveBuffers（恢复激活）完整流程

**证据**：`hcodec_bg.cpp:225-242`

```cpp
int32_t HDecoder::ActiveBuffers()
{
    if (isSecure_) {
        return AVCS_ERR_OK;
    }
    // 1. 对所有已 SwapOut 的 buffer 执行 SwapIn
    if (SwapInBufferByPortIndex(OMX_DirInput) != AVCS_ERR_OK) {
        return AVCS_ERR_UNKNOWN;
    }
    if (SwapInBufferByPortIndex(OMX_DirOutput) != AVCS_ERR_OK) {
        return AVCS_ERR_UNKNOWN;
    }
    // 2. 通知 OMX 层恢复填充 buffer（退出后台模式）
    OMX_CONFIG_BOOLEANTYPE param {};
    InitOMXParam(param);
    param.bEnabled = OMX_FALSE;
    if (!SetParameter(OMX_IndexParamBufferRecycle, param)) {
        return AVCS_ERR_UNKNOWN;
    }
    return AVCS_ERR_OK;
}
```

**SwapInBufferByPortIndex**（`hcodec_bg.cpp:177-190`）：遍历 `hasSwapedOut==true` 的 buffer，逐个调用 `SwapInDma`。

---

## 7. 与状态机的集成：FrozenState

**证据**：`hcodec_bg.cpp:317-336`

```cpp
void HCodec::RunningState::OnBufferRecycle(const MsgInfo &info)
{
    if (codec_->disableDmaSwap_) {  // hcodec.dmaswap.disable 参数
        SLOGI("hcodec dma swap has been disabled!");
        ReplyErrorCode(info.id, AVCS_ERR_OK);
        return;
    }
    int32_t errCode = codec_->FreezeBuffers();
    if (errCode == AVCS_ERR_OK) {
        codec_->ChangeStateTo(codec_->frozenState_);  // Running → Frozen
    }
    ReplyErrorCode(info.id, errCode);
}

void HCodec::FrozenState::OnBufferWriteback(const MsgInfo &info)
{
    int32_t errCode = codec_->ActiveBuffers();
    if (errCode == AVCS_ERR_OK) {
        codec_->SubmitBuffersToNextOwner();  // 重新分发 buffer 给下一个 owner
        codec_->ChangeStateTo(codec_->runningState_);  // Frozen → Running
    }
    ReplyErrorCode(info.id, errCode);
}
```

**状态转换**：

```
[RunningState]
    │
    │ OnBufferRecycle (应用请求进入后台)
    ▼
[FrozenState]   ← FreezeBuffers() → DMA SwapOut
    │               OMX 降频
    │ OnBufferWriteback (应用恢复前台)
    ▼
[RunningState]  ← ActiveBuffers() → DMA SwapIn
                  SubmitBuffersToNextOwner() → 续传
```

---

## 8. Surface Mode 与 BUFFER_USAGE_MEM_DMA

**证据**：`decoderbase/render_surface.cpp:68-72`

```cpp
uint64_t defaultUsage = BUFFER_USAGE_CPU_READ | BUFFER_USAGE_CPU_WRITE | BUFFER_USAGE_MEM_DMA;
// SurfaceBuffer 必须包含 DMA usage flag 才能参与 ZeroCopy 路径
uint64_t consumerUsage = sInfo_.surface->GetDefaultUsage();
uint64_t cfgedUsage = sInfo_.requestConfig.usage;
uint64_t finalUsage = defaultUsage | consumerUsage | cfgedUsage;
sInfo_.requestConfig.usage = finalUsage;
```

**BUFFER_USAGE_MEM_DMA** 是 SurfaceBuffer 参与 DMA-BUF 的必要标志：
- 解码器输出帧通过 `surfaceBuffer->GetFileDescriptor()` 获取 DMA fd
- 该 fd 传递给 Surface/BufferQueue，实现零拷贝 GPU 合成
- 若缺少此 flag，`GetFileDescriptor()` 返回无效 fd，ZeroCopy 降级为 CPU 拷贝

---

## 9. disableDmaSwap_ 开关

**证据**：`services/engine/codec/video/hcodec/hcodec.cpp:410`

```cpp
disableDmaSwap_ = OHOS::system::GetBoolParameter("hcodec.dmaswap.disable", false);
```

| 参数 | 默认值 | 效果 |
|------|--------|------|
| `hcodec.dmaswap.disable=true` | false | 完全禁用 DMA SwapOut/SwapIn，进入 FrozenState 时跳过 DMA 操作 |

**用途**：调试 DMA reclaim driver 异常，或在不支持 DMA-BUF 的设备上禁用零拷贝回退到传统路径。

---

## 10. 整体数据流图

```
应用（视频播放/相机预览）
    │
    ▼
CodecServer::QueueInputBuffer()
    │ 输入 buffer（AVBuffer，fd=DMABUF 或 普通fd）
    ▼
HCodec（硬件解码器）
    │
    ├─ Surface Mode → 输出 surfaceBuffer->GetFileDescriptor() → DMA fd
    │                  ↓
    │                Surface → GPU → 显示（ZeroCopy，无CPU拷贝）
    │
    └─ 后台通知 → RunningState::OnBufferRecycle()
                    ↓
                 FreezeBuffers()
                    ├─ SetParameter(OMX_IndexParamBufferRecycle=true) → OMX 降频
                    ├─ SwapOutBufferByPortIndex(DirInput) → ioctl(DMA_BUF_RECLAIM_FD)
                    └─ SwapOutBufferByPortIndex(DirOutput) → ioctl(DMA_BUF_RECLAIM_FD)
                    ↓
                 [FrozenState]（视频帧已冻结在 Surface，不丢帧）
                    ↓
                 前台恢复 → FrozenState::OnBufferWriteback()
                    ↓
                 ActiveBuffers()
                    ├─ SwapInBufferByPortIndex(DirInput) → ioctl(DMA_BUF_RESUME_FD)
                    ├─ SwapInBufferByPortIndex(DirOutput) → ioctl(DMA_BUF_RESUME_FD)
                    ├─ SetParameter(OMX_IndexParamBufferRecycle=false) → OMX 恢复
                    └─ SubmitBuffersToNextOwner() → 续传
                    ↓
                 [RunningState]（继续正常解码）
```

---

## 11. 相关文件索引

| 文件 | 作用 |
|------|------|
| `services/engine/codec/video/hcodec/hcodec_bg.cpp` | DmaSwaper 定义 + Freeze/Active/SwapOut/SwapIn 实现 |
| `services/engine/common/dma_swap.cpp` | 通用 DmaSwaper 单例（独立副本） |
| `services/engine/common/include/dma_swap.h` | DmaSwaper 头文件 |
| `services/engine/codec/video/hcodec/hcodec.h` | BufferOwner 枚举 + disableDmaSwap_ 声明 |
| `services/engine/codec/video/decoderbase/render_surface.cpp` | BUFFER_USAGE_MEM_DMA 设置 + SurfaceBuffer 管理 |
| `services/engine/codec/video/hcodec/hcodec_state.cpp` | RunningState/FrozenState 状态机集成 |

---

## 12. 与其他记忆条目的关联

| 条目 | 关联点 |
|------|--------|
| **MEM-ARCH-AVCODEC-S4**（Surface Mode） | Surface Mode 是 ZeroCopy 的前置条件；SurfaceBuffer 通过 DMA fd 传递给 GPU |
| **MEM-ARCH-AVCODEC-S3**（CodecServer Pipeline） | Freeze/Active 对应 Running/Frozen 两个 Pipeline 状态 |
| **MEM-ARCH-AVCODEC-018**（HDI IPC/Passthrough） | HDecoder（HCodec）是 DMA Swap 的调用方；安全 Codec（isSecure_）跳过 Swap |
| **MEM-ARCH-AVCODEC-016**（AVBufferQueue） | AVBuffer 的 memory_->GetFileDescriptor() 是 DMA fd 的来源之一 |
| **MEM-DEVFLOW-003**（日志定位） | DMA SwapOut/SwapIn 失败关键字：`freeze buffers failed`、`swap in error` |

---

## 13. 关键调试参数

```bash
# 查看 DMA Swap 是否启用
getprop hcodec.dmaswap.disable

# 强制开启 DMA Swap（eng 版本）
setprop hcodec.dmaswap.disable false

# 强制 Passthrough 模式（影响 DMA fd 来源）
setprop hcodec.usePassthrough 1
```

**日志关键字**：
- `SwapOutDma do ioctl!` → SwapOut 正在执行
- `SwapInDma do ioctl!` → SwapIn 正在执行
- `freeze buffers success` → 后台冻结成功
- `buffers active success` → 恢复成功
- `buf[X] can't freeze owner[Y] swaped out[Z]` → 某 buffer 因所有权无法冻结

---

## 变更记录

| 日期 | 操作 | 说明 |
|------|------|------|
| 2026-04-22 | 新建草案 | builder-agent 从 hcodec_bg.cpp/dma_swap.cpp/render_surface.cpp 提取 DMA-BUF ZeroCopy 架构 |
