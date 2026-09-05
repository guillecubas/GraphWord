"""Deterministic graph operations with no process-global mutable state."""

from collections import defaultdict, deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from hashlib import sha256
import re
from time import monotonic

Graph = dict[str, set[str]]


@dataclass(frozen=True)
class AllPathsResult:
    """Bounded result for an otherwise combinatorial path enumeration."""

    paths: list[list[str]]
    complete: bool
    stop_reason: str | None
    explored_states: int


@dataclass(frozen=True)
class LongestPathResult:
    """Best simple path found, plus whether its optimality is proven."""

    path: list[str]
    complete: bool
    stop_reason: str | None
    explored_states: int


def normalize_words(lines: Iterable[str]) -> list[str]:
    """Normalize ASCII English fixtures; this does NOT verify lexical meaning."""
    return sorted({word for line in lines if re.fullmatch(r"[a-z]+", word := line.strip().lower())})


def partition_for(pattern: str, partitions: int) -> int:
    """Stable across processes, machines and PYTHONHASHSEED settings."""
    if partitions < 1:
        raise ValueError("partitions must be positive")
    return int.from_bytes(sha256(pattern.encode("ascii")).digest(), "big") % partitions


def build_partition(words: Iterable[str], partition: int = 0, partitions: int = 1) -> Graph:
    """Assign whole wildcard buckets, never arbitrary word slices, to a worker.

    Each call currently reads the whole input, retaining all isolated nodes.
    The return value consists only of serializable dicts/sets; no cloud SDK needed.
    """
    if partitions < 1 or not 0 <= partition < partitions:
        raise ValueError("invalid partition index or count")
    clean = normalize_words(words)
    graph = {word: set() for word in clean}
    buckets: dict[str, list[str]] = defaultdict(list)
    for word in clean:
        for index in range(len(word)):
            pattern = word[:index] + "*" + word[index + 1:]
            if partition_for(pattern, partitions) != partition:
                continue
            for other in buckets[pattern]:
                graph[word].add(other)
                graph[other].add(word)
            buckets[pattern].append(word)
    return graph


def merge_partitions(parts: Iterable[Mapping[str, Iterable[str]]]) -> Graph:
    """Union is idempotent: receiving the same partition twice adds no edges."""
    graph: Graph = {}
    for part in parts:
        for word, neighbors in part.items():
            graph.setdefault(word, set()).update(neighbors)
    return graph


def shortest_path(graph: Graph, start: str, end: str) -> list[str]:
    """Breadth-first search is exact for this unweighted graph."""
    start, end = start.strip().lower(), end.strip().lower()
    if start not in graph or end not in graph:
        raise ValueError("both words must exist in the graph")
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
            return path[::-1]
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
    start, end = start.strip().lower(), end.strip().lower()
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
    """Enumerate deterministically without claiming completeness after pruning."""
    start, end = _validate_path_search(
        graph, start, end, max_states, max_depth, timeout_seconds
    )
    deadline = monotonic() + timeout_seconds if timeout_seconds is not None else None
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
            if not best or len(path) > len(best) or (len(path) == len(best) and path < best):
                best = path
            if collect_paths:
                paths.append(path)
            if max_paths is not None and len(paths) >= max_paths and stack:
                return paths, best, False, "max_paths", explored_states
            continue

        unvisited = [neighbor for neighbor in sorted(graph[current]) if neighbor not in visited]
        if max_depth is not None and len(path) - 1 >= max_depth:
            depth_pruned = depth_pruned or bool(unvisited)
            continue
        for neighbor in reversed(unvisited):
            stack.append((neighbor, [*path, neighbor], visited | {neighbor}))

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
    """Return simple paths and say explicitly whether enumeration was exhaustive."""
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
    """Find the longest start-to-end simple path; exact only when complete is true."""
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
    """Connected components; these are NOT dense community detection."""
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
    """Return the maximal induced subgraph whose internal degree is at least k.

    Nodes below the threshold are peeled repeatedly because removing one node can
    make its neighbors fall below the threshold too. The input graph is unchanged.
    """
    if k < 0:
        raise ValueError("k must not be negative")
    remaining = set(graph)
    degrees = {
        node: len(graph[node] & remaining)
        for node in remaining
    }
    pending = deque(sorted(node for node, degree in degrees.items() if degree < k))

    while pending:
        node = pending.popleft()
        if node not in remaining:
            continue
        remaining.remove(node)
        for neighbor in graph[node] & remaining:
            degrees[neighbor] -= 1
            if degrees[neighbor] == k - 1:
                pending.append(neighbor)

    return {
        node: graph[node] & remaining
        for node in sorted(remaining)
    }


def dense_subgraphs(graph: Graph, minimum_degree: int = 2) -> list[list[str]]:
    """Identify connected regions of a k-core, not mere graph components.

    This is an explicit density criterion rather than a modularity-based community
    partition. Raising ``minimum_degree`` produces progressively stricter cores.
    """
    if minimum_degree < 1:
        raise ValueError("minimum_degree must be positive")
    return components(k_core(graph, minimum_degree))


def nodes_by_degree(graph: Graph, degree: int) -> list[str]:
    if degree < 0:
        raise ValueError("degree must not be negative")
    return sorted(word for word, neighbors in graph.items() if len(neighbors) == degree)


def summary(graph: Graph) -> dict:
    max_degree = max(map(len, graph.values()), default=0)
    return {
        "nodes": len(graph),
        "edges": sum(map(len, graph.values())) // 2,
        "components": len(components(graph)),
        "isolated": nodes_by_degree(graph, 0),
        "max_degree": max_degree,
        "highest_degree_nodes": nodes_by_degree(graph, max_degree),
    }
