"""Edits from the Web UI: watchers and their aircraft.

These write the same config.json the Configure form and text commands use,
under commands.CONFIG_LOCK, and keep its shape (see
startos/fileModels/config.json.ts). Trips are edited through the same code
as the "inbound" / "change" / "cancel" text commands (see tailwatcher.py).
"""

import re
import time

import commands
import trips

TOPIC_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
PRIORITIES = ("low", "default", "high", "max")
MAX_WATCHERS = 20


class EditError(Exception):
    """A problem to show the person editing, e.g. a duplicate topic."""


def _find(raw, topic):
    return next((w for w in raw.get("watchers") or [] if w.get("topic") == topic), None)


def save_watcher(path, original, name, topic, priority="default", notify_landing=False, trips_path=None):
    """Add a watcher (original=None) or update the one whose topic is `original`."""
    name, topic = (name or "").strip()[:40], (topic or "").strip()
    if not name:
        raise EditError("Give the watcher a name.")
    if not TOPIC_RE.match(topic):
        raise EditError("The topic can only use letters, numbers, underscores and hyphens.")
    if priority not in PRIORITIES:
        raise EditError("Pick a priority: low, default, high or max.")
    with commands.CONFIG_LOCK:
        raw = commands.read_raw(path)
        watchers = raw.setdefault("watchers", [])
        current = _find(raw, original) if original else None
        if original and current is None:
            raise EditError("That watcher no longer exists.")
        clash = _find(raw, topic)
        if clash is not None and clash is not current:
            raise EditError(f"Another watcher already uses the topic {topic}.")
        if current is None:
            if len(watchers) >= MAX_WATCHERS:
                raise EditError(f"TailWatcher supports up to {MAX_WATCHERS} watchers.")
            current = {"name": name, "topic": topic, "aircraft": [], "notifyLanding": False, "priority": "default"}
            watchers.append(current)
        current.update(name=name, topic=topic, priority=priority, notifyLanding=bool(notify_landing))
        commands.write_raw(path, raw)
    if original and original != topic:
        rename_trip_topic(original, topic, trips_path)
    return f"Saved {name}." if original else f"Added {name}."


def rename_trip_topic(old, new, path=None):
    with trips.TRIPS_LOCK:
        all_trips = trips.load(path)
        changed = [t for t in all_trips if t.get("topic") == old]
        for t in changed:
            t["topic"] = new
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
