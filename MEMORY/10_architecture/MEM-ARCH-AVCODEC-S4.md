---
id: MEM-ARCH-AVCODEC-S4
title: Surface Mode 与 Buffer Mode 双模式切换机制
scope: [AVCodec, Core, SurfaceMode, BufferMode, ModeSwitch]
status: approved
created_at: 2026-04-22
approved_at: 2026-04-23
---

# Surface Mode 与 Buffer Mode 双模式切换机制

> **Builder 验证记录（2026-04-22）**：基于本地仓库 `/home/west/av_codec_repo` 代码验证，聚焦双模式区分与切换逻辑。覆盖 `isSurfaceMode_` 标志、`CreateInputSurface`、`SetInputSurface`、`SetOutputSurface` 的状态约束，以及停止时的 Surface 清理。

## 1. 概述

CodecServer 支持两种数据供给/消费模式：

- **Surface Mode**：解码器直接将图片输出到 Surface（GPU 合成），常用于视频播放、相机预览等场景
- **Buffer Mode**：应用通过 `OH_AVCodec_GetInputBuffer()` 获取原始 buffer，自己管理渲染

切换依据是在 `Configure` 之后、首次 `QueueInputBuffer` 之前是否创建/绑定了 Surface。**一旦进入某种模式并开始编解码，模式即锁定，不可切换。**

---

## 2. 核心标志位

```cpp
// codec_server.h（行 85-90）
bool isSurfaceMode_ = false;          // 是否为 Surface 模式
bool isCreateSurface_ = false;       // 是否由 CodecServer 自身创建了 InputSurface
bool isModeConfirmed_ = false;        // 模式是否已确认（第一次 QueueInputBuffer 后锁定）
```

证据：`isSurfaceMode_` 在以下位置被设置：
- `CreateInputSurface()` 行 534：`isSurfaceMode_ = true`
- `SetInputSurface()` 行 547：`isSurfaceMode_ = (ret == AVCS_ERR_OK)`
- `SetOutputSurface()` 行 571：`isSurfaceMode_ = (ret == AVCS_ERR_OK)`
- 停止路径行 466、509：`isSurfaceMode_ = false`

---

## 3. Surface Mode 入口

### 3.1 CreateInputSurface（CodecServer 自行创建 Surface）

```cpp
// codec_server.cpp 行 526-538
sptr<Surface> CodecServer::CreateInputSurface()
{
    std::lock_guard<std::shared_mutex> lock(mutex_);
    CHECK_AND_RETURN_RET_LOG_WITH_TAG(status_ == CONFIGURED, nullptr,
        "In invalid state, %{public}s", GetStatusDescription(status_).data());
    CHECK_AND_RETURN_RET_LOG_WITH_TAG(codecBase_ != nullptr, nullptr, "Codecbase is nullptr");
    sptr<Surface> surface = codecBase_->CreateInputSurface();
    if (surface != nullptr) {
        isSurfaceMode_ = true;
        isCreateSurface_ = true;
    }
    return surface;
}
```

**约束**：只能在 `CONFIGURED` 状态调用。返回的 Surface 交给应用用于输入原始视频帧。

### 3.2 SetInputSurface（应用将已有 Surface 注入 CodecServer）

```cpp
// codec_server.cpp 行 540-548
int32_t CodecServer::SetInputSurface(sptr<Surface> surface)
{
    std::lock_guard<std::shared_mutex> lock(mutex_);
    CHECK_AND_RETURN_RET_LOG_WITH_TAG(status_ == CONFIGURED, AVCS_ERR_INVALID_STATE,
        "In invalid state, %{public}s", GetStatusDescription(status_).data());
    CHECK_AND_RETURN_RET_LOG_WITH_TAG(codecBase_ != nullptr, AVCS_ERR_NO_MEMORY, "Codecbase is nullptr");
    int32_t ret = codecBase_->SetInputSurface(surface);
    isSurfaceMode_ = (ret == AVCS_ERR_OK);
    return ret;
}
```

**约束**：同样仅在 `CONFIGURED` 状态有效。

### 3.3 SetOutputSurface（设置解码器/编码器输出 Surface）

```cpp
// codec_server.cpp 行 551-572
int32_t CodecServer::SetOutputSurface(sptr<Surface> surface)
{
    std::lock_guard<std::shared_mutex> lock(mutex_);
    bool isBufferMode = isModeConfirmed_ && !isSurfaceMode_;
    CHECK_AND_RETURN_RET_LOG_WITH_TAG(!isBufferMode, AVCS_ERR_INVALID_OPERATION, "In buffer mode");
    // 只有 Surface mode 才允许设置 output surface
    bool isValidState = isModeConfirmed_
        ? isSurfaceMode_ && (status_ == CONFIGURED || status_ == RUNNING ||
                             status_ == FLUSHED || status_ == END_OF_STREAM)
        : status_ == CONFIGURED;
    CHECK_AND_RETURN_RET_LOG_WITH_TAG(isValidState, AVCS_ERR_INVALID_STATE,
        "In invalid state, %{public}s", GetStatusDescription(status_).data());
    // ... postProcessing 或 codecBase_->SetOutputSurface
    isSurfaceMode_ = (ret == AVCS_ERR_OK);
    return ret;
}
```

**关键约束**：
- Buffer Mode 下**绝对禁止**调用 `SetOutputSurface`（`AVCS_ERR_INVALID_OPERATION`）
- Surface Mode 下可在 `CONFIGURED | RUNNING | FLUSHED | EOS` 状态设置
- 如果配置了后处理（`postProcessing_`），优先走 `SetOutputSurfaceForPostProcessing`

---

## 4. 停止时的 Surface 清理

```cpp
// codec_server.cpp 行 499-509
if (isSurfaceMode_ && codecType_ == AVCODEC_TYPE_VIDEO_DECODER) {
    SurfaceTools::GetInstance().ReleaseSurface(instanceId_,
        SurfaceUtils::GetInstance()->GetSurface(surfaceId_),
        pushBlankBufferOnShutdown_, true);
}
isSurfaceMode_ = false;
```

停止时自动清理 Surface 资源，仅针对视频解码器（`AVCODEC_TYPE_VIDEO_DECODER`）。

另外在销毁路径（行 376-378）也会用 `SurfaceTools::GetInstance().CleanCache()` 清理缓存。

---

## 5. 双模式状态转换图

```
[UNINITIALIZED]
      |
   Init()
      v
[INITIALIZED]
      |
  Configure()
      v
[CONFIGURED]  ← 可在此处创建/注入 Surface
      |
      +-- CreateInputSurface() ──→ isSurfaceMode_ = true
      +-- SetInputSurface()  ────→ isSurfaceMode_ = true
      |
   Start()
      |
   QueueInputBuffer() ─── isModeConfirmed_ = true（模式锁定）
      |
      v
[RUNNING]（Surface Mode 或 Buffer Mode）
      |
   Stop()
      v
[CONFIGURED]（可重新 Configure）
```

> 注意：Buffer Mode 的 `OH_VideoDecoder_CreateByMime/Name` 不涉及 Surface，编解码全通过 `GetInputBuffer`/`SubmitInputBuffer`/`GetOutputBuffer`/`ReleaseOutputBuffer` API 驱动。

---

## 6. DFX 埋点中的模式记录

```cpp
// codec_server.cpp 行 1241
codecDfxInfo.codecMode = isSurfaceMode_ ? "Surface mode" : "Buffer Mode";
```

DFX 信息中记录当前模式，用于问题定位。

---

## 7. 相关文件

| 文件 | 作用 |
|------|------|
| `services/services/codec/server/video/codec_server.cpp` | Surface/Buffer 模式判断与切换逻辑 |
| `services/services/codec/server/video/codec_server.h` | `isSurfaceMode_` 等标志位定义 |
| `interfaces/kits/c/native_avcodec_videodecoder.h` | Native C API（CreateByMime/Name） |
| `interfaces/kits/c/native_avcodec_videoencoder.h` | 编码器 Surface mode C API |

---

## 8. 关联记忆

- **MEM-ARCH-AVCODEC-S1**：`codec_server.cpp` 的角色定位（服务实例容器）
- **MEM-ARCH-AVCODEC-S2**：Native C API 使用场景
- **MEM-ARCH-AVCODEC-S3**：CodecServer Pipeline 数据流与状态机
- **MEM-ARCH-AVCODEC-016**：`AVBufferQueue` 异步编解码队列机制
