"""Track-context observations (FBREVIEW FR-1) and the three relation / placement quantities (FR-2).

FR-1
(a) a dry track target gives the same crest / band_energy as query.observe on the same signal
(b) the solo path includes the send return and differs from dry
(c) without a valid cleanup cache: status error, nothing rendered, no project file added or changed (G-3)
(d) a direction without track targets: the outcome is byte-identical to the code before (and no
    StemSource is made)
(e) validate: no warning on a track target, unknown_target for an unknown track (with --project)
(f) --calibrate: the apply record does not change with or without track / context observations

FR-2
(a) image_position = -1 / +1 / 0 for left / right / both, 0.588 +- 0.01 for a mono source at 0.4
(b) masking > 0 for two tracks in the same band, lower when the other is 12 dB down; ~0 for far bands
(c) wet_ratio = -120.0 without a send, about +6 dB for a send 6 dB up (linear bus)
(d) the forbidden combinations are bad_value / bad_target
(e) masking equals masking_matrix called directly (no second definition)

Small synthetic projects in tmp_path (24 kHz, 3 s). Audio only under tmp_path.
"""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
from pathlib import Path

import numpy as np
import pytest
from scipy import signal as sig

from mankomix.core import audio_io
from mankomix.core import mixrender as mr
from mankomix.core.adapters.file import FileAdapter
from mankomix.core.analysis.stems import masking_matrix
from mankomix.core.project import Project
from mankomix.director import calibrate as C
from mankomix.director import direction as D
from mankomix.director import query as Q
from mankomix.director import stemobs as S
from tests.fixtures import synth

SR = 24000
SECS = 3.0
N = int(SR * SECS)


@pytest.fixture(autouse=True)
def _local_home(tmp_path, monkeypatch):
    monkeypatch.setenv("MANKOMIX_HOME", str(tmp_path / "home"))


def _noise(lo: float, hi: float, seed: int, dbfs: float = -20.0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    x = rng.standard_normal(N)
    sos = sig.butter(4, [lo / (SR / 2), hi / (SR / 2)], btype="bandpass", output="sos")
    x = sig.sosfiltfilt(sos, x)
    x *= 10 ** (dbfs / 20.0) / np.sqrt(np.mean(x ** 2))
    return np.stack([x, x], axis=1)


def _tree(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def _make(root: Path, stems: dict[str, np.ndarray], *, tracks: dict | None = None, fx: bool = True,
          variants: list[dict] | None = None) -> Path:
    """Project.create + file import; then per-track edits, an fx bus (gain 0 dB: linear) and variants."""
    src = root.parent / f"{root.name}_stems"
    for name, x in stems.items():
        synth.write_wav(src / f"{name}.wav", x, SR)
    p = Project.create(root, title="stemobs test")
    FileAdapter().fetch(src, p, actor="human")
    p.set("/mix/applied", {"proposal_id": "mxp_floor"}, actor="human")
    p.set("/variants", variants or [{"id": "var_x", "objective": None,
                                     "master": {"profile": "streaming_universal", "chain": []}, "outputs": []}],
          actor="human")
    data = json.loads((root / "project.json").read_text(encoding="utf-8"))
    for t in data["tracks"]:
        t.update(copy.deepcopy((tracks or {}).get(t["id"]) or {}))
    if fx:
        data["buses"].append({"id": "bus_fx", "kind": "fx", "output": "bus_mix",
                              "chain": [{"id": "prc_fx", "type": "gain", "params": {"gain_db": 0.0}, "reason": "test"}]})
    (root / "project.json").write_text(json.dumps(data), encoding="utf-8")
    pdir = root / "cache" / "proposals"
    pdir.mkdir(parents=True, exist_ok=True)
    floor = {"stage": "mix", "status": "applied", "proposal_id": "mxp_floor",
             "changes": {"mix_bus": "bus_mix", "tracks": {}, "buses": []},
             "sections": [{"id": "sec1", "start_s": 0.0, "end_s": 1.5, "label": "a"},
                          {"id": "sec2", "start_s": 1.5, "end_s": SECS, "label": "b"}],
             "objective_evaluation": {"score": 0.1}, "measurements": {}, "notes": []}
    (pdir / "mxp_floor.json").write_text(json.dumps(floor), encoding="utf-8")
    return root


VARIANTS = [{"id": "var_x", "objective": None, "master": {"profile": "streaming_universal", "chain": []}, "outputs": []},
            {"id": "v_send6", "track_overrides": {"trk_a": {"sends": [{"bus": "bus_fx", "level_db": -6.0}]}},
             "master": {"profile": "streaming_universal", "chain": []}, "outputs": []},
            {"id": "v_a12", "track_overrides": {"trk_a": {"gain_db": -12.0}},
             "master": {"profile": "streaming_universal", "chain": []}, "outputs": []},
            {"id": "v_mute_b", "track_overrides": {"trk_b": {"muted": True}},
             "master": {"profile": "streaming_universal", "chain": []}, "outputs": []},
            {"id": "v_unclean", "track_overrides": {"trk_a": {"cleanup": {"applied": {"assets": {
                "ast_a": {"plan_hash": "f" * 16, "asset_sha256": None}}}}}},
             "master": {"profile": "streaming_universal", "chain": []}, "outputs": []}]


@pytest.fixture(scope="module")
def _tpl(tmp_path_factory) -> Path:
    """trk_a and trk_b share 300-1000 Hz (a sends -12 dB to bus_fx, b is mono panned to 0.4); trk_c 4-8 kHz."""
    import os
    old = os.environ.get("MANKOMIX_HOME")
    base = tmp_path_factory.mktemp("stemobs_tpl")
    os.environ["MANKOMIX_HOME"] = str(base / "home")
    try:
        return _make(base / "song", {"a": _noise(300, 1000, 1), "b": _noise(300, 1000, 2, -22.0)[:, 0],   # a mono file: the constant-power pan law
                                     "c": _noise(4000, 8000, 3, -26.0)},
                     tracks={"trk_a": {"sends": [{"bus": "bus_fx", "level_db": -12.0}], "role": "vocals",
                                       "is_lead": True},
                             "trk_b": {"pan": {"position": 0.4, "width": 1.0}, "role": "keyboard"},
                             "trk_c": {"role": "synth"}},
                     variants=VARIANTS)
    finally:
        if old is None:
            os.environ.pop("MANKOMIX_HOME", None)
        else:
            os.environ["MANKOMIX_HOME"] = old


@pytest.fixture
def song(_tpl, tmp_path) -> Path:
    dst = tmp_path / "song"
    shutil.copytree(_tpl, dst)
    return dst


def _render(root: Path, vid: str = "var_x") -> None:
    y, sr, _ = mr.render_mix(Project.open(root), variant_id=vid, measure=False)
    d = root / "renders" / vid
    d.mkdir(parents=True, exist_ok=True)
    audio_io.write(d / "song__hires_native.wav", y, sr)


def _block(observations: list[dict], claims: list[dict] | None = None, moves: list[dict] | None = None) -> dict:
    return {"schema_version": 1, "kind": "direction", "song": "s", "request": {"utterance": "test"},
            "sources": {}, "aims": [{"id": "a1", "text": "x"}],
            "variants": [{"id": "var_x", "profile": "streaming_universal"}],
            "moves": moves or [{"id": "m01", "aim": "a1", "target": "trk_b", "op": "gain",
                                "params": {"delta_db": -1.0}, "basis": "x", "origin": "new"}],
            "claims": claims or [{"id": "c1", "quantity": "P-03", "direction": "not_worse", "tolerance": 1.0,
                                  "primary": True}],
            "observations": observations}


def _doc(dirpath: Path, block: dict) -> Path:
    dirpath.mkdir(parents=True, exist_ok=True)
    p = dirpath / "direction.md"
    p.write_text(f"---\nid: {D.direction_id(block)}\nkind: direction\ntitle: t\ncreated: 2026-11-16\n"
                 f"status: draft\nvisibility: private\n---\n\n# t\n\n```json direction\n"
                 f"{json.dumps(block, ensure_ascii=False)}\n```\n", encoding="utf-8")
    return p


def _validate(tmp_path: Path, observations: list[dict], project: Path | None = None, tag: str = "v") -> dict:
    return D.validate(D.parse_document(_doc(tmp_path / tag, _block(observations))), project)


# ---------------------------------------------------------------------------
# FR-1
# ---------------------------------------------------------------------------

def test_fr1_a_dry_equals_query_observe_on_the_same_signal(song):
    stems: dict = {}
    mr.render_mix(Project.open(song), variant_id="var_x", stems_out=stems, measure=False)
    src = S.StemSource(song, "var_x")
    for spec in ({"primitive": "crest"}, {"primitive": "band_energy", "band_hz": [300, 1000]},
                 {"primitive": "crest", "band_hz": [400, 900], "section": "sec2"},
                 {"primitive": "loudness", "level_match": True}):
        for tid in ("trk_a", "trk_b"):
            got = S.observe(src, {**spec, "target": tid}, sections=D._Project(song).sections())
            ref = Q.observe(stems[tid], SR, spec, sections=D._Project(song).sections())
            assert got["status"] == "ok" and got["value"] == ref["value"], (spec, tid)
            assert got["gain_db"] == 0.0 and got["signal"] == "mix_stage" and got["path"] == "dry"
            assert got["range_s"] == ref["range_s"]
    # query.observe itself keeps refusing a track target (the existing behaviour, FR-1)
    assert Q.observe(stems["trk_a"], SR, {"primitive": "crest", "target": "trk_a"})["status"] == "unsupported"


def test_fr1_b_solo_includes_the_send_return(song):
    src = S.StemSource(song, "var_x")
    dry = S.observe(src, {"primitive": "loudness", "target": "trk_a"})
    solo = S.observe(src, {"primitive": "loudness", "target": "trk_a", "path": "solo"})
    assert solo["status"] == dry["status"] == "ok" and solo["path"] == "solo"
    # a send at -12 dB into a 0 dB bus: the solo output is dry * (1 + 10^(-12/20)) in amplitude
    assert solo["value"] - dry["value"] == pytest.approx(20 * np.log10(1 + 10 ** (-12 / 20)), abs=0.05)
    # trk_c has no send: solo == dry
    a = S.observe(src, {"primitive": "crest", "target": "trk_c"})
    b = S.observe(src, {"primitive": "crest", "target": "trk_c", "path": "solo"})
    assert a["value"] == pytest.approx(b["value"], abs=1e-3)


def test_fr1_c_no_cache_is_an_error_and_writes_nothing(song, monkeypatch):
    before = _tree(song)
    calls = []
    monkeypatch.setattr(mr, "render_mix", lambda *a, **k: calls.append(1))
    src = S.StemSource(song, "v_unclean")
    for spec in ({"primitive": "crest", "target": "trk_b"}, {"primitive": "masking", "target": "all"},
                 {"primitive": "wet_ratio", "target": "trk_a"}, {"primitive": "crest", "target": "trk_a",
                                                                 "path": "solo"}):
        r = S.observe(src, spec)
        assert r["status"] == "error" and r["reason"].startswith("整音の cache が無いか古い"), spec
    assert calls == []
    assert _tree(song) == before


def test_fr1_c_check_with_track_observations_writes_only_the_outcome(song, tmp_path):
    floor = tmp_path / "floor"
    shutil.copytree(song, floor)
    _render(floor)
    data = json.loads((song / "project.json").read_text(encoding="utf-8"))
    next(t for t in data["tracks"] if t["id"] == "trk_a")["gain_db"] = -6.0
    (song / "project.json").write_text(json.dumps(data), encoding="utf-8")
    _render(song)
    obs = [{"id": "o1", "primitive": "crest", "target": "master"},
           {"id": "o2", "primitive": "loudness", "target": "trk_a"},
           {"id": "o3", "primitive": "masking", "target": "trk_b"},
           {"id": "o4", "primitive": "wet_ratio", "target": "trk_a"},
           {"id": "o5", "primitive": "image_position", "target": "trk_b"},
           {"id": "o6", "primitive": "image_position", "target": "master"},
           {"id": "o7", "primitive": "crest", "target": "trk_zz"}]
    blk = _block(obs, claims=[{"id": "c1", "quantity": "obs:o3", "direction": "down", "min_delta": 0.5,
                               "primary": True},
                              {"id": "c2", "quantity": "obs:o2", "direction": "down", "min_delta": 5.0}])
    doc = _doc(tmp_path / "d", blk)
    fb, sb = _tree(floor), _tree(song)
    out = D.check(song, floor, doc)
    sa = _tree(song)
    assert _tree(floor) == fb
    added = set(sa) - set(sb)
    assert added == {f"directions/{D.parse_document(doc)['id']}.outcome.json"}
    assert all(sa[k] == v for k, v in sb.items())
    ov = out["observations"]
    for oid in ("o2", "o3", "o4", "o5"):
        for side in ("floor", "result"):
            assert ov[oid][side]["status"] == "ok" and ov[oid][side]["signal"] == "mix_stage", (oid, side)
    assert ov["o2"]["result"]["value"] - ov["o2"]["floor"]["value"] == pytest.approx(-6.0, abs=0.01)
    assert ov["o4"]["floor"]["value"] == pytest.approx(-12.0, abs=0.01)
    assert ov["o5"]["floor"]["value"] == pytest.approx(np.sin(0.4 * np.pi / 2), abs=0.01)
    assert ov["o6"]["floor"]["status"] == "ok" and "signal" not in ov["o6"]["floor"]
    assert ov["o7"]["floor"] == {"status": "error", "reason": "unknown track 'trk_zz'"}
    c = {x["id"]: x for x in out["claims"]}
    assert c["c1"]["verdict"] == "met" and c["c2"]["verdict"] == "met"   # a 6 dB down: b less buried
    assert ov["o3"]["floor"]["value"] > ov["o3"]["result"]["value"] + 0.5


def test_fr1_d_outcome_without_track_targets_is_unchanged(tmp_path, monkeypatch):
    import tests.test_upgrade2_duck as U
    import tests.test_direction_update as T

    def boom(*a, **k):
        raise AssertionError("StemSource made for a direction without track observations")

    monkeypatch.setattr(S, "StemSource", boom)
    for tag, blk in (("plain", T._block()), ("min", T._minimal_block()), ("refs", T._with_refs(T._block()))):
        _, raw_plain, _, _ = U._check_both(tmp_path, blk, tag)
        assert U._masked(raw_plain.decode("utf-8")) == U.BASE["outcome"][tag], tag


def test_fr1_e_validate_track_targets(song, tmp_path):
    import tests.test_direction_update as T
    obs = [{"id": "o1", "primitive": "crest", "target": "trk_a"},
           {"id": "o2", "primitive": "band_energy", "target": "trk_b", "band_hz": [300, 1000], "path": "solo"}]
    for proj in (None, song):
        res = _validate(tmp_path, obs, proj, tag=f"ok{proj is None}")
        assert res["ok"] and res["warnings"] == [T.WARN_P03_B], res
    res = _validate(tmp_path, obs + [{"id": "o3", "primitive": "crest", "target": "trk_nope"},
                                     {"id": "o4", "primitive": "masking", "target": "trk_a", "against": "trk_x"}],
                    song, tag="unk")
    assert [(e["where"], e["code"]) for e in res["errors"]] == [("observations.o3", "unknown_target"),
                                                                ("observations.o4.against", "unknown_target")]
    # without --project an unknown track is not knowable: no error
    assert _validate(tmp_path, [{"id": "o3", "primitive": "crest", "target": "trk_nope"}], None, tag="np")["ok"]
    # other non-master targets keep the existing warning
    res = _validate(tmp_path, [{"id": "o1", "primitive": "crest", "target": "bus_fx"}], song, tag="bus")
    assert [(w["where"], w["code"]) for w in res["warnings"]] == [("observations.o1", "unsupported"),
                                                                  ("quantities.P-03", "unmeasured_quantity")]


def _cal_block(extra_obs: list[dict], extra_claims: list[dict], extra_safeguards: list[dict]) -> dict:
    m = {"id": "m01", "aim": "a1", "target": "trk_c", "op": "chain_add", "processor": "eq",
         "params": {"shape": "peak", "freq_hz": 5000, "gain_db": [1.0, 4.0], "bw_oct": 1.0},
         "basis": "x", "origin": "new",
         "safeguard": [{"quantity": "obs:o2", "direction": "not_worse", "tolerance": 0.5}] + extra_safeguards}
    return _block([{"id": "o1", "primitive": "band_energy", "target": "master", "band_hz": [4000, 8000]},
                   {"id": "o2", "primitive": "crest", "target": "master"}] + extra_obs,
                  claims=[{"id": "c1", "quantity": "obs:o1", "direction": "up", "min_delta": 1.0, "primary": True}]
                  + extra_claims, moves=[m])


def test_fr1_f_calibrate_ignores_track_and_context_observations(_tpl, tmp_path):
    plain = _cal_block([], [], [])
    extra = _cal_block([{"id": "o8", "primitive": "loudness", "target": "trk_c"},
                        {"id": "o9", "primitive": "masking", "target": "trk_a"},
                        {"id": "o10", "primitive": "wet_ratio", "target": "trk_a"}],
                       [{"id": "c2", "quantity": "obs:o9", "direction": "down", "min_delta": 0.5}],
                       [{"quantity": "obs:o8", "direction": "not_worse", "tolerance": 0.1}])
    recs = []
    for tag, blk in (("plain", plain), ("extra", extra)):
        song = tmp_path / f"song_{tag}"
        shutil.copytree(_tpl, song)
        a = D.apply(song, _doc(tmp_path / tag, blk), calibrate=True)
        assert a["applied"] is True, a
        recs.append(a)
    assert recs[0]["calibration"] == recs[1]["calibration"]
    assert recs[0]["record"]["moves"] == recs[1]["record"]["moves"]
    items = {i["key"] for i in C._items(D.parse_document(_doc(tmp_path / "x", extra)))}
    assert items == {"claim:c1", "safeguard:m01:0"}


# ---------------------------------------------------------------------------
# FR-2
# ---------------------------------------------------------------------------

def test_fr2_a_image_position():
    rng = np.random.default_rng(5)
    m = rng.standard_normal(SR) * 0.1
    z = np.zeros_like(m)
    io = lambda x: Q.observe(x, SR, {"primitive": "image_position"})
    assert io(np.stack([m, z], axis=1))["value"] == -1.0
    assert io(np.stack([z, m], axis=1))["value"] == 1.0
    assert io(np.stack([m, m], axis=1))["value"] == 0.0
    r = io(mr.pan_stereo(np.stack([m, m], axis=1), 0.4, 1.0, -3.0, mono=True))
    assert r["value"] == pytest.approx(0.588, abs=0.01) and r["unit"] == ""
    r7 = io(mr.pan_stereo(np.stack([m, m], axis=1), 0.7, 1.0, -3.0, mono=True))
    assert r7["value"] == pytest.approx(0.891, abs=0.01)
    # band_hz: a left low tone and a right high tone
    t = np.arange(SR) / SR
    x = np.stack([np.sin(2 * np.pi * 100 * t), np.sin(2 * np.pi * 3000 * t)], axis=1)
    assert Q.observe(x, SR, {"primitive": "image_position", "band_hz": [50, 200]})["value"] < -0.95
    assert Q.observe(x, SR, {"primitive": "image_position", "band_hz": [2000, 5000]})["value"] > 0.95
    assert Q.observe(np.zeros((SR, 2)), SR, {"primitive": "image_position"})["status"] == "error"
    for view in ("mono", "mono_band"):
        with pytest.raises(Q.QueryError, match="bad_value"):
            Q.observe(x, SR, {"primitive": "image_position", "view": view})
    assert "image_position" in Q.PRIMITIVES and "image_position" in Q.STEREO_ONLY_PRIMITIVES


def test_fr2_b_masking_same_band_level_and_far_bands(song, tmp_path):
    # trk_b (-25 dB at the pan law) is buried by trk_a (-20 dB) in the same band; a 12 dB down frees it
    base = S.observe(S.StemSource(song, "var_x"), {"primitive": "masking", "target": "trk_b"})
    low_a = S.observe(S.StemSource(song, "v_a12"), {"primitive": "masking", "target": "trk_b"})
    assert base["status"] == low_a["status"] == "ok" and base["unit"] == "dB"
    assert base["value"] > 0.5 and low_a["value"] < base["value"] - 0.5
    pair = S.observe(S.StemSource(song, "var_x"), {"primitive": "masking", "target": "trk_b", "against": "trk_a"})
    assert pair["value"] > 0.5
    far = _make(tmp_path / "far", {"lo": _noise(60, 150, 7), "hi": _noise(4000, 8000, 8)}, fx=False)
    for t in ("trk_lo", "trk_hi"):
        r = S.observe(S.StemSource(far, "var_x"), {"primitive": "masking", "target": t})
        assert r["status"] == "ok" and r["value"] < 0.5, (t, r)
    # band_hz: mean over the ERB bands whose centre is in [lo, hi); a band with no centre is an error
    bb = S.observe(S.StemSource(song, "var_x"), {"primitive": "masking", "target": "trk_a", "band_hz": [300, 1000]})
    assert bb["status"] == "ok"
    assert S.observe(S.StemSource(song, "var_x"),
                     {"primitive": "masking", "target": "trk_a", "band_hz": [300, 300.5]})["status"] == "error"
    # fewer than 2 audible tracks, a muted target
    one = _make(tmp_path / "one", {"x": _noise(300, 1000, 9)}, fx=False)
    assert S.observe(S.StemSource(one, "var_x"), {"primitive": "masking", "target": "all"})["status"] == "error"
    r = S.observe(S.StemSource(song, "v_mute_b"), {"primitive": "masking", "target": "trk_b"})
    assert r["status"] == "error" and "muted" in r["reason"]


def test_fr2_c_wet_ratio(song):
    src = S.StemSource(song, "var_x")
    assert S.observe(src, {"primitive": "wet_ratio", "target": "trk_b"})["value"] == -120.0
    w12 = S.observe(src, {"primitive": "wet_ratio", "target": "trk_a"})
    w6 = S.observe(S.StemSource(song, "v_send6"), {"primitive": "wet_ratio", "target": "trk_a"})
    assert w12["path"] == "solo" and w12["value"] == pytest.approx(-12.0, abs=0.5)
    assert w6["value"] - w12["value"] == pytest.approx(6.0, abs=0.5)
    wb = S.observe(src, {"primitive": "wet_ratio", "target": "trk_a", "band_hz": [400, 900], "section": "sec1"},
                   sections=D._Project(song).sections())
    assert wb["value"] == pytest.approx(-12.0, abs=0.5) and wb["range_s"] == [0.0, 1.5]


def test_fr2_d_forbidden_combinations(tmp_path):
    import tests.test_direction_update as T
    cases = [
        ({"primitive": "masking", "target": "trk_a", "against": "trk_b", "band_hz": [100, 500]}, "bad_value"),
        ({"primitive": "masking", "target": "all", "against": "trk_b"}, "bad_value"),
        ({"primitive": "masking", "target": "all", "band_hz": [100, 500]}, "bad_value"),
        ({"primitive": "masking", "target": "trk_a", "path": "dry"}, "bad_value"),
        ({"primitive": "masking", "target": "trk_a", "view": "mono"}, "bad_value"),
        ({"primitive": "masking", "target": "trk_a", "against": "trk_a"}, "bad_value"),
        ({"primitive": "masking", "target": "master"}, "bad_target"),
        ({"primitive": "wet_ratio", "target": "trk_a", "path": "solo"}, "bad_value"),
        ({"primitive": "wet_ratio", "target": "trk_a", "view": "stereo"}, "bad_value"),
        ({"primitive": "wet_ratio", "target": "master"}, "bad_target"),
        ({"primitive": "image_position", "target": "master", "view": "mono"}, "bad_value"),
        ({"primitive": "image_position", "target": "trk_a", "band_hz": [500, 100]}, "bad_value"),
        ({"primitive": "image_position", "target": "bus_fx"}, "bad_target"),
        ({"primitive": "crest", "target": "master", "path": "dry"}, "bad_value"),
        ({"primitive": "crest", "path": "solo"}, "bad_value"),
        ({"primitive": "crest", "target": "trk_a", "path": "wet"}, "bad_value"),
        ({"primitive": "crest", "target": "trk_a", "against": "trk_b"}, "bad_value"),
    ]
    for i, (o, code) in enumerate(cases):
        res = _validate(tmp_path, [{"id": "o1", **o}], tag=f"c{i}")
        assert not res["ok"] and [e["code"] for e in res["errors"]] == [code], (o, res["errors"])
    good = [{"primitive": "masking", "target": "all"}, {"primitive": "masking", "target": "trk_a", "against": "trk_b"},
            {"primitive": "masking", "target": "trk_a", "band_hz": [100, 500], "section": "all"},
            {"primitive": "wet_ratio", "target": "trk_a", "band_hz": [200, 4000]},
            {"primitive": "image_position", "target": "master", "band_hz": [200, 4000]},
            {"primitive": "image_position", "target": "trk_a", "path": "solo"}]
    res = _validate(tmp_path, [{"id": f"o{i}", **o} for i, o in enumerate(good)], tag="good")
    assert res["ok"] and res["warnings"] == [T.WARN_P03_B], res
    # the context primitives are not query primitives: `direction query` keeps refusing them
    for prim in S.CONTEXT_PRIMITIVES:
        assert prim not in Q.PRIMITIVES
        with pytest.raises(Q.QueryError, match="unknown primitive"):
            Q.observe(np.zeros((SR, 2)), SR, {"primitive": prim})


def test_fr2_e_masking_is_masking_matrix(song):
    from mankomix.core import objectives as O
    stems: dict = {}
    pobj = Project.open(song)
    mr.render_mix(pobj, variant_id="var_x", stems_out=stems, measure=False)
    res = O.resolve_objective(pobj, variant="var_x")
    lead = res["lead"]["stem"]
    meta = {t: {"role": (res["stems_meta"].get(t) or {}).get("role", "other"), "is_lead": t == lead,
                "importance": (res["stems_meta"].get(t) or {}).get("importance")} for t in stems}
    mm = masking_matrix(stems, SR, meta, genre=(res.get("genre") or {}).get("id"))
    src = S.StemSource(song, "var_x")
    for t in stems:
        assert S.observe(src, {"primitive": "masking", "target": t})["value"] == mm["per_target"][t]["buried_db"]
    assert S.observe(src, {"primitive": "masking", "target": "all"})["value"] == mm["overall"]["value"]
    assert S.observe(src, {"primitive": "masking", "target": "trk_a", "against": "trk_c"})["value"] == \
        mm["matrix"]["trk_a"]["trk_c"]
    # a section cuts every track before the call
    cut = {t: x[int(1.5 * SR):] for t, x in stems.items()}
    ms = masking_matrix(cut, SR, meta, genre=(res.get("genre") or {}).get("id"))
    r = S.observe(src, {"primitive": "masking", "target": "trk_b", "section": "sec2"},
                  sections=D._Project(song).sections())
    assert r["value"] == ms["per_target"]["trk_b"]["buried_db"] and r["range_s"] == [1.5, 3.0]


def test_refsheet_uses_the_shared_cache_check():
    import inspect
    from mankomix.director import refsheet as RSH
    src = inspect.getsource(RSH._project_stems)
    assert "cleanup_cache_error" in src and "_cache_valid" not in src
