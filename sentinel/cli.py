import argparse
import os
import time

from .audit import AuditLog
from .clock import Clock
from .engine import PolicyViolation, Sentinel
from .ledger import Ledger
from .notify import Notifier, WebhookNotifier
from .policy import Policy
from .providers.sim import SimProvider


def build(args):
    home = os.environ.get("SENTINEL_HOME", ".sentinel")
    os.makedirs(home, exist_ok=True)
    pol = Policy.load(args.policy) if args.policy else Policy()
    clock = Clock()
    hook = os.environ.get("SENTINEL_WEBHOOK")
    provider = SimProvider()
    if args.provider == "aws":
        from .providers.aws import AwsProvider
        provider = AwsProvider(pol)
    return Sentinel(Ledger(os.path.join(home, "ledger.db")), pol, provider,
                    AuditLog(os.path.join(home, "audit.jsonl"), clock=clock),
                    WebhookNotifier(hook) if hook else Notifier(), clock)


def main(argv=None):
    ap = argparse.ArgumentParser("sentinel")
    ap.add_argument("--policy")
    ap.add_argument("--provider", choices=["sim", "aws"], default="sim")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("demo")
    r = sub.add_parser("request"); r.add_argument("owner"); r.add_argument("cost_center")
    r.add_argument("budget", type=float); r.add_argument("--ttl", type=float); r.add_argument("--ticket", default="")
    p = sub.add_parser("provision"); p.add_argument("sandbox"); p.add_argument("type"); p.add_argument("--region", default="us-east-1")
    p.add_argument("--kind", default="compute")
    e = sub.add_parser("extend"); e.add_argument("sandbox"); e.add_argument("hours", type=float); e.add_argument("--approver", required=True)
    u = sub.add_parser("inject"); u.add_argument("sandbox"); u.add_argument("usd", type=float)
    sub.add_parser("tick"); sub.add_parser("status"); sub.add_parser("verify")
    d = sub.add_parser("daemon"); d.add_argument("--interval", type=int)
    a = ap.parse_args(argv)

    if a.cmd == "demo":
        from . import demo
        demo.run(policy=Policy.load(a.policy) if a.policy else None)
        return
    s = build(a)
    try:
        if a.cmd == "request":
            sb = s.request(a.owner, a.cost_center, a.budget, a.ttl, a.ticket)
            print(f"created {sb.id} expires {sb.expires_at:%Y-%m-%d %H:%M}Z")
        elif a.cmd == "provision":
            print("launched", s.provision(a.sandbox, a.kind, a.type, a.region).id)
        elif a.cmd == "extend":
            s.extend(a.sandbox, a.hours, a.approver); print("extended")
        elif a.cmd == "inject":
            s.inject_usage(a.sandbox, a.usd); print("usage injected")
        elif a.cmd == "tick":
            print(s.tick() or "no actions")
        elif a.cmd == "status":
            print(f"{'id':<14}{'owner':<10}{'state':<12}{'spend':>9}{'budget':>9}  expires")
            for sb in s.ledger.all():
                print(f"{sb.id:<14}{sb.owner:<10}{sb.state:<12}{sb.spend_usd:>9.2f}{sb.budget_usd:>9.0f}  {sb.expires_at:%m-%d %H:%M}Z")
        elif a.cmd == "verify":
            ok, bad = s.audit.verify()
            print("audit chain VERIFIED" if ok else f"TAMPERED at seq {bad}")
            raise SystemExit(0 if ok else 2)
        elif a.cmd == "daemon":
            iv = a.interval or s.policy.tick_seconds
            print(f"control loop every {iv}s (ctrl-c to stop)")
            while True:
                s.tick(); time.sleep(iv)
    except PolicyViolation as ex:
        print("DENIED:", ex)
        raise SystemExit(1)
