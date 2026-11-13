"""M7 completion criterion: an agent completes one full round of work through MCP alone.

SPEC 17 (M7 row): "an agent can complete one full round of work using MCP only";
SPEC 10.1 (CLI and MCP wrap the core 1:1, JSON results, no absolute paths) and
SPEC 10.3 (tool table, summary by default with a detail argument, jobs for long work,
workspace restriction).

The real server is launched as ``python -m mankomix.mcp --root <workspace>`` and driven
over stdio JSON-RPC exactly as an MCP client would: ``initialize``, ``tools/list`` and
``tools/call`` only. No CLI and no core API call performs an action here; result files
are only read for assertions. The agent below discovers every tool from ``tools/list``,
validates its own arguments against the advertised input schema, and runs every tool
that advertises ``async`` as a background job (``job_status`` / ``job_result``).

The round (on a 4 s synthetic stem set, run twice in two identical workspaces to check
determinism):

  project_init -> project_open -> import_files -> analyze_run -> objective_set (blend)
  -> plan_propose / plan_apply for the clean, mix and master stages -> plan_list
  -> gate_check -> render_preview -> render_spectrogram -> export_run -> verify_run
  -> verify_get -> report_get (ja, en) -> history_list -> history_undo -> history_checkout
  (redo) -> stems_list -> stems_edit (mute, role) -> stems_export (effect of the mute)
  -> model_list / model_get -> knowledge_lookup -> project_validate -> pipeline_run
  -> master_plan / master_apply (by proposal id)

Steps that cannot be completed today are kept as separate xfail tests with the exact
gap in the reason; the coverage tests compare tools/list with the SPEC 10.3 table and
with the CLI command set (``python -m mankomix.cli --help`` and the group helps).
"""

from __future__ import annotations

import concurrent.futures
import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import soundfile as sf

from tests.test_cli_stages import write_song
from tests.test_mcp import McpProcess, _forbidden

REPO = Path(__file__).resolve().parent.parent
SPEC_FILE = REPO / "docs" / "SPEC.md"
SR = 48000
SECONDS = 3.0
ROLES = ("vocals", "drums", "bass", "synth")
PROJECT = "song.mmx"
PROJECT_ID = "prj_m7e2e00001"        # fixed so that the two workspaces are comparable
JOB_TIMEOUT_S = 300.0

# Default (summary) responses must stay small enough for an agent's context.
SUMMARY_LIMIT_BYTES = 8 * 1024

# Error codes a tool failure may carry: core/errors.py (CLI codes) + the MCP server's own.
DOCUMENTED_ERRORS = {"input_error", "validation_error", "environment_error", "verify_failed",
                     "path_outside_workspace", "project_busy", "unknown_job", "unknown_tool"}

# Keys whose values legitimately differ between two identical runs (wall clock).
VOLATILE_KEYS = {"ts", "elapsed_s", "seconds", "created_at", "updated_at", "applied_at", "rejected_at",
                 "generated_at", "started_at", "finished_at", "duration_s", "wall_s", "time_s", "proposed_at"}


# ---------------------------------------------------------------------------
# the agent: MCP client that only uses what tools/list advertises
# ---------------------------------------------------------------------------

@dataclass
class Call:
    tool: str
    args: dict
    payload: Any
    is_error: bool
    nbytes: int
    detail: str
    job: bool = False
    secs: float = 0.0


@dataclass
class Agent:
    srv: McpProcess
    tools: dict = field(default_factory=dict)
    log: list = field(default_factory=list)
    _validators: dict = field(default_factory=dict)

    def discover(self) -> list[dict]:
        tools = self.srv.request("tools/list")["result"]["tools"]
        self.tools = {t["name"]: t for t in tools}
        return tools

    def has(self, name: str) -> bool:
        return name in self.tools

    def is_long(self, name: str) -> bool:
        return "async" in self.tools[name]["inputSchema"].get("properties", {})

    def _check_args(self, name: str, args: dict) -> None:
        from jsonschema import Draft202012Validator
        v = self._validators.get(name)
        if v is None:
            v = self._validators[name] = Draft202012Validator(self.tools[name]["inputSchema"])
        errors = [e.message for e in v.iter_errors(args)]
        assert not errors, f"the agent's own arguments for {name} violate the advertised schema: {errors}"

    def _raw(self, name: str, args: dict, detail: str, job: bool = False) -> tuple[Any, bool]:
        t0 = time.monotonic()
        resp = self.srv.request("tools/call", {"name": name, "arguments": args})
        assert "result" in resp, f"{name}: JSON-RPC error instead of a tool result: {resp}"
        res = resp["result"]
        text = res["content"][0]["text"]
        payload = json.loads(text)
        assert payload == res["structuredContent"], name
        self.log.append(Call(name, copy.deepcopy(args), payload, bool(res["isError"]),
                             len(text.encode("utf-8")), detail, job, time.monotonic() - t0))
        return payload, bool(res["isError"])

    def call(self, name: str, *, expect_error: str | None = None, unlisted: bool = False, **args) -> Any:
        """Call a tool the way an agent would. Long tools (schema has 'async') go through a job."""
        detail = args.get("detail", "summary")
        if not self.has(name):
            assert unlisted, f"tool {name} is not in tools/list"
            payload, is_error = self._raw(name, args, detail)
        else:
            self._check_args(name, args)
            if self.is_long(name):
                submit = {k: v for k, v in args.items() if k != "detail"} | {"async": True}
                job, is_error = self._raw(name, submit, "summary")
                assert not is_error, (name, job)
                assert job["state"] in ("queued", "running", "succeeded", "failed") and job["tool"] == name
                payload, is_error = self._wait(job["job_id"], detail)
                if not is_error:
                    assert payload["tool"] == name and payload["state"] == "succeeded"
                    payload = payload["result"]
            else:
                payload, is_error = self._raw(name, args, detail)
        if expect_error is not None:
            assert is_error, f"{name}{args}: expected error {expect_error}, got {payload}"
            assert payload.get("error") == expect_error, (name, args, payload)
        else:
            assert not is_error, f"{name}{args} failed: {payload}"
        return payload

    def try_call(self, name: str, **args) -> tuple[Any, bool]:
        """Call without asserting success (for steps that are known gaps)."""
        n = len(self.log)
        try:
            payload = self.call(name, unlisted=True, **args)
            return payload, False
        except AssertionError:
            last = self.log[n:][-1] if len(self.log) > n else None
            return (last.payload if last else None), True

    def _wait(self, job_id: str, detail: str) -> tuple[Any, bool]:
        deadline = time.monotonic() + JOB_TIMEOUT_S
        while True:
            st, err = self._raw("job_status", {"job_id": job_id}, "summary", job=True)
            assert not err, st
            if st["state"] in ("succeeded", "failed"):
                break
            assert time.monotonic() < deadline, f"job {job_id} did not finish"
            time.sleep(0.05)
        return self._raw("job_result", {"job_id": job_id, "detail": detail}, detail, job=True)


# ---------------------------------------------------------------------------
# the round
# ---------------------------------------------------------------------------

def _round(agent: Agent, root: Path) -> dict:
    """One full round of work, MCP only. Returns the named results (the log is on the agent)."""
    R: dict[str, Any] = {}
    p = {"project": PROJECT}
    R["tools"] = agent.discover()

    # create / open, import as-is, analyze
    R["init"] = agent.call("project_init", project=PROJECT, title="M7 round", genre="jpop", project_id=PROJECT_ID)
    R["open_empty"] = agent.call("project_open", **p)
    R["import"] = agent.call("import_files", **p, sources=["stems"])
    R["analyze"] = agent.call("analyze_run", **p)
    R["analyze_full"] = agent.call("analyze_run", **p, detail="full")   # cached second run, full result
    R["open"] = agent.call("project_open", **p)
    R["open_full"] = agent.call("project_open", **p, detail="full")

    # intent: a blend, plus a structured error for an unknown objective
    R["objective_bad"] = agent.call("objective_set", **p, spec="no_such_objective", expect_error="validation_error")
    R["objective"] = agent.call("objective_set", **p, spec="comfort:0.6+bass_heavy:0.4")

    # stage plans: propose -> approve and apply, for clean, mix and master
    R["clean_plan"] = agent.call("plan_propose", **p, stage="clean")
    R["clean_apply"] = agent.call("plan_apply", **p, proposal=R["clean_plan"]["proposal_id"])
    R["mix_plan"] = agent.call("plan_propose", **p, stage="mix", max_iter=1)
    R["mix_apply"] = agent.call("plan_apply", **p, proposal=R["mix_plan"]["proposal_id"])
    R["master_plan"] = agent.call("plan_propose", **p, stage="master", profile="spotify", max_iter=1)
    R["master_plan_full"] = agent.call("plan_get", **p, proposal_id=R["master_plan"]["proposal_id"], detail="full")
    R["master_apply"] = agent.call("plan_apply", **p, proposal=R["master_plan"]["proposal_id"])
    R["apply_bad"] = agent.call("plan_apply", **p, proposal="mpl_000000000000", expect_error="input_error")
    R["plan_list"] = agent.call("plan_list", **p)
    R["variants"] = agent.call("variant_list", **p)
    R["gate"] = agent.call("gate_check", **p)

    # render, spectrogram (SPEC 10.3), export, verify, report
    R["render"] = agent.call("render_preview", **p)
    R["spectrogram"], R["spectrogram_failed"] = agent.try_call("render_spectrogram", **p)
    R["export"] = agent.call("export_run", **p)
    R["verify"] = agent.call("verify_run", **p)
    R["verify_full"] = agent.call("verify_get", **p, detail="full")
    R["report_ja"] = agent.call("report_get", **p, lang="ja")
    R["report_en"] = agent.call("report_get", **p, lang="en")
    R["report_ja_full"] = agent.call("report_get", **p, lang="ja", detail="full")

    # history: list, undo, redo (checkout of the undone entry)
    R["history"] = agent.call("history_list", **p)
    R["history_full"] = agent.call("history_list", **p, detail="full")
    last = R["history"]["entries"][-1]
    R["history_last"] = last
    R["chain_before_undo"] = agent.call("project_get", **p, pointer="/variants")
    R["undo"] = agent.call("history_undo", **p)
    R["chain_after_undo"] = agent.call("project_get", **p, pointer="/variants", detail="full")
    R["redo"] = agent.call("history_checkout", **p, seq=last["seq"])
    R["chain_after_redo"] = agent.call("project_get", **p, pointer="/variants")

    # remix operations and their effect
    R["stems_before"] = agent.call("stems_list", **p)
    R["mute"] = agent.call("stems_edit", **p, op="mute", track="trk_drums", start="1s", end="2s",
                           reason="drop the drums for one second")
    R["role"] = agent.call("stems_edit", **p, op="role", track="trk_synth", role="keyboard")
    R["edit_bad"] = agent.call("stems_edit", **p, op="split", expect_error="input_error")
    R["stems_after"] = agent.call("stems_list", **p)
    R["stems_export"] = agent.call("stems_export", **p, tracks=["trk_drums"], processed=False, out_dir="renders/e2e")

    # catalogues (no network)
    R["models"] = agent.call("model_list")
    R["models_full"] = agent.call("model_list", detail="full")
    R["model"] = agent.call("model_get", id=R["models"]["models"][0]["id"])
    R["kn_query"] = agent.call("knowledge_lookup", query="muddy")
    R["kn_rule"] = agent.call("knowledge_lookup", id="R-14")

    # workspace restriction stays enforced in the round
    R["escape"] = agent.call("import_files", **p, sources=["../outside"], expect_error="path_outside_workspace")
    R["unknown"] = agent.call("no_such_tool", unlisted=True, expect_error="unknown_tool")

    R["validate"] = agent.call("project_validate", **p)
    R["history_end"] = agent.call("history_list", **p, limit=50)

    # the one-shot pipeline tool on the same stems, into its own project
    R["pipeline"] = agent.call("pipeline_run", sources=["stems"], objective="comfort", profile="spotify",
                               out="out", project="oneshot.mmx", title="M7 one-shot",
                               mix_max_iter=1, master_max_iter=1)
    R["pipeline_report"] = agent.call("report_get", project="oneshot.mmx", lang="en")

    # stage-specific master tools: apply by the proposal id master_plan returned (SPEC 10.3 README)
    R["mplan"] = agent.call("master_plan", **p, profile="spotify")
    R["mplan_id"] = R["mplan"].get("proposal", {}).get("proposal_id")
    R["mapply_id"], R["mapply_id_failed"] = agent.try_call("master_apply", **p, proposal_or_path=R["mplan_id"])
    R["mapply_rel"], R["mapply_rel_failed"] = agent.try_call("master_apply", **p,
                                                             proposal_or_path=R["mplan"].get("proposal_path"))
    return R


@dataclass
class RoundRun:
    root: Path
    R: dict
    log: list
    raw: list
    stderr: str
    exit_code: int


def _run_round(root: Path, stderr_file: Path) -> RoundRun:
    srv = McpProcess(root, stderr_file)
    code = None
    try:
        init = srv.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                          "clientInfo": {"name": "m7-e2e", "version": "1"}})
        assert init["result"]["capabilities"] == {"tools": {"listChanged": False}}
        srv.notify("notifications/initialized")
        agent = Agent(srv)
        R = _round(agent, root)
    finally:
        code = srv.close()
    err = stderr_file.read_text(encoding="utf-8", errors="replace")
    return RoundRun(root, R, agent.log, list(srv.raw), err, code)


@pytest.fixture(scope="module")
def rounds(tmp_path_factory):
    """The same round in two identical workspaces (run concurrently, one server each)."""
    base = tmp_path_factory.mktemp("m7e2e")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("MANKOMIX_HOME", str(base / "home"))     # model registry state stays in the sandbox
        # no network: any HTTP(S) attempt by the server (e.g. model_list) would hit a dead proxy
        for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY"):
            mp.setenv(var, "http://127.0.0.1:9")
        for var in ("NO_PROXY", "no_proxy"):
            mp.delenv(var, raising=False)
        # one stem set, copied byte for byte (libsndfile stamps the time into a FLOAT WAV's PEAK
        # chunk, so writing it twice would not give identical inputs)
        src = write_song(base / "stems_src", seconds=SECONDS, roles=ROLES)
        roots = []
        for name in ("ws_a", "ws_b"):
            root = base / name
            shutil.copytree(src, root / "stems")
            roots.append(root)
        (base / "outside").mkdir()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
            futs = [ex.submit(_run_round, r, base / f"{r.name}.stderr.log") for r in roots]
            a, b = (f.result() for f in futs)
        yield {"a": a, "b": b, "base": base}


# ---------------------------------------------------------------------------
# helpers for the assertions
# ---------------------------------------------------------------------------

_ABS_RE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]|\\\\[A-Za-z0-9]|(?:^|[\s\"'=(])/(?:tmp|home|Users|var|private|mnt)/")


def _strings(obj: Any):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _strings(k)
            yield from _strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v)


def _normalize(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: ("<volatile>" if k in VOLATILE_KEYS else _normalize(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_normalize(v) for v in obj]
    return obj


def _mask_project_identity(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: ("<project>" if k in ("project_id", "project_hash", "content_hash", "after_hash", "before_hash")
                    else _mask_project_identity(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_mask_project_identity(v) for v in obj]
    if isinstance(obj, str):
        return re.sub(r"prj_[0-9a-f]{10}", "prj_*", obj)
    return obj


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _proj(run: RoundRun) -> Path:
    return run.root / PROJECT


# ---------------------------------------------------------------------------
# the round: protocol hygiene over every call
# ---------------------------------------------------------------------------

def test_round_server_exits_cleanly(rounds):
    for key in ("a", "b"):
        run = rounds[key]
        assert run.exit_code == 0, run.stderr[-3000:]
        assert "Traceback" not in run.stderr, run.stderr[-3000:]


def test_round_every_call_succeeds_or_fails_structured(rounds):
    run = rounds["a"]
    assert len(run.log) > 60
    for c in run.log:
        assert isinstance(c.payload, dict), (c.tool, c.payload)
        if c.is_error:
            assert set(c.payload) >= {"error", "message"}, (c.tool, c.args, c.payload)
            assert isinstance(c.payload["message"], str) and c.payload["message"]
            assert c.payload["error"] in DOCUMENTED_ERRORS, (c.tool, c.args, c.payload)
            assert isinstance(c.payload.get("details", {}), dict)
    # the only failures are the ones the round provoked on purpose, plus the known gaps
    provoked = {("objective_set", "validation_error"), ("plan_apply", "input_error"), ("stems_edit", "input_error"),
                ("import_files", "path_outside_workspace"), ("no_such_tool", "unknown_tool")}
    gaps = {("render_spectrogram", "unknown_tool"), ("master_apply", "input_error")}
    seen = {(c.tool, c.payload["error"]) for c in run.log if c.is_error}
    assert seen <= provoked | gaps, seen - provoked - gaps
    assert provoked <= seen


def test_round_no_absolute_paths_anywhere(rounds):
    base = rounds["base"]
    for key in ("a", "b"):
        run = rounds[key]
        joined = "".join(run.raw)
        low = joined.lower()
        for f in _forbidden(base, run.root):
            assert f not in low, f"absolute path leaked into MCP output: {f}"
        for c in run.log:
            for s in _strings(c.payload):
                assert not _ABS_RE.search(s), (c.tool, s[:200])


def test_round_summaries_are_bounded_and_detail_returns_more(rounds):
    run = rounds["a"]
    summaries = [c for c in run.log if c.detail == "summary"]
    worst = max(summaries, key=lambda c: c.nbytes)
    assert worst.nbytes < SUMMARY_LIMIT_BYTES, (worst.tool, worst.nbytes)
    R = run.R
    size = lambda x: len(json.dumps(x, ensure_ascii=False).encode("utf-8"))   # noqa: E731
    pairs = [("project_open", R["open"], R["open_full"]),
             ("analyze_run", R["analyze"], R["analyze_full"]),
             ("report_get", R["report_ja"], R["report_ja_full"]),
             ("history_list", R["history"], R["history_full"]),
             ("model_list", R["models"], R["models_full"]),
             ("plan_propose/plan_get", R["master_plan"], R["master_plan_full"])]
    for name, summary, full in pairs:
        assert size(full) > size(summary), name
    # summaries drop the bulky parts
    assert "assets" in R["open_full"] and isinstance(R["open"]["tracks"], int)
    assert "proposal" not in R["master_plan"] and "proposal" in R["master_plan_full"]
    assert all("patch" not in e for e in R["history"]["entries"])
    assert any("patch" in e for e in R["history_full"]["entries"])
    assert len(R["report_ja"]["markdown"]) < len(R["report_ja_full"]["markdown"])


def test_round_long_tools_ran_as_jobs(rounds):
    run = rounds["a"]
    long_tools = {c.tool for c in run.log if c.args.get("async") is True}
    assert {"analyze_run", "plan_propose", "render_preview", "export_run", "stems_export",
            "pipeline_run"} <= long_tools
    listed = {x["name"]: x for x in run.R["tools"]}
    for t in long_tools:
        tool = listed[t]
        assert "job_id" in tool["description"] and "async" in tool["inputSchema"]["properties"]
    assert any(c.tool == "job_status" for c in run.log) and any(c.tool == "job_result" for c in run.log)


# ---------------------------------------------------------------------------
# the round: step results
# ---------------------------------------------------------------------------

def test_round_project_import_analyze(rounds):
    R = rounds["a"].R
    assert R["init"]["created"] is True and R["init"]["project"] == PROJECT and R["init"]["id"] == PROJECT_ID
    assert R["open_empty"]["tracks"] == 0
    imp = R["import"]["imported"][0]
    assert R["import"]["assets"] == len(ROLES) and imp["input_kind"] == "stem_folder"
    assert sorted(imp["assets_added"]) == sorted(f"ast_{r}" for r in ROLES) and imp["lead"] == "trk_vocals"
    assert R["analyze"]["measured"] == len(ROLES) + 1 and R["analyze"]["stem_sum"] == len(ROLES)
    assert R["open"]["tracks"] == len(ROLES) and R["open"]["lead"] == "trk_vocals"
    assert R["open"]["analysis"] == {"fresh": len(ROLES), "stem_sum:fresh": 1}


def test_round_objective_blend(rounds):
    R = rounds["a"].R
    assert R["objective"]["set"] == "project"
    assert [(b["id"], b["weight"]) for b in R["objective"]["objective"]["blend"]] == [("comfort", 0.6),
                                                                                      ("bass_heavy", 0.4)]
    assert R["objective"]["resolved"]["lead"]["stem"] == "trk_vocals"
    assert "no_such_objective" in json.dumps(R["objective_bad"]["details"])


def test_round_stage_plans_clean_mix_master(rounds):
    run = rounds["a"]
    R = run.R
    cp, ca = R["clean_plan"], R["clean_apply"]
    assert cp["proposal_id"].startswith("cln_") and cp["stage"] == "clean" and cp["applied"] is False
    assert ca["applied"] is True and ca["stage"] == "clean" and ca["s07_pass"] is True
    mp, ma = R["mix_plan"], R["mix_apply"]
    assert mp["proposal_id"].startswith("mxp_") and mp["stage"] == "mix" and mp["route"] == "stem_mix"
    assert [s["n"] for s in mp["steps"]] == list(range(1, 8))
    assert ma["applied"] is True and ma["stage"] == "mix" and ma["evaluation_stored"] is True
    sp, sa = R["master_plan"], R["master_apply"]
    assert sp["proposal_id"].startswith("mpl_") and sp["stage"] == "master" and sp["variant"] == "var_spotify"
    assert sp["gate"]["status"] in ("pass", "fail", "incomplete") and sp["breakdown"]
    assert sa["applied"] is True and sa["stage"] == "master" and sa["score"] == sp["score"]
    for pr in (cp, mp, sp):
        assert pr["proposal_path"] == f"cache/proposals/{pr['proposal_id']}.json"
        assert (_proj(run) / pr["proposal_path"]).is_file()
    statuses = {x["id"]: x["status"] for x in R["plan_list"]["proposals"]}
    assert statuses[cp["proposal_id"]] == statuses[mp["proposal_id"]] == statuses[sp["proposal_id"]] == "applied"
    assert R["variants"]["count"] == 1 and R["variants"]["variants"][0]["has_master_chain"] is True
    assert R["gate"]["status"] in ("pass", "fail", "incomplete") and R["gate"]["checks"]
    # proposals made through MCP are recorded as the agent's (D-035: shown as agent proposals in the GUI)
    for pr in (cp, mp, sp):
        stored = json.loads((_proj(run) / pr["proposal_path"]).read_text(encoding="utf-8"))
        assert (stored["status"], stored["author"], stored["requested_by"]) == ("applied", "agent", "agent")


@pytest.mark.ffmpeg  # verify measures the codec round trips (S-02); incomplete without ffmpeg
def test_round_render_export_verify(rounds):
    run = rounds["a"]
    R = run.R
    proj = _proj(run)
    for key in ("render", "export"):
        r = R[key]
        assert r["variant"] == "var_spotify" and r["outputs"]
        for o in r["outputs"]:
            assert o["status"] == "pass" and (proj / o["file"]).is_file() and (proj / o["manifest"]).is_file()
        assert (proj / r["archive"]["file"]).is_file()
    master = proj / R["export"]["outputs"][0]["file"]
    info = sf.info(str(master))
    assert info.samplerate > 0 and abs(info.duration - SECONDS) < 0.05
    v = R["verify"]
    assert v["passed"] is True and v["overall"] == "pass" and v["exit_code"] == 0
    assert (proj / v["path"]).is_file()
    assert R["verify_full"]["overall"] == "pass"


def test_round_report_ja_en(rounds):
    run = rounds["a"]
    R = run.R
    proj = _proj(run)
    ja, en = R["report_ja"], R["report_en"]
    for rep in (ja, en):
        assert rep["variant"] == "var_spotify"
        for f in rep["paths"].values():
            assert (proj / f).is_file(), f
    assert set(ja["paths"]) >= {"json", "md_ja", "md_en"}
    assert ja["markdown"].startswith("# Mix Report") and en["markdown"].startswith("# Mix Report")
    assert re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", ja["markdown"]), "ja markdown has no Japanese"
    assert not re.search(r"[\u3040-\u30ff]", en["markdown"]), "en markdown contains kana"
    md_ja = (proj / ja["paths"]["md_ja"]).read_text(encoding="utf-8")
    assert md_ja.startswith(R["report_ja_full"]["markdown"][:200])


def test_round_history_undo_redo(rounds):
    R = rounds["a"].R
    entries = R["history"]["entries"]
    ops = [e["op"] for e in entries]
    for op in ("import", "analyze", "objective_set", "clean_apply", "mix_apply"):
        assert op in ops, (op, ops)
    assert {e["actor"] for e in entries if e["op"] != "create"} == {"agent"}
    last = R["history_last"]
    assert R["undo"]["undone"]["undoes"] == last["seq"] and R["undo"]["undone"]["actor"] == "agent"
    assert R["undo"]["content_hash"] != last["after_hash"]
    assert R["chain_after_undo"]["value"] != R["chain_before_undo"]["value"]
    # redo-equivalent: checkout of the undone entry restores exactly its state
    assert R["redo"]["checked_out"] == last["seq"] and R["redo"]["content_hash"] == last["after_hash"]
    assert R["chain_after_redo"] == R["chain_before_undo"]
    end_ops = [e["op"] for e in R["history_end"]["entries"]]
    assert end_ops[-4:] == ["undo", "checkout", "range_mute", "set_role"], end_ops


def test_round_stems_edit_and_effect(rounds):
    run = rounds["a"]
    R = run.R
    before = {t["id"]: t for t in R["stems_before"]["tracks"]}
    after = {t["id"]: t for t in R["stems_after"]["tracks"]}
    assert set(before) == set(after) == {f"trk_{r}" for r in ROLES}
    assert R["mute"]["op"] == "range_mute" and (R["mute"]["start"], R["mute"]["end"]) == (SR, 2 * SR)
    muted = [c for c in after["trk_drums"]["clips"] if c["muted"]]
    assert [(c["timeline_start"], c["length"]) for c in muted] == [(SR, SR)]
    assert not any(c["muted"] for c in before["trk_drums"]["clips"])
    assert R["role"]["op"] == "set_role" and before["trk_synth"]["role"] == "synth"
    assert after["trk_synth"]["role"] == "keyboard"
    assert "needs" in R["edit_bad"]["message"]
    # the effect on audio: the exported raw drum stem is silent exactly in the muted range
    ex = R["stems_export"]
    assert ex["files"] == ["renders/e2e/trk_drums.wav"] and ex["processed"] is False
    y, sr = sf.read(str(_proj(run) / ex["files"][0]), always_2d=True)
    assert sr == SR
    assert np.max(np.abs(y[SR:2 * SR])) == 0.0
    assert np.max(np.abs(y[:SR])) > 1e-3 and np.max(np.abs(y[2 * SR:])) > 1e-3


def test_round_models_and_knowledge(rounds):
    R = rounds["a"].R
    models = R["models"]["models"]
    assert models and all({"id", "status", "license_weights", "state"} <= set(m) for m in models)
    assert R["model"]["id"] == models[0]["id"] and R["model"]["license_weights"]
    assert any(e["id"] == "komori" and e["kind"] == "term" for e in R["kn_query"]["entries"])
    rule = R["kn_rule"]["entries"]
    assert R["kn_rule"]["count"] == 1 and rule[0]["kind"] == "rule" and rule[0]["data"]["text"]["en"]


def test_round_final_project_validates_and_files_exist(rounds):
    run = rounds["a"]
    R = run.R
    assert R["validate"]["valid"] is True and R["validate"]["issues"] == []
    proj = _proj(run)
    assert (proj / R["export"]["outputs"][0]["file"]).is_file()
    for f in R["report_en"]["paths"].values():
        assert (proj / f).is_file()
    assert not (rounds["base"] / "outside" / "project.json").exists()


@pytest.mark.ffmpeg  # verify measures the codec round trips (S-02); incomplete without ffmpeg
def test_round_one_shot_pipeline(rounds):
    run = rounds["a"]
    r = run.R["pipeline"]
    assert r["project"] == "oneshot.mmx" and r["created"] is True
    assert r["status"] == "ok" and r["exit_code"] == 0, (r.get("stopped_at"), r.get("reason"), r.get("unresolved"))
    stages = [s["stage"] for s in r["stages"]]
    assert stages[:4] == ["project", "import", "separate", "analyze"]
    for st in ("clean", "mix", "master", "render", "verify", "report", "deliver"):
        assert st in stages, (st, stages)
    assert r["verify"] == {"var_spotify": "pass"}
    assert (run.root / r["summary_file"]).is_file()
    # deliverables are listed relative to 'out' (see test_gap_pipeline_deliverable_paths)
    out = run.root / "out"
    assert r["deliverables"] and all((out / f).is_file() or (run.root / f).is_file() for f in r["deliverables"])
    assert any(f.endswith(".wav") for f in r["deliverables"])
    assert run.R["pipeline_report"]["markdown"].startswith("# Mix Report")


# ---------------------------------------------------------------------------
# determinism: the same calls on an identical workspace give the same results
# ---------------------------------------------------------------------------

def test_round_is_deterministic_across_workspaces(rounds):
    a, b = rounds["a"], rounds["b"]
    assert [(c.tool, c.args) for c in a.log if c.tool not in ("job_status",)] == \
           [(c.tool, c.args) for c in b.log if c.tool not in ("job_status",)]
    ca = [c for c in a.log if c.tool != "job_status"]
    cb = [c for c in b.log if c.tool != "job_status"]
    diffs = []
    for x, y in zip(ca, cb):
        nx, ny = _normalize(x.payload), _normalize(y.payload)
        if x.args.get("project") == "oneshot.mmx" or x.tool == "pipeline_run" or (
                x.tool == "job_result" and isinstance(nx.get("result"), dict) and "stages" in nx["result"]):
            # the one-shot project gets a fresh random id (pipeline_run takes no project_id), and the
            # project hash covers it
            nx, ny = (_mask_project_identity(n) for n in (nx, ny))
        if nx != ny:
            diffs.append(x.tool)
    assert not diffs, f"responses differ between identical workspaces: {diffs}"
    # byte-identical audio deliverables and identical reports
    for r in a.R["export"]["outputs"]:
        assert _sha(_proj(a) / r["file"]) == _sha(_proj(b) / r["file"]), r["file"]
    arch = a.R["export"]["archive"]["file"]
    assert _sha(_proj(a) / arch) == _sha(_proj(b) / arch)
    assert _sha(_proj(a) / "renders/e2e/trk_drums.wav") == _sha(_proj(b) / "renders/e2e/trk_drums.wav")
    for f in a.R["report_en"]["paths"].values():
        ja = _normalize(json.loads((_proj(a) / f).read_text(encoding="utf-8"))) if f.endswith(".json") else \
            (_proj(a) / f).read_text(encoding="utf-8")
        jb = _normalize(json.loads((_proj(b) / f).read_text(encoding="utf-8"))) if f.endswith(".json") else \
            (_proj(b) / f).read_text(encoding="utf-8")
        assert ja == jb, f
    pa = json.loads((_proj(a) / "project.json").read_text(encoding="utf-8"))
    pb = json.loads((_proj(b) / "project.json").read_text(encoding="utf-8"))
    assert _normalize(pa) == _normalize(pb)
    for f in a.R["pipeline"]["deliverables"] or []:
        if f.endswith(".wav") or f.endswith(".flac"):
            fa = a.root / "out" / f if (a.root / "out" / f).is_file() else a.root / f
            fb = b.root / "out" / f if (b.root / "out" / f).is_file() else b.root / f
            assert _sha(fa) == _sha(fb), f


# ---------------------------------------------------------------------------
# known gaps in the round (precise reasons; xpass means the gap was closed)
# ---------------------------------------------------------------------------

@pytest.mark.xfail(reason="render_spectrogram (SPEC 10.3 table, M7 row 'spectrogram') is not exposed: "
                          "tools/call render_spectrogram {project: 'song.mmx'} returns isError "
                          "{error: 'unknown_tool'}; mcp/tools.py has the ToolSpec but core/api.py has no "
                          "render_spectrogram function, so the hasattr guard skips it. Expected: a project-"
                          "relative spectrogram image of a rendered variant (job-capable).", strict=False)
def test_gap_render_spectrogram(rounds):
    R = rounds["a"].R
    assert not R["spectrogram_failed"], R["spectrogram"]
    files = [s for s in _strings(R["spectrogram"]) if re.search(r"\.(png|svg|webp)$", s)]
    assert files and all((_proj(rounds["a"]) / f).is_file() for f in files)


@pytest.mark.xfail(reason="master_apply rejects the proposal id that master_plan returns: tools/call "
                          "master_apply {project: 'song.mmx', proposal_or_path: 'mpl_<id>'} -> isError "
                          "{error: 'input_error', message: 'proposal not found: mpl_<id>'}; the project-relative "
                          "proposal_path 'cache/proposals/mpl_<id>.json' fails the same way. Cause: the API "
                          "parameter name ends in '_path', so mcp/tools.py binds it as a workspace path and "
                          "passes an absolute path instead of the id (only the workspace-relative 'song.mmx/cache/"
                          "proposals/<id>.json' works). Expected (core/api.py docstring and the "
                          "error's own hint): a proposal id or cache/proposals/<id>.json is accepted, as "
                          "plan_apply does.", strict=False)
def test_gap_master_apply_by_proposal_id(rounds):
    R = rounds["a"].R
    assert R["mplan_id"] and R["mplan_id"].startswith("mpl_")
    assert not R["mapply_id_failed"], R["mapply_id"]
    assert R["mapply_id"]["applied"] is True and R["mapply_id"]["proposal_id"] == R["mplan_id"]
    assert not R["mapply_rel_failed"], R["mapply_rel"]


@pytest.mark.xfail(reason="render_preview has no section / range argument: its inputSchema properties are "
                          "project, variant, outputs (+detail, async) and it renders every output at full "
                          "length, identical to export_run. SPEC 10.2 defines render as 'preview (with a "
                          "section given)' and SPEC 10.3 separates render_preview from export_run. The CLI "
                          "'render' has the same gap (only --output), so CLI/MCP are equivalent here.",
                   strict=False)
def test_gap_render_preview_section(rounds):
    tool = next(t for t in rounds["a"].R["tools"] if t["name"] == "render_preview")
    props = set(tool["inputSchema"]["properties"])
    assert props & {"start", "end", "section", "sections", "range", "excerpt", "excerpt_s"}, sorted(props)


@pytest.mark.xfail(reason="report_get lang='ja' (or 'en') returns a resolved single-language report whose "
                          "'language' field still says 'both' (core/report.py resolve_language does not "
                          "update it); an agent cannot tell from the payload which language it got.",
                   strict=False)
def test_gap_report_language_label(rounds):
    R = rounds["a"].R
    assert R["report_ja"]["report"]["language"] == "ja"
    assert R["report_en"]["report"]["language"] == "en"


@pytest.mark.xfail(reason="pipeline_run mixes path bases in one response: summary_file is workspace-relative "
                          "('out/run_summary.json') but deliverables are relative to the out folder "
                          "('var_spotify/spotify__hires_native.wav', which does not exist at that workspace "
                          "path). Expected (SPEC 10.1, mcp/README: paths relative to the workspace/project): "
                          "every returned path resolvable against the same base.", strict=False)
def test_gap_pipeline_deliverable_paths(rounds):
    run = rounds["a"]
    r = run.R["pipeline"]
    assert r["deliverables"]
    for f in r["deliverables"]:
        assert (run.root / f).is_file(), f


# ---------------------------------------------------------------------------
# coverage: tools/list vs SPEC 10.3 and vs the CLI command set
# ---------------------------------------------------------------------------

def _spec_tools() -> list[str]:
    text = SPEC_FILE.read_text(encoding="utf-8")
    start = text.index("### 10.3")
    end = text.index("\n---", start)
    names: list[str] = []
    for line in text[start:end].splitlines():
        if line.startswith("|") and not line.startswith("|---"):
            first = line.split("|")[1]
            names += re.findall(r"`([a-z]+_[a-z_]+)`", first)
    return names


SPEC_TOOLS = _spec_tools()
KNOWN_MISSING_SPEC_TOOLS = {
    "render_spectrogram": "listed in SPEC 10.3 (and M7 'spectrogram') but not in tools/list: core/api.py has no "
                          "render_spectrogram, so the ToolSpec in mcp/tools.py is skipped",
}

# CLI command (as printed by the helps) -> MCP tool. None: a face command, not a tool (SPEC 10.2 'faces').
CLI_TO_MCP: dict[str, str | None] = {
    "doctor": "doctor", "init": "project_init", "import": "import_files", "status": "project_open",
    "validate": "project_validate", "analyze": "analyze_run", "measure": "measure_audio",
    "compare": "compare_audio", "set": "project_set", "patch": "project_patch", "history": "history_list",
    "undo": "history_undo", "checkout": "history_checkout", "get": "project_get", "gate": "gate_check",
    "knowledge": "knowledge_lookup", "route": "route_get", "render": "render_preview", "export": "export_run",
    "verify": "verify_run", "verify --last": "verify_get", "listen": "audio_get", "analysis": "analysis_get",
    "separate": "separate_run", "separate --records": "separate_list", "run": "pipeline_run",
    "report": "report_get",
    "profile list": "profile_list", "profile show": "profile_get", "profile deliveries": "delivery_list",
    "objective list": "objective_list", "objective show": "objective_get", "objective set": "objective_set",
    "objective validate": "objective_validate",
    "reference add": "reference_add", "reference list": "reference_list", "reference remove": "reference_remove",
    "plan propose": "plan_propose", "plan apply": "plan_apply", "plan list": "plan_list", "plan show": "plan_get",
    "plan reject": "plan_reject", "plan run": "plan_run",
    "master plan": "master_plan", "master apply": "master_apply",
    "variant list": "variant_list",
    "model list": "model_list", "model show": "model_get", "model pull": "model_pull",
    "model register": "model_register", "model verify": "model_verify", "model remove": "model_remove",
    "clean plan": "clean_plan", "clean apply": "clean_apply", "clean delta": "clean_delta",
    "mix plan": "mix_plan", "mix apply": "mix_apply",
    "stem list": "stems_list", "stem add": "stems_add", "stem replace": "stems_replace",
    "stem remove": "stems_remove", "stem move": "stems_edit", "stem mute": "stems_edit",
    "stem split": "stems_edit", "stem range-replace": "stems_edit", "stem role": "stems_edit",
    "stem export": "stems_export",
    "serve": None, "mcp": None,
}
# CLI flags that select a different core function (and so a different MCP tool).
CLI_FLAG_COMMANDS = {"verify --last": ("verify", "--last"), "separate --records": ("separate", "--records")}
KNOWN_CLI_ONLY = {
    "route": "CLI 'route' (core api.route, mastering route selection R-21) has no MCP tool: mcp/tools.py SPECS has "
             "no entry for api.route, against SPEC 10.1 (no feature on one face only)",
}
SERVER_TOOLS = {"job_status", "job_result", "job_list"}       # server-level, no CLI counterpart (README)


def _help(*argv: str) -> str:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["PYTHONIOENCODING"] = "utf-8"
    out = subprocess.run([sys.executable, "-m", "mankomix.cli", *argv, "--help"], capture_output=True,
                         cwd=str(REPO), env=env, timeout=120)
    assert out.returncode == 0, out.stderr.decode("utf-8", "replace")
    return out.stdout.decode("utf-8", "replace")


def _subcommands(help_text: str, metavar: str) -> list[str]:
    """Names listed under the positional COMMAND / SUBCOMMAND block of an argparse help."""
    lines = help_text.splitlines()
    try:
        i = next(n for n, line in enumerate(lines) if line.strip() == metavar)
    except StopIteration:
        return []
    names = []
    for line in lines[i + 1:]:
        if not line.strip() or not line.startswith("    "):
            if line.strip() and not line.startswith(" "):
                break
            continue
        m = re.match(r"^    ([a-z][a-z0-9-]*)(\s|$)", line)
        if m:
            names.append(m.group(1))
    return names


@pytest.fixture(scope="module")
def cli_commands() -> dict[str, str]:
    """Every CLI command path ('stem mute', 'render', ...) with its help text."""
    top = _subcommands(_help(), "COMMAND")
    assert {"init", "import", "render", "plan", "stem", "mcp"} <= set(top), top
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        helps = dict(zip(top, ex.map(lambda c: _help(c), top)))
    out: dict[str, str] = {}
    for cmd, text in helps.items():
        subs = _subcommands(text, "SUBCOMMAND")
        if subs:
            for s in subs:
                out[f"{cmd} {s}"] = text
        else:
            out[cmd] = text
    for name, (cmd, flag) in CLI_FLAG_COMMANDS.items():
        assert flag in helps[cmd], f"CLI '{cmd}' lost its {flag} option"
        out[name] = helps[cmd]
    return out


@pytest.fixture(scope="module")
def mcp_tools(tmp_path_factory) -> dict[str, dict]:
    root = tmp_path_factory.mktemp("m7cov")
    srv = McpProcess(root, root / "stderr.log")
    try:
        srv.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})
        tools = srv.request("tools/list")["result"]["tools"]
    finally:
        assert srv.close() == 0
    return {t["name"]: t for t in tools}


def test_spec_table_parsed():
    assert len(SPEC_TOOLS) >= 30 and len(set(SPEC_TOOLS)) == len(SPEC_TOOLS)
    assert {"project_open", "import_files", "plan_propose", "render_spectrogram", "history_undo"} <= set(SPEC_TOOLS)


@pytest.mark.parametrize("name", [
    pytest.param(n, marks=pytest.mark.xfail(reason=KNOWN_MISSING_SPEC_TOOLS[n], strict=False))
    if n in KNOWN_MISSING_SPEC_TOOLS else n
    for n in SPEC_TOOLS])
def test_spec_10_3_tool_is_listed(mcp_tools, name):
    assert name in mcp_tools, f"SPEC 10.3 lists {name} but tools/list does not"


def test_spec_10_3_tools_follow_group_verb_naming(mcp_tools):
    for name in mcp_tools:
        if name == "doctor":
            continue
        assert re.fullmatch(r"[a-z]+_[a-z]+", name), name


def test_cli_command_set_is_mapped(cli_commands):
    """Every CLI command printed by the helps has a declared MCP counterpart (or is a face)."""
    unmapped = sorted(set(cli_commands) - set(CLI_TO_MCP))
    assert not unmapped, f"CLI commands without an MCP mapping in this test: {unmapped}"
    stale = sorted(k for k in set(CLI_TO_MCP) - set(cli_commands))
    assert not stale, f"mapped CLI commands no longer in the CLI helps: {stale}"


def test_cli_and_mcp_are_one_to_one(cli_commands, mcp_tools):
    """SPEC 10.1: each CLI command has its MCP tool and each MCP tool its CLI command (known gaps aside)."""
    missing = sorted(c for c, t in CLI_TO_MCP.items()
                     if c in cli_commands and t is not None and t not in mcp_tools and c not in KNOWN_CLI_ONLY)
    assert not missing, f"CLI commands without an MCP tool: {[(c, CLI_TO_MCP[c]) for c in missing]}"
    covered = {t for c, t in CLI_TO_MCP.items() if t is not None and c in cli_commands}
    mcp_only = sorted(set(mcp_tools) - covered - SERVER_TOOLS)
    assert not mcp_only, f"MCP tools without a CLI command: {mcp_only}"


@pytest.mark.parametrize("command", [pytest.param(c, marks=pytest.mark.xfail(reason=r, strict=False))
                                     for c, r in sorted(KNOWN_CLI_ONLY.items())])
def test_gap_cli_only_command_has_mcp_tool(cli_commands, mcp_tools, command):
    assert command in cli_commands
    assert CLI_TO_MCP[command] in mcp_tools, KNOWN_CLI_ONLY[command]


def test_round_used_only_listed_tools(rounds):
    """The round itself is MCP-only: every tool it called (bar the probes for gaps) is in tools/list."""
    run = rounds["a"]
    listed = {t["name"] for t in run.R["tools"]}
    called = {c.tool for c in run.log}
    assert called - listed <= {"render_spectrogram", "no_such_tool"}, called - listed
    used = called & listed
    for t in ("project_init", "project_open", "import_files", "analyze_run", "objective_set", "plan_propose",
              "plan_apply", "render_preview", "export_run", "verify_run", "report_get", "history_list",
              "history_undo", "history_checkout", "stems_edit", "stems_list", "stems_export", "model_list",
              "knowledge_lookup", "project_validate", "pipeline_run", "job_status", "job_result"):
        assert t in used, t
