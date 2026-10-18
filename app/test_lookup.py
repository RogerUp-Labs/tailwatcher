import os
import unittest

import commands
import lookup

HERE = os.path.dirname(os.path.abspath(__file__))


class FakeAirports:
    rows = [("KFDK", "Frederick Municipal Airport", 39.4176, -77.3743),
            ("MD21", "Private strip", 39.54, -77.49)]  # closer, but not a landmark

    def nearest(self, lat, lon, max_nm=15):
        return None  # lookup.landmark() does its own search over rows


class FaaPageTest(unittest.TestCase):
    def test_parses_real_record(self):
        with open(os.path.join(HERE, "testdata", "faa_N17169.html")) as f:
            faa = lookup.parse_faa(f.read())
        self.assertEqual(faa["Name"], "UNITED AIRLINES INC")
        self.assertEqual(faa["Model"], "EMB-145XR")
        self.assertEqual(faa["Mfr Year"], "2004")
        self.assertEqual(faa["Mode S Code (Base 16 / Hex)"], "A12030")
        self.assertEqual((faa["City"], faa["State"]), ("CHICAGO", "ILLINOIS"))

    def test_page_without_record_is_empty(self):
        self.assertEqual(lookup.parse_faa("<html><body>No record</body></html>"), {})


class FormattingTest(unittest.TestCase):
    def test_titlecase_keeps_entity_suffixes(self):
        self.assertEqual(lookup.titlecase("LUKE AIRLINES LLC"), "Luke Airlines LLC")
        self.assertEqual(lookup.titlecase("UNITED AIRLINES INC"), "United Airlines Inc")

    def test_engine_names(self):
        self.assertEqual(lookup.describe_engine({"Engine Manufacturer": "CONT MOTOR", "Engine Model": "IO-360 SER",
                                                 "Engine Type": "Reciprocating"}), "Continental IO-360 (piston)")
        self.assertEqual(lookup.describe_engine({"Engine Manufacturer": "ROLLS-ROYC", "Engine Model": "AE3007 SER",
                                                 "Engine Type": "Turbo-fan"}), "Rolls-Royce AE3007 (turbofan)")
        self.assertEqual(lookup.describe_engine({"Engine Manufacturer": "CFM INTL.", "Engine Model": "CFM56-7B24/3",
                                                 "Engine Type": "Turbo-fan"}), "CFM56-7B24/3 (turbofan)")
        self.assertEqual(lookup.describe_engine({}), "")

    def test_compass(self):
        self.assertEqual(lookup.compass(39.0, -77.0, 40.0, -77.0), "N")
        self.assertEqual(lookup.compass(39.0, -77.0, 38.5, -77.6), "SW")


class BuildReplyTest(unittest.TestCase):
    FAA = {"Name": "SMITH JOHN Q", "Type Registration": "Individual", "City": "FREDERICK",
           "State": "MARYLAND", "Street": "1 SECRET LANE", "Manufacturer Name": "CESSNA",
           "Model": "172S", "Mfr Year": "2004", "Status": "Valid", "Expiration Date": "12/31/2028",
           "Mode S Code (Base 16 / Hex)": "A1B2C3"}

    def test_full_reply(self):
        found = {
            "faa": self.FAA,
            "hexdb": {"Manufacturer": "Cessna", "Type": "172S Skyhawk SP"},
            "live": {"hex": "a1b2c3", "alt_baro": 4500, "gs": 110, "lat": 39.55, "lon": -77.5,
                     "flight": "N12345", "dbFlags": 1 | 8},
            "photo": {"photographer": "A. Spotter", "link": "https://planespotters.net/photo/1",
                      "thumbnail_large": {"src": "https://t.plnspttrs.net/1.jpg"}},
            "hexcode": "a1b2c3",
        }
        r = lookup.build_reply("N12345", found, FakeAirports(), watching=False)
        msg = r["message"]
        self.assertEqual(r["title"], "🔎 N12345")
        self.assertTrue(msg.startswith("Cessna 172S Skyhawk SP (2004)"))
        self.assertIn("Owner: Smith John Q (individual) · Frederick, Maryland", msg)
        self.assertNotIn("SECRET", msg.upper())  # no street address in the reply
        self.assertIn("Live: ✈️ 4,500 ft · 110 kt · 10 nm NW of KFDK", msg)
        self.assertIn("🎖 military", msg)
        self.assertIn("LADD", msg)
        self.assertIn("Send N12345 to watch it.", msg)
        self.assertIn("📷 A. Spotter / planespotters.net", msg)
        self.assertEqual(r["attach"], "https://t.plnspttrs.net/1.jpg")
        self.assertEqual([a["label"] for a in r["actions"]], ["ADS-B Exchange", "FAA record", "Photo"])
        self.assertEqual(r["tags"], ["robot"])  # so the listener ignores its own reply

    def test_foreign_aircraft_uses_operator(self):
        found = {"faa": {}, "hexdb": {"Manufacturer": "Airbus", "Type": "A320 214",
                                      "RegisteredOwners": "British Airways"},
                 "live": None, "photo": None, "hexcode": "400abc"}
        r = lookup.build_reply("GEUUA", found, FakeAirports(), watching=True)
        self.assertIn("Operator: British Airways", r["message"])
        self.assertIn("Live: not transmitting right now", r["message"])
        self.assertIn("On your list ✓", r["message"])
        self.assertIsNone(r["attach"])

    def test_nothing_found(self):
        self.assertIsNone(lookup.build_reply("N0000", {"faa": {}, "hexdb": None, "live": None}, FakeAirports(), False))


class InfoCommandTest(unittest.TestCase):
    def test_watcher_imports_lookup(self):
        # on_info() runs inside run(); a missing import only shows up live.
        import tailwatcher
        self.assertIs(tailwatcher.lookup, lookup)

    def test_parse_info(self):
        self.assertEqual(commands.parse("info N12345")[:2], ("info", "N12345"))
        self.assertEqual(commands.parse("who UA 1234")[:2], ("info", "UA1234"))
        self.assertEqual(commands.parse("lookup g-abcd")[:2], ("info", "g-abcd"))
        self.assertEqual(commands.parse("info")[0], "unknown")


if __name__ == "__main__":
    unittest.main()
