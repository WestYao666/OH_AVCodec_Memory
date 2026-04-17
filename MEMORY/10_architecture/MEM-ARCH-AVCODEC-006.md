# MEM-ARCH-AVCODEC-006: MediaCodec 编解码数据流

## 基础信息

| 字段 | 值 |
|------|-----|
| 标题 | MediaCodec 编解码数据流 |
| 分类 | Architecture |
| 模块 | AVCodec |
| 状态 | approved |
| 关联主题 | P1a |
| 负责人 | 记忆工厂 PM |
| 创建日期 | 2026-04-17 |
| 证据来源 | `services/media_engine/modules/media_codec/media_codec.h` + `media_codec.cpp` |

---

## 1. 概述

`MediaCodec` 是 AVCodec 的核心类，负责音频编解码的完整数据流处理。它封装了 `CodecPlugin`，通过 `AVBufferQueue` 管理输入/输出 buffer，支持 Surface 模式和 Buffer 模式两种数据通路。

---

## 2. 状态机

`MediaCodec` 内部维护 `CodecState` 枚举，描述实例生命周期：

```
UNINITIALIZED
  ↓ Init()
INITIALIZING → INITIALIZED
  ↓ Configure()
CONFIGURED
  ↓ Prepare()
PREPARED
  ↓ Start()
STARTING → RUNNING
  ↓ Stop()
STOPPING → PREPARED
  ↓ Flush()
FLUSHING → FLUSHED
  ↓ Start()
RESUMING → RUNNING
  ↓ Release()
RELEASING → UNINITIALIZED
```

关键状态转换证据：
- `Init()`: `state_ = CodecState::INITIALIZING` → `state_ = CodecState::INITIALIZED`
- `Start()`: `state_ = CodecState::STARTING` → `state_ = CodecState::RUNNING`
- `Stop()`: `state_ = CodecState::STOPPING` → `state_ = CodecState::PREPARED`
- `Flush()`: `state_ = CodecState::FLUSHING` → `state_ = CodecState::FLUSHED`
- `Release()`: `state_ = CodecState::RELEASING` → `state_ = CodecState::UNINITIALIZED`

---

## 3. 输入数据流（编码/解码输入）

### 路径

```
外部调用者
  → GetInputBufferQueue() / GetInputBufferQueueConsumer()
  → inputBufferQueueProducer_->AttachBuffer()
  → InputBufferAvailableListener::OnBufferAvailable()
  → ProcessInputBuffer()
  → HandleInputBufferInner()
    → inputBufferQueueConsumer_->AcquireBuffer()  // 消费填充好的 buffer
    → DrmAudioCencDecrypt()                       // 可选 DRM 解密
    → CodePluginInputBuffer()
      → codecPlugin_->QueueInputBuffer()          // 送入 codec plugin
```

### 关键函数

| 函数 | 文件位置 | 职责 |
|------|---------|------|
| `GetInputBufferQueue()` | media_codec.cpp:ln335 | 返回 `inputBufferQueueProducer_`，供外部写入压缩数据 |
| `PrepareInputBufferQueue()` | media_codec.cpp:ln518 | 初始化输入 buffer 队列，attach 所有 buffer |
| `InputBufferAvailableListener::OnBufferAvailable()` | media_codec.cpp:ln42 | 外部写入后触发 ProcessInputBuffer |
| `ProcessInputBuffer()` | media_codec.cpp:ln472 | 入口函数，协调输入处理 |
| `HandleInputBufferInner()` | media_codec.cpp:ln483 | 从 consumer 取出 buffer，送入 plugin |
| `CodePluginInputBuffer()` | media_codec.cpp:ln830 | 调用 `codecPlugin_->QueueInputBuffer()` |
| `OnInputBufferDone()` | media_codec.cpp:ln708 | Plugin 用完输入 buffer 后回调，release 回队列 |

### DRM 解密路径（可选）

```
HandleInputBufferInner()
  → DrmAudioCencDecrypt(filledInputBuffer)
    → AttachDrmBufffer()              // 分配 DRM 临时 buffer
    → memcpy_s() 复制输入数据到 DRM buffer
    → drmDecryptor_->DrmAudioCencDecrypt()
    → memcpy_s() 复制解密数据回原 buffer
```

---

## 4. 输出数据流（编码/解码输出）

### 路径

```
codecPlugin_->QueueOutputBuffer()     // Plugin 产生输出
  → HandleOutputBufferOnce()
    → outputBufferQueueProducer_->RequestBuffer()  // 请求空 buffer
    → CodePluginOutputBuffer()
      → codecPlugin_->QueueOutputBuffer(outputBuffer)  // 送入队列
    → outputBufferQueueProducer_->PushBuffer(buffer, true)  // 推送给消费方
  → OnOutputBufferDone()                 // 回调通知
    → mediaCodecCallback_->OnOutputBufferDone(outputBuffer)  // 通知外部
```

### 关键函数

| 函数 | 文件位置 | 职责 |
|------|---------|------|
| `HandleOutputBufferOnce()` | media_codec.cpp:ln618 | 从 output queue 取空 buffer，调用 plugin 输出 |
| `HandleOutputBuffer()` | media_codec.cpp:ln603 | 同步/异步输出处理入口 |
| `CodePluginOutputBuffer()` | media_codec.cpp:ln843 | 调用 `codecPlugin_->QueueOutputBuffer()` |
| `OnOutputBufferDone()` | media_codec.cpp:ln721 | 输出 buffer 推送后回调，触发外部 OnOutputBufferDone |

---

## 5. 两种工作模式

### Buffer 模式

- 外部通过 `GetInputBufferQueue()` 获取 producer，手动写入压缩数据
- 通过 `GetOutputBufferQueueProducer()` 获取输出队列
- 通过 `SetCodecCallback()` 设置 `AudioBaseCodecCallback` 接收 `OnOutputBufferDone` 回调

### Surface 模式

- 通过 `SetOutputSurface(sptr<Surface>)` 设置输出 Surface
- 输入通过 `GetInputSurface()` 获取 Surface 用于写入原始数据

### 关键区分变量

```cpp
bool isSurfaceMode_;   // 是否 Surface 模式
bool isBufferMode_;   // 是否 Buffer 模式
// 两者互斥，不能同时为 true
```

---

## 6. Plugin 创建与切换

### 创建

```cpp
// 通过 mime 类型创建
CreatePlugin(const std::string &mime, Plugins::PluginType pluginType)
  → Plugins::PluginManagerV2::Instance().CreatePluginByMime(pluginType, mime)
  → std::reinterpret_pointer_cast<Plugins::CodecPlugin>(plugin)

// 通过 name 直接创建
Init(const std::string &name)
  → Plugins::PluginManagerV2::Instance().CreatePluginByName(name)
```

### Plugin 动态切换

```cpp
ChangePlugin(const std::string &mime, bool isEncoder, const std::shared_ptr<Meta> &meta)
  → codecPlugin_->Release()
  → CreatePlugin(mime, type)
  → codecPlugin_->SetParameter(meta)
  → codecPlugin_->Init()
  → codecPlugin_->SetDataCallback(this)
  → PrepareInputBufferQueue()
  → PrepareOutputBufferQueue()
  → codecPlugin_->Start()  // 如果当前在 RUNNING 状态
```

---

## 7. 核心成员变量

| 变量 | 类型 | 含义 |
|------|------|------|
| `codecPlugin_` | `std::shared_ptr<Plugins::CodecPlugin>` | 实际编解码插件 |
| `inputBufferQueue_` | `std::shared_ptr<AVBufferQueue>` | 输入 buffer 队列 |
| `inputBufferQueueProducer_` | `sptr<AVBufferQueueProducer>` | 输入队列生产者（外部写） |
| `inputBufferQueueConsumer_` | `sptr<AVBufferQueueConsumer>` | 输入队列消费者（MediaCodec 读） |
| `outputBufferQueueProducer_` | `sptr<AVBufferQueueProducer>` | 输出队列生产者（MediaCodec 写） |
| `codecCallback_` | `std::weak_ptr<CodecCallback>` | 视频 codec 回调 |
| `mediaCodecCallback_` | `std::weak_ptr<AudioBaseCodecCallback>` | 音频 codec 回调 |
| `drmDecryptor_` | `std::shared_ptr<CodecDrmDecrypt>` | DRM 解密器 |

---

## 8. 数据流图（文本版）

```
【输入方向】
外部 → inputBufferQueueProducer_->AttachBuffer() → inputBufferQueue_
         ↓
   InputBufferAvailableListener::OnBufferAvailable()
         ↓
   ProcessInputBuffer() → HandleInputBufferInner()
         ↓
   inputBufferQueueConsumer_->AcquireBuffer() → filledInputBuffer
         ↓ (可选)
   DrmAudioCencDecrypt() → 解密后 buffer
         ↓
   CodePluginInputBuffer() → codecPlugin_->QueueInputBuffer()
         ↓
   OnInputBufferDone() → ReleaseBuffer() 回队列

【处理方向】
codecPlugin_ 内部编解码

【输出方向】
codecPlugin_ → QueueOutputBuffer()
         ↓
   HandleOutputBufferOnce()
         ↓
   outputBufferQueueProducer_->RequestBuffer() → emptyBuffer
         ↓
   CodePluginOutputBuffer() → codecPlugin_->QueueOutputBuffer(emptyBuffer)
         ↓
   outputBufferQueueProducer_->PushBuffer(buffer, true)
         ↓
   OnOutputBufferDone() → mediaCodecCallback_->OnOutputBufferDone()
```

---

## 9. 调用时序（典型解码流程）

```
1. MediaCodec::Init(mime, isEncoder=false)   // 创建 plugin，进入 INITIALIZED
2. MediaCodec::Configure(meta)                  // 设置参数，进入 CONFIGURED
3. MediaCodec::SetCodecCallback(callback)     // 注册回调
4. MediaCodec::SetOutputBufferQueue(producer) // Buffer 模式：设置输出队列
5. MediaCodec::Prepare()                       // 准备 buffer，进入 PREPARED
6. MediaCodec::GetInputBufferQueue()          // 获取输入队列，写入压缩数据
7. MediaCodec::Start()                        // 启动，进入 RUNNING
8. 外部填充输入 buffer → InputBufferAvailableListener 触发 ProcessInputBuffer
9. HandleInputBufferInner → codecPlugin_->QueueInputBuffer()
10. Plugin 处理完成 → OnOutputBufferDone → PushBuffer → 外部收到输出
11. MediaCodec::Stop() / Flush() / Release()  // 结束流程
```

---

## 10. 关键约束

- `Configure()` 必须在 `INITIALIZED` 状态调用
- `SetOutputBufferQueue()` / `SetOutputSurface()` 在 `INITIALIZED` 或 `CONFIGURED` 状态调用
- `GetInputBufferQueue()` / `GetOutputBufferQueueProducer()` 只在 `PREPARED`/`RUNNING`/`FLUSHED`/`END_OF_STREAM` 状态有效
- `Start()` 只在 `PREPARED` 或 `FLUSHED` 状态有效
- Buffer 模式和 Surface 模式互斥，不能同时设置
- DRM 解密仅在 `drmDecryptor_` 非空时启用（`SUPPORT_DRM` 宏）

---

## 关联记忆

- MEM-ARCH-AVCODEC-001: AVCodec 模块总览（5大层）
- MEM-ARCH-AVCODEC-003: Plugin 架构
- MEM-ARCH-AVCODEC-005: Codec 实例生命周期
