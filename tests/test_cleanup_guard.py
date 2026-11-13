"""Cleanup stage: S-08 noise-return guard, P-21 side effects, delta, determinism."""

from __future__ import annotations

import numpy as np
import pytest

from mankomix.core.cleanup import (noise_baseline, noise_return_check, plan_cleanup, run_cleanup,
                                   side_effects)
from tests.fixtures import synth
from tests.test_cleanup_policy import SR, music


def _fft_gain(x, gain_fn):
    spec = np.fft.rfft(x, axis=0)
    f = np.fft.rfftfreq(x.shape[0], 1.0 / SR)
    return np.fft.irfft(spec * gain_fn(f)[:, None], x.shape[0], axis=0)


def _hf_shelf_db(f, gain_db=6.0, f0=6000.0, f1=10000.0):
    ramp = np.clip((f - f0) / (f1 - f0), 0.0, 1.0)
    return 10.0 ** (gain_db * (0.5 - 0.5 * np.cos(np.pi * ramp)) / 20.0)


@pytest.fixture(scope="module")
def cleaned():
    x = synth.add_shimmer(music(seconds=5.0, seed=2), SR, depth_db=-24.0, seed=11)
    res = run_cleanup(x, SR)
    return x, res


def test_noise_return_guard(cleaned):
    _, res = cleaned
    base = res.report["noise_baseline"]
    assert base == noise_baseline(res.audio, SR) | {"integrated_lufs": base["integrated_lufs"]}
    y = res.audio
    # pure gain change: passes after compensation (given or estimated)
    g = 10.0 ** (4.0 / 20.0)
    ok = noise_return_check(base, y * g, SR, gain_db=4.0)
    assert ok["pass"] is True and ok["suggestions"] == []
    for k in ("noise_floor_dbfs", "shimmer_index_db"):
        assert abs(ok["deltas"][k]["delta_db"]) < 0.1
    est = noise_return_check(base, y * g, SR)
    assert est["gain_source"] == "integrated_loudness" and abs(est["gain_db"] - 4.0) < 0.1
    assert est["pass"] is True
    # +6 dB HF shelf with the same gain: fails, suggests less HF boost / limiter drive
    shelf = _fft_gain(y, _hf_shelf_db) * g
    bad = noise_return_check(base, shelf, SR, gain_db=4.0)
    assert bad["pass"] is False
    assert bad["deltas"]["shimmer_index_db"]["pass"] is False
    assert bad["deltas"]["shimmer_index_db"]["delta_db"] > 3.0
    actions = {s["action"] for s in bad["suggestions"]}
    assert "reduce_hf_boost" in actions and "reduce_limiter_drive" in actions


def test_p21_side_effects_measured():
    x = music(seconds=3.0, seed=3)
    same = side_effects(x, x, SR)
    assert same["pass"] is True and same["lowmid_250_500_change_db"] == 0.0
    assert all(b["change_db"] in (0.0, None) for b in same["width_change"].values())
    # narrow the image above 2 kHz (side -6 dB): width loss is measured and fails
    m = 0.5 * (x[:, 0] + x[:, 1])
    s = 0.5 * (x[:, 0] - x[:, 1])
    s_n = _fft_gain(s[:, None], lambda f: np.where(f >= 2000.0, 0.5, 1.0))[:, 0]
    narrow = np.stack([m + s_n, m - s_n], axis=1)
    r = side_effects(x, narrow, SR)
    assert r["width_change"]["air"]["change_db"] < -4.0
    assert r["width_change"]["bass"]["change_db"] == pytest.approx(0.0, abs=0.01)
    assert r["pass"] is False
    # thin / thicken 250-500 Hz by 3 dB: measured and fails
    boosted = _fft_gain(x, lambda f: np.where((f >= 250.0) & (f < 500.0), 10.0 ** (3.0 / 20.0), 1.0))
    r2 = side_effects(x, boosted, SR)
    assert r2["lowmid_250_500_change_db"] == pytest.approx(3.0, abs=0.05)
    assert r2["pass"] is False
    # mono input: width not applicable
    r3 = side_effects(x.mean(axis=1), x.mean(axis=1), SR)
    assert r3["width_change"] is None and r3["pass"] is True


def test_cleanup_report_p21_and_delta(cleaned):
    x, res = cleaned
    assert res.delta.shape == x.shape
    assert np.array_equal(res.delta, x - res.audio)
    p21 = res.report["p21"]
    assert p21["lowmid_250_500_change_db"] == pytest.approx(0.0, abs=1e-6)
    assert p21["width_change"]["bass"]["change_db"] == pytest.approx(0.0, abs=1e-6)
    assert "oversuppression" in res.report and res.report["oversuppression"]["flagged"] is False
    assert np.all(np.isfinite(res.audio))


def test_determinism(cleaned):
    x, res = cleaned
    again = run_cleanup(x, SR)
    assert np.array_equal(again.audio, res.audio)
    assert np.array_equal(again.delta, res.delta)
    assert again.report["p16_after"] == res.report["p16_after"]


def test_oversuppression_rerun_is_recorded():
    x = synth.add_shimmer(music(seconds=3.0, seed=4), SR, depth_db=-24.0, seed=12)
    plan = plan_cleanup(x, SR, overrides={"policy": {"oversuppression": {
        "corr_threshold": -1.0, "min_removed_db": -400.0}}})
    res = run_cleanup(x, SR, plan)
    ov = res.report["oversuppression"]
    assert ov["rerun"] is True
    assert ov["rerun_detail"]["strength_factor"] == 0.5
    assert res.report["steps"]["spectral_reduction"]["strength"] == pytest.approx(0.5)
    assert res.report["s07"]["pass"] is True
