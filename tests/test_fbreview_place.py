"""The placement move ``place`` (FBREVIEW FR-5).

(a) the derivation: distance 2 with the default model -> fader -2.0 dB, shelf -1.0 dB @ 5000 Hz, send -20.0 dB;
    distance 8 / near_send_db -12 / send_db_per_doubling 6 -> the send sticks at -3.0 with send_clamped
(b) distance 1.0 adds no gain and no EQ
(c) the same placement written by hand with pan / gain / chain_add / send gives the same mix state
(d) validate: the four conflicts, ranges, unknown keys, room alone, bus / master targets, section
(e) apply + check: move_ref coverage is ok and the shelf / send carry the place's id
(f) review tier: E2 (also with origin catalog and on the lead)
(g) a direction without place: validate / proposal / apply record unchanged, place code never runs;
    --calibrate never takes a place parameter as a knob

Small synthetic projects in tmp_path; only (e) renders (24 kHz, a few seconds).
"""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from mankomix.director import calibrate as C
from mankomix.director import direction as D

import tests.test_direction_update as T
import tests.test_upgrade2_duck as K
import tests.test_upgrade2_edit as ED


@pytest.fixture(autouse=True)
def _local_home(tmp_path, monkeypatch):
    monkeypatch.setenv("MANKOMIX_HOME", str(tmp_path / "home"))


def _block(moves: list[dict], **over) -> dict:
    b = T._minimal_block()
    b["moves"] = moves
    b.update(over)
    return b


def _place(mid="m01", target="trk_vocals", origin="new", basis="placement", **params) -> dict:
    return {"id": mid, "aim": "a1", "op": "place", "target": target, "params": params, "basis": basis,
            "origin": origin}


def _mv(mid, op, target, params, **extra) -> dict:
    return {"id": mid, "aim": "a1", "op": op, "target": target, "params": params, "basis": "by hand",
            "origin": "new", **extra}


def _doc(tmp_path: Path, moves: list[dict], tag: str = "d", **over) -> dict:
    return D.parse_document(T._write_doc(tmp_path / tag, _block(moves, **over)))


def _build(tmp_path: Path, moves: list[dict], tag: str = "d", proj: Path | None = None):
    proj = proj or T._project(tmp_path / f"p_{tag}", low_amp=0.2)
    doc = _doc(tmp_path, moves, tag)
    v = D.validate(doc, proj)
    assert v["ok"], v["errors"]
    prop, record, notes = D.build_proposal(D._Project(proj), doc)
    return doc, prop, record


def _codes(res: dict) -> list[tuple[str, str]]:
    return [(e["where"], e["code"]) for e in res["errors"]]


# ---------------------------------------------------------------------------
# (a) (b) the derivation
# ---------------------------------------------------------------------------

def test_a_distance_two_with_the_default_model(tmp_path):
    doc, prop, record = _build(tmp_path, [_place(distance=2, room="bus_reverb")])
    r = record["moves"]["m01"]
    assert r == {"op": "place", "track": "trk_vocals", "azimuth": None, "width": None, "distance": 2.0,
                 "room": "bus_reverb",
                 "model": {"level_db_per_doubling": 2.0, "air_db_per_doubling": 1.0, "air_freq_hz": 5000.0,
                           "near_send_db": -24.0, "send_db_per_doubling": 4.0},
                 "derived": {"position": None, "width": None, "delta_db": -2.0, "air_gain_db": -1.0,
                             "send_level_db": -20.0, "send_clamped": False}}
    t = prop["changes"]["tracks"]["trk_vocals"]
    assert t["gain_db"] == -2.0
    shelf = t["chain"][-1]
    assert shelf["type"] == "eq" and shelf["move_ref"] == f"{doc['id']}/m01"
    assert shelf["params"] == {"shape": "high_shelf", "freq_hz": 5000.0, "gain_db": -1.0, "bw_oct": 1.9,
                               "phase": "minimum"}
    assert t["sends"] == [{"bus": "bus_reverb", "level_db": -20.0, "pre_fader": False, "owner": "director",
                           "move_ref": f"{doc['id']}/m01"}]
    assert "pan" not in t     # no azimuth / width: the pan is not touched


def test_a_send_sticks_at_minus_three_and_is_marked_clamped(tmp_path):
    _, prop, record = _build(tmp_path, [_place(distance=8, room="bus_reverb", near_send_db=-12,
                                               send_db_per_doubling=6)])
    dv = record["moves"]["m01"]["derived"]
    assert dv["send_level_db"] == -3.0 and dv["send_clamped"] is True
    assert dv["delta_db"] == -6.0 and dv["air_gain_db"] == -3.0
    assert prop["changes"]["tracks"]["trk_vocals"]["sends"][-1]["level_db"] == -3.0


def test_a_model_coefficients_and_rounding(tmp_path):
    out = D.place_derive({"distance": 3.0, "level_db_per_doubling": 3.0, "air_db_per_doubling": 0.5,
                          "air_freq_hz": 8000, "room": "bus_r"})
    # log2(3) = 1.58496...
    assert out["derived"] == {"position": None, "width": None, "delta_db": -4.75, "air_gain_db": -0.79,
                              "send_level_db": -17.66, "send_clamped": False}
    assert [m[0] for m in out["moves"]] == ["gain", "chain_add", "send"]
    assert out["moves"][1][2]["freq_hz"] == 8000.0


def test_b_distance_one_adds_neither_gain_nor_eq(tmp_path):
    floor = T._project(tmp_path / "pf", low_amp=0.2)
    doc, prop, record = _build(tmp_path, [_place(target="trk_bass", distance=1.0, azimuth=-0.5)], proj=floor)
    dv = record["moves"]["m01"]["derived"]
    assert dv["delta_db"] == 0.0 and dv["air_gain_db"] == 0.0 and dv["send_level_db"] is None
    t = prop["changes"]["tracks"]["trk_bass"]
    base = D._Project(floor).tracks()["trk_bass"]
    assert t["gain_db"] == base["gain_db"] and t["chain"] == base["chain"] and t["sends"] == []
    assert t["pan"] == {"position": -0.5, "width": 1.0}
    # with a room the send is near_send_db
    _, _, rec2 = _build(tmp_path, [_place(distance=1.0, room="bus_reverb")], tag="d2")
    assert rec2["moves"]["m01"]["derived"]["send_level_db"] == -24.0
    assert str(D.place_derive({"distance": 1.0})["derived"]["delta_db"]) == "0.0"   # no "-0.0"


# ---------------------------------------------------------------------------
# (c) the same as writing the four existing ops by hand
# ---------------------------------------------------------------------------

def _state(changes: dict) -> dict:
    """The mix state without ids, move_refs and reasons."""
    def strip(o):
        if isinstance(o, dict):
            return {k: strip(v) for k, v in o.items() if k not in ("id", "move_ref", "reason")}
        if isinstance(o, list):
            return [strip(v) for v in o]
        return o
    return strip({"tracks": changes.get("tracks"), "buses": changes.get("buses")})


@pytest.mark.parametrize("params, hand", [
    ({"azimuth": 0.3, "width": 0.8, "distance": 2, "room": "bus_reverb"},
     [("pan", {"position": 0.3, "width": 0.8}), ("gain", {"delta_db": -2.0}),
      ("chain_add", {"shape": "high_shelf", "freq_hz": 5000, "gain_db": -1.0, "bw_oct": 1.9, "phase": "minimum"}),
      ("send", {"bus": "bus_reverb", "level_db": -20.0, "pre_fader": False})]),
    ({"azimuth": [-0.6, -0.2], "distance": [2, 4], "level_db_per_doubling": 3, "air_freq_hz": 7000,
      "room": "bus_reverb", "near_send_db": -30, "send_db_per_doubling": 5},
     [("pan", {"position": -0.4}), ("gain", {"delta_db": -4.75}),
      ("chain_add", {"shape": "high_shelf", "freq_hz": 7000, "gain_db": -1.58, "bw_oct": 1.9, "phase": "minimum"}),
      ("send", {"bus": "bus_reverb", "level_db": -22.08, "pre_fader": False})]),
])
def test_c_place_equals_the_hand_written_moves(tmp_path, params, hand):
    _, p1, _ = _build(tmp_path, [_place(target="trk_bass", **params)], tag="place")
    moves = []
    for i, (op, p) in enumerate(hand):
        extra = {"processor": "eq"} if op == "chain_add" else {}
        moves.append(_mv(f"h{i}", op, "trk_bass", p, **extra))
    _, p2, _ = _build(tmp_path, moves, tag="hand")
    assert _state(p1["changes"]) == _state(p2["changes"])


def test_c_select_picks_the_end_of_a_range(tmp_path):
    m = _place(target="trk_bass", distance=[1, 4], azimuth=[-0.5, 0.5])
    m["select"] = {"distance": "max", "azimuth": "min"}
    _, _, rec = _build(tmp_path, [m])
    r = rec["moves"]["m01"]
    assert r["distance"] == 4.0 and r["azimuth"] == -0.5 and r["derived"]["delta_db"] == -4.0


def test_c_floor_send_to_the_same_bus_is_replaced_as_by_send(tmp_path):
    """A send already in the floor to the room bus: the place's send replaces it (the send op's behaviour)."""
    def floor(tag):
        root = T._project(tmp_path / tag, low_amp=0.2)
        data = json.loads((root / "project.json").read_text(encoding="utf-8"))
        data["tracks"][1]["sends"] = [{"bus": "bus_reverb", "level_db": -10.0, "pre_fader": False,
                                       "owner": "mixplan"}]
        (root / "project.json").write_text(json.dumps(data), encoding="utf-8")
        return root
    _, p1, _ = _build(tmp_path, [_place(distance=2, room="bus_reverb")], tag="a", proj=floor("fa"))
    _, p2, _ = _build(tmp_path, [_mv("h1", "gain", "trk_vocals", {"delta_db": -2.0}),
                                 _mv("h2", "chain_add", "trk_vocals", {"shape": "high_shelf", "freq_hz": 5000,
                                                                       "gain_db": -1.0, "bw_oct": 1.9,
                                                                       "phase": "minimum"}, processor="eq"),
                                 _mv("h3", "send", "trk_vocals", {"bus": "bus_reverb", "level_db": -20.0})],
                      tag="b", proj=floor("fb"))
    sends = p1["changes"]["tracks"]["trk_vocals"]["sends"]
    assert [(s["bus"], s["level_db"], s["owner"]) for s in sends] == [("bus_reverb", -20.0, "director")]
    assert _state(p1["changes"]) == _state(p2["changes"])


# ---------------------------------------------------------------------------
# (d) validate
# ---------------------------------------------------------------------------

BAD = [
    # conflicts
    ([_place(distance=2), _place("m02", distance=3)], ("moves.m02", "conflict")),
    ([_place(azimuth=0.2), _mv("m02", "pan", "trk_vocals", {"position": 0.1})], ("moves.m01", "conflict")),
    ([_place(width=0.5), _mv("m02", "pan", "trk_vocals", {"width": 1.2})], ("moves.m01", "conflict")),
    ([_place(distance=2), _mv("m02", "gain", "trk_vocals", {"delta_db": 1.0})], ("moves.m01", "conflict")),
    ([_place(distance=2, room="bus_reverb"), _mv("m02", "send", "trk_vocals", {"bus": "bus_reverb"})],
     ("moves.m01", "conflict")),
    # ranges
    ([_place(distance=9)], ("moves.m01.distance", "param_range")),
    ([_place(distance=0.5)], ("moves.m01.distance", "param_range")),
    ([_place(azimuth=[-2, 0])], ("moves.m01.azimuth", "param_range")),
    ([_place(width=2.5)], ("moves.m01.width", "param_range")),
    ([_place(distance=2, level_db_per_doubling=7)], ("moves.m01.level_db_per_doubling", "param_range")),
    ([_place(distance=2, air_db_per_doubling=4)], ("moves.m01.air_db_per_doubling", "param_range")),
    ([_place(distance=2, air_freq_hz=1000)], ("moves.m01.air_freq_hz", "param_range")),
    ([_place(distance=2, room="bus_reverb", near_send_db=-6)], ("moves.m01.near_send_db", "param_range")),
    ([_place(distance=2, send_db_per_doubling=6.5)], ("moves.m01.send_db_per_doubling", "param_range")),
    ([_place(distance=2, near_send_db=[-30, -20])], ("moves.m01.near_send_db", "bad_value")),
    ([_place(distance="far")], ("moves.m01.distance", "bad_value")),
    ([_place(distance=True)], ("moves.m01.distance", "bad_value")),
    # keys and fields
    ([_place(distance=2, depth=3)], ("moves.m01", "bad_value")),
    ([_place(room="bus_reverb")], ("moves.m01", "missing_field")),
    ([_place(room="bus_reverb")], ("moves.m01.room", "missing_field")),
    ([_place(azimuth=0.1, room="bus_reverb")], ("moves.m01.room", "missing_field")),
    ([_place(level_db_per_doubling=2)], ("moves.m01", "missing_field")),
    ([_place(distance=2, room="trk_bass")], ("moves.m01.room", "bad_value")),
    ([_place(distance=2, room="bus_nowhere")], ("moves.m01.room", "unknown_target")),
    # targets and section
    ([_place(target="bus_reverb", distance=2)], ("moves.m01", "bad_target")),
    ([_place(target="master", distance=2)], ("moves.m01", "bad_target")),
    ([_place(target="trk_nowhere", distance=2)], ("moves.m01", "unknown_target")),
    ([{**_place(distance=2), "section": "sec2"}], ("moves.m01", "section_scope")),
]


@pytest.mark.parametrize("moves, expected", BAD)
def test_d_errors(tmp_path, moves, expected):
    proj = T._project(tmp_path / "p", low_amp=0.2)
    res = D.validate(_doc(tmp_path, moves), proj)
    assert not res["ok"]
    assert expected in _codes(res), res["errors"]


def test_d_bus_target_without_a_project_and_a_new_bus_as_target(tmp_path):
    res = D.validate(_doc(tmp_path, [_place(target="bus_x", distance=2)]))
    assert ("moves.m01", "bad_target") in _codes(res)
    res = D.validate(_doc(tmp_path, [_mv("b1", "bus_add", "bus_room", {"name": "room"}), _place(target="bus_room", distance=2)],
                          tag="d2"), T._project(tmp_path / "p", low_amp=0.2))
    assert ("moves.m01", "bad_target") in _codes(res)


def test_d_what_is_not_a_conflict(tmp_path):
    """A section gain with distance, a send to another bus, a pan with distance only, other tracks."""
    proj = T._project(tmp_path / "p", low_amp=0.2)
    moves = [_mv("b1", "bus_add", "bus_room", {"name": "room"}),
             _place(distance=2, room="bus_room"),
             _mv("m02", "gain", "trk_vocals", {"delta_db": -1.0}, section="sec2"),
             _mv("m03", "send", "trk_vocals", {"bus": "bus_reverb", "level_db": -20.0}),
             _place("m04", target="trk_bass", distance=2),
             _mv("m05", "pan", "trk_bass", {"position": 0.2})]
    res = D.validate(_doc(tmp_path, moves), proj)
    assert res["ok"], res["errors"]


# ---------------------------------------------------------------------------
# (e) apply + check: move_ref coverage
# ---------------------------------------------------------------------------

def test_e_move_ref_coverage_after_apply_and_check(tmp_path):
    song = K._make(tmp_path / "song")
    floor = tmp_path / "floor"
    shutil.copytree(song, floor)
    K._render(floor)
    moves = [_mv("b1", "bus_add", "bus_room", {"chain": []}),
             _place(target="trk_bass", azimuth=-0.3, distance=2, room="bus_room"),
             _place("m02", target="trk_drums", width=0.8)]
    doc = T._write_doc(tmp_path / "d", _block(moves))
    a = D.apply(song, doc)
    assert a["applied"], a
    did = a["id"]
    rec = json.loads((song / "directions" / f"{did}.apply.json").read_text(encoding="utf-8"))
    assert set(rec["record"]["moves"]["m01"]) == {"op", "track", "azimuth", "width", "distance", "room",
                                                  "model", "derived"}
    K._render(song)
    out = D.check(song, floor, doc)
    assert out["move_ref"]["ok"], out["move_ref"]
    by = out["move_ref"]["by_move"]
    assert sorted(by["m01"]) == sorted(["dr.trk_bass.m01", "send:trk_bass->bus_room"])
    assert "m02" not in by          # pan only: traced by the apply record
    assert out["move_ref"]["moves_without_trace"] == []


def test_e_a_place_without_its_trace_is_reported(tmp_path):
    """The coverage logic itself: a record without the place, or a send without its item, is missing."""
    song = K._make(tmp_path / "song")
    floor = tmp_path / "floor"
    shutil.copytree(song, floor)
    K._render(floor)
    doc = T._write_doc(tmp_path / "d", _block([_place(target="trk_bass", distance=2)]))
    a = D.apply(song, doc)
    K._render(song)
    rp = song / "directions" / f"{a['id']}.apply.json"
    rec = json.loads(rp.read_text(encoding="utf-8"))
    rec["record"]["moves"].pop("m01")
    rp.write_text(json.dumps(rec), encoding="utf-8")
    out = D.check(song, floor, doc)
    assert out["move_ref"]["moves_without_trace"] == ["m01"] and not out["move_ref"]["ok"]


# ---------------------------------------------------------------------------
# (f) review tier
# ---------------------------------------------------------------------------

def test_f_place_is_e2_even_from_the_catalog_and_on_the_lead(tmp_path):
    proj = T._project(tmp_path / "p", low_amp=0.2)
    moves = [_place(target="trk_vocals", distance=2, origin="catalog", basis="R-06"),
             _place("m02", target="trk_bass", azimuth=0.4, origin="catalog", basis="R-06")]
    res = D.validate(_doc(tmp_path, moves), proj)
    assert res["ok"], res["errors"]
    assert res["tiers"] == {"m01": "E2", "m02": "E2"}
    # the same basis on a pan is E1 (the catalog rule stays as it was)
    res2 = D.validate(_doc(tmp_path, [{**_mv("m03", "pan", "trk_bass", {"width": 1.0}), "origin": "catalog",
                                       "basis": "R-06"}], tag="d2"), proj)
    assert res2["tiers"] == {"m03": "E1"}


# ---------------------------------------------------------------------------
# (g) nothing changes without place; calibration never takes a place parameter
# ---------------------------------------------------------------------------

def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


@pytest.mark.parametrize("folder", sorted(ED.BASE_VALIDATE))
def test_g_existing_directions_validate_byte_identical(folder, monkeypatch):
    monkeypatch.setattr(D, "_check_place", lambda *a, **k: pytest.fail("place code ran"))
    monkeypatch.setattr(D, "_place_conflicts", lambda *a, **k: pytest.fail("place code ran"))
    doc = D.parse_document(ED.SONG_DIR / folder / "direction.md")
    did, h = ED.BASE_VALIDATE[folder]
    assert doc["id"] == did
    assert ED._h(D.validate(doc)) == h


def test_g_proposal_and_apply_record_without_place_are_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "place_derive", lambda *a, **k: pytest.fail("place code ran"))
    proj = T._project(tmp_path / "p", low_amp=0.2)
    doc = D.parse_document(T._write_doc(tmp_path / "d", T._block()))
    assert _sha(json.dumps(D.validate(doc, proj), ensure_ascii=False, sort_keys=True)) == K.BASE["validate_synth"]
    prop, record, notes = D.build_proposal(D._Project(proj), doc)
    assert _sha(json.dumps({"prop": prop, "record": record, "notes": notes}, ensure_ascii=False,
                           sort_keys=True)) == K.BASE["proposal_synth"]
    assert prop["proposal_id"] == K.BASE["proposal_id"]
    assert _sha(json.dumps(C.knobs(doc, D._Project(proj)), ensure_ascii=False, sort_keys=True)) == K.BASE["knobs"]
    nomove = T._minimal_block()
    nomove["moves"] = []
    p2 = T._write_doc(tmp_path / "d2", nomove)
    D.apply(proj, p2)
    rid = D.parse_document(p2)["id"]
    assert K._masked((proj / "directions" / f"{rid}.apply.json").read_text(encoding="utf-8")) == \
        K.BASE["apply_record_nomove"]


def test_g_calibration_never_takes_a_place_parameter(tmp_path, monkeypatch):
    proj = T._project(tmp_path / "p", low_amp=0.2)
    b = T._block()
    b["moves"].append(_place("m09", target="trk_vocals", distance=[1, 4], azimuth=[-0.5, 0.5],
                             room="bus_reverb"))
    b["moves"] = [m for m in b["moves"] if m["id"] != "m05"]
    doc = D.parse_document(T._write_doc(tmp_path / "d", b))
    assert D.validate(doc, proj)["ok"]
    ks = C.knobs(doc, D._Project(proj))
    assert all(k["move"] != "m09" for k in ks) and ks
    monkeypatch.setattr(C, "_Predictor", K._FakePredictor)
    cal = C.calibrate(proj, doc, progress=lambda s: None)
    assert not any(k.startswith("m09.") for k in cal["selection"])
    prop, record, _ = D.build_proposal(D._Project(proj), doc, sel=cal["selection"])
    assert record["moves"]["m09"]["distance"] == 2.5 and record["moves"]["m09"]["azimuth"] == 0.0
