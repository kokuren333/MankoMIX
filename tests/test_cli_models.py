"""CLI and MCP faces of the model registry and stem separation (SPEC 6.2, 10, 12; M6).

Everything runs with MANKOMIX_HOME in a temporary folder and with downloads
disabled. Separation uses the worker's ``fake_filter`` backend registered as a
BYOW model (enabled with MANKOMIX_SEPARATION_FAKE=1, the same approach as
tests/test_separation.py); no real model or weights are needed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mankomix.cli import main as cli_main
from mankomix.core import api, config, registry
from mankomix.core.errors import EXIT_ENV_ERROR, EXIT_INPUT_ERROR, EXIT_OK
from mankomix.core.hashing import sha256_file
from mankomix.mcp.tools import Toolbox
from mankomix.mcp.workspace import Workspace

from tests.fixtures import synth
from tests.test_cli import assert_no_abs

SR = 48000
BANDS = {"bass": [0, 200], "vocals": [200, 4000], "other": [4000, None]}
FAKE_RUNTIME = {"backend": "fake_filter", "cpu_ok": True, "light": True, "sample_rate": 44100,
                "config": {"bands": BANDS}}


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    monkeypatch.setenv("MANKOMIX_HOME", str(h))
    monkeypatch.setenv("MANKOMIX_SEPARATION_FAKE", "1")
    config.clear_cache()

    def no_download(url):
        raise AssertionError("tests must never download")
    monkeypatch.setattr(registry, "_open_url", no_download)
    yield h
    config.clear_cache()


@pytest.fixture
def cli(capsys, tmp_path):
    def run(*argv, expect: int | None = EXIT_OK):
        code = cli_main.main([str(a) for a in argv])
        out = capsys.readouterr().out
        assert_no_abs(out, tmp_path)
        res = json.loads(out)
        if expect is not None:
            assert code == expect, res
        return res
    return run


@pytest.fixture
def weights(tmp_path) -> Path:
    w = tmp_path / "weights" / "fake_sep.bin"
    w.parent.mkdir()
    w.write_bytes(b"fake weights for the cli tests")
    return w


def _register(cli, weights: Path, model_id: str = "fake_sep", *extra):
    return cli("model", "register", weights, "--id", model_id, "--license-weights", "MIT",
               "--usage-restrictions", "none", "--evidence-url", "https://example.invalid/license",
               "--architecture", "fake", "--stems", ",".join(BANDS), "--attribution", "fake model for tests",
               "--runtime", json.dumps(FAKE_RUNTIME), *extra)


@pytest.fixture
def project(tmp_path) -> Path:
    stems = synth.song_stems(sr=SR, seconds=6.0, seed=1)
    mix = synth.normalize_peak(synth.stem_sum(stems), -3.0)
    src = tmp_path / "src"
    src.mkdir()
    synth.write_wav(src / "song_mix.wav", mix, SR)
    root = tmp_path / "song.mmx"
    api.init_project(str(root), title="cli separation")
    api.import_files(str(root), [str(src / "song_mix.wav")])
    return root


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------

def test_model_list_and_show(cli):
    r = cli("model", "list")
    official = [m for m in r["models"] if m["tier"] == "official"]
    assert official and r["byow_notice"] and r["defaults"]
    for m in official:
        assert m["installed"] is False and m["state"] == "not_installed"      # empty MANKOMIX_HOME
        assert m["license"]["weights"] and isinstance(m["license"]["evidence"], list)
    mid = official[0]["id"]
    s = cli("model", "show", mid)
    assert s["id"] == mid and s["files"] and all(f["present"] is False for f in s["files"])
    assert s["license"]["evidence"]
    err = cli("model", "show", "no_such_model", expect=EXIT_INPUT_ERROR)
    assert err["error"] == "input_error" and "unknown model" in err["message"]


def test_model_pull_refuses_unknown_and_candidates(cli):
    err = cli("model", "pull", "no_such_model", expect=EXIT_INPUT_ERROR)
    assert "unknown model" in err["message"]
    cands = [m["id"] for m in cli("model", "list")["models"] if m["tier"] == "official" and m["status"] != "verified"]
    if cands:
        err = cli("model", "pull", cands[0], expect=EXIT_INPUT_ERROR)
        assert "not pulled" in err["message"] or "restrictions" in err["message"]


def test_model_register_verify_remove(cli, weights):
    r = _register(cli, weights)
    assert r["tier"] == "byow" and r["sha256"] == sha256_file(weights) and r["file"] == weights.name
    assert r["notice"]
    listed = {m["id"]: m for m in cli("model", "list")["models"]}
    assert listed["fake_sep"]["installed"] is True and listed["fake_sep"]["tier"] == "byow"
    assert cli("model", "verify", "fake_sep")["ok"] is True
    shown = cli("model", "show", "fake_sep")
    assert shown["entry"]["weights"]["path"] == weights.name           # no absolute path

    err = cli("model", "register", weights, "--id", "fake_sep", "--license-weights", "MIT", expect=EXIT_INPUT_ERROR)
    assert "already registered" in err["message"]
    assert _register(cli, weights, "fake_sep", "--replace")["replaced"] is True
    bad = cli("model", "register", weights, "--id", "x", "--license-weights", "MIT", "--runtime", "[1]",
              expect=EXIT_INPUT_ERROR)
    assert "--runtime" in bad["message"]

    doc = cli("doctor", expect=None)
    assert doc["models"]["byow"] == 1 and doc["models"]["byow_available"] == ["fake_sep"]

    rm = cli("model", "remove", "fake_sep")
    assert rm["removed"] == "registration" and weights.is_file()
    assert "fake_sep" not in {m["id"] for m in cli("model", "list")["models"]}
    assert cli("model", "pull", "fake_sep", expect=EXIT_INPUT_ERROR)["error"] == "input_error"


# ---------------------------------------------------------------------------
# separation
# ---------------------------------------------------------------------------

def test_separate_preview_with_fake_worker(cli, weights, project):
    _register(cli, weights)
    res = cli("-p", project, "separate", "--model", "fake_sep", "--excerpt-s", "2", "--stems", "vocals,bass")
    assert res["mode"] == "preview" and res["model_id"] == "fake_sep"
    assert len(res["assets_added"]) == 2 and res["tracks_added"] == []
    assert res["excerpt"]["length"] == 2 * SR and res["license"]["weights"] == "MIT"
    journal = [json.loads(x) for x in (project / "journal.jsonl").read_text(encoding="utf-8").splitlines() if x]
    assert journal[-1]["op"] == "separate" and journal[-1]["actor"] == "human"

    recs = cli("-p", project, "separate", "--records")
    assert recs["count"] == 1 and recs["separations"][0]["model_id"] == "fake_sep"

    err = cli("-p", project, "separate", "--model", "fake_sep", "--stems", "piano", expect=EXIT_INPUT_ERROR)
    assert "does not produce" in err["message"]


def test_separate_default_model_not_downloaded(cli, project):
    # the default preview model is official but its weights are not in the empty home: never downloaded
    err = cli("-p", project, "separate", expect=EXIT_ENV_ERROR)
    assert err["error"] == "environment_error" and "model pull" in err["message"]


def test_mcp_model_and_separate_tools(tmp_path, weights, project):
    ws_root = tmp_path
    tb = Toolbox(Workspace(ws_root))
    names = set(tb.names())
    assert {"model_list", "model_get", "model_pull", "model_register", "model_verify", "model_remove",
            "separate_run", "separate_list"} <= names
    assert "async" in tb.tools["separate_run"].input_schema["properties"]
    assert "async" in tb.tools["model_pull"].input_schema["properties"]

    payload, err = tb.call("model_pull", {"id": "no_such_model"})
    assert err and payload["error"] == "input_error"
    payload, err = tb.call("model_register", {"path": "weights/fake_sep.bin", "id": "fake_sep",
                                              "license_weights": "MIT", "usage_restrictions": "none",
                                              "stems": list(BANDS), "runtime": FAKE_RUNTIME})
    assert not err and payload["tier"] == "byow", payload
    payload, err = tb.call("model_register", {"path": "../outside.bin", "id": "x", "license_weights": "MIT"})
    assert err and payload["error"] == "path_outside_workspace"

    listed, err = tb.call("model_list", {})
    assert not err and any(m["id"] == "fake_sep" and m["installed"] for m in listed["models"])

    job, err = tb.call("separate_run", {"project": "song.mmx", "model": "fake_sep", "excerpt_s": 2.0,
                                        "stems": ["vocals"], "async": True})
    assert not err and job["job_id"]
    done = tb.jobs.wait(job["job_id"], timeout=120)
    assert done.state == "succeeded", done.error
    out, err = tb.call("job_result", {"job_id": job["job_id"]})
    assert not err and out["result"]["model_id"] == "fake_sep" and len(out["result"]["assets_added"]) == 1
    journal = [json.loads(x) for x in (project / "journal.jsonl").read_text(encoding="utf-8").splitlines() if x]
    assert journal[-1]["op"] == "separate" and journal[-1]["actor"] == "agent"
    recs, err = tb.call("separate_list", {"project": "song.mmx"})
    assert not err and recs["count"] == 1
