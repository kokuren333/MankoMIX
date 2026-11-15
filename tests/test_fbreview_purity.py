"""FR-6 (a)-(f): synthetic stem-content measurements, never project writes."""
from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import numpy as np
import pytest
from scipy import signal

from mankomix.core import cleanstage, mixplan, mixrender as MR
from mankomix.core.analysis.stems import reverb_metrics
from mankomix.core.measure import loudness as L
from mankomix.director import purity as P
from mankomix.director import query


SR = 16000
SECONDS = 20


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("MANKOMIX_HOME", str(tmp_path / "home"))


def _noise(seed, seconds=SECONDS, sr=SR):
    return np.random.default_rng(seed).normal(0, 0.08, (int(seconds * sr), 2))


def _project(tmp_path, material, *, sr=SR):
    """Use real assets and renderer, with deterministic project IDs and hashes."""
    root = tmp_path / "song.mmx"
    assets, tracks = [], []
    for name, x in material.items():
        path = root / "assets" / f"{name}.wav"
        cleanstage.write_f32_wav(path, x, sr)
        assets.append({"id": f"ast_{name}", "path": f"assets/{name}.wav", "origin": "native_stem",
                       "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "channels": 2,
                       "sample_rate": sr, "length_samples": len(x)})
        tracks.append({"id": f"trk_{name}", "kind": "audio", "role": "other", "clips": [
            {"id": f"clp_{name}", "asset": f"ast_{name}"}]})
    data = {"schema_version": 1, "assets": assets, "tracks": tracks,
            "timebase": {"sample_rate": sr, "length_samples": max(map(len, material.values()))},
            "buses": [{"id": "bus_mix", "kind": "mix", "chain": []}]}
    _save(root, data)
    return root, data


def _save(root, data):
    (root / "project.json").write_text(json.dumps(data), encoding="utf-8")


def _snapshot(root):
    return {p.relative_to(root).as_posix(): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
            for p in root.rglob("*") if p.is_file()}


def _cache(root, data, name, audio):
    """Install an applied cache with the same sidecar/hash contract as cleanstage."""
    asset = next(a for a in data["assets"] if a["id"] == f"ast_{name}")
    phash = "b" * 64
    path = root / cleanstage.cache_rel(asset["sha256"], phash)
    cleanstage.write_f32_wav(path, audio, SR)
    cleanstage._sidecar(path).write_text(json.dumps({
        "asset_sha256": asset["sha256"], "plan_hash": phash,
        "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}), encoding="utf-8")
    track = next(t for t in data["tracks"] if t["id"] == f"trk_{name}")
    track["cleanup"] = {"applied": {"assets": {asset["id"]: {
        "asset_sha256": asset["sha256"], "plan_hash": phash}}}}
    _save(root, data)
    return path


def test_a_independent_noise_has_no_shared_components(tmp_path):
    root, _ = _project(tmp_path, {"a": _noise(10), "b": _noise(11)})
    out = P.stem_purity(root)
    assert out["kind"] == "direction_stem_purity"
    assert out["signal"] == "post_clean_pre_chain"
    assert out["note"] == P.NOTE
    assert out["mixture"] is None
    assert all(row["shared"] == [] for row in out["tracks"].values())


def test_b_minus_12_db_bleed_is_reported_and_louder_in_b(tmp_path):
    # Different spectral contents make the coherent energy's louder side
    # identifiable. Equal-spectrum white-noise beds need not identify origin.
    a = signal.sosfilt(signal.butter(6, 1800, fs=SR, output="sos"), _noise(20), axis=0)
    b = signal.sosfilt(signal.butter(6, 2800, fs=SR, btype="highpass", output="sos"), _noise(21), axis=0)
    a *= 0.08 / np.sqrt(np.mean(a * a))
    b *= 0.08 / np.sqrt(np.mean(b * b))
    root, _ = _project(tmp_path, {"a": a + b * 10 ** (-12 / 20), "b": b})
    row = P.stem_purity(root)["tracks"]["trk_a"]["shared"]
    assert len(row) == 1 and row[0]["track"] == "trk_b"
    assert row[0]["shared_power_db"] == pytest.approx(-12, abs=2)
    assert row[0]["louder_in"] == "trk_b"


def _independent_pitched(seed):
    """A pitched sustained sound with independently evolving phase per partial.

    A fixed-phase pure sine pair is linearly coherent even with a random
    initial phase. Independently excited narrow-band partials model distinct
    performances, with the same pitch and no stable phase relation.
    """
    rng = np.random.default_rng(seed)
    t = np.arange(SECONDS * SR) / SR
    sound = np.zeros_like(t)
    for harmonic in range(1, 7):
        baseband = signal.sosfilt(signal.butter(2, 35, fs=SR, output="sos"),
                                  rng.normal(size=(len(t), 2)), axis=0)
        phase = 2 * np.pi * 220 * harmonic * t
        sound += (baseband[:, 0] * np.cos(phase) + baseband[:, 1] * np.sin(phase)) / harmonic
    sound *= 0.08 / np.sqrt(np.mean(sound ** 2))
    return np.column_stack([sound, sound])


def test_c_same_pitch_independent_synthetic_performances_are_not_shared(tmp_path):
    a, b = _independent_pitched(30), _independent_pitched(31)
    f, pa = signal.welch(a[:, 0], fs=SR, nperseg=2048)
    _, pb = signal.welch(b[:, 0], fs=SR, nperseg=2048)
    assert 180 < f[np.argmax(pa)] < 260 and 180 < f[np.argmax(pb)] < 260
    # Check the specified estimator itself is below the reporting threshold.
    f, c = signal.coherence(a[:, 0], b[:, 0], **P.SPECTRUM)
    band = (f >= 100) & (f <= 7000)
    assert all(10 * np.log10(np.sum(c[band] * p[band]) / np.sum(p[band])) < -20 for p in (pa, pb))
    root, _ = _project(tmp_path, {"a": a, "b": b})
    assert all(r["shared"] == [] for r in P.stem_purity(root)["tracks"].values())


def test_d_short_and_silent_stems(tmp_path, monkeypatch):
    root, _ = _project(tmp_path, {"short": _noise(40, seconds=9.99), "long": _noise(41),
                                  "silent": np.zeros((SECONDS * SR, 2)), "quiet": _noise(42) * 1e-4})
    def no_pair(*args, **kwargs):
        pytest.fail("short/silent/below -70 dBFS pairs must not be measured")
    monkeypatch.setattr(P.signal, "coherence", no_pair)
    out = P.stem_purity(root)["tracks"]
    assert out["trk_short"]["shared"] is None
    assert out["trk_short"]["reason"] == "too_short"
    assert out["trk_long"]["shared"] == []
    assert out["trk_silent"]["shared"] == []
    assert out["trk_quiet"]["shared"] == []
    assert out["trk_silent"]["baked_reverb"] is None
    assert out["trk_silent"]["baked_dynamics"]["lufs_integrated"] is None
    json.dumps(out, allow_nan=False)


@pytest.mark.parametrize("seconds,short", [(9.999, True), (10.0, False)])
def test_d_ten_second_boundary(tmp_path, seconds, short):
    root, _ = _project(tmp_path, {"a": _noise(43, seconds=seconds)})
    row = P.stem_purity(root)["tracks"]["trk_a"]
    assert (row["shared"] is None) is short


def test_d_common_timeline_overlap_must_be_ten_seconds(tmp_path, monkeypatch):
    root, data = _project(tmp_path, {"a": _noise(44, seconds=12), "b": _noise(45, seconds=12)})
    data["tracks"][1]["clips"][0]["timeline_start"] = 3 * SR
    _save(root, data)
    monkeypatch.setattr(P.signal, "coherence", lambda *a, **k: pytest.fail("only 9 s overlap"))
    rows = P.stem_purity(root)["tracks"]
    assert all(row["shared"] is None and row["reason"] == "too_short" for row in rows.values())


def test_e_r22_baked_matches_floor_planner(tmp_path, monkeypatch):
    t = np.arange(SR * 2) / SR
    hot = np.column_stack([np.sin(2 * np.pi * 1000 * t)] * 2)
    root, data = _project(tmp_path, {"hot": hot, "cold": hot * 0.3, "crest": _noise(50, seconds=2)})
    out = P.stem_purity(root)["tracks"]
    features = {}
    for track in data["tracks"]:
        x, sr, _ = MR.render_track(P.Project.open(root), track["id"], apply_chain=False, apply_fader=False)
        features[track["id"]] = {"level": {"peak_dbfs": float(L.sample_peak_dbfs(x)),
                                          "lufs_integrated": float(L.integrated(x, sr))}}
    planner = SimpleNamespace(rules=mixplan.mix_rules(), data=data,
                              tracks={t["id"]: t for t in data["tracks"]})
    restrictions = mixplan._Planner._restrictions(planner, {"features": features})
    assert out["trk_hot"]["flags"]["r22_baked"] is True
    assert out["trk_cold"]["flags"]["r22_baked"] is False
    for tid, row in out.items():
        assert row["flags"]["r22_baked"] == (restrictions.get(tid, {}).get("source") == "baked")
    bd = planner.rules["r22"]["baked_detection"]
    # Pin >= at the peak boundary and strict < at the PLR boundary before rounding.
    for peak, plr in [(bd["peak_dbfs_min"], bd["plr_max_db"] - 0.0001),
                      (bd["peak_dbfs_min"], bd["plr_max_db"]),
                      (bd["peak_dbfs_min"] - 0.0001, bd["plr_max_db"] - 1)]:
        level = {"peak_dbfs": peak, "lufs_integrated": peak - plr}
        planner.tracks = {"trk_hot": data["tracks"][0]}
        expected = mixplan._Planner._restrictions(planner, {"features": {"trk_hot": {"level": level}}})
        with monkeypatch.context() as patch:
            patch.setattr(L, "sample_peak_dbfs", lambda x: peak)
            patch.setattr(L, "integrated", lambda x, sr: peak - plr)
            measured = P._measure(hot, SR, bd)
        assert measured["r22_baked"] == bool(expected)


def test_f_read_only_clean_signal_and_determinism(tmp_path):
    root, data = _project(tmp_path, {"b": _noise(61), "a": _noise(60)})
    cleaned = _noise(62)
    _cache(root, data, "a", cleaned)
    track = data["tracks"][1]
    track.update({"gain_db": -30, "pan": {"position": 1, "width": 0},
                  "chain": [{"id": "prc_gain", "type": "gain", "params": {"gain_db": -20}}]})
    values = {"residual_db": -32.12345, "correlation": 0.98765, "residual_after_gain_fit_db": -40.76543}
    data["ingest"] = {"checks": [{"check": "stem_sum_consistency", "values": values}]}
    data["mix"] = {"applied": {"proposal_id": "mxp_floor"}}
    proposals = root / "cache" / "proposals"
    proposals.mkdir(parents=True)
    (proposals / "mxp_floor.json").write_text(json.dumps({"stage": "mix", "proposal_id": "mxp_floor",
        "restrictions": {"trk_a": {"source": "declared"}}}), encoding="utf-8")
    # A newer unapplied proposal must not replace the applied floor's flags.
    (proposals / "mxp_other.json").write_text(json.dumps({"stage": "mix", "proposal_id": "mxp_other",
        "proposed_at": "9999", "restrictions": {"trk_b": {}}}), encoding="utf-8")
    _save(root, data)
    before = _snapshot(root)
    out = P.stem_purity(root)
    again = P.stem_purity(root)
    assert json.dumps(out, ensure_ascii=False, allow_nan=False) == json.dumps(again, ensure_ascii=False, allow_nan=False)
    assert _snapshot(root) == before
    row = out["tracks"]["trk_a"]
    x = np.asarray(cleaned, dtype=np.float32).astype(float)
    assert row["baked_dynamics"]["peak_dbfs"] == round(L.sample_peak_dbfs(x), 3)
    for primitive, key in [("correlation", "correlation"), ("side_ratio", "side_ratio_db")]:
        observed = query.observe(x, SR, {"primitive": primitive})["value"]
        assert row["baked_width"][key] == pytest.approx(observed, abs=0.0006)
    rv = reverb_metrics(x, SR)
    expected_reverb = {"dr_db": rv["dr_db"], "rt60_mid_s": rv["rt60_mid_s"]}
    assert row["baked_reverb"] == (P._ordered(expected_reverb) if any(
        v is not None for v in expected_reverb.values()) else None)
    assert row["flags"] == {"floor_restricted": True, "origin": "native_stem", "r22_baked": False}
    assert out["tracks"]["trk_b"]["flags"]["floor_restricted"] is False
    assert out["mixture"] == P._ordered(values)
    def ordered(value):
        if isinstance(value, dict):
            assert list(value) == sorted(value)
            for v in value.values():
                ordered(v)
        elif isinstance(value, list):
            for v in value:
                ordered(v)
        elif isinstance(value, float):
            assert np.isfinite(value) and value == round(value, 3)
    ordered(out)


@pytest.mark.parametrize("damage", ["missing", "sidecar", "hash", "asset", "plan"])
def test_f_invalid_cache_fails_before_render_without_writes(tmp_path, monkeypatch, damage):
    root, data = _project(tmp_path, {"a": _noise(70, seconds=1), "z": _noise(71, seconds=1)})
    path = _cache(root, data, "z", _noise(72, seconds=1))
    entry = data["tracks"][1]["cleanup"]["applied"]["assets"]["ast_z"]
    if damage == "missing":
        path.unlink()
    elif damage == "sidecar":
        cleanstage._sidecar(path).write_text("{}", encoding="utf-8")
    elif damage == "hash":
        path.write_bytes(path.read_bytes() + b"changed")
    elif damage == "asset":
        entry["asset_sha256"] = "c" * 64
    else:
        entry["plan_hash"] = "d" * 64
    _save(root, data)
    monkeypatch.setattr(MR, "render_track", lambda *a, **k: pytest.fail("render must not start"))
    before = _snapshot(root)
    with pytest.raises(P.PurityInputError, match="cache is missing or stale"):
        P.stem_purity(root)
    assert _snapshot(root) == before


def test_selection_honors_audibility_and_keeps_comparison_partners(tmp_path):
    b = _noise(81)
    root, data = _project(tmp_path, {"a": _noise(80) + b * 10 ** (-12 / 20), "b": b, "muted": _noise(82)})
    data["tracks"][2]["muted"] = True
    _save(root, data)
    assert set(P.stem_purity(root)["tracks"]) == {"trk_a", "trk_b"}
    out = P.stem_purity(root, tracks=["trk_a"])["tracks"]
    assert list(out) == ["trk_a"]
    assert out["trk_a"]["shared"][0]["track"] == "trk_b"
    assert list(P.stem_purity(root, tracks="trk_muted")["tracks"]) == ["trk_muted"]
    data["tracks"][1]["solo"] = True
    _save(root, data)
    assert list(P.stem_purity(root)["tracks"]) == ["trk_b"]
    for invalid in (["trk_unknown"], []):
        with pytest.raises(P.PurityInputError):
            P.stem_purity(root, invalid)
    with pytest.raises(P.PurityInputError):
        P.stem_purity(root / "missing")


def test_shared_is_sorted_capped_and_resampled(tmp_path):
    sr = 32000
    x = _noise(90, seconds=10, sr=sr)
    root, _ = _project(tmp_path, {name: x * (i + 1) / 8 for i, name in enumerate("hgfedcba")}, sr=sr)
    rows = P.stem_purity(root)["tracks"]
    for tid, row in rows.items():
        assert len(row["shared"]) == 5
        assert all(r["shared_power_db"] == pytest.approx(0, abs=0.001) for r in row["shared"])
        assert all(r["track"] != tid for r in row["shared"])
        assert [r["shared_power_db"] for r in row["shared"]] == sorted(
            [r["shared_power_db"] for r in row["shared"]], reverse=True)


def test_flags_are_information_even_for_separated_and_declared_tracks(tmp_path):
    root, data = _project(tmp_path, {"a": _noise(100, seconds=1)})
    data["assets"][0]["origin"] = "separated"
    data["tracks"][0]["restrictions"] = {"operations": ["balance"]}
    _save(root, data)
    row = P.stem_purity(root)["tracks"]["trk_a"]
    assert row["flags"]["origin"] == "separated"
    assert row["flags"]["floor_restricted"] is False


def test_shared_matches_exact_coherent_power_definition():
    b = _noise(21).mean(axis=1)
    a = _noise(20).mean(axis=1) + b * 10 ** (-12 / 20)
    audio = {"trk_a": np.column_stack([a, a]), "trk_b": np.column_stack([b, b])}
    spans = {tid: (0, len(x)) for tid, x in audio.items()}
    rows, short = P._shared(audio, spans, SR)
    params = {"fs": 16000, "window": "hann", "nperseg": 2048, "noverlap": 1024}
    f, coherence = signal.coherence(a, b, **params)
    _, pa = signal.welch(a, **params)
    _, pb = signal.welch(b, **params)
    band = (f >= 100) & (f <= 7000)
    ca, cb = [float(np.sum(coherence[band] * p[band])) for p in (pa, pb)]
    expected_louder = "trk_a" if ca >= cb else "trk_b"
    assert not short
    for tid, p, coherent in [("trk_a", pa, ca), ("trk_b", pb, cb)]:
        assert rows[tid][0]["shared_power_db"] == pytest.approx(10 * np.log10(coherent / np.sum(p[band])))
        assert rows[tid][0]["louder_in"] == expected_louder


def test_empty_clip_list_is_too_short_without_rendering(tmp_path):
    root, data = _project(tmp_path, {"a": _noise(110, seconds=1)}, sr=32000)
    data["tracks"][0]["clips"] = []
    _save(root, data)
    row = P.stem_purity(root)["tracks"]["trk_a"]
    assert row["shared"] is None and row["reason"] == "too_short"
    assert row["baked_reverb"] is None and row["baked_width"] is None
    assert all(value is None for value in row["baked_dynamics"].values())
