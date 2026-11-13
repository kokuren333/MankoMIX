"""Stem-mix renderer (core/mixrender.py; SPEC 6.1.5, 6.5.2, 9.2, 9.6; D-036, D-054)."""
from __future__ import annotations

import math

import numpy as np
import pytest
from scipy.signal import resample_poly

from mankomix.core import mixrender as mr
from mankomix.core.adapters.file import FileAdapter
from mankomix.core.errors import InputError, ValidationError
from mankomix.core.project import Project
from tests.fixtures import synth

SR = 48000


@pytest.fixture(autouse=True)
def _local_home(tmp_path, monkeypatch):
    monkeypatch.setenv("MANKOMIX_HOME", str(tmp_path / "home"))


def _noise(n, ch=2, seed=0, amp=0.1):
    rng = np.random.default_rng(seed)
    return amp * rng.standard_normal((n, ch))


def _project(tmp_path, files: dict[str, tuple[np.ndarray, int]], name="song.mmx") -> Project:
    """Create a project and import ``{file name: (audio, rate)}`` (32-bit float WAV)."""
    src = tmp_path / f"src_{name}"
    for fname, (x, sr) in files.items():
        synth.write_wav(src / fname, x, sr)
    proj = Project.create(tmp_path / name, title="mix test")
    FileAdapter().fetch(src, proj, actor="human")
    return proj


def _f32(x):
    return np.asarray(x, dtype=np.float32).astype(np.float64)


def _track_id(proj, role):
    return next(t["id"] for t in proj.data["tracks"] if t["role"] == role)


def _ti(proj, tid):
    return next(i for i, t in enumerate(proj.data["tracks"]) if t["id"] == tid)


# --------------------------------------------------------------------------
# clips


def test_clip_placement_is_sample_exact(tmp_path):
    x = _noise(SR, seed=1)
    proj = _project(tmp_path, {"synth.wav": (x, SR), "bass.wav": (_noise(2 * SR, seed=2), SR)})
    tid = _track_id(proj, "synth")
    i = _ti(proj, tid)
    proj.apply_patch([{"op": "replace", "path": f"/tracks/{i}/clips/0/source_start", "value": 1000},
                      {"op": "replace", "path": f"/tracks/{i}/clips/0/length", "value": 5000},
                      {"op": "replace", "path": f"/tracks/{i}/clips/0/timeline_start", "value": 20000}],
                     actor="human")
    y, sr, rec = mr.render_track(proj, tid)
    assert sr == SR and y.shape == (2 * SR, 2)
    src = _f32(x)
    assert np.array_equal(y[20000:25000], src[1000:6000])
    assert not np.any(y[:20000]) and not np.any(y[25000:])
    # In the mix (stereo source, centered): untouched by the pan stage.
    m, _, mrec = mr.render_mix(proj, solo=[tid])
    assert np.array_equal(m, y)
    assert mrec["tracks"][[t["id"] for t in mrec["tracks"]].index(tid)]["pan"]["mode"] == "stereo_balance"


def test_clip_past_asset_end_is_padded_with_silence(tmp_path):
    x = _noise(SR // 2, seed=3)
    proj = _project(tmp_path, {"synth.wav": (x, SR), "bass.wav": (_noise(SR, seed=4), SR)})
    tid = _track_id(proj, "synth")
    i = _ti(proj, tid)
    proj.apply_patch([{"op": "replace", "path": f"/tracks/{i}/clips/0/length", "value": SR}], actor="human")
    y, _, rec = mr.render_track(proj, tid)
    assert np.array_equal(y[:SR // 2], _f32(x)) and not np.any(y[SR // 2:])
    pads = [a for a in rec["conform"]["applied"] if a["action"] == "pad_silence_at_render"]
    assert pads and pads[0]["asset"] == proj.data["tracks"][i]["clips"][0]["asset"]


@pytest.mark.parametrize("curve", ["linear", "equal_power"])
def test_fades(tmp_path, curve):
    x = np.ones((SR, 2)) * 0.5
    proj = _project(tmp_path, {"synth.wav": (x, SR)})
    tid = _track_id(proj, "synth")
    i = _ti(proj, tid)
    proj.apply_patch([{"op": "replace", "path": f"/tracks/{i}/clips/0/fade_in", "value": 1000},
                      {"op": "replace", "path": f"/tracks/{i}/clips/0/fade_out", "value": 2000},
                      {"op": "add", "path": f"/tracks/{i}/clips/0/fade_curve", "value": curve}], actor="human")
    y, _, _ = mr.render_track(proj, tid)
    shape = (lambda u: u) if curve == "linear" else (lambda u: np.sin(0.5 * np.pi * u))
    k = np.arange(1000)
    assert np.allclose(y[:1000, 0], 0.5 * shape(k / 1000), atol=1e-12)
    j = np.arange(2000)[::-1]  # samples to the end: last sample j = 0
    assert np.allclose(y[-2000:, 1], 0.5 * shape(j / 2000), atol=1e-12)
    assert y[0, 0] == 0.0 and y[-1, 0] == 0.0
    assert np.all(y[1000:SR - 2000] == 0.5)
    if curve == "equal_power":
        assert math.isclose(y[500, 0] / 0.5, math.sin(math.pi / 4), rel_tol=1e-12)  # -3 dB at the midpoint


def test_mute_solo_and_gain(tmp_path):
    a, b = _noise(SR, seed=5), _noise(SR, seed=6)
    proj = _project(tmp_path, {"synth.wav": (a, SR), "guitar.wav": (b, SR)})
    ta, tb = _track_id(proj, "synth"), _track_id(proj, "guitar")
    ia, ib = _ti(proj, ta), _ti(proj, tb)
    proj.apply_patch([{"op": "replace", "path": f"/tracks/{ia}/clips/0/gain_db", "value": -6.0},
                      {"op": "replace", "path": f"/tracks/{ia}/gain_db", "value": 3.0}], actor="human")
    m, _, rec = mr.render_mix(proj, mute=[tb])
    assert np.allclose(m, _f32(a) * 10 ** (-3.0 / 20), atol=1e-12)
    assert np.array_equal(mr.render_mix(proj, solo=[ta])[0], m)
    proj.apply_patch([{"op": "replace", "path": f"/tracks/{ib}/clips/0/muted", "value": True}], actor="human")
    assert np.array_equal(mr.render_mix(proj)[0], m)
    proj.apply_patch([{"op": "add", "path": f"/tracks/{ia}/muted", "value": True}], actor="human")
    silent, _, rec = mr.render_mix(proj)
    assert not np.any(silent)
    assert {t["id"]: t["audible"] for t in rec["tracks"]} == {ta: False, tb: True}


def test_gain_automation(tmp_path):
    proj = _project(tmp_path, {"synth.wav": (np.ones((SR, 2)) * 0.25, SR)})
    tid = _track_id(proj, "synth")
    i = _ti(proj, tid)
    proj.apply_patch([{"op": "add", "path": f"/tracks/{i}/automation",
                       "value": {"gain_db": [[0, 0.0], [1000, -6.0]]}}], actor="human")
    y, _, _ = mr.render_track(proj, tid)
    assert y[0, 0] == 0.25
    assert math.isclose(y[500, 0], 0.25 * 10 ** (-3.0 / 20), rel_tol=1e-12)
    assert np.allclose(y[1000:, 0], 0.25 * 10 ** (-6.0 / 20), rtol=1e-12)


# --------------------------------------------------------------------------
# pan


@pytest.mark.parametrize("law", [-3.0, -4.5, -6.0])
def test_pan_law_center_attenuation_measured(tmp_path, law):
    x = _noise(SR, ch=1, seed=7)
    proj = _project(tmp_path, {"synth.wav": (x, SR)})
    proj.set("/mix/pan_law_center_db", law, actor="human")
    m, _, rec = mr.render_mix(proj)
    src = _f32(x)[:, 0]
    measured = [20 * math.log10(np.sqrt(np.mean(m[:, c] ** 2)) / np.sqrt(np.mean(src ** 2))) for c in (0, 1)]
    assert measured[0] == pytest.approx(law, abs=1e-9) and measured[1] == pytest.approx(law, abs=1e-9)
    assert rec["tracks"][0]["pan"]["mode"] == "mono_pan" and rec["pan_law_center_db"] == law
    # hard left: unity on the left, nothing on the right
    tid = proj.data["tracks"][0]["id"]
    left, _, _ = mr.render_mix(proj, overrides={tid: {"pan": {"position": -1.0}}})
    assert np.allclose(left[:, 0], src, atol=1e-15) and not np.any(left[:, 1])


def test_pan_stereo_balance_width_and_presets():
    x = _noise(4800, seed=8)
    assert np.array_equal(mr.pan_stereo(x, 0.0, 1.0, -3.0), x)          # centered stereo: untouched
    mono = mr.pan_stereo(x, 0.0, 0.0, -3.0)                               # width 0 = mono
    assert np.allclose(mono[:, 0], mono[:, 1]) and np.allclose(mono[:, 0], x.mean(axis=1))
    right = mr.pan_stereo(x, 1.0, 1.0, -3.0)
    assert not np.any(right[:, 0]) and np.array_equal(right[:, 1], x[:, 1])
    assert mr.pan_position("L") == -1.0 and mr.pan_position("RC", 0.1) == pytest.approx(0.6)
    assert mr.pan_position("R", 0.5) == 1.0
    with pytest.raises(InputError):
        mr.pan_position("X")
    assert mr.track_pan({"pan": {"preset": "LC", "fine": -0.1}}) == (pytest.approx(-0.6), 1.0)


def test_pan_gains_match_engine_reference():
    from mankomix.dsp.reference.basic import pan_gains as ref_gains
    for law in (-3.0, -4.5, -6.0, 0.0):
        for pos in (-1.0, -0.3, 0.0, 0.5, 1.0):
            assert mr.pan_gains(pos, law) == pytest.approx(ref_gains(pos, law), abs=1e-15)


# --------------------------------------------------------------------------
# buses and sends


def _with_fx_bus(proj, tid, *, level_db, pre_fader=False, fx_gain_db=-6.0):
    i = _ti(proj, tid)
    bus = {"id": "bus_fx", "kind": "fx", "output": "bus_mix",
           "chain": [{"id": "prc_fx_gain", "type": "gain", "params": {"gain_db": fx_gain_db}, "reason": "test"}]}
    proj.apply_patch([{"op": "add", "path": "/buses/-", "value": bus},
                      {"op": "replace", "path": f"/tracks/{i}/sends",
                       "value": [{"bus": "bus_fx", "level_db": level_db, "pre_fader": pre_fader}]}],
                     actor="human")


def test_send_to_fx_bus_with_gain_chain(tmp_path):
    x = _noise(SR, seed=9)
    proj = _project(tmp_path, {"synth.wav": (x, SR)})
    tid = proj.data["tracks"][0]["id"]
    _with_fx_bus(proj, tid, level_db=-6.0)
    m, _, rec = mr.render_mix(proj)
    g = 10 ** (-6.0 / 20)
    assert np.allclose(m, _f32(x) * (1.0 + g * g), atol=1e-12)
    assert rec["bus_order"].index("bus_fx") < rec["bus_order"].index("bus_mix")
    assert "reference" in rec["backends"]
    fx = next(b for b in rec["buses"] if b["id"] == "bus_fx")
    assert fx["chain"][0]["type"] == "gain" and fx["chain"][0]["backend"] == "reference"


def test_pre_fader_send_ignores_track_gain(tmp_path):
    x = _noise(SR, seed=10)
    proj = _project(tmp_path, {"synth.wav": (x, SR)})
    tid = proj.data["tracks"][0]["id"]
    _with_fx_bus(proj, tid, level_db=0.0, pre_fader=True, fx_gain_db=0.0)
    proj.set("/tracks/0/gain_db", -20.0, actor="human")
    m, _, _ = mr.render_mix(proj)
    assert np.allclose(m, _f32(x) * (10 ** (-20.0 / 20) + 1.0), atol=1e-12)


def test_bus_loop_rejected(tmp_path):
    proj = _project(tmp_path, {"synth.wav": (_noise(SR, seed=11), SR)})
    proj.data["buses"] += [{"id": "bus_a", "kind": "group", "chain": [], "output": "bus_b"},
                           {"id": "bus_b", "kind": "group", "chain": [], "output": "bus_a"}]
    with pytest.raises(ValidationError, match="loop"):
        mr.render_mix(proj)
    proj.data["buses"][-1]["output"] = "bus_mix"
    assert mr.bus_order(proj.data) == ["bus_a", "bus_b", "bus_mix"]  # bus_a feeds bus_b


def test_track_chain_runs_on_engine_and_reason_is_stripped(tmp_path):
    x = _noise(SR, seed=12)
    proj = _project(tmp_path, {"synth.wav": (x, SR)})
    proj.set("/tracks/0/chain", [{"id": "prc_t1", "type": "gain", "params": {"gain_db": -6.0}, "reason": "R-04"},
                                 {"id": "prc_t2", "type": "gain", "params": {"gain_db": -60.0}, "reason": "off",
                                  "enabled": False}], actor="human")
    y, _, rec = mr.render_track(proj, proj.data["tracks"][0]["id"])
    assert np.allclose(y, _f32(x) * 10 ** (-6.0 / 20), atol=1e-12)
    assert [s["id"] for s in rec["chain"]] == ["prc_t1", "prc_t2"] and rec["chain"][1]["bypass"] is True
    raw, _, _ = mr.render_track(proj, proj.data["tracks"][0]["id"], apply_chain=False)
    assert np.array_equal(raw, _f32(x))


# --------------------------------------------------------------------------
# conform, excerpts, determinism, variants


def test_mixed_rates_resampled_at_render_and_recorded(tmp_path):
    sine44 = 0.3 * np.sin(2 * np.pi * 1000.0 * np.arange(44100) / 44100)
    files = {"synth.wav": (_noise(SR, seed=13), SR), "bass.wav": (_noise(SR, seed=14), SR),
             "guitar.wav": (np.stack([sine44, sine44], axis=1), 44100)}
    proj = _project(tmp_path, files)
    assert proj.data["timebase"]["sample_rate"] == SR
    gid = _track_id(proj, "guitar")
    m, sr, rec = mr.render_mix(proj, solo=[gid])
    assert sr == SR and m.shape[0] == SR
    expected = resample_poly(_f32(np.stack([sine44, sine44], axis=1)), 160, 147, axis=0)
    assert np.allclose(m[:expected.shape[0]], expected[:SR], atol=1e-12)
    applied = rec["conform"]["applied"]
    gasset = proj.data["tracks"][_ti(proj, gid)]["clips"][0]["asset"]
    assert {"asset": gasset, "from_rate": 44100, "to_rate": SR, "action": "resample_at_render"}.items() <= \
        next(a for a in applied if a["action"] == "resample_at_render").items()
    assert rec["backends"]["resample"]["backend"] == "scipy.signal.resample_poly"


def test_excerpt_equals_slice_of_full_render(tmp_path):
    files = {"synth.wav": (_noise(2 * SR, seed=15), SR), "bass.wav": (_noise(2 * SR, ch=1, seed=16), SR)}
    proj = _project(tmp_path, files)
    tid = _track_id(proj, "synth")
    _with_fx_bus(proj, tid, level_db=-10.0)
    proj.set("/tracks/1/pan", {"position": 0.3, "width": 1.0}, actor="human")
    full, _, _ = mr.render_mix(proj)
    part, _, rec = mr.render_mix(proj, start=30000, length=20000)
    assert rec["range"] == {"start": 30000, "length": 20000, "timeline_length": 2 * SR, "excerpt": True,
                            "preroll": 0, "postroll": 0, "exact": True}
    assert np.array_equal(part, full[30000:50000])
    # Stateful chain (HPF): the pre-roll reaches the timeline start here, so the slice still matches.
    proj.set("/buses/1/chain", [{"id": "prc_hpf", "type": "filter",
                                 "params": {"kind": "hpf", "freq_hz": 100.0, "slope_db_oct": 12},
                                 "reason": "test"}], actor="human")
    full, _, _ = mr.render_mix(proj)
    part, _, rec = mr.render_mix(proj, start=30000, length=20000)
    assert rec["range"]["exact"] is True and rec["range"]["preroll"] == 30000
    assert np.allclose(part, full[30000:50000], atol=1e-9)
    _, _, rec = mr.render_mix(proj, start=30000, length=20000, preroll=1000)
    assert rec["range"]["exact"] is False and rec["range"]["preroll"] == 1000


def test_render_is_deterministic(tmp_path):
    files = {"synth.wav": (_noise(SR, seed=17), SR), "bass.wav": (_noise(SR, ch=1, seed=18), SR)}
    proj = _project(tmp_path, files)
    proj.set("/tracks/0/chain", [{"id": "prc_c", "type": "compressor", "params": {}, "reason": "test"}],
             actor="human")
    a, _, ra = mr.render_mix(proj, seed=3)
    b, _, rb = mr.render_mix(proj, seed=3)
    assert np.array_equal(a, b)
    assert ra == rb
    assert ra["project_hash"] == proj.content_hash()
    assert {x["id"] for x in ra["assets"]} == {a_["id"] for a_ in proj.data["assets"]}
    assert all(len(x["sha256"]) == 64 for x in ra["assets"])
    assert all(t["peak_dbfs"] is not None and t["lufs_i"] is not None for t in ra["tracks"])


def test_static_sum_is_plain_stem_sum(tmp_path):
    a, b = _noise(SR, seed=19), _noise(SR // 2, ch=1, seed=20)
    proj = _project(tmp_path, {"synth.wav": (a, SR), "bass.wav": (b, SR)})
    # Edits, gains, pan and mutes do not change the Before reference (D-036).
    proj.apply_patch([{"op": "replace", "path": "/tracks/0/gain_db", "value": -12.0},
                      {"op": "replace", "path": "/tracks/1/clips/0/muted", "value": True},
                      {"op": "replace", "path": "/mix/pan_law_center_db", "value": -6.0}], actor="human")
    s, sr, rec = mr.static_sum(proj)
    expected = _f32(a).copy()
    expected[:SR // 2] += _f32(b)
    assert sr == SR and np.array_equal(s, expected)
    assert rec["kind"] == "static_sum" and set(rec["summed_assets"]) == {x["id"] for x in proj.data["assets"]}


def test_static_sum_equals_untouched_mix_for_stereo_stems(tmp_path):
    proj = _project(tmp_path, {"synth.wav": (_noise(SR, seed=21), SR), "drums.wav": (_noise(SR, seed=22), SR)})
    assert np.allclose(mr.static_sum(proj)[0], mr.render_mix(proj)[0], atol=1e-15)


def test_variant_and_inline_overrides(tmp_path):
    x = _noise(SR, seed=23)
    proj = _project(tmp_path, {"synth.wav": (x, SR)})
    tid = proj.data["tracks"][0]["id"]
    proj.apply_patch([{"op": "add", "path": "/variants/-",
                       "value": {"id": "var_quiet", "outputs": [], "track_overrides": {tid: {"gain_db": -6.0}}}}],
                     actor="human")
    m, _, rec = mr.render_mix(proj, variant_id="var_quiet")
    assert np.allclose(m, _f32(x) * 10 ** (-6.0 / 20), atol=1e-12)
    assert rec["overrides_applied"] == {tid: ["gain_db"]} and rec["effective_hash"] != rec["project_hash"]
    m2, _, _ = mr.render_mix(proj, variant_id="var_quiet", overrides={tid: {"gain_db": 0.0}})
    assert np.array_equal(m2, _f32(x))
    with pytest.raises(InputError):
        mr.render_mix(proj, variant_id="var_missing")
    assert proj.data["tracks"][0].get("gain_db") == 0.0  # the project itself is unchanged


def test_output_rate_resamples_once(tmp_path):
    proj = _project(tmp_path, {"synth.wav": (_noise(SR, seed=24), SR)})
    y, sr, rec = mr.render_mix(proj, sr=44100)
    assert sr == 44100 and y.shape[0] == 44100
    assert rec["conform"]["applied"][-1]["action"] == "resample_output"
