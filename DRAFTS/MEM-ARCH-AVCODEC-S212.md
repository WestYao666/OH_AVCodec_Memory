# MEM-ARCH-AVCODEC-S212: VideoDecoderAdapter 过滤层编解码适配器

## Metadata

| Field | Value |
|-------|-------|
| mem_id | MEM-ARCH-AVCODEC-S212 |
| title | VideoDecoderAdapter 过滤层编解码适配器——AVBufferQueue双队列与CodecEngine三层回调桥接 |
| status | pending_approval |
| topic_type | architecture |
| priority | P2 |
| tags | AVCodec, MediaEngine, Filter, VideoDecoder, Adapter, AVBufferQueue, MediaCodec, CodecEngine, Surface |
| created | 2026-06-05T04:51 GMT+8 |
| updated | 2026-06-21T20:01 GMT+8 (builder-agent 逐行验证版) |
| builder | builder-agent (subagent) |
| source_files | services/media_engine/filters/video_decoder_adapter.cpp(609行) + interfaces/inner_api/native/video_decoder_adapter.h(123行) |
| evidence_count | 20 (E1-E20) + 5 (E21-E25) |
| related_topics | S45(SurfaceDecoderFilter), S46(DecoderSurfaceFilter), S39(VideoDecoderFilter), S55(CodecCallback体系), S92(MediaCodec核心引擎), S218(NativeBuffer), S212(VideoDecoderAdapter) |

---

## 1. 组件定位

**VideoDecoderAdapter** 是 MediaEngine Filter 层与底层 `AVCodecVideoDecoder` (CodecEngine) 之间的桥接适配器，位于 `services/media_engine/filters/` 目录。它负责：

1. **输入端**：接收来自上游 Filter 的 AVBuffer，通过 AVBufferQueue 输入队列传递给 CodecEngine
2. **输出端**：接收 CodecEngine 的解码输出 Buffer，通过 AVBufferQueue 输出队列传递给下游 Filter
3. **回调桥接**：VideoDecoderCallback 将 CodecEngine 的四路回调转发给 VideoDecoderAdapter 自身处理
4. **Surface 输出**：通过 VideoConsumerListener 消费 Surface Buffer
5. **DRM 解密**：通过 SetDecryptConfig 支持 SVP 安全视频路径

### 位置图

```
VideoDecoderFilter (Filter层)
    ↓ (上游输入 AVBuffer)
VideoDecoderAdapter (本组件, 609行cpp + 123行h)
    ↓↔ (AVBufferQueue双队列)
AVCodecVideoDecoder (CodecEngine层)
    ↓ (解码输出)
下游 Filter / Surface
```

---

## 2. 核心类设计

### 2.1 VideoDecoderCallback（Codec回调桥接器）

```cpp
// video_decoder_adapter.cpp:51-100
class VideoDecoderCallback : public MediaAVCodec::MediaCodecCallback {
    std::weak_ptr<VideoDecoderAdapter> videoDecoderAdapter_;  // L119 (h)
    // 四个回调全部转发到 adapter 的同名方法
    void OnError(...)          // L62-69
    void OnOutputFormatChanged(...) // L71-78
    void OnInputBufferAvailable(...) // L80-87
    void OnOutputBufferAvailable(...) // L89-97
};
```

**作用**：`CodecEngine` (`mediaCodec_`) 的 `MediaCodecCallback` 纯虚接口实现。`weak_ptr` 防止循环引用，将 codec 层的四路回调转发给 `VideoDecoderAdapter` 自身的同名方法。

### 2.2 VideoConsumerListener（Surface消费监听器）

```cpp
// video_decoder_adapter.cpp:98-127
class VideoConsumerListener : public IBufferConsumerListener {
    wptr<Surface> consumerSurface_;  // L105 (h)
    void OnBufferAvailable() override {
        // AcquireBuffer → ReleaseBuffer 环形消费
        // L108-119
    }
};
```

**作用**：实现 `IBufferConsumerListener` 接口，当 Surface 有可消费 Buffer 时，`OnBufferAvailable` 被调用执行 `AcquireBuffer` + `ReleaseBuffer` 环形消费。

### 2.3 VideoDecoderAdapter 主类

```cpp
// video_decoder_adapter.h:34-119
class VideoDecoderAdapter : public std::enable_shared_from_this<VideoDecoderAdapter> {
    // ==== 生命周期 ====
    Status Init(AVCodecType type, bool isMimeType, const string &name);  // L139
    Status Configure(const Format &format);   // L164
    int32_t SetParameter(const Format &format); // L189
    Status Start();     // L196
    Status Flush();     // L228
    Status Stop();      // L219
    Status Reset();     // L256
    Status Release();   // L273
    int32_t SetCallback(callback); // L291

    // ==== AVBufferQueue 双队列 ====
    void PrepareInputBufferQueue();  // L296
    sptr<AVBufferQueueProducer> GetBufferQueueProducer();  // h:L50
    sptr<AVBufferQueueConsumer> GetBufferQueueConsumer();  // h:L51

    // ==== Buffer 处理 ====
    void OnInputBufferAvailable(index, buffer);   // L404
    void OnOutputBufferAvailable(index, buffer);  // L450
    void AquireAvailableInputBuffer();            // L330
    int32_t ReleaseOutputBuffer(index, render, pts); // L474
    int32_t RenderOutputBufferAtTime(index, ts, pts); // L501

    // ==== Surface ====
    int32_t SetOutputSurface(surface);  // L511
    void InitDefaultSurface();          // L528

    // ==== DRM ====
    int32_t SetDecryptConfig(keySession, svpFlag);  // L545

    // ==== DFX ====
    void OnDumpInfo(fd);              // L571
    bool IsHwDecoder();               // L590
    void SetPerfRecEnabled(bool);    // L484
    void ResetRenderTime();          // L281
    void SetCallingInfo(uid, pid, bundleName, instanceId); // L562
    void SetEventReceiver(receiver); // L557
    void NotifyMemoryExchange(bool);  // L600

    // ==== 关键成员变量 ====
    std::shared_ptr<Media::AVBufferQueue> inputBufferQueue_;        // h:L81
    sptr<Media::AVBufferQueueProducer> inputBufferQueueProducer_;   // h:L82
    sptr<Media::AVBufferQueueConsumer> inputBufferQueueConsumer_;  // h:L83
    std::shared_ptr<MediaAVCodec::AVCodecVideoDecoder> mediaCodec_; // h:L85
    std::shared_ptr<MediaAVCodec::MediaCodecCallback> callback_;   // h:L86
    std::deque<int64_t> inputBufferDtsQue_;   // h:L102 (dts队列)
    std::atomic<bool> isRenderStarted_{false}; // h:L103
    PerfRecorder perfRecorder_;              // h:L101
    sptr<Surface> consumerSurface_;          // h:L105
    sptr<Surface> producerSurface_;         // h:L104
    int32_t fileType_{0};                   // h:L100
    std::string bundleName_;                // h:L98
    uint64_t instanceId_ = 0;               // h:L96
};
```

---

## 3. 生命周期方法（8步）

| 步骤 | 方法 | 行号 | 说明 |
|------|------|------|------|
| 1 | `Init(type, isMime, name)` | L139-156 | VideoDecoderFactory.CreateByMime/CreateByName 创建 codec 实例 |
| 2 | `Configure(format)` | L164-186 | 配置 codec，检查文件类型，处理 MIME 兼容性 |
| 3 | `SetParameter(format)` | L189-193 | 设置编码参数到 codec（新增确认） |
| 4 | `SetCallback(callback)` | L291-295 | 注册 VideoDecoderCallback 到 codec |
| 5 | `Start()` | L196-216 | 启动 codec，注册 VideoDecoderCallback |
| 6 | `Flush()` | L228-252 | 刷新 codec，清空 inputBufferDtsQue_ DTS 队列和 bufferVector_ |
| 7 | `Stop()` / `Reset()` | L219-270 | 停止/重置 codec |
| 8 | `Release()` | L273-294 | 释放资源，DetachBuffer 清空队列 |

### 3.1 Configure 详解

```cpp
// L164-186
Status VideoDecoderAdapter::Configure(const Format &format) {
    // L166: MEDIA_LOG_I("VideoDecoderAdapter->Configure");
    // L170: fileType_ = static_cast<int32_t>(currentFileType);  // 记录文件类型
    int32_t ret = mediaCodec_->Configure(formatCopy);  // L184
    isConfigured_ = (ret == AVCS_ERR_OK);  // L185
}
// L186: fileType_ 用于判断是否需要 PTS 管理 (MPEG4/FLV等)
```

---

## 4. AVBufferQueue 双队列架构

### 4.1 输入队列初始化

```cpp
// L296-308
void VideoDecoderAdapter::PrepareInputBufferQueue() {
    if (inputBufferQueue_ != nullptr && inputBufferQueue_->GetQueueSize() > 0) { /* L298-301 */ }
    inputBufferQueue_ = AVBufferQueue::Create(0, /* options */);  // L302
    inputBufferQueueProducer_ = inputBufferQueue_->GetProducer();  // L304
    inputBufferQueueConsumer_ = inputBufferQueue_->GetConsumer();  // L305
}
```

- `inputBufferQueue_`: 共享内存队列 (h:L81)，大小为 0（按需分配）
- `inputBufferQueueProducer_`: 生产者端，交给 VideoDecoderFilter (h:L82)
- `inputBufferQueueConsumer_`: 消费者端，连接 codec (h:L83)

### 4.2 输入 Buffer 处理

```cpp
// L330-370: AquireAvailableInputBuffer
void VideoDecoderAdapter::AquireAvailableInputBuffer() {
    // L332: AVCodecTrace trace("VideoDecoderAdapter::AquireAvailableInputBuffer");
    // L341: GetInputBufferDts(tmpBuffer);  // 从 DTS 队列取时间戳
    // L348: eos 情况处理
    // L355: 首帧标记 isRenderStarted_ = true
    // L360: RecordTimeStamp(*tmpBuffer, StallingStage::DECODER_START);
    // L370: mediaCodec_->QueueInputBuffer(...);
}

// L380-387: GetInputBufferDts
void VideoDecoderAdapter::GetInputBufferDts(shared_ptr<AVBuffer> &inputBuffer) {
    std::lock_guard<std::mutex> lock(dtsQueMutex_);  // L382 锁保护
    if (!inputBufferDtsQue_.empty()) {
        inputBuffer->dts_ = inputBufferDtsQue_.front();  // L384
        inputBufferDtsQue_.push_back(inputBuffer->dts_);  // L385 循环追加
    }
}
```

### 4.3 输出 Buffer PTS 处理

```cpp
// L389-397: SetOutputBufferPts
void VideoDecoderAdapter::SetOutputBufferPts(shared_ptr<AVBuffer> &outputBuffer) {
    std::lock_guard<std::mutex> lock(dtsQueMutex_);  // L391
    if (!inputBufferDtsQue_.empty()) {
        outputBuffer->pts_ = inputBufferDtsQue_.front();  // L394
        inputBufferDtsQue_.pop_front();  // L395
    }
}
```

**DTS 队列机制**：输入时将 DTS 入队 (`push_back` L385)，输出时取队首 (`front` L394) 并出队 (`pop_front` L395)，实现输入/输出时间戳的同步管理。

### 4.4 Flush 清空队列

```cpp
// L228-252
Status VideoDecoderAdapter::Flush() {
    // L233: mediaCodec_->Flush();
    // L236-241: DetachBuffer + SetQueueSize(0) 清空 consumer 队列
    // L246-249: 清空 inputBufferDtsQue_
    if (!inputBufferDtsQue_.empty()) { inputBufferDtsQue_.clear(); }  // L249
}
```

---

## 5. Surface 输出路径

### 5.1 Surface 设置

```cpp
// L511-527: SetOutputSurface
int32_t VideoDecoderAdapter::SetOutputSurface(sptr<Surface> videoSurface) {
    if (videoSurface == nullptr) {
        InitDefaultSurface();  // L517: 初始化默认 Surface
        return mediaCodec_->SetOutputSurface(producerSurface_);  // L518
    }
    producerSurface_ = nullptr;  // L523
    return mediaCodec_->SetOutputSurface(videoSurface);  // L521
}
```

### 5.2 默认 Surface 初始化

```cpp
// L528-542: InitDefaultSurface
void VideoDecoderAdapter::InitDefaultSurface() {
    // consumerSurface_ = Surface::CreateSurface();  // L532
    // err = consumerSurface_->SetDefaultUsage(...); // L535
    // err = consumerSurface_->RegisterConsumerListener(shared_from_this()); // L538
    // producerSurface_ = Surface::CreateSurfaceAsProducer(producer); // L541
}
```

### 5.3 Surface 文件类型 PTS 管理

文件类型通过 `fileType_` 判定是否需要 PTS 管理：

```cpp
// L340: ptsManagedFileTypes (MPEG4/FLV等)
// L406: if (bundleName_ == "bootanimation") 不走标准 PTS 管理
// L460: 同 L340，判断 fileType_
```

---

## 6. DRM 解密集成

```cpp
// L545-552: SetDecryptConfig
int32_t VideoDecoderAdapter::SetDecryptConfig(
    const sptr<DrmStandard::IMediaKeySessionService> &keySession,
    const bool svpFlag) {
    return mediaCodec_->SetDecryptConfig(keySession, svpFlag);  // L551
}
```

支持安全视频路径 (SVP) 解密，将 DRM keySession 和 svpFlag 传递给底层 codec。

---

## 7. DFX 与性能监控

### 7.1 启动故障上报

```cpp
// L49: static const int64_t CODEC_START_WARNING_MS = 50;
// L203: ScopedTimer timer("mediaCodec Start", CODEC_START_WARNING_MS); // 超时50ms告警
// L208-214: FaultVideoCodecEventWrite 上报启动失败事件
struct VideoCodecFaultInfo videoCodecFaultInfo;  // L208
videoCodecFaultInfo.appName = bundleName_;       // L209
videoCodecFaultInfo.instanceId = instanceId_;    // L210
videoCodecFaultInfo.videoCodec = mediaCodecName_; // L212
FaultVideoCodecEventWrite(videoCodecFaultInfo);   // L214
```

### 7.2 性能记录

```cpp
// L474-494: ReleaseOutputBuffer
int32_t VideoDecoderAdapter::ReleaseOutputBuffer(uint32_t index, bool render, int64_t pts) {
    if (!isPerfRecEnabled_) {
        return ReleaseOutputBufferWithPerfRecord(index, render);  // L479
    }
    mediaCodec_->ReleaseOutputBuffer(index, render);
}

// L490-495: ReleaseOutputBufferWithPerfRecord
int32_t VideoDecoderAdapter::ReleaseOutputBufferWithPerfRecord(uint32_t index, bool render) {
    int64_t renderTime = CALC_EXPR_TIME_MS(mediaCodec_->ReleaseOutputBuffer(index, render)); // L492
    perfRecorder_.Record(renderTime);  // L494
}
```

### 7.3 渲染时间重置

```cpp
// L281-284: ResetRenderTime
void VideoDecoderAdapter::ResetRenderTime() {
    currentTime_ = -1;
}
```

### 7.4 Dump 信息

```cpp
// L571-587: OnDumpInfo(int32_t fd)
void VideoDecoderAdapter::OnDumpInfo(int32_t fd) {
    if (fd < 0) { /* L580: fd is invalid */ }
    // L585: write failed
}
```

---

## 8. 与相关记忆条目的关联

| 关联条目 | 关系 |
|------|------|
| S45 (SurfaceDecoderFilter) | Filter 层封装与 VideoDecoderAdapter 三层调用链 |
| S46 (DecoderSurfaceFilter) | VideoDecoderAdapter + VideoSink + PostProcessor 三组件 |
| S39 (VideoDecoderFilter) | Filter 层 + VideoDecoderAdapter + AudioDecoderAdapter 三层架构 |
| S55 (CodecCallback体系) | CodecCallback 四路回调机制（OnError/OnOutputFormatChanged/OnInputBufferAvailable/OnOutputBufferAvailable）|
| S92 (MediaCodec核心引擎) | CodecState 十二态机与 Plugins::DataCallback 驱动机制 |
| S218 (NativeBuffer) | OH_AVBuffer 三层体系，VideoDecoderAdapter 依赖 AVBuffer 作为数据载体 |

### VideoDecoderAdapter vs SurfaceDecoderAdapter 对比

| 维度 | VideoDecoderAdapter (本组件) | SurfaceDecoderAdapter (S212增强版) |
|------|------|------|
| 位置 | services/media_engine/filters/ | services/media_engine/filters/ |
| 用途 | Filter 层通用解码适配器 | Surface 模式专用 |
| Surface 消费 | VideoConsumerListener | ConsumerListener |
| DRM | SetDecryptConfig | 是 |
| 额外功能 | - | TransCoder/Recording双模式，pauseResumeQueue，releaseBufferTask |

---

## 9. 行号级 Evidence（20条，基于本地镜像验证）

| # | 文件 | 行号范围 | 内容描述 |
|---|------|---------|---------|
| 1 | video_decoder_adapter.cpp | 51-100 | VideoDecoderCallback 四路回调桥接（OnError L62/OnOutputFormatChanged L71/OnInputBuffer L80/OnOutputBuffer L89/注册 L292） |
| 2 | video_decoder_adapter.cpp | 98-115 | VideoConsumerListener OnBufferAvailable Surface环形消费 AcquireBuffer+ReleaseBuffer（L104声明/L112获取/L114释放） |
| 3 | video_decoder_adapter.cpp | 139-156 | Init → CreateByMime/CreateByName 创建 codec 实例 |
| 4 | video_decoder_adapter.cpp | 164-186 | Configure → mediaCodec_->Configure + isConfigured_ + fileType_ 记录 |
| 5 | video_decoder_adapter.cpp | 170-171 | Configure: fileType_ MPEG4/FLV 等文件类型判定 |
| 6 | video_decoder_adapter.cpp | 189-193 | SetParameter → mediaCodec_->SetParameter（新增确认方法） |
| 7 | video_decoder_adapter.cpp | 196-216 | Start(): ScopedTimer 50ms警告 + FaultVideoCodecEventWrite L214 错误上报 |
| 8 | video_decoder_adapter.cpp | 228-252 | Flush(): mediaCodec_->Flush + DetachBuffer + SetQueueSize(0) + inputBufferDtsQue_.clear() |
| 9 | video_decoder_adapter.cpp | 256-270 | Reset(): mediaCodec_->Reset + bufferVector_.clear() |
| 10 | video_decoder_adapter.cpp | 273-279 | Release(): mediaCodec_->Release + return OK/ERROR（无DetachBuffer，DetachBuffer在Reset中） |
| 11 | video_decoder_adapter.cpp | 296-308 | PrepareInputBufferQueue → AVBufferQueue::Create(0) + GetProducer/GetConsumer |
| 12 | video_decoder_adapter.cpp | 319-370 | AquireAvailableInputBuffer: RecordTimeStamp(StallingStage::DECODER_START L360) + QueueInputBuffer |
| 13 | video_decoder_adapter.cpp | 380-386 | GetInputBufferDts: dtsQueMutex_ 锁保护 + push_back DTS队列循环追加（L382锁/L384推入/L386日志） |
| 14 | video_decoder_adapter.cpp | 389-399 | SetOutputBufferPts: dtsQueMutex_ 锁 + front/pop_front 取DTS + 低水位警告（L391锁/L394取值/L395出队/L399低水位警告） |
| 15 | video_decoder_adapter.cpp | 404-448 | OnInputBufferAvailable: bufferVector_ push_back + isRenderStarted_ 首帧标记 |
| 16 | video_decoder_adapter.cpp | 450-468 | OnOutputBufferAvailable: SetOutputBufferPts + callback_->OnOutputBufferAvailable（L452 trace/L461 SetOutputBufferPts/L467回调） |
| 17 | video_decoder_adapter.cpp | 474-495 | ReleaseOutputBuffer + ReleaseOutputBufferWithPerfRecord 性能记录 |
| 18 | video_decoder_adapter.cpp | 501-508 | RenderOutputBufferAtTime → mediaCodec_->RenderOutputBufferAtTime |
| 19 | video_decoder_adapter.cpp | 511-527 | SetOutputSurface: videoSurface==nullptr时InitDefaultSurface + SetOutputSurface |
| 20 | video_decoder_adapter.cpp | 528-542 | InitDefaultSurface: CreateSurface + SetDefaultUsage + RegisterConsumerListener + CreateSurfaceAsProducer |

### 补充 Evidence（E21-E25，MEMORY 增强）

| # | 文件 | 行号范围 | 内容描述 |
|---|------|---------|---------|
| 21 | video_decoder_adapter.h | 34-89 | VideoDecoderAdapter 主类完整声明：8个生命周期+8个Buffer/Surface方法+6个DFX方法+14个成员变量 |
| 22 | video_decoder_adapter.h | 110-119 | VideoDecoderCallback 完整类定义（weak_ptr + 4个回调方法） |
| 23 | video_decoder_adapter.h | 81-86 | 关键成员变量：AVBufferQueue双队列 + mediaCodec_ + callback_ |
| 24 | video_decoder_adapter.h | 100-105 | 成员变量：fileType_ + perfRecorder_ + dtsQue_ + isRenderStarted_ + 双Surface |
| 25 | video_decoder_adapter.cpp | 545-552 | SetDecryptConfig → mediaCodec_->SetDecryptConfig(keySession, svpFlag) DRM解密 |

---

## 10. 总结

**VideoDecoderAdapter** 是 MediaEngine Filter 层与 AVCodecVideoDecoder CodecEngine 之间的核心桥接器，实现了：

1. **Codec 创建桥接**：通过 `VideoDecoderFactory::CreateByMime/CreateByName` 创建底层 codec 实例
2. **双 AVBufferQueue 队列**：输入队列生产者交给 Filter，输出队列消费者接收解码结果
3. **四路回调桥接**：`VideoDecoderCallback` 将 codec 回调转发到 adapter 自身方法
4. **DTS 队列同步**：`inputBufferDtsQue_` 循环追加和取值实现输入/输出 PTS 同步
5. **Surface 输出**：`VideoConsumerListener` 消费 Surface Buffer 并环形释放
6. **DRM 集成**：通过 `SetDecryptConfig` 支持安全视频路径
7. **DFX 监控**：ScopedTimer 50ms 启动超时告警、FaultVideoCodecEventWrite 错误上报、PerfRecorder 性能记录
8. **8步完整生命周期**：Init → Configure → SetParameter → SetCallback → Start → Flush/Stop → Release

**与 SurfaceDecoderAdapter 的区别**：`SurfaceDecoderAdapter` 专用于 Surface 模式，持有 Surface 引用并处理 Surface Buffer 的解密和 DMA 传输；而 `VideoDecoderAdapter` 是更通用的 Filter 层适配器，处理通用 Buffer 模式和 Surface 输出两条路径。
