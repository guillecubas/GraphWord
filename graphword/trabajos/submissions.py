"""Reconocer peticiones repetidas mediante claves y huellas digitales estables."""
from hashlib import sha256
import json
from uuid import NAMESPACE_URL, uuid5
from graphword.motor.graph import normalize_words


class IdempotencyConflict(ValueError):
    """La misma clave se ha utilizado con datos distintos."""


def submission_identity(kind, payload, attempts, key):
    if key is None:
        return None, None
    # Rechazar claves vacías, demasiado largas o con caracteres no visibles.
    invalid_key = not 1 <= len(key) <= 128
    if not invalid_key:
        for char in key:
            if not 33 <= ord(char) <= 126:
                invalid_key = True
                break
    if invalid_key:
        raise ValueError("idempotency key must contain 1..128 visible ASCII characters")
    # Ordenar y normalizar permite reconocer la misma petición repetida.
    canonical = dict(payload)
    if "words" in canonical:
        canonical["words"] = normalize_words(canonical["words"])
    encoded = json.dumps([str(kind), canonical, attempts], sort_keys=True, separators=(",", ":"))
    submission_id = uuid5(NAMESPACE_URL, f"graphword:v1:{kind}:{key}")
    request_hash = sha256(encoded.encode()).hexdigest()
    return submission_id, request_hash


def require_same_request(actual, expected):
    if actual != expected:
        raise IdempotencyConflict("idempotency key already used with different input")
