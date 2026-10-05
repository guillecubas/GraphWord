"""One trial inside the API node. Driver reconciles every 0.5s for both modes."""
import hashlib
import json
from pathlib import Path
import sys
import time
from uuid import UUID, uuid4
from graphword.configuracion.aws_runtime import repositories
from graphword.motor.graph import build_partition, summary
from scripts.operaciones.smoke_aws import request


def main():
    # Leer la longitud del diccionario y el número de workers de esta prueba.
    length = int(sys.argv[1])
    workers = int(sys.argv[2])
    content = Path(f"data/curated/words{length}.txt").read_bytes()
    words = content.decode().splitlines()
    oracle = build_partition(words)
    graphs, jobs = repositories()
    # Medir desde el envío HTTP hasta la confirmación del trabajo terminado.
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
    children = []
    parent = jobs._read(UUID(job["job_id"]))
    for child in parent["dependencies"]:
        children.append(jobs.get(UUID(child)))
    worker_ids = set()
    for child in children:
        worker_ids.add(child.result["worker_id"])
    observed = sorted(worker_ids)
    attempts = []
    for child in children:
        attempts.append(child.attempts)
    result = {
        "length": length,
        "configured_workers": workers,
        "seconds": elapsed,
        "input_sha256": hashlib.sha256(content).hexdigest(),
        "job_id": job["job_id"],
        "graph_id": job["result"]["graph_id"],
        "nodes": len(oracle),
        "edges": summary(oracle)["edges"],
        "observed_workers": observed,
        "attempts": attempts,
        "oracle_equal": True,
    }
    print(json.dumps(result))


if __name__ == "__main__":
    main()
