"""BB-18 end-to-end tests on synthetic tmp_path projects; no production op."""
from __future__ import annotations

import copy
import json

import numpy as np
import pytest

from mankomix.core import api, audio_io, journal, mixrender as mr
from mankomix.core.adapters.file import FileAdapter
from mankomix.core.hashing import sha256_file
from mankomix.core.ingest.checks import run_checks
from mankomix.core.project import Project
from mankomix.director import derived as D, edit as E
from tests.fixtures import synth

SR = 24000
DIR = "dir_w2k"
TRACK = "trk_guitar"


@pytest.fixture(autouse=True)
def local_home(tmp_path, monkeypatch):
    monkeypatch.setenv("MANKOMIX_HOME", str(tmp_path / "home"))


def make(tmp_path, sr=SR, channels=2):
    source = tmp_path / "stems"
    t = np.arange(sr) / sr
    x = np.stack([0.1 * np.sin(2 * np.pi * (330 + k * 110) * t) for k in range(channels)], axis=1)
    synth.write_wav(source / "guitar.wav", x, sr)
    synth.write_wav(source / "vocals.wav", x * 0.7, sr)
    project = Project.create(tmp_path / "song", title="derived test")
    FileAdapter().fetch(source, project, actor="human")
    return project.root


@pytest.fixture
def song(tmp_path):
    return make(tmp_path)


def invert(x, sr, params):
    assert x.dtype == np.float64 and x.ndim == 2
    return x * params["polarity"]


def apply(song, move="m01", start=6000, end=12000, **overrides):
    kwargs = dict(op="test_polarity", params={"polarity": -1.0}, code_version="test-1", calculate=invert)
    kwargs.update(overrides)
    return D.apply(song, DIR, move, TRACK, start, end, **kwargs)


def ledger(song):
    return json.loads(E.ledger_path(song, DIR).read_text(encoding="utf-8"))


def render(song):
    return mr.render_mix(Project.open(song))[0]


def raw(song):
    return E.raw_track(song, TRACK)[0]


def cache(song, row):
    return song / "cache" / "derived" / (row["key"] + ".wav")


@pytest.mark.parametrize("sr", [44100, 48000, 96000])
@pytest.mark.parametrize("channels", [1, 2])
def test_full_route_and_bit_identical_revert(tmp_path, sr, channels):
    song = make(tmp_path, sr, channels)
    project = Project.open(song)
    before_assets = {a["id"]: sha256_file(project.asset_path(a["id"])) for a in project.data["assets"]}
    before_clips = copy.deepcopy(mr.find_track(project.data, TRACK)["clips"])
    before_mix, before_raw = render(song), raw(song)
    before_static = mr.static_sum(project)[0]
    start, end = sr // 4, sr // 2
    row = apply(song, start=start, end=end)
    expected = before_raw.copy()
    expected[start:end] *= -1
    assert raw(song).tobytes() == expected.tobytes()
    assert render(song).tobytes() != before_mix.tobytes()
    assert row["kind"] == "derived" and row["status"] == "applied"
    assert ledger(song)["derived"]["m01"] == row
    project = Project.open(song)
    asset = project.asset(row["result"]["asset"])
    assert asset["origin"] == "added"  # No new core vocabulary.
    assert asset["length_samples"] == sr and asset["subtype"] == "DOUBLE"
    assert sha256_file(project.asset_path(asset["id"])) == row["result"]["sha256"]
    assert all(sha256_file(project.asset_path(aid)) == sha for aid, sha in before_assets.items())
    assert not any(c["check"] == "length_mismatch" for c in run_checks(project))
    assert mr.timeline_length(project.data) == sr
    placed = next(c for c in mr.find_track(project.data, TRACK)["clips"] if c["id"] == row["clip"])
    assert placed["length"] == end - start and placed["source_start"] == 0
    assert row["muted_clips"] and row["journal_seq"] > row["import_journal_seq"]
    # D-036/OQ-2 is the existing head-aligned sum, including the derived asset.
    _, _, rec = mr.static_sum(project)
    assert asset["id"] in rec["summed_assets"]
    D.revert(song, DIR)
    assert render(song).tobytes() == before_mix.tobytes()
    assert raw(song).tobytes() == before_raw.tobytes()
    project = Project.open(song)
    assert mr.find_track(project.data, TRACK)["clips"] == before_clips
    assert project.asset(asset["id"])["unused"] is True
    assert mr.static_sum(project)[0].tobytes() == before_static.tobytes()
    assert ledger(song)["reverted"]
    seq = journal.last_seq(song)
    assert D.revert(song, DIR)["reverted_moves"] == []
    assert journal.last_seq(song) == seq


def test_raw_layout_and_revert_include_fades_gains_muted_and_cleanup(song):
    api.stem_edit(song, "split", clip="clp_guitar", at=18000, actor="human")
    p = Project.open(song)
    ti = next(i for i, t in enumerate(p.data["tracks"]) if t["id"] == TRACK)
    api.patch(song, [
        {"op": "replace", "path": f"/tracks/{ti}/clips/0/gain_db", "value": -3.0},
        {"op": "replace", "path": f"/tracks/{ti}/clips/0/fade_in", "value": 7000},
        {"op": "replace", "path": f"/tracks/{ti}/clips/1/muted", "value": True},
        {"op": "replace", "path": f"/tracks/{ti}/gain_db", "value": -9.0},
        {"op": "replace", "path": f"/tracks/{ti}/chain", "value": [
            {"id": "p_gain", "type": "gain", "params": {"gain_db": -6.0}, "reason": "test raw input"}]},
    ])
    result = api.clean_plan(song, targets=[TRACK], overrides={"spectral_reduction": "light"}, apply=True,
                            actor="agent")
    assert result.get("applied")
    expected = raw(song)[6000:12000].copy()
    before_mix = render(song)
    before_data = Project.open(song).data
    seen = []

    def capture(x, sr, params):
        seen.append(x.copy())
        return -x

    row = apply(song, calculate=capture)
    assert seen[0].tobytes() == expected.tobytes()
    D.revert(song, DIR)
    assert render(song).tobytes() == before_mix.tobytes()
    assert Project.open(song).data["tracks"] == before_data["tracks"]
    # Recreate from the recorded layout, while cleanup/fader/chain still exist.
    p = Project.open(song)
    p.asset_path(row["result"]["asset"]).unlink()
    cache(song, row).unlink()
    assert D.regenerate(song, DIR, "m01", calculate=capture)["regenerated"]
    assert seen[1].tobytes() == expected.tobytes()


@pytest.mark.parametrize("remove_cache", [False, True])
def test_regenerate_missing_asset_without_changing_project(song, remove_cache):
    row = apply(song)
    expected = render(song)
    p = Project.open(song)
    path = p.asset_path(row["result"]["asset"])
    content = path.read_bytes()
    project_bytes = (song / "project.json").read_bytes()
    ledger_bytes = E.ledger_path(song, DIR).read_bytes()
    seq = journal.last_seq(song)
    path.unlink()
    if remove_cache:
        cache(song, row).unlink()
        cache(song, row).with_suffix(".json").unlink()
    calls = []

    def calculate(x, sr, params):
        calls.append(1)
        return invert(x, sr, params)

    assert D.regenerate(song, DIR, "m01", calculate=calculate)["regenerated"]
    assert len(calls) == int(remove_cache)
    assert path.read_bytes() == content
    assert render(song).tobytes() == expected.tobytes()
    assert (song / "project.json").read_bytes() == project_bytes
    assert E.ledger_path(song, DIR).read_bytes() == ledger_bytes
    assert journal.last_seq(song) == seq
    assert not D.regenerate(song, DIR, "m01")["regenerated"]


def test_regeneration_detects_wrong_code_and_missing_calculator(song):
    row = apply(song)
    path = Project.open(song).asset_path(row["result"]["asset"])
    path.unlink()
    cache(song, row).unlink()
    with pytest.raises(D.DerivedError, match="calculator required"):
        D.regenerate(song, DIR, "m01")
    with pytest.raises(D.DerivedError, match="differs from the ledger"):
        D.regenerate(song, DIR, "m01", calculate=lambda x, sr, p: x)
    assert not path.exists() and not cache(song, row).exists()
    D.regenerate(song, DIR, "m01", calculate=invert)


def test_regeneration_detects_changed_source_and_result(song):
    row = apply(song)
    project = Project.open(song)
    result = project.asset_path(row["result"]["asset"])
    result.write_bytes(b"corrupt")
    with pytest.raises(D.DerivedError, match="result sha256"):
        D.regenerate(song, DIR, "m01")
    result.unlink()
    cache(song, row).write_bytes(b"corrupt cache")
    project.asset_path(row["source"]["assets"][0]["id"]).write_bytes(b"corrupt source")
    with pytest.raises(D.DerivedError, match="source sha256"):
        D.regenerate(song, DIR, "m01", calculate=invert)
    assert not result.exists()


def test_cache_key_and_reuse_are_deterministic(song):
    row = apply(song)
    D.revert(song, DIR)

    def forbidden(*args):
        pytest.fail("cached result must not be recalculated")

    again = apply(song, move="m02", calculate=forbidden)
    assert again["key"] == row["key"] and again["result"] == row["result"]
    assert len(Project.open(song).data["assets"]) == 3
    source = row["source"]
    kw = dict(start=6000, end=12000, timeline_start=6000, fit="keep_length")
    key = D.cache_key(source, "test_polarity", {"polarity": -1.0}, "test-1", **kw)
    assert key == row["key"]
    assert D.cache_key(source, "test_polarity", {"polarity": 1.0}, "test-1", **kw) != key
    assert D.cache_key(source, "test_polarity", {"polarity": -1.0}, "test-2", **kw) != key
    changed = copy.deepcopy(source)
    changed["assets"][0]["sha256"] = "0" * 64
    assert D.cache_key(changed, "test_polarity", row["params"], "test-1", **kw) != key
    changed = copy.deepcopy(source)
    changed["clips"][0]["source_start"] = 42
    assert D.cache_key(changed, "test_polarity", row["params"], "test-1", **kw) != key
    assert D.cache_key(source, "test", {"b": 2, "a": 1}, "1") == D.cache_key(source, "test", {"a": 1, "b": 2}, "1")
    with pytest.raises(D.DerivedError, match="already has"):
        apply(song, move="m02")


@pytest.mark.parametrize("size", [0, 1000, 9000])
def test_keep_length_truncates_or_pads(song, size):
    before = raw(song)
    row = apply(song, calculate=lambda x, sr, p: np.full((size, 2), 0.125))
    after = raw(song)
    assert np.array_equal(after[6000:6000 + min(size, 6000)], np.full((min(size, 6000), 2), 0.125))
    if size < 6000:
        assert not after[6000 + size:12000].any()
    assert after[:6000].tobytes() == before[:6000].tobytes()
    assert after[12000:].tobytes() == before[12000:].tobytes()
    assert row["result"]["calculated_frames"] == size
    assert row["result"]["fitted_frames"] == 6000


def test_keep_start_shift_and_length_preserve_timeline(song):
    # Tail of source clip ends at 12000, leaving room to move/extend into silence.
    p = Project.open(song)
    ti = next(i for i, t in enumerate(p.data["tracks"]) if t["id"] == TRACK)
    api.patch(song, [{"op": "replace", "path": f"/tracks/{ti}/clips/0/length", "value": 12000}])
    before = render(song)
    row = apply(song, fit="keep_start", timeline_start=15000,
                calculate=lambda x, sr, p: np.full((9000, 2), 0.125))
    after = raw(song)
    assert not after[6000:15000].any()
    assert np.array_equal(after[15000:24000], np.full((9000, 2), 0.125))
    assert row["offset_samples"] == 9000
    assert mr.timeline_length(Project.open(song).data) == 24000
    D.revert(song, DIR)
    assert render(song).tobytes() == before.tobytes()


@pytest.mark.parametrize("kwargs", [
    {"start": -1}, {"end": 25000}, {"start": True}, {"start": 1.5}, {"end": 6000},
    {"timeline_start": 24000}, {"timeline_start": 23000},
    {"fit": "unknown"}, {"code_version": ""}, {"params": {"polarity": float("nan")}},
    {"calculate": lambda x, sr, p: np.zeros(6)},
    {"calculate": lambda x, sr, p: np.full(x.shape, np.inf)},
    {"calculate": lambda x, sr, p: np.zeros((6, 1))},
    {"fit": "keep_start", "calculate": lambda x, sr, p: np.zeros((24000, 2))},
    {"fit": "keep_start", "calculate": lambda x, sr, p: np.zeros((9000, 2))},
    {"timeline_start": 12000},  # Existing content outside the input range.
])
def test_invalid_calculation_and_placement_do_not_mutate_project(song, kwargs):
    before = (song / "project.json").read_bytes()
    seq = journal.last_seq(song)
    with pytest.raises(ValueError):
        apply(song, **kwargs)
    assert (song / "project.json").read_bytes() == before
    assert journal.last_seq(song) == seq
    assert not E.ledger_path(song, DIR).exists()


def test_reverse_order_revert_protects_later_edits(song):
    before = render(song)
    apply(song)
    apply(song, move="m02", start=12000, end=18000)
    project_bytes = (song / "project.json").read_bytes()
    with pytest.raises(D.DerivedError, match="revert later"):
        D.revert(song, DIR, "m01")
    assert (song / "project.json").read_bytes() == project_bytes
    D.revert(song, DIR)
    assert render(song).tobytes() == before.tobytes()


def test_existing_fb2_ledger_is_preserved(song):
    E.apply_moves(song, {"id": DIR}, [{"id": "edit01", "op": "edit_trim", "target": TRACK,
                                      "params": {"side": "tail"}}])
    legacy = copy.deepcopy(ledger(song)["moves"])
    before = render(song)
    apply(song)
    assert ledger(song)["moves"] == legacy
    D.revert(song, DIR)
    assert ledger(song)["moves"] == legacy
    assert render(song).tobytes() == before.tobytes()


def test_failed_placement_rolls_back_source_mute(song, monkeypatch):
    ti = next(i for i, t in enumerate(Project.open(song).data["tracks"]) if t["id"] == TRACK)
    api.patch(song, [{"op": "replace", "path": f"/tracks/{ti}/clips/0/length", "value": 12000}])
    before = render(song)
    clips = copy.deepcopy(mr.find_track(Project.open(song).data, TRACK)["clips"])

    def fail(*args, **kwargs):
        raise RuntimeError("test placement failure")

    monkeypatch.setattr(api, "stem_range_replace", fail)
    with pytest.raises(RuntimeError, match="test placement failure"):
        apply(song, timeline_start=15000)
    assert mr.find_track(Project.open(song).data, TRACK)["clips"] == clips
    assert render(song).tobytes() == before.tobytes()
    assert not E.ledger_path(song, DIR).exists()


def test_nonzero_source_offset_and_timeline_offset_are_raw_input(song):
    ti = next(i for i, t in enumerate(Project.open(song).data["tracks"]) if t["id"] == TRACK)
    api.patch(song, [
        {"op": "replace", "path": f"/tracks/{ti}/clips/0/source_start", "value": 1234},
        {"op": "replace", "path": f"/tracks/{ti}/clips/0/timeline_start", "value": 4321},
        {"op": "replace", "path": f"/tracks/{ti}/clips/0/length", "value": 15000},
    ])
    expected = raw(song)
    before = render(song)
    row = apply(song)
    expected[6000:12000] *= -1
    assert raw(song).tobytes() == expected.tobytes()
    Project.open(song).asset_path(row["result"]["asset"]).unlink()
    cache(song, row).unlink()
    D.regenerate(song, DIR, "m01", calculate=invert)
    assert raw(song).tobytes() == expected.tobytes()
    D.revert(song, DIR)
    assert render(song).tobytes() == before.tobytes()


def test_stale_layout_revert_and_unknown_ledger_are_refused(song):
    with pytest.raises(D.DerivedError, match="no edit ledger"):
        D.revert(song, DIR)
    row = apply(song)
    api.stem_move(song, row["clip"], 6500)
    before = (song / "project.json").read_bytes()
    with pytest.raises(D.DerivedError, match="clip layout changed"):
        D.revert(song, DIR)
    assert (song / "project.json").read_bytes() == before
    assert ledger(song)["derived"]["m01"]["status"] == "applied"


def test_reapply_repairs_deduplicated_missing_asset(song):
    row = apply(song)
    before = render(song)
    D.revert(song, DIR)
    path = Project.open(song).asset_path(row["result"]["asset"])
    path.unlink()
    again = apply(song, move="m02")
    assert again["result"] == row["result"]
    assert sha256_file(path) == row["result"]["sha256"]
    assert render(song).tobytes() == before.tobytes()
