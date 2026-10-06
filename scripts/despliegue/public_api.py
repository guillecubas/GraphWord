"""URL HTTPS de demostración. Usa LabRole existente; no abre puertos EC2."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile

import boto3
from botocore.exceptions import ClientError
from graphword.almacenamiento.dictionaries import publish_dictionaries
from graphword.api.public_security import password_hash
from scripts.despliegue.deploy_aws import deploy
from scripts.despliegue.verify_lab_ec2 import verify_identity

ROOT = Path(__file__).resolve().parents[2]
STACK = "graphword-public-api"
FUNCTION = "graphword-public-api"


def template(config, artifact, role):
    # La contraseña nunca aparece en la plantilla: solo parámetros NoEcho.
    environment = {
        "GRAPHWORD_BUCKET": config["Bucket"],
        "GRAPHWORD_TABLE": config["Table"],
        "GRAPHWORD_QUEUE_URL": config["QueueUrl"],
        "GRAPHWORD_DICTIONARY_CATALOG": config["DictionaryCatalogKey"],
        "GRAPHWORD_DEMO_USER": "graphword",
        "GRAPHWORD_PASSWORD_SALT": {"Ref": "PasswordSalt"},
        "GRAPHWORD_PASSWORD_HASH": {"Ref": "PasswordHash"},
    }
    return {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Parameters": {
            "PasswordSalt": {"Type": "String", "NoEcho": True},
            "PasswordHash": {"Type": "String", "NoEcho": True},
        },
        "Resources": {
            "Logs": {"Type": "AWS::Logs::LogGroup", "Properties": {
                "LogGroupName": "/aws/lambda/" + FUNCTION, "RetentionInDays": 7,
            }},
            "API": {"Type": "AWS::Lambda::Function", "DependsOn": "Logs", "Properties": {
                "FunctionName": FUNCTION, "Runtime": "python3.11",
                "Handler": "graphword.api.lambda_app.handler", "Role": role,
                "MemorySize": 512, "Timeout": 35,
                "ReservedConcurrentExecutions": 2,
                "Code": {"S3Bucket": config["Bucket"], "S3Key": artifact},
                "Environment": {"Variables": environment},
                "Tags": [{"Key": "Project", "Value": "GraphWord"}],
            }},
            "URL": {"Type": "AWS::Lambda::Url", "Properties": {
                "TargetFunctionArn": {"Ref": "API"}, "AuthType": "NONE",
            }},
            # NONE significa invocación pública; la aplicación exige Basic Auth.
            "URLPermission": {"Type": "AWS::Lambda::Permission", "Properties": {
                "FunctionName": {"Ref": "API"}, "Principal": "*",
                "Action": "lambda:InvokeFunctionUrl", "FunctionUrlAuthType": "NONE",
            }},
            "InvokePermission": {"Type": "AWS::Lambda::Permission", "Properties": {
                "FunctionName": {"Ref": "API"}, "Principal": "*",
                "Action": "lambda:InvokeFunction", "InvokedViaFunctionUrl": True,
            }},
        },
        "Outputs": {"PublicUrl": {"Value": {"Fn::GetAtt": ["URL", "FunctionUrl"]}}},
    }


def assert_owned_stack(cf, name, required=False):
    # No actualizar ni pausar recursos ajenos con un nombre coincidente.
    try:
        stack = cf.describe_stacks(StackName=name)["Stacks"][0]
    except ClientError as error:
        if not required and "does not exist" in str(error):
            return None
        raise
    for tag in stack.get("Tags", []):
        if tag["Key"] == "Project" and tag["Value"] == "GraphWord":
            return stack
    raise RuntimeError("Stack does not belong to GraphWord: " + name)


def build_package(destination):
    # Pydantic incluye código nativo: construir solo en Linux y Python 3.11.
    if sys.platform != "linux" or sys.version_info[:2] != (3, 11):
        raise RuntimeError("Build the Lambda package on the Linux Python 3.11 runner")
    with tempfile.TemporaryDirectory(prefix="graphword-lambda-") as temporary:
        target = Path(temporary) / "package"
        subprocess.run([
            sys.executable, "-m", "pip", "install", "--no-compile",
            "--target", str(target), str(ROOT) + "[aws,public]",
        ], check=True)
        # Empaquetar dependencias y código, nunca .env, Secrets ni el repositorio.
        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(target.rglob("*")):
                if path.is_file() and "__pycache__" not in path.parts:
                    archive.write(path, path.relative_to(target).as_posix())


def request(url, path, authorization=None, payload=None):
    headers = {}
    if authorization is not None:
        headers["Authorization"] = authorization
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url + path.lstrip("/"), data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def smoke(url, password):
    # No guardar ni mostrar el encabezado de autenticación.
    authorization = "Basic " + base64.b64encode(
        ("graphword:" + password).encode()
    ).decode()
    for path in ("health", "docs", "openapi.json", "v1/dictionaries"):
        status, body = request(url, path)
        if status != 401:
            raise RuntimeError("Unauthenticated access was not rejected: " + path)
        status, body = request(url, path, authorization)
        if status != 200:
            raise RuntimeError("Authenticated access failed: " + path + " HTTP " + str(status))
    status, body = request(url, "health", "Basic Z3JhcGh3b3JkOndyb25n")
    if status != 401:
        raise RuntimeError("Wrong password was not rejected")
    # Este POST prueba la API Lambda y guarda un grafo pequeño en el S3 real.
    words = ["cat", "bat", "bad", "dad", "mat", "rat", "zzz"]
    status, body = request(url, "v1/graphs", authorization, {"words": words, "partitions": 2})
    if status not in (200, 201):
        raise RuntimeError("Public graph creation failed HTTP " + str(status))
    graph = json.loads(body)
    graph_id = graph["graph_id"]
    status, body = request(url, "v1/graphs/" + graph_id + "/queries/shortest-path",
                           authorization, {"start": "cat", "end": "dad"})
    if status != 200:
        raise RuntimeError("Public shortest path failed HTTP " + str(status))
    result = json.loads(body)
    if graph["nodes"] != 7 or graph["edges"] != 8 or len(result["path"]) != 4:
        raise RuntimeError("Public graph result differs from the expected example")
    return {"unauthenticated_rejected": True, "wrong_password_rejected": True,
            "authenticated_docs": True, "dictionary_catalog": True,
            "graph_id": graph_id, "shortest_path": result,
            "async_workers_verified_here": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["deploy", "pause"])
    args = parser.parse_args()
    session = boto3.Session(region_name="us-east-1")
    identity = session.client("sts").get_caller_identity()
    verify_identity(identity, os.environ["AWS_ACCOUNT_ID"])
    cf = session.client("cloudformation")
    assert_owned_stack(cf, STACK, required=args.action == "pause")
    client = session.client("lambda")
    if args.action == "pause":
        # Concurrencia cero conserva la URL pero impide ejecutar la función.
        client.put_function_concurrency(FunctionName=FUNCTION, ReservedConcurrentExecutions=0)
        value = client.get_function_concurrency(FunctionName=FUNCTION)
        if value["ReservedConcurrentExecutions"] != 0:
            raise RuntimeError("Pause was not confirmed")
        print("Public API paused; Lambda concurrency is zero")
        return
    password = os.environ.get("GRAPHWORD_DEMO_PASSWORD", "")
    if len(password) < 16 or len(password) > 256:
        raise RuntimeError("Create GRAPHWORD_DEMO_PASSWORD with 16 to 256 characters")
    storage = assert_owned_stack(cf, "graphword-storage", required=True)
    config = {}
    for item in storage["Outputs"]:
        config[item["OutputKey"]] = item["OutputValue"]
    config["DictionaryCatalogKey"] = publish_dictionaries(
        session.client("s3"), config["Bucket"], ROOT / "data/curated"
    )
    role = session.client("iam").get_role(RoleName="LabRole")["Role"]["Arn"]
    expected_role = "arn:aws:iam::" + identity["Account"] + ":role/LabRole"
    if role != expected_role:
        raise RuntimeError("Unexpected execution role")
    destination = ROOT / "var/aws-public-package.zip"
    destination.parent.mkdir(exist_ok=True)
    build_package(destination)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    artifact = "releases/public-" + digest + ".zip"
    session.client("s3").upload_file(str(destination), config["Bucket"], artifact)
    salt = secrets.token_hex(32)
    parameters = [
        {"ParameterKey": "PasswordSalt", "ParameterValue": salt},
        {"ParameterKey": "PasswordHash", "ParameterValue": password_hash(password, salt)},
    ]
    outputs = deploy(cf, STACK, template(config, artifact, role), parameters)
    # Reanudar una URL pausada: CloudFormation no siempre detecta ese cambio externo.
    client.put_function_concurrency(FunctionName=FUNCTION, ReservedConcurrentExecutions=2)
    url = outputs["PublicUrl"]
    try:
        report = smoke(url, password)
    except Exception:
        # Si la prueba de protección falla, cerrar inmediatamente la función.
        client.put_function_concurrency(FunctionName=FUNCTION, ReservedConcurrentExecutions=0)
        raise
    report["url"] = url
    report["username"] = "graphword"
    report["source_commit"] = os.getenv("GITHUB_SHA", "local")
    report["reserved_concurrency"] = 2
    report["ec2_modified"] = False
    (ROOT / "var/aws-public-api.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    print("Public requests invoke Lambda even without a valid password; pause after use.")


if __name__ == "__main__":
    main()
