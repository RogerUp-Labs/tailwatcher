import base64
import json
import os
import tempfile
import unittest
import urllib.error
import urllib.request

import history
import web


class Health:
    def get(self):
        return {"ok": True, "message": "Watching 1 aircraft"}


class WebServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.pw = os.path.join(cls.dir, "webui.json")
        with open(os.path.join(cls.dir, "index.html"), "w") as f:
            f.write("<title>TailWatcher</title>")
        cls.required = False
        cls.srv = web.serve(0, Health(), lambda: {"watchers": [], "secret": False},
                            password_path=cls.pw, web_dir=cls.dir, require_password=lambda: cls.required)
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def get(self, path, password=None):
        req = urllib.request.Request(self.base + path)
        if password is not None:
            req.add_header("Authorization", "Basic " + base64.b64encode(f"any:{password}".encode()).decode())
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.read().decode(), dict(r.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode(), dict(e.headers)

    def set_password(self, pw):
        with open(self.pw, "w") as f:
            json.dump({"password": pw}, f)

    def test_health_is_open(self):
        code, body, _ = self.get("/health")
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)["message"], "Watching 1 aircraft")

    def setUp(self):
        type(self).required = True

    def test_open_by_default(self):
        type(self).required = False
        self.set_password("correct-horse")
        code, body, _ = self.get("/api/state")
        self.assertEqual((code, json.loads(body)), (200, {"watchers": [], "secret": False}))
        self.assertEqual(self.get("/")[0], 200)

    def test_no_password_file_locks_everything(self):
        if os.path.exists(self.pw):
            os.unlink(self.pw)
        self.assertEqual(self.get("/", "x")[0], 503)

    def test_password_required(self):
        self.set_password("correct-horse")
        code, _, headers = self.get("/")
        self.assertEqual(code, 401)
        self.assertIn("Basic", headers.get("WWW-Authenticate", ""))
        self.assertEqual(self.get("/api/state", "wrong")[0], 401)
        code, body, headers = self.get("/api/state", "correct-horse")
        self.assertEqual((code, json.loads(body)), (200, {"watchers": [], "secret": False}))
        self.assertEqual(headers.get("Cache-Control"), "no-store")
        code, body, _ = self.get("/", "correct-horse")
        self.assertEqual(code, 200)
        self.assertIn("TailWatcher", body)
        self.assertEqual(self.get("/../../etc/passwd", "correct-horse")[0], 404)


class HistoryTest(unittest.TestCase):
    def test_ring_buffer_and_persistence(self):
        path = os.path.join(tempfile.mkdtemp(), "history.json")
        h = history.History(path, limit=3)
        for i in range(5):
            h.add("out", "t", f"m{i}", kind="alert", now=1000 + i)
        self.assertEqual([e["message"] for e in h.recent()], ["m4", "m3", "m2"])
        h.save()
        self.assertEqual([e["message"] for e in history.History(path, limit=3).recent()], ["m4", "m3", "m2"])

    def test_message_kinds(self):
        import tailwatcher as tw
        self.assertEqual(tw.message_kind({"tags": ["robot"]}), "reply")
        self.assertEqual(tw.message_kind({"tags": ["airplane"], "title": "N1 departed"}), "alert")
        self.assertEqual(tw.message_kind({"tags": ["airplane"], "title": "✈️ UA1: your plane is on its way"}), "trip")
        self.assertEqual(tw.message_kind({"tags": ["airplane", "test_tube"]}), "test")


if __name__ == "__main__":
    unittest.main()
