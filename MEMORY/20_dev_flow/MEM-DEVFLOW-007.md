id: MEM-DEVFLOW-007
title: 新需求开发标准流程——从插件注册到单测验证
type: dev_flow
scope: [Process, NewFeature, Plugin, Build]
status: approved
confidence: high
summary: >
  AVCodec 新增功能（Codec/解封装/封装支持）遵循标准流程：
  (1) 确定扩展点：新增 demuxer/muxer/codec 插件 → 在 services/media_engine/plugins/ 对应子目录实现；
  (2) 插件注册：demuxer/muxer 插件在 BUILD.gn 中声明 ohos_shared_library，编译入 libmedia_demuxer_plugin.a；
  codec 插件在 media_codec.cpp 中工厂函数创建；
  (3) 实现接口：在 interfaces/plugin/XXX_plugin.h 基类基础上实现子类（SetDataSource/GetMediaInfo/ReadSample 等）；
  (4) 在 services/media_engine/plugins/demuxer/BUILD.gn 中添加 source 文件路径，Build 系统自动编译；
  (5) 编写单测：在 test/moduletest/ 对应模块下新增 BUILD.gn target，参考同类 codec 的目录结构；
  (6) 验证：hb build av_codec -i（so）编译通过 + hb build av_codec -t（test）单测全绿。
  关键约束：新增 codec 需在 interfaces/kits/c/ 补充 C API（如需要）；所有新插件必须有对应单测。
why_it_matters:
 - 新需求开发：遵循标准流程避免"改了代码不知道改哪里"的问题
 - 插件发现：Build 系统通过 GN 编译时收集插件，不需要运行时动态注册
 - 质量保证：单测覆盖是新增功能的质量门槛，不可跳过
 - 扩展边界：明确知道在哪里扩展（plugins/）vs 哪里不要碰（frameworks/）
evidence:
 - kind: code
   ref: services/media_engine/plugins/demuxer/BUILD.gn
   anchor: 插件GN target声明
   note: |
     ohos_shared_library("media_plugin_FFmpegDemuxer") 和 ohos_shared_library("media_plugin_MPEG4Demuxer")
     通过 sources=[...] 包含所有 .cpp 文件；external_deps 链接 ffmpeg 库
 - kind: code
   ref: services/media_engine/plugins/demuxer/mpeg4_demuxer/mpeg4_demuxer_plugin.h
   anchor: 插件实现模板
   note: |
     继承 DemuxerPlugin，实现 SetDataSource / GetMediaInfo / SelectTrack / ReadSampleData
     参照接口 interfaces/plugin/demuxer_plugin.h 的纯虚函数定义
 - kind: code
   ref: services/media_engine/plugins/demuxer/BUILD.gn
   anchor: 插件编译链路
   note: |
     BUILD.gn 中 demuxer_config 定义 include_dirs 和编译参数
     media_plugin_FFmpegDemuxer deps = [ "$av_codec_root_dir/services/dfx:av_codec_service_dfx" ]
     插件与 dfx 模块链接，SetFaultEvent 可用
 - kind: code
   ref: interfaces/plugin/demuxer_plugin.h
   anchor: 插件基类接口
   note: DemuxerPlugin 继承 PluginBase，纯虚接口：SetDataSource/GetUserMeta/SelectTrack/UnselectTrack/ReadSample/SeekToTime
 - kind: code
   ref: interfaces/plugin/muxer_plugin.h
   anchor: MuxerPlugin基类
   note: MuxerPlugin 继承 PluginBase，实现 WriteSample / SetOffset 等接口
 - kind: build
   ref: hb build av_codec -i --skip-download
   anchor: 编译命令
   note: -i 编译so；--skip-download 避免重复拉取依赖库
 - kind: build
   ref: hb build av_codec -t
   anchor: 单测编译命令
   note: -t 编译测试目标；单测在 test/moduletest/ 各模块下按 BUILD.gn 执行
 - kind: code
   ref: test/moduletest/vcodec/BUILD.gn
   anchor: 单测target规范
   note: 同名 codec 单测命名规范：模块名_moduletest_native（参考 hwdecoder_moduletest）
related:
 - MEM-ARCH-AVCODEC-003
 - MEM-ARCH-AVCODEC-007
 - MEM-DEVFLOW-001
 - MEM-DEVFLOW-002
 - MEM-DEVFLOW-006
owner: 耀耀
review:
  owner: 耀耀
  approved_at: "2026-04-17"
  change_policy: update_on_code_change
update_trigger: code_change
created_at: "2026-04-17"
updated_at: "2026-04-17"
