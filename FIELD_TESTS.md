# Field tests

Unit tests (`make test`) cover parsing and logic with sample data. This list is for confirming each feature on **real flights, real phones and real people**. Tick an item once it has worked on a live flight, and add a line to the **Log** at the bottom with the date and what happened (including misses).

Status: ✅ passed · ⚠️ partly / with issues · ❌ failed · blank = not tried yet

## 1. Tail number alerts

| # | Test | Status | Notes |
|---|---|---|---|
| T1 | Takeoff alert for a watched tail (airport with ground coverage → "departed") | ✅ | 2026-10-19 |
| T2 | "Is airborne" alert from a small field with no ground coverage | | |
| T3 | Landing alert ("landed") with Landing alerts on | ✅ | 2026-10-19 |
| T4 | "Likely landed" (dropped off radar below 3,000 ft) | ✅ | 2026-10-20 |
| T5 | No landing alert for a watcher with Landing alerts off | | |
| T6 | Tapping an alert opens the plane on the live map | ✅ | 2026-10-19 |
| T7 | A plane already flying when added alerts within seconds | | |
| T8 | Two watchers following the same tail both get one alert each (no duplicates) | | |
| T9 | Touch-and-go / pattern work doesn't spam alerts | | |

## 2. Airline flight number alerts

| # | Test | Status | Notes |
|---|---|---|---|
| F1 | IATA flight number (`UA1234`) alerts on departure and names the tail | | |
| F2 | Landing alert for a flight number | | |
| F3 | ICAO form (`UAL1234`) and spaced form (`DL 89`) work the same | | |
| F4 | Expiring entry (`for 2 days`, `until fri`) stops on time with "⌛ Stopped watching" | | |
| F5 | A flight that flies daily doesn't alert on days after expiry | | |
| F6 | Regional/codeshare flight (e.g. operated by SkyWest or Republic) | | Callsign may differ from the ticket |
| F7 | Non-US airline (callsign differs, e.g. Ryanair) | | |

## 3. Trips: where's my plane?

| # | Test | Status | Notes |
|---|---|---|---|
| R1 | Manual trip (`inbound UA1234 N38473 dep 4:30pm`) | | |
| R2 | AeroDataBox trip (`inbound UA1234 11/14`) finds departure time | | Sample responses not yet checked against a live key |
| R3 | AeroDataBox assigns the plane in the last day or two | | |
| R4 | ✈️ "your plane is on its way" with a sensible arrival estimate | | |
| R5 | 🧳 "on an earlier flight" when the plane does another leg first | | |
| R6 | ⏳ / ⚠️ tight-connection warnings (45 / 20 min) | | |
| R7 | 🧳 "running later" (15+ min later than announced) | | |
| R8 | 🛬 "your plane landed" / "already here" | | |
| R9 | Plane swap reported by AeroDataBox | | |
| R10 | Departure time change reported | | |
| R11 | Renumbered/cancelled flight → suggested `change`, applied by text | | |
| R12 | Trip clears itself after departure | | |
| R13 | AeroDataBox requests for a month-out trip stay around 20 | | Check the RapidAPI dashboard |
| R14 | Outbound **and** return trips for the same journey both work | ⏳ | Booked trip next month |
| R15 | Round trip entered in one step (`inbound … return …` or the Return flight row): both legs listed together, return leaves from the outbound's destination, `share`/`cancel` cover both (`only` for one) | | 0.16.0 |

## 4. Sharing and other people's phones

| # | Test | Status | Notes |
|---|---|---|---|
| S1 | Invite link opened on someone else's phone (outside the home network) | | |
| S2 | They subscribe in ntfy and receive an alert | | |
| S3 | Expired / cancelled invite shows the right message | | |
| S4 | Someone adds a plane for themselves by text in their topic and gets alerts | | |
| S5 | Someone adds a plane for another watcher from the dashboard; that person gets alerts | | |
| S6 | `share 1 Name` → they get the 📣 note, then departure and landing on the day | | |
| S7 | Shared watcher gets time-change / disappeared notes but no inbound-plane updates | | |
| S8 | Cancelling a shared trip tells them | | |
| S9 | iPhone receives alerts promptly (ntfy.sh) | | |
| S10 | Android receives alerts promptly (battery Unrestricted) | | |

## 5. Text commands

| # | Test | Status | Notes |
|---|---|---|---|
| C1 | `list` shows the list, what's airborne and time left | | |
| C2 | `remove`, `add … nickname` | | |
| C3 | `info N12345` (FAA, photo, live position) | | |
| C4 | `info UA1234` while the flight is in the air | | |
| C5 | `trips`, `change N …`, `cancel N` | | |
| C6 | `help` | | |

## 6. Dashboard and setup

| # | Test | Status | Notes |
|---|---|---|---|
| D1 | Fresh install on ntfy.sh with no other packages | | |
| D2 | "Set up NTFY for me" on a local NTFY (open and login modes) | | |
| D3 | Web UI password on/off, Show/Reset password actions | | |
| D4 | Add/edit/remove watchers, aircraft and trips from the dashboard | | |
| D5 | Board theme flips tiles on a live change | | |
| D6 | System panel shows a real ntfy / feed / AeroDataBox problem | | |
| D7 | Survives a StartOS restart and a package update with config, trips and history intact | | |

## 7. Reliability (over weeks)

| # | Test | Status | Notes |
|---|---|---|---|
| L1 | No missed takeoffs over a month of normal use | | |
| L2 | No "too many requests" from adsb.fi / adsb.lol with the usual list size | | |
| L3 | Fallback to the other feed when one is down | | |
| L4 | ntfy outage → alerts retried, no duplicates | | |

## Ideas from testing

- **Itineraries:** enter the outbound and return flights together (and share both at once) instead of two separate trips. From the 2026-10-19 test. Done in 0.16.0 (round trips); test as R15, e.g. by linking next month's two trips with `return 1 …`.

## Log

- **2026-10-19:** Watched a tail number; got the takeoff alert and the landing alert, both accurate (T1, T3). Tapping the alert opened the plane on the live map (T6). Started tracking an outbound and return commercial flight for next month (R14).
- **2026-10-20:** N806X (CRJ7, callsign SCAN6) dropped off radar on final into KECP; got "likely landed · 3 nm from KECP – Northwest Florida Beaches Intl · 625 ft · 137 kt · hdg 340° · Signal lost at low altitude" with the live-map link (T4).
