"""Command-line worker for the local SQLite multi-process demonstration."""

import argparse
import json
import os
import socket
from time import sleep

from graphword.local_runtime import database_path
from graphword.sqlite_storage import SQLiteGraphRepository, SQLiteJobRepository
from graphword.worker import GraphWordWorker


def default_worker_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}"


def main() -> None:
    parser = argparse.ArgumentParser(description="GraphWord local SQLite worker")
    parser.add_argument("--database")
    parser.add_argument("--worker-id", default=default_worker_id())
    parser.add_argument("--lease-seconds", type=int, default=30)
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if args.lease_seconds < 1:
        parser.error("lease-seconds must be positive")
    if args.poll_seconds <= 0:
        parser.error("poll-seconds must be positive")

    database = database_path(args.database)
    worker = GraphWordWorker(
        SQLiteJobRepository(database),
        SQLiteGraphRepository(database),
    )
    if args.once:
        processed = worker.run_once(args.worker_id, args.lease_seconds)
        print(json.dumps({"worker_id": args.worker_id, "processed": processed}))
        return

    try:
        while True:
            if not worker.run_once(args.worker_id, args.lease_seconds):
                sleep(args.poll_seconds)
    except KeyboardInterrupt:
        return


if __name__ == "__main__":
    main()
