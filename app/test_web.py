import base64
import http.client
import json
import os
import tempfile
import unittest
import urllib.error
import urllib.parse
import urllib.request

import accounts
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
        cls.acc = os.path.join(cls.dir, "accounts.json")
        cls.ses = os.path.join(cls.dir, "sessions.json")
        with open(os.path.join(cls.dir, "index.html"), "w") as f:
            f.write("<title>TailWatcher</title>")
        cls.mode = "off"
        cls.seen, cls.codes, cls.signups = [], [], []

        def signup(token, form):
            cls.signups.append((token, form))
            if token != "good-token-0123456789abc":
                return 404, "expired", None
            return 303, "", accounts.create(form["username"], form["name"], form["password"], path=cls.acc)["id"]
        cls.srv = web.serve(0, Health(), lambda v: cls.seen.append(v) or {"watchers": [], "secret": False},
                            password_path=cls.pw, web_dir=cls.dir, mode=lambda: cls.mode,
                            post=lambda path, data, v: (200, {"ok": True, "who": (v["account"] or {}).get("username")}),
                            accounts_path=cls.acc, sessions_path=cls.ses, signup=signup,
                            forgot=lambda u: cls.codes.append(accounts.start_reset(u, cls.acc)[1]))
        cls.port = cls.srv.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        type(self).mode = "password"
        web.THROTTLE.fails.clear()

    def request(self, method, path, body=None, headers=None):
        """One request, redirects not followed: (status, body, headers)."""
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request(method, path, body=body, headers=headers or {})
        r = conn.getresponse()
        out = r.status, r.read().decode(), dict(r.getheaders())
        conn.close()
        return out

    def get(self, path, password=None, cookie=None):
        headers = {}
        if password is not None:
            headers["Authorization"] = "Basic " + base64.b64encode(f"any:{password}".encode()).decode()
        if cookie:
            headers["Cookie"] = cookie
        return self.request("GET", path, headers=headers)

    def login(self, password, username=""):
        return self.form("/login", username=username, password=password)

    def form(self, path, **fields):
        """POST a form like the browser does: (status, page, cookie)."""
        code, page, headers = self.request("POST", path, urllib.parse.urlencode(fields),
                                           {"Content-Type": "application/x-www-form-urlencoded", "Origin": "null"})
        cookie = (headers.get("Set-Cookie") or "").split(";")[0]
        return code, page, cookie

    def fresh_accounts(self):
        type(self).mode = "accounts"
        for p in (self.acc, self.ses):
            if os.path.exists(p):
                os.unlink(p)
        accounts._resets.clear()

    def set_password(self, pw):
        with open(self.pw, "w") as f:
            json.dump({"password": pw}, f)

    def test_health_is_open(self):
        code, body, _ = self.get("/health")
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)["message"], "Watching 1 aircraft")

    def test_open_when_sign_in_is_off(self):
        type(self).mode = "off"
        self.set_password("correct-horse")
        code, body, _ = self.get("/api/state")
        self.assertEqual((code, json.loads(body)), (200, {"watchers": [], "secret": False}))
        self.assertEqual(self.get("/")[0], 200)
        self.assertEqual(self.get("/login")[2].get("Location"), "./")

    def test_no_password_file_locks_everything(self):
        if os.path.exists(self.pw):
            os.unlink(self.pw)
        self.assertEqual(self.get("/", "x")[0], 503)

    def test_shared_password(self):
        self.set_password("correct-horse")
        code, _, headers = self.get("/")
        self.assertEqual((code, headers.get("Location")), (303, "login"))  # the sign-in form, not a browser prompt
        self.assertNotIn("WWW-Authenticate", headers)
        code, body, _ = self.get("/login")
        self.assertIn("Sign in", body)
        self.assertNotIn('name="username" value=""' + ' autocomplete', body)
        self.assertEqual(self.get("/api/state")[0], 401)
        self.assertEqual(self.get("/api/state", "wrong")[0], 401)
        code, body, headers = self.get("/api/state", "correct-horse")  # scripts may still use Basic auth
        self.assertEqual((code, json.loads(body)), (200, {"watchers": [], "secret": False}))
        self.assertEqual(headers.get("Cache-Control"), "no-store")
        self.assertEqual(self.login("wrong")[0], 401)
        code, _, cookie = self.login("correct-horse")
        self.assertEqual(code, 303)
        self.assertTrue(cookie.startswith("tw_session="))
        self.assertEqual(self.get("/", cookie=cookie)[0], 200)
        self.assertEqual(self.get("/../../etc/passwd", cookie=cookie)[0], 404)
        self.set_password("new-password")  # reset in StartOS Actions: old sessions stop working
        self.assertEqual(self.get("/api/state", cookie=cookie)[0], 401)

    def test_cookie_flags(self):
        self.set_password("correct-horse")
        body = urllib.parse.urlencode({"password": "correct-horse"})
        _, _, headers = self.request("POST", "/login", body, {"Content-Type": "application/x-www-form-urlencoded",
                                                              "X-Forwarded-Proto": "https"})
        flags = headers["Set-Cookie"]
        for flag in ("HttpOnly", "SameSite=Lax", "Secure", "Path=/"):
            self.assertIn(flag, flags)
        _, _, headers = self.request("POST", "/login", body, {"Content-Type": "application/x-www-form-urlencoded"})
        self.assertNotIn("Secure", headers["Set-Cookie"])  # plain http (LAN, Tor): a Secure cookie would be dropped

    def test_login_from_another_site_is_refused(self):
        self.set_password("correct-horse")
        body = urllib.parse.urlencode({"password": "correct-horse"})
        code, _, _ = self.request("POST", "/login", body, {"Content-Type": "application/x-www-form-urlencoded",
                                                           "Origin": "https://evil.example"})
        self.assertEqual(code, 403)

    def test_guessing_is_slowed(self):
        self.set_password("correct-horse")
        for _ in range(5):
            self.assertEqual(self.login("guess")[0], 401)
        code, page, _ = self.login("correct-horse")
        self.assertEqual(code, 429)
        self.assertIn("Too many tries", page)

    def test_family_accounts(self):
        self.fresh_accounts()
        accounts.create("mom", "Mom", "mom-password", "admin", ["tw-mom"], self.acc)
        accounts.create("kid", "Kid", "kid-password", "member", ["tw-kid"], self.acc)
        self.assertIn('name="username"', self.get("/login")[1])
        self.assertEqual(self.login("kid-password", "mom")[0], 401)
        code, _, cookie = self.login("kid-password", "Kid")  # usernames ignore case
        self.assertEqual(code, 303)
        self.assertEqual(self.get("/api/state", cookie=cookie)[0], 200)
        self.assertEqual(self.seen[-1]["account"]["username"], "kid")
        self.assertFalse(self.seen[-1]["admin"])
        self.assertNotIn("hash", self.seen[-1]["account"])
        post = lambda path, cookie: self.request(  # noqa: E731
            "POST", path, "{}", {"Content-Type": "application/json", "X-TailWatcher": "1", "Cookie": cookie})
        code, body, _ = post("/api/trip", cookie)
        self.assertEqual(json.loads(body)["who"], "kid")
        code, _, headers = post("/api/logout", cookie)
        self.assertEqual(code, 200)
        self.assertIn("Max-Age=0", headers["Set-Cookie"])
        self.assertEqual(self.get("/api/state", cookie=cookie)[0], 401)
        _, _, cookie = self.login("mom-password", "mom")
        self.get("/api/state", cookie=cookie)
        self.assertTrue(self.seen[-1]["admin"])
        accounts.update(self.seen[-1]["account"]["id"], password="another-password", path=self.acc)
        # (update() signs out the default sessions file; the server here uses its own)
        accounts.end_for(self.seen[-1]["account"]["id"], self.ses)
        self.assertEqual(self.get("/api/state", cookie=cookie)[0], 401)

    def test_forgot_password(self):
        self.fresh_accounts()
        accounts.create("kid", "Kid", "kid-password", "member", ["tw-kid"], self.acc)
        self.assertIn("login?forgot=1", self.get("/login")[1])
        self.assertIn('action="forgot"', self.get("/login?forgot=1")[1])
        code, page, _ = self.form("/forgot", username="Kid")
        self.assertEqual(code, 200)
        self.assertIn('action="reset"', page)
        code_sent = self.codes[-1]
        self.assertRegex(code_sent, r"^\d{6}$")
        page_for_nobody = self.form("/forgot", username="nobody")[1]  # same page: usernames can't be probed
        self.assertIn('action="reset"', page_for_nobody)
        self.assertIsNone(self.codes[-1])
        self.form("/forgot", username="kid")
        self.assertIsNone(self.codes[-1])  # one code a minute
        wrong = "000000" if code_sent != "000000" else "111111"
        code, page, _ = self.form("/reset", username="kid", code=wrong, password="new-password", confirm="new-password")
        self.assertEqual(code, 400)
        self.assertIn("didn&#x27;t match", page)
        code, page, _ = self.form("/reset", username="kid", code=code_sent, password="new-password", confirm="other")
        self.assertIn("don&#x27;t match", page)
        code, _, cookie = self.form("/reset", username="kid", code=code_sent, password="new-password",
                                    confirm="new-password")
        self.assertEqual(code, 303)
        self.assertEqual(self.get("/api/state", cookie=cookie)[0], 200)  # signed straight in
        self.assertEqual(self.login("new-password", "kid")[0], 303)
        code, page, _ = self.form("/reset", username="kid", code=code_sent, password="again-password",
                                  confirm="again-password")
        self.assertIn("expired", page)  # used up

    def test_forgot_is_only_for_accounts(self):
        self.set_password("correct-horse")
        self.assertNotIn("forgot", self.get("/login")[1])
        self.assertEqual(self.form("/forgot", username="kid")[0], 303)

    def test_sign_up_link(self):
        self.fresh_accounts()
        code, _, cookie = self.form("/join/good-token-0123456789abc", name="Grandma", username="grandma",
                                    password="grandma-pass", confirm="grandma-pass")
        self.assertEqual(code, 303)
        self.assertEqual(self.get("/api/state", cookie=cookie)[0], 200)
        self.assertEqual(self.seen[-1]["account"]["username"], "grandma")
        code, _, _ = self.request("POST", "/join/good-token-0123456789abc", "name=x",
                                  {"Content-Type": "application/x-www-form-urlencoded", "Origin": "https://evil.example"})
        self.assertEqual(code, 403)
        for _ in range(5):
            self.assertEqual(self.form("/join/guess-guess-guess-guess", name="x")[0], 404)
        self.assertEqual(self.form("/join/guess-guess-guess-guess", name="x")[0], 429)  # guessing links is slowed

    def test_sign_up_page(self):
        inv = {"token": "tok<en>", "from": "Sam <b>", "watcher": True}
        page = web.signup_page(inv, "Taken <x>", "Gr<an>dma", "gma")
        self.assertIn("Sam &lt;b&gt; invited you", page)
        self.assertIn("Taken &lt;x&gt;", page)
        self.assertIn('value="Gr&lt;an&gt;dma"', page)
        self.assertIn('action="tok&lt;en&gt;"', page)
        self.assertIn('href="../icon.svg"', page)


class PageTest(unittest.TestCase):
    """Cheap structural checks on the single-file dashboard; 0.10/0.11 shipped
    with JavaScript accidentally pasted into the <style> block."""

    def setUp(self):
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "index.html")) as f:
            self.page = f.read()
        self.css = self.page[self.page.index("<style>"):self.page.index("</style>")]
        self.js = self.page[self.page.index("<script>"):self.page.index("</script>")]

    def test_no_script_in_the_stylesheet(self):
        for marker in ("function ", "=>", "const ", "return "):
            self.assertNotIn(marker, self.css)

    def test_help_links_point_at_real_guide_sections(self):
        import re
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "instructions.md")) as f:
            headings = re.findall(r"^#{2,3}\s+(.*)$", f.read(), re.M)
        slugs = {re.sub(r"[^a-z0-9]+", "-", h.lower()).strip("-") for h in headings}
        linked = set(re.findall(r'data-section="([a-z0-9-]+)"', self.page)) | {"for-people-getting-alerts"}
        self.assertEqual(linked - slugs, set())

    def test_help_is_a_full_page_that_opens_before_the_state_loads(self):
        self.assertIn('<dialog id="help" class="help-page"', self.page)
        body = self.js[self.js.index("function onAction(btn) {"):]
        self.assertLess(body.index('"help"'), body.index("if (!LAST) return;"))

    def test_helpers_used_in_templates_are_defined(self):
        import re
        called = set(re.findall(r"\$\{([a-zA-Z_]\w*)\(", self.js))
        defined = set(re.findall(r"(?:function\s+|const\s+)([a-zA-Z_]\w*)", self.js))
        builtin = {"esc", "encodeURIComponent", "String", "Math", "Number", "JSON", "Date", "new"}
        self.assertEqual(called - defined - builtin, set())


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



class PostSizeTest(unittest.TestCase):
    def test_only_import_takes_a_whole_email(self):
        srv = web.serve(0, Health(), lambda: {}, password_path="/nonexistent", web_dir=tempfile.mkdtemp(),
                        post=lambda path, data, v: (200, {"ok": True, "size": len(data.get("text", ""))}))
        try:
            body = json.dumps({"text": "x" * 300_000}).encode()
            for path, want in (("/api/import", 200), ("/api/trip", 400)):
                req = urllib.request.Request(f"http://127.0.0.1:{srv.server_address[1]}{path}", data=body,
                                             headers={"Content-Type": "application/json", "X-TailWatcher": "1"})
                try:
                    with urllib.request.urlopen(req, timeout=5) as r:
                        code = r.status
                except urllib.error.HTTPError as e:
                    code = e.code
                self.assertEqual(code, want, path)
        finally:
            srv.shutdown()
            srv.server_close()


if __name__ == "__main__":
    unittest.main()
