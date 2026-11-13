"""One-shot pipeline ``run`` (SPEC 6, 7.1, 9.4, 10.2, 15.2): planner only, input to verified masters.

A synthetic stem folder with a full mix (tests/fixtures/synth.py ``song_stems``,
three stems, 5 s) runs once through the CLI with a blend objective; a single 2-mix runs
through the API (full-mix route) twice to check determinism. Exit codes: 0
when every variant verifies, 1 when a stage gate or a verification fails, 2
for bad input. Iteration caps are kept small so the file stays well under two
minutes.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from mankomix.cli import main as cli_main
from mankomix.core import api, pipeline
from mankomix.core.errors import EXIT_INPUT_ERROR, EXIT_OK, EXIT_VERIFY_FAILED, InputError
from tests.fixtures import synth
from tests.test_cli import _forbidden, assert_no_abs
from tests.test_cli_stages import SR, write_song

STAGE_ORDER = ["project", "import", "separate", "analyze", "clean", "mix", "master", "render", "verify", "report",
               "deliver"]


def _cli(root: Path, *argv) -> tuple[int, dict]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = cli_main.main([str(a) for a in argv])
    out = buf.getvalue()
    assert_no_abs(out, root)
    return code, json.loads(out)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stage(res: dict, name: str, variant: str | None = None) -> dict:
    return next(s for s in res["stages"] if s["stage"] == name and (variant is None or s.get("variant") == variant))


def _no_abs_in_tree(folder: Path, root: Path) -> None:
    bad = [f.lower() for f in _forbidden(root)]
    for f in folder.rglob("*"):
        if f.suffix in (".json", ".md"):
            text = f.read_text(encoding="utf-8").lower()
            for b in bad:
                assert b not in text, f"absolute path in {f.name}"


def _write_2mix(path: Path, seconds: float = 3.0) -> Path:
    stems = synth.song_stems(sr=SR, seconds=seconds, seed=0)
    path.parent.mkdir(parents=True, exist_ok=True)
    synth.write_wav(path, synth.stem_sum({r: stems[r] for r in ("vocals", "drums", "bass", "synth")}), SR)
    return path


def _verify_exit(res: dict) -> int:
    passed = all((r.get("verify") or {}).get("passed") for r in res["results"].values())
    return EXIT_OK if passed else EXIT_VERIFY_FAILED


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("MANKOMIX_HOME", str(tmp_path / "home"))


# --------------------------------------------------------------------------
# stems + full mix, blend objective, through the CLI


@pytest.fixture(scope="module")
def stem_run(tmp_path_factory):
    with pytest.MonkeyPatch.context() as mp:
        root = tmp_path_factory.mktemp("run")
        mp.setenv("MANKOMIX_HOME", str(root / "home"))
        src = write_song(root / "My Song", seconds=5.0, roles=("vocals", "drums", "bass"), fullmix=True)
        code, res = _cli(root, "run", src, "--objective", "comfort:0.6+bass_heavy:0.4", "--profile", "spotify",
                         "--delivery", "distributor_44k16", "--out", root / "out", "--genre", "jpop",
                         "--mix-max-iter", "1", "--max-iter", "1")
        yield code, res, root


def test_stem_run_stages_and_gates(stem_run):
    code, res, root = stem_run
    assert res["kind"] == "run_summary" and res["stopped_at"] in (None, "verify")
    assert code == res["exit_code"] == _verify_exit(res)
    assert [s["stage"] for s in res["stages"]] == STAGE_ORDER
    assert res["project"] == "my_song.mmx" and res["created"] is True
    assert res["objective"] == "comfort:0.6+bass_heavy:0.4"
    assert res["variants"] == [{"id": "var_spotify", "objective": "comfort:0.6+bass_heavy:0.4", "primary": True,
                                "profile": "spotify", "deliveries": ["distributor_44k16"]}]
    assert _stage(res, "import")["gate"]["status"] == "pass"
    clean = _stage(res, "clean")
    assert clean["status"] in ("applied", "skipped")
    if clean["status"] == "applied":
        assert clean["gate"] == {"status": "pass", "check": "S-07", "failed": []}
    mix = _stage(res, "mix")
    assert mix["status"] == "applied" and mix["proposal_id"].startswith("mxp_")
    assert mix["gate"]["status"] in ("pass", "warning")
    assert res["route"] == "stem_mix"                       # the mix result feeds the master (R-21)
    master = _stage(res, "master", "var_spotify")
    assert master["status"] == "applied" and master["gate"]["status"] in ("pass", "warning")
    for u in res["unresolved"]:
        assert u["stage"] in ("mix", "master") and u["code"]
    assert set(res["timings"]) >= set(STAGE_ORDER) | {"total"}

    project = root / "my_song.mmx"
    data = json.loads((project / "project.json").read_text(encoding="utf-8"))
    assert data["genre"] == "jpop"
    assert [(b["id"], b["weight"]) for b in data["objective"]["blend"]] == [("comfort", 0.6), ("bass_heavy", 0.4)]
    assert data["mix"]["applied"]["proposal_id"] == mix["proposal_id"]
    v = next(v for v in data["variants"] if v["id"] == "var_spotify")
    assert v["outputs"][0]["profile"] == "spotify" and v["outputs"][0]["delivery"] == "distributor_44k16"
    assert v["master"]["route_detail"] == "stem_mix"
    # every proposal the planner made is stored and marked applied (R-31)
    pids = [mix["proposal_id"], master["proposal_id"]] + ([clean["proposal_id"]] if clean["status"] == "applied" else [])
    for pid in pids:
        prop = json.loads((project / "cache" / "proposals" / f"{pid}.json").read_text(encoding="utf-8"))
        assert prop["status"] == "applied" and prop["author"] == "planner"
    actors = {json.loads(x)["actor"] for x in (project / "journal.jsonl").read_text(encoding="utf-8").splitlines()[1:]
              if x.strip()}
    assert actors == {"planner"}
    assert api.validate_project(project)["valid"] is True


def test_stem_run_deliverables(stem_run):
    code, res, root = stem_run
    out = root / "out"
    project = root / "my_song.mmx"
    stored = json.loads((out / "run_summary.json").read_text(encoding="utf-8"))
    expect = {k: v for k, v in res.items() if k not in ("timings", "summary_file")}
    assert stored == expect and "timings" not in stored
    assert res["summary_file"] == "out/run_summary.json"
    files = set(res["deliverables"]["files"])
    rep = {"var_spotify/report_var_spotify.json", "var_spotify/report_var_spotify.ja.md",
           "var_spotify/report_var_spotify.en.md", "var_spotify/verify_var_spotify.json",
           "var_spotify/spotify__distributor_44k16.manifest.json"}
    assert rep <= files
    for f in files:
        assert (out / f).is_file()
    master = "var_spotify/spotify__distributor_44k16.wav"
    verified = res["results"]["var_spotify"]["verify"]["passed"]
    assert (master in files) == verified == res["results"]["var_spotify"]["delivered"]
    if verified:
        assert _sha(out / master) == _sha(project / "renders" / "var_spotify" / "spotify__distributor_44k16.wav")
    report = json.loads((out / "var_spotify" / "report_var_spotify.json").read_text(encoding="utf-8"))
    assert report
    assert (out / "var_spotify" / "report_var_spotify.ja.md").read_text(encoding="utf-8").strip()
    assert (out / "var_spotify" / "report_var_spotify.en.md").read_text(encoding="utf-8").strip()
    _no_abs_in_tree(out, root)
    _no_abs_in_tree(project / "reports", root)


# --------------------------------------------------------------------------
# a single 2-mix: full-mix route; deterministic


def test_fullmix_route_is_deterministic(tmp_path):
    mix = _write_2mix(tmp_path / "in" / "song.wav")
    runs = []
    for name in ("a", "b"):
        res = api.run([str(mix)], objective="bass_heavy:0.7", profile="spotify", delivery="distributor_44k16",
                      out=str(tmp_path / f"out_{name}"), project=str(tmp_path / f"{name}.mmx"), master_max_iter=0)
        runs.append(res)
        assert [s["stage"] for s in res["stages"]] == STAGE_ORDER
        assert res["exit_code"] == _verify_exit(res)
        m = _stage(res, "mix")
        assert m["status"] == "skipped" and "full-mix route" in m["reason"]["en"]
        assert res["route"] == "full_mix"
        assert res["variants"][0]["id"] == "var_spotify" and res["variants"][0]["objective"] == "bass_heavy:0.7"
        assert res["variants"][0]["deliveries"] == ["distributor_44k16"]
        files = set(res["deliverables"]["files"])
        assert ("var_spotify/spotify__distributor_44k16.wav" in files) == res["results"]["var_spotify"]["verify"]["passed"]
    a, b = (tmp_path / "a.mmx" / "renders" / "var_spotify", tmp_path / "b.mmx" / "renders" / "var_spotify")
    wavs = sorted(p.name for p in a.glob("*.wav"))
    assert wavs and wavs == sorted(p.name for p in b.glob("*.wav"))
    for w in wavs:
        xa, sra = sf.read(str(a / w), dtype="float64")
        xb, srb = sf.read(str(b / w), dtype="float64")
        assert sra == srb and np.array_equal(xa, xb)
        assert _sha(a / w) == _sha(b / w)          # float WAVs too: no PEAK chunk timestamp
    sa = json.loads((tmp_path / "out_a" / "run_summary.json").read_text(encoding="utf-8"))
    sb = json.loads((tmp_path / "out_b" / "run_summary.json").read_text(encoding="utf-8"))
    for x in (sa, sb):
        x["project"] = x["deliverables"]["out"] = None
    assert sa == sb


# --------------------------------------------------------------------------
# exit codes


def test_input_errors_exit_2(tmp_path):
    mix = _write_2mix(tmp_path / "in" / "song.wav", seconds=1.0)
    code, r = _cli(tmp_path, "run", tmp_path / "missing.wav", "--out", tmp_path / "out")
    assert code == EXIT_INPUT_ERROR and r["error"] == "input_error" and "missing.wav" in r["message"]
    code, r = _cli(tmp_path, "run", mix, "--profile", "no_such_profile")
    assert code == EXIT_INPUT_ERROR
    code, r = _cli(tmp_path, "run", mix, "--objective", "comfort:0.6+")
    assert code == EXIT_INPUT_ERROR
    code, r = _cli(tmp_path, "run", mix, "--variants", "[{\"objective\": \"comfort\"}]")
    assert code == EXIT_INPUT_ERROR and "profile" in r["message"]
    assert not (tmp_path / "song.mmx").exists()            # nothing was created


def test_verify_failure_exit_1_withholds_masters(tmp_path, monkeypatch):
    mix = _write_2mix(tmp_path / "in" / "song.wav")
    real = api.verify

    def failing(*args, **kwargs):
        return {**real(*args, **kwargs), "passed": False, "overall": "fail", "exit_code": 1}

    monkeypatch.setattr(api, "verify", failing)
    code, res = _cli(tmp_path, "run", mix, "--profile", "spotify", "--out", tmp_path / "out", "--max-iter", "0")
    assert code == EXIT_VERIFY_FAILED == res["exit_code"]
    assert res["status"] == "failed" and res["stopped_at"] == "verify"
    assert "var_spotify" in res["reason"]["en"]
    files = res["deliverables"]["files"]
    assert not any(f.endswith(".wav") for f in files)                  # no failing master is delivered
    assert "var_spotify/report_var_spotify.en.md" in files              # the report explains the failure
    assert _stage(res, "deliver")["withheld"] == [{"variant": "var_spotify", "reason": "verification failed"}]
    assert not list((tmp_path / "out").rglob("*.wav"))


def test_stage_gate_stops_the_run(tmp_path, monkeypatch):
    mix = _write_2mix(tmp_path / "in" / "song.wav")
    real = api.clean_apply

    def residual_over_limit(*args, **kwargs):
        r = real(*args, **kwargs)
        for a in r["assets"]:
            a["s07"] = {**(a.get("s07") or {}), "pass": False}
        return r

    monkeypatch.setattr(api, "clean_apply", residual_over_limit)
    res = api.run([str(mix)], profile="spotify", out=str(tmp_path / "out"), master_max_iter=0)
    assert res["status"] == "stopped" and res["stopped_at"] == "clean" and res["exit_code"] == EXIT_VERIFY_FAILED
    assert "S-07" in res["reason"]["en"]
    assert [s["stage"] for s in res["stages"]][-1] == "clean" and _stage(res, "clean")["status"] == "failed"
    assert res["deliverables"] is None
    stored = json.loads((tmp_path / "out" / "run_summary.json").read_text(encoding="utf-8"))
    assert stored["stopped_at"] == "clean"
    assert not (tmp_path / "song.mmx" / "renders" / "var_spotify").exists()


def test_master_send_back_stops_the_run(tmp_path):
    """The synthetic 2-mix pushed to the club window needs more limiting than R-14 allows (and S-08
    would fail): the master plan sends the problem back to the mix stage, which a planner-only run
    cannot revisit, so the run stops at master with exit code 1 and says why (SPEC 6, 6.6.3)."""
    mix = _write_2mix(tmp_path / "in" / "song.wav")
    code, res = _cli(tmp_path, "run", mix, "--objective", "bass_heavy:0.7", "--profile", "club",
                     "--out", tmp_path / "out", "--max-iter", "0")
    assert code == EXIT_VERIFY_FAILED == res["exit_code"]
    assert res["status"] == "stopped" and res["stopped_at"] == "master"
    assert [s["stage"] for s in res["stages"]] == STAGE_ORDER[:STAGE_ORDER.index("master") + 1]
    master = _stage(res, "master", "var_club")
    assert master["status"] == "failed" and master["gate"]["status"] == "fail"
    sb = master["send_back"]
    assert "R-14" in sb["rules"] and master["gate"]["send_back"] == sb["rules"]
    r14 = next(i for i in sb["items"] if i["rule"] == "R-14")
    assert r14["measured"]["gr_p95_db"] > 5.0 and r14["reason"]["en"]
    assert "R-14" in res["reason"]["en"] and res["reason"]["ja"]
    sent = [u for u in res["unresolved"] if u["code"] == "send_back"]
    assert sent and sent[0]["stage"] == "master" and sent[0]["rules"] == sb["rules"]
    assert res["deliverables"] is None and not list((tmp_path / "out").rglob("*.wav"))
    stored = json.loads((tmp_path / "out" / "run_summary.json").read_text(encoding="utf-8"))
    assert stored["stopped_at"] == "master" and stored["exit_code"] == EXIT_VERIFY_FAILED


# --------------------------------------------------------------------------
# variants and the MCP face


def test_plan_variants():
    vs = pipeline.plan_variants("comfort", ["spotify", "club"], ["hires_native", "distributor_44k16"])
    assert [(v["id"], v["profile"], v["deliveries"], v["primary"]) for v in vs] == [
        ("var_spotify", "spotify", ["hires_native", "distributor_44k16"], True),
        ("var_club", "club", ["hires_native", "distributor_44k16"], True)]
    vs = pipeline.plan_variants(variants=[
        {"objective": "comfort", "profile": "streaming_universal", "delivery": "hires_native"},
        {"objective": "comfort", "profile": "streaming_universal", "delivery": "distributor_44k16"},
        {"objective": "bass_heavy:0.7", "profile": "club"},
        {"objective": "club_impact", "profile": "club"}])
    assert [(v["id"], v["objective_label"], v["deliveries"]) for v in vs] == [
        ("var_streaming_universal", "comfort", ["hires_native", "distributor_44k16"]),
        ("var_bass_heavy_i70_club", "bass_heavy:0.7", ["dj_wav"]),
        ("var_club_impact_club", "club_impact", ["dj_wav"])]
    assert [v["primary"] for v in vs] == [True, False, False]
    assert vs[1]["objective"]["intensity"] == 0.7
    with pytest.raises(InputError):
        pipeline.plan_variants(variants=[{"profile": "club", "colour": "red"}])
    with pytest.raises(InputError):
        pipeline.plan_variants("comfort", "club", "no_such_delivery")
    with pytest.raises(InputError):
        pipeline.plan_variants("no_such_objective")
    assert pipeline.default_project_path(["x/My Song.wav"], "y/out").name == "my_song.mmx"


def test_mcp_pipeline_run_job(tmp_path):
    from mankomix.mcp.tools import Toolbox
    from mankomix.mcp.workspace import Workspace

    _write_2mix(tmp_path / "in" / "take.wav")
    tb = Toolbox(Workspace(tmp_path))
    job, is_error = tb.call("pipeline_run", {"sources": ["in/take.wav"], "profile": "spotify", "out": "deliver",
                                             "master_max_iter": 0, "async": True})
    assert not is_error and job["job_id"]
    assert tb.jobs.wait(job["job_id"], 300).state == "succeeded"
    done, is_error = tb.call("job_result", {"job_id": job["job_id"]})
    assert not is_error
    r = done["result"]
    assert r["status"] in ("ok", "failed") and r["exit_code"] == (0 if r["status"] == "ok" else 1)
    assert r["project"] == "take.mmx" and (tmp_path / "take.mmx" / "project.json").is_file()
    assert [s["stage"] for s in r["stages"]] == STAGE_ORDER
    assert (tmp_path / "deliver" / "run_summary.json").is_file()
    data = json.loads((tmp_path / "take.mmx" / "project.json").read_text(encoding="utf-8"))
    assert data["variants"][0]["id"] == "var_spotify"
    entries = [json.loads(x) for x in (tmp_path / "take.mmx" / "journal.jsonl").read_text(encoding="utf-8")
               .splitlines() if x.strip()]
    assert {e["actor"] for e in entries[1:]} == {"agent"}
    _no_abs_in_tree(tmp_path / "deliver", tmp_path)
