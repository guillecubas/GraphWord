"""Job state machine and a process-local repository adapter."""

from collections import deque
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from threading import RLock
from typing import Any, Protocol
from uuid import UUID, uuid4


class JobKind(StrEnum):
    GRAPH_BUILD = "GRAPH_BUILD"
    BUILD_PARTITION = "BUILD_PARTITION"
    REDUCE_GRAPH = "REDUCE_GRAPH"


class JobStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class JobNotFoundError(KeyError):
    """Raised when a job identifier does not exist."""


class InvalidJobTransition(RuntimeError):
    """Raised for stale claims or invalid terminal transitions."""


@dataclass(frozen=True)
class Job:
    job_id: UUID
    kind: JobKind
    status: JobStatus
    attempts: int
    max_attempts: int
    result: dict[str, Any] | None
    error: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ClaimedJob:
    job_id: UUID
    kind: JobKind
    payload: dict[str, Any]
    worker_id: str
    attempt: int
    attempt_token: UUID
    lease_expires_at: datetime


class JobRepository(Protocol):
    def create(
        self,
        kind: JobKind,
        payload: Mapping[str, Any],
        max_attempts: int = 3,
    ) -> Job: ...

    def get(self, job_id: UUID) -> Job: ...

    def claim_next(self, worker_id: str, lease_seconds: int = 30) -> ClaimedJob | None: ...

    def complete(self, claim: ClaimedJob, result: Mapping[str, Any]) -> Job: ...

    def fail(self, claim: ClaimedJob, error: str, retryable: bool = True) -> Job: ...


class PartitionedBuildRepository(Protocol):
    def create_partitioned_build(self, words: list[str], partitions: int) -> Job: ...


@dataclass
class _JobRecord:
    job_id: UUID
    kind: JobKind
    payload: dict[str, Any]
    status: JobStatus
    attempts: int
    max_attempts: int
    result: dict[str, Any] | None
    error: str | None
    created_at: datetime
    updated_at: datetime
    worker_id: str | None = None
    attempt_token: UUID | None = None
    lease_expires_at: datetime | None = None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class InMemoryJobRepository:
    """Atomic only inside one process; this is not an SQS/DynamoDB substitute."""

    def __init__(
        self,
        *,
        id_factory: Callable[[], UUID] = uuid4,
        token_factory: Callable[[], UUID] = uuid4,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._id_factory = id_factory
        self._token_factory = token_factory
        self._clock = clock
        self._records: dict[UUID, _JobRecord] = {}
        self._pending: deque[UUID] = deque()
        self._lock = RLock()

    def create(
        self,
        kind: JobKind,
        payload: Mapping[str, Any],
        max_attempts: int = 3,
    ) -> Job:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        now = self._clock()
        job_id = self._id_factory()
        record = _JobRecord(
            job_id=job_id,
            kind=kind,
            payload=deepcopy(dict(payload)),
            status=JobStatus.PENDING,
            attempts=0,
            max_attempts=max_attempts,
            result=None,
            error=None,
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            if job_id in self._records:
                raise ValueError("job id already exists")
            self._records[job_id] = record
            self._pending.append(job_id)
            return self._snapshot(record)

    def get(self, job_id: UUID) -> Job:
        with self._lock:
            try:
                return self._snapshot(self._records[job_id])
            except KeyError as error:
                raise JobNotFoundError(str(job_id)) from error

    def claim_next(self, worker_id: str, lease_seconds: int = 30) -> ClaimedJob | None:
        if not worker_id.strip():
            raise ValueError("worker_id must not be empty")
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be positive")
        with self._lock:
            now = self._clock()
            self._recover_expired(now)
            while self._pending:
                job_id = self._pending.popleft()
                record = self._records[job_id]
                if record.status is not JobStatus.PENDING:
                    continue
                token = self._token_factory()
                record.status = JobStatus.RUNNING
                record.attempts += 1
                record.error = None
                record.worker_id = worker_id
                record.attempt_token = token
                record.lease_expires_at = now + timedelta(seconds=lease_seconds)
                record.updated_at = now
                return ClaimedJob(
                    job_id=job_id,
                    kind=record.kind,
                    payload=deepcopy(record.payload),
                    worker_id=worker_id,
                    attempt=record.attempts,
                    attempt_token=token,
                    lease_expires_at=record.lease_expires_at,
                )
            return None

    def complete(self, claim: ClaimedJob, result: Mapping[str, Any]) -> Job:
        with self._lock:
            record = self._active_record(claim)
            now = self._clock()
            record.status = JobStatus.SUCCEEDED
            record.result = deepcopy(dict(result))
            record.error = None
            self._clear_lease(record)
            record.updated_at = now
            return self._snapshot(record)

    def fail(self, claim: ClaimedJob, error: str, retryable: bool = True) -> Job:
        with self._lock:
            record = self._active_record(claim)
            now = self._clock()
            record.error = error
            self._clear_lease(record)
            if retryable and record.attempts < record.max_attempts:
                record.status = JobStatus.PENDING
                self._pending.append(record.job_id)
            else:
                record.status = JobStatus.FAILED
            record.updated_at = now
            return self._snapshot(record)

    def _recover_expired(self, now: datetime) -> None:
        for record in sorted(self._records.values(), key=lambda item: str(item.job_id)):
            if (
                record.status is not JobStatus.RUNNING
                or record.lease_expires_at is None
                or record.lease_expires_at > now
            ):
                continue
            record.error = "worker lease expired"
            self._clear_lease(record)
            if record.attempts < record.max_attempts:
                record.status = JobStatus.PENDING
                self._pending.append(record.job_id)
            else:
                record.status = JobStatus.FAILED
            record.updated_at = now

    def _active_record(self, claim: ClaimedJob) -> _JobRecord:
        try:
            record = self._records[claim.job_id]
        except KeyError as error:
            raise JobNotFoundError(str(claim.job_id)) from error
        now = self._clock()
        if (
            record.status is not JobStatus.RUNNING
            or record.worker_id != claim.worker_id
            or record.attempt_token != claim.attempt_token
            or record.lease_expires_at is None
            or record.lease_expires_at <= now
        ):
            raise InvalidJobTransition("claim is stale or no longer active")
        return record

    @staticmethod
    def _clear_lease(record: _JobRecord) -> None:
        record.worker_id = None
        record.attempt_token = None
        record.lease_expires_at = None

    @staticmethod
    def _snapshot(record: _JobRecord) -> Job:
        return Job(
            job_id=record.job_id,
            kind=record.kind,
            status=record.status,
            attempts=record.attempts,
            max_attempts=record.max_attempts,
            result=deepcopy(record.result),
            error=record.error,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
