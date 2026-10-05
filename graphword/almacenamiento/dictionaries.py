"""Metadatos de diccionarios y publicación reproducible del catálogo en S3."""
from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Protocol


class DictionaryNotFoundError(KeyError):
    pass


class InvalidDictionaryError(ValueError):
    pass


class DictionaryUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class DictionaryInfo:
    dictionary_id: str
    word_length: int
    word_count: int
    sha256: str
    s3_key: str


class DictionaryRepository(Protocol):
    def list(self) -> list[DictionaryInfo]:
        # El adaptador concreto implementa esta operación.
        pass

    def load(self, dictionary_id: str) -> tuple[DictionaryInfo, list[str]]:
        # El adaptador concreto implementa esta operación.
        pass


def publish_dictionaries(client, bucket: str, folder: Path) -> str:
    """Validar los archivos antes de subirlos y fijar el catálogo por su contenido.

    El catálogo se publica al final para que no apunte a archivos sin subir.
    Los despliegues existentes conservan su propia versión del catálogo.
    """
    # El manifiesto fija los tamaños y las huellas digitales esperadas.
    manifest_bytes = (folder / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    prefix = "dictionaries/curated/" + sha256(manifest_bytes).hexdigest() + "/"
    files = []
    entries = []
    for length in range(3, 9):
        name = f"words{length}.txt"
        content = (folder / name).read_bytes()
        expected = manifest["outputs"][name]
        words = content.decode("utf-8").splitlines()
        # Comprobar la integridad antes de subir cualquier archivo a S3.
        invalid_content = (
            sha256(content).hexdigest() != expected["sha256"]
            or len(words) != expected["words"]
            or words != sorted(set(words))
        )
        if not invalid_content:
            for word in words:
                if (
                    len(word) != length
                    or not word.isascii()
                    or not word.isalpha()
                    or not word.islower()
                ):
                    invalid_content = True
                    break
        if invalid_content:
            raise InvalidDictionaryError(f"Corpus does not match manifest: {name}")
        files.append((prefix + name, content, "text/plain; charset=utf-8"))
        entry = {
            "dictionary_id": f"words{length}",
            "word_length": length,
            "word_count": len(words),
            "sha256": expected["sha256"],
            "s3_key": prefix + name,
        }
        entries.append(entry)
    files.append((prefix + "manifest.json", manifest_bytes, "application/json"))
    # Conservar las licencias de las fuentes junto a los diccionarios derivados.
    for path in sorted((folder / "licenses").glob("*")):
        files.append((prefix + "licenses/" + path.name, path.read_bytes(), "text/plain; charset=utf-8"))
    for key, content, mime in files:
        client.put_object(Bucket=bucket, Key=key, Body=content, ContentType=mime,
                          ServerSideEncryption="AES256")
    # Publicar el catálogo al final: todos sus archivos ya deben existir.
    key = prefix + "catalog.json"
    client.put_object(Bucket=bucket, Key=key,
        Body=json.dumps({"schema_version": 1, "dictionaries": entries,
                         "manifest_key": prefix + "manifest.json"}, sort_keys=True).encode(),
        ContentType="application/json", ServerSideEncryption="AES256")
    return key
