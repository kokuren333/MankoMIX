"""Schemas and data files (SPEC 4.8, 5.2, 5.3, 12.2, 6.8)."""
from __future__ import annotations

import copy
import json

import pytest
from jsonschema import Draft202012Validator

from mankomix import repo_data_root
from mankomix.core import config, schema
from mankomix.core.errors import InputError


def _load(rel):
    with open(repo_data_root() / rel, encoding="utf-8") as fh:
        return json.load(fh)


def _errors(issues):
    return [i for i in issues if i["level"] == "error"]


@pytest.fixture
def catalog():
    return _load("objectives/catalog.json")


@pytest.mark.parametrize("name", schema.SCHEMA_NAMES)
def test_schema_files_are_valid_2020_12(name):
    s = schema.load_schema(name)
    assert s["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    Draft202012Validator.check_schema(s)


def test_data_files_validate():
    deliveries = _load("profiles/delivery_formats.json")
    assert _errors(schema.check_objectives(_load("objectives/catalog.json"))) == []
    assert _errors(schema.check_deliveries(deliveries)) == []
    assert _errors(schema.check_profiles(_load("profiles/media_profiles.json"), deliveries)) == []
    assert _errors(schema.check_registry(_load("registry/models.json"))) == []


def test_knowledge_and_sample_files_reference_known_ids():
    priors = config.load_genre_priors()
    assert config.load_vocabulary()["terms"]
    groups = set(priors["importance_groups"])
    for g in priors["genres"]:
        assert set(g.get("stem_importance_order", [])) <= groups
    sample = _load("samples/sample_set.json")
    assert sample["genre"] in config.genre_ids()
    for v in sample["variants"]:
        config.get_objective(v["objective"])
        config.get_profile(v["profile"])
        for d in v.get("deliveries", []):
            config.get_delivery(d)
    for p in sample["verification_only_profiles"]:
        config.get_profile(p)


def test_score_weights_sum_to_one(catalog):
    for obj in catalog["objectives"]:
        if obj["kind"] == "score":
            assert abs(sum(t["weight"] for t in obj["terms"]) - 1.0) <= 1e-6, obj["id"]


def test_unknown_metric_fails(catalog):
    bad = copy.deepcopy(catalog)
    bad["objectives"][0]["terms"][0]["metric"] = "P-99"
    errs = _errors(schema.check_objectives(bad))
    assert any(e["path"] == "/objectives/0/terms/0/metric" for e in errs)


def test_weight_sum_not_one_fails(catalog):
    bad = copy.deepcopy(catalog)
    terms = bad["objectives"][1]["terms"]  # bass_heavy
    terms[0]["weight"] = round(terms[0]["weight"] - 0.1, 10)  # total 0.9
    errs = _errors(schema.check_objectives(bad))
    assert any(e["path"] == "/objectives/1/terms" and "sum" in e["message"] for e in errs)


def test_gate_objective_is_exempt_from_weight_sum(catalog):
    gate = next(o for o in catalog["objectives"] if o["kind"] == "gate")
    assert "terms" not in gate
    assert _errors(schema.check_objectives(catalog)) == []


@pytest.mark.parametrize("field,value", [
    ("constraints_relax", ["S-01"]),
    ("relax_constraints", True),
    ("waive", ["S-03"]),
    ("disable_constraints", ["S-04"]),
])
def test_constraint_relaxation_field_fails(catalog, field, value):
    bad = copy.deepcopy(catalog)
    bad["objectives"][0][field] = value
    assert _errors(schema.check_objectives(bad))


def test_relaxation_param_and_unknown_constraint_fail(catalog):
    bad = copy.deepcopy(catalog)
    bad["objectives"][1]["params"] = {"relax_true_peak": {"default": True}}
    assert _errors(schema.check_objectives(bad))
    bad = copy.deepcopy(catalog)
    bad["objectives"][0]["constraints_emphasis"] = ["S-12"]
    assert _errors(schema.check_objectives(bad))


def test_single_objective_file_like_spec_example():
    obj = {
        "id": "bass_heavy_custom", "schema_version": 1,
        "label": {"ja": "重低音強化", "en": "Bass heavy"}, "kind": "score", "status": "draft",
        "summary": {"ja": "低域の量と質を最大化しつつ濁らせない"},
        "terms": [
            {"metric": "P-07", "variant": "sub+bass", "weight": 0.35, "sense": "raise_to_target"},
            {"metric": "P-13", "weight": 0.20, "sense": "minimize"},
            {"metric": "P-02", "variant": "low_to_mid", "weight": 0.20, "sense": "minimize"},
            {"metric": "P-08", "weight": 0.15, "sense": "raise_to_target"},
            {"metric": "P-03", "variant": "plr", "weight": 0.10, "sense": "keep_in_range"},
        ],
        "constraints_emphasis": ["S-03", "S-04"],
        "params": {"sub_band_hz": {"default": [20, 60]}},
        "report_notes": ["normalization_tradeoff"],
        "evidence": "weights are initial values subject to calibration",
    }
    assert _errors(schema.check_objectives(obj)) == []
    obj["terms"][0]["weight"] = 0.30
    assert _errors(schema.check_objectives(obj))


def test_profile_checks():
    deliveries = _load("profiles/delivery_formats.json")
    profiles = _load("profiles/media_profiles.json")
    bad = copy.deepcopy(profiles)
    bad["profiles"][0]["default_delivery"] = "no_such_delivery"
    assert _errors(schema.check_profiles(bad, deliveries))
    bad = copy.deepcopy(profiles)
    bad["profiles"][0]["loudness"]["target_lufs_i"] = -20.0  # outside window
    assert _errors(schema.check_profiles(bad, deliveries))
    bad = copy.deepcopy(profiles)
    bad["profiles"][0]["aliases"] = ["spotify"]  # collides with an id
    assert _errors(schema.check_profiles(bad, deliveries))


def test_delivery_dither_rules():
    doc = _load("profiles/delivery_formats.json")
    bad = copy.deepcopy(doc)
    bad["formats"][2]["dither"] = "none"  # 16 bit without dither
    assert _errors(schema.check_deliveries(bad))


def test_registry_rules():
    reg = _load("registry/models.json")
    bad = copy.deepcopy(reg)
    del bad["models"][0]["license"]["evidence"]
    assert _errors(schema.check_registry(bad))
    bad = copy.deepcopy(reg)
    del bad["models"][0]["license"]["weights"]
    assert _errors(schema.check_registry(bad))
    bad = copy.deepcopy(reg)
    bad["models"][0]["license"]["usage_restrictions"] = "research_only"
    assert _errors(schema.check_registry(bad))  # official tier needs usage_restrictions none
    ok = copy.deepcopy(bad)
    ok["models"][0]["tier"] = "byow"
    assert _errors(schema.check_registry(ok)) == []
    bad = copy.deepcopy(reg)
    bad["models"][0]["status"] = "verified"  # without pinned url + sha256
    assert _errors(schema.check_registry(bad))
    bad = copy.deepcopy(reg)
    bad["models"][0]["tier"] = "community"
    assert _errors(schema.check_registry(bad))


def test_report_skeleton():
    report = {
        "schema_version": 1,
        "summary": {"result": "pass"},
        "decisions": {"balance": [{"measured": {}, "rule": "R-04", "action": "gain", "alternatives": [], "result": {}}]},
        "listening_checks": [{"time_s": 12.5, "point": "chorus sibilance"}],
        "reproducibility": {"project_hash": "0" * 64},
        "extra_section": {"anything": True},
    }
    assert schema.check_report(report) == []
    assert schema.check_report({"summary": {"result": "maybe"}})


def test_config_lookups():
    assert config.get_profile("mv")["id"] == "youtube"
    assert config.get_delivery("distributor_44k16")["bit_depth"] == 16
    assert config.get_objective("comfort")["kind"] == "score"
    assert config.get_genre_prior("hiphop")["low_end_lead"] == "kick"
    with pytest.raises(InputError) as exc:
        config.get_profile("nope")
    assert "spotify" in exc.value.message and "mv" in exc.value.details["valid"]
    with pytest.raises(InputError):
        config.get_objective("nope")
    with pytest.raises(InputError):
        config.load_knowledge("../objectives/catalog")
    # getters hand out copies
    config.get_profile("spotify")["id"] = "mutated"
    assert config.get_profile("spotify")["id"] == "spotify"
