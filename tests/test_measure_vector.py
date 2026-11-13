"""Measurement vector: stereo, spectral, health, compare, JSON safety."""
from __future__ import annotations

import json
import math

import numpy as np
import pytest

from mankomix.core.errors import InputError
from mankomix.core.measure import (BANDS_P22, Spectrum, clip_bands, compare,
                                   low_band_negative_persistence, measure_signal)
from mankomix.core.measure.spectral import band_crest, band_energy

SR = 48000


def noise(dur_s: float, ch: int = 2, seed: int = 0, amp: float = 0.1) -> np.ndarray:
    return amp * np.random.default_rng(seed).standard_normal((int(dur_s * SR), ch))


def sine(freq: float, dur_s: float, amp: float = 0.5, fade_s: float = 0.0) -> np.ndarray:
    t = np.arange(int(dur_s * SR)) / SR
    s = amp * np.sin(2 * np.pi * freq * t)
    r = int(fade_s * SR)
    if r:
        w = 0.5 - 0.5 * np.cos(np.pi * np.arange(r) / r)
        s[:r] *= w
        s[-r:] *= w[::-1]
    return s


def dumps(v) -> str:
    return json.dumps(v, allow_nan=False)


def test_vector_shape_and_json():
    v = measure_signal(noise(4.0), SR)
    dumps(v)
    for key in ("analyzer_version", "sample_rate", "channels", "duration_s", "P-03", "P-04", "P-05",
                "P-06", "P-07", "P-14", "LTAS", "health"):
        assert key in v
    assert v["channels"] == 2 and v["sample_rate"] == SR
    assert v["duration_s"] == pytest.approx(4.0)
    assert v["P-14"]["oversample"] == 4 and v["P-14"]["codec"] is None
    assert v["P-14"]["true_peak_dbtp"] == v["P-03"]["true_peak_dbtp"]
    assert set(v["P-04"]["bands"]) == {b.name for b in BANDS_P22}
    assert v["P-04"]["window"] == {"kind": "full_signal", "start_s": 0.0, "end_s": 4.0}


def test_identical_channels_correlate_and_fold_losslessly():
    m = noise(3.0, ch=1)
    v = measure_signal(np.hstack([m, m]), SR)
    for b in v["P-05"]["bands"].values():
        assert b["correlation"] == pytest.approx(1.0, abs=1e-9)
        assert b["side_ratio"] == pytest.approx(0.0, abs=1e-9)
    for b in v["P-06"]["bands"].values():
        assert b["level_change_db"] == pytest.approx(0.0, abs=1e-6)
        assert not b["cancelled"]


def test_inverted_channels_cancel():
    m = noise(3.0, ch=1)
    v = measure_signal(np.hstack([m, -m]), SR)
    dumps(v)
    for b in v["P-05"]["bands"].values():
        assert b["correlation"] == pytest.approx(-1.0, abs=1e-9)
        assert b["side_ratio"] == pytest.approx(1.0, abs=1e-9)
    for b in v["P-06"]["bands"].values():
        assert b["cancelled"] is True
        assert b["level_change_db"] is None and b["mono_loss_db"] is None
    assert v["P-06"]["worst_band"] is not None
    p = v["P-05"]["low_band_persistence"]
    assert p["negative_fraction"] == pytest.approx(1.0)
    assert p["longest_negative_run_s"] == pytest.approx(3.0, abs=0.11)


def test_uncorrelated_channels():
    v = measure_signal(noise(5.0), SR)
    full5, full6 = v["P-05"]["full_band"], v["P-06"]["full_band"]
    assert abs(full5["correlation"]) < 0.02
    assert full5["side_ratio"] == pytest.approx(0.5, abs=0.01)
    assert full6["level_change_db"] == pytest.approx(-3.01, abs=0.1)
    assert full6["mono_loss_db"] == pytest.approx(3.01, abs=0.1)


def test_low_band_persistence_only_flags_low_band():
    lo = sine(60.0, 4.0, 0.3)
    hi = noise(4.0, ch=1, amp=0.1)[:, 0]
    x = np.stack([lo + hi, -lo + hi], axis=1)   # low band anti-phase, highs identical
    p = low_band_negative_persistence(x, SR, cutoff_hz=120.0)
    assert p["negative_fraction"] > 0.95
    assert p["longest_negative_run_s"] > 3.5
    y = np.stack([lo + hi, lo - hi], axis=1)   # low band in phase, highs anti-phase
    q = low_band_negative_persistence(y, SR, cutoff_hz=120.0)
    assert q["negative_fraction"] == 0.0 and q["longest_negative_run_s"] == 0.0
    assert low_band_negative_persistence(lo, SR) is None   # mono


def test_mono_input_reports_null_stereo():
    v = measure_signal(sine(440.0, 2.0), SR)
    dumps(v)
    assert v["channels"] == 1
    assert v["P-05"]["available"] is False and v["P-05"]["bands"] is None
    assert v["P-06"]["available"] is False and v["P-06"]["bands"] is None
    assert v["P-05"]["note"]
    assert any("mono" in n for n in v["notes"])


def test_band_energy_ratios_sum_to_one():
    v = measure_signal(noise(3.0), SR)
    fr = [b["fraction"] for b in v["P-07"]["partition_bands"].values()]
    assert sum(fr) == pytest.approx(1.0, abs=1e-9)
    # P-07 overlapping bands: sub+bass+highmid+air+lowmid+mid >= 1 because of overlap
    assert sum(b["fraction"] for b in v["P-07"]["bands"].values()) >= 1.0


def test_band_energy_of_sine_lands_in_its_band():
    x = np.stack([sine(1000.0, 4.0, fade_s=0.01)] * 2, axis=1)
    e = band_energy(Spectrum(x, SR), BANDS_P22)
    assert e["bands"]["mid"]["fraction"] == pytest.approx(1.0, abs=1e-6)
    assert e["bands"]["mid"]["level_db"] == pytest.approx(20 * math.log10(0.5) - 3.01, abs=0.03)


def test_crest_of_sine():
    # Faded to avoid onset ringing of the band filter (an abrupt start is a broadband event).
    x = np.stack([sine(1000.0, 4.0, fade_s=0.01)] * 2, axis=1)
    c = band_crest(Spectrum(x, SR), BANDS_P22, x=x)
    assert c["bands"]["mid"]["crest_db"] == pytest.approx(3.01, abs=0.1)
    assert c["full_band"]["crest_db"] == pytest.approx(3.01, abs=0.05)
    low = np.stack([sine(40.0, 4.0, fade_s=0.1)] * 2, axis=1)
    c2 = band_crest(Spectrum(low, SR), BANDS_P22)
    assert c2["bands"]["sub"]["crest_db"] == pytest.approx(3.01, abs=0.2)


def test_bands_are_clipped_at_nyquist():
    b = clip_bands(BANDS_P22, 8000)
    names = [x.name for x in b]
    assert "air" not in names
    assert b[-1].name == "highmid" and b[-1].hi_hz == 4000.0
    v = measure_signal(noise(2.0, seed=3)[: 16000], 8000)
    dumps(v)
    assert "air" not in v["P-04"]["bands"]


def test_ltas_grids():
    v = measure_signal(noise(2.0), SR)
    erb, third = v["LTAS"]["erb"], v["LTAS"]["third_octave"]
    assert len(erb["center_hz"]) == len(erb["level_db"]) >= 35
    assert len(third["center_hz"]) == 30
    assert all(x is not None for x in third["level_db"])


def test_health_detection():
    x = noise(2.0, amp=0.05)
    x[100, 0] = np.nan
    x[200, 1] = np.inf
    x[:, 1] += 0.01                       # DC on the right channel
    x[1000:1004, 0] = 1.0                 # clipped run of 4
    x[2000:2002, 0] = -1.0                # run of 2: not counted
    v = measure_signal(x, SR)
    dumps(v)
    h = v["health"]
    assert h["nan_count"] == 1 and h["inf_count"] == 1 and h["sanitized"] is True
    assert h["dc_offset_db"][1] == pytest.approx(-40.0, abs=0.5)
    assert h["dc_offset_db"][0] < -55.0
    assert h["clipped_samples"] == 4 and h["clip_runs"] == 1
    assert v["P-03"]["integrated_lufs"] is not None


def test_compare_lowers_the_louder():
    a = noise(4.0, seed=1, amp=0.2)
    b = noise(4.0, seed=2, amp=0.1)
    r = compare(a, SR, b, SR)
    dumps(r)
    assert r["matched_side"] == "a"
    assert r["match_gain_db"] == pytest.approx(-6.02, abs=0.1)
    after = r["after_match"]
    assert after["a"]["P-03"]["integrated_lufs"] == pytest.approx(after["b"]["P-03"]["integrated_lufs"], abs=0.01)
    assert after["b"] == r["before"]["b"]   # the quieter side is untouched
    d = r["deltas"]["P-03/integrated_lufs"]
    assert d["delta"] == pytest.approx(0.0, abs=0.01)
    assert d["perceived_ratio"] == pytest.approx(1.0, abs=0.01)
    before = r["before"]["integrated_delta"]
    assert before["perceived_ratio"] == pytest.approx(2 ** (before["delta"] / 10.0))
    assert r["deltas"]["P-03/lra_lu"]["perceived_ratio"] is None
    # swapped order lowers b
    r2 = compare(b, SR, a, SR)
    assert r2["matched_side"] == "b" and r2["match_gain_db"] < 0


def test_compare_rejects_rate_mismatch_and_silence():
    with pytest.raises(InputError):
        compare(noise(1.0), SR, noise(1.0), 44100)
    with pytest.raises(InputError):
        compare(np.zeros((SR, 2)), SR, noise(1.0), SR)


def test_compare_mono_vs_stereo():
    r = compare(noise(2.0, ch=1), SR, noise(2.0, seed=5), SR)
    dumps(r)
    assert not any(k.startswith("P-05") for k in r["deltas"])


@pytest.mark.slow
def test_performance_100s_stereo():
    import time
    x = noise(100.0)
    t0 = time.perf_counter()
    measure_signal(x, SR)
    # Target is ~4-5 s on an idle machine; the bound is loose so shared CI hosts do not flake.
    assert time.perf_counter() - t0 < 30.0


def test_measure_file_roundtrip(tmp_path):
    import soundfile as sf
    x = np.stack([sine(1000.0, 3.0, amp=10 ** (-23 / 20))] * 2, axis=1)
    p = tmp_path / "tone file.wav"
    sf.write(str(p), x, SR, subtype="FLOAT")
    from mankomix.core.measure import measure_file
    v = measure_file(p)
    dumps(v)
    assert v["source"] == {"file_name": "tone file.wav"}
    assert v["P-03"]["integrated_lufs"] == pytest.approx(-23.0, abs=0.1)
