"""The warning unmeasured_quantity (FBREVIEW FR-7, gate G-1, as amended by P3 / requirements 8.1).

`direction validate` warns once per ledger quantity (P-nn / P-nn:<qualifier>) of a claim, an
expectation or a safeguard, with or without --project. Kind A (the original text): the project's
floor variant has evaluation terms but none numeric (value or penalty) for the quantity. Kind B:
every other case (no --project, an unevaluated project, a numeric floor term) -- direction check
reads only the result variant's terms. Never for obs:<id>; a warning only: `ok` and the exit code
do not change.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from mankomix.director import direction as D
from tests import test_direction_update as T


@pytest.fixture(autouse=True)
def _local_home(tmp_path, monkeypatch):
    monkeypatch.setenv("MANKOMIX_HOME", str(tmp_path / "home"))


TERMS = [{"key": "P-01", "value": -9.5, "penalty": 0.0},
         {"key": "P-02", "value": None, "penalty": None},       # a term without numbers
         {"key": "P-03", "value": None, "penalty": 0.25},        # penalty only: measured
         {"key": "P-11", "value": 2.0, "penalty": None},
         {"key": "P-02:vs_lead", "value": 1.5, "penalty": 0.1}]


def _project(root: Path, terms: list | None) -> Path:
    T._project(root, low_amp=0.2)
    data = json.loads((root / "project.json").read_text(encoding="utf-8"))
    if terms is not None:
        data["variants"][0]["evaluation"] = {"terms": copy.deepcopy(terms)}
    (root / "project.json").write_text(json.dumps(data), encoding="utf-8")
    return root


def _blk(claims: list[dict], expect: list[dict] | None = None, safeguard: list[dict] | None = None) -> dict:
    b = T._minimal_block()
    b["claims"] = claims
    b["observations"] = [{"id": "o1", "primitive": "crest", "target": "master"}]
    m = b["moves"][0]
    if expect is not None:
        m["expect"] = expect
    if safeguard is not None:
        m["safeguard"] = safeguard
    return b


def _validate(tmp_path: Path, block: dict, project: Path | None, tag: str) -> dict:
    return D.validate(D.parse_document(T._write_doc(tmp_path / tag, block)), project)


def _unmeasured(res: dict) -> list[dict]:
    return [w for w in res["warnings"] if w["code"] == "unmeasured_quantity"]


def _q(qty: str, **kw) -> dict:
    return {"quantity": qty, "direction": "not_worse", "tolerance": 0.5, **kw}


BLOCK = _blk([{"id": "c1", "quantity": "P-02", "direction": "down", "min_delta": 0.5, "primary": True},
              {"id": "c2", **_q("P-01")}, {"id": "c3", **_q("obs:o1")}],
             expect=[_q("P-07")],
             safeguard=[_q("P-02"), _q("P-03"), _q("P-02:vs_lead"), _q("P-11:air"), _q("P-07:x"), _q("P-02")])


A_HEAD = "床の変種の評価項に "
B_MID = " は台帳指標（該当 "
ALL7 = ["quantities.P-02", "quantities.P-01", "quantities.P-07", "quantities.P-03", "quantities.P-02:vs_lead",
        "quantities.P-11:air", "quantities.P-07:x"]
COUNTS7 = {"P-02": 3, "P-01": 1, "P-07": 1, "P-03": 1, "P-02:vs_lead": 1, "P-11:air": 1, "P-07:x": 1}


def _kind_a(w: list[dict]) -> list[dict]:
    return [x for x in w if x["message"].startswith(A_HEAD)]


def _kind_b(w: list[dict]) -> list[dict]:
    return [x for x in w if B_MID in x["message"]]


def _a_text(qty: str, n: int) -> str:
    return (f"床の変種の評価項に {qty} の数値（value／penalty）が無い（該当 {n} 件）。direction check は "
            "not_measured を返す。obs:<id>（masking／wet_ratio／trk 対象の観察量）で測れる")


def _b_text(qty: str, n: int) -> str:
    return (f"{qty} は台帳指標（該当 {n} 件）。direction check は結果の変種の評価項だけを読み、指揮書の結果を"
            "測り直さない。標準の流れ（master plan --apply）では評価項が残らず not_measured になる。"
            "obs:<id> の観察量は check が床と結果の両方を測る")


def test_one_warning_per_ledger_quantity_with_its_count(tmp_path):
    proj = _project(tmp_path / "p", TERMS)
    res = _validate(tmp_path, BLOCK, proj, "d")
    assert res["ok"], res["errors"]
    w = _unmeasured(res)
    # first appearance order over claims, then each move's expect and safeguard; P-02 three times in all
    assert [x["where"] for x in w] == ALL7
    a, b = _kind_a(w), _kind_b(w)
    assert [x["where"] for x in a] == ["quantities.P-02", "quantities.P-07", "quantities.P-07:x"]
    assert [x["where"] for x in b] == ["quantities.P-01", "quantities.P-03", "quantities.P-02:vs_lead",
                                       "quantities.P-11:air"]
    assert "（該当 3 件）" in a[0]["message"] and "（該当 1 件）" in a[1]["message"]
    for x in a:
        assert "direction check は not_measured を返す" in x["message"]
        assert "obs:<id>（masking／wet_ratio／trk 対象の観察量）で測れる" in x["message"]
    for x in b:
        assert "direction check は結果の変種の評価項だけを読み" in x["message"]
        assert "標準の流れ（master plan --apply）では評価項が残らず not_measured になる" in x["message"]
        assert "obs:<id> の観察量は check が床と結果の両方を測る" in x["message"]
    for x in w:
        qty = x["where"].split(".", 1)[1]
        assert x == {"where": x["where"], "code": "unmeasured_quantity",
                     "message": (_a_text if x in a else _b_text)(qty, COUNTS7[qty])}
    # the warnings come after every existing warning
    assert res["warnings"][-len(w):] == w


def test_measured_quantities_get_kind_b_and_obs_gets_none(tmp_path):
    proj = _project(tmp_path / "p", TERMS)
    blk = _blk([{"id": "c1", **_q("P-01"), "primary": True}, {"id": "c2", **_q("obs:o1")}],
               safeguard=[_q("P-03"), _q("P-02:vs_lead"), _q("P-11:air"), _q("P-01:anything")])
    w = _unmeasured(_validate(tmp_path, blk, proj, "d"))
    assert [x["where"] for x in w] == ["quantities.P-01", "quantities.P-03", "quantities.P-02:vs_lead",
                                       "quantities.P-11:air", "quantities.P-01:anything"]
    assert _kind_a(w) == [] and _kind_b(w) == w
    assert not any("obs:o1" in x["where"] for x in w)


def test_without_project_or_for_an_unevaluated_project_every_quantity_is_kind_b(tmp_path):
    cases = [("noproj", None)]
    for tag, terms in (("none", None), ("empty", [])):
        cases.append((tag, _project(tmp_path / f"p_{tag}", terms)))
    for tag, proj in cases:
        w = _unmeasured(_validate(tmp_path, BLOCK, proj, f"d_{tag}"))
        assert [x["where"] for x in w] == ALL7, tag
        assert _kind_a(w) == [], tag
        assert [x["message"] for x in w] == [_b_text(q.split(".", 1)[1], COUNTS7[q.split(".", 1)[1]])
                                             for q in ALL7], tag


def test_ok_errors_and_everything_else_do_not_change(tmp_path):
    bad = copy.deepcopy(BLOCK)
    bad["moves"][0]["params"] = {"delta_db": 40.0}              # an existing error: param_range
    for tag, blk in (("good", BLOCK), ("bad", bad)):
        plain = _validate(tmp_path, blk, _project(tmp_path / f"u_{tag}", None), f"u_{tag}")
        evald = _validate(tmp_path, blk, _project(tmp_path / f"e_{tag}", TERMS), f"e_{tag}")
        assert _unmeasured(evald) and _unmeasured(plain)
        assert _kind_a(_unmeasured(evald)) and not _kind_a(_unmeasured(plain))
        strip = lambda r: dict(r, warnings=[w for w in r["warnings"] if w["code"] != "unmeasured_quantity"])
        assert strip(evald) == strip(plain)
        assert evald["ok"] is plain["ok"] is (tag == "good")


def test_a_malformed_quantity_is_an_error_only(tmp_path):
    proj = _project(tmp_path / "p", TERMS)
    blk = _blk([{"id": "c1", **_q("P-1"), "primary": True}])
    res = _validate(tmp_path, blk, proj, "d")
    assert [e["code"] for e in res["errors"]] == ["bad_quantity"] and _unmeasured(res) == []


def test_cli_exit_code_is_unchanged_by_the_warning(tmp_path, capsys):
    from mankomix.cli.main import main
    doc = T._write_doc(tmp_path / "d", BLOCK)
    for tag, terms in (("u", None), ("e", TERMS)):
        proj = _project(tmp_path / f"p_{tag}", terms)
        assert main(["direction", "validate", str(doc), "--project", str(proj)]) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["ok"] is True
        assert _unmeasured(out)
        assert bool(_kind_a(_unmeasured(out))) is (tag == "e")


def test_kind_b_full_text_for_one_quantity(tmp_path):
    blk = _blk([{"id": "c1", **_q("P-11"), "primary": True}], safeguard=[_q("P-11")])
    w = _unmeasured(_validate(tmp_path, blk, None, "d"))
    assert w == [{"where": "quantities.P-11", "code": "unmeasured_quantity",
                  "message": "P-11 は台帳指標（該当 2 件）。direction check は結果の変種の評価項だけを読み、"
                             "指揮書の結果を測り直さない。標準の流れ（master plan --apply）では評価項が残らず "
                             "not_measured になる。obs:<id> の観察量は check が床と結果の両方を測る"}]


def test_a_direction_without_ledger_quantities_gets_no_warning(tmp_path):
    blk = _blk([{"id": "c1", **_q("obs:o1"), "primary": True}], expect=[_q("obs:o1")], safeguard=[_q("obs:o1")])
    for tag, proj in (("noproj", None), ("evald", _project(tmp_path / "p", TERMS))):
        assert _unmeasured(_validate(tmp_path, blk, proj, f"d_{tag}")) == [], tag


def test_kind_a_text_is_the_original_text(tmp_path):
    proj = _project(tmp_path / "p", TERMS)
    w = _unmeasured(_validate(tmp_path, BLOCK, proj, "d"))
    assert w[0] == {"where": "quantities.P-02", "code": "unmeasured_quantity",
                    "message": "床の変種の評価項に P-02 の数値（value／penalty）が無い（該当 3 件）。direction check は "
                               "not_measured を返す。obs:<id>（masking／wet_ratio／trk 対象の観察量）で測れる"}
