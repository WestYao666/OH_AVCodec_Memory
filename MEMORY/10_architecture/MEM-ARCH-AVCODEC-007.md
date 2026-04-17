id: MEM-ARCH-AVCODEC-007
title: Demuxer 插件架构与容器格式支持
type: architecture_fact
scope: [AVCodec, Demuxer, Plugin, Container]
status: approved
confidence: high
summary: >
  AVCodec 解封装（demuxer）采用插件架构，接口定义在 interfaces/plugin/demuxer_plugin.h，
  目前有两类插件：MPEG4DemuxerPlugin（自研，支持 mp4/m4a 等）和 FFmpegDemuxerPlugin（复用 FFmpeg，
  支持 mkv/webm/flv/mp3 等几乎所有常见格式）。
  DemuxerPluginManager 负责插件生命周期管理，TypeFinder 负责从数据流中嗅探格式类型（按文件头魔数匹配）。
  完整数据流：DataSource → TypeFinder（嗅探格式）→ DemuxerPluginManager（路由到对应插件） →
  DemuxerPlugin.ReadSample() → Track（音/视频轨） → Sample（压缩数据单元）。
  关键数据结构：MediaInfo（媒体元信息）、TrackType（TRACK_VIDEO/AUDIO/SUBTITLE）。
why_it_matters:
 - 三方应用接入：接入新格式时需要注册对应 DemuxerPlugin，新增格式依赖 FFmpegDemuxerPlugin 时无需修改本仓代码
 - 问题定位：解封装问题首先确定是否为 FFmpeg 插件处理（通过 FindMediaType 判断）
 - 新需求开发：新增自研格式插件需遵循 DemuxerPlugin 接口，实现 SetDataSource/GetMediaInfo/SelectTrack/ReadSample 等
 - 性能分析：FFmpegDemuxerPlugin 复用 FFmpeg，能力覆盖广；MPEG4DemuxerPlugin 为轻量自研，mp4/m4a 场景性能更优
evidence:
 - kind: code
   ref: interfaces/plugin/demuxer_plugin.h
   anchor: DemuxerPlugin 接口定义
   note: |
     DemuxerPlugin 基类继承 PluginBase，定义纯虚接口：
     SetDataSource / GetMediaInfo / GetUserMeta / SelectTrack / UnselectTrack / ReadSample / SeekToTime
     CachePressureCallback 用于缓存压力回调
 - kind: code
   ref: services/media_engine/plugins/demuxer/mpeg4_demuxer/mpeg4_demuxer_plugin.h
   anchor: MPEG4DemuxerPlugin 实现
   note: |
     自研 MPEG4 解封装插件，继承 DemuxerPlugin。
     关键方法：SetDataSource / GetMediaInfo / SelectTrack / ReadSampleData
     依赖 mpeg4_box_parser.cpp（ISOBMFF box 解析）
 - kind: code
   ref: services/media_engine/plugins/demuxer/ffmpeg_demuxer/ffmpeg_demuxer_plugin.h
   anchor: FFmpegDemuxerPlugin 实现
   note: |
     复用 FFmpeg 的解封装插件，覆盖 mkv/webm/flv/mp3 等几乎所有 FFmpeg 支持格式。
     实现 FFmpeg 私有成员：mp4FirstKeyFrameIdx_ 等 mp4 格式特殊处理
 - kind: code
   ref: services/media_engine/modules/demuxer/demuxer_plugin_manager.h
   anchor: DemuxerPluginManager + TrackType
   note: |
     TrackType: TRACK_VIDEO(0) / TRACK_AUDIO(1) / TRACK_SUBTITLE(2) / TRACK_INVALID
     负责插件路由、Track 管理和 Sample 数据分发
 - kind: code
   ref: services/media_engine/modules/demuxer/type_finder.h
   anchor: TypeFinder::FindMediaType
   note: |
     按文件头魔数嗅探格式，FindMediaType() 返回格式字符串（mp4/mkv等）
     数据源通过 DataSourceImpl 封装 BaseStreamDemuxer，支持 offset+size 随机读取
 - kind: code
   ref: services/media_engine/modules/demuxer/demuxer_plugin_manager.h
   anchor: DataSourceImpl::ReadAt
   note: |
     DataSourceImpl 实现 DataSource 接口，封装 BaseStreamDemuxer 的 ReadAt 方法
     提供 Seekable 查询（可跳转/不可跳转）和媒体数据大小查询
related:
 - MEM-ARCH-AVCODEC-001
 - MEM-ARCH-AVCODEC-003
 - MEM-ARCH-AVCODEC-006
 - FAQ-SCENE2-002
owner: 耀耀
review:
  owner: 耀耀
  approved_at: "2026-04-17"
  change_policy: update_on_code_change
update_trigger: code_change
created_at: "2026-04-17"
updated_at: "2026-04-17"
