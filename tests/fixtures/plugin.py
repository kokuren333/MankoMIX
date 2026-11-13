"""pytest plugin with shared fixtures (registered by tests/conftest.py).

All material is synthesized by :mod:`tests.fixtures.synth`; no audio file is
read from the repository (docs/SPEC.md section 16.2).

Session-scoped arrays are marked read-only so that one test cannot change
what another test sees; call ``.copy()`` before modifying them.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from tests.fixtures import synth

SR = synth.DEFAULT_SR
MIX_PEAK_DBFS = -6.0


def _frozen(x: np.ndarray) -> np.ndarray:
    x = np.ascontiguousarray(x, dtype=np.float64)
    x.setflags(write=False)
    return x


@pytest.fixture(scope="session")
def sr() -> int:
    """Default sample rate of the synthetic material (48 kHz)."""
    return SR


@pytest.fixture
def rng() -> np.random.Generator:
    """A fresh, fixed-seed random generator for each test."""
    return np.random.default_rng(20240613)


@pytest.fixture(scope="session")
def song_stems() -> dict[str, np.ndarray]:
    """The 8 s synthetic song as twelve read-only stereo stems keyed by role."""
    stems = synth.song_stems(sr=SR, seconds=synth.SONG_SECONDS, seed=0)
    return {role: _frozen(x) for role, x in stems.items()}


@pytest.fixture(scope="session")
def song_sections() -> dict[str, tuple[float, float]]:
    """Quiet / loud section boundaries (seconds) of ``song_stems``."""
    return synth.song_sections(synth.SONG_SECONDS)


@pytest.fixture(scope="session")
def song_mix(song_stems) -> np.ndarray:
    """Gain-0 stem sum, normalized to a -6 dBFS sample peak (read-only)."""
    return _frozen(synth.normalize_peak(synth.stem_sum(song_stems), MIX_PEAK_DBFS))


@pytest.fixture(scope="session")
def defective_mix(song_mix) -> np.ndarray:
    """``song_mix`` with typical AI-render defects (read-only).

    Steep high-frequency ceiling at 16 kHz, 10-14 kHz shimmer at -30 dB and a
    -6 dBFS click on the first sample.
    """
    x = synth.add_hf_ceiling(song_mix, SR, cutoff_hz=16000.0)
    x = synth.add_shimmer(x, SR, band=(10000.0, 14000.0), depth_db=-30.0, seed=1)
    x = synth.add_head_click(x, SR, at_s=0.0, dbfs=-6.0)
    return _frozen(x)


@pytest.fixture
def stems_dir(tmp_path: Path, song_stems) -> Path:
    """Folder with one 32-bit float WAV per stem, named ``<role>.wav``."""
    folder = tmp_path / "stems"
    for role, x in song_stems.items():
        synth.write_wav(folder / f"{role}.wav", x, SR)
    return folder


@pytest.fixture
def mix_wav(tmp_path: Path, song_mix) -> Path:
    """The 2mix (``song_mix``) as a 32-bit float WAV file."""
    return synth.write_wav(tmp_path / "mix.wav", song_mix, SR)


@pytest.fixture
def defective_mix_wav(tmp_path: Path, defective_mix) -> Path:
    """``defective_mix`` as a 32-bit float WAV file."""
    return synth.write_wav(tmp_path / "defective_mix.wav", defective_mix, SR)
