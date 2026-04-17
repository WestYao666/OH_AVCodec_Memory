# avcodec-memory-reviewer skill

**角色**：Reviewer — 记忆工厂审批决策员  
**职责**：生成 diff，准备审批卡片，处理审批结果，管理 review ticket

## 激活条件

当有草案（draft）需要审批时激活，或用户回复了 approval 指令。

## 核心文件路径

- `WORKSPACE`：`/home/west/.openclaw/workspace-main/avcodec-dfx-memory`
- `MEMORY_DIR`：`avcodec-dfx-memory/MEMORY`
- `DRAFTS_DIR`：`avcodec-dfx-memory/DRAFTS/proposals`
- `STATE_DIR`：`avcodec-dfx-memory/STATE`
- `SCRIPTS_DIR`：`avcodec-dfx-memory/SCRIPTS`

---

## 技能 A：发审批卡

当草案生成完毕，调用此技能发飞书审批卡。

### 输入

- `draft_file`：草案文件路径
- `mem_id`：记忆条目 ID（如 `MEM-ARCH-AVCODEC-003`）

### 步骤

1. **读取草案**，提取 summary / evidence / scope / owner

2. **生成飞书 interactive card**（使用 `generate_review_card.py`）：

```python
python3 SCRIPTS/generate_review_card.py DRAFTS/proposals/A3_xxx.md DRAFTS/review_cards/REV-xxx.json
```

3. **发送到飞书会话**（chat_id: `oc_459341b87039573d4844caa5b15e7c36`，使用 big_clever_unlimited_minimax）

4. **卡片格式**（用 Python 直接发，不用 generate_review_card.py）：

```python
card = {
    "header": {
        "title": {"tag": "plain_text", "content": f"📋 记忆审批：{title}"},
        "template": "blue"
    },
    "elements": [
        {"tag": "markdown", "content": f"**条目ID**: `{mem_id}`\n**Owner**: {owner}\n**Scope**: {scope}"},
        {"tag": "hr"},
        {"tag": "markdown", "content": f"**摘要**:\n{summary}"},
        {"tag": "hr"},
        {"tag": "markdown", "content": f"**证据**: {n}条\n**Confidence**: {confidence}"},
        {"tag": "markdown", "content": "**请回复**：`approve` / `revise` / `reject` / `hold`"}
    ]
}
```

发送函数：
```python
def send_card(token, chat_id, title, mem_id, summary, evidence_count, scope):
    # ... 发送逻辑，见下方参考实现
```

### 参考实现（可直接复制）

```python
import urllib.request, json

def send_review_card(title, mem_id, summary, evidence_count, scope, owner="耀耀"):
    app_id = "cli_a948ccbd9db81bc9"
    app_secret = "HjK7kInCyQOcc2sSLY6b1lnLfXB8utbC"
    chat_id = "oc_459341b87039573d4844caa5b15e7c36"

    req = urllib.request.Request(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        data=json.dumps({"app_id": app_id, "app_secret": app_secret}).encode(),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as r:
        token = json.loads(r.read()).get("tenant_access_token", "")

    card = {
        "header": {"title": {"tag": "plain_text", "content": f"📋 记忆审批：{title}"}, "template": "blue"},
        "elements": [
            {"tag": "markdown", "content": f"**{mem_id}** | Owner: {owner}\n**Scope**: {scope}"},
            {"tag": "hr"},
            {"tag": "markdown", "content": f"**摘要**:\n{summary}"},
            {"tag": "hr"},
            {"tag": "markdown", "content": f"**证据**: {evidence_count}条 | **Confidence**: high"},
            {"tag": "markdown", "content": "请回复：`approve` / `revise` / `reject` / `hold`"}
        ]
    }
    payload = {"receive_id": chat_id, "msg_type": "interactive", "content": json.dumps(card)}
    req = urllib.request.Request(
        "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read()).get("code") == 0
```

---

## 技能 B：处理审批结果

当收到用户在飞书或此处的 `approve` / `revise` / `reject` / `hold` 指令时，执行此技能。

### 输入

- `decision`：approve | revise | reject | hold
- `mem_id`：记忆条目 ID

### 步骤

1. **读取当前草案文件**：`MEMORY/10_architecture/<mem_id>.md`

2. **根据 decision 分别处理**：

| decision | 操作 |
|----------|------|
| `approve` | status → approved，approved_at → 今天日期，git add + commit + push |
| `revise` | status → draft，追加修改意见到文件，开新的待确认问题 |
| `reject` | 移动到 `DRAFTS/rejected/`，记录原因 |
| `hold` | 留在原位，状态改为 hold |

3. **更新 backlog.yaml**：对应条目状态改为对应状态

4. **Git push**：
```bash
cd /home/west/.openclaw/workspace-main/avcodec-dfx-memory
git add MEMORY/...
git commit -m "[MEM] {mem_id} {decision}"
GIT_SSH_COMMAND="ssh -i $HOME/.ssh/github_avcodec" git push origin master
```

5. **发飞书通知**（approve 成功 / reject / revise 都需要通知）

6. **更新 STATE/backlog.yaml**

---

## 技能 C：生成 review ticket

每次审批完成后，记录到 `STATE/review_tickets.yaml`：

```yaml
- id: REV-20260417-xxx
  mem_id: MEM-ARCH-AVCODEC-XXX
  decision: approve
  reviewer: 耀耀
  decided_at: "2026-04-17T08:xx:00Z"
  comment: ""
```

---

## 硬规则

- 每张审批卡只包含一个记忆条目
- 审批结果必须写入 review ticket 并归档
- 只有 `approve` 才执行 Git push
- `revise` 必须给出具体的修改意见
