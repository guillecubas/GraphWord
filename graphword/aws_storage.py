"""AWS adapters. DynamoDB is authoritative; SQS messages are disposable hints.

A periodic reconciler republishes pending/expired jobs. This deliberately simple
outbox-by-reconciliation closes the DynamoDB/SQS crash window without claiming
exactly-once delivery. Full scans are suitable for a small teaching lab, not an
unbounded production table.
"""

from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal
import json
import logging
from threading import RLock
from uuid import UUID, uuid4

from botocore.exceptions import ClientError

from graphword.graph import normalize_words
from graphword.jobs import (
    ClaimedJob, InvalidJobTransition, Job, JobKind, JobNotFoundError,
    JobStatus, utc_now,
)
from graphword.storage import GraphNotFoundError
from graphword.submissions import submission_identity, require_same_request

LOG = logging.getLogger(__name__)


def plain_json(value):
    """Keep the repository contract independent of DynamoDB's Decimal wrapper."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {key: plain_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [plain_json(item) for item in value]
    return value


class S3GraphRepository:
    def __init__(self, client, bucket):
        self.client, self.bucket = client, bucket

    def put_json(self, key, value):
        self.client.put_object(
            Bucket=self.bucket, Key=key,
            Body=json.dumps(value, sort_keys=True).encode(),
            ContentType="application/json", ServerSideEncryption="AES256",
        )

    def get_json(self, key):
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        with response["Body"] as body:
            return json.loads(body.read())

    def save(self, graph):
        graph_id = uuid4()
        self.put_json(f"graphs/{graph_id}.json", {
            word: sorted(neighbors) for word, neighbors in graph.items()
        })
        return graph_id

    def get(self, graph_id):
        try:
            return {word: set(neighbors) for word, neighbors in
                    self.get_json(f"graphs/{graph_id}.json").items()}
        except ClientError as error:
            if error.response["Error"]["Code"] in ("NoSuchKey", "404"):
                raise GraphNotFoundError(str(graph_id)) from error
            raise


class AWSJobRepository:
    def __init__(self, table, sqs, queue_url, objects, *, clock=utc_now, wait_seconds=10):
        self.table, self.sqs, self.queue_url = table, sqs, queue_url
        self.objects, self.clock, self.wait_seconds = objects, clock, wait_seconds
        self.receipts = {}
        self.table_lock = RLock()

    def _table_call(self, method, **kwargs):
        # boto3 resources are not thread-safe; serialize the heartbeat and reads.
        with self.table_lock:
            return getattr(self.table, method)(**kwargs)

    def _new(self, kind, payload, max_attempts=3, job_id=None, dependencies=None):
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        now = self.clock().isoformat()
        return dict(job_id=str(job_id or uuid4()), kind=str(kind), status="PENDING",
                    attempts=0, max_attempts=max_attempts, payload=payload,
                    result=None, error=None, created_at=now, updated_at=now,
                    revision=0, dependencies=dependencies or [])

    @staticmethod
    def _snapshot(record):
        return Job(UUID(record["job_id"]), JobKind(record["kind"]),
                   JobStatus(record["status"]), int(record["attempts"]),
                   int(record["max_attempts"]), plain_json(record.get("result")),
                   record.get("error"), datetime.fromisoformat(record["created_at"]),
                   datetime.fromisoformat(record["updated_at"]))

    def _read(self, job_id):
        item = self._table_call("get_item", Key={"job_id": str(job_id)}, ConsistentRead=True).get("Item")
        if item is None:
            raise JobNotFoundError(str(job_id))
        return item

    def get(self, job_id):
        return self._snapshot(self._read(job_id))

    def _replace(self, old, new):
        new = deepcopy(new)
        new["revision"] = old["revision"] + 1
        new["updated_at"] = self.clock().isoformat()
        try:
            self._table_call("put_item", Item=new, ConditionExpression="revision = :r",
                                ExpressionAttributeValues={":r": old["revision"]})
        except ClientError as error:
            if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise InvalidJobTransition("concurrent or stale claim") from error
            raise
        return new

    def _payload(self, payload):
        payload = deepcopy(dict(payload))
        if "words" in payload:
            words = normalize_words(payload.pop("words"))
            if not words:
                raise ValueError("no valid words supplied")
            key = f"inputs/{uuid4()}.json"
            self.objects.put_json(key, words)
            payload["words_key"] = key
        return payload

    def _replay(self, stable_id, request_hash):
        if stable_id is None:
            return None
        try:
            record = self._read(stable_id)
        except JobNotFoundError:
            return None
        require_same_request(record.get("request_hash"), request_hash)
        return self._snapshot(record)

    def create(self, kind, payload, max_attempts=3, *, idempotency_key=None):
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        stable_id, request_hash = submission_identity(kind, payload, max_attempts, idempotency_key)
        existing = self._replay(stable_id, request_hash)
        if existing:
            return existing
        record = self._new(kind, self._payload(payload), max_attempts, job_id=stable_id)
        record["request_hash"] = request_hash
        try:
            self._table_call("put_item", Item=record, ConditionExpression="attribute_not_exists(job_id)")
        except ClientError as error:
            if error.response["Error"]["Code"] == "ConditionalCheckFailedException" and stable_id:
                existing = self._replay(stable_id, request_hash)
                if existing:
                    return existing
            raise
        # Do not require SQS to be available at submission: reconciler will send.
        return self._snapshot(record)

    def create_partitioned_build(self, words, partitions, *, idempotency_key=None):
        if not 1 <= partitions <= 64:
            raise ValueError("partitions must be between 1 and 64")
        stable_id, request_hash = submission_identity(JobKind.REDUCE_GRAPH,
            {"words": words, "partitions": partitions}, 3, idempotency_key)
        existing = self._replay(stable_id, request_hash)
        if existing:
            return existing
        payload = self._payload({"words": words})
        children = [self._new(JobKind.BUILD_PARTITION, dict(
            payload, partition=index, partitions=partitions)) for index in range(partitions)]
        ids = [child["job_id"] for child in children]
        parent = self._new(JobKind.REDUCE_GRAPH, {"partition_jobs": ids}, dependencies=ids, job_id=stable_id)
        parent["request_hash"] = request_hash
        # Resource client has boto3's DynamoDB native-type serializer attached.
        try:
            with self.table_lock:
                self.table.meta.client.transact_write_items(TransactItems=[{
                    "Put": {"TableName": self.table.name, "Item": record,
                            "ConditionExpression": "attribute_not_exists(job_id)"}
                } for record in [parent, *children]])
        except ClientError as error:
            if error.response["Error"]["Code"] == "TransactionCanceledException" and stable_id:
                existing = self._replay(stable_id, request_hash)
                if existing:
                    return existing
            raise
        return self._snapshot(parent)

    def _ready(self, record):
        return all(self.get(UUID(child)).status == JobStatus.SUCCEEDED
                   for child in record["dependencies"])

    def reconcile(self):
        """Run periodically even with an empty SQS queue. Safe with multiple callers."""
        request = {"ConsistentRead": True}
        sent = 0
        while True:
            page = self._table_call("scan", **request)
            for old in page["Items"]:
                try:
                    record = old
                    if record["status"] == "RUNNING" and record["lease"] <= int(self.clock().timestamp()):
                        new = dict(record, status=("FAILED" if record["attempts"] >= record["max_attempts"]
                                                  else "PENDING"), error="worker lease expired")
                        record = self._replace(record, new)
                    if record["status"] != "PENDING":
                        continue
                    deps = [self.get(UUID(child)).status for child in record["dependencies"]]
                    if JobStatus.FAILED in deps:
                        self._replace(record, dict(record, status="FAILED", error="partition failed"))
                    elif all(state == JobStatus.SUCCEEDED for state in deps):
                        self.sqs.send_message(QueueUrl=self.queue_url, MessageBody=record["job_id"])
                        sent += 1
                except InvalidJobTransition:
                    continue
            if "LastEvaluatedKey" not in page:
                return sent
            request["ExclusiveStartKey"] = page["LastEvaluatedKey"]

    def _delete(self, receipt):
        self.sqs.delete_message(QueueUrl=self.queue_url, ReceiptHandle=receipt)

    def claim_next(self, worker_id, lease_seconds=30):
        if not worker_id.strip() or not 1 <= lease_seconds <= 43200:
            raise ValueError("worker required; lease must be 1..43200 seconds")
        messages = self.sqs.receive_message(
            QueueUrl=self.queue_url, MaxNumberOfMessages=1,
            WaitTimeSeconds=self.wait_seconds, VisibilityTimeout=lease_seconds,
        ).get("Messages", [])
        for message in messages:
            try:
                job_id = UUID(message["Body"])
            except ValueError:
                # Leave malformed messages to SQS redrive/DLQ; never execute a body.
                LOG.warning("Malformed queue message; awaiting redrive")
                continue
            try:
                old = self._read(job_id)
            except JobNotFoundError:
                self._delete(message["ReceiptHandle"])
                continue
            if old["status"] in ("SUCCEEDED", "FAILED"):
                self._delete(message["ReceiptHandle"])
                continue
            if old["status"] != "PENDING" or not self._ready(old):
                continue
            token, now = uuid4(), self.clock()
            expiry = now + timedelta(seconds=lease_seconds)
            new = dict(old, status="RUNNING", attempts=old["attempts"] + 1,
                       token=str(token), worker=worker_id, lease=int(expiry.timestamp()), error=None)
            try:
                record = self._replace(old, new)
            except InvalidJobTransition:
                continue
            self.receipts[str(token)] = message["ReceiptHandle"]
            payload = deepcopy(record["payload"])
            for field in ("partition", "partitions"):
                if field in payload:
                    payload[field] = int(payload[field])
            try:
                if "words_key" in payload:
                    payload["words"] = self.objects.get_json(payload.pop("words_key"))
            except Exception:
                self.receipts.pop(str(token), None)
                # Durable RUNNING lease expires; reconciler recovers the job.
                raise
            return ClaimedJob(job_id, JobKind(record["kind"]), payload, worker_id,
                              int(record["attempts"]), token, expiry)
        return None

    def renew(self, claim, lease_seconds):
        if not 1 <= lease_seconds <= 43200:
            raise ValueError("lease must be 1..43200 seconds")
        old = self._read(claim.job_id)
        now = self.clock()
        if (old["status"] != "RUNNING" or old.get("token") != str(claim.attempt_token)
                or old.get("worker") != claim.worker_id or old["lease"] <= int(now.timestamp())):
            raise InvalidJobTransition("cannot renew a stale claim")
        receipt = self.receipts.get(str(claim.attempt_token))
        if not receipt:
            raise InvalidJobTransition("missing receipt for active claim")
        self.sqs.change_message_visibility(QueueUrl=self.queue_url, ReceiptHandle=receipt,
                                           VisibilityTimeout=lease_seconds)
        self._replace(old, dict(old, lease=int((now + timedelta(seconds=lease_seconds)).timestamp())))

    def _finish(self, claim, result=None, error=None, retryable=False):
        old = self._read(claim.job_id)
        if (old["status"] != "RUNNING" or old.get("token") != str(claim.attempt_token)
                or old.get("worker") != claim.worker_id
                or old["lease"] <= int(self.clock().timestamp())):
            self.receipts.pop(str(claim.attempt_token), None)
            raise InvalidJobTransition("claim is stale or expired")
        status = ("SUCCEEDED" if error is None else
                  "PENDING" if retryable and old["attempts"] < old["max_attempts"] else "FAILED")
        new = self._replace(old, dict(old, status=status, result=result, error=error))
        receipt = self.receipts.pop(str(claim.attempt_token), None)
        if receipt:
            try:
                self._delete(receipt)
            except ClientError:
                # Durable outcome is committed; a duplicate will only be acknowledged.
                LOG.warning("Result committed; SQS acknowledgement failed", exc_info=True)
        return self._snapshot(new)

    def complete(self, claim, result):
        return self._finish(claim, result=dict(result))

    def fail(self, claim, error, retryable=True):
        return self._finish(claim, error=error, retryable=retryable)
