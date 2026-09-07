"""Uvicorn entry point backed by local shared SQLite persistence."""

from graphword.api import create_app
from graphword.local_runtime import database_path
from graphword.sqlite_storage import SQLiteGraphRepository, SQLiteJobRepository


database = database_path()
jobs = SQLiteJobRepository(database)
app = create_app(
    SQLiteGraphRepository(database),
    jobs,
    storage_label="sqlite-local-shared",
    partitioned_builds=jobs,
)
