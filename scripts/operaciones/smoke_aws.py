"""Run on API instance: exercise deployed HTTP API and compare with local oracle."""
import json
from pathlib import Path
import time
import urllib.request
import urllib.error
from uuid import UUID, uuid4

from graphword.configuracion.aws_runtime import repositories
from graphword.motor.graph import build_partition, summary
from graphword.almacenamiento.aws_storage import S3DictionaryRepository
from dataclasses import asdict
import os


def request(path, body=None, headers=None):
    # Sin cuerpo se hace una lectura; con cuerpo se envía JSON.
    data = None
    if body is not None:
        data = json.dumps(body).encode()
    request_headers = {"Content-Type": "application/json"}
    if headers:
        request_headers.update(headers)
    req = urllib.request.Request(
        "http://127.0.0.1:8000" + path,
        data=data,
        headers=request_headers,
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def main():
    words = ["cat", "bat", "bad", "dad", "mat", "rat", "zzz"]
    # Primero comprobar que la API responde y acepta trabajos distribuidos.
    health = request("/health")
    headers = {"Idempotency-Key": "smoke-" + str(uuid4())}
    body = {"words": words, "partitions": 8}
    job = request("/v1/jobs/partitioned-builds", body, headers)
    replay = request("/v1/jobs/partitioned-builds", body, headers)
    assert replay["job_id"] == job["job_id"]
    try:
        conflicting_body = body.copy()
        conflicting_body["partitions"] = 7
        request("/v1/jobs/partitioned-builds", conflicting_body, headers)
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
    children = []
    for child in parent["dependencies"]:
        children.append(jobs.get(UUID(child)))
    worker_ids = set()
    child_results = []
    for child in children:
        worker_ids.add(child.result["worker_id"])
        child_results.append({"id": str(child.job_id), "result": child.result})
    workers = sorted(worker_ids)
    # Guardar la evidencia de las comprobaciones ya realizadas.
    result = {
        "health": health,
        "job": job,
        "graph": request("/v1/graphs/" + graph_id),
        "oracle": summary(build_partition(words)),
        "workers": workers,
        "children": child_results,
        "shortest_path": request(
            f"/v1/graphs/{graph_id}/queries/shortest-path",
            {"start": "cat", "end": "dad"},
        ),
        "oracle_equal": True,
        "two_workers_observed": len(workers) >= 2,
        "idempotent_replay": True,
        "idempotency_conflict_409": True,
    }
    # Leer el catálogo real de S3 y comprobar el grafo obtenido con sus palabras.
    catalogue = request("/v1/dictionaries")
    dictionaries = S3DictionaryRepository(graphs.client, graphs.bucket,
                                          os.environ["GRAPHWORD_DICTIONARY_CATALOG"])
    info, dictionary_words = dictionaries.load("words3")
    assert asdict(info) in catalogue
    dictionary_job = request("/v1/jobs/dictionary-builds", {"dictionary_id": "words3", "partitions": 8})
    deadline = time.monotonic() + 240
    while dictionary_job["status"] not in ("SUCCEEDED", "FAILED") and time.monotonic() < deadline:
        time.sleep(3)
        dictionary_job = request("/v1/jobs/" + dictionary_job["job_id"])
    assert dictionary_job["status"] == "SUCCEEDED", dictionary_job
    assert dictionary_job["result"]["source"] == asdict(info)
    dictionary_graph_id = dictionary_job["result"]["graph_id"]
    assert graphs.get(UUID(dictionary_graph_id)) == build_partition(dictionary_words)
    result["dictionary_build"] = {
        "job": dictionary_job,
        "graph": request("/v1/graphs/" + dictionary_graph_id),
        "oracle_equal": True,
        "shortest_path": request(
            f"/v1/graphs/{dictionary_graph_id}/queries/shortest-path",
            {"start": "cat", "end": "dad"},
        ),
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
