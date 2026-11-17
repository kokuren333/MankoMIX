"""FBREVIEW2 X-01 / X-02 / X-12: declarations, compatibility and reference-only outcomes."""

from __future__ import annotations

import copy
import json

import pytest

from mankomix.director import direction as D
from tests import test_director as TD
from tests import test_direction_update as T
from tests import test_upgrade2_duck as U


@pytest.fixture(autouse=True)
def _local_home(tmp_path, monkeypatch):
    monkeypatch.setenv("MANKOMIX_HOME", str(tmp_path / "home"))


@pytest.fixture(scope="module")
def projects(tmp_path_factory):
    root = tmp_path_factory.mktemp("frame")
    return (T._project(root / "floor", low_amp=0.2),
            T._project(root / "result", low_amp=0.3, width=0.7))


ROLES = ["lead_melody", "counter", "rhythm", "harmony_bed", "ornament", "double",
         "harmony_vocal", "call_response", "unknown"]
FRAME = {
    "lead": "voice", "yield": ["keys"], "keep": ["phrasing"], "roughness_ok": ["breath"],
    "scale": "small room", "era": {"year": 2024, "genre": "pop", "stance": "context"},
    "key_words": [{"t_s": 0.0, "text": "word"}, {"text": "untimed"}],
    "mono_keep": ["trk_vocals", "trk_bass"],
    "section_roles": [{"section": "sec1", "lead": "trk_vocals", "roles": {"trk_bass": ROLES}},
                      {"section": {"t0_s": 1.0, "t1_s": 2.0}, "roles": {}}],
    "tolerances": [{"quantity": "obs:o1", "range": [-100.0, 100.0], "note": "context"}],
}
TRIAGE = {
    "decision": "fix",
    "options": [{"choice": c, "gains": "alternative", "loses": ["phrasing"]}
                for c in ("fix", "replace", "regenerate", "leave")],
    "findings": [{"what": "texture", "track": "trk_vocals", "t_s": 0.0,
                  "status": s, "basis": "listening", "move": "m01"}
                 for s in ("fix", "unknown", "intentional", "no_change")],
}
SCENE = {"sources": [{"track": "trk_vocals", "depth": 1}]}


def _json(value):
    # Preserve insertion order as well as values.
    return json.dumps(value, ensure_ascii=False, indent=2)


def _validate(tmp_path, block, project=None):
    doc = D.parse_document(T._write_doc(tmp_path, block))
    first = D.validate(doc, project)
    assert _json(first) == _json(D.validate(doc, project))
    return first


def _addition(field, value):
    if field == "room":
        return {"scene": {**copy.deepcopy(SCENE), "room": value}}
    return {field: value}


@pytest.mark.parametrize("addition,with_project", [
    pytest.param({"frame": FRAME}, False, id="full-frame"),
    pytest.param({"frame": FRAME}, True, id="full-frame-project"),
    pytest.param({"frame": {}}, False, id="empty-frame"),
    pytest.param({"triage": TRIAGE}, False, id="full-triage"),
    pytest.param({"triage": TRIAGE}, True, id="full-triage-project"),
    pytest.param(_addition("room", {"note": "room"}), False, id="room-note"),
    pytest.param(_addition("room", {"note": "room", "bus": "bus_reverb"}), True, id="existing-bus"),
    pytest.param(_addition("room", {"note": "room", "bus": "bus_unresolved"}), False,
                 id="bus-without-project"),
    pytest.param({"frame": {"mono_keep": ["trk_unresolved"]},
                  "triage": {"decision": "leave", "findings": [
                      {"what": "x", "status": "unknown", "basis": "x", "track": "trk_unresolved"}]}},
                 False, id="tracks-without-project"),
])
def test_accepts_declarations(tmp_path, projects, addition, with_project):
    block = TD._block(**copy.deepcopy(addition))
    out = _validate(tmp_path, block, projects[0] if with_project else None)
    assert out["ok"] and out["errors"] == [] and out["warnings"] == [], out


def test_room_accepts_bus_added_in_same_direction(tmp_path, projects):
    block = TD._block(**_addition("room", {"note": "room", "bus": "bus_room"}))
    block["moves"].append({"id": "m02", "aim": "a1", "op": "bus_add", "target": "bus_room",
                           "params": {"chain": []}, "basis": "x", "origin": "new"})
    out = _validate(tmp_path, block, projects[0])
    assert out["ok"] and out["warnings"] == [], out


@pytest.mark.parametrize("year", [1900, 2100])
def test_accepts_limits(tmp_path, year):
    frame = copy.deepcopy(FRAME)
    frame.update({"lead": "文" * 400, "yield": ["x"] * 16, "keep": ["x"] * 16,
                  "roughness_ok": ["x"] * 16, "mono_keep": ["trk_vocals"] * 16,
                  "key_words": [{"text": "x"}] * 64,
                  "section_roles": [{"section": "all", "roles": {"trk_bass": ["unknown"] * 16}}] * 64,
                  "tolerances": [{"quantity": "obs:o1", "range": [-1, 1]}] * 16})
    frame["era"]["year"] = year
    triage = copy.deepcopy(TRIAGE)
    triage["options"] = [triage["options"][0]] * 8
    triage["findings"] = [triage["findings"][0]] * 64
    out = _validate(tmp_path, TD._block(frame=frame, triage=triage))
    assert out["ok"] and out["warnings"] == [], out


def _refusal_cases():
    cases = []

    def add(tag, field, value, where, code="bad_value", project=False):
        cases.append(pytest.param(_addition(field, value), (where, code), project, id=tag))

    add("frame-unknown", "frame", {"unexpected": 1}, "frame")
    for key in ("lead", "scale"):
        add(f"long-{key}", "frame", {key: "文" * 401}, f"frame.{key}", "param_range")
    for key in ("yield", "keep", "roughness_ok"):
        add(f"long-{key}", "frame", {key: ["x" * 401]}, f"frame.{key}[0]", "param_range")
        add(f"many-{key}", "frame", {key: ["x"] * 17}, f"frame.{key}", "param_range")
    for key in ("genre", "stance"):
        add(f"long-era-{key}", "frame", {"era": {key: "x" * 401}}, f"frame.era.{key}", "param_range")
    add("long-key-word", "frame", {"key_words": [{"text": "x" * 401}]},
        "frame.key_words[0].text", "param_range")
    add("many-key-words", "frame", {"key_words": [{"text": "x"}] * 65}, "frame.key_words", "param_range")
    add("many-section-roles", "frame", {"section_roles": [{"section": "all", "roles": {}}] * 65},
        "frame.section_roles", "param_range")
    add("many-roles", "frame", {"section_roles": [
        {"section": "all", "roles": {"trk_bass": ["rhythm"] * 17}}]},
        "frame.section_roles[0].roles.trk_bass", "param_range")
    add("role-vocabulary", "frame", {"section_roles": [
        {"section": "all", "roles": {"trk_bass": ["soloist"]}}]},
        "frame.section_roles[0].roles.trk_bass[0]")
    for tag, time, code in (("negative", -0.1, "param_range"), ("nan", float("nan"), "bad_value"),
                            ("inf", float("inf"), "bad_value"), ("neg-inf", -float("inf"), "bad_value")):
        add(f"word-time-{tag}", "frame", {"key_words": [{"text": "x", "t_s": time}]},
            "frame.key_words[0].t_s", code)
        add(f"finding-time-{tag}", "triage", {"decision": "leave", "findings": [
            {"what": "x", "status": "unknown", "basis": "x", "t_s": time}]},
            "triage.findings[0].t_s", code)
    for year, code in ((1899, "param_range"), (2101, "param_range"), (2024.5, "bad_value")):
        add(f"year-{year}", "frame", {"era": {"year": year}}, "frame.era.year", code)
    add("mono-not-list", "frame", {"mono_keep": "trk_bass"}, "frame.mono_keep")
    add("mono-bad-id", "frame", {"mono_keep": ["bus_mix"]}, "frame.mono_keep[0]")
    add("mono-missing", "frame", {"mono_keep": ["trk_missing"]},
        "frame.mono_keep[0]", "unknown_target", True)
    add("many-mono", "frame", {"mono_keep": ["trk_bass"] * 17}, "frame.mono_keep", "param_range")
    for quantity in ("P-01", "obs:missing"):
        add(f"quantity-{quantity}", "frame", {"tolerances": [{"quantity": quantity, "range": [-1, 1]}]},
            "frame.tolerances[0].quantity", "bad_quantity")
    ranges = [("equal", [1, 1], "param_range"), ("reversed", [2, 1], "param_range")]
    for tag, value in (("nan", float("nan")), ("inf", float("inf")), ("neg-inf", -float("inf"))):
        ranges.extend((f"{tag}-{side}", [value, 1] if side == 0 else [0, value], "bad_value")
                      for side in (0, 1))
    for tag, limits, code in ranges:
        add(f"range-{tag}", "frame", {"tolerances": [{"quantity": "obs:o1", "range": limits}]},
            "frame.tolerances[0].range", code)
    add("long-tolerance-note", "frame", {"tolerances": [
        {"quantity": "obs:o1", "range": [-1, 1], "note": "x" * 401}]},
        "frame.tolerances[0].note", "param_range")
    add("many-tolerances", "frame", {"tolerances": [{"quantity": "obs:o1", "range": [-1, 1]}] * 17},
        "frame.tolerances", "param_range")
    add("decision-enum", "triage", {"decision": "skip"}, "triage.decision")
    option = {"choice": "leave", "gains": "x", "loses": ["x"]}
    for tag, key, value, suffix, code in (
        ("choice-enum", "choice", "skip", "choice", "bad_value"),
        ("long-gains", "gains", "x" * 401, "gains", "param_range"),
        ("long-loses", "loses", ["x" * 401], "loses[0]", "param_range"),
        ("many-loses", "loses", ["x"] * 17, "loses", "param_range"),
    ):
        add(tag, "triage", {"decision": "leave", "options": [{**option, key: value}]},
            f"triage.options[0].{suffix}", code)
    add("many-options", "triage", {"decision": "leave", "options": [option] * 9},
        "triage.options", "param_range")
    finding = {"what": "x", "status": "unknown", "basis": "x"}
    for tag, key, value, code, project in (
        ("status-enum", "status", "skip", "bad_value", False),
        ("long-what", "what", "x" * 401, "param_range", False),
        ("long-basis", "basis", "x" * 401, "param_range", False),
        ("missing-move", "move", "m99", "bad_id", False),
        ("missing-track", "track", "trk_missing", "unknown_target", True),
    ):
        add(tag, "triage", {"decision": "leave", "findings": [{**finding, key: value}]},
            f"triage.findings[0].{key}", code, project)
    add("many-findings", "triage", {"decision": "leave", "findings": [finding] * 65},
        "triage.findings", "param_range")
    add("room-no-note", "room", {}, "scene.room.note", "missing_field")
    add("room-bus-prefix", "room", {"note": "x", "bus": "trk_bass"}, "scene.room.bus")
    add("room-missing-bus", "room", {"note": "x", "bus": "bus_missing"},
        "scene.room.bus", "unknown_target", True)
    add("room-string-legacy", "room", "big", "scene")
    add("room-long-note", "room", {"note": "x" * 401}, "scene.room.note", "param_range")
    return cases


@pytest.mark.parametrize("addition,want,with_project", _refusal_cases())
def test_rejects_one_condition(tmp_path, projects, addition, want, with_project):
    out = _validate(tmp_path, TD._block(**copy.deepcopy(addition)), projects[0] if with_project else None)
    assert not out["ok"]
    assert [(e["where"], e["code"]) for e in out["errors"]] == [want], out
    assert out["warnings"] == []


@pytest.mark.parametrize("decision,has_moves", [("fix", False), ("leave", True)])
def test_triage_does_not_require_consistency_with_moves(tmp_path, decision, has_moves):
    block = TD._block(triage={"decision": decision, "findings": [
        {"what": "texture", "status": "fix", "basis": "context"}]})
    if not has_moves:
        block["moves"] = []
    out = _validate(tmp_path, block)
    assert out["ok"] and out["warnings"] == [], out
    assert out["moves"] == (1 if has_moves else 0)


# Captured with git HEAD:director/direction.py before WP-24/25, using TD._block().
BASE_VALIDATE = {"kind": "direction_validation", "id": "dir_6ce9fde95356", "ok": True,
                 "errors": [], "warnings": [], "tiers": {"m01": "E1"}, "notes": [],
                 "moves": 1, "claims": 1, "observations": 1}


@pytest.mark.parametrize("addition", [{"frame": {}}, {"triage": TRIAGE},
                                      {"frame": FRAME, "triage": TRIAGE}],
                         ids=["frame", "triage", "both"])
def test_absent_fields_keep_baseline_json_and_id(tmp_path, addition, monkeypatch):
    block = TD._block()
    plain = _validate(tmp_path / "plain", block)
    assert _json(plain) == _json(BASE_VALIDATE)
    changed = _validate(tmp_path / "added", TD._block(**copy.deepcopy(addition)))
    assert changed["id"] != plain["id"]
    assert _json({**changed, "id": plain["id"]}) == _json(plain)
    restored = TD._block(**copy.deepcopy(addition))
    for key in addition:
        restored.pop(key)
    assert D.direction_id(restored) == BASE_VALIDATE["id"]
    # An omitted declaration must not enter either new validation branch.
    def unexpected(*args, **kwargs):
        pytest.fail("declaration validation ran for an absent field")
    monkeypatch.setattr(D, "_check_frame", unexpected)
    monkeypatch.setattr(D, "_check_triage", unexpected)
    assert _json(_validate(tmp_path / "restored", restored)) == _json(BASE_VALIDATE)


def test_omitting_frame_adds_no_warning(tmp_path):
    block = TD._block()
    plain = _validate(tmp_path / "plain", block)
    declared = _validate(tmp_path / "declared", {**block, "frame": {}})
    assert plain["warnings"] == declared["warnings"] == []
    # Existing warnings also stay intact when a declaration is omitted.
    minimal = T._minimal_block()
    a = _validate(tmp_path / "minimal", minimal)
    b = _validate(tmp_path / "minimal-frame", {**minimal, "frame": {}})
    assert a["warnings"] == b["warnings"] == [T.WARN_P03_B]


def _check(tmp_path, projects, block):
    path = T._write_doc(tmp_path, block)
    floor, result = projects
    first = D.check(result, floor, path)
    raw = (result / first["outcome_path"]).read_bytes()
    assert _json(first) == _json(D.check(result, floor, path))
    assert (result / first["outcome_path"]).read_bytes() == raw
    return first, raw


def _assert_only_reference_added(plain, added, key):
    expected = {k: v for k, v in plain.items() if k not in ("direction", "outcome_path")}
    actual = {k: v for k, v in added.items() if k not in ("direction", "outcome_path", key)}
    assert _json(actual) == _json(expected)
    # This also fixes every claim / expectation / safeguard verdict and the summary.
    for field in ("claims", "move_checks", "summary", "status"):
        assert plain[field] == added[field]


@pytest.mark.parametrize("tag,block", [("plain", T._block()), ("min", T._minimal_block()),
                                       ("refs", T._with_refs(T._block()))])
def test_check_without_fields_matches_existing_byte_golden(tmp_path, projects, tag, block):
    out, raw = _check(tmp_path, projects, block)
    assert "frame" not in out
    assert U._masked(raw.decode("utf-8")) == U.BASE["outcome"][tag]


@pytest.mark.parametrize("frame", [{}, {"lead": "voice", "keep": ["phrasing"]}])
def test_check_frame_without_tolerances_adds_no_key(tmp_path, projects, frame):
    plain, _ = _check(tmp_path / "plain", projects, T._block())
    declared, _ = _check(tmp_path / "declared", projects, T._block(frame=frame))
    assert "frame" not in declared
    _assert_only_reference_added(plain, declared, "frame")


def test_check_tolerances_reuse_observations_and_do_not_change_verdicts(tmp_path, projects, monkeypatch):
    plain, _ = _check(tmp_path / "plain", projects, T._block())
    observe = D.Q.observe
    calls = []
    def counted(*args, **kwargs):
        calls.append(args[2]["id"])
        return observe(*args, **kwargs)
    monkeypatch.setattr(D.Q, "observe", counted)
    frame = {"tolerances": [{"quantity": "obs:o1", "range": [-200, 200]},
                            {"quantity": "obs:o2", "range": [100, 200]}]}
    out, _ = _check(tmp_path / "frame", projects, T._block(frame=frame))
    assert len(calls) == 12  # Two checks, result + floor for each of three observations.
    assert out["frame"]["note"] == "参考値。どの判定にも入らない"
    rows = out["frame"]["tolerances"]
    assert [r["within"] for r in rows] == [True, False]
    for row, declaration in zip(rows, frame["tolerances"]):
        values = out["observations"][declaration["quantity"][4:]]
        assert row == {**declaration, "floor": round(values["floor"]["value"], 3),
                       "result": round(values["result"]["value"], 3), "within": row["within"]}
    _assert_only_reference_added(plain, out, "frame")


@pytest.mark.parametrize("floor_value,result_value,want", [
    pytest.param({"value": 0.12356}, {"value": 0.23456}, (0.124, 0.235, True), id="rounded"),
    pytest.param({"value": 0.5}, {"value": 0}, (0.5, 0.0, True), id="lower-inclusive"),
    pytest.param({"value": 0.5}, {"value": 1}, (0.5, 1.0, True), id="upper-inclusive"),
    pytest.param({"value": 0.5}, {"value": 1.001}, (0.5, 1.001, False), id="outside"),
    pytest.param({}, {"value": 0.5}, (None, 0.5, None), id="floor-missing"),
    pytest.param({"value": 0.5}, {}, (0.5, None, None), id="result-missing"),
    pytest.param({}, {}, (None, None, None), id="both-missing"),
    pytest.param({"status": "error", "value": 0.5}, {"value": 0.5}, (None, 0.5, None), id="floor-error"),
    pytest.param({"value": 0.5}, {"status": "error", "value": 0.5}, (0.5, None, None), id="result-error"),
])
def test_check_tolerance_boundaries_and_null(tmp_path, projects, monkeypatch, floor_value, result_value, want):
    # Inject measured responses, keeping the actual check / outcome / verdict path.
    replies = iter([result_value, floor_value] * 4)
    monkeypatch.setattr(D.Q, "observe", lambda *args, **kwargs: next(replies))
    block = T._minimal_block()
    block["observations"] = [{"id": "o1", "primitive": "crest", "target": "master"}]
    plain, _ = _check(tmp_path / "plain", projects, block)
    block["frame"] = {"tolerances": [{"quantity": "obs:o1", "range": [0, 1]}]}
    out, _ = _check(tmp_path / "frame", projects, block)
    row = out["frame"]["tolerances"][0]
    assert (row["floor"], row["result"], row["within"]) == want
    _assert_only_reference_added(plain, out, "frame")


def test_check_empty_tolerances_still_add_frame(tmp_path, projects):
    plain, _ = _check(tmp_path / "plain", projects, T._block())
    out, _ = _check(tmp_path / "frame", projects, T._block(frame={"tolerances": []}))
    assert out["frame"] == {"tolerances": [], "note": "参考値。どの判定にも入らない"}
    _assert_only_reference_added(plain, out, "frame")


@pytest.mark.parametrize("room", [{"note": "room"}, {"bus": "bus_reverb", "note": "room"}])
def test_check_copies_room_without_changing_verdicts(tmp_path, projects, room):
    plain, _ = _check(tmp_path / "plain", projects, T._block(scene=copy.deepcopy(SCENE)))
    assert "room" not in plain["scene"]
    out, _ = _check(tmp_path / "room", projects, T._block(**_addition("room", room)))
    assert _json(out["scene"]["room"]) == _json(room)
    stripped = copy.deepcopy(out)
    stripped["scene"].pop("room")
    _assert_only_reference_added(plain, stripped, "room")


def test_check_ignores_triage(tmp_path, projects):
    plain, _ = _check(tmp_path / "plain", projects, T._block())
    out, _ = _check(tmp_path / "triage", projects, T._block(triage=copy.deepcopy(TRIAGE)))
    assert "triage" not in out
    _assert_only_reference_added(plain, out, "triage")
