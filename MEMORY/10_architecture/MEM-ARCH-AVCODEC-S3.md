---
id: MEM-ARCH-AVCODEC-S3
title: CodecServer Pipeline 数据流与状态机
scope: [AVCodec, Core, Pipeline, StateMachine]
status: draft
author: Builder Agent
created_at: "2026-04-21T23:21:00+08:00"
type: architecture_fact
confidence: high
tags: [AVCodec, Pipeline, DataFlow, StateMachine, CodecServer, Buffer]
evidence_links:
  - /home/west/av_codec_repo/services/services/codec/server/video/codec_server.cpp
  - /home/west/av_codec_repo/services/services/codec/server/video/codec_server.h
related:
  - MEM-ARCH-AVCODEC-S1
  - MEM-ARCH-AVCODEC-006
  - MEM-ARCH-AVCODEC-016
owner: 耀耀
summary: >
  CodecServer（视频编解码服务实例容器）的 Pipeline 数据流与状态机。
  区分 CodecServer 状态机（UNINITIALIZED→INITIALIZED→CONFIGURED→RUNNING/FLUSHED/END_OF_STREAM/ERROR）
  与 MediaCodec 状态机（UNINITIALIZED→INITIALIZING→INITIALIZED→CONFIGURED→PREPARED→RUNNING）的差异。
  覆盖输入/输出数据流路径、关键状态转换条件、与 CodecBase Plugin 的调用关系。
关联场景: [新需求开发, 问题定位]
review:
  owner: 耀耀
  change_policy: update_on_code_change
update_trigger: code_change
created_at: "2026-04-21"
updated_at: "2026-04-21"
---

# CodecServer Pipeline 数据流与状态机

## 1. 概述

本条目聚焦 **CodecServer**（`services/services/codec/server/video/codec_server.cpp`）的 Pipeline 数据流与状态机，与 S1（codec_server 角色定位）和 S2（C API 使用场景）形成三角互补。

**CodecServer** 是视频编解码的服务实例容器，内部委托 `CodecBase` 插件执行实际编解码，通过回调向上层应用推送数据。

---

## 2. CodecServer 状态机详解

### 2.1 状态枚举

```cpp
// codec_server.h 行 40-48
enum CodecStatus {
    UNINITIALIZED = 0,   // 初始/已释放
    INITIALIZED,          // 已初始化插件
    CONFIGURED,           // 已配置格式参数
    RUNNING,             // 运行中
    FLUSHED,             // 已刷空缓冲区
    END_OF_STREAM,       // EOS已处理
    ERROR,               // 错误状态
};
```

**源码证据**：`codec_server.h` 行 40-48

### 2.2 完整状态转换图

```
                    ┌──────────────────────────────────────────────────────┐
                    │                      UNINITIALIZED                   │
                    └──────────────────────────────────────────────────────┘
                                               │
                                          Init() │
                                               ▼
┌──────────────────────────────────────── INITIALIZED ────────────────────────────────────────┐
│                                                                                               │
│                                      Configure()                                              │
│                                           ▼                                                   │
│                               ┌──────────────────┐                                          │
│                               │   CONFIGURED     │                                          │
│                               └──────────────────┘                                          │
│                                      │            │                                           │
│                                 Start()      Stop() (from RUNNING/FLUSHED/EOS)               │
│                                      │            │                                           │
│                                      ▼            │                                           │
│                               ┌──────────┐        │                                           │
│                               │ RUNNING  │─────────┘ ← re-Start() from CONFIGURED            │
│                               └──────────┘                                                │
│                            │         │         │                                            │
│                      Flush()    NotifyEos()   Stop()                                         │
│                            │         │         │                                            │
│                            ▼         ▼         ▼                                            │
│                      ┌─────────┐ ┌───────┐ ┌──────────┐                                    │
│                      │ FLUSHED │ │  EOS   │ │CONFIGURED│ ← back to CONFIGURED              │
│                      └─────────┘ └───────┘ └──────────┘                                    │
│                          │                                   ▲                               │
│                     Start() ◄─────────────────────────────────┘                               │
│                     (resume)                                                              │
│                                                                                             │
│  任意状态 ──────────────────────────── Reset() ──────────────────────────────────► UNINITIALIZED │
│                                                                                             │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
                              │
                    any state error
                              ▼
                    ┌─────────────────┐
                    │     ERROR       │
                    └─────────────────┘
                              │
                         Reset()
                              ▼
                    ┌─────────────────┐
                    │  UNINITIALIZED │
                    └─────────────────┘
```

**源码证据**：`codec_server.cpp` 行 1040-1049（StatusChanged）
```cpp
inline void CodecServer::StatusChanged(CodecStatus newStatus, bool printLog)
{
    if (status_ == newStatus) {
        return;
    }
    if (newStatus == ERROR && videoCb_ != nullptr && ...) {
        videoCb_->OnError(AVCODEC_ERROR_FRAMEWORK_FAILED, AVCS_ERR_INVALID_STATE);
    }
    EXPECT_AND_LOGI_WITH_TAG(printLog, "%{public}s -> %{public}s",
        GetStatusDescription(status_).data(), GetStatusDescription(newStatus).data());
    status_ = newStatus;
}
```

### 2.3 关键状态转换条件

| 当前状态 | 操作 | 目标状态 | 源码行 |
|---------|------|---------|--------|
| UNINITIALIZED | Init() | INITIALIZED | cpp:151 |
| INITIALIZED | Configure() | CONFIGURED | cpp:241 |
| CONFIGURED | Start() | RUNNING | cpp:332 |
| RUNNING | Flush() | FLUSHED | cpp:414 |
| RUNNING | NotifyEos/EOS flag | END_OF_STREAM | cpp:429 |
| FLUSHED | Start() | RUNNING | cpp:319 |
| any (except UNINITIALIZED) | Reset() | UNINITIALIZED | cpp:457 |
| CONFIGURED/RUNNING/FLUSHED/EOS | Stop() | CONFIGURED | cpp:380 |
| any (except UNINITIALIZED) | Release() | UNINITIALIZED | cpp:461 |
| any | error | ERROR | cpp:233/238/330... |

---

## 3. 输入数据流（Input Pipeline）

### 3.1 完整路径

```
上层应用（Native/C++）
    │
    │ OH_VideoDecoder_PushInputData() / OH_VideoEncoder_PushInputData()
    │         [index from OnNeedInputBuffer callback]
    ▼
CodecServiceStub（IPC层，每实例一个 CodecServer）
    │
    │ QueueInputBuffer(index, info, flag)
    ▼
CodecServer::QueueInputBuffer()
    │
    ├── flag & AVCODEC_BUFFER_FLAG_EOS ?
    │     → StatusChanged(END_OF_STREAM)
    │
    ├── DrmVideoCencDecrypt(index)  [if DRM enabled]
    │     → decryptVideoBufs_[index].inBuf
    │
    ├── temporalScalability_->ConfigureLTR(index)  [if temporal scalability]
    │
    ├── smartFluencyDecoding_->MakePreDecodeDecision(index)  [if SFD enabled]
    │
    └── codecBase_->QueueInputBuffer(index)
              │
              ▼
        CodecBase Plugin（libfcodec.z.so / libhcodec.z.so）
              │
              │ 实际解码/编码处理
              ▼
        CodecBaseCallback::OnInputBufferDone(index)
              │
              ▼
        CodecServer::OnInputBufferAvailable(index, buffer)
              │
              ├── drmDecryptor_ ? → 复用 decryptVideoBufs_
              └── 否则直接回调
              │
              ▼
        videoCb_->OnInputBufferAvailable(index, buffer)
              │
              ▼
        应用收到 OnNeedInputBuffer 回调（重新填充）
```

**源码证据**：`codec_server.cpp` 行 623-671（QueueInputBuffer）
```cpp
int32_t CodecServer::QueueInputBuffer(uint32_t index, AVCodecBufferInfo info, AVCodecBufferFlag flag)
{
    std::shared_lock<std::shared_mutex> freeLock(freeMutex_);
    if (isFree_) {
        return AVCS_ERR_INVALID_STATE;  // Stop后拒绝输入
    }
    if (flag & AVCODEC_BUFFER_FLAG_EOS) {
        ret = QueueInputBufferIn(index);
        if (ret == AVCS_ERR_OK) {
            CodecStatus newStatus = END_OF_STREAM;
            StatusChanged(newStatus);
        }
    } else {
        ret = QueueInputBufferIn(index);
    }
    return ret;
}
```

### 3.2 CodecServer vs MediaCodec 输入流差异

| 特性 | CodecServer（视频） | MediaCodec（音频） |
|------|-------------------|-------------------|
| 输入来源 | 上层通过 IPC 调用 QueueInputBuffer | Demuxer Filter 通过 AVBufferQueue |
| DRM 路径 | DrmVideoCencDecrypt（视频CENC） | DrmAudioCencDecrypt（音频CENC） |
| 回调路径 | CodecBaseCallback→CodecServer→videoCb_ | InputBufferAvailableListener→ProcessInputBuffer |
| 状态检查 | isFree_（Stop后拒绝输入）| state_ == RUNNING |

---

## 4. 输出数据流（Output Pipeline）

### 4.1 完整路径

```
CodecBase Plugin 产生输出帧
    │
    │ codecBase_->OnOutputBufferAvailable(index, buffer)
    ▼
CodecBaseCallback::OnOutputBufferAvailable(index, buffer)
    │
    ▼
CodecServer::OnOutputBufferAvailable(index, buffer)
    │
    ├── postProcessing_ ? → PostProcessingOnOutputBufferAvailable(index)
    │     ├── postProcessing_->ReleaseOutputBuffer(index, render)
    │     └── videoCb_->OnOutputBufferAvailable(index, buffer) [延迟到PostProcessing完成后]
    │
    └── 直接回调（无PostProcessing）
              │
              ▼
        videoCb_->OnOutputBufferAvailable(index, buffer)
              │
              ▼
        上层应用收到 OnNewOutputBuffer 回调
              │
              ▼
        应用层决定：
        ├── Surface模式 → RenderOutputData() / RenderOutputBufferAtTime()
        │     → CodecServer::ReleaseOutputBuffer(index, true)
        │         ├── isLocalReleaseMode_ ? → releaseBufferTask_
        │         └── postProcessing_ ? → ReleaseOutputBufferOfPostProcessing()
        │              └── codecBase_->ReleaseOutputBuffer(index)
        │
        └── 内存模式 → GetOutputBuffer() → 处理数据 → FreeOutputBuffer()
                                      │                      │
                                      └──── codecBase_->ReleaseOutputBuffer(index)
```

**源码证据**：`codec_server.cpp` 行 1144-1162（OnOutputBufferAvailable注释）
```cpp
void CodecServer::OnOutputBufferAvailable(uint32_t index, std::shared_ptr<AVBuffer> buffer)
{
    // If post processing is enabled and there is data,
    // the thread will pop the data from the queue and calls "CodecServer::ReleaseOutputBuffer" to flush
    // according to the index. The callback ipc proxy's function "videoCb_->OnOutputBufferAvailable" is called
    // later in "PostProcessingOnOutputBufferAvailable" by video processing engine when the frame is processed
    if (postProcessing_ != nullptr) {
        PostProcessingOnOutputBufferAvailable(index, 0);
        return;
    }
    // ... direct callback path
}
```

### 4.2 Surface模式 vs 内存模式 输出差异

| 模式 | 处理路径 | render参数 | buffer生命周期管理 |
|------|---------|-----------|------------------|
| Surface模式 | RenderOutputData → ReleaseOutputBufferOfCodec | `render=true` | Surface自动管理，CodecServer不主动释放 |
| 内存模式 | GetOutputBuffer → FreeOutputBuffer | `render=false` | 应用手动释放，漏掉会导致泄漏 |
| PostProcessing | ReleaseOutputBufferOfPostProcessing | 由postProcessing控制 | postProcessing持有buffer直至处理完成 |

---

## 5. CodecServer 状态机 vs MediaCodec 状态机

这是两个**不同的状态机**，分别服务于视频和音频编解码：

| 特性 | CodecServer（视频） | MediaCodec（音频） |
|------|-------------------|-------------------|
| 所在层 | services/（系统服务层） | media_engine/（引擎层） |
| 文件 | codec_server.cpp/h | media_codec.cpp/h |
| 状态数 | 7个（UNINITIALIZED→ERROR） | 至少6个（含INITIALIZING/STARTING/STOPPING等瞬态） |
| 瞬态状态 | 无（状态直接切换） | 有（INITIALIZING/STARTING/STOPPING/FLUSHING等） |
| EOS处理 | BufferFlag_EOS → END_OF_STREAM | NotifyEndOfStream() → EOS |
| Stop行为 | → CONFIGURED（可立即Start） | → PREPARED（需重新Start） |
| Flush行为 | → FLUSHED（可Start恢复） | → FLUSHED（需Start恢复） |
| 硬件对应 | CodecServer实例 | MediaCodec实例 |

**关键差异**：MediaCodec 的 Stop → PREPARED，而 CodecServer 的 Stop → CONFIGURED。这意味着视频 CodecServer Stop 后可以直接 Start，而音频 MediaCodec Stop 后也需要 Start。

---

## 6. Buffer 生命周期管理

### 6.1 输入 Buffer 生命周期

```
1. 应用收到 OnNeedInputBuffer(index, buffer)
2. 应用填充压缩数据（NALU/YUV）
3. 应用调用 PushInputData/PushInputBuffer
4. CodecServer::QueueInputBuffer → codecBase_->QueueInputBuffer
5. CodecBase 消费完成后触发 OnInputBufferDone
6. CodecServer 重新触发 OnInputBufferAvailable（buffer可复用）
```

### 6.2 输出 Buffer 生命周期

```
1. CodecBase 处理完成，OnOutputBufferAvailable(index, buffer)
2. CodecServer 通知应用 OnNewOutputBuffer
3. 应用选择路径：
   a) Surface模式：RenderOutputData → ReleaseOutputBuffer(render=true)
      → isLocalReleaseMode_ ? 走releaseBufferTask_异步释放
      → 否则 codecBase_->ReleaseOutputBuffer
   b) 内存模式：GetOutputBuffer → 处理 → FreeOutputBuffer
      → codecBase_->ReleaseOutputBuffer
```

---

## 7. 关键文件索引

| 文件 | 作用 |
|------|------|
| `codec_server.cpp` | CodecServer 主类，状态机 + 数据流入口（~1800行） |
| `codec_server.h` | CodecServer 类声明，包含 CodecStatus 枚举 |
| `codecbase.h` | CodecBase 抽象基类，插件接口定义 |
| `codec_service_stub.cpp` | IPC 入口，每个连接创建 CodecServer 实例 |
| `media_codec.cpp` | MediaCodec（AUDIO），独立状态机体系 |
| `post_processing/` | 解码后处理模块（视频解码+Surface模式） |
| `features/sfd/` | SmartFluencyDecoding 智能解码 |

---

## 8. 与现有记忆的互补关系

| 记忆 | 覆盖内容 | S3补充 |
|------|---------|--------|
| MEM-ARCH-AVCODEC-S1 | codec_server 角色定位 + 插件加载 | S3聚焦**状态机细节** + **数据流路径** |
| MEM-ARCH-AVCODEC-006 | MediaCodec（音频）数据流 | 视频CodecServer的独立数据流体系 |
| MEM-ARCH-AVCODEC-016 | AVBufferQueue + TaskThread | CodecServer内部不直接用AVBufferQueue，而是直接的IPC调用 |

---

## 9. 典型问题排查

**问题：输入数据后无输出**
- [ ] CodecServer 是否处于 RUNNING 状态？（Stop/Flush 后会退到 CONFIGURED）
- [ ] QueueInputBuffer 是否返回 AVCS_ERR_OK？
- [ ] 是否在 EOS 后继续 PushInputData？（EOS后拒绝输入）

**问题：OnNewOutputBuffer 持续不触发**
- [ ] 是否 codecBase_->Start() 成功？（CodecBase 内部错误会导致状态切 ERROR）
- [ ] postProcessing_ 是否正常？（postProcessing 异常会阻断输出回调）

**问题：Surface 模式画面卡住**
- [ ] 是否漏掉 ReleaseOutputBuffer？（Surface 模式也需要 release）
- [ ] releaseBufferTask_ 是否正常工作？（isLocalReleaseMode_ 时）

---

*本草案基于 `multimedia_av_codec` 仓库真实代码分析，覆盖 CodecServer 状态机完整转换图、输入/输出数据流路径、与 MediaCodec 状态机的差异对比*
