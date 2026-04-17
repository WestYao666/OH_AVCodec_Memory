---
id: MEM-DEVFLOW-007
title: 新需求开发标准流程
type: dev_flow
status: approved
confidence: high
summary: >
  AVCodec 新增一种 Codec（如 EAC3 解码器）的标准开发流程分为7步：
  ① config.gni 加 feature flag → ② avcodec_codec_name.h 加名称常量 →
  ③ avcodec_mime_type.h 加 MIME 常量 → ④ kits/c/ 扩展 C API（如需）→
  ⑤ plugins/ 下实现 CodecPlugin 子类 + PLUGIN_DEFINITION 注册 →
  ⑥ 子目录 BUILD.gn + plugins/BUILD.gn deps 注册 target →
  ⑦ test/moduletest/ 写 gtest 单测。
why_it_matters: >
  AVCodec 是高度模块化的插件架构，新增 Codec 涉及多个目录的联动修改。
  理解标准流程可避免漏改文件、build 失败或单测遗漏。
  本记忆是"新需求开发"场景（L3）的核心参考。
scope: AVCodec 新功能开发流程 / 新增 Codec 插件
service_scenario: "新需求开发"
evidence:
  - kind: code
    ref: /home/west/OH_AVCodec/config.gni
    anchor: av_codec_enable_codec_eac3, av_codec_defines += ["SUPPORT_CODEC_EAC3"]
    note: >
      config.gni 是全局 feature flag 定义入口。新 codec 需要添加
      av_codec_enable_codec_XXX = false 开关 + 条件 av_codec_defines += ["SUPPORT_CODEC_XXX"]。
      示例：eac3 开关在第50行，条件定义在第210行。

  - kind: code
    ref: /home/west/OH_AVCodec/services/media_engine/plugins/BUILD.gn
    anchor: av_codec_media_engine_plugins, deps
    note: >
      插件汇总 BUILD.gn。所有 ohos_shared_library 插件通过 deps 列表注册。
      新插件必须在此 deps 中出现（含条件 if (flag) 块）才能被构建。

  - kind: code
    ref: /home/west/OH_AVCodec/services/media_engine/plugins/ffmpeg_adapter/audio_decoder/eac3/ffmpeg_eac3_decoder_plugin.cpp
    anchor: RegisterAudioDecoderPlugins, PLUGIN_DEFINITION
    note: >
      EAC3 解码器是"新增 codec"的标准参考实现。
      PLUGIN_DEFINITION 宏（第68行）来自 plugin/plugin_definition.h（外部框架），
      在 .so 加载时自动调用注册函数，使用 reg->AddPlugin(definition) 注入能力。

  - kind: code
    ref: /home/west/OH_AVCodec/interfaces/inner_api/native/avcodec_codec_name.h
    anchor: AUDIO_DECODER_EAC3_NAME, #ifdef SUPPORT_CODEC_EAC3
    note: >
      Codec 名称常量定义文件。新 codec 名称 ID 必须添加，
      用 #ifdef SUPPORT_CODEC_XXX 条件编译包裹。

  - kind: code
    ref: /home/west/OH_AVCodec/interfaces/kits/c/native_avcodec_base.h
    anchor: OH_AVCODEC_MIMETYPE_AUDIO_EAC3
    note: >
      Kits 层 C API MIME 字符串 extern 声明（第484行）。
      新 codec 如需暴露给应用层，在此添加 extern 声明。

  - kind: code
    ref: /home/west/OH_AVCodec/test/moduletest/audio_decoder/BUILD.gn
    anchor: ohos_unittest("audio_decoder_module_test")
    note: >
      单测构建入口。使用 ohos_unittest target 类型，
      依赖 av_codec_client 和 av_codec_service。
      新 codec 单测文件需加入 sources 列表。

  - kind: code
    ref: /home/west/OH_AVCodec/test/moduletest/audio_decoder/NativeAPI/NativeFunctionTest.cpp
    anchor: testing::Test, CreateByMime, PushInputData
    note: >
      单测标准模式：gtest::Test 基类，CreateByMime 创建解码器实例，
      Configure → Start → PushInputData → FreeOutputBuffer 流程。

  - kind: code
    ref: /home/west/OH_AVCodec/services/media_engine/plugins/ffmpeg_adapter/muxer/ffmpeg_muxer_register.cpp
    anchor: PLUGIN_DEFINITION(FFmpegMuxer,...), RegisterMuxerPlugins
    note: >
      Muxer 插件注册参考，证明 demuxer/muxer 使用相同 PLUGIN_DEFINITION 模式。

  - kind: doc
    ref: /home/west/OH_AVCodec/README.md
    anchor: Contribution
    note: >
      无独立 CODEOWNERS / CONTRIBUTING.md。贡献流程遵循 OpenHarmony 标准
      PR 模式：Fork → Feat_xxx branch → Commit → Pull Request。

related:
  - MEM-DEVFLOW-001  # 可关联：构建系统入口
  - MEM-DEVFLOW-003  # 可关联：FFmpeg 适配层结构
  - MEM-DEVFLOW-005  # 可关联：API 层结构
  - MEM-CODEC-002    # 可关联：Audio Decoder 模块地图
  - MEM-TEST-001     # 可关联：单测运行命令
owner: 耀耀
review:
  owner: 耀耀
  approved_at: "2026-04-17"
change_policy: update_on_code_change
update_trigger: code_change
created_at: "2026-04-17"
updated_at: "2026-04-17"
---
