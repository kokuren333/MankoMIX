"""Loudness conformance (EBU Tech 3341 / 3342 style, BS.1770-4). Signals are synthesised."""
from __future__ import annotations

import math

import numpy as np
import pytest

from mankomix.core.measure import loudness as L
from mankomix.core.measure import measure_signal

SR = 48000


def tone(level_dbfs: float, dur_s: float, sr: int = SR, freq: float = 1000.0, ch: int = 2) -> np.ndarray:
    t = np.arange(int(round(dur_s * sr))) / sr
    s = 10.0 ** (level_dbfs / 20.0) * np.sin(2 * np.pi * freq * t)
    return np.repeat(s[:, None], ch, axis=1)


def seq(*parts) -> np.ndarray:
    return np.concatenate([tone(lv, d) for lv, d in parts], axis=0)


def pink_noise(n: int, ch: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    spec = np.fft.rfft(rng.standard_normal((n, ch)), axis=0)
    f = np.fft.rfftfreq(n, 1.0 / SR)
    f[0] = f[1]
    y = np.fft.irfft(spec / np.sqrt(f)[:, None], n=n, axis=0)
    return 0.1 * y / np.sqrt(np.mean(y ** 2))


def test_k_weighting_matches_published_48k():
    sos = L.k_weighting_sos(48000)
    pre = [1.53512485958697, -2.69169618940638, 1.19839281085285, 1.0, -1.69065929318241, 0.73248077421585]
    rlb = [1.0, -2.0, 1.0, 1.0, -1.99004745483398, 0.99007225036621]
    np.testing.assert_allclose(sos[0], pre, atol=1e-8)
    np.testing.assert_allclose(sos[1], rlb, atol=1e-8)


@pytest.mark.parametrize("sr", [44100, 48000, 96000])
def test_k_weighting_gain_at_1k_and_low_cut(sr):
    from scipy.signal import sosfreqz
    _, h = sosfreqz(L.k_weighting_sos(sr), worN=[20.0, 1000.0, 10000.0], fs=sr)
    db = 20 * np.log10(np.abs(h))
    assert db[1] == pytest.approx(0.69, abs=0.05)   # cancels the -0.691 offset
    assert db[0] < -10.0                              # RLB high-pass
    assert db[2] == pytest.approx(4.0, abs=0.3)       # high shelf


@pytest.mark.parametrize("level", [-23.0, -33.0])
def test_stereo_sine_integrated(level):
    assert L.integrated(tone(level, 20.0), SR) == pytest.approx(level, abs=0.1)


def test_gating_tone_sequence():
    x = seq((-36.0, 10.0), (-23.0, 60.0), (-36.0, 10.0))
    assert L.integrated(x, SR) == pytest.approx(-23.0, abs=0.1)


def test_gating_with_absolute_gate():
    x = seq((-72.0, 10.0), (-36.0, 10.0), (-23.0, 60.0), (-36.0, 10.0), (-72.0, 10.0))
    assert L.integrated(x, SR) == pytest.approx(-23.0, abs=0.1)


def test_mono_counts_as_one_channel():
    x = tone(-23.0, 10.0, ch=1)
    assert L.integrated(x, SR) == pytest.approx(-26.01, abs=0.1)
    assert L.integrated(x[:, 0], SR) == pytest.approx(-26.01, abs=0.1)


def test_surround_weights():
    x = tone(-30.0, 10.0, ch=5)
    # L+R+C at 1.0 plus 2 x 1.41 surrounds
    expected = -30.0 + 10 * math.log10((3 + 2 * 1.41) / 2)
    assert L.integrated(x, SR) == pytest.approx(expected, abs=0.1)


def test_momentary_and_short_term_constant_tone():
    x = tone(-23.0, 10.0)
    m = L.momentary(x, SR)
    s = L.short_term(x, SR)
    assert len(m) == 97 and len(s) == 71   # 100 ms hop, complete blocks only
    np.testing.assert_allclose(m[1:], -23.0, atol=0.1)
    np.testing.assert_allclose(s, -23.0, atol=0.1)


def test_momentary_tracks_level_step():
    x = seq((-30.0, 5.0), (-20.0, 5.0))
    m = L.momentary(x, SR)
    assert m[10] == pytest.approx(-30.0, abs=0.1)
    assert m[-1] == pytest.approx(-20.0, abs=0.1)
    assert m.max() == pytest.approx(-20.0, abs=0.1)


@pytest.mark.parametrize("a,b,lra", [(-20.0, -30.0, 10.0), (-20.0, -15.0, 5.0), (-40.0, -20.0, 20.0)])
def test_loudness_range_tech3342(a, b, lra):
    x = seq((a, 20.0), (b, 20.0))
    assert L.loudness_range(x, SR) == pytest.approx(lra, abs=1.0)


@pytest.mark.parametrize("sr", [44100, 96000])
def test_sample_rates_agree(sr):
    def multitone(rate):
        t = np.arange(rate * 8) / rate
        s = sum(a * np.sin(2 * np.pi * f * t + p) for f, a, p in
                [(50, 0.2, 0.1), (200, 0.15, 0.7), (1000, 0.1, 1.3), (5000, 0.05, 2.1), (12000, 0.03, 0.4)])
        return np.stack([s, 0.7 * s], axis=1)
    ref = L.integrated(multitone(48000), 48000)
    assert L.integrated(multitone(sr), sr) == pytest.approx(ref, abs=0.1)


def test_cross_check_pyloudnorm():
    pyln = pytest.importorskip("pyloudnorm")
    x = pink_noise(SR * 12, 2, seed=1234)
    x[: SR * 3] *= 0.05   # quiet intro exercises the gates
    ours = L.integrated(x, SR)
    theirs = pyln.Meter(SR).integrated_loudness(x)
    assert ours == pytest.approx(theirs, abs=0.1)


def test_silence_and_short_inputs():
    z = np.zeros((SR * 5, 2))
    assert L.integrated(z, SR) == -math.inf
    assert math.isnan(L.loudness_range(z, SR))
    assert np.all(np.isneginf(L.momentary(z, SR)))
    assert L.integrated(tone(-20.0, 0.3), SR) == -math.inf   # shorter than one 400 ms block
    assert L.short_term(tone(-20.0, 2.0), SR).size == 0
    v = measure_signal(z, SR)
    assert v["P-03"]["integrated_lufs"] is None
    assert v["P-03"]["true_peak_dbtp"] is None
    assert v["health"]["silent"] is True


def test_loudness_summary_keys_and_relations():
    x = seq((-30.0, 5.0), (-20.0, 5.0))
    s = L.loudness_summary(x, SR)
    assert set(s) == {"integrated_lufs", "short_term_max_lufs", "short_term_p10", "short_term_p50",
                      "short_term_p95", "momentary_max_lufs", "lra_lu", "true_peak_dbtp",
                      "sample_peak_dbfs", "plr_db", "psr_db"}
    assert s["plr_db"] == pytest.approx(s["true_peak_dbtp"] - s["integrated_lufs"])
    assert s["psr_db"] == pytest.approx(s["true_peak_dbtp"] - s["short_term_max_lufs"])
    assert s["short_term_p10"] <= s["short_term_p50"] <= s["short_term_p95"] <= s["short_term_max_lufs"]
    assert s["true_peak_dbtp"] >= s["sample_peak_dbfs"]
