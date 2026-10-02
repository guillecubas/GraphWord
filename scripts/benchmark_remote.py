"""One trial inside the API node. Driver reconciles every 0.5s for both modes."""
import hashlib
import json
from pathlib import Path
import sys
import time
from uuid import UUID, uuid4
from graphword.aws_runtime import repositories
from graphword.graph import build_partition, summary
from scripts.smoke_aws import request


def main():
    length, workers = int(sys.argv[1]), int(sys.argv[2])
    content = Path(f"data/curated/words{length}.txt").read_bytes()
    words = content.decode().splitlines()
    oracle = build_partition(words)
    graphs, jobs = repositories()
    started = time.perf_counter()
    job = request("/v1/jobs/partitioned-builds", {"words": words, "partitions": 8})
    deadline = time.monotonic() + 240
    while job["status"] not in ("SUCCEEDED", "FAILED") and time.monotonic() < deadline:
        jobs.reconcile()
        time.sleep(0.5)
        job = request("/v1/jobs/" + job["job_id"])
    elapsed = time.perf_counter() - started
    assert job["status"] == "SUCCEEDED", job
    assert graphs.get(UUID(job["result"]["graph_id"])) == oracle
    children = [jobs.get(UUID(child)) for child in jobs._read(UUID(job["job_id"]))["dependencies"]]
    observed = sorted({child.result["worker_id"] for child in children})
    print(json.dumps({"length": length, "configured_workers": workers, "seconds": elapsed,
        "input_sha256": hashlib.sha256(content).hexdigest(), "job_id": job["job_id"],
        "graph_id": job["result"]["graph_id"], "nodes": len(oracle), "edges": summary(oracle)["edges"],
        "observed_workers": observed, "attempts": [child.attempts for child in children], "oracle_equal": True}))


if __name__ == "__main__":
    main()
