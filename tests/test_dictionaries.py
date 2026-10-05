"""Catalogue integrity and HTTP -> S3 -> jobs -> worker end-to-end contracts."""
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import UUID

from fastapi.testclient import TestClient
from graphword.api.routes import create_app
from graphword.almacenamiento.dictionaries import publish_dictionaries
from graphword.motor.graph import build_partition
from graphword.trabajos.jobs import JobStatus
from graphword.trabajos.worker import GraphWordWorker

try:
    import boto3
    from moto import mock_aws
except ImportError:
    boto3 = None
    # Sin Moto, conservar el decorador; skipIf omitirá las pruebas AWS.
    def mock_aws():
        def unchanged_class(cls):
            return cls
        return unchanged_class

ROOT = Path(__file__).resolve().parents[1]


class DictionaryConfigurationTests(unittest.TestCase):
    def test_catalogue_routes_are_unavailable_without_configuration(self):
        client = TestClient(create_app())
        self.assertEqual(503, client.get("/v1/dictionaries").status_code)
        self.assertEqual(503, client.post("/v1/jobs/dictionary-builds",
            json={"dictionary_id": "words3"}).status_code)


@unittest.skipIf(boto3 is None, "install .[aws,aws-test]")
@mock_aws()
class DictionaryAWSContractTests(unittest.TestCase):
    def setUp(self):
        from graphword.almacenamiento.aws_storage import S3GraphRepository, AWSJobRepository, S3DictionaryRepository
        session = boto3.Session(region_name="us-east-1")
        self.s3 = session.client("s3")
        self.bucket = "graphword-dictionaries-tests"
        self.s3.create_bucket(Bucket=self.bucket)
        self.key = publish_dictionaries(self.s3, self.bucket, ROOT / "data/curated")
        self.catalogue = S3DictionaryRepository(self.s3, self.bucket, self.key)
        self.graphs = S3GraphRepository(self.s3, self.bucket)
        self.table = session.resource("dynamodb").create_table(TableName="jobs",
            BillingMode="PAY_PER_REQUEST", KeySchema=[{"AttributeName": "job_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "job_id", "AttributeType": "S"}])
        sqs = session.client("sqs")
        queue = sqs.create_queue(QueueName="jobs")["QueueUrl"]
        self.jobs = AWSJobRepository(self.table, sqs, queue, self.graphs, wait_seconds=0)
        self.client = TestClient(create_app(self.graphs, self.jobs, partitioned_builds=self.jobs,
            dictionary_repository=self.catalogue))

    def test_catalogue_and_source_notices_are_published(self):
        response = self.client.get("/v1/dictionaries")
        self.assertEqual(200, response.status_code)
        expected_ids = []
        for length in range(3, 9):
            expected_ids.append(f"words{length}")
        actual_ids = []
        for item in response.json():
            actual_ids.append(item["dictionary_id"])
        self.assertEqual(expected_ids, actual_ids)
        self.assertEqual(628, response.json()[0]["word_count"])
        prefix = self.key.removesuffix("catalog.json")
        for name in ("cmu-LICENSE", "scowl-README_en_US.txt"):
            self.assertEqual((ROOT / "data/curated/licenses" / name).read_bytes(),
                self.s3.get_object(Bucket=self.bucket, Key=prefix + "licenses/" + name)["Body"].read())

    def test_dictionary_build_uses_s3_and_reports_provenance(self):
        body = {"dictionary_id": "words3", "partitions": 3}
        headers = {"Idempotency-Key": "dictionary-test"}
        response = self.client.post("/v1/jobs/dictionary-builds", json=body, headers=headers)
        self.assertEqual(202, response.status_code)
        job_id = response.json()["job_id"]
        replay = self.client.post("/v1/jobs/dictionary-builds", json=body, headers=headers)
        self.assertEqual(job_id, replay.json()["job_id"])
        self.assertEqual(4, self.table.scan()["Count"])
        worker = GraphWordWorker(self.jobs, self.graphs)
        for _ in range(20):
            self.jobs.reconcile()
            worker.run_once("dictionary-worker")
            if self.jobs.get(UUID(job_id)).status is JobStatus.SUCCEEDED:
                break
        result = self.client.get("/v1/jobs/" + job_id).json()
        self.assertEqual("SUCCEEDED", result["status"])
        self.assertEqual("words3", result["result"]["source"]["dictionary_id"])
        info, words = self.catalogue.load("words3")
        self.assertEqual(asdict(info), result["result"]["source"])
        graph = self.graphs.get(UUID(result["result"]["graph_id"]))
        self.assertEqual(build_partition(words), graph)
        self.assertEqual(628, len(graph))
        self.assertEqual(200, self.client.post(f"/v1/graphs/{result['result']['graph_id']}/queries/shortest-path",
            json={"start": "cat", "end": "dad"}).status_code)
        conflict = self.client.post("/v1/jobs/dictionary-builds",
            json={"dictionary_id": "words4", "partitions": 3}, headers=headers)
        self.assertEqual(409, conflict.status_code)

    def test_selected_s3_content_is_used_instead_of_packaged_file(self):
        # A valid smaller S3 dictionary proves the API is not silently reading the local fixture.
        content = b"bat\ncat\ndad\n"
        catalogue = json.loads(self.s3.get_object(Bucket=self.bucket, Key=self.key)["Body"].read())
        item = catalogue["dictionaries"][0]
        item.update(sha256=sha256(content).hexdigest(), word_count=3)
        self.s3.put_object(Bucket=self.bucket, Key=item["s3_key"], Body=content)
        self.s3.put_object(Bucket=self.bucket, Key=self.key, Body=json.dumps(catalogue))
        _, words = self.catalogue.load("words3")
        self.assertEqual(["bat", "cat", "dad"], words)

    def test_unknown_id_and_arbitrary_paths_do_not_create_jobs(self):
        for dictionary_id in ("missing", "../inputs/private.json", "s3://other-bucket/file"):
            response = self.client.post("/v1/jobs/dictionary-builds", json={"dictionary_id": dictionary_id})
            self.assertEqual(404, response.status_code)
        self.assertEqual(0, self.table.scan()["Count"])

    def test_checksum_failure_does_not_create_jobs(self):
        info = self.catalogue.list()[0]
        self.s3.put_object(Bucket=self.bucket, Key=info.s3_key, Body=b"wrong\n")
        response = self.client.post("/v1/jobs/dictionary-builds", json={"dictionary_id": "words3"})
        self.assertEqual(422, response.status_code)
        self.assertEqual("invalid_dictionary", response.json()["detail"]["code"])
        self.assertEqual(0, self.table.scan()["Count"])

    def test_missing_catalogue_reports_unavailable(self):
        self.s3.delete_object(Bucket=self.bucket, Key=self.key)
        self.assertEqual(503, self.client.get("/v1/dictionaries").status_code)

    def test_publication_rejects_bad_corpus_before_uploading(self):
        with TemporaryDirectory() as folder:
            directory = Path(folder)
            (directory / "manifest.json").write_bytes((ROOT / "data/curated/manifest.json").read_bytes())
            (directory / "words3.txt").write_bytes(b"bad\n")
            with patch.object(self.s3, "put_object") as put:
                with self.assertRaises(ValueError):
                    publish_dictionaries(self.s3, self.bucket, directory)
                put.assert_not_called()

    def test_sqlite_reducer_also_preserves_source_and_idempotency(self):
        from graphword.almacenamiento.sqlite_storage import SQLiteGraphRepository, SQLiteJobRepository
        with TemporaryDirectory() as folder:
            path = Path(folder) / "jobs.db"
            jobs = SQLiteJobRepository(path)
            graphs = SQLiteGraphRepository(path)
            source = {"dictionary_id": "small", "sha256": "a" * 64}
            job = jobs.create_partitioned_build(["cat", "bat"], 2, source=source, idempotency_key="a")
            self.assertEqual(job.job_id, jobs.create_partitioned_build(["bat", "cat"], 2,
                source=source, idempotency_key="a").job_id)
            worker = GraphWordWorker(jobs, graphs)
            for _ in range(3):
                worker.run_once("local")
            self.assertEqual(source, jobs.get(job.job_id).result["source"])
