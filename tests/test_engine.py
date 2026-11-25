import os, tempfile, unittest

from sentinel.audit import AuditLog
from sentinel.clock import FakeClock
from sentinel.engine import PolicyViolation, Sentinel
from sentinel.ledger import Ledger
from sentinel.notify import Notifier
from sentinel.policy import Policy
from sentinel.providers.sim import SimProvider


def make(policy=None):
    clock = FakeClock()
    d = tempfile.mkdtemp()
    audit = AuditLog(os.path.join(d, "a.jsonl"), key=b"k", clock=clock)
    n = Notifier()
    import io, contextlib
    s = Sentinel(Ledger(), policy or Policy(), SimProvider(), audit, n, clock)
    return s, clock, audit, n


def run(s, clock, minutes):
    out = []
    with __import__("contextlib").redirect_stdout(__import__("io").StringIO()):
        for _ in range(minutes):
            clock.advance(minutes=1)
            out += s.tick()
    return out


class Guardrails(unittest.TestCase):
    def test_ttl_budget_caps(self):
        s, *_ = make()
        with self.assertRaises(PolicyViolation): s.request("a", "cc", 100, ttl_hours=999)
        with self.assertRaises(PolicyViolation): s.request("a", "cc", 99999)

    def test_ticket_required(self):
        s, *_ = make(Policy(require_ticket=True))
        with self.assertRaises(PolicyViolation): s.request("a", "cc", 10)
        s.request("a", "cc", 10, ticket="CHG-1")

    def test_owner_quota_and_cost_center_cap(self):
        s, *_ = make(Policy(max_active_per_owner=1, cost_center_cap_usd=150))
        s.request("a", "cc", 100)
        with self.assertRaises(PolicyViolation): s.request("a", "cc", 10)      # quota
        with self.assertRaises(PolicyViolation): s.request("b", "cc", 100)     # cc cap
        s.request("b", "other", 100)

    def test_allowlists(self):
        s, *_ = make()
        sb = s.request("a", "cc", 100)
        with self.assertRaises(PolicyViolation): s.provision(sb.id, "gpu", "p4d.24xlarge", "us-east-1")
        with self.assertRaises(PolicyViolation): s.provision(sb.id, "compute", "m5.xlarge", "ap-south-1")

    def test_worst_case_preflight(self):
        s, *_ = make()
        sb = s.request("a", "cc", 10, ttl_hours=8)       # p3.2xlarge * 8h = 24.5 > 10
        with self.assertRaises(PolicyViolation): s.provision(sb.id, "gpu", "p3.2xlarge", "us-east-1")

    def test_four_eyes_and_extension_limits(self):
        s, *_ = make()
        sb = s.request("a", "cc", 100, ttl_hours=8)
        with self.assertRaises(PolicyViolation): s.extend(sb.id, 2, approver="a")
        s.extend(sb.id, 2, approver="boss"); s.extend(sb.id, 2, approver="boss")
        with self.assertRaises(PolicyViolation): s.extend(sb.id, 2, approver="boss")
        sb2 = s.request("z", "cc", 100, ttl_hours=70)
        with self.assertRaises(PolicyViolation): s.extend(sb2.id, 10, approver="boss")  # > max ttl


class KillSwitch(unittest.TestCase):
    def test_expiry_terminates_and_warns(self):
        s, clock, _, n = make()
        sb = s.request("a", "cc", 100, ttl_hours=2)
        s.provision(sb.id, "compute", "t3.medium", "us-east-1")
        run(s, clock, 121)
        got = s.ledger.get(sb.id)
        self.assertEqual((got.state, got.reason), ("TERMINATED", "EXPIRED"))
        self.assertTrue(all(r.state == "terminated" for r in got.resources))
        self.assertEqual(len([m for m in n.messages if m[0] == "NOTICE"]), 2)

    def test_usage_spike_freezes_and_revokes(self):
        s, clock, *_ = make()
        sb = s.request("a", "cc", 100, ttl_hours=8)
        s.provision(sb.id, "compute", "t3.medium", "us-east-1")
        s.inject_usage(sb.id, 105)
        run(s, clock, 1)
        got = s.ledger.get(sb.id)
        self.assertEqual(got.state, "FROZEN")
        self.assertTrue(got.credentials_revoked)
        self.assertTrue(all(r.state == "stopped" for r in got.resources))

    def test_revoked_principal_cannot_keep_spending(self):
        s, clock, *_ = make()
        sb = s.request("a", "cc", 100)
        s.inject_usage(sb.id, 101); run(s, clock, 1)
        before = s.ledger.get(sb.id).spend_usd
        s.inject_usage(sb.id, 500); run(s, clock, 1)
        self.assertAlmostEqual(s.ledger.get(sb.id).spend_usd, before, places=2)

    def test_hard_kill_when_instant_overshoot(self):
        s, clock, *_ = make()
        sb = s.request("a", "cc", 100)
        s.inject_usage(sb.id, 150); run(s, clock, 1)
        self.assertEqual(s.ledger.get(sb.id).reason, "BUDGET_HARD_KILL")

    def test_predictive_freeze_beats_the_budget(self):
        s, clock, *_ = make(Policy(predictive_horizon_ticks=5))
        sb = s.request("a", "cc", 500, ttl_hours=72)
        s.provision(sb.id, "gpu", "p3.2xlarge", "us-east-1")
        s.inject_usage(sb.id, 499.9)   # $0.10 of headroom, burning $3.06/h
        run(s, clock, 1)
        got = s.ledger.get(sb.id)
        self.assertEqual(got.reason, "BUDGET_PREDICTED")
        self.assertLess(got.spend_usd, got.budget_usd)

    def test_frozen_timeout_reaps_even_if_nobody_acts(self):
        s, clock, *_ = make(Policy(frozen_grace_hours=1))
        sb = s.request("a", "cc", 100)
        s.inject_usage(sb.id, 101); run(s, clock, 1)
        run(s, clock, 61)
        self.assertEqual(s.ledger.get(sb.id).reason, "FROZEN_TIMEOUT")

    def test_warnings_fire_exactly_once(self):
        s, clock, _, n = make()
        sb = s.request("a", "cc", 100)
        s.inject_usage(sb.id, 55); run(s, clock, 5)
        s.inject_usage(sb.id, 30); run(s, clock, 5)
        self.assertEqual(len([m for m in n.messages if m[0] == "WARNING"]), 2)

    def test_tick_is_idempotent_on_terminated(self):
        s, clock, *_ = make()
        sb = s.request("a", "cc", 100, ttl_hours=1)
        run(s, clock, 61)
        self.assertEqual(run(s, clock, 10), [])

    def test_stopped_resources_cost_less(self):
        s, clock, *_ = make()
        sb = s.request("a", "cc", 400, ttl_hours=72)
        s.provision(sb.id, "gpu", "p3.2xlarge", "us-east-1")
        s.provider.stop(got := s.ledger.get(sb.id)); s.ledger.save(got)
        self.assertLess(s.ledger.get(sb.id).burn_rate, 0.2)


class AuditTests(unittest.TestCase):
    def test_chain_verifies_and_detects_tamper(self):
        s, clock, audit, _ = make()
        s.request("a", "cc", 10); s.request("b", "cc", 10)
        self.assertEqual(audit.verify(), (True, None))
        lines = open(audit.path).read().splitlines()
        lines[0] = lines[0].replace('"budget": 10', '"budget": 9999')
        open(audit.path, "w").write("\n".join(lines) + "\n")
        ok, bad = audit.verify()
        self.assertFalse(ok); self.assertEqual(bad, 1)

    def test_denials_are_audited(self):
        s, _, audit, _ = make()
        with self.assertRaises(PolicyViolation): s.request("a", "cc", 99999)
        self.assertEqual(audit.events()[-1]["event"], "DENIED")


class Policies(unittest.TestCase):
    def test_shipped_policies_load(self):
        for f in os.listdir("policies"):
            Policy.load(os.path.join("policies", f))

    def test_unknown_key_rejected(self):
        p = os.path.join(tempfile.mkdtemp(), "p.json")
        open(p, "w").write('{"max_budget_usdd": 1}')
        with self.assertRaises(ValueError): Policy.load(p)


if __name__ == "__main__":
    unittest.main()
