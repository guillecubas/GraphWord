# Pruebas del almacenamiento persistente y de las reservas entre procesos.
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from uuid import UUID

from graphword.trabajos.jobs import InvalidJobTransition, JobKind, JobStatus
from graphword.almacenamiento.sqlite_storage import SQLiteGraphRepository, SQLiteJobRepository
from graphword.trabajos.worker import GraphWordWorker


JOB_ID = UUID("00000000-0000-0000-0000-000000000030")
TOKEN_1 = UUID("00000000-0000-0000-0000-000000000031")
TOKEN_2 = UUID("00000000-0000-0000-0000-000000000032")
GRAPH_ID = UUID("00000000-0000-0000-0000-000000000040")


# Estas fábricas devuelven los mismos identificadores en cada prueba.
def fixed_job_id():
    return JOB_ID


def fixed_graph_id():
    return GRAPH_ID


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
        writer = SQLiteGraphRepository(self.database, id_factory=fixed_graph_id)
        writer.save({"cat": {"bat"}, "bat": {"cat"}, "dog": set()})

        reader = SQLiteGraphRepository(self.database)
        self.assertEqual(reader.get(GRAPH_ID), {
            "bat": {"cat"}, "cat": {"bat"}, "dog": set(),
        })

    def test_separate_repository_instances_share_jobs_and_graphs(self):
        api_jobs = SQLiteJobRepository(self.database, id_factory=fixed_job_id)
        api_jobs.create(JobKind.GRAPH_BUILD, {
            "words": ["cat", "bat", "bad", "dad"], "partitions": 2,
        })

        worker_jobs = SQLiteJobRepository(self.database)
        worker_graphs = SQLiteGraphRepository(self.database, id_factory=fixed_graph_id)
        worker = GraphWordWorker(worker_jobs, worker_graphs)
        self.assertTrue(worker.run_once("worker-process"))

        self.assertEqual(api_jobs.get(JOB_ID).status, JobStatus.SUCCEEDED)
        self.assertEqual(api_jobs.get(JOB_ID).result, {"graph_id": str(GRAPH_ID)})
        api_graphs = SQLiteGraphRepository(self.database)
        self.assertEqual(api_graphs.get(GRAPH_ID)["cat"], {"bat"})

    def test_transactional_claim_allows_only_one_worker(self):
        jobs = SQLiteJobRepository(self.database, id_factory=fixed_job_id)
        jobs.create(JobKind.GRAPH_BUILD, {"words": ["cat"], "partitions": 1})
        worker_a = SQLiteJobRepository(self.database)
        worker_b = SQLiteJobRepository(self.database)
        def claim_task(pair):
            repository = pair[0]
            worker_id = pair[1]
            return repository.claim_next(worker_id)

        # Los dos hilos compiten por una única tarea disponible.
        with ThreadPoolExecutor(max_workers=2) as executor:
            claims = list(executor.map(
                claim_task,
                [(worker_a, "worker-a"), (worker_b, "worker-b")],
            ))
        claimed_count = 0
        for claim in claims:
            if claim is not None:
                claimed_count += 1
        self.assertEqual(claimed_count, 1)
        self.assertEqual(jobs.get(JOB_ID).attempts, 1)

    def test_expired_sqlite_claim_is_recovered_across_instances(self):
        clock = ManualClock()
        tokens = iter([TOKEN_1, TOKEN_2])

        def next_token():
            return next(tokens)
        jobs = SQLiteJobRepository(
            self.database,
            id_factory=fixed_job_id,
            token_factory=next_token,
            clock=clock,
        )
        jobs.create(JobKind.GRAPH_BUILD, {"words": ["cat"], "partitions": 1})
        old_claim = jobs.claim_next("old", lease_seconds=5)
        clock.advance(5)

        restarted = SQLiteJobRepository(
            self.database,
            token_factory=next_token,
            clock=clock,
        )
        new_claim = restarted.claim_next("new", lease_seconds=5)
        self.assertEqual(new_claim.attempt, 2)
        with self.assertRaises(InvalidJobTransition):
            jobs.complete(old_claim, {"graph_id": "stale"})
        completed = restarted.complete(new_claim, {"graph_id": str(GRAPH_ID)})
        self.assertEqual(completed.status, JobStatus.SUCCEEDED)

    def test_worker_cli_processes_job_in_a_separate_process(self):
        jobs = SQLiteJobRepository(self.database, id_factory=fixed_job_id)
        jobs.create(JobKind.GRAPH_BUILD, {
            "words": ["cat", "bat", "bad", "dad"], "partitions": 2,
        })
        root = Path(__file__).resolve().parents[1]
        output = subprocess.check_output(
            [
                sys.executable, "-m", "graphword.trabajos.worker_cli",
                "--database", str(self.database), "--worker-id", "process-b",
                "--once",
            ],
            cwd=root,
            text=True,
        )
        self.assertEqual(json.loads(output), {
            "worker_id": "process-b", "processed": True,
        })
        completed = jobs.get(JOB_ID)
        self.assertEqual(completed.status, JobStatus.SUCCEEDED)
        graph_id = UUID(completed.result["graph_id"])
        self.assertEqual(SQLiteGraphRepository(self.database).get(graph_id)["cat"], {"bat"})


if __name__ == "__main__":
    unittest.main()
