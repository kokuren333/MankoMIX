"""Stem separation pipeline and worker contract (SPEC 6.2, 12.2, R-22, S-10, S-11).

The default tests use the worker's ``fake_filter`` backend (complementary FFT
bands, enabled only with MANKOMIX_SEPARATION_FAKE=1) registered as a BYOW
model, so no real model or weights are needed. The real-model test runs only
with MANKOMIX_RUN_SEPARATION=1 and the weights pulled into the user's home.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pytest

from core import api, config, registry
from core.errors import EnvironmentProblem, InputError
from core.hashing import sha256_file
from core.project import Project
from core.separation import pipeline, separate
from tests.fixtures import synth

SR = 48000
BANDS3 = {"bass": [0, 200], "vocals": [200, 4000], "other": [4000, None]}


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    monkeypatch.setenv("MANKOMIX_HOME", str(h))
    monkeypatch.setenv("MANKOMIX_SEPARATION_FAKE", "1")
    config.clear_cache()

    def no_download(url):
        raise AssertionError("separation must never download")
    monkeypatch.setattr(registry, "_open_url", no_download)
    yield h
    config.clear_cache()


def _register_fake(tmp_path, model_id="fake_sep", bands=None, **cfg):
    w = tmp_path / "weights" / f"{model_id}.bin"
    w.parent.mkdir(exist_ok=True)
    w.write_bytes(b"fake weights for " + model_id.encode())
    bands = bands or BANDS3
    registry.model_register(w, id=model_id, license_weights="MIT", usage_restrictions="none",
                            evidence_url="https://example.invalid/license", architecture="fake",
                            stems=list(bands), attribution="fake model for tests",
                            runtime={"backend": "fake_filter", "cpu_ok": True, "light": True,
                                     "sample_rate": 44100, "config": {"bands": bands, **cfg}})
    return w


@pytest.fixture
def project(tmp_path, home):
    stems = synth.song_stems(sr=SR, seconds=8.0, seed=0)
    mix = synth.normalize_peak(synth.stem_sum(stems), -3.0)
    src = tmp_path / "src"
    src.mkdir()
    synth.write_wav(src / "song_mix.wav", mix, SR)
    root = tmp_path / "song.mmx"
    api.init_project(str(root), title="separation test")
    api.import_files(str(root), [str(src / "song_mix.wav")])
    return root


def test_full_separation_adds_assets_tracks_and_records(tmp_path, project):
    w = _register_fake(tmp_path)
    proj = Project.open(project)
    src_id = proj.data["fullmix_asset"]
    src_sha = proj.asset(src_id)["sha256"]
    src_file = proj.asset_path(src_id)

    res = separate(project, model_id="fake_sep", mode="full")

    assert [s["stem"] for s in res["stems"]] == list(BANDS3)
    assert len(res["assets_added"]) == 3 and len(res["tracks_added"]) == 3
    assert res["model_sha256"] == sha256_file(w)
    assert res["postprocess"]["head_offset_samples"] == 0
    assert res["postprocess"]["residual_db"] < -30
    assert sha256_file(src_file) == src_sha                      # S-11: source untouched
    assert str(tmp_path) not in json.dumps(res)

    proj = Project.open(project)
    assert [i for i in proj.validate() if i["level"] == "error"] == []
    assert proj.data["fullmix_asset"] == src_id
    seps = [a for a in proj.data["assets"] if a.get("origin") == "separated"]
    assert {a["role"] for a in seps} == {"bass", "vocals", "other"}
    for a in seps:
        assert a["path"].startswith("assets/separated/")
        assert (project / a["path"]).is_file()
        assert a["sha256"] == sha256_file(project / a["path"])
        assert a["separation"]["model_id"] == "fake_sep"
        assert a["sample_rate"] == SR and a["length_samples"] == proj.asset(src_id)["length_samples"]
    tracks = [t for t in proj.data["tracks"] if t["id"] in res["tracks_added"]]
    for t in tracks:
        assert t["restrictions"]["operations"] == ["balance"] and t["restrictions"]["rule"] == "R-22"
    assert proj.data["objective"]["lead_stem"] in res["tracks_added"]

    rec = proj.data["ingest"]["separations"][-1]
    assert rec["model_id"] == "fake_sep" and rec["tier"] == "byow"
    assert rec["model_sha256"] == res["model_sha256"]
    assert rec["license"]["weights"] == "MIT" and rec["attribution"] == "fake model for tests"
    assert rec["source_sha256"] == src_sha and rec["mode"] == "full"
    assert pipeline.separation_records(project)[-1]["id"] == res["separation"]

    # stems add back up to the source (complementary bands)
    x, _ = synth.read_wav(src_file)
    total = sum(synth.read_wav(project / a["path"])[0] for a in seps)
    err = np.sqrt(np.mean((x - total) ** 2)) / np.sqrt(np.mean(x ** 2))
    assert 20 * np.log10(err) < -30

    # temp working copies are gone
    assert not list((project / "cache").glob("separation_*"))


def test_preview_is_an_excerpt_without_tracks(tmp_path, project):
    _register_fake(tmp_path)
    res = separate(project, model_id="fake_sep", mode="preview", excerpt_s=2.0, stems=["vocals"])
    assert res["excerpt"]["length"] == 2 * SR
    assert res["tracks_added"] == [] and len(res["assets_added"]) == 1
    proj = Project.open(project)
    a = proj.asset(res["assets_added"][0])
    assert a["length_samples"] == 2 * SR and a["origin"] == "separated"
    assert a["separation"]["source_start"] == res["excerpt"]["start"]
    assert res["postprocess"]["head_offset_samples"] is None    # subset of stems: no sum check


def test_head_offset_is_detected_and_fixed(tmp_path, project):
    _register_fake(tmp_path, delay_samples=200)
    res = separate(project, model_id="fake_sep", mode="full", add_tracks=False)
    lag = res["postprocess"]["head_offset_samples"]
    assert abs(lag - round(200 * SR / 44100)) <= 2
    assert res["postprocess"]["head_offset_fixed"]
    assert any("samples off" in w for w in res["warnings"])
    assert res["postprocess"]["residual_db"] < -20


def test_more_than_four_stems_warns(tmp_path, project):
    bands = {"bass": [0, 150], "drums": [150, 400], "vocals": [400, 2000], "guitar": [2000, 5000],
             "other": [5000, None]}
    _register_fake(tmp_path, "fake5", bands=bands)
    res = separate(project, model_id="fake5", mode="preview", excerpt_s=1.0)
    assert any("4 stems" in w for w in res["warnings"])


def test_input_errors(tmp_path, project):
    _register_fake(tmp_path)
    with pytest.raises(InputError):
        separate(project, model_id="fake_sep", mode="sideways")
    with pytest.raises(InputError):
        separate(project, model_id="fake_sep", stems=["piano"])
    with pytest.raises(InputError):
        separate(project, model_id="no_such_model")
    with pytest.raises(InputError):
        separate(project, model_id="fake_sep", source_asset="ast_missing")
    # candidates need an explicit flag; official weights are never fetched implicitly
    with pytest.raises(InputError, match="candidate"):
        separate(project, model_id="uvr_mdx_net_inst_hq_3")
    with pytest.raises(EnvironmentProblem, match="model pull"):
        separate(project, model_id="scnet_4stem")
    proj = Project.open(project)
    assert not [a for a in proj.data["assets"] if a.get("origin") == "separated"]


def test_worker_contract(tmp_path, home):
    sr = 44100
    t = np.arange(sr) / sr
    x = np.stack([np.sin(2 * np.pi * 100 * t), np.sin(2 * np.pi * 1000 * t)], axis=1) * 0.3
    work = tmp_path / "work"
    synth.write_wav(work / "in.wav", x, sr)
    req = {"protocol": 1, "backend": "fake_filter", "architecture": "fake",
           "config": {"bands": {"low": [0, 500], "high": [500, None]}}, "weights": {}, "roles": {},
           "input": str(work / "in.wav"), "output_dir": str(work / "out"), "device": "cpu"}
    res = pipeline.run_worker(req, work)
    assert res["ok"] and res["stems"] == {"low": "low.wav", "high": "high.wav"} and res["sample_rate"] == sr
    low, _ = synth.read_wav(work / "out" / "low.wav")
    assert np.max(np.abs(low[:, 1])) < 0.01 and np.max(np.abs(low[:, 0])) > 0.25
    with pytest.raises(InputError, match="unknown backend"):
        pipeline.run_worker(dict(req, backend="nope", output_dir=str(work / "o2")), work)
    with pytest.raises(InputError, match="weights file missing"):
        pipeline.run_worker(dict(req, weights={"w.bin": str(work / "nope.bin")}, output_dir=str(work / "o3")), work)


def test_fake_backend_needs_test_switch(tmp_path, home, monkeypatch):
    monkeypatch.delenv("MANKOMIX_SEPARATION_FAKE")
    work = tmp_path / "w"
    synth.write_wav(work / "in.wav", np.zeros((100, 2)), 44100)
    req = {"protocol": 1, "backend": "fake_filter", "config": {}, "weights": {}, "roles": {},
           "input": str(work / "in.wav"), "output_dir": str(work / "out"), "device": "cpu"}
    with pytest.raises(InputError, match="MANKOMIX_SEPARATION_FAKE"):
        pipeline.run_worker(req, work)


def test_core_process_does_not_load_model_code():
    # importing the pipeline must not pull torch / librosa / soxr into the core process
    import subprocess
    code = ("import sys; import core.separation.pipeline, core.registry; "
            "bad=[m for m in ('torch','librosa','soxr','openunmix') if m in sys.modules]; print(bad)")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         cwd=str(Path(__file__).resolve().parent.parent))
    assert out.stdout.strip() == "[]", out.stderr


@pytest.mark.slow
@pytest.mark.skipif(os.environ.get("MANKOMIX_RUN_SEPARATION") != "1",
                    reason="set MANKOMIX_RUN_SEPARATION=1 (weights pulled into MANKOMIX_HOME) to run")
def test_real_model_preview(tmp_path):
    config.clear_cache()
    model = os.environ.get("MANKOMIX_SEPARATION_MODEL", "scnet_4stem")
    stems = synth.song_stems(sr=44100, seconds=12.0, seed=0)
    mix = synth.normalize_peak(synth.stem_sum(stems), -3.0)
    synth.write_wav(tmp_path / "mix.wav", mix, 44100)
    root = tmp_path / "real.mmx"
    api.init_project(str(root), title="real separation")
    api.import_files(str(root), [str(tmp_path / "mix.wav")])
    res = separate(root, model_id=model, mode="preview", excerpt_s=10.0)
    assert len(res["assets_added"]) == len(registry.model_show(model)["stems"])
    assert res["postprocess"]["head_offset_samples"] == 0
