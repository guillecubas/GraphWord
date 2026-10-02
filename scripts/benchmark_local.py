"""Fixed-work strong-scaling experiment; process startup and IPC are included."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import platform
import statistics
import time
from graphword.graph import build_partition, merge_partitions, summary

ROOT = Path(__file__).resolve().parents[1]


def part(words, index, partitions):
    start = time.process_time()
    graph = build_partition(words, index, partitions)
    return graph, time.process_time() - start


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--partitions", type=int, default=8)
    parser.add_argument("--output", default="docs/evidence/benchmark-local.json")
    args = parser.parse_args()
    if args.repeats < 2 or args.partitions < 1:
        parser.error("at least two repeats and one partition required")
    records = []
    for length in (3, 4, 5, 6, 7, 8):
        source = ROOT / f"data/curated/words{length}.txt"
        data = source.read_bytes()
        words = data.decode().splitlines()
        oracle = build_partition(words)
        n = len(oracle)
        graph_summary = summary(oracle)
        samples = {1: [], 2: []}
        for trial in range(args.repeats):
            # Alternate order to reduce a systematic warm-cache/order advantage.
            for workers in ((1, 2) if trial % 2 == 0 else (2, 1)):
                start = time.perf_counter()
                with ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("spawn")) as pool:
                    futures = [pool.submit(part, words, index, args.partitions) for index in range(args.partitions)]
                    parts = [future.result() for future in futures]
                    graph = merge_partitions(item[0] for item in parts)
                elapsed = time.perf_counter() - start
                assert graph == oracle
                samples[workers].append({"seconds": elapsed, "worker_cpu_seconds_sum": sum(item[1] for item in parts)})
        medians = {workers: statistics.median(item["seconds"] for item in values) for workers, values in samples.items()}
        record = {"length": length, "input_sha256": hashlib.sha256(data).hexdigest(),
                  "nodes": n, "edges": graph_summary["edges"],
                  "density": 2 * graph_summary["edges"] / (n * (n - 1)) if n > 1 else 0,
                  "components": graph_summary["components"], "isolated_count": len(graph_summary["isolated"]),
                  "samples": samples, "median_seconds": medians,
                  "speedup_1_over_2": medians[1] / medians[2], "all_graphs_equal": True}
        records.append(record)
        print(f"length={length} nodes={n} 1-worker={medians[1]:.4f}s 2-workers={medians[2]:.4f}s speedup={medians[1]/medians[2]:.3f}", flush=True)
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"platform": platform.platform(), "python": platform.python_version(),
        "logical_cpus": os.cpu_count(), "partitions": args.partitions, "repeats": args.repeats,
        "includes": ["spawn", "partition computation", "IPC", "merge", "pool shutdown"],
        "excludes": ["file read", "reference graph", "equality assertion"], "records": records}, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
