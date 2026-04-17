id: MEM-TOOLCHAIN-001
title: 常用代码导航工具与路径
type: toolchain
scope: [Toolchain, Navigation]
status: draft
confidence: high
summary: >
  AVCodec 代码仓常用导航命令：
  - find：按文件名查找特定模块
  - rg (ripgrep)：按符号/字符串全文搜索
  - cscope：符号索引搜索（需先生成索引）
  - clangd：IDE 语言服务器，提供跳转/补全
  关键路径速查：services/dfx（DFX）、services/media_engine/plugins/（插件）、interfaces/kits/c/（C API）
why_it_matters:
 - 新人入项：快速定位感兴趣的文件
 - 问题定位：快速找到特定函数/类/变量的定义位置
 - 代码 code review：快速追踪调用链
evidence:
 - kind: code
   ref: services/dfx/
   anchor: DFX模块路径
   note: avcodec_sysevent.cpp/h, avcodec_dump_utils.cpp, avcodec_xcollie.cpp
 - kind: code
   ref: services/media_engine/plugins/
   anchor: 插件模块路径
   note: demuxer/muxer/source/sink 四类插件
 - kind: code
   ref: interfaces/kits/c/
   anchor: C API路径
   note: native_avcodec_*.h 头文件
 - kind: doc
   ref: README_zh.md
   anchor: 模块说明
   note: 官方文档描述的模块边界
related:
 - MEM-ARCH-AVCODEC-001
 - MEM-DEVFLOW-001
 - FAQ-SCENE1-003
owner: 耀耀
review:
  owner: 耀耀
  approved_at: pending
  change_policy: update_on_code_change
update_trigger: code_change
created_at: "2026-04-17"
updated_at: "2026-04-17"
