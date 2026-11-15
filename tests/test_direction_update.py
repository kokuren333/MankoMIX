"""Direction format additions (T-9) and song dossier v2 (T-10).

- backward compatibility: the three existing directions validate and keep their ``dir_`` ids; a document
  without the added fields gives byte-identical validate / proposal / check output (hashes of the output
  of the code before the additions, on a small synthetic project)
- the minimal direction (no added field, no analysis memo) goes through validate / apply / check without
  any stage being asked for (U-17)
- the added fields: request.like, sources.references, origin: reference, observations[].ref_value; their
  format errors; origin: reference is never E1; the invariant area is not bypassed through them;
  reference_distance is reported but never judged; --calibrate does not read ref_value
- dossier v2: 12 headings, version 2, 10.2 theory shelf (id and title only, separate from the 8-card cap),
  10.3 references

Fast and self-contained: tiny synthetic projects in tmp_path, no rendering of a real project.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from mankomix import repo_data_root
from mankomix.core import audio_io
from mankomix.director import calibrate as C
from mankomix.director import direction as D
from mankomix.director import dossier as DS
from mankomix.director import query as Q

SR = 48000
EXISTING = {
    "2026-11-14_p1-kikigokochi": "dir_68e88f393670",
    "2026-11-14_p2-ultra-sub-bass": "dir_2a6c9969107a",
    "2026-11-14_p3-spatial-panning": "dir_b465721f74fb",
}
SONG_DIR = repo_data_root() / "kb" / "songs" / "manko-shugi"


def _h(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# synthetic project (floor + result renders)
# ---------------------------------------------------------------------------

def _tone(freq: float, amp: float, secs: float = 2.0) -> np.ndarray:
    t = np.arange(int(SR * secs)) / SR
    return amp * np.sin(2 * np.pi * freq * t)


def _project(root: Path, *, low_amp: float, width: float = 1.0) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    data = {
        "timebase": {"sample_rate": SR, "length_samples": 2 * SR},
        "tracks": [
            {"id": "trk_bass", "kind": "audio", "role": "bass", "gain_db": -2.0,
             "chain": [{"id": "mx.trk_bass.eq", "type": "eq", "owner": "mixplan",
                        "params": {"shape": "peak", "freq_hz": 200.0, "gain_db": -1.0, "bw_oct": 1.0}}],
             "sends": [], "pan": {"position": 0.0, "width": 1.0}},
            {"id": "trk_vocals", "kind": "audio", "role": "vocals", "gain_db": 0.0, "chain": [], "sends": []},
        ],
        "buses": [{"id": "bus_mix", "kind": "mix", "chain": []},
                  {"id": "bus_reverb", "kind": "fx", "output": "bus_mix", "chain": []}],
        "mix": {"applied": {"proposal_id": "mxp_floor"}},
        "variants": [{"id": "var_x", "master": {"profile": "streaming_universal", "chain": []}}],
    }
    (root / "project.json").write_text(json.dumps(data), encoding="utf-8")
    pdir = root / "cache" / "proposals"
    pdir.mkdir(parents=True, exist_ok=True)
    floor = {"stage": "mix", "status": "applied", "proposal_id": "mxp_floor",
             "changes": {"mix_bus": "bus_mix", "tracks": {}, "buses": []},
             "sections": [{"id": "sec1", "start_s": 0.0, "end_s": 1.0, "label": "quiet"},
                          {"id": "sec2", "start_s": 1.0, "end_s": 2.0, "label": "loud"}],
             "objective_evaluation": {"score": 0.1}, "measurements": {}, "notes": []}
    (pdir / "mxp_floor.json").write_text(json.dumps(floor), encoding="utf-8")
    rd = root / "renders" / "var_x"
    rd.mkdir(parents=True, exist_ok=True)
    left = _tone(50, low_amp) + _tone(1000, 0.1)
    right = _tone(50, low_amp) + _tone(1000, 0.1 * width)
    audio_io.write(rd / "song__hires_native.wav", np.stack([left, right], axis=1), SR)
    return root


def _block(**over) -> dict:
    b = {
        "schema_version": 1, "kind": "direction", "song": "s",
        "request": {"pattern": "p1", "utterance": "test"},
        "sources": {"analysis": None, "dossier_sha256": "0", "cards": []},
        "aims": [{"id": "a1", "phrase": "x", "text": "x", "confidence": "high", "assumption": "-"}],
        "variants": [{"id": "var_x", "profile": "streaming_universal", "delivery": ["hires_native"],
                      "target_lufs": None, "reason": "default"}],
        "moves": [
            {"id": "m01", "aim": "a1", "stage": "mix", "target": "trk_bass", "section": None,
             "op": "chain_add", "processor": "eq",
             "params": {"shape": "low_shelf", "freq_hz": 80, "gain_db": [1.5, 3.0], "bw_oct": 1.0},
             "select": {"gain_db": "max"}, "basis": "R-06", "origin": "catalog",
             "expect": [{"quantity": "obs:o1", "direction": "up", "min_delta": 1.0}],
             "safeguard": [{"quantity": "obs:o2", "direction": "not_worse", "tolerance": 0.5}]},
            {"id": "m02", "aim": "a1", "target": "trk_bass", "op": "chain_param", "replaces": "mx.trk_bass.eq",
             "params": {"gain_db": -2.0}, "basis": "this song", "origin": "case"},
            {"id": "m03", "aim": "a1", "target": "trk_vocals", "op": "gain", "section": "sec2",
             "params": {"delta_db": -1.0}, "basis": "x", "origin": "new"},
            {"id": "m04", "aim": "a1", "target": "trk_bass", "op": "pan", "params": {"width": [0.8, 0.9]},
             "basis": "x", "origin": "new"},
            {"id": "m05", "aim": "a1", "target": "trk_vocals", "op": "send",
             "params": {"bus": "bus_reverb", "level_db": -18.0}, "basis": "x", "origin": "new"},
        ],
        "claims": [{"id": "c1", "quantity": "obs:o1", "vs": "floor", "direction": "up", "min_delta": 1.0,
                    "primary": True},
                   {"id": "c2", "quantity": "obs:o2", "vs": "floor", "direction": "not_worse", "tolerance": 0.5}],
        "observations": [{"id": "o1", "primitive": "band_energy", "target": "master", "band_hz": [20, 80],
                          "section": "all", "level_match": True},
                         {"id": "o2", "primitive": "side_ratio", "target": "master", "section": "sec2"},
                         {"id": "o3", "primitive": "crest", "target": "master"}],
        "listen_for": [{"t_s": 1.2, "what": "vocal"}],
    }
    b.update(over)
    return b


def _write_doc(dirpath: Path, block: dict, name: str = "direction.md") -> Path:
    dirpath.mkdir(parents=True, exist_ok=True)
    did = D.direction_id(block)
    p = dirpath / name
    p.write_text(f"---\nid: {did}\nkind: direction\ntitle: t\ncreated: 2026-11-15\nstatus: draft\n"
                 f"visibility: private\n---\n\n# t\n\n```json direction\n{json.dumps(block, ensure_ascii=False)}\n```\n",
                 encoding="utf-8")
    return p


def _minimal_block() -> dict:
    """The smallest direction: required fields only, no added field, no observation, no analysis memo."""
    return {"schema_version": 1, "kind": "direction", "song": "s", "request": {"utterance": "vocal 1 dB up"},
            "sources": {}, "aims": [{"id": "a1", "text": "vocal forward"}],
            "variants": [{"id": "var_x", "profile": "streaming_universal"}],
            "moves": [{"id": "m01", "aim": "a1", "target": "trk_vocals", "op": "gain", "params": {"delta_db": 1.0},
                       "basis": "the request", "origin": "new"}],
            "claims": [{"id": "c1", "quantity": "P-03", "direction": "up", "min_delta": 0.5, "primary": True}]}


def _with_refs(b: dict) -> dict:
    b = copy.deepcopy(b)
    b["request"]["like"] = ["work_sample-song", "eng_some-one"]
    b["sources"]["references"] = [{"work": "work_sample-song", "study_sha256": "ab" * 8, "refsheet_sha256": "cd" * 8}]
    for o in b["observations"]:
        o["ref_value"] = {"o1": -30.0, "o2": -12.5, "o3": 9.0}[o["id"]]
    b["moves"][3]["origin"] = "reference"
    b["moves"][3]["basis"] = "ref:work_sample-song §2 (width of the bass)"
    return b


def _outcome_hash(raw: bytes) -> str:
    """sha256 of the outcome file with the gate-definition hash masked (it hashes knowledge/ and profiles/
    files whose bytes depend on the checkout's line endings, not on direction.py)."""
    gate = D.gate_definitions_hash()["combined"].encode()
    return hashlib.sha256(raw.replace(gate, b"<gate>")).hexdigest()[:16]


def _check_out(tmp_path: Path, block: dict, tag: str) -> tuple[dict, bytes]:
    floor = _project(tmp_path / f"floor_{tag}", low_amp=0.2)
    res = _project(tmp_path / f"res_{tag}", low_amp=0.3, width=0.7)
    doc = _write_doc(tmp_path / f"doc_{tag}", block)
    out = D.check(res, floor, doc)
    raw = (res / "directions" / f"{D.parse_document(doc)['id']}.outcome.json").read_bytes()
    return out, raw


# ---------------------------------------------------------------------------
# backward compatibility
# ---------------------------------------------------------------------------

# hashes of the output of direction.py before the T-9 additions (same inputs as below)
BASE_VALIDATE = {
    "2026-11-14_p1-kikigokochi": "d46739a0e031d94e",  # P3 8.1: + kind-B unmeasured_quantity P-10, P-02, P-02:vs_lead, P-22 (was ae7269da2c2a3306)
    "2026-11-14_p2-ultra-sub-bass": "23d3baa391eb4a7a",  # FR-1: the 4 unsupported warnings on trk_* observations are gone (was e3d534ab96d12f97); P3 8.1: + kind-B unmeasured_quantity P-02:vs_lead, P-10, P-22, P-11 (was edc8fd383fc5820a)
    "2026-11-14_p3-spatial-panning": "a3996e0ea6fb6846",  # P3 8.1: + kind-B unmeasured_quantity P-02:vs_lead, P-10 (was df6057e37a5a1b07)
}
BASE_SYNTH_VALIDATE = "f0e997b2ca13d4f9"
BASE_PROPOSAL = "b9fc8176b26b7c51"
BASE_OUTCOME_FILE = "72f11127d364c785"
BASE_MINIMAL = "9dfa59a0a7e2b4d8"  # P3 8.1: + WARN_P03_B in the validate part (was 1e841cbbc7876916)
# P3 8.1 (FBREVIEW): a ledger quantity in a claim / expect / safeguard always gets one unmeasured_quantity
# warning; the minimal block's claim on P-03 gets kind B (its project fixture has no evaluation terms)
WARN_P03_B = {"where": "quantities.P-03", "code": "unmeasured_quantity",
              "message": "P-03 は台帳指標（該当 1 件）。direction check は結果の変種の評価項だけを読み、指揮書の結果を"
                         "測り直さない。標準の流れ（master plan --apply）では評価項が残らず not_measured になる。"
                         "obs:<id> の観察量は check が床と結果の両方を測る"}


@pytest.mark.parametrize("folder", sorted(EXISTING))
def test_existing_directions_validate_with_unchanged_ids(folder):
    doc = D.parse_document(SONG_DIR / folder / "direction.md")
    assert doc["id"] == EXISTING[folder]
    res = D.validate(doc)
    assert res["ok"], res["errors"]
    assert _h(res) == BASE_VALIDATE[folder]


def test_document_without_added_fields_gives_the_same_output(tmp_path):
    proj = _project(tmp_path / "p", low_amp=0.2)
    doc = D.parse_document(_write_doc(tmp_path / "d", _block()))
    v = D.validate(doc, proj)
    assert v["ok"], v["errors"]
    assert _h(v) == BASE_SYNTH_VALIDATE
    prop, record, notes = D.build_proposal(D._Project(proj), doc)
    assert _h({"prop": prop, "record": record, "notes": notes}) == BASE_PROPOSAL
    out, raw = _check_out(tmp_path, _block(), "plain")
    assert "reference_distance" not in out
    assert _outcome_hash(raw) == BASE_OUTCOME_FILE


def test_minimal_direction_needs_no_stage(tmp_path):
    """U-17 / §8.5 T-14: no added field, no analysis memo, empty sources -> validate, apply, check."""
    proj = _project(tmp_path / "p", low_amp=0.2)
    path = _write_doc(tmp_path / "d", _minimal_block())
    assert not (path.parent / "analysis.md").exists()
    doc = D.parse_document(path)
    v = D.validate(doc, proj)
    assert v["ok"] and v["warnings"] == [WARN_P03_B], v
    assert v["tiers"] == {"m01": "E2"}
    prop, record, _ = D.build_proposal(D._Project(proj), doc)
    assert prop["changes"]["tracks"]["trk_vocals"]["gain_db"] == 1.0
    assert _h({"validate": v, "prop": prop, "record": record}) == BASE_MINIMAL
    # apply all the way when there is no mix move (no planner run): only the record is written
    nomove = _minimal_block()
    nomove["moves"] = []
    p2 = _write_doc(tmp_path / "d2", nomove)
    a = D.apply(proj, p2)
    assert a["applied"] and "mix_proposal" not in a
    out, _ = _check_out(tmp_path, _minimal_block(), "min")
    assert out["status"] == "checked" and "reference_distance" not in out


# ---------------------------------------------------------------------------
# the added fields
# ---------------------------------------------------------------------------

def test_added_fields_are_accepted_and_change_nothing_else(tmp_path):
    proj = _project(tmp_path / "p", low_amp=0.2)
    plain = D.validate(D.parse_document(_write_doc(tmp_path / "a", _block())), proj)
    b = _with_refs(_block())
    res = D.validate(D.parse_document(_write_doc(tmp_path / "b", b)), proj)
    assert res["ok"], res["errors"]
    assert res["warnings"] == plain["warnings"]
    assert res["tiers"]["m04"] == "E2"
    assert {k: v for k, v in res.items() if k != "id"} == {k: v for k, v in plain.items() if k != "id"}


def test_empty_references_and_cards_are_never_reported(tmp_path):
    """U-17: sources.cards / sources.references are a record of what was used; empty is not a shortfall."""
    proj = _project(tmp_path / "p", low_amp=0.2)
    for i, src in enumerate(({}, {"cards": [], "references": []}, {"references": []})):
        b = _minimal_block()
        b["sources"] = src
        b["request"]["like"] = []
        res = D.validate(D.parse_document(_write_doc(tmp_path / f"d{i}", b)), proj)
        assert res["ok"] and res["warnings"] == [WARN_P03_B], res


@pytest.mark.parametrize("mutate,where,code", [
    (lambda b: b["request"].__setitem__("like", "work_x"), "request.like", "bad_value"),
    (lambda b: b["request"].__setitem__("like", ["song_x"]), "request.like[0]", "bad_ref"),
    (lambda b: b["request"].__setitem__("like", ["work_Bad Slug"]), "request.like[0]", "bad_ref"),
    (lambda b: b["sources"].__setitem__("references", {"work": "work_x"}), "sources.references", "bad_value"),
    (lambda b: b["sources"]["references"][0].__setitem__("work", "eng_x"), "sources.references[0].work", "bad_ref"),
    (lambda b: b["sources"]["references"][0].__setitem__("study_sha256", "XYZ"),
     "sources.references[0].study_sha256", "bad_value"),
    (lambda b: b["sources"]["references"][0].__setitem__("path", "a/b"), "sources.references[0]", "bad_value"),
    (lambda b: b["observations"][0].__setitem__("ref_value", "loud"), "observations.o1.ref_value", "bad_value"),
    (lambda b: b["observations"][0].__setitem__("ref_value", True), "observations.o1.ref_value", "bad_value"),
    (lambda b: b["moves"][3].__setitem__("origin", "memory"), "moves.m04", "bad_value"),
    (lambda b: b["moves"][3].__setitem__("basis", "ref:eng_x §1"), "moves.m04.basis", "bad_ref"),
])
def test_added_field_format_errors(tmp_path, mutate, where, code):
    b = _with_refs(_block())
    mutate(b)
    res = D.validate(D.parse_document(_write_doc(tmp_path, b)))
    assert not res["ok"]
    assert {"where": where, "code": code} in [{"where": e["where"], "code": e["code"]} for e in res["errors"]], res


@pytest.mark.parametrize("basis", [
    "ref:work_x、§4",
    "（ref:work_x）の読み",
    "ref:work_x§4",
    "ref:work_x §4",
])
def test_reference_basis_may_be_followed_by_any_delimiter(tmp_path, basis):
    """GATE_R1 R1-B: only the slug after 'ref:' is the id; Japanese punctuation may follow it."""
    b = _with_refs(_block())
    b["moves"][3]["basis"] = basis
    res = D.validate(D.parse_document(_write_doc(tmp_path, b)))
    assert not [e for e in res["errors"] if e["where"] == "moves.m04.basis"], res["errors"]


@pytest.mark.parametrize("basis", ["ref:eng_x", "ref:eng_x、§1", "ref:Work_X §1", "ref:KT-0016",
                                   "ref:work_", "ref:work_x/ref:eng_y"])
def test_reference_basis_must_name_a_work_card(tmp_path, basis):
    b = _with_refs(_block())
    b["moves"][3]["basis"] = basis
    res = D.validate(D.parse_document(_write_doc(tmp_path, b)))
    assert not res["ok"]
    assert {"where": "moves.m04.basis", "code": "bad_ref"} in \
        [{"where": e["where"], "code": e["code"]} for e in res["errors"]], res


@pytest.mark.parametrize("basis", ["ref: work_x §4", "R-06 (cf. ref: none)", "ref:", "ref:、§1"])
def test_reference_basis_without_a_slug_is_not_checked(tmp_path, basis):
    """GATE_R2 N-a: only a 'ref:' directly followed by a slug is checked; prose like 'ref: ...' is free."""
    b = _with_refs(_block())
    b["moves"][3]["basis"] = basis
    res = D.validate(D.parse_document(_write_doc(tmp_path, b)))
    assert not [e for e in res["errors"] if e["where"] == "moves.m04.basis"], res["errors"]


@pytest.mark.parametrize("basis", ["の読みref:work_x §4", "参照ref:work_x、§4"])
def test_reference_basis_directly_after_japanese_text_passes(tmp_path, basis):
    """W9b: a 'ref:' glued to Japanese text is still found, and a work id passes."""
    b = _with_refs(_block())
    b["moves"][3]["basis"] = basis
    res = D.validate(D.parse_document(_write_doc(tmp_path, b)))
    assert not [e for e in res["errors"] if e["where"] == "moves.m04.basis"], res["errors"]


@pytest.mark.parametrize("basis", ["の読みref:eng_x", "参照ref:eng_x、§1"])
def test_reference_basis_directly_after_japanese_text_is_checked(tmp_path, basis):
    """W9b: Python's \\b would treat the Japanese letter as a word character and skip this 'ref:'."""
    b = _with_refs(_block())
    b["moves"][3]["basis"] = basis
    res = D.validate(D.parse_document(_write_doc(tmp_path, b)))
    assert not res["ok"]
    assert {"where": "moves.m04.basis", "code": "bad_ref"} in \
        [{"where": e["where"], "code": e["code"]} for e in res["errors"]], res


@pytest.mark.parametrize("basis", ["xref:eng_x §1", "see_ref:eng_x", "の読みxref:eng_x"])
def test_reference_basis_after_ascii_word_is_out_of_scope(tmp_path, basis):
    """W9b: 'ref:' preceded by an ASCII letter, digit or underscore is not a reference basis."""
    b = _with_refs(_block())
    b["moves"][3]["basis"] = basis
    res = D.validate(D.parse_document(_write_doc(tmp_path, b)))
    assert not [e for e in res["errors"] if e["where"] == "moves.m04.basis"], res["errors"]


def test_null_ref_value_and_refsheet_are_allowed(tmp_path):
    b = _with_refs(_block())
    b["observations"][0]["ref_value"] = None
    b["sources"]["references"][0]["refsheet_sha256"] = None
    res = D.validate(D.parse_document(_write_doc(tmp_path, b)))
    assert res["ok"], res["errors"]


def test_reference_origin_is_never_e1(tmp_path):
    b = _with_refs(_block())
    # a move that would be E1 as a catalog move (cited rule R-06)
    b["moves"][0]["origin"] = "reference"
    b["moves"][0]["basis"] = "R-06 / ref:work_sample-song §3"
    res = D.validate(D.parse_document(_write_doc(tmp_path / "r", b)))
    assert res["ok"], res["errors"]
    assert res["tiers"]["m01"] == "E2"
    # the same move as catalog is E1, so only the origin made the difference
    b["moves"][0]["origin"] = "catalog"
    b["moves"][0]["basis"] = "R-06"
    assert D.validate(D.parse_document(_write_doc(tmp_path / "c", b)))["tiers"]["m01"] == "E1"


def test_theory_card_basis_does_not_make_e1(tmp_path):
    b = _block()
    b["moves"][0]["basis"] = "KT-0003 (theory card)"
    assert D.validate(D.parse_document(_write_doc(tmp_path / "t", b)))["tiers"]["m01"] == "E2"
    b["moves"][0]["basis"] = "R-06 / KT-0003"
    # the catalog range check alone decides E1; the theory card neither adds nor removes it
    assert D.validate(D.parse_document(_write_doc(tmp_path / "u", b)))["tiers"]["m01"] == "E1"


def test_invariant_area_is_not_bypassed_through_the_added_fields(tmp_path):
    b = _with_refs(_block())
    b["moves"].append({"id": "m06", "aim": "a1", "stage": "master", "target": "master", "op": "chain_add",
                       "processor": "limiter", "params": {"ceiling_dbtp": -0.1},
                       "basis": "ref:work_sample-song §1 (the reference is limited harder)", "origin": "reference"})
    b["moves"].append({"id": "m07", "aim": "a1", "target": "trk_bass", "op": "chain_add", "processor": "eq",
                       "params": {"shape": "low_shelf", "freq_hz": 80, "gain_db": [2, 40], "bw_oct": 1.0},
                       "basis": "ref:work_sample-song §2", "origin": "reference"})
    b["moves"].append({"id": "m08", "aim": "a1", "op": "master_target", "params": {"target_lufs": -6.0},
                       "basis": "ref:work_sample-song §1 (the reference is at -6 LUFS)", "origin": "reference"})
    b["sources"]["references"][0]["ceiling_dbtp"] = 0.0
    b["observations"][0]["true_peak"] = 0.0
    res = D.validate(D.parse_document(_write_doc(tmp_path, b)))
    assert not res["ok"]
    errs = {(e["where"], e["code"]) for e in res["errors"]}
    assert ("moves.m06", "invariant") in errs                        # master chain / limiter
    assert ("moves[5].params.ceiling_dbtp", "invariant") in errs
    assert ("moves.m07", "param_range") in errs                      # outside the declared range
    assert ("moves.m08", "invariant") in errs                        # target_lufs outside the window
    assert ("sources.references[0].ceiling_dbtp", "invariant") in errs
    assert ("observations[0].true_peak", "invariant") in errs


def test_reference_distance_is_reported_but_never_judged(tmp_path):
    plain, _ = _check_out(tmp_path, _block(), "plain")
    out, raw = _check_out(tmp_path, _with_refs(_block()), "ref")
    rd = out["reference_distance"]
    assert set(rd["by_observation"]) == {"o1", "o2", "o3"}
    o1 = rd["by_observation"]["o1"]
    f, r = out["observations"]["o1"]["floor"]["value"], out["observations"]["o1"]["result"]["value"]
    assert o1["floor"] == pytest.approx(abs(f + 30.0), abs=1e-4)
    assert o1["result"] == pytest.approx(abs(r + 30.0), abs=1e-4)
    assert o1["change"] == pytest.approx(o1["result"] - o1["floor"], abs=2e-4)
    # every verdict and the summary are the same as without ref_value
    for k in ("claims", "move_checks", "summary", "observations", "loudness", "convergence"):
        assert out[k] == plain[k], k
    assert json.loads(raw)["reference_distance"] == rd
    # a far or a near ref_value changes nothing in the verdicts
    for tag, val in (("far", 1000.0), ("near", None)):
        b = _with_refs(_block())
        for o in b["observations"]:
            o["ref_value"] = val if val is not None else out["observations"][o["id"]]["result"]["value"]
        other, _ = _check_out(tmp_path, b, tag)
        assert other["claims"] == plain["claims"] and other["summary"] == plain["summary"]
        assert other["move_checks"] == plain["move_checks"]


def test_observation_values_do_not_read_ref_value():
    x = np.stack([_tone(50, 0.3) + _tone(1000, 0.1)] * 2, axis=1)
    o = {"id": "o1", "primitive": "band_energy", "band_hz": [20, 80]}
    assert Q.observe(x, SR, o) == Q.observe(x, SR, {**o, "ref_value": -3.0})


class _NoRefDict(dict):
    def __getitem__(self, k):
        assert k != "ref_value", "calibrate read ref_value"
        return super().__getitem__(k)

    def get(self, k, default=None):
        assert k != "ref_value", "calibrate read ref_value"
        return super().get(k, default)


def test_calibrate_does_not_read_ref_value(tmp_path, monkeypatch):
    import inspect
    src = inspect.getsource(C)
    assert "ref_value" not in src and "reference_distance" not in src
    proj = _project(tmp_path / "p", low_amp=0.2)

    class FakePredictor:
        """Deterministic mix-stage prediction from the selection only (no rendering)."""

        def __init__(self, root, doc, progress):
            self.renders = 0

        def deltas(self, sel, label):
            self.renders += 1
            g, w = sel.get("m01.gain_db", 0.0), sel.get("m04.width", 1.0)
            return {"o1": round(0.3 * g, 4), "o2": round((1.0 - w) * 0.4, 4), "o3": 0.0}

    monkeypatch.setattr(C, "_Predictor", FakePredictor)

    def run(block, tag):
        doc = D.parse_document(_write_doc(tmp_path / tag, block))
        doc["block"]["observations"] = [_NoRefDict(o) for o in doc["block"]["observations"]]
        return C.calibrate(proj, doc, progress=lambda s: None)

    b = _block()
    b["moves"][0]["select"] = {"gain_db": "min"}       # claim c1 unmet at select -> candidates are evaluated
    plain = run(b, "plain")
    with_ref = run(_with_refs(b), "ref")
    assert len(plain["evaluations"]) > 1
    assert plain == with_ref


# ---------------------------------------------------------------------------
# song dossier v2
# ---------------------------------------------------------------------------

def _card(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _theory(cid: str, title: str, status: str = "active") -> str:
    return (f"---\nid: {cid}\nkind: theory\ntitle: {title}\ncreated: 2026-11-15\nstatus: {status}\n"
            "visibility: public\nevidence: practice\ndomain: practice\ntradition: field\nparaphrase: true\n"
            "sources_note: \"own words\"\n---\n\n## 要点\n\nTHEORY-BODY-MUST-NOT-APPEAR\n")


def _lesson(i: int) -> str:
    return (f"---\nid: KL-{i:04d}\nkind: lesson\ntitle: lesson {i}\ncreated: 2026-11-14\nstatus: active\n"
            "visibility: public\nevidence: practice\n---\n\n## 主張\n\nclaim text\n")


def _work(slug: str, title: str) -> str:
    return (f"---\nid: work_{slug}\nkind: work\ntitle: {title}\ncreated: 2026-11-15\nstatus: draft\n"
            "visibility: private\nrights: third_party\ncredits_source: \"user\"\nmaterials: []\n---\n\n"
            "## 測定の要点\n\nWORK-BODY-MUST-NOT-APPEAR -14.2 LUFS\n")


REFSTUDY = b"# refstudy\n\n| x | 1 |\n"


def _dossier_kb(tmp_path: Path) -> tuple[Path, Path]:
    kbr = tmp_path / "kb"
    for i in range(1, 11):
        _card(kbr / "lessons" / f"KL-{i:04d}.md", _lesson(i))
    _card(kbr / "theory" / "KT-0002.md", _theory("KT-0002", "倍音と音色"))
    _card(kbr / "theory" / "KT-0001.md", _theory("KT-0001", "音程の基礎"))
    _card(kbr / "theory" / "KT-0003.md", _theory("KT-0003", "退役した理論", status="stale"))
    _card(kbr / "references" / "works" / "own-song" / "work.md", _work("own-song", "自前の曲"))
    priv = tmp_path / "private_kb"
    w = priv / "references" / "works" / "other-song"
    _card(w / "work.md", _work("other-song", "他者の曲"))
    (w / "refstudy.md").write_bytes(REFSTUDY)
    return kbr, priv


def _section(md: str, head: str) -> str:
    start = md.index(head)
    ends = [e for e in (md.find("\n### ", start + len(head)), md.find("\n## ", start + len(head))) if e != -1]
    return md[start:min(ends) if ends else len(md)]


def test_dossier_v2_headings_version_and_theory_shelf(tmp_path):
    proj = _project(tmp_path / "p", low_amp=0.2)
    kbr, priv = _dossier_kb(tmp_path)
    res = DS.build_dossier(proj, kb_root=kbr, section_audio=False, ref_kb_root=priv)
    md = res["markdown"]
    assert DS.DOSSIER_VERSION == 2 and res["version"] == 2
    assert "mankomix direction dossier v2" in md
    assert len(DS.HEADINGS) == 12 and res["headings"] == list(DS.HEADINGS)
    assert [ln[3:] for ln in md.splitlines() if ln.startswith("## ")] == list(DS.HEADINGS)
    s10 = md[md.index("## 10. "):md.index("## 11. ")]
    assert s10.index("### 10.1 経験") < s10.index("### 10.2 理論の棚") < s10.index("### 10.3 リファレンス")
    # 10.1 keeps its cap of 8; the shelf is a separate frame with every active theory card
    s101 = _section(md, "### 10.1 経験")
    assert sum(1 for ln in s101.splitlines() if ln.startswith("- **KL-")) == DS.MAX_KB_CARDS
    assert "KT-" not in s101
    shelf = [ln for ln in _section(md, "### 10.2 理論の棚").splitlines() if ln.startswith("- ")]
    assert shelf == ["- KT-0001 音程の基礎", "- KT-0002 倍音と音色"]
    assert "THEORY-BODY-MUST-NOT-APPEAR" not in md and "KT-0003" not in md
    assert [ln for ln in _section(md, "### 10.3 リファレンス").splitlines() if ln.startswith("- ")] == ["- 指定なし"]
    # deterministic
    assert DS.build_dossier(proj, kb_root=kbr, section_audio=False, ref_kb_root=priv)["markdown"] == md


def test_dossier_v2_without_theory_cards(tmp_path):
    proj = _project(tmp_path / "p", low_amp=0.2)
    kbr = tmp_path / "kb"
    _card(kbr / "lessons" / "KL-0001.md", _lesson(1))
    md = DS.build_dossier(proj, kb_root=kbr, section_audio=False, ref_kb_root=tmp_path / "none")["markdown"]
    assert [ln for ln in _section(md, "### 10.2 理論の棚").splitlines() if ln.startswith("- ")] == ["- 理論カードなし"]


def test_dossier_v2_references(tmp_path):
    proj = _project(tmp_path / "p", low_amp=0.2)
    kbr, priv = _dossier_kb(tmp_path)
    res = DS.build_dossier(proj, kb_root=kbr, section_audio=False, ref_kb_root=priv,
                           refs=["work_other-song", "work_own-song", "work_missing", "work_other-song"])
    md = res["markdown"]
    assert res["references"] == ["work_other-song", "work_own-song", "work_missing"]
    lines = [ln for ln in _section(md, "### 10.3 リファレンス").splitlines() if ln.startswith("- ")]
    sha = hashlib.sha256(REFSTUDY).hexdigest()[:16]
    assert lines[0] == f"- work_other-song 他者の曲（非公開 kb）: refstudy `{sha}`"
    assert lines[1].startswith("- work_own-song 自前の曲（kb）: refstudy なし")
    assert lines[2].startswith("- work_missing: kb にカードが無い")
    assert len(lines) == 3
    assert "WORK-BODY-MUST-NOT-APPEAR" not in md and "-14.2" not in md
    assert str(tmp_path) not in md and tmp_path.as_posix() not in md
    with pytest.raises(ValueError):
        DS.build_dossier(proj, kb_root=kbr, section_audio=False, refs=["eng_x"])


def test_dossier_cli_ref_option():
    from mankomix.cli import main as M
    a = M.build_parser().parse_args(["direction", "dossier", "--ref", "work_a", "--ref", "work_b",
                                     "--ref-kb", "x"])
    assert a.refs == ["work_a", "work_b"] and a.ref_kb == "x"
    a = M.build_parser().parse_args(["direction", "dossier"])
    assert a.refs is None and a.ref_kb is None
