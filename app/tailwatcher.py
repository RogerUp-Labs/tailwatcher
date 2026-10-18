#!/usr/bin/env python3
"""TailWatcher: push an ntfy notification when a watched aircraft takes off.

Polls a public, unfiltered ADS-B API (adsb.lol or adsb.fi) for each
tail number or flight number (by ICAO callsign), tracks ground/airborne/unseen per aircraft, and publishes to each
watcher's ntfy topic on departure (and optionally on landing). Each tail is
polled once however many watchers follow it. Standard library only.

Config:  $TW_CONFIG (default /data/config.json), written by the StartOS
         Configure action.
State:   $TW_STATE (default /data/state.json), so restarts don't re-alert.
Env:     NTFY_URL  base URL of the ntfy server (e.g. http://10.0.3.5:80)
"""

import csv
import json
import logging
import math
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import commands
import flights
from commands import entry_key, normalize_tail

CONFIG_PATH = os.environ.get("TW_CONFIG", "/data/config.json")
STATE_PATH = os.environ.get("TW_STATE", "/data/state.json")
AIRPORTS_PATH = os.environ.get("TW_AIRPORTS", "/app/airports.csv")
HEALTH_PORT = int(os.environ.get("TW_HEALTH_PORT", "8080"))
USER_AGENT = "TailWatcher/0.4 (+https://github.com/homebrew-gh/tailwatcher)"

DATA_SOURCES = {
    "adsb.lol": {"tail": "https://api.adsb.lol/v2/reg/{key}",
                 "flight": "https://api.adsb.lol/v2/callsign/{key}"},
    "adsb.fi": {"tail": "https://opendata.adsb.fi/api/v2/registration/{key}",
                "flight": "https://opendata.adsb.fi/api/v2/callsign/{key}"},
}
MAP_LINKS = {
    "adsbx": ("ADS-B Exchange", "https://globe.adsbexchange.com/?icao={hex}"),
    "adsblol": ("adsb.lol", "https://adsb.lol/?icao={hex}"),
}

# An aircraft unseen this long is treated as "off the radar": seeing it
# airborne again counts as a new departure (small fields often have no
# ground-level ADS-B coverage, so the first fix is already in the air).
GAP_SECONDS = 20 * 60
# Below this altitude, losing the signal mid-flight is reported as a
# probable landing rather than silently dropped.
LOW_ALT_FT = 3000
# Above this, "nearest airport" says nothing useful about where it came from.
NEAR_AIRPORT_MAX_FT = 8000
# Alerts that fail to publish (ntfy down) are retried for this long.
RETRY_SECONDS = 30 * 60

log = logging.getLogger("tailwatcher")


# ---------------------------------------------------------------- config


def load_config(path=CONFIG_PATH, now=None):
    now = time.time() if now is None else now
    try:
        with open(path) as f:
            raw = json.load(f)
    except FileNotFoundError:
        raw = {}

    watchers_raw = raw.get("watchers")
    if watchers_raw is None and raw.get("aircraft"):
        # 0.1.x format: one aircraft list and one topic.
        watchers_raw = [{
            "name": "Me",
            "topic": raw.get("ntfyTopic") or "tailwatcher",
            "aircraft": raw["aircraft"],
            "notifyLanding": raw.get("notifyLanding", False),
            "priority": raw.get("priority", "default"),
        }]

    watchers = []
    for w in watchers_raw or []:
        topic = (w.get("topic") or "").strip()
        aircraft = []
        for a in w.get("aircraft") or []:
            kind = "flight" if a.get("kind") == "flight" else "tail"
            expires = a.get("expires")
            if isinstance(expires, (int, float)) and expires <= now:
                continue  # removed from the file at the next cycle
            if kind == "flight":
                parsed = flights.parse_flight(a.get("tail") or "")
                ident = parsed[0] if parsed else flights.compact(a.get("tail"))
            else:
                ident = normalize_tail(a.get("tail") or "")
            if ident:
                entry = {"tail": ident, "label": (a.get("label") or "").strip(), "kind": kind,
                         "expires": expires if isinstance(expires, (int, float)) else None}
                entry["key"] = entry_key(entry)
                aircraft.append(entry)
        if topic:
            watchers.append({
                "name": (w.get("name") or topic).strip(),
                "topic": topic,
                "aircraft": aircraft,
                "notify_landing": bool(w.get("notifyLanding", False)),
                "priority": w.get("priority") or "default",
            })

    return {
        "watchers": watchers,
        "ntfy_token": (raw.get("ntfyToken") or "").strip(),
        "poll_seconds": max(15, int(raw.get("pollSeconds") or 60)),
        "map_links": raw.get("mapLinks") or "adsbx",
        "data_source": raw.get("dataSource") or "adsb.lol",
        "text_commands": bool(raw.get("textCommands", True)),
    }


def subscriptions(cfg):
    """Map each tail/callsign to the watchers following it, so each is polled once.

    Returns {key: [(watcher, entry), ...]} in first-seen order, where key is
    the tail number or the flight's ICAO callsign.
    """
    subs = {}
    for w in cfg["watchers"]:
        for a in w["aircraft"]:
            subs.setdefault(a["key"], []).append((w, a))
    return subs


# -------------------------------------------------------------- airports


class Airports:
    """Nearest-airport lookup over the OurAirports extract baked into the image."""

    def __init__(self, path=AIRPORTS_PATH):
        self.rows = []
        try:
            with open(path, newline="") as f:
                for r in csv.DictReader(f):
                    self.rows.append(
                        (r["ident"], r["name"], float(r["lat"]), float(r["lon"]))
                    )
        except (OSError, KeyError, ValueError) as e:
            log.warning("airport database unavailable (%s)", e)

    def nearest(self, lat, lon, max_nm=15):
        best, best_d = None, max_nm
        for ident, name, alat, alon in self.rows:
            if abs(alat - lat) > 0.5:
                continue
            d = haversine_nm(lat, lon, alat, alon)
            if d < best_d:
                best, best_d = (ident, name), d
        return (best[0], best[1], best_d) if best else None


def haversine_nm(lat1, lon1, lat2, lon2):
    r = 3440.065
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# ----------------------------------------------------------- state logic


def observe(prev, ac, now):
    """Fold one poll result into an aircraft's state.

    prev: stored state dict (may be empty).  ac: aircraft dict from the API,
    or None if not currently seen.  Returns (new_state, event) where event is
    None, "departed", "airborne", "landed" or "lost_low".
    """
    st = dict(prev)
    last_seen = st.get("last_seen", 0)
    was = st.get("status", "unknown")  # ground | airborne | unknown
    gap = now - last_seen > GAP_SECONDS

    if ac is None:
        if was == "airborne" and gap:
            st["status"] = "unknown"
            low = (st.get("last_alt") or 0) < LOW_ALT_FT
            return st, ("lost_low" if low else None)
        return st, None

    alt = ac.get("alt_baro")
    on_ground = alt == "ground"
    st.update(
        last_seen=now,
        status="ground" if on_ground else "airborne",
        last_alt=0 if on_ground else alt,
        hex=ac.get("hex", st.get("hex")),
    )

    if on_ground:
        return st, ("landed" if was == "airborne" and not gap else None)
    if was == "ground" and not gap:
        return st, "departed"
    if was == "unknown" or gap:
        return st, "airborne"
    return st, None


# ----------------------------------------------------------------- ntfy


def build_message(cfg, watcher, tail, label, ac, event, airports, kind="tail"):
    # A flight's title names the aircraft flying it: "UA1234 (N38473) departed".
    reg = (ac.get("r") or "").strip() if kind == "flight" else ""
    extra = ", ".join(x for x in (label, reg) if x)
    name = f"{tail} ({extra})" if extra else tail
    verb = {
        "departed": "departed",
        "airborne": "is airborne",
        "landed": "landed",
        "lost_low": "likely landed",
    }[event]

    lines = []
    lat, lon = ac.get("lat"), ac.get("lon")
    alt = ac.get("alt_baro")
    low = alt == "ground" or (isinstance(alt, (int, float)) and alt < NEAR_AIRPORT_MAX_FT)
    if lat is not None and lon is not None and low:
        near = airports.nearest(lat, lon)
        if near:
            ident, apt, dist = near
            where = "at" if dist < 2 else f"{dist:.0f} nm from"
            lines.append(f"{where} {ident} – {apt}")
    stats = []
    if isinstance(alt, (int, float)):
        stats.append(f"{alt:,.0f} ft")
    if ac.get("gs") is not None:
        stats.append(f"{ac['gs']:.0f} kt")
    if ac.get("track") is not None:
        stats.append(f"hdg {ac['track']:03.0f}°")
    if stats:
        lines.append(" · ".join(stats))
    callsign = (ac.get("flight") or "").strip()
    ident = [x for x in (ac.get("t"), callsign if callsign not in (tail, "") else None) if x]
    if ident:
        lines.append(" · ".join(ident))
    if event == "lost_low":
        lines.append("Signal lost at low altitude")

    hexcode = ac.get("hex", "")
    keys = ["adsbx", "adsblol"] if cfg["map_links"] == "both" else [cfg["map_links"]]
    actions = [
        {"action": "view", "label": MAP_LINKS[k][0], "url": MAP_LINKS[k][1].format(hex=hexcode), "clear": True}
        for k in keys
        if k in MAP_LINKS and hexcode
    ]
    tags = ["airplane"] if event in ("departed", "airborne") else ["airplane_arriving"]
    return {
        "topic": watcher["topic"],
        "title": f"{name} {verb}",
        "message": "\n".join(lines) or verb,
        "tags": tags,
        "priority": {"min": 1, "low": 2, "default": 3, "high": 4, "max": 5}.get(watcher["priority"], 3),
        "click": actions[0]["url"] if actions else None,
        "actions": actions,
    }


def publish(ntfy_url, token, payload, timeout=15):
    body = json.dumps({k: v for k, v in payload.items() if v is not None}).encode()
    req = urllib.request.Request(ntfy_url.rstrip("/") + "/", data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", USER_AGENT)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status


# ------------------------------------------------------------- polling


def pick_match(data, key, kind="tail"):
    """The best record for a tail (`r`) or callsign (trimmed `flight`)."""
    if kind == "flight":
        matches = [a for a in data.get("ac") or [] if flights.matches(a, key)]
    else:
        matches = [a for a in data.get("ac") or [] if normalize_tail(a.get("r") or "") == key]
    if not matches:
        return None
    # Prefer a fix with a position, then the freshest one.
    matches.sort(key=lambda a: (a.get("lat") is None, a.get("seen", 99)))
    return matches[0]


def fetch_aircraft(source, key, kind="tail", timeout=15):
    url = DATA_SOURCES.get(source, DATA_SOURCES["adsb.lol"])[kind].format(key=key)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return pick_match(json.load(r), key, kind)


def config_mtime():
    try:
        return os.stat(CONFIG_PATH).st_mtime_ns
    except OSError:
        return None


def load_state():
    try:
        with open(STATE_PATH) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(state):
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=1)
    os.replace(tmp, STATE_PATH)


class Health:
    def __init__(self):
        self.lock = threading.Lock()
        self.status = {"ok": False, "message": "Starting"}

    def set(self, ok, message, **extra):
        with self.lock:
            self.status = {"ok": ok, "message": message, "time": int(time.time()), **extra}

    def get(self):
        with self.lock:
            return dict(self.status)


def serve_health(health):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps(health.get()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    srv = ThreadingHTTPServer(("0.0.0.0", HEALTH_PORT), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()


def run():
    logging.basicConfig(
        level=os.environ.get("TW_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )
    health = Health()
    serve_health(health)
    ntfy_url = os.environ.get("NTFY_URL", "").strip()
    airports = Airports()
    state = load_state()
    retry_queue = state.pop("_retry", [])
    cfg, subs, cfg_mtime = load_config(), {}, None  # (re)loaded at the top of each cycle

    # Topics whose last publish was refused (bad grant/token), and topics the
    # command listener can't read; both shown in health until they recover.
    topic_errors, listen_errors = {}, {}
    # Set by a text command that changed the list, to poll right away.
    wake = threading.Event()

    def on_command(topic, text):
        reply, changed = commands.apply_command(CONFIG_PATH, topic, text, status=load_state())
        log.info("command on %s: %r → %s", topic, text, reply.splitlines()[0] if reply else "ignored")
        if reply:
            send({"topic": topic, "message": reply, "tags": ["robot"], "priority": 2})
        if changed:
            wake.set()

    def on_listen_status(topic, err):
        if err and listen_errors.get(topic) != err:
            log.error(err)
        if err:
            listen_errors[topic] = err
        else:
            listen_errors.pop(topic, None)

    listeners = commands.Listeners(on_command, on_listen_status)

    def send(payload):
        """Publish once; queue transient failures for retry, record refusals."""
        topic = payload["topic"]
        try:
            publish(ntfy_url, cfg["ntfy_token"], payload)
            topic_errors.pop(topic, None)
            return True
        except urllib.error.HTTPError as e:
            if e.code != 429 and e.code < 500:
                topic_errors[topic] = (
                    f"NTFY refused topic {topic} (HTTP {e.code}); check the "
                    "publisher token has access to it")
                log.error(topic_errors[topic])
                return True  # retrying won't help; don't queue
            err = e
        except (urllib.error.URLError, OSError) as e:
            err = e
        log.error("ntfy publish to %s failed: %s (will retry)", topic, err)
        return False

    backoff, error_streak = 0, 0
    while True:
        # Trip entries ("UA1234 for 2 days") remove themselves; the file
        # change is picked up just below.
        try:
            expired = commands.remove_expired(CONFIG_PATH)
        except (OSError, ValueError) as e:
            log.error("removing expired entries: %s", e)
            expired = []
        for topic, ident in expired:
            log.info("%s: expired for %s", ident, topic)
            if ntfy_url:
                send({"topic": topic, "message": f"⌛ Stopped watching {ident} (expired)",
                      "tags": ["robot"], "priority": 2})

        mtime = config_mtime()
        if mtime != cfg_mtime:
            # Configure (StartOS) or a text command changed the file: apply it
            # without restarting.
            cfg_mtime, cfg = mtime, load_config()
            subs = subscriptions(cfg)
            for w in cfg["watchers"]:
                log.info("watcher %s → topic %s: %s", w["name"], w["topic"],
                         ", ".join(a["tail"] if a["kind"] == "tail" else f"{a['tail']} ({a['key']})"
                                   for a in w["aircraft"]) or "(none yet)")
            log.info("polling %d aircraft via %s every %ss, ntfy %s, text commands %s",
                     len(subs), cfg["data_source"], cfg["poll_seconds"], ntfy_url,
                     "on" if cfg["text_commands"] else "off")
            topics = [w["topic"] for w in cfg["watchers"]] if cfg["text_commands"] and ntfy_url else []
            listeners.sync(topics, ntfy_url, cfg["ntfy_token"])

        if not cfg["watchers"] or not ntfy_url:
            problems = [] if cfg["watchers"] else ["no watchers"]
            if not ntfy_url:
                problems.append("NTFY not reachable")
            health.set(False, "Not configured: " + ", ".join(problems) + ". Run the Configure action.")
            wake.wait(10)
            wake.clear()
            continue

        started = time.time()
        errors, airborne, rate_limited = [], [], False

        still_pending = []
        for item in retry_queue:
            if started > item["until"]:
                log.warning("giving up on alert to %s: %s", item["payload"]["topic"], item["payload"]["title"])
            elif not send(item["payload"]):
                still_pending.append(item)
        retry_queue = still_pending
        if retry_queue:
            errors.append(f"ntfy: {len(retry_queue)} alert(s) waiting to retry")

        for key, followers in subs.items():
            kind, shown = followers[0][1]["kind"], followers[0][1]["tail"]
            try:
                ac = fetch_aircraft(cfg["data_source"], key, kind)
            except urllib.error.HTTPError as e:
                errors.append(f"{shown}: {e}")
                if e.code == 429:
                    rate_limited = True
                    break  # stop hammering; back off below
                continue
            except (urllib.error.URLError, OSError, ValueError) as e:
                errors.append(f"{shown}: {e}")
                continue
            st, event = observe(state.get(key, {}), ac, time.time())
            if ac is not None:
                st["last_fix"] = {k: ac.get(k) for k in ("lat", "lon", "alt_baro", "gs", "track", "t", "flight", "r")}
            if st.get("status") == "airborne":
                airborne.append(shown)
            if event:
                log.info("%s: %s", key, event)
                fix = ac or {**(st.get("last_fix") or {}), "hex": st.get("hex")}
                for watcher, entry in followers:
                    if event in ("landed", "lost_low") and not watcher["notify_landing"]:
                        continue
                    payload = build_message(cfg, watcher, entry["tail"], entry["label"], fix, event,
                                            airports, entry["kind"])
                    if not send(payload):
                        retry_queue.append({"payload": payload, "until": time.time() + RETRY_SECONDS})
            state[key] = st
            time.sleep(1.1)  # stay under the APIs' ~1 req/s limit
        save_state({**state, "_retry": retry_queue})

        backoff = min(max(backoff * 2, 60), 600) if rate_limited else 0
        error_streak = error_streak + 1 if errors else 0
        flying = f" — airborne: {', '.join(airborne)}" if airborne else ""
        if errors:
            log.warning("poll errors: %s%s", "; ".join(errors),
                        f" (rate limited, backing off {backoff}s)" if backoff else "")
        refusals = list(topic_errors.values()) + list(listen_errors.values())
        if refusals:
            health.set(False, "; ".join(refusals)[:300], airborne=airborne)
        elif error_streak >= 3:
            health.set(False, "Errors: " + "; ".join(errors)[:300], airborne=airborne)
        elif backoff:
            health.set(True, f"Rate limited by {cfg['data_source']}, retrying in {backoff}s{flying}", airborne=airborne)
        elif not subs:
            health.set(True, "No aircraft yet. Text a tail or flight number to a watcher's topic, or use Configure.")
        else:
            n_w = len(cfg["watchers"])
            health.set(True, f"Watching {len(subs)} aircraft for {n_w} watcher{'s' if n_w != 1 else ''}{flying}",
                       airborne=airborne)
        wait = max(0, cfg["poll_seconds"] + backoff - (time.time() - started))
        if backoff:
            time.sleep(wait)  # don't let text commands cut a rate-limit backoff short
        else:
            wake.wait(wait)
        wake.clear()

if __name__ == "__main__":
    run()
