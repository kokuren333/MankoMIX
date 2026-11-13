"""MankoMIX package root.

The source tree keeps the layout of docs/SPEC.md section 3.4 (core/, dsp/,
cli/, mcp/ at the repository root). When running from a checkout, this shim
maps ``mankomix.core`` -> ``core/`` and so on. Installed wheels use the
setuptools ``package-dir`` mapping in pyproject.toml instead.
"""

from __future__ import annotations

from pathlib import Path

__version__ = "0.1.0"
ENGINE_VERSION = __version__

_ROOT = Path(__file__).resolve().parent.parent
if (_ROOT / "core" / "__init__.py").is_file():
    __path__.append(str(_ROOT))  # type: ignore[name-defined]


def repo_data_root() -> Path:
    """Directory holding the data folders (objectives/, profiles/, knowledge/, ...)."""
    return _ROOT
