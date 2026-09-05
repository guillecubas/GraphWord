import unittest
from uuid import UUID

from fastapi.testclient import TestClient

from graphword.api import create_app
from graphword.storage import InMemoryGraphRepository


GRAPH_ID = UUID("00000000-0000-0000-0000-000000000001")


class ApiTests(unittest.TestCase):
    def setUp(self):
        repository = InMemoryGraphRepository(id_factory=lambda: GRAPH_ID)
        self.client = TestClient(create_app(repository))

    def test_health_discloses_local_storage(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "status": "ok",
            "storage": "in-memory-local",
        })

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


if __name__ == "__main__":
    unittest.main()
