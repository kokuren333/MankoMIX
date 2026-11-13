"""Native backend wiring in the engine (SPEC 3.2, 9.6): aw.* processors, recording, fallbacks."""

from __future__ import annotations

import numpy as np
import pytest

from mankomix.dsp import engine, native_backend, native_wiring
from mankomix.dsp import processors as P
from mankomix.dsp.errors import ChainError, DSPError

SR = 48000
AW_TYPES = ["aw.purest_drive", "aw.clip_only2", "aw.console7_channel", "aw.console7_buss", "aw.pressure4"]

needs_native = pytest.mark.skipif(not native_backend.available(),
                                  reason=f"native library unavailable: {native_backend.load_error()}")


def _noise(seconds=0.5, amp=0.2, ch=2, seed=3):
    return np.random.default_rng(seed).standard_normal((int(SR * seconds), ch)) * amp


@pytest.fixture
def no_native(monkeypatch):
    """Make the native library look unavailable for the engine."""
    monkeypatch.setattr(native_backend, "available", lambda: False)
    monkeypatch.setattr(native_backend, "has_smoother", lambda: False)
    monkeypatch.setattr(native_backend, "load_error", lambda: "forced unavailable by the test")


# --------------------------------------------------------------------------- definitions

def test_aw_definitions_are_native_only_with_fallbacks():
    assert set(native_wiring.native_types()) == set(AW_TYPES)
    slots = {"aw.purest_drive": 3, "aw.clip_only2": 5, "aw.console7_channel": 3,
             "aw.console7_buss": 3, "aw.pressure4": 2}
    for t in AW_TYPES:
        d = P.describe(t)
        assert d["backends"] == ["native"] and d["implemented"] is True
        assert d["master_slot"] == slots[t]
        assert d["native"]["origin"]["license"] == "MIT"
        ft, fp, _ = native_wiring.fallback_params(t, P.validate_params(t, {}))
        assert ft == d["fallback"]["type"] and "reference" in P.PROCESSORS[ft]["backends"]
        assert fp == P.validate_params(ft, fp)
    for t in ("compressor", "dynamic_eq", "deesser"):
        assert P.describe(t)["backends"] == ["reference", "native"]


@needs_native
def test_aw_params_mirror_the_native_json():
    for t in AW_TYPES:
        info = native_backend.processor_info(P.PROCESSORS[t]["native"]["id"])
        mine = {s["id"]: s for s in P.PROCESSORS[t]["params"]}
        assert set(mine) == {q["id"] for q in info["params"]}, t
        for q in info["params"]:
            s = mine[q["id"]]
            assert (s["min"], s["max"], s["default"], s["unit"]) == \
                (q["min"], q["max"], q["default"], q["unit"]), (t, q["id"])
        assert P.PROCESSORS[t]["realtime"]["latency_samples"] == info["realtime"]["latency_samples"]
        assert P.PROCESSORS[t]["abstract_type"] == info["type"]


# --------------------------------------------------------------------------- native rendering

@needs_native
def test_aw_steps_render_through_native_and_are_recorded():
    x = _noise()
    chain = [
        {"id": "p4", "type": "aw.pressure4", "params": {"pressure": 0.4}},
        {"id": "drive", "type": "aw.purest_drive", "params": {"drive": 0.6}},
        {"id": "c7ch", "type": "aw.console7_channel"},
        {"id": "c7bus", "type": "aw.console7_buss"},
        {"id": "clip", "type": "aw.clip_only2", "params": {"ceiling_db": -1.0}},
        {"id": "lim", "type": "limiter", "params": {"ceiling_dbtp": -1.0}},
    ]
    res = engine.render_chain(x, SR, chain, stage="master")
    assert [s["backend"] for s in res.steps] == ["native"] * 5 + ["reference"]
    assert "native" in res.backends
    vi = res.backends["native"]
    assert vi["backend"] == "native" and len(vi["library_sha256"]) == 64
    assert "/" not in vi["library_file"] and "\\" not in vi["library_file"]
    assert not any("fallback" in w for w in res.warnings)
    st = {s["id"]: s["stats"] for s in res.steps}
    assert st["drive"]["harmonics"]["dominant"] in ("odd", "even", "mixed")
    assert st["clip"]["latency_samples"] == 1 and st["clip"]["latency_compensated"] is True
    assert st["p4"]["crest_factor"]["change_db"] is not None      # measured, not assumed
    assert all("fallback" not in s for s in res.steps)


@needs_native
def test_native_step_matches_direct_native_call_and_compensates_latency():
    x = _noise()
    res = engine.render_chain(x, SR, [{"type": "aw.purest_drive", "params": {"drive": 0.8}}], stage="track")
    direct = native_backend.process("aw.purest_drive", x, SR, {"drive": 0.8})
    assert np.array_equal(res.audio, direct)
    # ClipOnly2 below the ceiling is a pure one-sample delay; offline it is compensated
    quiet = _noise(amp=0.01)
    res = engine.render_chain(quiet, SR, [{"type": "aw.clip_only2"}], stage="track")
    assert res.audio.shape == quiet.shape and np.array_equal(res.audio, quiet)


@needs_native
def test_aw_master_order_is_enforced():
    with pytest.raises(ChainError) as ei:
        engine.validate_chain([{"type": "aw.clip_only2"}, {"type": "aw.purest_drive"}], "master")
    assert ei.value.rule == "S-06"


# --------------------------------------------------------------------------- unavailable / fallback

def test_aw_step_without_fallback_raises_backend_error(no_native):
    with pytest.raises(DSPError) as ei:
        engine.render_chain(_noise(), SR, [{"id": "d", "type": "aw.purest_drive"}], stage="track")
    assert ei.value.rule == "backend" and ei.value.step == "d"
    assert "forced unavailable" in str(ei.value)


def test_declared_fallback_is_used_and_recorded(no_native):
    x = _noise()
    chain = [{"id": "p4", "type": "aw.pressure4", "params": {"pressure": 0.5}, "fallback": "compressor"},
             {"id": "drive", "type": "aw.purest_drive", "params": {"drive": 0.5}, "fallback": "saturator"},
             {"id": "clip", "type": "aw.clip_only2", "params": {"input_gain_db": -3.0},
              "fallback": "clipper"}]
    res = engine.render_chain(x, SR, chain, stage="master")
    assert [s["backend"] for s in res.steps] == ["reference"] * 3
    assert "native" not in res.backends
    drive = res.steps[1]
    assert drive["type"] == "aw.purest_drive" and drive["params"] == {"drive": 0.5}
    fb = drive["fallback"]
    assert fb["type"] == "saturator" and fb["params"]["mix"] == 0.5 and fb["params"]["drive_db"] == 0.0
    assert "forced unavailable" in fb["reason"]
    assert res.steps[0]["fallback"]["params"]["ratio"] == pytest.approx(3.5)
    assert res.steps[2]["fallback"]["notes"]                   # negative input gain dropped
    fb_warn = [w for w in res.warnings if "fallback" in w]
    assert len(fb_warn) == 3 and all("approximation" in w for w in fb_warn)
    # the fallback really ran: same audio as the mapped reference processor alone
    ref = engine.render_chain(x, SR, [{"type": "saturator", "params": fb["params"]}], stage="track")
    single = engine.render_chain(x, SR, chain[1:2], stage="track")
    assert np.array_equal(single.audio, ref.audio)


def test_explicit_fallback_params(no_native):
    chain = [{"type": "aw.console7_buss", "fallback": {"type": "gain", "params": {"gain_db": -1.5}}}]
    res = engine.render_chain(_noise(), SR, chain, stage="bus")
    assert res.steps[0]["fallback"] == {"type": "gain", "params": {"gain_db": -1.5}, "mapping": "explicit",
                                        "reason": res.steps[0]["fallback"]["reason"], "notes": []}


def test_fallback_validation():
    with pytest.raises(ChainError):      # not a reference processor / not allowed as fallback
        engine.validate_chain([{"type": "aw.purest_drive", "fallback": "limiter"}], "master")
    with pytest.raises(ChainError):      # not the declared fallback and no params to map
        engine.validate_chain([{"type": "aw.purest_drive", "fallback": "clipper"}], "track")
    with pytest.raises(ChainError):
        engine.validate_chain([{"type": "aw.purest_drive", "fallback": {"kind": "saturator"}}], "track")
    with pytest.raises(ValueError):
        engine.validate_chain([{"type": "aw.purest_drive",
                                "fallback": {"type": "saturator", "params": {"drive_db": 99.0}}}], "track")
    steps = engine.validate_chain([{"type": "aw.purest_drive", "fallback": "saturator"}], "track")
    assert steps[0]["fallback"]["type"] == "saturator"


def test_ballistic_processors_fall_back_to_reference_without_native(no_native):
    x = _noise()
    res = engine.render_chain(x, SR, [{"type": "compressor"}], stage="bus",
                              backend_preference=("native", "reference"))
    assert res.steps[0]["backend"] == "reference" and res.steps[0]["stats"]["ballistics"] == "python"
    res = engine.render_chain(x, SR, [{"type": "compressor", "backend": "native"}], stage="bus")
    assert res.steps[0]["backend"] == "reference"
    assert any("unavailable" in w for w in res.warnings)


def test_graph_schema_accepts_fallback():
    jsonschema = pytest.importorskip("jsonschema")
    schema = P.graph_schema()
    jsonschema.validate([{"type": "aw.purest_drive", "params": {"drive": 0.3}, "fallback": "saturator"},
                         {"type": "aw.clip_only2", "fallback": {"type": "clipper", "params": {}}}], schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate([{"type": "aw.purest_drive", "params": {"drive_db": 3.0}}], schema)
