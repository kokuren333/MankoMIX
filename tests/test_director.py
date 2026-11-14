"""Direction layer (director/): kb front matter / index / lint, direction ids, validate, observation query.

Fast and self-contained: no sample set, no rendering. The end-to-end flow (apply -> master plan ->
render -> check) is exercised on the official sample in the implementation ledger, not here.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from mankomix.director import direction as D
from mankomix.director import kb
from mankomix.director import query as Q


# ---------------------------------------------------------------------------
# kb
# ---------------------------------------------------------------------------

def _card(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


GOOD_LESSON = """---
id: KL-0001
kind: lesson
title: a lesson
created: 2026-11-14
status: active
visibility: public
evidence: measured
backing: [songs/s/outcome.md]
applies_to: { genre: [hiphop], profile: [club] }
---

## 主張

Something measured.
"""

OUTCOME = """---
id: out_1
kind: outcome
title: an outcome
created: 2026-11-14
status: active
visibility: public
---

## 主張

The numbers.
"""


def test_front_matter_parses_flow_values():
    meta, body = kb.parse_front_matter(GOOD_LESSON)
    assert meta["id"] == "KL-0001"
    assert meta["applies_to"] == {"genre": ["hiphop"], "profile": ["club"]}
    assert meta["backing"] == ["songs/s/outcome.md"]
    assert "Something measured." in body


def test_kb_index_and_lint_pass(tmp_path):
    _card(tmp_path / "lessons" / "KL-0001.md", GOOD_LESSON)
    _card(tmp_path / "songs" / "s" / "outcome.md", OUTCOME)
    res = kb.write_index(tmp_path)
    assert res["entries"] == 2 and res["changed"]
    assert kb.write_index(tmp_path)["changed"] is False
    out = kb.lint(tmp_path)
    assert out["ok"], out["errors"]
    idx = (tmp_path / "INDEX.md").read_text(encoding="utf-8")
    assert "KL-0001" in idx and "genre=hiphop; profile=club" in idx


def test_kb_lint_rejects_forbidden_content(tmp_path):
    bad = GOOD_LESSON.replace("Something measured.", "See C:\\Users\\me\\mix.wav and [x](missing.md)")
    bad = bad.replace("backing: [songs/s/outcome.md]", "backing: [songs/none.md]")
    _card(tmp_path / "lessons" / "KL-0001.md", bad)
    _card(tmp_path / "moves" / "bad.md", OUTCOME.replace("kind: outcome", "kind: move").replace("id: out_1", "id: X-1"))
    kb.write_index(tmp_path)
    codes = {e["code"] for e in kb.lint(tmp_path)["errors"]}
    assert {"absolute_path", "audio_reference", "broken_link", "bad_backing", "bad_id", "missing_field"} <= codes


def test_kb_lint_detects_stale_index(tmp_path):
    _card(tmp_path / "songs" / "s" / "outcome.md", OUTCOME)
    kb.write_index(tmp_path)
    _card(tmp_path / "songs" / "s" / "outcome.md", OUTCOME.replace("an outcome", "renamed"))
    assert any(e["code"] == "index_stale" for e in kb.lint(tmp_path)["errors"])


# ---------------------------------------------------------------------------
# direction documents
# ---------------------------------------------------------------------------

def _block(**over) -> dict:
    b = {
        "schema_version": 1, "kind": "direction", "song": "s",
        "request": {"pattern": "p1", "utterance": "test"},
        "sources": {"analysis": None, "dossier_sha256": "0", "cards": []},
        "aims": [{"id": "a1", "phrase": "x", "text": "x", "confidence": "high", "assumption": "-"}],
        "variants": [{"id": "var_x", "profile": "streaming_universal", "delivery": ["hires_native"],
                      "target_lufs": None, "reason": "default"}],
        "moves": [{"id": "m01", "aim": "a1", "stage": "mix", "target": "trk_bass", "section": None,
                   "op": "chain_add", "processor": "eq",
                   "params": {"shape": "low_shelf", "freq_hz": 80, "gain_db": [1.5, 3.0], "bw_oct": 1.0},
                   "select": {"gain_db": "max"}, "basis": "R-06", "origin": "catalog",
                   "expect": [{"quantity": "obs:o1", "direction": "up", "min_delta": 1.0}]}],
        "claims": [{"id": "c1", "quantity": "obs:o1", "vs": "floor", "direction": "up", "min_delta": 1.0,
                    "primary": True}],
        "observations": [{"id": "o1", "primitive": "band_energy", "target": "master", "band_hz": [20, 60],
                          "section": "all", "level_match": True}],
        "listen_for": [],
    }
    b.update(over)
    return b


def _doc(tmp_path: Path, block: dict, fm_id: str | None = None) -> Path:
    did = D.direction_id(block)
    p = tmp_path / "direction.md"
    p.write_text(f"---\nid: {fm_id or did}\nkind: direction\ntitle: t\ncreated: 2026-11-14\nstatus: draft\n"
                 f"visibility: private\n---\n\n# t\n\n```json direction\n{json.dumps(block, ensure_ascii=False)}\n```\n",
                 encoding="utf-8")
    return p


def test_direction_id_is_canonical(tmp_path):
    b = _block()
    p = _doc(tmp_path, b)
    doc = D.parse_document(p)
    assert doc["id"] == D.direction_id(json.loads(json.dumps(b, indent=3)))
    assert doc["id"].startswith("dir_") and len(doc["id"]) == 16


def test_analysis_id_excludes_front_matter():
    a = b"---\nid: ana_1\n---\nbody\n"
    b = b"---\nid: ana_2\nextra: 1\n---\nbody\n"
    assert D.analysis_id(a) == D.analysis_id(b)


def test_validate_accepts_a_good_direction(tmp_path):
    doc = D.parse_document(_doc(tmp_path, _block()))
    res = D.validate(doc)
    assert res["ok"], res["errors"]
    assert res["tiers"]["m01"] in ("E1", "E2")


def test_validate_rejects_the_invariant_area(tmp_path):
    b = _block()
    b["moves"].append({"id": "m02", "aim": "a1", "stage": "master", "target": "master", "op": "chain_add",
                       "processor": "limiter", "params": {"ceiling_dbtp": -0.1}, "basis": "x", "origin": "new"})
    b["moves"].append({"id": "m03", "aim": "a1", "op": "pan", "target": "trk_x", "section": "sec2",
                       "params": {"position": 0.3}, "basis": "x", "origin": "new"})
    b["moves"][0]["params"]["gain_db"] = [2, 40]
    b["variants"][0]["target_lufs"] = -9.0
    res = D.validate(D.parse_document(_doc(tmp_path, b, fm_id="dir_wrong")))
    codes = [e["code"] for e in res["errors"]]
    assert not res["ok"]
    for c in ("id_mismatch", "invariant", "section_scope", "param_range"):
        assert c in codes, (c, codes)


def test_validate_needs_primary_claims_and_known_quantities(tmp_path):
    b = _block(claims=[{"id": "c1", "quantity": "S-08", "vs": "floor", "direction": "down", "min_delta": 0.1}])
    codes = [e["code"] for e in D.validate(D.parse_document(_doc(tmp_path, b)))["errors"]]
    assert "primary_count" in codes and "bad_quantity" in codes


def test_resolve_params_selects_within_range():
    m = {"id": "m", "select": {"a": "min", "b": "sweep:S-08_margin"}}
    out, notes = D.resolve_params(m, {"a": [1.0, 3.0], "b": [2.0, 4.0], "c": [0.0, 1.0], "d": 5})
    assert out == {"a": 1.0, "b": 3.0, "c": 0.5, "d": 5}
    assert notes and "sweep" in notes[0]


def test_section_automation_ramps():
    pts = D._automation(48000, [(1.0, 2.0, -2.0)], None)
    assert pts[0] == [48000 - 960, 0.0] and pts[1] == [48000, -2.0] and pts[-1] == [96000 + 960, 0.0]
    with pytest.raises(D.DirectionError):
        D._automation(48000, [(1.0, 2.0, -2.0), (2.0, 3.0, 1.0)], None)


# ---------------------------------------------------------------------------
# observation query
# ---------------------------------------------------------------------------

SR = 48000


def _tone(freq: float, amp: float = 0.5, secs: float = 2.0) -> np.ndarray:
    t = np.arange(int(SR * secs)) / SR
    return amp * np.sin(2 * np.pi * freq * t)


def test_query_band_ratio_and_energy():
    x = np.stack([_tone(50) + _tone(1000, 0.05)] * 2, axis=1)
    r = Q.observe(x, SR, {"primitive": "band_ratio", "band_hz": [30, 80], "ref_band_hz": [500, 2000]})
    assert r["status"] == "ok" and r["value"] == pytest.approx(20.0, abs=0.5)
    e0 = Q.observe(x, SR, {"primitive": "band_energy", "band_hz": [30, 80]})["value"]
    e6 = Q.observe(x, SR, {"primitive": "band_energy", "band_hz": [30, 80]}, gain_db=6.0)["value"]
    assert e6 - e0 == pytest.approx(6.0, abs=0.01)


def test_query_stereo_measures():
    mono = np.stack([_tone(440)] * 2, axis=1)
    assert Q.observe(mono, SR, {"primitive": "correlation"})["value"] == pytest.approx(1.0, abs=1e-6)
    assert Q.observe(mono, SR, {"primitive": "side_ratio"})["value"] < -150
    anti = np.stack([_tone(440), -_tone(440)], axis=1)
    assert Q.observe(anti, SR, {"primitive": "correlation"})["value"] == pytest.approx(-1.0, abs=1e-6)
    crest = Q.observe(mono, SR, {"primitive": "crest"})["value"]
    assert crest == pytest.approx(3.01, abs=0.05)


def test_query_sections_and_unsupported_targets():
    x = np.stack([_tone(440, secs=4.0)] * 2, axis=1)
    secs = [{"id": "sec1", "start_s": 0.0, "end_s": 1.0}, {"id": "sec2", "start_s": 1.0, "end_s": 4.0}]
    r = Q.observe(x, SR, {"primitive": "loudness", "stat": "integrated", "section": "sec2"}, sections=secs)
    assert r["range_s"] == [1.0, 4.0]
    assert Q.observe(x, SR, {"primitive": "crest", "target": "trk_bass"})["status"] == "unsupported"
    with pytest.raises(Q.QueryError):
        Q.observe(x, SR, {"primitive": "crest", "section": "nope"}, sections=secs)
