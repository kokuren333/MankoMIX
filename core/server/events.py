"""Change notifications for the GUI server (SPEC 9.5, 11.2; gui/API.md "Server-Sent Events").

``EventBus`` fans events out to every open ``/api/events`` stream. ``ProjectWatcher``
polls the project files about once a second, so changes made by any face (the GUI
itself, the CLI or an MCP agent in another process) reach the GUI the same way:

- ``project_changed``: project.json or journal.jsonl changed on disk; the payload is
  the newest journal entry (seq, actor, content hash, summary);
- ``proposal``: a proposal file under cache/proposals/ appeared or changed.

The watcher reads the project only through ``core.api`` (journal via ``api.history``,
proposals via ``api.proposal_list``).
"""

from __future__ import annotations

import logging
import queue
import threading
from pathlib import Path
from typing import Any

from mankomix.core import api
from mankomix.core.errors import MankoError

log = logging.getLogger("mankomix.server")

WATCHED_FILES = ("project.json", "journal.jsonl")


class EventBus:
    """Thread-safe fan-out of (event, data) pairs to subscriber queues."""

    def __init__(self, max_queue: int = 1000):
        self._subs: list[queue.Queue] = []
        self._lock = threading.Lock()
        self._max = max_queue

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=self._max)
        with self._lock:
            self._subs.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)

    def publish(self, event: str, data: dict) -> None:
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait((event, data))
            except queue.Full:      # a stalled client must not block the others
                pass

    @property
    def subscribers(self) -> int:
        with self._lock:
            return len(self._subs)


def _stat(p: Path) -> tuple[int, int] | None:
    try:
        st = p.stat()
    except OSError:
        return None
    return st.st_mtime_ns, st.st_size


class ProjectWatcher(threading.Thread):
    """Polls the project's canonical files and proposal folder; publishes change events."""

    def __init__(self, project: Path, bus: EventBus, *, interval_s: float = 1.0):
        super().__init__(name="mankomix-watcher", daemon=True)
        self.project = Path(project)
        self.bus = bus
        self.interval_s = interval_s
        self._stop_evt = threading.Event()
        self._files = self._snapshot_files()
        self._proposals = self._snapshot_proposals()

    def stop(self) -> None:
        self._stop_evt.set()

    def _snapshot_files(self) -> dict[str, Any]:
        return {name: _stat(self.project / name) for name in WATCHED_FILES}

    def _snapshot_proposals(self) -> dict[str, Any]:
        d = self.project / api.PROPOSAL_DIR
        if not d.is_dir():
            return {}
        return {p.name: _stat(p) for p in d.glob("*.json")}

    def run(self) -> None:
        while not self._stop_evt.wait(self.interval_s):
            try:
                self.check()
            except Exception:  # noqa: BLE001 - the watcher must keep running
                log.exception("project watcher check failed")

    def check(self) -> None:
        files = self._snapshot_files()
        if files != self._files:
            self._files = files
            self.bus.publish("project_changed", self._project_event())
        props = self._snapshot_proposals()
        if props != self._proposals:
            changed = {name for name, st in props.items() if self._proposals.get(name) != st}
            self._proposals = props
            if changed:
                self._publish_proposals(changed)

    def _project_event(self) -> dict:
        try:
            entries = api.history(str(self.project), limit=1).get("entries") or []
        except MankoError:
            entries = []
        if not entries:
            return {"seq": None, "actor": None, "content_hash": None, "summary": None}
        e = entries[-1]
        return {"seq": e.get("seq"), "actor": e.get("actor"), "op": e.get("op"),
                "content_hash": e.get("after_hash"), "summary": e.get("reason") or e.get("op")}

    def _publish_proposals(self, names: set[str]) -> None:
        try:
            views = api.proposal_list(str(self.project)).get("proposals") or []
        except MankoError:
            return
        for v in views:
            if f"{v.get('id')}.json" in names:
                self.bus.publish("proposal", {"proposal_id": v.get("id"), "author": v.get("author"),
                                              "stage": v.get("stage"), "status": v.get("status"),
                                              "variant": v.get("variant")})
