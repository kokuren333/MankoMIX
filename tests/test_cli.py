"""CLI and core API facade tests (SPEC 10.1, 10.2, 13.3).

Tests that depend on sibling core modules (project, journal, adapters,
ingest checks, measurement) are skipped with a clear reason until those
modules are importable.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from mankomix.cli import main as cli_main
from mankomix.core import api
from mankomix.core.errors import EXIT_ENV_ERROR, EXIT_INPUT_ERROR, EXIT_OK

REPO = Path(__file__).resolve().parent.parent
SR = 48000


def _needs(*mods: str) -> None:
    for m in mods:
        pytest.importorskip(f"mankomix.core.{m}", reason=f"core module '{m}' not available yet")


def _forbidden(tmp_path: Path) -> list[str]:
    out = []
    for p in (tmp_path, Path.home(), REPO):
        s = str(p.resolve())
        out += [s, s.replace("\\", "/"), s.replace("\\", "\\\\")]
    return [x for x in out if len(x) > 3]


def assert_no_abs(text: str, tmp_path: Path) -> None:
    low = text.lower()
    for f in _forbidden(tmp_path):
        assert f.lower() not in low, f"absolute path leaked into output: {f}"


@pytest.fixture
def cli(capsys, tmp_path):
    """Run the CLI in-process; return (exit_code, parsed JSON or text)."""

    def run(*argv: str, text: bool = False):
        code = cli_main.main([str(a) for a in argv])
        out = capsys.readouterr().out
        assert_no_abs(out, tmp_path)
        return code, (out if text else json.loads(out))

    return run


def _sine(freq: float, seconds: float = 2.0, sr: int = SR, amp: float = 0.25, channels: int = 2) -> np.ndarray:
    t = np.arange(int(seconds * sr)) / sr
    x = amp * np.sin(2 * np.pi * freq * t)
    return np.repeat(x[:, None], channels, axis=1)


def _write(path: Path, data: np.ndarray, sr: int = SR) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), data, sr, subtype="PCM_24")
    return path


@pytest.fixture
def stem_folder(tmp_path) -> Path:
    """A small Suno-export-shaped folder: fullmix (0 ...) + numbered stems."""
    d = tmp_path / "export"
    drums = _sine(80, amp=0.2)
    bass = _sine(55, amp=0.2)
    vocals = _sine(440, amp=0.1)
    _write(d / "1 Drums.wav", drums)
    _write(d / "2 Bass.wav", _sine(55, amp=0.2, sr=44100), sr=44100)   # other rate: summed after resampling
    _write(d / "3 Vocals.wav", vocals)
    _write(d / "0 Test Song.wav", drums + bass + vocals)
    return d


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------

DOCTOR_KEYS = {"status", "engine_version", "python", "packages", "ffmpeg", "ffprobe", "strict_lgpl",
               "gpu", "models", "issues"}


def test_doctor_shape(cli):
    code, r = cli("doctor")
    assert DOCTOR_KEYS <= set(r)
    assert r["status"] in ("ok", "warning", "error")
    assert code == (EXIT_ENV_ERROR if r["status"] == "error" else EXIT_OK)
    for name in ("numpy", "scipy", "soundfile", "jsonschema"):
        assert r["packages"][name]["installed"] is True
        assert r["packages"][name]["required"] is True
    for name in ("pyloudnorm", "librosa"):
        assert name in r["packages"]
    assert r["models"]["status"].startswith("registry not implemented")
    assert r["gpu"]["status"] in ("none", "nvidia")
    if r["ffmpeg"]["found"]:
        assert r["ffmpeg"]["build"] in ("lgpl", "gpl", "nonfree", "unknown")
        assert set(r["ffmpeg"]["encoders"]) == {"aac", "opus", "mp3", "vorbis", "flac"}
    assert "configuration" not in json.dumps(r["ffmpeg"])


def test_doctor_without_ffmpeg(cli, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: None)
    monkeypatch.delenv("MANKOMIX_STRICT_LGPL", raising=False)
    code, r = cli("doctor", "--no-strict-lgpl")
    assert r["ffmpeg"]["found"] is False and r["ffprobe"]["found"] is False
    assert r["gpu"] == {"status": "none", "devices": []}
    assert any(i["code"] == "ffmpeg_missing" for i in r["issues"])
    assert r["status"] == "warning" and code == EXIT_OK

    code, r = cli("doctor", "--strict-lgpl")
    assert r["status"] == "error" and code == EXIT_ENV_ERROR


_FAKE_VERSION = ("ffmpeg version 7.1-test Copyright (c) 2000-2026 the FFmpeg developers\n"
                 "built with gcc\n"
                 "configuration: --prefix=/opt/secret/build {flags} --enable-libopus\n")
_FAKE_ENCODERS = (" A....D aac                  AAC (Advanced Audio Coding)\n"
                  " A..X.D opus                 Opus\n"
                  " A....D flac                 FLAC\n")


def _fake_ffmpeg(monkeypatch, flags: str):
    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: f"/fake/bin/{name}" if name == "ffmpeg" else None)

    def fake_run(cmd, timeout=10):
        out = _FAKE_ENCODERS if "-encoders" in cmd else _FAKE_VERSION.format(flags=flags)
        return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")

    monkeypatch.setattr(api, "_run", fake_run)


@pytest.mark.parametrize("flags,build,status", [
    ("--enable-version3", "lgpl", "ok"),
    ("--enable-gpl --enable-version3", "gpl", "warning"),
    ("--enable-gpl --enable-nonfree", "nonfree", "warning"),
])
def test_doctor_ffmpeg_builds(monkeypatch, flags, build, status):
    monkeypatch.delenv("MANKOMIX_STRICT_LGPL", raising=False)
    _fake_ffmpeg(monkeypatch, flags)
    r = api.doctor(strict_lgpl=False)
    assert r["ffmpeg"]["found"] and r["ffmpeg"]["version"] == "7.1-test"
    assert r["ffmpeg"]["build"] == build
    codes = {i["code"] for i in r["issues"]}
    assert ("ffmpeg_gpl_build" in codes) == (build == "gpl")
    assert ("ffmpeg_nonfree_build" in codes) == (build == "nonfree")
    # only no_gpu (info) and missing round-trip encoders (info) besides the build warning
    assert r["status"] == status
    enc = r["ffmpeg"]["encoders"]
    assert enc["aac"]["encoder"] == "aac" and enc["opus"] == {"available": True, "encoder": "opus",
                                                                "experimental": True}
    assert enc["mp3"]["available"] is False
    dumped = json.dumps(r)
    assert "/opt/secret" not in dumped and "/fake/bin" not in dumped

    strict = api.doctor(strict_lgpl=True)
    assert strict["status"] == ("ok" if build == "lgpl" else "error")


def test_doctor_strict_from_env(monkeypatch):
    _fake_ffmpeg(monkeypatch, "--enable-gpl")
    monkeypatch.setenv("MANKOMIX_STRICT_LGPL", "1")
    r = api.doctor()
    assert r["strict_lgpl"] == {"enabled": True, "source": "environment"}
    assert r["status"] == "error"
    assert any(i["code"] == "strict_lgpl_violation" for i in r["issues"])


# ---------------------------------------------------------------------------
# stubs, global behaviour, bad input
# ---------------------------------------------------------------------------

STUBS = {"stem": "M4", "separate": "M6", "clean": "M5", "mix": "M4", "master": "M2", "render": "M2",
         "export": "M2", "verify": "M2", "report": "M2", "run": "M4", "model": "M6", "reference": "M3",
         "serve": "M8"}


@pytest.mark.parametrize("group", sorted(STUBS))
def test_stub_groups(cli, group):
    code, r = cli(group, "list", "--whatever")
    assert code == EXIT_INPUT_ERROR
    assert r["message"] == f"not implemented yet (milestone {STUBS[group]})"


def test_subprocess_module_entry_and_stub(tmp_path):
    env = {**os.environ, "PYTHONPATH": str(REPO), "PYTHONIOENCODING": "cp1252"}
    p = subprocess.run([sys.executable, "-m", "mankomix.cli", "master", "apply"], cwd=REPO, env=env,
                       capture_output=True, timeout=120)
    assert p.returncode == EXIT_INPUT_ERROR
    out = p.stdout.decode("utf-8")
    assert json.loads(out)["message"] == "not implemented yet (milestone M2)"

    p = subprocess.run([sys.executable, "-m", "mankomix.cli", "doctor", "--format", "text"], cwd=REPO, env=env,
                       capture_output=True, timeout=120)
    assert p.returncode in (EXIT_OK, EXIT_ENV_ERROR)
    text = p.stdout.decode("utf-8")
    assert text.startswith("status: ")
    assert_no_abs(text, tmp_path)


def test_bad_input_exit_codes(cli, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert cli("no-such-command")[0] == EXIT_INPUT_ERROR
    assert cli()[0] == EXIT_INPUT_ERROR
    code, r = cli("status")
    assert code == EXIT_INPUT_ERROR and "no project" in r["message"]
    code, r = cli("--project", str(tmp_path / "missing.mmx"), "status")
    assert code == EXIT_INPUT_ERROR and r["error"] == "input_error"
    code, r = cli("measure", str(tmp_path / "nope.wav"))
    assert code == EXIT_INPUT_ERROR and "nope.wav" in r["message"]
    assert cli("checkout", "abc")[0] == EXIT_INPUT_ERROR
    assert cli("history", "--limit", "x")[0] == EXIT_INPUT_ERROR
    assert cli("--actor", "robot", "status")[0] == EXIT_INPUT_ERROR
    assert cli("set", "no-pointer", "1", "-p", str(tmp_path))[0] == EXIT_INPUT_ERROR
    code, r = cli("--format", "text", "measure", str(tmp_path / "x.wav"), text=True)
    assert code == EXIT_INPUT_ERROR and r.startswith("error (input_error)")


def test_unexpected_exception_is_env_error(cli, monkeypatch):
    def boom():
        raise RuntimeError("kaboom")

    monkeypatch.setattr(api, "profile_list", boom)
    code, r = cli("profile", "list")
    assert code == EXIT_ENV_ERROR and r["error"] == "internal_error" and "kaboom" in r["message"]
    assert "traceback" not in r["details"]
    code, r = cli("profile", "list", "--debug")
    assert code == EXIT_ENV_ERROR and "traceback" in r["details"]


def test_scrub_strips_absolute_paths(tmp_path):
    proj = tmp_path / "song.mmx"
    roots = api._known_roots(proj, [tmp_path / "src"])
    s = api._scrub_str(f"cannot read {proj / 'assets' / 'a.wav'} or {tmp_path / 'src' / 'b.wav'}", roots)
    assert "assets/a.wav" in s and "b.wav" in s
    assert_no_abs(s, tmp_path)
    assert api._scrub_str("/tracks/0/gain_db", roots) == "/tracks/0/gain_db"


# ---------------------------------------------------------------------------
# profiles and objectives
# ---------------------------------------------------------------------------

def test_profile_and_objective_commands(cli):
    _needs("config")
    code, r = cli("profile", "list")
    assert code == EXIT_OK and r["profiles"] and all("id" in p for p in r["profiles"])
    assert any(d["id"] == "distributor_44k16" for d in r["deliveries"])
    pid = r["profiles"][0]["id"]
    code, r = cli("profile", "show", pid)
    assert code == EXIT_OK and r["profile"]["id"] == pid
    code, r = cli("profile", "show", "distributor_44k16")
    assert code == EXIT_OK and r["kind"] == "delivery"
    assert cli("profile", "show", "no_such_profile")[0] == EXIT_INPUT_ERROR

    code, r = cli("objective", "list")
    assert code == EXIT_OK and any(o["id"] == "comfort" for o in r["objectives"])
    code, r = cli("objective", "show", "comfort")
    assert code == EXIT_OK and r["objective"]["id"] == "comfort"
    assert cli("objective", "show", "nope")[0] == EXIT_INPUT_ERROR
    code, r = cli("objective", "set", "comfort")
    assert code == EXIT_INPUT_ERROR and "M3" in r["message"]


# ---------------------------------------------------------------------------
# measure / compare
# ---------------------------------------------------------------------------

def test_measure_and_compare(cli, tmp_path):
    _needs("measure.vector", "measure.compare")
    a = _write(tmp_path / "a.wav", _sine(1000, amp=0.25))
    b = _write(tmp_path / "b.wav", _sine(1000, amp=0.125))
    code, r = cli("measure", str(a))
    assert code == EXIT_OK and r["file"] == "a.wav"
    assert r["info"]["sample_rate"] == SR
    p03 = r["vector"]["P-03"]
    assert -30 < p03["integrated_lufs"] < 0
    assert "analyzer_version" in r["vector"]

    code, r = cli("compare", str(a), str(b))
    assert code == EXIT_OK and r["a"] == "a.wav" and r["b"] == "b.wav"
    assert isinstance(r["comparison"], dict) and r["comparison"]

    code, r = cli("--format", "text", "measure", str(a), text=True)
    assert code == EXIT_OK and "file: a.wav" in r


# ---------------------------------------------------------------------------
# project lifecycle
# ---------------------------------------------------------------------------

def test_init_status_validate(cli, tmp_path, monkeypatch):
    _needs("project", "journal")
    proj = tmp_path / "song.mmx"
    code, r = cli("init", str(proj), "--title", "Test Song", "--genre", "jpop")
    assert code == EXIT_OK and r["created"] and r["project"] == "song.mmx" and r["title"] == "Test Song"
    assert (proj / "project.json").is_file()
    assert cli("init", str(proj), "--title", "Again")[0] == EXIT_INPUT_ERROR

    code, r = cli("-p", str(proj), "status")
    assert code == EXIT_OK and r["title"] == "Test Song" and r["genre"] == "jpop"
    assert r["assets"] == [] and r["tracks"] == []

    monkeypatch.chdir(proj)                      # default project = current folder
    code, r = cli("validate")
    assert code == EXIT_OK and r["valid"] is True
    code, r = cli("status", "--format", "text", text=True)
    assert code == EXIT_OK and r.startswith("Test Song")

    # breaking the document makes validate fail with an input error
    data = json.loads((proj / "project.json").read_text(encoding="utf-8"))
    data["timebase"] = "broken"
    (proj / "project.json").write_text(json.dumps(data), encoding="utf-8")
    code, r = cli("validate")
    assert code == EXIT_INPUT_ERROR and r["error"] == "validation_error"


def test_import_analyze_cache(cli, tmp_path, stem_folder):
    _needs("project", "journal", "adapters.file", "ingest.checks", "measure.vector")
    proj = tmp_path / "song.mmx"
    assert cli("init", str(proj), "--title", "Test Song")[0] == EXIT_OK
    assert cli("-p", str(proj), "import", str(stem_folder), "--provenance", "[1]")[0] == EXIT_INPUT_ERROR
    assert cli("-p", str(proj), "import", str(tmp_path / "missing"))[0] == EXIT_INPUT_ERROR
    code, r = cli("-p", str(proj), "import", str(stem_folder), "--provenance", '{"notes": "synthetic"}')
    assert code == EXIT_OK, r
    assert r["assets"] == 4
    assert isinstance(r["checks"], list) and "checks" not in r["imported"][0]
    assert r["imported"][0]["provenance"]["declared_by_user"] is True

    code, st = cli("-p", str(proj), "status")
    assert code == EXIT_OK
    assert len(st["assets"]) == 4
    assert all(not a["path"].startswith("/") and ":" not in a["path"] for a in st["assets"])
    assert st["fullmix"] is not None
    assert {a["analysis"] for a in st["assets"]} == {"missing"}

    code, r = cli("-p", str(proj), "analyze")
    assert code == EXIT_OK, r
    assert r["measured"] == 5 and r["cached"] == 0 and r["saved"] is True
    assert r["stem_sum"]["stems"] == 3
    adir = proj / "analysis"
    files = sorted(p.name for p in adir.glob("*.json"))
    assert "stem_sum.json" in files and len(files) == 5
    rec = json.loads((adir / "stem_sum.json").read_text(encoding="utf-8"))
    assert set(rec) >= {"asset", "sha256", "analyzer_version", "vector"}
    for f in adir.glob("*.json"):
        assert_no_abs(f.read_text(encoding="utf-8"), tmp_path)

    code, r2 = cli("-p", str(proj), "analyze")
    assert code == EXIT_OK and r2["measured"] == 0 and r2["cached"] == 5 and r2["saved"] is False

    code, st = cli("-p", str(proj), "status")
    assert {a["analysis"] for a in st["assets"]} == {"fresh"}

    code, r3 = cli("-p", str(proj), "analyze", "--force")
    assert code == EXIT_OK and r3["measured"] == 5

    code, txt = cli("-p", str(proj), "analyze", "--format", "text", text=True)
    assert code == EXIT_OK and "measured: 0, cached: 5" in txt

    assert_no_abs((proj / "project.json").read_text(encoding="utf-8"), tmp_path)


def test_set_patch_history_undo(cli, tmp_path):
    _needs("project", "journal")
    proj = tmp_path / "song.mmx"
    assert cli("init", str(proj), "--title", "Before")[0] == EXIT_OK
    p = ("-p", str(proj))

    code, r = cli(*p, "--actor", "agent", "set", "/title", '"After"', "--reason", "rename")
    assert code == EXIT_OK, r
    assert cli(*p, "status")[1]["title"] == "After"

    code, r = cli(*p, "set", "/title", "not json")
    assert code == EXIT_INPUT_ERROR

    code, r = cli(*p, "patch", json.dumps([{"op": "replace", "path": "/title", "value": "Patched"}]))
    assert code == EXIT_OK, r
    assert cli(*p, "status")[1]["title"] == "Patched"

    patch_file = tmp_path / "ops.json"
    patch_file.write_text(json.dumps([{"op": "add", "path": "/notes", "value": "from file"}]), encoding="utf-8")
    assert cli(*p, "patch", f"@{patch_file}")[0] == EXIT_OK
    assert cli(*p, "patch", '{"not": "a patch"}')[0] == EXIT_INPUT_ERROR

    code, h = cli(*p, "history", "--limit", "10")
    assert code == EXIT_OK and h["count"] >= 3

    code, r = cli(*p, "undo")
    assert code == EXIT_OK, r
    code, r = cli(*p, "undo")
    assert code == EXIT_OK, r
    assert cli(*p, "status")[1]["title"] == "After"

    entries = cli(*p, "history")[1]["entries"]
    seqs = [e.get("seq") for e in entries if isinstance(e, dict) and isinstance(e.get("seq"), int)]
    assert seqs
    code, r = cli(*p, "checkout", str(min(seqs)))
    assert code == EXIT_OK, r
    assert cli(*p, "status")[1]["title"] == "Before"
