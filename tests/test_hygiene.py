"""Repository hygiene check (docs/SPEC.md section 16.4) as a test.

Runs ``tools/check_hygiene.py`` in a subprocess from the repository root.
Skipped when ``MANKOMIX_SKIP_HYGIENE=1``, when ``git`` is not on PATH, or when
the tree is not a git checkout (for example an exported source archive),
because the check inspects git's file list and commit history.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "tools" / "check_hygiene.py"


def _skip_reason() -> str | None:
    if os.environ.get("MANKOMIX_SKIP_HYGIENE") == "1":
        return "MANKOMIX_SKIP_HYGIENE=1"
    if shutil.which("git") is None:
        return "git is not on PATH"
    if not (REPO_ROOT / ".git").exists():
        return "not a git checkout"
    if not SCRIPT.is_file():
        return "tools/check_hygiene.py is missing"
    return None


@pytest.mark.skipif(_skip_reason() is not None, reason=_skip_reason() or "")
def test_repository_hygiene():
    result = subprocess.run(
        [sys.executable, "-I", str(SCRIPT.relative_to(REPO_ROOT))],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    assert result.returncode == 0, (result.stdout + result.stderr).strip()
