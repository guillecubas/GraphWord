"""Workflow evidence: separate processes, gating, retries and atomic submission."""

import json
from contextlib import closing
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from uuid import UUID

from fastapi.testclient import TestClient

from graphword.api import create_app
from graphword.graph import build_partition
from graphword.jobs import InvalidJobTransition, JobKind, JobStatus
from graphword.sqlite_storage import SQLiteGraphRepository, SQLiteJobRepository
from graphword.worker import GraphWordWorker


class PartitionedBuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "workflow.db"
        self.jobs = SQLiteJobRepository(self.path)
        self.graphs = SQLiteGraphRepository(self.path)
        self.words = ["cat", "bat", "bad", "dad", "dog", "cats"]
        self.worker = GraphWordWorker(self.jobs, self.graphs)

    def test_http_build_reduced_after_two_worker_processes(self):
        with TestClient(create_app(self.graphs, self.jobs, partitioned_builds=self.jobs)) as api:
            submitted = api.post("/v1/jobs/partitioned-builds", json={
                "words": self.words, "partitions": 2,
            })
            self.assertEqual(submitted.status_code, 202)
            location = submitted.headers["location"]
            # Explicitly give each distinct process one partition. This demonstrates
            # collaboration, not a speedup benchmark or guaranteed fair scheduling.
            for worker_id in ("worker-a", "worker-b"):
                completed = subprocess.run([
                    sys.executable, "-m", "graphword.worker_cli", "--once",
                    "--database", str(self.path), "--worker-id", worker_id,
                ], cwd=Path(__file__).resolve().parents[1], capture_output=True,
                    text=True, check=True, timeout=30)
                self.assertTrue(json.loads(completed.stdout)["processed"])
                self.assertEqual(api.get(location).json()["status"], "PENDING")
            self.assertTrue(self.worker.run_once("reducer"))
            result = api.get(location).json()
            self.assertEqual(result["status"], "SUCCEEDED")
            actual = self.graphs.get(UUID(result["result"]["graph_id"]))
            self.assertEqual(actual, build_partition(self.words))
            self.assertEqual(actual["cats"], set())
            self.assertFalse(self.worker.run_once("idle"))
        with closing(sqlite3.connect(self.path)) as connection:
            results = connection.execute(
                "SELECT result_json FROM jobs WHERE kind = 'BUILD_PARTITION'"
            ).fetchall()
        self.assertEqual({json.loads(row[0])["worker_id"] for row in results},
                         {"worker-a", "worker-b"})

    def test_reducer_cannot_be_claimed_while_partition_is_running(self):
        parent = self.jobs.create_partitioned_build(self.words, 1)
        claim = self.jobs.claim_next("a")
        self.assertEqual(claim.kind, JobKind.BUILD_PARTITION)
        self.assertIsNone(self.jobs.claim_next("b"))
        self.assertEqual(self.jobs.get(parent.job_id).attempts, 0)
        self.jobs.fail(claim, "permanent", retryable=False)
        self.assertEqual(self.jobs.get(parent.job_id).status, JobStatus.FAILED)
        self.assertIsNone(self.jobs.get(parent.job_id).result)
        self.assertIsNone(self.jobs.claim_next("b"))

    def test_retry_and_duplicate_completion_do_not_publish_twice(self):
        parent = self.jobs.create_partitioned_build(self.words, 1)
        old = self.jobs.claim_next("a")
        self.jobs.fail(old, "temporary")
        self.assertTrue(self.worker.run_once("b"))
        with self.assertRaises(InvalidJobTransition):
            self.jobs.complete(old, {"graph_id": "stale"})
        self.assertTrue(self.worker.run_once("reducer"))
        self.assertEqual(self.jobs.get(parent.job_id).status, JobStatus.SUCCEEDED)
        self.assertFalse(self.worker.run_once("duplicate"))

    def test_submission_rolls_back_if_dependency_insert_fails(self):
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("""CREATE TRIGGER reject_dependency
                BEFORE INSERT ON job_dependencies BEGIN
                SELECT RAISE(ABORT, 'simulated failure'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            self.jobs.create_partitioned_build(self.words, 2)
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 0)

    def test_invalid_dictionary_leaves_no_work(self):
        with self.assertRaises(ValueError):
            self.jobs.create_partitioned_build(["123"], 2)
        self.assertIsNone(self.jobs.claim_next("a"))


if __name__ == "__main__":
    unittest.main()
