# Runbook

**Pager fires: `FROZEN (BUDGET_EXCEEDED)`**
1. `sentinel status` — confirm which sandbox, spend, owner.
2. Contact owner. Inspect for compromise (cryptomining, leaked key) before releasing anything.
3. Data needed? A human with authority may snapshot volumes within `frozen_grace_hours`. Sentinel will terminate after that window by design.
4. Never raise a budget in place. Open a new sandbox with a new ticket; the audit trail stays clean.

**Audit verification (run daily from a separate host with the key in a vault):** `sentinel verify` → exit code 2 means tampering.

**Rollout plan:** week 1 reaper `dry_run=true` · week 2 Sentinel warn-only (`freeze_at: 99`) · week 3 enforce on one cost center · week 4 org-wide.

**Known limits (be honest with your board):**
- Control loop is 60 s. A burst faster than that overshoots by up to `rate × 60 s` — the demo shows ~$6 on a $200 budget. Mitigate with `predictive_horizon_ticks` and Layer 2.
- AWS Budgets data lags up to ~8–24 h; it is a backstop, not a primary.
- Usage-based services (LLM tokens, egress) need metering hooks in `drain_usage`.
