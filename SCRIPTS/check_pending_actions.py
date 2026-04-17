#!/usr/bin/env python3
"""
check_pending_actions.py — 定时检查 pending_actions.yaml，
处理飞书审批指令，输出待处理的决策列表。

由 cron 或 heartbeat 调用。
"""

import yaml
from datetime import datetime

STATE_FILE = "/home/west/.openclaw/workspace-main/avcodec-dfx-memory/STATE/pending_actions.yaml"

def check():
    try:
        with open(STATE_FILE) as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        print("NO_FILE")
        return []

    queue = data.get("queue", [])
    if not queue:
        print("EMPTY")
        return []

    pending = [item for item in queue if item.get("type") == "approval_response"]
    if not pending:
        print("NO_PENDING")
        return []

    for item in pending:
        print(f"PENDING: {item.get('decision')} {item.get('mem_id')} {item.get('timestamp')}")
    return pending

if __name__ == "__main__":
    check()
