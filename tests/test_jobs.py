from datetime import datetime, timedelta, timezone
import unittest
from uuid import UUID

from graphword.jobs import (
    InMemoryJobRepository,
    InvalidJobTransition,
    JobKind,
    JobStatus,
)
from graphword.storage import InMemoryGraphRepository
from graphword.worker import GraphWordWorker


JOB_ID = UUID("00000000-0000-0000-0000-000000000010")
TOKEN_1 = UUID("00000000-0000-0000-0000-000000000011")
TOKEN_2 = UUID("00000000-0000-0000-0000-000000000012")
GRAPH_ID = UUID("00000000-0000-0000-0000-000000000020")


class ManualClock:
    def __init__(self):
        self.now = datetime(2026, 9, 6, tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)


class JobTests(unittest.TestCase):
    def make_repository(self, max_tokens=2):
        clock = ManualClock()
        tokens = iter([TOKEN_1, TOKEN_2][:max_tokens])
        repository = InMemoryJobRepository(
            id_factory=lambda: JOB_ID,
            token_factory=lambda: next(tokens),
            clock=clock,
        )
        return repository, clock

    def test_job_moves_from_pending_to_running_to_succeeded(self):
        repository, _ = self.make_repository()
        created = repository.create(JobKind.GRAPH_BUILD, {"words": ["cat"]})
        self.assertEqual(created.status, JobStatus.PENDING)
        self.assertEqual(created.attempts, 0)

        claim = repository.claim_next("worker-a")
        self.assertIsNotNone(claim)
        self.assertEqual(repository.get(JOB_ID).status, JobStatus.RUNNING)
        completed = repository.complete(claim, {"graph_id": str(GRAPH_ID)})
        self.assertEqual(completed.status, JobStatus.SUCCEEDED)
        self.assertEqual(completed.result, {"graph_id": str(GRAPH_ID)})
        self.assertIsNone(repository.claim_next("worker-b"))

    def test_expired_lease_is_reclaimed_and_old_worker_cannot_complete(self):
        repository, clock = self.make_repository()
        repository.create(JobKind.GRAPH_BUILD, {"words": ["cat"]})
        old_claim = repository.claim_next("worker-old", lease_seconds=5)
        clock.advance(5)
        new_claim = repository.claim_next("worker-new", lease_seconds=5)

        self.assertEqual(new_claim.attempt, 2)
        self.assertNotEqual(new_claim.attempt_token, old_claim.attempt_token)
        with self.assertRaises(InvalidJobTransition):
            repository.complete(old_claim, {"graph_id": "stale"})
        completed = repository.complete(new_claim, {"graph_id": str(GRAPH_ID)})
        self.assertEqual(completed.status, JobStatus.SUCCEEDED)

    def test_retry_limit_ends_in_failed(self):
        repository, _ = self.make_repository()
        repository.create(JobKind.GRAPH_BUILD, {}, max_attempts=2)
        first = repository.claim_next("worker")
        retried = repository.fail(first, "temporary", retryable=True)
        self.assertEqual(retried.status, JobStatus.PENDING)
        second = repository.claim_next("worker")
        failed = repository.fail(second, "again", retryable=True)
        self.assertEqual(failed.status, JobStatus.FAILED)
        self.assertEqual(failed.attempts, 2)

    def test_worker_builds_graph_and_publishes_result(self):
        jobs, _ = self.make_repository()
        graphs = InMemoryGraphRepository(id_factory=lambda: GRAPH_ID)
        jobs.create(JobKind.GRAPH_BUILD, {
            "words": ["cat", "bat", "bad", "dad"],
            "partitions": 2,
        })
        worker = GraphWordWorker(jobs, graphs)

        self.assertTrue(worker.run_once("worker-a"))
        self.assertFalse(worker.run_once("worker-a"))
        self.assertEqual(jobs.get(JOB_ID).status, JobStatus.SUCCEEDED)
        self.assertEqual(graphs.get(GRAPH_ID)["cat"], {"bat"})

    def test_invalid_job_configuration_is_rejected(self):
        repository, _ = self.make_repository()
        with self.assertRaises(ValueError):
            repository.create(JobKind.GRAPH_BUILD, {}, max_attempts=0)
        with self.assertRaises(ValueError):
            repository.claim_next("")
        with self.assertRaises(ValueError):
            repository.claim_next("worker", lease_seconds=0)


if __name__ == "__main__":
    unittest.main()
