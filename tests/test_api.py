import unittest
from uuid import UUID

from fastapi.testclient import TestClient

from graphword.api import create_app
from graphword.jobs import InMemoryJobRepository
from graphword.storage import InMemoryGraphRepository
from graphword.worker import GraphWordWorker


GRAPH_ID = UUID("00000000-0000-0000-0000-000000000001")
JOB_ID = UUID("00000000-0000-0000-0000-000000000002")


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.graphs = InMemoryGraphRepository(id_factory=lambda: GRAPH_ID)
        self.jobs = InMemoryJobRepository(id_factory=lambda: JOB_ID)
        self.client = TestClient(create_app(self.graphs, self.jobs))

    def test_health_discloses_local_storage(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "status": "ok",
            "storage": "in-memory-local",
        })
        self.assertEqual(self.client.get("/openapi.json").json()["info"]["version"], "0.4.0")

    def test_create_and_read_graph(self):
        response = self.client.post("/v1/graphs", json={
            "words": ["cat", "bat", "bad", "dad", "dog"],
            "partitions": 3,
        })
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.headers["location"], f"/v1/graphs/{GRAPH_ID}")
        self.assertEqual(response.json(), {
            "graph_id": str(GRAPH_ID),
            "nodes": 5,
            "edges": 3,
            "components": 2,
            "isolated": ["dog"],
            "max_degree": 2,
            "highest_degree_nodes": ["bad", "bat"],
        })
        self.assertEqual(
            self.client.get(f"/v1/graphs/{GRAPH_ID}").json(),
            response.json(),
        )

    def test_graph_build_job_returns_202_and_worker_publishes_graph(self):
        submitted = self.client.post("/v1/jobs/graph-builds", json={
            "words": ["cat", "bat", "bad", "dad"],
            "partitions": 2,
        })
        self.assertEqual(submitted.status_code, 202)
        self.assertEqual(submitted.headers["location"], f"/v1/jobs/{JOB_ID}")
        self.assertEqual(submitted.json()["status"], "PENDING")
        self.assertEqual(submitted.json()["attempts"], 0)
        self.assertIsNone(submitted.json()["result"])

        worker = GraphWordWorker(self.jobs, self.graphs)
        self.assertTrue(worker.run_once("worker-a"))
        completed = self.client.get(f"/v1/jobs/{JOB_ID}")
        self.assertEqual(completed.status_code, 200)
        self.assertEqual(completed.json()["status"], "SUCCEEDED")
        self.assertEqual(completed.json()["attempts"], 1)
        self.assertEqual(completed.json()["result"], {"graph_id": str(GRAPH_ID)})
        self.assertEqual(self.client.get(f"/v1/graphs/{GRAPH_ID}").status_code, 200)

    def test_missing_job_has_a_specific_error(self):
        missing = self.client.get(
            "/v1/jobs/00000000-0000-0000-0000-000000000099"
        )
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json()["detail"]["code"], "job_not_found")

    def test_shortest_path_uses_the_stored_graph(self):
        self.client.post("/v1/graphs", json={
            "words": ["cat", "bat", "bad", "dad"],
        })
        response = self.client.post(
            f"/v1/graphs/{GRAPH_ID}/queries/shortest-path",
            json={"start": " CAT ", "end": "dad"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "graph_id": str(GRAPH_ID),
            "path": ["cat", "bat", "bad", "dad"],
        })

    def test_missing_graph_and_unknown_word_are_distinct_errors(self):
        missing = self.client.get(
            "/v1/graphs/00000000-0000-0000-0000-000000000099"
        )
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json()["detail"]["code"], "graph_not_found")

        self.client.post("/v1/graphs", json={"words": ["cat", "bat"]})
        unknown = self.client.post(
            f"/v1/graphs/{GRAPH_ID}/queries/shortest-path",
            json={"start": "cat", "end": "dog"},
        )
        self.assertEqual(unknown.status_code, 422)
        self.assertEqual(unknown.json()["detail"]["code"], "unknown_word")

    def test_all_paths_exposes_completeness_and_limits(self):
        self.client.post("/v1/graphs", json={
            "words": ["cat", "bat", "bad", "dad", "cad"],
        })
        response = self.client.post(
            f"/v1/graphs/{GRAPH_ID}/queries/all-simple-paths",
            json={"start": "cat", "end": "dad", "max_paths": 2},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body["paths"]), 2)
        self.assertFalse(body["complete"])
        self.assertEqual(body["stop_reason"], "max_paths")
        self.assertGreater(body["explored_states"], 0)

    def test_longest_path_does_not_claim_unproven_optimality(self):
        self.client.post("/v1/graphs", json={
            "words": ["cat", "bat", "bad", "dad", "cad"],
        })
        response = self.client.post(
            f"/v1/graphs/{GRAPH_ID}/queries/longest-simple-path",
            json={"start": "cat", "end": "dad", "max_states": 5},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["path"], ["cat", "bat", "bad", "cad", "dad"])
        self.assertFalse(response.json()["complete"])
        self.assertEqual(response.json()["stop_reason"], "max_states")

    def test_degree_selection_and_dense_subgraphs(self):
        self.client.post("/v1/graphs", json={
            "words": ["bat", "cat", "mat", "rat", "dog"],
        })
        isolated = self.client.get(f"/v1/graphs/{GRAPH_ID}/nodes?degree=0")
        self.assertEqual(isolated.status_code, 200)
        self.assertEqual(isolated.json()["nodes"], ["dog"])

        dense = self.client.get(
            f"/v1/graphs/{GRAPH_ID}/dense-subgraphs?minimum_degree=3"
        )
        self.assertEqual(dense.status_code, 200)
        self.assertEqual(dense.json()["subgraphs"], [["bat", "cat", "mat", "rat"]])

    def test_request_validation_rejects_invalid_inputs(self):
        self.assertEqual(
            self.client.post("/v1/graphs", json={"words": [], "partitions": 1}).status_code,
            422,
        )
        self.assertEqual(
            self.client.post("/v1/graphs", json={"words": ["cat"], "partitions": 0}).status_code,
            422,
        )
        invalid_words = self.client.post("/v1/graphs", json={"words": ["123", ""]})
        self.assertEqual(invalid_words.status_code, 422)
        self.assertEqual(invalid_words.json()["detail"]["code"], "empty_dictionary")

        self.client.post("/v1/graphs", json={"words": ["cat", "bat"]})
        excessive = self.client.post(
            f"/v1/graphs/{GRAPH_ID}/queries/all-simple-paths",
            json={"start": "cat", "end": "bat", "max_states": 1_000_001},
        )
        self.assertEqual(excessive.status_code, 422)
        invalid_core = self.client.get(
            f"/v1/graphs/{GRAPH_ID}/dense-subgraphs?minimum_degree=0"
        )
        self.assertEqual(invalid_core.status_code, 422)


if __name__ == "__main__":
    unittest.main()
