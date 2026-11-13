"""Objective resolution and evaluation (SPEC 4.1, 4.3, 4.4, 4.7, 4.8, 4.10).

All audio is synthesized; nothing is read from or written to the repository.
"""
from __future__ import annotations

import copy
import json

import numpy as np
import pytest

from mankomix.core import config
from mankomix.core import objectives as O
from mankomix.core.errors import InputError, ValidationError
from tests.fixtures import synth

SR = 48000


def _pink_stereo(seconds: float = 4.0, seed: int = 11) -> np.ndarray:
    p = synth.pink_noise(-20.0, sr=SR, seconds=seconds, seed=seed)[:, 0]
    a = synth.pink_noise(-20.0, sr=SR, seconds=seconds, seed=seed + 1)[:, 0]
    b = synth.pink_noise(-20.0, sr=SR, seconds=seconds, seed=seed + 2)[:, 0]
    x = np.stack([p + 0.3 * a, p + 0.3 * b], axis=1)
    t = np.arange(x.shape[0]) / SR
    x *= (0.6 + 0.4 * (np.mod(t, 0.5) < 0.12))[:, None]
    return x / np.max(np.abs(x)) * 10 ** (-6 / 20)


@pytest.fixture(scope="module")
def pink():
    return _pink_stereo()


@pytest.fixture(scope="module")
def antiphase(pink):
    return synth.antiphase_low(pink, SR, below_hz=120.0)


def _term(res, objective, key):
    return next(t for t in res["terms"] if t["objective"] == objective and t["key"] == key)


# --------------------------------------------------------------------------
# spec parsing / blend / intensity


def test_parse_objective_arg_forms():
    assert O.parse_objective_arg("comfort")["blend"] == [{"id": "comfort", "weight": 1.0}]
    s = O.parse_objective_arg("bass_heavy:0.7")
    assert s["blend"] == [{"id": "bass_heavy", "weight": 1.0}] and s["intensity"] == 0.7
    s = O.parse_objective_arg("comfort:0.6+bass_heavy:0.4")
    assert [b["weight"] for b in s["blend"]] == [0.6, 0.4] and s["intensity"] == 0.5


def test_blend_is_normalised_and_term_weights_sum_to_one():
    res = O.resolve_objective({"blend": [{"id": "comfort", "weight": 3}, {"id": "bass_heavy", "weight": 1}],
                               "intensity": 0.5})
    assert [round(b["weight"], 6) for b in res["blend"]] == [0.75, 0.25]
    assert sum(t["weight"] for t in res["terms"]) == pytest.approx(1.0)
    assert sum(t["weight"] for t in res["terms"] if t["objective"] == "comfort") == pytest.approx(0.75)
    p01 = _term(res, "comfort", "P-01")
    assert p01["weight"] == pytest.approx(0.75 * 0.25)


def test_intensity_moves_targets_from_base_towards_the_objective_limit():
    def p07(i):
        r = O.resolve_objective({"blend": [{"id": "bass_heavy", "weight": 1}], "intensity": i})
        return _term(r, "bass_heavy", "P-07:sub+bass")["target"]

    t0, t5, t1 = p07(0.0), p07(0.5), p07(1.0)
    row = O.metric_table()["metrics"]["P-07"]["sub+bass"]
    assert t0["range"] == row["base"] and t0["intensity_applied"] is False
    assert t1["range"] == pytest.approx(row["limit"])
    assert t5["range"] == pytest.approx([(a + b) / 2 for a, b in zip(row["base"], row["limit"])])
    # minimize-type term tightens towards its limit
    r1 = O.resolve_objective({"blend": [{"id": "low_fatigue", "weight": 1}], "intensity": 1.0})
    assert _term(r1, "low_fatigue", "P-11")["target"]["range"][1] == pytest.approx(1.0)


def test_comfort_is_the_intensity_baseline():
    a = O.resolve_objective({"blend": [{"id": "comfort", "weight": 1}], "intensity": 0.0})
    b = O.resolve_objective({"blend": [{"id": "comfort", "weight": 1}], "intensity": 1.0})
    for ta, tb in zip(a["terms"], b["terms"]):
        assert ta["target"].get("range") == tb["target"].get("range")
        assert tb["target"]["intensity_applied"] is False


# --------------------------------------------------------------------------
# constraints: rejection, never relaxed


def test_constraint_failure_rejects_regardless_of_blend_and_intensity(antiphase):
    specs = [
        {"blend": [{"id": "comfort", "weight": 1}], "intensity": 0.0},
        {"blend": [{"id": "bass_heavy", "weight": 1}], "intensity": 1.0},
        {"blend": [{"id": "club_impact", "weight": 2}, {"id": "clarity", "weight": 1}], "intensity": 1.0},
        {"blend": [{"id": "low_fatigue", "weight": 1}], "intensity": 0.3},
    ]
    base = O.resolve_objective(specs[0])
    meas = O.measure_for_objective(antiphase, SR, base, profile="spotify", ceiling_dbtp=-1.0)
    for spec in specs:
        for genre in (None, "edm", "club_track"):
            res = O.resolve_objective(spec, genre=genre)
            assert res["constraints"]["relaxable"] is False
            ev = O.evaluate(meas, res)
            assert ev["constraints"]["S-04"] == "fail"
            assert ev["rejected"] is True and ev["score"] is None
            assert ev["score_unconstrained"] is not None
            # the limits come from knowledge/thresholds.json, not from the objective
            assert ev["constraint_details"]["S-04"]["limits"]["low_band_max_db"] == 1.5


def test_clean_signal_passes_constraints_and_scores(pink):
    res = O.resolve_objective("comfort")
    ev = O.evaluate(O.measure_for_objective(pink, SR, res, profile="spotify", ceiling_dbtp=-1.0), res)
    assert ev["rejected"] is False
    for s in ("S-01", "S-03", "S-04", "S-09"):
        assert ev["constraints"][s] == "pass"
    assert ev["constraints"]["S-02"] == "not_evaluated"
    assert 0.0 <= ev["score"] <= 1.0
    json.dumps(ev, allow_nan=False)


def test_relaxation_attempts_in_overrides_are_rejected():
    for bad in ({"comfort": {"S-04": {"low_band_max_db": 6}}},
                {"bass_heavy": {"relax_constraints": True}},
                {"bass_heavy": {"undeclared_param": 1}}):
        with pytest.raises(ValidationError):
            O.resolve_objective({"blend": [{"id": "comfort", "weight": 1}, {"id": "bass_heavy", "weight": 1}],
                                 "intensity": 0.5, "overrides": bad})
    issues = O.validate_objective_spec({"blend": [{"id": "translation", "weight": 1}], "intensity": 0.5})
    assert any("gate" in i["message"] for i in issues)


# --------------------------------------------------------------------------
# not_measured redistribution


def test_not_measured_terms_redistribute_weight_and_are_recorded(pink):
    res = O.resolve_objective("comfort")
    ev = O.evaluate(O.measure_for_objective(pink, SR, res, before=pink), res)
    status = {t["key"]: t["status"] for t in ev["terms"]}
    assert status["P-02"] == "not_measured" and status["P-09"] == "not_measured"
    assert status["P-01"] == status["P-11"] == status["P-12"] == "measured"
    red = ev["redistribution"]
    assert len(red) == 1 and set(red[0]["terms"]) == {"P-02", "P-09"}
    assert red[0]["moved_weight"] == pytest.approx(0.30)
    assert all(red[0]["reasons"][k] for k in red[0]["terms"])
    eff = {t["key"]: t["effective_weight"] for t in ev["terms"]}
    assert eff["P-02"] == 0.0
    assert sum(eff.values()) == pytest.approx(1.0)
    assert eff["P-01"] == pytest.approx(0.25 / 0.70)
    assert ev["score"] == pytest.approx(sum(t["contribution"] for t in ev["terms"]))
    # without the unprocessed signal the preservation term is not measured either
    ev2 = O.evaluate(O.measure_for_objective(pink, SR, res), res)
    assert {t["key"]: t["status"] for t in ev2["terms"]}["P-12"] == "not_measured"


def test_unmeasurable_metrics_are_marked(pink):
    res = O.resolve_objective({"blend": [{"id": "low_fatigue", "weight": 1}], "intensity": 0.5})
    ev = O.evaluate(O.measure_for_objective(pink, SR, res), res)
    p16 = next(t for t in ev["terms"] if t["key"] == "P-16")
    assert p16["status"] == "not_measured" and "cleanup" in p16["reason"]
    res18 = O.resolve_objective({"blend": [{"id": "comfort", "weight": 1}], "intensity": 0.5})
    res18 = copy.deepcopy(res18)
    res18["terms"].append({**res18["terms"][0], "metric": "P-18", "key": "P-18", "variant": None,
                           "variant_canonical": None, "target": {"range": [None, 4.0], "scale": 2.0}})
    meas = O.measure_for_objective(pink, SR, res18)
    assert O.term_value(meas, res18["terms"][-1])["status"] == "not_measured"
    meas["limiter"] = {"gr_p95_db": 6.0}
    tv = O.term_value(meas, res18["terms"][-1])
    assert tv["status"] == "measured" and tv["penalty"] > 0.5


# --------------------------------------------------------------------------
# genre prior and lead


def test_genre_prior_changes_initial_values_with_provenance():
    spec = {"blend": [{"id": "bass_heavy", "weight": 1}], "intensity": 0.5}
    plain = O.resolve_objective(spec)
    hip = O.resolve_objective(spec, genre="hiphop")
    assert any(n["code"] == "genre_unset" for n in plain["notes"])
    assert not plain["provenance"]
    w_plain = _term(plain, "bass_heavy", "P-13")["weight"]
    w_hip = _term(hip, "bass_heavy", "P-13")["weight"]
    assert w_hip > w_plain
    assert _term(hip, "bass_heavy", "P-13")["weight_source"] == "genre_prior:hiphop:emphasis"
    assert sum(t["weight"] for t in hip["terms"]) == pytest.approx(1.0)
    prov = [p for p in hip["provenance"] if p["metric"] == "P-13"]
    assert prov and prov[0]["source"] == "genre_prior:hiphop" and prov[0]["from"] == pytest.approx(0.20)
    # P-10 target from the genre prior; an explicit user override wins (R-33)
    vf = {"blend": [{"id": "vocal_forward", "weight": 1}], "intensity": 0.0}
    t = _term(O.resolve_objective(vf, genre="jpop"), "vocal_forward", "P-10")["target"]
    assert t["range"] == [2.0, 6.0] and t["source"] == "genre_prior:jpop"
    t = _term(O.resolve_objective(vf), "vocal_forward", "P-10")["target"]
    assert t["source"] == "generic"
    vf_user = dict(vf, overrides={"vocal_forward": {"p10_target_db": [1.0, 3.0]}})
    t = _term(O.resolve_objective(vf_user, genre="jpop"), "vocal_forward", "P-10")["target"]
    assert t["range"] == [1.0, 3.0] and t["source"] == "user_override"


def test_declared_param_override_changes_the_metric_band():
    spec = {"blend": [{"id": "bass_heavy", "weight": 1}], "intensity": 0.5,
            "overrides": {"bass_heavy": {"sub_band_hz": [30, 60]}}}
    t = _term(O.resolve_objective(spec), "bass_heavy", "P-07:sub+bass")["target"]
    assert t["range_hz"] == [30.0, 250.0] and t["param_source"] == "user_override"
    with pytest.raises(ValidationError):
        O.resolve_objective(dict(spec, overrides={"bass_heavy": {"sub_band_hz": [5, 60]}}))


def test_lead_resolution_marks_estimates():
    meta = {"vox": {"role": "vocals"}, "gtr": {"role": "guitar"}}
    est = O.resolve_objective("vocal_forward", meta=meta)["lead"]
    assert est == {**est, "stem": "vox", "estimated": True, "source": "estimated_from_role"}
    dec = O.resolve_objective({"blend": [{"id": "vocal_forward", "weight": 1}], "intensity": 0.5,
                               "lead_stem": "gtr"}, meta=meta)["lead"]
    assert dec["stem"] == "gtr" and dec["estimated"] is False
    with pytest.raises(InputError):
        O.resolve_objective({"blend": [{"id": "comfort", "weight": 1}], "intensity": 0.5, "lead_stem": "nope"},
                            meta=meta)
    assert O.resolve_objective("comfort")["lead"]["source"] == "no_stems"


# --------------------------------------------------------------------------
# definition validation (objective validate)


def _spec_example() -> dict:
    return {
        "id": "bass_heavy_user", "schema_version": 1, "kind": "score",
        "label": {"ja": "重低音強化", "en": "Bass heavy"},
        "terms": [
            {"metric": "P-07", "variant": "sub+bass", "weight": 0.35, "sense": "raise_to_target"},
            {"metric": "P-13", "weight": 0.20, "sense": "minimize"},
            {"metric": "P-02", "variant": "low_to_mid", "weight": 0.20, "sense": "minimize"},
            {"metric": "P-08", "weight": 0.15, "sense": "raise_to_target"},
            {"metric": "P-03", "variant": "plr", "weight": 0.10, "sense": "keep_in_range"},
        ],
        "constraints_emphasis": ["S-03", "S-04"],
        "params": {"sub_band_hz": {"default": [20, 60]}},
    }


def _errors(issues):
    return [i for i in issues if i["level"] == "error"]


def test_definition_validation_accepts_spec_example_and_catalog():
    assert _errors(O.validate_objective_definition(_spec_example())) == []
    assert _errors(O.validate_objective_definition(config.load_objectives())) == []


def test_definition_validation_catches_unknown_metric_weight_sum_and_relaxation():
    bad = _spec_example()
    bad["terms"][1]["metric"] = "P-99"
    assert any("P-99" in i["message"] for i in _errors(O.validate_objective_definition(bad)))

    bad = _spec_example()
    bad["terms"][0]["weight"] = 0.25
    assert any("sum" in i["message"] for i in _errors(O.validate_objective_definition(bad)))

    bad = _spec_example()
    bad["terms"][0]["variant"] = "sub_plus_everything"
    assert any("variant" in i["message"] for i in _errors(O.validate_objective_definition(bad)))

    for mutate in (lambda d: d["params"].update({"relax_s04": {"default": True}}),
                   lambda d: d["terms"][0].update({"params": {"S-04": {"low_band_max_db": 9}}}),
                   lambda d: d.update({"x_constraints_override": {"S-01": -0.1}})):
        bad = _spec_example()
        mutate(bad)
        errs = _errors(O.validate_objective_definition(bad))
        assert errs, mutate
        assert any("S-nn" in e["message"] or "relax" in e["message"].lower() or "pattern" in e["message"].lower()
                   or "not" in e["message"].lower() for e in errs)
