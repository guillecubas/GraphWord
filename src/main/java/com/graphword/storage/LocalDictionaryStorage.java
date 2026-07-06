package com.graphword.storage;

import org.springframework.stereotype.Component;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Locale;

@Component
public class LocalDictionaryStorage implements DictionaryStorage {

    @Override
    public List<String> load(String location) throws IOException {
        return Files.readAllLines(Path.of(location)).stream()
                .map(String::trim)
                .map(word -> word.toLowerCase(Locale.ROOT))
                .filter(this::isValidWord)
                .distinct()
                .toList();
    }

    private boolean isValidWord(String word) {
        return word.matches("[a-z]+") && word.matches(".*[aeiou].*");
    }
}
