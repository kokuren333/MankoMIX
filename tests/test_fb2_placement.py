"""X-03 placement: known synthetic answers, read-only API and CLI contracts."""
from __future__ import annotations

import json
from unittest.mock import patch

import numpy as np
import pytest

from mankomix.cli.main import main
from mankomix.core import mixrender as MR
from mankomix.core import remix as RM
from mankomix.core.project import Project
from mankomix.director import placement as P
from tests import test_fbreview_stemobs as FS


@pytest.fixture(autouse=True)
def local_home(tmp_path, monkeypatch):
    monkeypatch.setenv("MANKOMIX_HOME", str(tmp_path / "home"))


def _tone(hz, start=0.0, end=FS.SECS):
    t = np.arange(FS.N) / FS.SR
    x = 0.1 * np.sin(2 * np.pi * hz * t)
    x[(t < start) | (t >= end)] = 0
    return np.column_stack([x, x])


@pytest.fixture
def song(tmp_path):
    return FS._make(tmp_path / "song", {
        "a": _tone(1000, 0, 1.5), "b": _tone(375),
        "z": np.zeros((FS.N, 2))}, fx=False, variants=FS.VARIANTS)


def _json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def _analysis(song, bpm=120, confidence=0.5):
    # Write via the existing project-music cache path, injecting only its summary.
    with patch.object(RM, "_music_summary", return_value={"bpm": bpm, "bpm_confidence": confidence}):
        RM.project_music(Project.open(song))


def _floor(song, sections):
    path = song / "cache" / "proposals" / "mxp_floor.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["sections"] = sections
    path.write_text(_json(data), encoding="utf-8")


def _click_song(tmp_path):
    x = np.zeros(FS.N)
    for t in (0.5, 1.0, 1.5, 2.0, 2.5):
        x[int(t * FS.SR)] = 0.5
    song = FS._make(tmp_path / "clicks", {"a": np.column_stack([x, x]),
                                          "z": np.zeros((FS.N, 2))}, fx=False)
    _floor(song, [{"id": "all", "start_s": 0, "end_s": 3}])
    return song


def test_known_bands_levels_silence_schema_and_determinism(song, tmp_path):
    before = FS._tree(tmp_path)
    out = P.placement(song)
    assert _json(out) == _json(P.placement(song))
    assert FS._tree(tmp_path) == before
    assert list(out) == ["kind", "signal", "sections", "tracks", "cells", "reliability", "note"]
    assert out["kind"] == "direction_stem_placement"
    assert out["signal"] == "mix_stage_dry"
    assert out["tracks"] == ["trk_a", "trk_b", "trk_z"]
    assert out["sections"] == [{"id": "sec1", "t0_s": 0.0, "t1_s": 1.5},
                                {"id": "sec2", "t0_s": 1.5, "t1_s": 3.0}]
    a, b = (out["cells"][tid]["sec1"] for tid in ("trk_a", "trk_b"))
    assert list(a) == ["active_ratio", "level_active_db", "activity_share", "bands", "occupied_hz",
                       "onset", "sustain", "image_position", "side_ratio_db", "declared_roles"]
    assert list(a["bands"]) == ["sub", "bass", "lowmid", "mid", "highmid", "air"]
    assert a["bands"]["mid"] == b["bands"]["lowmid"] == 1.0
    assert a["occupied_hz"][0] <= 1000 <= a["occupied_hz"][1]
    assert a["level_active_db"] == pytest.approx(-23.010, abs=0.01)
    assert a["active_ratio"] == b["active_ratio"] == 1.0
    assert a["activity_share"] == b["activity_share"] == 0.5
    assert out["cells"]["trk_b"]["sec2"]["activity_share"] == 1.0
    assert out["cells"]["trk_a"]["sec2"] is None
    assert out["cells"]["trk_z"] == {"sec1": None, "sec2": None}
    assert all(c is None or c["declared_roles"] is None
               for row in out["cells"].values() for c in row.values())
    assert out["reliability"] == {"bands": "high", "active_ratio": "high", "onset": "medium",
                                  "sustain": "medium", "roles": "not_decided"}
    assert out["note"] == ("値は関係と配置の記述で、良し悪しを言わない。役割は機械が決めない。"
                           "鳴り始めは密な素材で当てにならない。読みは指揮者の〔推定〕")


@pytest.mark.parametrize("confidence", [None, 0.499, 0.5, 0.9])
def test_click_rate_and_confidence_threshold(tmp_path, confidence):
    song = _click_song(tmp_path)
    if confidence is not None:
        _analysis(song, confidence=confidence)
    before = FS._tree(tmp_path)
    onset = P.placement(song)["cells"]["trk_a"]["all"]["onset"]
    assert onset["count"] == 5
    assert onset["per_s"] == 1.667
    if confidence is None or confidence < 0.5:
        assert onset["grid_offset_ms_median"] is None
    else:
        # Detector resolution: the five on-grid impulses peak up to 8 ms early.
        assert onset["grid_offset_ms_median"] == pytest.approx(-5, abs=4)
    assert FS._tree(tmp_path) == before


def test_grid_uses_absolute_time_and_signed_nearest_sixteenth(song, monkeypatch):
    _analysis(song)
    _floor(song, [{"id": "offset", "start_s": 0.13, "end_s": 1.13}])
    monkeypatch.setattr(P, "onsets", lambda *a: [0.01, 0.10, 0.20])
    # Absolute attacks .14, .23, .33; nearest .125, .25, .375 => +15,-20,-45 ms.
    row = P.placement(song)["cells"]["trk_a"]["offset"]["onset"]
    assert row == {"count": 3, "per_s": 3.0, "grid_offset_ms_median": -20.0}


@pytest.mark.parametrize("bpm,confidence", [(None, 1), (0, 1), (-120, 1), (120, None)])
def test_unusable_tempo_does_not_compute_or_write(song, tmp_path, monkeypatch, bpm, confidence):
    _analysis(song, bpm=bpm, confidence=confidence)
    monkeypatch.setattr(RM, "project_music", lambda *a: pytest.fail("must only read saved analysis"))
    monkeypatch.setattr(RM, "_music_summary", lambda *a: pytest.fail("must not compute tempo"))
    before = FS._tree(tmp_path)
    assert P.placement(song)["cells"]["trk_a"]["sec1"]["onset"]["grid_offset_ms_median"] is None
    assert FS._tree(tmp_path) == before


@pytest.mark.parametrize("case", ["missing", "old-version", "changed-assets", "no-attacks"])
def test_grid_null_when_analysis_unavailable_or_no_attacks(song, tmp_path, monkeypatch, case):
    if case != "missing":
        _analysis(song)
    if case == "old-version":
        path = next((song / "cache" / "remix").glob("music_*.json"))
        data = json.loads(path.read_text(encoding="utf-8"))
        data["version"] = -1
        path.write_text(_json(data), encoding="utf-8")
    elif case == "changed-assets":
        path = song / "project.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["assets"][0]["sha256"] = "0" * 64
        path.write_text(_json(data), encoding="utf-8")
    elif case == "no-attacks":
        monkeypatch.setattr(P, "onsets", lambda *a: [])
    monkeypatch.setattr(RM, "_music_summary", lambda *a: pytest.fail("must not compute tempo"))
    before = FS._tree(tmp_path)
    onset = P.placement(song)["cells"]["trk_a"]["sec1"]["onset"]
    assert onset["grid_offset_ms_median"] is None
    if case == "no-attacks":
        assert onset == {"count": 0, "per_s": 0.0, "grid_offset_ms_median": None}
    assert FS._tree(tmp_path) == before


def test_sustain_known_runs_and_section_clipping(tmp_path):
    short = _tone(1000, 0.5, 0.6) + _tone(1000, 1.0, 1.1)
    song = FS._make(tmp_path / "runs", {"long": _tone(1000, 0.5, 1.3), "short": short,
                                         "bed": _tone(375)}, fx=False)
    out = P.placement(song)["cells"]
    # 50 ms windows at a 10 ms hop extend both sides by 40 ms.
    assert out["trk_long"]["sec1"]["sustain"] == {"run_ms_median": 880.0}
    assert out["trk_short"]["sec1"]["sustain"] == {"run_ms_median": 180.0}
    assert out["trk_bed"]["sec2"]["sustain"] == {"run_ms_median": 1500.0}


def test_declarations_copied_verbatim_by_id_and_positive_overlap(song, tmp_path):
    rows = [{"section": "sec1", "lead": "trk_z", "roles": {"trk_a": ["unknown", "rhythm", "unknown"]}},
            {"section": {"t0_s": 1.4, "t1_s": 1.6}, "roles": {"trk_b": ["counter"]}},
            {"section": {"t0_s": 0, "t1_s": 1.5}, "roles": {}},
            {"section": "absent", "roles": {"trk_a": ["lead_melody"]}}]
    doc = FS._doc(tmp_path / "direction", {"frame": {"section_roles": rows}})
    before = FS._tree(tmp_path)
    out = P.placement(song, direction=doc)
    assert out["cells"]["trk_a"]["sec1"]["declared_roles"] == rows[:3]
    assert out["cells"]["trk_b"]["sec1"]["declared_roles"] == rows[:3]
    assert out["cells"]["trk_b"]["sec2"]["declared_roles"] == rows[1:2]
    assert out["cells"]["trk_z"]["sec1"] is None  # Declared lead does not create activity.
    assert FS._tree(tmp_path) == before
    out["cells"]["trk_a"]["sec1"]["declared_roles"][0]["roles"].clear()
    assert P.placement(song, direction=doc)["cells"]["trk_a"]["sec1"]["declared_roles"] == rows[:3]


def test_cli_variant_direction_determinism_and_readonly(song, tmp_path, capsys):
    doc = FS._doc(tmp_path / "direction", {"frame": {"section_roles": [{"section": "sec1", "roles": {}}]}})
    expected = P.placement(song, variant="v_a12", direction=doc)
    assert expected["cells"]["trk_a"]["sec1"]["level_active_db"] == pytest.approx(-35.010, abs=0.01)
    before = FS._tree(tmp_path)
    args = ["direction", "stems", "placement", "--project", str(song),
            "--variant", "v_a12", "--direction", str(doc)]
    assert main(args) == 0
    first = capsys.readouterr()
    assert not first.err and json.loads(first.out) == expected
    assert main(args) == 0
    assert capsys.readouterr().out == first.out
    assert FS._tree(tmp_path) == before


@pytest.mark.parametrize("case", ["unknown-track", "unknown-lead", "missing-cache", "stale-cache", "unknown-variant", "no-tracks"])
def test_input_errors_do_not_render_or_change_tree(song, tmp_path, monkeypatch, capsys, case):
    kwargs, args = {}, []
    if case in ("unknown-track", "unknown-lead"):
        row = {"section": "sec1", "roles": {"trk_missing": ["unknown"]}}
        if case == "unknown-lead":
            row = {"section": "sec1", "lead": "trk_missing", "roles": {}}
        doc = FS._doc(tmp_path / "direction", {"frame": {"section_roles": [row]}})
        kwargs["direction"] = doc
        args = ["--direction", str(doc)]
    elif case == "unknown-variant":
        kwargs["variant"] = "missing"
        args = ["--variant", "missing"]
    else:
        path = song / "project.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        for track in data["tracks"]:
            if case == "no-tracks":
                track["muted"] = True
            else:
                aid = track["clips"][0]["asset"]
                track["cleanup"] = {"applied": {"assets": {aid: {
                    "plan_hash": "f" * 16, "asset_sha256": "0" * 64 if case == "stale-cache" else None}}}}
        path.write_text(_json(data), encoding="utf-8")
    monkeypatch.setattr(MR, "render_mix", lambda *a, **k: pytest.fail("invalid input rendered"))
    before = FS._tree(tmp_path)
    with pytest.raises(P.PlacementInputError):
        P.placement(song, **kwargs)
    assert main(["direction", "stems", "placement", "--project", str(song), *args]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["error"] == "input_error"
    assert FS._tree(tmp_path) == before
