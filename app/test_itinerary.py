import datetime
import unittest

import itinerary
import trips


def ts(*args):
    return datetime.datetime(*args, tzinfo=datetime.timezone.utc).timestamp()


class FakeAirports:
    iata = {"EWR": "KEWR", "DEN": "KDEN", "SLC": "KSLC", "LAS": "KLAS", "ORD": "KORD", "AND": "XAND"}
    coords = {v: (0, 0, k) for k, v in iata.items()}
    tz = {"KEWR": "America/New_York", "KDEN": "America/Denver", "KSLC": "America/Denver",
          "KLAS": "America/Los_Angeles", "KORD": "America/Chicago"}


AIR = FakeAirports()
NOW = ts(2026, 10, 20, 14)
TZ = "America/New_York"


def run(text, name=""):
    return itinerary.preview(text, name, NOW, TZ, AIR)


UNITED_TEXT = """Thanks for choosing United. Confirmation number: K3XQ9P
Tue, Nov 03, 2026
UA 1234
Newark, NJ, US (EWR) 8:15 AM
Denver, CO, US (DEN) 10:30 AM
UA 567
Denver, CO, US (DEN) 12:05 PM
Salt Lake City, UT, US (SLC) 1:40 PM
Tue, Nov 10, 2026
UA 890
Salt Lake City, UT, US (SLC) 9:00 AM
Newark, NJ, US (EWR) 4:55 PM
Total: $412.30 AND taxes
"""

KAYAK_TEXT = """Your trip to Las Vegas
Depart · Sat, Dec 5
6:00 am  Chicago O'Hare (ORD) → 8:05 am Las Vegas (LAS)
Spirit 1421
Return · Wed, Dec 9
3:15 pm  Las Vegas (LAS) → 9:20 pm Chicago O'Hare (ORD)
Spirit 1422
"""

JSONLD_EMAIL = """From: "Delta Air Lines" <deltaairlines@t.delta.com>
To: sam@example.com
Subject: Your Flight Receipt
Date: Mon, 19 Oct 2026 10:00:00 -0400
MIME-Version: 1.0
Content-Type: multipart/mixed; boundary="b1"

--b1
Content-Type: multipart/alternative; boundary="b2"

--b2
Content-Type: text/plain; charset=utf-8

DL 89 Nov 14 ATL-LAS (ignored: the markup wins)

--b2
Content-Type: text/html; charset=utf-8
Content-Transfer-Encoding: quoted-printable

<html><head><script type=3D"application/ld+json">
[{"@context": "http://schema.org", "@type": "FlightReservation",
  "reservationNumber": "GXR4LK",
  "reservationFor": {"@type": "Flight", "flightNumber": "1234",
    "airline": {"@type": "Airline", "iataCode": "DL"},
    "departureAirport": {"@type": "Airport", "iataCode": "EWR"},
    "departureTime": "2026-11-14T07:05:00-05:00",
    "arrivalAirport": {"@type": "Airport", "iataCode": "DEN"}}},
 {"@context": "http://schema.org", "@type": "FlightReservation",
  "reservationFor": {"@type": "Flight", "flightNumber": "DL567",
    "departureAirport": {"@type": "Airport", "iataCode": "DEN"},
    "departureTime": "2026-11-21T18:40:00-07:00",
    "arrivalAirport": {"@type": "Airport", "iataCode": "EWR"}}}]
</script></head><body><p>Thanks for flying Delta</p></body></html>

--b2--

--b1
Content-Type: application/pdf; name="receipt.pdf"
Content-Disposition: attachment; filename="receipt.pdf"
Content-Transfer-Encoding: base64

JVBERi0xLjQK

--b1--
"""

TRIPIT_ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//TripIt//Calendar//EN
BEGIN:VEVENT
DTSTART:20261103T131500Z
DTEND:20261103T173000Z
SUMMARY:UA1234 EWR to DEN
LOCATION:Newark (EWR)
DESCRIPTION:[Flight] 11/3/2026 United Airlines(UA) #1234 dep Newark EWR 8
 :15am EST\\; arr Denver DEN 10:30am MST
END:VEVENT
BEGIN:VEVENT
DTSTART;TZID=America/Denver:20261110T090000
SUMMARY:Flight to Newark (UA 890)
LOCATION:Denver (DEN)
END:VEVENT
END:VCALENDAR
"""


class ReadTest(unittest.TestCase):
    def test_united_text_with_connection_and_return(self):
        r = run(UNITED_TEXT)
        self.assertTrue(r["ok"], r)
        self.assertEqual([(f["flight"], f["date"], f["time"], f["dep"], f["arr"]) for f in r["flights"]], [
            ("UA1234", "2026-11-03", "08:15", "EWR", "DEN"),
            ("UA567", "2026-11-03", "12:05", "DEN", "SLC"),
            ("UA890", "2026-11-10", "09:00", "SLC", "EWR"),
        ])
        self.assertEqual(r["form"], {
            "flight": "UA1234", "date": "2026-11-03", "time": "08:15", "airport": "EWR",
            "conn_flight": "UA567", "conn_time": "12:05",
            "ret_flight": "UA890", "ret_date": "2026-11-10", "ret_time": "09:00", "ret_airport": "SLC",
        })

    def test_the_form_reads_as_a_trip(self):
        """What the Add trip form sends for an imported trip parses as one journey."""
        f = run(UNITED_TEXT)["form"]
        text = (f"{f['flight']} {f['date']} dep {f['time']} from {f['airport']} then {f['conn_flight']} dep {f['conn_time']}"
                f" return {f['ret_flight']} {f['ret_date']} dep {f['ret_time']} from {f['ret_airport']}")
        legs = trips.parse_itinerary(text, NOW, TZ, AIR)
        self.assertIsInstance(legs, list, legs)
        self.assertEqual([(t["flight"], t["date"], t["leg"], t["dep_airport"]) for t in legs], [
            ("UA1234", "2026-11-03", "out", "KEWR"), ("UA567", "2026-11-03", "out", None),
            ("UA890", "2026-11-10", "return", "KSLC")])

    def test_booking_site_text_with_airline_names(self):
        r = run(KAYAK_TEXT)
        self.assertTrue(r["ok"], r)
        self.assertEqual([(f["flight"], f["date"], f["time"], f["dep"]) for f in r["flights"]], [
            ("NK1421", "2026-12-05", "06:00", "ORD"), ("NK1422", "2026-12-09", "15:15", "LAS")])
        self.assertEqual(r["form"]["ret_flight"], "NK1422")

    def test_email_markup_wins_and_pdf_attachment_is_noted(self):
        r = run(JSONLD_EMAIL, "Your Flight Receipt.eml")
        self.assertTrue(r["ok"], r)
        self.assertIn("flight details", r["message"])
        self.assertEqual([(f["flight"], f["date"], f["time"], f["dep"]) for f in r["flights"]], [
            ("DL1234", "2026-11-14", "07:05", "EWR"), ("DL567", "2026-11-21", "18:40", "DEN")])
        self.assertTrue(any("receipt.pdf" in n for n in r["notes"]))

    def test_email_without_markup_reads_the_text(self):
        raw = ("From: a@b.c\nSubject: Trip\nMIME-Version: 1.0\nContent-Type: text/plain\n\n"
               "Flight AA 100 on 11/14/2026 departs ORD at 7:05 PM\n")
        r = run(raw)
        self.assertEqual(r["flights"][0]["flight"], "AA100")
        self.assertEqual(r["form"]["date"], "2026-11-14")
        self.assertEqual(r["form"]["time"], "19:05")

    def test_calendar_file_in_the_airports_time_zone(self):
        r = run(TRIPIT_ICS, "trip.ics")
        self.assertTrue(r["ok"], r)
        self.assertEqual([(f["flight"], f["date"], f["time"], f["dep"]) for f in r["flights"]], [
            ("UA1234", "2026-11-03", "08:15", "EWR"),  # 13:15Z is 8:15 in Newark
            ("UA890", "2026-11-10", "09:00", "DEN")])

    def test_pdfs_and_images_are_refused_with_what_to_do(self):
        for text, name in (("%PDF-1.4 ...", "itinerary.pdf"), ("\x89PNG\x00\x00", "shot.png")):
            r = run(text, name)
            self.assertFalse(r["ok"])
            self.assertIn("copy it and paste", r["message"])

    def test_nothing_found(self):
        r = run("Hello, see you at 8:15 AM 11 Main St.")
        self.assertFalse(r["ok"])
        self.assertIn("couldn't find a flight number", r["message"])


class PartsTest(unittest.TestCase):
    def test_times_and_prices_are_not_flights(self):
        self.assertEqual([f for _, _, f in itinerary.find_flights("8:15 AM 11 and AA 1.50 and UA1234")], ["UA1234"])

    def test_dates(self):
        today = datetime.date(2026, 10, 20)
        got = [d.isoformat() for _, d in itinerary.find_dates(
            "2026-11-03, Nov 4, 5 November 2026, 06NOV26, 11/07/2026, 13/11/2026, Jan 2", today)]
        self.assertEqual(sorted(got), ["2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06",
                                       "2026-11-07", "2026-11-13", "2027-01-02"])

    def test_every_connection_fills_the_form(self):
        legs = [{"flight": f"UA{n}", "date": "2026-11-03", "time": f"0{n}:00", "dep": None, "arr": None}
                for n in range(1, 4)]
        form, notes = itinerary.to_form(itinerary.journeys(legs))
        self.assertEqual((form["conn_flight"], form["conn2_flight"]), ("UA2", "UA3"))
        self.assertFalse(any("UA3" in n for n in notes))

    def test_more_flights_than_can_be_followed(self):
        legs = [{"flight": f"UA{n}", "date": "2026-11-03", "time": f"{n:02}:00", "dep": None, "arr": None}
                for n in range(1, trips.MAX_LEGS + 2)]
        form, notes = itinerary.to_form(itinerary.journeys(legs))
        self.assertEqual(form[trips.form_prefix("", trips.MAX_LEGS - 2) + "flight"], f"UA{trips.MAX_LEGS}")
        self.assertTrue(any(f"UA{trips.MAX_LEGS + 1}" in n for n in notes))

    def test_a_later_flight_from_somewhere_else_is_a_separate_journey(self):
        legs = [{"flight": "UA1", "date": "2026-11-03", "time": "08:00", "dep": "EWR", "arr": "DEN"},
                {"flight": "UA2", "date": "2026-11-03", "time": "18:00", "dep": "ORD", "arr": "LAS"}]
        self.assertEqual(len(itinerary.journeys(legs)), 2)


if __name__ == "__main__":
    unittest.main()
