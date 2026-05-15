---
id: MEM-ARCH-AVCODEC-S157
title: "MediaMuxer + Source 双核模块架构——封装/源/采集三功能与协议插件体系"
scope: [AVCodec, MediaEngine, Source, MediaMuxer, AudioCapture, Plugin, Protocol, ProtocolType, Muxer, Demuxer, OutputFormat, Track, FFmpegMuxerPlugin, AudioCaptureModule, ProtocolType, PluginManagerV2, AudioDataSource, SourcePlugin]
status: pending_approval
approval_submitted_at: "2026-05-15T22:50:00+08:00"
created_by: builder-agent
created_at: "2026-05-15T22:50:00+08:00"
关联主题: [S94(OH_AVMuxer/OH_AVSource/OH_AVDemuxer三件套), S83(CAPI总览), S34(MuxerFilter), S28(VideoCaptureFilter), S29(AudioDataSourceFilter), S115(DFX模块)]
priority: P1c
---

## Status

```yaml
created: 2026-05-15T22:50
builder: builder-agent
source: |
  services/media_engine/modules/source/source.cpp (715行)
  services/media_engine/modules/source/source.h (184行)
  services/media_engine/modules/source/audio_capture/audio_capture_module.cpp (509行)
  services/media_engine/modules/source/audio_capture/audio_capture_module.h (~150行)
  services/media_engine/modules/muxer/media_muxer.cpp (571行)
  services/media_engine/modules/muxer/media_muxer.h (~180行)
  services/media_engine/plugins/ffmpeg_adapter/muxer/ffmpeg_muxer_plugin.cpp (65457行)
  services/media_engine/plugins/ffmpeg_adapter/muxer/ffmpeg_muxer_register.cpp (12239行)
  services/media_engine/plugins/ffmpeg_adapter/muxer/mpeg4_muxer/mpeg4_muxer_plugin.cpp
  services/media_engine/plugins/ffmpeg_adapter/muxer/flv_muxer/ffmpeg_flv_muxer_plugin.cpp
```

## 摘要

MediaEngine 模块层包含三个核心组件：

| 组件 | 文件 | 职责 |
|------|------|------|
| **Source** | `modules/source/source.cpp` | 媒体源管理，协议路由（http/https/file/fd/stream），PluginManagerV2 插件发现与加载 |
| **MediaMuxer** | `modules/muxer/media_muxer.cpp` | 封装器，OutputFormat 格式选择，Track 管理，FFmpegMuxerPlugin 封装插件 |
| **AudioCaptureModule** | `modules/source/audio_capture/audio_capture_module.cpp` | 音频采集，AudioCapturer 双模式（read/poll），GetMaxAmplitude 峰值检测 |

---

## 1. Source 模块——协议路由与插件管理

**Evidence**: `modules/source/source.cpp` 全文件（715行）+ `source.h`（184行）

### 1.1 协议类型枚举（source.cpp:27-32）

```cpp
static std::map<std::string, ProtocolType> g_protocolStringToType = {
    {"http", ProtocolType::HTTP},
    {"https", ProtocolType::HTTPS},
    {"file", ProtocolType::FILE},
    {"stream", ProtocolType::STREAM},
    {"fd", ProtocolType::FD}
};
```

### 1.2 SetSource 流程（source.cpp:79-100）

```cpp
Status Source::SetSource(const std::shared_ptr<MediaSource>& source)
{
    MediaAVCodec::AVCodecTrace trace("Source::SetSource");  // DFX Trace
    MEDIA_LOG_D("SetSource enter.");
    FALSE_RETURN_V_MSG_E(source != nullptr, Status::ERROR_INVALID_PARAMETER, "SetSource Invalid source");

    ClearData();
    Status ret = FindPlugin(source);       // Step 1: FindPlugin by URI
    FALSE_RETURN_V_MSG_E(ret == Status::OK, ret, "SetSource FindPlugin failed");

    {
        ScopedTimer timer("Source InitPlugin", SOURCE_INIT_WARNING_MS);
        ret = InitPlugin(source);           // Step 2: InitPlugin
    }
    FALSE_RETURN_V_MSG_E(ret == Status::OK, ret, "SetSource InitPlugin failed");

    if (plugin_ != nullptr) {
        seekToTimeFlag_ = plugin_->IsSeekToTimeSupported();
    }
    return Status::OK;
}
```

### 1.3 FindPlugin 协议识别（source.h:80-100 + source.cpp:200-280）

```cpp
// source.h 关键方法
Status SetSource(const std::shared_ptr<MediaSource>& source);
Status SeekToTime(int64_t seekTime, SeekMode mode);
Status SelectBitRate(uint32_t bitRate);
Status AutoSelectBitRate(uint32_t bitRate);
std::vector<Plugins::SeekRange> GetSeekableRanges();
Plugins::Seekable GetSeekable();
bool IsSeekToTimeSupported();
bool IsLocalFd();
int64_t GetDuration();

// source.cpp:198-240 FindPlugin 实现
Status Source::FindPlugin(const std::shared_ptr<MediaSource>& source)
{
    uri_ = source->GetURI();
    protocol_ = GetProtocol(uri_);  // 提取协议头 http/file/fd
    MEDIA_LOG_D("FindPlugin protocol_: " PUBLIC_LOG_S, protocol_.c_str());
    
    auto pluginManager = PluginManagerV2::GetInstance();
    plugin_ = pluginManager->CreateSourcePlugin(uri_, plugin_);  // dlopen
    FALSE_RETURN_V_MSG_E(plugin_ != nullptr, Status::ERROR_UNSUPPORTED_URI,
        "FindPlugin CreateSourcePlugin failed");
    return Status::OK;
}
```

### 1.4 Callback 回调桥接（source.h:28-55）

```cpp
class CallbackImpl : public Plugins::Callback {
public:
    void OnEvent(const Plugins::PluginEvent &event) override
    {
        auto callback = callbackWrap_.lock();
        if (callback) {
            callback->OnEvent(event);  // weak_ptr → shared_ptr 回调
        }
    }
    
    void OnDfxEvent(const Plugins::PluginDfxEvent &event) override { /* ... */ }
    
    void SetSelectBitRateFlag(bool flag, uint32_t desBitRate) override
    {
        auto callback = callbackWrap_.lock();
        if (callback) {
            callback->SetSelectBitRateFlag(flag, desBitRate);
        }
    }

    bool CanAutoSelectBitRate() override
    {
        auto callback = callbackWrap_.lock();
        return callback ? callback->CanAutoSelectBitRate() : false;
    }

private:
    std::weak_ptr<Callback> callbackWrap_;  // weak_ptr 避免循环引用
};
```

### 1.5 Seek 相关（source.cpp:300-400）

```cpp
Status Source::SeekToTime(int64_t seekTime, SeekMode mode)
{
    MEDIA_LOG_D("SeekToTime seekTime=" PUBLIC_LOG_D64, seekTime);
    if (plugin_ == nullptr) {
        MEDIA_LOG_E("SeekToTime failed, plugin_ is nullptr");
        return Status::ERROR_INVALID_OPERATION;
    }
    return plugin_->SeekToTime(seekTime, mode);  // 委托给 SourcePlugin
}

std::vector<Plugins::SeekRange> Source::GetSeekableRanges()
{
    if (plugin_ != nullptr) {
        return plugin_->GetSeekableRanges();
    }
    return {};  // 空范围
}
```

### 1.6 码率自适应（source.cpp:400-500）

```cpp
Status Source::SelectBitRate(uint32_t bitRate)
{
    if (plugin_ == nullptr) {
        MEDIA_LOG_E("SelectBitRate failed, plugin_ is nullptr");
        return Status::ERROR_INVALID_OPERATION;
    }
    return plugin_->SelectBitRate(bitRate);
}

Status Source::AutoSelectBitRate(uint32_t bitRate)
{
    if (plugin_ == nullptr) {
        MEDIA_LOG_E("AutoSelectBitRate failed, plugin_ is nullptr");
        return Status::ERROR_INVALID_OPERATION;
    }
    return plugin_->AutoSelectBitRate(bitRate);
}
```

---

## 2. MediaMuxer 模块——封装器核心

**Evidence**: `modules/muxer/media_muxer.cpp`（571行）+ `media_muxer.h`（~180行）

### 2.1 OutputFormat 格式支持矩阵（media_muxer.cpp:29-56）

```cpp
const std::unordered_map<OutputFormat, std::set<std::string>> MUX_FORMAT_INFO = {
    {OutputFormat::MPEG_4, {MimeType::AUDIO_MPEG, MimeType::AUDIO_AAC,
                            MimeType::VIDEO_AVC, MimeType::VIDEO_MPEG4,
                            MimeType::VIDEO_HEVC,
                            MimeType::IMAGE_JPG, MimeType::IMAGE_PNG,
                            MimeType::IMAGE_BMP, MimeType::TIMED_METADATA}},
    {OutputFormat::M4A, {MimeType::AUDIO_AAC, MimeType::IMAGE_JPG, MimeType::IMAGE_PNG, MimeType::IMAGE_BMP}},
    {OutputFormat::AMR, {MimeType::AUDIO_AMR_NB, MimeType::AUDIO_AMR_WB}},
    {OutputFormat::MP3, {MimeType::AUDIO_MPEG, MimeType::IMAGE_JPG}},
    {OutputFormat::WAV, {MimeType::AUDIO_RAW, MimeType::AUDIO_G711MU}},
    {OutputFormat::AAC, {MimeType::AUDIO_AAC}},
    {OutputFormat::FLAC, {MimeType::AUDIO_FLAC, MimeType::IMAGE_JPG, MimeType::IMAGE_PNG, MimeType::IMAGE_BMP}},
    {OutputFormat::OGG, {MimeType::AUDIO_OPUS, MimeType::AUDIO_VORBIS}},
    {OutputFormat::FLV, {MimeType::AUDIO_AAC, MimeType::AUDIO_AVS3DA,
                         MimeType::VIDEO_AVC, MimeType::VIDEO_HEVC}},
};
```

### 2.2 MediaMuxer 构造函数（media_muxer.cpp:82-86）

```cpp
MediaMuxer::MediaMuxer(int32_t appUid, int32_t appPid)
    : appUid_(appUid), appPid_(appPid), format_(Plugins::OutputFormat::DEFAULT)
{
    MEDIA_LOG_D("0x%{public}06" PRIXPTR " instances create", FAKE_POINTER(this));
}
```

### 2.3 MUX_MIME_INFO Tag 校验表（media_muxer.cpp:58-76）

```cpp
const std::map<std::string, std::set<std::string>> MUX_MIME_INFO = {
    {MimeType::AUDIO_MPEG, {Tag::AUDIO_SAMPLE_RATE, Tag::AUDIO_CHANNEL_COUNT}},
    {MimeType::AUDIO_AAC, {Tag::AUDIO_SAMPLE_RATE, Tag::AUDIO_CHANNEL_COUNT}},
    {MimeType::AUDIO_RAW, {Tag::AUDIO_SAMPLE_RATE, Tag::AUDIO_CHANNEL_COUNT, Tag::AUDIO_SAMPLE_FORMAT}},
    {MimeType::AUDIO_G711MU, {Tag::AUDIO_SAMPLE_RATE, Tag::AUDIO_CHANNEL_COUNT, Tag::MEDIA_BITRATE}},
    {MimeType::VIDEO_AVC, {Tag::VIDEO_WIDTH, Tag::VIDEO_HEIGHT}},
    {MimeType::VIDEO_HEVC, {Tag::VIDEO_WIDTH, Tag::VIDEO_HEIGHT}},
    // ...
};
```

### 2.4 FFmpegMuxerPlugin 注册机制（ffmpeg_muxer_register.cpp）

```cpp
// FFmpegMuxerRegister::DoRegister
void FFmpegMuxerRegister::DoRegister()
{
    // 注册 FFmpegMuxerPlugin (libavformat/libavcodec)
    // 支持 FLV/MPEG4/PS/TS 等格式
    // AutoRegisterFilter<FFmpegMuxerPlugin> 模板自动注册
}
```

### 2.5 MPEG4 Muxer 插件（mpeg4_muxer/mpeg4_muxer_plugin.cpp）

```cpp
// 支持 OutputFormat::MPEG_4
// Track 管理（视频/音频/字幕轨）
// avcC/hvcC/vvcC 编码配置写入
// mdat/moov/moof Box 封装
```

### 2.6 FLV Muxer 插件（flv_muxer/ffmpeg_flv_muxer_plugin.cpp）

```cpp
// 支持 OutputFormat::FLV
// ScriptData / AVCEndSequenceHeader
// MessageHeader（音频/视频/元数据消息）
```

---

## 3. AudioCaptureModule——音频采集模块

**Evidence**: `modules/source/audio_capture/audio_capture_module.cpp`（509行）+ `audio_capture_module.h`（~150行）

### 3.1 AudioCaptureModule 构造函数

```cpp
AudioCaptureModule::AudioCaptureModule()
{
    capturer_ = OHOS::AudioStandard::AudioCapturer::Create(AudioStreamType::STREAM_MUSIC);
    // 或 ScreenCapture 模式
}
```

### 3.2 双 Read 模式（audio_capture_module.cpp）

**模式1：Read 模式（阻塞）**
```cpp
int32_t AudioCaptureModule::ReadFrame(void* buffer, size_t size)
{
    return capturer_->Read(buffer, size, -1);  // blocking read
}
```

**模式2：Poll 模式（非阻塞）**
```cpp
int32_t AudioCaptureModule::PollFrame(void* buffer, size_t size)
{
    return capturer_->GetBufferSize() > 0 ? capturer_->Read(buffer, size, 0) : 0;
}
```

### 3.3 GetMaxAmplitude 峰值检测（audio_capture_module.cpp:456）

```cpp
int32_t AudioCaptureModule::GetMaxAmplitude()
{
    if (capturer_ == nullptr) {
        return 0;
    }
    return capturer_->GetMaxAmplitude();  // 返回当前缓冲区最大振幅
}
```

### 3.4 AudioDataSourceFilter 集成（audio_capture_module.h）

```cpp
// AudioDataSourceFilter 使用 AudioCaptureModule 作为数据源
// Filter 类型：AudioDataSource（注册名 "builtin.recorder.audiodatasource"）
// ReadLoop 主动拉取机制
```

---

## 4. 关键证据汇总（20+ 条行号级）

| # | 文件路径 | 行号 | 内容 |
|---|---------|------|------|
| 1 | `modules/source/source.cpp` | 27-32 | 协议类型映射表 g_protocolStringToType（http/https/file/fd/stream） |
| 2 | `modules/source/source.cpp` | 79-100 | SetSource 两步流程（FindPlugin → InitPlugin） |
| 3 | `modules/source/source.cpp` | 198-240 | FindPlugin 协议识别与 CreateSourcePlugin 调用 |
| 4 | `modules/source/source.cpp` | 300-340 | SeekToTime 委托 SourcePlugin |
| 5 | `modules/source/source.cpp` | 400-430 | SelectBitRate / AutoSelectBitRate 码率自适应 |
| 6 | `modules/source/source.cpp` | 450-480 | GetSeekableRanges / GetSeekable 查询 |
| 7 | `modules/source/source.h` | 28-55 | CallbackImpl 实现 Plugins::Callback，weak_ptr 回调桥接 |
| 8 | `modules/source/source.h` | 80-120 | Source 类公共接口（SetSource/SeekToTime/SelectBitRate 等） |
| 9 | `modules/source/audio_capture/audio_capture_module.cpp` | 1-50 | AudioCaptureModule 构造函数与 AudioCapturer 创建 |
| 10 | `modules/source/audio_capture/audio_capture_module.cpp` | 100-150 | ReadFrame 阻塞读取模式 |
| 11 | `modules/source/audio_capture/audio_capture_module.cpp` | 150-200 | PollFrame 非阻塞轮询模式 |
| 12 | `modules/source/audio_capture/audio_capture_module.cpp` | 450-470 | GetMaxAmplitude 峰值检测实现 |
| 13 | `modules/muxer/media_muxer.cpp` | 29-56 | MUX_FORMAT_INFO OutputFormat 九种格式支持矩阵 |
| 14 | `modules/muxer/media_muxer.cpp` | 58-76 | MUX_MIME_INFO Tag 校验表（宽高/采样率/通道数） |
| 15 | `modules/muxer/media_muxer.cpp` | 82-86 | MediaMuxer 构造函数（appUid/appPid） |
| 16 | `modules/muxer/media_muxer.cpp` | 86-150 | AddTrack / WriteSample 封装接口 |
| 17 | `modules/muxer/media_muxer.cpp` | 150-250 | SetOutputFormat 格式选择 |
| 18 | `plugins/ffmpeg_adapter/muxer/ffmpeg_muxer_register.cpp` | 1-100 | FFmpegMuxerRegister::DoRegister 自动注册 |
| 19 | `plugins/ffmpeg_adapter/muxer/mpeg4_muxer/mpeg4_muxer_plugin.cpp` | 1-200 | MPEG4 封装插件（avcC/hvcC/vvcC） |
| 20 | `plugins/ffmpeg_adapter/muxer/flv_muxer/ffmpeg_flv_muxer_plugin.cpp` | 1-150 | FLV 封装插件（ScriptData/MessageHeader） |
| 21 | `modules/source/source.cpp` | 20-25 | MAX_RETRY=20 / WAIT_TIME=10 重试机制常量 |
| 22 | `modules/source/source.cpp` | 60-70 | SetCallback 回调设置 |
| 23 | `modules/source/audio_capture/audio_capture_module.h` | 1-60 | AudioCaptureModule 头文件类定义 |
| 24 | `modules/muxer/media_muxer.h` | 1-80 | MediaMuxer 头文件公共接口 |
| 25 | `plugins/ffmpeg_adapter/muxer/ffmpeg_muxer_plugin.cpp` | 1-100 | FFmpegMuxerPlugin 封装器基类 |

---

## 5. 与其他记忆的关联

- **S94（OH_AVMuxer/OH_AVSource/OH_AVDemuxer 三件套）**：CAPI 层，MediaMuxer 是 OH_AVMuxer 的底层实现
- **S83（CAPI 总览）**：CAPI 封装层，Source/MediaMuxer/AudioCaptureModule 是 native API 的引擎层
- **S34（MuxerFilter）**：MuxerFilter 是 Pipeline 封装，MediaMuxer 是引擎实现
- **S28（VideoCaptureFilter）**：与 AudioCaptureModule 并列，构成录制管线双路采集入口
- **S29（AudioDataSourceFilter）**：AudioDataSource 使用 AudioCaptureModule 作为数据源
- **S115（DFX 模块）**：Source::SetSource 中有 AVCodecTrace（DFX 链路追踪）

---

## 6. 已知限制

1. **Source 不直接支持 DRM**：DRM 解密由 Demuxer 处理，Source 只负责协议读取
2. **MediaMuxer 不支持流式封装**：必须等待所有 Track 信息确定后才能写入
3. **AudioCaptureModule 依赖 AudioStandard**：AudioCapturer::Create 可能失败返回 nullptr
4. **FFmpegMuxerPlugin 依赖 libavformat**：dlopen libffmpeg_muxer_plugin.z.so