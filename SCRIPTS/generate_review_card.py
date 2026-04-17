#!/usr/bin/env python3
"""
generate_review_card.py — 生成飞书审批卡片 JSON

用法：python3 generate_review_card.py <draft_yaml> [output_json]
示例：python3 generate_review_card.py DRAFTS/proposals/A1_scout_report.md

输出：飞书 Interactive Card JSON，支持：
  - approve（批准入库）
  - revise（需要修改）
  - reject（拒绝）
  - hold（暂不入库）
"""

import sys
import json
import yaml
import re
from pathlib import Path

def extract_text_from_markdown(md_text, max_lines=10):
    """从 markdown 提取前 N 行作为摘要"""
    lines = [l.strip() for l in md_text.split("\n") if l.strip() and not l.startswith("#")]
    return "\n".join(lines[:max_lines])

def extract_from_yaml(data):
    title = data.get("title", "未命名条目")
    summary = data.get("summary", "")
    evidence = data.get("evidence", [])
    scope = data.get("scope", [])
    owner = data.get("owner", "未知")
    mem_id = data.get("id", "DRAFT")
    return title, summary, evidence, scope, owner, mem_id

def generate_card(title, summary, evidence, scope, owner, mem_id, diff_text=""):
    """生成飞书 Interactive Card payload"""

    evidence_md = ""
    for i, ev in enumerate(evidence[:5], 1):
        kind = ev.get("kind", "unknown")
        ref = ev.get("ref", "N/A")
        note = ev.get("note", "")
        evidence_md += f"- [{kind}] {ref}"
        if note:
            evidence_md += f" — {note}"
        evidence_md += "\n"
    if len(evidence) > 5:
        evidence_md += f"- ...还有 {len(evidence) - 5} 条证据\n"

    card = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": f"📋 记忆审批：{title}"},
                "template": "blue"
            },
            "elements": [
                {
                    "tag": "markdown",
                    "content": f"**条目ID**: `{mem_id}`\n**Owner**: {owner}\n**Scope**: {' / '.join(scope)}"
                },
                {"tag": "hr"},
                {
                    "tag": "markdown",
                    "content": f"**摘要**:\n{summary[:300]}{'...' if len(summary) > 300 else ''}"
                },
                {"tag": "hr"},
                {
                    "tag": "markdown",
                    "content": f"**证据列表** ({len(evidence)} 条):\n{evidence_md}"
                }
            ],
            "actions": [
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "✅ 批准入库"},
                    "type": "primary",
                    "action": {
                        "type": "callback",
                        "value": f"approve:{mem_id}"
                    }
                },
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "🔧 需要修改"},
                    "type": "default",
                    "action": {
                        "type": "callback",
                        "value": f"revise:{mem_id}"
                    }
                },
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "❌ 拒绝"},
                    "type": "danger",
                    "action": {
                        "type": "callback",
                        "value": f"reject:{mem_id}"
                    }
                },
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "⏸ 暂不入库"},
                    "type": "default",
                    "action": {
                        "type": "callback",
                        "value": f"hold:{mem_id}"
                    }
                }
            ],
            "extra": {
                "mem_id": mem_id,
                "status": "pending_review"
            }
        }
    }
    return card

def main():
    if len(sys.argv) < 2:
        print("用法: python3 generate_review_card.py <draft_yaml_or_md> [output_json]")
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else None

    with open(input_path, "r", encoding="utf-8") as f:
        raw = f.read()

    # 判断文件类型
    if input_path.endswith(".yaml") or input_path.endswith(".yml"):
        try:
            data = yaml.safe_load(raw)
            title, summary, evidence, scope, owner, mem_id = extract_from_yaml(data)
            diff_text = ""
        except Exception as e:
            print(f"ERROR: YAML 解析失败: {e}")
            sys.exit(1)
    else:
        # markdown
        title = Path(input_path).stem.replace("_", " ").title()
        summary = extract_text_from_markdown(raw)
        evidence = []
        scope = []
        owner = "待定"
        mem_id = "DRAFT"
        diff_text = raw[:500]

    card = generate_card(title, summary, evidence, scope, owner, mem_id, diff_text)
    json_str = json.dumps(card, ensure_ascii=False, indent=2)

    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(json_str)
        print(f"Card written to: {output_path}")
    else:
        print(json_str)

if __name__ == "__main__":
    main()
