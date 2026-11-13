"""Background jobs for long-running MCP tools (SPEC 10.3).

A long tool called with ``async: true`` returns a job id at once; the work
runs in a worker thread and the agent polls ``job_status`` / ``job_result``.
At most one job runs per project at a time (the project file has its own
lock, but two analyses or renders of one project would only fight).
"""

from __future__ import annotations

import itertools
import logging
import threading
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable

from mankomix.core.errors import InputError, MankoError

log = logging.getLogger("mankomix.mcp")

QUEUED, RUNNING, SUCCEEDED, FAILED = "queued", "running", "succeeded", "failed"
FINISHED = (SUCCEEDED, FAILED)


class ProjectBusy(InputError):
    code = "project_busy"


class UnknownJob(InputError):
    code = "unknown_job"


@dataclass
class Job:
    id: str
    tool: str
    key: str                       # project key (workspace-relative project path)
    args: dict
    state: str = QUEUED
    created: float = field(default_factory=time.monotonic)
    started: float | None = None
    finished: float | None = None
    result: Any = None
    error: dict | None = None

    def status(self) -> dict:
        now = time.monotonic()
        out = {"job_id": self.id, "tool": self.tool, "project": self.key, "state": self.state}
        if self.started is not None:
            out["elapsed_s"] = round((self.finished or now) - self.started, 3)
        if self.error is not None:
            out["error"] = self.error.get("error")
        return out


class JobManager:
    def __init__(self, *, keep: int = 100, error_mapper: Callable[[BaseException], dict] | None = None):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        self._keep = keep
        self._map_error = error_mapper or _default_error

    def busy(self, key: str) -> Job | None:
        with self._lock:
            for j in self._jobs.values():
                if j.key == key and j.state not in FINISHED:
                    return j
        return None

    def check_free(self, key: str) -> None:
        j = self.busy(key)
        if j is not None:
            raise ProjectBusy(f"a job is already running for this project: {j.id} ({j.tool})",
                              details={"job_id": j.id, "tool": j.tool, "project": key})

    def submit(self, tool: str, key: str, args: dict, fn: Callable[[], Any]) -> Job:
        with self._lock:
            for j in self._jobs.values():
                if j.key == key and j.state not in FINISHED:
                    raise ProjectBusy(f"a job is already running for this project: {j.id} ({j.tool})",
                                      details={"job_id": j.id, "tool": j.tool, "project": key})
            job = Job(id=f"job_{next(self._ids):04d}", tool=tool, key=key, args=args)
            self._jobs[job.id] = job
            self._prune()
        t = threading.Thread(target=self._run, args=(job, fn), name=f"mankomix-{job.id}", daemon=True)
        t.start()
        return job

    def get(self, job_id: Any) -> Job:
        with self._lock:
            job = self._jobs.get(job_id) if isinstance(job_id, str) else None
        if job is None:
            raise UnknownJob(f"unknown job: {job_id}")
        return job

    def list(self) -> list[Job]:
        with self._lock:
            return list(self._jobs.values())

    def wait(self, job_id: str, timeout: float | None = None) -> Job:
        """Block until the job finished (used by tests and on shutdown)."""
        deadline = None if timeout is None else time.monotonic() + timeout
        job = self.get(job_id)
        while job.state not in FINISHED:
            if deadline is not None and time.monotonic() > deadline:
                break
            time.sleep(0.01)
        return job

    def _run(self, job: Job, fn: Callable[[], Any]) -> None:
        job.state, job.started = RUNNING, time.monotonic()
        try:
            job.result = fn()
            job.state = SUCCEEDED
        except BaseException as e:  # noqa: BLE001 - a worker must never die silently
            job.error = self._map_error(e)
            job.state = FAILED
            if not isinstance(e, MankoError):
                log.error("job %s failed:\n%s", job.id, traceback.format_exc())
        finally:
            job.finished = time.monotonic()

    def _prune(self) -> None:
        done = [j for j in self._jobs.values() if j.state in FINISHED]
        for j in done[: max(0, len(self._jobs) - self._keep)]:
            self._jobs.pop(j.id, None)


def _default_error(e: BaseException) -> dict:
    if isinstance(e, MankoError):
        return e.to_dict()
    return {"error": "internal_error", "message": f"{type(e).__name__}: {e}", "details": {}}
