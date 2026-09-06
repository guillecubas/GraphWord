"""Worker application service, independent of the HTTP adapter."""

from graphword.graph import build_partition, merge_partitions
from graphword.jobs import InvalidJobTransition, JobKind, JobRepository
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
            if claim.kind is not JobKind.GRAPH_BUILD:
                raise ValueError(f"unsupported job kind: {claim.kind}")
            words = claim.payload["words"]
            partitions = claim.payload["partitions"]
            graph = merge_partitions(
                build_partition(words, index, partitions)
                for index in range(partitions)
            )
            graph_id = self._graphs.save(graph)
            self._jobs.complete(claim, {"graph_id": str(graph_id)})
        except InvalidJobTransition:
            pass
        except Exception as error:
            try:
                self._jobs.fail(claim, str(error), retryable=True)
            except InvalidJobTransition:
                pass
        return True
