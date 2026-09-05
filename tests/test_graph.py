import json
import os
from pathlib import Path
import random
import subprocess
import sys
import unittest

from graphword.graph import (
    all_simple_paths, build_partition, components, dense_subgraphs, k_core,
    longest_simple_path, merge_partitions, nodes_by_degree, normalize_words,
    partition_for, shortest_path, summary,
)


def pairwise_reference(words):
    words = sorted(set(words))
    graph = {word: set() for word in words}
    for i, first in enumerate(words):
        for second in words[i + 1:]:
            if len(first) == len(second) and sum(a != b for a, b in zip(first, second)) == 1:
                graph[first].add(second)
                graph[second].add(first)
    return graph


class GraphTests(unittest.TestCase):
    def test_normalization_does_not_guess_meaning_from_vowels(self):
        self.assertEqual(normalize_words([" Cat ", "cat", "DOG", "rhythms", "", "b4t"]),
                         ["cat", "dog", "rhythms"])

    def test_edges_are_undirected_and_same_length(self):
        graph = build_partition(["cat", "bat", "cot", "dog", "dogs", "cat"])
        self.assertEqual(graph["cat"], {"bat", "cot"})
        self.assertEqual(graph["dog"], set())
        self.assertEqual(graph, pairwise_reference(graph))

    def test_partition_union_against_independent_oracle(self):
        rng = random.Random(42)
        for trial in range(20):
            words = ["".join(rng.choices("abcde", k=rng.randint(1, 5))) for _ in range(70)]
            expected = pairwise_reference(words)
            for count in (1, 2, 7, 31):
                with self.subTest(trial=trial, count=count):
                    parts = [build_partition(words, i, count) for i in range(count)]
                    self.assertEqual(merge_partitions(parts), expected)
                    self.assertEqual(sum(sum(map(len, p.values())) for p in parts),
                                     sum(map(len, expected.values())))

    def test_partition_ids_stable_in_separate_interpreters(self):
        expression = "from graphword.graph import partition_for; print(partition_for('c*t', 31))"
        for seed in ("1", "123"):
            output = subprocess.check_output([sys.executable, "-c", expression],
                                             env={**os.environ, "PYTHONHASHSEED": seed}, text=True)
            self.assertEqual(int(output), partition_for("c*t", 31))

    def test_retrying_partition_does_not_duplicate_edges(self):
        part = build_partition(["cat", "bat", "cot"])
        self.assertEqual(merge_partitions([part, part]), part)

    def test_builds_do_not_share_state(self):
        first = build_partition(["cat", "bat"])
        first["cat"].clear()
        self.assertEqual(build_partition(["cat", "bat"])["cat"], {"bat"})
        self.assertEqual(build_partition([]), {})

    def test_shortest_path_and_normalization(self):
        graph = build_partition(["cat", "bat", "bad", "dad"])
        self.assertEqual(shortest_path(graph, " CAT ", "dad"), ["cat", "bat", "bad", "dad"])
        self.assertEqual(shortest_path(graph, "cat", "cat"), ["cat"])

    def test_disconnected_and_unknown_words(self):
        graph = build_partition(["cat", "dog"])
        self.assertEqual(shortest_path(graph, "cat", "dog"), [])
        with self.assertRaises(ValueError):
            shortest_path(graph, "cat", "bad")

    def test_all_simple_paths_are_deterministic_and_complete(self):
        graph = build_partition(["cat", "bat", "bad", "dad", "cad"])
        result = all_simple_paths(graph, " CAT ", "dad")
        self.assertTrue(result.complete)
        self.assertIsNone(result.stop_reason)
        self.assertEqual(result.paths, [
            ["cat", "bat", "bad", "cad", "dad"],
            ["cat", "bat", "bad", "dad"],
            ["cat", "cad", "bad", "dad"],
            ["cat", "cad", "dad"],
        ])

    def test_all_simple_paths_reports_truncation(self):
        graph = build_partition(["cat", "bat", "bad", "dad", "cad"])
        by_count = all_simple_paths(graph, "cat", "dad", max_paths=2)
        self.assertFalse(by_count.complete)
        self.assertEqual(by_count.stop_reason, "max_paths")
        self.assertEqual(len(by_count.paths), 2)

        by_depth = all_simple_paths(graph, "cat", "dad", max_depth=2)
        self.assertFalse(by_depth.complete)
        self.assertEqual(by_depth.stop_reason, "max_depth")
        self.assertEqual(by_depth.paths, [["cat", "cad", "dad"]])

    def test_longest_simple_path_distinguishes_proven_and_best_found(self):
        graph = build_partition(["cat", "bat", "bad", "dad", "cad"])
        exact = longest_simple_path(graph, "cat", "dad")
        self.assertTrue(exact.complete)
        self.assertEqual(exact.path, ["cat", "bat", "bad", "cad", "dad"])

        limited = longest_simple_path(graph, "cat", "dad", max_states=5)
        self.assertFalse(limited.complete)
        self.assertEqual(limited.stop_reason, "max_states")
        self.assertEqual(limited.path, ["cat", "bat", "bad", "cad", "dad"])

    def test_bounded_path_search_validates_limits_and_unknown_nodes(self):
        graph = build_partition(["cat", "bat"])
        invalid_calls = [
            lambda: all_simple_paths(graph, "cat", "dog"),
            lambda: all_simple_paths(graph, "cat", "bat", max_paths=0),
            lambda: all_simple_paths(graph, "cat", "bat", max_states=0),
            lambda: longest_simple_path(graph, "cat", "bat", max_depth=-1),
            lambda: longest_simple_path(graph, "cat", "bat", timeout_seconds=0),
        ]
        for call in invalid_calls:
            with self.subTest(call=call):
                with self.assertRaises(ValueError):
                    call()

    def test_components_and_degrees(self):
        graph = build_partition(["cat", "bat", "cot", "dog"])
        self.assertEqual(components(graph), [["bat", "cat", "cot"], ["dog"]])
        self.assertEqual(nodes_by_degree(graph, 2), ["cat"])
        self.assertEqual(summary(graph), {"nodes": 4, "edges": 2, "components": 2,
                                        "isolated": ["dog"], "max_degree": 2,
                                        "highest_degree_nodes": ["cat"]})

    def test_k_core_peels_low_degree_nodes_recursively(self):
        graph = {
            "a": {"b", "c", "d"},
            "b": {"a", "c"},
            "c": {"a", "b"},
            "d": {"a", "e"},
            "e": {"d"},
            "z": set(),
        }
        original = {node: set(neighbors) for node, neighbors in graph.items()}
        self.assertEqual(k_core(graph, 2), {
            "a": {"b", "c"},
            "b": {"a", "c"},
            "c": {"a", "b"},
        })
        self.assertEqual(k_core(graph, 3), {})
        self.assertEqual(graph, original)

    def test_dense_subgraphs_are_k_core_regions_not_plain_components(self):
        graph = {
            "a": {"b", "c"}, "b": {"a", "c"}, "c": {"a", "b"},
            "d": {"e", "f"}, "e": {"d", "f"}, "f": {"d", "e", "g"},
            "g": {"f"},
        }
        self.assertEqual(len(components(graph)), 2)
        self.assertEqual(dense_subgraphs(graph, 2), [
            ["a", "b", "c"],
            ["d", "e", "f"],
        ])
        with self.assertRaises(ValueError):
            dense_subgraphs(graph, 0)
        with self.assertRaises(ValueError):
            k_core(graph, -1)

    def test_empty_summary(self):
        self.assertEqual(summary({})["highest_degree_nodes"], [])
        self.assertEqual(components({}), [])

    def test_invalid_partitions(self):
        for index, count in [(0, 0), (-1, 2), (2, 2)]:
            with self.assertRaises(ValueError):
                build_partition(["cat"], index, count)
        with self.assertRaises(ValueError):
            nodes_by_degree({}, -1)

    def test_cli_fixture(self):
        root = Path(__file__).resolve().parents[1]
        output = subprocess.check_output(
            [sys.executable, "-m", "graphword", str(root / "data/words3.txt"),
             "--partitions", "4", "--from", "cat", "--to", "dad"], cwd=root, text=True)
        result = json.loads(output)
        self.assertEqual(result["shortest_path"][0], "cat")
        self.assertEqual(result["shortest_path"][-1], "dad")
        self.assertEqual(result["execution"], "local-sequential")


if __name__ == "__main__":
    unittest.main()
