from __future__ import annotations

import json
from dataclasses import dataclass, field, fields


@dataclass
class Policy:
    name: str = "default"
    default_ttl_hours: float = 8
    max_ttl_hours: float = 72
    max_budget_usd: float = 500
    warn_at: list = field(default_factory=lambda: [0.5, 0.8])
    freeze_at: float = 1.0          # stop compute + revoke credentials
    kill_at: float = 1.10           # hard terminate if spend still climbs
    frozen_grace_hours: float = 4   # frozen sandboxes are terminated after this
    predictive_horizon_ticks: int = 2
    tick_seconds: int = 60
    max_extensions: int = 2
    max_extension_hours: float = 24
    max_active_per_owner: int = 2
    cost_center_cap_usd: float = 5000
    require_ticket: bool = False
    four_eyes_extension: bool = True
    unknown_rate_hourly: float = 5.0   # conservative price for unpriced resources
    allowed_regions: list = field(default_factory=lambda: ["us-east-1", "eu-west-1"])
    allowed_types: dict = field(default_factory=lambda: {
        "t3.medium": 0.0416, "m5.xlarge": 0.192, "r5.2xlarge": 0.504,
        "g5.xlarge": 1.006, "p3.2xlarge": 3.06, "db.r5.large": 0.25,
    })

    @classmethod
    def load(cls, path: str) -> "Policy":
        with open(path) as f:
            raw = json.load(f)
        known = {f.name for f in fields(cls)}
        unknown = set(raw) - known
        if unknown:
            raise ValueError(f"unknown policy keys: {sorted(unknown)}")
        return cls(**raw)
