---
status: draft
mem_id: MEM-ARCH-AVCODEC-S92
title: "MediaCodec 核心引擎架构——CodecState 十二态机与 Plugins::DataCallback 驱动机制"
scope: [AVCodec, MediaCodec, CodecState, StateMachine, Plugins::DataCallback, Lifecycle, BufferQueue, Surface]
evidence_sources:
  - "services/media_engine/modules/media_codec/media_codec.h(35-75,90-260)"
  - "services/media_engine/modules/media_codec/media_codec.cpp(1-200,223-370)"
核心发现：
- MediaCodec (1266行) 是 AVCodec 模块的核心引擎类，位于 `services/media_engine/modules/media_codec/`，继承 `std::enable_shared_from_this` 与 `Plugins::DataCallback` 双接口
- CodecState 十二态机：稳定态(UNINITIALIZED/INITIALIZED/CONFIGURED/PREPARED/RUNNING/FLUSHED/END_OF_STREAM) + 过渡态(INITIALIZING/STARTING/STOPPING/FLUSHING/RESUMING/RELEASING)，使用 `std::atomic<CodecState>` 实现线程安全状态管理
- 生命周期七步曲：Init(by mime/by name) → Configure → Prepare → Start → Stop → Release；Configure前只能设置Callback/OutputSurface/BufferQueue，Start后进入RUNNING态
- Plugins::DataCallback 接口用于 buffer 出队/入队回调（OnBufferAvailable），驱动 ProcessInputBufferInner 消费输入缓冲区
- 双回调体系：CodecCallback（视频错误+输出） / AudioBaseCodecCallback（音频错误+输出+格式变化），通过 SetCodecCallback 注入
- Surface/Buffer 双模式：SetOutputSurface（Surface模式） vs SetOutputBufferQueue（Buffer模式）+ GetInputBufferQueue 获取输入队列
- Configure 状态校验：`state_ == CodecState::INITIALIZED` 才可 Configure；Prepare 校验：`state_ == CONFIGURED`
关联记忆：S83（Native C API 总览，CAPI 层面封装了 MediaCodec）/S55（模块间回调链路）/S39（VideoDecoder 三层架构）
---