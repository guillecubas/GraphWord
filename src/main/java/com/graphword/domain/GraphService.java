package com.graphword.domain;

import org.springframework.stereotype.Service;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedList;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Queue;
import java.util.Set;
import java.util.TreeSet;

@Service
public class GraphService {

    private WordGraph graph = new WordGraph();
    private boolean loaded = false;

    public synchronized void buildGraph(List<String> words) {
        WordGraph newGraph = new WordGraph();
        List<String> cleanWords = words.stream()
                .map(this::normalizeWord)
                .filter(this::isValidWord)
                .distinct()
                .sorted()
                .toList();

        cleanWords.forEach(newGraph::addWord);

        for (int i = 0; i < cleanWords.size(); i++) {
            for (int j = i + 1; j < cleanWords.size(); j++) {
                String first = cleanWords.get(i);
                String second = cleanWords.get(j);
                if (hasOneLetterDifference(first, second)) {
                    newGraph.addEdge(first, second);
                }
            }
        }

        graph = newGraph;
        loaded = true;
    }

    public boolean hasOneLetterDifference(String first, String second) {
        if (first.length() != second.length()) {
            return false;
        }

        int differences = 0;
        for (int i = 0; i < first.length(); i++) {
            if (first.charAt(i) != second.charAt(i)) {
                differences++;
            }
        }
        return differences == 1;
    }

    public synchronized boolean isLoaded() {
        return loaded;
    }

    public synchronized void requireLoaded() {
        if (!loaded) {
            throw new IllegalStateException("Graph has not been loaded yet");
        }
    }

    public synchronized void requireNode(String word) {
        requireLoaded();
        String normalizedWord = normalizeWord(word);
        if (!graph.contains(normalizedWord)) {
            throw new IllegalArgumentException("Word does not exist in the graph: " + word);
        }
    }

    public synchronized GraphSummary summary() {
        requireLoaded();
        return new GraphSummary(graph.nodes().size(), graph.edgeCount(), clusters().size());
    }

    public synchronized List<String> shortestPath(String start, String end) {
        String normalizedStart = normalizeWord(start);
        String normalizedEnd = normalizeWord(end);
        requireNode(start);
        requireNode(end);

        Queue<String> queue = new ArrayDeque<>();
        Map<String, String> previous = new HashMap<>();
        Set<String> visited = new HashSet<>();

        queue.add(normalizedStart);
        visited.add(normalizedStart);

        while (!queue.isEmpty()) {
            String current = queue.poll();
            if (current.equals(normalizedEnd)) {
                return reconstructPath(previous, normalizedStart, normalizedEnd);
            }

            for (String neighbor : graph.neighbors(current)) {
                if (visited.add(neighbor)) {
                    previous.put(neighbor, current);
                    queue.add(neighbor);
                }
            }
        }

        return List.of();
    }

    public synchronized List<List<String>> allPaths(String start, String end, int limit) {
        String normalizedStart = normalizeWord(start);
        String normalizedEnd = normalizeWord(end);
        requireNode(start);
        requireNode(end);
        if (limit <= 0) {
            throw new IllegalArgumentException("Limit must be greater than zero");
        }

        List<List<String>> results = new ArrayList<>();
        LinkedList<String> currentPath = new LinkedList<>();
        Set<String> visited = new HashSet<>();
        collectPaths(normalizedStart, normalizedEnd, limit, visited, currentPath, results);
        return results;
    }

    public synchronized List<String> longestPath(String start, String end, int limit) {
        String normalizedStart = normalizeWord(start);
        String normalizedEnd = normalizeWord(end);
        requireNode(start);
        requireNode(end);
        if (limit <= 0) {
            throw new IllegalArgumentException("Limit must be greater than zero");
        }

        SearchState state = new SearchState(limit);
        collectLongestPath(normalizedStart, normalizedEnd, new HashSet<>(), new LinkedList<>(), state);
        return state.bestPath;
    }

    public synchronized List<String> isolatedNodes() {
        requireLoaded();
        return graph.nodes().stream()
                .filter(node -> graph.degree(node) == 0)
                .sorted()
                .toList();
    }

    public synchronized List<String> nodesWithDegree(int degree) {
        requireLoaded();
        return graph.nodes().stream()
                .filter(node -> graph.degree(node) == degree)
                .sorted()
                .toList();
    }

    public synchronized List<String> highestDegreeNodes() {
        requireLoaded();
        int maxDegree = graph.nodes().stream()
                .mapToInt(graph::degree)
                .max()
                .orElse(0);
        return nodesWithDegree(maxDegree);
    }

    public synchronized List<Set<String>> clusters() {
        requireLoaded();
        List<Set<String>> clusters = new ArrayList<>();
        Set<String> visited = new HashSet<>();

        for (String node : new TreeSet<>(graph.nodes())) {
            if (!visited.contains(node)) {
                Set<String> cluster = new TreeSet<>();
                exploreCluster(node, visited, cluster);
                clusters.add(cluster);
            }
        }

        clusters.sort(Comparator.comparing(cluster -> cluster.iterator().next()));
        return clusters;
    }

    public synchronized WordGraph graph() {
        requireLoaded();
        return graph.copy();
    }

    private String normalizeWord(String word) {
        return word.trim().toLowerCase(Locale.ROOT);
    }

    private boolean isValidWord(String word) {
        return word.matches("[a-z]+") && word.matches(".*[aeiou].*");
    }

    private List<String> reconstructPath(Map<String, String> previous, String start, String end) {
        LinkedList<String> path = new LinkedList<>();
        String current = end;
        while (current != null) {
            path.addFirst(current);
            current = previous.get(current);
        }
        return path.getFirst().equals(start) ? path : List.of();
    }

    private void collectPaths(
            String current,
            String end,
            int limit,
            Set<String> visited,
            LinkedList<String> currentPath,
            List<List<String>> results
    ) {
        if (results.size() >= limit) {
            return;
        }

        visited.add(current);
        currentPath.add(current);

        if (current.equals(end)) {
            results.add(List.copyOf(currentPath));
        } else {
            for (String neighbor : graph.neighbors(current)) {
                if (!visited.contains(neighbor)) {
                    collectPaths(neighbor, end, limit, visited, currentPath, results);
                }
            }
        }

        currentPath.removeLast();
        visited.remove(current);
    }

    private void collectLongestPath(
            String current,
            String end,
            Set<String> visited,
            LinkedList<String> currentPath,
            SearchState state
    ) {
        if (state.exploredPaths >= state.limit) {
            return;
        }

        visited.add(current);
        currentPath.add(current);

        if (current.equals(end)) {
            state.exploredPaths++;
            if (currentPath.size() > state.bestPath.size()) {
                state.bestPath = List.copyOf(currentPath);
            }
        } else {
            for (String neighbor : graph.neighbors(current)) {
                if (!visited.contains(neighbor)) {
                    collectLongestPath(neighbor, end, visited, currentPath, state);
                }
            }
        }

        currentPath.removeLast();
        visited.remove(current);
    }

    private void exploreCluster(String node, Set<String> visited, Set<String> cluster) {
        visited.add(node);
        cluster.add(node);

        for (String neighbor : graph.neighbors(node)) {
            if (!visited.contains(neighbor)) {
                exploreCluster(neighbor, visited, cluster);
            }
        }
    }

    private static class SearchState {
        private final int limit;
        private int exploredPaths;
        private List<String> bestPath = List.of();

        private SearchState(int limit) {
            this.limit = limit;
        }
    }
}
