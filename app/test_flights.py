import unittest

import flights as f


class AirlineCodeTest(unittest.TestCase):
    def test_us_carriers(self):
        for iata, icao in [("UA", "UAL"), ("DL", "DAL"), ("AA", "AAL"), ("WN", "SWA"), ("B6", "JBU"),
                           ("AS", "ASA"), ("NK", "NKS"), ("F9", "FFT")]:
            self.assertEqual(f.parse_flight(f"{iata}123"), (f"{iata}123", f"{icao}123"))

    def test_international_and_icao_input(self):
        self.assertEqual(f.parse_flight("BA 117"), ("BA117", "BAW117"))
        self.assertEqual(f.parse_flight("lh400"), ("LH400", "DLH400"))
        self.assertEqual(f.parse_flight("UAL1234"), ("UAL1234", "UAL1234"))
        self.assertEqual(f.parse_flight("RYR5TM"), ("RYR5TM", "RYR5TM"))  # alphanumeric callsign

    def test_leading_zeros_dropped(self):
        self.assertEqual(f.parse_flight("DL 089"), ("DL89", "DAL89"))
        self.assertEqual(f.callsign("DL089"), "DAL89")


class TailOrFlightTest(unittest.TestCase):
    def test_registrations_are_not_flights(self):
        for tail in ["N12345", "N1", "N628TS", "N1A", "G-ABCD", "GABCD", "C-FJIC", "B-6123",
                     "JA8089", "HL7720", "D-AIKA", "N773AB"]:
            self.assertIsNone(f.parse_flight(tail), tail)

    def test_ambiguous_cases(self):
        # N + digit is always a US registration, never airline "N1".
        self.assertIsNone(f.parse_flight("N12"))
        # NH (ANA) and NK (Spirit) start with N but not N + digit.
        self.assertEqual(f.parse_flight("NH8"), ("NH8", "ANA8"))
        self.assertEqual(f.parse_flight("NK123"), ("NK123", "NKS123"))
        # A dash marks a registration: B-6123 is Chinese, B6123 is JetBlue 123.
        self.assertIsNone(f.parse_flight("B-6123"))
        self.assertEqual(f.parse_flight("B6123"), ("B6123", "JBU123"))
        # Unknown 2-character codes stay registrations; too many digits isn't a flight.
        self.assertIsNone(f.parse_flight("ZZ123"))
        self.assertIsNone(f.parse_flight("UA12345"))

    def test_matches_trimmed_flight_field(self):
        self.assertTrue(f.matches({"flight": "UAL1234 "}, "UAL1234"))
        self.assertFalse(f.matches({"flight": "UAL12345"}, "UAL1234"))
        self.assertFalse(f.matches({}, "UAL1234"))


if __name__ == "__main__":
    unittest.main()
