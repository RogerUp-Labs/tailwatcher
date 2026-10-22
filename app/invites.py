"""Invite links: a normal https link you can text to someone, opening a small
page that walks them through subscribing to their alerts in the ntfy app.

Messaging apps (SMS, iMessage, Signal) only make https:// links tappable, not
ntfy://, so the invite page is what carries the ntfy:// button. Each invite
is a random token for one watcher, expires (7 days by default) and can be
cancelled. The page is public on purpose (no dashboard password) and shows
only that one person's subscribe details. Invites carry a "kind": "watcher"
(subscribe to one watcher's alerts) or "account" (0.23.0: a sign-up link for
family accounts, used once, where the person picks their own username and
password and can get a watcher of their own).
"""

import datetime
import html
import json
import os
import re
import secrets
import threading
import time
import urllib.parse

INVITES_PATH = os.environ.get("TW_INVITES", "/data/invites.json")
INVITES_LOCK = threading.Lock()
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{20,64}$")
DEFAULT_DAYS = 7


def load(path=None):
    try:
        with open(path or INVITES_PATH) as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def save(invites, path=None):
    path = path or INVITES_PATH
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(invites, f, indent=1)
    os.replace(tmp, path)


def create(topic, sender="", days=DEFAULT_DAYS, now=None, path=None):
    """A new invite for the watcher on `topic`. Returns the invite dict."""
    now = time.time() if now is None else now
    days = max(1, min(30, int(days or DEFAULT_DAYS)))
    invite = {"token": secrets.token_urlsafe(18), "kind": "watcher", "topic": topic,
              "from": (sender or "").strip()[:40], "created": round(now), "expires": round(now + days * 86400)}
    with INVITES_LOCK:
        invites = [i for i in load(path) if i.get("expires", 0) > now]  # tidy expired ones
        invites.append(invite)
        save(invites, path)
    return invite


def create_signup(sender="", days=DEFAULT_DAYS, role="member", watcher=True, now=None, path=None):
    """A one-time sign-up link for a new family account."""
    now = time.time() if now is None else now
    days = max(1, min(30, int(days or DEFAULT_DAYS)))
    invite = {"token": secrets.token_urlsafe(18), "kind": "account", "topic": None,
              "role": "admin" if role == "admin" else "member", "watcher": bool(watcher),
              "from": (sender or "").strip()[:40], "created": round(now), "expires": round(now + days * 86400)}
    with INVITES_LOCK:
        invites = [i for i in load(path) if i.get("expires", 0) > now]
        invites.append(invite)
        save(invites, path)
    return invite


def claim(token, kind, now=None, path=None):
    """Take a live invite of this kind out of the list (sign-up links work
    once). Returns it, or None if someone else got there first."""
    now = time.time() if now is None else now
    with INVITES_LOCK:
        invites = load(path)
        hit = next((i for i in invites if i.get("token") == token and i.get("kind", "watcher") == kind
                    and i.get("expires", 0) > now), None)
        if hit is not None:
            save([i for i in invites if i is not hit], path)
        return hit


def restore(invite, path=None):
    """Put back an invite claim() took, when signing up failed (a taken username)."""
    with INVITES_LOCK:
        invites = load(path)
        if not any(i.get("token") == invite["token"] for i in invites):
            invites.append(invite)
            save(invites, path)


def revoke(token, path=None):
    with INVITES_LOCK:
        invites = load(path)
        keep = [i for i in invites if i.get("token") != token]
        if len(keep) != len(invites):
            save(keep, path)
        return len(invites) - len(keep)


def find(token, now=None, path=None):
    """The live invite for a token, or None (unknown, malformed or expired)."""
    now = time.time() if now is None else now
    if not TOKEN_RE.match(token or ""):
        return None
    return next((i for i in load(path) if i.get("token") == token and i.get("expires", 0) > now), None)


def active(now=None, path=None):
    now = time.time() if now is None else now
    return [i for i in load(path) if i.get("expires", 0) > now]


def display_name(watcher_name):
    """The subscription name the ntfy Android app shows instead of the tw-… topic."""
    return f"TailWatcher · {watcher_name}" if watcher_name else "TailWatcher"


def links(topic, phone_url, name=None):
    """(ntfy:// app link, https web link, host) for a topic, or (None, None, None).

    The app link carries ?display= so the ntfy Android app names the new
    subscription after the watcher. Only Android reads it, and only when it
    subscribes; the iPhone app has no display names."""
    base = (phone_url or "").rstrip("/")
    if not base:
        return None, None, None
    u = urllib.parse.urlparse(base)
    path = u.path.rstrip("/")
    query = {"display": display_name(name)}
    if u.scheme != "https":
        query["secure"] = "false"
    app = f"ntfy://{u.netloc}{path}/{urllib.parse.quote(topic)}?" + urllib.parse.urlencode(query, quote_via=urllib.parse.quote)
    return app, f"{base}/{urllib.parse.quote(topic)}", u.netloc


# ------------------------------------------------------------------ pages

STYLE = """
:root { --bg:#f3f5f9; --card:#fff; --text:#0f1b2d; --muted:#5a6a80; --line:#e3e8f0; --brand:#1f5fa8; --on-brand:#fff; --soft:#e6eefa; --warn:#9a5200; }
@media (prefers-color-scheme: dark) { :root { --bg:#0a111e; --card:#111b2c; --text:#e6edf7; --muted:#a9b6c9; --line:#1f2c42; --brand:#6aa6ff; --on-brand:#06101f; --soft:#16284a; --warn:#ffb547; } }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--text); font:16px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }
header { background:linear-gradient(135deg,#0a1a33,#1f5fa8); color:#fff; padding:calc(env(safe-area-inset-top) + 14px) 18px 14px; display:flex; gap:10px; align-items:center; font-weight:700; font-size:18px; }
header img { width:30px; height:30px; border-radius:8px; }
main { max-width:520px; margin:0 auto; padding:18px 16px 40px; }
h1 { font-size:23px; line-height:1.25; margin:6px 0 4px; }
.sub { color:var(--muted); margin:0 0 18px; }
.step { background:var(--card); border:1px solid var(--line); border-radius:14px; padding:16px; margin:12px 0; }
.step h2 { font-size:16px; margin:0 0 10px; display:flex; gap:10px; align-items:center; }
.n { width:26px; height:26px; border-radius:50%; background:var(--brand); color:var(--on-brand); display:grid; place-items:center; font-size:14px; flex:none; }
.stores { display:flex; flex-wrap:wrap; gap:8px; }
a.btn, button.btn { display:inline-block; text-decoration:none; padding:11px 16px; border-radius:10px; border:1px solid var(--line); color:var(--text); background:var(--card); font:inherit; font-size:15px; cursor:pointer; }
a.btn.primary { background:var(--brand); border-color:var(--brand); color:var(--on-brand); font-weight:600; display:block; text-align:center; font-size:17px; padding:14px; }
.small { font-size:14px; color:var(--muted); }
code { font-family:ui-monospace,Menlo,Consolas,monospace; font-size:14px; background:var(--soft); padding:1px 6px; border-radius:6px; overflow-wrap:anywhere; }
details { margin-top:10px; } summary { cursor:pointer; color:var(--brand); font-size:14px; }
ul { padding-left:20px; margin:6px 0; } li { margin:4px 0; }
.note { color:var(--warn); font-size:14px; }
footer { color:var(--muted); font-size:13px; text-align:center; margin-top:18px; }
"""


def _page(title, body):
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="robots" content="noindex, nofollow"><meta name="referrer" content="no-referrer">
<meta name="color-scheme" content="light dark"><title>{html.escape(title)}</title>
<link rel="icon" href="../icon.svg"><style>{STYLE}</style></head><body>
<header><img src="../icon.svg" alt="">TailWatcher</header><main>{body}</main></body></html>"""


def expired_page():
    return _page("Link expired", """<h1>This link has expired</h1>
<p class="sub">Invite and sign-up links only work for a few days, sign-up links only once,
or this one was cancelled. Ask the person who sent it for a new one.</p>""")


def join_page(invite, watcher_name, phone_url, server_mode="public", phone_mode="open", tz=None):
    e = html.escape
    app, web, host = links(invite["topic"], phone_url, watcher_name)
    sender = invite.get("from") or ""
    title = f"{sender} invited you to flight alerts" if sender else "You're invited to flight alerts"
    dt = datetime.datetime.fromtimestamp(invite["expires"], tz)
    when = f"{dt:%a %b} {dt.day}"  # no %-d: Alpine's C library doesn't support it
    login_note = ""
    if server_mode == "local" and phone_mode == "login":
        login_note = (f"<p class='note'>This server asks for a login. {e(sender or 'Whoever invited you')} "
                      "will send you a username and password to add in the ntfy app (Settings → Manage users).</p>")
    cert_note = ""
    if server_mode != "public":
        cert_note = ("<p class='small'>Does the ntfy app say <b>Trust anchor for certification path not found</b> "
                     "or show another certificate error? Your phone doesn't trust this server's certificate yet. "
                     f"Let {e(sender or 'whoever invited you')} know; it's a setting on their server.</p>")
    if app:
        subscribe = f"""<a class="btn primary" href="{e(app)}">Subscribe in ntfy</a>
<p class="small">Opens the ntfy app with your alerts ready. Tap <b>Subscribe</b> there.
On Android it's listed as <b>{e(display_name(watcher_name))}</b>.</p>
<details><summary>It didn't open?</summary>
<p class="small">Open <a href="{e(web)}" rel="noreferrer">{e(web)}</a>, or in the ntfy app tap <b>+</b>,
turn on <b>Use another server</b>, and enter server <code>{e(host)}</code> and topic <code>{e(invite['topic'])}</code>.</p>{cert_note}</details>"""
    else:
        subscribe = f"""<p class="small">In the ntfy app tap <b>+</b>, turn on <b>Use another server</b>, and enter the
server address you were given and topic <code>{e(invite['topic'])}</code>.</p>"""
    body = f"""<h1>{e(title)}</h1>
<p class="sub">Get a notification when the planes and flights on <b>{e(watcher_name)}</b>'s list take off and land.
Two quick steps on your phone.</p>
<section class="step"><h2><span class="n">1</span>Install the free ntfy app</h2>
<div class="stores" id="stores">
<a class="btn" data-os="ios" href="https://apps.apple.com/us/app/ntfy/id1625396347">App Store</a>
<a class="btn" data-os="android" href="https://play.google.com/store/apps/details?id=io.heckel.ntfy">Google Play</a>
<a class="btn" data-os="android" href="https://f-droid.org/packages/io.heckel.ntfy/">F-Droid</a>
</div></section>
<section class="step"><h2><span class="n">2</span>Subscribe to your alerts</h2>{subscribe}{login_note}</section>
<section class="step"><h2><span class="n">✓</span>What you'll get</h2><ul>
<li><b>Departed / is airborne:</b> a plane just took off. Tap the alert to see it on a live map.</li>
<li><b>Landed:</b> it's on the ground.</li>
<li><b>📣 Shared a flight with you:</b> someone added you to their trip; you'll get its departure and landing.</li>
<li>You can type in the app to manage your list: a tail or flight number (<code>N12345</code>, <code>UA1234 for 2 days</code>) to follow it, <code>list</code> to see it, <code>help</code> for more.</li>
<li>On iPhone the app lists it by its server and topic, a long random name; the iPhone app can't rename it,
but every alert says what it's about. On Android, rename it any time: open it, then ⋮ → <b>Subscription settings</b> → <b>Display name</b>.</li>
<li>On Android, set the ntfy app's battery use to <b>Unrestricted</b> so alerts arrive on time.</li>
</ul></section>
<footer>This invite works until {e(when)}. Keep it to yourself: anyone with it can read these alerts.</footer>
<script>
if (/iPhone|iPad|iPod/.test(navigator.userAgent)) document.querySelectorAll('[data-os="android"]').forEach(a => a.remove());
else if (/Android/.test(navigator.userAgent)) document.querySelectorAll('[data-os="ios"]').forEach(a => a.remove());
</script>"""
    return _page(title, body)
