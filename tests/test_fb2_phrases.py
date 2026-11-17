"""X-06 phrases: synthetic boundaries, levels, margin ranking and G-3."""
from __future__ import annotations

import json

import numpy as np
import pytest

from mankomix.cli.main import main
from mankomix.core import mixrender as MR
from mankomix.director import phrases as P
from tests import test_fbreview_stemobs as FS


@pytest.fixture(autouse=True)
def local_home(tmp_path, monkeypatch):
    monkeypatch.setenv("MANKOMIX_HOME", str(tmp_path / "home"))


def _voice(spans, seconds=3.0):
    t = np.arange(round(FS.SR * seconds)) / FS.SR
    x = np.zeros_like(t)
    for a, b, amplitude in spans:
        m = (t >= a) & (t < b)
        x[m] = amplitude * np.sin(2 * np.pi * 1500 * t[m])
    return np.column_stack([x, x])


@pytest.fixture
def song(tmp_path):
    voice = _voice([(0.3, 0.7, 0.1), (0.9, 1.3, 0.1), (1.9, 2.5, 0.2)])
    backing = _voice([(0, 1.9, 0.01), (1.9, 2.5, 0.8), (2.5, 3, 0.01)])
    return FS._make(tmp_path / "song", {"a": voice, "b": backing}, fx=False)


def _json(out):
    return json.dumps(out, ensure_ascii=False, allow_nan=False)


def test_known_phrases_schema_boundaries_and_levels(song, tmp_path):
    before = FS._tree(tmp_path)
    out = P.phrases(song, "trk_a", min_gap_ms=100)
    assert _json(out) == _json(P.phrases(song, "trk_a", min_gap_ms=100))
    assert FS._tree(tmp_path) == before
    assert list(out) == ["kind", "signal", "track", "phrases", "low_margin", "reliability", "note"]
    assert out["kind"] == "direction_stem_phrases"
    assert out["track"] == "trk_a" and out["signal"] == "mix_stage_dry"
    assert out["reliability"] == {"phrases": "medium", "syllables": "not_provided"}
    assert out["note"] == "先に計算して書いても、見つけ間違いと直しすぎは起きる。効き目は実証していない"
    assert len(out["phrases"]) == 3
    for n, (row, (a, b)) in enumerate(zip(out["phrases"], [(0.3, 0.7), (0.9, 1.3), (1.9, 2.5)]), 1):
        assert list(row) == ["n", "t0_s", "t1_s", "level_db", "level_rel_median_db",
                             "head_db", "tail_db", "margin_db"]
        assert row["n"] == n
        assert row["t0_s"] == pytest.approx(a, abs=0.02)
        assert row["t1_s"] == pytest.approx(b, abs=0.02)
        assert row["level_rel_median_db"] == pytest.approx(0 if n < 3 else 6.12, abs=0.12)
        assert row["level_db"] == pytest.approx(-23.010 if n < 3 else -16.99, abs=0.4)
    # The centre boundaries include 15 ms of silence on each side of the burst.
    expected = 20 + 10 * np.log10(0.4 / 0.43)
    assert out["phrases"][0]["margin_db"] == pytest.approx(expected, abs=0.02)
    assert out["phrases"][-1]["margin_db"] == pytest.approx(-12.041, abs=0.05)
    for row in out["phrases"] + out["low_margin"]:
        assert all(not isinstance(v, float) or v == round(v, 3) for v in row.values())


@pytest.mark.parametrize("gap,count", [(0, 3), (100, 3), (250, 2), (1000, 1)])
def test_gap_changes_joining(song, gap, count):
    assert len(P.phrases(song, "trk_a", min_gap_ms=gap)["phrases"]) == count


def test_default_gap(song):
    assert _json(P.phrases(song, "trk_a")) == _json(P.phrases(song, "trk_a", min_gap_ms=250))


def test_loud_backing_ranks_first_and_silence_is_excluded(song):
    rows = P.phrases(song, "trk_a")["low_margin"]
    assert 0 < len(rows) <= 32
    assert all(1.95 <= r["t_s"] <= 2.45 for r in rows[:4])
    assert all(r["margin_db"] == pytest.approx(-12.041, abs=0.05) for r in rows[:4])
    assert [r["margin_db"] for r in rows] == sorted(r["margin_db"] for r in rows)
    assert all(any(a <= r["t_s"] < b for a, b in [(0.3, 0.7), (0.9, 1.3), (1.9, 2.5)]) for r in rows)


def test_margin_uses_sum_and_ignores_out_of_band_backing(tmp_path):
    voice = _voice([(0, 3, 0.1)])
    t = np.arange(FS.N) / FS.SR
    low = np.column_stack([np.sin(2 * np.pi * 100 * t)] * 2)
    song = FS._make(tmp_path / "sum", {"a": voice, "b": voice * 0.5, "c": voice * 0.25, "d": low}, fx=False)
    out = P.phrases(song, "trk_a")
    assert out["phrases"][0]["margin_db"] == pytest.approx(20 * np.log10(1 / 0.75), abs=0.02)


def test_head_tail_150ms_and_signal_endpoints(tmp_path):
    voice = _voice([(0, 0.15, 0.1), (0.15, 2.85, 0.2), (2.85, 3, 0.05)])
    song = FS._make(tmp_path / "edges", {"a": voice, "b": _voice([(0, 3, 0.01)])}, fx=False)
    row, = P.phrases(song, "trk_a")["phrases"]
    assert row["t0_s"] == 0 and row["t1_s"] == 3
    assert row["head_db"] == pytest.approx(-23.010, abs=0.01)
    assert row["tail_db"] == pytest.approx(-29.031, abs=0.01)
    assert row["level_rel_median_db"] == 0


def test_limit_32_and_repeatable_order(tmp_path):
    voice = _voice([(0, 5, 0.1)], seconds=5)
    song = FS._make(tmp_path / "long", {"a": voice, "b": voice * 0.5}, fx=False)
    out = P.phrases(song, "trk_a")
    rows = out["low_margin"]
    assert len(rows) == 32
    assert [r["t_s"] for r in rows] == pytest.approx(np.arange(32) * 0.1 + 0.05)
    assert all(r["margin_db"] == pytest.approx(6.021, abs=0.001) for r in rows)
    assert _json(out) == _json(P.phrases(song, "trk_a"))


@pytest.mark.parametrize("samples", [1, 100, FS.N])
def test_silence_and_short_signals(tmp_path, samples):
    song = FS._make(tmp_path / "short", {"a": np.zeros((samples, 2)),
                                            "b": np.ones((samples, 2)) * 0.01}, fx=False)
    before = FS._tree(tmp_path)
    out = P.phrases(song, "trk_a")
    assert out["phrases"] == out["low_margin"] == []
    assert FS._tree(tmp_path) == before


@pytest.mark.parametrize("gap", [-1, float("nan"), float("inf"), True, "250", None])
def test_bad_gap_is_input_error(song, gap):
    before = FS._tree(song)
    with pytest.raises(P.PhrasesInputError, match="min_gap_ms"):
        P.phrases(song, "trk_a", min_gap_ms=gap)
    assert FS._tree(song) == before


@pytest.mark.parametrize("case", ["missing-cache", "stale-cache", "unknown-track"])
def test_errors_precede_render_and_write_nothing(song, monkeypatch, capsys, case):
    track = "trk_missing" if case == "unknown-track" else "trk_a"
    if case != "unknown-track":
        path = song / "project.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["tracks"][0]["cleanup"] = {"applied": {"assets": {"ast_a": {
            "plan_hash": "f" * 16, "asset_sha256": "0" * 64 if case == "stale-cache" else None}}}}
        path.write_text(_json(data), encoding="utf-8")
    monkeypatch.setattr(MR, "render_mix", lambda *a, **k: pytest.fail("must fail before rendering"))
    monkeypatch.setattr(MR, "render_track", lambda *a, **k: pytest.fail("must not regenerate cleanup"))
    before = FS._tree(song)
    with pytest.raises(P.PhrasesInputError):
        P.phrases(song, track)
    assert main(["direction", "stems", "phrases", "--project", str(song), "--track", track]) == 1
    error = json.loads(capsys.readouterr().out)
    assert error["error"] == "input_error"
    assert FS._tree(song) == before


def test_cli_json_determinism_and_gap(song, capsys):
    args = ["direction", "stems", "phrases", "--project", str(song), "--track", "trk_a"]
    before = FS._tree(song)
    assert main(args) == 0
    first = capsys.readouterr()
    assert first.err == ""
    assert json.loads(first.out) == P.phrases(song, "trk_a")
    assert main(args) == 0
    assert capsys.readouterr().out == first.out
    assert main(args + ["--min-gap-ms", "100"]) == 0
    assert len(json.loads(capsys.readouterr().out)["phrases"]) == 3
    assert main(args + ["--min-gap-ms", "nan"]) == 1
    assert "min_gap_ms" in json.loads(capsys.readouterr().out)["message"]
    assert FS._tree(song) == before
