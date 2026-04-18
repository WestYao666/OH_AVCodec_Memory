id: MEM-DEVFLOW-008
title: 问题定位首查路径——症状→工具→日志决策树
type: dev_flow
scope: [DFX, Diagnosis, HiSysEvent, HiLog, XCollie, HiTrace]
status: draft
confidence: high
summary: >
  AVCodec 问题定位遵循"症状 → 工具 → 域/标签 → 细节"的四步决策树。
  第一步按 FAULTTYPE 分类（卡死/崩溃/内部错误/模块故障），第二步选对工具（XCollie/HiSysEvent/HiLog/HiTrace），
  第三步根据 FAULT 事件中的 MODULE 字段或 LOG_DOMAIN 定位模块，第四步追溯代码调用链。
  关键规律：AV_CODEC domain 的 FAULT 事件由本地 hisysevent.yaml 管辖，
  而 DEMUXER/AUDIO_CODEC/VIDEO_CODEC/MUXER/RECORD_AUDIO_FAILURE 五大故障类型走 MULTI_MEDIA domain，
  不在本地 yaml 中定义。
why_it_matters:
 - 三方应用/问题定位：遇到具体症状时知道第一时间查哪个工具，而不是在所有日志里大海捞针
 - 新人入项：建立系统化排查思路，避免盲试
 - 回归验证：修复后可通过 HiSysEvent STATISTICS_INFO 对比关键指标（SPEED_DECODING_INFO）
decision_tree:
  step1_symptom_classification:
    description: 按症状类型分类，确定 FAULTTYPE
    branches:
      - symptom: "编解码调用超时/卡死（无响应）"
        faultType: FAULT_TYPE_FREEZE
        primary_tool: XCollie
        secondary: HiSysEvent FAULT(MODULE="Service"/"Client")
        evidence: |
          XCollie 默认 10s（Service）/ 30s（Client）超时触发回调
          Service 侧超时 → FaultEventWrite → _exit(-1) 杀进程
          Client 侧超时 → 仅写 HiSysEvent，不杀进程
        files:
          - services/dfx/avcodec_xcollie.cpp (ServiceInterfaceTimerCallback)
          - services/dfx/include/avcodec_xcollie.h (SetTimer 默认 10s)
      - symptom: "进程崩溃/闪退"
        faultType: FAULT_TYPE_CRASH
        primary_tool: HiSysEvent FAULT
        secondary: HiLog (LOG_DOMAIN_FRAMEWORK)
        evidence: |
          FAULT_TYPE_CRASH 事件写 HiSysEvent，MODULE 字段标识崩溃模块
          日志标签 {LOG_CORE, LOG_DOMAIN_FRAMEWORK, "AVCodecDFX"} 过滤 hilog
        files:
          - services/dfx/avcodec_sysevent.cpp (FAULT_TYPE_TO_STRING["Crash"])
      - symptom: "编解码逻辑错误（返回错误码）"
        faultType: FAULT_TYPE_INNER_ERROR
        primary_tool: HiSysEvent FAULT
        secondary: HiLog (按模块 domain)
        evidence: |
          FAULT_TYPE_INNER_ERROR 由业务层主动调用 FaultEventWrite 触发
          需要结合具体业务场景定位
        files:
          - services/dfx/avcodec_sysevent.cpp (FAULT_TYPE_TO_STRING["Inner error"])
      - symptom: "解封装失败"
        faultType: MULTI_MEDIA / DEMUXER_FAILURE
        primary_tool: HiSysEvent (MULTI_MEDIA domain)
        secondary: HiLog (LOG_DOMAIN_DEMUXER)
        evidence: |
          DEMUXER_FAILURE 走 MULTI_MEDIA domain，hisysevent.yaml 无定义
          日志过滤：hilog -l D -b 0xD002B3A（LOG_DOMAIN_DEMUXER）
        files:
          - services/dfx/avcodec_sysevent.cpp (FaultDemuxerEventWrite → MULTI_MEDIA)
          - services/dfx/include/avcodec_log.h (LOG_DOMAIN_DEMUXER = 0xD002B3A)
      - symptom: "音频编解码失败"
        faultType: MULTI_MEDIA / AUDIO_CODEC_FAILURE
        primary_tool: HiSysEvent (MULTI_MEDIA domain)
        secondary: HiLog (LOG_DOMAIN_AUDIO)
        evidence: |
          AUDIO_CODEC_FAILURE 走 MULTI_MEDIA domain
          日志过滤：hilog -l D -b 0xD002B31（LOG_DOMAIN_AUDIO）
        files:
          - services/dfx/avcodec_sysevent.cpp (FaultAudioCodecEventWrite → MULTI_MEDIA)
          - services/dfx/include/avcodec_log.h (LOG_DOMAIN_AUDIO = 0xD002B31)
      - symptom: "视频编解码失败"
        faultType: MULTI_MEDIA / VIDEO_CODEC_FAILURE
        primary_tool: HiSysEvent (MULTI_MEDIA domain)
        secondary: HiLog (LOG_DOMAIN_HCODEC)
        evidence: |
          VIDEO_CODEC_FAILURE 走 MULTI_MEDIA domain
          日志过滤：hilog -l D -b 0xD002B32（LOG_DOMAIN_HCODEC）
        files:
          - services/dfx/avcodec_sysevent.cpp (FaultVideoCodecEventWrite → MULTI_MEDIA)
          - services/dfx/include/avcodec_log.h (LOG_DOMAIN_HCODEC = 0xD002B32)
      - symptom: "封装/录制失败"
        faultType: MULTI_MEDIA / MUXER_FAILURE 或 RECORD_AUDIO_FAILURE
        primary_tool: HiSysEvent (MULTI_MEDIA domain)
        secondary: HiLog (LOG_DOMAIN_MUXER)
        evidence: |
          MUXER_FAILURE / RECORD_AUDIO_FAILURE 走 MULTI_MEDIA domain
          日志过滤：hilog -l D -b 0xD002B3B（LOG_DOMAIN_MUXER）
        files:
          - services/dfx/avcodec_sysevent.cpp (FaultMuxerEventWrite/FaultRecordAudioEventWrite → MULTI_MEDIA)
          - services/dfx/include/avcodec_log.h (LOG_DOMAIN_MUXER = 0xD002B3B)
  step2_tool_selection:
    description: 根据故障类型选择工具
    tools:
      XCollie:
        purpose: 超时/卡死检测（第一优先）
        header: services/dfx/include/avcodec_xcollie.h
        impl: services/dfx/avcodec_xcollie.cpp
        key_facts:
          - SetTimer() 默认 10s 超时，SetInterfaceTimer() 默认 30s
          - Service 侧超时 → HiSysEvent FREEZE + _exit(-1) 杀进程
          - Client 侧超时 → HiSysEvent FREEZE，不杀进程
          - RAII 便捷宏：COLLIE_LISTEN(stmt, name, isService, recovery, timeout)
      HiSysEvent:
        purpose: 系统级持久日志（查 FAULT/BEHAVIOR/STATISTIC）
        yaml: hisysevent.yaml
        impl: services/dfx/avcodec_sysevent.cpp
        key_facts:
          - FAULT 事件：FREEZE/CRASH/INNER_ERROR（AV_CODEC domain）
          - BEHAVIOR 事件：CODEC_START_INFO/CODEC_STOP_INFO/SERVICE_START_INFO
          - STATISTICS 事件：CODEC_START_INFO 等，含性能指标
          - 5 类模块故障走 MULTI_MEDIA domain（不在本地 yaml）
      HiLog:
        purpose: 进程内实时日志（按 LOG_DOMAIN 过滤）
        header: services/dfx/include/avcodec_log.h
        domains:
          - FRAMEWORK: 0xD002B30（avcodec 框架层）
          - AUDIO: 0xD002B31（音频编解码）
          - HCODEC: 0xD002B32（硬件/视频编解码）
          - TEST: 0xD002B36（测试相关）
          - DEMUXER: 0xD002B3A（解封装）
          - MUXER: 0xD002B3B（封装）
        macros: AVCODEC_LOGF/LOGE/LOGW/LOGI/LOGD + _LIMIT 限频变体
      HiTrace:
        purpose: 调用链追踪 + 性能分析
        header: services/dfx/include/avcodec_trace.h
        key_facts:
          - 基于 HITRACE_TAG_ZMEDIA
          - 同步：AVCODEC_SYNC_TRACE / AVCODEC_FUNC_TRACE_WITH_TAG
          - 异步：TraceBegin/TraceEnd
          - 计数器：CounterTrace
  step3_module_narrowing:
    description: 通过 HiSysEvent MODULE 字段或 LOG_DOMAIN 定位
    hiSysEvent_module_values:
      - Service（XCollie 服务侧超时）
      - Client（XCollie 客户端超时）
      - 具体模块名（codec/demuxer/muxer 等在 avcodec_sysevent.cpp 中定义）
    log_domain_mapping:
      0xD002B30: FRAMEWORK
      0xD002B31: AUDIO
      0xD002B32: HCODEC
      0xD002B36: TEST
      0xD002B3A: DEMUXER
      0xD002B3B: MUXER
  step4_detail_trace:
    description: 追溯具体调用链和代码位置
    tools:
      - HiTrace：AVCODEC_FUNC_TRACE_WITH_TAG 标记函数入口
      - HiLog：按 LOG_DOMAIN + 具体函数名过滤
      - XCollie Dump()：查看当前活跃的 timer 列表（fd dump）
faultType_summary:
  AV_CODEC_domain_faults:
    - FAULT_TYPE_FREEZE（超时/卡死）
    - FAULT_TYPE_CRASH（崩溃）
    - FAULT_TYPE_INNER_ERROR（内部错误）
    yaml_definable: true
  MULTI_MEDIA_domain_faults:
    - DEMUXER_FAILURE
    - AUDIO_CODEC_FAILURE
    - VIDEO_CODEC_FAILURE
    - MUXER_FAILURE
    - RECORD_AUDIO_FAILURE
    yaml_definable: false (平台侧管理)
evidence:
  - kind: code
    ref: services/dfx/avcodec_sysevent.cpp
    anchor: FAULT_TYPE_TO_STRING + 两个 domain 分支
    note: |
      FAULT_TYPE_TO_STRING: FREEZE/Crash/Inner error
      AV_CODEC domain: FAULT, CODEC_START_INFO, CODEC_STOP_INFO, SERVICE_START_INFO
      MULTI_MEDIA domain: DEMUXER_FAILURE, AUDIO_CODEC_FAILURE, VIDEO_CODEC_FAILURE, MUXER_FAILURE, RECORD_AUDIO_FAILURE
  - kind: code
    ref: services/dfx/avcodec_xcollie.cpp
    anchor: ServiceInterfaceTimerCallback / ClientInterfaceTimerCallback
    note: |
      Service 超时 → FAULT_TYPE_FREEZE + _exit(-1)（杀进程）
      Client 超时 → FAULT_TYPE_FREEZE（不杀进程）
      threshold = 1，首次超时计数，第2次杀进程
  - kind: code
    ref: services/dfx/include/avcodec_xcollie.h
    anchor: timerTimeout = 10, SetInterfaceTimer 默认 30s
    note: |
      constexpr uint32_t timerTimeout = 10（默认10秒）
      SetInterfaceTimer(uint32_t timeout = 30)
  - kind: code
    ref: services/dfx/include/avcodec_log.h
    anchor: 6个 LOG_DOMAIN 定义
    note: |
      FRAMEWORK(0xD002B30) / AUDIO(0xD002B31) / HCODEC(0xD002B32) /
      TEST(0xD002B36) / DEMUXER(0xD002B3A) / MUXER(0xD002B3B)
  - kind: code
    ref: services/dfx/include/avcodec_trace.h
    anchor: AVCODEC_SYNC_TRACE / TraceBegin/TraceEnd / CounterTrace
    note: |
      HITRACE_TAG_ZMEDIA，AVCODEC_SYNC_TRACE 标记函数入口，
      TraceBegin/End 支持异步 trace，CounterTrace 记录计数器
  - kind: code
    ref: hisysevent.yaml
    anchor: FAULT 事件域定义（MODULE/FAULTTYPE/MSG）
    note: |
      FAULT: MODULE(STRING)/FAULTTYPE(STRING)/MSG(STRING)
      三字段足以定位大部分故障
related:
  - MEM-DEVFLOW-003  # 日志定位流程（详细的三层工具说明）
  - MEM-DEVFLOW-004  # 新增 DFX 事件接入流程
  - MEM-ARCH-AVCODEC-002  # DFX 框架职责边界
  - MEM-ARCH-AVCODEC-005  # HiSysEvent 与故障事件函数映射
owner: 耀耀
review:
  owner: 耀耀
  approved_at: ""
  change_policy: update_on_code_change
update_trigger: 新增 FAULT 事件类型 / 新增 LOG_DOMAIN / XCollie 阈值调整
created_at: "2026-04-18"
updated_at: "2026-04-18"
