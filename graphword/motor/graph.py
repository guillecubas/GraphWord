"""Construcción y consultas de grafos, sin datos compartidos entre ejecuciones."""

from collections import defaultdict, deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from hashlib import sha256
import re
from time import monotonic

Graph = dict[str, set[str]]


@dataclass(frozen=True)
class AllPathsResult:
    """Caminos encontrados e información sobre los límites de la búsqueda."""

    paths: list[list[str]]
    complete: bool
    stop_reason: str | None
    explored_states: int


@dataclass(frozen=True)
class LongestPathResult:
    """Mejor camino encontrado y confirmación de si la búsqueda fue completa."""

    path: list[str]
    complete: bool
    stop_reason: str | None
    explored_states: int


def normalize_words(lines: Iterable[str]) -> list[str]:
    """Limpiar palabras inglesas ASCII; esto no comprueba su significado."""
    # Limpiar cada palabra y eliminar duplicados antes de ordenar.
    valid_words = set()
    for line in lines:
        word = line.strip().lower()
        if re.fullmatch(r"[a-z]+", word):
            valid_words.add(word)
    return sorted(valid_words)


def partition_for(pattern: str, partitions: int) -> int:
    """Calcular una partición estable entre procesos, máquinas y semillas."""
    if partitions < 1:
        raise ValueError("partitions must be positive")
    # El mismo patrón siempre debe llegar al mismo worker.
    encoded_pattern = pattern.encode("ascii")
    digest = sha256(encoded_pattern).digest()
    number = int.from_bytes(digest, "big")
    return number % partitions


def build_partition(words: Iterable[str], partition: int = 0, partitions: int = 1) -> Graph:
    """Asignar patrones completos a un worker, no trozos arbitrarios de palabras.

    Cada llamada lee todas las palabras e incluye los nodos aislados.
    El resultado contiene diccionarios y conjuntos; no necesita servicios AWS.
    """
    if partitions < 1 or not 0 <= partition < partitions:
        raise ValueError("invalid partition index or count")
    clean = normalize_words(words)
    # Incluir también las palabras que no tienen vecinos.
    graph = {}
    for word in clean:
        graph[word] = set()
    buckets: dict[str, list[str]] = defaultdict(list)
    for word in clean:
        for index in range(len(word)):
            pattern = word[:index] + "*" + word[index + 1:]
            if partition_for(pattern, partitions) != partition:
                continue
            # Las palabras del mismo patrón difieren en una sola letra.
            for other in buckets[pattern]:
                graph[word].add(other)
                graph[other].add(word)
            buckets[pattern].append(word)
    return graph


def merge_partitions(parts: Iterable[Mapping[str, Iterable[str]]]) -> Graph:
    """Unir particiones sin duplicar aristas cuando una partición se repite."""
    graph: Graph = {}
    for part in parts:
        for word, neighbors in part.items():
            if word not in graph:
                graph[word] = set()
            # update evita repetir aristas si llega una partición duplicada.
            graph[word].update(neighbors)
    return graph


def shortest_path(graph: Graph, start: str, end: str) -> list[str]:
    """Buscar por anchura (BFS) el camino mínimo de este grafo sin pesos."""
    start = start.strip().lower()
    end = end.strip().lower()
    if start not in graph or end not in graph:
        raise ValueError("both words must exist in the graph")
    # BFS visita primero los nodos más cercanos al origen.
    previous: dict[str, str | None] = {start: None}
    queue = deque([start])
    while queue:
        current = queue.popleft()
        if current == end:
            path = []
            node: str | None = current
            while node is not None:
                path.append(node)
                node = previous[node]
            # Reconstruimos desde el destino; invertir da el orden del recorrido.
            path.reverse()
            return path
        for neighbor in sorted(graph[current]):
            if neighbor not in previous:
                previous[neighbor] = current
                queue.append(neighbor)
    return []


def _validate_path_search(
    graph: Graph,
    start: str,
    end: str,
    max_states: int,
    max_depth: int | None,
    timeout_seconds: float | None,
) -> tuple[str, str]:
    start = start.strip().lower()
    end = end.strip().lower()
    if start not in graph or end not in graph:
        raise ValueError("both words must exist in the graph")
    if max_states < 1:
        raise ValueError("max_states must be positive")
    if max_depth is not None and max_depth < 0:
        raise ValueError("max_depth must not be negative")
    if timeout_seconds is not None and timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    return start, end


def _bounded_simple_paths(
    graph: Graph,
    start: str,
    end: str,
    *,
    max_states: int,
    max_depth: int | None,
    timeout_seconds: float | None,
    max_paths: int | None,
    collect_paths: bool,
) -> tuple[list[list[str]], list[str], bool, str | None, int]:
    """Enumerar caminos en orden estable e indicar si un límite detuvo la búsqueda."""
    start, end = _validate_path_search(
        graph, start, end, max_states, max_depth, timeout_seconds
    )
    deadline = None
    if timeout_seconds is not None:
        deadline = monotonic() + timeout_seconds
    # Cada entrada guarda el nodo, su camino y los nodos ya visitados.
    stack: list[tuple[str, list[str], frozenset[str]]] = [
        (start, [start], frozenset({start}))
    ]
    paths: list[list[str]] = []
    best: list[str] = []
    explored_states = 0
    depth_pruned = False

    while stack:
        if deadline is not None and monotonic() >= deadline:
            return paths, best, False, "timeout", explored_states
        if explored_states >= max_states:
            return paths, best, False, "max_states", explored_states

        current, path, visited = stack.pop()
        explored_states += 1
        if current == end:
            better_path = False
            if not best:
                better_path = True
            elif len(path) > len(best):
                better_path = True
            elif len(path) == len(best) and path < best:
                better_path = True
            if better_path:
                best = path
            if collect_paths:
                paths.append(path)
            if max_paths is not None and len(paths) >= max_paths and stack:
                return paths, best, False, "max_paths", explored_states
            continue

        unvisited = []
        for neighbor in sorted(graph[current]):
            if neighbor not in visited:
                unvisited.append(neighbor)
        if max_depth is not None and len(path) - 1 >= max_depth:
            if unvisited:
                depth_pruned = True
            continue
        for neighbor in reversed(unvisited):
            # Copiar evita modificar los caminos de otras ramas de la búsqueda.
            next_path = path.copy()
            next_path.append(neighbor)
            next_visited = visited.union({neighbor})
            stack.append((neighbor, next_path, next_visited))

    if depth_pruned:
        return paths, best, False, "max_depth", explored_states
    return paths, best, True, None, explored_states


def all_simple_paths(
    graph: Graph,
    start: str,
    end: str,
    *,
    max_paths: int = 1_000,
    max_states: int = 100_000,
    max_depth: int | None = None,
    timeout_seconds: float | None = None,
) -> AllPathsResult:
    """Devolver caminos sin ciclos e indicar si se pudieron explorar todos."""
    if max_paths < 1:
        raise ValueError("max_paths must be positive")
    paths, _, complete, stop_reason, explored_states = _bounded_simple_paths(
        graph,
        start,
        end,
        max_states=max_states,
        max_depth=max_depth,
        timeout_seconds=timeout_seconds,
        max_paths=max_paths,
        collect_paths=True,
    )
    return AllPathsResult(paths, complete, stop_reason, explored_states)


def longest_simple_path(
    graph: Graph,
    start: str,
    end: str,
    *,
    max_states: int = 100_000,
    max_depth: int | None = None,
    timeout_seconds: float | None = None,
) -> LongestPathResult:
    """Buscar el camino más largo sin ciclos; es exacto solo si complete es True."""
    _, best, complete, stop_reason, explored_states = _bounded_simple_paths(
        graph,
        start,
        end,
        max_states=max_states,
        max_depth=max_depth,
        timeout_seconds=timeout_seconds,
        max_paths=None,
        collect_paths=False,
    )
    return LongestPathResult(best, complete, stop_reason, explored_states)


def components(graph: Graph) -> list[list[str]]:
    """Encontrar grupos conectados; no confundirlos con comunidades densas."""
    # Recorrer cada grupo una vez, marcando los nodos que ya hemos visto.
    seen: set[str] = set()
    result = []
    for node in sorted(graph):
        if node in seen:
            continue
        group = []
        pending = [node]
        seen.add(node)
        while pending:
            current = pending.pop()
            group.append(current)
            for neighbor in graph[current]:
                if neighbor not in seen:
                    seen.add(neighbor)
                    pending.append(neighbor)
        result.append(sorted(group))
    return result


def k_core(graph: Graph, k: int) -> Graph:
    """Conservar el mayor subgrafo en el que cada nodo tiene al menos k vecinos.

    Eliminar nodos de grado bajo puede reducir el grado de sus vecinos.
    Repetimos esa eliminación sin modificar el grafo original.
    """
    if k < 0:
        raise ValueError("k must not be negative")
    remaining = set(graph)
    degrees = {}
    for node in remaining:
        internal_neighbors = graph[node].intersection(remaining)
        degrees[node] = len(internal_neighbors)
    low_degree_nodes = []
    for node, degree in degrees.items():
        if degree < k:
            low_degree_nodes.append(node)
    pending = deque(sorted(low_degree_nodes))

    while pending:
        node = pending.popleft()
        if node not in remaining:
            continue
        remaining.remove(node)
        # Al quitar un nodo, sus vecinos pierden una conexión interna.
        for neighbor in graph[node].intersection(remaining):
            degrees[neighbor] -= 1
            if degrees[neighbor] == k - 1:
                pending.append(neighbor)

    result = {}
    for node in sorted(remaining):
        result[node] = graph[node].intersection(remaining)
    return result


def dense_subgraphs(graph: Graph, minimum_degree: int = 2) -> list[list[str]]:
    """Encontrar regiones conectadas después de aplicar el filtro k-core.

    La densidad se define por el número mínimo de vecinos internos, no por
    modularidad. Aumentar minimum_degree hace más exigente ese filtro.
    """
    if minimum_degree < 1:
        raise ValueError("minimum_degree must be positive")
    return components(k_core(graph, minimum_degree))


def nodes_by_degree(graph: Graph, degree: int) -> list[str]:
    if degree < 0:
        raise ValueError("degree must not be negative")
    selected_words = []
    for word, neighbors in graph.items():
        if len(neighbors) == degree:
            selected_words.append(word)
    return sorted(selected_words)


def summary(graph: Graph) -> dict:
    # Cada arista aparece en los vecinos de sus dos extremos.
    max_degree = 0
    total_connections = 0
    for neighbors in graph.values():
        degree = len(neighbors)
        total_connections += degree
        if degree > max_degree:
            max_degree = degree
    return {
        "nodes": len(graph),
        "edges": total_connections // 2,
        "components": len(components(graph)),
        "isolated": nodes_by_degree(graph, 0),
        "max_degree": max_degree,
        "highest_degree_nodes": nodes_by_degree(graph, max_degree),
    }
