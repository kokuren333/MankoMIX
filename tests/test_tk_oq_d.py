"""OQ_D: reproduce project fallback loss and evaluate the additive candidate.

The production fix is withheld: C11 currently requires the lossy behavior.
Candidate-only tests extend the allowlist locally, without replacing rendering.
"""
import copy
import hashlib
import json

import numpy as np
import pytest

from mankomix.core import mixrender as mr
from mankomix.core.errors import ValidationError
from mankomix.core.project import Project
from mankomix.dsp import engine as E, native_backend
from tests.test_mixrender import _project
from tests.test_render_cache import proj as fixture_project


@pytest.fixture(autouse=True)
def isolated_render(tmp_path, monkeypatch):
    monkeypatch.setenv("MANKOMIX_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("MANKOMIX_RENDER_CACHE_MB", "0")
    mr.clear_track_cache()
    yield
    mr.clear_track_cache()


def _keys(monkeypatch, candidate):
    original = tuple(k for k in mr._ENGINE_KEYS if k != "fallback")
    monkeypatch.setattr(mr, "_ENGINE_KEYS", original + (("fallback",) if candidate else ()))


@pytest.mark.parametrize("fallback", [
    "saturator", {"type": "gain", "params": {"gain_db": -6.0}},
])
@pytest.mark.parametrize("candidate", [False, True], ids=["original", "candidate"])
def test_missing_backend_project_track_vs_direct_engine(tmp_path, monkeypatch, fallback, candidate):
    # Only backend availability is faked; processor implementations stay real.
    monkeypatch.setattr(native_backend, "available", lambda: False)
    monkeypatch.setattr(native_backend, "has_smoother", lambda: False)
    monkeypatch.setattr(native_backend, "load_error", lambda: "OQ_D forced unavailable")
    _keys(monkeypatch, candidate)
    x = np.random.Generator(np.random.PCG64(30)).normal(0, .05, (2048, 2))
    project = _project(tmp_path, {"synth.wav": (x, 48000)})
    chain = [{"id": "prc_oq_d", "type": "aw.purest_drive", "params": {"drive": .4},
              "backend": "native", "fallback": fallback, "reason": "OQ_D contract probe"}]
    project.set("/tracks/0/chain", chain, actor="human")
    project = Project.open(project.root)
    tid = project.data["tracks"][0]["id"]
    chain = project.data["tracks"][0]["chain"]
    assert chain[0]["fallback"] == fallback  # Persisted project schema accepts it.
    raw, sr, _ = mr.render_track(project, tid, apply_chain=False)
    direct_chain = [{k: copy.deepcopy(v) for k, v in chain[0].items() if k != "reason"}]
    direct = E.render_chain(raw, sr, direct_chain, stage="track", seed=30)
    fb = direct.steps[0]["fallback"]
    assert direct.steps[0]["backend"] == "reference"
    assert fb["reason"] and fb["mapping"] and fb["type"]
    expected = E.render_chain(raw, sr, [{"type": fb["type"], "params": fb["params"]}],
                              stage="track", seed=30)
    assert direct.audio.tobytes() == expected.audio.tobytes()
    warning = next(w for w in direct.warnings if "rendered with fallback" in w)
    assert "(approximation)" in warning
    if not candidate:
        assert "fallback" not in mr.engine_chain(chain)[0]
        with pytest.raises(ValidationError, match="no available backend") as exc:
            mr.render_track(project, tid, seed=30)
        assert exc.value.details["rule"] == "backend"
        assert exc.value.details["step"] == "prc_oq_d"
        return
    assert mr.engine_chain(chain)[0]["fallback"] == fallback
    rendered, rate, record = mr.render_track(project, tid, seed=30)
    assert rate == sr and rendered.tobytes() == direct.audio.tobytes()
    assert warning in record["warnings"]
    assert record["chain"][0]["backend"] == "reference"
    # Detailed fallback step serialization is OQ_B's separate responsibility.


def test_current_production_allowlist_preserves_declaration_and_renders(tmp_path, monkeypatch):
    assert mr.engine_chain([
        {"type": "aw.purest_drive", "fallback": "saturator"}
    ])[0]["fallback"] == "saturator"
    test_missing_backend_project_track_vs_direct_engine(tmp_path, monkeypatch, "saturator", True)


@pytest.mark.parametrize("fallback", ["saturator", {"type": "gain", "params": {"gain_db": -6}}])
def test_candidate_preserves_declaration_without_aliasing(monkeypatch, fallback):
    _keys(monkeypatch, True)
    chain = [{"type": "aw.purest_drive", "fallback": fallback, "reason": "probe"}]
    converted = mr.engine_chain(chain)
    assert converted[0]["fallback"] == fallback and "reason" not in converted[0]
    if isinstance(fallback, dict):
        converted[0]["fallback"]["params"]["gain_db"] = -12
        assert chain[0]["fallback"]["params"]["gain_db"] == -6
    E.validate_chain(mr.engine_chain(chain), "track")


def _render_bytes(project, kind):
    mr.clear_track_cache()  # A reused cached output must not mask execution.
    if kind == "track":
        audio, sr, record = mr.render_track(project, "trk_drums", seed=30)
    else:
        audio, sr, record = mr.render_mix(project, seed=30)
    assert record["chain"] if kind == "track" else record["tracks"]
    return audio.tobytes(), sr, json.dumps(record, ensure_ascii=False, allow_nan=False).encode("utf-8")


@pytest.mark.parametrize("kind", ["track", "mix"])
@pytest.mark.parametrize("declared", [False, True], ids=["existing-fixture", "available-with-fallback"])
def test_candidate_keeps_available_fixture_audio_and_full_record_bytes(
        fixture_project, monkeypatch, kind, declared):
    # Reuse the existing multirate/cache fixture, including its real DSP chains.
    if declared:
        # No existing sample project declares fallback. This extra probe declares
        # it on an available reference processor, so no substitute should run.
        for track in fixture_project.data["tracks"]:
            track["chain"][0]["fallback"] = {"type": "gain", "params": {"gain_db": -6}}
        fixture_project.save(actor="human", op="patch", reason="OQ_D available backend probe")
    _keys(monkeypatch, False)
    before = _render_bytes(fixture_project, kind)
    _keys(monkeypatch, True)
    after = _render_bytes(fixture_project, kind)
    assert before == after
    assert "rendered with fallback" not in after[2].decode("utf-8")
    hashes = [hashlib.sha256(part).hexdigest() for part in (after[0], after[2])]
    print(f"OQ_D {kind} declared={declared}: audio={hashes[0]} record={hashes[1]} before==after")
