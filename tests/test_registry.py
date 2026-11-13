"""Model registry: catalogue rules, BYOW, pull / verify / remove (SPEC 12, S-10)."""

from __future__ import annotations

import copy
import hashlib
import io
import json

import pytest

from core import config, registry
from core.errors import EnvironmentProblem, InputError, ValidationError


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    monkeypatch.setenv("MANKOMIX_HOME", str(h))
    config.clear_cache()
    yield h
    config.clear_cache()


def _errors(issues):
    return [i for i in issues if i["level"] == "error"]


def _catalog():
    return copy.deepcopy(config.load_registry())


def _fake_doc(payload: bytes, *, sha: str | None = None, status: str = "verified") -> dict:
    return {
        "schema_version": 1,
        "models": [{
            "id": "fake_model",
            "task": "separation",
            "stems": ["a", "b"],
            "architecture": "fake",
            "runtime": {"backend": "fake_filter", "cpu_ok": True},
            "weights": {"filename": "fake.bin", "source_url": "https://example.invalid/fake.bin",
                        "sha256": sha or hashlib.sha256(payload).hexdigest(), "size_bytes": len(payload)},
            "license": {"code": "MIT", "weights": "MIT", "usage_restrictions": "none",
                        "evidence": [{"url": "https://example.invalid/license", "checked_on": "2026-11-13",
                                      "kind": "license_file"}],
                        "caveats": ["test caveat"]},
            "attribution": "test attribution",
            "tier": "official",
            "status": status,
            "status_reason": "test",
        }],
    }


def _serve(monkeypatch, payload: bytes, calls: list | None = None):
    def fake_open(url):
        if calls is not None:
            calls.append(url)
        return io.BytesIO(payload)
    monkeypatch.setattr(registry, "_open_url", fake_open)


# --- catalogue -------------------------------------------------------------------------------------

def test_catalogue_validates():
    doc = registry.load_catalog()
    assert _errors(registry.catalog_issues(doc)) == []
    by_id = {m["id"]: m for m in doc["models"]}
    for mid in ("kim_melband_roformer_vocals", "scnet_4stem", "scnet_large_4stem", "open_unmix_umxhq"):
        assert by_id[mid]["status"] == "verified"
        assert by_id[mid]["license"]["usage_restrictions"] == "none"
        assert any("MUSDB" in c or "Training data" in c for c in by_id[mid]["license"]["caveats"])
    # D-042: at least one verified official model runs on the CPU
    assert any(m["status"] == "verified" and m["runtime"].get("cpu_ok") for m in doc["models"])
    # research-only / non-commercial weights stay out of the official tier
    names = " ".join(e["name"] for e in doc["excluded_from_standard_route"])
    assert "Demucs" in names and "umxl" in names
    assert not any("demucs" in m["id"] or "umxl" in m["id"] for m in doc["models"])
    for mode in ("preview", "full"):
        assert by_id[doc["defaults"][mode]]["status"] == "verified"


def test_research_only_official_entry_fails():
    doc = _catalog()
    doc["models"][0]["license"]["usage_restrictions"] = "research_only"
    assert _errors(registry.catalog_issues(doc))


def test_missing_evidence_or_license_fails():
    doc = _catalog()
    del doc["models"][0]["license"]["evidence"]
    assert _errors(registry.catalog_issues(doc))
    doc = _catalog()
    doc["models"][0]["license"]["evidence"] = []
    assert _errors(registry.catalog_issues(doc))
    doc = _catalog()
    del doc["models"][0]["license"]
    assert _errors(registry.catalog_issues(doc))
    doc = _catalog()
    doc["models"][0]["license"]["weights"] = "unknown"
    assert _errors(registry.catalog_issues(doc))


def test_catalogue_rules_beyond_schema():
    doc = _catalog()
    doc["models"][0]["license"]["evidence"] = [
        {"url": "https://example.invalid/blog", "checked_on": "2026-11-13", "kind": "secondary"}]
    assert any("primary" in e["message"] for e in _errors(registry.catalog_issues(doc)))
    doc = _catalog()
    doc["models"][0]["tier"] = "byow"
    assert _errors(registry.catalog_issues(doc))
    doc = _catalog()
    doc["defaults"]["preview"] = "uvr_mdx_net_inst_hq_3"   # a candidate
    assert _errors(registry.catalog_issues(doc))
    doc = _catalog()
    doc["models"][0]["license"]["evidence"] = [{"kind": "user_declaration", "checked_on": "2026-11-13"}]
    assert _errors(registry.catalog_issues(doc))            # official evidence needs a URL


def test_list_and_show_have_no_absolute_paths(home):
    out = registry.model_list()
    ids = [m["id"] for m in out["models"]]
    assert "scnet_4stem" in ids
    assert all(m["state"] == "not_installed" for m in out["models"])
    show = registry.model_show("kim_melband_roformer_vocals")
    assert show["license"]["weights"] == "MIT" and show["attribution"]
    text = json.dumps([out, show])
    assert str(home) not in text and str(home).replace("\\", "/") not in text


# --- pull -------------------------------------------------------------------------------------------

def test_pull_refuses_unknown_and_candidates(monkeypatch):
    calls: list = []
    _serve(monkeypatch, b"x", calls)
    with pytest.raises(InputError):
        registry.model_pull("no_such_model")
    with pytest.raises(InputError, match="candidate"):
        registry.model_pull("uvr_mdx_net_inst_hq_3")
    assert calls == []


def test_pull_downloads_and_verifies(monkeypatch, home):
    payload = b"weights-v1" * 1000
    monkeypatch.setattr(registry, "load_catalog", lambda: _fake_doc(payload))
    calls: list = []
    _serve(monkeypatch, payload, calls)
    res = registry.model_pull("fake_model")
    assert res["files"][0]["action"] == "downloaded"
    assert res["license"]["weights"] == "MIT" and res["attribution"] == "test attribution"
    assert res["caveats"] == ["test caveat"]
    dest = home / "models" / "fake_model" / "fake.bin"
    assert dest.read_bytes() == payload
    again = registry.model_pull("fake_model")
    assert again["files"][0]["action"] == "present" and len(calls) == 1
    assert registry.model_verify("fake_model")["ok"]
    dest.write_bytes(b"tampered")
    v = registry.model_verify("fake_model")
    assert not v["ok"] and v["files"][0]["state"] == "sha256_mismatch"
    with pytest.raises(ValidationError):
        registry.resolve_for_run("fake_model")
    rm = registry.model_remove("fake_model")
    assert rm["files"] == ["fake.bin"] and not dest.exists()


def test_pull_detects_sha_mismatch(monkeypatch, home):
    payload = b"real weights"
    monkeypatch.setattr(registry, "load_catalog", lambda: _fake_doc(payload, sha="0" * 64))
    _serve(monkeypatch, payload)
    with pytest.raises(ValidationError, match="sha256"):
        registry.model_pull("fake_model")
    folder = home / "models" / "fake_model"
    assert not (folder / "fake.bin").exists()
    assert not (folder / "fake.bin.part").exists()


def test_candidate_needs_explicit_flag(monkeypatch, home):
    payload = b"candidate weights"
    monkeypatch.setattr(registry, "load_catalog", lambda: _fake_doc(payload, status="candidate"))
    _serve(monkeypatch, payload)
    with pytest.raises(InputError):
        registry.model_pull("fake_model")
    res = registry.model_pull("fake_model", allow_candidate=True)
    assert res["warnings"] and res["files"][0]["action"] == "downloaded"
    with pytest.raises(InputError):
        registry.resolve_for_run("fake_model")
    assert registry.resolve_for_run("fake_model", allow_candidate=True)["model_sha256"]


def test_resolve_never_downloads(monkeypatch):
    def boom(url):
        raise AssertionError("resolve_for_run must not download")
    monkeypatch.setattr(registry, "_open_url", boom)
    with pytest.raises(EnvironmentProblem, match="model pull"):
        registry.resolve_for_run("scnet_4stem")


def test_open_url_rejects_non_http():
    with pytest.raises(InputError):
        registry._open_url("file:///etc/passwd")


# --- BYOW -------------------------------------------------------------------------------------------

def test_byow_register_verify_remove(tmp_path, home):
    w = tmp_path / "user_weights" / "my_model.ckpt"
    w.parent.mkdir()
    w.write_bytes(b"user weights" * 100)
    res = registry.model_register(w, id="my_demucs", license_weights="unknown",
                                  usage_restrictions="research only (author statement)",
                                  architecture="htdemucs", stems=["vocals", "other"])
    assert res["sha256"] == hashlib.sha256(w.read_bytes()).hexdigest()
    assert len(res["warnings"]) == 2 and "BYOW" in res["notice"]
    assert str(tmp_path) not in json.dumps(res)
    # stored in local settings, file not copied
    doc = json.loads((home / "byow.json").read_text(encoding="utf-8"))
    assert doc["models"][0]["tier"] == "byow" and doc["models"][0]["weights"]["path"]
    assert not (home / "models" / "my_demucs").exists()
    assert w.exists()
    listed = {m["id"]: m for m in registry.model_list()["models"]}
    assert listed["my_demucs"]["tier"] == "byow" and listed["my_demucs"]["state"] == "registered"
    show = registry.model_show("my_demucs")
    assert show["entry"]["weights"]["path"] == "my_model.ckpt"
    assert registry.model_verify("my_demucs")["ok"]
    run = registry.resolve_for_run("my_demucs")
    assert any("unknown" in x for x in run["warnings"])
    # BYOW weights are never downloaded
    with pytest.raises(InputError, match="never downloaded"):
        registry.model_pull("my_demucs")
    w.write_bytes(b"changed")
    assert not registry.model_verify("my_demucs")["ok"]
    out = registry.model_remove("my_demucs")
    assert out["removed"] == "registration" and w.exists()
    assert "my_demucs" not in [m["id"] for m in registry.model_list()["models"]]


def test_byow_register_rules(tmp_path):
    w = tmp_path / "m.bin"
    w.write_bytes(b"abc")
    with pytest.raises(InputError, match="license_weights"):
        registry.model_register(w, id="m1", license_weights="  ")
    with pytest.raises(InputError, match="official"):
        registry.model_register(w, id="scnet_4stem", license_weights="MIT")
    with pytest.raises(InputError):
        registry.model_register(w, id="Bad Id", license_weights="MIT")
    with pytest.raises(InputError):
        registry.model_register(tmp_path / "missing.bin", id="m2", license_weights="MIT")
    registry.model_register(w, id="m1", license_weights="MIT", evidence_url="https://example.invalid/l")
    with pytest.raises(InputError, match="already registered"):
        registry.model_register(w, id="m1", license_weights="MIT")
    assert registry.model_register(w, id="m1", license_weights="Apache-2.0", replace=True)["replaced"]
    assert registry.model_show("m1")["license"]["weights"] == "Apache-2.0"
