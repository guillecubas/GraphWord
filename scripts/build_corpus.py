"""Download pinned public dictionaries; preserve licenses and derive word lists."""
import hashlib
import json
from pathlib import Path
import re
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    "scowl": ("LibreOffice/dictionaries", "32b006a2c22a4ac7e8ed3f03346f7b3d85a970a4",
              ["en/en_US.dic", "en/en_US.aff", "en/README_en_US.txt"]),
    "cmu": ("cmusphinx/cmudict", "74790861f652b15e4ac49015a90074ad62a27690",
            ["cmudict.dict", "cmudict.symbols", "LICENSE"]),
}


def lexical_entries(text, forbidden_flag):
    result = set()
    for line in text.splitlines()[1:]:
        word, _, flags = line.partition("/")
        if re.fullmatch(r"[a-z]{3,8}", word) and forbidden_flag not in flags:
            result.add(word)
    return result


def pronounced_entries(text, symbols):
    result = set()
    for line in text.splitlines():
        fields = line.split("#", 1)[0].split()
        if len(fields) < 2:
            continue
        word = re.sub(r"\(\d+\)$", "", fields[0])
        phones = fields[1:]
        if (re.fullmatch(r"[a-z]{3,8}", word) and set(phones) <= symbols
                and any(re.fullmatch(r"[A-Z]+[012]", phone) for phone in phones)):
            result.add(word)
    return result


def main():
    output = ROOT / "data/curated"
    licenses = output / "licenses"
    licenses.mkdir(parents=True, exist_ok=True)
    loaded, manifest = {}, {"sources": {}, "outputs": {}, "rules_version": 1}
    for name, (repo, revision, paths) in SOURCES.items():
        manifest["sources"][name] = {"repository": repo, "revision": revision, "files": {}}
        for path in paths:
            url = f"https://raw.githubusercontent.com/{repo}/{revision}/{path}"
            with urllib.request.urlopen(url, timeout=60) as response:
                content = response.read()
            loaded[path] = content.decode("utf-8")
            manifest["sources"][name]["files"][path] = {"url": url, "sha256": hashlib.sha256(content).hexdigest()}
            if path.endswith(("LICENSE", "README_en_US.txt")):
                (licenses / (name + "-" + Path(path).name)).write_bytes(content)
    forbidden = re.search(r"^NOSUGGEST\s+(\S+)", loaded["en/en_US.aff"], re.M)
    if not forbidden:
        raise ValueError("Source no longer declares its NOSUGGEST flag; review filter")
    lexical = lexical_entries(loaded["en/en_US.dic"], forbidden[1])
    pronounced = pronounced_entries(loaded["cmudict.dict"], set(loaded["cmudict.symbols"].split()))
    combined = lexical & pronounced
    lists = {"scowl-base-words.txt": lexical, "cmu-pronounced-words.txt": pronounced}
    lists.update({f"words{length}.txt": {word for word in combined if len(word) == length} for length in range(3, 9)})
    for name, words in lists.items():
        content = ("\n".join(sorted(words)) + "\n").encode()
        (output / name).write_bytes(content)
        manifest["outputs"][name] = {"words": len(words), "sha256": hashlib.sha256(content).hexdigest()}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest["outputs"], indent=2))


if __name__ == "__main__":
    main()
