import os
import tempfile
import unittest

import accounts
import tailwatcher as tw


class AccountsTest(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp()
        self.path, self.ses = os.path.join(d, "accounts.json"), os.path.join(d, "sessions.json")
        self.old_sessions, accounts.SESSIONS_PATH = accounts.SESSIONS_PATH, self.ses

    def tearDown(self):
        accounts.SESSIONS_PATH = self.old_sessions

    def test_passwords_are_hashed(self):
        h = accounts.hash_password("correct horse")
        self.assertTrue(h.startswith("scrypt$"))
        self.assertNotIn("correct", h)
        self.assertTrue(accounts.check_password("correct horse", h))
        self.assertFalse(accounts.check_password("wrong horse", h))
        self.assertFalse(accounts.check_password("x", "garbage"))

    def test_create_and_sign_in(self):
        a = accounts.create("Mom", "Mom", "mom-password", "admin", ["tw-mom"], self.path)
        self.assertEqual(a["username"], "mom")
        self.assertNotIn("hash", a)
        self.assertEqual(accounts.authenticate("MOM", "mom-password", self.path)["id"], a["id"])
        self.assertIsNone(accounts.authenticate("mom", "nope", self.path))
        self.assertIsNone(accounts.authenticate("dad", "mom-password", self.path))
        self.assertIsNotNone(accounts.find(a["id"], self.path)["last_login"])
        with self.assertRaises(accounts.AccountError):
            accounts.create("mom", "Other", "another-password", path=self.path)  # taken
        with self.assertRaises(accounts.AccountError):
            accounts.create("dad", "Dad", "short", path=self.path)
        with self.assertRaises(accounts.AccountError):
            accounts.create("bad name", "Dad", "long-enough", path=self.path)

    def test_one_owner_per_watcher(self):
        mom = accounts.create("mom", "Mom", "mom-password", "admin", ["tw-a", "tw-b"], self.path)
        kid = accounts.create("kid", "Kid", "kid-password", "member", ["tw-b"], self.path)
        data = accounts.load(self.path)
        self.assertEqual(accounts.owner_of("tw-b", data)["id"], kid["id"])
        self.assertEqual(accounts.owner_of("tw-a", data)["id"], mom["id"])
        accounts.assign("tw-b", mom["id"], self.path)
        self.assertEqual(accounts.owner_of("tw-b", accounts.load(self.path))["id"], mom["id"])
        accounts.rename_topic("tw-b", "tw-c", self.path)
        self.assertEqual(accounts.find(mom["id"], self.path)["watchers"], ["tw-a", "tw-c"])
        accounts.drop_topic("tw-a", self.path)
        self.assertIsNone(accounts.owner_of("tw-a", accounts.load(self.path)))

    def test_always_an_admin(self):
        mom = accounts.create("mom", "Mom", "mom-password", "admin", path=self.path)
        kid = accounts.create("kid", "Kid", "kid-password", path=self.path)
        with self.assertRaises(accounts.AccountError):
            accounts.update(mom["id"], role="member", path=self.path)
        with self.assertRaises(accounts.AccountError):
            accounts.delete(mom["id"], self.path)
        accounts.update(kid["id"], role="admin", path=self.path)
        accounts.update(mom["id"], role="member", path=self.path)
        self.assertEqual(accounts.delete(mom["id"], self.path), [])

    def test_admin_made_when_accounts_are_turned_on_in_configure(self):
        made = accounts.ensure_admin("webui-password", ["tw-a", "tw-b"], self.path)
        self.assertEqual((made["username"], made["role"], made["watchers"]), ("admin", "admin", ["tw-a", "tw-b"]))
        self.assertIsNotNone(accounts.authenticate("admin", "webui-password", self.path))
        self.assertIsNone(accounts.ensure_admin("webui-password", ["tw-a"], self.path))  # only once

    def test_password_reset_from_startos_or_the_cli(self):
        mom = accounts.create("mom", "Mom", "mom-password", "admin", path=self.path)
        self.assertIsNone(accounts.sync_recovery("generated-at-install", self.path))  # first look: just remembered
        self.assertIsNotNone(accounts.authenticate("mom", "mom-password", self.path))
        token = accounts.new_session(mom["id"])
        self.assertIsNone(accounts.sync_recovery("generated-at-install", self.path))  # unchanged
        self.assertEqual(accounts.sync_recovery("reset-in-actions", self.path), "mom")
        self.assertIsNotNone(accounts.authenticate("mom", "reset-in-actions", self.path))
        self.assertIsNone(accounts.session(token))  # signed out everywhere

    def test_sessions(self):
        token = accounts.new_session("a_1", now=1000)
        with open(self.ses) as f:
            self.assertNotIn(token, f.read())  # only a hash is stored
        self.assertEqual(accounts.session(token, now=2000)["account"], "a_1")
        self.assertIsNone(accounts.session("made-up", now=2000))
        self.assertIsNone(accounts.session(token, now=1000 + 31 * 86400))  # expired
        keep, other = accounts.new_session("a_1"), accounts.new_session("a_1")
        accounts.end_for("a_1", keep=keep)
        self.assertIsNotNone(accounts.session(keep))
        self.assertIsNone(accounts.session(other))
        accounts.end(keep)
        self.assertIsNone(accounts.session(keep))

    def test_throttle(self):
        t = accounts.Throttle(limit=3, window=60, wait=30)
        for i in range(3):
            self.assertEqual(t.blocked(["ip:1"], now=100 + i), 0)
            t.failed(["ip:1"], now=100 + i)
        self.assertGreater(t.blocked(["ip:1"], now=105), 0)
        self.assertEqual(t.blocked(["ip:1"], now=140), 0)  # waited
        self.assertEqual(t.blocked(["ip:2"], now=105), 0)


class ScopeTest(unittest.TestCase):
    def test_each_person_sees_their_own_watchers(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "accounts.json")
        mom = accounts.create("mom", "Mom", "mom-password", "admin", ["tw-mom"], path)
        kid = accounts.create("kid", "Kid", "kid-password", "member", ["tw-kid"], path)
        cur = {"watchers": [{"topic": t} for t in ("tw-mom", "tw-kid", "tw-new")]}
        data = accounts.load(path)
        view = lambda a, admin: {"account": a, "admin": admin}  # noqa: E731
        self.assertEqual(tw.scope(view(kid, False), cur, data), {"tw-kid"})
        self.assertEqual(tw.scope(view(mom, True), cur, data), {"tw-mom", "tw-new"})  # nobody owns tw-new yet
        self.assertEqual(tw.scope({"account": None, "admin": True}, cur, data), {"tw-mom", "tw-kid", "tw-new"})
        self.assertEqual(tw.scope(None, cur, data), {"tw-mom", "tw-kid", "tw-new"})

    def test_watcher_ids_hide_topics(self):
        self.assertNotIn("tw-mom", tw.wid("tw-mom"))
        self.assertEqual(tw.wid("tw-mom"), tw.wid("tw-mom"))
        self.assertNotEqual(tw.wid("tw-mom"), tw.wid("tw-dad"))


class TimeZoneTest(unittest.TestCase):
    def test_each_watcher_can_have_their_own(self):
        import json
        p = os.path.join(tempfile.mkdtemp(), "config.json")
        with open(p, "w") as f:
            json.dump({"timeZone": "America/Chicago", "watchers": [
                {"name": "Grandma", "topic": "tw-g", "timeZone": "America/Phoenix"}, {"name": "Me", "topic": "tw-me"}]}, f)
        w = {x["name"]: x for x in tw.load_config(p)["watchers"]}
        self.assertEqual((w["Grandma"]["time_zone"], w["Grandma"]["tz_set"]), ("America/Phoenix", "America/Phoenix"))
        self.assertEqual((w["Me"]["time_zone"], w["Me"]["tz_set"]), ("America/Chicago", ""))


if __name__ == "__main__":
    unittest.main()
