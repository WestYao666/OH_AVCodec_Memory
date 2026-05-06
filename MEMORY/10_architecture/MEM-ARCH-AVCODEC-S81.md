---
mem_id: MEM-ARCH-AVCODEC-S81
status: approved
approved_at: "2026-05-06"
approved_by: feishu-user:ou_60d8641be684f82e8d9cb84c3015dde7
submitted_by: builder-agent
submitted_at: "2026-05-03T05:49:28+08:00"
scope: [AVCodec, DFX, Suspend, Freeze, PowerManagement, Monitor, AVCodecMonitor, AVCodecSuspend, AVCodecServiceFactory, CodecServer, SuspendFreeze, SuspendActive, SuspendActiveAll]
tags: [suspend, freeze, power-management, monitor, lifecycle]
associations:
  - S48 (CodecServer lifecycle - CodecServer holds SuspendFreeze/Active path)
  - S1 (codec_server.cpp承载能力)
  - S77 (AVCodec DFX四大支柱 - HiSysEvent/XCollie/Trace/Dump)
  - S57 (HDecoder/HEncoder硬件编解码器 - Frozen态与Suspend联动)
related_frontmatter:
  - MEM-ARCH-AVCODEC-001 (AVCodec模块总览, approved)
  - MEM-ARCH-AVCODEC-S48 (CodecServer七状态机, pending_approval)
---

# S81：AVCodec 暂停/冻结与运行监控——AVCodecSuspend 三模式与 AVCodecMonitor 活性查询

> **草案状态**: draft
> **生成时间**: 2026-05-03T13:18+08:00
> **scope**: AVCodec, Suspend, Freeze, PowerManagement, Monitor, AVCodecSuspend, AVCodecMonitor, AVCodecServiceFactory
> **关联场景**: 系统休眠/恢复 / 编解码生命周期管理 / 功耗控制

---

## 1. 概述

AVCodec 模块提供两类运行态控制组件，均位于 `frameworks/native/avcodec/`：

| 组件 | 文件 | 职责 |
|------|------|------|
| **AVCodecSuspend** | `avcodec_suspend.cpp` (45行) | 暂停/冻结/恢复 Codec 实例（功耗管理） |
| **AVCodecMonitor** | `avcodec_monitor.cpp` (32行) | 查询当前活跃的安全解码器进程 |

两者均委托 `AVCodecServiceFactory` 调用 `CodecServer` / `CodecBase` 层的实际实现。

```
AVCodecSuspend / AVCodecMonitor (Native API层)
        ↓ IPC
AVCodecServiceFactory::GetInstance()
        ↓
CodecServer → CodecBase（SuspendFreeze / SuspendActive）
        ↓
各 Codec 实例（VideoCodec / AudioCodec）
```

---

## 2. AVCodecSuspend——三模式暂停/恢复

**文件**: `frameworks/native/avcodec/avcodec_suspend.cpp`

**头文件**: `avcodec_suspend.h`（由 Native C API `native_avcodec_base.cpp` 调用）

### 2.1 三个入口函数

```cpp
// avcodec_suspend.cpp:28-37
int32_t AVCodecSuspend::SuspendFreeze(const std::vector<pid_t> &pidList)
{
    CHECK_AND_RETURN_RET_LOG(!pidList.empty(), AVCS_ERR_INPUT_DATA_ERROR, "Freeze pidlist is empty");
    return AVCodecServiceFactory::GetInstance().SuspendFreeze(pidList);
}

// avcodec_suspend.cpp:38-44
int32_t AVCodecSuspend::SuspendActive(const std::vector<pid_t> &pidList)
{
    CHECK_AND_RETURN_RET_LOG(!pidList.empty(), AVCS_ERR_INPUT_DATA_ERROR, "Active pidlist is empty");
    return AVCodecServiceFactory::GetInstance().SuspendActive(pidList);
}

// avcodec_suspend.cpp:45-48
int32_t AVCodecSuspend::SuspendActiveAll()
{
    return AVCodecServiceFactory::GetInstance().SuspendActiveAll();
}
```

### 2.2 三模式语义

| 模式 | 目标 | 调用链 | 典型场景 |
|------|------|--------|----------|
| **SuspendFreeze** | 冻结指定 PID 的所有 Codec 实例 | Factory → CodecServer → CodecBase::SuspendFreeze | 系统进入低功耗前 |
| **SuspendActive** | 恢复指定 PID 的所有 Codec 实例 | Factory → CodecServer → CodecBase::SuspendActive | 系统从低功耗返回 |
| **SuspendActiveAll** | 恢复所有活跃的 Codec 实例 | Factory → CodecServer → CodecBase::SuspendActiveAll | 全局恢复 |

### 2.3 与 CodecBase 状态机关联

`SuspendFreeze` 对应 `CodecBase::State::FROZEN` 态（S57:HCodec 八状态机），该态下：
- DMA-BUF 缓冲区执行 SwapOut（S80:SurfaceBuffer 内存管理）
- 解码线程暂停，不消费输入队列
- 恢复时触发 SwapIn + Buffer 重建

### 2.4 LogTag 生成

DFX 组件 `AVCodecDfxComponent`（`services/dfx/include/avcodec_dfx_component.h`）为每个 Codec 实例生成唯一 LogTag：
```cpp
std::string CreateVideoLogTag(const OHOS::Media::Meta &meta);
```
用于区分不同实例的日志，便于 Suspend 场景定位是哪个实例被冻结。

---

## 3. AVCodecMonitor——安全解码器活性查询

**文件**: `frameworks/native/avcodec/avcodec_monitor.cpp`

```cpp
// avcodec_monitor.cpp:23-28
int32_t AVCodecMonitor::GetActiveSecureDecoderPids(std::vector<pid_t> &pidList)
{
    AVCODEC_LOGD("GetActiveSecureDecoderPids entry");
    return AVCodecServiceFactory::GetInstance().GetActiveSecureDecoderPids(pidList);
}
```

**能力**: 查询当前正在运行的安全（DRM）解码器进程列表。

**用途**: 系统 Suspend 前需要确认无活跃安全解码器，否则冻结操作可能中断受保护的内容播放。

---

## 4. 与 S48 CodecServer 七状态机的映射关系

| AVCodecSuspend 行为 | CodecServer 系统级状态 | CodecBase 实例状态 |
|--------------------|----------------------|-------------------|
| SuspendFreeze | SA 可能进入低功耗态 | CodecBase::State::FROZEN |
| SuspendActive | SA 恢复正常 | 所有 Codec 实例回到 Running |
| SuspendActiveAll | 全局 SA 恢复 | 同上 |

---

## 5. 关键证据索引

| 证据 | 文件 | 行号 |
|------|------|------|
| SuspendFreeze 实现 | `avcodec_suspend.cpp` | 28-37 |
| SuspendActive 实现 | `avcodec_suspend.cpp` | 38-44 |
| SuspendActiveAll 实现 | `avcodec_suspend.cpp` | 45-48 |
| AVCodecMonitor 实现 | `avcodec_monitor.cpp` | 23-28 |
| AVCodecDfxComponent LogTag | `services/dfx/include/avcodec_dfx_component.h` | 全文 |
| CreateVideoLogTag 函数声明 | `services/dfx/include/avcodec_dfx_component.h` | 全文 |
| CodecBase FROZEN 态 | `services/engine/codec/video/hcodec/hcodec.cpp` | H codec 八状态机 |
| DMA-BUF Freeze/SwapOut | `services/media_engine/modules/sink/video_sink.cpp` | Freezed Buffers |

---

## 6. 关联记忆

- **S48** CodecServer 七状态机（UNINITIALIZED → RUNNING）——SuspendFreeze 对应 CodecBase::FROZEN
- **S57** HDecoder/HEncoder 硬件编解码器——FrozenState + DMA-BUF SuspendResume 机制
- **S80** SurfaceBuffer 与 RenderSurface 内存管理——FreezeBuffers 触发 SwapOut/SwapIn
- **S77** AVCodec DFX 四大支柱——AVCodecDfxComponent::CreateVideoLogTag 为 Suspned/Freeze 场景提供可观测性
- **S1** codec_server.cpp——承载 SuspendFreeze/Active 的服务端实现入口
