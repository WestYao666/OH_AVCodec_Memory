#!/usr/bin/env python3
"""
feishu_card_callback_server.py
飞书卡片回调服务端——接收飞书卡片的 button click callback，
解析 action value 并写入 STATE/pending_actions.yaml，供主 Agent 消费。

用法：
  python3 feishu_card_callback_server.py [port=3000]
"""

import sys
import json
import yaml
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
            return

        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len).decode("utf-8")

        try:
            payload = json.loads(body)
        except Exception:
            self.send_response(400)
            self.wfile.write(b"invalid json")
            return

        # 记录 action
        action = {
            "timestamp": datetime.now().isoformat() + "Z",
            "raw": payload
        }

        # 尝试解析 card callback 常用格式
        # 飞书 card callback: { "action": { "value": "approve:MEM-XXX" } }
        if "action" in payload and "value" in payload["action"]:
            value = payload["action"]["value"]
            if ":" in value:
                decision, mem_id = value.split(":", 1)
                action["decision"] = decision
                action["mem_id"] = mem_id
                action["type"] = "card_callback"
            else:
                action["decision"] = value
                action["type"] = "text_reply"
        else:
            action["type"] = "unknown"

        # 写入 pending_actions.yaml
        try:
            existing = []
            try:
                with open(STATE_FILE) as f:
                    existing = yaml.safe_load(f) or []
            except FileNotFoundError:
                pass

            existing.append(action)
            with open(STATE_FILE, "w") as f:
                yaml.dump(existing, f, allow_unicode=True, default_flow_style=False)
        except Exception as e:
            action["write_error"] = str(e)

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.wfile.write(json.dumps({"code": 0, "msg": "ok"}).encode())

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.wfile.write(b"feishu callback server running")

    def log_message(self, fmt, *args):
        print(f"[Callback] {fmt % args}")

if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), CallbackHandler)
    print(f"Feishu callback server listening on 0.0.0.0:{PORT}")
    print(f"Callback URL: http://<public-ip>:{PORT}/callback")
    sys.stdout.flush()
    server.serve_forever()
