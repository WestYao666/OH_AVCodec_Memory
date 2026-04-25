---
type: architecture
id: MEM-ARCH-AVCODEC-S18
status: pending_approval
topic: AudioCodecServer 音频编解码服务架构——AudioCodecFactory+CodecStatus七状态机与AudioCodec生命周期
created_at: "2026-04-24T06:10:00+08:00"
updated_at: "2026-04-25T19:45:00+08:00"
submitted_at: "2026-04-25T19:45:00+08:00"
scope: [AVCodec, AudioCodec, AudioCodecServer, CodecStatus, StateMachine, AudioCodecFactory, Lifecycle, AudioCodecAdapter]
pipeline_position: AudioCodecServer → AudioCodecFactory → AudioCodecAdapter/AudioCodec
evidence_count: 21
author: builder-agent

## 摘要

AudioCodecServer 是 AVCodec 模块的**音频编解码服务端入口类**，位于 `services/services/codec/server/audio/` 目录。与视频 CodecServer 平行，但更简洁（无 Surface/PostProcessing）。核心职责：七状态机维护、插件生命周期管理、四种回调分发。

## 架构层级

```
native_avcodec_* API（客户端）
         ↓
AudioCodecServer（服务端入口，audio_codec_server.cpp:68 Create()）
         ↓
AudioCodecFactory::Instance().CreateCodecByName(audio_codec_factory.cpp:54)
         ↓
API_VERSION_10 → AudioCodecAdapter（适配层，AudioCodec→AudioCodecAdapter包装）
         or
API_VERSION_11+ → AudioCodec（原生插件，audio_codec.cpp CreateCodecByName）
```

## CodecStatus 七状态机

| 状态 | 值 | 合法前驱 | 关键转换方法 |
|------|---|---------|------------|
| UNINITIALIZED | 0 | — | 构造函数 |
| INITIALIZED | 1 | UNINITIALIZED | Init() 成功（audio_codec_server.cpp:119） |
| CONFIGURED | 2 | INITIALIZED | Configure() 成功（audio_codec_server.cpp:170） |
| RUNNING | 3 | CONFIGURED, FLUSHED | Start() 成功（audio_codec_server.cpp:195） |
| FLUSHED | 4 | RUNNING, END_OF_STREAM | Flush() 成功（audio_codec_server.cpp:229） |
| END_OF_STREAM | 5 | RUNNING | NotifyEos() 成功（audio_codec_server.cpp:244） |
| ERROR | 6 | ANY | 任何方法失败 |

## 关键证据

| # | 文件:行号 | 证据 |
|---|----------|------|
| E1 | audio_codec_server.h:38-46 | CodecStatus 枚举七状态定义（UNINITIALIZED~ERROR） |
| E2 | audio_codec_server.h:109-110 | GetStatusDescription(status) + StatusChanged(newStatus) 状态机驱动 |
| E3 | audio_codec_server.h:115 | status_ = UNINITIALIZED 成员变量默认值 |
| E4 | audio_codec_server.cpp:68-125 | AudioCodecServer::Create() → Init() → StatusChanged(INITIALIZED) |
| E5 | audio_codec_server.cpp:107 | Init() 调用 InitByName 或 InitByMime（isMimeType 判定） |
| E6 | audio_codec_server.cpp:130-137 | InitByName: GetAudioCodecName → AudioCodecFactory::CreateCodecByName |
| E7 | audio_codec_server.cpp:140-155 | InitByMime: GetCodecNameArrayByMime → 遍历尝试创建直到成功 |
| E8 | audio_codec_server.cpp:116-119 | shareBufCallback_ = make_shared<CodecBaseCallback>(AVCodecCallback 接口) |
| E9 | audio_codec_server.cpp:121-123 | avBufCallback_ = make_shared<VCodecBaseCallback>(MediaCodecCallback 接口) |
| E10 | audio_codec_server.cpp:160-173 | Configure() 状态校验（必须是 INITIALIZED）→ codecBase_->Configure → StatusChanged(CONFIGURED) |
| E11 | audio_codec_server.cpp:185-198 | Start() 状态校验（FLUSHED 或 CONFIGURED）→ codecBase_->Start → StatusChanged(RUNNING) |
| E12 | audio_codec_server.cpp:201-218 | Stop() → codecBase_->Stop → StatusChanged(CONFIGURED)（回到已配置态） |
| E13 | audio_codec_server.cpp:217-234 | Flush() → codecBase_->Flush → StatusChanged(FLUSHED) |
| E14 | audio_codec_server.cpp:232-249 | NotifyEos() → codecBase_->NotifyEos → StatusChanged(END_OF_STREAM) |
| E15 | audio_codec_server.cpp:251-265 | Reset() → codecBase_->Reset → StatusChanged(INITIALIZED)（回到初始态） |
| E16 | audio_codec_server.cpp:260-275 | Release() → codecBase_->Release → 对象销毁（nullptr 置空） |
| E17 | audio_codec_server.h:66-69 | 四种 SetCallback 重载（AVCodecCallback/MediaCodecCallback/MediaCodecParameterCallback/MediaCodecParameterWithAttrCallback） |
| E18 | audio_codec_server.cpp:282-305 | QueueInputBuffer 双签名（含 AVCodecBufferInfo info + AVCodecBufferFlag flag） |
| E19 | audio_codec_server.cpp:341-371 | ReleaseOutputBufferOfCodec(index, render) → codecBase_->ReleaseOutputBuffer |
| E20 | audio_codec_factory.cpp:38-54 | CreateCodecByName 按 API_VERSION 分发：API_VERSION_10 → AudioCodecAdapter；API_VERSION_11+ → AudioCodec |
| E21 | audio_codec_factory.cpp:29-35 | GetCodecNameArrayByMime: codecListCore->FindCodecNameArray |

## 与视频 CodecServer 对比

| 特性 | AudioCodecServer | CodecServer（视频） |
|------|-----------------|-------------------|
| Surface 支持 | ❌ 无 | ✅ 有 |
| PostProcessing | ❌ 无 | ✅ 有 |
| CreateInputSurface | ❌ 无 | ✅ 有 |
| SetOutputSurface | ❌ 无 | ✅ 有 |
| 状态机 | 7状态（UNINIT~ERROR） | 7状态 |
| 回调类型 | 4种（AVCodecCallback/MediaCodecCallback/...） | 4种 |
| 插件工厂 | AudioCodecFactory 单例 | CodecFactory 单例 |
| 输入缓冲 | QueueInputBuffer(index, info, flag) | 同上 |
| 输出缓冲 | ReleaseOutputBuffer(index, render) | 同上 |

## AudioCodecFactory 工厂分发逻辑

```cpp
// audio_codec_factory.cpp:38-54
std::shared_ptr<CodecBase> AudioCodecFactory::CreateCodecByName(const std::string &name, API_VERSION apiVersion)
{
    CodecType codecType = codecListCore->FindCodecType(name);
    switch (codecType) {
        case AVCODEC_AUDIO_CODEC:
            if (apiVersion == API_VERSION_10) {
                codec = std::make_shared<AudioCodecAdapter>(name);  // 适配层（新版）
            } else {
                codec = std::make_shared<AudioCodec>(name);         // 原生插件（旧版）
            }
            break;
    }
    return codec;
}
```

## 关键行号锚点速查

| 描述 | 文件 | 行号 |
|------|------|------|
| CodecStatus 枚举 | audio_codec_server.h | 38-46 |
| Create() 入口 | audio_codec_server.cpp | 68-125 |
| InitByName | audio_codec_server.cpp | 130-137 |
| InitByMime | audio_codec_server.cpp | 140-155 |
| Configure 状态推进 | audio_codec_server.cpp | 160-173 |
| Start 状态推进 | audio_codec_server.cpp | 185-198 |
| Stop 状态推进 | audio_codec_server.cpp | 201-218 |
| Flush/NotifyEos | audio_codec_server.cpp | 217-249 |
| Reset/Release | audio_codec_server.cpp | 251-275 |
| 工厂分发逻辑 | audio_codec_factory.cpp | 38-54 |
| GetCodecNameArrayByMime | audio_codec_factory.cpp | 29-35 |
| 四种 SetCallback | audio_codec_server.h | 66-69 |

## 影响范围

- **音频编解码入口**：所有音频 encode/decode 操作经 AudioCodecServer
- **七状态机调试关键**：音频无输出时先查 status_ 是否正确推进到 RUNNING
- **API_VERSION 分发**：API_VERSION_10 用 AudioCodecAdapter（推荐），旧版 API_VERSION_11+ 用原生 AudioCodec
- **无 Surface 简化路径**：音频不需要 Surface 模式，比视频 CodecServer 更简单