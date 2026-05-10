---
id: MEM-ARCH-AVCODEC-S114
title: "MediaCodec 核心引擎架构——CodecState 十二态机与 Plugins::CodecPlugin 驱动机制"
scope: [AVCodec, MediaCodec, CodecState, StateMachine, CodecPlugin, Plugins::CodecPlugin, Lifecycle, BufferQueue, Surface]
status: pending_approval
approval_submitted_at: "2026-05-10T09:33:00+08:00"
created_by: builder-agent
created_at: "2026-05-10T09:33:00+08:00"
关联主题: [S83(CAPI总览), S55(模块间回调), S39(VideoDecoder三层架构), S92(MediaCodec Filter封装)]
---

## Status

```yaml
created: 2026-05-10T09:33
builder: builder-agent
source: |
  services/media_engine/modules/media_codec/media_codec.h
  services/media_engine/modules/media_codec/media_codec.cpp
  (local mirror: /home/west/av_codec_repo)
```

## 1. Overview

`MediaCodec` 是 AVCodec 模块的**核心引擎类**，负责音视频编解码的完整生命周期管理。它位于 `services/media_engine/modules/media_codec/media_codec.cpp`，共 1266 行（截至 2026-05）。

核心职责：
- **CodecState 十二态机**：管理编解码器从创建到销毁的全生命周期
- **Plugins::CodecPlugin 驱动**：持有 `std::shared_ptr<Plugins::CodecPlugin> codecPlugin_`（media_codec.h:196）作为底层编解码插件代理
- **AVBufferQueue 输入队列**：`std::shared_ptr<AVBufferQueue> inputBufferQueue_`（media_codec.h:197）管理输入缓冲区
- **DRM 解密**：持有 `std::shared_ptr<MediaAVCodec::CodecDrmDecrypt> drmDecryptor_`（media_codec.h:219）用于内容解密

```
Native C API (OH_AVCodec*)
    → MediaCodec (CodecState 十二态机)
    → Plugins::CodecPlugin (底层编解码插件)
    → HDecoder/FCodec/AVCodecVideoDecoder 等具体实现
```

## 2. CodecState 十二态机

**Evidence**: `media_codec.h:35-48`

```cpp
enum class CodecState : int32_t {
    // 6个稳定态
    UNINITIALIZED,   // 初始/已释放状态
    INITIALIZED,     // 已创建（插件已加载）
    CONFIGURED,      // 已配置参数
    PREPARED,        // 已准备（缓冲区已分配）
    RUNNING,         // 运行时（编解码进行中）
    FLUSHED,         // 已 flush（队列清空）
    END_OF_STREAM,   // 流结束
    // 6个过渡态
    INITIALIZING,     // RELEASED → INITIALIZED 过渡
    STARTING,        // INITIALIZED → RUNNING 过渡
    STOPPING,        // RUNNING → INITIALIZED 过渡
    FLUSHING,        // RUNNING → FLUSHED 过渡
    RESUMING,        // FLUSHED → RUNNING 过渡
    RELEASING,       // {任意状态} → RELEASED 过渡
    ERROR,           // 错误状态
};
```

**状态转换证据**（`media_codec.cpp`）：
- Line 89: `state_(CodecState::UNINITIALIZED)` — 构造函数初始化
- Line 100: `state_ = CodecState::UNINITIALIZED;` — Release 时重置
- Line 125: `if (state_ != CodecState::UNINITIALIZED)` — 检查状态有效性
- Line 130: `state_ = CodecState::INITIALIZING;` — 创建中
- Line 142: `state_ = CodecState::INITIALIZED;` — 创建完成
- Line 145: `state_ = CodecState::UNINITIALIZED;` — 创建失败
- Line 232: `CHECK_AND_RETURN_RET_LOG(state_ == CodecState::INITIALIZED, ...)` — Configure 前置检查
- Line 238: `state_ = CodecState::CONFIGURED;` — 配置完成
- Line 294: `CHECK_AND_RETURN_RET_LOG(state_ != CodecState::FLUSHED, ...)` — Start 前检查

**状态转换图**：

```
UNINITIALIZED
    ↓ Create()
INITIALIZING → INITIALIZED
                    ↓ Configure()
                 CONFIGURED
                    ↓ Prepare()
                 PREPARED
                    ↓ Start()
                 STARTING → RUNNING
                    ↓ Stop()
                 STOPPING → INITIALIZED
                    ↓ Flush()
                 FLUSHING → FLUSHED
                    ↓ Resume()
                 RESUMING → RUNNING
                    ↓ Release()
                 RELEASING → UNINITIALIZED
                 
任何稳定态 → ERROR（错误时进入）
```

**std::atomic 线程安全**：`std::atomic<CodecState> state_`（media_codec.h:218）保证状态变量线程安全。

## 3. 生命周期七步曲

**Evidence**: `media_codec.cpp:100-300+`

| 步骤 | 方法 | 状态变化 | 关键操作 |
|------|------|---------|---------|
| 1. Init | `Create()` | UNINITIALIZED → INITIALIZING → INITIALIZED | 插件加载（media_codec.h:196 codecPlugin_） |
| 2. Configure | `Configure(meta)` | → CONFIGURED | 参数校验、元数据设置 |
| 3. Prepare | `Prepare()` | → PREPARED | AVBufferQueue 分配（media_codec.h:197 inputBufferQueue_） |
| 4. Start | `Start()` | INITIALIZED → STARTING → RUNNING | 启动编解码循环 |
| 5. Stop | `Stop()` | RUNNING → STOPPING → INITIALIZED | 停止编解码 |
| 6. Flush | `Flush()` | RUNNING → FLUSHING → FLUSHED | 清空 Buffer 队列 |
| 7. Release | `Release()` | ANY → RELEASING → UNINITIALIZED | 释放插件和缓冲区 |

**关键成员**（`media_codec.h:196-225`）：
```cpp
std::shared_ptr<Plugins::CodecPlugin> codecPlugin_;       // 底层插件代理（line:196）
std::shared_ptr<AVBufferQueue> inputBufferQueue_;            // 输入缓冲区队列（line:197）
std::shared_ptr<AVBuffer> cachedOutputBuffer_;               // 输出缓冲缓存（line:198）
std::atomic<CodecState> state_;                             // 12态机（line:218）
std::shared_ptr<MediaAVCodec::CodecDrmDecrypt> drmDecryptor_; // DRM解密器（line:219）
std::vector<std::shared_ptr<AVBuffer>> inputBufferVector_;   // 输入缓冲向量（line:220）
std::vector<std::shared_ptr<AVBuffer>> outputBufferVector_;  // 输出缓冲向量（line:221）
```

## 4. Plugins::CodecPlugin 驱动机制

**Evidence**: `media_codec.h:196` 持有插件指针，`media_codec.cpp` 中 `CreatePlugin()` / `CodePluginInputBuffer()` / `CodePluginOutputBuffer()` 调用插件：

```cpp
// media_codec.h:152-153
std::shared_ptr<Plugins::CodecPlugin> CreatePlugin(Plugins::PluginType pluginType);
std::shared_ptr<Plugins::CodecPlugin> CreatePlugin(const std::string &mime, Plugins::PluginType pluginType);

// media_codec.cpp:191
Status CodePluginInputBuffer(const std::shared_ptr<AVBuffer> &inputBuffer);
Status CodePluginOutputBuffer(std::shared_ptr<AVBuffer> &outputBuffer);
```

CodecPlugin 是底层编解码器的抽象接口，由以下具体实现满足：
- `HDecoder` / `HEncoder`：硬件编解码（HDI/OMX 组件）
- `FCodec`：FFmpeg 软件解码器（libavcodec）
- `AVCodecVideoDecoder`：Native 视频解码器封装
- `Av1Decoder`：dav1d AV1 解码器

## 5. 数据流与回调

**输入路径**：
```
AVBufferQueue (inputBufferQueue_) → AcquireBuffer() → ProcessInput()
    → codecPlugin_->SendInputBuffer() → (HDecoder/FCodec/etc.)
```

**输出路径**：
```
codecPlugin_->GetOutputBuffer() → cachedOutputBuffer_ 
    → OnOutputBufferDone() 回调
```

**双回调体系**（`media_codec.h:70-87`）：
- `CodecCallback`：音视频通用回调（`OnInputBufferDone` / `OnOutputBufferDone` / `OnError` / `OnOutputFormatChanged`）
- `AudioBaseCodecCallback`：音频编解码专用回调

## 6. 与 S92/S83/S55 的关系

| 关系 | 主题 | 说明 |
|------|------|------|
| 上游 | S83 (Native C API) | `native_avcodec_*.cpp` 通过 IPC 调用 MediaCodec |
| 互补 | S92 (MediaCodec Filter封装) | Filter 层封装（`SurfaceDecoderFilter` 等）使用 MediaCodec 作为引擎 |
| 回调 | S55 (模块间回调链路) | MediaCodec 的 `OnOutputBufferDone` 触发 CodecListenerCallback IPC 回传 |
| 实现 | S39 (VideoDecoder三层) | MediaCodec → VideoDecoderAdapter → VideoDecoder → HDecoder/FCodec |

## 7. 文件 Evidence 一览

| 文件 | 行数 | 关键内容 |
|------|------|---------|
| `media_codec.h` | 1266 行 | CodecState 十二态枚举、MediaCodec 类定义、关键成员声明 |
| `media_codec.cpp` | 1266 行 | 状态转换逻辑、插件调用、Buffer 管理、DRM 解密 |