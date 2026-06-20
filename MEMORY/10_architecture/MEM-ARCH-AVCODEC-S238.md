id: MEM-ARCH-AVCODEC-S238
title: codec_utils——Scale RAII/四路格式映射表/WriteSurfaceData/ColorSpace/TranslateRotation
type: architecture_fact
scope: [AVCodec, codec_utils, Format, ColorSpace, Scale]
status: pending_approved
confidence: high
summary: >
  codec_utils 是 AVCodec 视频处理的核心工具模块，提供五大能力：
  1) Scale 类：ffmpeg swscale RAII 封装（shared_ptr<SwsContext>）
  2) 四路格式映射表：pixelFormat/colorPrimaries/transFunc/matrix
  3) WriteSurfaceData：Surface → AVMemory 的写入（含 stride 分支）
  4) ColorSpace：4参数转 CM_ColorSpaceInfo + HDR metadata 提取
  5) TranslateSurfaceRotation：VideoRotation → GraphicTransformType
  6) 验证函数：IsValidPixelFormat / IsValidScaleType / IsValidRotation
  7) WriteBufferData：Buffer → AVMemory 的写入（含 stride 分支）
  8) AVStrError：ffmpeg 错误码转 string 封装
why_it_matters:
 - 视频解码输出 Surface 时必须经过 WriteSurfaceData 做 stride 对齐
 - Scale 是贯穿编解码全流程的 RAII 资源管理标杆
 - ColorSpace 映射表是 HDR 支持的基石（PQ/HLG/BT2020）
 - TranslateSurfaceRotation 是 VideoRotation 到 GraphicLayer 的唯一桥梁
evidence:
 - kind: code
   ref: codec_utils.h
   anchor: 行23-34
   note: ScalePara 结构体定义（src/dst宽高/格式/对齐）
 - kind: code
   ref: codec_utils.h
   anchor: 行36-42
   note: Scale 类声明，swsCtx_ 为 shared_ptr<SwsContext> RAII 封装
 - kind: code
   ref: codec_utils.h
   anchor: 行44-49
   note: SurfaceInfo 结构体（stride/fence/scaleData/scaleLineSize）
 - kind: code
   ref: codec_utils.h
   anchor: 行58
   note: TranslateSurfaceFormat 声明（VideoPixelFormat → GraphicPixelFormat）
 - kind: code
   ref: codec_utils.h
   anchor: 行60-61
   note: 双向 pixelFormat 转换函数声明（FFmpeg ↔ VideoPixelFormat）
 - kind: code
   ref: codec_utils.h
   anchor: 行63
   note: TranslateSurfaceRotation 声明（VideoRotation → GraphicTransformType）
 - kind: code
   ref: codec_utils.h
   anchor: 行65-68
   note: ConvertVideoFrame 两个重载（AVFrame版 和 原始指针版）
 - kind: code
   ref: codec_utils.h
   anchor: 行70-71
   note: WriteSurfaceData 和 WriteBufferData 声明
 - kind: code
   ref: codec_utils.h
   anchor: 行73-74
   note: ColorSpaceInfo 转换 + HDR metadata 提取声明
 - kind: code
   ref: codec_utils.h
   anchor: 行80-83
   note: IsYuvFormat / IsRgbFormat / IsValidPixelFormat 等验证函数声明
 - kind: code
   ref: codec_utils.cpp
   anchor: 行21-26
   note: 常量定义：INDEX_ARRAY=2, WAIT_FENCE_MS=1000, DOUBLE=2
 - kind: code
   ref: codec_utils.cpp
   anchor: 行28-32
   note: g_pixelFormatMap：VideoPixelFormat → AVPixelFormat（4条映射）
 - kind: code
   ref: codec_utils.cpp
   anchor: 行34-39
   note: g_colorPrimariesMap：ColorPrimary → CM_ColorPrimaries（6条映射）
 - kind: code
   ref: codec_utils.cpp
   anchor: 行41-47
   note: g_transFuncMap：TransferCharacteristic → CM_TransFunc（8条映射，含PQ/HLG）
 - kind: code
   ref: codec_utils.cpp
   anchor: 行49-53
   note: g_matrixMap：MatrixCoefficient → CM_Matrix（5条映射，含ICTCP）
 - kind: code
   ref: codec_utils.cpp
   anchor: 行60-67
   note: IsValidPixelFormat：范围[YUVI420, RGBA]且排除SURFACE_FORMAT
 - kind: code
   ref: codec_utils.cpp
   anchor: 行69-73
   note: IsValidScaleType：仅接受 SCALE_TO_WINDOW 或 SCALE_CROP
 - kind: code
   ref: codec_utils.cpp
   anchor: 行75-81
   note: IsValidRotation：仅接受 0/90/180/270 四种旋转值
 - kind: code
   ref: codec_utils.cpp
   anchor: 行83-93
   note: ConvertVideoFrame(AVFrame重载)：lazy初始化Scale，调用scale->Convert
 - kind: code
   ref: codec_utils.cpp
   anchor: 行95-105
   note: ConvertVideoFrame(原始指针重载)：同上，参数更底层
 - kind: code
   ref: codec_utils.cpp
   anchor: 行107-121
   note: MemWritePlaneDataStride：按stride逐行写内存，处理不等长行
 - kind: code
   ref: codec_utils.cpp
   anchor: 行123-152
   note: WriteYuvDataStride：YUV stride写入，含YUVI420三平面和NV12/NV21单UV平面分支
 - kind: code
   ref: codec_utils.cpp
   anchor: 行154-168
   note: WriteRgbDataStride：RGB stride写入，逐行不等长复制
 - kind: code
   ref: codec_utils.cpp
   anchor: 行170-196
   note: WriteYuvData：YUV直接写入（无stride），按ySize/uvSize计算frameSize
 - kind: code
   ref: codec_utils.cpp
   anchor: 行198-207
   note: WriteRgbData：RGB直接写入（无stride）
 - kind: code
   ref: codec_utils.cpp
   anchor: 行209-247
   note: WriteSurfaceData：核心分发函数，wait fence → 判断stride差异 → 路由到Yuv/Rgb的Stride或Data版本
 - kind: code
   ref: codec_utils.cpp
   anchor: 行249-278
   note: WriteBufferData：Buffer写入分发，width作为stride参数，其余同WriteSurfaceData
 - kind: code
   ref: codec_utils.cpp
   anchor: 行280-286
   note: AVStrError：av_strerror封装，返回std::string
 - kind: code
   ref: codec_utils.cpp
   anchor: 行288-305
   note: TranslateSurfaceRotation：rotation映射（90→270, 180→180, 270→90, default→NONE）
 - kind: code
   ref: codec_utils.cpp
   anchor: 行307-319
   note: TranslateSurfaceFormat：VideoPixelFormat → GraphicPixelFormat（4种格式映射）
 - kind: code
   ref: codec_utils.cpp
   anchor: 行321-333
   note: ConvertPixelFormatFromFFmpeg：反向查g_pixelFormatMap，找不到返回UNKNOWN
 - kind: code
   ref: codec_utils.cpp
   anchor: 行335-347
   note: ConvertPixelFormatToFFmpeg：正向查g_pixelFormatMap，找不到返回AV_PIX_FMT_NONE
 - kind: code
   ref: codec_utils.cpp
   anchor: 行349-374
   note: ConvertParamsToColorSpaceInfo：4参数验证 → 查三张映射表 → 填充CM_ColorSpaceInfo
 - kind: code
   ref: codec_utils.cpp
   anchor: 行376-390
   note: GetMetaDataTypeByTransFunc：PQ→CM_VIDEO_HDR10, HLG→CM_VIDEO_HLG, else→NONE
 - kind: code
   ref: codec_utils.cpp
   anchor: 行392-399
   note: IsYuvFormat：YUVI420 || NV12 || NV21
 - kind: code
   ref: codec_utils.cpp
   anchor: 行401-404
   note: IsRgbFormat：仅 RGBA
 - kind: code
   ref: codec_utils.cpp
   anchor: 行406-437
   note: Scale::Init：sws_getContext → shared_ptr<SwsContext> RAII → av_image_alloc → lineSize校验
 - kind: code
   ref: codec_utils.cpp
   anchor: 行439-449
   note: Scale::Convert：sws_scale封装，返回AVCS_ERR_OK或AVCS_ERR_UNKNOWN
related:
 - MEM-ARCH-AVCODEC-001
 - MEM-ARCH-AVCODEC-005
owner: 耀耀
review:
  owner: 耀耀
  change_policy: update_on_code_change
update_trigger: code_change
created_at: "2026-06-20"
updated_at: "2026-06-20"
