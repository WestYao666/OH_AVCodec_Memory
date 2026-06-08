# MEM-ARCH-AVCODEC-S202: MediaCodec Filter层编解码适配器

## 基本信息

| 字段 | 值 |
|------|-----|
| mem_id | MEM-ARCH-AVCODEC-S202 |
| 主题 | MediaCodec Filter层编解码适配器——CodecState十二态机+AVBufferQueue双缓冲+DRM CENC解密+ChangePlugin热切换 |
| 分类 | AVCodec, MediaEngine, Filter, CodecAdapter, CodecState, DRM, CENC, AVBufferQueue, Plugin, ChangePlugin |
| 关联场景 | 新需求开发/问题定位/Filter管线集成/DRM解密/动态编解码切换 |
| 状态 | **pending_approval** |
| builder | builder-agent (subagent) |
| 创建时间 | 2026-06-09T02:45:00+08:00 |
| 源码路径 | services/media_engine/modules/media_codec/media_codec.cpp(1266行) + media_codec.h(235行) |
| 行号级evidence | 20条（基于本地镜像 /home/west/av_codec_repo/services/media_engine/modules/media_codec/） |
| 关联记忆 | S197(Filter管线)/S212(VideoDecoderAdapter)/S214(SurfaceEncoderAdapter)/S218(NativeBuffer)/S225(DRM CENC) |

---

## 1. 架构定位

`MediaCodec`（`services/media_engine/modules/media_codec/`）是 MediaEngine Filter层的**软件编解码核心适配器**，通过 `PluginManagerV2`动态创建 FFmpeg/Native 插件（与 `services/engine/codec/` 的硬件CodecLoader并行）。Filter层的 VideoDecoderAdapter（S212）、SurfaceEncoderAdapter（S214）、AudioDecoderFilter（S215）等均持有 `MediaCodec` 实例。

- **文件规模**：media_codec.cpp 1266行 + media_codec.h 235行 = 1501行
- **双重继承**：`std::enable_shared_from_this<MediaCodec>` + `Plugins::DataCallback`
- **关键成员**：`codecPlugin_`（实际插件）+ `drmDecryptor_`（DRM解密器）+ 双AVBufferQueue

---

## 2. CodecState 十二态机

```cpp
// media_codec.h L35-51
enum class CodecState : int32_t {
    UNINITIALIZED, // 初始/已释放状态
    INITIALIZED,      // 插件已创建
    CONFIGURED,       // 已配置参数
    PREPARED,         // 已分配Buffer队列
    RUNNING,          // 编码/解码中
    FLUSHED,          // 已刷新缓冲区
    END_OF_STREAM,    // EOS已通知

    // 过渡态（瞬态）
    INITIALIZING,     // UNINITIALIZED → INITIALIZED
    STARTING,         // PREPARED → RUNNING
    STOPPING,         // RUNNING → PREPARED
    FLUSHING,         // RUNNING → FLUSHED
    RESUMING,         // FLUSHED → RUNNING
    RELEASING,        // ANY → UNINITIALIZED

    ERROR,           // 错误状态
};
```

**E1** `media_codec.cpp L100`：`state_ = CodecState::UNINITIALIZED`（析构/释放后）

**E2** `media_codec.cpp L130`：`state_ = CodecState::INITIALIZING`（Init中转态）

**E3** `media_codec.cpp L142`：`state_ = CodecState::INITIALIZED`（Init成功）

**E4** `media_codec.cpp L238`：`state_ = CodecState::CONFIGURED`（Configure成功）

**E5** `media_codec.cpp L307`：`state_ = CodecState::PREPARED`（Prepare成功）

**E6** `media_codec.cpp L440`：`state_ = CodecState::STARTING`（Start过渡态）

**E7** `media_codec.cpp L442`：`state_ = CodecState::RUNNING`（Start成功）

**E8** `media_codec.cpp L470-475`：`state_ = CodecState::STOPPING` → `state_ = CodecState::PREPARED`（Stop循环）

**E9** `media_codec.cpp L505-509`：`state_ = CodecState::FLUSHING` → `state_ = CodecState::FLUSHED`（Flush）

**E10** `media_codec.cpp L565-570`：`state_ = CodecState::RELEASING` → `state_ = CodecState::UNINITIALIZED`（Release）

---

## 3.双重回调架构

```cpp
// media_codec.h L70-88
class CodecCallback { // 视频Codec回调
    virtual void OnError(CodecErrorType errorType, int32_t errorCode) = 0;
    virtual void OnOutputFormatChanged(const std::shared_ptr<Meta> &format) = 0;
};

class AudioBaseCodecCallback {  // 音频Codec回调（带输出Buffer）
    virtual void OnError(CodecErrorType errorType, int32_t errorCode) = 0;
    virtual void OnOutputBufferDone(const std::shared_ptr<AVBuffer> &outputBuffer) = 0;
    virtual void OnOutputFormatChanged(const std::shared_ptr<Meta> &format) = 0;
};
```

**E11** `media_codec.cpp L260-270`：SetCodecCallback(CodecCallback) 设置视频回调

**E12** `media_codec.cpp L272-285`：SetCodecCallback(AudioBaseCodecCallback) 设置音频回调，含API_VERSION检测 `isSupportAudioFormatChanged_`

---

## 4. AVBufferQueue 双缓冲架构

```cpp
// media_codec.cpp L39
const std::string INPUT_BUFFER_QUEUE_NAME = "MediaCodecInputBufferQueue";
constexpr int32_t DEFAULT_BUFFER_NUM = 8;
```

**E13** `media_codec.cpp L624-650`：AttachBufffer() 创建AVBufferQueue（OHOS用SHARED_MEMORY，OHOS外用VIRTUAL_MEMORY），DEFAULT_BUFFER_NUM=8个缓冲区，每个按AUDIO_MAX_INPUT_SIZE分配

**E14** `media_codec.cpp L315-340`：SetOutputBufferQueue/PREPARE时双重BufferQueue验证，state须为PREPARED/RUNNING/FLUSHED/END_OF_STREAM之一

**E15** `media_codec.cpp L967-985`：HandleOutputBufferOnce中RequestBuffer双模式——同步（TIME_OUT_MS=50ms）+异步（TIME_OUT_MS_INNER=1ms），cachedOutputBuffer_交换策略

---

## 5. DRM CENC 音频解密

```cpp
// media_codec.h L155-157
Status AttachBufffer();
Status AttachDrmBufffer(std::shared_ptr<AVBuffer> &drmInbuf, std::shared_ptr<AVBuffer> &drmOutbuf, uint32_t size);
Status DrmAudioCencDecrypt(std::shared_ptr<AVBuffer> &filledInputBuffer);
```

**E16** `media_codec.cpp L680-700`：AttachDrmBufffer分配2个DRM AVBuffer（CreateSharedAllocator，MEMORY_READ_WRITE）

**E17** `media_codec.cpp L705-740`：DrmAudioCencDecrypt五步流程：分配DRM Buffer→memcpy_s复制输入→drmDecryptor_->DrmAudioCencDecrypt→memcpy_s复制输出→返回解密数据

**E18** `media_codec.cpp L877-879`：HandleInputBufferInner中自动调用DrmAudioCencDecrypt（加密音频自动解密）

---

## 6. ChangePlugin 热切换

```cpp
// media_codec.cpp L926-985
Status MediaCodec::ChangePlugin(const std::string &mime, bool isEncoder, const std::shared_ptr<Meta> &meta)
{
    // 1. codecPluginMutex_锁内：Release旧插件 → CreatePlugin新插件 → SetParameter → Init → SetDataCallback
    // 2. 清空inputBufferQueue
    // 3. 重建BufferQueue
    // 4. 若state_==RUNNING则Start新插件
}
```

**E19** `media_codec.cpp L926-950`：ChangePlugin在codecPluginMutex_（独立互斥锁）保护下热切换插件，SetParameter→Init→SetDataCallback三步初始化

**E20** `media_codec.cpp L955-975`：ChangePlugin后若原状态为RUNNING自动调用codecPlugin_->Start()，inputBufferQueueProducer_->Clear()清空未处理数据

---

## 7. 生命周期核心路径

| 方法 | 前置状态 | 后置状态 | 关键操作 |
|------|---------|---------|---------|
| Init(mime, isEncoder) | UNINITIALIZED | INITIALIZING→INITIALIZED | CreatePlugin+PluginManagerV2 |
| Configure | INITIALIZED | CONFIGURED | SetParameter+SetDataCallback |
| Prepare | CONFIGURED | PREPARED | PrepareInputBufferQueue+PrepareOutputBufferQueue |
| Start | PREPARED/FLUSHED | STARTING→RUNNING | codecPlugin_->Start() |
| Stop | RUNNING/END_OF_STREAM/FLUSHED | STOPPING→PREPARED | codecPlugin_->Stop()+清Buffer |
| Flush | RUNNING/END_OF_STREAM | FLUSHING→FLUSHED | inputBufferQueueProducer_->Clear() |
| Release | ANY(except UNINITIALIZED) | RELEASING→UNINITIALIZED | codecPlugin_->Release()+清Buffer |
| Reset | ANY | INITIALIZED | codecPlugin_->Reset() |

---

## 8. 与相关记忆的关联

| 关联记忆 | 关系 |
|---------|------|
| S197 MediaEngine Filter录制管线 | MediaCodec是AudioEncoderFilter/VideoEncoderFilter等Filter的底层引擎 |
| S212 VideoDecoderAdapter | Filter层Adapter持有MediaCodec实例，双Callback驱动 |
| S214 SurfaceEncoderAdapter | 同上，Surface输入+编码输出 |
| S218 Native Buffer | MediaCodec通过AVBufferQueue管理OH_AVBuffer |
| S225 DRM CENC | MediaCodec.drmDecryptor_ == CodecDrmDecrypt实例，音频CENC解密入口 |
| S221 VideoCodecEncoder端口配置 | MediaCodec.Configure配置Meta参数，对应编码器端口配置 |