"""MCP server tests (SPEC 10.3): JSON-RPC over stdio against a real subprocess.

The server is started as ``python -m mankomix.mcp --root <tmp>`` and spoken
to over pipes, exactly as an MCP client would. A few unit tests exercise the
job manager and the declarative tool table in-process.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from mankomix.core import api
from mankomix.core.errors import InputError

REPO = Path(__file__).resolve().parent.parent
SR = 48000
TIMEOUT_S = 120


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _sine(freq: float, seconds: float = 2.0, amp: float = 0.2) -> np.ndarray:
    t = np.arange(int(seconds * SR)) / SR
    return np.repeat((amp * np.sin(2 * np.pi * freq * t))[:, None], 2, axis=1)


def write_stem_folder(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for name, f in (("1 Drums.wav", 80.0), ("2 Bass.wav", 55.0), ("3 Vocals.wav", 440.0)):
        sf.write(str(folder / name), _sine(f), SR, subtype="PCM_24")
    return folder


def _forbidden(*paths: Path) -> list[str]:
    out = []
    for p in (*paths, Path.home(), REPO):
        s = str(p.resolve())
        out += [s, s.replace("\\", "/"), s.replace("\\", "\\\\")]
    return [x.lower() for x in out if len(x) > 3]


class McpProcess:
    """Minimal MCP client: newline-delimited JSON-RPC over the child's pipes."""

    def __init__(self, root: Path, stderr_file: Path):
        env = dict(os.environ)
        env["PYTHONPATH"] = str(REPO) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        env["PYTHONIOENCODING"] = "cp1252"          # the server must force UTF-8 itself
        self._err = open(stderr_file, "wb")
        self.proc = subprocess.Popen([sys.executable, "-m", "mankomix.mcp", "--root", str(root)],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._err,
                                     cwd=str(root), env=env)
        self.lines: queue.Queue = queue.Queue()
        self.raw: list[str] = []
        self._n = 0
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        for raw in self.proc.stdout:
            self.lines.put(raw)
        self.lines.put(None)

    def send_raw(self, text: str) -> None:
        self.proc.stdin.write(text.encode("utf-8") + b"\n")
        self.proc.stdin.flush()

    def read(self) -> dict:
        raw = self.lines.get(timeout=TIMEOUT_S)
        assert raw is not None, "server closed stdout"
        text = raw.decode("utf-8")              # must be UTF-8 even with PYTHONIOENCODING=cp1252
        assert text.endswith("\n") and "\n" not in text[:-1]
        self.raw.append(text)
        return json.loads(text)

    def request(self, method: str, params: dict | None = None) -> dict:
        self._n += 1
        msg = {"jsonrpc": "2.0", "id": self._n, "method": method}
        if params is not None:
            msg["params"] = params
        self.send_raw(json.dumps(msg, ensure_ascii=False))
        resp = self.read()
        assert resp["jsonrpc"] == "2.0" and resp["id"] == self._n
        return resp

    def notify(self, method: str, params: dict | None = None) -> None:
        msg = {"jsonrpc": "2.0", "method": method, **({"params": params} if params is not None else {})}
        self.send_raw(json.dumps(msg))

    def call(self, name: str, **arguments) -> tuple[dict, bool]:
        resp = self.request("tools/call", {"name": name, "arguments": arguments})
        res = resp["result"]
        assert res["content"][0]["type"] == "text"
        payload = json.loads(res["content"][0]["text"])
        assert payload == res["structuredContent"]
        return payload, res["isError"]

    def ok(self, name: str, **arguments) -> dict:
        payload, is_error = self.call(name, **arguments)
        assert not is_error, payload
        return payload

    def close(self) -> int:
        try:
            self.proc.stdin.close()
            return self.proc.wait(timeout=TIMEOUT_S)
        finally:
            if self.proc.poll() is None:
                self.proc.kill()
            self._err.close()


@pytest.fixture
def workspace(tmp_path) -> Path:
    root = tmp_path / "ws"
    write_stem_folder(root / "export")
    return root


@pytest.fixture
def server(workspace, tmp_path):
    srv = McpProcess(workspace, tmp_path / "stderr.log")
    init = srv.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                      "clientInfo": {"name": "pytest", "version": "1"}})
    assert init["result"]["protocolVersion"] == "2025-06-18"
    srv.notify("notifications/initialized")
    yield srv
    code = srv.close()
    assert code == 0, (tmp_path / "stderr.log").read_text(encoding="utf-8", errors="replace")
    joined = "".join(srv.raw).lower()
    for f in _forbidden(tmp_path):
        assert f not in joined, f"absolute path leaked into MCP output: {f}"


# ---------------------------------------------------------------------------
# protocol
# ---------------------------------------------------------------------------

def test_initialize_versions(workspace, tmp_path):
    srv = McpProcess(workspace, tmp_path / "stderr.log")
    try:
        for v in ("2025-06-18", "2025-03-26", "2024-11-05"):
            r = srv.request("initialize", {"protocolVersion": v, "capabilities": {},
                                           "clientInfo": {"name": "t", "version": "0"}})["result"]
            assert r["protocolVersion"] == v
            assert r["serverInfo"]["name"] == "mankomix" and r["serverInfo"]["version"]
            assert r["capabilities"] == {"tools": {"listChanged": False}}
        r = srv.request("initialize", {"protocolVersion": "1999-01-01", "capabilities": {}})["result"]
        assert r["protocolVersion"] in ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
        assert srv.request("ping")["result"] == {}
    finally:
        assert srv.close() == 0


def test_tools_list_schemas(server):
    from jsonschema import Draft202012Validator

    tools = server.request("tools/list")["result"]["tools"]
    names = [t["name"] for t in tools]
    assert len(names) == len(set(names))
    expected = {"doctor", "project_init", "project_open", "project_get", "project_set", "project_patch",
                "project_validate", "import_files", "analyze_run", "measure_audio", "compare_audio",
                "objective_list", "objective_get", "profile_list", "profile_get", "history_list",
                "history_undo", "history_checkout", "knowledge_lookup", "job_status", "job_result", "job_list",
                # M3 (SPEC 10.3)
                "objective_set", "objective_validate", "reference_add", "reference_list", "reference_remove",
                "plan_propose", "plan_apply", "plan_reject", "plan_run", "gate_check"}
    assert expected <= set(names)
    for t in tools:
        assert t["description"]
        schema = t["inputSchema"]
        Draft202012Validator.check_schema(schema)
        assert schema["type"] == "object"
        for p in schema.get("required", []):
            assert p in schema["properties"]
        # the actor is never an argument: MCP calls are always the agent
        assert "actor" not in schema["properties"]
    by_name = {t["name"]: t for t in tools}
    assert "async" in by_name["analyze_run"]["inputSchema"]["properties"]
    assert "async" not in by_name["project_open"]["inputSchema"]["properties"]
    assert by_name["import_files"]["inputSchema"]["required"] == ["sources"]


def test_protocol_errors(server):
    server.send_raw("this is not json")
    r = server.read()
    assert r["id"] is None and r["error"]["code"] == -32700
    assert server.request("no/such/method")["error"]["code"] == -32601
    assert server.request("tools/call", {"arguments": {}})["error"]["code"] == -32602
    assert server.request("tools/call", {"name": "doctor", "arguments": [1]})["error"]["code"] == -32602
    server.send_raw(json.dumps({"jsonrpc": "1.0", "id": 99, "method": "ping"}))
    assert server.read()["error"]["code"] == -32600
    # notifications get no response; the next request still lines up
    server.notify("notifications/cancelled", {"requestId": 1})
    assert server.request("ping")["result"] == {}


def test_unknown_tool_and_bad_arguments(server):
    payload, is_error = server.call("no_such_tool")
    assert is_error and payload["error"] == "unknown_tool"
    payload, is_error = server.call("project_open", bogus=1)
    assert is_error and payload["error"] == "input_error"
    payload, is_error = server.call("measure_audio")
    assert is_error and "path" in payload["message"]
    payload, is_error = server.call("project_open", detail="everything")
    assert is_error and payload["error"] == "input_error"


# ---------------------------------------------------------------------------
# workflow: init -> import -> analyze (async) -> edit -> history
# ---------------------------------------------------------------------------

def test_workflow_with_job_and_agent_actor(server, workspace):
    r = server.ok("project_init", project="song", title="Song", genre="jpop")
    assert r["created"] is True and r["project"] == "song"

    r = server.ok("import_files", project="song", sources=["export"])
    assert r["assets"] == 3 and r["imported"][0]["assets_added"] == ["ast_drums", "ast_bass", "ast_vocals"]
    assert (workspace / "song" / "assets" / "1 Drums.wav").is_file()

    # analyze as a background job
    job = server.ok("analyze_run", project="song", **{"async": True})
    assert job["job_id"].startswith("job_")
    deadline = time.monotonic() + TIMEOUT_S
    while True:
        st = server.ok("job_status", job_id=job["job_id"])
        assert st["tool"] == "analyze_run" and st["project"] == "song"
        if st["state"] in ("succeeded", "failed"):
            break
        assert time.monotonic() < deadline, "analysis job did not finish"
        time.sleep(0.05)
    assert st["state"] == "succeeded"
    res = server.ok("job_result", job_id=job["job_id"])
    assert res["result"]["measured"] == 4 and res["result"]["stem_sum"] == 3
    full = server.ok("job_result", job_id=job["job_id"], detail="full")
    assert {a["asset"] for a in full["result"]["assets"]} == {"ast_drums", "ast_bass", "ast_vocals"}
    assert any(j["job_id"] == job["job_id"] for j in server.ok("job_list")["jobs"])
    payload, is_error = server.call("job_status", job_id="job_9999")
    assert is_error and payload["error"] == "unknown_job"

    # summary by default, full on request
    summary = server.ok("project_open", project="song")
    assert summary["tracks"] == 3 and summary["lead"] == "trk_vocals"
    assert summary["analysis"] == {"fresh": 3, "stem_sum:fresh": 1}
    full = server.ok("project_open", project="song", detail="full")
    assert len(json.dumps(full)) > len(json.dumps(summary))
    assert full["assets"][0]["path"] == "assets/1 Drums.wav"

    # edits are journaled with actor "agent"
    server.ok("project_set", project="song", pointer="/tracks/0/gain_db", value=-1.5, reason="balance")
    server.ok("project_set", project="song", pointer="/title", value="Song (agent)")
    assert server.ok("project_get", project="song", pointer="/title")["value"] == "Song (agent)"
    server.ok("project_patch", project="song", ops=[{"op": "replace", "path": "/tracks/1/gain_db", "value": -2.0}])
    assert server.ok("project_get", project="song", pointer="/tracks/1/gain_db")["value"] == -2.0
    undone = server.ok("history_undo", project="song")
    assert undone["undone"]["actor"] == "agent"
    assert server.ok("project_get", project="song", pointer="/tracks/1/gain_db")["value"] == 0.0
    assert server.ok("project_validate", project="song")["valid"] is True

    hist = server.ok("history_list", project="song")["entries"]
    by_op = {e["op"]: e["actor"] for e in hist}
    for op in ("import", "analyze", "set", "patch", "undo"):
        assert by_op[op] == "agent", (op, hist)
    journal = [json.loads(x) for x in
               (workspace / "song" / "journal.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    assert {e["actor"] for e in journal if e["op"] != "create"} == {"agent"}

    # measurement tools take workspace-relative paths
    m = server.ok("measure_audio", path="export/1 Drums.wav")
    assert m["file"] == "1 Drums.wav" and "integrated_lufs" in m["loudness"]
    assert "vector" not in m                              # summary, not the full vector
    c = server.ok("compare_audio", path_a="export/1 Drums.wav", path_b="song/assets/2 Bass.wav")
    assert c["largest_deltas"] and "match_gain_db" in c


def test_project_busy_while_job_runs(server):
    server.ok("project_init", project="p", title="P")
    server.ok("import_files", project="p", sources=["export"])
    first = server.ok("analyze_run", project="p", force=True, **{"async": True})
    second, is_error = server.call("analyze_run", project="p", force=True, **{"async": True})
    st = server.ok("job_status", job_id=first["job_id"])
    if st["state"] == "running":       # normally still running; tolerate a very fast machine
        assert is_error and second["error"] == "project_busy"
    while server.ok("job_status", job_id=first["job_id"])["state"] not in ("succeeded", "failed"):
        time.sleep(0.05)
    if not is_error:
        while server.ok("job_status", job_id=second["job_id"])["state"] not in ("succeeded", "failed"):
            time.sleep(0.05)


def test_knowledge_and_catalogue_tools(server):
    r = server.ok("knowledge_lookup", query="muddy")
    assert any(e["id"] == "komori" and e["kind"] == "term" for e in r["entries"])
    assert "data" not in r["entries"][0]
    r = server.ok("knowledge_lookup", id="komori")
    assert r["count"] == 1 and r["entries"][0]["data"]["en"] == ["muddy"]
    r = server.ok("knowledge_lookup", query="jpop", kind="genre")
    assert [e["id"] for e in r["entries"]] == ["jpop"]
    assert server.ok("knowledge_lookup", query="limiter")["count"] >= 1
    payload, is_error = server.call("knowledge_lookup", source="nope")
    assert is_error
    assert server.ok("objective_list")["objectives"]
    assert server.ok("objective_get", id="comfort")["objective"]["id"] == "comfort"
    assert server.ok("profile_get", id="spotify")["profile"]["id"] == "spotify"
    d = server.ok("doctor")
    assert d["status"] in ("ok", "warning", "error") and "packages" not in d


def test_m3_objective_plan_and_rules(server, workspace):
    from tests.test_mastering import make_project, synth_mix

    make_project(workspace / "m3", synth_mix(dur=3.0))
    r = server.ok("objective_set", project="m3", spec="comfort:0.6+bass_heavy:0.4")
    assert r["set"] == "project" and [b["id"] for b in r["objective"]["blend"]] == ["comfort", "bass_heavy"]
    payload, is_error = server.call("objective_validate", path_or_json={"blend": [{"id": "comfort", "weight": 1},
                                                                                  {"id": "nope", "weight": 1}]})
    assert is_error and payload["error"] == "validation_error"

    prop = server.ok("plan_propose", project="m3", profile="spotify", max_iter=1)
    assert prop["proposal_id"].startswith("mpl_") and prop["proposal_path"].startswith("cache/proposals/")
    assert prop["breakdown"] and prop["gate"]["status"] in ("pass", "fail", "incomplete")
    assert "proposal" not in prop                                     # summary by default
    applied = server.ok("plan_apply", project="m3", proposal=prop["proposal_id"])
    assert applied["applied"] is True and applied["evaluation_stored"] is True
    payload, is_error = server.call("plan_reject", project="m3", proposal_id=prop["proposal_id"], reason="too dark")
    assert is_error and "already applied" in payload["message"]
    ev = server.ok("project_get", project="m3", pointer="/variants/0/evaluation/score")
    assert ev["value"] == applied["score"]

    rule = server.ok("knowledge_lookup", id="R-14")
    assert rule["count"] == 1 and rule["entries"][0]["kind"] == "rule" and "S-01" in rule["entries"][0]["data"]["related"]


# ---------------------------------------------------------------------------
# workspace restriction
# ---------------------------------------------------------------------------

def _make_dir_link(link: Path, target: Path) -> bool:
    try:
        os.symlink(target, link, target_is_directory=True)
        return True
    except (OSError, NotImplementedError):
        pass
    if os.name == "nt":
        try:
            import _winapi
            _winapi.CreateJunction(str(target), str(link))
            return True
        except (ImportError, OSError):
            return False
    return False


def test_path_escape_rejected(server, workspace, tmp_path):
    outside = tmp_path / "outside"
    write_stem_folder(outside)
    linked = _make_dir_link(workspace / "escape", outside)
    server.ok("project_init", project="p", title="P")

    attempts = [
        ("measure_audio", {"path": "../outside/1 Drums.wav"}),
        ("measure_audio", {"path": str(outside / "1 Drums.wav")}),
        ("measure_audio", {"path": "export/../../outside/1 Drums.wav"}),
        ("compare_audio", {"path_a": "export/1 Drums.wav", "path_b": "../outside/2 Bass.wav"}),
        ("import_files", {"project": "p", "sources": ["../outside"]}),
        ("import_files", {"project": "p", "sources": ["export", str(outside)]}),
        ("project_open", {"project": ".."}),
        ("project_init", {"project": "../evil", "title": "x"}),
    ]
    if os.name == "nt":
        attempts.append(("measure_audio", {"path": "C:outside.wav"}))
    if linked:
        attempts.append(("measure_audio", {"path": "escape/1 Drums.wav"}))
        attempts.append(("import_files", {"project": "p", "sources": ["escape"]}))
    for name, args in attempts:
        payload, is_error = server.call(name, **args)
        assert is_error, (name, args, payload)
        assert payload["error"] == "path_outside_workspace", (name, args, payload)
    assert not (tmp_path / "evil").exists()
    assert server.ok("project_open", project="p")["tracks"] == 0       # nothing was imported


# ---------------------------------------------------------------------------
# in-process: job manager and the declarative tool table
# ---------------------------------------------------------------------------

def test_job_manager_one_job_per_project():
    from mankomix.mcp.jobs import JobManager, ProjectBusy

    jm = JobManager()
    gate = threading.Event()
    a = jm.submit("analyze_run", "p1", {}, lambda: gate.wait(10) and {"ok": True})
    with pytest.raises(ProjectBusy):
        jm.submit("analyze_run", "p1", {}, lambda: {})
    with pytest.raises(ProjectBusy):
        jm.check_free("p1")
    other = jm.submit("analyze_run", "p2", {}, lambda: {"ok": 2})      # other projects are independent
    gate.set()
    assert jm.wait(a.id, 10).state == "succeeded" and a.result == {"ok": True}
    assert jm.wait(other.id, 10).result == {"ok": 2}
    jm.check_free("p1")

    def boom():
        raise InputError("bad input")
    failed = jm.wait(jm.submit("x", "p1", {}, boom).id, 10)
    assert failed.state == "failed" and failed.error["error"] == "input_error"


def test_future_api_function_becomes_a_tool(monkeypatch, tmp_path):
    """A later API function shows up as a tool by its declarative entry alone (hasattr guard)."""
    from mankomix.mcp.tools import Toolbox
    from mankomix.mcp.workspace import Workspace

    ws = Workspace(tmp_path)
    assert "plan_propose" not in Toolbox(ws).tools or hasattr(api, "plan_propose")

    seen = {}

    def plan_propose(project_path: str, stage: str, *, objective: str | None = None,
                     actor: str = "human") -> dict:
        seen.update(project_path=project_path, stage=stage, objective=objective, actor=actor)
        items = [{"i": i, "reason": "lower the low mids a little"} for i in range(50)]
        return {"plan": {"stage": stage, "items": items}, "path": str(Path(project_path) / "x.json")}

    monkeypatch.setattr(api, "plan_propose", plan_propose, raising=False)
    tb = Toolbox(ws)
    tool = tb.tools["plan_propose"]
    props = tool.input_schema["properties"]
    assert set(props) - {"async"} == {"project", "stage", "objective", "detail"}   # plan_propose is a long tool
    assert tool.input_schema["required"] == ["stage"] and tool.mutates
    (tmp_path / "proj").mkdir()
    payload, is_error = tb.call("plan_propose", {"project": "proj", "stage": "master"})
    assert not is_error, payload
    assert seen["actor"] == "agent" and seen["stage"] == "master"
    assert Path(seen["project_path"]) == (tmp_path / "proj").resolve()
    assert payload["path"] == "proj/x.json"                           # no absolute path in results
    assert len(payload["plan"]["items"]) < 50                          # summarised by default
    full, _ = tb.call("plan_propose", {"project": "proj", "stage": "master", "detail": "full"})
    assert len(full["plan"]["items"]) == 50
    payload, is_error = tb.call("plan_propose", {"project": "../x", "stage": "master"})
    assert is_error and payload["error"] == "path_outside_workspace"
