"""tools/build_demo_data.py: the Pages demo dataset built from a project through core/api.py
(SPEC 11.4, 15.2, 15.3; layout gui/DEMO_DATA.md, reader gui/src/backend/MockBackend.ts)."""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from mankomix.core import api
from tests.fixtures import synth

from .test_mastering import synth_mix

REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "tools" / "build_demo_data.py"
SAMPLE_SET = json.loads((REPO / "samples" / "sample_set.json").read_text(encoding="utf-8"))
VARIANT_FILES = ("analysis.json", "plan.json", "verify.json", "report.ja.json", "report.en.json", "audio.json")
AUDIO_KEYS = {"before", "after", "delta", "before_level_matched", "fullmix_reference"}
RENDERED = {"v01": "var_streaming_universal", "v09": "var_club"}   # comfort x streaming_universal / club


def _has_mp3_encoder() -> bool:
    exe = shutil.which("ffmpeg")
    if not exe:
        return False
    r = subprocess.run([exe, "-hide_banner", "-encoders"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
    return re.search(r"^\s*A\S*\s+libmp3lame\s", r.stdout or "", re.MULTILINE) is not None


HAS_MP3 = _has_mp3_encoder()


def _tool_module():
    spec = importlib.util.spec_from_file_location("build_demo_data", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _build(project: Path, out: Path, *extra: str, expect: int = 0) -> subprocess.CompletedProcess:
    cmd = [sys.executable, "-I", str(TOOL), "--project", str(project), "--out", str(out), *extra]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       stdin=subprocess.DEVNULL, timeout=900)
    assert r.returncode == expect, r.stderr
    return r


def _load(root: Path, rel: str):
    return json.loads((root / rel).read_text(encoding="utf-8"))


def _json_files(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): p.read_text(encoding="utf-8") for p in sorted(root.rglob("*.json"))}


@pytest.fixture(scope="module")
def project(tmp_path_factory) -> Path:
    """A 4 s synthetic 2-mix with comfort x streaming_universal and comfort x club planned, rendered
    and verified, plus comfort x cd present in the project but never rendered."""
    root = tmp_path_factory.mktemp("demo_data")
    synth.write_wav(root / "mix.wav", synth_mix(dur=4.0), synth.DEFAULT_SR)
    proj = root / "song.mmx"
    api.init_project(str(proj), title="Demo data test", genre="hiphop")
    api.import_files(str(proj), [str(root / "mix.wav")])
    api.analyze(str(proj))
    for prof in ("streaming_universal", "club"):
        api.master_plan(str(proj), profile=prof, objective="comfort", apply=True)
    api.patch(str(proj), [{"op": "add", "path": "/variants/-", "value": {
        "id": "var_cd", "objective": {"blend": [{"id": "comfort", "weight": 1.0}], "intensity": 0.5},
        "master": {"chain": []}, "outputs": [{"profile": "cd", "delivery": "cd_redbook"}]}}],
        reason="planned but not rendered")
    for vid in RENDERED.values():
        api.render(str(proj), vid)
        api.verify(str(proj), vid)
    return proj


@pytest.fixture(scope="module")
def builds(project, tmp_path_factory) -> dict:
    """Two builds with the same options (MP3 when ffmpeg + libmp3lame exist) and one JSON-only build."""
    base = tmp_path_factory.mktemp("demo_out")
    extra = ("--mp3",) if HAS_MP3 else ()
    a, b, j = base / "a", base / "b", base / "json_only"
    out = {"a": a, "b": b, "json_only": j, "mp3": HAS_MP3, "base": base}
    out["stdout"] = json.loads(_build(project, a, *extra).stdout)
    _build(project, b, *extra)
    _build(project, j)
    return out


def test_layout_matches_mock_backend(builds, project):
    root = builds["a"]
    idx = _load(root, "index.json")
    assert idx["schema_version"] == 1 and idx["synthetic"] is False
    assert idx["generator"]["name"] == "tools/build_demo_data.py"
    assert idx["project"] == "project.json" and idx["history"] == "history.json"
    assert idx["definitions"] == {"objectives": "definitions/objectives.json",
                                  "profiles": "definitions/media_profiles.json",
                                  "deliveries": "definitions/delivery_formats.json",
                                  "models": "definitions/models.json"}
    assert idx["verification_only_profiles"] == SAMPLE_SET["verification_only_profiles"]
    # the 11 sample-set variants in order (gui/src/test/backend.test.ts checks the same)
    assert [(v["n"], v["objective"], v["profile"]) for v in idx["variants"]] == \
        [(v["n"], v["objective"], v["profile"]) for v in SAMPLE_SET["variants"]]
    for v in idx["variants"]:
        assert v["id"] == f"v{v['n']:02d}" and v["dir"] == f"variants/{v['id']}/"
        assert isinstance(v["available"], bool) and set(v["label"]) == {"ja", "en"}
        assert isinstance(v["deliveries"], list) and v["intensity"] == 0.5

    # definitions are verbatim copies of the canonical files
    for src, dst in (("objectives/catalog.json", "definitions/objectives.json"),
                     ("profiles/media_profiles.json", "definitions/media_profiles.json"),
                     ("profiles/delivery_formats.json", "definitions/delivery_formats.json"),
                     ("registry/models.json", "definitions/models.json")):
        assert (root / dst).read_bytes() == (REPO / src).read_bytes()

    proj = _load(root, "project.json")
    assert proj["schema_version"] == 1 and proj["title"] == "Demo data test"
    assert [a["path"] for a in proj["assets"]] == ["assets/mix.wav"]
    hist = _load(root, "history.json")["entries"]
    assert hist and all({"seq", "ts", "actor", "op", "summary"} <= set(e) for e in hist)
    assert idx["source"]["content_hash"] == hist[-1]["after_hash"]

    for vid, pid in RENDERED.items():
        d = root / "variants" / vid
        assert sorted(p.name for p in d.glob("*.json")) == sorted(VARIANT_FILES)
        a = _load(d, "analysis.json")
        assert a["schema_version"] == 1 and a["loudness"]["before"] and a["loudness"]["after"]
        assert len(a["ltas"]["freqs_hz"]) == len(a["ltas"]["before"]) > 0
        for k in ("band_correlation", "stems", "masking", "diagnostics", "metrics"):
            assert k in a
        props = _load(d, "plan.json")["proposals"]
        assert props and all({"id", "stage", "status", "steps", "author"} <= set(p) for p in props)
        assert {p["variant"] for p in props} <= {pid, None}
        ver = _load(d, "verify.json")
        assert "S-01" in [c["id"] for c in ver["constraints"]]
        assert {"overall", "gate", "profiles", "noise_return", "codec"} <= set(ver)
        assert _load(d, "report.ja.json")["language"] == "ja"
        assert _load(d, "report.en.json")["language"] == "en"
        au = _load(d, "audio.json")
        assert au["variant"] == vid and au["project_variant"] == pid
        assert AUDIO_KEYS <= set(au["files"])
        for f in au["files"].values():
            assert f is None or (root / f).is_file()
        entry = next(v for v in idx["variants"] if v["id"] == vid)
        assert entry["available"] is True and entry["project_variant"] == pid


def test_unavailable_variants_are_marked_not_fabricated(builds):
    root = builds["a"]
    idx = _load(root, "index.json")
    by_id = {v["id"]: v for v in idx["variants"]}
    assert sorted(k for k, v in by_id.items() if v["available"]) == sorted(RENDERED)
    cd = by_id["v08"]            # comfort x cd: in the project, never rendered
    assert cd["available"] is False and cd["unavailable_reason"] == "not_rendered"
    assert cd["project_variant"] == "var_cd" and cd["deliveries"] == ["cd_redbook"]
    for vid, v in by_id.items():
        if vid in RENDERED or vid == "v08":
            continue
        assert v["available"] is False and v["unavailable_reason"] == "not_in_project"
        assert v["project_variant"] is None
    for vid, v in by_id.items():
        if not v["available"]:
            assert not (root / "variants" / vid).exists()
    assert builds["stdout"]["available"] == sorted(RENDERED)


def test_match_gain_lowers_the_louder_side(builds, project):
    for vid, pid in RENDERED.items():
        au = _load(builds["a"], f"variants/{vid}/audio.json")
        core = api.audio_set(str(project), pid)
        assert au["match_gain_db"] == core["match_gain_db"] and au["match_target"] == core["match_target"]
        lb = au["measurements"]["before"]["lufs_i"]
        la = au["measurements"]["after"]["lufs_i"]
        assert au["match_gain_db"] <= 0
        assert au["match_target"] == ("before" if lb > la else "after")
        assert au["match_gain_db"] == pytest.approx(-abs(lb - la), abs=0.011)


def test_no_absolute_paths_or_addresses(builds, project):
    mod = _tool_module()
    roots = [str(p.resolve()) for p in (builds["base"], project, Path.home(), REPO)]
    roots = {s.lower() for r in roots for s in (r, r.replace("\\", "/"), r.replace("\\", "\\\\"))}
    for name in ("a", "json_only"):
        for rel, text in _json_files(builds[name]).items():
            if rel.startswith("definitions/"):
                continue
            low = text.lower()
            assert not any(r in low for r in roots), rel
            assert not mod.find_leaks(json.loads(text), []), rel
    out = builds["stdout"]["out"]
    assert not any(r in out.lower() for r in roots)


def test_deterministic(builds):
    a, b = builds["a"], builds["b"]
    ja, jb = _json_files(a), _json_files(b)
    assert sorted(ja) == sorted(jb)
    for rel in ja:
        assert ja[rel] == jb[rel], rel
    ma = sorted(p.relative_to(a).as_posix() for p in a.rglob("*.mp3"))
    assert ma == sorted(p.relative_to(b).as_posix() for p in b.rglob("*.mp3"))
    for rel in ma:
        assert (a / rel).read_bytes() == (b / rel).read_bytes(), rel


def test_json_only_mode(builds):
    root = builds["json_only"]
    idx = _load(root, "index.json")
    assert idx["audio"]["included"] is False and idx["audio"]["encoder"] is None
    assert not list(root.rglob("*.mp3"))
    for vid in RENDERED:
        au = _load(root, f"variants/{vid}/audio.json")
        assert all(v is None for v in au["files"].values())
        assert isinstance(au["match_gain_db"], (int, float)) and au["match_target"] in ("before", "after")


@pytest.mark.skipif(not HAS_MP3, reason="ffmpeg with libmp3lame not available")
def test_mp3_listening_copies(builds):
    root = builds["a"]
    idx = _load(root, "index.json")
    enc = idx["audio"]["encoder"]
    assert idx["audio"]["included"] is True and idx["audio"]["masters"] is False
    assert enc["tool"] == "ffmpeg" and enc["codec"] == "libmp3lame" and enc["bitrate_kbps"] == 320
    files = idx["audio"]["files"]
    assert files == sorted(p.relative_to(root).as_posix() for p in root.rglob("*.mp3"))
    assert {"audio/before.mp3", "variants/v01/after.mp3", "variants/v09/after.mp3"} <= set(files)
    for rel in files:
        head = (root / rel).read_bytes()[:3]
        assert head[0] == 0xFF and head[1] & 0xFE == 0xFA, rel     # MPEG-1 Layer III frame, no ID3
        assert head[2] >> 4 == 14, rel                              # bitrate index 14 = 320 kbps
    # only the main pair (#1) has a level-matched file: the louder side, lowered
    v1 = _load(root, "variants/v01/audio.json")
    lm = "before_level_matched" if v1["match_target"] == "before" else "after_level_matched"
    assert v1["files"][lm] and (root / v1["files"][lm]).is_file()
    v9 = _load(root, "variants/v09/audio.json")
    assert v9["files"]["before_level_matched"] is None and "after_level_matched" not in v9["files"]
    assert v9["files"]["before"] == v1["files"]["before"] == "audio/before.mp3"   # shared before


def test_refuses_a_foreign_output_folder(project, tmp_path):
    out = tmp_path / "busy"
    out.mkdir()
    (out / "keep.txt").write_text("not a dataset", encoding="utf-8")
    r = _build(project, out, expect=1)
    assert "not empty" in r.stderr and str(tmp_path) not in r.stderr
    assert (out / "keep.txt").is_file() and not (out / "index.json").exists()


def test_leak_detection_and_asset_sanitising():
    mod = _tool_module()
    drive = "C" + ":"              # built at run time so the hygiene scan of this file stays clean
    home = "/" + "home/x"
    assert mod.find_leaks({"a": drive + "\\Users\\x\\song.wav"}, [])
    assert mod.find_leaks({"a": ["see " + home + "/song.wav"]}, [])
    assert mod.find_leaks({"a": "mail someone@example.org"}, [])
    assert mod.find_leaks({"a": "/srv/secret/x"}, ["/srv/secret"])
    assert not mod.find_leaks({"a": "renders/var_cd/master__archive_f32.wav", "b": "/tracks/0/gain_db"}, [])
    data = mod.sanitise_project({"assets": [{"path": drive + "/music/take 1.wav"}, {"path": "/mnt/x/b.wav"},
                                            {"path": "linked/c.wav"}, {"path": "assets/d.wav"}]})
    assert [a["path"] for a in data["assets"]] == ["linked/take 1.wav", "linked/b.wav", "linked/c.wav", "assets/d.wav"]
