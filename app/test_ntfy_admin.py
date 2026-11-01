import json
import os
import tempfile
import unittest

import edits
import ntfy_admin


class FakeNtfy:
    """Records calls and answers like NTFY's admin API."""

    def __init__(self, admin_pw="right", existing=()):
        self.admin_pw, self.users, self.calls = admin_pw, set(existing), []

    def __call__(self, base, method, path, auth=None, body=None):
        self.calls.append((method, path, body))
        if path == "/v1/users" and method == "GET":
            return (200, [{"username": u} for u in self.users]) if auth == ("admin", self.admin_pw) else (401, {})
        if path == "/v1/users" and method == "POST":
            if body["username"] in self.users:
                return 409, {}
            self.users.add(body["username"])
            return 200, {}
        if path == "/v1/account/token":
            return 200, {"token": "tk_new123"}
        return 200, {}


class SetupTest(unittest.TestCase):
    def test_open_setup(self):
        ntfy = FakeNtfy()
        token, steps = ntfy_admin.setup("http://ntfy", "right", "open", call=ntfy)
        self.assertEqual(token, "tk_new123")
        grants = [c[2] for c in ntfy.calls if c[1] == "/v1/users/access" and c[0] == "PUT"]
        self.assertIn({"username": "tailwatcher", "topic": "tw-*", "permission": "read-write"}, grants)
        self.assertIn({"username": "*", "topic": "tw-*", "permission": "read-write"}, grants)
        # pre-0.12 tailwatcher_… topics: TailWatcher's own user only, never anonymous
        self.assertIn({"username": "tailwatcher", "topic": "tailwatcher*", "permission": "read-write"}, grants)
        self.assertNotIn({"username": "*", "topic": "tailwatcher*", "permission": "read-write"}, grants)
        self.assertIn("your admin password was not stored", steps[-1])
        # NTFY's default is a 72-hour token; TailWatcher's must never expire
        mint = [c[2] for c in ntfy.calls if c[1] == "/v1/account/token"]
        self.assertEqual(mint, [{"label": "TailWatcher", "expires": 0}])

    def test_rerun_resets_user_and_login_mode_closes_anonymous(self):
        ntfy = FakeNtfy(existing={"tailwatcher"})
        _, steps = ntfy_admin.setup("http://ntfy", "right", "login", call=ntfy)
        self.assertIn(("PUT", "/v1/users"), [(c[0], c[1]) for c in ntfy.calls])
        self.assertIn(("DELETE", "/v1/users/access", {"username": "*", "topic": "tw-*"}), ntfy.calls)
        self.assertIn("Reset TailWatcher's NTFY user", steps)

    def test_errors(self):
        with self.assertRaisesRegex(ntfy_admin.SetupError, "isn't NTFY's admin password"):
            ntfy_admin.setup("http://ntfy", "wrong", call=FakeNtfy())
        with self.assertRaisesRegex(ntfy_admin.SetupError, "isn't installed"):
            ntfy_admin.setup("", "right", call=FakeNtfy())

    def test_person_login(self):
        ntfy = FakeNtfy(existing={"admin", "tailwatcher", "dad"})
        user, pw = ntfy_admin.create_login("http://ntfy", "right", "Dad", "tw-dad-x", call=ntfy)
        self.assertEqual(user, "dad2")                                      # "dad" was taken
        self.assertEqual(len(pw), 16)
        self.assertIn(("PUT", "/v1/users/access", {"username": "dad2", "topic": "tw-dad-x",
                                                   "permission": "read-write"}), ntfy.calls)
        self.assertEqual(ntfy_admin.username_for("Admin", set()), "twadmin")
        ntfy = FakeNtfy()
        ntfy_admin.create_login("http://ntfy", "right", "Mom", ["tw-mom-x", "tw-mom-planes-y", ""], call=ntfy)
        self.assertEqual([c[2]["topic"] for c in ntfy.calls if c[1] == "/v1/users/access"],
                         ["tw-mom-x", "tw-mom-planes-y"])


class KeepTokenTest(unittest.TestCase):
    def account(self, tokens, status=200):
        calls = []

        def call(base, method, path, auth=None, body=None):
            calls.append((method, path, auth, body))
            if method == "GET":
                return status, {"username": "tailwatcher", "tokens": tokens}
            return 200, {}
        return calls, call

    def test_makes_setup_token_permanent(self):
        calls, call = self.account([{"token": "tk_a", "label": "TailWatcher", "expires": 1793000000}])
        self.assertTrue(ntfy_admin.keep_token("http://ntfy", "tk_a", call=call))
        self.assertEqual(calls[-1], ("PATCH", "/v1/account/token", "tk_a", {"token": "tk_a", "expires": 0}))

    def test_leaves_other_tokens_alone(self):
        for tokens in ([{"token": "tk_a", "label": "TailWatcher"}],          # already never expires
                       [{"token": "tk_a", "label": "mine", "expires": 1}],   # made by hand
                       [{"token": "tk_b", "label": "TailWatcher", "expires": 1}]):
            calls, call = self.account(tokens)
            self.assertFalse(ntfy_admin.keep_token("http://ntfy", "tk_a", call=call))
            self.assertEqual([c[0] for c in calls], ["GET"])
        self.assertFalse(ntfy_admin.keep_token("http://ntfy", "", call=call))

    def test_refused_token(self):
        calls, call = self.account([], status=401)
        self.assertIsNone(ntfy_admin.keep_token("http://ntfy", "tk_a", call=call))
        self.assertEqual(len(calls), 1)


class SettingsTest(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "config.json")
        with open(self.path, "w") as f:
            json.dump({"watchers": [], "aerodataboxKey": "keep", "ntfyToken": "tk_keep"}, f)

    def read(self):
        with open(self.path) as f:
            return json.load(f)

    def test_saves_only_given_values_and_keeps_secrets(self):
        edits.save_settings(self.path, {"pollSeconds": "90", "timeZone": "Asia/Tokyo", "aerodataboxKey": "",
                                        "textCommands": False, "ntfyServer": "public"})
        c = self.read()
        self.assertEqual((c["pollSeconds"], c["timeZone"], c["textCommands"]), (90, "Asia/Tokyo", False))
        self.assertEqual((c["aerodataboxKey"], c["ntfyToken"]), ("keep", "tk_keep"))  # blank = unchanged
        edits.save_settings(self.path, {"clearAerodatabox": True})
        self.assertEqual(self.read()["aerodataboxKey"], "")

    def test_rejects_bad_values(self):
        for bad in ({"pollSeconds": 5}, {"timeZone": "Mars/Base"}, {"ntfyServer": "custom"},
                    {"ntfyServer": "custom", "ntfyCustomUrl": "ntfy.example.com"}, {"ntfyToken": "nope"}):
            with self.assertRaises(edits.EditError, msg=bad):
                edits.save_settings(self.path, bad)


if __name__ == "__main__":
    unittest.main()
