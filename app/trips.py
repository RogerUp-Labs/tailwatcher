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
touches them) and are removed a few hours after departure. "trips" numbers
them soonest first; "change 2 …" and "cancel 2" act on that numbering.

Itineraries: "inbound UA1234 11/14 return UA5678 11/21" adds both flights of
a round trip, and "then UA567" adds a connecting flight ("inbound UA1234 then
UA567 return UA5678 11/21 then UA910"). Each flight is an ordinary trip
(checks, tracking and "change" work per flight), linked by a shared
"itinerary" id with leg "out" or "return" (the direction) and seq (its place
in the journey). Two flights in a row with the same leg are a connection:
TailWatcher follows the first one on ADS-B and says how long you'll have to
make the second. Legs are numbered together, and "cancel"/"share" act on the
whole journey unless told "only".

Through flights (one flight number with a stop, A→B→C): "from B" / "to B"
say which part you fly; without them you board at the first airport you
named (or the first leg) and stay on to the end.
"""

import datetime
import json
import logging
import os
import re
import secrets
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

# With an AeroDataBox key: full checks (2 requests) this many hours before
# departure; before that, light checks (1 request) weekly, then daily from
# DAILY_DAYS out. See check_level().
CHECKPOINT_HOURS = [24, 6, 2, 0.75]
DAILY_DAYS = 3
REMINDER_DAYS = (0, 1, 2, 3, 7)  # a watcher's tripReminder choices; 0 = off
APPROACH_MIN = 8        # added to distance/groundspeed for the approach and landing
TIGHT_MIN = 45          # warn when the inbound plane lands this close to your departure
LATE_MIN = 20           # ...and again at this, as a likely delay
ETA_SHIFT_MIN = 15      # re-announce the arrival estimate when it moves this much
CLIMB_ASSUMED_KT = 420  # see estimate_arrival
LANDED_NM = 5           # on the ground within this of your airport = arrived
STOP_NM = 50            # your own flight near a stop on its route: that's the stop, not your landing
CONNECT_TIGHT_MIN = 40  # warn when you'll have less than this to make a connecting flight
CONNECT_MISS_MIN = 15   # ...and again at this, as a likely miss
MAX_LEGS = 8            # flights in a row each way (a sanity cap: each costs AeroDataBox requests)
KEEP_AFTER_DEP_H = 3    # drop a trip this long after its departure
KEEP_UNDATED_H = 36     # ...or this long after it was added, with no departure time

TIME_RE = re.compile(r"^(\d{1,2})(?::(\d{2}))?(am|pm|a|p)?$", re.I)
DATE_RE = re.compile(r"^(\d{1,2})/(\d{1,2})$")
ISO_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")  # "2026-11-14", as the Web UI sends
ADB_TIME_RE = re.compile(r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})(?::\d{2})?Z")

USAGE = (
    "Tell me your flight and the plane flying in for it, e.g.\n"
    "inbound UA1234 N38473 dep 4:30pm\n"
    "(the plane is in your airline app under \"Where's my plane?\"; a flight number like UA567 works too). "
    "Add \"tomorrow\" or a date like 10/20, and \"from IAD\" if it isn't obvious. "
    "Connecting? Add \"then UA567\". Flying back too? Add \"return UA5678 11/21\"."
)
RETURN_WORDS = ("return", "returning")
CONNECT_WORDS = ("then", "connecting", "connect")


# --------------------------------------------------------------- parsing


def scan(words, now, tz_name, airports):
    """Read the words of an "inbound" or "change" message.

    Returns a dict with: idents [(kind, shown, key, marked_as_plane)] in order,
    day / explicit_day (a date), clock ((h, m) or None), airport (ICAO or None),
    to (ICAO where you get off, or None), or an error string.
    """
    tz = commands.zone(tz_name)
    today = datetime.datetime.fromtimestamp(now, tz).date()
    out = {"idents": [], "day": today, "explicit_day": False, "clock": None, "airport": None, "to": None}
    plane_next = False
    i = 0
    while i < len(words):
        w, low = words[i], words[i].lower()
        nxt = words[i + 1] if i + 1 < len(words) else ""
        if low == "to" and nxt.isalpha() and 3 <= len(nxt) <= 4 and resolve_airport(nxt, airports):
            out["to"], i = resolve_airport(nxt, airports), i + 2  # where you get off a through flight
            continue
        if low in ("dep", "departs", "departing", "leaves", "at", "on", "to", "now"):
            i += 1
            continue
        if low in ("plane", "inbound", "via"):
            plane_next, i = True, i + 1
            continue
        if low == "from" and nxt:
            out["airport"], i = resolve_airport(nxt, airports), i + 2
            if not out["airport"]:
                return f"❌ I don't know an airport \"{nxt}\"."
            continue
        if low in ("today", "tomorrow"):
            out["day"] = today + datetime.timedelta(days=low == "tomorrow")
            out["explicit_day"], i = True, i + 1
            continue
        m = ISO_DATE_RE.match(w)
        if m:
            try:
                out["day"], out["explicit_day"] = datetime.date(*map(int, m.groups())), True
            except ValueError:
                return f"❌ \"{w}\" isn't a date."
            i += 1
            continue
        m = DATE_RE.match(w)
        if m:
            out["day"], out["explicit_day"] = month_day(today, int(m.group(1)), int(m.group(2))), True
            if out["day"] is None:
                return f"❌ \"{w}\" isn't a date."
            i += 1
            continue
        if nxt.lower() in ("am", "pm") and TIME_RE.match(w + nxt):
            w, i = w + nxt, i + 1
        m = TIME_RE.match(w)
        if m and (m.group(2) or m.group(3)):  # "4:30", "4pm"; a bare "567" is not a time
            out["clock"] = to_24h(int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower())
            if out["clock"] is None:
                return f"❌ \"{w}\" isn't a time."
            i += 1
            continue
        merged = commands.merge_flight_words(words, i)[i]
        entry = commands.classify(merged)
        if not entry or (entry[0] == "tail" and not commands.looks_like_tail(merged)):
            return f"🤔 I didn't understand \"{w}\"."  # "banana" isn't a tail
        out["idents"].append((*entry, plane_next))
        plane_next = False
        i += 2 if merged != w else 1  # "UA 567" took two words
    return out


def as_inbound(kind, shown, key):
    return {"tail": shown if kind == "tail" else None,
            "flight": shown if kind == "flight" else None,
            "callsign": key if kind == "flight" else None}


def airport_zone(airport, airports, tz_name):
    """The time zone a typed departure time is in: the departure airport's when
    known (a return from LAS leaves on Las Vegas time), else TailWatcher's."""
    return getattr(airports, "tz", {}).get(airport or "") or tz_name


def departure_time(day, clock, explicit_day, now, tz_name):
    """Unix time of `clock` on `day` in tz_name; "dep 9am" said in the evening
    means tomorrow. Without an explicit day, "today" is today in tz_name."""
    tz = commands.zone(tz_name)
    if not explicit_day:
        day = datetime.datetime.fromtimestamp(now, tz).date()
    local = datetime.datetime.combine(day, datetime.time(*clock), tz)
    if not explicit_day and local.timestamp() < now - 3600:
        local += datetime.timedelta(days=1)
    return local.timestamp(), local.date()


def parse_inbound(text, now, tz_name, airports, need_date=False, default_airport=None,
                  default_day=None, after=None):
    """Parse "UA1234 [N38473|UA567] [dep] [4:30pm] [tomorrow|10/20] [from IAD] [to DEN]".

    Returns a new trip dict, or an error string to send back. need_date: the
    flight home has no sensible default day. default_airport: where it leaves
    from without "from" (the return leaves from where the outbound lands).
    default_day / after: a connecting flight is on the same day as the one
    before it, and a time earlier than `after` (that flight's departure) is
    the next day. A typed time is in the departure airport's time zone.
    """
    words = commands.merge_flight_words((text or "").split(), 0)
    if not words:
        return USAGE
    flight = flights.parse_flight(words[0])
    if not flight:
        return f"❌ \"{words[0]}\" doesn't look like a flight number.\n\n{USAGE}"
    f = scan(words[1:], now, tz_name, airports)
    if isinstance(f, str):
        return f"{f}\n\n{USAGE}"
    if len(f["idents"]) > 1:
        return f"🤔 I can only follow one plane per trip.\n\n{USAGE}"
    if need_date and not f["explicit_day"]:
        return f"🤔 Which day is {flight[0]}? Add its date, e.g. \"{flight[0]} 11/21\"."
    day, dep_time, airport = f["day"], None, f["airport"] or default_airport
    explicit = f["explicit_day"]
    if default_day and not explicit:
        day, explicit = default_day, True
    if f["clock"]:
        zone = airport_zone(airport, airports, tz_name)
        dep_time, day = departure_time(day, f["clock"], explicit, now, zone)
        if after and not f["explicit_day"] and dep_time <= after:  # an overnight connection
            dep_time, day = departure_time(day + datetime.timedelta(days=1), f["clock"], True, now, zone)
    inbound = as_inbound(*f["idents"][0][:3]) if f["idents"] else None
    trip = new_trip(flight, day.isoformat(), dep_time, airport, inbound, now)
    trip["get_off"] = trip["arr_airport"] = f["to"]
    return trip


def about_leg(err, label):
    """Label an error as being about one flight of a journey ("Return flight",
    "Connection"), keeping its leading emoji (the Web UI reads that to tell a failure)."""
    if err[:1] in ("❌", "🤔", "🤷") and err[1:2] == " ":
        return f"{err[0]} {label}: {err[2:]}"
    return f"❌ {label}: {err}"


def about_return(err):
    return about_leg(err, "Return flight")


def parse_return(outbound, text, now, tz_name, airports):
    """The flight home for `outbound` ("UA5678 11/21 [N123] [dep 6pm] [from LAS]").

    It leaves from where the outbound lands unless told otherwise. Returns a
    trip dict or an error string."""
    ret = parse_inbound(text, now, tz_name, airports, need_date=True,
                        default_airport=outbound.get("arr_airport"))
    if isinstance(ret, str):
        return about_return(ret)
    if ret["date"] < outbound["date"]:
        return (f"❌ Return flight: {ret['flight']} on {fmt_day(ret, tz_name)} is before "
                f"{outbound['flight']} on {fmt_day(outbound, tz_name)}.")
    return ret


def parse_connection(prev, text, now, tz_name, airports):
    """The connecting flight after `prev` ("UA567 [dep 2:10pm] [N123] [from DEN]").

    Same day as prev unless dated, leaving from where prev lands; a time
    before prev's departure is the next morning. Returns a trip dict or an error string."""
    t = parse_inbound(text, now, tz_name, airports, default_airport=prev.get("arr_airport"),
                      default_day=datetime.date.fromisoformat(prev["date"]), after=prev.get("dep_time"))
    if isinstance(t, str):
        return about_leg(t, "Connection")
    if t["date"] < prev["date"]:
        return (f"❌ Connection: {t['flight']} on {fmt_day(t, tz_name)} is before "
                f"{prev['flight']} on {fmt_day(prev, tz_name)}.")
    return t


def form_prefix(base, n):
    """The Web UI trip form's field prefix for connection n (0-based) after
    the outbound (base "") or the return (base "ret_"): conn_, conn2_, conn3_ …"""
    return f"{base}conn_" if n == 0 else f"{base}conn{n + 1}_"


def split_on(words, separators):
    """["UA1", "then", "UA2"] -> [["UA1"], ["UA2"]]."""
    parts = [[]]
    for w in words:
        if w.lower() in separators:
            parts.append([])
        else:
            parts[-1].append(w)
    return parts


def parse_itinerary(text, now, tz_name, airports):
    """Parse "UA1234 … [then UA567 …] [return UA5678 11/21 … [then UA910 …]]".

    Returns the flights in order, or an error string. With more than one,
    each has leg ("out"/"return") and seq set; add_journey() links them."""
    words = (text or "").split()
    cut = next((i for i, w in enumerate(words) if w.lower() in RETURN_WORDS), None)
    halves = [words] if cut is None else [words[:cut], words[cut + 1:]]
    if cut is not None and not halves[1]:
        return "🤔 Which flight is the return? e.g. \"… return UA5678 11/21\"."
    legs = []
    for half, direction in zip(halves, ("out", "return")):
        parts = split_on(half, CONNECT_WORDS)
        if len(parts) > MAX_LEGS:
            return f"🤔 I can follow up to {MAX_LEGS} flights in a row each way."
        for n, part in enumerate(parts):
            text_ = " ".join(part)
            if not part and n:
                return "🤔 Which flight is the connection? e.g. \"… then UA567\"."
            if n:
                t = parse_connection(legs[-1], text_, now, tz_name, airports)
            elif direction == "return":
                t = parse_return(legs[-1], text_, now, tz_name, airports)
            else:
                t = parse_inbound(text_, now, tz_name, airports)
            if isinstance(t, str):
                return t
            t["leg"] = direction
            legs.append(t)
    for n, t in enumerate(legs):
        t["seq"] = n if len(legs) > 1 else None
        if len(legs) == 1:
            t["leg"] = None
    return legs


def apply_change(trip, text, now, tz_name, airports):
    """Apply a "change 1 …" message to a trip.

    A tail number (or "plane UA567") sets the plane flying in; any other flight
    number renumbers your flight; a time, date or "from IAD" updates those.
    Returns (error or None, needs_lookup) where needs_lookup means the flight
    or date changed and AeroDataBox should look it up again.
    """
    f = scan((text or "").split(), now, tz_name, airports)
    if isinstance(f, str):
        return f, False
    if not (f["idents"] or f["clock"] or f["explicit_day"] or f["airport"] or f["to"]):
        return "🤔 What should change? e.g. \"change 1 AA5678\", \"change 1 dep 5:10pm\", " \
               "\"change 1 N38473\" or \"change 1 11/15\".", False
    renumber = plane = None
    for kind, shown, key, marked in f["idents"]:
        if kind == "tail" or marked:
            plane = as_inbound(kind, shown, key)
        else:
            renumber = flights.parse_flight(shown)
    needs_lookup = False
    if f["airport"]:
        trip["dep_airport"] = f["airport"]
    if f["to"]:
        trip["get_off"] = trip["arr_airport"] = f["to"]
        trip["stops"] = []  # the next AeroDataBox check fills these in again
    zone = airport_zone(trip.get("dep_airport"), airports, tz_name)
    if renumber and renumber[0] != trip["flight"]:
        trip["flight"], trip["callsign"] = renumber
        needs_lookup = True
    if f["explicit_day"] and f["day"].isoformat() != trip["date"]:
        trip["date"] = f["day"].isoformat()
        needs_lookup = True
    if needs_lookup:
        # Keep your departure time (AeroDataBox overwrites it if it knows
        # better); a new date keeps the same clock time on that day.
        if trip.get("dep_time") and f["explicit_day"] and not f["clock"]:
            old = datetime.datetime.fromtimestamp(trip["dep_time"], commands.zone(zone))
            trip["dep_time"], _ = departure_time(f["day"], (old.hour, old.minute), True, now, zone)
        trip.update(seen=False, missing=False, replacement=None,
                    checkpoints=list(CHECKPOINT_HOURS), last_check=None, adb_wait=None, reminded=False)
        if not trip.get("plane_locked"):
            trip["inbound"] = None
    if f["clock"]:
        day = datetime.date.fromisoformat(trip["date"])
        trip["dep_time"], day = departure_time(day, f["clock"], True, now, zone)
    if plane:
        trip["inbound"], trip["plane_locked"] = plane, True
    if plane or needs_lookup:
        trip.update(departed=False, landed=False, eta_sent=None, tight=False, late=False,
                    leg_note=None, near_low=None)
    return None, needs_lookup


def new_trip(flight, date, dep_time, dep_airport, inbound, now):
    return {
        "flight": flight[0], "callsign": flight[1], "date": date,
        "dep_time": dep_time, "dep_airport": dep_airport,
        "inbound": inbound, "source": "manual" if inbound else "aerodatabox",
        "checkpoints": list(CHECKPOINT_HOURS), "last_check": None,
        "created": now, "plane_locked": bool(inbound),
        # Journeys (round trips, connections): every flight shares an itinerary
        # id; leg is "out" or "return", seq its place in the journey.
        "itinerary": None, "leg": None, "seq": None,
        # Where you get off ("to DEN"), and for a flight number with stops,
        # its whole route and the stops on your part of it.
        "get_off": None, "route": [], "stops": [], "arr_time": None,
        # Connections: what was said about making the next flight.
        "conn_sent": {},
        # AeroDataBox bookkeeping: seen = it has listed this flight before,
        # missing = it no longer does (renumbered or cancelled?).
        "seen": False, "missing": False, "replacement": None,
        "arr_airport": None, "sched_dep_local": None,
        # Sharing: other watchers' topics who get your own flight's departure
        # and landing (not the inbound-plane alerts). own = observe() state for
        # your flight's callsign; own_sent = which shared alerts went out.
        "shared_with": [], "own": {}, "own_sent": {},
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


def add_journey(legs, path=None):
    """Store a journey's flights (from parse_itinerary), linked by a new itinerary id."""
    iid = secrets.token_hex(4)
    for n, t in enumerate(legs):
        t.update(itinerary=iid, leg=t.get("leg") or "out", seq=n)
    with TRIPS_LOCK:
        trips = [t for t in load(path) if not any(same_trip(t, l) for l in legs)]
        save(trips + list(legs), path)


def attach(anchor, new, connection, path=None):
    """Store `new` as a further flight of the stored trip `anchor`'s journey:
    a connection goes right after anchor in the same direction, a return at
    the end. It takes on anchor's sharing. Returns the stored anchor, or None
    if it's gone."""
    with TRIPS_LOCK:
        trips = load(path)
        stored = next((t for t in trips if same_trip(t, anchor)), None)
        if stored is None:
            return None
        if not stored.get("itinerary"):
            stored.update(itinerary=secrets.token_hex(4), leg="out")
        legs = [t for t in journey(stored, trips) if not same_trip(t, new)]
        at = next(i for i, t in enumerate(legs) if t is stored) + 1 if connection else len(legs)
        new.update(itinerary=stored["itinerary"], leg=(stored.get("leg") or "out") if connection else "return",
                   shared_with=list(stored.get("shared_with") or []))
        legs.insert(at, new)
        for n, t in enumerate(legs):
            t["seq"] = n
        save([t for t in trips if not same_trip(t, new)] + [new], path)
        return stored


def link_return(out, ret, path=None):
    """Store `ret` as the flight home of the stored trip `out`'s journey."""
    return attach(out, ret, False, path)


def sort_key(t):
    return t.get("dep_time") or date_end(t)


def leg_order(t):
    """A flight's place in its journey (older round trips have no seq)."""
    return t["seq"] if t.get("seq") is not None else int(t.get("leg") == "return")


def ordered(trips):
    """Soonest first, with a journey's flights kept together in order: each
    sorts by its journey's first departure, then its place in it."""
    starts = {}
    for t in trips:
        if t.get("itinerary"):
            k = (t.get("topic"), t["itinerary"])
            starts[k] = min(starts.get(k, sort_key(t)), sort_key(t))
    return sorted(trips, key=lambda t: (starts.get((t.get("topic"), t.get("itinerary")), sort_key(t)),
                                        leg_order(t) if t.get("itinerary") else 0, sort_key(t)))


def journey(trip, trips):
    """The flights of trip's journey in order (outbound first), or [trip]."""
    if not trip.get("itinerary"):
        return [trip]
    return [t for t in ordered(trips) if t.get("topic") == trip.get("topic")
            and t.get("itinerary") == trip["itinerary"]] or [trip]


def neighbour(trip, trips, step):
    legs = journey(trip, trips)
    i = next((i for i, t in enumerate(legs) if t is trip or same_trip(t, trip)), None)
    j = None if i is None else i + step
    return legs[j] if j is not None and 0 <= j < len(legs) else None


def prev_leg(trip, trips):
    """The flight before this one in its journey (for a return, the last flight out), or None."""
    return neighbour(trip, trips, -1)


def connects_from(trip, trips):
    """The flight you connect from onto this one, or None."""
    p = prev_leg(trip, trips)
    return p if p and p.get("leg") == trip.get("leg") else None


def connects_to(trip, trips):
    """The connecting flight after this one, or None."""
    n = neighbour(trip, trips, 1)
    return n if n and n.get("leg") == trip.get("leg") else None


def is_round_trip(legs):
    return any(t.get("leg") == "return" for t in legs)


def split_only(text):
    """("Mom only", "only") -> ("Mom", True): "only" limits an action to one flight."""
    words = (text or "").split()
    rest = [w for w in words if w.lower() != "only"]
    return " ".join(rest), len(rest) != len(words)


def for_topic(topic, path=None):
    """A watcher's trips, soonest first. "trips" numbers them in this order."""
    return ordered([t for t in load(path) if t["topic"] == topic])


def select(mine, selector, now, tz_name):
    """Find a trip in a watcher's list by number ("2") or flight ("AA1234", "AA1234 11/14").

    Returns (trip, rest_of_text) or (None, error).
    """
    words = commands.merge_flight_words((selector or "").split(), 0)
    if not words:
        return None, "Which trip? Send \"trips\" to see them numbered."
    if words[0].isdigit():
        n = int(words[0])
        if not 1 <= n <= len(mine):
            return None, f"🤷 There's no trip {n}. Send \"trips\" to see them numbered."
        return mine[n - 1], " ".join(words[1:])
    flight = flights.parse_flight(words[0])
    if not flight:
        return None, f"🤷 \"{words[0]}\" isn't a trip number or flight number."
    matches = [t for t in mine if t["flight"] == flight[0]]
    rest = words[1:]
    if len(matches) > 1 and rest and DATE_RE.match(rest[0]):
        today = datetime.datetime.fromtimestamp(now, commands.zone(tz_name)).date()
        day = month_day(today, *map(int, rest[0].split("/")))
        matches = [t for t in matches if day and t["date"] == day.isoformat()]
        rest = rest[1:]
    if not matches:
        return None, f"🤷 No trip for {flight[0]}."
    if len(matches) > 1:
        return None, (f"You have {len(matches)} {flight[0]} trips; use its number from \"trips\" "
                      "or add the date (e.g. 11/14).")
    return matches[0], " ".join(rest)


def modify(topic, selector, fn, now, tz_name, path=None):
    """Find one of a watcher's trips and change or delete it under the lock.

    fn(trip, rest_text) returns (reply, keep): keep=False deletes the trip.
    """
    with TRIPS_LOCK:
        all_trips = load(path)
        mine = ordered([t for t in all_trips if t["topic"] == topic])
        trip, rest = select(mine, selector, now, tz_name)
        if trip is None:
            return rest
        reply, keep = fn(trip, rest)
        others = [t for t in all_trips if t is not trip]
        save(others + [trip] if keep else others, path)
        return reply


def modify_legs(topic, selector, fn, now, tz_name, path=None):
    """Like modify(), for actions that cover a whole journey ("cancel",
    "share"): fn(legs, rest_text) gets every flight of the selected trip's
    journey, or just that one if the text says "only"."""
    with TRIPS_LOCK:
        all_trips = load(path)
        mine = ordered([t for t in all_trips if t["topic"] == topic])
        trip, rest = select(mine, selector, now, tz_name)
        if trip is None:
            return rest
        rest, only = split_only(rest)
        legs = [trip] if only else journey(trip, mine)
        reply, keep = fn(legs, rest)
        others = [t for t in all_trips if not any(t is l for l in legs)]
        save(others + legs if keep else others, path)
        return reply


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


def short(airport):
    """KDEN -> DEN, like a departures board."""
    return airport[1:] if airport and len(airport) == 4 and airport[0] == "K" else airport


def arrival_estimate(trip):
    """When your own flight gets in: landed, live estimate, else AeroDataBox's."""
    sent = trip.get("conn_sent") or {}
    return sent.get("landed_at") or sent.get("eta") or trip.get("arr_time")


def connection_minutes(prev, nxt):
    """Minutes between `prev` getting in and the connecting flight `nxt` leaving, or None."""
    arr, dep = arrival_estimate(prev), nxt.get("dep_time")
    return round((dep - arr) / 60) if arr and dep else None


def describe(trip, tz_name, intro=True, prev=None):
    """The trip summary sent when it's added, and by "trips". prev: the
    flight you connect from onto this one."""
    inb = trip.get("inbound") or {}
    icon = "🔗 Connection " if prev else "↩ Return " if trip.get("leg") == "return" else "🧳 "
    head = f"{icon}{trip['flight']} · {fmt_day(trip, tz_name)}"
    if trip.get("dep_time"):
        head += f", departs {fmt_time(trip['dep_time'], tz_name)}"
    if trip.get("dep_airport"):
        head += f" from {trip['dep_airport']}"
    if trip.get("stops"):
        head += f", stops in {', '.join(trip['stops'])} on the way to {trip.get('arr_airport')}"
    lines = [head]
    route = trip.get("route") or []
    if intro and len(route) > 2:
        lines.append(f"{trip['flight']} flies {'→'.join(short(a) or '?' for a in route)} that day; I'm following "
                     f"{short(trip.get('dep_airport'))}→{short(trip.get('arr_airport'))}. Add \"from …\" or "
                     "\"to …\" if your part is different.")
    if prev:
        mins = connection_minutes(prev, trip)
        where = f" in {prev['arr_airport']}" if prev.get("arr_airport") else ""
        lines.append(f"Connecting from {prev['flight']}{where}"
                     + (f": {mins} min after it gets in." if mins is not None and mins >= 0
                        else f": ⚠️ leaves {-mins} min before {prev['flight']} gets in." if mins is not None
                        else "."))
    if trip.get("missing"):
        lines.append("⚠️ No longer listed by AeroDataBox (renumbered or cancelled?)")
        rep = trip.get("replacement")
        if rep:
            lines.append(f"Possible replacement: {rep['flight']}, departs {fmt_time(rep['dep_time'], tz_name)}")
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
    parts = [f"{n}. " + describe(t, tz_name, intro=False, prev=connects_from(t, trips))
             for n, t in enumerate(trips, 1)]
    tail = ("\n\nChange one with \"change 1 …\" (new flight number, plane, "
            "time, date or airport) or remove it with \"cancel 1\".")
    if any(len(journey(t, trips)) > 1 for t in trips):
        tail += (" Cancelling or sharing a flight covers the rest of its trip too (connections and return); "
                 "add \"only\" for just that one.")
    return "\n\n".join(parts) + tail


# ------------------------------------------------------------ AeroDataBox


class AdbError(Exception):
    """`wait`: seconds before the trip checker tries that trip again."""
    def __init__(self, message, wait=1800):
        super().__init__(message)
        self.wait = wait


USAGE_PATH = os.environ.get("TW_ADB_USAGE", "/data/aerodatabox.json")
RATELIMIT_RE = re.compile(r"^x-ratelimit-([a-z0-9-]+?)-(limit|remaining|reset)$")


def record_usage(headers, now=None, path=None):
    """Keep RapidAPI's quota headers (x-ratelimit-requests-remaining, and the
    units the free plan is really metered in) for ⚙ Settings. Best effort."""
    now = now or time.time()
    usage = {}
    for name, value in headers.items():
        m = RATELIMIT_RE.match(name.lower())
        if m and value.strip().isdigit():
            usage.setdefault(m.group(1), {})[m.group(2)] = int(value)
    usage = {k: v for k, v in usage.items() if "remaining" in v}
    if not usage:
        return
    for v in usage.values():
        if "reset" in v:
            v["reset"] = now + v["reset"]  # RapidAPI sends seconds until the monthly reset
    try:
        tmp = (path or USAGE_PATH) + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"at": now, "quotas": usage}, f)
        os.replace(tmp, path or USAGE_PATH)
    except OSError:
        pass
    log.info("AeroDataBox: %s left this month", ", ".join(
        f"{v['remaining']} {k}" for k, v in usage.items()))


def load_usage(path=None):
    """What record_usage() last saw, or None."""
    try:
        with open(path or USAGE_PATH) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def adb_get(key, path, params, ua, timeout=20):
    url = f"https://{ADB_HOST}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={
        "X-RapidAPI-Key": key, "X-RapidAPI-Host": ADB_HOST, "User-Agent": ua})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            record_usage(r.headers)
            body = r.read()
            return json.loads(body) if r.status != 204 and body.strip() else []
    except urllib.error.HTTPError as e:
        record_usage(e.headers or {})
        if e.code in (401, 403):
            raise AdbError("AeroDataBox rejected the API key (check it in Settings)", 6 * 3600) from e
        if e.code == 429:
            raise AdbError("AeroDataBox quota or rate limit reached", 3600) from e
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


def leg_airport(leg, end):
    """ICAO of a leg's "departure" or "arrival" airport."""
    return ((leg.get(end) or {}).get("airport") or {}).get("icao")


def operated(legs):
    """A flight number's legs without codeshare duplicates."""
    return [l for l in legs if not l.get("codeshareStatus") == "IsCodeshared"] or legs


def pick_leg(legs, dep_airport):
    """Your leg of a flight number: the one leaving dep_airport, else the first."""
    legs = operated(legs)
    if dep_airport:
        mine = [l for l in legs if ((l.get("departure") or {}).get("airport") or {}).get("icao") == dep_airport]
        if mine:
            return mine[0]
    legs = sorted(legs, key=lambda l: adb_time(l.get("departure"), "scheduledTime") or 0)
    return legs[0] if legs else None


def through_route(legs, leg):
    """The flight number's legs that join up with `leg` into one route
    (A→B, B→C: a through flight with a stop), in order."""
    legs = sorted(legs, key=lambda l: adb_time(l.get("departure"), "scheduledTime") or 0)
    i = next(n for n, l in enumerate(legs) if l is leg)
    start, end = i, i
    while start > 0 and leg_airport(legs[start - 1], "arrival") == leg_airport(legs[start], "departure"):
        start -= 1
    while end + 1 < len(legs) and leg_airport(legs[end], "arrival") == leg_airport(legs[end + 1], "departure"):
        end += 1
    return legs[start:end + 1]


def ride(route, leg, get_off):
    """Your part of a through flight: from `leg` to get_off, else to the end."""
    part = route[route.index(leg):]
    off = next((n for n, l in enumerate(part) if leg_airport(l, "arrival") == get_off), None)
    return part[:off + 1] if get_off and off is not None else part


def pick_inbound(plane_legs, dep_airport, dep_time):
    """The plane's leg into dep_airport that lands before your departure. On a
    through flight you board at the stop, that's your own flight number's
    first leg."""
    best, best_arr = None, None
    for l in plane_legs:
        arr = l.get("arrival") or {}
        if (arr.get("airport") or {}).get("icao") != dep_airport:
            continue
        t = adb_time(arr, "scheduledTime")
        if t is None or (dep_time and t > dep_time + 3600):
            continue
        if best_arr is None or t > best_arr:
            best, best_arr = l, t
    return best


def resolve(trip, key, ua, full=True, sleep=time.sleep, get=adb_get):
    """Refresh the trip from AeroDataBox. Returns a list of change notes.

    A light check (full=False) costs one request: is the flight still listed,
    and when does it leave? A full check also looks up the assigned plane's
    day to find its inbound leg (a second request); that's only worth doing in
    the last day, when airlines have actually assigned a plane.
    Raises AdbError if AeroDataBox can't be used.
    """
    notes = []
    common = {"withAircraftImage": "false", "withLocation": "false"}
    legs = get(key, f"/flights/number/{urllib.parse.quote(trip['flight'])}/{trip['date']}",
               {**common, "dateLocalRole": "Departure"}, ua)
    legs = operated(legs if isinstance(legs, list) else [])
    leg = pick_leg(legs, trip.get("dep_airport"))
    if not leg:
        if trip.get("seen") and not trip.get("missing"):
            trip["missing"] = True
            notes.append(("missing", None, None))
        return notes
    if trip.get("missing"):
        trip.update(missing=False, replacement=None)
        notes.append(("back", None, None))
    trip["seen"] = True
    dep = leg.get("departure") or {}
    trip["dep_airport"] = (dep.get("airport") or {}).get("icao") or trip.get("dep_airport")
    route = through_route(legs, leg)
    mine = ride(route, leg, trip.get("get_off"))
    trip["arr_airport"] = leg_airport(mine[-1], "arrival") or trip.get("arr_airport")
    trip["arr_time"] = adb_time(mine[-1].get("arrival"), "revisedTime", "predictedTime", "scheduledTime")
    trip["stops"] = [a for a in (leg_airport(l, "arrival") for l in mine[:-1]) if a]
    trip["route"] = [leg_airport(route[0], "departure")] + [leg_airport(l, "arrival") for l in route] \
        if len(route) > 1 else []
    trip["sched_dep_local"] = (dep.get("scheduledTime") or {}).get("local") or trip.get("sched_dep_local")
    new_dep = adb_time(dep, "revisedTime", "predictedTime", "scheduledTime")
    if new_dep:
        old = trip.get("dep_time")
        if old and abs(new_dep - old) >= 10 * 60:
            notes.append(("dep_change", old, new_dep))
        trip["dep_time"] = new_dep
    reg = commands.normalize_tail((leg.get("aircraft") or {}).get("reg") or "")
    if not full or not reg or trip.get("plane_locked"):
        return notes  # far out, unassigned, or you named the plane yourself
    old_tail = (trip.get("inbound") or {}).get("tail")
    sleep(1.1)  # free tier allows 1 request per second
    plane_legs = get(key, f"/flights/reg/{reg}/{trip['date']}", {**common, "dateLocalRole": "Both"}, ua)
    inbound = pick_inbound(plane_legs if isinstance(plane_legs, list) else [],
                           trip["dep_airport"], trip.get("dep_time"))
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


def find_replacement(trip, key, ua, get=adb_get):
    """After a flight vanishes, look for the airline's new number for it: a
    departure from the same airport to the same destination, same airline,
    within 3 hours of the old time. One request. Returns a dict or None."""
    local = trip.get("sched_dep_local") or ""
    m = re.match(r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})", local)
    if not (m and trip.get("dep_airport") and trip.get("arr_airport")):
        return None
    t = datetime.datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}")
    fmt = "%Y-%m-%dT%H:%M"
    board = get(key, f"/flights/airports/icao/{trip['dep_airport']}/"
                     f"{(t - datetime.timedelta(hours=3)).strftime(fmt)}/"
                     f"{(t + datetime.timedelta(hours=3)).strftime(fmt)}",
                {"direction": "Departure", "withLeg": "true", "withCancelled": "false",
                 "withCodeshared": "false", "withCargo": "false", "withPrivate": "false",
                 "withLocation": "false"}, ua)
    departures = board.get("departures") if isinstance(board, dict) else None
    airline = (trip.get("callsign") or "")[:3]
    best, best_gap = None, None
    for f in departures or []:
        number = flights.parse_flight(f.get("number") or "")
        if not number or number[0] == trip["flight"] or number[1][:3] != airline:
            continue
        if ((f.get("arrival") or {}).get("airport") or {}).get("icao") != (trip.get("stops") or [trip["arr_airport"]])[0]:
            continue
        when = adb_time(f.get("departure") or f.get("movement"), "scheduledTime")
        if when is None:
            continue
        gap = abs(when - (trip.get("dep_time") or when))
        if best_gap is None or gap < best_gap:
            best, best_gap = {"flight": number[0], "dep_time": when}, gap
    return best


def check_level(trip, now):
    """What AeroDataBox check is due: None, "light" or "full".

    More than 3 days out: a light check weekly (is the flight still listed?).
    From then until a day out: a light check daily. In the last day: full
    checks about 24h, 6h, 2h and 45 min before departure (the plane is
    usually only assigned then). Consumes the checkpoints it reports.
    Nothing while a failed check waits to retry (`adb_wait`).
    """
    if trip.get("source") != "aerodatabox" or trip.get("landed") or now < (trip.get("adb_wait") or 0):
        return None
    dep = trip.get("dep_time")
    if dep and now >= dep - 24 * 3600:
        passed = [h for h in trip.get("checkpoints") or [] if now >= dep - h * 3600]
        if not passed:
            return None
        trip["checkpoints"] = [h for h in trip["checkpoints"] if h not in passed]
        return "full"
    ahead = (dep or date_end(trip)) - now
    interval = 7 * 86400 if ahead > DAILY_DAYS * 86400 else 86400
    last = trip.get("last_check")
    return "light" if not last or now - last >= interval else None


def next_check_time(trip, now):
    """When check_level() will next ask for an AeroDataBox check (for display)."""
    if trip.get("source") != "aerodatabox" or trip.get("landed"):
        return None
    wait = trip.get("adb_wait") or 0
    dep = trip.get("dep_time")
    if dep and now >= dep - 25 * 3600:
        upcoming = [dep - h * 3600 for h in trip.get("checkpoints") or [] if dep - h * 3600 > now]
        return max(min(upcoming), wait) if upcoming else None
    ahead = (dep or date_end(trip)) - now
    interval = 7 * 86400 if ahead > DAILY_DAYS * 86400 else 86400
    if trip.get("last_check"):
        # a weekly check never lands past the start of the daily ones
        due = min(trip["last_check"] + interval, (dep or date_end(trip)) - DAILY_DAYS * 86400)
        return max(now, due, wait)
    return max(now, wait)


REMINDER_WINDOW_H = 6  # a reminder that's this late (TailWatcher was off) is skipped


def reminder_due(trip, days, now):
    """A watcher's trip reminder (tripReminder: days before departure, 0 = off)
    is due for this flight. Once per flight, only for flights you start from
    (not a connection), and not for a trip added after the reminder time."""
    dep = trip.get("dep_time")
    if not days or not dep or trip.get("reminded") or trip.get("landed"):
        return False
    at = dep - days * 86400
    return trip.get("created", 0) < at <= now < at + REMINDER_WINDOW_H * 3600


def reminder_message(trip, days, tz_name, then=()):
    """(title, message, priority) for reminder_due(). then: its connections, in order."""
    when = "tomorrow" if days == 1 else "in a week" if days == 7 else f"in {days} days"
    lines = [describe(trip, tz_name, intro=False)]
    for c in then:
        line = f"🔗 Then {c['flight']}"
        if c.get("dep_time"):
            line += f", departs {fmt_time(c['dep_time'], tz_name)}"
        if c.get("dep_airport"):
            line += f" from {c['dep_airport']}"
        lines.append(line)
    return f"🧳 {trip['flight']} {when}", "\n".join(lines), 3


def change_messages(trip, notes, tz_name, number=None):
    """Messages for resolve() notes. `number` is the trip's place in "trips"."""
    ref = str(number) if number else trip["flight"]
    out = []
    for kind, old, new in notes:
        if kind == "plane_change":
            out.append(("🔁 Plane change", f"{trip['flight']} is now flying {new} (was {old}).\n"
                        + describe(trip, tz_name, intro=False), 4))
        elif kind == "dep_change":
            later = "later" if new > old else "earlier"
            out.append((f"🕓 {trip['flight']} time change",
                        f"Now departs {fmt_time(new, tz_name)} ({later} than {fmt_time(old, tz_name)}).", 4))
        elif kind == "missing":
            text = (f"{trip['flight']} on {fmt_day(trip, tz_name)} is no longer listed. "
                    "The airline may have renumbered or cancelled it.")
            rep = trip.get("replacement")
            if rep:
                text += (f"\nLooks like it's now {rep['flight']}, departing {fmt_time(rep['dep_time'], tz_name)}"
                         f" to {trip.get('arr_airport')}. Reply \"change {ref} {rep['flight']}\" to switch.")
            else:
                text += (f"\nWhen you know the new flight number, reply \"change {ref} AA5678\" "
                         "(with the new number), or \"cancel " + ref + "\".")
            out.append((f"⚠️ {trip['flight']} has disappeared", text, 4))
        elif kind == "back":
            out.append((f"✅ {trip['flight']} is listed again",
                        "AeroDataBox shows your flight again; I'll keep tracking it.", 3))
    return out


# ------------------------------------------------------------ live tracking


LIVE_BEFORE_H = 24  # start following the plane this long before departure
OWN_BEFORE_H = 3    # for shared trips, follow your own flight from this long before departure...
OWN_AFTER_H = 20    # ...until it lands, or this long after departure


def own_live(trip, now, connecting=False):
    """Is it time to follow your own flight, for the people you shared it with
    or because you have a connection to make after it?

    Only around departure: the same flight number flies every day, so a
    flight shared a month ahead must not alert on the other 29 days."""
    if not (trip.get("shared_with") or connecting) or (trip.get("own_sent") or {}).get("landed"):
        return False
    if trip.get("dep_time"):
        return trip["dep_time"] - OWN_BEFORE_H * 3600 <= now <= trip["dep_time"] + OWN_AFTER_H * 3600
    d = datetime.date.fromisoformat(trip["date"])
    start = datetime.datetime.combine(d, datetime.time(0), datetime.timezone.utc).timestamp() - 14 * 3600
    return start <= now <= date_end(trip) + 12 * 3600


def share_with(trip, topics, own_topic):
    """Set who the trip is shared with. Returns the topics newly added."""
    wanted = [t for t in dict.fromkeys(topics) if t and t != own_topic]
    added = [t for t in wanted if t not in (trip.get("shared_with") or [])]
    trip["shared_with"] = wanted
    return added


def near(ac, airport, airports, nm):
    """Is the aircraft position `ac` within nm of airport? False when unknown."""
    c = airports.coords.get(airport or "")
    if not c or not ac or ac.get("lat") is None or ac.get("lon") is None:
        return False
    return haversine_nm(ac["lat"], ac["lon"], c[0], c[1]) <= nm


def boards_midway(trip):
    """A through flight you board at one of its stops: its earlier leg's takeoff isn't yours."""
    route = trip.get("route") or []
    return bool(route and trip.get("dep_airport") and route[0] != trip["dep_airport"])


def own_event(trip, event, ac, airports):
    """Turn observe()'s event for your own flight into "departed", "landed" or
    None, recorded in trip["own_sent"] so each happens once. ac: this cycle's
    fix, or the last one. On a through flight, only the takeoff from where you
    board counts, and a landing at a stop on the way isn't your landing."""
    sent = trip.setdefault("own_sent", {})
    if event in ("departed", "airborne") and not sent.get("departed"):
        if boards_midway(trip) and not near(ac, trip["dep_airport"], airports, STOP_NM):
            return None
        sent["departed"] = True
        return "departed"
    if event in ("landed", "lost_low") and sent.get("departed") and not sent.get("landed"):
        if any(near(ac, stop, airports, STOP_NM) for stop in trip.get("stops") or []):
            return None
        sent["landed"] = True
        return "landed"
    return None


def connection_step(trip, nxt, fix, kind, now, airports, tz_name):
    """You're on `trip` and connect to `nxt`: from this cycle's fix of your own
    flight (kind = own_event()'s result), say how long you'll have to make it.
    Only a later arrival is worth another message. Returns [(title, message, priority)]."""
    sent = trip.setdefault("conn_sent", {})
    if sent.get("landed_at") or not (trip.get("own_sent") or {}).get("departed"):
        return []
    flight, where, dep = trip["flight"], trip.get("arr_airport"), nxt.get("dep_time")
    there = f" in {where}" if where else ""

    def left(arr):
        mins = round((dep - arr) / 60)
        if mins < 0:
            return f"{nxt['flight']} is due to leave {-mins} min before that."
        return f"That leaves {mins} min to make {nxt['flight']} (departs {fmt_time(dep, tz_name)})."

    if kind == "landed":
        sent["landed_at"] = now
        if not dep:
            return [(f"🛬 {flight} landed{there}", f"Your connection is {nxt['flight']}.", 3)]
        mins = round((dep - now) / 60)
        other = f" from {nxt['dep_airport']}" if nxt.get("dep_airport") and nxt["dep_airport"] != where else ""
        return [(f"🛬 {flight} landed{there}",
                 f"{nxt['flight']} departs{other} at {fmt_time(dep, tz_name)}, "
                 + (f"{mins} min from now." if mins >= 0 else f"{-mins} min ago by its schedule."),
                 4 if mins < CONNECT_TIGHT_MIN else 3)]
    target = airports.coords.get(where or "")
    if not fix or fix.get("alt_baro") == "ground" or not target or not dep:
        return []
    arr = estimate_arrival(fix, target[:2], now)
    if not arr:
        return []
    spare = (dep - arr) / 60
    due = f"{flight} is due{there} around {fmt_time(arr, tz_name)}. " + left(arr)
    if not sent.get("eta"):
        sent.update(eta=arr, tight=spare < CONNECT_TIGHT_MIN, miss=spare < CONNECT_MISS_MIN)
        return [(f"✈️ {flight} is on its way" + (f" to {where}" if where else ""), due, 4 if sent["tight"] else 3)]
    if spare < CONNECT_MISS_MIN and not sent.get("miss"):
        sent.update(eta=arr, tight=True, miss=True)
        return [(f"⚠️ {nxt['flight']}: connection at risk", due, 4)]
    if spare < CONNECT_TIGHT_MIN and not sent.get("tight"):
        sent.update(eta=arr, tight=True)
        return [(f"⏳ {nxt['flight']}: tight connection", due, 4)]
    if arr - sent["eta"] >= ETA_SHIFT_MIN * 60:
        sent["eta"] = arr
        return [(f"🧳 {flight}: running later", due, 3)]
    if sent["eta"] - arr >= ETA_SHIFT_MIN * 60:
        sent["eta"] = arr
    return []


def connection_notes(prev, nxt, tz_name):
    """Before you fly: warn when AeroDataBox's times leave a tight (or no)
    connection from prev to nxt, and again if it shrinks by another 15 min."""
    arr, dep = prev.get("arr_time"), nxt.get("dep_time")
    if not arr or not dep or (prev.get("own_sent") or {}).get("departed"):
        return []
    spare = round((dep - arr) / 60)
    sent = prev.setdefault("conn_sent", {})
    last = sent.get("sched")
    if spare >= CONNECT_TIGHT_MIN or (last is not None and last - spare < ETA_SHIFT_MIN):
        return []
    sent["sched"] = spare
    where = f" in {prev['arr_airport']}" if prev.get("arr_airport") else ""
    times = (f"{prev['flight']} is due{where} at {fmt_time(arr, tz_name)} and {nxt['flight']} "
             f"leaves at {fmt_time(dep, tz_name)}")
    if spare < 0:
        return [(f"⚠️ {nxt['flight']}: connection doesn't work", times + ". Check with the airline.", 4)]
    return [(f"⏳ Tight connection{where}", f"{times}: {spare} min to change planes.", 4)]


def share_announcement(legs, owner, tz_name):
    """What a watcher gets when a trip (one flight, or a whole journey) is
    shared with them: one note, however many flights."""
    lines = []
    for n, trip in enumerate(legs):
        when = f"departs {fmt_time(trip['dep_time'], tz_name)}" if trip.get("dep_time") else ""
        where = f"from {trip['dep_airport']}" if trip.get("dep_airport") else ""
        detail = " ".join(x for x in (when, where) if x)
        first_back = trip.get("leg") == "return" and (n == 0 or legs[n - 1].get("leg") != "return")
        label = "Return: " if first_back and len(legs) > 1 else "Then: " if n else ""
        lines.append(f"{label}{trip['flight']} · {fmt_day(trip, tz_name)}{', ' + detail if detail else ''}.")
    if len(legs) > 1:
        kind = "a round trip" if is_round_trip(legs) else "a trip"
        return (f"📣 {owner} shared {kind} with you", "\n".join(lines)
                + "\nYou'll get an alert when each flight departs and when it lands.", 3)
    return (f"📣 {owner} shared a flight with you",
            lines[0] + "\nYou'll get an alert when it departs and when it lands.", 3)


def share_note_messages(trip, notes, owner, tz_name):
    """AeroDataBox changes worth passing on to the people a trip is shared with
    (time changes and disappearances; not plane swaps, which only matter to you)."""
    out = []
    for kind, old, new in notes:
        if kind == "dep_change":
            later = "later" if new > old else "earlier"
            out.append((f"🕓 {owner}'s flight {trip['flight']}: new time",
                        f"Now departs {fmt_time(new, tz_name)} ({later} than {fmt_time(old, tz_name)}).", 4))
        elif kind == "missing":
            out.append((f"⚠️ {owner}'s flight {trip['flight']} changed",
                        f"{trip['flight']} on {fmt_day(trip, tz_name)} is no longer listed; the airline may "
                        f"have renumbered or cancelled it. {owner} will update it.", 4))
        elif kind == "back":
            out.append((f"✅ {owner}'s flight {trip['flight']} is listed again", "Tracking continues.", 3))
    return out


def is_live(trip, now):
    """Follow the plane on ADS-B only in the last day: a month out, the same
    tail is flying other people's trips."""
    if trip.get("dep_time"):
        return now >= trip["dep_time"] - LIVE_BEFORE_H * 3600
    d = datetime.date.fromisoformat(trip["date"])
    earliest = datetime.datetime.combine(d, datetime.time(0), datetime.timezone.utc) \
        - datetime.timedelta(hours=14)  # the date starts first at UTC+14
    return now >= earliest.timestamp() - 12 * 3600


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

    # Airborne. Is this the leg into your airport, or an earlier one? (On a
    # through flight boarding at the stop, the plane is your own flight number,
    # whose usual route may well end somewhere else.)
    through = (trip.get("inbound") or {}).get("callsign") == trip.get("callsign")
    dest = route_lookup(trip, callsign) if callsign and not through else None
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
