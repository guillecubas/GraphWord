package com.graphword.storage;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

class LocalDictionaryStorageTest {

    @TempDir
    Path tempDir;

    @Test
    void loadsAndNormalizesWordsFromFile() throws Exception {
        Path dictionary = tempDir.resolve("words.txt");
        Files.write(dictionary, List.of("Cat", " bat ", "", "CAT", "dog", "b4t", "DOG!", "rhythms"));
        LocalDictionaryStorage storage = new LocalDictionaryStorage();

        List<String> words = storage.load(dictionary.toString());

        assertThat(words).containsExactly("cat", "bat", "dog");
    }
}
