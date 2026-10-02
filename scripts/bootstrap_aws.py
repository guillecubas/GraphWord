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
    root = Path("/opt/graphword")
    config = json.loads((root / "deployment.json").read_text())
    run("useradd", "--system", "--home-dir", str(root), "--shell", "/sbin/nologin", "graphword")
    run(sys.executable, "-m", "venv", str(root / ".venv"))
    python = str(root / ".venv/bin/python")
    run(python, "-m", "pip", "install", str(root) + "[aws]")
    environment = {
        "AWS_DEFAULT_REGION": config["region"], "GRAPHWORD_BUCKET": config["Bucket"],
        "GRAPHWORD_TABLE": config["Table"], "GRAPHWORD_QUEUE_URL": config["QueueUrl"],
        "PYTHONUNBUFFERED": "1",
    }
    (root / "service.env").write_text("".join(f"{key}={value}\n" for key, value in environment.items()))
    commands = {"worker": f"{python} -m graphword.aws_worker worker"}
    if sys.argv[1] == "api":
        commands.update(api=f"{python} -m uvicorn graphword.aws_app:app --host 127.0.0.1 --port 8000",
                        reconcile=f"{python} -m graphword.aws_worker reconcile")
    for name, command in commands.items():
        Path(f"/etc/systemd/system/graphword-{name}.service").write_text(
            "[Unit]\nDescription=GraphWord " + name + "\nAfter=network-online.target\n"
            "Wants=network-online.target\n[Service]\nUser=graphword\n"
            f"WorkingDirectory={root}\nEnvironmentFile={root}/service.env\nExecStart={command}\n"
            "Restart=always\nRestartSec=5\nNoNewPrivileges=true\nPrivateTmp=true\n"
            "ProtectSystem=strict\nProtectHome=true\n[Install]\nWantedBy=multi-user.target\n"
        )
    run("systemctl", "daemon-reload")
    for name in commands:
        run("systemctl", "enable", "--now", f"graphword-{name}.service")


if __name__ == "__main__":
    main()
