"""Trim the OurAirports CSV to the columns TailWatcher needs (build time only)."""

import csv
import sys

KEEP = {"small_airport", "medium_airport", "large_airport", "seaplane_base"}

src, dst = sys.argv[1], sys.argv[2]
with open(src, newline="", encoding="utf-8") as fin, open(dst, "w", newline="") as fout:
    out = csv.writer(fout)
    out.writerow(["ident", "name", "lat", "lon", "iata"])
    for r in csv.DictReader(fin):
        if r["type"] in KEEP:
            ident = r.get("icao_code") or r.get("gps_code") or r.get("local_code") or r["ident"]
            out.writerow([ident, r["name"], r["latitude_deg"], r["longitude_deg"], r.get("iata_code") or ""])
