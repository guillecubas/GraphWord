import json
import os
from pathlib import Path
import random
import subprocess
import sys
import unittest

from graphword.graph import (
    build_partition, components, merge_partitions, nodes_by_degree,
    normalize_words, partition_for, shortest_path, summary,
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

    def test_components_and_degrees(self):
        graph = build_partition(["cat", "bat", "cot", "dog"])
        self.assertEqual(components(graph), [["bat", "cat", "cot"], ["dog"]])
        self.assertEqual(nodes_by_degree(graph, 2), ["cat"])
        self.assertEqual(summary(graph), {"nodes": 4, "edges": 2, "components": 2,
                                        "isolated": ["dog"], "max_degree": 2,
                                        "highest_degree_nodes": ["cat"]})

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
