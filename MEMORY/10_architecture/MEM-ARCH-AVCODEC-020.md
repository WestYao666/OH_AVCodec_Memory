---
id: MEM-ARCH-AVCODEC-020
title: AudioDecoderAdapter 音频解码适配器——AudioCodec 封装与 Filter 集成
type: architecture_fact
scope: [AVCodec, AudioCodec, Adapter, FilterPipeline, Decoding]
status: draft
created_by: builder-agent
created_at: "2026-04-23T20:25:00+08:00"
updated_by: builder-agent
updated_at: "2026-04-23T20:30:00+08:00"
evidence:
  - kind: local_file
    path: /home/west/OH_AVCodec/services/media_engine/filters/audio_decoder_adapter.cpp
    anchor: Line 34: AudioCodecFactory::CreateByMime/::CreateByName; Line 54-63: Configure + SetParameter; Line 81-96: Prepare/Start/Stop lifecycle; Line 138-156: SetOutputBufferQueue/GetInputBufferQueue/QueueProducer; Line 162-176: ProcessInputBufferInner/ChangePlugin; Line 185-196: OnDumpInfo + dumpString; Line 198-210: SetCodecCallback/SetAudioDecryptionConfig
owner: 耀耀
review: pending
---

# MEM-ARCH-AVCODEC-020: AudioDecoderAdapter 音频解码适配器

## Metadata

| 字段 | 值 |
|------|-----|
| id | MEM-ARCH-AVCODEC-020 |
| title | AudioDecoderAdapter 音频解码适配器——AudioCodec 封装与 Filter 集成 |
| type | architecture_fact |
| scope | [AVCodec, AudioCodec, Adapter, FilterPipeline, Decoding] |
| status | draft |
| created_by | builder-agent |
| created_at | 2026-04-23 |
| confidence | high |

## 摘要

AudioDecoderAdapter 是 media_engine filters 中专用于**音频解码 Filter 管道**的适配器类，封装 `MediaAVCodec::AudioCodec` 实例，为 Filter 层提供统一的音频解码能力接口。它不是 Filter（无 AutoRegisterFilter 注册），而是被 AudioDecoderFilter 等 Filter 组合使用的**组合部件（Component）**。

其核心职责：在 Filter Pipeline 上下文与底层 MediaCodec 实例之间做协议转换和生命周期代理。

## 关键类与接口

### AudioDecoderAdapter
- **文件**: `services/media_engine/filters/audio_decoder_adapter.cpp`
- **LOG_DOMAIN**: `LOG_DOMAIN_SYSTEM_PLAYER`（"AudioDecoderAdapter"）
- **非 Filter**：无 AutoRegisterFilter 注册，由 AudioDecoderFilter 等持有

### 核心成员

| 成员 | 类型 | 说明 |
|------|------|------|
| `audiocodec_` | `std::shared_ptr<MediaAVCodec::AudioCodec>` | 底层 AudioCodec 实例 |
| `isRunning_` | `std::atomic<bool>` | 运行状态标志 |
| `inputBufferQueueProducer_` | `sptr<AVBufferQueueProducer>` | 输入队列生产者 |
| `outputBufferQueueProducer_` | `sptr<AVBufferQueueProducer>` | 输出队列生产者 |
| `outputBufferQueueConsumer_` | `sptr<AVBufferQueueConsumer>` | 输出队列消费者（由 audiocodec_ 托管） |

## 构造与初始化

```cpp
// Init 两种创建路径
Status AudioDecoderAdapter::Init(bool isMimeType, const std::string &name)
{
    if (isMimeType) {
        audiocodec_ = MediaAVCodec::AudioCodecFactory::CreateByMime(name, false);
    } else {
        audiocodec_ = MediaAVCodec::AudioCodecFactory::CreateByName(name);
    }
    FALSE_RETURN_V_MSG(audiocodec_ != nullptr, Status::ERROR_INVALID_STATE, "audiocodec_ is nullptr");
    return Status::OK;
}
```

**与 AudioCodecFactory 的关系**：
- `CreateByMime(name, isEncoder=false)` — 按 MIME 类型创建
- `CreateByName(name)` — 按 codec 名称创建

## 生命周期

| 阶段 | 方法 | 关键操作 |
|------|------|----------|
| Init | `Init(isMime, name)` | AudioCodecFactory 创建实例 |
| Configure | `Configure(parameter)` | 配置参数，成功返回 OK，AVCS_ERR_INVALID_VAL 返回 ERROR_UNSUPPORTED_FORMAT |
| Prepare | `Prepare()` | audiocodec_->Prepare()，isRunning_=false |
| Start | `Start()` | ScopedTimer 计时警告（>50ms），audiocodec_->Start()，isRunning_=true |
| Stop | `Stop()` | audiocodec_->Stop()，isRunning_=false |
| Flush | `Flush()` | audiocodec_->Flush()，isRunning_=false |
| Reset | `Reset()` | audiocodec_->Reset()，isRunning_=false |
| Release | `Release()` | audiocodec_->Release()，isRunning_=false |

## Buffer 队列管理

```cpp
// 设置输出队列
Status AudioDecoderAdapter::SetOutputBufferQueue(const sptr<Media::AVBufferQueueProducer> &bufferQueueProducer)

// 获取输入队列
sptr<Media::AVBufferQueueProducer> AudioDecoderAdapter::GetInputBufferQueue()
sptr<Media::AVBufferQueueConsumer> AudioDecoderAdapter::GetInputBufferQueueConsumer()

// 获取输出队列
sptr<Media::AVBufferQueueProducer> AudioDecoderAdapter::GetOutputBufferQueueProducer()
```

队列关系：
```
FilterPipeline → inputBufferQueueProducer_ → audiocodec_ → outputBufferQueueProducer_ → 下游Filter
```

## ProcessInputBufferInner

```cpp
void AudioDecoderAdapter::ProcessInputBufferInner(bool isTriggeredByOutPort, bool isFlushed, uint32_t &bufferStatus)
{
    FALSE_RETURN_MSG(audiocodec_ != nullptr, "ProcessInputBufferInner audiocodec_ is nullptr");
    audiocodec_->ProcessInputBufferInner(isTriggeredByOutPort, isFlushed, bufferStatus);
}
```

代理到 audiocodec_ 的 ProcessInputBufferInner，用于 Filter 层触发解码输入处理。

## ChangePlugin 动态插件切换

```cpp
Status AudioDecoderAdapter::ChangePlugin(const std::string &mime, bool isEncoder, const std::shared_ptr<Meta> &meta)
{
    FALSE_RETURN_V(meta != nullptr, Status::ERROR_INVALID_PARAMETER);
    FALSE_RETURN_V_MSG(audiocodec_ != nullptr, Status::ERROR_INVALID_STATE, "audiocodec_ is nullptr");
    int32_t ret = audiocodec_->ChangePlugin(mime, isEncoder, meta);
    return ret == AVCodecServiceErrCode::AVCS_ERR_OK ? Status::OK : Status::ERROR_INVALID_STATE;
}
```

用于运行时动态切换解码插件（如编码格式变化时重新配置）。

## Dump 与调试

```cpp
void AudioDecoderAdapter::OnDumpInfo(int32_t fd)
{
    // 写入 inputBufferQueueProducer_ 和 outputBufferQueueProducer_ 的队列大小
    dumpString += "AudioDecoderAdapter inputBufferQueueProducer_ size is:" + ... + "\n";
    dumpString += "AudioDecoderAdapter outputBufferQueueProducer_ size is:" + ... + "\n";
}
```

## DRM 解密支持

```cpp
int32_t AudioDecoderAdapter::SetAudioDecryptionConfig(
    const sptr<DrmStandard::IMediaKeySessionService> &keySession, const bool svpFlag)
{
    FALSE_RETURN_V_MSG(audiocodec_ != nullptr, (int32_t)Status::ERROR_INVALID_STATE, "audiocodec_ is nullptr");
    return audiocodec_->SetAudioDecryptionConfig(keySession, svpFlag);
}
```

与 MEM-ARCH-AVCODEC-017（DRM CENC 解密流程）关联，支持安全视频路径（SVP）。

## 错误处理模式

| 错误码 | 处理策略 |
|--------|----------|
| `AVCS_ERR_INVALID_VAL`（Configure） | 返回 `ERROR_UNSUPPORTED_FORMAT` |
| `AVCS_ERR_OK` | 返回 `Status::OK` |
| 其他非 OK | 返回 `Status::ERROR_INVALID_STATE` |

## 与 AudioDecoderFilter 的关系

AudioDecoderFilter 是 Filter（通过 AutoRegisterFilter 注册），AudioDecoderAdapter 是其**内部组合组件**：

```
AudioDecoderFilter
  └── AudioDecoderAdapter (组合)
        └── MediaAVCodec::AudioCodec (底层)
```

AudioDecoderFilter 通过 AudioDecoderAdapter 代理所有 MediaCodec 调用，实现 Filter 协议与 AudioCodec 协议的解耦。

## 证据

- `services/media_engine/filters/audio_decoder_adapter.cpp` Line 34: `AudioCodecFactory::CreateByMime/CreateByName`
- Line 54-63: `Configure` + `SetParameter` 方法体
- Line 81-96: `Prepare/Start/Stop/Flush/Reset/Release` 生命周期方法
- Line 138-156: `SetOutputBufferQueue/GetInputBufferQueue/GetOutputBufferQueueProducer`
- Line 162-176: `ProcessInputBufferInner/ChangePlugin`
- Line 185-196: `OnDumpInfo` dump 字符串构建
- Line 198-210: `SetCodecCallback/SetAudioDecryptionConfig`
- Line 37: `AUDIO_DECODER_ADAPTER_CPP` 编译宏
- Line 27: `AUDIOCODEC_START_WARNING_MS = 50`（启动警告阈值 50ms）

## 相关已有记忆

- **MEM-ARCH-AVCODEC-006**: media_codec 编解码数据流（AudioCodec 核心接口）
- **MEM-ARCH-AVCODEC-S8**: 音频编解码 FFmpeg 插件架构（AudioBaseCodec）
- **MEM-ARCH-AVCODEC-017**: DRM CENC 解密流程（SetAudioDecryptionConfig）
- **MEM-ARCH-AVCODEC-010**: Codec 实例生命周期（Create→Configure→Start→Stop→Release）
- **MEM-ARCH-AVCODEC-003**: Plugin 架构（AutoRegisterFilter 注册机制）

## 待补充

- AudioDecoderFilter 如何组合 AudioDecoderAdapter 的具体代码（需要查看 audio_decoder_filter.cpp）
- AudioCodecFactory 的完整工厂方法实现
- ProcessInputBufferInner 的具体调用时序
- 与 VideoDecoderAdapter 的对称设计对比
