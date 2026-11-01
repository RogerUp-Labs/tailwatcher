"""One-click setup of this Start9's NTFY, driven from the Web UI's Settings.

Uses NTFY's admin API with the admin password the person types in. The
password is used for these requests only and never stored; what TailWatcher
keeps is a token for its own NTFY user.

Setup: (1) check the admin login, (2) create (or reset) the "tailwatcher"
user, (3) give it Read-Write on tw-* (and tailwatcher* for pre-0.12 topics), (4) phones: "open" grants anonymous
Read-Write on tw-* (subscribe with just the link; the topics are unguessable)
or "login" removes that grant and gives each person their own account,
(5) mint a token for the tailwatcher user that never expires.

NTFY's POST /v1/account/token gives a token that expires after 72 hours
unless the request says otherwise ("expires": 0 = never). Before 0.24.1
setup didn't, so its token stopped working 3 days later (HTTP 401);
keep_token() makes such a token permanent while it still works.
"""

import base64
import json
import re
import secrets
import urllib.error
import urllib.request

USER = "tailwatcher"
LABEL = "TailWatcher"  # the label setup() gives its token
TOPICS = "tw-*"
OLD_TOPICS = "tailwatcher*"  # watchers made before 0.12 (TailWatcher's user only, never anonymous)
ALPHABET = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"


class SetupError(Exception):
    """A problem to show in the Settings panel."""


def _password(n=24):
    return "".join(secrets.choice(ALPHABET) for _ in range(n))


def _call(base, method, path, auth=None, body=None, timeout=15):
    """One NTFY API request. auth: (user, password) or a token string."""
    req = urllib.request.Request(base.rstrip("/") + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None)
    if isinstance(auth, tuple):
        req.add_header("Authorization", "Basic " + base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode())
    elif auth:
        req.add_header("Authorization", f"Bearer {auth}")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {}
    except (urllib.error.URLError, OSError) as e:
        raise SetupError(f"Couldn't reach NTFY ({e}). Is it installed and running?") from e


def _check(status, what):
    if status != 200:
        raise SetupError(f"NTFY refused to {what} (HTTP {status}).")


def setup(base, admin_password, phones="open", admin_user="admin", call=_call):
    """Run the setup. Returns (token, steps) where steps is a list of done texts."""
    if not base:
        raise SetupError("NTFY isn't installed on this server (or isn't running). Install it from the "
                         "Marketplace first, or use ntfy.sh.")
    if not admin_password:
        raise SetupError("Enter NTFY's admin password.")
    admin = (admin_user or "admin", admin_password)
    status, _ = call(base, "GET", "/v1/users", admin)
    if status in (401, 403):
        raise SetupError("That isn't NTFY's admin password. It was shown by NTFY's \"Set Admin Password\" "
                         "step; NTFY → Actions → Reset User Password (admin) makes a new one.")
    _check(status, "list users")
    steps = ["Signed in to NTFY as admin"]

    password = _password()
    status, _ = call(base, "POST", "/v1/users", admin, {"username": USER, "password": password})
    if status == 409:
        status, _ = call(base, "PUT", "/v1/users", admin, {"username": USER, "password": password})
        _check(status, "update TailWatcher's user")
        steps.append("Reset TailWatcher's NTFY user")
    else:
        _check(status, "create TailWatcher's user")
        steps.append("Created an NTFY user for TailWatcher")

    status, _ = call(base, "PUT", "/v1/users/access", admin,
                     {"username": USER, "topic": TOPICS, "permission": "read-write"})
    _check(status, "grant TailWatcher access")
    status, _ = call(base, "PUT", "/v1/users/access", admin,
                     {"username": USER, "topic": OLD_TOPICS, "permission": "read-write"})
    _check(status, "grant TailWatcher access to older topics")
    steps.append(f"Gave it access to {TOPICS} topics (and {OLD_TOPICS} from older versions)")

    if phones == "open":
        status, _ = call(base, "PUT", "/v1/users/access", admin,
                         {"username": "*", "topic": TOPICS, "permission": "read-write"})
        _check(status, "allow phones without a login")
        steps.append(f"Let phones subscribe to {TOPICS} without a login (other topics stay locked)")
    else:
        call(base, "DELETE", "/v1/users/access", admin, {"username": "*", "topic": TOPICS})
        steps.append(f"Phones need a login for {TOPICS} (each person gets one)")

    status, data = call(base, "POST", "/v1/account/token", (USER, password),
                        {"label": LABEL, "expires": 0})  # 0 = never; NTFY's default is 72 hours
    _check(status, "make a token")
    token = data.get("token")
    if not token:
        raise SetupError("NTFY didn't return a token.")
    steps.append("Saved a token for TailWatcher (your admin password was not stored)")
    return token, steps


def keep_token(base, token, call=_call):
    """Make the token "Set up NTFY for me" made never expire, if it still
    works. Only touches a token labelled TailWatcher that has an expiry, so a
    token someone made by hand keeps the expiry they chose. Returns True if it
    changed the token, False if nothing needed doing, None if NTFY couldn't
    say (unreachable, or the token is already refused)."""
    if not base or not token:
        return False
    try:
        status, account = call(base, "GET", "/v1/account", token)
    except SetupError:
        return None
    if status != 200 or not isinstance(account, dict):
        return None
    mine = next((t for t in account.get("tokens") or [] if t.get("token") == token), None)
    if not mine or mine.get("label") != LABEL or not mine.get("expires") or mine.get("provisioned"):
        return False
    try:
        status, _ = call(base, "PATCH", "/v1/account/token", token, {"token": token, "expires": 0})
    except SetupError:
        return None
    return status == 200 or None


def username_for(name, taken):
    """A readable NTFY username for a watcher: "dad", "dad2", …"""
    base = re.sub(r"[^a-z0-9]+", "", (name or "").lower())[:20] or "person"
    if base in ("admin", USER, "everyone"):
        base = "tw" + base
    user, n = base, 2
    while user in taken:
        user, n = f"{base}{n}", n + 1
    return user


def create_login(base, admin_password, name, topic, admin_user="admin", call=_call):
    """Make an NTFY account for one person with Read-Write on their topic (or
    topics: a list also covers their Planes topic; blanks are skipped).
    Returns (username, password). The password is shown once and not stored."""
    if not admin_password:
        raise SetupError("Enter NTFY's admin password.")
    admin = (admin_user or "admin", admin_password)
    status, users = call(base, "GET", "/v1/users", admin)
    if status in (401, 403):
        raise SetupError("That isn't NTFY's admin password.")
    _check(status, "list users")
    taken = {u.get("username") for u in users} if isinstance(users, list) else set()
    user, password = username_for(name, taken), _password(16)
    status, _ = call(base, "POST", "/v1/users", admin, {"username": user, "password": password})
    _check(status, f"create a login for {name}")
    for t in [x for x in ([topic] if isinstance(topic, str) else topic) if x]:
        status, _ = call(base, "PUT", "/v1/users/access", admin,
                         {"username": user, "topic": t, "permission": "read-write"})
        _check(status, f"give {name} access to their topic")
    return user, password
