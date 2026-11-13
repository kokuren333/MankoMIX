"""`mankomix serve`: local HTTP server for the GUI (SPEC 3.3, 9.5, 11; gui/API.md).

Python standard library only (``http.server.ThreadingHTTPServer``). Every endpoint
calls ``mankomix.core.api`` functions; the server adds no processing logic of its
own (A-1). Face-level adaptation is limited to:

- the workspace restriction shared with the MCP server (``mcp/workspace.py``): the
  served project and every file request stay inside ``--root``;
- writes from the GUI are journaled with actor ``"human"``;
- long operations run as background jobs (``mcp/jobs.py``) and report through
  ``GET /api/jobs/{id}`` and ``job`` events;
- project-relative paths in results become ``/api/files/...`` URLs;
- errors use the CLI/MCP error object (``MankoError.to_dict()``) with an HTTP status.

The server binds to 127.0.0.1 by default and refuses a non-loopback address unless
``allow_remote`` is set. Requests whose Host header is not the bound loopback name
are rejected (DNS rebinding protection).
"""

from __future__ import annotations

import email.parser
import email.policy
import ipaddress
import json
import logging
import mimetypes
import os
import queue
import re
import shutil
import socket
import sys
import tempfile
import threading
import time
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, quote, unquote, urlsplit

import mankomix
from mankomix.core import api
from mankomix.core.errors import EnvironmentProblem, InputError, MankoError
from mankomix.mcp.jobs import FAILED, QUEUED, RUNNING, SUCCEEDED, Job, JobManager
from mankomix.mcp.workspace import Workspace

from .events import EventBus, ProjectWatcher

log = logging.getLogger("mankomix.server")

ACTOR = "human"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024
CHUNK = 64 * 1024
PING_S = 15.0
POLL_S = 1.0

AUDIO_TYPES = {".wav": "audio/wav", ".flac": "audio/flac", ".aif": "audio/aiff", ".aiff": "audio/aiff",
               ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".aac": "audio/aac", ".ogg": "audio/ogg",
               ".opus": "audio/ogg", ".json": "application/json", ".md": "text/markdown; charset=utf-8",
               ".txt": "text/plain; charset=utf-8", ".png": "image/png", ".svg": "image/svg+xml",
               ".js": "text/javascript; charset=utf-8", ".mjs": "text/javascript; charset=utf-8",
               ".css": "text/css; charset=utf-8", ".html": "text/html; charset=utf-8",
               ".webmanifest": "application/manifest+json", ".ico": "image/x-icon", ".woff2": "font/woff2"}

JOB_KINDS = {"analyze": "analyze", "render": "render", "export": "export", "verify": "verify",
             "separate": "separate", "plan_propose": "plan", "model_pull": "model_pull", "import": "import"}
JOB_STATES = {QUEUED: "queued", RUNNING: "running", SUCCEEDED: "done", FAILED: "failed"}


class NoProject(InputError):
    code = "not_found"


class RemoteBindRefused(InputError):
    code = "remote_bind_refused"


class NotFound(InputError):
    code = "not_found"


class Forbidden(InputError):
    code = "forbidden"


def is_loopback(host: str) -> bool:
    h = (host or "").strip().strip("[]")
    if h.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False


def http_status(e: BaseException) -> int:
    code = getattr(e, "code", None)
    if code in ("not_found", "not_generated", "unknown_job"):
        return 404
    if code in ("path_outside_workspace", "forbidden"):
        return 403
    if code in ("project_busy", "conflict"):
        return 409
    if code == "not_implemented":
        return 501
    if code == "payload_too_large":
        return 413
    if isinstance(e, EnvironmentProblem) or code == "environment_error":
        return 503
    if isinstance(e, MankoError):
        return 400
    return 500


class PayloadTooLarge(InputError):
    code = "payload_too_large"


# ---------------------------------------------------------------------------
# jobs: mcp/jobs.py with job events
# ---------------------------------------------------------------------------

class ServerJobs(JobManager):
    def __init__(self, bus: EventBus, view: Callable[[Job], dict], **kw):
        super().__init__(**kw)
        self._bus = bus
        self._view = view

    def _run(self, job: Job, fn: Callable[[], Any]) -> None:
        def wrapped():
            self._bus.publish("job", {"job": self._view(job)})      # state is "running" here
            return fn()
        super()._run(job, wrapped)
        self._bus.publish("job", {"job": self._view(job)})


# ---------------------------------------------------------------------------
# the application (state shared by all request threads)
# ---------------------------------------------------------------------------

class App:
    def __init__(self, root: str | os.PathLike[str], *, project: str | None = None, static: str | None = None,
                 host: str = DEFAULT_HOST, allow_remote: bool = False, poll_s: float = POLL_S,
                 ping_s: float = PING_S):
        self.ws = Workspace(root)
        self.host = host
        self.allow_remote = allow_remote
        self.ping_s = ping_s
        self.bus = EventBus()
        self.jobs = ServerJobs(self.bus, self.job_view, error_mapper=self._error_payload)
        self.stopping = threading.Event()
        if project:
            p = self.ws.resolve(project, what="project")
        else:
            p = self.ws.root
        self.project: Path | None = p if (p / "project.json").is_file() else None
        if project and self.project is None:
            raise InputError(f"not a MankoMIX project (no project.json): {self.ws.rel(p)}")
        self.static = self._static_dir(static)
        self.watcher = ProjectWatcher(self.project, self.bus, interval_s=poll_s) if self.project else None

    # -- helpers ---------------------------------------------------------------

    @staticmethod
    def _static_dir(static: str | None) -> Path | None:
        if static:
            p = Path(static)
            if not p.is_dir():
                raise InputError(f"static folder not found: {p.name or static}")
            return p.resolve()
        cand = Path(mankomix.repo_data_root()) / "gui" / "dist"
        return cand.resolve() if (cand / "index.html").is_file() else None

    def proj(self) -> str:
        if self.project is None:
            raise NoProject("no project is open: start the server with --project PATH (a folder with project.json)",
                            details={"hint": "mankomix serve --root <workspace> --project <project folder>"})
        return str(self.project)

    @property
    def key(self) -> str:
        return self.ws.rel(self.project) if self.project else "-"

    def scrub(self, obj: Any) -> Any:
        return self.ws.scrub(obj)

    def _error_payload(self, e: BaseException) -> dict:
        if isinstance(e, MankoError):
            return self.scrub(e.to_dict())
        log.error("internal error. %s", traceback.format_exc())
        return self.scrub({"error": "internal_error", "message": f"{type(e).__name__}: {e}", "details": {}})

    def job_view(self, job: Job) -> dict:
        out: dict[str, Any] = {"job_id": job.id, "kind": JOB_KINDS.get(job.tool, job.tool),
                               "state": JOB_STATES.get(job.state, job.state)}
        if job.state == SUCCEEDED:
            out["progress"] = 1.0
            out["result"] = self.scrub(job.result)
        elif job.state == FAILED:
            err = job.error or {}
            out["error"] = err.get("message") or err.get("error")
            out["error_detail"] = err
        if job.started is not None:
            out["elapsed_s"] = round((job.finished or time.monotonic()) - job.started, 3)
        return out

    def submit(self, tool: str, fn: Callable[[], Any], *, key: str | None = None, args: dict | None = None) -> dict:
        # job events are published by ServerJobs when the job starts and when it ends
        return self.job_view(self.jobs.submit(tool, key or self.key, args or {}, fn))

    def check_free(self) -> None:
        if self.project is not None:
            self.jobs.check_free(self.key)

    def file_url(self, rel: str | None) -> str | None:
        if not rel:
            return None
        return "/api/files/" + quote(rel.replace("\\", "/"), safe="/")

    def capabilities(self) -> dict:
        has = self.project is not None
        return {"mode": "local", "editProject": has, "importAudio": has, "runAnalysis": has, "runPlanner": has,
                "applyPlan": has, "render": has, "runVerify": has, "undo": has, "agentLink": has,
                "liveUpdates": True, "modelDownload": True,
                "project": self.ws.rel(self.project) if has else None,
                "engine_version": mankomix.ENGINE_VERSION, "actor": ACTOR}

    def start_background(self) -> None:
        if self.watcher is not None and not self.watcher.is_alive():
            self.watcher.start()

    def stop(self) -> None:
        self.stopping.set()
        if self.watcher is not None:
            self.watcher.stop()


# ---------------------------------------------------------------------------
# request handling
# ---------------------------------------------------------------------------

Route = tuple[str, re.Pattern, str]


def _routes() -> list[Route]:
    table = [
        ("GET", r"/api/capabilities", "capabilities"),
        ("GET", r"/api/status", "status"),
        ("GET", r"/api/project", "project_get"),
        ("PATCH", r"/api/project", "project_patch"),
        ("POST", r"/api/import", "import_files"),
        ("GET", r"/api/history", "history"),
        ("POST", r"/api/history/undo", "undo"),
        ("GET", r"/api/objectives", "objectives"),
        ("GET", r"/api/profiles", "profiles"),
        ("GET", r"/api/deliveries", "deliveries"),
        ("GET", r"/api/models", "models"),
        ("GET", r"/api/models/(?P<id>[^/]+)", "model_show"),
        ("POST", r"/api/models/(?P<id>[^/]+)/pull", "model_pull"),
        ("GET", r"/api/variants", "variants"),
        ("GET", r"/api/analysis", "analysis"),
        ("POST", r"/api/analyze", "analyze"),
        ("GET", r"/api/proposals", "proposals"),
        ("GET", r"/api/proposals/(?P<id>[^/]+)", "proposal_get"),
        ("POST", r"/api/plan/propose", "plan_propose"),
        ("POST", r"/api/plan/apply", "plan_apply"),
        ("POST", r"/api/plan/reject", "plan_reject"),
        ("POST", r"/api/render", "render"),
        ("POST", r"/api/export", "export"),
        ("GET", r"/api/jobs", "jobs"),
        ("GET", r"/api/jobs/(?P<id>[^/]+)", "job"),
        ("GET", r"/api/verify", "verify_get"),
        ("POST", r"/api/verify", "verify_run"),
        ("GET", r"/api/report", "report"),
        ("GET", r"/api/audio", "audio"),
        ("POST", r"/api/separate", "separate"),
        ("GET", r"/api/separations", "separations"),
        ("GET", r"/api/events", "events"),
        ("GET", r"/api/files/(?P<rel>.+)", "files"),
        ("HEAD", r"/api/files/(?P<rel>.+)", "files"),
    ]
    return [(m, re.compile(p + r"/?\Z"), name) for m, p, name in table]


ROUTES = _routes()


class Handler(BaseHTTPRequestHandler):
    server_version = "mankomix"
    sys_version = ""
    app: App          # set on the subclass created per server

    # -- plumbing ----------------------------------------------------------------

    def log_message(self, fmt: str, *args: Any) -> None:   # quiet by default; no client details on stdout
        log.debug("%s %s", self.command, fmt % args)

    def do_GET(self):      # noqa: N802 - http.server naming
        self._dispatch("GET")

    def do_HEAD(self):     # noqa: N802
        self._dispatch("HEAD")

    def do_POST(self):     # noqa: N802
        self._dispatch("POST")

    def do_PATCH(self):    # noqa: N802
        self._dispatch("PATCH")

    def do_PUT(self):      # noqa: N802
        self._dispatch("PUT")

    def do_DELETE(self):   # noqa: N802
        self._dispatch("DELETE")

    def _dispatch(self, method: str) -> None:
        url = urlsplit(self.path)
        path = unquote(url.path)
        self.query = {k: v[-1] for k, v in parse_qs(url.query, keep_blank_values=True).items()}
        try:
            self._check_host()
            if not path.startswith("/api/") and path != "/api":
                if method not in ("GET", "HEAD"):
                    raise NotFound(f"no such endpoint: {method} {path}")
                return self._static(path, head=method == "HEAD")
            allowed = []
            for m, pat, name in ROUTES:
                mt = pat.match(path)
                if mt is None:
                    continue
                if m != method:
                    allowed.append(m)
                    continue
                if method in ("POST", "PATCH", "PUT", "DELETE"):
                    self._check_origin()
                result = getattr(self, "h_" + name)(**mt.groupdict())
                if result is not None:
                    self._json(200, result)
                return
            if allowed:
                self._json(405, {"error": "method_not_allowed", "message": f"{method} is not allowed on {path}",
                                 "details": {"allowed": sorted(set(allowed))}}, extra={"Allow": ", ".join(sorted(set(allowed)))})
                return
            raise NotFound(f"no such endpoint: {method} {path}")
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return
        except MankoError as e:
            self._json(http_status(e), self.app.scrub(e.to_dict()))
        except Exception as e:  # noqa: BLE001
            log.error("internal error on %s %s. %s", method, path, traceback.format_exc())
            msg = api._scrub_str(f"{type(e).__name__}: {e}", api._known_roots(self.app.ws.root))
            self._json(500, {"error": "internal_error", "message": msg, "details": {}})

    def _check_host(self) -> None:
        if self.app.allow_remote:
            return
        host = (self.headers.get("Host") or "").strip()
        name = host.rsplit(":", 1)[0] if not host.startswith("[") else host[1:].split("]", 1)[0]
        if host and not is_loopback(name):
            raise Forbidden("requests must address the server by a loopback name (127.0.0.1, localhost, [::1])")

    def _check_origin(self) -> None:
        """Writes only from the same origin (or from non-browser clients, which send no Origin)."""
        origin = self.headers.get("Origin")
        if not origin or self.app.allow_remote:
            return
        o = urlsplit(origin)
        if o.hostname is None or not is_loopback(o.hostname):
            raise Forbidden("cross-origin writes are not allowed")

    def _send(self, status: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, obj: Any, extra: dict | None = None) -> None:
        body = json.dumps(obj, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8", extra)

    def _body_bytes(self, limit: int) -> bytes:
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise InputError("invalid Content-Length") from None
        if n > limit:
            raise PayloadTooLarge(f"request body too large ({n} bytes, limit {limit})")
        return self.rfile.read(n) if n > 0 else b""

    def _body(self) -> dict:
        raw = self._body_bytes(MAX_JSON_BYTES)
        if not raw.strip():
            return {}
        try:
            obj = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as e:
            raise InputError(f"request body is not valid JSON: {e}") from None
        if not isinstance(obj, dict):
            raise InputError("request body must be a JSON object")
        return obj

    def _q(self, name: str) -> str | None:
        v = self.query.get(name)
        return v if v not in (None, "") else None

    # -- static GUI ----------------------------------------------------------------

    def _static(self, path: str, head: bool = False) -> None:
        root = self.app.static
        if root is None:
            body = ("<!doctype html><meta charset=utf-8><title>MankoMIX</title>"
                    "<p>MankoMIX local server is running. The GUI is not built: run <code>npm run build</code> "
                    "in <code>gui/</code>, or open the API at <a href=/api/capabilities>/api/capabilities</a>.</p>")
            return self._send(200, body.encode("utf-8"), "text/html; charset=utf-8")
        rel = path.lstrip("/") or "index.html"
        cand = (root / rel).resolve()
        if cand != root and not cand.is_relative_to(root):
            raise NotFound("not found")
        if not cand.is_file():
            if Path(rel).suffix:          # a missing asset
                raise NotFound(f"not found: {Path(rel).name}")
            cand = root / "index.html"    # SPA routes
        self._file(cand, head=head, cache=cand.name != "index.html")

    # -- files with Range support ------------------------------------------------------

    def _file(self, path: Path, *, head: bool = False, cache: bool = False) -> None:
        size = path.stat().st_size
        ctype = AUDIO_TYPES.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        start, end, status = 0, size - 1, 200
        rng = self.headers.get("Range")
        if rng:
            parsed = parse_range(rng, size)
            if parsed == "unsatisfiable":
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if parsed is not None:
                start, end = parsed
                status = 206
        length = max(0, end - start + 1)
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "public, max-age=3600" if cache else "no-cache")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if head or self.command == "HEAD" or length == 0:
            return
        with open(path, "rb") as fh:
            fh.seek(start)
            remaining = length
            while remaining > 0:
                block = fh.read(min(CHUNK, remaining))
                if not block:
                    break
                self.wfile.write(block)
                remaining -= len(block)

    # -- endpoints -------------------------------------------------------------------
    # Each handler calls core.api functions only; a returned dict is sent as JSON.

    def h_capabilities(self):
        return self.app.capabilities()

    def h_status(self):
        return api.status(self.app.proj())

    def h_project_get(self):
        return api.project_get(self.app.proj())["value"]

    def h_project_patch(self):
        b = self._body()
        self.app.check_free()
        res = api.patch(self.app.proj(), b.get("ops"), ACTOR, reason=b.get("reason"))
        return {"applied": res.get("applied"), "content_hash": res.get("content_hash")}

    def h_import_files(self):
        ctype = self.headers.get("Content-Type") or ""
        if not ctype.lower().startswith("multipart/form-data"):
            raise InputError("POST /api/import expects multipart/form-data with one or more 'files' fields")
        raw = self._body_bytes(MAX_UPLOAD_BYTES)
        files = parse_multipart(ctype, raw)
        if not files:
            raise InputError("no files in the upload (field name 'files')")
        self.app.check_free()
        tmp = Path(tempfile.mkdtemp(prefix="mankomix_upload_"))
        try:
            folder = tmp / "upload"
            folder.mkdir()
            for name, data in files:
                (folder / name).write_bytes(data)
            # one folder: the file adapter recognises export sets (full mix + numbered stems)
            src = [str(folder)] if len(files) > 1 else [str(folder / files[0][0])]
            res = api.import_files(self.app.proj(), src, mode="copy", actor=ACTOR)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        head = (api.history(self.app.proj(), limit=1).get("entries") or [{}])[-1]
        added = 0
        for r in res.get("imported") or []:
            a = r.get("assets_added") if isinstance(r, dict) else None
            added += len(a) if isinstance(a, list) else int(a or 0)
        return {"applied": added, "content_hash": head.get("after_hash"), "assets": res.get("assets"),
                "check_counts": res.get("check_counts"), "result": res}

    def h_history(self):
        limit = self._q("limit")
        try:
            n = int(limit) if limit is not None else 50
        except ValueError:
            raise InputError("limit must be an integer") from None
        res = api.history(self.app.proj(), limit=n)
        entries = [dict(e, summary=e.get("reason") or e.get("op")) for e in reversed(res.get("entries") or [])]
        return {"entries": entries, "count": len(entries), "order": "newest_first"}

    def h_undo(self):
        self._body()
        self.app.check_free()
        return api.undo(self.app.proj(), ACTOR)

    def h_objectives(self):
        return api.objective_list(full=True)

    def h_profiles(self):
        return api.profile_list(full=True)

    def h_deliveries(self):
        return api.delivery_list()

    def h_models(self):
        return api.model_list()

    def h_model_show(self, id: str):
        return api.model_show(id)

    def h_model_pull(self, id: str):
        b = self._body()
        allow = bool(b.get("allow_candidate", False))
        force = bool(b.get("force", False))
        return self.app.submit("model_pull", lambda: api.model_pull(id, allow_candidate=allow, force=force),
                               key="-models", args={"id": id})

    def h_variants(self):
        return api.variant_list(self.app.proj())["variants"]

    def h_analysis(self):
        return api.analysis_view(self.app.proj(), self._q("variant"))

    def h_analyze(self):
        b = self._body()
        proj, force = self.app.proj(), bool(b.get("force", False))
        return self.app.submit("analyze", lambda: api.analyze(proj, force=force, actor=ACTOR))

    def h_proposals(self):
        return api.proposal_list(self.app.proj(), variant=self._q("variant"), stage=self._q("stage"),
                                 status=self._q("status"))

    def h_proposal_get(self, id: str):
        return api.proposal_get(self.app.proj(), id)

    def h_plan_propose(self):
        b = self._body()
        proj = self.app.proj()
        kw = {k: b.get(k) for k in ("variant", "profile", "delivery", "objective", "max_iter") if b.get(k) is not None}
        stage = b.get("stage") or "master"

        def run():
            res = api.plan_propose(proj, stage, actor=ACTOR, **kw)
            return api.proposal_get(proj, res["proposal_id"])["view"]

        job = self.app.submit("plan_propose", run, args={"stage": stage, **kw})
        if b.get("async"):
            return job
        done = self.app.jobs.wait(job["job_id"])        # the GUI contract returns the Proposal itself
        if done.state == FAILED:
            err = done.error or {}
            self._json(http_status(_ErrorLike(err.get("error"))), err)
            return None
        return done.result

    def h_plan_apply(self):
        b = self._body()
        pid = b.get("proposal_id")
        if not isinstance(pid, str) or not pid:
            raise InputError("proposal_id is required")
        self.app.check_free()
        res = api.plan_apply(self.app.proj(), pid, edits=b.get("edits") or None, actor=ACTOR)
        return {**res, "content_hash": (res.get("project") or {}).get("content_hash")}

    def h_plan_reject(self):
        b = self._body()
        self.app.check_free()
        return api.plan_reject(self.app.proj(), b.get("proposal_id"), b.get("reason"), actor=ACTOR)

    def h_render(self):
        b = self._body()
        proj, variant = self.app.proj(), b.get("variant")
        outputs = b.get("outputs")
        args = {"variant": variant}
        if b.get("range"):
            # core render has no range preview yet: the full variant is rendered
            args["range_ignored"] = b.get("range")
        return self.app.submit("render", lambda: api.render(proj, variant, outputs=outputs), args=args)

    def h_export(self):
        b = self._body()
        proj, variant = self.app.proj(), b.get("variant")
        return self.app.submit("export", lambda: api.export(proj, variant), args={"variant": variant})

    def h_jobs(self):
        return {"jobs": [self.app.job_view(j) for j in self.app.jobs.list()]}

    def h_job(self, id: str):
        return self.app.job_view(self.app.jobs.get(id))

    def h_verify_get(self):
        return api.verification_get(self.app.proj(), self._q("variant"))

    def h_verify_run(self):
        b = self._body()
        proj, variant = self.app.proj(), b.get("variant")
        recheck = bool(b.get("recheck_codecs", False))

        def run():
            api.verify(proj, variant, recheck_codecs=recheck)
            return api.verification_get(proj, variant)

        return self.app.submit("verify", run, args={"variant": variant})

    def h_report(self):
        lang = self._q("lang") or "both"
        return api.report(self.app.proj(), self._q("variant"), lang=lang, write=False)["report"]

    def h_audio(self):
        res = api.audio_set(self.app.proj(), self._q("variant"))
        res["files"] = {k: self.app.file_url(v) for k, v in (res.get("files") or {}).items()}
        res["deltas"] = {k: self.app.file_url(v) for k, v in (res.get("deltas") or {}).items()}
        return res

    def h_separate(self):
        b = self._body()
        proj = self.app.proj()
        kw = {k: b.get(k) for k in ("model", "source", "mode", "stems", "device", "allow_candidate", "add_tracks",
                                    "excerpt_s") if b.get(k) is not None}
        return self.app.submit("separate", lambda: api.separate(proj, actor=ACTOR, **kw), args=kw)

    def h_separations(self):
        return api.separation_list(self.app.proj())

    def h_files(self, rel: str):
        proj = Path(self.app.proj())
        p = self.app.ws.resolve(str(proj / rel), what="file")       # PathEscape (403) outside the workspace
        if p != proj and not p.is_relative_to(proj):
            raise Forbidden("files are served from inside the project only")
        if any(part.startswith(".") for part in p.relative_to(proj).parts):
            raise NotFound(f"not found: {p.name}")
        if not p.is_file():
            raise NotFound(f"not found: {p.name}")
        self._file(p)

    def h_events(self):
        app = self.app
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        q = app.bus.subscribe()
        try:
            self.wfile.write(b"retry: 3000\n: connected\n\n")
            self.wfile.flush()
            last = time.monotonic()
            while not app.stopping.is_set():
                try:
                    event, data = q.get(timeout=min(1.0, app.ping_s))
                except queue.Empty:
                    if time.monotonic() - last >= app.ping_s:
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                        last = time.monotonic()
                    continue
                payload = json.dumps(app.scrub(data), ensure_ascii=False, allow_nan=False)
                self.wfile.write(f"event: {event}\ndata: {payload}\n\n".encode("utf-8"))
                self.wfile.flush()
                last = time.monotonic()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass
        finally:
            app.bus.unsubscribe(q)
        self.close_connection = True
        return None


class _ErrorLike(Exception):
    def __init__(self, code: str | None):
        super().__init__(code)
        self.code = code


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def parse_range(header: str, size: int) -> tuple[int, int] | str | None:
    """'bytes=a-b' / 'bytes=a-' / 'bytes=-n' -> (start, end); 'unsatisfiable'; None = ignore (send all)."""
    m = re.fullmatch(r"\s*bytes\s*=\s*(\d*)\s*-\s*(\d*)\s*", header or "")
    if m is None:
        return None                      # multiple ranges or another unit: send the whole file
    a, b = m.groups()
    if a == "" and b == "":
        return None
    if size <= 0:
        return "unsatisfiable"
    if a == "":
        n = int(b)
        if n == 0:
            return "unsatisfiable"
        return max(0, size - n), size - 1
    start = int(a)
    end = min(int(b), size - 1) if b else size - 1
    if start >= size or start > end:
        return "unsatisfiable"
    return start, end


_SAFE_NAME = re.compile(r"[^\w .()\-\[\]&+,']+", re.UNICODE)


def safe_filename(name: str | None, index: int) -> str:
    base = (name or "").replace("\\", "/").rsplit("/", 1)[-1].strip().strip(".")
    base = _SAFE_NAME.sub("_", base)[:200]
    return base or f"upload_{index}.bin"


def parse_multipart(content_type: str, body: bytes) -> list[tuple[str, bytes]]:
    """Files of a multipart/form-data body -> [(safe file name, bytes)] (field 'files' or any file field)."""
    head = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("latin-1")
    msg = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(head + body)
    if not msg.is_multipart():
        raise InputError("malformed multipart body")
    out: list[tuple[str, bytes]] = []
    seen: set[str] = set()
    for i, part in enumerate(msg.iter_parts()):
        fname = part.get_filename()
        if fname is None:
            continue
        name = safe_filename(fname, i)
        stem, suffix = os.path.splitext(name)
        n = 2
        while name.lower() in seen:
            name = f"{stem}_{n}{suffix}"
            n += 1
        seen.add(name.lower())
        out.append((name, part.get_payload(decode=True) or b""))
    return out


# ---------------------------------------------------------------------------
# server object
# ---------------------------------------------------------------------------

class _HTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False
    allow_reuse_address = False


class _HTTPServer6(_HTTPServer):
    address_family = socket.AF_INET6


class MankoServer:
    """The local GUI server. ``start()`` serves in a background thread (tests); ``serve_forever()`` blocks."""

    def __init__(self, root: str | os.PathLike[str] = ".", *, project: str | None = None, host: str = DEFAULT_HOST,
                 port: int = DEFAULT_PORT, static: str | None = None, allow_remote: bool = False,
                 poll_s: float = POLL_S, ping_s: float = PING_S):
        if not is_loopback(host) and not allow_remote:
            raise RemoteBindRefused(
                f"refusing to bind to non-loopback address '{host}': the server gives full access to the "
                "project and must stay local", details={"hint": "use 127.0.0.1, or pass --allow-remote if you "
                                                                "really want to expose it to your network"})
        if not isinstance(port, int) or not 0 <= port <= 65535:
            raise InputError(f"invalid port: {port}")
        self.app = App(root, project=project, static=static, host=host, allow_remote=allow_remote,
                       poll_s=poll_s, ping_s=ping_s)
        handler = type("BoundHandler", (Handler,), {"app": self.app})
        cls = _HTTPServer6 if ":" in host.strip("[]") else _HTTPServer
        try:
            self.httpd = cls((host.strip("[]"), port), handler)
        except OSError as e:
            raise EnvironmentProblem(f"cannot listen on {host}:{port}: {e.strerror or e}",
                                     details={"hint": "choose another --port (0 picks a free one)"}) from None
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        return int(self.httpd.server_address[1])

    @property
    def url(self) -> str:
        h = self.app.host
        h = f"[{h.strip('[]')}]" if ":" in h.strip("[]") else h
        return f"http://{h}:{self.port}"

    def info(self) -> dict:
        return {"serving": self.url + "/", "api": self.url + "/api", "root": ".",
                "project": self.app.ws.rel(self.app.project) if self.app.project else None,
                "gui": self.app.static is not None, "remote": self.app.allow_remote}

    def start(self) -> "MankoServer":
        self.app.start_background()
        self._thread = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.2},
                                        name="mankomix-http", daemon=True)
        self._thread.start()
        return self

    def serve_forever(self) -> None:
        self.app.start_background()
        self.httpd.serve_forever(poll_interval=0.5)

    def close(self) -> None:
        self.app.stop()
        try:
            self.httpd.shutdown()
        except Exception:  # noqa: BLE001
            pass
        self.httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def __enter__(self) -> "MankoServer":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.close()


def run_server(*, root: str | None = None, project: str | None = None, host: str = DEFAULT_HOST,
               port: int = DEFAULT_PORT, static: str | None = None, allow_remote: bool = False) -> int:
    """Entry point of `mankomix serve`: print one JSON line with the address, then serve until Ctrl+C."""
    if root is None:
        root, project = (project, ".") if project else (".", None)
    if not is_loopback(host) and allow_remote:
        sys.stderr.write(f"WARNING: serving on non-loopback address '{host}'. Anyone who can reach it can read "
                         "and change the project and its audio. Use only on a trusted network.\n")
        sys.stderr.flush()
    srv = MankoServer(root, project=project, host=host, port=port, static=static, allow_remote=allow_remote)
    sys.stdout.write(json.dumps(srv.info(), ensure_ascii=False) + "\n")
    sys.stdout.flush()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.close()
    return 0
