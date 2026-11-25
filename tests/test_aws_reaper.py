import datetime as dt, sys, unittest
sys.path.insert(0, "lambda")
import reaper

NOW = dt.datetime(2026, 1, 5, 12, 0, tzinfo=dt.timezone.utc)


class FakeEC2:
    def __init__(self, instances): self.instances, self.killed = instances, []
    def get_paginator(self, _):
        outer = self
        class P:
            def paginate(self, **kw): return [{"Reservations": [{"Instances": outer.instances}]}]
        return P()
    def terminate_instances(self, InstanceIds): self.killed += InstanceIds


def inst(i, exp=None, bad=False):
    tags = [] if exp is None else [{"Key": "sentinel:expires", "Value": "garbage" if bad else exp.isoformat()}]
    return {"InstanceId": i, "Tags": tags}


class Reaper(unittest.TestCase):
    def test_reaps_expired_untagged_and_garbage_but_not_live(self):
        ec2 = FakeEC2([inst("i-old", NOW - dt.timedelta(minutes=1)), inst("i-live", NOW + dt.timedelta(hours=1)),
                       inst("i-untagged"), inst("i-bad", NOW, bad=True)])
        out = reaper.handler(ec2=ec2, now=NOW)
        self.assertEqual(sorted(ec2.killed), ["i-bad", "i-old", "i-untagged"])
        self.assertEqual(out["reasons"]["i-untagged"], "no expiry tag")

    def test_dry_run_kills_nothing(self):
        ec2 = FakeEC2([inst("i-old", NOW - dt.timedelta(hours=1))])
        reaper.handler(ec2=ec2, now=NOW, dry_run=True)
        self.assertEqual(ec2.killed, [])


if __name__ == "__main__":
    unittest.main()
