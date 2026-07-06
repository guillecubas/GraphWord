package com.graphword.api;

import com.graphword.domain.GraphService;
import com.graphword.domain.GraphSummary;
import com.graphword.storage.DictionaryCatalog;
import com.graphword.storage.DictionaryInfo;
import com.graphword.storage.DictionaryStorage;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.io.IOException;
import java.util.List;
import java.util.Map;
import java.util.Set;

@RestController
@RequestMapping
public class GraphController {

    private final GraphService graphService;
    private final DictionaryStorage dictionaryStorage;
    private final DictionaryCatalog dictionaryCatalog;

    public GraphController(
            GraphService graphService,
            DictionaryStorage dictionaryStorage,
            DictionaryCatalog dictionaryCatalog
    ) {
        this.graphService = graphService;
        this.dictionaryStorage = dictionaryStorage;
        this.dictionaryCatalog = dictionaryCatalog;
    }

    @GetMapping("/health")
    public Map<String, String> health() {
        return Map.of("status", "UP");
    }

    @GetMapping("/dictionaries")
    public List<DictionaryInfo> dictionaries() {
        return dictionaryCatalog.available();
    }

    @PostMapping("/graph/load")
    public Map<String, String> loadGraph(
            @RequestParam(name = "dictionary", defaultValue = "words3") String dictionary
    ) throws IOException {
        String dictionaryPath = dictionaryCatalog.pathFor(dictionary);
        List<String> words = dictionaryStorage.load(dictionaryPath);
        graphService.buildGraph(words);
        return Map.of("message", "Graph loaded successfully", "dictionary", dictionary);
    }

    @GetMapping("/graph/summary")
    public GraphSummary summary() {
        return graphService.summary();
    }

    @GetMapping("/graph/shortest")
    public List<String> shortestPath(@RequestParam("from") String from, @RequestParam("to") String to) {
        return graphService.shortestPath(from, to);
    }

    @GetMapping("/graph/paths")
    public List<List<String>> paths(
            @RequestParam("from") String from,
            @RequestParam("to") String to,
            @RequestParam(name = "limit", defaultValue = "20") int limit
    ) {
        return graphService.allPaths(from, to, limit);
    }

    @GetMapping("/graph/longest-path")
    public List<String> longestPath(
            @RequestParam("from") String from,
            @RequestParam("to") String to,
            @RequestParam(name = "limit", defaultValue = "1000") int limit
    ) {
        return graphService.longestPath(from, to, limit);
    }

    @GetMapping("/graph/isolated")
    public List<String> isolatedNodes() {
        return graphService.isolatedNodes();
    }

    @GetMapping("/graph/degree/{degree}")
    public List<String> nodesWithDegree(@PathVariable("degree") int degree) {
        return graphService.nodesWithDegree(degree);
    }

    @GetMapping("/graph/highest-degree")
    public List<String> highestDegreeNodes() {
        return graphService.highestDegreeNodes();
    }

    @GetMapping("/graph/clusters")
    public List<Set<String>> clusters() {
        return graphService.clusters();
    }
}
