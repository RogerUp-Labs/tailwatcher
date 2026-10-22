#!/usr/bin/env python3
"""TailWatcher: push an ntfy notification when a watched aircraft takes off.

Polls a public, unfiltered ADS-B API (adsb.lol or adsb.fi) for each
tail number or flight number (by ICAO callsign), tracks ground/airborne/unseen per aircraft, and publishes to each
watcher's ntfy topic on departure (and optionally on landing). Each tail is
polled once however many watchers follow it. Standard library only.

Config:  $TW_CONFIG (default /data/config.json), written by the StartOS
         Configure action or the Web UI's Settings.
State:   $TW_STATE (default /data/state.json), so restarts don't re-alert.
Env:     NTFY_URL        this server's NTFY as TailWatcher reaches it (e.g. http://10.0.3.5:80,
                         or http://ntfy:80 in docker-compose)
         NTFY_PHONE_URL  the address phones use for that NTFY (for "Connect phone" links)
         TAILWATCHER_PUBLIC_URL  TailWatcher's own https address, for invite links
         TW_PLATFORM     "startos" or "docker"; TAILWATCHER_PASSWORD (Docker) sets
                         the dashboard password
Which server is used comes from config.json "ntfyServer": public (ntfy.sh,
the default), local (NTFY_URL) or custom ("ntfyCustomUrl").
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
import urllib.parse
import urllib.request

import commands
import edits
import flights
import history
import invites
import itinerary
import lookup
import ntfy_admin
import trips
import web
from commands import entry_key, normalize_tail

CONFIG_PATH = os.environ.get("TW_CONFIG", "/data/config.json")
STATE_PATH = os.environ.get("TW_STATE", "/data/state.json")
AIRPORTS_PATH = os.environ.get("TW_AIRPORTS", "/app/airports.csv")
HEALTH_PORT = int(os.environ.get("TW_HEALTH_PORT", "8080"))
VERSION = "0.21.1"
# "startos" (main.ts sets it) or "docker" (the Dockerfile's default): only
# changes setup hints and whether the dashboard password starts on.
PLATFORM = os.environ.get("TW_PLATFORM", "startos")
USER_AGENT = f"TailWatcher/{VERSION} (+https://github.com/RogerUp-Labs/tailwatcher)"

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
        planes = (w.get("planesTopic") or "").strip()
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
                # Optional second topic for tail/flight watching, so the main
                # topic stays about trips. Blank = plane alerts go to `topic`.
                "planes_topic": planes if planes != topic else "",
                "aircraft": aircraft,
                "notify_landing": bool(w.get("notifyLanding", False)),
                "priority": w.get("priority") or "default",
            })

    return {
        "watchers": watchers,
        "ntfy_token": (raw.get("ntfyToken") or "").strip(),
        "poll_seconds": max(15, int(raw.get("pollSeconds") or 60)),
        "map_links": raw.get("mapLinks") or "adsbx",
        "data_source": raw.get("dataSource") or "adsb.fi",
        "text_commands": bool(raw.get("textCommands", True)),
        "time_zone": raw.get("timeZone") or commands.DEFAULT_TZ,
        # Installs from before 0.12 used this server's NTFY with a token.
        "ntfy_server": raw.get("ntfyServer") or ("local" if raw.get("ntfyToken") else "public"),
        "ntfy_custom_url": (raw.get("ntfyCustomUrl") or "").strip(),
        "ntfy_phone_mode": raw.get("ntfyPhoneMode") or "open",
        "adb_key": (raw.get("aerodataboxKey") or "").strip(),
        # Off by default on StartOS (LAN/VPN only); on for a plain Docker install,
        # whose port may be forwarded anywhere.
        "web_password": bool(raw.get("webPassword", PLATFORM != "startos")),
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
        self.coords = {}  # ident -> (lat, lon, name)
        self.iata = {}    # "IAD" -> "KIAD"
        self.tz = {}      # ident -> "America/New_York"
        self.towns = []   # (lat, lon, "Denver, CO") from medium/large airports' cities
        try:
            with open(path, newline="") as f:
                for r in csv.DictReader(f):
                    lat, lon = float(r["lat"]), float(r["lon"])
                    self.rows.append((r["ident"], r["name"], lat, lon))
                    self.coords[r["ident"]] = (lat, lon, r["name"])
                    if r.get("iata"):
                        self.iata.setdefault(r["iata"], r["ident"])
                    if r.get("tz"):
                        self.tz[r["ident"]] = r["tz"]
                    if r.get("city") and r.get("size") in ("m", "l"):
                        town = f"{r['city']}, {r['region']}" if r.get("region") else r["city"]
                        self.towns.append((lat, lon, town))
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


    def town(self, lat, lon, max_nm=300):
        """Nearest city with a sizeable airport: (town, distance_nm, bearing) or None."""
        best, best_d = None, max_nm
        for alat, alon, name in self.towns:
            if abs(alat - lat) > max_nm / 60:
                continue
            d = haversine_nm(alat, alon, lat, lon)
            if d < best_d:
                best, best_d = (name, alat, alon), d
        return (best[0], best_d, bearing(best[1], best[2], lat, lon)) if best else None

    def place(self, lat, lon, on_ground=False):
        """Plain-text approximate location for the dashboard: "at KFDK – Frederick
        Municipal Airport", "near Denver, CO", "40 nm NE of Denver, CO", or
        coordinates when nothing is near (oceans, or no airport data)."""
        if lat is None or lon is None:
            return None
        if on_ground:
            apt = self.nearest(lat, lon, 3)
            if apt:
                return f"at {apt[0]} – {apt[1]}"
        town = self.town(lat, lon)
        if town:
            name, d, brg = town
            return f"near {name}" if d < 15 else f"{d:.0f} nm {COMPASS[round(brg / 45) % 8]} of {name}"
        return f"{abs(lat):.1f}°{'N' if lat >= 0 else 'S'} {abs(lon):.1f}°{'E' if lon >= 0 else 'W'}"


COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


def bearing(lat1, lon1, lat2, lon2):
    """Initial bearing in degrees from point 1 to point 2."""
    p1, p2, dl = math.radians(lat1), math.radians(lat2), math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return math.degrees(math.atan2(x, y)) % 360


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


def planes_topic(watcher):
    """Where a watcher's plane-watching alerts go: their Planes topic if set."""
    return watcher.get("planes_topic") or watcher["topic"]


def home_topics(cfg):
    """Every topic TailWatcher listens on, mapped to its watcher's main topic."""
    out = {}
    for w in cfg["watchers"]:
        out[w["topic"]] = w["topic"]
        if w.get("planes_topic"):
            out.setdefault(w["planes_topic"], w["topic"])
    return out


PUBLIC_NTFY = "https://ntfy.sh"


def resolve_ntfy(cfg, env=os.environ):
    """(url TailWatcher publishes to, token to send, address phones subscribe to).

    The token is only sent to your own or a custom server, never to ntfy.sh,
    where anonymous publishing to an unguessable topic is the whole model.
    """
    mode = cfg.get("ntfy_server") or "public"
    if mode == "custom":
        url = cfg.get("ntfy_custom_url") or ""
        return url, cfg.get("ntfy_token") or "", url
    if mode == "local":
        return ((env.get("NTFY_URL") or "").strip(), cfg.get("ntfy_token") or "",
                (env.get("NTFY_PHONE_URL") or "").strip())
    return PUBLIC_NTFY, "", PUBLIC_NTFY


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
    url = DATA_SOURCES.get(source, DATA_SOURCES["adsb.fi"])[kind].format(key=key)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return pick_match(json.load(r), key, kind)


BATCH = 25  # keys per request; both feeds take comma-separated lists


def fetch_many(source, wanted, timeout=20, sleep=time.sleep, get=None):
    """Look up many tails and callsigns in as few requests as possible.

    wanted: {(kind, key)}. Returns {key: record or None}. Both feeds accept
    "N1,N2,N3" in one request, so a cycle costs one request per 25 keys
    instead of one per aircraft (adsb.lol allows only 500 requests a day).
    Raises urllib errors; the caller falls back to the other feed.
    """
    templates = DATA_SOURCES.get(source, DATA_SOURCES["adsb.fi"])
    out, first = {}, True
    for kind in ("tail", "flight"):
        keys = sorted(k for kd, k in wanted if kd == kind)
        for i in range(0, len(keys), BATCH):
            chunk = keys[i:i + BATCH]
            if not first:
                sleep(1.1)  # stay under 1 request per second
            first = False
            url = templates[kind].format(key=",".join(urllib.parse.quote(k) for k in chunk))
            if get:
                data = get(url)
            else:
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    data = json.load(r)
            for key in chunk:
                out[key] = pick_match(data, key, kind)
    return out


def poll_all(source, wanted, fetch=fetch_many):
    """fetch_many with fallback: if the chosen feed refuses or fails, try the other.

    Returns (fixes, error_text or None, rate_limited).
    """
    other = "adsb.lol" if source == "adsb.fi" else "adsb.fi"
    problems, limited = [], False
    for src in (source, other):
        try:
            return fetch(src, wanted), ("; ".join(problems) or None), False
        except urllib.error.HTTPError as e:
            limited = limited or e.code == 429
            problems.append(f"{src}: {'too many requests' if e.code == 429 else e}")
        except (urllib.error.URLError, OSError, ValueError) as e:
            problems.append(f"{src}: {e}")
    return {}, "; ".join(problems), limited


def web_password_required(path=CONFIG_PATH):
    """Read straight from config.json on each request, so turning the password
    on in Configure applies at once rather than at the next poll cycle."""
    default = PLATFORM != "startos"
    try:
        with open(path) as f:
            return json.load(f).get("webPassword", default) is True
    except (OSError, ValueError, AttributeError):
        return default


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


def message_kind(payload):
    tags = set(payload.get("tags") or [])
    if "test_tube" in tags:
        return "test"
    if tags & {"airplane", "airplane_arriving"}:
        return "trip" if "🧳" in (payload.get("title") or "") or "your plane" in (payload.get("title") or "") \
            else "alert"
    return "reply"


def run():
    logging.basicConfig(
        level=os.environ.get("TW_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )
    if PLATFORM != "startos":  # StartOS init writes it and shows it in Actions
        password = web.ensure_password(wanted=os.environ.get("TAILWATCHER_PASSWORD"))
        if web_password_required():
            log.info("Web UI password: %s (any username; change it with TAILWATCHER_PASSWORD, "
                     "or run: docker exec tailwatcher python /app/tailwatcher.py reset-password)", password)
    health = Health()
    hist = history.History()
    ntfy_url, ntfy_token, phone_url = resolve_ntfy(load_config())
    airports = Airports()
    state = load_state()
    retry_queue = state.pop("_retry", [])
    cfg, subs, cfg_mtime = load_config(), {}, None  # (re)loaded at the top of each cycle

    # Topics whose last publish was refused (bad grant/token), and topics the
    # command listener can't read; both shown in health until they recover.
    topic_errors, listen_errors = {}, {}
    # Set by a text command that changed the list, to poll right away.
    wake = threading.Event()

    def on_info(topic, ident_in):
        """Answer "info N12345" / "info UA1234" with a full aircraft lookup."""
        entry = commands.classify(ident_in or "")
        if not entry:
            return {"message": f"❌ \"{ident_in}\" doesn't look like a tail or flight number."}
        kind, shown, key = entry
        tail = shown
        if kind == "flight":
            try:
                ac = fetch_aircraft(cfg["data_source"], key, "flight")
            except (urllib.error.URLError, OSError, ValueError):
                ac = None
            if not ac or not ac.get("r"):
                return {"message": f"{shown} isn't transmitting right now, so I can't tell which plane is flying it."}
            tail = normalize_tail(ac["r"])
        found = lookup.gather(tail, USER_AGENT, lambda t: fetch_aircraft("adsb.fi", t))
        reply = lookup.build_reply(tail, found, airports, commands.is_watching(CONFIG_PATH, topic, key))
        if reply is None:
            return {"message": f"🤷 Couldn't find {tail} in the FAA registry, hexdb.io or live ADS-B. Check the tail number."}
        if kind == "flight":
            reply["title"] = f"🔎 {shown} → {tail}"
            reply["message"] = reply["message"].replace(f"Send {tail} to watch it.", f"Send {shown} to watch this flight.")
        return reply

    def look_up_new(trip, now):
        """Fill in a new trip from AeroDataBox if it needs it. Returns
        (error, note): an error means don't add it; a note replaces the summary."""
        if trip["inbound"]:
            return None, None
        if not cfg["adb_key"]:
            return (trips.USAGE + "\n\nOr add a free AeroDataBox key in ⚙ Settings and I'll look "
                    "the plane up myself."), None
        try:
            adb_refresh(trip, now)
        except trips.AdbError as e:
            return f"❌ {e}.\n\n{trips.USAGE}", None
        if not trip.get("dep_time") and not trip["inbound"]:
            return None, (f"🤷 AeroDataBox has nothing for {trip['flight']} on {trip['date']} yet. "
                          "I'll check again later; you can also add the plane yourself:\n" + trips.USAGE)
        return None, None

    def on_inbound(topic, text):
        """Answer "inbound UA1234 [N38473] [dep 4:30pm] [then UA567 …] [return UA5678 11/21 …]"
        by starting a trip (or every flight of a journey)."""
        now = time.time()
        legs = trips.parse_itinerary(text, now, cfg["time_zone"], airports)
        if isinstance(legs, str):
            return legs
        replies = []
        for n, trip in enumerate(legs):
            trip["topic"] = topic
            if n:
                # A connection or the flight home leaves from where the one before lands.
                trip["dep_airport"] = trip["dep_airport"] or legs[n - 1].get("arr_airport")
                if cfg["adb_key"] and not trip["inbound"]:
                    time.sleep(1.1)  # free tier allows 1 request per second
            err, note = look_up_new(trip, now)
            if err:
                first_back = trip["leg"] == "return" and legs[n - 1]["leg"] != "return"
                return err if not n else trips.about_return(err) if first_back else trips.about_leg(err, "Connection")
            prev = legs[n - 1] if n and legs[n - 1]["leg"] == trip["leg"] else None
            replies.append(note or trips.describe(trip, cfg["time_zone"], prev=prev))
        if len(legs) == 1:
            trips.add(legs[0])
        else:
            trips.add_journey(legs)
        wake.set()  # poll the plane right away
        return "\n\n".join(replies)

    def on_return(topic, text):
        """Answer "return 1 UA5678 11/21 …" by adding the flight home to trip 1."""
        now = time.time()
        mine = trips.for_topic(topic)
        out, rest = trips.select(mine, text, now, cfg["time_zone"])
        if out is None:
            return rest
        legs = trips.journey(out, mine)
        if trips.is_round_trip(legs):
            return (f"🤷 {out['flight']} already has a return flight. Change it with \"change …\" "
                    "(send \"trips\" for the numbers).")
        ret = trips.parse_return(legs[-1], rest, now, cfg["time_zone"], airports)
        if isinstance(ret, str):
            return ret
        ret["topic"] = topic
        err, note = look_up_new(ret, now)
        if err:
            return trips.about_return(err)
        stored = trips.link_return(out, ret)
        if stored is None:
            return f"🤷 {out['flight']} is no longer on your trips."
        if ret["shared_with"]:
            announce_share({t: [ret] for t in ret["shared_with"]}, topic)
        wake.set()
        return f"↩ Added the flight home to {out['flight']}.\n" + (note or trips.describe(ret, cfg["time_zone"]))

    def on_connect(topic, text):
        """Answer "connect 1 UA567 [dep 2:10pm] …" by adding a connecting flight after trip 1."""
        now = time.time()
        mine = trips.for_topic(topic)
        prev, rest = trips.select(mine, text, now, cfg["time_zone"])
        if prev is None:
            return rest
        nxt = trips.connects_to(prev, mine)
        if nxt:
            number = next(i for i, x in enumerate(mine, 1) if x is nxt)
            return (f"🤷 {prev['flight']} already connects to {nxt['flight']}. To add a flight after that one, "
                    f"send \"connect {number} …\".")
        conn = trips.parse_connection(prev, rest, now, cfg["time_zone"], airports)
        if isinstance(conn, str):
            return conn
        conn["topic"] = topic
        err, note = look_up_new(conn, now)
        if err:
            return trips.about_leg(err, "Connection")
        stored = trips.attach(prev, conn, True)
        if stored is None:
            return f"🤷 {prev['flight']} is no longer on your trips."
        if conn["shared_with"]:
            announce_share({t: [conn] for t in conn["shared_with"]}, topic)
        wake.set()
        return (f"🔗 Added {conn['flight']} as your connection after {prev['flight']}.\n"
                + (note or trips.describe(conn, cfg["time_zone"], prev=stored)))

    def adb_refresh(trip, now):
        """Look a trip up on AeroDataBox right away (when added or changed): a
        full check if it's within a day, otherwise just the schedule."""
        soon = (trip.get("dep_time") or trips.date_end(trip)) - now < 36 * 3600
        trips.resolve(trip, cfg["adb_key"], USER_AGENT, full=soon)
        trip["last_check"] = now
        trips.check_level(trip, now)  # checkpoints already behind us don't count

    def on_change(trip, rest):
        now = time.time()
        err, needs_lookup = trips.apply_change(trip, rest, now, cfg["time_zone"], airports)
        if err:
            return err, True
        note = ""
        if needs_lookup and cfg["adb_key"]:
            try:
                adb_refresh(trip, now)
            except trips.AdbError as e:
                note = f"\n(Couldn't check AeroDataBox: {e}.)"
        wake.set()
        return "✏️ Updated.\n" + trips.describe(trip, cfg["time_zone"], intro=False) + note, True

    def on_cancel(legs, rest):
        tz = cfg["time_zone"]
        if len(legs) == 2 and trips.is_round_trip(legs):
            return (f"🗑 Stopped tracking {legs[0]['flight']} on {trips.fmt_day(legs[0], tz)} and the "
                    f"return {legs[1]['flight']} on {trips.fmt_day(legs[1], tz)}."), False
        if len(legs) > 1:
            names = [f"{t['flight']} ({trips.fmt_day(t, tz)})" for t in legs]
            return f"🗑 Stopped tracking {', '.join(names[:-1])} and {names[-1]}.", False
        return f"🗑 Stopped tracking {legs[0]['flight']} on {trips.fmt_day(legs[0], tz)}.", False

    def announce_share(added, owner_topic):
        """Tell newly added people a trip was shared with them: {topic: [legs]},
        one note per person even for both flights of a round trip."""
        names = {w["topic"]: w for w in load_config()["watchers"]}
        owner = names.get(owner_topic, {}).get("name") or owner_topic
        for topic, legs in added.items():
            if topic in names:
                title, message, priority = trips.share_announcement(legs, owner, cfg["time_zone"])
                send({"topic": topic, "title": title, "message": message, "tags": ["robot"], "priority": priority})

    def set_share(topic, selector, topics=None, add=None, drop=None):
        """Share one of `topic`'s trips (and its return, unless the selector
        says "only") with exactly `topics`, or add/drop one person. Returns a reply."""
        names = {w["topic"]: w["name"] for w in load_config()["watchers"]}
        added = {}

        def apply(legs, rest):
            for trip in legs:
                want = topics if topics is not None else \
                    [t for t in (trip.get("shared_with") or []) if t != drop] + ([add] if add else [])
                for t in trips.share_with(trip, [t for t in want if t in names], topic):
                    added.setdefault(t, []).append(dict(trip))
            flights_ = " and ".join(t["flight"] for t in legs)
            who = sorted({names[t] for trip in legs for t in trip["shared_with"]}, key=str.lower)
            verb = "are" if len(legs) > 1 else "is"
            return ("🔗 " + flights_ + (f" {verb} shared with " + ", ".join(who) + "." if who
                                        else f" {verb}n't shared with anyone."), True)

        reply = trips.modify_legs(topic, selector, apply, time.time(), cfg["time_zone"])
        if added:
            announce_share(added, topic)
        return reply

    def on_share(topic, text, adding):
        """Text commands "share 1 Mom & Dad" / "unshare 1 Mom & Dad" (add "only"
        to leave the other flight of a round trip as it is)."""
        mine = trips.for_topic(topic)
        trip, rest = trips.select(mine, text, time.time(), cfg["time_zone"])
        if trip is None:
            return rest
        rest, only = trips.split_only(rest)
        want = rest.strip().lower()
        match = [w for w in load_config()["watchers"]
                 if w["topic"] != topic and want in (w["name"].lower(), w["topic"].lower())]
        if not match:
            others = ", ".join(w["name"] for w in load_config()["watchers"] if w["topic"] != topic) or "nobody yet"
            return f"🤷 No watcher called \"{rest.strip()}\". You can share with: {others}."
        number = next(i for i, x in enumerate(mine, 1) if trips.same_trip(x, trip))
        who = match[0]["topic"]
        return set_share(topic, f"{number}{' only' if only else ''}",
                         add=who if adding else None, drop=None if adding else who)

    def on_command(where, text):
        """A message typed in a watcher's topic (or their Planes topic, which
        acts for the same watcher). The reply goes back where it was typed."""
        hist.add("in", where, text, kind="command", status="received")
        topic = home_topics(cfg).get(where, where)
        verb, ident, _, _ = commands.parse(text)
        if verb in ("inbound", "return", "connect", "trips", "cancel", "change", "share", "unshare"):
            if not any(w["topic"] == topic for w in cfg["watchers"]):
                return
            now = time.time()
            if verb == "inbound":
                reply = on_inbound(topic, ident)
            elif verb == "return":
                reply = on_return(topic, ident)
            elif verb == "connect":
                reply = on_connect(topic, ident)
            elif verb == "trips":
                reply = trips.describe_all(trips.for_topic(topic), cfg["time_zone"])
            elif verb == "change":
                reply = trips.modify(topic, ident, on_change, now, cfg["time_zone"])
            elif verb in ("share", "unshare"):
                reply = on_share(topic, ident, verb == "share")
            else:
                reply = trips.modify_legs(topic, ident, on_cancel, now, cfg["time_zone"])
            log.info("command on %s: %r → %s", topic, text, reply.splitlines()[0])
            send({"topic": where, "message": reply, "tags": ["robot"], "priority": 2})
            return
        if verb == "info":
            if not any(w["topic"] == topic for w in cfg["watchers"]):
                return
            reply = on_info(topic, ident)
            log.info("command on %s: %r → %s", topic, text, reply.get("title") or reply["message"])
            send({"topic": where, "tags": ["robot"], "priority": 2, **reply})
            return
        reply, changed = commands.apply_command(CONFIG_PATH, topic, text, status=load_state())
        if reply and verb == "remove" and trips.cancel(topic, ident):
            reply = (f"🗑 Stopped tracking your {ident} trip." if "isn't on your list" in reply
                     else reply + f"\nAlso stopped tracking your {ident} trip.")
        if reply and verb == "list":
            mine = trips.for_topic(topic)
            if mine:
                reply += "\n\n" + trips.describe_all(mine, cfg["time_zone"])
        log.info("command on %s: %r → %s", topic, text, reply.splitlines()[0] if reply else "ignored")
        if reply:
            send({"topic": where, "message": reply, "tags": ["robot"], "priority": 2})
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

        def record(status):
            hist.add("out", topic, payload.get("message"), payload.get("title"), message_kind(payload), status)
        try:
            publish(ntfy_url, ntfy_token, payload)
            topic_errors.pop(topic, None)
            record("sent")
            return True
        except urllib.error.HTTPError as e:
            if e.code != 429 and e.code < 500:
                topic_errors[topic] = f"NTFY refused topic {topic} (HTTP {e.code})" + (
                    "; " + commands.access_hint(topic) if e.code in (401, 403) else "")
                log.error(topic_errors[topic])
                record("refused")
                return True  # retrying won't help; don't queue
            err = e
        except (urllib.error.URLError, OSError) as e:
            err = e
        log.error("ntfy publish to %s failed: %s (will retry)", topic, err)
        record("retrying")
        return False

    def trip_poll_keys():
        """The trips' planes to include in this cycle's batched poll: inbound
        planes in their last day, and your own flight around departure if shared
        or followed by a connection."""
        topics, now = {w["topic"] for w in cfg["watchers"]}, time.time()
        with trips.TRIPS_LOCK:
            all_trips = trips.load()
        keys = set()
        for t in all_trips:
            if t.get("topic") not in topics or trips.expires_at(t) <= now:
                continue
            if not t.get("landed") and trips.is_live(t, now) and trips.inbound_key(t):
                keys.add(trips.inbound_key(t))
            if trips.own_live(t, now, trips.connects_to(t, all_trips) is not None):
                keys.add(("flight", t["callsign"]))
        return keys

    def track_trips(fixes, errors):
        """Re-check AeroDataBox where due, poll each trip's planes, send trip alerts.

        Two kinds of tracking per trip: the inbound plane (alerts to you), and,
        if you shared the trip, your own flight (departed/landed alerts to the
        people you shared it with). Uses the fixes from this cycle's batched poll
        (trip_poll_keys() put the trips' planes in it).
        """
        by_topic = {w["topic"]: w for w in cfg["watchers"]}
        outgoing = []  # ntfy payloads

        def to_owner(t, title, message, priority, hexcode=None):
            outgoing.append({"topic": t["topic"], "title": title, "message": message, "tags": ["airplane"],
                             "priority": priority,
                             "click": f"https://globe.adsbexchange.com/?icao={hexcode}" if hexcode else None})

        def to_shared(t, title, message, priority):
            for topic in t.get("shared_with") or []:
                if topic in by_topic:
                    outgoing.append({"topic": topic, "title": title, "message": message,
                                     "tags": ["airplane"], "priority": priority})

        with trips.TRIPS_LOCK:
            now = time.time()
            all_trips = trips.load()
            active = [t for t in all_trips if trips.expires_at(t) > now and t.get("topic") in by_topic]
            changed = len(active) != len(all_trips)
            for t in active:
                if t.get("itinerary") and not t.get("dep_airport"):
                    # A connection (or the flight home) leaves from where the flight
                    # before it lands, once AeroDataBox says where.
                    before = trips.prev_leg(t, active)
                    if before and before.get("arr_airport"):
                        t["dep_airport"], changed = before["arr_airport"], True
            for t in active:
                level = trips.check_level(t, now) if cfg["adb_key"] else None
                if not level:
                    continue
                changed = True
                try:
                    notes = trips.resolve(t, cfg["adb_key"], USER_AGENT, full=level == "full")
                    t["last_check"] = now
                    if any(n[0] == "missing" for n in notes):
                        time.sleep(1.1)
                        t["replacement"] = trips.find_replacement(t, cfg["adb_key"], USER_AGENT)
                except trips.AdbError as e:
                    errors.append(str(e))
                    continue
                mine = trips.ordered([x for x in active if x["topic"] == t["topic"]])
                number = next(i for i, x in enumerate(mine, 1) if x is t)
                for m in trips.change_messages(t, notes, cfg["time_zone"], number):
                    to_owner(t, *m)
                owner = by_topic[t["topic"]]["name"]
                for m in trips.share_note_messages(t, notes, owner, cfg["time_zone"]):
                    to_shared(t, *m)
            for t in active:
                nxt = trips.connects_to(t, active)
                for m in trips.connection_notes(t, nxt, cfg["time_zone"]) if nxt else []:
                    changed = True
                    to_owner(t, *m)

            live = [t for t in active if not t.get("landed") and trips.is_live(t, now)]
            own = [t for t in active if trips.own_live(t, now, trips.connects_to(t, active) is not None)]
            for t in live:
                k = trips.inbound_key(t)
                if not k or k[1] not in fixes:
                    continue
                msgs = trips.step(t, fixes[k[1]], now, airports, cfg["time_zone"],
                                  lambda trip, cs: trips.route_destination(trip, cs, USER_AGENT))
                if msgs:
                    changed = True
                    for m in msgs:
                        to_owner(t, *m, hexcode=(fixes.get(k[1]) or {}).get("hex"))

            for t in own:
                if t["callsign"] not in fixes:
                    continue
                fix = fixes[t["callsign"]]
                st, event = observe(t.get("own") or {}, fix, now)
                if fix is not None:
                    st["last_fix"] = {k: fix.get(k) for k in ("lat", "lon", "alt_baro", "gs", "track", "t", "flight", "r", "hex")}
                t["own"], changed = st, True
                ac = fix or {**(st.get("last_fix") or {}), "hex": st.get("hex")}
                kind = trips.own_event(t, event, ac, airports)
                nxt = trips.connects_to(t, active)
                if nxt:
                    for m in trips.connection_step(t, nxt, fix, kind, now, airports, cfg["time_zone"]):
                        to_owner(t, *m, hexcode=st.get("hex"))
                if not kind:
                    continue
                owner = by_topic[t["topic"]]["name"]
                alert = event if kind == "landed" else ("departed" if event == "departed" else "airborne")
                for topic in t.get("shared_with") or []:
                    if topic in by_topic:
                        msg = build_message(cfg, by_topic[topic], t["flight"], f"{owner}'s flight",
                                            ac, alert, airports, "flight")
                        if kind == "landed" and nxt:
                            msg["message"] += f"\nConnecting to {nxt['flight']}" + (
                                f", departs {trips.fmt_time(nxt['dep_time'], cfg['time_zone'])}"
                                if nxt.get("dep_time") else "") + "."
                        outgoing.append(msg)
            if changed:
                trips.save(active)

        for payload in outgoing:
            if not send(payload):
                retry_queue.append({"payload": payload, "until": time.time() + RETRY_SECONDS})
        return False

    def snapshot():
        """Everything the web UI shows. Read-only; secrets are left out.

        Reads config.json fresh rather than using `cfg`, which only refreshes
        at the top of a poll cycle: an edit made a second ago (or during a
        rate-limit backoff) must show up right away."""
        now, st, cur = time.time(), load_state(), load_config()
        names = {w["topic"]: w["name"] for w in cur["watchers"]}
        home = home_topics(cur)
        watchers_out = []
        for w in cur["watchers"]:
            aircraft = []
            for a in w["aircraft"]:
                s_ = st.get(a["key"]) or {}
                fix = s_.get("last_fix") or {}
                aircraft.append({
                    "ident": a["tail"], "kind": a["kind"], "label": a["label"], "expires": a["expires"],
                    "status": s_.get("status") or "unknown", "last_seen": s_.get("last_seen"),
                    # Transponders go quiet once a plane parks, so a stored "ground"
                    # never changes until it flies again; only a recent fix is live.
                    "live": now - (s_.get("last_seen") or 0) <= GAP_SECONDS,
                    "hex": s_.get("hex"), "alt": fix.get("alt_baro"), "gs": fix.get("gs"),
                    "where": airports.place(fix.get("lat"), fix.get("lon"), fix.get("alt_baro") == "ground"),
                    "callsign": (fix.get("flight") or "").strip(), "type": fix.get("t"), "reg": fix.get("r")})
            watchers_out.append({"name": w["name"], "topic": w["topic"], "planes_topic": w["planes_topic"],
                                 "priority": w["priority"],
                                 "notify_landing": w["notify_landing"], "aircraft": aircraft, "following": []})
        trips_out = []
        all_trips = trips.load()
        by_topic = {w["topic"]: w for w in watchers_out}
        for t in all_trips:
            if t.get("topic") not in names:
                continue
            for topic in t.get("shared_with") or []:
                if topic in by_topic:
                    by_topic[topic]["following"].append({
                        "owner": names[t["topic"]], "flight": t["flight"], "date": t["date"],
                        "dep_time": t.get("dep_time"), "dep_airport": t.get("dep_airport"),
                        "departed": bool((t.get("own_sent") or {}).get("departed")),
                        "landed": bool((t.get("own_sent") or {}).get("landed"))})
        for topic, name in names.items():
            mine = trips.ordered([t for t in all_trips if t.get("topic") == topic])
            for n, t in enumerate(mine, 1):
                before, after = trips.connects_from(t, mine), trips.connects_to(t, mine)
                trips_out.append({**{k: t.get(k) for k in (
                    "flight", "date", "dep_time", "dep_airport", "arr_airport", "inbound", "source",
                    "departed", "landed", "eta_sent", "tight", "late", "missing", "replacement",
                    "last_check", "plane_locked", "itinerary", "leg", "seq", "arr_time", "stops", "route", "get_off")},
                    "connect_from": before["flight"] if before else None,
                    "connect_at": before.get("arr_airport") if before else None,
                    "connect_min": trips.connection_minutes(before, t) if before else None,
                    "connect_to": after["flight"] if after else None,
                    "topic": topic, "watcher": name, "number": n, "live": trips.is_live(t, now),
                    "dep_tz": trips.airport_zone(t.get("dep_airport"), airports, cur["time_zone"]),
                    "shared_with": [x for x in (t.get("shared_with") or []) if x in names],
                    "shared_names": [names[x] for x in (t.get("shared_with") or []) if x in names],
                    "next_check": trips.next_check_time(t, now) if cur["adb_key"] else None})
        trips_out.sort(key=lambda t: t["dep_time"] or 0)
        return {
            "now": now, "version": VERSION, "time_zone": cur["time_zone"], "health": health.get(),
            "settings": {"data_source": cur["data_source"], "poll_seconds": cur["poll_seconds"],
                         "map_links": cur["map_links"], "text_commands": cur["text_commands"],
                         "aerodatabox": bool(cur["adb_key"]), "ntfy": bool(resolve_ntfy(cur)[0]),
                         "ntfy_server": cur["ntfy_server"], "phone_url": resolve_ntfy(cur)[2],
                         "ntfy_custom_url": cur["ntfy_custom_url"], "ntfy_token_set": bool(cur["ntfy_token"]),
                         "ntfy_phone_mode": cur["ntfy_phone_mode"], "local_ntfy": bool(os.environ.get("NTFY_URL")),
                         "time_zone": cur["time_zone"], "web_password": cur["web_password"],
                         "time_zones": [[k, v] for k, v in edits.TIME_ZONES.items()],
                         "public_url": os.environ.get("TAILWATCHER_PUBLIC_URL", "").strip(),
                         "platform": PLATFORM,
                         "listening": sorted(names[k] for k in names if k not in listen_errors)},
            "watchers": watchers_out, "trips": trips_out,
            "invites": [{k: i.get(k) for k in ("token", "topic", "from", "expires", "kind")}
                        for i in invites.active(now) if i.get("topic") in names],
            "history": [dict(e, watcher=names.get(home.get(e["topic"])) or e["topic"] or "Settings")
                        for e in hist.recent(150)],
        }

    def trip_text(data, number=None, prefix=""):
        """Turn the Web UI's trip form into the text the "inbound"/"change"
        commands read. prefix "ret_" reads the form's return-flight fields."""
        val = lambda k: str(data.get(prefix + k) or "").strip()  # noqa: E731
        parts = [str(number)] if number is not None else [val("flight")]
        if number is not None and val("flight"):
            parts.append(val("flight"))
        if val("plane"):
            parts += ["plane", val("plane")]
        if val("date"):
            parts.append(val("date"))
        if val("time"):
            parts += ["dep", val("time")]
        if val("airport"):
            parts += ["from", val("airport")]
        if val("to"):
            parts += ["to", val("to")]
        return " ".join(p for p in parts if p)

    def ntfy_post(path, data):
        """Settings panel: save settings, set up this server's NTFY, make a person's login."""
        local = os.environ.get("NTFY_URL", "").strip()
        try:
            if path == "/api/settings":
                msg = edits.save_settings(CONFIG_PATH, data)
                hist.add("in", "", "Settings changed on the web", kind="web", status="received")
                wake.set()
                return 200, {"ok": True, "message": msg}
            if path == "/api/ntfy-setup":
                phones = "login" if data.get("phones") == "login" else "open"
                token, steps = ntfy_admin.setup(local, str(data.get("adminPassword") or ""), phones)
                logins = []
                if phones == "login":
                    for w in load_config()["watchers"]:
                        user, pw = ntfy_admin.create_login(local, str(data.get("adminPassword")), w["name"],
                                                           [w["topic"], w["planes_topic"]])
                        logins.append({"name": w["name"], "username": user, "password": pw})
                    if logins:
                        steps.append(f"Made NTFY logins for {', '.join(l['name'] for l in logins)}")
                with commands.CONFIG_LOCK:
                    raw = commands.read_raw(CONFIG_PATH)
                    raw.update(ntfyServer="local", ntfyToken=token, ntfyPhoneMode=phones)
                    commands.write_raw(CONFIG_PATH, raw)
                hist.add("in", "", "Set up this server's NTFY from the web", kind="web", status="received")
                wake.set()
                return 200, {"ok": True, "message": "NTFY is set up.", "steps": steps, "logins": logins}
            if path == "/api/ntfy-login":
                w = next((x for x in load_config()["watchers"] if x["topic"] == data.get("topic")), None)
                if w is None:
                    return 404, {"ok": False, "message": "That watcher no longer exists."}
                user, pw = ntfy_admin.create_login(local, str(data.get("adminPassword") or ""), w["name"],
                                                   [w["topic"], w["planes_topic"]])
                return 200, {"ok": True, "message": f"Made an NTFY login for {w['name']}.",
                             "logins": [{"name": w["name"], "username": user, "password": pw}]}
        except (edits.EditError, ntfy_admin.SetupError) as e:
            return 400, {"ok": False, "message": str(e)}
        return 404, {"ok": False, "message": "Not found."}

    def public_page(token):
        """The invite page at /join/<token> (no dashboard password)."""
        inv = invites.find(token)
        cur = load_config()
        w = next((x for x in cur["watchers"] if inv and x["topic"] == inv["topic"]), None)
        if inv is None or w is None:
            return 404, invites.expired_page()
        return 200, invites.join_page(inv, w["name"], resolve_ntfy(cur)[2], cur["ntfy_server"],
                                      cur["ntfy_phone_mode"], commands.zone(cur["time_zone"]))

    def invite_post(data):
        names = {w["topic"]: w["name"] for w in load_config()["watchers"]}
        if data.get("op") == "create":
            topic = str(data.get("topic") or "")
            if topic not in names:
                return 404, {"ok": False, "message": "That watcher no longer exists."}
            try:
                inv = invites.create(topic, str(data.get("from") or ""), int(data.get("days") or invites.DEFAULT_DAYS))
            except (TypeError, ValueError):
                return 400, {"ok": False, "message": "Bad request."}
            hist.add("in", topic, f"Invite link created for {names[topic]}", kind="web", status="received")
            return 200, {"ok": True, "message": f"Invite for {names[topic]} ready.", "path": f"join/{inv['token']}",
                         "expires": inv["expires"]}
        if data.get("op") == "revoke":
            n = invites.revoke(str(data.get("token") or ""))
            return 200, {"ok": True, "message": "Invite cancelled." if n else "That invite was already gone."}
        return 400, {"ok": False, "message": "Unknown action."}

    def handle_post(path, data):
        """Edits from the Web UI. Returns (http_status, {"ok", "message"})."""
        if path in ("/api/settings", "/api/ntfy-setup", "/api/ntfy-login"):
            return ntfy_post(path, data)
        if path == "/api/invite":
            return invite_post(data)
        if path == "/api/import":  # read only: it pre-fills the Add trip form, nothing is saved
            found = itinerary.preview(str(data.get("text") or ""), str(data.get("name") or ""),
                                      time.time(), load_config()["time_zone"], airports)
            return (200 if found["ok"] else 400), found
        topic = str(data.get("topic") or "")
        op = data.get("op")
        names = {w["topic"]: w["name"] for w in load_config()["watchers"]}  # fresh: see snapshot()
        try:
            if path == "/api/watcher":
                if op == "save":
                    msg = edits.save_watcher(CONFIG_PATH, data.get("original") or None, data.get("name"),
                                             data.get("topic"), data.get("priority") or "default",
                                             bool(data.get("notifyLanding")),
                                             new_topic_requested=bool(data.get("newTopic")),
                                             planes=data.get("planes"))
                elif op == "remove":
                    msg = edits.remove_watcher(CONFIG_PATH, topic)
                else:
                    return 400, {"ok": False, "message": "Unknown action."}
            elif path == "/api/aircraft":
                if op == "save":
                    msg = edits.save_aircraft(CONFIG_PATH, topic, data.get("ident"), data.get("label"),
                                              data.get("expiresDays"), data.get("original"))
                elif op == "remove":
                    msg = edits.remove_aircraft(CONFIG_PATH, topic, str(data.get("ident") or ""))
                else:
                    return 400, {"ok": False, "message": "Unknown action."}
            elif path == "/api/trip":
                if topic not in names:
                    return 404, {"ok": False, "message": "That watcher no longer exists."}
                now = time.time()
                share = data.get("share")
                if share is not None and not isinstance(share, list):
                    return 400, {"ok": False, "message": "Bad request."}
                has_return = bool(str(data.get("ret_flight") or "").strip())
                has = lambda prefix: bool(str(data.get(prefix + "flight") or "").strip())  # noqa: E731
                conns = lambda base: [p for p in (trips.form_prefix(base, n) for n in range(trips.MAX_LEGS - 1))  # noqa: E731
                                      if has(p)]
                if conns("ret_") and not has_return and op in ("add", "change"):
                    return 400, {"ok": False, "message": "Fill in the return flight before its connections."}
                if op == "add":
                    text = trip_text(data) + "".join(" then " + trip_text(data, prefix=p) for p in conns(""))
                    if has_return:
                        text += " return " + trip_text(data, prefix="ret_") \
                            + "".join(" then " + trip_text(data, prefix=p) for p in conns("ret_"))
                    msg = on_inbound(topic, text)
                    if share and not msg.startswith(("❌", "🤔", "Tell me your flight")):
                        flight = flights.parse_flight(str(data.get("flight") or ""))
                        mine = trips.for_topic(topic)
                        nums = [i for i, t in enumerate(mine, 1) if flight and t["flight"] == flight[0]
                                and (not data.get("date") or t["date"] == data["date"])]
                        if nums:
                            msg += "\n" + set_share(topic, str(nums[-1]), [str(x) for x in share])
                elif op == "change":
                    number = int(data.get("number") or 0)
                    msg = ""
                    if has_return:  # first: adding it never moves the outbound's number
                        msg = on_return(topic, f"{number} {trip_text(data, prefix='ret_')}")
                        if msg.startswith(("❌", "🤔", "🤷")):
                            return 400, {"ok": False, "message": msg}
                    # Connections go in each after the last: the return's first (they come
                    # after this flight, so never move its number), then this flight's.
                    chains = [("", number)]
                    if has_return and conns("ret_"):
                        mine = trips.for_topic(topic)
                        legs = trips.journey(mine[number - 1], mine) if 0 < number <= len(mine) else []
                        ret = next((x for x in reversed(legs) if x.get("leg") == "return"), None)
                        if ret is not None:
                            chains.insert(0, ("ret_", next(i for i, x in enumerate(mine, 1) if x is ret)))
                    for base, after in chains:
                        for p in conns(base):
                            added = on_connect(topic, f"{after} {trip_text(data, prefix=p)}")
                            if added.startswith(("❌", "🤔", "🤷")):
                                return 400, {"ok": False, "message": f"{added}\n(The flights before it were added.)" if msg else added}
                            msg = f"{msg}\n{added}".strip()
                            mine = trips.for_topic(topic)
                            nxt = trips.connects_to(mine[after - 1], mine)
                            after = next(i for i, x in enumerate(mine, 1) if x is nxt) if nxt else after
                    edits_text = trip_text(data, number)
                    if edits_text != str(number):
                        changed = trips.modify(topic, edits_text, on_change, now, cfg["time_zone"])
                        if msg and changed.startswith(("❌", "🤔", "🤷", "Which trip", "You have ")):
                            return 400, {"ok": False, "message": f"{changed}\n(The new flight was added.)"}
                        msg = f"{msg}\n{changed}".strip()
                    if share is not None and not msg.startswith(("🤔", "🤷", "❌")):
                        shared = set_share(topic, str(number), [str(x) for x in share])
                        msg = f"{msg}\n{shared}".strip() if msg else shared
                elif op == "cancel":
                    selector = f"{int(data.get('number') or 0)}{' only' if data.get('only') else ''}"
                    msg = trips.modify_legs(topic, selector, on_cancel, now, cfg["time_zone"])
                else:
                    return 400, {"ok": False, "message": "Unknown action."}
            else:
                return 404, {"ok": False, "message": "Not found."}
        except edits.EditError as e:
            return 400, {"ok": False, "message": str(e)}
        except (TypeError, ValueError):
            return 400, {"ok": False, "message": "Bad request."}
        failed = (msg.startswith(("❌", "🤔", "🤷", "Which trip", "Tell me your flight", "You have "))
                  and not msg.startswith("🤷 AeroDataBox has nothing"))  # that one still saves the trip
        if not failed:
            if path == "/api/watcher" and not topic:  # a new watcher's topic was just generated
                topic = next((w["topic"] for w in load_config()["watchers"]
                              if w["name"] == str(data.get("name") or "").strip()), "")
            hist.add("in", topic or data.get("topic") or "", msg.splitlines()[0], kind="web", status="received")
            wake.set()
        log.info("web edit %s %s → %s", path, op, msg.splitlines()[0])
        return (400 if failed else 200), {"ok": not failed, "message": msg}

    web.serve(HEALTH_PORT, health, snapshot, require_password=web_password_required, post=handle_post,
              public=public_page)

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
                where = next((planes_topic(w) for w in cfg["watchers"] if w["topic"] == topic), topic)
                send({"topic": where, "message": f"⌛ Stopped watching {ident} (expired)",
                      "tags": ["robot"], "priority": 2})

        mtime = config_mtime()
        if mtime != cfg_mtime:
            # Configure (StartOS) or a text command changed the file: apply it
            # without restarting.
            cfg_mtime, cfg = mtime, load_config()
            ntfy_url, ntfy_token, phone_url = resolve_ntfy(cfg)
            subs = subscriptions(cfg)
            for w in cfg["watchers"]:
                log.info("watcher %s → topic %s: %s", w["name"], w["topic"],
                         ", ".join(a["tail"] if a["kind"] == "tail" else f"{a['tail']} ({a['key']})"
                                   for a in w["aircraft"]) or "(none yet)")
            log.info("polling %d aircraft via %s every %ss, ntfy %s, text commands %s",
                     len(subs), cfg["data_source"], cfg["poll_seconds"], ntfy_url,
                     "on" if cfg["text_commands"] else "off")
            topics = list(home_topics(cfg)) if cfg["text_commands"] and ntfy_url else []
            listeners.sync(topics, ntfy_url, ntfy_token)

        if not cfg["watchers"] or not ntfy_url:
            problems = [] if cfg["watchers"] else ["no watchers"]
            if not ntfy_url:
                problems.append("NTFY not reachable")
            health.set(False, "Not configured: " + ", ".join(problems) + ". Set it up in the Web UI.")
            wake.wait(10)
            wake.clear()
            continue

        started = time.time()
        errors, airborne, rate_limited = [], [], False
        fixes = {}  # key -> this cycle's ADS-B record (None = not seen)

        still_pending = []
        for item in retry_queue:
            if started > item["until"]:
                log.warning("giving up on alert to %s: %s", item["payload"]["topic"], item["payload"]["title"])
            elif not send(item["payload"]):
                still_pending.append(item)
        retry_queue = still_pending
        if retry_queue:
            errors.append(f"ntfy: {len(retry_queue)} alert(s) waiting to retry")

        wanted = {(followers[0][1]["kind"], key) for key, followers in subs.items()} | trip_poll_keys()
        polled, poll_error, rate_limited = poll_all(cfg["data_source"], wanted) if wanted else ({}, None, False)
        if poll_error:
            errors.append(poll_error)
        fixes.update(polled)

        for key, followers in subs.items():
            kind, shown = followers[0][1]["kind"], followers[0][1]["tail"]
            if key not in fixes:
                continue  # the poll failed this cycle
            ac = fixes[key]
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
                    payload["topic"] = planes_topic(watcher)
                    if not send(payload):
                        retry_queue.append({"payload": payload, "until": time.time() + RETRY_SECONDS})
            state[key] = st
        if fixes or not wanted:
            track_trips(fixes, errors)
        save_state({**state, "_retry": retry_queue})
        hist.save()

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
            health.set(True, "No aircraft yet. Text a tail or flight number to a watcher's topic, or add one in the Web UI.")
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

def send_test(cfg):
    """A sample takeoff alert to every watcher's topic, like StartOS's
    "Send Test Notification" action. Returns [(watcher name, topic, result)]."""
    url, token, _ = resolve_ntfy(cfg)
    if not url:
        return [("", "", "no notification server: set NTFY_URL, or pick another server in Settings")]
    link = "https://globe.adsbexchange.com/?icao=a835af"
    out = []
    for w in cfg["watchers"]:
        try:
            publish(url, token, {
                "topic": w["topic"], "title": f"TailWatcher test for {w['name']}: N628TS departed",
                "message": "at KFDK – Frederick Municipal Airport\n1,800 ft · 105 kt · hdg 270°\nThis is a test alert.",
                "tags": ["airplane", "test_tube"], "click": link,
                "actions": [{"action": "view", "label": "ADS-B Exchange", "url": link}]})
            out.append((w["name"], w["topic"], "✓ sent"))
        except urllib.error.HTTPError as e:
            hint = (": the token has no access to this topic; " + commands.access_hint(w["topic"])
                    if e.code in (401, 403) else "")
            out.append((w["name"], w["topic"], f"✗ refused (HTTP {e.code}){hint}"))
        except (urllib.error.URLError, OSError) as e:
            out.append((w["name"], w["topic"], f"✗ could not reach {url}: {e}"))
    return out


def cli(args):
    """`python /app/tailwatcher.py password|reset-password|test`, for installs
    without StartOS's Actions menu (docker exec tailwatcher ...)."""
    if args == ["password"]:
        print(web.read_password() or "No password yet: start TailWatcher once to make one.")
    elif args == ["reset-password"]:
        print(web.new_password(), "(the old password stopped working; any username)")
    elif args == ["test"]:
        cfg = load_config()
        if not cfg["watchers"]:
            print("Add a watcher in the Web UI first.")
            return 1
        results = send_test(cfg)
        for name, topic, result in results:
            print(f"{name} → {topic}: {result}")
        return 1 if any(not r.startswith("✓") for _, _, r in results) else 0
    else:
        print("Usage: tailwatcher.py [password | reset-password | test]")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(cli(sys.argv[1:]) if len(sys.argv) > 1 else run())
