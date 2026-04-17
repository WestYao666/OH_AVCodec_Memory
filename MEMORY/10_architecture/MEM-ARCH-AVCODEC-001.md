id: MEM-ARCH-AVCODEC-001
title: AVCodec 模块总览
type: architecture_fact
scope: [AVCodec, Architecture]
status: approved
confidence: high
summary: >
  av_codec 部件分为 5 大层：interfaces（接口层）、services/media_engine（核心引擎）、
  services/services（IPC 封装层）、services/dfx（DFX 横切模块）、services/drm_decryptor（DRM 解密）。
  核心实现不在 services/engine/（该目录只有 base/codec/codeclist/common/factory），而在
  services/media_engine/modules/ 下分为 demuxer/muxer/media_codec/source/post_processor/sink 等模块。
  interfaces/kits/ 提供 C API（native_avcodec_*），供应用调用。
  services/dfx/ 提供统计事件（FaultEvent）和调试工具（dump/xcollie）。
why_it_matters:
 - 新人理解模块边界：不要再被 services/engine/ 误导，核心在 media_engine
 - 三方应用定位接入点：kits 层的 C API 是唯一稳定的对外接口
 - 新需求开发确定修改路径：功能在 media_engine/modules/，IPC 在 services/services/
 - 问题定位：dfx 事件是排查故障的第一线索
evidence:
 - kind: code
   ref: services/
   anchor: 顶层目录结构
   note: 发现 media_engine/dfx/drm_decryptor/services/etc 为独立目录
 - kind: code
   ref: services/engine/
   anchor: 目录列表
   note: services/engine/ 只有 base/codec/codeclist/common/factory，无 demuxer/muxer
 - kind: code
   ref: services/media_engine/
   anchor: 模块结构
   note: media_engine/modules/ 下有 demuxer/muxer/media_codec/source/post_processor/sink
 - kind: code
   ref: services/media_engine/plugins/
   anchor: 插件结构
   note: demuxer/ffmpeg_adapter/sink/source 四类插件
 - kind: code
   ref: services/dfx/
   anchor: 文件列表
   note: avcodec_sysevent.cpp 定义 FAULT_TYPE_FREEZE/CRASH/INNER_ERROR
 - kind: code
   ref: interfaces/kits/c/
   anchor: API 文件列表
   note: native_avcodec_{video,audio}{encoder,decoder}.h 等 10+ 个 C API 头文件
 - kind: doc
   ref: README_zh.md
   anchor: 模块介绍
   note: 官方描述的模块范围与实际代码结构有偏差
related:
 - MEM-ARCH-AVCODEC-002
 - MEM-DEVFLOW-001
 - FAQ-SCENE1-001
owner: 耀耀
review:
  owner: 耀耀
  approved_at: "2026-04-17"
  change_policy: update_on_code_change
update_trigger: code_change
created_at: "2026-04-17"
updated_at: "2026-04-17"
