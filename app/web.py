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
auth for scripts. /health (the StartOS ready check), /login, the "Forgot
password?" pages (/login?forgot, /forgot, /reset) and invite and sign-up
pages (/join/...) stay open.

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
main a { color:var(--brand); }
@media (prefers-color-scheme: dark) { .error { color:#ff6b63; } }
"""


def form_page(title, sub, form, action, error="", after="", base=""):
    """A small page with one form (plain HTML, works with JavaScript off).
    `base` leads back to the root for pages under /join/."""
    e = html.escape
    body = f"""<h1>{e(title)}</h1><p class="sub">{sub}</p>
<form method="post" action="{e(action)}">
{f'<p class="error" role="alert">{e(error)}</p>' if error else ''}
{form}
</form>
{after}"""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="robots" content="noindex, nofollow"><meta name="referrer" content="no-referrer">
<meta name="color-scheme" content="light dark"><title>{e(title)} · TailWatcher</title>
<link rel="icon" href="{base}icon.svg"><style>{LOGIN_STYLE}</style></head><body>
<header><img src="{base}icon.svg" alt="">TailWatcher</header><main>{body}</main></body></html>"""


def _field(label, name, value="", kind="text", auto="", extra=""):
    e = html.escape
    auto = f' autocomplete="{auto}"' if auto else ""
    return f'<label>{e(label)}<input type="{kind}" name="{name}" value="{e(value)}"{auto} {extra}></label>'


USERNAME_ATTRS = 'autocapitalize="none" spellcheck="false" required maxlength="32"'


def login_page(mode, error="", username=""):
    e = html.escape
    if mode == "accounts":
        title, sub = "Sign in to TailWatcher", "Use your username and password."
        user = _field("Username", "username", username, auto="username", extra=USERNAME_ATTRS + " autofocus")
        reset = ("StartOS → TailWatcher → Actions → Reset Web UI Password makes a new password for the first admin"
                 if PLATFORM == "startos" else
                 "docker exec tailwatcher python /app/tailwatcher.py reset-password USERNAME gives that account a new password")
        help_ = ("<p class='small'><a href='login?forgot=1'>Forgot your password?</a> TailWatcher sends a code "
                 "to your alerts in the ntfy app. No alerts set up yet? Ask an admin to reset it on the People page. "
                 f"Locked-out admin: {e(reset)}.</p>")
    else:
        title, sub = "TailWatcher", "This dashboard is password protected."
        user = '<input type="hidden" name="username" value="">'
        where = ("StartOS → TailWatcher → Actions → Show Web UI Password" if PLATFORM == "startos" else
                 "TailWatcher's container log, or: docker exec tailwatcher python /app/tailwatcher.py password")
        help_ = f"<p class='small'>The password is in {e(where)}.</p>"
    form = (user + _field("Password", "password", kind="password", auto="current-password",
                          extra="required" + ("" if mode == "accounts" else " autofocus"))
            + '<button class="btn primary" type="submit">Sign in</button>')
    return form_page(title, e(sub), form, "login", error, help_)


def forgot_page(error="", username=""):
    form = (_field("Username", "username", username, auto="username", extra=USERNAME_ATTRS + " autofocus")
            + '<button class="btn primary" type="submit">Send me a code</button>')
    return form_page("Forgot your password?", "TailWatcher sends a 6-digit code to your alerts in the ntfy app. "
                     "Type it on the next page to pick a new password.", form, "forgot", error,
                     "<p class='small'><a href='login'>Back to sign in</a></p>")


def reset_page(username, error=""):
    e = html.escape
    form = (f'<input type="hidden" name="username" value="{e(username)}">'
            + _field("Code", "code", auto="one-time-code",
                     extra='inputmode="numeric" pattern="[0-9 ]*" maxlength="7" required autofocus')
            + _field("New password", "password", kind="password", auto="new-password", extra='required minlength="8"')
            + _field("New password again", "confirm", kind="password", auto="new-password", extra='required minlength="8"')
            + '<button class="btn primary" type="submit">Set new password</button>')
    return form_page("Check your phone", f"If <b>{e(username)}</b> has alerts set up, a code is on its way in the "
                     f"ntfy app. It works for {accounts.RESET_MINUTES} minutes.", form, "reset", error,
                     "<p class='small'>Nothing came? <a href='login?forgot=1'>Send a new code</a> (one a minute), "
                     "or ask an admin to reset your password on the People page.</p>")


def signup_page(invite, error="", name="", username=""):
    """The sign-up link page at /join/<token> (family accounts)."""
    e = html.escape
    sender = invite.get("from") or ""
    title = f"{sender} invited you to TailWatcher" if sender else "Make your TailWatcher account"
    sub = ("Pick a name, username and password. You'll see your own trips and flight alerts"
           + (", with alerts sent to your phone" if invite.get("watcher") else "")
           + ", and trips people share with you.")
    form = (_field("Your name", "name", name, auto="name", extra='required maxlength="40" autofocus')
            + _field("Username", "username", username, auto="username", extra=USERNAME_ATTRS)
            + "<p class='small' style='margin:-8px 0 0'>Lowercase letters, numbers, dots or dashes. You type it to sign in.</p>"
            + _field("Password", "password", kind="password", auto="new-password", extra='required minlength="8"')
            + _field("Password again", "confirm", kind="password", auto="new-password", extra='required minlength="8"')
            + '<button class="btn primary" type="submit">Make my account</button>')
    return form_page(title, e(sub), form, invite["token"], error,
                     "<p class='small'>This link works once. Keep it to yourself.</p>", base="../")


def make_handler(health, snapshot, password_path=PASSWORD_PATH, web_dir=WEB_DIR,
                 mode=lambda: "off", post=None, public=None, before_login=None,
                 accounts_path=None, sessions_path=None, signup=None, forgot=None):
    """mode() gives the sign-in mode for each request: "off", "password" or
    "accounts". snapshot(viewer) and post(path, data, viewer) get the signed-in
    viewer: {"mode", "admin", "account" (None unless accounts), "token"}.
    post may return (code, body, {"login": {"account": id}}) to sign this
    browser in (after first setup or turning accounts on).
    signup(token, form) handles a sign-up link's form: (code, page, account_id
    or None). forgot(username) sends a reset code to that person's topics."""
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

        def form(self):
            """A posted form, or None (after a 403) if it came from another site.
            Our pages are sent with Referrer-Policy: no-referrer, so browsers
            post them with "Origin: null"."""
            origin = self.headers.get("Origin")
            if origin != "null" and not same_origin(origin, self.headers.get("Host")):
                self.reply(403, "Sign in from the TailWatcher page.", "text/plain; charset=utf-8")
                return None
            raw = self.body(4096)
            form = urllib.parse.parse_qs((raw or b"").decode("utf-8", "replace"))
            return {k: v[0] for k, v in form.items()}

        def page(self, code, page, extra=None):
            return self.reply(code, page, "text/html; charset=utf-8",
                              {"X-Robots-Tag": "noindex, nofollow", **(extra or {})})

        def login(self):
            m = mode()
            if m == "off":
                return self.reply(303, "", "text/plain", {"Location": "./"})
            form = self.form()
            if form is None:
                return
            username = form.get("username", "").strip().lower()[:64]
            password = form.get("password", "")
            keys = ["ip:" + self.client_address[0]] + (["user:" + username] if username else [])
            wait = THROTTLE.blocked(keys)
            if wait:
                return self.page(429, login_page(m, f"Too many tries. Wait {wait} seconds and try again.", username))
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
                return self.page(401, login_page(m, "That didn't match. Check the "
                                                 + ("username and password." if m == "accounts" else "password."),
                                                 username))
            THROTTLE.passed(keys)
            return self.reply(303, "", "text/plain", {"Location": "./", **self.cookie(token)})

        def forgot(self):
            """Forgot password, step 1: send a code. The reply never says
            whether the username exists."""
            if mode() != "accounts":
                return self.reply(303, "", "text/plain", {"Location": "login"})
            form = self.form()
            if form is None:
                return
            username = form.get("username", "").strip().lower()[:64]
            wait = THROTTLE.blocked(["ip:" + self.client_address[0]])
            if wait:
                return self.page(429, forgot_page(f"Too many tries. Wait {wait} seconds and try again.", username))
            if not username:
                return self.page(400, forgot_page("Type your username."))
            if forgot:
                forgot(username)
            return self.page(200, reset_page(username))

        def reset(self):
            """Forgot password, step 2: the code and a new password."""
            if mode() != "accounts":
                return self.reply(303, "", "text/plain", {"Location": "login"})
            form = self.form()
            if form is None:
                return
            username = form.get("username", "").strip().lower()[:64]
            keys = ["ip:" + self.client_address[0], "user:" + username]
            wait = THROTTLE.blocked(keys)
            if wait:
                return self.page(429, reset_page(username, f"Too many tries. Wait {wait} seconds and try again."))
            if form.get("password", "") != form.get("confirm", ""):
                return self.page(400, reset_page(username, "The two passwords don't match."))
            try:
                a = accounts.finish_reset(username, form.get("code", ""), form.get("password", ""), accounts_path)
            except accounts.AccountError as e:
                THROTTLE.failed(keys)
                return self.page(400, reset_page(username, str(e)))
            THROTTLE.passed(keys)
            token = accounts.new_session(a["id"], None, sessions_path)
            return self.reply(303, "", "text/plain", {"Location": "./", **self.cookie(token)})

        def join(self, token):
            """A sign-up link's form."""
            form = self.form()
            if form is None:
                return
            keys = ["ip:" + self.client_address[0]]
            wait = THROTTLE.blocked(keys)
            if wait:
                return self.page(429, f"Too many tries. Wait {wait} seconds, then go back and try again.")
            code, page, account_id = signup(token, form)
            if not account_id:
                if code == 404:
                    THROTTLE.failed(keys)  # someone guessing links
                return self.page(code, page)
            token = accounts.new_session(account_id, None, sessions_path)
            return self.reply(303, "", "text/plain", {"Location": "../#welcome", **self.cookie(token)})

        def do_POST(self):
            path = urllib.parse.urlparse(self.path).path
            if path == "/login":
                return self.login()
            if path == "/forgot":
                return self.forgot()
            if path == "/reset":
                return self.reset()
            if path.startswith("/join/") and signup is not None:
                return self.join(path[len("/join/"):])
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
                if m == "accounts" and "forgot" in urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query):
                    return self.page(200, forgot_page())
                return self.page(200, login_page(m))
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
          post=None, public=None, before_login=None, accounts_path=None, sessions_path=None,
          signup=None, forgot=None):
    srv = ThreadingHTTPServer(("0.0.0.0", port),
                              make_handler(health, snapshot, password_path, web_dir, mode, post, public,
                                           before_login, accounts_path, sessions_path, signup, forgot))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
