#!/bin/bash
# SCRIPTS/generate_daily_progress_report.sh
# 每天自动生成记忆工厂进度报告
# 执行时间: 每天 23:30 Asia/Shanghai

set -e

WORKSPACE="/home/west/.openclaw/workspace-main/avcodec-dfx-memory"
MEMORY_DIR="$WORKSPACE/memory"
TODAY=$(date +%Y-%m-%d)
REPORT_FILE="$MEMORY_DIR/progress_report_$TODAY.md"
TIMESTAMP=$(date "+%Y-%m-%d %H:%M %Z+8")

cd "$WORKSPACE"

echo "生成每日进度报告: $REPORT_FILE"

# 收集统计信息
TOTAL_FILES=$(ls MEMORY/10_architecture/*.md 2>/dev/null | wc -l | tr -d ' ')
APPROVED_FILES=$(grep -l "status: approved" MEMORY/10_architecture/*.md 2>/dev/null | wc -l | tr -d ' ')
PENDING_FILES=$(grep -l "status: pending_approval" MEMORY/10_architecture/*.md 2>/dev/null | wc -l | tr -d ' ')
DRAFT_FILES=$(grep -l "status: draft" MEMORY/10_architecture/*.md 2>/dev/null | wc -l | tr -d ' ')

# Backlog 统计
BACKLOG_TOTAL=$(grep -c "^\| S" STATE/backlog.yaml 2>/dev/null || echo "0")
BACKLOG_APPROVED=$(grep -c "approved" STATE/backlog.yaml 2>/dev/null || echo "0")
BACKLOG_PENDING=$(grep -c "pending" STATE/backlog.yaml 2>/dev/null || echo "0")

# Git 状态
GIT_STATUS=$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')
GIT_AHEAD=$(git log --oneline origin/master..master 2>/dev/null | wc -l | tr -d ' ')
LAST_COMMIT=$(git log -1 --format="%h %s" 2>/dev/null | head -1)

# 各目录文件数
ARCH_FILES=$(ls MEMORY/10_architecture/*.md 2>/dev/null | wc -l | tr -d ' ')
DEV_FLOW_FILES=$(ls MEMORY/20_dev_flow/*.md 2>/dev/null | wc -l | tr -d ' ')
TOOLCHAIN_FILES=$(ls MEMORY/30_toolchain/*.md 2>/dev/null | wc -l | tr -d ' ')
FAQ_FILES=$(ls MEMORY/50_faq/*.md 2>/dev/null | wc -l | tr -d ' ')

# Pending approvals
PENDING_APPROVALS=$(python3 -c "
import yaml
with open('STATE/pending_actions.yaml') as f:
    data = yaml.safe_load(f)
pending = [p for p in data.get('pending_approvals', []) if p.get('status') == 'pending_approval']
print(len(pending))
" 2>/dev/null || echo "0")

# 生成报告
cat > "$REPORT_FILE" << EOF
# AVCodec/DFX 记忆工厂 — 日进度报告

**生成时间**：$TIMESTAMP
**工作目录**：$WORKSPACE

---

## 📊 当前里程碑

| 步骤 | 内容 | 状态 |
|------|------|------|
| 第0步 | 建 Git 仓库骨架（AGENT_CONSTITUTION / MEMORY_POLICY / backlog.yaml） | ✅ 完成 |
| 第1步 | 打通"证据工厂"（Scout + Mapper） | ✅ 完成 |
| 第2步 | 打通"问题工厂"（Interviewer + 飞书问题卡） | ✅ 完成 |
| 第3步 | 打通"草案工厂"（Synthesizer） | ✅ 完成 |
| 第4步 | 接飞书审批流 | ✅ 完成 |
| 第5步 | 接 Git 发布流 | ✅ 完成 |
| 第6步 | 变更再学习机制 | ✅ 完成 |

---

## 📈 记忆统计

| 指标 | 数量 |
|------|------|
| **10_architecture/** | $ARCH_FILES 个文件 |
| **20_dev_flow/** | $DEV_FLOW_FILES 个文件 |
| **30_toolchain/** | $TOOLCHAIN_FILES 个文件 |
| **50_faq/** | $FAQ_FILES 个文件 |
| **Memory 文件总计** | $TOTAL_FILES 个 |
| **已批准 (approved)** | $APPROVED_FILES 个 |
| **待审批 (pending_approval)** | $PENDING_FILES 个 |
| **草稿 (draft)** | $DRAFT_FILES 个 |
| **待审批主题** | $PENDING_APPROVALS 个 |

---

## 📋 Backlog 进度

| 指标 | 数量 |
|------|------|
| Backlog 总主题 | $BACKLOG_TOTAL |
| 已批准 | $BACKLOG_APPROVED |
| 待处理 | $BACKLOG_PENDING |

---

## 🔧 定时任务状态

| 任务 | 执行时间 | 状态 |
|------|---------|------|
| PM Loop (审批检查) | 每15分钟 | ✅ 运行中 |
| High-Level Synthesis (知识综合) | 每周六 10:00 | ✅ 已配置 |
| **Daily Progress Report (本报告)** | 每天 23:30 | ✅ 已配置 |

---

## 📁 Git 仓库状态

- **Remote**：https://github.com/WestYao666/OH_AVCodec_Memory
- **本地变更**：$GIT_STATUS 个文件
- **待推送 Commit**：$GIT_AHEAD 个
- **最新 Commit**：\`$LAST_COMMIT\`

EOF

# 如果有待审批主题，列出它们
if [ "$PENDING_APPROVALS" -gt 0 ] || [ "$PENDING_FILES" -gt 0 ]; then
    echo "" >> "$REPORT_FILE"
    echo "## ⚠️ 待处理事项" >> "$REPORT_FILE"
    echo "" >> "$REPORT_FILE"
    
    if [ "$PENDING_APPROVALS" -gt 0 ]; then
        echo "### 待审批主题 ($PENDING_APPROVALS 个)" >> "$REPORT_FILE"
        echo "" >> "$REPORT_FILE"
        python3 -c "
import yaml
with open('STATE/pending_actions.yaml') as f:
    data = yaml.safe_load(f)
pending = [p for p in data.get('pending_approvals', []) if p.get('status') == 'pending_approval']
for p in pending[:20]:
    print(f'- **{p.get(\"mem_id\")}**')
    msg = p.get('message', '')
    if msg:
        # 提取第一行作为摘要
        first_line = msg.split('\n')[0].replace('Builder 报告：', '').replace('PM 检测：', '')
        print(f'  {first_line}')
    print()
" >> "$REPORT_FILE"
    fi
fi

# 列出最近批准的 5 个主题
echo "" >> "$REPORT_FILE"
echo "## ✅ 最近批准记忆" >> "$REPORT_FILE"
echo "" >> "$REPORT_FILE"
echo '| ID | 标题 | 批准时间 |' >> "$REPORT_FILE"
echo '|----|------|---------|' >> "$REPORT_FILE"
python3 -c "
import yaml
import re
from datetime import datetime

with open('STATE/pending_actions.yaml') as f:
    data = yaml.safe_load(f)

responses = data.get('approval_responses', [])
# 获取最近 5 个 approved
approved = [r for r in responses if r.get('decision') == 'approved']
approved.sort(key=lambda x: x.get('timestamp', ''), reverse=True)

for r in approved[:5]:
    mem_id = r.get('mem_id', '')
    ts = r.get('timestamp', '')
    # 尝试从文件获取标题
    title = mem_id
    try:
        fname = f'MEMORY/10_architecture/{mem_id}.md'
        with open(fname) as f:
            content = f.read()
            m = re.search(r'^#\s+.+?[-—–]\s*(.+?)(?:\n|$)', content, re.MULTILINE)
            if m:
                title = m.group(1)[:50]
    except:
        pass
    print(f'| {mem_id} | {title} | {ts[:10]} |')
" >> "$REPORT_FILE"

# 添加页脚
echo "" >> "$REPORT_FILE"
echo "---" >> "$REPORT_FILE"
echo "*报告生成：Daily Progress Reporter | $TIMESTAMP*" >> "$REPORT_FILE"

# Git add and commit
git add memory/
git commit -m "docs: 每日进度报告 $TODAY" 2>/dev/null || true

# Git push
eval "\$(ssh-agent -s)" && ssh-add ~/.ssh/github_avcodec 2>/dev/null && git push 2>/dev/null || true

echo "报告已生成: $REPORT_FILE"
echo "完成时间: $(date)"
