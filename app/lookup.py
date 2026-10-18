"""Aircraft lookup for the "info N12345" text command.

Combines four free sources, fetched in parallel; any of them may fail or
have nothing, and the reply uses whatever came back:

- FAA registry N-number page (US only): owner, city/state, model, year,
  engine, registration status, Mode S hex. Parsed from the HTML.
- hexdb.io: tail ↔ hex, plus a readable type name and owner/operator for
  any country.
- adsb.fi (or the configured feed): live position, plus military / LADD /
  PIA flags.
- planespotters.net: a photo, with the photographer credit their terms ask for.
"""

import html
import json
import logging
import math
import re
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger("tailwatcher")

FAA_URL = "https://registry.faa.gov/AircraftInquiry/Search/NNumberResult?nNumberTxt={n}"
HEXDB_REG_URL = "https://hexdb.io/reg-hex?reg={reg}"
HEXDB_AIRCRAFT_URL = "https://hexdb.io/api/v1/aircraft/{hex}"
PHOTO_URL = "https://api.planespotters.net/pub/photos/reg/{reg}"
ADSBX_URL = "https://globe.adsbexchange.com/?icao={hex}"
# The FAA site turns away requests that don't look like a browser.
FAA_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"

# adsb.fi / adsb.lol dbFlags bits.
FLAGS = [(1, "🎖 military"), (2, "⭐ interesting"), (4, "🔒 FAA privacy program (PIA)"),
         (8, "🚫 hidden from FlightAware/FR24 (LADD)")]
# Words the FAA writes in capitals that should stay that way when title-casing.
KEEP_UPPER = {"LLC", "LP", "LLP", "II", "III", "IV", "USA", "US", "PC", "NA", "DBA", "FBO",
              "AG", "SA", "PLC", "GE", "CFM", "FAA"}
# The FAA's truncated engine-maker names.
ENGINE_MAKERS = {"CONT MOTOR": "Continental", "CONTINENTAL": "Continental", "ROLLS-ROYC": "Rolls-Royce",
                 "P&W CANADA": "Pratt & Whitney Canada", "PRATT & WHITNEY": "Pratt & Whitney",
                 "PRATT&WHIT": "Pratt & Whitney", "CFM INTL": "CFM", "CFM INTL.": "CFM", "GE": "GE", "HONEYWELL": "Honeywell",
                 "LYCOMING": "Lycoming", "ROTAX": "Rotax", "WILLIAMS": "Williams", "GARRETT": "Garrett"}
ENGINE_TYPES = {"reciprocating": "piston", "turbo-fan": "turbofan", "turbo-prop": "turboprop",
                "turbo-shaft": "turboshaft", "turbo-jet": "turbojet"}
# FAA registration types worth saying when the owner's name doesn't already.
REG_TYPES = {"Individual": "individual", "Government": "government", "Co-Owned": "co-owned",
             "Partnership": "partnership", "Non Citizen Corporation": "non-US corporation",
             "Non-Citizen Co-Owned": "non-US co-owned"}


def get(url, ua, timeout=10, as_json=True):
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read().decode("utf-8", "replace")
    return json.loads(body) if as_json else body


def parse_faa(page):
    """Map each FAA record field ("Name", "Model", …) to its first value."""
    out = {}
    for label, value in re.findall(r'<td[^>]*data-label="([^"]+)"[^>]*>(.*?)</td>', page, re.S):
        text = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", value))).strip()
        out.setdefault(label.strip(), text)
    return out if out.get("Model") or out.get("Name") else {}


def titlecase(text):
    return " ".join(w if w in KEEP_UPPER else w.capitalize() for w in (text or "").split())


def describe_engine(faa):
    """"Continental IO-360 (piston)" from the FAA's "CONT MOTOR" / "IO-360 SER"."""
    maker = (faa.get("Engine Manufacturer") or "").strip()
    model = re.sub(r"\s+(SER|SERIES)$", "", (faa.get("Engine Model") or "").strip())
    maker = ENGINE_MAKERS.get(maker.rstrip("."), titlecase(maker)) if maker != "None" else ""
    model = "" if model == "None" else model
    if maker and model.upper().startswith(maker.split()[0].upper()):
        maker = ""  # "CFM56-7B" already names its maker
    name = " ".join(x for x in (maker, model) if x)
    etype = (faa.get("Engine Type") or "").strip().lower()
    etype = ENGINE_TYPES.get(etype, etype) if etype not in ("", "none") else ""
    return f"{name} ({etype})" if name and etype else name or etype


def compass(lat1, lon1, lat2, lon2):
    """Compass point (N, NE, …) from point 1 toward point 2."""
    dlon = math.radians(lon2 - lon1)
    p1, p2 = math.radians(lat1), math.radians(lat2)
    y = math.sin(dlon) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dlon)
    deg = (math.degrees(math.atan2(y, x)) + 360) % 360
    return ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][int((deg + 22.5) // 45) % 8]


def gather(tail, ua, fetch_live):
    """Fetch every source for a tail. Returns a dict of whatever was found."""
    us = tail.startswith("N") and len(tail) <= 6

    def faa():
        return parse_faa(get(FAA_URL.format(n=urllib.parse.quote(tail)), FAA_UA, as_json=False)) if us else {}

    def reg_hex():
        h = get(HEXDB_REG_URL.format(reg=urllib.parse.quote(tail)), ua, as_json=False).strip()
        return h.lower() if re.fullmatch(r"[0-9A-Fa-f]{6}", h) else None

    def photo():
        photos = get(PHOTO_URL.format(reg=urllib.parse.quote(tail)), ua).get("photos") or []
        return photos[0] if photos else None

    def safe(fn):
        try:
            return fn()
        except Exception as e:  # each source is optional
            log.info("lookup %s: %s failed: %s", tail, getattr(fn, "__name__", "source"), e)
            return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {name: pool.submit(safe, fn) for name, fn in
                   (("faa", faa), ("hex", reg_hex), ("live", lambda: fetch_live(tail)), ("photo", photo))}
        found = {name: f.result() for name, f in futures.items()}

    live = found["live"] or {}
    hexcode = ((found["faa"] or {}).get("Mode S Code (Base 16 / Hex)") or found["hex"]
               or live.get("hex") or "").lower() or None
    found["hexdb"] = safe(lambda: get(HEXDB_AIRCRAFT_URL.format(hex=hexcode), ua)) if hexcode else None
    found["hexcode"] = hexcode
    return found


def build_reply(tail, found, airports, watching):
    """Turn gathered data into an ntfy payload (without topic). None if nothing found."""
    faa = found.get("faa") or {}
    hexdb = found.get("hexdb") or {}
    if isinstance(hexdb, dict) and hexdb.get("status") == "404":
        hexdb = {}
    live = found.get("live") or {}
    photo = found.get("photo")
    hexcode = found.get("hexcode")
    if not (faa or hexdb or live):
        return None

    lines = []
    # What it is
    maker = hexdb.get("Manufacturer") or titlecase(faa.get("Manufacturer Name"))
    model = hexdb.get("Type") or faa.get("Model") or ""
    what = " ".join(x for x in (maker, model) if x) or (live.get("desc") or "").title() or "Unknown type"
    year = faa.get("Mfr Year") or live.get("year")
    lines.append(f"{what} ({year})" if year and year != "None" else what)

    # Who owns / operates it
    if faa.get("Name"):
        where = ", ".join(titlecase(faa[k]) for k in ("City", "State") if faa.get(k))
        kind = REG_TYPES.get(faa.get("Type Registration") or "")
        owner = titlecase(faa["Name"])
        lines.append(f"Owner: {owner}" + (f" ({kind})" if kind else "") + (f" · {where}" if where else ""))
    else:
        op = hexdb.get("RegisteredOwners") or live.get("ownOp")
        if op:
            lines.append(f"Operator: {titlecase(op) if op.isupper() else op}")

    if faa.get("Status"):
        exp = faa.get("Expiration Date")
        lines.append(f"Registration: {faa['Status'].lower()}" + (f", expires {exp}" if exp and exp != "None" else ""))
    engine = describe_engine(faa)
    if engine:
        lines.append(f"Engine: {engine}")

    # Where it is now
    if live:
        alt = live.get("alt_baro")
        lat, lon = live.get("lat"), live.get("lon")
        near = landmark(airports, lat, lon) if lat is not None and lon is not None else None
        if alt == "ground":
            spot = f" at {near[0]}" if near and near[1] < 3 else ""
            lines.append(f"Live: on the ground{spot}")
        else:
            bits = [f"✈️ {alt:,.0f} ft" if isinstance(alt, (int, float)) else "✈️ airborne"]
            if live.get("gs") is not None:
                bits.append(f"{live['gs']:.0f} kt")
            if near:
                ident, dist, alat, alon = near
                bits.append(f"{dist:.0f} nm {compass(alat, alon, lat, lon)} of {ident}"
                            if dist >= 2 else f"over {ident}")
            callsign = (live.get("flight") or "").strip()
            if callsign and callsign != tail:
                bits.append(callsign)
            lines.append("Live: " + " · ".join(bits))
    else:
        lines.append("Live: not transmitting right now")

    flags = [label for bit, label in FLAGS if (live.get("dbFlags") or 0) & bit]
    if flags:
        lines.append("Flags: " + ", ".join(flags))

    lines.append("On your list ✓" if watching else f"Send {tail} to watch it.")
    if photo and photo.get("photographer"):
        lines.append(f"📷 {photo['photographer']} / planespotters.net")

    actions = []
    if hexcode:
        actions.append({"action": "view", "label": "ADS-B Exchange", "url": ADSBX_URL.format(hex=hexcode)})
    if faa:
        actions.append({"action": "view", "label": "FAA record", "url": FAA_URL.format(n=tail)})
    if photo and photo.get("link"):
        actions.append({"action": "view", "label": "Photo", "url": photo["link"]})
    thumb = ((photo or {}).get("thumbnail_large") or {}).get("src")
    return {
        "title": f"🔎 {tail}",
        "message": "\n".join(lines),
        "tags": ["robot"],
        "priority": 2,
        "click": actions[0]["url"] if actions else None,
        "actions": actions,
        "attach": thumb,
        "filename": f"{tail}.jpg" if thumb else None,
    }


def landmark(airports, lat, lon, max_nm=60):
    """Nearest airport with a 4-letter ICAO code (KIAD, EGLL), as a reference
    point people recognize: (ident, distance_nm, lat, lon), or None.

    Private strips like "VA17" are skipped; they are often closer but mean
    nothing to anyone reading the alert.
    """
    best, best_d = None, max_nm
    for ident, _name, alat, alon in airports.rows:
        if len(ident) != 4 or not ident.isalpha() or abs(alat - lat) > 1.0:
            continue
        d = haversine_nm(lat, lon, alat, alon)
        if d < best_d:
            best, best_d = (ident, d, alat, alon), d
    return best


def haversine_nm(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 3440.065 * math.asin(math.sqrt(a))
