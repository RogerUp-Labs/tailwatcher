#!/usr/bin/env python3
"""TailWatcher: push an ntfy notification when a watched aircraft takes off.

Polls a public, unfiltered ADS-B API (adsb.lol or adsb.fi) for each
tail number, tracks ground/airborne/unseen per aircraft, and publishes to
ntfy on departure (and optionally on landing). Standard library only.

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
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CONFIG_PATH = os.environ.get("TW_CONFIG", "/data/config.json")
STATE_PATH = os.environ.get("TW_STATE", "/data/state.json")
AIRPORTS_PATH = os.environ.get("TW_AIRPORTS", "/app/airports.csv")
HEALTH_PORT = int(os.environ.get("TW_HEALTH_PORT", "8080"))
USER_AGENT = "TailWatcher/0.1 (+https://github.com/homebrew-gh/tailwatcher)"

DATA_SOURCES = {
    "adsb.lol": "https://api.adsb.lol/v2/reg/{reg}",
    "adsb.fi": "https://opendata.adsb.fi/api/v2/registration/{reg}",
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

log = logging.getLogger("tailwatcher")


# ---------------------------------------------------------------- config


def normalize_tail(tail):
    return re.sub(r"[^A-Z0-9]", "", tail.upper())


def load_config(path=CONFIG_PATH):
    try:
        with open(path) as f:
            raw = json.load(f)
    except FileNotFoundError:
        raw = {}
    aircraft = []
    for a in raw.get("aircraft") or []:
        tail = normalize_tail(a.get("tail") or "")
        if tail:
            aircraft.append({"tail": tail, "label": (a.get("label") or "").strip()})
    return {
        "aircraft": aircraft,
        "ntfy_topic": (raw.get("ntfyTopic") or "").strip(),
        "ntfy_token": (raw.get("ntfyToken") or "").strip(),
        "poll_seconds": max(15, int(raw.get("pollSeconds") or 60)),
        "notify_landing": bool(raw.get("notifyLanding", False)),
        "map_links": raw.get("mapLinks") or "adsbx",
        "data_source": raw.get("dataSource") or "adsb.lol",
        "priority": raw.get("priority") or "default",
    }


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


def build_message(cfg, entry, ac, event, airports):
    tail = entry["tail"]
    name = f"{tail} ({entry['label']})" if entry["label"] else tail
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
    ident = [x for x in (ac.get("t"), callsign if callsign != tail else None) if x]
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
        "topic": cfg["ntfy_topic"],
        "title": f"{name} {verb}",
        "message": "\n".join(lines) or verb,
        "tags": tags,
        "priority": {"min": 1, "low": 2, "default": 3, "high": 4, "max": 5}.get(cfg["priority"], 3),
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


def fetch_aircraft(source, tail, timeout=15):
    url = DATA_SOURCES.get(source, DATA_SOURCES["adsb.lol"]).format(reg=tail)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.load(r)
    matches = [a for a in data.get("ac") or [] if normalize_tail(a.get("r") or "") == tail]
    if not matches:
        return None
    # Prefer a fix with a position, then the freshest one.
    matches.sort(key=lambda a: (a.get("lat") is None, a.get("seen", 99)))
    return matches[0]


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
    cfg = load_config()
    ntfy_url = os.environ.get("NTFY_URL", "").strip()

    problems = []
    if not cfg["aircraft"]:
        problems.append("no tail numbers")
    if not cfg["ntfy_topic"]:
        problems.append("no ntfy topic")
    if not ntfy_url:
        problems.append("ntfy not reachable")
    if problems:
        msg = "Not configured: " + ", ".join(problems) + ". Run the Configure action."
        log.warning(msg)
        health.set(False, msg)
        while True:
            time.sleep(3600)

    airports = Airports()
    state = load_state()
    tails = [a["tail"] for a in cfg["aircraft"]]
    log.info("watching %s via %s, every %ss, ntfy %s topic %s",
             ", ".join(tails), cfg["data_source"], cfg["poll_seconds"], ntfy_url, cfg["ntfy_topic"])

    backoff, error_streak = 0, 0
    while True:
        started = time.time()
        errors, airborne, rate_limited = [], [], False
        for entry in cfg["aircraft"]:
            tail = entry["tail"]
            try:
                ac = fetch_aircraft(cfg["data_source"], tail)
            except urllib.error.HTTPError as e:
                errors.append(f"{tail}: {e}")
                if e.code == 429:
                    rate_limited = True
                    break  # stop hammering; back off below
                continue
            except (urllib.error.URLError, OSError, ValueError) as e:
                errors.append(f"{tail}: {e}")
                continue
            st, event = observe(state.get(tail, {}), ac, time.time())
            if ac is not None:
                st["last_fix"] = {k: ac.get(k) for k in ("lat", "lon", "alt_baro", "gs", "track", "t", "flight")}
            if st.get("status") == "airborne":
                airborne.append(tail)
            notify = event in ("departed", "airborne") or (
                cfg["notify_landing"] and event in ("landed", "lost_low"))
            if event:
                log.info("%s: %s", tail, event)
            if notify:
                fix = ac or {**(st.get("last_fix") or {}), "hex": st.get("hex")}
                try:
                    publish(ntfy_url, cfg["ntfy_token"], build_message(cfg, entry, fix, event, airports))
                except (urllib.error.URLError, OSError) as e:
                    errors.append(f"ntfy: {e}")
                    log.error("ntfy publish failed: %s", e)
                    time.sleep(1.1)
                    continue  # keep the old state so the alert retries next poll
            state[tail] = st
            time.sleep(1.1)  # stay under the APIs' ~1 req/s limit
        save_state(state)

        backoff = min(max(backoff * 2, 60), 600) if rate_limited else 0
        error_streak = error_streak + 1 if errors else 0
        flying = f" — airborne: {', '.join(airborne)}" if airborne else ""
        if errors:
            log.warning("poll errors: %s%s", "; ".join(errors),
                        f" (rate limited, backing off {backoff}s)" if backoff else "")
        if error_streak >= 3:
            health.set(False, "Errors: " + "; ".join(errors)[:300], airborne=airborne)
        elif backoff:
            health.set(True, f"Rate limited by {cfg['data_source']}, retrying in {backoff}s{flying}", airborne=airborne)
        else:
            health.set(True, f"Watching {len(tails)} aircraft{flying}", airborne=airborne)
        time.sleep(max(0, cfg["poll_seconds"] + backoff - (time.time() - started)))


if __name__ == "__main__":
    run()
