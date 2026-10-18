"""TailWatcher's web UI server: the dashboard page, its JSON data, and /health.

No login by default: it's an admin panel for a household server, reachable
only where StartOS exposes it. With "Require Web UI password" on in
Configure, everything except /health (the StartOS health check) needs the
password from /data/webui.json via HTTP Basic auth (any username); StartOS
writes it at install and "Show Web UI Password" displays it.
"""

import base64
import hmac
import json
import os
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

WEB_DIR = os.environ.get("TW_WEB_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "web"))
PASSWORD_PATH = os.environ.get("TW_WEB_PASSWORD", "/data/webui.json")
FILES = {"/": ("index.html", "text/html; charset=utf-8"),
         "/index.html": ("index.html", "text/html; charset=utf-8"),
         "/icon.svg": ("icon.svg", "image/svg+xml")}


def read_password(path=PASSWORD_PATH):
    try:
        with open(path) as f:
            return (json.load(f).get("password") or "").strip() or None
    except (OSError, ValueError, AttributeError):
        return None


def authorized(header, password):
    if not password or not header or not header.startswith("Basic "):
        return False
    try:
        _, _, given = base64.b64decode(header[6:]).decode("utf-8").partition(":")
    except (ValueError, UnicodeDecodeError):
        return False
    return hmac.compare_digest(given.encode(), password.encode())


def make_handler(health, snapshot, password_path=PASSWORD_PATH, web_dir=WEB_DIR,
                 require_password=lambda: False):
    class Handler(BaseHTTPRequestHandler):
        def reply(self, code, body, ctype="application/json", extra=None):
            if isinstance(body, (dict, list)):
                body = json.dumps(body)
            if isinstance(body, str):
                body = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urllib.parse.urlparse(self.path).path
            if path == "/health":
                return self.reply(200, health.get())
            password = read_password(password_path) if require_password() else None
            if require_password() and not password:
                return self.reply(503, "The Web UI password hasn't been set up yet. Restart TailWatcher.",
                                  "text/plain; charset=utf-8")
            if password and not authorized(self.headers.get("Authorization"), password):
                return self.reply(401, "Use the password from TailWatcher → Actions → Show Web UI Password.",
                                  "text/plain; charset=utf-8",
                                  {"WWW-Authenticate": 'Basic realm="TailWatcher", charset="UTF-8"'})
            if path == "/api/state":
                return self.reply(200, snapshot())
            if path in FILES:
                name, ctype = FILES[path]
                try:
                    with open(os.path.join(web_dir, name), "rb") as f:
                        return self.reply(200, f.read(), ctype)
                except OSError:
                    pass
            return self.reply(404, "Not found", "text/plain; charset=utf-8")

        def log_message(self, *args):
            pass

    return Handler


def serve(port, health, snapshot, password_path=PASSWORD_PATH, web_dir=WEB_DIR,
          require_password=lambda: False):
    srv = ThreadingHTTPServer(("0.0.0.0", port),
                              make_handler(health, snapshot, password_path, web_dir, require_password))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
