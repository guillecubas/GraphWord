package com.graphword.storage;

import org.springframework.stereotype.Component;

import java.util.List;
import java.util.Map;

@Component
public class DictionaryCatalog {

    private final Map<String, DictionaryInfo> dictionaries = Map.of(
            "words3", new DictionaryInfo("words3", "data/words3.txt", 3),
            "words4", new DictionaryInfo("words4", "data/words4.txt", 4)
    );

    public List<DictionaryInfo> available() {
        return dictionaries.values().stream()
                .sorted((first, second) -> first.name().compareTo(second.name()))
                .toList();
    }

    public String pathFor(String name) {
        DictionaryInfo dictionary = dictionaries.get(name);
        if (dictionary == null) {
            throw new IllegalArgumentException("Unknown dictionary: " + name);
        }
        return dictionary.path();
    }
}
