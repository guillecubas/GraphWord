"""Run on API instance: exercise deployed HTTP API and compare with local oracle."""
import json
from pathlib import Path
import time
import urllib.request
from uuid import UUID

from graphword.aws_runtime import repositories
from graphword.graph import build_partition, summary


def request(path, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request("http://127.0.0.1:8000" + path, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def main():
    words = ["cat", "bat", "bad", "dad", "mat", "rat", "zzz"]
    health = request("/health")
    job = request("/v1/jobs/partitioned-builds", {"words": words, "partitions": 8})
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
              "oracle_equal": True, "two_workers_observed": len(workers) >= 2}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
