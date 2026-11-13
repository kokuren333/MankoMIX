"""S-08 noise-return guard (SPEC 4.3, 6.7, R-14, R-20).

1. The measurement is fair: the master is measured on the baseline's frames
   (time-aligned quiet passages, onset gate, HF ceiling) on the baseline's
   sample rate, gain compensated by the integrated loudness difference. Pure
   gain and mild limiting pass; an HF shelf boost fails; a dynamics change
   elsewhere cannot hide noise returning in the baseline's quiet passage.
2. The mastering plan is S-08-aware: HF boost first, then the loudness target
   within the window (non-normalized media) or the limiter drive (normalized
   media); otherwise a send-back with the measured deltas. Never a relaxed
   tolerance.

Audio is synthesized into tmp folders; nothing is written into the repository.
"""
from __future__ import annotations

import numpy as np
import pytest
from scipy.signal import butter, resample_poly, sosfiltfilt

from mankomix.core import mastering, render, verify
from mankomix.core.cleanup import noise_baseline, noise_return_check, reference_selection

from .test_mastering import SR, make_project, synth_mix


@pytest.fixture(scope="module")
def mix():
    return synth_mix(dur=4.0)


@pytest.fixture(scope="module")
def ref(mix):
    return reference_selection(mix, SR)


def _check(mix, ref, y, sr=SR):
    return noise_return_check(noise_baseline(mix, SR), y, sr, reference=ref)


def _measured(r):
    return {k: c["delta_db"] for k, c in r["deltas"].items() if c["delta_db"] is not None}


# --------------------------------------------------------------------------
# measurement


def test_pure_static_gain_passes(mix, ref):
    r = _check(mix, ref, mix * 10 ** (6.0 / 20.0))
    assert r["pass"] and r["frame_selection"] == "baseline_frames"
    d = _measured(r)
    assert {"shimmer_index_db", "noise_floor_dbfs"} <= set(d)
    assert all(abs(v) < 0.05 for v in d.values()), d


def test_mild_limiting_that_keeps_the_hf_texture_passes(mix, ref):
    res = mastering._render(mix, SR, mastering.drive_tail(8.0, -1.0))
    assert mastering.limiter_stats(res)["gr_max_db"] > 0.5  # the limiter does work
    r = _check(mix, ref, res.audio)
    assert r["pass"], r["deltas"]
    assert all(abs(v) < 0.5 for v in _measured(r).values())


def test_hf_shelf_boost_fails(mix, ref):
    y = mastering._render(mix, SR, [mastering.eq_proc("hf", "high_shelf", 8000.0, 4.0, 1.0, "test")]).audio
    r = _check(mix, ref, y)
    assert r["pass"] is False
    assert r["deltas"]["shimmer_index_db"]["pass"] is False
    assert "reduce_hf_boost" in {s["action"] for s in r["suggestions"]}


def test_resampled_master_is_measured_on_the_baseline_timeline(mix, ref):
    """A 44.1 kHz delivery is conformed to the 48 kHz baseline before measuring; measured
    independently at its own rate the shimmer index reads higher for the same audio."""
    y = mastering._render(mix, SR, mastering.drive_tail(8.0, -1.0)).audio
    y44 = resample_poly(y, 147, 160, axis=0)
    aligned = _check(mix, ref, y44, 44100)
    assert aligned["conformed"]["resampled_from_hz"] == 44100 and aligned["conformed"]["resampled_to_hz"] == SR
    assert aligned["pass"] and abs(aligned["deltas"]["shimmer_index_db"]["delta_db"]) < 0.5
    independent = noise_return_check(noise_baseline(mix, SR), y44, 44100)
    assert independent["frame_selection"] == "independent"
    assert independent["deltas"]["shimmer_index_db"]["delta_db"] > aligned["deltas"]["shimmer_index_db"]["delta_db"]


def test_aligned_frames_catch_noise_hidden_by_a_fade():
    """Noise rises by ~10 dB in the baseline's pause while a fade-out elsewhere becomes the
    quietest passage of the master: frames chosen on the master would compare the fade (and
    pass); frames chosen on the baseline compare the pause (and fail)."""
    rng = np.random.default_rng(5)
    n = 4 * SR
    t = np.arange(n) / SR
    music = (0.1 * np.sin(2 * np.pi * 220.0 * t) + 0.05 * np.sin(2 * np.pi * 330.0 * t))[:, None] \
        + 0.01 * rng.standard_normal((n, 2))
    pause = slice(int(1.0 * SR), int(2.0 * SR))
    x = music.copy()
    x[pause] = 1e-3 * rng.standard_normal((pause.stop - pause.start, 2))
    y = x.copy()
    y[pause] *= 10 ** (10.0 / 20.0)  # noise returned in the pause
    tail = int(0.6 * SR)
    y[-tail:] *= 1e-4  # a fade-out: the master's own quietest passage
    base = noise_baseline(x, SR)
    independent = noise_return_check(base, y, SR)
    aligned = noise_return_check(base, y, SR, reference=reference_selection(x, SR))
    assert independent["deltas"]["noise_floor_dbfs"]["pass"] is True
    assert aligned["deltas"]["noise_floor_dbfs"]["pass"] is False
    assert aligned["deltas"]["noise_floor_dbfs"]["delta_db"] > 5.0  # 400 ms smoothing blurs the pause edges
    assert aligned["pass"] is False


# --------------------------------------------------------------------------
# S-08-aware mastering plans


def _guard(plan):
    g = plan["rationale"][-1]
    assert g["stage"] == "noise_return_guard" and g["rule"] == "S-08"
    for st in g["steps"]:
        assert {"measured", "rule", "action", "alternatives", "result"} <= set(st)
    return g


def _dark_mix():
    """Little energy above 4 kHz: the corrective EQ wants an air (high-shelf) boost."""
    x = synth_mix(dur=4.0)
    x = sosfiltfilt(butter(8, 4000.0, btype="lowpass", fs=SR, output="sos"), x, axis=0)
    x = x + np.random.default_rng(11).standard_normal(x.shape) * 1e-4
    return x / np.max(np.abs(x)) * 10 ** (-8.0 / 20.0)


def _dense_mix(k: float = 1.3):
    """Lower crest factor: the cd target is reachable under R-14 but not under S-08."""
    x = np.tanh(k * synth_mix(dur=4.0) / np.max(np.abs(synth_mix(dur=4.0))))
    x -= x.mean(axis=0, keepdims=True)
    return x / np.max(np.abs(x)) * 10 ** (-8.0 / 20.0)


def test_hf_boost_is_reduced_first_and_the_target_kept(tmp_path):
    proj = make_project(tmp_path / "dark.mmx", _dark_mix())
    plan = mastering.plan_master(proj, profile_id="apple_music", delivery_id="hires_native")
    g = _guard(plan)
    assert g["measured"]["s08"]["status"] == "fail"
    assert "noise_floor_hf_dbfs" in g["measured"]["s08"]["failing"]
    first = g["steps"][0]
    assert first["kind"] == "hf_boost" and "reduced to 50%" in first["action"]["en"]
    assert first["result"]["s08"]["status"] == "pass"
    assert plan["send_back"] is None and plan["expected"]["s08"]["status"] == "pass"
    assert plan["expected"]["target_lufs_i"] == -16.0  # normalized: target kept
    shelf = [p for p in plan["chain"] if p["type"] == "eq" and p["params"]["shape"] == "high_shelf"]
    assert shelf and shelf[0]["params"]["gain_db"] == 1.0 and "S-08" in shelf[0]["reason"]
    eq = next(r for r in plan["rationale"] if r["stage"] == "corrective_eq")
    assert any(m.get("s08_reduced_from_db") == 2.0 and m["gain_db"] == 1.0 for m in eq["moves"])
    mastering.apply_master_plan(proj, plan, actor="planner")
    render.render_variant(proj, "var_apple_music")
    out = verify.verify_variant(proj, "var_apple_music")["outputs"][0]
    assert out["checks"]["S-08"]["status"] == "pass", out["checks"]["S-08"]


def test_non_normalized_lowers_the_target_within_the_window(tmp_path):
    proj = make_project(tmp_path / "dense.mmx", _dense_mix())
    plan = mastering.plan_master(proj, profile_id="cd", delivery_id="cd_redbook")
    g = _guard(plan)
    assert g["measured"]["s08"]["status"] == "fail" and g["measured"]["s08"]["worst_excess_db"] > 0.5
    kinds = [st["kind"] for st in g["steps"]]
    assert kinds[0] == "hf_boost" and g["steps"][0]["result"] is None  # no HF boost: recorded, not applicable
    assert kinds[1:] and set(kinds[1:]) == {"target"}
    last = g["steps"][-1]["result"]
    assert last["s08"]["status"] == "pass"
    assert plan["send_back"] is None
    t = plan["expected"]["target_lufs_i"]
    assert -12.0 <= t < -10.0 and t == last["target_lufs_i"]
    assert any(w["code"] == "target_lowered_s08" and w["rule"] == "S-08" for w in plan["warnings"])
    assert all(p["type"] != "clipper" for p in plan["chain"])  # non-normalized: no clipper share
    assert plan["chain"][-1]["params"]["release_ms"] == mastering.DEFAULT_RELEASE_MS
    mastering.apply_master_plan(proj, plan, actor="planner")
    render.render_variant(proj, "var_cd")
    out = verify.verify_variant(proj, "var_cd")["outputs"][0]
    assert out["checks"]["S-08"]["status"] == "pass", out["checks"]["S-08"]
    assert out["checks"]["P-03"]["status"] == "pass"


def test_club_sends_back_for_r14_and_s08(tmp_path):
    """Heavy limiting at the bottom of the club window: R-14 sends back; S-08 is attached with
    its measured deltas and suggestions (never a relaxed tolerance)."""
    proj = make_project(tmp_path / "club.mmx", synth_mix(dur=4.0))
    plan = mastering.plan_master(proj, profile_id="club", delivery_id="dj_wav")
    sb = plan["send_back"]
    assert sb["rule"] == "R-14" and sb["rules"] == ["R-14", "S-08"]
    s08 = sb["also"][0]
    assert s08["rule"] == "S-08" and s08["measured"]["s08"]["status"] == "fail"
    assert s08["measured"]["s08"]["margin_db"] == pytest.approx(0.2)
    assert {"reduce_limiter_drive", "clean_first"} <= {x["action"] for x in s08["suggestions"]}
    from mankomix.core.cleanup._util import load_policy, v
    tol = float(v(load_policy()["s08"]["shimmer_index_tol_db"]))
    assert s08["measured"]["s08"]["deltas"]["shimmer_index_db"]["tolerance_db"] == tol  # not relaxed


# --------------------------------------------------------------------------
# Mix Report section 7 with an applied cleanup


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("MANKOMIX_HOME", str(tmp_path / "home"))


def test_report_cleanup_section_and_listening_checks(tmp_path, home):
    from mankomix.core import cleanstage as cs
    from mankomix.core import report
    from mankomix.core.adapters.file import FileAdapter
    from mankomix.core.project import Project
    from tests.fixtures import synth
    from tests.test_cleanup_policy import SR as CSR, music

    x = 0.5 * synth.add_head_click(synth.add_shimmer(music(4.0, seed=7), CSR, depth_db=-22.0, seed=5), CSR)
    src = tmp_path / "src"
    synth.write_wav(src / "fullmix.wav", x, CSR)
    proj = Project.create(tmp_path / "fm.mmx", title="fullmix cleanup report")
    FileAdapter().fetch(src / "fullmix.wav", proj, actor="human")
    fid = proj.data["fullmix_asset"]
    cs.apply_clean(proj, cs.plan_clean(proj), actor="human")
    plan = mastering.plan_master(proj, profile_id="streaming_universal", delivery_id="hires_native")
    assert _guard(plan)["measured"]["baseline"]["cleaned"] is True
    mastering.apply_master_plan(proj, plan, actor="planner")
    render.render_variant(proj, "var_streaming_universal")
    verify.verify_variant(proj, "var_streaming_universal")
    paths = report.write_report(proj, "var_streaming_universal")
    rep = report.build_report(proj, "var_streaming_universal", lang="both")

    c = rep["cleanup"]
    assert c["status"] == "applied" and c["neural_completion_used"] is False
    a = next(a for a in c["assets"] if a["asset"] == fid)
    assert a["skipped"] is False
    assert set(a["steps"].values()) <= {"run", "light", "skip"} and a["steps"]["click_repair"] == "run"
    assert set(a["steps_by_action"]) == {"run", "light", "skip"}
    shimmer = a["removed_energy"]["shimmer"]
    assert shimmer["removed_rel_db"] is not None
    assert shimmer["sone_ratio"] == pytest.approx(2 ** (shimmer["removed_rel_db"] / 10), abs=1e-3)
    assert a["side_effects"]["rule"] == "P-21" and "lowmid_250_500_change" in a["side_effects"]
    assert a["s07"]["pass"] is True
    assert a["delta_file"] and a["delta_file"].startswith("renders/delta/")
    assert c["noise_baseline"]["file"] == cs.BASELINE_FILE
    s08 = c["s08"][0]
    assert s08["status"] in ("pass", "fail") and s08["baseline"]["cleaned"] is True
    assert s08["frame_selection"] == "baseline_frames"
    assert c["s08_plan"]["status"] in ("pass", "fail")

    checks = rep["listening_checks"]
    delta = [x for x in checks if x.get("file") == a["delta_file"]]
    assert delta and "息や子音" in delta[0]["point"]["ja"] and "breaths or consonants" in delta[0]["point"]["en"]

    md_ja = (proj.root / paths["md_ja"]).read_text(encoding="utf-8")
    md_en = (proj.root / paths["md_en"]).read_text(encoding="utf-8")
    sec_ja = md_ja.split("## 7. ")[1].split("## 8. ")[0]
    sec_en = md_en.split("## 7. ")[1].split("## 8. ")[0]
    assert "適用済み" in sec_ja and "クリック修復 = run" in sec_ja and "sone" in sec_ja and "S-07" in sec_ja
    assert a["delta_file"] in sec_ja and "ノイズ戻り監視の基準" in sec_ja
    assert "applied" in sec_en and "click repair = run" in sec_en and "Side effects (P-21)" in sec_en
    assert "除去分の音声に息や子音が含まれていないか" in md_ja.split("## 9. ")[1]
    root = str(proj.root)
    for text in (md_ja, md_en):
        assert root not in text and proj.root.as_posix() not in text
