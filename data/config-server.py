#!/usr/bin/env python3
"""配置保存服务器 — 接收 POST 并写入 config.json"""
import json, os, sys
from http.server import HTTPServer, SimpleHTTPRequestHandler

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

class Handler(SimpleHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        if self.path == "/save":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                cfg = json.loads(body)
                # 验证基本结构
                if "stocks" not in cfg or "risk" not in cfg:
                    raise ValueError("配置结构不完整")
                with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                    json.dump(cfg, f, ensure_ascii=False, indent=2)
                self.send_response(200)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"ok":True, "msg":"配置已保存，下次检查自动生效"}).encode())
            except Exception as e:
                self.send_response(400)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"ok":False, "msg":str(e)}).encode())
        else:
            super().do_GET()

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8898
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    server = HTTPServer(("127.0.0.1", port), Handler)
    print(f"Config save server on http://127.0.0.1:{port}")
    server.serve_forever()
