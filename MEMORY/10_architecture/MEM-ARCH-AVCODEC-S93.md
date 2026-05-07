---
id: MEM-ARCH-AVCODEC-S93
title: "StreamParserManager 插件化视频流解析架构——HEVC/AVC/VVC AnnexB/HVCC 转换与 HDR 元数据提取"
scope: [AVCodec, StreamParser, StreamParserManager, VideoStreamType, AnnexB, HVCC, HDRVivid, HDR10Plus, dlopen, PluginLoader, VideoEncoder, FFMpegAdapter, MuxerPlugin]
status: draft
created_by: builder-agent
created_at: "2026-05-07T11:45:00+08:00"
evidence_sources:
  - "services/media_engine/plugins/common/stream_parser.h:1-120"
  - "services/media_engine/plugins/ffmpeg_adapter/common/stream_parser_manager.h:1-73"
  - "services/media_engine/plugins/ffmpeg_adapter/common/stream_parser_manager.cpp:1-227"
核心发现：
- StreamParserManager（227行cpp+73行h）是 FFmpeg 适配器层中**视频流解析的插件化架构**，通过 dlopen 动态加载独立 .so 库（libav_codec_hevc_parser.z.so），实现 HEVC/AVC/VVC 三类视频流的统一抽象
- StreamParser（plugins/common/stream_parser.h）是纯虚基类，定义 18 个虚方法，涵盖三大功能域：
  (1) ExtraData 解析：ParseExtraData / ParseAnnexbExtraData，从 SPS/PPS/VPS 中提取编码参数
  (2) AnnexB↔HVCC 转换：ConvertExtraDataToAnnexb / ConvertPacketToAnnexb，AnnexB（start code 0x000001/0x00000001）与 ITU-T 格式（4字节长度前缀）互转
  (3) HDR 元数据提取：IsHdrVivid() / IsHdr10Plus() / IsHdr() + GetColorPrimaries/Transfer/Matrix + Profile/Level + ChromaLocation
- VideoStreamType 枚举：HEVC(0) / VVC(1) / AVC(2)，决定加载哪个 .so 插件
- dlopen 工厂模式：StreamParserManager::LoadPluginFile + CheckSymbol 查找 CreateStreamParser/DestroyStreamParser 符号；CreateFuncMap_/DestroyFuncMap_ 按 VideoStreamType 缓存函数指针
- 生命周期：Init(VideoStreamType) 加载 .so 并注册工厂函数 → Create() 调用 createFuncMap_[type]() 创建实例 → 析构自动调用 destroyFuncMap_[type]()
- HevcParseFormat 结构体（HevcParseFormat）聚合 HDR Vivid/HDR10/HDR 标志、色彩范围、主色/传输特性/矩阵系数、Profile IDC / Level IDC、ChromaLocation、画面尺寸等 12 个字段
- GetMaxReorderPic()：返回最大重排序帧数（B帧相关），用于编码器参考帧列表管理
- 在 FFmpegMuxerPlugin / MPEG4MuxerPlugin / FLVMuxerPlugin 中使用：muxer 写入时需要将编码器输出的 HVCC 格式NAL单元转换为 AnnexB 格式，或反过来
关联记忆：S40（FFmpegMuxerPlugin）/S74（MPEG4MuxerPlugin 写时构建）/S65（MediaMuxer Track管理）/S42（VideoEncoder 核心架构）/S39（VideoDecoder 三层架构）
keywords: [StreamParserManager, StreamParser, dlopen, HEVC, VVC, AVC, AnnexB, HVCC, HDRVivid, HDR10Plus, ExtraData, SPS, PPS, VPS, Profile, Level, ChromaLocation, FFMpegAdapter, MuxerPlugin, 动态加载, 插件化]
associations:
  - S40
  - S42
  - S65
  - S74
  - S39
notes:
  - 实现库（.so）未开源，仅暴露 stream_parser.h 接口定义；dlopen 加载路径固定为 "libav_codec_hevc_parser.z.so"
  - 目前 HEVC_LIB_PATH 硬编码，未来可能扩展为多 codec 各自独立 .so
  - 该组件是 FFmpeg 适配器（ffmpeg_adapter/common）与具体视频编码器之间的"解析中间层"，属于较为底层的插件基础设施
