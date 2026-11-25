from __future__ import annotations

import datetime as dt
import uuid

from .models import Resource, Sandbox


class PolicyViolation(Exception):
    pass


class Sentinel:
    def __init__(self, ledger, policy, provider, audit, notifier, clock):
        self.ledger, self.policy, self.provider = ledger, policy, provider
        self.audit, self.notify, self.clock = audit, notifier, clock

    # ---------- guardrails at the door ----------
    def _deny(self, sid, why, **ctx):
        self.audit.record("DENIED", sandbox=sid, why=why, **ctx)
        raise PolicyViolation(why)

    def request(self, owner, cost_center, budget_usd, ttl_hours=None, ticket="", principal=""):
        p, now = self.policy, self.clock.now()
        ttl = ttl_hours if ttl_hours is not None else p.default_ttl_hours
        live = self.ledger.live()
        if ttl > p.max_ttl_hours:
            self._deny("-", f"ttl {ttl}h exceeds max {p.max_ttl_hours}h", owner=owner)
        if budget_usd > p.max_budget_usd:
            self._deny("-", f"budget ${budget_usd} exceeds max ${p.max_budget_usd}", owner=owner)
        if p.require_ticket and not ticket:
            self._deny("-", "change ticket required", owner=owner)
        if sum(1 for s in live if s.owner == owner) >= p.max_active_per_owner:
            self._deny("-", f"{owner} already has {p.max_active_per_owner} active sandboxes", owner=owner)
        committed = sum(s.budget_usd for s in live if s.cost_center == cost_center)
        if committed + budget_usd > p.cost_center_cap_usd:
            self._deny("-", f"cost center {cost_center} cap ${p.cost_center_cap_usd} would be exceeded",
                       owner=owner)
        sb = Sandbox(id="sbx-" + uuid.uuid4().hex[:8], owner=owner, cost_center=cost_center,
                     budget_usd=budget_usd, created_at=now, expires_at=now + dt.timedelta(hours=ttl),
                     last_accrual=now, ticket=ticket, principal=principal)
        self.ledger.save(sb)
        self.audit.record("CREATED", sandbox=sb.id, owner=owner, cost_center=cost_center,
                          budget=budget_usd, ttl_hours=ttl, expires=sb.expires_at.isoformat())
        return sb

    def provision(self, sid, kind, rtype, region):
        p, sb, now = self.policy, self.ledger.get(sid), self.clock.now()
        if sb.state != "ACTIVE":
            self._deny(sid, f"sandbox is {sb.state}")
        if rtype not in p.allowed_types:
            self._deny(sid, f"instance type {rtype} not on allow-list")
        if region not in p.allowed_regions:
            self._deny(sid, f"region {region} not allowed")
        rate = p.allowed_types[rtype]
        hours_left = max((sb.expires_at - now).total_seconds() / 3600, 0)
        worst = sb.spend_usd + (sb.burn_rate + rate) * hours_left
        if worst > sb.budget_usd:
            self._deny(sid, f"worst-case cost ${worst:.2f} over TTL exceeds budget ${sb.budget_usd:.2f}")
        res = Resource("res-" + uuid.uuid4().hex[:6], kind, rtype, region, rate, rate * 0.05)
        self.provider.launch(sb, res)
        sb.resources.append(res)
        self.ledger.save(sb)
        self.audit.record("PROVISIONED", sandbox=sid, resource=res.id, type=rtype, hourly=rate,
                          worst_case=round(worst, 2))
        return res

    def extend(self, sid, hours, approver):
        p, sb = self.policy, self.ledger.get(sid)
        if sb.state != "ACTIVE":
            self._deny(sid, f"cannot extend a {sb.state} sandbox")
        if p.four_eyes_extension and approver == sb.owner:
            self._deny(sid, "four-eyes: owner cannot approve own extension")
        if sb.extensions >= p.max_extensions or hours > p.max_extension_hours:
            self._deny(sid, "extension limit reached")
        new_exp = sb.expires_at + dt.timedelta(hours=hours)
        if (new_exp - sb.created_at).total_seconds() / 3600 > p.max_ttl_hours:
            self._deny(sid, f"extension would exceed max TTL {p.max_ttl_hours}h")
        sb.expires_at, sb.extensions = new_exp, sb.extensions + 1
        sb.expiry_warned = []
        self.ledger.save(sb)
        self.audit.record("EXTENDED", sandbox=sid, hours=hours, approver=approver, expires=new_exp.isoformat())

    def inject_usage(self, sid, usd):
        """Simulation hook: usage-based spend (egress, API/LLM calls) arriving between ticks."""
        sb = self.ledger.get(sid)
        sb.pending_usage_usd += usd
        self.ledger.save(sb)

    # ---------- the control loop ----------
    def tick(self):
        now, actions = self.clock.now(), []
        for sb in self.ledger.live():
            self._accrue(sb, now)
            act = self._decide(sb, now)
            if act:
                actions.append((sb.id, act))
            self.ledger.save(sb)
        return actions

    def _accrue(self, sb, now):
        self.provider.refresh(sb)
        hours = max((now - sb.last_accrual).total_seconds() / 3600, 0)
        sb.spend_usd += hours * sb.burn_rate + self.provider.drain_usage(sb)
        sb.last_accrual = now

    def _decide(self, sb, now):
        p = self.policy
        frac = sb.spend_usd / sb.budget_usd
        if sb.expires_at <= now:
            return self._terminate(sb, "EXPIRED", f"TTL reached at {sb.expires_at:%H:%M}")
        if sb.state == "FROZEN":
            if frac >= p.kill_at:
                return self._terminate(sb, "BUDGET_HARD_KILL", f"spend {frac:.0%} of budget while frozen")
            if (now - sb.frozen_at).total_seconds() / 3600 >= p.frozen_grace_hours:
                return self._terminate(sb, "FROZEN_TIMEOUT", "frozen grace period elapsed")
            return None
        if frac >= p.kill_at:
            return self._terminate(sb, "BUDGET_HARD_KILL", f"spend {frac:.0%} of budget")
        if frac >= p.freeze_at:
            return self._freeze(sb, "BUDGET_EXCEEDED", f"spend ${sb.spend_usd:.2f} >= budget ${sb.budget_usd:.2f}")
        horizon_h = p.tick_seconds * p.predictive_horizon_ticks / 3600
        if sb.burn_rate > 0 and (sb.budget_usd * p.freeze_at - sb.spend_usd) / sb.burn_rate < horizon_h:
            return self._freeze(sb, "BUDGET_PREDICTED", "burn rate will breach budget before next checks")
        for t in p.warn_at:
            if frac >= t and t not in sb.warned:
                sb.warned.append(t)
                self.audit.record("WARNED", sandbox=sb.id, threshold=t, spend=round(sb.spend_usd, 2))
                self.notify.send("WARNING", sb.id, f"{t:.0%} of ${sb.budget_usd:.0f} budget consumed")
                return f"WARN_{int(t*100)}"
        mins_left = (sb.expires_at - now).total_seconds() / 60
        for m in (60, 10):
            if mins_left <= m and m not in sb.expiry_warned:
                sb.expiry_warned.append(m)
                self.audit.record("EXPIRY_WARNING", sandbox=sb.id, minutes_left=m)
                self.notify.send("NOTICE", sb.id, f"expires in {m} minutes — request extension or save work")
                return f"EXPIRY_{m}m"
        return None

    def _freeze(self, sb, code, detail):
        self.provider.stop(sb)
        self.provider.revoke(sb)
        sb.state, sb.reason, sb.frozen_at = "FROZEN", code, self.clock.now()
        self.audit.record("FROZEN", sandbox=sb.id, code=code, detail=detail, spend=round(sb.spend_usd, 2))
        self.notify.send("CRITICAL", sb.id, f"FROZEN ({code}): {detail}. Compute stopped, credentials revoked.")
        return "FREEZE"

    def _terminate(self, sb, code, detail):
        self.provider.terminate(sb)
        sb.state, sb.reason = "TERMINATED", code
        self.audit.record("TERMINATED", sandbox=sb.id, code=code, detail=detail, spend=round(sb.spend_usd, 2))
        self.notify.send("CRITICAL" if "BUDGET" in code else "INFO", sb.id,
                         f"TERMINATED ({code}): {detail}. Final spend ${sb.spend_usd:.2f}")
        return "TERMINATE"
