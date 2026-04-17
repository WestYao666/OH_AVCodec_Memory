id: MEM-DEVFLOW-003
title: 日志定位流程——日志层级与故障排查路径
type: dev_flow
scope: [DFX, Log, Diagnosis, HiLog, HiSysEvent]
status: approved
confidence: high
summary: >
  AVCodec 日志系统分为三层，各层独立、互不干扰，定位故障时按层级选择正确工具：
  (1) **HiLog**（进程内实时日志）：写 hilog 系统服务，通过 LOG_DOMAIN 过滤模块，
      日志标签格式 HiLogLabel{LOG_CORE, LOG_DOMAIN, "tag"}。
      已知 7 个 LOG_DOMAIN：FRAMEWORK(0xD002B30) / AUDIO(0xD002B31) / HCODEC(0xD002B32) / SFD(0xD002B33) / TEST(0xD002B36) / DEMUXER(0xD002B3A) / MUXER(0xD002B3B)。
  (2) **HiSysEvent**（系统级持久日志）：写入 hisysevent.yaml 定义的事件域（AV_CODEC / MULTI_MEDIA），
      分为 BEHAVIOR（MINOR级）/ FAULT（CRITICAL级）/ STATISTIC（CRITICAL级）三类。
      故障类事件通过 hilog 透传，FAULT 事件可追溯到具体 MODULE / MSG / FAULTTYPE。
  (3) **HiTrace**（链路追踪）：TraceBegin/TraceEnd 标记调用链，CounterTrace 记录计数器。
      配合 AVCodecXCollie 超时检测（SetTimer 默认10秒超时）使用。
  故障排查标准路径：HiSysEvent FAULT 事件 → 定位 MODULE → HiLog 按 LOG_DOMAIN 过滤 → HiTrace 追踪调用链。
why_it_matters:
 - 问题定位：知道哪个工具对应哪类日志，避免在错误层级浪费时间
 - 故障排查：FAULTTYPE（FREEZE/CRASH/INNER_ERROR）对应不同的排查路径
 - 新需求开发：新增模块必须声明正确的 LOG_DOMAIN，新增事件必须遵循 hisysevent.yaml 定义
 - 回归验证：修复后通过 HiSysEvent STATISTICS_INFO 对比关键指标（SPEED_DECODING_INFO / CODEC_ERROR_INFO）
evidence:
 - kind: code
   ref: services/dfx/include/avcodec_log.h
   anchor: LOG_DOMAIN_宏定义（7个）
   note: FRAMEWORK/AUDIO/HCODEC/SFD/TEST/DEMUXER/MUXER 共7个domain
 - kind: code
   ref: services/dfx/include/avcodec_log.h
   anchor: HiLogLabel声明格式
   note: {LOG_CORE, LOG_DOMAIN, "tag"} 三元组
 - kind: code
   ref: hisysevent.yaml
   anchor: 三层事件定义
   note: BEHAVIOR(MINOR)/FAULT(CRITICAL)/STATISTIC(CRITICAL) 三级，AV_CODEC域
 - kind: code
   ref: services/dfx/include/avcodec_trace.h
   anchor: HiTrace API
   note: TraceBegin/TraceEnd/CounterTrace + AVCodecTrace RAII类
 - kind: code
   ref: services/dfx/include/avcodec_xcollie.h
   anchor: AVCodecXCollie::SetTimer
   note: 看门狗定时器，默认10秒超时，超时触发回调+dump
 - kind: code
   ref: services/dfx/avcodec_sysevent.cpp
   anchor: FAULT_TYPE_TO_STRING映射
   note: FAULT_TYPE_FREEZE/CRASH/INNER_ERROR 三种故障类型
 - kind: code
   ref: hisysevent.yaml
   anchor: STATISTICS_INFO详细字段
   note: QUERY_CAP_TIMES/CREATE_CODEC_TIMES/SPEED_DECODING_INFO/CODEC_ERROR_INFO等
related:
 - MEM-ARCH-AVCODEC-005
 - MEM-TOOLCHAIN-002
 - MEM-ARCH-AVCODEC-002
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
