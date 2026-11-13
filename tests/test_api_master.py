"""Core API facade for the M2 mastering path (route, master plan/apply, render/export, verify, report)."""
from __future__ import annotations

import json

import numpy as np
import pytest
import soundfile as sf

from mankomix.core import api
from mankomix.core.errors import InputError, VerifyFailed

from .test_mastering import make_project, synth_mix


@pytest.fixture(scope="module")
def proj_root(tmp_path_factory):
    root = tmp_path_factory.mktemp("api_m2") / "song.mmx"
    make_project(root, synth_mix(dur=4.0))
    return root


def _no_abs(result, root):
    text = json.dumps(result, ensure_ascii=False)
    assert str(root) not in text and root.as_posix() not in text


def test_api_master_flow(proj_root):
    r = api.route(str(proj_root))
    assert r["route"] == "full_mix" and r["rule"] == "R-21"

    plan = api.master_plan(str(proj_root), profile="cd")
    assert plan["applied"] is False and plan["proposal_path"].startswith("cache/proposals/")
    prop = plan["proposal"]
    assert prop["chain"][-1]["type"] == "limiter"
    _no_abs(plan, proj_root)

    # S-08 at planning time. On this fixture the cd master needs ~13 dB into the limiter; the
    # limiter's gain recovery modulates the noise (shimmer index and quiet-passage noise floor rise).
    # The chain has no HF boost and R-14 already took the target to the bottom of the window
    # (-12 + 0.3 margin), so nothing inside the window passes: the plan keeps the least-failing
    # candidate and sends the master back with the measured deltas (tolerance not relaxed).
    loud = next(x for x in prop["rationale"] if x["stage"] == "loudness")
    assert [t["target"] for t in loud["measured"]["tried"]][:3] == [-10.0, -11.0, -11.7]
    guard = next(x for x in prop["rationale"] if x["stage"] == "noise_return_guard")
    assert guard["rule"] == "S-08"
    assert guard["measured"]["s08"]["status"] == "fail"
    assert "shimmer_index_db" in guard["measured"]["s08"]["failing"]
    assert guard["measured"]["baseline"]["cleaned"] is False
    assert guard["steps"] and guard["steps"][0]["kind"] == "hf_boost"  # recorded: no HF boost to reduce
    for st in guard["steps"]:
        assert {"measured", "rule", "action", "alternatives", "result"} <= set(st)
    assert any("relax the tolerance" in a["en"] for a in guard["alternatives"])  # considered, rejected
    sb = prop["send_back"]
    assert sb["rule"] == "S-08" and sb["rules"] == ["S-08"]
    assert "S-08" in sb["reason"]["en"] and "shimmer index +" in sb["reason"]["en"]
    assert sb["measured"]["s08"]["worst_excess_db"] > 0
    assert sb["measured"]["target_lufs_i"] == -11.7
    assert {"reduce_limiter_drive", "clean_first", "limiter_style"} <= {x["action"] for x in sb["suggestions"]}
    assert prop["expected"]["s08"]["status"] == "fail"

    applied = api.master_apply(str(proj_root), prop["proposal_id"])
    assert applied["applied"] is True and applied["variant"] == "var_cd"

    out = api.render(str(proj_root), "var_cd", outputs=["cd:cd_redbook"])
    assert out["outputs"][0]["file"] == "renders/var_cd/cd__cd_redbook.wav"
    _no_abs(out, proj_root)
    exp = api.export(str(proj_root), "var_cd")
    assert [o["delivery"] for o in exp["outputs"]] == ["cd_redbook"]

    # verify stays a hard check: the master that still fails S-08 fails verify (exit 1), with suggestions
    v = api.verify(str(proj_root), "var_cd")
    assert v["passed"] is False and v["exit_code"] == 1
    o = v["outputs"][0]
    assert o["overall"] == "fail"
    for k in ("P-03", "S-01", "S-05", "S-06", "S-09"):
        assert o["checks"][k]["status"] == "pass", k
    s08 = o["checks"]["S-08"]
    assert s08["status"] == "fail" and s08["frame_selection"] == "baseline_frames"
    assert s08["conformed"]["resampled_from_hz"] == 44100  # measured on the 48 kHz baseline timeline
    assert s08["deltas"]["shimmer_index_db"]["pass"] is False
    acts = {x["action"] for x in s08["suggestions"]}
    assert {"reduce_limiter_drive", "send_back_to_mix"} <= acts and "reduce_hf_boost" not in acts
    assert s08["hf_boost_in_chain"] is False and s08["plan_send_back"]["rule"] == "S-08"
    _no_abs(v, proj_root)

    rep = api.report(str(proj_root), "var_cd", lang="ja")
    md = rep["markdown"]
    assert set(rep["paths"]) == {"json", "md_ja", "md_en"}
    assert "人の耳で確認すべき点" in md
    assert isinstance(rep["report"]["summary"]["route"]["reason"], str)
    assert rep["report"]["summary"]["result"] == "fail"
    assert rep["report"]["summary"]["send_back"]["rule"] == "S-08"
    cl = rep["report"]["cleanup"]
    assert cl["status"] == "not_applied" and cl["assets"] == []
    assert cl["s08"][0]["status"] == "fail" and cl["s08_plan"]["status"] == "fail"
    sec7 = md.split("## 7. ")[1].split("## 8. ")[0]
    assert "S-08" in sec7 and "シマー指数" in sec7 and "是正案" in sec7
    sec4 = md.split("## 4. ")[1].split("## 5. ")[0]
    assert "手順 1 [S-08]" in sec4
    assert any(c.get("rule") == "S-08" for c in rep["report"]["listening_checks"])
    _no_abs(rep, proj_root)
    en = (proj_root / rep["paths"]["md_en"]).read_text(encoding="utf-8")
    assert "Noise-return baseline" in en and "Send back (S-08)" in en


def test_api_verify_failure_flag_and_strict(proj_root):
    if not (proj_root / "renders" / "var_cd" / "cd__cd_redbook.wav").is_file():
        pytest.skip("needs the rendered variant from test_api_master_flow")
    path = proj_root / "renders" / "var_cd" / "cd__cd_redbook.wav"
    y, sr = sf.read(str(path), always_2d=True)
    sf.write(str(path), np.clip(y * 3.0, -1, 1), sr, subtype="PCM_16")  # too loud, peaks over the ceiling
    v = api.verify(str(proj_root), "var_cd")
    assert v["passed"] is False and v["exit_code"] == 1
    assert v["outputs"][0]["checks"]["S-01"]["status"] == "fail"
    with pytest.raises(VerifyFailed) as ei:
        api.verify(str(proj_root), "var_cd", strict=True)
    assert ei.value.exit_code == 1


def test_api_apply_plan_with_apply_flag_and_errors(proj_root):
    res = api.master_plan(str(proj_root), profile="apple_music", apply=True)
    assert res["applied"] is True
    with pytest.raises(InputError):
        api.render(str(proj_root), None)  # two variants now: must name one
    with pytest.raises(InputError):
        api.master_apply(str(proj_root), "mpl_doesnotexist")
    with pytest.raises(InputError):
        api.render(str(proj_root), "var_apple_music", outputs=["apple_music"])
