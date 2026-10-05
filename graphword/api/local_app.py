"""Aplicación local que Uvicorn arranca con persistencia compartida en SQLite."""

from graphword.api.routes import create_app
from graphword.configuracion.local_runtime import database_path
from graphword.almacenamiento.sqlite_storage import SQLiteGraphRepository, SQLiteJobRepository


# Usar el mismo archivo SQLite que utilizan los workers locales.
database = database_path()
jobs = SQLiteJobRepository(database)
app = create_app(
    SQLiteGraphRepository(database),
    jobs,
    storage_label="sqlite-local-shared",
    partitioned_builds=jobs,
)
