"""Comprobar Lambda y el rol existente sin crear recursos ni abrir puertos."""
import json
import os
from pathlib import Path

from scripts.despliegue.verify_lab_ec2 import aws, verify_identity


def main():
    identity = aws("sts", "get-caller-identity")
    verify_identity(identity, os.environ["AWS_ACCOUNT_ID"])
    settings = aws("lambda", "get-account-settings")
    role = aws("iam", "get-role", "--role-name", "LabRole")["Role"]

    # Solo leer si Lambda puede asumir el rol que ya tiene el laboratorio.
    services = []
    for statement in role["AssumeRolePolicyDocument"]["Statement"]:
        if statement.get("Effect") != "Allow":
            continue
        service = statement.get("Principal", {}).get("Service", [])
        if isinstance(service, str):
            service = [service]
        services.extend(service)
    if "lambda.amazonaws.com" not in services:
        raise RuntimeError("LabRole no permite que Lambda lo asuma; no se modificará IAM")

    report = {
        "account": identity["Account"],
        "region": "us-east-1",
        "role": role["Arn"],
        "lambda_trusted": True,
        "lambda_limits": settings["AccountLimit"],
        "function_count": settings["AccountUsage"]["FunctionCount"],
        "resources_created": False,
        "note": "Lectura correcta; CreateFunction y Function URL aún requieren validación real",
    }
    directory = Path("var")
    directory.mkdir(exist_ok=True)
    (directory / "aws-public-preflight.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
