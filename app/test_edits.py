import base64
import json
import os
import tempfile
import unittest
import urllib.error
import urllib.request

import edits
import trips
import web

NOW = 1_800_000_000


class EditsTest(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp()
        self.cfg, self.trips = os.path.join(d, "config.json"), os.path.join(d, "trips.json")
        with open(self.cfg, "w") as f:
            json.dump({"watchers": [{"name": "Sam", "topic": "tailwatcher_sam", "aircraft": [
                {"tail": "N1ZZ", "label": "", "kind": "tail", "expires": None}],
                "notifyLanding": False, "priority": "default"}], "ntfyToken": "tk_keep"}, f)

    def read(self):
        with open(self.cfg) as f:
            return json.load(f)

    def test_add_update_rename_and_remove_watcher(self):
        self.assertEqual(edits.save_watcher(self.cfg, None, "Dad", "tailwatcher_dad", "high", True), "Added Dad.")
        dad = self.read()["watchers"][1]
        self.assertEqual((dad["priority"], dad["notifyLanding"], dad["aircraft"]), ("high", True, []))
        trips.save([{"topic": "tailwatcher_dad", "flight": "UA1", "date": "2026-11-14", "created": NOW}], self.trips)
        edits.save_watcher(self.cfg, "tailwatcher_dad", "Pops", "tailwatcher_pops", trips_path=self.trips)
        self.assertEqual(self.read()["watchers"][1]["name"], "Pops")
        self.assertEqual(trips.load(self.trips)[0]["topic"], "tailwatcher_pops")  # trips follow the rename
        self.assertIn("Removed Pops", edits.remove_watcher(self.cfg, "tailwatcher_pops", trips_path=self.trips))
        self.assertEqual(trips.load(self.trips), [])
        self.assertEqual(self.read()["ntfyToken"], "tk_keep")

    def test_blank_topic_gets_an_unguessable_one(self):
        edits.save_watcher(self.cfg, None, "Mom & Dad", "")
        topic = self.read()["watchers"][1]["topic"]
        self.assertRegex(topic, r"^tw-momdad-[a-z2-9]{20}$")
        self.assertNotEqual(topic, edits.new_topic("Mom & Dad"))       # random every time
        edits.save_watcher(self.cfg, topic, "Parents", "")             # editing keeps it
        self.assertEqual(self.read()["watchers"][1]["topic"], topic)
        edits.save_watcher(self.cfg, topic, "Parents", topic, new_topic_requested=True)
        self.assertRegex(self.read()["watchers"][1]["topic"], r"^tw-parents-[a-z2-9]{20}$")

    def test_planes_topic(self):
        edits.save_watcher(self.cfg, "tailwatcher_sam", "Sam", "", planes=True)
        planes = self.read()["watchers"][0]["planesTopic"]
        self.assertRegex(planes, r"^tw-sam-planes-[a-z2-9]{20}$")
        edits.save_watcher(self.cfg, "tailwatcher_sam", "Sam", "", planes=True)    # kept, not remade
        edits.save_watcher(self.cfg, "tailwatcher_sam", "Sammy", "")               # None leaves it alone
        self.assertEqual(self.read()["watchers"][0]["planesTopic"], planes)
        with self.assertRaisesRegex(edits.EditError, "already uses"):
            edits.save_watcher(self.cfg, None, "Twin", planes)
        edits.save_watcher(self.cfg, "tailwatcher_sam", "Sam", "", planes=False)
        self.assertEqual(self.read()["watchers"][0]["planesTopic"], "")

    def test_watcher_validation(self):
        with self.assertRaisesRegex(edits.EditError, "already uses"):
            edits.save_watcher(self.cfg, None, "Twin", "tailwatcher_sam")
        with self.assertRaisesRegex(edits.EditError, "letters, numbers"):
            edits.save_watcher(self.cfg, None, "Bad", "has space")
        with self.assertRaisesRegex(edits.EditError, "name"):
            edits.save_watcher(self.cfg, None, " ", "tailwatcher_x")

    def test_aircraft_add_edit_remove(self):
        self.assertEqual(edits.save_aircraft(self.cfg, "tailwatcher_sam", "n-628ts", "Tesla jet", now=NOW),
                         "Added N628TS for Sam.")
        self.assertIn("flight UA1234", edits.save_aircraft(self.cfg, "tailwatcher_sam", "UA 1234", "", 2, now=NOW))
        ac = self.read()["watchers"][0]["aircraft"]
        self.assertEqual(ac[1], {"tail": "N628TS", "label": "Tesla jet", "kind": "tail", "expires": None})
        self.assertEqual((ac[2]["kind"], ac[2]["expires"]), ("flight", NOW + 2 * 86400))
        # Edit in place: new nickname, then replace the tail number itself.
        edits.save_aircraft(self.cfg, "tailwatcher_sam", "N628TS", "Elon", original="N628TS", now=NOW)
        edits.save_aircraft(self.cfg, "tailwatcher_sam", "N272BG", "", original="N1ZZ", now=NOW)
        tails = [a["tail"] for a in self.read()["watchers"][0]["aircraft"]]
        self.assertEqual(tails, ["N272BG", "N628TS", "UA1234"])
        self.assertIn("Removed UA1234", edits.remove_aircraft(self.cfg, "tailwatcher_sam", "UA1234"))
        with self.assertRaisesRegex(edits.EditError, "already on"):
            edits.save_aircraft(self.cfg, "tailwatcher_sam", "N628TS")
        with self.assertRaisesRegex(edits.EditError, "doesn't look like"):
            edits.save_aircraft(self.cfg, "tailwatcher_sam", "!!")
        with self.assertRaisesRegex(edits.EditError, "between 1 and 366"):
            edits.save_aircraft(self.cfg, "tailwatcher_sam", "N9", "", 0)


class Health:
    def get(self):
        return {"ok": True}


class PostGuardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.calls = []
        d = tempfile.mkdtemp()
        cls.srv = web.serve(0, Health(), lambda: {}, password_path=os.path.join(d, "none.json"), web_dir=d,
                            post=lambda path, data, viewer: (cls.calls.append((path, data)) or (200, {"ok": True})))
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def post(self, headers, body=b'{"op":"save"}'):
        req = urllib.request.Request(self.base + "/api/aircraft", data=body, method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code

    def test_only_the_page_can_edit(self):
        ok = {"Content-Type": "application/json", "X-TailWatcher": "1"}
        self.assertEqual(self.post(ok), 200)
        self.assertEqual(self.calls[-1], ("/api/aircraft", {"op": "save"}))
        self.assertEqual(self.post({"Content-Type": "application/json"}), 403)               # no header
        self.assertEqual(self.post({"Content-Type": "text/plain", "X-TailWatcher": "1"}), 403)  # form-style
        self.assertEqual(self.post({**ok, "Origin": "https://evil.example"}), 403)            # other site
        host = self.base.split("//")[1]
        self.assertEqual(self.post({**ok, "Origin": f"http://{host}"}), 200)                  # this page
        self.assertEqual(self.post(ok, body=b"not json"), 400)


if __name__ == "__main__":
    unittest.main()
