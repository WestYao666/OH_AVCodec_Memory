id: MEM-ARCH-AVCODEC-005
title: DFX 上报链路——HiSysEvent 与故障事件函数映射
type: architecture_fact
scope: [DFX, HiSysEvent, FaultType, EventReporting]
status: approved
confidence: high
summary: >
  services/dfx/avcodec_sysevent.cpp 是 DFX 事件写入的唯一入口，共定义 10+ 个写入函数。
  这些函数分为三类：
  (1) 系统事件（HiSysEvent）：通过 HiSysEventWrite() 向系统全局日志系统上报，
      领域分为 AV_CODEC（编解码专属）和 MULTI_MEDIA（多媒体通用）；
  (2) 行为事件（BEHAVIOR）：SERVICE_START_INFO / CODEC_START_INFO / CODEC_STOP_INFO；
  (3) 故障事件（FAULT）：FAULT / DEMUXER_FAILURE / AUDIO_CODEC_FAILURE / VIDEO_CODEC_FAILURE / MUXER_FAILURE / RECORD_AUDIO_FAILURE；
  (4) 统计事件（STATISTIC / BEHAVIOR）：MEDIAKIT_STATISTICS / SOURCE_STATISTICS_REPORT_INFO。
  写入时使用 HiSysEvent::EventType 枚举区分事件级别。
  所有事件字段通过键值对传递，无 schema 内嵌，依赖 hisysevent.yaml 定义字段约束。
why_it_matters:
 - 问题定位：知道某类故障对应哪个 Write 函数，就能快速找到上报点并加日志
 - 三方应用诊断：通过 HiSysEvent 日志可以追溯 Codec 实例生命周期
 - 新需求接入：新增故障类型必须调用 avcodec_sysevent.cpp 中的函数，不能自行实现
 - 性能分析：SOURCE_STATISTICS_REPORT_INFO 包含播放策略、缓冲时长、码率等性能数据
evidence:
 - kind: code
   ref: services/dfx/avcodec_sysevent.cpp
   anchor: 函数列表 + HiSysEventWrite 调用
   note: |
     10+ 个写入函数，4 类事件：
     - FAULT: FaultEventWrite (AV_CODEC域)
     - BEHAVIOR: ServiceStartEventWrite / CodecStartEventWrite / CodecStopEventWrite (AV_CODEC域)
     - FAULT: FaultDemuxerEventWrite / FaultAudioCodecEventWrite / FaultVideoCodecEventWrite / FaultMuxerEventWrite / FaultRecordAudioEventWrite (MULTI_MEDIA域)
     - STATISTIC/BEHAVIOR: StreamAppPackageNameEventWrite / SourceStatisticsEventWrite (MULTI_MEDIA域)
     HiSysEvent::EventType: FAULT/BEHAVIOR/STATISTIC 三级
 - kind: code
   ref: services/dfx/include/avcodec_sysevent.h
   anchor: 数据结构定义
   note: |
     CodecDfxInfo（Codec实例维度统计）/ DemuxerFaultInfo / MuxerFaultInfo /
     AudioCodecFaultInfo / VideoCodecFaultInfo / AudioSourceFaultInfo /
     SourceStatisticsReportInfo 等数据结构
 - kind: code
   ref: services/dfx/avcodec_sysevent.cpp
   anchor: HISYSEVENT_DOMAIN_AVCODEC = "AV_CODEC"
   note: 专有域，HiSysEvent Domain 为 "AV_CODEC"，与 MULTI_MEDIA 分离
 - kind: code
   ref: hisysevent.yaml
   anchor: 事件域定义
   note: 4个事件域（CODEC_START_INFO/STOP_INFO/FAULT/STATISTICS_INFO）及字段定义
 - kind: code
   ref: services/dfx/avcodec_xcollie.cpp
   anchor: AVCodecXCollie::SetTimer
   note: 看门狗定时器，用于检测 Codec 接口调用是否超时（默认10秒）
 - kind: code
   ref: services/dfx/avcodec_dump_utils.cpp
   anchor: 进程dump
   note: 进程信息转储（fd / 内存 / 线程信息）
related:
 - MEM-ARCH-AVCODEC-002
 - MEM-ARCH-AVCODEC-004
 - FAQ-SCENE4-001
 - FAQ-SCENE4-002
owner: 耀耀
review:
  owner: 耀耀
  approved_at: "2026-04-17"
  change_policy: update_on_code_change
update_trigger: code_change
created_at: "2026-04-17"
updated_at: "2026-04-17"
