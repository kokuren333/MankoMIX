"""Local GUI server (`mankomix serve`, SPEC 3.3 / 11, gui/API.md). See app.py."""

from __future__ import annotations

from .app import MankoServer, is_loopback, parse_range, run_server

__all__ = ["MankoServer", "run_server", "is_loopback", "parse_range"]
