"""Storage ports and the explicitly local adapter used in the HTTP milestone."""

from collections.abc import Callable
from threading import RLock
from typing import Protocol
from uuid import UUID, uuid4

from graphword.graph import Graph


class GraphNotFoundError(KeyError):
    """Raised when a graph identifier is not present in a repository."""


class GraphRepository(Protocol):
    """Port that future S3/DynamoDB adapters must implement."""

    def save(self, graph: Graph) -> UUID: ...

    def get(self, graph_id: UUID) -> Graph: ...


class InMemoryGraphRepository:
    """Process-local development adapter; replicas do not share this state."""

    def __init__(self, id_factory: Callable[[], UUID] = uuid4) -> None:
        self._id_factory = id_factory
        self._graphs: dict[UUID, Graph] = {}
        self._lock = RLock()

    def save(self, graph: Graph) -> UUID:
        graph_id = self._id_factory()
        with self._lock:
            self._graphs[graph_id] = graph
        return graph_id

    def get(self, graph_id: UUID) -> Graph:
        with self._lock:
            try:
                return self._graphs[graph_id]
            except KeyError as error:
                raise GraphNotFoundError(str(graph_id)) from error
