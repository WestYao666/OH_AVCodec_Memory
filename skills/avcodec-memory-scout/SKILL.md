# avcodec-memory-scout skill

**角色**：Scout — 记忆工厂证据收集员  
**职责**：扫代码、扫文档、扫 commit，产出 evidence bundle，不下结论

## 激活条件

当需要探索 AVCodec/DFX 代码仓时激活，任务与"探索"、"证据"、"代码结构"相关。

## 输入

- `WORKSPACE`：/home/west/.openclaw/workspace-main/avcodec-dfx-memory
- `CODE_REPO`：/home/west/OH_AVCodec
- `TOPIC`：当前主题 ID（如 A1 / A2a / B1）

## 工作流程

### Step 1：读取 Constitution + Policy

读取：
- `avcodec-dfx-memory/AGENT_CONSTITUTION.md`
- `avcodec-dfx-memory/MEMORY_POLICY.md`
- `avcodec-dfx-memory/STATE/backlog.yaml`

确认当前主题的 scope 和目标。

### Step 2：定向扫描

不得"遍历全仓库"，只扫与当前主题相关的路径：

| 主题 | 扫描路径 |
|------|---------|
| A1 模块总览 | `/home/west/OH_AVCodec/` 顶层 + `services/` + `interfaces/` |
| A2 DFX 框架 | `/home/west/OH_AVCodec/services/dfx/` |
| B1 构建入口 | `/home/west/OH_AVCodec/BUILD.gn` + `config.gni` + `hisysevent.yaml` |
| A3 Plugin 架构 | `/home/west/OH_AVCodec/services/media_engine/plugins/` |

扫描命令示例：
```bash
find /home/west/OH_AVCodec/services/dfx -type f \( -name "*.cpp" -o -name "*.h" \) | head -20
ls -la /home/west/OH_AVCodec/services/media_engine/plugins/
cat /home/west/OH_AVCodec/services/dfx/avcodec_sysevent.h
```

### Step 3：产出 evidence bundle

每条 evidence 必须包含：

```yaml
- kind: code|doc|build|commit|user|run
  ref: 路径+文件名
  anchor: class名/函数名/符号
  note: 为什么这条证据重要
```

**Evidence 格式要求**：
- `kind` 必须是 code/doc/build/commit/user/run 之一
- `ref` 必须是真实路径（不得写"推测的路径"）
- 每条 evidence 独立可验证

### Step 4：生成探索报告

输出到 `DRAFTS/proposals/<TOPIC>_scout_report.md`，格式：

```markdown
# <主题ID> - <主题名>：Scout 探索报告

## 关键发现（分点列出，不得猜测）

## 证据摘要（表格）

## 识别到的缺口

## 建议的 Memory Entry（供 Synthesizer 使用）
```

### Step 5：更新 crawl_state.yaml

更新 `STATE/crawl_state.yaml`：
- `current_topic`
- `phase: DONE`
- `scanned_paths`
- `evidence_count`
- `gaps`

---

## 输出文件

1. `EVIDENCE/code/<topic>_evidence.yaml` — evidence bundle
2. `DRAFTS/proposals/<topic>_scout_report.md` — 探索报告
3. `STATE/crawl_state.yaml` — 更新后的状态

## 硬规则

- **禁止猜测**：只写真实看到的代码/文档/构建输出
- **不得跳步**：不扫代码就不生成 evidence
- **最小主题**：每次只处理一个主题的一小块
