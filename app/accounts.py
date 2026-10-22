"""Family accounts: per-person logins for the Web UI (0.22.0).

Off unless the sign-in mode (config.json "webAuth") is "accounts". An account
owns some watchers (by topic) and its dashboard shows only those, their trips
and trips other people shared with them. Admins also get ⚙ Settings and the
People page, but never other people's trips.

/data/accounts.json  {"accounts": [{id, username, name, role, hash, watchers,
                       created, last_login}], "recovery": <mark>}
/data/sessions.json  {sha256(token): {account, expires, mark}}

Passwords are hashed with scrypt; only a hash of each session token is kept,
so a copy of /data can't be replayed as a login. The server owner can still
read every file in /data: accounts keep trips private from other household
members, not from whoever runs the server.

"recovery" is how a locked-out admin gets back in without email: StartOS's
"Reset Web UI Password" action (or `tailwatcher.py reset-password` on Docker)
writes a new password to webui.json, and sync_recovery() sees that it changed
and gives it to the first admin.
"""

import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time

ACCOUNTS_PATH = os.environ.get("TW_ACCOUNTS", "/data/accounts.json")
SESSIONS_PATH = os.environ.get("TW_SESSIONS", "/data/sessions.json")
LOCK = threading.RLock()

SESSION_DAYS = 30
MIN_PASSWORD = 8
MAX_ACCOUNTS = 20
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,31}$")
ROLES = ("admin", "member")
# scrypt cost: about 50 ms and 16 MB per check on a small server.
SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1}


class AccountError(Exception):
    """A problem to show the person, e.g. a username that's taken."""


# ------------------------------------------------------------- passwords


def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, dklen=32, **SCRYPT)
    return f"scrypt${SCRYPT['n']}${SCRYPT['r']}${SCRYPT['p']}${salt.hex()}${digest.hex()}"


def check_password(password, stored):
    try:
        kind, n, r, p, salt, digest = (stored or "").split("$")
        if kind != "scrypt":
            return False
        got = hashlib.scrypt((password or "").encode(), salt=bytes.fromhex(salt), dklen=32,
                             n=int(n), r=int(r), p=int(p))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got.hex(), digest)


DUMMY_HASH = hash_password(secrets.token_hex(8))  # so unknown usernames take as long as wrong passwords


def mark(password):
    """A short fingerprint of a password, to notice it changed (never the password)."""
    return hashlib.sha256(("tw-mark:" + (password or "")).encode()).hexdigest()[:16]


def check_new_password(password):
    if len(password or "") < MIN_PASSWORD:
        raise AccountError(f"Use at least {MIN_PASSWORD} characters for the password.")


# ----------------------------------------------------------------- store


def load(path=None):
    try:
        with open(path or ACCOUNTS_PATH) as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    data.setdefault("accounts", [])
    data.setdefault("recovery", "")
    return data


def save(data, path=None):
    path = path or ACCOUNTS_PATH
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, path)


def public(a):
    """An account without its password hash."""
    return {k: a.get(k) for k in ("id", "username", "name", "role", "watchers", "created", "last_login")}


def find(account_id, path=None):
    return next((a for a in load(path)["accounts"] if a["id"] == account_id), None)


def owner_of(topic, data):
    return next((a for a in data["accounts"] if topic in a.get("watchers") or []), None)


def admins(data):
    return [a for a in data["accounts"] if a.get("role") == "admin"]


def clean_username(username):
    u = (username or "").strip().lower()
    if not USERNAME_RE.match(u):
        raise AccountError("Usernames are 1–32 lowercase letters, numbers, dots, dashes or underscores.")
    return u


def create(username, name, password, role="member", watchers=(), path=None, now=None):
    username = clean_username(username)
    name = (name or "").strip()[:40] or username
    check_new_password(password)
    if role not in ROLES:
        raise AccountError("Pick a role: admin or member.")
    with LOCK:
        data = load(path)
        if any(a["username"] == username for a in data["accounts"]):
            raise AccountError(f"The username {username} is taken.")
        if len(data["accounts"]) >= MAX_ACCOUNTS:
            raise AccountError(f"TailWatcher supports up to {MAX_ACCOUNTS} accounts.")
        for a in data["accounts"]:  # a watcher belongs to one account
            a["watchers"] = [t for t in a.get("watchers") or [] if t not in watchers]
        account = {"id": "a_" + secrets.token_hex(6), "username": username, "name": name, "role": role,
                   "hash": hash_password(password), "watchers": list(dict.fromkeys(watchers)),
                   "created": round(now or time.time()), "last_login": None}
        data["accounts"].append(account)
        save(data, path)
    return public(account)


def update(account_id, name=None, role=None, password=None, path=None):
    """Change an account's name, role or password. The last admin stays an admin."""
    with LOCK:
        data = load(path)
        a = next((x for x in data["accounts"] if x["id"] == account_id), None)
        if a is None:
            raise AccountError("That account no longer exists.")
        if name is not None:
            a["name"] = name.strip()[:40] or a["username"]
        if role is not None:
            if role not in ROLES:
                raise AccountError("Pick a role: admin or member.")
            if role != "admin" and a["role"] == "admin" and len(admins(data)) == 1:
                raise AccountError("TailWatcher needs at least one admin. Make someone else an admin first.")
            a["role"] = role
        if password is not None:
            check_new_password(password)
            a["hash"] = hash_password(password)
        save(data, path)
    if password is not None:
        end_for(account_id)
    return public(a)


def delete(account_id, path=None):
    """Remove an account. Returns the watcher topics it owned (the caller moves or deletes them)."""
    with LOCK:
        data = load(path)
        a = next((x for x in data["accounts"] if x["id"] == account_id), None)
        if a is None:
            raise AccountError("That account no longer exists.")
        if a["role"] == "admin" and len(admins(data)) == 1:
            raise AccountError("TailWatcher needs at least one admin.")
        data["accounts"].remove(a)
        save(data, path)
    end_for(account_id)
    return list(a.get("watchers") or [])


def assign(topic, account_id, path=None):
    """Give a watcher to an account (None = nobody), taking it from whoever had it."""
    with LOCK:
        data = load(path)
        target = next((x for x in data["accounts"] if x["id"] == account_id), None)
        if account_id is not None and target is None:
            raise AccountError("That account no longer exists.")
        for a in data["accounts"]:
            a["watchers"] = [t for t in a.get("watchers") or [] if t != topic]
        if target is not None:
            target["watchers"].append(topic)
        save(data, path)


def rename_topic(old, new, path=None):
    with LOCK:
        data = load(path)
        changed = False
        for a in data["accounts"]:
            if old in (a.get("watchers") or []):
                a["watchers"] = [new if t == old else t for t in a["watchers"]]
                changed = True
        if changed:
            save(data, path)


def drop_topic(topic, path=None):
    assign(topic, None, path)


def authenticate(username, password, path=None, now=None):
    """The account for this username and password, or None."""
    u = (username or "").strip().lower()
    data = load(path)
    a = next((x for x in data["accounts"] if x["username"] == u), None)
    if not check_password(password, a["hash"] if a else DUMMY_HASH) or a is None:
        return None
    with LOCK:
        data = load(path)
        for x in data["accounts"]:
            if x["id"] == a["id"]:
                x["last_login"] = round(now or time.time())
        save(data, path)
    return public(a)


def ensure_admin(password, topics, path=None):
    """Accounts were turned on (e.g. in Configure) with nobody to sign in as:
    make "admin" with the Web UI password, owning every watcher. Returns the
    new account, or None if there was already an admin."""
    with LOCK:
        data = load(path)
        if admins(data) or not password:
            return None
        username = "admin"
        while any(a["username"] == username for a in data["accounts"]):
            username += "1"
        owned = {t for a in data["accounts"] for t in a.get("watchers") or []}
        account = create(username, "Admin", password, "admin", [t for t in topics if t not in owned], path)
        data = load(path)
        data["recovery"] = mark(password)
        save(data, path)
        return account


def sync_recovery(webui_password, path=None):
    """If the Web UI password (webui.json) changed since we last looked, it's a
    reset from StartOS Actions or the Docker CLI: it becomes the first admin's
    password. Returns that admin's username when it did."""
    if not webui_password:
        return None
    with LOCK:
        data = load(path)
        if not data["accounts"] or data["recovery"] == mark(webui_password):
            return None
        first = data["recovery"] == ""
        data["recovery"] = mark(webui_password)
        target = (admins(data) or [None])[0]
        if first or target is None:  # first time: just remember it, nothing was reset
            save(data, path)
            return None
        target["hash"] = hash_password(webui_password)
        save(data, path)
    end_for(target["id"])
    return target["username"]


# -------------------------------------------------------------- sessions


def _key(token):
    return hashlib.sha256(("tw-session:" + (token or "")).encode()).hexdigest()


def _load_sessions(path=None):
    try:
        with open(path or SESSIONS_PATH) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_sessions(sessions, path=None):
    path = path or SESSIONS_PATH
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(sessions, f)
    os.replace(tmp, path)


def new_session(account_id=None, pw_mark=None, path=None, now=None):
    """Start a session (account_id None = the shared-password mode). Returns the token."""
    now = now or time.time()
    token = secrets.token_urlsafe(32)
    with LOCK:
        sessions = {k: v for k, v in _load_sessions(path).items() if v.get("expires", 0) > now}
        sessions[_key(token)] = {"account": account_id, "mark": pw_mark,
                                 "expires": round(now + SESSION_DAYS * 86400)}
        _save_sessions(sessions, path)
    return token


def session(token, path=None, now=None):
    """The session for a cookie token, or None. Used sessions slide forward a day at a time."""
    if not token:
        return None
    now = now or time.time()
    with LOCK:
        sessions = _load_sessions(path)
        s = sessions.get(_key(token))
        if not s or s.get("expires", 0) <= now:
            return None
        if s["expires"] - now < (SESSION_DAYS - 1) * 86400:
            s["expires"] = round(now + SESSION_DAYS * 86400)
            _save_sessions(sessions, path)
        return dict(s)


def end(token, path=None):
    with LOCK:
        sessions = _load_sessions(path)
        if sessions.pop(_key(token), None) is not None:
            _save_sessions(sessions, path)


def end_for(account_id, path=None, keep=None):
    """Sign an account out everywhere (except the session `keep`, a token)."""
    with LOCK:
        sessions = _load_sessions(path)
        left = {k: v for k, v in sessions.items()
                if v.get("account") != account_id or (keep and k == _key(keep))}
        if len(left) != len(sessions):
            _save_sessions(left, path)


class Throttle:
    """Slows password guessing: after 5 failures for a username or an address
    within 15 minutes, each try waits 30 seconds after the last failure."""

    def __init__(self, limit=5, window=900, wait=30):
        self.limit, self.window, self.wait = limit, window, wait
        self.fails = {}
        self.lock = threading.Lock()

    def blocked(self, keys, now=None):
        now = now or time.time()
        with self.lock:
            for k in keys:
                recent = [t for t in self.fails.get(k, []) if now - t < self.window]
                self.fails[k] = recent
                if len(recent) >= self.limit and now - recent[-1] < self.wait:
                    return round(self.wait - (now - recent[-1])) or 1
        return 0

    def failed(self, keys, now=None):
        now = now or time.time()
        with self.lock:
            for k in keys:
                self.fails.setdefault(k, []).append(now)

    def passed(self, keys):
        with self.lock:
            for k in keys:
                self.fails.pop(k, None)
