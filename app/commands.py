"""Text commands: change a watcher's aircraft list by posting to their ntfy topic.

Each watcher's topic doubles as a chat with TailWatcher. In the ntfy app,
type "N12345" or a flight number like "UA1234" (or "add N12345 Vegas trip
for 3 days") to add an entry, "remove N12345" to drop it, and "list" to see
what's watched. TailWatcher edits the same config.json the StartOS Configure
form uses and replies on the topic.

Each aircraft entry in config.json is {tail, label, kind, expires}: `tail`
holds the tail number or flight number, `kind` is "tail" or "flight", and
`expires` is a Unix time or null. Keep it in sync with
startos/fileModels/config.json.ts.
"""

import datetime

import json
import logging
import math
import os
import re
import threading
import time
import urllib.error
import urllib.request
import zoneinfo
from collections import deque

import flights

log = logging.getLogger("tailwatcher")

# Tags on everything TailWatcher publishes (alerts, replies, test alerts).
# Messages carrying one are ignored, so it never answers itself.
OWN_TAGS = {"airplane", "airplane_arriving", "robot", "test_tube"}
MAX_AIRCRAFT = 50

HELP = (
    "TailWatcher commands\n"
    "\n"
    "🧳 YOUR TRIPS\n"
    "• inbound UA1234 11/14 — track your flight and the plane flying in for it\n"
    "   No AeroDataBox key in Settings? Add the plane and time: inbound UA1234 N38473 dep 4:30pm\n"
    "• inbound UA1234 11/14 return UA5678 11/21 — a round trip\n"
    "• inbound UA1234 then UA567 — with a connection (I'll tell you how long you'll have)\n"
    "• trips — your trips, numbered\n"
    "\n"
    "✏️ CHANGE A TRIP (by its number in \"trips\")\n"
    "• change 1 dep 5:10pm — or a new flight (AA5678), plane (N38473), date (11/15), from DFW or to DEN\n"
    "• return 1 UA5678 11/21 — add the flight home\n"
    "• connect 1 UA567 — add a connecting flight\n"
    "• cancel 1 — stop tracking the whole trip (cancel 1 only: just that flight)\n"
    "\n"
    "📣 SHARE A TRIP\n"
    "• share 1 Mom & Dad — send that watcher your takeoffs and landings\n"
    "• unshare 1 Mom & Dad — stop sharing\n"
    "\n"
    "🛩 WATCH A PLANE OR FLIGHT\n"
    "• N12345 or UA1234 — alert me every time it takes off\n"
    "• add N12345 Vegas trip — with a nickname\n"
    "• UA1234 for 2 days — stop on its own (also 12h, until fri)\n"
    "• remove N12345 — stop watching\n"
    "• info N12345 — what it is, who owns it, where it is now\n"
    "\n"
    "• list — everything you're tracking and watching\n"
    "• help — this list"
)

WEEKDAY_NAMES = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
WEEKDAYS = [d[:3] for d in WEEKDAY_NAMES]
# Trailing "for 2 days", "3d", "12h", "until fri", "until tomorrow".
DURATION_RE = re.compile(
    r"(?:^|\s)(?:for\s+)?(\d+(?:\.\d+)?)\s*(d|days?|h|hrs?|hours?)\s*$", re.I)
DEFAULT_TZ = "America/New_York"
# "until fri" runs through Friday night: entries expire at 3am the next day.
DAY_END_HOUR = 3
UNTIL_RE = re.compile(r"(?:^|\s)until\s+([a-z]+)\s*$", re.I)

CONFIG_LOCK = threading.Lock()


def normalize_tail(tail):
    return re.sub(r"[^A-Z0-9]", "", tail.upper())


def valid_tail(tail):
    return 2 <= len(tail) <= 10 and tail.isalnum()


def looks_like_tail(token):
    """A bare word counts as a tail if it has a digit (N12345) or a dash (G-ABCD)."""
    return valid_tail(normalize_tail(token)) and (
        any(c.isdigit() for c in token) or "-" in token.strip("-"))


def zone(name):
    try:
        return zoneinfo.ZoneInfo(name or DEFAULT_TZ)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):
        return datetime.timezone.utc


def split_expiry(text, now, tz=DEFAULT_TZ):
    """Strip a trailing expiry phrase from text. Returns (rest, expires|None).

    "until <weekday>" means through that day in the configured time zone
    (3am the next morning, so an evening flight still lands); today's
    weekday means today.
    """
    m = DURATION_RE.search(text)
    if m:
        n, unit = float(m.group(1)), m.group(2).lower()
        secs = n * (86400 if unit.startswith("d") else 3600)
        if secs > 0:
            return text[:m.start()].strip(), int(now + secs)
    m = UNTIL_RE.search(text)
    if m:
        word = m.group(1).lower()
        tzinfo = zone(tz)
        today = datetime.datetime.fromtimestamp(now, tzinfo).date()
        days = None
        if word in ("today", "tonight"):
            days = 0
        elif word in ("tomorrow", "tmrw"):
            days = 1
        elif word[:3] in WEEKDAYS and WEEKDAY_NAMES[WEEKDAYS.index(word[:3])].startswith(word):
            days = (WEEKDAYS.index(word[:3]) - today.weekday()) % 7
        if days is not None:
            end = datetime.datetime.combine(
                today + datetime.timedelta(days=days + 1), datetime.time(DAY_END_HOUR), tzinfo)
            return text[:m.start()].strip(), int(end.timestamp())
    return text.strip(), None


def merge_flight_words(words, i):
    """Join "DL 89" into "DL89" at words[i] when the pair is a flight number."""
    if i + 1 < len(words) and words[i + 1].isdigit() and len(words[i]) in (2, 3):
        if flights.parse_flight(words[i] + words[i + 1]):
            return words[:i] + [words[i] + words[i + 1]] + words[i + 2:]
    return words


def parse(text, now=None, tz=DEFAULT_TZ):
    """Parse a message into (verb, ident, label, expires).

    verb is add/remove/list/help/info/inbound/return/connect/trips/cancel/change/share/unshare/unknown; ident is the tail or flight number
    as typed; expires is a Unix time or None.
    """
    now = time.time() if now is None else now
    words = (text or "").split()
    if not words:
        return "unknown", None, "", None
    first = words[0].lower()
    if first in ("list", "ls", "show", "?"):
        return "list", None, "", None
    if first in ("help", "commands"):
        return "help", None, "", None
    if first in ("info", "lookup", "who", "whois", "what") and len(words) >= 2:
        return "info", merge_flight_words(words[1:], 0)[0], "", None
    if first in ("inbound", "trip", "flying") and len(words) >= 2:
        return "inbound", " ".join(words[1:]), "", None  # parsed by trips.parse_inbound
    if first in ("trips", "inbound", "trip") and len(words) == 1:
        return "trips", None, "", None
    if first == "return" and len(words) >= 3:
        return "return", " ".join(words[1:]), "", None  # "return 1 UA5678 11/21", parsed by trips
    if first in ("connect", "then") and len(words) >= 3:
        return "connect", " ".join(words[1:]), "", None  # "connect 1 UA567 dep 2pm", parsed by trips
    if first in ("cancel",) and len(words) >= 2:
        return "cancel", " ".join(words[1:]), "", None  # "2", "AA1234" or "AA1234 11/14"
    if first in ("share", "unshare") and len(words) >= 3:
        return first, " ".join(words[1:]), "", None  # "share 1 Mom & Dad"
    if first in ("change", "update", "edit") and len(words) >= 3:
        return "change", " ".join(words[1:]), "", None  # parsed by trips.select/apply_change
    if first in ("add", "watch", "+") and len(words) >= 2:
        verb, words = "add", merge_flight_words(words[1:], 0)
    elif first in ("remove", "rm", "delete", "del", "unwatch", "-") and len(words) >= 2:
        verb, words = "remove", merge_flight_words(words[1:], 0)
    elif first.startswith("+") and len(first) > 1:
        verb, words = "add", merge_flight_words([words[0][1:]] + words[1:], 0)
    elif first.startswith("-") and len(first) > 1:
        verb, words = "remove", merge_flight_words([words[0][1:]] + words[1:], 0)
    else:
        words = merge_flight_words(words, 0)
        if not looks_like_tail(words[0]):
            return "unknown", None, "", None
        verb = "add"
    if verb == "remove":
        return "remove", words[0], "", None
    label, expires = split_expiry(" ".join(words[1:]), now, tz)
    return "add", words[0], label, expires


def classify(ident):
    """Return (kind, stored form, poll key) for user input, or None if invalid.

    The poll key is the tail itself or the flight's ICAO callsign, so
    "UA1234" and "UAL1234" are the same entry.
    """
    flight = flights.parse_flight(ident)
    if flight:
        return "flight", flight[0], flight[1]
    tail = normalize_tail(ident)
    return ("tail", tail, tail) if valid_tail(tail) else None


def entry_key(a):
    """Poll/state key for a stored aircraft entry."""
    if a.get("kind") == "flight":
        return flights.callsign(a.get("tail") or "")
    return normalize_tail(a.get("tail") or "")


def format_left(expires, now):
    left = math.ceil(max(0, expires - now) / 60) * 60  # "for 2 days" reads back as 2d
    d, h = int(left // 86400), int(left % 86400 // 3600)
    if d:
        return f"{d}d {h}h left" if h else f"{d}d left"
    if h:
        return f"{h}h left"
    return f"{max(1, int(left // 60))}m left"


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


def format_list(watcher, status, now=None):
    now = time.time() if now is None else now
    aircraft = watcher.get("aircraft") or []
    if not aircraft:
        return "Your list is empty. Send a tail or flight number, e.g. N12345 or UA1234, to add one."
    lines = [f"{watcher.get('name') or 'Your'}'s aircraft ({len(aircraft)}):"]
    for a in aircraft:
        tail = a["tail"]
        name = f"{tail} ({a['label']})" if a.get("label") else tail
        st = (status or {}).get(entry_key(a)) or {}
        flags = []
        if st.get("status") == "airborne":
            reg = (st.get("last_fix") or {}).get("r")
            flags.append(f"✈️ airborne ({reg})" if a.get("kind") == "flight" and reg else "✈️ airborne")
        elif st.get("status") == "ground":
            flags.append("on the ground")
        if a.get("expires"):
            flags.append(format_left(a["expires"], now))
        lines.append(f"• {name}" + (" — " + " · ".join(flags) if flags else ""))
    return "\n".join(lines)


def describe_expiry(expires, now):
    return f" for {format_left(expires, now).replace(' left', '')}" if expires else ""


def apply_command(path, topic, text, status=None, now=None):
    """Run one text command for the watcher on `topic`.

    Returns (reply, changed): the reply to post (None if the topic is no
    longer configured) and whether config.json was rewritten.
    """
    now = time.time() if now is None else now
    with CONFIG_LOCK:
        raw = read_raw(path)
        watcher = next((w for w in raw.get("watchers") or [] if w.get("topic") == topic), None)
        if watcher is None:
            return None, False
        verb, ident_in, label, expires = parse(text, now, watcher.get("timeZone") or raw.get("timeZone") or DEFAULT_TZ)
        if verb == "list":
            return format_list(watcher, status, now), False
        if verb == "help":
            return HELP, False
        if verb in ("info", "inbound", "return", "trips", "cancel", "change", "share", "unshare"):
            return None, False  # handled by the caller (network lookups / trips.json)
        if verb == "unknown":
            return "🤔 I didn't understand that. Send \"help\" for commands.", False

        parsed = classify(ident_in)
        if not parsed:
            return f"❌ \"{ident_in}\" doesn't look like a tail or flight number.", False
        kind, ident, key = parsed
        aircraft = watcher.setdefault("aircraft", [])
        existing = next((a for a in aircraft if entry_key(a) == key), None)
        label = label.strip()[:40]

        if verb == "add":
            if existing:
                name = existing["tail"]
                changes = []
                if label and label != existing.get("label"):
                    existing["label"] = label
                    changes.append(f"renamed to \"{label}\"")
                if expires and expires != existing.get("expires"):
                    existing["expires"] = expires
                    changes.append(f"watching{describe_expiry(expires, now)}")
                if changes:
                    write_raw(path, raw)
                    return f"✏️ {name}: " + ", ".join(changes) + ".", True
                return f"👍 Already watching {name}.", False
            if len(aircraft) >= MAX_AIRCRAFT:
                return f"❌ Your list is full ({MAX_AIRCRAFT}). Remove one first.", False
            aircraft.append({"tail": ident, "label": label, "kind": kind, "expires": expires})
            write_raw(path, raw)
            name = f"{ident} ({label})" if label else ident
            what = f"flight {name}" if kind == "flight" else name
            return (f"✅ Added {what}{describe_expiry(expires, now)}. "
                    f"Watching {len(aircraft)} aircraft."), True

        # remove
        if not existing:
            return f"🤷 {ident} isn't on your list.", False
        aircraft.remove(existing)
        write_raw(path, raw)
        return f"🗑 Removed {existing['tail']}. Watching {len(aircraft)} aircraft.", True


def is_watching(path, topic, key):
    """Is `key` (a tail or callsign poll key) on the list of the watcher on `topic`?"""
    raw = read_raw(path)
    watcher = next((w for w in raw.get("watchers") or [] if w.get("topic") == topic), None)
    return bool(watcher) and any(entry_key(a) == key for a in watcher.get("aircraft") or [])


def remove_expired(path, now=None):
    """Drop entries whose `expires` has passed. Returns [(topic, ident), ...]."""
    now = time.time() if now is None else now
    with CONFIG_LOCK:
        raw = read_raw(path)
        removed = []
        for w in raw.get("watchers") or []:
            keep = []
            for a in w.get("aircraft") or []:
                exp = a.get("expires")
                if isinstance(exp, (int, float)) and exp <= now:
                    removed.append((w.get("topic"), a.get("tail")))
                else:
                    keep.append(a)
            w["aircraft"] = keep
        if removed:
            write_raw(path, raw)
        return removed


# ------------------------------------------------------------ listening


def topic_pattern(topic):
    """The NTFY permission pattern that covers a watcher topic: tw-* for
    topics made since 0.12, tailwatcher* for older ones."""
    if topic.startswith("tw-"):
        return "tw-*"
    if topic.startswith("tailwatcher"):
        return "tailwatcher*"
    return topic


def access_hint(topic):
    return ('open ⚙ Settings and run "Set up NTFY for me" again, or in NTFY give the user '
            f"whose token TailWatcher uses Read-Write on {topic_pattern(topic)}")


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
                        f"text commands can't read topic {self.topic} (HTTP {e.code}); "
                        + access_hint(self.topic)))
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
