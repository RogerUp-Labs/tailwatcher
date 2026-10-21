import base64
import json
import os
import tempfile
import unittest
import urllib.error
import urllib.request

import invites
import web

NOW = 1_800_000_000


class InviteTest(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "invites.json")

    def test_create_find_expire_revoke(self):
        inv = invites.create("tw-dad-x", "Sam", 7, now=NOW, path=self.path)
        self.assertRegex(inv["token"], r"^[A-Za-z0-9_-]{24}$")
        self.assertEqual((inv["kind"], inv["from"], inv["expires"]), ("watcher", "Sam", NOW + 7 * 86400))
        self.assertEqual(invites.find(inv["token"], now=NOW + 100, path=self.path)["topic"], "tw-dad-x")
        self.assertIsNone(invites.find(inv["token"], now=NOW + 8 * 86400, path=self.path))   # expired
        self.assertIsNone(invites.find("../../etc/passwd", now=NOW, path=self.path))        # malformed
        self.assertIsNone(invites.find("x" * 30, now=NOW, path=self.path))                   # unknown
        self.assertEqual(invites.revoke(inv["token"], path=self.path), 1)
        self.assertIsNone(invites.find(inv["token"], now=NOW, path=self.path))

    def test_days_are_clamped_and_old_invites_tidied(self):
        old = invites.create("tw-a", days=1, now=NOW, path=self.path)
        new = invites.create("tw-b", days=999, now=NOW + 2 * 86400, path=self.path)
        self.assertEqual(new["expires"], NOW + 2 * 86400 + 30 * 86400)
        self.assertEqual([i["token"] for i in invites.load(self.path)], [new["token"]])  # expired one dropped
        self.assertNotEqual(old["token"], new["token"])

    def test_join_page_links_and_escaping(self):
        inv = {"token": "t" * 24, "topic": "tw-dad-abc", "from": "<b>Sam</b>", "expires": NOW, "kind": "watcher"}
        page = invites.join_page(inv, "Dad <script>", "https://ntfy.sh")
        self.assertIn('href="ntfy://ntfy.sh/tw-dad-abc"', page)
        self.assertIn("https://ntfy.sh/tw-dad-abc", page)
        self.assertNotIn("<script>alert", page)
        self.assertIn("Dad &lt;script&gt;", page)
        self.assertIn("&lt;b&gt;Sam&lt;/b&gt; invited you", page)
        self.assertNotIn("asks for a login", page)
        login = invites.join_page(inv, "Dad", "http://ntfy.local:8080", "local", "login")
        self.assertIn("ntfy://ntfy.local:8080/tw-dad-abc?secure=false", login)
        self.assertIn("asks for a login", login)
        self.assertNotIn("Trust anchor", page)  # ntfy.sh has a certificate every phone trusts
        self.assertIn("Trust anchor", login)
        self.assertIn("Let &lt;b&gt;Sam&lt;/b&gt; know", login)
        self.assertIn("expired", invites.expired_page())


class Health:
    def get(self):
        return {"ok": True}


class JoinRouteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        d = tempfile.mkdtemp()
        cls.pw = os.path.join(d, "webui.json")
        with open(cls.pw, "w") as f:
            json.dump({"password": "secret-pass"}, f)
        for name, body in (("index.html", "<title>dash</title>"), ("icon.svg", "<svg/>")):
            with open(os.path.join(d, name), "w") as f:
                f.write(body)
        public = lambda token: (200, f"<h1>invite {token}</h1>") if token == "good" * 6 else (404, "expired")
        cls.srv = web.serve(0, Health(), lambda: {}, password_path=cls.pw, web_dir=d,
                            require_password=lambda: True, public=public)
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def get(self, path):
        try:
            with urllib.request.urlopen(self.base + path, timeout=5) as r:
                return r.status, r.read().decode(), dict(r.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode(), dict(e.headers)

    def test_invites_skip_the_password_but_the_dashboard_does_not(self):
        code, body, headers = self.get("/join/" + "good" * 6)
        self.assertEqual((code, body), (200, "<h1>invite goodgoodgoodgoodgoodgood</h1>"))
        self.assertIn("noindex", headers.get("X-Robots-Tag", ""))
        self.assertEqual(self.get("/join/nope")[0], 404)
        self.assertEqual(self.get("/icon.svg")[0], 200)
        self.assertEqual(self.get("/")[0], 401)
        self.assertEqual(self.get("/api/state")[0], 401)


if __name__ == "__main__":
    unittest.main()
