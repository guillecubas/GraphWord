"""Versioned HTTP adapter for the local GraphWord engine."""

from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Response, status
from pydantic import BaseModel, Field

from graphword.graph import build_partition, merge_partitions, shortest_path, summary
from graphword.storage import GraphNotFoundError, GraphRepository, InMemoryGraphRepository


class CreateGraphRequest(BaseModel):
    words: list[str] = Field(min_length=1, max_length=100_000)
    partitions: int = Field(default=1, ge=1, le=64)


class GraphSummaryResponse(BaseModel):
    graph_id: UUID
    nodes: int
    edges: int
    components: int
    isolated: list[str]
    max_degree: int
    highest_degree_nodes: list[str]


class PathRequest(BaseModel):
    start: str = Field(min_length=1)
    end: str = Field(min_length=1)


class PathResponse(BaseModel):
    graph_id: UUID
    path: list[str]


def create_app(repository: GraphRepository | None = None) -> FastAPI:
    """Application factory keeps the storage adapter replaceable and testable."""
    selected_repository = repository or InMemoryGraphRepository()
    application = FastAPI(
        title="GraphWord API",
        version="0.2.0",
        description=(
            "Local synchronous milestone. Its in-memory repository is not shared "
            "between replicas and is not the final distributed architecture."
        ),
    )

    def get_repository() -> GraphRepository:
        return selected_repository

    RepositoryDependency = Annotated[GraphRepository, Depends(get_repository)]

    def find_graph(graph_id: UUID, graph_repository: GraphRepository):
        try:
            return graph_repository.get(graph_id)
        except GraphNotFoundError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "graph_not_found", "message": str(graph_id)},
            ) from error

    @application.get("/health", tags=["operations"])
    def health() -> dict[str, str]:
        return {"status": "ok", "storage": "in-memory-local"}

    @application.post(
        "/v1/graphs",
        response_model=GraphSummaryResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["graphs"],
    )
    def create_graph(
        request: CreateGraphRequest,
        response: Response,
        graph_repository: RepositoryDependency,
    ) -> GraphSummaryResponse:
        graph = merge_partitions(
            build_partition(request.words, index, request.partitions)
            for index in range(request.partitions)
        )
        if not graph:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"code": "empty_dictionary", "message": "no valid words supplied"},
            )
        graph_id = graph_repository.save(graph)
        response.headers["Location"] = f"/v1/graphs/{graph_id}"
        return GraphSummaryResponse(graph_id=graph_id, **summary(graph))

    @application.get(
        "/v1/graphs/{graph_id}",
        response_model=GraphSummaryResponse,
        tags=["graphs"],
    )
    def get_graph(
        graph_id: UUID,
        graph_repository: RepositoryDependency,
    ) -> GraphSummaryResponse:
        graph = find_graph(graph_id, graph_repository)
        return GraphSummaryResponse(graph_id=graph_id, **summary(graph))

    @application.post(
        "/v1/graphs/{graph_id}/queries/shortest-path",
        response_model=PathResponse,
        tags=["queries"],
    )
    def query_shortest_path(
        graph_id: UUID,
        request: PathRequest,
        graph_repository: RepositoryDependency,
    ) -> PathResponse:
        graph = find_graph(graph_id, graph_repository)
        try:
            path = shortest_path(graph, request.start, request.end)
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"code": "unknown_word", "message": str(error)},
            ) from error
        return PathResponse(graph_id=graph_id, path=path)

    return application


app = create_app()
