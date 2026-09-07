"""Configuration shared by the local persistent API and worker entry points."""

import os
from pathlib import Path


DATABASE_ENVIRONMENT_VARIABLE = "GRAPHWORD_DB_PATH"
DEFAULT_DATABASE = Path("var/graphword.db")


def database_path(explicit_path: str | Path | None = None) -> Path:
    configured = explicit_path or os.environ.get(DATABASE_ENVIRONMENT_VARIABLE)
    path = Path(configured) if configured else DEFAULT_DATABASE
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
