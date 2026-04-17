id: MEM-DEVFLOW-002
title: 单测入口与测试目录结构
type: dev_flow
scope: [Test, UnitTest, GN]
status: approved
confidence: high
summary: >
  AVCodec 单测位于 test/moduletest/ 目录下，按模块分类：
  audio_decoder / audio_encoder / vcodec / demuxer / muxer / capability。
  每个单测子目录都有独立的 BUILD.gn，使用 GN 构建。
  vcodec 目录下按 codec 类型再分：swdecoder（软件解码）、swencoder（软件编码）、hwdecoder（硬件解码）、encoder（编码通用）。
  测试入口通过 BUILD.gn 的 group / executable target 定义。
why_it_matters:
 - 新人入项：知道单测在哪、如何运行
 - 问题定位：遇到特定 codec 问题可以找对应单测参考
 - 新需求开发：新增 codec 需要参考同名codec的测试结构
evidence:
 - kind: code
   ref: test/moduletest/BUILD.gn
   anchor: 顶层测试入口
   note: 定义了所有模块测试的编译入口
 - kind: code
   ref: test/moduletest/vcodec/BUILD.gn
   anchor: 目录不存在
   note: vcodec 目录下没有统一 BUILD.gn，按 codec 类型分散在子目录
 - kind: code
   ref: test/moduletest/vcodec/swdecoder/BUILD.gn
   anchor: 软件解码单测
   note: avcswdecoder/h263swdecoder 等软件解码单测的 GN target
 - kind: code
   ref: test/moduletest/vcodec/encoder/BUILD.gn
   anchor: 编码单测
   note: avcswencoder 等编码单测的 GN target
 - kind: code
   ref: test/moduletest/capability/BUILD.gn
   anchor: 能力查询单测
   note: Codec 能力列表的单测
 - kind: code
   ref: test/moduletest/demuxer/BUILD.gn
   anchor: 解封装单测
   note: 解封装单测
 - kind: code
   ref: test/moduletest/muxer/BUILD.gn
   anchor: 封装单测
   note: 封装单测
related:
 - MEM-DEVFLOW-001
 - MEM-ARCH-AVCODEC-003
 - FAQ-SCENE1-002
owner: 耀耀
review:
  owner: 耀耀
  approved_at: "2026-04-17"
  change_policy: update_on_code_change
update_trigger: code_change
created_at: "2026-04-17"
updated_at: "2026-04-17"
