package com.graphword.domain;

import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class GraphServiceTest {

    @Test
    void detectsOneLetterDifference() {
        GraphService service = new GraphService();

        assertThat(service.hasOneLetterDifference("cat", "bat")).isTrue();
        assertThat(service.hasOneLetterDifference("dig", "dog")).isTrue();
        assertThat(service.hasOneLetterDifference("cat", "dog")).isFalse();
        assertThat(service.hasOneLetterDifference("cat", "cats")).isFalse();
        assertThat(service.hasOneLetterDifference("cat", "cat")).isFalse();
    }

    @Test
    void buildsGraphWithExpectedNodesAndEdges() {
        GraphService service = new GraphService();

        service.buildGraph(List.of("cat", "bat", "bad", "dad", "dog"));

        GraphSummary summary = service.summary();
        assertThat(summary.nodes()).isEqualTo(5);
        assertThat(summary.edges()).isEqualTo(3);
        assertThat(summary.components()).isEqualTo(2);
    }

    @Test
    void findsShortestPathWithBreadthFirstSearch() {
        GraphService service = new GraphService();
        service.buildGraph(List.of("cat", "bat", "bad", "dad"));

        List<String> path = service.shortestPath("cat", "dad");

        assertThat(path).containsExactly("cat", "bat", "bad", "dad");
    }

    @Test
    void normalizesQueryWordsForShortestPath() {
        GraphService service = new GraphService();
        service.buildGraph(List.of("cat", "bat", "bad", "dad"));

        List<String> path = service.shortestPath(" CAT ", "DAD");

        assertThat(path).containsExactly("cat", "bat", "bad", "dad");
    }

    @Test
    void returnsEmptyShortestPathWhenNodesAreDisconnected() {
        GraphService service = new GraphService();
        service.buildGraph(List.of("cat", "bat", "dog"));

        List<String> path = service.shortestPath("cat", "dog");

        assertThat(path).isEmpty();
    }

    @Test
    void findsAllSimplePathsUpToLimit() {
        GraphService service = new GraphService();
        service.buildGraph(List.of("cat", "bat", "cot", "bot", "bog", "dog", "dot"));

        List<List<String>> paths = service.allPaths("cat", "dog", 3);

        assertThat(paths).hasSize(3);
        assertThat(paths).allSatisfy(path -> {
            assertThat(path.getFirst()).isEqualTo("cat");
            assertThat(path.getLast()).isEqualTo("dog");
        });
    }

    @Test
    void findsLongestSimplePathBetweenTwoNodes() {
        GraphService service = new GraphService();
        service.buildGraph(List.of("cat", "bat", "bad", "dad", "cad", "cot"));

        List<String> path = service.longestPath("cat", "dad", 100);

        assertThat(path).containsExactly("cat", "bat", "bad", "cad", "dad");
    }

    @Test
    void rejectsInvalidAllPathsLimit() {
        GraphService service = new GraphService();
        service.buildGraph(List.of("cat", "bat"));

        assertThatThrownBy(() -> service.allPaths("cat", "bat", 0))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void rejectsInvalidLongestPathLimit() {
        GraphService service = new GraphService();
        service.buildGraph(List.of("cat", "bat"));

        assertThatThrownBy(() -> service.longestPath("cat", "bat", 0))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void filtersInvalidWordsWhenBuildingGraph() {
        GraphService service = new GraphService();

        service.buildGraph(List.of("Cat", "b4t", "rhythms", "DOG!", "", "bat", "cat"));

        GraphSummary summary = service.summary();
        assertThat(summary.nodes()).isEqualTo(2);
        assertThat(service.graph().nodes()).containsExactlyInAnyOrder("bat", "cat");
    }

    @Test
    void rejectsUnknownWords() {
        GraphService service = new GraphService();
        service.buildGraph(List.of("cat", "bat"));

        assertThatThrownBy(() -> service.shortestPath("cat", "dog"))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void findsIsolatedNodes() {
        GraphService service = new GraphService();
        service.buildGraph(List.of("cat", "bat", "dog"));

        assertThat(service.isolatedNodes()).containsExactly("dog");
    }

    @Test
    void findsNodesByDegreeAndHighestDegree() {
        GraphService service = new GraphService();
        service.buildGraph(List.of("cat", "bat", "cot", "mat", "dog"));

        assertThat(service.nodesWithDegree(3)).containsExactly("cat");
        assertThat(service.highestDegreeNodes()).containsExactly("cat");
    }

    @Test
    void findsConnectedComponents() {
        GraphService service = new GraphService();
        service.buildGraph(List.of("cat", "bat", "dog", "dig"));

        List<Set<String>> clusters = service.clusters();

        assertThat(clusters).containsExactlyInAnyOrder(Set.of("cat", "bat"), Set.of("dig", "dog"));
    }

    @Test
    void graphReturnsSnapshot() {
        GraphService service = new GraphService();
        service.buildGraph(List.of("cat", "bat"));

        WordGraph snapshot = service.graph();
        snapshot.addWord("dog");

        assertThat(service.summary().nodes()).isEqualTo(2);
    }
}
