"""Reproducible, manual lab deployment. Creates only GraphWord-named stacks.

Run from the repository: python scripts/deploy_aws.py --profile default
Creates two t3.micro instances; costs lab credit. No inbound ports are opened.
"""
import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import time
import zipfile

import boto3
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[1]


def deploy(cf, name, template):
    body = json.dumps(template)
    cf.validate_template(TemplateBody=body)
    try:
        cf.describe_stacks(StackName=name)
    except ClientError as error:
        if "does not exist" not in str(error):
            raise
        cf.create_stack(StackName=name, TemplateBody=body,
                        Tags=[{"Key": "Project", "Value": "GraphWord"}])
    else:
        try:
            cf.update_stack(StackName=name, TemplateBody=body)
        except ClientError as error:
            if "No updates are to be performed" not in str(error):
                raise
    deadline = time.monotonic() + 900
    previous = None
    while time.monotonic() < deadline:
        stack = cf.describe_stacks(StackName=name)["Stacks"][0]
        state = stack["StackStatus"]
        if state != previous:
            print(name, state, flush=True)
            previous = state
        if state in ("CREATE_COMPLETE", "UPDATE_COMPLETE"):
            return {item["OutputKey"]: item["OutputValue"] for item in stack.get("Outputs", [])}
        if "IN_PROGRESS" not in state:
            events = cf.describe_stack_events(StackName=name)["StackEvents"]
            for event in events[:10]:
                print(event["LogicalResourceId"], event["ResourceStatus"], event.get("ResourceStatusReason", ""))
            raise RuntimeError(f"{name}: {state}")
        time.sleep(5)
    raise TimeoutError(f"Inspect stack {name}; deployment still pending")


def compute_template(vpc, subnet, ami, bucket, artifact, profile):
    # New immutable release -> new nodes. cloud-init does not rerun on a reboot.
    suffix = hashlib.sha256(artifact.encode()).hexdigest()[:10]
    resources = {
        "SecurityGroup": {"Type": "AWS::EC2::SecurityGroup", "Properties": {
            "GroupDescription": "GraphWord SSM-only access; no inbound ports", "VpcId": vpc,
            "SecurityGroupEgress": [{"IpProtocol": "-1", "CidrIp": "0.0.0.0/0"}],
            "Tags": [{"Key": "Project", "Value": "GraphWord"}],
        }}
    }
    for name, role in (("ApiNode", "api"), ("WorkerNode", "worker")):
        script = ("#!/bin/bash\nset -euo pipefail\n"
                  "dnf install -y python3.11 python3.11-pip unzip\n"
                  "mkdir -p /opt/graphword\n"
                  f"aws s3 cp s3://{bucket}/{artifact} /opt/graphword/release.zip --region us-east-1\n"
                  "cd /opt/graphword\nunzip -o release.zip\n"
                  f"python3.11 scripts/bootstrap_aws.py {role}\n")
        resources[name + suffix] = {"Type": "AWS::EC2::Instance", "Properties": {
            "ImageId": ami, "InstanceType": "t3.micro", "IamInstanceProfile": profile,
            "CreditSpecification": {"CPUCredits": "standard"},
            "MetadataOptions": {"HttpTokens": "required", "HttpEndpoint": "enabled"},
            "NetworkInterfaces": [{"DeviceIndex": "0", "AssociatePublicIpAddress": True,
                                   "SubnetId": subnet, "GroupSet": [{"Ref": "SecurityGroup"}]}],
            "BlockDeviceMappings": [{"DeviceName": "/dev/xvda", "Ebs": {
                "VolumeSize": 8, "VolumeType": "gp3", "Encrypted": True, "DeleteOnTermination": True}}],
            "UserData": base64.b64encode(script.encode()).decode(),
            "Tags": [{"Key": "Name", "Value": "graphword-" + role}, {"Key": "Project", "Value": "GraphWord"}],
        }}
    return {"AWSTemplateFormatVersion": "2010-09-09", "Resources": resources,
            "Outputs": {name: {"Value": {"Ref": name + suffix}} for name in ("ApiNode", "WorkerNode")}}


def build_release(config):
    """Deterministic ZIP, readable by the non-root application user after unzip."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        def add_file(name, content):
            info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, content)

        for pattern in ("graphword/*.py", "scripts/bootstrap_aws.py", "scripts/smoke_aws.py",
                        "scripts/benchmark_remote.py", "data/curated/words*.txt",
                        "data/curated/licenses/*", "data/curated/manifest.json", "pyproject.toml"):
            for path in sorted(ROOT.glob(pattern)):
                add_file(path.relative_to(ROOT).as_posix(), path.read_bytes())
        add_file("deployment.json", json.dumps(config, sort_keys=True))
    return buffer.getvalue()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default=None)
    parser.add_argument("--region", default="us-east-1", choices=["us-east-1"])
    parser.add_argument("--instance-profile", default="LabInstanceProfile")
    args = parser.parse_args()
    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    account = session.client("sts").get_caller_identity()["Account"]
    print("Target account:", account, "region:", args.region, flush=True)
    cf, ec2 = session.client("cloudformation"), session.client("ec2")
    vpcs = ec2.describe_vpcs(Filters=[{"Name": "isDefault", "Values": ["true"]}])["Vpcs"]
    if not vpcs:
        raise RuntimeError("No default VPC; specify a reviewed network before deploying")
    vpc = vpcs[0]["VpcId"]
    subnets = ec2.describe_subnets(Filters=[{"Name": "vpc-id", "Values": [vpc]},
                                           {"Name": "default-for-az", "Values": ["true"]}])["Subnets"]
    subnet = sorted(subnets, key=lambda item: item["AvailabilityZone"])[0]["SubnetId"]
    session.client("iam").get_instance_profile(InstanceProfileName=args.instance_profile)
    ami = session.client("ssm").get_parameter(
        Name="/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
    )["Parameter"]["Value"]
    outputs = deploy(cf, "graphword-storage", json.loads((ROOT / "infra/storage.json").read_text()))
    config = dict(outputs, region=args.region, account=account)
    # Allowlist only application sources. Never zip .aws, .env, .venv or Git metadata.
    content = build_release(config)
    digest = hashlib.sha256(content).hexdigest()
    artifact = f"releases/{digest}.zip"
    session.client("s3").put_object(Bucket=outputs["Bucket"], Key=artifact, Body=content,
                                    ServerSideEncryption="AES256")
    template = compute_template(vpc, subnet, ami, outputs["Bucket"], artifact, args.instance_profile)
    nodes = deploy(cf, "graphword-compute", template)
    config.update(nodes, artifact=artifact, artifact_sha256=digest)
    (ROOT / "var").mkdir(exist_ok=True)
    (ROOT / "var/aws-deployment.json").write_text(json.dumps(config, indent=2))
    print(json.dumps(config, indent=2), flush=True)
    print("EC2 creation is not application readiness. Verify cloud-init and run smoke test.", flush=True)


if __name__ == "__main__":
    main()
