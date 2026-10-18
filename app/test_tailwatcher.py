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
        self.cfg.update(ntfy_topic="planes", map_links="both")

    def test_message_fields(self):
        fix = ac(1800, lat=39.42, lon=-77.38, gs=105, track=270, t="C172", flight="N12345 ")
        m = tw.build_message(self.cfg, {"tail": "N12345", "label": "Dad"}, fix, "departed", self.airports)
        self.assertEqual(m["title"], "N12345 (Dad) departed")
        self.assertIn("KFDK", m["message"])
        self.assertIn("1,800 ft · 105 kt · hdg 270°", m["message"])
        self.assertIn("C172", m["message"])
        self.assertNotIn("N12345", m["message"])  # callsign == tail is not repeated
        self.assertEqual(m["click"], "https://globe.adsbexchange.com/?icao=a1b2c3")
        self.assertEqual([a["label"] for a in m["actions"]], ["ADS-B Exchange", "adsb.lol"])

    def test_no_airport_at_cruise(self):
        fix = ac(34000, lat=39.42, lon=-77.38)
        m = tw.build_message(self.cfg, {"tail": "N12345", "label": ""}, fix, "airborne", self.airports)
        self.assertNotIn("KFDK", m["message"])
        self.assertTrue(m["message"].startswith("34,000 ft"))

    def test_tail_normalization(self):
        self.assertEqual(tw.normalize_tail(" n-123ab "), "N123AB")


if __name__ == "__main__":
    unittest.main()
