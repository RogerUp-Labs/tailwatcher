"""Trim the OurAirports CSV to the columns TailWatcher needs (build time only).

usage: trim_airports.py airports-full.csv airports.csv [tz.json]

city/region/size let the dashboard say where a plane is ("40 nm NE of
Denver, CO"). OurAirports has no time zones, so tz.json (mwgg/Airports: ICAO -> {iata, lat,
lon, tz}) supplies them: matched by ICAO, then IATA, else the nearest airport
within NEAR_NM that has one (small fields share their neighbours' zone).
"""

import csv
import json
import math
import sys

KEEP = {"small_airport", "medium_airport", "large_airport", "seaplane_base"}
NEAR_NM = 150
STATE_COUNTRIES = {"US", "CA", "AU"}


def nm(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * 3440.065 * math.asin(math.sqrt(min(1.0, a)))


class Zones:
    def __init__(self, path):
        self.by_icao, self.by_iata, self.grid = {}, {}, {}
        if not path:
            return
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for icao, a in data.items():
            tz = a.get("tz")
            if not tz:
                continue
            self.by_icao[icao] = tz
            if a.get("iata"):
                self.by_iata.setdefault(a["iata"], tz)
            try:
                lat, lon = float(a["lat"]), float(a["lon"])
            except (KeyError, TypeError, ValueError):
                continue
            self.grid.setdefault((math.floor(lat), math.floor(lon)), []).append((lat, lon, tz))

    def find(self, idents, iata, lat, lon):
        for ident in idents:
            if ident in self.by_icao:
                return self.by_icao[ident]
        if iata in self.by_iata:
            return self.by_iata[iata]
        best, best_d = "", NEAR_NM
        r = 3 if abs(lat) < 60 else 6  # degrees of longitude shrink near the poles
        for dy in range(-3, 4):
            for dx in range(-r, r + 1):
                for alat, alon, tz in self.grid.get((math.floor(lat) + dy, (math.floor(lon) + dx + 180) % 360 - 180), ()):
                    d = nm(lat, lon, alat, alon)
                    if d < best_d:
                        best, best_d = tz, d
        return best


def main(src, dst, tz_path=None):
    zones = Zones(tz_path)
    with open(src, newline="", encoding="utf-8") as fin, open(dst, "w", newline="") as fout:
        out = csv.writer(fout)
        out.writerow(["ident", "name", "lat", "lon", "iata", "tz", "city", "region", "size"])
        for r in csv.DictReader(fin):
            if r["type"] in KEEP:
                ident = r.get("icao_code") or r.get("gps_code") or r.get("local_code") or r["ident"]
                iata = r.get("iata_code") or ""
                lat, lon = float(r["latitude_deg"]), float(r["longitude_deg"])
                tz = zones.find((ident, r["ident"]), iata, lat, lon)
                country = r.get("iso_country") or ""
                # "US-CO" -> "CO" where people name states; elsewhere the country code.
                region = (r.get("iso_region") or "").split("-")[-1] if country in STATE_COUNTRIES else country
                out.writerow([ident, r["name"], r["latitude_deg"], r["longitude_deg"], iata, tz,
                              r.get("municipality") or "", region, r["type"][0]])


if __name__ == "__main__":
    main(*sys.argv[1:4])
