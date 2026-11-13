"""Deterministic planner loop (SPEC 7.2, R-01, R-06, R-15, R-23, R-29, R-31; M3 completion criterion).

A synthesized 2mix with an obvious tonal imbalance (a broad +8 dB bump at
3.5 kHz on a pink-like spectrum) is mastered with the default objective
(comfort). Audio is written into tmp folders only.
"""
from __future__ import annotations

import json

import numpy as np
import pytest
import soundfile as sf

from mankomix.core import planner
from mankomix.core.errors import InputError
from mankomix.core.hashing import sha256_file
from mankomix.core.project import Project
from tests.fixtures import synth

SR = 48000


def harsh_mix(seconds: float = 6.0, boost_db: float = 8.0, seed: int = 3) -> np.ndarray:
    p = synth.pink_noise(-20.0, sr=SR, seconds=seconds, seed=seed)[:, 0]
    a = synth.pink_noise(-20.0, sr=SR, seconds=seconds, seed=seed + 1)[:, 0]
    b = synth.pink_noise(-20.0, sr=SR, seconds=seconds, seed=seed + 2)[:, 0]
    x = np.stack([p + 0.3 * a, p + 0.3 * b], axis=1)
    t = np.arange(x.shape[0]) / SR
    x *= (0.6 + 0.4 * (np.mod(t, 0.5) < 0.12))[:, None]
    x[: int(1.5 * SR)] *= 0.35
    x = synth._filt(synth._peaking_sos(SR, 3500.0, boost_db, 0.9), x)
    return x / np.max(np.abs(x)) * 10 ** (-6.0 / 20)


def make_project(root, x: np.ndarray) -> Project:
    proj = Project.create(root, title="planner test")
    path = root / "assets" / "mix.wav"
    sf.write(str(path), x.astype(np.float32), SR, subtype="FLOAT")
    proj.data["assets"].append({
        "id": "ast_fullmix", "path": "assets/mix.wav", "original_name": "mix.wav",
        "sha256": sha256_file(path), "role": "fullmix", "origin": "reference_fullmix",
        "channels": 2, "sample_rate": SR, "length_samples": int(x.shape[0]),
    })
    proj.data["fullmix_asset"] = "ast_fullmix"
    proj.data["timebase"]["sample_rate"] = SR
    proj.data["timebase"]["length_samples"] = int(x.shape[0])
    proj.save(actor="human", op="import", reason="test import")
    return proj


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    return make_project(tmp_path_factory.mktemp("planner") / "song.mmx", harsh_mix())


@pytest.fixture(scope="module")
def loop(project):
    return planner.run_loop(project, profile_id="spotify", delivery_id="hires_native", max_iter=6)


def test_comfort_loop_improves_monotonically_and_stops_with_a_reason(loop):
    its = loop["iterations"]
    assert its[0]["i"] == 0 and its[0]["move"] is None
    assert len(its) >= 3, "the obvious imbalance must be acted on"
    scores = [it["score"] for it in its]
    assert all(b < a for a, b in zip(scores, scores[1:])), scores
    assert scores[-1] < 0.5 * scores[0]
    for it in its[1:]:
        assert it["improvement"] >= loop["min_improvement"]
    assert loop["reason"]
    assert loop["converged"] or loop["reason"].startswith("iteration cap")
    assert len(its) - 1 <= loop["max_iter"]
    # the harsh band is cut, in small steps, within the master EQ limit (R-06, R-15)
    moves = [it["move"] for it in its[1:]]
    assert all(m["kind"] == "eq" and abs(m["delta_db"]) <= 0.5 for m in moves)
    assert any(m["band"] == "high_mid" and m["delta_db"] < 0 for m in moves)
    for p in loop["best"]["chain"]:
        if p["type"] == "eq":
            assert abs(p["params"]["gain_db"]) <= 2.0 + 1e-9


def test_chosen_chain_never_violates_constraints(loop):
    for it in loop["iterations"]:
        assert it["rejected"] is False
        assert "fail" not in it["constraints"].values()
    final = loop["final"]["evaluation"]
    assert final["rejected"] is False and "fail" not in final["constraints"].values()
    assert final["constraints"]["S-01"] == "pass" and final["constraints"]["S-06"] == "pass"
    types = [p["type"] for p in loop["best"]["chain"]]
    assert types[-1] == "limiter" and types[-2] == "loudness_gain"
    for r in loop["rejected"]:
        assert r.get("constraints") or r.get("gate")


def test_achievement_breakdown_and_report_material(loop):
    final = loop["final"]
    assert final["scope"] == "full_length"
    terms = final["evaluation"]["terms"]
    keys = {t["key"] for t in terms}
    assert {"P-01", "P-02", "P-03", "P-09", "P-11", "P-12", "P-19"} <= keys
    for t in terms:
        assert {"objective", "metric", "weight", "effective_weight", "value", "target", "penalty",
                "contribution", "status"} <= set(t)
    assert final["evaluation"]["score"] == pytest.approx(sum(t["contribution"] for t in terms))
    red = final["evaluation"]["redistribution"]
    assert red and set(red[0]["terms"]) == {"P-02", "P-09"}
    gate = final["evaluation"]["gate"]
    assert gate["status"] == "incomplete"          # 2mix only: lead checks not evaluable
    codes = {u["code"] for u in loop["unresolved"]}
    assert "not_measured" in codes and "gate_incomplete" in codes
    dec = loop["decisions"]
    assert set(dec) == {"balance", "panning", "frequency", "depth", "dynamics", "interest"}
    assert dec["interest"][0]["status"] == "depends_on_humans_and_references"
    assert any(d.get("rule") for d in dec["frequency"])
    json.dumps(loop, allow_nan=False)


def test_cap_and_determinism(project, loop):
    a = planner.run_loop(project, profile_id="spotify", delivery_id="hires_native", max_iter=1)
    b = planner.run_loop(project, profile_id="spotify", delivery_id="hires_native", max_iter=1)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert a["converged"] is False and a["reason"] == "iteration cap reached (1)"
    # the capped run is a prefix of the longer run
    for x, y in zip(a["iterations"], loop["iterations"][:2]):
        assert x["chain"] == y["chain"] and x["score"] == y["score"]


def test_excerpts_for_long_material():
    x = np.concatenate([harsh_mix(8.0, seed=5) * 0.2, harsh_mix(8.0, seed=6), harsh_mix(8.0, seed=7) * 0.5])
    ex = planner.choose_excerpts(x, SR)
    labels = {e["label"] for e in ex}
    assert {"loudest", "quietest"} <= labels and len(ex) == 3
    for e1, e2 in zip(ex, ex[1:]):
        assert e1["end"] <= e2["start"]
    loud = next(e for e in ex if e["label"] == "loudest")
    quiet = next(e for e in ex if e["label"] == "quietest")
    assert 8 * SR <= loud["start"] < 16 * SR and quiet["start"] < 8 * SR
    assert planner.choose_excerpts(x[: 6 * SR], SR) == [{"label": "full", "start": 0, "end": 6 * SR}]


def test_propose_and_apply(project):
    with pytest.raises(InputError):
        planner.propose(project, "mix")
    prop = planner.propose(project, "master", profile_id="spotify", delivery_id="hires_native", max_iter=1)
    assert prop["stage"] == "master" and prop["proposal_id"].startswith("mpl_")
    assert prop["operations"] == ["approve_and_apply", "reject_and_request_alternative"]
    assert prop["rationale"][-1]["stage"] == "planner_loop" and prop["rationale"][-1]["rule"]
    assert prop["alternatives"] and prop["objective_evaluation"]["terms"]
    assert prop["decisions"]["interest"]
    out = planner.apply(project, prop, actor="planner")
    assert out["applied"] is True
    v = next(v for v in Project.open(project.root).data["variants"] if v["id"] == prop["variant"])
    assert v["master"]["chain"] == prop["chain"]
