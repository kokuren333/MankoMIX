"""Content hashing helpers (SPEC 9.1, 9.6).

Assets are identified by the sha256 of their bytes; project states are
identified by the sha256 of their canonical JSON form.
"""

from __future__ import annotations

import hashlib
import json
from os import PathLike
from typing import Any

_CHUNK = 1 << 20


def sha256_file(path: str | PathLike[str]) -> str:
    """Streaming sha256 of a file, as 64 lowercase hex characters."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(_CHUNK)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(obj: Any) -> str:
    """Canonical JSON text: sorted keys, no whitespace, UTF-8 characters kept, no NaN."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def canonical_hash(obj: Any) -> str:
    """sha256 (hex) of the canonical JSON form of ``obj``."""
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()
