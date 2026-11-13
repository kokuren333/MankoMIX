"""audio_io.write is byte-deterministic (SPEC 16.1)."""
from __future__ import annotations

import hashlib
import time

import numpy as np
import pytest

from mankomix.core import audio_io


@pytest.mark.parametrize("subtype", ["FLOAT", "DOUBLE", "PCM_24", "PCM_16"])
def test_same_audio_same_bytes(tmp_path, subtype):
    x = np.random.default_rng(1).standard_normal((4800, 2)) * 0.1
    a, b = tmp_path / "a.wav", tmp_path / "b.wav"
    audio_io.write(a, x, 48000, subtype=subtype)
    time.sleep(1.1)  # libsndfile's PEAK chunk would carry a different timestamp
    audio_io.write(b, x, 48000, subtype=subtype)
    assert hashlib.sha256(a.read_bytes()).digest() == hashlib.sha256(b.read_bytes()).digest()
    assert b"PEAK" not in a.read_bytes()
    y, sr = audio_io.read(a)
    assert sr == 48000 and y.shape == x.shape
