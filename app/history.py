"""Alert history: every message TailWatcher sends or receives, for the web UI.

Kept in /data/history.json as a ring buffer of the most recent entries.
"""

import json
import os
import threading
import time

HISTORY_PATH = os.environ.get("TW_HISTORY", "/data/history.json")
LIMIT = 300


class History:
    def __init__(self, path=None, limit=LIMIT):
        self.path, self.limit = path or HISTORY_PATH, limit
        self.lock = threading.Lock()
        self.dirty = False
        try:
            with open(self.path) as f:
                self.entries = json.load(f)[-limit:]
        except (OSError, ValueError):
            self.entries = []

    def add(self, direction, topic, message, title=None, kind="reply", status="sent", now=None):
        """direction: "out" (sent by TailWatcher) or "in" (a text command).
        kind: alert / trip / reply / command. status: sent / retrying / refused / received."""
        entry = {"t": round(now or time.time()), "dir": direction, "topic": topic, "kind": kind,
                 "title": title or "", "message": message or "", "status": status}
        with self.lock:
            self.entries.append(entry)
            del self.entries[:-self.limit]
            self.dirty = True

    def recent(self, n=150):
        with self.lock:
            return list(reversed(self.entries[-n:]))

    def save(self):
        with self.lock:
            if not self.dirty:
                return
            data, self.dirty = list(self.entries), False
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, self.path)
