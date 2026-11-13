"""Per-track render cache of core/mixrender.py (performance only).

Cached and uncached renders must be bit-identical, records included; a change
to one track re-renders only that track; editing a clip, a chain or the asset
file invalidates the entry.
"""

from __future__ import annotations

import copy
import json

import numpy as np
import pytest

from mankomix.core import mixrender as mr
from mankomix.core.adapters.file import FileAdapter
from mankomix.core.mixplan import _View
from mankomix.core.project import Project
from tests.fixtures import synth

SR = 48000


@pytest.fixture
def proj(tmp_path, monkeypatch):
    monkeypatch.setenv("MANKOMIX_HOME", str(tmp_path / "home"))
    stems = synth.song_stems(sr=SR, seconds=3.0, seed=0)
    src = tmp_path / "src"
    for role in ("vocals", "drums", "bass"):
        synth.write_wav(src / f"{role}.wav", stems[role], SR)
    # a stem at another rate exercises the conform record replay
    synth.write_wav(src / "synth.wav", synth.song_stems(sr=44100, seconds=3.0, seed=0)["synth"], 44100)
    p = Project.create(tmp_path / "c.mmx", title="cache")
    FileAdapter().fetch(src, p, actor="human")
    data = p.data
    for t in data["tracks"]:
        t["chain"] = [{"id": f"prc_{t['id']}_hpf", "type": "filter", "params": {"kind": "hpf", "freq_hz": 80.0},
                       "reason": "test"},
                      {"id": f"prc_{t['id']}_comp", "type": "compressor",
                       "params": {"threshold_db": -20.0, "ratio": 3.0, "attack_ms": 10.0, "release_ms": 120.0},
                       "reason": "test"}]
    p.save(actor="human", op="patch", reason="chains")
    mr.clear_track_cache()
    yield p
    mr.clear_track_cache()


def _render(p, **kw):
    so: dict = {}
    y, sr, rec = mr.render_mix(p, stems_out=so, **kw)
    return y, sr, rec, so


def _same(a, b):
    ya, sra, reca, soa = a
    yb, srb, recb, sob = b
    assert sra == srb and ya.dtype == yb.dtype and ya.tobytes() == yb.tobytes()
    assert sorted(soa) == sorted(sob) and all(soa[k].tobytes() == sob[k].tobytes() for k in soa)
    assert json.dumps(reca, sort_keys=True, default=str) == json.dumps(recb, sort_keys=True, default=str)


def test_cached_and_uncached_renders_are_identical(proj, monkeypatch):
    monkeypatch.setenv("MANKOMIX_RENDER_CACHE_MB", "0")
    ref_full = _render(proj)
    ref_ex = _render(proj, start=SR, length=SR // 2)
    ref_trk = mr.render_track(proj, "trk_drums", apply_fader=False)
    assert mr.track_cache_info()["entries"] == 0
    assert any(a["action"] == "resample_at_render" for a in ref_full[2]["conform"]["applied"])

    monkeypatch.setenv("MANKOMIX_RENDER_CACHE_MB", "512")
    first = _render(proj)                      # fills the cache
    assert mr.track_cache_info()["misses"] == 4
    second = _render(proj)                     # every track is a hit
    assert mr.track_cache_info()["hits"] == 4
    for got in (first, second):
        _same(ref_full, got)
    _same(ref_ex, _render(proj, start=SR, length=SR // 2))
    _same(ref_ex, _render(proj, start=SR, length=SR // 2))
    for _ in range(2):
        y, sr, rec = mr.render_track(proj, "trk_drums", apply_fader=False)
        assert y.tobytes() == ref_trk[0].tobytes() and rec == ref_trk[2]
        y[:] = 0.0                             # callers own their copy; the cache is not touched
    _same(ref_full, _render(proj))


def test_one_changed_track_rerenders_only_that_track(proj):
    _render(proj)
    base = mr.track_cache_info()
    data = copy.deepcopy(proj.data)
    t = next(t for t in data["tracks"] if t["id"] == "trk_bass")
    t["chain"][0]["params"]["freq_hz"] = 60.0
    view = _View(proj, data)
    got = _render(view)
    info = mr.track_cache_info()
    assert info["misses"] - base["misses"] == 1 and info["hits"] - base["hits"] == 3
    # identical to an uncached render of the same candidate
    mr.clear_track_cache()
    _same(_render(view), got)
    # a fader / pan change does not touch the pre-fader cache at all
    t["gain_db"] = -3.0
    before = mr.track_cache_info()
    _render(view)
    after = mr.track_cache_info()
    assert after["misses"] == before["misses"] and after["hits"] - before["hits"] == 4


def test_clip_edit_and_file_change_invalidate(proj):
    _render(proj)
    data = copy.deepcopy(proj.data)
    clip = data["tracks"][0]["clips"][0]
    clip["gain_db"] = -6.0
    before = mr.track_cache_info()
    edited = _render(_View(proj, data))
    assert mr.track_cache_info()["misses"] - before["misses"] == 1
    assert not np.array_equal(edited[3][data["tracks"][0]["id"]], _render(proj)[3][data["tracks"][0]["id"]])
    # rewriting an asset file (new stat) is a miss even with the same project data
    path = proj.asset_path(data["tracks"][1]["clips"][0]["asset"])
    x, sr = synth.read_wav(path)
    synth.write_wav(path, x * 0.5, sr)
    before = mr.track_cache_info()
    _render(proj)
    assert mr.track_cache_info()["misses"] - before["misses"] >= 1
