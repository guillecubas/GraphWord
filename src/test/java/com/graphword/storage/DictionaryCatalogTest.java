package com.graphword.storage;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class DictionaryCatalogTest {

    @Test
    void returnsAvailableDictionariesSortedByName() {
        DictionaryCatalog catalog = new DictionaryCatalog();

        assertThat(catalog.available())
                .extracting(DictionaryInfo::name)
                .containsExactly("words3", "words4");
    }

    @Test
    void returnsPathForKnownDictionaryAndRejectsUnknownOne() {
        DictionaryCatalog catalog = new DictionaryCatalog();

        assertThat(catalog.pathFor("words3")).isEqualTo("data/words3.txt");
        assertThat(catalog.pathFor("words4")).isEqualTo("data/words4.txt");
        assertThatThrownBy(() -> catalog.pathFor("words5"))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessage("Unknown dictionary: words5");
    }
}
