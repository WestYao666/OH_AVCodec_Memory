id: MEM-ARCH-AVCODEC-012
title: 能力查询 API（AVCodecList）与 Codec 能力规格
type: architecture_fact
scope: [API, Capability, CodecList]
status: approved
confidence: high
summary: >
  AVCodecList 是 AVCodec 的能力查询入口，通过 AVCodecListFactory::CreateAVCodecList() 创建。
  核心方法：FindDecoder(format) / FindEncoder(format) - 按 MIME 格式字符串查找可用 Codec name；
  GetCapability(mime, isEncoder, category) - 获取指定 Codec 的详细能力规格。
  CapabilityData 包含：isVendor（硬件/厂商 vs 软件）/ isSecure（DRM 支持）/ maxInstance（最大实例数）/
  bitrate / width / height / frameRate（视频规格）/ pixFormat / sampleRate / channels（音频规格）。
  能力查询是三方应用接入的第一步：先 QueryCapability 确认设备支持，再按返回 name 创建 Codec 实例。
why_it_matters:
 - 三方应用接入：必须先查询设备能力，不支持则降级或提示用户
 - 问题定位：Codec 创建失败（FindDecoder 返回空）说明设备不支持该格式
 - 新需求开发：新增格式支持前先查 AVCodecList 确认能力边界
 - 规格判断：maxInstance / bitrate / resolution 上限决定了硬件Codec的承载能力
evidence:
 - kind: code
   ref: interfaces/inner_api/native/avcodec_list.h
   anchor: AVCodecList 核心API
   note: |
     FindDecoder(format) / FindEncoder(format) - 按MIME格式查找Codec name
     GetCapability(mime, isEncoder, category) - 获取详细能力
     GetCapabilityList(codecType) - 按类型获取所有能力
 - kind: code
   ref: interfaces/inner_api/native/avcodec_info.h
   anchor: CapabilityData 字段
   note: |
     isVendor（bool）- true=厂商/硬件，false=软件
     isSecure（bool）- 是否支持硬件DRM
     maxInstance - 最大并发实例数
     bitrate（max/min）/ width（max）/ height（max）/ frameRate（max）
     pixFormat（支持的像素格式）/ sampleRate（音频采样率）/ channels（声道数）
     profileLevelsMap - H.264/H.265 profile列表
 - kind: code
   ref: interfaces/inner_api/native/avcodec_list.h
   anchor: AVCodecListFactory
   note: AVCodecListFactory::CreateAVCodecList() - 创建能力查询实例
 - kind: doc
   ref: interfaces/kits/c/native_avcapability.h
   anchor: C API能力查询
   note: |
     QueryVideoDecoderCapability / QueryVideoEncoderCapability /
     QueryAudioDecoderCapability / QueryAudioEncoderCapability
     返回 Format 对象（键值对格式）
related:
 - MEM-ARCH-AVCODEC-009
 - MEM-ARCH-AVCODEC-011
 - MEM-ARCH-AVCODEC-001
 - FAQ-SCENE2-001
owner: 耀耀
review:
  owner: 耀耀
  approved_at: "2026-04-17"
  change_policy: update_on_code_change
update_trigger: code_change
created_at: "2026-04-17"
updated_at: "2026-04-17"
