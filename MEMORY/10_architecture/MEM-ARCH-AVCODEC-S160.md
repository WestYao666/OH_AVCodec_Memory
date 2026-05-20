---
id: MEM-ARCH-AVCODEC-S160
title: HDecoder/HEncoder 后台管理——FreezeBuffers / DMA-BUF Swap / DmaSwaper 与 MsgHandleLoop 状态机
scope: [AVCodec, HardwareCodec, HDecoder, HEncoder, HCodec, SuspendResume, DMA-BUF, MsgHandleLoop, StateMachine, BufferOwner, OMX]
topic: HDecoder/HEncoder 的后台挂起管理体系——MsgHandleLoop 异步消息队列、Frozen/Running双状态切换、FreezeBuffers DMA-BUF 换出/换入（通过 /dev/dma_reclaim 驱动）、BufferOwner 四态流转、NotifySuspend/NotifyResume 与系统低功耗策略的集成。
===
# MEM-ARCH-AVCODEC-S160

> **主题**: HDecoder/HEncoder 后台管理——FreezeBuffers / DMA-BUF Swap / DmaSwaper 与 MsgHandleLoop 状态机
>
> **状态**: pending_approval
>
> **scope**: AVCodec, HardwareCodec, HDecoder, HEncoder, HCodec, SuspendResume, DMA-BUF, MsgHandleLoop, StateMachine, BufferOwner, OMX
>
> **关联场景**: 后台切换/省电策略/问题定位
>
> **关联记忆**: S57(硬件Codec OMX架构)/S70(工厂Loader)/S21(MsgHandleLoop)/S154(VideoDecoder基类与RenderSurface)
>
> **draft_created**: 2026-05-20T09:25:00+08:00
>
> **builder**: builder-agent (subagent)

---

## 一、主题概述

HDecoder/HEncoder 的后台管理体系是 AVCodec 硬件编解码器在进程挂起/恢复时维持数据完整性、释放系统资源（内存频率/寄存器/DMA-BUF）并快速恢复的关键机制。本记忆覆盖：

1. **MsgHandleLoop** — 异步消息队列线程基础（SendSyncMsg/SendAsyncMsg）
2. **HCodec 状态机** — Running/Frozen/Stopping 多状态切换与 OnSuspend/OnResume
3. **FreezeBuffers / ActiveBuffers** — OMX_IndexParamBufferRecycle 参数控制缓冲区冻结
4. **DmaSwaper + /dev/dma_reclaim** — DMA-BUF fd 换出/换入机制（SwapOutDma/SwapInDma）
5. **BufferOwner 四态** — OWNED_BY_USER / OWNED_BY_OMX / OWNED_BY_SURFACE / OWNER_CNT
6. **NotifySuspend / NotifyResume** — 对外接口与内部消息分发

---

## 二、MsgHandleLoop — 异步消息队列线程

### 2.1 核心类定义

MsgHandleLoop 是 HCodec 的消息处理基础设施，封装独立线程 + 优先级队列 + 同步/异步两种发送模式：

```
services/engine/codec/video/hcodec/msg_handle_loop.h:37
class MsgHandleLoop {
protected:
    MsgHandleLoop();
    virtual ~MsgHandleLoop();
    void SendAsyncMsg(MsgType type, const ParamSP &msg, uint32_t delayUs = 0);   // 异步（带延迟）
    bool SendSyncMsg(MsgType type, const ParamSP &msg, ParamSP &reply, uint32_t waitMs = 0);  // 同步等待回复
    virtual void OnMsgReceived(const MsgInfo &info) = 0;   // 子类实现消息处理
    void PostReply(MsgId id, const ParamSP &reply);         // 回复同步消息
    void Stop();
    static constexpr MsgId ASYNC_MSG_ID = 0;
    using TimeUs = int64_t;
    static TimeUs GetNowUs();
    struct MsgToken {
        std::mutex m_mtx;
        std::map<TimeUs, MsgInfo> m_msgQueue;   // 按时间排序的消息队列（支持延迟）
        std::condition_variable m_threadCond;
        void SendAsyncMsg(MsgType type, const ParamSP &msg, uint32_t delayUs = 0);
    };
    std::shared_ptr<MsgToken> m_token;

private:
    std::thread m_thread;           // 独立线程
    bool m_threadNeedStop = false;   // 停止标志
    MsgId m_lastMsgId = 0;
    std::mutex m_replyMtx;
    std::map<MsgId, ParamSP> m_replies;    // 同步消息回复表（MsgId→reply）
    std::condition_variable m_replyCond;
};
```

- MsgInfo 携带 type + id + param（ParamBundle 智能指针）
- Async 消息用 MsgId=ASYNC_MSG_ID=0 标记，无回复
- Sync 消息用独立 MsgId，支持超时等待回复（waitMs）
- delayUs=0 表示立即，delayUs>0 表示延迟发送（常用于 SUSPEND/RESUME 后台消息）
- HCodec 继承 MsgHandleLoop，通过子类覆盖 OnMsgReceived 实现消息分发

### 2.2 HCodec 的消息类型

```
services/engine/codec/video/hcodec/hcodec.h:70
enum MsgWhat : MsgType {
    FORCE_SHUTDOWN = 0,
    CONFIGURE,
    START,
    STOP,
    FLUSH,
    RESET,
    RELEASE,
    GET_PARAMETER,
    SET_PARAMETER,
    QUEUE_INPUT_BUFFER,
    RENDER_OUTPUT_BUFFER,
    RELEASE_OUTPUT_BUFFER,
    OMX_EMPTY_BUFFER_DONE,
    OMX_FILL_BUFFER_DONE,
    BUFFER_RECYCLE,      // 内存回收（触发 FreezeBuffers）
    BUFFER_WRITEBACK,    // 内存写回（触发 ActiveBuffers）
    SUSPEND,             // 系统挂起
    RESUME,              // 系统恢复
    ...
};
```

### 2.3 DoSyncCall 封装

```
services/engine/codec/video/hcodec/hcodec.cpp:1376
bool ret = MsgHandleLoop::SendSyncMsg(msgType, msg, reply, waitMs);
```

HCodec 通过 DoSyncCall 模板将所有操作封装为同步消息，等待 OMX 层回复后返回结果。

---

## 三、FrozenState 与 RunningState — 双状态切换

### 3.1 状态类结构

HCodec::FrozenState 和 HCodec::RunningState 均继承 BaseState，覆盖 OnMsgReceived 处理各自的消息集合：

```
services/engine/codec/video/hcodec/hcodec_bg.cpp (整体441行)
```

关键状态转换路径：

| 当前状态 | 消息类型 | 行为 | 目标状态 |
|---|---|---|---|
| Running | BUFFER_RECYCLE | FreezeBuffers + SwapOut + 切换 | Frozen |
| Running | SUSPEND | DoSyncCall(OnSuspend) | -（不变）|
| Frozen | BUFFER_WRITEBACK | ActiveBuffers + SwapIn + SubmitBuffers + 切换 | Running |
| Frozen | RESUME | OnResume | -（不变）|
| Frozen | FORCE_SHUTDOWN/STOP/RELEASE | OnShutDown | Stopping |
| Frozen | QUEUE_INPUT_BUFFER | 仍可入队但延后处理 | Frozen |
| Frozen | SET_PARAMETER | 仍可设置参数 | Frozen |

### 3.2 OnSuspend / OnResume（Running状态处理SUSPEND/RESUME消息）

```
services/engine/codec/video/hcodec/hcodec_bg.cpp:388-392
case MsgWhat::SUSPEND:{
    OnSuspend(info);
    break;
}
case MsgWhat::RESUME:{
    OnResume(info);
    return;
}
```

OnSuspend/OnResume 在 RunningState 的 OnMsgReceived 中被调用，处理系统级别挂起/恢复事件（不同于 BUFFER_RECYCLE 触发 FreezeBuffers）。

---

## 四、FreezeBuffers — OMX + DMA-BUF 二阶段冻结

### 4.1 完整流程（hcodec_bg.cpp:208-227）

```cpp
int32_t HDecoder::FreezeBuffers()
{
    if (isSecure_) {
        return AVCS_ERR_OK;  // 安全解码器跳过冻结（安全内存不可swap）
    }
    // 第一阶段：通知OMX层冻结
    OMX_CONFIG_BOOLEANTYPE param {};
    InitOMXParam(param);
    param.bEnabled = OMX_TRUE;
    if (!SetParameter(OMX_IndexParamBufferRecycle, param)) {
        HLOGE("failed to set decoder to background to freeze buffers");
        return AVCS_ERR_UNKNOWN;
    }
    // 第二阶段：DMA-BUF换出
    if (SwapOutBufferByPortIndex(OMX_DirInput) != AVCS_ERR_OK) {
        return AVCS_ERR_UNKNOWN;
    }
    if (SwapOutBufferByPortIndex(OMX_DirOutput) != AVCS_ERR_OK) {
        return AVCS_ERR_UNKNOWN;
    }
    HLOGI("freeze buffers success");
    return AVCS_ERR_OK;
}
```

- `OMX_IndexParamBufferRecycle` = OMX vendor extension，通知硬件Codec进入后台冻结模式
- isSecure_ 检查：安全解码器（H264/H265 secure）不走DMA-BUF swap路径，直接返回OK

### 4.2 SwapOutBufferByPortIndex（hcodec_bg.cpp:151-169）

```cpp
int32_t HDecoder::SwapOutBufferByPortIndex(OMX_DIRTYPE portIndex)
{
    vector<BufferInfo>& pool = (portIndex == OMX_DirInput) ? inputBufferPool_ : outputBufferPool_;
    
    for (BufferInfo& info : pool) {
        if (CanSwapOut(portIndex, info) == false) {
            HLOGD("buf[%u] can't freeze owner[%d] swaped out[%d]", ...);
            continue;  // 正在用户手中的buffer不冻结
        }
        int fd = (portIndex == OMX_DirInput) ?
                 info.avBuffer->memory_->GetFileDescriptor() :
                 info.surfaceBuffer->GetFileDescriptor();
        if (DmaSwaper::GetInstance().SwapOutDma(pid_, fd) != AVCS_ERR_OK) {
            HLOGE("prot[%d] bufferId[%d], fd[%d] freeze failed", ...);
            return ActiveBuffers();  // 失败则回滚
        }
        info.hasSwapedOut = true;  // 标记已换出
    }
    return AVCS_ERR_OK;
}
```

- portIndex 区分 Input（avBuffer→memory_->GetFD()）和 Output（surfaceBuffer->GetFD()）
- CanSwapOut 检查：用户持有的buffer不能冻结（return false）
- fd：DMA-BUF 系统的文件描述符（通过 SurfaceBuffer::GetFileDescriptor() 获取）

### 4.3 CanSwapOut 判断逻辑（hcodec_bg.cpp:189-207）

```cpp
bool HDecoder::CanSwapOut(OMX_DIRTYPE portIndex, BufferInfo& info)
{
    if (portIndex == OMX_DirInput) {
        if (info.owner == BufferOwner::OWNED_BY_USER || info.hasSwapedOut) {
            return false;  // 用户手中/已换出 → 不能冻结
        }
    }
    if (portIndex == OMX_DirOutput) {
        if (currSurface_.surface_) {
            // Surface模式
            return !(info.owner == BufferOwner::OWNED_BY_SURFACE ||
                     info.hasSwapedOut || info.surfaceBuffer == nullptr);
        } else {
            // Buffer模式（Surface为空）
            return !(info.owner == BufferOwner::OWNED_BY_OMX ||
                     info.hasSwapedOut);
        }
    }
    return true;
}
```

### 4.4 ActiveBuffers（换入恢复，hcodec_bg.cpp:243-260）

```cpp
int32_t HDecoder::ActiveBuffers()
{
    if (isSecure_) {
        return AVCS_ERR_OK;
    }
    if (SwapInBufferByPortIndex(OMX_DirInput) != AVCS_ERR_OK) {
        return AVCS_ERR_UNKNOWN;
    }
    if (SwapInBufferByPortIndex(OMX_DirOutput) != AVCS_ERR_OK) {
        return AVCS_ERR_UNKNOWN;
    }
    OMX_CONFIG_BOOLEANTYPE param {};
    InitOMXParam(param);
    param.bEnabled = OMX_FALSE;
    if (!SetParameter(OMX_IndexParamBufferRecycle, param)) {  // 关闭冻结模式
        HLOGE("failed to set OMX_IndexParamBufferRecycle");
        return AVCS_ERR_UNKNOWN;
    }
    HLOGI("buffers active success");
    return AVCS_ERR_OK;
}
```

---

## 五、DmaSwaper — /dev/dma_reclaim 驱动封装

### 5.1 设备节点与IOCTL（hcodec_bg.cpp:22-40）

```cpp
#define DMA_DEVICE_FILE "/dev/dma_reclaim"
#define DMA_BUF_RECLAIM_IOC_MAGIC 'd'
#define DMA_BUF_RECLAIM_FD \
    _IOWR(DMA_BUF_RECLAIM_IOC_MAGIC, 0x07, int)
#define DMA_BUF_RESUME_FD \
    _IOWR(DMA_BUF_RECLAIM_IOC_MAGIC, 0x08, int)

struct DmaBufIoctlSwPara {
    pid_t pid;
    unsigned long ino;   // inode号
    unsigned int fd;
};

class DmaSwaper {
public:
    int32_t SwapOutDma(pid_t pid, int bufFd) {
        if (reclaimDriverFd_ <= 0) {
            return AVCS_ERR_UNKNOWN;  // 驱动未打开则失败
        }
        DmaBufIoctlSwPara param {};
        param.pid = pid;
        param.fd = bufFd;
        // ioctl(fd, DMA_BUF_RECLAIM_FD, &param) 通知内核回收DMA-BUF
        return ioctl(reclaimDriverFd_, DMA_BUF_RECLAIM_FD, &param);
    }
    int32_t SwapInDma(pid_t pid, int bufFd) {
        if (reclaimDriverFd_ <= 0) {
            return AVCS_ERR_UNKNOWN;
        }
        DmaBufIoctlSwPara param {};
        param.pid = pid;
        param.fd = bufFd;
        return ioctl(reclaimDriverFd_, DMA_BUF_RESUME_FD, &param);
    }
    static DmaSwaper& GetInstance() {
        static DmaSwaper swaper;
        return swaper;
    }
private:
    DmaSwaper() {
        reclaimDriverFd_ = open(DMA_DEVICE_FILE, O_RDWR | O_CLOEXEC | O_NONBLOCK);
        if (reclaimDriverFd_ <= 0) {
            HLOGW("dma_reclaim driver open failed, errno=%{public}d", errno);
        }
    }
    ~DmaSwaper() { close(reclaimDriverFd_); }
    int reclaimDriverFd_ = -1;  // 打开 /dev/dma_reclaim 的fd
};
```

- pid_：进程ID（用于进程级别DMA-BUF回收/恢复）
- ino：inode号（内核通过 inode 定位 DMA-BUF buffer）
- DMA_BUF_RECLAIM_FD(0x07)：将DMA-BUF换出到系统内存（释放GPU/硬件占用）
- DMA_BUF_RESUME_FD(0x08)：将DMA-BUF换入恢复（重新映射到进程）
- reclaimDriverFd_ 单例，进程生命周期内只打开一次

### 5.2 pid_ 成员变量

```cpp
services/engine/codec/video/hcodec/hcodec.h
// 在 HCodec 类中，pid_ 在 Configure 阶段设置：
// pid_ = getpid();  // 获取当前进程ID
```

---

## 六、BufferOwner 四态流转

### 6.1 BufferOwner 枚举（hcodec.h:115）

```cpp
enum BufferOwner {
    OWNED_BY_USER = 0,    // 用户侧持有（应用通过 GetOutputBuffer 拿到）
    OWNED_BY_OMX,         // OMX硬件组件持有（正在编解码）
    OWNED_BY_SURFACE,     // Surface渲染持有（Output Surface模式）
    OWNER_CNT             // 状态计数/占位
};
```

### 6.2 RecordBufferStatus 状态转移（hcodec_bg.cpp:117-122）

```cpp
void HCodec::RecordBufferStatus(OMX_DIRTYPE portIndex, uint32_t bufferId, BufferOwner nextOwner)
{
    auto bufferInfo = FindBufferInfoByID(portIndex, bufferId);
    HLOGI("port[%d] buffer[%u] next owner[%s]", portIndex, bufferId, ToString(nextOwner));
    if (bufferInfo != nullptr) {
        bufferInfo->nextStepOwner = nextOwner;  // 记录下一次转移目标
    }
}
```

### 6.3 SubmitBuffersToNextOwner（hcodec_bg.cpp:278-320）

当从 Frozen 恢复回 Running 时，调用 SubmitBuffersToNextOwner 将所有 Buffer 提交给下一个合法 Owner：

- inputBuffer：OWNED_BY_OMX → 重新入队；OWNED_BY_USER → 通知用户填充（NotifyUserToFillThisInBuffer）
- outputBuffer：OWNED_BY_OMX → 重新出队；OWNED_BY_SURFACE → 渲染；OWNED_BY_USER → 回调用户

---

## 七、NotifySuspend / NotifyResume 对外接口

### 7.1 NotifySuspend（hcodec_bg.cpp:126-133）

```cpp
int32_t HCodec::NotifySuspend()
{
    SCOPED_TRACE();
    FUNC_TRACKER();
    DoSyncCall(MsgWhat::SUSPEND, nullptr);  // 同步发送SUSPEND消息
    return AVCS_ERR_OK;
}
```

### 7.2 NotifyResume（hcodec_bg.cpp:134-141）

```cpp
int32_t HCodec::NotifyResume()
{
    SCOPED_TRACE();
    FUNC_TRACKER();
    DoSyncCall(MsgWhat::RESUME, nullptr);  // 同步发送RESUME消息
    return AVCS_ERR_OK;
}
```

两者都是同步调用（等待消息处理完成后返回），但消息处理本身可能在 Frozen/Running 状态中不改变状态机（需要外部触发 BUFFER_RECYCLE/BUFFER_WRITEBACK 才会切换状态）。

### 7.3 Related APIs in CodecBase

```cpp
// hcodec.h:66-67
int32_t NotifySuspend() override;
int32_t NotifyResume() override;

// hcocdec.cpp:612-620
int32_t HCodec::SetVideoPortInfo(OMX_DIRTYPE portIndex, const PortInfo& info)
```

---

## 八、DecreaseFreq / RecoverFreq — 频率管理

### 8.1 DecreaseFreq（hcodec_bg.cpp:230-241）

```cpp
int32_t HDecoder::DecreaseFreq()
{
    OMX_CONFIG_BOOLEANTYPE param {};
    InitOMXParam(param);
    param.bEnabled = OMX_TRUE;
    if (!SetParameter(OMX_IndexParamFreqUpdate, param)) {  // 通知硬件降频
        HLOGE("failed to set decoder to background to decrease freq");
        return AVCS_ERR_UNKNOWN;
    }
    HLOGI("Decrease Freq success");
    return AVCS_ERR_OK;
}
```

### 8.2 RecoverFreq（hcodec_bg.cpp:265-274）

```cpp
int32_t HDecoder::RecoverFreq()
{
    OMX_CONFIG_BOOLEANTYPE param {};
    InitOMXParam(param);
    param.bEnabled = OMX_FALSE;
    if (!SetParameter(OMX_IndexParamFreqUpdate, param)) {  // 通知硬件恢复频率
        HLOGE("failed to set OMX_IndexParamFreqUpdate");
        return AVCS_ERR_UNKNOWN;
    }
    HLOGI("Recover Freq success");
    return AVCS_ERR_OK;
}
```

与 FreezeBuffers/ActiveBuffers 平行，DecreaseFreq/RecoverFreq 管理硬件频率资源（GPU/内存控制器频率），与 DMA-BUF 冻结配合实现完整的后台省电。

---

## 九、关键证据汇总

| File | Lines | Evidence |
|---|---|---|
| services/engine/codec/video/hcodec/msg_handle_loop.h | 73 | MsgHandleLoop 类完整定义（73行）+SendSync/SendAsync+MsgToken队列 |
| services/engine/codec/video/hcodec/hcodec.h:70 | ~20 | MsgWhat 枚举完整列表（SUSPEND/RESUME/BUFFER_RECYCLE等） |
| services/engine/codec/video/hcodec/hcodec_bg.cpp | 441 | FreezeBuffers(208)/SwapOut(151)/SwapIn(171)/CanSwapOut(189)/ActiveBuffers(243)/DecreaseFreq(230)/RecoverFreq(265)/DmaSwaper(22-108) |
| services/engine/codec/video/hcodec/hcodec_bg.cpp:22-40 | ~20 | DmaSwaper 单例 + /dev/dma_reclaim + DMA_BUF_RECLAIM_FD/RESUME_FD + DmaBufIoctlSwPara |
| services/engine/codec/video/hcodec/hcodec_bg.cpp:126-141 | ~20 | NotifySuspend/NotifyResume 实现 |
| services/engine/codec/video/hcodec/hcodec_bg.cpp:329-410 | ~80 | FrozenState::OnMsgReceived + OnSuspend/OnResume + OnBufferWriteback + OnShutDown |
| services/engine/codec/video/hcodec/hcodec_bg.cpp:278-320 | ~40 | SubmitBuffersToNextOwner 所有BufferOwner状态重分发 |
| services/engine/codec/video/hcodec/hcodec.h:115 | ~10 | BufferOwner 枚举四态 |
| services/engine/codec/video/hcodec/hcodec_bg.cpp:117-122 | ~10 | RecordBufferStatus 状态转移记录 |
| services/engine/codec/video/hcodec/hcodec.cpp:442 | ~3 | MsgHandleLoop::Stop() 在析构中调用 |
| services/engine/codec/video/hcodec/hcodec.cpp:1376 | ~3 | SendSyncMsg 在 DoSyncCall 中调用 |
| services/engine/codec/video/hcodec/hdecoder.h:28 | ~10 | HDecoder 类声明（含 XperfConnector/SurfaceBufferItem/DecoderInst） |

---

## 十、与其他记忆的关联

- **S57**：HDecoder/HEncoder 的OMX组件架构基础（HCodec → OMX组件 → HDI V4.0）
- **S154**：VideoDecoder基类与RenderSurface双组件（包含 RenderSurface 的 Owner 枚举与 SwapOut/SwapIn）
- **S21**：MsgHandleLoop 消息循环基础设施（本次 S160 补充了与后台管理的集成）
- **S70**：CodecFactory/CodecLoader 插件体系（Freeze/Active 不涉及工厂层，纯HCodec内部）
- **S159**：AVCodec 错误码与回调体系（错误码从AVCS_ERR_OK/AVCS_ERR_UNKNOWN使用在 Freeze/Active 各处）

---

## 十一、文件速查表

| 文件路径 | 关键内容 |
|---|---|
| `services/engine/codec/video/hcodec/msg_handle_loop.h` | MsgHandleLoop 基类73行 |
| `services/engine/codec/video/hcodec/hcodec.h` | MsgWhat枚举、BufferOwner枚举、PortInfo结构、MsgHandleLoop子类关系 |
| `services/engine/codec/video/hcodec/hcodec.cpp` | OnMsgReceived消息分发、DoSyncCall、Stop() |
| `services/engine/codec/video/hcodec/hcodec_bg.cpp` | FreezeBuffers/SwapOut/SwapIn/DmaSwaper/DecreaseFreq/RecoverFreq/FrozenState/RunningState |
| `services/engine/codec/video/hcodec/hcodec_dfx.cpp` | 513行，DFX统计（Suspend/Resume计数、频率采样）|
| `services/engine/codec/video/hcodec/hdecoder.h` | HDecoder类声明（1615行hcodec.cpp的子类）|
| `services/engine/codec/video/hcodec/hencoder.h` | HEncoder类声明 |

---

_Draft generated by builder-agent subagent 2026-05-20T09:25_