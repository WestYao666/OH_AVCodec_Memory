---
id: MEM-ARCH-AVCODEC-S134
title: "FFmpegDemuxerPlugin 高级特性——HDR元数据解析/BitstreamFilter/PTS索引转换/分片缓冲/缓存压力控制"
scope: [AVCodec, MediaEngine, Demuxer, FFmpeg, Plugin, HDR_VIVID, HDR10, BitstreamFilter, AnnexB, PTS, IndexConvert, ReadAhead, CachePressure, MultiStreamParser, ReferenceParser, RMSeek]
关联主题: [S68(FFmpegDemuxerPlugin总览), S76(FFmpegDemuxerPlugin管线), S41(DemuxerFilter), S75(MediaDemuxer六组件), S58(MPEG4BoxParser)]
status: draft
created_at: "2026-05-14T17:50:00+08:00"
created_by: builder-agent
source_repo: /home/west/OH_AVCodec
source_root: services/media_engine/plugins/demuxer/ffmpeg_demuxer
evidence_version: local_mirror
---

# MEM-ARCH-AVCODEC-S134: FFmpegDemuxerPlugin 高级特性

## 1. 模块定位

FFmpegDemuxerPlugin (ffmpeg_demuxer_plugin.cpp/h) 是 AVCodec 解封装插件体系中功能最丰富的实现，4129行主文件 + 6个协作文件：

| 文件 | 行数 | 职责 |
|------|------|------|
| ffmpeg_demuxer_plugin.cpp/h | 4129行 | 主插件：解封装引擎、线程管理、HDR解析 |
| ffmpeg_demuxer_thread.cpp | 891行 | ReadLoop 异步读线程 |
| ffmpeg_format_helper.cpp | 1367行 | 轨道元数据解析（视频/音频/字幕） |
| ffmpeg_utils.cpp | 444行 | 工具函数 |
| avpacket_wrapper.cpp/h | 109行 | AVPacket 包装器 |
| avpacket_memory.cpp/h | 77行 | 共享内存管理 |
| ffmpeg_reference_parser.cpp | 488行 | I帧位置解析（dlopen插件） |

本记忆（S134）聚焦 S68/S76 未覆盖的高级特性：
HDR元数据解析 / BitstreamFilter注入 / PTSIndex双向转换 / 分片缓冲管理 / 缓存压力控制 / RM特殊处理

---

## 2. HDR元数据解析——六层判断逻辑

Evidence: ffmpeg_demuxer_plugin.h:64~79 — GetMediaInfo 注释文档

FFmpegDemuxerPlugin 的 HDR 判断采用六层递进逻辑：

[E1] line 64-66: 仅适用 H.265 流（COLOR_PRIMARIES/COLOR_MATRIX 非 BT2020 → NONE）
[E2] line 67-70: ITU_T_T35 PREFIX_SEI 解析
  - 国家码 0xB5/0x26 + provider_code=0x04 + oriented_code=0x05 → HDR_VIVID
  - 国家码 0xB5 + provider_code=0x3C → HDR10
[E3] line 71-72: 无 T35 时检查文件内特殊 Box
  - CUVV box → HDR_VIVID
  - DVCC/DVVC/DVH1 box → HDR10
[E4] line 73-75: 检查 COLOR_TRANSFER_CHARACTERISTIC
  - transfer=PQ → HDR10
  - transfer=HLG → HLG
[E5] line 76-77: 以上均不满足 → NONE（SDR 或非标准 HDR）

相关代码路径:
- ParseHvccBoxInfo() — 解析 HEVC CodecConfig box 提取 profile/tier/level
- ParseHdrTypeInfo() — 调用 HevcParseFormat 判断 HDR 类型
- ParseVideoHdrAndColorMetadata() — 解析 ColorBox / HdrType 元数据

---

## 3. BitstreamFilter 注入——AVC/HEVC/VVC 三路 AnnexB 转换

Evidence: ffmpeg_demuxer_plugin.cpp

FFmpeg 输出 MP4/FLV 时视频流是 AVCC 格式（length-prefixed NALU），播放管线需要 AnnexB 格式（起始码 0x00000001）。FFmpegDemuxerPlugin 通过 BitstreamFilter 注入实现转换：

[E2] line ~380: InitBitStreamContext() 初始化 BSF
    std::map<uint32_t, std::shared_ptr<AVBSFContext>> avbsfContexts_ {};

[E3] line ~390: ConvertAvcToAnnexb(AVPacket& pkt) 
    - 查找 avbsfContexts_[trackId]
    - 调用 av_bitstream_filter_filter() 执行转换
    - 原始 AVCC → AnnexB 起始码

[E4] line ~420: ConvertHevcToAnnexb(AVPacket& pkt)
    - 处理 HEVC VCL NALU (PREFIX_SEI/NAL_CODEC_SPLICING)
    - HEVC VPS/SPS/PPS 携入型 AVCC

[E5] line ~435: ConvertVvcToAnnexb(AVPacket& pkt)
    - 支持 VVC (H.266) 流

插件名称路由:
- H.264: h264_mp4toannexb — 提取 extradata 配置 BSF
- HEVC: hevc_mp4toannexb — 同理
- 注入时机: ConvertPacketToAnnexbWithParser() 在 ReadLoop 中对每个 packet 执行

---

## 4. PTS Index 双向转换——堆排序 + 二分搜索混合算法

Evidence: ffmpeg_demuxer_plugin.h:270~290 — IndexAndPTSConvertMode 枚举

FFmpegDemuxerPlugin 在解封装层实现了不依赖外部 PTS 转换器的本地索引：

[E6] enum IndexAndPTSConvertMode : unsigned int {
    GET_FIRST_PTS,           // 获取首帧 PTS
    INDEX_TO_RELATIVEPTS,     // Index → 相对 PTS（堆排序逆查）
    RELATIVEPTS_TO_INDEX,     // 相对 PTS → Index（二分搜索）
    GET_ALL_FRAME_PTS,       // 全量帧 PTS 遍历
};

[E7] line 285: absolutePTSIndexZero_ = INT64_MAX  // 首帧基准点
[E8] line 286: indexToRelativePTSMaxHeap_ // 逆查用最大堆（priority_queue）
[E9] line 288: relativePTSToIndexPosition_ // 二分搜索游标

转换算法:
- IndexToRelativePTSProcess() — 堆排序逆查：O(log n)
- RelativePTSToIndexProcess() — 二分搜索：O(log n)
- PTSAndIndexConvertSwitchProcess() — 根据 mode 分发
- 调用链: PTSAndIndexConvertSttsAndCttsProcess() 读取 STTS/CTTS 表

---

## 5. 分片缓冲管理——ReadAhead + SOFT/HARD 双阈值

Evidence: ffmpeg_demuxer_plugin.h:48~53 — 阈值常量

[E10] line 48: constexpr uint64_t FILE_SIZE_THRESHOLD = 1ULL * 1024 * 1024 * 1024; // 1GB
[E11] line 50: constexpr uint32_t SOFT_LIMIT_MULTIPLIER = 2;
[E12] line 51: constexpr uint32_t HARD_LIMIT_MULTIPLIER = 4;
[E13] line 52: constexpr uint32_t SOFT_LIMIT_MIN = 20;
[E14] line 53: constexpr uint32_t HARD_LIMIT_MIN = 50;

动态计算:
- CalculateSoftLimit(trackCount) = max(SOFT_LIMIT_MIN, trackCount x SOFT_LIMIT_MULTIPLIER)
- CalculateHardLimit(trackCount) = max(HARD_LIMIT_MIN, trackCount x HARD_LIMIT_MULTIPLIER)

ReadAhead 缓冲策略 (ffmpeg_demuxer_thread.cpp:895 FFmpegReadLoop):
[E15] line ~900: 软限制触发 → 降速读取（等待 cacheReady）
[E16] line ~910: 硬限制触发 → 丢帧（丢弃 oldest packet）
[E17] line ~920: CHECK_CACHE_DATA_LIMIT 调用 CheckCacheDataLimit()

---

## 6. 缓存压力控制——CachePressureCallback + per-track 限流

Evidence: ffmpeg_demuxer_plugin.h:120~125 — 缓存压力控制接口

[E18] line 120: using CachePressureCallback = DemuxerPlugin::CachePressureCallback;
[E19] line 121: Status SetCachePressureCallback(CachePressureCallback cb) override;
[E20] line 122: Status SetTrackCacheLimit(uint32_t trackId, uint32_t limitBytes, uint32_t windowMs = 500) override;

[E21] line 125: std::unordered_map<uint32_t, uint32_t> trackCacheLimitMap_; // per-track bytes limit
[E22] line 126: std::unordered_map<uint32_t, uint32_t> trackThrottleWindowMs_;
[E23] line 127: std::unordered_map<uint32_t, int64_t> trackLastNotifyMs_;
[E24] line 128: std::mutex cachePressureMutex_;

触发逻辑 MaybeNotifyCachePressure():
- 当 track 的 cache 字节数超过 trackCacheLimitMap_[trackId] 时触发回调
- 受 windowMs 控制，限流：每 windowMs 最多通知一次

---

## 7. 视频首帧解析——三阶段探测 (SoftLimit/HardLimit/ProbeExit)

Evidence: ffmpeg_demuxer_plugin.h:300~330 — 有限帧探测逻辑

FFmpegDemuxerPlugin 在 SetDataSource 后会提前探测视频首帧用于 Seek 校准：

[E25] enum class ProbeMode : uint32_t {
    FIRST_FRAME = 0,    // 阶段1：探测到首帧即可
    FULL_PARSE = 1,    // 阶段2：全量解析（如 FLV）
    LIMITED = 2,       // 阶段3：受限探测（按 SOFT/HARD LIMIT）
};

[E26] line 306: Status ParseVideoFirstFrames() 
    -> ParseVideoFirstFramesFull() / ParseVideoFirstFramesLimited()
[E27] line 307: MarkPendingTracksForFirstFrame() — 标记待补充首帧的轨道
[E28] line 308: SupplementFirstFrameIfPending() — 满足条件时补充首帧

退出条件 CheckLimitedProbeExitConditions():
- softLimit 内探测到视频轨+音频轨 → 退出
- 达到 hardLimit → 强制退出

---

## 8. MultiStreamParserManager——多轨流解析器（dlopen插件）

Evidence: ffmpeg_demuxer_plugin.h:150

[E29] line 150: std::shared_ptr<MultiStreamParserManager> streamParsers_ {nullptr};

MultiStreamParserManager 负责：
- 多轨视频流解析（支持分层编码 GOP 感知）
- HDR 检测 (GetFrameLayerInfo/GopLayerInfo/IFramePos)
- AnnexB ↔ HVCC 转换器管理
- 与 ReferenceParserManager 配合实现 I 帧精确定位

---

## 9. ReferenceParserManager——I帧精确定位（dlopen插件）

Evidence: ffmpeg_demuxer_plugin.h:155~165

[E30] line 155: std::shared_ptr<ReferenceParserManager> referenceParser_{nullptr};
[E31] line 156: std::atomic<int64_t> pendingSeekMsTime_ = -1;  // Seek 时间戳
[E32] line 157: std::vector<uint32_t> IFramePos_;              // I帧位置表
[E33] line 158: std::list<uint32_t> processingIFrame_;         // 处理中的 GOP
[E34] line 160: Status ParserRefInfo() override;                // GOP 信息查询

GOP 感知 Seek:
- ParserRefInit() — 初始化参考解析器（dlopen .so 插件）
- ParserRefInfoLoop() — 遍历 packet 构建 GOP 索引
- SelectProGopId() — 选择最优 GOP（用于关键帧 Seek）

---

## 10. RM 流特殊处理——AVSeekFrameLock + RMMediaSeek

Evidence: ffmpeg_demuxer_plugin.h:420~440

[E35] line 420: enum class RMMediaSeek : uint32_t {
    RM_SEEK_NO = 0,
    RM_SEEK_KEY_FRAME = 1,   // Seek 到最近关键帧
    RM_SEEK_NEXT_SYNC = 2,   // Seek 到下一关键帧
};

[E36] line 425: int AVSeekFrameLock(int idx, int64_t timestamp, int flags);
[E37] line 430: int RMSeekToStart();  // RM 特殊起始 Seek
[E38] line 435: Status SeekToRmKeyFrame(int trackIndex, int64_t seekTime, 
                                        int64_t ffTime, SeekMode mode, int64_t &realSeekTime);

RM 流特性:
- RM 格式不支持标准 av_seek_frame，需用 avio_seek() 精确控制
- IsUseFirstFrameDts() — 判断是否使用首帧 DTS 作为基准
- UpdateParserGopId() — 边 Seek 边更新 GOP 位置

---

## 11. DFX 链路追踪——TrackDfxInfo + DumpPacketInfo

Evidence: ffmpeg_demuxer_plugin.h:360~385 — DFX 结构体

[E39] struct TrackDfxInfo {
    int frameIndex = 0;           // 每轨帧计数
    int64_t lastPts {AV_NOPTS_VALUE};
    int64_t lastPos {0};
    int64_t lastDuration {0};
    bool dumpFirstInfo = false;
};

[E40] line 365: enum Stage : int32_t {
    FIRST_READ = 0,
    FILE_END   = 1,
};

[E41] line 366: void DumpPacketInfo(int32_t trackId, Stage stage);
[E42] line 367: static std::atomic<int> readatIndex_;   // ReadAt 序列号
[E43] line 368: int avpacketIndex_ {0};                  // AVPacket 序列号

Dump 模式:
[E44] enum DumpMode : unsigned long {
    DUMP_NONE = 0,
    DUMP_READAT_INPUT = 0b001,    // 记录 ReadAt 输入
    DUMP_AVPACKET_OUTPUT = 0b010, // 记录 AVPacket 输出
    DUMP_AVBUFFER_OUTPUT = 0b100, // 记录 AVBuffer 输出
};

---

## 12. 与已有记忆的关联

| 已有记忆 | 关联点 |
|---------|--------|
| S68/S76 | S134 在其基础上补充 HDR/BitstreamFilter/PTS转换/分片缓冲/缓存压力/RM处理 |
| S41 DemuxerFilter | S134 是 Filter 层调用的底层引擎，DemuxerFilter ↔ FFmpegDemuxerPlugin |
| S75 MediaDemuxer 六组件 | MediaDemuxer 管理 FFmpegDemuxerPlugin（作为 DemuxerPlugin 实例） |
| S58 MPEG4BoxParser | 两者并列：MPEG4DemuxerPlugin 用自研 Box 解析，FFmpegDemuxerPlugin 用 libavformat |
| S97 DemuxerPluginManager | 管理 FFmpegDemuxerPlugin 的 Track 路由映射 |
| S101 StreamDemuxer | PullData 数据源最终流向 FFmpegDemuxerPlugin 的 ReadLoop |

---

## 摘要

S134 揭示 FFmpegDemuxerPlugin 作为 AVCodec 解封装插件体系中功能最丰富的实现，相比 S68/S76 的总览层面，S134 聚焦以下高级特性：

1. HDR 六层判断 — ITU_T_T35 / CUVV/DVCC box / COLOR_TRANSFER 三路判断
2. BitstreamFilter 注入 — h264/hevc/vvc 三路 AnnexB 转换（AVCC → 起始码）
3. PTSIndex 双向转换 — 堆排序 + 二分搜索本地实现（不依赖外部转换器）
4. 分片缓冲 ReadAhead — SOFT/HARD 双阈值动态降速/丢帧
5. 缓存压力控制 — per-track 限流 + 回调通知
6. 视频首帧三阶段探测 — SoftLimit/HardLimit/ProbeExit
7. MultiStreamParserManager — 多轨 GOP 感知解析（dlopen 插件）
8. ReferenceParserManager — I帧精确定位（dlopen 插件）
9. RM 流特殊 Seek — AVSeekFrameLock + RMSeekToStart
10. DFX 链路追踪 — TrackDfxInfo + 三态 DumpMode
