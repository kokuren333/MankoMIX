"""Tests for core/analysis/stems.py (stem-context proxies P-02, P-08, P-09, P-10,
P-12, P-13, P-15, P-22). All signals are synthesized in memory."""

from __future__ import annotations

import json
import math

import numpy as np
import pytest
from scipy.signal import fftconvolve

from mankomix.core.analysis import stems as S

SR = 48000


def _t(dur):
    return np.arange(int(dur * SR)) / SR


def _harmonic(f0, dur, amp, n_harm=20, fmax=6000.0, tilt=1.0):
    t = _t(dur)
    y = np.zeros_like(t)
    for k in range(1, n_harm + 1):
        if k * f0 > fmax:
            break
        y += np.sin(2 * np.pi * k * f0 * t + 0.3 * k) / k ** tilt
    return amp * y / np.max(np.abs(y))


def _band_noise(lo, hi, dur, amp, seed=0, stereo=True):
    rng = np.random.default_rng(seed)
    n = int(dur * SR)
    out = []
    for _ in range(2 if stereo else 1):
        X = np.fft.rfft(rng.standard_normal(n))
        f = np.fft.rfftfreq(n, 1 / SR)
        X[(f < lo) | (f >= hi)] = 0
        y = np.fft.irfft(X, n)
        out.append(amp * y / np.sqrt(np.mean(y ** 2)))
    return np.stack(out, axis=1)


def _fft_gain(x, lo, hi, gain_db):
    x = np.atleast_2d(x.T).T
    out = np.empty_like(x)
    n = x.shape[0]
    f = np.fft.rfftfreq(n, 1 / SR)
    g = np.where((f >= lo) & (f < hi), 10 ** (gain_db / 20), 1.0)
    for c in range(x.shape[1]):
        out[:, c] = np.fft.irfft(np.fft.rfft(x[:, c]) * g, n)
    return out


def _jsonable(d):
    json.dumps(d, allow_nan=False)
    return d


META_VP = {
    "vox": {"role": "vocals", "is_lead": True},
    "pad": {"role": "synth"},
}


# --------------------------------------------------------------------------
# f0 / features


@pytest.mark.parametrize("f0", [55.0, 110.0])
def test_f0_estimator_within_2_percent(f0):
    x = 0.3 * np.sin(2 * np.pi * f0 * _t(3.0))
    feats = _jsonable(S.stem_features(x, SR))
    assert feats["f0"]["median_f0_hz"] == pytest.approx(f0, rel=0.02)
    assert feats["f0"]["lowest_f0_hz"] == pytest.approx(f0, rel=0.02)
    assert feats["f0"]["f0_confidence"] > 0.8


def test_stem_features_pan_width_activity():
    t = _t(4.0)
    s = 0.3 * np.sin(2 * np.pi * 330 * t)
    s[: SR] = 0.0  # silent first second
    x = np.stack([0.5 * s, s], axis=1)
    f = _jsonable(S.stem_features(x, SR))
    assert f["stereo"]["pan"] > 0.3             # right-heavy
    assert f["stereo"]["correlation"] == pytest.approx(1.0, abs=1e-6)
    assert 0.6 < f["activity"]["ratio"] < 0.85
    assert f["activity"]["intervals_s"][0][0] == pytest.approx(1.0, abs=0.1)
    assert f["spectral_centroid_hz"] == pytest.approx(330, rel=0.05)


# --------------------------------------------------------------------------
# P-02 masking


def _vox(dur=4.0, amp=0.05):
    return _harmonic(250.0, dur, amp, tilt=0.7)


def test_vs_lead_masking_rises_with_pad_and_cut_reduces_it():
    dur = 4.0
    vox = _vox(dur)
    quiet_pad = _band_noise(200, 800, dur, 0.005, seed=1)
    loud_pad = _band_noise(200, 800, dur, 0.15, seed=1)
    r_quiet = S.masking_matrix({"vox": vox, "pad": quiet_pad}, SR, META_VP)
    r_loud = _jsonable(S.masking_matrix({"vox": vox, "pad": loud_pad}, SR, META_VP))
    lm_q = r_quiet["vs_lead"]["low_mid"]["buried_db"]
    lm_l = r_loud["vs_lead"]["low_mid"]["buried_db"]
    assert lm_l > lm_q + 3.0
    assert r_loud["vs_lead"]["lead"] == "vox"
    assert r_loud["vs_lead"]["lead_source"] == "declared"
    assert r_loud["vs_lead"]["low_mid"]["top_maskers"][0]["track"] == "pad"
    assert 0.0 <= r_loud["vs_lead"]["penalty"] <= 1.0
    # R-05: cut the competing pad by 3 dB in 200-800 Hz instead of raising the lead
    cut_pad = _fft_gain(loud_pad, 200, 800, -3.0)
    r_cut = S.masking_matrix({"vox": vox, "pad": cut_pad}, SR, META_VP)
    lm_c = r_cut["vs_lead"]["low_mid"]["buried_db"]
    assert lm_c < lm_l - 1.5
    assert r_cut["vs_lead"]["penalty"] <= r_loud["vs_lead"]["penalty"]


def test_importance_weighting_lead_vs_fx():
    dur = 3.0
    t = _t(dur)
    masker = _band_noise(400, 600, dur, 0.2, seed=2)
    low_tone = 0.02 * np.sin(2 * np.pi * 500 * t)
    high_tone = 0.02 * np.sin(2 * np.pi * 3000 * t)
    meta = {"lead": {"role": "vocals", "is_lead": True}, "fx": {"role": "fx"}, "pad": {"role": "synth"}}
    # A: the lead sits under the masker; B: the fx does (same buried amount)
    ra = S.masking_matrix({"lead": low_tone, "fx": high_tone, "pad": masker}, SR, meta)
    rb = S.masking_matrix({"lead": high_tone, "fx": low_tone, "pad": masker}, SR, meta)
    assert ra["per_target"]["lead"]["buried_db"] == pytest.approx(rb["per_target"]["fx"]["buried_db"], abs=0.5)
    assert ra["per_target"]["lead"]["buried_db"] > 3.0
    assert ra["per_target"]["lead"]["importance"] > ra["per_target"]["fx"]["importance"]
    assert ra["overall"]["value"] > rb["overall"]["value"] + 1.0
    # declared importance wins over the default
    meta2 = {k: dict(v) for k, v in meta.items()}
    meta2["fx"]["importance"] = {"value": 5.0, "source": "user"}
    rc = S.masking_matrix({"lead": high_tone, "fx": low_tone, "pad": masker}, SR, meta2)
    assert rc["per_target"]["fx"]["importance"] == 5.0
    assert rc["overall"]["value"] > rb["overall"]["value"]


def test_low_to_mid_rises_with_loud_bass():
    dur = 3.0
    t = _t(dur)
    vox = _vox(dur, 0.05)
    pad = _band_noise(300, 700, dur, 0.01, seed=3)
    bass = 0.6 * np.sin(2 * np.pi * 90 * t) + 0.3 * np.sin(2 * np.pi * 180 * t)
    meta = {**META_VP, "bass": {"role": "bass"}}
    r0 = S.masking_matrix({"vox": vox, "pad": pad}, SR, META_VP)
    r1 = _jsonable(S.masking_matrix({"vox": vox, "pad": pad, "bass": bass}, SR, meta))
    v0 = r0["low_to_mid"]["value"] or 0.0
    assert r1["low_to_mid"]["value"] > v0 + 1.0
    assert r1["low_to_mid"]["spill_db"] is not None
    assert r1["low_to_mid"]["penalty"] >= (r0["low_to_mid"]["penalty"] or 0.0)


def _kick(dur, f=55.0, period=0.5, amp=0.8, decay=0.12):
    t = _t(dur)
    y = np.zeros_like(t)
    n_p = int(period * SR)
    k = np.arange(n_p) / SR
    hit = amp * np.sin(2 * np.pi * f * k) * np.exp(-k / decay)
    for s in range(0, t.size - n_p + 1, n_p):
        y[s:s + n_p] += hit
    return y


def test_time_axis_sidechain_unmasks_kick():
    dur = 4.0
    t = _t(dur)
    kick = _kick(dur)
    bass = 0.5 * np.sin(2 * np.pi * 58 * t)
    meta = {"kick": {"role": "drums"}, "bass": {"role": "bass"}}
    r = _jsonable(S.masking_matrix({"kick": kick, "bass": bass}, SR, meta, bpm=120))
    ta = r["time_axis"]
    assert ta["available"] and ta["kick"] == "kick" and ta["bass"] == "bass"
    assert ta["kick_buried_by_bass_db"] > 0
    assert ta["unmask_db"] > 0
    assert ta["ducking"]["release_from"] == "bpm_note_value"
    assert ta["ducking"]["suggested_release_note"] in ("1/16", "1/8", "1/4")
    assert 0.0 <= ta["penalty"] <= 1.0


# --------------------------------------------------------------------------
# P-22


def test_band_density_counts_owners():
    dur = 3.0
    meta = {k: {"role": "synth"} for k in ("a", "b", "c", "d")}
    stems3 = {
        "a": _band_noise(260, 480, dur, 0.1, seed=10),
        "b": _band_noise(260, 480, dur, 0.1, seed=11),
        "c": _band_noise(260, 480, dur, 0.1, seed=12),
        "d": _band_noise(2500, 5000, dur, 0.1, seed=13),
    }
    r3 = _jsonable(S.band_density(stems3, SR, meta))
    lm = r3["sections"][0]["bands"]["lowmid"]
    assert lm["count"] >= 3
    assert {o["track"] for o in lm["owners"]} >= {"a", "b", "c"}
    assert lm["penalty"] > 0
    stems1 = {
        "a": _band_noise(260, 480, dur, 0.1, seed=10),
        "b": _band_noise(700, 1500, dur, 0.1, seed=11),
        "c": _band_noise(70, 200, dur, 0.1, seed=12),
        "d": _band_noise(2500, 5000, dur, 0.1, seed=13),
    }
    r1 = S.band_density(stems1, SR, meta, sections=[{"id": "s1", "start": 0, "length": SR},
                                                    {"id": "s2", "start_s": 1.0, "end_s": 3.0}])
    assert [s["id"] for s in r1["sections"]] == ["s1", "s2"]
    for s in r1["sections"]:
        assert s["bands"]["lowmid"]["count"] == 1
        assert s["bands"]["lowmid"]["owners"][0]["track"] == "a"
        assert s["bands"]["lowmid"]["penalty"] == 0.0


# --------------------------------------------------------------------------
# P-13


def test_low_tuning_kick_bass_cents():
    dur = 4.0
    t = _t(dur)
    stems = {"kick": _kick(dur, 55.0), "bass": 0.4 * np.sin(2 * np.pi * 58 * t)}
    meta = {"kick": {"role": "drums"}, "bass": {"role": "bass"}}
    r = _jsonable(S.low_tuning(stems, SR, meta, key_tonic_hz=110.0))
    expected = 1200 * math.log2(58 / 55)  # ~92 cents
    assert r["kick_f0_hz"] == pytest.approx(55.0, rel=0.02)
    assert r["bass_f0_hz"] == pytest.approx(58.0, rel=0.01)
    assert r["cents_difference"] == pytest.approx(expected, abs=15.0)
    assert r["beating_risk"] > 0.5
    assert r["tonic"]["folded_hz"] == pytest.approx(55.0)
    assert r["tonic"]["in_sub_band"] is True
    assert r["tonic"]["policy_hint"] == "use_fundamental"


# --------------------------------------------------------------------------
# P-08


def test_harmonic_completion_saw_vs_sine():
    t = _t(3.0)
    sine = 0.4 * np.sin(2 * np.pi * 55 * t)
    saw = 0.4 * (2 * ((55 * t) % 1.0) - 1.0)
    rs = _jsonable(S.harmonic_completion(sine, SR))
    rw = _jsonable(S.harmonic_completion(saw, SR))
    assert rw["index_db"] > rs["index_db"] + 20
    assert rw["h2_db"] == pytest.approx(-6.0, abs=1.5)
    assert rw["penalty"] < rs["penalty"]
    rf = S.harmonic_completion(saw, SR, f0=55.0)
    assert rf["f0_source"] == "given"
    assert rf["index_db"] == pytest.approx(rw["index_db"], abs=1.0)
    mw = _jsonable(S.missing_fundamental_check(saw, SR))
    ms = S.missing_fundamental_check(sine, SR)
    assert mw["preserved"] is True
    assert ms["preserved"] is False


# --------------------------------------------------------------------------
# P-10


def test_lead_band_difference_sign():
    dur = 3.0
    acc = _band_noise(300, 5000, dur, 0.05, seed=5)
    loud = S.lead_band_difference({"vox": _vox(dur, 0.5), "acc": acc}, SR,
                                  {"vox": {"role": "vocals"}, "acc": {"role": "guitar"}})
    quiet = S.lead_band_difference({"vox": _vox(dur, 0.005), "acc": acc}, SR,
                                   {"vox": {"role": "vocals"}, "acc": {"role": "guitar"}})
    _jsonable(loud)
    assert loud["value"] > 3.0 and quiet["value"] < -3.0
    assert loud["lead_is_estimate"] is True and loud["lead_source"] == "estimated_from_role"
    assert quiet["verdict"] == "buried"
    assert loud["verdict"] in ("ok", "floating")
    g = S.lead_band_difference({"vox": _vox(dur, 0.5), "acc": acc}, SR,
                               {"vox": {"role": "vocals", "is_lead": True}, "acc": {"role": "guitar"}},
                               genre="edm")
    assert g["target_db"] == [0.0, 3.0] and g["target_source"].startswith("genre_prior")
    assert g["verdict"] == "floating" and g["penalty"] > 0


# --------------------------------------------------------------------------
# P-09 / P-15


def _plucks(dur, amp, f=440.0, period=0.5, decay=0.04):
    t = _t(dur)
    y = np.zeros_like(t)
    n_p = int(period * SR)
    k = np.arange(n_p) / SR
    hit = np.sin(2 * np.pi * f * k) * np.exp(-k / decay)
    for s in range(0, t.size - n_p + 1, n_p):
        y[s:s + n_p] += hit
    return amp * y


def _reverberate(x, rt60=1.2, wet=1.0, seed=7):
    rng = np.random.default_rng(seed)
    n = int(rt60 * SR)
    k = np.arange(n) / SR
    ir = rng.standard_normal(n) * 10 ** (-3 * k / rt60) * 0.02
    ir[0] = 0.0
    y = fftconvolve(x, ir)[: x.size]
    return x + wet * y / np.max(np.abs(y)) * np.max(np.abs(x))


def test_depth_order_dry_loud_vs_reverberant_quiet():
    dur = 4.0
    dry = _plucks(dur, 0.5)
    wet = _reverberate(_plucks(dur, 0.1, f=660.0), wet=2.0)
    stems = {"dry": dry, "wet": wet}
    meta = {"dry": {"role": "vocals", "is_lead": True}, "wet": {"role": "synth"}}
    ok = _jsonable(S.depth_order(stems, SR, meta, declared_order=["dry", "wet"]))
    assert ok["estimated_order_front_to_back"] == ["dry", "wet"]
    assert ok["per_stem"]["dry"]["dr_db"] > ok["per_stem"]["wet"]["dr_db"]
    assert ok["kendall_tau"] == pytest.approx(1.0)
    assert ok["penalty"] == pytest.approx(0.0)
    bad = S.depth_order(stems, SR, meta, declared_order=["wet", "dry"])
    assert bad["penalty"] == pytest.approx(1.0)
    dflt = S.depth_order(stems, SR, meta)
    assert dflt["declared_order_source"].startswith("lead_front_default")
    assert dflt["penalty"] == pytest.approx(0.0)


def test_reverb_metrics_wet_longer_than_dry():
    dur = 4.0
    dry = _plucks(dur, 0.5, period=1.0, decay=0.02)
    wet = _reverberate(_plucks(dur, 0.5, period=1.0, decay=0.02), rt60=1.0, wet=1.0)
    rd = _jsonable(S.reverb_metrics(dry, SR))
    rw = _jsonable(S.reverb_metrics(wet, SR))
    assert rd["rough"] is True
    assert rd["dr_db"] > rw["dr_db"]
    assert rw["rt60_mid_s"] is not None and rd["rt60_mid_s"] is not None
    assert rw["rt60_mid_s"] > rd["rt60_mid_s"]
    assert 0.0 <= rw["penalty"] <= 1.0


# --------------------------------------------------------------------------
# P-12


def test_transient_retention():
    x = _plucks(3.0, 0.8, f=200.0, decay=0.08) + _band_noise(2000, 6000, 3.0, 0.01, seed=4, stereo=False)[:, 0]
    same = _jsonable(S.transient_retention(x, x, SR))
    assert same["penalty"] == pytest.approx(0.0)
    squashed = np.tanh(6 * x) / 6
    r = _jsonable(S.transient_retention(x, squashed, SR))
    assert r["mean_crest_loss_db"] > 1.0
    assert r["penalty"] > 0.0


# --------------------------------------------------------------------------
# Bundle


def test_measure_stem_context_bundle_json_safe():
    dur = 4.0
    t = _t(dur)
    stems = {
        "vox": _vox(dur, 0.1),
        "pad": _band_noise(200, 800, dur, 0.05, seed=1),
        "kick": _kick(dur),
        "bass": 0.4 * (2 * ((58 * t) % 1.0) - 1.0),
        "silent": np.zeros((int(dur * SR) // 2, 2)),   # shorter and silent
    }
    meta = {"vox": {"role": "vocals", "is_lead": True}, "pad": {"role": "synth"},
            "kick": {"role": "drums"}, "bass": {"role": "bass"}, "silent": {"role": "fx"}}
    sections = [{"id": "verse", "start": 0, "length": 2 * SR},
                {"id": "chorus", "start": 2 * SR, "length": 2 * SR}]
    r = S.measure_stem_context(stems, SR, meta, genre="jpop", declared_order=["vox", "pad", "bass", "kick"],
                               sections=sections, key_tonic_hz=220.0, bpm=120,
                               before=stems["vox"], after=stems["vox"] * 0.5)
    json.dumps(r, allow_nan=False)
    for key in ("features", "P-02", "P-08", "P-09", "P-10", "P-12", "P-13", "P-15", "P-22"):
        assert key in r
    assert set(r["features"]) == set(stems)
    assert r["P-08"]["track"] == "bass"
    assert r["P-12"]["penalty"] == pytest.approx(0.0)
    assert len(r["P-02"]["by_section"]) == 2
    assert r["P-15"]["lead"] == "vox"
    for p in (r["P-02"]["overall"]["penalty"], r["P-02"]["vs_lead"]["penalty"], r["P-09"]["penalty"],
              r["P-10"]["penalty"], r["P-13"]["penalty"], r["P-22"]["penalty"]):
        assert p is None or 0.0 <= p <= 1.0
    r2 = S.measure_stem_context({"vox": stems["vox"]}, SR, {"vox": {"role": "vocals"}})
    json.dumps(r2, allow_nan=False)
    assert r2["P-12"] is None and r2["P-08"] is None
