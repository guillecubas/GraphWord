"""Stable identities for retried HTTP submissions, scoped to operation type."""
from hashlib import sha256
import json
from uuid import NAMESPACE_URL, uuid5
from graphword.graph import normalize_words


class IdempotencyConflict(ValueError):
    """The same key was reused with a different request."""


def submission_identity(kind, payload, attempts, key):
    if key is None:
        return None, None
    if not 1 <= len(key) <= 128 or any(not 33 <= ord(char) <= 126 for char in key):
        raise ValueError("idempotency key must contain 1..128 visible ASCII characters")
    canonical = dict(payload)
    if "words" in canonical:
        canonical["words"] = normalize_words(canonical["words"])
    encoded = json.dumps([str(kind), canonical, attempts], sort_keys=True, separators=(",", ":"))
    return uuid5(NAMESPACE_URL, f"graphword:v1:{kind}:{key}"), sha256(encoded.encode()).hexdigest()


def require_same_request(actual, expected):
    if actual != expected:
        raise IdempotencyConflict("idempotency key already used with different input")
