package com.graphword.domain;

import org.junit.jupiter.api.Test;

import java.util.Map;
import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class WordGraphTest {

    @Test
    void addEdgeCreatesBidirectionalConnectionAndCountsItOnce() {
        WordGraph graph = new WordGraph();

        graph.addEdge("cat", "bat");

        assertThat(graph.neighbors("cat")).containsExactly("bat");
        assertThat(graph.neighbors("bat")).containsExactly("cat");
        assertThat(graph.edgeCount()).isEqualTo(1);
    }

    @Test
    void returnsEmptyNeighborsForUnknownWord() {
        WordGraph graph = new WordGraph();

        assertThat(graph.neighbors("missing")).isEmpty();
        assertThat(graph.degree("missing")).isZero();
    }

    @Test
    void exposesImmutableSnapshots() {
        WordGraph graph = new WordGraph();
        graph.addEdge("cat", "bat");

        Set<String> nodes = graph.nodes();
        Set<String> neighbors = graph.neighbors("cat");
        Map<String, Set<String>> adjacency = graph.adjacency();

        assertThatThrownBy(() -> nodes.add("dog"))
                .isInstanceOf(UnsupportedOperationException.class);
        assertThatThrownBy(() -> neighbors.add("dog"))
                .isInstanceOf(UnsupportedOperationException.class);
        assertThatThrownBy(() -> adjacency.put("dog", Set.of()))
                .isInstanceOf(UnsupportedOperationException.class);
        assertThatThrownBy(() -> adjacency.get("cat").add("dog"))
                .isInstanceOf(UnsupportedOperationException.class);
    }
}
