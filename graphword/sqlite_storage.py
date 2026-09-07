"""SQLite adapters for local multi-process API and worker demonstrations."""

from collections.abc import Callable, Mapping
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator
from uuid import UUID, uuid4

from graphword.graph import Graph, normalize_words
from graphword.jobs import (
    ClaimedJob,
    InvalidJobTransition,
    Job,
    JobKind,
    JobNotFoundError,
    JobStatus,
    utc_now,
)
from graphword.storage import GraphNotFoundError


SCHEMA = """
CREATE TABLE IF NOT EXISTS graphs (
    graph_id TEXT PRIMARY KEY,
    adjacency_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    attempts INTEGER NOT NULL,
    max_attempts INTEGER NOT NULL,
    result_json TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    worker_id TEXT,
    attempt_token TEXT,
    lease_expires_at TEXT
);

CREATE INDEX IF NOT EXISTS jobs_pending_order
ON jobs(status, created_at, job_id);

CREATE TABLE IF NOT EXISTS job_dependencies (
    parent_id TEXT NOT NULL REFERENCES jobs(job_id),
    child_id TEXT NOT NULL REFERENCES jobs(job_id),
    PRIMARY KEY(parent_id, child_id)
);
"""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("clock must return timezone-aware datetimes")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


class _SQLiteAdapter:
    def __init__(self, database: str | Path) -> None:
        self._database = str(database)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(SCHEMA)


class SQLiteGraphRepository(_SQLiteAdapter):
    """Durable graph repository shared by local processes through one database."""

    def __init__(
        self,
        database: str | Path,
        *,
        id_factory: Callable[[], UUID] = uuid4,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._id_factory = id_factory
        self._clock = clock
        super().__init__(database)

    def save(self, graph: Graph) -> UUID:
        graph_id = self._id_factory()
        adjacency = {
            node: sorted(neighbors)
            for node, neighbors in sorted(graph.items())
        }
        try:
            with self._connection() as connection:
                connection.execute(
                    "INSERT INTO graphs(graph_id, adjacency_json, created_at) VALUES (?, ?, ?)",
                    (str(graph_id), _json(adjacency), _timestamp(self._clock())),
                )
        except sqlite3.IntegrityError as error:
            raise ValueError("graph id already exists") from error
        return graph_id

    def get(self, graph_id: UUID) -> Graph:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT adjacency_json FROM graphs WHERE graph_id = ?",
                (str(graph_id),),
            ).fetchone()
        if row is None:
            raise GraphNotFoundError(str(graph_id))
        adjacency = json.loads(row["adjacency_json"])
        return {node: set(neighbors) for node, neighbors in adjacency.items()}


class SQLiteJobRepository(_SQLiteAdapter):
    """Durable local queue and catalogue with transactional job claims."""

    def __init__(
        self,
        database: str | Path,
        *,
        id_factory: Callable[[], UUID] = uuid4,
        token_factory: Callable[[], UUID] = uuid4,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._id_factory = id_factory
        self._token_factory = token_factory
        self._clock = clock
        super().__init__(database)

    def create_partitioned_build(self, words: list[str], partitions: int) -> Job:
        """Atomically register all partitions and their waiting reducer."""
        if not 1 <= partitions <= 64:
            raise ValueError("partitions must be between 1 and 64")
        clean = normalize_words(words)
        if not clean:
            raise ValueError("no valid words supplied")
        parent_id = uuid4()
        child_ids = [uuid4() for _ in range(partitions)]
        now = _timestamp(self._clock())
        records = [(parent_id, JobKind.REDUCE_GRAPH, {
            "partition_jobs": [str(child_id) for child_id in child_ids],
        })]
        records.extend((child_id, JobKind.BUILD_PARTITION, {
            "words": clean, "partition": index, "partitions": partitions,
        }) for index, child_id in enumerate(child_ids))
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for job_id, kind, payload in records:
                connection.execute(
                    """INSERT INTO jobs(job_id, kind, status, payload_json,
                       attempts, max_attempts, created_at, updated_at)
                       VALUES (?, ?, 'PENDING', ?, 0, 3, ?, ?)""",
                    (str(job_id), kind.value, _json(payload), now, now),
                )
            connection.executemany(
                "INSERT INTO job_dependencies(parent_id, child_id) VALUES (?, ?)",
                [(str(parent_id), str(child_id)) for child_id in child_ids],
            )
        return self.get(parent_id)

    def create(
        self,
        kind: JobKind,
        payload: Mapping[str, Any],
        max_attempts: int = 3,
    ) -> Job:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        job_id = self._id_factory()
        now = _timestamp(self._clock())
        try:
            with self._connection() as connection:
                connection.execute(
                    """
                    INSERT INTO jobs(
                        job_id, kind, status, payload_json, attempts, max_attempts,
                        result_json, error, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 0, ?, NULL, NULL, ?, ?)
                    """,
                    (str(job_id), kind.value, JobStatus.PENDING.value,
                     _json(dict(payload)), max_attempts, now, now),
                )
        except sqlite3.IntegrityError as error:
            raise ValueError("job id already exists") from error
        return self.get(job_id)

    def get(self, job_id: UUID) -> Job:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (str(job_id),)
            ).fetchone()
        if row is None:
            raise JobNotFoundError(str(job_id))
        return self._snapshot(row)

    def claim_next(self, worker_id: str, lease_seconds: int = 30) -> ClaimedJob | None:
        if not worker_id.strip():
            raise ValueError("worker_id must not be empty")
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be positive")
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            # Read the clock after acquiring the lock, not before waiting for it.
            now_value = self._clock()
            now = _timestamp(now_value)
            lease_expires_at = now_value + timedelta(seconds=lease_seconds)
            connection.execute(
                """
                UPDATE jobs
                SET status = CASE WHEN attempts < max_attempts THEN ? ELSE ? END,
                    error = 'worker lease expired', worker_id = NULL,
                    attempt_token = NULL, lease_expires_at = NULL, updated_at = ?
                WHERE status = ? AND lease_expires_at <= ?
                """,
                (JobStatus.PENDING.value, JobStatus.FAILED.value, now,
                 JobStatus.RUNNING.value, now),
            )
            self._propagate_failures(connection, now)
            row = connection.execute(
                """
                SELECT * FROM jobs
                WHERE status = ? AND NOT EXISTS (
                    SELECT 1 FROM job_dependencies AS d
                    JOIN jobs AS child ON child.job_id = d.child_id
                    WHERE d.parent_id = jobs.job_id AND child.status != 'SUCCEEDED'
                )
                ORDER BY created_at, job_id
                LIMIT 1
                """,
                (JobStatus.PENDING.value,),
            ).fetchone()
            if row is None:
                return None
            token = self._token_factory()
            attempt = row["attempts"] + 1
            connection.execute(
                """
                UPDATE jobs
                SET status = ?, attempts = ?, error = NULL, worker_id = ?,
                    attempt_token = ?, lease_expires_at = ?, updated_at = ?
                WHERE job_id = ? AND status = ?
                """,
                (JobStatus.RUNNING.value, attempt, worker_id, str(token),
                 _timestamp(lease_expires_at), now, row["job_id"],
                 JobStatus.PENDING.value),
            )
            return ClaimedJob(
                job_id=UUID(row["job_id"]),
                kind=JobKind(row["kind"]),
                payload=json.loads(row["payload_json"]),
                worker_id=worker_id,
                attempt=attempt,
                attempt_token=token,
                lease_expires_at=lease_expires_at,
            )

    def complete(self, claim: ClaimedJob, result: Mapping[str, Any]) -> Job:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            now = self._clock()
            self._require_active(connection, claim, now)
            connection.execute(
                """
                UPDATE jobs
                SET status = ?, result_json = ?, error = NULL, worker_id = NULL,
                    attempt_token = NULL, lease_expires_at = NULL, updated_at = ?
                WHERE job_id = ?
                """,
                (JobStatus.SUCCEEDED.value, _json(dict(result)), _timestamp(now),
                 str(claim.job_id)),
            )
        return self.get(claim.job_id)

    def fail(self, claim: ClaimedJob, error: str, retryable: bool = True) -> Job:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            now = self._clock()
            row = self._require_active(connection, claim, now)
            status = (
                JobStatus.PENDING
                if retryable and row["attempts"] < row["max_attempts"]
                else JobStatus.FAILED
            )
            connection.execute(
                """
                UPDATE jobs
                SET status = ?, error = ?, worker_id = NULL, attempt_token = NULL,
                    lease_expires_at = NULL, updated_at = ?
                WHERE job_id = ?
                """,
                (status.value, error, _timestamp(now), str(claim.job_id)),
            )
            self._propagate_failures(connection, _timestamp(now))
        return self.get(claim.job_id)

    @staticmethod
    def _propagate_failures(connection: sqlite3.Connection, now: str) -> None:
        # This workflow has exactly one dependency level: partitions -> reducer.
        connection.execute(
            """UPDATE jobs SET status = 'FAILED', error = 'partition job failed',
               updated_at = ? WHERE status = 'PENDING' AND EXISTS (
                   SELECT 1 FROM job_dependencies AS d
                   JOIN jobs AS child ON child.job_id = d.child_id
                   WHERE d.parent_id = jobs.job_id AND child.status = 'FAILED'
               )""", (now,),
        )

    @staticmethod
    def _require_active(
        connection: sqlite3.Connection,
        claim: ClaimedJob,
        now: datetime,
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM jobs WHERE job_id = ?", (str(claim.job_id),)
        ).fetchone()
        if row is None:
            raise JobNotFoundError(str(claim.job_id))
        if (
            row["status"] != JobStatus.RUNNING.value
            or row["worker_id"] != claim.worker_id
            or row["attempt_token"] != str(claim.attempt_token)
            or row["lease_expires_at"] is None
            or datetime.fromisoformat(row["lease_expires_at"]) <= now
        ):
            raise InvalidJobTransition("claim is stale or no longer active")
        return row

    @staticmethod
    def _snapshot(row: sqlite3.Row) -> Job:
        return Job(
            job_id=UUID(row["job_id"]),
            kind=JobKind(row["kind"]),
            status=JobStatus(row["status"]),
            attempts=row["attempts"],
            max_attempts=row["max_attempts"],
            result=json.loads(row["result_json"]) if row["result_json"] else None,
            error=row["error"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
