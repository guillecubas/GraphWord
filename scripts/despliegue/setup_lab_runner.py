"""Comprobar el laboratorio y crear una EC2 separada para el runner privado.

Sin --create solo consulta recursos. No crea roles, claves ni reglas de entrada.
Se ejecuta desde CloudShell o una EC2 autorizada, no exportando sus credenciales.
"""
import argparse
import base64
import json
import time

import boto3
from botocore.exceptions import ClientError


REGION = "us-east-1"
STACK = "graphword-cd-runner"
UBUNTU_PARAMETER = "/aws/service/canonical/ubuntu/server/22.04/stable/current/amd64/hvm/ebs-gp2/ami-id"
RUNNER_URL = "https://github.com/actions/runner/releases/download/v2.337.0/actions-runner-linux-x64-2.337.0.tar.gz"
RUNNER_SHA256 = "70920811a4f8ad4328818682bca5c6469c1c942fab52448868071d0063816613"


def startup_script():
    # Instalar desde fuentes oficiales. El token de registro se introduce después.
    return "\n".join([
        "#!/bin/bash",
        "set -euo pipefail",
        "export DEBIAN_FRONTEND=noninteractive",
        "apt-get update",
        "apt-get install -y ca-certificates curl git jq awscli python3-venv python3-boto3",
        "useradd --create-home --shell /bin/bash graphword-runner",
        "install -d -o graphword-runner -g graphword-runner /opt/actions-runner",
        "cd /opt/actions-runner",
        "curl --fail --location --retry 3 '" + RUNNER_URL + "' -o runner.tar.gz",
        "echo '" + RUNNER_SHA256 + "  runner.tar.gz' | sha256sum --check -",
        "tar -xzf runner.tar.gz",
        "./bin/installdependencies.sh",
        "chown -R graphword-runner:graphword-runner /opt/actions-runner",
        "echo 'Runner preparado. Falta registrar solo en guillecubas/GraphWord-CD.'",
        "",
    ])


def runner_template(vpc, subnet, ami, root_device):
    # El runner nunca pertenece a graphword-compute: desplegar no lo reemplaza.
    return {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Resources": {
            "SecurityGroup": {
                "Type": "AWS::EC2::SecurityGroup",
                "Properties": {
                    "GroupDescription": "GraphWord CD: SSM only, no inbound ports",
                    "VpcId": vpc,
                    "SecurityGroupEgress": [{"IpProtocol": "-1", "CidrIp": "0.0.0.0/0"}],
                    "Tags": [{"Key": "Project", "Value": "GraphWord"}],
                },
            },
            "Runner": {
                "Type": "AWS::EC2::Instance",
                "Properties": {
                    "ImageId": ami,
                    "InstanceType": "t3.micro",
                    "IamInstanceProfile": "LabInstanceProfile",
                    "CreditSpecification": {"CPUCredits": "standard"},
                    "MetadataOptions": {"HttpTokens": "required", "HttpEndpoint": "enabled"},
                    "NetworkInterfaces": [{
                        "DeviceIndex": "0", "AssociatePublicIpAddress": True,
                        "SubnetId": subnet, "GroupSet": [{"Ref": "SecurityGroup"}],
                    }],
                    "BlockDeviceMappings": [{
                        "DeviceName": root_device,
                        "Ebs": {"VolumeSize": 12, "VolumeType": "gp3",
                                "Encrypted": True, "DeleteOnTermination": True},
                    }],
                    "UserData": base64.b64encode(startup_script().encode()).decode(),
                    "Tags": [
                        {"Key": "Name", "Value": "graphword-cd-runner"},
                        {"Key": "Project", "Value": "GraphWord"},
                    ],
                },
            },
        },
        "Outputs": {"RunnerNode": {"Value": {"Ref": "Runner"}}},
    }


def subnet_is_public(ec2, vpc, subnet):
    # Revisar la tabla asociada; si no hay una, se aplica la tabla principal.
    tables = ec2.describe_route_tables(Filters=[
        {"Name": "association.subnet-id", "Values": [subnet]},
    ])["RouteTables"]
    if not tables:
        tables = ec2.describe_route_tables(Filters=[
            {"Name": "vpc-id", "Values": [vpc]},
            {"Name": "association.main", "Values": ["true"]},
        ])["RouteTables"]
    for table in tables:
        for route in table.get("Routes", []):
            if (route.get("DestinationCidrBlock") == "0.0.0.0/0"
                    and route.get("GatewayId", "").startswith("igw-")
                    and route.get("State") == "active"):
                return True
    return False


def check_environment(session, expected_account):
    # No continuar en una cuenta distinta a la autorizada por el usuario.
    identity = session.client("sts").get_caller_identity()
    if identity["Account"] != expected_account:
        raise RuntimeError("La cuenta AWS no coincide con la cuenta autorizada")
    ec2 = session.client("ec2")
    profile = session.client("iam").get_instance_profile(
        InstanceProfileName="LabInstanceProfile")["InstanceProfile"]
    role_names = []
    for role in profile["Roles"]:
        role_names.append(role["RoleName"])
    if role_names != ["LabRole"]:
        raise RuntimeError("LabInstanceProfile no contiene el LabRole esperado")

    # Reservar espacio para el runner y los dos nodos nuevos de un despliegue.
    reservations = ec2.describe_instances(Filters=[
        {"Name": "instance-state-name", "Values": ["pending", "running"]},
    ])["Reservations"]
    instance_count = 0
    instance_types = set()
    counts = {}
    for reservation in reservations:
        for instance in reservation["Instances"]:
            instance_count += 1
            instance_type = instance["InstanceType"]
            instance_types.add(instance_type)
            counts[instance_type] = counts.get(instance_type, 0) + 1
    if instance_count + 3 > 9:
        raise RuntimeError("No hay margen seguro para el runner y dos nodos nuevos")
    used_vcpus = 0
    if instance_types:
        descriptions = ec2.describe_instance_types(
            InstanceTypes=sorted(instance_types))["InstanceTypes"]
        for item in descriptions:
            used_vcpus += counts[item["InstanceType"]] * item["VCpuInfo"]["DefaultVCpus"]
    if used_vcpus + 6 > 32:
        raise RuntimeError("No hay margen seguro de vCPU en el laboratorio")

    vpcs = ec2.describe_vpcs(Filters=[
        {"Name": "isDefault", "Values": ["true"]},
    ])["Vpcs"]
    if len(vpcs) != 1:
        raise RuntimeError("Se necesita exactamente una VPC predeterminada")
    vpc = vpcs[0]["VpcId"]
    subnets = ec2.describe_subnets(Filters=[
        {"Name": "vpc-id", "Values": [vpc]},
        {"Name": "default-for-az", "Values": ["true"]},
    ])["Subnets"]
    subnet = None
    def availability_zone(item):
        return item["AvailabilityZone"]

    for item in sorted(subnets, key=availability_zone):
        if subnet_is_public(ec2, vpc, item["SubnetId"]):
            subnet = item["SubnetId"]
            break
    if subnet is None:
        raise RuntimeError("No hay una subred predeterminada con salida a Internet")
    ami = session.client("ssm").get_parameter(Name=UBUNTU_PARAMETER)["Parameter"]["Value"]
    images = ec2.describe_images(ImageIds=[ami], Owners=["099720109477"])["Images"]
    if len(images) != 1 or images[0]["Architecture"] != "x86_64":
        raise RuntimeError("La AMI no es la imagen x86_64 oficial de Canonical")
    report = {
        "account": identity["Account"], "identity": identity["Arn"], "region": REGION,
        "running_or_pending_instances": instance_count, "used_vcpus": used_vcpus,
        "vpc": vpc, "subnet": subnet, "ami": ami,
        "root_device": images[0]["RootDeviceName"], "instance_profile": "LabInstanceProfile",
    }
    # Validar la plantilla es una consulta; no prueba que CreateStack esté permitido.
    template = runner_template(vpc, subnet, ami, report["root_device"])
    session.client("cloudformation").validate_template(TemplateBody=json.dumps(template))
    return report, template


def create_runner(cf, template):
    # Si existe, no actualizar ni reemplazar el runner que ya está registrado.
    try:
        stack = cf.describe_stacks(StackName=STACK)["Stacks"][0]
    except ClientError as error:
        if "does not exist" not in str(error):
            raise
        cf.create_stack(StackName=STACK, TemplateBody=json.dumps(template),
                        Tags=[{"Key": "Project", "Value": "GraphWord"}])
    else:
        tags = {}
        for tag in stack.get("Tags", []):
            tags[tag["Key"]] = tag["Value"]
        if tags.get("Project") != "GraphWord":
            raise RuntimeError("El stack existente no pertenece a GraphWord")
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        stack = cf.describe_stacks(StackName=STACK)["Stacks"][0]
        state = stack["StackStatus"]
        print("Runner stack:", state, flush=True)
        if state in ("CREATE_COMPLETE", "UPDATE_COMPLETE"):
            for output in stack.get("Outputs", []):
                if output["OutputKey"] == "RunnerNode":
                    return output["OutputValue"]
            raise RuntimeError("El stack no tiene la salida RunnerNode")
        if not state.endswith("IN_PROGRESS"):
            raise RuntimeError("Revisar los eventos del stack " + STACK + ": " + state)
        time.sleep(10)
    raise TimeoutError("El stack sigue pendiente; inspeccionarlo antes de repetir")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", required=True)
    parser.add_argument("--create", action="store_true")
    args = parser.parse_args()
    session = boto3.Session(region_name=REGION)
    report, template = check_environment(session, args.account)
    print(json.dumps(report, indent=2), flush=True)
    if not args.create:
        print("Comprobaciones de lectura completadas. No se ha creado ningún recurso.")
        return
    runner = create_runner(session.client("cloudformation"), template)
    print("RunnerNode:", runner, flush=True)
    print("Esperar cloud-init y registrar el runner solo en guillecubas/GraphWord-CD.")


if __name__ == "__main__":
    main()
