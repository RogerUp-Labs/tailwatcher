"""Inbound-plane tracking ("where's my plane?") for trips.

A trip is your flight ("UA1234" on a date) plus the aircraft flying the leg
into your departure airport before it. TailWatcher follows that aircraft on
ADS-B and tells you when it takes off toward you, when its arrival slips
close to your departure, and when it lands.

Two ways to say which plane it is:
- Manual: "inbound UA1234 N38473 dep 4:30pm" (tail or inbound flight number
  from the airline app's "Where's my plane?" screen).
- Automatic: with an AeroDataBox key (RapidAPI, free tier) in Configure,
  "inbound UA1234" looks up the assigned plane, its inbound leg and your
  departure time, and re-checks before departure in case the plane changes.

Trips live in trips.json (not config.json, so the Configure form never
touches them) and are removed a few hours after departure.
"""

import datetime
import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import commands
import flights
from lookup import haversine_nm

log = logging.getLogger("tailwatcher")

TRIPS_PATH = os.environ.get("TW_TRIPS", "/data/trips.json")
TRIPS_LOCK = threading.Lock()

ADB_HOST = "aerodatabox.p.rapidapi.com"
ADSBDB_ROUTE_URL = "https://api.adsbdb.com/v0/callsign/{cs}"

# With an AeroDataBox key, re-check the assignment this many hours before
# departure (plus once when the trip is added). ~2 calls each.
CHECKPOINT_HOURS = [24, 6, 2, 0.75]
APPROACH_MIN = 8        # added to distance/groundspeed for the approach and landing
TIGHT_MIN = 45          # warn when the inbound plane lands this close to your departure
LATE_MIN = 20           # ...and again at this, as a likely delay
ETA_SHIFT_MIN = 15      # re-announce the arrival estimate when it moves this much
CLIMB_ASSUMED_KT = 420  # see estimate_arrival
LANDED_NM = 5           # on the ground within this of your airport = arrived
KEEP_AFTER_DEP_H = 3    # drop a trip this long after its departure
KEEP_UNDATED_H = 36     # ...or this long after it was added, with no departure time

TIME_RE = re.compile(r"^(\d{1,2})(?::(\d{2}))?(am|pm|a|p)?$", re.I)
DATE_RE = re.compile(r"^(\d{1,2})/(\d{1,2})$")
ADB_TIME_RE = re.compile(r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})(?::\d{2})?Z")

USAGE = (
    "Tell me your flight and the plane flying in for it, e.g.\n"
    "inbound UA1234 N38473 dep 4:30pm\n"
    "(the plane is in your airline app under \"Where's my plane?\"; a flight number like UA567 works too). "
    "Add \"tomorrow\" or a date like 10/20, and \"from IAD\" if it isn't obvious."
)


# --------------------------------------------------------------- parsing


def parse_inbound(text, now, tz_name, airports):
    """Parse "UA1234 [N38473|UA567] [dep] [4:30pm] [tomorrow|10/20] [from IAD]".

    Returns a new trip dict, or an error string to send back.
    """
    tz = commands.zone(tz_name)
    words = commands.merge_flight_words((text or "").split(), 0)
    if not words:
        return USAGE
    flight = flights.parse_flight(words[0])
    if not flight:
        return f"❌ \"{words[0]}\" doesn't look like a flight number.\n\n{USAGE}"

    today = datetime.datetime.fromtimestamp(now, tz).date()
    day, clock, inbound, dep_airport, explicit_day = today, None, None, None, False
    i = 1
    while i < len(words):
        w, low = words[i], words[i].lower()
        nxt = words[i + 1] if i + 1 < len(words) else ""
        if low in ("dep", "departs", "departing", "leaves", "at", "on"):
            i += 1
            continue
        if low == "from" and nxt:
            dep_airport, i = resolve_airport(nxt, airports), i + 2
            if not dep_airport:
                return f"❌ I don't know an airport \"{nxt}\"."
            continue
        if low in ("today", "tomorrow"):
            day, explicit_day = today + datetime.timedelta(days=low == "tomorrow"), True
            i += 1
            continue
        m = DATE_RE.match(w)
        if m:
            day, explicit_day = month_day(today, int(m.group(1)), int(m.group(2))), True
            if day is None:
                return f"❌ \"{w}\" isn't a date."
            i += 1
            continue
        if nxt.lower() in ("am", "pm") and TIME_RE.match(w + nxt):
            w, i = w + nxt, i + 1
        m = TIME_RE.match(w)
        if m and (m.group(2) or m.group(3)):  # "4:30", "4pm"; a bare "567" is not a time
            clock = to_24h(int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower())
            if clock is None:
                return f"❌ \"{w}\" isn't a time."
            i += 1
            continue
        merged = commands.merge_flight_words(words, i)[i]
        entry = commands.classify(merged)
        if not entry or inbound:
            return f"🤔 I didn't understand \"{w}\".\n\n{USAGE}"
        kind, shown, key = entry
        if kind == "tail" and not commands.looks_like_tail(merged):
            return f"🤔 I didn't understand \"{w}\".\n\n{USAGE}"  # "banana" isn't a tail
        inbound = {"tail": shown if kind == "tail" else None,
                   "flight": shown if kind == "flight" else None,
                   "callsign": key if kind == "flight" else None}
        if merged != w:
            i += 1  # "UA 567" took two words
        i += 1

    dep_time = None
    if clock:
        local = datetime.datetime.combine(day, datetime.time(*clock), tz)
        if not explicit_day and local.timestamp() < now - 3600:
            local += datetime.timedelta(days=1)  # "dep 9am" said in the evening means tomorrow
            day = local.date()
        dep_time = local.timestamp()

    return new_trip(flight, day.isoformat(), dep_time, dep_airport, inbound, now)


def new_trip(flight, date, dep_time, dep_airport, inbound, now):
    return {
        "flight": flight[0], "callsign": flight[1], "date": date,
        "dep_time": dep_time, "dep_airport": dep_airport,
        "inbound": inbound, "source": "manual" if inbound else "aerodatabox",
        "checkpoints": list(CHECKPOINT_HOURS), "last_check": None,
        "created": now,
        # progress
        "departed": False, "landed": False, "eta_sent": None,
        "tight": False, "late": False, "leg_note": None, "near_low": None, "routes": {},
    }


def to_24h(h, m, ampm):
    if m > 59:
        return None
    if ampm in ("pm", "p") and h < 12:
        h += 12
    elif ampm in ("am", "a") and h == 12:
        h = 0
    return (h, m) if h < 24 else None


def month_day(today, month, day):
    try:
        d = datetime.date(today.year, month, day)
    except ValueError:
        return None
    if (today - d).days > 30:  # "1/5" said in December means next January
        d = d.replace(year=today.year + 1)
    return d


def resolve_airport(code, airports):
    """"IAD" or "KIAD" -> "KIAD". Three letters are an IATA code first: some
    small airport's own ident is often the same three letters ("LAS")."""
    code = code.upper().strip(",.")
    if len(code) == 3 and code in airports.iata:
        return airports.iata[code]
    return code if code in airports.coords else None


def date_end(trip):
    """Unix time at the end of the trip's date (UTC-12, the last place it's still that day)."""
    d = datetime.date.fromisoformat(trip["date"]) + datetime.timedelta(days=1)
    return datetime.datetime.combine(d, datetime.time(12), datetime.timezone.utc).timestamp()


def expires_at(trip):
    """Drop a trip a few hours after departure; with no departure time, after
    its date has ended everywhere (a trip added a month ahead stays a month)."""
    if trip.get("dep_time"):
        return trip["dep_time"] + KEEP_AFTER_DEP_H * 3600
    return max(trip["created"] + KEEP_UNDATED_H * 3600, date_end(trip) + KEEP_AFTER_DEP_H * 3600)


# --------------------------------------------------------------- storage


def load(path=None):
    try:
        with open(path or TRIPS_PATH) as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def save(trips, path=None):
    path = path or TRIPS_PATH
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(trips, f, indent=1)
    os.replace(tmp, path)


def same_trip(a, b):
    return a["topic"] == b["topic"] and a["flight"] == b["flight"] and a["date"] == b["date"]


def add(trip, path=None):
    """Store a trip, replacing an earlier one for the same flight and date."""
    with TRIPS_LOCK:
        trips = [t for t in load(path) if not same_trip(t, trip)]
        trips.append(trip)
        save(trips, path)


def cancel(topic, ident, path=None):
    """Remove the watcher's trips for a flight number. Returns how many."""
    flight = flights.parse_flight(ident or "")
    if not flight:
        return 0
    with TRIPS_LOCK:
        trips = load(path)
        keep = [t for t in trips if not (t["topic"] == topic and t["flight"] == flight[0])]
        if len(keep) != len(trips):
            save(keep, path)
        return len(trips) - len(keep)


def for_topic(topic, path=None):
    return sorted((t for t in load(path) if t["topic"] == topic),
                  key=lambda t: t.get("dep_time") or t["created"])


# ------------------------------------------------------------ formatting


def fmt_time(ts, tz_name):
    t = datetime.datetime.fromtimestamp(ts, commands.zone(tz_name))
    return t.strftime("%I:%M%p").lstrip("0").lower()


def fmt_day(trip, tz_name):
    d = datetime.date.fromisoformat(trip["date"])
    return d.strftime("%a %b ") + str(d.day)


def plane_name(trip):
    inb = trip.get("inbound") or {}
    if inb.get("tail") and inb.get("flight"):
        return f"{inb['tail']} ({inb['flight']})"
    return inb.get("tail") or inb.get("flight") or "your plane"


def describe(trip, tz_name, intro=True):
    """The trip summary sent when it's added, and by "trips"."""
    inb = trip.get("inbound") or {}
    head = f"🧳 {trip['flight']} · {fmt_day(trip, tz_name)}"
    if trip.get("dep_time"):
        head += f", departs {fmt_time(trip['dep_time'], tz_name)}"
    if trip.get("dep_airport"):
        head += f" from {trip['dep_airport']}"
    lines = [head]
    if inb.get("tail") or inb.get("flight"):
        bits = [f"Your plane: {inb.get('tail') or inb.get('flight')}"]
        if inb.get("tail") and inb.get("flight"):
            bits.append(f"arriving as {inb['flight']}")
        if inb.get("origin"):
            bits.append(f"from {inb['origin']}")
        line = ", ".join(bits)
        if inb.get("arr_time"):
            line += f" (due {fmt_time(inb['arr_time'], tz_name)})"
        lines.append(line)
        if trip.get("landed"):
            lines.append("Status: 🛬 at the airport")
        elif trip.get("departed"):
            lines.append("Status: ✈️ on its way" + (f", due {fmt_time(trip['eta_sent'], tz_name)}"
                                                    if trip.get("eta_sent") else ""))
        elif intro:
            lines.append("I'll tell you when it takes off toward you, if it's running close to your "
                         "departure, and when it lands.")
    else:
        lines.append("No plane assigned yet. I'll check again closer to departure "
                     "(about 24h, 6h and 2h before).")
    if not trip.get("dep_time") and intro:
        lines.append("Add your departure time (\"dep 4:30pm\") to get a warning if it's running late.")
    return "\n".join(lines)


def describe_all(trips, tz_name):
    if not trips:
        return "No trips. Send \"inbound UA1234 N38473 dep 4:30pm\" to track the plane flying in for your flight."
    return "\n\n".join(describe(t, tz_name, intro=False) for t in trips)


# ------------------------------------------------------------ AeroDataBox


class AdbError(Exception):
    pass


def adb_get(key, path, params, ua, timeout=20):
    url = f"https://{ADB_HOST}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={
        "X-RapidAPI-Key": key, "X-RapidAPI-Host": ADB_HOST, "User-Agent": ua})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            remaining = r.headers.get("x-ratelimit-requests-remaining")
            if remaining is not None:
                log.info("AeroDataBox: %s requests left this month", remaining)
            body = r.read()
            return json.loads(body) if r.status != 204 and body.strip() else []
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise AdbError("AeroDataBox rejected the API key (check it in Configure)") from e
        if e.code == 429:
            raise AdbError("AeroDataBox quota or rate limit reached") from e
        raise AdbError(f"AeroDataBox error HTTP {e.code}") from e
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise AdbError(f"AeroDataBox unreachable: {e}") from e


def adb_time(movement, *fields):
    """Unix time of the first of `fields` (e.g. revisedTime) present in a movement."""
    for f in fields:
        m = ADB_TIME_RE.search(((movement or {}).get(f) or {}).get("utc") or "")
        if m:
            return datetime.datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}+00:00").timestamp()
    return None


def pick_leg(legs, dep_airport):
    """Your leg of a flight number: the one leaving dep_airport, else the first."""
    legs = [l for l in legs if not l.get("codeshareStatus") == "IsCodeshared"] or legs
    if dep_airport:
        mine = [l for l in legs if ((l.get("departure") or {}).get("airport") or {}).get("icao") == dep_airport]
        if mine:
            return mine[0]
    legs = sorted(legs, key=lambda l: adb_time(l.get("departure"), "scheduledTime") or 0)
    return legs[0] if legs else None


def pick_inbound(plane_legs, dep_airport, dep_time, flight):
    """The plane's leg into dep_airport that lands before your departure."""
    best, best_arr = None, None
    for l in plane_legs:
        if commands.normalize_tail(l.get("number") or "") == commands.normalize_tail(flight):
            continue
        arr = l.get("arrival") or {}
        if (arr.get("airport") or {}).get("icao") != dep_airport:
            continue
        t = adb_time(arr, "scheduledTime")
        if t is None or (dep_time and t > dep_time + 3600):
            continue
        if best_arr is None or t > best_arr:
            best, best_arr = l, t
    return best


def resolve(trip, key, ua, sleep=time.sleep, get=adb_get):
    """Fill in the trip from AeroDataBox. Returns a list of change notes.

    Raises AdbError if AeroDataBox can't be used; leaves the trip unchanged
    when it has no data for the flight yet.
    """
    notes = []
    common = {"withAircraftImage": "false", "withLocation": "false"}
    legs = get(key, f"/flights/number/{urllib.parse.quote(trip['flight'])}/{trip['date']}",
               {**common, "dateLocalRole": "Departure"}, ua)
    leg = pick_leg(legs if isinstance(legs, list) else [], trip.get("dep_airport"))
    if not leg:
        return notes
    dep = leg.get("departure") or {}
    trip["dep_airport"] = (dep.get("airport") or {}).get("icao") or trip.get("dep_airport")
    new_dep = adb_time(dep, "revisedTime", "predictedTime", "scheduledTime")
    if new_dep:
        old = trip.get("dep_time")
        if old and abs(new_dep - old) >= 10 * 60:
            notes.append(("dep_change", old, new_dep))
        trip["dep_time"] = new_dep
    reg = commands.normalize_tail((leg.get("aircraft") or {}).get("reg") or "")
    if not reg:
        return notes
    old_tail = (trip.get("inbound") or {}).get("tail")
    sleep(1.1)  # free tier allows 1 request per second
    plane_legs = get(key, f"/flights/reg/{reg}/{trip['date']}", {**common, "dateLocalRole": "Both"}, ua)
    inbound = pick_inbound(plane_legs if isinstance(plane_legs, list) else [],
                           trip["dep_airport"], trip.get("dep_time"), trip["flight"])
    info = {"tail": reg, "flight": None, "callsign": None, "origin": None, "arr_time": None}
    if inbound:
        number = flights.parse_flight(inbound.get("number") or "")
        info.update(
            flight=number[0] if number else (inbound.get("number") or None),
            callsign=flights.compact(inbound.get("callSign") or "") or (number[1] if number else None),
            origin=((inbound.get("departure") or {}).get("airport") or {}).get("icao"),
            arr_time=adb_time(inbound.get("arrival"), "revisedTime", "predictedTime", "scheduledTime"))
    if old_tail and old_tail != reg:
        notes.append(("plane_change", old_tail, reg))
        trip.update(departed=False, landed=False, eta_sent=None, tight=False, late=False, leg_note=None)
    trip["inbound"] = info
    return notes


def due_for_check(trip, now):
    """Should this AeroDataBox trip be re-checked now? Consumes passed checkpoints."""
    if trip.get("source") != "aerodatabox" or trip.get("landed"):
        return False
    if not trip.get("dep_time"):
        # No schedule yet: once a day while the trip is more than 2 days off,
        # every 6 hours after that.
        far = date_end(trip) - now > 3 * 86400
        interval = 24 * 3600 if far else 6 * 3600
        return not trip.get("last_check") or now - trip["last_check"] > interval
    passed = [h for h in trip.get("checkpoints") or [] if now >= trip["dep_time"] - h * 3600]
    if not passed:
        return False
    trip["checkpoints"] = [h for h in trip["checkpoints"] if h not in passed]
    return True


def change_messages(trip, notes, tz_name):
    out = []
    for kind, old, new in notes:
        if kind == "plane_change":
            out.append(("🔁 Plane change", f"{trip['flight']} is now flying {new} (was {old}).\n"
                        + describe(trip, tz_name, intro=False), 4))
        elif kind == "dep_change":
            later = "later" if new > old else "earlier"
            out.append((f"🕓 {trip['flight']} time change",
                        f"Now departs {fmt_time(new, tz_name)} ({later} than {fmt_time(old, tz_name)}).", 4))
    return out


# ------------------------------------------------------------ live tracking


def inbound_key(trip):
    """(kind, key) to poll on ADS-B for the trip's inbound plane, or None."""
    inb = trip.get("inbound") or {}
    if inb.get("tail"):
        return "tail", inb["tail"]
    if inb.get("callsign"):
        return "flight", inb["callsign"]
    return None


def route_destination(trip, callsign, ua):
    """Destination ICAO of a callsign's usual route (adsbdb.com), cached on the trip."""
    routes = trip.setdefault("routes", {})
    if callsign not in routes:
        try:
            req = urllib.request.Request(ADSBDB_ROUTE_URL.format(cs=urllib.parse.quote(callsign)),
                                         headers={"User-Agent": ua})
            with urllib.request.urlopen(req, timeout=10) as r:
                resp = json.load(r).get("response")
            route = resp.get("flightroute") if isinstance(resp, dict) else None
            routes[callsign] = {"origin": (route.get("origin") or {}).get("icao_code"),
                                "destination": (route.get("destination") or {}).get("icao_code")} if route else {}
        except (urllib.error.URLError, OSError, ValueError, AttributeError):
            return None  # try again next time
    return routes[callsign].get("destination")


def estimate_arrival(fix, target, now):
    """Distance / groundspeed + approach time. While still climbing far from the
    destination, assume a typical airliner cruise speed instead: climb-out
    groundspeed would make the first estimate far too pessimistic."""
    gs, lat, lon, alt = fix.get("gs"), fix.get("lat"), fix.get("lon"), fix.get("alt_baro")
    if not gs or gs < 60 or lat is None or lon is None:
        return None
    dist = haversine_nm(lat, lon, *target)
    if isinstance(alt, (int, float)) and alt < 15000 and dist > 150:
        gs = max(gs, CLIMB_ASSUMED_KT)
    return now + dist / gs * 3600 + APPROACH_MIN * 60


def step(trip, fix, now, airports, tz_name, route_lookup):
    """Advance one trip with this cycle's ADS-B fix for its plane (None = not seen).

    Returns [(title, message, priority), ...] to send to the trip's watcher.
    """
    if trip.get("landed"):
        return []
    out = []
    flight, plane = trip["flight"], plane_name(trip)
    target = airports.coords.get(trip.get("dep_airport") or "")
    target = target[:2] if target else None
    dep = trip.get("dep_time")

    def buffer_text(arr):
        if not dep or not arr:
            return ""
        mins = round((dep - arr) / 60)
        return (f"\nYour {flight} departs {fmt_time(dep, tz_name)}, "
                + (f"{mins} min after it lands." if mins >= 0 else f"{-mins} min before it's due in."))

    if fix is None:
        near = trip.get("near_low")
        if trip.get("departed") and near and now - near > 10 * 60:
            trip["landed"] = True
            out.append((f"🛬 {flight}: your plane has likely landed",
                        f"{plane} dropped off the radar on approach to {trip.get('dep_airport')}."
                        + buffer_text(now), 3))
        return out

    callsign = (fix.get("flight") or "").strip()
    if fix.get("alt_baro") == "ground":
        if target and fix.get("lat") is not None and \
                haversine_nm(fix["lat"], fix["lon"], *target) <= LANDED_NM:
            trip["landed"] = True
            if trip.get("departed"):
                out.append((f"🛬 {flight}: your plane landed",
                            f"{plane} is on the ground at {trip['dep_airport']}." + buffer_text(now), 3))
            else:
                out.append((f"🛬 {flight}: your plane is already here",
                            f"{plane} is on the ground at {trip['dep_airport']}.", 3))
        return out

    # Airborne. Is this the leg into your airport, or an earlier one?
    dest = route_lookup(trip, callsign) if callsign else None
    if dest and not trip.get("dep_airport"):
        trip["dep_airport"] = dest
        target = airports.coords.get(dest)
        target = target[:2] if target else None
    if dest and trip.get("dep_airport") and dest != trip["dep_airport"]:
        if trip.get("leg_note") != callsign:
            trip["leg_note"] = callsign
            origin = trip.get("routes", {}).get(callsign, {}).get("origin") or "?"
            out.append((f"🧳 {flight}: your plane is on an earlier flight",
                        f"{plane} is flying {callsign} {origin}→{dest} first, then on to "
                        f"{trip['dep_airport']} for your flight.", 2))
        return out

    arr = estimate_arrival(fix, target, now) if target else None
    if target and fix.get("lat") is not None and isinstance(fix.get("alt_baro"), (int, float)):
        if fix["alt_baro"] < 5000 and haversine_nm(fix["lat"], fix["lon"], *target) < 30:
            trip["near_low"] = now
    if not trip.get("departed"):
        trip["departed"], trip["eta_sent"] = True, arr
        due = f" Due at {trip['dep_airport']} around {fmt_time(arr, tz_name)}." if arr else ""
        out.append((f"✈️ {flight}: your plane is on its way",
                    f"{plane} is in the air{(' as ' + callsign) if callsign else ''}.{due}" + buffer_text(arr), 3))
        trip["late"] = bool(arr and dep and (dep - arr) / 60 < LATE_MIN)
        trip["tight"] = bool(arr and dep and (dep - arr) / 60 < TIGHT_MIN)
        return out
    if not arr:
        return out
    if dep:
        spare = (dep - arr) / 60
        if spare < LATE_MIN and not trip.get("late"):
            trip["late"] = trip["tight"] = True
            trip["eta_sent"] = arr
            out.append((f"⚠️ {flight} may be delayed",
                        f"{plane} is now due around {fmt_time(arr, tz_name)}." + buffer_text(arr), 4))
            return out
        if spare < TIGHT_MIN and not trip.get("tight"):
            trip["tight"] = True
            trip["eta_sent"] = arr
            out.append((f"⏳ {flight}: tight turnaround",
                        f"{plane} is now due around {fmt_time(arr, tz_name)}." + buffer_text(arr), 3))
            return out
    # Only a later arrival can make you late, so only that is worth a message;
    # an earlier one just moves the baseline.
    if trip.get("eta_sent") and arr - trip["eta_sent"] >= ETA_SHIFT_MIN * 60:
        trip["eta_sent"] = arr
        out.append((f"🧳 {flight}: running later",
                    f"{plane} is now due around {fmt_time(arr, tz_name)}." + buffer_text(arr), 3))
    elif trip.get("eta_sent") and trip["eta_sent"] - arr >= ETA_SHIFT_MIN * 60:
        trip["eta_sent"] = arr
    return out
