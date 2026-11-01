import json
import os
import tempfile
import unittest

import commands as c


class ParseTest(unittest.TestCase):
    def test_bare_tail_adds_with_nickname(self):
        self.assertEqual(c.parse("N12345"), ("add", "N12345", "", None))
        self.assertEqual(c.parse("n12345 Vegas trip"), ("add", "n12345", "Vegas trip", None))
        self.assertEqual(c.parse("G-ABCD"), ("add", "G-ABCD", "", None))

    def test_explicit_verbs(self):
        self.assertEqual(c.parse("add GABCD Club plane"), ("add", "GABCD", "Club plane", None))
        self.assertEqual(c.parse("+N1"), ("add", "N1", "", None))
        self.assertEqual(c.parse("remove N12345"), ("remove", "N12345", "", None))
        self.assertEqual(c.parse("rm n12345"), ("remove", "n12345", "", None))
        self.assertEqual(c.parse("-N12345"), ("remove", "N12345", "", None))
        self.assertEqual(c.parse("List")[0], "list")
        self.assertEqual(c.parse("help")[0], "help")

    def test_help_puts_trips_first_and_every_example_parses(self):
        self.assertLess(c.HELP.index("YOUR TRIPS"), c.HELP.index("WATCH A PLANE"))
        for line in c.HELP.splitlines():
            if line.startswith("• "):
                example = line[2:].split(" — ")[0].split(" or ")[0]
                self.assertNotEqual(c.parse(example)[0], "unknown", example)

    def test_chatter_is_not_a_tail(self):
        self.assertEqual(c.parse("hello there")[0], "unknown")
        self.assertEqual(c.parse("")[0], "unknown")
        self.assertEqual(c.parse("thanks!")[0], "unknown")


# Thursday 2026-10-15 12:00 UTC
NOW = 1_792_065_600


class ExpiryParseTest(unittest.TestCase):
    def test_durations(self):
        self.assertEqual(c.parse("UA1234 for 2 days", NOW), ("add", "UA1234", "", NOW + 2 * 86400))
        self.assertEqual(c.parse("add N12345 Vegas trip for 3d", NOW),
                         ("add", "N12345", "Vegas trip", NOW + 3 * 86400))
        self.assertEqual(c.parse("N12345 12h", NOW), ("add", "N12345", "", NOW + 12 * 3600))
        self.assertEqual(c.parse("UA1234 Mom for 1 day", NOW)[2:], ("Mom", NOW + 86400))
        self.assertEqual(c.parse("UA1234 for 6 hours", NOW)[3], NOW + 6 * 3600)

    def test_until_weekday_runs_through_that_night_in_local_time(self):
        import datetime as dt
        ny = dt.timezone(dt.timedelta(hours=-4))  # EDT in October
        self.assertEqual(dt.datetime.fromtimestamp(NOW, ny).strftime("%a %H:%M"), "Thu 08:00")
        # Through Friday = Saturday 03:00 EDT = Saturday 07:00 UTC.
        fri_end = NOW + 2 * 86400 - 5 * 3600
        self.assertEqual(c.parse("UA1234 until fri", NOW)[3], fri_end)
        self.assertEqual(c.parse("UA1234 until Friday", NOW)[3], fri_end)
        self.assertEqual(c.parse("UA1234 until thu", NOW)[3], fri_end - 86400)  # today
        self.assertEqual(c.parse("UA1234 until wed", NOW)[3], fri_end + 5 * 86400)  # next week
        self.assertEqual(c.parse("UA1234 until tomorrow", NOW)[3], fri_end)

    def test_until_uses_local_date_not_utc(self):
        # Friday 21:58 EDT is already Saturday in UTC; "tomorrow" is still Saturday.
        fri_evening = NOW + 86400 + 13 * 3600 + 58 * 60
        sat_end = NOW + 3 * 86400 - 5 * 3600
        self.assertEqual(c.parse("UA1234 until tomorrow", fri_evening)[3], sat_end)
        self.assertEqual(c.parse("UA1234 until fri", fri_evening)[3], sat_end - 86400)
        # Another zone, and a bad name falls back to UTC.
        self.assertEqual(c.parse("UA1234 until fri", NOW, "Europe/London")[3], NOW + 2 * 86400 - 10 * 3600)
        self.assertEqual(c.parse("UA1234 until fri", NOW, "Mars/Base")[3], NOW + 2 * 86400 - 9 * 3600)

    def test_label_without_expiry_is_kept(self):
        self.assertEqual(c.parse("N12345 for Mom", NOW), ("add", "N12345", "for Mom", None))
        self.assertEqual(c.parse("N12345 Boeing 737", NOW)[2:], ("Boeing 737", None))
        self.assertEqual(c.parse("N12345 until fried", NOW)[2:], ("until fried", None))


class FlightParseTest(unittest.TestCase):
    def test_flight_numbers_are_added(self):
        self.assertEqual(c.parse("UA1234")[:2], ("add", "UA1234"))
        self.assertEqual(c.parse("DL 89")[:2], ("add", "DL89"))
        self.assertEqual(c.parse("add DL 89 Mom for 2d", NOW), ("add", "DL89", "Mom", NOW + 2 * 86400))
        self.assertEqual(c.parse("remove AA 100")[:2], ("remove", "AA100"))
        self.assertEqual(c.parse("UAL1234")[:2], ("add", "UAL1234"))

    def test_classify(self):
        self.assertEqual(c.classify("UA1234"), ("flight", "UA1234", "UAL1234"))
        self.assertEqual(c.classify("ual1234"), ("flight", "UAL1234", "UAL1234"))
        self.assertEqual(c.classify("N12345"), ("tail", "N12345", "N12345"))
        self.assertEqual(c.classify("G-ABCD"), ("tail", "GABCD", "GABCD"))
        self.assertIsNone(c.classify("!!"))


class ApplyTest(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        self.write({
            "watchers": [
                {"name": "Sam", "topic": "tailwatcher_sam", "aircraft": [{"tail": "N628TS", "label": ""}],
                 "notifyLanding": False, "priority": "default"},
                {"name": "Dad", "topic": "tailwatcher_dad", "aircraft": [],
                 "notifyLanding": True, "priority": "high"},
            ],
            "ntfyToken": "tk_x", "pollSeconds": 60, "dataSource": "adsb.lol", "mapLinks": "adsbx",
        })

    def tearDown(self):
        os.unlink(self.path)

    def write(self, data):
        with open(self.path, "w") as f:
            json.dump(data, f)

    def read(self):
        with open(self.path) as f:
            return json.load(f)

    def run_cmd(self, topic, text, status=None):
        return c.apply_command(self.path, topic, text, status)

    def test_add_only_touches_that_watcher(self):
        reply, changed = self.run_cmd("tailwatcher_dad", "n-12345 Vegas trip")
        self.assertTrue(changed)
        self.assertIn("Added N12345 (Vegas trip)", reply)
        cfg = self.read()
        self.assertEqual(cfg["watchers"][1]["aircraft"], [{"tail": "N12345", "label": "Vegas trip", "kind": "tail", "expires": None}])
        self.assertEqual(cfg["watchers"][0]["aircraft"], [{"tail": "N628TS", "label": ""}])
        self.assertEqual(cfg["ntfyToken"], "tk_x")  # other settings preserved
        self.assertEqual(cfg["watchers"][1]["priority"], "high")

    def test_duplicate_add_and_rename(self):
        self.assertIn("Already watching", self.run_cmd("tailwatcher_sam", "N628TS")[0])
        reply, changed = self.run_cmd("tailwatcher_sam", "add N628TS Tesla jet")
        self.assertTrue(changed)
        self.assertIn("renamed to \"Tesla jet\"", reply)
        self.assertEqual(self.read()["watchers"][0]["aircraft"][0]["label"], "Tesla jet")

    def test_remove(self):
        reply, changed = self.run_cmd("tailwatcher_sam", "remove n628ts")
        self.assertTrue(changed)
        self.assertIn("Removed N628TS. Watching 0", reply)
        reply, changed = self.run_cmd("tailwatcher_sam", "remove N628TS")
        self.assertFalse(changed)
        self.assertIn("isn't on your list", reply)

    def test_list_shows_status(self):
        reply, changed = self.run_cmd("tailwatcher_sam", "list", status={"N628TS": {"status": "airborne"}})
        self.assertFalse(changed)
        self.assertIn("Sam's aircraft (1)", reply)
        self.assertIn("N628TS — ✈️ airborne", reply)
        self.assertIn("empty", self.run_cmd("tailwatcher_dad", "list")[0])

    def test_add_flight_with_expiry_and_list(self):
        reply, changed = c.apply_command(self.path, "tailwatcher_dad", "UA 1234 for 2 days", now=NOW)
        self.assertTrue(changed)
        self.assertIn("Added flight UA1234 for 2d", reply)
        a = self.read()["watchers"][1]["aircraft"][0]
        self.assertEqual(a, {"tail": "UA1234", "label": "", "kind": "flight", "expires": NOW + 2 * 86400})
        # The ICAO form is the same flight; re-adding with a new expiry extends it.
        reply, changed = c.apply_command(self.path, "tailwatcher_dad", "UAL1234 for 3d", now=NOW)
        self.assertTrue(changed)
        self.assertIn("UA1234: watching for 3d", reply)
        self.assertEqual(len(self.read()["watchers"][1]["aircraft"]), 1)
        status = {"UAL1234": {"status": "airborne", "last_fix": {"r": "N38473"}}}
        reply, _ = c.apply_command(self.path, "tailwatcher_dad", "list", status, now=NOW + 3600)
        self.assertIn("• UA1234 — ✈️ airborne (N38473) · 2d 23h left", reply)
        self.assertEqual(c.format_left(NOW + 86400 - 0.5, NOW), "1d left")
        self.assertEqual(c.format_left(NOW + 90, NOW), "2m left")
        reply, changed = c.apply_command(self.path, "tailwatcher_dad", "remove UAL 1234")
        self.assertTrue(changed)
        self.assertIn("Removed UA1234", reply)

    def test_remove_expired(self):
        self.write({"watchers": [
            {"name": "Sam", "topic": "tailwatcher_sam", "aircraft": [
                {"tail": "N628TS", "label": ""},
                {"tail": "UA1234", "label": "", "kind": "flight", "expires": NOW - 1},
                {"tail": "N12345", "label": "", "kind": "tail", "expires": NOW + 60},
            ]},
            {"name": "Dad", "topic": "tailwatcher_dad", "aircraft": [
                {"tail": "DL89", "label": "", "kind": "flight", "expires": NOW}]},
        ], "ntfyToken": "tk_x"})
        self.assertEqual(c.remove_expired(self.path, NOW),
                         [("tailwatcher_sam", "UA1234"), ("tailwatcher_dad", "DL89")])
        cfg = self.read()
        self.assertEqual([a["tail"] for a in cfg["watchers"][0]["aircraft"]], ["N628TS", "N12345"])
        self.assertEqual(cfg["watchers"][1]["aircraft"], [])
        self.assertEqual(cfg["ntfyToken"], "tk_x")
        mtime = os.stat(self.path).st_mtime_ns
        self.assertEqual(c.remove_expired(self.path, NOW), [])
        self.assertEqual(os.stat(self.path).st_mtime_ns, mtime)  # untouched when nothing expired

    def test_unknown_topic_and_bad_input(self):
        self.assertEqual(self.run_cmd("someone_else", "N12345"), (None, False))
        self.assertIn("didn't understand", self.run_cmd("tailwatcher_sam", "hello")[0])
        self.assertIn("doesn't look like", self.run_cmd("tailwatcher_sam", "add !!")[0])

    def test_legacy_config_is_upgraded_on_edit(self):
        self.write({"aircraft": [{"tail": "N1", "label": ""}], "ntfyTopic": "tailwatcher",
                    "ntfyToken": "tk_y", "notifyLanding": True, "priority": "high"})
        reply, changed = self.run_cmd("tailwatcher", "N2")
        self.assertTrue(changed)
        cfg = self.read()
        self.assertNotIn("aircraft", cfg)
        self.assertEqual(cfg["ntfyToken"], "tk_y")
        w = cfg["watchers"][0]
        self.assertEqual((w["topic"], w["priority"], w["notifyLanding"]), ("tailwatcher", "high", True))
        self.assertEqual([a["tail"] for a in w["aircraft"]], ["N1", "N2"])


class AccessHintTest(unittest.TestCase):
    def test_pattern_matches_topic(self):
        # A 403 on a new tw-… topic used to point people at tailwatcher*
        self.assertIn("Read-Write on tw-*", c.access_hint("tw-dad-h5nenad6cp8g5jwksg9t"))
        self.assertIn("Read-Write on tailwatcher*", c.access_hint("tailwatcher_dad"))
        self.assertIn("Read-Write on family", c.access_hint("family"))
        self.assertIn("Set up NTFY for me", c.access_hint("tw-dad-x"))
        # 401: the token itself is refused (expired), not a missing grant
        self.assertIn("no longer accepts", c.access_hint("tw-dad-x", 401))
        self.assertIn("Set up NTFY for me", c.access_hint("tw-dad-x", 401))
        self.assertNotIn("no longer accepts", c.access_hint("tw-dad-x", 403))


class ListenerFilterTest(unittest.TestCase):
    def test_own_messages_and_non_messages_are_ignored(self):
        got = []
        lis = c.TopicListener("http://x", "", "t", lambda topic, text: got.append(text), lambda *a: None)
        lis.handle(json.dumps({"id": "1", "event": "open"}))
        lis.handle(json.dumps({"id": "2", "event": "message", "message": "N1 departed", "tags": ["airplane"]}))
        lis.handle(json.dumps({"id": "3", "event": "message", "message": "✅ Added", "tags": ["robot"]}))
        lis.handle(json.dumps({"id": "4", "event": "message", "message": "N12345"}))
        lis.handle(json.dumps({"id": "4", "event": "message", "message": "N12345"}))  # replayed
        self.assertEqual(got, ["N12345"])
        self.assertEqual(lis.since, "4")


if __name__ == "__main__":
    unittest.main()
