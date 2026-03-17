#!/usr/bin/env python3
"""
CaloriTrack - Cloud server
Runs on Railway, Render, Heroku, or any PaaS.
API key set via ANTHROPIC_API_KEY environment variable.
"""

import os
import json
import urllib.request
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

PORT      = int(os.environ.get("PORT", 7842))
STATIC    = Path(__file__).parent / "static"
# API key comes from environment variable (set in Railway/Render dashboard)
API_KEY   = os.environ.get("ANTHROPIC_API_KEY", "")


class Handler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        print(f"  {self.command} {self.path} — {args[1]}")

    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path: Path, mime: str):
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            f = STATIC / "index.html"
            self.send_file(f, "text/html; charset=utf-8")
        elif path == "/api/status":
            key = API_KEY
            self.send_json({
                "has_key": bool(key),
                "key_preview": ("sk-ant-..." + key[-4:]) if key else ""
            })
        elif path.startswith("/api/"):
            self.send_json({"error": "not found"}, 404)
        else:
            # All non-API unknown routes serve index.html (SPA fallback)
            f = STATIC / "index.html"
            self.send_file(f, "text/html; charset=utf-8")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(length))
        except Exception:
            self.send_json({"error": "invalid JSON"}, 400)
            return

        if self.path == "/api/claude":
            key = API_KEY
            if not key:
                self.send_json({"error": "ANTHROPIC_API_KEY environment variable not set on server."}, 401)
                return

            payload = json.dumps(data).encode()
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": key,
                    "anthropic-version": "2023-06-01",
                },
                method="POST"
            )
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    self.send_json(json.loads(resp.read()))
            except urllib.error.HTTPError as e:
                try:
                    err = json.loads(e.read())
                    msg = err.get("error", {}).get("message", str(e))
                except Exception:
                    msg = f"HTTP {e.code}"
                self.send_json({"error": msg}, e.code)
            except urllib.error.URLError as e:
                self.send_json({"error": f"Network error: {e.reason}"}, 503)
            return

        self.send_json({"error": "unknown endpoint"}, 404)


if __name__ == "__main__":
    print(f"\n  CaloriTrack running on port {PORT}")
    print(f"  API key: {'✓ set' if API_KEY else '✗ NOT SET — add ANTHROPIC_API_KEY env var'}\n")
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    server.serve_forever()
