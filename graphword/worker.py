"""Worker application service, independent of the HTTP adapter."""

from graphword.graph import build_partition, merge_partitions
from uuid import UUID

from graphword.jobs import InvalidJobTransition, JobKind, JobRepository, JobStatus
from graphword.storage import GraphRepository


class GraphWordWorker:
    def __init__(self, jobs: JobRepository, graphs: GraphRepository) -> None:
        self._jobs = jobs
        self._graphs = graphs

    def run_once(self, worker_id: str, lease_seconds: int = 30) -> bool:
        """Process at most one job and report whether a claim was obtained."""
        claim = self._jobs.claim_next(worker_id, lease_seconds)
        if claim is None:
            return False
        try:
            if claim.kind is JobKind.BUILD_PARTITION:
                graph = build_partition(
                    claim.payload["words"], claim.payload["partition"],
                    claim.payload["partitions"],
                )
            elif claim.kind is JobKind.REDUCE_GRAPH:
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
                graph = merge_partitions(
                    build_partition(words, index, partitions)
                    for index in range(partitions)
                )
            else:
                raise ValueError(f"unsupported job kind: {claim.kind}")
            graph_id = self._graphs.save(graph)
            result = {"graph_id": str(graph_id)}
            if claim.kind is JobKind.BUILD_PARTITION:
                result.update(worker_id=claim.worker_id, partition=claim.payload["partition"])
            self._jobs.complete(claim, result)
        except InvalidJobTransition:
            pass
        except Exception as error:
            try:
                self._jobs.fail(claim, str(error), retryable=True)
            except InvalidJobTransition:
                pass
        return True
