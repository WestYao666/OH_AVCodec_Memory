id: MEM-DEVFLOW-001
title: 构建入口与部件组织
type: dev_flow
scope: [Build, GN]
status: approved
confidence: high
summary: >
  av_codec 部件使用 GN（Generate Nearby）构建系统，通过 BUILD.gn 定义构建目标。
  顶层构建入口声明两个 public_deps：interfaces/inner_api/native:av_codec_client（客户端）和
  services/services:av_codec_service（服务端）。
  config.gni 定义全局编译配置。hisysevent.yaml 定义系统行为事件的 schema。
why_it_matters:
 - 新人构建第一步：知道用 GN 而非 Make/cmake
 - 新需求开发：新增模块必须遵守 GN 目录结构，否则无法编入
 - 问题定位：构建失败时常与 GN target 声明相关
evidence:
 - kind: code
   ref: BUILD.gn
   anchor: av_codec_packages
   note: 顶层 group，依赖 av_codec_client + av_codec_service
 - kind: code
   ref: config.gni
   anchor: 全局配置
   note: 包含编译选项、依赖路径等全局配置
 - kind: code
   ref: hisysevent.yaml
   anchor: 事件 schema
   note: 定义 CODEC_START_INFO / CODEC_STOP_INFO / FAULT / STATISTICS_INFO 四个事件域
 - kind: code
   ref: interfaces/inner_api/native/BUILD.gn
   anchor: 客户端构建
   note: capi 层 GN target
 - kind: code
   ref: services/services/BUILD.gn
   anchor: 服务端构建
   note: av_codec_service 的 GN target
related:
 - MEM-ARCH-AVCODEC-001
 - MEM-DEVFLOW-002
 - FAQ-SCENE1-001
owner: 耀耀
review:
  owner: 耀耀
  approved_at: "2026-04-17"
  change_policy: update_on_code_change
update_trigger: code_change
created_at: "2026-04-17"
updated_at: "2026-04-17"
