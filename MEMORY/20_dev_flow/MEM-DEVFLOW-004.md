id: MEM-DEVFLOW-004
title: 新增 DFX 事件接入流程
type: dev_flow
scope: [DFX, Event, HiSysEvent, Integration]
status: approved
confidence: high
summary: >
  在 AVCodec 中新增一个 DFX 统计/故障事件，需要修改 2~3 个文件，走两条路径之一：
  路径 A（AV_CODEC domain，3步）：(1) services/dfx/include/avcodec_sysevent.h
  定义 XxxInfo 结构体 + XxxEventWrite() 函数声明；(2) avcodec_sysevent.cpp 实现
  Write 函数，内部调用 HiSysEventWrite(HISYSEVENT_DOMAIN_AVCODEC, "EVENT_NAME", ...)；
  (3) hisysevent.yaml 添加 EVENT_NAME 和字段类型定义。
  路径 B（MULTI_MEDIA domain，2步）：无需修改 hisysevent.yaml（由平台侧管理），
  直接在 .h/.cpp 中调用 HiSysEventWrite(HiSysEvent::Domain::MULTI_MEDIA, "EVENT_NAME", ...)。
  调用模式统一：声明 Info 结构体 → 填充字段 → 调用 XxxEventWrite()。
  注意：hisysevent.yaml 仅定义了4个 AV_CODEC 事件（START_INFO/STOP_INFO/FAULT/STATISTICS_INFO），
  7+个故障事件走 MULTI_MEDIA domain，不在本地 yaml 管理。
why_it_matters:
 - 新需求开发：新增 DFX 事件时知道从哪入手、改哪些文件
 - 规范流程：遵循三段式结构避免事件上报失效
 - 问题定位：知道路径A/B 的区别就知道该查哪个 yaml
 - 待确认缺口：MULTI_MEDIA domain 的 yaml 在哪个仓？新增事件是否需要 DFX Approver 审批？
evidence:
 - kind: code
   ref: services/dfx/include/avcodec_sysevent.h
   anchor: CodecDfxInfo 结构体 + Write函数声明
   note: |
     结构体+Write函数声明的标准格式，15个字段（CODEC_START_INFO 的载体）
     struct XxxInfo { ... }; void XxxEventWrite(XxxInfo&);
 - kind: code
   ref: services/dfx/avcodec_sysevent.cpp
   anchor: HiSysEventWrite 调用模式
   note: |
     统一调用模式：HiSysEventWrite(DOMAIN, "EVENT_NAME", EventType::FAULT/BEHAVIOR/STATISTIC, 键值对...)
     域分 AV_CODEC(自有yaml) 和 MULTI_MEDIA(平台侧yaml) 两种
 - kind: code
   ref: hisysevent.yaml
   anchor: 4个AV_CODEC事件域定义
   note: |
     仅定义了4个事件：CODEC_START_INFO / CODEC_STOP_INFO / FAULT / STATISTICS_INFO
     字段类型：BEHAVIOR(MINOR) / FAULT(CRITICAL) / STATISTIC(CRITICAL)
 - kind: code
   ref: services/dfx/avcodec_sysevent.cpp
   anchor: FAULT/MULTI_MEDIA域7+个故障事件
   note: |
     DEMUXER_FAILURE / AUDIO_CODEC_FAILURE / VIDEO_CODEC_FAILURE /
     MUXER_FAILURE / RECORD_AUDIO_FAILURE / SOURCE_STATISTICS 等走 MULTI_MEDIA 域
     不在本地 hisysevent.yaml 管理
 - kind: code
   ref: services/dfx/avcodec_sysevent.cpp
   anchor: 调用点分散
   note: CodecServer（启动/停止）+ media_engine/filters（故障事件）
 - kind: code
   ref: services/dfx/include/avcodec_sysevent.h
   anchor: XxxEventWrite函数模板
   note: |
     函数声明格式可复用：void XxxEventWrite(XxxInfo& xxxFaultInfo)
     实现在 avcodec_sysevent.cpp 中，参照 FaultDemuxerEventWrite 等
related:
 - MEM-ARCH-AVCODEC-005
 - MEM-DEVFLOW-003
 - FAQ-SCENE3-002
 - FAQ-SCENE3-004
owner: 耀耀
review:
  owner: 耀耀
  approved_at: "2026-04-17"
  change_policy: update_on_code_change
update_trigger: code_change
created_at: "2026-04-17"
updated_at: "2026-04-17"

gap:
  - question: MULTI_MEDIA domain 的 hisysevent.yaml 在哪个仓库？
    priority: high
    relates_to: MEM-DEVFLOW-004
  - question: 新增 AV_CODEC domain 事件是否需要 DFX Approver 审批？
    priority: medium
    relates_to: MEM-DEVFLOW-004
