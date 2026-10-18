import datetime
import os
import tempfile
import unittest

import commands
import trips

TZ = "America/New_York"
NY = commands.zone(TZ)


def ts(y, mo, d, h, mi=0):
    return datetime.datetime(y, mo, d, h, mi, tzinfo=NY).timestamp()


class FakeAirports:
    coords = {"KIAD": (38.9445, -77.4558, "Washington Dulles"),
              "LAS": (35.0, -100.0, "Some strip whose ident is LAS"),
              "KLAS": (36.08, -115.15, "Harry Reid"),
              "KORD": (41.9786, -87.9048, "Chicago O'Hare"),
              "KDEN": (39.8617, -104.6731, "Denver")}
    iata = {"IAD": "KIAD", "ORD": "KORD", "DEN": "KDEN", "LAS": "KLAS"}


AIR = FakeAirports()
NOON = ts(2026, 10, 20, 12)


class ParseTest(unittest.TestCase):
    def parse(self, text, now=NOON):
        return trips.parse_inbound(text, now, TZ, AIR)

    def test_manual_trip(self):
        t = self.parse("UA1234 N38473 dep 4:30pm from IAD")
        self.assertEqual((t["flight"], t["callsign"], t["date"]), ("UA1234", "UAL1234", "2026-10-20"))
        self.assertEqual(t["dep_time"], ts(2026, 10, 20, 16, 30))
        self.assertEqual(t["dep_airport"], "KIAD")
        self.assertEqual(t["inbound"]["tail"], "N38473")
        self.assertEqual(t["source"], "manual")

    def test_inbound_flight_number_and_split_time(self):
        t = self.parse("UA 1234 UA 567 at 4:30 pm")
        self.assertEqual(t["flight"], "UA1234")
        self.assertEqual((t["inbound"]["flight"], t["inbound"]["callsign"]), ("UA567", "UAL567"))
        self.assertIsNone(t["inbound"]["tail"])
        self.assertEqual(t["dep_time"], ts(2026, 10, 20, 16, 30))

    def test_morning_time_said_in_evening_is_tomorrow(self):
        t = self.parse("DL89 N123DL dep 9am", now=ts(2026, 10, 20, 21))
        self.assertEqual(t["date"], "2026-10-21")
        self.assertEqual(t["dep_time"], ts(2026, 10, 21, 9))

    def test_explicit_dates(self):
        self.assertEqual(self.parse("UA1234 N1 tomorrow 7:15am")["dep_time"], ts(2026, 10, 21, 7, 15))
        t = self.parse("UA1234 10/24 16:05")
        self.assertEqual((t["date"], t["dep_time"]), ("2026-10-24", ts(2026, 10, 24, 16, 5)))
        self.assertEqual(self.parse("UA1234 1/5", now=ts(2026, 12, 20, 12))["date"], "2027-01-05")

    def test_no_plane_means_aerodatabox(self):
        t = self.parse("UA1234")
        self.assertIsNone(t["inbound"])
        self.assertEqual(t["source"], "aerodatabox")
        self.assertIsNone(t["dep_time"])

    def test_three_letters_mean_iata(self):
        self.assertEqual(self.parse("UA1234 N1 from LAS")["dep_airport"], "KLAS")
        self.assertEqual(self.parse("UA1234 N1 from KLAS")["dep_airport"], "KLAS")

    def test_errors(self):
        self.assertIn("didn't understand", self.parse("AA2000 banana"))
        self.assertIn("doesn't look like a flight", self.parse("N38473 UA1234"))
        self.assertIn("didn't understand", self.parse("UA1234 N1 banana"))
        self.assertIn("don't know an airport", self.parse("UA1234 from ZZZ"))
        self.assertIn("isn't a time", self.parse("UA1234 25:00"))


def movement(icao, sched, revised=None):
    m = {"airport": {"icao": icao}, "scheduledTime": {"utc": sched, "local": "ignored"}}
    if revised:
        m["revisedTime"] = {"utc": revised, "local": "ignored"}
    return m


# Shaped like AeroDataBox's FlightContract (openapi-rapidapi-v1.json).
MY_FLIGHT = [{
    "number": "UA 1234", "callSign": "UAL1234", "status": "Expected",
    "departure": movement("KIAD", "2026-10-20 20:30Z", "2026-10-20 20:45Z"),
    "arrival": movement("KDEN", "2026-10-20 23:40Z"),
    "aircraft": {"reg": "N38473", "modeS": "A4F2B1", "model": "Boeing 737 MAX 9"},
}]
PLANE_DAY = [
    {"number": "UA 900", "callSign": "UAL900", "departure": movement("KDEN", "2026-10-20 12:00Z"),
     "arrival": movement("KORD", "2026-10-20 14:30Z"), "aircraft": {"reg": "N38473"}},
    {"number": "UA 567", "callSign": "UAL567", "departure": movement("KORD", "2026-10-20 17:05Z"),
     "arrival": movement("KIAD", "2026-10-20 19:10Z", "2026-10-20 19:25Z"), "aircraft": {"reg": "N38473"}},
    MY_FLIGHT[0],
]


class ResolveTest(unittest.TestCase):
    def fake_get(self, responses):
        calls = []

        def get(key, path, params, ua):
            calls.append((path, params))
            return responses[len(calls) - 1]
        return get, calls

    def test_finds_plane_inbound_leg_and_departure(self):
        trip = trips.parse_inbound("UA1234", NOON, TZ, AIR)
        get, calls = self.fake_get([MY_FLIGHT, PLANE_DAY])
        notes = trips.resolve(trip, "k", "ua", sleep=lambda s: None, get=get)
        self.assertEqual(notes, [])
        self.assertEqual(calls[0][0], "/flights/number/UA1234/2026-10-20")
        self.assertEqual(calls[0][1]["dateLocalRole"], "Departure")
        self.assertEqual(calls[1][0], "/flights/reg/N38473/2026-10-20")
        self.assertEqual(trip["dep_airport"], "KIAD")
        self.assertEqual(trip["dep_time"], ts(2026, 10, 20, 16, 45))  # revised time wins
        inb = trip["inbound"]
        self.assertEqual((inb["tail"], inb["flight"], inb["callsign"], inb["origin"]),
                         ("N38473", "UA567", "UAL567", "KORD"))
        self.assertEqual(inb["arr_time"], ts(2026, 10, 20, 15, 25))

    def test_plane_and_time_changes_are_reported(self):
        trip = trips.parse_inbound("UA1234", NOON, TZ, AIR)
        trips.resolve(trip, "k", "ua", sleep=lambda s: None, get=self.fake_get([MY_FLIGHT, PLANE_DAY])[0])
        trip["departed"] = True
        swapped = [dict(MY_FLIGHT[0], aircraft={"reg": "N77001"},
                        departure=movement("KIAD", "2026-10-20 20:30Z", "2026-10-20 21:30Z"))]
        notes = trips.resolve(trip, "k", "ua", sleep=lambda s: None, get=self.fake_get([swapped, []])[0])
        self.assertIn(("plane_change", "N38473", "N77001"), notes)
        self.assertEqual([n[0] for n in notes], ["dep_change", "plane_change"])
        self.assertFalse(trip["departed"])  # tracking restarts for the new plane
        msgs = trips.change_messages(trip, notes, TZ)
        self.assertIn("Now departs 5:30pm (later than 4:45pm)", msgs[0][1])
        self.assertIn("now flying N77001 (was N38473)", msgs[1][1])

    def test_no_data_yet_leaves_trip_alone(self):
        trip = trips.parse_inbound("UA1234", NOON, TZ, AIR)
        self.assertEqual(trips.resolve(trip, "k", "ua", get=self.fake_get([[]])[0]), [])
        self.assertIsNone(trip["inbound"])

    def test_month_ahead_trip_is_kept_until_its_date(self):
        trip = trips.parse_inbound("AA1234 11/14", NOON, TZ, AIR)
        self.assertEqual((trip["date"], trip["dep_time"]), ("2026-11-14", None))
        self.assertGreater(trips.expires_at(trip), ts(2026, 11, 15, 0))
        self.assertLess(trips.expires_at(trip), ts(2026, 11, 16, 12))
        trip["dep_time"] = ts(2026, 11, 14, 16)
        self.assertEqual(trips.expires_at(trip), ts(2026, 11, 14, 19))

    def test_check_schedule_scales_with_distance(self):
        trip = trips.parse_inbound("AA1234 11/24", NOON, TZ, AIR)   # 35 days out
        trip["dep_time"] = ts(2026, 11, 24, 16)
        self.assertEqual(trips.check_level(trip, NOON), "light")     # never checked
        trip["last_check"] = NOON
        self.assertIsNone(trips.check_level(trip, NOON + 3 * 86400))
        self.assertEqual(trips.check_level(trip, NOON + 7 * 86400), "light")   # weekly
        trip["last_check"] = ts(2026, 11, 14, 12)                     # 10 days out: daily
        self.assertIsNone(trips.check_level(trip, ts(2026, 11, 14, 20)))
        self.assertEqual(trips.check_level(trip, ts(2026, 11, 15, 13)), "light")
        # Last day: full checks at 24h, 6h, 2h and 45 min, each once.
        self.assertEqual(trips.check_level(trip, ts(2026, 11, 23, 16, 30)), "full")
        self.assertIsNone(trips.check_level(trip, ts(2026, 11, 23, 20)))
        self.assertEqual(trips.check_level(trip, ts(2026, 11, 24, 10, 30)), "full")
        self.assertEqual(trip["checkpoints"], [2, 0.75])

    def test_light_check_skips_the_plane_lookup(self):
        trip = trips.parse_inbound("UA1234", NOON, TZ, AIR)
        get, calls = self.fake_get([MY_FLIGHT])
        trips.resolve(trip, "k", "ua", full=False, get=get)
        self.assertEqual(len(calls), 1)
        self.assertEqual(trip["dep_time"], ts(2026, 10, 20, 16, 45))
        self.assertEqual(trip["arr_airport"], "KDEN")
        self.assertIsNone(trip["inbound"])

    def test_flight_disappears_and_comes_back(self):
        trip = trips.parse_inbound("UA1234", NOON, TZ, AIR)
        trips.resolve(trip, "k", "ua", full=False, get=self.fake_get([MY_FLIGHT])[0])
        notes = trips.resolve(trip, "k", "ua", full=False, get=self.fake_get([[]])[0])
        self.assertEqual(notes, [("missing", None, None)])
        self.assertTrue(trip["missing"])
        self.assertEqual(trips.resolve(trip, "k", "ua", full=False, get=self.fake_get([[]])[0]), [])  # said once
        notes = trips.resolve(trip, "k", "ua", full=False, get=self.fake_get([MY_FLIGHT])[0])
        self.assertEqual(notes, [("back", None, None)])
        self.assertFalse(trip["missing"])

    def test_never_listed_is_not_missing(self):
        trip = trips.parse_inbound("UA1234 11/14", NOON, TZ, AIR)
        self.assertEqual(trips.resolve(trip, "k", "ua", get=self.fake_get([[]])[0]), [])
        self.assertFalse(trip["missing"])

    def test_replacement_search(self):
        trip = trips.parse_inbound("UA1234", NOON, TZ, AIR)
        trips.resolve(trip, "k", "ua", full=False, get=self.fake_get([[dict(MY_FLIGHT[0], departure=dict(
            movement("KIAD", "2026-10-20 20:30Z"), scheduledTime={"utc": "2026-10-20 20:30Z",
                                                                 "local": "2026-10-20 16:30-04:00"}))]])[0])
        board = {"departures": [
            {"number": "UA 2200", "departure": movement("KIAD", "2026-10-20 20:40Z"),
             "arrival": movement("KORD", "2026-10-20 22:00Z")},            # wrong destination
            {"number": "DL 77", "departure": movement("KIAD", "2026-10-20 20:35Z"),
             "arrival": movement("KDEN", "2026-10-20 23:40Z")},            # wrong airline
            {"number": "UA 1999", "departure": movement("KIAD", "2026-10-20 22:30Z"),
             "arrival": movement("KDEN", "2026-10-21 01:30Z")},            # right, but further off
            {"number": "UA 5678", "departure": movement("KIAD", "2026-10-20 20:40Z"),
             "arrival": movement("KDEN", "2026-10-20 23:50Z")},            # the renumbered flight
        ]}
        get, calls = self.fake_get([board])
        rep = trips.find_replacement(trip, "k", "ua", get=get)
        self.assertEqual(calls[0][0], "/flights/airports/icao/KIAD/2026-10-20T13:30/2026-10-20T19:30")
        self.assertEqual(calls[0][1]["direction"], "Departure")
        self.assertEqual(rep, {"flight": "UA5678", "dep_time": ts(2026, 10, 20, 16, 40)})
        trip.update(missing=True, replacement=rep)
        msg = trips.change_messages(trip, [("missing", None, None)], TZ, number=2)[0]
        self.assertIn("disappeared", msg[0])
        self.assertIn("Looks like it's now UA5678, departing 4:40pm to KDEN", msg[1])
        self.assertIn('Reply "change 2 UA5678" to switch.', msg[1])

    def test_checkpoints_only_in_last_day(self):
        trip = trips.parse_inbound("UA1234", NOON, TZ, AIR)
        trip["dep_time"], trip["last_check"] = ts(2026, 10, 20, 16, 30), NOON - 3600
        self.assertEqual(trips.check_level(trip, ts(2026, 10, 20, 12, 30)), "full")  # 24h and 6h points
        self.assertEqual(trip["checkpoints"], [2, 0.75])


class ChangeTest(unittest.TestCase):
    def setUp(self):
        self.trip = trips.parse_inbound("UA1234 10/24 dep 4:30pm from IAD", NOON, TZ, AIR)
        self.trip.update(topic="t", source="aerodatabox", seen=True, inbound=None, plane_locked=False)

    def change(self, text):
        return trips.apply_change(self.trip, text, NOON, TZ, AIR)

    def test_renumber_needs_a_new_lookup_but_keeps_your_time(self):
        self.assertEqual(self.change("UA5678"), (None, True))
        t = self.trip
        self.assertEqual((t["flight"], t["callsign"], t["seen"]), ("UA5678", "UAL5678", False))
        self.assertEqual((t["date"], t["dep_time"]), ("2026-10-24", ts(2026, 10, 24, 16, 30)))

    def test_new_date_keeps_clock_time(self):
        self.change("10/27")
        self.assertEqual((self.trip["date"], self.trip["dep_time"]), ("2026-10-27", ts(2026, 10, 27, 16, 30)))

    def test_time_date_airport_and_plane(self):
        self.assertEqual(self.change("dep 5:10pm"), (None, False))
        self.assertEqual(self.trip["dep_time"], ts(2026, 10, 24, 17, 10))
        err, lookup = self.change("10/25 7am from ORD")
        self.assertTrue(lookup)
        self.assertEqual((self.trip["date"], self.trip["dep_time"], self.trip["dep_airport"]),
                         ("2026-10-25", ts(2026, 10, 25, 7), "KORD"))
        self.assertEqual(self.change("N38473"), (None, False))
        self.assertEqual(self.trip["inbound"]["tail"], "N38473")
        self.assertTrue(self.trip["plane_locked"])
        self.change("plane UA567")
        self.assertEqual(self.trip["inbound"]["flight"], "UA567")

    def test_nothing_to_change(self):
        self.assertIn("What should change", self.change("")[0])
        self.assertIn("didn't understand", self.change("banana")[0])


class SelectTest(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        for text in ("AA1234 11/14", "UA9 10/22", "AA1234 12/1"):
            t = trips.parse_inbound(text, NOON, TZ, AIR)
            t["topic"] = "sam"
            trips.add(t, self.path)

    def tearDown(self):
        os.unlink(self.path)

    def test_numbered_soonest_first(self):
        mine = trips.for_topic("sam", self.path)
        self.assertEqual([t["date"] for t in mine], ["2026-10-22", "2026-11-14", "2026-12-01"])
        listing = trips.describe_all(mine, TZ)
        self.assertTrue(listing.startswith("1. 🧳 UA9"))
        self.assertIn("2. 🧳 AA1234 · Sat Nov 14", listing)
        self.assertIn('"cancel 1"', listing)

    def test_select_by_number_flight_and_date(self):
        mine = trips.for_topic("sam", self.path)
        self.assertEqual(trips.select(mine, "2 dep 5pm", NOON, TZ)[0]["date"], "2026-11-14")
        self.assertEqual(trips.select(mine, "2 dep 5pm", NOON, TZ)[1], "dep 5pm")
        self.assertEqual(trips.select(mine, "UA 9", NOON, TZ)[0]["flight"], "UA9")
        self.assertIn("2 AA1234 trips", trips.select(mine, "AA1234", NOON, TZ)[1])
        self.assertEqual(trips.select(mine, "AA1234 12/1", NOON, TZ)[0]["date"], "2026-12-01")
        self.assertIn("no trip 7", trips.select(mine, "7", NOON, TZ)[1])

    def test_modify_change_and_cancel(self):
        def rename(trip, rest):
            trips.apply_change(trip, rest, NOON, TZ, AIR)
            return "ok", True
        self.assertEqual(trips.modify("sam", "2 AA5678", rename, NOON, TZ, self.path), "ok")
        self.assertEqual([t["flight"] for t in trips.for_topic("sam", self.path)], ["UA9", "AA5678", "AA1234"])
        self.assertEqual(trips.modify("sam", "1", lambda t, r: ("gone", False), NOON, TZ, self.path), "gone")
        self.assertEqual(len(trips.for_topic("sam", self.path)), 2)


class LiveWindowTest(unittest.TestCase):
    def test_only_followed_in_the_last_day(self):
        t = trips.parse_inbound("AA1234 N1 11/14 dep 4:05pm", NOON, TZ, AIR)
        self.assertFalse(trips.is_live(t, NOON))
        self.assertFalse(trips.is_live(t, ts(2026, 11, 13, 15)))
        self.assertTrue(trips.is_live(t, ts(2026, 11, 13, 16, 10)))
        undated = trips.parse_inbound("AA1234 N1 11/14", NOON, TZ, AIR)
        self.assertFalse(trips.is_live(undated, ts(2026, 11, 12, 12)))
        self.assertTrue(trips.is_live(undated, ts(2026, 11, 13, 12)))


class StepTest(unittest.TestCase):
    def setUp(self):
        self.trip = trips.parse_inbound("UA1234 N38473 dep 4:30pm from IAD", NOON, TZ, AIR)
        self.trip["topic"] = "t"
        self.routes = {"UAL900": "KORD", "UAL567": "KIAD"}

    def route(self, trip, cs):
        return self.routes.get(cs)

    def fix(self, lat, lon, alt=30000, gs=450, flight="UAL567"):
        return {"hex": "a4f2b1", "lat": lat, "lon": lon, "alt_baro": alt, "gs": gs, "flight": flight}

    def step(self, fix, now):
        return trips.step(self.trip, fix, now, AIR, TZ, self.route)

    def test_full_inbound_journey(self):
        # Earlier leg first: noted once, no "took off" yet.
        out = self.step(self.fix(40.5, -95.0, flight="UAL900"), ts(2026, 10, 20, 8))
        self.assertIn("earlier flight", out[0][0])
        self.assertEqual(self.step(self.fix(40.6, -94.0, flight="UAL900"), ts(2026, 10, 20, 8, 5)), [])
        self.assertFalse(self.trip["departed"])

        # The inbound leg takes off from Chicago (~500 nm out at 450 kt ≈ 67 + 8 min).
        out = self.step(self.fix(41.98, -87.80, alt=3000, gs=200), ts(2026, 10, 20, 13, 5))
        self.assertEqual(len(out), 1)
        self.assertIn("on its way", out[0][0])
        self.assertIn("as UAL567", out[0][1])
        self.assertIn("Your UA1234 departs 4:30pm", out[0][1])

        # Cruising, comfortably early: nothing new.
        self.assertEqual(self.step(self.fix(40.5, -82.0), ts(2026, 10, 20, 13, 40)), [])
        # Slowed by headwinds: due 15+ min later than announced, still not tight.
        out = self.step(self.fix(40.3, -80.5, gs=250), ts(2026, 10, 20, 14, 10))
        self.assertIn("running later", out[0][0])

        # Held up: now due ~4:10pm, 20 min before departure → tight.
        out = self.step(self.fix(40.0, -80.0, gs=150), ts(2026, 10, 20, 15, 0))
        self.assertIn("tight turnaround", out[0][0])
        out = self.step(self.fix(39.5, -78.5, gs=60), ts(2026, 10, 20, 15, 50))
        self.assertIn("may be delayed", out[0][0])
        self.assertEqual(out[0][2], 4)

        # Lands at Dulles.
        out = self.step(self.fix(38.95, -77.45, alt="ground", gs=10), ts(2026, 10, 20, 16, 20))
        self.assertIn("landed", out[0][0])
        self.assertIn("10 min after it lands", out[0][1])
        self.assertTrue(self.trip["landed"])
        self.assertEqual(self.step(self.fix(38.95, -77.45, alt="ground"), ts(2026, 10, 20, 16, 25)), [])

    def test_plane_already_at_airport(self):
        out = self.step(self.fix(38.95, -77.45, alt="ground", gs=0), ts(2026, 10, 20, 13))
        self.assertIn("already here", out[0][0])

    def test_lost_on_approach_counts_as_landed(self):
        self.step(self.fix(39.3, -77.9, alt=12000, gs=300), ts(2026, 10, 20, 15, 30))  # departed
        self.step(self.fix(39.0, -77.6, alt=3000, gs=180), ts(2026, 10, 20, 15, 45))    # low and close
        self.assertEqual(self.step(None, ts(2026, 10, 20, 15, 50)), [])
        out = self.step(None, ts(2026, 10, 20, 15, 58))
        self.assertIn("likely landed", out[0][0])


class WiringTest(unittest.TestCase):
    def test_watcher_imports_trips(self):
        # on_inbound()/track_trips() run inside run(); a missing import only shows up live.
        import tailwatcher
        self.assertIs(tailwatcher.trips, trips)
        self.assertEqual(commands.parse("inbound UA1234 N1")[:2], ("inbound", "UA1234 N1"))
        self.assertEqual(commands.parse("trips")[0], "trips")
        self.assertEqual(commands.parse("cancel 2")[:2], ("cancel", "2"))
        self.assertEqual(commands.parse("change 1 dep 5:10pm")[:2], ("change", "1 dep 5:10pm"))


class StorageTest(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.unlink(self.path)

    def tearDown(self):
        if os.path.exists(self.path):
            os.unlink(self.path)

    def test_add_replace_list_cancel(self):
        a = trips.parse_inbound("UA1234 N1 dep 4:30pm", NOON, TZ, AIR)
        a["topic"] = "sam"
        b = dict(a, topic="dad")
        trips.add(a, self.path)
        trips.add(b, self.path)
        trips.add(dict(a, inbound={"tail": "N2", "flight": None, "callsign": None}), self.path)  # same trip again
        self.assertEqual(len(trips.load(self.path)), 2)
        self.assertEqual(trips.for_topic("sam", self.path)[0]["inbound"]["tail"], "N2")
        self.assertEqual(trips.cancel("sam", "UA 1234", self.path), 1)
        self.assertEqual([t["topic"] for t in trips.load(self.path)], ["dad"])

    def test_expiry_and_summary(self):
        t = trips.parse_inbound("UA1234 N38473 dep 4:30pm from IAD", NOON, TZ, AIR)
        self.assertEqual(trips.expires_at(t), ts(2026, 10, 20, 19, 30))
        text = trips.describe(t, TZ)
        self.assertIn("🧳 UA1234 · Tue Oct 20, departs 4:30pm from KIAD", text)
        self.assertIn("Your plane: N38473", text)
        self.assertIn("No trips", trips.describe_all([], TZ))


if __name__ == "__main__":
    unittest.main()
