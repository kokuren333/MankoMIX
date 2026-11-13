"""True peak (BS.1770-4 Annex 2 style) with intersample-peak signals."""
from __future__ import annotations

import math

import numpy as np
import pytest

from mankomix.core.measure import loudness as L


def quarter_rate_sine(sr: int, amp: float, phase: float, dur_s: float = 1.0) -> np.ndarray:
    """Sine at fs/4 with raised-cosine fades (no edge transients)."""
    n = np.arange(int(sr * dur_s))
    s = amp * np.sin(2 * np.pi * 0.25 * n + phase)
    r = int(0.05 * sr)
    w = np.ones_like(s)
    w[:r] = 0.5 - 0.5 * np.cos(np.pi * np.arange(r) / r)
    w[-r:] = w[:r][::-1]
    return s * w


@pytest.mark.parametrize("sr", [44100, 48000, 96000])
def test_intersample_peak_45deg(sr):
    x = quarter_rate_sine(sr, 1.0, math.pi / 4)
    assert L.sample_peak_dbfs(x) == pytest.approx(-3.01, abs=0.02)
    assert L.true_peak_dbtp(x, sr) == pytest.approx(0.0, abs=0.2)


@pytest.mark.parametrize("sr", [44100, 48000])
def test_full_scale_samples_overshoot(sr):
    # Samples reach exactly +-1.0 but the waveform between them peaks at +3.01 dBTP.
    x = np.stack([quarter_rate_sine(sr, math.sqrt(2.0), math.pi / 4)] * 2, axis=1)
    assert L.sample_peak_dbfs(x) == pytest.approx(0.0, abs=0.02)
    assert L.true_peak_dbtp(x, sr) == pytest.approx(3.01, abs=0.2)


def test_low_frequency_sine_has_no_overshoot():
    sr = 48000
    t = np.arange(sr) / sr
    x = 0.5 * np.sin(2 * np.pi * 997 * t)
    assert L.true_peak_dbtp(x, sr) == pytest.approx(20 * math.log10(0.5), abs=0.05)


def test_oversample_factor():
    assert L.tp_oversample_factor(44100) == 5
    assert L.tp_oversample_factor(48000) == 4
    assert L.tp_oversample_factor(96000) == 4
    assert L.tp_oversample_factor(32000) == 6


@pytest.mark.parametrize("seed", range(8))
def test_true_peak_never_below_sample_peak(seed):
    rng = np.random.default_rng(seed)
    sr = int(rng.choice([44100, 48000, 96000]))
    n = int(rng.integers(100, 20000))
    x = rng.standard_normal((n, 2)) * rng.uniform(0.01, 0.5)
    if seed % 2:
        x = np.cumsum(x, axis=0) * 0.01   # low-passed material
    sp = L.sample_peak_dbfs(x)
    tp = L.true_peak_dbtp(x, sr)
    assert tp >= sp - 1e-9
    per_ch = L.true_peak_per_channel(x, sr)
    assert len(per_ch) == 2 and max(per_ch) == pytest.approx(tp)


def test_chunking_is_seamless():
    rng = np.random.default_rng(7)
    x = rng.standard_normal((50000, 1)) * 0.3
    full = L.true_peak_per_channel(x, 48000, chunk=1 << 20)
    small = L.true_peak_per_channel(x, 48000, chunk=1000)
    assert small[0] == pytest.approx(full[0], abs=1e-9)


def test_silence_and_non_finite():
    assert L.true_peak_dbtp(np.zeros((1000, 2)), 48000) == -math.inf
    x = np.zeros(1000)
    x[10] = np.nan
    x[20] = 0.5
    assert L.true_peak_dbtp(x, 48000) >= 20 * math.log10(0.5) - 1e-9
