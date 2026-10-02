from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import hashlib
import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from graphword.api import create_app
from graphword.jobs import InMemoryJobRepository, JobKind, JobStatus, InvalidJobTransition
from graphword.sqlite_storage import SQLiteJobRepository
from graphword.storage import InMemoryGraphRepository
from graphword.submissions import IdempotencyConflict
from graphword.worker import GraphWordWorker
from scripts.build_corpus import lexical_entries, pronounced_entries


class HardeningTests(unittest.TestCase):
    def test_committed_corpus_matches_manifest_and_intersection(self):
        folder = Path(__file__).resolve().parents[1] / "data/curated"
        manifest = json.loads((folder / "manifest.json").read_text())
        for name, expected in manifest["outputs"].items():
            content = (folder / name).read_bytes()
            words = content.decode().splitlines()
            self.assertEqual(expected["sha256"], hashlib.sha256(content).hexdigest())
            self.assertEqual(expected["words"], len(words))
            self.assertEqual(sorted(set(words)), words)
        lexical = set((folder / "scowl-base-words.txt").read_text().splitlines())
        pronounced = set((folder / "cmu-pronounced-words.txt").read_text().splitlines())
        for length in range(3, 9):
            self.assertEqual({word for word in lexical & pronounced if len(word) == length},
                set((folder / f"words{length}.txt").read_text().splitlines()))

    def test_memory_concurrent_retry_returns_one_job(self):
        jobs = InMemoryJobRepository()
        def submit(_):
            return jobs.create(JobKind.GRAPH_BUILD, {"words": ["cat"], "partitions": 1}, idempotency_key="same")
        with ThreadPoolExecutor(max_workers=4) as pool:
            ids = {job.job_id for job in pool.map(submit, range(8))}
        self.assertEqual(1, len(ids))
        with self.assertRaises(IdempotencyConflict):
            jobs.create(JobKind.GRAPH_BUILD, {"words": ["dog"], "partitions": 1}, idempotency_key="same")

    def test_sqlite_idempotency_is_persistent_and_atomic(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "jobs.db"
            jobs = SQLiteJobRepository(path)
            parent = jobs.create_partitioned_build(["cat", "bat"], 2, idempotency_key="a")
            reopened = SQLiteJobRepository(path)
            replay = reopened.create_partitioned_build([" BAT ", "cat", "cat"], 2, idempotency_key="a")
            self.assertEqual(parent.job_id, replay.job_id)
            with jobs._connection() as connection:
                self.assertEqual(3, connection.execute("SELECT count(*) FROM jobs").fetchone()[0])
            with self.assertRaises(IdempotencyConflict):
                reopened.create_partitioned_build(["cat"], 2, idempotency_key="a")

    def test_http_idempotency_replay_conflict_and_validation(self):
        client = TestClient(create_app())
        body = {"words": ["cat"], "partitions": 1}
        url = "/v1/jobs/graph-builds"
        first = client.post(url, json=body, headers={"Idempotency-Key": "test"})
        second = client.post(url, json=body, headers={"Idempotency-Key": "test"})
        self.assertEqual(first.json()["job_id"], second.json()["job_id"])
        self.assertEqual(409, client.post(url, json={"words": ["dog"]}, headers={"Idempotency-Key": "test"}).status_code)
        self.assertEqual(422, client.post(url, json=body, headers={"Idempotency-Key": "has spaces"}).status_code)

    def test_local_renewal_rejects_expired_and_preserves_attempt(self):
        with TemporaryDirectory() as folder:
            for kind in ("memory", "sqlite"):
                now = [datetime.now(timezone.utc)]
                jobs = (InMemoryJobRepository(clock=lambda: now[0]) if kind == "memory" else
                        SQLiteJobRepository(Path(folder) / "jobs.db", clock=lambda: now[0]))
                job = jobs.create(JobKind.GRAPH_BUILD, {"words": ["cat"], "partitions": 1})
                claim = jobs.claim_next("a", 3)
                now[0] += timedelta(seconds=2)
                jobs.renew(claim, 3)
                now[0] += timedelta(seconds=2)
                self.assertIsNone(jobs.claim_next("b"))
                now[0] += timedelta(seconds=2)
                with self.assertRaises(InvalidJobTransition):
                    jobs.renew(claim, 3)
                self.assertEqual(1, jobs.get(job.job_id).attempts)

    def test_slow_worker_renews_and_finishes(self):
        jobs, graphs = InMemoryJobRepository(), InMemoryGraphRepository()
        job = jobs.create(JobKind.GRAPH_BUILD, {"words": ["cat"], "partitions": 1})
        worker = GraphWordWorker(jobs, graphs)
        def slow(_):
            time.sleep(1.6)
            return {"cat": set()}
        with patch.object(worker, "_build", side_effect=slow), patch.object(jobs, "renew", wraps=jobs.renew) as renew:
            worker.run_once("slow", lease_seconds=1)
            self.assertGreaterEqual(renew.call_count, 2)
        self.assertEqual(JobStatus.SUCCEEDED, jobs.get(job.job_id).status)

    def test_heartbeat_failure_cannot_publish_success(self):
        jobs, graphs = InMemoryJobRepository(), InMemoryGraphRepository()
        job = jobs.create(JobKind.GRAPH_BUILD, {"words": ["cat"], "partitions": 1})
        worker = GraphWordWorker(jobs, graphs)
        def slow(_):
            time.sleep(0.6)
            return {"cat": set()}
        with patch.object(worker, "_build", side_effect=slow), patch.object(jobs, "renew", side_effect=RuntimeError("network")):
            worker.run_once("slow", lease_seconds=1)
        self.assertIsNone(jobs.get(job.job_id).result)
        self.assertEqual(JobStatus.RUNNING, jobs.get(job.job_id).status)

    def test_dictionary_filters_do_not_invent_pronunciation(self):
        self.assertEqual({"cat"}, lexical_entries("4\ncat/S\nAlice\nbad/!\na-b\n", "!"))
        self.assertEqual({"cat"}, pronounced_entries("cat K AE1 T\ncat(2) K AE0 T\nxyz X Y Z\n", {"K", "AE1", "AE0", "T"}))
