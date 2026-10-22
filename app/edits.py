"""Edits from the Web UI: watchers and their aircraft.

These write the same config.json the Configure form and text commands use,
under commands.CONFIG_LOCK, and keep its shape (see
startos/fileModels/config.json.ts). Trips are edited through the same code
as the "inbound" / "change" / "cancel" text commands (see tailwatcher.py).
"""

import re
import secrets
import time

import commands
import trips

TOPIC_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
PRIORITIES = ("low", "default", "high", "max")
MAX_WATCHERS = 20
TIME_ZONES = {
    "America/New_York": "US Eastern",
    "America/Chicago": "US Central",
    "America/Denver": "US Mountain",
    "America/Phoenix": "Arizona",
    "America/Los_Angeles": "US Pacific",
    "America/Anchorage": "Alaska",
    "Pacific/Honolulu": "Hawaii",
    "America/Halifax": "Atlantic (Canada)",
    "Europe/London": "UK / Ireland",
    "Europe/Paris": "Central Europe",
    "Europe/Helsinki": "Eastern Europe",
    "Asia/Tokyo": "Japan",
    "Australia/Sydney": "Australia Eastern",
    "UTC": "UTC",
}  # keep in sync with timeZones in startos/fileModels/config.json.ts


def new_topic(name, kind=""):
    """An unguessable topic like "tw-dad-k3j9…" (kind "planes": "tw-dad-planes-k3j9…"):
    on ntfy.sh, where anyone can read any topic, the name is the only lock, so
    20 random characters."""
    slug = re.sub(r"[^a-z0-9]+", "", (name or "").lower())[:12] or "watcher"
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    return f"tw-{slug}-{kind + '-' if kind else ''}" + "".join(secrets.choice(alphabet) for _ in range(20))


class EditError(Exception):
    """A problem to show the person editing, e.g. a duplicate topic."""


def _find(raw, topic):
    return next((w for w in raw.get("watchers") or [] if w.get("topic") == topic), None)


def _uses(w, topic):
    return topic in (w.get("topic"), w.get("planesTopic"))


def save_watcher(path, original, name, topic, priority="default", notify_landing=False, trips_path=None,
                 new_topic_requested=False, planes=None, time_zone=None, reminder=None, result=None):
    """Add a watcher (original=None) or update the one whose topic is `original`.
    A blank topic gets a new unguessable one (new watchers) or stays as it was.
    planes: True gives them a separate Planes topic (kept if they have one),
    False puts plane alerts back in the main topic, None leaves it as it is.
    time_zone: theirs ("" = the server's), None leaves it. reminder: days
    before each flight for a trip reminder (0 = off), None leaves it. The saved topic
    goes in result["topic"]."""
    name, topic = (name or "").strip()[:40], (topic or "").strip()
    if not name:
        raise EditError("Give the watcher a name.")
    if new_topic_requested or not topic:
        topic = new_topic(name) if new_topic_requested or not original else original
    if not TOPIC_RE.match(topic):
        raise EditError("The topic can only use letters, numbers, underscores and hyphens.")
    if priority not in PRIORITIES:
        raise EditError("Pick a priority: low, default, high or max.")
    if time_zone not in (None, "") and time_zone not in TIME_ZONES:
        raise EditError("Pick a time zone from the list.")
    if reminder is not None:
        try:
            reminder = int(reminder)
        except (TypeError, ValueError):
            reminder = -1
        if reminder not in trips.REMINDER_DAYS:
            raise EditError("Pick when to send trip reminders from the list.")
    with commands.CONFIG_LOCK:
        raw = commands.read_raw(path)
        watchers = raw.setdefault("watchers", [])
        current = _find(raw, original) if original else None
        if original and current is None:
            raise EditError("That watcher no longer exists.")
        clash = next((w for w in watchers if _uses(w, topic)), None)
        if clash is not None and clash is not current:
            raise EditError(f"Another watcher already uses the topic {topic}.")
        if current is None:
            if len(watchers) >= MAX_WATCHERS:
                raise EditError(f"TailWatcher supports up to {MAX_WATCHERS} watchers.")
            current = {"name": name, "topic": topic, "aircraft": [], "notifyLanding": False, "priority": "default"}
            watchers.append(current)
        current.update(name=name, topic=topic, priority=priority, notifyLanding=bool(notify_landing))
        if planes is not None:
            keep = current.get("planesTopic") if current.get("planesTopic") != topic else ""
            current["planesTopic"] = (keep or new_topic(name, "planes")) if planes else ""
        if time_zone is not None:
            current["timeZone"] = time_zone
        if reminder is not None:
            current["tripReminder"] = reminder
        commands.write_raw(path, raw)
    if original and original != topic:
        rename_trip_topic(original, topic, trips_path)
    if result is not None:
        result["topic"] = topic
    return f"Saved {name}." if original else f"Added {name}."


def set_time_zone(path, topics, time_zone):
    """Set several watchers' time zone at once (an account's "My time zone")."""
    if time_zone and time_zone not in TIME_ZONES:
        raise EditError("Pick a time zone from the list.")
    with commands.CONFIG_LOCK:
        raw = commands.read_raw(path)
        for w in raw.get("watchers") or []:
            if w.get("topic") in topics:
                w["timeZone"] = time_zone
        commands.write_raw(path, raw)


def rename_trip_topic(old, new, path=None):
    """A watcher's topic changed: move their trips, and the trips other
    people shared with them."""
    with trips.TRIPS_LOCK:
        all_trips = trips.load(path)
        changed = False
        for t in all_trips:
            if t.get("topic") == old:
                t["topic"], changed = new, True
            if old in (t.get("shared_with") or []):
                t["shared_with"], changed = [new if x == old else x for x in t["shared_with"]], True
        if changed:
            trips.save(all_trips, path)


def remove_watcher(path, topic, trips_path=None):
    with commands.CONFIG_LOCK:
        raw = commands.read_raw(path)
        current = _find(raw, topic)
        if current is None:
            raise EditError("That watcher no longer exists.")
        raw["watchers"].remove(current)
        commands.write_raw(path, raw)
    with trips.TRIPS_LOCK:
        all_trips = trips.load(trips_path)
        keep = [t for t in all_trips if t.get("topic") != topic]
        if len(keep) != len(all_trips):
            trips.save(keep, trips_path)
    return f"Removed {current.get('name') or topic} and their trips."


def save_aircraft(path, topic, ident, label="", expires_days=None, original=None, now=None):
    """Add an aircraft or flight to a watcher, or update the entry `original`
    (its tail or flight number as stored). expires_days None = watch forever."""
    now = time.time() if now is None else now
    parsed = commands.classify(ident or "")
    if not parsed or (parsed[0] == "tail" and not commands.valid_tail(parsed[1])):
        raise EditError(f"\"{ident}\" doesn't look like a tail or flight number.")
    kind, shown, key = parsed
    label = (label or "").strip()[:40]
    if expires_days in ("", None):
        expires = None
    else:
        try:
            days = float(expires_days)
        except (TypeError, ValueError):
            raise EditError("Stop-after must be a number of days.") from None
        if not 0 < days <= 366:
            raise EditError("Stop-after must be between 1 and 366 days.")
        expires = round(now + days * 86400)
    with commands.CONFIG_LOCK:
        raw = commands.read_raw(path)
        watcher = _find(raw, topic)
        if watcher is None:
            raise EditError("That watcher no longer exists.")
        aircraft = watcher.setdefault("aircraft", [])
        entry = {"tail": shown, "label": label, "kind": kind, "expires": expires}
        old = None
        if original is not None:
            old = next((a for a in aircraft if a.get("tail") == original), None)
            if old is None:
                raise EditError(f"{original} is no longer on {watcher.get('name')}'s list.")
        clash = next((a for a in aircraft if commands.entry_key(a) == key), None)
        if clash is not None and clash is not old:
            raise EditError(f"{shown} is already on {watcher.get('name')}'s list.")
        if old is not None:
            aircraft[aircraft.index(old)] = entry
        else:
            if len(aircraft) >= commands.MAX_AIRCRAFT:
                raise EditError(f"{watcher.get('name')}'s list is full ({commands.MAX_AIRCRAFT}).")
            aircraft.append(entry)
        commands.write_raw(path, raw)
    what = f"flight {shown}" if kind == "flight" else shown
    return f"Saved {what}." if old is not None else f"Added {what} for {watcher.get('name')}."


def remove_aircraft(path, topic, ident):
    with commands.CONFIG_LOCK:
        raw = commands.read_raw(path)
        watcher = _find(raw, topic)
        if watcher is None:
            raise EditError("That watcher no longer exists.")
        aircraft = watcher.get("aircraft") or []
        entry = next((a for a in aircraft if a.get("tail") == ident), None)
        if entry is None:
            raise EditError(f"{ident} is no longer on {watcher.get('name')}'s list.")
        aircraft.remove(entry)
        commands.write_raw(path, raw)
    return f"Removed {ident} from {watcher.get('name')}'s list."


def save_settings(path, data):
    """Apply the Web UI Settings panel. Only keys present in `data` change;
    secrets are only set when a new value is typed, or cleared on request."""
    changes = {}

    def choice(key, allowed):
        if data[key] not in allowed:
            raise EditError(f"Invalid {key}.")
        return data[key]
    if "ntfyServer" in data:
        changes["ntfyServer"] = choice("ntfyServer", ("public", "local", "custom"))
    if "ntfyCustomUrl" in data:
        url = str(data["ntfyCustomUrl"] or "").strip().rstrip("/")
        if url and not re.match(r"^https?://\S+$", url):
            raise EditError("The custom server address must start with https:// or http://.")
        changes["ntfyCustomUrl"] = url
    if data.get("ntfyToken"):
        token = str(data["ntfyToken"]).strip()
        if not re.match(r"^tk_[A-Za-z0-9]+$", token):
            raise EditError("NTFY tokens start with tk_.")
        changes["ntfyToken"] = token
    if data.get("clearNtfyToken"):
        changes["ntfyToken"] = ""
    if "ntfyPhoneMode" in data:
        changes["ntfyPhoneMode"] = choice("ntfyPhoneMode", ("open", "login"))
    if data.get("aerodataboxKey"):
        changes["aerodataboxKey"] = str(data["aerodataboxKey"]).strip()
    if data.get("clearAerodatabox"):
        changes["aerodataboxKey"] = ""
    if "dataSource" in data:
        changes["dataSource"] = choice("dataSource", ("adsb.fi", "adsb.lol"))
    if "mapLinks" in data:
        changes["mapLinks"] = choice("mapLinks", ("adsbx", "adsblol", "both"))
    if "timeZone" in data:
        changes["timeZone"] = choice("timeZone", tuple(TIME_ZONES))
    if "pollSeconds" in data:
        try:
            secs = int(data["pollSeconds"])
        except (TypeError, ValueError):
            raise EditError("Check every must be a number of seconds.") from None
        if not 15 <= secs <= 600:
            raise EditError("Check every must be between 15 and 600 seconds.")
        changes["pollSeconds"] = secs
    if "webAuth" in data:
        changes["webAuth"] = choice("webAuth", ("off", "password", "accounts"))
        changes["webPassword"] = changes["webAuth"] != "off"  # what 0.21 and older read
    for key in ("textCommands",):
        if key in data:
            changes[key] = bool(data[key])
    with commands.CONFIG_LOCK:
        raw = commands.read_raw(path)
        if changes.get("ntfyServer", raw.get("ntfyServer")) == "custom" and not changes.get(
                "ntfyCustomUrl", raw.get("ntfyCustomUrl")):
            raise EditError("Enter the custom server's address.")
        raw.update(changes)
        commands.write_raw(path, raw)
    return "Settings saved."
