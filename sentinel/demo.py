"""Scripted 10-hour scenario on a simulated clock. Run: python -m sentinel demo"""
import os
import tempfile

from .audit import AuditLog
from .clock import FakeClock
from .engine import PolicyViolation, Sentinel
from .ledger import Ledger
from .notify import Notifier
from .policy import Policy
from .providers.sim import SimProvider
from .report import html_report


def banner(t):
    print(f"\n{'='*78}\n{t}\n{'='*78}")


def run(out_dir=".", quiet=False, policy=None):
    clock = FakeClock()
    d = tempfile.mkdtemp()
    audit = AuditLog(os.path.join(d, "audit.jsonl"), clock=clock)
    s = Sentinel(Ledger(), policy or Policy(), SimProvider(), audit, Notifier(), clock)
    samples, events, t0 = [], [], clock.now()

    banner("1. GUARDRAILS AT THE DOOR — risky requests are refused before spending a cent")
    for label, fn in [
        ("TTL of 200h", lambda: s.request("mallory", "CC-ML", 100, ttl_hours=200)),
        ("budget $50,000", lambda: s.request("mallory", "CC-ML", 50000)),
    ]:
        try:
            fn()
        except PolicyViolation as e:
            print(f"  DENIED  {label:<16} -> {e}")

    banner("2. THREE SANDBOXES: runaway, well-behaved, and extended")
    a = s.request("alice", "CC-ML", 200, ttl_hours=8)
    b = s.request("bob", "CC-DATA", 60, ttl_hours=2)
    c = s.request("carol", "CC-DATA", 120, ttl_hours=3)
    for sb, items in [(a, [("compute", "m5.xlarge"), ("gpu", "p3.2xlarge")]),
                      (b, [("compute", "t3.medium")]), (c, [("compute", "r5.2xlarge")])]:
        for kind, typ in items:
            s.provision(sb.id, kind, typ, "us-east-1")
            print(f"  {sb.id} ({sb.owner}) launched {typ}")
    for sb, kind, typ, reg in [(a, "gpu", "p4d.24xlarge", "us-east-1"), (a, "compute", "m5.xlarge", "ap-south-1")]:
        try:
            s.provision(sb.id, kind, typ, reg)
        except PolicyViolation as e:
            print(f"  DENIED  {typ} in {reg} -> {e}")
    try:
        s.extend(c.id, 2, approver="carol")
    except PolicyViolation as e:
        print(f"  DENIED  carol self-approving extension -> {e}")
    s.extend(c.id, 2, approver="dave-manager")
    print("  carol's extension approved by dave-manager (four-eyes)")

    banner("3. SIMULATING 10 HOURS (1-minute control loop)")
    for minute in range(10 * 60):
        if minute == 120:
            print("\n  >>> t+2h00: alice's notebook enters a runaway loop: ~$9/min of API/egress charges\n")
        if 120 <= minute < 150:
            s.inject_usage(a.id, 9.0)
        clock.advance(minutes=1)
        for sid, act in s.tick():
            events.append({"id": sid, "t": (clock.now() - t0).total_seconds() / 3600, "kind": act})
            print(f"  t+{minute+1:>3}m {sid} -> {act}")
        for sb in s.ledger.all():
            samples.append({"id": sb.id, "t": (clock.now() - t0).total_seconds() / 3600, "spend": sb.spend_usd})

    banner("4. OUTCOME")
    print(f"  {'sandbox':<14}{'owner':<8}{'budget':>8}{'spend':>10}  {'state':<12}reason")
    for sb in s.ledger.all():
        print(f"  {sb.id:<14}{sb.owner:<8}{'$'+format(sb.budget_usd,'.0f'):>8}{'$'+format(sb.spend_usd,'.2f'):>10}  {sb.state:<12}{sb.reason}")
    ok, bad = audit.verify()
    print(f"\n  audit chain: {'VERIFIED' if ok else 'TAMPERED at seq %s' % bad}  ({len(audit.events())} records)")
    path = os.path.join(out_dir, "demo-report.html")
    with open(path, "w") as f:
        f.write(html_report("Sandbox Sentinel — 10h simulation", s.ledger.all(), samples, events, ok))
    from .report import svg_chart
    alice = a.id
    d_ = next(x for x in s.ledger.all() if x.id == alice).to_dict(); d_["budget"] = d_["budget_usd"]
    os.makedirs(os.path.join(out_dir, "docs", "img"), exist_ok=True)
    with open(os.path.join(out_dir, "docs", "img", "runaway.svg"), "w") as f:
        f.write(svg_chart(d_, samples, events))
    print(f"  report written: {path}")
    return s, audit


if __name__ == "__main__":
    run()
