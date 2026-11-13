"""Cleanup stage: shimmer index, HF ceiling, clicks, deterministic completion."""

from __future__ import annotations

import numpy as np
import pytest
from scipy.signal import butter, sosfiltfilt

from mankomix.core.cleanup import (detect_clicks, diagnose, noise_shimmer_metrics,
                                   plan_cleanup, run_cleanup)
from tests.fixtures import synth
from tests.test_cleanup_policy import SR, music


@pytest.fixture(scope="module")
def clean():
    return music(seconds=5.0, seed=1)


def _hp_energy(x, lo_hz, a, b):
    sos = butter(4, lo_hz, btype="highpass", fs=SR, output="sos")
    y = sosfiltfilt(sos, np.asarray(x)[:, :], axis=0)
    return float(np.sum(y[a:b] ** 2))


def test_shimmer_index_rises_and_cleanup_reduces_it(clean):
    x = synth.add_shimmer(clean, SR, depth_db=-24.0, seed=7)
    m_clean = noise_shimmer_metrics(clean, SR)
    m_shim = noise_shimmer_metrics(x, SR)
    assert m_shim["shimmer_index_db"] >= m_clean["shimmer_index_db"] + 10.0
    assert m_shim["shimmer_flatness"] > m_clean["shimmer_flatness"]
    d = diagnose(x, SR)
    assert d["steps"]["spectral_reduction"] == "run"
    assert d["steps"]["protection"] == "run"
    res = run_cleanup(x, SR)
    rep = res.report
    before = rep["p16_before"]["shimmer_index_db"]
    after = rep["p16_after"]["shimmer_index_db"]
    assert after <= before - 3.0
    assert rep["recheck"]["shimmer_index_change_db"] <= -3.0
    # the shimmer band lost energy, the protected low band none
    assert rep["removed_energy"]["shimmer"]["removed_rel_db"] > -30.0
    low = rep["removed_energy"]["low"]["removed_rel_db"]
    assert low is None or low < -100.0
    # multi-pass, limited per pass
    passes = rep["steps"]["spectral_reduction"]["channels"]["mid"]["passes"]
    assert len(passes) >= 2
    assert all(p["max_added_db"] <= 6.0 + 1e-6 for p in passes)


def test_weaker_shimmer_is_still_reduced(clean):
    x = synth.add_shimmer(clean, SR, depth_db=-30.0, seed=8)
    res = run_cleanup(x, SR)
    rep = res.report
    assert rep["steps_planned"]["spectral_reduction"] in ("run", "light")
    assert rep["p16_after"]["shimmer_index_db"] <= rep["p16_before"]["shimmer_index_db"] - 3.0


def test_hf_ceiling_detected(clean):
    assert noise_shimmer_metrics(clean, SR, with_clicks=False)["hf_ceiling_hz"] is None
    x = synth.add_hf_ceiling(clean, SR, 16000.0)
    m = noise_shimmer_metrics(x, SR, with_clicks=False)
    assert m["hf_ceiling_hz"] is not None
    assert abs(m["hf_ceiling_hz"] - 16000.0) <= 1000.0
    d = diagnose(x, SR)
    # completion is optional: proposed off, but explained
    assert d["steps"]["completion"] == "skip"
    assert any("ceiling" in r for r in d["reasons"]["completion"])


def test_hf_ceiling_other_cutoff(clean):
    x = synth.add_hf_ceiling(clean, SR, 12000.0)
    fc = noise_shimmer_metrics(x, SR, with_clicks=False)["hf_ceiling_hz"]
    assert fc is not None and abs(fc - 12000.0) <= 1000.0


def test_deterministic_completion_when_enabled(clean):
    x = synth.add_hf_ceiling(clean, SR, 16000.0)
    plan = plan_cleanup(x, SR, overrides={"completion": "run"})
    assert plan["steps"]["completion"]["action"] == "run"
    res = run_cleanup(x, SR, plan)
    rec = res.report["steps"]["completion"]
    assert rec["method"] == "dsp_harmonic" and rec["neural"] is False and rec["deterministic"] is True
    assert res.report["neural_completion_used"] is False
    # energy appeared above the ceiling, at a low level
    spec_in = np.abs(np.fft.rfft(x[:, 0])) ** 2
    spec_out = np.abs(np.fft.rfft(res.audio[:, 0])) ** 2
    f = np.fft.rfftfreq(x.shape[0], 1.0 / SR)
    above = (f > 16500.0) & (f < 19000.0)
    below = (f > 13000.0) & (f < 15000.0)
    assert spec_out[above].sum() > 100.0 * spec_in[above].sum()
    assert spec_out[above].sum() < spec_out[below].sum()
    assert res.report["s07"]["pass"] is True
    # deterministic
    res2 = run_cleanup(x, SR, plan)
    assert np.array_equal(res.audio, res2.audio)


def test_head_click_detected_and_repaired(clean):
    x = synth.add_head_click(clean, SR)  # at the very first sample
    d = diagnose(x, SR)
    assert d["metrics"]["head_click"] is True
    assert d["steps"]["click_repair"] == "run"
    res = run_cleanup(x, SR)
    rep = res.report
    rep_clicks = rep["steps"]["click_repair"]["repaired"]
    assert len(rep_clicks) >= 1 and rep_clicks[0]["start"] == 0
    assert rep["p16_after"]["head_click"] is False
    n = int(0.004 * SR)
    e_click = _hp_energy(x - clean, 2000.0, 0, n)        # the injected click
    e_left = _hp_energy(res.audio - clean, 2000.0, 0, n)  # what is left of it
    assert e_left <= e_click * 0.03  # >= 15 dB less click energy above 2 kHz
    assert rep["s07"]["pass"] is True


def test_click_in_the_middle_reported(clean):
    x = synth.add_head_click(clean, SR, at_s=1.3, dbfs=-12.0)
    found = detect_clicks(x, SR)
    assert len(found) == 1
    assert abs(found[0]["time_s"] - 1.3) < 0.003
    assert detect_clicks(clean, SR) == []
    assert diagnose(x, SR)["metrics"]["head_click"] is False
