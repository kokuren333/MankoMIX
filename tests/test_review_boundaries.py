"""Boundary and display checks added by the double review (2026-11-14).

They pin the current judgments exactly at their limits (no criterion is changed here):
S-08 at the planning limit (tolerance - margin) and at the verify tolerance, Spotify's
conditional ceiling at exactly -14 LUFS, the verify overall precedence, the GUI view of S-08,
and the proposal record of ``master plan --apply``.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from mankomix.core import api, config, mastering, verify
from mankomix.core.cleanup import guard
from mankomix.core.errors import InputError

from .test_mastering import make_project, synth_mix


# -- S-08 at planning time (s08_reduce: fails when delta > tolerance - margin) ----------------

def _s08_result(**deltas):
    return {"status": "pass", "deltas": {
        k: ({"delta_db": d, "tolerance_db": t, "pass": d <= t} if d is not None
            else {"delta_db": None, "tolerance_db": None, "pass": None, "note": "not measurable"})
        for k, (d, t) in deltas.items()}}


def test_s08_reduce_exactly_at_planning_limit_passes():
    r = mastering.s08_reduce(_s08_result(shimmer_index_db=(1.3, 1.5)), 0.2)
    assert r["status"] == "pass" and r["failing"] == []
    assert r["worst_excess_db"] == pytest.approx(0.0, abs=1e-9)


def test_s08_reduce_just_above_planning_limit_fails_even_below_verify_tolerance():
    r = mastering.s08_reduce(_s08_result(shimmer_index_db=(1.31, 1.5), noise_floor_dbfs=(0.5, 2.0)), 0.2)
    assert r["status"] == "fail" and r["failing"] == ["shimmer_index_db"]
    assert r["worst_excess_db"] == pytest.approx(0.01)
    assert r["verify_tolerance_status"] == "pass"     # verify would still pass at 1.31 <= 1.5


def test_s08_reduce_without_judged_metrics_is_not_run():
    r = mastering.s08_reduce(_s08_result(above_ceiling_level_db=(None, None)), 0.2)
    assert r["status"] == "not_run" and r["worst_excess_db"] is None and r["deltas"] == {}


# -- S-08 at verify time (noise_return_check: passes when delta <= tolerance) -------------------

@pytest.mark.parametrize("excess, ok", [(0.0, True), (1e-6, False)])
def test_noise_return_check_shimmer_at_tolerance(monkeypatch, excess, ok):
    tol = float(guard.v(guard.load_policy()["s08"]["shimmer_index_tol_db"]))   # 1.5
    before = {"shimmer_index_db": -40.0, "integrated_lufs": -20.0}
    monkeypatch.setattr(guard, "noise_shimmer_metrics",
                        lambda *a, **k: {"shimmer_index_db": -40.0 + tol + excess})
    r = guard.noise_return_check(before, np.zeros((4800, 2)), 48000, gain_db=0.0)
    assert r["deltas"]["shimmer_index_db"]["pass"] is ok and r["pass"] is ok


@pytest.mark.parametrize("excess, ok", [(0.0, True), (1e-6, False)])
def test_noise_return_check_noise_floor_is_gain_compensated_at_tolerance(monkeypatch, excess, ok):
    tol = float(guard.v(guard.load_policy()["s08"]["noise_floor_tol_db"]))     # 2.0
    before = {"noise_floor_dbfs": -60.0, "integrated_lufs": -20.0}
    monkeypatch.setattr(guard, "noise_shimmer_metrics",
                        lambda *a, **k: {"noise_floor_dbfs": -60.0 + 4.0 + tol + excess})
    r = guard.noise_return_check(before, np.zeros((4800, 2)), 48000, gain_db=4.0)
    c = r["deltas"]["noise_floor_dbfs"]
    assert c["pass"] is ok and c["gain_compensated"] is True


# -- conditional ceiling and verify precedence -------------------------------------------------

def test_spotify_conditional_ceiling_is_strict_at_minus_14():
    sp = config.get_profile("spotify")
    assert mastering.effective_ceiling(sp, -14.0) == -1.0      # "louder than -14": -14.0 is not
    assert mastering.effective_ceiling(sp, -13.99) == -2.0


def test_verify_overall_precedence():
    hard = {k: {"status": "pass"} for k in verify.HARD_CHECKS}
    assert verify._overall(hard) == "pass"
    assert verify._overall({**hard, "OF-5": {"status": "not_evaluated"}, "S-04": {"status": "not_applicable"}}) == "pass"
    assert verify._overall({**hard, "S-08": {"status": "not_run"}}) == "incomplete"
    assert verify._overall({**hard, "S-08": {"status": "not_run"}, "S-02": {"status": "fail"}}) == "fail"
    assert verify._overall({k: v for k, v in hard.items() if k != "S-08"}) == "pass"   # absent != not_run


# -- GUI view of S-08 (verification_view) ------------------------------------------------------

def _out(profile, s08_deltas, status):
    return {"profile": profile, "delivery": "hires_native", "overall": status, "measured": {},
            "checks": {"S-08": {"status": status, "rule": "S-08", "deltas": s08_deltas}}}


def test_verification_view_s08_shows_worst_output_and_metric():
    ok = {"shimmer_index_db": {"delta_db": 0.4, "tolerance_db": 1.5, "pass": True},
          "noise_floor_dbfs": {"delta_db": 0.2, "tolerance_db": 2.0, "pass": True}}
    bad = {"shimmer_index_db": {"delta_db": 1.7, "tolerance_db": 1.5, "pass": False},
           "noise_floor_hf_dbfs": {"delta_db": 1.0, "tolerance_db": 2.0, "pass": True},
           "above_ceiling_level_db": {"delta_db": None, "tolerance_db": None, "pass": None}}
    rep = {"variant": "var_x", "overall": "fail",
           "outputs": [_out("spotify", ok, "pass"), _out("apple_music", bad, "fail")]}
    view = api.verification_view(rep)
    nr = view["noise_return"]
    assert nr["status"] == "fail" and nr["metric"] == "shimmer_index_db"
    assert nr["delta_db"] == 1.7 and nr["tolerance_db"] == 1.5
    row = next(c for c in view["constraints"] if c["id"] == "S-08")
    assert row["status"] == "fail" and row["value"] == 1.7 and row["limit"] == 1.5


def test_verification_view_s08_single_pass_output():
    ok = {"shimmer_index_db": {"delta_db": 1.153, "tolerance_db": 1.5, "pass": True},
          "noise_floor_hf_dbfs": {"delta_db": 1.162, "tolerance_db": 2.0, "pass": True}}
    nr = api.verification_view({"variant": "v", "overall": "pass", "outputs": [_out("club", ok, "pass")]})["noise_return"]
    # the closest to its tolerance: shimmer 1.153 - 1.5 = -0.347 > HF 1.162 - 2.0 = -0.838
    assert nr["status"] == "pass" and nr["metric"] == "shimmer_index_db" and nr["delta_db"] == 1.153


# -- master plan --apply records the proposal as applied ---------------------------------------

def test_master_plan_apply_marks_saved_proposal_applied(tmp_path):
    root = tmp_path / "song.mmx"
    make_project(root, synth_mix(dur=4.0))
    res = api.master_plan(str(root), profile="apple_music", apply=True)
    assert res["applied"] is True
    saved = json.loads((Path(root) / res["proposal_path"]).read_text(encoding="utf-8"))
    assert saved["status"] == "applied" and saved["applied"]["actor"] == "human"
    assert saved["applied"]["journal_seq"] is not None
    with pytest.raises(InputError):
        api.plan_reject(str(root), res["proposal"]["proposal_id"], "too loud")
