"""Executed on fresh lab EC2 instances only, as root via cloud-init.

No embedded credentials: boto3 uses the instance's LabInstanceProfile.
"""
import json
from pathlib import Path
import subprocess
import sys


def run(*command):
    subprocess.run(command, check=True)


def main():
    # Preparar el usuario y el entorno Python de la nueva instancia.
    root = Path("/opt/graphword")
    config = json.loads((root / "deployment.json").read_text())
    run("useradd", "--system", "--home-dir", str(root), "--shell", "/sbin/nologin", "graphword")
    run(sys.executable, "-m", "venv", str(root / ".venv"))
    python = str(root / ".venv/bin/python")
    run(python, "-m", "pip", "install", str(root) + "[aws]")
    environment = {
        "AWS_DEFAULT_REGION": config["region"],
        "GRAPHWORD_BUCKET": config["Bucket"],
        "GRAPHWORD_TABLE": config["Table"],
        "GRAPHWORD_QUEUE_URL": config["QueueUrl"],
        "GRAPHWORD_DICTIONARY_CATALOG": config["DictionaryCatalogKey"],
        "PYTHONUNBUFFERED": "1",
    }
    # Escribir una variable por línea; los servicios leerán este archivo.
    environment_lines = []
    for key, value in environment.items():
        environment_lines.append(f"{key}={value}\n")
    (root / "service.env").write_text("".join(environment_lines))
    commands = {"worker": f"{python} -m graphword.trabajos.aws_worker worker"}
    if sys.argv[1] == "api":
        commands["api"] = f"{python} -m uvicorn graphword.api.aws_app:app --host 127.0.0.1 --port 8000"
        commands["reconcile"] = f"{python} -m graphword.trabajos.aws_worker reconcile"
    # systemd mantiene estos procesos activos y los reinicia si fallan.
    for name, command in commands.items():
        Path(f"/etc/systemd/system/graphword-{name}.service").write_text(
            "[Unit]\nDescription=GraphWord " + name + "\nAfter=network-online.target\n"
            "Wants=network-online.target\n[Service]\nUser=graphword\n"
            f"WorkingDirectory={root}\nEnvironmentFile={root}/service.env\nExecStart={command}\n"
            "Restart=always\nRestartSec=5\nNoNewPrivileges=true\nPrivateTmp=true\n"
            "ProtectSystem=strict\nProtectHome=true\n[Install]\nWantedBy=multi-user.target\n"
        )
    # Cargar la configuración creada y arrancar cada servicio.
    run("systemctl", "daemon-reload")
    for name in commands:
        run("systemctl", "enable", "--now", f"graphword-{name}.service")


if __name__ == "__main__":
    main()
