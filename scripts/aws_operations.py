"""Operate only the two nodes recorded by deploy_aws.py. Never accepts shell input."""
import argparse
import json
from pathlib import Path
import time
import sys
import boto3
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[1]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["status", "logs", "smoke", "start", "stop", "tunnel-command"])
    parser.add_argument("--profile", default=None)
    args = parser.parse_args()
    config = json.loads((ROOT / "var/aws-deployment.json").read_text())
    session = boto3.Session(profile_name=args.profile, region_name=config["region"])
    assert session.client("sts").get_caller_identity()["Account"] == config["account"], "Wrong AWS account"
    ec2, ssm = session.client("ec2"), session.client("ssm")
    ids = [config["ApiNode"], config["WorkerNode"]]
    # Verify ownership before any operation, including start/stop.
    instances = [node for reservation in ec2.describe_instances(InstanceIds=ids)["Reservations"]
                 for node in reservation["Instances"]]
    for node in instances:
        tags = {tag["Key"]: tag["Value"] for tag in node.get("Tags", [])}
        assert tags.get("aws:cloudformation:stack-name") == "graphword-compute", "Not our stack"
    if args.action in ("start", "stop"):
        response = getattr(ec2, args.action + "_instances")(InstanceIds=ids)
        print(json.dumps(response, default=str, indent=2))
        return
    if args.action == "tunnel-command":
        print(f"aws ssm start-session --target {ids[0]} --document-name AWS-StartPortForwardingSession "
              f"--parameters portNumber=8000,localPortNumber=8000 --region {config['region']}"
              + (f" --profile {args.profile}" if args.profile else ""))
        return
    targets = ids if args.action in ("status", "logs") else ids[:1]
    if args.action == "logs":
        commands = ["journalctl --no-pager -n 50 -u graphword-worker -u graphword-api -u graphword-reconcile"]
    elif args.action == "status":
        commands = ["set -eu", "cloud-init status --wait", "tail -n 15 /var/log/cloud-init-output.log",
                    "systemctl --no-pager status graphword-*",
                    "systemctl is-active --quiet graphword-worker",
                    "if test -f /etc/systemd/system/graphword-api.service; then systemctl is-active --quiet graphword-api graphword-reconcile; "
                    "for attempt in $(seq 1 30); do if curl --max-time 2 --fail --silent http://127.0.0.1:8000/health; then exit 0; fi; sleep 2; done; exit 1; fi"]
    else:
        commands = ["set -eu", "cd /opt/graphword", "set -a", ". ./service.env", "set +a",
                    ".venv/bin/python scripts/smoke_aws.py"]
    command_id = ssm.send_command(
        InstanceIds=targets, DocumentName="AWS-RunShellScript",
        Parameters={"commands": commands, "executionTimeout": ["600"]},
        CloudWatchOutputConfig={"CloudWatchLogGroupName": config["LogGroup"], "CloudWatchOutputEnabled": True},
    )["Command"]["CommandId"]
    print("SSM command:", command_id, flush=True)
    results = {}
    deadline = time.monotonic() + 660
    while len(results) < len(targets) and time.monotonic() < deadline:
        for node in targets:
            if node in results:
                continue
            try:
                result = ssm.get_command_invocation(CommandId=command_id, InstanceId=node)
            except ClientError as error:
                if error.response["Error"]["Code"] != "InvocationDoesNotExist":
                    raise
                continue
            if result["Status"] in ("Success", "Failed", "TimedOut", "Cancelled"):
                results[node] = result
                print(node, result["Status"], result["StandardOutputContent"], result["StandardErrorContent"], flush=True)
        if len(results) < len(targets):
            time.sleep(5)
    (ROOT / f"var/aws-{args.action}.json").write_text(json.dumps(results, default=str, indent=2))
    if len(results) != len(targets) or any(item["Status"] != "Success" for item in results.values()):
        raise RuntimeError("Remote check failed or timed out; inspect var evidence and CloudWatch")


if __name__ == "__main__":
    main()
