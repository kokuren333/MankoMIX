"""DSP unit tests on synthesized signals (SPEC 16.1: frequency response, gain, time constants)."""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy import signal

from mankomix.dsp import processors as P
from mankomix.dsp.reference import basic, dynamics, filters, nonlinear, stereo

SR = 48000


def _resp_db(sos, f, sr=SR):
    _, h = signal.sosfreqz(sos, worN=np.atleast_1d(np.asarray(f, dtype=float)), fs=sr)
    return 20 * np.log10(np.abs(h))


def _sine(f, n=SR, amp=0.5, sr=SR, ch=1):
    t = np.arange(n) / sr
    x = amp * np.sin(2 * math.pi * f * t)
    return np.repeat(x[:, None], ch, axis=1)


def _rms_db(x):
    return 10 * math.log10(float(np.mean(np.asarray(x) ** 2)))


def _run(t, x, **params):
    fn = {"eq": filters.eq, "filter": filters.filt, "compressor": dynamics.compressor,
          "pan": basic.pan, "stereo": stereo.stereo, "saturator": nonlinear.saturator,
          "clipper": nonlinear.clipper}[t]
    return fn(x, SR, P.validate_params(t, params))


# --------------------------------------------------------------------------- definitions

def test_every_processor_declares_contract():
    for t, d in P.PROCESSORS.items():
        ids = [s["id"] for s in d["params"]]
        assert len(ids) == len(set(ids)), t
        assert set(d["realtime"]) >= {"block_ok", "latency_samples", "allocates"}, t
        assert isinstance(d["offline_only"], bool)
        assert set(d["stages"]) <= set(P.STAGES)
        for s in d["params"]:
            assert "unit" in s and "default" in s
        # defaults validate
        P.validate_params(t, {})
    assert P.describe("limiter")["stages"] == ["master"]
    for t in ("resample", "dither"):
        assert P.describe(t)["stages"] == ["export"]
    assert "export" in P.describe("loudness_gain")["stages"]


def test_validate_params_rejects_unknown_and_out_of_range():
    with pytest.raises(ValueError):
        P.validate_params("eq", {"q": 1.0})           # bandwidth is held in octaves (R-12)
    with pytest.raises(ValueError):
        P.validate_params("eq", {"gain_db": 40.0})
    with pytest.raises(ValueError):
        P.validate_params("filter", {"slope_db_oct": 30})
    with pytest.raises(ValueError):
        P.validate_params("nope", {})
    with pytest.raises(ValueError):
        P.validate_params("compressor", {"ratio": float("nan")})
    with pytest.raises(ValueError):
        P.validate_params("stereo", {"crossovers_hz": [2000.0], "widths": [1.0]})
    p = P.validate_params("eq", {"freq_hz": 250})
    assert p["freq_hz"] == 250.0 and p["phase"] == "minimum" and p["bw_oct"] == 1.0


def test_graph_schema_validates_a_chain():
    jsonschema = pytest.importorskip("jsonschema")
    schema = P.graph_schema()
    chain = [{"id": "eq1", "type": "eq", "params": {"freq_hz": 300.0, "gain_db": -1.5, "bw_oct": 1.0}},
             {"type": "limiter", "params": {"ceiling_dbtp": -1.0}}]
    jsonschema.validate(chain, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate([{"type": "eq", "params": {"q": 2}}], schema)


# --------------------------------------------------------------------------- eq / filter

@pytest.mark.parametrize("gain", [-6.0, 3.0, 12.0])
@pytest.mark.parametrize("f0", [100.0, 1000.0, 8000.0])
def test_peak_gain_at_center_and_octave_bandwidth(gain, f0):
    bw = 1.0
    sos = filters.rbj_biquad("peak", f0, gain, bw, SR)
    assert abs(_resp_db(sos, f0)[0] - gain) < 0.1
    # RBJ: bandwidth is measured between the half-gain (dB) points
    edges = _resp_db(sos, [f0 * 2 ** (-bw / 2), f0 * 2 ** (bw / 2)])
    assert np.all(np.abs(edges - gain / 2) < (0.3 if f0 <= 1000 else 0.6))
    # measured octave width between the half-gain points
    f = np.geomspace(f0 / 8, min(f0 * 8, SR / 2 * 0.999), 20000)
    r = _resp_db(sos, f)
    inside = f[(r - gain / 2) * np.sign(gain) >= 0]
    assert abs(math.log2(inside[-1] / inside[0]) - bw) < (0.03 if f0 <= 1000 else 0.12)


def test_notch_minus3db_points_follow_octave_width():
    f0, bw = 1000.0, 0.5
    sos = filters.rbj_biquad("notch", f0, 0.0, bw, SR)
    assert _resp_db(sos, f0)[0] < -60
    edges = _resp_db(sos, [f0 * 2 ** (-bw / 2), f0 * 2 ** (bw / 2)])
    assert np.all(np.abs(edges + 3.01) < 0.2)


def test_peak_on_a_signal_and_minimum_phase_stats():
    x = _sine(1000.0)
    y, _, st = _run("eq", x, freq_hz=1000.0, gain_db=-4.0, bw_oct=1.0)
    assert abs(_rms_db(y[SR // 2:]) - _rms_db(x[SR // 2:]) + 4.0) < 0.1
    assert st["phase_cost"]["phase_type"] == "minimum" and st["latency_samples"] == 0


@pytest.mark.parametrize("shape,gain", [("low_shelf", 6.0), ("low_shelf", -4.0),
                                        ("high_shelf", 6.0), ("high_shelf", -3.0)])
def test_shelf_gains(shape, gain):
    f0 = 300.0 if shape == "low_shelf" else 6000.0
    sos = filters.rbj_biquad(shape, f0, gain, 1.9, SR)
    lo, hi = _resp_db(sos, [20.0, 20000.0]) if shape == "low_shelf" else _resp_db(sos, [20000.0, 20.0])
    assert abs(lo - gain) < 0.25        # shelf side
    assert abs(hi) < 0.25               # flat side
    assert abs(_resp_db(sos, f0)[0] - gain / 2) < 0.2   # corner = half gain in dB


def test_linear_phase_eq_is_aligned_and_reports_pre_ringing():
    x = np.zeros((8192, 1))
    x[4000, 0] = 1.0
    y, _, st = _run("eq", x, freq_hz=200.0, gain_db=-1.0, bw_oct=1.0, phase="linear")
    assert int(np.argmax(np.abs(y[:, 0]))) == 4000          # latency compensated
    assert st["latency_samples"] > 0 and st["latency_compensated"]
    assert "pre_ringing" in st
    # magnitude matches the minimum-phase design
    s = _sine(200.0, n=SR)
    yl, _, _ = _run("eq", s, freq_hz=200.0, gain_db=-1.0, bw_oct=1.0, phase="linear")
    assert abs(_rms_db(yl[SR // 4:-SR // 4]) - _rms_db(s[SR // 4:-SR // 4]) + 1.0) < 0.05


@pytest.mark.parametrize("slope", [6, 12, 18, 24, 48])
@pytest.mark.parametrize("kind", ["hpf", "lpf"])
def test_butterworth_minus3db_at_cutoff(kind, slope):
    fc = 120.0 if kind == "hpf" else 5000.0
    sos = filters.butter_sos(kind, fc, slope, SR)
    assert abs(_resp_db(sos, fc)[0] + 3.01) < 0.05
    far = fc / 8 if kind == "hpf" else fc * 4
    assert _resp_db(sos, far)[0] < -slope * 1.8   # >= 2 octaves away: about slope dB per octave


def test_hpf_on_signal_records_phase_cost():
    x = _sine(120.0)
    y, _, st = _run("filter", x, kind="hpf", freq_hz=120.0, slope_db_oct=24)
    assert abs(_rms_db(y[SR // 2:]) - _rms_db(x[SR // 2:]) + 3.01) < 0.1
    probe = {p["freq_hz"]: p for p in st["phase_cost"]["probes"]}
    assert 120.0 in probe and probe[120.0]["group_delay_ms"] > 0


# --------------------------------------------------------------------------- compressor

@pytest.mark.parametrize("level_db", [-40.0, -20.0, -10.0, -3.0])
def test_compressor_static_curve_hard_knee(level_db):
    T, R = -20.0, 4.0
    x = np.full((SR // 2, 2), 10 ** (level_db / 20))      # DC: detector level is exact
    y, _, st = _run("compressor", x, threshold_db=T, ratio=R, knee_db=0.0, attack_ms=1.0,
                    release_ms=50.0, detector="peak")
    out_db = 20 * math.log10(y[-1, 0])
    expect = level_db if level_db <= T else T + (level_db - T) / R
    assert abs(out_db - expect) < 0.01
    assert st["gain_reduction"]["max_db"] >= 0


def test_compressor_soft_knee_midpoint_and_makeup():
    T, R, W = -20.0, 4.0, 10.0
    x = np.full((SR // 2, 1), 10 ** (T / 20))
    y, _, _ = _run("compressor", x, threshold_db=T, ratio=R, knee_db=W, attack_ms=1.0,
                   detector="rms", makeup_db=2.0)
    expect = T - (1 - 1 / R) * W / 8 + 2.0
    assert abs(20 * math.log10(y[-1, 0]) - expect) < 0.01
    assert np.allclose(dynamics.static_curve_db(np.array([-60.0]), T, R, W), -60.0)


def test_compressor_time_constants():
    # step from -40 to -10 dBFS: after one attack time ~63 % of the final GR is reached
    T, R, att = -30.0, 10.0, 20.0
    x = np.full((SR, 1), 10 ** (-40 / 20))
    x[SR // 2:] = 10 ** (-10 / 20)
    _, _, _ = _run("compressor", x, threshold_db=T, ratio=R, knee_db=0.0, attack_ms=att,
                   release_ms=200.0, detector="peak")
    gr_final = (-10 - T) * (1 - 1 / R)
    a = dynamics._coef(att, SR)
    gr = dynamics._smooth_gr(np.concatenate([np.zeros(SR // 2), np.full(SR // 2, gr_final)]), a, a)
    k = SR // 2 + int(att * 1e-3 * SR)
    assert abs(gr[k] / gr_final - (1 - math.exp(-1))) < 0.01


# --------------------------------------------------------------------------- pan

def test_pan_law_center_minus3db():
    x = _sine(1000.0, n=4800)
    y, _, st = _run("pan", x, position=0.0)
    assert y.shape[1] == 2
    for c in range(2):
        assert abs(20 * math.log10(np.max(np.abs(y[:, c])) / 0.5) + 3.0) < 1e-6
    yl, _, _ = _run("pan", x, position=-1.0)
    assert np.max(np.abs(yl[:, 1])) < 1e-12 and abs(np.max(np.abs(yl[:, 0])) - 0.5) < 1e-9
    y6, _, _ = _run("pan", x, position=0.0, center_db=-6.0)
    assert abs(20 * math.log10(np.max(np.abs(y6[:, 0])) / 0.5) + 6.0) < 1e-6
    # power is constant across positions for the -3 dB law
    for pos in (-0.7, -0.2, 0.4, 0.9):
        gl, gr = basic.pan_gains(pos, -3.0)
        assert abs(gl * gl + gr * gr - 1.0) < 5e-3   # k = 0.9966 for exactly -3.000 dB


def test_pan_balance_on_stereo_keeps_center_untouched():
    x = np.random.default_rng(0).standard_normal((1000, 2)) * 0.1
    y, _, _ = _run("pan", x, position=0.0)
    assert np.array_equal(y, x)
    y, _, _ = _run("pan", x, position=0.5)
    assert np.array_equal(y[:, 1], x[:, 1]) and np.max(np.abs(y[:, 0])) < np.max(np.abs(x[:, 0]))


# --------------------------------------------------------------------------- stereo

def _band(x, lo, hi):
    if lo:
        x = signal.sosfiltfilt(signal.butter(4, lo, "highpass", output="sos", fs=SR), x, axis=0)
    if hi:
        x = signal.sosfiltfilt(signal.butter(4, hi, "lowpass", output="sos", fs=SR), x, axis=0)
    return x


def test_stereo_mono_below_makes_low_band_correlated():
    rng = np.random.default_rng(1)
    x = rng.standard_normal((SR, 2)) * 0.2          # decorrelated L/R
    y, _, st = _run("stereo", x, mono_below_hz=150.0)
    lo = _band(y, None, 60.0)[SR // 8:-SR // 8]
    r = np.corrcoef(lo[:, 0], lo[:, 1])[0, 1]
    assert r > 0.999
    lo_in = _band(x, None, 60.0)[SR // 8:-SR // 8]
    assert abs(np.corrcoef(lo_in[:, 0], lo_in[:, 1])[0, 1]) < 0.2
    # high band untouched (width 1 above the split)
    hi_in = _band(x, 2000.0, None)[SR // 8:-SR // 8]
    hi_out = _band(y, 2000.0, None)[SR // 8:-SR // 8]
    assert np.max(np.abs(hi_out - hi_in)) < 1e-3
    assert st["latency_compensated"] and len(y) == len(x)


def test_stereo_per_band_widths_and_identity():
    rng = np.random.default_rng(2)
    x = rng.standard_normal((SR // 2, 2)) * 0.2
    y, _, _ = _run("stereo", x)                       # defaults are neutral
    assert np.allclose(y, x, atol=1e-15)
    y0, _, _ = _run("stereo", x, width=0.0)
    assert np.allclose(y0[:, 0], y0[:, 1])
    y, _, st = _run("stereo", x, mono_below_hz=120.0, crossovers_hz=[3000.0], widths=[1.0, 1.5])
    assert [b["width"] for b in st["bands"]] == [0.0, 1.0, 1.5]
    s_in = 0.5 * (x[:, 0] - x[:, 1])
    s_out = 0.5 * (y[:, 0] - y[:, 1])
    hi_in = _band(s_in[:, None], 8000.0, None)[2000:-2000]
    hi_out = _band(s_out[:, None], 8000.0, None)[2000:-2000]
    assert abs(_rms_db(hi_out) - _rms_db(hi_in) - 20 * math.log10(1.5)) < 0.1
    m_in, m_out = x.sum(axis=1), y.sum(axis=1)
    assert np.allclose(m_in, m_out, atol=1e-12)        # mid untouched


# --------------------------------------------------------------------------- saturator / clipper

def _harm_db(y, f0, k):
    n = len(y)
    spec = np.abs(np.fft.rfft(y * signal.windows.hann(n)))
    return 20 * math.log10(spec[int(f0 * k * n / SR)] / spec[int(f0 * n / SR)] + 1e-30)


def test_saturator_adds_harmonics():
    x = _sine(1000.0, amp=0.5)
    y, _, st = _run("saturator", x, drive_db=12.0, mode="tanh")
    assert _harm_db(y[:, 0], 1000.0, 3) > -40
    assert _harm_db(x[:, 0], 1000.0, 3) < -100
    assert st["harmonics"]["dominant"] == "odd"
    ya, _, sta = _run("saturator", x, drive_db=12.0, mode="asymmetric", asymmetry=0.8)
    assert _harm_db(ya[:, 0], 1000.0, 2) > -40          # even harmonics from asymmetry
    assert sta["harmonics"]["even_db"] > st["harmonics"]["even_db"]
    assert abs(float(np.mean(ya[SR // 2:]))) < 1e-4      # DC blocked (after settling)
    yd, _, _ = _run("saturator", x, drive_db=12.0, mix=0.0)
    assert np.allclose(yd, x)


def test_clipper_ceiling_and_oversampling_reduces_aliasing():
    f0 = 7000.0
    x = _sine(f0, amp=1.0)
    y1, _, _ = _run("clipper", x, mode="hard", ceiling_db=-6.0, oversample=1)
    y4, _, _ = _run("clipper", x, mode="hard", ceiling_db=-6.0, oversample=4)
    c = 10 ** (-6 / 20)
    assert np.max(np.abs(y1)) <= c + 1e-12
    assert np.max(np.abs(y4)) < c * 10 ** (1.0 / 20)    # small overshoot after downsampling

    def alias_energy(y):
        n = len(y)
        spec = np.abs(np.fft.rfft(y[:, 0] * signal.windows.hann(n))) ** 2
        freqs = np.fft.rfftfreq(n, 1 / SR)
        harm = np.zeros_like(freqs, dtype=bool)
        for k in range(1, 4):
            harm |= np.abs(freqs - f0 * k) < 20
        return 10 * math.log10(spec[~harm & (freqs > 50)].sum() / spec[harm].sum())
    assert alias_energy(y4) < alias_energy(y1) - 10
    ys, _, _ = _run("clipper", x * 0.1, mode="soft", ceiling_db=-6.0)
    assert np.allclose(ys[1000:-1000], x[1000:-1000] * 0.1, atol=1e-4)   # below the knee: transparent
