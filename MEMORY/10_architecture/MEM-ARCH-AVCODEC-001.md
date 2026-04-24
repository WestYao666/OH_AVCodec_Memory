---
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
 # === 原有目录级证据 ===
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

 # === 新增代码级证据（Builder 2026-04-25）===
 - kind: code
   ref: services/engine/base/include/codecbase.h:31
   anchor: CodecBase 抽象基类
   evidence: |
     class CodecBase {  // 行 31：所有编解码插件的基类
         virtual sptr<Surface> CreateInputSurface();       // 行 50
         virtual int32_t SetInputSurface(sptr<Surface>);   // 行 51
         virtual int32_t SetOutputSurface(sptr<Surface>);  // 行 52
         virtual int32_t CreateCodecByName(const std::string &name);  // 行 81
         virtual int32_t Init(Media::Meta &callerInfo);    // 行 87
     };
     enum class CodecState : int32_t { ... };              // 行 35
     enum class CodecErrorType : int32_t { ... };          // 行 54
 - kind: code
   ref: services/services/codec/server/video/codec_server.h:42
   anchor: CodecServer 服务实例
   evidence: |
     class CodecServer : public std::enable_shared_from_this<CodecServer> {  // 行 42
         int32_t InitByName(const std::string &codecName, Meta &callerInfo);  // 行 129
         int32_t InitByMime(AVCodecType type, const std::string &codecMime, Meta &callerInfo);  // 行 130
         bool isSurfaceMode_ = false;  // 行 162：区分 Surface/Buffer 模式
     };
 - kind: code
   ref: services/media_engine/modules/media_codec/media_codec.h:90
   anchor: MediaCodec 核心实现类
   evidence: |
     class MediaCodec : public std::enable_shared_from_this<MediaCodec>,
                        public Plugins::DataCallback {  // 行 90
         int32_t SetOutputSurface(sptr<Surface> surface);                    // 行 108
         sptr<AVBufferQueueProducer> GetOutputBufferQueueProducer();         // 行 116
     };
 - kind: code
   ref: services/engine/codec/video/video_codec_loader.cpp
   anchor: VideoCodecLoader 插件加载器基类
   evidence: |
     VideoCodecLoader::Init() 执行 dlopen(libPath_, RTLD_LAZY) 加载 .z.so
     video_codec_loader.cpp 定义软件/硬件编解码器通用加载逻辑
 - kind: code
   ref: services/engine/codec/video/
   anchor: 专用 Loader 插件清单
   evidence: |
     hevc_decoder_loader.cpp     → libhevc_decoder.z.so
     avc_encoder_loader.cpp      → libavc_encoder.z.so
     vp8_decoder_loader.cpp      → libvp8_decoder.z.so
     vp9_decoder_loader.cpp      → libvp9_decoder.z.so
     av1_decoder_loader.cpp      → libav1_decoder.z.so
     fcodec_loader.cpp           → libfcodec.z.so（软件编解码）
     hcodec_loader.cpp            → libhcodec.z.so（硬件编解码）
 - kind: code
   ref: services/media_engine/modules/
   anchor: media_engine/modules/ 子模块
   evidence: |
     demuxer/        → 解封装（mp4/mkv/hls/dash）
     muxer/          → 封装
     media_codec/    → 编解码核心（MediaCodec 类，行 90）
     source/         → 媒体源
     sink/           → 媒体输出（audio_sink/video_sink/subtitle_sink）
     post_processor/ → 后处理（VideoPostProcessor/SuperResolution）
     pts_index_conversion/ → PTS 索引转换
 - kind: code
   ref: interfaces/kits/c/native_avcodec_*.h
   anchor: Native C API 清单
   evidence: |
     native_avcodec_base.h              → 公共类型和错误码
     native_avcodec_videodecoder.h      → OH_VideoDecoder_CreateByMime/Name
     native_avcodec_videoencoder.h      → OH_VideoEncoder_CreateByMime/Name
     native_avcodec_audiodecoder.h      → OH_AudioDecoder_CreateByMime/Name
     native_avcodec_audioencoder.h      → OH_AudioEncoder_CreateByMime/Name
     native_avdemuxer.h                 → OH_Demuxer_Create
     native_avmuxer.h                   → OH_Muxer_Create
     native_avsource.h                   → OHSource_Create
     native_avcapability.h              → OH_AVCodec_GetCapability
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
updated_at: "2026-04-25"
last_enhanced_at: "2026-04-25"
last_enhanced_by: builder-agent
enhancement_note: >
  新增 8 条代码级证据，从目录级补充到函数/类/行号级。
  关键类：CodecBase(codecbase.h:31)、CodecServer(codec_server.h:42)、
  MediaCodec(media_codec.h:90)、VideoCodecLoader(video_codec_loader.cpp)；
  补充 7 个专用 Loader 插件清单；补充 8 个 Native C API 头文件。
