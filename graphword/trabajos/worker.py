"""Ejecutar tareas de grafos sin depender de las rutas HTTP."""

from graphword.motor.graph import build_partition, merge_partitions
from uuid import UUID
from graphword.trabajos.heartbeat import keep_claim_alive

from graphword.trabajos.jobs import InvalidJobTransition, JobKind, JobRepository, JobStatus
from graphword.almacenamiento.storage import GraphRepository


class GraphWordWorker:
    def __init__(self, jobs: JobRepository, graphs: GraphRepository) -> None:
        self._jobs = jobs
        self._graphs = graphs

    def run_once(self, worker_id: str, lease_seconds: int = 30) -> bool:
        """Procesar como máximo una tarea y devolver si se consiguió una reserva."""
        # Reservar como máximo una tarea; si no hay ninguna, no hacer trabajo.
        claim = self._jobs.claim_next(worker_id, lease_seconds)
        if claim is None:
            return False
        try:
            # Mantener la reserva mientras calculamos y guardamos el grafo.
            with keep_claim_alive(self._jobs, claim, lease_seconds):
                graph = self._build(claim)
                graph_id = self._graphs.save(graph)
            result = {"graph_id": str(graph_id)}
            if "source" in claim.payload:
                result["source"] = claim.payload["source"]
            if claim.kind is JobKind.BUILD_PARTITION:
                result["worker_id"] = claim.worker_id
                result["partition"] = claim.payload["partition"]
            self._jobs.complete(claim, result)
        except InvalidJobTransition:
            # Otro worker puede haber recuperado la tarea; no publicar un resultado viejo.
            pass
        except Exception as error:
            # Registrar el fallo para permitir un nuevo intento cuando corresponda.
            try:
                self._jobs.fail(claim, str(error), retryable=True)
            except InvalidJobTransition:
                pass
        return True

    def _build(self, claim):
        if claim.kind is JobKind.BUILD_PARTITION:
            graph = build_partition(
                claim.payload["words"], claim.payload["partition"],
                claim.payload["partitions"],
            )
        elif claim.kind is JobKind.REDUCE_GRAPH:
            # El reductor solo une particiones que ya terminaron correctamente.
            parts = []
            for child_id in claim.payload["partition_jobs"]:
                child = self._jobs.get(UUID(child_id))
                if child.status is not JobStatus.SUCCEEDED or child.result is None:
                    raise ValueError("partition is not confirmed")
                parts.append(self._graphs.get(UUID(child.result["graph_id"])))
            graph = merge_partitions(parts)
        elif claim.kind is JobKind.GRAPH_BUILD:
            words = claim.payload["words"]
            partitions = claim.payload["partitions"]
            # yield produce una partición cada vez, sin acumular todas en memoria.
            def build_parts():
                for index in range(partitions):
                    yield build_partition(words, index, partitions)

            graph = merge_partitions(build_parts())
        else:
            raise ValueError(f"unsupported job kind: {claim.kind}")
        return graph
