"""Tamper-evident audit log: every record is HMAC-chained to the previous one."""
from __future__ import annotations

import hashlib
import hmac
import json
import os


class AuditLog:
    GENESIS = "0" * 64

    def __init__(self, path: str, key: bytes | None = None, clock=None):
        self.path = path
        self.key = key or os.environ.get("SENTINEL_AUDIT_KEY", "dev-only-key").encode()
        self.clock = clock
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._seq, self._prev = self._tail()

    def _mac(self, prev: str, body: str) -> str:
        return hmac.new(self.key, (prev + body).encode(), hashlib.sha256).hexdigest()

    def _tail(self):
        seq, prev = 0, self.GENESIS
        if os.path.exists(self.path):
            with open(self.path) as f:
                for line in f:
                    rec = json.loads(line)
                    seq, prev = rec["seq"], rec["hash"]
        return seq, prev

    def record(self, event: str, **data) -> dict:
        self._seq += 1
        ts = self.clock.now().isoformat() if self.clock else ""
        body = json.dumps({"seq": self._seq, "ts": ts, "event": event, "data": data}, sort_keys=True)
        rec = {"seq": self._seq, "ts": ts, "event": event, "data": data,
               "prev": self._prev, "hash": self._mac(self._prev, body)}
        with open(self.path, "a") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")
        self._prev = rec["hash"]
        return rec

    def verify(self):
        """Return (ok, first_bad_seq)."""
        prev = self.GENESIS
        if not os.path.exists(self.path):
            return True, None
        with open(self.path) as f:
            for line in f:
                rec = json.loads(line)
                body = json.dumps({"seq": rec["seq"], "ts": rec["ts"], "event": rec["event"],
                                   "data": rec["data"]}, sort_keys=True)
                if rec["prev"] != prev or not hmac.compare_digest(rec["hash"], self._mac(prev, body)):
                    return False, rec["seq"]
                prev = rec["hash"]
        return True, None

    def events(self):
        if not os.path.exists(self.path):
            return []
        with open(self.path) as f:
            return [json.loads(l) for l in f]
