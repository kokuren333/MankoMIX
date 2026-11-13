"""OF-5 translation gate (SPEC 4.5, 5.2 playback_assumptions)."""
from __future__ import annotations

import json

import numpy as np
import pytest
from scipy.signal import butter, sosfilt

from mankomix.core import gate as G
from tests.fixtures import synth

SR = 48000
DUR = 3.0


def _t():
    return np.arange(int(SR * DUR)) / SR


def _hats(seed=4) -> np.ndarray:
    rng = np.random.default_rng(seed)
    sos = butter(4, [3000.0, 9000.0], btype="bandpass", fs=SR, output="sos")
    t = _t()
    return 0.05 * sosfilt(sos, rng.standard_normal(t.size)) * (np.mod(t, 0.25) < 0.05)


def _stereo(mono: np.ndarray, width: float = 0.0, seed: int = 9) -> np.ndarray:
    rng = np.random.default_rng(seed)
    side = width * 0.01 * rng.standard_normal(mono.size)
    return np.stack([mono + side, mono - side], axis=1)


def _sine_bass():
    return 0.4 * np.sin(2 * np.pi * 55.0 * _t())


def _saw_bass():
    t = _t()
    return 0.4 * (2 * ((55.0 * t) % 1.0) - 1.0)


def _check(res, cid):
    return next(c for c in res["checks"] if c["id"] == cid)


def test_mono_cancelling_low_band_fails_check_2():
    x = _stereo(_saw_bass() + _hats())
    ok = G.evaluate_gate(x, SR, profile="spotify")
    assert _check(ok, "mono_fold_loss_within_limit")["status"] == "pass"
    bad = synth.antiphase_low(x, SR, below_hz=120.0)
    res = G.evaluate_gate(bad, SR, profile="spotify")
    c2 = _check(res, "mono_fold_loss_within_limit")
    assert c2["status"] == "fail" and c2["values"]["problems"]
    assert c2["threshold"]["low_band_max_db"] == 1.5
    assert res["status"] == "fail" and res["pass"] is False
    assert any(s["check"] == "mono_fold_loss_within_limit" for s in res["corrective_suggestions"])
    json.dumps(res, allow_nan=False)


def test_sine_bass_loses_pitch_without_fundamental_saw_keeps_it():
    sine = G.evaluate_gate(_stereo(_sine_bass() + _hats()), SR, profile="spotify")
    saw = G.evaluate_gate(_stereo(_saw_bass() + _hats()), SR, profile="spotify")
    c_sine = _check(sine, "pitch_preserved_without_fundamental")
    c_saw = _check(saw, "pitch_preserved_without_fundamental")
    assert c_sine["status"] == "fail" and c_saw["status"] == "pass"
    assert "proxy" in c_saw["values"]["source"]
    assert c_saw["values"]["harmonic_index_db"] > c_sine["values"]["harmonic_index_db"]
    # with a bass stem the stem is used directly
    stems = {"bass": _stereo(_sine_bass()), "hats": _stereo(_hats())}
    res = G.evaluate_gate(_stereo(_sine_bass() + _hats()), SR, stems=stems,
                          meta={"bass": {"role": "bass"}, "hats": {"role": "drums"}}, profile="spotify")
    c = _check(res, "pitch_preserved_without_fundamental")
    assert c["status"] == "fail" and c["values"]["source"] == "bass stem"


def test_2mix_only_lead_checks_are_not_evaluated_and_not_a_pass():
    res = G.evaluate_gate(_stereo(_saw_bass() + _hats()), SR, profile="spotify")
    for cid in ("band_limited_lead_preserved", "low_level_balance_preserved"):
        c = _check(res, cid)
        assert c["status"] == "not_evaluated" and c["reason"] == "not_evaluable_without_stems"
        assert c["required"] is True
    assert res["status"] == "incomplete" and res["pass"] is False and res["failed"] is False


def _vocal(f0=220.0):
    t = _t()
    v = sum((0.5 / k) * np.sin(2 * np.pi * k * f0 * t) for k in range(1, 12))
    return 0.3 * v * (0.6 + 0.4 * np.sin(2 * np.pi * 3 * t) ** 2)


def test_lead_checks_with_stems():
    acc = _saw_bass() * 0.5 + _hats()
    stems = {"vox": _stereo(_vocal()), "band": _stereo(acc)}
    meta = {"vox": {"role": "vocals"}, "band": {"role": "other"}}
    mix = stems["vox"] + stems["band"]
    res = G.evaluate_gate(mix, SR, stems=stems, meta=meta, profile="spotify")
    assert res["lead"] == "vox"
    c1 = _check(res, "band_limited_lead_preserved")
    c3 = _check(res, "low_level_balance_preserved")
    assert c1["status"] == "pass" and c3["status"] == "pass"
    assert c1["values"]["lead_vs_acc_band_limited_db"] >= c1["values"]["lead_vs_acc_full_db"] - 3.0
    # a "lead" that lives below the small-speaker band collapses
    low_lead = {"vox": _stereo(0.4 * np.sin(2 * np.pi * 70.0 * _t())), "band": _stereo(_vocal(330.0))}
    res = G.evaluate_gate(low_lead["vox"] + low_lead["band"], SR, stems=low_lead, meta=meta, profile="spotify")
    assert _check(res, "band_limited_lead_preserved")["status"] == "fail"
    assert _check(res, "low_level_balance_preserved")["status"] == "fail"


def test_profile_decides_which_checks_apply():
    x = _stereo(_saw_bass() + _hats())
    res = G.evaluate_gate(x, SR, profile="club")
    assert res["playback_assumptions"]["mono_fold_strict"] is True
    assert _check(res, "mono_fold_loss_within_limit")["threshold"]["low_band_max_db"] == pytest.approx(0.5)
    for cid in ("band_limited_lead_preserved", "low_level_balance_preserved", "pitch_preserved_without_fundamental"):
        c = _check(res, cid)
        assert c["required"] is False and c["reason"] == "not_required_by_profile"
    assert res["status"] == "pass" and res["pass"] is True
