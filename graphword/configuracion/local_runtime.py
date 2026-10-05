"""Elegir la base de datos compartida por la API y los workers locales."""

import os
from pathlib import Path


DATABASE_ENVIRONMENT_VARIABLE = "GRAPHWORD_DB_PATH"
DEFAULT_DATABASE = Path("var/graphword.db")


def database_path(explicit_path: str | Path | None = None) -> Path:
    # La ruta explícita tiene prioridad sobre la variable de entorno.
    configured = explicit_path
    if not configured:
        configured = os.environ.get(DATABASE_ENVIRONMENT_VARIABLE)
    if configured:
        path = Path(configured)
    else:
        path = DEFAULT_DATABASE
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
