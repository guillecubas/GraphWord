from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from uuid import UUID

from graphword.jobs import InvalidJobTransition, JobKind, JobStatus
from graphword.sqlite_storage import SQLiteGraphRepository, SQLiteJobRepository
from graphword.worker import GraphWordWorker


JOB_ID = UUID("00000000-0000-0000-0000-000000000030")
TOKEN_1 = UUID("00000000-0000-0000-0000-000000000031")
TOKEN_2 = UUID("00000000-0000-0000-0000-000000000032")
GRAPH_ID = UUID("00000000-0000-0000-0000-000000000040")


class ManualClock:
    def __init__(self):
        self.now = datetime(2026, 9, 7, tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)


class SQLiteStorageTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.database = Path(self.temporary_directory.name) / "graphword.db"

    def test_graph_survives_repository_recreation(self):
        writer = SQLiteGraphRepository(self.database, id_factory=lambda: GRAPH_ID)
        writer.save({"cat": {"bat"}, "bat": {"cat"}, "dog": set()})

        reader = SQLiteGraphRepository(self.database)
        self.assertEqual(reader.get(GRAPH_ID), {
            "bat": {"cat"}, "cat": {"bat"}, "dog": set(),
        })

    def test_separate_repository_instances_share_jobs_and_graphs(self):
        api_jobs = SQLiteJobRepository(self.database, id_factory=lambda: JOB_ID)
        api_jobs.create(JobKind.GRAPH_BUILD, {
            "words": ["cat", "bat", "bad", "dad"], "partitions": 2,
        })

        worker_jobs = SQLiteJobRepository(self.database)
        worker_graphs = SQLiteGraphRepository(self.database, id_factory=lambda: GRAPH_ID)
        worker = GraphWordWorker(worker_jobs, worker_graphs)
        self.assertTrue(worker.run_once("worker-process"))

        self.assertEqual(api_jobs.get(JOB_ID).status, JobStatus.SUCCEEDED)
        self.assertEqual(api_jobs.get(JOB_ID).result, {"graph_id": str(GRAPH_ID)})
        api_graphs = SQLiteGraphRepository(self.database)
        self.assertEqual(api_graphs.get(GRAPH_ID)["cat"], {"bat"})

    def test_transactional_claim_allows_only_one_worker(self):
        jobs = SQLiteJobRepository(self.database, id_factory=lambda: JOB_ID)
        jobs.create(JobKind.GRAPH_BUILD, {"words": ["cat"], "partitions": 1})
        worker_a = SQLiteJobRepository(self.database)
        worker_b = SQLiteJobRepository(self.database)
        with ThreadPoolExecutor(max_workers=2) as executor:
            claims = list(executor.map(
                lambda pair: pair[0].claim_next(pair[1]),
                [(worker_a, "worker-a"), (worker_b, "worker-b")],
            ))
        self.assertEqual(sum(claim is not None for claim in claims), 1)
        self.assertEqual(jobs.get(JOB_ID).attempts, 1)

    def test_expired_sqlite_claim_is_recovered_across_instances(self):
        clock = ManualClock()
        tokens = iter([TOKEN_1, TOKEN_2])
        jobs = SQLiteJobRepository(
            self.database,
            id_factory=lambda: JOB_ID,
            token_factory=lambda: next(tokens),
            clock=clock,
        )
        jobs.create(JobKind.GRAPH_BUILD, {"words": ["cat"], "partitions": 1})
        old_claim = jobs.claim_next("old", lease_seconds=5)
        clock.advance(5)

        restarted = SQLiteJobRepository(
            self.database,
            token_factory=lambda: next(tokens),
            clock=clock,
        )
        new_claim = restarted.claim_next("new", lease_seconds=5)
        self.assertEqual(new_claim.attempt, 2)
        with self.assertRaises(InvalidJobTransition):
            jobs.complete(old_claim, {"graph_id": "stale"})
        completed = restarted.complete(new_claim, {"graph_id": str(GRAPH_ID)})
        self.assertEqual(completed.status, JobStatus.SUCCEEDED)


if __name__ == "__main__":
    unittest.main()
