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
    assert plan["proposal"]["chain"][-1]["type"] == "limiter"
    _no_abs(plan, proj_root)

    applied = api.master_apply(str(proj_root), plan["proposal"]["proposal_id"])
    assert applied["applied"] is True and applied["variant"] == "var_cd"

    out = api.render(str(proj_root), "var_cd", outputs=["cd:cd_redbook"])
    assert out["outputs"][0]["file"] == "renders/var_cd/cd__cd_redbook.wav"
    _no_abs(out, proj_root)
    exp = api.export(str(proj_root), "var_cd")
    assert [o["delivery"] for o in exp["outputs"]] == ["cd_redbook"]

    v = api.verify(str(proj_root), "var_cd")
    assert v["passed"] is True and v["exit_code"] == 0
    _no_abs(v, proj_root)

    rep = api.report(str(proj_root), "var_cd", lang="ja")
    assert set(rep["paths"]) == {"json", "md_ja", "md_en"}
    assert "人の耳で確認すべき点" in rep["markdown"]
    assert isinstance(rep["report"]["summary"]["route"]["reason"], str)
    _no_abs(rep, proj_root)


def test_api_verify_failure_flag_and_strict(proj_root):
    if not (proj_root / "renders" / "var_cd" / "cd__cd_redbook.wav").is_file():
        pytest.skip("needs the rendered variant from test_api_master_flow")
    path = proj_root / "renders" / "var_cd" / "cd__cd_redbook.wav"
    y, sr = sf.read(str(path), always_2d=True)
    sf.write(str(path), np.clip(y * 3.0, -1, 1), sr, subtype="PCM_16")  # too loud, peaks over the ceiling
    v = api.verify(str(proj_root), "var_cd")
    assert v["passed"] is False and v["exit_code"] == 1
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
