"""Arrancar el worker o el reconciliador AWS como proceso supervisado por systemd."""
import argparse
import logging
import socket
import time
from graphword.configuracion.aws_runtime import repositories
from graphword.trabajos.worker import GraphWordWorker


def main():
    # Elegir si este proceso calcula tareas o recupera tareas pendientes.
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["worker", "reconcile"])
    parser.add_argument("--worker-id", default=socket.gethostname())
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--lease-seconds", type=int, default=300)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    graphs, jobs = repositories()
    worker = GraphWordWorker(jobs, graphs)
    while True:
        try:
            if args.mode == "reconcile":
                result = jobs.reconcile()
            else:
                result = worker.run_once(args.worker_id, args.lease_seconds)
            if result:
                logging.info("%s worker=%s result=%s", args.mode, args.worker_id, result)
        except Exception:
            logging.exception("Transient service error; durable jobs will be recovered")
            if args.once:
                raise
            time.sleep(5)
        if args.once:
            return
        if args.mode == "reconcile":
            time.sleep(30)


if __name__ == "__main__":
    main()
