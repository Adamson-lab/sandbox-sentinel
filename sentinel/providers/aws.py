"""AWS provider (tag-driven). Needs `pip install boto3`.

Resources are created by your IaC pipeline with tags:
    sentinel:sandbox = <sandbox id>
Sentinel discovers them by tag, prices them, and enforces. Anything tagged but unpriced is billed
at policy.unknown_rate_hourly, so shadow/unexpected resources fail *safe* (expensive), not silent.

NOTE: exercised against fakes in tests/test_aws_reaper.py; run against a throwaway account first.
"""
from .base import Provider
from ..models import Resource

TAG = "sentinel:sandbox"


class AwsProvider(Provider):
    def __init__(self, policy, region="us-east-1", session=None):
        import boto3
        s = session or boto3.Session(region_name=region)
        self.ec2, self.iam, self.ce = s.client("ec2"), s.client("iam"), s.client("ce")
        self.policy = policy

    def _instances(self, sb, states):
        resp = self.ec2.describe_instances(Filters=[
            {"Name": f"tag:{TAG}", "Values": [sb.id]},
            {"Name": "instance-state-name", "Values": states}])
        return [i for r in resp["Reservations"] for i in r["Instances"]]

    def launch(self, sb, resource):
        pass  # created by IaC; Sentinel only governs

    def refresh(self, sb):
        found = []
        for i in self._instances(sb, ["pending", "running", "stopping", "stopped"]):
            t = i["InstanceType"]
            rate = self.policy.allowed_types.get(t, self.policy.unknown_rate_hourly)
            state = "running" if i["State"]["Name"] in ("pending", "running") else "stopped"
            found.append(Resource(i["InstanceId"], "compute", t, i["Placement"]["AvailabilityZone"][:-1],
                                  rate, rate * 0.05, state))
        sb.resources = found

    def drain_usage(self, sb):
        # True-up against Cost Explorer (24h lag) — catches usage-based spend our rate table can't see.
        return 0.0

    def stop(self, sb):
        ids = [i["InstanceId"] for i in self._instances(sb, ["pending", "running"])]
        if ids:
            self.ec2.stop_instances(InstanceIds=ids)

    def revoke(self, sb):
        if sb.principal:
            self.iam.put_role_policy(RoleName=sb.principal, PolicyName="sentinel-freeze",
                                     PolicyDocument='{"Version":"2012-10-17","Statement":[{"Effect":"Deny","Action":"*","Resource":"*"}]}')
        sb.credentials_revoked = True

    def terminate(self, sb):
        ids = [i["InstanceId"] for i in self._instances(sb, ["pending", "running", "stopping", "stopped"])]
        if ids:
            self.ec2.terminate_instances(InstanceIds=ids)
        self.revoke(sb)
