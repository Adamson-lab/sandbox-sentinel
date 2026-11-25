import json
import sqlite3

from .models import Sandbox


class Ledger:
    def __init__(self, path=":memory:"):
        self.db = sqlite3.connect(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS sandboxes (id TEXT PRIMARY KEY, doc TEXT NOT NULL)")
        self.db.commit()

    def save(self, sb: Sandbox):
        self.db.execute("INSERT OR REPLACE INTO sandboxes VALUES (?, ?)", (sb.id, json.dumps(sb.to_dict())))
        self.db.commit()

    def get(self, sid: str) -> Sandbox:
        row = self.db.execute("SELECT doc FROM sandboxes WHERE id=?", (sid,)).fetchone()
        if not row:
            raise KeyError(f"no such sandbox: {sid}")
        return Sandbox.from_dict(json.loads(row[0]))

    def all(self):
        return [Sandbox.from_dict(json.loads(r[0])) for r in self.db.execute("SELECT doc FROM sandboxes")]

    def live(self):
        return [s for s in self.all() if s.state != "TERMINATED"]
