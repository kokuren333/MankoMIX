"""Local GUI server tests (`mankomix serve`, SPEC 3.3, 9.5, 11; gui/API.md).

The server runs in-process on an ephemeral loopback port in a background thread,
with a temporary workspace. Requests go through a real HTTP client (urllib /
http.client, proxies disabled).
"""

from __future__ import annotations

import http.client
import json
import queue
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import pytest

from mankomix.cli import main as cli_main
from mankomix.core import api, config
from mankomix.core.errors import EXIT_INPUT_ERROR, InputError
from mankomix.core.server import MankoServer, is_loopback, parse_range

from tests.test_mcp import write_stem_folder

REPO = Path(__file__).resolve().parent.parent
TIMEOUT_S = 120


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

class Client:
    def __init__(self, base: str, tmp_path: Path):
        self.base = base
        self.tmp_path = tmp_path
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def raw(self, method: str, path: str, body: bytes | None = None, headers: dict | None = None):
        req = urllib.request.Request(self.base + path, data=body, method=method, headers=headers or {})
        try:
            with self.opener.open(req, timeout=TIMEOUT_S) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    def call(self, method: str, path: str, obj=None, expect: int | None = 200):
        body = None if obj is None else json.dumps(obj).encode("utf-8")
        headers = {"Content-Type": "application/json"} if body is not None else {}
        status, hdrs, data = self.raw(method, path, body, headers)
        text = data.decode("utf-8")
        assert_no_abs(text, self.tmp_path)
        out = json.loads(text) if text else None
        if expect is not None:
            assert status == expect, (status, out)
        return out

    def get(self, path: str, **kw):
        return self.call("GET", path, **kw)

    def post(self, path: str, obj=None, **kw):
        return self.call("POST", path, {} if obj is None else obj, **kw)

    def wait_job(self, job: dict, timeout: float = TIMEOUT_S) -> dict:
        deadline = time.monotonic() + timeout
        while True:
            j = self.get(f"/api/jobs/{job['job_id']}")
            if j["state"] in ("done", "failed"):
                return j
            assert time.monotonic() < deadline, j
            time.sleep(0.05)


def assert_no_abs(text: str, tmp_path: Path) -> None:
    low = text.lower()
    for p in (tmp_path, Path.home(), REPO):
        s = str(p.resolve())
        for f in (s, s.replace("\\", "/"), s.replace("\\", "\\\\")):
            assert f.lower() not in low, "absolute path leaked into a response"


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("MANKOMIX_HOME", str(tmp_path / "home"))
    config.clear_cache()
    yield tmp_path / "home"
    config.clear_cache()


@pytest.fixture
def workspace(tmp_path, home) -> Path:
    root = tmp_path / "ws"
    write_stem_folder(root / "export")
    api.init_project(str(root / "song"), title="Song", genre="jpop")
    api.import_files(str(root / "song"), [str(root / "export")])
    return root


def _start(root: Path, **kw) -> MankoServer:
    kw.setdefault("port", 0)
    kw.setdefault("poll_s", 0.1)
    kw.setdefault("ping_s", 0.5)
    return MankoServer(root, **kw).start()


@pytest.fixture
def server(workspace, tmp_path):
    srv = _start(workspace, project="song")
    try:
        yield srv, Client(srv.url, tmp_path)
    finally:
        srv.close()


def _journal(project: Path) -> list[dict]:
    return [json.loads(x) for x in (project / "journal.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------

def test_capabilities_and_static(server):
    srv, c = server
    cap = c.get("/api/capabilities")
    assert cap["mode"] == "local" and cap["project"] == "song"
    for k in ("editProject", "importAudio", "runAnalysis", "runPlanner", "applyPlan", "render", "runVerify",
              "undo", "agentLink", "liveUpdates", "modelDownload"):
        assert cap[k] is True
    status, headers, body = c.raw("GET", "/")
    assert status == 200 and headers["Content-Type"].startswith("text/html")
    status, _, body = c.raw("GET", "/api/no/such/thing")
    assert status == 404 and json.loads(body)["error"] == "not_found"
    status, _, body = c.raw("DELETE", "/api/project")
    assert status == 405


def test_project_patch_history_undo(server, workspace):
    srv, c = server
    proj = c.get("/api/project")
    assert proj["title"] == "Song" and proj["tracks"]
    res = c.call("PATCH", "/api/project", {"ops": [{"op": "replace", "path": "/title", "value": "From GUI"}],
                                           "reason": "rename in GUI"})
    assert res["applied"] == 1 and res["content_hash"]
    assert c.get("/api/project")["title"] == "From GUI"
    last = _journal(workspace / "song")[-1]
    assert last["actor"] == "human" and last["op"] == "patch" and last["reason"] == "rename in GUI"

    hist = c.get("/api/history?limit=3")["entries"]
    assert len(hist) == 3 and hist[0]["op"] == "patch" and hist[0]["actor"] == "human"   # newest first
    assert hist[0]["seq"] > hist[1]["seq"] > hist[2]["seq"]

    # invalid change: same error object as the CLI, HTTP 400
    err = c.call("PATCH", "/api/project", {"ops": [{"op": "replace", "path": "/tracks/0/gain_db", "value": "x"}]},
                 expect=400)
    assert set(err) == {"error", "message", "details"} and err["error"] == "validation_error"
    assert c.call("PATCH", "/api/project", {"ops": "nope"}, expect=400)["error"] == "input_error"

    undone = c.post("/api/history/undo")
    assert undone["undone"]["op"] == "undo" and undone["undone"]["undoes"] == hist[0]["seq"]
    assert undone["content_hash"]
    assert c.get("/api/project")["title"] == "Song"
    assert _journal(workspace / "song")[-1]["actor"] == "human"


def test_definitions(server):
    srv, c = server
    obj = c.get("/api/objectives")
    assert obj["default"] and any(o["id"] == "comfort" and o.get("terms") for o in obj["objectives"])
    prof = c.get("/api/profiles")["profiles"]
    assert any(p["id"] == "spotify" and p["loudness"]["target_lufs_i"] is not None for p in prof)
    deliveries = c.get("/api/deliveries")["formats"]
    assert any(d["id"] == "archive_f32" and "bit_depth" in d for d in deliveries)
    models = c.get("/api/models")
    assert models["models"] and all("installed" in m and "license" in m for m in models["models"])
    assert all(m["installed"] is False for m in models["models"] if m["tier"] == "official")   # empty home
    assert c.get(f"/api/models/{models['models'][0]['id']}")["id"] == models["models"][0]["id"]


def test_model_pull_unknown_fails_as_job(server):
    srv, c = server
    job = c.post("/api/models/no_such_model/pull")
    assert job["kind"] == "model_pull"
    done = c.wait_job(job)
    assert done["state"] == "failed" and "unknown model" in done["error"]


def test_analyze_job_and_views(server, workspace):
    srv, c = server
    job = c.post("/api/analyze")
    assert job["kind"] == "analyze" and job["state"] in ("queued", "running", "done")
    done = c.wait_job(job)
    assert done["state"] == "done", done
    assert done["progress"] == 1.0 and done["result"]["measured"] >= 1
    assert _journal(workspace / "song")[-1]["op"] == "analyze"
    assert _journal(workspace / "song")[-1]["actor"] == "human"
    assert any(j["job_id"] == job["job_id"] for j in c.get("/api/jobs")["jobs"])
    assert c.get("/api/jobs/job_9999", expect=404)["error"] == "unknown_job"

    an = c.get("/api/analysis")
    assert an["schema_version"] == 1 and an["before_kind"] == "stem_sum"
    assert an["loudness"]["hop_s"] == 1.0 and an["loudness"]["after"] is None
    assert an["ltas"]["freqs_hz"] and len(an["ltas"]["before"]) == len(an["ltas"]["freqs_hz"])
    assert {s["track"] for s in an["stems"]} and all("centroid_hz" in s for s in an["stems"])
    assert an["band_correlation"]["bands"] and an["metrics"]
    assert c.get("/api/variants") == []
    assert c.get("/api/proposals") == {"proposals": [], "count": 0}
    # a view needs a variant: same input error as CLI/MCP
    assert c.get("/api/audio", expect=400)["error"] == "input_error"


def test_files_with_range(server, workspace):
    srv, c = server
    rel = api.status(str(workspace / "song"))["assets"][0]["path"]
    data = (workspace / "song" / rel).read_bytes()
    url = "/api/files/" + urllib.request.quote(rel)
    status, headers, body = c.raw("GET", url)
    assert status == 200 and body == data
    assert headers["Content-Type"] == "audio/wav" and headers["Accept-Ranges"] == "bytes"
    status, headers, body = c.raw("GET", url, headers={"Range": "bytes=0-99"})
    assert status == 206 and body == data[:100] and headers["Content-Range"] == f"bytes 0-99/{len(data)}"
    status, headers, body = c.raw("GET", url, headers={"Range": "bytes=-10"})
    assert status == 206 and body == data[-10:]
    status, headers, body = c.raw("GET", url, headers={"Range": f"bytes={len(data) - 5}-"})
    assert status == 206 and body == data[-5:]
    status, headers, _ = c.raw("GET", url, headers={"Range": f"bytes={len(data) + 10}-"})
    assert status == 416 and headers["Content-Range"] == f"bytes */{len(data)}"
    status, headers, body = c.raw("HEAD", url)
    assert status == 200 and body == b"" and int(headers["Content-Length"]) == len(data)
    status, _, body = c.raw("GET", "/api/files/project.json")
    assert status == 200 and json.loads(body)["title"] == "Song"
    assert c.get("/api/files/nope.wav", expect=404)["error"] == "not_found"


def test_path_escape_rejected(server, workspace, tmp_path):
    srv, c = server
    (tmp_path / "outside.txt").write_text("secret", encoding="utf-8")
    for path in ("/api/files/%2e%2e/export/1%20Drums.wav",                 # inside the workspace, not the project
                 "/api/files/%2e%2e/%2e%2e/outside.txt",                       # outside the workspace
                 "/api/files/" + urllib.request.quote(str(tmp_path / "outside.txt"))):   # absolute
        status, _, body = c.raw("GET", path)
        assert status == 403, path
        err = json.loads(body)
        assert err["error"] in ("forbidden", "path_outside_workspace")
        assert b"secret" not in body
        assert_no_abs(body.decode("utf-8"), tmp_path)
    with pytest.raises(InputError) as ei:
        MankoServer(workspace, project="../elsewhere", port=0)
    assert ei.value.code == "path_outside_workspace"
    # DNS rebinding: a non-loopback Host header is refused
    status, _, body = c.raw("GET", "/api/capabilities", headers={"Host": "evil.example:80"})
    assert status == 403
    # cross-origin writes are refused
    status, _, _ = c.raw("POST", "/api/history/undo", b"{}", {"Content-Type": "application/json",
                                                               "Origin": "http://evil.example"})
    assert status == 403


def _sse_reader(srv: MankoServer, events: queue.Queue, ready: threading.Event, stop: threading.Event):
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=30)
    conn.request("GET", "/api/events", headers={"Accept": "text/event-stream"})
    resp = conn.getresponse()
    assert resp.status == 200 and resp.getheader("Content-Type").startswith("text/event-stream")
    ready.set()
    name, data = None, []
    try:
        while not stop.is_set():
            line = resp.fp.readline()
            if not line:
                break
            line = line.decode("utf-8").rstrip("\r\n")
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].strip())
            elif line == "" and name:
                events.put((name, json.loads("\n".join(data))))
                name, data = None, []
    finally:
        conn.close()


def test_sse_project_changed_after_external_change(server, workspace):
    srv, c = server
    events: queue.Queue = queue.Queue()
    ready, stop = threading.Event(), threading.Event()
    t = threading.Thread(target=_sse_reader, args=(srv, events, ready, stop), daemon=True)
    t.start()
    assert ready.wait(10)
    time.sleep(0.3)
    # an external face (CLI / MCP agent) changes the project in the same folder
    api.set_value(str(workspace / "song"), "/title", json.dumps("Changed by agent"), actor="agent",
                  reason="agent rename")
    deadline = time.monotonic() + 15
    got = None
    while time.monotonic() < deadline:
        try:
            name, data = events.get(timeout=0.5)
        except queue.Empty:
            continue
        if name == "project_changed":
            got = data
            break
    stop.set()
    assert got is not None, "no project_changed event"
    assert got["actor"] == "agent" and got["summary"] == "agent rename" and got["seq"] and got["content_hash"]
    assert c.get("/api/project")["title"] == "Changed by agent"


def test_sse_job_events(server):
    srv, c = server
    events: queue.Queue = queue.Queue()
    ready, stop = threading.Event(), threading.Event()
    threading.Thread(target=_sse_reader, args=(srv, events, ready, stop), daemon=True).start()
    assert ready.wait(10)
    job = c.post("/api/analyze")
    c.wait_job(job)
    deadline = time.monotonic() + 15
    states = []
    while time.monotonic() < deadline and "done" not in states:
        try:
            name, data = events.get(timeout=0.5)
        except queue.Empty:
            continue
        if name == "job" and data["job"]["job_id"] == job["job_id"]:
            states.append(data["job"]["state"])
    stop.set()
    assert "done" in states


def test_import_multipart(workspace, tmp_path):
    api.init_project(str(workspace / "fresh"), title="Fresh")
    srv = _start(workspace, project="fresh")
    try:
        c = Client(srv.url, tmp_path)
        wav = (workspace / "export" / "1 Drums.wav").read_bytes()
        boundary = uuid.uuid4().hex
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; filename=\"../Kick Loop.wav\"\r\n"
                f"Content-Type: audio/wav\r\n\r\n").encode("utf-8") + wav + f"\r\n--{boundary}--\r\n".encode("utf-8")
        status, _, data = c.raw("POST", "/api/import", body,
                                {"Content-Type": f"multipart/form-data; boundary={boundary}"})
        res = json.loads(data)
        assert status == 200, res
        assert res["applied"] == 1 and res["content_hash"]
        proj = c.get("/api/project")
        assert [a["original_name"] for a in proj["assets"]] == ["Kick Loop.wav"]
        last = _journal(workspace / "fresh")[-1]
        assert last["actor"] == "human" and last["op"] == "import"
        status, _, data = c.raw("POST", "/api/import", b"{}", {"Content-Type": "application/json"})
        assert status == 400
    finally:
        srv.close()


def test_no_project(workspace, tmp_path):
    srv = _start(workspace)          # the workspace root itself is not a project
    try:
        c = Client(srv.url, tmp_path)
        cap = c.get("/api/capabilities")
        assert cap["project"] is None and cap["editProject"] is False
        assert c.get("/api/project", expect=404)["error"] == "not_found"
        assert c.get("/api/objectives")["objectives"]           # definitions work without a project
    finally:
        srv.close()


def test_non_loopback_bind_refused(workspace, capsys):
    with pytest.raises(InputError) as ei:
        MankoServer(workspace, host="0.0.0.0", port=0)
    assert ei.value.code == "remote_bind_refused"
    with pytest.raises(InputError):
        MankoServer(workspace, host="192.168.1.20", port=0)
    code = cli_main.main(["serve", "--root", str(workspace), "--host", "0.0.0.0", "--port", "0"])
    out = json.loads(capsys.readouterr().out)
    assert code == EXIT_INPUT_ERROR and out["error"] == "remote_bind_refused"
    assert is_loopback("127.0.0.1") and is_loopback("localhost") and is_loopback("::1") and is_loopback("[::1]")
    assert not is_loopback("0.0.0.0") and not is_loopback("example.org")


def test_parse_range():
    assert parse_range("bytes=0-0", 10) == (0, 0)
    assert parse_range("bytes=5-", 10) == (5, 9)
    assert parse_range("bytes=-3", 10) == (7, 9)
    assert parse_range("bytes=-30", 10) == (0, 9)
    assert parse_range("bytes=8-100", 10) == (8, 9)
    assert parse_range("bytes=10-", 10) == "unsatisfiable"
    assert parse_range("bytes=0-1,4-5", 10) is None      # multiple ranges: whole file
    assert parse_range("items=0-1", 10) is None


def test_plan_propose_reject_and_proposal_events(workspace, tmp_path):
    from tests.test_mastering import make_project, synth_mix

    make_project(workspace / "m3", synth_mix(dur=3.0))
    srv = _start(workspace, project="m3")
    try:
        c = Client(srv.url, tmp_path)
        prop = c.post("/api/plan/propose", {"stage": "master", "profile": "spotify", "max_iter": 1})
        assert prop["stage"] == "master" and prop["status"] == "pending" and prop["author"] == "planner"
        assert prop["steps"] and all(s["target"] == "master" and s["processor"]["id"] for s in prop["steps"])
        listed = c.get(f"/api/proposals?variant={prop['variant']}")["proposals"]
        assert [p["id"] for p in listed] == [prop["id"]]
        c.post("/api/plan/reject", {"proposal_id": prop["id"], "reason": "too bright"})
        assert c.get("/api/proposals")["proposals"][0]["status"] == "rejected"
        assert _journal(workspace / "m3")[-1]["op"] == "plan_reject"
        assert _journal(workspace / "m3")[-1]["actor"] == "human"
        err = c.post("/api/plan/apply", {"proposal_id": prop["id"], "edits": {}}, expect=400)
        assert "rejected" in err["message"]

        # an agent proposal (MCP actor) shows up as author "agent"
        api.plan_propose(str(workspace / "m3"), "master", profile="spotify", max_iter=0, actor="agent")
        agent = [p for p in c.get("/api/proposals?status=pending")["proposals"]]
        assert agent and agent[0]["author"] == "agent"
        first = agent[0]["steps"][0]["processor"]
        param = next(k for k, v in first["params"].items() if isinstance(v, (int, float)) and not isinstance(v, bool))
        bad = c.post("/api/plan/apply", {"proposal_id": agent[0]["id"], "edits": {"nope": {"x": 1}}}, expect=400)
        assert "no processor" in bad["message"]
        res = c.post("/api/plan/apply", {"proposal_id": agent[0]["id"],
                                         "edits": {first["id"]: {param: first["params"][param]}}})
        assert res["applied"] is True and res["content_hash"]
        assert _journal(workspace / "m3")[-1]["actor"] == "human"
        variants = c.get("/api/variants")
        vid = agent[0]["variant"]
        assert variants[0]["id"] == vid and variants[0]["has_master_chain"] and not variants[0]["rendered"]

        # render -> listening set -> verify -> report
        done = c.wait_job(c.post("/api/render", {"variant": vid, "range": None}))
        assert done["state"] == "done", done
        assert c.get("/api/variants")[0]["rendered"] is True
        audio = c.get(f"/api/audio?variant={vid}")
        assert audio["files"]["before"].startswith("/api/files/assets/")          # full-mix route
        assert audio["files"]["after"].startswith("/api/files/renders/")
        assert audio["match_gain_db"] <= 0 and audio["match_target"] in ("before", "after")
        status, headers, body = c.raw("GET", audio["files"]["after"], headers={"Range": "bytes=0-15"})
        assert status == 206 and body[:4] == b"RIFF"
        assert c.get(f"/api/verify?variant={vid}", expect=404)["error"] == "not_generated"
        vjob = c.wait_job(c.post("/api/verify", {"variant": vid}))
        assert vjob["state"] == "done", vjob
        ver = c.get(f"/api/verify?variant={vid}")
        assert ver["overall"] in ("pass", "fail", "warning", "not_run") and ver["profiles"] and ver["constraints"]
        assert ver == {**vjob["result"], "stale": ver["stale"]}
        rep = c.get(f"/api/report?variant={vid}&lang=en")
        assert rep["summary"]
        assert c.get(f"/api/analysis?variant={vid}", expect=404)["error"] == "not_generated"
        assert c.wait_job(c.post("/api/analyze"))["state"] == "done"
        an = c.get(f"/api/analysis?variant={vid}")
        assert an["before_kind"] == "fullmix" and an["loudness"]["after"] and an["ltas"]["after"]
    finally:
        srv.close()
