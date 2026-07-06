package com.graphword.storage;

import java.io.IOException;
import java.util.List;

public interface DictionaryStorage {

    List<String> load(String location) throws IOException;
}
