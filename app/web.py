"""TailWatcher's web UI server: the dashboard page, its JSON data, and /health.

No login by default: it's an admin panel for a household server, reachable
only where StartOS exposes it. With "Require Web UI password" on in
Configure, everything except /health (the StartOS health check) needs the
password from /data/webui.json via HTTP Basic auth (any username); StartOS
writes it at install and "Show Web UI Password" displays it. A plain Docker
install has no StartOS init, so ensure_password() makes it on first start
(or takes $TAILWATCHER_PASSWORD).

Edits are JSON POSTs to /api/... carrying an "X-TailWatcher: 1" header, and
an Origin, if sent, must match the Host. Browsers won't let another website
add that header without a CORS preflight (which this server never answers),
so a page elsewhere can't make your browser change your lists.
"""

import base64
import hmac
import json
import os
import secrets
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

WEB_DIR = os.environ.get("TW_WEB_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "web"))
PASSWORD_PATH = os.environ.get("TW_WEB_PASSWORD", "/data/webui.json")
FILES = {"/": ("index.html", "text/html; charset=utf-8"),
         "/index.html": ("index.html", "text/html; charset=utf-8"),
         "/icon.svg": ("icon.svg", "image/svg+xml"),
         "/guide.md": ("guide.md", "text/markdown; charset=utf-8")}  # instructions.md, for ? Help


def read_password(path=PASSWORD_PATH):
    try:
        with open(path) as f:
            return (json.load(f).get("password") or "").strip() or None
    except (OSError, ValueError, AttributeError):
        return None


# Same alphabet as newPassword() in startos/fileModels/webui.json.ts (no l, I, O, 0, 1).
PASSWORD_CHARS = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def write_password(password, path=PASSWORD_PATH):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"password": password}, f)
    os.replace(tmp, path)


def new_password(path=PASSWORD_PATH):
    password = "".join(secrets.choice(PASSWORD_CHARS) for _ in range(20))
    write_password(password, path)
    return password


def ensure_password(path=PASSWORD_PATH, wanted=None):
    """The dashboard password, made if there isn't one. `wanted` (from
    $TAILWATCHER_PASSWORD) replaces whatever is stored."""
    wanted = (wanted or "").strip()
    if wanted:
        if read_password(path) != wanted:
            write_password(wanted, path)
        return wanted
    return read_password(path) or new_password(path)


def authorized(header, password):
    if not password or not header or not header.startswith("Basic "):
        return False
    try:
        _, _, given = base64.b64decode(header[6:]).decode("utf-8").partition(":")
    except (ValueError, UnicodeDecodeError):
        return False
    return hmac.compare_digest(given.encode(), password.encode())


MAX_BODY = 64 * 1024
MAX_IMPORT = 3 * 1024 * 1024  # a saved confirmation email, inline images and all


def same_origin(origin, host):
    if not origin:
        return True  # same-origin GETs and non-browser clients often omit it
    return urllib.parse.urlparse(origin).netloc == (host or "")


def make_handler(health, snapshot, password_path=PASSWORD_PATH, web_dir=WEB_DIR,
                 require_password=lambda: False, post=None, public=None):
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

        def locked(self):
            """Send the password challenge if one is needed and missing; True if sent."""
            password = read_password(password_path) if require_password() else None
            if require_password() and not password:
                self.reply(503, "The Web UI password hasn't been set up yet. Restart TailWatcher.",
                           "text/plain; charset=utf-8")
                return True
            if password and not authorized(self.headers.get("Authorization"), password):
                self.reply(401, "Use the password from TailWatcher → Actions → Show Web UI Password.",
                           "text/plain; charset=utf-8",
                           {"WWW-Authenticate": 'Basic realm="TailWatcher", charset="UTF-8"'})
                return True
            return False

        def do_POST(self):
            path = urllib.parse.urlparse(self.path).path
            if self.locked():
                return
            if (self.headers.get("X-TailWatcher") != "1"
                    or not (self.headers.get("Content-Type") or "").startswith("application/json")
                    or not same_origin(self.headers.get("Origin"), self.headers.get("Host"))):
                return self.reply(403, {"ok": False, "message": "Edits must come from the TailWatcher page."})
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            if not 0 < length <= (MAX_IMPORT if path == "/api/import" else MAX_BODY):
                return self.reply(400, {"ok": False, "message": "Bad request."})
            try:
                data = json.loads(self.rfile.read(length))
            except ValueError:
                return self.reply(400, {"ok": False, "message": "Bad request."})
            if post is None or not isinstance(data, dict):
                return self.reply(404, {"ok": False, "message": "Not found."})
            code, body = post(path, data)
            return self.reply(code, body)

        def do_GET(self):
            path = urllib.parse.urlparse(self.path).path
            if path == "/health":
                return self.reply(200, health.get())
            # Invite pages are for people without dashboard access, so they skip the
            # password; each shows one person's subscribe details behind a random token.
            if path.startswith("/join/") and public is not None:
                code, page = public(path[len("/join/"):])
                return self.reply(code, page, "text/html; charset=utf-8",
                                  {"X-Robots-Tag": "noindex, nofollow"})
            if path != "/icon.svg" and self.locked():
                return
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
          require_password=lambda: False, post=None, public=None):
    srv = ThreadingHTTPServer(("0.0.0.0", port),
                              make_handler(health, snapshot, password_path, web_dir, require_password, post, public))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
