id: MEM-ARCH-AVCODEC-002
title: DFX 统计事件框架职责边界
type: architecture_fact
scope: [DFX, StatisticsEvent, FaultType]
status: draft
confidence: high
summary: >
  services/dfx/ 是 AVCodec 唯一的 DFX 模块，包含两套独立机制：
  (1) 系统事件（HiSysEvent）：通过 FaultEventWrite()/CodecStartEventWrite() 等函数向系统上报故障事件，
  事件类型定义在 avcodec_sysevent.h 的 FaultType 枚举（FAULT_TYPE_FREEZE/CRASH/INNER_ERROR）；
  (2) 进程内调试工具：avcodec_dump_utils（进程信息 dump）、avcodec_xcollie（看门狗超时检测）。
  这套框架独立于 codec/demuxer/muxer 业务逻辑存在，属于横切关注点。
  子模块通过调用 dfx 层的公共接口接入，而非自行实现统计逻辑。
why_it_matters:
 - 三方应用定位故障：遇到 FREEZE/CRASH 时通过系统事件追溯根因
 - 新需求开发接入 DFX：新增统计事件必须通过 dfx 层接口，不能自行实现
 - 问题定位：avcodec_xcollie 是卡顿检测的第一工具
 - 理解框架边界：dfx 职责是"横切上报"，不参与具体 codec 逻辑
evidence:
 - kind: code
   ref: services/dfx/avcodec_sysevent.h
   anchor: FaultType 枚举 + 事件写入函数声明
   note: |
     5 种 FaultType：FREEZE/CRASH/INNER_ERROR
     写入函数：FaultEventWrite/CodecStartEventWrite/CodecStopEventWrite/
     FaultDemuxerEventWrite/FaultAudioCodecEventWrite/FaultVideoCodecEventWrite/
     FaultMuxerEventWrite/SourceStatisticsEventWrite
 - kind: code
   ref: services/dfx/avcodec_sysevent.cpp
   anchor: 实现
   note: 实现各 FaultEvent 写入逻辑
 - kind: code
   ref: services/dfx/avcodec_dfx_component.cpp
   anchor: AVCodecDfxComponent 类
   note: 提供 tag 管理（SetTag/GetTag），用于标识组件身份
 - kind: code
   ref: services/dfx/avcodec_dump_utils.cpp
   anchor: 进程信息 dump
   note: 提供进程状态信息转储
 - kind: code
   ref: services/dfx/avcodec_xcollie.cpp
   anchor: 看门狗超时检测
   note: xcollie 是进程内超时检测工具，用于检测 Codec 卡死
 - kind: code
   ref: services/dfx/include/avcodec_trace.h
   anchor: trace 工具
   note: 提供 trace 能力（未详细扫描）
related:
 - MEM-ARCH-AVCODEC-001
 - MEM-DEVFLOW-003
 - FAQ-SCENE4-001
 - FAQ-SCENE2-003
owner: 耀耀
review:
  owner: 耀耀
  approved_at: pending
  change_policy: update_on_code_change
update_trigger: code_change
created_at: "2026-04-17"
updated_at: "2026-04-17"
