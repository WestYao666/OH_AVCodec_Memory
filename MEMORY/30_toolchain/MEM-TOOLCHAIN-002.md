id: MEM-TOOLCHAIN-002
title: 日志框架——LOG_DOMAIN 与 HiTrace 链路追踪
type: toolchain
scope: [Toolchain, Log, Trace, HiLog]
status: approved
confidence: high
summary: >
  AVCodec 使用 HiLog（日志）+ HiTrace（链路追踪）作为日志框架。
  LOG_DOMAIN 定义在 services/dfx/include/avcodec_log.h，共 7 个域：
  FRAMEWORK(0xD002B30) / AUDIO(0xD002B31) / HCODEC(0xD002B32) / SFD(0xD002B33) / TEST(0xD002B36) / DEMUXER(0xD002B3A) / MUXER(0xD002B3B)。
  HiTrace 提供 TraceBegin/TraceEnd（链路标记）和 CounterTrace（计数器）两种追踪能力。
  HiLog 使用宏HiLogLabel{LOG_CORE, LOG_DOMAIN, "tag"} 声明日志标签，写入到 hilog 系统服务。
  常用日志级别由 HiSysEvent::EventType 定义：FAULT（故障）/ BEHAVIOR（行为）/ STATISTIC（统计）。
why_it_matters:
 - 问题定位：不同 LOG_DOMAIN 对应不同模块，通过日志 domain 过滤快速定位问题模块
 - 链路追踪：HiTrace 可追踪完整调用链，特别适合多线程/异步场景的性能分析
 - 新需求开发：新增模块日志需遵守 avcodec_log.h 的 domain 定义规范
 - 调试：AVCodecXCollie 的超时检测配合 HiTrace 可以定位是哪一步卡住
evidence:
 - kind: code
   ref: services/dfx/include/avcodec_log.h
   anchor: LOG_DOMAIN_宏定义
   note: 7个 LOG_DOMAIN 常量（16进制 ID 到 模块名 的映射）
 - kind: code
   ref: services/dfx/include/avcodec_log.h
   anchor: HiLogLabel 声明格式
   note: 使用 {LOG_CORE, LOG_DOMAIN, "tag"} 三元组声明日志标签
 - kind: code
   ref: services/dfx/include/avcodec_trace.h
   anchor: AVCodecTrace / TraceBegin / TraceEnd / CounterTrace
   note: HiTrace API，提供 RAII 自动追踪和手动 begin/end 接口
 - kind: code
   ref: services/dfx/include/avcodec_sysevent.h
   anchor: HiSysEvent::EventType 枚举
   note: FAULT/BEHAVIOR/STATISTIC 三级事件级别定义
 - kind: code
   ref: services/dfx/avcodec_sysevent.cpp
   anchor: HiSysEventWrite 调用
   note: 事件写入函数使用 HiSysEvent::EventType 而非 HiLog
 - kind: code
   ref: services/dfx/avcodec_xcollie.cpp
   anchor: AVCodecXCollie 超时检测
   note: SetTimer 设置看门狗定时器，配合日志定位超时根因
related:
 - MEM-ARCH-AVCODEC-005
 - MEM-ARCH-AVCODEC-002
 - MEM-DEVFLOW-001
 - FAQ-SCENE4-002
owner: 耀耀
review:
  owner: 耀耀
  approved_at: "2026-04-17"
  change_policy: update_on_code_change
update_trigger: code_change
created_at: "2026-04-17"
updated_at: "2026-04-17"
