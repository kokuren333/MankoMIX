"""Remix operations (core/remix.py; SPEC 9.3, 9.5; R-22, D-048)."""
from __future__ import annotations

import json
import re

import numpy as np
import pytest

from mankomix.core import journal
from mankomix.core import mixrender as mr
from mankomix.core import remix
from mankomix.core.adapters.file import FileAdapter
from mankomix.core.errors import InputError
from mankomix.core.hashing import canonical_hash, sha256_file
from mankomix.core.project import Project
from tests.fixtures import synth

SR = 24000
SECONDS = 6.0


@pytest.fixture(autouse=True)
def _local_home(tmp_path, monkeypatch):
    monkeypatch.setenv("MANKOMIX_HOME", str(tmp_path / "home"))


def click(bpm: float, *, seconds: float = SECONDS, freq: float = 1000.0) -> np.ndarray:
    """Stereo click track: decaying sine bursts on every beat."""
    n = int(seconds * SR)
    x = np.zeros(n)
    t = np.arange(int(0.03 * SR)) / SR
    burst = 0.5 * np.sin(2 * np.pi * freq * t) * np.exp(-t / 0.008)
    k = 0
    while (s := int(round(k * 60.0 / bpm * SR))) + burst.size <= n:
        x[s:s + burst.size] += burst
        k += 1
    return np.stack([x, x], axis=1)


def _noise(n, seed, ch=2):
    return 0.1 * np.random.default_rng(seed).standard_normal((n, ch))


@pytest.fixture
def proj(tmp_path) -> Project:
    src = tmp_path / "stems"
    synth.write_wav(src / "drums.wav", click(120.0), SR)
    synth.write_wav(src / "bass.wav", _noise(int(SECONDS * SR), 1), SR)
    synth.write_wav(src / "vocals.wav", _noise(int(SECONDS * SR), 2), SR)
    p = Project.create(tmp_path / "song.mmx", title="remix test")
    FileAdapter().fetch(src, p, actor="human")
    return p


def _tid(p, role):
    return next(t["id"] for t in p.data["tracks"] if t["role"] == role)


def _last(p):
    return journal.list_entries(p.root, limit=1)[0]


def _undo_restores(p, before_hash):
    journal.undo(p, actor="human")
    p.reload()
    assert canonical_hash(p.data) == before_hash


def test_stem_list(proj):
    lst = remix.stem_list(proj)
    assert {t["role"] for t in lst["tracks"]} == {"drums", "bass", "vocals"}
    assert lst["lead"] == _tid(proj, "vocals") and lst["sample_rate"] == SR
    assert lst["timeline_length"] == int(SECONDS * SR) and lst["unused_assets"] == [] and lst["notes"] == []


def test_stem_add_reports_tempo_mismatch_without_altering_audio(proj, tmp_path):
    before = canonical_hash(proj.data)
    new_file = tmp_path / "in" / "percussion.wav"
    synth.write_wav(new_file, click(100.0, freq=2000.0), SR)
    sha_in = sha256_file(new_file)
    res = remix.stem_add(proj, new_file, actor="agent")
    assert res["changed"] and res["role"] == "percussion" and res["origin"] == "added"
    tempo = res["consistency"]["tempo"]
    assert tempo["status"] == "mismatch" and tempo["project_bpm"] == pytest.approx(120.0, abs=0.5)
    assert tempo["asset_bpm"] == pytest.approx(100.0, abs=0.5)
    assert res["consistency"]["time_stretch"] is False and res["consistency"]["action"] == "reported_only"
    assert any("not stretched" in m for m in res["consistency"]["messages"])
    # project.json: asset (origin added, bytes unchanged), track, consistency summary; one journal entry.
    asset = proj.asset(res["asset"])
    assert asset["origin"] == "added" and asset["sha256"] == sha_in
    assert sha256_file(proj.asset_path(res["asset"])) == sha_in
    assert asset["length_samples"] == int(SECONDS * SR) and asset["sample_rate"] == SR
    track = mr.find_track(proj.data, res["track"])
    assert track["consistency"]["tempo"]["status"] == "mismatch" and track["is_lead"] is False
    assert proj.data["objective"]["lead_stem"] == _tid(proj, "vocals")
    entry = _last(proj)
    assert entry["op"] == "stem_add" and entry["actor"] == "agent" and entry["seq"] == res["journal_seq"]
    assert any(c["check"] for c in res["checks"])  # import checks ran on the new asset
    on_disk = json.loads((proj.root / "project.json").read_text(encoding="utf-8"))
    assert res["track"] in {t["id"] for t in on_disk["tracks"]}
    # analyses are cached under cache/
    assert list((proj.root / "cache" / "remix").glob("music_*.json"))
    _undo_restores(proj, before)


def test_stem_add_rejects_duplicates_and_bad_roles(proj, tmp_path):
    with pytest.raises(InputError):
        remix.stem_add(proj, proj.asset_path(proj.data["assets"][0]["id"]), actor="human", diagnose=False)
    f = tmp_path / "in" / "thing.wav"
    synth.write_wav(f, _noise(SR, 9), SR)
    with pytest.raises(InputError):
        remix.stem_add(proj, f, role="kazoo", actor="human")
    res = remix.stem_add(proj, f, role="fx", actor="human", diagnose=False)
    assert res["role"] == "fx" and proj.asset(res["asset"])["role_source"] == "user"


def test_stem_replace_keeps_layout_and_marks_old_asset_unused(proj, tmp_path):
    tid = _tid(proj, "bass")
    i = next(k for k, t in enumerate(proj.data["tracks"]) if t["id"] == tid)
    proj.set(f"/tracks/{i}/chain", [{"id": "prc_b1", "type": "gain", "params": {"gain_db": -3.0},
                                     "reason": "test"}], actor="human")
    before = canonical_hash(proj.data)
    old = proj.data["tracks"][i]["clips"][0]["asset"]
    f = tmp_path / "in" / "bass take 2.wav"
    synth.write_wav(f, _noise(int(SECONDS * SR) - 4800, 3), SR)
    res = remix.stem_replace(proj, tid, f, keep_chain=True, actor="human")
    t = mr.find_track(proj.data, tid)
    assert t["clips"][0]["asset"] == res["asset"] != old
    assert t["clips"][0]["length"] == int(SECONDS * SR) - 4800 and res["length_change"] == -4800
    assert t["chain"] and proj.asset(old)["unused"] is True and res["unused_assets"] == [old]
    assert len(proj.data["tracks"]) == 3  # no extra track from the import
    assert _last(proj)["op"] == "stem_replace"
    _undo_restores(proj, before)
    # replacing with an existing asset id, chain cleared
    res = remix.stem_replace(proj, tid, _tid(proj, "vocals").replace("trk_", "ast_"), keep_chain=False,
                             actor="human", diagnose=False)
    assert mr.find_track(proj.data, tid)["chain"] == []


def test_stem_remove_keeps_asset(proj):
    before = canonical_hash(proj.data)
    tid = _tid(proj, "vocals")
    aid = mr.find_track(proj.data, tid)["clips"][0]["asset"]
    res = remix.stem_remove(proj, tid, actor="human")
    assert tid not in {t["id"] for t in proj.data["tracks"]}
    assert proj.asset(aid)["unused"] is True and res["unused_assets"] == [aid]
    assert proj.data["objective"]["lead_stem"] is None
    assert proj.asset_path(aid).is_file()
    assert _last(proj)["op"] == "stem_remove"
    _undo_restores(proj, before)


def test_clip_split_is_seamless(proj):
    full, _, _ = mr.render_mix(proj, measure=False)
    before = canonical_hash(proj.data)
    tid = _tid(proj, "bass")
    cid = mr.find_track(proj.data, tid)["clips"][0]["id"]
    res = remix.clip_split(proj, cid, 123457, actor="human")
    clips = mr.find_track(proj.data, tid)["clips"]
    assert [c["id"] for c in clips] == [res["left"], res["right"]]
    assert clips[0]["length"] == 123457 and clips[1]["source_start"] == 123457
    assert clips[1]["timeline_start"] == 123457 and clips[1]["length"] == int(SECONDS * SR) - 123457
    assert np.array_equal(mr.render_mix(proj, measure=False)[0], full)
    assert _last(proj)["op"] == "clip_split"
    with pytest.raises(InputError):
        remix.clip_split(proj, res["left"], 0, actor="human")
    _undo_restores(proj, before)


def test_range_mute(proj):
    before = canonical_hash(proj.data)
    tid = _tid(proj, "bass")
    solo_before, _, _ = mr.render_mix(proj, solo=[tid], measure=False)
    res = remix.range_mute(proj, tid, SR, 2 * SR, actor="human")
    clips = mr.find_track(proj.data, tid)["clips"]
    assert len(clips) == 3 and [c["muted"] for c in clips] == [False, True, False]
    assert res["muted_clips"] == [clips[1]["id"]]
    y, _, _ = mr.render_mix(proj, solo=[tid], measure=False)
    assert not np.any(y[SR:2 * SR])
    assert np.array_equal(y[:SR], solo_before[:SR]) and np.array_equal(y[2 * SR:], solo_before[2 * SR:])
    assert _last(proj)["op"] == "range_mute"
    _undo_restores(proj, before)


def test_range_replace(proj):
    before = canonical_hash(proj.data)
    tid = _tid(proj, "bass")
    other = mr.find_track(proj.data, _tid(proj, "vocals"))["clips"][0]["asset"]
    res = remix.range_replace(proj, tid, SR, 2 * SR, other, source_start=5000, actor="human")
    clips = mr.find_track(proj.data, tid)["clips"]
    new = next(c for c in clips if c["id"] == res["clip"])
    assert new == {"id": res["clip"], "asset": other, "source_start": 5000, "length": SR, "timeline_start": SR,
                   "gain_db": 0.0, "fade_in": 0, "fade_out": 0, "muted": False}
    y, _, _ = mr.render_track(proj, tid)
    src, _ = synth.read_wav(proj.asset_path(other))
    assert np.array_equal(y[SR:2 * SR], src[5000:5000 + SR])
    assert _last(proj)["op"] == "range_replace"
    _undo_restores(proj, before)


def test_clip_move(proj):
    before = canonical_hash(proj.data)
    tid = _tid(proj, "bass")
    cid = mr.find_track(proj.data, tid)["clips"][0]["id"]
    res = remix.clip_move(proj, cid, 4800, actor="planner")
    assert res["old_timeline_start"] == 0 and mr.find_track(proj.data, tid)["clips"][0]["timeline_start"] == 4800
    assert mr.timeline_length(proj.data) == int(SECONDS * SR) + 4800
    entry = _last(proj)
    assert entry["op"] == "clip_move" and entry["actor"] == "planner"
    with pytest.raises(InputError):
        remix.clip_move(proj, cid, -1, actor="human")
    _undo_restores(proj, before)


def test_set_role_single_lead(proj):
    before = canonical_hash(proj.data)
    tid = _tid(proj, "bass")
    res = remix.set_role(proj, tid, "synth", is_lead=True, actor="human")
    leads = [t["id"] for t in proj.data["tracks"] if t.get("is_lead")]
    assert leads == [tid] and res["lead"] == tid and proj.data["objective"]["lead_stem"] == tid
    assert mr.find_track(proj.data, tid)["role"] == "synth"
    assert _last(proj)["op"] == "set_role"
    with pytest.raises(InputError):
        remix.set_role(proj, tid, "fullmix", actor="human")
    _undo_restores(proj, before)


def test_stem_export_files_and_manifest(proj, tmp_path):
    tid = _tid(proj, "bass")
    i = next(k for k, t in enumerate(proj.data["tracks"]) if t["id"] == tid)
    proj.apply_patch([{"op": "replace", "path": f"/tracks/{i}/gain_db", "value": -6.0},
                      {"op": "replace", "path": f"/tracks/{i}/pan", "value": {"position": 0.5, "width": 1.0}}],
                     actor="human")
    res = remix.stem_export(proj)
    assert len(res["files"]) == 3 and res["manifest"] == "renders/stems/manifest.json"
    for rel in res["files"] + [res["manifest"]]:
        assert not re.match(r"^([A-Za-z]:|/)", rel) and "\\" not in rel and ".." not in rel
        assert (proj.root / rel).is_file()
    text = (proj.root / res["manifest"]).read_text(encoding="utf-8")
    assert str(tmp_path) not in text and str(tmp_path.as_posix()) not in text
    manifest = json.loads(text)
    assert manifest["processed"] is True and {f["file"] for f in manifest["files"]} == set(res["files"])
    assert manifest["project_hash"] == proj.content_hash()
    # processed stems (no buses, no sends here) sum to the mix within float32 precision
    total = sum(synth.read_wav(proj.root / f)[0] for f in res["files"])
    mix, _, _ = mr.render_mix(proj, measure=False)
    assert np.allclose(total, mix, atol=1e-6)
    # unprocessed export: clip layout only (no fader / pan)
    raw = remix.stem_export(proj, [tid], processed=False, out_dir="renders/stems_raw", subtype="PCM_24")
    x, _ = synth.read_wav(proj.root / raw["files"][0])
    src, _ = synth.read_wav(proj.asset_path(mr.find_track(proj.data, tid)["clips"][0]["asset"]))
    assert np.allclose(x, src, atol=2 ** -22)
    with pytest.raises(InputError):
        remix.stem_export(proj, out_dir="../outside")


def test_separated_stems_get_r22_note(proj):
    tid = _tid(proj, "bass")
    aid = mr.find_track(proj.data, tid)["clips"][0]["asset"]
    k = next(i for i, a in enumerate(proj.data["assets"]) if a["id"] == aid)
    proj.set(f"/assets/{k}/origin", "separated", actor="human")
    notes = remix.stem_list(proj)["notes"]
    assert [n["track"] for n in notes] == [tid] and notes[0]["rule"] == "R-22"
    assert remix.clip_move(proj, mr.find_track(proj.data, tid)["clips"][0]["id"], 10,
                           actor="human")["notes"][0]["rule"] == "R-22"
    assert remix.stem_export(proj, [tid])["notes"][0]["track"] == tid
    assert mr.render_mix(proj, measure=False)[2]["notes"][0]["rule"] == "R-22"
