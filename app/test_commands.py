import json
import os
import tempfile
import unittest

import commands as c


class ParseTest(unittest.TestCase):
    def test_bare_tail_adds_with_nickname(self):
        self.assertEqual(c.parse("N12345"), ("add", "N12345", ""))
        self.assertEqual(c.parse("n12345 Vegas trip"), ("add", "n12345", "Vegas trip"))
        self.assertEqual(c.parse("G-ABCD"), ("add", "G-ABCD", ""))

    def test_explicit_verbs(self):
        self.assertEqual(c.parse("add GABCD Club plane"), ("add", "GABCD", "Club plane"))
        self.assertEqual(c.parse("+N1"), ("add", "N1", ""))
        self.assertEqual(c.parse("remove N12345"), ("remove", "N12345", ""))
        self.assertEqual(c.parse("rm n12345"), ("remove", "n12345", ""))
        self.assertEqual(c.parse("-N12345"), ("remove", "N12345", ""))
        self.assertEqual(c.parse("List")[0], "list")
        self.assertEqual(c.parse("help")[0], "help")

    def test_chatter_is_not_a_tail(self):
        self.assertEqual(c.parse("hello there")[0], "unknown")
        self.assertEqual(c.parse("")[0], "unknown")
        self.assertEqual(c.parse("thanks!")[0], "unknown")


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
        self.assertEqual(cfg["watchers"][1]["aircraft"], [{"tail": "N12345", "label": "Vegas trip"}])
        self.assertEqual(cfg["watchers"][0]["aircraft"], [{"tail": "N628TS", "label": ""}])
        self.assertEqual(cfg["ntfyToken"], "tk_x")  # other settings preserved
        self.assertEqual(cfg["watchers"][1]["priority"], "high")

    def test_duplicate_add_and_rename(self):
        self.assertIn("Already watching", self.run_cmd("tailwatcher_sam", "N628TS")[0])
        reply, changed = self.run_cmd("tailwatcher_sam", "add N628TS Tesla jet")
        self.assertTrue(changed)
        self.assertIn("Renamed", reply)
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
