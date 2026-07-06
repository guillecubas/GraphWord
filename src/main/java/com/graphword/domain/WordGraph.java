package com.graphword.domain;

import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;

public class WordGraph {

    private final Map<String, Set<String>> adjacency = new HashMap<>();

    public void addWord(String word) {
        adjacency.putIfAbsent(word, new TreeSet<>());
    }

    public void addEdge(String first, String second) {
        addWord(first);
        addWord(second);
        adjacency.get(first).add(second);
        adjacency.get(second).add(first);
    }

    public Set<String> nodes() {
        return Collections.unmodifiableSet(adjacency.keySet());
    }

    public Set<String> neighbors(String word) {
        return Collections.unmodifiableSet(adjacency.getOrDefault(word, Set.of()));
    }

    public boolean contains(String word) {
        return adjacency.containsKey(word);
    }

    public int degree(String word) {
        return neighbors(word).size();
    }

    public int edgeCount() {
        int totalDegrees = adjacency.values().stream().mapToInt(Set::size).sum();
        return totalDegrees / 2;
    }

    public WordGraph copy() {
        WordGraph copy = new WordGraph();
        adjacency.forEach((word, neighbors) -> copy.adjacency.put(word, new TreeSet<>(neighbors)));
        return copy;
    }

    public Map<String, Set<String>> adjacency() {
        Map<String, Set<String>> copy = new HashMap<>();
        adjacency.forEach((word, neighbors) -> copy.put(word, Collections.unmodifiableSet(new HashSet<>(neighbors))));
        return Collections.unmodifiableMap(copy);
    }
}
