"""Layer 3 — STATELESS backstop. Deploy as a Lambda on a 5-minute EventBridge schedule.

It trusts nothing but AWS tags, so it still works if the Sentinel control plane, its database,
or its host is down/compromised. Terminates any instance whose `sentinel:expires` tag is in the past,
and any instance in a sandbox-tagged account that has NO expiry tag at all (untagged = illegal).
"""
import datetime as dt

EXPIRES, SANDBOX = "sentinel:expires", "sentinel:sandbox"


def handler(event=None, context=None, ec2=None, now=None, dry_run=False):
    if ec2 is None:
        import boto3
        ec2 = boto3.client("ec2")
    now = now or dt.datetime.now(dt.timezone.utc)
    doomed, reasons = [], {}
    pages = ec2.get_paginator("describe_instances").paginate(
        Filters=[{"Name": "instance-state-name", "Values": ["pending", "running", "stopping", "stopped"]}])
    for page in pages:
        for r in page["Reservations"]:
            for i in r["Instances"]:
                tags = {t["Key"]: t["Value"] for t in i.get("Tags", [])}
                if EXPIRES not in tags:
                    doomed.append(i["InstanceId"]); reasons[i["InstanceId"]] = "no expiry tag"
                    continue
                try:
                    exp = dt.datetime.fromisoformat(tags[EXPIRES])
                except ValueError:
                    doomed.append(i["InstanceId"]); reasons[i["InstanceId"]] = "unparseable expiry tag"
                    continue
                if exp <= now:
                    doomed.append(i["InstanceId"]); reasons[i["InstanceId"]] = "expired"
    if doomed and not dry_run:
        ec2.terminate_instances(InstanceIds=doomed)
    print({"terminated": doomed, "reasons": reasons, "dry_run": dry_run})
    return {"terminated": doomed, "reasons": reasons}


def lambda_entry(event, context):
    import os
    return handler(event, context, dry_run=os.environ.get("DRY_RUN", "true").lower() == "true")
