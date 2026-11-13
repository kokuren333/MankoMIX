"""True-peak limiter: S-01 ceiling guarantee, transparency, time alignment (S-09)."""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy import signal

from mankomix.dsp import engine
from mankomix.dsp import processors as P
from mankomix.dsp.reference import dynamics, truepeak

try:
    from mankomix.core.measure import loudness as core_loudness
except Exception:  # pragma: no cover - measurement module optional for dsp tests
    core_loudness = None

TOL_DB = 0.05


def _music_like(seed: int, sr: int, seconds: float = 1.5) -> np.ndarray:
    """Seeded mixture: pink-ish noise, tones (one near Nyquist), drum-like bursts, hard edges."""
    rng = np.random.default_rng(seed)
    n = int(sr * seconds)
    t = np.arange(n) / sr
    white = rng.standard_normal((n, 2))
    pink = signal.lfilter([0.049922035, -0.095993537, 0.050612699, -0.004408786],
                          [1, -2.494956002, 2.017265875, -0.522189400], white, axis=0)
    x = 0.4 * pink / np.max(np.abs(pink))
    for _ in range(3):
        f = rng.uniform(40, 0.45 * sr)
        x += rng.uniform(0.05, 0.3) * np.sin(2 * math.pi * f * t + rng.uniform(0, 6.28))[:, None]
    env = np.zeros(n)
    for start in rng.integers(0, n - 2000, size=8):
        env[start:start + 2000] += np.exp(-np.arange(2000) / 300.0)
    x += (env[:, None] * rng.standard_normal((n, 2))) * 0.8
    x[int(0.1 * n), :] += rng.choice([-1, 1]) * 1.5      # single-sample spike
    x[: 3, :] = 0.9                                       # loud start (lookahead at the edge)
    peak_db = rng.uniform(0.0, 12.0)                      # peaks up to +12 dBFS
    return x / np.max(np.abs(x)) * 10 ** (peak_db / 20)


def _limit(x, sr, **params):
    return dynamics.limiter(np.asarray(x, dtype=np.float64), sr, P.validate_params("limiter", params))


@pytest.mark.parametrize("ceiling", [-1.0, -2.0, -0.3])
@pytest.mark.parametrize("seed", [0, 1, 2])
def test_true_peak_never_exceeds_ceiling(ceiling, seed):
    sr = 48000
    x = _music_like(seed, sr)
    y, sr_out, st = _limit(x, sr, ceiling_dbtp=ceiling)
    assert sr_out == sr and y.shape == x.shape and np.all(np.isfinite(y))
    assert truepeak.true_peak_dbtp(y, sr) <= ceiling + TOL_DB
    assert truepeak.true_peak_dbtp(y, factor=4) <= ceiling + TOL_DB
    assert st["out_true_peak_dbtp"] <= ceiling + 1e-9
    if core_loudness is not None:
        assert core_loudness.true_peak_dbtp(y, sr) <= ceiling + TOL_DB
    gr = st["gain_reduction"]
    assert set(gr) >= {"median_db", "p95_db", "frac_over_1db", "max_db"}
    assert 0 <= gr["median_db"] <= gr["p95_db"] <= gr["max_db"]


@pytest.mark.parametrize("sr", [44100, 96000])
def test_true_peak_ceiling_other_rates(sr):
    x = _music_like(7, sr, seconds=1.0)
    y, _, _ = _limit(x, sr, ceiling_dbtp=-1.0, lookahead_ms=1.5, release_ms=50.0)
    assert truepeak.true_peak_dbtp(y, sr) <= -1.0 + TOL_DB
    assert truepeak.true_peak_dbtp(y, factor=4) <= -1.0 + TOL_DB
    if core_loudness is not None:
        assert core_loudness.true_peak_dbtp(y, sr) <= -1.0 + TOL_DB


def test_intersample_peak_is_caught():
    sr = 48000
    n = np.arange(sr // 2)
    x = np.repeat(np.sin(2 * math.pi * (sr / 4) * n / sr + math.pi / 4)[:, None], 2, axis=1) * 1.2
    assert 20 * math.log10(np.max(np.abs(x))) < -1.0          # sample peak is below the ceiling ...
    assert truepeak.true_peak_dbtp(x, sr) > 0.0                # ... the true peak is not
    y, _, st = _limit(x, sr, ceiling_dbtp=-1.0)
    assert truepeak.true_peak_dbtp(y, sr) <= -1.0 + TOL_DB
    assert st["gain_reduction"]["max_db"] > 0.5


def test_transparent_below_ceiling_and_time_aligned():
    sr = 48000
    rng = np.random.default_rng(5)
    x = _music_like(3, sr) * 0.0
    x += rng.standard_normal(x.shape) * 0.05                   # far below the ceiling
    assert truepeak.true_peak_dbtp(x, sr) < -6
    y, _, st = _limit(x, sr, ceiling_dbtp=-1.0, lookahead_ms=5.0)
    assert np.array_equal(y, x)                                # bit-identical, no delay
    assert st["gain_reduction"]["max_db"] == 0.0
    assert st["latency_compensated"] and st["lookahead_samples"] == 240


def test_output_is_time_aligned_when_limiting():
    sr = 48000
    n = sr
    t = np.arange(n) / sr
    x = np.repeat((0.2 * np.sin(2 * math.pi * 220 * t))[:, None], 2, axis=1)
    x[30000, :] = 1.8                                          # loud spike far over the ceiling
    y, _, _ = _limit(x, sr, ceiling_dbtp=-1.0, lookahead_ms=3.0)
    assert y.shape == x.shape
    # far away from the spike the signal is untouched and in place (sample positions preserved)
    assert np.array_equal(y[:20000], x[:20000])
    c = signal.correlate(y[:, 0], x[:, 0], mode="full", method="fft")
    assert int(np.argmax(c)) - (n - 1) == 0
    # the spike stays at its position, reduced
    region = np.abs(y[29000:31000, 0])
    assert int(np.argmax(region)) + 29000 == 30000
    assert truepeak.true_peak_dbtp(y, sr) <= -1.0 + TOL_DB


def test_engine_records_limiter_and_warns_on_heavy_gr():
    sr = 48000
    x = _music_like(4, sr) / 10 ** (12 / 20)
    chain = [{"type": "loudness_gain", "params": {"gain_db": 18.0}}, {"type": "limiter"}]
    res = engine.render_chain(x, sr, chain, stage="master")
    lim = res.steps[-1]
    assert lim["type"] == "limiter" and lim["backend"] == "reference"
    assert lim["stats"]["out_true_peak_dbtp"] <= -1.0
    assert any(w.startswith("P-18") for w in res.warnings)
    assert res.audio.shape == x.shape
