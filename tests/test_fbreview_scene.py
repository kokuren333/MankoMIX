"""The placement declaration `scene` and its reference-only block in check (FBREVIEW FR-4).

- validate: form and range only (bad_value / param_range / bad_id / unknown_target with --project /
  missing_field); nothing about coverage, the moves or the result
- a direction without scene: dir_ id, validate and outcome byte-identical (the scene code never runs)
- with scene: the claims, move checks and summary do not change; the block is reference only
- three synthetic tracks with sends and levels in depth order: tau = +1; in reverse order: -1
"""

from __future__ import annotations

import copy
import json
import math
import shutil
from pathlib import Path

import numpy as np
import pytest

from mankomix.director import direction as D
from mankomix.director import stemobs as S
from tests import test_direction_update as T
from tests import test_fbreview_stemobs as FS
from tests import test_upgrade2_edit as ED


@pytest.fixture(autouse=True)
def _local_home(tmp_path, monkeypatch):
    monkeypatch.setenv("MANKOMIX_HOME", str(tmp_path / "home"))


def _src(track: str, **kw) -> dict:
    return {"track": track, **kw}


def _vblock(scene) -> dict:
    b = T._minimal_block()
    b["scene"] = scene
    return b


def _validate(tmp_path: Path, scene, project: Path | None = None, tag: str = "v") -> dict:
    return D.validate(D.parse_document(T._write_doc(tmp_path / tag, _vblock(scene))), project)


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------

GOOD = {"note": "front vocal, keys left back",
        "sources": [_src("trk_vocals", azimuth=0.0, depth=1, note="centre"), _src("trk_bass", depth=2),
                    _src("trk_keys", azimuth=-0.4)]}


def test_a_valid_scene_has_no_error_or_warning(tmp_path):
    res = _validate(tmp_path, GOOD)
    assert res["ok"] and res["warnings"] == [T.WARN_P03_B], res
    res = _validate(tmp_path, {"sources": [_src("trk_vocals", azimuth=1, depth=5),
                                           _src("trk_bass", azimuth=-1.0)]}, tag="ends")
    assert res["ok"], res


ERRS = [
    ("not_object", ["trk_vocals"], [("scene", "bad_value")]),
    ("unknown_key", {"sources": [_src("trk_vocals", depth=1)], "room": "big"}, [("scene", "bad_value")]),
    ("note", {"note": 3, "sources": [_src("trk_vocals", depth=1)]}, [("scene.note", "bad_value")]),
    ("no_sources", {"note": "x"}, [("scene.sources", "missing_field")]),
    ("sources_not_list", {"sources": {"trk_vocals": 1}}, [("scene.sources", "bad_value")]),
    ("empty", {"sources": []}, [("scene.sources", "param_range")]),
    ("too_many", {"sources": [_src(f"trk_s{i}", depth=1) for i in range(33)]}, [("scene.sources", "param_range")]),
    ("source_not_object", {"sources": ["trk_vocals"]}, [("scene.sources[0]", "bad_value")]),
    ("source_unknown_key", {"sources": [_src("trk_vocals", depth=1, distance=2)]}, [("scene.sources[0]", "bad_value")]),
    ("no_track", {"sources": [{"depth": 1}]}, [("scene.sources[0].track", "missing_field")]),
    ("bad_track", {"sources": [_src("bus_reverb", depth=1)]}, [("scene.sources[0].track", "bad_value")]),
    ("dup", {"sources": [_src("trk_vocals", depth=1), _src("trk_vocals", azimuth=0.2)]},
     [("scene.sources[1].track", "bad_id")]),
    ("az_type", {"sources": [_src("trk_vocals", azimuth="left")]}, [("scene.sources[0].azimuth", "bad_value")]),
    ("az_bool", {"sources": [_src("trk_vocals", azimuth=True)]}, [("scene.sources[0].azimuth", "bad_value")]),
    ("az_range", {"sources": [_src("trk_vocals", azimuth=1.2)]}, [("scene.sources[0].azimuth", "param_range")]),
    ("az_range_lo", {"sources": [_src("trk_vocals", azimuth=-1.01)]}, [("scene.sources[0].azimuth", "param_range")]),
    ("depth_float", {"sources": [_src("trk_vocals", depth=2.0)]}, [("scene.sources[0].depth", "bad_value")]),
    ("depth_bool", {"sources": [_src("trk_vocals", depth=True)]}, [("scene.sources[0].depth", "bad_value")]),
    ("depth_range0", {"sources": [_src("trk_vocals", depth=0)]}, [("scene.sources[0].depth", "param_range")]),
    ("depth_range6", {"sources": [_src("trk_vocals", depth=6)]}, [("scene.sources[0].depth", "param_range")]),
    ("neither", {"sources": [_src("trk_vocals", note="somewhere")]}, [("scene.sources[0]", "missing_field")]),
    ("src_note", {"sources": [_src("trk_vocals", depth=1, note=["x"])]}, [("scene.sources[0].note", "bad_value")]),
]


@pytest.mark.parametrize("tag,scene,want", ERRS, ids=[e[0] for e in ERRS])
def test_b_form_errors(tmp_path, tag, scene, want):
    res = _validate(tmp_path, scene, tag=tag)
    assert not res["ok"] and [(e["where"], e["code"]) for e in res["errors"]] == want, res["errors"]


def test_b_unknown_track_with_project_only(tmp_path):
    proj = T._project(tmp_path / "p", low_amp=0.2)
    sc = {"sources": [_src("trk_vocals", depth=1), _src("trk_nope", azimuth=0.5)]}
    res = _validate(tmp_path, sc, proj, tag="p")
    assert [(e["where"], e["code"]) for e in res["errors"]] == [("scene.sources[1].track", "unknown_target")]
    assert _validate(tmp_path, sc, None, tag="np")["ok"]


def test_b_coverage_and_the_moves_are_not_checked(tmp_path):
    # one source only, a track the moves never touch, and a pan move that contradicts the declaration
    proj = T._project(tmp_path / "p", low_amp=0.2)
    b = _vblock({"sources": [_src("trk_bass", azimuth=0.9, depth=5)]})
    b["moves"].append({"id": "m02", "aim": "a1", "target": "trk_bass", "op": "pan", "params": {"position": -0.9},
                       "basis": "x", "origin": "new"})
    with_scene = D.validate(D.parse_document(T._write_doc(tmp_path / "s", b)), proj)
    b.pop("scene")
    without = D.validate(D.parse_document(T._write_doc(tmp_path / "n", b)), proj)
    assert with_scene["ok"]
    assert {k: v for k, v in with_scene.items() if k != "id"} == {k: v for k, v in without.items() if k != "id"}


# ---------------------------------------------------------------------------
# without scene: nothing changes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("folder", sorted(ED.BASE_VALIDATE))
def test_c_existing_directions_validate_unchanged_without_running_scene_code(folder, monkeypatch):
    monkeypatch.setattr(D, "_check_scene", lambda *a, **k: pytest.fail("scene code ran"))
    doc = D.parse_document(ED.SONG_DIR / folder / "direction.md")
    did, h = ED.BASE_VALIDATE[folder]
    assert "scene" not in doc["block"] and doc["id"] == did
    assert ED._h(D.validate(doc)) == h


def test_c_outcome_without_scene_is_byte_identical(tmp_path, monkeypatch):
    import tests.test_upgrade2_duck as U
    monkeypatch.setattr(D, "scene_block", lambda *a, **k: pytest.fail("scene code ran"))
    monkeypatch.setattr(S, "StemSource", lambda *a, **k: pytest.fail("StemSource made without scene"))
    for tag, blk in (("plain", T._block()), ("min", T._minimal_block()), ("refs", T._with_refs(T._block()))):
        _, raw_plain, _, _ = U._check_both(tmp_path, blk, tag)
        assert U._masked(raw_plain.decode("utf-8")) == U.BASE["outcome"][tag], tag


# ---------------------------------------------------------------------------
# check: the reference-only block on three synthetic tracks
# ---------------------------------------------------------------------------

# depth 1 -> 3: sends rising, levels falling (in depth order)
ORDER = {"trk_a": {"sends": [{"bus": "bus_fx", "level_db": -30.0}], "gain_db": 0.0},
         "trk_b": {"sends": [{"bus": "bus_fx", "level_db": -18.0}], "gain_db": -6.0},
         "trk_c": {"sends": [{"bus": "bus_fx", "level_db": -8.0}], "gain_db": -12.0}}


@pytest.fixture(scope="module")
def _three(tmp_path_factory) -> Path:
    import os
    old = os.environ.get("MANKOMIX_HOME")
    base = tmp_path_factory.mktemp("scene_tpl")
    os.environ["MANKOMIX_HOME"] = str(base / "home")
    try:
        root = FS._make(base / "song", {"a": FS._noise(200, 800, 11), "b": FS._noise(800, 3000, 12),
                                        "c": FS._noise(3000, 8000, 13)},
                        tracks={"trk_a": {**ORDER["trk_a"], "role": "vocals", "is_lead": True,
                                          "pan": {"position": 0.0, "width": 1.0}},
                                "trk_b": {**ORDER["trk_b"], "role": "keyboard"},
                                "trk_c": {**ORDER["trk_c"], "role": "synth"}})
        FS._render(root)
        return root
    finally:
        if old is None:
            os.environ.pop("MANKOMIX_HOME", None)
        else:
            os.environ["MANKOMIX_HOME"] = old


def _sblock(scene: dict | None, claims: list[dict] | None = None) -> dict:
    obs = [{"id": "o1", "primitive": "crest", "target": "master"}]
    b = FS._block(obs, claims=claims or [{"id": "c1", "quantity": "obs:o1", "direction": "not_worse",
                                          "tolerance": 50.0, "primary": True}],
                  moves=[{"id": "m01", "aim": "a1", "target": "trk_c", "op": "gain", "params": {"delta_db": -1.0},
                          "basis": "x", "origin": "new",
                          "safeguard": [{"quantity": "obs:o1", "direction": "not_worse", "tolerance": 0.0}]}])
    if scene is not None:
        b["scene"] = scene
    return b


def _pair(_three, tmp_path, result_gain: dict | None = None) -> tuple[Path, Path]:
    floor, res = tmp_path / "floor", tmp_path / "res"
    shutil.copytree(_three, floor)
    shutil.copytree(_three, res)
    if result_gain:
        data = json.loads((res / "project.json").read_text(encoding="utf-8"))
        for t in data["tracks"]:
            if t["id"] in result_gain:
                t["gain_db"] = result_gain[t["id"]]
        (res / "project.json").write_text(json.dumps(data), encoding="utf-8")
        FS._render(res)
    return floor, res


SCENE = {"sources": [_src("trk_a", azimuth=0.0, depth=1), _src("trk_b", azimuth=-0.4, depth=2),
                     _src("trk_c", depth=3), _src("trk_zz", azimuth=0.5)]}


def test_d_scene_block_and_tau_plus_one(_three, tmp_path):
    floor, res = _pair(_three, tmp_path, {"trk_c": -13.0})
    doc = FS._doc(tmp_path / "d", _sblock(SCENE))
    assert D.validate(D.parse_document(doc))["ok"]    # trk_zz is not in the project: unknown_target with it
    pj_floor, pj_res = (floor / "project.json").read_bytes(), (res / "project.json").read_bytes()
    out = D.check(res, floor, doc)
    sc = out["scene"]
    assert sc["note"] == ("参考値。どの判定にも入らない（主張・期待・ガード・summary・ゲート）。奥行きの知覚は 1 つの量で"
                          "決まらない。expected_image は sin(azimuth·π/2) の目安（モノ素材の等電力則の値。ステレオで"
                          "取り込んだ素材は釣り合い則で、これより中央寄りに出る）")
    assert list(sc["sources"]) == ["trk_a", "trk_b", "trk_c", "trk_zz"]
    b = sc["sources"]["trk_b"]
    assert b["azimuth"] == -0.4 and b["expected_image"] == round(math.sin(-0.4 * math.pi / 2), 3) == -0.588
    assert b["depth"] == 2
    assert set(b["image_position"]) == set(b["wet_ratio_db"]) == set(b["level_lufs"]) == {"floor", "result"}
    assert b["wet_ratio_db"]["floor"] == pytest.approx(-18.0, abs=0.5)
    assert sc["sources"]["trk_a"]["image_position"]["result"] == pytest.approx(0.0, abs=0.01)
    c = sc["sources"]["trk_c"]
    assert "azimuth" not in c and "expected_image" not in c and c["depth"] == 3
    assert c["level_lufs"]["result"] - c["level_lufs"]["floor"] == pytest.approx(-1.0, abs=0.05)
    # a source that cannot be measured stays, with nulls
    zz = sc["sources"]["trk_zz"]
    assert zz["image_position"] == zz["wet_ratio_db"] == zz["level_lufs"] == {"floor": None, "result": None}
    assert sc["depth_consistency"] == {"n": 3, "tau_wet": 1.0, "tau_level": 1.0}
    # the written outcome carries the same block; project.json (mix.declared_depth_order, read by P-09) is untouched
    disk = json.loads((res / "directions" / f"{D.parse_document(doc)['id']}.outcome.json").read_text(encoding="utf-8"))
    assert disk["scene"] == sc
    for root, before in ((floor, pj_floor), (res, pj_res)):
        assert (root / "project.json").read_bytes() == before
        assert json.loads(before)["mix"]["declared_depth_order"] == []


def test_d_reverse_order_gives_tau_minus_one_and_few_sources_give_null(_three, tmp_path):
    floor, res = _pair(_three, tmp_path)
    rev = {"sources": [_src("trk_a", depth=3), _src("trk_b", depth=2), _src("trk_c", depth=1)]}
    out = D.check(res, floor, FS._doc(tmp_path / "r", _sblock(rev)))
    assert out["scene"]["depth_consistency"] == {"n": 3, "tau_wet": -1.0, "tau_level": -1.0}
    two = {"sources": [_src("trk_a", depth=1), _src("trk_b", depth=2), _src("trk_c", azimuth=0.3)]}
    out = D.check(res, floor, FS._doc(tmp_path / "t", _sblock(two)))
    assert out["scene"]["depth_consistency"] == {"n": 2, "tau_wet": None, "tau_level": None}


def test_e_scene_changes_no_verdict_or_summary(_three, tmp_path):
    floor, res = _pair(_three, tmp_path, {"trk_c": -13.0})
    claims = [{"id": "c1", "quantity": "obs:o1", "direction": "up", "min_delta": 0.1, "primary": True},
              {"id": "c2", "quantity": "P-03", "direction": "not_worse", "tolerance": 1.0}]
    a = D.check(res, floor, FS._doc(tmp_path / "a", _sblock(None, claims)))
    b = D.check(res, floor, FS._doc(tmp_path / "b", _sblock(SCENE, claims)))
    assert "scene" not in a and "scene" in b
    for k in ("claims", "move_checks", "summary", "observations", "loudness", "convergence", "status"):
        assert a[k] == b[k], k
    assert set(b) - set(a) == {"scene"}
