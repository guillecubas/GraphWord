"""Deployment pipeline using temporary environment credentials, never stored keys.

For a teaching lab: verify a live API, then stop its EC2 nodes to limit spending.
A runner kill/timeout or incomplete CloudFormation deployment requires inspection.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import boto3

ROOT = Path(__file__).resolve().parents[2]


def run(script, *args):
    # Preparar cada argumento por separado para no construir órdenes de shell.
    command = [sys.executable, str(ROOT / "scripts" / script)]
    command.extend(args)
    subprocess.run(command, cwd=ROOT, check=True)


def main():
    public_enabled = os.getenv("ENABLE_PUBLIC_API") == "true"
    if public_enabled:
        # Comprobar el Secret antes de crear o reemplazar ninguna EC2.
        password = os.getenv("GRAPHWORD_DEMO_PASSWORD", "")
        if len(password) < 16 or len(password) > 256:
            raise RuntimeError("Configure GRAPHWORD_DEMO_PASSWORD before deploying public HTTPS")
    config_path = ROOT / "var/aws-deployment.json"
    # Prevent cleanup accidentally targeting a previous deployment on a reused runner.
    if config_path.exists():
        raise RuntimeError("Use a fresh CI checkout; deployment metadata already exists")
    try:
        run("despliegue/deploy_aws.py")
        run("operaciones/aws_operations.py", "start")
        config = json.loads(config_path.read_text())
        ssm = boto3.client("ssm", region_name=config["region"])
        nodes = {config["ApiNode"], config["WorkerNode"]}
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            entries = ssm.describe_instance_information(
                Filters=[{"Key": "InstanceIds", "Values": sorted(nodes)}])
            # Esperar hasta que ambas instancias acepten órdenes de SSM.
            online = set()
            for item in entries["InstanceInformationList"]:
                if item["PingStatus"] == "Online":
                    online.add(item["InstanceId"])
            if online == nodes:
                break
            time.sleep(10)
        else:
            raise TimeoutError("SSM nodes did not become ready")
        run("operaciones/aws_operations.py", "status")
        run("operaciones/aws_operations.py", "smoke")
        if public_enabled:
            # Actualizar también la entrada HTTPS si se ha habilitado expresamente.
            subprocess.run([sys.executable, "-m", "scripts.despliegue.public_api", "deploy"],
                           cwd=ROOT, check=True)
    finally:
        # Intentar parar los nodos registrados incluso si una comprobación falla.
        if config_path.exists():
            run("operaciones/aws_operations.py", "stop")


if __name__ == "__main__":
    main()
