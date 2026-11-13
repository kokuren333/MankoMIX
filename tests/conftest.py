"""Shared pytest configuration. Shared fixtures live in tests/fixtures/."""
from __future__ import annotations

import os
import shutil

import pytest

pytest_plugins = ["tests.fixtures.plugin"]


def pytest_collection_modifyitems(config, items):
    has_ffmpeg = shutil.which("ffmpeg") is not None
    has_sample = bool(os.environ.get("MANKOMIX_SAMPLE_DIR"))
    for item in items:
        if "ffmpeg" in item.keywords and not has_ffmpeg:
            item.add_marker(pytest.mark.skip(reason="ffmpeg not on PATH"))
        if "sample" in item.keywords and not has_sample:
            item.add_marker(pytest.mark.skip(reason="MANKOMIX_SAMPLE_DIR not set"))
