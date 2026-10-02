"""AWS contract tests with Moto; these do not constitute a real AWS deployment."""
from datetime import datetime, timedelta, timezone
import json
import unittest
from unittest.mock import patch
from uuid import uuid4

try:
    import boto3
    from moto import mock_aws
except ImportError:
    boto3 = None
    mock_aws = lambda: (lambda cls: cls)

from graphword.graph import build_partition
from graphword.jobs import InvalidJobTransition, JobKind, JobStatus
from graphword.worker import GraphWordWorker


@unittest.skipIf(boto3 is None, "install .[aws,aws-test]")
@mock_aws()
class AWSStorageTests(unittest.TestCase):
    def setUp(self):
        from graphword.aws_storage import AWSJobRepository, S3GraphRepository
        session = boto3.Session(region_name="us-east-1")
        s3 = session.client("s3")
        s3.create_bucket(Bucket="graphword-tests")
        self.graphs = S3GraphRepository(s3, "graphword-tests")
        self.table = session.resource("dynamodb").create_table(
            TableName="jobs", BillingMode="PAY_PER_REQUEST",
            KeySchema=[{"AttributeName": "job_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "job_id", "AttributeType": "S"}],
        )
        self.sqs = session.client("sqs")
        self.url = self.sqs.create_queue(QueueName="jobs")["QueueUrl"]
        self.now = datetime.now(timezone.utc)
        self.jobs = AWSJobRepository(self.table, self.sqs, self.url, self.graphs,
                                     clock=lambda: self.now, wait_seconds=0)
        self.worker = GraphWordWorker(self.jobs, self.graphs)

    def drain(self, count=30):
        for _ in range(count):
            self.jobs.reconcile()
            self.worker.run_once("test-worker")

    def test_s3_round_trip_and_missing(self):
        from graphword.storage import GraphNotFoundError
        graph = build_partition(["cat", "bat", "zzz"])
        self.assertEqual(graph, self.graphs.get(self.graphs.save(graph)))
        with self.assertRaises(GraphNotFoundError):
            self.graphs.get(uuid4())

    def test_aws_renewal_extends_claim_and_rejects_stale(self):
        self.jobs.create(JobKind.GRAPH_BUILD, {"words": ["cat"], "partitions": 1})
        self.jobs.reconcile()
        claim = self.jobs.claim_next("one", 10)
        self.now += timedelta(seconds=6)
        self.jobs.renew(claim, 10)
        self.now += timedelta(seconds=6)
        self.jobs.reconcile()
        self.assertEqual(JobStatus.RUNNING, self.jobs.get(claim.job_id).status)
        self.jobs.complete(claim, {"graph_id": "confirmed"})
        with self.assertRaises(InvalidJobTransition):
            self.jobs.renew(claim, 10)

    def test_aws_idempotency_single_and_partitioned(self):
        from graphword.submissions import IdempotencyConflict
        job = self.jobs.create(JobKind.GRAPH_BUILD, {"words": ["cat"], "partitions": 1}, idempotency_key="one")
        self.assertEqual(job.job_id, self.jobs.create(JobKind.GRAPH_BUILD,
            {"words": ["cat"], "partitions": 1}, idempotency_key="one").job_id)
        parent = self.jobs.create_partitioned_build(["cat", "bat"], 2, idempotency_key="two")
        replay = self.jobs.create_partitioned_build(["bat", "cat"], 2, idempotency_key="two")
        self.assertEqual(parent.job_id, replay.job_id)
        self.assertEqual(4, self.table.scan()["Count"])
        with self.assertRaises(IdempotencyConflict):
            self.jobs.create_partitioned_build(["dog"], 2, idempotency_key="two")

    def test_partitioned_build_matches_oracle(self):
        words = ["cat", "bat", "bad", "dad", "zzz"]
        parent = self.jobs.create_partitioned_build(words, 3)
        self.assertEqual(4, self.table.scan()["Count"])
        self.assertFalse(self.jobs._ready(self.jobs._read(parent.job_id)))
        self.drain()
        result = self.jobs.get(parent.job_id)
        self.assertEqual(JobStatus.SUCCEEDED, result.status)
        self.assertEqual(build_partition(words), self.graphs.get(result.result["graph_id"]))
        for child in self.jobs._read(parent.job_id)["dependencies"]:
            json.dumps(self.jobs.get(child).result)

    def test_optimistic_lock_rejects_concurrent_replacement(self):
        job = self.jobs.create(JobKind.GRAPH_BUILD, {"words": ["cat"], "partitions": 1})
        first = self.jobs._read(job.job_id)
        second = self.jobs._read(job.job_id)
        self.jobs._replace(first, dict(first, status="RUNNING"))
        with self.assertRaises(InvalidJobTransition):
            self.jobs._replace(second, dict(second, status="RUNNING"))

    def test_partition_transaction_leaves_no_partial_jobs(self):
        from botocore.exceptions import ClientError
        with patch.object(self.table.meta.client, "transact_write_items", side_effect=ClientError(
                {"Error": {"Code": "TransactionCanceledException", "Message": "test"}}, "TransactWriteItems")):
            with self.assertRaises(ClientError):
                self.jobs.create_partitioned_build(["cat", "bat"], 2)
        self.assertEqual(0, self.table.scan()["Count"])

    def test_submission_survives_sqs_outage(self):
        with patch.object(self.sqs, "send_message", side_effect=RuntimeError("offline")):
            job = self.jobs.create(JobKind.GRAPH_BUILD, {"words": ["cat"], "partitions": 1})
            with self.assertRaises(RuntimeError):
                self.jobs.reconcile()
        self.drain(2)
        self.assertEqual(JobStatus.SUCCEEDED, self.jobs.get(job.job_id).status)

    def test_duplicate_and_stale_claim(self):
        job = self.jobs.create(JobKind.GRAPH_BUILD, {"words": ["cat"], "partitions": 1})
        self.jobs.reconcile()
        first = self.jobs.claim_next("one", 10)
        self.sqs.send_message(QueueUrl=self.url, MessageBody=str(job.job_id))
        self.assertIsNone(self.jobs.claim_next("two", 10))
        self.now += timedelta(seconds=11)
        self.jobs.reconcile()
        second = self.jobs.claim_next("two", 10)
        self.assertIsNotNone(second)
        with self.assertRaises(InvalidJobTransition):
            self.jobs.complete(first, {"graph_id": "stale"})
        self.jobs.complete(second, {"graph_id": "confirmed"})
        self.assertEqual("confirmed", self.jobs.get(job.job_id).result["graph_id"])
        self.jobs.reconcile()
        self.assertEqual(2, self.jobs.get(job.job_id).attempts)

    def test_expired_last_attempt_and_parent_failure(self):
        parent = self.jobs.create_partitioned_build(["cat"], 1)
        self.jobs.reconcile()
        claim = self.jobs.claim_next("one", 5)
        self.jobs.fail(claim, "invalid", retryable=False)
        self.jobs.reconcile()
        self.assertEqual(JobStatus.FAILED, self.jobs.get(parent.job_id).status)
        job = self.jobs.create(JobKind.GRAPH_BUILD, {"words": ["cat"], "partitions": 1}, max_attempts=1)
        self.jobs.reconcile()
        self.assertIsNotNone(self.jobs.claim_next("one", 5))
        self.now += timedelta(seconds=6)
        self.jobs.reconcile()
        self.assertEqual(JobStatus.FAILED, self.jobs.get(job.job_id).status)

    def test_failure_retry_limit(self):
        job = self.jobs.create(JobKind.GRAPH_BUILD, {"words": ["cat"], "partitions": 1}, max_attempts=2)
        for _ in range(2):
            self.jobs.reconcile()
            claim = self.jobs.claim_next("one")
            self.jobs.fail(claim, "bad input")
        self.assertEqual(JobStatus.FAILED, self.jobs.get(job.job_id).status)

    def test_failed_ack_does_not_undo_success(self):
        from botocore.exceptions import ClientError
        job = self.jobs.create(JobKind.GRAPH_BUILD, {"words": ["cat"], "partitions": 1})
        self.jobs.reconcile()
        claim = self.jobs.claim_next("one")
        with patch.object(self.sqs, "delete_message", side_effect=ClientError(
                {"Error": {"Code": "InternalError", "Message": "test"}}, "DeleteMessage")):
            with self.assertLogs("graphword.aws_storage", level="WARNING"):
                self.jobs.complete(claim, {"graph_id": "done"})
        self.assertEqual(JobStatus.SUCCEEDED, self.jobs.get(job.job_id).status)

    def test_empty_dictionary_does_not_create_jobs(self):
        with self.assertRaises(ValueError):
            self.jobs.create_partitioned_build(["123"], 2)
        self.assertEqual(0, self.table.scan()["Count"])

    def test_http_with_shared_cloud_repositories(self):
        from fastapi.testclient import TestClient
        from graphword.api import create_app
        client = TestClient(create_app(self.graphs, self.jobs, partitioned_builds=self.jobs))
        response = client.post("/v1/jobs/partitioned-builds", json={"words": ["cat", "bat"], "partitions": 2})
        self.assertEqual(202, response.status_code)
        self.drain()
        result = client.get(response.headers["location"]).json()
        self.assertEqual("SUCCEEDED", result["status"])
        graph = client.get("/v1/graphs/" + result["result"]["graph_id"]).json()
        self.assertEqual(1, graph["edges"])
