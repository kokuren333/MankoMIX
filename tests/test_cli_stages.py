"""CLI for the cleanup and mix stages and the remix operations (SPEC 6.4, 6.5, 9.3, 10.2, R-31).

A 6 s synthetic song (tests/fixtures/synth.py ``song_stems``: vocals, drums,
bass, synth) is written to a temporary folder and imported once; the stage
commands run through the in-process CLI (``cli.main.main``) and their JSON
output is checked, together with the files and project.json fields they
leave behind. The MCP tools for the same operations are checked at the end.
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path

import pytest

from mankomix.cli import main as cli_main
from mankomix.core.errors import EXIT_INPUT_ERROR, EXIT_OK
from tests.fixtures import synth
from tests.test_cli import assert_no_abs

SR = 48000
ROLES = ("vocals", "drums", "bass", "synth")


def write_song(folder: Path, seconds: float = 6.0, roles=ROLES, fullmix: bool = False) -> Path:
    stems = synth.song_stems(sr=SR, seconds=seconds, seed=0)
    sel = {r: stems[r] for r in roles}
    folder.mkdir(parents=True, exist_ok=True)
    for r, x in sel.items():
        synth.write_wav(folder / f"{r}.wav", x, SR)
    if fullmix:
        synth.write_wav(folder / "fullmix.wav", synth.stem_sum(sel), SR)
    return folder


class Cli:
    """In-process CLI returning (exit code, parsed JSON); checks that no absolute path leaks."""

    def __init__(self, root: Path, project: Path):
        self.root = root
        self.project = project

    def __call__(self, *argv, expect: int | None = EXIT_OK, project: bool = True):
        args = [str(a) for a in argv]
        if project:
            args = [args[0], "--project", str(self.project), *args[1:]] if args else args
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = cli_main.main(args)
        out = buf.getvalue()
        assert_no_abs(out, self.root)
        if expect is not None:
            assert code == expect, out
        return code, json.loads(out)


def _proposal(project: Path, pid: str) -> dict:
    return json.loads((project / "cache" / "proposals" / f"{pid}.json").read_text(encoding="utf-8"))


def _data(project: Path) -> dict:
    return json.loads((project / "project.json").read_text(encoding="utf-8"))


def _journal_ops(project: Path) -> list[str]:
    lines = (project / "journal.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(x)["op"] for x in lines if x.strip()]


@pytest.fixture(scope="module")
def song(tmp_path_factory):
    with pytest.MonkeyPatch.context() as mp:
        root = tmp_path_factory.mktemp("stages")
        mp.setenv("MANKOMIX_HOME", str(root / "home"))
        src = write_song(root / "song src")
        project = root / "song.mmx"
        cli = Cli(root, project)
        cli("init", project, "--title", "Stage Song", "--genre", "jpop", project=False)
        cli("import", src)
        cli("analyze")
        yield cli, project, root


# --------------------------------------------------------------------------
# cleanup stage


def test_clean_plan_apply_delta(song):
    cli, project, _ = song
    _, plan = cli("clean", "plan")
    pid = plan["proposal_id"]
    assert pid.startswith("cln_") and plan["stage"] == "clean" and plan["applied"] is False
    assert plan["proposal_path"] == f"cache/proposals/{pid}.json"
    s = plan["summary"]
    assert {i["asset"] for i in s["items"]} | {k["asset"] for k in s["skipped"]} == \
        {f"ast_{r}" for r in ROLES}
    assert s["items"], "the synthetic drums carry detectable artifacts"
    for k in s["skipped"]:
        assert k["code"] == "nothing_detected" and k["reason"]
    stored = _proposal(project, pid)
    assert stored["status"] == "proposed" and stored["author"] == "planner" and stored["requested_by"] == "human"

    # the same plan shows up as a reviewable proposal
    _, listed = cli("plan", "list", "--stage", "clean")
    view = next(p for p in listed["proposals"] if p["id"] == pid)
    assert view["stage"] == "cleanup" and view["status"] == "pending"
    assert {st["processor"]["type"] for st in view["steps"]} == {"cleanup"}

    _, applied = cli("clean", "apply", pid)
    assert applied["applied"] is True and applied["proposal_id"] == pid and applied["s07_pass"] is True
    # cleaned assets, plus the skipped ones recorded as such (the "nothing detected" decision is kept)
    assert {a["asset"] for a in applied["assets"] if not a["skipped"]} == {i["asset"] for i in s["items"]}
    assert {a["asset"] for a in applied["assets"] if a["skipped"]} == {k["asset"] for k in s["skipped"]}
    assert _proposal(project, pid)["status"] == "applied"
    data = _data(project)
    for i in s["items"]:
        tr = next(t for t in data["tracks"] if t["id"] == i["track"])
        assert tr["cleanup"]["applied"]["proposal_id"] == pid
        assert tr["cleanup"]["applied"]["assets"][i["asset"]]["plan_hash"]
    assert "clean_apply" in _journal_ops(project)

    target = s["items"][0]["asset"]
    _, d = cli("clean", "delta", target)
    assert d["asset"] == target and d["delta"] == f"renders/delta/{target}.wav"
    assert (project / d["delta"]).is_file() and d["plan_hash"]
    # by track id too
    _, d2 = cli("clean", "delta", s["items"][0]["track"])
    assert d2["delta"] == d["delta"]
    # nothing was removed from an asset where nothing was detected
    if s["skipped"]:
        _, err = cli("clean", "delta", s["skipped"][0]["asset"], expect=EXIT_INPUT_ERROR)
        assert "skipped" in err["message"]


def test_clean_overrides_reject_and_bad_input(song):
    cli, project, _ = song
    _, plan = cli("plan", "propose", "--stage", "clean", "--target", "trk_drums",
                  "--overrides", json.dumps({"spectral_reduction": "skip"}))
    pid = plan["proposal_id"]
    assert plan["stage"] == "clean"
    assert [i["asset"] for i in plan["summary"]["items"]] + [k["asset"] for k in plan["summary"]["skipped"]] \
        == ["ast_drums"]
    _, rej = cli("plan", "reject", pid, "--reason", "keep the raw drums")
    assert rej["rejected"] is True and _proposal(project, pid)["status"] == "rejected"
    _, err = cli("clean", "apply", pid, expect=EXIT_INPUT_ERROR)
    assert "rejected" in err["message"]
    _, err = cli("clean", "plan", "--target", "no_such_track", expect=EXIT_INPUT_ERROR)
    assert "unknown cleanup target" in err["message"]
    _, err = cli("plan", "propose", "--stage", "clean", "--profile", "spotify", expect=EXIT_INPUT_ERROR)
    assert "cleanup stage" in err["message"]


# --------------------------------------------------------------------------
# mix stage


def test_mix_plan_apply_and_edits(song):
    cli, project, _ = song
    _, plan = cli("mix", "plan", "--max-iter", "1")
    pid = plan["proposal_id"]
    s = plan["summary"]
    assert pid.startswith("mxp_") and plan["stage"] == "mix" and plan["applied"] is False
    assert [st["n"] for st in s["steps"]] == list(range(1, 8))
    assert s["lead"] == "trk_vocals" and s["route"] in ("stem_mix", "stem_sum")
    assert s["score"] is not None and s["gate"]["status"] in ("pass", "fail", "incomplete")
    assert set(plan["decision_texts"]) == {"balance", "pan", "frequency", "depth", "dynamics", "interest"}
    assert "proposal" in plan and _proposal(project, pid)["status"] == "proposed"

    _, applied = cli("mix", "apply", pid)
    assert applied["applied"] is True and applied["stage"] == "mix" and applied["route"] == "stem_mix"
    assert applied["evaluation_stored"] and applied["decisions_stored"]
    data = _data(project)
    assert data["mix"]["applied"]["proposal_id"] == pid and data["mix"]["evaluation"]["proposal_id"] == pid
    assert set(data["mix"]["decisions"]) >= {"balance"}
    assert _proposal(project, pid)["status"] == "applied"
    assert "mix_apply" in _journal_ops(project)
    _, v = cli("validate")
    assert v["valid"] is True

    # edits change a proposed processor parameter before approval (R-31)
    prop = _proposal(project, pid)
    procs = [p for d in prop["changes"]["tracks"].values() for p in d.get("chain") or []]
    proc = next(p for p in procs if any(isinstance(x, (int, float)) and not isinstance(x, bool)
                                        for x in p["params"].values()))
    key = next(k for k, x in proc["params"].items() if isinstance(x, (int, float)) and not isinstance(x, bool))
    new = proc["params"][key] + 1
    _, edited = cli("plan", "apply", pid, "--edits", json.dumps({proc["id"]: {key: new}}))
    assert edited["edited"] == [f"{proc['id']}.{key}"] and edited["stage"] == "mix"
    found = [p for t in _data(project)["tracks"] for p in t.get("chain") or [] if p["id"] == proc["id"]]
    assert found and found[0]["params"][key] == new
    _, err = cli("mix", "apply", pid, "--edits", json.dumps({"nope": {"x": 1}}), expect=EXIT_INPUT_ERROR)
    assert "no processor" in err["message"]

    # a cleanup proposal is not a mix proposal
    _, err = cli("mix", "apply", json.dumps({"proposal_id": "cln_000000000000", "stage": "clean"}),
                 expect=EXIT_INPUT_ERROR)
    assert "not a mix proposal" in err["message"]


# --------------------------------------------------------------------------
# remix operations


@pytest.fixture
def remix(tmp_path, monkeypatch):
    monkeypatch.setenv("MANKOMIX_HOME", str(tmp_path / "home"))
    src = write_song(tmp_path / "src", seconds=4.0, roles=("vocals", "drums", "bass"))
    extra = tmp_path / "extra"
    extra.mkdir()
    synth.write_wav(extra / "guitar take.wav", synth.song_stems(sr=SR, seconds=4.0, seed=1)["guitar"], SR)
    project = tmp_path / "remix.mmx"
    cli = Cli(tmp_path, project)
    cli("init", project, "--title", "Remix", project=False)
    cli("import", src)
    return cli, project, extra


def test_stem_operations(remix):
    cli, project, extra = remix
    _, ls = cli("stem", "list")
    tracks = {t["id"]: t for t in ls["tracks"]}
    assert set(tracks) == {"trk_vocals", "trk_drums", "trk_bass"} and ls["lead"] == "trk_vocals"
    clip = tracks["trk_bass"]["clips"][0]["id"]

    _, r = cli("stem", "split", clip, "1.5s")
    assert r["op"] == "clip_split" and r["at"] == int(1.5 * SR)
    _, r = cli("stem", "mute", "trk_drums", "0.5s", str(SR))
    assert r["op"] == "range_mute" and r["start"] == SR // 2 and r["end"] == SR and r["muted_clips"]
    _, r = cli("stem", "move", r["muted_clips"][0], "0.25s")
    assert r["op"] == "clip_move" and r["timeline_start"] == SR // 4
    _, r = cli("stem", "role", "trk_bass", "synth", "--reason", "it is a synth bass")
    assert r["op"] == "set_role" and r["role"] == "synth"
    _, r = cli("stem", "range-replace", "trk_drums", "2s", "3s", "ast_bass")
    assert r["op"] == "range_replace" and r["asset"] == "ast_bass"

    _, add = cli("stem", "add", extra / "guitar take.wav", "--role", "guitar")
    assert add["op"] == "stem_add" and add["role"] == "guitar" and add["origin"] == "added"
    assert add["consistency"]["status"] and add["track"]
    _, rp = cli("stem", "replace", "trk_vocals", "--asset", add["asset"], "--drop-chain")
    assert rp["op"] == "stem_replace" and rp["asset"] == add["asset"]
    _, err = cli("stem", "replace", "trk_vocals", expect=EXIT_INPUT_ERROR)
    assert "exactly one" in err["message"]
    _, rm = cli("stem", "remove", add["track"])
    assert rm["op"] == "stem_remove"

    _, ex = cli("stem", "export", "--track", "trk_drums", "--track", "trk_bass", "--subtype", "PCM_24")
    assert ex["files"] == ["renders/stems/trk_drums.wav", "renders/stems/trk_bass.wav"]
    assert ex["manifest"] == "renders/stems/manifest.json"
    for f in ex["files"] + [ex["manifest"]]:
        assert (project / f).is_file()
    _, err = cli("stem", "export", "--out-dir", "../outside", expect=EXIT_INPUT_ERROR)
    assert err["error"] == "input_error"

    assert _journal_ops(project)[-8:] == ["clip_split", "range_mute", "clip_move", "set_role", "range_replace",
                                          "stem_add", "stem_replace", "stem_remove"]
    _, v = cli("validate")
    assert v["valid"] is True
    _, u = cli("undo")
    assert u
    _, ls = cli("stem", "list")
    assert add["track"] in {t["id"] for t in ls["tracks"]}       # the removal was undone


def test_mcp_stage_and_stem_tools(remix):
    from mankomix.mcp.tools import Toolbox
    from mankomix.mcp.workspace import Workspace

    cli, project, extra = remix
    tb = Toolbox(Workspace(project.parent))
    names = set(tb.names())
    assert {"stems_list", "stems_add", "stems_replace", "stems_edit", "stems_export", "clean_plan",
            "clean_apply", "clean_delta", "mix_plan", "mix_apply", "pipeline_run"} <= names

    def ok(name, **args):
        payload, is_error = tb.call(name, args)
        assert not is_error, payload
        return payload

    ls = ok("stems_list", project="remix.mmx")
    assert {t["id"] for t in ls["tracks"]} == {"trk_vocals", "trk_drums", "trk_bass"}
    r = ok("stems_edit", project="remix.mmx", op="mute", track="trk_bass", start="1s", end="2s")
    assert r["op"] == "range_mute"
    payload, is_error = tb.call("stems_edit", {"project": "remix.mmx", "op": "split"})
    assert is_error and "needs" in payload["message"]
    add = ok("stems_add", project="remix.mmx", source="extra/guitar take.wav", role="guitar")
    assert add["op"] == "stem_add"
    plan = ok("plan_propose", project="remix.mmx", stage="clean")
    assert plan["proposal_id"].startswith("cln_") and "items" in plan
    ex = ok("stems_export", project="remix.mmx", tracks=["trk_vocals"], out_dir="renders/mcp")
    assert ex["files"] == ["renders/mcp/trk_vocals.wav"]
    entries = [json.loads(x) for x in (project / "journal.jsonl").read_text(encoding="utf-8").splitlines() if x]
    assert entries[-1]["actor"] == "agent" and entries[-1]["op"] == "stem_add"
