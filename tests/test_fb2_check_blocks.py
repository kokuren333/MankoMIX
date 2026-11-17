"""X-07/X-08 contracts on synthetic signals; no production code changes."""
import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from mankomix.cli.main import main
from mankomix.director import calibrate as C, contour as CT, direction as D
from mankomix.director import editlist as EL, query as Q, relate as R
from tests import test_direction_update as T, test_upgrade2_duck as TD
from tests.test_upgrade2_refs import _cal_block, _canon

SR = 24000
EDIT_NOTE = "参考値。どの判定にも入らない"
CONTOUR_NOTE = "落差・傾き・空白が残ったかを見る参考値。大きいほど良いわけではない"


@pytest.fixture(autouse=True)
def local_home(tmp_path, monkeypatch):
    monkeypatch.setenv("MANKOMIX_HOME", str(tmp_path / "home"))


def _outcome(result, doc):
    return result / "directions" / f"{D.parse_document(doc)['id']}.outcome.json"


def _bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").replace("\n", os.linesep).encode("utf-8")


@pytest.mark.parametrize("tag", ["plain", "min", "refs"])
def test_flagless_golden_and_only_optional_blocks_added(tmp_path, tag):
    blocks = {"plain": T._block(), "min": T._minimal_block(), "refs": T._with_refs(T._block())}
    floor = T._project(tmp_path / "floor", low_amp=.2)
    result = T._project(tmp_path / "result", low_amp=.3, width=.7)
    doc = T._write_doc(tmp_path / "doc", blocks[tag])
    plain = D.check(result, floor, doc)
    raw = _outcome(result, doc).read_bytes()
    assert TD._masked(raw.decode("utf-8")) == TD.BASE["outcome"][tag]
    assert "edit_list" not in plain and "contour" not in plain
    for flags in ({"edit_list": True}, {"contour": True}, {"edit_list": True, "contour": True}):
        rich = D.check(result, floor, doc, **flags)
        saved = json.loads(_outcome(result, doc).read_bytes())
        for key in flags:
            rich.pop(key)
            saved.pop(key)
        assert rich == plain
        assert _bytes(saved) == raw
        assert rich["summary"] == plain["summary"]
        assert rich["claims"] == plain["claims"]
        assert rich["move_checks"] == plain["move_checks"]
        assert rich["convergence"]["converged"] == plain["convergence"]["converged"]
    D.check(result, floor, doc)
    assert _outcome(result, doc).read_bytes() == raw


def test_flags_are_lazy_without_render_or_without_flags(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("optional measurement was unexpectedly called")
    monkeypatch.setattr(EL, "block", forbidden)
    monkeypatch.setattr(CT, "block", forbidden)
    floor = T._project(tmp_path / "floor", low_amp=.2)
    result = T._project(tmp_path / "result", low_amp=.3)
    doc = T._write_doc(tmp_path / "doc", T._minimal_block())
    assert D.check(result, floor, doc)["status"] == "checked"
    _outcome(result, doc).unlink()
    next((result / "renders").rglob("*.wav")).unlink()
    plain = D.check(result, floor, doc)
    assert plain["status"] == "incomplete"
    assert D.check(result, floor, doc, edit_list=True, contour=True) == plain


@pytest.fixture(scope="module")
def edited(tmp_path_factory):
    base = tmp_path_factory.mktemp("check_blocks")
    floor = TD._make(base / "floor")
    TD._render(floor)
    result = base / "result"
    shutil.copytree(floor, result)
    moves = [TD._duck(depth_db=3, release_ms=180),
             {"id": "m02", "aim": "a1", "op": "gain", "target": "trk_vocals",
              "section": {"t0_s": 1, "t1_s": 2}, "params": {"delta_db": -2},
              "basis": "space", "origin": "new"},
             {"id": "m03", "aim": "a1", "op": "gain_curve", "target": "trk_vocals",
              "params": {"segments": [{"t0_s": 3, "t1_s": 4, "delta_db": 2, "why": "phrase"},
                                      {"t0_s": 4.05, "t1_s": 5, "delta_db": 1, "why": "keep", "hold": True}]},
              "basis": "phrases", "origin": "new"}]
    doc = TD._doc(base / "doc", TD._block(moves))
    applied = D.apply(result, doc)
    assert applied["applied"], applied
    TD._render(result)
    return result, floor, doc


def test_edit_rows_values_hold_and_determinism(edited):
    result, floor, doc = edited
    block = D.check(result, floor, doc, edit_list=True)["edit_list"]
    assert list(block) == ["note", "mode", "row_count", "rows"]
    assert block["note"] == EDIT_NOTE and block["mode"] == "rows" and block["row_count"] == 4
    assert [r["move"] for r in block["rows"]] == ["m01", "m02", "m03", "m03"]
    for row, amount, why, span in zip(block["rows"][1:], [-2, 2, 0],
                                      ["space", "phrase", "keep"], [(1, 2), (3, 4), (4.05, 5)]):
        assert list(row) == ["move", "track", "t0_s", "t1_s", "amount_db", "why", "before_db", "after_db"]
        assert row["track"] == "trk_vocals"
        assert (row["t0_s"], row["t1_s"]) == span
        assert row["amount_db"] == amount and row["why"] == why
        assert row["before_db"] == pytest.approx(-23.010, abs=.002)
        assert row["after_db"] - row["before_db"] == pytest.approx(amount, abs=.02)
    raw = _outcome(result, doc).read_bytes()
    assert D.check(result, floor, doc, edit_list=True)["edit_list"] == block
    assert _outcome(result, doc).read_bytes() == raw


def test_duck_row_shape_and_planned_values(edited):
    result, floor, doc = edited
    row = D.check(result, floor, doc, edit_list=True)["edit_list"]["rows"][0]
    assert list(row) == ["move", "track", "key", "hits", "planned", "measured"]
    assert row["track"] == "trk_bass" and row["key"] == "trk_drums" and row["hits"] == TD.N_HITS
    assert row["planned"]["depth_db"] == 3
    assert row["planned"]["lead_ms"] == 5
    assert row["planned"]["release"]["ms"] == 180
    assert set(row["measured"]) == {"band_drop_db_median", "bottom_minus_onset_ms_median"}
    assert abs(row["measured"]["bottom_minus_onset_ms_median"]) <= 10


def test_duck_attenuation_is_a_positive_band_drop(edited):
    result, floor, doc = edited
    row = D.check(result, floor, doc, edit_list=True)["edit_list"]["rows"][0]
    # band_drop is floor minus result, on the same sign as planned.depth_db:
    # an attenuation is a positive drop, and it does not exceed the planned depth.
    drop = row["measured"]["band_drop_db_median"]
    assert drop > 0, row
    assert drop <= row["planned"]["depth_db"] + 0.5, row


@pytest.mark.parametrize("count", [0, 512, 513])
def test_edit_list_summary_boundary(tmp_path, count):
    class Source:
        def dry(self):
            return {"trk_vocals": np.full((6250, 2), .1)}, 1000
    moves = []
    left = count
    for i in range(3):
        n = min(171, left)
        left -= n
        if n:
            moves.append({"id": f"m{i}", "op": "gain_curve", "target": "trk_vocals", "basis": "span",
                          "params": {"segments": [{"t0_s": j * .02, "t1_s": j * .02 + .01,
                                                   "delta_db": i, "why": "segment"} for j in range(n)]}})
    project = SimpleNamespace(root=tmp_path)
    block = EL.block({"id": "dir_test", "block": {"moves": moves}}, project, project, None,
                     result_source=Source(), floor_source=Source())
    assert block["note"] == EDIT_NOTE and block["row_count"] == count
    assert block["mode"] == ("summary" if count > 512 else "rows")
    assert len(block["rows"]) == (3 if count > 512 else count)
    if count > 512:
        for i, row in enumerate(block["rows"]):
            assert row == {"move": f"m{i}", "track": "trk_vocals", "op": "gain_curve", "rows": 171,
                           "t0_s": 0.0, "t1_s": 3.41, "amount_db_range": [i, i], "why": "span",
                           "before_db": -20.0, "after_db": -20.0}


def _tone(seconds):
    t = np.arange(round(seconds * SR)) / SR
    return t, np.repeat(np.sin(2 * np.pi * 1000 * t)[:, None], 2, axis=1)


def test_contour_stairs_shape_match_gain_and_determinism():
    t, tone = _tone(24)
    fdb = np.repeat([-30, -24, -18], 8 * SR)
    rdb = np.repeat([-28, -25, -16], 8 * SR)
    floor, result = tone * 10 ** (fdb[:, None] / 20), tone * 10 ** (rdb[:, None] / 20)
    sections = [{"id": f"s{i}", "start_s": i * 8, "end_s": (i + 1) * 8} for i in range(3)]
    match = Q.integrated_lufs(floor, SR) - Q.integrated_lufs(result, SR)
    block = CT.block(result, floor, SR, match, sections)
    assert list(block) == ["note", "sections", "steps", "gaps"] and block["note"] == CONTOUR_NOTE
    assert block["steps"] == [{"from": "s0", "to": "s1", "floor": 6.0, "result": 3.0, "change": -3.0},
                               {"from": "s1", "to": "s2", "floor": 6.0, "result": 9.0, "change": 3.0}]
    for row in block["sections"].values():
        assert list(row) == ["lufs_s_mean", "side_ratio_db", "bright_db", "low_db", "slope_db_per_s"]
        assert all(set(pair) == {"floor", "result", "change"} for pair in row.values())
        assert abs(row["slope_db_per_s"]["floor"]) < .001
        assert abs(row["slope_db_per_s"]["result"]) < .001
    assert block["sections"]["s0"]["lufs_s_mean"]["change"] == pytest.approx(2 + match, abs=.002)
    assert json.dumps(CT.block(result, floor, SR, match, sections), allow_nan=False) == json.dumps(block, allow_nan=False)


def test_contour_slopes():
    t, tone = _tone(12)
    floor = tone * 10 ** ((-35 + .5 * t[:, None]) / 20)
    result = tone * 10 ** ((-35 - .25 * t[:, None]) / 20)
    row = CT.block(result, floor, SR, 3, [{"id": "ramp", "start_s": 0, "end_s": 12}])["sections"]["ramp"]
    assert row["slope_db_per_s"] == {"floor": .5, "result": -.25, "change": -.75}


def test_contour_real_gap_and_level_matched_residual():
    t, tone = _tone(8)
    floor, result = .1 * tone, .1 * tone
    quiet = (t >= 5) & (t < 5.5)
    floor[quiet] *= .0001
    result[quiet] *= .01
    block = CT.block(result, floor, SR, -2, [])
    assert block["sections"] == {} and block["steps"] == []
    assert block["gaps"] == [{"t0_s": 5.0, "t1_s": 5.5,
                               "residual_db": {"floor": -103.010, "result": -65.010, "change": 38.0}}]


def test_gap_duration_boundaries_and_cap():
    _, tone = _tone(46)
    floor = .1 * tone
    for a, b in [(1, 1.07), (3, 3.08), (6, 8), (10, 12.01)]:
        floor[round(a * SR):round(b * SR)] *= .0001
    assert CT.block(floor, floor, SR, 0, [])["gaps"] == [
        {"t0_s": a, "t1_s": b, "residual_db": {"floor": -103.010, "result": -103.010, "change": 0.0}}
        for a, b in [(3.0, 3.08), (6.0, 8.0)]]
    expected = [(3.0, 3.08), (6.0, 8.0)]
    for k in range(20):
        a, b = 14 + k * 1.5, 14.2 + k * 1.5
        floor[round(a * SR):round(b * SR)] *= .0001
        expected.append((round(a, 3), round(b, 3)))
    gaps = CT.block(floor, floor, SR, 0, [])["gaps"]
    assert [(g["t0_s"], g["t1_s"]) for g in gaps] == expected[:16]


def test_short_silent_contour_has_null_loudness_and_slope():
    silence = np.zeros((SR, 2))
    block = CT.block(silence, silence, SR, 0, [{"id": "short", "start_s": 0, "end_s": 1}])
    assert block["gaps"] == []
    for key in ("lufs_s_mean", "slope_db_per_s"):
        assert block["sections"]["short"][key] == {"floor": None, "result": None, "change": None}
    json.dumps(block, allow_nan=False)


def test_calibration_does_not_read_block_modules_or_outcomes(tmp_path, monkeypatch):
    source = Path(C.__file__).read_text(encoding="utf-8")
    for name in ("edit_list", "editlist", "contour"):
        assert name not in source
    song = TD._make(tmp_path / "song")
    doc = TD._doc(tmp_path / "doc", _cal_block([]))
    parsed = D.parse_document(doc)
    before = C.calibrate(song, parsed, progress=lambda s: None)
    assert before["renders"] > 1 and len(before["evaluations"]) > 1
    TD._render(song)
    floor = tmp_path / "floor"
    shutil.copytree(song, floor)
    rich = D.check(song, floor, doc, edit_list=True, contour=True)
    assert "edit_list" in rich and "contour" in rich
    # Persist hostile values to prove the predictor ignores the saved blocks as well.
    saved = json.loads(_outcome(song, doc).read_bytes())
    saved["edit_list"] = {"verdict": "fail", "amount_db": 1e9}
    saved["contour"] = {"converged": False, "change": -1e9}
    _outcome(song, doc).write_bytes(_bytes(saved))
    def forbidden(*args, **kwargs):
        pytest.fail("calibration read an optional block")
    monkeypatch.setattr(EL, "block", forbidden)
    monkeypatch.setattr(CT, "block", forbidden)
    after = C.calibrate(song, parsed, progress=lambda s: None)
    assert _canon(after) == _canon(before)


def test_cli_passes_both_flags_and_matches_api(edited, capsys):
    result, floor, doc = edited
    D.check(result, floor, doc, edit_list=True, contour=True)
    expected = _outcome(result, doc).read_bytes()
    main(["direction", "check", str(doc), "--project", str(result), "--floor", str(floor),
          "--edit-list", "--contour"])
    out = json.loads(capsys.readouterr().out)
    assert out["edit_list"]["note"] == EDIT_NOTE and out["contour"]["note"] == CONTOUR_NOTE
    assert _outcome(result, doc).read_bytes() == expected


def test_mix_side_view_is_accepted_and_measured(tmp_path):
    # Put a known 1 kHz side on an otherwise silent mix; matching must stay off.
    _, tone = _tone(TD.SECS)
    x = np.stack([.1 * tone[:, 0], -.1 * tone[:, 0]], axis=1)
    song = TD._make(tmp_path / "song", stems={"vocals": x})
    spec = {"id": "o1", "primitive": "band_energy", "target": "mix", "view": "side",
            "band_hz": [500, 2000], "level_match": True}
    doc = D.parse_document(TD._doc(tmp_path / "doc", TD._block([], observations=[spec], claims=[
        {"id": "c1", "quantity": "obs:o1", "direction": "not_worse", "tolerance": 1, "primary": True}])))
    validated = D.validate(doc, song)
    assert validated["ok"] and not validated["warnings"], validated
    row = R.observe_specs(song, [spec])["observations"][0]["result"]
    assert row["status"] == "ok"
    assert row["signal"] == "mix_stage" and row["gain_db"] == 0
    # band_energy uses the existing STFT normalization, rather than RMS dBFS.
    assert row["value"] == pytest.approx(-63.395, abs=.002)
    stereo = R.observe_specs(song, [{k: v for k, v in spec.items() if k != "view"}])
    assert stereo["observations"][0]["result"]["value"] < -190
