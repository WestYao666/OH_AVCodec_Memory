---
type: architecture
id: MEM-ARCH-AVCODEC-S18
status: draft
topic: AudioCodecServer 音频编解码服务架构——AudioCodecFactory+CodecStatus七状态机与AudioCodec生命周期
created_at: "2026-04-24T06:10:00+08:00"
evidence: |
  - source: /home/west/av_codec_repo/services/services/codec/server/audio/audio_codec_server.h
    anchor: "AudioCodecServer::CodecStatus enum: UNINITIALIZED/INITIALIZED/CONFIGURED/RUNNING/FLUSHED/END_OF_STREAM/ERROR"
  - source: /home/west/av_codec_repo/services/services/codec/server/audio/audio_codec_server.cpp
    anchor: "AudioCodecServer::Create() -> AudioCodecFactory::Instance().CreateCodecByName()"
  - source: /home/west/av_codec_repo/services/services/codec/server/audio/audio_codec_server.cpp
    anchor: "AudioCodecServer::Configure() -> CHECK_AND_RETURN_RET_LOG(status_ == INITIALIZED) -> StatusChanged(CONFIGURED)"
  - source: /home/west/av_codec_repo/services/services/codec/server/audio/audio_codec_server.cpp
    anchor: "AudioCodecServer::Start() -> StatusChanged(RUNNING); Stop() -> StatusChanged(CONFIGURED)"
  - source: /home/west/av_codec_repo/services/services/codec/server/audio/audio_codec_server.cpp
    anchor: "AudioCodecServer::InitByName / InitByMime — 双初始化路径按名称或MIME类型"
  - source: /home/west/av_codec_repo/services/services/codec/server/audio/audio_codec_factory.h
    anchor: "AudioCodecFactory::Instance() singleton; GetCodecNameArrayByMime; CreateCodecByName"
  - source: /home/west/av_codec_repo/services/services/codec/server/audio/audio_codec_server.h
    anchor: "SetCallback支持AVCodecCallback/MediaCodecCallback/MediaCodecParameterCallback/MediaCodecParameterWithAttrCallback四种回调"
  - source: /home/west/av_codec_repo/services/services/codec/server/audio/audio_codec_server.h
    anchor: "QueueInputBuffer/ReleaseOutputBuffer — 无Surface模式（音频不使用输入Surface）"
---

# MEM-ARCH-AVCODEC-S18: AudioCodecServer 音频编解码服务架构

## Metadata

| 字段 | 值 |
|------|-----|
| id | MEM-ARCH-AVCODEC-S18 |
| title | AudioCodecServer 音频编解码服务架构——AudioCodecFactory+CodecStatus七状态机与AudioCodec生命周期 |
| scope | [AVCodec, AudioCodec, AudioCodecServer, CodecStatus, StateMachine, AudioCodecFactory, Lifecycle] |
| status | draft |
| created_by | builder-agent |
| created_at | 2026-04-24 |
| type | architecture_fact |
| confidence | high |
| related_scenes | [新需求开发, 问题定位, 音频编解码接入, 音频Codec生命周期, 音频编解码调试] |
| why_it_matters: |
  - 音频编解码接入：AudioCodecServer 是音频编解码的入口类，与视频CodecServer平行但更简洁（无Surface）
  - 新需求开发：接入新音频编解码格式需理解 AudioCodecFactory 工厂创建路径和 InitByName/InitByMime 双模式
  - 问题定位：音频解码无输出、花屏、卡顿时需排查 AudioCodecServer 状态机是否正确推进
  - 对比视频CodecServer：音频CodecServer状态机更简洁（无Surface/PostProcessing），生命周期相同

## 摘要

AudioCodecServer 是 AVCodec 音频编解码的**服务端入口类**，位于 `services/services/codec/server/audio/` 目录。与视频 CodecServer 平行，但更简洁：
- **无 Surface 模式**：音频编解码不使用 Surface（无 CreateInputSurface/SetOutputSurface）
- **七状态机**：UNINITIALIZED → INITIALIZED → CONFIGURED → RUNNING → FLUSHED/END_OF_STREAM/ERROR
- **AudioCodecFactory 工厂**：单例模式，通过名称或 MIME 类型创建音频插件
- **四种回调**：支持 AVCodecCallback、MediaCodecCallback、MediaCodecParameterCallback、MediaCodecParameterWithAttrCallback

## 架构层级

```
客户端调用（native_avcodec_* API）
         ↓
AudioCodecServer（CodecServer 音频版）
         ↓
AudioCodecFactory::Instance().CreateCodecByName()
         ↓
CodecBase 插件（FFmpeg 音频插件 / 硬件插件）
```

## CodecStatus 七状态机

| 状态 | 含义 | 合法前驱状态 | 关键方法 |
|------|------|------------|---------|
| UNINITIALIZED | 对象创建，未初始化 | — | 构造函数 |
| INITIALIZED | 已 Init（插件已创建） | UNINITIALIZED | Init(), InitByName(), InitByMime() |
| CONFIGURED | 已 Configure（格式已设置） | INITIALIZED | Configure() |
| RUNNING | 运行中 | CONFIGURED, FLUSHED, END_OF_STREAM | Start() |
| FLUSHED | 已 Flush（缓冲区已清空） | RUNNING | Flush() |
| END_OF_STREAM | 流结束 | RUNNING | NotifyEos() |
| ERROR | 错误状态 | ANY | OnError() |

**状态转换规则：**
- `Stop()` → CONFIGURED（从 RUNNING/FLUSHED/END_OF_STREAM 回到 CONFIGURED）
- `Reset()` → INITIALIZED（回到初始状态）
- `Release()` → 对象销毁

## AudioCodecFactory 单例工厂

```cpp
class AudioCodecFactory {
public:
    static AudioCodecFactory &Instance();  // 单例
    std::vector<std::string> GetCodecNameArrayByMime(const AVCodecType type, const std::string &mime);
    std::shared_ptr<CodecBase> CreateCodecByName(const std::string &name, API_VERSION apiVersion);
};
```

初始化路径：
- **InitByName**：按编码器名称初始化（`AudioCodecFactory::CreateCodecByName(codecName)`）
- **InitByMime**：按 MIME 类型初始化（先 `GetCodecNameArrayByMime` 查名称列表，再 `CreateCodecByName`）

## 与视频 CodecServer 对比

| 特性 | AudioCodecServer | CodecServer（视频） |
|------|-----------------|-------------------|
| Surface 支持 | ❌ 无 | ✅ 有（CreateInputSurface/SetOutputSurface） |
| PostProcessing | ❌ 无 | ✅ 有（DecoderFilter → PostProcessingFilter） |
| 状态机 | 7状态（UNINIT~ERROR） | 类似 |
| 回调类型 | 4种回调 | 类似 |
| 插件创建 | AudioCodecFactory 单例 | CodecFactory 单例 |
| 输入队列 | QueueInputBuffer | QueueInputBuffer |
| 输出队列 | ReleaseOutputBuffer | ReleaseOutputBuffer |

## 关键代码片段

### 状态转换（Configure）

```cpp
int32_t AudioCodecServer::Configure(const Format &format)
{
    // 状态校验：必须是 INITIALIZED
    CHECK_AND_RETURN_RET_LOG(status_ == INITIALIZED, AVCS_ERR_INVALID_STATE,
                             "In invalid state, %{public}s", GetStatusDescription(status_).data());
    // 配置 codecBase_
    CHECK_AND_RETURN_RET_LOG(status_ == INITIALIZED, AVCS_ERR_INVALID_STATE, ...);
    StatusChanged(CONFIGURED);  // 状态推进
    return AVCS_ERR_OK;
}
```

### 工厂创建插件

```cpp
// InitByName 路径
codecBase_ = AudioCodecFactory::Instance().CreateCodecByName(codecName_, apiVersion);

// InitByMime 路径：先查名称列表
std::vector<std::string> nameArray = AudioCodecFactory::Instance().GetCodecNameArrayByMime(codecType_, codecName_);
for (auto iter = nameArray.begin(); iter != nameArray.end(); iter++) {
    codecBase_ = AudioCodecFactory::Instance().CreateCodecByName(*iter, apiVersion);
}
```

### Start 状态推进

```cpp
int32_t AudioCodecServer::Start()
{
    CHECK_AND_RETURN_RET_LOG(status_ == CONFIGURED || status_ == FLUSHED,
                             AVCS_ERR_INVALID_STATE, ...);
    StatusChanged(RUNNING);
    return AVCS_ERR_OK;
}
```

## Impact

- **AudioCodecServer 是音频编解码的核心入口**：所有音频编解码操作都经过此类
- **七状态机是调试关键**：音频无输出时首先检查状态机是否正确推进到 RUNNING
- **与视频 CodecServer 平行但简化**：无 Surface 和 PostProcessing，适合作为理解视频 CodecServer 的前置概念
- **AudioCodecFactory 单例保证插件唯一性**：避免重复创建音频编码器/解码器实例
