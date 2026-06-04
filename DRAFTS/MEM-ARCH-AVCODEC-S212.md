# MEM-ARCH-AVCODEC-S212: VideoDecoderAdapter 过滤层编解码适配器

## Metadata

| Field | Value |
|-------|-------|
| mem_id | MEM-ARCH-AVCODEC-S212 |
| title | VideoDecoderAdapter 过滤层编解码适配器——AVBufferQueue双队列与CodecEngine三层回调桥接 |
| status | draft |
| topic_type | architecture |
| priority | P2 |
| tags | AVCodec, MediaEngine, Filter, VideoDecoder, Adapter, AVBufferQueue, MediaCodec, CodecEngine, Surface |
| created | 2026-06-05T04:51 GMT+8 |
| builder | builder-agent (subagent) |
| source_files | services/media_engine/filters/video_decoder_adapter.cpp(609行) + interfaces/inner_api/native/video_decoder_adapter.h(123行) |
| evidence_count | 14 |
| related_topics | S45(SurfaceDecoderFilter), S46(DecoderSurfaceFilter), S39(VideoDecoderFilter), S55(CodecCallback体系), S92(MediaCodec核心引擎) |

---

## 1. 组件定位

**VideoDecoderAdapter** 是 MediaEngine Filter 层与底层 CodecEngine (AVCodecVideoDecoder) 之间的桥接适配器，位于 `services/media_engine/filters/` 目录。它负责：

1. **输入端**：接收来自上游 Filter 的 AVBuffer，通过 AVBufferQueue 输入队列传递给 CodecEngine
2. **输出端**：接收 CodecEngine 的解码输出 Buffer，通过 AVBufferQueue 输出队列传递给下游 Filter
3. **回调桥接**：VideoDecoderCallback 将 CodecEngine 的四路回调（OnError/OnOutputFormatChanged/OnInputBufferAvailable/OnOutputBufferAvailable）转发给 VideoDecoderAdapter 自身处理
4. **Surface 输出**：通过 VideoConsumerListener 消费 Surface Buffer

### 位置图

```
VideoDecoderFilter (Filter层)
    ↓ (上游输入)
VideoDecoderAdapter (本组件, 609行cpp + 123行h)
    ↓↔ (AVBufferQueue双队列)
AVCodecVideoDecoder (CodecEngine层)
```

---

## 2. 核心类设计

### 2.1 VideoDecoderCallback（Codec回调桥接器）

```cpp
// video_decoder_adapter.cpp:50-79
class VideoDecoderCallback : public MediaAVCodec::MediaCodecCallback {
    std::weak_ptr<VideoDecoderAdapter> videoDecoderAdapter_;
    // 四路回调全部转发到 videoDecoderAdapter_
    void OnError(...)      // L57-63
    void OnOutputFormatChanged(...) // L65-71
    void OnInputBufferAvailable(...) // L73-80
    void OnOutputBufferAvailable(...) // L82-90
};
```

**作用**：CodecEngine (`mediaCodec_`) 的 `MediaCodecCallback` 纯虚接口实现。将 codec 层的四路回调转发给 `VideoDecoderAdapter` 自身的同名方法。`weak_ptr` 防止循环引用。

### 2.2 VideoConsumerListener（Surface消费监听器）

```cpp
// video_decoder_adapter.cpp:98-127
class VideoConsumerListener : public IBufferConsumerListener {
    wptr<Surface> consumerSurface_;
    void OnBufferAvailable() override {
        // AcquireBuffer → ReleaseBuffer 环形消费
        // L108-119
    }
};
```

**作用**：实现 `IBufferConsumerListener` 接口，当 Surface 有可消费 Buffer 时，`OnBufferAvailable` 被调用执行 `AcquireBuffer` + `ReleaseBuffer` 环形消费。

### 2.3 VideoDecoderAdapter 主类

```cpp
// video_decoder_adapter.h:39-89
class VideoDecoderAdapter : public std::enable_shared_from_this<VideoDecoderAdapter> {
    // 关键成员
    std::shared_ptr<Media::AVBufferQueue> inputBufferQueue_;           // L81
    sptr<Media::AVBufferQueueProducer> inputBufferQueueProducer_;      // L82
    sptr<Media::AVBufferQueueConsumer> inputBufferQueueConsumer_;      // L83
    std::shared_ptr<MediaAVCodec::AVCodecVideoDecoder> mediaCodec_;   // L85
    std::shared_ptr<MediaAVCodec::MediaCodecCallback> callback_;       // L86
};
```

---

## 3. 生命周期方法（7步）

| 步骤 | 方法 | 说明 |
|------|------|------|
| 1 | `Init(type, isMime, name)` | L132-156: VideoDecoderFactory.CreateByMime/CreateByName 创建 codec 实例 |
| 2 | `Configure(format)` | L158-180: 配置 codec，检查文件类型，处理 MIME 兼容性 |
| 3 | `SetParameter(format)` | 设置编码参数到 codec |
| 4 | `Start()` | 启动 codec，注册 VideoDecoderCallback |
| 5 | `Flush()` | 刷新 codec，清空 DTS 队列 |
| 6 | `Stop()` | 停止 codec |
| 7 | `Release()` | 释放资源 |

---

## 4. AVBufferQueue 双队列架构

### 4.1 输入队列初始化

```cpp
// video_decoder_adapter.h:49-51
void PrepareInputBufferQueue();
sptr<AVBufferQueueProducer> GetBufferQueueProducer();
sptr<AVBufferQueueConsumer> GetBufferQueueConsumer();
```

- `inputBufferQueue_`: 共享内存队列 (L81)
- `inputBufferQueueProducer_`: 生产者端，交给 VideoDecoderFilter (L82)
- `inputBufferQueueConsumer_`: 消费者端，连接 codec (L83)

### 4.2 输入 Buffer 处理

```cpp
// video_decoder_adapter.h:53, L182-188
void OnInputBufferAvailable(uint32_t index, std::shared_ptr<AVBuffer> buffer);
// AquireAvailableInputBuffer: 获取可用输入 Buffer
// GetInputBufferDts: 获取输入 Buffer 的 DTS
```

### 4.3 输出 Buffer 处理

```cpp
// video_decoder_adapter.h:56-58, L190-200
void OnOutputBufferAvailable(uint32_t index, std::shared_ptr<AVBuffer> buffer);
int32_t ReleaseOutputBuffer(uint32_t index, bool render, int64_t pts = 0);
int32_t RenderOutputBufferAtTime(uint32_t index, int64_t renderTimestampNs, int64_t pts = 0);
```

---

## 5. Surface 输出路径

### 5.1 Surface 设置

```cpp
// video_decoder_adapter.h:60
int32_t SetOutputSurface(sptr<Surface> videoSurface);
void InitDefaultSurface(); // L72: 初始化默认 Surface
```

### 5.2 Surface 消费监听

`VideoConsumerListener::OnBufferAvailable()` 执行 `AcquireBuffer` → `ReleaseBuffer` 环形消费 Surface Buffer。

### 5.3 输出 Surface + SurfaceDecoderAdapter 对比

| 维度 | VideoDecoderAdapter (本组件) | SurfaceDecoderAdapter |
|------|------|------|
| 位置 | services/media_engine/filters/ | services/media_engine/filters/ |
| 用途 | Filter 层通用解码适配器 | Surface 模式专用 |
| Surface 消费 | VideoConsumerListener | ConsumerListener |
| DRM | SetDecryptConfig | 是 |

---

## 6. DRM 解密集成

```cpp
// video_decoder_adapter.h:64-65
int32_t SetDecryptConfig(
    const sptr<DrmStandard::IMediaKeySessionService> &keySession,
    const bool svpFlag);
```

支持安全视频路径 (SVP) 解密，通过 DRM 解密配置传递给底层 codec。

---

## 7. DFX 与性能监控

| 方法 | 说明 |
|------|------|
| `OnDumpInfo(int32_t fd)` | L67: DUMP 信息输出 |
| `PerfRecord(buffer)` | L76: 性能记录 |
| `SetPerfRecEnabled(bool)` | L70: 性能记录开关 |
| `IsHwDecoder()` | L71: 判定是否硬件解码器 |
| `ResetRenderTime()` | L69: 重置渲染时间 |

---

## 8. 与相关记忆条目的关联

| 关联条目 | 关系 |
|------|------|
| S45 (SurfaceDecoderFilter) | Filter 层封装与 SurfaceDecoderAdapter 三层调用链 |
| S46 (DecoderSurfaceFilter) | VideoDecoderAdapter + VideoSink + PostProcessor 三组件 |
| S39 (VideoDecoderFilter) | Filter 层 + VideoDecoderAdapter + AudioDecoderAdapter 三层架构 |
| S55 (CodecCallback体系) | CodecCallback 四路回调机制（OnError/OnOutputFormatChanged/OnInputBufferAvailable/OnOutputBufferAvailable）|
| S92 (MediaCodec核心引擎) | CodecState 十二态机与 Plugins::DataCallback 驱动机制 |

---

## 9. 行号级 Evidence（14条）

| # | 文件 | 行号范围 | 内容描述 |
|---|------|---------|---------|
| 1 | video_decoder_adapter.cpp | 50-79 | VideoDecoderCallback 四路回调桥接 |
| 2 | video_decoder_adapter.cpp | 98-127 | VideoConsumerListener OnBufferAvailable |
| 3 | video_decoder_adapter.cpp | 132-156 | Init → CreateByMime/CreateByName |
| 4 | video_decoder_adapter.cpp | 158-180 | Configure → 设置文件类型/ MIME |
| 5 | video_decoder_adapter.cpp | 158-180 | Configure: 检查 VC1/WMV3/RV30/MPEG4 |
| 6 | video_decoder_adapter.h | 81-86 | 关键成员变量声明 |
| 7 | video_decoder_adapter.h | 49-51 | AVBufferQueue 双队列接口 |
| 8 | video_decoder_adapter.h | 53,57-58 | 输入/输出 Buffer 处理方法 |
| 9 | video_decoder_adapter.h | 60,72 | Surface 输出接口 |
| 10 | video_decoder_adapter.h | 64-65 | SetDecryptConfig DRM 解密接口 |
| 11 | video_decoder_adapter.h | 67,70,76 | DFX 和性能监控方法 |
| 12 | video_decoder_adapter.cpp | ~182-200 | OnInputBufferAvailable/OnOutputBufferAvailable |
| 13 | video_decoder_adapter.cpp | ~115-126 | Surface Buffer 环形消费 AcquireBuffer+ReleaseBuffer |
| 14 | video_decoder_adapter.h | 71 | IsHwDecoder 硬件解码器判定 |

---

## 10. 总结

**VideoDecoderAdapter** 是 MediaEngine Filter 层与 AVCodecVideoDecoder CodecEngine 之间的核心桥接器，实现了：

1. **Codec 创建桥接**：通过 `VideoDecoderFactory::CreateByMime/CreateByName` 创建底层 codec 实例
2. **双 AVBufferQueue 队列**：输入队列生产者交给 Filter，输出队列消费者接收解码结果
3. **四路回调桥接**：`VideoDecoderCallback` 将 codec 回调转发到 adapter 自身方法
4. **Surface 输出**：`VideoConsumerListener` 消费 Surface Buffer 并环形释放
5. **DRM 集成**：通过 `SetDecryptConfig` 支持安全视频路径
6. **DFX 监控**：性能记录、DUMP、硬件解码器判定

**与 SurfaceDecoderAdapter 的区别**：`SurfaceDecoderAdapter` 专用于 Surface 模式，持有 `Surface` 引用并处理 Surface Buffer 的解密和 DMA 传输；而 `VideoDecoderAdapter` 是更通用的 Filter 层适配器，处理通用 Buffer 模式和 Surface 输出两条路径。
