#!/usr/bin/env python3
"""配置保存服务器 — 接收 POST 并写入 config.json"""
import json, os, sys
from http.server import HTTPServer, SimpleHTTPRequestHandler

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
STRATEGY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "strategy-config.json")

class Handler(SimpleHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _save_json(self, filepath, body, required_keys):
        cfg = json.loads(body)
        for key in required_keys:
            if key not in cfg:
                raise ValueError(f"缺少必要字段: {key}")
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return {"ok": True, "msg": "配置已保存，下次检查自动生效"}

    def _respond(self, data, code=200):
        self.send_response(code)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
        except Exception:
            return self._respond({"ok": False, "msg": "无法读取请求体"}, 400)

        if self.path == "/save":
            try:
                result = self._save_json(CONFIG_FILE, body, ["stocks", "risk"])
                self._respond(result)
            except Exception as e:
                self._respond({"ok": False, "msg": str(e)}, 400)
        elif self.path == "/save-strategy":
            try:
                result = self._save_json(STRATEGY_FILE, body, ["enabled", "threshold"])
                self._respond(result)
            except Exception as e:
                self._respond({"ok": False, "msg": str(e)}, 400)
        else:
            super().do_GET()

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8898
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    server = HTTPServer(("127.0.0.1", port), Handler)
    print(f"Config save server on http://127.0.0.1:{port}")
    server.serve_forever()
