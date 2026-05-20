---
type: architecture
id: MEM-ARCH-AVCODEC-S167
status: pending_approval
topic: MediaCodec 核心引擎与 Utils 工具链——MediaCodec(CodecState 十二态机+Plugins::DataCallback 双回调) + TaskThread(五态机+500ms自醒) + SurfaceTools(单例+Surface生命周期)
scope: [AVCodec, MediaCodec, CodecState, Utils, TaskThread, SurfaceTools, Plugin, DataCallback, StateMachine]
assoc_scenes: 新需求开发, 问题定位, 新人入项, 代码导航
builder: builder-agent
created: 2026-05-20T22:55 Asia/Shanghai
evidence_source: local_mirror /home/west/av_codec_repo
---

# MEM-ARCH-AVCODEC-S167 — MediaCodec 核心引擎与 Utils 工具链

## Metadata

| 字段 | 内容 |
|------|------|
| ID | MEM-ARCH-AVCODEC-S167 |
| 标题 | MediaCodec 核心引擎与 Utils 工具链——MediaCodec(CodecState 十二态机+Plugins::DataCallback 双回调) + TaskThread(五态机+500ms自醒) + SurfaceTools(单例+Surface生命周期) |
| 状态 | draft |
| 创建时间 | 2026-05-20T22:55 Asia/Shanghai |
| Builder | builder-agent |
| 标签 | AVCodec, MediaCodec, CodecState, Utils, TaskThread, SurfaceTools, Plugin, DataCallback, StateMachine, Lifecycle |
| 关联主题 | S92(MediaCodec核心引擎), S14(FilterChain), S34(MuxerFilter), S41(DemuxerFilter), S22(MediaSyncManager), S98(VideoSink/AudioSink/SubtitleSink), S152(TaskThread+SurfaceTools), S57(CodecServer状态机) |
| 源码路径 | /home/west/av_codec_repo/services/media_engine/modules/media_codec/ + /home/west/av_codec_repo/services/utils/ |

---

## 1. 架构概述

S167 记录两个互补子系统：

1. **MediaCodec 核心引擎**（`modules/media_codec/media_codec.cpp/h`）——编解码实例的顶层引擎，管理 CodecState 十二态机、Plugin 生命周期、缓冲区队列、Surface/Buffer 双模式输入，继承 `Plugins::DataCallback` 接收 Plugin 输出回调

2. **Utils 工具链**（`services/utils/`）——TaskThread 线程管理（五态机+500ms 自醒+pthread_setname_np）和 SurfaceTools Surface 生命周期管理（单例+surfaceProducerMap_ 映射表+RegisterReleaseListener）

两者为 Filter Pipeline 和 CodecServer 提供底层运行时支撑：TaskThread 驱动 Filter 数据处理，SurfaceTools 管理解码输出 Surface 的生命周期，MediaCodec 则是编解码实例的核心引擎。

---

## 2. MediaCodec 核心引擎架构

### 2.1 CodecState 十二态机（L24-36, media_codec.h）

```cpp
// media_codec.h L24-36
enum class CodecState : int32_t {
    UNINITIALIZED,    // 初始空状态
    INITIALIZED,      // 已初始化（创建后）
    CONFIGURED,       // 已配置参数
    PREPARED,         // 已准备（Surface/Buffer 就绪）
    RUNNING,          // 运行中
    FLUSHED,          // 已刷新（队列清空）
    END_OF_STREAM,    // EOS 已标记

    // 过渡态（transient states）
    INITIALIZING,      // UNINITIALIZED → INITIALIZED
    STARTING,          // INITIALIZED → RUNNING
    STOPPING,          // RUNNING → INITIALIZED
    FLUSHING,          // RUNNING → FLUSHED
    RESUMING,          // FLUSHED → RUNNING
    RELEASING,         // {ANY EXCEPT RELEASED} → RELEASED

    ERROR,             // 错误态
};
```

- **核心稳态**：UNINITIALIZED → INITIALIZED → CONFIGURED → PREPARED → RUNNING → FLUSHED/END_OF_STREAM
- **过渡态**：INITIALIZING/STARTING/STOPPING/FLUSHING/RESUMING/RELEASING（异步操作中间态）
- **错误态**：ERROR（任何操作失败后进入）

### 2.2 Plugins::DataCallback 驱动机制（L90-93, media_codec.h）

```cpp
// media_codec.h L90
class MediaCodec : public std::enable_shared_from_this<MediaCodec>, public Plugins::DataCallback {
public:
    // ... 
    void OnInputBufferDone(const std::shared_ptr<AVBuffer> &inputBuffer) override;  // L164
    void OnOutputBufferDone(const std::shared_ptr<AVBuffer> &outputBuffer) override; // L166
```

- `MediaCodec` 继承 `Plugins::DataCallback`（Plugin 层回调接口）
- L236/L261: `codecPlugin_->SetDataCallback(this)` 将 MediaCodec 自身注册为 Plugin 的数据回调
- Plugin 产生的输出缓冲区通过 `OnOutputBufferDone` 路由回 MediaCodec

### 2.3 生命周期七步曲（media_codec.cpp L100-L466）

| 步骤 | 函数 | 状态转换 | 关键操作 |
|------|------|---------|---------|
| 1 Init | `Init()` L100-172 | UNINITIALIZED → INITIALIZING → INITIALIZED | 创建 codecPlugin_，SetDataCallback(this) L236 |
| 2 Configure | `Configure()` L232-238 | INITIALIZED → CONFIGURED | 设置 Meta 参数 |
| 3 Prepare | `Prepare()` L246-307 | CONFIGURED → PREPARED | 创建 AVBufferQueue 或 Surface |
| 4 Start | `Start()` L463-488 | PREPARED/FLUSHED → STARTING → RUNNING | 启动编码/解码 |
| 5 FeedInput | `QueueInputBuffer()` | RUNNING | 接收原始数据 |
| 6 DrainOutput | `GetOutputBuffer()` | RUNNING | 输出编码/解码结果 |
| 7 Stop | `Stop()` L315-338 | RUNNING → STOPPING → INITIALIZED | 停止并回收资源 |

### 2.4 Plugin 创建与 MIME 路由（media_codec.cpp L179-185）

```cpp
// media_codec.cpp L179-185
std::shared_ptr<Plugins::CodecPlugin> MediaCodec::CreatePlugin(const std::string &mime, Plugins::PluginType pluginType)
{
    auto plugin = Plugins::PluginManagerV2::Instance().CreatePluginByMime(pluginType, mime);
    return std::reinterpret_pointer_cast<Plugins::CodecPlugin>(plugin);
}
```

- L163: `PluginManagerV2::Instance().CreatePluginByName(name)` 按名称创建
- L181: `CreatePluginByMime(pluginType, mime)` 按 MIME 类型创建
- 支持 AUDIO_ENCODER/DECODER 和 VIDEO_ENCODER/DECODER 四类插件

---

## 3. Utils 工具链

### 3.1 TaskThread 线程管理（task_thread.cpp 175行）

```cpp
// task_thread.cpp L1-50（五态机）
enum class TaskThreadState : int32_t {
    STOPPED = 0,   // 停止态
    STARTED = 1,   // 运行态
    PAUSING = 2,   // 暂停中
    PAUSED = 3,    // 已暂停
    STOPPING = 4,  // 停止中
};
```

- **500ms 自醒机制**：WAIT_TIMEOUT_MS=500（500ms 检查一次任务队列）
- **pthread_setname_np**：线程命名，便于调试
- **任务调度**：std::function 任务队列，线程安全 mutex 保护

### 3.2 SurfaceTools Surface 生命周期管理（surface_tools.cpp 107行）

```cpp
// surface_tools.cpp（单例模式）
class SurfaceTools {
public:
    static SurfaceTools& GetInstance();
    // surfaceProducerMap_ — SurfaceProducer → Surface 对象映射表
    // RegisterReleaseListener — 注册 Surface 释放监听器
    // CleanCache — 清理过期 Surface 缓存
    // ReleaseSurface — 显式释放 Surface 资源
};
```

- **单例模式**：全局唯一 SurfaceTools 实例
- **surfaceProducerMap_**：管理 SurfaceProducer 与 Surface 对象的映射关系
- **RegisterReleaseListener**：Surface 生命周期结束回调
- **CleanCache**：防止 Surface 泄漏

---

## 4. 与已有记忆的关联

| 关联记忆 | 关系 |
|---------|------|
| S92(MediaCodec核心引擎) | S167 补充 CodecState 十二态机细节（L24-36）+ Plugins::DataCallback 实现（L90-166）+ 生命周期七步曲行号证据 |
| S14(FilterChain) | MediaCodec 是 VideoDecoderFilter/AudioDecoderFilter 内部封装的核心引擎；TaskThread 驱动 Filter 数据处理循环 |
| S41(DemuxerFilter) | DemuxerFilter 输出通过 MediaCodec 解码；MediaCodec 处理后输出给 VideoSink/AudioSink |
| S34(MuxerFilter) | MediaCodec 输出编码帧送 MuxerFilter 封装；MuxerFilter 配置 MediaCodec 编码参数 |
| S22(MediaSyncManager) | MediaCodec + VideoSink 共同受 MediaSyncManager 调度 PTS 同步 |
| S98(三路Sink) | VideoSink/AudioSink/SubtitleSink 消费 MediaCodec 输出的 AVBuffer |
| S152(TaskThread+SurfaceTools) | S167 是 S152 的行号级 evidence 补充（task_thread.cpp 175行 + surface_tools.cpp 107行原始证据） |
| S57(CodecServer状态机) | CodecServer 管理多个 MediaCodec 实例；MediaCodec CodecState 是 CodecServer 状态机的子状态 |
| S164(SA Codec IPC) | CodecClient 通过 IPC 调用远端 MediaCodec 实例的生命周期接口 |
| S163(DRM CENC) | CodecDrmDecrypt 在 MediaCodec HandleInputBufferInner 中触发解密 |

---

## 5. 文件清单

| 文件 | 行数 | 关键内容 |
|------|------|---------|
| `services/media_engine/modules/media_codec/media_codec.cpp` | 1266 | MediaCodec 引擎主体，CodecState 十二态机，生命周期七步曲，Plugin 创建与回调 |
| `services/media_engine/modules/media_codec/media_codec.h` | 235 | CodecState 枚举，CodecCallback/AudioBaseCodecCallback 接口，MediaCodec 类定义，Plugins::DataCallback 继承 |
| `services/utils/task_thread.cpp` | 175 | TaskThread 五态机，500ms 自醒机制，pthread_setname_np 线程命名 |
| `services/utils/surface_tools.cpp` | 107 | SurfaceTools 单例，surfaceProducerMap_ 映射表，Surface 生命周期管理 |
| `services/media_engine/filters/video_decoder_filter.cpp` | ~600 | VideoDecoderFilter 组合 MediaCodec 的 Filter 层实现 |
| `services/media_engine/filters/audio_decoder_filter.cpp` | ~500 | AudioDecoderFilter 组合 MediaCodec 的 Filter 层实现 |

---

## 6. 状态与后续

- **状态**：draft（草案）
- **待办**：提交 pending_approval 审批
- **生成时间**：2026-05-20T22:55 Asia/Shanghai
- **Builder**：builder-agent