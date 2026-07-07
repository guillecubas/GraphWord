package com.graphword.api;

import com.graphword.domain.GraphSummary;
import com.graphword.domain.GraphService;
import com.graphword.storage.DictionaryCatalog;
import com.graphword.storage.DictionaryInfo;
import com.graphword.storage.DictionaryStorage;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.test.web.servlet.MockMvc;

import java.io.IOException;
import java.util.List;
import java.util.Set;

import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest({GraphController.class, ApiExceptionHandler.class})
class GraphControllerTest {

    @Autowired
    MockMvc mockMvc;

    @MockBean
    GraphService graphService;

    @MockBean
    DictionaryStorage dictionaryStorage;

    @MockBean
    DictionaryCatalog dictionaryCatalog;

    @Test
    void healthReturnsOk() throws Exception {
        mockMvc.perform(get("/health"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("UP"));
    }

    @Test
    void loadBuildsGraphFromLocalDictionary() throws Exception {
        when(dictionaryStorage.load(anyString())).thenReturn(List.of("cat", "bat"));
        when(dictionaryCatalog.pathFor("words3")).thenReturn("test-data/words.txt");

        mockMvc.perform(post("/graph/load"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.message").value("Graph loaded successfully"));

        verify(dictionaryStorage).load("test-data/words.txt");
        verify(graphService).buildGraph(List.of("cat", "bat"));
    }

    @Test
    void loadBuildsGraphFromSelectedDictionary() throws Exception {
        when(dictionaryCatalog.pathFor("words4")).thenReturn("data/words4.txt");
        when(dictionaryStorage.load("data/words4.txt")).thenReturn(List.of("cold", "cord", "card"));

        mockMvc.perform(post("/graph/load").param("dictionary", "words4"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.dictionary").value("words4"))
                .andExpect(jsonPath("$.message").value("Graph loaded successfully"));

        verify(dictionaryStorage).load("data/words4.txt");
        verify(graphService).buildGraph(List.of("cold", "cord", "card"));
    }

    @Test
    void dictionariesReturnsAvailableDictionaryCatalog() throws Exception {
        when(dictionaryCatalog.available()).thenReturn(List.of(
                new DictionaryInfo("words3", "data/words3.txt", 3),
                new DictionaryInfo("words4", "data/words4.txt", 4)
        ));

        mockMvc.perform(get("/dictionaries"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].name").value("words3"))
                .andExpect(jsonPath("$[1].wordLength").value(4));
    }

    @Test
    void dictionaryReadFailureReturnsServerError() throws Exception {
        when(dictionaryCatalog.pathFor("words3")).thenReturn("test-data/words.txt");
        when(dictionaryStorage.load(anyString())).thenThrow(new IOException("missing file"));

        mockMvc.perform(post("/graph/load"))
                .andExpect(status().isInternalServerError())
                .andExpect(jsonPath("$.message").value("Could not read dictionary: missing file"));
    }

    @Test
    void summaryReturnsGraphSummary() throws Exception {
        when(graphService.summary()).thenReturn(new GraphSummary(2, 1, 1));

        mockMvc.perform(get("/graph/summary"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.nodes").value(2))
                .andExpect(jsonPath("$.edges").value(1))
                .andExpect(jsonPath("$.components").value(1));
    }

    @Test
    void unloadedGraphReturnsBadRequest() throws Exception {
        when(graphService.summary()).thenThrow(new IllegalStateException("Graph has not been loaded yet"));

        mockMvc.perform(get("/graph/summary"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.message").value("Graph has not been loaded yet"));
    }

    @Test
    void shortestPathReturnsPath() throws Exception {
        when(graphService.shortestPath("cat", "dad")).thenReturn(List.of("cat", "bat", "bad", "dad"));

        mockMvc.perform(get("/graph/shortest").param("from", "cat").param("to", "dad"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0]").value("cat"))
                .andExpect(jsonPath("$[3]").value("dad"));
    }

    @Test
    void missingWordReturnsNotFound() throws Exception {
        when(graphService.shortestPath("cat", "zzz"))
                .thenThrow(new IllegalArgumentException("Word does not exist in the graph: zzz"));

        mockMvc.perform(get("/graph/shortest").param("from", "cat").param("to", "zzz"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.message").value("Word does not exist in the graph: zzz"));
    }

    @Test
    void pathsUsesDefaultLimit() throws Exception {
        when(graphService.allPaths("cat", "dad", 20))
                .thenReturn(List.of(List.of("cat", "bat", "bad", "dad")));

        mockMvc.perform(get("/graph/paths").param("from", "cat").param("to", "dad"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0][0]").value("cat"))
                .andExpect(jsonPath("$[0][3]").value("dad"));

        verify(graphService).allPaths("cat", "dad", 20);
    }

    @Test
    void pathsRejectsInvalidLimit() throws Exception {
        doAnswer(invocation -> {
            throw new IllegalArgumentException("Limit must be greater than zero");
        }).when(graphService).allPaths("cat", "dad", 0);

        mockMvc.perform(get("/graph/paths").param("from", "cat").param("to", "dad").param("limit", "0"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.message").value("Limit must be greater than zero"));
    }

    @Test
    void longestPathReturnsPath() throws Exception {
        when(graphService.longestPath("cat", "dad", 1000))
                .thenReturn(List.of("cat", "bat", "bad", "cad", "dad"));

        mockMvc.perform(get("/graph/longest-path").param("from", "cat").param("to", "dad"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0]").value("cat"))
                .andExpect(jsonPath("$[4]").value("dad"));

        verify(graphService).longestPath("cat", "dad", 1000);
    }

    @Test
    void isolatedReturnsIsolatedNodes() throws Exception {
        when(graphService.isolatedNodes()).thenReturn(List.of("dog"));

        mockMvc.perform(get("/graph/isolated"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0]").value("dog"));
    }

    @Test
    void degreeReturnsNodesWithRequestedDegree() throws Exception {
        when(graphService.nodesWithDegree(3)).thenReturn(List.of("cat"));

        mockMvc.perform(get("/graph/degree/3"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0]").value("cat"));

        verify(graphService).nodesWithDegree(3);
    }

    @Test
    void highestDegreeReturnsMostConnectedNodes() throws Exception {
        when(graphService.highestDegreeNodes()).thenReturn(List.of("cat", "bat"));

        mockMvc.perform(get("/graph/highest-degree"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0]").value("cat"))
                .andExpect(jsonPath("$[1]").value("bat"));
    }

    @Test
    void clustersReturnsComponents() throws Exception {
        when(graphService.clusters()).thenReturn(List.of(Set.of("cat", "bat"), Set.of("dog", "dig")));

        mockMvc.perform(get("/graph/clusters"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].length()").value(2));
    }
}
