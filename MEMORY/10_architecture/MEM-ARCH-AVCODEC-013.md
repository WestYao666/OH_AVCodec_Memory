id: MEM-ARCH-AVCODEC-013
title: 编解码参数配置（OH_AVFormat + OH_MD_KEY 键值对体系）
type: architecture_fact
scope: [API, Configuration, Format, AVCodecKit]
status: approved
confidence: high
summary: >
  AVCodec 所有配置均通过 OH_AVFormat 键值对传入，Configure(format) / SetParameter(format) /
  GetOutputDescription() 等方法均使用 OH_AVFormat。
  OH_MD_KEY_* 键名分为 7 类：(1) 视频基础：OH_MD_KEY_WIDTH / HEIGHT / PIXEL_FORMAT / FRAME_RATE /
  ROTATION / VIDEO_TRANSFORM_TYPE；(2) 编码控制：OH_MD_KEY_BITRATE / MAX_BITRATE /
  VIDEO_ENCODE_BITRATE_MODE / I_FRAME_INTERVAL / PROFILE；(3) 音频基础：OH_MD_KEY_AUD_CHANNEL_COUNT /
  AUD_SAMPLE_RATE / AUDIO_SAMPLE_FORMAT / AUDIO_COMPRESSION_LEVEL；(4) HDR/色彩：
  OH_MD_KEY_COLOR_PRIMARIES / TRANSFER_CHARACTERISTICS / MATRIX_COEFFICIENTS /
  VIDEO_IS_HDR_VIVID；(5) 编码器Qos：OH_MD_KEY_VIDEO_ENCODER_QP_* / MSE / QUALITY /
  SQR_FACTOR；(6) 音频压缩：OH_MD_KEY_AUDIO_OBJECT_BITRATE / SOUNDBED_BITRATE / AAC_IS_ADTS / SBR；
  (7) 时间/缓冲：OH_MD_KEY_DURATION / BUFFER_DURATION / START_TIME / MAX_INPUT_SIZE /
  DECODING_TIMESTAMP。
  OH_AVFormat 通过 SetInt32 / SetString / SetFloat / GetInt32 / GetString 等API读写。
why_it_matters:
 - 新需求开发：Configure 阶段的 Format 参数决定了 Codec 行为，正确设置是关键
 - 问题定位：视频无输出/音频无声先查 FORMAT 是否与 Capability 匹配
 - 三方应用：不同场景（直播/点播/录制）需要不同的 BITRATE / FRAME_RATE 配置
 - 性能分析：VIDEO_ENCODE_BITRATE_MODE（CBR/VBR/UBR）影响码率控制策略
 - HDR 支持：OH_MD_KEY_VIDEO_IS_HDR_VIVID + COLOR_PRIMARIES 等色彩参数影响 HDR 显示效果
evidence:
 - kind: code
   ref: interfaces/kits/c/native_avcodec_base.h
   anchor: OH_MD_KEY_* 键名定义（全部）
   note: |
     视频基础：WIDTH/HEIGHT/PIXEL_FORMAT/FRAME_RATE/ROTATION/VIDEO_TRANSFORM_TYPE/RANGE_FLAG
     编码控制：BITRATE/MAX_BITRATE/VIDEO_ENCODE_BITRATE_MODE/I_FRAME_INTERVAL/PROFILE
     音频基础：AUD_CHANNEL_COUNT/AUD_SAMPLE_RATE/AUDIO_SAMPLE_FORMAT/AUDIO_COMPRESSION_LEVEL
     HDR/色彩：COLOR_PRIMARIES/TRANSFER_CHARACTERISTICS/MATRIX_COEFFICIENTS/VIDEO_IS_HDR_VIVID
     编码Qos：QP_MAX/QP_MIN/QP_AVERAGE/MSE/QUALITY/SQR_FACTOR/SETUP_HEADER
     音频压缩：AUDIO_OBJECT_BITRATE/SOUNDBED_BITRATE/AAC_IS_ADTS/SBR
     时间/缓冲：DURATION/BUFFER_DURATION/START_TIME/MAX_INPUT_SIZE/DECODING_TIMESTAMP
     其他：CODEC_CONFIG/TITLE/ARTIST/ALBUM/COPYRIGHT/LANGUAGE 等元数据
 - kind: code
   ref: interfaces/kits/c/native_avcodec_base.h
   anchor: OH_AVFormat API
   note: |
     SetInt32(format, key, value) / GetInt32(format, key, &value)
     SetString / GetString / SetFloat / GetFloat
     OH_AVErrCode OH_AVFormat_SetInt32(OH_AVFormat *format, const char *key, int32_t value)
     OH_AVErrCode OH_AVFormat_GetInt32(OH_AVFormat *format, const char *key, int32_t *value)
 - kind: code
   ref: interfaces/kits/c/native_avcodec_videodecoder.h
   anchor: Configure + GetOutputDescription
   note: Configure(format) 配置视频格式，GetOutputDescription() 获取实际输出格式（可能与输入不同）
 - kind: code
   ref: interfaces/kits/c/native_avcodec_videoencoder.h
   anchor: SetParameter 动态参数调整
   note: SetParameter(codec, format) 动态调整编码参数（如码率/帧率）
 - kind: code
   ref: interfaces/kits/c/native_avcodec_base.h
   anchor: OH_VideoEncodeBitrateMode 枚举
   note: 视频编码码率模式：CBR(0) / VBR(1) / UBR(2)
 - kind: code
   ref: interfaces/kits/c/native_avcodec_base.h
   anchor: OH_AVPixelFormat 枚举
   note: 像素格式：YUV_NV12 / YUV_NV21 / RGBA / YUV_SEMIPLANAR_NV12 / YUV_SEMIPLANAR_NV21 等
related:
 - MEM-ARCH-AVCODEC-011
 - MEM-ARCH-AVCODEC-012
 - MEM-ARCH-AVCODEC-010
 - FAQ-SCENE2-003
 - FAQ-SCENE3-005
owner: 耀耀
review:
  owner: 耀耀
  approved_at: "2026-04-17"
  change_policy: update_on_code_change
update_trigger: code_change
created_at: "2026-04-17"
updated_at: "2026-04-17"
