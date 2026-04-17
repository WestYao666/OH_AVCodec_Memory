id: MEM-ARCH-AVCODEC-011
title: interfaces/kits C API 契约总览
type: architecture_fact
scope: [API, C, Integration, AVCodecKit]
status: approved
confidence: high
summary: >
  AVCodec 对外 C API 定义在 interfaces/kits/c/ 目录下，共 10 个头文件，按功能分为 6 类：
  (1) Base(native_avcodec_base.h)：OH_AVCodec 句柄、OH_AVCodecCallback 回调（OnError/OnStreamChanged/
  OnNeedInputBuffer/OnNewOutputBuffer）、OH_AVMemory/OHA VBuffer 内存管理、OH_AVFormat 参数封装。
  (2) VideoDecoder(native_avcodec_videodecoder.h)：CreateByMime/CreateByName → SetCallback/RegisterCallback →
  Configure → Prepare → Start → PushInputData/QueryOutputBuffer → GetOutputBuffer → RenderOutputData/FreeOutputData
  → Stop → Destroy，支持 Surface 直出模式（SetSurface）和内存模式两种输出路径。
  (3) VideoEncoder(native_avcodec_videoencoder.h)：Create → SetCallback → Configure → Start →
  GetInputBuffer/PushInputData → QueryOutputBuffer → Stop → Destroy，支持 DRM 加密（SetDecryptionConfig）。
  (4) AudioCodec(native_avcodec_audiocodec.h / audiocodec_*.h)：音频编解码器 C API，流程同视频。
  (5) Demuxer(native_avdemuxer.h)：Create → SetCallback → Prepare → ReadSample → GetMediaInfo →
  SelectTrack/UnselectTrack → Destroy。
  (6) Muxer(native_avmuxer.h)：Create → AddTrack/AddTrackWithMime → Start → WriteSample → Stop → Destroy。
  (7) Capability(native_avcapability.h)：QueryVideoDecoderCapability/QueryVideoEncoderCapability/
  QueryAudioDecoderCapability/QueryAudioEncoderCapability，返回设备支持的 Codec 能力列表。
  所有 API 返回 OH_AVErrCode 错误码（AV_ERR_OK = 0，其余为具体错误码）。
why_it_matters:
 - 三方应用接入：必须通过这些 C API 接入，正确理解回调机制和 Buffer 管理是避免内存泄漏的关键
 - 问题定位：C API 错误码是排查接入问题的第一线索
 - 新需求开发：Native 层新增能力必须考虑 C API 是否暴露，以及 libnative_media_codecbase.so 的链接方式
 - 性能分析：Surface 模式比内存模式性能更优（省去内存拷贝），三方应优先使用 Surface
evidence:
 - kind: code
   ref: interfaces/kits/c/native_avcodec_base.h
   anchor: 核心类型与回调
   note: |
     OH_AVCodec（codec实例句柄）+ OH_AVCodecCallback（4类回调）
     OH_AVMemory（内存buffer）/ OH_AVBuffer（高效buffer）
     OH_AVFormat（键值对参数封装）
     OH_AVErrCode 错误码体系
 - kind: code
   ref: interfaces/kits/c/native_avcodec_videodecoder.h
   anchor: 视频解码器API完整列表
   note: |
     CreateByMime/CreateByName + SetCallback/RegisterCallback + Configure + Prepare
     Start/Stop/Flush/Reset + GetOutputDescription/SetParameter
     PushInputData/PushInputBuffer + QueryOutputBuffer/GetOutputBuffer
     RenderOutputData/RenderOutputBufferAtTime/FreeOutputData/FreeOutputBuffer
     SetSurface（Surface直出模式） + IsValid + SetDecryptionConfig
 - kind: code
   ref: interfaces/kits/c/native_avdemuxer.h
   anchor: 解封装C API
   note: |
     CreateByMime/CreateByName + SetCallback + SelectTrack/UnselectTrack
     ReadSample + GetMediaInfo + GetInputFormat + GetOutputFormat
 - kind: code
   ref: interfaces/kits/c/native_avmuxer.h
   anchor: 封装C API
   note: |
     Create + AddTrack/AddTrackWithMime + Start + WriteSample + Stop + Destroy
 - kind: code
   ref: interfaces/kits/c/native_avcapability.h
   anchor: Capability查询API
   note: |
     QueryVideoDecoderCapability / QueryVideoEncoderCapability
     QueryAudioDecoderCapability / QueryAudioEncoderCapability
     返回 Format（包含支持格式、能力参数）
 - kind: code
   ref: interfaces/kits/c/native_avcodec_base.h
   anchor: 错误码体系
   note: |
     AV_ERR_OK(0) / AV_ERR_NO_MEMORY / AV_ERR_OPERATE_NOT_PERMITTED /
     AV_ERR_INVALID_VAL / AV_ERR_UNKNOWN / AV_ERR_TIMEOUT 等
related:
 - MEM-ARCH-AVCODEC-001
 - MEM-ARCH-AVCODEC-009
 - MEM-ARCH-AVCODEC-010
 - FAQ-SCENE2-001
 - FAQ-SCENE2-002
owner: 耀耀
review:
  owner: 耀耀
  approved_at: "2026-04-17"
  change_policy: update_on_code_change
update_trigger: code_change
created_at: "2026-04-17"
updated_at: "2026-04-17"
