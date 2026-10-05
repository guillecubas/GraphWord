"""Rutas HTTP, validación y respuestas públicas de GraphWord."""

from dataclasses import asdict
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Response, status, Header
from graphword.trabajos.submissions import IdempotencyConflict
from pydantic import BaseModel, Field
from graphword.almacenamiento.dictionaries import (
    DictionaryRepository,
    DictionaryNotFoundError,
    InvalidDictionaryError,
    DictionaryUnavailableError,
)

from graphword.motor.graph import (
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
from graphword.trabajos.jobs import (
    InMemoryJobRepository,
    Job,
    JobKind,
    JobNotFoundError,
    JobRepository,
    JobStatus,
    PartitionedBuildRepository,
)
from graphword.almacenamiento.storage import (
    GraphNotFoundError,
    GraphRepository,
    InMemoryGraphRepository,
)


# Estos modelos validan las entradas y definen lo que se ve en Swagger.
class CreateGraphRequest(BaseModel):
    words: list[str] = Field(min_length=1, max_length=100_000)
    partitions: int = Field(default=1, ge=1, le=64)


class DictionaryBuildRequest(BaseModel):
    model_config = {"extra": "forbid"}
    dictionary_id: str = Field(min_length=1, max_length=128, examples=["words3"])
    partitions: int = Field(default=8, ge=1, le=64)


class DictionaryResponse(BaseModel):
    dictionary_id: str
    word_length: int
    word_count: int
    sha256: str
    s3_key: str


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
    # Copiar todos los campos conserva el formato público de la API.
    fields = asdict(job)
    return JobResponse(
        job_id=fields["job_id"],
        kind=fields["kind"],
        status=fields["status"],
        attempts=fields["attempts"],
        max_attempts=fields["max_attempts"],
        result=fields["result"],
        error=fields["error"],
        created_at=fields["created_at"],
        updated_at=fields["updated_at"],
    )


def create_app(
    repository: GraphRepository | None = None,
    job_repository: JobRepository | None = None,
    *,
    storage_label: str = "in-memory-local",
    partitioned_builds: PartitionedBuildRepository | None = None,
    dictionary_repository: DictionaryRepository | None = None,
) -> FastAPI:
    """Crear la API con adaptadores reemplazables para local, AWS y pruebas."""
    # Si no se proporcionan adaptadores, usar almacenamiento en memoria.
    if repository:
        selected_repository = repository
    else:
        selected_repository = InMemoryGraphRepository()
    if job_repository:
        selected_job_repository = job_repository
    else:
        selected_job_repository = InMemoryJobRepository()
    application = FastAPI(
        title="GraphWord API",
        version="0.7.0",
        description=(
            "Word graphs with interchangeable local and AWS storage adapters. "
            "Partitioned jobs are processed by independent workers."
        ),
    )

    def get_repository() -> GraphRepository:
        return selected_repository

    def get_job_repository() -> JobRepository:
        return selected_job_repository

    # Depends entrega a cada petición el repositorio ya configurado.
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

    def dictionary_error(error):
        if isinstance(error, DictionaryNotFoundError):
            return HTTPException(404, detail={"code": "dictionary_not_found"})
        if isinstance(error, InvalidDictionaryError):
            return HTTPException(422, detail={"code": "invalid_dictionary", "message": str(error)})
        return HTTPException(503, detail={"code": "dictionaries_unavailable"})

    @application.get("/v1/dictionaries", response_model=list[DictionaryResponse], tags=["dictionaries"])
    def list_dictionaries():
        if dictionary_repository is None:
            raise dictionary_error(DictionaryUnavailableError())
        try:
            # La API devuelve los metadatos, no todas las palabras del catálogo.
            entries = []
            for item in dictionary_repository.list():
                entries.append(asdict(item))
            return entries
        except (DictionaryNotFoundError, InvalidDictionaryError, DictionaryUnavailableError) as error:
            raise dictionary_error(error) from error

    @application.post("/v1/jobs/dictionary-builds", response_model=JobResponse,
        status_code=status.HTTP_202_ACCEPTED, tags=["jobs"])
    def create_dictionary_build(
        request: DictionaryBuildRequest,
        response: Response,
        idempotency_key: Annotated[
            str | None,
            Header(min_length=1, max_length=128, pattern=r"^[!-~]+$"),
        ] = None,
    ):
        if dictionary_repository is None or partitioned_builds is None:
            raise dictionary_error(DictionaryUnavailableError())
        try:
            # Leer el diccionario elegido y registrar tareas para los workers.
            info, words = dictionary_repository.load(request.dictionary_id)
            job = partitioned_builds.create_partitioned_build(
                words,
                request.partitions,
                idempotency_key=idempotency_key,
                source=asdict(info),
            )
        except (DictionaryNotFoundError, InvalidDictionaryError, DictionaryUnavailableError) as error:
            raise dictionary_error(error) from error
        except IdempotencyConflict as error:
            raise HTTPException(
                409,
                detail={"code": "idempotency_conflict", "message": str(error)},
            ) from error
        except ValueError as error:
            raise HTTPException(422, detail={"code": "invalid_build", "message": str(error)}) from error
        # Esta dirección permite consultar después el estado de la tarea.
        response.headers["Location"] = f"/v1/jobs/{job.job_id}"
        return job_response(job)

    @application.post(
        "/v1/jobs/partitioned-builds", response_model=JobResponse,
        status_code=status.HTTP_202_ACCEPTED, tags=["jobs"],
    )
    def create_partitioned_build(
        request: CreateGraphRequest,
        response: Response,
        idempotency_key: Annotated[
            str | None,
            Header(min_length=1, max_length=128, pattern=r"^[!-~]+$"),
        ] = None,
    ) -> JobResponse:
        if partitioned_builds is None:
            raise HTTPException(503, detail={"code": "partitioned_builds_unavailable"})
        try:
            job = partitioned_builds.create_partitioned_build(
                request.words,
                request.partitions,
                idempotency_key=idempotency_key,
            )
        except IdempotencyConflict as error:
            raise HTTPException(
                409,
                detail={"code": "idempotency_conflict", "message": str(error)},
            ) from error
        except ValueError as error:
            raise HTTPException(422, detail={
                "code": "invalid_build", "message": str(error),
            }) from error
        # Esta dirección permite consultar después el estado de la tarea.
        response.headers["Location"] = f"/v1/jobs/{job.job_id}"
        return job_response(job)

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
        idempotency_key: Annotated[
            str | None,
            Header(min_length=1, max_length=128, pattern=r"^[!-~]+$"),
        ] = None,
    ) -> JobResponse:
        try:
            job = jobs.create(
                JobKind.GRAPH_BUILD,
                {"words": request.words, "partitions": request.partitions},
                idempotency_key=idempotency_key,
            )
        except IdempotencyConflict as error:
            raise HTTPException(
                409,
                detail={"code": "idempotency_conflict", "message": str(error)},
            ) from error
        except ValueError as error:
            raise HTTPException(422, detail={"code": "invalid_build", "message": str(error)}) from error
        # Esta dirección permite consultar después el estado de la tarea.
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
        # Esta operación es síncrona: construye y une las particiones aquí.
        def build_parts():
            for index in range(request.partitions):
                yield build_partition(request.words, index, request.partitions)

        graph = merge_partitions(build_parts())
        if not graph:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"code": "empty_dictionary", "message": "no valid words supplied"},
            )
        graph_id = graph_repository.save(graph)
        response.headers["Location"] = f"/v1/graphs/{graph_id}"
        statistics = summary(graph)
        return GraphSummaryResponse(
            graph_id=graph_id,
            nodes=statistics["nodes"],
            edges=statistics["edges"],
            components=statistics["components"],
            isolated=statistics["isolated"],
            max_degree=statistics["max_degree"],
            highest_degree_nodes=statistics["highest_degree_nodes"],
        )

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
        statistics = summary(graph)
        return GraphSummaryResponse(
            graph_id=graph_id,
            nodes=statistics["nodes"],
            edges=statistics["edges"],
            components=statistics["components"],
            isolated=statistics["isolated"],
            max_degree=statistics["max_degree"],
            highest_degree_nodes=statistics["highest_degree_nodes"],
        )

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
        # Recuperar el grafo guardado antes de ejecutar la consulta.
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
        # Recuperar el grafo guardado antes de ejecutar la consulta.
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
        fields = asdict(result)
        return AllPathsResponse(
            graph_id=graph_id,
            paths=fields["paths"],
            complete=fields["complete"],
            stop_reason=fields["stop_reason"],
            explored_states=fields["explored_states"],
        )

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
        # Recuperar el grafo guardado antes de ejecutar la consulta.
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
        fields = asdict(result)
        return LongestPathResponse(
            graph_id=graph_id,
            path=fields["path"],
            complete=fields["complete"],
            stop_reason=fields["stop_reason"],
            explored_states=fields["explored_states"],
        )

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

    # Devolver la aplicación con todas sus rutas registradas.
    return application


app = create_app()
