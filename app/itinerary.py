"""Import a trip from a booking confirmation: pasted text, a saved email or a calendar file.

There's no one itinerary standard, but TailWatcher only needs each flight's
number and date (AeroDataBox and ADS-B fill in the rest), so this reads, in
order of trust:

1. schema.org FlightReservation JSON-LD, which most airlines and booking
   sites hide in their confirmation emails' HTML (it's what Gmail's flight
   cards read);
2. calendar events (.ics files, or one attached to the email), as airline
   "add to calendar" buttons, TripIt and Kayak Trips make them;
3. the text itself: flight numbers like "UA 1234", with the nearest date,
   time and airport codes around each.

PDFs, images and Word files aren't read (the stdlib can't); people copy the
text out instead. Nothing here makes a network request: the result only
pre-fills the Add trip form, which the person checks before saving.
"""

import datetime
import email
import email.policy
import html
import html.parser
import json
import re

import commands
import flights
import trips

MAX_FLIGHTS = 12
CONNECT_MAX_H = 24  # a flight leaving within this of the one before (from where it lands) is a connection

SUPPORTED = "pasted text, saved emails (.eml), calendar files (.ics) and web pages (.html, .txt)"
NOT_SUPPORTED = ("PDFs, screenshots and Word files can't be read. Open it, select all the text, "
                 "copy it and paste it here instead.")

MONTHS = {m: n for n, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
MON = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
DATE_PATTERNS = [  # (regex, which groups are year, month, day)
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), "ymd"),
    (re.compile(MON.join((r"\b", r"\s+(\d{1,2})(?:st|nd|rd|th)?\b(?:,?\s+(\d{4})\b)?")), re.I), "mdy"),
    (re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+" + MON + r"(?:,?\s+(\d{4})\b)?", re.I), "dmy"),
    (re.compile(r"\b(\d{2})(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)(\d{2})?\b"), "dmy"),
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4}|\d{2})\b"), "nnY"),
]
TIME_12 = re.compile(r"\b(\d{1,2}):(\d{2})\s*([ap])\.?\s?m\b\.?", re.I)
TIME_24 = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b(?!\s*[ap]\.?\s?m)", re.I)
FLIGHT_RE = re.compile(r"\b([A-Z]{3}|[A-Z][A-Z0-9]|[0-9][A-Z])(\s?)(\d{1,4})\b")
AIRPORT_RE = re.compile(r"\b[A-Z]{3}\b")
ICAO_AIRLINES = set(flights.AIRLINES.values())
# Common capitalised words that happen to be some airport's IATA code.
NOT_AIRPORTS = {
    "THE", "AND", "FOR", "YOU", "ARE", "ALL", "NEW", "NOT", "ONE", "TWO", "USA", "USD", "EUR", "GBP",
    "CAD", "PDF", "FAQ", "VIP", "TSA", "MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN", "JAN", "FEB",
    "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC", "EST", "EDT", "CST", "CDT",
    "MST", "MDT", "PST", "PDT", "UTC", "GMT", "AIR", "SEAT", "BAG", "FEE", "TAX", "PNR", "REF", "NON",
    "VIA", "AMP", "APP", "WEB", "BOX", "ANY", "OUT", "OFF", "NOW", "OUR", "HAS", "CAN", "MRS", "MSS",
    "TOP", "ADD", "PAY", "WAY", "DAY", "BUS", "CAR", "MPH", "KMH", "ETA", "ETD", "RES", "SKY",
}
AIRLINE_NAMES = {
    "united": "UA", "delta": "DL", "american": "AA", "southwest": "WN", "jetblue": "B6",
    "alaska": "AS", "spirit": "NK", "frontier": "F9", "allegiant": "G4", "hawaiian": "HA",
    "sun country": "SY", "breeze": "MX", "air canada": "AC", "westjet": "WS", "british airways": "BA",
    "lufthansa": "LH", "air france": "AF", "klm": "KL", "aer lingus": "EI", "virgin atlantic": "VS",
    "emirates": "EK", "qatar airways": "QR", "ryanair": "FR", "easyjet": "U2",
}
NAMED_FLIGHT_RE = re.compile(r"\bflight\s*(?:number|no\.?|#)?\s*:?\s*#?\s*(\d{1,4})\b", re.I)
# "United 1234", "Southwest Airlines flight #1234", as booking sites write them.
AIRLINE_FLIGHT_RE = re.compile(r"\b(" + "|".join(AIRLINE_NAMES) + r")(?:\s+air\s*lines|\s+airlines?|\s+airways)?"
                               r"(?:\s+flight)?\s*(?:number|no\.?)?\s*#?\s*(\d{1,4})\b(?![:/.,]\d)", re.I)


class ReadError(Exception):
    """A message for the person: nothing could be read."""


# ------------------------------------------------------------------ reading


def detect(text, name=""):
    """What kind of upload this is: "pdf", "binary", "ics", "eml", "html" or "text"."""
    name = (name or "").lower()
    head = text.lstrip()[:2000]
    if head.startswith("%PDF") or name.endswith(".pdf"):
        return "pdf"
    if name.endswith((".png", ".jpg", ".jpeg", ".heic", ".gif", ".webp", ".doc", ".docx", ".pages")) \
            or "\x00" in text[:4000]:
        return "binary"
    if "BEGIN:VCALENDAR" in head or name.endswith(".ics"):
        return "ics"
    if name.endswith(".eml") or (re.search(r"^(From|Subject|Date|MIME-Version|Received):", head, re.M | re.I)
                                 and re.search(r"^Content-Type:", text[:20000], re.M | re.I)):
        return "eml"
    if name.endswith((".html", ".htm")) or re.search(r"<(html|body|table|div)\b", head, re.I):
        return "html"
    return "text"


class _Text(html.parser.HTMLParser):
    """HTML to text, with a line break at each block element, and its JSON-LD scripts."""
    BLOCKS = {"p", "div", "br", "tr", "li", "table", "h1", "h2", "h3", "h4", "h5", "h6", "section", "td", "th"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.scripts, self.skip, self.ld = [], [], 0, None

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head", "title"):
            self.skip += 1
            if tag == "script" and "ld+json" in (dict(attrs).get("type") or "").lower():
                self.ld = []
        if tag in self.BLOCKS:
            self.out.append("\n" if tag not in ("td", "th") else " ")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head", "title"):
            self.skip = max(0, self.skip - 1)
            if tag == "script" and self.ld is not None:
                self.scripts.append("".join(self.ld))
                self.ld = None
        if tag in self.BLOCKS:
            self.out.append("\n")

    def handle_data(self, data):
        if self.ld is not None:
            self.ld.append(data)
        elif not self.skip:
            self.out.append(data)


def html_parts(markup):
    """(visible text, [JSON-LD script bodies])."""
    p = _Text()
    try:
        p.feed(markup)
        p.close()
    except Exception:  # noqa: BLE001 - a malformed email is still worth a text scan
        pass
    text = re.sub(r"[ \t\xa0]+", " ", "".join(p.out))
    return re.sub(r"\n\s*\n+", "\n", text), p.scripts


def email_parts(raw):
    """Split an email into its HTML, plain text, calendar parts and the names of files it can't read."""
    msg = email.message_from_string(raw, policy=email.policy.default)
    out = {"html": [], "text": [], "ics": [], "skipped": []}
    for part in msg.walk():
        if part.is_multipart():
            continue
        ctype, name = part.get_content_type(), part.get_filename() or ""
        if ctype == "text/calendar" or name.lower().endswith(".ics"):
            kind = "ics"
        elif ctype == "text/html":
            kind = "html"
        elif ctype == "text/plain" and not name:
            kind = "text"
        else:
            if name:
                out["skipped"].append(name)
            continue
        try:
            body = part.get_content()
        except (LookupError, ValueError):
            body = (part.get_payload(decode=True) or b"").decode("utf-8", "replace")
        if isinstance(body, bytes):
            body = body.decode("utf-8", "replace")
        out[kind].append(body)
    return out


# --------------------------------------------------------------- JSON-LD


def _walk(node):
    if isinstance(node, list):
        for x in node:
            yield from _walk(x)
    elif isinstance(node, dict):
        yield node
        for v in node.values():
            if isinstance(v, (dict, list)):
                yield from _walk(v)


def _types(node):
    t = node.get("@type") or ""
    return {x.split("/")[-1] for x in (t if isinstance(t, list) else [t]) if isinstance(x, str)}


def _code(node, *keys):
    if isinstance(node, str):
        return node
    if isinstance(node, dict):
        for k in keys:
            if isinstance(node.get(k), str) and node[k].strip():
                return node[k].strip()
    return None


def from_jsonld(scripts):
    """Flights from schema.org FlightReservation / Flight objects."""
    found = []
    for s in scripts:
        try:
            data = json.loads(s.strip().strip(";"))
        except ValueError:
            try:
                data = json.loads(html.unescape(s))
            except ValueError:
                continue
        for node in _walk(data):
            if "Flight" not in _types(node):
                continue
            number = str(node.get("flightNumber") or "").strip()
            airline = _code(node.get("airline") or node.get("provider"), "iataCode", "alternateName")
            parsed = flights.parse_flight(number) or (airline and flights.parse_flight(airline + number))
            if not parsed:
                continue
            dep = node.get("departureTime") or ""
            m = re.match(r"(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}:\d{2}))?", str(dep))
            found.append({"flight": parsed[0], "date": m.group(1) if m else None,
                          "time": m.group(2) if m else None,
                          "dep": _code(node.get("departureAirport"), "iataCode"),
                          "arr": _code(node.get("arrivalAirport"), "iataCode")})
    return found


# ------------------------------------------------------------------ calendar


def ics_events(text):
    """VEVENTs as dicts of property -> (params, value), lines unfolded and unescaped."""
    lines = re.sub(r"\r?\n[ \t]", "", text).splitlines()
    events, cur = [], None
    for line in lines:
        if line.strip().upper() == "BEGIN:VEVENT":
            cur = {}
        elif line.strip().upper() == "END:VEVENT":
            if cur is not None:
                events.append(cur)
            cur = None
        elif cur is not None and ":" in line:
            head, value = line.split(":", 1)
            name, *params = head.split(";")
            value = (value.replace("\\n", "\n").replace("\\N", "\n").replace("\\,", ",")
                     .replace("\\;", ";").replace("\\\\", "\\"))
            cur.setdefault(name.upper(), (dict(p.split("=", 1) for p in params if "=" in p), value))
    return events


def ics_start(params, value, dep, airports, tz_name):
    """(date, "HH:MM" or None) of a DTSTART, in the departure airport's time zone when known."""
    m = re.match(r"(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2})(?:\d{2})?)?(Z)?", value.strip())
    if not m:
        return None, None
    y, mo, d, hh, mm, utc = m.groups()
    if hh is None:
        return f"{y}-{mo}-{d}", None
    local = trips.airport_zone(trips.resolve_airport(dep, airports) if dep else None, airports, "") or None
    when = datetime.datetime(int(y), int(mo), int(d), int(hh), int(mm))
    if utc:
        when = when.replace(tzinfo=datetime.timezone.utc).astimezone(commands.zone(local or tz_name))
    elif params.get("TZID") and local:
        when = when.replace(tzinfo=commands.zone(params["TZID"].strip('"'))).astimezone(commands.zone(local))
    return when.date().isoformat(), when.strftime("%H:%M")


def from_ics(text, now, tz_name, airports):
    found = []
    for ev in ics_events(text):
        words = " \n".join(ev.get(k, ({}, ""))[1] for k in ("SUMMARY", "LOCATION", "DESCRIPTION"))
        hits = from_text(words, now, tz_name, airports)
        if not hits:
            continue
        f = hits[0]  # one flight per event; the rest of the text is usually its details
        if "DTSTART" in ev:
            date, clock = ics_start(*ev["DTSTART"], f.get("dep"), airports, tz_name)
            f["date"], f["time"] = date or f["date"], clock or f["time"]
        found.append(f)
    return found


# ---------------------------------------------------------------- free text


def find_dates(text, today):
    out = []
    for rx, order in DATE_PATTERNS:
        for m in rx.finditer(text):
            g = m.groups()
            try:
                if order == "ymd":
                    y, mo, d = int(g[0]), int(g[1]), int(g[2])
                elif order == "mdy":
                    mo, d, y = MONTHS[g[0][:3].lower()], int(g[1]), int(g[2]) if g[2] else None
                elif order == "dmy":
                    d, mo = int(g[0]), MONTHS[g[1][:3].lower()]
                    y = int(g[2]) if g[2] else None
                    y = y + 2000 if y and y < 100 else y
                else:  # 11/03/2026 is US order unless the first number can't be a month
                    a, b, y = int(g[0]), int(g[1]), int(g[2])
                    mo, d = (b, a) if a > 12 else (a, b)
                    y = y + 2000 if y < 100 else y
                day = datetime.date(y, mo, d) if y else trips.month_day(today, mo, d)
            except (ValueError, KeyError):
                continue
            if day:
                out.append((m.start(), day))
    return sorted(out)


def find_times(text):
    out = []
    for m in TIME_12.finditer(text):
        h = trips.to_24h(int(m.group(1)), int(m.group(2)), m.group(3).lower() + "m")
        if h:
            out.append((m.start(), "%02d:%02d" % h))
    if not out:  # only 24-hour times in the whole text
        out = [(m.start(), "%02d:%02d" % (int(m.group(1)), int(m.group(2)))) for m in TIME_24.finditer(text)]
    return sorted(out)


def find_flights(text):
    """(start, end, "UA1234") for each flight number in the text."""
    out = []
    for m in FLIGHT_RE.finditer(text):
        code, gap, num = m.groups()
        if (len(code) == 2 and code not in flights.AIRLINES) or (len(code) == 3 and code not in ICAO_AIRLINES):
            continue
        before, after = text[max(0, m.start() - 8):m.start()], text[m.end():m.end() + 2]
        if gap and re.search(r"\d:\d\d\s*$", before):  # "8:15 AM 11" isn't Aeroméxico 11
            continue
        if re.match(r"[:/.,]\d", after):  # part of a time, date or price
            continue
        parsed = flights.parse_flight(code + num)
        if parsed:
            out.append((m.start(), m.end(), parsed[0]))
    for m in AIRLINE_FLIGHT_RE.finditer(text):
        parsed = flights.parse_flight(AIRLINE_NAMES[m.group(1).lower()] + m.group(2))
        if parsed and not any(s < m.end() and m.start() < e for s, e, _ in out):
            out.append((m.start(), m.end(), parsed[0]))
    if not out:
        named = {code for name, code in AIRLINE_NAMES.items() if re.search(r"\b" + name + r"\b", text, re.I)}
        if len(named) == 1:  # "Southwest" in the header, "Flight #1234" below
            code = named.pop()
            for m in NAMED_FLIGHT_RE.finditer(text):
                parsed = flights.parse_flight(code + m.group(1))
                if parsed:
                    out.append((m.start(), m.end(), parsed[0]))
    return sorted(out)


def find_airports(text, airports):
    return [(m.start(), m.group()) for m in AIRPORT_RE.finditer(text)
            if m.group() not in NOT_AIRPORTS and m.group() in airports.iata]


def from_text(text, now, tz_name, airports):
    """Flights in free text, each with the date, time and airports nearest it."""
    today = datetime.datetime.fromtimestamp(now, commands.zone(tz_name)).date()
    hits = find_flights(text)
    if not hits:
        return []
    dates, times, codes = find_dates(text, today), find_times(text), find_airports(text, airports)
    inside = lambda items, lo, hi: [v for p, v in items if lo <= p < hi]  # noqa: E731
    # Do a flight's details follow its number ("UA 1234 · EWR → DEN") or lead up to it?
    # (Two airport codes before the first flight number: its details lead up to it.)
    after = len(inside(codes, max(0, hits[0][0] - 400), hits[0][0])) < 2
    found = []
    for i, (start, end, flight) in enumerate(hits):
        if after:
            lo, hi = start, hits[i + 1][0] if i + 1 < len(hits) else end + 500
        else:
            lo, hi = hits[i - 1][1] if i else max(0, start - 300), end
        # "UA 1234 · Tue, Nov 3" or a date heading somewhere above it
        eol = text.find("\n", end)
        soon = inside(dates, start, eol if eol >= 0 else len(text)) if after else []
        before = [d for p, d in dates if p < start]
        date = soon[0] if soon else before[-1] if before else (inside(dates, lo, hi) or [None])[0]
        ports = inside(codes, lo, hi)
        if after and len(ports) < 2:  # e.g. "EWR → DEN" on the line above the flight number
            ports = inside(codes, max(0, start - 200), hi)
        ports = [p for n, p in enumerate(ports) if n == 0 or p != ports[n - 1]]
        clock = inside(times, lo, hi)
        found.append({"flight": flight, "date": date.isoformat() if date else None,
                      "time": clock[0] if clock else None,
                      "dep": ports[0] if ports else None, "arr": ports[1] if len(ports) > 1 else None})
    return found


# -------------------------------------------------------------- the import


def dedupe(found):
    """One entry per flight and date, merging what each mention knew."""
    out = []
    for f in found:
        same = next((g for g in out if g["flight"] == f["flight"]
                     and (g["date"] == f["date"] or not g["date"] or not f["date"])), None)
        if same:
            for k, v in f.items():
                same[k] = same.get(k) or v
        else:
            out.append(dict(f))
    return out


def read(text, name, now, tz_name, airports):
    """(flights, where they came from, notes). Raises ReadError with a message."""
    kind = detect(text, name)
    if kind in ("pdf", "binary"):
        raise ReadError(f"🤷 {NOT_SUPPORTED}")
    notes = []
    if kind == "ics":
        return from_ics(text, now, tz_name, airports), "calendar file", notes
    if kind == "eml":
        parts = email_parts(text)
        if parts["skipped"]:
            notes.append("I can't read the attached " + ", ".join(parts["skipped"][:3])
                         + ", so this is from the email itself.")
        markup = [html_parts(h) for h in parts["html"]]
        ld = from_jsonld([s for _, scripts in markup for s in scripts])
        if ld:
            return ld, "the email's flight details", notes
        cal = [f for c in parts["ics"] for f in from_ics(c, now, tz_name, airports)]
        if cal:
            return cal, "the calendar invite in the email", notes
        body = "\n".join(t for t, _ in markup) or "\n".join(parts["text"])
        return from_text(body, now, tz_name, airports), "the email's text", notes
    if kind == "html":
        body, scripts = html_parts(text)
        ld = from_jsonld(scripts)
        if ld:
            return ld, "the page's flight details", notes
        return from_text(body, now, tz_name, airports), "the page's text", notes
    return from_text(text, now, tz_name, airports), "the text", notes


def sort_key(f):
    return (f.get("date") or "9999", f.get("time") or "99:99")


def journeys(found):
    """Split flights in date order into journeys: a flight leaving within a
    day of the one before, from where it landed, is a connection."""
    groups = []
    for f in sorted(found, key=sort_key):
        prev = groups[-1][-1] if groups else None
        if prev and f.get("date") and prev.get("date"):
            gap_days = (datetime.date.fromisoformat(f["date"]) - datetime.date.fromisoformat(prev["date"])).days
            same_place = not (f.get("dep") and prev.get("arr")) or f["dep"] == prev["arr"]
            near = gap_days == 0 or (gap_days == 1 and (f.get("time") or "99") < (prev.get("time") or "00"))
            if near and same_place:
                groups[-1].append(f)
                continue
        groups.append([f])
    return groups


def to_form(groups):
    """Values for the Add trip form, and notes about what didn't fit in it."""
    form, notes = {}, []
    if not groups:
        return form, notes
    out, ret = groups[0], groups[1] if len(groups) > 1 else []

    def put(prefix, f, with_date=True, with_airport=True):
        form[prefix + "flight"] = f["flight"]
        if with_date and f.get("date"):
            form[prefix + "date"] = f["date"]
        if f.get("time"):
            form[prefix + "time"] = f["time"]
        if with_airport and f.get("dep"):
            form[prefix + "airport"] = f["dep"]

    put("", out[0])
    for n, f in enumerate(out[1:trips.MAX_LEGS]):
        put(trips.form_prefix("", n), f, with_date=False, with_airport=False)
    if ret:
        put("ret_", ret[0])
        for n, f in enumerate(ret[1:trips.MAX_LEGS]):
            put(trips.form_prefix("ret_", n), f, with_date=False, with_airport=False)
    extra = out[trips.MAX_LEGS:] + ret[trips.MAX_LEGS:]
    if extra:
        notes.append(f"I can follow up to {trips.MAX_LEGS} flights in a row each way, so "
                     + ", ".join(f["flight"] for f in extra) + " were left out.")
    for g in groups[2:]:
        notes.append(f"{', '.join(f['flight'] for f in g)} looks like a separate trip; import or add it on its own.")
    if any(not f.get("date") for f in out + ret):
        notes.append("I couldn't find every date. Check them before adding.")
    return form, notes


def preview(text, name, now, tz_name, airports):
    """What the Web UI's Import shows: {"ok", "message", "flights", "form", "notes"}."""
    text = text or ""
    if detect("", name) in ("pdf", "binary"):  # the page doesn't upload these, just their name
        return {"ok": False, "message": f"🤷 {NOT_SUPPORTED}"}
    if not text.strip():
        return {"ok": False, "message": f"Paste your confirmation or choose a file. I can read {SUPPORTED}."}
    try:
        found, source, notes = read(text, name, now, tz_name, airports)
    except ReadError as e:
        return {"ok": False, "message": str(e)}
    found = dedupe(found)[:MAX_FLIGHTS]
    if not found:
        return {"ok": False, "message": "🤷 I couldn't find a flight number (like UA 1234) in that. "
                                        f"I can read {SUPPORTED}; {NOT_SUPPORTED}"}
    groups = journeys(found)
    form, more = to_form(groups)
    flat = [f for g in groups for f in g]
    return {"ok": True, "message": f"Found {len(flat)} flight{'s' * (len(flat) != 1)} in {source}.",
            "flights": flat, "form": form, "notes": notes + more}
