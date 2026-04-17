id: MEM-ARCH-AVCODEC-009
title: 硬件 vs 软件 Codec 区分与切换机制
type: architecture_fact
scope: [AVCodec, Hardware, Vendor, CodecList]
status: approved
confidence: high
summary: >
  AVCodec 通过 CapabilityData.isVendor 和 AVCodecInfo 的三个方法区分硬件/软件/厂商实现：
  IsHardwareAccelerated()（是否硬件加速）/ IsSoftwareOnly()（是否纯软件）/ IsVendor()（是否厂商提供）。
  CapabilityData.isVendor = true 表示该 Codec 由厂商（硬件）实现，false 表示纯软件实现。
  能力查询入口：AVCodecListFactory::CreateAVCodecList() → FindDecoder/FindEncoder(format) →
  GetCapability(mime, isEncoder, category) → CapabilityData。
  应用层通过创建 Codec 时指定 codec name 来选择使用硬件还是软件 Codec。
  注意：isVendor 和 IsSoftwareOnly 有细微区别——IsVendor 表示由厂商提供，IsSoftwareOnly 表示纯软件，
  但两者之间可能存在"厂商提供但非硬件加速"的情况。
why_it_matters:
 - 三方应用接入：接入时需要确认设备支持硬件 Codec 还是软件 Codec，按需选择
 - 问题定位：性能问题（视频卡顿/编码慢）需要确认是否使用了硬件 Codec
 - 新需求开发：指定 Codec 类型时需理解 FindDecoder 返回的是厂商 Codec 还是软件 Codec
 - 安全场景：AVCodecInfo.IsSecure() 可判断是否支持 DRM 硬件保护（isSecure 字段）
evidence:
 - kind: code
   ref: interfaces/inner_api/native/avcodec_info.h
   anchor: AVCodecInfo 硬件判断三方法
   note: |
     IsHardwareAccelerated() - 是否硬件加速
     IsSoftwareOnly() - 是否纯软件实现
     IsVendor() - 是否由厂商提供
     IsSecure() - 是否支持硬件DRM保护
 - kind: code
   ref: interfaces/inner_api/native/avcodec_info.h
   anchor: CapabilityData.isVendor + isSecure
   note: |
     CapabilityData.isVendor（bool）- true=厂商/硬件，false=纯软件
     CapabilityData.isSecure（bool）- 是否支持DRM硬件保护
     CapabilityData.maxInstance - 最大实例数（硬件通常限制更严）
 - kind: code
   ref: interfaces/inner_api/native/avcodec_info.h
   anchor: CapabilityData 能力字段
   note: |
     bitrate/width/height/frameRate 等规格限制字段
     pixFormat（像素格式）/ profileLevelsMap（H.264/H.265 profile）
     sampleRate（音频采样率）/ channels（声道数）
 - kind: code
   ref: interfaces/inner_api/native/avcodec_list.h
   anchor: AVCodecList 能力查询API
   note: |
     FindDecoder(format) / FindEncoder(format) - 按MIME格式查找Codec name
     GetCapability(mime, isEncoder, category) - 获取具体Codec的能力
     GetCapabilityList(codecType) - 按类型获取所有Codec能力列表
 - kind: code
   ref: interfaces/inner_api/native/avcodec_codec_name.h
   anchor: CodecName命名规范
   note: |
     OH.Media.Codec.Encoder.Audio.Vendor.AAC - 厂商（硬件）AAC编码器
     命名规范可反映Vendor vs Software区分
related:
 - MEM-ARCH-AVCODEC-001
 - MEM-ARCH-AVCODEC-006
 - P2b（能力查询API）
 - FAQ-SCENE2-001
owner: 耀耀
review:
  owner: 耀耀
  approved_at: "2026-04-17"
  change_policy: update_on_code_change
update_trigger: code_change
created_at: "2026-04-17"
updated_at: "2026-04-17"
