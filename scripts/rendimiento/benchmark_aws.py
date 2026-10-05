"""Controlled experiment on the existing two-node lab; always restore services.

Refuses to run with unfinished jobs. Pauses only GraphWord's dispatcher and worker
B between trials. This is a benchmark window, not a production traffic procedure.
"""
import argparse
import json
from pathlib import Path
import statistics
import time
import boto3
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[2]


def command(ssm, node, commands):
    # SSM ejecuta estas órdenes solo en el nodo indicado.
    remote_commands = ["set -eu"]
    remote_commands.extend(commands)
    cid = ssm.send_command(InstanceIds=[node], DocumentName="AWS-RunShellScript",
        Parameters={"commands": remote_commands, "executionTimeout": ["300"]})["Command"]["CommandId"]
    deadline = time.monotonic() + 360
    while time.monotonic() < deadline:
        try:
            result = ssm.get_command_invocation(CommandId=cid, InstanceId=node)
        except ClientError as error:
            if error.response["Error"]["Code"] != "InvocationDoesNotExist":
                raise
            time.sleep(2)
            continue
        if result["Status"] == "Success":
            return result["StandardOutputContent"]
        if result["Status"] in ("Failed", "TimedOut", "Cancelled"):
            raise RuntimeError(result["StandardErrorContent"] + result["StandardOutputContent"])
        time.sleep(2)
    raise TimeoutError(cid)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default=None)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if args.repeats < 2:
        parser.error("Use at least two repeats to alternate worker order")
    config = json.loads((ROOT / "var/aws-deployment.json").read_text())
    session = boto3.Session(profile_name=args.profile, region_name=config["region"])
    assert session.client("sts").get_caller_identity()["Account"] == config["account"]
    table = session.resource("dynamodb").Table(config["Table"])
    scan = {}
    while True:
        page = table.scan(ConsistentRead=True, **scan)
        # No interferir con trabajos que todavía están ejecutándose.
        for item in page["Items"]:
            if item["status"] not in ("SUCCEEDED", "FAILED"):
                raise RuntimeError("Refusing benchmark: unfinished jobs exist")
        if "LastEvaluatedKey" not in page:
            break
        scan["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    ec2 = session.client("ec2")
    nodes = [config["ApiNode"], config["WorkerNode"]]
    for reservation in ec2.describe_instances(InstanceIds=nodes)["Reservations"]:
        for node in reservation["Instances"]:
            tags = {}
            for tag in node["Tags"]:
                tags[tag["Key"]] = tag["Value"]
            assert tags.get("aws:cloudformation:stack-name") == "graphword-compute"
    ssm = session.client("ssm")
    records = []
    output = ROOT / "docs/evidence/benchmark-aws.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        command(ssm, nodes[0], ["systemctl stop graphword-reconcile"])
        for length in (3, 4, 5, 6):
            for repeat in range(args.repeats):
                # Alternar el orden reduce la ventaja de una caché ya caliente.
                if repeat % 2 == 0:
                    worker_order = (1, 2)
                else:
                    worker_order = (2, 1)
                for workers in worker_order:
                    if workers == 1:
                        action = "stop"
                    else:
                        action = "start"
                    command(ssm, nodes[1], [f"systemctl {action} graphword-worker"])
                    result = command(ssm, nodes[0], ["cd /opt/graphword", "set -a", ". ./service.env", "set +a",
                        f".venv/bin/python -m scripts.rendimiento.benchmark_remote {length} {workers}"])
                    record = json.loads(result)
                    record["repeat"] = repeat
                    records.append(record)
                    output.write_text(json.dumps({"records": records, "complete": False}, indent=2) + "\n")
                    print(f"length={length} repeat={repeat} workers={workers} seconds={record['seconds']:.3f} observed={len(record['observed_workers'])}", flush=True)
    finally:
        # Restore each service even if restoration of the other fails.
        try:
            command(ssm, nodes[1], ["systemctl start graphword-worker"])
        finally:
            command(ssm, nodes[0], ["systemctl start graphword-reconcile"])
    medians = []
    for length in (3, 4, 5, 6):
        # Comparar las medianas evita que un tiempo aislado domine el resultado.
        values = {}
        for workers in (1, 2):
            durations = []
            for item in records:
                if item["length"] == length and item["configured_workers"] == workers:
                    durations.append(item["seconds"])
            values[workers] = statistics.median(durations)
        medians.append({"length": length, "median_seconds": values, "speedup_1_over_2": values[1] / values[2]})
    output.write_text(json.dumps({"complete": True, "region": config["region"], "instance_type": "t3.micro",
        "repeats": args.repeats, "partitions": 8, "reconcile_interval_seconds": 0.5,
        "includes": ["HTTP submission", "S3", "DynamoDB", "SQS", "workers", "reduction", "status polling"],
        "excludes": ["SSM dispatch", "reference graph", "result download/equality", "service start/stop"],
        "records": records, "medians": medians}, indent=2) + "\n")


if __name__ == "__main__":
    main()
