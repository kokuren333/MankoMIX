"""Compatibility shim: ``knowledge_lookup`` now lives in the core (core/knowledge.py).

The MCP tool ``knowledge_lookup`` wraps ``core.api.knowledge_lookup`` like every
other tool (SPEC 10.1); this module only keeps the old import path working.
"""

from __future__ import annotations

from mankomix.core.knowledge import KINDS, knowledge_lookup

__all__ = ["KINDS", "knowledge_lookup"]
