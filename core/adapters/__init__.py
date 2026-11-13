"""Source adapters (docs/SPEC.md 6.1). v1 implements only the file adapter."""

from __future__ import annotations

from .base import SourceAdapter, available_adapters, get_adapter, register_adapter
from .file import FileAdapter

__all__ = ["SourceAdapter", "FileAdapter", "get_adapter", "register_adapter", "available_adapters"]
