"""Comprobar el rol del runner y la parada real de los nodos de GraphWord."""
import argparse
import json
import os
from pathlib import Path
import subprocess


def aws(*arguments):
    # Cada argumento se pasa por separado, sin construir una orden de shell.
    command = ["aws"]
    command.extend(arguments)
    command.extend(["--region", "us-east-1", "--output", "json"])
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    if result.stdout.strip():
        return json.loads(result.stdout)
    return None


def verify_identity(identity, expected_account):
    # No aceptar otro usuario, cuenta o rol en lugar del rol de esta EC2.
    if identity["Account"] != expected_account:
        raise RuntimeError("Cuenta AWS distinta de la autorizada")
    prefix = "arn:aws:sts::" + expected_account + ":assumed-role/LabRole/i-"
    if not identity["Arn"].startswith(prefix):
        raise RuntimeError("El runner no está utilizando LabRole de una EC2")


def instance_tags(instance):
    # Convertir las etiquetas AWS en un diccionario fácil de consultar.
    tags = {}
    for tag in instance.get("Tags", []):
        tags[tag["Key"]] = tag["Value"]
    return tags


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stopped-metadata")
    args = parser.parse_args()

    # El workflow debe obtener credenciales del rol, no de una clave externa.
    credential_variables = (
        "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
        "AWS_WEB_IDENTITY_TOKEN_FILE", "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
        "AWS_CONTAINER_CREDENTIALS_FULL_URI",
    )
    for name in credential_variables:
        if os.environ.get(name):
            raise RuntimeError("No se admiten credenciales externas al rol de EC2: " + name)

    identity = aws("sts", "get-caller-identity")
    verify_identity(identity, os.environ["AWS_ACCOUNT_ID"])
    runner_id = identity["Arn"].rsplit("/", 1)[1]
    reservations = aws("ec2", "describe-instances", "--instance-ids", runner_id)["Reservations"]
    runner = reservations[0]["Instances"][0]
    if instance_tags(runner).get("aws:cloudformation:stack-name") != "graphword-cd-runner":
        raise RuntimeError("El runner no pertenece al stack separado esperado")
    print("Identidad EC2 verificada:", identity["Arn"])

    # En la primera llamada solo se comprueba el runner.
    if not args.stopped_metadata:
        return

    config = json.loads(Path(args.stopped_metadata).read_text(encoding="utf-8"))
    if config["account"] != identity["Account"] or config["region"] != "us-east-1":
        raise RuntimeError("Los nodos del despliegue pertenecen a otra cuenta o región")
    nodes = [config["ApiNode"], config["WorkerNode"]]
    if runner_id in nodes or nodes[0] == nodes[1]:
        raise RuntimeError("Los nodos de aplicación no pueden ser el runner")

    # Comprobar ambas instancias y su propiedad antes de esperar su apagado.
    arguments = ["ec2", "describe-instances", "--instance-ids"]
    arguments.extend(nodes)
    reservations = aws(*arguments)["Reservations"]
    observed_nodes = set()
    for reservation in reservations:
        for node in reservation["Instances"]:
            if instance_tags(node).get("aws:cloudformation:stack-name") != "graphword-compute":
                raise RuntimeError("Nodo ajeno al stack de aplicación")
            observed_nodes.add(node["InstanceId"])
    if observed_nodes != set(nodes):
        raise RuntimeError("La respuesta AWS no contiene exactamente los dos nodos esperados")

    # Esperar el estado stopped; aceptar StopInstances no demuestra la parada.
    arguments = ["ec2", "wait", "instance-stopped", "--instance-ids"]
    arguments.extend(nodes)
    aws(*arguments)
    print("API y worker detenidos. El runner permanece disponible durante la sesión.")


if __name__ == "__main__":
    main()
