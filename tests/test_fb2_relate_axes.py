"""X-04 overlap axes, with pre-implementation API and CLI byte snapshots."""
from __future__ import annotations

import hashlib
import json

import numpy as np
import pytest

from mankomix.cli.main import main
from mankomix.core import mixrender as MR
from mankomix.director import placement as P
from mankomix.director import relate as R
from tests import test_fbreview_stemobs as FS
from tests.test_fbreview_relate import _four, _local_home, song


# Captured from the unmodified implementation using the existing _four fixture.
LEGACY = {
    "None:3": {"api": "9bf42f02161d02219507225349a16ca315d4fdbe63d6ca59e1f753398a698add",
               "cli": "7de620260f65561f4ac1dcbf37f7b1e6fe548d1b19be64b50a4372720ef0c0d7"},
    "sec2:1": {"api": "ec618eac1b09fe0cd4217415b45f8facc25b253be3793828cb8fded64b0c598a",
               "cli": "ab52e7bf76e59ac3a8cb75f579c692454137764dc55add6902521db0dbd92e66"},
}


def _bytes(value):
    return json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")


@pytest.mark.parametrize("section,top", [(None, 3), ("sec2", 1)])
def test_flagless_preimplementation_bytes(song, section, top, capsys, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("flagless relate must not measure axes")
    monkeypatch.setattr(P, "activity", forbidden)
    key = f"{section}:{top}"
    out = R.stem_relate(song, section=section, top=top)
    assert "axes" not in out
    assert hashlib.sha256(_bytes(out)).hexdigest() == LEGACY[key]["api"]
    args = ["direction", "stems", "relate", "--project", str(song), "--top", str(top)]
    if section is not None:
        args += ["--section", section]
    assert main(args) == 0
    captured = capsys.readouterr()
    assert not captured.err
    assert hashlib.sha256(captured.out.encode("utf-8")).hexdigest() == LEGACY[key]["cli"]


def _tone(hz=750, starts=(0.5, 1.5, 2.5), duration=0.2):
    t = np.arange(FS.N) / FS.SR
    x = np.zeros(FS.N)
    for start in starts:
        mask = (t >= start) & (t < start + duration)
        x[mask] = 0.1 * np.sin(2 * np.pi * hz * t[mask])
    return np.column_stack([x, x])


@pytest.mark.parametrize("case", ["same", "far_band", "alternate", "wide", "octave", "silent"])
def test_synthetic_axes(tmp_path, case):
    a = _tone()
    b = {"same": lambda: _tone(875), "far_band": lambda: _tone(6000),
         "alternate": lambda: _tone(875, (1.0, 2.0)), "wide": lambda: _tone(875),
         "octave": lambda: _tone(1500), "silent": lambda: np.zeros_like(a)}[case]()
    if case == "wide":
        a[:, 1] = 0
        b[:, 0] = 0
    project = FS._make(tmp_path / "pair", {"a": a, "b": b}, fx=False)
    before = FS._tree(tmp_path)
    out = R.stem_relate(project, axes=True)
    assert FS._tree(tmp_path) == before
    assert _bytes(out) == _bytes(R.stem_relate(project, axes=True))
    axes = out["axes"]
    assert list(axes) == ["pairs", "all_axes", "thresholds", "reliability", "note"]
    assert axes["thresholds"] == {"band": 0.5, "time": 0.5, "length": 0.5, "space": 0.25}
    assert axes["note"] == ("4 軸とも重なる組は、まず見る所の候補であって、問題の判定ではない。"
                            "意図した重なり・一体感もある。前後（距離）の軸は測っていない")
    row, = axes["pairs"]
    assert list(row) == ["a", "b", "band_overlap", "co_onset_ratio", "co_active_ratio",
                         "same_octave_time", "image_distance", "overlapping"]
    assert [row["a"], row["b"]] == ["trk_a", "trk_b"]
    for key in ("band_overlap", "co_onset_ratio", "co_active_ratio", "same_octave_time", "image_distance"):
        assert row[key] is None or (0 <= row[key] <= 1 and row[key] == round(row[key], 3))
    if case == "same":
        assert row["overlapping"] == ["band", "time", "length", "space"]
        assert axes["all_axes"] == [["trk_a", "trk_b"]]
        assert row["same_octave_time"] == 1.0
    elif case == "far_band":
        assert row["band_overlap"] < 0.05 and "band" not in row["overlapping"]
    elif case == "alternate":
        assert row["co_active_ratio"] < 0.05 and "length" not in row["overlapping"]
        assert row["co_onset_ratio"] == 0
    elif case == "wide":
        assert row["image_distance"] == 1 and "space" not in row["overlapping"]
    elif case == "octave":
        assert row["same_octave_time"] == 0
    else:
        assert row["co_active_ratio"] == row["co_onset_ratio"] == 0
        assert row["same_octave_time"] == 0 and row["image_distance"] is None
        assert row["overlapping"] == []


def test_axes_cli_section_variant_and_only_addition(song, capsys):
    before = FS._tree(song)
    kwargs = {"variant": "v_a12", "section": "sec2", "top": 1}
    plain = R.stem_relate(song, **kwargs)
    out = R.stem_relate(song, axes=True, **kwargs)
    assert _bytes({k: v for k, v in out.items() if k != "axes"}) == _bytes(plain)
    pairs = out["axes"]["pairs"]
    assert [(r["a"], r["b"]) for r in pairs] == [
        (a, b) for i, a in enumerate(out["tracks"]) for b in out["tracks"][i + 1:]]
    assert len(pairs) == 6
    args = ["direction", "stems", "relate", "--project", str(song), "--axes",
            "--variant", "v_a12", "--section", "sec2", "--top", "1"]
    assert main(args) == 0
    first = capsys.readouterr()
    assert not first.err and json.loads(first.out) == out
    assert main(args) == 0
    assert capsys.readouterr().out == first.out
    assert FS._tree(song) == before


@pytest.mark.parametrize("stale", [False, True])
def test_axes_cache_errors_before_render(song, monkeypatch, capsys, stale):
    if stale:
        path = song / "project.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        variant = next(v for v in data["variants"] if v["id"] == "v_unclean")
        variant["track_overrides"]["trk_a"]["cleanup"]["applied"]["assets"]["ast_a"]["asset_sha256"] = "0" * 64
        path.write_text(json.dumps(data), encoding="utf-8")
    before = FS._tree(song)
    def forbidden(*args, **kwargs):
        pytest.fail("invalid cleanup cache must not render")
    monkeypatch.setattr(MR, "render_mix", forbidden)
    with pytest.raises(R.StemCacheError):
        R.stem_relate(song, variant="v_unclean", axes=True)
    assert main(["direction", "stems", "relate", "--project", str(song),
                 "--axes", "--variant", "v_unclean"]) != 0
    assert json.loads(capsys.readouterr().out)["error"]
    assert FS._tree(song) == before


@pytest.mark.parametrize("a,b,want", [
    ([0.1], [0.115], 1.0), ([0.115], [0.1], 1.0),
    ([0.1], [0.116], 0.0), ([0.1, 0.5, 1.0], [0.11, 2.0], 0.5),
    ([0.1, 0.11], [0.105, 1.0], 0.5), ([], [0.1], 0.0),
])
def test_onset_tolerance_and_smaller_denominator(a, b, want):
    assert R._co_onsets(a, b) == want
    assert R._co_onsets(b, a) == want


def test_octave_time_tracks_changing_frequency_and_channel_power():
    t = np.arange(FS.N) / FS.SR
    a = 0.1 * np.sin(2 * np.pi * 750 * t)
    b = a.copy()
    b[FS.N // 2:] = 0.1 * np.sin(2 * np.pi * 1500 * t[FS.N // 2:])
    # Anti-phase stereo retains octave energy even though mono onsets cancel.
    out = R._axes({"trk_a": np.column_stack([a, -a]),
                   "trk_b": np.column_stack([b, -b])}, FS.SR)
    row, = out["pairs"]
    assert row["same_octave_time"] == pytest.approx(0.5, abs=0.02)
    assert row["co_active_ratio"] == 1
    assert row["co_onset_ratio"] == 0
    assert "time" not in row["overlapping"]


def test_activity_smaller_denominator_and_short_track_padding():
    a = _tone(starts=(0.5, 1.5), duration=0.2)
    b = _tone(starts=(0.5,), duration=0.2)[:FS.SR]
    row, = R._axes({"trk_a": a, "trk_b": b}, FS.SR)["pairs"]
    # Every active frame of the shorter track is also active in the longer one.
    assert row["co_active_ratio"] == 1
    assert row["same_octave_time"] == 1


def test_axes_use_selected_section(tmp_path):
    a, b = _tone(starts=(0.5, 2.0)), _tone(6000, starts=(0.5,))
    b += _tone(875, starts=(2.0,))
    project = FS._make(tmp_path / "section_pair", {"a": a, "b": b}, fx=False)
    before = FS._tree(tmp_path)
    early = R.stem_relate(project, section="sec1", axes=True)["axes"]
    late = R.stem_relate(project, section="sec2", axes=True)["axes"]
    assert early["pairs"][0]["band_overlap"] < 0.05
    assert early["all_axes"] == []
    assert late["all_axes"] == [["trk_a", "trk_b"]]
    assert FS._tree(tmp_path) == before
