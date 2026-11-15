"""FR-3 / FR-6 CLI contracts and G-3: read-only look-ahead on synthetic projects."""
from __future__ import annotations

import hashlib
import json

import pytest

from mankomix.cli.main import main
from mankomix.core import cleanstage, mixrender as MR
from mankomix.director import purity as P
from tests import test_fbreview_stemobs as FS


@pytest.fixture(autouse=True)
def _local_home(tmp_path, monkeypatch):
    monkeypatch.setenv("MANKOMIX_HOME", str(tmp_path / "home"))


@pytest.fixture
def song(tmp_path):
    return FS._make(tmp_path / "song", {
        "a": FS._noise(300, 1000, 31), "b": FS._noise(300, 1000, 32, -24.0),
        "c": FS._noise(200, 2000, 33, -22.0), "d": FS._noise(4000, 8000, 34, -26.0)},
        tracks={"trk_a": {"role": "vocals", "is_lead": True,
                          "sends": [{"bus": "bus_fx", "level_db": -12.0}]}},
        variants=FS.VARIANTS)


def _snapshot(root):
    return {p.relative_to(root).as_posix(): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
            for p in root.rglob("*") if p.is_file()}


def _run(song, capsys, command, *args, code=0):
    before = _snapshot(song)
    assert main(["direction", "stems", command, "--project", str(song), *args]) == code
    captured = capsys.readouterr()
    assert not captured.err
    assert _snapshot(song) == before
    return json.loads(captured.out)


@pytest.mark.parametrize("from_file", [False, True])
def test_observe_json_object_or_file_array_and_variant(song, tmp_path, capsys, from_file):
    spec = {"primitive": "wet_ratio", "target": "trk_a"}
    specs = [spec, {"primitive": "image_position", "target": "trk_b", "path": "solo"}] if from_file else spec
    arg = json.dumps(specs)
    if from_file:
        path = tmp_path / "specs.json"
        path.write_text(arg, encoding="utf-8")
        arg = "@" + str(path)
    out = _run(song, capsys, "observe", "--variant", "v_send6", arg)
    assert list(out) == ["kind", "observations"]
    assert out["kind"] == "direction_stem_observations"
    rows = out["observations"]
    assert [row["spec"] for row in rows] == (specs if from_file else [specs])
    assert all(list(row) == ["spec", "result"] and row["result"]["status"] == "ok" for row in rows)
    assert rows[0]["result"]["value"] == pytest.approx(-6.0, abs=0.5)


@pytest.mark.parametrize("top", [None, 1, 2, 8])
def test_relate_json_top_maskers_descending_and_count(song, capsys, top):
    out = _run(song, capsys, "relate", *([] if top is None else ["--top", str(top)]))
    assert list(out) == ["kind", "signal", "section", "tracks", "masking", "band_owners", "note"]
    assert out["kind"] == "direction_stem_relate" and out["signal"] == "mix_stage_dry"
    assert out["section"] is None
    assert out["tracks"] == ["trk_a", "trk_b", "trk_c", "trk_d"]
    assert list(out["masking"]) == ["overall_db", "lead", "per_target"]
    assert out["masking"]["lead"] == "trk_a"
    bands = ["sub", "bass", "lowmid", "mid", "highmid", "air"]
    assert list(out["band_owners"]) == bands
    assert all(isinstance(owners, list) for owners in out["band_owners"].values())
    for tid, row in out["masking"]["per_target"].items():
        assert list(row) == ["buried_db", "by_band", "top_maskers"]
        assert list(row["by_band"]) == bands
        maskers = row["top_maskers"]
        assert len(maskers) == min(3 if top is None else top, len(out["tracks"]) - 1)
        assert all(set(m) == {"track", "buried_db"} and m["track"] != tid for m in maskers)
        values = [m["buried_db"] for m in maskers]
        assert values == sorted(values, reverse=True)


@pytest.mark.parametrize("section", ["sec1", {"t0_s": 0.0, "t1_s": 1.5}])
def test_relate_section_and_variant(song, capsys, section):
    arg = json.dumps(section) if isinstance(section, dict) else section
    out = _run(song, capsys, "relate", "--section", arg, "--variant", "v_mute_b")
    assert out["section"] == section
    assert out["tracks"] == ["trk_a", "trk_c", "trk_d"]


@pytest.mark.parametrize("top", [-1, 0, 9])
def test_top_outside_range_is_input_error_before_render(song, capsys, monkeypatch, top):
    monkeypatch.setattr(MR, "render_mix", lambda *a, **k: pytest.fail("invalid top must not render"))
    out = _run(song, capsys, "relate", "--top", str(top), code=1)
    assert out["error"] == "input_error" and "1 to 8" in out["message"]


@pytest.mark.parametrize("top", ["2.0", "true", "abc"])
def test_top_must_parse_as_an_integer(song, capsys, top):
    out = _run(song, capsys, "relate", "--top", top, code=2)
    assert out["error"] == "input_error"


@pytest.mark.parametrize("tracks", [None, ["trk_a", "trk_c"]])
def test_purity_json_and_repeated_track_selection(song, capsys, monkeypatch, tracks):
    actual = P.stem_purity
    passed = []
    def record(root, tracks=None):
        passed.append(tracks)
        return actual(root, tracks=tracks)
    monkeypatch.setattr(P, "stem_purity", record)
    args = [value for tid in tracks or [] for value in ("--track", tid)]
    out = _run(song, capsys, "purity", *args)
    assert passed == [tracks]
    assert set(out) == {"kind", "signal", "tracks", "mixture", "note"}
    assert out["kind"] == "direction_stem_purity" and out["signal"] == "post_clean_pre_chain"
    assert list(out["tracks"]) == (tracks or ["trk_a", "trk_b", "trk_c", "trk_d"])
    assert out["mixture"] is None and out["note"] == P.NOTE
    for row in out["tracks"].values():
        assert {"shared", "baked_reverb", "baked_width", "baked_dynamics", "flags"} <= row.keys()
        assert row["shared"] is None and row["reason"] == "too_short"
        assert set(row["flags"]) == {"origin", "r22_baked", "floor_restricted"}


@pytest.mark.parametrize("command", ["observe", "relate", "purity"])
@pytest.mark.parametrize("damage", ["missing", "stale"])
def test_invalid_cleanup_cache_exits_one_without_render_or_writes(song, capsys, monkeypatch, command, damage):
    project_file = song / "project.json"
    data = json.loads(project_file.read_text(encoding="utf-8"))
    track = next(t for t in data["tracks"] if t["id"] == "trk_d")
    aid = track["clips"][0]["asset"]
    asha = next(a["sha256"] for a in data["assets"] if a["id"] == aid)
    phash = "b" * 64
    path = song / cleanstage.cache_rel(asha, phash)
    cleanstage.write_f32_wav(path, FS._noise(4000, 8000, 35), FS.SR)
    cleanstage._sidecar(path).write_text(json.dumps({"asset_sha256": asha, "plan_hash": phash,
        "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}), encoding="utf-8")
    track["cleanup"] = {"applied": {"assets": {aid: {"asset_sha256": asha, "plan_hash": phash}}}}
    project_file.write_text(json.dumps(data), encoding="utf-8")
    if damage == "missing":
        path.unlink()
    else:
        path.write_bytes(path.read_bytes() + b"changed")
    def no_render(*args, **kwargs):
        pytest.fail("invalid cleanup cache must fail before rendering any track")
    monkeypatch.setattr(MR, "render_mix", no_render)
    monkeypatch.setattr(MR, "render_track", no_render)
    args = [json.dumps({"primitive": "crest", "target": "trk_a"})] if command == "observe" else []
    out = _run(song, capsys, command, *args, code=1)
    assert out["error"] == "input_error"
    assert "clean apply" in out["message"] and "render" in out["message"]
    if command == "purity":
        assert out["message"] == (f"cleanup cache is missing or stale for 'trk_d' / '{aid}'; "
                                  "run clean apply/render first")


@pytest.mark.parametrize("command,args", [
    ("observe", ["[]"]), ("relate", ["--section", "unknown_section"]),
    ("purity", ["--track", "trk_unknown"])])
def test_measurement_input_errors_are_json(song, capsys, command, args):
    assert _run(song, capsys, command, *args, code=1)["error"] == "input_error"


@pytest.mark.parametrize("placement", ["before", "group", "after"])
def test_common_options_and_text_output(song, capsys, placement):
    options = ["--project", str(song), "--format", "text", "--actor", "agent"]
    args = {"before": [*options, "direction", "stems", "purity"],
            "group": ["direction", "stems", *options, "purity"],
            "after": ["direction", "stems", "purity", *options]}[placement]
    before = _snapshot(song)
    assert main(args) == 0
    out = capsys.readouterr()
    assert "direction_stem_purity" in out.out and not out.err
    assert _snapshot(song) == before


def test_stems_help_lists_all_three_commands(capsys):
    assert main(["direction", "stems", "--help"]) == 0
    out = capsys.readouterr()
    assert not out.err
    for command in ("observe", "relate", "purity"):
        assert any(line.startswith("    " + command + " ") for line in out.out.splitlines())
