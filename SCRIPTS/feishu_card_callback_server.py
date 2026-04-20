#!/usr/bin/env python3
"""
feishu_card_callback_server.py
飞书卡片回调服务端——接收飞书卡片的 button click callback，
解析 action value 并写入 STATE/pending_actions.yaml，供主 Agent 消费。

用法：
  python3 feishu_card_callback_server.py [port=3000]

回调 URL（飞书卡片配置）：
  https://<your-server>/callback
"""

import sys
import json
import yaml
import os
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
STATE_FILE = "/home/west/.openclaw/workspace-main/avcodec-dfx-memory/STATE/pending_actions.yaml"

class CallbackHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/callback":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"not found")
            return

        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len).decode("utf-8")
        print(f"[Callback] POST /callback — {content_len} bytes", flush=True)

        try:
            payload = json.loads(body)
        except Exception as e:
            print(f"[Callback] JSON parse error: {e}", flush=True)
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.wfile.write(json.dumps({"code": 1, "msg": "invalid json"}).encode())
            return

        # 解析 card callback
        # 飞书 card callback 格式: { "action": { "value": "approve:MEM-XXX" } }
        action = {
            "timestamp": datetime.now().isoformat() + "Z",
            "type": "card_callback",
            "raw_payload": payload
        }

        decision = None
        mem_id = None

        if "action" in payload and "value" in payload["action"]:
            value = payload["action"]["value"]
            print(f"[Callback] action.value = {value}", flush=True)
            if ":" in value:
                decision, mem_id = value.split(":", 1)
            else:
                decision = value
                mem_id = None

        if decision is None:
            print(f"[Callback] No decision found in payload", flush=True)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.wfile.write(json.dumps({"code": 0, "msg": "no decision"}).encode())
            return

        action["decision"] = decision
        action["mem_id"] = mem_id

        # 写入 pending_actions.yaml（保持 queue 结构）
        try:
            # 读取现有结构
            if os.path.exists(STATE_FILE):
                with open(STATE_FILE, "r") as f:
                    data = yaml.safe_load(f) or {}
                # 确保是 dict 结构
                if not isinstance(data, dict):
                    data = {"queue": []}
            else:
                data = {"queue": []}

            # 规范化 decision 值（统一为 approve/revise/reject/hold）
            norm_decision = decision.strip().lower()
            action["decision"] = norm_decision

            # 更新 last_updated
            data["last_updated"] = datetime.now().isoformat() + "Z"

            # 查找同 mem_id 的 pending_review 条目，更新为 approved/revise/reject
            queue = data.setdefault("queue", [])
            found = False
            for item in queue:
                if item.get("mem_id") == mem_id and item.get("type") == "approval_request":
                    item["decision"] = norm_decision
                    item["timestamp"] = action["timestamp"]
                    if "responder" in payload:
                        item["responder"] = payload.get("responder")
                    found = True
                    print(f"[Callback] Updated existing approval_request for {mem_id}", flush=True)
                    break

            if not found:
                # 没有 pending_request，直接追加 response
                action["type"] = "approval_response"
                queue.append(action)
                print(f"[Callback] Appended new approval_response for {mem_id}", flush=True)

            # 写回文件
            with open(STATE_FILE, "w") as f:
                yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
            print(f"[Callback] Written to {STATE_FILE}", flush=True)

        except Exception as e:
            print(f"[Callback] Write error: {e}", flush=True)
            action["write_error"] = str(e)

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.wfile.write(json.dumps({"code": 0, "msg": "ok"}).encode())

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.wfile.write(b"feishu callback server running\n")
        self.wfile.write(f"State file: {STATE_FILE}\n".encode())

    def log_message(self, fmt, *args):
        print(f"[Callback] {fmt % args}", flush=True)

if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), CallbackHandler)
    print(f"Feishu callback server listening on 0.0.0.0:{PORT}")
    print(f"Callback URL: http://<public-ip>:{PORT}/callback")
    sys.stdout.flush()
    server.serve_forever()