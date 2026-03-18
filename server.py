#!/usr/bin/env python3
"""
CaloriTrack - Cloud server with shared storage
All data stored server-side in data.json so all devices see the same data.
"""

import os
import json
import threading
import urllib.request
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

PORT    = int(os.environ.get("PORT", 7842))
STATIC  = Path(__file__).parent / "static"
API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# Data file — on Railway, mount a Volume at /data for persistence
# Falls back to local directory if no volume mounted (ephemeral but works for testing)
DATA_DIR  = Path(os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", "."))
DATA_FILE = DATA_DIR / "caloritrack_data.json"

DEFAULT_DATA = {"ingredients": [], "rawIngredients": [], "recipes": []}

# Thread lock so concurrent requests don't corrupt the file
_lock = threading.Lock()

def read_data():
    with _lock:
        try:
            if DATA_FILE.exists():
                return json.loads(DATA_FILE.read_text())
        except Exception as e:
            print(f"  ! Error reading data: {e}")
        return dict(DEFAULT_DATA)

def write_data(data):
    with _lock:
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            DATA_FILE.write_text(json.dumps(data, indent=2))
            return True
        except Exception as e:
            print(f"  ! Error writing data: {e}")
            return False


class Handler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        print(f"  {self.command} {self.path} {args[1]}")

    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path, mime):
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

    MIME = {
        ".html": "text/html; charset=utf-8",
        ".json": "application/json",
        ".png":  "image/png",
        ".jpg":  "image/jpeg",
        ".ico":  "image/x-icon",
        ".js":   "application/javascript",
        ".css":  "text/css",
        ".webp": "image/webp",
    }

    def do_GET(self):
        path = self.path.split("?")[0]

        if path in ("/", "/index.html"):
            self.send_file(STATIC / "index.html", "text/html; charset=utf-8")

        elif path == "/api/data":
            self.send_json(read_data())

        elif path == "/api/status":
            key = API_KEY
            self.send_json({
                "has_key": bool(key),
                "key_preview": ("sk-ant-..." + key[-4:]) if key else ""
            })

        elif path.startswith("/api/"):
            self.send_json({"error": "not found"}, 404)

        else:
            # Serve static files (icons, manifest, sw.js, splash screens)
            static_file = STATIC / path.lstrip("/")
            if static_file.exists() and static_file.is_file():
                ext = static_file.suffix.lower()
                mime = self.MIME.get(ext, "application/octet-stream")
                self.send_file(static_file, mime)
            else:
                self.send_file(STATIC / "index.html", "text/html; charset=utf-8")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length))
        except Exception:
            self.send_json({"error": "invalid JSON"}, 400)
            return

        if self.path == "/api/data":
            ok = write_data(body)
            self.send_json({"ok": ok})
            return

        if self.path == "/api/claude":
            key = API_KEY
            if not key:
                self.send_json({"error": "ANTHROPIC_API_KEY not set on server."}, 401)
                return
            payload = json.dumps(body).encode()
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

        # ── Generate food image via Claude SVG ──────────────────────────────
        if self.path == "/api/food-image":
            key = API_KEY
            if not key:
                self.send_json({"error": "No API key"}, 401)
                return
            food_name = body.get("name", "food")
            prompt = f"""Create a beautiful, appetizing SVG illustration of "{food_name}" for a food tracking app.

Style: Clean, modern food illustration. Warm colors. Centered composition. No text labels.
Size: 200x200 viewBox. Use shapes, gradients, and details to make it look delicious and recognizable.
Output ONLY the raw SVG code starting with <svg and ending with </svg>. No explanation, no markdown."""

            req_body = json.dumps({
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 1500,
                "messages": [{"role": "user", "content": prompt}]
            }).encode()
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                data=req_body,
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": key,
                    "anthropic-version": "2023-06-01",
                },
                method="POST"
            )
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    result = json.loads(resp.read())
                svg = result.get("content", [{}])[0].get("text", "")
                # Extract SVG if wrapped in anything
                if "<svg" in svg:
                    svg = svg[svg.index("<svg"):svg.rindex("</svg>")+6]
                import base64
                b64 = base64.b64encode(svg.encode()).decode()
                data_uri = f"data:image/svg+xml;base64,{b64}"
                self.send_json({"imageUrl": data_uri})
            except Exception as e:
                self.send_json({"error": str(e)}, 500)
            return

        self.send_json({"error": "unknown endpoint"}, 404)


if __name__ == "__main__":
    print(f"\n  CaloriTrack")
    print(f"  Port    : {PORT}")
    print(f"  API key : {'set' if API_KEY else 'NOT SET'}")
    print(f"  Data    : {DATA_FILE}")
    vol = os.environ.get("RAILWAY_VOLUME_MOUNT_PATH")
    print(f"  Storage : {'Railway Volume at ' + vol if vol else 'Local (add Railway Volume for persistence)'}\n")
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
