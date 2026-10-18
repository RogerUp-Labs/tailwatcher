import unittest

import tailwatcher as tw

T0 = 1_000_000


def ac(alt, **kw):
    return {"hex": "a1b2c3", "r": "N12345", "alt_baro": alt, **kw}


class ObserveTest(unittest.TestCase):
    def test_ground_to_air_is_departure(self):
        st, ev = tw.observe({}, ac("ground"), T0)
        self.assertIsNone(ev)
        st, ev = tw.observe(st, ac(800), T0 + 60)
        self.assertEqual(ev, "departed")

    def test_first_sighting_airborne(self):
        _, ev = tw.observe({}, ac(2500), T0)
        self.assertEqual(ev, "airborne")

    def test_steady_flight_is_quiet(self):
        st, _ = tw.observe({}, ac(2500), T0)
        st, ev = tw.observe(st, ac(4500), T0 + 60)
        self.assertIsNone(ev)
        st, ev = tw.observe(st, None, T0 + 120)  # brief dropout
        self.assertIsNone(ev)
        _, ev = tw.observe(st, ac(5000), T0 + 180)
        self.assertIsNone(ev)

    def test_reappearing_after_gap_is_new_flight(self):
        st, _ = tw.observe({}, ac(2500), T0)
        st, ev = tw.observe(st, None, T0 + tw.GAP_SECONDS + 60)
        self.assertEqual(ev, "lost_low")
        _, ev = tw.observe(st, ac(1500), T0 + 3 * 3600)
        self.assertEqual(ev, "airborne")

    def test_lost_high_is_not_landing(self):
        st, _ = tw.observe({}, ac(35000), T0)
        _, ev = tw.observe(st, None, T0 + tw.GAP_SECONDS + 60)
        self.assertIsNone(ev)

    def test_landing(self):
        st, _ = tw.observe({}, ac(1200), T0)
        _, ev = tw.observe(st, ac("ground"), T0 + 60)
        self.assertEqual(ev, "landed")

    def test_restart_mid_flight_does_not_realert(self):
        st, _ = tw.observe({}, ac(5000), T0)
        _, ev = tw.observe(st, ac(5200), T0 + 300)  # state reloaded from disk
        self.assertIsNone(ev)


class MessageTest(unittest.TestCase):
    def setUp(self):
        self.airports = tw.Airports("/nonexistent")
        self.airports.rows = [("KFDK", "Frederick Municipal Airport", 39.4176, -77.3743)]
        self.cfg = tw.load_config("/nonexistent")
        self.cfg.update(map_links="both")
        self.watcher = {"name": "Sam", "topic": "tailwatcher_sam", "aircraft": [],
                        "notify_landing": False, "priority": "high"}

    def test_message_fields(self):
        fix = ac(1800, lat=39.42, lon=-77.38, gs=105, track=270, t="C172", flight="N12345 ")
        m = tw.build_message(self.cfg, self.watcher, "N12345", "Dad", fix, "departed", self.airports)
        self.assertEqual(m["title"], "N12345 (Dad) departed")
        self.assertIn("KFDK", m["message"])
        self.assertIn("1,800 ft · 105 kt · hdg 270°", m["message"])
        self.assertIn("C172", m["message"])
        self.assertNotIn("N12345", m["message"])  # callsign == tail is not repeated
        self.assertEqual(m["click"], "https://globe.adsbexchange.com/?icao=a1b2c3")
        self.assertEqual([a["label"] for a in m["actions"]], ["ADS-B Exchange", "adsb.lol"])
        self.assertEqual(m["topic"], "tailwatcher_sam")
        self.assertEqual(m["priority"], 4)

    def test_no_airport_at_cruise(self):
        fix = ac(34000, lat=39.42, lon=-77.38)
        m = tw.build_message(self.cfg, self.watcher, "N12345", "", fix, "airborne", self.airports)
        self.assertNotIn("KFDK", m["message"])
        self.assertTrue(m["message"].startswith("34,000 ft"))

    def test_flight_title_names_the_aircraft(self):
        fix = ac(2500, r="N38473", flight="UAL1234 ", t="B39M")
        m = tw.build_message(self.cfg, self.watcher, "UA1234", "", fix, "departed", self.airports, "flight")
        self.assertEqual(m["title"], "UA1234 (N38473) departed")
        self.assertIn("B39M · UAL1234", m["message"])
        m = tw.build_message(self.cfg, self.watcher, "UA1234", "Mom", fix, "airborne", self.airports, "flight")
        self.assertEqual(m["title"], "UA1234 (Mom, N38473) is airborne")

    def test_tail_normalization(self):
        self.assertEqual(tw.normalize_tail(" n-123ab "), "N123AB")


class ConfigTest(unittest.TestCase):
    def write(self, data):
        import json, tempfile
        f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump(data, f)
        f.close()
        return f.name

    def test_legacy_config_becomes_one_watcher(self):
        cfg = tw.load_config(self.write({
            "aircraft": [{"tail": "n-12345", "label": "Dad"}],
            "ntfyTopic": "tailwatcher", "ntfyToken": "tk_x",
            "notifyLanding": True, "priority": "high",
        }))
        self.assertEqual(len(cfg["watchers"]), 1)
        w = cfg["watchers"][0]
        self.assertEqual((w["name"], w["topic"], w["priority"]), ("Me", "tailwatcher", "high"))
        self.assertTrue(w["notify_landing"])
        self.assertEqual(w["aircraft"], [{"tail": "N12345", "label": "Dad", "kind": "tail",
                                          "expires": None, "key": "N12345"}])
        self.assertEqual(cfg["ntfy_token"], "tk_x")

    def test_shared_tail_polled_once_for_both_watchers(self):
        cfg = tw.load_config(self.write({"watchers": [
            {"name": "Sam", "topic": "tailwatcher_sam",
             "aircraft": [{"tail": "N12345", "label": ""}, {"tail": "N628TS", "label": ""}]},
            {"name": "Dad", "topic": "tailwatcher_dad",
             "aircraft": [{"tail": "N12345", "label": "Sam's plane"}]},
            {"name": "Empty", "topic": "tailwatcher_x", "aircraft": []},
        ]}))
        # A watcher with no aircraft yet is kept so they can text a tail to add one.
        self.assertEqual([w["name"] for w in cfg["watchers"]], ["Sam", "Dad", "Empty"])
        subs = tw.subscriptions(cfg)
        self.assertEqual(list(subs), ["N12345", "N628TS"])
        self.assertEqual([(w["name"], a["label"]) for w, a in subs["N12345"]],
                         [("Sam", ""), ("Dad", "Sam's plane")])

    def test_flights_share_a_callsign_and_expired_entries_are_skipped(self):
        cfg = tw.load_config(self.write({"watchers": [
            {"name": "Sam", "topic": "tailwatcher_sam", "aircraft": [
                {"tail": "UA1234", "label": "", "kind": "flight", "expires": None},
                {"tail": "DL089", "label": "", "kind": "flight", "expires": T0 - 1}]},
            {"name": "Dad", "topic": "tailwatcher_dad", "aircraft": [
                {"tail": "UAL1234", "label": "Sam", "kind": "flight", "expires": T0 + 60}]},
        ]}), now=T0)
        subs = tw.subscriptions(cfg)
        self.assertEqual(list(subs), ["UAL1234"])
        self.assertEqual([a["tail"] for _, a in subs["UAL1234"]], ["UA1234", "UAL1234"])


class MatchTest(unittest.TestCase):
    def test_callsign_match_uses_trimmed_flight(self):
        data = {"ac": [
            {"hex": "1", "flight": "UAL12345", "r": "N1"},
            {"hex": "2", "flight": "UAL1234 ", "r": "N38473", "lat": 39.0, "seen": 2},
            {"hex": "3", "r": "N2"},
        ]}
        self.assertEqual(tw.pick_match(data, "UAL1234", "flight")["r"], "N38473")
        self.assertIsNone(tw.pick_match(data, "UAL123", "flight"))
        self.assertEqual(tw.pick_match(data, "N2")["hex"], "3")


class BatchPollTest(unittest.TestCase):
    def test_one_request_per_25_keys(self):
        urls = []

        def get(url):
            urls.append(url)
            return {"ac": [{"r": "N2", "hex": "a2", "alt_baro": 3000, "lat": 1, "lon": 2},
                           {"r": "N9", "flight": "UAL567  ", "hex": "a9", "alt_baro": 9000}]}
        wanted = {("tail", f"N{i}") for i in range(1, 31)} | {("flight", "UAL567")}
        out = tw.fetch_many("adsb.fi", wanted, sleep=lambda s: None, get=get)
        self.assertEqual(len(urls), 3)                       # 30 tails -> 2 requests, 1 flight -> 1
        self.assertTrue(urls[0].startswith("https://opendata.adsb.fi/api/v2/registration/N1,N10,"))
        self.assertIn("/api/v2/callsign/UAL567", urls[2])
        self.assertEqual(out["N2"]["hex"], "a2")
        self.assertIsNone(out["N3"])                          # asked about, not seen
        self.assertEqual(out["UAL567"]["hex"], "a9")
        self.assertEqual(len(out), 31)

    def test_falls_back_to_the_other_feed(self):
        import urllib.error
        calls = []

        def fetch(src, wanted):
            calls.append(src)
            if src == "adsb.lol":
                raise urllib.error.HTTPError("u", 429, "Too Many Requests", {}, None)
            return {"N1": None}
        fixes, err, limited = tw.poll_all("adsb.lol", {("tail", "N1")}, fetch=fetch)
        self.assertEqual((calls, fixes, limited), (["adsb.lol", "adsb.fi"], {"N1": None}, False))
        self.assertIn("adsb.lol: too many requests", err)

        def both_fail(src, wanted):
            raise urllib.error.HTTPError("u", 429, "Too Many Requests", {}, None)
        fixes, err, limited = tw.poll_all("adsb.fi", {("tail", "N1")}, fetch=both_fail)
        self.assertEqual((fixes, limited), ({}, True))


if __name__ == "__main__":
    unittest.main()
