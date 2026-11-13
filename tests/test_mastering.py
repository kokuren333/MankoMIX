"""M2 full-mix mastering path: plan -> apply -> render -> verify -> report.

Audio is synthesized into tmp folders; nothing is written into the repository.
"""
from __future__ import annotations

import json
import re

import numpy as np
import pytest
import soundfile as sf
from scipy.signal import butter, sosfilt

from mankomix.core import config, mastering, render, report, verify
from mankomix.core.errors import ValidationError
from mankomix.core.hashing import sha256_file
from mankomix.core.measure import loudness as ld
from mankomix.core.project import Project

SR = 48000
PROFILES = {  # profile -> delivery
    "streaming_universal": "hires_native",
    "spotify": "hires_native",
    "apple_music": "hires_native",
    "club": "dj_wav",
    "cd": "cd_redbook",
}


def synth_mix(sr: int = SR, dur: float = 6.0, seed: int = 7, level_dbfs: float = -8.0) -> np.ndarray:
    """Stereo 2-mix: kick transients, bass, chords, hats, noise; quiet intro; DC-free."""
    rng = np.random.default_rng(seed)
    n = int(sr * dur)
    t = np.arange(n) / sr
    x = np.zeros((n, 2))
    beat = int(0.5 * sr)
    klen = int(0.25 * sr)
    kt = np.arange(klen) / sr
    env = np.exp(-kt * 14.0)
    kick = np.sin(2 * np.pi * (55.0 * kt + 40.0 * (1 - np.exp(-kt * 30.0)) / 30.0)) * env
    for s in range(0, n - klen, beat):
        x[s:s + klen] += kick[:, None] * 0.9
    x += (0.35 * np.sin(2 * np.pi * 55.0 * t))[:, None]
    chord = sum(np.sin(2 * np.pi * f * t + ph) for f, ph in ((220.0, 0.0), (277.2, 0.4), (329.6, 1.1)))
    x[:, 0] += 0.08 * chord
    x[:, 1] += 0.07 * np.roll(chord, 24)
    sos = butter(2, [3000.0, 9000.0], btype="bandpass", fs=sr, output="sos")
    hats = sosfilt(sos, rng.standard_normal((n, 2)), axis=0)
    gate = (np.mod(t, 0.25) < 0.04).astype(float)
    x += hats * gate[:, None] * 0.25
    x += rng.standard_normal((n, 2)) * 0.01
    x[: int(1.5 * sr)] *= 0.3
    x -= x.mean(axis=0, keepdims=True)
    return x / np.max(np.abs(x)) * 10 ** (level_dbfs / 20.0)


def make_project(root, x: np.ndarray, sr: int = SR) -> Project:
    """Create a project and register a 2-mix the way the ingest adapter does."""
    proj = Project.create(root, title="m2 test")
    path = root / "assets" / "mix.wav"
    sf.write(str(path), x.astype(np.float32), sr, subtype="FLOAT")
    proj.data["assets"].append({
        "id": "ast_fullmix", "path": "assets/mix.wav", "original_name": "mix.wav",
        "sha256": sha256_file(path), "role": "fullmix", "origin": "reference_fullmix",
        "channels": int(x.shape[1]), "sample_rate": sr, "length_samples": int(x.shape[0]),
    })
    proj.data["fullmix_asset"] = "ast_fullmix"
    proj.data["timebase"]["sample_rate"] = sr
    proj.data["timebase"]["length_samples"] = int(x.shape[0])
    proj.save(actor="human", op="import", reason="test import")
    return proj


@pytest.fixture(scope="module")
def mastered(tmp_path_factory):
    root = tmp_path_factory.mktemp("m2") / "song.mmx"
    proj = make_project(root, synth_mix())
    out = {"project": proj, "root": root, "plans": {}, "renders": {}, "verify": {}}
    for prof, dl in PROFILES.items():
        plan = mastering.plan_master(proj, profile_id=prof, delivery_id=dl)
        mastering.apply_master_plan(proj, plan, actor="planner")
        out["plans"][prof] = plan
    # render after every apply so the project hash (dither seed source) is final
    for prof in PROFILES:
        vid = f"var_{prof}"
        out["renders"][prof] = render.render_variant(proj, vid)
        out["verify"][prof] = verify.verify_variant(proj, vid)
    return out


# --------------------------------------------------------------------------
# planner


def test_plan_is_a_proposal_in_fixed_order(mastered):
    plan = mastered["plans"]["streaming_universal"]
    assert plan["stage"] == "master" and plan["route"]["route"] == "full_mix"
    assert plan["route"]["rule"] == "R-21"
    types = [p["type"] for p in plan["chain"]]
    assert types[-1] == "limiter" and types[-2] == "loudness_gain"
    assert "multiband" not in " ".join(types)
    for p in plan["chain"]:
        assert p["reason"] and p["id"]
        if p["type"] == "eq":
            assert abs(p["params"]["gain_db"]) <= 2.0
    stages = [r["stage"] for r in plan["rationale"]]
    assert stages == ["corrective_eq", "dynamics", "enhance", "stereo", "loudness", "true_peak_limiter"]
    for r in plan["rationale"]:
        assert {"measured", "rule", "action", "alternatives", "expected"} <= set(r)
    assert mastering.check_chain_order(plan["chain"])["status"] == "pass"


def test_apply_writes_variant(mastered):
    proj = Project.open(mastered["root"])
    v = mastering.find_variant(proj.data, "var_cd")
    assert v["master"]["route"] == "fullmix" and v["master"]["route_detail"] == "full_mix"
    assert [(o["profile"], o["delivery"]) for o in v["outputs"]] == [("cd", "cd_redbook")]
    assert v["master"]["chain"][-1]["type"] == "limiter"
    assert v["master"]["plan"]["rationale"]
    assert all(i.get("level") != "error" for i in proj.validate())


def test_conditional_ceiling_spotify():
    sp = config.get_profile("spotify")
    assert mastering.effective_ceiling(sp, -13.0) == -2.0
    assert mastering.effective_ceiling(sp, -14.5) == -1.0
    assert mastering.effective_ceiling(config.get_profile("club"), -7.0) == -0.5


# --------------------------------------------------------------------------
# render + verify


@pytest.mark.parametrize("prof", list(PROFILES))
def test_loudness_and_true_peak(mastered, prof):
    profile = config.get_profile(prof)
    rec = mastered["verify"][prof]["outputs"][0]
    path = mastered["root"] / rec["file"]
    y, sr = sf.read(str(path), always_2d=True)
    lufs = ld.integrated(y, sr)
    tp = ld.true_peak_dbtp(y, sr)
    lo, hi = profile["loudness"]["window_lufs_i"]
    assert lo - 1e-6 <= lufs <= hi + 1e-6
    ceiling = mastering.effective_ceiling(profile, lufs)
    assert tp <= ceiling + 1e-9  # S-01, measured at >= 4x oversampling
    checks = rec["checks"]
    assert checks["P-03"]["status"] == "pass"
    assert checks["S-01"]["status"] == "pass"
    assert checks["S-01"]["oversample"] >= 4
    assert checks["S-06"]["status"] == "pass"
    assert checks["S-09"]["status"] == "pass"
    assert checks["S-03"]["status"] == "pass"
    assert checks["S-04"]["status"] == "pass"
    assert checks["OF-5"]["status"] == "not_evaluated"
    assert checks["S-08"]["status"] == "not_evaluated"
    if not profile["codec_checks"]:
        assert checks["S-02"]["status"] == "not_applicable"
    assert rec["overall"] in ("pass", "incomplete")


def test_spotify_conditional_ceiling_respected(mastered):
    rec = mastered["verify"]["spotify"]["outputs"][0]
    lufs = rec["measured"]["lufs_i"]
    s01 = rec["checks"]["S-01"]
    assert s01["ceiling_dbtp"] == (-2.0 if lufs > -14.0 else -1.0)
    assert rec["measured"]["true_peak_dbtp"] <= s01["ceiling_dbtp"]


@pytest.mark.ffmpeg
@pytest.mark.parametrize("prof", ["streaming_universal", "spotify", "apple_music"])
def test_codec_round_trip(mastered, prof):
    rec = mastered["verify"][prof]["outputs"][0]
    s02 = rec["checks"]["S-02"]
    assert s02["status"] in ("pass", "not_run")
    ran = [c for c in s02["codecs"].values() if c["status"] != "not_run"]
    assert ran, "ffmpeg is present, at least one encoder must run"
    for c in ran:
        assert c["true_peak_dbtp"] <= s02["codec_after_ceiling_dbtp"] + 1e-9
    man = json.loads((mastered["root"] / rec["manifest"]).read_text(encoding="utf-8"))
    its = man["s02"]["iterations"]
    assert man["s02"]["status"] == "pass"
    # either the first render passed or the ceiling was lowered and re-rendered
    if len(its) > 1:
        assert its[-1]["limiter_ceiling_dbtp"] < its[0]["limiter_ceiling_dbtp"]
    assert man["backends"]["ffmpeg"]["used"] is True
    assert man["backends"]["ffmpeg"]["configuration"] is not None
    if s02["status"] == "not_run":
        assert rec["overall"] != "pass"  # not_run is never a pass


def test_dither_once_only_when_depth_reduced(mastered):
    cd = mastered["verify"]["cd"]["outputs"][0]["checks"]["S-05"]
    assert cd["status"] == "pass" and cd["facts"]["dither_count"] == 1
    assert cd["facts"]["target_bit_depth"] == 16
    arch = mastered["verify"]["cd"]["archive"]["checks"]["S-05"]
    assert arch["status"] == "pass" and arch["facts"]["dither_count"] == 0
    assert sf.info(str(mastered["root"] / mastered["verify"]["cd"]["outputs"][0]["file"])).subtype == "PCM_16"
    assert sf.info(str(mastered["root"] / mastered["verify"]["cd"]["outputs"][0]["file"])).samplerate == 44100
    hires = mastered["verify"]["spotify"]["outputs"][0]["checks"]["S-05"]
    assert hires["status"] == "pass" and hires["facts"]["dither_count"] == 1  # 32f -> 24 bit
    dj = mastered["verify"]["club"]["outputs"][0]["checks"]["S-05"]
    assert dj["status"] == "pass" and dj["facts"]["dither_count"] == 1
    assert sf.info(str(mastered["root"] / mastered["verify"]["spotify"]["outputs"][0]["file"])).subtype == "PCM_24"


def test_s05_rule_is_checked_not_the_declared_policy():
    from mankomix.core.verify import _check_s05
    hires = config.get_delivery("hires_native")
    assert hires["dither"] == "tpdf"
    undithered = {"bit_depth": 24, "steps": [], "dithered": False}
    assert _check_s05(undithered, dict(hires, dither="none"))["status"] == "fail"
    once = {"bit_depth": 24, "steps": [{"id": "export_dither", "type": "dither"}], "dithered": True}
    assert _check_s05(once, hires)["status"] == "pass"
    twice = {"bit_depth": 16, "steps": [{"id": "d1", "type": "dither"}, {"id": "d2", "type": "dither"}]}
    assert _check_s05(twice, config.get_delivery("cd_redbook"))["status"] == "fail"
    f32 = {"bit_depth": "32f", "steps": [{"id": "d", "type": "dither"}], "dithered": True}
    assert _check_s05(f32, config.get_delivery("archive_f32"))["status"] == "fail"


def test_out_of_order_chain_rejected(mastered):
    proj = mastered["project"]
    plan = dict(mastered["plans"]["cd"])
    chain = list(plan["chain"])
    bad = [chain[-1]] + chain[:-1]  # limiter first
    assert mastering.check_chain_order(bad)["status"] == "fail"
    with pytest.raises(ValidationError):
        mastering.apply_master_plan(proj, dict(plan, chain=bad), actor="planner")
    eq_after = chain + [mastering.eq_proc("late_eq", "peak", 1000.0, -1.0, 1.0, "test")]
    with pytest.raises(ValidationError):
        mastering.validate_master_chain(eq_after)
    from mankomix.dsp import engine
    with pytest.raises(ValueError):
        engine.render_chain(np.zeros((4800, 2)), SR, mastering.engine_chain(bad), stage="master")


def test_render_is_deterministic(mastered):
    proj = mastered["project"]
    first = render.render_variant(proj, "var_cd")
    f = mastered["root"] / first["outputs"][0]["file"]
    a = f.read_bytes()
    second = render.render_variant(proj, "var_cd")
    assert (mastered["root"] / second["outputs"][0]["file"]).read_bytes() == a
    man = json.loads((mastered["root"] / second["outputs"][0]["manifest"]).read_text(encoding="utf-8"))
    v = mastering.find_variant(proj.data, "var_cd")
    seed, seed_hash = render.dither_seed(render.seed_inputs(
        v, [proj.data["assets"][0]["sha256"]], "cd", "cd_redbook"))
    assert man["dither"]["seed"] == seed and man["dither"]["seed_inputs_sha256"] == seed_hash
    assert man["project_hash"] == proj.content_hash()
    assert man["engine_version"]
    assert man["models"] == []
    assert man["assets"][0]["sha256"] == proj.data["assets"][0]["sha256"]
    assert "profile" in man["definitions"] and "delivery" in man["definitions"]
    # editing another variant changes the project hash but not this render's bytes
    hash_before = proj.content_hash()
    club = mastering.find_variant(proj.data, "var_club")
    club["master"]["chain"][-1]["params"]["ceiling_dbtp"] = -0.7
    club["label"] = "edited"
    proj.save(actor="human", op="edit", reason="edit another variant")
    assert proj.content_hash() != hash_before
    third = render.render_variant(proj, "var_cd")
    assert (mastered["root"] / third["outputs"][0]["file"]).read_bytes() == a


_ABS = re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/]|(?:/Users/|/home/|\\Users\\)|@[A-Za-z0-9-]+\.[A-Za-z]")


def test_manifests_and_reports_have_no_absolute_paths(mastered):
    root = mastered["root"]
    paths = report.write_report(mastered["project"], "var_spotify")
    files = list((root / "renders").rglob("*.json")) + list((root / "reports").glob("*"))
    assert files
    root_str = str(root)
    for p in files:
        text = p.read_text(encoding="utf-8")
        assert root_str not in text and root.as_posix() not in text, p.name
        assert not _ABS.search(text), (p.name, _ABS.search(text))
    for rel in paths.values():
        assert not rel.startswith("/") and ":" not in rel


def test_report_ja_en(mastered):
    proj = mastered["project"]
    paths = report.write_report(proj, "var_spotify")
    md_ja = (mastered["root"] / paths["md_ja"]).read_text(encoding="utf-8")
    md_en = (mastered["root"] / paths["md_en"]).read_text(encoding="utf-8")
    assert "人の耳で確認すべき点" in md_ja and "Listening checks" in md_en
    assert "音量を固定" in md_ja and "fixed volume" in md_en
    assert "ジャンル未指定" in md_ja and "generic prior" in md_en
    for n in range(1, 11):
        assert f"## {n}. " in md_ja and f"## {n}. " in md_en
    rep = json.loads((mastered["root"] / paths["json"]).read_text(encoding="utf-8"))
    assert rep["language"] == "both"
    assert rep["measurements"]["level_matched"] is True
    lc = rep["measurements"]["loudness_change"]
    assert abs(lc["sone_ratio"] - 2 ** (lc["delta_db"] / 10)) < 1e-2
    checks = rep["listening_checks"]
    assert len(checks) >= 3 and checks[0]["time_s"] == 0.0
    assert any(c["time_s"] and c["time_s"] > 0 for c in checks[1:])
    man = json.loads((mastered["root"] / "renders/var_spotify/spotify__hires_native.manifest.json")
                     .read_text(encoding="utf-8"))
    assert rep["reproducibility"]["project_hash"] == man["project_hash"]
    # M3: per-metric breakdown computed on the rendered master (no planner evaluation stored)
    ob = rep["objective_breakdown"]
    assert ob["status"] == "evaluated" and ob["source"] == "rendered_master"
    measured = [t for t in ob["terms"] if t["status"] == "measured"]
    assert measured and all({"value", "target", "penalty", "contribution", "value_before"} <= set(t) for t in measured)
    assert ob["score"] == pytest.approx(sum(t["contribution"] for t in measured))
    assert rep["translation_gate"]["status"] in ("fail", "incomplete") and rep["translation_gate"]["meaning"]
    assert "P-01" in md_en.split("## 5. ")[1].split("## 6. ")[0]
    assert "OF-5" in md_ja.split("## 6. ")[1]
    en = report.build_report(proj, "var_spotify", lang="en")
    assert isinstance(en["summary"]["route"]["reason"], str)


def test_bass_objective_adds_normalization_note(mastered):
    proj = mastered["project"]
    rep = report.build_report(proj, "var_spotify", lang="both")
    assert not any(n["code"] == "normalization_tradeoff" for n in rep["notes"])
    notes = report._notes(proj, {"blend": [{"id": "bass_heavy", "weight": 1.0}], "intensity": 0.5})
    assert any(n["code"] == "normalization_tradeoff" for n in notes)


# --------------------------------------------------------------------------
# achievability (R-14)


def over_limited_mix(sr: int = SR, dur: float = 3.5) -> np.ndarray:
    """Dense, very peaky material: reaching club loudness needs sustained heavy limiting."""
    rng = np.random.default_rng(3)
    n = int(sr * dur)
    x = rng.standard_normal((n, 2)) * 0.08
    period = int(0.03 * sr)
    for s in range(0, n - 96, period):
        x[s:s + 96] += np.hanning(96)[:, None] * 0.9
    x -= x.mean(axis=0, keepdims=True)
    return x / np.max(np.abs(x)) * 0.5


def test_over_limited_input_sends_back(tmp_path):
    proj = make_project(tmp_path / "hot.mmx", over_limited_mix())
    plan = mastering.plan_master(proj, profile_id="club", delivery_id="dj_wav")
    assert plan["send_back"] is not None
    assert plan["send_back"]["rule"] == "R-14"
    window = config.get_profile("club")["loudness"]["window_lufs_i"]
    assert plan["expected"]["target_lufs_i"] < -7.0  # target lowered within the window first
    assert plan["expected"]["target_lufs_i"] >= window[0]
    assert any(w["code"] == "limiter_dependency" for w in plan["warnings"])
