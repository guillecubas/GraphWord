"""Run on API instance: exercise deployed HTTP API and compare with local oracle."""
import json
from pathlib import Path
import time
import urllib.request
import urllib.error
from uuid import UUID, uuid4

from graphword.aws_runtime import repositories
from graphword.graph import build_partition, summary


def request(path, body=None, headers=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request("http://127.0.0.1:8000" + path, data=data,
                                 headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def main():
    words = ["cat", "bat", "bad", "dad", "mat", "rat", "zzz"]
    health = request("/health")
    headers = {"Idempotency-Key": "smoke-" + str(uuid4())}
    body = {"words": words, "partitions": 8}
    job = request("/v1/jobs/partitioned-builds", body, headers)
    replay = request("/v1/jobs/partitioned-builds", body, headers)
    assert replay["job_id"] == job["job_id"]
    try:
        request("/v1/jobs/partitioned-builds", {**body, "partitions": 7}, headers)
    except urllib.error.HTTPError as error:
        assert error.code == 409
    else:
        raise AssertionError("Idempotency conflict was not rejected")
    deadline = time.monotonic() + 240
    while job["status"] not in ("SUCCEEDED", "FAILED") and time.monotonic() < deadline:
        time.sleep(3)
        job = request("/v1/jobs/" + job["job_id"])
    assert job["status"] == "SUCCEEDED", job
    graph_id = job["result"]["graph_id"]
    graphs, jobs = repositories()
    assert graphs.get(UUID(graph_id)) == build_partition(words)
    parent = jobs._read(UUID(job["job_id"]))
    children = [jobs.get(UUID(child)) for child in parent["dependencies"]]
    workers = sorted({child.result["worker_id"] for child in children})
    result = {"health": health, "job": job, "graph": request("/v1/graphs/" + graph_id),
              "oracle": summary(build_partition(words)), "workers": workers,
              "children": [{"id": str(child.job_id), "result": child.result} for child in children],
              "shortest_path": request(f"/v1/graphs/{graph_id}/queries/shortest-path", {"start": "cat", "end": "dad"}),
              "oracle_equal": True, "two_workers_observed": len(workers) >= 2,
              "idempotent_replay": True, "idempotency_conflict_409": True}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
