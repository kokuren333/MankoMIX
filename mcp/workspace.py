"""Workspace restriction for the MCP server (SPEC 10.3).

The server is started with one root folder. Every path an agent passes in is
resolved against that root and must stay inside it: ``..`` escapes, absolute
paths outside the root, drive-relative Windows paths and symlink/junction
escapes are rejected. Results are scrubbed so that no absolute path leaves
the server.
"""

from __future__ import annotations

import os
from pathlib import Path, PurePath
from typing import Any

from mankomix.core import api
from mankomix.core.errors import InputError


class PathEscape(InputError):
    code = "path_outside_workspace"


class Workspace:
    def __init__(self, root: str | os.PathLike[str]):
        try:
            r = Path(root).resolve(strict=True)
        except (OSError, RuntimeError):
            raise InputError(f"workspace root not found: {Path(root).name or str(root)}") from None
        if not r.is_dir():
            raise InputError(f"workspace root is not a folder: {r.name}")
        self.root = r

    # -- input paths ---------------------------------------------------------

    def resolve(self, value: Any, *, what: str = "path") -> Path:
        """Resolve a user-supplied path inside the workspace or raise PathEscape."""
        if isinstance(value, PurePath):
            value = str(value)
        if not isinstance(value, str) or not value.strip():
            raise InputError(f"{what} must be a non-empty string")
        if "\x00" in value:
            raise InputError(f"{what} contains a NUL character")
        p = Path(value)
        if p.is_absolute():
            cand = p
        elif p.drive or p.root:
            # Windows "C:foo" (drive-relative) or "\foo" (root of the current drive).
            raise PathEscape(f"{what} must be relative to the workspace: {self._safe(value)}")
        else:
            cand = self.root / p
        try:
            resolved = cand.resolve(strict=False)   # follows symlinks / junctions that exist
        except (OSError, RuntimeError, ValueError):
            raise PathEscape(f"{what} cannot be resolved: {self._safe(value)}") from None
        if resolved != self.root and not resolved.is_relative_to(self.root):
            raise PathEscape(f"{what} is outside the workspace: {self._safe(value)}",
                             details={"hint": "paths are relative to the folder the server was started with"})
        return resolved

    def rel(self, p: str | os.PathLike[str]) -> str:
        """Workspace-relative POSIX form of a path inside the root ('.' for the root)."""
        rp = Path(p).resolve(strict=False)
        try:
            out = rp.relative_to(self.root).as_posix()
        except ValueError:
            return rp.name
        return out or "."

    @staticmethod
    def _safe(value: str) -> str:
        """Echo a rejected path without leaking an absolute location."""
        p = Path(value)
        if p.is_absolute() or p.drive or p.root:
            return f"<absolute path ...{p.name}>" if p.name else "<absolute path>"
        return value

    # -- output scrubbing ----------------------------------------------------

    def scrub(self, obj: Any) -> Any:
        """Replace absolute paths in a result by workspace-relative ones (or bare names)."""
        roots = api._known_roots(self.root)
        return api._scrub(obj, roots)
