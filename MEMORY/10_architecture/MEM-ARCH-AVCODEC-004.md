id: MEM-ARCH-AVCODEC-004
title: DFX 事件体系——HiSysEvent + 进程内调试工具
type: architecture_fact
scope: [DFX, HiSysEvent, Statistics]
status: draft
confidence: high
summary: >
  AVCodec DFX 体系包含两套独立机制：
  (1) HiSysEvent 系统事件（写入系统日志）：
      - CODEC_START_INFO / CODEC_STOP_INFO：行为事件（MINOR级别）
      - FAULT：故障事件（CRITICAL级别，含 MODULE/MSG/FAULTTYPE）
      - STATISTICS_INFO：统计事件（CRITICAL级别，含查询次数/创建次数/异常统计等）
  (2) 进程内调试工具：
      - avcodec_sysevent.cpp：事件写入函数（FaultEventWrite / CodecStartEventWrite 等）
      - avcodec_dump_utils.cpp：进程状态转储
      - avcodec_xcollie.cpp：看门狗超时检测（检测 Codec 卡死）
      - avcodec_trace.h/cpp：trace 工具
      - avcodec_dfx_component.cpp：tag 管理（SetTag/GetTag）
why_it_matters:
 - 三方应用定位故障：通过 FAULT 事件中的 MODULE/MSG/FAULTTYPE 追溯根因
 - 新需求开发接入 DFX：新增统计事件必须调用 avcodec_sysevent.cpp 中的公共函数
 - 问题定位：FREEZE/CRASH/INNER_ERROR 三种 FaultType 对应不同排查路径
 - 性能分析：STATISTICS_INFO 中的 SPEED_DECODING_INFO / CODEC_ERROR_INFO 可用于性能分析
evidence:
 - kind: code
   ref: hisysevent.yaml
   anchor: 事件域定义
   note: 4个事件域（CODEC_START_INFO/STOP_INFO/FAULT/STATISTICS_INFO）及字段定义
 - kind: code
   ref: services/dfx/avcodec_sysevent.cpp
   anchor: 事件写入函数
   note: 8个写入函数，覆盖 codec/demuxer/muxer/audio/video/source 各模块
 - kind: code
   ref: services/dfx/avcodec_dfx_component.cpp
   anchor: AVCodecDfxComponent
   note: tag 管理接口，组件身份标识
 - kind: code
   ref: services/dfx/avcodec_dump_utils.cpp
   anchor: 进程dump
   note: 进程状态转储工具
 - kind: code
   ref: services/dfx/avcodec_xcollie.cpp
   anchor: xcollie
   note: 看门狗超时检测
 - kind: code
   ref: services/dfx/include/avcodec_trace.h
   anchor: trace
   note: trace 工具头文件
related:
 - MEM-ARCH-AVCODEC-002
 - MEM-ARCH-AVCODEC-001
 - FAQ-SCENE4-001
 - FAQ-SCENE4-002
owner: 耀耀
review:
  owner: 耀耀
  approved_at: pending
  change_policy: update_on_code_change
update_trigger: code_change
created_at: "2026-04-17"
updated_at: "2026-04-17"
