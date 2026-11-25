from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field


def _iso(d):
    return d.isoformat() if d else None


def _parse(s):
    return dt.datetime.fromisoformat(s) if s else None


@dataclass
class Resource:
    id: str
    kind: str            # compute | database | gpu | storage
    type: str            # e.g. m5.xlarge
    region: str
    hourly_usd: float
    stopped_hourly_usd: float = 0.0
    state: str = "running"   # running | stopped | terminated

    @property
    def rate(self) -> float:
        return {"running": self.hourly_usd, "stopped": self.stopped_hourly_usd}.get(self.state, 0.0)


@dataclass
class Sandbox:
    id: str
    owner: str
    cost_center: str
    budget_usd: float
    created_at: dt.datetime
    expires_at: dt.datetime
    last_accrual: dt.datetime
    ticket: str = ""
    principal: str = ""              # IAM role / service principal bound to the sandbox
    spend_usd: float = 0.0
    state: str = "ACTIVE"            # ACTIVE | FROZEN | TERMINATED
    reason: str = ""
    extensions: int = 0
    frozen_at: dt.datetime | None = None
    credentials_revoked: bool = False
    pending_usage_usd: float = 0.0   # usage-based spend not yet metered (egress, API calls, tokens)
    warned: list = field(default_factory=list)
    expiry_warned: list = field(default_factory=list)
    resources: list = field(default_factory=list)

    @property
    def burn_rate(self) -> float:
        return sum(r.rate for r in self.resources)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "owner": self.owner, "cost_center": self.cost_center,
            "budget_usd": self.budget_usd, "created_at": _iso(self.created_at),
            "expires_at": _iso(self.expires_at), "last_accrual": _iso(self.last_accrual),
            "ticket": self.ticket, "principal": self.principal, "spend_usd": self.spend_usd,
            "state": self.state, "reason": self.reason, "extensions": self.extensions,
            "frozen_at": _iso(self.frozen_at), "credentials_revoked": self.credentials_revoked,
            "pending_usage_usd": self.pending_usage_usd, "warned": self.warned,
            "expiry_warned": self.expiry_warned,
            "resources": [r.__dict__ for r in self.resources],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Sandbox":
        d = dict(d)
        for k in ("created_at", "expires_at", "last_accrual", "frozen_at"):
            d[k] = _parse(d.get(k))
        d["resources"] = [Resource(**r) for r in d.get("resources", [])]
        return cls(**d)
