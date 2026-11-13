"""dynamic_eq, deesser and the shared ballistics (R-13, SPEC 6.5.2), plus compressor speed."""

from __future__ import annotations

import math
import time

import numpy as np
import pytest
from scipy import signal

from mankomix.dsp import engine
from mankomix.dsp import processors as P
from mankomix.dsp.reference import ballistics, dynamics, dyneq

SR = 48000


def _sine(f, n, amp, phase=0.0):
    return amp * np.sin(2 * math.pi * f * np.arange(n) / SR + phase)


def _tone_db(x, f):
    """Amplitude (dB) of the component at f by lock-in over the whole signal."""
    t = np.arange(len(x)) / SR
    c = np.mean(x * np.cos(2 * math.pi * f * t))
    s = np.mean(x * np.sin(2 * math.pi * f * t))
    return 20 * math.log10(2 * math.hypot(c, s))


def _run(t, x, **params):
    fn = {"dynamic_eq": dyneq.dynamic_eq, "deesser": dyneq.deesser}[t]
    return fn(np.asarray(x, dtype=np.float64), SR, P.validate_params(t, params))


# --------------------------------------------------------------------------- dynamic_eq

def test_dynamic_eq_is_transparent_below_threshold():
    x = np.stack([_sine(1000, SR, 10 ** (-40 / 20)), _sine(1000, SR, 10 ** (-42 / 20))], axis=1)
    y, _, st = _run("dynamic_eq", x, freq_hz=1000.0, threshold_db=-20.0, range_db=-6.0)
    assert np.array_equal(y, x)                       # bit for bit
    assert st["gain_change"]["max_db"] == 0.0 and st["activity"]["active_frac"] == 0.0
    assert st["phase"] == "minimum"


def test_dynamic_eq_acts_only_while_the_band_exceeds_threshold():
    n = 2 * SR
    low = _sine(100, n, 0.3)
    burst = _sine(1000, n, 0.5) * ((np.arange(n) >= SR) & (np.arange(n) < SR + SR // 2))
    x = (low + burst)[:, None]
    y, _, st = _run("dynamic_eq", x, freq_hz=1000.0, bw_oct=1.0, threshold_db=-30.0, range_db=-6.0,
                    attack_ms=2.0, release_ms=50.0)
    # before the burst the 1 kHz band (100 Hz is 3.3 octaves away) stays below threshold
    assert np.array_equal(y[: SR - 10], x[: SR - 10])
    # during the burst (after the attack) the 1 kHz component is cut by the full range
    seg = slice(SR + SR // 8, SR + SR // 2)
    d1k = _tone_db(y[seg, 0], 1000) - _tone_db(x[seg, 0], 1000)
    assert -6.5 < d1k < -5.0
    # 100 Hz content is left alone
    assert abs(_tone_db(y[seg, 0], 100) - _tone_db(x[seg, 0], 100)) < 0.3
    act = st["activity"]
    assert act["events"] == 1 and 0.2 < act["active_frac"] < 0.35
    assert st["direction"] == "cut"


def test_dynamic_eq_boost_and_shelves():
    x = _sine(8000, SR // 2, 0.5)[:, None]
    y, _, _ = _run("dynamic_eq", x, shape="high_shelf", freq_hz=4000.0, threshold_db=-40.0,
                   range_db=4.0, attack_ms=1.0)
    seg = slice(SR // 4, SR // 2)
    assert 3.0 < _tone_db(y[seg, 0], 8000) - _tone_db(x[seg, 0], 8000) < 4.5
    y, _, _ = _run("dynamic_eq", x, shape="low_shelf", freq_hz=200.0, threshold_db=-40.0,
                   range_db=-6.0)
    assert np.array_equal(y, x)                       # 8 kHz is not in a 200 Hz low band


# --------------------------------------------------------------------------- deesser

def _sibilant_bursts(n, seed=0):
    rng = np.random.default_rng(seed)
    noise = signal.sosfilt(signal.butter(6, [5000, 8000], "bandpass", output="sos", fs=SR),
                           rng.standard_normal(n))
    gate = ((np.arange(n) // (SR // 10)) % 3 == 1).astype(float)     # 100 ms on, 200 ms off
    return 0.3 * noise * gate, gate.astype(bool)


def test_deesser_reduces_sibilance_and_keeps_1khz():
    n = 3 * SR
    s, on = _sibilant_bursts(n)
    tone = _sine(1000, n, 0.1)                                       # -20 dBFS
    x = np.stack([tone + s, tone + s], axis=1)
    y, _, st = _run("deesser", x, threshold_db=-35.0, range_db=8.0)
    assert st["mode"] == "split_band" and 4000 < st["band_hz"][0] < 5000
    band = signal.butter(6, [5000, 8000], "bandpass", output="sos", fs=SR)
    bx = signal.sosfiltfilt(band, x[:, 0])
    by = signal.sosfiltfilt(band, y[:, 0])
    red = 10 * math.log10(np.sum(bx[on] ** 2) / np.sum(by[on] ** 2))
    assert red >= 3.0, red
    assert abs(_tone_db(y[:, 0], 1000) - _tone_db(x[:, 0], 1000)) <= 0.5
    assert st["activity"]["events"] >= 5


# --------------------------------------------------------------------------- ballistics

def _gr_trace(n=SR):
    rng = np.random.default_rng(9)
    return np.maximum(0.0, rng.standard_normal(n).cumsum() * 0.05)


@pytest.mark.skipif(not ballistics.native_kernel_available(), reason="native smoother kernel unavailable")
def test_native_ballistics_are_bit_identical_to_python():
    gr = _gr_trace()
    a, r = ballistics.coef(3.0, SR), ballistics.coef(120.0, SR)
    yn, impl = ballistics.smooth(gr, a, r, impl="native")
    yp, _ = ballistics.smooth(gr, a, r, impl="python")
    assert impl == "native" and np.array_equal(yn, yp)
    x = np.random.default_rng(1).standard_normal((SR, 2)) * 0.3
    p = P.validate_params("compressor", {"threshold_db": -30.0, "ratio": 4.0})
    y1, _, s1 = dynamics.compressor(x, SR, p, ballistics_impl="native")
    y2, _, s2 = dynamics.compressor(x, SR, p, ballistics_impl="python")
    assert np.array_equal(y1, y2) and s1["ballistics"] == "native" and s2["ballistics"] == "python"
    # the native backend variants render identically and are recorded as native
    chain = [{"type": "deesser", "params": {"threshold_db": -40.0}}, {"type": "compressor"}]
    rn = engine.render_chain(x, SR, chain, stage="bus", backend_preference=("native", "reference"))
    rr = engine.render_chain(x, SR, chain, stage="bus")
    assert [s["backend"] for s in rn.steps] == ["native", "native"]
    assert [s["backend"] for s in rr.steps] == ["reference", "reference"]
    assert np.array_equal(rn.audio, rr.audio)
    assert "native" in rn.backends and rn.backends["native"]["backend"] == "native"


def test_python_ballistics_time_constant():
    a = ballistics.coef(20.0, SR)
    gr = np.concatenate([np.zeros(SR // 2), np.full(SR // 2, 10.0)])
    y, impl = ballistics.smooth(gr, a, a, impl="python")
    k = SR // 2 + int(0.020 * SR)
    assert impl == "python" and abs(y[k] / 10.0 - (1 - math.exp(-1))) < 0.01


@pytest.mark.slow
def test_compressor_speed_three_minutes_stereo():
    n = 180 * SR
    x = np.random.default_rng(0).standard_normal((n, 2)) * 0.1
    p = P.validate_params("compressor", {"threshold_db": -30.0, "ratio": 3.0})
    t0 = time.perf_counter()
    y, _, st = dynamics.compressor(x, SR, p)
    elapsed = time.perf_counter() - t0
    assert y.shape == x.shape
    # native kernel: ~1.5 s on the reference machine; the pure-Python ballistics loop is ~3x slower
    limit = 6.0 if st["ballistics"] == "native" else 20.0
    assert elapsed < limit, f"compressor too slow: {elapsed:.1f} s ({st['ballistics']} ballistics)"
