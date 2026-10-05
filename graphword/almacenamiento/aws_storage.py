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
from hashlib import sha256
import re
from threading import RLock
from uuid import UUID, uuid4

from botocore.exceptions import ClientError

from graphword.motor.graph import normalize_words
from graphword.trabajos.jobs import (
    ClaimedJob, InvalidJobTransition, Job, JobKind, JobNotFoundError,
    JobStatus, utc_now,
)
from graphword.almacenamiento.storage import GraphNotFoundError
from graphword.trabajos.submissions import submission_identity, require_same_request
from graphword.almacenamiento.dictionaries import (
    DictionaryInfo,
    DictionaryNotFoundError,
    InvalidDictionaryError,
    DictionaryUnavailableError,
)

LOG = logging.getLogger(__name__)


class S3DictionaryRepository:
    """Read only the configured bucket/catalogue; callers select IDs, not URLs."""
    def __init__(self, client, bucket, catalog_key):
        self.client = client
        self.bucket = bucket
        self.catalog_key = catalog_key

    def _read(self, key, limit):
        try:
            # Limitar el tamaño leído evita cargar objetos enormes en la API.
            response = self.client.get_object(Bucket=self.bucket, Key=key)
            with response["Body"] as body:
                if response["ContentLength"] > limit:
                    raise InvalidDictionaryError("Dictionary object is too large")
                content = body.read(limit + 1)
            if len(content) > limit:
                raise InvalidDictionaryError("Dictionary object is too large")
            return content
        except InvalidDictionaryError:
            raise
        except Exception as error:
            raise DictionaryUnavailableError("Dictionary storage is unavailable") from error

    def list(self):
        content = self._read(self.catalog_key, 1024 * 1024)
        try:
            catalog = json.loads(content)
            if catalog["schema_version"] != 1:
                raise ValueError("unsupported catalogue")
            entries = []
            for item in catalog["dictionaries"]:
                # ** pasa los campos del catálogo al constructor y valida sus nombres.
                entries.append(DictionaryInfo(**item))
            duplicate_ids = False
            if len(entries) <= 100:
                dictionary_ids = set()
                for item in entries:
                    dictionary_ids.add(item.dictionary_id)
                duplicate_ids = len(dictionary_ids) != len(entries)
            if len(entries) > 100 or duplicate_ids:
                raise ValueError("invalid catalogue size or duplicate IDs")
            for item in entries:
                if (not re.fullmatch(r"words[3-8]", item.dictionary_id)
                        or item.word_length != int(item.dictionary_id[-1])
                        or not 1 <= item.word_count <= 100_000
                        or not re.fullmatch(r"[0-9a-f]{64}", item.sha256)
                        or not re.fullmatch(r"dictionaries/curated/[0-9a-f]{64}/words[3-8]\.txt", item.s3_key)
                        or not item.s3_key.endswith(item.dictionary_id + ".txt")):
                    raise ValueError("invalid catalogue entry")
            return entries
        except (KeyError, TypeError, ValueError, UnicodeError) as error:
            raise InvalidDictionaryError("Invalid dictionary catalogue") from error

    def load(self, dictionary_id):
        # Buscar solo dentro del catálogo configurado, nunca en una URL del usuario.
        info = None
        for item in self.list():
            if item.dictionary_id == dictionary_id:
                info = item
                break
        if info is None:
            raise DictionaryNotFoundError(dictionary_id)
        content = self._read(info.s3_key, 16 * 1024 * 1024)
        if sha256(content).hexdigest() != info.sha256:
            raise InvalidDictionaryError("Dictionary checksum does not match catalogue")
        try:
            words = content.decode("utf-8").splitlines()
        except UnicodeError as error:
            raise InvalidDictionaryError("Dictionary must be UTF-8") from error
        invalid_words = (
            len(words) != info.word_count or words != normalize_words(words)
        )
        if not invalid_words:
            for word in words:
                if len(word) != info.word_length:
                    invalid_words = True
                    break
        if invalid_words:
            raise InvalidDictionaryError("Dictionary words do not match catalogue")
        return info, words


def plain_json(value):
    """Keep the repository contract independent of DynamoDB's Decimal wrapper."""
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    if isinstance(value, dict):
        # Convertir también los valores de diccionarios anidados.
        converted = {}
        for key, item in value.items():
            converted[key] = plain_json(item)
        return converted
    if isinstance(value, list):
        converted = []
        for item in value:
            converted.append(plain_json(item))
        return converted
    return value


class S3GraphRepository:
    def __init__(self, client, bucket):
        self.client = client
        self.bucket = bucket

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
        # JSON no admite conjuntos; guardar los vecinos como listas ordenadas.
        adjacency = {}
        for word, neighbors in graph.items():
            adjacency[word] = sorted(neighbors)
        self.put_json(f"graphs/{graph_id}.json", adjacency)
        return graph_id

    def get(self, graph_id):
        try:
            adjacency = self.get_json(f"graphs/{graph_id}.json")
            graph = {}
            for word, neighbors in adjacency.items():
                graph[word] = set(neighbors)
            return graph
        except ClientError as error:
            if error.response["Error"]["Code"] in ("NoSuchKey", "404"):
                raise GraphNotFoundError(str(graph_id)) from error
            raise


class AWSJobRepository:
    def __init__(self, table, sqs, queue_url, objects, *, clock=utc_now, wait_seconds=10):
        self.table = table
        self.sqs = sqs
        self.queue_url = queue_url
        self.objects = objects
        self.clock = clock
        self.wait_seconds = wait_seconds
        self.receipts = {}
        self.table_lock = RLock()

    def _table_call(self, method, **kwargs):
        # El bloqueo impide usar el recurso boto3 desde dos hilos a la vez.
        with self.table_lock:
            # getattr elige la operación; **kwargs conserva sus argumentos AWS.
            operation = getattr(self.table, method)
            return operation(**kwargs)

    def _new(self, kind, payload, max_attempts=3, job_id=None, dependencies=None):
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        now = self.clock().isoformat()
        if not job_id:
            job_id = uuid4()
        if not dependencies:
            dependencies = []
        return {
            "job_id": str(job_id),
            "kind": str(kind),
            "status": "PENDING",
            "attempts": 0,
            "max_attempts": max_attempts,
            "payload": payload,
            "result": None,
            "error": None,
            "created_at": now,
            "updated_at": now,
            "revision": 0,
            "dependencies": dependencies,
        }

    @staticmethod
    def _snapshot(record):
        # Convertir el registro de DynamoDB al objeto que utiliza la aplicación.
        return Job(
            job_id=UUID(record["job_id"]),
            kind=JobKind(record["kind"]),
            status=JobStatus(record["status"]),
            attempts=int(record["attempts"]),
            max_attempts=int(record["max_attempts"]),
            result=plain_json(record.get("result")),
            error=record.get("error"),
            created_at=datetime.fromisoformat(record["created_at"]),
            updated_at=datetime.fromisoformat(record["updated_at"]),
        )

    def _read(self, job_id):
        response = self._table_call(
            "get_item",
            Key={"job_id": str(job_id)},
            ConsistentRead=True,
        )
        item = response.get("Item")
        if item is None:
            raise JobNotFoundError(str(job_id))
        return item

    def get(self, job_id):
        return self._snapshot(self._read(job_id))

    def _replace(self, old, new):
        new = deepcopy(new)
        # La condición de versión impide sobrescribir cambios de otro worker.
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

    def create_partitioned_build(self, words, partitions, *, idempotency_key=None, source=None):
        if not 1 <= partitions <= 64:
            raise ValueError("partitions must be between 1 and 64")
        identity = {"words": words, "partitions": partitions}
        if source is not None:
            identity["source"] = source
        stable_id, request_hash = submission_identity(JobKind.REDUCE_GRAPH,
            identity, 3, idempotency_key)
        existing = self._replay(stable_id, request_hash)
        if existing:
            return existing
        payload = self._payload({"words": words})
        # Crear una tarea por partición y reunir sus identificadores.
        children = []
        for index in range(partitions):
            child_payload = payload.copy()
            child_payload["partition"] = index
            child_payload["partitions"] = partitions
            children.append(self._new(JobKind.BUILD_PARTITION, child_payload))
        ids = []
        for child in children:
            ids.append(child["job_id"])
        parent = self._new(
            JobKind.REDUCE_GRAPH,
            {"partition_jobs": ids},
            dependencies=ids,
            job_id=stable_id,
        )
        if source is not None:
            parent["payload"]["source"] = deepcopy(source)
        parent["request_hash"] = request_hash
        # Resource client has boto3's DynamoDB native-type serializer attached.
        try:
            with self.table_lock:
                # La transacción guarda el padre y sus hijos: todos o ninguno.
                records = [parent]
                records.extend(children)
                transactions = []
                for record in records:
                    transactions.append({
                        "Put": {
                            "TableName": self.table.name,
                            "Item": record,
                            "ConditionExpression": "attribute_not_exists(job_id)",
                        }
                    })
                self.table.meta.client.transact_write_items(TransactItems=transactions)
        except ClientError as error:
            if error.response["Error"]["Code"] == "TransactionCanceledException" and stable_id:
                existing = self._replay(stable_id, request_hash)
                if existing:
                    return existing
            raise
        return self._snapshot(parent)

    def _ready(self, record):
        # Parar en el primer hijo pendiente conserva la comprobación original.
        for child in record["dependencies"]:
            if self.get(UUID(child)).status != JobStatus.SUCCEEDED:
                return False
        return True

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
                        # Una reserva caducada se reintenta solo si quedan intentos.
                        new = record.copy()
                        if record["attempts"] >= record["max_attempts"]:
                            new["status"] = "FAILED"
                        else:
                            new["status"] = "PENDING"
                        new["error"] = "worker lease expired"
                        record = self._replace(record, new)
                    if record["status"] != "PENDING":
                        continue
                    deps = []
                    for child in record["dependencies"]:
                        deps.append(self.get(UUID(child)).status)
                    if JobStatus.FAILED in deps:
                        new = record.copy()
                        new["status"] = "FAILED"
                        new["error"] = "partition failed"
                        self._replace(record, new)
                    else:
                        all_succeeded = True
                        for state in deps:
                            if state != JobStatus.SUCCEEDED:
                                all_succeeded = False
                                break
                        if all_succeeded:
                            # SQS solo avisa; el estado definitivo está en DynamoDB.
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
            token = uuid4()
            now = self.clock()
            expiry = now + timedelta(seconds=lease_seconds)
            # Reservar este intento con un token exclusivo y una fecha de caducidad.
            new = old.copy()
            new["status"] = "RUNNING"
            new["attempts"] = old["attempts"] + 1
            new["token"] = str(token)
            new["worker"] = worker_id
            new["lease"] = int(expiry.timestamp())
            new["error"] = None
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
        new = old.copy()
        expiry = now + timedelta(seconds=lease_seconds)
        new["lease"] = int(expiry.timestamp())
        self._replace(old, new)

    def _finish(self, claim, result=None, error=None, retryable=False):
        old = self._read(claim.job_id)
        if (old["status"] != "RUNNING" or old.get("token") != str(claim.attempt_token)
                or old.get("worker") != claim.worker_id
                or old["lease"] <= int(self.clock().timestamp())):
            self.receipts.pop(str(claim.attempt_token), None)
            raise InvalidJobTransition("claim is stale or expired")
        # Distinguir éxito, fallo temporal y fallo definitivo.
        if error is None:
            status = "SUCCEEDED"
        elif retryable and old["attempts"] < old["max_attempts"]:
            status = "PENDING"
        else:
            status = "FAILED"
        updated = old.copy()
        updated["status"] = status
        updated["result"] = result
        updated["error"] = error
        new = self._replace(old, updated)
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
