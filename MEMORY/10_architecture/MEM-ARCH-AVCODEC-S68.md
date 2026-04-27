---
id: MEM-ARCH-AVCODEC-S68
title: FFmpegDemuxerPlugin 音视频解封装插件——libavformat 全格式支持与 av_read_frame 管线
type: architecture_fact
scope: [AVCodec, MediaEngine, Demuxer, FFmpeg, Plugin, DemuxerPlugin, libavformat, avformat_open_input, av_read_frame, av_seek_frame, avformat_find_stream_info, BitstreamFilter, FLV, MKV, MPEGTS, MPEGPS, FileType, AVPacket, ReadSample, SeekTo, DRM, GetMediaInfo]
status: draft
confidence: medium
created_by: builder-agent
created_at: "2026-04-27T09:06:00+08:00"
service_scenario: 新需求开发/问题定位
summary: >
  S68 梳理 FFmpegDemuxerPlugin（4129 行），它是基于 FFmpeg libavformat 的通用解封装插件，
  与 MPEG4DemuxerPlugin（S58）并列，共同为 DemuxerFilter(S41) 提供解封装能力。
  FFmpegDemuxerPlugin 通过 avformat_open_input 打开容器，av_read_frame 读取压缩帧，
  av_seek_frame 定位，支持 20+ 容器格式（FLV/MKV/MPEGTS/MPEGPS/RM/WMV/OGG/MP3/AMR/AAC/FLAC/WAV/AVI/VOB/DTS/AC3 等）。
  FFmpegFormatHelper（1367 行）负责 FFmpeg 类型到内部类型的双向转换。
  FFmpegDemuxerThread（895 行）实现 AVReadPacket 回调函数，实现自定义 IO 读取。
  关键特性：BitstreamFilter 注入（h264_mp4toannexb/hevc_mp4toannexb）、ReadAhead 软/硬缓冲区限制、
  LIVE_FLV 快速探测（100KB×2）、HEIF 格式检测、MultiStreamParserManager 多轨解析。
why_it_matters:
 - 20+ 容器格式支持：播放管线覆盖绝大多数常见音视频格式
 - FFmpeg 生态：持续从 FFmpeg 获取格式支持和 bug 修复
 - 与 MPEG4DemuxerPlugin 分工：FFmpegDemuxerPlugin 负责通用格式，MPEG4DemuxerPlugin 专注 MP4/MOV 细节
 - BitstreamFilter：H.264/HEVC 从 MP4 格式到 AnnexB 格式的自动转换
 - ReadAhead 机制：防止解码器吃不饱或撑死
evidence:
 - kind: code
   ref: services/media_engine/plugins/demuxer/ffmpeg_demuxer/ffmpeg_demuxer_plugin.h
   anchor: Line 50-148: FFmpegDemuxerPlugin 类定义（DemuxerPlugin 子类）
   note: |
     Line 73-76: Reset/Start/Stop/Flush 生命周期管理
     Line 96: GetMediaInfo 获取媒体信息
     Line 100: SeekTo 定位
     Line 101-102: ReadSample 读压缩帧（同步/超时版本）
     Line 103: ReadSampleZeroCopy 零拷贝读
     Line 105: GetNextSampleSize 查询下一帧大小
     Line 108: GetDrmInfo DRM 信息查询
     Line 124-134: 多模式 Seek（SeekToKeyFrame/SeekToFrameByDts/SeekToRmKeyFrame）
     Line 143: CachePressureCallback 缓存压力回调
     Line 148: SetReadTimeoutForInitSeek 初始化阶段超时控制
 - kind: code
   ref: services/media_engine/plugins/demuxer/ffmpeg_demuxer/ffmpeg_demuxer_plugin.cpp
   anchor: Line 62-66: 文件大小阈值常量
   note: |
     Line 62: FILE_SIZE_THRESHOLD = 1GB（软/硬缓冲区阈值分界）
     Line 63-66: SOFT_LIMIT_MULTIPLIER=2 / HARD_LIMIT_MULTIPLIER=4（软/硬缓冲区乘数）
     SOFT_LIMIT_MIN=20 / HARD_LIMIT_MIN=50（最小缓冲帧数）
 - kind: code
   ref: services/media_engine/plugins/demuxer/ffmpeg_demuxer/ffmpeg_demuxer_plugin.cpp
   anchor: Line 168-173: BitstreamFilter 与 StreamParser 表
   note: |
     Line 168: g_bitstreamFilterMap（AVCodecID → BitstreamFilter 名）
     h264_mp4toannexb / hevc_mp4toannexb / mpeg4_ipmp / mpeg4_als
     Line 173: g_streamParserMap（AVCodecID → VideoStreamType）
     HEVC→HEVC / H264→H264 / VPX→VPX / MPEG4→MPEG4 / SVQ3→SVQ3
 - kind: code
   ref: services/media_engine/plugins/demuxer/ffmpeg_demuxer/ffmpeg_demuxer_plugin.cpp
   anchor: Line 188-214: g_streamCheckFileTypeVec / g_fileSkipGetMinTsPktInfo 格式特殊处理向量
   note: |
     Line 192-195: g_streamCheckFileTypeVec（MPEGTS/MPEGPS/VOB 需额外流信息检查）
     Line 198-200: g_fileContainSkipInfo（OGG/MP3 跳过获取最小时间戳）
     Line 204-210: g_fileSkipGetMinTsPktInfo（FLV/MKV/WMV/WMA/MPEGTS/MPEGPS/RM 跳过获取最小TS包信息）
 - kind: code
   ref: services/media_engine/plugins/demuxer/ffmpeg_demuxer/ffmpeg_demuxer_plugin.cpp
   anchor: Line 329-371: ConvertFlagsToFFmpeg Seek 标志转换（FLV+ H264 特殊处理）
   note: |
     Line 329: ConvertFlagsToFFmpeg() Seek 标志到 FFmpeg av_seek_frame flags 的转换
     Line 368-369: FLV + H264 EOS frame 特殊处理：FLV_EOS_TAG_SIZE=4
     Line 371: AVSEEK_FLAG_BACKWARD 用于 FLV+ H264 避免 seek 到 EOS 帧
 - kind: code
   ref: services/media_engine/plugins/demuxer/ffmpeg_demuxer/ffmpeg_demuxer_plugin.cpp
   anchor: Line 549-558: GetProbeSize 获取探测大小
   note: |
     Line 549: GetProbeSize(int32_t &offset, int32_t &size) 入口
     返回 formatContext_->probesize（FFmpeg 探测缓冲区大小）
 - kind: code
   ref: services/media_engine/plugins/demuxer/ffmpeg_demuxer/ffmpeg_demuxer_plugin.cpp
   anchor: Line 1487-1515: ParseHeader 容器格式探测
   note: |
     Line 1492: avformat_open_input(&formatContext, nullptr, pluginImpl.get(), options)
     FFmpeg 打开输入格式上下文
     Line 1508: LIVE_FLV_PROBE_SIZE = 100KB×2（Live FLV 快速探测）
     Line 1512: avformat_find_stream_info 探测所有流的编解码信息
 - kind: code
   ref: services/media_engine/plugins/demuxer/ffmpeg_demuxer/ffmpeg_demuxer_plugin.cpp
   anchor: Line 1607-1647: SetDataSource 初始化入口
   note: |
     Line 1607: SetDataSource(source, configs) 入口
     创建 IOContext，设置 DataSource 回调
     Line 1612-1617: InitAVFormatContext 分配 formatContext
     Line 1625: av_find_input_format 查找指定格式的输入插件（如 FLV）
     Line 1638: fileType_ = FFmpegFormatHelper::GetFileTypeByName(*formatContext_)
 - kind: code
   ref: services/media_engine/plugins/demuxer/ffmpeg_demuxer/ffmpeg_demuxer_plugin.cpp
   anchor: Line 1795-1835: GetMediaInfo 获取媒体信息
   note: |
     Line 1795: GetMediaInfo(MediaInfo&) 获取媒体信息（公开接口）
     Line 1835: fileType_ != FileType::FLV && !FFmpegFormatHelper::IsMpeg4File(fileType_) 时跳过
     FFmpegDemuxerPlugin 不处理 MP4/FLV 容器（由 MPEG4DemuxerPlugin 负责）
 - kind: code
   ref: services/media_engine/plugins/demuxer/ffmpeg_demuxer/ffmpeg_demuxer_plugin.cpp
   anchor: Line 2059-2090: GetDrmInfo DRM 信息获取
   note: |
     Line 2059: GetDrmInfo() 入口
     Line 2078-2084: 从流的 side data 读取 DRM 信息（AV_CODEC_ID_AES_GCM）
     DRM 信息通过 multimap<std::string, std::vector<uint8_t>> 返回
 - kind: code
   ref: services/media_engine/plugins/demuxer/ffmpeg_demuxer/ffmpeg_demuxer_plugin.cpp
   anchor: Line 2943-2983: SeekTo 定位实现
   note: |
     Line 2943: SeekTo() 主入口
     CheckSeekParams → SyncSeekThread → SelectSeekTrack → ConvertTimeToFFmpeg
     IsEnableSeekTimeCalib（启用 Seek 校准）：MPEGTS/FLV/RM/HEVC_MP4
     DoSeekInternal → av_seek_frame → AVSeekFrameLock
     Line 2978: fileType_ == FileType::RM → SeekToRmKeyFrame 特殊处理
 - kind: code
   ref: services/media_engine/plugins/demuxer/ffmpeg_demuxer/ffmpeg_demuxer_plugin.cpp
   anchor: Line 3215-3270: ReadSample 读帧实现
   note: |
     Line 3215: ReadSample() 主入口（同步模式）
     WaitForCacheReady → cacheQueue_.Front → ConvertAVPacketToSample
     cacheQueue_ 按 trackId 缓存解码前的压缩帧
     isEOS 特殊处理：SetEosSample
     ReadSampleZeroCopy（Line 103）零拷贝路径
 - kind: code
   ref: services/media_engine/plugins/demuxer/ffmpeg_demuxer/ffmpeg_demuxer_plugin.cpp
   anchor: Line 1772-1785: MultiStreamParserManager 和 ReferenceParserManager
   note: |
     Line 1772: streamParsers_ = std::make_shared<MultiStreamParserManager>()
     多轨解析管理器
     Line 1785: g_streamParserMap.at(codecId) 路由到对应解析器
     ReferenceParserManager: GOP 参考帧解析（Line 1774: referenceParser_）
     用于 SVC-TL / LTR 等参考帧结构
 - kind: code
   ref: services/media_engine/plugins/demuxer/ffmpeg_demuxer/ffmpeg_format_helper.cpp
   anchor: Line 71-215: FFmpegFormatHelper 类型转换表
   note: |
     Line 71: g_convertFfmpegPixFmt（AVPixelFormat → RawVideoPixelFormat）
     AV_PIX_FMT_YUV420P→YUV420P / NV12→NV12 / NV21→NV21 / RGBA→RGBA
     Line 78: g_convertFfmpegTrackType（AVMediaType → MediaType）
     AVMEDIA_TYPE_VIDEO→VIDEO / AVMEDIA_TYPE_AUDIO→AUDIO
     Line 188-218: g_convertFfmpegFileType（FFmpeg format name → FileType enum）
     25+ 映射：mpegts→MPEGTS / matroska,webm→MKV / flv→FLV / mpeg→MPEGPS / rm→RM 等
 - kind: code
   ref: services/media_engine/plugins/demuxer/ffmpeg_demuxer/ffmpeg_format_helper.cpp
   anchor: Line 60-65: FFmpegFormatHelper 核心静态函数
   note: |
     GetFileTypeByName(avFormatContext) → FileType 枚举
     IsMpeg4File(FileType) → bool（MPEG4/ISMV/3GP/MP4 判断）
     IsVideoType / IsAudioType / IsImageTrack
 - kind: code
   ref: services/media_engine/plugins/demuxer/ffmpeg_demuxer/ffmpeg_demuxer_thread.cpp
   anchor: Line 52-120: AVReadPacket 回调函数实现
   note: |
     Line 52: AVReadPacket(void* opaque, uint8_t* buf, int bufSize) FFmpeg IO 回调
     调用 ioContext->dataSource->ReadAt 读取数据
     重试逻辑：AV_READ_PACKET_RETRY_UPPER_LIMIT=9 / AV_READ_PACKET_NON_READ_RETRY_UPPER_LIMIT=10
     AV_READ_PACKET_SLEEP_TIME=50ms / AV_READ_PACKET_NON_READ_SLEEP_TIME=10ms
     Line 75: HandleReadOK → 更新 ioContext_.offset 和 readatIndex_
 - kind: code
   ref: services/media_engine/plugins/demuxer/ffmpeg_demuxer/avpacket_wrapper.cpp
   anchor: Line 36-109: AVPacketWrapper RAII 封装
   note: |
     AVPacketWrapper: RAII holder for AVPacket*
     构造函数分配 AVPacket 或接受外部所有权
     析构函数调用 av_packet_free()
     GetAVPacket() 返回裸指针供 FFmpeg API 使用
 - kind: code
   ref: services/media_engine/plugins/demuxer/ffmpeg_demuxer/ffmpeg_utils.cpp
   anchor: Line 25-70: FFmpeg 工具函数
   note: |
     AVStrError: FFmpeg 错误码到字符串转换
     ConvertTimeFromFFmpeg: 将 FFmpeg 时间（AVRational）转换为纳秒
     IsHvccSyncFrame / IsAnnexbSyncFrame: AnnexB / HVCC NAL 同步帧判断
     FindNalStartCode: 搜索 NAL 起始码（0x000001 / 0x00000001）
     NAL_START_CODE_SIZE=4 / START_CODE={0x00,0x00,0x01}
key_findings:
 - 'FFmpegDemuxerPlugin 覆盖 25+ 容器格式：FLV/MKV/MPEGTS/MPEGPS/RM/WMV/OGG/MP3/AMR/AAC/FLAC/WAV/AVI/VOB/DTS/AC3/CAF/APE/SRT/VTT/AIFF/AU/LRC/SAMI'
 - 'FFmpegFormatHelper: FFmpeg AVPixelFormat→RawVideoPixelFormat / AVMediaType→MediaType / format name→FileType'
 - 'BitstreamFilter 注入: h264_mp4toannexb (H.264) / hevc_mp4toannexb (HEVC) / mpeg4_ipmp / mpeg4_als'
 - 'LIVE_FLV_PROBE_SIZE=100KB×2: Live FLV 场景快速探测，避免长探测延迟'
 - 'ReadAhead 缓冲: cacheQueue_ 按 trackId 缓存，SOFT_LIMIT/HARD_LIMIT 根据文件大小和轨道数动态调整'
 - 'Seek 校准: IsEnableSeekTimeCalib 针对 MPEGTS/FLV/RM/HEVC_MP4 启用精确 Seek'
 - 'MultiStreamParserManager: 多轨解析，支持 HEVC/H264/VPX/MPEG4/SVQ3 视频流'
 - 'ReferenceParserManager: GOP 参考帧解析（SVC-TL / LTR 场景）'
 - 'HEIF 格式检测: IsHeifFormat() (Line 100) 检测 heif/heic 图像格式'
 - 'AVPacketWrapper: RAII 封装 AVPacket*，避免内存泄漏'
 - 'AVReadPacket 回调: 自定义 IO 上下文，支持 DataSource ReadAt 重试和超时'
 - 'DRM: GetDrmInfo 从流的 side data 读取 AES_GCM DRM 信息'
 - 'ReadSampleZeroCopy: 零拷贝读路径（Line 103 header 定义）'
 - 'XCollie 看门狗: GetMediaInfo / SeekTo / ReadSample 均使用 SetTimer 超时保护'
 - '与 MPEG4DemuxerPlugin 分工: FFmpegDemuxerPlugin 不处理 MP4/FLV，IsMpeg4File 时跳过'
 - '与 S41 DemuxerFilter: FFmpegDemuxerPlugin 是 DemuxerFilter 底层的解封装引擎之一'
 - '与 S58 MPEG4BoxParser: MPEG4DemuxerPlugin 使用 MPEG4BoxParser 做 MP4 box 解析，FFmpegDemuxerPlugin 用 FFmpeg'
related:
 - MEM-ARCH-AVCODEC-S41    # DemuxerFilter 上游 Filter 层封装
 - MEM-ARCH-AVCODEC-S58    # MPEG4DemuxerPlugin 与 MPEG4BoxParser（MP4/MOV 专用）
 - MEM-ARCH-AVCODEC-S37    # HTTP 流媒体源插件（HttpSourcePlugin 提供数据给 Demuxer）
 - MEM-ARCH-AVCODEC-S67    # SourcePlugin 源插件体系
 - MEM-ARCH-AVCODEC-S66    # TypeFinder 媒体类型探测（决定用哪个 Demuxer 插件）
 - MEM-ARCH-AVCODEC-S63    # DRM CENC 解密（Demuxer 输出的加密流由 CodecServer 解密）
owner: builder-agent
review:
  owner: 耀耀
  change_policy: manual_review
update_trigger: FFmpegDemuxerPlugin 新增格式支持 / BitstreamFilter 变更 / ReadAhead 缓冲策略调整
notes: |
  S68 与 S41 互补：S41 描述 DemuxerFilter（Filter 层），S68 描述 FFmpegDemuxerPlugin（插件引擎层）。
  FFmpegDemuxerPlugin 与 MPEG4DemuxerPlugin 是两个并列的 DemuxerPlugin 实现。
  FFmpegDemuxerPlugin 基于 FFmpeg libavformat，适合通用格式；
  MPEG4DemuxerPlugin 基于自研 MPEG4BoxParser，适合 MP4/MOV 精细解析（edts/ctts/avcC 等）。
  FFmpegFormatHelper（1367 行）是 FFmpeg 类型到内部类型的转换桥梁，含 25+ FileType 映射。
  FFmpegDemuxerThread（895 行）实现 AVReadPacket 回调，支持 ReadAt 重试和阻塞模式。
  AVPacketWrapper（109 行）是 RAII AVPacket 封装，防止 FFmpeg 资源泄漏。
  READ_SIZE_THRESHOLD=1GB 决定软/硬缓冲区乘数（SOFT×2 / HARD×4）。
