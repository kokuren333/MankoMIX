"""License audit (docs/SPEC.md 13.4, 16.4): tools/license_audit.py.

The audit itself must pass on the test environment; injected GPL / unknown
metadata, rejected imports, a non-allowlisted npm license and an incomplete
third_party/ folder must fail; the generated files must be deterministic.
"""

from __future__ import annotations

import email.message
import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("license_audit", REPO / "tools" / "license_audit.py")
la = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(la)

MIT_TEXT = ("MIT License\n\nCopyright (c) 2024 Someone\n\nPermission is hereby granted, free of charge, to any "
            "person obtaining a copy of this software ...\n")


class FakeDist:
    def __init__(self, name: str, requires: list[str] | None = None, **fields):
        self.metadata = email.message.Message()
        self.metadata["Name"] = name
        for key, value in fields.items():
            key = key.replace("_", "-")
            for v in value if isinstance(value, list) else [value]:
                self.metadata[key] = v
        self.requires = requires or []
        self.files = []
        self.version = "0.0.0"


def _patch(monkeypatch, fakes: dict[str, object | None]) -> None:
    real = la.find_distribution

    def lookup(name: str):
        key = la.norm_name(name)
        return fakes[key] if key in fakes else real(name)

    monkeypatch.setattr(la, "find_distribution", lookup)


@pytest.fixture(scope="module")
def baseline():
    return la.run_audit(la.ROOT)


# --- whole audit ----------------------------------------------------------------------------

def test_audit_passes_on_current_environment(baseline):
    assert baseline["violations"] == []
    core = {p["name"] for p in baseline["python"]["scopes"][0]["packages"]}
    assert {"numpy", "scipy", "soundfile", "jsonschema"} <= core
    for banned in ("librosa", "soxr", "torch", "onnxruntime", "openunmix", "audio-separator", "pedalboard"):
        assert banned not in core


def test_generated_files_are_deterministic(baseline):
    first = la.render_all(baseline)
    second = la.render_all(la.run_audit(la.ROOT))
    assert first == second
    assert set(first) == {la.REPORT_MD, la.PYTHON_JSON, la.NPM_JSON}
    for rel, text in first.items():
        assert text.endswith("\n") and "\r" not in text
        assert str(REPO) not in text and REPO.as_posix() not in text
        if rel.endswith(".json"):
            json.loads(text)


def test_output_does_not_depend_on_what_is_installed(monkeypatch, baseline):
    """Packages missing here (other platform, optional extra) keep the committed records."""
    files = la.render_all(baseline)
    committed = json.loads(files[la.PYTHON_JSON])
    monkeypatch.setattr(la, "_carried_records", lambda root: {
        p["name"]: p for s in committed["scopes"] for p in s["packages"] if p["status"] != la.UNVERIFIED})
    hidden = {"colorama", "pytest", "torch", "onnxruntime", "openunmix", "typing-extensions"}
    _patch(monkeypatch, {n: None for n in hidden})
    assert la.render_all(la.run_audit(la.ROOT)) == files


def test_check_mode_detects_drift(tmp_path, baseline):
    files = la.render_all(baseline)
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text, encoding="utf-8", newline="\n")
    assert la._drift(tmp_path, files) == []
    md_path = tmp_path / la.REPORT_MD
    md_path.write_text(md_path.read_text(encoding="utf-8") + "edited\n", encoding="utf-8", newline="\n")
    drift = la._drift(tmp_path, files)
    assert drift and drift[0].startswith(la.REPORT_MD)


# --- Python packages ----------------------------------------------------------------------------

def test_fake_gpl_distribution_fails(monkeypatch):
    _patch(monkeypatch, {"soundfile": FakeDist("soundfile", ["numpy", "cffi>=1.0"],
                                               License_Expression="GPL-3.0-or-later")})
    result = la.run_audit(la.ROOT)
    hits = [v for v in result["violations"] if "python core: soundfile" in v]
    assert hits and "GPL-3.0-or-later" in hits[0]


def test_lgpl_classifier_in_core_fails(monkeypatch):
    _patch(monkeypatch, {"jsonschema": FakeDist(
        "jsonschema", ["attrs"], Classifier=["License :: OSI Approved :: GNU Lesser General Public License v3 (LGPLv3)"])})
    result = la.run_audit(la.ROOT)
    assert any("python core: jsonschema" in v and "LGPL" in v for v in result["violations"])


def test_unknown_license_fails_unless_reviewed(monkeypatch):
    _patch(monkeypatch, {"attrs": FakeDist("attrs")})
    result = la.run_audit(la.ROOT)
    assert any("python core: attrs [UNKNOWN]" in v for v in result["violations"])

    node = {"installed": True, "required_by": {"jsonschema"}, "requires": set()}
    reviewed = {"python": {"attrs": {"license": "MIT", "reason": "LICENSE file read", "evidence": ["https://example.org"]}},
                "npm": {}, "native": {}}
    entry = la.audit_package("attrs", node, "core", {}, reviewed, set())
    assert entry["status"] == la.FLAG and entry["license"] == "MIT"
    # An exception can never accept a copyleft license.
    reviewed["python"]["attrs"]["license"] = "GPL-2.0-only"
    assert la.audit_package("attrs", node, "core", {}, reviewed, set())["status"] == la.FAIL


def test_rejected_dependency_in_core_closure_fails(monkeypatch):
    _patch(monkeypatch, {
        "scipy": FakeDist("scipy", ["numpy", "librosa"], License_Expression="BSD-3-Clause"),
        "librosa": FakeDist("librosa", [], License_Expression="ISC"),
    })
    result = la.run_audit(la.ROOT)
    assert any("python core: librosa" in v and "D-057" in v for v in result["violations"])


def test_mpl_is_flagged_not_failed():
    assert la.evaluate(la.normalise("MPL-2.0 AND MIT")) == (la.FLAG, "weak copyleft, allowed unmodified")


@pytest.mark.parametrize("expr,status", [
    ("MIT", la.OK),
    ("MIT OR GPL-3.0-only", la.OK),
    ("MIT AND GPL-3.0-only", la.FAIL),
    ("Apache-2.0 WITH LLVM-exception", la.OK),
    ("GPL-3.0-or-later WITH GCC-exception-3.1", la.OK),
    ("BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0", la.OK),
    ("LGPL-2.1-or-later", la.FAIL),
    ("AGPL-3.0-only", la.FAIL),
    ("BlueOak-1.0.0", la.FAIL),
    ("Apache 2.0", la.OK),
    ("3-Clause BSD License", la.OK),
])
def test_expression_policy(expr, status):
    tree = la.normalise(expr)
    assert tree is not None
    assert la.evaluate(tree)[0] == status


def test_unspecified_bsd_is_resolved_from_the_license_file(tmp_path):
    lic = tmp_path / "pkg-1.0.dist-info" / "LICENSE"
    lic.parent.mkdir()
    lic.write_text("Redistribution and use in source and binary forms ... Neither the name of the copyright "
                   "holder nor the names of its contributors may be used to endorse ...", encoding="utf-8")
    dist = FakeDist("pkg", Classifier=["License :: OSI Approved :: BSD License"])
    dist.files = [Path("pkg-1.0.dist-info/LICENSE")]
    dist.locate_file = lambda f: tmp_path / f
    assert la.expression_text(la.license_of(dist)) == "BSD-3-Clause"
    dist.files = []
    assert la.evaluate(la.license_of(dist))[0] == la.FAIL  # BSD variant unknown


def test_markers_cover_every_target_platform():
    assert la.marker_possible('sys_platform == "win32"')
    assert la.marker_possible('platform_system == "Linux" and platform_machine == "x86_64"')
    assert la.marker_possible("python_version < '3.13'")
    assert not la.marker_possible('python_version < "3.11"')
    assert not la.marker_possible('extra == "dev"')
    assert la.marker_possible('extra == "dev"', ("dev",))


# --- import boundary ----------------------------------------------------------------------------

def test_import_scan_rejects_forbidden_modules(tmp_path):
    (tmp_path / "core" / "separation").mkdir(parents=True)
    (tmp_path / "core" / "analysis.py").write_text("import numpy\n\ndef f():\n    import librosa\n", encoding="utf-8")
    (tmp_path / "core" / "infer.py").write_text("from torch import nn\n", encoding="utf-8")
    (tmp_path / "core" / "bridge.py").write_text("from .separation import archs\n", encoding="utf-8")
    (tmp_path / "core" / "separation" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "core" / "separation" / "worker.py").write_text("import torch\n", encoding="utf-8")
    (tmp_path / "core" / "separation" / "archs.py").write_text("import openunmix\nimport soxr\n", encoding="utf-8")
    scan = la.scan_imports(tmp_path, ("core",))
    found = {(f["file"], f["module"]) for f in scan["findings"]}
    assert ("core/analysis.py", "librosa") in found
    assert ("core/infer.py", "torch") in found
    assert ("core/bridge.py", "core.separation.archs") in found
    assert ("core/separation/archs.py", "soxr") in found  # soxr is banned even in the worker
    assert {"file": "core/separation/worker.py", "module": "torch"} in scan["worker_imports"]
    assert not any(f["file"] == "core/separation/worker.py" for f in scan["findings"])


def test_repository_import_boundary_holds(baseline):
    assert baseline["imports"]["findings"] == []


# --- npm ----------------------------------------------------------------------------------------

def test_npm_blueoak_and_missing_license_fail(tmp_path):
    (tmp_path / "gui").mkdir()
    lock = {"lockfileVersion": 3, "packages": {
        "": {"name": "x"},
        "node_modules/react": {"version": "1.0.0", "license": "MIT"},
        "node_modules/jsdom-dep": {"version": "2.0.0", "license": "BlueOak-1.0.0", "dev": True},
        "node_modules/mystery": {"version": "3.0.0", "dev": True},
        "node_modules/cc0": {"version": "1.0.0", "license": "CC0-1.0", "dev": True},
    }}
    (tmp_path / "gui" / "package-lock.json").write_text(json.dumps(lock), encoding="utf-8")
    res = la.audit_npm(tmp_path, {"python": {}, "npm": {}, "native": {}}, set())
    by = {p["name"]: p for p in res["packages"]}
    assert by["react"]["scope"] == "runtime" and by["react"]["status"] == la.OK
    assert by["jsdom-dep"]["scope"] == "dev" and by["jsdom-dep"]["status"] == la.FAIL
    assert by["mystery"]["status"] == la.FAIL
    assert by["cc0"]["status"] == la.OK


def test_gui_lockfile_passes(baseline):
    pk = baseline["npm"]["packages"]
    assert pk and all(p["status"] == la.OK for p in pk)
    assert {p["scope"] for p in pk} == {"runtime", "dev"}


# --- third_party ------------------------------------------------------------------------------

def _third_party(tmp_path: Path, origin: bool = True, license_text: str = MIT_TEXT) -> Path:
    d = tmp_path / "third_party" / "foo"
    d.mkdir(parents=True)
    (tmp_path / "third_party" / "README.md").write_text("| `foo/` | Foo | MIT |\n", encoding="utf-8")
    (d / "LICENSE").write_text(license_text, encoding="utf-8")
    if origin:
        (d / "ORIGIN.md").write_text("Source: https://example.org/foo\n", encoding="utf-8")
    return tmp_path


def test_third_party_complete_folder_passes(tmp_path):
    items = la.audit_third_party(_third_party(tmp_path))
    assert items == [{"folder": "third_party/foo", "license": "MIT", "status": la.OK, "note": ""}]


def test_third_party_missing_origin_fails(tmp_path):
    items = la.audit_third_party(_third_party(tmp_path, origin=False))
    assert items[0]["status"] == la.FAIL and "ORIGIN.md is missing" in items[0]["note"]


def test_third_party_gpl_text_fails(tmp_path):
    items = la.audit_third_party(_third_party(tmp_path, license_text="GNU GENERAL PUBLIC LICENSE\nVersion 3\n"))
    assert items[0]["status"] == la.FAIL


def test_repository_third_party_and_registry_pass(baseline):
    assert baseline["third_party"] and all(t["status"] == la.OK for t in baseline["third_party"])
    assert not [i for i in baseline["registry"]["issues"] if i["level"] == "error"]
    assert baseline["ffmpeg"] == []


def test_exceptions_file_requires_reason_and_https_evidence(tmp_path):
    (tmp_path / "licenses").mkdir()
    (tmp_path / la.EXCEPTIONS_JSON).write_text(json.dumps({"python": [
        {"name": "a", "license": "MIT", "reason": "read", "evidence": ["http://insecure.example.org"]},
        {"name": "b", "license": "MIT", "evidence": ["https://example.org"]},
        {"name": "c", "license": "MIT", "reason": "read", "evidence": ["https://example.org"]},
    ]}), encoding="utf-8")
    exceptions, problems = la.load_exceptions(tmp_path)
    assert list(exceptions["python"]) == ["c"]
    assert len(problems) == 2
