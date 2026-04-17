id: FAQ-SCENE1-001
title: 新人入项 FAQ — Top5（新人入项问答）
type: faq
scope: [FAQ, Newcomer]
status: approved
confidence: high
summary: >
  整理 AVCodec/DFX 新人最常见的 5 个入项问题及其答案。
  基于真实代码仓结构和 20 个问题池中高优先级条目筛选而来。
why_it_matters:
 - 新人快速上手必备，降低入项门槛
 - 四类场景之一（新人入项）的核心记忆产品
evidence:
 - kind: code
   ref: test/moduletest/
   anchor: 单测目录
   note: 回答"如何运行单测"问题的实证
 - kind: code
   ref: BUILD.gn
   anchor: 构建入口
   note: 回答"如何编译"问题的实证
 - kind: code
   ref: services/dfx/avcodec_sysevent.h
   anchor: FaultType枚举
   note: 回答"故障类型有哪些"问题的实证
 - kind: code
   ref: services/media_engine/plugins/
   anchor: 插件结构
   note: 回答"新增格式支持改哪里"问题的实证
 - kind: doc
   ref: README_zh.md
   anchor: 官方模块说明
   note: 回答"模块边界在哪里"问题的实证
related:
 - MEM-ARCH-AVCODEC-001
 - MEM-DEVFLOW-001
 - MEM-DEVFLOW-002
owner: 耀耀
review:
  owner: 耀耀
  approved_at: "2026-04-17"
  change_policy: update_on_code_change
update_trigger: code_change
created_at: "2026-04-17"
updated_at: "2026-04-17"

answers:
  - id: FAQ-SCENE1-001-Q1
    question: 如何编译 av_codec 部件？
    answer: |
      使用 GN 构建系统：
      1. 在 AVCodec 根目录执行：./build.sh
      2. 或在源码根目录用 GN 引用 av_codec_packages
      顶层 BUILD.gn 声明 av_codec_packages，依赖 interfaces/inner_api/native:av_codec_client 和 services/services:av_codec_service 两大子模块。
    best_practice: 使用官方提供的构建脚本，不要手动改 GN target

  - id: FAQ-SCENE1-001-Q2
    question: 如何运行单测？
    answer: |
      单测位于 test/moduletest/，按模块分类（audio_decoder/encoder、vcodec、demuxer、muxer、capability）。
      每个子目录有独立 BUILD.gn，通过 GN 执行对应单测 target。
      示例：进入 test/moduletest/vcodec/swdecoder/ 编译 avcswdecoder 单测。
    best_practice: 参考同类型已有单测 BUILD.gn 结构

  - id: FAQ-SCENE1-001-Q3
    question: services/engine 和 services/services 两个目录是什么关系？
    answer: |
      services/engine 是功能实现层（base/codec/codeclist/common/factory）。
      services/services 是 IPC 封装层，对 engine 的每个子模块提供 RPC 接口。
      注意：实际核心功能代码在 services/media_engine/modules/（非 services/engine/）。
    best_practice: 新增功能改 media_engine/modules/，IPC 封装改 services/services/

  - id: FAQ-SCENE1-001-Q4
    question: DFX 故障类型有哪些？如何排查？
    answer: |
      DFX 故障类型定义在 services/dfx/avcodec_sysevent.h 的 FaultType 枚举：
      - FAULT_TYPE_FREEZE：解码画面冻结
      - FAULT_TYPE_CRASH：Codec 实例崩溃
      - FAULT_TYPE_INNER_ERROR：内部错误
      排查工具：avcodec_xcollie（看门狗超时检测）、avcodec_dump_utils（进程状态 dump）
    best_practice: 遇到 FREEZE/CRASH 先查 avcodec_sysevent.h 的事件写入时机

  - id: FAQ-SCENE1-001-Q5
    question: 新增一种音视频格式支持，应该改哪里？
    answer: |
      AVCodec 支持插件化扩展，新增格式需要：
      1. 在 services/media_engine/plugins/ 下对应类型目录实现插件
        - demuxer/：解封装插件（读取容器格式）
        - muxer/：封装插件（写入容器格式）
      2. 注册插件到框架
      3. 对应编写单测（参考 test/moduletest/ 下同类测试）
    best_practice: 参考 ffmpeg_adapter 的实现方式复用 FFmpeg 已有能力
