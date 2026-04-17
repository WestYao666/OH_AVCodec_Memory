# avcodec-memory-factory skill

**角色**：记忆工厂总调度 — 负责协调 Scout/Mapper/Synthesizer/Reviewer/Publisher 的工作流  
**激活条件**：任何与 AVCodec/DFX 记忆工厂相关的任务

## 环境变量

```
WORKSPACE=/home/west/.openclaw/workspace-main/avcodec-dfx-memory
CODE_REPO=/home/west/OH_AVCodec
GIT_REMOTE=git@github.com:WestYao666/OH_AVCodec_Memory.git
SSH_KEY=$HOME/.ssh/github_avcodec
FEISHU_APP_ID=cli_a948ccbd9db81bc9
FEISHU_APP_SECRET=HjK7kInCyQOcc2sSLY6b1lnLfXB8utbC
FEISHU_CHAT_ID=oc_459341b87039573d4844caa5b15e7c36
```

## 整体工作流

```
PICK_TOPIC    → 从 backlog 取一个 pending 主题
EXPLORE       → Scout 扫描代码，产 evidence bundle
GAP_CHECK     → Mapper 检查证据缺口
ASK_HUMAN     → Interviewer 发飞书问题卡（如果有缺口）
MERGE         → Synthesizer 合并 evidence + 用户回答
DRAFT         → 生成 memory entry 草案
REVIEW_PREP   → Reviewer 发飞书审批卡
WAIT_APPROVAL → 等待用户在飞书回复 approve/revise/reject/hold
APPROVED      → Publisher push 到 GitHub
```

## 子角色 SKILL 参考

| 角色 | skill file |
|------|-----------|
| Scout | `skills/avcodec-memory-scout/SKILL.md` |
| Reviewer | `skills/avcodec-memory-reviewer/SKILL.md` |

---

## 调度命令

### 选主题
```bash
TOPIC=$(python3 -c "
import yaml
with open('$WORKSPACE/STATE/backlog.yaml') as f:
    data = yaml.safe_load(f)
for item in data.get('backlog', []):
    if item.get('status') == 'pending':
        print(item.get('id') + '|' + item.get('topic'))
        break
")
echo "TOPIC=$TOPIC"
```

### 更新 backlog 状态
```bash
python3 -c "
import yaml
with open('$WORKSPACE/STATE/backlog.yaml') as f:
    data = yaml.safe_load(f)
for item in data.get('backlog', []):
    if item.get('status') == 'pending':
        item['status'] = 'in_progress'
        break
with open('$WORKSPACE/STATE/backlog.yaml', 'w') as f:
    yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
"
```

### Git push 标准流程
```bash
cd $WORKSPACE
git add ...
git commit -m "[MEM] <mem_id> <action> - <summary>"
GIT_SSH_COMMAND="ssh -i $SSH_KEY" git push origin master
```

---

## 飞书发送工具函数

```python
def feishu_send_text(token, chat_id, text):
    req = urllib.request.Request(
        "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
        data=json.dumps({"receive_id": chat_id, "msg_type": "text", "content": json.dumps({"text": text})}).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

def feishu_get_token(app_id, app_secret):
    req = urllib.request.Request(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        data=json.dumps({"app_id": app_id, "app_secret": app_secret}).encode(),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read()).get("tenant_access_token", "")
```

---

## 标准化 commit message 格式

```
[MEM] {mem_id} {action} - {short summary}
[STATE] {description}
[SCRIPTS] {description}
[WORKFLOWS] {description}
[DRAFTS] {description}
```

## 关键约束

- **小步完整**：每个主题必须完整走完探索→草案→审批→发布
- **人在环**：缺口必须问耀耀，不得猜测
- **Git 是唯一真相**：所有 stable 记忆必须 commit 到 GitHub
- **飞书是唯一审批入口**：审批只在飞书会话里进行
