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

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
STATE_FILE = "/home/west/.openclaw/workspace-main/avcodec-dfx-memory/STATE/pending_actions.yaml"

class CallbackHandler(BaseHTTPRequestHandler):
    def send_json(self, code=0, msg="ok"):
        payload = json.dumps({"code": code, "msg": msg}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(payload))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path == "/":
            self.send_json(0, "feishu callback server running")
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        if self.path != "/callback":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"not found")
            return

        # Read content-length
        cl = int(self.headers.get("Content-Length", 0) or 0)
        if cl == 0:
            body = b""
        else:
            body = self.rfile.read(cl)

        print(f"[Callback] POST /callback — {cl} bytes", flush=True)

        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception as e:
            print(f"[Callback] JSON parse error: {e}", flush=True)
            self.send_json(1, f"invalid json: {e}")
            return

        # 解析飞书 card callback 格式: { "action": { "value": "approve:MEM-XXX" } }
        action_value = None
        if "action" in payload and isinstance(payload["action"], dict):
            action_value = payload["action"].get("value")

        if not action_value:
            print(f"[Callback] No action.value found in payload", flush=True)
            self.send_json(0, "no action.value")
            return

        decision, mem_id = action_value.split(":", 1) if ":" in action_value else (action_value, None)
        decision = decision.strip().lower()
        print(f"[Callback] decision={decision}, mem_id={mem_id}", flush=True)

        action = {
            "timestamp": datetime.now().isoformat() + "Z",
            "type": "card_callback",
            "decision": decision,
            "mem_id": mem_id,
            "raw_payload": payload
        }

        # 写入 pending_actions.yaml
        try:
            if os.path.exists(STATE_FILE):
                with open(STATE_FILE, "r") as f:
                    data = yaml.safe_load(f) or {}
                if not isinstance(data, dict):
                    data = {"queue": []}
            else:
                data = {"queue": []}

            data["last_updated"] = datetime.now().isoformat() + "Z"
            queue = data.setdefault("queue", [])

            # 查找同 mem_id 的 pending approval_request，更新 decision
            found = False
            for item in queue:
                if item.get("mem_id") == mem_id and item.get("type") == "approval_request":
                    item["decision"] = decision
                    item["timestamp"] = action["timestamp"]
                    found = True
                    print(f"[Callback] Updated approval_request for {mem_id} → {decision}", flush=True)
                    break

            if not found:
                action["type"] = "approval_response"
                queue.append(action)
                print(f"[Callback] Appended new approval_response for {mem_id}", flush=True)

            with open(STATE_FILE, "w") as f:
                yaml.dump(data, f, allow_unicode=True, default_flow_style=False)

        except Exception as e:
            print(f"[Callback] Write error: {e}", flush=True)

        self.send_json(0, "ok")

    def log_message(self, fmt, *args):
        print(f"[Callback] {fmt % args}", flush=True)

if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), CallbackHandler)
    print(f"Feishu callback server listening on 0.0.0.0:{PORT}", flush=True)
    print(f"Callback URL: http://<public-ip>:{PORT}/callback", flush=True)
    sys.stdout.flush()
    server.serve_forever()