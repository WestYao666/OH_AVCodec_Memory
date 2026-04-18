id: MEM-DEVFLOW-006
title: 问题修复回归流程
type: dev_flow
status: approved
confidence: high
scope: avcodec_testing
summary: >
  AVCodec 问题修复后的回归验证采用"三层测试矩阵"：
  单测（moduletest）→ 模糊测试（fuzztest）→（若有）性能测试。
  所有模块测试入口为 `av_codec_unit_test` group，
  通过 `ohos_unittest("&lt;module&gt;_module_test")` GN 模板组织。
  超时卡顿检测由 XCollie 框架提供，触发 FAULT_TYPE_FREEZE 上报并可触发进程退出。
why_it_matters: >
  问题修复若未做回归，可能引入新问题。三层测试矩阵确保修正是
  全面的、不引入副作用的。XCollie 卡顿检测是质量保障的最后防线。
test_matrix:
  layer1_moduletest:
    description: 模块级单测（黑盒功能测试）
    target_pattern: "ohos_unittest(\"<module>_module_test\")"
    entry_group: av_codec_unit_test
    build_output: "av_codec/AVCodec_{Audio|Video}/moduletest"
    resource_config: test/moduletest/resources/ohos_test.xml
    modules:
      audio_decoder: audio_decoder_module_test
      audio_encoder: audio_encoder_module_test
      capability: capability_module_test
      demuxer: demuxer_native_module_test
      muxer: muxer_native_module_test
      vcodec_encoders: encoder_native_module_test
      vcodec_decoders:
        - dvcntsdecoder_native_module_test
        - dvcprohddecoder_native_module_test
        - h263swdecoder_native_module_test
        - hevcswdecoder_native_module_test
        - hwdecoder_native_module_test
        - mpeg1decoder_native_module_test
        - mpeg2swdecoder_native_module_test
        - mpeg4swdecoder_native_module_test
        - swdecoder_native_module_test
  layer2_fuzztest:
    description: 模糊测试（随机输入安全性）
    location: test/fuzztest/
    count: "200+ fuzzer cases"
    naming: "<component>_fuzzer (e.g. audiodecoderaac_fuzzer)"
    purpose: 防止恶意/异常输入导致崩溃
  layer3_performance:
    description: 性能测试（未在仓内找到独立 perf test）
    note: "OpenHarmony 整体 CI 可能提供，不在 AVCodec 代码仓内维护"
xcollie_mechanism:
  purpose: 卡顿/超时检测与回溯
  header: services/dfx/include/avcodec_xcollie.h
  implementation: services/dfx/avcodec_xcollie.cpp
  api:
    - SetTimer(name, recovery, dumpLog, timeout, callback)
    - SetInterfaceTimer(name, isService, recovery, timeout)
    - CancelTimer(timerId)
    - Dump(fd)  # 进程存活时转储所有活跃 timer 状态
  timeout_default: 10s (AVCodecXCollie::timerTimeout)
  interface_timeout_default: 30s
  callback_chain:
    Service task timeout:
      - logs "Service task {name} timeout"
      - writes FAULT_TYPE_FREEZE HiSysEvent
      - if threadDeadlockCount_ >= threshold: _exit(-1) kills process
    Client task timeout:
      - logs "Client task {name} timeout"
      - writes FAULT_TYPE_FREEZE HiSysEvent
      - does NOT kill process
  macros:
    COLLIE_LISTEN(statement, args...): RAII 风格，statement 执行期间开启监控
    CLIENT_COLLIE_LISTEN(statement, name): Client 侧 30s 超时监控
  dfx_chain:
    - XCollie 超时 → ServiceInterfaceTimerCallback
    - → FaultEventWrite(FAULT_TYPE_FREEZE, msg, "Service"/"Client")
    - → HiSysEvent: domain=AV_CODEC, type=FAULT, MODULE/FAULTTYPE/MSG
ci_cd:
  note: "AVCodec 代码仓内未发现 .gitlab-ci.yml / ci.toml / Jenkinsfile"
  conclusion: 依赖 OpenHarmony 整体 CI 体系，不在 AVCodec 仓内维护独立流水线
  evidence_file: hisysevent.yaml (唯一 yaml，全局配置)
regression_checklist:
  - "[ ] 修改对应 module 的单测用例，覆盖修复 case"
  - "[ ] 执行 av_codec_unit_test 全量单测"
  - "[ ] 若修改涉及 decode/encode/run 时长，检查 fuzztest 相关 fuzzer"
  - "[ ] 检查 XCollie 监控路径是否有 regression（超时阈值是否合理）"
  - "[ ] 验证 HiSysEvent FAULT 上报链路是否正常"
evidence:
  - kind: code
    ref: test/BUILD.gn
    anchor: group("av_codec_unit_test")
    note: 顶层 group 汇总所有单测模块，共 6 大类
  - kind: code
    ref: test/moduletest/audio_decoder/BUILD.gn
    anchor: ohos_unittest("audio_decoder_module_test")
    note: 单测 target 命名规范：ohos_unittest + "_module_test" 后缀
  - kind: code
    ref: services/dfx/avcodec_xcollie.cpp
    anchor: SetTimer / ServiceInterfaceTimerCallback
    note: XCollie 超时检测实现，超时触发 FAULT_TYPE_FREEZE 并可杀进程
  - kind: code
    ref: services/dfx/avcodec_sysevent.cpp
    anchor: FaultEventWrite
    note: 卡顿事件写入 HiSysEvent 的 FAULT 链路
  - kind: code
    ref: services/dfx/include/avcodec_xcollie.h
    anchor: COLLIE_LISTEN / CLIENT_COLLIE_LISTEN
    note: RAII 便捷宏，自动管理 timer 生命周期
  - kind: code
    ref: services/services/sa_avcodec/client/avcodec_client.cpp
    anchor: ScheduleReleaseResources
    note: XCollie 应用示例：防止 ReleaseResources 卡死
  - kind: code
    ref: test/fuzztest/
    note: 200+ fuzztest 用例覆盖各组件
  - kind: doc
    ref: test/moduletest/resources/ohos_test.xml
    note: 单测资源配置
related:
  - MEM-DEVFLOW-001  # 可能有测试相关记忆
  - MEM-ARCH-003     # 可能有 DFX 相关架构记忆
owner: 耀耀
review:
  owner: 耀耀
  approved_at: "2026-04-18"
  change_policy: update_on_code_change
update_trigger: test/BUILD.gn 变更 / 新增 moduletest 模块 / XCollie 阈值调整
created_at: "2026-04-17"
updated_at: "2026-04-17"