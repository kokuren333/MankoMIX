"""Source adapter contract (docs/SPEC.md 6.1).

An adapter brings source material into a project without altering it
(A-7, A-12). v1 ships only the file adapter; external services (for example a
Suno MCP connector) can be added later as further adapters without the core
depending on them (A-10).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..errors import InputError


class SourceAdapter(ABC):
    """Contract every input adapter implements.

    probe(src)  -> summary of what would be imported (never writes anything)
    fetch(src, project, mode=..., provenance=...) -> import record; copies (or
                links) the material into the project and records it.
    """

    id: str = ""

    @abstractmethod
    def probe(self, src: Any) -> dict:
        raise NotImplementedError

    @abstractmethod
    def fetch(self, src: Any, project: Any, *, mode: str = "copy",
              provenance: dict | None = None, **kwargs: Any) -> dict:
        raise NotImplementedError


_REGISTRY: dict[str, type[SourceAdapter]] = {}


def register_adapter(cls: type[SourceAdapter]) -> type[SourceAdapter]:
    """Register an adapter class under its ``id`` (usable as a decorator)."""
    if not getattr(cls, "id", ""):
        raise ValueError("adapter class needs a non-empty 'id'")
    _REGISTRY[cls.id] = cls
    return cls


def get_adapter(adapter_id: str = "file") -> SourceAdapter:
    """Return a new instance of the adapter registered as ``adapter_id``."""
    try:
        return _REGISTRY[adapter_id]()
    except KeyError:
        raise InputError(f"unknown source adapter: {adapter_id!r}",
                         details={"available": sorted(_REGISTRY)}) from None


def available_adapters() -> list[str]:
    return sorted(_REGISTRY)
