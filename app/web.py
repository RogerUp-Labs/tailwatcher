"""TailWatcher's web UI server: the dashboard page, its JSON data, and /health.

Three sign-in modes (config.json "webAuth", passed in as `mode`):
  off       no login: a household admin panel reachable only where StartOS
            exposes it (LAN/VPN by default).
  password  one shared password from /data/webui.json. StartOS writes it at
            install ("Show Web UI Password"); a plain Docker install has no
            StartOS init, so ensure_password() makes it on first start (or
            takes $TAILWATCHER_PASSWORD).
  accounts  family accounts (accounts.py): each person signs in with their own
            username and sees only their own watchers and trips.
Both login modes use the /login form and a session cookie (no JavaScript
needed, so it works over Tor); password mode also still takes HTTP Basic
auth for scripts. /health (the StartOS ready check), /login and invite pages
(/join/...) stay open.

Edits are JSON POSTs to /api/... carrying an "X-TailWatcher: 1" header, and
an Origin, if sent, must match the Host. Browsers won't let another website
add that header without a CORS preflight (which this server never answers),
so a page elsewhere can't make your browser change your lists.
"""

import base64
import hmac
import html
import json
import os
import secrets
import threading
import urllib.parse
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import accounts
import invites

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


COOKIE = "tw_session"
PLATFORM = os.environ.get("TW_PLATFORM", "startos")
THROTTLE = accounts.Throttle()

LOGIN_STYLE = invites.STYLE + """
form { background:var(--card); border:1px solid var(--line); border-radius:14px; padding:18px; display:grid; gap:14px; margin-top:14px; }
label { display:grid; gap:4px; font-size:14px; color:var(--muted); }
input { font:inherit; font-size:16px; padding:11px 12px; border-radius:10px; border:1px solid var(--line); background:var(--bg); color:var(--text); width:100%; }
input:focus { outline:2px solid var(--brand); outline-offset:0; }
button.btn.primary { background:var(--brand); border-color:var(--brand); color:var(--on-brand); font-weight:600; font-size:17px; padding:13px; }
.error { color:#c2312b; font-size:14px; margin:0; }
@media (prefers-color-scheme: dark) { .error { color:#ff6b63; } }
"""


def login_page(mode, error="", username=""):
    """The sign-in form (plain HTML, works with JavaScript off)."""
    e = html.escape
    if mode == "accounts":
        title, sub = "Sign in to TailWatcher", "Use the username and password you were given."
        user = (f'<label for="u">Username<input id="u" name="username" value="{e(username)}" autocomplete="username" '
                'autocapitalize="none" spellcheck="false" required autofocus></label>')
        reset = ("StartOS → TailWatcher → Actions → Reset Web UI Password makes a new password for the first admin"
                 if PLATFORM == "startos" else
                 "docker exec tailwatcher python /app/tailwatcher.py reset-password USERNAME gives that account a new password")
        help_ = ("<p class='small'>Forgot your password? Ask an admin to reset it on the People page. "
                 f"Locked-out admin: {e(reset)}.</p>")
    else:
        title, sub = "TailWatcher", "This dashboard is password protected."
        user = '<input type="hidden" name="username" value="">'
        where = ("StartOS → TailWatcher → Actions → Show Web UI Password" if PLATFORM == "startos" else
                 "TailWatcher's container log, or: docker exec tailwatcher python /app/tailwatcher.py password")
        help_ = f"<p class='small'>The password is in {e(where)}.</p>"
    body = f"""<h1>{e(title)}</h1><p class="sub">{e(sub)}</p>
<form method="post" action="login">
{f'<p class="error" role="alert">{e(error)}</p>' if error else ''}
{user}
<label for="p">Password<input id="p" type="password" name="password" autocomplete="current-password" required{'' if mode == 'accounts' else ' autofocus'}></label>
<button class="btn primary" type="submit">Sign in</button>
</form>
{help_}"""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="robots" content="noindex, nofollow"><meta name="referrer" content="no-referrer">
<meta name="color-scheme" content="light dark"><title>Sign in · TailWatcher</title>
<link rel="icon" href="icon.svg"><style>{LOGIN_STYLE}</style></head><body>
<header><img src="icon.svg" alt="">TailWatcher</header><main>{body}</main></body></html>"""


def make_handler(health, snapshot, password_path=PASSWORD_PATH, web_dir=WEB_DIR,
                 mode=lambda: "off", post=None, public=None, before_login=None,
                 accounts_path=None, sessions_path=None):
    """mode() gives the sign-in mode for each request: "off", "password" or
    "accounts". snapshot(viewer) and post(path, data, viewer) get the signed-in
    viewer: {"mode", "admin", "account" (None unless accounts), "token"}.
    post may return (code, body, {"login": {"account": id}}) to sign this
    browser in (after first setup or turning accounts on)."""
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

        def token(self):
            try:
                c = SimpleCookie(self.headers.get("Cookie") or "")
            except Exception:  # noqa: BLE001 - a malformed cookie header is just no cookie
                return None
            return c[COOKIE].value if COOKIE in c else None

        def cookie(self, token, max_age=accounts.SESSION_DAYS * 86400):
            # Lax, not Strict: tapping the dashboard link in an alert is a
            # cross-site navigation, and edits need the X-TailWatcher header anyway.
            secure = "; Secure" if (self.headers.get("X-Forwarded-Proto") or "").lower() == "https" else ""
            return {"Set-Cookie": f"{COOKIE}={token or ''}; Max-Age={max_age}; Path=/; HttpOnly; SameSite=Lax{secure}"}

        def viewer(self, m):
            """The signed-in viewer, None if signing in is needed, or "nopw" if
            password mode has no password to check against."""
            if m == "off":
                return {"mode": m, "admin": True, "account": None, "token": None}
            token = self.token()
            s = accounts.session(token, sessions_path) if token else None
            if m == "password":
                password = read_password(password_path)
                if not password:
                    return "nopw"
                if s and s.get("account") is None and s.get("mark") == accounts.mark(password):
                    return {"mode": m, "admin": True, "account": None, "token": token}
                if authorized(self.headers.get("Authorization"), password):
                    return {"mode": m, "admin": True, "account": None, "token": None}
                return None
            a = accounts.find(s["account"], accounts_path) if s and s.get("account") else None
            if a is None:
                return None
            return {"mode": m, "admin": a.get("role") == "admin", "account": accounts.public(a), "token": token}

        def gate(self, page=False):
            """The viewer, or None after sending the sign-in redirect / 401."""
            v = self.viewer(mode())
            if v == "nopw":
                self.reply(503, "The Web UI password hasn't been set up yet. Restart TailWatcher.",
                           "text/plain; charset=utf-8")
                return None
            if v is None:
                if page:
                    self.reply(303, "", "text/plain", {"Location": "login"})
                else:
                    self.reply(401, {"ok": False, "login": True, "message": "Sign in again."})
                return None
            return v

        def body(self, limit):
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            if not 0 < length <= limit:
                return None
            return self.rfile.read(length)

        def login(self):
            m = mode()
            if m == "off":
                return self.reply(303, "", "text/plain", {"Location": "./"})
            # The form page is sent with Referrer-Policy: no-referrer, so browsers post it with "Origin: null".
            origin = self.headers.get("Origin")
            if origin != "null" and not same_origin(origin, self.headers.get("Host")):
                return self.reply(403, "Sign in from the TailWatcher page.", "text/plain; charset=utf-8")
            raw = self.body(4096)
            form = urllib.parse.parse_qs((raw or b"").decode("utf-8", "replace"))
            username = (form.get("username") or [""])[0].strip().lower()[:64]
            password = (form.get("password") or [""])[0]
            keys = ["ip:" + self.client_address[0]] + (["user:" + username] if username else [])
            wait = THROTTLE.blocked(keys)
            if wait:
                return self.reply(429, login_page(m, f"Too many tries. Wait {wait} seconds and try again.", username),
                                  "text/html; charset=utf-8")
            if m == "password":
                stored = read_password(password_path)
                ok = bool(stored) and hmac.compare_digest(password.encode(), stored.encode())
                token = accounts.new_session(None, accounts.mark(stored), sessions_path) if ok else None
            else:
                if before_login:
                    before_login()
                a = accounts.authenticate(username, password, accounts_path)
                token = accounts.new_session(a["id"], None, sessions_path) if a else None
            if not token:
                THROTTLE.failed(keys)
                return self.reply(401, login_page(m, "That didn't match. Check the "
                                                  + ("username and password." if m == "accounts" else "password."),
                                                  username), "text/html; charset=utf-8")
            THROTTLE.passed(keys)
            return self.reply(303, "", "text/plain", {"Location": "./", **self.cookie(token)})

        def do_POST(self):
            path = urllib.parse.urlparse(self.path).path
            if path == "/login":
                return self.login()
            v = self.gate()
            if v is None:
                return
            if (self.headers.get("X-TailWatcher") != "1"
                    or not (self.headers.get("Content-Type") or "").startswith("application/json")
                    or not same_origin(self.headers.get("Origin"), self.headers.get("Host"))):
                return self.reply(403, {"ok": False, "message": "Edits must come from the TailWatcher page."})
            raw = self.body(MAX_IMPORT if path == "/api/import" else MAX_BODY)
            if raw is None:
                return self.reply(400, {"ok": False, "message": "Bad request."})
            try:
                data = json.loads(raw)
            except ValueError:
                return self.reply(400, {"ok": False, "message": "Bad request."})
            if not isinstance(data, dict):
                return self.reply(400, {"ok": False, "message": "Bad request."})
            if path == "/api/logout":
                if v["token"]:
                    if data.get("everywhere") and v["account"]:
                        accounts.end_for(v["account"]["id"], sessions_path)
                    accounts.end(v["token"], sessions_path)
                return self.reply(200, {"ok": True, "message": "Signed out."}, extra=self.cookie("", 0))
            if post is None:
                return self.reply(404, {"ok": False, "message": "Not found."})
            code, body, *more = post(path, data, v)
            extra = None
            login = (more[0] if more else {}).get("login")
            if login is not None:
                if login.get("account"):
                    token = accounts.new_session(login["account"], None, sessions_path)
                else:
                    token = accounts.new_session(None, accounts.mark(read_password(password_path)), sessions_path)
                extra = self.cookie(token)
            return self.reply(code, body, extra=extra)

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
            if path == "/icon.svg":
                return self.file(path)
            if path == "/login":
                m = mode()
                if m == "off" or self.viewer(m) not in (None, "nopw"):
                    return self.reply(303, "", "text/plain", {"Location": "./"})
                return self.reply(200, login_page(m), "text/html; charset=utf-8",
                                  {"X-Robots-Tag": "noindex, nofollow"})
            v = self.gate(page=path in ("/", "/index.html"))
            if v is None:
                return
            if path == "/api/state":
                return self.reply(200, snapshot(v))
            return self.file(path)

        def file(self, path):
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


def serve(port, health, snapshot, password_path=PASSWORD_PATH, web_dir=WEB_DIR, mode=lambda: "off",
          post=None, public=None, before_login=None, accounts_path=None, sessions_path=None):
    srv = ThreadingHTTPServer(("0.0.0.0", port),
                              make_handler(health, snapshot, password_path, web_dir, mode, post, public,
                                           before_login, accounts_path, sessions_path))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
