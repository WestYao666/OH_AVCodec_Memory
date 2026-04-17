id: MEM-DEVFLOW-006
title: 问题修复回归流程——单测 + 故障事件回溯
type: dev_flow
scope: [Process, Test, Regression, DFX]
status: approved
confidence: high
summary: >
  AVCodec 问题修复的回归验证分三层：
  (1) 单测层：test/moduletest/ 下按模块独立（audio_decoder/audio_encoder/vcodec/demuxer/muxer/capability），
  每个子目录有独立 BUILD.gn，按 codec 类型再分（hwdecoder/swdecoder/encoder 等）。
  单测通过 `hb build av_codec -t` 执行，按 GN group 逐个跑；
  (2) 故障回溯层：修复后通过 HiSysEvent FAULT 事件的 MODULE + FAULTTYPE + MSG 字段精确定位根因，
  SetFaultEvent() 在各 Filter（DemuxerFilter / MuxerFilter / AudioEncoderFilter / VideoDecoderAdapter 等）
  中调用 avcodec_sysevent.cpp 的函数写入系统事件；
  (3) 卡顿检测层：AVCodecXCollie 的 SetTimer 看门狗机制记录超时栈（`avcodec_xcollie.cpp`），
  配合 HiLog 按 LOG_DOMAIN 过滤精确定位是哪一步卡住。
  回归标准：修复后单测全绿 + HiSysEvent 中对应 FAULT 事件不再出现 + 回归场景跑通。
why_it_matters:
 - 问题定位：SetFaultEvent 遍布各 Filter，是故障定位的第一入口
 - 回归验证：修复后必须跑对应模块的单测，不能只靠功能测试
 - 流程规范：清晰的三层验证体系避免同类问题回归
 - 卡顿排查：AVCodecXCollie 超时回溯是解码 freeze 问题定位神器
evidence:
 - kind: code
   ref: test/moduletest/
   anchor: 单测目录结构
   note: 6大模块：audio_decoder/audio_encoder/vcodec/demuxer/muxer/capability；vcodec下按codec类型再分
 - kind: code
   ref: test/moduletest/vcodec/hwdecoder/BUILD.gn
   anchor: 单测GN target规范
   note: import("//build/test.gni") + import("//.../config.gni")；MEDIA_ROOT_DIR定义路径；module_output_path输出路径
 - kind: code
   ref: services/media_engine/filters/video_decoder_adapter.cpp
   anchor: SetFaultEvent + avcodec_sysevent.h
   note: #include "avcodec_sysevent.h" + SetFaultEvent() 写入 DFX 事件
 - kind: code
   ref: services/media_engine/filters/demuxer_filter.cpp
   anchor: SetFaultEvent调用点
   note: #include "avcodec_sysevent.h" + SetFaultEvent("DemuxerFilter::OnLinked error", ret)
 - kind: code
   ref: services/media_engine/filters/muxer_filter.cpp
   anchor: SetFaultEvent调用点
   note: SetFaultEvent("MuxerFilter::DoStart error", (int32_t)ret)
 - kind: code
   ref: services/media_engine/filters/audio_encoder_filter.cpp
   anchor: AudioEncoderFilter SetFaultEvent
   note: SetFaultEvent("AudioEncoderFilter::Configure error", ret)
 - kind: code
   ref: services/dfx/avcodec_xcollie.cpp
   anchor: AVCodecXCollie SetTimer超时回溯
   note: SetTimer 设置看门狗，超时触发回调记录栈；用于检测 Codec 接口调用卡死
 - kind: build
   ref: hb build av_codec -t
   anchor: 单测编译命令
   note: --skip-download 避免重复拉取；按模块跑对应 target
related:
 - MEM-DEVFLOW-002
 - MEM-ARCH-AVCODEC-005
 - MEM-DEVFLOW-003
 - FAQ-SCENE4-001
 - FAQ-SCENE4-002
owner: 耀耀
review:
  owner: 耀耀
  approved_at: "2026-04-17"
  change_policy: update_on_code_change
update_trigger: code_change
created_at: "2026-04-17"
updated_at: "2026-04-17"
