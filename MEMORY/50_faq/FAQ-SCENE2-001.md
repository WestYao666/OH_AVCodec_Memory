id: FAQ-SCENE2-001
title: 三方应用接入 FAQ — Top10（三方应用问题解答）
type: faq
scope: [FAQ, Integration, ThirdParty]
status: approved
confidence: high
summary: >
  整理 AVCodec 三方应用接入最常见的 10 个问题及答案，基于真实 C API 文档和代码结构。
  覆盖：能力查询 / 错误码解读 / 格式配置 / 解封装 / 编码参数 / Surface 模式 / DRM / 性能优化。
why_it_matters:
 - 三方应用接入必备，降低接入摩擦
 - 四类场景之二（第三方应用）的核心记忆产品
 - 错误码是排查接入问题的第一线索
evidence:
 - kind: code
   ref: interfaces/inner_api/native/avcodec_list.h
   anchor: AVCodecList.FindDecoder/FindEncoder
   note: 能力查询 API
 - kind: code
   ref: interfaces/inner_api/native/avcodec_info.h
   anchor: CapabilityData.isVendor/isSecure
   note: 硬件Codec vs 软件Codec的区分
 - kind: code
   ref: interfaces/kits/c/native_avcodec_base.h
   anchor: OH_AVFormat API + OH_MD_KEY_* 键名
   note: Format参数配置体系
 - kind: code
   ref: interfaces/kits/c/native_avdemuxer.h
   anchor: 解封装API
   note: ReadSample + GetMediaInfo
 - kind: doc
   ref: interfaces/kits/c/native_avcodec_videodecoder.h
   anchor: SetSurface模式
   note: Surface直出模式（零拷贝）
related:
 - MEM-ARCH-AVCODEC-011
 - MEM-ARCH-AVCODEC-012
 - MEM-ARCH-AVCODEC-013
 - MEM-DEVFLOW-005
owner: 耀耀
review:
  owner: 耀耀
  approved_at: "2026-04-17"
  change_policy: update_on_code_change
update_trigger: code_change
created_at: "2026-04-17"
updated_at: "2026-04-17"

answers:
  - id: FAQ-SCENE2-001-Q1
    question: 如何查询设备支持哪些Codec？
    answer: |
      1. 创建 AVCodecList：AVCodecListFactory::CreateAVCodecList()
      2. 按 MIME 查 Codec name：FindDecoder("video/avc") / FindEncoder("audio/mp4a-latm")
      3. 获取能力详情：GetCapability(mime, isEncoder, category) → CapabilityData
      4. 检查关键字段：isVendor=true（硬件）/ isSecure=true（DRM）/ maxInstance / bitrate上限
      注意：FindDecoder 返回空说明设备不支持该格式，需要降级或提示用户。
    best_practice: 接入时必须先 QueryCapability，不支持则降级提示

  - id: FAQ-SCENE2-001-Q2
    question: Codec创建失败（FindDecoder返回空）如何处理？
    answer: |
      原因：设备不支持该 MIME 格式。
      排查步骤：(1) 确认 MIME 拼写正确（video/avc 而非 video/h264）；(2) 查 AVCodecList.GetCapabilityList() 获取设备所有支持格式；(3) 尝试其他格式（如 video/hevc → video/avc）。
      降级方案：点播场景用软编（IsSoftwareOnly=true），直播场景提示用户设备不支持。
    best_practice: 接入时按优先级尝试多个 Codec name，不要 hardcode 单一 Codec

  - id: FAQ-SCENE2-001-Q3
    question: Configure 失败如何定位？
    answer: |
      返回 AV_ERR_INVALID_VAL（参数无效）或 AV_ERR_OPERATE_NOT_PERMIT（状态不对）。
      常见原因：(1) 分辨率超规格（超 maxWidth/maxHeight）；(2) 帧率超规格；(3) 像素格式不支持；(4) Configure 前未 SetCallback；(5) Start 后再 Configure。
      排查方法：打印 Format 所有键值确认参数合法；对比 CapabilityData 的 maxWidth/maxHeight/frameRate。
    best_practice: Configure 前先打印 Format 内容；优先验证分辨率/帧率在规格内

  - id: FAQ-SCENE2-001-Q4
    question: 解封装后没有视频/音频轨道（GetMediaInfo返回空）？
    answer: |
      原因：(1) 容器格式不支持（FFmpegDemuxerPlugin 支持 mkv/webm，但 MPEG4DemuxerPlugin 不支持所有 mp4）；(2) 文件损坏；(3) DataSource 不可读。
      排查：先用 TypeFinder.FindMediaType() 确认格式；检查 ReadSample 是否返回正常数据；用 ffprobe 或 MediaInfo 独立验证文件完整性。
    best_practice: 接解封装前用 TypeFinder 确认格式；异常文件提前预检

  - id: FAQ-SCENE2-001-Q5
    question: 视频编码器输出的像素格式（PIXEL_FORMAT）有哪些选择？
    answer: |
      支持的像素格式（OH_AVPixelFormat）：YUV_NV12 / YUV_NV21 / YUV_SEMIPLANAR_NV12 / YUV_SEMIPLANAR_NV21 / RGBA / YUV_YU12（YV12）等。
      推荐：硬件 Codec 通常只支持 NV12/NV21；软编可支持更多格式。
      配置方式：OH_AVFormat_SetInt32(format, OH_MD_KEY_PIXEL_FORMAT, OH_PIXEL_NV12)
    best_practice: 优先用 NV12（硬件兼容性最好）；不同相机/显示设备可能要求不同格式

  - id: FAQ-SCENE2-001-Q6
    question: Surface 模式 vs 内存模式，哪个性能更好？
    answer: |
      Surface 模式性能更优（零拷贝）：编码输入直接从 Surface 取，绕过内存拷贝，适合 Camera 预览 → 编码场景。
      内存模式：应用自己管理 buffer（OH_AVMemory / OH_AVBuffer），更灵活但多一次拷贝。
      选择建议：Camera → 编码用 Surface；文件 → 编码用内存；解码输出到 Surface 用 SetSurface。
    best_practice: 实时视频流（Camera/屏幕录制）优先 Surface；离线文件处理用内存模式

  - id: FAQ-SCENE2-001-Q7
    question: DRM 加密内容如何解密播放？
    answer: |
      检查 CapabilityData.isSecure：true 表示支持 DRM 硬件保护。
      配置解密：SetDecryptionConfig(codec, decryptConfig)
      支持的 DRM 方案：Common Encryption (CENC)，通过 native_cencinfo.h 接口配置。
      注意：DRM 解密必须在 CreateByName 后立即 Configure 前完成配置，且解密内容仅能在安全环境中处理。
    best_practice: 播放 DRM 内容前必须 QueryCapability 确认 isSecure=true

  - id: FAQ-SCENE2-001-Q8
    question: 编码码率控制（BITRATE_MODE）如何选择？
    answer: |
      三种模式（OH_VideoEncodeBitrateMode）：CBR(0) 固定码率 / VBR(1) 可变码率 / UBR(2) 无上限码率。
      直播推荐：CBR（码率稳定，网络波动小）；点播推荐：VBR（质量优先，文件更小）；高质量场景：UBR。
      配置：OH_AVFormat_SetInt32(format, OH_MD_KEY_VIDEO_ENCODE_BITRATE_MODE, OH_VideoEncodeBitrateMode_CBR)
      注意：H.264 / H.265 / AAC 各有自己的 profile/level 上限，超出会被硬件拒绝。
    best_practice: 直播用 CBR，点播用 VBR，注意 profile/level 规格限制

  - id: FAQ-SCENE2-001-Q9
    question: 解码画面freeze（FREEZE）如何排查？
    answer: |
      先查 HiSysEvent：HiSysEvent FAULT_TYPE_FREEZE 事件中 MODULE 和 FAULTTYPE 字段。
      常见原因：(1) 输入数据不完整（关键帧缺失）；(2) 帧率配置不匹配；(3) Surface 缓冲区满导致丢帧；(4) 硬件 Codec 超时（AVCodecXCollie 默认10秒）。
      排查步骤：确认输入流完整（用 ffprobe 检查关键帧）；检查 FRAME_RATE 配置是否与实际匹配；用 RenderOutputBufferAtTime 控制渲染节奏。
    best_practice: 排查时先看 HiSysEvent FAULT 事件中的 MODULE 字段定位问题模块

  - id: FAQ-SCENE2-001-Q10
    question: 如何动态调整编码参数（码率/帧率）？
    answer: |
      在 Start 后使用 SetParameter(format) 动态调整：
      - 码率：SetInt32(OH_MD_KEY_BITRATE, newBitrate)
      - 帧率：SetFloat(OH_MD_KEY_FRAME_RATE, newFps)
      - QP：SetInt32(OH_MD_KEY_VIDEO_ENCODER_QP_AVERAGE, newQp)
      注意：调整后可能有 1-2 帧延迟生效；频繁调整可能导致码率抖动。
    best_practice: 直播中调整码率建议以 GOP 为单位（每1-2秒调整一次），避免过于频繁
