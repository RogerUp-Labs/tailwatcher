"""Flight numbers: tell them apart from tail numbers and turn them into callsigns.

Airlines sell tickets under an IATA flight number ("UA1234", "DL 89") but
broadcast an ICAO callsign over ADS-B ("UAL1234", "DAL89"), which is what
the feeds' `flight` field holds. The aircraft (tail) flying it is only
assigned on the day, so a trip is watched by callsign.
"""

import re

# IATA airline code → ICAO callsign prefix. Any 3-letter ICAO code is also
# accepted as typed ("UAL1234"), so this only needs the codes people type.
AIRLINES = {
    # United States
    "AA": "AAL", "UA": "UAL", "DL": "DAL", "WN": "SWA", "B6": "JBU", "AS": "ASA",
    "NK": "NKS", "F9": "FFT", "G4": "AAY", "HA": "HAL", "SY": "SCX", "MX": "MXY",
    "XP": "VXP", "QX": "QXE", "OO": "SKW", "YX": "RPA", "9E": "EDV", "MQ": "ENY",
    "OH": "JIA", "YV": "ASH", "ZW": "AWI", "PT": "PDT", "G7": "GJS", "C5": "UCA",
    "5X": "UPS", "FX": "FDX",
    # Canada, Mexico, Latin America
    "AC": "ACA", "WS": "WJA", "TS": "TSC", "PD": "POE", "F8": "FLE", "QK": "JZA",
    "AM": "AMX", "Y4": "VOI", "VB": "VIV", "AV": "AVA", "CM": "CMP", "LA": "LAN",
    "JJ": "TAM", "G3": "GLO", "AD": "AZU", "AR": "ARG",
    # Europe
    "BA": "BAW", "VS": "VIR", "AF": "AFR", "KL": "KLM", "LH": "DLH", "LX": "SWR",
    "OS": "AUA", "SN": "BEL", "IB": "IBE", "VY": "VLG", "UX": "AEA", "TP": "TAP",
    "AZ": "ITY", "EI": "EIN", "FR": "RYR", "U2": "EZY", "W6": "WZZ", "SK": "SAS",
    "AY": "FIN", "DY": "NOZ", "LO": "LOT", "TK": "THY", "PC": "PGT", "LS": "EXS",
    "EW": "EWG", "A3": "AEE", "FI": "ICE",
    # Middle East and Africa
    "EK": "UAE", "QR": "QTR", "EY": "ETD", "SV": "SVA", "RJ": "RJA", "LY": "ELY",
    "GF": "GFA", "WY": "OMA", "MS": "MSR", "ET": "ETH", "SA": "SAA", "KQ": "KQA",
    # Asia-Pacific
    "SQ": "SIA", "CX": "CPA", "JL": "JAL", "NH": "ANA", "KE": "KAL", "OZ": "AAR",
    "CI": "CAL", "BR": "EVA", "CA": "CCA", "MU": "CES", "CZ": "CSN", "HU": "CHH",
    "AI": "AIC", "6E": "IGO", "TG": "THA", "MH": "MAS", "GA": "GIA", "PR": "PAL",
    "VN": "HVN", "QF": "QFA", "VA": "VOZ", "NZ": "ANZ", "FJ": "FJI",
}

IATA_RE = re.compile(r"^([A-Z0-9]{2})0*(\d{1,4})$")
# ICAO callsigns are usually code + number, but some airlines (Ryanair,
# easyJet) add letters: RYR5TM, EZY12AB.
ICAO_RE = re.compile(r"^([A-Z]{3})0*(\d{1,4}[A-Z]{0,2})$")
N_NUMBER_RE = re.compile(r"^N[1-9][0-9A-Z]{0,4}$")


def compact(text):
    return re.sub(r"[^A-Z0-9]", "", (text or "").upper())


def parse_flight(text):
    """Return (display, callsign) for a flight number, or None if it isn't one.

    The rule, in order:
    1. Anything with a dash is a registration (G-ABCD, B-1234).
    2. US N-numbers (N + digit…) are registrations, even though "N1" could
       otherwise read as a 2-character airline code.
    3. A 3-letter ICAO code + 1–4 digits (+ up to 2 letters) is a callsign.
    4. A known 2-character IATA code + 1–4 digits is a flight number.
       Unknown codes stay registrations, so JA8089 and HL7xxx still work.
    Leading zeros are dropped (DL 089 → DL89 / DAL89), as on ADS-B.
    """
    if "-" in (text or "").strip("-"):
        return None
    s = compact(text)
    if N_NUMBER_RE.match(s):
        return None
    m = ICAO_RE.match(s)
    if m:
        cs = m.group(1) + m.group(2)
        return cs, cs
    m = IATA_RE.match(s)
    if m and m.group(1) in AIRLINES:
        return m.group(1) + m.group(2), AIRLINES[m.group(1)] + m.group(2)
    return None


def callsign(display):
    """The ADS-B callsign for a stored flight number (falls back to itself)."""
    parsed = parse_flight(display)
    return parsed[1] if parsed else compact(display)


def matches(ac, cs):
    """Does a feed record carry this callsign? (`flight` is space-padded.)"""
    return (ac.get("flight") or "").strip().upper() == cs
