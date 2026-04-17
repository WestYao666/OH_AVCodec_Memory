# AVCodec / DFX 长期记忆仓库

**Evidence-driven · Human-in-the-Loop · Incremental · Git-Auditable**

---

## 这是什么

AVCodec / DFX 领域的长期记忆资产仓库，服务于四类场景：

1. **新人入项问答** — 系统总览、模块地图、术语表、开发环境入项 FAQ
2. **三方应用问题解答** — 接入契约、能力边界、字段定义、故障排查
3. **新需求开发** — 架构视图、可扩展点、场景矩阵、开发约束
4. **问题定位与修复** — 故障树、日志路径、回归清单

---

## 设计原则

- **证据优先，禁止猜想**：所有记忆必须带来源，无 evidence 不入库
- **人在环审批**：未经过 approve 的记忆不得写入 Git 主库
- **小步完整**：每次只处理一个最小主题，完整走完探索→草案→审批→发布
- **Git 可审计**：所有变更可追溯、可 review、可回滚

---

## 仓库结构

```
avcodec-dfx-memory/
├─ AGENT_CONSTITUTION.md   # Agent 行为准则
├─ MEMORY_POLICY.md        # 记忆入库政策
├─ CHANGELOG.md            # 变更历史
├─ MEMORY_SCHEMA/          # 条目结构定义（JSON Schema）
├─ STATE/                  # 当前工作状态（backlog / crawl_state / pending_questions / publish_queue）
├─ MEMORY/                 # 长期记忆（按主题分类）
│ ├─ 00_domain_map/        # 术语表、领域总览
│ ├─ 10_architecture/       # 架构事实
│ ├─ 20_dev_flow/          # 开发流程
│ ├─ 30_toolchain/          # 工具链
│ ├─ 40_scenarios/          # 场景矩阵
│ ├─ 50_faq/               # FAQ
│ └─ 90_decisions/          # 架构决策记录（ADR）
├─ EVIDENCE/               # 证据索引（代码/文档/commit/用户确认）
├─ DRAFTS/                 # 待审批草案
├─ SCRIPTS/                # 工具脚本
└─ WORKFLOWS/              # 自动化工作流定义
```

---

## 核心工作流

```
IDLE
 -> PICK_TOPIC        （从 backlog 选一个最小主题）
 -> EXPLORE_EVIDENCE  （Scout 扫代码/文档产出 evidence）
 -> GAP_CHECK         （Mapper 检查证据缺口）
 -> ASK_HUMAN         （Interviewer 发飞书问题卡）
 -> WAIT_HUMAN_REPLY  （等待耀耀回答）
 -> MERGE_HUMAN_EVIDENCE （Synthesizer 合并证据）
 -> DRAFT_MEMORY      （生成记忆草案）
 -> REVIEW_PREP       （Reviewer 生成 diff + 审批卡）
 -> WAIT_APPROVAL     （等待耀耀审批）
 -> APPROVED -> PUBLISH_GIT -> DONE
```

---

## 当前里程碑

- [ ] 第0步：建 Git 仓库 + 写入 Constitution + Policy + Backlog ← 当前进度
- [ ] 第1步：打通证据工厂（Scout + Mapper）
- [ ] 第2步：打通问题工厂（Interviewer + 飞书问题卡）
- [ ] 第3步：打通草案工厂（Synthesizer）
- [ ] 第4步：接飞书审批流
- [ ] 第5步：接 Git 发布流
- [ ] 第6步：变更再学习机制

---

## 负责 Agent

本仓库由 **AVCodec / DFX 长期记忆工厂 Agent**（运行于 OpenClaw）维护。

Agent 角色：Scout · Mapper · Interviewer · Synthesizer · Reviewer · Publisher
