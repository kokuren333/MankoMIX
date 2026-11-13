"""Optional regression scaffold for the official sample (docs/SPEC.md 15.1, 16.2).

These tests run only when the sample location is given from outside:

* ``MANKOMIX_SAMPLE_DIR`` - folder with the conform set (12 stems and the
  aligned full mix, 48 kHz). Required; without it every test here is skipped
  by ``tests/conftest.py`` (``sample`` marker).
* ``MANKOMIX_SAMPLE_EXPORT_DIR`` - optional folder with the as-downloaded
  Suno Studio export set ("<number> <part>.wav" names, number 0 = full mix).

The sample audio itself never enters the repository. Expected measurement
ranges (data only, no audio) may be added later (SPEC 15.4).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.sample

AUDIO_SUFFIXES = {".wav", ".flac", ".aif", ".aiff"}


def _audio_files(folder: Path) -> list[Path]:
    return sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in AUDIO_SUFFIXES)


def _folder_from_env(name: str) -> Path:
    value = os.environ.get(name, "").strip()
    if not value:
        pytest.skip(f"{name} not set")
    return Path(value).expanduser()


def test_sample_conform_set_is_present():
    folder = _folder_from_env("MANKOMIX_SAMPLE_DIR")
    assert folder.is_dir(), "MANKOMIX_SAMPLE_DIR does not point to a folder"
    assert len(_audio_files(folder)) >= 1, "no audio files in MANKOMIX_SAMPLE_DIR"
    # TODO(M1 intake): ingest the conform set unchanged; expect 12 stems plus the
    #   aligned full mix, 48 kHz; the derived "other" / "no_vocals" files must
    #   not be used as inputs (D-037); content hashes unchanged after intake.
    # TODO(M2 measure): compare the measurement vector (P-03 loudness, P-14 true
    #   peak, P-16 noise/shimmer, ...) with stored expected ranges.
    # TODO(later milestones): render the 11 sample variants of SPEC 15.2 and check
    #   the safety invariants S-01..S-11 and bit-identical re-rendering (16.3).


def test_sample_export_set_is_present():
    folder = _folder_from_env("MANKOMIX_SAMPLE_EXPORT_DIR")
    assert folder.is_dir(), "MANKOMIX_SAMPLE_EXPORT_DIR does not point to a folder"
    assert len(_audio_files(folder)) >= 1, "no audio files in MANKOMIX_SAMPLE_EXPORT_DIR"
    # TODO(M1 intake): detect the Suno export pattern, assign roles from part
    #   names, register the number-0 file as fullmix, and report the stem-sum vs
    #   full-mix residual (SPEC 6.1.3, 6.1.4) without converting anything.
