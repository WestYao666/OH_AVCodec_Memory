id: MEM-ARCH-AVCODEC-010
title: Codec 实例生命周期管理
type: architecture_fact
scope: [AVCodec, Lifecycle, CoreAPI]
status: approved
confidence: high
summary: >
  AVCodec 实例生命周期分为两条独立路径（视频解码器 vs 音频编解码器），但总体流程一致：
  CreateByName(name) → Configure() → Start() → 编解码循环 → Stop() → Release()。
  视频解码器：CreateByName → Configure(format) → Start() → QueueInputBuffer() →
  GetOutputBuffer()/ReleaseOutputBuffer() 循环 → Flush()/Stop() → Release()。
  音频编解码器：CreateByName(name) → Configure(meta) → Start() →
  ProcessInputBufferInner()（自动回调）→ ReleaseOutputBuffer() → Stop() → Release()。
  注意：Configure 必须在 Start 之前调用；Release 后实例不可再用；Stop 后可重新 Start。
  Flush 会清空输入输出 buffer，但实例配置保持不变。
why_it_matters:
 - 新需求开发：理解生命周期才能正确管理 Codec 实例资源，避免内存泄漏或 use-after-release
 - 问题定位：实例状态混乱（Stop 后又 QueueInputBuffer）是最常见的崩溃原因之一
 - 性能分析：Configure 阶段的参数（分辨率/帧率）决定了硬件加速是否生效
 - 资源管理：CreateByName 每次创建新实例，需配对 Release；重复 Configure 会覆盖之前状态
evidence:
 - kind: code
   ref: interfaces/inner_api/native/avcodec_video_decoder.h
   anchor: 视频解码器生命周期方法
   note: |
     Configure(format) - 配置视频格式（宽/高/像素格式）
     Start() / Stop() / Flush() / Release()
     QueueInputBuffer() - 送入压缩数据
     GetOutputBuffer() / ReleaseOutputBuffer() - 获取/释放解码输出
     GetOutputFormat() - 获取实际输出格式（配置后）
 - kind: code
   ref: interfaces/inner_api/native/avcodec_video_encoder.h
   anchor: 视频编码器生命周期
   note: |
     Configure(format) / Start() / Stop() / Flush() / Release()
     GetInputBuffer() - 获取输入 buffer（编码前填充）
     QueueInputBuffer() - 送入编码后的数据
     NotifyEndOfStream() - 通知编码器输入结束
 - kind: code
   ref: interfaces/inner_api/native/avcodec_audio_codec.h
   anchor: 音频Codec生命周期
   note: |
     CreateByName(name) / Configure(meta) / Start() / Stop() / Flush() / Release()
     ProcessInputBufferInner() - 音频内部回调，不需要手动 QueueInputBuffer
     ReleaseOutputBuffer() - 释放输出buffer
 - kind: code
   ref: interfaces/inner_api/native/avcodec_video_decoder.h
   anchor: CreateByName工厂方法
   note: |
     CreateByName(name) - 按codec name创建解码器实例
     两种重载：只返回decoder / 同时输出format+decoder
     codec name 通过 AVCodecList.FindDecoder(format) 获取
 - kind: code
   ref: interfaces/inner_api/native/avcodec_audio_codec.h
   anchor: ProcessInputBufferInner回调
   note: |
     ProcessInputBufferInner(isTriggeredByOutPort, isFlushed, bufferStatus)
     音频Codec内部自动触发，不暴露给应用层
     内部处理输入buffer的管理和输出buffer的回调
related:
 - MEM-ARCH-AVCODEC-001
 - MEM-ARCH-AVCODEC-009
 - MEM-ARCH-AVCODEC-006
 - P2a（interfaces/kits C API）
 - FAQ-SCENE4-001
owner: 耀耀
review:
  owner: 耀耀
  approved_at: "2026-04-17"
  change_policy: update_on_code_change
update_trigger: code_change
created_at: "2026-04-17"
updated_at: "2026-04-17"
