"""As-is import of Suno Studio export sets and other folders (SPEC 6.1.2, 6.1.3, 16.2)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from mankomix.core.adapters import FileAdapter, get_adapter
from mankomix.core.project import Project
from tests.fixtures.folders import SUNO_PARTS, SUNO_ROLES, make_suno_export, stem_signal

TITLE = "テスト 曲 (Mix)"


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _snapshot(folder: Path) -> dict[str, tuple[str, int]]:
    return {p.name: (_sha(p), p.stat().st_mtime_ns) for p in sorted(folder.iterdir()) if p.is_file()}


@pytest.fixture
def project(tmp_path):
    return Project.create(tmp_path / "song.mmx", title="test song")


def _by_name(probe: dict) -> dict[str, dict]:
    return {f["original_name"]: f for f in probe["files"]}


def test_registry_has_file_adapter():
    assert isinstance(get_adapter("file"), FileAdapter)
    assert get_adapter("file").id == "file"


def test_detects_full_suno_export(tmp_path):
    src = make_suno_export(tmp_path / "export")
    probe = FileAdapter().probe(src)
    assert probe["kind"] == "suno_studio_multitrack_export"
    assert probe["detected_by"] == "filename_pattern"
    assert probe["service"] == "suno"
    assert probe["title"] == TITLE
    files = _by_name(probe)
    assert len(files) == 13
    for i, part in enumerate(SUNO_PARTS, start=1):
        f = files[f"{i} {part}.wav"]
        assert f["role"] == SUNO_ROLES[part]
        assert f["role_source"] == "filename_pattern"
        assert f["number"] == i
    assert files[f"0 {TITLE}.wav"]["role"] == "fullmix"


def test_roles_come_from_names_not_numbers(tmp_path):
    src = make_suno_export(tmp_path / "five", n_stems=5)
    probe = FileAdapter().probe(src)
    assert probe["kind"] == "suno_studio_multitrack_export"
    files = _by_name(probe)
    # 5-stem export: "1 Guitar" ... "5 Vocals" (number 1 is not Woodwinds here)
    assert files["1 Guitar.wav"]["role"] == "guitar"
    assert files["2 Bass.wav"]["role"] == "bass"
    assert files["3 Drums.wav"]["role"] == "drums"
    assert files["4 Backing Vocals.wav"]["role"] == "backing_vocals"
    assert files["5 Vocals.wav"]["role"] == "vocals"


def test_unknown_part_name_becomes_other_with_estimate(tmp_path, project):
    src = make_suno_export(tmp_path / "unk", parts=["Vocals", "Choir Pad", "BASS"])
    probe = FileAdapter().probe(src)
    files = _by_name(probe)
    assert probe["kind"] == "suno_studio_multitrack_export"
    assert files["2 Choir Pad.wav"]["role"] == "other"
    assert files["2 Choir Pad.wav"]["role_source"] == "default"
    assert "estimate" in files["2 Choir Pad.wav"]["role_note"]
    assert files["3 BASS.wav"]["role"] == "bass"  # case-insensitive
    rec = FileAdapter().fetch(src, project)
    unknown = [c for c in rec["checks"] if c["check"] == "unknown_role"]
    assert len(unknown) == 1 and unknown[0]["level"] == "warning"


def test_fetch_suno_export_as_is(tmp_path, project):
    src = make_suno_export(tmp_path / "export")
    before = _snapshot(src)
    rec = FileAdapter().fetch(src, project)
    after = _snapshot(src)
    assert before == after, "source files must stay untouched (bytes and mtime)"

    data = Project.open(project.root).data  # persisted and valid
    assets = {a["original_name"]: a for a in data["assets"]}
    assert set(assets) == set(before)
    for name, (sha, _mtime) in before.items():
        a = assets[name]
        assert a["sha256"] == sha
        assert a["path"] == f"assets/{name}"  # original name kept, no renaming
        copied = project.root / "assets" / name
        assert copied.read_bytes() == (src / name).read_bytes()
        assert a["format"] == "wav_f32"
        assert a["sample_rate"] == 48000 and a["channels"] == 2
        assert a["linked"] is False

    fm = assets[f"0 {TITLE}.wav"]
    assert data["fullmix_asset"] == fm["id"] == "ast_fullmix"
    assert fm["origin"] == "reference_fullmix"
    assert all(a["origin"] == "native_stem" for n, a in assets.items() if a is not fm)
    clip_assets = {c["asset"] for t in data["tracks"] for c in t["clips"]}
    assert fm["id"] not in clip_assets, "full mix must not become a track"
    assert len(data["tracks"]) == 12

    tracks = {t["role"]: t for t in data["tracks"]}
    assert tracks["vocals"]["is_lead"] is True
    assert sum(t["is_lead"] for t in data["tracks"]) == 1
    assert data["objective"]["lead_stem"] == tracks["vocals"]["id"] == "trk_vocals"
    assert tracks["vocals"]["importance"] == {"value": 1.0, "source": "default", "by_section": {}}
    assert tracks["drums"]["importance"]["value"] == 0.8
    assert tracks["bass"]["importance"]["value"] == 0.7
    assert tracks["strings"]["importance"]["value"] == 0.5
    assert tracks["fx"]["importance"]["value"] == 0.3
    clip = tracks["bass"]["clips"][0]
    assert clip["timeline_start"] == 0 and clip["gain_db"] == 0.0 and clip["muted"] is False
    assert clip["length"] == assets["9 Bass.wav"]["length_samples"]
    assert tracks["bass"]["output"] == "bus_mix" and tracks["bass"]["kind"] == "audio"

    prov = data["provenance"]
    assert prov["source"] == "ai_generated" and prov["service"] == "suno"
    assert prov["input_kind"] == "suno_studio_multitrack_export"
    assert prov["detected_by"] == "filename_pattern" and prov["declared_by_user"] is False
    assert "estimate" in prov["notes"]

    ing = data["ingest"]
    assert ing["adapter"] == "file" and ing["input_kind"] == "suno_studio_multitrack_export"
    assert {f["original_name"] for f in ing["files"]} == set(before)
    assert all(f["sha256"] == before[f["original_name"]][0] for f in ing["files"])
    assert data["timebase"]["sample_rate"] == 48000
    assert data["timebase"]["length_samples"] == 3 * 48000
    assert data["timebase"]["conform_policy"]["applied"] == []

    ss = [c for c in ing["checks"] if c["check"] == "stem_sum_consistency"]
    assert len(ss) == 1 and ss[0]["level"] == "info"
    assert ss[0]["values"]["residual_db"] is not None
    assert ss[0]["values"]["correlation"] > 0.9
    assert not [c for c in ing["checks"] if c["level"] == "reject"]
    assert rec["fullmix_asset"] == "ast_fullmix"

    # No absolute path of the input leaks into the project file.
    text = (project.root / "project.json").read_text(encoding="utf-8")
    assert str(tmp_path) not in text and tmp_path.as_posix() not in text


def test_japanese_and_space_names_generic_folder(tmp_path, project):
    src = tmp_path / "フォルダ 名"
    src.mkdir()
    names = {"リード ボーカル (main).wav": "vocals", "ベース 1.wav": "bass", "Kick & Snare.wav": "drums",
             "歌 コーラス.wav": "backing_vocals", "謎の音.wav": "other"}
    for i, n in enumerate(names):
        sf.write(str(src / n), stem_signal(i, 48000, 1.0), 48000, subtype="PCM_24")
    (src / "メモ.txt").write_text("not audio", encoding="utf-8")
    (src / "sub").mkdir()
    probe = FileAdapter().probe(src)
    assert probe["kind"] == "stem_folder" and probe["detected_by"] is None
    got = {f["original_name"]: f["role"] for f in probe["files"]}
    assert got == names
    assert {i["name"] for i in probe["ignored"]} == {"メモ.txt", "sub"}

    before = _snapshot(src)
    FileAdapter().fetch(src, project)
    assert _snapshot(src) == before
    data = Project.open(project.root).data
    for a in data["assets"]:
        assert (project.root / a["path"]).read_bytes() == (src / a["original_name"]).read_bytes()
        assert a["format"] == "wav_pcm24"
    assert data["provenance"]["source"] is None and data["provenance"]["input_kind"] == "stem_folder"
    assert data["fullmix_asset"] is None
    unknown = [c for c in data["ingest"]["checks"] if c["check"] == "unknown_role"]
    assert [c["values"]["original_name"] for c in unknown] == ["謎の音.wav"]


def test_conformed_derived_set_accepted_as_stem_folder(tmp_path, project):
    src = tmp_path / "conformed"
    src.mkdir()
    parts = ["vocals", "backing_vocals", "drums", "bass", "guitar", "keyboard", "synth", "strings"]
    for i, p in enumerate(parts):
        sf.write(str(src / f"{p}_conformed.wav"), stem_signal(i, 48000, 1.0), 48000, subtype="FLOAT")
    total = sum(stem_signal(i, 48000, 1.0) for i in range(len(parts)))
    sf.write(str(src / "song_fullmix_conformed.wav"), total, 48000, subtype="FLOAT")
    # Derived sums next to a conformed set (D-037): must not be imported.
    sf.write(str(src / "other.wav"), total * 0.5, 48000, subtype="FLOAT")
    sf.write(str(src / "no_vocals.wav"), total * 0.7, 48000, subtype="FLOAT")

    probe = FileAdapter().probe(src)
    assert probe["kind"] == "stem_folder"
    files = _by_name(probe)
    assert files["other.wav"]["derived_sum"] and files["no_vocals.wav"]["derived_sum"]
    assert files["song_fullmix_conformed.wav"]["role"] == "fullmix"
    assert files["backing_vocals_conformed.wav"]["role"] == "backing_vocals"

    rec = FileAdapter().fetch(src, project, provenance={"source": "ai_generated", "service": "suno",
                                                      "notes": "conformed to the original song length"})
    data = Project.open(project.root).data
    names = {a["original_name"] for a in data["assets"]}
    assert "other.wav" not in names and "no_vocals.wav" not in names
    assert {s["original_name"] for s in rec["skipped"]} == {"other.wav", "no_vocals.wav"}
    assert data["provenance"]["declared_by_user"] is True
    assert data["provenance"]["service"] == "suno"
    assert data["provenance"]["input_kind"] == "stem_folder"
    assert data["fullmix_asset"] is not None
    assert len(data["tracks"]) == len(parts)
    ss = [c for c in data["ingest"]["checks"] if c["check"] == "stem_sum_consistency"][0]
    assert ss["values"]["residual_db"] < -60  # exact sum here
    assert [c for c in data["ingest"]["checks"] if c["check"] == "derived_sum"]


def test_link_mode_keeps_files_outside(tmp_path, project, monkeypatch):
    monkeypatch.setenv("MANKOMIX_HOME", str(tmp_path / "home"))
    from mankomix.core import config
    src = make_suno_export(tmp_path / "export", n_stems=3)
    before = _snapshot(src)
    rec = FileAdapter().fetch(src, project, mode="link")
    assert _snapshot(src) == before
    assert not any((project.root / "assets").iterdir()), "link mode must not copy"
    data = Project.open(project.root).data
    for a in data["assets"]:
        assert a["linked"] is True
        assert a["path"] == f"linked/{a['original_name']}"
        loc = config.get_linked_location(a["sha256"])
        assert Path(loc).resolve() == (src / a["original_name"]).resolve()
    text = (project.root / "project.json").read_text(encoding="utf-8")
    assert str(tmp_path) not in text and tmp_path.as_posix() not in text
    assert any(c["check"] == "stem_sum_consistency" for c in rec["checks"])


def test_reimport_appends_without_duplicates(tmp_path, project):
    src = make_suno_export(tmp_path / "export", n_stems=3)
    FileAdapter().fetch(src, project)
    extra_dir = tmp_path / "extra"
    extra_dir.mkdir()
    sf.write(str(extra_dir / "Strings.wav"), stem_signal(31, 48000, 3.0), 48000, subtype="FLOAT")
    # Same name as an existing asset but different content -> stored with a suffix.
    sf.write(str(extra_dir / "3 Vocals.wav"), stem_signal(32, 48000, 3.0), 48000, subtype="FLOAT")
    dup = src / "1 Drums.wav"
    rec = FileAdapter().fetch([extra_dir / "Strings.wav", dup, extra_dir / "3 Vocals.wav"], project)
    data = Project.open(project.root).data
    assert [s["reason"] for s in rec["skipped"]] == ["duplicate"], rec["skipped"]
    assert rec["skipped"][0]["duplicate_of"] == "ast_drums"
    shas = [a["sha256"] for a in data["assets"]]
    assert len(shas) == len(set(shas)) == 6
    roles = sorted(t["role"] for t in data["tracks"])
    assert roles == ["backing_vocals", "drums", "strings", "vocals", "vocals"]
    second_vocals = [a for a in data["assets"] if a["original_name"] == "3 Vocals.wav" and a["path"] != "assets/3 Vocals.wav"]
    assert len(second_vocals) == 1 and second_vocals[0]["path"] == "assets/3 Vocals_2.wav"
    assert sum(t["is_lead"] for t in data["tracks"]) == 1  # existing lead kept
    assert data["ingest"]["input_kind"] == "suno_studio_multitrack_export"
    assert len(data["ingest"]["files"]) == 6
    assert any(c["check"] == "duplicate" for c in data["ingest"]["checks"])


def test_single_file_is_the_fullmix(tmp_path, project):
    p = tmp_path / "my song 2mix.wav"
    sf.write(str(p), stem_signal(0, 44100, 1.0), 44100, subtype="PCM_16")
    probe = FileAdapter().probe(p)
    assert probe["kind"] == "single_mix"
    rec = FileAdapter().fetch(p, project)
    data = Project.open(project.root).data
    assert data["fullmix_asset"] == "ast_fullmix" and data["tracks"] == []
    assert data["assets"][0]["format"] == "wav_pcm16"
    assert data["timebase"]["sample_rate"] == 44100
    assert rec["kind"] == "single_mix"


def test_project_file_is_valid_json_with_relative_paths(tmp_path, project):
    src = make_suno_export(tmp_path / "export", n_stems=2)
    FileAdapter().fetch(src, project)
    data = json.loads((project.root / "project.json").read_text(encoding="utf-8"))
    assert all(not a["path"].startswith("/") and ":" not in a["path"] for a in data["assets"])
    assert all(i["level"] != "error" for i in Project.open(project.root).validate())
    assert np.isfinite([a["duration_s"] for a in data["assets"]]).all()
