id: MEM-DEVFLOW-005
title: av_codec 开发环境搭建指南（WSL2 + 稀疏拉取）
type: dev_flow
scope: [Build, Environment, WSL2, Git]
status: approved
confidence: high
summary: >
  av_codec 开发环境搭建在 WSL2（Ubuntu-22.04）中进行，核心要点：
  (1) WSL2 迁移到非系统盘（D:\\wsl），避免C盘空间不足；
  (2) 换清华源加速依赖安装；
  (3) 通过 git 稀疏拉取（sparse-checkout）只拉代码、屏蔽 98% 的测试资源文件；
  (4) 安装 hb 编译工具（build 仓 + prebuilts_config.sh）；
  (5) 配置 VSCode c_cpp_properties.json 实现跨仓代码跳转；
  (6) 编译命令：hb build av_codec -i（so）+ hb build av_codec -t（test）。
why_it_matters:
 - 新人入项：解决"代码仓太大拉不动"和"本地编译卡住"两大痛点
 - 环境标准化：WSL2+稀疏拉取是官方推荐方案，可解决98%空间浪费
 - 问题定位：编译失败第一步查 hb 是否安装正确、sparse-checkout 是否生效
 - VSCode 跳转：避免"代码看得到但跳转失败"的开发体验问题
evidence:
 - kind: doc
   ref: https://gitee.com/westyao/westyao/raw/master/OpenHarmony/狴戔攭缂栧 20OH 20av_codec 20⑦827⑦86B96BC.md
   anchor: 全文
   note: 完整环境搭建指南，含 WSL2 配置 / 换源 / 稀疏拉取 / hb 安装 / VSCode配置 / 编译命令
 - kind: build
   ref: build/prebuilts_config.sh
   anchor: hb预编译脚本
   note: 安装 hb 工具的前置依赖脚本
 - kind: build
   ref: git clone --filter=blob:none --sparse
   anchor: 稀疏拉取命令
   note: 仅拉取代码，屏蔽 test/fuzztest/*/corpus 等大文件目录
 - kind: build
   ref: .git/info/sparse-checkout
   anchor: 稀疏拉取配置
   note: 屏蔽 /test/fuzztest/*/corpus、/test/moduletest/resources/*、/test/unittest/resources/*，只保留测试xml
 - kind: build
   ref: hb build av_codec -i --variant standard
   anchor: so编译命令
   note: --skip-download 避免重复拉取依赖库
 - kind: build
   ref: hb build av_codec -t --variant standard
   anchor: test编译命令
   note: 编译测试目标
related:
 - MEM-DEVFLOW-001
 - MEM-DEVFLOW-002
 - MEM-TOOLCHAIN-001
 - FAQ-SCENE1-001
owner: 耀耀
review:
  owner: 耀耀
  approved_at: "2026-04-17"
  change_policy: manual_review
update_trigger: manual_review
created_at: "2026-04-17"
updated_at: "2026-04-17"
