"""Deterministic graph operations with no process-global mutable state."""

from collections import defaultdict, deque
from collections.abc import Iterable, Mapping
from hashlib import sha256
import re

Graph = dict[str, set[str]]


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
