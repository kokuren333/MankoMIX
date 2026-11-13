"""ERB/ISO 226 helpers and the 2mix perceptual proxies (SPEC 4.2 P-01/P-11/P-17/P-19/P-20)."""
from __future__ import annotations

import json
import time

import numpy as np
import pytest
from scipy.signal import butter, lfilter, sosfilt

from mankomix.core.analysis import erb
from mankomix.core.analysis.perceptual import (contrast_change, harshness, ltas_deviation,
                                               measure_mix_perceptual, range_penalty,
                                               section_contrast, sibilance, spectral_smoothness)

SR = 48000


def _pink(n: int, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    spec = np.fft.rfft(rng.standard_normal(n))
    f = np.arange(spec.size, dtype=float)
    f[0] = 1.0
    y = np.fft.irfft(spec / np.sqrt(f), n)
    return y / np.std(y) * 0.1


def _peaking(x: np.ndarray, f0: float, gain_db: float, q: float, sr: int = SR) -> np.ndarray:
    """RBJ cookbook peaking EQ."""
    a_ = 10 ** (gain_db / 40)
    w = 2 * np.pi * f0 / sr
    al = np.sin(w) / (2 * q)
    b = np.array([1 + al * a_, -2 * np.cos(w), 1 - al * a_])
    a = np.array([1 + al / a_, -2 * np.cos(w), 1 - al / a_])
    return lfilter(b / a[0], a / a[0], x)


def _clean(obj) -> None:
    json.dumps(obj, allow_nan=False)


@pytest.fixture(scope="module")
def pink():
    return _pink(SR * 15)


# --------------------------------------------------------------------------
# range_penalty


def test_range_penalty_shape():
    assert range_penalty(1.0, 0.0, 2.0, 1.0) == 0.0
    assert range_penalty(2.0, 0.0, 2.0, 1.0) == 0.0
    assert range_penalty(3.0, 0.0, 2.0, 1.0) == pytest.approx(1 - np.exp(-1))
    assert range_penalty(-1.0, 0.0, 2.0, 1.0) == pytest.approx(1 - np.exp(-1))
    assert range_penalty(10.0, 0.0, 2.0, 1.0) == pytest.approx(1.0)
    assert range_penalty(-100.0, None, 2.0, 1.0) == 0.0
    assert range_penalty(100.0, 0.0, None, 1.0) == 0.0
    assert range_penalty(None, 0.0, 1.0) is None
    assert range_penalty(float("nan"), 0.0, 1.0) is None
    vals = [range_penalty(v, None, 0.0, 2.0) for v in np.linspace(0, 6, 13)]
    assert all(b >= a for a, b in zip(vals, vals[1:]))
    arr = range_penalty(np.array([-3.0, 0.0, 3.0]), -1.0, 1.0, 2.0)
    assert arr[1] == 0.0 and arr[0] == pytest.approx(arr[2]) and 0 < arr[0] < 1
    with pytest.raises(ValueError):
        range_penalty(1.0, 0.0, 1.0, 0.0)


# --------------------------------------------------------------------------
# ERB, Bark, ISO 226


def test_erb_scale_known_values():
    assert float(erb.hz_to_erb_number(1000.0)) == pytest.approx(15.6, abs=0.05)
    assert float(erb.erb_bandwidth(1000.0)) == pytest.approx(132.6, abs=0.2)
    f = np.array([50.0, 440.0, 5000.0])
    assert np.allclose(erb.erb_number_to_hz(erb.hz_to_erb_number(f)), f)
    assert float(erb.hz_to_bark(1000.0, "zwicker")) == pytest.approx(8.5, abs=0.1)
    assert float(erb.bark_to_hz(erb.hz_to_bark(2000.0))) == pytest.approx(2000.0)


def test_erb_band_edges_cover_range():
    edges, centers = erb.erb_band_edges(SR, 8192)
    assert edges[0] == pytest.approx(20.0)
    assert np.all(np.diff(edges) >= SR / 8192 - 1e-9)
    assert np.all((centers > edges[:-1]) & (centers < edges[1:]))
    steps = np.diff(erb.hz_to_erb_number(edges))
    assert np.allclose(steps, 1.0)
    m = erb.band_matrix(SR, 8192, edges)
    assert m.shape == (centers.size, 4097)
    assert np.all(m.sum(axis=0) <= 1.0 + 1e-9)


def test_iso226_weights():
    _, spl = erb.iso226_spl(40.0)
    assert spl[0] == pytest.approx(99.85, abs=0.1)  # 40 phon at 20 Hz
    w = erb.equal_loudness_weight_db([1000.0, 50.0, 100.0, 3150.0], 80.0)
    assert w[0] == pytest.approx(0.0, abs=1e-9)
    assert w[1] < -10.0 and w[2] < 0.0
    assert w[3] > 0.0  # most sensitive region
    # Low frequencies are weighted down more at lower listening levels.
    assert erb.equal_loudness_weight_db([50.0], 40.0)[0] < erb.equal_loudness_weight_db([50.0], 80.0)[0]
    pw = erb.perceptual_band_weights(np.array([50.0, 1000.0, 3150.0]))
    assert pw["importance"][2] > pw["importance"][1] > pw["importance"][0]


def test_ltas_erb_is_level_matched(pink):
    a = erb.ltas_erb(pink, SR)
    b = erb.ltas_erb(pink * 0.1, SR)
    assert np.allclose(a["level_db"], b["level_db"], atol=0.05)
    assert a["normalization"]["level_matched"] is True
    st = erb.ltas_erb(np.stack([pink, pink * 0.5], axis=1), SR, per_channel=True)
    assert len(st["per_channel_db"]) == 2
    assert np.all(st["per_channel_db"][0] > st["per_channel_db"][1])


# --------------------------------------------------------------------------
# P-01 / P-11


def test_p01_pink_small_boost_large(pink):
    r_pink = ltas_deviation(pink, SR)
    r_boost = ltas_deviation(_peaking(pink, 3000.0, 8.0, 1.0), SR)
    _clean(r_pink)
    assert r_pink["generic_prior"] is True
    assert r_pink["penalty"] < 0.01
    assert r_pink["weighted_rms_deviation_db"] < 1.5
    assert r_boost["penalty"] > r_pink["penalty"] + 0.01
    assert r_boost["weighted_rms_deviation_db"] > r_pink["weighted_rms_deviation_db"] + 1.0
    top = r_boost["largest_deviations"][0]
    assert 2000.0 < top["center_hz"] < 5000.0 and top["deviation_db"] > 0
    assert len(r_pink["deviation_db"]) == len(r_pink["centers_hz"]) == len(r_pink["importance"])


def test_p01_with_reference(pink):
    ref_lt = erb.ltas_erb(_pink(SR * 15, seed=7), SR)
    reference = {"centers_hz": ref_lt["centers_hz"], "median_db": ref_lt["level_db"],
                 "iqr_db": np.full(ref_lt["level_db"].size, 3.0)}
    r_same = ltas_deviation(pink, SR, reference)
    r_boost = ltas_deviation(_peaking(pink, 3000.0, 8.0, 1.0), SR, reference)
    assert r_same["generic_prior"] is False
    assert r_same["penalty"] < 0.02
    assert r_boost["penalty"] > 0.05


def test_p11_harshness_and_presence(pink):
    r_pink = harshness(pink, SR)
    r_boost = harshness(_peaking(pink, 3000.0, 8.0, 1.0), SR)
    r_cut = harshness(_peaking(pink, 3000.0, -10.0, 1.0), SR)
    _clean(r_pink)
    assert abs(r_pink["ltas_prominence_db"]) < 1.0
    assert r_pink["penalty"] < 0.05
    assert r_boost["ltas_prominence_db"] > r_pink["ltas_prominence_db"] + 3.0
    assert r_boost["peaky_frame_pct"] > r_pink["peaky_frame_pct"]
    assert r_boost["penalty"] > 0.2
    # Two-sided presence: a cut is a deficit, a boost an excess.
    assert r_cut["presence"]["deficit_db"] > 0.0
    assert r_cut["presence"]["penalty"] > 0.0
    assert r_cut["penalty"] < 0.05
    assert r_boost["presence"]["excess_db"] > 0.0
    assert r_pink["presence"]["penalty"] == 0.0


# --------------------------------------------------------------------------
# P-17 / P-19


def test_p17_sibilant_bursts(pink):
    rng = np.random.default_rng(5)
    band = sosfilt(butter(4, [5000, 8000], btype="band", fs=SR, output="sos"),
                   rng.standard_normal(pink.size))
    gate = np.zeros(pink.size)
    for t in np.arange(0.5, pink.size / SR - 0.2, 1.0):
        gate[int(t * SR):int((t + 0.12) * SR)] = 1.0
    r0 = sibilance(pink, SR)
    r1 = sibilance(pink + 0.5 * band * gate, SR)
    _clean(r1)
    assert r1["p99_prominence_db"] > r0["p99_prominence_db"] + 6.0
    assert r1["events"] >= 10 and r0["events"] <= 2
    assert r1["penalty"] > 0.5 > r0["penalty"]


def test_p19_resonance(pink):
    r0 = spectral_smoothness(pink, SR)
    r1 = spectral_smoothness(_peaking(pink, 1000.0, 10.0, 8.0), SR)
    _clean(r1)
    assert r0["resonance_count"] == 0
    assert r1["resonance_count"] >= 1
    assert abs(np.log2(r1["resonances"][0]["freq_hz"] / 1000.0)) < 1 / 6
    assert r1["max_peak_db"] > r0["max_peak_db"] + 2.0
    assert r1["rms_deviation_db"] > r0["rms_deviation_db"]
    r2 = spectral_smoothness(_peaking(pink, 1000.0, 15.0, 10.0), SR)
    assert r2["penalty"] > r0["penalty"]


# --------------------------------------------------------------------------
# P-20


def test_p20_contrast_shrinks_under_gain_riding():
    env = np.concatenate([np.full(SR * 6, 0.2), np.full(SR * 6, 1.0), np.full(SR * 6, 0.2)])
    rng = np.random.default_rng(3)
    x = np.stack([_pink(env.size, 3), _pink(env.size, 4)], axis=1) * env[:, None]
    x[:, 0] += 1e-5 * rng.standard_normal(env.size)
    before = section_contrast(x, SR)
    _clean(before)
    assert before["has_contrast"] and before["contrast_db"] > 8.0
    assert [s["label"] for s in before["sections"]] == ["quiet", "loud", "quiet"]
    # Static gain riding: pull the loud part down by 8 dB.
    ride = np.where(env > 0.5, 10 ** (-8 / 20), 1.0)
    after = section_contrast(x * ride[:, None], SR, sections=before["sections"])
    ch = contrast_change(before, after)
    _clean(ch)
    assert after["contrast_db"] < before["contrast_db"] - 5.0
    assert ch["shrink_db"] > 5.0 and ch["warning"] is True
    assert ch["sections_match"] is True
    assert ch["penalty"] > 0.9
    same = contrast_change(before, section_contrast(x, SR, sections=before["sections"]))
    assert abs(same["shrink_db"]) < 0.1 and same["warning"] is False and same["penalty"] == 0.0


def test_p20_opening_detects_darker_loud_section():
    env = np.concatenate([np.full(SR * 6, 0.2), np.full(SR * 6, 1.0), np.full(SR * 6, 0.2)])
    x = _pink(env.size, 8) * env
    before = section_contrast(x, SR)
    lp = sosfilt(butter(2, 3000, fs=SR, output="sos"), x)
    darker = np.where(env > 0.5, lp, x)
    after = section_contrast(darker, SR, sections=before["sections"])
    ch = contrast_change(before, after)
    assert ch["opening_shrink_db"] > 1.5 and ch["opening_warning"] is True


# --------------------------------------------------------------------------
# Bundle


def test_measure_mix_perceptual_bundle_and_speed():
    base = _pink(SR * 20, 11)
    x = np.tile(np.stack([base, 0.9 * base], axis=1), (5, 1))  # 100 s stereo
    t0 = time.perf_counter()
    r = measure_mix_perceptual(x, SR)
    elapsed = time.perf_counter() - t0
    _clean(r)
    for k in ("P-01", "P-11", "P-17", "P-19", "P-20", "music", "level_match"):
        assert k in r
    for k in ("P-01", "P-11", "P-17", "P-19"):
        p = r[k]["penalty"]
        assert p is not None and 0.0 <= p <= 1.0
    assert r["P-01"]["generic_prior"] is True
    assert r["level_match"]["integrated_lufs"] is not None
    assert elapsed < 12.0, f"too slow: {elapsed:.1f} s"


def test_silence_is_json_clean():
    x = np.zeros((SR * 5, 2))
    r = measure_mix_perceptual(x, SR)
    _clean(r)
    assert r["P-11"]["penalty"] is None
    assert r["P-20"]["has_contrast"] is False
