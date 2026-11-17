"""X-06: fixed limits, exact curve composition, traceability and legacy bytes."""

from __future__ import annotations

import copy
import json
import shutil

import numpy as np
import pytest

from mankomix.core.project import Project
from mankomix.director import calibrate as C
from mankomix.director import curve
from mankomix.director import direction as D
from mankomix.director import duck as K
from tests import test_upgrade2_duck as T
from tests.test_upgrade2_duck import _local_home, _template, song


def _segment(**over):
    return {"t0_s": 1.0, "t1_s": 2.0, "delta_db": 1.5, "why": "phrase head", **over}


def _move(mid="m01", target="trk_bass", **params):
    return {"id": mid, "aim": "a1", "op": "gain_curve", "target": target,
            "params": {"segments": [_segment()], **params}, "basis": "phrase balance", "origin": "new"}


def _parsed(tmp_path, moves, **over):
    return D.parse_document(T._doc(tmp_path / "doc", T._block(moves, **over)))


@pytest.mark.parametrize("params,code", [
    ({"segments": []}, "param_range"),
    ({"segments": [_segment(t0_s=i, t1_s=i + 0.5) for i in range(257)]}, "param_range"),
    ({"segments": [_segment(), _segment(t0_s=1.5, t1_s=3)]}, "bad_value"),
    ({"segments": [_segment(delta_db=-6.001)]}, "param_range"),
    ({"segments": [_segment(delta_db=6.001)]}, "param_range"),
    ({"segments": [_segment(delta_db=[-1, 1])]}, "bad_value"),
    ({"segments": [{k: v for k, v in _segment().items() if k != "why"}]}, "missing_field"),
    ({"segments": [_segment(why="x" * 201)]}, "param_range"),
    ({"segments": [_segment(why=1)]}, "bad_value"),
    ({"segments": [_segment(t1_s=1)]}, "bad_value"),
    ({"segments": [_segment(t1_s=0)]}, "bad_value"),
    ({"segments": [_segment(delta_db=True)]}, "bad_value"),
    ({"segments": [_segment(t0_s=float("nan"))]}, "bad_value"),
    ({"segments": [_segment(hold=1)]}, "bad_value"),
    ({"segments": [_segment(extra=1)]}, "bad_value"),
    ({"segments": "bad"}, "bad_value"),
    ({"segments": [None]}, "bad_value"),
    ({"ramp_ms": 4}, "param_range"),
    ({"ramp_ms": 201}, "param_range"),
    ({"ramp_ms": [5, 200]}, "bad_value"),
    ({"extra": 1}, "bad_value"),
])
def test_refuses_bad_params(tmp_path, params, code):
    result = D.validate(_parsed(tmp_path, [_move(**params)]))
    assert not result["ok"] and code in T._codes(result)


@pytest.mark.parametrize("section", [None, "all", "sec1", {"t0_s": 1, "t1_s": 2}])
def test_refuses_section(tmp_path, section):
    move = _move()
    move["section"] = section
    assert "section_scope" in T._codes(D.validate(_parsed(tmp_path, [move])))


@pytest.mark.parametrize("target", ["bus_mix", "master"])
def test_refuses_bus_and_master(song, tmp_path, target):
    assert "bad_target" in T._codes(D.validate(_parsed(tmp_path, [_move(target=target)]), song))


def test_unknown_keys_and_target(song, tmp_path):
    move = _move()
    move["extra"] = 1
    assert "bad_value" in T._codes(D.validate(_parsed(tmp_path, [move])))
    assert "unknown_target" in T._codes(D.validate(_parsed(tmp_path, [_move(target="trk_absent")]), song))
    move = _move()
    del move["params"]["segments"]
    assert "missing_field" in T._codes(D.validate(_parsed(tmp_path, [move])))


@pytest.mark.parametrize("count", [1, 256])
@pytest.mark.parametrize("ramp", [5, 200])
def test_accepts_boundaries_and_touching(tmp_path, count, ramp):
    segs = [_segment(t0_s=i, t1_s=i + 1, delta_db=(-6 if i % 2 else 6), why="x" * 200)
            for i in range(count)]
    doc = _parsed(tmp_path, [_move(segments=list(reversed(segs)), ramp_ms=ramp)])
    result = D.validate(doc)
    assert result["ok"], result["errors"]
    assert C.knobs(doc, None) == []


@pytest.mark.parametrize("ramp", [5, 20, 200])
def test_ramp_shape(ramp):
    r = ramp / 1000
    pts = curve.points(T.SR, [_segment()], ramp, 4)
    times = np.array([0, 1 - r, 1 - r / 2, 1, 1.5, 2, 2 + r / 2, 2 + r, 3])
    assert K.evaluate(pts, times * T.SR) == pytest.approx([0, 0, .75, 1.5, 1.5, 1.5, .75, 0, 0])
    assert all(a[0] < b[0] for a, b in zip(pts, pts[1:]))


def test_touching_short_segments_retain_midpoint_values():
    segs = [_segment(t0_s=1, t1_s=1.01, delta_db=2),
            _segment(t0_s=1.01, t1_s=1.02, delta_db=-3)]
    pts = curve.points(T.SR, segs, 200, 3)
    assert K.evaluate(pts, np.array([1.005, 1.015]) * T.SR) == pytest.approx([2, -3])


@pytest.mark.parametrize("floor_on,gain_on,duck_on", [
    (f, g, d) for f in (False, True) for g in (False, True) for d in (False, True)
])
def test_exact_sum(song, tmp_path, monkeypatch, floor_on, gain_on, duck_on):
    base = [[0, 0], [24000, -1.5], [48000, 0]] if floor_on else []
    if base:
        p = Project.open(song)
        tracks = copy.deepcopy(p.data["tracks"])
        next(t for t in tracks if t["id"] == "trk_bass")["automation"] = {
            "gain_db": base, "owner": "mixplan"}
        p.set("/tracks", tracks, actor="human")
    monkeypatch.setattr(K, "key_hits", lambda *args: ([6000, 18000, 30000], T.SR))
    gain = {"id": "g", "aim": "a1", "op": "gain", "target": "trk_bass", "section": "sec2",
            "params": {"delta_db": -1}, "basis": "balance", "origin": "new"}
    moves = ([gain] if gain_on else []) + ([T._duck("d")] if duck_on else []) + [_move()]
    doc = _parsed(tmp_path, moves)
    assert D.validate(doc, song)["ok"]
    prop, record, _ = D.build_proposal(D._Project(song), doc)
    auto = prop["changes"]["tracks"]["trk_bass"]["automation"]
    xs = np.arange(int(T.SECS * T.SR) + 101, dtype=float)
    want = K.evaluate(base, xs) + K.evaluate(curve.points(T.SR, [_segment()], 20, T.SECS), xs)
    if gain_on:
        want += K.evaluate(D._automation(T.SR, [(3, T.SECS, -1)], None), xs)
    if duck_on:
        want += K.evaluate(K.plan(song, moves[0 if not gain_on else 1], {"key": "trk_drums"}, 120)["points"], xs)
    assert np.max(np.abs(K.evaluate(auto["gain_db"], xs) - want)) <= 1e-6
    assert auto["owner"] == "director"
    assert auto["move_ref"] == [f"{doc['id']}/{m['id']}" for m in moves]
    assert record["moves"]["m01"]["points"] > 0


@pytest.mark.parametrize("all_held", [False, True])
def test_hold_record_and_note(song, tmp_path, all_held):
    segs = [_segment(hold=all_held), _segment(t0_s=3, t1_s=4, delta_db=-2, hold=True)]
    original = copy.deepcopy(segs)
    doc = _parsed(tmp_path, [_move(segments=segs)])
    prop, record, notes = D.build_proposal(D._Project(song), doc)
    rec = record["moves"]["m01"]
    pts = prop["changes"]["tracks"]["trk_bass"]["automation"]["gain_db"]
    assert rec == {"op": "gain_curve", "track": "trk_bass", "ramp_ms": 20,
                   "segments": [{**s, "applied": not s.get("hold", False)} for s in original], "points": len(pts)}
    assert segs == original
    assert K.evaluate(pts, np.array([3, 3.5, 4]) * T.SR) == pytest.approx([0, 0, 0])
    assert notes == ["m01: 先に計算して書いても、見つけ間違いと直しすぎは起きる。効き目は実証していない"]
    if all_held:
        assert pts == []


def test_tiers_and_existing_listen_warnings(song, tmp_path):
    moves = [_move(), _move("m02", "trk_vocals")]
    for m in moves:
        m.update(origin="catalog", basis="R-11")
    result = D.validate(_parsed(tmp_path, moves), song)
    assert result["ok"] and result["tiers"] == {"m01": "E2", "m02": "E3"}
    warnings = [w for w in result["warnings"] if w["code"] != "unmeasured_quantity"]
    assert warnings == [
        {"where": "moves.m02", "code": "listen_for", "message": "an E3 move needs listen_for entries"},
        {"where": "listen_for", "code": "missing", "message": "E3 moves on the lead need listen_for"}]
    result = D.validate(_parsed(tmp_path, moves, listen_for=[{"t_s": 1, "what": "phrase level"}]), song)
    assert all(w["code"] not in ("listen_for", "missing") for w in result["warnings"])


@pytest.mark.parametrize("hold", [False, True])
def test_apply_check_move_ref_and_determinism(song, tmp_path, hold):
    floor = tmp_path / "floor"
    twin = tmp_path / "twin"
    shutil.copytree(song, floor)
    shutil.copytree(song, twin)
    T._render(floor)
    doc = _parsed(tmp_path, [_move(segments=[_segment(hold=hold)])])
    a = D.apply(song, doc["path"])
    b = D.apply(twin, doc["path"])
    assert a["applied"] and b["applied"]
    assert (song / "directions" / f"{doc['id']}.apply.json").read_bytes() == \
        (twin / "directions" / f"{doc['id']}.apply.json").read_bytes()
    T._render(song)
    out = D.check(song, floor, doc["path"])
    assert out["move_ref"]["ok"]
    assert out["move_ref"]["by_move"] == {"m01": ["automation:trk_bass"]}
    outcome = song / "directions" / f"{doc['id']}.outcome.json"
    raw = outcome.read_bytes()
    D.check(song, floor, doc["path"])
    assert outcome.read_bytes() == raw
    p = Project.open(song)
    tracks = copy.deepcopy(p.data["tracks"])
    next(t for t in tracks if t["id"] == "trk_bass")["automation"]["move_ref"] = []
    p.set("/tracks", tracks, actor="human")
    out = D.check(song, floor, doc["path"])
    assert not out["move_ref"]["ok"] and out["move_ref"]["moves_without_trace"] == ["m01"]


def test_without_curve_legacy_bytes(tmp_path, monkeypatch):
    from tests import test_direction_update as U
    proj = U._project(tmp_path / "p", low_amp=0.2)
    doc = D.parse_document(U._write_doc(tmp_path / "d", U._block()))

    def unexpected(*args, **kwargs):
        pytest.fail("gain_curve branch entered without a curve")

    monkeypatch.setattr(curve, "points", unexpected)
    monkeypatch.setattr(D, "_merge_curves", unexpected)
    prop, record, notes = D.build_proposal(D._Project(proj), doc)
    assert T._sha(json.dumps({"prop": prop, "record": record, "notes": notes},
                             ensure_ascii=False, sort_keys=True)) == T.BASE["proposal_synth"]
    block = U._minimal_block()
    block["moves"] = []
    path = U._write_doc(tmp_path / "empty", block)
    D.apply(proj, path)
    did = D.parse_document(path)["id"]
    assert T._masked((proj / "directions" / f"{did}.apply.json").read_text(encoding="utf-8")) == \
        T.BASE["apply_record_nomove"]


def test_without_curve_keeps_existing_automation_exception(tmp_path):
    T.test_section_gain_on_floor_automation_without_duck_is_still_refused(tmp_path)
