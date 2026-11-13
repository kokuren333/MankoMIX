"""Follow-ups of the run pipeline (SPEC 9.1, 10.1, 15.2).

- relative and absolute ``--project`` give the same project-relative results
  (run, report, listen);
- an explicit list of loose files is imported as one set (numbered stems plus
  the "0 <title>" full mix), not as one 2-mix per file;
- ``clean delta stems``: one delta for the whole stem set (Before minus the
  cleaned stem sum) that the listening set uses on stem routes;
- verification-only profiles: the rendered master judged against other
  profiles without re-rendering or changing the project.
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path

import numpy as np
import pytest

from mankomix.cli import main as cli_main
from mankomix.core import api
from mankomix.core import mixrender as mr
from mankomix.core.errors import EXIT_ENV_ERROR, EXIT_INPUT_ERROR
from mankomix.core.project import Project
from tests.fixtures import synth
from tests.test_cli import assert_no_abs
from tests.test_cli_stages import SR
from tests.test_run_pipeline import _write_2mix

SUNO = {"1 Vocals.wav": "vocals", "2 Drums.wav": "drums", "3 Bass.wav": "bass"}


def _cli(root: Path, *argv) -> tuple[int, dict]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = cli_main.main([str(a) for a in argv])
    out = buf.getvalue()
    assert_no_abs(out, root)
    return code, json.loads(out)


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("MANKOMIX_HOME", str(tmp_path / "home"))


def _suno_files(folder: Path, seconds: float = 3.0) -> list[Path]:
    stems = synth.song_stems(sr=SR, seconds=seconds, seed=0)
    folder.mkdir(parents=True, exist_ok=True)
    files = []
    for name, role in SUNO.items():
        synth.write_wav(folder / name, stems[role], SR)
        files.append(folder / name)
    synth.write_wav(folder / "0 My Song.wav", synth.stem_sum({r: stems[r] for r in SUNO.values()}), SR)
    return files + [folder / "0 My Song.wav"]


# --------------------------------------------------------------------------
# relative --project (BUG 1) and verification-only profiles (FEATURE B)


def test_relative_and_absolute_project_paths(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_2mix(tmp_path / "in" / "song.wav")
    code, _ = _cli(tmp_path, "init", "tmp/x/v01.mmx", "--title", "rel")
    assert code == 0
    code, res = _cli(tmp_path, "run", "in/song.wav", "--project", "tmp/x/v01.mmx", "--out", "tmp/x/out",
                     "--profile", "spotify", "--max-iter", "0")
    assert code != EXIT_ENV_ERROR and code == res["exit_code"], res
    assert res["project"] == "v01.mmx" and res["stopped_at"] in (None, "verify")
    rep = res["results"]["var_spotify"]["report"]
    assert rep["json"] == "reports/report_var_spotify.json"
    assert (tmp_path / "tmp/x/v01.mmx" / rep["json"]).is_file()
    assert (tmp_path / "tmp/x/out/var_spotify/report_var_spotify.json").is_file()

    _, rel_rep = _cli(tmp_path, "report", "var_spotify", "--project", "tmp/x/v01.mmx", "--lang", "en")
    _, abs_rep = _cli(tmp_path, "report", "var_spotify", "--project", tmp_path / "tmp/x/v01.mmx", "--lang", "en")
    assert rel_rep["paths"] == abs_rep["paths"] == {"json": "reports/report_var_spotify.json",
                                                     "md_ja": "reports/report_var_spotify.ja.md",
                                                     "md_en": "reports/report_var_spotify.en.md"}
    _, rel_l = _cli(tmp_path, "listen", "var_spotify", "--project", "tmp/x/v01.mmx")
    _, abs_l = _cli(tmp_path, "listen", "var_spotify", "--project", tmp_path / "tmp/x/v01.mmx")
    assert rel_l["files"] == abs_l["files"]
    for f in rel_l["files"].values():
        assert f is None or not f.startswith("tmp/")

    # verification-only profiles: the spotify master judged against youtube and club, nothing rendered
    proj = tmp_path / "tmp/x/v01.mmx"
    before = (proj / "project.json").read_bytes()
    wav = proj / "renders/var_spotify/spotify__hires_native.wav"
    stamp = wav.stat().st_mtime_ns
    code, ag = _cli(tmp_path, "verify", "var_spotify", "--project", "tmp/x/v01.mmx",
                    "--against-profile", "youtube", "--against-profile", "club")
    assert code == ag["exit_code"] and ag["kind"] == "verify_against_report"
    assert set(ag["profiles"]) == {"youtube", "club"}
    for pid, r in ag["profiles"].items():
        assert r["overall"] in ("pass", "fail", "incomplete")
        assert set(r["outputs"][0]["checks"]) == {"P-03", "S-01", "S-02"}
    # a -14 LUFS master is outside the club window (P-03)
    assert "P-03" in ag["profiles"]["club"]["failed"] and ag["passed"] is False and code == 1
    assert ag["path"] == "reports/verify_var_spotify__against.json" and (proj / ag["path"]).is_file()
    assert (proj / "project.json").read_bytes() == before and wav.stat().st_mtime_ns == stamp
    # MCP face, same function
    from mankomix.mcp.tools import Toolbox
    from mankomix.mcp.workspace import Workspace
    payload, is_error = Toolbox(Workspace(tmp_path)).call(
        "verify_run", {"project": "tmp/x/v01.mmx", "variant": "var_spotify", "profiles": ["youtube"],
                       "detail": "full"})
    assert not is_error and set(payload["profiles"]) == {"youtube"}


# --------------------------------------------------------------------------
# explicit file list (BUG 2) and the stem-set delta (FEATURE A)


def test_file_list_is_one_set_and_stems_delta(tmp_path):
    files = _suno_files(tmp_path / "export")
    root = tmp_path / "song.mmx"
    api.init_project(root, title="list")
    imp = api.import_files(root, [str(f) for f in files])
    assert len(imp["imported"]) == 1 and imp["imported"][0]["input_kind"] == "suno_studio_multitrack_export"
    data = Project.open(root).data
    roles = sorted(t["role"] for t in data["tracks"])
    assert roles == ["bass", "drums", "vocals"]
    assert data["fullmix_asset"] and sum(a["role"] == "fullmix" for a in data["assets"]) == 1
    assert api.route(root)["route"] == "full_mix"            # no mix result yet; a stem set nonetheless

    # a single file stays a 2-mix
    one = tmp_path / "one.mmx"
    api.init_project(one, title="one")
    api.import_files(one, [str(files[-1])])
    assert Project.open(one).data["tracks"] == []

    # stems delta: needs an applied cleanup that changed a stem
    with pytest.raises(Exception):
        api.clean_delta(root, "stems")
    plan = api.clean_plan(root, targets=[t["id"] for t in data["tracks"]], apply=True)
    assert plan["applied"] and plan["summary"]["items"], "the synthetic drums carry detectable artifacts"
    d = api.clean_delta(root, "stems")
    assert d["delta"] == "renders/delta/stem_sum_delta.wav" and d["cleaned"]
    assert "ast_fullmix" not in d["stems"] and set(d["stems"]) == {a for a in d["stems"]}
    p = Project.open(root)
    raw, _, _ = mr.static_sum(p)
    cl, _, _ = mr.static_sum(p, cleaned=True)
    got, sr = synth.read_wav(root / d["delta"])
    assert sr == SR and got.shape == raw.shape
    assert np.allclose(got, (raw - cl).astype(np.float32), atol=1e-7)
    stamp = (root / d["delta"]).stat().st_mtime_ns
    assert api.clean_delta(root, "stems")["delta"] == d["delta"]
    assert (root / d["delta"]).stat().st_mtime_ns == stamp   # unchanged cleanup: not rewritten
    code, r = _cli(tmp_path, "clean", "delta", "stems", "--project", root)
    assert code == 0 and r["delta"] == d["delta"]

    # the listening set of a stem route uses it as the one delta (SPEC 15.2)
    tracks = p.data["tracks"]
    i = next(k for k, t in enumerate(tracks) if t["id"] == "trk_vocals")
    api.patch(root, [{"op": "add", "path": f"/tracks/{i}/chain", "value": [
        {"id": "prc_v", "type": "gain", "params": {"gain_db": -1.0}, "reason": "mix"}]}], "human")
    api.master_plan(root, profile="spotify", delivery="hires_native", apply=True)
    api.render(root, "var_spotify")
    ls = api.audio_set(root, "var_spotify")
    assert ls["before_kind"] != "fullmix" and ls["files"]["delta"] == d["delta"]
