"""Versioned HTTP adapter for the local GraphWord engine."""

from dataclasses import asdict
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Response, status
from pydantic import BaseModel, Field

from graphword.graph import (
    all_simple_paths,
    build_partition,
    dense_subgraphs,
    Graph,
    longest_simple_path,
    merge_partitions,
    nodes_by_degree,
    shortest_path,
    summary,
)
from graphword.jobs import (
    InMemoryJobRepository,
    Job,
    JobKind,
    JobNotFoundError,
    JobRepository,
    JobStatus,
)
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


class AllPathsRequest(PathRequest):
    max_paths: int = Field(default=1_000, ge=1, le=10_000)
    max_states: int = Field(default=100_000, ge=1, le=1_000_000)
    max_depth: int | None = Field(default=None, ge=0, le=10_000)
    timeout_seconds: float | None = Field(default=None, gt=0, le=30)


class LongestPathRequest(PathRequest):
    max_states: int = Field(default=100_000, ge=1, le=1_000_000)
    max_depth: int | None = Field(default=None, ge=0, le=10_000)
    timeout_seconds: float | None = Field(default=None, gt=0, le=30)


StopReason = Literal["max_paths", "max_states", "max_depth", "timeout"]


class AllPathsResponse(BaseModel):
    graph_id: UUID
    paths: list[list[str]]
    complete: bool
    stop_reason: StopReason | None
    explored_states: int


class LongestPathResponse(BaseModel):
    graph_id: UUID
    path: list[str]
    complete: bool
    stop_reason: StopReason | None
    explored_states: int


class DegreeNodesResponse(BaseModel):
    graph_id: UUID
    degree: int
    nodes: list[str]


class DenseSubgraphsResponse(BaseModel):
    graph_id: UUID
    minimum_degree: int
    subgraphs: list[list[str]]


class JobResponse(BaseModel):
    job_id: UUID
    kind: JobKind
    status: JobStatus
    attempts: int
    max_attempts: int
    result: dict | None
    error: str | None
    created_at: datetime
    updated_at: datetime


def job_response(job: Job) -> JobResponse:
    return JobResponse(**asdict(job))


def create_app(
    repository: GraphRepository | None = None,
    job_repository: JobRepository | None = None,
    *,
    storage_label: str = "in-memory-local",
) -> FastAPI:
    """Application factory keeps the storage adapter replaceable and testable."""
    selected_repository = repository or InMemoryGraphRepository()
    selected_job_repository = job_repository or InMemoryJobRepository()
    application = FastAPI(
        title="GraphWord API",
        version="0.4.0",
        description=(
            "Local API and leased-job milestone. The configured adapters are not "
            "the final AWS distributed architecture."
        ),
    )

    def get_repository() -> GraphRepository:
        return selected_repository

    def get_job_repository() -> JobRepository:
        return selected_job_repository

    RepositoryDependency = Annotated[GraphRepository, Depends(get_repository)]
    JobRepositoryDependency = Annotated[JobRepository, Depends(get_job_repository)]

    def find_graph(graph_id: UUID, graph_repository: GraphRepository) -> Graph:
        try:
            return graph_repository.get(graph_id)
        except GraphNotFoundError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "graph_not_found", "message": str(graph_id)},
            ) from error

    def unknown_word(error: ValueError) -> HTTPException:
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "unknown_word", "message": str(error)},
        )

    def find_job(job_id: UUID, jobs: JobRepository) -> Job:
        try:
            return jobs.get(job_id)
        except JobNotFoundError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "job_not_found", "message": str(job_id)},
            ) from error

    @application.get("/health", tags=["operations"])
    def health() -> dict[str, str]:
        return {"status": "ok", "storage": storage_label}

    @application.post(
        "/v1/jobs/graph-builds",
        response_model=JobResponse,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["jobs"],
    )
    def create_graph_build_job(
        request: CreateGraphRequest,
        response: Response,
        jobs: JobRepositoryDependency,
    ) -> JobResponse:
        job = jobs.create(
            JobKind.GRAPH_BUILD,
            {"words": request.words, "partitions": request.partitions},
        )
        response.headers["Location"] = f"/v1/jobs/{job.job_id}"
        return job_response(job)

    @application.get(
        "/v1/jobs/{job_id}",
        response_model=JobResponse,
        tags=["jobs"],
    )
    def get_job(
        job_id: UUID,
        jobs: JobRepositoryDependency,
    ) -> JobResponse:
        return job_response(find_job(job_id, jobs))

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
            raise unknown_word(error) from error
        return PathResponse(graph_id=graph_id, path=path)

    @application.post(
        "/v1/graphs/{graph_id}/queries/all-simple-paths",
        response_model=AllPathsResponse,
        tags=["queries"],
    )
    def query_all_simple_paths(
        graph_id: UUID,
        request: AllPathsRequest,
        graph_repository: RepositoryDependency,
    ) -> AllPathsResponse:
        graph = find_graph(graph_id, graph_repository)
        try:
            result = all_simple_paths(
                graph,
                request.start,
                request.end,
                max_paths=request.max_paths,
                max_states=request.max_states,
                max_depth=request.max_depth,
                timeout_seconds=request.timeout_seconds,
            )
        except ValueError as error:
            raise unknown_word(error) from error
        return AllPathsResponse(graph_id=graph_id, **asdict(result))

    @application.post(
        "/v1/graphs/{graph_id}/queries/longest-simple-path",
        response_model=LongestPathResponse,
        tags=["queries"],
    )
    def query_longest_simple_path(
        graph_id: UUID,
        request: LongestPathRequest,
        graph_repository: RepositoryDependency,
    ) -> LongestPathResponse:
        graph = find_graph(graph_id, graph_repository)
        try:
            result = longest_simple_path(
                graph,
                request.start,
                request.end,
                max_states=request.max_states,
                max_depth=request.max_depth,
                timeout_seconds=request.timeout_seconds,
            )
        except ValueError as error:
            raise unknown_word(error) from error
        return LongestPathResponse(graph_id=graph_id, **asdict(result))

    @application.get(
        "/v1/graphs/{graph_id}/nodes",
        response_model=DegreeNodesResponse,
        tags=["queries"],
    )
    def query_nodes_by_degree(
        graph_id: UUID,
        degree: Annotated[int, Field(ge=0)],
        graph_repository: RepositoryDependency,
    ) -> DegreeNodesResponse:
        graph = find_graph(graph_id, graph_repository)
        return DegreeNodesResponse(
            graph_id=graph_id,
            degree=degree,
            nodes=nodes_by_degree(graph, degree),
        )

    @application.get(
        "/v1/graphs/{graph_id}/dense-subgraphs",
        response_model=DenseSubgraphsResponse,
        tags=["queries"],
    )
    def query_dense_subgraphs(
        graph_id: UUID,
        graph_repository: RepositoryDependency,
        minimum_degree: Annotated[int, Field(ge=1, le=10_000)] = 2,
    ) -> DenseSubgraphsResponse:
        graph = find_graph(graph_id, graph_repository)
        return DenseSubgraphsResponse(
            graph_id=graph_id,
            minimum_degree=minimum_degree,
            subgraphs=dense_subgraphs(graph, minimum_degree),
        )

    return application


app = create_app()
