"""Text commands: change a watcher's aircraft list by posting to their ntfy topic.

Each watcher's topic doubles as a chat with TailWatcher. In the ntfy app,
type "N12345" (or "add N12345 Vegas trip") to add an aircraft, "remove
N12345" to drop it, and "list" to see what's watched. TailWatcher edits the
same config.json the StartOS Configure form uses and replies on the topic.
"""

import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.request
from collections import deque

log = logging.getLogger("tailwatcher")

# Tags on everything TailWatcher publishes (alerts, replies, test alerts).
# Messages carrying one are ignored, so it never answers itself.
OWN_TAGS = {"airplane", "airplane_arriving", "robot", "test_tube"}
MAX_AIRCRAFT = 50

HELP = (
    "Send a tail number to watch it:\n"
    "• N12345 — add\n"
    "• add N12345 Vegas trip — add with a nickname\n"
    "• remove N12345 — stop watching\n"
    "• list — what you're watching"
)

CONFIG_LOCK = threading.Lock()


def normalize_tail(tail):
    return re.sub(r"[^A-Z0-9]", "", tail.upper())


def valid_tail(tail):
    return 2 <= len(tail) <= 10 and tail.isalnum()


def looks_like_tail(token):
    """A bare word counts as a tail if it has a digit (N12345) or a dash (G-ABCD)."""
    return valid_tail(normalize_tail(token)) and (
        any(c.isdigit() for c in token) or "-" in token.strip("-"))


def parse(text):
    """Parse a message into (verb, tail, label); verb is add/remove/list/help/unknown."""
    words = (text or "").split()
    if not words:
        return "unknown", None, ""
    first = words[0].lower()
    rest = " ".join(words[2:])
    if first in ("list", "ls", "show", "?"):
        return "list", None, ""
    if first in ("help", "commands"):
        return "help", None, ""
    if first in ("add", "watch", "+") and len(words) >= 2:
        return "add", words[1], rest
    if first in ("remove", "rm", "delete", "del", "unwatch", "-") and len(words) >= 2:
        return "remove", words[1], ""
    if first.startswith("+") and len(first) > 1:
        return "add", words[0][1:], " ".join(words[1:])
    if first.startswith("-") and len(first) > 1:
        return "remove", words[0][1:], ""
    if looks_like_tail(words[0]):
        return "add", words[0], " ".join(words[1:])
    return "unknown", None, ""


# --------------------------------------------------------- config edits


def read_raw(path):
    """Read config.json as written by StartOS, upgrading the 0.1.x layout."""
    try:
        with open(path) as f:
            raw = json.load(f)
    except FileNotFoundError:
        raw = {}
    if "watchers" not in raw and isinstance(raw.get("aircraft"), list):
        raw = {
            "watchers": [{
                "name": "Me",
                "topic": raw.get("ntfyTopic") or "tailwatcher",
                "aircraft": raw["aircraft"],
                "notifyLanding": bool(raw.get("notifyLanding", False)),
                "priority": raw.get("priority", "default"),
            }],
            **{k: v for k, v in raw.items()
               if k not in ("aircraft", "ntfyTopic", "notifyLanding", "priority")},
        }
    return raw


def write_raw(path, raw):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(raw, f, indent=2)
    os.replace(tmp, path)


def format_list(watcher, status):
    aircraft = watcher.get("aircraft") or []
    if not aircraft:
        return "Your list is empty. Send a tail number, e.g. N12345, to add one."
    lines = [f"{watcher.get('name') or 'Your'}'s aircraft ({len(aircraft)}):"]
    for a in aircraft:
        tail = a["tail"]
        name = f"{tail} ({a['label']})" if a.get("label") else tail
        st = (status or {}).get(tail) or {}
        flag = {"airborne": " — ✈️ airborne", "ground": " — on the ground"}.get(st.get("status"), "")
        lines.append(f"• {name}{flag}")
    return "\n".join(lines)


def apply_command(path, topic, text, status=None):
    """Run one text command for the watcher on `topic`.

    Returns (reply, changed): the reply to post (None if the topic is no
    longer configured) and whether config.json was rewritten.
    """
    verb, tail_in, label = parse(text)
    with CONFIG_LOCK:
        raw = read_raw(path)
        watcher = next((w for w in raw.get("watchers") or [] if w.get("topic") == topic), None)
        if watcher is None:
            return None, False
        if verb == "list":
            return format_list(watcher, status), False
        if verb == "help":
            return HELP, False
        if verb == "unknown":
            return "🤔 I didn't understand that. Send \"help\" for commands.", False

        tail = normalize_tail(tail_in)
        if not valid_tail(tail):
            return f"❌ \"{tail_in}\" doesn't look like a tail number.", False
        aircraft = watcher.setdefault("aircraft", [])
        existing = next((a for a in aircraft if a.get("tail") == tail), None)
        label = label.strip()[:40]

        if verb == "add":
            if existing:
                if label and label != existing.get("label"):
                    existing["label"] = label
                    write_raw(path, raw)
                    return f"✏️ Renamed {tail} to \"{label}\".", True
                return f"👍 Already watching {tail}.", False
            if len(aircraft) >= MAX_AIRCRAFT:
                return f"❌ Your list is full ({MAX_AIRCRAFT}). Remove one first.", False
            aircraft.append({"tail": tail, "label": label})
            write_raw(path, raw)
            name = f"{tail} ({label})" if label else tail
            return f"✅ Added {name}. Watching {len(aircraft)} aircraft.", True

        # remove
        if not existing:
            return f"🤷 {tail} isn't on your list.", False
        aircraft.remove(existing)
        write_raw(path, raw)
        return f"🗑 Removed {tail}. Watching {len(aircraft)} aircraft.", True


# ------------------------------------------------------------ listening


class TopicListener(threading.Thread):
    """Streams one ntfy topic and hands each human-written message to a callback."""

    def __init__(self, ntfy_url, token, topic, on_message, on_status):
        super().__init__(daemon=True, name=f"listen-{topic}")
        self.url = f"{ntfy_url.rstrip('/')}/{topic}/json"
        self.token, self.topic = token, topic
        self.on_message, self.on_status = on_message, on_status
        self.stopped = threading.Event()
        self.since = str(int(time.time()))  # skip the backlog on first connect
        self.seen = deque(maxlen=200)

    def stop(self):
        self.stopped.set()

    def run(self):
        delay = 5
        while not self.stopped.is_set():
            req = urllib.request.Request(f"{self.url}?since={self.since}")
            if self.token:
                req.add_header("Authorization", f"Bearer {self.token}")
            try:
                # ntfy sends a keepalive every 45s, so a 90s read timeout only
                # fires if the connection has really died.
                with urllib.request.urlopen(req, timeout=90) as r:
                    self.on_status(self.topic, None)
                    delay = 5
                    for line in r:
                        if self.stopped.is_set():
                            return
                        self.handle(line)
            except urllib.error.HTTPError as e:
                if e.code in (401, 403):
                    self.on_status(self.topic, (
                        f"text commands can't read topic {self.topic} (HTTP {e.code}); in NTFY, "
                        "grant pkg_tailwatcher Read-Write on tailwatcher*"))
                    delay = 60
                else:
                    log.warning("listening on %s: %s", self.topic, e)
            except (urllib.error.URLError, OSError, ValueError) as e:
                log.warning("listening on %s: %s", self.topic, e)
            self.stopped.wait(delay)
            delay = min(delay * 2, 60)

    def handle(self, line):
        try:
            msg = json.loads(line)
        except ValueError:
            return
        if msg.get("event") != "message" or msg.get("id") in self.seen:
            return
        self.seen.append(msg["id"])
        self.since = msg["id"]  # resume after this message on reconnect
        if OWN_TAGS & set(msg.get("tags") or []):
            return
        try:
            self.on_message(self.topic, msg.get("message") or "")
        except Exception:  # never let one bad message kill the listener
            log.exception("handling command on %s", self.topic)


class Listeners:
    """Keeps one TopicListener per watcher topic in step with the config."""

    def __init__(self, on_message, on_status):
        self.on_message, self.on_status = on_message, on_status
        self.running = {}  # (topic, url, token) -> TopicListener

    def sync(self, topics, ntfy_url, token):
        wanted = {(t, ntfy_url, token) for t in topics}
        for key in list(self.running):
            if key not in wanted:
                self.running.pop(key).stop()
                self.on_status(key[0], None)
        for key in wanted - set(self.running):
            listener = TopicListener(ntfy_url, token, key[0], self.on_message, self.on_status)
            self.running[key] = listener
            listener.start()
