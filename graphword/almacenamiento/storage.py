"""Contrato de almacenamiento de grafos y su implementación en memoria."""

from collections.abc import Callable
from threading import RLock
from typing import Protocol
from uuid import UUID, uuid4

from graphword.motor.graph import Graph


class GraphNotFoundError(KeyError):
    """El grafo solicitado no existe en este repositorio."""


class GraphRepository(Protocol):
    """Operaciones que deben implementar los repositorios de grafos."""

    def save(self, graph: Graph) -> UUID:
        # El adaptador concreto implementa esta operación.
        pass

    def get(self, graph_id: UUID) -> Graph:
        # El adaptador concreto implementa esta operación.
        pass


class InMemoryGraphRepository:
    """Guardar grafos en este proceso; otras réplicas no comparten estos datos."""

    def __init__(self, id_factory: Callable[[], UUID] = uuid4) -> None:
        self._id_factory = id_factory
        self._graphs: dict[UUID, Graph] = {}
        # Proteger el diccionario cuando varios hilos acceden al repositorio.
        self._lock = RLock()

    def save(self, graph: Graph) -> UUID:
        # Conservar el grafo con un identificador para las siguientes consultas.
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
